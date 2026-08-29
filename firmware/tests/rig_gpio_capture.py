#!/usr/bin/env python3
"""Independent Phase 06 physical-GPIO hardware acceptance.

The remote rig uploads this file by itself to a network-disabled Python 3.13
container.  It intentionally embeds the protocol values it grades, uses only
the Python standard library plus pyserial, and never imports the project API or
generated constants.
"""

from __future__ import annotations

import json
import math
import os
import re
import resource
import struct
import sys
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

import serial

BAUD_RATE = 115_200
SERIAL_READ_TIMEOUT_SECONDS = 0.02
SERIAL_WRITE_TIMEOUT_SECONDS = 0.5
SERIAL_READ_BYTES = 64 * 1024
STARTUP_DRAIN_SECONDS = 0.25
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 0.5
DIAGNOSTIC_DEADLINE_SECONDS = 1.0
STOP_DRAIN_DEADLINE_SECONDS = 2.0
STOP_DRAIN_QUIET_SECONDS = 0.10
DEFAULT_CAPTURE_SECONDS = 10.0
DEFAULT_STATUS_INTERVAL_SECONDS = 0.25
MAX_CAPTURE_SECONDS = 3600.0
MIN_STATUS_INTERVAL_SECONDS = 0.01
MAX_STATUS_SAMPLES = 16_384
RATE_TOLERANCE_FRACTION = 0.01
STATUS_P99_LIMIT_SECONDS = 0.100
STATUS_MAXIMUM_LIMIT_SECONDS = 0.250
MAX_RSS_GROWTH_BYTES = 32 * 1024 * 1024
GPIO_PROCESSING_CPU_MAX_BASIS_POINTS = 5_000

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 1
HEADER_SIZE = 44
TRAILER_SIZE = 4
DATA_FRAME_BYTES = 4096
DATA_PAYLOAD_BYTES = 4048
MAX_CONTROL_FRAME_BYTES = 1280
MAX_FRAME_BYTES = DATA_FRAME_BYTES
CHECKSUM_ADLER32 = 1
CHECKSUM_CRC32C = 2
CHECKSUM_CRC32_ISO_HDLC = 3
BOOTSTRAP_CHECKSUM = CHECKSUM_ADLER32
DEFAULT_DATA_CHECKSUM = CHECKSUM_ADLER32
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
ADC_PAIRS_PER_FRAME = 1012
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4048
GPIO_PINS_BY_BIT = tuple(range(6, 14))
FRAME_COVERAGE_TICKS = GPIO_SAMPLES_PER_FRAME * GPIO_SAMPLE_PERIOD_TICKS

GPIO_CLOCK_PIT_HZ = 24_000_000
GPIO_CLOCK_DWT_HZ = 600_000_000
GPIO_CLOCK_MIN_RATE_HZ = 1_000
GPIO_CLOCK_MAX_RATE_HZ = GPIO_SAMPLE_RATE_HZ
GPIO_CLOCK_MIN_EVENT_COUNT = 32
GPIO_CLOCK_MAX_EVENT_COUNT = 8_192
GPIO_CLOCK_MAX_ELAPSED_CYCLES = 60_000_000
GPIO_CLOCK_DUPLICATE_GUARD_EVENTS = 16
GPIO_CLOCK_COUNT_TOLERANCE = 1
DEFAULT_LOW_RATE_HZ = 1_000
DEFAULT_LOW_RATE_EVENT_COUNT = 64
DEFAULT_PRODUCTION_EVENT_COUNT = 8_192

GPIO_PACKED_WIDTH_BITS = 8
GPIO_RAW_RING_DEPTH = 4
GPIO_RAW_SAMPLES_PER_BUFFER = 4048
GPIO_RAW_RING_BYTES = 64_768
GPIO_PACKED_RING_DEPTH = 4
GPIO_PACKED_RING_BYTES = 16_256
GPIO_PACKET_BUFFER_COUNT = 200
GPIO_PIT_CHANNEL = 0
GPIO_XBAR_INPUT = 56
GPIO_XBAR_OUTPUT = 0
GPIO_EDMA_CHANNEL = 2
GPIO_DMAMUX_SOURCE = 30
GPIO_EDMA_PRIORITY = 0
GPIO_XBAR_ACTIVE_EDGE = 1
GPIO2_CAPTURE_MASK = 0x00030C0F
GPIO2_BITS_BY_PACKED_BIT = (10, 17, 16, 11, 0, 2, 1, 3)
DMAMUX_ENABLE = 0x80000000
EDMA_CHANNEL_MASK = 1 << GPIO_EDMA_CHANNEL
DIAGNOSTIC_SOURCE_WORD = 0xA5C35A7E
TCD_32BIT_ATTRIBUTES = 0x0202
TCD_DREQ = 0x0008
PIT_MDIS = 0x00000002
CCM_PERCLK_MASK = 0x0000007F
CCM_PERCLK_24MHZ = 0x00000040
CCM_PIT_GATE_MASK = 0x00003000
CCM_XBAR_GATE_MASK = 0x00C00000
CCM_DMA_GATE_MASK = 0x000000C0

ADC_DATA = 0x01
GPIO_DATA = 0x02
INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
GPIO_CLOCK_DIAGNOSTIC_REQUEST = 0x18
GPIO_CAPTURE_DIAGNOSTIC_REQUEST = 0x19
INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
GPIO_CLOCK_DIAGNOSTIC_RESPONSE = 0x98
GPIO_CAPTURE_DIAGNOSTIC_RESPONSE = 0x99
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
CAPABILITY_ADC_STREAM = 1
CAPABILITY_GPIO_STREAM = 2
CAPABILITY_HARDWARE_SOURCE = 4
CAPABILITY_SYNTHETIC_SOURCE = 8
CAPABILITY_RESET_STATS = 16
CAPABILITY_PING = 32
CAPABILITY_CHECKSUM_BENCHMARK = 64
CAPABILITY_GPIO_CLOCK_DIAGNOSTIC = 128
CAPABILITY_GPIO_CAPTURE_DIAGNOSTIC = 256
EXPECTED_CAPABILITIES = 0x000001FF

GPIO_DIAGNOSTIC_NON_DRIVING = 0
GPIO_DIAGNOSTIC_SELF_DRIVEN_SWEEP = 1
GPIO_DIAGNOSTIC_FIXTURE_STIMULUS = 2
GPIO_DIAGNOSTIC_MODES = {
    GPIO_DIAGNOSTIC_NON_DRIVING: "NON_DRIVING_CAPTURE",
    GPIO_DIAGNOSTIC_SELF_DRIVEN_SWEEP: "SELF_DRIVEN_SWEEP",
    GPIO_DIAGNOSTIC_FIXTURE_STIMULUS: "FIXTURE_STIMULUS",
}
GPIO_DIAGNOSTIC_AVAILABLE = 1
GPIO_DIAGNOSTIC_DECLARATION_VALID = 2
GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED = 4
GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED = 8
GPIO_DIAGNOSTIC_DMA_CAPTURE_EXERCISED = 16
GPIO_DIAGNOSTIC_PACKED_OBSERVATION_EXERCISED = 32
GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED = 64
GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED = 128
GPIO_DIAGNOSTIC_FINAL_INPUT_SAFE = 256
KNOWN_GPIO_DIAGNOSTIC_FLAGS = 0x000001FF
KNOWN_GPIO_CAPTURE_ERROR_MASK = 0x0000FFFF
NON_DRIVING_ANALYSIS_SAMPLES = 256
SWEEP_VALUE_COUNT = 256
SWEEP_SAMPLES_PER_VALUE = 8

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
TRAILER = struct.Struct("<I")
CONFIGURATION = struct.Struct("<BBBBI")
RESPONSE_PREFIX = struct.Struct("<BBH")
GPIO_CLOCK_REQUEST = struct.Struct("<IHH")

REQUEST_RESPONSE_KIND = {
    INFO_REQUEST: INFO_RESPONSE,
    CONFIGURE_REQUEST: CONFIGURE_RESPONSE,
    START_REQUEST: START_RESPONSE,
    GET_STATUS_REQUEST: GET_STATUS_RESPONSE,
    STOP_REQUEST: STOP_RESPONSE,
    RESET_STATS_REQUEST: RESET_STATS_RESPONSE,
    GPIO_CLOCK_DIAGNOSTIC_REQUEST: GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
    GPIO_CAPTURE_DIAGNOSTIC_REQUEST: GPIO_CAPTURE_DIAGNOSTIC_RESPONSE,
}
REQUEST_PAYLOAD_SIZE = {
    INFO_REQUEST: 0,
    CONFIGURE_REQUEST: 8,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
    GPIO_CLOCK_DIAGNOSTIC_REQUEST: 8,
    GPIO_CAPTURE_DIAGNOSTIC_REQUEST: 0,
}
SUCCESS_PAYLOAD_SIZE = {
    INFO_RESPONSE: 376,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 1228,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    GPIO_CLOCK_DIAGNOSTIC_RESPONSE: 140,
    GPIO_CAPTURE_DIAGNOSTIC_RESPONSE: 144,
    ERROR_RESPONSE: 8,
}
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE)


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


def compute_checksum_fallback(
    data: bytes | bytearray | memoryview,
    algorithm: int,
) -> int:
    """Dependency-free reference checksum for each protocol-v1 algorithm."""

    if algorithm == CHECKSUM_ADLER32:
        return _pure_adler32(data)
    if algorithm == CHECKSUM_CRC32C:
        return _pure_reflected_crc32(data, CRC32C_TABLE)
    if algorithm == CHECKSUM_CRC32_ISO_HDLC:
        return _pure_reflected_crc32(data, CRC32_ISO_HDLC_TABLE)
    raise ProtocolFailure(f"host lacks checksum support for algorithm {algorithm}")


def compute_checksum(
    data: bytes | bytearray | memoryview,
    algorithm: int,
) -> int:
    """Compute the exact named wire checksum without polynomial substitution."""

    if algorithm == CHECKSUM_ADLER32:
        return zlib.adler32(data, 1) & 0xFFFFFFFF
    if algorithm == CHECKSUM_CRC32C:
        return compute_checksum_fallback(data, algorithm)
    if algorithm == CHECKSUM_CRC32_ISO_HDLC:
        return zlib.crc32(data, 0) & 0xFFFFFFFF
    raise ProtocolFailure(f"host lacks checksum support for algorithm {algorithm}")


