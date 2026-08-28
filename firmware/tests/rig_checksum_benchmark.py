#!/usr/bin/env python3
"""Independent Phase 05 checksum benchmark and streaming rig campaign.

The remote rig uploads this file by itself to a network-disabled Python 3.13
container. It intentionally embeds the protocol values it grades, uses only
the Python standard library plus pyserial, and never imports the project API or
generated constants.
"""

from __future__ import annotations

import gc
import json
import math
import os
import re
import struct
import sys
import threading
import time
import zlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import serial

BAUD_RATE = 115_200
SERIAL_READ_TIMEOUT_SECONDS = 0.02
SERIAL_WRITE_TIMEOUT_SECONDS = 0.5
SERIAL_READ_BYTES = 64 * 1024
SERIAL_READER_QUEUE_CHUNKS = 8
SERIAL_READER_QUEUE_BYTES = SERIAL_READ_BYTES * SERIAL_READER_QUEUE_CHUNKS
STARTUP_DRAIN_SECONDS = 0.25
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 0.5
BENCHMARK_DEADLINE_SECONDS = 5.0
STOP_DRAIN_DEADLINE_SECONDS = 2.0
STOP_DRAIN_QUIET_SECONDS = 0.10
DEFAULT_CAPTURE_SECONDS = 10.0
DEFAULT_STATUS_INTERVAL_SECONDS = 0.25
MAX_CAPTURE_SECONDS = 3_600.0
MIN_STATUS_INTERVAL_SECONDS = 0.01
MAX_STATUS_SAMPLES = 16_384
RATE_TOLERANCE_FRACTION = 0.01
STATUS_P99_LIMIT_SECONDS = 0.100
STATUS_MAXIMUM_LIMIT_SECONDS = 0.250

DEFAULT_BENCHMARK_BATCH_COUNT = 4
DEFAULT_BENCHMARK_ITERATIONS_PER_BATCH = 256
MAX_BENCHMARK_BATCH_COUNT = 8
MAX_BENCHMARK_ITERATIONS_PER_BATCH = 4_096
MAX_BENCHMARK_OPERATIONS = 32_768
MAX_BENCHMARK_PROCESSED_BYTES = 8 * 1024 * 1024
BENCHMARK_CYCLE_COUNTER_HZ = 600_000_000
BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND = 8_100_000
BENCHMARK_WORKING_RAM_BYTES = 8_192

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 1
HEADER_SIZE = 44
TRAILER_SIZE = 4
DATA_FRAME_BYTES = 4_096
DATA_PAYLOAD_BYTES = 4_048
MAX_CONTROL_FRAME_BYTES = 1_024
MAX_FRAME_BYTES = DATA_FRAME_BYTES

CHECKSUM_ADLER32 = 1
CHECKSUM_CRC32C = 2
CHECKSUM_CRC32_ISO_HDLC = 3
BOOTSTRAP_CHECKSUM = CHECKSUM_ADLER32
SUPPORTED_CHECKSUMS = frozenset(
    {CHECKSUM_ADLER32, CHECKSUM_CRC32C, CHECKSUM_CRC32_ISO_HDLC}
)
SUPPORTED_CHECKSUM_MASK = sum(1 << value for value in SUPPORTED_CHECKSUMS)
CHECKSUM_NAMES = {
    CHECKSUM_ADLER32: "ADLER32",
    CHECKSUM_CRC32C: "CRC32C",
    CHECKSUM_CRC32_ISO_HDLC: "CRC32_ISO_HDLC",
}

TIMESTAMP_HZ = 8_000_000
ADC_PAIR_RATE_HZ = 1_000_000
ADC_PAIR_PERIOD_TICKS = 8
ADC1_PHASE_TICKS = 4
ADC_RESOLUTION_BITS = 12
ADC_CONTAINER_BYTES = 2
ADC_BYTES_PER_PAIR = 4
ADC_PAIRS_PER_FRAME = 1_012
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4_048
GPIO_PINS_BY_BIT = tuple(range(6, 14))
FRAME_COVERAGE_TICKS = 8_096

TARGET_ADC_PAYLOAD_BYTES_PER_SECOND = ADC_PAIR_RATE_HZ * ADC_BYTES_PER_PAIR
TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND = GPIO_SAMPLE_RATE_HZ
TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND = (
    TARGET_ADC_PAYLOAD_BYTES_PER_SECOND + TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND
)
TARGET_COMBINED_FRAMED_BYTES_PER_SECOND = (
    2 * DATA_FRAME_BYTES * TIMESTAMP_HZ / FRAME_COVERAGE_TICKS
)

ADC_DATA = 0x01
GPIO_DATA = 0x02
INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
PING_REQUEST = 0x16
CHECKSUM_BENCHMARK_REQUEST = 0x17
INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
PING_RESPONSE = 0x96
CHECKSUM_BENCHMARK_RESPONSE = 0x97
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
STREAM_ADC = 1
STREAM_GPIO = 2
STREAM_BOTH = STREAM_ADC | STREAM_GPIO
SOURCE_SYNTHETIC = 1
CAPABILITY_ADC_STREAM = 1
CAPABILITY_GPIO_STREAM = 2
CAPABILITY_SYNTHETIC_SOURCE = 8
CAPABILITY_RESET_STATS = 16
CAPABILITY_PING = 32
CAPABILITY_CHECKSUM_BENCHMARK = 64
EXPECTED_CAPABILITIES = (
    CAPABILITY_ADC_STREAM
    | CAPABILITY_GPIO_STREAM
    | CAPABILITY_SYNTHETIC_SOURCE
    | CAPABILITY_RESET_STATS
    | CAPABILITY_PING
    | CAPABILITY_CHECKSUM_BENCHMARK
)

VECTOR_EMPTY = 0
VECTOR_CANONICAL_123456789 = 1
VECTOR_BUFFER_64 = 2
VECTOR_BUFFER_512 = 3
VECTOR_FRAME_COVERAGE = 4
BENCHMARK_VECTORS = (
    VECTOR_EMPTY,
    VECTOR_CANONICAL_123456789,
    VECTOR_BUFFER_64,
    VECTOR_BUFFER_512,
    VECTOR_FRAME_COVERAGE,
)
VECTOR_NAMES = {
    VECTOR_EMPTY: "EMPTY",
    VECTOR_CANONICAL_123456789: "CANONICAL_123456789",
    VECTOR_BUFFER_64: "BUFFER_64",
    VECTOR_BUFFER_512: "BUFFER_512",
    VECTOR_FRAME_COVERAGE: "FRAME_COVERAGE",
}
VECTOR_BYTES = {
    VECTOR_EMPTY: 0,
    VECTOR_CANONICAL_123456789: 9,
    VECTOR_BUFFER_64: 64,
    VECTOR_BUFFER_512: 512,
    VECTOR_FRAME_COVERAGE: DATA_FRAME_BYTES - TRAILER_SIZE,
}
MEMORY_DTCM_PACKET = 0
MEMORY_OCRAM_DMA = 1
MEMORY_NAMES = {
    MEMORY_DTCM_PACKET: "DTCM_PACKET",
    MEMORY_OCRAM_DMA: "OCRAM_DMA",
}
CACHE_HOT_OR_NATIVE = 0
CACHE_COLD_INVALIDATED = 1
CACHE_NAMES = {
    CACHE_HOT_OR_NATIVE: "HOT_OR_NATIVE",
    CACHE_COLD_INVALIDATED: "COLD_INVALIDATED",
}

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
TRAILER = struct.Struct("<I")
CONFIGURATION = struct.Struct("<BBBBI")
RESPONSE_PREFIX = struct.Struct("<BBH")
BENCHMARK_REQUEST = struct.Struct("<BBBBHH")

REQUEST_RESPONSE_KIND = {
    INFO_REQUEST: INFO_RESPONSE,
    CONFIGURE_REQUEST: CONFIGURE_RESPONSE,
    START_REQUEST: START_RESPONSE,
    GET_STATUS_REQUEST: GET_STATUS_RESPONSE,
    STOP_REQUEST: STOP_RESPONSE,
    RESET_STATS_REQUEST: RESET_STATS_RESPONSE,
    PING_REQUEST: PING_RESPONSE,
    CHECKSUM_BENCHMARK_REQUEST: CHECKSUM_BENCHMARK_RESPONSE,
}
REQUEST_PAYLOAD_SIZE = {
    INFO_REQUEST: 0,
    CONFIGURE_REQUEST: 8,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
    PING_REQUEST: 8,
    CHECKSUM_BENCHMARK_REQUEST: 8,
}
SUCCESS_PAYLOAD_SIZE = {
    INFO_RESPONSE: 98,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 56,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    PING_RESPONSE: 12,
    CHECKSUM_BENCHMARK_RESPONSE: 96,
    ERROR_RESPONSE: 8,
}
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE)

# These values were independently calculated from the documented wire variants
# and the exact benchmark vector construction. They are not generated from the
# package or firmware implementation under test.
EXPECTED_VECTOR_CHECKSUMS = {
    CHECKSUM_ADLER32: {
        VECTOR_EMPTY: 0x00000001,
        VECTOR_CANONICAL_123456789: 0x091E01DE,
        VECTOR_BUFFER_64: 0xF7ED2021,
        VECTOR_BUFFER_512: 0xC4E2FF01,
        VECTOR_FRAME_COVERAGE: 0x4F2DE54E,
    },
    CHECKSUM_CRC32C: {
        VECTOR_EMPTY: 0x00000000,
        VECTOR_CANONICAL_123456789: 0xE3069283,
        VECTOR_BUFFER_64: 0x3D0F7D5D,
        VECTOR_BUFFER_512: 0x724B2C2F,
        VECTOR_FRAME_COVERAGE: 0xBFC9BB50,
    },
    CHECKSUM_CRC32_ISO_HDLC: {
        VECTOR_EMPTY: 0x00000000,
        VECTOR_CANONICAL_123456789: 0xCBF43926,
        VECTOR_BUFFER_64: 0xFFBAE609,
        VECTOR_BUFFER_512: 0xFF1346DB,
        VECTOR_FRAME_COVERAGE: 0xBEA7D1ED,
    },
}


class ProtocolFailure(RuntimeError):
    """The rig observed an invalid or unexpected wire event."""


class DeadlineExpired(ProtocolFailure):
    """A finite serial operation did not complete by its deadline."""


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


def _reference_adler32(data: bytes) -> int:
    sum_1 = 1
    sum_2 = 0
    offset = 0
    while offset < len(data):
        end = min(offset + 5_552, len(data))
        for value in data[offset:end]:
            sum_1 += value
            sum_2 += sum_1
        sum_1 %= 65_521
        sum_2 %= 65_521
        offset = end
    return (sum_2 << 16) | sum_1


def _reference_reflected_crc32(data: bytes, polynomial: int) -> int:
    remainder = 0xFFFFFFFF
    for value in data:
        remainder ^= value
        for _ in range(8):
            remainder = (remainder >> 1) ^ (polynomial if remainder & 1 else 0)
    return remainder ^ 0xFFFFFFFF


