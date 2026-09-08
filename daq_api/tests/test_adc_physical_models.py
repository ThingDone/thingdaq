"""Focused tests for physical ADC block metadata and status decoding."""

from __future__ import annotations

import itertools
import struct
import unittest
from dataclasses import replace

from thingdone_daq import (
    ADCBlock,
    AdcBlockMetadata,
    AdcCalibrationMetadata,
    AdcCalibrationState,
    AdcConfigurationFlag,
    AdcConverter,
    DAQConfiguration,
    DeviceState,
    FrameFlag,
    InMemoryTransport,
    SimulatedDevice,
    Source,
    Status,
    StreamGap,
    StreamMask,
    ThingDAQ,
    UnexpectedStreamValidationError,
)
from thingdone_daq._generated import protocol_constants as constants


def _payload(*pairs: tuple[int, int]) -> bytes:
    payload = bytearray(constants.ADC_DATA_PAYLOAD_SIZE)
    for index in range(constants.ADC_PAIRS_PER_FRAME):
        struct.pack_into(
            "<HH",
            payload,
            index * constants.ADC_BYTES_PER_PAIR,
            *pairs[index % len(pairs)],
        )
    return bytes(payload)


def _calibration(resolution_bits: int = 12) -> AdcCalibrationMetadata:
    resolution_flag = (
        AdcConfigurationFlag.PRIMARY_12_BIT
        if resolution_bits == constants.ADC_PRIMARY_RESOLUTION_BITS
        else AdcConfigurationFlag.FALLBACK_10_BIT
    )
    return AdcCalibrationMetadata(
        states=(
            AdcCalibrationState.SUCCEEDED,
            AdcCalibrationState.SUCCEEDED,
        ),
        cycles=(1200, 1300),
        configuration_flags=(
            AdcConfigurationFlag.INITIALIZED
            | AdcConfigurationFlag.NO_HARDWARE_AVERAGING
            | AdcConfigurationFlag.HIGH_SPEED
            | AdcConfigurationFlag.SHORTEST_SAMPLE
            | AdcConfigurationFlag.ROUTES_VALIDATED
            | AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
            | AdcConfigurationFlag.CALIBRATION_COMPLETE
            | resolution_flag
        ),
    )


class _GapFirstAdcDevice(SimulatedDevice):
    def _reset_epoch(self) -> None:
        super()._reset_epoch()
        self._adc_sequence = 1
        self._adc_first_ticks = constants.FRAME_COVERAGE_TICKS
        self._adc_item_index = constants.ADC_PAIRS_PER_FRAME


