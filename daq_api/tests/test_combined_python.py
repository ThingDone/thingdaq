"""Independent combined-stream Python, parser, alignment, and CLI tests."""

from __future__ import annotations

import importlib
import importlib.util
import io
import os
import random
import re
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from collections.abc import Iterable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import serial
from thingdaq import (
    ADCBlock,
    AlignedInterval,
    AlignmentItem,
    AlignmentLoss,
    AlignmentLossReason,
    CommandResponse,
    DAQConfiguration,
    DeviceState,
    Frame,
    FrameFlag,
    FrameKind,
    GPIOBlock,
    HostQueueLoss,
    IncrementalFrameParser,
    InMemoryTransport,
    LossOrigin,
    SerialTransport,
    SimulatedDevice,
    Source,
    Status,
    StreamGap,
    StreamMask,
    ThingDAQ,
    TimestampAligner,
    TimestampAlignmentError,
    UnexpectedStreamGapError,
    decode_frame,
    decode_message,
    encode_frame,
    synthetic_adc0_code,
    synthetic_adc1_code,
    synthetic_adc_payload,
    synthetic_gpio_byte,
    synthetic_gpio_payload,
    validate_synthetic_block,
)
from thingdaq._generated import protocol_constants as constants
from thingdaq.cli import CliExitCode, _execute, build_parser, main

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SOURCE = REPOSITORY_ROOT / "daq_api" / "src"
_BOTH_STREAMS = StreamMask.ADC | StreamMask.GPIO


def _flags(sequence: int) -> FrameFlag:
    flags = FrameFlag.SYNTHETIC
    if sequence == 0:
        flags |= FrameFlag.EPOCH_START
    return flags