def reference_checksum(data: bytes, algorithm: int) -> int:
    """Compute vectors through an intentionally slow bitwise reference."""

    if algorithm == CHECKSUM_ADLER32:
        return _reference_adler32(data)
    if algorithm == CHECKSUM_CRC32C:
        return _reference_reflected_crc32(data, 0x82F63B78)
    if algorithm == CHECKSUM_CRC32_ISO_HDLC:
        return _reference_reflected_crc32(data, 0xEDB88320)
    raise ProtocolFailure(f"host lacks checksum support for algorithm {algorithm}")


def _table_crc32(
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
    """Compute exactly the named wire variant for continuous trailer checks."""

    if algorithm == CHECKSUM_ADLER32:
        return zlib.adler32(data, 1) & 0xFFFFFFFF
    if algorithm == CHECKSUM_CRC32C:
        return _table_crc32(data, CRC32C_TABLE)
    if algorithm == CHECKSUM_CRC32_ISO_HDLC:
        return zlib.crc32(data, 0) & 0xFFFFFFFF
    raise ProtocolFailure(f"host lacks checksum support for algorithm {algorithm}")


def benchmark_vector_bytes(vector: int, algorithm: int) -> bytes:
    """Construct the exact bytes consumed by the target benchmark runner."""

    if vector == VECTOR_EMPTY:
        return b""
    if vector == VECTOR_CANONICAL_123456789:
        return b"123456789"
    if vector in {VECTOR_BUFFER_64, VECTOR_BUFFER_512}:
        return bytes((index * 37 + 11) & 0xFF for index in range(VECTOR_BYTES[vector]))
    if vector != VECTOR_FRAME_COVERAGE:
        raise ValueError(f"unknown benchmark vector {vector}")
    payload = bytes(
        (index * 37 + 11) & 0xFF
        for index in range(HEADER_SIZE, HEADER_SIZE + DATA_PAYLOAD_BYTES)
    )
    header = HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        GPIO_DATA,
        FLAG_SYNTHETIC | FLAG_EPOCH_START,
        HEADER_SIZE,
        algorithm,
        0,
        DATA_FRAME_BYTES,
        DATA_PAYLOAD_BYTES,
        1,
        0,
        0,
        0,
        GPIO_SAMPLES_PER_FRAME,
    )
    return header + payload


def validate_independent_vectors() -> tuple[dict[str, object], ...]:
    """Validate fast and bitwise paths against fixed values before serial I/O."""

    records: list[dict[str, object]] = []
    for algorithm in sorted(SUPPORTED_CHECKSUMS):
        for vector in BENCHMARK_VECTORS:
            body = benchmark_vector_bytes(vector, algorithm)
            expected = EXPECTED_VECTOR_CHECKSUMS[algorithm][vector]
            reference = reference_checksum(body, algorithm)
            fast = compute_checksum(body, algorithm)
            if len(body) != VECTOR_BYTES[vector]:
                raise ProtocolFailure(
                    f"{VECTOR_NAMES[vector]} constructed {len(body)} bytes; "
                    f"expected {VECTOR_BYTES[vector]}"
                )
            if reference != expected or fast != expected:
                raise ProtocolFailure(
                    f"{CHECKSUM_NAMES[algorithm]} {VECTOR_NAMES[vector]} "
                    f"expected 0x{expected:08x}, reference=0x{reference:08x}, "
                    f"fast=0x{fast:08x}"
                )
            records.append(
                {
                    "checksum_algorithm": CHECKSUM_NAMES[algorithm],
                    "checksum_algorithm_id": algorithm,
                    "checksum_hex": f"{expected:08x}",
                    "input_bytes": len(body),
                    "vector": VECTOR_NAMES[vector],
                    "vector_id": vector,
                }
            )
    return tuple(records)


def expected_benchmark_digest(checksum_value: int, operations: int) -> int:
    digest = 0x811C9DC5
    for operation_index in range(operations):
        digest ^= (
            checksum_value + 0x9E3779B9 + ((digest << 6) & 0xFFFFFFFF) + (digest >> 2)
        ) & 0xFFFFFFFF
        digest &= 0xFFFFFFFF
        digest ^= (operation_index * 0x85EBCA6B) & 0xFFFFFFFF
        digest &= 0xFFFFFFFF
    return digest


class SerialPort(Protocol):
    """The narrow pyserial surface used by this self-contained program."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


class BufferedSerialPort:
    """Drain the OS TTY continuously into one fixed-size in-memory queue."""

    def __init__(self, port: SerialPort) -> None:
        self._port = port
        self._chunks: deque[bytes] = deque()
        self._queued_bytes = 0
        self._high_water_bytes = 0
        self._high_water_chunks = 0
        self._error: Exception | None = None
        self._stopped = False
        self._condition = threading.Condition()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="checksum-rig-serial-reader",
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
                self._queued_bytes -= len(result)
            else:
                result = chunk
                self._queued_bytes -= len(chunk)
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

    def reader_queue_metrics(self) -> dict[str, int | bool]:
        with self._condition:
            return {
                "enabled": True,
                "capacity_bytes": SERIAL_READER_QUEUE_BYTES,
                "capacity_chunks": SERIAL_READER_QUEUE_CHUNKS,
                "final_bytes": self._queued_bytes,
                "final_chunks": len(self._chunks),
                "high_water_bytes": self._high_water_bytes,
                "high_water_chunks": self._high_water_chunks,
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
                chunk = bytes(self._port.read(SERIAL_READ_BYTES))
            except Exception as error:  # noqa: BLE001 - relay reader failures
                with self._condition:
                    self._error = error
                    self._condition.notify_all()
                return
            if not chunk:
                continue
            with self._condition:
                if self._stopped:
                    return
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
    """One independently validated wire frame."""

    kind: int
    flags: int
    checksum_algorithm: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    payload: bytes
    checksum: int


@dataclass(frozen=True)
class StatusSnapshot:
    device_state: int
    stream_mask: int
    source: int
    checksum: int
    data_frame_bytes: int
    adc_frames_emitted: int
    gpio_frames_emitted: int
    adc_items_dropped: int
    gpio_items_dropped: int
    parser_errors: int
    transport_errors: int
    stats_generation: int


@dataclass
class StreamTotals:
    expected_sequence: int = 0
    expected_ticks: int = 0
    frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0


@dataclass(frozen=True)
class BenchmarkSelection:
    checksum_algorithm: int
    vector: int
    memory_region: int
    cache_state: int
    batch_count: int
    iterations_per_batch: int

    def __post_init__(self) -> None:
        if self.checksum_algorithm not in SUPPORTED_CHECKSUMS:
            raise ValueError("benchmark checksum algorithm is not supported")
        if self.vector not in BENCHMARK_VECTORS:
            raise ValueError("benchmark vector is unknown")
        if self.memory_region not in MEMORY_NAMES:
            raise ValueError("benchmark memory region is unknown")
        if self.cache_state not in CACHE_NAMES:
            raise ValueError("benchmark cache state is unknown")
        if not 1 <= self.batch_count <= MAX_BENCHMARK_BATCH_COUNT:
            raise ValueError("benchmark batch count is outside its bound")
        if not 1 <= self.iterations_per_batch <= MAX_BENCHMARK_ITERATIONS_PER_BATCH:
            raise ValueError("benchmark iteration count is outside its bound")
        if self.cache_state == CACHE_COLD_INVALIDATED and (
            self.memory_region != MEMORY_OCRAM_DMA or self.vector == VECTOR_EMPTY
        ):
            raise ValueError("cold benchmark needs nonempty DMA-visible OCRAM")
        if self.operations > MAX_BENCHMARK_OPERATIONS:
            raise ValueError("benchmark exceeds its operation bound")
        if self.processed_bytes > MAX_BENCHMARK_PROCESSED_BYTES:
            raise ValueError("benchmark exceeds its processed-byte bound")

    @property
    def buffer_bytes(self) -> int:
        return VECTOR_BYTES[self.vector]

    @property
    def operations(self) -> int:
        return self.batch_count * self.iterations_per_batch

    @property
    def processed_bytes(self) -> int:
        return self.operations * self.buffer_bytes

    def to_payload(self) -> bytes:
        return BENCHMARK_REQUEST.pack(
            self.checksum_algorithm,
            self.vector,
            self.memory_region,
            self.cache_state,
            self.batch_count,
            self.iterations_per_batch,
        )


@dataclass(frozen=True)
class BenchmarkMeasurement:
    selection: BenchmarkSelection
    buffer_bytes: int
    cycle_counter_hz: int
    timer_overhead_cycles: int
    implementation_code_bytes: int
    table_bytes: int
    working_ram_bytes: int
    deterministic_digest: int
    processed_bytes: int
    raw_checksum_cycles: int
    net_checksum_cycles: int
    cache_setup_cycles: int
    min_batch_cycles: int
    max_batch_cycles: int
    cycles_per_byte_q16: int
    mb_per_second_q16: int
    projected_cpu_percent_q16: int
    target_framed_bytes_per_second: int

    @property
    def cycles_per_byte(self) -> float:
        return self.cycles_per_byte_q16 / 65_536.0

    @property
    def mb_per_second(self) -> float:
        return self.mb_per_second_q16 / 65_536.0

    @property
    def projected_cpu_percent(self) -> float:
        return self.projected_cpu_percent_q16 / 65_536.0


def encode_request(kind: int, request_id: int, payload: bytes = b"") -> bytes:
    """Independently encode one bounded protocol-v1 command."""

    if kind not in REQUEST_PAYLOAD_SIZE:
        raise ValueError(f"unknown request kind 0x{kind:02x}")
    if len(payload) != REQUEST_PAYLOAD_SIZE[kind]:
        raise ValueError(
            f"request 0x{kind:02x} needs {REQUEST_PAYLOAD_SIZE[kind]} payload bytes"
        )
    if not 1 <= request_id <= 0xFFFFFFFF:
        raise ValueError("request ID must be a nonzero uint32")
    total_length = HEADER_SIZE + len(payload) + TRAILER_SIZE
    header = HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        kind,
        0,
        HEADER_SIZE,
        BOOTSTRAP_CHECKSUM,
        0,
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


class FrameParser:
    """Bounded resynchronizing parser for arbitrary high-rate CDC chunks."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.bytes_received = 0
        self.frames_decoded = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.bytes_discarded = 0
        self.high_water_bytes = 0
        self.synthetic_crc32c_combined_checks = 0
        self.full_crc32c_data_checks = 0

    @property
    def errors(self) -> int:
        return self.header_errors + self.checksum_errors + self.payload_errors

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
                self._discard(len(self.buffer) - retained)
                break
            self._discard(magic_at)
            if len(self.buffer) < HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.buffer)
            try:
                total_length = self._validate_header(fields)
            except ProtocolFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            if len(self.buffer) < total_length:
                break
            payload_length = fields[8]
            payload_end = HEADER_SIZE + payload_length
            try:
                expected: int | None = None
                if fields[2] in DATA_KINDS and fields[5] == CHECKSUM_CRC32C:
                    expected = _synthetic_crc32c_data_checksum(
                        self.buffer,
                        fields,
                        payload_end,
                    )
                    if expected is None:
                        self.full_crc32c_data_checks += 1
                    else:
                        self.synthetic_crc32c_combined_checks += 1
                if expected is None:
                    expected = compute_checksum(
                        memoryview(self.buffer)[:payload_end], fields[5]
                    )
            except ProtocolFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            actual = TRAILER.unpack_from(self.buffer, payload_end)[0]
            if actual != expected:
                self.checksum_errors += 1
                self._discard(1)
                continue
            frame = Frame(
                kind=fields[2],
                flags=fields[3],
                checksum_algorithm=fields[5],
                run_id=fields[9],
                sequence=fields[10],
                request_id=fields[11],
                first_sample_ticks=fields[12],
                item_count=fields[13],
                payload=bytes(self.buffer[HEADER_SIZE:payload_end]),
                checksum=actual,
            )
            try:
                self._validate_payload(frame)
            except ProtocolFailure:
                self.payload_errors += 1
                self._discard(1)
                continue
            del self.buffer[:total_length]
            self.frames_decoded += 1
            frames.append(frame)

        retained_bound = MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1
        if len(self.buffer) > retained_bound:
            raise ProtocolFailure(
                f"parser retained {len(self.buffer)} bytes; bound is {retained_bound}"
            )
        high_water_bound = SERIAL_READ_BYTES + retained_bound
        if self.high_water_bytes > high_water_bound:
            raise ProtocolFailure(
                f"parser high water is {self.high_water_bytes}; bound is "
                f"{high_water_bound}"
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
            reserved,
            total_length,
            payload_length,
            run_id,
            sequence,
            request_id,
            first_sample_ticks,
            item_count,
        ) = fields
        if magic != MAGIC or version != PROTOCOL_VERSION:
            raise ProtocolFailure("invalid magic or protocol version")
        if header_length != HEADER_SIZE or reserved:
            raise ProtocolFailure("invalid fixed header fields")
        if total_length != HEADER_SIZE + payload_length + TRAILER_SIZE:
            raise ProtocolFailure("inconsistent total and payload lengths")
        if kind in DATA_KINDS:
            if checksum not in SUPPORTED_CHECKSUMS:
                raise ProtocolFailure(
                    f"host lacks checksum support for algorithm {checksum}"
                )
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            period = (
                ADC_PAIR_PERIOD_TICKS if kind == ADC_DATA else GPIO_SAMPLE_PERIOD_TICKS
            )
            if total_length != DATA_FRAME_BYTES or payload_length != DATA_PAYLOAD_BYTES:
                raise ProtocolFailure("data frame does not have its fixed shape")
            if flags & ~DATA_FLAG_MASK:
                raise ProtocolFailure("data frame carries a reserved flag")
            if flags & FLAG_OVERRUN_BEFORE and not flags & FLAG_GAP_BEFORE:
                raise ProtocolFailure("OVERRUN_BEFORE lacks GAP_BEFORE")
            if run_id == 0 or request_id != 0 or item_count != expected_items:
                raise ProtocolFailure("invalid data run/request/item fields")
            if first_sample_ticks % period:
                raise ProtocolFailure("data timestamp is not source-period aligned")
            epoch = bool(flags & FLAG_EPOCH_START)
            if epoch != (sequence == 0 and first_sample_ticks == 0):
                raise ProtocolFailure("EPOCH_START disagrees with sequence/timestamp")
            return total_length

        if kind not in RESPONSE_KINDS:
            raise ProtocolFailure(f"unexpected device frame kind 0x{kind:02x}")
        if checksum != BOOTSTRAP_CHECKSUM:
            raise ProtocolFailure("control response does not use bootstrap Adler-32")
        if flags not in {0, FLAG_RESPONSE_ERROR}:
            raise ProtocolFailure("control response carries invalid flags")
        if kind == ERROR_RESPONSE and flags != FLAG_RESPONSE_ERROR:
            raise ProtocolFailure("generic error response lacks its error flag")
        if not HEADER_SIZE + TRAILER_SIZE <= total_length <= MAX_CONTROL_FRAME_BYTES:
            raise ProtocolFailure("control response exceeds its finite bound")
        if request_id == 0 or sequence or first_sample_ticks or item_count:
            raise ProtocolFailure("invalid response correlation/data-only fields")
        expected_payload = (
            4
            if flags == FLAG_RESPONSE_ERROR and kind != ERROR_RESPONSE
            else SUCCESS_PAYLOAD_SIZE[kind]
        )
        if payload_length != expected_payload:
            raise ProtocolFailure("response payload length does not match its kind")
        return total_length

    @staticmethod
    def _validate_payload(frame: Frame) -> None:
        if frame.kind in DATA_KINDS:
            return
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == FLAG_RESPONSE_ERROR
        if reserved or is_error != (status == 1) or (error == 0) == is_error:
            raise ProtocolFailure("response prefix status/flag/error disagrees")
        if not is_error and status != 0:
            raise ProtocolFailure("successful response has nonzero status")
        if error > 12:
            raise ProtocolFailure("response reports an unknown error code")
        if is_error and frame.kind != ERROR_RESPONSE:
            return
        payload = frame.payload
        if frame.kind == INFO_RESPONSE and (payload[1] or payload[61]):
            raise ProtocolFailure("INFO reserved fields are nonzero")
        if frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE} and (
            payload[1] or payload[7]
        ):
            raise ProtocolFailure("configuration response reserved field is nonzero")
        if frame.kind == GET_STATUS_RESPONSE and payload[1]:
            raise ProtocolFailure("STATUS reserved field is nonzero")
        if frame.kind == STOP_RESPONSE and (payload[1] or any(payload[5:])):
            raise ProtocolFailure("STOP reserved fields are nonzero")
        if frame.kind == CHECKSUM_BENCHMARK_RESPONSE and payload[1]:
            raise ProtocolFailure("benchmark response reserved field is nonzero")

    def _partial_magic_suffix(self) -> int:
        maximum = min(len(self.buffer), len(MAGIC_BYTES) - 1)
        for length in range(maximum, 0, -1):
            if self.buffer[-length:] == MAGIC_BYTES[:length]:
                return length
        return 0

    def _discard(self, count: int) -> None:
        if count > 0:
            del self.buffer[:count]
            self.bytes_discarded += count


