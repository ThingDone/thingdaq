#!/usr/bin/env python3
"""Generate protocol-v1 constants and deterministic golden frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
PYTHON_OUTPUT_PATH = (
    REPOSITORY_ROOT / "daq_api/src/teensy_daq/_generated/protocol_constants.py"
)
CPP_OUTPUT_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_constants.h"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
MANIFEST_PATH = FIXTURE_DIRECTORY / "manifest.json"

INTEGER_FORMATS = {
    "u8": "B",
    "u16": "H",
    "u32": "I",
    "u64": "Q",
}
INTEGER_WIDTHS = {
    "u8": 1,
    "u16": 2,
    "u32": 4,
    "u64": 8,
}


class ContractError(ValueError):
    """Raised when the canonical source is internally inconsistent."""


def load_contract() -> tuple[dict[str, Any], bytes]:
    """Read the canonical JSON source and return it with its exact bytes."""

    source_bytes = SOURCE_PATH.read_bytes()
    contract = json.loads(source_bytes)
    if not isinstance(contract, dict):
        raise ContractError("protocol source root must be a JSON object")
    return contract, source_bytes


def enum_map(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Convert a list of named numeric entries to a validated mapping."""

    result: dict[str, int] = {}
    used_values: set[int] = set()
    for entry in entries:
        name = str(entry["name"])
        value = int(entry["value"])
        if name in result:
            raise ContractError(f"duplicate enum name: {name}")
        if value in used_values:
            raise ContractError(f"duplicate enum value {value} in {entries!r}")
        result[name] = value
        used_values.add(value)
    return result


def validate_enum_width(
    owner: str, entries: Sequence[Mapping[str, Any]], bits: int
) -> None:
    """Require every enum value to fit its declared unsigned wire width."""

    maximum = (1 << bits) - 1
    for entry in entries:
        value = int(entry["value"])
        if not 0 <= value <= maximum:
            raise ContractError(
                f"{owner}.{entry['name']}={value} does not fit unsigned {bits} bits"
            )


def field_width(field: Mapping[str, Any]) -> int:
    """Return the encoded width for a machine-readable field definition."""

    field_type = str(field["type"])
    if field_type in INTEGER_WIDTHS:
        return INTEGER_WIDTHS[field_type]
    if field_type in {"bytes", "nul_ascii", "u8_array"}:
        return int(field["count"])
    if field_type == "repeated_u16_pair":
        return int(field["count"]) * 4
    raise ContractError(f"unsupported field type: {field_type}")


def validate_fields(owner: str, size: int, fields: Sequence[Mapping[str, Any]]) -> None:
    """Require fields to cover their declared byte region exactly once."""

    occupancy: list[str | None] = [None] * size
    for field in fields:
        name = str(field["name"])
        offset = int(field["offset"])
        width = field_width(field)
        if offset < 0 or width < 0 or offset + width > size:
            raise ContractError(
                f"{owner}.{name} at {offset}+{width} exceeds declared size {size}"
            )
        for index in range(offset, offset + width):
            previous = occupancy[index]
            if previous is not None:
                raise ContractError(
                    f"{owner}.{name} overlaps {previous} at byte {index}"
                )
            occupancy[index] = name
    gaps = [index for index, field_name in enumerate(occupancy) if field_name is None]
    if gaps:
        raise ContractError(f"{owner} has uncovered bytes: {gaps}")


