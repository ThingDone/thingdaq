"""Focused tests for the isolated adaptive-RLE simulator and demonstration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from thingdaq import (
    ADCBlock,
    ConfigurationEncoding,
    DeviceCapabilityError,
    ExperimentalSourcePattern,
    FrameEncoding,
    GPIOBlock,
    ThingDAQ,
    count_rle_runs,
    synthetic_adc_payload,
    synthetic_gpio_payload,
)
from thingdaq._generated import protocol_constants as constants
from thingdaq.simulator import experimental_adc_payload, experimental_gpio_payload

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
EXAMPLE_PATH = PACKAGE_ROOT / "examples/rle_compression.py"


def _capture(
    pattern: ExperimentalSourcePattern,
    encoding: ConfigurationEncoding,
) -> tuple[ADCBlock, GPIOBlock, int]:
    with ThingDAQ.simulated_experimental(
        encoding=encoding,
        adc_pattern=pattern,
        gpio_pattern=pattern,
        read_chunk_size=19,
        write_chunk_size=3,
        strict=True,
    ) as daq:
        daq.configure(encoding=encoding)
        daq.start()
        blocks = list(daq.blocks(2))
        status = daq.validate_stream_health()
        daq.stop()
    adc, gpio = blocks
    if not isinstance(adc, ADCBlock) or not isinstance(gpio, GPIOBlock):
        raise TypeError("combined simulator did not alternate ADC then GPIO")
    return adc, gpio, status.data_framed_bytes_transmitted


class ExperimentalPatternTests(unittest.TestCase):
    def test_every_pattern_is_exact_deterministic_and_frame_sized(self) -> None:
        for pattern in ExperimentalSourcePattern:
            with self.subTest(pattern=pattern.value):
                first_adc = experimental_adc_payload(pattern)
                second_adc = experimental_adc_payload(pattern)
                first_gpio = experimental_gpio_payload(pattern)
                second_gpio = experimental_gpio_payload(pattern)

                self.assertEqual(first_adc, second_adc)
                self.assertEqual(first_gpio, second_gpio)
                self.assertEqual(constants.DATA_PAYLOAD_BYTES, len(first_adc))
                self.assertEqual(constants.DATA_PAYLOAD_BYTES, len(first_gpio))
                for offset in range(0, len(first_adc), constants.ADC_BYTES_PER_PAIR):
                    adc0 = int.from_bytes(first_adc[offset : offset + 2], "little")
                    adc1 = int.from_bytes(first_adc[offset + 2 : offset + 4], "little")
                    maximum_code = (1 << constants.ADC_RESOLUTION_BITS) - 1
                    self.assertLessEqual(adc0, maximum_code)
                    self.assertLessEqual(adc1, maximum_code)

    def test_patterns_cover_compressible_and_incompressible_run_shapes(self) -> None:
        compressible = {
            ExperimentalSourcePattern.CONSTANT,
            ExperimentalSourcePattern.LONG_HOLD,
            ExperimentalSourcePattern.SPARSE_TRANSITION,
            ExperimentalSourcePattern.SLOWLY_CHANGING,
        }
        for pattern in ExperimentalSourcePattern:
            with self.subTest(pattern=pattern.value):
                adc_runs = count_rle_runs(
                    experimental_adc_payload(pattern),
                    item_size=constants.ADC_BYTES_PER_PAIR,
                    max_items=constants.ADC_PAIRS_PER_FRAME,
                )
                gpio_runs = count_rle_runs(
                    experimental_gpio_payload(pattern),
                    item_size=1,
                    max_items=constants.GPIO_SAMPLES_PER_FRAME,
                )
                if pattern in compressible:
                    self.assertLess(
                        adc_runs * (2 + constants.ADC_BYTES_PER_PAIR),
                        constants.DATA_PAYLOAD_BYTES,
                    )
                    self.assertLess(
                        gpio_runs * 3,
                        constants.DATA_PAYLOAD_BYTES,
                    )
                elif pattern is ExperimentalSourcePattern.ALTERNATING:
                    self.assertEqual(constants.ADC_PAIRS_PER_FRAME, adc_runs)
                    self.assertEqual(constants.GPIO_SAMPLES_PER_FRAME, gpio_runs)
                else:
                    self.assertGreaterEqual(
                        adc_runs * (2 + constants.ADC_BYTES_PER_PAIR),
                        constants.DATA_PAYLOAD_BYTES,
                    )
                    self.assertGreaterEqual(
                        gpio_runs * 3,
                        constants.DATA_PAYLOAD_BYTES,
                    )


class ExperimentalSimulatorTests(unittest.TestCase):
    def test_default_simulator_remains_protocol_v1_with_original_formulas(self) -> None:
        with ThingDAQ.simulated(strict=True) as daq:
            info = daq.device_info
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(constants.PROTOCOL_VERSION, info.protocol_version)
            daq.configure()
            daq.start()
            adc, gpio = list(daq.blocks(2))
            self.assertIsInstance(adc, ADCBlock)
            self.assertIsInstance(gpio, GPIOBlock)
            assert isinstance(adc, ADCBlock)
            assert isinstance(gpio, GPIOBlock)
            self.assertEqual(synthetic_adc_payload(0), adc.payload)
            self.assertEqual(synthetic_gpio_payload(0), gpio.payload)
            self.assertIsNone(adc.encoding_diagnostics)
            self.assertIsNone(gpio.encoding_diagnostics)
            daq.stop()

        with self.assertRaises(DeviceCapabilityError):
            ThingDAQ.simulated(encoding=ConfigurationEncoding.RLE_AUTO)

    def test_raw_and_rle_auto_match_and_adapt_for_every_pattern(self) -> None:
        fallback_patterns = {
            ExperimentalSourcePattern.ALTERNATING,
            ExperimentalSourcePattern.HIGH_ENTROPY,
        }
        for pattern in ExperimentalSourcePattern:
            with self.subTest(pattern=pattern.value):
                raw_adc, raw_gpio, raw_wire_bytes = _capture(
                    pattern,
                    ConfigurationEncoding.RAW,
                )
                rle_adc, rle_gpio, selected_wire_bytes = _capture(
                    pattern,
                    ConfigurationEncoding.RLE_AUTO,
                )
                self.assertEqual(raw_adc.payload, rle_adc.payload)
                self.assertEqual(raw_gpio.payload, rle_gpio.payload)
                self.assertEqual(raw_adc.sequence, rle_adc.sequence)
                self.assertEqual(
                    raw_gpio.first_sample_ticks, rle_gpio.first_sample_ticks
                )
                self.assertEqual(2 * constants.DATA_FRAME_BYTES, raw_wire_bytes)

                diagnostics = (
                    rle_adc.encoding_diagnostics,
                    rle_gpio.encoding_diagnostics,
                )
                self.assertTrue(all(item is not None for item in diagnostics))
                selected = tuple(item for item in diagnostics if item is not None)
                self.assertEqual(
                    sum(item.encoded_frame_bytes for item in selected),
                    selected_wire_bytes,
                )
                expected_selector = (
                    FrameEncoding.RAW
                    if pattern in fallback_patterns
                    else FrameEncoding.RLE
                )
                self.assertEqual(
                    [expected_selector, expected_selector],
                    [item.frame_encoding for item in selected],
                )
                self.assertLessEqual(selected_wire_bytes, raw_wire_bytes)

    def test_experimental_surface_rejects_unknown_controls(self) -> None:
        with self.assertRaisesRegex(ValueError, "source pattern"):
            ThingDAQ.simulated_experimental(
                encoding=ConfigurationEncoding.RAW,
                adc_pattern="not-a-pattern",
            )
        with self.assertRaisesRegex(TypeError, "encoding"):
            ThingDAQ.simulated_experimental(encoding=True)


class CompressionExampleTests(unittest.TestCase):
    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        source_path = str(PACKAGE_ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (source_path, environment.get("PYTHONPATH")))
        )
        return environment

    def test_command_prints_per_stream_equality_and_fallback_evidence(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(EXAMPLE_PATH),
                "--frames-per-stream",
                "1",
                "--pattern",
                "constant",
                "--pattern",
                "alternating",
            ],
            cwd=REPOSITORY_ROOT,
            env=self._environment(),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("evidence=simulated", completed.stdout)
        self.assertIn(
            "pattern=constant stream=ADC frames=1",
            completed.stdout,
        )
        self.assertIn("rle_frames=1 fallback_frames=0", completed.stdout)
        self.assertIn(
            "pattern=alternating stream=GPIO frames=1",
            completed.stdout,
        )
        self.assertIn("rle_frames=0 fallback_frames=1", completed.stdout)
        self.assertEqual(4, completed.stdout.count("decoded_equal=true"))

    def test_requested_output_uses_shared_structured_reporter(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rle-demo-report-",
            dir=REPOSITORY_ROOT,
        ) as temporary:
            output = Path(temporary) / "demo"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EXAMPLE_PATH),
                    "--frames-per-stream",
                    "1",
                    "--pattern",
                    "constant",
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                env=self._environment(),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            json_path = output.with_suffix(".json")
            markdown_path = output.with_suffix(".md")
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

            self.assertEqual("INCONCLUSIVE", report["result"])
            self.assertEqual("simulated", report["evidence"][0]["level"])
            self.assertEqual("PASS", report["evidence"][0]["result"])
            self.assertIn(
                "encoded_wire_bytes", {metric["name"] for metric in report["metrics"]}
            )
            self.assertTrue(markdown.startswith("---\ntype: report\n"))
            self.assertIn("| **simulated** |", markdown)


if __name__ == "__main__":
    unittest.main()
