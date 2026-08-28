"""Bounded byte transports for serial hardware and the local simulator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock, RLock, Thread
from time import monotonic
from types import TracebackType
from typing import Literal, Protocol, cast, runtime_checkable

import serial

from ._generated import protocol_constants as constants
from .simulator import SimulatedDevice

BytesLike = bytes | bytearray | memoryview


class TransportError(RuntimeError):
    """Base error for byte-transport failures."""


class TransportClosedError(TransportError):
    """An operation was attempted after the transport closed."""


class TransportTimeoutError(TransportError):
    """A bounded transport operation exceeded its configured deadline."""


class TransportOpenError(TransportError):
    """A serial port could not be opened."""


class TransportDisconnectedError(TransportError):
    """The byte stream disappeared or failed during I/O."""


class TransportBufferError(TransportError):
    """The bounded in-memory receive queue cannot accept another response."""


@runtime_checkable
class ByteTransport(Protocol):
    """Minimal synchronous byte stream required by the protocol reader.

    Implementations bound every individual operation. ``write`` is allowed to
    make partial progress; callers that require a complete frame must retry the
    unwritten suffix against their own overall deadline.
    """

    @property
    def is_open(self) -> bool:
        """Whether reads and writes are currently permitted."""

        ...

    def write(self, data: BytesLike) -> int:
        """Write up to ``len(data)`` bytes and return the accepted count."""

        ...

    def read(self, size: int) -> bytes:
        """Return at most ``size`` bytes, or ``b\"\"`` at the read deadline."""

        ...

    def flush(self) -> None:
        """Boundedly wait for accepted output to leave the transport."""

        ...

    def close(self) -> None:
        """Cancel outstanding I/O and release resources, idempotently."""

        ...


Transport = ByteTransport


class _SerialPort(Protocol):
    """Subset of PySerial used by :class:`SerialTransport`."""

    @property
    def is_open(self) -> bool: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: BytesLike) -> int | None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


SerialFactory = Callable[..., _SerialPort]


@dataclass(slots=True)
class _OpenAttempt:
    """Shared state that closes a port if its bounded opener times out."""

    done: Event = field(default_factory=Event)
    lock: Lock = field(default_factory=Lock)
    serial_port: _SerialPort | None = None
    error: BaseException | None = None
    cancelled: bool = False


@dataclass(slots=True)
class _VoidAttempt:
    """Completion state for a bounded flush or close helper."""

    done: Event = field(default_factory=Event)
    error: BaseException | None = None


def _default_serial_factory(
    *,
    port: str,
    baudrate: int,
    timeout: float,
    write_timeout: float,
    inter_byte_timeout: float | None,
    exclusive: bool | None = None,
) -> _SerialPort:
    return cast(
        _SerialPort,
        serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=write_timeout,
            inter_byte_timeout=inter_byte_timeout,
            exclusive=exclusive,
        ),
    )


def _mapped_serial_error(operation: str, error: BaseException) -> TransportError:
    if isinstance(error, TransportError):
        return error
    if isinstance(error, serial.SerialTimeoutException):
        return TransportTimeoutError(f"serial {operation} timed out")
    if operation == "open":
        return TransportOpenError(f"could not open serial port: {error}")
    return TransportDisconnectedError(f"serial {operation} failed: {error}")


