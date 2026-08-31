#!/usr/bin/env python3
"""Canonical, dependency-bounded ThingDAQ endurance validator.

``firmware/tools/generate_soak_programs.py`` replaces only marked blocks and
writes three standalone rig programs plus the checked Windows handoff script.
Keep all wire, validation, deadline, cleanup, and result-schema logic in this
file so a protocol repair cannot drift between entry points or soak modes.

Every generated program intentionally imports only the standard library and
PySerial.  Remote-service programs read ``SERIAL_PORT``; the Windows handoff
uses bounded metadata-first COM discovery supplied by its generated driver.
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
      "sha256": "0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a"
    },
    "board": {
      "board_id": 1,
      "fqbn": "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
      "hardware_serial": 20512460,
      "mcu_id": 1
    },
    "firmware": {
      "build_id": "thingdaq-a0dc150fd48a6e9b",
      "source_id": "a0dc150fd48a6e9b62c614fe487d533f6c7c90bee6c7d5cd3c9f8e985e0b49ba",
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
      "hard_deadline_seconds": 3691.0,
      "info_interval_seconds": 30.0,
      "measured_duration_seconds": 3600.0,
      "service_container_limit_seconds": 3721.0,
      "status_interval_seconds": 1.0,
      "warmup_seconds": 1.0
    }
  },
  "candidate_sha256": "32dcf73bc99f5abc53935901baa4f14103df339e1aafbe71ef3330f3b79d8656",
  "entry_point": "windows-standalone",
  "generator_schema_version": 1,
  "mode": "physical-combined",
  "validation_manifest": {
    "accepted_evidence": {
      "candidate_freeze_sha256": "b285449f1a7af391d5210189f87a0c01f7d28acc7c4f608a7ba3ade70c3b77a9",
      "candidate_semantic_sha256": "32dcf73bc99f5abc53935901baa4f14103df339e1aafbe71ef3330f3b79d8656",
      "firmware_build_manifest_sha256": "6741c3fe10c44b8d7ff5666ddfd9a6eba2147c584e687e34794a1165e9af384b",
      "protocol_contract_sha256": "a5993a8afe9b8b42b951ed6ec3dbd2ca84b3271e4302f717e56ee3b9dcb69676",
      "reproducible_build_count": 2,
      "reproducible_hex_size_bytes": 357214
    },
    "acquisition": {
      "adc1_phase_nanoseconds": 500,
      "adc1_phase_ticks": 4,
      "adc_container_bits": 16,
      "adc_pair_period_ticks": 8,
      "adc_pair_rate_hz": 1000000,
      "adc_pins_by_pair_position": {
        "adc0": 14,
        "adc1": 15
      },
      "adc_resolution_bits": 12,
      "adc_trigger_ipg_clock_hz": 150000000,
      "adc_trigger_phase_ipg_cycles": 75,
      "gpio_pins_by_bit": [
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13
      ],
      "gpio_sample_period_ticks": 2,
      "gpio_sample_rate_hz": 4000000,
      "timestamp_hz": 8000000
    },
    "capabilities": {
      "bits": 511,
      "names": [
        "ADC_STREAM",
        "GPIO_STREAM",
        "HARDWARE_SOURCE",
        "SYNTHETIC_SOURCE",
        "RESET_STATS",
        "PING",
        "CHECKSUM_BENCHMARK",
        "GPIO_CLOCK_DIAGNOSTIC",
        "GPIO_CAPTURE_DIAGNOSTIC"
      ],
      "supported_checksum_mask": 14,
      "supported_configuration_mask": 63,
      "supported_source_mask": 3,
      "supported_stream_mask": 3
    },
    "expected_info": {
      "adc1_phase_ticks": 4,
      "adc_container_bytes": 2,
      "adc_dma_ring_depth": 8,
      "adc_pair_bytes": 4,
      "adc_pair_period_ticks": 8,
      "adc_pair_rate_hz": 1000000,
      "adc_pairs_per_frame": 1012,
      "adc_resolution_bits": 12,
      "board_id": 1,
      "build_id": "thingdaq-a0dc150fd48a6e9b",
      "capability_bits": 511,
      "command_queue_capacity": 4,
      "data_checksum_algorithm": 1,
      "data_frame_bytes": 4096,
      "data_payload_bytes": 4048,
      "firmware_version": [
        0,
        7,
        0
      ],
      "frame_coverage_ticks": 8096,
      "gpio_pin_count": 8,
      "gpio_pin_map": [
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13
      ],
      "gpio_sample_period_ticks": 2,
      "gpio_sample_rate_hz": 4000000,
      "gpio_samples_per_frame": 4048,
      "hardware_serial": 20512460,
      "max_control_frame_bytes": 1280,
      "mcu_id": 1,
      "nominal_framed_bytes_per_second_per_stream": 4047431,
      "nominal_payload_bytes_per_second_per_stream": 4000000,
      "packet_buffer_count": 200,
      "packet_ready_queue_capacity": 200,
      "packet_transmit_queue_capacity": 200,
      "protocol_version": 1,
      "response_queue_capacity": 4,
      "supported_checksum_mask": 14,
      "supported_configuration_mask": 63,
      "supported_source_mask": 3,
      "supported_stream_mask": 3,
      "timestamp_hz": 8000000
    },
    "firmware": {
      "build_id": "thingdaq-a0dc150fd48a6e9b",
      "exported_hex": {
        "name": "firmware.ino.hex",
        "sha256": "0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a",
        "size_bytes": 357214
      },
      "fqbn": "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
      "source_id": "a0dc150fd48a6e9b62c614fe487d533f6c7c90bee6c7d5cd3c9f8e985e0b49ba",
      "version": [
        0,
        7,
        0
      ]
    },
    "kind": "thingdaq-release-validation",
    "protocol": {
      "byte_order": "little",
      "checksum": {
        "algorithm": 1,
        "name": "ADLER32",
        "parameters": {
          "coverage": "all 44 header bytes followed by every payload byte, starting at magic offset 0 and excluding all 4 trailer bytes",
          "initial_value": 1,
          "modulus": 65521,
          "trailer_byte_order": "little",
          "width_bits": 32
        }
      },
      "frames": {
        "adc_pairs_per_frame": 1012,
        "data_frame_bytes": 4096,
        "frame_coverage_ticks": 8096,
        "gpio_samples_per_frame": 4048,
        "header_bytes": 44,
        "max_control_frame_bytes": 1280,
        "payload_bytes": 4048,
        "trailer_bytes": 4
      },
      "version": 1
    },
    "related": [
      "[[Phase-11-Soak-Evidence]]"
    ],
    "release_policy": {
      "hardware_serial_is_stable_identity": true,
      "identity_override_option": "--diagnostic-identity-override",
      "identity_override_results_are_release_eligible": false,
      "mutable_com_port_is_identity": false
    },
    "required_zero": {
      "final_idle_gauges": [
        "packet_ready_depth",
        "packet_transmit_depth",
        "packet_owned_depth",
        "adc_packet_filling_depth",
        "gpio_packet_filling_depth",
        "adc_packet_ready_depth",
        "gpio_packet_ready_depth",
        "adc_packet_transmit_depth",
        "gpio_packet_transmit_depth",
        "usb_command_queue_depth",
        "usb_response_queue_depth",
        "usb_lower_priority_queue_depth",
        "usb_active_frame_bytes_sent",
        "usb_active_frame_size"
      ],
      "firmware_during_stream_fields": [
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
        "gpio_frames_dropped_after_promotion"
      ],
      "firmware_final_fields": [
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
        "gpio_frames_dropped_after_promotion"
      ],
      "host_parser_fields": [
        "bytes_discarded",
        "errors",
        "buffered_bytes"
      ],
      "host_stream_fields": [
        "adc_missing_frames",
        "gpio_missing_frames",
        "adc_gap_flag_frames",
        "gpio_gap_flag_frames"
      ],
      "physical_stop_tail_bounded_fields": [
        "adc_items_dropped",
        "gpio_items_dropped",
        "gpio_raw_samples_lost",
        "adc_raw_pairs_lost",
        "adc_stop_pairs_discarded",
        "adc_incomplete_conversions",
        "adc_incomplete_buffers",
        "adc_completion_mismatches"
      ],
      "required_value": 0
    },
    "schema_version": 1
  },
  "validation_manifest_sha256": "d6da65261b17b91409da59a5a0f8f47182a26d2d2a5637ac68b4cf902413b260",
  "validator_sha256": "bde658a05069032dc6e65bf3bf86f9b040961d62870422e709ecd955b638da34",
  "windows_driver_sha256": "7fce45f23639949d215e26aa31a956399e8b4c2c65fa6303379a61868b0a5466",
  "windows_profile_sha256": "adb14bdcad996888cee26ddc08f0a7eda29d50894b11d60a08d6535ef7452412"
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
EXPECTED_NEGATIVE_STALL_SECONDS = 0.25
EXPECTED_NEGATIVE_STALL_DEADLINE_SECONDS = 1.0
SYNC_ATTEMPTS = 4
SYNC_DEADLINE_SECONDS = 0.75
COMMAND_DEADLINE_SECONDS = 0.5
STOP_DRAIN_DEADLINE_SECONDS = 3.0
STOP_DRAIN_QUIET_SECONDS = 0.10
MAX_STATUS_SAMPLES = 4_096
MAX_LATENCY_SAMPLES = 4_096
MAX_DIAGNOSTIC_SAMPLES = 8
MAX_COUNTER_SAMPLES = 12
MAX_EXPECTED_GAP_EVENTS = 8
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
ADC_RAW_RING_DEPTH = 8

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
    on_data: Callable[[Frame], None] | None = None,
    expected_run_id: int | None = None,
) -> tuple[dict[str, object], list[float]]:
    previous: dict[str, object] | None = None
    latencies: list[float] = []
    last_error = "no INFO response"
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            frame, latency = link.exchange(
                INFO_REQUEST,
                timeout=SYNC_DEADLINE_SECONDS,
                on_data=on_data,
                hard_deadline=hard_deadline,
            )
            current = decode_info(frame)
            if expected_run_id is not None:
                require(
                    frame.run_id == expected_run_id,
                    "stale_run",
                    f"reopened INFO run ID {frame.run_id} != {expected_run_id}",
                )
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
_STATUS_CACHE_U32_FIELDS = (
    "gpio_cache_dma_discards",
    "gpio_cache_cpu_invalidations",
    "adc_cache_dma_discards",
    "adc_cache_cpu_invalidations",
)
_STATUS_PARSER_DETAIL_U32_FIELDS = (
    "bad_flags",
    "bad_payloads",
    "bad_request_ids",
)
_STATUS_RESPONSE_U32_FIELDS = (
    "responses_queued",
    "responses_completed",
    "response_queue_rejections",
    "response_reservations_abandoned",
)
_STATUS_PRESSURE_U64_FIELDS = (
    "packet_pressure_evictions",
    "packet_capacity_drops_without_evictable_frame",
)
_STATUS_EVICTION_U64_FIELDS = (
    "adc_frames_evicted",
    "adc_frames_evicted_after_promotion",
    "gpio_frames_evicted",
    "gpio_frames_evicted_after_promotion",
)
_STATUS_DROP_BOUNDARY_U64_FIELDS = (
    "adc_frames_dropped_after_framing",
    "adc_frames_dropped_after_promotion",
    "gpio_frames_dropped_after_framing",
    "gpio_frames_dropped_after_promotion",
)
_STATUS_GPIO_PIPELINE_DETAIL_U64_FIELDS = (
    "gpio_buffers_completed",
    "gpio_buffers_acquired",
    "gpio_buffers_released",
    "gpio_samples_delivered",
    "gpio_stop_samples_discarded",
)
_STATUS_GPIO_PACKER_DETAIL_U64_FIELDS = (
    "gpio_frames_produced",
    "gpio_samples_produced",
    "gpio_frames_packed",
    "gpio_duplicate_samples_ignored",
)
_STATUS_ADC_PIPELINE_DETAIL_U64_FIELDS = (
    "adc_frames_consumed",
    "adc_pairs_consumed",
    "adc_raw_gap_pairs",
    "adc_raw_drop_pairs_projected",
)
_STATUS_DROP_PROJECTION_U64_FIELDS = (
    "gpio_raw_drop_samples_projected",
    "gpio_packer_drop_samples_projected",
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
        "packet_owned_depth",
        "usb_active_frame_size",
        "adc_packet_filling_depth",
        "gpio_packet_filling_depth",
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
)
_EXPECTED_PRESSURE_LOSS_FIELDS = frozenset(
    {
        "adc_items_dropped",
        "gpio_items_dropped",
        "adc_frames_dropped",
        "gpio_frames_dropped",
        "adc_payload_bytes_dropped",
        "gpio_payload_bytes_dropped",
        "packet_pool_exhaustions",
        "packet_pressure_evictions",
        "adc_frames_evicted",
        "adc_frames_evicted_after_promotion",
        "gpio_frames_evicted",
        "gpio_frames_evicted_after_promotion",
        "adc_frames_dropped_after_framing",
        "adc_frames_dropped_after_promotion",
        "gpio_frames_dropped_after_framing",
        "gpio_frames_dropped_after_promotion",
    }
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
_MANIFEST_HOST_PARSER_ZERO_FIELDS = (
    "bytes_discarded",
    "errors",
    "buffered_bytes",
)
_MANIFEST_HOST_STREAM_ZERO_FIELDS = (
    "adc_missing_frames",
    "gpio_missing_frames",
    "adc_gap_flag_frames",
    "gpio_gap_flag_frames",
)
_MANIFEST_FINAL_IDLE_ZERO_GAUGES = (
    "packet_ready_depth",
    "packet_transmit_depth",
    "packet_owned_depth",
    "adc_packet_filling_depth",
    "gpio_packet_filling_depth",
    "adc_packet_ready_depth",
    "gpio_packet_ready_depth",
    "adc_packet_transmit_depth",
    "gpio_packet_transmit_depth",
    "usb_command_queue_depth",
    "usb_response_queue_depth",
    "usb_lower_priority_queue_depth",
    "usb_active_frame_bytes_sent",
    "usb_active_frame_size",
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
    values["packet_owned_depth"] = _u16(payload, 976)
    values["usb_active_frame_size"] = _u16(payload, 978)
    values.update(_decode_run(payload, 980, "I", _STATUS_CACHE_U32_FIELDS))
    values.update(_decode_run(payload, 996, "I", _STATUS_PARSER_DETAIL_U32_FIELDS))
    values.update(_decode_run(payload, 1008, "I", _STATUS_RESPONSE_U32_FIELDS))
    values.update(_decode_run(payload, 1024, "Q", _STATUS_PRESSURE_U64_FIELDS))
    values.update(_decode_run(payload, 1040, "Q", _STATUS_EVICTION_U64_FIELDS))
    values["adc_packet_filling_depth"] = _u16(payload, 1072)
    values["gpio_packet_filling_depth"] = _u16(payload, 1074)
    values.update(_decode_run(payload, 1076, "Q", _STATUS_DROP_BOUNDARY_U64_FIELDS))
    values.update(
        _decode_run(payload, 1108, "Q", _STATUS_GPIO_PIPELINE_DETAIL_U64_FIELDS)
    )
    values.update(
        _decode_run(payload, 1148, "Q", _STATUS_GPIO_PACKER_DETAIL_U64_FIELDS)
    )
    values.update(
        _decode_run(payload, 1180, "Q", _STATUS_ADC_PIPELINE_DETAIL_U64_FIELDS)
    )
    values.update(_decode_run(payload, 1212, "Q", _STATUS_DROP_PROJECTION_U64_FIELDS))
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
    validation_manifest_sha256: str | None
    expected_info: dict[str, object]
    diagnostic_identity_override: bool


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise SoakFailure("configuration", f"{name} must be a list of strings")
    if len(value) != len(set(value)):
        raise SoakFailure("configuration", f"{name} contains duplicates")
    return list(value)


def _sha256_string(value: object, name: str) -> str:
    result = _string(value, name)
    require(
        len(result) == 64
        and result == result.lower()
        and all(character in "0123456789abcdef" for character in result),
        "configuration",
        f"{name} must be lowercase SHA-256",
    )
    return result


def _expected_info_contract(
    *,
    protocol_version: int,
    hardware_serial: int,
    firmware_version: tuple[int, int, int],
    board_id: int,
    mcu_id: int,
    build_id: str,
    checksum_algorithm: int,
) -> dict[str, object]:
    return {
        "protocol_version": protocol_version,
        "hardware_serial": hardware_serial,
        "firmware_version": list(firmware_version),
        "board_id": board_id,
        "mcu_id": mcu_id,
        "build_id": build_id,
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
        "data_checksum_algorithm": checksum_algorithm,
        "gpio_pin_map": list(GPIO_PINS_BY_BIT),
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


def _validation_manifest(
    config: Mapping[str, object],
    *,
    candidate_sha256: str,
    expected_info: Mapping[str, object],
    firmware_version: tuple[int, int, int],
    build_id: str,
    source_id: str,
    artifact_name: str,
    artifact_sha256: str,
    fqbn: str,
) -> tuple[dict[str, object] | None, str | None]:
    raw_manifest = config.get("validation_manifest")
    raw_sha256 = config.get("validation_manifest_sha256")
    if raw_manifest is None:
        require(
            raw_sha256 is None,
            "configuration",
            "validation manifest digest exists without a manifest",
        )
        return None, None
    manifest = dict(_mapping(raw_manifest, "validation_manifest"))
    manifest_sha256 = _sha256_string(raw_sha256, "validation_manifest_sha256")
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    require(
        hashlib.sha256(encoded).hexdigest() == manifest_sha256,
        "configuration",
        "embedded validation manifest SHA-256 mismatch",
    )
    require(
        manifest.get("schema_version") == 1
        and manifest.get("kind") == "thingdaq-release-validation",
        "configuration",
        "unsupported validation manifest schema/kind",
    )
    related = _string_list(manifest.get("related"), "validation_manifest.related")
    require(
        "[[Phase-11-Soak-Evidence]]" in related,
        "configuration",
        "validation manifest is not linked to Phase 11 evidence",
    )
    evidence = _mapping(
        manifest.get("accepted_evidence"),
        "validation_manifest.accepted_evidence",
    )
    require(
        evidence.get("candidate_semantic_sha256") == candidate_sha256
        and evidence.get("reproducible_build_count") == 2,
        "configuration",
        "validation manifest does not identify the accepted candidate freeze",
    )
    for name in (
        "candidate_freeze_sha256",
        "firmware_build_manifest_sha256",
        "protocol_contract_sha256",
    ):
        _sha256_string(evidence.get(name), f"validation_manifest.{name}")

    manifest_firmware = _mapping(
        manifest.get("firmware"), "validation_manifest.firmware"
    )
    exported_hex = _mapping(
        manifest_firmware.get("exported_hex"),
        "validation_manifest.firmware.exported_hex",
    )
    require(
        manifest_firmware.get("version") == list(firmware_version)
        and manifest_firmware.get("build_id") == build_id
        and manifest_firmware.get("source_id") == source_id
        and manifest_firmware.get("fqbn") == fqbn
        and exported_hex.get("name") == artifact_name
        and exported_hex.get("sha256") == artifact_sha256,
        "configuration",
        "validation manifest firmware/HEX identity disagrees with the candidate",
    )
    hex_size = exported_hex.get("size_bytes")
    if not isinstance(hex_size, int) or isinstance(hex_size, bool) or hex_size <= 0:
        raise SoakFailure("configuration", "validation manifest HEX size is invalid")
    manifest_expected = dict(
        _mapping(manifest.get("expected_info"), "validation_manifest.expected_info")
    )
    require(
        manifest_expected == dict(expected_info),
        "configuration",
        "validation manifest INFO contract disagrees with the validator",
    )

    required_zero = _mapping(
        manifest.get("required_zero"), "validation_manifest.required_zero"
    )
    require(
        required_zero.get("required_value") == 0,
        "configuration",
        "validation manifest zero policy is invalid",
    )
    zero_lists = {
        "host_parser_fields": list(_MANIFEST_HOST_PARSER_ZERO_FIELDS),
        "host_stream_fields": list(_MANIFEST_HOST_STREAM_ZERO_FIELDS),
        "firmware_during_stream_fields": list(_ZERO_ERROR_FIELDS),
        "firmware_final_fields": [
            name
            for name in _ZERO_ERROR_FIELDS
            if name not in _PHYSICAL_STOP_TAIL_FIELDS
        ],
        "final_idle_gauges": list(_MANIFEST_FINAL_IDLE_ZERO_GAUGES),
    }
    for name, expected in zero_lists.items():
        actual = _string_list(
            required_zero.get(name), f"validation_manifest.required_zero.{name}"
        )
        require(
            actual == expected,
            "configuration",
            f"validation manifest {name} disagrees with the validator",
        )
    stop_tail = _string_list(
        required_zero.get("physical_stop_tail_bounded_fields"),
        "validation_manifest.required_zero.physical_stop_tail_bounded_fields",
    )
    require(
        set(stop_tail) == set(_PHYSICAL_STOP_TAIL_FIELDS),
        "configuration",
        "validation manifest physical STOP-tail policy disagrees with the validator",
    )
    policy = _mapping(
        manifest.get("release_policy"), "validation_manifest.release_policy"
    )
    require(
        policy.get("identity_override_option") == "--diagnostic-identity-override"
        and policy.get("identity_override_results_are_release_eligible") is False
        and policy.get("hardware_serial_is_stable_identity") is True
        and policy.get("mutable_com_port_is_identity") is False,
        "configuration",
        "validation manifest release/identity policy is invalid",
    )
    return manifest, manifest_sha256


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
        build_id == f"thingdaq-{source_id[:16]}",
        "configuration",
        "build ID does not derive from the source ID",
    )
    artifact_name = _string(artifact.get("name"), "artifact.name")
    fqbn = _string(board.get("fqbn"), "board.fqbn")
    hardware_serial = _integer(
        board.get("hardware_serial"), "board.hardware_serial", minimum=1
    )
    board_id = _integer(board.get("board_id"), "board.board_id", minimum=1)
    mcu_id = _integer(board.get("mcu_id"), "board.mcu_id", minimum=1)
    candidate_sha256 = _string(config.get("candidate_sha256"), "candidate_sha256")
    expected_info = _expected_info_contract(
        protocol_version=protocol_version,
        hardware_serial=hardware_serial,
        firmware_version=version,
        board_id=board_id,
        mcu_id=mcu_id,
        build_id=build_id,
        checksum_algorithm=checksum_algorithm,
    )
    _manifest, validation_manifest_sha256 = _validation_manifest(
        config,
        candidate_sha256=candidate_sha256,
        expected_info=expected_info,
        firmware_version=version,
        build_id=build_id,
        source_id=source_id,
        artifact_name=artifact_name,
        artifact_sha256=artifact_sha256,
        fqbn=fqbn,
    )
    diagnostic_identity_override = config.get("diagnostic_identity_override", False)
    if not isinstance(diagnostic_identity_override, bool):
        raise SoakFailure(
            "configuration", "diagnostic_identity_override must be boolean"
        )
    require(
        not diagnostic_identity_override or validation_manifest_sha256 is not None,
        "configuration",
        "diagnostic identity override requires a release validation manifest",
    )
    return RuntimeSettings(
        mode=mode,
        protocol_version=protocol_version,
        checksum_algorithm=checksum_algorithm,
        checksum_name=_string(protocol.get("checksum_name"), "protocol.checksum_name"),
        firmware_version=version,
        build_id=build_id,
        source_id=source_id,
        artifact_name=artifact_name,
        artifact_sha256=artifact_sha256,
        fqbn=fqbn,
        hardware_serial=hardware_serial,
        board_id=board_id,
        mcu_id=mcu_id,
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
        candidate_sha256=candidate_sha256,
        validator_sha256=_string(config.get("validator_sha256"), "validator_sha256"),
        validation_manifest_sha256=validation_manifest_sha256,
        expected_info=expected_info,
        diagnostic_identity_override=diagnostic_identity_override,
    )


def _identity_json_value(value: object) -> object:
    return list(value) if isinstance(value, tuple) else value


def info_identity_mismatches(
    info: Mapping[str, object],
    settings: RuntimeSettings,
) -> dict[str, dict[str, object]]:
    expected_info = (
        settings.expected_info
        if settings.validation_manifest_sha256 is not None
        else _expected_info_contract(
            protocol_version=settings.protocol_version,
            hardware_serial=settings.hardware_serial,
            firmware_version=settings.firmware_version,
            board_id=settings.board_id,
            mcu_id=settings.mcu_id,
            build_id=settings.build_id,
            checksum_algorithm=settings.checksum_algorithm,
        )
    )
    return {
        name: {
            "expected": expected,
            "actual": _identity_json_value(info.get(name)),
        }
        for name, expected in expected_info.items()
        if _identity_json_value(info.get(name)) != expected
    }


def validate_info_identity(
    info: Mapping[str, object],
    settings: RuntimeSettings,
    *,
    expected_state: int | None = None,
    expected_source: int | None = None,
) -> None:
    mismatches = info_identity_mismatches(info, settings)
    require(
        not mismatches or settings.diagnostic_identity_override,
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
    missing_frames: int = 0
    gap_flag_frames: int = 0
    items: int = 0
    payload_bytes: int = 0
    framed_bytes: int = 0

    def snapshot(self) -> tuple[int, int, int, int]:
        return self.frames, self.items, self.payload_bytes, self.framed_bytes

    @property
    def logical_frames(self) -> int:
        return self.frames + self.missing_frames


class StreamValidator:
    """Rolling formula/continuity validator shared by every soak mode."""

    def __init__(
        self,
        run_id: int,
        source: int,
        checksum_algorithm: int,
        clock: Clock,
        *,
        allow_expected_gaps: bool = False,
    ) -> None:
        require(1 <= run_id <= 0xFFFFFFFF, "control", "START returned run ID zero")
        require(source in {SOURCE_HARDWARE, SOURCE_SYNTHETIC}, "control", "source")
        self.run_id = run_id
        self.source = source
        self.checksum_algorithm = checksum_algorithm
        self.clock = clock
        self.allow_expected_gaps = allow_expected_gaps
        self.adc = StreamTotals()
        self.gpio = StreamTotals()
        self.expected_gaps = BoundedSamples(MAX_EXPECTED_GAP_EVENTS)
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
        totals = self.adc if frame.kind == ADC_DATA else self.gpio
        missing = (frame.sequence - totals.expected_sequence) & 0xFFFFFFFF
        require(
            missing <= 0x7FFFFFFF,
            "source_gap",
            f"kind 0x{frame.kind:02x} reordered sequence {frame.sequence}",
        )
        require(
            self.allow_expected_gaps or missing == 0,
            "source_gap",
            f"kind 0x{frame.kind:02x} sequence {frame.sequence} "
            f"!= {totals.expected_sequence}",
        )
        expected_flags = FLAG_SYNTHETIC if expected_synthetic else 0
        if frame.sequence == 0 and frame.first_sample_ticks == 0:
            expected_flags |= FLAG_EPOCH_START
        if missing:
            expected_flags |= FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE
        require(
            frame.flags == expected_flags,
            "source_gap",
            f"frame flags 0x{frame.flags:04x} != 0x{expected_flags:04x}",
        )
        expected_ticks = (
            totals.expected_ticks + missing * FRAME_COVERAGE_TICKS
        ) & 0xFFFFFFFFFFFFFFFF
        require(
            frame.first_sample_ticks == expected_ticks,
            "timestamp",
            f"kind 0x{frame.kind:02x} timestamp {frame.first_sample_ticks} "
            f"!= {expected_ticks}",
        )
        if frame.kind == ADC_DATA:
            self._validate_adc(frame)
        else:
            self._validate_gpio(frame)
        totals.frames += 1
        if missing:
            totals.missing_frames += missing
            totals.gap_flag_frames += 1
            self.expected_gaps.add(
                {
                    "kind": "adc" if frame.kind == ADC_DATA else "gpio",
                    "first_missing_sequence": (frame.sequence - missing) & 0xFFFFFFFF,
                    "last_missing_sequence": (frame.sequence - 1) & 0xFFFFFFFF,
                    "missing_frames": missing,
                    "successor_sequence": frame.sequence,
                    "successor_ticks": frame.first_sample_ticks,
                    "flags": frame.flags,
                }
            )
            emit_event(
                "expected_negative_gap",
                source="adc" if frame.kind == ADC_DATA else "gpio",
                missing_frames=missing,
                successor_sequence=frame.sequence,
                successor_ticks=frame.first_sample_ticks,
            )
        totals.items += frame.item_count
        totals.payload_bytes += len(frame.payload)
        totals.framed_bytes += DATA_FRAME_BYTES
        totals.expected_sequence = (frame.sequence + 1) & 0xFFFFFFFF
        totals.expected_ticks = (
            frame.first_sample_ticks + FRAME_COVERAGE_TICKS
        ) & 0xFFFFFFFFFFFFFFFF
        skew = abs(self.adc.logical_frames - self.gpio.logical_frames)
        self.maximum_frame_skew = max(self.maximum_frame_skew, skew)
        gap_successors_are_paired = (
            self.adc.gap_flag_frames == self.gpio.gap_flag_frames
        )
        if not self.allow_expected_gaps or gap_successors_are_paired:
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
    "packet_owned_depth",
    "packet_owned_high_water",
    "adc_packet_filling_depth",
    "gpio_packet_filling_depth",
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
    "usb_lower_priority_queue_depth",
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
    allow_expected_pressure_loss: bool = False,
) -> dict[str, int]:
    return {
        name: status.values[name]
        for name in _ZERO_ERROR_FIELDS
        if status.values[name]
        and (not allow_physical_stop_tail or name not in _PHYSICAL_STOP_TAIL_FIELDS)
        and (
            not allow_expected_pressure_loss
            or name not in _EXPECTED_PRESSURE_LOSS_FIELDS
        )
    }


def validate_status_invariants(
    status: StatusSnapshot,
    *,
    source: int,
    allow_physical_stop_tail: bool = False,
    allow_expected_pressure_loss: bool = False,
) -> None:
    errors = _nonzero_errors(
        status,
        allow_physical_stop_tail=allow_physical_stop_tail,
        allow_expected_pressure_loss=allow_expected_pressure_loss,
    )
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
            and 0 <= status.adc_incomplete_buffers <= 2
            and 0 <= status.adc_completion_mismatches <= status.adc_incomplete_buffers
            and 0 <= status.adc_incomplete_conversions <= adc_tail
            and (adc_tail == 0) == (status.adc_incomplete_buffers == 0)
            and 0 <= gpio_tail < GPIO_SAMPLES_PER_FRAME
            and status.gpio_items_dropped
            == status.gpio_frames_dropped * GPIO_SAMPLES_PER_FRAME + gpio_tail
            and status.adc_items_dropped
            == status.adc_frames_dropped * ADC_PAIRS_PER_FRAME + adc_tail,
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
        dropped = status.values[f"{prefix}_frames_dropped"]
        filling = status.values[f"{prefix}_packet_filling_depth"]
        ready = status.values[f"{prefix}_packet_ready_depth"]
        transmitting = status.values[f"{prefix}_packet_transmit_depth"]
        dropped_after_framing = status.values[f"{prefix}_frames_dropped_after_framing"]
        dropped_after_promotion = status.values[
            f"{prefix}_frames_dropped_after_promotion"
        ]
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
        tail_items = 0
        if allow_physical_stop_tail and prefix == "adc":
            tail_items = status.adc_stop_pairs_discarded
        elif allow_physical_stop_tail and prefix == "gpio":
            tail_items = status.gpio_raw_samples_lost
        require(
            status.values[f"{prefix}_items_dropped"]
            == dropped * items_per_frame + tail_items,
            "counter_disagreement",
            f"{prefix} dropped-item accounting disagrees with frames/tail",
        )
        require(
            status.values[f"{prefix}_payload_bytes_dropped"]
            == dropped * items_per_frame * item_bytes,
            "counter_disagreement",
            f"{prefix} dropped payload bytes disagree with dropped frames",
        )
        require(
            generated == transmitted + dropped + filling + ready + transmitting,
            "counter_disagreement",
            f"{prefix} produced-frame conservation failed",
        )
        require(
            framed == transmitted + ready + transmitting + dropped_after_framing,
            "counter_disagreement",
            f"{prefix} framed-frame conservation failed",
        )
        require(
            emitted == transmitted + transmitting + dropped_after_promotion,
            "counter_disagreement",
            f"{prefix} emitted-frame conservation failed",
        )
        evicted = status.values[f"{prefix}_frames_evicted"]
        evicted_after_promotion = status.values[
            f"{prefix}_frames_evicted_after_promotion"
        ]
        require(
            evicted <= dropped_after_framing
            and evicted_after_promotion <= evicted
            and evicted_after_promotion <= dropped_after_promotion,
            "counter_disagreement",
            f"{prefix} pressure-eviction boundaries disagree",
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
    require(
        status.packet_pressure_evictions
        == status.adc_frames_evicted + status.gpio_frames_evicted
        and status.adc_frames_dropped + status.gpio_frames_dropped
        == status.packet_pressure_evictions
        + status.packet_capacity_drops_without_evictable_frame,
        "counter_disagreement",
        "shared pressure/drop counters do not reconcile",
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
        "packet_owned_depth": PACKET_BUFFER_COUNT,
        "adc_packet_filling_depth": PACKET_BUFFER_COUNT,
        "gpio_packet_filling_depth": PACKET_BUFFER_COUNT,
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
        "usb_lower_priority_queue_depth": PACKET_QUEUE_CAPACITY,
        "usb_active_frame_bytes_sent": DATA_FRAME_BYTES,
        "usb_active_frame_size": DATA_FRAME_BYTES,
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
        status.packet_owned_depth
        == status.packet_ready_depth
        + status.packet_transmit_depth
        + status.adc_packet_filling_depth
        + status.gpio_packet_filling_depth,
        "counter_disagreement",
        "packet ownership states do not sum to owned depth",
    )
    require(
        status.packet_owned_depth <= status.packet_owned_high_water,
        "queue_bound",
        "packet owned depth exceeds its high-water mark",
    )
    require(
        status.usb_lower_priority_queue_depth == status.packet_transmit_depth,
        "counter_disagreement",
        "USB lower-priority depth disagrees with packet transmit depth",
    )
    require(
        status.gpio_processing_cpu_basis_points <= 10_000,
        "counter_disagreement",
        "GPIO processing CPU exceeds 100 percent",
    )
    require(
        status.usb_active_frame_bytes_sent <= status.usb_active_frame_size
        and status.usb_active_frame_size in {0, DATA_FRAME_BYTES},
        "counter_disagreement",
        "USB active-frame progress/size is invalid",
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
    allow_expected_pressure_loss: bool = False,
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
    validate_status_invariants(
        status,
        source=validator.source,
        allow_expected_pressure_loss=allow_expected_pressure_loss,
    )
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
    allow_expected_pressure_loss: bool = False,
) -> dict[str, object] | None:
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
        allow_expected_pressure_loss=allow_expected_pressure_loss,
    )
    adc_frames = validator.adc.frames
    gpio_frames = validator.gpio.frames
    adc_items = validator.adc.items
    gpio_items = validator.gpio.items
    adc_logical_frames = validator.adc.logical_frames
    gpio_logical_frames = validator.gpio.logical_frames
    adc_logical_items = adc_logical_frames * ADC_PAIRS_PER_FRAME
    gpio_logical_items = gpio_logical_frames * GPIO_SAMPLES_PER_FRAME
    adc_framed_frames = adc_frames + status.adc_frames_dropped_after_framing
    gpio_framed_frames = gpio_frames + status.gpio_frames_dropped_after_framing
    adc_emitted_frames = adc_frames + status.adc_frames_dropped_after_promotion
    gpio_emitted_frames = gpio_frames + status.gpio_frames_dropped_after_promotion
    common_exact = {
        "adc_frames_emitted": adc_emitted_frames,
        "gpio_frames_emitted": gpio_emitted_frames,
        "adc_frames_generated": adc_logical_frames,
        "adc_items_generated": adc_logical_items,
        "adc_frames_framed_pipeline": adc_framed_frames,
        "adc_items_framed_pipeline": adc_framed_frames * ADC_PAIRS_PER_FRAME,
        "adc_items_emitted": adc_emitted_frames * ADC_PAIRS_PER_FRAME,
        "adc_frames_transmitted": adc_frames,
        "adc_items_transmitted_pipeline": adc_items,
        "gpio_frames_generated": gpio_logical_frames,
        "gpio_items_generated": gpio_logical_items,
        "gpio_frames_framed_pipeline": gpio_framed_frames,
        "gpio_items_framed_pipeline": gpio_framed_frames * GPIO_SAMPLES_PER_FRAME,
        "gpio_items_emitted": gpio_emitted_frames * GPIO_SAMPLES_PER_FRAME,
        "gpio_frames_transmitted": gpio_frames,
        "gpio_items_transmitted_pipeline": gpio_items,
        "adc_frames_dropped": validator.adc.missing_frames,
        "gpio_frames_dropped": validator.gpio.missing_frames,
        "adc_payload_bytes_produced": adc_logical_items * ADC_BYTES_PER_PAIR,
        "adc_payload_bytes_framed": adc_framed_frames * DATA_PAYLOAD_BYTES,
        "adc_payload_bytes_emitted": adc_emitted_frames * DATA_PAYLOAD_BYTES,
        "adc_payload_bytes_transmitted": validator.adc.payload_bytes,
        "adc_payload_bytes_dropped": (
            validator.adc.missing_frames * DATA_PAYLOAD_BYTES
        ),
        "adc_framed_bytes_framed": adc_framed_frames * DATA_FRAME_BYTES,
        "adc_framed_bytes_emitted": adc_emitted_frames * DATA_FRAME_BYTES,
        "adc_framed_bytes_transmitted": validator.adc.framed_bytes,
        "gpio_payload_bytes_produced": gpio_logical_items,
        "gpio_payload_bytes_framed": gpio_framed_frames * DATA_PAYLOAD_BYTES,
        "gpio_payload_bytes_emitted": gpio_emitted_frames * DATA_PAYLOAD_BYTES,
        "gpio_payload_bytes_transmitted": validator.gpio.payload_bytes,
        "gpio_payload_bytes_dropped": (
            validator.gpio.missing_frames * DATA_PAYLOAD_BYTES
        ),
        "gpio_framed_bytes_framed": gpio_framed_frames * DATA_FRAME_BYTES,
        "gpio_framed_bytes_emitted": gpio_emitted_frames * DATA_FRAME_BYTES,
        "gpio_framed_bytes_transmitted": validator.gpio.framed_bytes,
        "packet_frames_promoted": adc_emitted_frames + gpio_emitted_frames,
        "packet_accounted_frame_skew": abs(adc_logical_frames - gpio_logical_frames),
        "data_payload_bytes_transmitted": (
            validator.adc.payload_bytes + validator.gpio.payload_bytes
        ),
        "data_framed_bytes_transmitted": (
            validator.adc.framed_bytes + validator.gpio.framed_bytes
        ),
        "commands_accepted": expected_commands,
        "packet_ready_depth": 0,
        "packet_transmit_depth": 0,
        "packet_owned_depth": 0,
        "adc_packet_filling_depth": 0,
        "gpio_packet_filling_depth": 0,
        "adc_packet_ready_depth": 0,
        "gpio_packet_ready_depth": 0,
        "adc_packet_transmit_depth": 0,
        "gpio_packet_transmit_depth": 0,
        "usb_command_queue_depth": 0,
        "usb_response_queue_depth": 0,
        "usb_lower_priority_queue_depth": 0,
        "usb_active_frame_bytes_sent": 0,
        "usb_active_frame_size": 0,
    }
    for name, expected in common_exact.items():
        require(
            status.values[name] == expected,
            "counter_disagreement",
            f"final {name}={status.values[name]} != {expected}",
        )

    if physical:
        physical_exact = {
            "gpio_samples_captured": (
                gpio_logical_items + status.gpio_raw_samples_lost
            ),
            "gpio_samples_packed": gpio_logical_items,
            "gpio_samples_framed": gpio_framed_frames * GPIO_SAMPLES_PER_FRAME,
            "gpio_samples_transmitted": gpio_items,
            "gpio_dma_major_loops": gpio_logical_frames,
            "adc0_dma_major_loops": adc_logical_frames,
            "adc1_dma_major_loops": adc_logical_frames,
            "adc0_dma_results": adc_logical_items,
            "adc1_dma_results": adc_logical_items,
            "adc_paired_major_loops": adc_logical_frames,
            "adc_buffers_completed": adc_logical_frames,
            "adc_buffers_acquired": adc_logical_frames,
            "adc_buffers_released": adc_logical_frames,
            "adc_pairs_captured": (adc_logical_items + status.adc_stop_pairs_discarded),
            "adc_pairs_delivered": adc_logical_items,
            "adc_pairs_framed": adc_framed_frames * ADC_PAIRS_PER_FRAME,
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

    gap_summary = validator.expected_gaps.summary()
    if not allow_expected_pressure_loss:
        require(
            validator.adc.missing_frames == 0
            and validator.gpio.missing_frames == 0
            and gap_summary["total"] == 0,
            "source_gap",
            "normal epoch recorded expected-loss gaps",
        )
        return None

    missing_total = validator.adc.missing_frames + validator.gpio.missing_frames
    require(
        physical
        and validator.adc.missing_frames > 0
        and validator.gpio.missing_frames > 0
        and validator.adc.gap_flag_frames > 0
        and validator.gpio.gap_flag_frames > 0,
        "expected_negative_loss",
        "named read-stall subcase did not induce flagged loss in both streams",
    )
    require(
        status.adc_frames_evicted == validator.adc.missing_frames
        and status.gpio_frames_evicted == validator.gpio.missing_frames
        and status.packet_pressure_evictions == missing_total
        and status.packet_pool_exhaustions == missing_total
        and status.packet_capacity_drops_without_evictable_frame == 0,
        "expected_negative_loss",
        "named read-stall pressure loss does not exactly match eviction counters",
    )
    return {
        "adc_frames": validator.adc.missing_frames,
        "adc_items": validator.adc.missing_frames * ADC_PAIRS_PER_FRAME,
        "adc_payload_bytes": validator.adc.missing_frames * DATA_PAYLOAD_BYTES,
        "adc_gap_flag_frames": validator.adc.gap_flag_frames,
        "gpio_frames": validator.gpio.missing_frames,
        "gpio_items": validator.gpio.missing_frames * GPIO_SAMPLES_PER_FRAME,
        "gpio_payload_bytes": validator.gpio.missing_frames * DATA_PAYLOAD_BYTES,
        "gpio_gap_flag_frames": validator.gpio.gap_flag_frames,
        "packet_pressure_evictions": status.packet_pressure_evictions,
        "packet_pool_exhaustions": status.packet_pool_exhaustions,
        "packet_capacity_drops_without_evictable_frame": (
            status.packet_capacity_drops_without_evictable_frame
        ),
        "gaps": gap_summary,
    }


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
    "adc_frames_dropped",
    "gpio_frames_generated",
    "gpio_frames_framed_pipeline",
    "gpio_frames_transmitted",
    "gpio_frames_dropped",
    "adc_payload_bytes_produced",
    "adc_payload_bytes_framed",
    "adc_payload_bytes_transmitted",
    "gpio_payload_bytes_produced",
    "gpio_payload_bytes_framed",
    "gpio_payload_bytes_transmitted",
    "data_payload_bytes_transmitted",
    "data_framed_bytes_transmitted",
    "packet_frames_promoted",
    "packet_pressure_evictions",
    "packet_capacity_drops_without_evictable_frame",
    "adc_frames_evicted",
    "gpio_frames_evicted",
    "adc_frames_dropped_after_framing",
    "adc_frames_dropped_after_promotion",
    "gpio_frames_dropped_after_framing",
    "gpio_frames_dropped_after_promotion",
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
    timed_adc_missing_frames: int
    timed_gpio_missing_frames: int
    timed_adc_items: int
    timed_gpio_items: int
    total_adc_frames: int
    total_gpio_frames: int
    total_adc_missing_frames: int
    total_gpio_missing_frames: int
    total_adc_items: int
    total_gpio_items: int
    status_latency: dict[str, float | int | None]
    command_latency: dict[str, float | int | None]
    status_rollup: dict[str, object]
    final_counters: dict[str, int]
    diagnostics: dict[str, object]
    maximum_receive_gap_seconds: float
    parser: dict[str, int]
    expected_negative_subcase: dict[str, object] | None

    @property
    def timed_payload_bytes(self) -> int:
        return self.timed_adc_items * ADC_BYTES_PER_PAIR + self.timed_gpio_items

    @property
    def timed_framed_bytes(self) -> int:
        return (self.timed_adc_frames + self.timed_gpio_frames) * DATA_FRAME_BYTES

    @property
    def logical_timed_adc_items(self) -> int:
        return (
            self.timed_adc_items + self.timed_adc_missing_frames * ADC_PAIRS_PER_FRAME
        )

    @property
    def logical_timed_gpio_items(self) -> int:
        return (
            self.timed_gpio_items
            + self.timed_gpio_missing_frames * GPIO_SAMPLES_PER_FRAME
        )

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
                "adc_missing_frames": self.timed_adc_missing_frames,
                "gpio_missing_frames": self.timed_gpio_missing_frames,
                "adc_pairs": self.timed_adc_items,
                "gpio_samples": self.timed_gpio_items,
                "logical_adc_pairs": self.logical_timed_adc_items,
                "logical_gpio_samples": self.logical_timed_gpio_items,
                "payload_bytes": self.timed_payload_bytes,
                "framed_bytes": self.timed_framed_bytes,
                "adc_pair_rate_hz": self.timed_adc_items / elapsed,
                "gpio_sample_rate_hz": self.timed_gpio_items / elapsed,
                "logical_adc_pair_rate_hz": self.logical_timed_adc_items / elapsed,
                "logical_gpio_sample_rate_hz": (
                    self.logical_timed_gpio_items / elapsed
                ),
                "payload_bytes_per_second": self.timed_payload_bytes / elapsed,
                "framed_bytes_per_second": self.timed_framed_bytes / elapsed,
            },
            "total": {
                "adc_frames": self.total_adc_frames,
                "gpio_frames": self.total_gpio_frames,
                "adc_missing_frames": self.total_adc_missing_frames,
                "gpio_missing_frames": self.total_gpio_missing_frames,
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
            "expected_negative_subcase": self.expected_negative_subcase,
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

    def stall_running_with_expected_pressure(
        self,
        validator: StreamValidator,
    ) -> dict[str, object]:
        """Pause host reads in one live session and retain named-loss evidence."""

        link = self.link
        if self.port is None or link is None:
            raise SoakFailure("control", "cannot stall a closed serial session")
        parser_before = {
            "bytes_received": link.parser.bytes_received,
            "frames_decoded": link.parser.frames_decoded,
            "bytes_discarded": link.parser.bytes_discarded,
            "errors": link.parser.errors,
            "buffered_bytes": len(link.parser.buffer),
        }
        emit_event(
            "expected_negative_subcase_begin",
            subcase="serial_read_stall_pressure",
            expected_device_state="RUNNING",
            expected="no host serial reads",
            run_id=validator.run_id,
            stall_seconds=EXPECTED_NEGATIVE_STALL_SECONDS,
        )
        started = self.clock.monotonic()
        self.clock.sleep(EXPECTED_NEGATIVE_STALL_SECONDS)
        elapsed = self.clock.monotonic() - started
        self._check_budget("serial read stall", reserve=8.0)
        parser_after = {
            "bytes_received": link.parser.bytes_received,
            "frames_decoded": link.parser.frames_decoded,
            "bytes_discarded": link.parser.bytes_discarded,
            "errors": link.parser.errors,
            "buffered_bytes": len(link.parser.buffer),
        }
        require(
            parser_after == parser_before,
            "expected_negative_loss",
            "serial parser changed during the intentional no-read interval",
        )
        require(
            elapsed >= EXPECTED_NEGATIVE_STALL_SECONDS,
            "latency_violation",
            f"serial read stall {elapsed:.6f}s ended before its planned interval",
        )
        require(
            elapsed <= EXPECTED_NEGATIVE_STALL_DEADLINE_SECONDS,
            "latency_violation",
            f"serial read stall {elapsed:.6f}s exceeds "
            f"{EXPECTED_NEGATIVE_STALL_DEADLINE_SECONDS:.6f}s",
        )
        evidence: dict[str, object] = {
            "name": "serial_read_stall_pressure",
            "result": "pending",
            "run_id": validator.run_id,
            "expected_device_state": "RUNNING",
            "stall_seconds": EXPECTED_NEGATIVE_STALL_SECONDS,
            "elapsed_seconds": elapsed,
            "transport_session": "continuous",
            "parser_before": parser_before,
            "parser_after": parser_after,
        }
        emit_event(
            "expected_negative_subcase_stall_complete",
            subcase="serial_read_stall_pressure",
            elapsed_seconds=elapsed,
            run_id=validator.run_id,
            state="RUNNING",
        )
        return evidence

    def run_epoch(
        self,
        *,
        index: int,
        source: int,
        measured_seconds: float,
        warmup_seconds: float,
        previous_run_id: int | None,
        expected_negative_subcase: str | None = None,
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
            allow_expected_gaps=expected_negative_subcase is not None,
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
        timed_baseline = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        next_status_at = active_started
        next_info_at = active_started + self.settings.info_interval_seconds
        previous_status: StatusSnapshot | None = None
        negative_evidence: dict[str, object] | None = None
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
                    validator.adc.missing_frames,
                    validator.gpio.missing_frames,
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
            if (
                expected_negative_subcase is not None
                and negative_evidence is None
                and timed_started_at is not None
                and now >= timed_started_at + min(2.0, measured_seconds / 3.0)
            ):
                require(
                    expected_negative_subcase == "serial_read_stall_pressure",
                    "configuration",
                    f"unknown expected negative subcase {expected_negative_subcase!r}",
                )
                require(
                    previous_status is not None
                    and previous_status.adc_frames_dropped == 0
                    and previous_status.gpio_frames_dropped == 0,
                    "expected_negative_loss",
                    "serial read-stall pressure baseline was not zero-loss",
                )
                assert previous_status is not None
                negative_evidence = self.stall_running_with_expected_pressure(validator)
                negative_evidence["baseline"] = {
                    "stats_generation": previous_status.stats_generation,
                    "adc_frames_generated": previous_status.adc_frames_generated,
                    "gpio_frames_generated": previous_status.gpio_frames_generated,
                    "adc_frames_dropped": previous_status.adc_frames_dropped,
                    "gpio_frames_dropped": previous_status.gpio_frames_dropped,
                    "device_state": previous_status.device_state,
                }
                next_status_at = self.clock.monotonic()
                continue
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
                    allow_expected_pressure_loss=negative_evidence is not None,
                )
                previous_status = status
                status_rollup.observe(status)
                checkpoint = status_rollup.count % checkpoint_interval == 0
                self.memory.sample_streaming(checkpoint=checkpoint)
                if checkpoint:
                    emit_event(
                        "status_checkpoint",
                        epoch=index,
                        elapsed_seconds=(
                            max(0.0, self.clock.monotonic() - timed_started_at)
                            if timed_started_at is not None
                            else 0.0
                        ),
                        planned_seconds=measured_seconds,
                        adc_frames=validator.adc.frames,
                        gpio_frames=validator.gpio.frames,
                        status_count=status_rollup.count,
                        parser_errors=link.parser.errors,
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
        require(
            expected_negative_subcase is None or negative_evidence is not None,
            "expected_negative_loss",
            "planned named negative subcase did not execute",
        )
        measured_elapsed = self.clock.monotonic() - timed_started_at
        baseline_adc_frames, baseline_gpio_frames = timed_baseline[:2]
        baseline_adc_items, baseline_gpio_items = timed_baseline[2:4]
        baseline_adc_missing, baseline_gpio_missing = timed_baseline[8:10]
        timed_adc_frames = validator.adc.frames - baseline_adc_frames
        timed_gpio_frames = validator.gpio.frames - baseline_gpio_frames
        timed_adc_missing_frames = validator.adc.missing_frames - baseline_adc_missing
        timed_gpio_missing_frames = (
            validator.gpio.missing_frames - baseline_gpio_missing
        )
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
        pressure_loss = reconcile_final_status(
            final_status,
            final_frame,
            validator,
            expected_generation=expected_generation,
            expected_commands=expected_commands,
            allow_expected_pressure_loss=negative_evidence is not None,
        )
        if negative_evidence is not None:
            require(
                pressure_loss is not None,
                "expected_negative_loss",
                "named negative subcase produced no reconciled loss summary",
            )
            negative_evidence["result"] = "PASS"
            negative_evidence["loss"] = pressure_loss
            negative_evidence["final_state"] = "IDLE"
            negative_evidence["stats_generation"] = expected_generation
            emit_event(
                "expected_negative_subcase_complete",
                subcase=expected_negative_subcase,
                run_id=validator.run_id,
                adc_frames=validator.adc.missing_frames,
                gpio_frames=validator.gpio.missing_frames,
                packet_pressure_evictions=final_status.packet_pressure_evictions,
                state="IDLE",
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
        graded_adc_items = (
            timed_adc_items + timed_adc_missing_frames * ADC_PAIRS_PER_FRAME
        )
        graded_gpio_items = (
            timed_gpio_items + timed_gpio_missing_frames * GPIO_SAMPLES_PER_FRAME
        )
        rates = {
            "adc_pair_rate_hz": graded_adc_items / measured_elapsed,
            "gpio_sample_rate_hz": graded_gpio_items / measured_elapsed,
            "payload_bytes_per_second": (
                graded_adc_items * ADC_BYTES_PER_PAIR + graded_gpio_items
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
            timed_adc_missing_frames=timed_adc_missing_frames,
            timed_gpio_missing_frames=timed_gpio_missing_frames,
            timed_adc_items=timed_adc_items,
            timed_gpio_items=timed_gpio_items,
            total_adc_frames=validator.adc.frames,
            total_gpio_frames=validator.gpio.frames,
            total_adc_missing_frames=validator.adc.missing_frames,
            total_gpio_missing_frames=validator.gpio.missing_frames,
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
            expected_negative_subcase=negative_evidence,
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
                    expected_negative_subcase=(
                        "serial_read_stall_pressure" if epoch_index == 1 else None
                    ),
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
            negative_subcases = [
                epoch.expected_negative_subcase
                for epoch in self.epochs
                if epoch.expected_negative_subcase is not None
            ]
            require(
                len(negative_subcases) == 1
                and negative_subcases[0].get("name") == "serial_read_stall_pressure"
                and negative_subcases[0].get("result") == "PASS",
                "expected_negative_loss",
                "control campaign did not complete exactly one named loss subcase",
            )

        require(
            bool(self.epochs)
            and self.epochs[-1].final_counters.get("device_state") == STATE_IDLE,
            "control",
            "campaign did not finish in IDLE",
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
        negative_subcases = [
            epoch.expected_negative_subcase
            for epoch in self.epochs
            if epoch.expected_negative_subcase is not None
        ]
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
                "expected_negative_subcase_count": len(negative_subcases),
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
            "negative_subcases": negative_subcases,
            "cleanup": {"attempted": False, "normal_close": True},
            "program": {
                "sha256": _program_sha256(),
                "validator_sha256": self.settings.validator_sha256,
                "candidate_sha256": self.settings.candidate_sha256,
                "validation_manifest_sha256": (
                    self.settings.validation_manifest_sha256
                ),
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
            "validation_manifest_sha256": (self.settings.validation_manifest_sha256),
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
        if link is None:
            self.cleanup["stop"] = "unavailable"
            return
        cleanup_deadline = min(
            self.script_started_at + self.settings.service_container_limit_seconds,
            self.clock.monotonic() + 2.0,
        )
        if self.clock.monotonic() >= cleanup_deadline:
            self.cleanup["stop"] = "unavailable: total deadline expired"
            return
        try:
            frame, latency = link.exchange(
                GET_STATUS_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.01, cleanup_deadline - self.clock.monotonic()),
                ),
                on_data=lambda _frame: None,
                hard_deadline=cleanup_deadline,
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
        if self.clock.monotonic() >= cleanup_deadline:
            self.cleanup["stop"] = "unavailable"
            return
        try:
            frame, latency = link.exchange(
                STOP_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.01, cleanup_deadline - self.clock.monotonic()),
                ),
                on_data=lambda _frame: None,
                hard_deadline=cleanup_deadline,
            )
            self.cleanup["stop"] = {
                "response_flags": frame.flags,
                "state": frame.payload[4] if len(frame.payload) > 4 else None,
                "latency_seconds": latency,
            }
        except Exception as error:  # noqa: BLE001 - best-effort remote evidence
            self.cleanup["stop"] = f"{type(error).__name__}: {error}"
        if self.clock.monotonic() >= cleanup_deadline:
            return
        try:
            frame, latency = link.exchange(
                GET_STATUS_REQUEST,
                timeout=min(
                    COMMAND_DEADLINE_SECONDS,
                    max(0.01, cleanup_deadline - self.clock.monotonic()),
                ),
                on_data=lambda _frame: None,
                hard_deadline=cleanup_deadline,
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
                "validation_manifest_sha256": (
                    self.settings.validation_manifest_sha256
                ),
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


# <soak-cli>
import argparse  # noqa: I001 - generated driver imports follow the canonical core
import ctypes
import platform
import re
import threading
from pathlib import Path

from serial.tools import list_ports


WINDOWS_REPORT_SCHEMA_VERSION = 2
WINDOWS_DEFAULT_DURATION_SECONDS = 3_600.0
WINDOWS_SMOKE_DURATION_SECONDS = 10.0
WINDOWS_MAXIMUM_DURATION_SECONDS = 86_400.0
WINDOWS_RUN_RESERVE_SECONDS = 90.0
WINDOWS_CLEANUP_RESERVE_SECONDS = 30.0
WINDOWS_DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 15.0
WINDOWS_DEFAULT_OPEN_TIMEOUT_SECONDS = 3.0
WINDOWS_CLOSE_TIMEOUT_SECONDS = 1.0
TEENSY_USB_SERIAL_VID = 0x16C0
TEENSY_USB_SERIAL_PID = 0x0483
THINGDAQ_PRODUCT = "ThingDAQ"
WINDOWS_PORT_PATTERN = re.compile(r"(?i)^COM([1-9][0-9]*)$")
SOAK_CONFORMANCE_SCHEMA_VERSION = 1
SOAK_CONFORMANCE_PREFIX = "SOAK_CONFORMANCE "
_WINDOWS_RELEASE_PROFILE_REQUIREMENTS = (
    "physical_combined_mode",
    "exact_3600_second_duration",
    "non_smoke",
    "diagnostic_identity_override_disabled",
    "native_windows_host",
)


class _WindowsProcessMemoryCounters(ctypes.Structure):
    """Windows ``PROCESS_MEMORY_COUNTERS`` with architecture-sized fields."""

    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


@dataclass(frozen=True)
class _WindowsProcessMemoryApi:
    """Mockable pair of native calls needed for process-memory evidence."""

    get_current_process: Callable[[], object]
    get_process_memory_info: Callable[[object, object, int], object]


def _load_windows_process_memory_api() -> _WindowsProcessMemoryApi | None:
    """Load and type the dependency-free Windows process-memory API once."""

    dll_loader = getattr(ctypes, "WinDLL", None)
    if dll_loader is None:
        return None
    try:
        kernel32 = dll_loader("kernel32", use_last_error=True)
        psapi = dll_loader("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_WindowsProcessMemoryCounters),
            ctypes.c_uint32,
        ]
        get_process_memory_info.restype = ctypes.c_int
    except Exception:  # noqa: BLE001 - optional native evidence fails closed
        return None
    return _WindowsProcessMemoryApi(
        get_current_process=get_current_process,
        get_process_memory_info=get_process_memory_info,
    )


_WINDOWS_PROCESS_MEMORY_API = (
    _load_windows_process_memory_api() if sys.platform == "win32" else None
)
_canonical_current_rss_bytes = _current_rss_bytes
_canonical_peak_rss_bytes = _peak_rss_bytes


def _windows_process_memory_bytes(
    api: _WindowsProcessMemoryApi | None = None,
) -> tuple[int, int] | None:
    """Return validated current/peak working-set bytes from one native call."""

    selected_api = _WINDOWS_PROCESS_MEMORY_API if api is None else api
    if selected_api is None:
        return None
    counters = _WindowsProcessMemoryCounters()
    structure_size = ctypes.sizeof(counters)
    counters.cb = structure_size
    try:
        process = selected_api.get_current_process()
        if process is None or process == 0:
            return None
        succeeded = selected_api.get_process_memory_info(
            process,
            ctypes.byref(counters),
            structure_size,
        )
    except Exception:  # noqa: BLE001 - optional native evidence fails closed
        return None
    if not succeeded or counters.cb != structure_size:
        return None
    current_bytes = int(counters.WorkingSetSize)
    peak_bytes = int(counters.PeakWorkingSetSize)
    if current_bytes < 0 or peak_bytes < current_bytes:
        return None
    return current_bytes, peak_bytes


def _current_rss_bytes() -> int | None:  # type: ignore[no-redef]
    if sys.platform != "win32":
        return _canonical_current_rss_bytes()
    memory = _windows_process_memory_bytes()
    return memory[0] if memory is not None else None


def _peak_rss_bytes() -> int | None:  # type: ignore[no-redef]
    if sys.platform != "win32":
        return _canonical_peak_rss_bytes()
    memory = _windows_process_memory_bytes()
    return memory[1] if memory is not None else None


@dataclass(frozen=True)
class WindowsPortCandidate:
    """One plausible Windows Teensy USB Serial endpoint."""

    port: str
    vid: int
    pid: int
    serial_number: str | None
    product: str | None
    manufacturer: str | None
    location: str | None
    interface: str | None
    description: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "port": self.port,
            "vid": self.vid,
            "pid": self.pid,
            "vid_pid": f"{self.vid:04X}:{self.pid:04X}",
            "serial_number": self.serial_number,
            "product": self.product,
            "manufacturer": self.manufacturer,
            "location": self.location,
            "interface": self.interface,
            "description": self.description,
        }


@dataclass(frozen=True)
class WindowsProbeResult:
    """Bounded INFO-probe evidence for one plausible endpoint."""

    candidate: WindowsPortCandidate
    observed_identity: dict[str, object] | None
    identity_mismatches: dict[str, dict[str, object]]
    latency_seconds: list[float]
    failure: dict[str, str] | None
    close: dict[str, object]

    @property
    def passed(self) -> bool:
        return self.failure is None and self.observed_identity is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_dict(),
            "result": "PASS" if self.passed else "FAIL",
            "release_identity_match": not self.identity_mismatches,
            "observed_identity": self.observed_identity,
            "identity_mismatches": self.identity_mismatches,
            "info_latency_seconds": self.latency_seconds,
            "failure": self.failure,
            "close": self.close,
        }


def _optional_metadata(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _windows_port_number(port: str) -> int:
    match = WINDOWS_PORT_PATTERN.fullmatch(port)
    return int(match.group(1)) if match is not None else 0x7FFFFFFF


def _windows_candidate_sort_key(
    candidate: WindowsPortCandidate,
) -> tuple[object, ...]:
    if candidate.product == THINGDAQ_PRODUCT:
        product_rank = 0
    elif candidate.product is None:
        product_rank = 1
    else:
        product_rank = 2
    return (
        product_rank,
        (candidate.serial_number or "").casefold(),
        (candidate.location or "").casefold(),
        _windows_port_number(candidate.port),
        candidate.port.casefold(),
    )


def enumerate_windows_candidates(
    port_enumerator: Callable[[], object] | None = None,
) -> tuple[WindowsPortCandidate, ...]:
    """Enumerate only matching Teensy USB Serial COM endpoints."""

    enumerate_ports = port_enumerator or (
        lambda: list_ports.comports(include_links=False)
    )
    candidates: list[WindowsPortCandidate] = []
    seen: set[str] = set()
    metadata_records = enumerate_ports()
    if not isinstance(metadata_records, (list, tuple)):
        raise SoakFailure("discovery", "COM enumerator did not return a sequence")
    for metadata in metadata_records:
        if (
            getattr(metadata, "vid", None) != TEENSY_USB_SERIAL_VID
            or getattr(metadata, "pid", None) != TEENSY_USB_SERIAL_PID
        ):
            continue
        port = getattr(metadata, "device", None)
        if not isinstance(port, str) or WINDOWS_PORT_PATTERN.fullmatch(port) is None:
            continue
        normalized = port.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(
            WindowsPortCandidate(
                port=port,
                vid=TEENSY_USB_SERIAL_VID,
                pid=TEENSY_USB_SERIAL_PID,
                serial_number=_optional_metadata(
                    getattr(metadata, "serial_number", None)
                ),
                product=_optional_metadata(getattr(metadata, "product", None)),
                manufacturer=_optional_metadata(
                    getattr(metadata, "manufacturer", None)
                ),
                location=_optional_metadata(getattr(metadata, "location", None)),
                interface=_optional_metadata(getattr(metadata, "interface", None)),
                description=_optional_metadata(getattr(metadata, "description", None)),
            )
        )
    candidates.sort(key=_windows_candidate_sort_key)
    return tuple(candidates)


class _SerialOpenAttempt:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.cancelled = False
        self.port: SerialPort | None = None
        self.error: BaseException | None = None


def _close_raw_serial(port: SerialPort) -> None:
    try:
        port.close()
    except BaseException:  # noqa: BLE001 - late open cleanup is best effort
        return


class BoundedWindowsSerial:
    """Map PySerial failures and make close attempts time-bounded."""

    def __init__(self, port_name: str, raw_port: SerialPort) -> None:
        self.port_name = port_name
        self.raw_port = raw_port
        self.close_attempted = False
        self.close_completed = False
        self.close_timed_out = False
        self.close_error: str | None = None

    def read(self, size: int = 1) -> bytes:
        try:
            return bytes(self.raw_port.read(size))
        except (serial.SerialException, OSError) as error:
            raise SoakFailure(
                "disconnect",
                f"{self.port_name} read failed: {type(error).__name__}: {error}",
            ) from error

    def write(self, data: bytes) -> int | None:
        try:
            return self.raw_port.write(data)
        except serial.SerialTimeoutException as error:
            raise DeadlineExpired(
                f"{self.port_name} write timed out: {error}"
            ) from error
        except (serial.SerialException, OSError) as error:
            raise SoakFailure(
                "disconnect",
                f"{self.port_name} write failed: {type(error).__name__}: {error}",
            ) from error

    def close(self) -> None:
        if self.close_attempted:
            return
        self.close_attempted = True
        completed = threading.Event()
        errors: list[str] = []

        def close_worker() -> None:
            try:
                self.raw_port.close()
            except BaseException as error:  # noqa: BLE001 - retained as evidence
                errors.append(f"{type(error).__name__}: {error}")
            finally:
                completed.set()

        threading.Thread(
            target=close_worker,
            name="thingdaq-serial-close",
            daemon=True,
        ).start()
        self.close_completed = completed.wait(WINDOWS_CLOSE_TIMEOUT_SECONDS)
        self.close_timed_out = not self.close_completed
        self.close_error = errors[0] if errors else None

    def close_summary(self) -> dict[str, object]:
        return {
            "attempted": self.close_attempted,
            "completed": self.close_completed,
            "timed_out": self.close_timed_out,
            "error": self.close_error,
        }


def open_windows_serial(
    port_name: str,
    *,
    open_timeout_seconds: float,
) -> BoundedWindowsSerial:
    """Open a COM endpoint without allowing the calling thread to hang."""

    attempt = _SerialOpenAttempt()

    def open_worker() -> None:
        opened: SerialPort | None = None
        error: BaseException | None = None
        try:
            opened = serial.Serial(
                port=port_name,
                baudrate=BAUD_RATE,
                timeout=SERIAL_READ_TIMEOUT_SECONDS,
                write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
            )
            try:
                opened.dtr = True  # type: ignore[attr-defined]
            except (AttributeError, OSError, serial.SerialException):
                pass
        except BaseException as caught:  # noqa: BLE001 - transferred to caller
            error = caught
        close_late_port: SerialPort | None = None
        with attempt.lock:
            if attempt.cancelled:
                close_late_port = opened
            else:
                attempt.port = opened
                attempt.error = error
        attempt.done.set()
        if close_late_port is not None:
            threading.Thread(
                target=_close_raw_serial,
                args=(close_late_port,),
                name="thingdaq-late-open-close",
                daemon=True,
            ).start()

    threading.Thread(
        target=open_worker,
        name="thingdaq-serial-open",
        daemon=True,
    ).start()
    if not attempt.done.wait(open_timeout_seconds):
        opened_after_timeout: SerialPort | None
        with attempt.lock:
            attempt.cancelled = True
            opened_after_timeout = attempt.port
            attempt.port = None
        if opened_after_timeout is not None:
            threading.Thread(
                target=_close_raw_serial,
                args=(opened_after_timeout,),
                name="thingdaq-open-timeout-close",
                daemon=True,
            ).start()
        raise DeadlineExpired(
            f"serial open for {port_name} exceeded {open_timeout_seconds:g} seconds"
        )
    if attempt.error is not None:
        error = attempt.error
        category = (
            "timeout"
            if isinstance(error, serial.SerialTimeoutException)
            else "serial_open"
        )
        raise SoakFailure(
            category,
            f"could not open {port_name}: {type(error).__name__}: {error}",
        ) from error
    if attempt.port is None:
        raise SoakFailure(
            "serial_open", f"serial open for {port_name} returned no port"
        )
    return BoundedWindowsSerial(port_name, attempt.port)


def _observed_probe_identity(
    info: Mapping[str, object],
    expected_info: Mapping[str, object],
) -> dict[str, object]:
    return {name: _identity_json_value(info.get(name)) for name in expected_info}


def probe_windows_candidate(
    candidate: WindowsPortCandidate,
    settings: RuntimeSettings,
    *,
    discovery_deadline: float,
    open_timeout_seconds: float,
    clock: Clock = time,
) -> WindowsProbeResult:
    """Perform a bounded, read-only, exact-identity INFO probe."""

    port: BoundedWindowsSerial | None = None
    info: dict[str, object] | None = None
    identity_mismatches: dict[str, dict[str, object]] = {}
    latencies: list[float] = []
    failure: dict[str, str] | None = None
    try:
        remaining = discovery_deadline - clock.monotonic()
        if remaining <= 0:
            raise DeadlineExpired("Windows COM discovery total deadline expired")
        port = open_windows_serial(
            candidate.port,
            open_timeout_seconds=min(open_timeout_seconds, remaining),
        )
        link = SerialLink(port, clock, read_bytes=settings.serial_read_bytes)
        remaining = discovery_deadline - clock.monotonic()
        if remaining <= STARTUP_DRAIN_SECONDS:
            raise DeadlineExpired("insufficient discovery budget for startup drain")
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        info, latencies = synchronize(link, hard_deadline=discovery_deadline)
        identity_mismatches = info_identity_mismatches(info, settings)
        validate_info_identity(info, settings, expected_state=STATE_IDLE)
        usb_serial = candidate.serial_number
        if usb_serial is not None and usb_serial.isascii() and usb_serial.isdecimal():
            require(
                int(usb_serial, 10) == info["hardware_serial"],
                "identity",
                "USB descriptor serial disagrees with INFO hardware serial",
            )
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            raise
        failure = {
            "category": error.category if isinstance(error, SoakFailure) else "probe",
            "type": type(error).__name__,
            "message": str(error),
        }
    finally:
        if port is not None:
            port.close()
    close: dict[str, object]
    if port is not None:
        close = port.close_summary()
    else:
        close = {
            "attempted": False,
            "completed": False,
            "timed_out": False,
            "error": None,
        }
    if failure is None and (close["timed_out"] or close["error"] is not None):
        failure = {
            "category": "cleanup",
            "type": "SerialCloseError",
            "message": f"probe close did not complete cleanly: {close}",
        }
    return WindowsProbeResult(
        candidate=candidate,
        observed_identity=(
            _observed_probe_identity(info, settings.expected_info)
            if failure is None and info is not None
            else None
        ),
        identity_mismatches=identity_mismatches,
        latency_seconds=latencies,
        failure=failure,
        close=close,
    )


def probe_windows_candidates(
    candidates: tuple[WindowsPortCandidate, ...],
    settings: RuntimeSettings,
    *,
    discovery_timeout_seconds: float,
    open_timeout_seconds: float,
    clock: Clock = time,
) -> tuple[WindowsProbeResult, ...]:
    deadline = clock.monotonic() + discovery_timeout_seconds
    results: list[WindowsProbeResult] = []
    for candidate in candidates:
        if clock.monotonic() >= deadline:
            results.append(
                WindowsProbeResult(
                    candidate=candidate,
                    observed_identity=None,
                    identity_mismatches={},
                    latency_seconds=[],
                    failure={
                        "category": "timeout",
                        "type": "DeadlineExpired",
                        "message": "not probed before the discovery total deadline",
                    },
                    close={
                        "attempted": False,
                        "completed": False,
                        "timed_out": False,
                        "error": None,
                    },
                )
            )
            continue
        print(f"Probing {candidate.port}...", flush=True)
        result = probe_windows_candidate(
            candidate,
            settings,
            discovery_deadline=deadline,
            open_timeout_seconds=open_timeout_seconds,
            clock=clock,
        )
        if result.passed:
            match = (
                "matching release identity"
                if not result.identity_mismatches
                else "accepted only by diagnostic identity override"
            )
            print(f"  {candidate.port}: ThingDAQ, {match}", flush=True)
        else:
            assert result.failure is not None
            print(
                f"  {candidate.port}: rejected "
                f"({result.failure['category']}: {result.failure['message']})",
                flush=True,
            )
        results.append(result)
    return tuple(results)


def select_windows_candidate(
    probes: tuple[WindowsProbeResult, ...],
    *,
    hardware_serial: int,
) -> WindowsPortCandidate:
    matching = [
        probe.candidate
        for probe in probes
        if probe.passed
        and probe.observed_identity is not None
        and probe.observed_identity.get("hardware_serial") == hardware_serial
    ]
    if not matching:
        raise SoakFailure(
            "discovery",
            f"no plausible COM port passed the exact identity probe for hardware "
            f"serial {hardware_serial}",
        )
    return min(matching, key=_windows_candidate_sort_key)


class WindowsPortFactory:
    def __init__(
        self,
        candidate: WindowsPortCandidate,
        *,
        open_timeout_seconds: float,
    ) -> None:
        self.candidate = candidate
        self.open_timeout_seconds = open_timeout_seconds
        self.opened: list[BoundedWindowsSerial] = []

    def __call__(self) -> SerialPort:
        port = open_windows_serial(
            self.candidate.port,
            open_timeout_seconds=self.open_timeout_seconds,
        )
        self.opened.append(port)
        return port

    def summary(self) -> list[dict[str, object]]:
        return [port.close_summary() for port in self.opened]


def windows_runtime_settings(
    mode: str,
    duration: float,
    *,
    diagnostic_identity_override: bool = False,
) -> RuntimeSettings:
    """Apply only duration/source choices to the pinned generated candidate."""

    config = json.loads(json.dumps(GENERATED_CONFIG))
    if not isinstance(config, dict):
        raise SoakFailure("configuration", "generated config is not an object")
    candidate = _mapping(config.get("candidate"), "candidate")
    soak = candidate.get("soak")
    if not isinstance(soak, dict):
        raise SoakFailure("configuration", "candidate.soak is not an object")
    internal_mode = "physical-combined" if mode == "combined" else "synthetic"
    status_interval = max(1.0, duration / 3_500.0)
    info_interval = max(30.0, duration / 400.0, status_interval)
    warmup = _number(soak.get("warmup_seconds"), "soak.warmup_seconds")
    soak.update(
        {
            "measured_duration_seconds": duration,
            "status_interval_seconds": status_interval,
            "info_interval_seconds": info_interval,
            "hard_deadline_seconds": (duration + warmup + WINDOWS_RUN_RESERVE_SECONDS),
            "service_container_limit_seconds": (
                duration
                + warmup
                + WINDOWS_RUN_RESERVE_SECONDS
                + WINDOWS_CLEANUP_RESERVE_SECONDS
            ),
        }
    )
    config["mode"] = internal_mode
    config["diagnostic_identity_override"] = diagnostic_identity_override
    return load_settings(config)


class _ConformanceClock:
    """Deterministic clock used only by the bounded entry-point self-check."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _conformance_payload(kind: int, first_sample_ticks: int) -> bytes:
    if kind == ADC_DATA:
        start_pair = first_sample_ticks // ADC_PAIR_PERIOD_TICKS
        offset = (start_pair * ADC_BYTES_PER_PAIR) % len(ADC_PATTERN)
        return ADC_PATTERN_DOUBLE[offset : offset + DATA_PAYLOAD_BYTES]
    start_sample = first_sample_ticks // GPIO_SAMPLE_PERIOD_TICKS
    offset = start_sample & 0xFF
    return GPIO_PATTERN_EXPANDED[offset : offset + DATA_PAYLOAD_BYTES]


