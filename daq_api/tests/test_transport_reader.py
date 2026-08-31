"""Focused tests for bounded serial I/O and background reader primitives."""

from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Callable

import serial
from thingdaq import (
    BackgroundReader,
    ByteTransport,
    CommandResponse,
    Configuration,
    DeviceDisconnectedError,
    Frame,
    FrameFlag,
    FrameKind,
    IncrementalFrameParser,
    Info,
    InMemoryTransport,
    PendingRequestLimitError,
    ReaderClosedError,
    ReaderProtocolError,
    RequestTimeoutError,
    SerialPortBusyError,
    SerialTransport,
    SimulatedDevice,
    Source,
    StreamMask,
    StreamStoppedError,
    TransportClosedError,
    TransportDisconnectedError,
    TransportTimeoutError,
    encode_frame,
    synthetic_adc_payload,
)
from thingdaq._generated import protocol_constants as constants
from thingdaq.models import ResponseValue


def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true before its deadline")
        time.sleep(0.001)


class FakeSerial:
    """Small PySerial-shaped object used without opening host hardware."""

    def __init__(
        self,
        incoming: bytes = b"",
        *,
        write_limit: int | None = None,
    ) -> None:
        self._incoming = bytearray(incoming)
        self._is_open = True
        self.write_limit = write_limit
        self.written = bytearray()
        self.flush_calls = 0
        self.cancel_read_calls = 0
        self.cancel_write_calls = 0
        self.closed = threading.Event()

    @property
    def is_open(self) -> bool:
        return self._is_open

    def read(self, size: int = 1) -> bytes:
        returned = min(size, len(self._incoming))
        result = bytes(self._incoming[:returned])
        del self._incoming[:returned]
        return result

    def write(self, data: bytes | bytearray | memoryview) -> int:
        view = memoryview(data).cast("B")
        try:
            accepted = len(view)
            if self.write_limit is not None:
                accepted = min(accepted, self.write_limit)
            self.written.extend(view[:accepted])
            return accepted
        finally:
            view.release()

    def flush(self) -> None:
        self.flush_calls += 1

    def cancel_read(self) -> None:
        self.cancel_read_calls += 1

    def cancel_write(self) -> None:
        self.cancel_write_calls += 1

    def close(self) -> None:
        self._is_open = False
        self.closed.set()


class BlockingFlushSerial(FakeSerial):
    def __init__(self) -> None:
        super().__init__()
        self.flush_release = threading.Event()

    def flush(self) -> None:
        self.flush_calls += 1
        self.flush_release.wait(1.0)

    def cancel_write(self) -> None:
        super().cancel_write()
        self.flush_release.set()


class BlockingCloseSerial(FakeSerial):
    def __init__(self) -> None:
        super().__init__()
        self.close_entered = threading.Event()
        self.close_release = threading.Event()

    def close(self) -> None:
        self.close_entered.set()
        self.close_release.wait(1.0)
        super().close()


class FailingReadSerial(FakeSerial):
    def read(self, size: int = 1) -> bytes:
        raise serial.SerialException("device vanished")


class ControlledTransport:
    """Thread-safe byte stream whose device-to-host bytes are test-controlled."""

    def __init__(
        self,
        *,
        read_chunk_size: int = 65_536,
        write_chunk_size: int = 3,
    ) -> None:
        self._condition = threading.Condition()
        self._incoming = bytearray()
        self._request_parser = IncrementalFrameParser()
        self._requests: list[Frame] = []
        self._is_open = True
        self._disconnected = False
        self._read_chunk_size = read_chunk_size
        self._write_chunk_size = write_chunk_size
        self.read_sizes: list[int] = []
        self.flush_calls = 0

    @property
    def is_open(self) -> bool:
        with self._condition:
            return self._is_open

    @property
    def requests(self) -> tuple[Frame, ...]:
        with self._condition:
            return tuple(self._requests)

    def write(self, data: bytes | bytearray | memoryview) -> int:
        view = memoryview(data).cast("B")
        try:
            with self._condition:
                self._require_open()
                accepted = min(len(view), self._write_chunk_size)
                self._requests.extend(self._request_parser.feed(view[:accepted]))
                self._condition.notify_all()
                return accepted
        finally:
            view.release()

    def read(self, size: int) -> bytes:
        with self._condition:
            self.read_sizes.append(size)
            if not self._incoming and self._is_open:
                self._condition.wait(0.01)
            self._require_open()
            returned = min(size, self._read_chunk_size, len(self._incoming))
            result = bytes(self._incoming[:returned])
            del self._incoming[:returned]
            return result

    def flush(self) -> None:
        with self._condition:
            self._require_open()
            self.flush_calls += 1

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
            self._incoming.extend(wire)
            self._condition.notify_all()

    def wait_for_requests(
        self,
        count: int,
        timeout: float = 1.0,
    ) -> tuple[Frame, ...]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self._requests) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    raise AssertionError(
                        f"only received {len(self._requests)} requests"
                    )
            return tuple(self._requests)

    def _require_open(self) -> None:
        if self._is_open:
            return
        if self._disconnected:
            raise TransportDisconnectedError("controlled device disconnected")
        raise TransportClosedError("controlled transport is closed")


