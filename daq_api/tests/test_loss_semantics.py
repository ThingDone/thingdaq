"""Focused Phase 09 host loss classification and reconciliation tests."""

from __future__ import annotations

import time
import unittest

from thingdaq import (
    ADCBlock,
    FrameFlag,
    FrameKind,
    HostQueueLoss,
    InMemoryTransport,
    SimulatedDevice,
    Source,
    StreamAnomaly,
    StreamAnomalyReason,
    StreamGap,
    ThingDAQ,
    UnexpectedStreamAnomalyError,
    UnexpectedStreamGapError,
    analyze_stream_continuity,
    decode_frame,
    encode_frame,
    synthetic_adc_payload,
)
from thingdaq._generated import protocol_constants as constants


def _adc(
    sequence: int,
    *,
    run_id: int = 7,
    ticks: int | None = None,
    flags: FrameFlag = FrameFlag.SYNTHETIC,
) -> ADCBlock:
    return ADCBlock(
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=(
            sequence * constants.FRAME_COVERAGE_TICKS if ticks is None else ticks
        ),
        payload=synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME),
        flags=flags,
    )


class _DuplicateDevice(SimulatedDevice):
    def __init__(self) -> None:
        super().__init__()
        self._first_adc: bytes | None = None
        self._duplicated = False

    def next_data_frame(self) -> bytes | None:
        if self._first_adc is not None and not self._duplicated:
            self._duplicated = True
            return self._first_adc
        wire = super().next_data_frame()
        if wire is not None and self._first_adc is None:
            self._first_adc = wire
        return wire


class _CounterMismatchDevice(SimulatedDevice):
    """Skip ADC sequence one but deliberately leave loss counters at zero."""

    def __init__(self) -> None:
        super().__init__()
        self._injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None:
            return None
        frame = decode_frame(wire)
        if (
            not self._injected
            and frame.header.kind is FrameKind.ADC_DATA
            and frame.header.sequence == 1
        ):
            self._injected = True
            replacement = super().next_data_frame()
            assert replacement is not None
            frame = decode_frame(replacement)
            return encode_frame(
                frame.header.kind,
                frame.payload,
                flags=(
                    frame.header.flags | FrameFlag.GAP_BEFORE | FrameFlag.OVERRUN_BEFORE
                ),
                checksum_algorithm=frame.header.checksum_algorithm,
                run_id=frame.header.run_id,
                sequence=frame.header.sequence,
                first_sample_ticks=frame.header.first_sample_ticks,
                item_count=frame.header.item_count,
            )
        return wire


class _OneGapDevice(SimulatedDevice):
    """Inject one fully reconciled first-run gap, then remain continuous."""

    def __init__(self) -> None:
        super().__init__()
        self._injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None:
            return None
        frame = decode_frame(wire)
        if (
            not self._injected
            and frame.header.kind is FrameKind.ADC_DATA
            and frame.header.sequence == 1
        ):
            self._injected = True
            self._adc_items_dropped += constants.ADC_PAIRS_PER_FRAME
            replacement = super().next_data_frame()
            assert replacement is not None
            frame = decode_frame(replacement)
            return encode_frame(
                frame.header.kind,
                frame.payload,
                flags=(
                    frame.header.flags | FrameFlag.GAP_BEFORE | FrameFlag.OVERRUN_BEFORE
                ),
                checksum_algorithm=frame.header.checksum_algorithm,
                run_id=frame.header.run_id,
                sequence=frame.header.sequence,
                first_sample_ticks=frame.header.first_sample_ticks,
                item_count=frame.header.item_count,
            )
        return wire


class _StaleAfterStartTransport(InMemoryTransport):
    def __init__(self) -> None:
        super().__init__()
        self._injected = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        request = decode_frame(bytes(data))
        written = super().write(data)
        if request.header.kind is FrameKind.START_REQUEST and not self._injected:
            self._injected = True
            stale = encode_frame(
                FrameKind.ADC_DATA,
                synthetic_adc_payload(0),
                flags=FrameFlag.SYNTHETIC | FrameFlag.EPOCH_START,
                run_id=constants.UINT32_MAX,
                sequence=0,
                first_sample_ticks=0,
                item_count=constants.ADC_PAIRS_PER_FRAME,
            )
            with self._lock:
                self._pending.extend(stale)
        return written


