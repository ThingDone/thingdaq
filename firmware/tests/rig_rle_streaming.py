#!/usr/bin/env python3
"""Standalone protocol-v1/v2 RLE streaming smoke and endurance rig.

The remote service uploads this file by itself to a network-disabled Python
container.  It deliberately imports no ThingDAQ package or generated file: the
wire constants, control encoders, checksums, bounded parser, canonical RLE
decoder, target formulas, accounting rules, and result schema are independent.
Only the Python standard library and PySerial are required.

No decoded capture is retained.  Every accepted frame is checksummed before
RLE inspection, compared with its logical timestamp/formula, reduced into
bounded counters, and released.  Cleanup always attempts STOP and a final IDLE
STATUS, including after codec, firmware, fixture, or serial-service failures.
"""

from __future__ import annotations

import gc
import json
import math
import os
import resource
import statistics
import struct
import sys
import threading
import time
import zlib
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

import serial

BAUD_RATE = 115_200
SERIAL_READ_TIMEOUT_SECONDS = 0.02
SERIAL_WRITE_TIMEOUT_SECONDS = 0.5
SERIAL_READ_BYTES = 16 * 1024
SERIAL_READER_QUEUE_CHUNKS = 32
SERIAL_READER_QUEUE_BYTES = SERIAL_READ_BYTES * SERIAL_READER_QUEUE_CHUNKS
SERIAL_READER_SWITCH_INTERVAL_SECONDS = 0.001
STARTUP_DRAIN_SECONDS = 0.25
COMMAND_DEADLINE_SECONDS = 0.75
STOP_DRAIN_DEADLINE_SECONDS = 2.0
STOP_DRAIN_QUIET_SECONDS = 0.10

MODE_SMOKE = "smoke"
MODE_ENDURANCE = "endurance"
SUPPORTED_MODES = frozenset({MODE_SMOKE, MODE_ENDURANCE})
DEFAULT_SMOKE_CAPTURE_SECONDS = 10.0
DEFAULT_ENDURANCE_CAPTURE_SECONDS = 600.0
MIN_ENDURANCE_CAPTURE_SECONDS = 600.0
MAX_SMOKE_CAPTURE_SECONDS = 60.0
MAX_CAPTURE_SECONDS = 3600.0
DEFAULT_SMOKE_WARMUP_SECONDS = 1.0
DEFAULT_ENDURANCE_WARMUP_SECONDS = 10.0
MAX_WARMUP_SECONDS = 30.0
DEFAULT_STATUS_INTERVAL_SECONDS = 0.5
MIN_STATUS_INTERVAL_SECONDS = 0.05
MAX_STATUS_INTERVAL_SECONDS = 5.0
MAX_STATUS_SAMPLES = 16_384
RLE_RESULT_PREFIX = "RLE_RESULT "
RLE_EVENT_PREFIX = "RLE_EVENT "
RLE_RESULT_SCHEMA_VERSION = 1

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_V1 = 1
PROTOCOL_V2 = 2
HEADER_SIZE = 44
TRAILER_SIZE = 4
DATA_FRAME_BYTES = 4096
DATA_PAYLOAD_BYTES = 4048
MAX_V1_CONTROL_FRAME_BYTES = 1280
MAX_V2_CONTROL_FRAME_BYTES = 1536
MAX_FRAME_BYTES = DATA_FRAME_BYTES
MIN_V2_RLE_FRAME_BYTES = 51

CHECKSUM_ADLER32 = 1
CHECKSUM_CRC32C = 2
CHECKSUM_CRC32_ISO_HDLC = 3
BOOTSTRAP_CHECKSUM = CHECKSUM_ADLER32
SUPPORTED_CHECKSUMS = frozenset(
    {CHECKSUM_ADLER32, CHECKSUM_CRC32C, CHECKSUM_CRC32_ISO_HDLC}
)
CHECKSUM_NAMES = {
    CHECKSUM_ADLER32: "ADLER32",
    CHECKSUM_CRC32C: "CRC32C",
    CHECKSUM_CRC32_ISO_HDLC: "CRC32_ISO_HDLC",
}

FRAME_ENCODING_RAW = 0
FRAME_ENCODING_RLE = 1
CONFIGURATION_ENCODING_RAW = 0
CONFIGURATION_ENCODING_RLE_AUTO = 1
CONFIGURATION_ENCODING_NAMES = {
    CONFIGURATION_ENCODING_RAW: "RAW",
    CONFIGURATION_ENCODING_RLE_AUTO: "RLE_AUTO",
}

TIMESTAMP_HZ = 8_000_000
ADC_PAIR_RATE_HZ = 1_000_000
ADC_PAIR_PERIOD_TICKS = 8
ADC_BYTES_PER_PAIR = 4
ADC_PAIRS_PER_FRAME = 1012
ADC_CODE_MASK = 0x0FFF
# Each little-endian ADC code is valid exactly when its high byte is one of
# these 16 values.  bytes.translate() applies the deletion set in C, avoiding
# a Python-level loop over 2,024 high bytes for every full-rate ADC frame.
VALID_ADC_HIGH_BYTES = bytes(range((ADC_CODE_MASK >> 8) + 1))
ADC_DMA_RING_DEPTH = 8
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4048
GPIO_RAW_RING_DEPTH = 4
GPIO_PACKED_RING_DEPTH = 4
FRAME_COVERAGE_TICKS = 8096
CPU_DWT_HZ = 600_000_000
PACKET_BUFFER_COUNT = 200

ADC_DATA = 0x01
GPIO_DATA = 0x02
INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
ERROR_RESPONSE = 0x9F

FLAG_SYNTHETIC = 0x0001
FLAG_GAP_BEFORE = 0x0002
FLAG_EPOCH_START = 0x0004
FLAG_OVERRUN_BEFORE = 0x0008
FLAG_RESPONSE_ERROR = 0x8000
DATA_FLAG_MASK = (
    FLAG_SYNTHETIC | FLAG_GAP_BEFORE | FLAG_EPOCH_START | FLAG_OVERRUN_BEFORE
)

STATE_IDLE = 1
STATE_CONFIGURED = 2
STATE_RUNNING = 3
STREAM_NONE = 0
STREAM_ADC = 1
STREAM_GPIO = 2
STREAM_BOTH = STREAM_ADC | STREAM_GPIO

SOURCE_HARDWARE = 0
SOURCE_SYNTHETIC = 1
SOURCE_SYNTHETIC_CONSTANT = 2
SOURCE_SYNTHETIC_SPARSE_HOLD = 3
SOURCE_SYNTHETIC_SLOW_ADC = 4
SOURCE_SYNTHETIC_ALTERNATING = 5
SOURCE_SYNTHETIC_INCOMPRESSIBLE = 6
PATTERN_SOURCE = {
    "physical": SOURCE_HARDWARE,
    "constant": SOURCE_SYNTHETIC_CONSTANT,
    "sparse-hold": SOURCE_SYNTHETIC_SPARSE_HOLD,
    "slow-adc": SOURCE_SYNTHETIC_SLOW_ADC,
    "alternating": SOURCE_SYNTHETIC_ALTERNATING,
    "incompressible": SOURCE_SYNTHETIC_INCOMPRESSIBLE,
}
SYNTHETIC_PATTERNS = frozenset(PATTERN_SOURCE) - {"physical"}
SOURCE_PATTERN = {value: key for key, value in PATTERN_SOURCE.items()}

CAPABILITY_RLE_STREAMING = 0x00000200
CAPABILITY_SYNTHETIC_PATTERNS = 0x00000400
KNOWN_V1_CAPABILITY_MASK = 0x000001FF
KNOWN_V2_CAPABILITY_MASK = 0x000007FF
V1_SOURCE_MASK = 0x03
V2_SOURCE_MASK = 0x7F

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
TRAILER = struct.Struct("<I")
CONFIGURATION = struct.Struct("<BBBBI")
RESPONSE_PREFIX = struct.Struct("<BBH")

REQUEST_RESPONSE_KIND = {
    INFO_REQUEST: INFO_RESPONSE,
    CONFIGURE_REQUEST: CONFIGURE_RESPONSE,
    START_REQUEST: START_RESPONSE,
    GET_STATUS_REQUEST: GET_STATUS_RESPONSE,
    STOP_REQUEST: STOP_RESPONSE,
    RESET_STATS_REQUEST: RESET_STATS_RESPONSE,
}
REQUEST_PAYLOAD_SIZE = {
    INFO_REQUEST: 0,
    CONFIGURE_REQUEST: 8,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
}
SUCCESS_PAYLOAD_SIZE = {
    PROTOCOL_V1: {
        INFO_RESPONSE: 376,
        CONFIGURE_RESPONSE: 12,
        START_RESPONSE: 12,
        GET_STATUS_RESPONSE: 1228,
        STOP_RESPONSE: 8,
        RESET_STATS_RESPONSE: 8,
        ERROR_RESPONSE: 8,
    },
    PROTOCOL_V2: {
        INFO_RESPONSE: 376,
        CONFIGURE_RESPONSE: 12,
        START_RESPONSE: 12,
        GET_STATUS_RESPONSE: 1484,
        STOP_RESPONSE: 8,
        RESET_STATS_RESPONSE: 8,
        ERROR_RESPONSE: 8,
    },
}
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE[PROTOCOL_V2])


class RigFailure(RuntimeError):
    """Base class for a graded rig outcome."""


class ServiceFailure(RigFailure):
    """The serial runner or remote service could not complete bounded I/O."""


class FixtureFailure(RigFailure):
    """The connected firmware artifact does not match the declared fixture."""


class CodecFailure(RigFailure):
    """A checksummed envelope or encoded payload violates protocol v1/v2."""


class FirmwareFailure(RigFailure):
    """Logical samples, timestamps, telemetry, or conservation are wrong."""


def _make_reflected_crc_table(polynomial: int) -> tuple[tuple[int, ...], ...]:
    first_slice: list[int] = []
    for index in range(256):
        remainder = index
        for _ in range(8):
            remainder = (remainder >> 1) ^ (polynomial if remainder & 1 else 0)
        first_slice.append(remainder)
    slices = [tuple(first_slice)]
    for _ in range(3):
        previous = slices[-1]
        slices.append(
            tuple((value >> 8) ^ slices[0][value & 0xFF] for value in previous)
        )
    return tuple(slices)


CRC32C_TABLE = _make_reflected_crc_table(0x82F63B78)
CRC32_ISO_HDLC_TABLE = _make_reflected_crc_table(0xEDB88320)


def _pure_adler32(data: bytes | bytearray | memoryview) -> int:
    view = memoryview(data).cast("B")
    try:
        sum_1 = 1
        sum_2 = 0
        offset = 0
        while offset < len(view):
            end = min(offset + 5_552, len(view))
            for value in view[offset:end]:
                sum_1 += value
                sum_2 += sum_1
            sum_1 %= 65_521
            sum_2 %= 65_521
            offset = end
        return (sum_2 << 16) | sum_1
    finally:
        view.release()


def _pure_reflected_crc32(
    data: bytes | bytearray | memoryview,
    table: tuple[tuple[int, ...], ...],
) -> int:
    view = memoryview(data).cast("B")
    try:
        remainder = 0xFFFFFFFF
        word_bytes = len(view) & ~3
        slice_0, slice_1, slice_2, slice_3 = table
        if sys.byteorder == "little":
            words = view[:word_bytes].cast("I")
            try:
                for word in words:
                    remainder ^= word
                    remainder = (
                        slice_3[remainder & 0xFF]
                        ^ slice_2[(remainder >> 8) & 0xFF]
                        ^ slice_1[(remainder >> 16) & 0xFF]
                        ^ slice_0[remainder >> 24]
                    )
            finally:
                words.release()
        else:
            for offset in range(0, word_bytes, 4):
                remainder ^= int.from_bytes(view[offset : offset + 4], "little")
                remainder = (
                    slice_3[remainder & 0xFF]
                    ^ slice_2[(remainder >> 8) & 0xFF]
                    ^ slice_1[(remainder >> 16) & 0xFF]
                    ^ slice_0[remainder >> 24]
                )
        for value in view[word_bytes:]:
            remainder = (remainder >> 8) ^ slice_0[(remainder ^ value) & 0xFF]
        return remainder ^ 0xFFFFFFFF
    finally:
        view.release()


def compute_checksum(
    data: bytes | bytearray | memoryview,
    algorithm: int,
) -> int:
    """Compute the exact wire checksum without substituting polynomials."""

    if algorithm == CHECKSUM_ADLER32:
        return zlib.adler32(data, 1) & 0xFFFFFFFF
    if algorithm == CHECKSUM_CRC32C:
        return _pure_reflected_crc32(data, CRC32C_TABLE)
    if algorithm == CHECKSUM_CRC32_ISO_HDLC:
        return zlib.crc32(data, 0) & 0xFFFFFFFF
    raise CodecFailure(f"unsupported checksum algorithm {algorithm}")


def encode_control(
    version: int,
    kind: int,
    request_id: int,
    payload: bytes = b"",
) -> bytes:
    """Independently encode a bounded protocol-v1 or protocol-v2 command."""

    if version not in {PROTOCOL_V1, PROTOCOL_V2}:
        raise ValueError("control version must be exactly 1 or 2")
    if kind not in REQUEST_PAYLOAD_SIZE:
        raise ValueError(f"unknown request kind 0x{kind:02x}")
    if len(payload) != REQUEST_PAYLOAD_SIZE[kind]:
        raise ValueError(
            f"request 0x{kind:02x} needs {REQUEST_PAYLOAD_SIZE[kind]} bytes"
        )
    if not 1 <= request_id <= 0xFFFFFFFF:
        raise ValueError("request ID must be a nonzero uint32")
    if kind == CONFIGURE_REQUEST:
        _streams, source, _checksum, encoding, frame_bytes = CONFIGURATION.unpack(
            payload
        )
        if frame_bytes != DATA_FRAME_BYTES:
            raise ValueError("CONFIGURE data frame size must be 4096")
        if version == PROTOCOL_V1 and (source > SOURCE_SYNTHETIC or encoding != 0):
            raise ValueError("protocol v1 cannot select v2 source/encoding values")
        if version == PROTOCOL_V2 and (
            source not in range(SOURCE_HARDWARE, SOURCE_SYNTHETIC_INCOMPRESSIBLE + 1)
            or encoding
            not in {
                CONFIGURATION_ENCODING_RAW,
                CONFIGURATION_ENCODING_RLE_AUTO,
            }
        ):
            raise ValueError("protocol v2 CONFIGURE contains an unknown selector")
    total_length = HEADER_SIZE + len(payload) + TRAILER_SIZE
    header = HEADER.pack(
        MAGIC,
        version,
        kind,
        0,
        HEADER_SIZE,
        BOOTSTRAP_CHECKSUM,
        FRAME_ENCODING_RAW,
        total_length,
        len(payload),
        0,
        0,
        request_id,
        0,
        0,
    )
    body = header + payload
    return body + TRAILER.pack(compute_checksum(body, BOOTSTRAP_CHECKSUM))


