#!/usr/bin/env python3
"""Canonical, dependency-bounded Teensy DAQ endurance validator.

``firmware/tools/generate_soak_programs.py`` replaces only the marked
configuration block and writes three standalone rig programs.  Keep all wire,
validation, deadline, cleanup, and result-schema logic in this file so a
protocol repair cannot drift between soak modes.

The generated programs run in the remote service's network-disabled Python
3.13 container and intentionally import only the standard library and
PySerial.  They read the serial endpoint exclusively from ``SERIAL_PORT``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import sys
import time
import tracemalloc
import zlib
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import serial

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows only
    resource = None  # type: ignore[assignment]


# <soak-generated-config>
GENERATED_CONFIG: dict[str, object] = json.loads(
    r"""
{
  "candidate": {
    "artifact": {
      "name": "firmware.ino.hex",
      "sha256": "f10798db45504fffb7dbbaacafaa06a8317b9c6fbab6b07c788e1a198881a3ba"
    },
    "board": {
      "board_id": 1,
      "fqbn": "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
      "hardware_serial": 20512460,
      "mcu_id": 1
    },
    "firmware": {
      "build_id": "tdaq-4f1423acdfa045f2",
      "source_id": "4f1423acdfa045f23e8fa02a180fb73648996108ee0aae03417d5910fbeeda7a",
      "version": [
        0,
        7,
        0
      ]
    },
    "protocol": {
      "checksum_algorithm": 1,
      "checksum_name": "ADLER32",
      "version": 1
    },
    "schema_version": 1,
    "soak": {
      "control_epoch_seconds": 12.0,
      "control_reopen_every_epochs": 4,
      "hard_deadline_seconds": 780.0,
      "info_interval_seconds": 30.0,
      "measured_duration_seconds": 600.0,
      "service_container_limit_seconds": 900.0,
      "status_interval_seconds": 0.5,
      "warmup_seconds": 1.0
    }
  },
  "candidate_sha256": "c2dac797f1e1f54310ee38d022435818dc84038e55dbf88a893d6b39c96621f6",
  "generator_schema_version": 1,
  "mode": "physical-combined",
  "validator_sha256": "064089fcf4f8f710fec8ce7d14adb8f1a5888ba51a74b5e555f21c3186d3caa3"
}
"""
)
# </soak-generated-config>


RESULT_PREFIX = "SOAK_RESULT "
EVENT_PREFIX = "SOAK_EVENT "
RESULT_SCHEMA_VERSION = 1
SUPPORTED_MODES = frozenset({"synthetic", "physical-combined", "control-stress"})

BAUD_RATE = 115_200
SERIAL_READ_TIMEOUT_SECONDS = 0.02
SERIAL_WRITE_TIMEOUT_SECONDS = 0.5
SYNTHETIC_SERIAL_READ_BYTES = 64 * 1024
PHYSICAL_SERIAL_READ_BYTES = 16 * 1024
STARTUP_DRAIN_SECONDS = 0.25
REOPEN_SETTLE_SECONDS = 0.25
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 0.5
STOP_DRAIN_DEADLINE_SECONDS = 3.0
STOP_DRAIN_QUIET_SECONDS = 0.10
MAX_STATUS_SAMPLES = 4_096
MAX_LATENCY_SAMPLES = 4_096
MAX_DIAGNOSTIC_SAMPLES = 8
MAX_COUNTER_SAMPLES = 12
RATE_TOLERANCE_FRACTION = 0.01
STATUS_P99_LIMIT_SECONDS = 0.100
STATUS_MAXIMUM_LIMIT_SECONDS = 0.250
MAX_RSS_GROWTH_BYTES = 32 * 1024 * 1024
MAX_TRACED_GROWTH_BYTES = 16 * 1024 * 1024
MINIMUM_DEADLINE_RESERVE_SECONDS = 30.0

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 1
HEADER_SIZE = 44
TRAILER_SIZE = 4
DATA_FRAME_BYTES = 4_096
DATA_PAYLOAD_BYTES = 4_048
MAX_CONTROL_FRAME_BYTES = 1_280
MAX_FRAME_BYTES = DATA_FRAME_BYTES
CHECKSUM_ADLER32 = 1
BOOTSTRAP_CHECKSUM = CHECKSUM_ADLER32

TIMESTAMP_HZ = 8_000_000
ADC_PAIR_RATE_HZ = 1_000_000
ADC_PAIR_PERIOD_TICKS = 8
ADC1_PHASE_TICKS = 4
ADC_RESOLUTION_BITS = 12
ADC_BYTES_PER_PAIR = 4
ADC_PAIRS_PER_FRAME = 1_012
GPIO_SAMPLE_RATE_HZ = 4_000_000
GPIO_SAMPLE_PERIOD_TICKS = 2
GPIO_SAMPLES_PER_FRAME = 4_048
GPIO_PINS_BY_BIT = tuple(range(6, 14))
FRAME_COVERAGE_TICKS = 8_096
TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND = 8_000_000
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

EXPECTED_STREAM_MASK = STREAM_BOTH
EXPECTED_SOURCE_MASK = (1 << SOURCE_HARDWARE) | (1 << SOURCE_SYNTHETIC)
EXPECTED_CHECKSUM_MASK = 0x0E
EXPECTED_CAPABILITIES = 0x000001FF
EXPECTED_CONFIGURATION_MASK = 0x003F
EXPECTED_BOARD_ID = 1
EXPECTED_MCU_ID = 1
PACKET_BUFFER_COUNT = 200
PACKET_QUEUE_CAPACITY = 200
COMMAND_QUEUE_CAPACITY = 4
RESPONSE_QUEUE_CAPACITY = 4
GPIO_RAW_RING_DEPTH = 4
GPIO_PACKED_RING_DEPTH = 4
ADC_RAW_RING_DEPTH = 6

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
    INFO_RESPONSE: 376,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 1_228,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    ERROR_RESPONSE: 8,
}
DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
RESPONSE_KINDS = frozenset(SUCCESS_PAYLOAD_SIZE)


class SoakFailure(RuntimeError):
    """One classified validation failure destined for the final JSON."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class DeadlineExpired(SoakFailure):
    """A finite operation or the script-wide budget expired."""

    def __init__(self, message: str) -> None:
        super().__init__("timeout", message)


def require(condition: bool, category: str, message: str) -> None:
    if not condition:
        raise SoakFailure(category, message)


