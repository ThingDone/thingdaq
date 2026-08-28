#!/usr/bin/env python3
"""Independent Phase 04 full-rate synthetic-stream hardware acceptance.

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
MAX_CAPTURE_SECONDS = 3600.0
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
MAX_CONTROL_FRAME_BYTES = 1024
MAX_FRAME_BYTES = DATA_FRAME_BYTES
CHECKSUM_ADLER32 = 1

TIMESTAMP_HZ = 8_000_000
ADC_PAIR_RATE_HZ = 1_000_000
ADC_PAIR_PERIOD_TICKS = 8
ADC1_PHASE_TICKS = 4
ADC_RESOLUTION_BITS = 12
ADC_CONTAINER_BYTES = 2
ADC_BYTES_PER_PAIR = 4
ADC_PAIRS_PER_FRAME = 1012
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4048
GPIO_PINS_BY_BIT = tuple(range(6, 14))
FRAME_COVERAGE_TICKS = 8096

ADC_DATA = 0x01
GPIO_DATA = 0x02
INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
PING_REQUEST = 0x16
INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
PING_RESPONSE = 0x96
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
CAPABILITY_SYNTHETIC_SOURCE = 8
CAPABILITY_RESET_STATS = 16
CAPABILITY_PING = 32
EXPECTED_CAPABILITIES = (
    CAPABILITY_ADC_STREAM
    | CAPABILITY_GPIO_STREAM
    | CAPABILITY_SYNTHETIC_SOURCE
    | CAPABILITY_RESET_STATS
    | CAPABILITY_PING
)

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
    PING_REQUEST: PING_RESPONSE,
}
REQUEST_PAYLOAD_SIZE = {
    INFO_REQUEST: 0,
    CONFIGURE_REQUEST: 8,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
    PING_REQUEST: 8,
}
SUCCESS_PAYLOAD_SIZE = {
    INFO_RESPONSE: 98,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 56,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    PING_RESPONSE: 12,
    ERROR_RESPONSE: 8,
}
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE)

TARGET_ADC_PAYLOAD_BYTES_PER_SECOND = ADC_PAIR_RATE_HZ * ADC_BYTES_PER_PAIR
TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND = GPIO_SAMPLE_RATE_HZ
TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND = (
    TARGET_ADC_PAYLOAD_BYTES_PER_SECOND + TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND
)
TARGET_COMBINED_FRAMED_BYTES_PER_SECOND = (
    2 * DATA_FRAME_BYTES * TIMESTAMP_HZ / FRAME_COVERAGE_TICKS
)


class ProtocolFailure(RuntimeError):
    """The rig observed an invalid or unexpected wire event."""


class DeadlineExpired(ProtocolFailure):
    """A finite serial operation did not complete by its deadline."""


class SerialPort(Protocol):
    """The narrow pyserial surface used by this self-contained program."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Frame:
    """One independently validated wire frame."""

    kind: int
    flags: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    payload: bytes
    checksum: int