class ContinuityClassificationTests(unittest.TestCase):
    def test_missing_duplicate_reordered_timestamp_and_wrap_are_distinct(self) -> None:
        missing = analyze_stream_continuity(
            _adc(
                2,
                flags=(
                    FrameFlag.SYNTHETIC
                    | FrameFlag.GAP_BEFORE
                    | FrameFlag.OVERRUN_BEFORE
                ),
            ),
            expected_sequence=1,
            expected_first_sample_ticks=constants.FRAME_COVERAGE_TICKS,
            active_run_id=7,
            previous_sequence=0,
        )
        self.assertIsInstance(missing, StreamGap)
        assert isinstance(missing, StreamGap)
        self.assertEqual(Source.SYNTHETIC, missing.source)
        self.assertEqual(0, missing.previous_sequence)
        self.assertEqual(1, missing.missing_frames)
        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, missing.missing_items)
        self.assertEqual(
            missing.sequence_inferred_items,
            missing.missing_items,
        )
        self.assertEqual(
            constants.FRAME_COVERAGE_TICKS,
            missing.missing_end_ticks - missing.missing_start_ticks,
        )

        duplicate = analyze_stream_continuity(
            _adc(0),
            expected_sequence=1,
            expected_first_sample_ticks=constants.FRAME_COVERAGE_TICKS,
            active_run_id=7,
            previous_sequence=0,
        )
        reordered = analyze_stream_continuity(
            _adc(0),
            expected_sequence=2,
            expected_first_sample_ticks=2 * constants.FRAME_COVERAGE_TICKS,
            active_run_id=7,
            previous_sequence=1,
        )
        bad_time = analyze_stream_continuity(
            _adc(1, ticks=constants.FRAME_COVERAGE_TICKS + 8),
            expected_sequence=1,
            expected_first_sample_ticks=constants.FRAME_COVERAGE_TICKS,
            active_run_id=7,
            previous_sequence=0,
        )
        wrapped_clean = analyze_stream_continuity(
            _adc(0, ticks=1234),
            expected_sequence=0,
            expected_first_sample_ticks=1234,
            active_run_id=7,
            previous_sequence=constants.UINT32_MAX,
        )
        wrapped_gap = analyze_stream_continuity(
            _adc(
                0,
                ticks=constants.FRAME_COVERAGE_TICKS,
                flags=(
                    FrameFlag.SYNTHETIC
                    | FrameFlag.GAP_BEFORE
                    | FrameFlag.OVERRUN_BEFORE
                ),
            ),
            expected_sequence=constants.UINT32_MAX,
            expected_first_sample_ticks=0,
            active_run_id=7,
            previous_sequence=constants.UINT32_MAX - 1,
        )
        initial_reverse = analyze_stream_continuity(
            _adc(constants.UINT32_MAX),
            expected_sequence=0,
            expected_first_sample_ticks=0,
            active_run_id=7,
        )

        self.assertIsInstance(duplicate, StreamAnomaly)
        self.assertIsInstance(reordered, StreamAnomaly)
        self.assertIsInstance(bad_time, StreamAnomaly)
        assert isinstance(duplicate, StreamAnomaly)
        assert isinstance(reordered, StreamAnomaly)
        assert isinstance(bad_time, StreamAnomaly)
        self.assertEqual(StreamAnomalyReason.DUPLICATE, duplicate.reason)
        self.assertEqual(StreamAnomalyReason.REORDERED, reordered.reason)
        self.assertEqual(
            StreamAnomalyReason.TIMESTAMP_INCONSISTENT,
            bad_time.reason,
        )
        self.assertIsNone(wrapped_clean)
        self.assertIsInstance(wrapped_gap, StreamGap)
        assert isinstance(wrapped_gap, StreamGap)
        self.assertEqual(constants.UINT32_MAX, wrapped_gap.expected_sequence)
        self.assertEqual(0, wrapped_gap.observed_sequence)
        self.assertEqual(1, wrapped_gap.missing_frames)
        self.assertIsInstance(initial_reverse, StreamAnomaly)
        assert isinstance(initial_reverse, StreamAnomaly)
        self.assertEqual(StreamAnomalyReason.REORDERED, initial_reverse.reason)

    def test_sequence_and_timestamp_missing_counts_must_agree(self) -> None:
        bad = analyze_stream_continuity(
            _adc(2, ticks=3 * constants.FRAME_COVERAGE_TICKS),
            expected_sequence=1,
            expected_first_sample_ticks=constants.FRAME_COVERAGE_TICKS,
            active_run_id=7,
            previous_sequence=0,
        )
        self.assertIsInstance(bad, StreamAnomaly)
        assert isinstance(bad, StreamAnomaly)
        self.assertEqual(StreamAnomalyReason.TIMESTAMP_INCONSISTENT, bad.reason)
        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, bad.sequence_inferred_items)
        self.assertEqual(
            2 * constants.ADC_PAIRS_PER_FRAME,
            bad.timestamp_inferred_items,
        )
        self.assertIsNotNone(bad.firmware_evidence)
        assert bad.firmware_evidence is not None
        self.assertFalse(bad.firmware_evidence.flags_match)
        self.assertTrue(bad.firmware_evidence.errors)


