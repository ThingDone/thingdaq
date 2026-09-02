#!/usr/bin/env python3
"""Independent ThingDAQ 1.0 basic control test for the hardware rig.

The rig uploads this file alone to a network-disabled Python 3.13 container.
It intentionally uses only the standard library and pyserial, and does not
import the project package or generated protocol constants.
"""

from __future__ import annotations

import os
import re
import struct
import sys
import time
import zlib
from dataclasses import dataclass
from typing import Protocol

import serial

BAUD_RATE = 115_200
SERIAL_READ_TIMEOUT_SECONDS = 0.05
SERIAL_WRITE_TIMEOUT_SECONDS = 0.5
STARTUP_DRAIN_SECONDS = 0.25
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 1.0

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 1
HEADER_SIZE = 44
TRAILER_SIZE = 4
MAX_CONTROL_FRAME_BYTES = 1280
DATA_FRAME_BYTES = 4096
CHECKSUM_ADLER32 = 1
RESPONSE_ERROR = 0x8000

INFO_REQUEST = 0x10
CONFIGURE_REQUEST = 0x11
START_REQUEST = 0x12
GET_STATUS_REQUEST = 0x13
STOP_REQUEST = 0x14
RESET_STATS_REQUEST = 0x15
PING_REQUEST = 0x16
CHECKSUM_BENCHMARK_REQUEST = 0x17
GPIO_CLOCK_DIAGNOSTIC_REQUEST = 0x18
GPIO_CAPTURE_DIAGNOSTIC_REQUEST = 0x19

INFO_RESPONSE = 0x90
CONFIGURE_RESPONSE = 0x91
START_RESPONSE = 0x92
GET_STATUS_RESPONSE = 0x93
STOP_RESPONSE = 0x94
RESET_STATS_RESPONSE = 0x95
PING_RESPONSE = 0x96
CHECKSUM_BENCHMARK_RESPONSE = 0x97
GPIO_CLOCK_DIAGNOSTIC_RESPONSE = 0x98
GPIO_CAPTURE_DIAGNOSTIC_RESPONSE = 0x99
ERROR_RESPONSE = 0x9F

STATE_IDLE = 1
STATE_CONFIGURED = 2
STATE_RUNNING = 3
SOURCE_HARDWARE = 0
SOURCE_SYNTHETIC = 1
STREAM_NONE = 0
STREAM_ADC = 1
STREAM_GPIO = 2
STREAM_BOTH = STREAM_ADC | STREAM_GPIO
CAPABILITY_ADC_STREAM = 1
CAPABILITY_GPIO_STREAM = 2
CAPABILITY_HARDWARE_SOURCE = 4
CAPABILITY_SYNTHETIC_SOURCE = 8
CAPABILITY_RESET_STATS = 16
CAPABILITY_PING = 32
CAPABILITY_CHECKSUM_BENCHMARK = 64
CAPABILITY_GPIO_CLOCK_DIAGNOSTIC = 128
CAPABILITY_GPIO_CAPTURE_DIAGNOSTIC = 256
EXPECTED_CAPABILITIES = (
    CAPABILITY_ADC_STREAM
    | CAPABILITY_GPIO_STREAM
    | CAPABILITY_HARDWARE_SOURCE
    | CAPABILITY_SYNTHETIC_SOURCE
    | CAPABILITY_RESET_STATS
    | CAPABILITY_PING
    | CAPABILITY_CHECKSUM_BENCHMARK
    | CAPABILITY_GPIO_CLOCK_DIAGNOSTIC
    | CAPABILITY_GPIO_CAPTURE_DIAGNOSTIC
)
SUPPORTED_CONFIGURATION_MASK = 0x003F
ERROR_UNSUPPORTED_CONFIGURATION = 8
ERROR_CHECKSUM_MISMATCH = 12

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
    CHECKSUM_BENCHMARK_REQUEST: CHECKSUM_BENCHMARK_RESPONSE,
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
    PING_REQUEST: 8,
    CHECKSUM_BENCHMARK_REQUEST: 8,
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
    PING_RESPONSE: 12,
    CHECKSUM_BENCHMARK_RESPONSE: 96,
    GPIO_CLOCK_DIAGNOSTIC_RESPONSE: 140,
    GPIO_CAPTURE_DIAGNOSTIC_RESPONSE: 144,
    ERROR_RESPONSE: 8,
}