@dataclass(frozen=True)
class StatusSnapshot:
    """The protocol-v1 STATUS fields used for continuous reconciliation."""

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
    """Validated totals and next expected header values for one stream."""

    expected_sequence: int = 0
    expected_ticks: int = 0
    frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0


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
        CHECKSUM_ADLER32,
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
    return body + TRAILER.pack(zlib.adler32(body) & 0xFFFFFFFF)


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
            expected = zlib.adler32(self.buffer[:payload_end]) & 0xFFFFFFFF
            actual = TRAILER.unpack_from(self.buffer, payload_end)[0]
            if actual != expected:
                self.checksum_errors += 1
                self._discard(1)
                continue
            frame = Frame(
                kind=fields[2],
                flags=fields[3],
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
        if header_length != HEADER_SIZE or checksum != CHECKSUM_ADLER32 or reserved:
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
            if payload[1] or payload[45] or payload[61]:
                raise ProtocolFailure("INFO reserved fields are nonzero")
        elif frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            if payload[1] or payload[7]:
                raise ProtocolFailure("configuration response reserved byte is nonzero")
        elif frame.kind == GET_STATUS_RESPONSE:
            if payload[1]:
                raise ProtocolFailure("STATUS reserved field is nonzero")
        elif frame.kind == STOP_RESPONSE:
            if payload[1] or any(payload[5:]):
                raise ProtocolFailure("STOP reserved fields are nonzero")
        elif frame.kind == RESET_STATS_RESPONSE:
            if payload[1]:
                raise ProtocolFailure("RESET_STATS reserved byte is nonzero")
        elif frame.kind == PING_RESPONSE:
            if payload[1]:
                raise ProtocolFailure("PING reserved byte is nonzero")
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
            frame, _latency = link.exchange(
                INFO_REQUEST,
                timeout=SYNC_DEADLINE_SECONDS,
            )
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


def grade_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> None:
    exact = {
        "device_state": STATE_IDLE,
        "protocol_version": PROTOCOL_VERSION,
        "supported_stream_mask": STREAM_BOTH,
        "supported_source_mask": 1 << SOURCE_SYNTHETIC,
        "supported_checksum_mask": 1 << CHECKSUM_ADLER32,
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
        "firmware_version": (0, 4, 0),
        "board_id": 1,
        "mcu_id": 1,
    }
    for name, expected in exact.items():
        evidence.equal(f"identity.{name}", expected, info[name])

    hardware_serial = info["hardware_serial"]
    if expected_hardware_serial is None:
        evidence.check(
            "identity.hardware_serial",
            "nonzero uint32",
            hardware_serial,
            isinstance(hardware_serial, int)
            and not isinstance(hardware_serial, bool)
            and 1 <= hardware_serial <= 0xFFFFFFFF,
        )
    else:
        evidence.equal(
            "identity.hardware_serial", expected_hardware_serial, hardware_serial
        )

    build_id = info["build_id"]
    if expected_build_id is None:
        evidence.check(
            "identity.build_id",
            "tdaq-<16 lowercase hex>",
            build_id,
            isinstance(build_id, str)
            and re.fullmatch(r"tdaq-[0-9a-f]{16}", build_id) is not None,
        )
    else:
        evidence.equal("identity.build_id", expected_build_id, build_id)


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
GPIO_PATTERN = bytes(range(256))
GPIO_PATTERN_EXPANDED = GPIO_PATTERN * 17


class SyntheticValidator:
    """Continuously validate both formulas and all epoch continuity fields."""

    def __init__(self, run_id: int) -> None:
        if not 1 <= run_id <= 0xFFFFFFFF:
            raise ValueError("run ID must be a nonzero uint32")
        self.run_id = run_id
        self.adc = StreamTotals()
        self.gpio = StreamTotals()
        self.first_receive_time: float | None = None
        self.last_receive_time: float | None = None

    def accept(self, frame: Frame) -> None:
        received_at = time.monotonic()
        if self.first_receive_time is None:
            self.first_receive_time = received_at
        self.last_receive_time = received_at
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"data run ID is {frame.run_id}; expected {self.run_id}"
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
                f"kind 0x{frame.kind:02x} timestamp is {frame.first_sample_ticks}; "
                f"expected {totals.expected_ticks}"
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
            expected_adc0 = (2 * pair_index) & 0xFFF
            expected_adc1 = (2 * pair_index + 1) & 0xFFF
            if (observed_adc0, observed_adc1) != (expected_adc0, expected_adc1):
                raise ProtocolFailure(
                    f"ADC pair {pair_index} is ({observed_adc0}, {observed_adc1}); "
                    f"expected ({expected_adc0}, {expected_adc1})"
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
            expected_sample = sample_index & 0xFF
            if observed != expected_sample:
                raise ProtocolFailure(
                    f"GPIO sample {sample_index} is {observed}; "
                    f"expected {expected_sample}"
                )
        raise ProtocolFailure("GPIO payload differs despite matching decoded samples")


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
    """Return portable-enough peak RSS bytes for the Linux remote rig."""

    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1024)


def current_rss_bytes() -> int:
    """Return current Linux RSS, falling back to the process peak elsewhere."""

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
        CHECKSUM_ADLER32,
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
            "running STATUS reports loss/error counters: "
            f"adc_drop={status.adc_items_dropped} "
            f"gpio_drop={status.gpio_items_dropped} "
            f"parser={status.parser_errors} transport={status.transport_errors}"
        )
    adc_received_before, gpio_received_before = received_frames_before_request
    if status.adc_frames_emitted < adc_received_before:
        raise ProtocolFailure(
            "firmware ADC counter trails frames received before STATUS request"
        )
    if status.gpio_frames_emitted < gpio_received_before:
        raise ProtocolFailure(
            "firmware GPIO counter trails frames received before STATUS request"
        )


def _relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / expected