class SerialPort(Protocol):
    """The narrow PySerial surface used by this self-contained runner."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


class BufferedSerialPort:
    """Drain the OS TTY continuously into one fixed-capacity chunk queue."""

    def __init__(self, port: SerialPort) -> None:
        self._port = port
        self._chunks: deque[bytes] = deque()
        self._queued_bytes = 0
        self._high_water_bytes = 0
        self._high_water_chunks = 0
        self._maximum_read_call_seconds = 0.0
        self._maximum_successful_read_gap_seconds = 0.0
        self._last_successful_read_at: float | None = None
        self._read_calls = 0
        self._error: Exception | None = None
        self._stopped = False
        self._condition = threading.Condition()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="rle-rig-serial-reader",
            daemon=True,
        )
        self._thread.start()

    def read(self, size: int = 1) -> bytes:
        if size <= 0:
            return b""
        deadline = time.monotonic() + SERIAL_READ_TIMEOUT_SECONDS
        with self._condition:
            while not self._chunks:
                if self._error is not None:
                    raise self._error
                if self._stopped:
                    return b""
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._condition.wait(remaining)
            chunk = self._chunks.popleft()
            if len(chunk) > size:
                result = chunk[:size]
                self._chunks.appendleft(chunk[size:])
            else:
                result = chunk
            self._queued_bytes -= len(result)
            self._condition.notify_all()
            return result

    def write(self, data: bytes) -> int | None:
        return self._port.write(data)

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        self._thread.join(timeout=1.0)
        if self._thread.is_alive():
            raise RuntimeError("bounded serial reader did not stop")

    def metrics(self) -> dict[str, int | float | bool]:
        with self._condition:
            return {
                "enabled": True,
                "capacity_bytes": SERIAL_READER_QUEUE_BYTES,
                "capacity_chunks": SERIAL_READER_QUEUE_CHUNKS,
                "final_bytes": self._queued_bytes,
                "final_chunks": len(self._chunks),
                "high_water_bytes": self._high_water_bytes,
                "high_water_chunks": self._high_water_chunks,
                "maximum_read_call_seconds": self._maximum_read_call_seconds,
                "maximum_successful_read_gap_seconds": (
                    self._maximum_successful_read_gap_seconds
                ),
                "read_calls": self._read_calls,
            }

    def _reader_loop(self) -> None:
        while True:
            with self._condition:
                while (
                    len(self._chunks) >= SERIAL_READER_QUEUE_CHUNKS
                    and not self._stopped
                ):
                    self._condition.wait()
                if self._stopped:
                    return
            try:
                read_started = time.monotonic()
                chunk = bytes(self._port.read(SERIAL_READ_BYTES))
                read_finished = time.monotonic()
                if len(chunk) > SERIAL_READ_BYTES:
                    raise ServiceFailure(
                        "serial reader exceeded its fixed per-call byte bound"
                    )
            except Exception as error:  # noqa: BLE001 - relay reader failures
                with self._condition:
                    self._error = error
                    self._condition.notify_all()
                return
            with self._condition:
                self._read_calls += 1
                self._maximum_read_call_seconds = max(
                    self._maximum_read_call_seconds,
                    read_finished - read_started,
                )
                if not chunk or self._stopped:
                    if self._stopped:
                        return
                    continue
                if self._last_successful_read_at is not None:
                    self._maximum_successful_read_gap_seconds = max(
                        self._maximum_successful_read_gap_seconds,
                        read_finished - self._last_successful_read_at,
                    )
                self._last_successful_read_at = read_finished
                self._chunks.append(chunk)
                self._queued_bytes += len(chunk)
                self._high_water_bytes = max(
                    self._high_water_bytes,
                    self._queued_bytes,
                )
                self._high_water_chunks = max(
                    self._high_water_chunks,
                    len(self._chunks),
                )
                self._condition.notify_all()


@dataclass(frozen=True)
class Frame:
    """One checksum- and structure-validated transmitted frame."""

    version: int
    kind: int
    flags: int
    checksum_algorithm: int
    encoding: int
    total_length: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    payload: bytes
    checksum: int
    run_count: int = 0
    rle_formula_pattern: str | None = None
    rle_validation_nanoseconds: int = 0


class FrameParser:
    """Bounded parser that validates checksum before any RLE record."""

    def __init__(self, *, strict: bool = False) -> None:
        self.buffer = bytearray()
        self.strict = strict
        self.bytes_received = 0
        self.frames_decoded = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.bytes_discarded = 0
        self.high_water_bytes = 0
        self.rle_validator: Callable[[Frame], tuple[int, str]] | None = None
        self.last_frame_context = "none"

    @property
    def errors(self) -> int:
        return self.header_errors + self.checksum_errors + self.payload_errors

    def reset_for_cleanup(self) -> None:
        self.buffer.clear()
        self.strict = False
        self.last_frame_context = "none"

    def feed(self, data: bytes) -> list[Frame]:
        incoming = bytes(data)
        self.bytes_received += len(incoming)
        self.buffer.extend(incoming)
        self.high_water_bytes = max(self.high_water_bytes, len(self.buffer))
        frames: list[Frame] = []
        while True:
            magic_at = self.buffer.find(MAGIC_BYTES)
            if magic_at < 0:
                retained = self._partial_magic_suffix()
                discard = len(self.buffer) - retained
                if discard:
                    self._discard_or_fail(discard, "wire bytes precede frame magic")
                break
            if magic_at:
                self._discard_or_fail(magic_at, "wire bytes precede frame magic")
            if len(self.buffer) < HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.buffer)
            try:
                total_length = self._validate_header(fields)
            except CodecFailure:
                self.header_errors += 1
                if self.strict:
                    raise
                del self.buffer[0]
                self.bytes_discarded += 1
                continue
            if len(self.buffer) < total_length:
                break
            payload_length = fields[8]
            payload_end = HEADER_SIZE + payload_length
            checksum_view = memoryview(self.buffer)[:payload_end]
            try:
                expected = compute_checksum(checksum_view, fields[5])
            finally:
                checksum_view.release()
            actual = TRAILER.unpack_from(self.buffer, payload_end)[0]
            if actual != expected:
                self.checksum_errors += 1
                message = (
                    f"checksum mismatch: expected 0x{expected:08x}, "
                    f"received 0x{actual:08x}; "
                    f"kind=0x{fields[2]:02x} encoding={fields[6]} "
                    f"total_length={fields[7]} payload_length={fields[8]} "
                    f"run_id={fields[9]} sequence={fields[10]} "
                    f"request_id={fields[11]}"
                )
                if self.strict:
                    raise CodecFailure(message)
                del self.buffer[0]
                self.bytes_discarded += 1
                continue

            payload = bytes(self.buffer[HEADER_SIZE:payload_end])
            frame = Frame(
                version=fields[1],
                kind=fields[2],
                flags=fields[3],
                checksum_algorithm=fields[5],
                encoding=fields[6],
                total_length=fields[7],
                run_id=fields[9],
                sequence=fields[10],
                request_id=fields[11],
                first_sample_ticks=fields[12],
                item_count=fields[13],
                payload=payload,
                checksum=actual,
            )
            validation_started = (
                time.perf_counter_ns()
                if frame.encoding == FRAME_ENCODING_RLE
                and self.rle_validator is not None
                else 0
            )
            try:
                run_count, formula_pattern = self._validate_payload(frame)
            except CodecFailure:
                self.payload_errors += 1
                if self.strict:
                    raise
                del self.buffer[0]
                self.bytes_discarded += 1
                continue
            if run_count or formula_pattern is not None:
                validation_nanoseconds = (
                    time.perf_counter_ns() - validation_started
                    if formula_pattern is not None
                    else 0
                )
                frame = Frame(
                    **{
                        **frame.__dict__,
                        "run_count": run_count,
                        "rle_formula_pattern": formula_pattern,
                        "rle_validation_nanoseconds": validation_nanoseconds,
                    }
                )
            del self.buffer[:total_length]
            self.frames_decoded += 1
            self.last_frame_context = (
                f"kind=0x{frame.kind:02x} encoding={frame.encoding} "
                f"run_id={frame.run_id} sequence={frame.sequence} "
                f"request_id={frame.request_id} total_length={frame.total_length}"
            )
            frames.append(frame)

        retained_bound = MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1
        if len(self.buffer) > retained_bound:
            raise CodecFailure(
                f"parser retained {len(self.buffer)} bytes; bound is {retained_bound}"
            )
        high_water_bound = SERIAL_READ_BYTES + retained_bound
        if self.high_water_bytes > high_water_bound:
            raise CodecFailure(
                f"parser high water {self.high_water_bytes} exceeds {high_water_bound}"
            )
        return frames

    @staticmethod
    def _validate_header(fields: tuple[int, ...]) -> int:
        (
            magic,
            version,
            kind,
            flags,
            header_length,
            checksum,
            encoding,
            total_length,
            payload_length,
            run_id,
            sequence,
            request_id,
            first_sample_ticks,
            item_count,
        ) = fields
        if magic != MAGIC or version not in {PROTOCOL_V1, PROTOCOL_V2}:
            raise CodecFailure("invalid magic or protocol version")
        if header_length != HEADER_SIZE:
            raise CodecFailure("invalid fixed header length")
        if total_length != HEADER_SIZE + payload_length + TRAILER_SIZE:
            raise CodecFailure("inconsistent total and payload lengths")
        if kind in DATA_KINDS:
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            period = (
                ADC_PAIR_PERIOD_TICKS if kind == ADC_DATA else GPIO_SAMPLE_PERIOD_TICKS
            )
            if checksum not in SUPPORTED_CHECKSUMS:
                raise CodecFailure("data frame uses an unsupported checksum")
            if flags & ~DATA_FLAG_MASK:
                raise CodecFailure("data frame carries reserved flags")
            if flags & FLAG_OVERRUN_BEFORE and not flags & FLAG_GAP_BEFORE:
                raise CodecFailure("OVERRUN_BEFORE lacks GAP_BEFORE")
            if run_id == 0 or request_id != 0 or item_count != expected_items:
                raise CodecFailure("invalid data run/request/item fields")
            if first_sample_ticks % period:
                raise CodecFailure("data timestamp is not source-period aligned")
            epoch = bool(flags & FLAG_EPOCH_START)
            if epoch != (sequence == 0 and first_sample_ticks == 0):
                raise CodecFailure("EPOCH_START disagrees with logical position")
            if version == PROTOCOL_V1:
                if (
                    encoding != FRAME_ENCODING_RAW
                    or total_length != DATA_FRAME_BYTES
                    or payload_length != DATA_PAYLOAD_BYTES
                ):
                    raise CodecFailure("protocol-v1 data shape changed")
            elif encoding == FRAME_ENCODING_RAW:
                if (
                    total_length != DATA_FRAME_BYTES
                    or payload_length != DATA_PAYLOAD_BYTES
                ):
                    raise CodecFailure("protocol-v2 RAW shape is invalid")
            elif encoding == FRAME_ENCODING_RLE:
                record_bytes = 6 if kind == ADC_DATA else 3
                max_runs = 674 if kind == ADC_DATA else 1349
                max_payload = 4044 if kind == ADC_DATA else 4047
                if (
                    not MIN_V2_RLE_FRAME_BYTES <= total_length < DATA_FRAME_BYTES
                    or payload_length == 0
                    or payload_length > max_payload
                    or payload_length % record_bytes
                    or payload_length // record_bytes > max_runs
                ):
                    raise CodecFailure("protocol-v2 RLE shape exceeds its bounds")
            else:
                raise CodecFailure("data frame has an unknown encoding")
            return total_length

        if kind not in RESPONSE_KINDS:
            raise CodecFailure(f"unexpected device frame kind 0x{kind:02x}")
        if checksum != BOOTSTRAP_CHECKSUM or encoding != FRAME_ENCODING_RAW:
            raise CodecFailure("control response changed bootstrap checksum/encoding")
        if flags not in {0, FLAG_RESPONSE_ERROR}:
            raise CodecFailure("control response carries invalid flags")
        if kind == ERROR_RESPONSE and flags != FLAG_RESPONSE_ERROR:
            raise CodecFailure("generic error response lacks error flag")
        control_limit = (
            MAX_V1_CONTROL_FRAME_BYTES
            if version == PROTOCOL_V1
            else MAX_V2_CONTROL_FRAME_BYTES
        )
        if not HEADER_SIZE + TRAILER_SIZE <= total_length <= control_limit:
            raise CodecFailure("control response exceeds its finite bound")
        if request_id == 0 or sequence or first_sample_ticks or item_count:
            raise CodecFailure("invalid response correlation/data-only fields")
        expected_payload = (
            4
            if flags == FLAG_RESPONSE_ERROR and kind != ERROR_RESPONSE
            else SUCCESS_PAYLOAD_SIZE[version][kind]
        )
        if payload_length != expected_payload:
            raise CodecFailure("response payload length disagrees with its kind")
        if kind == START_RESPONSE and flags == 0 and run_id == 0:
            raise CodecFailure("successful START requires a nonzero run ID")
        return total_length

    def _validate_payload(self, frame: Frame) -> tuple[int, str | None]:
        if frame.kind in DATA_KINDS:
            if frame.encoding == FRAME_ENCODING_RAW:
                return 0, None
            if self.rle_validator is not None:
                return self.rle_validator(frame)
            item_bytes = ADC_BYTES_PER_PAIR if frame.kind == ADC_DATA else 1
            record_bytes = item_bytes + 2
            decoded_items = 0
            previous: bytes | None = None
            run_count = 0
            for offset in range(0, len(frame.payload), record_bytes):
                run_length = struct.unpack_from("<H", frame.payload, offset)[0]
                if run_length == 0:
                    raise CodecFailure("RLE run length is zero")
                if run_length > frame.item_count - decoded_items:
                    raise CodecFailure("RLE decoded count exceeds advertised bound")
                item = frame.payload[offset + 2 : offset + record_bytes]
                if item == previous:
                    raise CodecFailure("adjacent equal RLE records are noncanonical")
                if frame.kind == ADC_DATA:
                    adc0, adc1 = struct.unpack("<HH", item)
                    if adc0 & ~ADC_CODE_MASK or adc1 & ~ADC_CODE_MASK:
                        raise CodecFailure("RLE ADC item exceeds 12 bits")
                decoded_items += run_length
                previous = item
                run_count += 1
            if decoded_items != frame.item_count:
                raise CodecFailure("RLE runs do not sum to header.item_count")
            return run_count, None

        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == FLAG_RESPONSE_ERROR
        if reserved or is_error != (status == 1) or (error == 0) == is_error:
            raise CodecFailure("response prefix status/flag/error disagrees")
        if not is_error and status != 0:
            raise CodecFailure("successful response has nonzero status")
        if error > 12:
            raise CodecFailure("response reports an unknown error code")
        if is_error and frame.kind != ERROR_RESPONSE:
            return 0, None
        if frame.kind == INFO_RESPONSE:
            reserved_ranges = (
                frame.payload[1:2],
                frame.payload[61:62],
                frame.payload[118:120],
                frame.payload[127:128],
                frame.payload[154:156],
                frame.payload[182:184],
                frame.payload[230:232],
                frame.payload[334:336],
            )
            if any(any(section) for section in reserved_ranges):
                raise CodecFailure("INFO reserved fields are nonzero")
        elif frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            if frame.payload[1] or frame.payload[11]:
                raise CodecFailure("configuration response reserved byte is nonzero")
        elif frame.kind == GET_STATUS_RESPONSE:
            reserved_offsets = [1, 226, 227, 274, 275]
            if frame.version == PROTOCOL_V2:
                reserved_offsets.extend(
                    [1229, 1234, 1235, *range(1360, 1364), *range(1480, 1484)]
                )
            if any(frame.payload[offset] for offset in reserved_offsets):
                raise CodecFailure("STATUS reserved fields are nonzero")
        elif frame.kind == STOP_RESPONSE:
            if frame.payload[1] or any(frame.payload[5:]):
                raise CodecFailure("STOP reserved fields are nonzero")
        elif frame.kind == RESET_STATS_RESPONSE and frame.payload[1]:
            raise CodecFailure("RESET_STATS reserved byte is nonzero")
        elif frame.kind == ERROR_RESPONSE and (
            frame.payload[1] or any(frame.payload[6:])
        ):
            raise CodecFailure("generic error reserved fields are nonzero")
        return 0, None

    def _partial_magic_suffix(self) -> int:
        maximum = min(len(self.buffer), len(MAGIC_BYTES) - 1)
        for length in range(maximum, 0, -1):
            if self.buffer.endswith(MAGIC_BYTES[:length]):
                return length
        return 0

    def _discard_or_fail(self, count: int, message: str) -> None:
        if self.strict:
            preview_bytes = min(count, 32)
            prefix = bytes(self.buffer[:preview_bytes]).hex()
            suffix = bytes(self.buffer[max(0, count - preview_bytes) : count]).hex()
            raise CodecFailure(
                f"{message}: discard_bytes={count} buffered_bytes={len(self.buffer)} "
                f"prefix_hex={prefix} suffix_hex={suffix} "
                f"last_frame=({self.last_frame_context})"
            )
        del self.buffer[:count]
        self.bytes_discarded += count


# Complete scalar STATUS layout copied from the reviewed protocol-v2 contract.
# Keeping this table local is intentional: the remote runner must not trust the
# implementation package it is grading.
_STATUS_LAYOUT = """
response_status u8 0
reserved u8 1
error_code u16 2
device_state u8 4
stream_mask u8 5
source u8 6
data_checksum_algorithm u8 7
data_frame_bytes u32 8
adc_frames_emitted u64 12
gpio_frames_emitted u64 20
adc_items_dropped u64 28
gpio_items_dropped u64 36
parser_errors u32 44
transport_errors u32 48
stats_generation u32 52
gpio_samples_captured u64 56
gpio_samples_packed u64 64
gpio_samples_framed u64 72
gpio_samples_transmitted u64 80
gpio_raw_samples_lost u64 88
gpio_packer_samples_dropped u64 96
gpio_raw_ring_overruns u64 104
gpio_dma_major_loops u64 112
gpio_raw_ready_depth u16 120
gpio_raw_ready_high_water u16 122
gpio_packed_ready_depth u16 124
gpio_packed_ready_high_water u16 126
packet_ready_depth u16 128
packet_transmit_depth u16 130
packet_owned_high_water u16 132
gpio_processing_cpu_basis_points u16 134
gpio_hardware_errors u32 136
gpio_raw_invariant_errors u32 140
gpio_packer_source_errors u32 144
gpio_packer_pipeline_errors u32 148
gpio_packer_chronology_errors u32 152
gpio_resource_conflicts u32 156
gpio_start_errors u32 160
gpio_stop_errors u32 164
gpio_stale_dma_completions u32 168
adc_resolution_bits u8 172
adc_container_bytes u8 173
adc0_calibration_state u8 174
adc1_calibration_state u8 175
adc_code_min u16 176
adc_code_max u16 178
adc_reference u8 180
adc_clock_source u8 181
adc_clock_divider u8 182
adc_hardware_average_count u8 183
adc_reference_mv_nominal u16 184
adc_input_min_mv_nominal u16 186
adc_input_max_mv_nominal u16 188
adc_sample_time_adck u8 190
adc_conversion_mode u8 191
adc_configuration_flags u16 192
adc0_pin u8 194
adc1_pin u8 195
adc0_peripheral u8 196
adc1_peripheral u8 197
adc0_channel u8 198
adc1_channel u8 199
adc_ipg_clock_hz u32 200
adc_clock_hz u32 204
adc_calibration_deadline_us u32 208
adc0_calibration_cycles u32 212
adc1_calibration_cycles u32 216
adc_initialization_error_flags u32 220
adc_trigger_configuration_flags u16 224
reserved_2 u16 226
adc_trigger_error_flags u32 228
adc_trigger_pit_clock_hz u32 232
adc_trigger_dwt_clock_hz u32 236
adc_trigger_gpio_master_rate_hz u32 240
adc_trigger_pair_rate_hz u32 244
adc_trigger_ipg_clock_hz u32 248
adc_trigger_gpio_master_pit_channel u8 252
adc_trigger_pair_pit_channel u8 253
adc_trigger_gpio_master_pit_load u8 254
adc_trigger_pair_pit_load u8 255
adc_trigger_predivider u8 256
adc_trigger_chain_length u8 257
adc0_trigger_xbar_input u8 258
adc1_trigger_xbar_input u8 259
adc0_trigger_xbar_output u8 260
adc1_trigger_xbar_output u8 261
adc0_etc_trigger_queue u8 262
adc1_etc_trigger_queue u8 263
adc0_trigger_initial_delay u16 264
adc1_trigger_initial_delay u16 266
adc0_trigger_effective_delay u16 268
adc1_trigger_effective_delay u16 270
adc_trigger_phase_ipg_cycles u16 272
reserved_3 u16 274
adc_trigger_ccm_cscmr1_configured u32 276
adc_trigger_ccm_ccgr1_configured u32 280
adc_trigger_ccm_ccgr2_configured u32 284
adc_trigger_pit_mcr_configured u32 288
adc_trigger_gpio_master_tctrl_configured u32 292
adc_trigger_pair_tctrl_configured u32 296
adc_etc_ctrl_configured u32 300
adc0_etc_trigger_ctrl_configured u32 304
adc1_etc_trigger_ctrl_configured u32 308
adc0_etc_trigger_counter_configured u32 312
adc1_etc_trigger_counter_configured u32 316
adc0_etc_chain_configured u32 320
adc1_etc_chain_configured u32 324
adc_etc_done0_1_irq_final u32 328
adc_etc_done2_err_irq_final u32 332
adc0_completion_count u32 336
adc1_completion_count u32 340
adc_completion_delta_cycles u32 344
adc_completion_expected_delta_cycles u32 348
adc_completion_tolerance_cycles u32 352
adc_completion_diagnostic_elapsed_cycles u32 356
adc_trigger_error_count u32 360
adc0_trigger_xbar_sel_configured u16 364
adc1_trigger_xbar_sel_configured u16 366
adc0_dma_major_loops u64 368
adc1_dma_major_loops u64 376
adc0_dma_results u64 384
adc1_dma_results u64 392
adc_paired_major_loops u64 400
adc_buffers_completed u64 408
adc_buffers_acquired u64 416
adc_buffers_released u64 424
adc_pairs_captured u64 432
adc_pairs_delivered u64 440
adc_pairs_framed u64 448
adc_pairs_transmitted u64 456
adc_raw_pairs_lost u64 464
adc_stop_pairs_discarded u64 472
adc_incomplete_conversions u64 480
adc_overwritten_conversions u64 488
adc_raw_ring_overruns u64 496
adc_incomplete_buffers u64 504
adc_raw_ready_depth u16 512
adc_raw_ready_high_water u16 514
adc_etc_error_events u32 516
adc_etc_error_flags u32 520
adc_dma_error_events u32 524
adc_completion_mismatches u32 528
adc_destination_mismatches u32 532
adc_schedule_exhaustions u32 536
adc_raw_invariant_errors u32 540
adc_stale_completions u32 544
adc_resource_conflicts u32 548
adc_start_errors u32 552
adc_stop_errors u32 556
adc_stale_interrupts u32 560
adc_packer_source_errors u32 564
adc_packer_pipeline_errors u32 568
adc_packer_chronology_errors u32 572
adc_frames_generated u64 576
adc_items_generated u64 584
adc_frames_framed_pipeline u64 592
adc_items_framed_pipeline u64 600
adc_items_emitted u64 608
adc_frames_transmitted u64 616
adc_items_transmitted_pipeline u64 624
adc_frames_dropped u64 632
gpio_frames_generated u64 640
gpio_items_generated u64 648
gpio_frames_framed_pipeline u64 656
gpio_items_framed_pipeline u64 664
gpio_items_emitted u64 672
gpio_frames_transmitted u64 680
gpio_items_transmitted_pipeline u64 688
gpio_frames_dropped u64 696
adc_payload_bytes_produced u64 704
adc_payload_bytes_framed u64 712
adc_payload_bytes_emitted u64 720
adc_payload_bytes_transmitted u64 728
adc_payload_bytes_dropped u64 736
adc_framed_bytes_framed u64 744
adc_framed_bytes_emitted u64 752
adc_framed_bytes_transmitted u64 760
gpio_payload_bytes_produced u64 768
gpio_payload_bytes_framed u64 776
gpio_payload_bytes_emitted u64 784
gpio_payload_bytes_transmitted u64 792
gpio_payload_bytes_dropped u64 800
gpio_framed_bytes_framed u64 808
gpio_framed_bytes_emitted u64 816
gpio_framed_bytes_transmitted u64 824
adc_packet_ready_depth u16 832
gpio_packet_ready_depth u16 834
adc_packet_transmit_depth u16 836
gpio_packet_transmit_depth u16 838
adc_packet_ready_high_water u16 840
gpio_packet_ready_high_water u16 842
adc_packet_transmit_high_water u16 844
gpio_packet_transmit_high_water u16 846
packet_ready_high_water u16 848
packet_transmit_high_water u16 850
packet_frames_promoted u64 852
packet_fairness_deferrals u64 860
packet_accounted_frame_skew u64 868
data_payload_bytes_transmitted u64 876
data_framed_bytes_transmitted u64 884
packet_pool_exhaustions u32 892
packet_invalid_operations u32 896
packet_encoding_rejections u32 900
packet_ready_queue_rejections u32 904
packet_transmit_queue_rejections u32 908
commands_accepted u32 912
commands_rejected u32 916
bad_checksums u32 920
bad_lengths u32 924
bad_types u32 928
bad_versions u32 932
timeouts u32 936
partial_usb_writes u32 940
state_errors u32 944
usb_short_capacity_deferrals u32 948
usb_rx_stall_events u32 952
usb_tx_stall_events u32 956
usb_io_errors u32 960
usb_command_queue_depth u16 964
usb_response_queue_depth u16 966
usb_lower_priority_queue_depth u16 968
usb_command_queue_high_water u16 970
usb_response_queue_high_water u16 972
usb_active_frame_bytes_sent u16 974
packet_owned_depth u16 976
usb_active_frame_size u16 978
adc_cache_dma_discards u32 980
adc_cache_cpu_invalidations u32 984
gpio_cache_dma_discards u32 988
gpio_cache_cpu_invalidations u32 992
bad_flags u32 996
bad_payloads u32 1000
bad_request_ids u32 1004
responses_queued u32 1008
responses_completed u32 1012
response_queue_rejections u32 1016
response_reservations_abandoned u32 1020
packet_pressure_evictions u64 1024
packet_capacity_drops_without_evictable_frame u64 1032
adc_frames_evicted u64 1040
adc_frames_evicted_after_promotion u64 1048
gpio_frames_evicted u64 1056
gpio_frames_evicted_after_promotion u64 1064
adc_packet_filling_depth u16 1072
gpio_packet_filling_depth u16 1074
adc_frames_dropped_after_framing u64 1076
adc_frames_dropped_after_promotion u64 1084
gpio_frames_dropped_after_framing u64 1092
gpio_frames_dropped_after_promotion u64 1100
gpio_buffers_completed u64 1108
gpio_buffers_acquired u64 1116
gpio_buffers_released u64 1124
gpio_samples_delivered u64 1132
gpio_stop_samples_discarded u64 1140
gpio_frames_produced u64 1148
gpio_samples_produced u64 1156
gpio_frames_packed u64 1164
gpio_duplicate_samples_ignored u64 1172
adc_frames_consumed u64 1180
adc_pairs_consumed u64 1188
adc_raw_gap_pairs u64 1196
adc_raw_drop_pairs_projected u64 1204
gpio_raw_drop_samples_projected u64 1212
gpio_packer_drop_samples_projected u64 1220
configuration_encoding u8 1228
reserved_7 u8 1229
temporary_pages_owned u16 1230
temporary_page_high_water u16 1232
reserved_8 u16 1234
temporary_page_exhaustions u32 1236
encode_failures u32 1240
adc_encoded_payload_bytes_framed u64 1244
adc_encoded_payload_bytes_transmitted u64 1252
adc_encoded_payload_bytes_dropped u64 1260
adc_encoded_payload_bytes_queued u64 1268
adc_encoded_wire_bytes_dropped u64 1276
adc_encoded_wire_bytes_queued u64 1284
adc_raw_frames u64 1292
adc_rle_frames u64 1300
adc_rle_runs u64 1308
adc_fallback_frames u64 1316
adc_fallback_not_smaller u64 1324
adc_fallback_temporary_page_unavailable u64 1332
adc_fallback_encoder_failure u64 1340
adc_encode_cycles u64 1348
adc_encode_failures u32 1356
reserved_9 u32 1360
gpio_encoded_payload_bytes_framed u64 1364
gpio_encoded_payload_bytes_transmitted u64 1372
gpio_encoded_payload_bytes_dropped u64 1380
gpio_encoded_payload_bytes_queued u64 1388
gpio_encoded_wire_bytes_dropped u64 1396
gpio_encoded_wire_bytes_queued u64 1404
gpio_raw_frames u64 1412
gpio_rle_frames u64 1420
gpio_rle_runs u64 1428
gpio_fallback_frames u64 1436
gpio_fallback_not_smaller u64 1444
gpio_fallback_temporary_page_unavailable u64 1452
gpio_fallback_encoder_failure u64 1460
gpio_encode_cycles u64 1468
gpio_encode_failures u32 1476
reserved_10 u32 1480
"""

_SCALAR_FORMAT = {"u8": "<B", "u16": "<H", "u32": "<I", "u64": "<Q"}
STATUS_FIELDS: dict[str, tuple[str, int]] = {}
for _line in _STATUS_LAYOUT.splitlines():
    if _line:
        _name, _scalar, _offset = _line.split()
        STATUS_FIELDS[_name] = (_SCALAR_FORMAT[_scalar], int(_offset))


@dataclass(frozen=True)
class StatusSnapshot:
    """All protocol-v2 STATUS scalars decoded from one validated response."""

    values: dict[str, int]

    @classmethod
    def from_frame(cls, frame: Frame) -> StatusSnapshot:
        if frame.version != PROTOCOL_V2 or frame.kind != GET_STATUS_RESPONSE:
            raise CodecFailure("full STATUS telemetry requires protocol v2")
        if frame.flags:
            raise FirmwareFailure("GET_STATUS returned an error response")
        values = {
            name: int(struct.unpack_from(fmt, frame.payload, offset)[0])
            for name, (fmt, offset) in STATUS_FIELDS.items()
        }
        return cls(values)

    def __getattr__(self, name: str) -> int:
        try:
            return self.values[name]
        except KeyError as error:
            raise AttributeError(name) from error


def _mix_u32(value: int) -> int:
    value = (value + 0x9E3779B9) & 0xFFFFFFFF
    value = ((value ^ (value >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    value = ((value ^ (value >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return (value ^ (value >> 16)) & 0xFFFFFFFF


def logical_item(pattern: str, kind: int, index: int) -> bytes:
    """Return one target-defined logical ADC pair or GPIO sample."""

    if kind == ADC_DATA:
        if pattern == "constant":
            adc0, adc1 = 0x155, 0xAAA
        elif pattern == "sparse-hold":
            adc0 = 0x456 ^ (((index // 997) & 1) << 3)
            adc1 = 0x789
        elif pattern == "slow-adc":
            adc0 = (0x100 + index // 8) & ADC_CODE_MASK
            adc1 = (0x900 + index // 11) & ADC_CODE_MASK
        elif pattern == "alternating":
            adc0, adc1 = (0x123, 0xABC) if index % 2 == 0 else (0xFED, 0x456)
        elif pattern == "incompressible":
            adc0 = _mix_u32(index & 0xFFFFFFFF) & ADC_CODE_MASK
            adc1 = (_mix_u32((index ^ 0xA5A55A5A) & 0xFFFFFFFF) >> 12) & ADC_CODE_MASK
        else:  # pragma: no cover - configuration parser owns this invariant
            raise ValueError(f"unknown pattern {pattern!r}")
        return struct.pack("<HH", adc0, adc1)

    if kind != GPIO_DATA:
        raise ValueError(f"unknown data kind 0x{kind:02x}")
    if pattern == "constant":
        value = 0x5A
    elif pattern == "sparse-hold":
        epoch = index // 4001
        gray = epoch ^ (epoch >> 1)
        value = 0x33 ^ (gray & 0xFF)
    elif pattern == "slow-adc":
        value = (0x40 + index // 16) & 0xFF
    elif pattern == "alternating":
        value = 0x55 if index % 2 == 0 else 0xAA
    elif pattern == "incompressible":
        value = _mix_u32((index ^ 0xC001D00D) & 0xFFFFFFFF) & 0xFF
    else:  # pragma: no cover - configuration parser owns this invariant
        raise ValueError(f"unknown pattern {pattern!r}")
    return bytes((value,))


def expected_run_length(pattern: str, kind: int, index: int, maximum: int) -> int:
    """Return the maximal frame-local run from ``index`` without expansion."""

    if maximum <= 0:
        raise ValueError("run bound must be positive")
    if pattern == "constant":
        return maximum
    if pattern == "alternating":
        return 1
    if pattern == "slow-adc":
        if kind == ADC_DATA:
            return min(maximum, 8 - index % 8, 11 - index % 11)
        return min(maximum, 16 - index % 16)
    if pattern == "sparse-hold" and kind == ADC_DATA:
        return min(maximum, 997 - index % 997)
    if pattern == "sparse-hold":
        item = logical_item(pattern, kind, index)
        consumed = 0
        cursor = index
        while consumed < maximum:
            step = min(maximum - consumed, 4001 - cursor % 4001)
            consumed += step
            cursor += step
            if consumed == maximum or logical_item(pattern, kind, cursor) != item:
                return consumed
        return maximum

    item = logical_item(pattern, kind, index)
    for length in range(1, maximum):
        if logical_item(pattern, kind, index + length) != item:
            return length
    return maximum


_FIXED_PAYLOAD_CACHE: dict[tuple[str, int], bytes] = {}


def fixed_payload(pattern: str, kind: int) -> bytes | None:
    """Return a reusable exact payload for frame-periodic patterns."""

    key = (pattern, kind)
    if key in _FIXED_PAYLOAD_CACHE:
        return _FIXED_PAYLOAD_CACHE[key]
    item_count = ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
    if pattern == "constant":
        result = logical_item(pattern, kind, 0) * item_count
    elif pattern == "alternating":
        result = (logical_item(pattern, kind, 0) + logical_item(pattern, kind, 1)) * (
            item_count // 2
        )
    else:
        return None
    _FIXED_PAYLOAD_CACHE[key] = result
    return result


@dataclass
class StreamMetrics:
    """Bounded host observations for one logical stream."""

    name: str
    kind: int
    items_per_frame: int
    item_bytes: int
    frames: int = 0
    raw_frames: int = 0
    rle_frames: int = 0
    rle_runs: int = 0
    logical_items: int = 0
    logical_payload_bytes: int = 0
    encoded_payload_bytes: int = 0
    framed_bytes: int = 0
    decode_nanoseconds: int = 0
    decoded_logical_adler32: int | None = None
    formula_full_frames: int = 0
    formula_spot_items: int = 0
    first_sequence: int | None = None
    last_sequence: int | None = None

    def summary(self) -> dict[str, int | float | None]:
        encoded_ratio = (
            self.encoded_payload_bytes / self.logical_payload_bytes
            if self.logical_payload_bytes
            else None
        )
        framed_ratio = (
            self.framed_bytes / (self.frames * DATA_FRAME_BYTES)
            if self.frames
            else None
        )
        decode_seconds = self.decode_nanoseconds / 1_000_000_000
        return {
            "frames": self.frames,
            "raw_frames": self.raw_frames,
            "rle_frames": self.rle_frames,
            "rle_runs": self.rle_runs,
            "logical_items": self.logical_items,
            "raw_payload_bytes": self.logical_payload_bytes,
            "raw_framed_bytes": self.frames * DATA_FRAME_BYTES,
            "logical_payload_bytes": self.logical_payload_bytes,
            "encoded_payload_bytes": self.encoded_payload_bytes,
            "framed_bytes": self.framed_bytes,
            "encoded_payload_ratio": encoded_ratio,
            "framed_byte_ratio": framed_ratio,
            "decode_seconds": decode_seconds,
            "decode_bytes_per_second": (
                self.logical_payload_bytes / decode_seconds
                if decode_seconds > 0
                else None
            ),
            "decoded_logical_adler32": self.decoded_logical_adler32,
            "formula_full_frames": self.formula_full_frames,
            "formula_spot_items": self.formula_spot_items,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
        }


class CaptureValidator:
    """Validate logical v2 frames and retain only aggregate measurements."""

    def __init__(self, pattern: str, configuration_encoding: int) -> None:
        self.pattern = pattern
        self.configuration_encoding = configuration_encoding
        self.run_id: int | None = None
        self.streams = {
            ADC_DATA: StreamMetrics(
                "adc", ADC_DATA, ADC_PAIRS_PER_FRAME, ADC_BYTES_PER_PAIR
            ),
            GPIO_DATA: StreamMetrics("gpio", GPIO_DATA, GPIO_SAMPLES_PER_FRAME, 1),
        }

    def observe(self, frame: Frame) -> None:
        if frame.version != PROTOCOL_V2 or frame.kind not in DATA_KINDS:
            raise FirmwareFailure("capture contains a non-v2 data frame")
        if self.configuration_encoding == CONFIGURATION_ENCODING_RAW:
            if frame.encoding != FRAME_ENCODING_RAW:
                raise FirmwareFailure("RAW configuration emitted an RLE frame")
        elif frame.encoding not in {FRAME_ENCODING_RAW, FRAME_ENCODING_RLE}:
            raise FirmwareFailure("RLE_AUTO emitted an unknown frame encoding")
        if self.run_id is None:
            self.run_id = frame.run_id
        elif frame.run_id != self.run_id:
            raise FirmwareFailure("data run ID changed during one capture")

        metrics = self.streams[frame.kind]
        expected_sequence = metrics.frames & 0xFFFFFFFF
        if frame.sequence != expected_sequence:
            raise FirmwareFailure(
                f"{metrics.name} sequence {frame.sequence} != {expected_sequence}"
            )
        expected_ticks = metrics.frames * FRAME_COVERAGE_TICKS
        if frame.first_sample_ticks != expected_ticks:
            raise FirmwareFailure(
                f"{metrics.name} timestamp {frame.first_sample_ticks} "
                f"!= {expected_ticks}"
            )
        required_flags = FLAG_EPOCH_START if metrics.frames == 0 else 0
        if self.pattern != "physical":
            required_flags |= FLAG_SYNTHETIC
        if frame.flags != required_flags:
            raise FirmwareFailure(
                f"{metrics.name} flags 0x{frame.flags:04x} != 0x{required_flags:04x}"
            )

        started = time.perf_counter_ns()
        if self.pattern == "physical":
            logical_payload = self._decode_physical(frame, metrics)
            metrics.decoded_logical_adler32 = zlib.adler32(
                logical_payload,
                metrics.decoded_logical_adler32 or 1,
            )
            full, spots = 0, 0
        elif frame.encoding == FRAME_ENCODING_RLE:
            if frame.rle_formula_pattern is None:
                run_count, formula_pattern = self.validate_rle_payload(frame)
                if run_count != frame.run_count or formula_pattern != self.pattern:
                    raise CodecFailure("RLE formula pass disagrees with bounded parser")
                elapsed = time.perf_counter_ns() - started
            elif frame.rle_formula_pattern != self.pattern:
                raise CodecFailure("RLE frame carries the wrong formula proof")
            else:
                elapsed = frame.rle_validation_nanoseconds
            full, spots = 1, metrics.items_per_frame
        else:
            full, spots = self._validate_raw_formula(frame, metrics)
        if frame.encoding != FRAME_ENCODING_RLE or self.pattern == "physical":
            elapsed = time.perf_counter_ns() - started

        if metrics.first_sequence is None:
            metrics.first_sequence = frame.sequence
        metrics.last_sequence = frame.sequence
        metrics.frames += 1
        metrics.raw_frames += frame.encoding == FRAME_ENCODING_RAW
        metrics.rle_frames += frame.encoding == FRAME_ENCODING_RLE
        metrics.rle_runs += frame.run_count
        metrics.logical_items += frame.item_count
        metrics.logical_payload_bytes += frame.item_count * metrics.item_bytes
        metrics.encoded_payload_bytes += len(frame.payload)
        metrics.framed_bytes += frame.total_length
        metrics.decode_nanoseconds += elapsed
        metrics.formula_full_frames += full
        metrics.formula_spot_items += spots

    @staticmethod
    def _decode_physical(frame: Frame, metrics: StreamMetrics) -> bytes:
        """Boundedly decode one physical frame and validate its sample range."""

        if frame.encoding == FRAME_ENCODING_RAW:
            logical_payload = frame.payload
        else:
            record_bytes = metrics.item_bytes + 2
            decoded = bytearray()
            previous: bytes | None = None
            for offset in range(0, len(frame.payload), record_bytes):
                run_length = struct.unpack_from("<H", frame.payload, offset)[0]
                item = frame.payload[offset + 2 : offset + record_bytes]
                if item == previous:
                    raise CodecFailure("physical RLE contains adjacent equal records")
                if len(decoded) + run_length * metrics.item_bytes > DATA_PAYLOAD_BYTES:
                    raise CodecFailure("physical RLE exceeds the logical payload bound")
                decoded.extend(item * run_length)
                previous = item
            logical_payload = bytes(decoded)
        if len(logical_payload) != DATA_PAYLOAD_BYTES:
            raise CodecFailure("physical decode does not fill one logical payload")
        if frame.kind == ADC_DATA and logical_payload[1::2].translate(
            None, VALID_ADC_HIGH_BYTES
        ):
            raise FirmwareFailure("physical ADC payload contains a code above 12 bits")
        return logical_payload

    def validate_rle_payload(self, frame: Frame) -> tuple[int, str]:
        """Validate one synthetic RLE payload after its wire checksum passes."""

        metrics = self.streams[frame.kind]
        if self.pattern == "slow-adc":
            records = self._validate_slow_adc_rle(frame, metrics)
        else:
            records = self._validate_generic_rle(frame, metrics)
        return records, self.pattern

    def _validate_generic_rle(self, frame: Frame, metrics: StreamMetrics) -> int:
        record_bytes = metrics.item_bytes + 2
        logical = frame.sequence * metrics.items_per_frame
        remaining = metrics.items_per_frame
        records = 0
        previous: bytes | None = None
        formula_mismatch_at: int | None = None
        for offset in range(0, len(frame.payload), record_bytes):
            run_length = struct.unpack_from("<H", frame.payload, offset)[0]
            if run_length == 0:
                raise CodecFailure("RLE run length is zero")
            if run_length > remaining:
                raise CodecFailure("RLE decoded count exceeds advertised bound")
            item = frame.payload[offset + 2 : offset + record_bytes]
            if item == previous:
                raise CodecFailure("adjacent equal RLE records are noncanonical")
            if frame.kind == ADC_DATA:
                adc0, adc1 = struct.unpack("<HH", item)
                if adc0 & ~ADC_CODE_MASK or adc1 & ~ADC_CODE_MASK:
                    raise CodecFailure("RLE ADC item exceeds 12 bits")
            expected_item = logical_item(self.pattern, frame.kind, logical)
            expected_run = expected_run_length(
                self.pattern, frame.kind, logical, remaining
            )
            if formula_mismatch_at is None and (
                item != expected_item or run_length != expected_run
            ):
                formula_mismatch_at = logical
            previous = item
            logical += run_length
            remaining -= run_length
            records += 1
        if remaining:
            raise CodecFailure("RLE runs do not sum to header.item_count")
        if formula_mismatch_at is not None:
            raise FirmwareFailure(
                f"{metrics.name} RLE formula/run mismatch at logical "
                f"{formula_mismatch_at}"
            )
        return records

    @staticmethod
    def _validate_slow_adc_rle(frame: Frame, metrics: StreamMetrics) -> int:
        """Validate the record-dense slow-ADC workload without byte objects."""

        logical = frame.sequence * metrics.items_per_frame
        remaining = metrics.items_per_frame
        records = 0
        formula_mismatch_at: int | None = None
        if frame.kind == ADC_DATA:
            previous: tuple[int, int] | None = None
            for offset in range(0, len(frame.payload), 6):
                run_length, adc0, adc1 = struct.unpack_from(
                    "<HHH", frame.payload, offset
                )
                if run_length == 0:
                    raise CodecFailure("RLE run length is zero")
                if run_length > remaining:
                    raise CodecFailure("RLE decoded count exceeds advertised bound")
                item = (adc0, adc1)
                if item == previous:
                    raise CodecFailure("adjacent equal RLE records are noncanonical")
                if adc0 & ~ADC_CODE_MASK or adc1 & ~ADC_CODE_MASK:
                    raise CodecFailure("RLE ADC item exceeds 12 bits")
                expected_run = min(
                    remaining,
                    8 - logical % 8,
                    11 - logical % 11,
                )
                if formula_mismatch_at is None and (
                    run_length != expected_run
                    or adc0 != (0x100 + logical // 8) & ADC_CODE_MASK
                    or adc1 != (0x900 + logical // 11) & ADC_CODE_MASK
                ):
                    formula_mismatch_at = logical
                previous = item
                logical += run_length
                remaining -= run_length
                records += 1
        else:
            previous_gpio: int | None = None
            for offset in range(0, len(frame.payload), 3):
                run_length = frame.payload[offset] | frame.payload[offset + 1] << 8
                value = frame.payload[offset + 2]
                if run_length == 0:
                    raise CodecFailure("RLE run length is zero")
                if run_length > remaining:
                    raise CodecFailure("RLE decoded count exceeds advertised bound")
                if value == previous_gpio:
                    raise CodecFailure("adjacent equal RLE records are noncanonical")
                expected_run = min(remaining, 16 - logical % 16)
                if formula_mismatch_at is None and (
                    run_length != expected_run or value != (0x40 + logical // 16) & 0xFF
                ):
                    formula_mismatch_at = logical
                previous_gpio = value
                logical += run_length
                remaining -= run_length
                records += 1
        if remaining:
            raise CodecFailure("RLE runs do not sum to header.item_count")
        if formula_mismatch_at is not None:
            raise FirmwareFailure(
                f"{metrics.name} RLE formula/run mismatch at logical "
                f"{formula_mismatch_at}"
            )
        return records

    def _validate_raw_formula(
        self, frame: Frame, metrics: StreamMetrics
    ) -> tuple[int, int]:
        reusable = fixed_payload(self.pattern, frame.kind)
        if reusable is not None:
            if frame.payload != reusable:
                raise FirmwareFailure(f"{metrics.name} RAW fixed formula mismatch")
            return 1, metrics.items_per_frame

        logical_start = frame.sequence * metrics.items_per_frame
        if self.pattern != "incompressible":
            logical = logical_start
            payload_offset = 0
            remaining = metrics.items_per_frame
            while remaining:
                run = expected_run_length(self.pattern, frame.kind, logical, remaining)
                item = logical_item(self.pattern, frame.kind, logical)
                byte_count = run * metrics.item_bytes
                if (
                    frame.payload[payload_offset : payload_offset + byte_count]
                    != item * run
                ):
                    raise FirmwareFailure(
                        f"{metrics.name} RAW formula mismatch at logical {logical}"
                    )
                logical += run
                payload_offset += byte_count
                remaining -= run
            return 1, metrics.items_per_frame

        # The fmix workload intentionally has no short frame-local period.
        # Fully grade deterministic cadence frames and formula-spots on every
        # intervening frame so endurance validation remains faster than the
        # 8 MB/s wire while still covering the complete sequence domain.
        full_frame = frame.sequence < 2 or frame.sequence % 64 == 0
        offsets: Iterable[int]
        if full_frame:
            offsets = range(metrics.items_per_frame)
        else:
            rotating = frame.sequence % metrics.items_per_frame
            offsets = sorted(
                {
                    0,
                    1,
                    metrics.items_per_frame // 2,
                    metrics.items_per_frame - 2,
                    metrics.items_per_frame - 1,
                    rotating,
                    (rotating * 17 + 31) % metrics.items_per_frame,
                    (rotating * 257 + 7) % metrics.items_per_frame,
                }
            )
        checked = 0
        for item_offset in offsets:
            byte_offset = item_offset * metrics.item_bytes
            expected = logical_item(
                self.pattern, frame.kind, logical_start + item_offset
            )
            if (
                frame.payload[byte_offset : byte_offset + metrics.item_bytes]
                != expected
            ):
                raise FirmwareFailure(
                    f"{metrics.name} incompressible formula mismatch at "
                    f"logical {logical_start + item_offset}"
                )
            checked += 1
        return (1 if full_frame else 0), checked

    def combined_summary(self) -> dict[str, int | float | None]:
        streams = tuple(self.streams.values())
        logical = sum(stream.logical_payload_bytes for stream in streams)
        encoded = sum(stream.encoded_payload_bytes for stream in streams)
        framed = sum(stream.framed_bytes for stream in streams)
        raw_framed = sum(stream.frames for stream in streams) * DATA_FRAME_BYTES
        decode_ns = sum(stream.decode_nanoseconds for stream in streams)
        decode_seconds = decode_ns / 1_000_000_000
        return {
            "frames": sum(stream.frames for stream in streams),
            "raw_frames": sum(stream.raw_frames for stream in streams),
            "rle_frames": sum(stream.rle_frames for stream in streams),
            "rle_runs": sum(stream.rle_runs for stream in streams),
            "logical_items": sum(stream.logical_items for stream in streams),
            "raw_payload_bytes": logical,
            "raw_framed_bytes": raw_framed,
            "logical_payload_bytes": logical,
            "encoded_payload_bytes": encoded,
            "framed_bytes": framed,
            "encoded_payload_ratio": encoded / logical if logical else None,
            "framed_byte_ratio": framed / raw_framed if raw_framed else None,
            "decode_seconds": decode_seconds,
            "decode_bytes_per_second": (
                logical / decode_seconds if decode_seconds > 0 else None
            ),
        }


ZERO_COUNTER_FIELDS = (
    "adc_items_dropped",
    "gpio_items_dropped",
    "parser_errors",
    "transport_errors",
    "gpio_raw_samples_lost",
    "gpio_packer_samples_dropped",
    "gpio_raw_ring_overruns",
    "gpio_hardware_errors",
    "gpio_raw_invariant_errors",
    "gpio_packer_source_errors",
    "gpio_packer_pipeline_errors",
    "gpio_packer_chronology_errors",
    "gpio_resource_conflicts",
    "gpio_start_errors",
    "gpio_stop_errors",
    "gpio_stale_dma_completions",
    "adc_initialization_error_flags",
    "adc_trigger_error_flags",
    "adc_trigger_error_count",
    "adc_raw_pairs_lost",
    "adc_stop_pairs_discarded",
    "adc_incomplete_conversions",
    "adc_overwritten_conversions",
    "adc_raw_ring_overruns",
    "adc_incomplete_buffers",
    "adc_etc_error_events",
    "adc_etc_error_flags",
    "adc_dma_error_events",
    "adc_completion_mismatches",
    "adc_destination_mismatches",
    "adc_schedule_exhaustions",
    "adc_raw_invariant_errors",
    "adc_stale_completions",
    "adc_resource_conflicts",
    "adc_start_errors",
    "adc_stop_errors",
    "adc_stale_interrupts",
    "adc_packer_source_errors",
    "adc_packer_pipeline_errors",
    "adc_packer_chronology_errors",
    "adc_frames_dropped",
    "gpio_frames_dropped",
    "adc_payload_bytes_dropped",
    "gpio_payload_bytes_dropped",
    "packet_pool_exhaustions",
    "packet_invalid_operations",
    "packet_encoding_rejections",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
    "commands_rejected",
    "bad_checksums",
    "bad_lengths",
    "bad_types",
    "bad_versions",
    "timeouts",
    "state_errors",
    "usb_io_errors",
    "bad_flags",
    "bad_payloads",
    "bad_request_ids",
    "response_queue_rejections",
    "response_reservations_abandoned",
    "packet_pressure_evictions",
    "packet_capacity_drops_without_evictable_frame",
    "adc_frames_evicted",
    "adc_frames_evicted_after_promotion",
    "gpio_frames_evicted",
    "gpio_frames_evicted_after_promotion",
    "adc_frames_dropped_after_framing",
    "adc_frames_dropped_after_promotion",
    "gpio_frames_dropped_after_framing",
    "gpio_frames_dropped_after_promotion",
    "gpio_stop_samples_discarded",
    "gpio_duplicate_samples_ignored",
    "adc_raw_gap_pairs",
    "adc_raw_drop_pairs_projected",
    "gpio_raw_drop_samples_projected",
    "gpio_packer_drop_samples_projected",
    "temporary_page_exhaustions",
    "encode_failures",
    "adc_encoded_payload_bytes_dropped",
    "adc_encoded_wire_bytes_dropped",
    "adc_fallback_temporary_page_unavailable",
    "adc_fallback_encoder_failure",
    "adc_encode_failures",
    "gpio_encoded_payload_bytes_dropped",
    "gpio_encoded_wire_bytes_dropped",
    "gpio_fallback_temporary_page_unavailable",
    "gpio_fallback_encoder_failure",
    "gpio_encode_failures",
)

CURRENT_QUEUE_FIELDS = (
    "gpio_raw_ready_depth",
    "gpio_packed_ready_depth",
    "packet_ready_depth",
    "packet_transmit_depth",
    "adc_raw_ready_depth",
    "adc_packet_ready_depth",
    "gpio_packet_ready_depth",
    "adc_packet_transmit_depth",
    "gpio_packet_transmit_depth",
    "usb_command_queue_depth",
    "usb_response_queue_depth",
    "usb_lower_priority_queue_depth",
    "packet_owned_depth",
    "adc_packet_filling_depth",
    "gpio_packet_filling_depth",
    "temporary_pages_owned",
)

HIGH_WATER_FIELDS = (
    "gpio_raw_ready_high_water",
    "gpio_packed_ready_high_water",
    "packet_owned_high_water",
    "adc_raw_ready_high_water",
    "adc_packet_ready_high_water",
    "gpio_packet_ready_high_water",
    "adc_packet_transmit_high_water",
    "gpio_packet_transmit_high_water",
    "packet_ready_high_water",
    "packet_transmit_high_water",
    "usb_command_queue_high_water",
    "usb_response_queue_high_water",
    "temporary_page_high_water",
)

SERVICE_COUNTER_FIELDS = (
    "partial_usb_writes",
    "usb_short_capacity_deferrals",
    "usb_rx_stall_events",
    "usb_tx_stall_events",
    "packet_fairness_deferrals",
)

BOUNDED_PHYSICAL_STOP_TAIL_FIELDS = frozenset(
    {
        "adc_items_dropped",
        "gpio_items_dropped",
        "gpio_raw_samples_lost",
        "gpio_stop_samples_discarded",
        "adc_raw_pairs_lost",
        "adc_stop_pairs_discarded",
        "adc_incomplete_conversions",
        "adc_incomplete_buffers",
        "adc_completion_mismatches",
    }
)


def current_rss_bytes() -> int:
    """Return current RSS without adding a third-party process dependency."""

    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            resident_pages = int(statm.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum if sys.platform == "darwin" else maximum * 1024


def maximum_rss_bytes() -> int:
    maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum if sys.platform == "darwin" else maximum * 1024


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[rank]


@dataclass
class StatusObserver:
    """Reduce periodic STATUS, latency, queue, and process memory samples."""

    expected_source: int
    expected_encoding: int
    expected_checksum: int
    latencies: list[float] = field(default_factory=list)
    samples: int = 0
    maximum_current_depths: dict[str, int] = field(default_factory=dict)
    maximum_high_waters: dict[str, int] = field(default_factory=dict)
    service_counters: dict[str, int] = field(default_factory=dict)
    rss_start_bytes: int = field(default_factory=current_rss_bytes)
    rss_end_bytes: int = 0
    rss_maximum_bytes: int = 0
    stats_generation: int | None = None

    def observe(self, status: StatusSnapshot, latency: float) -> None:
        if self.samples >= MAX_STATUS_SAMPLES:
            raise ServiceFailure("STATUS sample bound exceeded")
        validate_status_health(status)
        if (
            status.device_state != STATE_RUNNING
            or status.stream_mask != STREAM_BOTH
            or status.source != self.expected_source
            or status.configuration_encoding != self.expected_encoding
            or status.data_checksum_algorithm != self.expected_checksum
            or status.data_frame_bytes != DATA_FRAME_BYTES
        ):
            raise FirmwareFailure("running STATUS contradicts applied configuration")
        if self.stats_generation is None:
            self.stats_generation = status.stats_generation
        elif status.stats_generation != self.stats_generation:
            raise FirmwareFailure("stats generation changed during active capture")
        if status.packet_accounted_frame_skew > 1:
            raise FirmwareFailure("fair scheduler accounted-frame skew exceeds one")
        if status.temporary_pages_owned > 1 or status.temporary_page_high_water > 1:
            raise FirmwareFailure("temporary RLE ownership exceeds one fixed page")
        if (
            status.packet_owned_depth > PACKET_BUFFER_COUNT
            or status.packet_owned_high_water > PACKET_BUFFER_COUNT
        ):
            raise FirmwareFailure("packet ownership exceeds the fixed 200-page pool")
        queue_limits = {
            "adc_raw_ready_depth": ADC_DMA_RING_DEPTH,
            "adc_raw_ready_high_water": ADC_DMA_RING_DEPTH,
            "gpio_raw_ready_depth": GPIO_RAW_RING_DEPTH,
            "gpio_raw_ready_high_water": GPIO_RAW_RING_DEPTH,
            "gpio_packed_ready_depth": GPIO_PACKED_RING_DEPTH,
            "gpio_packed_ready_high_water": GPIO_PACKED_RING_DEPTH,
            "packet_ready_depth": PACKET_BUFFER_COUNT,
            "packet_transmit_depth": PACKET_BUFFER_COUNT,
        }
        exceeded = {
            name: {"observed": status.values[name], "limit": limit}
            for name, limit in queue_limits.items()
            if status.values[name] > limit
        }
        if exceeded:
            raise FirmwareFailure(
                "firmware queue exceeds its fixed capacity: "
                + json.dumps(exceeded, sort_keys=True, separators=(",", ":"))
            )
        self.latencies.append(latency)
        self.samples += 1
        for name in CURRENT_QUEUE_FIELDS:
            self.maximum_current_depths[name] = max(
                self.maximum_current_depths.get(name, 0), status.values[name]
            )
        for name in HIGH_WATER_FIELDS:
            self.maximum_high_waters[name] = max(
                self.maximum_high_waters.get(name, 0), status.values[name]
            )
        for name in SERVICE_COUNTER_FIELDS:
            self.service_counters[name] = max(
                self.service_counters.get(name, 0), status.values[name]
            )
        self.rss_maximum_bytes = max(
            self.rss_maximum_bytes, current_rss_bytes(), maximum_rss_bytes()
        )

    def summary(self) -> dict[str, object]:
        self.rss_end_bytes = current_rss_bytes()
        self.rss_maximum_bytes = max(
            self.rss_maximum_bytes, self.rss_end_bytes, maximum_rss_bytes()
        )
        return {
            "status_samples": self.samples,
            "status_latency_seconds": {
                "minimum": min(self.latencies) if self.latencies else None,
                "median": statistics.median(self.latencies) if self.latencies else None,
                "p95": percentile(self.latencies, 0.95),
                "p99": percentile(self.latencies, 0.99),
                "maximum": max(self.latencies) if self.latencies else None,
            },
            "maximum_current_queue_depths": self.maximum_current_depths,
            "firmware_queue_high_waters": self.maximum_high_waters,
            "service_counters": self.service_counters,
            "memory": {
                "rss_start_bytes": self.rss_start_bytes,
                "rss_end_bytes": self.rss_end_bytes,
                "rss_growth_bytes": self.rss_end_bytes - self.rss_start_bytes,
                "rss_maximum_bytes": self.rss_maximum_bytes,
            },
        }


def validate_status_health(
    status: StatusSnapshot, *, allow_bounded_physical_stop_tail: bool = False
) -> None:
    nonzero = {
        name: status.values[name]
        for name in ZERO_COUNTER_FIELDS
        if status.values[name]
        and (
            not allow_bounded_physical_stop_tail
            or name not in BOUNDED_PHYSICAL_STOP_TAIL_FIELDS
        )
    }
    if nonzero:
        raise FirmwareFailure(
            "STATUS reports loss or error counters: "
            + json.dumps(nonzero, sort_keys=True, separators=(",", ":"))
        )
    if allow_bounded_physical_stop_tail:
        adc_tail = status.adc_stop_pairs_discarded
        gpio_tail = status.gpio_raw_samples_lost
        if not (
            0 <= adc_tail < 2 * ADC_PAIRS_PER_FRAME
            and status.adc_raw_pairs_lost == adc_tail
            and status.adc_items_dropped == adc_tail
            and 0 <= status.adc_incomplete_buffers <= 2
            and 0 <= status.adc_completion_mismatches <= status.adc_incomplete_buffers
            and 0 <= status.adc_incomplete_conversions <= adc_tail
            and (adc_tail == 0) == (status.adc_incomplete_buffers == 0)
            and 0 <= gpio_tail < GPIO_SAMPLES_PER_FRAME
            and status.gpio_items_dropped == gpio_tail
        ):
            raise FirmwareFailure("physical STOP-tail accounting is inconsistent")


@dataclass(frozen=True)
class DeviceIdentity:
    protocol_version: int
    hardware_serial: int
    firmware_version: str
    board_id: int
    mcu_id: int
    build_id: str
    supported_stream_mask: int
    supported_source_mask: int
    supported_checksum_mask: int
    capability_bits: int
    dwt_clock_hz: int
    max_control_frame_bytes: int

    def summary(self) -> dict[str, object]:
        return self.__dict__.copy()


def response_success(frame: Frame, expected_kind: int, version: int) -> None:
    if frame.kind != expected_kind or frame.version != version or frame.flags:
        status, _reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        raise FirmwareFailure(
            f"response kind=0x{frame.kind:02x} version={frame.version} "
            f"flags=0x{frame.flags:04x} status={status} error={error}"
        )
    status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    if status or reserved or error:
        raise CodecFailure("successful response prefix is invalid")


def parse_info(frame: Frame) -> DeviceIdentity:
    response_success(frame, INFO_RESPONSE, frame.version)
    payload = frame.payload
    protocol_version = payload[5]
    if protocol_version != frame.version:
        raise FixtureFailure("INFO payload/header versions disagree")
    source_mask = payload[7]
    checksum_mask = struct.unpack_from("<I", payload, 8)[0]
    capability_bits = struct.unpack_from("<I", payload, 12)[0]
    maximum = struct.unpack_from("<I", payload, 24)[0]
    if frame.version == PROTOCOL_V1:
        if (
            source_mask != V1_SOURCE_MASK
            or capability_bits != KNOWN_V1_CAPABILITY_MASK
            or maximum != MAX_V1_CONTROL_FRAME_BYTES
        ):
            raise FirmwareFailure("protocol-v1 INFO leaked a v2 extension")
    elif (
        source_mask != V2_SOURCE_MASK
        or capability_bits != KNOWN_V2_CAPABILITY_MASK
        or maximum != MAX_V2_CONTROL_FRAME_BYTES
    ):
        raise FixtureFailure("firmware lacks the requested v2 experiment capability")
    if not checksum_mask & (1 << payload[45]):
        raise FirmwareFailure("INFO selected checksum is not advertised")
    build_bytes = payload[66:98]
    try:
        terminator = build_bytes.index(0)
        build_id = build_bytes[:terminator].decode("ascii")
    except (ValueError, UnicodeDecodeError) as error:
        raise CodecFailure("INFO build ID is not NUL-terminated ASCII") from error
    if any(build_bytes[terminator + 1 :]):
        raise CodecFailure("INFO build ID padding is nonzero")
    return DeviceIdentity(
        protocol_version=protocol_version,
        hardware_serial=struct.unpack_from("<I", payload, 54)[0],
        firmware_version=f"{payload[58]}.{payload[59]}.{payload[60]}",
        board_id=struct.unpack_from("<H", payload, 62)[0],
        mcu_id=struct.unpack_from("<H", payload, 64)[0],
        build_id=build_id,
        supported_stream_mask=payload[6],
        supported_source_mask=source_mask,
        supported_checksum_mask=checksum_mask,
        capability_bits=capability_bits,
        dwt_clock_hz=struct.unpack_from("<I", payload, 192)[0],
        max_control_frame_bytes=maximum,
    )


class SerialLink:
    """One-command-at-a-time link that services data while awaiting control."""

    def __init__(self, port: SerialPort) -> None:
        self.port = port
        self.parser = FrameParser()
        self.next_request_id = 1
        self.stale_responses = 0
        self.discarded_data_frames = 0
        self.maximum_read_bytes = 0
        self.command_latencies: list[float] = []

    def reader_metrics(self) -> dict[str, int | float | bool]:
        if isinstance(self.port, BufferedSerialPort):
            return self.port.metrics()
        return {
            "enabled": False,
            "capacity_bytes": 0,
            "capacity_chunks": 0,
            "final_bytes": 0,
            "final_chunks": 0,
            "high_water_bytes": 0,
            "high_water_chunks": 0,
            "maximum_read_call_seconds": 0.0,
            "maximum_successful_read_gap_seconds": 0.0,
            "read_calls": 0,
        }

    def drain_startup(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            chunk = self._read_bytes()
            if chunk:
                self.discarded_data_frames += len(self.parser.feed(chunk))
        self.parser.strict = True

    def exchange(
        self,
        version: int,
        request_kind: int,
        payload: bytes = b"",
        *,
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[Frame, float]:
        request_id = self._allocate_request_id()
        wire = encode_control(version, request_kind, request_id, payload)
        started = time.monotonic()
        deadline = started + timeout
        self._write_all(wire, deadline)
        expected_kind = REQUEST_RESPONSE_KIND[request_kind]
        while True:
            if time.monotonic() >= deadline:
                raise ServiceFailure(
                    f"request {request_id} kind 0x{request_kind:02x} timed out"
                )
            matched: Frame | None = None
            for frame in self._read_frames():
                if frame.kind in DATA_KINDS:
                    if on_data is None:
                        self.discarded_data_frames += 1
                    else:
                        on_data(frame)
                    continue
                if frame.request_id != request_id:
                    self.stale_responses += 1
                    continue
                if frame.version != version or frame.kind != expected_kind:
                    raise CodecFailure(
                        f"request {request_id} expected v{version} "
                        f"kind 0x{expected_kind:02x}, received v{frame.version} "
                        f"kind 0x{frame.kind:02x}"
                    )
                if matched is not None:
                    raise CodecFailure("one request received duplicate responses")
                matched = frame
            if matched is not None:
                latency = time.monotonic() - started
                self.command_latencies.append(latency)
                return matched, latency

    def pump_once(self, on_data: Callable[[Frame], None]) -> int:
        chunk = self._read_bytes()
        frames = self.parser.feed(chunk) if chunk else []
        for frame in frames:
            if frame.kind not in DATA_KINDS:
                raise CodecFailure(
                    f"unsolicited response 0x{frame.kind:02x} for {frame.request_id}"
                )
            on_data(frame)
        return len(chunk)

    def drain_until_quiet(self, on_data: Callable[[Frame], None]) -> None:
        hard_deadline = time.monotonic() + STOP_DRAIN_DEADLINE_SECONDS
        quiet_since = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= hard_deadline:
                raise ServiceFailure("post-STOP data did not drain before deadline")
            if now - quiet_since >= STOP_DRAIN_QUIET_SECONDS:
                if self.parser.buffer:
                    raise CodecFailure("post-STOP parser retains a partial frame")
                return
            received = self.pump_once(on_data)
            if received:
                quiet_since = time.monotonic()

    def _allocate_request_id(self) -> int:
        request_id = self.next_request_id
        self.next_request_id = (self.next_request_id + 1) & 0xFFFFFFFF
        if self.next_request_id == 0:
            self.next_request_id = 1
        return request_id

    def _write_all(self, wire: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(wire):
            if time.monotonic() >= deadline:
                raise ServiceFailure(
                    f"serial write stopped after {offset}/{len(wire)} bytes"
                )
            try:
                written = self.port.write(wire[offset:])
            except Exception as error:
                raise ServiceFailure(f"serial write failed: {error}") from error
            if written is None:
                written = 0
            if not isinstance(written, int) or not 0 <= written <= len(wire) - offset:
                raise ServiceFailure(f"serial write returned invalid count {written!r}")
            offset += written
            if written == 0:
                time.sleep(0.0001)

    def _read_bytes(self) -> bytes:
        try:
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        except Exception as error:
            raise ServiceFailure(f"serial read failed: {error}") from error
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        if len(chunk) > SERIAL_READ_BYTES:
            raise ServiceFailure("serial read exceeded the requested finite bound")
        return chunk

    def _read_frames(self) -> list[Frame]:
        chunk = self._read_bytes()
        return self.parser.feed(chunk) if chunk else []


def validate_applied_configuration(
    frame: Frame,
    expected_source: int,
    expected_checksum: int,
    expected_encoding: int,
) -> None:
    response_success(frame, frame.kind, PROTOCOL_V2)
    observed = CONFIGURATION.unpack_from(frame.payload, 4)
    expected = (
        STREAM_BOTH,
        expected_source,
        expected_checksum,
        expected_encoding,
        DATA_FRAME_BYTES,
    )
    if observed != expected:
        raise FirmwareFailure(
            f"applied configuration {observed!r} != requested {expected!r}"
        )


def _require_equal(status: StatusSnapshot, expected: dict[str, int]) -> None:
    mismatches = {
        name: {"expected": value, "observed": status.values[name]}
        for name, value in expected.items()
        if status.values[name] != value
    }
    if mismatches:
        raise FirmwareFailure(
            "final STATUS conservation mismatch: "
            + json.dumps(mismatches, sort_keys=True, separators=(",", ":"))
        )


def _validate_physical_acquisition_accounting(
    status: StatusSnapshot, capture: CaptureValidator
) -> dict[str, int]:
    """Reconcile complete hardware frames plus bounded partial STOP tails."""

    adc = capture.streams[ADC_DATA]
    gpio = capture.streams[GPIO_DATA]
    adc_tail = status.adc_stop_pairs_discarded
    gpio_tail = status.gpio_raw_samples_lost
    _require_equal(
        status,
        {
            "adc0_dma_major_loops": adc.frames,
            "adc1_dma_major_loops": adc.frames,
            "adc0_dma_results": adc.logical_items,
            "adc1_dma_results": adc.logical_items,
            "adc_paired_major_loops": adc.frames,
            "adc_buffers_completed": adc.frames,
            "adc_buffers_acquired": adc.frames,
            "adc_buffers_released": adc.frames,
            "adc_pairs_captured": adc.logical_items + adc_tail,
            "adc_pairs_delivered": adc.logical_items,
            "adc_frames_consumed": adc.frames,
            "adc_pairs_consumed": adc.logical_items,
            "gpio_samples_captured": gpio.logical_items + gpio_tail,
            "gpio_samples_packed": gpio.logical_items,
            "gpio_dma_major_loops": gpio.frames,
            "gpio_buffers_completed": gpio.frames,
            "gpio_buffers_acquired": gpio.frames,
            "gpio_buffers_released": gpio.frames,
            "gpio_samples_delivered": gpio.logical_items,
            "gpio_stop_samples_discarded": gpio_tail,
            "gpio_frames_produced": gpio.frames,
            "gpio_samples_produced": gpio.logical_items,
            "gpio_frames_packed": gpio.frames,
        },
    )
    return {"adc_pairs": adc_tail, "gpio_samples": gpio_tail}


def validate_final_accounting(
    status: StatusSnapshot,
    capture: CaptureValidator,
    requested_encoding: int,
    observed_seconds: float,
    dwt_clock_hz: int = CPU_DWT_HZ,
) -> dict[str, object]:
    """Require quiescent lossless host/firmware byte and item conservation."""

    if dwt_clock_hz <= 0:
        raise FirmwareFailure("INFO reported a non-positive DWT clock")
    is_physical = capture.pattern == "physical"
    validate_status_health(status, allow_bounded_physical_stop_tail=is_physical)
    if (
        status.device_state != STATE_IDLE
        or status.stream_mask != STREAM_NONE
        or status.source != SOURCE_HARDWARE
        or status.configuration_encoding != CONFIGURATION_ENCODING_RAW
        or status.stats_generation == 0
    ):
        raise FirmwareFailure("final STATUS is not an IDLE/default configuration")
    nonzero_queues = {
        name: status.values[name]
        for name in CURRENT_QUEUE_FIELDS
        if status.values[name]
    }
    for name in (
        "usb_active_frame_bytes_sent",
        "usb_active_frame_size",
        "adc_encoded_payload_bytes_queued",
        "adc_encoded_wire_bytes_queued",
        "gpio_encoded_payload_bytes_queued",
        "gpio_encoded_wire_bytes_queued",
    ):
        if status.values[name]:
            nonzero_queues[name] = status.values[name]
    if nonzero_queues:
        raise FirmwareFailure(
            "final STATUS retains ownership: "
            + json.dumps(nonzero_queues, sort_keys=True, separators=(",", ":"))
        )
    if status.temporary_page_high_water > 1:
        raise FirmwareFailure("temporary RLE page high water exceeds one")

    physical_stop_tail = (
        _validate_physical_acquisition_accounting(status, capture)
        if is_physical
        else None
    )

    combined_logical = 0
    combined_framed = 0
    combined_frames = 0
    combined_fallbacks = 0
    stream_result: dict[str, object] = {}
    for kind, metrics in capture.streams.items():
        prefix = metrics.name
        logical_bytes = metrics.frames * DATA_PAYLOAD_BYTES
        combined_logical += logical_bytes
        combined_framed += metrics.framed_bytes
        combined_frames += metrics.frames
        frame_emitted_field = f"{prefix}_frames_emitted"
        legacy_items_framed = (
            "adc_pairs_framed" if kind == ADC_DATA else "gpio_samples_framed"
        )
        legacy_items_transmitted = (
            "adc_pairs_transmitted" if kind == ADC_DATA else "gpio_samples_transmitted"
        )
        expected = {
            f"{prefix}_frames_generated": metrics.frames,
            f"{prefix}_frames_framed_pipeline": metrics.frames,
            frame_emitted_field: metrics.frames,
            f"{prefix}_frames_transmitted": metrics.frames,
            f"{prefix}_items_generated": metrics.logical_items,
            f"{prefix}_items_framed_pipeline": metrics.logical_items,
            f"{prefix}_items_emitted": metrics.logical_items,
            f"{prefix}_items_transmitted_pipeline": metrics.logical_items,
            legacy_items_framed: metrics.logical_items,
            legacy_items_transmitted: metrics.logical_items,
            f"{prefix}_payload_bytes_produced": logical_bytes,
            f"{prefix}_payload_bytes_framed": logical_bytes,
            f"{prefix}_payload_bytes_emitted": logical_bytes,
            f"{prefix}_payload_bytes_transmitted": logical_bytes,
            f"{prefix}_framed_bytes_framed": metrics.framed_bytes,
            f"{prefix}_framed_bytes_emitted": metrics.framed_bytes,
            f"{prefix}_framed_bytes_transmitted": metrics.framed_bytes,
            f"{prefix}_encoded_payload_bytes_framed": (metrics.encoded_payload_bytes),
            f"{prefix}_encoded_payload_bytes_transmitted": (
                metrics.encoded_payload_bytes
            ),
            f"{prefix}_raw_frames": metrics.raw_frames,
            f"{prefix}_rle_frames": metrics.rle_frames,
            f"{prefix}_rle_runs": metrics.rle_runs,
        }
        _require_equal(status, expected)
        fallback = status.values[f"{prefix}_fallback_frames"]
        fallback_reasons = (
            status.values[f"{prefix}_fallback_not_smaller"]
            + status.values[f"{prefix}_fallback_temporary_page_unavailable"]
            + status.values[f"{prefix}_fallback_encoder_failure"]
        )
        if fallback != fallback_reasons:
            raise FirmwareFailure(f"{prefix} fallback reasons do not partition")
        if requested_encoding == CONFIGURATION_ENCODING_RLE_AUTO:
            if fallback != metrics.raw_frames:
                raise FirmwareFailure(
                    f"{prefix} RAW frames do not equal adaptive fallbacks"
                )
        elif fallback or metrics.rle_frames or status.values[f"{prefix}_encode_cycles"]:
            raise FirmwareFailure(f"{prefix} RAW mode performed RLE work")
        combined_fallbacks += fallback
        stream_result[prefix] = {
            "encode_cycles": status.values[f"{prefix}_encode_cycles"],
            "fallback_frames": fallback,
            "fallback_reasons": {
                "not_smaller": status.values[f"{prefix}_fallback_not_smaller"],
                "temporary_page_unavailable": status.values[
                    f"{prefix}_fallback_temporary_page_unavailable"
                ],
                "encoder_failure": status.values[f"{prefix}_fallback_encoder_failure"],
            },
        }

    _require_equal(
        status,
        {
            "packet_frames_promoted": combined_frames,
            "data_payload_bytes_transmitted": combined_logical,
            "data_framed_bytes_transmitted": combined_framed,
        },
    )
    if status.packet_accounted_frame_skew > 1:
        raise FirmwareFailure("final fair-scheduler skew exceeds one frame")
    total_cycles = status.adc_encode_cycles + status.gpio_encode_cycles
    conservation_ranges = (
        (12, 120),
        (368, 516),
        (576, 912),
        (1024, 1228),
        (1244, 1480),
    )
    return {
        "streams": stream_result,
        "combined_fallback_frames": combined_fallbacks,
        "combined_encode_cycles": total_cycles,
        "encode_cycles_per_logical_byte": (
            total_cycles / combined_logical if combined_logical else None
        ),
        "encode_cpu_load_fraction": (
            total_cycles / (observed_seconds * dwt_clock_hz)
            if observed_seconds > 0
            else None
        ),
        "queue_high_waters": {name: status.values[name] for name in HIGH_WATER_FIELDS},
        "loss_error_counters": {
            name: status.values[name] for name in ZERO_COUNTER_FIELDS
        },
        "conservation_counters": {
            name: status.values[name]
            for name, (_fmt, offset) in STATUS_FIELDS.items()
            if any(start <= offset < end for start, end in conservation_ranges)
        },
        "service_counters": {
            name: status.values[name] for name in SERVICE_COUNTER_FIELDS
        },
        "stats_generation": status.stats_generation,
        "physical_stop_tail": physical_stop_tail,
    }


@dataclass(frozen=True)
class RigConfiguration:
    port: str
    mode: str
    capture_seconds: float
    warmup_seconds: float
    status_interval_seconds: float
    pattern: str
    source: int
    encoding: int
    checksum: int
    expected_build_id: str | None
    expected_hardware_serial: int | None
    artifact_sha256: str | None
    source_id: str | None
    job_id: str | None


@dataclass
class Execution:
    identity_v1: DeviceIdentity | None = None
    identity_v2: DeviceIdentity | None = None
    capture: CaptureValidator | None = None
    status_observer: StatusObserver | None = None
    observed_seconds: float = 0.0
    steady_capture_seconds: float = 0.0
    final_status: StatusSnapshot | None = None
    firmware_summary: dict[str, object] = field(default_factory=dict)
    cleanup: dict[str, object] = field(
        default_factory=lambda: {
            "stop_attempted": False,
            "stop_succeeded": False,
            "idle_status_attempted": False,
            "idle_confirmed": False,
            "errors": [],
        }
    )


def emit_event(event: str, **values: object) -> None:
    payload = {"event": event, "monotonic_seconds": time.monotonic(), **values}
    print(RLE_EVENT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))


def emit_result(payload: dict[str, object]) -> None:
    print(
        RLE_RESULT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def _positive_float_environment(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


def _nonnegative_float_environment(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be nonnegative and finite")
    return value


def _optional_text_environment(name: str, maximum: int = 128) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    if (
        not raw
        or len(raw) > maximum
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw)
    ):
        raise ValueError(f"{name} must be bounded printable text")
    return raw


def _optional_uint32_environment(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        value = int(raw, 0)
    except ValueError as error:
        raise ValueError(f"{name} must be a uint32") from error
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be a uint32")
    return value


def _optional_sha256_environment(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    normalized = raw.lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        raise ValueError(f"{name} must be exactly 64 hexadecimal characters")
    return normalized


def parse_configuration() -> RigConfiguration:
    port = os.environ.get("SERIAL_PORT")
    if not port:
        raise ValueError("SERIAL_PORT is required")
    mode = os.environ.get("RLE_STREAMING_MODE", MODE_SMOKE).strip().lower()
    if mode not in SUPPORTED_MODES:
        raise ValueError("RLE_STREAMING_MODE must be exactly smoke or endurance")
    default_capture = (
        DEFAULT_SMOKE_CAPTURE_SECONDS
        if mode == MODE_SMOKE
        else DEFAULT_ENDURANCE_CAPTURE_SECONDS
    )
    default_warmup = (
        DEFAULT_SMOKE_WARMUP_SECONDS
        if mode == MODE_SMOKE
        else DEFAULT_ENDURANCE_WARMUP_SECONDS
    )
    capture_seconds = _positive_float_environment(
        "RLE_CAPTURE_SECONDS", default_capture
    )
    warmup_seconds = _nonnegative_float_environment(
        "RLE_WARMUP_SECONDS", default_warmup
    )
    status_interval = _positive_float_environment(
        "RLE_STATUS_INTERVAL_SECONDS", DEFAULT_STATUS_INTERVAL_SECONDS
    )
    if mode == MODE_SMOKE and capture_seconds > MAX_SMOKE_CAPTURE_SECONDS:
        raise ValueError(
            f"smoke capture must be <= {MAX_SMOKE_CAPTURE_SECONDS} seconds"
        )
    if mode == MODE_ENDURANCE and capture_seconds < MIN_ENDURANCE_CAPTURE_SECONDS:
        raise ValueError("endurance capture must contain at least 600 seconds")
    if capture_seconds > MAX_CAPTURE_SECONDS:
        raise ValueError(f"capture must be <= {MAX_CAPTURE_SECONDS} seconds")
    if warmup_seconds > MAX_WARMUP_SECONDS:
        raise ValueError(f"warm-up must be <= {MAX_WARMUP_SECONDS} seconds")
    if (
        not MIN_STATUS_INTERVAL_SECONDS
        <= status_interval
        <= MAX_STATUS_INTERVAL_SECONDS
    ):
        raise ValueError(
            f"status interval must be {MIN_STATUS_INTERVAL_SECONDS}.."
            f"{MAX_STATUS_INTERVAL_SECONDS} seconds"
        )
    pattern = (
        os.environ.get("RLE_PATTERN", "constant").strip().lower().replace("_", "-")
    )
    if pattern not in PATTERN_SOURCE:
        raise ValueError(
            "RLE_PATTERN must be physical, constant, sparse-hold, slow-adc, "
            "alternating, or incompressible"
        )
    encoding_name = os.environ.get("RLE_ENCODING", "RLE_AUTO").strip().upper()
    encoding_by_name = {
        "RAW": CONFIGURATION_ENCODING_RAW,
        "RLE_AUTO": CONFIGURATION_ENCODING_RLE_AUTO,
    }
    if encoding_name not in encoding_by_name:
        raise ValueError("RLE_ENCODING must be exactly RAW or RLE_AUTO")
    checksum_name = os.environ.get("RLE_CHECKSUM_ALGORITHM", "ADLER32").strip().upper()
    checksum_by_name = {name: value for value, name in CHECKSUM_NAMES.items()}
    if checksum_name not in checksum_by_name:
        raise ValueError(
            "RLE_CHECKSUM_ALGORITHM must be ADLER32, CRC32C, or CRC32_ISO_HDLC"
        )
    return RigConfiguration(
        port=port,
        mode=mode,
        capture_seconds=capture_seconds,
        warmup_seconds=warmup_seconds,
        status_interval_seconds=status_interval,
        pattern=pattern,
        source=PATTERN_SOURCE[pattern],
        encoding=encoding_by_name[encoding_name],
        checksum=checksum_by_name[checksum_name],
        expected_build_id=_optional_text_environment("EXPECTED_BUILD_ID", 31),
        expected_hardware_serial=_optional_uint32_environment(
            "EXPECTED_HARDWARE_SERIAL"
        ),
        artifact_sha256=_optional_sha256_environment("FIRMWARE_ARTIFACT_SHA256"),
        source_id=_optional_text_environment("EXPECTED_SOURCE_ID"),
        job_id=_optional_text_environment("RIG_JOB_ID"),
    )


def _identity_key(identity: DeviceIdentity) -> tuple[object, ...]:
    return (
        identity.hardware_serial,
        identity.firmware_version,
        identity.board_id,
        identity.mcu_id,
        identity.build_id,
        identity.dwt_clock_hz,
    )


def execute_capture(
    link: SerialLink, configuration: RigConfiguration, execution: Execution
) -> None:
    """Normalize IDLE, prove v1 isolation/v2 capability, then capture."""

    initial_stop, _latency = link.exchange(PROTOCOL_V2, STOP_REQUEST)
    response_success(initial_stop, STOP_RESPONSE, PROTOCOL_V2)
    if initial_stop.payload[4] != STATE_IDLE:
        raise FirmwareFailure("initial STOP did not return IDLE")
    link.drain_until_quiet(lambda _frame: None)

    v1_info_frame, _latency = link.exchange(PROTOCOL_V1, INFO_REQUEST)
    execution.identity_v1 = parse_info(v1_info_frame)
    v2_info_frame, _latency = link.exchange(PROTOCOL_V2, INFO_REQUEST)
    execution.identity_v2 = parse_info(v2_info_frame)
    if _identity_key(execution.identity_v1) != _identity_key(execution.identity_v2):
        raise FixtureFailure("v1/v2 INFO responses identify different firmware")
    identity = execution.identity_v2
    if not 1 <= identity.hardware_serial <= 0xFFFFFFFF:
        raise FixtureFailure("firmware does not advertise a nonzero uint32 serial")
    if identity.supported_stream_mask != STREAM_BOTH:
        raise FixtureFailure("firmware does not advertise both logical streams")
    if not identity.supported_checksum_mask & (1 << configuration.checksum):
        raise FixtureFailure("firmware does not advertise the requested checksum")
    if identity.dwt_clock_hz <= 0:
        raise FixtureFailure("firmware does not report a usable DWT clock")
    if (
        configuration.expected_build_id is not None
        and identity.build_id != configuration.expected_build_id
    ):
        raise FixtureFailure(
            f"build ID {identity.build_id!r} != "
            f"EXPECTED_BUILD_ID {configuration.expected_build_id!r}"
        )
    if (
        configuration.expected_hardware_serial is not None
        and identity.hardware_serial != configuration.expected_hardware_serial
    ):
        raise FixtureFailure(
            f"hardware serial {identity.hardware_serial} != "
            f"EXPECTED_HARDWARE_SERIAL {configuration.expected_hardware_serial}"
        )
    emit_event(
        "identity_verified",
        build_id=identity.build_id,
        capability_bits=identity.capability_bits,
        hardware_serial=identity.hardware_serial,
        protocol_versions=[PROTOCOL_V1, PROTOCOL_V2],
        supported_source_mask=identity.supported_source_mask,
    )

    reset, _latency = link.exchange(PROTOCOL_V2, RESET_STATS_REQUEST)
    response_success(reset, RESET_STATS_RESPONSE, PROTOCOL_V2)
    if struct.unpack_from("<I", reset.payload, 4)[0] == 0:
        raise FirmwareFailure("RESET_STATS returned generation zero")

    configure_payload = CONFIGURATION.pack(
        STREAM_BOTH,
        configuration.source,
        configuration.checksum,
        configuration.encoding,
        DATA_FRAME_BYTES,
    )
    configured, _latency = link.exchange(
        PROTOCOL_V2, CONFIGURE_REQUEST, configure_payload
    )
    response_success(configured, CONFIGURE_RESPONSE, PROTOCOL_V2)
    validate_applied_configuration(
        configured,
        configuration.source,
        configuration.checksum,
        configuration.encoding,
    )

    capture = CaptureValidator(configuration.pattern, configuration.encoding)
    if configuration.pattern != "physical":
        # The parser invokes this only after the complete wire checksum passes.
        # Fusing canonical/bounded and target-formula checks keeps record-dense
        # real-time patterns ahead of the advertised 8 MB/s logical cadence.
        link.parser.rle_validator = capture.validate_rle_payload
    observer = StatusObserver(
        configuration.source, configuration.encoding, configuration.checksum
    )
    execution.capture = capture
    execution.status_observer = observer
    run_started = time.monotonic()
    started, _latency = link.exchange(
        PROTOCOL_V2, START_REQUEST, on_data=capture.observe
    )
    response_success(started, START_RESPONSE, PROTOCOL_V2)
    validate_applied_configuration(
        started,
        configuration.source,
        configuration.checksum,
        configuration.encoding,
    )
    if capture.run_id is not None and capture.run_id != started.run_id:
        raise FirmwareFailure("START response and first data frame run IDs disagree")
    capture.run_id = started.run_id
    steady_started = run_started + configuration.warmup_seconds
    capture_deadline = steady_started + configuration.capture_seconds
    next_status = run_started + configuration.status_interval_seconds
    emit_event(
        "capture_started",
        capture_seconds=configuration.capture_seconds,
        encoding=CONFIGURATION_ENCODING_NAMES[configuration.encoding],
        mode=configuration.mode,
        pattern=configuration.pattern,
        source=configuration.source,
        warmup_seconds=configuration.warmup_seconds,
    )
    while time.monotonic() < capture_deadline:
        now = time.monotonic()
        if now >= next_status:
            status_frame, latency = link.exchange(
                PROTOCOL_V2,
                GET_STATUS_REQUEST,
                on_data=capture.observe,
            )
            response_success(status_frame, GET_STATUS_RESPONSE, PROTOCOL_V2)
            observer.observe(StatusSnapshot.from_frame(status_frame), latency)
            next_status += configuration.status_interval_seconds
            if next_status <= now:
                skipped = math.floor(
                    (now - next_status) / configuration.status_interval_seconds
                )
                next_status += (skipped + 1) * configuration.status_interval_seconds
        else:
            link.pump_once(capture.observe)

    status_frame, latency = link.exchange(
        PROTOCOL_V2,
        GET_STATUS_REQUEST,
        on_data=capture.observe,
    )
    response_success(status_frame, GET_STATUS_RESPONSE, PROTOCOL_V2)
    observer.observe(StatusSnapshot.from_frame(status_frame), latency)
    execution.observed_seconds = time.monotonic() - run_started
    execution.steady_capture_seconds = max(0.0, time.monotonic() - steady_started)
    for metrics in capture.streams.values():
        if metrics.frames == 0:
            raise FirmwareFailure(f"capture received no {metrics.name} frames")
    emit_event(
        "capture_window_complete",
        adc_frames=capture.streams[ADC_DATA].frames,
        gpio_frames=capture.streams[GPIO_DATA].frames,
        observed_seconds=execution.observed_seconds,
    )


def cleanup_to_idle(
    link: SerialLink,
    execution: Execution,
    *,
    preserve_validation: bool,
) -> None:
    """Always attempt STOP, drain, and final IDLE confirmation."""

    report = execution.cleanup
    errors = report["errors"]
    assert isinstance(errors, list)
    callback: Callable[[Frame], None]
    if preserve_validation and execution.capture is not None:
        callback = execution.capture.observe
    else:
        callback = lambda _frame: None
        link.parser.reset_for_cleanup()

    report["stop_attempted"] = True
    try:
        stop, _latency = link.exchange(PROTOCOL_V2, STOP_REQUEST, on_data=callback)
        response_success(stop, STOP_RESPONSE, PROTOCOL_V2)
        report["stop_succeeded"] = stop.payload[4] == STATE_IDLE
        if not report["stop_succeeded"]:
            raise FirmwareFailure("STOP response did not report IDLE")
    except Exception as error:  # noqa: BLE001 - cleanup records every outcome
        errors.append(f"v2 STOP: {type(error).__name__}: {error}")
        link.parser.reset_for_cleanup()

    try:
        link.drain_until_quiet(callback)
    except Exception as error:  # noqa: BLE001 - cleanup remains best effort
        errors.append(f"drain: {type(error).__name__}: {error}")
        link.parser.reset_for_cleanup()

    report["idle_status_attempted"] = True
    try:
        idle_frame, _latency = link.exchange(
            PROTOCOL_V2, GET_STATUS_REQUEST, on_data=callback
        )
        response_success(idle_frame, GET_STATUS_RESPONSE, PROTOCOL_V2)
        execution.final_status = StatusSnapshot.from_frame(idle_frame)
        report["idle_confirmed"] = execution.final_status.device_state == STATE_IDLE
        if not report["idle_confirmed"]:
            raise FirmwareFailure("final v2 STATUS is not IDLE")
    except Exception as error:  # noqa: BLE001 - fallback still attempts v1
        errors.append(f"v2 STATUS: {type(error).__name__}: {error}")
        link.parser.reset_for_cleanup()

    if not report["idle_confirmed"]:
        try:
            fallback_stop, _latency = link.exchange(PROTOCOL_V1, STOP_REQUEST)
            response_success(fallback_stop, STOP_RESPONSE, PROTOCOL_V1)
            report["stop_succeeded"] = fallback_stop.payload[4] == STATE_IDLE
            fallback_status, _latency = link.exchange(PROTOCOL_V1, GET_STATUS_REQUEST)
            response_success(fallback_status, GET_STATUS_RESPONSE, PROTOCOL_V1)
            report["idle_confirmed"] = fallback_status.payload[4] == STATE_IDLE
            if not report["idle_confirmed"]:
                raise FirmwareFailure("fallback v1 STATUS is not IDLE")
        except Exception as error:  # noqa: BLE001 - final cleanup evidence
            errors.append(f"v1 fallback: {type(error).__name__}: {error}")
    emit_event(
        "cleanup_complete",
        idle_confirmed=report["idle_confirmed"],
        stop_succeeded=report["stop_succeeded"],
        errors=errors,
    )


def classify_failure(error: BaseException) -> str:
    if isinstance(error, FixtureFailure):
        return "fixture"
    if isinstance(error, ServiceFailure):
        return "service"
    if isinstance(error, CodecFailure):
        return "codec"
    if isinstance(error, FirmwareFailure):
        return "firmware"
    return "service"


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "minimum": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "maximum": max(values) if values else None,
    }


def result_payload(
    configuration: RigConfiguration | None,
    execution: Execution,
    link: SerialLink | None,
    failure: BaseException | None,
) -> dict[str, object]:
    failure_class = classify_failure(failure) if failure is not None else None
    result = (
        "PASS"
        if failure is None
        else "FAIL"
        if failure_class in {"firmware", "codec"}
        else "INCONCLUSIVE"
    )
    capture = execution.capture
    observer = execution.status_observer
    streams = (
        {metrics.name: metrics.summary() for metrics in capture.streams.values()}
        if capture is not None
        else {}
    )
    combined = capture.combined_summary() if capture is not None else {}
    if capture is not None and execution.observed_seconds > 0:
        logical_payload_bytes = combined["logical_payload_bytes"]
        framed_bytes = combined["framed_bytes"]
        assert logical_payload_bytes is not None
        assert framed_bytes is not None
        combined["wall_logical_bytes_per_second"] = (
            logical_payload_bytes / execution.observed_seconds
        )
        combined["wall_framed_bytes_per_second"] = (
            framed_bytes / execution.observed_seconds
        )
        for stream in streams.values():
            logical_stream_bytes = stream["logical_payload_bytes"]
            framed_stream_bytes = stream["framed_bytes"]
            assert logical_stream_bytes is not None
            assert framed_stream_bytes is not None
            stream["wall_logical_bytes_per_second"] = (
                logical_stream_bytes / execution.observed_seconds
            )
            stream["wall_framed_bytes_per_second"] = (
                framed_stream_bytes / execution.observed_seconds
            )
    host = {
        "streams": streams,
        "combined": combined,
        "status": observer.summary() if observer is not None else {},
        "parser": (
            {
                "bytes_received": link.parser.bytes_received,
                "frames_decoded": link.parser.frames_decoded,
                "header_errors": link.parser.header_errors,
                "checksum_errors": link.parser.checksum_errors,
                "payload_errors": link.parser.payload_errors,
                "bytes_discarded": link.parser.bytes_discarded,
                "buffer_high_water_bytes": link.parser.high_water_bytes,
                "maximum_serial_read_bytes": link.maximum_read_bytes,
                "stale_responses": link.stale_responses,
                "startup_discarded_data_frames": link.discarded_data_frames,
            }
            if link is not None
            else {}
        ),
        "serial_reader": link.reader_metrics() if link is not None else {},
        "command_latency_seconds": (
            _latency_summary(link.command_latencies) if link is not None else {}
        ),
    }
    return {
        "schema_version": RLE_RESULT_SCHEMA_VERSION,
        "kind": "thingdaq-rle-streaming-run",
        "validation_semantics": (
            "physical-rle-streaming-v2"
            if configuration is not None and configuration.pattern == "physical"
            else "synthetic-rle-streaming-v2"
        ),
        "mode": configuration.mode if configuration is not None else None,
        "result": result,
        "reason": (
            f"{type(failure).__name__}: {failure}" if failure is not None else None
        ),
        "failure_class": failure_class,
        "experiment": (
            {
                "pattern": configuration.pattern,
                "source_selector": configuration.source,
                "configuration_encoding": CONFIGURATION_ENCODING_NAMES[
                    configuration.encoding
                ],
                "checksum_algorithm": CHECKSUM_NAMES[configuration.checksum],
                "requested_capture_seconds": configuration.capture_seconds,
                "warmup_seconds": configuration.warmup_seconds,
                "status_interval_seconds": configuration.status_interval_seconds,
            }
            if configuration is not None
            else {}
        ),
        "identity": (
            execution.identity_v2.summary()
            if execution.identity_v2 is not None
            else None
        ),
        "v1_identity": (
            execution.identity_v1.summary()
            if execution.identity_v1 is not None
            else None
        ),
        "declared_identity": (
            {
                "firmware_artifact_sha256": configuration.artifact_sha256,
                "source_id": configuration.source_id,
                "job_id": configuration.job_id,
            }
            if configuration is not None
            else {}
        ),
        "run": {
            "run_id": capture.run_id if capture is not None else None,
            "observed_seconds": execution.observed_seconds,
            "steady_capture_seconds": execution.steady_capture_seconds,
        },
        "host": host,
        "firmware": execution.firmware_summary,
        "cleanup": execution.cleanup,
        "validation": {
            "checksum_before_decompression": True,
            "bounded_decompression": True,
            "bulk_capture_retained": False,
            "incompressible_formula_scope": (
                "full cadence frames plus rotating spots on every frame"
                if configuration is not None and configuration.pattern != "physical"
                else None
            ),
            "control_versions_encoded_independently": [PROTOCOL_V1, PROTOCOL_V2],
        },
    }


def main() -> int:
    execution = Execution()
    try:
        configuration = parse_configuration()
    except ValueError as error:
        payload = result_payload(None, execution, None, error)
        payload["result"] = "NOT_RUN"
        payload["failure_class"] = "configuration"
        payload["reason"] = str(error)
        emit_result(payload)
        return 2

    emit_event(
        "program_start",
        mode=configuration.mode,
        pattern=configuration.pattern,
        protocol_versions=[PROTOCOL_V1, PROTOCOL_V2],
    )
    try:
        port = serial.Serial(
            port=configuration.port,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - explicit service classification
        open_failure = ServiceFailure(
            f"serial open failed: {type(error).__name__}: {error}"
        )
        emit_result(result_payload(configuration, execution, None, open_failure))
        return 2

    buffered_port: BufferedSerialPort | None = None
    cyclic_gc_was_enabled = False
    previous_switch_interval: float | None = None
    link_port: SerialPort = port
    if configuration.mode == MODE_ENDURANCE:
        previous_switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(SERIAL_READER_SWITCH_INTERVAL_SECONDS)
        buffered_port = BufferedSerialPort(port)
        link_port = buffered_port
        cyclic_gc_was_enabled = gc.isenabled()
        if cyclic_gc_was_enabled:
            gc.disable()
        emit_event(
            "serial_reader_started",
            chunk_bytes=SERIAL_READ_BYTES,
            queue_bytes=SERIAL_READER_QUEUE_BYTES,
            queue_chunks=SERIAL_READER_QUEUE_CHUNKS,
            switch_interval_seconds=SERIAL_READER_SWITCH_INTERVAL_SECONDS,
        )

    link = SerialLink(link_port)
    failure: BaseException | None = None
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        execute_capture(link, configuration, execution)
    except Exception as error:  # noqa: BLE001 - classified in result schema
        failure = error
        emit_event(
            "capture_failed",
            error=f"{type(error).__name__}: {error}",
            failure_class=classify_failure(error),
        )
    finally:
        cleanup_to_idle(link, execution, preserve_validation=failure is None)

    cleanup_errors = execution.cleanup["errors"]
    assert isinstance(cleanup_errors, list)
    if failure is None and cleanup_errors:
        failure = ServiceFailure(str(cleanup_errors[0]))
    if failure is None and not execution.cleanup["idle_confirmed"]:
        failure = ServiceFailure("cleanup could not confirm final IDLE")
    if failure is None:
        try:
            if (
                execution.final_status is None
                or execution.capture is None
                or execution.identity_v2 is None
            ):
                raise ServiceFailure("final accounting evidence is incomplete")
            execution.firmware_summary = validate_final_accounting(
                execution.final_status,
                execution.capture,
                configuration.encoding,
                execution.observed_seconds,
                execution.identity_v2.dwt_clock_hz,
            )
        except Exception as error:  # noqa: BLE001 - validation classification
            failure = error

    if buffered_port is not None:
        try:
            buffered_port.close()
            reader_metrics = buffered_port.metrics()
            if failure is None and reader_metrics["final_bytes"] != 0:
                failure = ServiceFailure(
                    "bounded serial reader retained bytes after final IDLE"
                )
        except Exception as error:  # noqa: BLE001 - explicit service boundary
            close_failure = ServiceFailure(f"serial reader close failed: {error}")
            if failure is None:
                failure = close_failure
            cleanup_errors.append(str(close_failure))
        finally:
            if cyclic_gc_was_enabled:
                gc.enable()
            assert previous_switch_interval is not None
            sys.setswitchinterval(previous_switch_interval)

    try:
        port.close()
    except Exception as error:  # noqa: BLE001 - explicit service boundary
        close_failure = ServiceFailure(f"serial close failed: {error}")
        if failure is None:
            failure = close_failure
        cleanup_errors.append(str(close_failure))

    payload = result_payload(configuration, execution, link, failure)
    emit_result(payload)
    if failure is None:
        return 0
    return 1 if classify_failure(failure) in {"firmware", "codec"} else 2


if __name__ == "__main__":
    sys.exit(main())