class SerialPort(Protocol):
    """The narrow pyserial surface used by this self-contained program."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Frame:
    """One independently checksum- and structure-validated wire frame."""

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
    """Every protocol-v1 STATUS field used by the physical GPIO gate."""

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
    gpio_samples_captured: int
    gpio_samples_packed: int
    gpio_samples_framed: int
    gpio_samples_transmitted: int
    gpio_raw_samples_lost: int
    gpio_packer_samples_dropped: int
    gpio_raw_ring_overruns: int
    gpio_dma_major_loops: int
    gpio_raw_ready_depth: int
    gpio_raw_ready_high_water: int
    gpio_packed_ready_depth: int
    gpio_packed_ready_high_water: int
    packet_ready_depth: int
    packet_transmit_depth: int
    packet_owned_high_water: int
    gpio_processing_cpu_basis_points: int
    gpio_hardware_errors: int
    gpio_raw_invariant_errors: int
    gpio_packer_source_errors: int
    gpio_packer_pipeline_errors: int
    gpio_packer_chronology_errors: int
    gpio_resource_conflicts: int
    gpio_start_errors: int
    gpio_stop_errors: int
    gpio_stale_dma_completions: int

    def monotonic_counters(self) -> tuple[int, ...]:
        return (
            self.adc_frames_emitted,
            self.gpio_frames_emitted,
            self.adc_items_dropped,
            self.gpio_items_dropped,
            self.parser_errors,
            self.transport_errors,
            self.gpio_samples_captured,
            self.gpio_samples_packed,
            self.gpio_samples_framed,
            self.gpio_samples_transmitted,
            self.gpio_raw_samples_lost,
            self.gpio_packer_samples_dropped,
            self.gpio_raw_ring_overruns,
            self.gpio_dma_major_loops,
            self.gpio_hardware_errors,
            self.gpio_raw_invariant_errors,
            self.gpio_packer_source_errors,
            self.gpio_packer_pipeline_errors,
            self.gpio_packer_chronology_errors,
            self.gpio_resource_conflicts,
            self.gpio_start_errors,
            self.gpio_stop_errors,
            self.gpio_stale_dma_completions,
        )


@dataclass
class StreamTotals:
    expected_sequence: int = 0
    expected_ticks: int = 0
    frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0


@dataclass(frozen=True)
class AcceptanceResult:
    evidence: Evidence
    external_stimulus_exercised: bool
    mapping_mode: str


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
        if frame.kind == INFO_RESPONSE:
            if (
                payload[1]
                or payload[61]
                or any(payload[118:120])
                or payload[127]
                or any(payload[154:156])
                or any(payload[334:336])
            ):
                raise ProtocolFailure("INFO reserved fields are nonzero")
        elif frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            if payload[1] or payload[7]:
                raise ProtocolFailure(
                    "configuration response reserved field is nonzero"
                )
        elif frame.kind == GET_STATUS_RESPONSE:
            if payload[1]:
                raise ProtocolFailure("STATUS reserved field is nonzero")
            if _u16(payload, 134) > 10_000:
                raise ProtocolFailure("STATUS GPIO CPU measurement exceeds 100%")
        elif frame.kind == STOP_RESPONSE:
            if payload[1] or any(payload[5:]):
                raise ProtocolFailure("STOP reserved fields are nonzero")
        elif frame.kind == RESET_STATS_RESPONSE:
            if payload[1]:
                raise ProtocolFailure("RESET_STATS reserved field is nonzero")
        elif frame.kind == GPIO_CLOCK_DIAGNOSTIC_RESPONSE:
            if payload[1]:
                raise ProtocolFailure("clock diagnostic reserved field is nonzero")
        elif frame.kind == GPIO_CAPTURE_DIAGNOSTIC_RESPONSE:
            if payload[1] or any(payload[70:72]) or payload[139]:
                raise ProtocolFailure("capture diagnostic reserved fields are nonzero")
        elif frame.kind == ERROR_RESPONSE and (payload[1] or any(payload[6:])):
            raise ProtocolFailure("generic error reserved fields are nonzero")

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
                raise DeadlineExpired(
                    "post-STOP data did not drain before its deadline"
                )
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


class Evidence:
    """Machine-readable expected-versus-actual checks for remote grading."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.check_count = 0

    def check(self, name: str, expected: object, actual: object, passed: bool) -> None:
        self.check_count += 1
        record = {
            "actual": actual,
            "expected": expected,
            "name": name,
            "pass": bool(passed),
        }
        print("METRIC " + json.dumps(record, sort_keys=True, separators=(",", ":")))
        if not passed:
            self.failures.append(f"{name}: expected {expected!r}, got {actual!r}")

    def equal(self, name: str, expected: object, actual: object) -> None:
        self.check(name, expected, actual, actual == expected)