def _conformance_data_frame(
    kind: int,
    *,
    sequence: int = 0,
    gap_before: bool = False,
    corrupt_checksum: bool = False,
    corrupt_pattern: bool = False,
) -> bytes:
    first_sample_ticks = sequence * FRAME_COVERAGE_TICKS
    flags = FLAG_SYNTHETIC
    if sequence == 0:
        flags |= FLAG_EPOCH_START
    if gap_before:
        flags |= FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE
    payload = bytearray(_conformance_payload(kind, first_sample_ticks))
    if corrupt_pattern:
        payload[17] ^= 0x01
    item_count = ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
    header = HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        kind,
        flags,
        HEADER_SIZE,
        CHECKSUM_ADLER32,
        0,
        DATA_FRAME_BYTES,
        DATA_PAYLOAD_BYTES,
        7,
        sequence,
        0,
        first_sample_ticks,
        item_count,
    )
    body = header + payload
    wire = bytearray(body + TRAILER.pack(adler32(body)))
    if corrupt_checksum:
        wire[HEADER_SIZE + 29] ^= 0x80
    return bytes(wire)


def _conformance_grade(transcript: bytes) -> dict[str, object]:
    parser = FrameParser(maximum_input_bytes=DATA_FRAME_BYTES)
    clock = _ConformanceClock()
    validator = StreamValidator(
        7,
        SOURCE_SYNTHETIC,
        CHECKSUM_ADLER32,
        clock,
    )
    pattern = (1, 7, 31, 257, DATA_FRAME_BYTES, 17)
    offset = 0
    chunk_index = 0
    try:
        while offset < len(transcript):
            chunk_bytes = pattern[chunk_index % len(pattern)]
            chunk_index += 1
            chunk = transcript[offset : offset + chunk_bytes]
            offset += len(chunk)
            before_errors = parser.errors
            frames = parser.feed(chunk)
            if parser.errors != before_errors:
                category = "checksum_corruption" if parser.checksum_errors else "parser"
                raise SoakFailure(
                    category,
                    "fixture transcript contains rejected wire bytes",
                )
            for frame in frames:
                validator.accept(frame)
        require(not parser.buffer, "parser", "fixture transcript ended mid-frame")
        require(
            validator.adc.frames == 1 and validator.gpio.frames == 1,
            "source_gap",
            "fixture transcript did not contain one frame from each stream",
        )
        elapsed_seconds = FRAME_COVERAGE_TICKS / TIMESTAMP_HZ
        metrics = {
            "elapsed_seconds": elapsed_seconds,
            "adc_pair_rate_hz": validator.adc.items / elapsed_seconds,
            "gpio_sample_rate_hz": validator.gpio.items / elapsed_seconds,
            "payload_bytes_per_second": (
                validator.adc.payload_bytes + validator.gpio.payload_bytes
            )
            / elapsed_seconds,
            "framed_bytes_per_second": (
                validator.adc.framed_bytes + validator.gpio.framed_bytes
            )
            / elapsed_seconds,
        }
        for name, target in (
            ("adc_pair_rate_hz", ADC_PAIR_RATE_HZ),
            ("gpio_sample_rate_hz", GPIO_SAMPLE_RATE_HZ),
            (
                "payload_bytes_per_second",
                TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND,
            ),
        ):
            value = metrics[name]
            require(
                abs(value - target) / target <= RATE_TOLERANCE_FRACTION,
                "rate",
                f"fixture {name} is outside the accepted tolerance",
            )
        return {
            "result": "PASS",
            "failure_category": None,
            "parser": {
                "bytes_received": parser.bytes_received,
                "frames_decoded": parser.frames_decoded,
                "bytes_discarded": parser.bytes_discarded,
                "errors": parser.errors,
                "buffered_bytes": len(parser.buffer),
                "high_water_bytes": parser.high_water_bytes,
            },
            "frames": {
                "adc": validator.adc.frames,
                "gpio": validator.gpio.frames,
                "maximum_skew": validator.maximum_frame_skew,
            },
            "metrics": metrics,
        }
    except SoakFailure as error:
        return {
            "result": "FAIL",
            "failure_category": error.category,
            "parser": {
                "bytes_received": parser.bytes_received,
                "frames_decoded": parser.frames_decoded,
                "bytes_discarded": parser.bytes_discarded,
                "errors": parser.errors,
                "buffered_bytes": len(parser.buffer),
                "high_water_bytes": parser.high_water_bytes,
            },
        }


