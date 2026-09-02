"""Shared bounded byte-stream framing and resynchronization mechanics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

BytesLike = bytes | bytearray | memoryview


class HeaderWithLength(Protocol):
    """The one header property needed by the framing loop."""

    @property
    def total_length(self) -> int:
        """Return the complete transmitted frame length."""

        ...


HeaderT = TypeVar("HeaderT", bound=HeaderWithLength)
FrameT = TypeVar("FrameT")


@dataclass(frozen=True, slots=True)
class ParserCounters:
    """Immutable snapshot of incremental-parser health and bounded state.

    ``corruption_events`` is the sum of rejected header, checksum, and typed
    payload candidates. ``resynchronizations`` counts distinct loss-of-alignment
    episodes, including leading noise; one episode can reject several false
    magic candidates before the parser accepts another frame.
    """

    bytes_received: int
    frames_decoded: int
    corruption_events: int
    header_errors: int
    checksum_errors: int
    payload_errors: int
    resynchronizations: int
    bytes_discarded: int
    buffered_bytes: int
    high_water_mark: int


def _partial_magic_suffix_length(
    data: bytearray,
    magic_bytes: bytes,
    start: int = 0,
) -> int:
    maximum = min(len(data) - start, len(magic_bytes) - 1)
    for length in range(maximum, 0, -1):
        if data.endswith(magic_bytes[:length], start):
            return length
    return 0


def _byte_view(chunk: BytesLike) -> memoryview:
    """Return a one-dimensional byte view, copying only non-contiguous inputs."""

    try:
        return memoryview(chunk).cast("B")
    except TypeError:
        return memoryview(bytes(chunk))


class BoundedIncrementalParser(Generic[HeaderT, FrameT]):
    """Version-neutral bounded scanner for magic-prefixed wire frames."""

    def __init__(
        self,
        *,
        magic_bytes: bytes,
        header_size: int,
        max_frame_bytes: int,
        decode_header: Callable[[bytearray, int], HeaderT],
        decode_frame: Callable[[bytearray, int, HeaderT], FrameT],
        validation_error: type[Exception],
        checksum_error: type[Exception],
    ) -> None:
        if not magic_bytes or header_size < len(magic_bytes):
            raise ValueError("framing magic/header bounds are invalid")
        if max_frame_bytes < header_size:
            raise ValueError("maximum frame size is smaller than its header")
        self._magic_bytes = magic_bytes
        self._header_size = header_size
        self._decode_header = decode_header
        self._decode_frame = decode_frame
        self._validation_error = validation_error
        self._checksum_error = checksum_error
        self.max_buffered_bytes = max_frame_bytes + len(magic_bytes) - 1
        self._buffer = bytearray()
        self._scan_start = 0
        self._resynchronizing = False
        self.bytes_received = 0
        self.frames_decoded = 0
        self.corruption_events = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.resynchronizations = 0
        self.bytes_discarded = 0
        self.high_water_mark = 0

    @property
    def buffered_bytes(self) -> int:
        """Number of bytes retained while awaiting a plausible complete frame."""

        return len(self._buffer) - self._scan_start

    @property
    def errors(self) -> int:
        """Backward-compatible total of all rejected frame candidates."""

        return self.corruption_events

    @property
    def counters(self) -> ParserCounters:
        """Return an immutable snapshot suitable for monitoring or logging."""

        return ParserCounters(
            bytes_received=self.bytes_received,
            frames_decoded=self.frames_decoded,
            corruption_events=self.corruption_events,
            header_errors=self.header_errors,
            checksum_errors=self.checksum_errors,
            payload_errors=self.payload_errors,
            resynchronizations=self.resynchronizations,
            bytes_discarded=self.bytes_discarded,
            buffered_bytes=self.buffered_bytes,
            high_water_mark=self.high_water_mark,
        )

    @property
    def is_resynchronizing(self) -> bool:
        """Whether bytes have been discarded since the last accepted frame."""

        return self._resynchronizing

    def reset(self) -> None:
        """Discard pending bytes and reset parser counters."""

        self.reset_session()
        self.bytes_received = 0
        self.frames_decoded = 0
        self.corruption_events = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.resynchronizations = 0
        self.bytes_discarded = 0
        self.high_water_mark = 0

    def reset_session(self) -> None:
        """Discard only partial wire state while retaining lifetime counters."""

        self._buffer.clear()
        self._scan_start = 0
        self._resynchronizing = False

    def feed(self, chunk: BytesLike) -> list[FrameT]:
        """Consume a chunk and return every complete valid frame it contains."""

        incoming = _byte_view(chunk)
        try:
            self.bytes_received += len(incoming)
            frames: list[FrameT] = []
            position = 0
            while position < len(incoming):
                frames.extend(self._drain())
                capacity = self.max_buffered_bytes - self.buffered_bytes
                if capacity <= 0:
                    raise RuntimeError(
                        "incremental parser could not make bounded progress"
                    )
                take = min(capacity, len(incoming) - position)
                self._buffer.extend(incoming[position : position + take])
                position += take
                self.high_water_mark = max(
                    self.high_water_mark,
                    self.buffered_bytes,
                )
            frames.extend(self._drain())
            return frames
        finally:
            incoming.release()

    def _drain(self) -> list[FrameT]:
        frames: list[FrameT] = []
        while True:
            magic_at = self._buffer.find(self._magic_bytes, self._scan_start)
            if magic_at < 0:
                retained = _partial_magic_suffix_length(
                    self._buffer,
                    self._magic_bytes,
                    self._scan_start,
                )
                self._discard(self.buffered_bytes - retained)
                break
            if magic_at > self._scan_start:
                self._discard(magic_at - self._scan_start)
            if self.buffered_bytes < self._header_size:
                break
            try:
                header = self._decode_header(self._buffer, self._scan_start)
            except self._validation_error:
                self._record_corruption("header")
                self._discard(1)
                continue
            if self.buffered_bytes < header.total_length:
                break
            try:
                frame = self._decode_frame(self._buffer, self._scan_start, header)
            except self._checksum_error:
                self._record_corruption("checksum")
                self._discard(1)
                continue
            except self._validation_error:
                self._record_corruption("payload")
                self._discard(1)
                continue
            self._scan_start += header.total_length
            self.frames_decoded += 1
            self._resynchronizing = False
            frames.append(frame)
        self._compact()
        return frames

    def _discard(self, count: int) -> None:
        if count <= 0:
            return
        if not self._resynchronizing:
            self._resynchronizing = True
            self.resynchronizations += 1
        self._scan_start += count
        self.bytes_discarded += count

    def _record_corruption(self, category: str) -> None:
        self.corruption_events += 1
        if category == "header":
            self.header_errors += 1
        elif category == "checksum":
            self.checksum_errors += 1
        else:
            self.payload_errors += 1

    def _compact(self) -> None:
        if self._scan_start:
            del self._buffer[: self._scan_start]
            self._scan_start = 0


__all__ = ["BoundedIncrementalParser", "BytesLike", "ParserCounters"]
