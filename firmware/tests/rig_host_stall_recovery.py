#!/usr/bin/env python3
"""Independent Phase 09 host-stall and live-recovery hardware acceptance.

The remote rig uploads this file by itself to a network-disabled Python
container.  It intentionally embeds the protocol-v1 values it grades and uses
only the Python standard library plus pyserial; it never imports the project
package or generated constants.

The program starts physical ADC+GPIO acquisition, establishes a zero-loss
baseline, deliberately performs no serial reads for a bounded interval, then
resumes draining.  It validates every retained frame, catches both streams up
past a running STATUS snapshot, and independently reconciles sequence gaps,
timestamp gaps, GAP/OVERRUN flags, complete-frame loss, item loss, byte loss,
pressure eviction, and the packet ownership conservation equations.
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
STOP_DRAIN_DEADLINE_SECONDS = 2.0
STOP_DRAIN_QUIET_SECONDS = 0.10
DEFAULT_STALL_SECONDS = 1.0
DEFAULT_RECOVERY_DEADLINE_SECONDS = 10.0
DEFAULT_BASELINE_FRAMES_PER_SOURCE = 4
POST_SNAPSHOT_FRAMES_PER_SOURCE = 2
MAX_STALL_SECONDS = 30.0
MAX_RECOVERY_DEADLINE_SECONDS = 60.0
MAX_STABILIZATION_SNAPSHOTS = 4

MAGIC = 0xDEADBEEF
MAGIC_BYTES = b"\xef\xbe\xad\xde"
PROTOCOL_VERSION = 1
HEADER_SIZE = 44
TRAILER_SIZE = 4
DATA_FRAME_BYTES = 4096
DATA_PAYLOAD_BYTES = 4048
MAX_CONTROL_FRAME_BYTES = 1364
MAX_FRAME_BYTES = DATA_FRAME_BYTES
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

ADC_PAIRS_PER_FRAME = 1012
ADC_BYTES_PER_PAIR = 4
GPIO_SAMPLES_PER_FRAME = 4048
FRAME_COVERAGE_TICKS = 8096
UINT32_MAX = 0xFFFFFFFF
UINT64_MAX = 0xFFFFFFFFFFFFFFFF

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
    """The rig observed an invalid or unreconciled wire event."""


class DeadlineExpired(ProtocolFailure):
    """A finite serial operation did not complete by its deadline."""


class SerialPort(Protocol):
    """The narrow pyserial surface used by this self-contained program."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Frame:
    """One independently structure- and checksum-validated wire frame."""

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