class ProtocolFailure(RuntimeError):
    """The rig observed an invalid or unexpected wire event."""


class DeadlineExpired(ProtocolFailure):
    """A finite serial operation did not complete by its deadline."""


class SerialPort(Protocol):
    """The narrow pyserial surface used by this self-contained script."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Frame:
    kind: int
    flags: int
    run_id: int
    request_id: int
    payload: bytes


def encode_request(kind: int, request_id: int, payload: bytes = b"") -> bytes:
    """Independently encode one bounded protocol-v1 request."""

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
    """Bounded resynchronizing parser for arbitrary CDC read boundaries."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.bytes_discarded = 0
        self.invalid_candidates = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(data)
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
            try:
                fields = HEADER.unpack_from(self.buffer)
                total_length = self._validate_header(fields)
            except ProtocolFailure:
                self.invalid_candidates += 1
                self._discard(1)
                continue
            if len(self.buffer) < total_length:
                break
            payload_length = fields[8]
            payload_end = HEADER_SIZE + payload_length
            expected = zlib.adler32(self.buffer[:payload_end]) & 0xFFFFFFFF
            actual = TRAILER.unpack_from(self.buffer, payload_end)[0]
            if actual != expected:
                self.invalid_candidates += 1
                self._discard(1)
                continue
            frame = Frame(
                kind=fields[2],
                flags=fields[3],
                run_id=fields[9],
                request_id=fields[11],
                payload=bytes(self.buffer[HEADER_SIZE:payload_end]),
            )
            self._validate_payload(frame)
            del self.buffer[:total_length]
            frames.append(frame)
        if len(self.buffer) > MAX_CONTROL_FRAME_BYTES + len(MAGIC_BYTES) - 1:
            raise ProtocolFailure("frame parser exceeded its fixed control-frame bound")
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
            _run_id,
            sequence,
            request_id,
            first_sample_ticks,
            item_count,
        ) = fields
        if magic != MAGIC or version != PROTOCOL_VERSION:
            raise ProtocolFailure("invalid response magic or version")
        if kind not in SUCCESS_PAYLOAD_SIZE:
            raise ProtocolFailure(f"unknown response kind 0x{kind:02x}")
        if flags not in {0, RESPONSE_ERROR}:
            raise ProtocolFailure(f"invalid response flags 0x{flags:04x}")
        if kind == ERROR_RESPONSE and flags != RESPONSE_ERROR:
            raise ProtocolFailure("generic ERROR_RESPONSE lacks its error flag")
        if header_length != HEADER_SIZE or checksum != CHECKSUM_ADLER32 or reserved:
            raise ProtocolFailure("invalid fixed response header fields")
        if total_length != HEADER_SIZE + payload_length + TRAILER_SIZE:
            raise ProtocolFailure("inconsistent response lengths")
        if not HEADER_SIZE + TRAILER_SIZE <= total_length <= MAX_CONTROL_FRAME_BYTES:
            raise ProtocolFailure("response exceeds the control-frame bound")
        expected_payload = (
            4
            if flags == RESPONSE_ERROR and kind != ERROR_RESPONSE
            else (SUCCESS_PAYLOAD_SIZE[kind])
        )
        if payload_length != expected_payload:
            raise ProtocolFailure("response payload length does not match its kind")
        if request_id == 0 or sequence or first_sample_ticks or item_count:
            raise ProtocolFailure("invalid response correlation or data-only fields")
        return total_length

    @staticmethod
    def _validate_payload(frame: Frame) -> None:
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == RESPONSE_ERROR
        if reserved or is_error != (status == 1) or (error == 0) == is_error:
            raise ProtocolFailure("response prefix status, flag, or error disagrees")
        if not is_error and status != 0:
            raise ProtocolFailure("successful response has a nonzero status")
        if error > 12:
            raise ProtocolFailure("response reports an unknown error code")
        payload = frame.payload
        if not is_error and frame.kind == INFO_RESPONSE:
            if (
                payload[1]
                or payload[61]
                or any(payload[118:120])
                or payload[127]
                or any(payload[154:156])
                or any(payload[334:336])
            ):
                raise ProtocolFailure("INFO reserved fields are nonzero")
            checksum_mask = struct.unpack_from("<I", payload, 8)[0]
            if not checksum_mask & (1 << payload[45]):
                raise ProtocolFailure("INFO selected checksum is not advertised")
        elif not is_error and frame.kind in {CONFIGURE_RESPONSE, START_RESPONSE}:
            if payload[1] or payload[7]:
                raise ProtocolFailure(
                    "configuration response reserved fields are nonzero"
                )
        elif not is_error and frame.kind == GET_STATUS_RESPONSE and payload[1]:
            raise ProtocolFailure("STATUS reserved field is nonzero")
        elif (
            not is_error
            and frame.kind == STOP_RESPONSE
            and any(payload[1:2] + payload[5:])
        ):
            raise ProtocolFailure("STOP reserved fields are nonzero")
        elif (
            not is_error
            and frame.kind in {RESET_STATS_RESPONSE, PING_RESPONSE}
            and payload[1]
        ):
            raise ProtocolFailure("response reserved field is nonzero")

    def _partial_magic_suffix(self) -> int:
        for length in range(min(3, len(self.buffer)), 0, -1):
            if self.buffer.endswith(MAGIC_BYTES[:length]):
                return length
        return 0

    def _discard(self, count: int) -> None:
        if count > 0:
            del self.buffer[:count]
            self.bytes_discarded += count


