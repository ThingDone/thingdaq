#!/usr/bin/env python3
"""Standalone protected D16-D23 to D6-D13 loopback campaign.

The remote runner uploads this file by itself to a network-disabled Python
container.  It intentionally uses only the Python standard library and
PySerial and embeds every protocol-v2 value that it validates.

Driving is fail-closed.  ``AUX_OUTPUT_FIXTURE_JSON`` must contain exactly one
of the supported machine-readable declarations before OUTPUT_ARM or START can
be written.  Protected loopback uses this shape::

    {
      "schema_version": 1,
      "hardware_serial": 20512460,
      "connections": [
        {"output_pin": 16, "input_pin": 6,
         "series_resistance_ohms": 470},
        ... one ordered entry through D23-to-D13 ...
      ],
      "io_voltage_volts": 3.3,
      "external_drivers": false,
      "authorized_profiles": [
        "teensy40-d16-d23-to-d6-d13-1mhz-v1"
      ]
    }

An explicitly unconnected smoke test uses the same fields, but declares an
empty ``connections`` array and authorizes only
``teensy40-d16-d23-unconnected-smoke-v1``.  That mode validates the output
lifecycle and internal counters without grading physical pin values.

The declaration is compared with the hardware serial returned by INFO.  Logs
contain only its SHA-256 identity and interlock result, never its raw content.
Loopback is self-observation and is not evidence of pad voltage, edge timing,
jitter, or signal integrity; an independent instrument is still required.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import sys
import time
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

import serial

try:
    import resource
except ImportError:  # pragma: no cover - remote service runs Linux
    resource = None  # type: ignore[assignment]


RESULT_PREFIX = "AUX_OUTPUT_LOOPBACK_RESULT "
EVENT_PREFIX = "AUX_OUTPUT_LOOPBACK_EVENT "
RESULT_SCHEMA_VERSION = 1
EXPERIMENT_ID = "aux-output-bank"
PROFILE_ID = "teensy40-d16-d23-to-d6-d13-1mhz-v1"
UNCONNECTED_PROFILE_ID = "teensy40-d16-d23-unconnected-smoke-v1"
FIXTURE_SCHEMA_VERSION = 1
OUTPUT_PINS = tuple(range(16, 24))
INPUT_PINS = tuple(range(6, 14))
OUTPUT_GPIO_BITS = (23, 22, 17, 16, 26, 27, 24, 25)
MIN_SERIES_RESISTANCE_OHMS = 100
MAX_SERIES_RESISTANCE_OHMS = 10_000
MAX_FIXTURE_BYTES = 16_384
# A submitted one-file runner may replace this with an exact declaration when
# its service cannot inject environment variables.  The checked-in default is
# deliberately non-authorizing.
EMBEDDED_FIXTURE_DECLARATION: str | None = None

BAUD_RATE = 115_200
SERIAL_TIMEOUT_SECONDS = 0.02
WRITE_TIMEOUT_SECONDS = 0.5
SERIAL_READ_BYTES = 64 * 1024
STARTUP_DRAIN_SECONDS = 0.25
REOPEN_SETTLE_SECONDS = 0.25
COMMAND_DEADLINE_SECONDS = 0.75
STOP_DRAIN_DEADLINE_SECONDS = 3.0
STOP_DRAIN_QUIET_SECONDS = 0.10
STATUS_INTERVAL_SECONDS = 0.10
HOLD_OBSERVATION_SECONDS = 0.01
STATUS_P99_LIMIT_SECONDS = 0.100
STATUS_MAX_LIMIT_SECONDS = 0.250
MAX_LOOPBACK_LAG_TICKS = 64
MAX_CAPTURE_SECONDS = 900.0
MAX_HOST_STALL_SECONDS = 0.075
MAX_RSS_GROWTH_BYTES = 32 * 1024 * 1024

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
ACQUISITION_PROTOCOL_VERSION = 1
PROTOCOL_VERSION = 2
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
SUPPORTED_CHECKSUMS = frozenset(
    {CHECKSUM_ADLER32, CHECKSUM_CRC32C, CHECKSUM_CRC32_ISO_HDLC}
)

TIMESTAMP_HZ = 8_000_000
ADC_PAIR_RATE_HZ = 1_000_000
ADC_PAIR_PERIOD_TICKS = 8
ADC1_PHASE_TICKS = 4
ADC_PAIRS_PER_FRAME = 1012
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4048
FRAME_COVERAGE_TICKS = 8096
OUTPUT_RATE_HZ = 1_000_000
OUTPUT_PERIOD_TICKS = 8
OUTPUT_CAPACITY_SEGMENTS = 1024
OUTPUT_LEGAL_STATE_MASK = 0xFF
OUTPUT_REPEAT_FOREVER = 0

ADC_DATA = 0x01
GPIO_DATA = 0x02
INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
OUTPUT_BEGIN_REQUEST = 0x20
OUTPUT_APPEND_REQUEST = 0x21
OUTPUT_COMMIT_REQUEST = 0x22
OUTPUT_ARM_REQUEST = 0x23
OUTPUT_STATUS_REQUEST = 0x24
OUTPUT_CLEAR_REQUEST = 0x25

INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
OUTPUT_BEGIN_RESPONSE = 0xA0
OUTPUT_APPEND_RESPONSE = 0xA1
OUTPUT_COMMIT_RESPONSE = 0xA2
OUTPUT_ARM_RESPONSE = 0xA3
OUTPUT_STATUS_RESPONSE = 0xA4
OUTPUT_CLEAR_RESPONSE = 0xA5
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
STREAM_BOTH = 3
SOURCE_HARDWARE = 0
OUTPUT_BANK_DISABLED = 0
OUTPUT_BANK_ENABLED = 1
OUTPUT_EMPTY = 0
OUTPUT_LOADING = 1
OUTPUT_COMMITTED = 2
OUTPUT_ARMED = 3
OUTPUT_RUNNING = 4
OUTPUT_HELD = 5
OUTPUT_FAULTED = 6
OUTPUT_ERROR_NONE = 0
OUTPUT_ERROR_UNDERRUN = 7
CAPABILITY_PRELOADED_OUTPUT = 1 << 9
CAPABILITY_COMMON_EPOCH_OUTPUT = 1 << 10
REQUIRED_OUTPUT_CAPABILITIES = (
    CAPABILITY_PRELOADED_OUTPUT | CAPABILITY_COMMON_EPOCH_OUTPUT
)

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
TRAILER = struct.Struct("<I")
RESPONSE_PREFIX = struct.Struct("<BBH")
CONFIGURATION = struct.Struct("<BBBBI")
SEGMENT = struct.Struct("<II")

REQUEST_RESPONSE_KIND = {
    INFO_REQUEST: INFO_RESPONSE,
    CONFIGURE_REQUEST: CONFIGURE_RESPONSE,
    START_REQUEST: START_RESPONSE,
    GET_STATUS_REQUEST: GET_STATUS_RESPONSE,
    STOP_REQUEST: STOP_RESPONSE,
    RESET_STATS_REQUEST: RESET_STATS_RESPONSE,
    OUTPUT_BEGIN_REQUEST: OUTPUT_BEGIN_RESPONSE,
    OUTPUT_APPEND_REQUEST: OUTPUT_APPEND_RESPONSE,
    OUTPUT_COMMIT_REQUEST: OUTPUT_COMMIT_RESPONSE,
    OUTPUT_ARM_REQUEST: OUTPUT_ARM_RESPONSE,
    OUTPUT_STATUS_REQUEST: OUTPUT_STATUS_RESPONSE,
    OUTPUT_CLEAR_REQUEST: OUTPUT_CLEAR_RESPONSE,
}
REQUEST_PAYLOAD_SIZE = {
    INFO_REQUEST: 0,
    CONFIGURE_REQUEST: 8,
    START_REQUEST: 0,
    GET_STATUS_REQUEST: 0,
    STOP_REQUEST: 0,
    RESET_STATS_REQUEST: 0,
    OUTPUT_BEGIN_REQUEST: 8,
    OUTPUT_APPEND_REQUEST: 8,
    OUTPUT_COMMIT_REQUEST: 8,
    OUTPUT_ARM_REQUEST: 0,
    OUTPUT_STATUS_REQUEST: 0,
    OUTPUT_CLEAR_REQUEST: 0,
}
SUCCESS_PAYLOAD_SIZE = {
    INFO_RESPONSE: 412,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 1228,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    OUTPUT_BEGIN_RESPONSE: 224,
    OUTPUT_APPEND_RESPONSE: 16,
    OUTPUT_COMMIT_RESPONSE: 224,
    OUTPUT_ARM_RESPONSE: 224,
    OUTPUT_STATUS_RESPONSE: 224,
    OUTPUT_CLEAR_RESPONSE: 224,
    ERROR_RESPONSE: 8,
}
OUTPUT_STATUS_RESPONSE_KINDS = frozenset(
    {
        OUTPUT_BEGIN_RESPONSE,
        OUTPUT_COMMIT_RESPONSE,
        OUTPUT_ARM_RESPONSE,
        OUTPUT_STATUS_RESPONSE,
        OUTPUT_CLEAR_RESPONSE,
    }
)
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE)
DRIVE_COMMAND_KINDS = frozenset({OUTPUT_ARM_REQUEST, START_REQUEST})
V2_REQUEST_KINDS = frozenset(
    {
        INFO_REQUEST,
        OUTPUT_BEGIN_REQUEST,
        OUTPUT_APPEND_REQUEST,
        OUTPUT_COMMIT_REQUEST,
        OUTPUT_ARM_REQUEST,
        OUTPUT_STATUS_REQUEST,
        OUTPUT_CLEAR_REQUEST,
    }
)
V2_RESPONSE_KINDS = frozenset(
    {
        INFO_RESPONSE,
        OUTPUT_BEGIN_RESPONSE,
        OUTPUT_APPEND_RESPONSE,
        OUTPUT_COMMIT_RESPONSE,
        OUTPUT_ARM_RESPONSE,
        OUTPUT_STATUS_RESPONSE,
        OUTPUT_CLEAR_RESPONSE,
    }
)


class CampaignFailure(RuntimeError):
    """A bounded safety, protocol, or acceptance failure."""


class DeadlineExpired(CampaignFailure):
    """A serial or campaign deadline expired."""


class InterlockDenied(CampaignFailure):
    """A drive command was refused before serial transmission."""


def emit_event(name: str, **fields: object) -> None:
    """Emit bounded, sorted JSON without fixture content or credentials."""

    record = {"event": name, **fields}
    print(EVENT_PREFIX + json.dumps(record, sort_keys=True, separators=(",", ":")))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CampaignFailure(message)


def _u16(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", payload, offset)[0])


def _u32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", payload, offset)[0])


def _u64(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<Q", payload, offset)[0])


def _crc_table(polynomial: int) -> tuple[int, ...]:
    values: list[int] = []
    for index in range(256):
        remainder = index
        for _ in range(8):
            remainder = (remainder >> 1) ^ (polynomial if remainder & 1 else 0)
        values.append(remainder)
    return tuple(values)


CRC32C_TABLE = _crc_table(0x82F63B78)


def compute_checksum(data: bytes | bytearray | memoryview, algorithm: int) -> int:
    if algorithm == CHECKSUM_ADLER32:
        return zlib.adler32(data, 1) & 0xFFFFFFFF
    if algorithm == CHECKSUM_CRC32_ISO_HDLC:
        return zlib.crc32(data, 0) & 0xFFFFFFFF
    if algorithm == CHECKSUM_CRC32C:
        remainder = 0xFFFFFFFF
        for value in data:
            remainder = CRC32C_TABLE[(remainder ^ value) & 0xFF] ^ (remainder >> 8)
        return remainder ^ 0xFFFFFFFF
    raise CampaignFailure("wire selected an unsupported checksum algorithm")


@dataclass(frozen=True)
class FixtureDeclaration:
    hardware_serial: int
    declaration_sha256: str
    profile_id: str = PROFILE_ID
    observation_mode: str = "loopback"


def parse_fixture_declaration(raw: str | None) -> FixtureDeclaration | None:
    """Validate the exact safety declaration without exposing its values."""

    if raw is None:
        return None
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_FIXTURE_BYTES:
        raise ValueError("fixture declaration exceeds its finite size bound")
    digest = hashlib.sha256(encoded).hexdigest()
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("fixture declaration is not valid JSON") from error
    if not isinstance(value, dict):
        raise TypeError("fixture declaration must be a JSON object")
    required_keys = {
        "schema_version",
        "hardware_serial",
        "connections",
        "io_voltage_volts",
        "external_drivers",
        "authorized_profiles",
    }
    if set(value) != required_keys:
        raise ValueError("fixture declaration fields do not match the safety schema")
    serial_value = value["hardware_serial"]
    if (
        not isinstance(serial_value, int)
        or isinstance(serial_value, bool)
        or not 1 <= serial_value <= 0xFFFFFFFF
    ):
        raise ValueError("fixture hardware identity is invalid")
    if value["schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise ValueError("fixture declaration schema is unsupported")
    voltage = value["io_voltage_volts"]
    if (
        not isinstance(voltage, (int, float))
        or isinstance(voltage, bool)
        or not math.isfinite(float(voltage))
        or float(voltage) != 3.3
    ):
        raise ValueError("fixture does not declare exact 3.3 V I/O")
    if value["external_drivers"] is not False:
        raise ValueError("fixture does not declare absence of external drivers")
    profiles = value["authorized_profiles"]
    if not isinstance(profiles, list) or profiles not in (
        [PROFILE_ID],
        [UNCONNECTED_PROFILE_ID],
    ):
        raise ValueError("fixture does not authorize one exact output profile")
    profile_id = profiles[0]
    connections = value["connections"]
    if not isinstance(connections, list):
        raise ValueError("fixture connections must be a JSON array")
    if profile_id == UNCONNECTED_PROFILE_ID:
        if connections:
            raise ValueError("unconnected smoke requires zero declared connections")
        return FixtureDeclaration(
            int(serial_value), digest, profile_id, "unconnected"
        )
    if len(connections) != 8:
        raise ValueError("fixture does not declare exactly eight loopback wires")
    for index, connection in enumerate(connections):
        if not isinstance(connection, dict) or set(connection) != {
            "output_pin",
            "input_pin",
            "series_resistance_ohms",
        }:
            raise ValueError("fixture connection does not match the safety schema")
        resistance = connection["series_resistance_ohms"]
        if (
            connection["output_pin"] != OUTPUT_PINS[index]
            or connection["input_pin"] != INPUT_PINS[index]
            or not isinstance(resistance, int)
            or isinstance(resistance, bool)
            or not MIN_SERIES_RESISTANCE_OHMS
            <= resistance
            <= MAX_SERIES_RESISTANCE_OHMS
        ):
            raise ValueError("fixture loopback order or series protection is invalid")
    return FixtureDeclaration(int(serial_value), digest, profile_id, "loopback")


@dataclass(frozen=True)
class _DrivePermit:
    hardware_serial: int
    declaration_sha256: str
    owner_identity: int
    observation_mode: str


class DriveInterlock:
    """The sole creator and validator of permits accepted by drive writes."""

    def __init__(self, declaration: FixtureDeclaration | None) -> None:
        self._declaration = declaration
        self._identity = id(self)

    @property
    def declaration_sha256(self) -> str | None:
        return (
            None if self._declaration is None else self._declaration.declaration_sha256
        )

    def authorize(self, observed_hardware_serial: int) -> _DrivePermit:
        declaration = self._declaration
        if declaration is None:
            raise InterlockDenied("no fixture declaration was supplied")
        if declaration.hardware_serial != observed_hardware_serial:
            raise InterlockDenied("fixture and INFO hardware identities do not match")
        return _DrivePermit(
            observed_hardware_serial,
            declaration.declaration_sha256,
            self._identity,
            declaration.observation_mode,
        )

    def validate(self, permit: _DrivePermit | None) -> None:
        declaration = self._declaration
        if (
            declaration is None
            or not isinstance(permit, _DrivePermit)
            or permit.owner_identity != self._identity
            or permit.hardware_serial != declaration.hardware_serial
            or permit.declaration_sha256 != declaration.declaration_sha256
            or permit.observation_mode != declaration.observation_mode
        ):
            raise InterlockDenied("drive command refused by fixture interlock")


class SerialPort(Protocol):
    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Frame:
    kind: int
    flags: int
    checksum_algorithm: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    payload: bytes


def encode_request(
    kind: int,
    request_id: int,
    payload: bytes = b"",
    *,
    run_id: int = 0,
) -> bytes:
    if kind not in REQUEST_PAYLOAD_SIZE:
        raise ValueError("unknown request kind")
    if len(payload) != REQUEST_PAYLOAD_SIZE[kind]:
        raise ValueError("request payload has the wrong fixed size")
    if not 1 <= request_id <= 0xFFFFFFFF:
        raise ValueError("request ID must be a nonzero u32")
    if not 0 <= run_id <= 0xFFFFFFFF:
        raise ValueError("run ID must be a u32")
    total = HEADER_SIZE + len(payload) + TRAILER_SIZE
    header = HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION if kind in V2_REQUEST_KINDS else ACQUISITION_PROTOCOL_VERSION,
        kind,
        0,
        HEADER_SIZE,
        BOOTSTRAP_CHECKSUM,
        0,
        total,
        len(payload),
        run_id,
        0,
        request_id,
        0,
        0,
    )
    body = header + payload
    return body + TRAILER.pack(compute_checksum(body, BOOTSTRAP_CHECKSUM))


class FrameParser:
    """Bounded resynchronizing parser for control plus both data streams."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.bytes_received = 0
        self.bytes_discarded = 0
        self.frames_decoded = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.high_water_bytes = 0

    @property
    def errors(self) -> int:
        return self.header_errors + self.checksum_errors + self.payload_errors

    def feed(self, data: bytes) -> list[Frame]:
        self.bytes_received += len(data)
        self.buffer.extend(data)
        self.high_water_bytes = max(self.high_water_bytes, len(self.buffer))
        frames: list[Frame] = []
        while True:
            position = self.buffer.find(MAGIC_BYTES)
            if position < 0:
                retained = self._partial_magic_suffix()
                self._discard(len(self.buffer) - retained)
                break
            self._discard(position)
            if len(self.buffer) < HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.buffer)
            try:
                total = self._validate_header(fields)
            except CampaignFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            if len(self.buffer) < total:
                break
            payload_length = fields[8]
            payload_end = HEADER_SIZE + payload_length
            expected = compute_checksum(
                memoryview(self.buffer)[:payload_end], fields[5]
            )
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
            )
            try:
                self._validate_payload(frame)
            except CampaignFailure:
                self.payload_errors += 1
                self._discard(1)
                continue
            del self.buffer[:total]
            self.frames_decoded += 1
            frames.append(frame)
        retained_bound = MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1
        require(len(self.buffer) <= retained_bound, "parser retention bound exceeded")
        require(
            self.high_water_bytes <= SERIAL_READ_BYTES + retained_bound,
            "parser memory high-water bound exceeded",
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
            total,
            payload_length,
            run_id,
            sequence,
            request_id,
            first_ticks,
            item_count,
        ) = fields
        require(magic == MAGIC, "bad frame magic")
        require(header_length == HEADER_SIZE and reserved == 0, "bad fixed header")
        require(total == HEADER_SIZE + payload_length + TRAILER_SIZE, "bad length")
        if kind in DATA_KINDS:
            require(
                version == ACQUISITION_PROTOCOL_VERSION,
                "data frame protocol version mismatch",
            )
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            period = (
                ADC_PAIR_PERIOD_TICKS if kind == ADC_DATA else GPIO_SAMPLE_PERIOD_TICKS
            )
            require(checksum in SUPPORTED_CHECKSUMS, "bad data checksum selection")
            require(
                total == DATA_FRAME_BYTES and payload_length == DATA_PAYLOAD_BYTES,
                "bad fixed data frame shape",
            )
            require(flags & ~DATA_FLAG_MASK == 0, "data frame has reserved flags")
            require(
                not flags & FLAG_SYNTHETIC, "physical campaign received synthetic data"
            )
            require(
                not flags & FLAG_OVERRUN_BEFORE or bool(flags & FLAG_GAP_BEFORE),
                "overrun flag lacks gap flag",
            )
            require(run_id != 0 and request_id == 0, "bad data correlation fields")
            require(item_count == expected_items, "bad data item count")
            require(first_ticks % period == 0, "unaligned data timestamp")
            require(
                bool(flags & FLAG_EPOCH_START) == (sequence == 0 and first_ticks == 0),
                "epoch flag disagrees with sequence or timestamp",
            )
            return total
        require(kind in RESPONSE_KINDS, "unexpected device frame kind")
        require(
            version in (ACQUISITION_PROTOCOL_VERSION, PROTOCOL_VERSION)
            if kind == ERROR_RESPONSE
            else version
            == (
                PROTOCOL_VERSION
                if kind in V2_RESPONSE_KINDS
                else ACQUISITION_PROTOCOL_VERSION
            ),
            "control response protocol version mismatch",
        )
        require(checksum == BOOTSTRAP_CHECKSUM, "control checksum is not bootstrap")
        require(flags in (0, FLAG_RESPONSE_ERROR), "bad response flags")
        require(request_id != 0 and sequence == 0, "bad response correlation")
        require(first_ticks == 0 and item_count == 0, "response has data-only fields")
        require(
            HEADER_SIZE + TRAILER_SIZE <= total <= MAX_CONTROL_FRAME_BYTES,
            "control response exceeds bound",
        )
        if flags == FLAG_RESPONSE_ERROR and kind in OUTPUT_STATUS_RESPONSE_KINDS | {
            OUTPUT_APPEND_RESPONSE
        }:
            expected_payload = 224
        elif flags == FLAG_RESPONSE_ERROR and kind != ERROR_RESPONSE:
            expected_payload = 4
        else:
            expected_payload = SUCCESS_PAYLOAD_SIZE[kind]
        require(payload_length == expected_payload, "response payload size mismatch")
        return total

    @staticmethod
    def _validate_payload(frame: Frame) -> None:
        if frame.kind in DATA_KINDS:
            return
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == FLAG_RESPONSE_ERROR
        require(reserved == 0, "response reserved prefix is nonzero")
        require(is_error == (status == 1), "response error flag/status mismatch")
        require((error == 0) != is_error, "response error code mismatch")
        require(error <= 12, "response contains unknown error code")
        if frame.kind == INFO_RESPONSE and not is_error:
            for start, end in (
                (61, 62),
                (118, 120),
                (127, 128),
                (154, 156),
                (182, 184),
                (230, 232),
                (334, 336),
            ):
                require(
                    not any(frame.payload[start:end]), "INFO reserved field nonzero"
                )
        if frame.kind == GET_STATUS_RESPONSE and not is_error:
            require(
                frame.payload[1] == 0
                and not any(frame.payload[226:228])
                and not any(frame.payload[274:276]),
                "STATUS reserved field nonzero",
            )
        if frame.kind in OUTPUT_STATUS_RESPONSE_KINDS or (
            frame.kind == OUTPUT_APPEND_RESPONSE and is_error
        ):
            require(
                frame.payload[1] == 0
                and frame.payload[7] == 0
                and not any(frame.payload[61:64])
                and not any(frame.payload[209:224]),
                "output status reserved field nonzero",
            )

    def _partial_magic_suffix(self) -> int:
        for length in range(min(len(self.buffer), 3), 0, -1):
            if self.buffer.endswith(MAGIC_BYTES[:length]):
                return length
        return 0

    def _discard(self, count: int) -> None:
        if count:
            del self.buffer[:count]
            self.bytes_discarded += count