class PublicLossRecoveryTests(unittest.TestCase):
    def test_duplicate_is_reported_then_discarded_in_continuing_mode(self) -> None:
        with ThingDAQ.open(InMemoryTransport(_DuplicateDevice())) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            first = daq.read_block()
            duplicate = daq.read_block()
            following = daq.read_block()

        self.assertIsInstance(first, ADCBlock)
        self.assertIsInstance(duplicate, StreamAnomaly)
        assert isinstance(duplicate, StreamAnomaly)
        self.assertEqual(StreamAnomalyReason.DUPLICATE, duplicate.reason)
        self.assertIsInstance(following, ADCBlock)
        assert isinstance(following, ADCBlock)
        self.assertEqual(1, following.sequence)

    def test_duplicate_raises_promptly_in_strict_mode(self) -> None:
        with ThingDAQ.open(InMemoryTransport(_DuplicateDevice()), strict=True) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            with self.assertRaises(UnexpectedStreamAnomalyError) as raised:
                daq.read_block()

        self.assertEqual(StreamAnomalyReason.DUPLICATE, raised.exception.anomaly.reason)

    def test_stale_run_is_visible_without_entering_the_application_queue(self) -> None:
        with ThingDAQ.open(_StaleAfterStartTransport()) as daq:
            daq.configure(adc=True, gpio=False)
            run_id = daq.start()
            deadline = time.monotonic() + 1.0
            while daq.reader_counters.stale_blocks_discarded == 0:
                if time.monotonic() >= deadline:
                    self.fail("reader did not observe the injected stale frame")
                time.sleep(0.001)
            stale = daq.read_block()
            current = daq.read_block()

        self.assertIsInstance(stale, StreamAnomaly)
        assert isinstance(stale, StreamAnomaly)
        self.assertEqual(StreamAnomalyReason.STALE_RUN, stale.reason)
        self.assertEqual(constants.UINT32_MAX, stale.observed_run_id)
        self.assertEqual(run_id, stale.active_run_id)
        self.assertIsInstance(current, ADCBlock)
        assert isinstance(current, ADCBlock)
        self.assertEqual(run_id, current.run_id)
        self.assertEqual(0, current.sequence)

    def test_counter_disagreement_remains_explicit_on_the_gap(self) -> None:
        with ThingDAQ.open(InMemoryTransport(_CounterMismatchDevice())) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            gap = daq.read_block()
            block = daq.read_block()
            losses = daq.loss_counters(refresh=False)

        self.assertIsInstance(gap, StreamGap)
        assert isinstance(gap, StreamGap)
        self.assertIsInstance(block, ADCBlock)
        evidence = gap.firmware_evidence
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertTrue(evidence.flags_match)
        self.assertFalse(evidence.counters_match)
        self.assertEqual(
            constants.ADC_PAIRS_PER_FRAME, evidence.expected_cumulative_items
        )
        self.assertEqual(0, evidence.cumulative_dropped_items)
        self.assertTrue(evidence.errors)
        self.assertEqual(1, losses.protocol_telemetry_errors)

    def test_strict_gap_exception_retains_counter_disagreement(self) -> None:
        with ThingDAQ.open(
            InMemoryTransport(_CounterMismatchDevice()), strict=True
        ) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            with self.assertRaises(UnexpectedStreamGapError) as raised:
                daq.read_block()

        evidence = raised.exception.gap.firmware_evidence
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertFalse(evidence.counters_match)
        self.assertTrue(evidence.errors)

    def test_new_start_and_reset_stats_do_not_join_run_baselines(self) -> None:
        with ThingDAQ.open(InMemoryTransport(_OneGapDevice())) as daq:
            daq.configure(adc=True, gpio=False)
            first_run = daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            self.assertIsInstance(daq.read_block(), StreamGap)
            self.assertIsInstance(daq.read_block(), ADCBlock)
            daq.stop()
            generation = daq.reset_stats()
            daq.configure(adc=True, gpio=False)
            second_run = daq.start()
            first_second_run = daq.read_block()
            second_losses = daq.loss_counters()

        self.assertNotEqual(first_run, second_run)
        self.assertGreater(generation, 0)
        self.assertIsInstance(first_second_run, ADCBlock)
        assert isinstance(first_second_run, ADCBlock)
        self.assertEqual(0, first_second_run.sequence)
        self.assertEqual(0, first_second_run.first_sample_ticks)
        self.assertFalse(second_losses.has_loss)

    def test_new_start_resets_cumulative_firmware_baseline(self) -> None:
        with ThingDAQ.open(InMemoryTransport(_OneGapDevice())) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            self.assertIsInstance(daq.read_block(), StreamGap)
            self.assertIsInstance(daq.read_block(), ADCBlock)
            first_run_losses = daq.loss_counters()
            daq.stop()

            daq.configure(adc=True, gpio=False)
            daq.start()
            uncached_losses = daq.loss_counters(refresh=False)
            self.assertIsInstance(daq.read_block(), ADCBlock)
            second_run_losses = daq.loss_counters()

        self.assertEqual(0, uncached_losses.protocol_telemetry_errors)
        self.assertEqual(0, second_run_losses.observed_stream_gaps)
        self.assertEqual(0, second_run_losses.protocol_telemetry_errors)
        self.assertFalse(second_run_losses.telemetry_errors)
        self.assertNotEqual(
            first_run_losses.firmware.stats_generation,
            second_run_losses.firmware.stats_generation,
        )
        self.assertEqual(
            0,
            second_run_losses.firmware.adc_items_dropped,
        )

    def test_host_queue_loss_reports_exact_policy_units(self) -> None:
        class _BurstTransport(InMemoryTransport):
            def write(self, data: bytes | bytearray | memoryview) -> int:
                request = decode_frame(bytes(data))
                written = super().write(data)
                if request.header.kind is FrameKind.START_REQUEST:
                    with self._lock:
                        for _ in range(3):
                            wire = self.device.next_data_frame()
                            assert wire is not None
                            self._pending.extend(wire)
                return written

        with ThingDAQ.open(_BurstTransport(), max_buffered_blocks=1) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            deadline = time.monotonic() + 1.0
            while daq.reader_counters.host_block_queue_drops != 2:
                if time.monotonic() >= deadline:
                    self.fail("reader did not record the expected queue loss")
                time.sleep(0.001)
            loss = daq.read_block()

        self.assertIsInstance(loss, HostQueueLoss)
        assert isinstance(loss, HostQueueLoss)
        self.assertEqual(2, loss.dropped_blocks)
        self.assertEqual(2 * constants.ADC_PAIRS_PER_FRAME, loss.dropped_items)
        self.assertEqual((0, 1), (loss.first_sequence, loss.last_sequence))
        self.assertEqual("drop_oldest_complete", loss.policy.value)


if __name__ == "__main__":
    unittest.main()