class PhysicalAdcBlockModelTests(unittest.TestCase):
    def test_raw_views_publish_zero_copy_layout_and_actual_timing(self) -> None:
        metadata = AdcBlockMetadata(
            source=Source.HARDWARE,
            calibration=_calibration(),
        )
        block = ADCBlock(
            run_id=9,
            sequence=4,
            first_sample_ticks=16,
            payload=_payload((4095, 7), (12, 3001)),
            flags=FrameFlag.EPOCH_START,
            metadata=metadata,
        )

        adc0_buffer = block.adc0.payload_view
        adc1_buffer = block.adc1.payload_view
        try:
            self.assertIs(block.payload, adc0_buffer.obj)
            self.assertIs(block.payload, adc1_buffer.obj)
        finally:
            adc0_buffer.release()
            adc1_buffer.release()
        self.assertEqual((0, 2), (block.adc0.byte_offset, block.adc1.byte_offset))
        self.assertEqual((4, 4), (block.adc0.byte_stride, block.adc1.byte_stride))
        self.assertEqual((4095, 12, 4095), block.adc0[:3])
        self.assertEqual((7, 3001, 7), block.adc1[:3])

        self.assertEqual(16, block.t0)
        self.assertEqual(8, block.pair_period)
        self.assertEqual(4, block.adc1_phase)
        self.assertEqual(12, block.resolution)
        self.assertEqual(4, block.sequence)
        self.assertEqual(9, block.run)
        self.assertEqual((0, 4095), block.code_range)
        self.assertTrue(block.calibration.ready)
        self.assertTrue(block.calibration.converter_ready(AdcConverter.ADC1))

        samples = tuple(itertools.islice(block.interleaved(), 4))
        self.assertEqual([4095, 7, 12, 3001], [item.code for item in samples])
        self.assertEqual([16, 20, 24, 28], [item.timestamp_ticks for item in samples])

    def test_raw_channel_and_interleave_views_cover_both_frame_boundaries(
        self,
    ) -> None:
        first_pair_index = 5
        first_tick = first_pair_index * constants.ADC_PAIR_PERIOD_TICKS
        block = ADCBlock(
            run_id=11,
            sequence=7,
            first_sample_ticks=first_tick,
            payload=_payload((1, 2), (3, 4)),
            metadata=AdcBlockMetadata(
                source=Source.HARDWARE,
                calibration=_calibration(),
            ),
        )

        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, len(block.adc0))
        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, len(block.adc1))
        self.assertEqual((1, 3, 1, 3), block.adc0[:4])
        self.assertEqual((2, 4, 2, 4), block.adc1[:4])
        self.assertEqual((3, 4), block.pair(-1))
        self.assertEqual(first_pair_index, block.first_pair_index)
        self.assertEqual(
            first_tick + constants.FRAME_COVERAGE_TICKS,
            block.end_tick_exclusive,
        )
        self.assertEqual(
            (first_tick, first_tick + constants.ADC1_PHASE_TICKS), block.pair_ticks(0)
        )

        last_adc0_tick = (
            first_tick
            + (constants.ADC_PAIRS_PER_FRAME - 1) * constants.ADC_PAIR_PERIOD_TICKS
        )
        self.assertEqual(
            (last_adc0_tick, last_adc0_tick + constants.ADC1_PHASE_TICKS),
            block.pair_ticks(-1),
        )
        merged = tuple(block.interleaved())
        self.assertEqual(2 * constants.ADC_PAIRS_PER_FRAME, len(merged))
        self.assertEqual(
            (AdcConverter.ADC0, AdcConverter.ADC1),
            (merged[0].converter, merged[1].converter),
        )
        self.assertEqual(
            (constants.ADC_PAIRS_PER_FRAME - 1,) * 2,
            (merged[-2].pair_index, merged[-1].pair_index),
        )
        self.assertEqual(
            (last_adc0_tick, last_adc0_tick + constants.ADC1_PHASE_TICKS),
            (merged[-2].timestamp_ticks, merged[-1].timestamp_ticks),
        )

    def test_payload_size_and_advertised_fallback_range_are_enforced(self) -> None:
        fallback = AdcBlockMetadata(
            source=Source.HARDWARE,
            resolution_bits=constants.ADC_FALLBACK_RESOLUTION_BITS,
            code_max=(1 << constants.ADC_FALLBACK_RESOLUTION_BITS) - 1,
            calibration=_calibration(constants.ADC_FALLBACK_RESOLUTION_BITS),
        )
        valid = ADCBlock(1, 0, 0, _payload((0, 1023), (512, 1)), metadata=fallback)
        self.assertEqual(10, valid.resolution_bits)
        self.assertEqual((0, 1023), valid.code_range)

        invalid = bytearray(valid.payload)
        struct.pack_into("<H", invalid, 2, 1024)
        with self.assertRaisesRegex(ValueError, "advertised 10-bit range"):
            ADCBlock(1, 0, 0, bytes(invalid), metadata=fallback)
        with self.assertRaisesRegex(ValueError, "exactly 1012"):
            ADCBlock(1, 0, 0, valid.payload[:-4], metadata=fallback)

        with self.assertRaisesRegex(ValueError, "flags disagree"):
            AdcBlockMetadata(
                source=Source.HARDWARE,
                resolution_bits=constants.ADC_FALLBACK_RESOLUTION_BITS,
                code_max=(1 << constants.ADC_FALLBACK_RESOLUTION_BITS) - 1,
                calibration=_calibration(constants.ADC_PRIMARY_RESOLUTION_BITS),
            )

    def test_gap_metadata_matches_the_following_frame_boundary(self) -> None:
        observed_sequence = 3
        observed_tick = 3 * constants.FRAME_COVERAGE_TICKS
        block = ADCBlock(
            run_id=13,
            sequence=observed_sequence,
            first_sample_ticks=observed_tick,
            payload=_payload((0, 1)),
            flags=FrameFlag.GAP_BEFORE | FrameFlag.OVERRUN_BEFORE,
            metadata=AdcBlockMetadata(
                source=Source.HARDWARE,
                calibration=_calibration(),
            ),
        )
        gap = StreamGap.from_expected(
            block,
            expected_sequence=1,
            expected_first_sample_ticks=constants.FRAME_COVERAGE_TICKS,
        )
        self.assertIsNotNone(gap)
        assert gap is not None
        attached = replace(block, gap=gap)
        self.assertIs(gap, attached.gap)
        self.assertEqual(2, gap.missing_frames)
        self.assertEqual(2 * constants.ADC_PAIRS_PER_FRAME, gap.missing_items)
        self.assertEqual(
            2 * constants.FRAME_COVERAGE_TICKS,
            gap.missing_duration_ticks,
        )
        self.assertTrue(gap.firmware_reported)
        self.assertTrue(gap.firmware_overrun)

        with self.assertRaisesRegex(ValueError, "does not describe this block"):
            replace(attached, sequence=observed_sequence + 1)

    def test_production_gap_is_attached_to_the_following_adc_block(self) -> None:
        transport = InMemoryTransport(_GapFirstAdcDevice())
        with ThingDAQ.open(transport) as daq:
            daq.configure(adc=True, gpio=False, source=Source.SYNTHETIC)
            run_id = daq.start()
            status = daq.status()

            gap = daq.read_block()
            block = daq.read_block()

            self.assertIsInstance(gap, StreamGap)
            self.assertIsInstance(block, ADCBlock)
            assert isinstance(gap, StreamGap)
            assert isinstance(block, ADCBlock)
            self.assertIs(gap, block.gap)
            self.assertTrue(block.gap_before)
            self.assertEqual(run_id, block.run)
            self.assertEqual(Source.SYNTHETIC, block.source)
            self.assertEqual(status.adc_acquisition, block.acquisition)
            self.assertEqual(constants.ADC_PAIRS_PER_FRAME, gap.missing_items)

    def test_strict_hardware_path_accepts_varying_codes_without_a_pattern(self) -> None:
        with ThingDAQ.simulated(strict=True) as daq:
            daq.configure(adc=True, gpio=False, source=Source.SYNTHETIC)
            run_id = daq.start()
            # Exercise the physical branch after the ordinary public lifecycle
            # has established the run and continuity expectations.
            daq._configuration = DAQConfiguration(
                StreamMask.ADC,
                Source.HARDWARE,
            )
            block = ADCBlock(
                run_id,
                0,
                0,
                _payload((3711, 2), (19, 4094), (888, 1234)),
                FrameFlag.EPOCH_START,
            )

            processed = daq._process_block(block)

            self.assertIsInstance(processed, ADCBlock)
            assert isinstance(processed, ADCBlock)
            self.assertEqual(Source.HARDWARE, processed.source)
            self.assertEqual((3711, 2), processed.pair(0))


