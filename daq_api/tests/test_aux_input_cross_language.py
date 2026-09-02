"""Cross-language golden equality for Python, simulator, and portable C++."""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from thingdaq import (
    ADCBlock,
    AuxBankMode,
    DeviceState,
    GPIOBlock,
    InMemoryTransport,
    RateProfile,
    SimulatedDevice,
    Source,
    SyntheticGPIOPattern,
    ThingDAQ,
    synthetic_gpio_bank_bytes,
    synthetic_gpio_value,
)
from thingdaq._generated import protocol_v2_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_ORACLE = REPOSITORY_ROOT / "firmware/tests/aux_input_cross_language_oracle.cpp"

_PRIMARY_PORT_BITS = (10, 17, 16, 11, 0, 2, 1, 3)
_AUXILIARY_PORT_BITS = (23, 22, 17, 16, 26, 27, 24, 25)


def _independent_bank_formula(
    sample_index: int,
    pattern: SyntheticGPIOPattern,
) -> tuple[int, int]:
    if pattern is SyntheticGPIOPattern.ALL_ZERO:
        return 0, 0
    if pattern is SyntheticGPIOPattern.WALKING_BIT:
        return 1 << (sample_index % 8), 1 << ((sample_index + 3) % 8)
    if pattern is SyntheticGPIOPattern.COUNTER:
        return sample_index & 0xFF, (3 * sample_index + 0x55) & 0xFF
    return (
        0xAA if sample_index % 2 == 0 else 0x55,
        0x0F if sample_index % 2 == 0 else 0xF0,
    )


def _scatter(value: int, port_bits: tuple[int, ...]) -> int:
    return sum(
        ((value >> wire_bit) & 1) << port_bit
        for wire_bit, port_bit in enumerate(port_bits)
    )