class SerialLink:
    def __init__(self, port: SerialPort) -> None:
        self.port = port
        self.parser = FrameParser()
        self.ready: list[Frame] = []
        self.next_request_id = 1
        self.stale_frames = 0

    def drain_startup(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        valid_frames = 0
        while time.monotonic() < deadline:
            chunk = self.port.read(256)
            if chunk:
                valid_frames += len(self.parser.feed(bytes(chunk)))
        print(
            "SYNC startup drain: "
            f"discarded_bytes={self.parser.bytes_discarded} "
            f"valid_stale_frames={valid_frames}"
        )

    def exchange(
        self,
        request_kind: int,
        payload: bytes = b"",
        timeout: float | None = None,
    ) -> tuple[Frame, float]:
        request_id = self._allocate_request_id()
        wire = encode_request(request_kind, request_id, payload)
        started = time.monotonic()
        deadline = started + (COMMAND_DEADLINE_SECONDS if timeout is None else timeout)
        self._write_all(wire, deadline)
        response_kind = REQUEST_RESPONSE_KIND[request_kind]
        while True:
            frame = self._read_frame(deadline)
            if frame.request_id != request_id:
                self.stale_frames += 1
                print(
                    "SYNC discarding late response: "
                    f"request_id={frame.request_id} kind=0x{frame.kind:02x}"
                )
                continue
            if frame.kind != response_kind:
                raise ProtocolFailure(
                    f"request {request_id} expected kind 0x{response_kind:02x}, "
                    f"received 0x{frame.kind:02x}"
                )
            return frame, time.monotonic() - started

    def send_corrupt_and_expect_rejection(
        self, request_kind: int
    ) -> tuple[Frame, float]:
        request_id = self._allocate_request_id()
        wire = bytearray(encode_request(request_kind, request_id))
        wire[-1] ^= 0x80
        started = time.monotonic()
        deadline = started + COMMAND_DEADLINE_SECONDS
        self._write_all(bytes(wire), deadline)
        while True:
            frame = self._read_frame(deadline)
            if frame.request_id != request_id:
                self.stale_frames += 1
                continue
            if frame.kind != ERROR_RESPONSE:
                raise ProtocolFailure(
                    "checksum-corrupt request expected a generic rejection, "
                    f"received kind=0x{frame.kind:02x}"
                )
            return frame, time.monotonic() - started

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

    def _read_frame(self, deadline: float) -> Frame:
        while True:
            if self.ready:
                return self.ready.pop(0)
            self.ready.extend(self.parser.feed(b""))
            if self.ready:
                return self.ready.pop(0)
            if time.monotonic() >= deadline:
                raise DeadlineExpired(
                    "no complete response arrived before the deadline"
                )
            chunk = self.port.read(256)
            if chunk:
                self.ready.extend(self.parser.feed(bytes(chunk)))
                if self.ready:
                    return self.ready.pop(0)


class Evidence:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, expected: object, actual: object, passed: bool) -> None:
        outcome = "PASS" if passed else "FAIL"
        print(f"CHECK {label}: expected={expected!r} actual={actual!r} [{outcome}]")
        if not passed:
            self.failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    def equal(self, label: str, expected: object, actual: object) -> None:
        self.check(label, expected, actual, actual == expected)

    def latency(self, label: str, seconds: float) -> None:
        self.check(
            f"{label} latency",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{seconds:.6f}s",
            seconds <= COMMAND_DEADLINE_SECONDS,
        )