class FailingParser(IncrementalFrameParser):
    def feed(
        self,
        chunk: bytes | bytearray | memoryview,
    ) -> list[Frame]:
        raise RuntimeError("injected parser failure")


def _adc_wire(
    run_id: int,
    sequence: int,
    checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    ),
) -> bytes:
    flags = FrameFlag.SYNTHETIC
    if sequence == 0:
        flags |= FrameFlag.EPOCH_START
    first_sample_ticks = sequence * constants.FRAME_COVERAGE_TICKS
    return encode_frame(
        FrameKind.ADC_DATA,
        synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME),
        flags=flags,
        checksum_algorithm=checksum_algorithm,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=first_sample_ticks,
        item_count=constants.ADC_PAIRS_PER_FRAME,
    )


class SerialTransportTests(unittest.TestCase):
    def test_readinto_falls_back_when_serial_factory_only_exposes_read(self) -> None:
        fake = FakeSerial(b"abcdef")
        transport = SerialTransport(
            "read-only-factory",
            serial_factory=lambda **options: fake,
        )
        storage = bytearray(4)

        self.assertEqual(4, transport.readinto(storage))
        self.assertEqual(b"abcd", storage)
        transport.close()

    def test_large_reads_partial_writes_flush_and_close_are_bounded(self) -> None:
        fake = FakeSerial(b"x" * 70_000, write_limit=3)
        captured: dict[str, object] = {}

        def factory(**options: object) -> FakeSerial:
            captured.update(options)
            return fake

        transport = SerialTransport(
            "COM42",
            open_timeout=0.2,
            read_timeout=0.02,
            write_timeout=0.03,
            exclusive=True,
            serial_factory=factory,
        )

        self.assertIsInstance(transport, ByteTransport)
        self.assertEqual("COM42", captured["port"])
        self.assertEqual(0.02, captured["timeout"])
        self.assertEqual(0.03, captured["write_timeout"])
        self.assertIs(True, captured["exclusive"])
        self.assertEqual(65_536, len(transport.read(65_536)))
        self.assertEqual(3, transport.write(b"abcdef"))
        self.assertEqual(b"abc", fake.written)
        transport.flush()
        self.assertEqual(1, fake.flush_calls)

        transport.close()
        transport.close()
        self.assertFalse(transport.is_open)
        self.assertEqual(1, fake.cancel_read_calls)
        self.assertEqual(1, fake.cancel_write_calls)
        with self.assertRaises(TransportClosedError):
            transport.read(1)

    def test_open_timeout_closes_a_port_that_returns_late(self) -> None:
        release = threading.Event()
        entered = threading.Event()
        late_serial = FakeSerial()

        def slow_factory(**options: object) -> FakeSerial:
            entered.set()
            release.wait(1.0)
            return late_serial

        with self.assertRaises(TransportTimeoutError):
            SerialTransport(
                "late-port",
                open_timeout=0.02,
                serial_factory=slow_factory,
            )
        self.assertTrue(entered.is_set())
        release.set()
        self.assertTrue(late_serial.closed.wait(1.0))

    def test_flush_timeout_cancels_io_and_closes_the_transport(self) -> None:
        fake = BlockingFlushSerial()
        transport = SerialTransport(
            "blocked-flush",
            flush_timeout=0.02,
            serial_factory=lambda **options: fake,
        )

        with self.assertRaises(TransportTimeoutError):
            transport.flush()

        self.assertFalse(transport.is_open)
        self.assertEqual(1, fake.cancel_write_calls)
        self.assertTrue(fake.closed.is_set())

    def test_close_returns_a_typed_error_at_its_deadline(self) -> None:
        fake = BlockingCloseSerial()
        transport = SerialTransport(
            "blocked-close",
            close_timeout=0.02,
            serial_factory=lambda **options: fake,
        )

        with self.assertRaises(TransportTimeoutError):
            transport.close()

        self.assertTrue(fake.close_entered.is_set())
        self.assertFalse(transport.is_open)
        fake.close_release.set()
        self.assertTrue(fake.closed.wait(1.0))

    def test_pyserial_failures_have_typed_open_and_disconnect_errors(self) -> None:
        def rejected_factory(**options: object) -> FakeSerial:
            raise serial.SerialException("access denied")

        with self.assertRaises(SerialPortBusyError):
            SerialTransport("denied", serial_factory=rejected_factory)

        transport = SerialTransport(
            "vanishing",
            serial_factory=lambda **options: FailingReadSerial(),
        )
        with self.assertRaises(TransportDisconnectedError):
            transport.read(65_536)
        transport.close()