class SerialLink:
    """One-request-at-a-time link with a non-bypassable drive interlock."""

    def __init__(self, port: SerialPort, interlock: DriveInterlock) -> None:
        self.port = port
        self.interlock = interlock
        self.parser = FrameParser()
        self.next_request_id = 1
        self.stale_responses = 0
        self.discarded_data_frames = 0
        self.maximum_read_bytes = 0
        self.requests_written = 0
        self.drive_requests_written = 0

    def drain_startup(self, duration: float = STARTUP_DRAIN_SECONDS) -> None:
        deadline = time.monotonic() + duration
        discarded = 0
        while time.monotonic() < deadline:
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
            self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
            if chunk:
                discarded += len(self.parser.feed(chunk))
        self.discarded_data_frames += discarded
        emit_event("startup_drain", discarded_frames=discarded)

    def exchange(
        self,
        kind: int,
        payload: bytes = b"",
        *,
        run_id: int = 0,
        permit: _DrivePermit | None = None,
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[Frame, float]:
        if kind in DRIVE_COMMAND_KINDS:
            self.interlock.validate(permit)
        elif permit is not None:
            raise InterlockDenied("drive permit supplied to a non-drive request")
        request_id = self._allocate_request_id()
        wire = encode_request(kind, request_id, payload, run_id=run_id)
        started = time.monotonic()
        deadline = started + timeout
        self._write_all(wire, deadline)
        self.requests_written += 1
        if kind in DRIVE_COMMAND_KINDS:
            self.drive_requests_written += 1
        expected_kind = REQUEST_RESPONSE_KIND[kind]
        while time.monotonic() < deadline:
            matched: Frame | None = None
            for frame in self._read_once():
                if frame.kind in DATA_KINDS:
                    if on_data is None:
                        self.discarded_data_frames += 1
                    else:
                        on_data(frame)
                    continue
                if frame.request_id != request_id:
                    self.stale_responses += 1
                    continue
                error_code = (
                    _u16(frame.payload, 2) if len(frame.payload) >= 4 else None
                )
                require(
                    frame.kind in (expected_kind, ERROR_RESPONSE),
                    "response kind mismatch: "
                    f"expected 0x{expected_kind:02x}, received 0x{frame.kind:02x}, "
                    f"error={error_code}",
                )
                require(matched is None, "duplicate response for one request")
                matched = frame
            if matched is not None:
                return matched, time.monotonic() - started
        raise DeadlineExpired("bounded command exchange timed out")

    def pump_once(self, on_data: Callable[[Frame], None]) -> int:
        chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        if not chunk:
            return 0
        for frame in self.parser.feed(chunk):
            require(frame.kind in DATA_KINDS, "unsolicited control response")
            on_data(frame)
        return len(chunk)

    def drain_until_quiet(self, on_data: Callable[[Frame], None]) -> None:
        deadline = time.monotonic() + STOP_DRAIN_DEADLINE_SECONDS
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            received = self.pump_once(on_data)
            if received:
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= STOP_DRAIN_QUIET_SECONDS:
                require(
                    not self.parser.buffer, "post-STOP parser retains partial frame"
                )
                return
        raise DeadlineExpired("post-STOP stream did not become quiet")

    def _read_once(self) -> list[Frame]:
        chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        return self.parser.feed(chunk) if chunk else []

    def _allocate_request_id(self) -> int:
        result = self.next_request_id
        self.next_request_id = (result + 1) & 0xFFFFFFFF or 1
        return result

    def _write_all(self, wire: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(wire):
            if time.monotonic() >= deadline:
                raise DeadlineExpired("serial write timed out")
            written = self.port.write(wire[offset:])
            if written is None:
                written = 0
            require(
                isinstance(written, int) and 0 <= written <= len(wire) - offset,
                "serial write returned an invalid count",
            )
            offset += written
            if written == 0:
                time.sleep(0.0001)


def response_success(frame: Frame, expected_kind: int) -> None:
    require(frame.kind == expected_kind and frame.flags == 0, "command was rejected")
    status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    require(status == reserved == error == 0, "success prefix is invalid")


@dataclass(frozen=True)
class DeviceInfo:
    hardware_serial: int
    build_id: str
    checksum_algorithm: int
    output_bank_mode: int


def decode_info(frame: Frame) -> DeviceInfo:
    response_success(frame, INFO_RESPONSE)
    payload = frame.payload
    build_bytes = payload[66:98]
    try:
        end = build_bytes.index(0)
        build_id = build_bytes[:end].decode("ascii")
    except (ValueError, UnicodeDecodeError) as error:
        raise CampaignFailure("INFO build identity is not canonical ASCII") from error
    require(not any(build_bytes[end + 1 :]), "INFO build identity padding is nonzero")
    capabilities = _u32(payload, 12)
    require(payload[4] == STATE_IDLE, "device is not IDLE at preflight")
    require(payload[5] == PROTOCOL_VERSION, "device is not protocol v2")
    require(payload[6] & STREAM_BOTH == STREAM_BOTH, "combined streams unavailable")
    require(
        capabilities & REQUIRED_OUTPUT_CAPABILITIES == REQUIRED_OUTPUT_CAPABILITIES,
        "output capabilities unavailable",
    )
    require(_u32(payload, 16) == TIMESTAMP_HZ, "timestamp frequency mismatch")
    require(_u32(payload, 28) == ADC_PAIR_RATE_HZ, "ADC rate mismatch")
    require(_u32(payload, 32) == GPIO_SAMPLE_RATE_HZ, "GPIO rate mismatch")
    require(_u16(payload, 36) == ADC_PAIR_PERIOD_TICKS, "ADC period mismatch")
    require(_u16(payload, 38) == ADC1_PHASE_TICKS, "ADC phase mismatch")
    require(_u16(payload, 40) == GPIO_SAMPLE_PERIOD_TICKS, "GPIO period mismatch")
    require(tuple(payload[46:54]) == INPUT_PINS, "GPIO input pin map mismatch")
    require(payload[376] == OUTPUT_BANK_DISABLED, "output bank is not safely disabled")
    require(payload[377:380] == bytes((8, 8, 1)), "output geometry mismatch")
    require(tuple(payload[380:388]) == OUTPUT_PINS, "output pin map mismatch")
    require(tuple(payload[388:396]) == OUTPUT_GPIO_BITS, "output GPIO bit map mismatch")
    require(_u32(payload, 396) == OUTPUT_RATE_HZ, "output rate mismatch")
    require(_u32(payload, 400) == OUTPUT_PERIOD_TICKS, "output period mismatch")
    require(_u32(payload, 404) == OUTPUT_CAPACITY_SEGMENTS, "output capacity mismatch")
    require(_u32(payload, 408) == OUTPUT_LEGAL_STATE_MASK, "output mask mismatch")
    checksum = payload[45]
    require(checksum in SUPPORTED_CHECKSUMS, "INFO checksum is unsupported")
    return DeviceInfo(_u32(payload, 54), build_id, checksum, payload[376])


OUTPUT_STATUS_FIELDS: dict[str, tuple[str, int]] = {
    "generation": ("I", 8),
    "idle_state_mask": ("I", 12),
    "current_state_mask": ("I", 16),
    "last_emitted_state_mask": ("I", 20),
    "repeat_count": ("I", 24),
    "completed_repeats": ("I", 28),
    "segment_count": ("I", 32),
    "accepted_segment_count": ("I", 36),
    "program_checksum": ("I", 40),
    "current_segment_index": ("I", 44),
    "ticks_elapsed": ("Q", 48),
    "transitions_emitted": ("I", 56),
    "current_segment_remaining": ("I", 64),
    "common_run_id": ("I", 68),
    "requested_duration_states": ("Q", 72),
    "states_expanded": ("Q", 80),
    "dma_states_queued": ("Q", 88),
    "dma_states_emitted": ("Q", 96),
    "held_remainder_states": ("Q", 104),
    "blocks_filled": ("Q", 112),
    "blocks_completed": ("Q", 120),
    "start_tick": ("Q", 128),
    "completion_tick": ("Q", 136),
    "hold_tick": ("Q", 144),
    "ready_depth": ("H", 152),
    "ready_high_water": ("H", 154),
    "refill_lead": ("I", 156),
    "refill_lead_high_water": ("I", 160),
    "cache_flushes": ("I", 164),
    "start_operations": ("I", 168),
    "stop_operations": ("I", 172),
    "invalid_operations": ("I", 176),
    "resource_conflicts": ("I", 180),
    "underruns": ("I", 184),
    "stale_completions": ("I", 188),
    "dma_errors": ("I", 192),
    "start_errors": ("I", 196),
    "stop_errors": ("I", 200),
    "conservation_errors": ("I", 204),
}


@dataclass(frozen=True)
class OutputStatus:
    state: int
    bank_mode: int
    fault_latched: bool
    output_error: int
    conservation_exact: bool
    values: dict[str, int]


def decode_output_status(
    frame: Frame, expected_kind: int, *, allow_error: bool = False
) -> OutputStatus:
    if allow_error:
        require(
            frame.kind == expected_kind and frame.flags == FLAG_RESPONSE_ERROR,
            "expected rejected output-status response",
        )
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        require(
            status == 1 and reserved == 0 and error != 0,
            "rejected output-status prefix is invalid",
        )
    else:
        response_success(frame, expected_kind)
    payload = frame.payload
    values = {
        name: int(struct.unpack_from("<" + kind, payload, offset)[0])
        for name, (kind, offset) in OUTPUT_STATUS_FIELDS.items()
    }
    for name in ("idle_state_mask", "current_state_mask", "last_emitted_state_mask"):
        require(
            values[name] & ~OUTPUT_LEGAL_STATE_MASK == 0,
            "output status has invalid state bits",
        )
    require(
        payload[6] in (0, 1) and payload[208] in (0, 1), "output boolean is invalid"
    )
    require(
        payload[4] <= OUTPUT_FAULTED and payload[5] <= OUTPUT_BANK_ENABLED,
        "unknown output lifecycle value",
    )
    require(payload[60] <= 9, "unknown output error")
    return OutputStatus(
        payload[4],
        payload[5],
        bool(payload[6]),
        payload[60],
        bool(payload[208]),
        values,
    )


STATUS_FIELDS: dict[str, tuple[str, int]] = {
    "adc_frames_emitted": ("Q", 12),
    "gpio_frames_emitted": ("Q", 20),
    "adc_items_dropped": ("Q", 28),
    "gpio_items_dropped": ("Q", 36),
    "parser_errors": ("I", 44),
    "transport_errors": ("I", 48),
    "gpio_samples_captured": ("Q", 56),
    "gpio_samples_framed": ("Q", 72),
    "gpio_samples_transmitted": ("Q", 80),
    "gpio_raw_samples_lost": ("Q", 88),
    "gpio_packer_samples_dropped": ("Q", 96),
    "gpio_raw_ring_overruns": ("Q", 104),
    "gpio_raw_ready_high_water": ("H", 122),
    "gpio_packed_ready_high_water": ("H", 126),
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
    "adc0_dma_results": ("Q", 384),
    "adc1_dma_results": ("Q", 392),
    "adc_pairs_captured": ("Q", 432),
    "adc_pairs_framed": ("Q", 448),
    "adc_pairs_transmitted": ("Q", 456),
    "adc_raw_pairs_lost": ("Q", 464),
    "adc_incomplete_conversions": ("Q", 480),
    "adc_overwritten_conversions": ("Q", 488),
    "adc_raw_ring_overruns": ("Q", 496),
    "adc_raw_ready_high_water": ("H", 514),
    "adc_etc_error_events": ("I", 516),
    "adc_dma_error_events": ("I", 524),
    "adc_completion_mismatches": ("I", 528),
    "adc_destination_mismatches": ("I", 532),
    "adc_schedule_exhaustions": ("I", 536),
    "adc_raw_invariant_errors": ("I", 540),
    "adc_resource_conflicts": ("I", 548),
    "adc_start_errors": ("I", 552),
    "adc_stop_errors": ("I", 556),
    "adc_packer_source_errors": ("I", 564),
    "adc_packer_pipeline_errors": ("I", 568),
    "adc_packer_chronology_errors": ("I", 572),
    "adc_frames_dropped": ("Q", 632),
    "gpio_frames_dropped": ("Q", 696),
    "packet_pool_exhaustions": ("I", 892),
    "packet_encoding_rejections": ("I", 900),
    "packet_ready_queue_rejections": ("I", 904),
    "packet_transmit_queue_rejections": ("I", 908),
    "usb_io_errors": ("I", 960),
    "usb_command_queue_high_water": ("H", 970),
    "usb_response_queue_high_water": ("H", 972),
    "packet_pressure_evictions": ("Q", 1024),
    "packet_capacity_drops_without_evictable_frame": ("Q", 1032),
    "adc_frames_dropped_after_framing": ("Q", 1076),
    "adc_frames_dropped_after_promotion": ("Q", 1084),
    "gpio_frames_dropped_after_framing": ("Q", 1092),
    "gpio_frames_dropped_after_promotion": ("Q", 1100),
    "adc_raw_gap_pairs": ("Q", 1196),
    "adc_raw_drop_pairs_projected": ("Q", 1204),
    "gpio_raw_drop_samples_projected": ("Q", 1212),
    "gpio_packer_drop_samples_projected": ("Q", 1220),
}
ACQUISITION_LOSS_FIELDS = (
    "adc_items_dropped",
    "gpio_items_dropped",
    "gpio_raw_samples_lost",
    "gpio_packer_samples_dropped",
    "gpio_raw_ring_overruns",
    "adc_raw_pairs_lost",
    "adc_incomplete_conversions",
    "adc_overwritten_conversions",
    "adc_raw_ring_overruns",
    "adc_frames_dropped",
    "gpio_frames_dropped",
    "packet_pool_exhaustions",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
    "packet_pressure_evictions",
    "packet_capacity_drops_without_evictable_frame",
    "adc_frames_dropped_after_framing",
    "adc_frames_dropped_after_promotion",
    "gpio_frames_dropped_after_framing",
    "gpio_frames_dropped_after_promotion",
    "adc_raw_gap_pairs",
    "adc_raw_drop_pairs_projected",
    "gpio_raw_drop_samples_projected",
    "gpio_packer_drop_samples_projected",
)


@dataclass(frozen=True)
class AcquisitionStatus:
    device_state: int
    stream_mask: int
    source: int
    checksum_algorithm: int
    values: dict[str, int]


def decode_acquisition_status(frame: Frame) -> AcquisitionStatus:
    response_success(frame, GET_STATUS_RESPONSE)
    payload = frame.payload
    values = {
        name: int(struct.unpack_from("<" + kind, payload, offset)[0])
        for name, (kind, offset) in STATUS_FIELDS.items()
    }
    return AcquisitionStatus(payload[4], payload[5], payload[6], payload[7], values)


@dataclass(frozen=True)
class Program:
    name: str
    segments: tuple[tuple[int, int], ...]
    repeat_count: int
    idle_state: int = 0

    def __post_init__(self) -> None:
        require(0 < len(self.segments) <= OUTPUT_CAPACITY_SEGMENTS, "bad program size")
        require(0 <= self.repeat_count <= 0xFFFFFFFF, "bad repeat count")
        require(self.idle_state & ~OUTPUT_LEGAL_STATE_MASK == 0, "bad idle state")
        previous: int | None = None
        for duration, state in self.segments:
            require(0 < duration <= 0xFFFFFFFF, "bad segment duration")
            require(state & ~OUTPUT_LEGAL_STATE_MASK == 0, "bad segment state")
            require(state != previous, "adjacent equal states are not canonical")
            previous = state

    @property
    def canonical_bytes(self) -> bytes:
        return b"".join(SEGMENT.pack(*segment) for segment in self.segments)

    @property
    def checksum(self) -> int:
        return zlib.adler32(self.canonical_bytes, 1) & 0xFFFFFFFF

    @property
    def cycle_states(self) -> int:
        return sum(duration for duration, _state in self.segments)

    @property
    def finite_states(self) -> int | None:
        return None if self.repeat_count == 0 else self.cycle_states * self.repeat_count

    def state_at(self, interval: int) -> int:
        position = interval % self.cycle_states
        elapsed = 0
        for duration, state in self.segments:
            elapsed += duration
            if position < elapsed:
                return state
        raise AssertionError("program position is outside its cycle")


def walking_program() -> Program:
    states: list[int] = []
    for bit in range(8):
        states.extend((0, 1 << bit))
    return Program("walking-bit", tuple((1, state) for state in states), 256, 0)


def long_hold_program() -> Program:
    return Program("long-hold", ((2048, 0x00), (3072, 0xFF), (4096, 0xA5)), 2, 0)


def every_transition_program(repeats: int) -> Program:
    segments = tuple((1, 0xAA if index & 1 else 0x55) for index in range(1024))
    return Program("every-microsecond-transition", segments, repeats, 0)


def finite_repeat_program() -> Program:
    return Program(
        "finite-repeat", ((7, 0x81), (13, 0x18), (29, 0x42), (5, 0x24)), 97, 0x3C
    )


def infinite_repeat_program() -> Program:
    return Program(
        "infinite-repeat", ((17, 0x11), (31, 0xEE), (23, 0x69), (43, 0x96)), 0, 0
    )


@dataclass
class StreamTotals:
    frames: int = 0
    items: int = 0
    last_sequence: int | None = None
    last_ticks: int | None = None


@dataclass
class IntervalGrader:
    program: Program
    lag_ticks: int
    start_tick: int = 0
    allow_gaps: bool = False
    intervals_graded: int = 0
    samples_graded: int = 0
    mismatches: int = 0
    incomplete_intervals: int = 0
    skipped_intervals: int = 0
    _current_interval: int | None = None
    _current_count: int = 0

    def accept(self, ticks: int, state: int) -> None:
        relative = ticks - self.start_tick - self.lag_ticks
        if relative < 0:
            return
        interval, phase = divmod(relative, OUTPUT_PERIOD_TICKS)
        if phase % GPIO_SAMPLE_PERIOD_TICKS:
            raise CampaignFailure("loopback sample is not on the GPIO grid")
        finite = self.program.finite_states
        if finite is not None and interval >= finite:
            return
        if self._current_interval is None:
            self._current_interval = interval
        if interval != self._current_interval:
            self._finish_interval()
            if interval != self._current_interval + 1:
                self.skipped_intervals += max(0, interval - self._current_interval - 1)
            self._current_interval = interval
            self._current_count = 0
        self._current_count += 1
        self.samples_graded += 1
        if state != self.program.state_at(interval):
            self.mismatches += 1

    def _finish_interval(self) -> None:
        if self._current_count == 4:
            self.intervals_graded += 1
        else:
            self.incomplete_intervals += 1

    def finish(self) -> None:
        if self._current_interval is not None:
            self._finish_interval()
            self._current_interval = None
        require(self.intervals_graded > 0, "no complete output interval was graded")
        require(
            self.mismatches == 0, "loopback states do not match the output schedule"
        )
        require(
            self.allow_gaps
            or (self.incomplete_intervals == 0 and self.skipped_intervals == 0),
            "output intervals lack exactly four GPIO samples",
        )


@dataclass
class CaptureValidator:
    program: Program
    checksum_algorithm: int
    run_id: int
    lag_ticks: int | None
    infer_lag: bool
    allow_gaps: bool = False
    grade_loopback: bool = True
    adc: StreamTotals = field(default_factory=StreamTotals)
    gpio: StreamTotals = field(default_factory=StreamTotals)
    adc_min: list[int] = field(default_factory=lambda: [0xFFFF, 0xFFFF])
    adc_max: list[int] = field(default_factory=lambda: [0, 0])
    prefix_samples: list[tuple[int, int]] = field(default_factory=list)
    grader: IntervalGrader | None = None
    gap_frames: int = 0

    def accept(self, frame: Frame) -> None:
        require(frame.run_id == self.run_id, "data frame run identity mismatch")
        require(
            frame.checksum_algorithm == self.checksum_algorithm,
            "data checksum selection changed",
        )
        totals = self.adc if frame.kind == ADC_DATA else self.gpio
        if totals.last_sequence is not None:
            if totals.last_ticks is None:
                raise AssertionError("stream timestamp state is inconsistent")
            sequence_gap = (frame.sequence - totals.last_sequence) & 0xFFFFFFFF
            ticks_gap = frame.first_sample_ticks - totals.last_ticks
            if sequence_gap != 1 or ticks_gap != FRAME_COVERAGE_TICKS:
                if not self.allow_gaps:
                    raise CampaignFailure(
                        "input sequence or timestamp is discontinuous"
                    )
                self.gap_frames += max(1, sequence_gap - 1)
        totals.last_sequence = frame.sequence
        totals.last_ticks = frame.first_sample_ticks
        totals.frames += 1
        totals.items += frame.item_count
        if frame.flags & (FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE):
            if not self.allow_gaps:
                raise CampaignFailure("unexpected acquisition loss flag")
            self.gap_frames += 1
        if frame.kind == ADC_DATA:
            for adc0, adc1 in struct.iter_unpack("<HH", frame.payload):
                require(adc0 <= 4095 and adc1 <= 4095, "ADC code exceeds 12-bit range")
                self.adc_min[0] = min(self.adc_min[0], adc0)
                self.adc_min[1] = min(self.adc_min[1], adc1)
                self.adc_max[0] = max(self.adc_max[0], adc0)
                self.adc_max[1] = max(self.adc_max[1], adc1)
            return
        if not self.grade_loopback:
            return
        for index, state in enumerate(frame.payload):
            ticks = frame.first_sample_ticks + index * GPIO_SAMPLE_PERIOD_TICKS
            if self.grader is None:
                self.prefix_samples.append((ticks, state))
            else:
                self.grader.accept(ticks, state)
        if self.grader is None and len(self.prefix_samples) >= GPIO_SAMPLES_PER_FRAME:
            if self.infer_lag:
                self.lag_ticks = infer_loopback_lag(self.program, self.prefix_samples)
            lag_ticks = self.lag_ticks
            if lag_ticks is None:
                raise CampaignFailure("loopback lag is unavailable")
            self.grader = IntervalGrader(
                self.program, lag_ticks, allow_gaps=self.allow_gaps
            )
            for ticks, state in self.prefix_samples:
                self.grader.accept(ticks, state)
            self.prefix_samples.clear()

    def finish(self) -> None:
        require(
            self.adc.frames > 0 and self.gpio.frames > 0,
            "both input streams are required",
        )
        require(
            self.adc.items == self.adc.frames * ADC_PAIRS_PER_FRAME,
            "ADC item conservation failed",
        )
        require(
            self.gpio.items == self.gpio.frames * GPIO_SAMPLES_PER_FRAME,
            "GPIO item conservation failed",
        )
        require(
            all(
                low <= high
                for low, high in zip(self.adc_min, self.adc_max, strict=True)
            ),
            "ADC stream is empty",
        )
        if not self.grade_loopback:
            return
        grader = self.grader
        if grader is None:
            raise CampaignFailure("insufficient GPIO prefix to grade loopback")
        grader.finish()


def infer_loopback_lag(program: Program, samples: Iterable[tuple[int, int]]) -> int:
    """Infer one unique GPIO-grid lag without assuming coincident DMA phase."""

    sample_list = list(samples)
    candidates: list[int] = []
    for lag in range(0, MAX_LOOPBACK_LAG_TICKS + 1, GPIO_SAMPLE_PERIOD_TICKS):
        compared = 0
        valid = True
        for ticks, state in sample_list:
            relative = ticks - lag
            if relative < 0:
                continue
            interval = relative // OUTPUT_PERIOD_TICKS
            finite = program.finite_states
            if finite is not None and interval >= finite:
                continue
            compared += 1
            if state != program.state_at(interval):
                valid = False
                break
        if valid and compared >= 512:
            candidates.append(lag)
    require(
        len(candidates) == 1, "loopback prefix did not identify one bounded fixed lag"
    )
    return candidates[0]


@dataclass
class MemoryMonitor:
    baseline_bytes: int = 0
    high_water_bytes: int = 0

    def __post_init__(self) -> None:
        self.sample()
        self.baseline_bytes = self.high_water_bytes

    def sample(self) -> None:
        if resource is None:
            return
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            value *= 1024
        self.high_water_bytes = max(self.high_water_bytes, value)

    @property
    def growth_bytes(self) -> int:
        return max(0, self.high_water_bytes - self.baseline_bytes)


@dataclass(frozen=True)
class CaseResult:
    name: str
    run_id: int
    lag_ticks: int | None
    adc_frames: int
    gpio_frames: int
    output_intervals: int
    status_latency_p99_ms: float
    status_latency_max_ms: float
    output: dict[str, int]
    acquisition: dict[str, int]
    recovery: str


def percentile_99(values: list[float]) -> float:
    require(bool(values), "no STATUS latency samples were recorded")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)]