def validate_contract(contract: Mapping[str, Any]) -> None:
    """Validate cross-field invariants before generating any output."""

    if contract["byte_order"] != "little":
        raise ContractError("protocol v1 must use explicit little-endian encoding")
    if int(contract["magic"]) != 0xDEADBEEF:
        raise ContractError("protocol v1 magic must be 0xDEADBEEF")
    if int(contract["protocol_version"]) != 1:
        raise ContractError("this generator only accepts protocol version 1")

    scalar_types = contract["scalar_types"]
    if set(scalar_types) != set(INTEGER_WIDTHS):
        raise ContractError("scalar type table must define u8, u16, u32, and u64")
    for name, width in INTEGER_WIDTHS.items():
        scalar = scalar_types[name]
        if int(scalar["width"]) != width or scalar["signed"] is not False:
            raise ContractError(f"{name} must be an unsigned {width}-byte scalar")

    header = contract["header"]
    header_size = int(header["size"])
    validate_fields("header", header_size, header["fields"])

    trailer = contract["trailer"]
    trailer_size = int(trailer["size"])
    if trailer_size != 4 or trailer["type"] != "u32":
        raise ContractError("the v1 trailer must be one little-endian uint32")

    limits = contract["limits"]
    data_frame_bytes = int(limits["data_frame_bytes"])
    max_data_frame_bytes = int(limits["max_data_frame_bytes"])
    min_frame_bytes = int(limits["min_frame_bytes"])
    max_control_frame_bytes = int(limits["max_control_frame_bytes"])
    max_command_frame_bytes = int(limits["max_command_frame_bytes"])
    max_command_payload_bytes = int(limits["max_command_payload_bytes"])
    if data_frame_bytes != 4096:
        raise ContractError("v1 data frames must be exactly 4096 bytes")
    if max_data_frame_bytes != data_frame_bytes:
        raise ContractError("the fixed data frame must also be the maximum data frame")
    if min_frame_bytes != header_size + trailer_size:
        raise ContractError("minimum frame size must equal header plus trailer")
    if max_control_frame_bytes > data_frame_bytes:
        raise ContractError("control-frame bound must not exceed a data frame")
    if max_command_frame_bytes != min_frame_bytes + max_command_payload_bytes:
        raise ContractError("command frame and payload limits are inconsistent")
    if max_command_frame_bytes > max_control_frame_bytes:
        raise ContractError("command-frame bound must fit inside the control bound")

    data_payload_bytes = data_frame_bytes - header_size - trailer_size
    layouts = contract["data_layouts"]
    adc = layouts["adc"]
    gpio = layouts["gpio"]
    if int(adc["payload_bytes"]) != data_payload_bytes:
        raise ContractError("ADC payload does not fill the fixed data frame")
    if int(gpio["payload_bytes"]) != data_payload_bytes:
        raise ContractError("GPIO payload does not fill the fixed data frame")
    if int(adc["items_per_frame"]) * int(adc["bytes_per_item"]) != data_payload_bytes:
        raise ContractError("ADC item count and width do not fill its payload")
    if int(gpio["items_per_frame"]) * int(gpio["bytes_per_item"]) != data_payload_bytes:
        raise ContractError("GPIO item count and width do not fill its payload")

    timing = contract["timing"]
    adc_coverage = int(adc["items_per_frame"]) * int(timing["adc_pair_period_ticks"])
    gpio_coverage = int(gpio["items_per_frame"]) * int(
        timing["gpio_sample_period_ticks"]
    )
    if adc_coverage != gpio_coverage:
        raise ContractError("ADC and GPIO frames must cover equal nominal time")

    benchmark = contract["checksum_benchmark"]
    positive_benchmark_fields = (
        "cycle_counter_hz",
        "target_framed_bytes_per_second",
        "max_batch_count",
        "max_iterations_per_batch",
        "max_operations",
        "max_processed_bytes",
        "timer_calibration_samples",
        "warmup_operations",
    )
    if any(int(benchmark[name]) <= 0 for name in positive_benchmark_fields):
        raise ContractError("checksum benchmark bounds must all be positive")
    if int(benchmark["cycle_counter_hz"]) != 600_000_000:
        raise ContractError("checksum benchmark DWT frequency must be 600 MHz")
    if int(benchmark["max_batch_count"]) * int(
        benchmark["max_iterations_per_batch"]
    ) > int(benchmark["max_operations"]):
        raise ContractError("checksum benchmark batch bounds exceed operation bound")

    gpio_clock = contract["gpio_clock_diagnostic"]
    positive_gpio_clock_fields = (
        "pit_clock_hz",
        "cycle_counter_hz",
        "production_rate_hz",
        "minimum_rate_hz",
        "minimum_event_count",
        "maximum_event_count",
        "maximum_elapsed_cycles",
        "duplicate_guard_events",
        "count_tolerance",
    )
    if any(int(gpio_clock[name]) <= 0 for name in positive_gpio_clock_fields):
        raise ContractError("GPIO clock diagnostic bounds must all be positive")
    if int(gpio_clock["production_rate_hz"]) != int(timing["gpio_sample_rate_hz"]):
        raise ContractError(
            "GPIO clock production rate must equal advertised GPIO timing"
        )
    if int(gpio_clock["pit_clock_hz"]) % int(gpio_clock["production_rate_hz"]):
        raise ContractError("GPIO production rate must divide the PIT clock exactly")
    if int(gpio_clock["minimum_rate_hz"]) > int(gpio_clock["production_rate_hz"]):
        raise ContractError("GPIO diagnostic minimum exceeds production rate")
    if int(gpio_clock["minimum_event_count"]) > int(gpio_clock["maximum_event_count"]):
        raise ContractError("GPIO diagnostic event-count bounds are inverted")
    maximum_major_count = 2 * int(gpio_clock["maximum_event_count"]) + int(
        gpio_clock["duplicate_guard_events"]
    )
    if maximum_major_count > 0x7FFF:
        raise ContractError("GPIO diagnostic eDMA major count exceeds ELINKNO width")

    adc_initialization = contract["adc_initialization"]
    positive_adc_fields = (
        "primary_resolution_bits",
        "fallback_resolution_bits",
        "container_bits",
        "reference_mv_nominal",
        "input_max_mv_nominal",
        "ipg_clock_hz",
        "adc_clock_hz",
        "clock_divider",
        "sample_time_adck",
        "calibration_cycle_counter_hz",
        "calibration_deadline_us",
        "calibration_poll_limit",
    )
    if any(int(adc_initialization[name]) <= 0 for name in positive_adc_fields):
        raise ContractError("ADC initialization bounds must be positive")
    if (
        int(adc_initialization["primary_resolution_bits"])
        != int(adc["resolution_bits"])
        or int(adc_initialization["fallback_resolution_bits"]) != 10
        or int(adc_initialization["container_bits"]) != int(adc["container_bits"])
        or int(adc_initialization["code_min"]) != 0
        or int(adc_initialization["input_min_mv_nominal"]) != 0
    ):
        raise ContractError("ADC initialization resolution/range contract disagrees")
    if int(adc_initialization["adc_clock_hz"]) * int(
        adc_initialization["clock_divider"]
    ) != int(adc_initialization["ipg_clock_hz"]):
        raise ContractError("ADC clock and divisor do not reconstruct the IPG root")
    if int(adc_initialization["hardware_average_count"]) != 0:
        raise ContractError("ADC hardware averaging must remain disabled")
    if (
        list(adc_initialization["pins"]) != [14, 15]
        or list(adc_initialization["peripherals"]) != [1, 2]
        or list(adc_initialization["channels"]) != [7, 8]
    ):
        raise ContractError("ADC route metadata must remain A0/ADC1 and A1/ADC2")
    deadline_cycles = (
        int(adc_initialization["calibration_cycle_counter_hz"])
        * int(adc_initialization["calibration_deadline_us"])
        // 1_000_000
    )
    if not 0 < deadline_cycles <= 0xFFFFFFFF:
        raise ContractError("ADC calibration deadline must fit one DWT interval")

    flag_values = enum_map(contract["flags"])
    validate_enum_width("flags", contract["flags"], 16)
    if any(value == 0 or value & (value - 1) for value in flag_values.values()):
        raise ContractError("every named frame flag must be one nonzero bit")
    capability_values = enum_map(contract["enums"]["capability_bits"])
    validate_enum_width("capability_bits", contract["enums"]["capability_bits"], 32)
    if any(value == 0 or value & (value - 1) for value in capability_values.values()):
        raise ContractError("every named capability must be one nonzero bit")
    gpio_clock_error_values = enum_map(contract["enums"]["gpio_clock_error"])
    validate_enum_width("gpio_clock_error", contract["enums"]["gpio_clock_error"], 32)
    if any(
        value == 0 or value & (value - 1) for value in gpio_clock_error_values.values()
    ):
        raise ContractError("every GPIO clock error must be one nonzero bit")
    for enum_name in ("adc_configuration_flag", "adc_initialization_error"):
        values = enum_map(contract["enums"][enum_name])
        validate_enum_width(enum_name, contract["enums"][enum_name], 32)
        if any(value == 0 or value & (value - 1) for value in values.values()):
            raise ContractError(f"every {enum_name} value must be one nonzero bit")

    checksums = enum_map(contract["checksum_algorithms"])
    validate_enum_width("checksum_algorithms", contract["checksum_algorithms"], 8)
    enabled_checksums = {
        str(entry["name"])
        for entry in contract["checksum_algorithms"]
        if bool(entry["enabled_in_v1"])
    }
    if checksums.get("NONE_RESERVED") != 0:
        raise ContractError("checksum algorithm zero must remain invalid/reserved")
    if checksums.get("ADLER32") != 1 or "ADLER32" not in enabled_checksums:
        raise ContractError("Adler-32 must be the enabled bootstrap checksum")
    if checksums.get("CRC32C") != 2:
        raise ContractError("CRC-32C must retain protocol checksum ID 2")
    if checksums.get("CRC32_ISO_HDLC") != 3:
        raise ContractError("CRC-32/ISO-HDLC must retain protocol checksum ID 3")
    if any(checksums[name] >= 32 for name in enabled_checksums):
        raise ContractError("enabled checksum IDs must fit the uint32 capability mask")
    bootstrap_checksum = contract.get("bootstrap_checksum_algorithm")
    if bootstrap_checksum != "ADLER32":
        raise ContractError("protocol v1 bootstrap checksum must remain Adler-32")
    if bootstrap_checksum not in enabled_checksums:
        raise ContractError("bootstrap checksum must be enabled")
    if contract["default_checksum_algorithm"] not in enabled_checksums:
        raise ContractError("default checksum must be enabled")

    kinds = enum_map(contract["frame_kinds"])
    validate_enum_width("frame_kinds", contract["frame_kinds"], 8)
    kind_specs = {str(entry["name"]): entry for entry in contract["frame_kinds"]}
    schemas = contract["payload_schemas"]
    for schema_name, schema in schemas.items():
        validate_fields(
            f"payload_schemas.{schema_name}",
            int(schema["size"]),
            schema["fields"],
        )
    for kind in contract["frame_kinds"]:
        for schema_key in ("payload_schema", "error_payload_schema"):
            if schema_key in kind and kind[schema_key] not in schemas:
                raise ContractError(
                    f"{kind['name']} references unknown {schema_key} "
                    f"{kind[schema_key]!r}"
                )
        unknown_flags = set(kind["allowed_flags"]) - flag_values.keys()
        if unknown_flags:
            raise ContractError(
                f"{kind['name']} allows unknown flags {sorted(unknown_flags)}"
            )
        if "response_kind" in kind and kind["response_kind"] not in kinds:
            raise ContractError(
                f"{kind['name']} references unknown response {kind['response_kind']!r}"
            )

    commands = enum_map(contract["command_kinds"])
    validate_enum_width("command_kinds", contract["command_kinds"], 8)
    observed_command_payload_max = 0
    for command in contract["command_kinds"]:
        name = str(command["name"])
        request_name = str(command["request_kind"])
        response_name = str(command["response_kind"])
        if request_name not in kind_specs or response_name not in kind_specs:
            raise ContractError(f"command {name} references an unknown frame kind")
        request = kind_specs[request_name]
        response = kind_specs[response_name]
        if request["class"] != "request" or response["class"] != "response":
            raise ContractError(f"command {name} must map request and response classes")
        if int(command["value"]) != int(request["value"]):
            raise ContractError(f"command {name} ID must equal its request frame ID")
        if int(response["value"]) != (int(command["value"]) | 0x80):
            raise ContractError(f"command {name} response ID must be request ID | 0x80")
        if request.get("response_kind") != response_name:
            raise ContractError(
                f"command {name} disagrees with request response mapping"
            )
        request_payload_size = int(schemas[str(request["payload_schema"])]["size"])
        observed_command_payload_max = max(
            observed_command_payload_max, request_payload_size
        )
        if request_payload_size > max_command_payload_bytes:
            raise ContractError(f"command {name} payload exceeds the command bound")
    request_kind_names = {
        name for name, spec in kind_specs.items() if spec["class"] == "request"
    }
    if request_kind_names != {
        str(command["request_kind"]) for command in contract["command_kinds"]
    }:
        raise ContractError("every request frame kind must map to one command kind")
    if set(commands.values()) != {
        int(kind_specs[name]["value"]) for name in request_kind_names
    }:
        raise ContractError("command IDs must exactly cover request frame IDs")
    if observed_command_payload_max != max_command_payload_bytes:
        raise ContractError("command payload bound must equal the largest command")

    for enum_name, bits in {
        "response_status": 8,
        "error_code": 16,
        "device_state": 8,
        "stream_mask": 8,
        "source": 8,
        "board_id": 16,
        "mcu_id": 16,
        "benchmark_vector": 8,
        "benchmark_memory_region": 8,
        "benchmark_cache_state": 8,
        "gpio_clock_error": 32,
        "adc_reference": 8,
        "adc_clock_source": 8,
        "adc_calibration_state": 8,
        "adc_configuration_flag": 16,
        "adc_initialization_error": 32,
    }.items():
        enum_map(contract["enums"][enum_name])
        validate_enum_width(enum_name, contract["enums"][enum_name], bits)

    fixtures = contract["golden_fixtures"]
    fixture_names = [str(fixture["name"]) for fixture in fixtures]
    if len(fixture_names) != len(set(fixture_names)):
        raise ContractError("golden fixture names must be unique")
    fixture_kinds = [str(fixture["kind"]) for fixture in fixtures]
    if set(fixture_kinds) != set(kinds):
        missing = sorted(set(kinds) - set(fixture_kinds))
        extra = sorted(set(fixture_kinds) - set(kinds))
        raise ContractError(
            f"golden fixtures must cover every frame kind; missing={missing}, "
            f"extra={extra}"
        )
    fixtures_by_kind = {str(fixture["kind"]): fixture for fixture in fixtures}
    for command in contract["command_kinds"]:
        request = fixtures_by_kind[str(command["request_kind"])]
        response = fixtures_by_kind[str(command["response_kind"])]
        if int(request["request_id"]) != int(response["request_id"]):
            raise ContractError(
                f"{command['name']} golden response must echo its request ID"
            )


