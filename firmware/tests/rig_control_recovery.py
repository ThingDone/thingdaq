#!/usr/bin/env python3
"""Independent Phase 09 malformed-control and CDC-reopen rig acceptance.

The remote rig uploads this file by itself to a network-disabled Python
container.  It embeds the protocol-v1 subset it grades and uses only the
Python standard library plus pyserial; it does not import the project package
or generated constants.

The program brackets deliberately malformed commands with valid INFO/STATUS
probes, checks exact typed rejections, executes at least 100 complete physical
CONFIGURE/START/STATUS/STOP cycles, then closes and reopens CDC while a run is
live.  Every operation has a finite deadline and the terminal state must be
IDLE.  Expected parser rejections and close-induced loss are reported apart
from unexpected inbound corruption and acquisition/hardware failures.
"""

from __future__ import annotations

import json
import math
import os
import re
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
COMMAND_DEADLINE_SECONDS = 1.0
CYCLE_DRAIN_DEADLINE_SECONDS = 1.0
CYCLE_DRAIN_QUIET_SECONDS = 0.01
DEFAULT_CYCLE_COUNT = 100
MAX_CYCLE_COUNT = 1000
DEFAULT_REOPEN_PAUSE_SECONDS = 0.25
MAX_REOPEN_PAUSE_SECONDS = 5.0
DEFAULT_REOPEN_DEADLINE_SECONDS = 4.0
MAX_REOPEN_DEADLINE_SECONDS = 30.0
REOPEN_BASELINE_FRAMES_PER_SOURCE = 2

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 1
HEADER_SIZE = 44
TRAILER_SIZE = 4
DATA_FRAME_BYTES = 4096
DATA_PAYLOAD_BYTES = 4048
MAX_FRAME_BYTES = DATA_FRAME_BYTES
MAX_CONTROL_FRAME_BYTES = 1364
MAX_COMMAND_FRAME_BYTES = 56

CHECKSUM_ADLER32 = 1
FLAG_SYNTHETIC = 0x0001
FLAG_GAP_BEFORE = 0x0002
FLAG_EPOCH_START = 0x0004
FLAG_OVERRUN_BEFORE = 0x0008
FLAG_RESPONSE_ERROR = 0x8000
DATA_FLAG_MASK = (
    FLAG_SYNTHETIC | FLAG_GAP_BEFORE | FLAG_EPOCH_START | FLAG_OVERRUN_BEFORE
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

STATE_IDLE = 1
STATE_CONFIGURED = 2
STATE_RUNNING = 3
STREAM_ADC = 1
STREAM_GPIO = 2
STREAM_BOTH = STREAM_ADC | STREAM_GPIO
SOURCE_HARDWARE = 0
PROFILE_HARDWARE_COMBINED = 4

ERROR_UNSUPPORTED_VERSION = 1
ERROR_UNKNOWN_FRAME_KIND = 2
ERROR_INVALID_LENGTH = 4
ERROR_INVALID_PAYLOAD = 5
ERROR_INVALID_STATE = 7
ERROR_INVALID_REQUEST_ID = 9
ERROR_CHECKSUM_MISMATCH = 12

ADC_PAIRS_PER_FRAME = 1012
ADC_BYTES_PER_PAIR = 4
GPIO_SAMPLES_PER_FRAME = 4048
UINT32_MAX = 0xFFFFFFFF

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
TRAILER = struct.Struct("<I")
CONFIGURATION = struct.Struct("<BBBBI")
RESPONSE_PREFIX = struct.Struct("<BBH")

DATA_KINDS = frozenset({ADC_DATA, GPIO_DATA})
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
    INFO_RESPONSE: 408,
    CONFIGURE_RESPONSE: 12,
    START_RESPONSE: 12,
    GET_STATUS_RESPONSE: 1316,
    STOP_RESPONSE: 8,
    RESET_STATS_RESPONSE: 8,
    ERROR_RESPONSE: 8,
}


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
    kind: int
    flags: int
    checksum_algorithm: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    payload: bytes


def encode_request(kind: int, request_id: int, payload: bytes = b"") -> bytes:
    """Independently encode one bounded protocol-v1 request."""

    if kind not in REQUEST_PAYLOAD_SIZE:
        raise ValueError(f"unknown request kind 0x{kind:02x}")
    if len(payload) != REQUEST_PAYLOAD_SIZE[kind]:
        raise ValueError(
            f"request 0x{kind:02x} needs {REQUEST_PAYLOAD_SIZE[kind]} payload bytes"
        )
    if not 1 <= request_id <= UINT32_MAX:
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
    return body + TRAILER.pack(zlib.adler32(body) & UINT32_MAX)


def refresh_checksum(wire: bytearray) -> None:
    if len(wire) < HEADER_SIZE + TRAILER_SIZE:
        raise ValueError("wire frame is too short to checksum")
    struct.pack_into("<I", wire, len(wire) - TRAILER_SIZE, zlib.adler32(wire[:-4]))