def upload_program(link: SerialLink, program: Program, generation: int) -> OutputStatus:
    frame, _ = link.exchange(
        OUTPUT_BEGIN_REQUEST,
        struct.pack("<II", program.repeat_count, program.idle_state),
        run_id=generation,
    )
    status = decode_output_status(frame, OUTPUT_BEGIN_RESPONSE)
    require(
        status.state == OUTPUT_LOADING and status.values["generation"] == generation,
        "OUTPUT_BEGIN echo mismatch",
    )
    require(
        status.values["accepted_segment_count"] == 0,
        "OUTPUT_BEGIN accepted count is not zero",
    )
    for index, segment in enumerate(program.segments, 1):
        response, _ = link.exchange(
            OUTPUT_APPEND_REQUEST, SEGMENT.pack(*segment), run_id=generation
        )
        response_success(response, OUTPUT_APPEND_RESPONSE)
        require(_u32(response.payload, 4) == index, "OUTPUT_APPEND count mismatch")
        require(
            response.payload[8:16] == SEGMENT.pack(*segment),
            "OUTPUT_APPEND echo mismatch",
        )
    frame, _ = link.exchange(
        OUTPUT_COMMIT_REQUEST,
        struct.pack("<II", len(program.segments), program.checksum),
        run_id=generation,
    )
    status = decode_output_status(frame, OUTPUT_COMMIT_RESPONSE)
    require(status.state == OUTPUT_COMMITTED, "OUTPUT_COMMIT did not commit")
    require(
        status.values["program_checksum"] == program.checksum,
        "program checksum echo mismatch",
    )
    require(
        status.values["segment_count"] == len(program.segments),
        "program segment count mismatch",
    )
    require(
        status.values["accepted_segment_count"] == len(program.segments),
        "accepted segment count mismatch",
    )
    return status


