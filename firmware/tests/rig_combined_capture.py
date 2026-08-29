#!/usr/bin/env python3
"""Independent Phase 08 physical combined-acquisition acceptance.

The remote rig uploads this file by itself to a network-disabled Python 3.13
container. It embeds the protocol-v1 values it grades, uses only the Python
standard library plus pyserial, and never imports the project package or its
generated constants.

Every ADC code and GPIO byte is range checked, but external electrical claims
remain explicit and separate. Analog stimulus conformance is graded only from
``ADC_FIXTURE_STIMULUS_JSON``. Digital fixture stimulus is claimed only when
the firmware's bounded GPIO capture diagnostic reports a declared external
stimulus and completed external-transition validation. Neither path claims an
analog aperture or external pad-propagation measurement.
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
from typing import Protocol

import serial

BAUD_RATE = 115_200
SERIAL_READ_TIMEOUT_SECONDS = 0.02
SERIAL_WRITE_TIMEOUT_SECONDS = 0.5
SERIAL_READ_BYTES = 16 * 1024
STARTUP_DRAIN_SECONDS = 0.25
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 0.5
DIAGNOSTIC_DEADLINE_SECONDS = 1.0
STOP_DRAIN_DEADLINE_SECONDS = 2.0
STOP_DRAIN_QUIET_SECONDS = 0.10
DEFAULT_CAPTURE_SECONDS = 10.0
DEFAULT_WARMUP_SECONDS = 0.25
DEFAULT_STATUS_INTERVAL_SECONDS = 0.5
MAX_CAPTURE_SECONDS = 3600.0
MAX_WARMUP_SECONDS = 10.0
MIN_STATUS_INTERVAL_SECONDS = 0.01
MAX_STATUS_SAMPLES = 16_384
RATE_TOLERANCE_FRACTION = 0.01
STATUS_P99_LIMIT_SECONDS = 0.100
STATUS_MAXIMUM_LIMIT_SECONDS = 0.250
MAX_RSS_GROWTH_BYTES = 32 * 1024 * 1024

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
ADC_CONTAINER_BYTES = 2
ADC_BYTES_PER_PAIR = 4
ADC_PAIRS_PER_FRAME = 1012
ADC_PRIMARY_RESOLUTION_BITS = 12
ADC_FALLBACK_RESOLUTION_BITS = 10
ADC_CODE_MIN = 0
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4048
GPIO_PINS_BY_BIT = tuple(range(6, 14))
FRAME_COVERAGE_TICKS = 8096

ADC_PAYLOAD_STRUCT = struct.Struct(f"<{2 * ADC_PAIRS_PER_FRAME}H")
GPIO_ADJACENT_SAMPLE_COUNT = GPIO_SAMPLES_PER_FRAME - 1
GPIO_ADJACENT_SAMPLE_MASK = (1 << (8 * GPIO_ADJACENT_SAMPLE_COUNT)) - 1
GPIO_BYTE_LOW_SEVEN_BITS = int.from_bytes(
    b"\x7f" * GPIO_ADJACENT_SAMPLE_COUNT, "little"
)
GPIO_BYTE_HIGH_BITS = int.from_bytes(b"\x80" * GPIO_ADJACENT_SAMPLE_COUNT, "little")

GPIO_PACKED_WIDTH_BITS = 8
GPIO_RAW_RING_DEPTH = 4
GPIO_RAW_SAMPLES_PER_BUFFER = 4048
GPIO_RAW_RING_BYTES = 64_768
GPIO_PACKED_RING_DEPTH = 4
GPIO_PACKED_RING_BYTES = 16_256
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
GPIO_EDMA_CHANNEL_MASK = 1 << GPIO_EDMA_CHANNEL

ADC_PINS = (14, 15)
ADC_PERIPHERALS = (1, 2)
ADC_CHANNELS = (7, 8)
ADC_DMA_RING_DEPTH = 4
ADC_PAIR_BYTES = 4
ADC_DMA_RING_BYTES = 16_256
ADC_EDMA_CHANNELS = (0, 1)
ADC_EDMA_PRIORITIES = (2, 1)
ADC_DMAMUX_SOURCES = (24, 88)
ADC_DMA_IRQ_PRIORITY = 48
GPIO_DMA_IRQ_PRIORITY = 64

ADC_REFERENCE = 1
ADC_CLOCK_SOURCE = 1
ADC_CLOCK_DIVIDER = 4
ADC_HARDWARE_AVERAGE_COUNT = 0
ADC_REFERENCE_MV_NOMINAL = 3300
ADC_INPUT_MIN_MV_NOMINAL = 0
ADC_INPUT_MAX_MV_NOMINAL = 3300
ADC_SAMPLE_TIME_ADCK = 3
ADC_PRIMARY_CONVERSION_MODE = 2
ADC_FALLBACK_CONVERSION_MODE = 1
ADC_IPG_CLOCK_HZ = 150_000_000
ADC_CLOCK_HZ = 37_500_000
ADC_CALIBRATION_CYCLE_COUNTER_HZ = 600_000_000
ADC_CALIBRATION_DEADLINE_US = 10_000
ADC_CALIBRATION_DEADLINE_CYCLES = (
    ADC_CALIBRATION_CYCLE_COUNTER_HZ * ADC_CALIBRATION_DEADLINE_US // 1_000_000
)

ADC_TRIGGER_PIT_CLOCK_HZ = 24_000_000
ADC_TRIGGER_DWT_CLOCK_HZ = 600_000_000
ADC_TRIGGER_GPIO_MASTER_RATE_HZ = GPIO_SAMPLE_RATE_HZ
ADC_TRIGGER_PAIR_RATE_HZ = ADC_PAIR_RATE_HZ
ADC_TRIGGER_IPG_CLOCK_HZ = ADC_IPG_CLOCK_HZ
ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL = 0
ADC_TRIGGER_PAIR_PIT_CHANNEL = 1
ADC_TRIGGER_GPIO_MASTER_PIT_LOAD = 5
ADC_TRIGGER_PAIR_PIT_LOAD = 3
ADC_TRIGGER_PREDIVIDER = 0
ADC_TRIGGER_CHAIN_LENGTH = 1
ADC_TRIGGER_XBAR_INPUTS = (57, 57)
ADC_TRIGGER_XBAR_OUTPUTS = (103, 107)
ADC_TRIGGER_QUEUES = (0, 4)
ADC_TRIGGER_INITIAL_DELAYS = (0, 75)
ADC_TRIGGER_EFFECTIVE_DELAYS = (1, 76)
ADC_TRIGGER_PHASE_IPG_CYCLES = 75
ADC_COMPLETION_EXPECTED_DWT_CYCLES = 300
ADC_COMPLETION_TOLERANCE_DWT_CYCLES = 120
ADC_TRIGGER_DIAGNOSTIC_DEADLINE_US = 2_000
ADC_TRIGGER_DIAGNOSTIC_DEADLINE_CYCLES = (
    ADC_TRIGGER_DWT_CLOCK_HZ * ADC_TRIGGER_DIAGNOSTIC_DEADLINE_US // 1_000_000
)

ADC_CONFIGURATION_INITIALIZED = 1
ADC_CONFIGURATION_NO_HARDWARE_AVERAGING = 2
ADC_CONFIGURATION_HIGH_SPEED = 4
ADC_CONFIGURATION_SHORTEST_SAMPLE = 8
ADC_CONFIGURATION_ROUTES_VALIDATED = 16
ADC_CONFIGURATION_READBACK_VALID = 32
ADC_CONFIGURATION_CALIBRATION_COMPLETE = 64
ADC_CONFIGURATION_PRIMARY_12_BIT = 128
ADC_CONFIGURATION_FALLBACK_10_BIT = 256
ADC_CONFIGURATION_COMMON_FLAGS = (
    ADC_CONFIGURATION_INITIALIZED
    | ADC_CONFIGURATION_NO_HARDWARE_AVERAGING
    | ADC_CONFIGURATION_HIGH_SPEED
    | ADC_CONFIGURATION_SHORTEST_SAMPLE
    | ADC_CONFIGURATION_ROUTES_VALIDATED
    | ADC_CONFIGURATION_READBACK_VALID
    | ADC_CONFIGURATION_CALIBRATION_COMPLETE
)
KNOWN_ADC_CONFIGURATION_FLAG_MASK = 0x01FF
KNOWN_ADC_INITIALIZATION_ERROR_MASK = 0x07FF
KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK = 0x00FF
KNOWN_ADC_TRIGGER_ERROR_MASK = 0x00007FFF

ADC_TRIGGER_CONFIGURED_STOPPED = 1
ADC_TRIGGER_CLOCKS_VALID = 2
ADC_TRIGGER_XBAR_ROUTES_VALID = 4
ADC_TRIGGER_QUEUES_VALID = 8
ADC_TRIGGER_HARDWARE_TRIGGER_VALID = 16
ADC_TRIGGER_ARM_SEQUENCE_EXERCISED = 32
ADC_TRIGGER_COMPLETION_TIMING_VALID = 64
ADC_TRIGGER_STOPPED_AFTER_DIAGNOSTIC = 128
ADC_TRIGGER_REQUIRED_FLAGS = KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK

CCM_PERCLK_MASK = 0x0000007F
CCM_PERCLK_24MHZ = 0x00000040
CCM_PIT_GATE_MASK = 0x00003000
CCM_ADC1_GATE_MASK = 0x00030000
CCM_ADC2_GATE_MASK = 0x00000300
CCM_XBAR_GATE_MASK = 0x00C00000
PIT_MDIS = 0x00000002
PIT_TCTRL_CHAIN = 0x00000004
ADC_ETC_ERROR_MASK = (1 << (16 + ADC_TRIGGER_QUEUES[0])) | (
    1 << (16 + ADC_TRIGGER_QUEUES[1])
)
ADC0_CHAIN_CONFIGURED = (1 << 13) | (1 << 4) | ADC_CHANNELS[0]
ADC1_CHAIN_CONFIGURED = (2 << 13) | (1 << 4) | ADC_CHANNELS[1]

PACKET_BUFFER_COUNT = 200
PACKET_PRIMARY_COUNT = 105
PACKET_RESERVE_COUNT = 95
PACKET_READY_QUEUE_CAPACITY = 200
PACKET_TRANSMIT_QUEUE_CAPACITY = 200
COMMAND_QUEUE_CAPACITY = 4
RESPONSE_QUEUE_CAPACITY = 4
SUPPORTED_CONFIGURATION_MASK = 0x003F
NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM = 4_000_000
NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM = 4_047_431

ADC_DATA = 0x01
GPIO_DATA = 0x02
INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
GPIO_CAPTURE_DIAGNOSTIC_REQUEST = 0x19
INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
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
    GPIO_CAPTURE_DIAGNOSTIC_REQUEST: GPIO_CAPTURE_DIAGNOSTIC_RESPONSE,
}
REQUEST_PAYLOAD_SIZE = {
    INFO_REQUEST: 0,
    CONFIGURE_REQUEST: 8,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
    GPIO_CAPTURE_DIAGNOSTIC_REQUEST: 0,
}
SUCCESS_PAYLOAD_SIZE = {
    INFO_RESPONSE: 376,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 1228,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
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
    """Dependency-free reference checksum for each data algorithm."""

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
    """Compute the exact wire checksum without substituting polynomials."""

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
        self._scan_start = 0
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
        self.high_water_bytes = max(self.high_water_bytes, self._buffered_bytes())
        frames: list[Frame] = []
        while True:
            magic_at = self.buffer.find(MAGIC_BYTES, self._scan_start)
            if magic_at < 0:
                retained = self._partial_magic_suffix()
                self._discard(self._buffered_bytes() - retained)
                break
            self._discard(magic_at - self._scan_start)
            if self._buffered_bytes() < HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.buffer, self._scan_start)
            try:
                total_length = self._validate_header(fields)
            except ProtocolFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            if self._buffered_bytes() < total_length:
                break
            payload_length = fields[8]
            payload_start = self._scan_start + HEADER_SIZE
            payload_end = payload_start + payload_length
            checksum_view = memoryview(self.buffer)[self._scan_start : payload_end]
            try:
                expected = compute_checksum(checksum_view, fields[5])
            except ProtocolFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            finally:
                checksum_view.release()
            actual = TRAILER.unpack_from(self.buffer, payload_end)[0]
            if actual != expected:
                self.checksum_errors += 1
                self._discard(1)
                continue
            payload_view = memoryview(self.buffer)[payload_start:payload_end]
            try:
                payload = payload_view.tobytes()
            finally:
                payload_view.release()
            frame = Frame(
                kind=fields[2],
                flags=fields[3],
                checksum_algorithm=fields[5],
                run_id=fields[9],
                sequence=fields[10],
                request_id=fields[11],
                first_sample_ticks=fields[12],
                item_count=fields[13],
                payload=payload,
                checksum=actual,
            )
            try:
                self._validate_payload(frame)
            except ProtocolFailure:
                self.payload_errors += 1
                self._discard(1)
                continue
            self._scan_start += total_length
            self.frames_decoded += 1
            frames.append(frame)

        self._compact()
        retained_bound = MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1
        if self._buffered_bytes() > retained_bound:
            raise ProtocolFailure(
                f"parser retained {self._buffered_bytes()} bytes; "
                f"bound is {retained_bound}"
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
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            period = (
                ADC_PAIR_PERIOD_TICKS if kind == ADC_DATA else GPIO_SAMPLE_PERIOD_TICKS
            )
            if checksum not in SUPPORTED_CHECKSUMS:
                raise ProtocolFailure(
                    f"host lacks checksum support for algorithm {checksum}"
                )
            if total_length != DATA_FRAME_BYTES or payload_length != DATA_PAYLOAD_BYTES:
                raise ProtocolFailure("data frame does not have the fixed shape")
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
            raise ProtocolFailure("control response does not use bootstrap checksum")
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
        payload = frame.payload
        if is_error and frame.kind != ERROR_RESPONSE:
            return
        if frame.kind == INFO_RESPONSE:
            reserved_ranges = (
                payload[1:2],
                payload[61:62],
                payload[118:120],
                payload[127:128],
                payload[154:156],
                payload[182:184],
                payload[230:232],
                payload[334:336],
            )
            if any(any(section) for section in reserved_ranges):
                raise ProtocolFailure("INFO reserved fields are nonzero")
            checksum_mask = struct.unpack_from("<I", payload, 8)[0]
            if not checksum_mask & (1 << payload[45]):
                raise ProtocolFailure("INFO selected checksum is not advertised")
        elif frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            if payload[1] or payload[7]:
                raise ProtocolFailure("configuration response reserved byte is nonzero")
        elif frame.kind == GET_STATUS_RESPONSE:
            if payload[1] or any(payload[226:228]) or any(payload[274:276]):
                raise ProtocolFailure("STATUS reserved fields are nonzero")
        elif frame.kind == STOP_RESPONSE:
            if payload[1] or any(payload[5:]):
                raise ProtocolFailure("STOP reserved fields are nonzero")
        elif frame.kind == RESET_STATS_RESPONSE and payload[1]:
            raise ProtocolFailure("RESET_STATS reserved byte is nonzero")
        elif frame.kind == ERROR_RESPONSE and (payload[1] or any(payload[6:])):
            raise ProtocolFailure("generic error reserved fields are nonzero")

    def _partial_magic_suffix(self) -> int:
        maximum = min(self._buffered_bytes(), len(MAGIC_BYTES) - 1)
        for length in range(maximum, 0, -1):
            if self.buffer.endswith(MAGIC_BYTES[:length], self._scan_start):
                return length
        return 0

    def _discard(self, count: int) -> None:
        if count > 0:
            self._scan_start += count
            self.bytes_discarded += count

    def _buffered_bytes(self) -> int:
        return len(self.buffer) - self._scan_start

    def _compact(self) -> None:
        if self._scan_start:
            del self.buffer[: self._scan_start]
            self._scan_start = 0


class SerialLink:
    """One-request-at-a-time link that services both streams while waiting."""

    def __init__(self, port: SerialPort) -> None:
        self.port = port
        self.parser = FrameParser()
        self.next_request_id = 1
        self.stale_responses = 0
        self.discarded_data_frames = 0
        self.maximum_read_bytes = 0
        self.accepted_requests = 0

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
                if not matched.flags:
                    self.accepted_requests += 1
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
                time.sleep(0.0001)

    def _read_once(self) -> list[Frame]:
        _chunk, frames = self._read_chunk_and_frames()
        return frames

    def _read_chunk_and_frames(self) -> tuple[bytes, list[Frame]]:
        chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        return chunk, self.parser.feed(chunk) if chunk else []


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
    return int(struct.unpack_from("<H", payload, offset)[0])


def _u32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", payload, offset)[0])


def _u64(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<Q", payload, offset)[0])


def decode_adc_metadata(
    payload: bytes,
    base: int,
    *,
    status_layout: bool = False,
) -> dict[str, int | tuple[int, int]]:
    """Decode the common INFO/STATUS ADC metadata block from its base."""

    calibration_states_offset = base - 2 if status_layout else base + 18
    route_offset = base + 18 if status_layout else base + 20
    clocks_offset = base + 24 if status_layout else base + 28
    trigger_offset = base + 48 if status_layout else base + 52
    return {
        "code_min": _u16(payload, base),
        "code_max": _u16(payload, base + 2),
        "reference": payload[base + 4],
        "clock_source": payload[base + 5],
        "clock_divider": payload[base + 6],
        "hardware_average_count": payload[base + 7],
        "reference_mv_nominal": _u16(payload, base + 8),
        "input_min_mv_nominal": _u16(payload, base + 10),
        "input_max_mv_nominal": _u16(payload, base + 12),
        "sample_time_adck": payload[base + 14],
        "conversion_mode": payload[base + 15],
        "configuration_flags": _u16(payload, base + 16),
        "calibration_states": (
            payload[calibration_states_offset],
            payload[calibration_states_offset + 1],
        ),
        "pins": (payload[route_offset], payload[route_offset + 1]),
        "peripherals": (payload[route_offset + 2], payload[route_offset + 3]),
        "channels": (payload[route_offset + 4], payload[route_offset + 5]),
        "ipg_clock_hz": _u32(payload, clocks_offset),
        "clock_hz": _u32(payload, clocks_offset + 4),
        "calibration_deadline_us": _u32(payload, clocks_offset + 8),
        "calibration_cycles": (
            _u32(payload, clocks_offset + 12),
            _u32(payload, clocks_offset + 16),
        ),
        "initialization_error_flags": _u32(payload, trigger_offset - 4),
        "trigger_configuration_flags": _u16(payload, trigger_offset),
        "trigger_error_flags": _u32(payload, trigger_offset + 4),
        "trigger_pit_clock_hz": _u32(payload, trigger_offset + 8),
        "trigger_dwt_clock_hz": _u32(payload, trigger_offset + 12),
        "trigger_gpio_master_rate_hz": _u32(payload, trigger_offset + 16),
        "trigger_pair_rate_hz": _u32(payload, trigger_offset + 20),
        "trigger_ipg_clock_hz": _u32(payload, trigger_offset + 24),
        "trigger_gpio_master_pit_channel": payload[trigger_offset + 28],
        "trigger_pair_pit_channel": payload[trigger_offset + 29],
        "trigger_gpio_master_pit_load": payload[trigger_offset + 30],
        "trigger_pair_pit_load": payload[trigger_offset + 31],
        "trigger_predivider": payload[trigger_offset + 32],
        "trigger_chain_length": payload[trigger_offset + 33],
        "trigger_xbar_inputs": (
            payload[trigger_offset + 34],
            payload[trigger_offset + 35],
        ),
        "trigger_xbar_outputs": (
            payload[trigger_offset + 36],
            payload[trigger_offset + 37],
        ),
        "trigger_queues": (
            payload[trigger_offset + 38],
            payload[trigger_offset + 39],
        ),
        "trigger_initial_delays": (
            _u16(payload, trigger_offset + 40),
            _u16(payload, trigger_offset + 42),
        ),
        "trigger_effective_delays": (
            _u16(payload, trigger_offset + 44),
            _u16(payload, trigger_offset + 46),
        ),
        "trigger_phase_ipg_cycles": _u16(payload, trigger_offset + 48),
        "trigger_ccm_cscmr1_configured": _u32(payload, trigger_offset + 52),
        "trigger_ccm_ccgr1_configured": _u32(payload, trigger_offset + 56),
        "trigger_ccm_ccgr2_configured": _u32(payload, trigger_offset + 60),
        "trigger_pit_mcr_configured": _u32(payload, trigger_offset + 64),
        "trigger_gpio_master_tctrl_configured": _u32(payload, trigger_offset + 68),
        "trigger_pair_tctrl_configured": _u32(payload, trigger_offset + 72),
        "adc_etc_ctrl_configured": _u32(payload, trigger_offset + 76),
        "trigger_ctrl_configured": (
            _u32(payload, trigger_offset + 80),
            _u32(payload, trigger_offset + 84),
        ),
        "trigger_counter_configured": (
            _u32(payload, trigger_offset + 88),
            _u32(payload, trigger_offset + 92),
        ),
        "trigger_chain_configured": (
            _u32(payload, trigger_offset + 96),
            _u32(payload, trigger_offset + 100),
        ),
        "adc_etc_done0_1_irq_final": _u32(payload, trigger_offset + 104),
        "adc_etc_done2_err_irq_final": _u32(payload, trigger_offset + 108),
        "completion_counts": (
            _u32(payload, trigger_offset + 112),
            _u32(payload, trigger_offset + 116),
        ),
        "completion_delta_cycles": _u32(payload, trigger_offset + 120),
        "completion_expected_delta_cycles": _u32(payload, trigger_offset + 124),
        "completion_tolerance_cycles": _u32(payload, trigger_offset + 128),
        "completion_diagnostic_elapsed_cycles": _u32(payload, trigger_offset + 132),
        "trigger_error_count": _u32(payload, trigger_offset + 136),
        "trigger_xbar_sel_configured": (
            _u16(payload, trigger_offset + 140),
            _u16(payload, trigger_offset + 142),
        ),
    }


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
        "adc_metadata": decode_adc_metadata(payload, 128),
        "applied_stream_mask": payload[324],
        "applied_source": payload[325],
        "supported_configuration_mask": _u16(payload, 326),
        "data_payload_bytes": _u16(payload, 328),
        "adc_pairs_per_frame": _u16(payload, 330),
        "gpio_samples_per_frame": _u16(payload, 332),
        "frame_coverage_ticks": _u32(payload, 336),
        "adc_dma_ring_depth": payload[340],
        "adc_pair_bytes": payload[341],
        "adc_edma_channels": tuple(payload[342:344]),
        "adc_edma_priorities": tuple(payload[344:346]),
        "adc_dmamux_sources": tuple(payload[346:348]),
        "adc_dma_irq_priority": payload[348],
        "gpio_dma_irq_priority": payload[349],
        "adc_pairs_per_buffer": _u16(payload, 350),
        "adc_dma_ring_bytes": _u32(payload, 352),
        "packet_buffer_count": _u16(payload, 356),
        "packet_primary_count": _u16(payload, 358),
        "packet_reserve_count": _u16(payload, 360),
        "packet_ready_queue_capacity": _u16(payload, 362),
        "packet_transmit_queue_capacity": _u16(payload, 364),
        "command_queue_capacity": payload[366],
        "response_queue_capacity": payload[367],
        "nominal_payload_bytes_per_second_per_stream": _u32(payload, 368),
        "nominal_framed_bytes_per_second_per_stream": _u32(payload, 372),
    }


def decode_configuration(frame: Frame, expected_kind: int) -> tuple[int, int, int, int]:
    response_success(frame, expected_kind)
    streams, source, checksum, reserved, frame_bytes = CONFIGURATION.unpack_from(
        frame.payload, 4
    )
    if reserved:
        raise ProtocolFailure("applied configuration reserved byte is nonzero")
    return streams, source, checksum, frame_bytes


_STATUS_BASE_FIELDS = {
    "device_state": ("B", 4),
    "stream_mask": ("B", 5),
    "source": ("B", 6),
    "checksum": ("B", 7),
    "data_frame_bytes": ("I", 8),
    "adc_frames_emitted": ("Q", 12),
    "gpio_frames_emitted": ("Q", 20),
    "adc_items_dropped": ("Q", 28),
    "gpio_items_dropped": ("Q", 36),
    "parser_errors": ("I", 44),
    "transport_errors": ("I", 48),
    "stats_generation": ("I", 52),
}
_STATUS_GPIO_U64_FIELDS = (
    "gpio_samples_captured",
    "gpio_samples_packed",
    "gpio_samples_framed",
    "gpio_samples_transmitted",
    "gpio_raw_samples_lost",
    "gpio_packer_samples_dropped",
    "gpio_raw_ring_overruns",
    "gpio_dma_major_loops",
)
_STATUS_GPIO_U16_FIELDS = (
    "gpio_raw_ready_depth",
    "gpio_raw_ready_high_water",
    "gpio_packed_ready_depth",
    "gpio_packed_ready_high_water",
    "packet_ready_depth",
    "packet_transmit_depth",
    "packet_owned_high_water",
    "gpio_processing_cpu_basis_points",
)
_STATUS_GPIO_U32_FIELDS = (
    "gpio_hardware_errors",
    "gpio_raw_invariant_errors",
    "gpio_packer_source_errors",
    "gpio_packer_pipeline_errors",
    "gpio_packer_chronology_errors",
    "gpio_resource_conflicts",
    "gpio_start_errors",
    "gpio_stop_errors",
    "gpio_stale_dma_completions",
)
_STATUS_ADC_U64_FIELDS = (
    "adc0_dma_major_loops",
    "adc1_dma_major_loops",
    "adc0_dma_results",
    "adc1_dma_results",
    "adc_paired_major_loops",
    "adc_buffers_completed",
    "adc_buffers_acquired",
    "adc_buffers_released",
    "adc_pairs_captured",
    "adc_pairs_delivered",
    "adc_pairs_framed",
    "adc_pairs_transmitted",
    "adc_raw_pairs_lost",
    "adc_stop_pairs_discarded",
    "adc_incomplete_conversions",
    "adc_overwritten_conversions",
    "adc_raw_ring_overruns",
    "adc_incomplete_buffers",
)
_STATUS_ADC_U32_FIELDS = (
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
)
_STATUS_PIPELINE_U64_FIELDS = (
    "adc_frames_generated",
    "adc_items_generated",
    "adc_frames_framed_pipeline",
    "adc_items_framed_pipeline",
    "adc_items_emitted",
    "adc_frames_transmitted",
    "adc_items_transmitted_pipeline",
    "adc_frames_dropped",
    "gpio_frames_generated",
    "gpio_items_generated",
    "gpio_frames_framed_pipeline",
    "gpio_items_framed_pipeline",
    "gpio_items_emitted",
    "gpio_frames_transmitted",
    "gpio_items_transmitted_pipeline",
    "gpio_frames_dropped",
    "adc_payload_bytes_produced",
    "adc_payload_bytes_framed",
    "adc_payload_bytes_emitted",
    "adc_payload_bytes_transmitted",
    "adc_payload_bytes_dropped",
    "adc_framed_bytes_framed",
    "adc_framed_bytes_emitted",
    "adc_framed_bytes_transmitted",
    "gpio_payload_bytes_produced",
    "gpio_payload_bytes_framed",
    "gpio_payload_bytes_emitted",
    "gpio_payload_bytes_transmitted",
    "gpio_payload_bytes_dropped",
    "gpio_framed_bytes_framed",
    "gpio_framed_bytes_emitted",
    "gpio_framed_bytes_transmitted",
)
_STATUS_QUEUE_U16_FIELDS = (
    "adc_packet_ready_depth",
    "gpio_packet_ready_depth",
    "adc_packet_transmit_depth",
    "gpio_packet_transmit_depth",
    "adc_packet_ready_high_water",
    "gpio_packet_ready_high_water",
    "adc_packet_transmit_high_water",
    "gpio_packet_transmit_high_water",
    "packet_ready_high_water",
    "packet_transmit_high_water",
)
_STATUS_PACKET_U64_FIELDS = (
    "packet_frames_promoted",
    "packet_fairness_deferrals",
    "packet_accounted_frame_skew",
    "data_payload_bytes_transmitted",
    "data_framed_bytes_transmitted",
)
_STATUS_PACKET_U32_FIELDS = (
    "packet_pool_exhaustions",
    "packet_invalid_operations",
    "packet_encoding_rejections",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
)
_STATUS_DIAGNOSTIC_U32_FIELDS = (
    "commands_accepted",
    "commands_rejected",
    "bad_checksums",
    "bad_lengths",
    "bad_types",
    "bad_versions",
    "timeouts",
    "partial_usb_writes",
    "state_errors",
)
_STATUS_USB_U32_FIELDS = (
    "usb_short_capacity_deferrals",
    "usb_rx_stall_events",
    "usb_tx_stall_events",
    "usb_io_errors",
)
_STATUS_USB_U16_FIELDS = (
    "usb_command_queue_depth",
    "usb_response_queue_depth",
    "usb_lower_priority_queue_depth",
    "usb_command_queue_high_water",
    "usb_response_queue_high_water",
    "usb_active_frame_bytes_sent",
)

_STATUS_NON_MONOTONIC_FIELDS = frozenset(
    {
        "device_state",
        "stream_mask",
        "source",
        "checksum",
        "data_frame_bytes",
        "stats_generation",
        "gpio_raw_ready_depth",
        "gpio_packed_ready_depth",
        "packet_ready_depth",
        "packet_transmit_depth",
        "gpio_processing_cpu_basis_points",
        "adc_raw_ready_depth",
        "adc_packet_ready_depth",
        "gpio_packet_ready_depth",
        "adc_packet_transmit_depth",
        "gpio_packet_transmit_depth",
        "packet_accounted_frame_skew",
        "usb_command_queue_depth",
        "usb_response_queue_depth",
        "usb_lower_priority_queue_depth",
        "usb_active_frame_bytes_sent",
    }
)


def _decode_run(
    payload: bytes,
    offset: int,
    code: str,
    names: tuple[str, ...],
) -> dict[str, int]:
    width = struct.calcsize("<" + code)
    return {
        name: int(struct.unpack_from("<" + code, payload, offset + index * width)[0])
        for index, name in enumerate(names)
    }


@dataclass(frozen=True)
class StatusSnapshot:
    """Decoded complete STATUS telemetry without generated project code."""

    values: dict[str, int]
    adc_metadata: dict[str, int | tuple[int, int]]
    adc_resolution_bits: int
    adc_container_bytes: int

    def __getattr__(self, name: str) -> int:
        try:
            return self.values[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def monotonic_counter_items(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (name, self.values[name])
            for name in sorted(self.values)
            if name not in _STATUS_NON_MONOTONIC_FIELDS
        )

    def regressions_from(self, previous: StatusSnapshot) -> dict[str, tuple[int, int]]:
        before = dict(previous.monotonic_counter_items())
        return {
            name: (before[name], current)
            for name, current in self.monotonic_counter_items()
            if current < before[name]
        }


def decode_status(frame: Frame) -> StatusSnapshot:
    response_success(frame, GET_STATUS_RESPONSE)
    payload = frame.payload
    values: dict[str, int] = {}
    for name, (code, offset) in _STATUS_BASE_FIELDS.items():
        values[name] = int(struct.unpack_from("<" + code, payload, offset)[0])
    values.update(_decode_run(payload, 56, "Q", _STATUS_GPIO_U64_FIELDS))
    values.update(_decode_run(payload, 120, "H", _STATUS_GPIO_U16_FIELDS))
    values.update(_decode_run(payload, 136, "I", _STATUS_GPIO_U32_FIELDS))
    values.update(_decode_run(payload, 368, "Q", _STATUS_ADC_U64_FIELDS))
    values["adc_raw_ready_depth"] = _u16(payload, 512)
    values["adc_raw_ready_high_water"] = _u16(payload, 514)
    values.update(_decode_run(payload, 516, "I", _STATUS_ADC_U32_FIELDS))
    values.update(_decode_run(payload, 576, "Q", _STATUS_PIPELINE_U64_FIELDS))
    values.update(_decode_run(payload, 832, "H", _STATUS_QUEUE_U16_FIELDS))
    values.update(_decode_run(payload, 852, "Q", _STATUS_PACKET_U64_FIELDS))
    values.update(_decode_run(payload, 892, "I", _STATUS_PACKET_U32_FIELDS))
    values.update(_decode_run(payload, 912, "I", _STATUS_DIAGNOSTIC_U32_FIELDS))
    values.update(_decode_run(payload, 948, "I", _STATUS_USB_U32_FIELDS))
    values.update(_decode_run(payload, 964, "H", _STATUS_USB_U16_FIELDS))
    return StatusSnapshot(
        values=values,
        adc_metadata=decode_adc_metadata(payload, 176, status_layout=True),
        adc_resolution_bits=payload[172],
        adc_container_bytes=payload[173],
    )


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


@dataclass(frozen=True)
class ChannelStimulus:
    """Machine-readable accepted-code envelope for one analog input."""

    pin: str
    minimum_code: int
    maximum_code: int
    mean_minimum_code: float | None = None
    mean_maximum_code: float | None = None


@dataclass(frozen=True)
class FixtureStimulus:
    """Validated optional external ADC fixture declaration."""

    fixture_id: str
    stimulus_id: str
    channels: tuple[ChannelStimulus, ChannelStimulus]

    @property
    def grades_analog_quality(self) -> bool:
        return all(
            channel.mean_minimum_code is not None
            and channel.mean_maximum_code is not None
            for channel in self.channels
        )


def _fixture_number(value: object, name: str, *, optional: bool) -> float | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(  # noqa: TRY004 - one configuration-error contract
            f"ADC fixture {name} must be a finite number"
        )
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"ADC fixture {name} must be a finite number")
    return converted


def _fixture_code(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(  # noqa: TRY004 - one configuration-error contract
            f"ADC fixture {name} must be an integer ADC code"
        )
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"ADC fixture {name} must be a uint16 ADC code")
    return value


def load_fixture_stimulus(raw: str | None) -> FixtureStimulus | None:
    """Parse a strict optional analog-stimulus declaration from the rig."""

    if raw is None or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("ADC fixture stimulus is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004 - one configuration-error contract
            "ADC fixture stimulus must be a JSON object"
        )
    if set(value) != {"schema", "fixture_id", "stimulus_id", "channels"}:
        raise ValueError("ADC fixture stimulus contains missing or unknown fields")
    if value["schema"] != "teensy-daq-adc-stimulus-v1":
        raise ValueError("ADC fixture stimulus schema is unsupported")
    fixture_id = value["fixture_id"]
    stimulus_id = value["stimulus_id"]
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise ValueError("ADC fixture fixture_id must be a nonempty string")
    if not isinstance(stimulus_id, str) or not stimulus_id.strip():
        raise ValueError("ADC fixture stimulus_id must be a nonempty string")
    channels = value["channels"]
    if not isinstance(channels, dict) or set(channels) != {"adc0", "adc1"}:
        raise ValueError("ADC fixture channels must contain exactly adc0 and adc1")

    parsed: list[ChannelStimulus] = []
    for index, key in enumerate(("adc0", "adc1")):
        channel = channels[key]
        if not isinstance(channel, dict):
            raise ValueError(  # noqa: TRY004 - one configuration-error contract
                f"ADC fixture {key} must be an object"
            )
        required = {"pin", "minimum_code", "maximum_code"}
        optional = {"mean_minimum_code", "mean_maximum_code"}
        if not required <= set(channel) or set(channel) - required - optional:
            raise ValueError(f"ADC fixture {key} fields are incomplete or unknown")
        pin = channel["pin"]
        expected_pin = f"A{index}"
        if pin != expected_pin:
            raise ValueError(f"ADC fixture {key} must declare pin {expected_pin}")
        minimum = _fixture_code(channel["minimum_code"], f"{key}.minimum_code")
        maximum = _fixture_code(channel["maximum_code"], f"{key}.maximum_code")
        mean_minimum = _fixture_number(
            channel.get("mean_minimum_code"),
            f"{key}.mean_minimum_code",
            optional=True,
        )
        mean_maximum = _fixture_number(
            channel.get("mean_maximum_code"),
            f"{key}.mean_maximum_code",
            optional=True,
        )
        if minimum > maximum:
            raise ValueError(f"ADC fixture {key} minimum exceeds maximum")
        if (mean_minimum is None) != (mean_maximum is None):
            raise ValueError(f"ADC fixture {key} must provide both mean bounds")
        if (
            mean_minimum is not None
            and mean_maximum is not None
            and (
                mean_minimum > mean_maximum
                or mean_minimum < minimum
                or mean_maximum > maximum
            )
        ):
            raise ValueError(f"ADC fixture {key} mean bounds are inconsistent")
        parsed.append(
            ChannelStimulus(
                pin,
                minimum,
                maximum,
                mean_minimum,
                mean_maximum,
            )
        )
    return FixtureStimulus(fixture_id, stimulus_id, (parsed[0], parsed[1]))


class Evidence:
    """Structured expected-versus-actual checks for remote grading."""

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


def stable_identity(info: dict[str, object]) -> tuple[object, ...]:
    return tuple(
        info[name]
        for name in (
            "protocol_version",
            "hardware_serial",
            "firmware_version",
            "board_id",
            "mcu_id",
            "build_id",
            "supported_stream_mask",
            "supported_source_mask",
            "supported_configuration_mask",
            "capability_bits",
        )
    )


def synchronize(link: SerialLink) -> dict[str, object]:
    """Obtain two stable INFO identities after bounded reset-noise recovery."""

    previous: dict[str, object] | None = None
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, _latency = link.exchange(INFO_REQUEST, timeout=SYNC_DEADLINE_SECONDS)
            current = decode_info(frame)
        except (DeadlineExpired, ProtocolFailure) as error:
            last_error = str(error)
            emit_event("sync_retry", attempt=attempt, error=last_error)
            continue
        if previous is not None:
            if stable_identity(previous) != stable_identity(current):
                raise ProtocolFailure("INFO identity changed during synchronization")
            emit_event("synchronized", attempts=attempt)
            return current
        previous = current
    raise DeadlineExpired(
        f"stable INFO synchronization failed after {SYNC_ATTEMPTS} attempts: "
        f"{last_error}"
    )


def _metadata_int(
    metadata: dict[str, int | tuple[int, int]],
    name: str,
) -> int:
    value = metadata[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolFailure(f"ADC metadata {name} is not an integer")
    return value


def _metadata_pair(
    metadata: dict[str, int | tuple[int, int]],
    name: str,
) -> tuple[int, int]:
    value = metadata[name]
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise ProtocolFailure(f"ADC metadata {name} is not an integer pair")
    return value


def _info_int(info: dict[str, object], name: str) -> int:
    value = info[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolFailure(f"INFO {name} is not an integer")
    return value


def _raise_if_new_failures(evidence: Evidence, before: int, context: str) -> None:
    if len(evidence.failures) != before:
        raise ProtocolFailure(f"{context} grading failed")


def grade_adc_metadata(
    evidence: Evidence,
    metadata: dict[str, int | tuple[int, int]],
    *,
    resolution_bits: int,
    label: str,
) -> None:
    """Grade calibration, routes, common schedule, and register evidence."""

    before = len(evidence.failures)
    expected_mode = (
        ADC_PRIMARY_CONVERSION_MODE
        if resolution_bits == ADC_PRIMARY_RESOLUTION_BITS
        else ADC_FALLBACK_CONVERSION_MODE
    )
    resolution_flag = (
        ADC_CONFIGURATION_PRIMARY_12_BIT
        if resolution_bits == ADC_PRIMARY_RESOLUTION_BITS
        else ADC_CONFIGURATION_FALLBACK_10_BIT
    )
    forbidden_flag = (
        ADC_CONFIGURATION_FALLBACK_10_BIT
        if resolution_bits == ADC_PRIMARY_RESOLUTION_BITS
        else ADC_CONFIGURATION_PRIMARY_12_BIT
    )
    exact_scalars = {
        "code_min": ADC_CODE_MIN,
        "code_max": (1 << resolution_bits) - 1,
        "reference": ADC_REFERENCE,
        "clock_source": ADC_CLOCK_SOURCE,
        "clock_divider": ADC_CLOCK_DIVIDER,
        "hardware_average_count": ADC_HARDWARE_AVERAGE_COUNT,
        "reference_mv_nominal": ADC_REFERENCE_MV_NOMINAL,
        "input_min_mv_nominal": ADC_INPUT_MIN_MV_NOMINAL,
        "input_max_mv_nominal": ADC_INPUT_MAX_MV_NOMINAL,
        "sample_time_adck": ADC_SAMPLE_TIME_ADCK,
        "conversion_mode": expected_mode,
        "configuration_flags": ADC_CONFIGURATION_COMMON_FLAGS | resolution_flag,
        "initialization_error_flags": 0,
        "trigger_configuration_flags": ADC_TRIGGER_REQUIRED_FLAGS,
        "trigger_error_flags": 0,
        "trigger_pit_clock_hz": ADC_TRIGGER_PIT_CLOCK_HZ,
        "trigger_dwt_clock_hz": ADC_TRIGGER_DWT_CLOCK_HZ,
        "trigger_gpio_master_rate_hz": ADC_TRIGGER_GPIO_MASTER_RATE_HZ,
        "trigger_pair_rate_hz": ADC_TRIGGER_PAIR_RATE_HZ,
        "trigger_ipg_clock_hz": ADC_TRIGGER_IPG_CLOCK_HZ,
        "trigger_gpio_master_pit_channel": ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL,
        "trigger_pair_pit_channel": ADC_TRIGGER_PAIR_PIT_CHANNEL,
        "trigger_gpio_master_pit_load": ADC_TRIGGER_GPIO_MASTER_PIT_LOAD,
        "trigger_pair_pit_load": ADC_TRIGGER_PAIR_PIT_LOAD,
        "trigger_predivider": ADC_TRIGGER_PREDIVIDER,
        "trigger_chain_length": ADC_TRIGGER_CHAIN_LENGTH,
        "trigger_phase_ipg_cycles": ADC_TRIGGER_PHASE_IPG_CYCLES,
        "completion_expected_delta_cycles": ADC_COMPLETION_EXPECTED_DWT_CYCLES,
        "completion_tolerance_cycles": ADC_COMPLETION_TOLERANCE_DWT_CYCLES,
        "trigger_error_count": 0,
    }
    for name, expected in exact_scalars.items():
        evidence.equal(f"{label}.{name}", expected, _metadata_int(metadata, name))

    exact_pairs = {
        "calibration_states": (1, 1),
        "pins": ADC_PINS,
        "peripherals": ADC_PERIPHERALS,
        "channels": ADC_CHANNELS,
        "trigger_xbar_inputs": ADC_TRIGGER_XBAR_INPUTS,
        "trigger_xbar_outputs": ADC_TRIGGER_XBAR_OUTPUTS,
        "trigger_queues": ADC_TRIGGER_QUEUES,
        "trigger_initial_delays": ADC_TRIGGER_INITIAL_DELAYS,
        "trigger_effective_delays": ADC_TRIGGER_EFFECTIVE_DELAYS,
        "trigger_ctrl_configured": (0, 0),
        "trigger_counter_configured": ADC_TRIGGER_INITIAL_DELAYS,
        "trigger_chain_configured": (
            ADC0_CHAIN_CONFIGURED,
            ADC1_CHAIN_CONFIGURED,
        ),
    }
    for name, expected_pair in exact_pairs.items():
        evidence.equal(f"{label}.{name}", expected_pair, _metadata_pair(metadata, name))

    flags = _metadata_int(metadata, "configuration_flags")
    evidence.equal(
        f"{label}.configuration_reserved_flags",
        0,
        flags & ~KNOWN_ADC_CONFIGURATION_FLAG_MASK,
    )
    evidence.equal(f"{label}.forbidden_resolution_flag", 0, flags & forbidden_flag)
    evidence.equal(
        f"{label}.initialization_reserved_errors",
        0,
        _metadata_int(metadata, "initialization_error_flags")
        & ~KNOWN_ADC_INITIALIZATION_ERROR_MASK,
    )
    evidence.equal(
        f"{label}.trigger_reserved_flags",
        0,
        _metadata_int(metadata, "trigger_configuration_flags")
        & ~KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK,
    )
    evidence.equal(
        f"{label}.trigger_reserved_errors",
        0,
        _metadata_int(metadata, "trigger_error_flags") & ~KNOWN_ADC_TRIGGER_ERROR_MASK,
    )
    evidence.equal(
        f"{label}.ipg_clock_hz",
        ADC_IPG_CLOCK_HZ,
        _metadata_int(metadata, "ipg_clock_hz"),
    )
    evidence.equal(
        f"{label}.clock_hz", ADC_CLOCK_HZ, _metadata_int(metadata, "clock_hz")
    )
    evidence.equal(
        f"{label}.calibration_deadline_us",
        ADC_CALIBRATION_DEADLINE_US,
        _metadata_int(metadata, "calibration_deadline_us"),
    )
    for index, cycles in enumerate(_metadata_pair(metadata, "calibration_cycles")):
        evidence.check(
            f"{label}.adc{index}_calibration_cycles",
            f"1..{ADC_CALIBRATION_DEADLINE_CYCLES}",
            cycles,
            1 <= cycles <= ADC_CALIBRATION_DEADLINE_CYCLES,
        )

    initial_delays = _metadata_pair(metadata, "trigger_initial_delays")
    effective_delays = _metadata_pair(metadata, "trigger_effective_delays")
    phase_cycles = effective_delays[1] - effective_delays[0]
    phase_ticks = phase_cycles * TIMESTAMP_HZ // ADC_TRIGGER_IPG_CLOCK_HZ
    evidence.equal(
        f"{label}.delay_hardware_formula",
        (initial_delays[0] + 1, initial_delays[1] + 1),
        effective_delays,
    )
    evidence.equal(
        f"{label}.phase_cycle_arithmetic", ADC_TRIGGER_PHASE_IPG_CYCLES, phase_cycles
    )
    evidence.equal(f"{label}.phase_tick_arithmetic", ADC1_PHASE_TICKS, phase_ticks)
    evidence.equal(
        f"{label}.gpio_to_adc_event_ratio",
        4,
        _metadata_int(metadata, "trigger_gpio_master_rate_hz")
        // _metadata_int(metadata, "trigger_pair_rate_hz"),
    )
    evidence.equal(
        f"{label}.pit_master_rate_arithmetic",
        GPIO_SAMPLE_RATE_HZ,
        ADC_TRIGGER_PIT_CLOCK_HZ // (ADC_TRIGGER_GPIO_MASTER_PIT_LOAD + 1),
    )
    evidence.equal(
        f"{label}.pit_chain_rate_arithmetic",
        ADC_PAIR_RATE_HZ,
        GPIO_SAMPLE_RATE_HZ // (ADC_TRIGGER_PAIR_PIT_LOAD + 1),
    )

    cscmr1 = _metadata_int(metadata, "trigger_ccm_cscmr1_configured")
    ccgr1 = _metadata_int(metadata, "trigger_ccm_ccgr1_configured")
    ccgr2 = _metadata_int(metadata, "trigger_ccm_ccgr2_configured")
    evidence.equal(
        f"{label}.register.perclk", CCM_PERCLK_24MHZ, cscmr1 & CCM_PERCLK_MASK
    )
    evidence.equal(
        f"{label}.register.pit_adc_gates",
        CCM_PIT_GATE_MASK | CCM_ADC1_GATE_MASK | CCM_ADC2_GATE_MASK,
        ccgr1 & (CCM_PIT_GATE_MASK | CCM_ADC1_GATE_MASK | CCM_ADC2_GATE_MASK),
    )
    evidence.equal(
        f"{label}.register.xbar_gate", CCM_XBAR_GATE_MASK, ccgr2 & CCM_XBAR_GATE_MASK
    )
    evidence.equal(
        f"{label}.register.pit_enabled",
        0,
        _metadata_int(metadata, "trigger_pit_mcr_configured") & PIT_MDIS,
    )
    evidence.equal(
        f"{label}.register.master_stopped",
        0,
        _metadata_int(metadata, "trigger_gpio_master_tctrl_configured"),
    )
    evidence.equal(
        f"{label}.register.pair_chained_stopped",
        PIT_TCTRL_CHAIN,
        _metadata_int(metadata, "trigger_pair_tctrl_configured"),
    )
    evidence.equal(
        f"{label}.register.adc_etc_stopped",
        ADC_TRIGGER_PREDIVIDER << 16,
        _metadata_int(metadata, "adc_etc_ctrl_configured"),
    )
    evidence.equal(
        f"{label}.register.xbar_selected_inputs",
        ADC_TRIGGER_XBAR_INPUTS,
        tuple(
            (value >> 8) & 0xFF
            for value in _metadata_pair(metadata, "trigger_xbar_sel_configured")
        ),
    )
    evidence.equal(
        f"{label}.register.adc_etc_error_bits",
        0,
        _metadata_int(metadata, "adc_etc_done2_err_irq_final") & ADC_ETC_ERROR_MASK,
    )
    completion_counts = _metadata_pair(metadata, "completion_counts")
    evidence.check(
        f"{label}.completion_counts",
        "equal nonzero converter counts",
        completion_counts,
        completion_counts[0] == completion_counts[1] and completion_counts[0] > 0,
    )
    completion_delta = _metadata_int(metadata, "completion_delta_cycles")
    evidence.check(
        f"{label}.completion_timing_cycles",
        f"{ADC_COMPLETION_EXPECTED_DWT_CYCLES} +/- "
        f"{ADC_COMPLETION_TOLERANCE_DWT_CYCLES}",
        completion_delta,
        abs(completion_delta - ADC_COMPLETION_EXPECTED_DWT_CYCLES)
        <= ADC_COMPLETION_TOLERANCE_DWT_CYCLES,
    )
    diagnostic_elapsed = _metadata_int(metadata, "completion_diagnostic_elapsed_cycles")
    evidence.check(
        f"{label}.completion_diagnostic_elapsed_cycles",
        f"1..{2 * ADC_TRIGGER_DIAGNOSTIC_DEADLINE_CYCLES}",
        diagnostic_elapsed,
        1 <= diagnostic_elapsed <= 2 * ADC_TRIGGER_DIAGNOSTIC_DEADLINE_CYCLES,
    )
    _raise_if_new_failures(evidence, before, f"{label} ADC metadata")


def grade_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> int:
    """Pin identity, rates, physical routes, memory geometry, and schedule."""

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
        "adc_container_bytes": ADC_CONTAINER_BYTES,
        "gpio_pin_count": len(GPIO_PINS_BY_BIT),
        "gpio_pin_map": GPIO_PINS_BY_BIT,
        "board_id": 1,
        "mcu_id": 1,
        "gpio_packed_width_bits": GPIO_PACKED_WIDTH_BITS,
        "gpio_raw_ring_depth": GPIO_RAW_RING_DEPTH,
        "gpio_packed_ring_depth": GPIO_PACKED_RING_DEPTH,
        "gpio_raw_samples_per_buffer": GPIO_RAW_SAMPLES_PER_BUFFER,
        "gpio_raw_ring_bytes": GPIO_RAW_RING_BYTES,
        "gpio_packed_ring_bytes": GPIO_PACKED_RING_BYTES,
        "gpio_packet_buffer_count": PACKET_BUFFER_COUNT,
        "gpio_pit_channel": GPIO_PIT_CHANNEL,
        "gpio_xbar_input": GPIO_XBAR_INPUT,
        "gpio_xbar_output": GPIO_XBAR_OUTPUT,
        "gpio_edma_channel": GPIO_EDMA_CHANNEL,
        "gpio_dmamux_source": GPIO_DMAMUX_SOURCE,
        "gpio_edma_priority": GPIO_EDMA_PRIORITY,
        "gpio_xbar_active_edge": GPIO_XBAR_ACTIVE_EDGE,
        "applied_stream_mask": STREAM_NONE,
        "applied_source": SOURCE_HARDWARE,
        "supported_configuration_mask": SUPPORTED_CONFIGURATION_MASK,
        "data_payload_bytes": DATA_PAYLOAD_BYTES,
        "adc_pairs_per_frame": ADC_PAIRS_PER_FRAME,
        "gpio_samples_per_frame": GPIO_SAMPLES_PER_FRAME,
        "frame_coverage_ticks": FRAME_COVERAGE_TICKS,
        "adc_dma_ring_depth": ADC_DMA_RING_DEPTH,
        "adc_pair_bytes": ADC_PAIR_BYTES,
        "adc_edma_channels": ADC_EDMA_CHANNELS,
        "adc_edma_priorities": ADC_EDMA_PRIORITIES,
        "adc_dmamux_sources": ADC_DMAMUX_SOURCES,
        "adc_dma_irq_priority": ADC_DMA_IRQ_PRIORITY,
        "gpio_dma_irq_priority": GPIO_DMA_IRQ_PRIORITY,
        "adc_pairs_per_buffer": ADC_PAIRS_PER_FRAME,
        "adc_dma_ring_bytes": ADC_DMA_RING_BYTES,
        "packet_buffer_count": PACKET_BUFFER_COUNT,
        "packet_primary_count": PACKET_PRIMARY_COUNT,
        "packet_reserve_count": PACKET_RESERVE_COUNT,
        "packet_ready_queue_capacity": PACKET_READY_QUEUE_CAPACITY,
        "packet_transmit_queue_capacity": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "command_queue_capacity": COMMAND_QUEUE_CAPACITY,
        "response_queue_capacity": RESPONSE_QUEUE_CAPACITY,
        "nominal_payload_bytes_per_second_per_stream": (
            NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM
        ),
        "nominal_framed_bytes_per_second_per_stream": (
            NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM
        ),
    }
    for name, expected in exact.items():
        evidence.equal(f"identity.{name}", expected, info[name])

    firmware_version = info["firmware_version"]
    evidence.check(
        "identity.minimum_firmware",
        ">= (0, 7, 0)",
        firmware_version,
        isinstance(firmware_version, tuple)
        and len(firmware_version) == 3
        and all(isinstance(part, int) for part in firmware_version)
        and firmware_version >= (0, 7, 0),
    )
    build_id = info["build_id"]
    evidence.check(
        "identity.build_id",
        expected_build_id or "tdaq-<16 lowercase hex>",
        build_id,
        isinstance(build_id, str)
        and re.fullmatch(r"tdaq-[0-9a-f]{16}", build_id) is not None
        and (expected_build_id is None or build_id == expected_build_id),
    )
    hardware_serial = _info_int(info, "hardware_serial")
    evidence.check(
        "identity.hardware_serial",
        expected_hardware_serial or "nonzero uint32",
        hardware_serial,
        1 <= hardware_serial <= 0xFFFFFFFF
        and (
            expected_hardware_serial is None
            or hardware_serial == expected_hardware_serial
        ),
    )
    selected_checksum = _info_int(info, "data_checksum_algorithm")
    evidence.check(
        "identity.selected_checksum",
        "advertised enabled algorithm",
        selected_checksum,
        selected_checksum in SUPPORTED_CHECKSUMS
        and bool(SUPPORTED_CHECKSUM_MASK & (1 << selected_checksum)),
    )
    resolution_bits = _info_int(info, "adc_resolution_bits")
    evidence.check(
        "identity.adc_resolution_bits",
        "12-bit primary or explicit 10-bit fallback",
        resolution_bits,
        resolution_bits in {ADC_PRIMARY_RESOLUTION_BITS, ADC_FALLBACK_RESOLUTION_BITS},
    )
    diagnostic_mode = _info_int(info, "gpio_capture_diagnostic_mode")
    diagnostic_flags = _info_int(info, "gpio_capture_diagnostic_flags")
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
    evidence.equal(
        "identity.equal_frame_coverage",
        _info_int(info, "adc_pairs_per_frame")
        * _info_int(info, "adc_pair_period_ticks"),
        _info_int(info, "gpio_samples_per_frame")
        * _info_int(info, "gpio_sample_period_ticks"),
    )
    evidence.equal(
        "identity.packet_bank_partition",
        _info_int(info, "packet_buffer_count"),
        _info_int(info, "packet_primary_count")
        + _info_int(info, "packet_reserve_count"),
    )
    metadata = info["adc_metadata"]
    if not isinstance(metadata, dict):
        raise ProtocolFailure("INFO ADC metadata is not an object")
    grade_adc_metadata(
        evidence,
        metadata,
        resolution_bits=resolution_bits,
        label="identity.adc",
    )
    _raise_if_new_failures(evidence, before, "identity/resource")
    return resolution_bits


def pack_gpio2_word(word: int) -> int:
    """Apply the production GPIO2_PSR-to-D6-through-D13 permutation."""

    return sum(
        ((word >> gpio2_bit) & 1) << packed_bit
        for packed_bit, gpio2_bit in enumerate(GPIO2_BITS_BY_PACKED_BIT)
    )


def grade_capture_diagnostic(
    evidence: Evidence,
    snapshot: dict[str, int],
    info: dict[str, object],
) -> tuple[bool, str]:
    """Validate digital mapping/safety and return the external claim scope."""

    before = len(evidence.failures)
    mode = snapshot["mode"]
    flags = snapshot["diagnostic_flags"]
    evidence.equal("digital.mode", info["gpio_capture_diagnostic_mode"], mode)
    evidence.check(
        "digital.known_mode", GPIO_DIAGNOSTIC_MODES, mode, mode in GPIO_DIAGNOSTIC_MODES
    )
    evidence.equal("digital.hardware_error_flags", 0, snapshot["hardware_error_flags"])
    evidence.equal(
        "digital.reserved_error_flags",
        0,
        snapshot["hardware_error_flags"] & ~KNOWN_GPIO_CAPTURE_ERROR_MASK,
    )
    evidence.equal(
        "digital.reserved_diagnostic_flags", 0, flags & ~KNOWN_GPIO_DIAGNOSTIC_FLAGS
    )
    evidence.equal(
        "digital.declaration_flags_match_info",
        _info_int(info, "gpio_capture_diagnostic_flags") & 0x0F,
        flags & 0x0F,
    )
    required = (
        GPIO_DIAGNOSTIC_AVAILABLE
        | GPIO_DIAGNOSTIC_DECLARATION_VALID
        | GPIO_DIAGNOSTIC_DMA_CAPTURE_EXERCISED
        | GPIO_DIAGNOSTIC_PACKED_OBSERVATION_EXERCISED
        | GPIO_DIAGNOSTIC_FINAL_INPUT_SAFE
    )
    evidence.equal("digital.required_evidence_flags", required, flags & required)
    evidence.equal(
        "digital.dwt_counter_hz", ADC_TRIGGER_DWT_CLOCK_HZ, snapshot["dwt_counter_hz"]
    )
    evidence.check(
        "digital.elapsed_cycles",
        "nonzero and bounded",
        snapshot["dwt_elapsed_cycles"],
        0 < snapshot["dwt_elapsed_cycles"] <= 12_000_000,
    )
    evidence.check(
        "digital.capture_accounting",
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
        "digital.analysis_count",
        "0 < analyzed == limit <= retained",
        {
            "limit": snapshot["analysis_sample_limit"],
            "analyzed": snapshot["samples_analyzed"],
            "retained": snapshot["complete_samples_retained"],
        },
        0
        < snapshot["analysis_sample_limit"]
        == snapshot["samples_analyzed"]
        <= snapshot["complete_samples_retained"],
    )
    evidence.equal("digital.mapping_failures", 0, snapshot["mapping_failures"])
    evidence.equal("digital.unstable_samples", 0, snapshot["unstable_samples"])
    evidence.equal(
        "digital.packed_and_from_raw",
        pack_gpio2_word(snapshot["raw_word_and"]),
        snapshot["packed_value_and"],
    )
    evidence.equal(
        "digital.packed_or_from_raw",
        pack_gpio2_word(snapshot["raw_word_or"]),
        snapshot["packed_value_or"],
    )
    for name in ("gpr27_configured", "gpr27_after"):
        evidence.equal(f"digital.{name}_input", 0, snapshot[name] & GPIO2_CAPTURE_MASK)
    for name in ("gpio2_gdir_configured", "gpio2_gdir_after"):
        evidence.equal(f"digital.{name}_input", 0, snapshot[name] & GPIO2_CAPTURE_MASK)
    evidence.equal("digital.pit_load", 5, snapshot["pit_ldval_configured"])
    evidence.equal("digital.pit_enabled", 1, snapshot["pit_tctrl_configured"])
    evidence.equal(
        "digital.dmamux_route",
        DMAMUX_ENABLE | GPIO_DMAMUX_SOURCE,
        snapshot["dmamux_chcfg_configured"],
    )
    evidence.equal(
        "digital.edma_request",
        GPIO_EDMA_CHANNEL_MASK,
        snapshot["dma_erq_configured"] & GPIO_EDMA_CHANNEL_MASK,
    )
    evidence.equal(
        "digital.edma_error",
        0,
        snapshot["dma_err_final"] & GPIO_EDMA_CHANNEL_MASK,
    )
    evidence.equal(
        "digital.tcd_biter",
        GPIO_RAW_SAMPLES_PER_BUFFER,
        snapshot["tcd_biter_configured"],
    )
    evidence.check(
        "digital.tcd_citer",
        f"0..{snapshot['tcd_biter_configured']}",
        snapshot["tcd_citer_configured"],
        0 <= snapshot["tcd_citer_configured"] <= snapshot["tcd_biter_configured"],
    )
    evidence.equal(
        "digital.edma_priority",
        GPIO_EDMA_PRIORITY,
        snapshot["edma_priority_configured"],
    )

    if mode == GPIO_DIAGNOSTIC_NON_DRIVING:
        forbidden = (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
            | GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
        )
        evidence.equal("digital.non_driving_claims", 0, flags & forbidden)
    elif mode == GPIO_DIAGNOSTIC_SELF_DRIVEN_SWEEP:
        required_sweep = (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
        )
        evidence.equal(
            "digital.self_driven_flags", required_sweep, flags & required_sweep
        )
        evidence.check(
            "digital.self_driven_fixture_identity",
            "nonzero",
            snapshot["fixture_identity"],
            snapshot["fixture_identity"] != 0,
        )
    elif mode == GPIO_DIAGNOSTIC_FIXTURE_STIMULUS:
        external_flags = (
            GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
            | GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
        )
        evidence.equal(
            "digital.external_fixture_flags", external_flags, flags & external_flags
        )
        evidence.check(
            "digital.external_fixture_identity",
            "nonzero",
            snapshot["fixture_identity"],
            snapshot["fixture_identity"] != 0,
        )
        evidence.check(
            "digital.external_stimulus_identity",
            "nonzero",
            snapshot["stimulus_identity"],
            snapshot["stimulus_identity"] != 0,
        )
        evidence.check(
            "digital.external_transitions",
            "> 0",
            snapshot["observed_transitions"],
            snapshot["observed_transitions"] > 0,
        )
    if flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED:
        evidence.check(
            "digital.output_drive_authorized",
            "OUTPUT_DRIVE_PERMITTED",
            flags,
            bool(flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED),
        )
    _raise_if_new_failures(evidence, before, "digital capture/mapping diagnostic")
    external_exercised = bool(
        flags & GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
        and flags & GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
    )
    mode_name = GPIO_DIAGNOSTIC_MODES[mode]
    emit_event(
        "digital_diagnostic_complete",
        external_stimulus_exercised=external_exercised,
        fixture_identity=snapshot["fixture_identity"],
        mode=mode_name,
        output_drive_exercised=bool(flags & GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED),
        stimulus_identity=snapshot["stimulus_identity"],
    )
    return external_exercised, mode_name


@dataclass
class StreamTotals:
    expected_sequence: int = 0
    expected_ticks: int = 0
    frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0


def count_adjacent_byte_transitions(payload: bytes) -> int:
    """Count adjacent unequal bytes with fixed-width native big-int work."""

    if len(payload) != GPIO_SAMPLES_PER_FRAME:
        raise ValueError("GPIO transition payload has the wrong length")
    packed = int.from_bytes(payload, "little")
    differences = (packed ^ (packed >> 8)) & GPIO_ADJACENT_SAMPLE_MASK
    zero_difference_high_bits = (
        ~(
            ((differences & GPIO_BYTE_LOW_SEVEN_BITS) + GPIO_BYTE_LOW_SEVEN_BITS)
            | differences
            | GPIO_BYTE_LOW_SEVEN_BITS
        )
    ) & GPIO_BYTE_HIGH_BITS
    return GPIO_ADJACENT_SAMPLE_COUNT - zero_difference_high_bits.bit_count()


class CombinedValidator:
    """Validate both physical streams without retaining bulk frame payloads."""

    def __init__(
        self,
        run_id: int,
        checksum_algorithm: int,
        resolution_bits: int,
        fixture: FixtureStimulus | None,
        track_gpio_transitions: bool = False,
    ) -> None:
        if not 1 <= run_id <= 0xFFFFFFFF:
            raise ValueError("run ID must be a nonzero uint32")
        if checksum_algorithm not in SUPPORTED_CHECKSUMS:
            raise ProtocolFailure(
                f"host lacks checksum support for algorithm {checksum_algorithm}"
            )
        self.run_id = run_id
        self.checksum_algorithm = checksum_algorithm
        self.code_min = ADC_CODE_MIN
        self.code_max = (1 << resolution_bits) - 1
        self.fixture = fixture
        self.track_gpio_transitions = track_gpio_transitions
        if fixture is not None:
            for index, channel in enumerate(fixture.channels):
                if not (
                    self.code_min
                    <= channel.minimum_code
                    <= channel.maximum_code
                    <= self.code_max
                ):
                    raise ProtocolFailure(
                        f"fixture ADC{index} code envelope is outside the "
                        "advertised ADC range"
                    )
        self.adc = StreamTotals()
        self.gpio = StreamTotals()
        self.channel_minimums = [0xFFFF, 0xFFFF]
        self.channel_maximums = [0, 0]
        self.channel_sums = [0, 0]
        self.channel_counts = [0, 0]
        self.fixture_violations = [0, 0]
        self.gpio_payload_and = 0xFF
        self.gpio_payload_or = 0
        self.gpio_transitions = 0
        self.gpio_low_seen = 0
        self.gpio_high_seen = 0
        self.maximum_frame_skew = 0
        self.maximum_receive_gap_seconds = 0.0
        self._last_gpio_value: int | None = None
        self._last_received_at: float | None = None

    def accept(self, frame: Frame) -> None:
        received_at = time.monotonic()
        if self._last_received_at is not None:
            self.maximum_receive_gap_seconds = max(
                self.maximum_receive_gap_seconds,
                received_at - self._last_received_at,
            )
        self._last_received_at = received_at
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"data run ID is {frame.run_id}; expected {self.run_id}"
            )
        if frame.checksum_algorithm != self.checksum_algorithm:
            raise ProtocolFailure("data checksum selection changed within run")
        if frame.flags & FLAG_SYNTHETIC:
            raise ProtocolFailure("physical combined frame carries SYNTHETIC")
        if frame.flags & (FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE):
            raise ProtocolFailure(
                f"physical frame {frame.sequence} reports gap/overrun"
            )
        if frame.kind == ADC_DATA:
            self._accept_adc(frame)
        elif frame.kind == GPIO_DATA:
            self._accept_gpio(frame)
        else:
            raise ProtocolFailure(f"unexpected data kind 0x{frame.kind:02x}")
        skew = abs(self.adc.frames - self.gpio.frames)
        self.maximum_frame_skew = max(self.maximum_frame_skew, skew)
        if skew > 1:
            raise ProtocolFailure(f"combined fair-scheduler frame skew is {skew}")

    @staticmethod
    def _validate_continuity(frame: Frame, totals: StreamTotals, label: str) -> None:
        expected_flags = FLAG_EPOCH_START if totals.frames == 0 else 0
        if frame.flags != expected_flags:
            raise ProtocolFailure(
                f"{label} flags 0x{frame.flags:04x}; expected 0x{expected_flags:04x}"
            )
        if frame.sequence != totals.expected_sequence:
            raise ProtocolFailure(
                f"{label} sequence {frame.sequence}; expected {totals.expected_sequence}"
            )
        if frame.first_sample_ticks != totals.expected_ticks:
            raise ProtocolFailure(
                f"{label} timestamp {frame.first_sample_ticks}; "
                f"expected {totals.expected_ticks}"
            )

    @staticmethod
    def _advance(totals: StreamTotals, frame: Frame) -> None:
        totals.frames += 1
        totals.items += frame.item_count
        totals.payload_bytes += len(frame.payload)
        totals.framed_bytes += DATA_FRAME_BYTES
        totals.expected_sequence = (totals.expected_sequence + 1) & 0xFFFFFFFF
        totals.expected_ticks = (
            totals.expected_ticks + FRAME_COVERAGE_TICKS
        ) & 0xFFFFFFFFFFFFFFFF

    def _accept_adc(self, frame: Frame) -> None:
        self._validate_continuity(frame, self.adc, "ADC")
        if frame.item_count != ADC_PAIRS_PER_FRAME:
            raise ProtocolFailure(
                f"ADC item count {frame.item_count}; expected {ADC_PAIRS_PER_FRAME}"
            )
        if len(frame.payload) != ADC_PAIRS_PER_FRAME * ADC_BYTES_PER_PAIR:
            raise ProtocolFailure("ADC payload does not contain four-byte pairs")
        high_bytes = frame.payload[1::2]
        if max(high_bytes) > self.code_max >> 8:
            raise ProtocolFailure(
                f"ADC payload contains a code outside {self.code_min}..{self.code_max}"
            )
        # The byte-lane check above covers every code without allocating
        # thousands of Python integers per frame. One complete
        # frame supplies representative extrema when no external fixture is
        # declared; a fixture retains exhaustive per-code envelope and mean
        # grading.
        if self.adc.frames == 0 or self.fixture is not None:
            samples = ADC_PAYLOAD_STRUCT.unpack(frame.payload)
            channels = (samples[0::2], samples[1::2])
            for index, values in enumerate(channels):
                minimum = min(values)
                maximum = max(values)
                self.channel_minimums[index] = min(
                    self.channel_minimums[index], minimum
                )
                self.channel_maximums[index] = max(
                    self.channel_maximums[index], maximum
                )
                if self.fixture is not None:
                    fixture = self.fixture.channels[index]
                    self.channel_sums[index] += sum(values)
                    self.fixture_violations[index] += sum(
                        value < fixture.minimum_code or value > fixture.maximum_code
                        for value in values
                    )
        self.channel_counts[0] += frame.item_count
        self.channel_counts[1] += frame.item_count
        self._advance(self.adc, frame)

    def _accept_gpio(self, frame: Frame) -> None:
        self._validate_continuity(frame, self.gpio, "GPIO")
        if frame.item_count != GPIO_SAMPLES_PER_FRAME:
            raise ProtocolFailure(
                f"GPIO item count {frame.item_count}; expected {GPIO_SAMPLES_PER_FRAME}"
            )
        if len(frame.payload) != GPIO_SAMPLES_PER_FRAME:
            raise ProtocolFailure("GPIO payload does not contain one byte per sample")
        # ``bytes`` makes every sample intrinsically safe in 0..255, and the
        # frame checksum covers all of them. Derive representative extrema
        # once unless an external-transition claim explicitly needs exhaustive
        # stream-wide level and transition evidence.
        if self.gpio.frames == 0 or self.track_gpio_transitions:
            for value in set(frame.payload):
                self.gpio_payload_and &= value
                self.gpio_payload_or |= value
                self.gpio_low_seen |= (~value) & 0xFF
                self.gpio_high_seen |= value
        if self.track_gpio_transitions:
            if (
                self._last_gpio_value is not None
                and frame.payload[0] != self._last_gpio_value
            ):
                self.gpio_transitions += 1
            self.gpio_transitions += count_adjacent_byte_transitions(frame.payload)
            self._last_gpio_value = frame.payload[-1]
        self._advance(self.gpio, frame)

    def means(self) -> tuple[float, float]:
        if not all(self.channel_counts):
            raise ProtocolFailure("ADC capture contains no complete pairs")
        return (
            self.channel_sums[0] / self.channel_counts[0],
            self.channel_sums[1] / self.channel_counts[1],
        )

    def grade_analog_fixture(self, evidence: Evidence) -> bool:
        if self.fixture is None:
            return False
        before = len(evidence.failures)
        evidence.equal(
            "stimulus.analog_code_violations", (0, 0), tuple(self.fixture_violations)
        )
        means = self.means()
        if self.fixture.grades_analog_quality:
            for index, (mean, channel) in enumerate(
                zip(means, self.fixture.channels, strict=True)
            ):
                lower = channel.mean_minimum_code
                upper = channel.mean_maximum_code
                if lower is None or upper is None:
                    raise ProtocolFailure("fixture analog bounds are inconsistent")
                evidence.check(
                    f"stimulus.adc{index}_mean_code",
                    f"{lower}..{upper}",
                    mean,
                    lower <= mean <= upper,
                )
        _raise_if_new_failures(evidence, before, "declared analog stimulus")
        return self.fixture.grades_analog_quality


_ZERO_ERROR_FIELDS = (
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
)

_BOUNDED_STOP_TAIL_FIELDS = frozenset(
    {
        "adc_items_dropped",
        "gpio_items_dropped",
        "gpio_raw_samples_lost",
        "adc_raw_pairs_lost",
        "adc_stop_pairs_discarded",
        "adc_incomplete_conversions",
        "adc_incomplete_buffers",
        "adc_completion_mismatches",
    }
)


def _status_errors(status: StatusSnapshot) -> dict[str, int]:
    return {name: status.values[name] for name in _ZERO_ERROR_FIELDS}


def validate_status_accounting(
    status: StatusSnapshot, *, allow_bounded_stop_tail: bool = False
) -> None:
    """Reject inconsistent stage, byte, queue, error, or STOP-tail telemetry."""

    nonzero_errors = {
        name: value
        for name, value in _status_errors(status).items()
        if value
        and (not allow_bounded_stop_tail or name not in _BOUNDED_STOP_TAIL_FIELDS)
    }
    if nonzero_errors:
        raise ProtocolFailure(
            "STATUS reports loss, firmware errors, or host-visible drops: "
            + json.dumps(nonzero_errors, sort_keys=True, separators=(",", ":"))
        )
    if allow_bounded_stop_tail:
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
            raise ProtocolFailure(
                "STATUS bounded STOP-tail accounting is inconsistent: "
                + json.dumps(
                    {
                        name: status.values[name]
                        for name in sorted(_BOUNDED_STOP_TAIL_FIELDS)
                    },
                    separators=(",", ":"),
                )
            )
    if status.adc0_dma_results != status.adc0_dma_major_loops * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS ADC0 results disagree with major loops")
    if status.adc1_dma_results != status.adc1_dma_major_loops * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS ADC1 results disagree with major loops")
    if abs(status.adc0_dma_major_loops - status.adc1_dma_major_loops) > 1:
        raise ProtocolFailure("STATUS ADC channel major-loop lead exceeds one")
    if status.adc_paired_major_loops != min(
        status.adc0_dma_major_loops, status.adc1_dma_major_loops
    ):
        raise ProtocolFailure("STATUS paired ADC loops disagree with channel barrier")
    adc_stages = (
        status.adc_buffers_completed,
        status.adc_buffers_acquired,
        status.adc_buffers_released,
    )
    if not adc_stages[0] >= adc_stages[1] >= adc_stages[2]:
        raise ProtocolFailure(
            f"STATUS ADC buffer stages are inconsistent: {adc_stages}"
        )
    if status.adc_buffers_completed > status.adc_paired_major_loops:
        raise ProtocolFailure("STATUS ADC completed buffers exceed paired loops")
    if status.adc_pairs_delivered != status.adc_buffers_acquired * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS ADC delivered pairs disagree with buffer leases")
    if not (
        status.adc_pairs_captured
        >= status.adc_pairs_delivered
        >= status.adc_pairs_framed
        >= status.adc_pairs_transmitted
    ):
        raise ProtocolFailure("STATUS ADC pair stages are not monotonic")

    gpio_stages = (
        status.gpio_samples_captured,
        status.gpio_samples_packed,
        status.gpio_samples_framed,
        status.gpio_samples_transmitted,
    )
    if not all(
        gpio_stages[index] >= gpio_stages[index + 1]
        for index in range(len(gpio_stages) - 1)
    ):
        raise ProtocolFailure(f"STATUS GPIO stages are not monotonic: {gpio_stages}")
    if status.gpio_samples_framed % GPIO_SAMPLES_PER_FRAME:
        raise ProtocolFailure("STATUS framed GPIO samples are not frame aligned")
    if status.gpio_samples_transmitted % GPIO_SAMPLES_PER_FRAME:
        raise ProtocolFailure("STATUS transmitted GPIO samples are not frame aligned")

    for prefix, items_per_frame, item_bytes in (
        ("adc", ADC_PAIRS_PER_FRAME, ADC_BYTES_PER_PAIR),
        ("gpio", GPIO_SAMPLES_PER_FRAME, 1),
    ):
        generated = status.values[f"{prefix}_frames_generated"]
        framed = status.values[f"{prefix}_frames_framed_pipeline"]
        emitted = status.values[f"{prefix}_frames_emitted"]
        transmitted = status.values[f"{prefix}_frames_transmitted"]
        if not generated >= framed >= emitted >= transmitted:
            raise ProtocolFailure(f"STATUS {prefix} frame stages are not monotonic")
        frame_item_fields = {
            f"{prefix}_items_generated": generated * items_per_frame,
            f"{prefix}_items_framed_pipeline": framed * items_per_frame,
            f"{prefix}_items_emitted": emitted * items_per_frame,
            f"{prefix}_items_transmitted_pipeline": transmitted * items_per_frame,
        }
        for name, expected in frame_item_fields.items():
            if status.values[name] != expected:
                raise ProtocolFailure(f"STATUS {name} does not match its frame stage")
        payload_fields = {
            f"{prefix}_payload_bytes_produced": generated
            * items_per_frame
            * item_bytes,
            f"{prefix}_payload_bytes_framed": framed * items_per_frame * item_bytes,
            f"{prefix}_payload_bytes_emitted": emitted * items_per_frame * item_bytes,
            f"{prefix}_payload_bytes_transmitted": transmitted
            * items_per_frame
            * item_bytes,
            f"{prefix}_framed_bytes_framed": framed * DATA_FRAME_BYTES,
            f"{prefix}_framed_bytes_emitted": emitted * DATA_FRAME_BYTES,
            f"{prefix}_framed_bytes_transmitted": transmitted * DATA_FRAME_BYTES,
        }
        for name, expected in payload_fields.items():
            if status.values[name] != expected:
                raise ProtocolFailure(f"STATUS {name} does not match its frame stage")

    if status.adc_pairs_framed != status.adc_items_framed_pipeline:
        raise ProtocolFailure("legacy/pipeline ADC framed counts disagree")
    if status.adc_pairs_transmitted != status.adc_items_transmitted_pipeline:
        raise ProtocolFailure("legacy/pipeline ADC transmitted counts disagree")
    if status.gpio_samples_framed != status.gpio_items_framed_pipeline:
        raise ProtocolFailure("legacy/pipeline GPIO framed counts disagree")
    if status.gpio_samples_transmitted != status.gpio_items_transmitted_pipeline:
        raise ProtocolFailure("legacy/pipeline GPIO transmitted counts disagree")
    if status.data_payload_bytes_transmitted != (
        status.adc_payload_bytes_transmitted + status.gpio_payload_bytes_transmitted
    ):
        raise ProtocolFailure("shared transmitted payload bytes do not reconcile")
    if status.data_framed_bytes_transmitted != (
        status.adc_framed_bytes_transmitted + status.gpio_framed_bytes_transmitted
    ):
        raise ProtocolFailure("shared transmitted framed bytes do not reconcile")
    if status.packet_accounted_frame_skew > 1:
        raise ProtocolFailure("STATUS fair-scheduler accounted skew exceeds one")

    depth_limits = {
        "gpio_raw_ready_depth": GPIO_RAW_RING_DEPTH,
        "gpio_raw_ready_high_water": GPIO_RAW_RING_DEPTH,
        "gpio_packed_ready_depth": GPIO_PACKED_RING_DEPTH,
        "gpio_packed_ready_high_water": GPIO_PACKED_RING_DEPTH,
        "adc_raw_ready_depth": ADC_DMA_RING_DEPTH,
        "adc_raw_ready_high_water": ADC_DMA_RING_DEPTH,
        "packet_ready_depth": PACKET_READY_QUEUE_CAPACITY,
        "packet_transmit_depth": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "packet_owned_high_water": PACKET_BUFFER_COUNT,
        "adc_packet_ready_depth": PACKET_READY_QUEUE_CAPACITY,
        "gpio_packet_ready_depth": PACKET_READY_QUEUE_CAPACITY,
        "adc_packet_transmit_depth": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "gpio_packet_transmit_depth": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "adc_packet_ready_high_water": PACKET_READY_QUEUE_CAPACITY,
        "gpio_packet_ready_high_water": PACKET_READY_QUEUE_CAPACITY,
        "adc_packet_transmit_high_water": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "gpio_packet_transmit_high_water": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "packet_ready_high_water": PACKET_READY_QUEUE_CAPACITY,
        "packet_transmit_high_water": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "usb_command_queue_depth": COMMAND_QUEUE_CAPACITY,
        "usb_response_queue_depth": RESPONSE_QUEUE_CAPACITY,
        "usb_command_queue_high_water": COMMAND_QUEUE_CAPACITY,
        "usb_response_queue_high_water": RESPONSE_QUEUE_CAPACITY,
    }
    for name, limit in depth_limits.items():
        if not 0 <= status.values[name] <= limit:
            raise ProtocolFailure(
                f"STATUS {name}={status.values[name]} exceeds capacity {limit}"
            )
    if status.gpio_raw_ready_depth > status.gpio_raw_ready_high_water:
        raise ProtocolFailure("GPIO raw depth exceeds high water")
    if status.gpio_packed_ready_depth > status.gpio_packed_ready_high_water:
        raise ProtocolFailure("GPIO packed depth exceeds high water")
    if status.adc_raw_ready_depth > status.adc_raw_ready_high_water:
        raise ProtocolFailure("ADC raw depth exceeds high water")
    if status.packet_ready_depth != (
        status.adc_packet_ready_depth + status.gpio_packet_ready_depth
    ):
        raise ProtocolFailure("aggregate/per-source packet-ready depths disagree")
    if status.packet_transmit_depth != (
        status.adc_packet_transmit_depth + status.gpio_packet_transmit_depth
    ):
        raise ProtocolFailure("aggregate/per-source transmit depths disagree")
    if status.packet_ready_depth + status.packet_transmit_depth > PACKET_BUFFER_COUNT:
        raise ProtocolFailure("packet depths exceed the fixed pool")
    if status.gpio_processing_cpu_basis_points > 10_000:
        raise ProtocolFailure("GPIO processing CPU measurement exceeds 100%")
    if status.usb_active_frame_bytes_sent >= DATA_FRAME_BYTES:
        raise ProtocolFailure("USB active-frame offset exceeds one frame")


def validate_status_identity(
    status: StatusSnapshot,
    frame: Frame,
    *,
    expected_state: int,
    expected_stream_mask: int,
    expected_checksum: int,
    expected_generation: int,
    run_id: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> None:
    expected = (
        expected_state,
        expected_stream_mask,
        SOURCE_HARDWARE,
        expected_checksum,
        DATA_FRAME_BYTES,
    )
    actual = (
        status.device_state,
        status.stream_mask,
        status.source,
        status.checksum,
        status.data_frame_bytes,
    )
    if actual != expected:
        raise ProtocolFailure(f"STATUS configuration is {actual}; expected {expected}")
    if frame.run_id != run_id:
        raise ProtocolFailure(f"STATUS run ID is {frame.run_id}; expected {run_id}")
    if status.stats_generation != expected_generation:
        raise ProtocolFailure(
            f"STATUS generation is {status.stats_generation}; "
            f"expected {expected_generation}"
        )
    if (
        status.adc_resolution_bits != resolution_bits
        or status.adc_container_bytes != ADC_CONTAINER_BYTES
        or status.adc_metadata != expected_metadata
    ):
        raise ProtocolFailure("STATUS ADC metadata changed from graded INFO")


def validate_running_status(
    status: StatusSnapshot,
    frame: Frame,
    validator: CombinedValidator,
    *,
    expected_generation: int,
    expected_commands: int,
    host_adc_floor: int,
    host_gpio_floor: int,
    previous: StatusSnapshot | None,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> None:
    validate_status_identity(
        status,
        frame,
        expected_state=STATE_RUNNING,
        expected_stream_mask=STREAM_BOTH,
        expected_checksum=validator.checksum_algorithm,
        expected_generation=expected_generation,
        run_id=validator.run_id,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    if status.adc_frames_emitted < host_adc_floor:
        raise ProtocolFailure("firmware ADC frame count trails the host floor")
    if status.gpio_frames_emitted < host_gpio_floor:
        raise ProtocolFailure("firmware GPIO frame count trails the host floor")
    if status.commands_accepted != expected_commands:
        raise ProtocolFailure(
            f"firmware accepted-command count is {status.commands_accepted}; "
            f"expected {expected_commands}"
        )
    validate_status_accounting(status)
    if previous is not None:
        regressions = status.regressions_from(previous)
        if regressions:
            raise ProtocolFailure(
                "running STATUS counters moved backwards: "
                + json.dumps(regressions, sort_keys=True, separators=(",", ":"))
            )


class MemoryTracker:
    """Bounded process-memory telemetry without optional dependencies."""

    def __init__(self) -> None:
        self.baseline_current_bytes = current_rss_bytes()
        self.baseline_peak_bytes = peak_rss_bytes()
        self.maximum_current_bytes = self.baseline_current_bytes
        self.peak_bytes = self.baseline_peak_bytes
        self.final_current_bytes = self.baseline_current_bytes

    def sample(self) -> None:
        current = current_rss_bytes()
        peak = peak_rss_bytes()
        self.final_current_bytes = current
        self.maximum_current_bytes = max(self.maximum_current_bytes, current)
        self.peak_bytes = max(self.peak_bytes, peak, current)

    @property
    def peak_growth_bytes(self) -> int:
        return max(
            0,
            self.maximum_current_bytes - self.baseline_current_bytes,
            self.peak_bytes - self.baseline_peak_bytes,
        )


def peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def current_rss_bytes() -> int:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return peak_rss_bytes()


def percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return math.inf
    ordered = sorted(samples)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


@dataclass(frozen=True)
class AcceptanceResult:
    evidence: Evidence
    analog_stimulus_exercised: bool
    analog_quality_graded: bool
    analog_aperture_graded: bool
    digital_stimulus_exercised: bool
    digital_mode: str


def reconcile_final_status(
    evidence: Evidence,
    status: StatusSnapshot,
    frame: Frame,
    validator: CombinedValidator,
    *,
    expected_generation: int,
    expected_commands: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> None:
    """Classify and reconcile every final firmware STATUS field."""

    validate_status_identity(
        status,
        frame,
        expected_state=STATE_IDLE,
        expected_stream_mask=STREAM_NONE,
        expected_checksum=DEFAULT_DATA_CHECKSUM,
        expected_generation=expected_generation,
        run_id=validator.run_id,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    validate_status_accounting(status, allow_bounded_stop_tail=True)
    adc_frames = validator.adc.frames
    gpio_frames = validator.gpio.frames
    adc_items = validator.adc.items
    gpio_items = validator.gpio.items
    total_frames = adc_frames + gpio_frames
    total_payload = validator.adc.payload_bytes + validator.gpio.payload_bytes
    total_framed = validator.adc.framed_bytes + validator.gpio.framed_bytes

    exact: dict[str, int] = {
        "device_state": STATE_IDLE,
        "stream_mask": STREAM_NONE,
        "source": SOURCE_HARDWARE,
        "checksum": DEFAULT_DATA_CHECKSUM,
        "data_frame_bytes": DATA_FRAME_BYTES,
        "adc_frames_emitted": adc_frames,
        "gpio_frames_emitted": gpio_frames,
        "stats_generation": expected_generation,
        "gpio_samples_captured": gpio_items + status.gpio_raw_samples_lost,
        "gpio_samples_packed": gpio_items,
        "gpio_samples_framed": gpio_items,
        "gpio_samples_transmitted": gpio_items,
        "gpio_dma_major_loops": gpio_frames,
        "gpio_raw_ready_depth": 0,
        "gpio_packed_ready_depth": 0,
        "packet_ready_depth": 0,
        "packet_transmit_depth": 0,
        "adc0_dma_major_loops": adc_frames,
        "adc1_dma_major_loops": adc_frames,
        "adc0_dma_results": adc_items,
        "adc1_dma_results": adc_items,
        "adc_paired_major_loops": adc_frames,
        "adc_buffers_completed": adc_frames,
        "adc_buffers_acquired": adc_frames,
        "adc_buffers_released": adc_frames,
        "adc_pairs_captured": adc_items + status.adc_stop_pairs_discarded,
        "adc_pairs_delivered": adc_items,
        "adc_pairs_framed": adc_items,
        "adc_pairs_transmitted": adc_items,
        "adc_raw_ready_depth": 0,
        "adc_frames_generated": adc_frames,
        "adc_items_generated": adc_items,
        "adc_frames_framed_pipeline": adc_frames,
        "adc_items_framed_pipeline": adc_items,
        "adc_items_emitted": adc_items,
        "adc_frames_transmitted": adc_frames,
        "adc_items_transmitted_pipeline": adc_items,
        "gpio_frames_generated": gpio_frames,
        "gpio_items_generated": gpio_items,
        "gpio_frames_framed_pipeline": gpio_frames,
        "gpio_items_framed_pipeline": gpio_items,
        "gpio_items_emitted": gpio_items,
        "gpio_frames_transmitted": gpio_frames,
        "gpio_items_transmitted_pipeline": gpio_items,
        "adc_payload_bytes_produced": validator.adc.payload_bytes,
        "adc_payload_bytes_framed": validator.adc.payload_bytes,
        "adc_payload_bytes_emitted": validator.adc.payload_bytes,
        "adc_payload_bytes_transmitted": validator.adc.payload_bytes,
        "adc_framed_bytes_framed": validator.adc.framed_bytes,
        "adc_framed_bytes_emitted": validator.adc.framed_bytes,
        "adc_framed_bytes_transmitted": validator.adc.framed_bytes,
        "gpio_payload_bytes_produced": validator.gpio.payload_bytes,
        "gpio_payload_bytes_framed": validator.gpio.payload_bytes,
        "gpio_payload_bytes_emitted": validator.gpio.payload_bytes,
        "gpio_payload_bytes_transmitted": validator.gpio.payload_bytes,
        "gpio_framed_bytes_framed": validator.gpio.framed_bytes,
        "gpio_framed_bytes_emitted": validator.gpio.framed_bytes,
        "gpio_framed_bytes_transmitted": validator.gpio.framed_bytes,
        "adc_packet_ready_depth": 0,
        "gpio_packet_ready_depth": 0,
        "adc_packet_transmit_depth": 0,
        "gpio_packet_transmit_depth": 0,
        "packet_frames_promoted": total_frames,
        "packet_accounted_frame_skew": abs(adc_frames - gpio_frames),
        "data_payload_bytes_transmitted": total_payload,
        "data_framed_bytes_transmitted": total_framed,
        "commands_accepted": expected_commands,
        "usb_command_queue_depth": 0,
        "usb_response_queue_depth": 0,
        "usb_lower_priority_queue_depth": 0,
        "usb_active_frame_bytes_sent": 0,
    }
    exact.update(
        {
            name: 0
            for name in _ZERO_ERROR_FIELDS
            if name not in _BOUNDED_STOP_TAIL_FIELDS
        }
    )
    exact.update(
        {
            "adc_items_dropped": status.adc_stop_pairs_discarded,
            "adc_raw_pairs_lost": status.adc_stop_pairs_discarded,
            "adc_stop_pairs_discarded": status.adc_stop_pairs_discarded,
            "gpio_items_dropped": status.gpio_raw_samples_lost,
            "gpio_raw_samples_lost": status.gpio_raw_samples_lost,
        }
    )
    bounded: dict[str, tuple[int, int]] = {
        "adc_incomplete_conversions": (0, status.adc_stop_pairs_discarded),
        "adc_incomplete_buffers": (0, 2),
        "adc_completion_mismatches": (0, status.adc_incomplete_buffers),
        "gpio_raw_ready_high_water": (1, GPIO_RAW_RING_DEPTH),
        "gpio_packed_ready_high_water": (1, GPIO_PACKED_RING_DEPTH),
        "packet_owned_high_water": (1, PACKET_BUFFER_COUNT),
        "gpio_processing_cpu_basis_points": (1, 10_000),
        "adc_raw_ready_high_water": (1, ADC_DMA_RING_DEPTH),
        "adc_packet_ready_high_water": (0, PACKET_READY_QUEUE_CAPACITY),
        "gpio_packet_ready_high_water": (0, PACKET_READY_QUEUE_CAPACITY),
        "adc_packet_transmit_high_water": (0, PACKET_TRANSMIT_QUEUE_CAPACITY),
        "gpio_packet_transmit_high_water": (0, PACKET_TRANSMIT_QUEUE_CAPACITY),
        "packet_ready_high_water": (0, PACKET_READY_QUEUE_CAPACITY),
        "packet_transmit_high_water": (0, PACKET_TRANSMIT_QUEUE_CAPACITY),
        "packet_fairness_deferrals": (0, 0xFFFFFFFFFFFFFFFF),
        "partial_usb_writes": (0, 0xFFFFFFFF),
        "usb_short_capacity_deferrals": (0, 0xFFFFFFFF),
        "usb_rx_stall_events": (0, 0xFFFFFFFF),
        "usb_tx_stall_events": (0, 0xFFFFFFFF),
        "usb_command_queue_high_water": (0, COMMAND_QUEUE_CAPACITY),
        "usb_response_queue_high_water": (0, RESPONSE_QUEUE_CAPACITY),
    }
    classified = set(exact) | set(bounded)
    evidence.equal(
        "final.all_status_fields_classified",
        sorted(status.values),
        sorted(classified),
    )
    for name, expected in exact.items():
        evidence.equal(f"final.counter.{name}", expected, status.values[name])
    for name, (minimum, maximum) in bounded.items():
        value = status.values[name]
        evidence.check(
            f"final.counter.{name}",
            {"minimum": minimum, "maximum": maximum},
            value,
            minimum <= value <= maximum,
        )


def _relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / expected


def grade_capture_metrics(
    evidence: Evidence,
    validator: CombinedValidator,
    link: SerialLink,
    final_status: StatusSnapshot,
    memory: MemoryTracker,
    *,
    capture_elapsed: float,
    timed_adc_frames: int,
    timed_gpio_frames: int,
    timed_adc_items: int,
    timed_gpio_items: int,
    status_latencies: list[float],
    all_command_latencies: list[float],
    minimum_status_samples: int,
    parser_errors_at_start: int,
    discarded_data_at_start: int,
    digital_external_exercised: bool,
) -> bool:
    """Grade target rates, common epoch, host bounds, latency, and stimulus."""

    rates = {
        "adc_pair_rate_hz": (
            timed_adc_items / capture_elapsed,
            ADC_PAIR_RATE_HZ,
        ),
        "adc_payload_bytes_per_second": (
            timed_adc_items * ADC_BYTES_PER_PAIR / capture_elapsed,
            NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM,
        ),
        "adc_framed_bytes_per_second": (
            timed_adc_frames * DATA_FRAME_BYTES / capture_elapsed,
            NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM,
        ),
        "gpio_sample_rate_hz": (
            timed_gpio_items / capture_elapsed,
            GPIO_SAMPLE_RATE_HZ,
        ),
        "gpio_payload_bytes_per_second": (
            timed_gpio_items / capture_elapsed,
            NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM,
        ),
        "gpio_framed_bytes_per_second": (
            timed_gpio_frames * DATA_FRAME_BYTES / capture_elapsed,
            NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM,
        ),
    }
    for name, (actual, expected) in rates.items():
        evidence.check(
            f"rate.{name}",
            {"target": expected, "tolerance_fraction": RATE_TOLERANCE_FRACTION},
            actual,
            actual > 0 and _relative_error(actual, expected) <= RATE_TOLERANCE_FRACTION,
        )
    combined_payload_rate = (
        timed_adc_items * ADC_BYTES_PER_PAIR + timed_gpio_items
    ) / capture_elapsed
    evidence.check(
        "rate.combined_payload_bytes_per_second",
        {
            "target": 2 * NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM,
            "tolerance_fraction": RATE_TOLERANCE_FRACTION,
        },
        combined_payload_rate,
        _relative_error(
            combined_payload_rate,
            2 * NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM,
        )
        <= RATE_TOLERANCE_FRACTION,
    )
    complete_frame_skew = abs(validator.adc.frames - validator.gpio.frames)
    evidence.check(
        "epoch.complete_frame_counts",
        "difference <= 1 complete equal-coverage frame",
        {"adc": validator.adc.frames, "gpio": validator.gpio.frames},
        complete_frame_skew <= 1,
    )
    evidence.check(
        "epoch.four_gpio_events_per_adc_pair",
        f"difference <= {GPIO_SAMPLES_PER_FRAME} GPIO events at STOP",
        {
            "adc_equivalent_gpio_events": validator.adc.items * 4,
            "gpio_events": validator.gpio.items,
        },
        abs(validator.adc.items * 4 - validator.gpio.items) <= GPIO_SAMPLES_PER_FRAME,
    )
    evidence.check(
        "epoch.equal_final_timestamps",
        f"difference <= {FRAME_COVERAGE_TICKS} ticks at STOP",
        {"adc": validator.adc.expected_ticks, "gpio": validator.gpio.expected_ticks},
        abs(validator.adc.expected_ticks - validator.gpio.expected_ticks)
        <= FRAME_COVERAGE_TICKS,
    )
    evidence.check(
        "epoch.maximum_wire_frame_skew",
        "<= 1 equal-coverage frame",
        validator.maximum_frame_skew,
        validator.maximum_frame_skew <= 1,
    )
    evidence.equal(
        "layout.adc_payload_bytes",
        validator.adc.items * ADC_BYTES_PER_PAIR,
        validator.adc.payload_bytes,
    )
    evidence.equal(
        "layout.gpio_payload_bytes", validator.gpio.items, validator.gpio.payload_bytes
    )
    evidence.equal(
        "layout.adc_channel_counts",
        (validator.adc.items, validator.adc.items),
        tuple(validator.channel_counts),
    )
    for index in range(2):
        evidence.check(
            f"range.adc{index}_codes",
            f"{validator.code_min}..{validator.code_max}",
            (validator.channel_minimums[index], validator.channel_maximums[index]),
            validator.code_min
            <= validator.channel_minimums[index]
            <= validator.channel_maximums[index]
            <= validator.code_max,
        )
    evidence.check(
        "range.gpio_bytes",
        "0..255",
        (validator.gpio_payload_and, validator.gpio_payload_or),
        0 <= validator.gpio_payload_and <= validator.gpio_payload_or <= 0xFF,
    )
    if digital_external_exercised:
        evidence.check(
            "stimulus.digital_stream_transitions",
            "> 0 for declared external-transition fixture",
            validator.gpio_transitions,
            validator.gpio_transitions > 0,
        )

    status_p99 = percentile(status_latencies, 0.99)
    status_maximum = max(status_latencies, default=math.inf)
    command_maximum = max(all_command_latencies, default=math.inf)
    evidence.check(
        "latency.status_sample_count",
        f">= {minimum_status_samples}",
        len(status_latencies),
        len(status_latencies) >= minimum_status_samples,
    )
    evidence.check(
        "latency.status_p99_seconds",
        f"<= {STATUS_P99_LIMIT_SECONDS}",
        status_p99,
        bool(status_latencies) and status_p99 <= STATUS_P99_LIMIT_SECONDS,
    )
    evidence.check(
        "latency.status_maximum_seconds",
        f"<= {STATUS_MAXIMUM_LIMIT_SECONDS}",
        status_maximum,
        bool(status_latencies) and status_maximum <= STATUS_MAXIMUM_LIMIT_SECONDS,
    )
    evidence.check(
        "latency.all_commands_maximum_seconds",
        f"<= {STATUS_MAXIMUM_LIMIT_SECONDS}",
        command_maximum,
        bool(all_command_latencies) and command_maximum <= STATUS_MAXIMUM_LIMIT_SECONDS,
    )

    evidence.equal("host.parser_errors", 0, link.parser.errors - parser_errors_at_start)
    evidence.equal("host.stale_responses", 0, link.stale_responses)
    evidence.equal(
        "host.data_frames_discarded_during_run",
        discarded_data_at_start,
        link.discarded_data_frames,
    )
    evidence.equal("host.parser_buffered_bytes", 0, len(link.parser.buffer))
    parser_bound = SERIAL_READ_BYTES + MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1
    evidence.check(
        "host.parser_high_water_bytes",
        f"<= {parser_bound}",
        link.parser.high_water_bytes,
        link.parser.high_water_bytes <= parser_bound,
    )
    evidence.check(
        "host.maximum_read_bytes",
        f"<= {SERIAL_READ_BYTES}",
        link.maximum_read_bytes,
        link.maximum_read_bytes <= SERIAL_READ_BYTES,
    )
    evidence.check(
        "host.checksummed_data_frames",
        f">= {validator.adc.frames + validator.gpio.frames}",
        link.parser.frames_decoded,
        link.parser.frames_decoded >= validator.adc.frames + validator.gpio.frames,
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
    analog_quality_graded = validator.grade_analog_fixture(evidence)
    emit_event(
        "capture_complete",
        adc_frames=validator.adc.frames,
        adc_pairs=validator.adc.items,
        analog_aperture_graded=False,
        analog_quality_graded=analog_quality_graded,
        capture_elapsed_seconds=capture_elapsed,
        checksum_algorithm=CHECKSUM_NAMES[validator.checksum_algorithm],
        combined_payload_rate=combined_payload_rate,
        digital_external_stimulus_exercised=digital_external_exercised,
        firmware_partial_usb_writes=final_status.partial_usb_writes,
        firmware_usb_tx_stalls=final_status.usb_tx_stall_events,
        gpio_frames=validator.gpio.frames,
        gpio_samples=validator.gpio.items,
        maximum_receive_gap_seconds=validator.maximum_receive_gap_seconds,
        process_peak_rss_growth_bytes=memory.peak_growth_bytes,
        status_p99_seconds=status_p99,
    )
    return analog_quality_graded


def run_acceptance(
    port: SerialPort,
    *,
    capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
    warmup_seconds: float = DEFAULT_WARMUP_SECONDS,
    status_interval_seconds: float = DEFAULT_STATUS_INTERVAL_SECONDS,
    checksum_algorithm: int = DEFAULT_DATA_CHECKSUM,
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
    fixture: FixtureStimulus | None = None,
) -> AcceptanceResult:
    """Run one bounded physical combined epoch and always return to IDLE."""

    if (
        not math.isfinite(capture_seconds)
        or not 0 < capture_seconds <= MAX_CAPTURE_SECONDS
    ):
        raise ValueError(
            f"capture_seconds must be positive, finite, and <= {MAX_CAPTURE_SECONDS}"
        )
    if (
        not math.isfinite(warmup_seconds)
        or not 0 <= warmup_seconds <= MAX_WARMUP_SECONDS
    ):
        raise ValueError(
            f"warmup_seconds must be finite and in [0, {MAX_WARMUP_SECONDS}]"
        )
    if (
        not math.isfinite(status_interval_seconds)
        or status_interval_seconds < MIN_STATUS_INTERVAL_SECONDS
    ):
        raise ValueError(
            "status_interval_seconds must be finite and >= "
            f"{MIN_STATUS_INTERVAL_SECONDS}"
        )
    projected_statuses = (
        math.ceil((capture_seconds + warmup_seconds) / status_interval_seconds) + 1
    )
    if projected_statuses > MAX_STATUS_SAMPLES:
        raise ValueError(
            f"capture requests more than {MAX_STATUS_SAMPLES} STATUS samples"
        )
    if checksum_algorithm not in SUPPORTED_CHECKSUMS:
        raise ProtocolFailure(
            f"host lacks checksum support for algorithm {checksum_algorithm}"
        )

    evidence = Evidence()
    link = SerialLink(port)
    completed = False
    validator: CombinedValidator | None = None
    analog_exercised = fixture is not None
    analog_quality_graded = False
    digital_exercised = False
    digital_mode = "NOT_RUN"
    all_command_latencies: list[float] = []
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        synchronized_info = synchronize(link)
        info_frame, info_latency = link.exchange(INFO_REQUEST)
        all_command_latencies.append(info_latency)
        info = decode_info(info_frame)
        evidence.equal(
            "identity.stable_sync",
            stable_identity(synchronized_info),
            stable_identity(info),
        )
        resolution_bits = grade_info(
            evidence,
            info,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
        if not _info_int(info, "supported_checksum_mask") & (1 << checksum_algorithm):
            raise ProtocolFailure(
                f"device does not advertise checksum algorithm {checksum_algorithm}"
            )
        metadata = info["adc_metadata"]
        if not isinstance(metadata, dict):
            raise ProtocolFailure("INFO ADC metadata is not an object")

        diagnostic_frame, diagnostic_latency = link.exchange(
            GPIO_CAPTURE_DIAGNOSTIC_REQUEST,
            timeout=DIAGNOSTIC_DEADLINE_SECONDS,
        )
        all_command_latencies.append(diagnostic_latency)
        digital_exercised, digital_mode = grade_capture_diagnostic(
            evidence,
            decode_capture_diagnostic(diagnostic_frame),
            info,
        )
        analog_statement = (
            f"external analog fixture {fixture.fixture_id}/{fixture.stimulus_id} "
            "was declared and exercised"
            if fixture is not None
            else "external analog fixture stimulus was not declared or exercised"
        )
        digital_statement = (
            "external digital fixture stimulus was declared and transition-validated"
            if digital_exercised
            else "external digital fixture stimulus was not exercised"
        )
        print(
            "ANALOG_STIMULUS: " + analog_statement + "; analog aperture was not graded"
        )
        print("DIGITAL_STIMULUS: " + digital_statement)
        emit_event(
            "external_stimulus_scope",
            analog_aperture_graded=False,
            analog_external_exercised=analog_exercised,
            analog_quality_requested=(
                fixture.grades_analog_quality if fixture is not None else False
            ),
            digital_external_exercised=digital_exercised,
            digital_mode=digital_mode,
        )

        reset_frame, reset_latency = link.exchange(RESET_STATS_REQUEST)
        all_command_latencies.append(reset_latency)
        response_success(reset_frame, RESET_STATS_RESPONSE)
        reset_generation = _u32(reset_frame.payload, 4)
        if reset_generation == 0:
            raise ProtocolFailure("RESET_STATS returned generation zero")

        requested = CONFIGURATION.pack(
            STREAM_BOTH,
            SOURCE_HARDWARE,
            checksum_algorithm,
            0,
            DATA_FRAME_BYTES,
        )
        configured_frame, configure_latency = link.exchange(
            CONFIGURE_REQUEST, requested
        )
        all_command_latencies.append(configure_latency)
        applied = (
            STREAM_BOTH,
            SOURCE_HARDWARE,
            checksum_algorithm,
            DATA_FRAME_BYTES,
        )
        evidence.equal(
            "configure.applied",
            applied,
            decode_configuration(configured_frame, CONFIGURE_RESPONSE),
        )
        configured_status_frame, configured_status_latency = link.exchange(
            GET_STATUS_REQUEST
        )
        all_command_latencies.append(configured_status_latency)
        configured_status = decode_status(configured_status_frame)
        validate_status_identity(
            configured_status,
            configured_status_frame,
            expected_state=STATE_CONFIGURED,
            expected_stream_mask=STREAM_BOTH,
            expected_checksum=checksum_algorithm,
            expected_generation=reset_generation,
            run_id=configured_status_frame.run_id,
            resolution_bits=resolution_bits,
            expected_metadata=metadata,
        )
        validate_status_accounting(configured_status)
        configured_info_frame, configured_info_latency = link.exchange(INFO_REQUEST)
        all_command_latencies.append(configured_info_latency)
        configured_info = decode_info(configured_info_frame)
        evidence.equal(
            "configure.info_identity",
            stable_identity(info),
            stable_identity(configured_info),
        )
        evidence.equal(
            "configure.info_state", STATE_CONFIGURED, configured_info["device_state"]
        )
        evidence.equal(
            "configure.info_stream_mask",
            STREAM_BOTH,
            configured_info["applied_stream_mask"],
        )
        evidence.equal(
            "configure.info_source",
            SOURCE_HARDWARE,
            configured_info["applied_source"],
        )
        evidence.equal(
            "configure.info_checksum",
            checksum_algorithm,
            configured_info["data_checksum_algorithm"],
        )
        evidence.equal(
            "configure.info_adc_metadata", metadata, configured_info["adc_metadata"]
        )
        if evidence.failures:
            raise ProtocolFailure("pre-stream grading failed")

        deferred: list[Frame] = []
        deferred_limit = math.ceil(SERIAL_READ_BYTES / DATA_FRAME_BYTES) + 1

        def collect_start_data(frame: Frame) -> None:
            if len(deferred) >= deferred_limit:
                raise ProtocolFailure(
                    f"START boundary exceeded its {deferred_limit}-frame bound"
                )
            deferred.append(frame)

        accepted_before_start = link.accepted_requests
        start_frame, start_latency = link.exchange(
            START_REQUEST,
            on_data=collect_start_data,
        )
        all_command_latencies.append(start_latency)
        response_success(start_frame, START_RESPONSE)
        evidence.equal(
            "start.applied", applied, decode_configuration(start_frame, START_RESPONSE)
        )
        evidence.check(
            "start.run_id",
            "nonzero uint32",
            start_frame.run_id,
            1 <= start_frame.run_id <= 0xFFFFFFFF,
        )
        expected_generation = (configured_status.stats_generation + 1) & 0xFFFFFFFF
        expected_generation = expected_generation or 1
        validator = CombinedValidator(
            start_frame.run_id,
            checksum_algorithm,
            resolution_bits,
            fixture,
            track_gpio_transitions=digital_exercised,
        )
        for data_frame in deferred:
            validator.accept(data_frame)
        parser_errors_at_start = link.parser.errors
        discarded_data_at_start = link.discarded_data_frames
        memory = MemoryTracker()

        active_started = time.monotonic()
        warmup_deadline = active_started + warmup_seconds
        timed_started_at: float | None = None
        timed_start_adc_frames = 0
        timed_start_gpio_frames = 0
        timed_start_adc_items = 0
        timed_start_gpio_items = 0
        next_status_at = active_started
        status_latencies: list[float] = []
        previous_status: StatusSnapshot | None = None
        status_count = 0
        while True:
            now = time.monotonic()
            if timed_started_at is None and now >= warmup_deadline:
                timed_started_at = now
                timed_start_adc_frames = validator.adc.frames
                timed_start_gpio_frames = validator.gpio.frames
                timed_start_adc_items = validator.adc.items
                timed_start_gpio_items = validator.gpio.items
                emit_event(
                    "warmup_complete",
                    adc_frames=timed_start_adc_frames,
                    elapsed_seconds=now - active_started,
                    gpio_frames=timed_start_gpio_frames,
                )
            if (
                timed_started_at is not None
                and now >= timed_started_at + capture_seconds
            ):
                break
            if now >= next_status_at:
                adc_floor = validator.adc.frames
                gpio_floor = validator.gpio.frames
                status_frame, latency = link.exchange(
                    GET_STATUS_REQUEST,
                    on_data=validator.accept,
                )
                status = decode_status(status_frame)
                validate_running_status(
                    status,
                    status_frame,
                    validator,
                    expected_generation=expected_generation,
                    expected_commands=1 + status_count,
                    host_adc_floor=adc_floor,
                    host_gpio_floor=gpio_floor,
                    previous=previous_status,
                    resolution_bits=resolution_bits,
                    expected_metadata=metadata,
                )
                previous_status = status
                status_latencies.append(latency)
                all_command_latencies.append(latency)
                status_count += 1
                memory.sample()
                next_status_at += status_interval_seconds
                while next_status_at <= time.monotonic():
                    next_status_at += status_interval_seconds
                continue
            link.pump_once(validator.accept)

        if timed_started_at is None:
            raise ProtocolFailure("timed capture phase never began")
        capture_elapsed = time.monotonic() - timed_started_at
        timed_adc_frames = validator.adc.frames - timed_start_adc_frames
        timed_gpio_frames = validator.gpio.frames - timed_start_gpio_frames
        timed_adc_items = validator.adc.items - timed_start_adc_items
        timed_gpio_items = validator.gpio.items - timed_start_gpio_items

        stop_frame, stop_latency = link.exchange(
            STOP_REQUEST,
            on_data=validator.accept,
        )
        all_command_latencies.append(stop_latency)
        response_success(stop_frame, STOP_RESPONSE)
        evidence.equal("stop.state", STATE_IDLE, stop_frame.payload[4])
        evidence.equal("stop.run_id", validator.run_id, stop_frame.run_id)
        link.drain_until_quiet(validator.accept)
        final_frame, final_latency = link.exchange(
            GET_STATUS_REQUEST,
            on_data=validator.accept,
        )
        all_command_latencies.append(final_latency)
        final_status = decode_status(final_frame)
        expected_firmware_commands = status_count + 2
        reconcile_final_status(
            evidence,
            final_status,
            final_frame,
            validator,
            expected_generation=expected_generation,
            expected_commands=expected_firmware_commands,
            resolution_bits=resolution_bits,
            expected_metadata=metadata,
        )
        host_generation_requests = link.accepted_requests - accepted_before_start
        evidence.equal(
            "final.host_firmware_command_reconciliation",
            host_generation_requests - 1,
            final_status.commands_accepted,
        )
        minimum_status_samples = max(
            2,
            int((capture_seconds + warmup_seconds) / status_interval_seconds),
        )
        analog_quality_graded = grade_capture_metrics(
            evidence,
            validator,
            link,
            final_status,
            memory,
            capture_elapsed=capture_elapsed,
            timed_adc_frames=timed_adc_frames,
            timed_gpio_frames=timed_gpio_frames,
            timed_adc_items=timed_adc_items,
            timed_gpio_items=timed_gpio_items,
            status_latencies=status_latencies,
            all_command_latencies=all_command_latencies,
            minimum_status_samples=minimum_status_samples,
            parser_errors_at_start=parser_errors_at_start,
            discarded_data_at_start=discarded_data_at_start,
            digital_external_exercised=digital_exercised,
        )
        emit_event("final_firmware_counters", **final_status.values)
        completed = not evidence.failures
    except Exception as error:  # noqa: BLE001 - stdout is remote diagnosis
        message = f"{type(error).__name__}: {error}"
        diagnostics: dict[str, object] = {}
        if validator is not None:
            diagnostics = {
                "accepted_adc_frames": validator.adc.frames,
                "accepted_gpio_frames": validator.gpio.frames,
                "maximum_frame_skew": validator.maximum_frame_skew,
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
        analog_stimulus_exercised=analog_exercised,
        analog_quality_graded=analog_quality_graded,
        analog_aperture_graded=False,
        digital_stimulus_exercised=digital_exercised,
        digital_mode=digital_mode,
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
            "COMBINED_CAPTURE_SECONDS", DEFAULT_CAPTURE_SECONDS
        )
        warmup_seconds = _nonnegative_float_environment(
            "COMBINED_WARMUP_SECONDS", DEFAULT_WARMUP_SECONDS
        )
        status_interval_seconds = _positive_float_environment(
            "COMBINED_STATUS_INTERVAL_SECONDS", DEFAULT_STATUS_INTERVAL_SECONDS
        )
        checksum_algorithm = _checksum_environment(
            "COMBINED_CHECKSUM_ALGORITHM", DEFAULT_DATA_CHECKSUM
        )
        expected_hardware_serial = _optional_uint32_environment(
            "EXPECTED_HARDWARE_SERIAL"
        )
        fixture = load_fixture_stimulus(os.environ.get("ADC_FIXTURE_STIMULUS_JSON"))
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
        external_analog_fixture_declared=fixture is not None,
        port=port_name,
        protocol=PROTOCOL_VERSION,
        status_interval_seconds=status_interval_seconds,
        warmup_seconds=warmup_seconds,
    )
    try:
        port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - rig-visible open failure
        emit_event("open_failed", error=f"{type(error).__name__}: {error}")
        return 2
    try:
        result = run_acceptance(
            port,
            capture_seconds=capture_seconds,
            warmup_seconds=warmup_seconds,
            status_interval_seconds=status_interval_seconds,
            checksum_algorithm=checksum_algorithm,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
            fixture=fixture,
        )
    finally:
        port.close()
    summary = {
        "analog_aperture": (
            "GRADED" if result.analog_aperture_graded else "NOT_GRADED"
        ),
        "analog_external_stimulus": (
            "EXERCISED" if result.analog_stimulus_exercised else "NOT_EXERCISED"
        ),
        "analog_quality": ("GRADED" if result.analog_quality_graded else "NOT_GRADED"),
        "checks": result.evidence.check_count,
        "digital_external_stimulus": (
            "EXERCISED" if result.digital_stimulus_exercised else "NOT_EXERCISED"
        ),
        "digital_mode": result.digital_mode,
        "failures": result.evidence.failures,
        "result": "PASS" if not result.evidence.failures else "FAIL",
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if not result.evidence.failures else 1


if __name__ == "__main__":
    sys.exit(main())