def snake_to_pascal(name: str) -> str:
    """Convert a source identifier to a stable C++ PascalCase identifier."""

    return "".join(part.capitalize() for part in name.lower().split("_"))


def python_enum(
    class_name: str,
    entries: Sequence[Mapping[str, Any]],
    *,
    base: str = "IntEnum",
    include_none: bool = False,
) -> list[str]:
    """Render one generated Python enum."""

    lines = [f"class {class_name}({base}):"]
    if include_none:
        lines.append("    NONE = 0")
    lines.extend(f"    {entry['name']} = {int(entry['value'])}" for entry in entries)
    lines.append("")
    lines.append("")
    return lines


def render_python(contract: Mapping[str, Any], source_sha256: str) -> bytes:
    """Render Python constants and enums from the canonical contract."""

    header = contract["header"]
    trailer = contract["trailer"]
    limits = contract["limits"]
    timing = contract["timing"]
    benchmark = contract["checksum_benchmark"]
    gpio_clock = contract["gpio_clock_diagnostic"]
    gpio_capture = contract["gpio_capture"]
    gpio_capture_diagnostic = contract["gpio_capture_diagnostic"]
    adc_initialization = contract["adc_initialization"]
    layouts = contract["data_layouts"]
    kinds = contract["frame_kinds"]
    commands = contract["command_kinds"]
    checksums = contract["checksum_algorithms"]
    flags = contract["flags"]
    capabilities = contract["enums"]["capability_bits"]
    schemas = contract["payload_schemas"]
    header_format = "<" + "".join(
        INTEGER_FORMATS[str(field["type"])] for field in header["fields"]
    )
    data_payload_bytes = (
        int(limits["data_frame_bytes"]) - int(header["size"]) - int(trailer["size"])
    )
    coverage_ticks = int(layouts["adc"]["items_per_frame"]) * int(
        timing["adc_pair_period_ticks"]
    )
    checksum_values = enum_map(checksums)
    bootstrap_checksum = str(contract["bootstrap_checksum_algorithm"])
    default_checksum = str(contract["default_checksum_algorithm"])
    magic_bytes_literal = "".join(
        f"\\x{byte:02x}" for byte in int(contract["magic"]).to_bytes(4, "little")
    )

    lines = [
        '"""Generated protocol-v1 constants. Do not edit by hand.',
        "",
        "Source: protocol/protocol-v1.json",
        f"Source SHA-256: {source_sha256}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from enum import IntEnum, IntFlag",
        "",
        f'SOURCE_SHA256 = "{source_sha256}"',
        f"MAGIC = 0x{int(contract['magic']):08X}",
        f'MAGIC_BYTES = b"{magic_bytes_literal}"',
        f"PROTOCOL_VERSION = {int(contract['protocol_version'])}",
        f'BYTE_ORDER = "{contract["byte_order"]}"',
        f'HEADER_STRUCT_FORMAT = "{header_format}"',
        f"HEADER_SIZE = {int(header['size'])}",
        f"TRAILER_SIZE = {int(trailer['size'])}",
        f"MIN_FRAME_BYTES = {int(limits['min_frame_bytes'])}",
        f"DATA_FRAME_BYTES = {int(limits['data_frame_bytes'])}",
        f"MAX_DATA_FRAME_BYTES = {int(limits['max_data_frame_bytes'])}",
        f"DATA_PAYLOAD_BYTES = {data_payload_bytes}",
        f"MAX_CONTROL_FRAME_BYTES = {int(limits['max_control_frame_bytes'])}",
        "MAX_CONTROL_PAYLOAD_BYTES = MAX_CONTROL_FRAME_BYTES - HEADER_SIZE - TRAILER_SIZE",
        f"MAX_COMMAND_FRAME_BYTES = {int(limits['max_command_frame_bytes'])}",
        f"MAX_COMMAND_PAYLOAD_BYTES = {int(limits['max_command_payload_bytes'])}",
        f"TIMESTAMP_HZ = {int(timing['timestamp_hz'])}",
        f"ADC_PAIR_RATE_HZ = {int(timing['adc_pair_rate_hz'])}",
        f"ADC_PAIR_PERIOD_TICKS = {int(timing['adc_pair_period_ticks'])}",
        f"ADC1_PHASE_TICKS = {int(timing['adc1_phase_ticks'])}",
        f"GPIO_SAMPLE_RATE_HZ = {int(timing['gpio_sample_rate_hz'])}",
        f"GPIO_SAMPLE_PERIOD_TICKS = {int(timing['gpio_sample_period_ticks'])}",
        f"FRAME_COVERAGE_TICKS = {coverage_ticks}",
        f"CHECKSUM_BENCHMARK_CYCLE_COUNTER_HZ = {int(benchmark['cycle_counter_hz'])}",
        (
            "CHECKSUM_BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND = "
            f"{int(benchmark['target_framed_bytes_per_second'])}"
        ),
        f"CHECKSUM_BENCHMARK_MAX_BATCH_COUNT = {int(benchmark['max_batch_count'])}",
        (
            "CHECKSUM_BENCHMARK_MAX_ITERATIONS_PER_BATCH = "
            f"{int(benchmark['max_iterations_per_batch'])}"
        ),
        f"CHECKSUM_BENCHMARK_MAX_OPERATIONS = {int(benchmark['max_operations'])}",
        (
            "CHECKSUM_BENCHMARK_MAX_PROCESSED_BYTES = "
            f"{int(benchmark['max_processed_bytes'])}"
        ),
        (
            "CHECKSUM_BENCHMARK_TIMER_CALIBRATION_SAMPLES = "
            f"{int(benchmark['timer_calibration_samples'])}"
        ),
        f"CHECKSUM_BENCHMARK_WARMUP_OPERATIONS = {int(benchmark['warmup_operations'])}",
        f"GPIO_CLOCK_PIT_HZ = {int(gpio_clock['pit_clock_hz'])}",
        f"GPIO_CLOCK_DWT_HZ = {int(gpio_clock['cycle_counter_hz'])}",
        f"GPIO_CLOCK_PRODUCTION_RATE_HZ = {int(gpio_clock['production_rate_hz'])}",
        f"GPIO_CLOCK_MIN_RATE_HZ = {int(gpio_clock['minimum_rate_hz'])}",
        f"GPIO_CLOCK_MIN_EVENT_COUNT = {int(gpio_clock['minimum_event_count'])}",
        f"GPIO_CLOCK_MAX_EVENT_COUNT = {int(gpio_clock['maximum_event_count'])}",
        f"GPIO_CLOCK_MAX_ELAPSED_CYCLES = {int(gpio_clock['maximum_elapsed_cycles'])}",
        f"GPIO_CLOCK_DUPLICATE_GUARD_EVENTS = {int(gpio_clock['duplicate_guard_events'])}",
        f"GPIO_CLOCK_COUNT_TOLERANCE = {int(gpio_clock['count_tolerance'])}",
        f"GPIO_PACKED_WIDTH_BITS = {int(gpio_capture['packed_width_bits'])}",
        f"GPIO_RAW_RING_DEPTH = {int(gpio_capture['raw_ring_depth'])}",
        (
            "GPIO_RAW_SAMPLES_PER_BUFFER = "
            f"{int(gpio_capture['raw_samples_per_buffer'])}"
        ),
        f"GPIO_RAW_RING_BYTES = {int(gpio_capture['raw_ring_bytes'])}",
        f"GPIO_PACKED_RING_DEPTH = {int(gpio_capture['packed_ring_depth'])}",
        f"GPIO_PACKED_RING_BYTES = {int(gpio_capture['packed_ring_bytes'])}",
        f"GPIO_PACKET_BUFFER_COUNT = {int(gpio_capture['packet_buffer_count'])}",
        f"GPIO_PIT_CHANNEL = {int(gpio_capture['pit_channel'])}",
        f"GPIO_XBAR_INPUT = {int(gpio_capture['xbar_input'])}",
        f"GPIO_XBAR_OUTPUT = {int(gpio_capture['xbar_output'])}",
        f"GPIO_XBAR_ACTIVE_EDGE = {int(gpio_capture['xbar_active_edge'])}",
        f"GPIO_EDMA_CHANNEL = {int(gpio_capture['edma_channel'])}",
        f"GPIO_DMAMUX_SOURCE = {int(gpio_capture['dmamux_source'])}",
        f"GPIO_EDMA_PRIORITY = {int(gpio_capture['edma_priority'])}",
        (
            "GPIO_CAPTURE_DIAGNOSTIC_ANALYSIS_SAMPLES = "
            f"{int(gpio_capture_diagnostic['analysis_samples'])}"
        ),
        f"ADC_PRIMARY_RESOLUTION_BITS = {int(adc_initialization['primary_resolution_bits'])}",
        f"ADC_FALLBACK_RESOLUTION_BITS = {int(adc_initialization['fallback_resolution_bits'])}",
        f"ADC_CODE_MIN = {int(adc_initialization['code_min'])}",
        f"ADC_REFERENCE_MV_NOMINAL = {int(adc_initialization['reference_mv_nominal'])}",
        f"ADC_INPUT_MIN_MV_NOMINAL = {int(adc_initialization['input_min_mv_nominal'])}",
        f"ADC_INPUT_MAX_MV_NOMINAL = {int(adc_initialization['input_max_mv_nominal'])}",
        f"ADC_IPG_CLOCK_HZ = {int(adc_initialization['ipg_clock_hz'])}",
        f"ADC_CLOCK_HZ = {int(adc_initialization['adc_clock_hz'])}",
        f"ADC_CLOCK_DIVIDER = {int(adc_initialization['clock_divider'])}",
        f"ADC_HARDWARE_AVERAGE_COUNT = {int(adc_initialization['hardware_average_count'])}",
        f"ADC_SAMPLE_TIME_ADCK = {int(adc_initialization['sample_time_adck'])}",
        f"ADC_CALIBRATION_CYCLE_COUNTER_HZ = {int(adc_initialization['calibration_cycle_counter_hz'])}",
        f"ADC_CALIBRATION_DEADLINE_US = {int(adc_initialization['calibration_deadline_us'])}",
        f"ADC_CALIBRATION_POLL_LIMIT = {int(adc_initialization['calibration_poll_limit'])}",
        f"ADC_PINS = {tuple(adc_initialization['pins'])!r}",
        f"ADC_PERIPHERALS = {tuple(adc_initialization['peripherals'])!r}",
        f"ADC_CHANNELS = {tuple(adc_initialization['channels'])!r}",
        f"ADC_BYTES_PER_PAIR = {int(layouts['adc']['bytes_per_item'])}",
        f"ADC_PAIRS_PER_FRAME = {int(layouts['adc']['items_per_frame'])}",
        f"ADC_RESOLUTION_BITS = {int(layouts['adc']['resolution_bits'])}",
        f"ADC_CONTAINER_BITS = {int(layouts['adc']['container_bits'])}",
        f"GPIO_SAMPLES_PER_FRAME = {int(layouts['gpio']['items_per_frame'])}",
        f"GPIO_PINS_BY_BIT = {tuple(layouts['gpio']['pins_by_bit'])!r}",
        "UINT32_MAX = 0xFFFFFFFF",
        "UINT64_MAX = 0xFFFFFFFFFFFFFFFF",
        "",
        "",
    ]
    for field in header["fields"]:
        constant_name = f"HEADER_{str(field['name']).upper()}_OFFSET"
        lines.append(f"{constant_name} = {int(field['offset'])}")
    lines.extend(["", ""])

    lines.extend(python_enum("FrameKind", kinds))
    lines.extend(python_enum("CommandKind", commands))
    lines.extend(python_enum("FrameFlag", flags, base="IntFlag", include_none=True))
    lines.extend(python_enum("ChecksumAlgorithm", checksums))
    lines.extend(python_enum("ResponseStatus", contract["enums"]["response_status"]))
    lines.extend(python_enum("ErrorCode", contract["enums"]["error_code"]))
    lines.extend(python_enum("DeviceState", contract["enums"]["device_state"]))
    lines.extend(
        python_enum(
            "StreamMask",
            contract["enums"]["stream_mask"],
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(
        python_enum(
            "Capability",
            capabilities,
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(python_enum("Source", contract["enums"]["source"]))
    lines.extend(python_enum("BoardId", contract["enums"]["board_id"]))
    lines.extend(python_enum("McuId", contract["enums"]["mcu_id"]))
    lines.extend(python_enum("BenchmarkVector", contract["enums"]["benchmark_vector"]))
    lines.extend(
        python_enum(
            "BenchmarkMemoryRegion",
            contract["enums"]["benchmark_memory_region"],
        )
    )
    lines.extend(
        python_enum("BenchmarkCacheState", contract["enums"]["benchmark_cache_state"])
    )
    lines.extend(
        python_enum(
            "GpioClockError",
            contract["enums"]["gpio_clock_error"],
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(
        python_enum(
            "GpioCaptureDiagnosticMode",
            contract["enums"]["gpio_capture_diagnostic_mode"],
        )
    )
    lines.extend(
        python_enum(
            "GpioCaptureDiagnosticFlag",
            contract["enums"]["gpio_capture_diagnostic_flag"],
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(
        python_enum(
            "GpioCaptureError",
            contract["enums"]["gpio_capture_error"],
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(python_enum("AdcReference", contract["enums"]["adc_reference"]))
    lines.extend(python_enum("AdcClockSource", contract["enums"]["adc_clock_source"]))
    lines.extend(
        python_enum("AdcCalibrationState", contract["enums"]["adc_calibration_state"])
    )
    lines.extend(
        python_enum(
            "AdcConfigurationFlag",
            contract["enums"]["adc_configuration_flag"],
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(
        python_enum(
            "AdcInitializationError",
            contract["enums"]["adc_initialization_error"],
            base="IntFlag",
            include_none=True,
        )
    )

    lines.extend(
        [
            f"BOOTSTRAP_CHECKSUM_ALGORITHM = ChecksumAlgorithm.{bootstrap_checksum}",
            f"DEFAULT_CHECKSUM_ALGORITHM = ChecksumAlgorithm.{default_checksum}",
            "SUPPORTED_CHECKSUM_ALGORITHMS = frozenset(",
            "    {",
        ]
    )
    for entry in checksums:
        if entry["enabled_in_v1"]:
            lines.append(f"        ChecksumAlgorithm.{entry['name']},")
    lines.extend(["    }", ")", ""])
    supported_checksum_mask = sum(
        1 << checksum_values[str(entry["name"])]
        for entry in checksums
        if entry["enabled_in_v1"]
    )
    lines.append(f"SUPPORTED_CHECKSUM_MASK = {supported_checksum_mask}")
    lines.append(
        "KNOWN_FRAME_FLAG_MASK = " + str(sum(int(entry["value"]) for entry in flags))
    )
    lines.append(
        "KNOWN_CAPABILITY_MASK = "
        + str(sum(int(entry["value"]) for entry in capabilities))
    )
    lines.append(
        "KNOWN_GPIO_CLOCK_ERROR_MASK = "
        + str(
            sum(int(entry["value"]) for entry in contract["enums"]["gpio_clock_error"])
        )
    )
    lines.append(
        "KNOWN_GPIO_CAPTURE_DIAGNOSTIC_FLAG_MASK = "
        + str(
            sum(
                int(entry["value"])
                for entry in contract["enums"]["gpio_capture_diagnostic_flag"]
            )
        )
    )
    lines.append(
        "KNOWN_GPIO_CAPTURE_ERROR_MASK = "
        + str(
            sum(
                int(entry["value"]) for entry in contract["enums"]["gpio_capture_error"]
            )
        )
    )
    lines.append(
        "KNOWN_ADC_CONFIGURATION_FLAG_MASK = "
        + str(
            sum(
                int(entry["value"])
                for entry in contract["enums"]["adc_configuration_flag"]
            )
        )
    )
    lines.append(
        "KNOWN_ADC_INITIALIZATION_ERROR_MASK = "
        + str(
            sum(
                int(entry["value"])
                for entry in contract["enums"]["adc_initialization_error"]
            )
        )
    )
    lines.extend(["", ""])

    lines.append("FRAME_KIND_CLASS: dict[FrameKind, str] = {")
    for kind in kinds:
        lines.append(f'    FrameKind.{kind["name"]}: "{kind["class"]}",')
    lines.extend(["}", ""])

    lines.append("ALLOWED_FLAGS_BY_KIND: dict[FrameKind, FrameFlag] = {")
    for kind in kinds:
        allowed = kind["allowed_flags"]
        if not allowed:
            lines.append(f"    FrameKind.{kind['name']}: FrameFlag.NONE,")
            continue
        lines.append(f"    FrameKind.{kind['name']}: FrameFlag.{allowed[0]}")
        for flag_name in allowed[1:]:
            lines.append(f"    | FrameFlag.{flag_name}")
        lines[-1] += ","
    lines.extend(["}", ""])

    lines.append("REQUEST_RESPONSE_KIND: dict[FrameKind, FrameKind] = {")
    for kind in kinds:
        if "response_kind" in kind:
            lines.append(
                f"    FrameKind.{kind['name']}: FrameKind.{kind['response_kind']},"
            )
    lines.extend(["}", ""])

    lines.append("COMMAND_REQUEST_KIND: dict[CommandKind, FrameKind] = {")
    for command in commands:
        lines.append(
            f"    CommandKind.{command['name']}: FrameKind.{command['request_kind']},"
        )
    lines.extend(["}", ""])

    lines.append("COMMAND_RESPONSE_KIND: dict[CommandKind, FrameKind] = {")
    for command in commands:
        lines.append(
            f"    CommandKind.{command['name']}: FrameKind.{command['response_kind']},"
        )
    lines.extend(["}", ""])

    lines.append("COMMAND_BY_REQUEST_KIND: dict[FrameKind, CommandKind] = {")
    for command in commands:
        lines.append(
            f"    FrameKind.{command['request_kind']}: CommandKind.{command['name']},"
        )
    lines.extend(["}", ""])

    lines.append("COMMAND_BY_RESPONSE_KIND: dict[FrameKind, CommandKind] = {")
    for command in commands:
        lines.append(
            f"    FrameKind.{command['response_kind']}: CommandKind.{command['name']},"
        )
    lines.extend(["}", ""])

    lines.append("PAYLOAD_SCHEMA_BY_KIND: dict[FrameKind, str] = {")
    for kind in kinds:
        lines.append(f'    FrameKind.{kind["name"]}: "{kind["payload_schema"]}",')
    lines.extend(["}", ""])

    lines.append("ERROR_PAYLOAD_SCHEMA_BY_KIND: dict[FrameKind, str] = {")
    for kind in kinds:
        if "error_payload_schema" in kind:
            lines.append(
                f'    FrameKind.{kind["name"]}: "{kind["error_payload_schema"]}",'
            )
    lines.extend(["}", ""])

    lines.append("PAYLOAD_SIZE_BY_SCHEMA: dict[str, int] = {")
    for name, schema in schemas.items():
        lines.append(f'    "{name}": {int(schema["size"])},')
    lines.extend(["}", ""])
    for name, schema in schemas.items():
        lines.append(f"{name.upper()}_PAYLOAD_SIZE = {int(schema['size'])}")
        for field in schema["fields"]:
            field_prefix = f"{name}_{field['name']}".upper()
            lines.append(f"{field_prefix}_OFFSET = {int(field['offset'])}")
            if "count" in field:
                lines.append(f"{field_prefix}_COUNT = {int(field['count'])}")
    lines.append("")

    return ("\n".join(lines).rstrip() + "\n").encode()


def cpp_enum(
    enum_name: str,
    underlying_type: str,
    entries: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Render one generated scoped C++ enum."""

    lines = [f"enum class {enum_name} : {underlying_type} {{"]
    lines.extend(
        f"  k{snake_to_pascal(str(entry['name']))} = {int(entry['value'])}U,"
        for entry in entries
    )
    lines.extend(["};", ""])
    return lines


def render_cpp(contract: Mapping[str, Any], source_sha256: str) -> bytes:
    """Render portable C++ constants without relying on packed structs."""

    header = contract["header"]
    trailer = contract["trailer"]
    limits = contract["limits"]
    timing = contract["timing"]
    benchmark = contract["checksum_benchmark"]
    gpio_clock = contract["gpio_clock_diagnostic"]
    gpio_capture = contract["gpio_capture"]
    gpio_capture_diagnostic = contract["gpio_capture_diagnostic"]
    adc_initialization = contract["adc_initialization"]
    layouts = contract["data_layouts"]
    kinds = contract["frame_kinds"]
    commands = contract["command_kinds"]
    checksums = contract["checksum_algorithms"]
    flags = contract["flags"]
    capabilities = contract["enums"]["capability_bits"]
    schemas = contract["payload_schemas"]
    data_payload_bytes = (
        int(limits["data_frame_bytes"]) - int(header["size"]) - int(trailer["size"])
    )
    coverage_ticks = int(layouts["adc"]["items_per_frame"]) * int(
        timing["adc_pair_period_ticks"]
    )
    bootstrap_checksum = snake_to_pascal(str(contract["bootstrap_checksum_algorithm"]))
    default_checksum = snake_to_pascal(str(contract["default_checksum_algorithm"]))

    lines = [
        "// Generated from protocol/protocol-v1.json. Do not edit by hand.",
        f"// Source SHA-256: {source_sha256}",
        "#pragma once",
        "",
        "#include <cstddef>",
        "#include <cstdint>",
        "",
        "namespace teensy_daq::protocol_v1 {",
        "",
        f'inline constexpr char kSourceSha256[] = "{source_sha256}";',
        f"inline constexpr std::uint32_t kMagic = 0x{int(contract['magic']):08X}U;",
        f"inline constexpr std::uint8_t kProtocolVersion = {int(contract['protocol_version'])}U;",
        "inline constexpr bool kWireIsLittleEndian = true;",
        f"inline constexpr std::size_t kHeaderSize = {int(header['size'])}U;",
        f"inline constexpr std::size_t kTrailerSize = {int(trailer['size'])}U;",
        f"inline constexpr std::size_t kMinFrameBytes = {int(limits['min_frame_bytes'])}U;",
        f"inline constexpr std::size_t kDataFrameBytes = {int(limits['data_frame_bytes'])}U;",
        f"inline constexpr std::size_t kMaxDataFrameBytes = {int(limits['max_data_frame_bytes'])}U;",
        f"inline constexpr std::size_t kDataPayloadBytes = {data_payload_bytes}U;",
        (
            "inline constexpr std::size_t kMaxControlFrameBytes = "
            f"{int(limits['max_control_frame_bytes'])}U;"
        ),
        "inline constexpr std::size_t kMaxControlPayloadBytes =",
        "    kMaxControlFrameBytes - kHeaderSize - kTrailerSize;",
        (
            "inline constexpr std::size_t kMaxCommandFrameBytes = "
            f"{int(limits['max_command_frame_bytes'])}U;"
        ),
        (
            "inline constexpr std::size_t kMaxCommandPayloadBytes = "
            f"{int(limits['max_command_payload_bytes'])}U;"
        ),
        f"inline constexpr std::uint32_t kTimestampHz = {int(timing['timestamp_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcPairRateHz = {int(timing['adc_pair_rate_hz'])}U;",
        (
            "inline constexpr std::uint32_t kAdcPairPeriodTicks = "
            f"{int(timing['adc_pair_period_ticks'])}U;"
        ),
        f"inline constexpr std::uint32_t kAdc1PhaseTicks = {int(timing['adc1_phase_ticks'])}U;",
        (
            "inline constexpr std::uint32_t kGpioSampleRateHz = "
            f"{int(timing['gpio_sample_rate_hz'])}U;"
        ),
        (
            "inline constexpr std::uint32_t kGpioSamplePeriodTicks = "
            f"{int(timing['gpio_sample_period_ticks'])}U;"
        ),
        f"inline constexpr std::uint32_t kFrameCoverageTicks = {coverage_ticks}U;",
        (
            "inline constexpr std::uint32_t kChecksumBenchmarkCycleCounterHz = "
            f"{int(benchmark['cycle_counter_hz'])}U;"
        ),
        (
            "inline constexpr std::uint32_t "
            "kChecksumBenchmarkTargetFramedBytesPerSecond = "
            f"{int(benchmark['target_framed_bytes_per_second'])}U;"
        ),
        (
            "inline constexpr std::uint16_t kChecksumBenchmarkMaxBatchCount = "
            f"{int(benchmark['max_batch_count'])}U;"
        ),
        (
            "inline constexpr std::uint16_t "
            "kChecksumBenchmarkMaxIterationsPerBatch = "
            f"{int(benchmark['max_iterations_per_batch'])}U;"
        ),
        (
            "inline constexpr std::uint32_t kChecksumBenchmarkMaxOperations = "
            f"{int(benchmark['max_operations'])}U;"
        ),
        (
            "inline constexpr std::uint32_t "
            "kChecksumBenchmarkMaxProcessedBytes = "
            f"{int(benchmark['max_processed_bytes'])}U;"
        ),
        (
            "inline constexpr std::uint16_t "
            "kChecksumBenchmarkTimerCalibrationSamples = "
            f"{int(benchmark['timer_calibration_samples'])}U;"
        ),
        (
            "inline constexpr std::uint16_t "
            "kChecksumBenchmarkWarmupOperations = "
            f"{int(benchmark['warmup_operations'])}U;"
        ),
        f"inline constexpr std::uint32_t kGpioClockPitHz = {int(gpio_clock['pit_clock_hz'])}U;",
        f"inline constexpr std::uint32_t kGpioClockDwtHz = {int(gpio_clock['cycle_counter_hz'])}U;",
        (
            "inline constexpr std::uint32_t kGpioClockProductionRateHz = "
            f"{int(gpio_clock['production_rate_hz'])}U;"
        ),
        f"inline constexpr std::uint32_t kGpioClockMinRateHz = {int(gpio_clock['minimum_rate_hz'])}U;",
        (
            "inline constexpr std::uint16_t kGpioClockMinEventCount = "
            f"{int(gpio_clock['minimum_event_count'])}U;"
        ),
        (
            "inline constexpr std::uint16_t kGpioClockMaxEventCount = "
            f"{int(gpio_clock['maximum_event_count'])}U;"
        ),
        (
            "inline constexpr std::uint32_t kGpioClockMaxElapsedCycles = "
            f"{int(gpio_clock['maximum_elapsed_cycles'])}U;"
        ),
        (
            "inline constexpr std::uint16_t kGpioClockDuplicateGuardEvents = "
            f"{int(gpio_clock['duplicate_guard_events'])}U;"
        ),
        (
            "inline constexpr std::uint32_t kGpioClockCountTolerance = "
            f"{int(gpio_clock['count_tolerance'])}U;"
        ),
        f"inline constexpr std::uint8_t kGpioPackedWidthBits = {int(gpio_capture['packed_width_bits'])}U;",
        f"inline constexpr std::uint8_t kGpioRawRingDepth = {int(gpio_capture['raw_ring_depth'])}U;",
        (
            "inline constexpr std::uint32_t kGpioRawSamplesPerBuffer = "
            f"{int(gpio_capture['raw_samples_per_buffer'])}U;"
        ),
        f"inline constexpr std::uint32_t kGpioRawRingBytes = {int(gpio_capture['raw_ring_bytes'])}U;",
        f"inline constexpr std::uint8_t kGpioPackedRingDepth = {int(gpio_capture['packed_ring_depth'])}U;",
        f"inline constexpr std::uint32_t kGpioPackedRingBytes = {int(gpio_capture['packed_ring_bytes'])}U;",
        f"inline constexpr std::uint16_t kGpioPacketBufferCount = {int(gpio_capture['packet_buffer_count'])}U;",
        f"inline constexpr std::uint8_t kGpioPitChannel = {int(gpio_capture['pit_channel'])}U;",
        f"inline constexpr std::uint8_t kGpioXbarInput = {int(gpio_capture['xbar_input'])}U;",
        f"inline constexpr std::uint8_t kGpioXbarOutput = {int(gpio_capture['xbar_output'])}U;",
        f"inline constexpr std::uint8_t kGpioXbarActiveEdge = {int(gpio_capture['xbar_active_edge'])}U;",
        f"inline constexpr std::uint8_t kGpioEdmaChannel = {int(gpio_capture['edma_channel'])}U;",
        f"inline constexpr std::uint8_t kGpioDmamuxSource = {int(gpio_capture['dmamux_source'])}U;",
        f"inline constexpr std::uint8_t kGpioEdmaPriority = {int(gpio_capture['edma_priority'])}U;",
        (
            "inline constexpr std::uint32_t "
            "kGpioCaptureDiagnosticAnalysisSamples = "
            f"{int(gpio_capture_diagnostic['analysis_samples'])}U;"
        ),
        f"inline constexpr std::uint8_t kAdcPrimaryResolutionBits = {int(adc_initialization['primary_resolution_bits'])}U;",
        f"inline constexpr std::uint8_t kAdcFallbackResolutionBits = {int(adc_initialization['fallback_resolution_bits'])}U;",
        f"inline constexpr std::uint16_t kAdcCodeMin = {int(adc_initialization['code_min'])}U;",
        f"inline constexpr std::uint16_t kAdcReferenceMvNominal = {int(adc_initialization['reference_mv_nominal'])}U;",
        f"inline constexpr std::uint16_t kAdcInputMinMvNominal = {int(adc_initialization['input_min_mv_nominal'])}U;",
        f"inline constexpr std::uint16_t kAdcInputMaxMvNominal = {int(adc_initialization['input_max_mv_nominal'])}U;",
        f"inline constexpr std::uint32_t kAdcIpgClockHz = {int(adc_initialization['ipg_clock_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcClockHz = {int(adc_initialization['adc_clock_hz'])}U;",
        f"inline constexpr std::uint8_t kAdcClockDivider = {int(adc_initialization['clock_divider'])}U;",
        f"inline constexpr std::uint8_t kAdcHardwareAverageCount = {int(adc_initialization['hardware_average_count'])}U;",
        f"inline constexpr std::uint8_t kAdcSampleTimeAdck = {int(adc_initialization['sample_time_adck'])}U;",
        f"inline constexpr std::uint32_t kAdcCalibrationCycleCounterHz = {int(adc_initialization['calibration_cycle_counter_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcCalibrationDeadlineUs = {int(adc_initialization['calibration_deadline_us'])}U;",
        f"inline constexpr std::uint32_t kAdcCalibrationPollLimit = {int(adc_initialization['calibration_poll_limit'])}U;",
        "inline constexpr std::uint8_t kAdcPins[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_initialization["pins"])
        + "};",
        "inline constexpr std::uint8_t kAdcPeripherals[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_initialization["peripherals"])
        + "};",
        "inline constexpr std::uint8_t kAdcChannels[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_initialization["channels"])
        + "};",
        f"inline constexpr std::size_t kAdcBytesPerPair = {int(layouts['adc']['bytes_per_item'])}U;",
        f"inline constexpr std::size_t kAdcPairsPerFrame = {int(layouts['adc']['items_per_frame'])}U;",
        f"inline constexpr std::uint8_t kAdcResolutionBits = {int(layouts['adc']['resolution_bits'])}U;",
        f"inline constexpr std::uint8_t kAdcContainerBits = {int(layouts['adc']['container_bits'])}U;",
        f"inline constexpr std::size_t kGpioSamplesPerFrame = {int(layouts['gpio']['items_per_frame'])}U;",
        "inline constexpr std::uint8_t kGpioPinsByBit[] = {"
        + ", ".join(f"{int(pin)}U" for pin in layouts["gpio"]["pins_by_bit"])
        + "};",
        "",
    ]
    for field in header["fields"]:
        name = snake_to_pascal(str(field["name"]))
        lines.append(
            f"inline constexpr std::size_t kHeader{name}Offset = "
            f"{int(field['offset'])}U;"
        )
    lines.append("")

    lines.extend(cpp_enum("FrameKind", "std::uint8_t", kinds))
    lines.extend(cpp_enum("CommandKind", "std::uint8_t", commands))
    lines.extend(cpp_enum("FrameFlag", "std::uint16_t", flags))
    lines.extend(cpp_enum("ChecksumAlgorithm", "std::uint8_t", checksums))
    lines.extend(
        cpp_enum("ResponseStatus", "std::uint8_t", contract["enums"]["response_status"])
    )
    lines.extend(
        cpp_enum("ErrorCode", "std::uint16_t", contract["enums"]["error_code"])
    )
    lines.extend(
        cpp_enum("DeviceState", "std::uint8_t", contract["enums"]["device_state"])
    )
    lines.extend(
        cpp_enum("StreamMask", "std::uint8_t", contract["enums"]["stream_mask"])
    )
    lines.extend(cpp_enum("Capability", "std::uint32_t", capabilities))
    lines.extend(cpp_enum("Source", "std::uint8_t", contract["enums"]["source"]))
    lines.extend(cpp_enum("BoardId", "std::uint16_t", contract["enums"]["board_id"]))
    lines.extend(cpp_enum("McuId", "std::uint16_t", contract["enums"]["mcu_id"]))
    lines.extend(
        cpp_enum(
            "BenchmarkVector", "std::uint8_t", contract["enums"]["benchmark_vector"]
        )
    )
    lines.extend(
        cpp_enum(
            "BenchmarkMemoryRegion",
            "std::uint8_t",
            contract["enums"]["benchmark_memory_region"],
        )
    )
    lines.extend(
        cpp_enum(
            "BenchmarkCacheState",
            "std::uint8_t",
            contract["enums"]["benchmark_cache_state"],
        )
    )
    lines.extend(
        cpp_enum(
            "GpioClockError",
            "std::uint32_t",
            contract["enums"]["gpio_clock_error"],
        )
    )
    lines.extend(
        cpp_enum(
            "GpioCaptureDiagnosticMode",
            "std::uint8_t",
            contract["enums"]["gpio_capture_diagnostic_mode"],
        )
    )
    lines.extend(
        cpp_enum(
            "GpioCaptureDiagnosticFlag",
            "std::uint32_t",
            contract["enums"]["gpio_capture_diagnostic_flag"],
        )
    )
    lines.extend(
        cpp_enum(
            "GpioCaptureError",
            "std::uint32_t",
            contract["enums"]["gpio_capture_error"],
        )
    )
    lines.extend(
        cpp_enum("AdcReference", "std::uint8_t", contract["enums"]["adc_reference"])
    )
    lines.extend(
        cpp_enum(
            "AdcClockSource",
            "std::uint8_t",
            contract["enums"]["adc_clock_source"],
        )
    )
    lines.extend(
        cpp_enum(
            "AdcCalibrationState",
            "std::uint8_t",
            contract["enums"]["adc_calibration_state"],
        )
    )
    lines.extend(
        cpp_enum(
            "AdcConfigurationFlag",
            "std::uint16_t",
            contract["enums"]["adc_configuration_flag"],
        )
    )
    lines.extend(
        cpp_enum(
            "AdcInitializationError",
            "std::uint32_t",
            contract["enums"]["adc_initialization_error"],
        )
    )

    lines.extend(
        [
            "inline constexpr ChecksumAlgorithm kBootstrapChecksumAlgorithm =",
            f"    ChecksumAlgorithm::k{bootstrap_checksum};",
            "inline constexpr ChecksumAlgorithm kDefaultChecksumAlgorithm =",
            f"    ChecksumAlgorithm::k{default_checksum};",
            "inline constexpr std::uint32_t kSupportedChecksumMask = "
            + str(
                sum(
                    1 << int(entry["value"])
                    for entry in checksums
                    if entry["enabled_in_v1"]
                )
            )
            + "U;",
            "inline constexpr std::uint16_t kKnownFrameFlagMask = "
            + str(sum(int(entry["value"]) for entry in flags))
            + "U;",
            "inline constexpr std::uint32_t kKnownCapabilityMask = "
            + str(sum(int(entry["value"]) for entry in capabilities))
            + "U;",
            "inline constexpr std::uint32_t kKnownGpioClockErrorMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["gpio_clock_error"]
                )
            )
            + "U;",
            "inline constexpr std::uint32_t "
            "kKnownGpioCaptureDiagnosticFlagMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["gpio_capture_diagnostic_flag"]
                )
            )
            + "U;",
            "inline constexpr std::uint32_t kKnownGpioCaptureErrorMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["gpio_capture_error"]
                )
            )
            + "U;",
            "inline constexpr std::uint16_t kKnownAdcConfigurationFlagMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["adc_configuration_flag"]
                )
            )
            + "U;",
            "inline constexpr std::uint32_t kKnownAdcInitializationErrorMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["adc_initialization_error"]
                )
            )
            + "U;",
            "",
        ]
    )
    for name, schema in schemas.items():
        schema_name = snake_to_pascal(name)
        lines.append(
            f"inline constexpr std::size_t k{schema_name}PayloadSize = "
            f"{int(schema['size'])}U;"
        )
        for field in schema["fields"]:
            field_name = snake_to_pascal(str(field["name"]))
            lines.append(
                f"inline constexpr std::size_t k{schema_name}{field_name}Offset = "
                f"{int(field['offset'])}U;"
            )
            if "count" in field:
                lines.append(
                    f"inline constexpr std::size_t k{schema_name}{field_name}Count = "
                    f"{int(field['count'])}U;"
                )

    lines.extend(
        [
            "",
            "constexpr std::uint16_t allowedFlags(FrameKind kind) {",
            "  switch (kind) {",
        ]
    )
    for kind in kinds:
        flags_expression = " | ".join(
            f"static_cast<std::uint16_t>(FrameFlag::k{snake_to_pascal(str(flag_name))})"
            for flag_name in kind["allowed_flags"]
        )
        if not flags_expression:
            flags_expression = "0U"
        lines.extend(
            [
                f"    case FrameKind::k{snake_to_pascal(str(kind['name']))}:",
                f"      return {flags_expression};",
            ]
        )
    lines.extend(["  }", "  return 0U;", "}", ""])

    lines.extend(
        [
            "constexpr FrameKind requestFrameKind(CommandKind command) {",
            "  switch (command) {",
        ]
    )
    for command in commands:
        lines.extend(
            [
                f"    case CommandKind::k{snake_to_pascal(str(command['name']))}:",
                "      return FrameKind::k"
                + snake_to_pascal(str(command["request_kind"]))
                + ";",
            ]
        )
    lines.extend(
        [
            "  }",
            "  return FrameKind::kInfoRequest;",
            "}",
            "",
            "constexpr FrameKind responseFrameKind(CommandKind command) {",
            "  switch (command) {",
        ]
    )
    for command in commands:
        lines.extend(
            [
                f"    case CommandKind::k{snake_to_pascal(str(command['name']))}:",
                "      return FrameKind::k"
                + snake_to_pascal(str(command["response_kind"]))
                + ";",
            ]
        )
    lines.extend(
        [
            "  }",
            "  return FrameKind::kInfoResponse;",
            "}",
            "",
        ]
    )

    lines.extend(
        [
            "static_assert(kHeaderSize + kDataPayloadBytes + kTrailerSize ==",
            "              kDataFrameBytes);",
            "static_assert(kAdcPairsPerFrame * kAdcBytesPerPair ==",
            "              kDataPayloadBytes);",
            "static_assert(kGpioSamplesPerFrame == kDataPayloadBytes);",
            "",
            "}  // namespace teensy_daq::protocol_v1",
            "",
        ]
    )
    return "\n".join(lines).encode()


def encode_schema_payload(
    contract: Mapping[str, Any], schema_name: str, values: Mapping[str, Any]
) -> bytes:
    """Encode one fixed payload schema for a golden fixture."""

    schema = contract["payload_schemas"][schema_name]
    payload = bytearray(int(schema["size"]))
    expected_value_names: set[str] = set()
    for field in schema["fields"]:
        name = str(field["name"])
        field_type = str(field["type"])
        offset = int(field["offset"])
        if "required" in field:
            value = int(field["required"])
        else:
            expected_value_names.add(name)
            if name not in values:
                raise ContractError(f"fixture schema {schema_name} is missing {name}")
            value = values[name]

        if field_type in INTEGER_FORMATS:
            struct.pack_into("<" + INTEGER_FORMATS[field_type], payload, offset, value)
        elif field_type == "u8_array":
            encoded = bytes(value)
            if len(encoded) != int(field["count"]):
                raise ContractError(f"{schema_name}.{name} has the wrong array size")
            payload[offset : offset + len(encoded)] = encoded
        elif field_type == "nul_ascii":
            encoded = str(value).encode("ascii")
            count = int(field["count"])
            if len(encoded) >= count:
                raise ContractError(
                    f"{schema_name}.{name} must leave room for a NUL terminator"
                )
            payload[offset : offset + len(encoded)] = encoded
        elif field_type == "bytes":
            encoded = bytes(value)
            if len(encoded) != int(field["count"]):
                raise ContractError(f"{schema_name}.{name} has the wrong byte count")
            payload[offset : offset + len(encoded)] = encoded
        else:
            raise ContractError(
                f"generic fixture encoder does not support {field_type!r}"
            )

    extras = set(values) - expected_value_names
    if extras:
        raise ContractError(
            f"fixture schema {schema_name} has unexpected values {sorted(extras)}"
        )
    return bytes(payload)


def encode_fixture_payload(
    contract: Mapping[str, Any], fixture: Mapping[str, Any]
) -> bytes:
    """Build a golden payload from a schema or deterministic data pattern."""

    payload_spec = fixture["payload"]
    pattern = payload_spec.get("pattern")
    if pattern == "adc_interleaved_ramp":
        layout = contract["data_layouts"]["adc"]
        count = int(layout["items_per_frame"])
        code_mask = (1 << int(layout["resolution_bits"])) - 1
        start_index = int(payload_spec["start_index"])
        payload = bytearray()
        for offset in range(count):
            sample_index = start_index + offset
            payload.extend(
                struct.pack(
                    "<HH",
                    (2 * sample_index) & code_mask,
                    (2 * sample_index + 1) & code_mask,
                )
            )
        return bytes(payload)
    if pattern == "gpio_byte_ramp":
        count = int(contract["data_layouts"]["gpio"]["items_per_frame"])
        start_index = int(payload_spec["start_index"])
        return bytes((start_index + offset) & 0xFF for offset in range(count))
    if pattern is not None:
        raise ContractError(f"unknown golden payload pattern: {pattern}")

    schema_name = str(payload_spec["schema"])
    return encode_schema_payload(contract, schema_name, payload_spec["values"])


def compute_golden_checksum(data: bytes, algorithm_name: str) -> int:
    """Compute a fixture checksum independently of either generated codec."""

    if algorithm_name == "ADLER32":
        return zlib.adler32(data) & 0xFFFFFFFF
    if algorithm_name == "CRC32_ISO_HDLC":
        return zlib.crc32(data) & 0xFFFFFFFF
    if algorithm_name == "CRC32C":
        remainder = 0xFFFFFFFF
        for value in data:
            remainder ^= value
            for _ in range(8):
                remainder = (remainder >> 1) ^ (0x82F63B78 if remainder & 1 else 0)
        return remainder ^ 0xFFFFFFFF
    raise ContractError(f"no golden checksum implementation for {algorithm_name}")


def build_golden_frames(
    contract: Mapping[str, Any],
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    """Build every deterministic binary frame and its manifest metadata."""

    header = contract["header"]
    limits = contract["limits"]
    trailer_size = int(contract["trailer"]["size"])
    header_format = "<" + "".join(
        INTEGER_FORMATS[str(field["type"])] for field in header["fields"]
    )
    if struct.calcsize(header_format) != int(header["size"]):
        raise ContractError("calculated header struct does not match header size")

    kinds = enum_map(contract["frame_kinds"])
    kind_specs = {str(entry["name"]): entry for entry in contract["frame_kinds"]}
    flag_values = enum_map(contract["flags"])
    checksum_values = enum_map(contract["checksum_algorithms"])
    bootstrap_checksum_name = str(contract["bootstrap_checksum_algorithm"])
    default_checksum_name = str(contract["default_checksum_algorithm"])

    outputs: dict[str, bytes] = {}
    manifest_entries: list[dict[str, Any]] = []
    for fixture in contract["golden_fixtures"]:
        fixture_name = str(fixture["name"])
        kind_name = str(fixture["kind"])
        kind_spec = kind_specs[kind_name]
        checksum_name = (
            default_checksum_name
            if kind_spec["class"] == "data"
            else bootstrap_checksum_name
        )
        checksum_id = checksum_values[checksum_name]
        payload = encode_fixture_payload(contract, fixture)
        payload_spec = fixture["payload"]
        if (
            "schema" in payload_spec
            and payload_spec["schema"] != kind_spec["payload_schema"]
        ):
            raise ContractError(
                f"fixture {fixture_name} schema disagrees with {kind_name}"
            )
        flags = sum(flag_values[str(name)] for name in fixture.get("flags", []))
        allowed_flags = sum(
            flag_values[str(name)] for name in kind_spec["allowed_flags"]
        )
        if flags & ~allowed_flags:
            raise ContractError(f"fixture {fixture_name} uses disallowed flags")
        if flags & flag_values["OVERRUN_BEFORE"] and not (
            flags & flag_values["GAP_BEFORE"]
        ):
            raise ContractError(
                f"fixture {fixture_name} uses OVERRUN_BEFORE without GAP_BEFORE"
            )

        run_id = int(fixture.get("run_id", 0))
        sequence = int(fixture.get("sequence", 0))
        request_id = int(fixture.get("request_id", 0))
        first_sample_ticks = int(fixture.get("first_sample_ticks", 0))
        item_count = int(fixture.get("item_count", 0))
        total_length = int(header["size"]) + len(payload) + trailer_size
        if kind_spec["class"] == "data":
            if total_length != int(limits["data_frame_bytes"]):
                raise ContractError(f"fixture {fixture_name} is not 4096 bytes")
            if request_id != 0:
                raise ContractError(f"data fixture {fixture_name} has a request ID")
        else:
            if total_length > int(limits["max_control_frame_bytes"]):
                raise ContractError(f"fixture {fixture_name} exceeds control bound")
            if kind_spec["class"] == "request" and total_length > int(
                limits["max_command_frame_bytes"]
            ):
                raise ContractError(f"fixture {fixture_name} exceeds command bound")
            if request_id == 0:
                raise ContractError(
                    f"control fixture {fixture_name} needs a request ID"
                )
            if sequence != 0 or first_sample_ticks != 0 or item_count != 0:
                raise ContractError(
                    f"control fixture {fixture_name} has data-only header values"
                )

        header_bytes = struct.pack(
            header_format,
            int(contract["magic"]),
            int(contract["protocol_version"]),
            kinds[kind_name],
            flags,
            int(header["size"]),
            checksum_id,
            0,
            total_length,
            len(payload),
            run_id,
            sequence,
            request_id,
            first_sample_ticks,
            item_count,
        )
        checksum = compute_golden_checksum(header_bytes + payload, checksum_name)
        frame = header_bytes + payload + struct.pack("<I", checksum)
        output_name = f"{fixture_name}.bin"
        outputs[output_name] = frame

        manifest_entry: dict[str, Any] = {
            "checksum": f"0x{checksum:08x}",
            "checksum_algorithm": checksum_name,
            "file": output_name,
            "first_sample_ticks": first_sample_ticks,
            "flags": flags,
            "frame_sha256": hashlib.sha256(frame).hexdigest(),
            "item_count": item_count,
            "kind": kind_name,
            "payload_length": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "request_id": request_id,
            "run_id": run_id,
            "sequence": sequence,
            "total_length": len(frame),
        }
        if len(frame) <= 256:
            manifest_entry["frame_hex"] = frame.hex()
        manifest_entries.append(manifest_entry)

    return outputs, manifest_entries


def expected_outputs(
    contract: Mapping[str, Any], source_bytes: bytes
) -> dict[Path, bytes]:
    """Return all expected generated paths and exact bytes."""

    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    fixture_outputs, manifest_entries = build_golden_frames(contract)
    manifest = {
        "byte_order": contract["byte_order"],
        "fixtures": manifest_entries,
        "generator": "tools/generate_protocol.py",
        "protocol_version": int(contract["protocol_version"]),
        "source": "protocol/protocol-v1.json",
        "source_sha256": source_sha256,
    }
    outputs = {
        PYTHON_OUTPUT_PATH: render_python(contract, source_sha256),
        CPP_OUTPUT_PATH: render_cpp(contract, source_sha256),
        MANIFEST_PATH: (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    }
    outputs.update(
        {
            FIXTURE_DIRECTORY / name: contents
            for name, contents in fixture_outputs.items()
        }
    )
    return outputs


def relative_paths(paths: Iterable[Path]) -> list[str]:
    """Make generated paths concise and stable in command output."""

    return [str(path.relative_to(REPOSITORY_ROOT)) for path in paths]


def check_outputs(outputs: Mapping[Path, bytes]) -> int:
    """Return zero only when every generated output matches exactly."""

    drifted = [
        path
        for path, expected in outputs.items()
        if not path.is_file() or path.read_bytes() != expected
    ]
    if MANIFEST_PATH in outputs:
        expected_fixture_paths = {
            path for path in outputs if path.parent == FIXTURE_DIRECTORY
        }
        drifted.extend(
            path
            for path in FIXTURE_DIRECTORY.glob("*.bin")
            if path not in expected_fixture_paths
        )
    if drifted:
        print("Generated protocol files are missing or stale:", file=sys.stderr)
        for relative_path in relative_paths(drifted):
            print(f"  {relative_path}", file=sys.stderr)
        print(
            "Run: python3 tools/generate_protocol.py",
            file=sys.stderr,
        )
        return 1
    print(f"Protocol outputs are current ({len(outputs)} files).")
    return 0


def write_outputs(outputs: Mapping[Path, bytes]) -> int:
    """Write only changed outputs, preserving mtimes for identical files."""

    changed: list[Path] = []
    removed: list[Path] = []
    if MANIFEST_PATH in outputs:
        expected_fixture_paths = {
            path for path in outputs if path.parent == FIXTURE_DIRECTORY
        }
        for path in FIXTURE_DIRECTORY.glob("*.bin"):
            if path not in expected_fixture_paths:
                path.unlink()
                removed.append(path)
    for path, expected in outputs.items():
        if path.is_file() and path.read_bytes() == expected:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(expected)
        changed.append(path)
    if changed or removed:
        print("Generated protocol files:")
        for relative_path in relative_paths(changed):
            print(f"  {relative_path}")
        for relative_path in relative_paths(removed):
            print(f"  removed {relative_path}")
    else:
        print(f"Protocol outputs already current ({len(outputs)} files).")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report generated-file drift without changing the workspace",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        contract, source_bytes = load_contract()
        validate_contract(contract)
        outputs = expected_outputs(contract, source_bytes)
    except (ContractError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Invalid protocol contract: {error}", file=sys.stderr)
        return 2
    if args.check:
        return check_outputs(outputs)
    return write_outputs(outputs)


if __name__ == "__main__":
    raise SystemExit(main())