def soak_conformance_vector() -> dict[str, object]:
    """Return deterministic command, frame, metric, and grading evidence."""

    configuration = CONFIGURATION.pack(
        STREAM_BOTH,
        SOURCE_SYNTHETIC,
        CHECKSUM_ADLER32,
        0,
        DATA_FRAME_BYTES,
    )
    command_inputs = (
        (INFO_REQUEST, 1, b""),
        (CONFIGURE_REQUEST, 2, configuration),
        (START_REQUEST, 3, b""),
        (GET_STATUS_REQUEST, 4, b""),
        (STOP_REQUEST, 5, b""),
        (RESET_STATS_REQUEST, 6, b""),
    )
    commands = [
        {
            "kind": kind,
            "request_id": request_id,
            "size_bytes": len(wire),
            "sha256": hashlib.sha256(wire).hexdigest(),
        }
        for kind, request_id, payload in command_inputs
        for wire in (encode_request(kind, request_id, payload),)
    ]
    adc = _conformance_data_frame(ADC_DATA)
    gpio = _conformance_data_frame(GPIO_DATA)
    valid = adc + gpio
    latency = BoundedLatency()
    for sample in (0.001, 0.010, 0.050, 0.095, 0.099):
        latency.add(sample)
    grades = {
        "valid": _conformance_grade(valid),
        "checksum_corruption": _conformance_grade(
            _conformance_data_frame(ADC_DATA, corrupt_checksum=True) + gpio
        ),
        "pattern_error": _conformance_grade(
            _conformance_data_frame(ADC_DATA, corrupt_pattern=True) + gpio
        ),
        "source_gap": _conformance_grade(
            adc + _conformance_data_frame(GPIO_DATA, sequence=2, gap_before=True)
        ),
    }
    return {
        "schema_version": SOAK_CONFORMANCE_SCHEMA_VERSION,
        "commands": commands,
        "frames": {
            "transcript_bytes": len(valid),
            "transcript_sha256": hashlib.sha256(valid).hexdigest(),
            "chunk_pattern": [1, 7, 31, 257, DATA_FRAME_BYTES, 17],
        },
        "latency": latency.summary(),
        "grades": grades,
    }