def malformed_upload_probe(link: SerialLink, generation: int) -> None:
    """Prove malformed bytes are rejected before ARM and then erased."""

    begin, _ = link.exchange(
        OUTPUT_BEGIN_REQUEST, struct.pack("<II", 1, 0), run_id=generation
    )
    decode_output_status(begin, OUTPUT_BEGIN_RESPONSE)
    malformed, _ = link.exchange(
        OUTPUT_APPEND_REQUEST,
        SEGMENT.pack(1, 0x100),
        run_id=generation,
    )
    require(
        malformed.kind == ERROR_RESPONSE
        and malformed.flags == FLAG_RESPONSE_ERROR,
        "malformed output segment was accepted",
    )
    status, _ = link.exchange(OUTPUT_CLEAR_REQUEST, run_id=generation)
    cleared = decode_output_status(status, OUTPUT_CLEAR_RESPONSE)
    require(
        cleared.state == OUTPUT_EMPTY and cleared.bank_mode == OUTPUT_BANK_DISABLED,
        "malformed upload cleanup did not release pins",
    )


def non_driving_output_control_probe(link: SerialLink, generation: int) -> None:
    """Exercise output controls that cannot arm, then prove fail-closed state."""

    frame, _ = link.exchange(OUTPUT_STATUS_REQUEST, run_id=generation)
    initial = decode_output_status(frame, OUTPUT_STATUS_RESPONSE)
    require(
        initial.state == OUTPUT_EMPTY
        and initial.bank_mode == OUTPUT_BANK_DISABLED,
        "output bank was not empty and disabled before non-driving probe",
    )
    malformed_upload_probe(link, generation)
    frame, _ = link.exchange(OUTPUT_STATUS_REQUEST, run_id=generation)
    final = decode_output_status(frame, OUTPUT_STATUS_RESPONSE)
    require(
        final.state == OUTPUT_EMPTY and final.bank_mode == OUTPUT_BANK_DISABLED,
        "output bank was not empty and disabled after non-driving probe",
    )
    emit_event(
        "non_driving_output_control",
        drive_requests_written=link.drive_requests_written,
        final_bank_disabled=True,
        malformed_segment_rejected=True,
    )


