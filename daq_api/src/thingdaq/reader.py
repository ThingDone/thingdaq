"""Background parsing, request correlation, and bounded decoded queues."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Condition, Event, Lock, RLock, Thread, current_thread
from time import monotonic
from types import TracebackType
from typing import Literal, TypeAlias

from ._generated import protocol_constants as constants
from ._generated import protocol_v2_constants as v2_constants
from .models import (
    AdcBlock,
    CommandResponse,
    DAQConfiguration,
    GpioBlock,
    HostQueueLoss,
    ResponseValue,
    StreamAnomaly,
    decode_message,
)
from .protocol import (
    Frame,
    IncrementalFrameParser,
    ParserCounters,
    encode_frame,
)
from .protocol_v2 import (
    IncrementalV2FrameParser,
    V2Frame,
    decode_v2_message,
    encode_v2_frame,
)
from .transport import (
    ByteTransport,
    TransportClosedError,
    TransportDisconnectedError,
    TransportError,
    TransportTimeoutError,
)

DataBlock: TypeAlias = AdcBlock | GpioBlock
ReaderStreamReport: TypeAlias = HostQueueLoss | StreamAnomaly
ReaderStreamItem: TypeAlias = DataBlock | ReaderStreamReport
ReaderEvent: TypeAlias = Frame
DEFAULT_MAX_QUEUED_BLOCKS = 512


class ReaderError(RuntimeError):
    """Base error for background reader and request operations."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.reader_counters: ReaderCounters | None = None
        self.parser_counters: ParserCounters | None = None
        # The public ThingDAQ facade fills this with its last firmware and
        # loss snapshot before re-raising a terminal reader error.
        self.evidence: object | None = None


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
        super().__init__(message, cause)