def _positive_duration(value: str) -> float:
    try:
        duration = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("duration must be numeric") from error
    if (
        not math.isfinite(duration)
        or not 1.0 <= duration <= WINDOWS_MAXIMUM_DURATION_SECONDS
    ):
        raise argparse.ArgumentTypeError("duration must be between 1 and 86400 seconds")
    return duration


def _positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be numeric") from error
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 300.0:
        raise argparse.ArgumentTypeError("timeout must be between 0.1 and 300 seconds")
    return timeout


def _hardware_serial(value: str) -> int:
    try:
        result = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "hardware serial must be decimal or 0x-prefixed hexadecimal"
        ) from error
    if not 1 <= result <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("hardware serial must be a nonzero uint32")
    return result


def build_windows_parser() -> argparse.ArgumentParser:
    implementation = (
        "Installed-package"
        if GENERATED_CONFIG.get("entry_point") == "installed-package"
        else "Standalone"
    )
    parser = argparse.ArgumentParser(
        description=(
            f"{implementation}, release-identity-pinned ThingDAQ Windows soak validator"
        )
    )
    parser.add_argument(
        "--conformance-check",
        action="store_true",
        help="run the bounded deterministic protocol/validator self-check and exit",
    )
    parser.add_argument(
        "--mode",
        choices=("combined", "synthetic"),
        default="combined",
        help="combined physical acquisition (default) or firmware synthetic source",
    )
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument(
        "--duration",
        type=_positive_duration,
        default=WINDOWS_DEFAULT_DURATION_SECONDS,
        metavar="SECONDS",
        help="measured streaming duration (default: 3600)",
    )
    duration.add_argument(
        "--smoke",
        action="store_true",
        help="run the same validation semantics for a 10-second diagnostic smoke",
    )
    parser.add_argument(
        "--hardware-serial",
        type=_hardware_serial,
        help="select the pinned device deterministically across COM renumbering",
    )
    parser.add_argument(
        "--port",
        help="limit probing to this plausible enumerated COM port",
    )
    parser.add_argument(
        "--diagnostic-identity-override",
        action="store_true",
        help=(
            "allow a nonmatching firmware/device identity for diagnosis; every "
            "result is prominently marked non-release"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("thingdaq-windows-soak"),
        help="report path base; .json and .md are written (default shown)",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=_positive_timeout,
        default=WINDOWS_DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="total COM enumeration/probe deadline (default: 15)",
    )
    parser.add_argument(
        "--open-timeout",
        type=_positive_timeout,
        default=WINDOWS_DEFAULT_OPEN_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="per-COM serial-open deadline (default: 3)",
    )
    return parser


def windows_host_identity() -> dict[str, object]:
    win32 = platform.win32_ver()
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "win32_version": list(win32),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "pyserial_version": getattr(serial, "VERSION", None),
        "sys_platform": sys.platform,
    }