class AdcAcquisitionStatusTests(unittest.TestCase):
    def test_status_round_trip_exposes_trigger_and_conversion_errors(self) -> None:
        status = Status(
            device_state=DeviceState.RUNNING,
            stream_mask=StreamMask.ADC,
            source=Source.HARDWARE,
            data_checksum_algorithm=constants.DEFAULT_CHECKSUM_ALGORITHM,
            adc0_dma_major_loops=11,
            adc1_dma_major_loops=10,
            adc0_dma_results=11 * constants.ADC_PAIRS_PER_FRAME,
            adc1_dma_results=10 * constants.ADC_PAIRS_PER_FRAME,
            adc_pairs_captured=11 * constants.ADC_PAIRS_PER_FRAME,
            adc_pairs_delivered=10 * constants.ADC_PAIRS_PER_FRAME,
            adc_incomplete_conversions=3,
            adc_overwritten_conversions=2,
            adc_raw_ready_depth=1,
            adc_raw_ready_high_water=3,
            adc_etc_error_events=1,
            adc_etc_error_flags=0x0001_0000,
            adc_dma_error_events=4,
        )

        decoded = Status.from_payload(status.to_payload())

        self.assertEqual(status, decoded)
        self.assertTrue(decoded.has_adc_errors)
        self.assertTrue(decoded.adc_acquisition.has_conversion_errors)
        self.assertIn(
            ("adc_incomplete_conversions", 3),
            decoded.adc_acquisition.nonzero_error_fields,
        )
        self.assertEqual(0x0001_0000, decoded.counters.adc_etc_error_flags)
        self.assertTrue(decoded.counters.has_loss)

    def test_strict_health_check_surfaces_physical_conversion_errors(self) -> None:
        with ThingDAQ.simulated(strict=True) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            status = replace(daq.status(), adc_incomplete_conversions=1)

            with self.assertRaises(UnexpectedStreamValidationError) as raised:
                daq.validate_stream_health(status)

            self.assertEqual("firmware_adc_errors", raised.exception.category)


if __name__ == "__main__":
    unittest.main()