def grade_final_metrics(
    evidence: Evidence,
    *,
    capture_elapsed: float,
    final_frame: Frame,
    final_status: StatusSnapshot,
    validator: SyntheticValidator,
    link: SerialLink,
    parser_errors_at_start: int,
    status_latencies: list[float],
    minimum_status_samples: int,
    memory: MemoryTracker,
) -> None:
    evidence.equal("final.state", STATE_IDLE, final_status.device_state)
    evidence.equal("final.run_id", validator.run_id, final_frame.run_id)
    evidence.equal(
        "final.adc_frames_emitted",
        validator.adc.frames,
        final_status.adc_frames_emitted,
    )
    evidence.equal(
        "final.gpio_frames_emitted",
        validator.gpio.frames,
        final_status.gpio_frames_emitted,
    )
    evidence.equal("final.adc_items_dropped", 0, final_status.adc_items_dropped)
    evidence.equal("final.gpio_items_dropped", 0, final_status.gpio_items_dropped)
    evidence.equal("final.firmware_parser_errors", 0, final_status.parser_errors)
    evidence.equal("final.transport_errors", 0, final_status.transport_errors)
    evidence.check(
        "stream.frame_balance",
        "ADC/GPIO frame-count difference <= 1",
        {"adc": validator.adc.frames, "gpio": validator.gpio.frames},
        abs(validator.adc.frames - validator.gpio.frames) <= 1,
    )
    evidence.check(
        "stream.nonempty_both",
        "at least one frame per source",
        {"adc": validator.adc.frames, "gpio": validator.gpio.frames},
        validator.adc.frames > 0 and validator.gpio.frames > 0,
    )

    evidence.equal(
        "stream.adc_items",
        validator.adc.frames * ADC_PAIRS_PER_FRAME,
        validator.adc.items,
    )
    evidence.equal(
        "stream.gpio_items",
        validator.gpio.frames * GPIO_SAMPLES_PER_FRAME,
        validator.gpio.items,
    )
    evidence.equal(
        "stream.adc_payload_bytes",
        validator.adc.frames * DATA_PAYLOAD_BYTES,
        validator.adc.payload_bytes,
    )
    evidence.equal(
        "stream.gpio_payload_bytes",
        validator.gpio.frames * DATA_PAYLOAD_BYTES,
        validator.gpio.payload_bytes,
    )

    adc_rate = validator.adc.payload_bytes / capture_elapsed
    gpio_rate = validator.gpio.payload_bytes / capture_elapsed
    payload_rate = (validator.adc.payload_bytes + validator.gpio.payload_bytes) / (
        capture_elapsed
    )
    framed_rate = (validator.adc.framed_bytes + validator.gpio.framed_bytes) / (
        capture_elapsed
    )
    evidence.check(
        "throughput.adc_payload_bytes_per_second",
        {
            "target": TARGET_ADC_PAYLOAD_BYTES_PER_SECOND,
            "tolerance_fraction": RATE_TOLERANCE_FRACTION,
        },
        adc_rate,
        _relative_error(adc_rate, TARGET_ADC_PAYLOAD_BYTES_PER_SECOND)
        <= RATE_TOLERANCE_FRACTION,
    )
    evidence.check(
        "throughput.gpio_payload_bytes_per_second",
        {
            "target": TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND,
            "tolerance_fraction": RATE_TOLERANCE_FRACTION,
        },
        gpio_rate,
        _relative_error(gpio_rate, TARGET_GPIO_PAYLOAD_BYTES_PER_SECOND)
        <= RATE_TOLERANCE_FRACTION,
    )
    evidence.check(
        "throughput.combined_payload_bytes_per_second",
        {
            "target": TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND,
            "tolerance_fraction": RATE_TOLERANCE_FRACTION,
        },
        payload_rate,
        _relative_error(payload_rate, TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND)
        <= RATE_TOLERANCE_FRACTION,
    )
    evidence.check(
        "throughput.combined_framed_bytes_per_second",
        {
            "target": TARGET_COMBINED_FRAMED_BYTES_PER_SECOND,
            "tolerance_fraction": RATE_TOLERANCE_FRACTION,
        },
        framed_rate,
        _relative_error(framed_rate, TARGET_COMBINED_FRAMED_BYTES_PER_SECOND)
        <= RATE_TOLERANCE_FRACTION,
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
    data_frames = validator.adc.frames + validator.gpio.frames
    evidence.check(
        "host.checksummed_frames",
        f">= {data_frames} validated data frames",
        link.parser.frames_decoded,
        link.parser.frames_decoded >= data_frames,
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
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
) -> Evidence:
    """Run one bounded full-rate epoch and leave the board in IDLE."""

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
    evidence = Evidence()
    link = SerialLink(port)
    completed = False
    validator: SyntheticValidator | None = None
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
        if evidence.failures:
            raise ProtocolFailure("identity/capability grading failed")

        parser_errors_at_start = link.parser.errors
        requested_configuration = CONFIGURATION.pack(
            STREAM_BOTH,
            SOURCE_SYNTHETIC,
            CHECKSUM_ADLER32,
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
        evidence.equal(
            "configure.applied",
            (STREAM_BOTH, SOURCE_SYNTHETIC, CHECKSUM_ADLER32, DATA_FRAME_BYTES),
            decode_configuration(configured_frame, CONFIGURE_RESPONSE),
        )

        configured_status_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        configured_status = decode_status(configured_status_frame)
        evidence.equal(
            "configure.state", STATE_CONFIGURED, configured_status.device_state
        )
        evidence.check(
            "configure.stats_generation",
            "nonzero uint32",
            configured_status.stats_generation,
            1 <= configured_status.stats_generation <= 0xFFFFFFFF,
        )

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
            (STREAM_BOTH, SOURCE_SYNTHETIC, CHECKSUM_ADLER32, DATA_FRAME_BYTES),
            decode_configuration(start_frame, START_RESPONSE),
        )
        validator = SyntheticValidator(start_frame.run_id)
        for frame in deferred_data:
            validator.accept(frame)

        memory = MemoryTracker()
        active_started = time.monotonic()
        capture_deadline = active_started + capture_seconds
        next_status_at = active_started
        status_latencies: list[float] = []
        stats_generation: int | None = None
        status_count = 0

        while time.monotonic() < capture_deadline:
            now = time.monotonic()
            if now >= next_status_at:
                # One serial read may contain the STATUS response followed by
                # newer data, so grade its snapshot against the pre-request floor.
                received_frames_before_request = (
                    validator.adc.frames,
                    validator.gpio.frames,
                )
                status_frame, latency = link.exchange(
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
                    evidence.equal(
                        "start.stats_generation",
                        expected_generation,
                        stats_generation,
                    )
                validate_running_status(
                    status,
                    status_frame,
                    validator,
                    stats_generation,
                    received_frames_before_request,
                )
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
            "final.stats_generation",
            stats_generation,
            final_status.stats_generation,
        )
        minimum_status_samples = max(
            1,
            int(capture_seconds / status_interval_seconds),
        )
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
        )
        emit_event(
            "capture_complete",
            capture_elapsed_seconds=capture_elapsed,
            status_requests=status_count,
            adc_frames=validator.adc.frames,
            gpio_frames=validator.gpio.frames,
            adc_items=validator.adc.items,
            gpio_items=validator.gpio.items,
            payload_bytes=validator.adc.payload_bytes + validator.gpio.payload_bytes,
            framed_bytes=validator.adc.framed_bytes + validator.gpio.framed_bytes,
        )
        completed = not evidence.failures
    except Exception as error:  # noqa: BLE001 - stdout is the remote diagnosis
        message = f"{type(error).__name__}: {error}"
        emit_event("fatal", error=message)
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
    return evidence


def _positive_environment(name: str, default: float) -> float:
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


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        emit_event("configuration_error", error="SERIAL_PORT is required")
        return 2
    try:
        capture_seconds = _positive_environment(
            "SYNTHETIC_CAPTURE_SECONDS",
            DEFAULT_CAPTURE_SECONDS,
        )
        status_interval_seconds = _positive_environment(
            "SYNTHETIC_STATUS_INTERVAL_SECONDS",
            DEFAULT_STATUS_INTERVAL_SECONDS,
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
        port=port_name,
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
    except Exception as error:  # noqa: BLE001 - print the rig-visible open failure
        emit_event(
            "open_failed",
            error=f"{type(error).__name__}: {error}",
        )
        return 2
    try:
        evidence = run_acceptance(
            port,
            capture_seconds=capture_seconds,
            status_interval_seconds=status_interval_seconds,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
    finally:
        port.close()
    summary = {
        "checks": evidence.check_count,
        "failures": evidence.failures,
        "result": "PASS" if not evidence.failures else "FAIL",
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if not evidence.failures else 1


if __name__ == "__main__":
    sys.exit(main())