class Campaign:
    def __init__(
        self,
        port_name: str,
        link: SerialLink,
        interlock: DriveInterlock,
        permit: _DrivePermit,
        info: DeviceInfo,
        memory: MemoryMonitor,
    ) -> None:
        self.port_name = port_name
        self.link = link
        self.interlock = interlock
        self.permit = permit
        self.info = info
        self.memory = memory
        self.observation_mode = permit.observation_mode
        self.lag_ticks: int | None = None
        self.next_generation = 0xA8000001
        self._prior_drive_requests_written = 0

    @property
    def drive_requests_written(self) -> int:
        return self._prior_drive_requests_written + self.link.drive_requests_written

    def allocate_generation(self) -> int:
        value = self.next_generation
        self.next_generation = (value + 1) & 0xFFFFFFFF or 1
        return value

    def run_case(
        self,
        program: Program,
        *,
        minimum_seconds: float,
        stop_phase_states: int | None = None,
        host_stall_seconds: float = 0.0,
        disconnect_reopen: bool = False,
        allow_recovery_gaps: bool = False,
        expect_underrun: bool = False,
    ) -> CaseResult:
        allow_observation_gaps = (
            allow_recovery_gaps or self.observation_mode == "unconnected"
        )
        parser_errors_at_start = self.link.parser.errors
        generation = self.allocate_generation()
        upload_program(self.link, program, generation)
        arm, _ = self.link.exchange(
            OUTPUT_ARM_REQUEST,
            run_id=generation,
            permit=self.permit,
        )
        if arm.flags == FLAG_RESPONSE_ERROR:
            rejected = decode_output_status(
                arm, OUTPUT_ARM_RESPONSE, allow_error=True
            )
            protocol_error = _u16(arm.payload, 2)
            emit_event(
                "arm_rejected",
                bank_mode=rejected.bank_mode,
                generation=rejected.values["generation"],
                invalid_operations=rejected.values["invalid_operations"],
                output_error=rejected.output_error,
                protocol_error=protocol_error,
                resource_conflicts=rejected.values["resource_conflicts"],
                start_errors=rejected.values["start_errors"],
                state=rejected.state,
            )
            clear, _ = self.link.exchange(OUTPUT_CLEAR_REQUEST, run_id=generation)
            cleared = decode_output_status(clear, OUTPUT_CLEAR_RESPONSE)
            require(
                cleared.state == OUTPUT_EMPTY
                and cleared.bank_mode == OUTPUT_BANK_DISABLED,
                "CLEAR after rejected ARM did not release the output program",
            )
            raise CampaignFailure(
                "OUTPUT_ARM rejected: "
                f"protocol_error={protocol_error}, "
                f"output_error={rejected.output_error}, "
                f"resource_conflicts={rejected.values['resource_conflicts']}, "
                f"start_errors={rejected.values['start_errors']}"
            )
        armed = decode_output_status(arm, OUTPUT_ARM_RESPONSE)
        require(
            armed.state == OUTPUT_ARMED and armed.bank_mode == OUTPUT_BANK_ENABLED,
            "OUTPUT_ARM did not atomically arm the bank",
        )
        emit_event(
            "output_armed",
            generation=generation,
            state=armed.state,
            bank_mode=armed.bank_mode,
        )
        configured, _ = self.link.exchange(
            CONFIGURE_REQUEST,
            CONFIGURATION.pack(
                STREAM_BOTH,
                SOURCE_HARDWARE,
                self.info.checksum_algorithm,
                0,
                DATA_FRAME_BYTES,
            ),
        )
        if configured.flags == FLAG_RESPONSE_ERROR:
            protocol_error = _u16(configured.payload, 2)
            output_frame, _ = self.link.exchange(
                OUTPUT_STATUS_REQUEST, run_id=generation
            )
            output_status = decode_output_status(
                output_frame, OUTPUT_STATUS_RESPONSE
            )
            emit_event(
                "configure_rejected",
                output_bank_mode=output_status.bank_mode,
                output_state=output_status.state,
                protocol_error=protocol_error,
                resource_conflicts=output_status.values["resource_conflicts"],
                start_errors=output_status.values["start_errors"],
            )
            clear, _ = self.link.exchange(OUTPUT_CLEAR_REQUEST, run_id=generation)
            decode_output_status(clear, OUTPUT_CLEAR_RESPONSE)
            raise CampaignFailure(
                f"CONFIGURE rejected after ARM: protocol_error={protocol_error}"
            )
        response_success(configured, CONFIGURE_RESPONSE)
        emit_event("acquisition_configured", generation=generation)
        start_data: list[Frame] = []
        started, _ = self.link.exchange(
            START_REQUEST, permit=self.permit, on_data=start_data.append
        )
        if started.flags == FLAG_RESPONSE_ERROR:
            protocol_error = _u16(started.payload, 2)
            output_frame, _ = self.link.exchange(
                OUTPUT_STATUS_REQUEST, run_id=generation
            )
            output_status = decode_output_status(
                output_frame, OUTPUT_STATUS_RESPONSE
            )
            emit_event(
                "start_rejected",
                output_error=output_status.output_error,
                output_state=output_status.state,
                protocol_error=protocol_error,
                resource_conflicts=output_status.values["resource_conflicts"],
                start_errors=output_status.values["start_errors"],
            )
            stop, _ = self.link.exchange(STOP_REQUEST)
            response_success(stop, STOP_RESPONSE)
            clear, _ = self.link.exchange(OUTPUT_CLEAR_REQUEST, run_id=generation)
            decode_output_status(clear, OUTPUT_CLEAR_RESPONSE)
            raise CampaignFailure(
                f"START rejected after ARM/CONFIGURE: protocol_error={protocol_error}"
            )
        response_success(started, START_RESPONSE)
        run_id = started.run_id
        require(run_id != 0, "START returned a zero common run identity")
        validator = CaptureValidator(
            program,
            self.info.checksum_algorithm,
            run_id,
            self.lag_ticks,
            self.lag_ticks is None,
            allow_observation_gaps,
            grade_loopback=self.observation_mode == "loopback",
        )
        for frame in start_data:
            validator.accept(frame)
        status_latencies: list[float] = []
        started_at = time.monotonic()
        deadline = started_at + max(minimum_seconds + 2.0, 3.0)
        next_status = started_at
        stalled = False
        reopened = False
        latest_output: OutputStatus | None = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            elapsed = now - started_at
            if host_stall_seconds and not stalled and elapsed >= minimum_seconds / 3:
                time.sleep(host_stall_seconds)
                stalled = True
                emit_event(
                    "host_stall_complete",
                    case=program.name,
                    duration_seconds=host_stall_seconds,
                )
                continue
            if disconnect_reopen and not reopened and elapsed >= minimum_seconds / 2:
                self._disconnect_reopen()
                reopened = True
                continue
            if now >= next_status:
                frame, latency = self.link.exchange(
                    OUTPUT_STATUS_REQUEST,
                    run_id=generation,
                    on_data=validator.accept,
                )
                latest_output = decode_output_status(frame, OUTPUT_STATUS_RESPONSE)
                status_latencies.append(latency)
                live_frame, live_latency = self.link.exchange(
                    GET_STATUS_REQUEST, on_data=validator.accept
                )
                live = decode_acquisition_status(live_frame)
                if not (
                    live.device_state == STATE_RUNNING
                    and live.stream_mask == STREAM_BOTH
                    and live.source == SOURCE_HARDWARE
                ):
                    emit_event(
                        "live_status_profile_mismatch",
                        acquisition_faults={
                            name: value
                            for name, value in live.values.items()
                            if value != 0
                            and any(
                                marker in name
                                for marker in (
                                    "error",
                                    "lost",
                                    "dropped",
                                    "overrun",
                                    "mismatch",
                                    "exhaustion",
                                    "rejection",
                                    "eviction",
                                )
                            )
                        },
                        checksum_algorithm=live.checksum_algorithm,
                        device_state=live.device_state,
                        output_dma_errors=latest_output.values["dma_errors"],
                        output_error=latest_output.output_error,
                        output_fault_latched=latest_output.fault_latched,
                        output_resource_conflicts=latest_output.values[
                            "resource_conflicts"
                        ],
                        output_start_errors=latest_output.values["start_errors"],
                        output_state=latest_output.state,
                        output_underruns=latest_output.values["underruns"],
                        run_id=live_frame.run_id,
                        source=live.source,
                        stream_mask=live.stream_mask,
                    )
                require(
                    live.device_state == STATE_RUNNING
                    and live.stream_mask == STREAM_BOTH
                    and live.source == SOURCE_HARDWARE,
                    "live acquisition STATUS changed profile",
                )
                status_latencies.append(live_latency)
                self.memory.sample()
                if (
                    expect_underrun
                    and latest_output.output_error == OUTPUT_ERROR_UNDERRUN
                ):
                    break
                finite_complete = (
                    program.finite_states is not None
                    and latest_output.state == OUTPUT_HELD
                    and elapsed >= minimum_seconds
                )
                phase_reached = (
                    stop_phase_states is not None
                    and latest_output.values["dma_states_emitted"] >= stop_phase_states
                )
                if (
                    finite_complete
                    or phase_reached
                    or (
                        program.finite_states is None
                        and stop_phase_states is None
                        and elapsed >= minimum_seconds
                    )
                ):
                    break
                next_status = now + STATUS_INTERVAL_SECONDS
                continue
            self.link.pump_once(validator.accept)
        else:
            raise DeadlineExpired("output case exceeded its bounded deadline")

        stop, stop_latency = self.link.exchange(STOP_REQUEST, on_data=validator.accept)
        status_latencies.append(stop_latency)
        response_success(stop, STOP_RESPONSE)
        require(
            stop.payload[4] == STATE_IDLE and stop.run_id == run_id,
            "STOP did not return the common run to IDLE",
        )
        self.link.drain_until_quiet(validator.accept)
        output_frame, latency = self.link.exchange(
            OUTPUT_STATUS_REQUEST, run_id=generation
        )
        status_latencies.append(latency)
        final_output = decode_output_status(output_frame, OUTPUT_STATUS_RESPONSE)
        time.sleep(HOLD_OBSERVATION_SECONDS)
        held_frame, latency = self.link.exchange(
            OUTPUT_STATUS_REQUEST, run_id=generation
        )
        status_latencies.append(latency)
        held_again = decode_output_status(held_frame, OUTPUT_STATUS_RESPONSE)
        for field_name in (
            "current_state_mask",
            "last_emitted_state_mask",
            "dma_states_emitted",
            "hold_tick",
        ):
            require(
                held_again.values[field_name] == final_output.values[field_name],
                "physical hold changed during the observation interval",
            )
        require(held_again.state == final_output.state, "held lifecycle state changed")
        final_output = held_again
        acquisition_frame, latency = self.link.exchange(GET_STATUS_REQUEST)
        status_latencies.append(latency)
        final_acquisition = decode_acquisition_status(acquisition_frame)
        validator.finish()
        if self.observation_mode == "loopback":
            require(validator.lag_ticks is not None, "loopback lag was not inferred")
            if self.lag_ticks is None:
                self.lag_ticks = validator.lag_ticks
                emit_event("loopback_lag_inferred", lag_ticks=self.lag_ticks)
            require(
                validator.lag_ticks == self.lag_ticks,
                "loopback lag shifted between cases",
            )
        self._validate_output_final(program, run_id, final_output, expect_underrun)
        self._validate_acquisition_final(
            final_acquisition, validator, allow_observation_gaps
        )
        if not allow_observation_gaps:
            require(
                self.link.parser.errors == parser_errors_at_start,
                "host parser rejected wire bytes during a lossless case",
            )
        p99 = percentile_99(status_latencies)
        maximum = max(status_latencies)
        require(p99 <= STATUS_P99_LIMIT_SECONDS, "STATUS p99 latency exceeded bound")
        require(maximum <= STATUS_MAX_LIMIT_SECONDS, "command latency exceeded bound")
        clear, _ = self.link.exchange(OUTPUT_CLEAR_REQUEST, run_id=generation)
        cleared = decode_output_status(clear, OUTPUT_CLEAR_RESPONSE)
        require(
            cleared.state == OUTPUT_EMPTY and cleared.bank_mode == OUTPUT_BANK_DISABLED,
            "CLEAR did not release all output pins",
        )
        info_frame, _ = self.link.exchange(INFO_REQUEST)
        post_clear = decode_info(info_frame)
        require(
            post_clear.hardware_serial == self.info.hardware_serial,
            "hardware identity changed",
        )
        self.memory.sample()
        intervals = int(validator.grader.intervals_graded if validator.grader else 0)
        lag_ticks = self.lag_ticks
        if self.observation_mode == "loopback" and lag_ticks is None:
            raise AssertionError("campaign lag disappeared after validation")
        emit_event(
            "case_complete",
            adc_frames=validator.adc.frames,
            case=program.name,
            gpio_frames=validator.gpio.frames,
            loopback_intervals=intervals,
            observation_mode=self.observation_mode,
            recovery=(
                "disconnect-reopen"
                if disconnect_reopen
                else "host-stall"
                if host_stall_seconds
                else "none"
            ),
        )
        return CaseResult(
            program.name,
            run_id,
            lag_ticks,
            validator.adc.frames,
            validator.gpio.frames,
            intervals,
            p99 * 1000.0,
            maximum * 1000.0,
            final_output.values,
            final_acquisition.values,
            "disconnect-reopen"
            if disconnect_reopen
            else "host-stall"
            if host_stall_seconds
            else "none",
        )

    def _disconnect_reopen(self) -> None:
        old = self.link
        self._prior_drive_requests_written += old.drive_requests_written
        old.port.close()
        time.sleep(REOPEN_SETTLE_SECONDS)
        port = serial.Serial(
            port=self.port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_TIMEOUT_SECONDS,
            write_timeout=WRITE_TIMEOUT_SECONDS,
        )
        self.link = SerialLink(port, self.interlock)
        self.link.drain_startup(REOPEN_SETTLE_SECONDS)
        emit_event("serial_reopened")

    @staticmethod
    def _validate_output_final(
        program: Program,
        run_id: int,
        status: OutputStatus,
        expect_underrun: bool,
    ) -> None:
        values = status.values
        if expect_underrun:
            require(
                status.state == OUTPUT_FAULTED, "forced underrun did not latch FAULTED"
            )
            require(
                status.output_error == OUTPUT_ERROR_UNDERRUN
                and values["underruns"] > 0,
                "forced underrun evidence is absent",
            )
        else:
            require(
                status.state == OUTPUT_HELD and not status.fault_latched,
                "STOP/completion did not hold safely",
            )
            require(
                status.output_error == OUTPUT_ERROR_NONE,
                "output reported an unexpected error",
            )
            require(
                values["resource_conflicts"] == 0 and values["underruns"] == 0,
                "output conflict or underrun observed",
            )
            require(
                values["dma_errors"] == 0
                and values["start_errors"] == 0
                and values["stop_errors"] == 0,
                "output lifecycle error observed",
            )
            require(
                values["conservation_errors"] == 0 and status.conservation_exact,
                "output conservation flag failed",
            )
        require(
            values["common_run_id"] == run_id, "output/common run identity mismatch"
        )
        require(
            values["dma_states_queued"] == values["states_expanded"],
            "expanded/queued output conservation failed",
        )
        require(
            values["states_expanded"]
            == values["dma_states_emitted"]
            + values["refill_lead"]
            + values["held_remainder_states"],
            "emitted/lead/held output conservation failed",
        )
        if program.finite_states is not None:
            require(
                values["requested_duration_states"] == program.finite_states,
                "finite duration accounting mismatch",
            )
        require(
            values["hold_tick"] >= values["start_tick"], "hold tick precedes start tick"
        )

    @staticmethod
    def _validate_acquisition_final(
        status: AcquisitionStatus,
        validator: CaptureValidator,
        allow_gaps: bool,
    ) -> None:
        require(status.device_state == STATE_IDLE, "acquisition is not IDLE after STOP")
        require(
            status.stream_mask == STREAM_NONE and status.source == SOURCE_HARDWARE,
            "final acquisition profile is not the IDLE placeholder",
        )
        require(
            status.checksum_algorithm == validator.checksum_algorithm,
            "final checksum selection changed",
        )
        values = status.values
        require(
            values["adc_frames_emitted"] >= validator.adc.frames,
            "ADC frame counter trails host",
        )
        require(
            values["gpio_frames_emitted"] >= validator.gpio.frames,
            "GPIO frame counter trails host",
        )
        errors = (
            "parser_errors",
            "transport_errors",
            "gpio_hardware_errors",
            "gpio_raw_invariant_errors",
            "gpio_packer_source_errors",
            "gpio_packer_pipeline_errors",
            "gpio_packer_chronology_errors",
            "gpio_resource_conflicts",
            "gpio_start_errors",
            "gpio_stop_errors",
            "adc_etc_error_events",
            "adc_dma_error_events",
            "adc_completion_mismatches",
            "adc_destination_mismatches",
            "adc_schedule_exhaustions",
            "adc_raw_invariant_errors",
            "adc_resource_conflicts",
            "adc_start_errors",
            "adc_stop_errors",
            "adc_packer_source_errors",
            "adc_packer_pipeline_errors",
            "adc_packer_chronology_errors",
            "packet_encoding_rejections",
            "usb_io_errors",
        )
        nonzero_errors = {
            name: values[name] for name in errors if values[name] != 0
        }
        if nonzero_errors:
            emit_event("acquisition_error_counters", counters=nonzero_errors)
        require(
            not nonzero_errors,
            "acquisition error counter is nonzero",
        )
        nonzero_losses = {
            name: values[name]
            for name in ACQUISITION_LOSS_FIELDS
            if values[name] != 0
        }
        if nonzero_losses:
            emit_event("acquisition_loss_counters", counters=nonzero_losses)
        if not allow_gaps:
            require(
                not nonzero_losses,
                "unexpected acquisition loss observed",
            )
        require(
            values["adc0_dma_results"] == values["adc1_dma_results"],
            "ADC stream pair conservation failed",
        )
        require(
            values["adc_pairs_captured"] >= values["adc_pairs_framed"],
            "ADC capture/framing conservation failed",
        )
        require(
            values["gpio_samples_captured"] >= values["gpio_samples_framed"],
            "GPIO capture/framing conservation failed",
        )
        require(
            values["gpio_raw_ready_high_water"] <= 4, "GPIO raw queue exceeded ring"
        )
        require(
            values["gpio_packed_ready_high_water"] <= 4,
            "GPIO packed queue exceeded ring",
        )
        require(values["adc_raw_ready_high_water"] <= 8, "ADC raw queue exceeded ring")
        require(
            values["packet_owned_high_water"] <= 194,
            "packet ownership exceeded repartition",
        )
        require(
            values["gpio_processing_cpu_basis_points"] <= 10_000,
            "GPIO load metric is invalid",
        )


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside its finite bound")
    return value