class BackgroundReaderTests(unittest.TestCase):
    def test_reader_runs_the_existing_simulator_transport_through_stop(self) -> None:
        transport = InMemoryTransport(read_chunk_size=73, write_chunk_size=3)
        configuration = Configuration(
            stream_mask=StreamMask.ADC | StreamMask.GPIO,
            source=Source.SYNTHETIC,
        )

        with BackgroundReader(
            transport,
            max_queued_blocks=4,
            request_timeout=1.0,
        ) as reader:
            configured = reader.request(
                FrameKind.CONFIGURE_REQUEST,
                configuration.to_payload(),
            )
            started = reader.request(FrameKind.START_REQUEST)
            block = reader.get_block(timeout=0.5)
            status = reader.request(FrameKind.GET_STATUS_REQUEST)
            stopped = reader.request(FrameKind.STOP_REQUEST)

            self.assertEqual(FrameKind.CONFIGURE_RESPONSE, configured.kind)
            self.assertEqual(FrameKind.START_RESPONSE, started.kind)
            self.assertEqual(started.run_id, block.run_id)
            self.assertEqual(FrameKind.GET_STATUS_RESPONSE, status.kind)
            self.assertEqual(FrameKind.STOP_RESPONSE, stopped.kind)
            self.assertEqual(4, reader.counters.responses_matched)
            with self.assertRaises(StreamStoppedError):
                reader.get_block(timeout=0.1)

        self.assertFalse(transport.is_open)

    def test_reordered_concurrent_responses_match_across_arbitrary_chunks(self) -> None:
        transport = ControlledTransport(read_chunk_size=7, write_chunk_size=2)
        device = SimulatedDevice()
        results: dict[str, CommandResponse[ResponseValue]] = {}
        failures: list[BaseException] = []

        def request(name: str, kind: FrameKind, payload: bytes = b"") -> None:
            try:
                results[name] = reader.request(kind, payload, timeout=1.0)
            except Exception as error:  # noqa: BLE001 - report from test thread
                failures.append(error)

        with BackgroundReader(transport, read_size=65_536) as reader:
            info_thread = threading.Thread(
                target=request,
                args=("info", FrameKind.INFO_REQUEST),
            )
            nonce = 0x0123456789ABCDEF
            ping_thread = threading.Thread(
                target=request,
                args=("ping", FrameKind.PING_REQUEST, nonce.to_bytes(8, "little")),
            )
            info_thread.start()
            ping_thread.start()
            requests = transport.wait_for_requests(2)
            by_kind = {frame.header.kind: frame for frame in requests}
            info_response = device.receive(by_kind[FrameKind.INFO_REQUEST].to_bytes())[
                0
            ]
            ping_response = device.receive(by_kind[FrameKind.PING_REQUEST].to_bytes())[
                0
            ]

            reader.activate_run(7)
            # Reverse command order and interleave a full data frame. The fake
            # then fragments this combined stream into seven-byte reads.
            transport.inject(ping_response + _adc_wire(7, 0) + info_response)
            info_thread.join(1.0)
            ping_thread.join(1.0)

            self.assertFalse(info_thread.is_alive())
            self.assertFalse(ping_thread.is_alive())
            self.assertEqual([], failures)
            info = results["info"]
            ping = results["ping"]
            self.assertIsInstance(info.value, Info)
            self.assertEqual(nonce, ping.value)
            self.assertEqual(0, reader.get_block(timeout=0.5).sequence)
            counters = reader.counters
            self.assertEqual(2, counters.responses_matched)
            self.assertEqual(0, counters.late_responses)
            self.assertEqual(0, counters.pending_requests)
            self.assertEqual(65_536, transport.read_sizes[0])

    def test_pending_bound_deadline_cleanup_and_late_response_accounting(
        self,
    ) -> None:
        transport = ControlledTransport()
        failures: list[BaseException] = []

        with BackgroundReader(
            transport,
            max_pending_requests=1,
            request_timeout=0.2,
        ) as reader:

            def wait_for_info() -> None:
                try:
                    reader.request(FrameKind.INFO_REQUEST)
                except Exception as error:  # noqa: BLE001 - report from test thread
                    failures.append(error)

            request_thread = threading.Thread(target=wait_for_info)
            request_thread.start()
            request_frame = transport.wait_for_requests(1)[0]

            with self.assertRaises(PendingRequestLimitError):
                reader.request(FrameKind.PING_REQUEST, bytes(8))

            request_thread.join(1.0)
            self.assertFalse(request_thread.is_alive())
            self.assertEqual(1, len(failures))
            self.assertIsInstance(failures[0], RequestTimeoutError)
            self.assertEqual(0, reader.pending_count)
            self.assertEqual(1, reader.counters.request_timeouts)

            response = SimulatedDevice().receive(request_frame.to_bytes())[0]
            transport.inject(response)
            _wait_until(lambda: reader.counters.late_responses == 1)
            self.assertEqual(0, reader.counters.responses_matched)

    def test_drop_oldest_queues_have_separate_host_only_counters(self) -> None:
        transport = ControlledTransport()
        with BackgroundReader(
            transport,
            max_queued_blocks=2,
            max_queued_events=2,
        ) as reader:
            reader.activate_run(11)
            block_wire = b"".join(_adc_wire(11, sequence) for sequence in range(3))
            event_wire = b"".join(
                encode_frame(FrameKind.INFO_REQUEST, request_id=100 + index)
                for index in range(3)
            )
            transport.inject(block_wire + event_wire)
            _wait_until(lambda: reader.counters.frames_received == 6)

            self.assertEqual(
                [1, 2],
                [
                    reader.get_block(timeout=0.2).sequence,
                    reader.get_block(timeout=0.2).sequence,
                ],
            )
            self.assertEqual(
                [101, 102],
                [
                    reader.get_event(timeout=0.2).header.request_id,
                    reader.get_event(timeout=0.2).header.request_id,
                ],
            )
            counters = reader.counters
            self.assertEqual(1, counters.host_block_queue_drops)
            self.assertEqual(1, counters.host_event_queue_drops)
            self.assertEqual(0, reader.parser_counters.corruption_events)

            transport.inject(_adc_wire(12, 0))
            _wait_until(lambda: reader.counters.stale_blocks_discarded == 1)
            self.assertEqual(1, reader.counters.host_block_queue_drops)

    def test_active_run_rejects_a_valid_frame_with_the_wrong_algorithm(self) -> None:
        transport = ControlledTransport()
        with BackgroundReader(transport) as reader:
            reader.activate_run(13, constants.ChecksumAlgorithm.CRC32C)
            transport.inject(_adc_wire(13, 0, constants.ChecksumAlgorithm.CRC32C))
            self.assertEqual(0, reader.get_block(timeout=0.5).sequence)

            transport.inject(
                _adc_wire(13, 1, constants.ChecksumAlgorithm.CRC32_ISO_HDLC)
            )
            _wait_until(lambda: not reader.is_running)
            with self.assertRaisesRegex(ReaderProtocolError, "configured algorithm"):
                reader.get_block(timeout=0.1)
            self.assertEqual(1, reader.counters.protocol_failures)

    def test_stop_response_cancels_a_block_waiter(self) -> None:
        transport = ControlledTransport()
        device = SimulatedDevice()
        block_failures: list[BaseException] = []
        stop_failures: list[BaseException] = []

        with BackgroundReader(transport) as reader:
            reader.activate_run(9)
            waiter_entered = threading.Event()

            def wait_for_block() -> None:
                waiter_entered.set()
                try:
                    reader.get_block(timeout=1.0)
                except Exception as error:  # noqa: BLE001 - report from test thread
                    block_failures.append(error)

            def stop() -> None:
                try:
                    reader.request(FrameKind.STOP_REQUEST, timeout=1.0)
                except Exception as error:  # noqa: BLE001 - report from test thread
                    stop_failures.append(error)

            block_thread = threading.Thread(target=wait_for_block)
            block_thread.start()
            self.assertTrue(waiter_entered.wait(0.5))
            stop_thread = threading.Thread(target=stop)
            stop_thread.start()
            stop_request = transport.wait_for_requests(1)[0]
            transport.inject(device.receive(stop_request.to_bytes())[0])
            block_thread.join(1.0)
            stop_thread.join(1.0)

            self.assertFalse(block_thread.is_alive())
            self.assertFalse(stop_thread.is_alive())
            self.assertEqual([], stop_failures)
            self.assertEqual(1, len(block_failures))
            self.assertIsInstance(block_failures[0], StreamStoppedError)

    def test_disconnect_fails_pending_request_and_stops_reader(self) -> None:
        transport = ControlledTransport()
        failures: list[BaseException] = []

        with BackgroundReader(transport) as reader:

            def request_info() -> None:
                try:
                    reader.request(FrameKind.INFO_REQUEST, timeout=1.0)
                except Exception as error:  # noqa: BLE001 - report from test thread
                    failures.append(error)

            request_thread = threading.Thread(target=request_info)
            request_thread.start()
            transport.wait_for_requests(1)
            transport.disconnect()
            request_thread.join(1.0)
            _wait_until(lambda: not reader.is_running)

            self.assertFalse(request_thread.is_alive())
            self.assertEqual(1, len(failures))
            self.assertIsInstance(failures[0], DeviceDisconnectedError)
            disconnect = failures[0]
            assert isinstance(disconnect, DeviceDisconnectedError)
            self.assertIsNotNone(disconnect.reader_counters)
            self.assertIsNotNone(disconnect.parser_counters)
            assert disconnect.reader_counters is not None
            self.assertEqual(1, disconnect.reader_counters.disconnects)
            self.assertEqual(0, reader.pending_count)
            self.assertEqual(1, reader.counters.disconnects)

    def test_parser_failure_is_typed_and_cancels_the_session(self) -> None:
        transport = ControlledTransport()
        reader = BackgroundReader(transport, parser=FailingParser())
        failures: list[BaseException] = []
        reader.start()
        try:

            def request_info() -> None:
                try:
                    reader.request(FrameKind.INFO_REQUEST, timeout=1.0)
                except Exception as error:  # noqa: BLE001 - report from test thread
                    failures.append(error)

            request_thread = threading.Thread(target=request_info)
            request_thread.start()
            transport.wait_for_requests(1)
            transport.inject(b"trigger parser")
            request_thread.join(1.0)
            _wait_until(lambda: not reader.is_running)

            self.assertFalse(request_thread.is_alive())
            self.assertEqual(1, len(failures))
            self.assertIsInstance(failures[0], ReaderProtocolError)
            parser_failure = failures[0]
            assert isinstance(parser_failure, ReaderProtocolError)
            self.assertIsNotNone(parser_failure.reader_counters)
            self.assertIsNotNone(parser_failure.parser_counters)
            assert parser_failure.reader_counters is not None
            self.assertEqual(1, parser_failure.reader_counters.protocol_failures)
            with self.assertRaises(ReaderProtocolError) as repeated:
                reader.request(FrameKind.INFO_REQUEST)
            self.assertIs(repeated.exception, parser_failure)
            self.assertEqual(1, reader.counters.protocol_failures)
            self.assertEqual(0, reader.pending_count)
        finally:
            reader.close()

    def test_close_cancels_a_pending_request_before_joining(self) -> None:
        transport = ControlledTransport()
        reader = BackgroundReader(transport)
        failures: list[BaseException] = []
        reader.start()

        def request_info() -> None:
            try:
                reader.request(FrameKind.INFO_REQUEST, timeout=1.0)
            except Exception as error:  # noqa: BLE001 - report from test thread
                failures.append(error)

        request_thread = threading.Thread(target=request_info)
        request_thread.start()
        transport.wait_for_requests(1)
        reader.close()
        request_thread.join(1.0)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], ReaderClosedError)
        self.assertEqual(0, reader.pending_count)
        self.assertFalse(reader.is_running)

    def test_context_manager_closes_transport_and_joins_reader(self) -> None:
        transport = ControlledTransport()
        with BackgroundReader(transport) as reader:
            self.assertTrue(reader.is_running)

        self.assertFalse(transport.is_open)
        self.assertFalse(reader.is_running)
        with self.assertRaises(TransportClosedError):
            transport.read(1)


if __name__ == "__main__":
    unittest.main()
