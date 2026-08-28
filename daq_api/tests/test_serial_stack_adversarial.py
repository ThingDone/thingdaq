"""Adversarial serial-stack tests independent of the production transports."""

from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass

import serial
from teensy_daq import (
    ADCBlock,
    BackgroundReader,
    ByteTransport,
    CommandResponse,
    DAQConfiguration,
    DeviceDisconnectedError,
    DeviceInfo,
    DeviceState,
    Frame,
    FrameFlag,
    FrameKind,
    IncrementalFrameParser,
    InMemoryTransport,
    PendingRequestLimitError,
    RequestTimeoutError,
    SerialTransport,
    SimulatedDevice,
    Source,
    Status,
    TeensyDAQ,
    encode_frame,
    synthetic_adc_payload,
)
from teensy_daq._generated import protocol_constants as constants
from teensy_daq.models import ResponseValue


def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true before its deadline")
        time.sleep(0.001)


def _adc_wire(run_id: int, sequence: int) -> bytes:
    flags = FrameFlag.SYNTHETIC
    if sequence == 0:
        flags |= FrameFlag.EPOCH_START
    return encode_frame(
        FrameKind.ADC_DATA,
        synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME),
        flags=flags,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=sequence * constants.FRAME_COVERAGE_TICKS,
        item_count=constants.ADC_PAIRS_PER_FRAME,
    )


class RecordingSimulatedDevice(SimulatedDevice):
    """Simulator peer that records complete wire traffic without decoding it."""

    def __init__(self) -> None:
        super().__init__()
        self.host_chunks: list[bytes] = []
        self.response_frames: list[bytes] = []
        self.data_frames: list[bytes] = []

    @property
    def host_bytes(self) -> bytes:
        return b"".join(self.host_chunks)

    def receive(self, data: bytes | bytearray | memoryview) -> tuple[bytes, ...]:
        self.host_chunks.append(bytes(data))
        responses = super().receive(data)
        self.response_frames.extend(responses)
        return responses

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is not None:
            self.data_frames.append(wire)
        return wire


