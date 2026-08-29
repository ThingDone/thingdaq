"""Tests for typed protocol models and deterministic source semantics."""

from __future__ import annotations

import itertools
import struct
import unittest
from collections.abc import Sequence
from pathlib import Path

from teensy_daq import (
    AdcBlock,
    AdcChannelView,
    AdcConverter,
    CommandResponse,
    Configuration,
    DAQConfiguration,
    DeviceState,
    FrameFlag,
    GpioBlock,
    GpioChannelView,
    Info,
    Source,
    Status,
    StreamGap,
    StreamMask,
    decode_frame,
    decode_message,
    extract_gpio_channel,
    interleave_adc,
    synthetic_adc0_code,
    synthetic_adc1_code,
    synthetic_adc_payload,
    synthetic_gpio_byte,
    synthetic_gpio_payload,
)
from teensy_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"


def _message(name: str) -> object:
    return decode_message(decode_frame((FIXTURE_DIRECTORY / name).read_bytes()))


class TypedControlModelTests(unittest.TestCase):
    def test_info_configuration_and_status_fixtures_decode_to_typed_values(
        self,
    ) -> None:
        info_response = _message("info-response.bin")
        configure_response = _message("configure-response.bin")
        status_response = _message("get-status-response.bin")

        self.assertIsInstance(info_response, CommandResponse)
        self.assertIsInstance(configure_response, CommandResponse)
        self.assertIsInstance(status_response, CommandResponse)
        assert isinstance(info_response, CommandResponse)
        assert isinstance(configure_response, CommandResponse)
        assert isinstance(status_response, CommandResponse)
        self.assertTrue(info_response.ok)
        self.assertEqual(1, info_response.request_id)
        self.assertIsInstance(info_response.value, Info)
        assert isinstance(info_response.value, Info)
        self.assertEqual("synthetic-golden-v1", info_response.value.build_id)
        self.assertEqual(constants.GPIO_PINS_BY_BIT, info_response.value.gpio_pin_map)
        self.assertTrue(info_response.value.supports_source(Source.SYNTHETIC))
        for source in (Source.HARDWARE, Source.SYNTHETIC):
            for streams in (
                StreamMask.ADC,
                StreamMask.GPIO,
                StreamMask.ADC | StreamMask.GPIO,
            ):
                self.assertTrue(
                    info_response.value.capabilities.supports_configuration(
                        DAQConfiguration(streams, source)
                    )
                )
        self.assertEqual(1012, info_response.value.adc_pairs_per_buffer)
        self.assertEqual(16256, info_response.value.adc_dma_ring_bytes)
        self.assertEqual(200, info_response.value.packet_buffer_count)

        self.assertIsInstance(configure_response.value, Configuration)
        assert isinstance(configure_response.value, Configuration)
        self.assertEqual(
            StreamMask.ADC | StreamMask.GPIO, configure_response.value.stream_mask
        )
        self.assertEqual(Source.SYNTHETIC, configure_response.value.source)

        self.assertIsInstance(status_response.value, Status)
        assert isinstance(status_response.value, Status)
        self.assertEqual(DeviceState.RUNNING, status_response.value.device_state)
        self.assertEqual(1, status_response.value.adc_frames_emitted)
        self.assertEqual(1, status_response.value.gpio_frames_emitted)
        self.assertEqual(0, status_response.value.adc_items_dropped)
        self.assertEqual(1234, status_response.value.gpio_processing_cpu_basis_points)
        self.assertEqual(1012, status_response.value.adc_items_generated)
        self.assertEqual(4048, status_response.value.gpio_items_generated)
        self.assertEqual(8096, status_response.value.data_payload_bytes_transmitted)
        self.assertEqual(8192, status_response.value.data_framed_bytes_transmitted)
        self.assertEqual(2, status_response.value.packet_ready_high_water)
        self.assertEqual(4, status_response.value.commands_accepted)
        self.assertEqual(1, status_response.value.usb_command_queue_high_water)

    def test_typed_payload_models_round_trip_the_golden_payloads(self) -> None:
        info_frame = decode_frame(
            (FIXTURE_DIRECTORY / "info-response.bin").read_bytes()
        )
        config_frame = decode_frame(
            (FIXTURE_DIRECTORY / "configure-response.bin").read_bytes()
        )
        status_frame = decode_frame(
            (FIXTURE_DIRECTORY / "get-status-response.bin").read_bytes()
        )

        self.assertEqual(
            info_frame.payload, Info.from_payload(info_frame.payload).to_payload()
        )
        self.assertEqual(
            config_frame.payload[4:],
            Configuration.from_payload(config_frame.payload[4:]).to_payload(),
        )
        self.assertEqual(
            status_frame.payload,
            Status.from_payload(status_frame.payload).to_payload(),
        )