class AuxiliaryInputCrossLanguageGoldenTests(unittest.TestCase):
    executable: Path
    temporary: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            raise unittest.SkipTest("g++ is required for cross-language tests")
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="thingdaq-aux-cross-language-"
        )
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.executable = Path(cls.temporary.name) / "aux-input-oracle"
        compiled = subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-O3",
                "-flto",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wconversion",
                "-Wsign-conversion",
                "-pedantic",
                "-fno-exceptions",
                "-fno-rtti",
                f"-I{FIRMWARE_SOURCE}",
                str(CPP_ORACLE),
                str(FIRMWARE_SOURCE / "variable_rate_scheduler.cpp"),
                "-o",
                str(cls.executable),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if compiled.returncode != 0:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def test_python_simulator_and_cpp_match_words_and_timestamps(self) -> None:
        query_rows: list[tuple[int, int, int, int, int, int, int]] = []
        expected_rows: list[tuple[int, int, int, int, str]] = []
        offsets = (0, 1, 7, 8, 255, 256)

        for profile in RateProfile:
            for pattern in SyntheticGPIOPattern:
                device = SimulatedDevice(gpio_pattern=pattern)
                transport = InMemoryTransport(
                    device,
                    read_chunk_size=23,
                    write_chunk_size=3,
                )
                with ThingDAQ.open(
                    transport,
                    strict=True,
                    synchronization_retry_delay=0,
                    synthetic_gpio_pattern=pattern,
                ) as daq:
                    configuration = daq.configure(
                        source=Source.SYNTHETIC,
                        aux_bank_mode=AuxBankMode.INPUT,
                        rate_profile=profile,
                    )
                    daq.start()
                    items = tuple(daq.blocks(4, timeout=0.5))
                    self.assertTrue(
                        all(isinstance(item, (ADCBlock, GPIOBlock)) for item in items)
                    )
                    adc_by_sequence = {
                        item.sequence: item
                        for item in items
                        if isinstance(item, ADCBlock)
                    }
                    gpio_blocks = tuple(
                        item for item in items if isinstance(item, GPIOBlock)
                    )
                    self.assertEqual({0, 1}, set(adc_by_sequence))
                    self.assertEqual(
                        (0, 1), tuple(block.sequence for block in gpio_blocks)
                    )

                    for gpio in gpio_blocks:
                        adc = adc_by_sequence[gpio.sequence]
                        selected_offsets = (*offsets, gpio.item_count - 1)
                        for ordinal, gpio_offset in enumerate(selected_offsets):
                            adc_offset = (
                                0,
                                1,
                                7,
                                255,
                                adc.item_count - 1,
                            )[ordinal % 5]
                            sample_index = gpio.first_sample_index + gpio_offset
                            primary, auxiliary = _independent_bank_formula(
                                sample_index,
                                pattern,
                            )
                            packed = primary | (auxiliary << 8)
                            label = (
                                f"{profile.name}/{pattern.value}/"
                                f"sequence={gpio.sequence}/offset={gpio_offset}"
                            )
                            with self.subTest(case=label):
                                self.assertEqual(
                                    (primary, auxiliary),
                                    synthetic_gpio_bank_bytes(sample_index, pattern),
                                )
                                self.assertEqual(
                                    packed,
                                    synthetic_gpio_value(
                                        sample_index,
                                        aux_bank_mode=AuxBankMode.INPUT,
                                        pattern=pattern,
                                    ),
                                )
                                self.assertEqual(packed, gpio.sample(gpio_offset))
                                payload_offset = 2 * gpio_offset
                                self.assertEqual(
                                    struct.pack("<H", packed),
                                    gpio.payload[payload_offset : payload_offset + 2],
                                )
                                pair_index = adc.first_pair_index + adc_offset
                                self.assertEqual(
                                    (
                                        (2 * pair_index) & 0x0FFF,
                                        (2 * pair_index + 1) & 0x0FFF,
                                    ),
                                    adc.pair(adc_offset),
                                )

                            primary_word = _scatter(primary, _PRIMARY_PORT_BITS)
                            auxiliary_word = _scatter(
                                auxiliary,
                                _AUXILIARY_PORT_BITS,
                            )
                            self.assertEqual(
                                primary_word,
                                primary_word & constants.PRIMARY_GPIO_CAPTURE_MASK,
                            )
                            self.assertEqual(
                                auxiliary_word,
                                auxiliary_word & constants.AUX_GPIO_CAPTURE_MASK,
                            )
                            query_rows.append(
                                (
                                    int(profile),
                                    primary_word,
                                    auxiliary_word,
                                    gpio.first_sample_ticks,
                                    gpio_offset,
                                    adc.first_sample_ticks,
                                    adc_offset,
                                )
                            )
                            adc0_ticks, adc1_ticks = adc.pair_ticks(adc_offset)
                            expected_rows.append(
                                (
                                    packed,
                                    gpio.sample_ticks(gpio_offset),
                                    adc0_ticks,
                                    adc1_ticks,
                                    label,
                                )
                            )
                    status = daq.validate_stream_health()
                    self.assertEqual(configuration, status.configuration)
                self.assertFalse(transport.is_open)
                self.assertIs(DeviceState.IDLE, device.state)

        encoded_input = "".join(
            " ".join(str(value) for value in row) + "\n" for row in query_rows
        )
        result = subprocess.run(
            [str(self.executable)],
            input=encoded_input,
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        observed_rows = tuple(
            tuple(int(value) for value in line.split())
            for line in result.stdout.splitlines()
        )
        self.assertEqual(len(expected_rows), len(observed_rows))
        self.assertEqual(224, len(observed_rows))
        for observed, expected in zip(observed_rows, expected_rows, strict=True):
            packed, gpio_ticks, adc0_ticks, adc1_ticks, label = expected
            with self.subTest(cpp_case=label):
                self.assertEqual(
                    (packed, gpio_ticks, adc0_ticks, adc1_ticks),
                    observed,
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