class ScriptedSerialPeer:
    """PySerial-shaped peer with deterministic partial I/O and held responses."""

    def __init__(
        self,
        device: RecordingSimulatedDevice | None = None,
        *,
        read_pattern: tuple[int, ...] = (1, 7, 2, 13),
        write_pattern: tuple[int, ...] = (1, 0, 3, 2, 11),
        hold_responses: bool = False,
        one_shot_stream: bool = False,
        empty_read_wait: float = 0.002,
    ) -> None:
        if not read_pattern or any(limit <= 0 for limit in read_pattern):
            raise ValueError("read pattern must contain positive limits")
        if (
            not write_pattern
            or any(limit < 0 for limit in write_pattern)
            or not any(write_pattern)
        ):
            raise ValueError("write pattern must contain a positive limit")
        self.device = device if device is not None else RecordingSimulatedDevice()
        self._read_pattern = read_pattern
        self._write_pattern = write_pattern
        self._hold_responses = hold_responses
        self._one_shot_stream = one_shot_stream
        self._empty_read_wait = empty_read_wait
        self._condition = threading.Condition()
        self._request_parser = IncrementalFrameParser()
        self._request_frames: list[Frame] = []
        self._pending = bytearray()
        self._held_responses: list[bytes] = []
        self._read_index = 0
        self._write_index = 0
        self._stream_frame_sent = False
        self._is_open = True
        self._disconnected = False
        self.write_counts: list[int] = []
        self.read_counts: list[int] = []
        self.flush_calls = 0
        self.cancel_read_calls = 0
        self.cancel_write_calls = 0

    @property
    def is_open(self) -> bool:
        with self._condition:
            return self._is_open

    @property
    def request_frames(self) -> tuple[Frame, ...]:
        with self._condition:
            return tuple(self._request_frames)

    @property
    def held_responses(self) -> tuple[bytes, ...]:
        with self._condition:
            return tuple(self._held_responses)

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
                responses = self.device.receive(chunk)
                if self._hold_responses:
                    self._held_responses.extend(responses)
                else:
                    for response in responses:
                        self._pending.extend(response)
                self._condition.notify_all()
                return accepted
        finally:
            view.release()

    def read(self, size: int = 1) -> bytes:
        with self._condition:
            self._require_open()
            self._queue_one_stream_frame()
            if not self._pending:
                self._condition.wait(self._empty_read_wait)
                self._require_open()
                self._queue_one_stream_frame()
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
            self.flush_calls += 1

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
            self._is_open = False
            self._condition.notify_all()

    def disconnect(self) -> None:
        with self._condition:
            self._disconnected = True
            self._is_open = False
            self._condition.notify_all()

    def inject(self, wire: bytes) -> None:
        with self._condition:
            self._require_open()
            self._pending.extend(wire)
            self._condition.notify_all()

    def release_held(
        self,
        *,
        order: tuple[int, ...] | None = None,
        interleave_after_first: bytes = b"",
    ) -> None:
        with self._condition:
            selected_order = (
                tuple(range(len(self._held_responses))) if order is None else order
            )
            if sorted(selected_order) != list(range(len(self._held_responses))):
                raise ValueError("response order must be a complete permutation")
            selected = [self._held_responses[index] for index in selected_order]
            self._held_responses.clear()
            for index, response in enumerate(selected):
                self._pending.extend(response)
                if index == 0:
                    self._pending.extend(interleave_after_first)
            self._condition.notify_all()

    def wait_for_requests(
        self,
        count: int,
        timeout: float = 1.0,
    ) -> tuple[Frame, ...]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self._request_frames) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    raise AssertionError(
                        f"only received {len(self._request_frames)} requests"
                    )
            return tuple(self._request_frames)

    def _queue_one_stream_frame(self) -> None:
        if self._pending or not self._one_shot_stream or self._stream_frame_sent:
            return
        wire = self.device.next_data_frame()
        if wire is not None:
            self._pending.extend(wire)
            self._stream_frame_sent = True

    def _require_open(self) -> None:
        if self._is_open:
            return
        if self._disconnected:
            raise serial.SerialException("scripted device disconnected")
        raise serial.SerialException("scripted serial port is closed")


def _serial_transport(peer: ScriptedSerialPeer) -> SerialTransport:
    return SerialTransport(
        "scripted-loopback",
        open_timeout=0.2,
        read_timeout=0.01,
        write_timeout=0.05,
        flush_timeout=0.2,
        close_timeout=0.2,
        serial_factory=lambda **_options: peer,
    )