def _expected_settings(settings: RuntimeSettings) -> dict[str, object]:
    return {
        "protocol_version": settings.protocol_version,
        "checksum_algorithm": settings.checksum_algorithm,
        "checksum_name": settings.checksum_name,
        "firmware_version": list(settings.firmware_version),
        "build_id": settings.build_id,
        "source_id": settings.source_id,
        "artifact_name": settings.artifact_name,
        "artifact_sha256": settings.artifact_sha256,
        "fqbn": settings.fqbn,
        "hardware_serial": settings.hardware_serial,
        "board_id": settings.board_id,
        "mcu_id": settings.mcu_id,
        "validation_manifest_sha256": settings.validation_manifest_sha256,
    }


def windows_failure_result(
    error: BaseException,
    *,
    settings: RuntimeSettings | None,
    mode: str,
) -> dict[str, object]:
    message = str(error) or (
        "interrupted by Ctrl+C" if isinstance(error, KeyboardInterrupt) else "no detail"
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result": "FAIL",
        "mode": "physical-combined" if mode == "combined" else "synthetic",
        "failure": {
            "category": error.category if isinstance(error, SoakFailure) else "program",
            "type": type(error).__name__,
            "message": message,
        },
        "expected": _expected_settings(settings) if settings is not None else None,
        "observed_identity": None,
        "timing": (
            {
                "measured_duration_seconds": settings.measured_duration_seconds,
                "hard_deadline_seconds": settings.hard_deadline_seconds,
                "service_container_limit_seconds": (
                    settings.service_container_limit_seconds
                ),
            }
            if settings is not None
            else {}
        ),
        "metrics": {},
        "epochs": [],
        "cleanup": {"attempted": False, "normal_close": False},
        "program": {
            "sha256": _program_sha256(),
            "validator_sha256": (
                settings.validator_sha256 if settings is not None else None
            ),
            "candidate_sha256": (
                settings.candidate_sha256 if settings is not None else None
            ),
            "validation_manifest_sha256": (
                settings.validation_manifest_sha256 if settings is not None else None
            ),
            "python": sys.version.split()[0],
        },
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }


def _windows_validation_reasons(
    result: Mapping[str, object],
    *,
    diagnostic_identity_override: bool,
    identity_mismatches: Mapping[str, object],
    release_requirements: Mapping[str, bool],
    process_rss: Mapping[str, object],
) -> list[str]:
    reasons: list[str] = []
    if diagnostic_identity_override:
        reasons.append(
            "NON-RELEASE: --diagnostic-identity-override was supplied; this "
            "result cannot support a release claim"
        )
        if identity_mismatches:
            reasons.append(
                "the observed INFO identity/capabilities differ from the pinned "
                "Phase 11 validation manifest"
            )
    if not release_requirements["native_windows_host"]:
        reasons.append(
            "NON-RELEASE: native Windows host identity is required "
            '(system == "Windows" and sys_platform == "win32")'
        )
    if not all(
        release_requirements[name]
        for name in (
            "physical_combined_mode",
            "exact_3600_second_duration",
            "non_smoke",
        )
    ):
        reasons.append(
            "NON-RELEASE: the release profile requires an exact 3,600-second "
            "non-smoke physical-combined run"
        )
    rss_validity_requirements = (
        "process_rss_baseline_valid",
        "process_rss_peak_valid",
        "process_rss_growth_valid",
    )
    if not all(release_requirements[name] for name in rss_validity_requirements):
        rss_values = {
            name: process_rss.get(name)
            for name in ("baseline_bytes", "peak_bytes", "growth_bytes")
        }
        unavailable = any(value is None for value in rss_values.values())
        reasons.append(
            "NON-RELEASE: complete numeric process-RSS evidence is "
            + ("unavailable" if unavailable else "invalid")
            + "; baseline_bytes, peak_bytes, and growth_bytes must be finite "
            "nonnegative numbers"
        )
    elif not release_requirements["process_rss_growth_within_limit"]:
        reasons.append(
            "NON-RELEASE: process-RSS growth "
            f"{process_rss.get('growth_bytes')} exceeds "
            f"{MAX_RSS_GROWTH_BYTES} bytes"
        )
    if not release_requirements["exact_manifest_device_identity"]:
        reasons.append(
            "NON-RELEASE: exact validation-manifest and device identity "
            "evidence is required"
        )
    if result.get("result") != "PASS":
        failure = result.get("failure")
        if isinstance(failure, Mapping):
            reasons.append(
                f"{failure.get('category', 'failure')}: "
                f"{failure.get('message', 'no detail')}"
            )
            return reasons
        reasons.append("validation did not pass")
        return reasons
    reasons.extend(
        [
            (
                "COM metadata and two stable INFO responses matched the pinned identity"
                if release_requirements["exact_manifest_device_identity"]
                else "COM metadata and two stable INFO responses identified one stable "
                "diagnostic device"
            ),
            "every decoded frame passed structure and Adler-32 validation",
            "run IDs, independent sequences, timestamps, counts, and rates reconciled",
            "live and final STATUS counters and bounded queue depths reconciled",
            "command latency requirements passed",
            "STOP reached IDLE and the serial close completed within its deadline",
        ]
    )
    if all(
        release_requirements[name]
        for name in (
            *rss_validity_requirements,
            "process_rss_growth_within_limit",
        )
    ):
        reasons.append(
            "complete numeric process-RSS evidence remained within its growth limit"
        )
    return reasons