class FrameParser:
    """Bounded parser that records unexpected inbound corruption."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.scan_start = 0
        self.frames_decoded = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.bytes_discarded = 0
        self.high_water_bytes = 0

    @property
    def errors(self) -> int:
        return self.header_errors + self.checksum_errors + self.payload_errors

    @property
    def buffered_bytes(self) -> int:
        return len(self.buffer) - self.scan_start

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(bytes(data))
        self.high_water_bytes = max(self.high_water_bytes, self.buffered_bytes)
        frames: list[Frame] = []
        while True:
            magic_at = self.buffer.find(MAGIC_BYTES, self.scan_start)
            if magic_at < 0:
                retained = self._partial_magic_suffix()
                self._discard(self.buffered_bytes - retained)
                break
            self._discard(magic_at - self.scan_start)
            if self.buffered_bytes < HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.buffer, self.scan_start)
            try:
                total_length = self._validate_header(fields)
            except ProtocolFailure:
                self.header_errors += 1
                self._discard(1)
                continue
            if self.buffered_bytes < total_length:
                break
            payload_length = fields[8]
            payload_start = self.scan_start + HEADER_SIZE
            payload_end = payload_start + payload_length
            expected = (
                zlib.adler32(self.buffer[self.scan_start : payload_end]) & UINT32_MAX
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
                payload=bytes(self.buffer[payload_start:payload_end]),
            )
            try:
                self._validate_payload(frame)
            except ProtocolFailure:
                self.payload_errors += 1
                self._discard(1)
                continue
            self.scan_start += total_length
            self.frames_decoded += 1
            frames.append(frame)
            if self.scan_start >= MAX_FRAME_BYTES:
                self._compact()
        if self.buffered_bytes > MAX_FRAME_BYTES + len(MAGIC_BYTES) - 1:
            raise ProtocolFailure("inbound parser retained more than one frame")
        self._compact()
        return frames

    def _validate_header(self, fields: tuple[int, ...]) -> int:
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
            first_ticks,
            item_count,
        ) = fields
        if magic != MAGIC or version != PROTOCOL_VERSION:
            raise ProtocolFailure("invalid inbound magic or version")
        if kind not in DATA_KINDS and kind not in SUCCESS_PAYLOAD_SIZE:
            raise ProtocolFailure(f"unknown inbound kind 0x{kind:02x}")
        if header_length != HEADER_SIZE or checksum != CHECKSUM_ADLER32 or reserved:
            raise ProtocolFailure("invalid fixed inbound header fields")
        if total_length != HEADER_SIZE + payload_length + TRAILER_SIZE:
            raise ProtocolFailure("inconsistent inbound frame lengths")
        if not HEADER_SIZE + TRAILER_SIZE <= total_length <= MAX_FRAME_BYTES:
            raise ProtocolFailure("inbound frame exceeds fixed bounds")
        if kind in DATA_KINDS:
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            if (
                total_length != DATA_FRAME_BYTES
                or payload_length != DATA_PAYLOAD_BYTES
                or flags & ~DATA_FLAG_MASK
                or flags & FLAG_RESPONSE_ERROR
                or not run_id
                or request_id
                or item_count != expected_items
            ):
                raise ProtocolFailure("invalid inbound data header")
        else:
            if flags not in {0, FLAG_RESPONSE_ERROR}:
                raise ProtocolFailure("invalid response flags")
            if not request_id or sequence or first_ticks or item_count:
                raise ProtocolFailure("invalid response-only header fields")
            if kind == ERROR_RESPONSE:
                expected_payload = SUCCESS_PAYLOAD_SIZE[kind]
                if flags != FLAG_RESPONSE_ERROR:
                    raise ProtocolFailure("generic error lacks its flag")
            else:
                expected_payload = (
                    4 if flags == FLAG_RESPONSE_ERROR else SUCCESS_PAYLOAD_SIZE[kind]
                )
            if (
                payload_length != expected_payload
                or total_length > MAX_CONTROL_FRAME_BYTES
            ):
                raise ProtocolFailure("response payload size does not match kind")
        return total_length

    @staticmethod
    def _validate_payload(frame: Frame) -> None:
        if frame.kind in DATA_KINDS:
            if frame.kind == ADC_DATA and max(frame.payload[1::2]) > 0x0F:
                raise ProtocolFailure("ADC data exceeds the 12-bit container")
            return
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == FLAG_RESPONSE_ERROR
        if reserved or is_error != (status == 1) or (error == 0) == is_error:
            raise ProtocolFailure("response prefix disagrees with flags")
        if error > ERROR_CHECKSUM_MISMATCH:
            raise ProtocolFailure("response carries an unknown error code")

    def _partial_magic_suffix(self) -> int:
        maximum = min(self.buffered_bytes, len(MAGIC_BYTES) - 1)
        for length in range(maximum, 0, -1):
            if self.buffer[-length:] == MAGIC_BYTES[:length]:
                return length
        return 0

    def _discard(self, count: int) -> None:
        if count > 0:
            self.scan_start += count
            self.bytes_discarded += count
            if self.scan_start >= MAX_FRAME_BYTES:
                self._compact()

    def _compact(self) -> None:
        if self.scan_start:
            del self.buffer[: self.scan_start]
            self.scan_start = 0


class SerialLink:
    """Finite-deadline request link with concurrent data-frame servicing."""

    def __init__(self, port: SerialPort) -> None:
        self.port = port
        self.parser = FrameParser()
        self.next_request_id = 1
        self.stale_responses = 0
        self.discarded_data_frames = 0

    def drain_startup(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        frames = 0
        while time.monotonic() < deadline:
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
            if chunk:
                frames += len(self.parser.feed(chunk))
        emit_event(
            "startup_drain",
            discarded_bytes=self.parser.bytes_discarded,
            discarded_frames=frames,
        )

    def allocate_request_id(self) -> int:
        result = self.next_request_id
        self.next_request_id = (self.next_request_id + 1) & UINT32_MAX
        if self.next_request_id == 0:
            self.next_request_id = 1
        return result

    def exchange(
        self,
        request_kind: int,
        payload: bytes = b"",
        *,
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[Frame, float]:
        request_id = self.allocate_request_id()
        return self.exchange_wire(
            encode_request(request_kind, request_id, payload),
            request_id,
            REQUEST_RESPONSE_KIND[request_kind],
            timeout=timeout,
            on_data=on_data,
        )

    def exchange_wire(
        self,
        wire: bytes,
        request_id: int,
        expected_kind: int,
        *,
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[Frame, float]:
        started = time.monotonic()
        deadline = started + timeout
        self._write_all(wire, deadline)
        responses = self._collect_responses(
            {request_id: expected_kind}, deadline, on_data=on_data
        )
        return responses[request_id], time.monotonic() - started

    def exchange_batch(
        self,
        wire: bytes,
        expected: dict[int, int],
        *,
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[dict[int, Frame], float]:
        started = time.monotonic()
        deadline = started + timeout
        self._write_all(wire, deadline)
        return (
            self._collect_responses(expected, deadline, on_data=on_data),
            time.monotonic() - started,
        )

    def drain_until_quiet(self, on_data: Callable[[Frame], None] | None) -> None:
        deadline = time.monotonic() + CYCLE_DRAIN_DEADLINE_SECONDS
        quiet_since = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise DeadlineExpired("stopped data did not drain before deadline")
            if now - quiet_since >= CYCLE_DRAIN_QUIET_SECONDS:
                if self.parser.buffered_bytes:
                    raise ProtocolFailure(
                        f"stopped parser retains {self.parser.buffered_bytes} bytes"
                    )
                return
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
            if not chunk:
                continue
            quiet_since = time.monotonic()
            for frame in self.parser.feed(chunk):
                if frame.kind not in DATA_KINDS:
                    raise ProtocolFailure(
                        f"unsolicited stopped response 0x{frame.kind:02x}"
                    )
                if on_data is None:
                    self.discarded_data_frames += 1
                else:
                    on_data(frame)

    def _collect_responses(
        self,
        expected: dict[int, int],
        deadline: float,
        *,
        on_data: Callable[[Frame], None] | None,
    ) -> dict[int, Frame]:
        matched: dict[int, Frame] = {}
        while len(matched) < len(expected):
            if time.monotonic() >= deadline:
                missing = sorted(set(expected) - set(matched))
                raise DeadlineExpired(
                    f"responses {missing} did not arrive before deadline"
                )
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
            if not chunk:
                continue
            for frame in self.parser.feed(chunk):
                if frame.kind in DATA_KINDS:
                    if on_data is None:
                        self.discarded_data_frames += 1
                    else:
                        on_data(frame)
                    continue
                expected_kind = expected.get(frame.request_id)
                if expected_kind is None:
                    self.stale_responses += 1
                    continue
                if frame.kind != expected_kind:
                    raise ProtocolFailure(
                        f"request {frame.request_id} expected 0x{expected_kind:02x}, "
                        f"received 0x{frame.kind:02x}"
                    )
                if frame.request_id in matched:
                    raise ProtocolFailure(
                        f"request {frame.request_id} received duplicate responses"
                    )
                matched[frame.request_id] = frame
        return matched

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


def response_error(frame: Frame) -> int:
    status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    if reserved or status != 1 or frame.flags != FLAG_RESPONSE_ERROR or error == 0:
        raise ProtocolFailure("expected typed error response is malformed")
    return error


def response_success(frame: Frame, expected_kind: int) -> None:
    if frame.kind != expected_kind or frame.flags:
        raise ProtocolFailure(
            f"expected successful kind 0x{expected_kind:02x}, got "
            f"kind=0x{frame.kind:02x} flags=0x{frame.flags:04x}"
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
        "hardware_serial": struct.unpack_from("<I", payload, 54)[0],
        "firmware_version": tuple(payload[58:61]),
        "board_id": struct.unpack_from("<H", payload, 62)[0],
        "mcu_id": struct.unpack_from("<H", payload, 64)[0],
        "build_id": build_id,
        "applied_stream_mask": payload[324],
        "applied_source": payload[325],
        "supported_configuration_mask": struct.unpack_from("<H", payload, 326)[0],
    }


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


def _info_integer(info: dict[str, object], name: str) -> int:
    value = info[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolFailure(f"INFO {name} is not an integer")
    return value


def synchronize(
    link: SerialLink,
    *,
    on_data: Callable[[Frame], None] | None = None,
) -> tuple[dict[str, object], Frame]:
    first: tuple[object, ...] | None = None
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, _latency = link.exchange(
                INFO_REQUEST,
                timeout=SYNC_DEADLINE_SECONDS,
                on_data=on_data,
            )
            info = decode_info(frame)
            identity = stable_identity(info)
            if first is None:
                first = identity
                emit_event("sync_probe", attempt=attempt, role="throwaway")
            elif identity == first:
                emit_event("sync_probe", attempt=attempt, role="confirmed")
                return info, frame
            else:
                raise ProtocolFailure("INFO identity changed during synchronization")
        except DeadlineExpired as error:
            last_error = str(error)
        if attempt < SYNC_ATTEMPTS:
            time.sleep(0.01)
    raise DeadlineExpired(
        f"synchronization failed after {SYNC_ATTEMPTS} attempts: {last_error}"
    )


STATUS_FIELDS: dict[str, tuple[str, int]] = {
    "device_state": ("B", 4),
    "stream_mask": ("B", 5),
    "source": ("B", 6),
    "checksum": ("B", 7),
    "adc_items_dropped": ("Q", 28),
    "gpio_items_dropped": ("Q", 36),
    "parser_errors": ("I", 44),
    "transport_errors": ("I", 48),
    "stats_generation": ("I", 52),
    "gpio_raw_samples_lost": ("Q", 88),
    "gpio_packer_samples_dropped": ("Q", 96),
    "gpio_raw_ring_overruns": ("Q", 104),
    "gpio_hardware_errors": ("I", 136),
    "gpio_raw_invariant_errors": ("I", 140),
    "gpio_packer_source_errors": ("I", 144),
    "gpio_packer_pipeline_errors": ("I", 148),
    "gpio_packer_chronology_errors": ("I", 152),
    "gpio_resource_conflicts": ("I", 156),
    "gpio_start_errors": ("I", 160),
    "gpio_stop_errors": ("I", 164),
    "gpio_stale_dma_completions": ("I", 168),
    "adc_raw_pairs_lost": ("Q", 464),
    "adc_overwritten_conversions": ("Q", 488),
    "adc_raw_ring_overruns": ("Q", 496),
    "adc_etc_error_events": ("I", 516),
    "adc_etc_error_flags": ("I", 520),
    "adc_dma_error_events": ("I", 524),
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
    "adc_frames_dropped": ("Q", 632),
    "gpio_frames_dropped": ("Q", 696),
    "adc_payload_bytes_dropped": ("Q", 736),
    "gpio_payload_bytes_dropped": ("Q", 800),
    "commands_rejected": ("I", 916),
    "bad_checksums": ("I", 920),
    "bad_lengths": ("I", 924),
    "bad_types": ("I", 928),
    "bad_versions": ("I", 932),
    "timeouts": ("I", 936),
    "state_errors": ("I", 944),
    "usb_io_errors": ("I", 960),
    "bad_flags": ("I", 996),
    "bad_payloads": ("I", 1000),
    "bad_request_ids": ("I", 1004),
    "response_queue_rejections": ("I", 1016),
    "response_reservations_abandoned": ("I", 1020),
}


@dataclass(frozen=True)
class StatusSnapshot:
    values: dict[str, int]

    def __getattr__(self, name: str) -> int:
        try:
            return self.values[name]
        except KeyError as error:
            raise AttributeError(name) from error


def decode_status(frame: Frame) -> StatusSnapshot:
    response_success(frame, GET_STATUS_RESPONSE)
    return StatusSnapshot(
        {
            name: int(struct.unpack_from("<" + code, frame.payload, offset)[0])
            for name, (code, offset) in STATUS_FIELDS.items()
        }
    )


def decode_configuration(frame: Frame, expected_kind: int) -> tuple[int, int, int, int]:
    response_success(frame, expected_kind)
    streams, source, checksum, reserved, frame_bytes = CONFIGURATION.unpack_from(
        frame.payload, 4
    )
    if reserved:
        raise ProtocolFailure("applied configuration reserved byte is nonzero")
    return streams, source, checksum, frame_bytes


@dataclass
class DataValidator:
    run_id: int
    adc_frames: int = 0
    gpio_frames: int = 0

    def accept(self, frame: Frame) -> None:
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"data run {frame.run_id}; expected active run {self.run_id}"
            )
        if frame.flags & FLAG_SYNTHETIC:
            raise ProtocolFailure("physical control recovery received synthetic data")
        if frame.checksum_algorithm != CHECKSUM_ADLER32:
            raise ProtocolFailure("data checksum changed during control recovery")
        if frame.kind == ADC_DATA:
            self.adc_frames += 1
        elif frame.kind == GPIO_DATA:
            self.gpio_frames += 1
        else:
            raise ProtocolFailure(f"unexpected data kind 0x{frame.kind:02x}")


class Evidence:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.check_count = 0

    def check(self, label: str, expected: object, actual: object, passed: bool) -> None:
        self.check_count += 1
        outcome = "PASS" if passed else "FAIL"
        print(f"CHECK {label}: expected={expected!r} actual={actual!r} [{outcome}]")
        if not passed:
            self.failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    def equal(self, label: str, expected: object, actual: object) -> None:
        self.check(label, expected, actual, actual == expected)


def emit_event(name: str, **fields: object) -> None:
    print(
        "EVENT "
        + json.dumps(
            {"event": name, **fields},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _grade_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> None:
    source_mask = _info_integer(info, "supported_source_mask")
    profile_mask = _info_integer(info, "supported_configuration_mask")
    evidence.equal("INFO protocol", PROTOCOL_VERSION, info["protocol_version"])
    evidence.equal("INFO stream support", STREAM_BOTH, info["supported_stream_mask"])
    evidence.check(
        "INFO hardware source",
        "hardware bit set",
        source_mask,
        bool(source_mask & 1),
    )
    evidence.check(
        "INFO physical combined profile",
        "profile bit set",
        profile_mask,
        bool(profile_mask & PROFILE_HARDWARE_COMBINED),
    )
    evidence.check(
        "INFO hardware serial",
        "nonzero uint32",
        info["hardware_serial"],
        isinstance(info["hardware_serial"], int) and int(info["hardware_serial"]) > 0,
    )
    evidence.check(
        "INFO build ID",
        "thingdaq-<16 lowercase hex>",
        info["build_id"],
        isinstance(info["build_id"], str)
        and re.fullmatch(r"thingdaq-[0-9a-f]{16}", str(info["build_id"])) is not None,
    )
    if expected_build_id is not None:
        evidence.equal("pinned build ID", expected_build_id, info["build_id"])
    if expected_hardware_serial is not None:
        evidence.equal(
            "pinned hardware serial", expected_hardware_serial, info["hardware_serial"]
        )


def _grade_error(
    evidence: Evidence,
    label: str,
    frame: Frame,
    *,
    expected_error: int,
    rejected_kind: int | None = None,
    rejected_version: int | None = None,
) -> None:
    evidence.equal(f"{label} error code", expected_error, response_error(frame))
    evidence.equal(f"{label} error flag", FLAG_RESPONSE_ERROR, frame.flags)
    if frame.kind == ERROR_RESPONSE:
        if rejected_kind is not None:
            evidence.equal(f"{label} rejected kind", rejected_kind, frame.payload[4])
        if rejected_version is not None:
            evidence.equal(
                f"{label} rejected version", rejected_version, frame.payload[5]
            )


def _valid_probe(
    evidence: Evidence,
    link: SerialLink,
    label: str,
    identity: tuple[object, ...],
    expected_state: int,
    *,
    on_data: Callable[[Frame], None] | None = None,
) -> dict[str, object]:
    frame, latency = link.exchange(INFO_REQUEST, on_data=on_data)
    info = decode_info(frame)
    evidence.equal(f"{label} identity", identity, stable_identity(info))
    evidence.equal(f"{label} state", expected_state, info["device_state"])
    evidence.check(
        f"{label} deadline",
        f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
        f"{latency:.6f}s",
        latency <= COMMAND_DEADLINE_SECONDS,
    )
    return info


def _malformed_command_campaign(
    evidence: Evidence,
    link: SerialLink,
    identity: tuple[object, ...],
) -> None:
    illegal_id = link.allocate_request_id()
    illegal, latency = link.exchange_wire(
        encode_request(START_REQUEST, illegal_id),
        illegal_id,
        START_RESPONSE,
    )
    _grade_error(
        evidence,
        "IDLE START",
        illegal,
        expected_error=ERROR_INVALID_STATE,
    )
    emit_event(
        "negative_transition",
        actual="INVALID_STATE",
        command="START",
        expected="INVALID_STATE",
        state="IDLE",
        latency_seconds=latency,
    )
    _valid_probe(evidence, link, "probe after illegal IDLE START", identity, STATE_IDLE)

    cases: list[tuple[str, bytearray, int, int, int]] = []
    checksum_id = link.allocate_request_id()
    bad_checksum = bytearray(encode_request(INFO_REQUEST, checksum_id))
    bad_checksum[-1] ^= 0x80
    cases.append(
        (
            "bad checksum",
            bad_checksum,
            checksum_id,
            ERROR_CHECKSUM_MISMATCH,
            INFO_REQUEST,
        )
    )
    oversized_id = link.allocate_request_id()
    oversized = bytearray(encode_request(INFO_REQUEST, oversized_id))
    struct.pack_into("<I", oversized, 12, MAX_COMMAND_FRAME_BYTES + 1)
    cases.append(
        (
            "oversized",
            oversized,
            oversized_id,
            ERROR_INVALID_LENGTH,
            INFO_REQUEST,
        )
    )
    unknown_kind_id = link.allocate_request_id()
    unknown_kind = bytearray(encode_request(INFO_REQUEST, unknown_kind_id))
    unknown_kind[5] = 0x7F
    refresh_checksum(unknown_kind)
    cases.append(
        (
            "unknown kind",
            unknown_kind,
            unknown_kind_id,
            ERROR_UNKNOWN_FRAME_KIND,
            0x7F,
        )
    )
    unknown_version_id = link.allocate_request_id()
    unknown_version = bytearray(encode_request(INFO_REQUEST, unknown_version_id))
    unknown_version[4] = PROTOCOL_VERSION + 1
    refresh_checksum(unknown_version)
    cases.append(
        (
            "unknown version",
            unknown_version,
            unknown_version_id,
            ERROR_UNSUPPORTED_VERSION,
            INFO_REQUEST,
        )
    )
    reserved_id = link.allocate_request_id()
    reserved = bytearray(encode_request(INFO_REQUEST, reserved_id))
    reserved[11] = 1
    refresh_checksum(reserved)
    cases.append(
        (
            "reserved field",
            reserved,
            reserved_id,
            ERROR_INVALID_PAYLOAD,
            INFO_REQUEST,
        )
    )

    for label, wire, request_id, expected_error, rejected_kind in cases:
        frame, latency = link.exchange_wire(bytes(wire), request_id, ERROR_RESPONSE)
        _grade_error(
            evidence,
            label,
            frame,
            expected_error=expected_error,
            rejected_kind=rejected_kind,
            rejected_version=(
                PROTOCOL_VERSION + 1 if label == "unknown version" else PROTOCOL_VERSION
            ),
        )
        emit_event(
            "negative_command",
            actual_error=expected_error,
            case=label,
            expected_error=expected_error,
            latency_seconds=latency,
            request_id=request_id,
        )
        _valid_probe(evidence, link, f"probe after {label}", identity, STATE_IDLE)

    truncated_id = link.allocate_request_id()
    complete = encode_request(INFO_REQUEST, truncated_id)
    probe_id = link.allocate_request_id()
    probe_wire = encode_request(INFO_REQUEST, probe_id)
    responses, latency = link.exchange_batch(
        complete[:-3] + bytes((0xD2,)) * 7 + probe_wire,
        {truncated_id: ERROR_RESPONSE, probe_id: INFO_RESPONSE},
    )
    _grade_error(
        evidence,
        "truncated command",
        responses[truncated_id],
        expected_error=ERROR_CHECKSUM_MISMATCH,
        rejected_kind=INFO_REQUEST,
        rejected_version=PROTOCOL_VERSION,
    )
    recovered_info = decode_info(responses[probe_id])
    evidence.equal(
        "truncated command valid-probe identity",
        identity,
        stable_identity(recovered_info),
    )
    evidence.equal(
        "truncated command preserves IDLE", STATE_IDLE, recovered_info["device_state"]
    )
    emit_event(
        "negative_command",
        actual_error=ERROR_CHECKSUM_MISMATCH,
        case="truncated_then_garbage",
        expected_error=ERROR_CHECKSUM_MISMATCH,
        latency_seconds=latency,
        request_id=truncated_id,
    )

    duplicate_id = link.allocate_request_id()
    first, _latency = link.exchange_wire(
        encode_request(INFO_REQUEST, duplicate_id),
        duplicate_id,
        INFO_RESPONSE,
    )
    response_success(first, INFO_RESPONSE)
    duplicate, _latency = link.exchange_wire(
        encode_request(INFO_REQUEST, duplicate_id),
        duplicate_id,
        INFO_RESPONSE,
    )
    _grade_error(
        evidence,
        "duplicate request ID",
        duplicate,
        expected_error=ERROR_INVALID_REQUEST_ID,
    )
    _valid_probe(evidence, link, "probe after duplicate ID", identity, STATE_IDLE)

    status_frame, _latency = link.exchange(GET_STATUS_REQUEST)
    status = decode_status(status_frame)
    minima = {
        "bad_checksums": 2,
        "bad_lengths": 1,
        "bad_types": 1,
        "bad_versions": 1,
        "bad_payloads": 1,
        "bad_request_ids": 1,
        "state_errors": 1,
    }
    for name, minimum in minima.items():
        evidence.check(
            f"negative parser classification {name}",
            f">= {minimum}",
            status.values[name],
            status.values[name] >= minimum,
        )
    emit_event(
        "expected_negative_parser_evidence",
        **{name: status.values[name] for name in minima},
        commands_rejected=status.commands_rejected,
        parser_errors=status.parser_errors,
    )


UNEXPECTED_HARDWARE_FIELDS = (
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
    "usb_io_errors",
    "response_queue_rejections",
    "response_reservations_abandoned",
)
EXPECTED_STOP_TAIL_FIELDS = frozenset(
    {
        "adc_raw_pairs_lost",
        "gpio_raw_samples_lost",
    }
)


def _unexpected_hardware(
    status: StatusSnapshot, *, allow_stop_tail: bool = False
) -> dict[str, int]:
    return {
        name: status.values[name]
        for name in UNEXPECTED_HARDWARE_FIELDS
        if status.values[name]
        and (not allow_stop_tail or name not in EXPECTED_STOP_TAIL_FIELDS)
    }


def _physical_configuration() -> bytes:
    return CONFIGURATION.pack(
        STREAM_BOTH,
        SOURCE_HARDWARE,
        CHECKSUM_ADLER32,
        0,
        DATA_FRAME_BYTES,
    )


def _exercise_running_illegal_states(
    evidence: Evidence,
    link: SerialLink,
) -> None:
    applied = (STREAM_BOTH, SOURCE_HARDWARE, CHECKSUM_ADLER32, DATA_FRAME_BYTES)
    configured, _latency = link.exchange(CONFIGURE_REQUEST, _physical_configuration())
    evidence.equal(
        "illegal-state setup CONFIGURE",
        applied,
        decode_configuration(configured, CONFIGURE_RESPONSE),
    )
    deferred: list[Frame] = []
    started, _latency = link.exchange(START_REQUEST, on_data=deferred.append)
    evidence.equal(
        "illegal-state setup START",
        applied,
        decode_configuration(started, START_RESPONSE),
    )
    validator = DataValidator(started.run_id)
    for frame in deferred:
        validator.accept(frame)
    for label, kind, payload in (
        ("RUNNING CONFIGURE", CONFIGURE_REQUEST, _physical_configuration()),
        ("repeated RUNNING START", START_REQUEST, b""),
        ("RUNNING RESET_STATS", RESET_STATS_REQUEST, b""),
    ):
        frame, latency = link.exchange(kind, payload, on_data=validator.accept)
        _grade_error(evidence, label, frame, expected_error=ERROR_INVALID_STATE)
        emit_event(
            "negative_transition",
            actual="INVALID_STATE",
            command=label,
            expected="INVALID_STATE",
            latency_seconds=latency,
            state="RUNNING",
        )
    running_frame, _latency = link.exchange(
        GET_STATUS_REQUEST, on_data=validator.accept
    )
    running = decode_status(running_frame)
    evidence.equal(
        "illegal commands preserve RUNNING", STATE_RUNNING, running.device_state
    )
    stopped, _latency = link.exchange(STOP_REQUEST, on_data=validator.accept)
    response_success(stopped, STOP_RESPONSE)
    evidence.equal("illegal-state setup STOP", STATE_IDLE, stopped.payload[4])
    link.drain_until_quiet(validator.accept)


def _run_lifecycle_cycles(
    evidence: Evidence,
    link: SerialLink,
    cycle_count: int,
) -> int:
    applied = (STREAM_BOTH, SOURCE_HARDWARE, CHECKSUM_ADLER32, DATA_FRAME_BYTES)
    previous_run_id = 0
    for cycle in range(1, cycle_count + 1):
        configured, configure_latency = link.exchange(
            CONFIGURE_REQUEST, _physical_configuration()
        )
        actual_applied = decode_configuration(configured, CONFIGURE_RESPONSE)
        evidence.equal(f"cycle {cycle} CONFIGURE applied", applied, actual_applied)
        emit_event(
            "lifecycle_transition",
            actual="CONFIGURED",
            command="CONFIGURE",
            cycle=cycle,
            expected="CONFIGURED",
            latency_seconds=configure_latency,
        )

        deferred: list[Frame] = []
        started, start_latency = link.exchange(START_REQUEST, on_data=deferred.append)
        evidence.equal(
            f"cycle {cycle} START applied",
            applied,
            decode_configuration(started, START_RESPONSE),
        )
        expected_run = (previous_run_id + 1) & UINT32_MAX
        expected_run = expected_run or 1
        if previous_run_id:
            evidence.equal(f"cycle {cycle} run ID", expected_run, started.run_id)
        else:
            evidence.check(
                f"cycle {cycle} run ID",
                "nonzero uint32",
                started.run_id,
                started.run_id > 0,
            )
        previous_run_id = started.run_id
        validator = DataValidator(started.run_id)
        for frame in deferred:
            validator.accept(frame)
        emit_event(
            "lifecycle_transition",
            actual="RUNNING",
            command="START",
            cycle=cycle,
            expected="RUNNING",
            latency_seconds=start_latency,
            run_id=started.run_id,
        )

        status_frame, status_latency = link.exchange(
            GET_STATUS_REQUEST, on_data=validator.accept
        )
        status = decode_status(status_frame)
        evidence.equal(
            f"cycle {cycle} STATUS state", STATE_RUNNING, status.device_state
        )
        evidence.equal(
            f"cycle {cycle} STATUS run ID", started.run_id, status_frame.run_id
        )
        evidence.equal(
            f"cycle {cycle} STATUS hardware errors", {}, _unexpected_hardware(status)
        )
        emit_event(
            "lifecycle_transition",
            actual="RUNNING",
            command="STATUS",
            cycle=cycle,
            expected="RUNNING",
            latency_seconds=status_latency,
            run_id=started.run_id,
        )

        stopped, stop_latency = link.exchange(STOP_REQUEST, on_data=validator.accept)
        response_success(stopped, STOP_RESPONSE)
        evidence.equal(f"cycle {cycle} STOP state", STATE_IDLE, stopped.payload[4])
        evidence.equal(f"cycle {cycle} STOP run ID", started.run_id, stopped.run_id)
        emit_event(
            "lifecycle_transition",
            actual="IDLE",
            command="STOP",
            cycle=cycle,
            expected="IDLE",
            latency_seconds=stop_latency,
            run_id=started.run_id,
        )
        link.drain_until_quiet(validator.accept)
    evidence.check(
        "complete lifecycle cycle count", ">= 100", cycle_count, cycle_count >= 100
    )
    return previous_run_id


def _reconcile_reopen_loss(
    evidence: Evidence,
    before: StatusSnapshot,
    after: StatusSnapshot,
) -> None:
    loss: dict[str, int] = {}
    for prefix, items_per_frame, item_bytes in (
        ("adc", ADC_PAIRS_PER_FRAME, ADC_BYTES_PER_PAIR),
        ("gpio", GPIO_SAMPLES_PER_FRAME, 1),
    ):
        frames = (
            after.values[f"{prefix}_frames_dropped"]
            - before.values[f"{prefix}_frames_dropped"]
        )
        items = (
            after.values[f"{prefix}_items_dropped"]
            - before.values[f"{prefix}_items_dropped"]
        )
        payload_bytes = (
            after.values[f"{prefix}_payload_bytes_dropped"]
            - before.values[f"{prefix}_payload_bytes_dropped"]
        )
        evidence.check(
            f"expected_negative_loss.reopen.{prefix}.nonnegative",
            ">= 0 frames",
            frames,
            frames >= 0,
        )
        evidence.equal(
            f"expected_negative_loss.reopen.{prefix}.items",
            frames * items_per_frame,
            items,
        )
        evidence.equal(
            f"expected_negative_loss.reopen.{prefix}.payload_bytes",
            items * item_bytes,
            payload_bytes,
        )
        loss[f"{prefix}_frames"] = frames
        loss[f"{prefix}_items"] = items
        loss[f"{prefix}_payload_bytes"] = payload_bytes
    emit_event("expected_negative_loss", scope="cdc_close_reopen", **loss)
    unexpected = _unexpected_hardware(after)
    evidence.equal("unexpected reopen hardware errors", {}, unexpected)
    emit_event(
        "unexpected_error_snapshot", counters=unexpected, scope="cdc_close_reopen"
    )


def run_acceptance(
    open_port: Callable[[], SerialPort],
    *,
    cycle_count: int,
    reopen_pause_seconds: float,
    reopen_deadline_seconds: float,
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
) -> Evidence:
    """Run malformed-command, lifecycle, and DTR recovery campaigns."""

    evidence = Evidence()
    port: SerialPort | None = None
    link: SerialLink | None = None
    validator: DataValidator | None = None
    completed = False
    try:
        port = open_port()
        link = SerialLink(port)
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        info, _info_frame = synchronize(link)
        identity = stable_identity(info)
        _grade_info(
            evidence,
            info,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )

        initial_stop, _latency = link.exchange(STOP_REQUEST)
        response_success(initial_stop, STOP_RESPONSE)
        evidence.equal("initial STOP", STATE_IDLE, initial_stop.payload[4])
        link.drain_until_quiet(None)
        reset, _latency = link.exchange(RESET_STATS_REQUEST)
        response_success(reset, RESET_STATS_RESPONSE)

        inbound_errors_before = link.parser.errors
        _malformed_command_campaign(evidence, link, identity)
        evidence.equal(
            "unexpected inbound corruption during negative commands",
            inbound_errors_before,
            link.parser.errors,
        )
        _exercise_running_illegal_states(evidence, link)

        reset, _latency = link.exchange(RESET_STATS_REQUEST)
        response_success(reset, RESET_STATS_RESPONSE)
        last_cycle_run = _run_lifecycle_cycles(evidence, link, cycle_count)

        configured, _latency = link.exchange(
            CONFIGURE_REQUEST, _physical_configuration()
        )
        decode_configuration(configured, CONFIGURE_RESPONSE)
        deferred: list[Frame] = []
        started, _latency = link.exchange(START_REQUEST, on_data=deferred.append)
        validator = DataValidator(started.run_id)
        for frame in deferred:
            validator.accept(frame)
        expected_reopen_run = (last_cycle_run + 1) & UINT32_MAX
        expected_reopen_run = expected_reopen_run or 1
        evidence.equal("reopen campaign run ID", expected_reopen_run, started.run_id)
        reopen_baseline_deadline = time.monotonic() + reopen_deadline_seconds
        while (
            validator.adc_frames < REOPEN_BASELINE_FRAMES_PER_SOURCE
            or validator.gpio_frames < REOPEN_BASELINE_FRAMES_PER_SOURCE
        ):
            if time.monotonic() >= reopen_baseline_deadline:
                raise DeadlineExpired(
                    "pre-close live-data baseline did not complete before deadline"
                )
            probe, _latency = link.exchange(
                GET_STATUS_REQUEST, on_data=validator.accept
            )
            response_success(probe, GET_STATUS_RESPONSE)
        before_frame, _latency = link.exchange(
            GET_STATUS_REQUEST, on_data=validator.accept
        )
        before = decode_status(before_frame)
        evidence.equal("pre-close state", STATE_RUNNING, before.device_state)
        old_inbound_errors = link.parser.errors

        emit_event(
            "cdc_close",
            actual_state="port closed",
            expected_device_state="RUNNING",
            run_id=started.run_id,
        )
        close_started = time.monotonic()
        port.close()
        port = None
        time.sleep(reopen_pause_seconds)
        port = open_port()
        link = SerialLink(port)
        reopened_info, reopened_info_frame = synchronize(
            link,
            on_data=validator.accept,
        )
        reopen_elapsed = time.monotonic() - close_started
        evidence.equal("reopen identity", identity, stable_identity(reopened_info))
        evidence.equal(
            "reopen INFO state", STATE_RUNNING, reopened_info["device_state"]
        )
        evidence.equal("reopen INFO run ID", started.run_id, reopened_info_frame.run_id)
        evidence.check(
            "bounded CDC reopen",
            f"<= {reopen_deadline_seconds:.3f}s",
            f"{reopen_elapsed:.6f}s",
            reopen_elapsed <= reopen_deadline_seconds,
        )
        emit_event(
            "cdc_reopen",
            actual_state="RUNNING",
            elapsed_seconds=reopen_elapsed,
            expected_state="RUNNING",
            run_id=reopened_info_frame.run_id,
        )

        after_frame, status_latency = link.exchange(
            GET_STATUS_REQUEST, on_data=validator.accept
        )
        after = decode_status(after_frame)
        evidence.equal("post-reopen STATUS state", STATE_RUNNING, after.device_state)
        evidence.equal("post-reopen STATUS run ID", started.run_id, after_frame.run_id)
        evidence.check(
            "post-reopen STATUS deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{status_latency:.6f}s",
            status_latency <= COMMAND_DEADLINE_SECONDS,
        )
        _reconcile_reopen_loss(evidence, before, after)
        evidence.equal(
            "unexpected old-session inbound corruption", 0, old_inbound_errors
        )
        evidence.equal(
            "unexpected new-session inbound corruption", 0, link.parser.errors
        )

        stopped, stop_latency = link.exchange(STOP_REQUEST, on_data=validator.accept)
        response_success(stopped, STOP_RESPONSE)
        evidence.equal("reopened STOP state", STATE_IDLE, stopped.payload[4])
        evidence.equal("reopened STOP run ID", started.run_id, stopped.run_id)
        evidence.check(
            "reopened STOP deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{stop_latency:.6f}s",
            stop_latency <= COMMAND_DEADLINE_SECONDS,
        )
        link.drain_until_quiet(validator.accept)
        final_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        final_status = decode_status(final_frame)
        evidence.equal("final STATUS state", STATE_IDLE, final_status.device_state)
        evidence.equal("final STATUS stream mask", 0, final_status.stream_mask)
        evidence.equal("final STATUS run ID", started.run_id, final_frame.run_id)
        final_stop_tail = {
            name: final_status.values[name]
            for name in EXPECTED_STOP_TAIL_FIELDS
            if final_status.values[name]
        }
        emit_event(
            "expected_negative_loss",
            counters=final_stop_tail,
            scope="bounded_stop_tail",
        )
        evidence.equal(
            "final unexpected hardware errors",
            {},
            _unexpected_hardware(final_status, allow_stop_tail=True),
        )
        evidence.equal("late response count", 0, link.stale_responses)
        completed = not evidence.failures
    except Exception as error:  # noqa: BLE001 - stdout is the remote diagnosis
        message = f"{type(error).__name__}: {error}"
        emit_event("fatal", error=message)
        evidence.failures.append(message)
    finally:
        if not completed and link is not None:
            try:
                cleanup, _latency = link.exchange(
                    STOP_REQUEST,
                    on_data=(validator.accept if validator is not None else None),
                )
                emit_event(
                    "cleanup_stop",
                    actual_state=(
                        cleanup.payload[4] if len(cleanup.payload) > 4 else None
                    ),
                    expected_state=STATE_IDLE,
                )
            except Exception as cleanup_error:  # noqa: BLE001 - best effort only
                emit_event(
                    "cleanup_stop_failed",
                    error=f"{type(cleanup_error).__name__}: {cleanup_error}",
                )
        if port is not None:
            port.close()
    return evidence


def _bounded_float_environment(name: str, default: float, maximum: float) -> float:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be finite and in [0, {maximum}]")
    return value


def _cycle_count_environment() -> int:
    raw = os.environ.get("CONTROL_RECOVERY_CYCLES")
    try:
        value = DEFAULT_CYCLE_COUNT if raw is None else int(raw, 0)
    except ValueError as error:
        raise ValueError("CONTROL_RECOVERY_CYCLES must be an integer") from error
    if not DEFAULT_CYCLE_COUNT <= value <= MAX_CYCLE_COUNT:
        raise ValueError(
            f"CONTROL_RECOVERY_CYCLES must be in "
            f"{DEFAULT_CYCLE_COUNT}..{MAX_CYCLE_COUNT}"
        )
    return value


def _optional_uint32_environment(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        value = int(raw, 0)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= value <= UINT32_MAX:
        raise ValueError(f"{name} must be a nonzero uint32")
    return value


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        emit_event("configuration_error", error="SERIAL_PORT is required")
        return 2
    try:
        cycle_count = _cycle_count_environment()
        reopen_pause_seconds = _bounded_float_environment(
            "REOPEN_PAUSE_SECONDS",
            DEFAULT_REOPEN_PAUSE_SECONDS,
            MAX_REOPEN_PAUSE_SECONDS,
        )
        reopen_deadline_seconds = _bounded_float_environment(
            "REOPEN_DEADLINE_SECONDS",
            DEFAULT_REOPEN_DEADLINE_SECONDS,
            MAX_REOPEN_DEADLINE_SECONDS,
        )
        if reopen_deadline_seconds <= 0:
            raise ValueError("REOPEN_DEADLINE_SECONDS must be positive")
        expected_hardware_serial = _optional_uint32_environment(
            "EXPECTED_HARDWARE_SERIAL"
        )
    except ValueError as error:
        emit_event("configuration_error", error=str(error))
        return 2
    expected_build_id = os.environ.get("EXPECTED_BUILD_ID")
    emit_event(
        "program_start",
        cycles=cycle_count,
        port=port_name,
        protocol=PROTOCOL_VERSION,
        reopen_deadline_seconds=reopen_deadline_seconds,
        reopen_pause_seconds=reopen_pause_seconds,
    )

    def open_port() -> SerialPort:
        return serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )

    try:
        evidence = run_acceptance(
            open_port,
            cycle_count=cycle_count,
            reopen_pause_seconds=reopen_pause_seconds,
            reopen_deadline_seconds=reopen_deadline_seconds,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
    except Exception as error:  # noqa: BLE001 - initial/reopen failure is rig-visible
        emit_event("open_or_run_failed", error=f"{type(error).__name__}: {error}")
        return 2
    summary = {
        "checks": evidence.check_count,
        "cycles": cycle_count,
        "failures": evidence.failures,
        "result": "PASS" if not evidence.failures else "FAIL",
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if not evidence.failures else 1


if __name__ == "__main__":
    sys.exit(main())