class AdversarialSerialReaderTests(unittest.TestCase):
    def test_reordered_delayed_responses_match_ids_while_data_interleaves(
        self,
    ) -> None:
        peer = ScriptedSerialPeer(hold_responses=True)
        results: dict[str, CommandResponse[ResponseValue]] = {}
        failures: list[BaseException] = []
        nonce = 0x0123456789ABCDEF

        with BackgroundReader(
            _serial_transport(peer),
            read_size=65_536,
            max_pending_requests=3,
            request_timeout=1.0,
        ) as reader:
            reader.activate_run(77)

            def request(
                name: str,
                kind: FrameKind,
                payload: bytes = b"",
            ) -> None:
                try:
                    results[name] = reader.request(kind, payload, timeout=1.0)
                except Exception as error:  # noqa: BLE001 - collect thread result
                    failures.append(error)

            threads = (
                threading.Thread(
                    target=request,
                    args=("info", FrameKind.INFO_REQUEST),
                ),
                threading.Thread(
                    target=request,
                    args=(
                        "ping",
                        FrameKind.PING_REQUEST,
                        nonce.to_bytes(8, "little"),
                    ),
                ),
                threading.Thread(
                    target=request,
                    args=("status", FrameKind.GET_STATUS_REQUEST),
                ),
            )
            for thread in threads:
                thread.start()

            requests = peer.wait_for_requests(3)
            self.assertEqual(3, len(peer.held_responses))
            peer.release_held(
                order=(2, 1, 0),
                interleave_after_first=_adc_wire(77, 0),
            )
            for thread in threads:
                thread.join(1.0)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual([], failures)
            self.assertIsInstance(results["info"].value, DeviceInfo)
            self.assertEqual(nonce, results["ping"].value)
            self.assertIsInstance(results["status"].value, Status)
            self.assertEqual(0, reader.get_block(timeout=0.5).sequence)
            self.assertEqual(3, reader.counters.responses_matched)
            self.assertEqual(0, reader.counters.pending_requests)
            self.assertEqual(0, reader.counters.late_responses)
            self.assertEqual(3, len({frame.header.request_id for frame in requests}))

        self.assertIn(0, peer.write_counts)
        self.assertGreater(len(peer.write_counts), len(requests))
        self.assertGreater(len([count for count in peer.read_counts if count]), 3)
        self.assertLessEqual(max(peer.read_counts), 13)

    def test_pending_bound_timeout_cleanup_and_every_late_reply_are_exact(
        self,
    ) -> None:
        peer = ScriptedSerialPeer(hold_responses=True)
        failures: list[BaseException] = []

        with BackgroundReader(
            _serial_transport(peer),
            max_pending_requests=2,
            request_timeout=0.2,
        ) as reader:

            def request(kind: FrameKind, payload: bytes = b"") -> None:
                try:
                    reader.request(kind, payload, timeout=0.2)
                except Exception as error:  # noqa: BLE001 - collect thread result
                    failures.append(error)

            threads = (
                threading.Thread(target=request, args=(FrameKind.INFO_REQUEST,)),
                threading.Thread(
                    target=request,
                    args=(FrameKind.PING_REQUEST, bytes(8)),
                ),
            )
            for thread in threads:
                thread.start()
            requests = peer.wait_for_requests(2)

            with self.assertRaises(PendingRequestLimitError):
                reader.request(FrameKind.GET_STATUS_REQUEST, timeout=0.05)

            for thread in threads:
                thread.join(1.0)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(2, len(failures))
            self.assertTrue(
                all(isinstance(error, RequestTimeoutError) for error in failures)
            )
            self.assertEqual(0, reader.pending_count)
            self.assertEqual(2, reader.counters.request_timeouts)

            peer.release_held(order=(1, 0))
            _wait_until(lambda: reader.counters.late_responses == 2)
            self.assertEqual(0, reader.counters.responses_matched)
            self.assertEqual(2, len({frame.header.request_id for frame in requests}))

    def test_disconnect_fails_all_pending_requests_and_joins_reader_thread(
        self,
    ) -> None:
        peer = ScriptedSerialPeer(hold_responses=True)
        failures: list[BaseException] = []
        reader = BackgroundReader(
            _serial_transport(peer),
            max_pending_requests=3,
            request_timeout=1.0,
        )
        reader.start()
        reader_thread_name = f"teensy-daq-reader-{id(reader):x}"

        def request(kind: FrameKind, payload: bytes = b"") -> None:
            try:
                reader.request(kind, payload, timeout=1.0)
            except Exception as error:  # noqa: BLE001 - collect thread result
                failures.append(error)

        threads = (
            threading.Thread(target=request, args=(FrameKind.INFO_REQUEST,)),
            threading.Thread(
                target=request,
                args=(FrameKind.PING_REQUEST, bytes(8)),
            ),
            threading.Thread(target=request, args=(FrameKind.GET_STATUS_REQUEST,)),
        )
        try:
            for thread in threads:
                thread.start()
            peer.wait_for_requests(3)
            peer.disconnect()
            for thread in threads:
                thread.join(1.0)
            _wait_until(lambda: not reader.is_running)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(3, len(failures))
            self.assertTrue(
                all(isinstance(error, DeviceDisconnectedError) for error in failures)
            )
            self.assertEqual(0, reader.pending_count)
            self.assertEqual(1, reader.counters.disconnects)
        finally:
            reader.close()

        self.assertFalse(
            any(
                thread.name == reader_thread_name and thread.is_alive()
                for thread in threading.enumerate()
            )
        )


