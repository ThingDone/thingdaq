#!/usr/bin/env python3
"""Independent Phase 07 physical dual-ADC hardware acceptance.

The remote rig uploads this file by itself to a network-disabled Python 3.13
container.  It intentionally embeds the protocol values it grades, uses only
the Python standard library plus pyserial, and never imports the project API or
generated constants.

The BOOT conversion-completion diagnostic is digital timing evidence.  It is
not an analog aperture measurement.  Raw values from A0/A1 are always checked
for wire layout and advertised code range, but analog stimulus conformance is
graded only when ``ADC_FIXTURE_STIMULUS_JSON`` contains a valid declaration.
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
SERIAL_READ_BYTES = 64 * 1024
STARTUP_DRAIN_SECONDS = 0.25
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 0.5
STOP_DRAIN_DEADLINE_SECONDS = 2.0
STOP_DRAIN_QUIET_SECONDS = 0.10
DEFAULT_CAPTURE_SECONDS = 10.0
DEFAULT_STATUS_INTERVAL_SECONDS = 0.25
DEFAULT_REDUCED_CAPTURE_FRAMES = 4
MAX_CAPTURE_SECONDS = 3600.0
MIN_STATUS_INTERVAL_SECONDS = 0.01
MAX_STATUS_SAMPLES = 16_384
MAX_REDUCED_CAPTURE_FRAMES = 64
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
MAX_CONTROL_FRAME_BYTES = 1024
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
ADC_PRIMARY_RESOLUTION_BITS = 12
ADC_FALLBACK_RESOLUTION_BITS = 10
ADC_CONTAINER_BYTES = 2
ADC_BYTES_PER_PAIR = 4
ADC_PAIRS_PER_FRAME = 1012
ADC_FRAME_COVERAGE_TICKS = ADC_PAIRS_PER_FRAME * ADC_PAIR_PERIOD_TICKS
ADC_CODE_MIN = 0
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
ADC_PINS = (14, 15)
ADC_PERIPHERALS = (1, 2)
ADC_CHANNELS = (7, 8)
ADC_DMA_RING_DEPTH = 4
ADC_PACKET_BUFFER_COUNT = 200

ADC_TRIGGER_PIT_CLOCK_HZ = 24_000_000
ADC_TRIGGER_DWT_CLOCK_HZ = 600_000_000
ADC_TRIGGER_GPIO_MASTER_RATE_HZ = 4_000_000
ADC_TRIGGER_PAIR_RATE_HZ = ADC_PAIR_RATE_HZ
ADC_TRIGGER_IPG_CLOCK_HZ = 150_000_000
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

ADC_CALIBRATION_SUCCEEDED = 1
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
    INFO_RESPONSE: 324,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 576,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
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
class ChannelStimulus:
    """Machine-readable accepted-code envelope for one declared input."""

    pin: str
    minimum_code: int
    maximum_code: int
    mean_minimum_code: float | None = None
    mean_maximum_code: float | None = None


@dataclass(frozen=True)
class FixtureStimulus:
    """Validated optional ADC fixture declaration supplied by the rig."""

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


@dataclass(frozen=True)
class StatusSnapshot:
    """Every STATUS field needed to reconcile the physical ADC path."""

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
    packet_ready_depth: int
    packet_transmit_depth: int
    packet_owned_high_water: int
    adc_resolution_bits: int
    adc_container_bytes: int
    adc_metadata: dict[str, int | tuple[int, int]]
    adc0_dma_major_loops: int
    adc1_dma_major_loops: int
    adc0_dma_results: int
    adc1_dma_results: int
    adc_paired_major_loops: int
    adc_buffers_completed: int
    adc_buffers_acquired: int
    adc_buffers_released: int
    adc_pairs_captured: int
    adc_pairs_delivered: int
    adc_pairs_framed: int
    adc_pairs_transmitted: int
    adc_raw_pairs_lost: int
    adc_stop_pairs_discarded: int
    adc_incomplete_conversions: int
    adc_overwritten_conversions: int
    adc_raw_ring_overruns: int
    adc_incomplete_buffers: int
    adc_raw_ready_depth: int
    adc_raw_ready_high_water: int
    adc_etc_error_events: int
    adc_etc_error_flags: int
    adc_dma_error_events: int
    adc_completion_mismatches: int
    adc_destination_mismatches: int
    adc_schedule_exhaustions: int
    adc_raw_invariant_errors: int
    adc_stale_completions: int
    adc_resource_conflicts: int
    adc_start_errors: int
    adc_stop_errors: int
    adc_stale_interrupts: int
    adc_packer_source_errors: int
    adc_packer_pipeline_errors: int
    adc_packer_chronology_errors: int

    def monotonic_counters(self) -> tuple[int, ...]:
        return (
            self.adc_frames_emitted,
            self.gpio_frames_emitted,
            self.adc_items_dropped,
            self.gpio_items_dropped,
            self.parser_errors,
            self.transport_errors,
            self.adc0_dma_major_loops,
            self.adc1_dma_major_loops,
            self.adc0_dma_results,
            self.adc1_dma_results,
            self.adc_paired_major_loops,
            self.adc_buffers_completed,
            self.adc_buffers_acquired,
            self.adc_buffers_released,
            self.adc_pairs_captured,
            self.adc_pairs_delivered,
            self.adc_pairs_framed,
            self.adc_pairs_transmitted,
            self.adc_raw_pairs_lost,
            self.adc_stop_pairs_discarded,
            self.adc_incomplete_conversions,
            self.adc_overwritten_conversions,
            self.adc_raw_ring_overruns,
            self.adc_incomplete_buffers,
            self.adc_etc_error_events,
            self.adc_etc_error_flags,
            self.adc_dma_error_events,
            self.adc_completion_mismatches,
            self.adc_destination_mismatches,
            self.adc_schedule_exhaustions,
            self.adc_raw_invariant_errors,
            self.adc_stale_completions,
            self.adc_resource_conflicts,
            self.adc_start_errors,
            self.adc_stop_errors,
            self.adc_stale_interrupts,
            self.adc_packer_source_errors,
            self.adc_packer_pipeline_errors,
            self.adc_packer_chronology_errors,
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
    fixture_stimulus_exercised: bool
    analog_quality_graded: bool
    aperture_graded: bool


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
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else DATA_PAYLOAD_BYTES
            )
            period = ADC_PAIR_PERIOD_TICKS if kind == ADC_DATA else 2
            if total_length != DATA_FRAME_BYTES or payload_length != DATA_PAYLOAD_BYTES:
                raise ProtocolFailure(
                    "data frame does not have the fixed 4096-byte shape"
                )
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
    """One-request-at-a-time serial link that services ADC data while waiting."""

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


class Evidence:
    """Structured expected-versus-actual checks for rig logs and grading."""

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

    record = {"event": name, **fields}
    print("EVENT " + json.dumps(record, sort_keys=True, separators=(",", ":")))


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
        "data_checksum_algorithm": payload[45],
        "hardware_serial": _u32(payload, 54),
        "firmware_version": (payload[58], payload[59], payload[60]),
        "board_id": _u16(payload, 62),
        "mcu_id": _u16(payload, 64),
        "build_id": build_id,
        "adc_metadata": decode_adc_metadata(payload, 128),
    }


def decode_configuration(frame: Frame, expected_kind: int) -> tuple[int, int, int, int]:
    response_success(frame, expected_kind)
    return (
        frame.payload[4],
        frame.payload[5],
        frame.payload[6],
        _u32(frame.payload, 8),
    )


_STATUS_U64_FIELDS = (
    ("adc0_dma_major_loops", 368),
    ("adc1_dma_major_loops", 376),
    ("adc0_dma_results", 384),
    ("adc1_dma_results", 392),
    ("adc_paired_major_loops", 400),
    ("adc_buffers_completed", 408),
    ("adc_buffers_acquired", 416),
    ("adc_buffers_released", 424),
    ("adc_pairs_captured", 432),
    ("adc_pairs_delivered", 440),
    ("adc_pairs_framed", 448),
    ("adc_pairs_transmitted", 456),
    ("adc_raw_pairs_lost", 464),
    ("adc_stop_pairs_discarded", 472),
    ("adc_incomplete_conversions", 480),
    ("adc_overwritten_conversions", 488),
    ("adc_raw_ring_overruns", 496),
    ("adc_incomplete_buffers", 504),
)
_STATUS_U32_FIELDS = (
    ("adc_etc_error_events", 516),
    ("adc_etc_error_flags", 520),
    ("adc_dma_error_events", 524),
    ("adc_completion_mismatches", 528),
    ("adc_destination_mismatches", 532),
    ("adc_schedule_exhaustions", 536),
    ("adc_raw_invariant_errors", 540),
    ("adc_stale_completions", 544),
    ("adc_resource_conflicts", 548),
    ("adc_start_errors", 552),
    ("adc_stop_errors", 556),
    ("adc_stale_interrupts", 560),
    ("adc_packer_source_errors", 564),
    ("adc_packer_pipeline_errors", 568),
    ("adc_packer_chronology_errors", 572),
)


def decode_status(frame: Frame) -> StatusSnapshot:
    response_success(frame, GET_STATUS_RESPONSE)
    payload = frame.payload
    counters: dict[str, int] = {
        name: _u64(payload, offset) for name, offset in _STATUS_U64_FIELDS
    }
    counters.update(
        {name: _u32(payload, offset) for name, offset in _STATUS_U32_FIELDS}
    )
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
        packet_ready_depth=_u16(payload, 128),
        packet_transmit_depth=_u16(payload, 130),
        packet_owned_high_water=_u16(payload, 132),
        adc_resolution_bits=payload[172],
        adc_container_bytes=payload[173],
        adc_metadata=decode_adc_metadata(payload, 176, status_layout=True),
        adc_raw_ready_depth=_u16(payload, 512),
        adc_raw_ready_high_water=_u16(payload, 514),
        **counters,
    )


def stable_identity(info: dict[str, object]) -> tuple[object, ...]:
    return (
        info["protocol_version"],
        info["hardware_serial"],
        info["firmware_version"],
        info["board_id"],
        info["mcu_id"],
        info["build_id"],
        info["supported_stream_mask"],
        info["supported_source_mask"],
        info["capability_bits"],
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


def _fixture_number(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")  # noqa: TRY004
    converted = float(value)
    if not math.isfinite(converted) or not minimum <= converted <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return converted


def _fixture_code(value: object, name: str, *, minimum: int) -> int:
    converted = _fixture_number(
        value,
        name,
        minimum=minimum,
        maximum=0xFFFF,
    )
    if not converted.is_integer():
        raise ValueError(f"{name} must be an integer ADC code")
    return int(converted)


def load_fixture_stimulus(raw: str | None) -> FixtureStimulus | None:
    """Parse the fail-closed optional machine-readable ADC fixture declaration."""

    if raw is None or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("ADC_FIXTURE_STIMULUS_JSON must be valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004
            "ADC fixture stimulus must be a JSON object"
        )
    allowed = {"schema", "fixture_id", "stimulus_id", "channels"}
    if set(value) != allowed:
        raise ValueError("ADC fixture stimulus contains missing or unknown fields")
    if value.get("schema") != "teensy-daq-adc-stimulus-v1":
        raise ValueError("ADC fixture stimulus schema is unsupported")
    fixture_id = value.get("fixture_id")
    stimulus_id = value.get("stimulus_id")
    for name, identifier in (
        ("fixture_id", fixture_id),
        ("stimulus_id", stimulus_id),
    ):
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", identifier
        ):
            raise ValueError(f"ADC fixture {name} is invalid")
    channels = value.get("channels")
    if not isinstance(channels, dict) or set(channels) != {"adc0", "adc1"}:
        raise ValueError("ADC fixture channels must declare adc0 and adc1")
    parsed: list[ChannelStimulus] = []
    for index, name in enumerate(("adc0", "adc1")):
        channel = channels[name]
        if not isinstance(channel, dict):
            raise ValueError(  # noqa: TRY004
                f"ADC fixture channel {name} must be an object"
            )
        required = {"pin", "minimum_code", "maximum_code"}
        optional = {"mean_minimum_code", "mean_maximum_code"}
        if not required <= set(channel) or set(channel) - required - optional:
            raise ValueError(f"ADC fixture channel {name} fields are invalid")
        mean_keys = optional & set(channel)
        if mean_keys not in (set(), optional):
            raise ValueError(f"ADC fixture channel {name} mean bounds are incomplete")
        expected_pin = f"A{index}"
        if channel["pin"] != expected_pin:
            raise ValueError(f"ADC fixture {name} must declare pin {expected_pin}")
        minimum_code = _fixture_code(
            channel["minimum_code"],
            f"{name}.minimum_code",
            minimum=0,
        )
        maximum_code = _fixture_code(
            channel["maximum_code"],
            f"{name}.maximum_code",
            minimum=minimum_code,
        )
        mean_minimum: float | None = None
        mean_maximum: float | None = None
        if mean_keys:
            mean_minimum = _fixture_number(
                channel["mean_minimum_code"],
                f"{name}.mean_minimum_code",
                minimum=minimum_code,
                maximum=maximum_code,
            )
            mean_maximum = _fixture_number(
                channel["mean_maximum_code"],
                f"{name}.mean_maximum_code",
                minimum=mean_minimum,
                maximum=maximum_code,
            )
        parsed.append(
            ChannelStimulus(
                pin=expected_pin,
                minimum_code=minimum_code,
                maximum_code=maximum_code,
                mean_minimum_code=mean_minimum,
                mean_maximum_code=mean_maximum,
            )
        )
    if not isinstance(fixture_id, str) or not isinstance(stimulus_id, str):
        raise ValueError("ADC fixture identifiers are invalid")  # noqa: TRY004
    return FixtureStimulus(fixture_id, stimulus_id, (parsed[0], parsed[1]))


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


def grade_adc_metadata(
    evidence: Evidence,
    metadata: dict[str, int | tuple[int, int]],
    *,
    resolution_bits: int,
    label: str,
) -> None:
    """Grade calibration, routes, trigger arithmetic, and register evidence."""

    before = len(evidence.failures)
    expected_code_max = (1 << resolution_bits) - 1
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
    forbidden_resolution_flag = (
        ADC_CONFIGURATION_FALLBACK_10_BIT
        if resolution_bits == ADC_PRIMARY_RESOLUTION_BITS
        else ADC_CONFIGURATION_PRIMARY_12_BIT
    )
    expected_flags = ADC_CONFIGURATION_COMMON_FLAGS | resolution_flag

    exact_scalars = {
        "code_min": ADC_CODE_MIN,
        "code_max": expected_code_max,
        "reference": ADC_REFERENCE,
        "clock_source": ADC_CLOCK_SOURCE,
        "clock_divider": ADC_CLOCK_DIVIDER,
        "hardware_average_count": ADC_HARDWARE_AVERAGE_COUNT,
        "reference_mv_nominal": ADC_REFERENCE_MV_NOMINAL,
        "input_min_mv_nominal": ADC_INPUT_MIN_MV_NOMINAL,
        "input_max_mv_nominal": ADC_INPUT_MAX_MV_NOMINAL,
        "sample_time_adck": ADC_SAMPLE_TIME_ADCK,
        "conversion_mode": expected_mode,
        "configuration_flags": expected_flags,
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
    evidence.equal(
        f"{label}.calibration_states",
        (1, 1),
        _metadata_pair(metadata, "calibration_states"),
    )
    evidence.equal(f"{label}.pins", ADC_PINS, _metadata_pair(metadata, "pins"))
    evidence.equal(
        f"{label}.peripherals",
        ADC_PERIPHERALS,
        _metadata_pair(metadata, "peripherals"),
    )
    evidence.equal(
        f"{label}.channels", ADC_CHANNELS, _metadata_pair(metadata, "channels")
    )
    evidence.equal(
        f"{label}.trigger_xbar_inputs",
        ADC_TRIGGER_XBAR_INPUTS,
        _metadata_pair(metadata, "trigger_xbar_inputs"),
    )
    evidence.equal(
        f"{label}.trigger_xbar_outputs",
        ADC_TRIGGER_XBAR_OUTPUTS,
        _metadata_pair(metadata, "trigger_xbar_outputs"),
    )
    evidence.equal(
        f"{label}.trigger_queues",
        ADC_TRIGGER_QUEUES,
        _metadata_pair(metadata, "trigger_queues"),
    )
    evidence.equal(
        f"{label}.trigger_initial_delays",
        ADC_TRIGGER_INITIAL_DELAYS,
        _metadata_pair(metadata, "trigger_initial_delays"),
    )
    evidence.equal(
        f"{label}.trigger_effective_delays",
        ADC_TRIGGER_EFFECTIVE_DELAYS,
        _metadata_pair(metadata, "trigger_effective_delays"),
    )

    flags = _metadata_int(metadata, "configuration_flags")
    evidence.equal(
        f"{label}.configuration_reserved_flags",
        0,
        flags & ~KNOWN_ADC_CONFIGURATION_FLAG_MASK,
    )
    evidence.equal(
        f"{label}.forbidden_resolution_flag",
        0,
        flags & forbidden_resolution_flag,
    )
    initialization_errors = _metadata_int(metadata, "initialization_error_flags")
    evidence.equal(
        f"{label}.initialization_reserved_errors",
        0,
        initialization_errors & ~KNOWN_ADC_INITIALIZATION_ERROR_MASK,
    )
    trigger_flags = _metadata_int(metadata, "trigger_configuration_flags")
    evidence.equal(
        f"{label}.trigger_reserved_flags",
        0,
        trigger_flags & ~KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK,
    )
    trigger_errors = _metadata_int(metadata, "trigger_error_flags")
    evidence.equal(
        f"{label}.trigger_reserved_errors",
        0,
        trigger_errors & ~KNOWN_ADC_TRIGGER_ERROR_MASK,
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
    cycles = _metadata_pair(metadata, "calibration_cycles")
    for index, cycle_count in enumerate(cycles):
        evidence.check(
            f"{label}.adc{index}_calibration_cycles",
            f"1..{ADC_CALIBRATION_DEADLINE_CYCLES}",
            cycle_count,
            1 <= cycle_count <= ADC_CALIBRATION_DEADLINE_CYCLES,
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
        f"{label}.gpio_to_adc_rate_ratio",
        4,
        _metadata_int(metadata, "trigger_gpio_master_rate_hz")
        // _metadata_int(metadata, "trigger_pair_rate_hz"),
    )
    evidence.equal(
        f"{label}.pit_master_rate_arithmetic",
        ADC_TRIGGER_GPIO_MASTER_RATE_HZ,
        ADC_TRIGGER_PIT_CLOCK_HZ // (ADC_TRIGGER_GPIO_MASTER_PIT_LOAD + 1),
    )
    evidence.equal(
        f"{label}.pit_chain_rate_arithmetic",
        ADC_TRIGGER_PAIR_RATE_HZ,
        ADC_TRIGGER_GPIO_MASTER_RATE_HZ // (ADC_TRIGGER_PAIR_PIT_LOAD + 1),
    )

    cscmr1 = _metadata_int(metadata, "trigger_ccm_cscmr1_configured")
    ccgr1 = _metadata_int(metadata, "trigger_ccm_ccgr1_configured")
    ccgr2 = _metadata_int(metadata, "trigger_ccm_ccgr2_configured")
    evidence.equal(
        f"{label}.register.perclk_24mhz", CCM_PERCLK_24MHZ, cscmr1 & CCM_PERCLK_MASK
    )
    evidence.equal(
        f"{label}.register.pit_adc_clock_gates",
        CCM_PIT_GATE_MASK | CCM_ADC1_GATE_MASK | CCM_ADC2_GATE_MASK,
        ccgr1 & (CCM_PIT_GATE_MASK | CCM_ADC1_GATE_MASK | CCM_ADC2_GATE_MASK),
    )
    evidence.equal(
        f"{label}.register.xbar_clock_gate",
        CCM_XBAR_GATE_MASK,
        ccgr2 & CCM_XBAR_GATE_MASK,
    )
    pit_mcr = _metadata_int(metadata, "trigger_pit_mcr_configured")
    evidence.equal(f"{label}.register.pit_enabled", 0, pit_mcr & PIT_MDIS)
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
        f"{label}.register.trigger_ctrl",
        (0, 0),
        _metadata_pair(metadata, "trigger_ctrl_configured"),
    )
    evidence.equal(
        f"{label}.register.trigger_counter",
        ADC_TRIGGER_INITIAL_DELAYS,
        _metadata_pair(metadata, "trigger_counter_configured"),
    )
    evidence.equal(
        f"{label}.register.trigger_chain",
        (ADC0_CHAIN_CONFIGURED, ADC1_CHAIN_CONFIGURED),
        _metadata_pair(metadata, "trigger_chain_configured"),
    )
    xbar_selects = _metadata_pair(metadata, "trigger_xbar_sel_configured")
    evidence.equal(
        f"{label}.register.xbar_selected_inputs",
        ADC_TRIGGER_XBAR_INPUTS,
        tuple((value >> 8) & 0xFF for value in xbar_selects),
    )
    done_error = _metadata_int(metadata, "adc_etc_done2_err_irq_final")
    evidence.equal(
        f"{label}.register.adc_etc_error_bits", 0, done_error & ADC_ETC_ERROR_MASK
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
        f"{ADC_COMPLETION_EXPECTED_DWT_CYCLES} +/- {ADC_COMPLETION_TOLERANCE_DWT_CYCLES}",
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
    if len(evidence.failures) != before:
        raise ProtocolFailure(f"{label} ADC calibration/register/timing grading failed")


def grade_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> int:
    """Pin the physical target identity and return the advertised resolution."""

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
        "adc_pair_period_ticks": ADC_PAIR_PERIOD_TICKS,
        "adc1_phase_ticks": ADC1_PHASE_TICKS,
        "adc_container_bytes": ADC_CONTAINER_BYTES,
        "board_id": 1,
        "mcu_id": 1,
    }
    for name, expected in exact.items():
        evidence.equal(f"identity.{name}", expected, info[name])
    firmware_version = info["firmware_version"]
    firmware_ok = (
        isinstance(firmware_version, tuple)
        and len(firmware_version) == 3
        and all(isinstance(part, int) for part in firmware_version)
        and firmware_version >= (0, 7, 0)
    )
    evidence.check(
        "identity.minimum_firmware",
        ">= (0, 7, 0)",
        firmware_version,
        firmware_ok,
    )
    build_id = info["build_id"]
    evidence.check(
        "identity.build_id_format",
        "tdaq- followed by 16 lowercase hexadecimal digits",
        build_id,
        isinstance(build_id, str)
        and re.fullmatch(r"tdaq-[0-9a-f]{16}", build_id) is not None,
    )
    if expected_build_id is not None:
        evidence.equal("identity.build_id", expected_build_id, build_id)
    hardware_serial = _info_int(info, "hardware_serial")
    evidence.check(
        "identity.hardware_serial_nonzero",
        "nonzero uint32",
        hardware_serial,
        1 <= hardware_serial <= 0xFFFFFFFF,
    )
    if expected_hardware_serial is not None:
        evidence.equal(
            "identity.hardware_serial",
            expected_hardware_serial,
            hardware_serial,
        )
    resolution_bits = _info_int(info, "adc_resolution_bits")
    evidence.check(
        "identity.adc_resolution_bits",
        "12-bit primary or explicitly gated 10-bit fallback",
        resolution_bits,
        resolution_bits in {ADC_PRIMARY_RESOLUTION_BITS, ADC_FALLBACK_RESOLUTION_BITS},
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
    evidence.equal(
        "identity.adc_code_range_width",
        1 << resolution_bits,
        _metadata_int(metadata, "code_max") - _metadata_int(metadata, "code_min") + 1,
    )
    evidence.equal(
        "identity.adc_pair_timestamp_rate",
        TIMESTAMP_HZ,
        _info_int(info, "adc_pair_rate_hz") * _info_int(info, "adc_pair_period_ticks"),
    )
    if len(evidence.failures) != before:
        raise ProtocolFailure("identity/capability grading failed")
    emit_event(
        "adc_boot_diagnostic_complete",
        analog_aperture_evidence=False,
        completion_delta_cycles=_metadata_int(metadata, "completion_delta_cycles"),
        completion_timing_only=True,
        resolution_bits=resolution_bits,
    )
    return resolution_bits


class PhysicalAdcValidator:
    """Validate every physical ADC frame without retaining bulk captures."""

    def __init__(
        self,
        run_id: int,
        checksum_algorithm: int,
        resolution_bits: int,
        fixture: FixtureStimulus | None,
    ) -> None:
        self.run_id = run_id
        self.checksum_algorithm = checksum_algorithm
        self.code_min = ADC_CODE_MIN
        self.code_max = (1 << resolution_bits) - 1
        self.fixture = fixture
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
        self.channel_minimums = [0xFFFF, 0xFFFF]
        self.channel_maximums = [0, 0]
        self.channel_sums = [0, 0]
        self.channel_counts = [0, 0]
        self.fixture_violations = [0, 0]
        self.maximum_receive_gap_seconds = 0.0
        self._last_received_at: float | None = None

    def accept(self, frame: Frame) -> None:
        now = time.monotonic()
        if self._last_received_at is not None:
            self.maximum_receive_gap_seconds = max(
                self.maximum_receive_gap_seconds,
                now - self._last_received_at,
            )
        self._last_received_at = now
        if frame.kind != ADC_DATA:
            raise ProtocolFailure(
                f"ADC-only capture received non-ADC data kind 0x{frame.kind:02x}"
            )
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"ADC frame run {frame.run_id} differs from {self.run_id}"
            )
        if frame.checksum_algorithm != self.checksum_algorithm:
            raise ProtocolFailure("ADC frame checksum selection changed within run")
        if frame.flags & FLAG_SYNTHETIC:
            raise ProtocolFailure("physical ADC frame is marked SYNTHETIC")
        if frame.flags & (FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE):
            raise ProtocolFailure("physical ADC frame reports gap/overrun")
        expected_flags = FLAG_EPOCH_START if self.adc.frames == 0 else 0
        if frame.flags != expected_flags:
            raise ProtocolFailure(
                f"ADC frame flags 0x{frame.flags:04x}; expected 0x{expected_flags:04x}"
            )
        if frame.sequence != self.adc.expected_sequence:
            raise ProtocolFailure(
                f"ADC sequence {frame.sequence}; expected {self.adc.expected_sequence}"
            )
        if frame.first_sample_ticks != self.adc.expected_ticks:
            raise ProtocolFailure(
                f"ADC timestamp {frame.first_sample_ticks}; "
                f"expected {self.adc.expected_ticks}"
            )
        if frame.item_count != ADC_PAIRS_PER_FRAME:
            raise ProtocolFailure(
                f"ADC item count {frame.item_count}; expected {ADC_PAIRS_PER_FRAME}"
            )
        if len(frame.payload) != ADC_PAIRS_PER_FRAME * ADC_BYTES_PER_PAIR:
            raise ProtocolFailure("ADC payload does not contain fixed four-byte pairs")

        for adc0, adc1 in struct.iter_unpack("<HH", frame.payload):
            self._accept_code(0, adc0)
            self._accept_code(1, adc1)

        self.adc.frames += 1
        self.adc.items += frame.item_count
        self.adc.payload_bytes += len(frame.payload)
        self.adc.framed_bytes += DATA_FRAME_BYTES
        self.adc.expected_sequence = (self.adc.expected_sequence + 1) & 0xFFFFFFFF
        self.adc.expected_ticks = (
            self.adc.expected_ticks + ADC_FRAME_COVERAGE_TICKS
        ) & 0xFFFFFFFFFFFFFFFF

    def _accept_code(self, converter: int, value: int) -> None:
        if not self.code_min <= value <= self.code_max:
            raise ProtocolFailure(
                f"ADC{converter} code {value} outside {self.code_min}..{self.code_max}"
            )
        self.channel_minimums[converter] = min(self.channel_minimums[converter], value)
        self.channel_maximums[converter] = max(self.channel_maximums[converter], value)
        self.channel_sums[converter] += value
        self.channel_counts[converter] += 1
        if self.fixture is not None:
            declared = self.fixture.channels[converter]
            if not declared.minimum_code <= value <= declared.maximum_code:
                self.fixture_violations[converter] += 1

    def means(self) -> tuple[float, float]:
        if not all(self.channel_counts):
            raise ProtocolFailure("ADC capture contains no complete sample pairs")
        return (
            self.channel_sums[0] / self.channel_counts[0],
            self.channel_sums[1] / self.channel_counts[1],
        )

    def grade_fixture(self, evidence: Evidence, *, label: str) -> bool:
        if self.fixture is None:
            return False
        before = len(evidence.failures)
        evidence.equal(
            f"{label}.stimulus_code_violations",
            (0, 0),
            tuple(self.fixture_violations),
        )
        means = self.means()
        if self.fixture.grades_analog_quality:
            for index, (mean, declared) in enumerate(
                zip(means, self.fixture.channels, strict=True)
            ):
                lower = declared.mean_minimum_code
                upper = declared.mean_maximum_code
                if lower is None or upper is None:
                    raise ProtocolFailure("fixture analog bounds are inconsistent")
                evidence.check(
                    f"{label}.adc{index}_mean_code",
                    f"{lower}..{upper}",
                    mean,
                    lower <= mean <= upper,
                )
        if len(evidence.failures) != before:
            raise ProtocolFailure("declared ADC fixture stimulus grading failed")
        return self.fixture.grades_analog_quality


def _status_error_values(status: StatusSnapshot) -> dict[str, int]:
    return {
        "adc_items_dropped": status.adc_items_dropped,
        "gpio_frames_emitted": status.gpio_frames_emitted,
        "gpio_items_dropped": status.gpio_items_dropped,
        "parser_errors": status.parser_errors,
        "transport_errors": status.transport_errors,
        "adc_raw_pairs_lost": status.adc_raw_pairs_lost,
        "adc_stop_pairs_discarded": status.adc_stop_pairs_discarded,
        "adc_incomplete_conversions": status.adc_incomplete_conversions,
        "adc_overwritten_conversions": status.adc_overwritten_conversions,
        "adc_raw_ring_overruns": status.adc_raw_ring_overruns,
        "adc_incomplete_buffers": status.adc_incomplete_buffers,
        "adc_etc_error_events": status.adc_etc_error_events,
        "adc_etc_error_flags": status.adc_etc_error_flags,
        "adc_dma_error_events": status.adc_dma_error_events,
        "adc_completion_mismatches": status.adc_completion_mismatches,
        "adc_destination_mismatches": status.adc_destination_mismatches,
        "adc_schedule_exhaustions": status.adc_schedule_exhaustions,
        "adc_raw_invariant_errors": status.adc_raw_invariant_errors,
        "adc_stale_completions": status.adc_stale_completions,
        "adc_resource_conflicts": status.adc_resource_conflicts,
        "adc_start_errors": status.adc_start_errors,
        "adc_stop_errors": status.adc_stop_errors,
        "adc_stale_interrupts": status.adc_stale_interrupts,
        "adc_packer_source_errors": status.adc_packer_source_errors,
        "adc_packer_pipeline_errors": status.adc_packer_pipeline_errors,
        "adc_packer_chronology_errors": status.adc_packer_chronology_errors,
    }


def validate_status_accounting(status: StatusSnapshot) -> None:
    """Reject an internally inconsistent DMA-to-USB accounting snapshot."""

    if status.adc0_dma_results != status.adc0_dma_major_loops * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS ADC0 result count disagrees with major loops")
    if status.adc1_dma_results != status.adc1_dma_major_loops * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS ADC1 result count disagrees with major loops")
    if abs(status.adc0_dma_major_loops - status.adc1_dma_major_loops) > 1:
        raise ProtocolFailure("STATUS ADC channel major-loop lead exceeds one")
    if status.adc_paired_major_loops != min(
        status.adc0_dma_major_loops,
        status.adc1_dma_major_loops,
    ):
        raise ProtocolFailure("STATUS paired major loops disagree with channel barrier")
    if status.adc_buffers_completed > status.adc_paired_major_loops:
        raise ProtocolFailure("STATUS completed buffers exceed paired major loops")
    if status.adc_buffers_acquired > status.adc_buffers_completed:
        raise ProtocolFailure("STATUS acquired buffers exceed completed buffers")
    if status.adc_buffers_released > status.adc_buffers_acquired:
        raise ProtocolFailure("STATUS released buffers exceed acquired buffers")
    if status.adc_pairs_delivered != status.adc_buffers_acquired * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS delivered pairs disagree with buffer leases")
    if status.adc_pairs_framed != status.adc_frames_emitted * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS framed pairs disagree with emitted ADC frames")
    if status.adc_pairs_transmitted > status.adc_pairs_framed:
        raise ProtocolFailure("STATUS transmitted pairs exceed framed pairs")
    if status.adc_pairs_transmitted % ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("STATUS transmitted pairs are not whole ADC frames")
    if status.adc_pairs_delivered < status.adc_pairs_framed:
        raise ProtocolFailure("STATUS framed pairs exceed delivered pairs")
    if status.adc_pairs_captured < status.adc_pairs_delivered:
        raise ProtocolFailure("STATUS delivered pairs exceed captured pairs")
    if status.adc_raw_ready_depth > status.adc_raw_ready_high_water:
        raise ProtocolFailure("STATUS current ADC ready depth exceeds its high water")
    if (
        status.packet_ready_depth + status.packet_transmit_depth
        > ADC_PACKET_BUFFER_COUNT
    ):
        raise ProtocolFailure("STATUS packet depths exceed fixed packet capacity")
    if any(_status_error_values(status).values()):
        raise ProtocolFailure(
            "STATUS reports ADC_ETC/DMA/cache/frame/transport/lifecycle errors"
        )
    if status.adc_buffers_completed != status.adc_paired_major_loops:
        raise ProtocolFailure("error-free STATUS lost a paired DMA buffer")
    if status.adc_pairs_captured != status.adc_paired_major_loops * ADC_PAIRS_PER_FRAME:
        raise ProtocolFailure("error-free STATUS captured-pair accounting disagrees")


def validate_status_identity(
    status: StatusSnapshot,
    *,
    expected_state: int,
    checksum_algorithm: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> None:
    if status.device_state != expected_state:
        raise ProtocolFailure(
            f"STATUS state {status.device_state}; expected {expected_state}"
        )
    expected_stream = STREAM_NONE if expected_state == STATE_IDLE else STREAM_ADC
    if (
        status.stream_mask != expected_stream
        or status.source != SOURCE_HARDWARE
        or status.checksum != checksum_algorithm
        or status.data_frame_bytes != DATA_FRAME_BYTES
    ):
        raise ProtocolFailure("STATUS active configuration is inconsistent")
    if (
        status.adc_resolution_bits != resolution_bits
        or status.adc_container_bytes != ADC_CONTAINER_BYTES
        or status.adc_metadata != expected_metadata
    ):
        raise ProtocolFailure("STATUS ADC metadata changed from the graded INFO")
    if not 1 <= status.stats_generation <= 0xFFFFFFFF:
        raise ProtocolFailure("STATUS statistics generation is invalid")
    if not 0 <= status.adc_raw_ready_depth <= ADC_DMA_RING_DEPTH:
        raise ProtocolFailure("STATUS ADC ready depth exceeds ring capacity")
    if not 0 <= status.adc_raw_ready_high_water <= ADC_DMA_RING_DEPTH:
        raise ProtocolFailure("STATUS ADC high-water depth exceeds ring capacity")
    for depth in (
        status.packet_ready_depth,
        status.packet_transmit_depth,
        status.packet_owned_high_water,
    ):
        if not 0 <= depth <= ADC_PACKET_BUFFER_COUNT:
            raise ProtocolFailure("STATUS packet depth exceeds fixed capacity")
    validate_status_accounting(status)


def validate_running_status(
    status: StatusSnapshot,
    frame: Frame,
    validator: PhysicalAdcValidator,
    *,
    stats_generation: int,
    host_frames_before_request: int,
    previous_status: StatusSnapshot | None,
    checksum_algorithm: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> None:
    validate_status_identity(
        status,
        expected_state=STATE_RUNNING,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    if frame.run_id != validator.run_id:
        raise ProtocolFailure("running STATUS run ID disagrees with START")
    if status.stats_generation != stats_generation:
        raise ProtocolFailure("running STATUS statistics generation changed")
    if status.adc_frames_emitted < host_frames_before_request:
        raise ProtocolFailure(
            "STATUS ADC frame count trails the pre-request host floor"
        )
    if previous_status is not None and any(
        current < previous
        for current, previous in zip(
            status.monotonic_counters(),
            previous_status.monotonic_counters(),
            strict=True,
        )
    ):
        raise ProtocolFailure("STATUS ADC counters moved backwards")


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
class EpochResult:
    validator: PhysicalAdcValidator
    final_status: StatusSnapshot
    capture_elapsed: float
    timed_frames: int
    timed_items: int
    status_latencies: tuple[float, ...]
    status_count: int
    parser_errors_at_start: int
    memory: MemoryTracker


def _bounded_deferred_collector(target: list[Frame]) -> Callable[[Frame], None]:
    maximum = math.ceil(SERIAL_READ_BYTES / DATA_FRAME_BYTES) + 1

    def collect(frame: Frame) -> None:
        if len(target) >= maximum:
            raise ProtocolFailure(
                f"START boundary exceeded its {maximum}-frame deferred bound"
            )
        target.append(frame)

    return collect


def configure_and_start(
    link: SerialLink,
    evidence: Evidence,
    *,
    label: str,
    checksum_algorithm: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
    fixture: FixtureStimulus | None,
) -> tuple[PhysicalAdcValidator, int, int]:
    requested = CONFIGURATION.pack(
        STREAM_ADC,
        SOURCE_HARDWARE,
        checksum_algorithm,
        0,
        DATA_FRAME_BYTES,
    )
    configured_frame, configure_latency = link.exchange(CONFIGURE_REQUEST, requested)
    evidence.check(
        f"{label}.latency.configure_seconds",
        f"<= {COMMAND_DEADLINE_SECONDS}",
        configure_latency,
        configure_latency <= COMMAND_DEADLINE_SECONDS,
    )
    evidence.equal(
        f"{label}.configure.applied",
        (STREAM_ADC, SOURCE_HARDWARE, checksum_algorithm, DATA_FRAME_BYTES),
        decode_configuration(configured_frame, CONFIGURE_RESPONSE),
    )
    configured_status_frame, status_latency = link.exchange(GET_STATUS_REQUEST)
    configured_status = decode_status(configured_status_frame)
    evidence.check(
        f"{label}.latency.configured_status_seconds",
        f"<= {COMMAND_DEADLINE_SECONDS}",
        status_latency,
        status_latency <= COMMAND_DEADLINE_SECONDS,
    )
    validate_status_identity(
        configured_status,
        expected_state=STATE_CONFIGURED,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )

    deferred: list[Frame] = []
    start_frame, start_latency = link.exchange(
        START_REQUEST,
        on_data=_bounded_deferred_collector(deferred),
    )
    evidence.check(
        f"{label}.latency.start_seconds",
        f"<= {COMMAND_DEADLINE_SECONDS}",
        start_latency,
        start_latency <= COMMAND_DEADLINE_SECONDS,
    )
    response_success(start_frame, START_RESPONSE)
    evidence.equal(
        f"{label}.start.applied",
        (STREAM_ADC, SOURCE_HARDWARE, checksum_algorithm, DATA_FRAME_BYTES),
        decode_configuration(start_frame, START_RESPONSE),
    )
    evidence.check(
        f"{label}.start.run_id",
        "nonzero uint32",
        start_frame.run_id,
        1 <= start_frame.run_id <= 0xFFFFFFFF,
    )
    validator = PhysicalAdcValidator(
        start_frame.run_id,
        checksum_algorithm,
        resolution_bits,
        fixture,
    )
    for frame in deferred:
        validator.accept(frame)
    expected_generation = (configured_status.stats_generation + 1) & 0xFFFFFFFF
    expected_generation = expected_generation or 1
    return validator, expected_generation, link.parser.errors


def stop_and_finalize_epoch(
    link: SerialLink,
    evidence: Evidence,
    validator: PhysicalAdcValidator,
    *,
    label: str,
    stats_generation: int,
    checksum_algorithm: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> StatusSnapshot:
    stop_frame, stop_latency = link.exchange(
        STOP_REQUEST,
        on_data=validator.accept,
    )
    response_success(stop_frame, STOP_RESPONSE)
    evidence.check(
        f"{label}.latency.stop_seconds",
        f"<= {COMMAND_DEADLINE_SECONDS}",
        stop_latency,
        stop_latency <= COMMAND_DEADLINE_SECONDS,
    )
    evidence.equal(f"{label}.stop.state", STATE_IDLE, stop_frame.payload[4])
    evidence.equal(f"{label}.stop.run_id", validator.run_id, stop_frame.run_id)
    link.drain_until_quiet(validator.accept)
    final_frame, final_latency = link.exchange(
        GET_STATUS_REQUEST,
        on_data=validator.accept,
    )
    final_status = decode_status(final_frame)
    evidence.check(
        f"{label}.latency.final_status_seconds",
        f"<= {COMMAND_DEADLINE_SECONDS}",
        final_latency,
        final_latency <= COMMAND_DEADLINE_SECONDS,
    )
    validate_status_identity(
        final_status,
        expected_state=STATE_IDLE,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    if final_frame.run_id != validator.run_id:
        raise ProtocolFailure("final STATUS run ID disagrees with START")
    if final_status.stats_generation != stats_generation:
        raise ProtocolFailure("final STATUS statistics generation changed")
    if final_status.adc0_dma_major_loops != final_status.adc1_dma_major_loops:
        raise ProtocolFailure("final ADC channel major-loop completions are unmatched")
    if not (
        final_status.adc_buffers_completed
        == final_status.adc_buffers_acquired
        == final_status.adc_buffers_released
        == final_status.adc_frames_emitted
        == validator.adc.frames
    ):
        raise ProtocolFailure("final ADC buffer/frame counters do not reconcile")
    if not (
        final_status.adc_pairs_captured
        == final_status.adc_pairs_delivered
        == final_status.adc_pairs_framed
        == final_status.adc_pairs_transmitted
        == validator.adc.items
    ):
        raise ProtocolFailure("final ADC pair counters do not reconcile")
    if (
        final_status.adc_raw_ready_depth
        or final_status.packet_ready_depth
        or final_status.packet_transmit_depth
    ):
        raise ProtocolFailure("final ADC/packet queues are not empty")
    return final_status


def run_reduced_capture(
    link: SerialLink,
    evidence: Evidence,
    *,
    frame_target: int,
    checksum_algorithm: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
) -> None:
    """Run a bounded low-volume DMA capture before the timed full-rate epoch.

    The active converter schedule remains the exact 1 MHz production schedule;
    the bounded frame quota deliberately reduces total diagnostic traffic.  The
    BOOT snapshot above is the bounded one-pair trigger timing diagnostic.
    """

    label = "reduced_capture"
    validator, expected_generation, parser_errors_at_start = configure_and_start(
        link,
        evidence,
        label=label,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
        fixture=None,
    )
    deadline = time.monotonic() + max(
        COMMAND_DEADLINE_SECONDS,
        4 * frame_target * ADC_PAIRS_PER_FRAME / ADC_PAIR_RATE_HZ,
    )
    while validator.adc.frames < frame_target:
        if time.monotonic() >= deadline:
            raise DeadlineExpired(
                f"bounded ADC capture received {validator.adc.frames}/{frame_target} frames"
            )
        link.pump_once(validator.accept)
    host_floor = validator.adc.frames
    status_frame, status_latency = link.exchange(
        GET_STATUS_REQUEST,
        on_data=validator.accept,
    )
    status = decode_status(status_frame)
    validate_running_status(
        status,
        status_frame,
        validator,
        stats_generation=expected_generation,
        host_frames_before_request=host_floor,
        previous_status=None,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    evidence.check(
        f"{label}.latency.status_seconds",
        f"<= {COMMAND_DEADLINE_SECONDS}",
        status_latency,
        status_latency <= COMMAND_DEADLINE_SECONDS,
    )
    final_status = stop_and_finalize_epoch(
        link,
        evidence,
        validator,
        label=label,
        stats_generation=expected_generation,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    evidence.equal(
        f"{label}.host_parser_errors",
        0,
        link.parser.errors - parser_errors_at_start,
    )
    emit_event(
        "reduced_capture_complete",
        active_pair_rate_hz=ADC_PAIR_RATE_HZ,
        adc_frames=validator.adc.frames,
        adc_pairs=validator.adc.items,
        diagnostic_scope="bounded low-volume trigger/DMA path",
        dma_major_loops=final_status.adc_paired_major_loops,
    )


def run_full_rate_capture(
    link: SerialLink,
    evidence: Evidence,
    *,
    capture_seconds: float,
    status_interval_seconds: float,
    checksum_algorithm: int,
    resolution_bits: int,
    expected_metadata: dict[str, int | tuple[int, int]],
    fixture: FixtureStimulus | None,
) -> EpochResult:
    label = "full_rate"
    validator, expected_generation, parser_errors_at_start = configure_and_start(
        link,
        evidence,
        label=label,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
        fixture=fixture,
    )
    memory = MemoryTracker()
    timed_start_frames = validator.adc.frames
    timed_start_items = validator.adc.items
    active_started = time.monotonic()
    capture_deadline = active_started + capture_seconds
    next_status_at = active_started
    status_latencies: list[float] = []
    previous_status: StatusSnapshot | None = None
    status_count = 0
    while time.monotonic() < capture_deadline:
        now = time.monotonic()
        if now >= next_status_at:
            host_floor = validator.adc.frames
            status_frame, latency = link.exchange(
                GET_STATUS_REQUEST,
                on_data=validator.accept,
            )
            status = decode_status(status_frame)
            validate_running_status(
                status,
                status_frame,
                validator,
                stats_generation=expected_generation,
                host_frames_before_request=host_floor,
                previous_status=previous_status,
                checksum_algorithm=checksum_algorithm,
                resolution_bits=resolution_bits,
                expected_metadata=expected_metadata,
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
    capture_elapsed = time.monotonic() - active_started
    timed_frames = validator.adc.frames - timed_start_frames
    timed_items = validator.adc.items - timed_start_items
    final_status = stop_and_finalize_epoch(
        link,
        evidence,
        validator,
        label=label,
        stats_generation=expected_generation,
        checksum_algorithm=checksum_algorithm,
        resolution_bits=resolution_bits,
        expected_metadata=expected_metadata,
    )
    memory.sample()
    return EpochResult(
        validator=validator,
        final_status=final_status,
        capture_elapsed=capture_elapsed,
        timed_frames=timed_frames,
        timed_items=timed_items,
        status_latencies=tuple(status_latencies),
        status_count=status_count,
        parser_errors_at_start=parser_errors_at_start,
        memory=memory,
    )


def grade_full_rate_result(
    evidence: Evidence,
    result: EpochResult,
    link: SerialLink,
    *,
    capture_seconds: float,
    status_interval_seconds: float,
) -> tuple[bool, bool]:
    validator = result.validator
    final_status = result.final_status
    pair_rate = result.timed_items / result.capture_elapsed
    payload_rate = pair_rate * ADC_BYTES_PER_PAIR
    framed_rate = result.timed_frames * DATA_FRAME_BYTES / result.capture_elapsed
    pair_rate_error = abs(pair_rate - ADC_PAIR_RATE_HZ) / ADC_PAIR_RATE_HZ
    evidence.check(
        "rate.adc_pairs_per_second",
        f"{ADC_PAIR_RATE_HZ} +/- {RATE_TOLERANCE_FRACTION:.1%}",
        pair_rate,
        result.timed_items > 0 and pair_rate_error <= RATE_TOLERANCE_FRACTION,
    )
    evidence.check(
        "rate.payload_bytes_per_second",
        f"{ADC_PAIR_RATE_HZ * ADC_BYTES_PER_PAIR} +/- {RATE_TOLERANCE_FRACTION:.1%}",
        payload_rate,
        result.timed_items > 0 and pair_rate_error <= RATE_TOLERANCE_FRACTION,
    )
    expected_framed_rate = ADC_PAIR_RATE_HZ / ADC_PAIRS_PER_FRAME * DATA_FRAME_BYTES
    framed_error = abs(framed_rate - expected_framed_rate) / expected_framed_rate
    evidence.check(
        "rate.framed_bytes_per_second",
        f"{expected_framed_rate} +/- {RATE_TOLERANCE_FRACTION:.1%}",
        framed_rate,
        result.timed_frames > 0 and framed_error <= RATE_TOLERANCE_FRACTION,
    )

    evidence.equal(
        "layout.payload_pair_bytes",
        ADC_BYTES_PER_PAIR,
        DATA_PAYLOAD_BYTES // ADC_PAIRS_PER_FRAME,
    )
    evidence.equal(
        "layout.adc0_offset_adc1_offset",
        (0, 2),
        (0, ADC_CONTAINER_BYTES),
    )
    evidence.equal(
        "stream.adc_pair_count",
        validator.adc.frames * ADC_PAIRS_PER_FRAME,
        validator.adc.items,
    )
    evidence.equal(
        "stream.adc_payload_bytes",
        validator.adc.items * ADC_BYTES_PER_PAIR,
        validator.adc.payload_bytes,
    )
    evidence.equal(
        "stream.adc_final_sequence",
        validator.adc.frames & 0xFFFFFFFF,
        validator.adc.expected_sequence,
    )
    evidence.equal(
        "stream.adc_final_timestamp",
        (validator.adc.items * ADC_PAIR_PERIOD_TICKS) & 0xFFFFFFFFFFFFFFFF,
        validator.adc.expected_ticks,
    )
    evidence.equal(
        "stream.code_counts",
        (validator.adc.items, validator.adc.items),
        tuple(validator.channel_counts),
    )
    evidence.check(
        "stream.code_range_adc0",
        f"{validator.code_min}..{validator.code_max}",
        (validator.channel_minimums[0], validator.channel_maximums[0]),
        validator.code_min
        <= validator.channel_minimums[0]
        <= validator.channel_maximums[0]
        <= validator.code_max,
    )
    evidence.check(
        "stream.code_range_adc1",
        f"{validator.code_min}..{validator.code_max}",
        (validator.channel_minimums[1], validator.channel_maximums[1]),
        validator.code_min
        <= validator.channel_minimums[1]
        <= validator.channel_maximums[1]
        <= validator.code_max,
    )

    evidence.equal(
        "final.matched_dma_major_loops",
        final_status.adc0_dma_major_loops,
        final_status.adc1_dma_major_loops,
    )
    evidence.equal(
        "final.firmware_host_adc_frames",
        validator.adc.frames,
        final_status.adc_frames_emitted,
    )
    evidence.equal(
        "final.firmware_host_adc_pairs",
        validator.adc.items,
        final_status.adc_pairs_transmitted,
    )
    for name, actual in _status_error_values(final_status).items():
        evidence.equal(f"final.error.{name}", 0, actual)
    evidence.equal("queue.adc_raw_ready_depth", 0, final_status.adc_raw_ready_depth)
    evidence.check(
        "queue.adc_raw_ready_high_water",
        f"<= {ADC_DMA_RING_DEPTH}",
        final_status.adc_raw_ready_high_water,
        0 < final_status.adc_raw_ready_high_water <= ADC_DMA_RING_DEPTH,
    )
    evidence.equal("queue.packet_ready_depth", 0, final_status.packet_ready_depth)
    evidence.equal("queue.packet_transmit_depth", 0, final_status.packet_transmit_depth)
    evidence.check(
        "queue.packet_owned_high_water",
        f"1..{ADC_PACKET_BUFFER_COUNT}",
        final_status.packet_owned_high_water,
        1 <= final_status.packet_owned_high_water <= ADC_PACKET_BUFFER_COUNT,
    )

    minimum_status_samples = max(1, int(capture_seconds / status_interval_seconds))
    p99 = percentile(list(result.status_latencies), 0.99)
    maximum = max(result.status_latencies, default=math.inf)
    evidence.check(
        "latency.status_sample_count",
        f">= {minimum_status_samples}",
        result.status_count,
        result.status_count >= minimum_status_samples,
    )
    evidence.check(
        "latency.status_p99_seconds",
        f"<= {STATUS_P99_LIMIT_SECONDS}",
        p99,
        bool(result.status_latencies) and p99 <= STATUS_P99_LIMIT_SECONDS,
    )
    evidence.check(
        "latency.status_maximum_seconds",
        f"<= {STATUS_MAXIMUM_LIMIT_SECONDS}",
        maximum,
        bool(result.status_latencies) and maximum <= STATUS_MAXIMUM_LIMIT_SECONDS,
    )
    evidence.equal(
        "host.parser_errors",
        0,
        link.parser.errors - result.parser_errors_at_start,
    )
    evidence.equal("host.stale_responses", 0, link.stale_responses)
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
        "host.checksummed_frames",
        f">= {validator.adc.frames} ADC data frames",
        link.parser.frames_decoded,
        link.parser.frames_decoded >= validator.adc.frames,
    )
    evidence.check(
        "memory.peak_rss_growth_bytes",
        f"<= {MAX_RSS_GROWTH_BYTES}",
        result.memory.peak_growth_bytes,
        result.memory.peak_growth_bytes <= MAX_RSS_GROWTH_BYTES,
    )
    evidence.check(
        "memory.process_rss_bytes",
        "finite nonnegative baseline/current/peak",
        {
            "baseline_current": result.memory.baseline_current_bytes,
            "baseline_peak": result.memory.baseline_peak_bytes,
            "final_current": result.memory.final_current_bytes,
            "peak": result.memory.peak_bytes,
        },
        0
        <= result.memory.baseline_current_bytes
        <= result.memory.maximum_current_bytes
        <= result.memory.peak_bytes,
    )

    analog_quality_graded = validator.grade_fixture(
        evidence,
        label="fixture",
    )
    fixture_exercised = validator.fixture is not None
    emit_event(
        "capture_complete",
        adc_frames=validator.adc.frames,
        adc_pairs=validator.adc.items,
        analog_aperture_graded=False,
        analog_quality_graded=analog_quality_graded,
        capture_elapsed_seconds=result.capture_elapsed,
        checksum_algorithm=CHECKSUM_NAMES[validator.checksum_algorithm],
        checksum_algorithm_id=validator.checksum_algorithm,
        fixture_stimulus_exercised=fixture_exercised,
        framed_bytes=validator.adc.framed_bytes,
        pair_rate_hz=pair_rate,
        payload_bytes=validator.adc.payload_bytes,
        status_requests=result.status_count,
    )
    return fixture_exercised, analog_quality_graded


def run_acceptance(
    port: SerialPort,
    *,
    capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
    status_interval_seconds: float = DEFAULT_STATUS_INTERVAL_SECONDS,
    reduced_capture_frames: int = DEFAULT_REDUCED_CAPTURE_FRAMES,
    checksum_algorithm: int = DEFAULT_DATA_CHECKSUM,
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
    fixture: FixtureStimulus | None = None,
) -> AcceptanceResult:
    """Run bounded diagnostic and timed full-rate epochs; leave IDLE."""

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
    if not 1 <= reduced_capture_frames <= MAX_REDUCED_CAPTURE_FRAMES:
        raise ValueError(
            f"reduced_capture_frames must be in [1, {MAX_REDUCED_CAPTURE_FRAMES}]"
        )
    if checksum_algorithm not in SUPPORTED_CHECKSUMS:
        raise ProtocolFailure(
            f"host lacks checksum support for algorithm {checksum_algorithm}"
        )

    evidence = Evidence()
    link = SerialLink(port)
    completed = False
    active_validator: PhysicalAdcValidator | None = None
    fixture_exercised = False
    analog_quality_graded = False
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
        resolution_bits = grade_info(
            evidence,
            info,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
        checksum_mask = _info_int(info, "supported_checksum_mask")
        if not checksum_mask & (1 << checksum_algorithm):
            raise ProtocolFailure(
                f"device does not advertise checksum algorithm {checksum_algorithm}"
            )
        metadata_value = info["adc_metadata"]
        if not isinstance(metadata_value, dict):
            raise ProtocolFailure("INFO ADC metadata is invalid")
        expected_metadata: dict[str, int | tuple[int, int]] = metadata_value

        if fixture is None:
            print(
                "ADC_STIMULUS: A0/A1 are unstimulated; analog quality and "
                "analog aperture were not graded"
            )
            emit_event(
                "fixture_stimulus",
                analog_aperture_graded=False,
                analog_quality_graded=False,
                declared=False,
                pins="A0,A1",
            )
        else:
            print(
                "ADC_STIMULUS: using declared machine-readable fixture "
                f"{fixture.fixture_id}/{fixture.stimulus_id}; analog aperture "
                "was not graded"
            )
            emit_event(
                "fixture_stimulus",
                analog_aperture_graded=False,
                analog_quality_requested=fixture.grades_analog_quality,
                declared=True,
                fixture_id=fixture.fixture_id,
                stimulus_id=fixture.stimulus_id,
            )

        run_reduced_capture(
            link,
            evidence,
            frame_target=reduced_capture_frames,
            checksum_algorithm=checksum_algorithm,
            resolution_bits=resolution_bits,
            expected_metadata=expected_metadata,
        )
        full_result = run_full_rate_capture(
            link,
            evidence,
            capture_seconds=capture_seconds,
            status_interval_seconds=status_interval_seconds,
            checksum_algorithm=checksum_algorithm,
            resolution_bits=resolution_bits,
            expected_metadata=expected_metadata,
            fixture=fixture,
        )
        active_validator = full_result.validator
        fixture_exercised, analog_quality_graded = grade_full_rate_result(
            evidence,
            full_result,
            link,
            capture_seconds=capture_seconds,
            status_interval_seconds=status_interval_seconds,
        )
        completed = not evidence.failures
    except Exception as error:  # noqa: BLE001 - stdout is the remote diagnosis
        message = f"{type(error).__name__}: {error}"
        diagnostics: dict[str, object] = {}
        if active_validator is not None:
            diagnostics = {
                "accepted_adc_frames": active_validator.adc.frames,
                "accepted_adc_pairs": active_validator.adc.items,
                "maximum_receive_gap_seconds": (
                    active_validator.maximum_receive_gap_seconds
                ),
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
            else:
                try:
                    failure_frame, failure_latency = link.exchange(
                        GET_STATUS_REQUEST,
                        timeout=COMMAND_DEADLINE_SECONDS,
                        on_data=lambda _frame: None,
                    )
                    failure_status = decode_status(failure_frame)
                    emit_event(
                        "failure_status",
                        adc_dma_error_events=failure_status.adc_dma_error_events,
                        adc_etc_error_events=failure_status.adc_etc_error_events,
                        adc_frames_emitted=failure_status.adc_frames_emitted,
                        adc_items_dropped=failure_status.adc_items_dropped,
                        adc_pairs_transmitted=failure_status.adc_pairs_transmitted,
                        latency_seconds=failure_latency,
                        parser_errors=failure_status.parser_errors,
                        state=failure_status.device_state,
                        stats_generation=failure_status.stats_generation,
                        transport_errors=failure_status.transport_errors,
                    )
                except Exception as status_error:  # noqa: BLE001 - diagnostics only
                    emit_event(
                        "failure_status_failed",
                        error=f"{type(status_error).__name__}: {status_error}",
                    )
    return AcceptanceResult(
        evidence=evidence,
        fixture_stimulus_exercised=fixture_exercised,
        analog_quality_graded=analog_quality_graded,
        aperture_graded=False,
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
    *,
    minimum: int,
    maximum: int,
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
            "ADC_CAPTURE_SECONDS",
            DEFAULT_CAPTURE_SECONDS,
        )
        status_interval_seconds = _positive_float_environment(
            "ADC_STATUS_INTERVAL_SECONDS",
            DEFAULT_STATUS_INTERVAL_SECONDS,
        )
        reduced_capture_frames = _bounded_int_environment(
            "ADC_REDUCED_CAPTURE_FRAMES",
            DEFAULT_REDUCED_CAPTURE_FRAMES,
            minimum=1,
            maximum=MAX_REDUCED_CAPTURE_FRAMES,
        )
        checksum_algorithm = _checksum_environment(
            "ADC_CHECKSUM_ALGORITHM",
            DEFAULT_DATA_CHECKSUM,
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
        fixture_declared=fixture is not None,
        port=port_name,
        protocol=PROTOCOL_VERSION,
        reduced_capture_frames=reduced_capture_frames,
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
            reduced_capture_frames=reduced_capture_frames,
            checksum_algorithm=checksum_algorithm,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
            fixture=fixture,
        )
    finally:
        port.close()
    summary = {
        "analog_aperture": "GRADED" if result.aperture_graded else "NOT_GRADED",
        "analog_quality": ("GRADED" if result.analog_quality_graded else "NOT_GRADED"),
        "checks": result.evidence.check_count,
        "failures": result.evidence.failures,
        "fixture_stimulus": (
            "EXERCISED" if result.fixture_stimulus_exercised else "NOT_EXERCISED"
        ),
        "result": "PASS" if not result.evidence.failures else "FAIL",
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if not result.evidence.failures else 1


if __name__ == "__main__":
    sys.exit(main())