def _boolean_environment(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def build_result(
    *,
    result: str,
    reason: str,
    fixture_sha256: str | None,
    info: DeviceInfo | None,
    cases: list[CaseResult],
    failures: list[str],
    memory: MemoryMonitor,
    drive_requests_written: int,
    profile_id: str = PROFILE_ID,
    observation_mode: str = "loopback",
) -> dict[str, object]:
    lag = cases[0].lag_ticks if cases else None
    p99 = max((case.status_latency_p99_ms for case in cases), default=None)
    maximum = max((case.status_latency_max_ms for case in cases), default=None)
    intervals = sum(case.output_intervals for case in cases)
    acquisition_losses = {
        name: sum(case.acquisition[name] for case in cases)
        for name in ACQUISITION_LOSS_FIELDS
        if any(case.acquisition[name] != 0 for case in cases)
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "matrix_schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "result": result,
        "reason": reason,
        "identity": {
            "hardware_serial": None if info is None else info.hardware_serial,
            "firmware_build_id": None if info is None else info.build_id,
            "fixture_declaration_sha256": fixture_sha256,
            "output_profile": profile_id,
            "observation_mode": observation_mode,
            "protocol_version": PROTOCOL_VERSION,
        },
        "evidence": {
            "level": "rig",
            "authorization": "PASS" if cases else "NOT_RUN",
            "drive_requests_written": drive_requests_written,
            "case_count": len(cases),
            "cases": [
                {
                    "name": case.name,
                    "run_id": case.run_id,
                    "adc_frames": case.adc_frames,
                    "gpio_frames": case.gpio_frames,
                    "output_intervals": case.output_intervals,
                    "status_latency_p99_ms": case.status_latency_p99_ms,
                    "status_latency_max_ms": case.status_latency_max_ms,
                    "recovery": case.recovery,
                    "acquisition_losses": {
                        name: case.acquisition[name]
                        for name in ACQUISITION_LOSS_FIELDS
                        if case.acquisition[name] != 0
                    },
                }
                for case in cases
            ],
            "failures": failures,
        },
        "metrics": {
            "output_loopback_lag_ticks": lag,
            "output_intervals_graded": intervals,
            "status_latency_p99_ms": p99,
            "status_latency_max_ms": maximum,
            "host_rss_growth_bytes": memory.growth_bytes,
            "acquisition_losses": acquisition_losses,
        },
        "acceptance": {
            "fixture_interlock": "PASS" if cases else "NOT_RUN",
            "loopback_schedule": "PASS"
            if observation_mode == "loopback" and cases and not failures
            else "NOT_RUN"
            if observation_mode == "unconnected" or not cases
            else "FAIL",
            "output_lifecycle": "PASS"
            if cases and not failures
            else "NOT_RUN"
            if not cases
            else "FAIL",
            "combined_acquisition": "PASS"
            if cases and not failures and not acquisition_losses
            else "FAIL"
            if cases and acquisition_losses
            else "NOT_RUN"
            if not cases
            else "FAIL",
            "final_idle_cleanup": "PASS"
            if cases and not failures
            else "NOT_RUN"
            if not cases
            else "FAIL",
        },
        "limitations": [
            "Loopback self-observation is not independent timing or signal-integrity evidence.",
            "ADC codes are range/conservation checked without claiming analog accuracy.",
            *(
                ["Unconnected smoke does not observe output pin state or waveform."]
                if observation_mode == "unconnected"
                else []
            ),
        ],
    }


def emit_not_run(reason: str) -> None:
    """Emit the mandatory machine-readable result for preflight exits."""

    print(
        RESULT_PREFIX
        + json.dumps(
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "experiment_id": EXPERIMENT_ID,
                "result": "NOT_RUN",
                "reason": reason,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        emit_not_run("SERIAL_PORT is required")
        return 2
    mode = os.environ.get("AUX_OUTPUT_MODE", "smoke").strip().lower()
    if mode not in {"smoke", "endurance"}:
        reason = "AUX_OUTPUT_MODE must be smoke or endurance"
        emit_event("configuration_error", error=reason)
        emit_not_run(reason)
        return 2
    try:
        declaration = parse_fixture_declaration(
            os.environ.get("AUX_OUTPUT_FIXTURE_JSON")
            or EMBEDDED_FIXTURE_DECLARATION
        )
        host_stall = _bounded_float(
            "AUX_OUTPUT_HOST_STALL_SECONDS", 0.025, 0.0, MAX_HOST_STALL_SECONDS
        )
        endurance_seconds = _bounded_float(
            "AUX_OUTPUT_ENDURANCE_SECONDS", 600.0, 1.0, MAX_CAPTURE_SECONDS
        )
        enable_recovery = _boolean_environment("AUX_OUTPUT_RECOVERY_CASES", True)
        force_underrun = _boolean_environment(
            "AUX_OUTPUT_EXPECT_FORCED_UNDERRUN", False
        )
    except (TypeError, ValueError) as error:
        emit_event("configuration_error", error=str(error))
        emit_not_run(str(error))
        return 2
    interlock = DriveInterlock(declaration)
    port: SerialPort | None = None
    link: SerialLink | None = None
    campaign: Campaign | None = None
    info: DeviceInfo | None = None
    memory = MemoryMonitor()
    cases: list[CaseResult] = []
    failures: list[str] = []
    result = "FAIL"
    reason = "campaign did not complete"
    exit_code = 1
    try:
        port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_TIMEOUT_SECONDS,
            write_timeout=WRITE_TIMEOUT_SECONDS,
        )
        link = SerialLink(port, interlock)
        link.drain_startup()
        info_frame, _ = link.exchange(INFO_REQUEST)
        info = decode_info(info_frame)
        emit_event(
            "preflight",
            fixture_declaration_sha256=interlock.declaration_sha256,
            fixture_present=declaration is not None,
            observation_mode=(
                "none" if declaration is None else declaration.observation_mode
            ),
            output_bank_disabled=info.output_bank_mode == OUTPUT_BANK_DISABLED,
            protocol=PROTOCOL_VERSION,
        )
        non_driving_output_control_probe(link, 0xA7000001)
        try:
            permit = interlock.authorize(info.hardware_serial)
        except InterlockDenied as error:
            result = "INCONCLUSIVE"
            reason = str(error)
            exit_code = 0
        else:
            campaign = Campaign(port_name, link, interlock, permit, info, memory)
            cases.append(campaign.run_case(walking_program(), minimum_seconds=0.15))
            cases.append(campaign.run_case(long_hold_program(), minimum_seconds=0.15))
            repetitions = (
                max(8, math.ceil(endurance_seconds * OUTPUT_RATE_HZ / 1024))
                if mode == "endurance"
                else 16
            )
            repetitions = min(repetitions, 0xFFFFFFFF)
            cases.append(
                campaign.run_case(
                    every_transition_program(repetitions),
                    minimum_seconds=endurance_seconds if mode == "endurance" else 0.15,
                )
            )
            cases.append(
                campaign.run_case(finite_repeat_program(), minimum_seconds=0.15)
            )
            for phase in (100_257, 202_033, 304_099):
                cases.append(
                    campaign.run_case(
                        infinite_repeat_program(),
                        minimum_seconds=0.05,
                        stop_phase_states=phase,
                    )
                )
            if enable_recovery:
                cases.append(
                    campaign.run_case(
                        infinite_repeat_program(),
                        minimum_seconds=0.35,
                        host_stall_seconds=host_stall,
                    )
                )
                cases.append(
                    campaign.run_case(
                        infinite_repeat_program(),
                        minimum_seconds=0.70,
                        disconnect_reopen=True,
                        allow_recovery_gaps=True,
                    )
                )
            if force_underrun:
                cases.append(
                    campaign.run_case(
                        every_transition_program(OUTPUT_REPEAT_FOREVER),
                        minimum_seconds=0.25,
                        host_stall_seconds=MAX_HOST_STALL_SECONDS,
                        allow_recovery_gaps=True,
                        expect_underrun=True,
                    )
                )
            memory.sample()
            require(
                memory.growth_bytes <= MAX_RSS_GROWTH_BYTES,
                "host RSS growth exceeded bound",
            )
            acquisition_losses_present = any(
                case.acquisition[name] != 0
                for case in cases
                for name in ACQUISITION_LOSS_FIELDS
            )
            if declaration.observation_mode == "loopback":
                result = "PASS"
                reason = "authorized loopback campaign passed every bounded check"
                exit_code = 0
            elif acquisition_losses_present:
                result = "FAIL"
                reason = (
                    "unconnected output lifecycle completed with acquisition loss"
                )
                exit_code = 1
            else:
                result = "INCONCLUSIVE"
                reason = (
                    "unconnected output lifecycle passed; physical output was not "
                    "observed"
                )
                exit_code = 0
    except Exception as error:  # noqa: BLE001 - preserve rig diagnosis
        message = f"{type(error).__name__}: {error}"
        failures.append(message)
        emit_event("fatal", error=message)
    finally:
        active_link = campaign.link if campaign is not None else link
        if active_link is not None:
            try:
                if campaign is None and info is not None:
                    cleared_frame, _ = active_link.exchange(
                        OUTPUT_CLEAR_REQUEST,
                        run_id=0xA7000001,
                        timeout=COMMAND_DEADLINE_SECONDS,
                    )
                    cleared = decode_output_status(
                        cleared_frame, OUTPUT_CLEAR_RESPONSE
                    )
                    require(
                        cleared.state == OUTPUT_EMPTY
                        and cleared.bank_mode == OUTPUT_BANK_DISABLED,
                        "final OUTPUT_CLEAR did not leave the bank disabled",
                    )
                    emit_event("final_clear_attempt", accepted=True)
                else:
                    stop, _ = active_link.exchange(
                        STOP_REQUEST, timeout=COMMAND_DEADLINE_SECONDS
                    )
                    emit_event("final_stop_attempt", accepted=stop.flags == 0)
            except Exception as error:  # noqa: BLE001 - best effort is evidence
                cleanup_message = f"{type(error).__name__}: {error}"
                failures.append("final STOP failed: " + cleanup_message)
                emit_event("final_stop_failed", error=cleanup_message)
                if result == "PASS":
                    result = "FAIL"
                    reason = "final STOP/hold attempt failed"
                    exit_code = 1
            try:
                active_link.port.close()
            except Exception as error:  # noqa: BLE001 - result records cleanup
                failures.append(f"serial close failed: {type(error).__name__}: {error}")
                if result == "PASS":
                    result = "FAIL"
                    reason = "serial close failed"
                    exit_code = 1
        elif port is not None:
            port.close()
    drive_requests = 0
    if campaign is not None:
        drive_requests = campaign.drive_requests_written
    elif link is not None:
        drive_requests = link.drive_requests_written
    report = build_result(
        result=result,
        reason=reason,
        fixture_sha256=interlock.declaration_sha256,
        info=info,
        cases=cases,
        failures=failures,
        memory=memory,
        drive_requests_written=drive_requests,
        profile_id=(PROFILE_ID if declaration is None else declaration.profile_id),
        observation_mode=(
            "loopback" if declaration is None else declaration.observation_mode
        ),
    )
    print(RESULT_PREFIX + json.dumps(report, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