class DataBlockModelTests(unittest.TestCase):
    def test_adc_views_and_explicit_interleaving_preserve_converter_identity(
        self,
    ) -> None:
        block = _message("adc-data.bin")
        self.assertIsInstance(block, AdcBlock)
        assert isinstance(block, AdcBlock)

        self.assertIsInstance(block.adc0, AdcChannelView)
        self.assertIsInstance(block.adc0, Sequence)
        self.assertEqual((0, 2, 4, 6), block.adc0[:4])
        self.assertEqual((1, 3, 5, 7), block.adc1[:4])
        self.assertEqual((2022, 2023), block.pair(-1))
        self.assertEqual((0, 4), block.pair_ticks(0))
        self.assertEqual(constants.FRAME_COVERAGE_TICKS, block.end_tick_exclusive)

        samples = list(itertools.islice(interleave_adc(block), 4))
        self.assertEqual(
            [AdcConverter.ADC0, AdcConverter.ADC1] * 2,
            [sample.converter for sample in samples],
        )
        self.assertEqual(["A0", "A1", "A0", "A1"], [sample.pin for sample in samples])
        self.assertEqual([0, 4, 8, 12], [sample.timestamp_ticks for sample in samples])
        self.assertEqual([0, 1, 2, 3], [sample.code for sample in samples])

    def test_gpio_extraction_is_lazy_and_uses_d6_through_d13_bit_order(self) -> None:
        block = _message("gpio-data.bin")
        self.assertIsInstance(block, GpioBlock)
        assert isinstance(block, GpioBlock)

        d6 = extract_gpio_channel(block, 6)
        d13 = block.channel(13)
        self.assertIsInstance(d6, GpioChannelView)
        self.assertEqual((False, True, False, True), d6[:4])
        self.assertEqual((False, False, False, False), d13[:4])
        self.assertTrue(d13[128])
        self.assertEqual(8094, block.sample_ticks(-1))
        self.assertEqual(constants.FRAME_COVERAGE_TICKS, block.end_tick_exclusive)
        self.assertEqual(bytes(range(8)), bytes(block.samples[:8]))

    def test_interleave_endpoints_and_every_gpio_bit_keep_timing_and_identity(
        self,
    ) -> None:
        adc = _message("adc-data.bin")
        self.assertIsInstance(adc, AdcBlock)
        assert isinstance(adc, AdcBlock)
        last_pair = adc.item_count - 1
        tail = list(
            itertools.islice(interleave_adc(adc), 2 * last_pair, 2 * adc.item_count)
        )

        self.assertEqual(
            [AdcConverter.ADC0, AdcConverter.ADC1],
            [sample.converter for sample in tail],
        )
        self.assertEqual(["A0", "A1"], [sample.pin for sample in tail])
        self.assertEqual(
            [
                last_pair * constants.ADC_PAIR_PERIOD_TICKS,
                last_pair * constants.ADC_PAIR_PERIOD_TICKS
                + constants.ADC1_PHASE_TICKS,
            ],
            [sample.timestamp_ticks for sample in tail],
        )
        self.assertEqual([2022, 2023], [sample.code for sample in tail])

        packed = bytearray(constants.GPIO_DATA_PAYLOAD_SIZE)
        for bit in range(len(constants.GPIO_PINS_BY_BIT)):
            packed[bit] = 1 << bit
        gpio = GpioBlock(1, 0, 0, bytes(packed), FrameFlag.EPOCH_START)
        for bit, pin in enumerate(constants.GPIO_PINS_BY_BIT):
            with self.subTest(pin=pin, bit=bit):
                channel = extract_gpio_channel(gpio, pin)
                self.assertEqual(bit, channel.bit)
                self.assertTrue(channel[bit])
                self.assertEqual(1, sum(channel[: len(constants.GPIO_PINS_BY_BIT)]))
                self.assertEqual(
                    constants.GPIO_SAMPLE_PERIOD_TICKS * bit,
                    gpio.sample_ticks(bit),
                )

    def test_stream_gap_counts_logical_items_and_handles_sequence_wrap(self) -> None:
        payload = synthetic_adc_payload(0)
        previous = AdcBlock(7, 0, 0, payload, FrameFlag.EPOCH_START)
        current = AdcBlock(
            7,
            2,
            2 * constants.FRAME_COVERAGE_TICKS,
            payload,
            FrameFlag.GAP_BEFORE,
        )

        gap = StreamGap.between(previous, current)

        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(1, gap.missing_frames)
        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, gap.missing_items)
        self.assertEqual(constants.FRAME_COVERAGE_TICKS, gap.missing_duration_ticks)

        before_wrap = AdcBlock(7, constants.UINT32_MAX, 0, payload)
        after_wrap = AdcBlock(
            7,
            0,
            constants.FRAME_COVERAGE_TICKS,
            payload,
        )
        self.assertIsNone(StreamGap.between(before_wrap, after_wrap))