@dataclass(frozen=True, slots=True)
class _PublicTranscript:
    info: DeviceInfo
    configuration: DAQConfiguration
    run_id: int
    block: ADCBlock
    running_status: Status
    stop_state: DeviceState
    stats_generation: int
    idle_status: Status


def _exercise_public_api(transport: ByteTransport) -> _PublicTranscript:
    with TeensyDAQ.open(
        transport,
        read_size=97,
        command_timeout=1.0,
        block_timeout=1.0,
    ) as daq:
        info = daq.info()
        configuration = daq.configure(
            adc=True,
            gpio=False,
            source=Source.SYNTHETIC,
        )
        run_id = daq.start()
        block = daq.read_block()
        if not isinstance(block, ADCBlock):
            raise TypeError(f"expected ADCBlock, received {type(block).__name__}")
        running_status = daq.status()
        stop_state = daq.stop()
        stats_generation = daq.reset_stats()
        idle_status = daq.status()
        return _PublicTranscript(
            info,
            configuration,
            run_id,
            block,
            running_status,
            stop_state,
            stats_generation,
            idle_status,
        )


class PublicSerialSimulatorParityTests(unittest.TestCase):
    def test_public_api_has_identical_wire_and_models_on_both_transports(self) -> None:
        memory_device = RecordingSimulatedDevice()
        memory_transport = InMemoryTransport(
            memory_device,
            read_chunk_size=19,
            write_chunk_size=4,
        )
        memory_result = _exercise_public_api(memory_transport)

        serial_device = RecordingSimulatedDevice()
        serial_peer = ScriptedSerialPeer(
            serial_device,
            read_pattern=(5, 13, 2, 31),
            write_pattern=(1, 0, 3, 7, 2, 11),
            one_shot_stream=True,
        )
        serial_result = _exercise_public_api(_serial_transport(serial_peer))

        self.assertEqual(memory_result, serial_result)
        self.assertEqual(memory_device.host_bytes, serial_device.host_bytes)
        self.assertEqual(memory_device.response_frames, serial_device.response_frames)
        self.assertEqual(memory_device.data_frames, serial_device.data_frames)

        request_parser = IncrementalFrameParser()
        requests = request_parser.feed(serial_device.host_bytes)
        self.assertEqual(0, request_parser.buffered_bytes)
        self.assertEqual(
            [
                FrameKind.INFO_REQUEST,
                FrameKind.INFO_REQUEST,
                FrameKind.INFO_REQUEST,
                FrameKind.CONFIGURE_REQUEST,
                FrameKind.START_REQUEST,
                FrameKind.GET_STATUS_REQUEST,
                FrameKind.STOP_REQUEST,
                FrameKind.RESET_STATS_REQUEST,
                FrameKind.GET_STATUS_REQUEST,
            ],
            [frame.header.kind for frame in requests],
        )
        self.assertEqual(
            list(range(1, len(requests) + 1)),
            [frame.header.request_id for frame in requests],
        )

        response_parser = IncrementalFrameParser()
        responses = response_parser.feed(b"".join(serial_device.response_frames))
        self.assertEqual(0, response_parser.buffered_bytes)
        self.assertEqual(
            [frame.header.request_id for frame in requests],
            [frame.header.request_id for frame in responses],
        )
        self.assertGreater(len(serial_peer.write_counts), len(requests))
        self.assertIn(0, serial_peer.write_counts)
        self.assertGreater(
            len([count for count in serial_peer.read_counts if count]), 8
        )


if __name__ == "__main__":
    unittest.main()