class SerialTransport:
    """Timeout-bounded PySerial transport suitable for the background reader.

    PySerial does not expose a portable open or flush timeout. Those two calls
    therefore run in small helper threads. A timed-out opener is marked
    cancelled and closes the port if the operating-system call later returns;
    a timed-out flush closes the transport to cancel the drain. Reads use
    PySerial's finite ``timeout`` and writes use ``write_timeout`` directly.
    """

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 115_200,
        open_timeout: float = 1.0,
        read_timeout: float = 0.05,
        write_timeout: float = 0.25,
        flush_timeout: float = 0.5,
        close_timeout: float = 0.5,
        exclusive: bool | None = None,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        if not isinstance(port, str) or not port:
            raise ValueError("serial port path must be a nonempty string")
        if not isinstance(baudrate, int) or baudrate <= 0:
            raise ValueError("baudrate must be a positive integer")
        deadlines = {
            "open_timeout": open_timeout,
            "read_timeout": read_timeout,
            "write_timeout": write_timeout,
            "flush_timeout": flush_timeout,
            "close_timeout": close_timeout,
        }
        if any(
            not isinstance(value, (int, float)) or value <= 0
            for value in deadlines.values()
        ):
            raise ValueError("serial operation timeouts must be positive")

        self.port = port
        self.read_timeout = float(read_timeout)
        self.write_timeout = float(write_timeout)
        self.flush_timeout = float(flush_timeout)
        self.close_timeout = float(close_timeout)
        self._state_lock = RLock()
        self._write_lock = Lock()
        self._closed = False

        options: dict[str, object] = {
            "port": port,
            "baudrate": baudrate,
            "timeout": self.read_timeout,
            "write_timeout": self.write_timeout,
            "inter_byte_timeout": None,
        }
        if exclusive is not None:
            options["exclusive"] = exclusive
        self._serial = self._open_bounded(
            serial_factory or _default_serial_factory,
            options,
            float(open_timeout),
        )

    @classmethod
    def open(
        cls,
        port: str,
        *,
        baudrate: int = 115_200,
        open_timeout: float = 1.0,
        read_timeout: float = 0.05,
        write_timeout: float = 0.25,
        flush_timeout: float = 0.5,
        close_timeout: float = 0.5,
        exclusive: bool | None = None,
        serial_factory: SerialFactory | None = None,
    ) -> SerialTransport:
        """Open ``port`` using the same bounded constructor semantics."""

        return cls(
            port,
            baudrate=baudrate,
            open_timeout=open_timeout,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            flush_timeout=flush_timeout,
            close_timeout=close_timeout,
            exclusive=exclusive,
            serial_factory=serial_factory,
        )

    @property
    def is_open(self) -> bool:
        with self._state_lock:
            return not self._closed and bool(self._serial.is_open)

    def read(self, size: int) -> bytes:
        """Read as many as ``size`` bytes using the finite PySerial timeout."""

        if not isinstance(size, int) or size <= 0:
            raise ValueError("read size must be a positive integer")
        serial_port = self._require_open()
        try:
            chunk = bytes(serial_port.read(size))
        except (serial.SerialException, OSError) as error:
            raise _mapped_serial_error("read", error) from error
        if len(chunk) > size:
            raise TransportError("serial read returned more bytes than requested")
        return chunk

    def write(self, data: BytesLike) -> int:
        """Perform one bounded write, preserving PySerial's partial count."""

        view = memoryview(data).cast("B")
        try:
            if not view:
                return 0
            serial_port = self._require_open()
            try:
                with self._write_lock:
                    result = serial_port.write(view)
            except (
                serial.SerialTimeoutException,
                serial.SerialException,
                OSError,
            ) as error:
                raise _mapped_serial_error("write", error) from error
            written = 0 if result is None else result
            if not isinstance(written, int) or not 0 <= written <= len(view):
                raise TransportError("serial write returned an invalid byte count")
            return written
        finally:
            view.release()

    def flush(self) -> None:
        """Drain accepted output or close the port at ``flush_timeout``."""

        serial_port = self._require_open()
        try:
            self._run_void_bounded(
                "flush",
                serial_port.flush,
                self.flush_timeout,
            )
        except TransportTimeoutError:
            try:
                self.close()
            except TransportError:
                pass
            raise

    def close(self) -> None:
        """Cancel reads/writes and close the PySerial handle idempotently."""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            serial_port = self._serial

        # PySerial exposes cancellation only on platforms that support it.
        for method_name in ("cancel_read", "cancel_write"):
            cancellation = getattr(serial_port, method_name, None)
            if cancellation is not None:
                try:
                    cancellation()
                except (serial.SerialException, OSError):
                    pass
        self._run_void_bounded("close", serial_port.close, self.close_timeout)

    def __enter__(self) -> SerialTransport:  # noqa: PYI034
        self._require_open()
        return self

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
            except TransportError:
                pass
        return False

    def _require_open(self) -> _SerialPort:
        with self._state_lock:
            if self._closed or not self._serial.is_open:
                raise TransportClosedError(f"serial port {self.port!r} is closed")
            return self._serial

    def _open_bounded(
        self,
        factory: SerialFactory,
        options: dict[str, object],
        timeout: float,
    ) -> _SerialPort:
        attempt = _OpenAttempt()

        def open_port() -> None:
            opened: _SerialPort | None = None
            try:
                opened = factory(**options)
            except Exception as error:  # noqa: BLE001 - propagated to caller
                with attempt.lock:
                    attempt.error = error
                    attempt.done.set()
                return

            with attempt.lock:
                if attempt.cancelled:
                    close_late_port = True
                else:
                    attempt.serial_port = opened
                    close_late_port = False
                attempt.done.set()
            if close_late_port:
                try:
                    opened.close()
                except Exception:  # noqa: BLE001, S110 - best-effort late cleanup
                    pass

        opener = Thread(
            target=open_port,
            name="teensy-daq-serial-open",
            daemon=True,
        )
        opener.start()
        if not attempt.done.wait(timeout):
            with attempt.lock:
                attempt.cancelled = True
                opened = attempt.serial_port
                attempt.serial_port = None
            if opened is not None:
                try:
                    opened.close()
                except Exception:  # noqa: BLE001, S110 - best-effort late cleanup
                    pass
            raise TransportTimeoutError(
                f"opening serial port {self.port!r} exceeded {timeout:g} seconds"
            )

        if attempt.error is not None:
            error = attempt.error
            raise _mapped_serial_error("open", error) from error
        if attempt.serial_port is None:
            raise TransportOpenError("serial factory returned no port")
        if not attempt.serial_port.is_open:
            try:
                attempt.serial_port.close()
            except Exception:  # noqa: BLE001, S110 - best-effort rejected handle cleanup
                pass
            raise TransportOpenError("serial factory returned a closed port")
        return attempt.serial_port

    @staticmethod
    def _run_void_bounded(
        operation: str,
        function: Callable[[], None],
        timeout: float,
    ) -> None:
        attempt = _VoidAttempt()

        def invoke() -> None:
            try:
                function()
            except Exception as error:  # noqa: BLE001 - propagated to caller
                attempt.error = error
            finally:
                attempt.done.set()

        worker = Thread(
            target=invoke,
            name=f"teensy-daq-serial-{operation}",
            daemon=True,
        )
        worker.start()
        if not attempt.done.wait(timeout):
            raise TransportTimeoutError(
                f"serial {operation} exceeded {timeout:g} seconds"
            )
        if attempt.error is not None:
            error = attempt.error
            raise _mapped_serial_error(operation, error) from error


