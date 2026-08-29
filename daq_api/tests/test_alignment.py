"""Focused tests for bounded cross-stream timestamp alignment."""

from __future__ import annotations

import unittest

from teensy_daq import (
    ADCBlock,
    AlignedInterval,
    AlignmentLoss,
    AlignmentLossReason,
    FrameFlag,
    GPIOBlock,
    Source,
    StreamGap,
    StreamMask,
    TeensyDAQ,
    TimestampAligner,
    TimestampAlignmentError,
    align_by_timestamp,
    synthetic_adc_payload,
    synthetic_gpio_payload,
)
from teensy_daq._generated import protocol_constants as constants


def _flags(sequence: int, source: Source) -> FrameFlag:
    flags = FrameFlag.EPOCH_START if sequence == 0 else FrameFlag.NONE
    if source is Source.SYNTHETIC:
        flags |= FrameFlag.SYNTHETIC
    return flags


def _adc(
    interval: int,
    *,
    run_id: int = 7,
    sequence: int | None = None,
    source: Source = Source.SYNTHETIC,
) -> ADCBlock:
    selected_sequence = interval if sequence is None else sequence
    ticks = interval * constants.FRAME_COVERAGE_TICKS
    return ADCBlock(
        run_id=run_id,
        sequence=selected_sequence,
        first_sample_ticks=ticks,
        payload=synthetic_adc_payload(ticks // constants.ADC_PAIR_PERIOD_TICKS),
        flags=_flags(selected_sequence, source),
    )


def _gpio(
    interval: int,
    *,
    run_id: int = 7,
    sequence: int | None = None,
    source: Source = Source.SYNTHETIC,
) -> GPIOBlock:
    selected_sequence = interval if sequence is None else sequence
    ticks = interval * constants.FRAME_COVERAGE_TICKS
    return GPIOBlock(
        run_id=run_id,
        sequence=selected_sequence,
        first_sample_ticks=ticks,
        payload=synthetic_gpio_payload(ticks // constants.GPIO_SAMPLE_PERIOD_TICKS),
        flags=_flags(selected_sequence, source),
    )


class AlignedIntervalTests(unittest.TestCase):
    def test_complete_interval_retains_views_identity_and_nominal_timebase(
        self,
    ) -> None:
        adc = _adc(0)
        gpio = _gpio(0)
        aligner = TimestampAligner(max_pending_intervals=2)

        self.assertEqual((), aligner.push(adc))
        outputs = aligner.push(gpio)

        self.assertEqual(1, len(outputs))
        interval = outputs[0]
        self.assertIsInstance(interval, AlignedInterval)
        assert isinstance(interval, AlignedInterval)
        self.assertIs(adc, interval.adc)
        self.assertIs(gpio, interval.gpio)
        self.assertTrue(interval.complete)
        self.assertEqual(StreamMask.NONE, interval.missing_streams)
        adc_payload_view = interval.adc_payload_view
        gpio_payload_view = interval.gpio_payload_view
        assert adc_payload_view is not None
        assert gpio_payload_view is not None
        self.assertIs(adc.payload, adc_payload_view.obj)
        self.assertIs(gpio.payload, gpio_payload_view.obj)
        self.assertEqual((0, 4), interval.adc_pair_ticks(0))
        self.assertEqual(6, interval.gpio_sample_ticks(3))
        self.assertEqual((0.0, 0.5e-6), interval.adc_pair_seconds(0))
        self.assertEqual(0.75e-6, interval.gpio_sample_seconds(3))
        self.assertEqual(constants.TIMESTAMP_HZ, interval.epoch.timestamp_hz)
        self.assertEqual(0, interval.epoch.start_ticks)
        self.assertIsNone(interval.epoch.external_latency_ticks)
        self.assertEqual(Source.SYNTHETIC, interval.source)

    def test_independent_block_models_expose_per_item_nominal_seconds(self) -> None:
        adc = _adc(1)
        gpio = _gpio(1)

        self.assertEqual(constants.TIMESTAMP_HZ, adc.timestamp_hz)
        self.assertEqual(constants.TIMESTAMP_HZ, gpio.timestamp_hz)
        self.assertEqual(
            adc.first_sample_ticks / constants.TIMESTAMP_HZ, adc.t0_seconds
        )
        self.assertEqual(
            gpio.first_sample_ticks / constants.TIMESTAMP_HZ, gpio.t0_seconds
        )
        self.assertEqual(
            tuple(tick / constants.TIMESTAMP_HZ for tick in adc.pair_ticks(2)),
            adc.pair_seconds(2),
        )
        self.assertEqual(
            gpio.sample_ticks(2) / constants.TIMESTAMP_HZ,
            gpio.sample_seconds(2),
        )
        self.assertEqual(
            next(adc.interleaved()).timestamp_ticks / constants.TIMESTAMP_HZ,
            next(adc.interleaved()).timestamp_seconds,
        )


class TimestampAlignerTests(unittest.TestCase):
    def test_raw_facade_delivery_stays_immediate_and_independently_typed(self) -> None:
        aligner = TimestampAligner()
        with TeensyDAQ.simulated() as daq:
            daq.configure(adc=True, gpio=True)
            daq.start()

            first = daq.read_block()
            second = daq.read_block()
            self.assertIsInstance(first, ADCBlock)
            self.assertIsInstance(second, GPIOBlock)
            assert isinstance(first, ADCBlock)
            assert isinstance(second, GPIOBlock)
            self.assertEqual((), aligner.push(first))
            aligned = aligner.push(second)

        self.assertEqual(1, len(aligned))
        interval = aligned[0]
        self.assertIsInstance(interval, AlignedInterval)
        assert isinstance(interval, AlignedInterval)
        self.assertIs(first, interval.adc)
        self.assertIs(second, interval.gpio)

    def test_bounded_window_accepts_out_of_order_intervals(self) -> None:
        aligner = TimestampAligner(max_pending_intervals=2)

        self.assertEqual((), aligner.push(_adc(1)))
        self.assertEqual((), aligner.push(_gpio(1)))
        self.assertEqual((), aligner.push(_gpio(0)))
        outputs = aligner.push(_adc(0))

        self.assertEqual(2, len(outputs))
        self.assertTrue(all(isinstance(item, AlignedInterval) for item in outputs))
        self.assertEqual(
            [0, constants.FRAME_COVERAGE_TICKS],
            [
                item.first_sample_ticks
                for item in outputs
                if isinstance(item, AlignedInterval)
            ],
        )
        self.assertEqual(0, aligner.pending_intervals)
        self.assertEqual(2, aligner.high_water_intervals)

    def test_window_expiry_emits_missing_side_and_source_gap_explicitly(self) -> None:
        aligner = TimestampAligner(max_pending_intervals=2)
        aligner.push(_adc(0))
        aligner.push(_adc(1))
        aligner.push(_gpio(1))

        outputs = aligner.push(_adc(2))

        self.assertEqual(
            [AlignmentLoss, AlignedInterval, StreamGap, AlignedInterval],
            [type(item) for item in outputs],
        )
        loss = outputs[0]
        first = outputs[1]
        gap = outputs[2]
        second = outputs[3]
        assert isinstance(loss, AlignmentLoss)
        assert isinstance(first, AlignedInterval)
        assert isinstance(gap, StreamGap)
        assert isinstance(second, AlignedInterval)
        self.assertEqual(AlignmentLossReason.WINDOW_EXPIRED, loss.reason)
        self.assertEqual(StreamMask.ADC, loss.present_streams)
        self.assertEqual(StreamMask.GPIO, loss.missing_streams)
        self.assertIsNotNone(first.adc)
        self.assertIsNone(first.gpio)
        self.assertEqual(constants.FrameKind.GPIO_DATA, gap.kind)
        self.assertEqual(constants.GPIO_SAMPLES_PER_FRAME, gap.missing_items)
        self.assertEqual((gap,), second.stream_gaps)
        self.assertLessEqual(
            aligner.high_water_intervals,
            aligner.max_pending_intervals,
        )

    def test_finite_helper_marks_fully_missing_ranges_and_final_partial_tail(
        self,
    ) -> None:
        outputs = list(
            align_by_timestamp(
                (_adc(2), _gpio(2), _adc(3)),
                max_pending_intervals=8,
            )
        )

        losses = [item for item in outputs if isinstance(item, AlignmentLoss)]
        intervals = [item for item in outputs if isinstance(item, AlignedInterval)]
        gaps = [item for item in outputs if isinstance(item, StreamGap)]
        self.assertEqual(2, len(losses))
        self.assertEqual(StreamMask.ADC | StreamMask.GPIO, losses[0].missing_streams)
        self.assertEqual(2, losses[0].interval_count)
        self.assertEqual(AlignmentLossReason.END_OF_INPUT, losses[0].reason)
        self.assertEqual(StreamMask.GPIO, losses[1].missing_streams)
        self.assertEqual(
            [2, 3],
            [
                item.first_sample_ticks // constants.FRAME_COVERAGE_TICKS
                for item in intervals
            ],
        )
        self.assertEqual(
            {constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA},
            {gap.kind for gap in gaps},
        )

    def test_run_boundary_flushes_without_pairing_across_epochs(self) -> None:
        aligner = TimestampAligner()
        run_one_adc = _adc(0, run_id=11)
        run_two_adc = _adc(0, run_id=12)
        run_two_gpio = _gpio(0, run_id=12)

        aligner.push(run_one_adc)
        boundary = aligner.push(run_two_adc)
        paired = aligner.push(run_two_gpio)

        self.assertEqual([AlignmentLoss, AlignedInterval], [type(x) for x in boundary])
        loss = boundary[0]
        old_interval = boundary[1]
        assert isinstance(loss, AlignmentLoss)
        assert isinstance(old_interval, AlignedInterval)
        self.assertEqual(AlignmentLossReason.RUN_BOUNDARY, loss.reason)
        self.assertEqual(11, old_interval.run_id)
        self.assertIsNone(old_interval.gpio)
        self.assertEqual(1, len(paired))
        new_interval = paired[0]
        assert isinstance(new_interval, AlignedInterval)
        self.assertEqual(12, new_interval.run_id)
        self.assertTrue(new_interval.complete)

    def test_source_change_duplicates_and_late_arrivals_are_rejected(self) -> None:
        aligner = TimestampAligner(max_pending_intervals=1)
        adc = _adc(0, source=Source.HARDWARE)
        aligner.push(adc)
        with self.assertRaisesRegex(TimestampAlignmentError, "source changed"):
            aligner.push(_gpio(0, source=Source.SYNTHETIC))

        duplicate_aligner = TimestampAligner()
        duplicate_aligner.push(_adc(0))
        with self.assertRaisesRegex(TimestampAlignmentError, "duplicate ADC"):
            duplicate_aligner.push(_adc(0))

        late_aligner = TimestampAligner()
        late_aligner.push(_adc(0))
        late_aligner.push(_gpio(0))
        with self.assertRaisesRegex(TimestampAlignmentError, "late or reordered"):
            late_aligner.push(_adc(0))


if __name__ == "__main__":
    unittest.main()