def _adc(
    interval: int,
    *,
    run_id: int = 0xDA08_0001,
    sequence: int | None = None,
) -> ADCBlock:
    selected_sequence = interval if sequence is None else sequence
    first_ticks = interval * constants.FRAME_COVERAGE_TICKS
    return ADCBlock(
        run_id=run_id,
        sequence=selected_sequence,
        first_sample_ticks=first_ticks,
        payload=synthetic_adc_payload(first_ticks // constants.ADC_PAIR_PERIOD_TICKS),
        flags=_flags(selected_sequence),
    )


def _gpio(
    interval: int,
    *,
    run_id: int = 0xDA08_0001,
    sequence: int | None = None,
) -> GPIOBlock:
    selected_sequence = interval if sequence is None else sequence
    first_ticks = interval * constants.FRAME_COVERAGE_TICKS
    return GPIOBlock(
        run_id=run_id,
        sequence=selected_sequence,
        first_sample_ticks=first_ticks,
        payload=synthetic_gpio_payload(
            first_ticks // constants.GPIO_SAMPLE_PERIOD_TICKS
        ),
        flags=_flags(selected_sequence),
    )


def _collect_alignment(
    aligner: TimestampAligner,
    arrivals: Iterable[ADCBlock | GPIOBlock | StreamGap],
) -> tuple[AlignmentItem, ...]:
    outputs: list[AlignmentItem] = []
    for arrival in arrivals:
        outputs.extend(aligner.push(arrival))
    outputs.extend(aligner.finish())
    return tuple(outputs)


class CombinedAlignmentTests(unittest.TestCase):
    def test_in_order_out_of_order_and_delayed_arrivals_pair_monotonically(
        self,
    ) -> None:
        cases: dict[str, tuple[ADCBlock | GPIOBlock, ...]] = {
            "in-order": (_adc(0), _gpio(0), _adc(1), _gpio(1)),
            "out-of-order": (_gpio(1), _adc(1), _gpio(0), _adc(0)),
            "delayed-side": (_adc(0), _adc(1), _gpio(1), _gpio(0)),
        }

        for name, arrivals in cases.items():
            with self.subTest(order=name):
                outputs = _collect_alignment(
                    TimestampAligner(max_pending_intervals=2),
                    arrivals,
                )
                self.assertEqual(
                    [AlignedInterval, AlignedInterval], [type(x) for x in outputs]
                )
                intervals = tuple(
                    item for item in outputs if isinstance(item, AlignedInterval)
                )
                self.assertEqual(
                    [0, constants.FRAME_COVERAGE_TICKS],
                    [item.first_sample_ticks for item in intervals],
                )
                self.assertTrue(all(item.complete for item in intervals))
                self.assertTrue(
                    all(item.present_streams == _BOTH_STREAMS for item in intervals)
                )

    def test_missing_adc_gpio_and_whole_intervals_are_explicit(self) -> None:
        cases = (
            ("gpio", (_adc(0), _adc(1), _gpio(1)), StreamMask.GPIO),
            ("adc", (_gpio(0), _gpio(1), _adc(1)), StreamMask.ADC),
        )
        for name, arrivals, missing in cases:
            with self.subTest(missing=name):
                outputs = _collect_alignment(
                    TimestampAligner(max_pending_intervals=1),
                    arrivals,
                )
                losses = tuple(
                    item for item in outputs if isinstance(item, AlignmentLoss)
                )
                intervals = tuple(
                    item for item in outputs if isinstance(item, AlignedInterval)
                )
                self.assertEqual(1, len(losses))
                self.assertEqual(missing, losses[0].missing_streams)
                self.assertEqual(AlignmentLossReason.WINDOW_EXPIRED, losses[0].reason)
                self.assertEqual(missing, intervals[0].missing_streams)
                self.assertFalse(intervals[0].complete)
                self.assertTrue(intervals[1].complete)

        whole_interval = _collect_alignment(
            TimestampAligner(max_pending_intervals=1),
            (_adc(0), _gpio(0), _adc(2), _gpio(2)),
        )
        whole_losses = tuple(
            item for item in whole_interval if isinstance(item, AlignmentLoss)
        )
        self.assertEqual(1, len(whole_losses))
        self.assertEqual(StreamMask.NONE, whole_losses[0].present_streams)
        self.assertEqual(_BOTH_STREAMS, whole_losses[0].missing_streams)
        self.assertEqual(1, whole_losses[0].interval_count)

    def test_duplicate_sources_are_rejected_and_runs_never_cross_pair(self) -> None:
        for name, first, duplicate, message in (
            ("adc", _adc(0), _adc(0), "duplicate ADC"),
            ("gpio", _gpio(0), _gpio(0), "duplicate GPIO"),
        ):
            with self.subTest(source=name):
                aligner = TimestampAligner()
                self.assertEqual((), aligner.push(first))
                with self.assertRaisesRegex(TimestampAlignmentError, message):
                    aligner.push(duplicate)

        run_one_adc = _adc(0, run_id=41)
        run_two_gpio = _gpio(0, run_id=42)
        aligner = TimestampAligner()
        aligner.push(run_one_adc)
        boundary = aligner.push(run_two_gpio)
        paired = aligner.push(_adc(0, run_id=42))

        self.assertEqual([AlignmentLoss, AlignedInterval], [type(x) for x in boundary])
        old_interval = boundary[1]
        assert isinstance(old_interval, AlignedInterval)
        self.assertEqual(41, old_interval.run_id)
        self.assertIs(run_one_adc, old_interval.adc)
        self.assertIsNone(old_interval.gpio)
        new_interval = paired[0]
        assert isinstance(new_interval, AlignedInterval)
        self.assertEqual(42, new_interval.run_id)
        self.assertEqual((), new_interval.stream_gaps)
        self.assertIs(run_two_gpio, new_interval.gpio)
        self.assertTrue(new_interval.complete)

    def test_explicit_flush_resolves_delay_and_storage_stays_bounded(self) -> None:
        aligner = TimestampAligner(max_pending_intervals=4)
        outputs: list[AlignmentItem] = []
        for interval in range(128):
            outputs.extend(aligner.push(_adc(interval)))
            self.assertLessEqual(aligner.pending_intervals, 4)
        outputs.extend(aligner.flush())

        losses = tuple(item for item in outputs if isinstance(item, AlignmentLoss))
        intervals = tuple(item for item in outputs if isinstance(item, AlignedInterval))
        self.assertEqual(128, len(losses))
        self.assertEqual(128, len(intervals))
        self.assertEqual(4, aligner.high_water_intervals)
        self.assertEqual(0, aligner.pending_intervals)
        self.assertTrue(all(item.missing_streams == StreamMask.GPIO for item in losses))
        self.assertEqual(
            AlignmentLossReason.EXPLICIT_FLUSH,
            losses[-1].reason,
        )


class _CombinedFirmwareGapDevice(SimulatedDevice):
    """Skip one ADC interval while the combined GPIO stream stays continuous."""

    def __init__(self) -> None:
        super().__init__()
        self._combined_gap_injected = False

    def _next_adc_frame(self, configuration: DAQConfiguration) -> bytes:
        inject = not self._combined_gap_injected and self._adc_sequence == 1
        if inject:
            self._combined_gap_injected = True
            self._adc_sequence += 1
            self._adc_first_ticks += constants.FRAME_COVERAGE_TICKS
            self._adc_item_index += constants.ADC_PAIRS_PER_FRAME
            self._adc_items_dropped += constants.ADC_PAIRS_PER_FRAME

        wire = super()._next_adc_frame(configuration)
        if not inject:
            return wire
        frame = decode_frame(wire)
        return encode_frame(
            frame.header.kind,
            frame.payload,
            flags=(
                frame.header.flags | FrameFlag.GAP_BEFORE | FrameFlag.OVERRUN_BEFORE
            ),
            checksum_algorithm=frame.header.checksum_algorithm,
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            request_id=frame.header.request_id,
            first_sample_ticks=frame.header.first_sample_ticks,
            item_count=frame.header.item_count,
        )


class _CombinedStartBurstTransport(InMemoryTransport):
    """Queue three intervals behind START to force balanced host evictions."""

    def __init__(self) -> None:
        super().__init__()
        self._burst_added = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        request = decode_frame(bytes(data))
        written = super().write(data)
        if request.header.kind is FrameKind.START_REQUEST and not self._burst_added:
            self._burst_added = True
            with self._lock:
                for _ in range(6):
                    wire = self.device.next_data_frame()
                    assert wire is not None
                    self._pending.extend(wire)
        return written


def _wait_for_host_drops(
    daq: ThingDAQ,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while daq.reader_counters.host_block_queue_drops < expected:
        if time.monotonic() >= deadline:
            raise AssertionError(
                "host queue did not reach the expected deterministic drop count"
            )
        time.sleep(0.001)


class CombinedGapPolicyTests(unittest.TestCase):
    def test_continuing_and_strict_modes_handle_one_combined_firmware_gap(self) -> None:
        with ThingDAQ.open(
            InMemoryTransport(_CombinedFirmwareGapDevice())
        ) as continuing:
            continuing.configure(adc=True, gpio=True)
            continuing.start()
            items = list(continuing.blocks(3))
            losses = continuing.loss_counters()

        self.assertEqual(
            [ADCBlock, GPIOBlock, StreamGap, ADCBlock],
            [type(item) for item in items],
        )
        gap = items[2]
        block = items[3]
        assert isinstance(gap, StreamGap)
        assert isinstance(block, ADCBlock)
        self.assertEqual(FrameKind.ADC_DATA, gap.kind)
        self.assertEqual(LossOrigin.FIRMWARE, gap.origin)
        self.assertEqual(1, gap.missing_frames)
        self.assertEqual(2, block.sequence)
        self.assertIs(gap, block.gap)
        self.assertEqual(
            constants.ADC_PAIRS_PER_FRAME, losses.firmware.adc_items_dropped
        )
        self.assertEqual(0, losses.host.host_block_queue_drops)

        with ThingDAQ.open(
            InMemoryTransport(_CombinedFirmwareGapDevice()),
            strict=True,
        ) as strict:
            strict.configure(adc=True, gpio=True)
            strict.start()
            self.assertIsInstance(strict.read_block(), ADCBlock)
            self.assertIsInstance(strict.read_block(), GPIOBlock)
            with self.assertRaises(UnexpectedStreamGapError) as raised:
                strict.read_block()
            strict_losses = strict.loss_counters()

        self.assertEqual(LossOrigin.FIRMWARE, raised.exception.gap.origin)
        self.assertEqual(2, raised.exception.block.sequence)
        self.assertEqual(0, raised.exception.gap.host_queue_drops)
        self.assertEqual(0, strict_losses.host.host_block_queue_drops)

    def test_combined_host_queue_loss_remains_separate_from_firmware_loss(self) -> None:
        transport = _CombinedStartBurstTransport()
        with ThingDAQ.open(transport, max_buffered_blocks=2) as daq:
            daq.configure(adc=True, gpio=True)
            daq.start()
            _wait_for_host_drops(daq, 4)
            items = list(daq.blocks(2))
            losses = daq.loss_counters()
            reader = daq.reader_counters

        host_losses = tuple(item for item in items if isinstance(item, HostQueueLoss))
        blocks = tuple(
            item for item in items if isinstance(item, (ADCBlock, GPIOBlock))
        )
        self.assertEqual(2, len(host_losses))
        self.assertEqual(2, len(blocks))
        self.assertEqual(
            {FrameKind.ADC_DATA, FrameKind.GPIO_DATA},
            {loss.kind for loss in host_losses},
        )
        self.assertTrue(
            all(loss.origin is LossOrigin.HOST_QUEUE for loss in host_losses)
        )
        self.assertEqual(4, sum(loss.dropped_blocks for loss in host_losses))
        self.assertEqual(
            2 * constants.ADC_PAIRS_PER_FRAME + 2 * constants.GPIO_SAMPLES_PER_FRAME,
            sum(loss.dropped_items for loss in host_losses),
        )
        self.assertEqual(2, reader.adc_block_queue_drops)
        self.assertEqual(2, reader.gpio_block_queue_drops)
        self.assertEqual(4, losses.host.host_block_queue_drops)
        self.assertEqual(0, losses.firmware.items_dropped)


def _device_request(
    device: SimulatedDevice,
    kind: FrameKind,
    request_id: int,
    payload: bytes = b"",
) -> bytes:
    responses = device.receive(encode_frame(kind, payload, request_id=request_id))
    if len(responses) != 1:
        raise AssertionError(f"{kind.name} did not produce exactly one response")
    return responses[0]


def _mixed_wire_corpus(interval_count: int = 257) -> bytes:
    device = SimulatedDevice()
    configuration = DAQConfiguration(_BOTH_STREAMS, Source.SYNTHETIC)
    request_id = 1
    wire = bytearray()

    wire.extend(_device_request(device, FrameKind.INFO_REQUEST, request_id))
    request_id += 1
    wire.extend(
        _device_request(
            device,
            FrameKind.CONFIGURE_REQUEST,
            request_id,
            configuration.to_payload(),
        )
    )
    request_id += 1
    wire.extend(_device_request(device, FrameKind.START_REQUEST, request_id))
    request_id += 1

    for interval in range(interval_count):
        adc_wire = device.next_data_frame()
        if adc_wire is None:
            raise AssertionError("combined simulator stopped producing data")
        wire.extend(adc_wire)
        if interval % 11 == 3:
            wire.extend(
                _device_request(device, FrameKind.GET_STATUS_REQUEST, request_id)
            )
            request_id += 1
        if interval % 19 == 7:
            nonce = (0xDA08_0000_0000_0000 | interval).to_bytes(8, "little")
            wire.extend(
                _device_request(device, FrameKind.PING_REQUEST, request_id, nonce)
            )
            request_id += 1
        gpio_wire = device.next_data_frame()
        if gpio_wire is None:
            raise AssertionError("combined simulator stopped producing data")
        wire.extend(gpio_wire)

    wire.extend(_device_request(device, FrameKind.GET_STATUS_REQUEST, request_id))
    request_id += 1
    wire.extend(_device_request(device, FrameKind.STOP_REQUEST, request_id))
    return bytes(wire)


def _consume_mixed_corpus(
    wire: bytes,
    *,
    seed: int,
    maximum_chunk: int,
) -> tuple[int, int, int, int, int]:
    parser = IncrementalFrameParser()
    aligner = TimestampAligner(max_pending_intervals=4)
    randomizer = random.Random(seed)
    adc_count = 0
    gpio_count = 0
    response_count = 0
    status_count = 0
    ping_count = 0
    aligned_count = 0
    previous_request_id = 0
    offset = 0
    wire_view = memoryview(wire)
    try:
        while offset < len(wire_view):
            chunk_size = randomizer.randint(
                1,
                min(maximum_chunk, len(wire_view) - offset),
            )
            chunk = wire_view[offset : offset + chunk_size]
            try:
                frames = parser.feed(chunk)
            finally:
                chunk.release()
            offset += chunk_size

            for frame in frames:
                message = decode_message(frame)
                if isinstance(message, ADCBlock):
                    self_expected = adc_count
                    if message.sequence != self_expected:
                        raise AssertionError("ADC sequence changed in valid corpus")
                    validate_synthetic_block(message)
                    adc_count += 1
                    aligned = aligner.push(message)
                elif isinstance(message, GPIOBlock):
                    self_expected = gpio_count
                    if message.sequence != self_expected:
                        raise AssertionError("GPIO sequence changed in valid corpus")
                    validate_synthetic_block(message)
                    gpio_count += 1
                    aligned = aligner.push(message)
                else:
                    if not isinstance(message, CommandResponse):
                        raise TypeError("mixed corpus decoded an unknown event")
                    if message.request_id <= previous_request_id:
                        raise AssertionError("response request IDs are not monotonic")
                    previous_request_id = message.request_id
                    response_count += 1
                    if message.kind is FrameKind.GET_STATUS_RESPONSE:
                        if not isinstance(message.value, Status):
                            raise AssertionError("STATUS response is not typed")
                        if (
                            message.value.adc_frames_emitted != adc_count
                            or message.value.gpio_frames_emitted != gpio_count
                        ):
                            raise AssertionError(
                                "STATUS counters do not match preceding data frames"
                            )
                        status_count += 1
                    elif message.kind is FrameKind.PING_RESPONSE:
                        if not isinstance(message.value, int):
                            raise AssertionError("PING response is not typed")
                        ping_count += 1
                    continue

                for item in aligned:
                    if not isinstance(item, AlignedInterval) or not item.complete:
                        raise AssertionError("valid mixed corpus did not pair cleanly")
                    if (
                        item.first_sample_ticks
                        != aligned_count * constants.FRAME_COVERAGE_TICKS
                    ):
                        raise AssertionError("aligned output is not monotonic")
                    aligned_count += 1
    finally:
        wire_view.release()

    if aligner.finish():
        raise AssertionError("complete combined corpus left an alignment tail")
    if parser.buffered_bytes or parser.counters.corruption_events:
        raise AssertionError("valid mixed corpus left parser loss or trailing bytes")
    if aligned_count != adc_count or aligned_count != gpio_count:
        raise AssertionError("combined corpus did not align every source frame")
    return adc_count, gpio_count, response_count, status_count, ping_count


class CombinedMixedStreamTests(unittest.TestCase):
    def test_sustained_interleaved_commands_survive_seeded_random_chunks(self) -> None:
        wire = _mixed_wire_corpus()
        profiles = (
            (0xDA08_1001, 127),
            (0xDA08_1002, 1_509),
            (0xDA08_1003, 8_191),
        )
        expected: tuple[int, int, int, int, int] | None = None
        for seed, maximum_chunk in profiles:
            with self.subTest(seed=seed, maximum_chunk=maximum_chunk):
                observed = _consume_mixed_corpus(
                    wire,
                    seed=seed,
                    maximum_chunk=maximum_chunk,
                )
                self.assertEqual((257, 257), observed[:2])
                self.assertGreater(observed[2], 30)
                self.assertGreater(observed[3], 20)
                self.assertGreater(observed[4], 10)
                if expected is None:
                    expected = observed
                else:
                    self.assertEqual(expected, observed)

    def test_optional_numpy_uses_original_payload_buffers_when_available(self) -> None:
        if importlib.util.find_spec("numpy") is None:
            self.skipTest("NumPy is an optional dependency")
        numpy = importlib.import_module("numpy")
        adc = _adc(0)
        gpio = _gpio(0)

        adc_pairs = numpy.frombuffer(adc.payload_view, dtype="<u2").reshape(-1, 2)
        gpio_samples = numpy.frombuffer(gpio.payload_view, dtype="u1")

        self.assertEqual((constants.ADC_PAIRS_PER_FRAME, 2), adc_pairs.shape)
        self.assertEqual((constants.GPIO_SAMPLES_PER_FRAME,), gpio_samples.shape)
        self.assertFalse(adc_pairs.flags.owndata)
        self.assertFalse(gpio_samples.flags.owndata)
        self.assertFalse(adc_pairs.flags.writeable)
        self.assertFalse(gpio_samples.flags.writeable)
        self.assertEqual(
            [synthetic_adc0_code(0), synthetic_adc1_code(0)],
            adc_pairs[0].tolist(),
        )
        self.assertEqual(synthetic_gpio_byte(0), int(gpio_samples[0]))

    def test_package_parses_and_aligns_combined_data_when_numpy_is_forbidden(
        self,
    ) -> None:
        script = textwrap.dedent(
            """
            import builtins
            import struct
            import sys

            original_import = builtins.__import__
            def guarded_import(name, *args, **kwargs):
                if name.partition('.')[0] == 'numpy':
                    raise AssertionError('pure-Python path imported NumPy')
                return original_import(name, *args, **kwargs)
            builtins.__import__ = guarded_import

            from thingdaq import (
                ADCBlock, AlignedInterval, FrameFlag, GPIOBlock,
                TimestampAligner, synthetic_adc_payload, synthetic_gpio_payload,
            )

            adc = ADCBlock(9, 0, 0, synthetic_adc_payload(0),
                           FrameFlag.SYNTHETIC | FrameFlag.EPOCH_START)
            gpio = GPIOBlock(9, 0, 0, synthetic_gpio_payload(0),
                             FrameFlag.SYNTHETIC | FrameFlag.EPOCH_START)
            aligner = TimestampAligner(max_pending_intervals=1)
            assert aligner.push(adc) == ()
            output = aligner.push(gpio)
            assert len(output) == 1 and isinstance(output[0], AlignedInterval)
            adc_view = output[0].adc_payload_view
            gpio_view = output[0].gpio_payload_view
            assert adc_view is not None and adc_view.obj is adc.payload
            assert gpio_view is not None and gpio_view.obj is gpio.payload
            assert struct.unpack_from('<HH', adc_view) == (0, 1)
            assert gpio_view[0] == 0
            assert 'numpy' not in sys.modules
            """
        )
        environment = os.environ.copy()
        existing_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(PACKAGE_SOURCE) + (
            os.pathsep + existing_path if existing_path else ""
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


class _PartialSerialPeer:
    """PySerial-shaped combined peer with partial I/O and optional disconnect."""

    def __init__(
        self,
        *,
        disconnect_after_data_frames: int | None = None,
        stream_interval: float = 0.00025,
    ) -> None:
        self.device = SimulatedDevice()
        self._disconnect_after_data_frames = disconnect_after_data_frames
        self._stream_interval = stream_interval
        self._condition = threading.Condition()
        self._pending = bytearray()
        self._request_parser = IncrementalFrameParser()
        self._request_frames: list[Frame] = []
        self._read_pattern = (1, 37, 509, 113, 1_021)
        self._write_pattern = (1, 0, 3, 11, 29)
        self._read_index = 0
        self._write_index = 0
        self._data_frames_queued = 0
        self._next_stream_at = time.monotonic()
        self._is_open = True
        self._disconnected = False
        self.read_counts: list[int] = []
        self.write_counts: list[int] = []
        self.cancel_read_calls = 0
        self.cancel_write_calls = 0
        self.close_calls = 0

    @property
    def is_open(self) -> bool:
        with self._condition:
            return self._is_open

    @property
    def request_frames(self) -> tuple[Frame, ...]:
        with self._condition:
            return tuple(self._request_frames)

    def write(self, data: bytes | bytearray | memoryview) -> int:
        view = memoryview(data).cast("B")
        try:
            with self._condition:
                self._require_open()
                limit = self._write_pattern[
                    self._write_index % len(self._write_pattern)
                ]
                self._write_index += 1
                accepted = min(len(view), limit)
                self.write_counts.append(accepted)
                if accepted == 0:
                    return 0
                chunk = bytes(view[:accepted])
                self._request_frames.extend(self._request_parser.feed(chunk))
                for response in self.device.receive(chunk):
                    self._pending.extend(response)
                self._condition.notify_all()
                return accepted
        finally:
            view.release()

    def read(self, size: int = 1) -> bytes:
        with self._condition:
            self._require_open()
            self._queue_stream_frame()
            if not self._pending:
                self._condition.wait(0.0002)
                self._require_open()
                self._queue_stream_frame()
            if not self._pending:
                self.read_counts.append(0)
                return b""

            limit = self._read_pattern[self._read_index % len(self._read_pattern)]
            self._read_index += 1
            returned = min(size, limit, len(self._pending))
            result = bytes(self._pending[:returned])
            del self._pending[:returned]
            self.read_counts.append(returned)
            return result

    def flush(self) -> None:
        with self._condition:
            self._require_open()

    def cancel_read(self) -> None:
        with self._condition:
            self.cancel_read_calls += 1
            self._condition.notify_all()

    def cancel_write(self) -> None:
        with self._condition:
            self.cancel_write_calls += 1
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self.close_calls += 1
            self._is_open = False
            self._condition.notify_all()

    def _queue_stream_frame(self) -> None:
        if self._pending or self.device.state is not DeviceState.RUNNING:
            return
        if (
            self._disconnect_after_data_frames is not None
            and self._data_frames_queued >= self._disconnect_after_data_frames
        ):
            self._disconnected = True
            self._is_open = False
            self._condition.notify_all()
            raise serial.SerialException("deterministic combined disconnect")
        now = time.monotonic()
        if now < self._next_stream_at:
            return
        wire = self.device.next_data_frame()
        if wire is None:
            return
        self._pending.extend(wire)
        self._data_frames_queued += 1
        self._next_stream_at = now + self._stream_interval

    def _require_open(self) -> None:
        if self._is_open:
            return
        if self._disconnected:
            raise serial.SerialException("deterministic combined disconnect")
        raise serial.SerialException("deterministic combined port is closed")


def _serial_transport(peer: _PartialSerialPeer) -> SerialTransport:
    return SerialTransport(
        "combined-partial-serial",
        open_timeout=0.2,
        read_timeout=0.01,
        write_timeout=0.2,
        flush_timeout=0.2,
        close_timeout=0.2,
        serial_factory=lambda **_options: peer,
    )


def _summary_fields(output: str) -> dict[str, str]:
    summary = next(
        (line for line in output.splitlines() if line.startswith("summary ")),
        None,
    )
    if summary is None:
        raise AssertionError("monitor output omitted its summary")
    fields = dict(re.findall(r"([a-zA-Z_]+)=([^ ]+)", summary))
    if not fields:
        raise AssertionError("monitor summary has no machine-readable fields")
    return fields


class CombinedCliSerialTests(unittest.TestCase):
    def test_monitor_telemetry_and_cleanup_survive_partial_serial_io(self) -> None:
        peer = _PartialSerialPeer()
        daq = ThingDAQ.open(
            _serial_transport(peer),
            read_size=2_048,
            command_timeout=0.5,
            block_timeout=0.1,
            idle_sleep=0.00001,
        )
        arguments = build_parser().parse_args(
            [
                "monitor",
                "--duration",
                "0.08",
                "--status-interval",
                "0.015",
                "--block-timeout",
                "0.01",
            ]
        )
        output = io.StringIO()
        with patch("thingdaq.cli._open_device", return_value=daq):
            result = _execute(arguments, output)

        rendered = output.getvalue()
        summary = _summary_fields(rendered)
        request_kinds = [frame.header.kind for frame in peer.request_frames]
        self.assertEqual(CliExitCode.OK, result)
        self.assertIn("profile=SYNTHETIC_COMBINED", rendered)
        self.assertIn("final_state=IDLE", rendered)
        self.assertGreater(float(summary["adc_payload_Bps"]), 0.0)
        self.assertGreater(float(summary["gpio_payload_Bps"]), 0.0)
        self.assertEqual("0", summary["gaps"])
        self.assertEqual("0", summary["host_block_queue_drops"])
        self.assertGreaterEqual(float(summary["command_latency_max_ms"]), 0.0)
        self.assertIn(FrameKind.CONFIGURE_REQUEST, request_kinds)
        self.assertIn(FrameKind.START_REQUEST, request_kinds)
        self.assertIn(FrameKind.GET_STATUS_REQUEST, request_kinds)
        self.assertIn(FrameKind.STOP_REQUEST, request_kinds)
        self.assertEqual(DeviceState.IDLE, peer.device.state)
        self.assertFalse(peer.is_open)
        self.assertFalse(daq.is_open)
        self.assertIn(0, peer.write_counts)
        self.assertGreater(len(peer.write_counts), len(peer.request_frames))
        self.assertGreater(len([count for count in peer.read_counts if count]), 20)
        self.assertLessEqual(max(peer.read_counts), 1_021)
        self.assertGreaterEqual(peer.cancel_read_calls, 1)
        self.assertGreaterEqual(peer.cancel_write_calls, 1)
        self.assertEqual(1, peer.close_calls)

    def test_disconnect_still_attempts_stop_closes_and_returns_typed_cli_error(
        self,
    ) -> None:
        peer = _PartialSerialPeer(disconnect_after_data_frames=4)
        daq = ThingDAQ.open(
            _serial_transport(peer),
            read_size=1_024,
            command_timeout=0.5,
            block_timeout=0.1,
            idle_sleep=0.00001,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("thingdaq.cli._open_device", return_value=daq),
            patch.object(daq, "stop", wraps=daq.stop) as stop,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = main(
                [
                    "capture",
                    "--duration",
                    "1",
                    "--status-interval",
                    "0.2",
                    "--block-timeout",
                    "0.05",
                ]
            )

        self.assertEqual(CliExitCode.DISCONNECTED, exit_code)
        self.assertIn("[disconnected]", stderr.getvalue())
        self.assertEqual(1, stop.call_count)
        self.assertFalse(peer.is_open)
        self.assertFalse(daq.is_open)
        self.assertEqual(1, daq.reader_counters.disconnects)
        self.assertIn(0, peer.write_counts)
        self.assertGreaterEqual(peer.cancel_read_calls, 1)
        self.assertGreaterEqual(peer.cancel_write_calls, 1)
        self.assertEqual(1, peer.close_calls)


if __name__ == "__main__":
    unittest.main()