class ReaderProtocolError(ReaderError):
    """A decoded message or parser operation violated reader invariants."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message, cause)


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
    readinto_calls: int = 0
    maximum_read_bytes: int = 0
    pending_request_high_water: int = 0
    block_queue_high_water: int = 0
    event_queue_high_water: int = 0
    adc_frames_received: int = 0
    gpio_frames_received: int = 0
    adc_block_queue_drops: int = 0
    gpio_block_queue_drops: int = 0
    adc_stale_blocks_discarded: int = 0
    gpio_stale_blocks_discarded: int = 0
    adc_boundary_blocks_discarded: int = 0
    gpio_boundary_blocks_discarded: int = 0
    adc_item_queue_drops: int = 0
    gpio_item_queue_drops: int = 0
    queued_loss_reports: int = 0
    loss_report_queue_drops: int = 0


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
    stream state remains visible; exact source block/item units are retained in
    a separate bounded/coalesced loss-report queue and the corresponding
    ``host_*_queue_drops`` counter remains independent of firmware loss.
    """

    def __init__(
        self,
        transport: ByteTransport,
        *,
        read_size: int = 64 * 1024,
        max_pending_requests: int = 32,
        max_queued_blocks: int = DEFAULT_MAX_QUEUED_BLOCKS,
        max_queued_events: int = 32,
        request_timeout: float = 1.0,
        queue_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        parser: IncrementalFrameParser | None = None,
        encoding: v2_constants.ConfigurationEncoding | int = (
            v2_constants.ConfigurationEncoding.RAW
        ),
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
        try:
            selected_encoding = v2_constants.ConfigurationEncoding(encoding)
        except (TypeError, ValueError) as exc:
            raise ValueError("reader encoding must be RAW or RLE_AUTO") from exc
        if (
            selected_encoding is v2_constants.ConfigurationEncoding.RLE_AUTO
            and parser is not None
        ):
            raise ValueError("a custom v1 parser cannot be used for an RLE session")

        self._transport = transport
        self._read_size = read_size
        self._max_pending_requests = max_pending_requests
        self._max_queued_blocks = max_queued_blocks
        self._max_queued_events = max_queued_events
        self._max_stream_reports = max(2, max_queued_events)
        self._request_timeout = float(request_timeout)
        self._queue_timeout = float(queue_timeout)
        self._shutdown_timeout = float(shutdown_timeout)
        self._idle_sleep = float(idle_sleep)
        self._session_encoding = selected_encoding
        self._protocol_version = (
            v2_constants.PROTOCOL_VERSION
            if selected_encoding is v2_constants.ConfigurationEncoding.RLE_AUTO
            else constants.PROTOCOL_VERSION
        )
        self._parser: IncrementalFrameParser | IncrementalV2FrameParser = (
            IncrementalV2FrameParser()
            if self._protocol_version == v2_constants.PROTOCOL_VERSION
            else (parser if parser is not None else IncrementalFrameParser())
        )
        self._read_buffer = bytearray(read_size)

        self._condition = Condition(RLock())
        self._write_lock = Lock()
        self._stop_event = Event()
        self._pending: dict[int, _PendingRequest] = {}
        self._blocks: deque[DataBlock] = deque()
        self._stream_reports: deque[ReaderStreamReport] = deque()
        self._events: deque[ReaderEvent] = deque()
        self._next_request_id = 1
        self._active_run_id = 0
        self._active_checksum_algorithm = constants.DEFAULT_CHECKSUM_ALGORITHM
        self._active_configuration_encoding = selected_encoding
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
        self._readinto_calls = 0
        self._maximum_read_bytes = 0
        self._pending_request_high_water = 0
        self._block_queue_high_water = 0
        self._event_queue_high_water = 0
        self._adc_frames_received = 0
        self._gpio_frames_received = 0
        self._adc_block_queue_drops = 0
        self._gpio_block_queue_drops = 0
        self._adc_item_queue_drops = 0
        self._gpio_item_queue_drops = 0
        self._loss_report_queue_drops = 0
        self._adc_stale_blocks_discarded = 0
        self._gpio_stale_blocks_discarded = 0
        self._adc_boundary_blocks_discarded = 0
        self._gpio_boundary_blocks_discarded = 0

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
    def terminal_error(self) -> ReaderError | None:
        """Terminal thread failure, including its captured counter evidence."""

        with self._condition:
            return self._terminal_error

    @property
    def read_buffer_size(self) -> int:
        """Fixed reusable receive-buffer capacity in bytes."""

        return len(self._read_buffer)

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
                readinto_calls=self._readinto_calls,
                maximum_read_bytes=self._maximum_read_bytes,
                pending_request_high_water=self._pending_request_high_water,
                block_queue_high_water=self._block_queue_high_water,
                event_queue_high_water=self._event_queue_high_water,
                adc_frames_received=self._adc_frames_received,
                gpio_frames_received=self._gpio_frames_received,
                adc_block_queue_drops=self._adc_block_queue_drops,
                gpio_block_queue_drops=self._gpio_block_queue_drops,
                adc_stale_blocks_discarded=self._adc_stale_blocks_discarded,
                gpio_stale_blocks_discarded=self._gpio_stale_blocks_discarded,
                adc_boundary_blocks_discarded=(self._adc_boundary_blocks_discarded),
                gpio_boundary_blocks_discarded=(self._gpio_boundary_blocks_discarded),
                adc_item_queue_drops=self._adc_item_queue_drops,
                gpio_item_queue_drops=self._gpio_item_queue_drops,
                queued_loss_reports=len(self._stream_reports),
                loss_report_queue_drops=self._loss_report_queue_drops,
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
                name=f"thingdaq-reader-{id(self):x}",
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
            if self._protocol_version == v2_constants.PROTOCOL_VERSION:
                wire = encode_v2_frame(
                    selected_kind,
                    payload,
                    request_id=request_id,
                )
            else:
                wire = encode_frame(
                    selected_kind,
                    payload,
                    request_id=request_id,
                )
            self._pending[request_id] = pending
            self._pending_request_high_water = max(
                self._pending_request_high_water,
                len(self._pending),
            )

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
            if not self._blocks and self._stream_active:
                request_stream_frame = getattr(
                    self._transport,
                    "request_stream_frame",
                    None,
                )
                if callable(request_stream_frame):
                    try:
                        request_stream_frame()
                    except TransportError as error:
                        raise DeviceDisconnectedError(
                            "simulated stream request failed",
                            error,
                        ) from error
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

    def get_stream_item(
        self,
        *,
        timeout: float | None = None,
    ) -> ReaderStreamItem:
        """Return a loss report before the oldest retained application block.

        This facade-facing operation preserves :meth:`get_block` for callers
        that intentionally consume only decoded blocks. Loss reports use their
        own bounded/coalesced queue and therefore never stop serial draining.
        """

        selected_timeout = self._resolve_timeout(timeout, self._queue_timeout)
        deadline = monotonic() + selected_timeout
        with self._condition:
            self._require_live_locked()
            if not self._stream_reports and not self._blocks and self._stream_active:
                request_stream_frame = getattr(
                    self._transport,
                    "request_stream_frame",
                    None,
                )
                if callable(request_stream_frame):
                    try:
                        request_stream_frame()
                    except TransportError as error:
                        raise DeviceDisconnectedError(
                            "simulated stream request failed",
                            error,
                        ) from error
            while not self._stream_reports and not self._blocks:
                if self._terminal_error is not None:
                    raise self._terminal_error
                if not self._stream_active:
                    raise StreamStoppedError("acquisition stream is not active")
                remaining = deadline - monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    self._queue_wait_timeouts += 1
                    raise QueueWaitTimeoutError("stream", selected_timeout)
                if self._closed:
                    raise ReaderClosedError("background reader is closed")
            if self._stream_reports:
                return self._stream_reports.popleft()
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

    def activate_run(
        self,
        run_id: int,
        checksum_algorithm: constants.ChecksumAlgorithm = (
            constants.DEFAULT_CHECKSUM_ALGORITHM
        ),
        encoding: v2_constants.ConfigurationEncoding | int = (
            v2_constants.ConfigurationEncoding.RAW
        ),
    ) -> None:
        """Establish an externally learned run identity and clear old blocks."""

        if not isinstance(run_id, int) or not 0 < run_id <= constants.UINT32_MAX:
            raise ValueError("active run ID must be a nonzero uint32")
        if isinstance(checksum_algorithm, bool):
            raise TypeError("active checksum algorithm is not supported")
        try:
            selected_checksum = constants.ChecksumAlgorithm(checksum_algorithm)
        except ValueError as exc:
            raise ValueError("active checksum algorithm is not supported") from exc
        if selected_checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError("active checksum algorithm is not supported")
        try:
            selected_encoding = v2_constants.ConfigurationEncoding(encoding)
        except (TypeError, ValueError) as exc:
            raise ValueError("active encoding must be RAW or RLE_AUTO") from exc
        if selected_encoding is not self._session_encoding:
            raise ValueError("active encoding differs from the reader session")
        with self._condition:
            self._require_live_locked()
            self._activate_run_locked(
                run_id,
                selected_checksum,
                selected_encoding,
            )

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
            self._stream_reports.clear()
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
                shutdown_error = ReaderShutdownError(
                    f"reader thread did not stop within {self._shutdown_timeout:g} seconds"
                )
                self._attach_evidence(shutdown_error)
                raise shutdown_error
        if transport_error is not None:
            shutdown_error = ReaderShutdownError(
                f"transport close failed: {transport_error}"
            )
            self._attach_evidence(shutdown_error)
            raise shutdown_error from transport_error

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
            reusable_chunk: memoryview | None = None
            try:
                readinto = getattr(self._transport, "readinto", None)
                if callable(readinto):
                    received = readinto(self._read_buffer)
                    if (
                        not isinstance(received, int)
                        or isinstance(received, bool)
                        or not 0 <= received <= self._read_size
                    ):
                        raise TransportError(
                            "transport returned an invalid readinto count"
                        )
                    reusable_chunk = memoryview(self._read_buffer)[:received]
                    chunk: bytes | memoryview = reusable_chunk
                    used_readinto = True
                else:
                    chunk = self._transport.read(self._read_size)
                    if len(chunk) > self._read_size:
                        raise TransportError(
                            "transport returned more bytes than requested"
                        )
                    used_readinto = False
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
                self._maximum_read_bytes = max(
                    self._maximum_read_bytes,
                    len(chunk),
                )
                if used_readinto:
                    self._readinto_calls += 1
            if not chunk:
                if reusable_chunk is not None:
                    reusable_chunk.release()
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
            finally:
                if reusable_chunk is not None:
                    reusable_chunk.release()

            for frame in frames:
                if self._stop_event.is_set():
                    return
                try:
                    if isinstance(frame, V2Frame):
                        message = decode_v2_message(
                            frame,
                            negotiated_encoding=(self._active_configuration_encoding),
                        )
                    else:
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
                    if not isinstance(response.value, DAQConfiguration):
                        protocol_error = ReaderProtocolError(
                            "successful START response omitted its configuration"
                        )
                        pending.error = protocol_error
                    else:
                        self._activate_run_locked(
                            response.run_id,
                            response.value.data_checksum_algorithm,
                            response.value.encoding,
                        )
                elif response.ok and response.kind is constants.FrameKind.STOP_RESPONSE:
                    self._deactivate_stream_locked()
            pending.completed.set()
            self._condition.notify_all()

        if protocol_error is not None:
            raise protocol_error

    def _dispatch_block(
        self,
        block: DataBlock,
    ) -> None:
        with self._condition:
            if isinstance(block, AdcBlock):
                self._adc_frames_received += 1
            else:
                self._gpio_frames_received += 1
            if not self._stream_active or block.run_id != self._active_run_id:
                self._stale_blocks_discarded += 1
                if isinstance(block, AdcBlock):
                    self._adc_stale_blocks_discarded += 1
                else:
                    self._gpio_stale_blocks_discarded += 1
                if self._stream_active:
                    self._enqueue_stream_report_locked(
                        StreamAnomaly.stale_run(
                            block,
                            active_run_id=self._active_run_id,
                        )
                    )
                    self._condition.notify_all()
                return
            if block.checksum_algorithm != self._active_checksum_algorithm:
                raise ReaderProtocolError(
                    f"run {block.run_id} data used "
                    f"{block.checksum_algorithm.name}; "
                    f"configured algorithm is {self._active_checksum_algorithm.name}"
                )
            if len(self._blocks) >= self._max_queued_blocks:
                dropped = self._blocks.popleft()
                self._enqueue_stream_report_locked(HostQueueLoss.from_block(dropped))
                self._host_block_queue_drops += 1
                if isinstance(dropped, AdcBlock):
                    self._adc_block_queue_drops += 1
                    self._adc_item_queue_drops += dropped.item_count
                else:
                    self._gpio_block_queue_drops += 1
                    self._gpio_item_queue_drops += dropped.item_count
            self._blocks.append(block)
            self._block_queue_high_water = max(
                self._block_queue_high_water,
                len(self._blocks),
            )
            self._condition.notify_all()

    def _enqueue_stream_report_locked(self, report: ReaderStreamReport) -> None:
        """Coalesce same-source reports before using bounded report storage."""

        for index in range(len(self._stream_reports) - 1, -1, -1):
            existing = self._stream_reports[index]
            if isinstance(existing, HostQueueLoss) and isinstance(
                report, HostQueueLoss
            ):
                if (
                    existing.kind is report.kind
                    and existing.source is report.source
                    and existing.run_id == report.run_id
                ):
                    self._stream_reports[index] = existing.aggregated_with(report)
                    return
            elif isinstance(existing, StreamAnomaly) and isinstance(
                report, StreamAnomaly
            ):
                try:
                    self._stream_reports[index] = existing.merged_with(report)
                except ValueError:
                    continue
                return

        if len(self._stream_reports) >= self._max_stream_reports:
            anomaly_index = next(
                (
                    index
                    for index, queued in enumerate(self._stream_reports)
                    if isinstance(queued, StreamAnomaly)
                ),
                None,
            )
            if anomaly_index is None:
                # At most one active-run HostQueueLoss exists per source, so a
                # two-entry all-host queue is already exact and complete.
                self._loss_report_queue_drops += 1
                return
            del self._stream_reports[anomaly_index]
            self._loss_report_queue_drops += 1
        self._stream_reports.append(report)

    def _dispatch_event(self, event: ReaderEvent) -> None:
        with self._condition:
            if len(self._events) >= self._max_queued_events:
                self._events.popleft()
                self._host_event_queue_drops += 1
            self._events.append(event)
            self._event_queue_high_water = max(
                self._event_queue_high_water,
                len(self._events),
            )
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
                self._attach_evidence(error)
            self._stream_active = False
            self._stop_event.set()
            self._condition.notify_all()

    def _attach_evidence(self, error: ReaderError) -> None:
        error.reader_counters = self.counters
        error.parser_counters = self._parser.counters

    def _fail_all_pending_locked(self, error: ReaderError) -> None:
        pending_requests = tuple(self._pending.values())
        self._pending.clear()
        for pending in pending_requests:
            if pending.response is None and pending.error is None:
                pending.error = error
                pending.completed.set()

    def _activate_run_locked(
        self,
        run_id: int,
        checksum_algorithm: constants.ChecksumAlgorithm,
        encoding: v2_constants.ConfigurationEncoding,
    ) -> None:
        if run_id == 0:
            raise ReaderProtocolError("successful START established run ID zero")
        if checksum_algorithm not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ReaderProtocolError(
                "successful START selected an unsupported checksum algorithm"
            )
        if encoding is not self._session_encoding:
            raise ReaderProtocolError(
                "successful START selected an encoding outside this session"
            )
        self._record_boundary_blocks_locked()
        self._blocks.clear()
        self._stream_reports.clear()
        self._active_run_id = run_id
        self._active_checksum_algorithm = checksum_algorithm
        self._active_configuration_encoding = encoding
        self._stream_active = True
        self._condition.notify_all()

    def _deactivate_stream_locked(self) -> None:
        self._record_boundary_blocks_locked()
        self._blocks.clear()
        self._stream_reports.clear()
        self._stream_active = False
        self._active_checksum_algorithm = constants.DEFAULT_CHECKSUM_ALGORITHM
        self._active_configuration_encoding = self._session_encoding
        self._condition.notify_all()

    def _record_boundary_blocks_locked(self) -> None:
        self._boundary_blocks_discarded += len(self._blocks)
        for block in self._blocks:
            if isinstance(block, AdcBlock):
                self._adc_boundary_blocks_discarded += 1
            else:
                self._gpio_boundary_blocks_discarded += 1

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
    "DEFAULT_MAX_QUEUED_BLOCKS",
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
    "ReaderStreamItem",
    "ReaderStreamReport",
    "RequestTimeoutError",
    "StreamStoppedError",
]