def _is_nonnegative_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _windows_release_requirements(
    result: Mapping[str, object],
    *,
    arguments: argparse.Namespace,
    duration: float,
    host: Mapping[str, object],
    exact_manifest_device_identity: bool,
    process_rss: Mapping[str, object],
) -> dict[str, bool]:
    baseline = process_rss.get("baseline_bytes")
    peak = process_rss.get("peak_bytes")
    growth = process_rss.get("growth_bytes")
    growth_valid = _is_nonnegative_finite_number(growth)
    growth_within_limit = (
        growth_valid
        and isinstance(growth, (int, float))
        and growth <= MAX_RSS_GROWTH_BYTES
    )
    return {
        "physical_combined_mode": arguments.mode == "combined",
        "exact_3600_second_duration": duration == WINDOWS_DEFAULT_DURATION_SECONDS,
        "non_smoke": not bool(arguments.smoke),
        "diagnostic_identity_override_disabled": not bool(
            arguments.diagnostic_identity_override
        ),
        "native_windows_host": (
            host.get("system") == "Windows" and host.get("sys_platform") == "win32"
        ),
        "overall_pass": result.get("result") == "PASS",
        "exact_manifest_device_identity": exact_manifest_device_identity,
        "process_rss_baseline_valid": _is_nonnegative_finite_number(baseline),
        "process_rss_peak_valid": _is_nonnegative_finite_number(peak),
        "process_rss_growth_valid": growth_valid,
        "process_rss_growth_within_limit": growth_within_limit,
    }


def attach_windows_evidence(
    result: dict[str, object],
    *,
    arguments: argparse.Namespace,
    duration: float,
    candidates: tuple[WindowsPortCandidate, ...],
    probes: tuple[WindowsProbeResult, ...],
    selected: WindowsPortCandidate | None,
    lifecycle: list[dict[str, object]],
) -> None:
    diagnostic_override = bool(arguments.diagnostic_identity_override)
    host = windows_host_identity()
    selected_probe = next(
        (
            probe
            for probe in probes
            if selected is not None and probe.candidate == selected and probe.passed
        ),
        None,
    )
    identity_mismatches = (
        selected_probe.identity_mismatches if selected_probe is not None else {}
    )
    generated_manifest = GENERATED_CONFIG.get("validation_manifest")
    manifest_map = generated_manifest if isinstance(generated_manifest, Mapping) else {}
    manifest_expected = manifest_map.get("expected_info")
    manifest_expected_map = (
        manifest_expected if isinstance(manifest_expected, Mapping) else {}
    )
    expected = result.get("expected")
    expected_map = expected if isinstance(expected, Mapping) else {}
    program = result.get("program")
    program_map = program if isinstance(program, Mapping) else {}
    manifest_sha256 = GENERATED_CONFIG.get("validation_manifest_sha256")
    release_identity_match = (
        selected_probe is not None
        and not identity_mismatches
        and bool(manifest_expected_map)
        and isinstance(manifest_sha256, str)
        and len(manifest_sha256) == 64
        and selected_probe.observed_identity == dict(manifest_expected_map)
        and expected_map.get("validation_manifest_sha256") == manifest_sha256
        and program_map.get("validation_manifest_sha256") == manifest_sha256
    )
    metrics = result.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    memory = metrics_map.get("memory")
    memory_map = memory if isinstance(memory, Mapping) else {}
    process_rss_value = memory_map.get("process_rss")
    process_rss = process_rss_value if isinstance(process_rss_value, Mapping) else {}
    release_requirements = _windows_release_requirements(
        result,
        arguments=arguments,
        duration=duration,
        host=host,
        exact_manifest_device_identity=release_identity_match,
        process_rss=process_rss,
    )
    release_profile = all(
        release_requirements[name] for name in _WINDOWS_RELEASE_PROFILE_REQUIREMENTS
    )
    result["report_schema_version"] = WINDOWS_REPORT_SCHEMA_VERSION
    result["windows"] = {
        "profile": (
            "diagnostic-identity-override"
            if diagnostic_override
            else ("release" if release_profile else "diagnostic")
        ),
        "release_eligible": all(release_requirements.values()),
        "release_requirements": release_requirements,
        "diagnostic_identity_override": {
            "requested": diagnostic_override,
            "release_eligible": False if diagnostic_override else None,
            "identity_mismatches": identity_mismatches,
        },
        "requested_mode": arguments.mode,
        "requested_duration_seconds": duration,
        "smoke": bool(arguments.smoke),
        "requested_hardware_serial": arguments.hardware_serial,
        "explicit_port": arguments.port,
        "host": host,
        "com_discovery": {
            "teensy_vid": TEENSY_USB_SERIAL_VID,
            "teensy_pid": TEENSY_USB_SERIAL_PID,
            "preferred_product": THINGDAQ_PRODUCT,
            "candidate_count": len(candidates),
            "candidates": [candidate.as_dict() for candidate in candidates],
            "probes": [probe.as_dict() for probe in probes],
            "selected": selected.as_dict() if selected is not None else None,
            "selected_release_identity_match": release_identity_match,
        },
        "serial_lifecycle": lifecycle,
        "generation": {
            "entry_point": GENERATED_CONFIG.get("entry_point"),
            "generator_schema_version": GENERATED_CONFIG.get(
                "generator_schema_version"
            ),
            "windows_driver_sha256": GENERATED_CONFIG.get("windows_driver_sha256"),
            "windows_profile_sha256": GENERATED_CONFIG.get("windows_profile_sha256"),
            "validation_manifest_sha256": GENERATED_CONFIG.get(
                "validation_manifest_sha256"
            ),
        },
        "validation_manifest": {
            "schema_version": manifest_map.get("schema_version"),
            "kind": manifest_map.get("kind"),
            "related": manifest_map.get("related"),
            "semantic_sha256": GENERATED_CONFIG.get("validation_manifest_sha256"),
        },
        "validation_reasons": _windows_validation_reasons(
            result,
            diagnostic_identity_override=diagnostic_override,
            identity_mismatches=identity_mismatches,
            release_requirements=release_requirements,
            process_rss=process_rss,
        ),
    }


def _mark_close_failure(
    result: dict[str, object],
    lifecycle: list[dict[str, object]],
) -> bool:
    failed = any(
        not item.get("attempted")
        or not item.get("completed")
        or item.get("timed_out")
        or item.get("error") is not None
        for item in lifecycle
    )
    if not failed or result.get("result") != "PASS":
        return failed
    result["result"] = "FAIL"
    result["failure"] = {
        "category": "cleanup",
        "type": "SerialCloseError",
        "message": f"serial close did not complete cleanly: {lifecycle}",
    }
    cleanup = result.get("cleanup")
    if isinstance(cleanup, dict):
        cleanup["normal_close"] = False
        cleanup["serial_lifecycle"] = lifecycle
    return True


def _markdown_cell(value: object) -> str:
    if value is None:
        return "n/a"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _metric(value: object, *, scale: float = 1.0, digits: int = 3) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "n/a"
    return f"{float(value) * scale:.{digits}f}"