class FrameParser:
    """Bounded resynchronizing parser for arbitrary high-rate CDC chunks."""

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
            body_start = self.scan_start
            expected = zlib.adler32(self.buffer[body_start:payload_end]) & UINT32_MAX
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
            raise ProtocolFailure("parser retained more than one bounded frame")
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
            raise ProtocolFailure("invalid frame magic or version")
        if kind not in DATA_KINDS and kind not in SUCCESS_PAYLOAD_SIZE:
            raise ProtocolFailure(f"unknown inbound kind 0x{kind:02x}")
        if header_length != HEADER_SIZE or checksum != CHECKSUM_ADLER32 or reserved:
            raise ProtocolFailure("invalid fixed header fields")
        if total_length != HEADER_SIZE + payload_length + TRAILER_SIZE:
            raise ProtocolFailure("inconsistent frame lengths")
        if not HEADER_SIZE + TRAILER_SIZE <= total_length <= MAX_FRAME_BYTES:
            raise ProtocolFailure("frame length is outside the fixed bound")
        if kind in DATA_KINDS:
            if (
                total_length != DATA_FRAME_BYTES
                or payload_length != DATA_PAYLOAD_BYTES
                or flags & ~DATA_FLAG_MASK
                or flags & FLAG_RESPONSE_ERROR
                or not run_id
                or request_id
            ):
                raise ProtocolFailure("invalid data-frame header")
            expected_items = (
                ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
            )
            if item_count != expected_items:
                raise ProtocolFailure("data-frame item count is invalid")
        else:
            if flags not in {0, FLAG_RESPONSE_ERROR}:
                raise ProtocolFailure("invalid response flags")
            if not request_id or sequence or first_ticks or item_count:
                raise ProtocolFailure("invalid response-only header fields")
            if kind == ERROR_RESPONSE:
                expected_payload = SUCCESS_PAYLOAD_SIZE[kind]
                if flags != FLAG_RESPONSE_ERROR:
                    raise ProtocolFailure("ERROR_RESPONSE lacks error flag")
            else:
                expected_payload = (
                    4 if flags == FLAG_RESPONSE_ERROR else SUCCESS_PAYLOAD_SIZE[kind]
                )
            if payload_length != expected_payload:
                raise ProtocolFailure("response payload size does not match kind")
            if total_length > MAX_CONTROL_FRAME_BYTES:
                raise ProtocolFailure("response exceeds control-frame bound")
        return total_length

    @staticmethod
    def _validate_payload(frame: Frame) -> None:
        if frame.kind in DATA_KINDS:
            if frame.kind == ADC_DATA and max(frame.payload[1::2]) > 0x0F:
                raise ProtocolFailure("ADC frame contains a code above 12 bits")
            return
        status, reserved, error = RESPONSE_PREFIX.unpack_from(frame.payload)
        is_error = frame.flags == FLAG_RESPONSE_ERROR
        if reserved or is_error != (status == 1) or (error == 0) == is_error:
            raise ProtocolFailure("response prefix disagrees with response flags")
        if error > 12:
            raise ProtocolFailure("response reports an unknown error code")

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
    """One-request-at-a-time link that drains data while awaiting responses."""

    def __init__(self, port: SerialPort) -> None:
        self.port = port
        self.parser = FrameParser()
        self.next_request_id = 1
        self.maximum_read_bytes = 0
        self.stale_responses = 0
        self.discarded_data_frames = 0

    def drain_startup(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        frames = 0
        while time.monotonic() < deadline:
            chunk = bytes(self.port.read(SERIAL_READ_BYTES))
            if chunk:
                decoded = self.parser.feed(chunk)
                frames += len(decoded)
        emit_event(
            "startup_drain",
            discarded_bytes=self.parser.bytes_discarded,
            discarded_frames=frames,
        )

    def exchange(
        self,
        request_kind: int,
        payload: bytes = b"",
        *,
        timeout: float = COMMAND_DEADLINE_SECONDS,
        on_data: Callable[[Frame], None] | None = None,
    ) -> tuple[Frame, float]:
        request_id = self._allocate_request_id()
        started = time.monotonic()
        deadline = started + timeout
        self._write_all(encode_request(request_kind, request_id, payload), deadline)
        expected_kind = REQUEST_RESPONSE_KIND[request_kind]
        while True:
            if time.monotonic() >= deadline:
                raise DeadlineExpired(
                    f"request {request_id} kind 0x{request_kind:02x} timed out"
                )
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
                if frame.kind != expected_kind:
                    raise ProtocolFailure(
                        f"request {request_id} expected 0x{expected_kind:02x}, "
                        f"received 0x{frame.kind:02x}"
                    )
                if matched is not None:
                    raise ProtocolFailure(f"request {request_id} got two responses")
                matched = frame
            if matched is not None:
                return matched, time.monotonic() - started

    def pump_once(self, on_data: Callable[[Frame], None]) -> int:
        chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        frames = self.parser.feed(chunk) if chunk else []
        for frame in frames:
            if frame.kind not in DATA_KINDS:
                raise ProtocolFailure(
                    f"unsolicited response 0x{frame.kind:02x} request={frame.request_id}"
                )
            on_data(frame)
        return len(chunk)

    def drain_until_quiet(self, on_data: Callable[[Frame], None]) -> None:
        deadline = time.monotonic() + STOP_DRAIN_DEADLINE_SECONDS
        quiet_since = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise DeadlineExpired("post-STOP stream did not become quiet")
            if now - quiet_since >= STOP_DRAIN_QUIET_SECONDS:
                if self.parser.buffered_bytes:
                    raise ProtocolFailure(
                        f"post-STOP parser retains {self.parser.buffered_bytes} bytes"
                    )
                return
            if self.pump_once(on_data):
                quiet_since = time.monotonic()

    def _read_once(self) -> list[Frame]:
        chunk = bytes(self.port.read(SERIAL_READ_BYTES))
        self.maximum_read_bytes = max(self.maximum_read_bytes, len(chunk))
        return self.parser.feed(chunk) if chunk else []

    def _allocate_request_id(self) -> int:
        result = self.next_request_id
        self.next_request_id = (self.next_request_id + 1) & UINT32_MAX
        if self.next_request_id == 0:
            self.next_request_id = 1
        return result

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
        "hardware_serial": struct.unpack_from("<I", payload, 54)[0],
        "firmware_version": tuple(payload[58:61]),
        "board_id": struct.unpack_from("<H", payload, 62)[0],
        "mcu_id": struct.unpack_from("<H", payload, 64)[0],
        "build_id": build_id,
        "applied_stream_mask": payload[324],
        "applied_source": payload[325],
        "supported_configuration_mask": struct.unpack_from("<H", payload, 326)[0],
        "data_payload_bytes": struct.unpack_from("<H", payload, 328)[0],
        "adc_pairs_per_frame": struct.unpack_from("<H", payload, 330)[0],
        "gpio_samples_per_frame": struct.unpack_from("<H", payload, 332)[0],
        "frame_coverage_ticks": struct.unpack_from("<I", payload, 336)[0],
        "packet_buffer_count": struct.unpack_from("<H", payload, 356)[0],
        "nominal_framed_bytes_per_second_per_stream": struct.unpack_from(
            "<I", payload, 372
        )[0],
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


def synchronize(link: SerialLink) -> dict[str, object]:
    first: tuple[object, ...] | None = None
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, _latency = link.exchange(
                INFO_REQUEST,
                timeout=SYNC_DEADLINE_SECONDS,
            )
            info = decode_info(frame)
            identity = stable_identity(info)
            if first is None:
                first = identity
                emit_event("sync_probe", attempt=attempt, role="throwaway")
            elif identity == first:
                emit_event("sync_probe", attempt=attempt, role="confirmed")
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


STATUS_FIELDS: dict[str, tuple[str, int]] = {
    "device_state": ("B", 4),
    "stream_mask": ("B", 5),
    "source": ("B", 6),
    "checksum": ("B", 7),
    "adc_frames_emitted": ("Q", 12),
    "gpio_frames_emitted": ("Q", 20),
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
    "adc_stop_pairs_discarded": ("Q", 472),
    "adc_incomplete_conversions": ("Q", 480),
    "adc_overwritten_conversions": ("Q", 488),
    "adc_raw_ring_overruns": ("Q", 496),
    "adc_incomplete_buffers": ("Q", 504),
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
    "adc_payload_bytes_dropped": ("Q", 736),
    "gpio_payload_bytes_dropped": ("Q", 800),
    "adc_packet_ready_depth": ("H", 832),
    "gpio_packet_ready_depth": ("H", 834),
    "adc_packet_transmit_depth": ("H", 836),
    "gpio_packet_transmit_depth": ("H", 838),
    "packet_pool_exhaustions": ("I", 892),
    "packet_invalid_operations": ("I", 896),
    "packet_encoding_rejections": ("I", 900),
    "packet_ready_queue_rejections": ("I", 904),
    "packet_transmit_queue_rejections": ("I", 908),
    "commands_rejected": ("I", 916),
    "bad_checksums": ("I", 920),
    "bad_lengths": ("I", 924),
    "bad_types": ("I", 928),
    "bad_versions": ("I", 932),
    "timeouts": ("I", 936),
    "state_errors": ("I", 944),
    "usb_tx_stall_events": ("I", 956),
    "usb_io_errors": ("I", 960),
    "bad_flags": ("I", 996),
    "bad_payloads": ("I", 1000),
    "bad_request_ids": ("I", 1004),
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


@dataclass(frozen=True)
class GapRecord:
    first_missing_index: int
    last_missing_index: int
    successor_sequence: int
    missing_frames: int


@dataclass
class StreamTracker:
    """Independent continuity and payload validator for one physical source."""

    label: str
    kind: int
    items_per_frame: int
    run_id: int
    last_sequence: int | None = None
    last_ticks: int | None = None
    logical_index: int = -1
    frames_received: int = 0
    gap_flag_frames: int = 0
    gaps: list[GapRecord] | None = None

    def __post_init__(self) -> None:
        self.gaps = []

    @property
    def coverage_frames(self) -> int:
        return self.logical_index + 1

    @property
    def missing_frames(self) -> int:
        assert self.gaps is not None
        return sum(gap.missing_frames for gap in self.gaps)

    def missing_before(self, generated_frames: int) -> int:
        assert self.gaps is not None
        total = 0
        for gap in self.gaps:
            upper = min(gap.last_missing_index + 1, generated_frames)
            lower = min(max(gap.first_missing_index, 0), generated_frames)
            total += max(0, upper - lower)
        return total

    def accept(self, frame: Frame) -> None:
        if frame.kind != self.kind:
            raise ProtocolFailure(
                f"{self.label} tracker received kind 0x{frame.kind:02x}"
            )
        if frame.run_id != self.run_id:
            raise ProtocolFailure(
                f"{self.label} run {frame.run_id}; expected {self.run_id}"
            )
        if frame.checksum_algorithm != CHECKSUM_ADLER32:
            raise ProtocolFailure(f"{self.label} checksum selection changed")
        if (
            len(frame.payload) != DATA_PAYLOAD_BYTES
            or frame.item_count != self.items_per_frame
        ):
            raise ProtocolFailure(f"{self.label} payload shape changed")
        if frame.flags & FLAG_SYNTHETIC:
            raise ProtocolFailure(f"{self.label} physical frame is marked synthetic")

        if self.last_sequence is None:
            if frame.sequence > 0x7FFFFFFF:
                raise ProtocolFailure(
                    f"{self.label} first sequence is implausibly reordered"
                )
            delta = frame.sequence + 1
            new_index = frame.sequence
            missing = frame.sequence
            expected_ticks = (frame.sequence * FRAME_COVERAGE_TICKS) & UINT64_MAX
        else:
            delta = (frame.sequence - self.last_sequence) & UINT32_MAX
            if delta == 0:
                raise ProtocolFailure(
                    f"{self.label} duplicate sequence {frame.sequence}"
                )
            if delta > 0x7FFFFFFF:
                raise ProtocolFailure(
                    f"{self.label} reordered sequence {frame.sequence}"
                )
            new_index = self.logical_index + delta
            missing = delta - 1
            assert self.last_ticks is not None
            expected_ticks = (
                self.last_ticks + delta * FRAME_COVERAGE_TICKS
            ) & UINT64_MAX
        if frame.first_sample_ticks != expected_ticks:
            timestamp_delta = (
                frame.first_sample_ticks - (self.last_ticks or 0)
            ) & UINT64_MAX
            raise ProtocolFailure(
                f"{self.label} timestamp {frame.first_sample_ticks} does not imply "
                f"sequence delta {delta}; raw_delta={timestamp_delta}"
            )

        expected_flags = 0
        if new_index == 0:
            expected_flags |= FLAG_EPOCH_START
        if missing:
            expected_flags |= FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE
        if frame.flags != expected_flags:
            raise ProtocolFailure(
                f"{self.label} sequence {frame.sequence} flags 0x{frame.flags:04x}; "
                f"expected 0x{expected_flags:04x}"
            )
        if missing:
            assert self.gaps is not None
            self.gaps.append(
                GapRecord(
                    first_missing_index=new_index - missing,
                    last_missing_index=new_index - 1,
                    successor_sequence=frame.sequence,
                    missing_frames=missing,
                )
            )
            self.gap_flag_frames += 1
            emit_event(
                "expected_negative_gap",
                source=self.label,
                first_missing_index=new_index - missing,
                last_missing_index=new_index - 1,
                missing_frames=missing,
                successor_sequence=frame.sequence,
            )
        self.last_sequence = frame.sequence
        self.last_ticks = frame.first_sample_ticks
        self.logical_index = new_index
        self.frames_received += 1


class CombinedTracker:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.adc = StreamTracker("ADC", ADC_DATA, ADC_PAIRS_PER_FRAME, run_id)
        self.gpio = StreamTracker("GPIO", GPIO_DATA, GPIO_SAMPLES_PER_FRAME, run_id)

    def accept(self, frame: Frame) -> None:
        if frame.kind == ADC_DATA:
            self.adc.accept(frame)
        elif frame.kind == GPIO_DATA:
            self.gpio.accept(frame)
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


def _status_loss_signature(status: StatusSnapshot) -> tuple[int, ...]:
    return (
        status.adc_frames_dropped,
        status.gpio_frames_dropped,
        status.adc_items_dropped,
        status.gpio_items_dropped,
        status.adc_payload_bytes_dropped,
        status.gpio_payload_bytes_dropped,
    )


def _collect_until(
    link: SerialLink,
    tracker: CombinedTracker,
    predicate: Callable[[], bool],
    deadline: float,
    label: str,
) -> None:
    while not predicate():
        if time.monotonic() >= deadline:
            raise DeadlineExpired(f"{label} did not complete before its deadline")
        link.pump_once(tracker.accept)


def _collect_past_snapshot(
    link: SerialLink,
    tracker: CombinedTracker,
    status: StatusSnapshot,
    deadline: float,
) -> None:
    adc_target = status.adc_frames_generated + POST_SNAPSHOT_FRAMES_PER_SOURCE
    gpio_target = status.gpio_frames_generated + POST_SNAPSHOT_FRAMES_PER_SOURCE
    _collect_until(
        link,
        tracker,
        lambda: (
            tracker.adc.coverage_frames >= adc_target
            and tracker.gpio.coverage_frames >= gpio_target
        ),
        deadline,
        "catch-up to live data",
    )
    emit_event(
        "live_catch_up",
        adc_coverage=tracker.adc.coverage_frames,
        adc_target=adc_target,
        gpio_coverage=tracker.gpio.coverage_frames,
        gpio_target=gpio_target,
    )


UNEXPECTED_STATUS_FIELDS = (
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
    "packet_invalid_operations",
    "packet_encoding_rejections",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
    "commands_rejected",
    "bad_checksums",
    "bad_lengths",
    "bad_types",
    "bad_versions",
    "bad_flags",
    "bad_payloads",
    "bad_request_ids",
    "timeouts",
    "state_errors",
    "usb_io_errors",
    "response_queue_rejections",
    "response_reservations_abandoned",
)


def _reconcile_pressure(
    evidence: Evidence,
    tracker: CombinedTracker,
    baseline: StatusSnapshot,
    recovered: StatusSnapshot,
) -> None:
    evidence.equal("recovery state", STATE_RUNNING, recovered.device_state)
    evidence.equal("recovery stream mask", STREAM_BOTH, recovered.stream_mask)
    evidence.equal("recovery source", SOURCE_HARDWARE, recovered.source)
    evidence.equal("recovery checksum", CHECKSUM_ADLER32, recovered.checksum)
    evidence.equal(
        "statistics generation preserved",
        baseline.stats_generation,
        recovered.stats_generation,
    )

    baseline_loss = {
        name: baseline.values[name]
        for name in (
            "adc_frames_dropped",
            "gpio_frames_dropped",
            "adc_items_dropped",
            "gpio_items_dropped",
        )
    }
    evidence.equal(
        "baseline loss counters", {name: 0 for name in baseline_loss}, baseline_loss
    )

    for prefix, stream, items_per_frame, item_bytes in (
        ("adc", tracker.adc, ADC_PAIRS_PER_FRAME, ADC_BYTES_PER_PAIR),
        ("gpio", tracker.gpio, GPIO_SAMPLES_PER_FRAME, 1),
    ):
        dropped_frames = recovered.values[f"{prefix}_frames_dropped"]
        inferred = stream.missing_before(recovered.values[f"{prefix}_frames_generated"])
        evidence.check(
            f"expected_negative_loss.{prefix}.present",
            "> 0 complete frames",
            dropped_frames,
            dropped_frames > 0,
        )
        evidence.equal(
            f"expected_negative_loss.{prefix}.sequence_missing_frames",
            dropped_frames,
            inferred,
        )
        evidence.equal(
            f"expected_negative_loss.{prefix}.items",
            dropped_frames * items_per_frame,
            recovered.values[f"{prefix}_items_dropped"],
        )
        evidence.equal(
            f"expected_negative_loss.{prefix}.payload_bytes",
            dropped_frames * items_per_frame * item_bytes,
            recovered.values[f"{prefix}_payload_bytes_dropped"],
        )
        evidence.equal(
            f"expected_negative_loss.{prefix}.evicted_frames",
            dropped_frames,
            recovered.values[f"{prefix}_frames_evicted"],
        )
        evidence.equal(
            f"expected_negative_loss.{prefix}.flagged_successors",
            len(stream.gaps or []),
            stream.gap_flag_frames,
        )

        produced = recovered.values[f"{prefix}_frames_generated"]
        framed = recovered.values[f"{prefix}_frames_framed_pipeline"]
        emitted = recovered.values[f"{prefix}_frames_emitted"]
        transmitted = recovered.values[f"{prefix}_frames_transmitted"]
        filling = recovered.values[f"{prefix}_packet_filling_depth"]
        ready = recovered.values[f"{prefix}_packet_ready_depth"]
        transmitting = recovered.values[f"{prefix}_packet_transmit_depth"]
        after_framing = recovered.values[f"{prefix}_frames_dropped_after_framing"]
        after_promotion = recovered.values[f"{prefix}_frames_dropped_after_promotion"]
        evidence.equal(
            f"conservation.{prefix}.produced",
            transmitted + dropped_frames + filling + ready + transmitting,
            produced,
        )
        evidence.equal(
            f"conservation.{prefix}.framed",
            transmitted + ready + transmitting + after_framing,
            framed,
        )
        evidence.equal(
            f"conservation.{prefix}.emitted",
            transmitted + transmitting + after_promotion,
            emitted,
        )

    total_dropped = recovered.adc_frames_dropped + recovered.gpio_frames_dropped
    evidence.equal(
        "expected_negative_loss.pressure_evictions",
        total_dropped,
        recovered.packet_pressure_evictions,
    )
    evidence.equal(
        "expected_negative_loss.no_unowned_capacity_drop",
        0,
        recovered.packet_capacity_drops_without_evictable_frame,
    )
    unexpected = {
        name: recovered.values[name]
        for name in UNEXPECTED_STATUS_FIELDS
        if recovered.values[name]
    }
    evidence.equal("unexpected_firmware_or_hardware_errors", {}, unexpected)
    emit_event(
        "expected_negative_loss",
        adc_frames=recovered.adc_frames_dropped,
        adc_items=recovered.adc_items_dropped,
        adc_payload_bytes=recovered.adc_payload_bytes_dropped,
        gpio_frames=recovered.gpio_frames_dropped,
        gpio_items=recovered.gpio_items_dropped,
        gpio_payload_bytes=recovered.gpio_payload_bytes_dropped,
        packet_pool_exhaustions=recovered.packet_pool_exhaustions,
        pressure_evictions=recovered.packet_pressure_evictions,
        usb_tx_stall_events=recovered.usb_tx_stall_events,
    )
    emit_event("unexpected_error_snapshot", counters=unexpected)


def _grade_info(
    evidence: Evidence,
    info: dict[str, object],
    *,
    expected_build_id: str | None,
    expected_hardware_serial: int | None,
) -> None:
    source_mask = _info_integer(info, "supported_source_mask")
    profile_mask = _info_integer(info, "supported_configuration_mask")
    checksum_mask = _info_integer(info, "supported_checksum_mask")
    evidence.equal("INFO protocol version", PROTOCOL_VERSION, info["protocol_version"])
    evidence.equal("INFO combined streams", STREAM_BOTH, info["supported_stream_mask"])
    evidence.check(
        "INFO hardware source",
        "hardware bit set",
        source_mask,
        bool(source_mask & (1 << SOURCE_HARDWARE)),
    )
    evidence.check(
        "INFO hardware-combined profile",
        "profile bit set",
        profile_mask,
        bool(profile_mask & PROFILE_HARDWARE_COMBINED),
    )
    evidence.check(
        "INFO Adler-32 support",
        "checksum bit set",
        checksum_mask,
        bool(checksum_mask & (1 << CHECKSUM_ADLER32)),
    )
    evidence.equal("INFO payload bytes", DATA_PAYLOAD_BYTES, info["data_payload_bytes"])
    evidence.equal(
        "INFO ADC pairs/frame", ADC_PAIRS_PER_FRAME, info["adc_pairs_per_frame"]
    )
    evidence.equal(
        "INFO GPIO samples/frame",
        GPIO_SAMPLES_PER_FRAME,
        info["gpio_samples_per_frame"],
    )
    evidence.equal(
        "INFO frame coverage ticks", FRAME_COVERAGE_TICKS, info["frame_coverage_ticks"]
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


def run_acceptance(
    port: SerialPort,
    *,
    stall_seconds: float,
    recovery_deadline_seconds: float,
    baseline_frames_per_source: int,
    expected_build_id: str | None = None,
    expected_hardware_serial: int | None = None,
) -> Evidence:
    """Run one finite physical pressure/recovery campaign."""

    evidence = Evidence()
    link = SerialLink(port)
    tracker: CombinedTracker | None = None
    completed = False
    try:
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        synchronized = synchronize(link)
        _grade_info(
            evidence,
            synchronized,
            expected_build_id=expected_build_id,
            expected_hardware_serial=expected_hardware_serial,
        )
        combined_framed_rate = 2 * _info_integer(
            synchronized, "nominal_framed_bytes_per_second_per_stream"
        )
        advertised_packet_buffer_seconds = (
            _info_integer(synchronized, "packet_buffer_count")
            * DATA_FRAME_BYTES
            / combined_framed_rate
        )
        evidence.check(
            "intentional stall exceeds advertised packet buffering",
            f"> {advertised_packet_buffer_seconds:.6f}s",
            f"{stall_seconds:.6f}s",
            stall_seconds > advertised_packet_buffer_seconds,
        )
        if stall_seconds <= advertised_packet_buffer_seconds:
            raise ProtocolFailure(
                "STALL_SECONDS does not exceed the advertised combined packet-pool "
                "buffer duration"
            )

        stop_frame, stop_latency = link.exchange(STOP_REQUEST)
        response_success(stop_frame, STOP_RESPONSE)
        evidence.equal("initial STOP transition", STATE_IDLE, stop_frame.payload[4])
        evidence.check(
            "initial STOP deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{stop_latency:.6f}s",
            stop_latency <= COMMAND_DEADLINE_SECONDS,
        )
        link.drain_until_quiet(lambda _frame: None)

        reset_frame, _reset_latency = link.exchange(RESET_STATS_REQUEST)
        response_success(reset_frame, RESET_STATS_RESPONSE)
        reset_generation = struct.unpack_from("<I", reset_frame.payload, 4)[0]
        evidence.check(
            "RESET_STATS generation",
            "nonzero uint32",
            reset_generation,
            reset_generation > 0,
        )

        requested = CONFIGURATION.pack(
            STREAM_BOTH,
            SOURCE_HARDWARE,
            CHECKSUM_ADLER32,
            0,
            DATA_FRAME_BYTES,
        )
        configure_frame, _configure_latency = link.exchange(
            CONFIGURE_REQUEST, requested
        )
        applied = (STREAM_BOTH, SOURCE_HARDWARE, CHECKSUM_ADLER32, DATA_FRAME_BYTES)
        evidence.equal(
            "CONFIGURE transition",
            applied,
            decode_configuration(configure_frame, CONFIGURE_RESPONSE),
        )

        deferred: list[Frame] = []
        start_frame, start_latency = link.exchange(
            START_REQUEST,
            on_data=deferred.append,
        )
        evidence.equal(
            "START transition",
            applied,
            decode_configuration(start_frame, START_RESPONSE),
        )
        evidence.check(
            "START run ID", "nonzero uint32", start_frame.run_id, start_frame.run_id > 0
        )
        evidence.check(
            "START deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{start_latency:.6f}s",
            start_latency <= COMMAND_DEADLINE_SECONDS,
        )
        tracker = CombinedTracker(start_frame.run_id)
        for frame in deferred:
            tracker.accept(frame)
        parser_errors_at_start = link.parser.errors

        baseline_deadline = time.monotonic() + recovery_deadline_seconds
        _collect_until(
            link,
            tracker,
            lambda: (
                tracker.adc.frames_received >= baseline_frames_per_source
                and tracker.gpio.frames_received >= baseline_frames_per_source
            ),
            baseline_deadline,
            "baseline acquisition",
        )
        baseline_frame, baseline_latency = link.exchange(
            GET_STATUS_REQUEST,
            on_data=tracker.accept,
        )
        baseline = decode_status(baseline_frame)
        evidence.equal("baseline state", STATE_RUNNING, baseline.device_state)
        expected_generation = (reset_generation + 1) & UINT32_MAX
        expected_generation = expected_generation or 1
        evidence.equal(
            "baseline generation", expected_generation, baseline.stats_generation
        )
        evidence.check(
            "baseline STATUS deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{baseline_latency:.6f}s",
            baseline_latency <= COMMAND_DEADLINE_SECONDS,
        )
        emit_event(
            "baseline",
            adc_frames=tracker.adc.frames_received,
            adc_generated=baseline.adc_frames_generated,
            gpio_frames=tracker.gpio.frames_received,
            gpio_generated=baseline.gpio_frames_generated,
            loss_signature=_status_loss_signature(baseline),
            stats_generation=baseline.stats_generation,
        )

        emit_event(
            "intentional_read_stall_begin",
            expected="no host serial reads",
            seconds=stall_seconds,
        )
        stall_started = time.monotonic()
        time.sleep(stall_seconds)
        stall_elapsed = time.monotonic() - stall_started
        emit_event(
            "intentional_read_stall_end",
            actual_seconds=stall_elapsed,
            expected_seconds=stall_seconds,
        )
        evidence.check(
            "intentional no-read interval",
            f">= {stall_seconds:.6f}s",
            f"{stall_elapsed:.6f}s",
            stall_elapsed >= stall_seconds,
        )

        recovery_deadline = time.monotonic() + recovery_deadline_seconds
        resumed_frame, resumed_latency = link.exchange(
            GET_STATUS_REQUEST,
            timeout=min(COMMAND_DEADLINE_SECONDS, recovery_deadline_seconds),
            on_data=tracker.accept,
        )
        status = decode_status(resumed_frame)
        evidence.check(
            "resumed STATUS deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{resumed_latency:.6f}s",
            resumed_latency <= COMMAND_DEADLINE_SECONDS,
        )
        stable = False
        for attempt in range(1, MAX_STABILIZATION_SNAPSHOTS + 1):
            _collect_past_snapshot(link, tracker, status, recovery_deadline)
            next_frame, latency = link.exchange(
                GET_STATUS_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.001, recovery_deadline - time.monotonic()),
                ),
                on_data=tracker.accept,
            )
            next_status = decode_status(next_frame)
            emit_event(
                "loss_stability_probe",
                attempt=attempt,
                current=_status_loss_signature(status),
                latency_seconds=latency,
                next=_status_loss_signature(next_status),
            )
            if _status_loss_signature(next_status) == _status_loss_signature(status):
                status = next_status
                _collect_past_snapshot(link, tracker, status, recovery_deadline)
                stable = True
                break
            status = next_status
        evidence.equal("loss counters stabilize while draining", True, stable)
        if not stable:
            raise ProtocolFailure("loss counters did not stabilize during recovery")

        _reconcile_pressure(evidence, tracker, baseline, status)
        evidence.equal(
            "unexpected host parser errors",
            parser_errors_at_start,
            link.parser.errors,
        )
        evidence.equal("unexpected stale responses", 0, link.stale_responses)
        evidence.check(
            "live ADC after recovery snapshot",
            f">= {status.adc_frames_generated + POST_SNAPSHOT_FRAMES_PER_SOURCE}",
            tracker.adc.coverage_frames,
            tracker.adc.coverage_frames
            >= status.adc_frames_generated + POST_SNAPSHOT_FRAMES_PER_SOURCE,
        )
        evidence.check(
            "live GPIO after recovery snapshot",
            f">= {status.gpio_frames_generated + POST_SNAPSHOT_FRAMES_PER_SOURCE}",
            tracker.gpio.coverage_frames,
            tracker.gpio.coverage_frames
            >= status.gpio_frames_generated + POST_SNAPSHOT_FRAMES_PER_SOURCE,
        )

        stop_frame, stop_latency = link.exchange(
            STOP_REQUEST,
            on_data=tracker.accept,
        )
        response_success(stop_frame, STOP_RESPONSE)
        evidence.equal("final STOP transition", STATE_IDLE, stop_frame.payload[4])
        evidence.equal("final STOP run ID", tracker.run_id, stop_frame.run_id)
        evidence.check(
            "final STOP deadline",
            f"<= {COMMAND_DEADLINE_SECONDS:.3f}s",
            f"{stop_latency:.6f}s",
            stop_latency <= COMMAND_DEADLINE_SECONDS,
        )
        link.drain_until_quiet(tracker.accept)
        final_frame, _final_latency = link.exchange(GET_STATUS_REQUEST)
        final_status = decode_status(final_frame)
        evidence.equal("final STATUS transition", STATE_IDLE, final_status.device_state)
        evidence.equal("final STATUS stream mask", 0, final_status.stream_mask)
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
                    on_data=(tracker.accept if tracker is not None else None),
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
    return evidence


def _positive_float_environment(name: str, default: float, maximum: float) -> float:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be finite and in (0, {maximum}]")
    return value


def _positive_int_environment(name: str, default: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else int(raw, 0)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be in 1..{maximum}")
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
        stall_seconds = _positive_float_environment(
            "STALL_SECONDS", DEFAULT_STALL_SECONDS, MAX_STALL_SECONDS
        )
        recovery_deadline_seconds = _positive_float_environment(
            "RECOVERY_DEADLINE_SECONDS",
            DEFAULT_RECOVERY_DEADLINE_SECONDS,
            MAX_RECOVERY_DEADLINE_SECONDS,
        )
        baseline_frames = _positive_int_environment(
            "BASELINE_FRAMES_PER_SOURCE",
            DEFAULT_BASELINE_FRAMES_PER_SOURCE,
            10_000,
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
        baseline_frames_per_source=baseline_frames,
        port=port_name,
        protocol=PROTOCOL_VERSION,
        recovery_deadline_seconds=recovery_deadline_seconds,
        stall_seconds=stall_seconds,
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
        evidence = run_acceptance(
            port,
            stall_seconds=stall_seconds,
            recovery_deadline_seconds=recovery_deadline_seconds,
            baseline_frames_per_source=baseline_frames,
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
