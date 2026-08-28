"""Background parsing, request correlation, and bounded decoded queues."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Condition, Event, Lock, RLock, Thread, current_thread
from time import monotonic
from types import TracebackType
from typing import Literal, TypeAlias

from ._generated import protocol_constants as constants
from .models import (
    AdcBlock,
    CommandResponse,
    GpioBlock,
    ResponseValue,
    decode_message,
)
from .protocol import (
    Frame,
    IncrementalFrameParser,
    ParserCounters,
    encode_frame,
)
from .transport import (
    ByteTransport,
    TransportClosedError,
    TransportDisconnectedError,
    TransportError,
    TransportTimeoutError,
)

DataBlock: TypeAlias = AdcBlock | GpioBlock
ReaderEvent: TypeAlias = Frame


class ReaderError(RuntimeError):
    """Base error for background reader and request operations."""


class ReaderNotStartedError(ReaderError):
    """An operation needs :meth:`BackgroundReader.start` first."""


class ReaderClosedError(ReaderError):
    """The reader was explicitly closed or cancelled."""


class RequestTimeoutError(ReaderError):
    """A correlated command did not complete before its deadline."""

    def __init__(
        self,
        kind: constants.FrameKind,
        request_id: int,
        timeout: float,
    ) -> None:
        super().__init__(
            f"{kind.name} request {request_id} exceeded {timeout:g} seconds"
        )
        self.kind = kind
        self.request_id = request_id
        self.timeout = timeout


class DeviceDisconnectedError(ReaderError):
    """The device transport disappeared while the reader was active."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class ReaderProtocolError(ReaderError):
    """A decoded message or parser operation violated reader invariants."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class PendingRequestLimitError(ReaderError):
    """The bounded request map has no free entry."""


class QueueWaitTimeoutError(ReaderError):
    """No decoded queue item arrived before a bounded wait expired."""

    def __init__(self, queue_name: str, timeout: float) -> None:
        super().__init__(f"{queue_name} queue wait exceeded {timeout:g} seconds")
        self.queue_name = queue_name
        self.timeout = timeout


class StreamStoppedError(ReaderError):
    """A block wait was cancelled because the acquisition stream stopped."""


class ReaderShutdownError(ReaderError):
    """The transport or reader thread did not shut down cleanly."""


@dataclass(frozen=True, slots=True)
class ReaderCounters:
    """Immutable background-reader health and queue-accounting snapshot.

    ``host_block_queue_drops`` and ``host_event_queue_drops`` count only local
    oldest-item evictions from the decoded queues. They never include device
    sequence gaps, firmware overrun flags, or firmware status counters.
    """

    bytes_read: int
    read_calls: int
    frames_received: int
    responses_matched: int
    late_responses: int
    request_timeouts: int
    queue_wait_timeouts: int
    host_block_queue_drops: int
    host_event_queue_drops: int
    stale_blocks_discarded: int
    boundary_blocks_discarded: int
    protocol_failures: int
    disconnects: int
    pending_requests: int
    queued_blocks: int
    queued_events: int


@dataclass(slots=True)
class _PendingRequest:
    kind: constants.FrameKind
    expected_kind: constants.FrameKind
    request_id: int
    deadline: float
    timeout: float
    completed: Event = field(default_factory=Event)
    response: CommandResponse[ResponseValue] | None = None
    error: ReaderError | None = None


class BackgroundReader:
    """Own one incremental parser and continuously demultiplex a byte stream.

    Command callers may run concurrently. Each request is registered before
    its frame is written, writes are completed from partial progress under an
    overall deadline, and responses are matched solely by their echoed request
    ID. Data blocks and non-response frames use separate bounded queues. When a
    queue fills, the oldest complete decoded item is discarded so the newest
    stream state remains visible; the corresponding ``host_*_queue_drops``
    counter is incremented independently of every firmware loss signal.
    """

    def __init__(
        self,
        transport: ByteTransport,
        *,
        read_size: int = 64 * 1024,
        max_pending_requests: int = 32,
        max_queued_blocks: int = 8,
        max_queued_events: int = 32,
        request_timeout: float = 1.0,
        queue_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        parser: IncrementalFrameParser | None = None,
    ) -> None:
        integer_limits = {
            "read_size": read_size,
            "max_pending_requests": max_pending_requests,
            "max_queued_blocks": max_queued_blocks,
            "max_queued_events": max_queued_events,
        }
        if any(
            not isinstance(value, int) or value <= 0
            for value in integer_limits.values()
        ):
            raise ValueError("reader sizes and queue limits must be positive integers")
        deadlines = {
            "request_timeout": request_timeout,
            "queue_timeout": queue_timeout,
            "shutdown_timeout": shutdown_timeout,
            "idle_sleep": idle_sleep,
        }
        if any(
            not isinstance(value, (int, float)) or value <= 0
            for value in deadlines.values()
        ):
            raise ValueError("reader timeouts must be positive")

        self._transport = transport
        self._read_size = read_size
        self._max_pending_requests = max_pending_requests
        self._max_queued_blocks = max_queued_blocks
        self._max_queued_events = max_queued_events
        self._request_timeout = float(request_timeout)
        self._queue_timeout = float(queue_timeout)
        self._shutdown_timeout = float(shutdown_timeout)
        self._idle_sleep = float(idle_sleep)
        self._parser = parser if parser is not None else IncrementalFrameParser()

        self._condition = Condition(RLock())
        self._write_lock = Lock()
        self._stop_event = Event()
        self._pending: dict[int, _PendingRequest] = {}
        self._blocks: deque[DataBlock] = deque()
        self._events: deque[ReaderEvent] = deque()
        self._next_request_id = 1
        self._active_run_id = 0
        self._stream_active = False
        self._thread: Thread | None = None
        self._started = False
        self._closed = False
        self._terminal_error: ReaderError | None = None

        self._bytes_read = 0
        self._read_calls = 0
        self._frames_received = 0
        self._responses_matched = 0
        self._late_responses = 0
        self._request_timeouts = 0
        self._queue_wait_timeouts = 0
        self._host_block_queue_drops = 0
        self._host_event_queue_drops = 0
        self._stale_blocks_discarded = 0
        self._boundary_blocks_discarded = 0
        self._protocol_failures = 0
        self._disconnects = 0

    @property
    def transport(self) -> ByteTransport:
        return self._transport

    @property
    def is_running(self) -> bool:
        with self._condition:
            return (
                self._started
                and not self._closed
                and self._terminal_error is None
                and self._thread is not None
                and self._thread.is_alive()
            )

    @property
    def active_run_id(self) -> int:
        with self._condition:
            return self._active_run_id

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def parser_counters(self) -> ParserCounters:
        """Return the independent incremental-parser counter snapshot."""

        return self._parser.counters

    @property
    def counters(self) -> ReaderCounters:
        with self._condition:
            return ReaderCounters(
                bytes_read=self._bytes_read,
                read_calls=self._read_calls,
                frames_received=self._frames_received,
                responses_matched=self._responses_matched,
                late_responses=self._late_responses,
                request_timeouts=self._request_timeouts,
                queue_wait_timeouts=self._queue_wait_timeouts,
                host_block_queue_drops=self._host_block_queue_drops,
                host_event_queue_drops=self._host_event_queue_drops,
                stale_blocks_discarded=self._stale_blocks_discarded,
                boundary_blocks_discarded=self._boundary_blocks_discarded,
                protocol_failures=self._protocol_failures,
                disconnects=self._disconnects,
                pending_requests=len(self._pending),
                queued_blocks=len(self._blocks),
                queued_events=len(self._events),
            )

    def start(self) -> BackgroundReader:
        """Start the one non-daemon reader thread, idempotently."""

        with self._condition:
            if self._closed:
                raise ReaderClosedError("background reader is closed")
            if self._terminal_error is not None:
                raise self._terminal_error
            if self._started:
                return self
            if not self._transport.is_open:
                raise DeviceDisconnectedError("transport is not open")
            self._thread = Thread(
                target=self._reader_loop,
                name=f"teensy-daq-reader-{id(self):x}",
                daemon=False,
            )
            self._started = True
            self._thread.start()
        return self

    def request(
        self,
        kind: constants.FrameKind | int,
        payload: bytes | bytearray | memoryview = b"",
        *,
        timeout: float | None = None,
    ) -> CommandResponse[ResponseValue]:
        """Send one command and wait for its request-ID-correlated response."""

        try:
            selected_kind = constants.FrameKind(kind)
        except ValueError as error:
            raise ValueError(f"unknown request frame kind {int(kind)}") from error
        if selected_kind not in constants.REQUEST_RESPONSE_KIND:
            raise ValueError(f"{selected_kind.name} is not a request frame kind")
        selected_timeout = self._resolve_timeout(timeout, self._request_timeout)

        with self._condition:
            self._require_live_locked()
            if len(self._pending) >= self._max_pending_requests:
                raise PendingRequestLimitError(
                    f"at most {self._max_pending_requests} requests may be pending"
                )
            request_id = self._allocate_request_id_locked()
            pending = _PendingRequest(
                kind=selected_kind,
                expected_kind=constants.REQUEST_RESPONSE_KIND[selected_kind],
                request_id=request_id,
                deadline=monotonic() + selected_timeout,
                timeout=selected_timeout,
            )
            wire = encode_frame(
                selected_kind,
                payload,
                request_id=request_id,
            )
            self._pending[request_id] = pending

        try:
            self._write_all(wire, pending)
        except RequestTimeoutError as error:
            self._complete_with_error(pending, error, timeout=True)
        except TransportTimeoutError:
            timeout_error = RequestTimeoutError(
                selected_kind,
                request_id,
                selected_timeout,
            )
            self._complete_with_error(pending, timeout_error, timeout=True)
        except (
            TransportClosedError,
            TransportDisconnectedError,
            TransportError,
        ) as error:
            disconnected = DeviceDisconnectedError(
                f"transport failed while writing {selected_kind.name}",
                error,
            )
            self._terminate(disconnected, disconnected=True)
        except ReaderError as error:
            self._complete_with_error(pending, error)

        remaining = max(0.0, pending.deadline - monotonic())
        if not pending.completed.wait(remaining):
            self._complete_with_error(
                pending,
                RequestTimeoutError(
                    selected_kind,
                    request_id,
                    selected_timeout,
                ),
                timeout=True,
            )

        if pending.error is not None:
            raise pending.error
        if pending.response is None:
            protocol_error = ReaderProtocolError(
                f"request {request_id} completed without a response or error"
            )
            self._terminate(protocol_error, protocol_failure=True)
            raise protocol_error
        return pending.response

    def get_block(self, *, timeout: float | None = None) -> DataBlock:
        """Return the oldest queued data block using a bounded wait."""

        selected_timeout = self._resolve_timeout(timeout, self._queue_timeout)
        deadline = monotonic() + selected_timeout
        with self._condition:
            self._require_live_locked()
            while not self._blocks:
                if self._terminal_error is not None:
                    raise self._terminal_error
                if not self._stream_active:
                    raise StreamStoppedError("acquisition stream is not active")
                remaining = deadline - monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    self._queue_wait_timeouts += 1
                    raise QueueWaitTimeoutError("block", selected_timeout)
                if self._closed:
                    raise ReaderClosedError("background reader is closed")
            return self._blocks.popleft()

    def get_event(self, *, timeout: float | None = None) -> ReaderEvent:
        """Return the oldest non-response, non-data frame using a bounded wait."""

        selected_timeout = self._resolve_timeout(timeout, self._queue_timeout)
        deadline = monotonic() + selected_timeout
        with self._condition:
            self._require_live_locked()
            while not self._events:
                if self._terminal_error is not None:
                    raise self._terminal_error
                remaining = deadline - monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    self._queue_wait_timeouts += 1
                    raise QueueWaitTimeoutError("event", selected_timeout)
                if self._closed:
                    raise ReaderClosedError("background reader is closed")
            return self._events.popleft()

    def activate_run(self, run_id: int) -> None:
        """Establish an externally learned run identity and clear old blocks."""

        if not isinstance(run_id, int) or not 0 < run_id <= constants.UINT32_MAX:
            raise ValueError("active run ID must be a nonzero uint32")
        with self._condition:
            self._require_live_locked()
            self._activate_run_locked(run_id)

    def deactivate_stream(self) -> None:
        """Cancel block waiters and discard blocks at a deliberate boundary."""

        with self._condition:
            self._require_live_locked()
            self._deactivate_stream_locked()

    def close(self) -> None:
        """Cancel pending work, close the transport, and join the reader thread."""

        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._stop_event.set()
            self._fail_all_pending_locked(
                ReaderClosedError("background reader was closed")
            )
            self._blocks.clear()
            self._events.clear()
            self._stream_active = False
            self._condition.notify_all()
            thread = self._thread

        transport_error: Exception | None = None
        try:
            self._transport.close()
        except Exception as error:  # noqa: BLE001 - join even on bad transports
            transport_error = error

        if thread is not None and thread is not current_thread():
            thread.join(self._shutdown_timeout)
            if thread.is_alive():
                raise ReaderShutdownError(
                    f"reader thread did not stop within {self._shutdown_timeout:g} seconds"
                )
        if transport_error is not None:
            raise ReaderShutdownError(
                f"transport close failed: {transport_error}"
            ) from transport_error

    def __enter__(self) -> BackgroundReader:  # noqa: PYI034
        return self.start()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is None:
            self.close()
        else:
            try:
                self.close()
            except ReaderError:
                pass
        return False

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            self._expire_pending_requests()
            try:
                chunk = self._transport.read(self._read_size)
            except (
                TransportClosedError,
                TransportDisconnectedError,
                TransportError,
            ) as error:
                if self._stop_event.is_set():
                    return
                self._terminate(
                    DeviceDisconnectedError("device transport disconnected", error),
                    disconnected=True,
                )
                return

            with self._condition:
                self._read_calls += 1
                self._bytes_read += len(chunk)
            if not chunk:
                if not self._transport.is_open:
                    self._terminate(
                        DeviceDisconnectedError("device transport closed"),
                        disconnected=True,
                    )
                    return
                self._stop_event.wait(self._idle_sleep)
                continue

            try:
                frames = self._parser.feed(chunk)
            except Exception as error:  # noqa: BLE001 - parser failure ends session
                self._terminate(
                    ReaderProtocolError("incremental parser failed", error),
                    protocol_failure=True,
                )
                return

            for frame in frames:
                if self._stop_event.is_set():
                    return
                try:
                    message = decode_message(frame)
                    with self._condition:
                        self._frames_received += 1
                    if isinstance(message, CommandResponse):
                        self._dispatch_response(message)
                    elif isinstance(message, (AdcBlock, GpioBlock)):
                        self._dispatch_block(message)
                    else:
                        self._dispatch_event(message)
                except ReaderProtocolError as error:
                    self._terminate(error, protocol_failure=True)
                    return
                except Exception as error:  # noqa: BLE001 - fail all waiters cleanly
                    self._terminate(
                        ReaderProtocolError("decoded frame violated protocol", error),
                        protocol_failure=True,
                    )
                    return

    def _dispatch_response(
        self,
        response: CommandResponse[ResponseValue],
    ) -> None:
        protocol_error: ReaderProtocolError | None = None
        with self._condition:
            pending = self._pending.pop(response.request_id, None)
            if pending is None:
                self._late_responses += 1
                if (
                    response.ok
                    and response.kind is constants.FrameKind.STOP_RESPONSE
                    and response.run_id == self._active_run_id
                ):
                    self._deactivate_stream_locked()
                return

            if response.kind not in {
                pending.expected_kind,
                constants.FrameKind.ERROR_RESPONSE,
            }:
                protocol_error = ReaderProtocolError(
                    f"request {response.request_id} expected "
                    f"{pending.expected_kind.name}, received {response.kind.name}"
                )
                pending.error = protocol_error
            else:
                pending.response = response
                self._responses_matched += 1
                if response.ok and response.kind is constants.FrameKind.START_RESPONSE:
                    self._activate_run_locked(response.run_id)
                elif response.ok and response.kind is constants.FrameKind.STOP_RESPONSE:
                    self._deactivate_stream_locked()
            pending.completed.set()
            self._condition.notify_all()

        if protocol_error is not None:
            raise protocol_error

    def _dispatch_block(self, block: DataBlock) -> None:
        with self._condition:
            if not self._stream_active or block.run_id != self._active_run_id:
                self._stale_blocks_discarded += 1
                return
            if len(self._blocks) >= self._max_queued_blocks:
                self._blocks.popleft()
                self._host_block_queue_drops += 1
            self._blocks.append(block)
            self._condition.notify_all()

    def _dispatch_event(self, event: ReaderEvent) -> None:
        with self._condition:
            if len(self._events) >= self._max_queued_events:
                self._events.popleft()
                self._host_event_queue_drops += 1
            self._events.append(event)
            self._condition.notify_all()

    def _write_all(self, wire: bytes, pending: _PendingRequest) -> None:
        remaining = pending.deadline - monotonic()
        if remaining <= 0 or not self._write_lock.acquire(timeout=remaining):
            raise RequestTimeoutError(
                pending.kind,
                pending.request_id,
                pending.timeout,
            )
        try:
            offset = 0
            while offset < len(wire):
                if self._stop_event.is_set():
                    with self._condition:
                        raise self._current_error_locked()
                if monotonic() >= pending.deadline:
                    raise RequestTimeoutError(
                        pending.kind,
                        pending.request_id,
                        pending.timeout,
                    )
                written = self._transport.write(wire[offset:])
                if (
                    not isinstance(written, int)
                    or written < 0
                    or written > (len(wire) - offset)
                ):
                    raise TransportError("transport returned an invalid write count")
                if written == 0:
                    wait_time = max(
                        0.0,
                        min(self._idle_sleep, pending.deadline - monotonic()),
                    )
                    self._stop_event.wait(wait_time)
                    continue
                offset += written
        finally:
            self._write_lock.release()

    def _expire_pending_requests(self) -> None:
        now = monotonic()
        with self._condition:
            expired = [
                pending for pending in self._pending.values() if pending.deadline <= now
            ]
            for pending in expired:
                self._pending.pop(pending.request_id, None)
                if pending.response is None and pending.error is None:
                    pending.error = RequestTimeoutError(
                        pending.kind,
                        pending.request_id,
                        pending.timeout,
                    )
                    self._request_timeouts += 1
                    pending.completed.set()
            if expired:
                self._condition.notify_all()

    def _complete_with_error(
        self,
        pending: _PendingRequest,
        error: ReaderError,
        *,
        timeout: bool = False,
    ) -> None:
        with self._condition:
            if pending.response is not None or pending.error is not None:
                return
            if self._pending.get(pending.request_id) is pending:
                self._pending.pop(pending.request_id)
            pending.error = error
            if timeout:
                self._request_timeouts += 1
            pending.completed.set()
            self._condition.notify_all()

    def _terminate(
        self,
        error: ReaderError,
        *,
        protocol_failure: bool = False,
        disconnected: bool = False,
    ) -> None:
        with self._condition:
            if self._terminal_error is None and not self._closed:
                self._terminal_error = error
                if protocol_failure:
                    self._protocol_failures += 1
                if disconnected:
                    self._disconnects += 1
                self._fail_all_pending_locked(error)
            self._stream_active = False
            self._stop_event.set()
            self._condition.notify_all()

    def _fail_all_pending_locked(self, error: ReaderError) -> None:
        pending_requests = tuple(self._pending.values())
        self._pending.clear()
        for pending in pending_requests:
            if pending.response is None and pending.error is None:
                pending.error = error
                pending.completed.set()

    def _activate_run_locked(self, run_id: int) -> None:
        if run_id == 0:
            raise ReaderProtocolError("successful START established run ID zero")
        self._boundary_blocks_discarded += len(self._blocks)
        self._blocks.clear()
        self._active_run_id = run_id
        self._stream_active = True
        self._condition.notify_all()

    def _deactivate_stream_locked(self) -> None:
        self._boundary_blocks_discarded += len(self._blocks)
        self._blocks.clear()
        self._stream_active = False
        self._condition.notify_all()

    def _allocate_request_id_locked(self) -> int:
        for _ in range(self._max_pending_requests + 1):
            request_id = self._next_request_id
            self._next_request_id = (request_id + 1) & constants.UINT32_MAX
            if self._next_request_id == 0:
                self._next_request_id = 1
            if request_id not in self._pending:
                return request_id
        raise PendingRequestLimitError("no request ID is available")

    def _require_live_locked(self) -> None:
        if self._closed:
            raise ReaderClosedError("background reader is closed")
        if self._terminal_error is not None:
            raise self._terminal_error
        if not self._started:
            raise ReaderNotStartedError("background reader has not been started")

    def _current_error_locked(self) -> ReaderError:
        if self._terminal_error is not None:
            return self._terminal_error
        if self._closed:
            return ReaderClosedError("background reader is closed")
        return ReaderError("background reader was cancelled")

    @staticmethod
    def _resolve_timeout(value: float | None, default: float) -> float:
        selected = default if value is None else value
        if not isinstance(selected, (int, float)) or selected <= 0:
            raise ValueError("timeout must be positive")
        return float(selected)


__all__ = [
    "BackgroundReader",
    "DataBlock",
    "DeviceDisconnectedError",
    "PendingRequestLimitError",
    "QueueWaitTimeoutError",
    "ReaderClosedError",
    "ReaderCounters",
    "ReaderError",
    "ReaderEvent",
    "ReaderNotStartedError",
    "ReaderProtocolError",
    "ReaderShutdownError",
    "RequestTimeoutError",
    "StreamStoppedError",
]
