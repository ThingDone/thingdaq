"""Transport boundary and deterministic in-memory byte-stream implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._generated import protocol_constants as constants
from .simulator import SimulatedDevice

BytesLike = bytes | bytearray | memoryview


class TransportError(RuntimeError):
    """Base error for byte-transport failures."""


class TransportClosedError(TransportError):
    """An operation was attempted after the transport closed."""


class TransportBufferError(TransportError):
    """The bounded in-memory receive queue cannot accept another response."""


@runtime_checkable
class ByteTransport(Protocol):
    """Minimal synchronous byte stream required by :class:`TeensyDAQ`.

    A future serial implementation can satisfy this interface without changing
    command, parser, state-machine, or user-facing API code.
    """

    @property
    def is_open(self) -> bool:
        """Whether reads and writes are currently permitted."""

        ...

    def write(self, data: BytesLike) -> int:
        """Write up to ``len(data)`` bytes and return the accepted count."""

        ...

    def read(self, size: int) -> bytes:
        """Return at most ``size`` bytes, or ``b\"\"`` if none are available."""

        ...

    def close(self) -> None:
        """Release transport resources, idempotently."""

        ...


Transport = ByteTransport


class InMemoryTransport:
    """Connect a host facade to :class:`SimulatedDevice` through wire bytes.

    Optional read/write chunk limits deliberately model arbitrary serial stream
    boundaries.  The pending device-to-host queue is bounded and a data frame
    already being read is always completed before a later command response.
    """

    def __init__(
        self,
        device: SimulatedDevice | None = None,
        *,
        read_chunk_size: int | None = None,
        write_chunk_size: int | None = None,
        max_pending_bytes: int = 64 * 1024,
    ) -> None:
        if read_chunk_size is not None and read_chunk_size <= 0:
            raise ValueError("read_chunk_size must be positive")
        if write_chunk_size is not None and write_chunk_size <= 0:
            raise ValueError("write_chunk_size must be positive")
        minimum_pending = constants.DATA_FRAME_BYTES + constants.MAX_CONTROL_FRAME_BYTES
        if max_pending_bytes < minimum_pending:
            raise ValueError(f"max_pending_bytes must be at least {minimum_pending}")

        self.device = device if device is not None else SimulatedDevice()
        self._read_chunk_size = read_chunk_size
        self._write_chunk_size = write_chunk_size
        self._max_pending_bytes = max_pending_bytes
        self._pending = bytearray()
        self._is_open = True

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def pending_bytes(self) -> int:
        """Bytes queued for the host but not yet read."""

        return len(self._pending)

    def write(self, data: BytesLike) -> int:
        """Accept a bounded partial write and feed it to the simulated device."""

        self._require_open()
        view = memoryview(data).cast("B")
        if not view:
            return 0
        accepted = min(len(view), self.device.max_receive_bytes)
        if self._write_chunk_size is not None:
            accepted = min(accepted, self._write_chunk_size)
        responses = self.device.receive(view[:accepted])
        response_bytes = sum(len(response) for response in responses)
        if len(self._pending) + response_bytes > self._max_pending_bytes:
            self.device.record_transport_error()
            raise TransportBufferError("in-memory receive queue is full")
        for response in responses:
            self._pending.extend(response)
        return accepted

    def read(self, size: int) -> bytes:
        """Return a bounded chunk, producing at most one new data frame."""

        self._require_open()
        if size <= 0:
            raise ValueError("read size must be positive")
        if not self._pending:
            data_frame = self.device.next_data_frame()
            if data_frame is not None:
                self._pending.extend(data_frame)
        if not self._pending:
            return b""

        returned = min(size, len(self._pending))
        if self._read_chunk_size is not None:
            returned = min(returned, self._read_chunk_size)
        chunk = bytes(self._pending[:returned])
        del self._pending[:returned]
        return chunk

    def close(self) -> None:
        """Close the stream and discard unread simulated wire bytes."""

        if self._is_open:
            self._is_open = False
            self._pending.clear()

    def _require_open(self) -> None:
        if not self._is_open:
            raise TransportClosedError("transport is closed")


MemoryTransport = InMemoryTransport


__all__ = [
    "ByteTransport",
    "InMemoryTransport",
    "MemoryTransport",
    "Transport",
    "TransportBufferError",
    "TransportClosedError",
    "TransportError",
]