class Clock(Protocol):
    """Injectable clock surface used by accelerated offline tests."""

    def monotonic(self) -> float: ...

    def perf_counter(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SerialPort(Protocol):
    """Narrow PySerial surface needed by the standalone validator."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


def emit_event(name: str, **fields: object) -> None:
    print(
        EVENT_PREFIX
        + json.dumps({"event": name, **fields}, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def adler32(data: bytes | bytearray | memoryview) -> int:
    return zlib.adler32(data, 1) & 0xFFFFFFFF


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
    checksum: int


def encode_request(kind: int, request_id: int, payload: bytes = b"") -> bytes:
    require(kind in REQUEST_PAYLOAD_SIZE, "protocol", f"unknown request kind {kind}")
    require(
        len(payload) == REQUEST_PAYLOAD_SIZE[kind],
        "protocol",
        f"request 0x{kind:02x} payload has {len(payload)} bytes",
    )
    require(1 <= request_id <= 0xFFFFFFFF, "protocol", "request ID is zero")
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
    return body + TRAILER.pack(adler32(body))


class FrameParser:
    """Bounded parser for arbitrary CDC chunks with strict corruption signals."""

    def __init__(self, maximum_input_bytes: int = SYNTHETIC_SERIAL_READ_BYTES) -> None:
        require(
            maximum_input_bytes > 0,
            "configuration",
            "parser maximum input bytes must be positive",
        )
        self.maximum_input_bytes = maximum_input_bytes
        self.buffer = bytearray()
        self.scan_start = 0
        self.bytes_received = 0
        self.frames_decoded = 0
        self.bytes_discarded = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
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
            magic_at = self.buffer.find(MAGIC_BYTES, self.scan_start)
            if magic_at < 0:
                retained = self._partial_magic_suffix()
                self._discard(self._buffered_bytes() - retained)
                break
            self._discard(magic_at - self.scan_start)
            if self._buffered_bytes() < HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.buffer, self.scan_start)
            try:
                total_length = self._validate_header(fields)
            except SoakFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            if self._buffered_bytes() < total_length:
                break
            payload_length = fields[8]
            payload_start = self.scan_start + HEADER_SIZE
            payload_end = payload_start + payload_length
            checksum_view = memoryview(self.buffer)[self.scan_start : payload_end]
            try:
                expected_checksum = adler32(checksum_view)
            finally:
                checksum_view.release()
            actual_checksum = TRAILER.unpack_from(self.buffer, payload_end)[0]
            if expected_checksum != actual_checksum:
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
                checksum=actual_checksum,
            )
            try:
                self._validate_payload(frame)
            except SoakFailure:
                self.payload_errors += 1
                self._discard(1)
                continue
            self.scan_start += total_length
            self.frames_decoded += 1
            frames.append(frame)

        self._compact()
        retained_bound = MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1
        require(
            self._buffered_bytes() <= retained_bound,
            "parser",
            f"parser retained {self._buffered_bytes()} bytes",
        )
        high_water_bound = self.maximum_input_bytes + retained_bound
        require(
            self.high_water_bytes <= high_water_bound,
            "parser",
            f"parser high water {self.high_water_bytes} exceeds {high_water_bound}",
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
        require(magic == MAGIC, "protocol", "frame magic mismatch")
        require(version == PROTOCOL_VERSION, "protocol", "protocol version mismatch")
        require(
            header_length == HEADER_SIZE and reserved == 0,
            "protocol",
            "invalid fixed header fields",
        )
        require(
            total_length == HEADER_SIZE + payload_length + TRAILER_SIZE,
            "protocol",
            "inconsistent frame lengths",
        )
        require(checksum == CHECKSUM_ADLER32, "protocol", "unexpected checksum")

        if kind in DATA_KINDS:
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            period = (
                ADC_PAIR_PERIOD_TICKS if kind == ADC_DATA else GPIO_SAMPLE_PERIOD_TICKS
            )
            require(
                total_length == DATA_FRAME_BYTES
                and payload_length == DATA_PAYLOAD_BYTES,
                "protocol",
                "data frame shape mismatch",
            )
            require(not flags & ~DATA_FLAG_MASK, "protocol", "reserved data flag")
            require(
                not flags & FLAG_OVERRUN_BEFORE or bool(flags & FLAG_GAP_BEFORE),
                "protocol",
                "OVERRUN flag lacks GAP flag",
            )
            require(
                run_id != 0 and request_id == 0 and item_count == expected_items,
                "protocol",
                "invalid data identity/count fields",
            )
            require(
                first_sample_ticks % period == 0,
                "protocol",
                "unaligned data timestamp",
            )
            epoch = bool(flags & FLAG_EPOCH_START)
            require(
                epoch == (sequence == 0 and first_sample_ticks == 0),
                "protocol",
                "EPOCH_START disagrees with sequence/timestamp",
            )
            return total_length

        require(kind in RESPONSE_KINDS, "protocol", f"unexpected kind 0x{kind:02x}")
        require(
            flags in {0, FLAG_RESPONSE_ERROR},
            "protocol",
            "invalid response flags",
        )
        require(
            HEADER_SIZE + TRAILER_SIZE <= total_length <= MAX_CONTROL_FRAME_BYTES,
            "protocol",
            "control response exceeds bound",
        )
        require(
            request_id != 0
            and sequence == 0
            and first_sample_ticks == 0
            and item_count == 0,
            "protocol",
            "invalid response correlation fields",
        )
        expected_payload = (
            4
            if flags == FLAG_RESPONSE_ERROR and kind != ERROR_RESPONSE
            else SUCCESS_PAYLOAD_SIZE[kind]
        )
        require(
            payload_length == expected_payload,
            "protocol",
            "response payload size mismatch",
        )
        return total_length

    @staticmethod
    def _validate_payload(frame: Frame) -> None:
        if frame.kind in DATA_KINDS:
            return
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == FLAG_RESPONSE_ERROR
        require(reserved == 0, "protocol", "response reserved prefix is nonzero")
        require(
            is_error == (status == 1) and ((error != 0) == is_error),
            "protocol",
            "response status/flag/error mismatch",
        )
        require(error <= 12, "protocol", "response error code is unknown")
        if is_error and frame.kind != ERROR_RESPONSE:
            return
        payload = frame.payload
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
            require(
                not any(any(section) for section in reserved_ranges),
                "protocol",
                "INFO reserved fields are nonzero",
            )
        elif frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            require(
                payload[1] == 0 and payload[7] == 0,
                "protocol",
                "configuration response reserved field is nonzero",
            )
        elif frame.kind == GET_STATUS_RESPONSE:
            require(
                payload[1] == 0
                and not any(payload[226:228])
                and not any(payload[274:276]),
                "protocol",
                "STATUS reserved fields are nonzero",
            )
        elif frame.kind == STOP_RESPONSE:
            require(
                payload[1] == 0 and not any(payload[5:]),
                "protocol",
                "STOP reserved fields are nonzero",
            )
        elif frame.kind == RESET_STATS_RESPONSE:
            require(payload[1] == 0, "protocol", "RESET reserved byte is nonzero")

    def _partial_magic_suffix(self) -> int:
        maximum = min(self._buffered_bytes(), len(MAGIC_BYTES) - 1)
        for length in range(maximum, 0, -1):
            if self.buffer.endswith(MAGIC_BYTES[:length], self.scan_start):
                return length
        return 0

    def _discard(self, count: int) -> None:
        if count > 0:
            self.scan_start += count
            self.bytes_discarded += count

    def _buffered_bytes(self) -> int:
        return len(self.buffer) - self.scan_start

    def _compact(self) -> None:
        if self.scan_start:
            del self.buffer[: self.scan_start]
            self.scan_start = 0


class SerialLink:
    """One-request-at-a-time link that drains data while awaiting control."""

    def __init__(
        self,
        port: SerialPort,
        clock: Clock,
        read_bytes: int = SYNTHETIC_SERIAL_READ_BYTES,
    ) -> None:
        require(
            read_bytes > 0,
            "configuration",
            "serial read bytes must be positive",
        )
        self.port = port
        self.clock = clock
        self.read_bytes = read_bytes
        self.parser = FrameParser(read_bytes)
        self.next_request_id = 1
        self.stale_responses = 0
        self.discarded_data_frames = 0
        self.maximum_read_bytes = 0
        self.accepted_requests = 0

    def drain_startup(self, duration: float) -> None:
        deadline = self.clock.monotonic() + duration
        discarded_frames = 0
        while self.clock.monotonic() < deadline:
            chunk = bytes(self.port.read(self.read_bytes))
            self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
            if chunk:
                before_errors = self.parser.errors
                discarded_frames += len(self.parser.feed(chunk))
                self._raise_new_parser_error(before_errors)
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
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
        hard_deadline: float | None = None,
    ) -> tuple[Frame, float]:
        request_id = self._allocate_request_id()
        wire = encode_request(request_kind, request_id, payload)
        started = self.clock.monotonic()
        deadline = started + timeout
        if hard_deadline is not None:
            deadline = min(deadline, hard_deadline)
        self._write_all(wire, deadline)
        expected_kind = REQUEST_RESPONSE_KIND[request_kind]
        while True:
            if self.clock.monotonic() >= deadline:
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
                require(
                    frame.kind == expected_kind,
                    "protocol",
                    f"request {request_id} got kind 0x{frame.kind:02x}, "
                    f"expected 0x{expected_kind:02x}",
                )
                require(matched is None, "protocol", "duplicate control response")
                matched = frame
            if matched is not None:
                if not matched.flags:
                    self.accepted_requests += 1
                return matched, self.clock.monotonic() - started

    def pump_once(self, on_data: Callable[[Frame], None]) -> int:
        chunk, frames = self._read_chunk_and_frames()
        for frame in frames:
            require(
                frame.kind in DATA_KINDS,
                "protocol",
                f"unsolicited response 0x{frame.kind:02x}",
            )
            on_data(frame)
        return len(chunk)

    def drain_until_quiet(
        self,
        on_data: Callable[[Frame], None],
        *,
        hard_deadline: float,
    ) -> None:
        deadline = min(
            self.clock.monotonic() + STOP_DRAIN_DEADLINE_SECONDS,
            hard_deadline,
        )
        quiet_since = self.clock.monotonic()
        while True:
            now = self.clock.monotonic()
            if now >= deadline:
                raise DeadlineExpired("post-STOP data did not drain before deadline")
            if now - quiet_since >= STOP_DRAIN_QUIET_SECONDS:
                require(
                    not self.parser.buffer,
                    "parser",
                    f"post-STOP parser retains {len(self.parser.buffer)} bytes",
                )
                return
            if self.pump_once(on_data):
                quiet_since = self.clock.monotonic()

    def _allocate_request_id(self) -> int:
        request_id = self.next_request_id
        self.next_request_id = (request_id + 1) & 0xFFFFFFFF
        if self.next_request_id == 0:
            self.next_request_id = 1
        return request_id

    def _write_all(self, wire: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(wire):
            if self.clock.monotonic() >= deadline:
                raise DeadlineExpired(
                    f"serial write stopped after {offset}/{len(wire)} bytes"
                )
            written = self.port.write(wire[offset:])
            if written is None:
                written = 0
            require(
                isinstance(written, int)
                and not isinstance(written, bool)
                and 0 <= written <= len(wire) - offset,
                "transport",
                f"serial write returned {written!r}",
            )
            offset += written
            if written == 0:
                self.clock.sleep(0.0001)

    def _read_once(self) -> list[Frame]:
        _chunk, frames = self._read_chunk_and_frames()
        return frames

    def _read_chunk_and_frames(self) -> tuple[bytes, list[Frame]]:
        chunk = bytes(self.port.read(self.read_bytes))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        if not chunk:
            return chunk, []
        before_errors = self.parser.errors
        frames = self.parser.feed(chunk)
        self._raise_new_parser_error(before_errors)
        return chunk, frames

    def _raise_new_parser_error(self, before_errors: int) -> None:
        if self.parser.errors == before_errors:
            return
        if self.parser.checksum_errors:
            category = "checksum_corruption"
        else:
            category = "parser"
        raise SoakFailure(
            category,
            "frame parser rejected wire bytes: "
            f"header={self.parser.header_errors} "
            f"checksum={self.parser.checksum_errors} "
            f"payload={self.parser.payload_errors}",
        )


def response_success(frame: Frame, expected_kind: int) -> None:
    if frame.kind != expected_kind or frame.flags:
        status, _reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        raise SoakFailure(
            "control",
            f"response kind=0x{frame.kind:02x} flags=0x{frame.flags:04x} "
            f"status={status} error={error}",
        )
    status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    require(
        status == 0 and reserved == 0 and error == 0,
        "protocol",
        "successful response prefix is invalid",
    )


def _u16(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", payload, offset)[0])


def _u32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", payload, offset)[0])


def _u64(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<Q", payload, offset)[0])


def decode_info(frame: Frame) -> dict[str, object]:
    response_success(frame, INFO_RESPONSE)
    payload = frame.payload
    build_field = payload[66:98]
    try:
        terminator = build_field.index(0)
        build_id = build_field[:terminator].decode("ascii")
    except (ValueError, UnicodeDecodeError) as error:
        raise SoakFailure("identity", "INFO build ID is not NUL ASCII") from error
    require(
        not any(build_field[terminator + 1 :]),
        "identity",
        "INFO build ID padding is nonzero",
    )
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
        "applied_stream_mask": payload[324],
        "applied_source": payload[325],
        "supported_configuration_mask": _u16(payload, 326),
        "data_payload_bytes": _u16(payload, 328),
        "adc_pairs_per_frame": _u16(payload, 330),
        "gpio_samples_per_frame": _u16(payload, 332),
        "frame_coverage_ticks": _u32(payload, 336),
        "adc_dma_ring_depth": payload[340],
        "adc_pair_bytes": payload[341],
        "packet_buffer_count": _u16(payload, 356),
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
    require(reserved == 0, "protocol", "applied configuration reserved byte")
    return streams, source, checksum, frame_bytes


def stable_identity(info: Mapping[str, object]) -> tuple[object, ...]:
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
            "supported_checksum_mask",
            "supported_configuration_mask",
            "capability_bits",
        )
    )


def synchronize(
    link: SerialLink,
    *,
    hard_deadline: float,
) -> tuple[dict[str, object], list[float]]:
    previous: dict[str, object] | None = None
    latencies: list[float] = []
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, latency = link.exchange(
                INFO_REQUEST,
                timeout=SYNC_DEADLINE_SECONDS,
                hard_deadline=hard_deadline,
            )
            current = decode_info(frame)
            latencies.append(latency)
        except SoakFailure as error:
            last_error = str(error)
            emit_event("sync_retry", attempt=attempt, error=last_error)
            continue
        if previous is not None:
            require(
                stable_identity(previous) == stable_identity(current),
                "identity",
                "INFO identity changed during synchronization",
            )
            emit_event("synchronized", attempts=attempt)
            return current, latencies
        previous = current
    raise DeadlineExpired(
        f"stable INFO synchronization failed after {SYNC_ATTEMPTS} attempts: "
        f"{last_error}"
    )


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
_PHYSICAL_STOP_TAIL_FIELDS = frozenset(
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
            if name not in _STATUS_NON_MONOTONIC_FIELDS
            and value < previous.values[name]
        }


def decode_status(frame: Frame) -> StatusSnapshot:
    response_success(frame, GET_STATUS_RESPONSE)
    payload = frame.payload
    values = {
        name: int(struct.unpack_from("<" + code, payload, offset)[0])
        for name, (code, offset) in _STATUS_BASE_FIELDS.items()
    }
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
    return StatusSnapshot(values)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SoakFailure("configuration", f"{name} is not an object")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SoakFailure("configuration", f"{name} must be an integer >= {minimum}")
    return value


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SoakFailure("configuration", f"{name} must be finite and >= {minimum}")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise SoakFailure("configuration", f"{name} must be finite and >= {minimum}")
    return result


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SoakFailure("configuration", f"{name} empty")
    return value


@dataclass(frozen=True)
class RuntimeSettings:
    mode: str
    protocol_version: int
    checksum_algorithm: int
    checksum_name: str
    firmware_version: tuple[int, int, int]
    build_id: str
    source_id: str
    artifact_name: str
    artifact_sha256: str
    fqbn: str
    hardware_serial: int
    board_id: int
    mcu_id: int
    measured_duration_seconds: float
    warmup_seconds: float
    status_interval_seconds: float
    info_interval_seconds: float
    control_epoch_seconds: float
    control_reopen_every_epochs: int
    hard_deadline_seconds: float
    service_container_limit_seconds: float
    serial_read_bytes: int
    candidate_sha256: str
    validator_sha256: str


def load_settings(config: Mapping[str, object] = GENERATED_CONFIG) -> RuntimeSettings:
    mode = _string(config.get("mode"), "mode")
    require(mode in SUPPORTED_MODES, "configuration", f"unsupported mode {mode!r}")
    candidate = _mapping(config.get("candidate"), "candidate")
    artifact = _mapping(candidate.get("artifact"), "candidate.artifact")
    board = _mapping(candidate.get("board"), "candidate.board")
    firmware = _mapping(candidate.get("firmware"), "candidate.firmware")
    protocol = _mapping(candidate.get("protocol"), "candidate.protocol")
    soak = _mapping(candidate.get("soak"), "candidate.soak")

    raw_version = firmware.get("version")
    if not (
        isinstance(raw_version, list)
        and len(raw_version) == 3
        and all(isinstance(value, int) and 0 <= value <= 255 for value in raw_version)
    ):
        raise SoakFailure(
            "configuration", "firmware.version must contain three uint8 values"
        )
    version: tuple[int, int, int] = (
        int(raw_version[0]),
        int(raw_version[1]),
        int(raw_version[2]),
    )
    source_id = _string(firmware.get("source_id"), "firmware.source_id")
    artifact_sha256 = _string(artifact.get("sha256"), "artifact.sha256")
    for name, digest in (
        ("source_id", source_id),
        ("artifact.sha256", artifact_sha256),
    ):
        require(
            len(digest) == 64
            and digest == digest.lower()
            and all(character in "0123456789abcdef" for character in digest),
            "configuration",
            f"{name} must be lowercase SHA-256",
        )

    measured = _number(
        soak.get("measured_duration_seconds"),
        "soak.measured_duration_seconds",
        minimum=1.0,
    )
    warmup = _number(soak.get("warmup_seconds"), "soak.warmup_seconds")
    status_interval = _number(
        soak.get("status_interval_seconds"),
        "soak.status_interval_seconds",
        minimum=0.05,
    )
    info_interval = _number(
        soak.get("info_interval_seconds"),
        "soak.info_interval_seconds",
        minimum=status_interval,
    )
    hard_deadline = _number(
        soak.get("hard_deadline_seconds"),
        "soak.hard_deadline_seconds",
        minimum=measured + warmup + MINIMUM_DEADLINE_RESERVE_SECONDS,
    )
    service_limit = _number(
        soak.get("service_container_limit_seconds"),
        "soak.service_container_limit_seconds",
        minimum=hard_deadline + MINIMUM_DEADLINE_RESERVE_SECONDS,
    )
    require(
        hard_deadline < service_limit,
        "configuration",
        "script hard deadline must precede the service container limit",
    )
    require(
        math.ceil((measured + warmup) / status_interval) <= MAX_STATUS_SAMPLES,
        "configuration",
        "configured STATUS count exceeds its memory bound",
    )
    protocol_version = _integer(protocol.get("version"), "protocol.version", minimum=1)
    checksum_algorithm = _integer(
        protocol.get("checksum_algorithm"),
        "protocol.checksum_algorithm",
        minimum=1,
    )
    require(
        protocol_version == PROTOCOL_VERSION and checksum_algorithm == CHECKSUM_ADLER32,
        "configuration",
        "canonical validator supports the pinned protocol-v1 Adler-32 candidate",
    )
    build_id = _string(firmware.get("build_id"), "firmware.build_id")
    require(
        build_id == f"tdaq-{source_id[:16]}",
        "configuration",
        "build ID does not derive from the source ID",
    )
    return RuntimeSettings(
        mode=mode,
        protocol_version=protocol_version,
        checksum_algorithm=checksum_algorithm,
        checksum_name=_string(protocol.get("checksum_name"), "protocol.checksum_name"),
        firmware_version=version,
        build_id=build_id,
        source_id=source_id,
        artifact_name=_string(artifact.get("name"), "artifact.name"),
        artifact_sha256=artifact_sha256,
        fqbn=_string(board.get("fqbn"), "board.fqbn"),
        hardware_serial=_integer(
            board.get("hardware_serial"), "board.hardware_serial", minimum=1
        ),
        board_id=_integer(board.get("board_id"), "board.board_id", minimum=1),
        mcu_id=_integer(board.get("mcu_id"), "board.mcu_id", minimum=1),
        measured_duration_seconds=measured,
        warmup_seconds=warmup,
        status_interval_seconds=status_interval,
        info_interval_seconds=info_interval,
        control_epoch_seconds=_number(
            soak.get("control_epoch_seconds"),
            "soak.control_epoch_seconds",
            minimum=5.0,
        ),
        control_reopen_every_epochs=_integer(
            soak.get("control_reopen_every_epochs"),
            "soak.control_reopen_every_epochs",
            minimum=1,
        ),
        hard_deadline_seconds=hard_deadline,
        service_container_limit_seconds=service_limit,
        serial_read_bytes=(
            SYNTHETIC_SERIAL_READ_BYTES
            if mode == "synthetic"
            else PHYSICAL_SERIAL_READ_BYTES
        ),
        candidate_sha256=_string(config.get("candidate_sha256"), "candidate_sha256"),
        validator_sha256=_string(config.get("validator_sha256"), "validator_sha256"),
    )


def validate_info_identity(
    info: Mapping[str, object],
    settings: RuntimeSettings,
    *,
    expected_state: int | None = None,
    expected_source: int | None = None,
) -> None:
    expected = {
        "protocol_version": settings.protocol_version,
        "hardware_serial": settings.hardware_serial,
        "firmware_version": settings.firmware_version,
        "board_id": settings.board_id,
        "mcu_id": settings.mcu_id,
        "build_id": settings.build_id,
        "supported_stream_mask": EXPECTED_STREAM_MASK,
        "supported_source_mask": EXPECTED_SOURCE_MASK,
        "supported_checksum_mask": EXPECTED_CHECKSUM_MASK,
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
        "adc_container_bytes": 2,
        "gpio_pin_count": len(GPIO_PINS_BY_BIT),
        "data_checksum_algorithm": settings.checksum_algorithm,
        "gpio_pin_map": GPIO_PINS_BY_BIT,
        "supported_configuration_mask": EXPECTED_CONFIGURATION_MASK,
        "data_payload_bytes": DATA_PAYLOAD_BYTES,
        "adc_pairs_per_frame": ADC_PAIRS_PER_FRAME,
        "gpio_samples_per_frame": GPIO_SAMPLES_PER_FRAME,
        "frame_coverage_ticks": FRAME_COVERAGE_TICKS,
        "adc_dma_ring_depth": ADC_RAW_RING_DEPTH,
        "adc_pair_bytes": ADC_BYTES_PER_PAIR,
        "packet_buffer_count": PACKET_BUFFER_COUNT,
        "packet_ready_queue_capacity": PACKET_QUEUE_CAPACITY,
        "packet_transmit_queue_capacity": PACKET_QUEUE_CAPACITY,
        "command_queue_capacity": COMMAND_QUEUE_CAPACITY,
        "response_queue_capacity": RESPONSE_QUEUE_CAPACITY,
        "nominal_payload_bytes_per_second_per_stream": 4_000_000,
        "nominal_framed_bytes_per_second_per_stream": 4_047_431,
    }
    mismatches = {
        name: {"expected": value, "actual": info.get(name)}
        for name, value in expected.items()
        if info.get(name) != value
    }
    require(
        not mismatches,
        "identity",
        "INFO identity/capability mismatch: "
        + json.dumps(mismatches, sort_keys=True, separators=(",", ":")),
    )
    if expected_state is not None:
        require(
            info.get("device_state") == expected_state,
            "control",
            f"INFO state {info.get('device_state')} != {expected_state}",
        )
        expected_stream_mask = (
            STREAM_NONE if expected_state == STATE_IDLE else STREAM_BOTH
        )
        require(
            info.get("applied_stream_mask") == expected_stream_mask,
            "control",
            "INFO applied stream mask "
            f"{info.get('applied_stream_mask')} != {expected_stream_mask}",
        )
    if expected_source is not None:
        require(
            info.get("applied_source") == expected_source,
            "control",
            f"INFO source {info.get('applied_source')} != {expected_source}",
        )


class BoundedLatency:
    """Bounded exact latency distribution for the configured campaign."""

    def __init__(self) -> None:
        self.samples: list[float] = []

    def add(self, value: float) -> None:
        require(value >= 0 and math.isfinite(value), "latency", "invalid latency")
        require(
            len(self.samples) < MAX_LATENCY_SAMPLES,
            "latency",
            "latency sample bound exhausted",
        )
        self.samples.append(value)

    @staticmethod
    def _percentile(ordered: list[float], fraction: float) -> float | None:
        if not ordered:
            return None
        index = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[index]

    def summary(self) -> dict[str, float | int | None]:
        ordered = sorted(self.samples)
        return {
            "count": len(ordered),
            "minimum_seconds": ordered[0] if ordered else None,
            "p50_seconds": self._percentile(ordered, 0.50),
            "p95_seconds": self._percentile(ordered, 0.95),
            "p99_seconds": self._percentile(ordered, 0.99),
            "maximum_seconds": ordered[-1] if ordered else None,
        }

    def merge(self, other: BoundedLatency) -> None:
        for value in other.samples:
            self.add(value)


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    return value if sys.platform == "darwin" else value * 1_024


def _current_rss_bytes() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return _peak_rss_bytes()


def _available_process_memory_bytes() -> int | None:
    try:
        with open("/sys/fs/cgroup/memory.max", encoding="ascii") as handle:
            limit_text = handle.read().strip()
        with open("/sys/fs/cgroup/memory.current", encoding="ascii") as handle:
            used = int(handle.read().strip())
        if limit_text != "max":
            return max(0, int(limit_text) - used)
    except (FileNotFoundError, OSError, ValueError):
        pass
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1_024
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None
    return None


def _cgroup_cpu_statistics() -> dict[str, int]:
    """Read normalized cgroup CPU counters without probing during streaming."""

    paths = ("/sys/fs/cgroup/cpu.stat", "/sys/fs/cgroup/cpu/cpu.stat")
    for path in paths:
        try:
            with open(path, encoding="ascii") as handle:
                values = {
                    parts[0]: int(parts[1])
                    for line in handle
                    if len(parts := line.split()) == 2
                }
        except (FileNotFoundError, OSError, ValueError):
            continue
        if "throttled_time" in values and "throttled_usec" not in values:
            values["throttled_usec"] = values["throttled_time"] // 1_000
        return values
    return {}


class CpuTracker:
    """Boundary-only cgroup quota evidence for host-stall classification."""

    def __init__(self) -> None:
        self.baseline = _cgroup_cpu_statistics()
        self.final = dict(self.baseline)

    def sample(self) -> None:
        self.final = _cgroup_cpu_statistics()

    def summary(self) -> dict[str, object]:
        delta = {
            name: max(0, value - self.baseline[name])
            for name, value in self.final.items()
            if name in self.baseline
        }
        return {
            "coverage": "control boundaries only",
            "baseline": self.baseline,
            "final": self.final,
            "delta": delta,
        }


class MemoryTracker:
    """Boundary tracing plus continuous process RSS high-water evidence.

    Tracing every short-lived frame and payload allocation materially reduces
    throughput in the service's Alpine container.  Keep ``tracemalloc`` and
    filesystem-backed current/available-memory probes at control boundaries;
    during full-rate streaming, sample only the kernel-maintained process RSS
    high water so memory evidence cannot itself backpressure the device.
    """

    def __init__(self) -> None:
        tracemalloc.start()
        self.baseline_traced_bytes, _peak = tracemalloc.get_traced_memory()
        self.baseline_rss_bytes = _current_rss_bytes()
        self.baseline_peak_rss_bytes = _peak_rss_bytes()
        self.maximum_traced_bytes = self.baseline_traced_bytes
        self.maximum_traced_peak_bytes = self.baseline_traced_bytes
        self.maximum_rss_bytes = self.baseline_rss_bytes
        self.maximum_peak_rss_bytes = self.baseline_peak_rss_bytes
        self.minimum_available_bytes = _available_process_memory_bytes()
        self.final_traced_bytes = self.baseline_traced_bytes
        self.final_rss_bytes = self.baseline_rss_bytes
        self.samples = 0
        self.streaming_samples = 0
        self.streaming_windows = 0
        self.streaming_active = False
        self.checkpoints: list[dict[str, int | None]] = []
        self.sample(checkpoint=True)

    def sample(self, *, checkpoint: bool = False) -> None:
        current_traced, peak_traced = tracemalloc.get_traced_memory()
        current_rss = _current_rss_bytes()
        peak_rss = _peak_rss_bytes()
        available = _available_process_memory_bytes()
        self.samples += 1
        self.final_traced_bytes = current_traced
        self.final_rss_bytes = current_rss
        self.maximum_traced_bytes = max(self.maximum_traced_bytes, current_traced)
        self.maximum_traced_peak_bytes = max(
            self.maximum_traced_peak_bytes, peak_traced
        )
        if current_rss is not None:
            self.maximum_rss_bytes = max(self.maximum_rss_bytes or 0, current_rss)
        if peak_rss is not None:
            self.maximum_peak_rss_bytes = max(
                self.maximum_peak_rss_bytes or 0, peak_rss
            )
        if available is not None:
            self.minimum_available_bytes = min(
                self.minimum_available_bytes
                if self.minimum_available_bytes is not None
                else available,
                available,
            )
        if checkpoint and len(self.checkpoints) < MAX_COUNTER_SAMPLES:
            self.checkpoints.append(
                {
                    "traced_bytes": current_traced,
                    "rss_bytes": current_rss,
                    "peak_rss_bytes": peak_rss,
                    "available_bytes": available,
                }
            )

    def begin_streaming(self) -> None:
        """Pause allocation tracing before one full-rate acquisition epoch."""

        require(
            not self.streaming_active,
            "memory_growth",
            "memory tracker streaming window is already active",
        )
        self.sample(checkpoint=True)
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        self.streaming_active = True
        self.streaming_windows += 1

    def sample_streaming(self, *, checkpoint: bool = False) -> None:
        """Record the OS process high water without allocating payload traces."""

        require(
            self.streaming_active,
            "memory_growth",
            "streaming memory sample is outside an acquisition epoch",
        )
        peak_rss = _peak_rss_bytes()
        self.samples += 1
        self.streaming_samples += 1
        if peak_rss is not None:
            self.maximum_peak_rss_bytes = max(
                self.maximum_peak_rss_bytes or 0,
                peak_rss,
            )
        if checkpoint and len(self.checkpoints) < MAX_COUNTER_SAMPLES:
            self.checkpoints.append(
                {
                    "traced_bytes": None,
                    "rss_bytes": None,
                    "peak_rss_bytes": peak_rss,
                    "available_bytes": None,
                }
            )

    def end_streaming(self) -> None:
        """Resume allocation tracing and take a complete boundary sample."""

        if not self.streaming_active:
            return
        self.streaming_active = False
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        self.sample(checkpoint=True)

    @property
    def traced_growth_bytes(self) -> int:
        return max(0, self.maximum_traced_bytes - self.baseline_traced_bytes)

    @property
    def rss_growth_bytes(self) -> int | None:
        if (
            self.baseline_peak_rss_bytes is not None
            and self.maximum_peak_rss_bytes is not None
        ):
            return max(
                0,
                self.maximum_peak_rss_bytes - self.baseline_peak_rss_bytes,
            )
        if self.baseline_rss_bytes is not None and self.maximum_rss_bytes is not None:
            return max(0, self.maximum_rss_bytes - self.baseline_rss_bytes)
        return None

    def summary(self) -> dict[str, object]:
        return {
            "sample_count": self.samples,
            "coverage": {
                "tracemalloc": "control-and-epoch-boundaries",
                "process_rss_peak": "sampled-throughout-streaming",
                "available_memory": "control-and-epoch-boundaries",
                "streaming_samples": self.streaming_samples,
                "streaming_windows": self.streaming_windows,
            },
            "tracemalloc": {
                "baseline_bytes": self.baseline_traced_bytes,
                "final_bytes": self.final_traced_bytes,
                "maximum_current_bytes": self.maximum_traced_bytes,
                "peak_bytes": self.maximum_traced_peak_bytes,
                "growth_bytes": self.traced_growth_bytes,
            },
            "process_rss": {
                "baseline_bytes": self.baseline_rss_bytes,
                "final_bytes": self.final_rss_bytes,
                "maximum_current_bytes": self.maximum_rss_bytes,
                "peak_bytes": self.maximum_peak_rss_bytes,
                "growth_bytes": self.rss_growth_bytes,
            },
            "minimum_available_bytes": self.minimum_available_bytes,
            "bounded_checkpoints": self.checkpoints,
        }


class BoundedSamples:
    """Retain fixed first/last diagnostic samples without retaining payloads."""

    def __init__(self, limit: int = MAX_DIAGNOSTIC_SAMPLES) -> None:
        self.first_limit = max(1, limit // 2)
        self.first: list[dict[str, object]] = []
        self.last: deque[dict[str, object]] = deque(maxlen=limit - self.first_limit)
        self.total = 0

    def add(self, value: dict[str, object]) -> None:
        self.total += 1
        if len(self.first) < self.first_limit:
            self.first.append(value)
        else:
            self.last.append(value)

    def summary(self) -> dict[str, object]:
        return {"total": self.total, "first": self.first, "last": list(self.last)}


def _build_adc_pattern() -> bytes:
    period_pairs = 1 << (ADC_RESOLUTION_BITS - 1)
    result = bytearray(period_pairs * ADC_BYTES_PER_PAIR)
    for pair_index in range(period_pairs):
        struct.pack_into(
            "<HH",
            result,
            pair_index * ADC_BYTES_PER_PAIR,
            (2 * pair_index) & 0x0FFF,
            (2 * pair_index + 1) & 0x0FFF,
        )
    return bytes(result)


ADC_PATTERN = _build_adc_pattern()
ADC_PATTERN_DOUBLE = ADC_PATTERN + ADC_PATTERN
GPIO_PATTERN_EXPANDED = bytes(range(256)) * 17
ADC_PHYSICAL_OUT_OF_RANGE_MASK = int.from_bytes(
    b"\x00\xf0" * (DATA_PAYLOAD_BYTES // 2), "little"
)


@dataclass
class StreamTotals:
    expected_sequence: int = 0
    expected_ticks: int = 0
    frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0

    def snapshot(self) -> tuple[int, int, int, int]:
        return self.frames, self.items, self.payload_bytes, self.framed_bytes


class StreamValidator:
    """Rolling formula/continuity validator shared by every soak mode."""

    def __init__(
        self,
        run_id: int,
        source: int,
        checksum_algorithm: int,
        clock: Clock,
    ) -> None:
        require(1 <= run_id <= 0xFFFFFFFF, "control", "START returned run ID zero")
        require(source in {SOURCE_HARDWARE, SOURCE_SYNTHETIC}, "control", "source")
        self.run_id = run_id
        self.source = source
        self.checksum_algorithm = checksum_algorithm
        self.clock = clock
        self.adc = StreamTotals()
        self.gpio = StreamTotals()
        self.maximum_frame_skew = 0
        self.maximum_receive_gap_seconds = 0.0
        self.last_received_at: float | None = None
        self.adc_minimums = [0xFFFF, 0xFFFF]
        self.adc_maximums = [0, 0]
        self.gpio_and = 0xFF
        self.gpio_or = 0
        self.diagnostics = BoundedSamples()

    def accept(self, frame: Frame) -> None:
        received_at = self.clock.monotonic()
        if self.last_received_at is not None:
            self.maximum_receive_gap_seconds = max(
                self.maximum_receive_gap_seconds,
                received_at - self.last_received_at,
            )
        self.last_received_at = received_at
        require(
            frame.run_id == self.run_id,
            "stale_run",
            f"data run ID {frame.run_id} != {self.run_id}",
        )
        require(
            frame.checksum_algorithm == self.checksum_algorithm,
            "checksum_corruption",
            "data checksum selection changed",
        )
        expected_synthetic = self.source == SOURCE_SYNTHETIC
        require(
            bool(frame.flags & FLAG_SYNTHETIC) == expected_synthetic,
            "source",
            "data SYNTHETIC flag disagrees with configured source",
        )
        require(
            not frame.flags & (FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE),
            "source_gap",
            f"frame kind=0x{frame.kind:02x} sequence={frame.sequence} carries gap",
        )
        totals = self.adc if frame.kind == ADC_DATA else self.gpio
        expected_flags = FLAG_SYNTHETIC if expected_synthetic else 0
        if totals.frames == 0:
            expected_flags |= FLAG_EPOCH_START
        require(
            frame.flags == expected_flags,
            "source_gap",
            f"frame flags 0x{frame.flags:04x} != 0x{expected_flags:04x}",
        )
        require(
            frame.sequence == totals.expected_sequence,
            "source_gap",
            f"kind 0x{frame.kind:02x} sequence {frame.sequence} "
            f"!= {totals.expected_sequence}",
        )
        require(
            frame.first_sample_ticks == totals.expected_ticks,
            "timestamp",
            f"kind 0x{frame.kind:02x} timestamp {frame.first_sample_ticks} "
            f"!= {totals.expected_ticks}",
        )
        if frame.kind == ADC_DATA:
            self._validate_adc(frame)
        else:
            self._validate_gpio(frame)
        totals.frames += 1
        totals.items += frame.item_count
        totals.payload_bytes += len(frame.payload)
        totals.framed_bytes += DATA_FRAME_BYTES
        totals.expected_sequence = (frame.sequence + 1) & 0xFFFFFFFF
        totals.expected_ticks = (
            frame.first_sample_ticks + FRAME_COVERAGE_TICKS
        ) & 0xFFFFFFFFFFFFFFFF
        skew = abs(self.adc.frames - self.gpio.frames)
        self.maximum_frame_skew = max(self.maximum_frame_skew, skew)
        require(
            skew <= 1,
            "source_gap",
            f"combined fair-scheduler frame skew reached {skew}",
        )
        self.diagnostics.add(
            {
                "kind": "adc" if frame.kind == ADC_DATA else "gpio",
                "sequence": frame.sequence,
                "first_sample_ticks": frame.first_sample_ticks,
                "flags": frame.flags,
                "payload_head_hex": frame.payload[:8].hex(),
                "payload_tail_hex": frame.payload[-8:].hex(),
            }
        )

    def _validate_adc(self, frame: Frame) -> None:
        require(
            frame.item_count == ADC_PAIRS_PER_FRAME
            and len(frame.payload) == DATA_PAYLOAD_BYTES,
            "protocol",
            "ADC frame item/payload size mismatch",
        )
        if self.source == SOURCE_SYNTHETIC:
            start_pair = frame.first_sample_ticks // ADC_PAIR_PERIOD_TICKS
            offset = (start_pair * ADC_BYTES_PER_PAIR) % len(ADC_PATTERN)
            expected = ADC_PATTERN_DOUBLE[offset : offset + DATA_PAYLOAD_BYTES]
            if frame.payload != expected:
                for pair_offset in range(ADC_PAIRS_PER_FRAME):
                    observed = struct.unpack_from(
                        "<HH", frame.payload, pair_offset * ADC_BYTES_PER_PAIR
                    )
                    pair_index = start_pair + pair_offset
                    expected_pair = (
                        (2 * pair_index) & 0x0FFF,
                        (2 * pair_index + 1) & 0x0FFF,
                    )
                    if observed != expected_pair:
                        raise SoakFailure(
                            "pattern_error",
                            f"ADC pair {pair_index} is {observed}, "
                            f"expected {expected_pair}",
                        )
                raise SoakFailure("pattern_error", "ADC formula bytes differ")
            return

        require(
            int.from_bytes(frame.payload, "little") & ADC_PHYSICAL_OUT_OF_RANGE_MASK
            == 0,
            "physical_range",
            "physical ADC payload contains a code above 4095",
        )
        if self.adc.frames == 0:
            values = struct.unpack(f"<{2 * ADC_PAIRS_PER_FRAME}H", frame.payload)
            for channel in range(2):
                channel_values = values[channel::2]
                self.adc_minimums[channel] = min(channel_values)
                self.adc_maximums[channel] = max(channel_values)

    def _validate_gpio(self, frame: Frame) -> None:
        require(
            frame.item_count == GPIO_SAMPLES_PER_FRAME
            and len(frame.payload) == DATA_PAYLOAD_BYTES,
            "protocol",
            "GPIO frame item/payload size mismatch",
        )
        if self.source == SOURCE_SYNTHETIC:
            start_sample = frame.first_sample_ticks // GPIO_SAMPLE_PERIOD_TICKS
            offset = start_sample & 0xFF
            expected = GPIO_PATTERN_EXPANDED[offset : offset + DATA_PAYLOAD_BYTES]
            if frame.payload != expected:
                for sample_offset, observed in enumerate(frame.payload):
                    sample_index = start_sample + sample_offset
                    expected_sample = sample_index & 0xFF
                    if observed != expected_sample:
                        raise SoakFailure(
                            "pattern_error",
                            f"GPIO sample {sample_index} is {observed}, "
                            f"expected {expected_sample}",
                        )
                raise SoakFailure("pattern_error", "GPIO formula bytes differ")
            return
        if self.gpio.frames == 0:
            for value in set(frame.payload):
                self.gpio_and &= value
                self.gpio_or |= value


QUEUE_FIELDS = (
    "gpio_raw_ready_depth",
    "gpio_raw_ready_high_water",
    "gpio_packed_ready_depth",
    "gpio_packed_ready_high_water",
    "packet_ready_depth",
    "packet_transmit_depth",
    "packet_owned_high_water",
    "adc_raw_ready_depth",
    "adc_raw_ready_high_water",
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
    "usb_command_queue_depth",
    "usb_response_queue_depth",
    "usb_command_queue_high_water",
    "usb_response_queue_high_water",
)


class StatusRollup:
    """Bounded queue maxima, counter endpoints, and representative snapshots."""

    def __init__(self) -> None:
        self.count = 0
        self.first_counters: dict[str, int] | None = None
        self.final_counters: dict[str, int] | None = None
        self.maximum_queues = {name: 0 for name in QUEUE_FIELDS}
        self.samples = BoundedSamples(MAX_COUNTER_SAMPLES)

    def observe(self, status: StatusSnapshot) -> None:
        self.count += 1
        if self.first_counters is None:
            self.first_counters = dict(status.values)
        self.final_counters = dict(status.values)
        for name in QUEUE_FIELDS:
            self.maximum_queues[name] = max(
                self.maximum_queues[name], status.values[name]
            )
        self.samples.add(
            {
                "state": status.device_state,
                "generation": status.stats_generation,
                "adc_frames": status.adc_frames_emitted,
                "gpio_frames": status.gpio_frames_emitted,
                "adc_drop": status.adc_items_dropped,
                "gpio_drop": status.gpio_items_dropped,
                "packet_ready_depth": status.packet_ready_depth,
                "packet_transmit_depth": status.packet_transmit_depth,
                "packet_owned_high_water": status.packet_owned_high_water,
            }
        )

    def summary(self) -> dict[str, object]:
        return {
            "count": self.count,
            "maximum_queues": self.maximum_queues,
            "bounded_snapshots": self.samples.summary(),
            "first_counters": self.first_counters,
            "final_counters": self.final_counters,
        }


def _nonzero_errors(
    status: StatusSnapshot,
    *,
    allow_physical_stop_tail: bool,
) -> dict[str, int]:
    return {
        name: status.values[name]
        for name in _ZERO_ERROR_FIELDS
        if status.values[name]
        and (not allow_physical_stop_tail or name not in _PHYSICAL_STOP_TAIL_FIELDS)
    }


def validate_status_invariants(
    status: StatusSnapshot,
    *,
    source: int,
    allow_physical_stop_tail: bool = False,
) -> None:
    errors = _nonzero_errors(status, allow_physical_stop_tail=allow_physical_stop_tail)
    require(
        not errors,
        "counter_disagreement",
        "STATUS loss/error counters are nonzero: "
        + json.dumps(errors, sort_keys=True, separators=(",", ":")),
    )
    if allow_physical_stop_tail:
        adc_tail = status.adc_stop_pairs_discarded
        gpio_tail = status.gpio_raw_samples_lost
        require(
            source == SOURCE_HARDWARE
            and 0 <= adc_tail < 2 * ADC_PAIRS_PER_FRAME
            and status.adc_raw_pairs_lost == adc_tail
            and status.adc_items_dropped == adc_tail
            and 0 <= status.adc_incomplete_buffers <= 2
            and 0 <= status.adc_completion_mismatches <= status.adc_incomplete_buffers
            and 0 <= status.adc_incomplete_conversions <= adc_tail
            and (adc_tail == 0) == (status.adc_incomplete_buffers == 0)
            and 0 <= gpio_tail < GPIO_SAMPLES_PER_FRAME
            and status.gpio_items_dropped == gpio_tail,
            "counter_disagreement",
            "physical STOP-tail counters do not reconcile",
        )

    for prefix, items_per_frame, item_bytes in (
        ("adc", ADC_PAIRS_PER_FRAME, ADC_BYTES_PER_PAIR),
        ("gpio", GPIO_SAMPLES_PER_FRAME, 1),
    ):
        generated = status.values[f"{prefix}_frames_generated"]
        framed = status.values[f"{prefix}_frames_framed_pipeline"]
        emitted = status.values[f"{prefix}_frames_emitted"]
        transmitted = status.values[f"{prefix}_frames_transmitted"]
        require(
            generated >= framed >= emitted >= transmitted,
            "counter_disagreement",
            f"{prefix} frame stages are not conservative",
        )
        expected_items = {
            f"{prefix}_items_generated": generated * items_per_frame,
            f"{prefix}_items_framed_pipeline": framed * items_per_frame,
            f"{prefix}_items_emitted": emitted * items_per_frame,
            f"{prefix}_items_transmitted_pipeline": transmitted * items_per_frame,
        }
        for name, expected in expected_items.items():
            require(
                status.values[name] == expected,
                "counter_disagreement",
                f"{name}={status.values[name]} != {expected}",
            )
        expected_bytes = {
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
        for name, expected in expected_bytes.items():
            require(
                status.values[name] == expected,
                "counter_disagreement",
                f"{name}={status.values[name]} != {expected}",
            )

    require(
        status.adc_pairs_framed == status.adc_items_framed_pipeline
        and status.adc_pairs_transmitted == status.adc_items_transmitted_pipeline
        and status.gpio_samples_framed == status.gpio_items_framed_pipeline
        and status.gpio_samples_transmitted == status.gpio_items_transmitted_pipeline,
        "counter_disagreement",
        "legacy and pipeline item counters disagree",
    )
    require(
        status.data_payload_bytes_transmitted
        == status.adc_payload_bytes_transmitted + status.gpio_payload_bytes_transmitted,
        "counter_disagreement",
        "combined payload bytes do not reconcile",
    )
    require(
        status.data_framed_bytes_transmitted
        == status.adc_framed_bytes_transmitted + status.gpio_framed_bytes_transmitted,
        "counter_disagreement",
        "combined framed bytes do not reconcile",
    )
    require(
        status.packet_accounted_frame_skew <= 1,
        "counter_disagreement",
        "packet accounted frame skew exceeds one",
    )

    queue_limits = {
        "gpio_raw_ready_depth": GPIO_RAW_RING_DEPTH,
        "gpio_raw_ready_high_water": GPIO_RAW_RING_DEPTH,
        "gpio_packed_ready_depth": GPIO_PACKED_RING_DEPTH,
        "gpio_packed_ready_high_water": GPIO_PACKED_RING_DEPTH,
        "adc_raw_ready_depth": ADC_RAW_RING_DEPTH,
        "adc_raw_ready_high_water": ADC_RAW_RING_DEPTH,
        "packet_ready_depth": PACKET_QUEUE_CAPACITY,
        "packet_transmit_depth": PACKET_QUEUE_CAPACITY,
        "packet_owned_high_water": PACKET_BUFFER_COUNT,
        "adc_packet_ready_depth": PACKET_QUEUE_CAPACITY,
        "gpio_packet_ready_depth": PACKET_QUEUE_CAPACITY,
        "adc_packet_transmit_depth": PACKET_QUEUE_CAPACITY,
        "gpio_packet_transmit_depth": PACKET_QUEUE_CAPACITY,
        "adc_packet_ready_high_water": PACKET_QUEUE_CAPACITY,
        "gpio_packet_ready_high_water": PACKET_QUEUE_CAPACITY,
        "adc_packet_transmit_high_water": PACKET_QUEUE_CAPACITY,
        "gpio_packet_transmit_high_water": PACKET_QUEUE_CAPACITY,
        "packet_ready_high_water": PACKET_QUEUE_CAPACITY,
        "packet_transmit_high_water": PACKET_QUEUE_CAPACITY,
        "usb_command_queue_depth": COMMAND_QUEUE_CAPACITY,
        "usb_response_queue_depth": RESPONSE_QUEUE_CAPACITY,
        "usb_command_queue_high_water": COMMAND_QUEUE_CAPACITY,
        "usb_response_queue_high_water": RESPONSE_QUEUE_CAPACITY,
    }
    for name, limit in queue_limits.items():
        require(
            0 <= status.values[name] <= limit,
            "queue_bound",
            f"{name}={status.values[name]} exceeds {limit}",
        )
    require(
        status.packet_ready_depth
        == status.adc_packet_ready_depth + status.gpio_packet_ready_depth
        and status.packet_transmit_depth
        == status.adc_packet_transmit_depth + status.gpio_packet_transmit_depth,
        "counter_disagreement",
        "aggregate and per-source packet depths disagree",
    )
    require(
        status.packet_ready_depth + status.packet_transmit_depth <= PACKET_BUFFER_COUNT,
        "queue_bound",
        "aggregate packet ownership exceeds the pool",
    )
    require(
        status.gpio_processing_cpu_basis_points <= 10_000,
        "counter_disagreement",
        "GPIO processing CPU exceeds 100 percent",
    )
    require(
        status.usb_active_frame_bytes_sent < DATA_FRAME_BYTES,
        "counter_disagreement",
        "USB active-frame offset exceeds one frame",
    )

    if source == SOURCE_HARDWARE:
        require(
            status.adc0_dma_results == status.adc0_dma_major_loops * ADC_PAIRS_PER_FRAME
            and status.adc1_dma_results
            == status.adc1_dma_major_loops * ADC_PAIRS_PER_FRAME,
            "counter_disagreement",
            "ADC DMA results disagree with major loops",
        )
        require(
            abs(status.adc0_dma_major_loops - status.adc1_dma_major_loops) <= 1
            and status.adc_paired_major_loops
            == min(status.adc0_dma_major_loops, status.adc1_dma_major_loops),
            "counter_disagreement",
            "ADC paired-channel barrier counters disagree",
        )
        require(
            status.adc_buffers_completed
            >= status.adc_buffers_acquired
            >= status.adc_buffers_released,
            "counter_disagreement",
            "ADC buffer stages are not monotonic",
        )
        require(
            status.adc_buffers_completed <= status.adc_paired_major_loops
            and status.adc_pairs_delivered
            == status.adc_buffers_acquired * ADC_PAIRS_PER_FRAME,
            "counter_disagreement",
            "ADC completed/delivered counts disagree with paired buffers",
        )
        require(
            status.adc_pairs_captured
            >= status.adc_pairs_delivered
            >= status.adc_pairs_framed
            >= status.adc_pairs_transmitted,
            "counter_disagreement",
            "ADC pair stages are not monotonic",
        )
        require(
            status.gpio_samples_captured
            >= status.gpio_samples_packed
            >= status.gpio_samples_framed
            >= status.gpio_samples_transmitted,
            "counter_disagreement",
            "GPIO sample stages are not monotonic",
        )
        require(
            status.gpio_samples_framed % GPIO_SAMPLES_PER_FRAME == 0
            and status.gpio_samples_transmitted % GPIO_SAMPLES_PER_FRAME == 0,
            "counter_disagreement",
            "GPIO framed/transmitted samples are not frame aligned",
        )

    for depth_name, high_water_name in (
        ("gpio_raw_ready_depth", "gpio_raw_ready_high_water"),
        ("gpio_packed_ready_depth", "gpio_packed_ready_high_water"),
        ("adc_raw_ready_depth", "adc_raw_ready_high_water"),
    ):
        require(
            status.values[depth_name] <= status.values[high_water_name],
            "queue_bound",
            f"{depth_name} exceeds {high_water_name}",
        )


def validate_status_identity(
    status: StatusSnapshot,
    frame: Frame,
    *,
    expected_state: int,
    expected_stream_mask: int,
    source: int,
    checksum_algorithm: int,
    expected_generation: int,
    run_id: int,
) -> None:
    actual = (
        status.device_state,
        status.stream_mask,
        status.source,
        status.checksum,
        status.data_frame_bytes,
        status.stats_generation,
        frame.run_id,
    )
    expected = (
        expected_state,
        expected_stream_mask,
        source,
        checksum_algorithm,
        DATA_FRAME_BYTES,
        expected_generation,
        run_id,
    )
    require(
        actual == expected,
        "counter_disagreement",
        f"STATUS identity {actual} != {expected}",
    )


def validate_running_status(
    status: StatusSnapshot,
    frame: Frame,
    validator: StreamValidator,
    *,
    expected_generation: int,
    expected_commands: int,
    host_adc_floor: int,
    host_gpio_floor: int,
    previous: StatusSnapshot | None,
) -> None:
    validate_status_identity(
        status,
        frame,
        expected_state=STATE_RUNNING,
        expected_stream_mask=STREAM_BOTH,
        source=validator.source,
        checksum_algorithm=validator.checksum_algorithm,
        expected_generation=expected_generation,
        run_id=validator.run_id,
    )
    validate_status_invariants(status, source=validator.source)
    require(
        status.adc_frames_emitted >= host_adc_floor
        and status.gpio_frames_emitted >= host_gpio_floor,
        "counter_disagreement",
        "firmware emitted-frame counters trail the pre-request host floor",
    )
    require(
        status.commands_accepted == expected_commands,
        "counter_disagreement",
        f"commands_accepted={status.commands_accepted} != {expected_commands}",
    )
    if previous is not None:
        regressions = status.regressions_from(previous)
        require(
            not regressions,
            "counter_disagreement",
            "running counters regressed: "
            + json.dumps(regressions, sort_keys=True, separators=(",", ":")),
        )


def reconcile_final_status(
    status: StatusSnapshot,
    frame: Frame,
    validator: StreamValidator,
    *,
    expected_generation: int,
    expected_commands: int,
) -> None:
    physical = validator.source == SOURCE_HARDWARE
    validate_status_identity(
        status,
        frame,
        expected_state=STATE_IDLE,
        expected_stream_mask=STREAM_NONE,
        source=SOURCE_HARDWARE,
        checksum_algorithm=BOOTSTRAP_CHECKSUM,
        expected_generation=expected_generation,
        run_id=validator.run_id,
    )
    validate_status_invariants(
        status,
        source=validator.source,
        allow_physical_stop_tail=physical,
    )
    adc_frames = validator.adc.frames
    gpio_frames = validator.gpio.frames
    adc_items = validator.adc.items
    gpio_items = validator.gpio.items
    common_exact = {
        "adc_frames_emitted": adc_frames,
        "gpio_frames_emitted": gpio_frames,
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
        "packet_frames_promoted": adc_frames + gpio_frames,
        "packet_accounted_frame_skew": abs(adc_frames - gpio_frames),
        "data_payload_bytes_transmitted": (
            validator.adc.payload_bytes + validator.gpio.payload_bytes
        ),
        "data_framed_bytes_transmitted": (
            validator.adc.framed_bytes + validator.gpio.framed_bytes
        ),
        "commands_accepted": expected_commands,
        "packet_ready_depth": 0,
        "packet_transmit_depth": 0,
        "adc_packet_ready_depth": 0,
        "gpio_packet_ready_depth": 0,
        "adc_packet_transmit_depth": 0,
        "gpio_packet_transmit_depth": 0,
        "usb_command_queue_depth": 0,
        "usb_response_queue_depth": 0,
        "usb_lower_priority_queue_depth": 0,
        "usb_active_frame_bytes_sent": 0,
    }
    for name, expected in common_exact.items():
        require(
            status.values[name] == expected,
            "counter_disagreement",
            f"final {name}={status.values[name]} != {expected}",
        )

    if physical:
        physical_exact = {
            "gpio_samples_captured": gpio_items + status.gpio_raw_samples_lost,
            "gpio_samples_packed": gpio_items,
            "gpio_samples_framed": gpio_items,
            "gpio_samples_transmitted": gpio_items,
            "gpio_dma_major_loops": gpio_frames,
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
            "gpio_raw_ready_depth": 0,
            "gpio_packed_ready_depth": 0,
            "adc_raw_ready_depth": 0,
        }
        for name, expected in physical_exact.items():
            require(
                status.values[name] == expected,
                "counter_disagreement",
                f"final {name}={status.values[name]} != {expected}",
            )
    else:
        require(
            all(status.values[name] == 0 for name in _PHYSICAL_STOP_TAIL_FIELDS),
            "counter_disagreement",
            "synthetic run has physical STOP-tail counters",
        )


FINAL_REPORT_FIELDS = (
    "device_state",
    "source",
    "stats_generation",
    "adc_frames_emitted",
    "gpio_frames_emitted",
    "adc_items_dropped",
    "gpio_items_dropped",
    "adc_pairs_captured",
    "adc_pairs_framed",
    "adc_pairs_transmitted",
    "gpio_samples_captured",
    "gpio_samples_framed",
    "gpio_samples_transmitted",
    "adc_frames_generated",
    "adc_frames_framed_pipeline",
    "adc_frames_transmitted",
    "gpio_frames_generated",
    "gpio_frames_framed_pipeline",
    "gpio_frames_transmitted",
    "adc_payload_bytes_produced",
    "adc_payload_bytes_framed",
    "adc_payload_bytes_transmitted",
    "gpio_payload_bytes_produced",
    "gpio_payload_bytes_framed",
    "gpio_payload_bytes_transmitted",
    "data_payload_bytes_transmitted",
    "data_framed_bytes_transmitted",
    "packet_frames_promoted",
    "packet_owned_high_water",
    "packet_ready_high_water",
    "packet_transmit_high_water",
    "adc_raw_ready_high_water",
    "gpio_raw_ready_high_water",
    "gpio_packed_ready_high_water",
    "commands_accepted",
    "partial_usb_writes",
    "usb_rx_stall_events",
    "usb_tx_stall_events",
    "adc_stop_pairs_discarded",
    "gpio_raw_samples_lost",
)


@dataclass
class EpochReport:
    index: int
    source: int
    run_id: int
    stats_generation: int
    started_offset_seconds: float
    completed_offset_seconds: float
    warmup_seconds: float
    measured_elapsed_seconds: float
    timed_adc_frames: int
    timed_gpio_frames: int
    timed_adc_items: int
    timed_gpio_items: int
    total_adc_frames: int
    total_gpio_frames: int
    total_adc_items: int
    total_gpio_items: int
    status_latency: dict[str, float | int | None]
    command_latency: dict[str, float | int | None]
    status_rollup: dict[str, object]
    final_counters: dict[str, int]
    diagnostics: dict[str, object]
    maximum_receive_gap_seconds: float
    parser: dict[str, int]

    @property
    def timed_payload_bytes(self) -> int:
        return self.timed_adc_items * ADC_BYTES_PER_PAIR + self.timed_gpio_items

    @property
    def timed_framed_bytes(self) -> int:
        return (self.timed_adc_frames + self.timed_gpio_frames) * DATA_FRAME_BYTES

    def as_dict(self) -> dict[str, object]:
        elapsed = self.measured_elapsed_seconds
        return {
            "index": self.index,
            "source": "synthetic" if self.source == SOURCE_SYNTHETIC else "hardware",
            "run_id": self.run_id,
            "stats_generation": self.stats_generation,
            "started_offset_seconds": self.started_offset_seconds,
            "completed_offset_seconds": self.completed_offset_seconds,
            "warmup_seconds": self.warmup_seconds,
            "measured_elapsed_seconds": elapsed,
            "timed": {
                "adc_frames": self.timed_adc_frames,
                "gpio_frames": self.timed_gpio_frames,
                "adc_pairs": self.timed_adc_items,
                "gpio_samples": self.timed_gpio_items,
                "payload_bytes": self.timed_payload_bytes,
                "framed_bytes": self.timed_framed_bytes,
                "adc_pair_rate_hz": self.timed_adc_items / elapsed,
                "gpio_sample_rate_hz": self.timed_gpio_items / elapsed,
                "payload_bytes_per_second": self.timed_payload_bytes / elapsed,
                "framed_bytes_per_second": self.timed_framed_bytes / elapsed,
            },
            "total": {
                "adc_frames": self.total_adc_frames,
                "gpio_frames": self.total_gpio_frames,
                "adc_pairs": self.total_adc_items,
                "gpio_samples": self.total_gpio_items,
            },
            "latency": {
                "status": self.status_latency,
                "all_commands": self.command_latency,
            },
            "status": self.status_rollup,
            "final_counters": self.final_counters,
            "diagnostic_samples": self.diagnostics,
            "maximum_receive_gap_seconds": self.maximum_receive_gap_seconds,
            "parser": self.parser,
            "fixture_scope": (
                {
                    "external_analog_stimulus": "not-declared",
                    "external_digital_stimulus": "not-declared",
                    "graded": (
                        "physical conversion/capture/DMA/packing/transport only"
                    ),
                }
                if self.source == SOURCE_HARDWARE
                else {"synthetic_formulas": "all-payload-items"}
            ),
        }


class PortFactory(Protocol):
    def __call__(self) -> SerialPort: ...


class SoakRunner:
    """Own serial lifecycle and execute continuous or control-stress epochs."""

    def __init__(
        self,
        settings: RuntimeSettings,
        port_factory: PortFactory,
        clock: Clock = time,
    ) -> None:
        self.settings = settings
        self.port_factory = port_factory
        self.clock = clock
        self.script_started_at = clock.monotonic()
        self.hard_deadline = self.script_started_at + settings.hard_deadline_seconds
        self.port: SerialPort | None = None
        self.link: SerialLink | None = None
        self.identity: dict[str, object] | None = None
        self.epochs: list[EpochReport] = []
        self.status_latency = BoundedLatency()
        self.command_latency = BoundedLatency()
        self.memory = MemoryTracker()
        self.cpu = CpuTracker()
        self.reopen_count = 0
        self.cleanup: dict[str, object] = {"attempted": False}
        self.active_epoch_index: int | None = None
        self.active_validator: StreamValidator | None = None
        self.active_status: StatusSnapshot | None = None

    def _check_budget(self, context: str, *, reserve: float = 0.0) -> None:
        remaining = self.hard_deadline - self.clock.monotonic()
        if remaining <= reserve:
            raise DeadlineExpired(
                f"script deadline has {remaining:.3f}s remaining during {context}; "
                f"needs {reserve:.3f}s"
            )

    def open_and_synchronize(self, *, reopened: bool = False) -> None:
        self._check_budget("serial open", reserve=5.0)
        self.port = self.port_factory()
        self.link = SerialLink(
            self.port,
            self.clock,
            read_bytes=self.settings.serial_read_bytes,
        )
        self.link.drain_startup(
            REOPEN_SETTLE_SECONDS if reopened else STARTUP_DRAIN_SECONDS
        )
        info, latencies = synchronize(self.link, hard_deadline=self.hard_deadline)
        for latency in latencies:
            self.command_latency.add(latency)
        validate_info_identity(info, self.settings, expected_state=STATE_IDLE)
        if self.identity is not None:
            require(
                stable_identity(info) == stable_identity(self.identity),
                "identity",
                "identity changed after CDC reopen",
            )
        self.identity = info

    def reopen(self) -> None:
        port = self.port
        if port is None:
            raise SoakFailure("control", "cannot reopen a closed session")
        port.close()
        self.port = None
        self.link = None
        self.clock.sleep(REOPEN_SETTLE_SECONDS)
        self.open_and_synchronize(reopened=True)
        self.reopen_count += 1
        emit_event("cdc_reopened", count=self.reopen_count)

    def run_epoch(
        self,
        *,
        index: int,
        source: int,
        measured_seconds: float,
        warmup_seconds: float,
        previous_run_id: int | None,
    ) -> EpochReport:
        link = self.link
        if link is None:
            raise SoakFailure("control", "serial link is not open")
        epoch_started_offset = self.clock.monotonic() - self.script_started_at
        self._check_budget(
            "epoch start",
            reserve=measured_seconds + warmup_seconds + 8.0,
        )
        epoch_command_latency = BoundedLatency()
        epoch_status_latency = BoundedLatency()

        reset_frame, latency = link.exchange(
            RESET_STATS_REQUEST, hard_deadline=self.hard_deadline
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        response_success(reset_frame, RESET_STATS_RESPONSE)
        reset_generation = _u32(reset_frame.payload, 4)
        require(reset_generation != 0, "control", "RESET returned generation zero")

        requested = CONFIGURATION.pack(
            STREAM_BOTH,
            source,
            self.settings.checksum_algorithm,
            0,
            DATA_FRAME_BYTES,
        )
        configured_frame, latency = link.exchange(
            CONFIGURE_REQUEST,
            requested,
            hard_deadline=self.hard_deadline,
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        applied = (
            STREAM_BOTH,
            source,
            self.settings.checksum_algorithm,
            DATA_FRAME_BYTES,
        )
        require(
            decode_configuration(configured_frame, CONFIGURE_RESPONSE) == applied,
            "control",
            "CONFIGURE echo differs from requested profile",
        )

        configured_status_frame, latency = link.exchange(
            GET_STATUS_REQUEST, hard_deadline=self.hard_deadline
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        configured_status = decode_status(configured_status_frame)
        validate_status_identity(
            configured_status,
            configured_status_frame,
            expected_state=STATE_CONFIGURED,
            expected_stream_mask=STREAM_BOTH,
            source=source,
            checksum_algorithm=self.settings.checksum_algorithm,
            expected_generation=reset_generation,
            run_id=configured_status_frame.run_id,
        )
        validate_status_invariants(configured_status, source=source)

        configured_info_frame, latency = link.exchange(
            INFO_REQUEST, hard_deadline=self.hard_deadline
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        configured_info = decode_info(configured_info_frame)
        validate_info_identity(
            configured_info,
            self.settings,
            expected_state=STATE_CONFIGURED,
            expected_source=source,
        )
        require(
            self.identity is not None
            and stable_identity(configured_info) == stable_identity(self.identity),
            "identity",
            "configured INFO identity changed",
        )

        deferred: list[Frame] = []
        deferred_limit = math.ceil(link.read_bytes / DATA_FRAME_BYTES) + 1

        def collect_start_data(frame: Frame) -> None:
            require(
                len(deferred) < deferred_limit,
                "queue_bound",
                "START deferred-data bound exhausted",
            )
            deferred.append(frame)

        self.memory.begin_streaming()
        accepted_before_start = link.accepted_requests
        start_frame, latency = link.exchange(
            START_REQUEST,
            on_data=collect_start_data,
            hard_deadline=self.hard_deadline,
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        response_success(start_frame, START_RESPONSE)
        require(
            decode_configuration(start_frame, START_RESPONSE) == applied,
            "control",
            "START echo differs from configured profile",
        )
        if previous_run_id is not None:
            expected_run_id = (previous_run_id + 1) & 0xFFFFFFFF or 1
            require(
                start_frame.run_id == expected_run_id,
                "stale_run",
                f"run ID {start_frame.run_id} != planned {expected_run_id}",
            )
        validator = StreamValidator(
            start_frame.run_id,
            source,
            self.settings.checksum_algorithm,
            self.clock,
        )
        self.active_epoch_index = index
        self.active_validator = validator
        self.active_status = None
        for frame in deferred:
            validator.accept(frame)
        expected_generation = (configured_status.stats_generation + 1) & 0xFFFFFFFF or 1
        parser_errors_at_start = link.parser.errors
        discarded_at_start = link.discarded_data_frames
        status_rollup = StatusRollup()

        active_started = self.clock.monotonic()
        warmup_deadline = active_started + warmup_seconds
        timed_started_at: float | None = None
        timed_baseline = (0, 0, 0, 0, 0, 0, 0, 0)
        next_status_at = active_started
        next_info_at = active_started + self.settings.info_interval_seconds
        previous_status: StatusSnapshot | None = None
        projected_statuses = max(
            1,
            math.ceil(
                (measured_seconds + warmup_seconds)
                / self.settings.status_interval_seconds
            ),
        )
        checkpoint_interval = max(1, projected_statuses // 10)
        while True:
            now = self.clock.monotonic()
            self._check_budget("streaming epoch", reserve=5.0)
            if timed_started_at is None and now >= warmup_deadline:
                timed_started_at = now
                timed_baseline = (
                    validator.adc.frames,
                    validator.gpio.frames,
                    validator.adc.items,
                    validator.gpio.items,
                    validator.adc.payload_bytes,
                    validator.gpio.payload_bytes,
                    validator.adc.framed_bytes,
                    validator.gpio.framed_bytes,
                )
                emit_event(
                    "warmup_complete",
                    epoch=index,
                    source=source,
                    elapsed_seconds=now - active_started,
                )
            if (
                timed_started_at is not None
                and now >= timed_started_at + measured_seconds
            ):
                break
            if now >= next_status_at:
                adc_floor = validator.adc.frames
                gpio_floor = validator.gpio.frames
                status_frame, latency = link.exchange(
                    GET_STATUS_REQUEST,
                    on_data=validator.accept,
                    hard_deadline=self.hard_deadline,
                )
                epoch_status_latency.add(latency)
                epoch_command_latency.add(latency)
                self.status_latency.add(latency)
                self.command_latency.add(latency)
                status = decode_status(status_frame)
                self.active_status = status
                expected_commands = link.accepted_requests - accepted_before_start - 1
                validate_running_status(
                    status,
                    status_frame,
                    validator,
                    expected_generation=expected_generation,
                    expected_commands=expected_commands,
                    host_adc_floor=adc_floor,
                    host_gpio_floor=gpio_floor,
                    previous=previous_status,
                )
                previous_status = status
                status_rollup.observe(status)
                self.memory.sample_streaming(
                    checkpoint=status_rollup.count % checkpoint_interval == 0
                )
                next_status_at += self.settings.status_interval_seconds
                while next_status_at <= self.clock.monotonic():
                    next_status_at += self.settings.status_interval_seconds
                continue
            if now >= next_info_at:
                info_frame, latency = link.exchange(
                    INFO_REQUEST,
                    on_data=validator.accept,
                    hard_deadline=self.hard_deadline,
                )
                epoch_command_latency.add(latency)
                self.command_latency.add(latency)
                live_info = decode_info(info_frame)
                validate_info_identity(
                    live_info,
                    self.settings,
                    expected_state=STATE_RUNNING,
                    expected_source=source,
                )
                next_info_at += self.settings.info_interval_seconds
                continue
            link.pump_once(validator.accept)

        require(timed_started_at is not None, "timeout", "measured phase never began")
        measured_elapsed = self.clock.monotonic() - timed_started_at
        baseline_adc_frames, baseline_gpio_frames = timed_baseline[:2]
        baseline_adc_items, baseline_gpio_items = timed_baseline[2:4]
        timed_adc_frames = validator.adc.frames - baseline_adc_frames
        timed_gpio_frames = validator.gpio.frames - baseline_gpio_frames
        timed_adc_items = validator.adc.items - baseline_adc_items
        timed_gpio_items = validator.gpio.items - baseline_gpio_items

        stop_frame, latency = link.exchange(
            STOP_REQUEST,
            on_data=validator.accept,
            hard_deadline=self.hard_deadline,
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        response_success(stop_frame, STOP_RESPONSE)
        require(stop_frame.run_id == validator.run_id, "stale_run", "STOP run ID")
        require(
            stop_frame.payload[4] == STATE_IDLE, "control", "STOP did not reach IDLE"
        )
        link.drain_until_quiet(validator.accept, hard_deadline=self.hard_deadline)
        final_frame, latency = link.exchange(
            GET_STATUS_REQUEST,
            on_data=validator.accept,
            hard_deadline=self.hard_deadline,
        )
        epoch_command_latency.add(latency)
        self.command_latency.add(latency)
        final_status = decode_status(final_frame)
        expected_commands = link.accepted_requests - accepted_before_start - 1
        reconcile_final_status(
            final_status,
            final_frame,
            validator,
            expected_generation=expected_generation,
            expected_commands=expected_commands,
        )
        status_rollup.observe(final_status)
        self.memory.end_streaming()

        require(
            link.parser.errors == parser_errors_at_start,
            "parser",
            "parser error counter changed during epoch",
        )
        require(
            link.discarded_data_frames == discarded_at_start,
            "source_gap",
            "host discarded a data frame during epoch",
        )
        require(link.stale_responses == 0, "stale_run", "stale control response")
        require(not link.parser.buffer, "parser", "parser is nonempty after STOP")
        require(
            timed_adc_items > 0 and timed_gpio_items > 0,
            "rate",
            "measured epoch contains no complete data",
        )
        rates = {
            "adc_pair_rate_hz": timed_adc_items / measured_elapsed,
            "gpio_sample_rate_hz": timed_gpio_items / measured_elapsed,
            "payload_bytes_per_second": (
                timed_adc_items * ADC_BYTES_PER_PAIR + timed_gpio_items
            )
            / measured_elapsed,
        }
        for name, target in (
            ("adc_pair_rate_hz", ADC_PAIR_RATE_HZ),
            ("gpio_sample_rate_hz", GPIO_SAMPLE_RATE_HZ),
            (
                "payload_bytes_per_second",
                TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND,
            ),
        ):
            relative_error = abs(rates[name] - target) / target
            require(
                relative_error <= RATE_TOLERANCE_FRACTION,
                "rate",
                f"{name}={rates[name]:.6f} outside {target} +/-1%",
            )
        status_summary = epoch_status_latency.summary()
        status_p99 = status_summary["p99_seconds"]
        status_maximum = status_summary["maximum_seconds"]
        require(
            isinstance(status_p99, float) and status_p99 <= STATUS_P99_LIMIT_SECONDS,
            "latency_violation",
            f"STATUS p99 {status_p99!r} exceeds {STATUS_P99_LIMIT_SECONDS}",
        )
        require(
            isinstance(status_maximum, float)
            and status_maximum <= STATUS_MAXIMUM_LIMIT_SECONDS,
            "latency_violation",
            f"STATUS maximum {status_maximum!r} exceeds {STATUS_MAXIMUM_LIMIT_SECONDS}",
        )
        report = EpochReport(
            index=index,
            source=source,
            run_id=validator.run_id,
            stats_generation=expected_generation,
            started_offset_seconds=epoch_started_offset,
            completed_offset_seconds=(self.clock.monotonic() - self.script_started_at),
            warmup_seconds=warmup_seconds,
            measured_elapsed_seconds=measured_elapsed,
            timed_adc_frames=timed_adc_frames,
            timed_gpio_frames=timed_gpio_frames,
            timed_adc_items=timed_adc_items,
            timed_gpio_items=timed_gpio_items,
            total_adc_frames=validator.adc.frames,
            total_gpio_frames=validator.gpio.frames,
            total_adc_items=validator.adc.items,
            total_gpio_items=validator.gpio.items,
            status_latency=status_summary,
            command_latency=epoch_command_latency.summary(),
            status_rollup=status_rollup.summary(),
            final_counters={
                name: final_status.values[name] for name in FINAL_REPORT_FIELDS
            },
            diagnostics=validator.diagnostics.summary(),
            maximum_receive_gap_seconds=validator.maximum_receive_gap_seconds,
            parser={
                "bytes_received": link.parser.bytes_received,
                "frames_decoded": link.parser.frames_decoded,
                "bytes_discarded": link.parser.bytes_discarded,
                "errors": link.parser.errors,
                "high_water_bytes": link.parser.high_water_bytes,
                "maximum_read_bytes": link.maximum_read_bytes,
                "buffered_bytes": len(link.parser.buffer),
            },
        )
        emit_event(
            "epoch_complete",
            epoch=index,
            source="synthetic" if source == SOURCE_SYNTHETIC else "hardware",
            run_id=validator.run_id,
            measured_elapsed_seconds=measured_elapsed,
            payload_bytes=report.timed_payload_bytes,
        )
        return report

    def execute_mode(self) -> dict[str, object]:
        self.open_and_synchronize()
        measured_started_at = self.clock.monotonic()
        previous_run_id: int | None = None
        if self.settings.mode in {"synthetic", "physical-combined"}:
            source = (
                SOURCE_SYNTHETIC
                if self.settings.mode == "synthetic"
                else SOURCE_HARDWARE
            )
            report = self.run_epoch(
                index=1,
                source=source,
                measured_seconds=self.settings.measured_duration_seconds,
                warmup_seconds=self.settings.warmup_seconds,
                previous_run_id=None,
            )
            self.epochs.append(report)
            measured_elapsed = report.measured_elapsed_seconds
        else:
            campaign_deadline = (
                measured_started_at + self.settings.measured_duration_seconds
            )
            epoch_index = 0
            while self.clock.monotonic() < campaign_deadline:
                self._check_budget("control campaign", reserve=12.0)
                epoch_index += 1
                remaining = campaign_deadline - self.clock.monotonic()
                measured_seconds = min(
                    self.settings.control_epoch_seconds,
                    max(5.0, remaining - 1.0),
                )
                source = SOURCE_HARDWARE if epoch_index % 2 else SOURCE_SYNTHETIC
                report = self.run_epoch(
                    index=epoch_index,
                    source=source,
                    measured_seconds=measured_seconds,
                    warmup_seconds=min(0.25, self.settings.warmup_seconds),
                    previous_run_id=previous_run_id,
                )
                self.epochs.append(report)
                previous_run_id = report.run_id
                if (
                    epoch_index % self.settings.control_reopen_every_epochs == 0
                    and self.clock.monotonic() + 8.0 < campaign_deadline
                ):
                    self.reopen()
            measured_elapsed = self.clock.monotonic() - measured_started_at
            require(
                measured_elapsed >= self.settings.measured_duration_seconds,
                "timeout",
                "control campaign ended before its 600-second measured duration",
            )

        self.memory.sample(checkpoint=True)
        self.cpu.sample()
        memory_summary = self.memory.summary()
        require(
            self.memory.traced_growth_bytes <= MAX_TRACED_GROWTH_BYTES,
            "memory_growth",
            f"tracemalloc growth {self.memory.traced_growth_bytes} exceeds "
            f"{MAX_TRACED_GROWTH_BYTES}",
        )
        rss_growth = self.memory.rss_growth_bytes
        require(
            rss_growth is None or rss_growth <= MAX_RSS_GROWTH_BYTES,
            "memory_growth",
            f"RSS growth {rss_growth} exceeds {MAX_RSS_GROWTH_BYTES}",
        )
        command_summary = self.command_latency.summary()
        command_maximum = command_summary["maximum_seconds"]
        require(
            isinstance(command_maximum, float)
            and command_maximum <= COMMAND_DEADLINE_SECONDS,
            "latency_violation",
            f"command maximum {command_maximum!r} exceeds {COMMAND_DEADLINE_SECONDS}",
        )
        return self._success_result(measured_elapsed, memory_summary)

    def _success_result(
        self,
        measured_elapsed: float,
        memory_summary: dict[str, object],
    ) -> dict[str, object]:
        timed_seconds = sum(epoch.measured_elapsed_seconds for epoch in self.epochs)
        payload_bytes = sum(epoch.timed_payload_bytes for epoch in self.epochs)
        framed_bytes = sum(epoch.timed_framed_bytes for epoch in self.epochs)
        adc_pairs = sum(epoch.timed_adc_items for epoch in self.epochs)
        gpio_samples = sum(epoch.timed_gpio_items for epoch in self.epochs)
        maximum_queues = {name: 0 for name in QUEUE_FIELDS}
        for epoch in self.epochs:
            status_rollup = epoch.status_rollup
            raw_queues = status_rollup.get("maximum_queues")
            if isinstance(raw_queues, Mapping):
                for name, current in maximum_queues.items():
                    value = raw_queues.get(name)
                    if isinstance(value, int):
                        maximum_queues[name] = max(current, value)
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "result": "PASS",
            "mode": self.settings.mode,
            "failure": None,
            "expected": self._expected_identity(),
            "observed_identity": self._observed_identity(),
            "timing": {
                "measured_duration_seconds": self.settings.measured_duration_seconds,
                "measured_elapsed_seconds": measured_elapsed,
                "streaming_elapsed_seconds": timed_seconds,
                "script_elapsed_seconds": (
                    self.clock.monotonic() - self.script_started_at
                ),
                "hard_deadline_seconds": self.settings.hard_deadline_seconds,
                "service_container_limit_seconds": (
                    self.settings.service_container_limit_seconds
                ),
                "service_safety_margin_seconds": (
                    self.settings.service_container_limit_seconds
                    - self.settings.hard_deadline_seconds
                ),
            },
            "metrics": {
                "epoch_count": len(self.epochs),
                "cdc_reopen_count": self.reopen_count,
                "payload_bytes": payload_bytes,
                "framed_bytes": framed_bytes,
                "adc_pairs": adc_pairs,
                "gpio_samples": gpio_samples,
                "payload_bytes_per_streaming_second": payload_bytes / timed_seconds,
                "framed_bytes_per_streaming_second": framed_bytes / timed_seconds,
                "adc_pair_rate_hz": adc_pairs / timed_seconds,
                "gpio_sample_rate_hz": gpio_samples / timed_seconds,
                "latency": {
                    "status": self.status_latency.summary(),
                    "all_commands": self.command_latency.summary(),
                },
                "maximum_queues": maximum_queues,
                "memory": memory_summary,
                "cpu": self.cpu.summary(),
            },
            "epochs": [epoch.as_dict() for epoch in self.epochs],
            "cleanup": {"attempted": False, "normal_close": True},
            "program": {
                "sha256": _program_sha256(),
                "validator_sha256": self.settings.validator_sha256,
                "candidate_sha256": self.settings.candidate_sha256,
                "python": sys.version.split()[0],
                "serial_read_bytes": self.settings.serial_read_bytes,
            },
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _expected_identity(self) -> dict[str, object]:
        return {
            "protocol_version": self.settings.protocol_version,
            "checksum_algorithm": self.settings.checksum_algorithm,
            "checksum_name": self.settings.checksum_name,
            "firmware_version": list(self.settings.firmware_version),
            "build_id": self.settings.build_id,
            "source_id": self.settings.source_id,
            "artifact_name": self.settings.artifact_name,
            "artifact_sha256": self.settings.artifact_sha256,
            "fqbn": self.settings.fqbn,
            "hardware_serial": self.settings.hardware_serial,
            "board_id": self.settings.board_id,
            "mcu_id": self.settings.mcu_id,
        }

    def _observed_identity(self) -> dict[str, object] | None:
        if self.identity is None:
            return None
        names = (
            "protocol_version",
            "hardware_serial",
            "firmware_version",
            "board_id",
            "mcu_id",
            "build_id",
            "supported_stream_mask",
            "supported_source_mask",
            "supported_checksum_mask",
            "supported_configuration_mask",
            "capability_bits",
        )
        result = {name: self.identity[name] for name in names}
        if isinstance(result["firmware_version"], tuple):
            result["firmware_version"] = list(result["firmware_version"])
        return result

    def attempt_cleanup(self) -> None:
        self.cleanup = {"attempted": True}
        link = self.link
        if link is None or self.clock.monotonic() >= self.hard_deadline:
            self.cleanup["stop"] = "unavailable"
            return
        try:
            frame, latency = link.exchange(
                GET_STATUS_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.01, self.hard_deadline - self.clock.monotonic()),
                ),
                on_data=lambda _frame: None,
                hard_deadline=self.hard_deadline,
            )
            status = decode_status(frame)
            self.cleanup["pre_stop_status"] = {
                "state": status.device_state,
                "run_id": frame.run_id,
                "adc_frames": status.adc_frames_emitted,
                "gpio_frames": status.gpio_frames_emitted,
                "adc_drop": status.adc_items_dropped,
                "gpio_drop": status.gpio_items_dropped,
                "nonzero_errors": _nonzero_errors(
                    status,
                    allow_physical_stop_tail=False,
                ),
                "queues": {name: status.values[name] for name in QUEUE_FIELDS},
                "latency_seconds": latency,
            }
        except Exception as error:  # noqa: BLE001 - best-effort remote evidence
            self.cleanup["pre_stop_status"] = f"{type(error).__name__}: {error}"
        if self.clock.monotonic() >= self.hard_deadline:
            self.cleanup["stop"] = "unavailable"
            return
        try:
            frame, latency = link.exchange(
                STOP_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.01, self.hard_deadline - self.clock.monotonic()),
                ),
                on_data=lambda _frame: None,
                hard_deadline=self.hard_deadline,
            )
            self.cleanup["stop"] = {
                "response_flags": frame.flags,
                "state": frame.payload[4] if len(frame.payload) > 4 else None,
                "latency_seconds": latency,
            }
        except Exception as error:  # noqa: BLE001 - best-effort remote evidence
            self.cleanup["stop"] = f"{type(error).__name__}: {error}"
        if self.clock.monotonic() >= self.hard_deadline:
            return
        try:
            frame, latency = link.exchange(
                GET_STATUS_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.01, self.hard_deadline - self.clock.monotonic()),
                ),
                on_data=lambda _frame: None,
                hard_deadline=self.hard_deadline,
            )
            status = decode_status(frame)
            self.cleanup["final_status"] = {
                "state": status.device_state,
                "run_id": frame.run_id,
                "adc_frames": status.adc_frames_emitted,
                "gpio_frames": status.gpio_frames_emitted,
                "adc_drop": status.adc_items_dropped,
                "gpio_drop": status.gpio_items_dropped,
                "latency_seconds": latency,
            }
        except Exception as error:  # noqa: BLE001 - best-effort remote evidence
            self.cleanup["final_status"] = f"{type(error).__name__}: {error}"

    def failure_result(self, error: BaseException) -> dict[str, object]:
        self.memory.end_streaming()
        self.cpu.sample()
        category = error.category if isinstance(error, SoakFailure) else "program"
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "result": "FAIL",
            "mode": self.settings.mode,
            "failure": {
                "category": category,
                "type": type(error).__name__,
                "message": str(error),
            },
            "expected": self._expected_identity(),
            "observed_identity": self._observed_identity(),
            "timing": {
                "measured_duration_seconds": self.settings.measured_duration_seconds,
                "script_elapsed_seconds": (
                    self.clock.monotonic() - self.script_started_at
                ),
                "hard_deadline_seconds": self.settings.hard_deadline_seconds,
                "service_container_limit_seconds": (
                    self.settings.service_container_limit_seconds
                ),
            },
            "metrics": {
                "epoch_count": len(self.epochs),
                "cdc_reopen_count": self.reopen_count,
                "latency": {
                    "status": self.status_latency.summary(),
                    "all_commands": self.command_latency.summary(),
                },
                "memory": self.memory.summary(),
                "cpu": self.cpu.summary(),
                "active_epoch": self._active_epoch_evidence(),
            },
            "epochs": [epoch.as_dict() for epoch in self.epochs],
            "cleanup": self.cleanup,
            "program": {
                "sha256": _program_sha256(),
                "validator_sha256": self.settings.validator_sha256,
                "candidate_sha256": self.settings.candidate_sha256,
                "python": sys.version.split()[0],
                "serial_read_bytes": self.settings.serial_read_bytes,
            },
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _active_epoch_evidence(self) -> dict[str, object] | None:
        validator = self.active_validator
        if validator is None:
            return None
        link = self.link
        status = self.active_status
        return {
            "index": self.active_epoch_index,
            "source": (
                "synthetic" if validator.source == SOURCE_SYNTHETIC else "hardware"
            ),
            "run_id": validator.run_id,
            "adc_frames": validator.adc.frames,
            "gpio_frames": validator.gpio.frames,
            "maximum_receive_gap_seconds": validator.maximum_receive_gap_seconds,
            "parser": (
                {
                    "bytes_received": link.parser.bytes_received,
                    "frames_decoded": link.parser.frames_decoded,
                    "bytes_discarded": link.parser.bytes_discarded,
                    "errors": link.parser.errors,
                    "high_water_bytes": link.parser.high_water_bytes,
                    "maximum_read_bytes": link.maximum_read_bytes,
                    "buffered_bytes": len(link.parser.buffer),
                }
                if link is not None
                else None
            ),
            "last_status_nonzero_errors": (
                _nonzero_errors(status, allow_physical_stop_tail=False)
                if status is not None
                else None
            ),
            "last_status_queues": (
                {name: status.values[name] for name in QUEUE_FIELDS}
                if status is not None
                else None
            ),
            "diagnostic_samples": validator.diagnostics.summary(),
        }

    def close(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            finally:
                self.port = None
                self.link = None


def _program_sha256() -> str | None:
    try:
        with open(__file__, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def _default_port_factory(port_name: str) -> PortFactory:
    def open_port() -> SerialPort:
        port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )
        try:
            port.dtr = True
        except (AttributeError, OSError):
            pass
        return port

    return open_port


def run_generated(
    settings: RuntimeSettings,
    port_factory: PortFactory,
    *,
    clock: Clock = time,
) -> tuple[int, dict[str, object]]:
    runner = SoakRunner(settings, port_factory, clock)
    try:
        result = runner.execute_mode()
        return 0, result
    except BaseException as error:  # noqa: BLE001 - final JSON must survive failures
        runner.attempt_cleanup()
        return 1, runner.failure_result(error)
    finally:
        runner.close()


def main() -> int:
    try:
        settings = load_settings()
    except BaseException as error:  # noqa: BLE001 - configuration result is structured
        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "result": "FAIL",
            "mode": GENERATED_CONFIG.get("mode"),
            "failure": {
                "category": (
                    error.category
                    if isinstance(error, SoakFailure)
                    else "configuration"
                ),
                "type": type(error).__name__,
                "message": str(error),
            },
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }
        print(RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "result": "FAIL",
            "mode": settings.mode,
            "failure": {
                "category": "configuration",
                "type": "MissingEnvironment",
                "message": "SERIAL_PORT is required",
            },
            "expected": {
                "build_id": settings.build_id,
                "artifact_sha256": settings.artifact_sha256,
            },
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }
        print(RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2
    emit_event(
        "program_start",
        mode=settings.mode,
        measured_duration_seconds=settings.measured_duration_seconds,
        hard_deadline_seconds=settings.hard_deadline_seconds,
        service_container_limit_seconds=settings.service_container_limit_seconds,
        serial_read_bytes=settings.serial_read_bytes,
        protocol_version=settings.protocol_version,
        firmware_version=list(settings.firmware_version),
        build_id=settings.build_id,
        artifact_sha256=settings.artifact_sha256,
        port=port_name,
    )
    exit_code, result = run_generated(
        settings,
        _default_port_factory(port_name),
    )
    print(
        RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