class SerialLink:
    """One-request-at-a-time serial link that services data while waiting."""

    def __init__(self, port: SerialPort) -> None:
        self.port = port
        self.parser = FrameParser()
        self.next_request_id = 1
        self.stale_responses = 0
        self.discarded_data_frames = 0
        self.maximum_read_bytes = 0

    def reader_queue_metrics(self) -> dict[str, int | bool]:
        if isinstance(self.port, BufferedSerialPort):
            return self.port.reader_queue_metrics()
        return {
            "enabled": False,
            "capacity_bytes": 0,
            "capacity_chunks": 0,
            "final_bytes": 0,
            "final_chunks": 0,
            "high_water_bytes": 0,
            "high_water_chunks": 0,
        }

    def drain_startup(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        discarded_frames = 0
        while time.monotonic() < deadline:
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
            self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
            if chunk:
                discarded_frames += len(self.parser.feed(chunk))
        self.discarded_data_frames += discarded_frames
        emit_event(
            "startup_drain",
            discarded_bytes=self.parser.bytes_discarded,
            discarded_frames=discarded_frames,
        )

    def exchange(
        self,
        request_kind: int,
        payload: bytes = b"",
        *,
        timeout: float | None = None,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[Frame, float]:
        request_id = self._allocate_request_id()
        wire = encode_request(request_kind, request_id, payload)
        started = time.monotonic()
        deadline = started + (COMMAND_DEADLINE_SECONDS if timeout is None else timeout)
        self._write_all(wire, deadline)
        expected_kind = REQUEST_RESPONSE_KIND[request_kind]
        while True:
            if time.monotonic() >= deadline:
                raise DeadlineExpired(
                    f"request {request_id} kind 0x{request_kind:02x} timed out"
                )
            frames = self._read_once()
            matched: Frame | None = None
            for frame in frames:
                if frame.kind in DATA_KINDS:
                    if on_data is None:
                        self.discarded_data_frames += 1
                    else:
                        on_data(frame)
                    continue
                if frame.request_id != request_id:
                    self.stale_responses += 1
                    continue
                if frame.kind != expected_kind:
                    raise ProtocolFailure(
                        f"request {request_id} expected kind 0x{expected_kind:02x}, "
                        f"received 0x{frame.kind:02x}"
                    )
                if matched is not None:
                    raise ProtocolFailure(
                        f"request {request_id} received two responses"
                    )
                matched = frame
            if matched is not None:
                return matched, time.monotonic() - started

    def pump_once(self, on_data: Callable[[Frame], None]) -> int:
        chunk, frames = self._read_chunk_and_frames()
        for frame in frames:
            if frame.kind not in DATA_KINDS:
                raise ProtocolFailure(
                    f"unsolicited response kind 0x{frame.kind:02x} "
                    f"for request {frame.request_id}"
                )
            on_data(frame)
        return len(chunk)

    def drain_until_quiet(self, on_data: Callable[[Frame], None]) -> None:
        hard_deadline = time.monotonic() + STOP_DRAIN_DEADLINE_SECONDS
        quiet_since = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= hard_deadline:
                raise DeadlineExpired("post-STOP data did not drain before deadline")
            if now - quiet_since >= STOP_DRAIN_QUIET_SECONDS:
                if self.parser.buffer:
                    raise ProtocolFailure(
                        f"post-STOP parser retains {len(self.parser.buffer)} bytes"
                    )
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
                raise DeadlineExpired(
                    f"serial write stopped after {offset}/{len(wire)} bytes"
                )
            written = self.port.write(wire[offset:])
            if written is None:
                written = 0
            if not isinstance(written, int) or not 0 <= written <= len(wire) - offset:
                raise ProtocolFailure(
                    f"serial write returned invalid count {written!r}"
                )
            offset += written
            if written == 0:
                time.sleep(0.001)

    def _read_once(self) -> list[Frame]:
        _chunk, frames = self._read_chunk_and_frames()
        return frames

    def _read_chunk_and_frames(self) -> tuple[bytes, list[Frame]]:
        chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        return chunk, self.parser.feed(chunk)


def emit_event(name: str, **fields: object) -> None:
    """Print one machine-readable lifecycle record."""

    print(
        "EVENT "
        + json.dumps(
            {"event": name, **fields},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def response_success(frame: Frame, expected_kind: int) -> None:
    if frame.kind != expected_kind or frame.flags:
        status, _reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        raise ProtocolFailure(
            f"response 0x{frame.kind:02x} flags=0x{frame.flags:04x} "
            f"status={status} error={error}"
        )
    status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    if status or reserved or error:
        raise ProtocolFailure("successful response prefix is invalid")


def decode_info(frame: Frame) -> dict[str, object]:
    response_success(frame, INFO_RESPONSE)
    payload = frame.payload
    build_field = payload[66:98]
    try:
        terminator = build_field.index(0)
        build_id = build_field[:terminator].decode("ascii")
    except (ValueError, UnicodeDecodeError) as error:
        raise ProtocolFailure("INFO build ID is not NUL-terminated ASCII") from error
    if any(build_field[terminator + 1 :]):
        raise ProtocolFailure("INFO build ID padding is nonzero")
    return {
        "device_state": payload[4],
        "protocol_version": payload[5],
        "supported_stream_mask": payload[6],
        "supported_source_mask": payload[7],
        "supported_checksum_mask": struct.unpack_from("<I", payload, 8)[0],
        "capability_bits": struct.unpack_from("<I", payload, 12)[0],
        "timestamp_hz": struct.unpack_from("<I", payload, 16)[0],
        "data_frame_bytes": struct.unpack_from("<I", payload, 20)[0],
        "max_control_frame_bytes": struct.unpack_from("<I", payload, 24)[0],
        "adc_pair_rate_hz": struct.unpack_from("<I", payload, 28)[0],
        "gpio_sample_rate_hz": struct.unpack_from("<I", payload, 32)[0],
        "adc_pair_period_ticks": struct.unpack_from("<H", payload, 36)[0],
        "adc1_phase_ticks": struct.unpack_from("<H", payload, 38)[0],
        "gpio_sample_period_ticks": struct.unpack_from("<H", payload, 40)[0],
        "adc_resolution_bits": payload[42],
        "adc_container_bytes": payload[43],
        "gpio_pin_count": payload[44],
        "data_checksum_algorithm": payload[45],
        "gpio_pin_map": tuple(payload[46:54]),
        "hardware_serial": struct.unpack_from("<I", payload, 54)[0],
        "firmware_version": tuple(payload[58:61]),
        "board_id": struct.unpack_from("<H", payload, 62)[0],
        "mcu_id": struct.unpack_from("<H", payload, 64)[0],
        "build_id": build_id,
    }


def decode_configuration(frame: Frame, expected_kind: int) -> tuple[int, int, int, int]:
    response_success(frame, expected_kind)
    streams, source, checksum, reserved, frame_bytes = CONFIGURATION.unpack_from(
        frame.payload, 4
    )
    if reserved:
        raise ProtocolFailure("applied configuration reserved byte is nonzero")
    return streams, source, checksum, frame_bytes


def decode_status(frame: Frame) -> StatusSnapshot:
    response_success(frame, GET_STATUS_RESPONSE)
    payload = frame.payload
    return StatusSnapshot(
        device_state=payload[4],
        stream_mask=payload[5],
        source=payload[6],
        checksum=payload[7],
        data_frame_bytes=struct.unpack_from("<I", payload, 8)[0],
        adc_frames_emitted=struct.unpack_from("<Q", payload, 12)[0],
        gpio_frames_emitted=struct.unpack_from("<Q", payload, 20)[0],
        adc_items_dropped=struct.unpack_from("<Q", payload, 28)[0],
        gpio_items_dropped=struct.unpack_from("<Q", payload, 36)[0],
        parser_errors=struct.unpack_from("<I", payload, 44)[0],
        transport_errors=struct.unpack_from("<I", payload, 48)[0],
        stats_generation=struct.unpack_from("<I", payload, 52)[0],
    )


def stable_identity(info: dict[str, object]) -> tuple[object, ...]:
    return tuple(
        info[name]
        for name in (
            "protocol_version",
            "firmware_version",
            "build_id",
            "hardware_serial",
            "board_id",
            "mcu_id",
        )
    )


def synchronize(link: SerialLink) -> dict[str, object]:
    first_identity: tuple[object, ...] | None = None
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, _latency = link.exchange(INFO_REQUEST, timeout=SYNC_DEADLINE_SECONDS)
            info = decode_info(frame)
            identity = stable_identity(info)
            if first_identity is None:
                first_identity = identity
                emit_event("sync_probe", attempt=attempt, disposition="throwaway")
            elif identity == first_identity:
                emit_event("sync_probe", attempt=attempt, disposition="stable")
                return info
            else:
                raise ProtocolFailure("INFO identity changed during synchronization")
        except DeadlineExpired as error:
            last_error = str(error)
        if attempt < SYNC_ATTEMPTS:
            time.sleep(0.01)
    raise DeadlineExpired(
        f"synchronization failed after {SYNC_ATTEMPTS} attempts: {last_error}"
    )


def validate_info(
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> tuple[int, ...]:
    expected = {
        "device_state": STATE_IDLE,
        "protocol_version": PROTOCOL_VERSION,
        "supported_stream_mask": STREAM_BOTH,
        "supported_source_mask": 1 << SOURCE_SYNTHETIC,
        "capability_bits": EXPECTED_CAPABILITIES,
        "timestamp_hz": TIMESTAMP_HZ,
        "data_frame_bytes": DATA_FRAME_BYTES,
        "max_control_frame_bytes": MAX_CONTROL_FRAME_BYTES,
        "adc_pair_rate_hz": ADC_PAIR_RATE_HZ,
        "gpio_sample_rate_hz": GPIO_SAMPLE_RATE_HZ,
        "adc_pair_period_ticks": ADC_PAIR_PERIOD_TICKS,
        "adc1_phase_ticks": ADC1_PHASE_TICKS,
        "gpio_sample_period_ticks": GPIO_SAMPLE_PERIOD_TICKS,
        "adc_resolution_bits": ADC_RESOLUTION_BITS,
        "adc_container_bytes": ADC_CONTAINER_BYTES,
        "gpio_pin_count": len(GPIO_PINS_BY_BIT),
        "gpio_pin_map": GPIO_PINS_BY_BIT,
        "firmware_version": (0, 5, 0),
        "board_id": 1,
        "mcu_id": 1,
    }
    for name, wanted in expected.items():
        if info[name] != wanted:
            raise ProtocolFailure(f"INFO {name} is {info[name]!r}; expected {wanted!r}")
    mask = info["supported_checksum_mask"]
    if not isinstance(mask, int) or isinstance(mask, bool):
        raise ProtocolFailure("INFO checksum mask is not an integer")
    if mask == 0 or mask & ~SUPPORTED_CHECKSUM_MASK:
        raise ProtocolFailure(
            f"device advertises unsupported checksum mask 0x{mask:08x}"
        )
    candidates = tuple(
        algorithm
        for algorithm in sorted(SUPPORTED_CHECKSUMS)
        if mask & (1 << algorithm)
    )
    selected = info["data_checksum_algorithm"]
    if selected not in candidates:
        raise ProtocolFailure("INFO selected checksum is not advertised")
    build_id = info["build_id"]
    if (
        not isinstance(build_id, str)
        or re.fullmatch(r"tdaq-[0-9a-f]{16}", build_id) is None
    ):
        raise ProtocolFailure("INFO build ID does not match tdaq-<16 lowercase hex>")
    if expected_build_id is not None and build_id != expected_build_id:
        raise ProtocolFailure(
            f"INFO build ID is {build_id}; expected {expected_build_id}"
        )
    hardware_serial = info["hardware_serial"]
    if not isinstance(hardware_serial, int) or isinstance(hardware_serial, bool):
        raise ProtocolFailure("INFO hardware serial is not an integer")
    if not 1 <= hardware_serial <= 0xFFFFFFFF:
        raise ProtocolFailure("INFO hardware serial is not a nonzero uint32")
    if (
        expected_hardware_serial is not None
        and hardware_serial != expected_hardware_serial
    ):
        raise ProtocolFailure(
            f"INFO hardware serial is {hardware_serial}; "
            f"expected {expected_hardware_serial}"
        )
    return candidates


def _u32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<I", payload, offset)[0]


def _u64(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", payload, offset)[0]


def decode_benchmark_measurement(
    frame: Frame,
    expected_selection: BenchmarkSelection,
) -> BenchmarkMeasurement:
    """Decode and independently cross-check every benchmark result field."""

    response_success(frame, CHECKSUM_BENCHMARK_RESPONSE)
    payload = frame.payload
    selection = BenchmarkSelection(*BENCHMARK_REQUEST.unpack_from(payload, 4))
    if selection != expected_selection:
        raise ProtocolFailure(
            f"benchmark echoed {selection!r}; expected {expected_selection!r}"
        )
    measurement = BenchmarkMeasurement(
        selection=selection,
        buffer_bytes=_u32(payload, 12),
        cycle_counter_hz=_u32(payload, 16),
        timer_overhead_cycles=_u32(payload, 20),
        implementation_code_bytes=_u32(payload, 24),
        table_bytes=_u32(payload, 28),
        working_ram_bytes=_u32(payload, 32),
        deterministic_digest=_u32(payload, 36),
        processed_bytes=_u64(payload, 40),
        raw_checksum_cycles=_u64(payload, 48),
        net_checksum_cycles=_u64(payload, 56),
        cache_setup_cycles=_u64(payload, 64),
        min_batch_cycles=_u32(payload, 72),
        max_batch_cycles=_u32(payload, 76),
        cycles_per_byte_q16=_u32(payload, 80),
        mb_per_second_q16=_u32(payload, 84),
        projected_cpu_percent_q16=_u32(payload, 88),
        target_framed_bytes_per_second=_u32(payload, 92),
    )
    operations = selection.operations
    expected_table_bytes = (
        0 if selection.checksum_algorithm == CHECKSUM_ADLER32 else 4_096
    )
    calibrated_overhead = operations * measurement.timer_overhead_cycles
    expected_digest = expected_benchmark_digest(
        EXPECTED_VECTOR_CHECKSUMS[selection.checksum_algorithm][selection.vector],
        operations,
    )
    if (
        measurement.buffer_bytes != selection.buffer_bytes
        or measurement.cycle_counter_hz != BENCHMARK_CYCLE_COUNTER_HZ
        or measurement.implementation_code_bytes == 0
        or measurement.table_bytes != expected_table_bytes
        or measurement.working_ram_bytes != BENCHMARK_WORKING_RAM_BYTES
        or measurement.deterministic_digest != expected_digest
        or measurement.processed_bytes != selection.processed_bytes
        or measurement.raw_checksum_cycles < calibrated_overhead
        or measurement.raw_checksum_cycles - calibrated_overhead
        != measurement.net_checksum_cycles
        or measurement.min_batch_cycles > measurement.max_batch_cycles
        or measurement.net_checksum_cycles
        < measurement.min_batch_cycles * selection.batch_count
        or measurement.net_checksum_cycles
        > measurement.max_batch_cycles * selection.batch_count
        or (
            selection.cache_state != CACHE_COLD_INVALIDATED
            and measurement.cache_setup_cycles != 0
        )
        or measurement.target_framed_bytes_per_second
        != BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND
    ):
        raise ProtocolFailure("benchmark response raw/resource fields disagree")

    total_cycles = measurement.net_checksum_cycles + measurement.cache_setup_cycles
    if measurement.processed_bytes == 0:
        expected_metrics = (0, 0, 0)
    else:
        if total_cycles == 0:
            raise ProtocolFailure("nonempty benchmark reported zero cycles")
        cycles_per_byte_q16 = total_cycles * 65_536 // measurement.processed_bytes
        bytes_per_second = (
            measurement.cycle_counter_hz * measurement.processed_bytes // total_cycles
        )
        expected_metrics = (
            cycles_per_byte_q16,
            bytes_per_second * 65_536 // 1_000_000,
            cycles_per_byte_q16
            * measurement.target_framed_bytes_per_second
            * 100
            // measurement.cycle_counter_hz,
        )
    actual_metrics = (
        measurement.cycles_per_byte_q16,
        measurement.mb_per_second_q16,
        measurement.projected_cpu_percent_q16,
    )
    if actual_metrics != expected_metrics:
        raise ProtocolFailure(
            f"benchmark derived metrics are {actual_metrics}; expected {expected_metrics}"
        )
    return measurement


def measurement_record(
    measurement: BenchmarkMeasurement,
    command_latency_seconds: float,
) -> dict[str, object]:
    selection = measurement.selection
    return {
        "batch_count": selection.batch_count,
        "buffer_bytes": measurement.buffer_bytes,
        "cache_setup_cycles": measurement.cache_setup_cycles,
        "cache_state": CACHE_NAMES[selection.cache_state],
        "cache_state_id": selection.cache_state,
        "checksum_algorithm": CHECKSUM_NAMES[selection.checksum_algorithm],
        "checksum_algorithm_id": selection.checksum_algorithm,
        "command_latency_seconds": command_latency_seconds,
        "cycle_counter_hz": measurement.cycle_counter_hz,
        "cycles_per_byte": measurement.cycles_per_byte,
        "cycles_per_byte_q16": measurement.cycles_per_byte_q16,
        "deterministic_digest": measurement.deterministic_digest,
        "implementation_code_bytes": measurement.implementation_code_bytes,
        "iterations_per_batch": selection.iterations_per_batch,
        "maximum_batch_cycles": measurement.max_batch_cycles,
        "mb_per_second": measurement.mb_per_second,
        "mb_per_second_q16": measurement.mb_per_second_q16,
        "memory_region": MEMORY_NAMES[selection.memory_region],
        "memory_region_id": selection.memory_region,
        "minimum_batch_cycles": measurement.min_batch_cycles,
        "net_checksum_cycles": measurement.net_checksum_cycles,
        "processed_bytes": measurement.processed_bytes,
        "projected_cpu_percent": measurement.projected_cpu_percent,
        "projected_cpu_percent_q16": measurement.projected_cpu_percent_q16,
        "raw_checksum_cycles": measurement.raw_checksum_cycles,
        "table_flash_bytes": measurement.table_bytes,
        "target_framed_bytes_per_second": (measurement.target_framed_bytes_per_second),
        "timer_overhead_cycles": measurement.timer_overhead_cycles,
        "vector": VECTOR_NAMES[selection.vector],
        "vector_id": selection.vector,
        "working_ram_bytes": measurement.working_ram_bytes,
    }


def benchmark_selections(
    checksum_algorithm: int,
    *,
    batch_count: int,
    iterations_per_batch: int,
) -> tuple[BenchmarkSelection, ...]:
    """Build every meaningful vector/region/cache combination within bounds."""

    selections: list[BenchmarkSelection] = []
    for vector in BENCHMARK_VECTORS:
        buffer_bytes = VECTOR_BYTES[vector]
        bounded_iterations = min(
            iterations_per_batch,
            MAX_BENCHMARK_OPERATIONS // batch_count,
        )
        if buffer_bytes:
            bounded_iterations = min(
                bounded_iterations,
                MAX_BENCHMARK_PROCESSED_BYTES // (batch_count * buffer_bytes),
            )
        if bounded_iterations < 1:
            raise ValueError(
                f"benchmark count cannot fit vector {VECTOR_NAMES[vector]}"
            )
        for memory_region, cache_state in (
            (MEMORY_DTCM_PACKET, CACHE_HOT_OR_NATIVE),
            (MEMORY_OCRAM_DMA, CACHE_HOT_OR_NATIVE),
        ):
            selections.append(
                BenchmarkSelection(
                    checksum_algorithm=checksum_algorithm,
                    vector=vector,
                    memory_region=memory_region,
                    cache_state=cache_state,
                    batch_count=batch_count,
                    iterations_per_batch=bounded_iterations,
                )
            )
        if vector != VECTOR_EMPTY:
            selections.append(
                BenchmarkSelection(
                    checksum_algorithm=checksum_algorithm,
                    vector=vector,
                    memory_region=MEMORY_OCRAM_DMA,
                    cache_state=CACHE_COLD_INVALIDATED,
                    batch_count=batch_count,
                    iterations_per_batch=bounded_iterations,
                )
            )
    return tuple(selections)


def _status_tuple(status: StatusSnapshot, run_id: int) -> tuple[int, ...]:
    return (
        run_id,
        status.device_state,
        status.stream_mask,
        status.source,
        status.checksum,
        status.data_frame_bytes,
        status.adc_frames_emitted,
        status.gpio_frames_emitted,
        status.adc_items_dropped,
        status.gpio_items_dropped,
        status.parser_errors,
        status.transport_errors,
        status.stats_generation,
    )


def run_device_benchmarks(
    link: SerialLink,
    checksum_algorithm: int,
    *,
    batch_count: int,
    iterations_per_batch: int,
) -> tuple[tuple[BenchmarkMeasurement, ...], list[float]]:
    """Run the complete bounded target matrix and prove state is unchanged."""

    before_frame, _before_latency = link.exchange(GET_STATUS_REQUEST)
    before = decode_status(before_frame)
    if before.device_state != STATE_IDLE:
        raise ProtocolFailure("checksum benchmark requires the device to be IDLE")
    measurements: list[BenchmarkMeasurement] = []
    latencies: list[float] = []
    for selection in benchmark_selections(
        checksum_algorithm,
        batch_count=batch_count,
        iterations_per_batch=iterations_per_batch,
    ):
        frame, latency = link.exchange(
            CHECKSUM_BENCHMARK_REQUEST,
            selection.to_payload(),
            timeout=BENCHMARK_DEADLINE_SECONDS,
        )
        measurement = decode_benchmark_measurement(frame, selection)
        measurements.append(measurement)
        latencies.append(latency)
        emit_event(
            "device_checksum_benchmark",
            **measurement_record(measurement, latency),
        )

    after_frame, _after_latency = link.exchange(GET_STATUS_REQUEST)
    after = decode_status(after_frame)
    if _status_tuple(after, after_frame.run_id) != _status_tuple(
        before, before_frame.run_id
    ):
        raise ProtocolFailure("checksum benchmark changed acquisition state/statistics")
    resources = {
        (
            measurement.implementation_code_bytes,
            measurement.table_bytes,
            measurement.working_ram_bytes,
        )
        for measurement in measurements
    }
    if len(resources) != 1:
        raise ProtocolFailure("benchmark resource fields vary across vector profiles")
    return tuple(measurements), latencies


def _build_adc_cycle() -> bytes:
    pair_period = 1 << (ADC_RESOLUTION_BITS - 1)
    result = bytearray(pair_period * ADC_BYTES_PER_PAIR)
    code_mask = (1 << ADC_RESOLUTION_BITS) - 1
    for index in range(pair_period):
        struct.pack_into(
            "<HH",
            result,
            index * ADC_BYTES_PER_PAIR,
            (2 * index) & code_mask,
            (2 * index + 1) & code_mask,
        )
    return bytes(result)


ADC_PATTERN = _build_adc_cycle()
ADC_PATTERN_DOUBLE = ADC_PATTERN + ADC_PATTERN
GPIO_PATTERN_EXPANDED = bytes(range(256)) * 17


def _gf2_matrix_times(matrix: tuple[int, ...], value: int) -> int:
    result = 0
    index = 0
    while value:
        if value & 1:
            result ^= matrix[index]
        value >>= 1
        index += 1
    return result


def _gf2_matrix_square(matrix: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(_gf2_matrix_times(matrix, value) for value in matrix)


def _shift_reflected_crc32(
    value: int,
    byte_count: int,
    polynomial: int,
) -> int:
    """Apply ``byte_count`` zero bytes to a finalized reflected CRC."""

    if byte_count <= 0:
        return value
    odd = [polynomial]
    row = 1
    for _ in range(1, 32):
        odd.append(row)
        row <<= 1
    odd_matrix = tuple(odd)
    even_matrix = _gf2_matrix_square(odd_matrix)
    odd_matrix = _gf2_matrix_square(even_matrix)
    while True:
        even_matrix = _gf2_matrix_square(odd_matrix)
        if byte_count & 1:
            value = _gf2_matrix_times(even_matrix, value)
        byte_count >>= 1
        if not byte_count:
            return value
        odd_matrix = _gf2_matrix_square(even_matrix)
        if byte_count & 1:
            value = _gf2_matrix_times(odd_matrix, value)
        byte_count >>= 1
        if not byte_count:
            return value


CRC32C_PAYLOAD_SHIFT_OPERATOR = tuple(
    _shift_reflected_crc32(1 << bit, DATA_PAYLOAD_BYTES, 0x82F63B78)
    for bit in range(32)
)


def _build_synthetic_crc32c_payload_checksums() -> dict[tuple[int, int], int]:
    checksums: dict[tuple[int, int], int] = {}
    for kind, cycle in (
        (ADC_DATA, ADC_PATTERN),
        (GPIO_DATA, bytes(range(256))),
    ):
        offset = 0
        expanded = cycle + cycle * math.ceil(DATA_PAYLOAD_BYTES / len(cycle))
        while (kind, offset) not in checksums:
            expected = expanded[offset : offset + DATA_PAYLOAD_BYTES]
            checksums[(kind, offset)] = _table_crc32(expected, CRC32C_TABLE)
            offset = (offset + DATA_PAYLOAD_BYTES) % len(cycle)
    return checksums


SYNTHETIC_CRC32C_PAYLOAD_CHECKSUMS = _build_synthetic_crc32c_payload_checksums()


def _synthetic_crc32c_data_checksum(
    buffer: bytearray,
    fields: tuple[int, ...],
    payload_end: int,
) -> int | None:
    """Combine the actual header with a proven-exact synthetic payload CRC."""

    kind = fields[2]
    flags = fields[3]
    first_sample_ticks = fields[12]
    if not flags & FLAG_SYNTHETIC:
        return None
    if kind == ADC_DATA:
        start_pair = first_sample_ticks // ADC_PAIR_PERIOD_TICKS
        offset = (start_pair * ADC_BYTES_PER_PAIR) % len(ADC_PATTERN)
        expected_payload = ADC_PATTERN_DOUBLE[offset : offset + DATA_PAYLOAD_BYTES]
    elif kind == GPIO_DATA:
        start_sample = first_sample_ticks // GPIO_SAMPLE_PERIOD_TICKS
        offset = start_sample & 0xFF
        expected_payload = GPIO_PATTERN_EXPANDED[offset : offset + DATA_PAYLOAD_BYTES]
    else:
        return None
    payload_checksum = SYNTHETIC_CRC32C_PAYLOAD_CHECKSUMS.get((kind, offset))
    if payload_checksum is None or buffer[HEADER_SIZE:payload_end] != expected_payload:
        return None
    header_checksum = _table_crc32(
        memoryview(buffer)[:HEADER_SIZE],
        CRC32C_TABLE,
    )
    return (
        _gf2_matrix_times(CRC32C_PAYLOAD_SHIFT_OPERATOR, header_checksum)
        ^ payload_checksum
    )


class SyntheticValidator:
    """Continuously validate formulas, flags, sequences, and common epoch."""

    def __init__(self, run_id: int, checksum_algorithm: int) -> None:
        if not 1 <= run_id <= 0xFFFFFFFF:
            raise ValueError("run ID must be a nonzero uint32")
        if checksum_algorithm not in SUPPORTED_CHECKSUMS:
            raise ProtocolFailure(
                f"host lacks checksum support for algorithm {checksum_algorithm}"
            )
        self.run_id = run_id
        self.checksum_algorithm = checksum_algorithm
        self.adc = StreamTotals()
        self.gpio = StreamTotals()
        self.first_receive_time: float | None = None
        self.last_receive_time: float | None = None
        self.maximum_receive_gap_seconds = 0.0

    def accept(self, frame: Frame) -> None:
        received_at = time.monotonic()
        if self.first_receive_time is None:
            self.first_receive_time = received_at
        if self.last_receive_time is not None:
            self.maximum_receive_gap_seconds = max(
                self.maximum_receive_gap_seconds,
                received_at - self.last_receive_time,
            )
        self.last_receive_time = received_at
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"data run ID is {frame.run_id}; expected {self.run_id}"
            )
        if frame.checksum_algorithm != self.checksum_algorithm:
            raise ProtocolFailure(
                f"data checksum is {frame.checksum_algorithm}; configured "
                f"algorithm is {self.checksum_algorithm}"
            )
        if not frame.flags & FLAG_SYNTHETIC:
            raise ProtocolFailure("data frame lacks the SYNTHETIC flag")
        if frame.flags & (FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE):
            raise ProtocolFailure(
                f"data frame 0x{frame.kind:02x}/{frame.sequence} carries gap flags"
            )
        totals = self.adc if frame.kind == ADC_DATA else self.gpio
        expected_flags = FLAG_SYNTHETIC
        if totals.frames == 0:
            expected_flags |= FLAG_EPOCH_START
        if frame.flags != expected_flags:
            raise ProtocolFailure(
                f"frame flags are 0x{frame.flags:04x}; expected 0x{expected_flags:04x}"
            )
        if frame.sequence != totals.expected_sequence:
            raise ProtocolFailure(
                f"kind 0x{frame.kind:02x} sequence is {frame.sequence}; "
                f"expected {totals.expected_sequence}"
            )
        if frame.first_sample_ticks != totals.expected_ticks:
            raise ProtocolFailure(
                f"kind 0x{frame.kind:02x} timestamp is "
                f"{frame.first_sample_ticks}; expected {totals.expected_ticks}"
            )
        if frame.kind == ADC_DATA:
            self._validate_adc(frame)
        elif frame.kind == GPIO_DATA:
            self._validate_gpio(frame)
        else:
            raise ProtocolFailure(
                f"validator received non-data kind 0x{frame.kind:02x}"
            )
        totals.expected_sequence = (frame.sequence + 1) & 0xFFFFFFFF
        totals.expected_ticks = (frame.first_sample_ticks + FRAME_COVERAGE_TICKS) & (
            0xFFFFFFFFFFFFFFFF
        )
        totals.frames += 1
        totals.items += frame.item_count
        totals.payload_bytes += len(frame.payload)
        totals.framed_bytes += DATA_FRAME_BYTES

    @staticmethod
    def _validate_adc(frame: Frame) -> None:
        start_pair = frame.first_sample_ticks // ADC_PAIR_PERIOD_TICKS
        byte_offset = (start_pair * ADC_BYTES_PER_PAIR) % len(ADC_PATTERN)
        expected = ADC_PATTERN_DOUBLE[byte_offset : byte_offset + DATA_PAYLOAD_BYTES]
        if frame.payload == expected:
            return
        for pair_offset in range(ADC_PAIRS_PER_FRAME):
            observed_adc0, observed_adc1 = struct.unpack_from(
                "<HH", frame.payload, pair_offset * ADC_BYTES_PER_PAIR
            )
            pair_index = start_pair + pair_offset
            wanted = ((2 * pair_index) & 0xFFF, (2 * pair_index + 1) & 0xFFF)
            if (observed_adc0, observed_adc1) != wanted:
                raise ProtocolFailure(
                    f"ADC pair {pair_index} is ({observed_adc0}, "
                    f"{observed_adc1}); expected {wanted}"
                )
        raise ProtocolFailure("ADC payload differs despite matching decoded pairs")

    @staticmethod
    def _validate_gpio(frame: Frame) -> None:
        start_sample = frame.first_sample_ticks // GPIO_SAMPLE_PERIOD_TICKS
        offset = start_sample & 0xFF
        expected = GPIO_PATTERN_EXPANDED[offset : offset + DATA_PAYLOAD_BYTES]
        if frame.payload == expected:
            return
        for sample_offset, observed in enumerate(frame.payload):
            sample_index = start_sample + sample_offset
            wanted = sample_index & 0xFF
            if observed != wanted:
                raise ProtocolFailure(
                    f"GPIO sample {sample_index} is {observed}; expected {wanted}"
                )
        raise ProtocolFailure("GPIO payload differs despite matching samples")


def validate_running_status(
    status: StatusSnapshot,
    frame: Frame,
    validator: SyntheticValidator,
    stats_generation: int,
    received_frames_before_request: tuple[int, int],
) -> None:
    if frame.run_id != validator.run_id:
        raise ProtocolFailure(
            f"STATUS run ID is {frame.run_id}; expected {validator.run_id}"
        )
    expected_configuration = (
        STATE_RUNNING,
        STREAM_BOTH,
        SOURCE_SYNTHETIC,
        validator.checksum_algorithm,
        DATA_FRAME_BYTES,
    )
    actual_configuration = (
        status.device_state,
        status.stream_mask,
        status.source,
        status.checksum,
        status.data_frame_bytes,
    )
    if actual_configuration != expected_configuration:
        raise ProtocolFailure(
            f"running STATUS configuration is {actual_configuration}; "
            f"expected {expected_configuration}"
        )
    if status.stats_generation != stats_generation:
        raise ProtocolFailure(
            f"STATUS generation is {status.stats_generation}; "
            f"expected {stats_generation}"
        )
    if (
        status.adc_items_dropped
        or status.gpio_items_dropped
        or status.parser_errors
        or status.transport_errors
    ):
        raise ProtocolFailure(
            "running STATUS reports errors: "
            f"adc_items_dropped={status.adc_items_dropped}, "
            f"gpio_items_dropped={status.gpio_items_dropped}, "
            f"parser_errors={status.parser_errors}, "
            f"transport_errors={status.transport_errors}"
        )
    adc_before, gpio_before = received_frames_before_request
    if status.adc_frames_emitted < adc_before:
        raise ProtocolFailure("firmware ADC counter trails received frames")
    if status.gpio_frames_emitted < gpio_before:
        raise ProtocolFailure("firmware GPIO counter trails received frames")


def percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def latency_record(samples: list[float]) -> dict[str, object]:
    return {
        "count": len(samples),
        "maximum": max(samples, default=0.0),
        "p50": percentile(samples, 0.50),
        "p95": percentile(samples, 0.95),
        "p99": percentile(samples, 0.99),
        "samples": samples,
    }


def _relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / expected


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolFailure(message)


def run_candidate_stream(
    link: SerialLink,
    checksum_algorithm: int,
    *,
    capture_seconds: float,
    status_interval_seconds: float,
) -> dict[str, object]:
    """Run one full-rate epoch and return a bounded machine-readable record."""

    _require(not link.parser.buffer, "parser retained bytes before candidate stream")
    parser_error_baseline = link.parser.errors
    parser_frames_baseline = link.parser.frames_decoded
    parser_discard_baseline = link.parser.bytes_discarded
    stale_baseline = link.stale_responses
    crc32c_combined_baseline = link.parser.synthetic_crc32c_combined_checks
    crc32c_full_baseline = link.parser.full_crc32c_data_checks
    link.parser.high_water_bytes = len(link.parser.buffer)
    control_latencies: dict[str, float] = {}

    requested = CONFIGURATION.pack(
        STREAM_BOTH,
        SOURCE_SYNTHETIC,
        checksum_algorithm,
        0,
        DATA_FRAME_BYTES,
    )
    configured_frame, latency = link.exchange(CONFIGURE_REQUEST, requested)
    control_latencies["configure"] = latency
    _require(
        decode_configuration(configured_frame, CONFIGURE_RESPONSE)
        == (STREAM_BOTH, SOURCE_SYNTHETIC, checksum_algorithm, DATA_FRAME_BYTES),
        "CONFIGURE response does not echo the selected checksum",
    )

    configured_status_frame, latency = link.exchange(GET_STATUS_REQUEST)
    control_latencies["configured_status"] = latency
    configured_status = decode_status(configured_status_frame)
    _require(
        (
            configured_status.device_state,
            configured_status.stream_mask,
            configured_status.source,
            configured_status.checksum,
            configured_status.data_frame_bytes,
        )
        == (
            STATE_CONFIGURED,
            STREAM_BOTH,
            SOURCE_SYNTHETIC,
            checksum_algorithm,
            DATA_FRAME_BYTES,
        ),
        "configured STATUS does not match the requested checksum",
    )

    configured_info_frame, latency = link.exchange(INFO_REQUEST)
    control_latencies["configured_info"] = latency
    configured_info = decode_info(configured_info_frame)
    _require(
        configured_info["device_state"] == STATE_CONFIGURED
        and configured_info["data_checksum_algorithm"] == checksum_algorithm,
        "configured INFO does not expose the selected checksum",
    )

    deferred_data: list[Frame] = []

    def defer_start_data(frame: Frame) -> None:
        maximum = math.ceil(SERIAL_READ_BYTES / DATA_FRAME_BYTES) + 1
        if len(deferred_data) >= maximum:
            raise ProtocolFailure(
                f"START boundary exceeded its {maximum}-frame deferred bound"
            )
        deferred_data.append(frame)

    start_frame, latency = link.exchange(START_REQUEST, on_data=defer_start_data)
    control_latencies["start"] = latency
    response_success(start_frame, START_RESPONSE)
    _require(1 <= start_frame.run_id <= 0xFFFFFFFF, "START run ID is invalid")
    _require(
        decode_configuration(start_frame, START_RESPONSE)
        == (STREAM_BOTH, SOURCE_SYNTHETIC, checksum_algorithm, DATA_FRAME_BYTES),
        "START response does not echo the selected checksum",
    )
    validator = SyntheticValidator(start_frame.run_id, checksum_algorithm)
    for frame in deferred_data:
        validator.accept(frame)

    active_started = time.monotonic()
    capture_deadline = active_started + capture_seconds
    next_status_at = active_started
    status_latencies: list[float] = []
    stats_generation: int | None = None
    while time.monotonic() < capture_deadline:
        if time.monotonic() >= next_status_at:
            receive_floor = (validator.adc.frames, validator.gpio.frames)
            status_frame, status_latency = link.exchange(
                GET_STATUS_REQUEST,
                on_data=validator.accept,
            )
            status = decode_status(status_frame)
            if stats_generation is None:
                stats_generation = status.stats_generation
                expected_generation = (
                    configured_status.stats_generation + 1
                ) & 0xFFFFFFFF
                expected_generation = expected_generation or 1
                _require(
                    stats_generation == expected_generation,
                    "START did not advance statistics generation",
                )
            validate_running_status(
                status,
                status_frame,
                validator,
                stats_generation,
                receive_floor,
            )
            status_latencies.append(status_latency)
            next_status_at += status_interval_seconds
            while next_status_at <= time.monotonic():
                next_status_at += status_interval_seconds
            continue
        link.pump_once(validator.accept)

    capture_elapsed = time.monotonic() - active_started
    stop_frame, latency = link.exchange(STOP_REQUEST, on_data=validator.accept)
    control_latencies["stop"] = latency
    response_success(stop_frame, STOP_RESPONSE)
    _require(stop_frame.run_id == validator.run_id, "STOP run ID changed")
    _require(stop_frame.payload[4] == STATE_IDLE, "STOP did not return IDLE")
    link.drain_until_quiet(validator.accept)

    final_frame, latency = link.exchange(
        GET_STATUS_REQUEST,
        on_data=validator.accept,
    )
    control_latencies["final_status"] = latency
    final_status = decode_status(final_frame)
    _require(stats_generation is not None, "stream completed without STATUS sample")
    _require(final_status.device_state == STATE_IDLE, "final STATUS is not IDLE")
    _require(final_frame.run_id == validator.run_id, "final STATUS run ID changed")
    _require(
        final_status.stats_generation == stats_generation,
        "final statistics generation changed",
    )
    _require(
        final_status.adc_frames_emitted == validator.adc.frames,
        "final firmware ADC count does not match received frames",
    )
    _require(
        final_status.gpio_frames_emitted == validator.gpio.frames,
        "final firmware GPIO count does not match received frames",
    )
    _require(
        not (
            final_status.adc_items_dropped
            or final_status.gpio_items_dropped
            or final_status.parser_errors
            or final_status.transport_errors
        ),
        "final STATUS reports a drop/parser/transport error",
    )
    _require(
        validator.adc.frames > 0 and validator.gpio.frames > 0,
        "stream did not deliver both sources",
    )
    _require(
        abs(validator.adc.frames - validator.gpio.frames) <= 1,
        "ADC/GPIO frame counts are not balanced",
    )
    _require(
        validator.adc.items == validator.adc.frames * ADC_PAIRS_PER_FRAME,
        "ADC item accounting disagrees",
    )
    _require(
        validator.gpio.items == validator.gpio.frames * GPIO_SAMPLES_PER_FRAME,
        "GPIO item accounting disagrees",
    )

    adc_rate = validator.adc.payload_bytes / capture_elapsed
    gpio_rate = validator.gpio.payload_bytes / capture_elapsed
    combined_payload_bytes = validator.adc.payload_bytes + validator.gpio.payload_bytes
    combined_framed_bytes = validator.adc.framed_bytes + validator.gpio.framed_bytes
    combined_payload_rate = combined_payload_bytes / capture_elapsed
    combined_framed_rate = combined_framed_bytes / capture_elapsed
    rate_checks = (
        (adc_rate, TARGET_ADC_PAYLOAD_BYTES_PER_SECOND, "ADC payload"),
        (gpio_rate, TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND, "GPIO payload"),
        (
            combined_payload_rate,
            TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND,
            "combined payload",
        ),
        (
            combined_framed_rate,
            TARGET_COMBINED_FRAMED_BYTES_PER_SECOND,
            "combined framed",
        ),
    )
    for actual, target, name in rate_checks:
        _require(
            _relative_error(actual, target) <= RATE_TOLERANCE_FRACTION,
            f"{name} rate {actual} is outside {RATE_TOLERANCE_FRACTION:.3%} "
            f"of {target}",
        )

    minimum_status_samples = max(1, int(capture_seconds / status_interval_seconds))
    _require(
        len(status_latencies) >= minimum_status_samples,
        f"received {len(status_latencies)} STATUS samples; "
        f"expected at least {minimum_status_samples}",
    )
    _require(
        percentile(status_latencies, 0.99) <= STATUS_P99_LIMIT_SECONDS,
        "STATUS p99 latency exceeded its bound",
    )
    _require(
        max(status_latencies) <= STATUS_MAXIMUM_LIMIT_SECONDS,
        "STATUS maximum latency exceeded its bound",
    )
    for name, command_latency in control_latencies.items():
        _require(
            command_latency <= COMMAND_DEADLINE_SECONDS,
            f"{name} command latency exceeded its deadline",
        )

    parser_errors = link.parser.errors - parser_error_baseline
    parser_frames = link.parser.frames_decoded - parser_frames_baseline
    parser_discarded = link.parser.bytes_discarded - parser_discard_baseline
    stale_responses = link.stale_responses - stale_baseline
    data_frames = validator.adc.frames + validator.gpio.frames
    crc32c_combined_checks = (
        link.parser.synthetic_crc32c_combined_checks - crc32c_combined_baseline
    )
    crc32c_full_checks = link.parser.full_crc32c_data_checks - crc32c_full_baseline
    reader_queue = link.reader_queue_metrics()
    _require(parser_errors == 0, "host parser reported an error during stream")
    _require(parser_discarded == 0, "host parser discarded bytes during stream")
    _require(stale_responses == 0, "host observed a stale response during stream")
    _require(not link.parser.buffer, "host parser retained bytes after stream")
    _require(
        parser_frames >= data_frames,
        "not every received data trailer was validated",
    )
    if checksum_algorithm == CHECKSUM_CRC32C:
        _require(
            crc32c_combined_checks == data_frames and crc32c_full_checks == 0,
            "not every CRC-32C data trailer used the bounded synthetic validator",
        )
    if reader_queue["enabled"]:
        _require(
            int(reader_queue["high_water_bytes"])
            <= int(reader_queue["capacity_bytes"]),
            "host serial reader exceeded its fixed byte capacity",
        )
        _require(
            int(reader_queue["final_bytes"]) == 0,
            "host serial reader retained bytes after stream",
        )

    return {
        "capture_elapsed_seconds": capture_elapsed,
        "checksum_algorithm": CHECKSUM_NAMES[checksum_algorithm],
        "checksum_algorithm_id": checksum_algorithm,
        "errors": {
            "firmware_adc_items_dropped": final_status.adc_items_dropped,
            "firmware_gpio_items_dropped": final_status.gpio_items_dropped,
            "firmware_parser_errors": final_status.parser_errors,
            "firmware_transport_errors": final_status.transport_errors,
            "host_parser_errors": parser_errors,
            "host_stale_responses": stale_responses,
            "host_stream_bytes_discarded": parser_discarded,
        },
        "frames": {
            "adc": validator.adc.frames,
            "gpio": validator.gpio.frames,
            "trailers_validated_including_control": parser_frames,
        },
        "items": {
            "adc_pairs": validator.adc.items,
            "gpio_samples": validator.gpio.items,
        },
        "checksum_validation": {
            "crc32c_full_data_checks": crc32c_full_checks,
            "crc32c_synthetic_combined_checks": crc32c_combined_checks,
            "synthetic_crc32c_payload_cache_entries": len(
                SYNTHETIC_CRC32C_PAYLOAD_CHECKSUMS
            ),
        },
        "latency_seconds": {
            "commands": control_latencies,
            "status": latency_record(status_latencies),
        },
        "maximum_receive_gap_seconds": validator.maximum_receive_gap_seconds,
        "queue": {
            "firmware_internal_depth_available_in_protocol_v1": False,
            "firmware_packet_capacity_frames": 106,
            "firmware_queue_exhaustion_observed": False,
            "host_parser_buffered_bytes_final": len(link.parser.buffer),
            "host_parser_high_water_bytes": link.parser.high_water_bytes,
            "host_serial_reader": reader_queue,
            "maximum_start_boundary_deferred_frames": len(deferred_data),
        },
        "run_id": validator.run_id,
        "stats_generation": stats_generation,
        "throughput": {
            "adc_payload_bytes_per_second": adc_rate,
            "combined_framed_bytes": combined_framed_bytes,
            "combined_framed_bytes_per_second": combined_framed_rate,
            "combined_payload_bytes": combined_payload_bytes,
            "combined_payload_bytes_per_second": combined_payload_rate,
            "gpio_payload_bytes_per_second": gpio_rate,
            "rate_tolerance_fraction": RATE_TOLERANCE_FRACTION,
            "target_combined_framed_bytes_per_second": (
                TARGET_COMBINED_FRAMED_BYTES_PER_SECOND
            ),
            "target_combined_payload_bytes_per_second": (
                TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND
            ),
        },
    }


def _find_measurement(
    measurements: tuple[BenchmarkMeasurement, ...],
    *,
    vector: int,
    memory_region: int,
    cache_state: int,
) -> BenchmarkMeasurement:
    matches = [
        measurement
        for measurement in measurements
        if measurement.selection.vector == vector
        and measurement.selection.memory_region == memory_region
        and measurement.selection.cache_state == cache_state
    ]
    if len(matches) != 1:
        raise ProtocolFailure("benchmark matrix lacks one required representative")
    return matches[0]


def candidate_record(
    checksum_algorithm: int,
    measurements: tuple[BenchmarkMeasurement, ...],
    benchmark_latencies: list[float],
    stream: dict[str, object],
) -> dict[str, object]:
    representative = _find_measurement(
        measurements,
        vector=VECTOR_FRAME_COVERAGE,
        memory_region=MEMORY_DTCM_PACKET,
        cache_state=CACHE_HOT_OR_NATIVE,
    )
    cold = _find_measurement(
        measurements,
        vector=VECTOR_FRAME_COVERAGE,
        memory_region=MEMORY_OCRAM_DMA,
        cache_state=CACHE_COLD_INVALIDATED,
    )
    representative_latency = benchmark_latencies[measurements.index(representative)]
    cold_latency = benchmark_latencies[measurements.index(cold)]
    resources = {
        "benchmark_working_ram_bytes": representative.working_ram_bytes,
        "implementation_code_bytes": representative.implementation_code_bytes,
        "table_flash_bytes": representative.table_bytes,
        "total_reported_flash_bytes": (
            representative.implementation_code_bytes + representative.table_bytes
        ),
    }
    return {
        "benchmark": {
            "cold_ocram_frame": measurement_record(cold, cold_latency),
            "command_latency_seconds": latency_record(benchmark_latencies),
            "profile_count": len(measurements),
            "representative_hot_dtcm_frame": measurement_record(
                representative,
                representative_latency,
            ),
        },
        "checksum_algorithm": CHECKSUM_NAMES[checksum_algorithm],
        "checksum_algorithm_id": checksum_algorithm,
        "errors": stream["errors"],
        "latency_seconds": stream["latency_seconds"],
        "queue": stream["queue"],
        "resources": resources,
        "result": "PASS",
        "stream": stream,
        "throughput": stream["throughput"],
    }


def run_campaign(
    port: SerialPort,
    *,
    capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
    status_interval_seconds: float = DEFAULT_STATUS_INTERVAL_SECONDS,
    benchmark_batch_count: int = DEFAULT_BENCHMARK_BATCH_COUNT,
    benchmark_iterations_per_batch: int = (DEFAULT_BENCHMARK_ITERATIONS_PER_BATCH),
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
    selected_checksum_algorithm: int | None = None,
) -> dict[str, object]:
    """Benchmark and stream the selected advertised candidates sequentially."""

    if (
        not math.isfinite(capture_seconds)
        or not 0 < capture_seconds <= MAX_CAPTURE_SECONDS
    ):
        raise ValueError(
            f"capture_seconds must be positive, finite, and <= {MAX_CAPTURE_SECONDS}"
        )
    if (
        not math.isfinite(status_interval_seconds)
        or status_interval_seconds < MIN_STATUS_INTERVAL_SECONDS
    ):
        raise ValueError(
            "status_interval_seconds must be finite and >= "
            f"{MIN_STATUS_INTERVAL_SECONDS}"
        )
    if math.ceil(capture_seconds / status_interval_seconds) > MAX_STATUS_SAMPLES:
        raise ValueError(
            f"capture requests more than {MAX_STATUS_SAMPLES} STATUS samples"
        )
    if not 1 <= benchmark_batch_count <= MAX_BENCHMARK_BATCH_COUNT:
        raise ValueError("benchmark_batch_count is outside its bound")
    if not 1 <= benchmark_iterations_per_batch <= MAX_BENCHMARK_ITERATIONS_PER_BATCH:
        raise ValueError("benchmark_iterations_per_batch is outside its bound")

    vectors = validate_independent_vectors()
    for record in vectors:
        emit_event("independent_vector", **record)

    link = SerialLink(port)
    candidate_results: list[dict[str, object]] = []
    total_benchmark_profiles = 0
    completed = False
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        synchronized_info = synchronize(link)
        info_frame, info_latency = link.exchange(INFO_REQUEST)
        info = decode_info(info_frame)
        if stable_identity(info) != stable_identity(synchronized_info):
            raise ProtocolFailure("INFO identity changed after synchronization")
        candidates = validate_info(
            info,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
        if (
            selected_checksum_algorithm is not None
            and selected_checksum_algorithm not in candidates
        ):
            raise ProtocolFailure(
                "selected checksum algorithm is not advertised by the target"
            )
        campaign_candidates = (
            candidates
            if selected_checksum_algorithm is None
            else (selected_checksum_algorithm,)
        )
        if info_latency > COMMAND_DEADLINE_SECONDS:
            raise ProtocolFailure("INFO command latency exceeded its deadline")
        emit_event(
            "identity",
            advertised_candidates=[CHECKSUM_NAMES[value] for value in candidates],
            advertised_candidate_ids=list(candidates),
            build_id=info["build_id"],
            campaign_candidates=[
                CHECKSUM_NAMES[value] for value in campaign_candidates
            ],
            campaign_candidate_ids=list(campaign_candidates),
            firmware_version=info["firmware_version"],
            hardware_serial=info["hardware_serial"],
            info_latency_seconds=info_latency,
            protocol_version=info["protocol_version"],
        )

        for checksum_algorithm in campaign_candidates:
            emit_event(
                "candidate_start",
                checksum_algorithm=CHECKSUM_NAMES[checksum_algorithm],
                checksum_algorithm_id=checksum_algorithm,
            )
            measurements, benchmark_latencies = run_device_benchmarks(
                link,
                checksum_algorithm,
                batch_count=benchmark_batch_count,
                iterations_per_batch=benchmark_iterations_per_batch,
            )
            total_benchmark_profiles += len(measurements)
            stream = run_candidate_stream(
                link,
                checksum_algorithm,
                capture_seconds=capture_seconds,
                status_interval_seconds=status_interval_seconds,
            )
            result = candidate_record(
                checksum_algorithm,
                measurements,
                benchmark_latencies,
                stream,
            )
            candidate_results.append(result)
            print(
                "CANDIDATE " + json.dumps(result, sort_keys=True, separators=(",", ":"))
            )
        final_frame, final_latency = link.exchange(GET_STATUS_REQUEST)
        final_status = decode_status(final_frame)
        if final_status.device_state != STATE_IDLE:
            raise ProtocolFailure("campaign final state is not IDLE")
        if link.parser.errors:
            raise ProtocolFailure("campaign parser accumulated an error")
        if link.stale_responses:
            raise ProtocolFailure("campaign observed a stale response")
        completed = True
        return {
            "advertised_candidate_count": len(candidates),
            "advertised_candidate_ids": list(candidates),
            "benchmark_profile_count": total_benchmark_profiles,
            "build_id": info["build_id"],
            "campaign_candidate_ids": list(campaign_candidates),
            "candidate_count": len(candidate_results),
            "candidates": candidate_results,
            "final_state": final_status.device_state,
            "final_status_latency_seconds": final_latency,
            "hardware_serial": info["hardware_serial"],
            "independent_vector_count": len(vectors),
            "result": "PASS",
        }
    finally:
        if not completed:
            emit_event(
                "campaign_failure_diagnostics",
                crc32c_full_data_checks=link.parser.full_crc32c_data_checks,
                crc32c_synthetic_combined_checks=(
                    link.parser.synthetic_crc32c_combined_checks
                ),
                maximum_serial_read_bytes=link.maximum_read_bytes,
                parser_buffered_bytes=len(link.parser.buffer),
                parser_errors=link.parser.errors,
                parser_frames_decoded=link.parser.frames_decoded,
                reader_queue=link.reader_queue_metrics(),
            )
            try:
                cleanup, cleanup_latency = link.exchange(
                    STOP_REQUEST,
                    timeout=COMMAND_DEADLINE_SECONDS,
                    on_data=lambda _frame: None,
                )
                emit_event(
                    "cleanup_stop",
                    latency_seconds=cleanup_latency,
                    state=(cleanup.payload[4] if len(cleanup.payload) > 4 else None),
                )
            except Exception as error:  # noqa: BLE001 - best-effort diagnostics
                emit_event(
                    "cleanup_stop_failed",
                    error=f"{type(error).__name__}: {error}",
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


def _bounded_int_environment(
    name: str,
    default: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 0)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _optional_uint32_environment(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        value = int(raw, 0)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be a nonzero uint32")
    return value


def _optional_checksum_environment(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    normalized = raw.strip().upper().replace("-", "_")
    by_name = {value: key for key, value in CHECKSUM_NAMES.items()}
    if normalized in by_name:
        return by_name[normalized]
    try:
        value = int(normalized, 0)
    except ValueError as error:
        choices = ", ".join(CHECKSUM_NAMES.values())
        raise ValueError(
            f"{name} must be an algorithm ID or one of {choices}"
        ) from error
    if value not in SUPPORTED_CHECKSUMS:
        raise ValueError(f"{name} identifies an unsupported checksum algorithm")
    return value


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        emit_event("configuration_error", error="SERIAL_PORT is required")
        return 2
    try:
        capture_seconds = _positive_float_environment(
            "CHECKSUM_CAPTURE_SECONDS",
            DEFAULT_CAPTURE_SECONDS,
        )
        status_interval_seconds = _positive_float_environment(
            "CHECKSUM_STATUS_INTERVAL_SECONDS",
            DEFAULT_STATUS_INTERVAL_SECONDS,
        )
        benchmark_batch_count = _bounded_int_environment(
            "CHECKSUM_BENCHMARK_BATCH_COUNT",
            DEFAULT_BENCHMARK_BATCH_COUNT,
            MAX_BENCHMARK_BATCH_COUNT,
        )
        benchmark_iterations_per_batch = _bounded_int_environment(
            "CHECKSUM_BENCHMARK_ITERATIONS_PER_BATCH",
            DEFAULT_BENCHMARK_ITERATIONS_PER_BATCH,
            MAX_BENCHMARK_ITERATIONS_PER_BATCH,
        )
        expected_hardware_serial = _optional_uint32_environment(
            "EXPECTED_HARDWARE_SERIAL"
        )
        selected_checksum_algorithm = _optional_checksum_environment(
            "CHECKSUM_CAMPAIGN_ALGORITHM"
        )
    except ValueError as error:
        emit_event("configuration_error", error=str(error))
        return 2

    expected_build_id = os.environ.get("EXPECTED_BUILD_ID")
    emit_event(
        "program_start",
        baud=BAUD_RATE,
        benchmark_batch_count=benchmark_batch_count,
        benchmark_iterations_per_batch=benchmark_iterations_per_batch,
        capture_seconds_per_candidate=capture_seconds,
        checksum_campaign_algorithm=(
            CHECKSUM_NAMES[selected_checksum_algorithm]
            if selected_checksum_algorithm is not None
            else "ALL"
        ),
        port=port_name,
        protocol=PROTOCOL_VERSION,
        status_interval_seconds=status_interval_seconds,
        cyclic_gc_disabled_during_campaign=True,
        serial_reader_queue_bytes=SERIAL_READER_QUEUE_BYTES,
    )
    try:
        port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - retain rig-visible open failure
        emit_event("open_failed", error=f"{type(error).__name__}: {error}")
        return 2

    buffered_port = BufferedSerialPort(port)
    cyclic_gc_was_enabled = gc.isenabled()
    if cyclic_gc_was_enabled:
        gc.disable()
    try:
        try:
            summary = run_campaign(
                buffered_port,
                capture_seconds=capture_seconds,
                status_interval_seconds=status_interval_seconds,
                benchmark_batch_count=benchmark_batch_count,
                benchmark_iterations_per_batch=benchmark_iterations_per_batch,
                expected_build_id=expected_build_id,
                expected_hardware_serial=expected_hardware_serial,
                selected_checksum_algorithm=selected_checksum_algorithm,
            )
        except Exception as error:  # noqa: BLE001 - stdout is remote diagnosis
            message = f"{type(error).__name__}: {error}"
            emit_event("fatal", error=message)
            summary = {"failures": [message], "result": "FAIL"}
    finally:
        if cyclic_gc_was_enabled:
            gc.enable()
        buffered_port.close()
        port.close()
    print("SUMMARY " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