def response_prefix(frame: Frame) -> tuple[int, int]:
    status, _reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
    return status, error


def decode_info(frame: Frame) -> dict[str, object]:
    if frame.kind != INFO_RESPONSE or frame.flags:
        raise ProtocolFailure("INFO did not return a successful typed response")
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
        "applied_stream_mask": payload[324],
        "applied_source": payload[325],
        "supported_configuration_mask": struct.unpack_from("<H", payload, 326)[0],
    }


def decode_configuration(frame: Frame) -> tuple[int, int, int, int]:
    if frame.flags:
        raise ProtocolFailure("configuration command returned an error")
    streams, source, checksum, reserved, frame_bytes = CONFIGURATION.unpack_from(
        frame.payload, 4
    )
    if reserved:
        raise ProtocolFailure("applied configuration reserved byte is nonzero")
    return streams, source, checksum, frame_bytes


def decode_status(frame: Frame) -> dict[str, int]:
    if frame.kind != GET_STATUS_RESPONSE or frame.flags:
        raise ProtocolFailure("STATUS did not return a successful typed response")
    payload = frame.payload
    return {
        "device_state": payload[4],
        "stream_mask": payload[5],
        "source": payload[6],
        "checksum": payload[7],
        "data_frame_bytes": struct.unpack_from("<I", payload, 8)[0],
        "adc_frames_emitted": struct.unpack_from("<Q", payload, 12)[0],
        "gpio_frames_emitted": struct.unpack_from("<Q", payload, 20)[0],
        "adc_items_dropped": struct.unpack_from("<Q", payload, 28)[0],
        "gpio_items_dropped": struct.unpack_from("<Q", payload, 36)[0],
        "parser_errors": struct.unpack_from("<I", payload, 44)[0],
        "transport_errors": struct.unpack_from("<I", payload, 48)[0],
        "stats_generation": struct.unpack_from("<I", payload, 52)[0],
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


def synchronize(link: SerialLink) -> dict[str, object]:
    first: tuple[object, ...] | None = None
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, _latency = link.exchange(
                INFO_REQUEST,
                timeout=SYNC_DEADLINE_SECONDS,
            )
            if frame.flags:
                _status, error = response_prefix(frame)
                last_error = f"typed INFO error {error}"
                continue
            info = decode_info(frame)
            identity = stable_identity(info)
            if first is None:
                first = identity
                print(f"SYNC valid throwaway INFO on attempt {attempt}")
            elif identity == first:
                print(f"SYNC stable INFO confirmed on attempt {attempt}")
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


def next_generation(current: int) -> int:
    result = (current + 1) & 0xFFFFFFFF
    return result or 1


def grade_info(evidence: Evidence, info: dict[str, object]) -> None:
    exact = {
        "device_state": STATE_IDLE,
        "protocol_version": PROTOCOL_VERSION,
        "supported_stream_mask": STREAM_BOTH,
        "supported_source_mask": (1 << SOURCE_HARDWARE) | (1 << SOURCE_SYNTHETIC),
        "supported_checksum_mask": 0b1110,
        "capability_bits": EXPECTED_CAPABILITIES,
        "timestamp_hz": 8_000_000,
        "data_frame_bytes": DATA_FRAME_BYTES,
        "max_control_frame_bytes": MAX_CONTROL_FRAME_BYTES,
        "adc_pair_rate_hz": 1_000_000,
        "gpio_sample_rate_hz": 4_000_000,
        "adc_pair_period_ticks": 8,
        "adc1_phase_ticks": 4,
        "gpio_sample_period_ticks": 2,
        "adc_resolution_bits": 12,
        "adc_container_bytes": 2,
        "gpio_pin_count": 8,
        "data_checksum_algorithm": CHECKSUM_ADLER32,
        "gpio_pin_map": tuple(range(6, 14)),
        "firmware_version": (1, 0, 0),
        "board_id": 1,
        "mcu_id": 1,
        "applied_stream_mask": STREAM_NONE,
        "applied_source": SOURCE_HARDWARE,
        "supported_configuration_mask": SUPPORTED_CONFIGURATION_MASK,
    }
    for name, expected in exact.items():
        evidence.equal(f"INFO {name}", expected, info[name])
    hardware_serial = info["hardware_serial"]
    evidence.check(
        "INFO hardware_serial",
        "nonzero uint32",
        hardware_serial,
        isinstance(hardware_serial, int) and 1 <= hardware_serial <= 0xFFFFFFFF,
    )
    build_id = info["build_id"]
    evidence.check(
        "INFO build_id",
        "thingdaq-<16 lowercase hex>",
        build_id,
        isinstance(build_id, str)
        and re.fullmatch(r"thingdaq-[0-9a-f]{16}", build_id) is not None,
    )


def grade_success(evidence: Evidence, label: str, frame: Frame) -> None:
    status, error = response_prefix(frame)
    evidence.equal(f"{label} response status", 0, status)
    evidence.equal(f"{label} error code", 0, error)


def grade_control_status(
    evidence: Evidence,
    label: str,
    status: dict[str, int],
    *,
    expected_stream_mask: int = STREAM_NONE,
    expected_source: int = SOURCE_HARDWARE,
) -> None:
    expected = {
        "stream_mask": expected_stream_mask,
        "source": expected_source,
        "checksum": CHECKSUM_ADLER32,
        "data_frame_bytes": DATA_FRAME_BYTES,
    }
    for field, value in expected.items():
        evidence.equal(f"{label} {field}", value, status[field])
    evidence.check(
        f"{label} stats_generation",
        "nonzero uint32",
        status["stats_generation"],
        1 <= status["stats_generation"] <= 0xFFFFFFFF,
    )


def run_acceptance(port: SerialPort) -> Evidence:
    evidence = Evidence()
    link = SerialLink(port)
    completed = False
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        synchronized_info = synchronize(link)

        info_frame, latency = link.exchange(INFO_REQUEST)
        evidence.latency("INFO", latency)
        grade_success(evidence, "INFO", info_frame)
        info = decode_info(info_frame)
        evidence.equal("INFO run_id at boot", 0, info_frame.run_id)
        evidence.equal(
            "graded identity matches synchronization",
            stable_identity(synchronized_info),
            stable_identity(info),
        )
        grade_info(evidence, info)

        nonce = 0x0123456789ABCDEF
        ping_frame, latency = link.exchange(PING_REQUEST, struct.pack("<Q", nonce))
        evidence.latency("PING", latency)
        grade_success(evidence, "PING", ping_frame)
        evidence.equal(
            "PING nonce echo", nonce, struct.unpack_from("<Q", ping_frame.payload, 4)[0]
        )

        invalid_configuration = CONFIGURATION.pack(
            STREAM_NONE, SOURCE_HARDWARE, CHECKSUM_ADLER32, 0, DATA_FRAME_BYTES
        )
        invalid_frame, latency = link.exchange(CONFIGURE_REQUEST, invalid_configuration)
        evidence.latency("invalid CONFIGURE", latency)
        status, error = response_prefix(invalid_frame)
        evidence.equal("invalid CONFIGURE response status", 1, status)
        evidence.equal(
            "invalid CONFIGURE error",
            ERROR_UNSUPPORTED_CONFIGURATION,
            error,
        )
        evidence.equal(
            "invalid CONFIGURE error flag", RESPONSE_ERROR, invalid_frame.flags
        )

        idle_frame, latency = link.exchange(GET_STATUS_REQUEST)
        evidence.latency("post-rejection STATUS", latency)
        idle_status = decode_status(idle_frame)
        evidence.equal(
            "invalid command preserves IDLE", STATE_IDLE, idle_status["device_state"]
        )
        grade_control_status(evidence, "IDLE STATUS", idle_status)
        evidence.equal("run_id before CONFIGURE", 0, idle_frame.run_id)

        control_configuration = CONFIGURATION.pack(
            STREAM_ADC, SOURCE_SYNTHETIC, CHECKSUM_ADLER32, 0, DATA_FRAME_BYTES
        )
        configured_frame, latency = link.exchange(
            CONFIGURE_REQUEST, control_configuration
        )
        evidence.latency("CONFIGURE", latency)
        grade_success(evidence, "CONFIGURE", configured_frame)
        evidence.equal(
            "CONFIGURE applied profile",
            (STREAM_ADC, SOURCE_SYNTHETIC, CHECKSUM_ADLER32, DATA_FRAME_BYTES),
            decode_configuration(configured_frame),
        )

        configured_status_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        configured_status = decode_status(configured_status_frame)
        evidence.equal(
            "CONFIGURE enters CONFIGURED",
            STATE_CONFIGURED,
            configured_status["device_state"],
        )
        grade_control_status(
            evidence,
            "CONFIGURED STATUS",
            configured_status,
            expected_stream_mask=STREAM_ADC,
            expected_source=SOURCE_SYNTHETIC,
        )
        evidence.equal("CONFIGURE preserves run_id", 0, configured_status_frame.run_id)

        corrupt_frame, latency = link.send_corrupt_and_expect_rejection(INFO_REQUEST)
        evidence.latency("checksum-corrupt INFO rejection", latency)
        status, error = response_prefix(corrupt_frame)
        evidence.equal("checksum rejection response status", 1, status)
        evidence.equal("checksum rejection error", ERROR_CHECKSUM_MISMATCH, error)
        evidence.equal(
            "checksum rejection error flag", RESPONSE_ERROR, corrupt_frame.flags
        )
        evidence.equal("checksum rejection run_id", 0, corrupt_frame.run_id)
        evidence.equal(
            "checksum rejection rejected kind", INFO_REQUEST, corrupt_frame.payload[4]
        )
        evidence.equal(
            "checksum rejection rejected version",
            PROTOCOL_VERSION,
            corrupt_frame.payload[5],
        )
        evidence.equal(
            "checksum rejection reserved fields",
            b"\x00\x00\x00",
            corrupt_frame.payload[1:2] + corrupt_frame.payload[6:8],
        )
        damaged_status_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        damaged_status = decode_status(damaged_status_frame)
        evidence.equal(
            "corrupt command preserves CONFIGURED",
            STATE_CONFIGURED,
            damaged_status["device_state"],
        )
        grade_control_status(
            evidence,
            "post-corruption STATUS",
            damaged_status,
            expected_stream_mask=STREAM_ADC,
            expected_source=SOURCE_SYNTHETIC,
        )
        evidence.check(
            "parser error counter before reset",
            f"> {configured_status['parser_errors']}",
            damaged_status["parser_errors"],
            damaged_status["parser_errors"] > configured_status["parser_errors"],
        )

        stop_frame, latency = link.exchange(STOP_REQUEST)
        evidence.latency("STOP", latency)
        grade_success(evidence, "STOP", stop_frame)
        evidence.equal("STOP enters IDLE", STATE_IDLE, stop_frame.payload[4])
        second_stop, latency = link.exchange(STOP_REQUEST)
        evidence.latency("idempotent STOP", latency)
        grade_success(evidence, "idempotent STOP", second_stop)
        evidence.equal(
            "idempotent STOP remains IDLE", STATE_IDLE, second_stop.payload[4]
        )
        evidence.equal("STOP preserves zero run_id", 0, second_stop.run_id)

        before_reset_frame, _latency = link.exchange(GET_STATUS_REQUEST)
        before_reset = decode_status(before_reset_frame)
        evidence.equal("pre-reset state", STATE_IDLE, before_reset["device_state"])
        evidence.equal(
            "STOP preserves statistics generation",
            damaged_status["stats_generation"],
            before_reset["stats_generation"],
        )

        reset_frame, latency = link.exchange(RESET_STATS_REQUEST)
        evidence.latency("RESET_STATS", latency)
        grade_success(evidence, "RESET_STATS", reset_frame)
        reset_generation = struct.unpack_from("<I", reset_frame.payload, 4)[0]
        evidence.equal(
            "RESET_STATS generation increment",
            next_generation(before_reset["stats_generation"]),
            reset_generation,
        )

        final_frame, latency = link.exchange(GET_STATUS_REQUEST)
        evidence.latency("final STATUS", latency)
        final_status = decode_status(final_frame)
        evidence.equal("final state", STATE_IDLE, final_status["device_state"])
        grade_control_status(evidence, "final STATUS", final_status)
        evidence.equal("final run_id", 0, final_frame.run_id)
        evidence.equal(
            "final statistics generation",
            reset_generation,
            final_status["stats_generation"],
        )
        for counter in (
            "adc_frames_emitted",
            "gpio_frames_emitted",
            "adc_items_dropped",
            "gpio_items_dropped",
            "parser_errors",
            "transport_errors",
        ):
            evidence.equal(f"final {counter}", 0, final_status[counter])
        evidence.equal("late/interleaved response count", 0, link.stale_frames)
        completed = True
    except Exception as error:  # noqa: BLE001 - stdout is the remote diagnosis
        message = f"{type(error).__name__}: {error}"
        print(f"FATAL expected='complete bounded control lifecycle' actual={message!r}")
        evidence.failures.append(message)
    finally:
        if not completed:
            try:
                cleanup, _latency = link.exchange(STOP_REQUEST)
                print(
                    "CLEANUP STOP: "
                    f"state={cleanup.payload[4] if len(cleanup.payload) > 4 else 'unknown'}"
                )
            except Exception as cleanup_error:  # noqa: BLE001 - best effort only
                print(f"CLEANUP STOP failed: {cleanup_error}")
    return evidence


def main() -> int:
    port_name = os.environ.get("SERIAL_PORT")
    if not port_name:
        print("FAIL: SERIAL_PORT is required")
        return 2
    print(
        f"ThingDAQ 1.0 basic rig smoke: port={port_name!r} "
        f"baud={BAUD_RATE} protocol={PROTOCOL_VERSION}"
    )
    try:
        port = serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_SECONDS,
            write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - print the rig-visible open failure
        print(f"FAIL: could not open SERIAL_PORT: {type(error).__name__}: {error}")
        return 2
    try:
        evidence = run_acceptance(port)
    finally:
        port.close()
    if evidence.failures:
        print(f"\nFAIL ({len(evidence.failures)} check(s)):")
        for failure in evidence.failures:
            print(f"  - {failure}")
        return 1
    print(
        "\nPASS: ThingDAQ 1.0 identity, configuration, recovery, and counters verified"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