class SyntheticPatternTests(unittest.TestCase):
    def test_adc_formulas_wrap_modulo_code_range_without_mixing_channels(self) -> None:
        self.assertEqual(4094, synthetic_adc0_code(2047))
        self.assertEqual(4095, synthetic_adc1_code(2047))
        self.assertEqual(0, synthetic_adc0_code(2048))
        self.assertEqual(1, synthetic_adc1_code(2048))

    def test_synthetic_payloads_match_cross_language_golden_vectors(self) -> None:
        adc_wire = (FIXTURE_DIRECTORY / "adc-data.bin").read_bytes()
        gpio_wire = (FIXTURE_DIRECTORY / "gpio-data.bin").read_bytes()
        adc_frame = decode_frame(adc_wire)
        gpio_frame = decode_frame(gpio_wire)

        self.assertEqual(adc_frame.payload, synthetic_adc_payload(0))
        self.assertEqual(gpio_frame.payload, synthetic_gpio_payload(0))
        self.assertEqual(
            [254, 255, 0, 1], [synthetic_gpio_byte(n) for n in range(254, 258)]
        )

    def test_payload_builders_apply_the_formulas_at_every_offset(self) -> None:
        first_pair = 2046
        adc_payload = synthetic_adc_payload(first_pair)
        adc_pairs = tuple(struct.iter_unpack("<HH", adc_payload))
        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, len(adc_pairs))
        self.assertEqual(
            tuple(
                (
                    synthetic_adc0_code(first_pair + offset),
                    synthetic_adc1_code(first_pair + offset),
                )
                for offset in range(constants.ADC_PAIRS_PER_FRAME)
            ),
            adc_pairs,
        )

        first_gpio_sample = 254
        gpio_payload = synthetic_gpio_payload(first_gpio_sample)
        self.assertEqual(constants.GPIO_SAMPLES_PER_FRAME, len(gpio_payload))
        self.assertEqual(
            bytes(
                synthetic_gpio_byte(first_gpio_sample + offset)
                for offset in range(constants.GPIO_SAMPLES_PER_FRAME)
            ),
            gpio_payload,
        )


if __name__ == "__main__":
    unittest.main()