class InMemoryTransport:
    """Connect a host reader to :class:`SimulatedDevice` through wire bytes.

    Optional read/write chunk limits deliberately model arbitrary serial stream
    boundaries. The pending device-to-host queue is bounded and a data frame
    already being read is always completed before a later command response.
    Operations are serialized so a background reader and concurrent request
    writers can safely share the transport.
    """

    def __init__(
        self,
        device: SimulatedDevice | None = None,
        *,
        read_chunk_size: int | None = None,
        write_chunk_size: int | None = None,
        max_pending_bytes: int = 64 * 1024,
        stream_interval: float | None = None,
        demand_driven: bool = True,
    ) -> None:
        if read_chunk_size is not None and read_chunk_size <= 0:
            raise ValueError("read_chunk_size must be positive")
        if write_chunk_size is not None and write_chunk_size <= 0:
            raise ValueError("write_chunk_size must be positive")
        minimum_pending = constants.DATA_FRAME_BYTES + constants.MAX_CONTROL_FRAME_BYTES
        if max_pending_bytes < minimum_pending:
            raise ValueError(f"max_pending_bytes must be at least {minimum_pending}")
        if stream_interval is not None and (
            not isinstance(stream_interval, (int, float))
            or isinstance(stream_interval, bool)
            or stream_interval <= 0
        ):
            raise ValueError("stream_interval must be positive or None")
        if not isinstance(demand_driven, bool):
            raise TypeError("demand_driven must be a boolean")

        self.device = device if device is not None else SimulatedDevice()
        self._read_chunk_size = read_chunk_size
        self._write_chunk_size = write_chunk_size
        self._max_pending_bytes = max_pending_bytes
        self._stream_interval = (
            None if stream_interval is None else float(stream_interval)
        )
        self._demand_driven = demand_driven
        self._stream_credits = 0
        self._next_stream_at = monotonic()
        self._pending = bytearray()
        self._is_open = True
        self._lock = RLock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open

    @property
    def pending_bytes(self) -> int:
        """Bytes queued for the host but not yet read."""

        with self._lock:
            return len(self._pending)

    def write(self, data: BytesLike) -> int:
        """Accept a bounded partial write and feed it to the simulated device."""

        view = memoryview(data).cast("B")
        try:
            with self._lock:
                self._require_open()
                if not view:
                    return 0
                accepted = min(len(view), self.device.max_receive_bytes)
                if self._write_chunk_size is not None:
                    accepted = min(accepted, self._write_chunk_size)
                previous_state = self.device.state
                responses = self.device.receive(view[:accepted])
                if self.device.state is not previous_state:
                    self._stream_credits = 0
                    self._next_stream_at = monotonic()
                response_bytes = sum(len(response) for response in responses)
                if len(self._pending) + response_bytes > self._max_pending_bytes:
                    self.device.record_transport_error()
                    raise TransportBufferError("in-memory receive queue is full")
                for response in responses:
                    self._pending.extend(response)
                return accepted
        finally:
            view.release()

    def read(self, size: int) -> bytes:
        """Return a bounded chunk, producing at most one new data frame."""

        with self._lock:
            self._require_open()
            if size <= 0:
                raise ValueError("read size must be positive")
            if not self._pending:
                if self._demand_driven and self._stream_credits == 0:
                    return b""
                now = monotonic()
                if self._stream_interval is not None and now < self._next_stream_at:
                    return b""
                data_frame = self.device.next_data_frame()
                if data_frame is not None:
                    self._pending.extend(data_frame)
                    if self._demand_driven:
                        self._stream_credits -= 1
                    if self._stream_interval is not None:
                        self._next_stream_at = now + self._stream_interval
            if not self._pending:
                return b""

            returned = min(size, len(self._pending))
            if self._read_chunk_size is not None:
                returned = min(returned, self._read_chunk_size)
            chunk = bytes(self._pending[:returned])
            del self._pending[:returned]
            return chunk

    def request_stream_frame(self) -> None:
        """Grant one simulator frame credit to a waiting public consumer.

        Real serial devices stream independently. The deterministic simulator
        instead produces one frame per host block request so background
        prefetch cannot make offline assertions depend on thread scheduling.
        Command and response bytes still traverse the exact same reader path.
        """

        with self._lock:
            self._require_open()
            if self._demand_driven:
                self._stream_credits += 1

    def flush(self) -> None:
        """Complete immediately because writes synchronously reach the simulator."""

        with self._lock:
            self._require_open()

    def close(self) -> None:
        """Close the stream and discard unread simulated wire bytes."""

        with self._lock:
            if self._is_open:
                self._is_open = False
                self._pending.clear()
                self._stream_credits = 0

    def _require_open(self) -> None:
        if not self._is_open:
            raise TransportClosedError("transport is closed")


MemoryTransport = InMemoryTransport


__all__ = [
    "ByteTransport",
    "InMemoryTransport",
    "MemoryTransport",
    "SerialTransport",
    "Transport",
    "TransportBufferError",
    "TransportClosedError",
    "TransportDisconnectedError",
    "TransportError",
    "TransportOpenError",
    "TransportTimeoutError",
]