def emit_event(name: str, **fields: object) -> None:
    """Print one machine-readable lifecycle event."""

    print(
        "EVENT "
        + json.dumps({"event": name, **fields}, sort_keys=True, separators=(",", ":"))
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


def _u16(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<H", payload, offset)[0]


def _u32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<I", payload, offset)[0]


def _u64(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", payload, offset)[0]


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
        "supported_checksum_mask": _u32(payload, 8),
        "capability_bits": _u32(payload, 12),
        "timestamp_hz": _u32(payload, 16),
        "data_frame_bytes": _u32(payload, 20),
        "max_control_frame_bytes": _u32(payload, 24),
        "adc_pair_rate_hz": _u32(payload, 28),
        "gpio_sample_rate_hz": _u32(payload, 32),
        "adc_pair_period_ticks": _u16(payload, 36),
        "adc1_phase_ticks": _u16(payload, 38),
        "gpio_sample_period_ticks": _u16(payload, 40),
        "adc_resolution_bits": payload[42],
        "adc_container_bytes": payload[43],
        "gpio_pin_count": payload[44],
        "data_checksum_algorithm": payload[45],
        "gpio_pin_map": tuple(payload[46:54]),
        "hardware_serial": _u32(payload, 54),
        "firmware_version": tuple(payload[58:61]),
        "board_id": _u16(payload, 62),
        "mcu_id": _u16(payload, 64),
        "build_id": build_id,
        "gpio_packed_width_bits": payload[98],
        "gpio_raw_ring_depth": payload[99],
        "gpio_packed_ring_depth": payload[100],
        "gpio_capture_diagnostic_mode": payload[101],
        "gpio_capture_diagnostic_flags": _u16(payload, 102),
        "gpio_raw_samples_per_buffer": _u32(payload, 104),
        "gpio_raw_ring_bytes": _u32(payload, 108),
        "gpio_packed_ring_bytes": _u32(payload, 112),
        "gpio_packet_buffer_count": _u16(payload, 116),
        "gpio_pit_channel": payload[120],
        "gpio_xbar_input": payload[121],
        "gpio_xbar_output": payload[122],
        "gpio_edma_channel": payload[123],
        "gpio_dmamux_source": payload[124],
        "gpio_edma_priority": payload[125],
        "gpio_xbar_active_edge": payload[126],
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
        data_frame_bytes=_u32(payload, 8),
        adc_frames_emitted=_u64(payload, 12),
        gpio_frames_emitted=_u64(payload, 20),
        adc_items_dropped=_u64(payload, 28),
        gpio_items_dropped=_u64(payload, 36),
        parser_errors=_u32(payload, 44),
        transport_errors=_u32(payload, 48),
        stats_generation=_u32(payload, 52),
        gpio_samples_captured=_u64(payload, 56),
        gpio_samples_packed=_u64(payload, 64),
        gpio_samples_framed=_u64(payload, 72),
        gpio_samples_transmitted=_u64(payload, 80),
        gpio_raw_samples_lost=_u64(payload, 88),
        gpio_packer_samples_dropped=_u64(payload, 96),
        gpio_raw_ring_overruns=_u64(payload, 104),
        gpio_dma_major_loops=_u64(payload, 112),
        gpio_raw_ready_depth=_u16(payload, 120),
        gpio_raw_ready_high_water=_u16(payload, 122),
        gpio_packed_ready_depth=_u16(payload, 124),
        gpio_packed_ready_high_water=_u16(payload, 126),
        packet_ready_depth=_u16(payload, 128),
        packet_transmit_depth=_u16(payload, 130),
        packet_owned_high_water=_u16(payload, 132),
        gpio_processing_cpu_basis_points=_u16(payload, 134),
        gpio_hardware_errors=_u32(payload, 136),
        gpio_raw_invariant_errors=_u32(payload, 140),
        gpio_packer_source_errors=_u32(payload, 144),
        gpio_packer_pipeline_errors=_u32(payload, 148),
        gpio_packer_chronology_errors=_u32(payload, 152),
        gpio_resource_conflicts=_u32(payload, 156),
        gpio_start_errors=_u32(payload, 160),
        gpio_stop_errors=_u32(payload, 164),
        gpio_stale_dma_completions=_u32(payload, 168),
    )


CLOCK_U32_FIELDS = {
    "configured_rate_hz": 4,
    "production_rate_hz": 8,
    "pit_clock_hz": 12,
    "pit_load_value": 16,
    "requested_event_count": 20,
    "scheduled_event_count": 24,
    "dma_sample_count": 28,
    "dwt_counter_hz": 32,
    "dwt_elapsed_cycles": 36,
    "hardware_error_flags": 40,
    "ccm_cscmr1_configured": 44,
    "ccm_ccgr1_configured": 48,
    "ccm_ccgr2_configured": 52,
    "ccm_ccgr5_configured": 56,
    "pit_mcr_configured": 60,
    "pit_ldval_configured": 64,
    "pit_cval_final": 68,
    "pit_tctrl_configured": 72,
    "pit_tflg_final": 76,
    "dmamux_chcfg_configured": 84,
    "dma_cr_configured": 88,
    "dma_es_final": 92,
    "dma_erq_configured": 96,
    "dma_err_final": 100,
    "dma_hrs_final": 104,
    "tcd_saddr": 108,
    "tcd_daddr": 112,
    "tcd_nbytes": 116,
    "last_sample_word": 120,
}
CLOCK_U16_FIELDS = {
    "xbar_sel_configured": 80,
    "xbar_ctrl_configured": 82,
    "tcd_citer_final": 124,
    "tcd_biter": 126,
    "tcd_csr_final": 128,
    "tcd_attr": 130,
    "tcd_soff": 138,
}
CLOCK_U8_FIELDS = {
    "pit_channel": 132,
    "xbar_input": 133,
    "xbar_output": 134,
    "edma_channel": 135,
    "dmamux_source": 136,
    "edma_priority": 137,
}


def decode_clock_diagnostic(frame: Frame) -> dict[str, int]:
    response_success(frame, GPIO_CLOCK_DIAGNOSTIC_RESPONSE)
    payload = frame.payload
    result = {name: _u32(payload, offset) for name, offset in CLOCK_U32_FIELDS.items()}
    result.update(
        {name: _u16(payload, offset) for name, offset in CLOCK_U16_FIELDS.items()}
    )
    result.update({name: payload[offset] for name, offset in CLOCK_U8_FIELDS.items()})
    return result


CAPTURE_U32_FIELDS = {
    "fixture_identity": 8,
    "stimulus_identity": 12,
    "hardware_error_flags": 16,
    "diagnostic_flags": 20,
    "dwt_counter_hz": 24,
    "dwt_elapsed_cycles": 28,
    "complete_samples_retained": 40,
    "samples_analyzed": 44,
    "stopped_partial_samples": 48,
    "raw_word_and": 52,
    "raw_word_or": 56,
    "observed_transitions": 60,
    "gpr27_before": 76,
    "gpr27_configured": 80,
    "gpr27_after": 84,
    "gpio2_gdir_before": 88,
    "gpio2_gdir_configured": 92,
    "gpio2_gdir_after": 96,
    "gpio2_psr_before": 100,
    "gpio2_psr_configured": 104,
    "gpio2_psr_after": 108,
    "pit_ldval_configured": 112,
    "pit_tctrl_configured": 116,
    "dmamux_chcfg_configured": 120,
    "dma_erq_configured": 124,
    "dma_err_final": 128,
    "analysis_sample_limit": 140,
}
CAPTURE_U16_FIELDS = {
    "mapping_values_checked": 64,
    "mapping_failures": 66,
    "unstable_samples": 68,
    "tcd_citer_configured": 132,
    "tcd_biter_configured": 134,
    "tcd_csr_configured": 136,
}
CAPTURE_U8_FIELDS = {
    "mode": 4,
    "metadata_kind": 5,
    "drive_safety": 6,
    "stimulus_kind": 7,
    "packed_value_and": 72,
    "packed_value_or": 73,
    "first_packed_value": 74,
    "last_packed_value": 75,
    "edma_priority_configured": 138,
}


def decode_capture_diagnostic(frame: Frame) -> dict[str, int]:
    response_success(frame, GPIO_CAPTURE_DIAGNOSTIC_RESPONSE)
    payload = frame.payload
    result = {
        name: _u32(payload, offset) for name, offset in CAPTURE_U32_FIELDS.items()
    }
    result.update(
        {name: _u16(payload, offset) for name, offset in CAPTURE_U16_FIELDS.items()}
    )
    result.update({name: payload[offset] for name, offset in CAPTURE_U8_FIELDS.items()})
    result["dma_samples_captured"] = _u64(payload, 32)
    return result


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


def info_integer(info: dict[str, object], name: str) -> int:
    value = info[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolFailure(f"INFO {name} is not an integer")
    return value


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


def _raise_if_new_failures(evidence: Evidence, before: int, context: str) -> None:
    if len(evidence.failures) != before:
        raise ProtocolFailure(f"{context} grading failed")


def grade_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> None:
    before = len(evidence.failures)
    exact = {
        "device_state": STATE_IDLE,
        "protocol_version": PROTOCOL_VERSION,
        "supported_stream_mask": STREAM_BOTH,
        "supported_source_mask": (1 << SOURCE_HARDWARE) | (1 << SOURCE_SYNTHETIC),
        "supported_checksum_mask": SUPPORTED_CHECKSUM_MASK,
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
        "firmware_version": (0, 7, 0),
        "board_id": 1,
        "mcu_id": 1,
        "gpio_packed_width_bits": GPIO_PACKED_WIDTH_BITS,
        "gpio_raw_ring_depth": GPIO_RAW_RING_DEPTH,
        "gpio_packed_ring_depth": GPIO_PACKED_RING_DEPTH,
        "gpio_raw_samples_per_buffer": GPIO_RAW_SAMPLES_PER_BUFFER,
        "gpio_raw_ring_bytes": GPIO_RAW_RING_BYTES,
        "gpio_packed_ring_bytes": GPIO_PACKED_RING_BYTES,
        "gpio_packet_buffer_count": GPIO_PACKET_BUFFER_COUNT,
        "gpio_pit_channel": GPIO_PIT_CHANNEL,
        "gpio_xbar_input": GPIO_XBAR_INPUT,
        "gpio_xbar_output": GPIO_XBAR_OUTPUT,
        "gpio_edma_channel": GPIO_EDMA_CHANNEL,
        "gpio_dmamux_source": GPIO_DMAMUX_SOURCE,
        "gpio_edma_priority": GPIO_EDMA_PRIORITY,
        "gpio_xbar_active_edge": GPIO_XBAR_ACTIVE_EDGE,
    }
    for name, expected in exact.items():
        evidence.equal(f"identity.{name}", expected, info[name])

    build_id = info["build_id"]
    evidence.check(
        "identity.build_id",
        expected_build_id or "tdaq-<16 lowercase hex>",
        build_id,
        isinstance(build_id, str)
        and re.fullmatch(r"tdaq-[0-9a-f]{16}", build_id) is not None
        and (expected_build_id is None or build_id == expected_build_id),
    )
    hardware_serial = info["hardware_serial"]
    evidence.check(
        "identity.hardware_serial",
        expected_hardware_serial or "nonzero uint32",
        hardware_serial,
        isinstance(hardware_serial, int)
        and not isinstance(hardware_serial, bool)
        and 1 <= hardware_serial <= 0xFFFFFFFF
        and (
            expected_hardware_serial is None
            or hardware_serial == expected_hardware_serial
        ),
    )
    selected_checksum = info["data_checksum_algorithm"]
    evidence.check(
        "identity.selected_checksum",
        "advertised enabled algorithm",
        selected_checksum,
        isinstance(selected_checksum, int)
        and selected_checksum in SUPPORTED_CHECKSUMS
        and bool(SUPPORTED_CHECKSUM_MASK & (1 << selected_checksum)),
    )
    diagnostic_mode = info_integer(info, "gpio_capture_diagnostic_mode")
    diagnostic_flags = info_integer(info, "gpio_capture_diagnostic_flags")
    evidence.check(
        "identity.gpio_capture_diagnostic_mode",
        GPIO_DIAGNOSTIC_MODES,
        diagnostic_mode,
        diagnostic_mode in GPIO_DIAGNOSTIC_MODES,
    )
    evidence.check(
        "identity.gpio_capture_diagnostic_flags",
        "known, available, declaration-valid flags",
        diagnostic_flags,
        not diagnostic_flags & ~KNOWN_GPIO_DIAGNOSTIC_FLAGS
        and bool(diagnostic_flags & GPIO_DIAGNOSTIC_AVAILABLE)
        and bool(diagnostic_flags & GPIO_DIAGNOSTIC_DECLARATION_VALID),
    )
    if diagnostic_mode == GPIO_DIAGNOSTIC_NON_DRIVING:
        evidence.equal(
            "identity.non_driving_authority",
            0,
            diagnostic_flags
            & (
                GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
                | GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
            ),
        )
    elif diagnostic_mode == GPIO_DIAGNOSTIC_SELF_DRIVEN_SWEEP:
        evidence.check(
            "identity.self_drive_authority",
            "OUTPUT_DRIVE_PERMITTED",
            diagnostic_flags,
            bool(diagnostic_flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED),
        )
    elif diagnostic_mode == GPIO_DIAGNOSTIC_FIXTURE_STIMULUS:
        evidence.check(
            "identity.external_stimulus_declaration",
            "EXTERNAL_STIMULUS_DECLARED",
            diagnostic_flags,
            bool(diagnostic_flags & GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED),
        )
    _raise_if_new_failures(evidence, before, "identity/capability")


def valid_clock_selection(rate_hz: int, event_count: int) -> bool:
    if not GPIO_CLOCK_MIN_RATE_HZ <= rate_hz <= GPIO_CLOCK_MAX_RATE_HZ:
        return False
    if GPIO_CLOCK_PIT_HZ % rate_hz or GPIO_CLOCK_DWT_HZ % rate_hz:
        return False
    if not GPIO_CLOCK_MIN_EVENT_COUNT <= event_count <= GPIO_CLOCK_MAX_EVENT_COUNT:
        return False
    measurement = event_count * (GPIO_CLOCK_DWT_HZ // rate_hz)
    major = 2 * event_count + GPIO_CLOCK_DUPLICATE_GUARD_EVENTS
    return measurement <= GPIO_CLOCK_MAX_ELAPSED_CYCLES and major <= 0x7FFF


def pack_gpio2_word(word: int) -> int:
    """Apply the production GPIO2_PSR-to-D6-through-D13 bit permutation."""

    return sum(
        ((word >> gpio2_bit) & 1) << packed_bit
        for packed_bit, gpio2_bit in enumerate(GPIO2_BITS_BY_PACKED_BIT)
    )


def grade_clock_diagnostic(
    evidence: Evidence,
    snapshot: dict[str, int],
    *,
    label: str,
    rate_hz: int,
    event_count: int,
    info: dict[str, object],
) -> None:
    before = len(evidence.failures)
    prefix = f"clock.{label}"
    cycles_per_event = GPIO_CLOCK_DWT_HZ // rate_hz
    expected_major = 2 * event_count + GPIO_CLOCK_DUPLICATE_GUARD_EVENTS
    expected_scheduled = snapshot["dwt_elapsed_cycles"] // cycles_per_event
    exact = {
        "configured_rate_hz": rate_hz,
        "production_rate_hz": GPIO_SAMPLE_RATE_HZ,
        "pit_clock_hz": GPIO_CLOCK_PIT_HZ,
        "pit_load_value": GPIO_CLOCK_PIT_HZ // rate_hz - 1,
        "requested_event_count": event_count,
        "dwt_counter_hz": GPIO_CLOCK_DWT_HZ,
        "hardware_error_flags": 0,
        "pit_ldval_configured": GPIO_CLOCK_PIT_HZ // rate_hz - 1,
        "pit_tctrl_configured": 1,
        "dmamux_chcfg_configured": DMAMUX_ENABLE | GPIO_DMAMUX_SOURCE,
        "tcd_nbytes": 4,
        "tcd_biter": expected_major,
        "tcd_attr": TCD_32BIT_ATTRIBUTES,
        "pit_channel": info["gpio_pit_channel"],
        "xbar_input": info["gpio_xbar_input"],
        "xbar_output": info["gpio_xbar_output"],
        "edma_channel": info["gpio_edma_channel"],
        "dmamux_source": info["gpio_dmamux_source"],
        "edma_priority": info["gpio_edma_priority"],
        "tcd_soff": 0,
        "last_sample_word": DIAGNOSTIC_SOURCE_WORD,
    }
    for name, expected in exact.items():
        evidence.equal(f"{prefix}.{name}", expected, snapshot[name])
    evidence.equal(
        f"{prefix}.scheduled_from_dwt",
        expected_scheduled,
        snapshot["scheduled_event_count"],
    )
    evidence.equal(
        f"{prefix}.sample_count_from_tcd",
        snapshot["tcd_biter"] - snapshot["tcd_citer_final"],
        snapshot["dma_sample_count"],
    )
    evidence.check(
        f"{prefix}.scheduled_count_tolerance",
        f"requested +/- {GPIO_CLOCK_COUNT_TOLERANCE}",
        snapshot["scheduled_event_count"],
        abs(snapshot["scheduled_event_count"] - event_count)
        <= GPIO_CLOCK_COUNT_TOLERANCE,
    )
    evidence.check(
        f"{prefix}.sample_count_tolerance",
        f"scheduled +/- {GPIO_CLOCK_COUNT_TOLERANCE}",
        snapshot["dma_sample_count"],
        abs(snapshot["dma_sample_count"] - snapshot["scheduled_event_count"])
        <= GPIO_CLOCK_COUNT_TOLERANCE,
    )
    event_ratio = snapshot["scheduled_event_count"] / event_count
    sample_ratio = (
        snapshot["dma_sample_count"] / snapshot["scheduled_event_count"]
        if snapshot["scheduled_event_count"]
        else 0.0
    )
    evidence.check(
        f"{prefix}.event_ratio",
        "consistent with +/-1 exact-event tolerance",
        event_ratio,
        abs(snapshot["scheduled_event_count"] - event_count) <= 1,
    )
    evidence.check(
        f"{prefix}.sample_event_ratio",
        "consistent with +/-1 DMA-event tolerance",
        sample_ratio,
        snapshot["scheduled_event_count"] > 0
        and abs(snapshot["dma_sample_count"] - snapshot["scheduled_event_count"]) <= 1,
    )
    evidence.equal(
        f"{prefix}.perclk_configuration",
        CCM_PERCLK_24MHZ,
        snapshot["ccm_cscmr1_configured"] & CCM_PERCLK_MASK,
    )
    evidence.equal(
        f"{prefix}.pit_gate",
        CCM_PIT_GATE_MASK,
        snapshot["ccm_ccgr1_configured"] & CCM_PIT_GATE_MASK,
    )
    evidence.equal(
        f"{prefix}.xbar_gate",
        CCM_XBAR_GATE_MASK,
        snapshot["ccm_ccgr2_configured"] & CCM_XBAR_GATE_MASK,
    )
    evidence.equal(
        f"{prefix}.dma_gate",
        CCM_DMA_GATE_MASK,
        snapshot["ccm_ccgr5_configured"] & CCM_DMA_GATE_MASK,
    )
    evidence.equal(
        f"{prefix}.pit_enabled",
        0,
        snapshot["pit_mcr_configured"] & PIT_MDIS,
    )
    evidence.equal(
        f"{prefix}.xbar_selection",
        GPIO_XBAR_INPUT,
        snapshot["xbar_sel_configured"] & 0xFF,
    )
    evidence.equal(
        f"{prefix}.xbar_rising_dma",
        0x0005,
        snapshot["xbar_ctrl_configured"] & 0x00FF,
    )
    evidence.equal(
        f"{prefix}.edma_request_enabled",
        EDMA_CHANNEL_MASK,
        snapshot["dma_erq_configured"] & EDMA_CHANNEL_MASK,
    )
    evidence.equal(f"{prefix}.edma_global_error", 0, snapshot["dma_es_final"])
    evidence.equal(
        f"{prefix}.edma_channel_error",
        0,
        snapshot["dma_err_final"] & EDMA_CHANNEL_MASK,
    )
    evidence.equal(
        f"{prefix}.edma_hardware_request_final",
        0,
        snapshot["dma_hrs_final"] & EDMA_CHANNEL_MASK,
    )
    evidence.check(
        f"{prefix}.diagnostic_addresses",
        "32-byte-aligned source and adjacent destination word",
        {"source": snapshot["tcd_saddr"], "destination": snapshot["tcd_daddr"]},
        snapshot["tcd_saddr"] != 0
        and snapshot["tcd_saddr"] % 32 == 0
        and snapshot["tcd_daddr"] == snapshot["tcd_saddr"] + 4,
    )
    evidence.check(
        f"{prefix}.tcd_dreq",
        "DREQ set after bounded major loop",
        snapshot["tcd_csr_final"],
        bool(snapshot["tcd_csr_final"] & TCD_DREQ),
    )
    _raise_if_new_failures(evidence, before, f"{label} clock diagnostic")
    emit_event(
        "clock_diagnostic_complete",
        configured_rate_hz=rate_hz,
        dma_sample_count=snapshot["dma_sample_count"],
        event_ratio=event_ratio,
        label=label,
        sample_event_ratio=sample_ratio,
        scheduled_event_count=snapshot["scheduled_event_count"],
    )


def grade_capture_diagnostic(
    evidence: Evidence,
    snapshot: dict[str, int],
    info: dict[str, object],
) -> tuple[bool, str]:
    before = len(evidence.failures)
    mode = snapshot["mode"]
    flags = snapshot["diagnostic_flags"]
    evidence.equal(
        "mapping.mode",
        info["gpio_capture_diagnostic_mode"],
        mode,
    )
    evidence.check(
        "mapping.known_mode",
        GPIO_DIAGNOSTIC_MODES,
        mode,
        mode in GPIO_DIAGNOSTIC_MODES,
    )
    for name in ("metadata_kind", "drive_safety", "stimulus_kind"):
        evidence.check(
            f"mapping.{name}",
            "known enum value 0..2",
            snapshot[name],
            0 <= snapshot[name] <= 2,
        )
    evidence.equal("mapping.hardware_error_flags", 0, snapshot["hardware_error_flags"])
    evidence.equal(
        "mapping.reserved_error_flags",
        0,
        snapshot["hardware_error_flags"] & ~KNOWN_GPIO_CAPTURE_ERROR_MASK,
    )
    evidence.equal(
        "mapping.reserved_diagnostic_flags", 0, flags & ~KNOWN_GPIO_DIAGNOSTIC_FLAGS
    )
    advertised_flags = info_integer(info, "gpio_capture_diagnostic_flags")
    evidence.equal(
        "mapping.declaration_flags_match_info",
        advertised_flags & 0x0F,
        flags & 0x0F,
    )
    required = (
        GPIO_DIAGNOSTIC_AVAILABLE
        | GPIO_DIAGNOSTIC_DECLARATION_VALID
        | GPIO_DIAGNOSTIC_DMA_CAPTURE_EXERCISED
        | GPIO_DIAGNOSTIC_PACKED_OBSERVATION_EXERCISED
        | GPIO_DIAGNOSTIC_FINAL_INPUT_SAFE
    )
    evidence.equal("mapping.required_evidence_flags", required, flags & required)
    evidence.equal(
        "mapping.dwt_counter_hz", GPIO_CLOCK_DWT_HZ, snapshot["dwt_counter_hz"]
    )
    evidence.check(
        "mapping.elapsed_cycles",
        "nonzero and bounded",
        snapshot["dwt_elapsed_cycles"],
        0 < snapshot["dwt_elapsed_cycles"] <= 2 * 6_000_000,
    )
    evidence.check(
        "mapping.capture_accounting",
        "retained + stopped partial <= captured",
        {
            "captured": snapshot["dma_samples_captured"],
            "retained": snapshot["complete_samples_retained"],
            "stopped_partial": snapshot["stopped_partial_samples"],
        },
        snapshot["complete_samples_retained"] + snapshot["stopped_partial_samples"]
        <= snapshot["dma_samples_captured"],
    )
    evidence.check(
        "mapping.analysis_count",
        "analyzed == declared limit <= retained",
        {
            "limit": snapshot["analysis_sample_limit"],
            "analyzed": snapshot["samples_analyzed"],
            "retained": snapshot["complete_samples_retained"],
        },
        0 < snapshot["analysis_sample_limit"] <= GPIO_SAMPLES_PER_FRAME
        and snapshot["samples_analyzed"] == snapshot["analysis_sample_limit"]
        and snapshot["samples_analyzed"] <= snapshot["complete_samples_retained"],
    )
    evidence.equal("mapping.mapping_failures", 0, snapshot["mapping_failures"])
    evidence.equal("mapping.unstable_samples", 0, snapshot["unstable_samples"])
    evidence.equal(
        "mapping.packed_and_from_raw",
        pack_gpio2_word(snapshot["raw_word_and"]),
        snapshot["packed_value_and"],
    )
    evidence.equal(
        "mapping.packed_or_from_raw",
        pack_gpio2_word(snapshot["raw_word_or"]),
        snapshot["packed_value_or"],
    )
    evidence.equal(
        "mapping.gpr27_configured_input",
        0,
        snapshot["gpr27_configured"] & GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpio2_gdir_configured_input",
        0,
        snapshot["gpio2_gdir_configured"] & GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpr27_final_input",
        0,
        snapshot["gpr27_after"] & GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpio2_gdir_final_input",
        0,
        snapshot["gpio2_gdir_after"] & GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpr27_unrelated_bits",
        snapshot["gpr27_before"] & ~GPIO2_CAPTURE_MASK,
        snapshot["gpr27_configured"] & ~GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpio2_gdir_unrelated_bits",
        snapshot["gpio2_gdir_before"] & ~GPIO2_CAPTURE_MASK,
        snapshot["gpio2_gdir_configured"] & ~GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpr27_final_unrelated_bits",
        snapshot["gpr27_before"] & ~GPIO2_CAPTURE_MASK,
        snapshot["gpr27_after"] & ~GPIO2_CAPTURE_MASK,
    )
    evidence.equal(
        "mapping.gpio2_gdir_final_unrelated_bits",
        snapshot["gpio2_gdir_before"] & ~GPIO2_CAPTURE_MASK,
        snapshot["gpio2_gdir_after"] & ~GPIO2_CAPTURE_MASK,
    )
    exact_registers = {
        "pit_ldval_configured": 5,
        "pit_tctrl_configured": 1,
        "dmamux_chcfg_configured": DMAMUX_ENABLE | GPIO_DMAMUX_SOURCE,
        "tcd_biter_configured": GPIO_RAW_SAMPLES_PER_BUFFER,
        "edma_priority_configured": GPIO_EDMA_PRIORITY,
    }
    for name, expected in exact_registers.items():
        evidence.equal(f"mapping.{name}", expected, snapshot[name])
    evidence.equal(
        "mapping.edma_request_enabled",
        EDMA_CHANNEL_MASK,
        snapshot["dma_erq_configured"] & EDMA_CHANNEL_MASK,
    )
    evidence.equal(
        "mapping.edma_channel_error",
        0,
        snapshot["dma_err_final"] & EDMA_CHANNEL_MASK,
    )
    evidence.check(
        "mapping.tcd_active_count",
        {"minimum": 0, "maximum": snapshot["tcd_biter_configured"]},
        snapshot["tcd_citer_configured"],
        0 <= snapshot["tcd_citer_configured"] <= snapshot["tcd_biter_configured"],
    )
    evidence.equal(
        "mapping.tcd_major_link_interrupt",
        0x0012,
        snapshot["tcd_csr_configured"] & 0x0012,
    )

    if mode == GPIO_DIAGNOSTIC_NON_DRIVING:
        forbidden = (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
            | GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
        )
        evidence.equal("mapping.non_driving_electrical_claims", 0, flags & forbidden)
        evidence.equal(
            "mapping.non_driving_values_checked", 0, snapshot["mapping_values_checked"]
        )
        evidence.equal(
            "mapping.non_driving_analysis_limit",
            NON_DRIVING_ANALYSIS_SAMPLES,
            snapshot["analysis_sample_limit"],
        )
    elif mode == GPIO_DIAGNOSTIC_SELF_DRIVEN_SWEEP:
        required_sweep_flags = (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
        )
        evidence.equal(
            "mapping.self_driven_flags",
            required_sweep_flags,
            flags & required_sweep_flags,
        )
        evidence.equal(
            "mapping.sweep_values",
            SWEEP_VALUE_COUNT,
            snapshot["mapping_values_checked"],
        )
        evidence.equal(
            "mapping.sweep_analysis_limit",
            SWEEP_VALUE_COUNT * SWEEP_SAMPLES_PER_VALUE,
            snapshot["analysis_sample_limit"],
        )
        evidence.equal("mapping.sweep_metadata_kind", 2, snapshot["metadata_kind"])
        evidence.equal("mapping.sweep_drive_safety", 2, snapshot["drive_safety"])
        evidence.equal("mapping.sweep_stimulus_kind", 0, snapshot["stimulus_kind"])
        evidence.check(
            "mapping.sweep_fixture_identity",
            "nonzero machine-readable fixture identity",
            snapshot["fixture_identity"],
            snapshot["fixture_identity"] != 0,
        )
    elif mode == GPIO_DIAGNOSTIC_FIXTURE_STIMULUS:
        required_fixture_flags = (
            GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
            | GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
        )
        evidence.equal(
            "mapping.fixture_stimulus_flags",
            required_fixture_flags,
            flags & required_fixture_flags,
        )
        evidence.check(
            "mapping.fixture_identity",
            "nonzero machine-readable fixture identity",
            snapshot["fixture_identity"],
            snapshot["fixture_identity"] != 0,
        )
        evidence.check(
            "mapping.stimulus_identity",
            "nonzero declared stimulus identity",
            snapshot["stimulus_identity"],
            snapshot["stimulus_identity"] != 0,
        )
        evidence.equal("mapping.fixture_metadata_kind", 2, snapshot["metadata_kind"])
        evidence.check(
            "mapping.fixture_stimulus_kind",
            "LOOPBACK or EXTERNAL",
            snapshot["stimulus_kind"],
            snapshot["stimulus_kind"] in {1, 2},
        )

    if flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED:
        evidence.check(
            "mapping.output_drive_authorized",
            "drive exercised only when explicitly permitted",
            flags,
            bool(flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED),
        )
    _raise_if_new_failures(evidence, before, "GPIO capture/mapping diagnostic")
    external_stimulus_exercised = bool(
        flags & GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
        and flags & GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
    )
    mode_name = GPIO_DIAGNOSTIC_MODES[mode]
    emit_event(
        "mapping_diagnostic_complete",
        external_electrical_stimulus_exercised=external_stimulus_exercised,
        fixture_identity=snapshot["fixture_identity"],
        mapping_values_checked=snapshot["mapping_values_checked"],
        mode=mode_name,
        output_drive_exercised=bool(flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED),
        stimulus_identity=snapshot["stimulus_identity"],
    )
    return external_stimulus_exercised, mode_name


class PhysicalGpioValidator:
    """Validate arbitrary physical payload bytes and every wire invariant."""

    def __init__(self, run_id: int, checksum_algorithm: int) -> None:
        if not 1 <= run_id <= 0xFFFFFFFF:
            raise ValueError("run ID must be a nonzero uint32")
        if checksum_algorithm not in SUPPORTED_CHECKSUMS:
            raise ProtocolFailure(
                f"host lacks checksum support for algorithm {checksum_algorithm}"
            )
        self.run_id = run_id
        self.checksum_algorithm = checksum_algorithm
        self.gpio = StreamTotals()
        self.first_receive_time: float | None = None
        self.last_receive_time: float | None = None
        self.maximum_receive_gap_seconds = 0.0
        self.payload_and = 0xFF
        self.payload_or = 0
        self.payload_transitions = 0
        self._last_payload_value: int | None = None

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
        if frame.kind != GPIO_DATA:
            raise ProtocolFailure(
                f"physical GPIO run emitted non-GPIO kind 0x{frame.kind:02x}"
            )
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"data run ID is {frame.run_id}; expected {self.run_id}"
            )
        if frame.checksum_algorithm != self.checksum_algorithm:
            raise ProtocolFailure(
                f"data checksum is {frame.checksum_algorithm}; configured "
                f"algorithm is {self.checksum_algorithm}"
            )
        if frame.flags & FLAG_SYNTHETIC:
            raise ProtocolFailure("physical GPIO frame carries SYNTHETIC")
        if frame.flags & (FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE):
            raise ProtocolFailure(
                f"GPIO frame {frame.sequence} carries gap/overrun flags"
            )
        expected_flags = FLAG_EPOCH_START if self.gpio.frames == 0 else 0
        if frame.flags != expected_flags:
            raise ProtocolFailure(
                f"GPIO frame flags are 0x{frame.flags:04x}; "
                f"expected 0x{expected_flags:04x}"
            )
        if frame.sequence != self.gpio.expected_sequence:
            raise ProtocolFailure(
                f"GPIO sequence is {frame.sequence}; "
                f"expected {self.gpio.expected_sequence}"
            )
        if frame.first_sample_ticks != self.gpio.expected_ticks:
            raise ProtocolFailure(
                f"GPIO timestamp is {frame.first_sample_ticks}; "
                f"expected {self.gpio.expected_ticks}"
            )
        for value in frame.payload:
            self.payload_and &= value
            self.payload_or |= value
            if (
                self._last_payload_value is not None
                and value != self._last_payload_value
            ):
                self.payload_transitions += 1
            self._last_payload_value = value
        self.gpio.expected_sequence = (frame.sequence + 1) & 0xFFFFFFFF
        self.gpio.expected_ticks = (
            frame.first_sample_ticks + FRAME_COVERAGE_TICKS
        ) & 0xFFFFFFFFFFFFFFFF
        self.gpio.frames += 1
        self.gpio.items += frame.item_count
        self.gpio.payload_bytes += len(frame.payload)
        self.gpio.framed_bytes += DATA_FRAME_BYTES


def _status_error_values(status: StatusSnapshot) -> dict[str, int]:
    return {
        "adc_frames_emitted": status.adc_frames_emitted,
        "adc_items_dropped": status.adc_items_dropped,
        "gpio_items_dropped": status.gpio_items_dropped,
        "parser_errors": status.parser_errors,
        "transport_errors": status.transport_errors,
        "gpio_raw_samples_lost": status.gpio_raw_samples_lost,
        "gpio_packer_samples_dropped": status.gpio_packer_samples_dropped,
        "gpio_raw_ring_overruns": status.gpio_raw_ring_overruns,
        "gpio_hardware_errors": status.gpio_hardware_errors,
        "gpio_raw_invariant_errors": status.gpio_raw_invariant_errors,
        "gpio_packer_source_errors": status.gpio_packer_source_errors,
        "gpio_packer_pipeline_errors": status.gpio_packer_pipeline_errors,
        "gpio_packer_chronology_errors": status.gpio_packer_chronology_errors,
        "gpio_resource_conflicts": status.gpio_resource_conflicts,
        "gpio_start_errors": status.gpio_start_errors,
        "gpio_stop_errors": status.gpio_stop_errors,
        "gpio_stale_dma_completions": status.gpio_stale_dma_completions,
    }


def validate_status_accounting(
    status: StatusSnapshot,
    info: dict[str, object],
) -> None:
    stages = (
        status.gpio_samples_captured,
        status.gpio_samples_packed,
        status.gpio_samples_framed,
        status.gpio_samples_transmitted,
    )
    if not all(left >= right for left, right in pairwise(stages)):
        raise ProtocolFailure(f"GPIO stage counters are not monotonic: {stages}")
    if status.gpio_samples_framed % GPIO_SAMPLES_PER_FRAME:
        raise ProtocolFailure("framed GPIO sample count is not frame-aligned")
    if status.gpio_samples_transmitted % GPIO_SAMPLES_PER_FRAME:
        raise ProtocolFailure("transmitted GPIO sample count is not frame-aligned")
    if status.gpio_frames_emitted * GPIO_SAMPLES_PER_FRAME > status.gpio_samples_framed:
        raise ProtocolFailure("emitted GPIO frames exceed framed samples")
    if (
        status.gpio_samples_transmitted
        > status.gpio_frames_emitted * GPIO_SAMPLES_PER_FRAME
    ):
        raise ProtocolFailure("transmitted samples exceed emitted GPIO frames")
    depth_limits = {
        "gpio_raw_ready_depth": info_integer(info, "gpio_raw_ring_depth"),
        "gpio_raw_ready_high_water": info_integer(info, "gpio_raw_ring_depth"),
        "gpio_packed_ready_depth": info_integer(info, "gpio_packed_ring_depth"),
        "gpio_packed_ready_high_water": info_integer(info, "gpio_packed_ring_depth"),
        "packet_ready_depth": info_integer(info, "gpio_packet_buffer_count"),
        "packet_transmit_depth": info_integer(info, "gpio_packet_buffer_count"),
        "packet_owned_high_water": info_integer(info, "gpio_packet_buffer_count"),
    }
    for name, limit in depth_limits.items():
        value = getattr(status, name)
        if value > limit:
            raise ProtocolFailure(f"STATUS {name}={value} exceeds capacity {limit}")
    if status.gpio_processing_cpu_basis_points > 10_000:
        raise ProtocolFailure("GPIO processing CPU measurement exceeds 100%")
    if status.gpio_raw_ready_depth > status.gpio_raw_ready_high_water:
        raise ProtocolFailure("raw ready depth exceeds its high-water mark")
    if status.gpio_packed_ready_depth > status.gpio_packed_ready_high_water:
        raise ProtocolFailure("packed ready depth exceeds its high-water mark")
    if (
        status.packet_ready_depth + status.packet_transmit_depth
        > status.packet_owned_high_water
    ):
        raise ProtocolFailure("packet queue depths exceed owned high-water count")


def validate_running_status(
    status: StatusSnapshot,
    frame: Frame,
    validator: PhysicalGpioValidator,
    stats_generation: int,
    received_frames_before_request: int,
    previous_status: StatusSnapshot | None,
    info: dict[str, object],
) -> None:
    if frame.run_id != validator.run_id:
        raise ProtocolFailure(
            f"STATUS run ID is {frame.run_id}; expected {validator.run_id}"
        )
    expected_configuration = (
        STATE_RUNNING,
        STREAM_GPIO,
        SOURCE_HARDWARE,
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
            f"STATUS generation is {status.stats_generation}; expected {stats_generation}"
        )
    errors = _status_error_values(status)
    if any(errors.values()):
        raise ProtocolFailure(f"running STATUS reports loss/errors: {errors}")
    if status.gpio_frames_emitted < received_frames_before_request:
        raise ProtocolFailure("firmware GPIO counter trails pre-request receive floor")
    if (
        status.gpio_samples_transmitted
        < received_frames_before_request * GPIO_SAMPLES_PER_FRAME
    ):
        raise ProtocolFailure("firmware transmitted count trails received frames")
    validate_status_accounting(status, info)
    if previous_status is not None:
        before_values = previous_status.monotonic_counters()
        after_values = status.monotonic_counters()
        if any(after < before for before, after in zip(before_values, after_values)):
            raise ProtocolFailure("running STATUS counters moved backwards")


class MemoryTracker:
    """Track process RSS without retaining stream payloads."""

    def __init__(self) -> None:
        self.baseline_current_bytes = current_rss_bytes()
        self.baseline_peak_bytes = peak_rss_bytes()
        self.maximum_current_bytes = self.baseline_current_bytes

    def sample(self) -> None:
        self.maximum_current_bytes = max(
            self.maximum_current_bytes,
            current_rss_bytes(),
        )

    @property
    def final_current_bytes(self) -> int:
        return current_rss_bytes()

    @property
    def peak_bytes(self) -> int:
        return max(self.maximum_current_bytes, peak_rss_bytes())

    @property
    def peak_growth_bytes(self) -> int:
        return max(0, self.peak_bytes - self.baseline_peak_bytes)


def peak_rss_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1024)


def current_rss_bytes() -> int:
    try:
        with open("/proc/self/statm", encoding="ascii") as status:
            resident_pages = int(status.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return peak_rss_bytes()


def percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / expected


def grade_final_metrics(
    evidence: Evidence,
    *,
    capture_elapsed: float,
    final_frame: Frame,
    final_status: StatusSnapshot,
    validator: PhysicalGpioValidator,
    link: SerialLink,
    parser_errors_at_start: int,
    status_latencies: list[float],
    minimum_status_samples: int,
    memory: MemoryTracker,
    info: dict[str, object],
) -> None:
    evidence.equal("final.state", STATE_IDLE, final_status.device_state)
    evidence.equal("final.stream_mask", STREAM_NONE, final_status.stream_mask)
    evidence.equal("final.source", SOURCE_HARDWARE, final_status.source)
    evidence.equal("final.run_id", validator.run_id, final_frame.run_id)
    evidence.equal("final.adc_frames_emitted", 0, final_status.adc_frames_emitted)
    evidence.equal(
        "final.gpio_frames_emitted",
        validator.gpio.frames,
        final_status.gpio_frames_emitted,
    )
    evidence.equal(
        "final.gpio_items",
        validator.gpio.frames * GPIO_SAMPLES_PER_FRAME,
        validator.gpio.items,
    )
    evidence.equal(
        "final.gpio_payload_bytes",
        validator.gpio.frames * DATA_PAYLOAD_BYTES,
        validator.gpio.payload_bytes,
    )
    evidence.equal(
        "final.gpio_samples_captured",
        validator.gpio.items,
        final_status.gpio_samples_captured,
    )
    evidence.equal(
        "final.gpio_samples_packed",
        validator.gpio.items,
        final_status.gpio_samples_packed,
    )
    evidence.equal(
        "final.gpio_samples_framed",
        validator.gpio.items,
        final_status.gpio_samples_framed,
    )
    evidence.equal(
        "final.gpio_samples_transmitted",
        validator.gpio.items,
        final_status.gpio_samples_transmitted,
    )
    evidence.equal(
        "final.gpio_dma_major_loops",
        validator.gpio.frames,
        final_status.gpio_dma_major_loops,
    )
    for name, value in _status_error_values(final_status).items():
        evidence.equal(f"final.{name}", 0, value)
    final_depths = {
        "gpio_raw_ready_depth": final_status.gpio_raw_ready_depth,
        "gpio_packed_ready_depth": final_status.gpio_packed_ready_depth,
        "packet_ready_depth": final_status.packet_ready_depth,
        "packet_transmit_depth": final_status.packet_transmit_depth,
    }
    for name, value in final_depths.items():
        evidence.equal(f"final.{name}", 0, value)
    evidence.check(
        "cpu.gpio_processing_basis_points",
        {
            "minimum": 1,
            "maximum": GPIO_PROCESSING_CPU_MAX_BASIS_POINTS,
            "measured_scope": "pack/copy/checksum/framing service",
        },
        final_status.gpio_processing_cpu_basis_points,
        1
        <= final_status.gpio_processing_cpu_basis_points
        <= GPIO_PROCESSING_CPU_MAX_BASIS_POINTS,
    )
    queue_high_waters = {
        "gpio_raw_ready_high_water": (
            final_status.gpio_raw_ready_high_water,
            info_integer(info, "gpio_raw_ring_depth"),
        ),
        "gpio_packed_ready_high_water": (
            final_status.gpio_packed_ready_high_water,
            info_integer(info, "gpio_packed_ring_depth"),
        ),
        "packet_owned_high_water": (
            final_status.packet_owned_high_water,
            info_integer(info, "gpio_packet_buffer_count"),
        ),
    }
    for name, (value, capacity) in queue_high_waters.items():
        evidence.check(
            f"queue.{name}",
            {"minimum": 0, "maximum": capacity},
            value,
            0 <= value <= capacity,
        )
    try:
        validate_status_accounting(final_status, info)
    except ProtocolFailure as error:
        evidence.check(
            "final.status_accounting", "internally consistent", str(error), False
        )
    else:
        evidence.check(
            "final.status_accounting", "internally consistent", "consistent", True
        )

    evidence.check(
        "stream.nonempty_gpio",
        "at least one physical GPIO frame",
        validator.gpio.frames,
        validator.gpio.frames > 0,
    )
    sample_rate = validator.gpio.items / capture_elapsed
    payload_rate = validator.gpio.payload_bytes / capture_elapsed
    framed_rate = validator.gpio.framed_bytes / capture_elapsed
    target_framed_rate = DATA_FRAME_BYTES * TIMESTAMP_HZ / FRAME_COVERAGE_TICKS
    evidence.check(
        "throughput.gpio_samples_per_second",
        {"target": GPIO_SAMPLE_RATE_HZ, "tolerance_fraction": RATE_TOLERANCE_FRACTION},
        sample_rate,
        _relative_error(sample_rate, GPIO_SAMPLE_RATE_HZ) <= RATE_TOLERANCE_FRACTION,
    )
    evidence.check(
        "throughput.gpio_payload_bytes_per_second",
        {"target": GPIO_SAMPLE_RATE_HZ, "tolerance_fraction": RATE_TOLERANCE_FRACTION},
        payload_rate,
        _relative_error(payload_rate, GPIO_SAMPLE_RATE_HZ) <= RATE_TOLERANCE_FRACTION,
    )
    evidence.check(
        "throughput.gpio_framed_bytes_per_second",
        {"target": target_framed_rate, "tolerance_fraction": RATE_TOLERANCE_FRACTION},
        framed_rate,
        _relative_error(framed_rate, target_framed_rate) <= RATE_TOLERANCE_FRACTION,
    )

    p99 = percentile(status_latencies, 0.99)
    maximum = max(status_latencies, default=0.0)
    evidence.check(
        "latency.status_sample_count",
        f">= {minimum_status_samples}",
        len(status_latencies),
        len(status_latencies) >= minimum_status_samples,
    )
    evidence.check(
        "latency.status_p99_seconds",
        f"<= {STATUS_P99_LIMIT_SECONDS}",
        p99,
        bool(status_latencies) and p99 <= STATUS_P99_LIMIT_SECONDS,
    )
    evidence.check(
        "latency.status_maximum_seconds",
        f"<= {STATUS_MAXIMUM_LIMIT_SECONDS}",
        maximum,
        bool(status_latencies) and maximum <= STATUS_MAXIMUM_LIMIT_SECONDS,
    )

    host_parser_errors = link.parser.errors - parser_errors_at_start
    evidence.equal("host.parser_errors", 0, host_parser_errors)
    evidence.equal("host.stale_responses", 0, link.stale_responses)
    evidence.equal("host.parser_buffered_bytes", 0, len(link.parser.buffer))
    evidence.check(
        "host.parser_high_water_bytes",
        f"<= {SERIAL_READ_BYTES + MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1}",
        link.parser.high_water_bytes,
        link.parser.high_water_bytes
        <= SERIAL_READ_BYTES + MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1,
    )
    evidence.check(
        "host.maximum_read_bytes",
        f"<= {SERIAL_READ_BYTES}",
        link.maximum_read_bytes,
        link.maximum_read_bytes <= SERIAL_READ_BYTES,
    )
    evidence.check(
        "host.checksummed_frames",
        f">= {validator.gpio.frames} validated data frames",
        link.parser.frames_decoded,
        link.parser.frames_decoded >= validator.gpio.frames,
    )
    memory.sample()
    evidence.check(
        "memory.peak_rss_growth_bytes",
        f"<= {MAX_RSS_GROWTH_BYTES}",
        memory.peak_growth_bytes,
        memory.peak_growth_bytes <= MAX_RSS_GROWTH_BYTES,
    )
    evidence.check(
        "memory.process_rss_bytes",
        "finite nonnegative baseline/current/peak",
        {
            "baseline_current": memory.baseline_current_bytes,
            "baseline_peak": memory.baseline_peak_bytes,
            "final_current": memory.final_current_bytes,
            "peak": memory.peak_bytes,
        },
        0
        <= memory.baseline_current_bytes
        <= memory.maximum_current_bytes
        <= memory.peak_bytes,
    )


def run_acceptance(
    port: SerialPort,
    *,
    capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
    status_interval_seconds: float = DEFAULT_STATUS_INTERVAL_SECONDS,
    checksum_algorithm: int = DEFAULT_DATA_CHECKSUM,
    low_rate_hz: int = DEFAULT_LOW_RATE_HZ,
    low_rate_event_count: int = DEFAULT_LOW_RATE_EVENT_COUNT,
    production_event_count: int = DEFAULT_PRODUCTION_EVENT_COUNT,
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
) -> AcceptanceResult:
    """Run diagnostics and one bounded physical GPIO epoch, ending in IDLE."""

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
    if checksum_algorithm not in SUPPORTED_CHECKSUMS:
        raise ProtocolFailure(
            f"host lacks checksum support for algorithm {checksum_algorithm}"
        )
    if low_rate_hz >= GPIO_SAMPLE_RATE_HZ or not valid_clock_selection(
        low_rate_hz, low_rate_event_count
    ):
        raise ValueError(
            "low-rate diagnostic selection is not a bounded exact divisor below 4 MHz"
        )
    if not valid_clock_selection(GPIO_SAMPLE_RATE_HZ, production_event_count):
        raise ValueError("production-rate diagnostic selection is invalid")

    evidence = Evidence()
    link = SerialLink(port)
    completed = False
    validator: PhysicalGpioValidator | None = None
    external_stimulus_exercised = False
    mapping_mode = "NOT_RUN"
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        synchronized_info = synchronize(link)
        info_frame, info_latency = link.exchange(INFO_REQUEST)
        info = decode_info(info_frame)
        evidence.check(
            "latency.info_seconds",
            f"<= {COMMAND_DEADLINE_SECONDS}",
            info_latency,
            info_latency <= COMMAND_DEADLINE_SECONDS,
        )
        evidence.equal(
            "identity.stable_sync",
            stable_identity(synchronized_info),
            stable_identity(info),
        )
        grade_info(
            evidence,
            info,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
        if not info_integer(info, "supported_checksum_mask") & (
            1 << checksum_algorithm
        ):
            raise ProtocolFailure(
                f"device does not advertise checksum algorithm {checksum_algorithm}"
            )

        idle_before_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        idle_before = decode_status(idle_before_frame)
        if idle_before.device_state != STATE_IDLE:
            raise ProtocolFailure("diagnostic precondition is not IDLE")

        for label, rate_hz, event_count in (
            ("low_rate", low_rate_hz, low_rate_event_count),
            ("production_rate", GPIO_SAMPLE_RATE_HZ, production_event_count),
        ):
            payload = GPIO_CLOCK_REQUEST.pack(rate_hz, event_count, 0)
            diagnostic_frame, latency = link.exchange(
                GPIO_CLOCK_DIAGNOSTIC_REQUEST,
                payload,
                timeout=DIAGNOSTIC_DEADLINE_SECONDS,
            )
            evidence.check(
                f"latency.clock_{label}_seconds",
                f"<= {DIAGNOSTIC_DEADLINE_SECONDS}",
                latency,
                latency <= DIAGNOSTIC_DEADLINE_SECONDS,
            )
            grade_clock_diagnostic(
                evidence,
                decode_clock_diagnostic(diagnostic_frame),
                label=label,
                rate_hz=rate_hz,
                event_count=event_count,
                info=info,
            )

        after_clock_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        after_clock = decode_status(after_clock_frame)
        evidence.equal("clock.status_state", STATE_IDLE, after_clock.device_state)
        evidence.equal(
            "clock.acquisition_counters_unchanged",
            idle_before.monotonic_counters(),
            after_clock.monotonic_counters(),
        )

        capture_frame, capture_latency = link.exchange(
            GPIO_CAPTURE_DIAGNOSTIC_REQUEST,
            timeout=DIAGNOSTIC_DEADLINE_SECONDS,
        )
        evidence.check(
            "latency.capture_diagnostic_seconds",
            f"<= {DIAGNOSTIC_DEADLINE_SECONDS}",
            capture_latency,
            capture_latency <= DIAGNOSTIC_DEADLINE_SECONDS,
        )
        external_stimulus_exercised, mapping_mode = grade_capture_diagnostic(
            evidence,
            decode_capture_diagnostic(capture_frame),
            info,
        )
        statement = (
            "external electrical stimulus was exercised"
            if external_stimulus_exercised
            else "external electrical stimulus was not exercised"
        )
        print(f"ELECTRICAL_STIMULUS: {statement}")
        emit_event(
            "external_electrical_stimulus",
            exercised=external_stimulus_exercised,
            statement=statement,
        )

        reset_frame, _latency = link.exchange(RESET_STATS_REQUEST)
        response_success(reset_frame, RESET_STATS_RESPONSE)
        reset_generation = _u32(reset_frame.payload, 4)
        if reset_generation == 0:
            raise ProtocolFailure("RESET_STATS returned generation zero")

        parser_errors_at_start = link.parser.errors
        requested_configuration = CONFIGURATION.pack(
            STREAM_GPIO,
            SOURCE_HARDWARE,
            checksum_algorithm,
            0,
            DATA_FRAME_BYTES,
        )
        configured_frame, configure_latency = link.exchange(
            CONFIGURE_REQUEST,
            requested_configuration,
        )
        evidence.check(
            "latency.configure_seconds",
            f"<= {COMMAND_DEADLINE_SECONDS}",
            configure_latency,
            configure_latency <= COMMAND_DEADLINE_SECONDS,
        )
        expected_configuration = (
            STREAM_GPIO,
            SOURCE_HARDWARE,
            checksum_algorithm,
            DATA_FRAME_BYTES,
        )
        evidence.equal(
            "configure.applied",
            expected_configuration,
            decode_configuration(configured_frame, CONFIGURE_RESPONSE),
        )

        configured_status_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        configured_status = decode_status(configured_status_frame)
        evidence.equal(
            "configure.state", STATE_CONFIGURED, configured_status.device_state
        )
        evidence.equal(
            "configure.stream_mask", STREAM_GPIO, configured_status.stream_mask
        )
        evidence.equal("configure.source", SOURCE_HARDWARE, configured_status.source)
        evidence.equal(
            "configure.checksum", checksum_algorithm, configured_status.checksum
        )
        evidence.equal(
            "configure.stats_generation",
            reset_generation,
            configured_status.stats_generation,
        )
        configured_info_frame, _latency = link.exchange(INFO_REQUEST)
        configured_info = decode_info(configured_info_frame)
        evidence.equal(
            "configure.info_state", STATE_CONFIGURED, configured_info["device_state"]
        )
        evidence.equal(
            "configure.info_checksum",
            checksum_algorithm,
            configured_info["data_checksum_algorithm"],
        )
        if evidence.failures:
            raise ProtocolFailure("pre-stream grading failed")

        deferred_data: list[Frame] = []

        def defer_start_data(frame: Frame) -> None:
            maximum = math.ceil(SERIAL_READ_BYTES / DATA_FRAME_BYTES) + 1
            if len(deferred_data) >= maximum:
                raise ProtocolFailure(
                    f"START boundary exceeded its {maximum}-frame deferred bound"
                )
            deferred_data.append(frame)

        start_frame, start_latency = link.exchange(
            START_REQUEST,
            on_data=defer_start_data,
        )
        evidence.check(
            "latency.start_seconds",
            f"<= {COMMAND_DEADLINE_SECONDS}",
            start_latency,
            start_latency <= COMMAND_DEADLINE_SECONDS,
        )
        response_success(start_frame, START_RESPONSE)
        evidence.check(
            "start.run_id",
            "nonzero uint32",
            start_frame.run_id,
            1 <= start_frame.run_id <= 0xFFFFFFFF,
        )
        evidence.equal(
            "start.applied",
            expected_configuration,
            decode_configuration(start_frame, START_RESPONSE),
        )
        validator = PhysicalGpioValidator(start_frame.run_id, checksum_algorithm)
        for frame in deferred_data:
            validator.accept(frame)

        memory = MemoryTracker()
        active_started = time.monotonic()
        capture_deadline = active_started + capture_seconds
        next_status_at = active_started
        status_latencies: list[float] = []
        stats_generation: int | None = None
        previous_status: StatusSnapshot | None = None
        status_count = 0

        while time.monotonic() < capture_deadline:
            now = time.monotonic()
            if now >= next_status_at:
                received_before_request = validator.gpio.frames
                status_frame, latency = link.exchange(
                    GET_STATUS_REQUEST,
                    on_data=validator.accept,
                )
                status = decode_status(status_frame)
                if stats_generation is None:
                    stats_generation = status.stats_generation
                    expected_generation = (reset_generation + 1) & 0xFFFFFFFF
                    expected_generation = expected_generation or 1
                    evidence.equal(
                        "start.stats_generation", expected_generation, stats_generation
                    )
                validate_running_status(
                    status,
                    status_frame,
                    validator,
                    stats_generation,
                    received_before_request,
                    previous_status,
                    info,
                )
                previous_status = status
                status_latencies.append(latency)
                status_count += 1
                memory.sample()
                next_status_at += status_interval_seconds
                while next_status_at <= time.monotonic():
                    next_status_at += status_interval_seconds
                continue
            link.pump_once(validator.accept)

        stop_requested_at = time.monotonic()
        capture_elapsed = stop_requested_at - active_started
        stop_frame, stop_latency = link.exchange(
            STOP_REQUEST,
            on_data=validator.accept,
        )
        response_success(stop_frame, STOP_RESPONSE)
        evidence.check(
            "latency.stop_seconds",
            f"<= {COMMAND_DEADLINE_SECONDS}",
            stop_latency,
            stop_latency <= COMMAND_DEADLINE_SECONDS,
        )
        evidence.equal("stop.state", STATE_IDLE, stop_frame.payload[4])
        evidence.equal("stop.run_id", validator.run_id, stop_frame.run_id)

        link.drain_until_quiet(validator.accept)
        final_frame, final_latency = link.exchange(
            GET_STATUS_REQUEST,
            on_data=validator.accept,
        )
        final_status = decode_status(final_frame)
        evidence.check(
            "latency.final_status_seconds",
            f"<= {COMMAND_DEADLINE_SECONDS}",
            final_latency,
            final_latency <= COMMAND_DEADLINE_SECONDS,
        )
        if stats_generation is None:
            raise ProtocolFailure("capture completed without a running STATUS response")
        evidence.equal(
            "final.stats_generation", stats_generation, final_status.stats_generation
        )
        minimum_status_samples = max(1, int(capture_seconds / status_interval_seconds))
        grade_final_metrics(
            evidence,
            capture_elapsed=capture_elapsed,
            final_frame=final_frame,
            final_status=final_status,
            validator=validator,
            link=link,
            parser_errors_at_start=parser_errors_at_start,
            status_latencies=status_latencies,
            minimum_status_samples=minimum_status_samples,
            memory=memory,
            info=info,
        )
        emit_event(
            "capture_complete",
            capture_elapsed_seconds=capture_elapsed,
            checksum_algorithm=CHECKSUM_NAMES[checksum_algorithm],
            checksum_algorithm_id=checksum_algorithm,
            external_electrical_stimulus_exercised=external_stimulus_exercised,
            gpio_frames=validator.gpio.frames,
            gpio_items=validator.gpio.items,
            mapping_mode=mapping_mode,
            maximum_receive_gap_seconds=validator.maximum_receive_gap_seconds,
            payload_and=validator.payload_and,
            payload_or=validator.payload_or,
            payload_transitions=validator.payload_transitions,
            status_requests=status_count,
        )
        completed = not evidence.failures
    except Exception as error:  # noqa: BLE001 - stdout is the remote diagnosis
        message = f"{type(error).__name__}: {error}"
        diagnostics: dict[str, object] = {}
        if validator is not None:
            diagnostics = {
                "accepted_gpio_frames": validator.gpio.frames,
                "maximum_receive_gap_seconds": validator.maximum_receive_gap_seconds,
            }
        emit_event("fatal", error=message, **diagnostics)
        evidence.failures.append(message)
    finally:
        if not completed:
            try:
                cleanup, _latency = link.exchange(
                    STOP_REQUEST,
                    timeout=COMMAND_DEADLINE_SECONDS,
                    on_data=lambda _frame: None,
                )
                emit_event(
                    "cleanup_stop",
                    state=(cleanup.payload[4] if len(cleanup.payload) > 4 else None),
                )
            except Exception as cleanup_error:  # noqa: BLE001 - best effort only
                emit_event(
                    "cleanup_stop_failed",
                    error=f"{type(cleanup_error).__name__}: {cleanup_error}",
                )
    return AcceptanceResult(
        evidence=evidence,
        external_stimulus_exercised=external_stimulus_exercised,
        mapping_mode=mapping_mode,
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
    name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 0)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
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


def _checksum_environment(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().upper().replace("-", "_").replace("/", "_")
    aliases = {
        "ADLER32": CHECKSUM_ADLER32,
        "ADLER_32": CHECKSUM_ADLER32,
        "CRC32C": CHECKSUM_CRC32C,
        "CRC_32C": CHECKSUM_CRC32C,
        "CRC32_ISO_HDLC": CHECKSUM_CRC32_ISO_HDLC,
        "CRC_32_ISO_HDLC": CHECKSUM_CRC32_ISO_HDLC,
    }
    selected = aliases.get(normalized)
    if selected is None:
        try:
            selected = int(raw, 0)
        except ValueError:
            selected = -1
    if selected not in SUPPORTED_CHECKSUMS:
        choices = ", ".join(
            CHECKSUM_NAMES[algorithm] for algorithm in sorted(SUPPORTED_CHECKSUMS)
        )
        raise ValueError(f"{name} must be one of {choices} or its numeric ID")
    return selected


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        emit_event("configuration_error", error="SERIAL_PORT is required")
        return 2
    try:
        capture_seconds = _positive_float_environment(
            "GPIO_CAPTURE_SECONDS", DEFAULT_CAPTURE_SECONDS
        )
        status_interval_seconds = _positive_float_environment(
            "GPIO_STATUS_INTERVAL_SECONDS", DEFAULT_STATUS_INTERVAL_SECONDS
        )
        checksum_algorithm = _checksum_environment(
            "GPIO_CHECKSUM_ALGORITHM", DEFAULT_DATA_CHECKSUM
        )
        low_rate_hz = _bounded_int_environment(
            "GPIO_LOW_RATE_HZ",
            DEFAULT_LOW_RATE_HZ,
            GPIO_CLOCK_MIN_RATE_HZ,
            GPIO_CLOCK_MAX_RATE_HZ - 1,
        )
        low_rate_event_count = _bounded_int_environment(
            "GPIO_LOW_RATE_EVENT_COUNT",
            DEFAULT_LOW_RATE_EVENT_COUNT,
            GPIO_CLOCK_MIN_EVENT_COUNT,
            GPIO_CLOCK_MAX_EVENT_COUNT,
        )
        production_event_count = _bounded_int_environment(
            "GPIO_PRODUCTION_EVENT_COUNT",
            DEFAULT_PRODUCTION_EVENT_COUNT,
            GPIO_CLOCK_MIN_EVENT_COUNT,
            GPIO_CLOCK_MAX_EVENT_COUNT,
        )
        expected_hardware_serial = _optional_uint32_environment(
            "EXPECTED_HARDWARE_SERIAL"
        )
    except ValueError as error:
        emit_event("configuration_error", error=str(error))
        return 2
    expected_build_id = os.environ.get("EXPECTED_BUILD_ID")
    emit_event(
        "program_start",
        baud=BAUD_RATE,
        capture_seconds=capture_seconds,
        checksum_algorithm=CHECKSUM_NAMES[checksum_algorithm],
        checksum_algorithm_id=checksum_algorithm,
        low_rate_event_count=low_rate_event_count,
        low_rate_hz=low_rate_hz,
        port=port_name,
        production_event_count=production_event_count,
        protocol=PROTOCOL_VERSION,
        status_interval_seconds=status_interval_seconds,
    )
    try:
        port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - print rig-visible open failure
        emit_event("open_failed", error=f"{type(error).__name__}: {error}")
        return 2
    try:
        result = run_acceptance(
            port,
            capture_seconds=capture_seconds,
            status_interval_seconds=status_interval_seconds,
            checksum_algorithm=checksum_algorithm,
            low_rate_hz=low_rate_hz,
            low_rate_event_count=low_rate_event_count,
            production_event_count=production_event_count,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
    finally:
        port.close()
    summary = {
        "checks": result.evidence.check_count,
        "external_electrical_stimulus": (
            "EXERCISED" if result.external_stimulus_exercised else "NOT_EXERCISED"
        ),
        "failures": result.evidence.failures,
        "mapping_mode": result.mapping_mode,
        "result": "PASS" if not result.evidence.failures else "FAIL",
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if not result.evidence.failures else 1


if __name__ == "__main__":
    sys.exit(main())