def render_windows_markdown(result: Mapping[str, object]) -> str:
    completed = result.get("completed_utc")
    created = (
        str(completed)[:10]
        if isinstance(completed, str) and len(completed) >= 10
        else datetime.now(timezone.utc).date().isoformat()
    )
    windows = result.get("windows")
    windows_map = windows if isinstance(windows, Mapping) else {}
    override = windows_map.get("diagnostic_identity_override")
    override_map = override if isinstance(override, Mapping) else {}
    override_requested = override_map.get("requested") is True
    raw_mismatches = override_map.get("identity_mismatches")
    mismatch_map = raw_mismatches if isinstance(raw_mismatches, Mapping) else {}
    mismatch_lines = [
        (
            f"| {_markdown_cell(name)} | "
            f"{_markdown_cell(values.get('expected'))} | "
            f"{_markdown_cell(values.get('actual'))} |"
        )
        for name, raw_values in sorted(mismatch_map.items())
        for values in ([raw_values] if isinstance(raw_values, Mapping) else [{}])
    ] or ["| None | n/a | n/a |"]
    override_warning = (
        [
            "> [!WARNING]",
            (
                "> `--diagnostic-identity-override` was supplied. This report is "
                "**NON-RELEASE** regardless of PASS/FAIL; it does not validate the "
                "accepted Phase 11 firmware/device identity."
            ),
            "",
        ]
        if override_requested
        else []
    )
    discovery = windows_map.get("com_discovery")
    discovery_map = discovery if isinstance(discovery, Mapping) else {}
    selected = discovery_map.get("selected")
    selected_map = selected if isinstance(selected, Mapping) else {}
    host = windows_map.get("host")
    host_map = host if isinstance(host, Mapping) else {}
    expected = result.get("expected")
    expected_map = expected if isinstance(expected, Mapping) else {}
    observed = result.get("observed_identity")
    observed_map = observed if isinstance(observed, Mapping) else {}
    metrics = result.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    latency = metrics_map.get("latency")
    latency_map = latency if isinstance(latency, Mapping) else {}
    status_latency = latency_map.get("status")
    status_latency_map = status_latency if isinstance(status_latency, Mapping) else {}
    command_latency = latency_map.get("all_commands")
    command_latency_map = (
        command_latency if isinstance(command_latency, Mapping) else {}
    )
    memory = metrics_map.get("memory")
    memory_map = memory if isinstance(memory, Mapping) else {}
    traced = memory_map.get("tracemalloc")
    traced_map = traced if isinstance(traced, Mapping) else {}
    rss = memory_map.get("process_rss")
    rss_map = rss if isinstance(rss, Mapping) else {}
    failure = result.get("failure")
    failure_map = failure if isinstance(failure, Mapping) else {}
    reasons = windows_map.get("validation_reasons")
    reason_lines = (
        [f"- {_markdown_cell(reason)}" for reason in reasons]
        if isinstance(reasons, list)
        else ["- Validation detail unavailable"]
    )
    epochs = result.get("epochs")
    epoch = epochs[0] if isinstance(epochs, list) and epochs else {}
    epoch_map = epoch if isinstance(epoch, Mapping) else {}
    counters = epoch_map.get("final_counters")
    counter_map = counters if isinstance(counters, Mapping) else {}
    parser = epoch_map.get("parser")
    parser_map = parser if isinstance(parser, Mapping) else {}
    counter_lines = [
        f"| {_markdown_cell(name)} | {_markdown_cell(value)} |"
        for name, value in sorted(counter_map.items())
    ] or ["| n/a | n/a |"]
    raw_json = json.dumps(result, indent=2, sort_keys=True)
    return "\n".join(
        [
            "---",
            "type: report",
            "title: ThingDAQ Windows Soak Report",
            f"created: {created}",
            "tags:",
            "  - thingdaq",
            "  - windows",
            "  - soak-validation",
            "related:",
            "  - '[[Phase-11-Soak-Evidence]]'",
            "  - '[[Quickstart]]'",
            "  - '[[Hardware-Safety]]'",
            "  - '[[Protocol-V1]]'",
            "---",
            "",
            "# ThingDAQ Windows soak report",
            "",
            *override_warning,
            "## Outcome",
            "",
            (
                f"**{_markdown_cell(result.get('result'))}"
                f"{' (NON-RELEASE DIAGNOSTIC)' if override_requested else ''}** — "
                f"{_markdown_cell(failure_map.get('category', 'all checks passed'))}: "
                f"{_markdown_cell(failure_map.get('message', 'validation completed'))}"
            ),
            "",
            *reason_lines,
            "",
            "| Run property | Value |",
            "| --- | --- |",
            f"| Profile | {_markdown_cell(windows_map.get('profile'))} |",
            f"| Release eligible | {_markdown_cell(windows_map.get('release_eligible'))} |",
            f"| Diagnostic identity override | {_markdown_cell(override_requested)} |",
            f"| Mode | {_markdown_cell(result.get('mode'))} |",
            f"| Requested duration (s) | {_markdown_cell(windows_map.get('requested_duration_seconds'))} |",
            f"| Completed UTC | {_markdown_cell(completed)} |",
            "",
            "## Host, COM, and device identity",
            "",
            "| Identity | Value |",
            "| --- | --- |",
            f"| Hostname | {_markdown_cell(host_map.get('hostname'))} |",
            f"| Platform | {_markdown_cell(host_map.get('platform'))} |",
            f"| Python | {_markdown_cell(host_map.get('python_implementation'))} {_markdown_cell(host_map.get('python_version'))} |",
            f"| PySerial | {_markdown_cell(host_map.get('pyserial_version'))} |",
            f"| COM port | {_markdown_cell(selected_map.get('port'))} |",
            f"| USB VID:PID | {_markdown_cell(selected_map.get('vid_pid'))} |",
            f"| USB product | {_markdown_cell(selected_map.get('product'))} |",
            f"| USB serial | {_markdown_cell(selected_map.get('serial_number'))} |",
            f"| INFO hardware serial | {_markdown_cell(observed_map.get('hardware_serial'))} |",
            f"| Firmware version | {_markdown_cell(observed_map.get('firmware_version'))} |",
            f"| Build ID | {_markdown_cell(observed_map.get('build_id'))} |",
            f"| Expected source ID | {_markdown_cell(expected_map.get('source_id'))} |",
            f"| Expected HEX SHA-256 | {_markdown_cell(expected_map.get('artifact_sha256'))} |",
            f"| Validation manifest SHA-256 | {_markdown_cell(expected_map.get('validation_manifest_sha256'))} |",
            "",
            "## Release identity comparison",
            "",
            "| INFO field | Expected | Actual |",
            "| --- | --- | --- |",
            *mismatch_lines,
            "",
            "## Rates, latency, and memory",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Payload B/s | {_metric(metrics_map.get('payload_bytes_per_streaming_second'))} |",
            f"| Framed B/s | {_metric(metrics_map.get('framed_bytes_per_streaming_second'))} |",
            f"| ADC pairs/s | {_metric(metrics_map.get('adc_pair_rate_hz'))} |",
            f"| GPIO samples/s | {_metric(metrics_map.get('gpio_sample_rate_hz'))} |",
            f"| STATUS p99 (ms) | {_metric(status_latency_map.get('p99_seconds'), scale=1_000.0)} |",
            f"| STATUS maximum (ms) | {_metric(status_latency_map.get('maximum_seconds'), scale=1_000.0)} |",
            f"| Any-command maximum (ms) | {_metric(command_latency_map.get('maximum_seconds'), scale=1_000.0)} |",
            f"| Tracemalloc growth (bytes) | {_markdown_cell(traced_map.get('growth_bytes'))} |",
            f"| Process RSS growth (bytes) | {_markdown_cell(rss_map.get('growth_bytes'))} |",
            f"| Parser bytes / frames | {_markdown_cell(parser_map.get('bytes_received'))} / {_markdown_cell(parser_map.get('frames_decoded'))} |",
            f"| Parser errors / retained bytes | {_markdown_cell(parser_map.get('errors'))} / {_markdown_cell(parser_map.get('buffered_bytes'))} |",
            "",
            "## Final firmware counters",
            "",
            "| Counter | Value |",
            "| --- | ---: |",
            *counter_lines,
            "",
            "## Complete machine-readable record",
            "",
            "```json",
            raw_json,
            "```",
            "",
        ]
    )


def _report_paths(base: Path) -> tuple[Path, Path]:
    if base.suffix.casefold() in {".json", ".md"}:
        base = base.with_suffix("")
    return Path(f"{base}.json"), Path(f"{base}.md")


def _atomic_text_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_windows_reports(
    base: Path,
    result: dict[str, object],
) -> tuple[Path, Path]:
    json_path, markdown_path = _report_paths(base)
    windows = result.get("windows")
    if isinstance(windows, dict):
        windows["reports"] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }
    _atomic_text_write(
        json_path,
        json.dumps(result, indent=2, sort_keys=True) + "\n",
    )
    _atomic_text_write(markdown_path, render_windows_markdown(result))
    return json_path, markdown_path


def _windows_emit_event(name: str, **fields: object) -> None:
    if name == "sync_retry":
        print(
            f"Synchronization retry {fields.get('attempt')}: {fields.get('error')}",
            flush=True,
        )
    elif name == "synchronized":
        print(
            f"Identity synchronized in {fields.get('attempts')} attempt(s)", flush=True
        )
    elif name == "warmup_complete":
        print("Warm-up complete; measured validation started", flush=True)
    elif name == "status_checkpoint":
        elapsed = fields.get("elapsed_seconds")
        planned = fields.get("planned_seconds")
        percent = (
            min(100.0, 100.0 * float(elapsed) / float(planned))
            if isinstance(elapsed, (int, float))
            and isinstance(planned, (int, float))
            and planned > 0
            else 0.0
        )
        print(
            f"Progress {percent:5.1f}% | "
            f"ADC frames {fields.get('adc_frames')} | "
            f"GPIO frames {fields.get('gpio_frames')} | "
            f"STATUS {fields.get('status_count')}",
            flush=True,
        )
    elif name == "epoch_complete":
        measured = fields.get("measured_elapsed_seconds")
        measured_seconds = (
            float(measured)
            if isinstance(measured, (int, float)) and not isinstance(measured, bool)
            else 0.0
        )
        print(
            f"Stream complete: {measured_seconds:.3f}s, "
            f"{fields.get('payload_bytes')} payload bytes",
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    arguments = build_windows_parser().parse_args(argv)
    if arguments.conformance_check:
        print(
            SOAK_CONFORMANCE_PREFIX
            + json.dumps(
                soak_conformance_vector(),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    duration = (
        WINDOWS_SMOKE_DURATION_SECONDS if arguments.smoke else float(arguments.duration)
    )
    settings: RuntimeSettings | None = None
    candidates: tuple[WindowsPortCandidate, ...] = ()
    probes: tuple[WindowsProbeResult, ...] = ()
    selected: WindowsPortCandidate | None = None
    factory: WindowsPortFactory | None = None
    exit_code = 2
    try:
        settings = windows_runtime_settings(
            arguments.mode,
            duration,
            diagnostic_identity_override=arguments.diagnostic_identity_override,
        )
        if arguments.diagnostic_identity_override:
            print(
                "WARNING: diagnostic identity override enabled; every outcome is "
                "NON-RELEASE and cannot validate the Phase 11 candidate identity",
                flush=True,
            )
        requested_serial = (
            settings.hardware_serial
            if arguments.hardware_serial is None
            else arguments.hardware_serial
        )
        if (
            requested_serial != settings.hardware_serial
            and not arguments.diagnostic_identity_override
        ):
            raise SoakFailure(
                "identity",
                f"this release validator is pinned to hardware serial "
                f"{settings.hardware_serial}; requested {requested_serial}",
            )
        arguments.hardware_serial = requested_serial
        print(
            f"Scanning for ThingDAQ {TEENSY_USB_SERIAL_VID:04X}:"
            f"{TEENSY_USB_SERIAL_PID:04X} COM ports...",
            flush=True,
        )
        candidates = enumerate_windows_candidates()
        if arguments.port is not None:
            candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.port.casefold() == arguments.port.casefold()
            )
            if not candidates:
                raise SoakFailure(
                    "discovery",
                    f"{arguments.port!r} is not an enumerated plausible Teensy COM port",
                )
        if not candidates:
            raise SoakFailure(
                "discovery",
                "no COM ports matched Teensy USB Serial VID/PID metadata",
            )
        probes = probe_windows_candidates(
            candidates,
            settings,
            discovery_timeout_seconds=arguments.discovery_timeout,
            open_timeout_seconds=arguments.open_timeout,
        )
        selected = select_windows_candidate(
            probes,
            hardware_serial=requested_serial,
        )
        print(
            f"Selected {selected.port} by INFO hardware serial {requested_serial}; "
            f"starting {duration:g}s {arguments.mode} validation",
            flush=True,
        )
        factory = WindowsPortFactory(
            selected,
            open_timeout_seconds=arguments.open_timeout,
        )
        global emit_event
        emit_event = _windows_emit_event
        exit_code, result = run_generated(settings, factory)
        lifecycle = factory.summary()
        if _mark_close_failure(result, lifecycle):
            exit_code = 1
    except BaseException as error:  # noqa: BLE001 - all exits receive reports
        result = windows_failure_result(
            error,
            settings=settings,
            mode=arguments.mode,
        )
        lifecycle = factory.summary() if factory is not None else []
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 2
    attach_windows_evidence(
        result,
        arguments=arguments,
        duration=duration,
        candidates=candidates,
        probes=probes,
        selected=selected,
        lifecycle=lifecycle,
    )
    try:
        json_path, markdown_path = write_windows_reports(arguments.output, result)
    except BaseException as error:  # noqa: BLE001 - report failure must be explicit
        print(
            f"FAIL report_write: {type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 3
    failure = result.get("failure")
    failure_map = failure if isinstance(failure, Mapping) else {}
    if result.get("result") == "PASS":
        pass_label = (
            "PASS (NON-RELEASE DIAGNOSTIC IDENTITY OVERRIDE)"
            if arguments.diagnostic_identity_override
            else "PASS"
        )
        print(f"{pass_label} | JSON {json_path} | Markdown {markdown_path}", flush=True)
    else:
        print(
            f"FAIL {failure_map.get('category', 'validation')}: "
            f"{failure_map.get('message', 'no detail')} | "
            f"JSON {json_path} | Markdown {markdown_path}",
            flush=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
# </soak-cli>
