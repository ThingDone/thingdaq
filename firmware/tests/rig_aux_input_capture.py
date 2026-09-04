#!/usr/bin/env python3
"""Independent protocol-v2 auxiliary-input hardware validator.

The remote rig uploads this file by itself to a network-disabled Python 3.13
container. It uses only the Python standard library plus PySerial, embeds every
wire value it grades, applies finite deadlines, never drives a device pin, and
never retains bulk acquisition payloads.

Physical D16-D23 transition and pin-order evidence is graded only when
AUX_INPUT_FIXTURE_JSON contains an authorized machine-readable declaration
whose identities match the target diagnostic. Without that declaration the
auxiliary bank is explicitly classified ELECTRICALLY_UNSTIMULATED and all
external-transition checks remain NOT_RUN.

Required environment:
  SERIAL_PORT=/dev/ttyACM0

Campaign selectors:
  AUX_INPUT_CASE=CONTROL_GPIO|CONTROL_COMBINED|INPUT_GPIO|INPUT_COMBINED
  AUX_INPUT_RATE_PROFILE=ADC_1MHZ_GPIO_4MHZ|ADC_500KHZ_GPIO_2MHZ|
      ADC_250KHZ_GPIO_1MHZ|ADC_125KHZ_GPIO_500KHZ
  AUX_INPUT_CAPTURE_SECONDS=10
  AUX_INPUT_WARMUP_SECONDS=0.25
  AUX_INPUT_STATUS_INTERVAL_SECONDS=0.5
  AUX_INPUT_CHECKSUM_ALGORITHM=ADLER32|CRC32C|CRC32_ISO_HDLC
  AUX_INPUT_RUN_DIAGNOSTIC=1 (0 isolates streaming from the paired-bank diagnostic)
  EXPECTED_BUILD_ID=thingdaq-<16 lowercase hex>
  EXPECTED_HARDWARE_SERIAL=<nonzero uint32>

The optional AUX_INPUT_FIXTURE_JSON object must use schema
'thingdaq.aux-input-stimulus/v1', set 'authorized' to true, contain nonzero
numeric 'fixture_identity' and 'stimulus_identity' values, declare
'pins_by_bit' as [16,17,18,19,20,21,22,23], and may provide an auxiliary
'required_transition_mask' (default 255).
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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
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
MAX_GPIO_PROCESSING_CPU_BASIS_POINTS = 7_500

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 2
HEADER_SIZE = 44
TRAILER_SIZE = 4
MAX_CONTROL_FRAME_BYTES = 1536
MAX_FRAME_BYTES = 4096

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
STREAM_NONE = 0
STREAM_ADC = 1
STREAM_GPIO = 2
STREAM_BOTH = STREAM_ADC | STREAM_GPIO
SOURCE_HARDWARE = 0
SOURCE_SYNTHETIC = 1
STATE_IDLE = 1
STATE_CONFIGURED = 2
STATE_RUNNING = 3
AUX_DISABLED = 0
AUX_INPUT = 1

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

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
TRAILER = struct.Struct("<I")
CONFIGURATION = struct.Struct("<BBBBIII")
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
    CONFIGURE_REQUEST: 16,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
    GPIO_CAPTURE_DIAGNOSTIC_REQUEST: 0,
}
SUCCESS_PAYLOAD_SIZE = {
    INFO_RESPONSE: 632,
    CONFIGURE_RESPONSE: 20,
    START_RESPONSE: 20,
    GET_STATUS_RESPONSE: 1476,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    GPIO_CAPTURE_DIAGNOSTIC_RESPONSE: 272,
    ERROR_RESPONSE: 8,
}
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE)

PRIMARY_GPIO_PINS = tuple(range(6, 14))
AUX_GPIO_PINS = tuple(range(16, 24))
ALL_GPIO_PINS = PRIMARY_GPIO_PINS + AUX_GPIO_PINS
PRIMARY_GPIO_PORT_BITS = (10, 17, 16, 11, 0, 2, 1, 3)
AUX_GPIO_PORT_BITS = (23, 22, 17, 16, 26, 27, 24, 25)
PRIMARY_GPIO_MASK = 0x00030C0F
AUX_GPIO_MASK = 0x0FC30000
GPIO_PIT_CHANNEL = 0
GPIO_XBAR_INPUT = 56
PRIMARY_XBAR_OUTPUT = 0
AUX_XBAR_OUTPUT = 1
PRIMARY_DMAMUX_SOURCE = 30
AUX_DMAMUX_SOURCE = 31
PRIMARY_EDMA_CHANNEL = 2
AUX_EDMA_CHANNEL = 3
GPIO_DMA_IRQ_PRIORITY = 64
GPIO_RAW_RING_DEPTH = 4
GPIO_PACKED_RING_DEPTH = 4
GPIO_PACKED_RING_BYTES = 16_256
LEGACY_GPIO_RAW_RING_BYTES = 64_768
INPUT_BANK_RAW_RING_BYTES = 32_384
PACKET_BUFFER_COUNT = 200
PACKET_READY_QUEUE_CAPACITY = 200
PACKET_TRANSMIT_QUEUE_CAPACITY = 200
COMMAND_QUEUE_CAPACITY = 4
RESPONSE_QUEUE_CAPACITY = 4
EXPECTED_CAPABILITIES = 0x000007FF

ADC_CONTAINER_BYTES = 2
ADC_BYTES_PER_PAIR = 4
ADC_RESOLUTION_BITS = 12
ADC_DMA_RING_DEPTH = 8
ADC_EDMA_CHANNELS = (0, 1)
ADC_DMAMUX_SOURCES = (24, 88)
ADC_DMA_IRQ_PRIORITY = 48

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
GPIO_DIAGNOSTIC_REQUIRED_NONDRIVING = (
    GPIO_DIAGNOSTIC_AVAILABLE
    | GPIO_DIAGNOSTIC_DECLARATION_VALID
    | GPIO_DIAGNOSTIC_DMA_CAPTURE_EXERCISED
    | GPIO_DIAGNOSTIC_PACKED_OBSERVATION_EXERCISED
    | GPIO_DIAGNOSTIC_FINAL_INPUT_SAFE
)
DMAMUX_ENABLE = 0x80000000
TCD_INTMAJOR = 0x0002
TCD_ESG = 0x0010


@dataclass(frozen=True)
class RateProfile:
    value: int
    name: str
    adc_rate_hz: int
    gpio_rate_hz: int
    adc_period_ticks: int
    adc_phase_ticks: int
    gpio_period_ticks: int
    pit_divider: int
    pit_load: int
    adc_phase_ipg_cycles: int
    completion_dwt_cycles: int
    disabled_coverage_ticks: int
    input_coverage_ticks: int


PROFILES = (
    RateProfile(
        0,
        "ADC_1MHZ_GPIO_4MHZ",
        1_000_000,
        4_000_000,
        8,
        4,
        2,
        6,
        5,
        75,
        300,
        8096,
        4048,
    ),
    RateProfile(
        1,
        "ADC_500KHZ_GPIO_2MHZ",
        500_000,
        2_000_000,
        16,
        8,
        4,
        12,
        11,
        150,
        600,
        16192,
        8096,
    ),
    RateProfile(
        2,
        "ADC_250KHZ_GPIO_1MHZ",
        250_000,
        1_000_000,
        32,
        16,
        8,
        24,
        23,
        300,
        1200,
        32384,
        16192,
    ),
    RateProfile(
        3,
        "ADC_125KHZ_GPIO_500KHZ",
        125_000,
        500_000,
        64,
        32,
        16,
        48,
        47,
        600,
        2400,
        64768,
        32384,
    ),
)
PROFILE_BY_VALUE = {profile.value: profile for profile in PROFILES}
PROFILE_BY_NAME = {profile.name: profile for profile in PROFILES}


@dataclass(frozen=True)
class Layout:
    aux_mode: int
    gpio_width_bits: int
    gpio_item_bytes: int
    gpio_items_per_frame: int
    gpio_payload_bytes: int
    gpio_total_frame_bytes: int
    adc_items_per_frame: int
    adc_payload_bytes: int
    adc_total_frame_bytes: int


LAYOUTS = {
    AUX_DISABLED: Layout(AUX_DISABLED, 8, 1, 4048, 4048, 4096, 1012, 4048, 4096),
    AUX_INPUT: Layout(AUX_INPUT, 16, 2, 2024, 4048, 4096, 506, 2024, 2072),
}
ALLOWED_DATA_SHAPES = {
    ADC_DATA: frozenset(
        (
            layout.adc_total_frame_bytes,
            layout.adc_payload_bytes,
            layout.adc_items_per_frame,
        )
        for layout in LAYOUTS.values()
    ),
    GPIO_DATA: frozenset(
        (
            layout.gpio_total_frame_bytes,
            layout.gpio_payload_bytes,
            layout.gpio_items_per_frame,
        )
        for layout in LAYOUTS.values()
    ),
}
ALLOWED_PERIODS = {
    ADC_DATA: frozenset(profile.adc_period_ticks for profile in PROFILES),
    GPIO_DATA: frozenset(profile.gpio_period_ticks for profile in PROFILES),
}


@dataclass(frozen=True)
class RunCase:
    name: str
    aux_mode: int
    stream_mask: int


RUN_CASES = {
    "CONTROL_GPIO": RunCase("CONTROL_GPIO", AUX_DISABLED, STREAM_GPIO),
    "CONTROL_COMBINED": RunCase("CONTROL_COMBINED", AUX_DISABLED, STREAM_BOTH),
    "INPUT_GPIO": RunCase("INPUT_GPIO", AUX_INPUT, STREAM_GPIO),
    "INPUT_COMBINED": RunCase("INPUT_COMBINED", AUX_INPUT, STREAM_BOTH),
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
    """Independently encode one bounded protocol-v2 command."""

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
        legacy_rejection = version == 1 and kind == ERROR_RESPONSE
        if magic != MAGIC or (version != PROTOCOL_VERSION and not legacy_rejection):
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
            if (total_length, payload_length, item_count) not in ALLOWED_DATA_SHAPES[
                kind
            ]:
                raise ProtocolFailure("data frame does not have a declared v2 shape")
            if flags & ~DATA_FLAG_MASK:
                raise ProtocolFailure("data frame carries a reserved flag")
            if flags & FLAG_OVERRUN_BEFORE and not flags & FLAG_GAP_BEFORE:
                raise ProtocolFailure("OVERRUN_BEFORE lacks GAP_BEFORE")
            if run_id == 0 or request_id != 0:
                raise ProtocolFailure("invalid data run/request/item fields")
            if not any(
                first_sample_ticks % period == 0 for period in ALLOWED_PERIODS[kind]
            ):
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
                payload[383:384],
                payload[411:412],
                payload[431:432],
            )
            if any(any(section) for section in reserved_ranges):
                raise ProtocolFailure("INFO reserved fields are nonzero")
            checksum_mask = struct.unpack_from("<I", payload, 8)[0]
            if not checksum_mask & (1 << payload[45]):
                raise ProtocolFailure("INFO selected checksum is not advertised")
        elif frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            if payload[1]:
                raise ProtocolFailure("configuration response reserved byte is nonzero")
        elif frame.kind == GET_STATUS_RESPONSE:
            if (
                payload[1]
                or any(payload[226:228])
                or any(payload[274:276])
                or any(payload[1260:1264])
            ):
                raise ProtocolFailure("STATUS reserved fields are nonzero")
        elif frame.kind == STOP_RESPONSE:
            if payload[1] or any(payload[5:]):
                raise ProtocolFailure("STOP reserved fields are nonzero")
        elif frame.kind == RESET_STATS_RESPONSE and payload[1]:
            raise ProtocolFailure("RESET_STATS reserved byte is nonzero")
        elif frame.kind == GPIO_CAPTURE_DIAGNOSTIC_RESPONSE and (
            payload[1] or payload[139] or any(payload[149:152]) or payload[255]
        ):
            raise ProtocolFailure("capture diagnostic reserved fields are nonzero")
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
        received_prefix = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise DeadlineExpired(
                    f"request {request_id} kind 0x{request_kind:02x} timed out; "
                    f"parser_errors={self.parser.errors} rx_prefix={received_prefix.hex()}"
                )
            chunk, frames = self._read_chunk_and_frames()
            received_prefix.extend(chunk[: max(0, 96 - len(received_prefix))])
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
    """Require one successful typed response."""

    status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    if frame.kind != expected_kind or frame.flags or status or reserved or error:
        raise ProtocolFailure(
            f"response kind=0x{frame.kind:02x} flags=0x{frame.flags:04x} "
            f"status={status} error={error}; expected success 0x{expected_kind:02x}"
        )


def _u16(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", payload, offset)[0])


def _u32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", payload, offset)[0])


def _u64(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<Q", payload, offset)[0])


def _ascii_field(payload: bytes, offset: int, size: int, name: str) -> str:
    field = payload[offset : offset + size]
    try:
        terminator = field.index(0)
        value = field[:terminator].decode("ascii")
    except (ValueError, UnicodeDecodeError) as error:
        raise ProtocolFailure(f"{name} is not NUL-terminated ASCII") from error
    if any(field[terminator + 1 :]):
        raise ProtocolFailure(f"{name} padding is nonzero")
    return value


def _decode_rate_profile(payload: bytes, offset: int) -> dict[str, int]:
    return {
        "value": payload[offset],
        "predivider": payload[offset + 1],
        "chain_length": payload[offset + 2],
        "reserved": payload[offset + 3],
        "adc_rate_hz": _u32(payload, offset + 4),
        "gpio_rate_hz": _u32(payload, offset + 8),
        "adc_period_ticks": _u16(payload, offset + 12),
        "adc_phase_ticks": _u16(payload, offset + 14),
        "gpio_period_ticks": _u16(payload, offset + 16),
        "pit_divider": _u16(payload, offset + 18),
        "pit_load": _u16(payload, offset + 20),
        "adc_pair_divider": _u16(payload, offset + 22),
        "adc_pair_load": _u16(payload, offset + 24),
        "adc0_initial_delay": _u16(payload, offset + 26),
        "adc1_initial_delay": _u16(payload, offset + 28),
        "adc0_effective_delay": _u16(payload, offset + 30),
        "adc1_effective_delay": _u16(payload, offset + 32),
        "phase_ipg_cycles": _u16(payload, offset + 34),
        "completion_dwt_cycles": _u32(payload, offset + 36),
        "disabled_coverage_ticks": _u32(payload, offset + 40),
        "input_coverage_ticks": _u32(payload, offset + 44),
    }


def decode_info(frame: Frame) -> dict[str, object]:
    response_success(frame, INFO_RESPONSE)
    p = frame.payload
    return {
        "device_state": p[4],
        "protocol_version": p[5],
        "supported_stream_mask": p[6],
        "supported_source_mask": p[7],
        "supported_checksum_mask": _u32(p, 8),
        "capability_bits": _u32(p, 12),
        "timestamp_hz": _u32(p, 16),
        "data_frame_bytes": _u32(p, 20),
        "max_control_frame_bytes": _u32(p, 24),
        "adc_pair_rate_hz": _u32(p, 28),
        "gpio_sample_rate_hz": _u32(p, 32),
        "adc_pair_period_ticks": _u16(p, 36),
        "adc1_phase_ticks": _u16(p, 38),
        "gpio_sample_period_ticks": _u16(p, 40),
        "adc_resolution_bits": p[42],
        "adc_container_bytes": p[43],
        "gpio_pin_count": p[44],
        "data_checksum_algorithm": p[45],
        "gpio_pin_map": tuple(p[46:54]),
        "hardware_serial": _u32(p, 54),
        "firmware_version": tuple(p[58:61]),
        "board_id": _u16(p, 62),
        "mcu_id": _u16(p, 64),
        "build_id": _ascii_field(p, 66, 32, "INFO build ID"),
        "gpio_packed_width_bits": p[98],
        "gpio_raw_ring_depth": p[99],
        "gpio_packed_ring_depth": p[100],
        "gpio_diagnostic_mode": p[101],
        "gpio_diagnostic_flags": _u16(p, 102),
        "gpio_raw_samples_per_buffer": _u32(p, 104),
        "gpio_raw_ring_bytes": _u32(p, 108),
        "gpio_packed_ring_bytes": _u32(p, 112),
        "gpio_packet_buffer_count": _u16(p, 116),
        "gpio_pit_channel": p[120],
        "gpio_xbar_input": p[121],
        "gpio_xbar_output": p[122],
        "gpio_edma_channel": p[123],
        "gpio_dmamux_source": p[124],
        "gpio_edma_priority": p[125],
        "gpio_xbar_active_edge": p[126],
        "applied_stream_mask": p[324],
        "applied_source": p[325],
        "supported_configuration_mask": _u16(p, 326),
        "data_payload_bytes": _u16(p, 328),
        "adc_pairs_per_frame": _u16(p, 330),
        "gpio_samples_per_frame": _u16(p, 332),
        "frame_coverage_ticks": _u32(p, 336),
        "adc_dma_ring_depth": p[340],
        "adc_pair_bytes": p[341],
        "adc_edma_channels": tuple(p[342:344]),
        "adc_edma_priorities": tuple(p[344:346]),
        "adc_dmamux_sources": tuple(p[346:348]),
        "adc_dma_irq_priority": p[348],
        "gpio_dma_irq_priority": p[349],
        "adc_pairs_per_buffer": _u16(p, 350),
        "adc_dma_ring_bytes": _u32(p, 352),
        "packet_buffer_count": _u16(p, 356),
        "packet_primary_count": _u16(p, 358),
        "packet_reserve_count": _u16(p, 360),
        "packet_ready_queue_capacity": _u16(p, 362),
        "packet_transmit_queue_capacity": _u16(p, 364),
        "command_queue_capacity": p[366],
        "response_queue_capacity": p[367],
        "supported_rate_profile_mask": p[376],
        "selected_rate_profile": p[377],
        "supported_aux_mode_mask": p[378],
        "applied_aux_mode": p[379],
        "gpio_item_bytes": p[380],
        "aux_gpio_pin_count": p[381],
        "rate_profile_count": p[382],
        "aux_gpio_pin_map": tuple(p[384:392]),
        "aux_gpio_port_bits": tuple(p[392:400]),
        "aux_gpio_standard_port": p[400],
        "aux_gpio_fast_port": p[401],
        "aux_gpio_fast_select_gpr": p[402],
        "gpio_raw_word_bytes": p[403],
        "aux_gpio_capture_mask": _u32(p, 404),
        "primary_gpio_standard_port": p[408],
        "primary_gpio_fast_port": p[409],
        "primary_gpio_fast_select_gpr": p[410],
        "primary_gpio_capture_mask": _u32(p, 412),
        "primary_gpio_edma_channel": p[416],
        "aux_gpio_edma_channel": p[417],
        "primary_gpio_dmamux_source": p[418],
        "aux_gpio_dmamux_source": p[419],
        "primary_gpio_xbar_output": p[420],
        "aux_gpio_xbar_output": p[421],
        "paired_gpio_xbar_input": p[422],
        "aux_gpio_edma_priority": p[423],
        "primary_gpio_edma_priority": p[424],
        "adc0_edma_priority": p[425],
        "adc1_edma_priority": p[426],
        "aux_gpio_dma_irq_priority": p[427],
        "primary_gpio_raw_ring_depth": p[428],
        "aux_gpio_raw_ring_depth": p[429],
        "paired_gpio_join_required": p[430],
        "disabled_adc_pairs_per_frame": _u16(p, 432),
        "disabled_gpio_samples_per_frame": _u16(p, 434),
        "input_adc_pairs_per_frame": _u16(p, 436),
        "input_gpio_samples_per_frame": _u16(p, 438),
        "rate_profiles": tuple(_decode_rate_profile(p, 440 + 48 * i) for i in range(4)),
    }


def decode_configuration(frame: Frame, expected_kind: int) -> tuple[int, ...]:
    response_success(frame, expected_kind)
    return tuple(int(value) for value in CONFIGURATION.unpack_from(frame.payload, 4))


class Evidence:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []
        self.failures: list[str] = []

    def check(self, name: str, expected: object, actual: object, passed: bool) -> None:
        record = {
            "name": name,
            "expected": expected,
            "actual": actual,
            "pass": bool(passed),
        }
        self.checks.append(record)
        if not passed:
            self.failures.append(f"{name}: expected {expected!r}, got {actual!r}")

    def equal(self, name: str, expected: object, actual: object) -> None:
        self.check(name, expected, actual, actual == expected)


def emit_event(name: str, **fields: object) -> None:
    print(
        "EVENT "
        + json.dumps({"event": name, **fields}, sort_keys=True, separators=(",", ":"))
    )


def stable_identity(info: dict[str, object]) -> tuple[object, ...]:
    keys = (
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
        "supported_rate_profile_mask",
        "supported_aux_mode_mask",
        "rate_profiles",
    )
    return tuple(info[key] for key in keys)


def _info_int(info: dict[str, object], name: str) -> int:
    value = info[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolFailure(f"INFO {name} is not an integer")
    return value


def synchronize(link: SerialLink) -> dict[str, object]:
    previous: dict[str, object] | None = None
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, _ = link.exchange(INFO_REQUEST, timeout=SYNC_DEADLINE_SECONDS)
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
    raise DeadlineExpired(f"stable INFO synchronization failed: {last_error}")


@dataclass(frozen=True)
class FixtureDeclaration:
    fixture_identity: int
    stimulus_identity: int
    pins_by_bit: tuple[int, ...]
    required_transition_mask: int


def load_fixture_declaration(raw: str | None) -> FixtureDeclaration | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("AUX_INPUT_FIXTURE_JSON must be valid JSON") from error
    if not isinstance(value, dict):
        raise TypeError("AUX_INPUT_FIXTURE_JSON must be a JSON object")
    if value.get("schema") != "thingdaq.aux-input-stimulus/v1":
        raise ValueError("fixture schema must be thingdaq.aux-input-stimulus/v1")
    if value.get("authorized") is not True:
        raise ValueError("fixture declaration must set authorized=true")
    try:
        fixture_identity = int(value["fixture_identity"])
        stimulus_identity = int(value["stimulus_identity"])
        pins = tuple(int(pin) for pin in value["pins_by_bit"])
        transition_mask = int(value.get("required_transition_mask", 0xFF))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "fixture identities, pins, and transition mask must be integers"
        ) from error
    if (
        not 1 <= fixture_identity <= 0xFFFFFFFF
        or not 1 <= stimulus_identity <= 0xFFFFFFFF
    ):
        raise ValueError(
            "fixture and stimulus identities must be nonzero uint32 values"
        )
    if pins != AUX_GPIO_PINS:
        raise ValueError(
            "fixture pins_by_bit must declare D16 through D23 in wire order"
        )
    if not 0 <= transition_mask <= 0xFF:
        raise ValueError("required_transition_mask must be an auxiliary uint8 mask")
    return FixtureDeclaration(
        fixture_identity, stimulus_identity, pins, transition_mask
    )


def _expected_profile_record(profile: RateProfile) -> dict[str, int]:
    return {
        "value": profile.value,
        "predivider": 0,
        "chain_length": 1,
        "reserved": 0,
        "adc_rate_hz": profile.adc_rate_hz,
        "gpio_rate_hz": profile.gpio_rate_hz,
        "adc_period_ticks": profile.adc_period_ticks,
        "adc_phase_ticks": profile.adc_phase_ticks,
        "gpio_period_ticks": profile.gpio_period_ticks,
        "pit_divider": profile.pit_divider,
        "pit_load": profile.pit_load,
        "adc_pair_divider": 4,
        "adc_pair_load": 3,
        "adc0_initial_delay": 0,
        "adc1_initial_delay": profile.adc_phase_ipg_cycles,
        "adc0_effective_delay": 1,
        "adc1_effective_delay": profile.adc_phase_ipg_cycles + 1,
        "phase_ipg_cycles": profile.adc_phase_ipg_cycles,
        "completion_dwt_cycles": profile.completion_dwt_cycles,
        "disabled_coverage_ticks": profile.disabled_coverage_ticks,
        "input_coverage_ticks": profile.input_coverage_ticks,
    }


def grade_static_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> None:
    exact: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "supported_stream_mask": STREAM_BOTH,
        "supported_source_mask": 3,
        "supported_checksum_mask": SUPPORTED_CHECKSUM_MASK,
        "capability_bits": EXPECTED_CAPABILITIES,
        "timestamp_hz": TIMESTAMP_HZ,
        "data_frame_bytes": MAX_FRAME_BYTES,
        "max_control_frame_bytes": MAX_CONTROL_FRAME_BYTES,
        "adc_resolution_bits": ADC_RESOLUTION_BITS,
        "adc_container_bytes": ADC_CONTAINER_BYTES,
        "gpio_pin_count": 8,
        "gpio_pin_map": PRIMARY_GPIO_PINS,
        "board_id": 1,
        "mcu_id": 1,
        "gpio_raw_ring_depth": GPIO_RAW_RING_DEPTH,
        "gpio_packed_ring_depth": GPIO_PACKED_RING_DEPTH,
        "gpio_packed_ring_bytes": GPIO_PACKED_RING_BYTES,
        "gpio_packet_buffer_count": PACKET_BUFFER_COUNT,
        "gpio_pit_channel": GPIO_PIT_CHANNEL,
        "gpio_xbar_input": GPIO_XBAR_INPUT,
        "gpio_xbar_output": PRIMARY_XBAR_OUTPUT,
        "gpio_edma_channel": PRIMARY_EDMA_CHANNEL,
        "gpio_dmamux_source": PRIMARY_DMAMUX_SOURCE,
        "gpio_xbar_active_edge": 1,
        "supported_configuration_mask": 0x003F,
        "adc_dma_ring_depth": ADC_DMA_RING_DEPTH,
        "adc_pair_bytes": ADC_BYTES_PER_PAIR,
        "adc_edma_channels": ADC_EDMA_CHANNELS,
        "adc_dmamux_sources": ADC_DMAMUX_SOURCES,
        "adc_dma_irq_priority": ADC_DMA_IRQ_PRIORITY,
        "gpio_dma_irq_priority": GPIO_DMA_IRQ_PRIORITY,
        "packet_buffer_count": PACKET_BUFFER_COUNT,
        "packet_primary_count": 105,
        "packet_reserve_count": 95,
        "packet_ready_queue_capacity": PACKET_READY_QUEUE_CAPACITY,
        "packet_transmit_queue_capacity": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "command_queue_capacity": COMMAND_QUEUE_CAPACITY,
        "response_queue_capacity": RESPONSE_QUEUE_CAPACITY,
        "supported_rate_profile_mask": 0x0F,
        "supported_aux_mode_mask": 0x03,
        "aux_gpio_pin_count": 8,
        "rate_profile_count": 4,
        "aux_gpio_pin_map": AUX_GPIO_PINS,
        "aux_gpio_port_bits": AUX_GPIO_PORT_BITS,
        "aux_gpio_standard_port": 1,
        "aux_gpio_fast_port": 6,
        "aux_gpio_fast_select_gpr": 26,
        "gpio_raw_word_bytes": 4,
        "aux_gpio_capture_mask": AUX_GPIO_MASK,
        "primary_gpio_standard_port": 2,
        "primary_gpio_fast_port": 7,
        "primary_gpio_fast_select_gpr": 27,
        "primary_gpio_capture_mask": PRIMARY_GPIO_MASK,
        "primary_gpio_edma_channel": PRIMARY_EDMA_CHANNEL,
        "aux_gpio_edma_channel": AUX_EDMA_CHANNEL,
        "primary_gpio_dmamux_source": PRIMARY_DMAMUX_SOURCE,
        "aux_gpio_dmamux_source": AUX_DMAMUX_SOURCE,
        "primary_gpio_xbar_output": PRIMARY_XBAR_OUTPUT,
        "aux_gpio_xbar_output": AUX_XBAR_OUTPUT,
        "paired_gpio_xbar_input": GPIO_XBAR_INPUT,
        "aux_gpio_edma_priority": 0,
        "aux_gpio_dma_irq_priority": GPIO_DMA_IRQ_PRIORITY,
        "primary_gpio_raw_ring_depth": GPIO_RAW_RING_DEPTH,
        "aux_gpio_raw_ring_depth": GPIO_RAW_RING_DEPTH,
        "paired_gpio_join_required": 1,
        "disabled_adc_pairs_per_frame": LAYOUTS[AUX_DISABLED].adc_items_per_frame,
        "disabled_gpio_samples_per_frame": LAYOUTS[AUX_DISABLED].gpio_items_per_frame,
        "input_adc_pairs_per_frame": LAYOUTS[AUX_INPUT].adc_items_per_frame,
        "input_gpio_samples_per_frame": LAYOUTS[AUX_INPUT].gpio_items_per_frame,
        "rate_profiles": tuple(
            _expected_profile_record(profile) for profile in PROFILES
        ),
    }
    for name, expected in exact.items():
        evidence.equal(f"identity.{name}", expected, info[name])
    selected_checksum = _info_int(info, "data_checksum_algorithm")
    evidence.check(
        "identity.selected_checksum",
        "advertised supported checksum",
        selected_checksum,
        selected_checksum in SUPPORTED_CHECKSUMS
        and bool(_info_int(info, "supported_checksum_mask") & (1 << selected_checksum)),
    )
    version = info["firmware_version"]
    evidence.check(
        "identity.minimum_firmware",
        ">= (0, 7, 0)",
        version,
        isinstance(version, tuple) and version >= (0, 7, 0),
    )
    build_id = info["build_id"]
    evidence.check(
        "identity.build_id",
        expected_build_id or "thingdaq-<16 lowercase hex>",
        build_id,
        isinstance(build_id, str)
        and re.fullmatch(r"thingdaq-[0-9a-f]{16}", build_id) is not None
        and (expected_build_id is None or build_id == expected_build_id),
    )
    serial_number = _info_int(info, "hardware_serial")
    evidence.check(
        "identity.hardware_serial",
        expected_hardware_serial or "nonzero uint32",
        serial_number,
        1 <= serial_number <= 0xFFFFFFFF
        and (
            expected_hardware_serial is None
            or serial_number == expected_hardware_serial
        ),
    )
    evidence.check(
        "identity.diagnostic_non_driving",
        "NON_DRIVING_CAPTURE or declared FIXTURE_STIMULUS without output drive",
        {"mode": info["gpio_diagnostic_mode"], "flags": info["gpio_diagnostic_flags"]},
        _info_int(info, "gpio_diagnostic_mode") in {0, 2}
        and not _info_int(info, "gpio_diagnostic_flags")
        & (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
        ),
    )


def grade_active_info(
    evidence: Evidence,
    info: dict[str, object],
    case: RunCase,
    profile: RateProfile,
    *,
    expected_checksum: int,
    expected_state: int,
) -> None:
    layout = LAYOUTS[case.aux_mode]
    coverage = (
        profile.input_coverage_ticks
        if case.aux_mode == AUX_INPUT
        else profile.disabled_coverage_ticks
    )
    raw_ring_bytes = layout.gpio_items_per_frame * 4 * GPIO_RAW_RING_DEPTH
    adc_ring_bytes = math.ceil(layout.adc_payload_bytes / 32) * 32 * ADC_DMA_RING_DEPTH
    exact: dict[str, object] = {
        "device_state": expected_state,
        "data_checksum_algorithm": expected_checksum,
        "applied_stream_mask": case.stream_mask,
        "applied_source": SOURCE_HARDWARE,
        "selected_rate_profile": profile.value,
        "applied_aux_mode": case.aux_mode,
        "adc_pair_rate_hz": profile.adc_rate_hz,
        "gpio_sample_rate_hz": profile.gpio_rate_hz,
        "adc_pair_period_ticks": profile.adc_period_ticks,
        "adc1_phase_ticks": profile.adc_phase_ticks,
        "gpio_sample_period_ticks": profile.gpio_period_ticks,
        "gpio_packed_width_bits": layout.gpio_width_bits,
        "gpio_item_bytes": layout.gpio_item_bytes,
        "gpio_raw_samples_per_buffer": layout.gpio_items_per_frame,
        "gpio_raw_ring_bytes": raw_ring_bytes,
        "data_payload_bytes": layout.adc_payload_bytes,
        "adc_pairs_per_frame": layout.adc_items_per_frame,
        "gpio_samples_per_frame": layout.gpio_items_per_frame,
        "frame_coverage_ticks": coverage,
        "adc_pairs_per_buffer": layout.adc_items_per_frame,
        "adc_dma_ring_bytes": adc_ring_bytes,
        "adc_edma_priorities": (3, 2) if case.aux_mode == AUX_INPUT else (2, 1),
        # Extension fields publish the fixed INPUT arbitration vector even
        # while DISABLED; legacy active-route fields above follow the mode.
        "adc0_edma_priority": 3,
        "adc1_edma_priority": 2,
        "primary_gpio_edma_priority": 1,
        "gpio_edma_priority": 1 if case.aux_mode == AUX_INPUT else 0,
    }
    for name, expected in exact.items():
        evidence.equal(f"active.{name}", expected, info[name])


CAPTURE_U32 = {
    "fixture_identity": 8,
    "stimulus_identity": 12,
    "hardware_error_flags": 16,
    "diagnostic_flags": 20,
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
    "dmamux_chcfg_configured": 120,
    "dma_erq_configured": 124,
    "dma_err_final": 128,
    "analysis_sample_limit": 140,
    "configured_rate_hz": 152,
    "aux_hardware_error_flags": 156,
    "aux_diagnostic_flags": 160,
    "aux_complete_samples_retained": 172,
    "aux_samples_analyzed": 176,
    "aux_stopped_partial_samples": 180,
    "aux_raw_word_and": 184,
    "aux_raw_word_or": 188,
    "aux_observed_transitions": 192,
    "gpr26_before": 200,
    "gpr26_configured": 204,
    "gpr26_after": 208,
    "gpio1_gdir_before": 212,
    "gpio1_gdir_configured": 216,
    "gpio1_gdir_after": 220,
    "aux_dmamux_chcfg_configured": 236,
    "aux_dma_erq_configured": 240,
    "aux_dma_err_final": 244,
    "primary_cache_dma_discards": 256,
    "aux_cache_dma_discards": 260,
    "primary_cache_cpu_invalidations": 264,
    "aux_cache_cpu_invalidations": 268,
}


def decode_capture_diagnostic(frame: Frame) -> dict[str, int]:
    response_success(frame, GPIO_CAPTURE_DIAGNOSTIC_RESPONSE)
    p = frame.payload
    result = {name: _u32(p, offset) for name, offset in CAPTURE_U32.items()}
    result.update(
        {
            "mode": p[4],
            "drive_safety": p[6],
            "stimulus_kind": p[7],
            "mapping_values_checked": _u16(p, 64),
            "mapping_failures": _u16(p, 66),
            "unstable_samples": _u16(p, 68),
            "packed_value_and": p[72],
            "packed_value_or": p[73],
            "tcd_citer": _u16(p, 132),
            "tcd_biter": _u16(p, 134),
            "tcd_csr": _u16(p, 136),
            "edma_priority": p[138],
            "bank_count": p[144],
            "aux_mode": p[145],
            "rate_profile": p[146],
            "aux_electrically_unstimulated": p[147],
            "aux_external_transition_checks_run": p[148],
            "aux_packed_value_and": p[196],
            "aux_packed_value_or": p[197],
            "aux_tcd_citer": _u16(p, 248),
            "aux_tcd_biter": _u16(p, 250),
            "aux_tcd_csr": _u16(p, 252),
            "aux_edma_priority": p[254],
            "dma_samples_captured": _u64(p, 32),
            "aux_dma_samples_captured": _u64(p, 164),
        }
    )
    return result


def _pack_port_mask(mask: int, port_bits: tuple[int, ...]) -> int:
    return sum(((mask >> bit) & 1) << index for index, bit in enumerate(port_bits))


def grade_capture_diagnostic(
    evidence: Evidence,
    snapshot: dict[str, int],
    fixture: FixtureDeclaration | None,
) -> str:
    flags = snapshot["diagnostic_flags"]
    aux_flags = snapshot["aux_diagnostic_flags"]
    exact = {
        "bank_count": 2,
        "aux_mode": AUX_INPUT,
        "rate_profile": 0,
        "configured_rate_hz": PROFILES[0].gpio_rate_hz,
        "hardware_error_flags": 0,
        "aux_hardware_error_flags": 0,
        "mapping_failures": 0,
        "unstable_samples": 0,
        "dma_err_final": 0,
        "aux_dma_err_final": 0,
        "tcd_biter": LAYOUTS[AUX_INPUT].gpio_items_per_frame,
        "aux_tcd_citer": LAYOUTS[AUX_INPUT].gpio_items_per_frame,
        "aux_tcd_biter": LAYOUTS[AUX_INPUT].gpio_items_per_frame,
        "tcd_csr": TCD_ESG | TCD_INTMAJOR,
        "aux_tcd_csr": TCD_ESG | TCD_INTMAJOR,
        "edma_priority": 1,
        "aux_edma_priority": 0,
    }
    for name, expected in exact.items():
        evidence.equal(f"diagnostic.{name}", expected, snapshot[name])
    evidence.check(
        "diagnostic.tcd_citer",
        f"0..{LAYOUTS[AUX_INPUT].gpio_items_per_frame}",
        snapshot["tcd_citer"],
        0 <= snapshot["tcd_citer"] <= LAYOUTS[AUX_INPUT].gpio_items_per_frame,
    )
    evidence.check(
        "diagnostic.flags",
        "known non-driving capture flags",
        flags,
        not flags & ~KNOWN_GPIO_DIAGNOSTIC_FLAGS
        and flags & GPIO_DIAGNOSTIC_REQUIRED_NONDRIVING
        == GPIO_DIAGNOSTIC_REQUIRED_NONDRIVING
        and not flags
        & (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
        ),
    )
    evidence.check(
        "diagnostic.aux_flags",
        "known non-driving capture flags",
        aux_flags,
        not aux_flags & ~KNOWN_GPIO_DIAGNOSTIC_FLAGS
        and aux_flags & GPIO_DIAGNOSTIC_REQUIRED_NONDRIVING
        == GPIO_DIAGNOSTIC_REQUIRED_NONDRIVING
        and not aux_flags
        & (
            GPIO_DIAGNOSTIC_OUTPUT_DRIVE_PERMITTED
            | GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
        ),
    )
    evidence.check(
        "diagnostic.paired_counts",
        "each bank retains a complete block and has a bounded partial tail",
        {
            "primary": snapshot["complete_samples_retained"],
            "aux": snapshot["aux_complete_samples_retained"],
            "primary_partial": snapshot["stopped_partial_samples"],
            "aux_partial": snapshot["aux_stopped_partial_samples"],
        },
        snapshot["complete_samples_retained"]
        == LAYOUTS[AUX_DISABLED].gpio_items_per_frame
        and snapshot["aux_complete_samples_retained"]
        == LAYOUTS[AUX_INPUT].gpio_items_per_frame
        and 0
        <= snapshot["stopped_partial_samples"]
        < LAYOUTS[AUX_INPUT].gpio_items_per_frame
        and 0
        <= snapshot["aux_stopped_partial_samples"]
        < LAYOUTS[AUX_INPUT].gpio_items_per_frame,
    )
    evidence.check(
        "diagnostic.primary_capture_accounting",
        "retained + partial <= captured",
        snapshot["dma_samples_captured"],
        snapshot["complete_samples_retained"] + snapshot["stopped_partial_samples"]
        <= snapshot["dma_samples_captured"],
    )
    evidence.check(
        "diagnostic.aux_capture_accounting",
        "retained + partial <= captured",
        snapshot["aux_dma_samples_captured"],
        snapshot["aux_complete_samples_retained"]
        + snapshot["aux_stopped_partial_samples"]
        <= snapshot["aux_dma_samples_captured"],
    )
    evidence.check(
        "diagnostic.analysis_counts",
        "both banks analyze the declared nonzero bounded sample count",
        (
            snapshot["analysis_sample_limit"],
            snapshot["samples_analyzed"],
            snapshot["aux_samples_analyzed"],
        ),
        0
        < snapshot["analysis_sample_limit"]
        == snapshot["samples_analyzed"]
        == snapshot["aux_samples_analyzed"]
        <= LAYOUTS[AUX_INPUT].gpio_items_per_frame,
    )
    evidence.equal(
        "diagnostic.primary_packed_and",
        _pack_port_mask(snapshot["raw_word_and"], PRIMARY_GPIO_PORT_BITS),
        snapshot["packed_value_and"],
    )
    evidence.equal(
        "diagnostic.primary_packed_or",
        _pack_port_mask(snapshot["raw_word_or"], PRIMARY_GPIO_PORT_BITS),
        snapshot["packed_value_or"],
    )
    evidence.equal(
        "diagnostic.aux_packed_and",
        _pack_port_mask(snapshot["aux_raw_word_and"], AUX_GPIO_PORT_BITS),
        snapshot["aux_packed_value_and"],
    )
    evidence.equal(
        "diagnostic.aux_packed_or",
        _pack_port_mask(snapshot["aux_raw_word_or"], AUX_GPIO_PORT_BITS),
        snapshot["aux_packed_value_or"],
    )
    evidence.check(
        "diagnostic.cache_ownership",
        "both banks discarded before DMA and invalidated on CPU acquisition",
        {
            "discard": (
                snapshot["primary_cache_dma_discards"],
                snapshot["aux_cache_dma_discards"],
            ),
            "invalidate": (
                snapshot["primary_cache_cpu_invalidations"],
                snapshot["aux_cache_cpu_invalidations"],
            ),
        },
        snapshot["primary_cache_dma_discards"] > 0
        and snapshot["aux_cache_dma_discards"] > 0
        and snapshot["primary_cache_cpu_invalidations"] > 0
        and snapshot["aux_cache_cpu_invalidations"] > 0,
    )
    evidence.equal(
        "diagnostic.primary_direction_safe",
        0,
        snapshot["gpio2_gdir_configured"] & PRIMARY_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.aux_direction_safe",
        0,
        snapshot["gpio1_gdir_configured"] & AUX_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.primary_gpr_configured",
        0,
        snapshot["gpr27_configured"] & PRIMARY_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.aux_gpr_configured",
        0,
        snapshot["gpr26_configured"] & AUX_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.primary_dmamux",
        DMAMUX_ENABLE | PRIMARY_DMAMUX_SOURCE,
        snapshot["dmamux_chcfg_configured"],
    )
    evidence.equal(
        "diagnostic.aux_dmamux",
        DMAMUX_ENABLE | AUX_DMAMUX_SOURCE,
        snapshot["aux_dmamux_chcfg_configured"],
    )
    evidence.equal(
        "diagnostic.primary_dma_request",
        1 << PRIMARY_EDMA_CHANNEL,
        snapshot["dma_erq_configured"] & (1 << PRIMARY_EDMA_CHANNEL),
    )
    evidence.equal(
        "diagnostic.aux_dma_request",
        1 << AUX_EDMA_CHANNEL,
        snapshot["aux_dma_erq_configured"] & (1 << AUX_EDMA_CHANNEL),
    )
    evidence.equal(
        "diagnostic.primary_gpr_safe",
        0,
        snapshot["gpr27_after"] & PRIMARY_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.aux_gpr_safe",
        0,
        snapshot["gpr26_after"] & AUX_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.primary_direction_after_safe",
        0,
        snapshot["gpio2_gdir_after"] & PRIMARY_GPIO_MASK,
    )
    evidence.equal(
        "diagnostic.aux_direction_after_safe",
        0,
        snapshot["gpio1_gdir_after"] & AUX_GPIO_MASK,
    )
    if fixture is None:
        evidence.equal(
            "stimulus.aux_electrically_unstimulated",
            1,
            snapshot["aux_electrically_unstimulated"],
        )
        evidence.equal(
            "stimulus.external_transition_checks",
            0,
            snapshot["aux_external_transition_checks_run"],
        )
        return "NOT_RUN"
    evidence.equal("stimulus.diagnostic_mode", 2, snapshot["mode"])
    evidence.equal(
        "stimulus.fixture_identity",
        fixture.fixture_identity,
        snapshot["fixture_identity"],
    )
    evidence.equal(
        "stimulus.stimulus_identity",
        fixture.stimulus_identity,
        snapshot["stimulus_identity"],
    )
    evidence.equal(
        "stimulus.aux_electrically_unstimulated",
        0,
        snapshot["aux_electrically_unstimulated"],
    )
    evidence.equal(
        "stimulus.external_transition_checks",
        1,
        snapshot["aux_external_transition_checks_run"],
    )
    required = (
        GPIO_DIAGNOSTIC_EXTERNAL_STIMULUS_DECLARED
        | GPIO_DIAGNOSTIC_EXTERNAL_TRANSITION_VALIDATION_EXERCISED
    )
    evidence.check(
        "stimulus.authorization_flags",
        "declared and transition-validated",
        aux_flags,
        aux_flags & required == required,
    )
    observed_mask = _pack_port_mask(
        snapshot["aux_raw_word_and"] ^ snapshot["aux_raw_word_or"], AUX_GPIO_PORT_BITS
    )
    evidence.check(
        "stimulus.aux_transition_mask",
        f"contains 0x{fixture.required_transition_mask:02x}",
        f"0x{observed_mask:02x}",
        observed_mask & fixture.required_transition_mask
        == fixture.required_transition_mask,
    )
    return "GRADED"


STATUS_FIELDS = {
    "device_state": ("B", 4),
    "stream_mask": ("B", 5),
    "source": ("B", 6),
    "data_checksum_algorithm": ("B", 7),
    "data_frame_bytes": ("I", 8),
    "adc_frames_emitted": ("Q", 12),
    "gpio_frames_emitted": ("Q", 20),
    "adc_items_dropped": ("Q", 28),
    "gpio_items_dropped": ("Q", 36),
    "parser_errors": ("I", 44),
    "transport_errors": ("I", 48),
    "stats_generation": ("I", 52),
    "gpio_samples_captured": ("Q", 56),
    "gpio_samples_packed": ("Q", 64),
    "gpio_samples_framed": ("Q", 72),
    "gpio_samples_transmitted": ("Q", 80),
    "gpio_raw_samples_lost": ("Q", 88),
    "gpio_packer_samples_dropped": ("Q", 96),
    "gpio_raw_ring_overruns": ("Q", 104),
    "gpio_dma_major_loops": ("Q", 112),
    "gpio_raw_ready_depth": ("H", 120),
    "gpio_raw_ready_high_water": ("H", 122),
    "gpio_packed_ready_depth": ("H", 124),
    "gpio_packed_ready_high_water": ("H", 126),
    "packet_ready_depth": ("H", 128),
    "packet_transmit_depth": ("H", 130),
    "packet_owned_high_water": ("H", 132),
    "gpio_processing_cpu_basis_points": ("H", 134),
    "gpio_hardware_errors": ("I", 136),
    "gpio_raw_invariant_errors": ("I", 140),
    "gpio_packer_source_errors": ("I", 144),
    "gpio_packer_pipeline_errors": ("I", 148),
    "gpio_packer_chronology_errors": ("I", 152),
    "gpio_resource_conflicts": ("I", 156),
    "gpio_start_errors": ("I", 160),
    "gpio_stop_errors": ("I", 164),
    "gpio_stale_dma_completions": ("I", 168),
    "adc_resolution_bits": ("B", 172),
    "adc_container_bytes": ("B", 173),
    "adc0_calibration_state": ("B", 174),
    "adc1_calibration_state": ("B", 175),
    "adc_code_min": ("H", 176),
    "adc_code_max": ("H", 178),
    "adc_reference": ("B", 180),
    "adc_clock_source": ("B", 181),
    "adc_clock_divider": ("B", 182),
    "adc_hardware_average_count": ("B", 183),
    "adc_reference_mv_nominal": ("H", 184),
    "adc_input_min_mv_nominal": ("H", 186),
    "adc_input_max_mv_nominal": ("H", 188),
    "adc_sample_time_adck": ("B", 190),
    "adc_conversion_mode": ("B", 191),
    "adc_configuration_flags": ("H", 192),
    "adc0_pin": ("B", 194),
    "adc1_pin": ("B", 195),
    "adc0_peripheral": ("B", 196),
    "adc1_peripheral": ("B", 197),
    "adc0_channel": ("B", 198),
    "adc1_channel": ("B", 199),
    "adc_ipg_clock_hz": ("I", 200),
    "adc_clock_hz": ("I", 204),
    "adc_calibration_deadline_us": ("I", 208),
    "adc0_calibration_cycles": ("I", 212),
    "adc1_calibration_cycles": ("I", 216),
    "adc_initialization_error_flags": ("I", 220),
    "adc_trigger_configuration_flags": ("H", 224),
    "adc_trigger_error_flags": ("I", 228),
    "adc_trigger_pit_clock_hz": ("I", 232),
    "adc_trigger_dwt_clock_hz": ("I", 236),
    "adc_trigger_gpio_master_rate_hz": ("I", 240),
    "adc_trigger_pair_rate_hz": ("I", 244),
    "adc_trigger_ipg_clock_hz": ("I", 248),
    "adc_trigger_gpio_master_pit_channel": ("B", 252),
    "adc_trigger_pair_pit_channel": ("B", 253),
    "adc_trigger_gpio_master_pit_load": ("B", 254),
    "adc_trigger_pair_pit_load": ("B", 255),
    "adc_trigger_predivider": ("B", 256),
    "adc_trigger_chain_length": ("B", 257),
    "adc0_trigger_xbar_input": ("B", 258),
    "adc1_trigger_xbar_input": ("B", 259),
    "adc0_trigger_xbar_output": ("B", 260),
    "adc1_trigger_xbar_output": ("B", 261),
    "adc0_etc_trigger_queue": ("B", 262),
    "adc1_etc_trigger_queue": ("B", 263),
    "adc0_trigger_initial_delay": ("H", 264),
    "adc1_trigger_initial_delay": ("H", 266),
    "adc0_trigger_effective_delay": ("H", 268),
    "adc1_trigger_effective_delay": ("H", 270),
    "adc_trigger_phase_ipg_cycles": ("H", 272),
    "adc_trigger_ccm_cscmr1_configured": ("I", 276),
    "adc_trigger_ccm_ccgr1_configured": ("I", 280),
    "adc_trigger_ccm_ccgr2_configured": ("I", 284),
    "adc_trigger_pit_mcr_configured": ("I", 288),
    "adc_trigger_gpio_master_tctrl_configured": ("I", 292),
    "adc_trigger_pair_tctrl_configured": ("I", 296),
    "adc_etc_ctrl_configured": ("I", 300),
    "adc0_etc_trigger_ctrl_configured": ("I", 304),
    "adc1_etc_trigger_ctrl_configured": ("I", 308),
    "adc0_etc_trigger_counter_configured": ("I", 312),
    "adc1_etc_trigger_counter_configured": ("I", 316),
    "adc0_etc_chain_configured": ("I", 320),
    "adc1_etc_chain_configured": ("I", 324),
    "adc_etc_done0_1_irq_final": ("I", 328),
    "adc_etc_done2_err_irq_final": ("I", 332),
    "adc0_completion_count": ("I", 336),
    "adc1_completion_count": ("I", 340),
    "adc_completion_delta_cycles": ("I", 344),
    "adc_completion_expected_delta_cycles": ("I", 348),
    "adc_completion_tolerance_cycles": ("I", 352),
    "adc_completion_diagnostic_elapsed_cycles": ("I", 356),
    "adc_trigger_error_count": ("I", 360),
    "adc0_trigger_xbar_sel_configured": ("H", 364),
    "adc1_trigger_xbar_sel_configured": ("H", 366),
    "adc0_dma_major_loops": ("Q", 368),
    "adc1_dma_major_loops": ("Q", 376),
    "adc0_dma_results": ("Q", 384),
    "adc1_dma_results": ("Q", 392),
    "adc_paired_major_loops": ("Q", 400),
    "adc_buffers_completed": ("Q", 408),
    "adc_buffers_acquired": ("Q", 416),
    "adc_buffers_released": ("Q", 424),
    "adc_pairs_captured": ("Q", 432),
    "adc_pairs_delivered": ("Q", 440),
    "adc_pairs_framed": ("Q", 448),
    "adc_pairs_transmitted": ("Q", 456),
    "adc_raw_pairs_lost": ("Q", 464),
    "adc_stop_pairs_discarded": ("Q", 472),
    "adc_incomplete_conversions": ("Q", 480),
    "adc_overwritten_conversions": ("Q", 488),
    "adc_raw_ring_overruns": ("Q", 496),
    "adc_incomplete_buffers": ("Q", 504),
    "adc_raw_ready_depth": ("H", 512),
    "adc_raw_ready_high_water": ("H", 514),
    "adc_etc_error_events": ("I", 516),
    "adc_etc_error_flags": ("I", 520),
    "adc_dma_error_events": ("I", 524),
    "adc_completion_mismatches": ("I", 528),
    "adc_destination_mismatches": ("I", 532),
    "adc_schedule_exhaustions": ("I", 536),
    "adc_raw_invariant_errors": ("I", 540),
    "adc_stale_completions": ("I", 544),
    "adc_resource_conflicts": ("I", 548),
    "adc_start_errors": ("I", 552),
    "adc_stop_errors": ("I", 556),
    "adc_stale_interrupts": ("I", 560),
    "adc_packer_source_errors": ("I", 564),
    "adc_packer_pipeline_errors": ("I", 568),
    "adc_packer_chronology_errors": ("I", 572),
    "adc_frames_generated": ("Q", 576),
    "adc_items_generated": ("Q", 584),
    "adc_frames_framed_pipeline": ("Q", 592),
    "adc_items_framed_pipeline": ("Q", 600),
    "adc_items_emitted": ("Q", 608),
    "adc_frames_transmitted": ("Q", 616),
    "adc_items_transmitted_pipeline": ("Q", 624),
    "adc_frames_dropped": ("Q", 632),
    "gpio_frames_generated": ("Q", 640),
    "gpio_items_generated": ("Q", 648),
    "gpio_frames_framed_pipeline": ("Q", 656),
    "gpio_items_framed_pipeline": ("Q", 664),
    "gpio_items_emitted": ("Q", 672),
    "gpio_frames_transmitted": ("Q", 680),
    "gpio_items_transmitted_pipeline": ("Q", 688),
    "gpio_frames_dropped": ("Q", 696),
    "adc_payload_bytes_produced": ("Q", 704),
    "adc_payload_bytes_framed": ("Q", 712),
    "adc_payload_bytes_emitted": ("Q", 720),
    "adc_payload_bytes_transmitted": ("Q", 728),
    "adc_payload_bytes_dropped": ("Q", 736),
    "adc_framed_bytes_framed": ("Q", 744),
    "adc_framed_bytes_emitted": ("Q", 752),
    "adc_framed_bytes_transmitted": ("Q", 760),
    "gpio_payload_bytes_produced": ("Q", 768),
    "gpio_payload_bytes_framed": ("Q", 776),
    "gpio_payload_bytes_emitted": ("Q", 784),
    "gpio_payload_bytes_transmitted": ("Q", 792),
    "gpio_payload_bytes_dropped": ("Q", 800),
    "gpio_framed_bytes_framed": ("Q", 808),
    "gpio_framed_bytes_emitted": ("Q", 816),
    "gpio_framed_bytes_transmitted": ("Q", 824),
    "adc_packet_ready_depth": ("H", 832),
    "gpio_packet_ready_depth": ("H", 834),
    "adc_packet_transmit_depth": ("H", 836),
    "gpio_packet_transmit_depth": ("H", 838),
    "adc_packet_ready_high_water": ("H", 840),
    "gpio_packet_ready_high_water": ("H", 842),
    "adc_packet_transmit_high_water": ("H", 844),
    "gpio_packet_transmit_high_water": ("H", 846),
    "packet_ready_high_water": ("H", 848),
    "packet_transmit_high_water": ("H", 850),
    "packet_frames_promoted": ("Q", 852),
    "packet_fairness_deferrals": ("Q", 860),
    "packet_accounted_frame_skew": ("Q", 868),
    "data_payload_bytes_transmitted": ("Q", 876),
    "data_framed_bytes_transmitted": ("Q", 884),
    "packet_pool_exhaustions": ("I", 892),
    "packet_invalid_operations": ("I", 896),
    "packet_encoding_rejections": ("I", 900),
    "packet_ready_queue_rejections": ("I", 904),
    "packet_transmit_queue_rejections": ("I", 908),
    "commands_accepted": ("I", 912),
    "commands_rejected": ("I", 916),
    "bad_checksums": ("I", 920),
    "bad_lengths": ("I", 924),
    "bad_types": ("I", 928),
    "bad_versions": ("I", 932),
    "timeouts": ("I", 936),
    "partial_usb_writes": ("I", 940),
    "state_errors": ("I", 944),
    "usb_short_capacity_deferrals": ("I", 948),
    "usb_rx_stall_events": ("I", 952),
    "usb_tx_stall_events": ("I", 956),
    "usb_io_errors": ("I", 960),
    "usb_command_queue_depth": ("H", 964),
    "usb_response_queue_depth": ("H", 966),
    "usb_lower_priority_queue_depth": ("H", 968),
    "usb_command_queue_high_water": ("H", 970),
    "usb_response_queue_high_water": ("H", 972),
    "usb_active_frame_bytes_sent": ("H", 974),
    "packet_owned_depth": ("H", 976),
    "usb_active_frame_size": ("H", 978),
    "adc_cache_dma_discards": ("I", 980),
    "adc_cache_cpu_invalidations": ("I", 984),
    "gpio_cache_dma_discards": ("I", 988),
    "gpio_cache_cpu_invalidations": ("I", 992),
    "bad_flags": ("I", 996),
    "bad_payloads": ("I", 1000),
    "bad_request_ids": ("I", 1004),
    "responses_queued": ("I", 1008),
    "responses_completed": ("I", 1012),
    "response_queue_rejections": ("I", 1016),
    "response_reservations_abandoned": ("I", 1020),
    "packet_pressure_evictions": ("Q", 1024),
    "packet_capacity_drops_without_evictable_frame": ("Q", 1032),
    "adc_frames_evicted": ("Q", 1040),
    "adc_frames_evicted_after_promotion": ("Q", 1048),
    "gpio_frames_evicted": ("Q", 1056),
    "gpio_frames_evicted_after_promotion": ("Q", 1064),
    "adc_packet_filling_depth": ("H", 1072),
    "gpio_packet_filling_depth": ("H", 1074),
    "adc_frames_dropped_after_framing": ("Q", 1076),
    "adc_frames_dropped_after_promotion": ("Q", 1084),
    "gpio_frames_dropped_after_framing": ("Q", 1092),
    "gpio_frames_dropped_after_promotion": ("Q", 1100),
    "gpio_buffers_completed": ("Q", 1108),
    "gpio_buffers_acquired": ("Q", 1116),
    "gpio_buffers_released": ("Q", 1124),
    "gpio_samples_delivered": ("Q", 1132),
    "gpio_stop_samples_discarded": ("Q", 1140),
    "gpio_frames_produced": ("Q", 1148),
    "gpio_samples_produced": ("Q", 1156),
    "gpio_frames_packed": ("Q", 1164),
    "gpio_duplicate_samples_ignored": ("Q", 1172),
    "adc_frames_consumed": ("Q", 1180),
    "adc_pairs_consumed": ("Q", 1188),
    "adc_raw_gap_pairs": ("Q", 1196),
    "adc_raw_drop_pairs_projected": ("Q", 1204),
    "gpio_raw_drop_samples_projected": ("Q", 1212),
    "gpio_packer_drop_samples_projected": ("Q", 1220),
    "protocol_version": ("B", 1228),
    "aux_bank_mode": ("B", 1229),
    "rate_profile": ("B", 1230),
    "gpio_item_bytes": ("B", 1231),
    "adc_pair_rate_hz": ("I", 1232),
    "gpio_sample_rate_hz": ("I", 1236),
    "frame_coverage_ticks": ("I", 1240),
    "packet_retention_us_combined": ("I", 1244),
    "packet_retention_us_single_stream": ("I", 1248),
    "primary_gpio_raw_ready_depth": ("H", 1252),
    "aux_gpio_raw_ready_depth": ("H", 1254),
    "primary_gpio_raw_ready_high_water": ("H", 1256),
    "aux_gpio_raw_ready_high_water": ("H", 1258),
    "primary_gpio_dma_major_loops": ("Q", 1264),
    "aux_gpio_dma_major_loops": ("Q", 1272),
    "primary_gpio_samples_captured": ("Q", 1280),
    "aux_gpio_samples_captured": ("Q", 1288),
    "paired_gpio_dma_major_loops": ("Q", 1296),
    "paired_gpio_buffers_completed": ("Q", 1304),
    "paired_gpio_buffers_acquired": ("Q", 1312),
    "paired_gpio_buffers_released": ("Q", 1320),
    "paired_gpio_samples_captured": ("Q", 1328),
    "paired_gpio_samples_joined": ("Q", 1336),
    "paired_gpio_samples_delivered": ("Q", 1344),
    "paired_gpio_samples_lost": ("Q", 1352),
    "paired_gpio_raw_ring_overruns": ("Q", 1360),
    "paired_gpio_generation_skew_events": ("Q", 1368),
    "paired_gpio_generation_skew_samples": ("Q", 1376),
    "paired_gpio_canceled_generations": ("Q", 1384),
    "paired_gpio_cancellation_samples": ("Q", 1392),
    "paired_gpio_stop_tail_samples": ("Q", 1400),
    "paired_gpio_timestamp_mismatches": ("I", 1408),
    "paired_gpio_count_mismatches": ("I", 1412),
    "paired_gpio_destination_mismatches": ("I", 1416),
    "paired_gpio_schedule_exhaustions": ("I", 1420),
    "paired_gpio_stale_completions": ("I", 1424),
    "paired_gpio_cache_dma_discards": ("I", 1428),
    "paired_gpio_cache_cpu_invalidations": ("I", 1432),
    "paired_gpio_hardware_errors": ("I", 1436),
    "paired_gpio_invariant_errors": ("I", 1440),
    "paired_gpio_resource_conflicts": ("I", 1444),
    "paired_gpio_start_errors": ("I", 1448),
    "paired_gpio_stop_errors": ("I", 1452),
    "paired_gpio_stale_dma_completions": ("I", 1456),
    "primary_gpio_raw_ring_overruns": ("I", 1460),
    "aux_gpio_raw_ring_overruns": ("I", 1464),
    "primary_gpio_stale_completions": ("I", 1468),
    "aux_gpio_stale_completions": ("I", 1472),
}

CURRENT_STATUS_FIELDS = frozenset(
    {
        "device_state",
        "stream_mask",
        "source",
        "data_checksum_algorithm",
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
        "packet_owned_depth",
        "usb_active_frame_size",
        "adc_packet_filling_depth",
        "gpio_packet_filling_depth",
        "aux_bank_mode",
        "rate_profile",
        "gpio_item_bytes",
        "adc_pair_rate_hz",
        "gpio_sample_rate_hz",
        "frame_coverage_ticks",
        "packet_retention_us_combined",
        "packet_retention_us_single_stream",
        "primary_gpio_raw_ready_depth",
        "aux_gpio_raw_ready_depth",
    }
)


@dataclass(frozen=True)
class StatusSnapshot:
    values: dict[str, int]

    def __getattr__(self, name: str) -> int:
        try:
            return self.values[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def regressions_from(self, previous: StatusSnapshot) -> dict[str, tuple[int, int]]:
        return {
            name: (previous.values[name], value)
            for name, value in self.values.items()
            if name not in CURRENT_STATUS_FIELDS and value < previous.values[name]
        }


def decode_status(frame: Frame) -> StatusSnapshot:
    response_success(frame, GET_STATUS_RESPONSE)
    return StatusSnapshot(
        {
            name: int(struct.unpack_from("<" + code, frame.payload, offset)[0])
            for name, (code, offset) in STATUS_FIELDS.items()
        }
    )


ZERO_ERROR_FIELDS = (
    "parser_errors",
    "transport_errors",
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
    "adc_overwritten_conversions",
    "adc_raw_ring_overruns",
    "adc_etc_error_events",
    "adc_etc_error_flags",
    "adc_dma_error_events",
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
    "partial_usb_writes",
    "gpio_duplicate_samples_ignored",
    "adc_raw_gap_pairs",
    "adc_raw_drop_pairs_projected",
    "gpio_raw_drop_samples_projected",
    "gpio_packer_drop_samples_projected",
    "paired_gpio_raw_ring_overruns",
    "paired_gpio_generation_skew_events",
    "paired_gpio_generation_skew_samples",
    "paired_gpio_canceled_generations",
    "paired_gpio_cancellation_samples",
    "paired_gpio_timestamp_mismatches",
    "paired_gpio_count_mismatches",
    "paired_gpio_destination_mismatches",
    "paired_gpio_schedule_exhaustions",
    "paired_gpio_stale_completions",
    "paired_gpio_hardware_errors",
    "paired_gpio_invariant_errors",
    "paired_gpio_resource_conflicts",
    "paired_gpio_start_errors",
    "paired_gpio_stop_errors",
    "paired_gpio_stale_dma_completions",
    "primary_gpio_raw_ring_overruns",
    "aux_gpio_raw_ring_overruns",
    "primary_gpio_stale_completions",
    "aux_gpio_stale_completions",
)


def validate_status(
    status: StatusSnapshot,
    case: RunCase,
    profile: RateProfile,
    *,
    expected_checksum: int,
    expected_state: int,
    expected_generation: int,
    final: bool,
) -> None:
    layout = LAYOUTS[case.aux_mode]
    # STOP clears the applied configuration, not the completed run's counters.
    # Grade current metadata against IDLE defaults; reconcile counters below
    # against the original run layout/rate passed by the caller.
    reported_profile = PROFILES[0] if final else profile
    reported_mode = AUX_DISABLED if final else case.aux_mode
    expected_configuration = {
        "device_state": expected_state,
        "stream_mask": STREAM_NONE if final else case.stream_mask,
        "source": SOURCE_HARDWARE,
        "data_checksum_algorithm": DEFAULT_DATA_CHECKSUM
        if final
        else expected_checksum,
        "data_frame_bytes": MAX_FRAME_BYTES,
        "stats_generation": expected_generation,
        "protocol_version": PROTOCOL_VERSION,
        "aux_bank_mode": reported_mode,
        "rate_profile": reported_profile.value,
        "gpio_item_bytes": LAYOUTS[reported_mode].gpio_item_bytes,
        "adc_pair_rate_hz": reported_profile.adc_rate_hz,
        "gpio_sample_rate_hz": reported_profile.gpio_rate_hz,
        "frame_coverage_ticks": (
            reported_profile.input_coverage_ticks
            if reported_mode == AUX_INPUT
            else reported_profile.disabled_coverage_ticks
        ),
    }
    wrong = {
        name: {"expected": expected, "actual": status.values[name]}
        for name, expected in expected_configuration.items()
        if status.values[name] != expected
    }
    if wrong:
        emit_event("status_failure_snapshot", final=final, values=status.values)
        raise ProtocolFailure(
            "STATUS configuration echo is contradictory: "
            + json.dumps(wrong, sort_keys=True)
        )
    nonzero = {
        name: status.values[name]
        for name in ZERO_ERROR_FIELDS
        if status.values[name]
        and not (
            final
            and case.aux_mode == AUX_INPUT
            and name == "paired_gpio_canceled_generations"
            and status.values[name] <= 2
        )
    }
    if nonzero:
        raise ProtocolFailure(
            "STATUS reports loss/error counters: " + json.dumps(nonzero, sort_keys=True)
        )

    adc_enabled = bool(case.stream_mask & STREAM_ADC)
    if not adc_enabled and any(
        status.values[name]
        for name in (
            "adc_frames_emitted",
            "adc0_dma_major_loops",
            "adc1_dma_major_loops",
            "adc_pairs_captured",
            "adc_frames_generated",
            "adc_frames_transmitted",
        )
    ):
        raise ProtocolFailure("GPIO-only run reports active ADC counters")
    if adc_enabled:
        if (
            status.adc0_dma_results
            != status.adc0_dma_major_loops * layout.adc_items_per_frame
        ):
            raise ProtocolFailure("ADC0 results disagree with major loops")
        if (
            status.adc1_dma_results
            != status.adc1_dma_major_loops * layout.adc_items_per_frame
        ):
            raise ProtocolFailure("ADC1 results disagree with major loops")
        if abs(status.adc0_dma_major_loops - status.adc1_dma_major_loops) > 1:
            raise ProtocolFailure("ADC DMA channel skew exceeds one major loop")
        if status.adc_paired_major_loops != min(
            status.adc0_dma_major_loops, status.adc1_dma_major_loops
        ):
            raise ProtocolFailure("ADC paired major-loop barrier is inconsistent")
        if (
            not status.adc_buffers_completed
            >= status.adc_buffers_acquired
            >= status.adc_buffers_released
        ):
            raise ProtocolFailure("ADC buffer ownership stages are inconsistent")
        if status.adc_buffers_completed > status.adc_paired_major_loops:
            raise ProtocolFailure("ADC completed buffers exceed paired DMA loops")
        if (
            status.adc_pairs_delivered
            != status.adc_buffers_acquired * layout.adc_items_per_frame
        ):
            raise ProtocolFailure("ADC delivered pairs disagree with buffer leases")
        if not (
            status.adc_pairs_captured
            >= status.adc_pairs_delivered
            >= status.adc_pairs_framed
            >= status.adc_pairs_transmitted
        ):
            raise ProtocolFailure("ADC pair stages are inconsistent")

    if case.aux_mode == AUX_INPUT:
        if (
            abs(status.primary_gpio_dma_major_loops - status.aux_gpio_dma_major_loops)
            > 1
        ):
            raise ProtocolFailure("GPIO bank DMA major-loop skew exceeds one")
        if status.paired_gpio_dma_major_loops != min(
            status.primary_gpio_dma_major_loops, status.aux_gpio_dma_major_loops
        ):
            raise ProtocolFailure("paired GPIO major loops disagree with bank barrier")
        if (
            status.primary_gpio_samples_captured
            != status.primary_gpio_dma_major_loops * layout.gpio_items_per_frame
        ):
            raise ProtocolFailure("primary bank samples disagree with major loops")
        if (
            status.aux_gpio_samples_captured
            != status.aux_gpio_dma_major_loops * layout.gpio_items_per_frame
        ):
            raise ProtocolFailure("auxiliary bank samples disagree with major loops")
        if (
            not status.paired_gpio_buffers_completed
            >= status.paired_gpio_buffers_acquired
            >= status.paired_gpio_buffers_released
        ):
            raise ProtocolFailure("paired GPIO ownership stages are inconsistent")
        if (
            not status.paired_gpio_samples_captured
            >= status.paired_gpio_samples_joined
            >= status.paired_gpio_samples_delivered
        ):
            raise ProtocolFailure("paired GPIO sample stages are inconsistent")
        if status.paired_gpio_samples_lost != status.paired_gpio_stop_tail_samples:
            raise ProtocolFailure("paired GPIO loss is not entirely bounded STOP tail")
        if (
            status.gpio_dma_major_loops != status.paired_gpio_dma_major_loops
            or status.paired_gpio_buffers_completed > status.paired_gpio_dma_major_loops
        ):
            raise ProtocolFailure("legacy/paired GPIO major-loop counts disagree")
        if (
            status.paired_gpio_samples_joined
            != status.paired_gpio_buffers_completed * layout.gpio_items_per_frame
            or status.paired_gpio_samples_delivered
            != status.paired_gpio_buffers_acquired * layout.gpio_items_per_frame
        ):
            raise ProtocolFailure(
                "paired GPIO sample counts disagree with buffer leases"
            )
        if (
            status.paired_gpio_samples_captured
            != status.paired_gpio_samples_joined + status.paired_gpio_samples_lost
        ):
            raise ProtocolFailure(
                "paired GPIO captured/joined/lost conservation failed"
            )
        if not final and status.paired_gpio_stop_tail_samples:
            raise ProtocolFailure("running STATUS reports a STOP tail")
        if (
            final
            and not 0
            <= status.paired_gpio_stop_tail_samples
            <= layout.gpio_items_per_frame
        ):
            raise ProtocolFailure("paired GPIO STOP tail exceeds one logical frame")
    else:
        extension_activity = (
            status.primary_gpio_dma_major_loops
            + status.aux_gpio_dma_major_loops
            + status.paired_gpio_dma_major_loops
            + status.paired_gpio_samples_captured
        )
        if extension_activity:
            raise ProtocolFailure(
                "eight-input control reports auxiliary pipeline activity"
            )

    if not (
        status.gpio_samples_captured
        >= status.gpio_samples_packed
        >= status.gpio_samples_framed
        >= status.gpio_samples_transmitted
    ):
        raise ProtocolFailure(
            "logical GPIO capture/pack/frame/transmit stages are inconsistent"
        )
    if (
        status.gpio_samples_framed % layout.gpio_items_per_frame
        or status.gpio_samples_transmitted % layout.gpio_items_per_frame
    ):
        raise ProtocolFailure(
            "logical GPIO framed/transmitted samples are not frame aligned"
        )
    if (
        status.gpio_samples_framed != status.gpio_items_framed_pipeline
        or status.gpio_samples_transmitted != status.gpio_items_transmitted_pipeline
        or status.gpio_samples_packed
        != status.gpio_frames_packed * layout.gpio_items_per_frame
    ):
        raise ProtocolFailure("legacy/pipeline GPIO conservation failed")
    if adc_enabled and (
        status.adc_pairs_framed != status.adc_items_framed_pipeline
        or status.adc_pairs_transmitted != status.adc_items_transmitted_pipeline
    ):
        raise ProtocolFailure("legacy/pipeline ADC conservation failed")

    for prefix, enabled, items, item_bytes in (
        ("adc", adc_enabled, layout.adc_items_per_frame, ADC_BYTES_PER_PAIR),
        ("gpio", True, layout.gpio_items_per_frame, layout.gpio_item_bytes),
    ):
        generated = status.values[f"{prefix}_frames_generated"]
        framed = status.values[f"{prefix}_frames_framed_pipeline"]
        emitted = status.values[f"{prefix}_frames_emitted"]
        transmitted = status.values[f"{prefix}_frames_transmitted"]
        if not enabled and any((generated, framed, emitted, transmitted)):
            raise ProtocolFailure(f"disabled {prefix} stream has frame activity")
        if not generated >= framed >= emitted >= transmitted:
            raise ProtocolFailure(f"{prefix} frame stages are inconsistent")
        exact = {
            f"{prefix}_items_generated": generated * items,
            f"{prefix}_items_framed_pipeline": framed * items,
            f"{prefix}_items_emitted": emitted * items,
            f"{prefix}_items_transmitted_pipeline": transmitted * items,
            f"{prefix}_payload_bytes_produced": generated * items * item_bytes,
            f"{prefix}_payload_bytes_framed": framed * items * item_bytes,
            f"{prefix}_payload_bytes_emitted": emitted * items * item_bytes,
            f"{prefix}_payload_bytes_transmitted": transmitted * items * item_bytes,
            f"{prefix}_framed_bytes_framed": framed
            * (
                layout.adc_total_frame_bytes
                if prefix == "adc"
                else layout.gpio_total_frame_bytes
            ),
            f"{prefix}_framed_bytes_emitted": emitted
            * (
                layout.adc_total_frame_bytes
                if prefix == "adc"
                else layout.gpio_total_frame_bytes
            ),
            f"{prefix}_framed_bytes_transmitted": transmitted
            * (
                layout.adc_total_frame_bytes
                if prefix == "adc"
                else layout.gpio_total_frame_bytes
            ),
        }
        for name, expected in exact.items():
            if status.values[name] != expected:
                raise ProtocolFailure(
                    f"STATUS {name}={status.values[name]}; expected {expected}"
                )
    if (
        status.data_payload_bytes_transmitted
        != status.adc_payload_bytes_transmitted + status.gpio_payload_bytes_transmitted
    ):
        raise ProtocolFailure("combined payload-byte conservation failed")
    if (
        status.data_framed_bytes_transmitted
        != status.adc_framed_bytes_transmitted + status.gpio_framed_bytes_transmitted
    ):
        raise ProtocolFailure("combined framed-byte conservation failed")
    # This is the absolute difference between stream frame counts, not an
    # error counter. With ADC disabled it legitimately grows with every GPIO
    # frame; fairness bounds apply only when both streams are selected.
    if adc_enabled and status.packet_accounted_frame_skew > 1:
        raise ProtocolFailure("packet scheduler accounted skew exceeds bound")

    depth_limits = {
        "gpio_raw_ready_depth": GPIO_RAW_RING_DEPTH,
        "gpio_raw_ready_high_water": GPIO_RAW_RING_DEPTH,
        "gpio_packed_ready_depth": GPIO_PACKED_RING_DEPTH,
        "gpio_packed_ready_high_water": GPIO_PACKED_RING_DEPTH,
        "adc_raw_ready_depth": ADC_DMA_RING_DEPTH,
        "adc_raw_ready_high_water": ADC_DMA_RING_DEPTH,
        "packet_ready_depth": PACKET_READY_QUEUE_CAPACITY,
        "packet_transmit_depth": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "packet_ready_high_water": PACKET_READY_QUEUE_CAPACITY,
        "packet_transmit_high_water": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "adc_packet_ready_depth": PACKET_READY_QUEUE_CAPACITY,
        "gpio_packet_ready_depth": PACKET_READY_QUEUE_CAPACITY,
        "adc_packet_transmit_depth": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "gpio_packet_transmit_depth": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "adc_packet_ready_high_water": PACKET_READY_QUEUE_CAPACITY,
        "gpio_packet_ready_high_water": PACKET_READY_QUEUE_CAPACITY,
        "adc_packet_transmit_high_water": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "gpio_packet_transmit_high_water": PACKET_TRANSMIT_QUEUE_CAPACITY,
        "packet_owned_depth": PACKET_BUFFER_COUNT,
        "packet_owned_high_water": PACKET_BUFFER_COUNT,
        "usb_command_queue_depth": COMMAND_QUEUE_CAPACITY,
        "usb_response_queue_depth": RESPONSE_QUEUE_CAPACITY,
        "usb_command_queue_high_water": COMMAND_QUEUE_CAPACITY,
        "usb_response_queue_high_water": RESPONSE_QUEUE_CAPACITY,
        "primary_gpio_raw_ready_depth": GPIO_RAW_RING_DEPTH,
        "aux_gpio_raw_ready_depth": GPIO_RAW_RING_DEPTH,
        "primary_gpio_raw_ready_high_water": GPIO_RAW_RING_DEPTH,
        "aux_gpio_raw_ready_high_water": GPIO_RAW_RING_DEPTH,
    }
    for name, limit in depth_limits.items():
        if not 0 <= status.values[name] <= limit:
            raise ProtocolFailure(f"STATUS {name} exceeds {limit}")
    if (
        status.gpio_raw_ready_depth > status.gpio_raw_ready_high_water
        or status.gpio_packed_ready_depth > status.gpio_packed_ready_high_water
        or status.adc_raw_ready_depth > status.adc_raw_ready_high_water
    ):
        raise ProtocolFailure("current queue depth exceeds its high-water mark")
    if (
        status.packet_ready_depth
        != status.adc_packet_ready_depth + status.gpio_packet_ready_depth
        or status.packet_transmit_depth
        != status.adc_packet_transmit_depth + status.gpio_packet_transmit_depth
    ):
        raise ProtocolFailure("aggregate/per-stream packet depths disagree")
    if status.packet_ready_depth + status.packet_transmit_depth > PACKET_BUFFER_COUNT:
        raise ProtocolFailure("packet queue ownership exceeds the fixed pool")
    if status.usb_active_frame_bytes_sent >= MAX_FRAME_BYTES:
        raise ProtocolFailure("USB active-frame offset exceeds one frame")
    if (
        not 0
        <= status.gpio_processing_cpu_basis_points
        <= MAX_GPIO_PROCESSING_CPU_BASIS_POINTS
    ):
        raise ProtocolFailure("GPIO processing CPU utilization exceeds bound")
    coverage = expected_configuration["frame_coverage_ticks"]
    expected_combined_retention = 100 * int(coverage) * 1_000_000 // TIMESTAMP_HZ
    if status.packet_retention_us_combined != expected_combined_retention:
        raise ProtocolFailure("combined packet retention is contradictory")
    if status.packet_retention_us_single_stream != 2 * expected_combined_retention:
        raise ProtocolFailure("single-stream packet retention is contradictory")


@dataclass
class StreamTotals:
    frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0
    expected_sequence: int = 0
    expected_ticks: int = 0


class AcquisitionValidator:
    """Validate frame content and continuity while retaining only aggregates."""

    def __init__(
        self,
        run_id: int,
        checksum_algorithm: int,
        case: RunCase,
        profile: RateProfile,
        fixture: FixtureDeclaration | None,
    ) -> None:
        self.run_id = run_id
        self.checksum_algorithm = checksum_algorithm
        self.case = case
        self.profile = profile
        self.layout = LAYOUTS[case.aux_mode]
        self.fixture = fixture
        self.adc = StreamTotals()
        self.gpio = StreamTotals()
        self.maximum_frame_skew = 0
        self.maximum_receive_gap_seconds = 0.0
        self.primary_and = 0xFF
        self.primary_or = 0
        self.aux_and = 0xFF
        self.aux_or = 0
        self.primary_transitions = 0
        self.aux_transitions = 0
        self._last_gpio: int | None = None
        self._last_receive: float | None = None

    def accept(self, frame: Frame) -> None:
        now = time.monotonic()
        if self._last_receive is not None:
            self.maximum_receive_gap_seconds = max(
                self.maximum_receive_gap_seconds, now - self._last_receive
            )
        self._last_receive = now
        if frame.run_id != self.run_id:
            raise ProtocolFailure(f"data run ID {frame.run_id}; expected {self.run_id}")
        if frame.checksum_algorithm != self.checksum_algorithm:
            raise ProtocolFailure("data checksum changed during run")
        if frame.flags & (FLAG_SYNTHETIC | FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE):
            raise ProtocolFailure(
                f"physical data carries invalid flags 0x{frame.flags:04x}"
            )
        if frame.kind == ADC_DATA:
            if not self.case.stream_mask & STREAM_ADC:
                raise ProtocolFailure("GPIO-only run received ADC data")
            self._accept_adc(frame)
        elif frame.kind == GPIO_DATA:
            self._accept_gpio(frame)
        else:
            raise ProtocolFailure(f"unexpected data kind 0x{frame.kind:02x}")
        if self.case.stream_mask == STREAM_BOTH:
            self.maximum_frame_skew = max(
                self.maximum_frame_skew, abs(self.adc.frames - self.gpio.frames)
            )
            if self.maximum_frame_skew > 1:
                raise ProtocolFailure("combined host frame skew exceeds one")

    def _continuity(
        self, frame: Frame, totals: StreamTotals, period: int, coverage: int, label: str
    ) -> None:
        expected_flags = FLAG_EPOCH_START if totals.frames == 0 else 0
        if (
            frame.flags != expected_flags
            or frame.sequence != totals.expected_sequence
            or frame.first_sample_ticks != totals.expected_ticks
        ):
            raise ProtocolFailure(
                f"{label} continuity expected flags/seq/ticks "
                f"{expected_flags}/{totals.expected_sequence}/{totals.expected_ticks}, got "
                f"{frame.flags}/{frame.sequence}/{frame.first_sample_ticks}"
            )
        if frame.first_sample_ticks % period:
            raise ProtocolFailure(f"{label} timestamp is not exact-period aligned")
        totals.expected_sequence = (totals.expected_sequence + 1) & 0xFFFFFFFF
        totals.expected_ticks = (totals.expected_ticks + coverage) & 0xFFFFFFFFFFFFFFFF

    @staticmethod
    def _advance(totals: StreamTotals, frame: Frame, total_bytes: int) -> None:
        totals.frames += 1
        totals.items += frame.item_count
        totals.payload_bytes += len(frame.payload)
        totals.framed_bytes += total_bytes

    def _accept_adc(self, frame: Frame) -> None:
        coverage = (
            self.profile.input_coverage_ticks
            if self.case.aux_mode == AUX_INPUT
            else self.profile.disabled_coverage_ticks
        )
        self._continuity(
            frame, self.adc, self.profile.adc_period_ticks, coverage, "ADC"
        )
        if (
            frame.item_count != self.layout.adc_items_per_frame
            or len(frame.payload) != self.layout.adc_payload_bytes
        ):
            raise ProtocolFailure("ADC frame shape differs from active layout")
        if max(frame.payload[1::2], default=0) > ((1 << ADC_RESOLUTION_BITS) - 1) >> 8:
            raise ProtocolFailure("ADC frame contains an out-of-range code")
        self._advance(self.adc, frame, self.layout.adc_total_frame_bytes)

    def _accept_gpio(self, frame: Frame) -> None:
        coverage = (
            self.profile.input_coverage_ticks
            if self.case.aux_mode == AUX_INPUT
            else self.profile.disabled_coverage_ticks
        )
        self._continuity(
            frame, self.gpio, self.profile.gpio_period_ticks, coverage, "GPIO"
        )
        if (
            frame.item_count != self.layout.gpio_items_per_frame
            or len(frame.payload) != self.layout.gpio_payload_bytes
        ):
            raise ProtocolFailure("GPIO frame shape differs from active layout")
        inspect_all = self.fixture is not None
        if self.case.aux_mode == AUX_DISABLED:
            byte_samples = frame.payload if inspect_all else frame.payload[:1]
            for value in byte_samples:
                self.primary_and &= value
                self.primary_or |= value
                if self._last_gpio is not None:
                    self.primary_transitions |= self._last_gpio ^ value
                self._last_gpio = value
        else:
            word_samples: Iterator[int]
            if inspect_all:
                word_samples = (
                    fields[0] for fields in struct.iter_unpack("<H", frame.payload)
                )
            else:
                word_samples = iter((struct.unpack_from("<H", frame.payload)[0],))
            for value in word_samples:
                primary = value & 0xFF
                auxiliary = value >> 8
                self.primary_and &= primary
                self.primary_or |= primary
                self.aux_and &= auxiliary
                self.aux_or |= auxiliary
                if self._last_gpio is not None:
                    changed = self._last_gpio ^ value
                    self.primary_transitions |= changed & 0xFF
                    self.aux_transitions |= changed >> 8
                self._last_gpio = value
        self._advance(self.gpio, frame, self.layout.gpio_total_frame_bytes)


class MemoryTracker:
    def __init__(self) -> None:
        self.start = current_rss_bytes()
        self.peak = self.start

    def sample(self) -> None:
        self.peak = max(self.peak, current_rss_bytes())

    @property
    def growth(self) -> int:
        return max(0, self.peak - self.start)


def current_rss_bytes() -> int:
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return peak_rss_bytes()


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        raise ProtocolFailure("latency percentile has no samples")
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


@dataclass(frozen=True)
class AcceptanceResult:
    evidence: Evidence
    metrics: dict[str, object]
    stimulus_grade: str


def _check_stop_tails(status: StatusSnapshot, case: RunCase, *, final: bool) -> None:
    layout = LAYOUTS[case.aux_mode]
    if not final:
        fields = (
            status.adc_items_dropped,
            status.gpio_items_dropped,
            status.adc_raw_pairs_lost,
            status.adc_stop_pairs_discarded,
            status.gpio_raw_samples_lost,
            status.gpio_stop_samples_discarded,
            status.paired_gpio_stop_tail_samples,
        )
        if any(fields):
            raise ProtocolFailure("running STATUS reports STOP-tail loss")
        return
    if case.stream_mask & STREAM_ADC:
        adc_tail = status.adc_stop_pairs_discarded
        if not (
            0 <= adc_tail < 2 * layout.adc_items_per_frame
            and status.adc_raw_pairs_lost == adc_tail
            and status.adc_items_dropped == adc_tail
            and 0 <= status.adc_incomplete_buffers <= 2
            and 0 <= status.adc_incomplete_conversions <= adc_tail
            and 0 <= status.adc_completion_mismatches <= status.adc_incomplete_buffers
        ):
            raise ProtocolFailure("ADC STOP-tail accounting is inconsistent")
    gpio_tail = status.gpio_stop_samples_discarded
    gpio_tail_limit = (
        layout.gpio_items_per_frame
        if case.aux_mode == AUX_INPUT
        else layout.gpio_items_per_frame - 1
    )
    if not (
        0 <= gpio_tail <= gpio_tail_limit
        and status.gpio_raw_samples_lost == gpio_tail
        and status.gpio_items_dropped == gpio_tail
    ):
        raise ProtocolFailure("GPIO STOP-tail accounting is inconsistent")
    if case.aux_mode == AUX_INPUT and status.paired_gpio_stop_tail_samples != gpio_tail:
        raise ProtocolFailure("paired and logical GPIO STOP tails disagree")


def _final_reconciliation(
    evidence: Evidence,
    status: StatusSnapshot,
    validator: AcquisitionValidator,
    case: RunCase,
    fixture: FixtureDeclaration | None,
) -> None:
    evidence.equal("final.state", STATE_IDLE, status.device_state)
    evidence.equal(
        "final.gpio_frames", validator.gpio.frames, status.gpio_frames_transmitted
    )
    evidence.equal(
        "final.gpio_items", validator.gpio.items, status.gpio_items_transmitted_pipeline
    )
    evidence.equal(
        "final.gpio_payload_bytes",
        validator.gpio.payload_bytes,
        status.gpio_payload_bytes_transmitted,
    )
    evidence.equal(
        "final.gpio_framed_bytes",
        validator.gpio.framed_bytes,
        status.gpio_framed_bytes_transmitted,
    )
    if case.stream_mask & STREAM_ADC:
        evidence.equal(
            "final.adc_frames", validator.adc.frames, status.adc_frames_transmitted
        )
        evidence.equal(
            "final.adc_items",
            validator.adc.items,
            status.adc_items_transmitted_pipeline,
        )
        evidence.equal(
            "final.adc_payload_bytes",
            validator.adc.payload_bytes,
            status.adc_payload_bytes_transmitted,
        )
        evidence.equal(
            "final.adc_framed_bytes",
            validator.adc.framed_bytes,
            status.adc_framed_bytes_transmitted,
        )
    else:
        evidence.equal("final.adc_frames", 0, validator.adc.frames)
    if case.aux_mode == AUX_INPUT:
        evidence.equal(
            "final.joined_samples",
            status.gpio_samples_packed,
            status.paired_gpio_samples_delivered,
        )
        bank_delta = abs(
            status.primary_gpio_samples_captured - status.aux_gpio_samples_captured
        )
        evidence.check(
            "final.bank_capture_skew",
            f"<= {LAYOUTS[AUX_INPUT].gpio_items_per_frame} samples",
            bank_delta,
            bank_delta <= LAYOUTS[AUX_INPUT].gpio_items_per_frame,
        )
        evidence.equal(
            "final.joined_logical_capture",
            status.gpio_samples_captured,
            status.paired_gpio_samples_captured,
        )
    if fixture is not None and case.aux_mode == AUX_INPUT:
        evidence.check(
            "stimulus.stream_aux_transition_mask",
            f"contains 0x{fixture.required_transition_mask:02x}",
            f"0x{validator.aux_transitions:02x}",
            validator.aux_transitions & fixture.required_transition_mask
            == fixture.required_transition_mask,
        )


def run_acceptance(
    port: SerialPort,
    *,
    case: RunCase,
    profile: RateProfile,
    capture_seconds: float,
    warmup_seconds: float,
    status_interval_seconds: float,
    checksum_algorithm: int,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
    fixture: FixtureDeclaration | None,
    run_diagnostic: bool = True,
) -> AcceptanceResult:
    if not 0 < capture_seconds <= MAX_CAPTURE_SECONDS:
        raise ValueError(f"capture_seconds must be in (0, {MAX_CAPTURE_SECONDS}]")
    if not 0 <= warmup_seconds <= MAX_WARMUP_SECONDS:
        raise ValueError(f"warmup_seconds must be in [0, {MAX_WARMUP_SECONDS}]")
    if (
        not math.isfinite(status_interval_seconds)
        or status_interval_seconds < MIN_STATUS_INTERVAL_SECONDS
    ):
        raise ValueError("status interval is too short or not finite")
    projected = (
        math.ceil((capture_seconds + warmup_seconds) / status_interval_seconds) + 2
    )
    if projected > MAX_STATUS_SAMPLES:
        raise ValueError(
            f"capture requests more than {MAX_STATUS_SAMPLES} STATUS samples"
        )
    if case.aux_mode == AUX_DISABLED and fixture is not None:
        raise ValueError("an auxiliary fixture declaration requires an INPUT run case")
    if not run_diagnostic and fixture is not None:
        raise ValueError("fixture grading requires the diagnostic")

    evidence = Evidence()
    link = SerialLink(port)
    validator: AcquisitionValidator | None = None
    completed = False
    metrics: dict[str, object] = {}
    stimulus_grade = "NOT_RUN"
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        synchronized = synchronize(link)
        if _info_int(synchronized, "device_state") != STATE_IDLE:
            cleanup, _ = link.exchange(STOP_REQUEST)
            response_success(cleanup, STOP_RESPONSE)
            synchronized = synchronize(link)
        evidence.equal(
            "identity.initial_idle", STATE_IDLE, synchronized["device_state"]
        )
        grade_static_info(
            evidence,
            synchronized,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
        diagnostic_mode = _info_int(synchronized, "gpio_diagnostic_mode")
        if fixture is None and diagnostic_mode != 0:
            raise ProtocolFailure(
                "undeclared fixture stimulus mode will not be exercised"
            )
        if fixture is not None and diagnostic_mode != 2:
            raise ProtocolFailure(
                "authorized fixture declaration requires FIXTURE_STIMULUS mode"
            )
        if evidence.failures:
            raise ProtocolFailure("static identity/resource grading failed")

        diagnostic_latency = 0.0
        if run_diagnostic:
            diagnostic_frame, diagnostic_latency = link.exchange(
                GPIO_CAPTURE_DIAGNOSTIC_REQUEST,
                timeout=DIAGNOSTIC_DEADLINE_SECONDS,
            )
            stimulus_grade = grade_capture_diagnostic(
                evidence,
                decode_capture_diagnostic(diagnostic_frame),
                fixture,
            )
            if evidence.failures:
                raise ProtocolFailure("IDLE auxiliary diagnostic grading failed")
        else:
            emit_event("diagnostic_not_run", reason="independent streaming experiment")

        reset_frame, _ = link.exchange(RESET_STATS_REQUEST)
        response_success(reset_frame, RESET_STATS_RESPONSE)
        reset_generation = _u32(reset_frame.payload, 4)
        if reset_generation == 0:
            raise ProtocolFailure("RESET_STATS returned generation zero")

        requested = CONFIGURATION.pack(
            case.stream_mask,
            SOURCE_HARDWARE,
            checksum_algorithm,
            case.aux_mode,
            MAX_FRAME_BYTES,
            profile.adc_rate_hz,
            profile.gpio_rate_hz,
        )
        configured_frame, configure_latency = link.exchange(
            CONFIGURE_REQUEST, requested
        )
        evidence.equal(
            "configure.echo",
            CONFIGURATION.unpack(requested),
            decode_configuration(configured_frame, CONFIGURE_RESPONSE),
        )
        configured_status_frame, configured_status_latency = link.exchange(
            GET_STATUS_REQUEST
        )
        configured_status = decode_status(configured_status_frame)
        validate_status(
            configured_status,
            case,
            profile,
            expected_checksum=checksum_algorithm,
            expected_state=STATE_CONFIGURED,
            expected_generation=reset_generation,
            final=False,
        )
        _check_stop_tails(configured_status, case, final=False)
        configured_info_frame, info_latency = link.exchange(INFO_REQUEST)
        configured_info = decode_info(configured_info_frame)
        evidence.equal(
            "configure.stable_identity",
            stable_identity(synchronized),
            stable_identity(configured_info),
        )
        grade_active_info(
            evidence,
            configured_info,
            case,
            profile,
            expected_checksum=checksum_algorithm,
            expected_state=STATE_CONFIGURED,
        )
        if evidence.failures:
            raise ProtocolFailure("configured echo/metadata grading failed")

        deferred: list[Frame] = []
        deferred_limit = (
            math.ceil(
                SERIAL_READ_BYTES
                / min(layout.adc_total_frame_bytes for layout in LAYOUTS.values())
            )
            + 1
        )

        def collect_start(frame: Frame) -> None:
            if len(deferred) >= deferred_limit:
                raise ProtocolFailure("START boundary data exceeds bounded deferral")
            deferred.append(frame)

        start_frame, start_latency = link.exchange(START_REQUEST, on_data=collect_start)
        evidence.equal(
            "start.echo",
            CONFIGURATION.unpack(requested),
            decode_configuration(start_frame, START_RESPONSE),
        )
        evidence.check(
            "start.run_id",
            "nonzero uint32",
            start_frame.run_id,
            1 <= start_frame.run_id <= 0xFFFFFFFF,
        )
        expected_generation = (reset_generation + 1) & 0xFFFFFFFF or 1
        validator = AcquisitionValidator(
            start_frame.run_id, checksum_algorithm, case, profile, fixture
        )
        for frame in deferred:
            validator.accept(frame)
        deferred.clear()

        memory = MemoryTracker()
        status_latencies: list[float] = []
        all_latencies = [
            diagnostic_latency,
            configure_latency,
            configured_status_latency,
            info_latency,
            start_latency,
        ]
        status_count = 0
        previous: StatusSnapshot | None = None
        active_start = time.monotonic()
        timed_start: float | None = None
        timed_adc_items = 0
        timed_gpio_items = 0
        next_status = active_start
        while True:
            now = time.monotonic()
            if timed_start is None and now >= active_start + warmup_seconds:
                timed_start = now
                timed_adc_items = validator.adc.items
                timed_gpio_items = validator.gpio.items
                emit_event(
                    "warmup_complete",
                    adc_items=timed_adc_items,
                    gpio_items=timed_gpio_items,
                )
            if timed_start is not None and now >= timed_start + capture_seconds:
                break
            if now >= next_status:
                status_frame, latency = link.exchange(
                    GET_STATUS_REQUEST, on_data=validator.accept
                )
                status = decode_status(status_frame)
                if status_frame.run_id != validator.run_id:
                    raise ProtocolFailure("running STATUS run ID changed")
                validate_status(
                    status,
                    case,
                    profile,
                    expected_checksum=checksum_algorithm,
                    expected_state=STATE_RUNNING,
                    expected_generation=expected_generation,
                    final=False,
                )
                _check_stop_tails(status, case, final=False)
                if previous is not None:
                    regressions = status.regressions_from(previous)
                    if regressions:
                        raise ProtocolFailure(
                            "STATUS counters regressed: "
                            + json.dumps(regressions, sort_keys=True)
                        )
                previous = status
                status_latencies.append(latency)
                all_latencies.append(latency)
                status_count += 1
                memory.sample()
                next_status += status_interval_seconds
                while next_status <= time.monotonic():
                    next_status += status_interval_seconds
            else:
                link.pump_once(validator.accept)
        if timed_start is None:
            raise ProtocolFailure("timed acquisition never started")
        elapsed = time.monotonic() - timed_start
        measured_adc_items = validator.adc.items - timed_adc_items
        measured_gpio_items = validator.gpio.items - timed_gpio_items
        while status_count < 2:
            status_frame, latency = link.exchange(
                GET_STATUS_REQUEST, on_data=validator.accept
            )
            status = decode_status(status_frame)
            if status_frame.run_id != validator.run_id:
                raise ProtocolFailure("running STATUS run ID changed")
            validate_status(
                status,
                case,
                profile,
                expected_checksum=checksum_algorithm,
                expected_state=STATE_RUNNING,
                expected_generation=expected_generation,
                final=False,
            )
            _check_stop_tails(status, case, final=False)
            if previous is not None:
                regressions = status.regressions_from(previous)
                if regressions:
                    raise ProtocolFailure(
                        "STATUS counters regressed: "
                        + json.dumps(regressions, sort_keys=True)
                    )
            previous = status
            status_latencies.append(latency)
            all_latencies.append(latency)
            status_count += 1
            memory.sample()

        stop_frame, stop_latency = link.exchange(STOP_REQUEST, on_data=validator.accept)
        response_success(stop_frame, STOP_RESPONSE)
        evidence.equal("stop.state", STATE_IDLE, stop_frame.payload[4])
        evidence.equal("stop.run_id", validator.run_id, stop_frame.run_id)
        link.drain_until_quiet(validator.accept)
        final_frame, final_latency = link.exchange(
            GET_STATUS_REQUEST, on_data=validator.accept
        )
        final_status = decode_status(final_frame)
        evidence.equal("final.status_run_id", validator.run_id, final_frame.run_id)
        validate_status(
            final_status,
            case,
            profile,
            expected_checksum=checksum_algorithm,
            expected_state=STATE_IDLE,
            expected_generation=expected_generation,
            final=True,
        )
        _check_stop_tails(final_status, case, final=True)
        if previous is not None:
            regressions = final_status.regressions_from(previous)
            if regressions:
                raise ProtocolFailure(
                    "final STATUS counters regressed: "
                    + json.dumps(regressions, sort_keys=True)
                )
        _final_reconciliation(evidence, final_status, validator, case, fixture)

        all_latencies.extend((stop_latency, final_latency))
        evidence.check(
            "latency.status_samples", ">= 2", status_count, status_count >= 2
        )
        evidence.check(
            "latency.status_p99_seconds",
            f"<= {STATUS_P99_LIMIT_SECONDS}",
            percentile(status_latencies, 0.99),
            percentile(status_latencies, 0.99) <= STATUS_P99_LIMIT_SECONDS,
        )
        evidence.check(
            "latency.command_max_seconds",
            f"<= {STATUS_MAXIMUM_LIMIT_SECONDS}",
            max(all_latencies),
            max(all_latencies) <= STATUS_MAXIMUM_LIMIT_SECONDS,
        )
        evidence.check(
            "memory.rss_growth_bytes",
            f"<= {MAX_RSS_GROWTH_BYTES}",
            memory.growth,
            memory.growth <= MAX_RSS_GROWTH_BYTES,
        )
        gpio_rate = measured_gpio_items / elapsed
        evidence.check(
            "rate.gpio_hz",
            f"{profile.gpio_rate_hz} +/- 1%",
            gpio_rate,
            abs(gpio_rate - profile.gpio_rate_hz) / profile.gpio_rate_hz
            <= RATE_TOLERANCE_FRACTION,
        )
        adc_rate: float | None = None
        if case.stream_mask & STREAM_ADC:
            adc_rate = measured_adc_items / elapsed
            evidence.check(
                "rate.adc_hz",
                f"{profile.adc_rate_hz} +/- 1%",
                adc_rate,
                abs(adc_rate - profile.adc_rate_hz) / profile.adc_rate_hz
                <= RATE_TOLERANCE_FRACTION,
            )
            evidence.check(
                "rate.gpio_to_adc_ratio",
                "4 +/- 1%",
                gpio_rate / adc_rate,
                abs(gpio_rate / adc_rate - 4.0) <= 0.04,
            )
        evidence.equal("host.parser_errors", 0, link.parser.errors)
        evidence.equal("host.stale_responses", 0, link.stale_responses)
        evidence.equal("host.discarded_run_data", 0, link.discarded_data_frames)
        metrics = {
            "adc_frames": validator.adc.frames,
            "adc_rate_hz": adc_rate,
            "capture_seconds": elapsed,
            "firmware_processing_cpu_basis_points": final_status.gpio_processing_cpu_basis_points,
            "gpio_frames": validator.gpio.frames,
            "gpio_rate_hz": gpio_rate,
            "host_peak_rss_growth_bytes": memory.growth,
            "maximum_frame_skew": validator.maximum_frame_skew,
            "maximum_receive_gap_seconds": validator.maximum_receive_gap_seconds,
            "packet_ready_high_water": final_status.packet_ready_high_water,
            "packet_transmit_high_water": final_status.packet_transmit_high_water,
            "paired_generation_skew_events": final_status.paired_gpio_generation_skew_events,
            "primary_bank_samples_captured": final_status.primary_gpio_samples_captured,
            "aux_bank_samples_captured": final_status.aux_gpio_samples_captured,
            "paired_samples_joined": final_status.paired_gpio_samples_joined,
            "paired_samples_transmitted": final_status.gpio_samples_transmitted,
            "status_count": status_count,
            "status_p99_seconds": percentile(status_latencies, 0.99),
            "stop_tail_adc_items": final_status.adc_stop_pairs_discarded,
            "stop_tail_gpio_items": final_status.gpio_stop_samples_discarded,
        }
        emit_event(
            "final_counters",
            adc_frames_transmitted=final_status.adc_frames_transmitted,
            aux_bank_samples_captured=final_status.aux_gpio_samples_captured,
            gpio_frames_transmitted=final_status.gpio_frames_transmitted,
            paired_samples_joined=final_status.paired_gpio_samples_joined,
            primary_bank_samples_captured=final_status.primary_gpio_samples_captured,
        )
        completed = not evidence.failures
    except Exception as error:  # noqa: BLE001 - remote evidence must retain diagnosis
        evidence.failures.append(f"{type(error).__name__}: {error}")
        emit_event("fatal", error=evidence.failures[-1])
        try:
            failure_frame, _ = link.exchange(
                GET_STATUS_REQUEST, on_data=lambda _frame: None
            )
            emit_event("failure_status", values=decode_status(failure_frame).values)
        except Exception as status_error:  # noqa: BLE001 - cleanup must still run
            emit_event("failure_status_unavailable", error=str(status_error))
    finally:
        if not completed:
            try:
                cleanup, _ = link.exchange(STOP_REQUEST, on_data=lambda _frame: None)
                emit_event(
                    "cleanup_stop",
                    state=cleanup.payload[4] if len(cleanup.payload) > 4 else None,
                )
            except Exception as cleanup_error:  # noqa: BLE001 - best-effort safety cleanup
                emit_event(
                    "cleanup_stop_failed",
                    error=f"{type(cleanup_error).__name__}: {cleanup_error}",
                )
    return AcceptanceResult(evidence, metrics, stimulus_grade)


def _positive_float_environment(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
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
        raise ValueError(f"{name} must be numeric") from error
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


def _checksum_environment() -> int:
    raw = os.environ.get("AUX_INPUT_CHECKSUM_ALGORITHM", "ADLER32")
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
        raise ValueError("AUX_INPUT_CHECKSUM_ALGORITHM is not supported")
    return selected


def _case_environment() -> RunCase:
    raw = os.environ.get("AUX_INPUT_CASE", "INPUT_COMBINED")
    normalized = raw.strip().upper().replace("-", "_")
    try:
        return RUN_CASES[normalized]
    except KeyError as error:
        raise ValueError(
            "AUX_INPUT_CASE must be CONTROL_GPIO, CONTROL_COMBINED, "
            "INPUT_GPIO, or INPUT_COMBINED"
        ) from error


def _profile_environment() -> RateProfile:
    raw = os.environ.get("AUX_INPUT_RATE_PROFILE", PROFILES[0].name)
    normalized = raw.strip().upper().replace("-", "_")
    aliases = {
        "1MHZ_4MHZ": PROFILES[0],
        "500KHZ_2MHZ": PROFILES[1],
        "250KHZ_1MHZ": PROFILES[2],
        "125KHZ_500KHZ": PROFILES[3],
    }
    if normalized in PROFILE_BY_NAME:
        return PROFILE_BY_NAME[normalized]
    if normalized in aliases:
        return aliases[normalized]
    try:
        return PROFILE_BY_VALUE[int(raw, 0)]
    except (ValueError, KeyError) as error:
        raise ValueError(
            "AUX_INPUT_RATE_PROFILE must name one of the four exact profiles "
            "or use ID 0..3"
        ) from error


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        emit_event("configuration_error", error="SERIAL_PORT is required")
        return 2
    try:
        case = _case_environment()
        profile = _profile_environment()
        capture_seconds = _positive_float_environment(
            "AUX_INPUT_CAPTURE_SECONDS", DEFAULT_CAPTURE_SECONDS
        )
        warmup_seconds = _nonnegative_float_environment(
            "AUX_INPUT_WARMUP_SECONDS", DEFAULT_WARMUP_SECONDS
        )
        status_interval_seconds = _positive_float_environment(
            "AUX_INPUT_STATUS_INTERVAL_SECONDS", DEFAULT_STATUS_INTERVAL_SECONDS
        )
        checksum = _checksum_environment()
        fixture = load_fixture_declaration(os.environ.get("AUX_INPUT_FIXTURE_JSON"))
        expected_serial = _optional_uint32_environment("EXPECTED_HARDWARE_SERIAL")
        diagnostic_setting = os.environ.get("AUX_INPUT_RUN_DIAGNOSTIC", "1")
        if diagnostic_setting not in {"0", "1"}:
            raise ValueError("AUX_INPUT_RUN_DIAGNOSTIC must be 0 or 1")
        run_diagnostic = diagnostic_setting == "1"
    except (TypeError, ValueError) as error:
        emit_event("configuration_error", error=str(error))
        return 2
    expected_build_id = os.environ.get("EXPECTED_BUILD_ID")
    emit_event(
        "program_start",
        baud=BAUD_RATE,
        capture_seconds=capture_seconds,
        case=case.name,
        checksum=CHECKSUM_NAMES[checksum],
        fixture_authorized=fixture is not None,
        port=port_name,
        profile=profile.name,
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
    except Exception as error:  # noqa: BLE001 - rig-visible open diagnosis
        emit_event("open_failed", error=f"{type(error).__name__}: {error}")
        return 2
    try:
        result = run_acceptance(
            port,
            case=case,
            profile=profile,
            capture_seconds=capture_seconds,
            warmup_seconds=warmup_seconds,
            status_interval_seconds=status_interval_seconds,
            checksum_algorithm=checksum,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_serial,
            fixture=fixture,
            run_diagnostic=run_diagnostic,
        )
    finally:
        port.close()
    artifact = {
        "schema": "thingdaq.experiment-evidence/v1",
        "kind": "aux_input_capture",
        "paired_diagnostic": "REQUIRED" if run_diagnostic else "NOT_RUN",
        "protocol_version": PROTOCOL_VERSION,
        "case": case.name,
        "aux_bank_mode": "INPUT" if case.aux_mode == AUX_INPUT else "DISABLED",
        "rate_profile": profile.name,
        "configured_rates_hz": {
            "adc_pairs": profile.adc_rate_hz,
            "gpio_samples": profile.gpio_rate_hz,
        },
        "duration_seconds": capture_seconds,
        "fixture": {
            "authorized": fixture is not None,
            "classification": (
                result.stimulus_grade
                if fixture is not None
                else "ELECTRICALLY_UNSTIMULATED"
            ),
            "external_transition_checks": result.stimulus_grade,
        },
        "checks": len(result.evidence.checks),
        "failed_checks": [
            check for check in result.evidence.checks if not check["pass"]
        ],
        "failures": result.evidence.failures,
        "metrics": result.metrics,
        "result": "PASS" if not result.evidence.failures else "FAIL",
    }
    print("EVIDENCE " + json.dumps(artifact, sort_keys=True, separators=(",", ":")))
    return 0 if not result.evidence.failures else 1


if __name__ == "__main__":
    sys.exit(main())
