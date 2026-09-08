#!/usr/bin/env python3
"""Generate versioned protocol constants and deterministic golden frames."""

from __future__ import annotations

import argparse
import copy
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
V2_SOURCE_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
PYTHON_OUTPUT_PATH = (
    REPOSITORY_ROOT / "daq_api/src/thingdone_daq/_generated/protocol_constants.py"
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


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of silently keeping the last value."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_contract(path: Path = SOURCE_PATH) -> tuple[dict[str, Any], bytes]:
    """Read the canonical JSON source and return it with its exact bytes."""

    source_bytes = path.read_bytes()
    contract = json.loads(source_bytes, object_pairs_hook=_unique_json_object)
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


def checksum_enabled(contract: Mapping[str, Any], entry: Mapping[str, Any]) -> bool:
    """Return whether a checksum is enabled in the contract's own version."""

    key = f"enabled_in_v{int(contract['protocol_version'])}"
    return bool(entry[key])


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


def field_width(
    field: Mapping[str, Any],
    schemas: Mapping[str, Mapping[str, Any]] | None = None,
) -> int:
    """Return the encoded width for a machine-readable field definition."""

    field_type = str(field["type"])
    if field_type in INTEGER_WIDTHS:
        return INTEGER_WIDTHS[field_type]
    if field_type in {"bytes", "nul_ascii", "u8_array"}:
        return int(field["count"])
    if field_type == "repeated_u16":
        return int(field["count"]) * 2
    if field_type == "repeated_u16_pair":
        return int(field["count"]) * 4
    if field_type == "repeated_schema":
        if schemas is None:
            raise ContractError("repeated_schema needs the payload schema table")
        schema_name = str(field["schema"])
        if schema_name not in schemas:
            raise ContractError(f"unknown repeated payload schema: {schema_name}")
        return int(field["count"]) * int(schemas[schema_name]["size"])
    raise ContractError(f"unsupported field type: {field_type}")


def validate_fields(
    owner: str,
    size: int,
    fields: Sequence[Mapping[str, Any]],
    schemas: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Require fields to cover their declared byte region exactly once."""

    names = [str(field["name"]) for field in fields]
    if len(names) != len(set(names)):
        raise ContractError(f"{owner} contains duplicate field names")
    occupancy: list[str | None] = [None] * size
    for field in fields:
        name = str(field["name"])
        offset = int(field["offset"])
        width = field_width(field, schemas)
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

    combined = contract["combined_acquisition"]
    profile_values = enum_map(contract["enums"]["configuration_profile"])
    validate_enum_width(
        "configuration_profile",
        contract["enums"]["configuration_profile"],
        16,
    )
    if any(value == 0 or value & (value - 1) for value in profile_values.values()):
        raise ContractError("every configuration profile must be one nonzero bit")
    known_profile_mask = sum(profile_values.values())
    if int(combined["supported_configuration_mask"]) != known_profile_mask:
        raise ContractError("combined profile mask must advertise all six profiles")
    if (
        int(combined["adc_dma_ring_depth"]) != 8
        or int(combined["adc_pairs_per_buffer"]) != int(adc["items_per_frame"])
        or int(combined["adc_pair_bytes"]) != int(adc["bytes_per_item"])
        or int(combined["dma_alignment_bytes"]) != 32
        or int(combined["adc_dma_ring_bytes"])
        != int(combined["adc_dma_ring_depth"])
        * (
            (int(adc["payload_bytes"]) + int(combined["dma_alignment_bytes"]) - 1)
            // int(combined["dma_alignment_bytes"])
        )
        * int(combined["dma_alignment_bytes"])
        or list(combined["adc_edma_channels"]) != [0, 1]
        or list(combined["adc_edma_priorities"]) != [2, 1]
        or list(combined["adc_dmamux_sources"]) != [24, 88]
        or int(combined["packet_buffer_count"])
        != int(combined["packet_primary_count"]) + int(combined["packet_reserve_count"])
        or int(combined["packet_buffer_count"])
        != int(contract["gpio_capture"]["packet_buffer_count"])
        or int(combined["packet_ready_queue_capacity"])
        != int(combined["packet_buffer_count"])
        or int(combined["packet_transmit_queue_capacity"])
        != int(combined["packet_buffer_count"])
    ):
        raise ContractError("combined acquisition storage/resources are inconsistent")
    payload_rate = (
        int(adc["payload_bytes"]) * int(timing["timestamp_hz"]) // adc_coverage
    )
    framed_rate = (
        int(limits["data_frame_bytes"]) * int(timing["timestamp_hz"])
        + adc_coverage // 2
    ) // adc_coverage
    if (
        int(combined["nominal_payload_bytes_per_second_per_stream"]) != payload_rate
        or int(combined["nominal_framed_bytes_per_second_per_stream"]) != framed_rate
    ):
        raise ContractError("combined nominal byte rates are inconsistent")

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
    gpio_capture = contract["gpio_capture"]
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

    adc_trigger = contract["adc_trigger"]
    positive_adc_trigger_fields = (
        "pit_clock_hz",
        "dwt_clock_hz",
        "gpio_master_rate_hz",
        "pair_rate_hz",
        "ipg_clock_hz",
        "chain_length",
        "phase_ipg_cycles",
        "completion_expected_dwt_cycles",
        "completion_tolerance_dwt_cycles",
        "diagnostic_deadline_us",
        "diagnostic_poll_limit",
        "irq_priority",
    )
    if any(int(adc_trigger[name]) <= 0 for name in positive_adc_trigger_fields):
        raise ContractError("ADC trigger schedule bounds must be positive")
    if (
        int(adc_trigger["pit_clock_hz"]) != int(gpio_clock["pit_clock_hz"])
        or int(adc_trigger["gpio_master_rate_hz"]) != int(timing["gpio_sample_rate_hz"])
        or int(adc_trigger["pair_rate_hz"]) != int(timing["adc_pair_rate_hz"])
        or int(adc_trigger["ipg_clock_hz"]) != int(adc_initialization["ipg_clock_hz"])
    ):
        raise ContractError("ADC trigger clocks/rates disagree with shared timing")
    pit_clock_hz = int(adc_trigger["pit_clock_hz"])
    master_rate_hz = int(adc_trigger["gpio_master_rate_hz"])
    pair_rate_hz = int(adc_trigger["pair_rate_hz"])
    if (
        pit_clock_hz % master_rate_hz
        or master_rate_hz % pair_rate_hz
        or pit_clock_hz // master_rate_hz - 1
        != int(adc_trigger["gpio_master_pit_load"])
        or master_rate_hz // pair_rate_hz - 1 != int(adc_trigger["pair_pit_load"])
    ):
        raise ContractError("ADC trigger PIT divisors are not exact")
    if (
        int(adc_trigger["gpio_master_pit_channel"]) != int(gpio_capture["pit_channel"])
        or int(adc_trigger["pair_pit_channel"]) != 1
        or int(adc_trigger["predivider"]) != 0
        or int(adc_trigger["chain_length"]) != 1
        or list(adc_trigger["xbar_inputs"]) != [57, 57]
        or list(adc_trigger["xbar_outputs"]) != [103, 107]
        or list(adc_trigger["queues"]) != [0, 4]
    ):
        raise ContractError("ADC trigger route identities changed")
    initial_delays = [int(value) for value in adc_trigger["initial_delays"]]
    effective_delays = [int(value) for value in adc_trigger["effective_delays"]]
    if (
        initial_delays != [0, 75]
        or effective_delays != [value + 1 for value in initial_delays]
        or effective_delays[1] - effective_delays[0]
        != int(adc_trigger["phase_ipg_cycles"])
    ):
        raise ContractError("ADC trigger initial-delay arithmetic is inconsistent")
    phase_cycles = int(adc_trigger["phase_ipg_cycles"])
    ipg_clock_hz = int(adc_trigger["ipg_clock_hz"])
    dwt_clock_hz = int(adc_trigger["dwt_clock_hz"])
    if (
        phase_cycles * int(timing["timestamp_hz"])
        != int(timing["adc1_phase_ticks"]) * ipg_clock_hz
        or phase_cycles * dwt_clock_hz
        != int(adc_trigger["completion_expected_dwt_cycles"]) * ipg_clock_hz
    ):
        raise ContractError("ADC trigger phase does not map exactly across clocks")
    diagnostic_deadline_cycles = (
        dwt_clock_hz * int(adc_trigger["diagnostic_deadline_us"]) // 1_000_000
    )
    if not 0 < diagnostic_deadline_cycles <= 0xFFFFFFFF:
        raise ContractError("ADC trigger diagnostic deadline must fit DWT")

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
    for enum_name in (
        "adc_configuration_flag",
        "adc_initialization_error",
        "adc_trigger_configuration_flag",
        "adc_trigger_error",
    ):
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
            schemas,
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
        "configuration_profile": 16,
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
        "adc_trigger_configuration_flag": 16,
        "adc_trigger_error": 32,
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


def validate_v2_contract(
    contract: Mapping[str, Any],
    v1_contract: Mapping[str, Any],
    v1_source_bytes: bytes,
) -> None:
    """Validate the isolated auxiliary-input extension and its generation plan."""

    if int(contract["protocol_version"]) != 2:
        raise ContractError("the auxiliary-input contract must be protocol version 2")
    if contract.get("status") != "release-1.1.0" or contract.get("extension") != (
        "aux-input-bank-fixed-1mhz-temperature"
    ):
        raise ContractError("protocol v2 must identify the release input contract")
    if contract["byte_order"] != "little" or int(contract["magic"]) != 0xDEADBEEF:
        raise ContractError("protocol v2 must retain the v1 little-endian envelope")

    extends = contract["extends"]
    v1_sha256 = hashlib.sha256(v1_source_bytes).hexdigest()
    if (
        int(extends["protocol_version"]) != 1
        or extends["source"] != "protocol/protocol-v1.json"
        or extends["source_sha256"] != v1_sha256
    ):
        raise ContractError("protocol v2 does not pin the exact protocol-v1 source")
    for key in (
        "magic",
        "byte_order",
        "scalar_types",
        "header",
        "trailer",
        "flags",
        "bootstrap_checksum_algorithm",
        "default_checksum_algorithm",
    ):
        if contract[key] != v1_contract[key]:
            raise ContractError(f"protocol v2 unexpectedly changes frozen v1 {key}")
    v1_checksums = [
        (str(entry["name"]), int(entry["value"]), bool(entry["enabled_in_v1"]))
        for entry in v1_contract["checksum_algorithms"]
    ]
    v2_checksums = [
        (str(entry["name"]), int(entry["value"]), bool(entry["enabled_in_v2"]))
        for entry in contract["checksum_algorithms"]
    ]
    if v2_checksums != v1_checksums:
        raise ContractError("protocol v2 changes the frozen checksum IDs or support")
    normalized_v2_kinds = []
    for entry in contract["frame_kinds"]:
        normalized = dict(entry)
        normalized.pop("payload_schema_by_aux_bank_mode", None)
        normalized_v2_kinds.append(normalized)
    temperature_kinds = [
        {
            "name": "GET_TEMPERATURE_REQUEST",
            "value": 26,
            "class": "request",
            "payload_schema": "empty",
            "allowed_flags": [],
            "response_kind": "GET_TEMPERATURE_RESPONSE",
        },
        {
            "name": "GET_TEMPERATURE_RESPONSE",
            "value": 154,
            "class": "response",
            "payload_schema": "temperature_response",
            "error_payload_schema": "response_prefix",
            "allowed_flags": ["RESPONSE_ERROR"],
        },
    ]
    if normalized_v2_kinds != v1_contract["frame_kinds"] + temperature_kinds:
        raise ContractError("protocol v2 unexpectedly changes frozen frame kinds")
    if contract["command_kinds"] != v1_contract["command_kinds"] + [
        {
            "name": "GET_TEMPERATURE",
            "value": 26,
            "request_kind": "GET_TEMPERATURE_REQUEST",
            "response_kind": "GET_TEMPERATURE_RESPONSE",
            "optional": True,
        }
    ]:
        raise ContractError("protocol v2 unexpectedly changes frozen command kinds")
    for entry in contract["frame_kinds"][:2]:
        layouts_by_mode = entry.get("payload_schema_by_aux_bank_mode")
        if layouts_by_mode != {
            "DISABLED": entry["payload_schema"],
            "INPUT": "adc_aux_data" if entry["name"] == "ADC_DATA" else "gpio_aux_data",
        }:
            raise ContractError("protocol v2 data-kind layout mapping is inconsistent")

    generated = contract["generated_outputs"]
    expected_output_keys = {
        "python_constants",
        "cpp_constants",
        "fixture_directory",
        "fixture_manifest",
    }
    if set(generated) != expected_output_keys:
        raise ContractError("protocol v2 generated outputs are incomplete")
    generated_paths = [Path(str(value)) for value in generated.values()]
    if len(set(generated_paths)) != len(generated_paths):
        raise ContractError("protocol v2 generated output paths must be disjoint")
    for path in generated_paths:
        if path.is_absolute() or ".." in path.parts:
            raise ContractError(
                "protocol v2 generated outputs must stay in the repository"
            )
    v1_paths = {
        PYTHON_OUTPUT_PATH.relative_to(REPOSITORY_ROOT),
        CPP_OUTPUT_PATH.relative_to(REPOSITORY_ROOT),
        FIXTURE_DIRECTORY.relative_to(REPOSITORY_ROOT),
        MANIFEST_PATH.relative_to(REPOSITORY_ROOT),
    }
    if set(generated_paths) & v1_paths:
        raise ContractError("protocol v2 generated outputs overlap frozen v1 outputs")
    fixture_directory = Path(str(generated["fixture_directory"]))
    if Path(str(generated["fixture_manifest"])).parent != fixture_directory:
        raise ContractError("protocol v2 fixture manifest is outside its directory")

    scalar_types = contract["scalar_types"]
    if set(scalar_types) != set(INTEGER_WIDTHS):
        raise ContractError("protocol v2 scalar table is incomplete")
    for name, width in INTEGER_WIDTHS.items():
        scalar = scalar_types[name]
        if int(scalar["width"]) != width or scalar["signed"] is not False:
            raise ContractError(f"protocol v2 {name} scalar is inconsistent")

    header = contract["header"]
    trailer = contract["trailer"]
    validate_fields("v2.header", int(header["size"]), header["fields"])
    if int(trailer["size"]) != 4 or trailer["type"] != "u32":
        raise ContractError("protocol v2 trailer must remain one uint32")
    limits = contract["limits"]
    if (
        int(limits["data_frame_bytes"]) != 4096
        or int(limits["max_data_frame_bytes"]) != 4096
        or int(limits["min_data_frame_bytes"]) != 2072
        or int(limits["min_frame_bytes"]) != int(header["size"]) + int(trailer["size"])
        or int(limits["max_command_frame_bytes"])
        != int(limits["min_frame_bytes"]) + int(limits["max_command_payload_bytes"])
    ):
        raise ContractError("protocol v2 frame bounds are inconsistent")

    schemas = contract["payload_schemas"]
    for schema_name, schema in schemas.items():
        validate_fields(
            f"v2.payload_schemas.{schema_name}",
            int(schema["size"]),
            schema["fields"],
            schemas,
        )
    if (
        int(schemas["configure_request"]["size"]) != 16
        or int(schemas["configure_response"]["size"]) != 20
        or int(schemas["info_response"]["size"]) != 680
        or int(schemas["status_response"]["size"]) != 1476
        or int(schemas["gpio_capture_diagnostic_response"]["size"]) != 272
        or int(schemas["rate_profile_info"]["size"]) != 48
    ):
        raise ContractError("protocol v2 control extension sizes are inconsistent")

    kind_specs = {str(entry["name"]): entry for entry in contract["frame_kinds"]}
    kinds = enum_map(contract["frame_kinds"])
    validate_enum_width("v2.frame_kinds", contract["frame_kinds"], 8)
    observed_command_payload_max = 0
    for command in contract["command_kinds"]:
        request = kind_specs[str(command["request_kind"])]
        response = kind_specs[str(command["response_kind"])]
        if (
            int(command["value"]) != int(request["value"])
            or int(response["value"]) != (int(command["value"]) | 0x80)
            or request.get("response_kind") != response["name"]
        ):
            raise ContractError(f"v2 command {command['name']} mapping is inconsistent")
        request_size = int(schemas[str(request["payload_schema"])]["size"])
        observed_command_payload_max = max(observed_command_payload_max, request_size)
    if observed_command_payload_max != int(limits["max_command_payload_bytes"]):
        raise ContractError("protocol v2 command payload bound is not exact")

    for enum_name, bits in {
        "response_status": 8,
        "error_code": 16,
        "device_state": 8,
        "stream_mask": 8,
        "configuration_profile": 16,
        "capability_bits": 32,
        "source": 8,
        "aux_bank_mode": 8,
        "rate_profile": 8,
    }.items():
        enum_map(contract["enums"][enum_name])
        validate_enum_width(enum_name, contract["enums"][enum_name], bits)
    modes = enum_map(contract["enums"]["aux_bank_mode"])
    if modes != {"DISABLED": 0, "INPUT": 1}:
        raise ContractError("protocol v2 auxiliary modes must be DISABLED and INPUT")
    auxiliary = contract["auxiliary_input"]
    if (
        auxiliary["default_mode"] != "DISABLED"
        or auxiliary["supported_modes"] != ["DISABLED", "INPUT"]
        or auxiliary["direction_granularity"] != "whole_bank"
        or auxiliary["output_supported"] is not False
    ):
        raise ContractError("protocol v2 auxiliary direction contract is unsafe")

    layouts = auxiliary["layouts"]
    data_layouts = contract["data_layouts"]
    expected_layouts = {
        "DISABLED": (8, 1, 4048, 1012, 4096),
        "INPUT": (16, 2, 2024, 506, 2072),
    }
    for mode, (
        width,
        item_bytes,
        gpio_items,
        adc_items,
        adc_frame_bytes,
    ) in expected_layouts.items():
        layout = layouts[mode]
        if (
            int(layout["gpio_width_bits"]) != width
            or int(layout["gpio_bytes_per_item"]) != item_bytes
            or int(layout["gpio_items_per_frame"]) != gpio_items
            or int(layout["gpio_payload_bytes"]) != gpio_items * item_bytes
            or int(layout["gpio_total_frame_bytes"]) != 4096
            or int(layout["adc_items_per_frame"]) != adc_items
            or int(layout["adc_payload_bytes"]) != adc_items * 4
            or int(layout["adc_total_frame_bytes"]) != adc_frame_bytes
        ):
            raise ContractError(f"protocol v2 {mode} frame layout is inconsistent")
    if (
        data_layouts["gpio"]["pins_by_bit"] != list(range(6, 14))
        or data_layouts["gpio_aux_input"]["pins_by_bit"]
        != [*range(6, 14), *range(16, 24)]
        or data_layouts["gpio_aux_input"]["byte_order"] != "little"
    ):
        raise ContractError("protocol v2 GPIO wire bit order is inconsistent")

    timing = contract["timing"]
    timestamp_hz = int(timing["timestamp_hz"])
    pit_hz = int(timing["pit_clock_hz"])
    ipg_hz = int(timing["ipg_clock_hz"])
    dwt_hz = int(timing["dwt_clock_hz"])
    rate_profiles = contract["rate_profiles"]
    rate_enum = enum_map(contract["enums"]["rate_profile"])
    if len(rate_profiles) != 5 or rate_enum != {
        str(profile["name"]): int(profile["value"]) for profile in rate_profiles
    }:
        raise ContractError("protocol v2 rate profile enum and table disagree")
    if int(timing["supported_rate_profile_mask"]) != sum(
        1 << int(profile["value"]) for profile in rate_profiles
    ):
        raise ContractError("protocol v2 supported rate mask is inconsistent")
    for profile in rate_profiles:
        adc_rate = int(profile["adc_pair_rate_hz"])
        gpio_rate = int(profile["gpio_sample_rate_hz"])
        if (
            gpio_rate != int(profile["gpio_to_adc_ratio"]) * adc_rate
            or timestamp_hz % adc_rate
            or timestamp_hz % gpio_rate
            or pit_hz % gpio_rate
            or ipg_hz % (2 * adc_rate)
            or dwt_hz % (2 * adc_rate)
            or int(profile["adc_pair_period_ticks"]) != timestamp_hz // adc_rate
            or int(profile["adc1_phase_ticks"]) != timestamp_hz // (2 * adc_rate)
            or int(profile["gpio_sample_period_ticks"]) != timestamp_hz // gpio_rate
            or int(profile["gpio_master_pit_divider"]) != pit_hz // gpio_rate
            or int(profile["gpio_master_pit_load"])
            != int(profile["gpio_master_pit_divider"]) - 1
            or int(profile["adc_pair_pit_divider"]) != gpio_rate // adc_rate
            or int(profile["adc_pair_pit_load"]) != gpio_rate // adc_rate - 1
            or int(profile["adc1_phase_ipg_cycles"]) != ipg_hz // (2 * adc_rate)
            or int(profile["completion_expected_dwt_cycles"])
            != dwt_hz // (2 * adc_rate)
        ):
            raise ContractError(f"rate profile {profile['name']} is not exact")
        for mode, layout in layouts.items():
            adc_coverage = int(layout["adc_items_per_frame"]) * int(
                profile["adc_pair_period_ticks"]
            )
            gpio_coverage = int(layout["gpio_items_per_frame"]) * int(
                profile["gpio_sample_period_ticks"]
            )
            if (
                adc_coverage * (4 // int(profile["gpio_to_adc_ratio"])) != gpio_coverage
                or int(profile["frame_coverage_ticks"][mode]) != adc_coverage
            ):
                raise ContractError(
                    f"rate profile {profile['name']} {mode} coverage is inconsistent"
                )

    fixtures = contract["golden_fixtures"]
    fixture_names = [str(fixture["name"]) for fixture in fixtures]
    if len(fixture_names) != len(set(fixture_names)):
        raise ContractError("protocol v2 seed fixture names must be unique")
    if {str(fixture["kind"]) for fixture in fixtures} != set(kinds):
        raise ContractError("protocol v2 seed fixtures must cover every frame kind")

    plan = contract["golden_vector_plan"]
    for switch in (
        "generate_gpio_mode_profile_matrix",
        "generate_configure_mode_profile_matrix",
        "generate_info_mode_profile_matrix",
    ):
        if plan.get(switch) is not True:
            raise ContractError(f"protocol v2 golden-vector plan must enable {switch}")
    malformed = plan["malformed_cases"]
    malformed_names = [str(case["name"]) for case in malformed]
    if len(malformed_names) != len(set(malformed_names)):
        raise ContractError("protocol v2 malformed fixture names must be unique")
    valid_targets = {"configure_request", "configure_response", "info_response"}
    if any(str(case["target"]) not in valid_targets for case in malformed):
        raise ContractError("protocol v2 malformed fixture target is unknown")
    if any(not str(case.get("expected_rejection", "")) for case in malformed):
        raise ContractError("protocol v2 malformed fixtures need rejection reasons")
    required_cases = {
        "unsupported-rates",
        "wrong-four-to-one-ratio",
        "mixed-bank-mode",
        "duplicate-aux-pins",
        "bad-gpio-width",
        "bad-frame-counts",
        "nonintegral-timestamps",
        "contradictory-configure-echo",
    }
    if not required_cases <= set(malformed_names):
        raise ContractError("protocol v2 malformed fixture coverage is incomplete")


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
    combined = contract["combined_acquisition"]
    gpio_capture_diagnostic = contract["gpio_capture_diagnostic"]
    adc_initialization = contract["adc_initialization"]
    adc_trigger = contract["adc_trigger"]
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
        f"SUPPORTED_CONFIGURATION_MASK = {int(combined['supported_configuration_mask'])}",
        f"ADC_DMA_RING_DEPTH = {int(combined['adc_dma_ring_depth'])}",
        f"ADC_PAIRS_PER_BUFFER = {int(combined['adc_pairs_per_buffer'])}",
        f"ADC_PAIR_BYTES = {int(combined['adc_pair_bytes'])}",
        f"ADC_DMA_RING_BYTES = {int(combined['adc_dma_ring_bytes'])}",
        f"ADC_EDMA_CHANNELS = {tuple(combined['adc_edma_channels'])!r}",
        f"ADC_EDMA_PRIORITIES = {tuple(combined['adc_edma_priorities'])!r}",
        f"ADC_DMAMUX_SOURCES = {tuple(combined['adc_dmamux_sources'])!r}",
        f"ADC_DMA_IRQ_PRIORITY = {int(combined['adc_dma_irq_priority'])}",
        f"GPIO_DMA_IRQ_PRIORITY = {int(combined['gpio_dma_irq_priority'])}",
        f"PACKET_BUFFER_COUNT = {int(combined['packet_buffer_count'])}",
        f"PACKET_PRIMARY_COUNT = {int(combined['packet_primary_count'])}",
        f"PACKET_RESERVE_COUNT = {int(combined['packet_reserve_count'])}",
        f"PACKET_READY_QUEUE_CAPACITY = {int(combined['packet_ready_queue_capacity'])}",
        f"PACKET_TRANSMIT_QUEUE_CAPACITY = {int(combined['packet_transmit_queue_capacity'])}",
        f"COMMAND_QUEUE_CAPACITY = {int(combined['command_queue_capacity'])}",
        f"RESPONSE_QUEUE_CAPACITY = {int(combined['response_queue_capacity'])}",
        (
            "NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM = "
            f"{int(combined['nominal_payload_bytes_per_second_per_stream'])}"
        ),
        (
            "NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM = "
            f"{int(combined['nominal_framed_bytes_per_second_per_stream'])}"
        ),
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
        f"ADC_TRIGGER_PIT_CLOCK_HZ = {int(adc_trigger['pit_clock_hz'])}",
        f"ADC_TRIGGER_DWT_CLOCK_HZ = {int(adc_trigger['dwt_clock_hz'])}",
        f"ADC_TRIGGER_GPIO_MASTER_RATE_HZ = {int(adc_trigger['gpio_master_rate_hz'])}",
        f"ADC_TRIGGER_PAIR_RATE_HZ = {int(adc_trigger['pair_rate_hz'])}",
        f"ADC_TRIGGER_IPG_CLOCK_HZ = {int(adc_trigger['ipg_clock_hz'])}",
        f"ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL = {int(adc_trigger['gpio_master_pit_channel'])}",
        f"ADC_TRIGGER_PAIR_PIT_CHANNEL = {int(adc_trigger['pair_pit_channel'])}",
        f"ADC_TRIGGER_GPIO_MASTER_PIT_LOAD = {int(adc_trigger['gpio_master_pit_load'])}",
        f"ADC_TRIGGER_PAIR_PIT_LOAD = {int(adc_trigger['pair_pit_load'])}",
        f"ADC_TRIGGER_PREDIVIDER = {int(adc_trigger['predivider'])}",
        f"ADC_TRIGGER_CHAIN_LENGTH = {int(adc_trigger['chain_length'])}",
        f"ADC_TRIGGER_XBAR_INPUTS = {tuple(adc_trigger['xbar_inputs'])!r}",
        f"ADC_TRIGGER_XBAR_OUTPUTS = {tuple(adc_trigger['xbar_outputs'])!r}",
        f"ADC_TRIGGER_QUEUES = {tuple(adc_trigger['queues'])!r}",
        f"ADC_TRIGGER_INITIAL_DELAYS = {tuple(adc_trigger['initial_delays'])!r}",
        f"ADC_TRIGGER_EFFECTIVE_DELAYS = {tuple(adc_trigger['effective_delays'])!r}",
        f"ADC_TRIGGER_PHASE_IPG_CYCLES = {int(adc_trigger['phase_ipg_cycles'])}",
        f"ADC_COMPLETION_EXPECTED_DWT_CYCLES = {int(adc_trigger['completion_expected_dwt_cycles'])}",
        f"ADC_COMPLETION_TOLERANCE_DWT_CYCLES = {int(adc_trigger['completion_tolerance_dwt_cycles'])}",
        f"ADC_TRIGGER_DIAGNOSTIC_DEADLINE_US = {int(adc_trigger['diagnostic_deadline_us'])}",
        f"ADC_TRIGGER_DIAGNOSTIC_POLL_LIMIT = {int(adc_trigger['diagnostic_poll_limit'])}",
        f"ADC_TRIGGER_IRQ_PRIORITY = {int(adc_trigger['irq_priority'])}",
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
            "ConfigurationProfile",
            contract["enums"]["configuration_profile"],
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
        python_enum(
            "AdcTriggerConfigurationFlag",
            contract["enums"]["adc_trigger_configuration_flag"],
            base="IntFlag",
            include_none=True,
        )
    )
    lines.extend(
        python_enum(
            "AdcTriggerError",
            contract["enums"]["adc_trigger_error"],
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
        if checksum_enabled(contract, entry):
            lines.append(f"        ChecksumAlgorithm.{entry['name']},")
    lines.extend(["    }", ")", ""])
    supported_checksum_mask = sum(
        1 << checksum_values[str(entry["name"])]
        for entry in checksums
        if checksum_enabled(contract, entry)
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
        "KNOWN_CONFIGURATION_PROFILE_MASK = "
        + str(
            sum(
                int(entry["value"])
                for entry in contract["enums"]["configuration_profile"]
            )
        )
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
    lines.append(
        "KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK = "
        + str(
            sum(
                int(entry["value"])
                for entry in contract["enums"]["adc_trigger_configuration_flag"]
            )
        )
    )
    lines.append(
        "KNOWN_ADC_TRIGGER_ERROR_MASK = "
        + str(
            sum(int(entry["value"]) for entry in contract["enums"]["adc_trigger_error"])
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


def render_python_v2(contract: Mapping[str, Any], source_sha256: str) -> bytes:
    """Render the disjoint experimental-v2 Python constants module."""

    rendered = render_python(contract, source_sha256).decode()
    rendered = rendered.replace(
        '"""Generated protocol-v1 constants. Do not edit by hand.',
        '"""Generated experimental protocol-v2 constants. Do not edit by hand.',
        1,
    ).replace(
        "Source: protocol/protocol-v1.json", "Source: protocol/protocol-v2.json", 1
    )

    auxiliary = contract["auxiliary_input"]
    resources = auxiliary["provisional_resources"]
    banks = auxiliary["pin_banks"]
    timing = contract["timing"]
    layouts = auxiliary["layouts"]
    extension: list[str] = [
        "",
        "",
        "# Experimental protocol-v2 auxiliary-input extension.",
    ]
    extension.extend(python_enum("AuxBankMode", contract["enums"]["aux_bank_mode"]))
    extension.extend(
        python_enum("TemperatureStatus", contract["enums"]["temperature_status"])
    )
    extension.extend(python_enum("RateProfile", contract["enums"]["rate_profile"]))
    extension.extend(
        [
            f"MIN_DATA_FRAME_BYTES = {int(contract['limits']['min_data_frame_bytes'])}",
            f"PIT_CLOCK_HZ = {int(timing['pit_clock_hz'])}",
            f"IPG_CLOCK_HZ = {int(timing['ipg_clock_hz'])}",
            f"DWT_CLOCK_HZ = {int(timing['dwt_clock_hz'])}",
            ("DEFAULT_AUX_BANK_MODE = AuxBankMode." + str(auxiliary["default_mode"])),
            (
                "DEFAULT_RATE_PROFILE = RateProfile."
                + str(timing["default_rate_profile"])
            ),
            "SUPPORTED_AUX_BANK_MODES = frozenset(AuxBankMode)",
            "SUPPORTED_RATE_PROFILES = frozenset(RateProfile)",
            (
                "SUPPORTED_AUX_BANK_MODE_MASK = "
                + str(
                    sum(
                        1 << int(entry["value"])
                        for entry in contract["enums"]["aux_bank_mode"]
                    )
                )
            ),
            (
                "SUPPORTED_RATE_PROFILE_MASK = "
                + str(int(timing["supported_rate_profile_mask"]))
            ),
            (
                "PRIMARY_GPIO_PINS_BY_BIT = "
                + repr(tuple(banks["primary"]["teensy_pins"]))
            ),
            (
                "AUX_GPIO_PINS_BY_BIT = "
                + repr(tuple(banks["auxiliary"]["teensy_pins"]))
            ),
            (
                "GPIO_16_PINS_BY_BIT = "
                + repr(tuple(contract["data_layouts"]["gpio_aux_input"]["pins_by_bit"]))
            ),
            (
                "PRIMARY_GPIO_PORT_BITS_BY_WIRE_BIT = "
                + repr(tuple(banks["primary"]["standard_gpio_bits_by_wire_bit"]))
            ),
            (
                "AUX_GPIO_PORT_BITS_BY_WIRE_BIT = "
                + repr(tuple(banks["auxiliary"]["standard_gpio_bits_by_wire_bit"]))
            ),
            f"PRIMARY_GPIO_CAPTURE_MASK = 0x{int(banks['primary']['aggregate_mask']):08X}",
            f"AUX_GPIO_CAPTURE_MASK = 0x{int(banks['auxiliary']['aggregate_mask']):08X}",
            f"PRIMARY_GPIO_STANDARD_PORT = {int(banks['primary']['standard_gpio'])}",
            f"AUX_GPIO_STANDARD_PORT = {int(banks['auxiliary']['standard_gpio'])}",
            f"PRIMARY_GPIO_FAST_PORT = {int(banks['primary']['fast_gpio'])}",
            f"AUX_GPIO_FAST_PORT = {int(banks['auxiliary']['fast_gpio'])}",
            f"PRIMARY_GPIO_FAST_SELECT_GPR = {int(banks['primary']['fast_select_gpr'])}",
            f"AUX_GPIO_FAST_SELECT_GPR = {int(banks['auxiliary']['fast_select_gpr'])}",
            f"AUX_GPIO_XBAR_OUTPUT = {int(resources['auxiliary_xbar_output'])}",
            f"AUX_GPIO_DMAMUX_SOURCE = {int(resources['auxiliary_dmamux_source'])}",
            f"AUX_GPIO_EDMA_CHANNEL = {int(resources['auxiliary_edma_channel'])}",
            f"AUX_GPIO_EDMA_PRIORITY = {int(resources['enabled_mode_edma_priorities'][3])}",
            f"AUX_GPIO_RAW_RING_DEPTH = {int(resources['raw_ring_depth_per_bank'])}",
            f"GPIO_RAW_WORD_BYTES_PER_BANK = {int(resources['raw_word_bytes_per_bank'])}",
            f"PAIRED_GPIO_JOIN_REQUIRED = {bool(resources['paired_join_required'])!r}",
            "",
            "AUX_BANK_LAYOUTS: dict[AuxBankMode, dict[str, int]] = {",
        ]
    )
    for mode_name, layout in layouts.items():
        extension.append(f"    AuxBankMode.{mode_name}: {{")
        for key, value in layout.items():
            extension.append(f'        "{key}": {int(value)},')
        extension.append("    },")
    extension.extend(
        ["}", "", "RATE_PROFILE_TIMING: dict[RateProfile, dict[str, int]] = {"]
    )
    for profile in contract["rate_profiles"]:
        extension.append(f"    RateProfile.{profile['name']}: {{")
        for key in (
            "adc_pair_rate_hz",
            "gpio_sample_rate_hz",
            "adc_pair_period_ticks",
            "adc1_phase_ticks",
            "gpio_sample_period_ticks",
            "gpio_master_pit_divider",
            "gpio_master_pit_load",
            "adc_pair_pit_divider",
            "adc_pair_pit_load",
            "adc_etc_predivider",
            "adc_etc_chain_length",
            "adc0_initial_delay",
            "adc1_initial_delay",
            "adc0_effective_delay",
            "adc1_effective_delay",
            "adc1_phase_ipg_cycles",
            "completion_expected_dwt_cycles",
        ):
            extension.append(f'        "{key}": {int(profile[key])},')
        extension.append(
            '        "disabled_frame_coverage_ticks": '
            f"{int(profile['frame_coverage_ticks']['DISABLED'])},"
        )
        extension.append(
            '        "input_frame_coverage_ticks": '
            f"{int(profile['frame_coverage_ticks']['INPUT'])},"
        )
        extension.append("    },")
    extension.extend(["}", ""])
    return (rendered.rstrip() + "\n" + "\n".join(extension)).encode()


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
    combined = contract["combined_acquisition"]
    gpio_capture_diagnostic = contract["gpio_capture_diagnostic"]
    adc_initialization = contract["adc_initialization"]
    adc_trigger = contract["adc_trigger"]
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
        "namespace thingdaq::protocol_v1 {",
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
        f"inline constexpr std::uint16_t kSupportedConfigurationMask = {int(combined['supported_configuration_mask'])}U;",
        f"inline constexpr std::uint8_t kAdcDmaRingDepth = {int(combined['adc_dma_ring_depth'])}U;",
        f"inline constexpr std::uint16_t kAdcPairsPerBuffer = {int(combined['adc_pairs_per_buffer'])}U;",
        f"inline constexpr std::uint8_t kAdcPairBytes = {int(combined['adc_pair_bytes'])}U;",
        f"inline constexpr std::uint32_t kAdcDmaRingBytes = {int(combined['adc_dma_ring_bytes'])}U;",
        "inline constexpr std::uint8_t kAdcEdmaChannels[] = {"
        + ", ".join(f"{int(value)}U" for value in combined["adc_edma_channels"])
        + "};",
        "inline constexpr std::uint8_t kAdcEdmaPriorities[] = {"
        + ", ".join(f"{int(value)}U" for value in combined["adc_edma_priorities"])
        + "};",
        "inline constexpr std::uint8_t kAdcDmamuxSources[] = {"
        + ", ".join(f"{int(value)}U" for value in combined["adc_dmamux_sources"])
        + "};",
        f"inline constexpr std::uint8_t kAdcDmaIrqPriority = {int(combined['adc_dma_irq_priority'])}U;",
        f"inline constexpr std::uint8_t kGpioDmaIrqPriority = {int(combined['gpio_dma_irq_priority'])}U;",
        f"inline constexpr std::uint16_t kPacketBufferCount = {int(combined['packet_buffer_count'])}U;",
        f"inline constexpr std::uint16_t kPacketPrimaryCount = {int(combined['packet_primary_count'])}U;",
        f"inline constexpr std::uint16_t kPacketReserveCount = {int(combined['packet_reserve_count'])}U;",
        f"inline constexpr std::uint16_t kPacketReadyQueueCapacity = {int(combined['packet_ready_queue_capacity'])}U;",
        f"inline constexpr std::uint16_t kPacketTransmitQueueCapacity = {int(combined['packet_transmit_queue_capacity'])}U;",
        f"inline constexpr std::uint8_t kCommandQueueCapacity = {int(combined['command_queue_capacity'])}U;",
        f"inline constexpr std::uint8_t kResponseQueueCapacity = {int(combined['response_queue_capacity'])}U;",
        (
            "inline constexpr std::uint32_t "
            "kNominalPayloadBytesPerSecondPerStream = "
            f"{int(combined['nominal_payload_bytes_per_second_per_stream'])}U;"
        ),
        (
            "inline constexpr std::uint32_t "
            "kNominalFramedBytesPerSecondPerStream = "
            f"{int(combined['nominal_framed_bytes_per_second_per_stream'])}U;"
        ),
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
        f"inline constexpr std::uint32_t kAdcTriggerPitClockHz = {int(adc_trigger['pit_clock_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcTriggerDwtClockHz = {int(adc_trigger['dwt_clock_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcTriggerGpioMasterRateHz = {int(adc_trigger['gpio_master_rate_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcTriggerPairRateHz = {int(adc_trigger['pair_rate_hz'])}U;",
        f"inline constexpr std::uint32_t kAdcTriggerIpgClockHz = {int(adc_trigger['ipg_clock_hz'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerGpioMasterPitChannel = {int(adc_trigger['gpio_master_pit_channel'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerPairPitChannel = {int(adc_trigger['pair_pit_channel'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerGpioMasterPitLoad = {int(adc_trigger['gpio_master_pit_load'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerPairPitLoad = {int(adc_trigger['pair_pit_load'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerPredivider = {int(adc_trigger['predivider'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerChainLength = {int(adc_trigger['chain_length'])}U;",
        "inline constexpr std::uint8_t kAdcTriggerXbarInputs[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_trigger["xbar_inputs"])
        + "};",
        "inline constexpr std::uint8_t kAdcTriggerXbarOutputs[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_trigger["xbar_outputs"])
        + "};",
        "inline constexpr std::uint8_t kAdcTriggerQueues[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_trigger["queues"])
        + "};",
        "inline constexpr std::uint16_t kAdcTriggerInitialDelays[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_trigger["initial_delays"])
        + "};",
        "inline constexpr std::uint16_t kAdcTriggerEffectiveDelays[] = {"
        + ", ".join(f"{int(value)}U" for value in adc_trigger["effective_delays"])
        + "};",
        f"inline constexpr std::uint16_t kAdcTriggerPhaseIpgCycles = {int(adc_trigger['phase_ipg_cycles'])}U;",
        f"inline constexpr std::uint32_t kAdcCompletionExpectedDwtCycles = {int(adc_trigger['completion_expected_dwt_cycles'])}U;",
        f"inline constexpr std::uint32_t kAdcCompletionToleranceDwtCycles = {int(adc_trigger['completion_tolerance_dwt_cycles'])}U;",
        f"inline constexpr std::uint32_t kAdcTriggerDiagnosticDeadlineUs = {int(adc_trigger['diagnostic_deadline_us'])}U;",
        f"inline constexpr std::uint32_t kAdcTriggerDiagnosticPollLimit = {int(adc_trigger['diagnostic_poll_limit'])}U;",
        f"inline constexpr std::uint8_t kAdcTriggerIrqPriority = {int(adc_trigger['irq_priority'])}U;",
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
    lines.extend(
        cpp_enum(
            "ConfigurationProfile",
            "std::uint16_t",
            contract["enums"]["configuration_profile"],
        )
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
        cpp_enum(
            "AdcTriggerConfigurationFlag",
            "std::uint16_t",
            contract["enums"]["adc_trigger_configuration_flag"],
        )
    )
    lines.extend(
        cpp_enum(
            "AdcTriggerError",
            "std::uint32_t",
            contract["enums"]["adc_trigger_error"],
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
                    if checksum_enabled(contract, entry)
                )
            )
            + "U;",
            "inline constexpr std::uint16_t kKnownFrameFlagMask = "
            + str(sum(int(entry["value"]) for entry in flags))
            + "U;",
            "inline constexpr std::uint32_t kKnownCapabilityMask = "
            + str(sum(int(entry["value"]) for entry in capabilities))
            + "U;",
            "inline constexpr std::uint16_t kKnownConfigurationProfileMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["configuration_profile"]
                )
            )
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
            "inline constexpr std::uint16_t "
            "kKnownAdcTriggerConfigurationFlagMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["adc_trigger_configuration_flag"]
                )
            )
            + "U;",
            "inline constexpr std::uint32_t kKnownAdcTriggerErrorMask = "
            + str(
                sum(
                    int(entry["value"])
                    for entry in contract["enums"]["adc_trigger_error"]
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
            "}  // namespace thingdaq::protocol_v1",
            "",
        ]
    )
    return "\n".join(lines).encode()


def render_cpp_v2(contract: Mapping[str, Any], source_sha256: str) -> bytes:
    """Render the disjoint experimental-v2 portable C++ constants header."""

    rendered = render_cpp(contract, source_sha256).decode()
    rendered = rendered.replace(
        "// Generated from protocol/protocol-v1.json. Do not edit by hand.",
        "// Generated from protocol/protocol-v2.json. Do not edit by hand.",
        1,
    ).replace("protocol_v1", "protocol_v2")
    closing = "\n}  // namespace thingdaq::protocol_v2\n"
    if closing not in rendered:
        raise ContractError("cannot locate generated protocol-v2 namespace boundary")

    auxiliary = contract["auxiliary_input"]
    banks = auxiliary["pin_banks"]
    resources = auxiliary["provisional_resources"]
    timing = contract["timing"]
    layouts = auxiliary["layouts"]
    lines: list[str] = [
        "",
        "enum class AuxBankMode : std::uint8_t {",
    ]
    lines.extend(
        f"  k{snake_to_pascal(str(entry['name']))} = {int(entry['value'])}U,"
        for entry in contract["enums"]["aux_bank_mode"]
    )
    lines.extend(["};", "", "enum class TemperatureStatus : std::uint8_t {"])
    lines.extend(
        f"  k{snake_to_pascal(str(entry['name']))} = {int(entry['value'])}U,"
        for entry in contract["enums"]["temperature_status"]
    )
    lines.extend(["};", "", "enum class RateProfile : std::uint8_t {"])
    lines.extend(
        f"  k{snake_to_pascal(str(entry['name']))} = {int(entry['value'])}U,"
        for entry in contract["enums"]["rate_profile"]
    )
    lines.extend(
        [
            "};",
            "",
            "struct RateProfileTiming {",
            "  RateProfile profile;",
            "  std::uint32_t adc_pair_rate_hz;",
            "  std::uint32_t gpio_sample_rate_hz;",
            "  std::uint16_t adc_pair_period_ticks;",
            "  std::uint16_t adc1_phase_ticks;",
            "  std::uint16_t gpio_sample_period_ticks;",
            "  std::uint16_t gpio_master_pit_divider;",
            "  std::uint16_t gpio_master_pit_load;",
            "  std::uint16_t adc_pair_pit_divider;",
            "  std::uint16_t adc_pair_pit_load;",
            "  std::uint16_t adc1_phase_ipg_cycles;",
            "  std::uint32_t completion_expected_dwt_cycles;",
            "  std::uint32_t disabled_frame_coverage_ticks;",
            "  std::uint32_t input_frame_coverage_ticks;",
            "};",
            "",
            (
                "inline constexpr std::size_t kMinDataFrameBytes = "
                f"{int(contract['limits']['min_data_frame_bytes'])}U;"
            ),
            f"inline constexpr std::uint32_t kPitClockHz = {int(timing['pit_clock_hz'])}U;",
            f"inline constexpr std::uint32_t kIpgClockHz = {int(timing['ipg_clock_hz'])}U;",
            f"inline constexpr std::uint32_t kDwtClockHz = {int(timing['dwt_clock_hz'])}U;",
            (
                "inline constexpr std::uint8_t kSupportedAuxBankModeMask = "
                + str(
                    sum(
                        1 << int(entry["value"])
                        for entry in contract["enums"]["aux_bank_mode"]
                    )
                )
                + "U;"
            ),
            (
                "inline constexpr std::uint8_t kSupportedRateProfileMask = "
                f"{int(timing['supported_rate_profile_mask'])}U;"
            ),
            "inline constexpr AuxBankMode kDefaultAuxBankMode =",
            f"    AuxBankMode::k{snake_to_pascal(str(auxiliary['default_mode']))};",
            "inline constexpr RateProfile kDefaultRateProfile =",
            f"    RateProfile::k{snake_to_pascal(str(timing['default_rate_profile']))};",
            "inline constexpr std::uint8_t kPrimaryGpioPinsByBit[] = {"
            + ", ".join(f"{int(value)}U" for value in banks["primary"]["teensy_pins"])
            + "};",
            "inline constexpr std::uint8_t kAuxGpioPinsByBit[] = {"
            + ", ".join(f"{int(value)}U" for value in banks["auxiliary"]["teensy_pins"])
            + "};",
            "inline constexpr std::uint8_t kGpio16PinsByBit[] = {"
            + ", ".join(
                f"{int(value)}U"
                for value in contract["data_layouts"]["gpio_aux_input"]["pins_by_bit"]
            )
            + "};",
            "inline constexpr std::uint8_t kPrimaryGpioPortBitsByWireBit[] = {"
            + ", ".join(
                f"{int(value)}U"
                for value in banks["primary"]["standard_gpio_bits_by_wire_bit"]
            )
            + "};",
            "inline constexpr std::uint8_t kAuxGpioPortBitsByWireBit[] = {"
            + ", ".join(
                f"{int(value)}U"
                for value in banks["auxiliary"]["standard_gpio_bits_by_wire_bit"]
            )
            + "};",
            (
                "inline constexpr std::uint32_t kPrimaryGpioCaptureMask = "
                f"0x{int(banks['primary']['aggregate_mask']):08X}U;"
            ),
            (
                "inline constexpr std::uint32_t kAuxGpioCaptureMask = "
                f"0x{int(banks['auxiliary']['aggregate_mask']):08X}U;"
            ),
            f"inline constexpr std::uint8_t kAuxGpioXbarOutput = {int(resources['auxiliary_xbar_output'])}U;",
            f"inline constexpr std::uint8_t kAuxGpioDmamuxSource = {int(resources['auxiliary_dmamux_source'])}U;",
            f"inline constexpr std::uint8_t kAuxGpioEdmaChannel = {int(resources['auxiliary_edma_channel'])}U;",
            "inline constexpr std::uint8_t kInputModeEdmaPriorities[] = {"
            + ", ".join(
                f"{int(value)}U" for value in resources["enabled_mode_edma_priorities"]
            )
            + "};",
            f"inline constexpr std::uint8_t kAuxGpioRawRingDepth = {int(resources['raw_ring_depth_per_bank'])}U;",
            f"inline constexpr std::uint8_t kGpioRawWordBytesPerBank = {int(resources['raw_word_bytes_per_bank'])}U;",
            "inline constexpr bool kPairedGpioJoinRequired = true;",
            (
                "inline constexpr std::size_t kDisabledAdcPairsPerFrame = "
                f"{int(layouts['DISABLED']['adc_items_per_frame'])}U;"
            ),
            (
                "inline constexpr std::size_t kDisabledGpioSamplesPerFrame = "
                f"{int(layouts['DISABLED']['gpio_items_per_frame'])}U;"
            ),
            (
                "inline constexpr std::size_t kInputAdcPairsPerFrame = "
                f"{int(layouts['INPUT']['adc_items_per_frame'])}U;"
            ),
            (
                "inline constexpr std::size_t kInputGpioSamplesPerFrame = "
                f"{int(layouts['INPUT']['gpio_items_per_frame'])}U;"
            ),
            "",
            "inline constexpr RateProfileTiming kRateProfiles[] = {",
        ]
    )
    for profile in contract["rate_profiles"]:
        values = (
            f"RateProfile::k{snake_to_pascal(str(profile['name']))}",
            *(
                f"{int(profile[key])}U"
                for key in (
                    "adc_pair_rate_hz",
                    "gpio_sample_rate_hz",
                    "adc_pair_period_ticks",
                    "adc1_phase_ticks",
                    "gpio_sample_period_ticks",
                    "gpio_master_pit_divider",
                    "gpio_master_pit_load",
                    "adc_pair_pit_divider",
                    "adc_pair_pit_load",
                    "adc1_phase_ipg_cycles",
                    "completion_expected_dwt_cycles",
                )
            ),
            f"{int(profile['frame_coverage_ticks']['DISABLED'])}U",
            f"{int(profile['frame_coverage_ticks']['INPUT'])}U",
        )
        lines.append("    {" + ", ".join(values) + "},")
    lines.extend(
        [
            "};",
            f"static_assert(sizeof(kRateProfiles) / sizeof(kRateProfiles[0]) == {len(contract['rate_profiles'])}U);",
            "static_assert(kInputAdcPairsPerFrame * kAdcBytesPerPair == 2024U);",
            "static_assert(kInputGpioSamplesPerFrame * 2U == kDataPayloadBytes);",
            "",
        ]
    )
    extension = "\n".join(lines)
    return rendered.replace(closing, extension + closing, 1).encode()


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
        elif field_type == "repeated_u16":
            items = list(value)
            if len(items) != int(field["count"]):
                raise ContractError(f"{schema_name}.{name} has the wrong item count")
            for index, item in enumerate(items):
                struct.pack_into("<H", payload, offset + index * 2, int(item))
        elif field_type == "repeated_u16_pair":
            items = list(value)
            if len(items) != int(field["count"]):
                raise ContractError(f"{schema_name}.{name} has the wrong pair count")
            for index, pair in enumerate(items):
                if len(pair) != 2:
                    raise ContractError(
                        f"{schema_name}.{name}[{index}] is not a uint16 pair"
                    )
                struct.pack_into(
                    "<HH",
                    payload,
                    offset + index * 4,
                    int(pair[0]),
                    int(pair[1]),
                )
        elif field_type == "repeated_schema":
            items = list(value)
            count = int(field["count"])
            nested_schema = str(field["schema"])
            nested_size = int(contract["payload_schemas"][nested_schema]["size"])
            if len(items) != count:
                raise ContractError(f"{schema_name}.{name} has the wrong record count")
            for index, item in enumerate(items):
                encoded = encode_schema_payload(contract, nested_schema, item)
                start = offset + index * nested_size
                payload[start : start + nested_size] = encoded
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
        layout_name = (
            "adc_aux_input" if fixture.get("aux_bank_mode") == "INPUT" else "adc"
        )
        layout = contract["data_layouts"][layout_name]
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
    if pattern == "gpio_u16_bank_ramp":
        count = int(contract["data_layouts"]["gpio_aux_input"]["items_per_frame"])
        start_index = int(payload_spec["start_index"])
        payload = bytearray(count * 2)
        for offset in range(count):
            sample_index = start_index + offset
            primary = sample_index & 0xFF
            auxiliary = (0x80 + 3 * sample_index) & 0xFF
            struct.pack_into("<H", payload, offset * 2, primary | (auxiliary << 8))
        return bytes(payload)
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


def _fixture_by_name(
    fixtures: Sequence[Mapping[str, Any]], name: str
) -> Mapping[str, Any]:
    for fixture in fixtures:
        if fixture["name"] == name:
            return fixture
    raise ContractError(f"missing golden fixture seed {name!r}")


def _profile_slug(profile_name: str) -> str:
    return profile_name.lower().replace("_", "-")


def _v2_configuration_values(
    contract: Mapping[str, Any], mode_name: str, profile: Mapping[str, Any]
) -> dict[str, int]:
    modes = enum_map(contract["enums"]["aux_bank_mode"])
    return {
        "stream_mask": 3,
        "source": 1,
        "data_checksum_algorithm": 1,
        "aux_bank_mode": modes[mode_name],
        "data_frame_bytes": int(contract["limits"]["data_frame_bytes"]),
        "adc_pair_rate_hz": int(profile["adc_pair_rate_hz"]),
        "gpio_sample_rate_hz": int(profile["gpio_sample_rate_hz"]),
    }


def _v2_info_values(
    contract: Mapping[str, Any],
    seed_values: Mapping[str, Any],
    mode_name: str,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    values = copy.deepcopy(dict(seed_values))
    mode_value = enum_map(contract["enums"]["aux_bank_mode"])[mode_name]
    layout = contract["auxiliary_input"]["layouts"][mode_name]
    alignment = int(contract["combined_acquisition"]["dma_alignment_bytes"])
    adc_payload_bytes = int(layout["adc_payload_bytes"])
    aligned_adc_payload = ((adc_payload_bytes + alignment - 1) // alignment) * alignment
    raw_ring_depth = int(contract["gpio_capture"]["raw_ring_depth"])
    values.update(
        {
            "device_state": 2,
            "adc_pair_rate_hz": int(profile["adc_pair_rate_hz"]),
            "gpio_sample_rate_hz": int(profile["gpio_sample_rate_hz"]),
            "adc_pair_period_ticks": int(profile["adc_pair_period_ticks"]),
            "adc1_phase_ticks": int(profile["adc1_phase_ticks"]),
            "gpio_sample_period_ticks": int(profile["gpio_sample_period_ticks"]),
            "gpio_packed_width_bits": int(layout["gpio_width_bits"]),
            "gpio_raw_samples_per_buffer": int(layout["gpio_items_per_frame"]),
            "gpio_raw_ring_bytes": (
                raw_ring_depth * int(layout["gpio_items_per_frame"]) * 4
            ),
            "gpio_edma_priority": 1 if mode_name == "INPUT" else 0,
            "adc_trigger_gpio_master_rate_hz": int(profile["gpio_sample_rate_hz"]),
            "adc_trigger_pair_rate_hz": int(profile["adc_pair_rate_hz"]),
            "adc_trigger_gpio_master_pit_load": int(profile["gpio_master_pit_load"]),
            "adc_trigger_pair_pit_load": int(profile["adc_pair_pit_load"]),
            "adc_trigger_predivider": int(profile["adc_etc_predivider"]),
            "adc_trigger_chain_length": int(profile["adc_etc_chain_length"]),
            "adc0_trigger_initial_delay": int(profile["adc0_initial_delay"]),
            "adc1_trigger_initial_delay": int(profile["adc1_initial_delay"]),
            "adc0_trigger_effective_delay": int(profile["adc0_effective_delay"]),
            "adc1_trigger_effective_delay": int(profile["adc1_effective_delay"]),
            "adc_trigger_phase_ipg_cycles": int(profile["adc1_phase_ipg_cycles"]),
            "adc_completion_expected_delta_cycles": int(
                profile["completion_expected_dwt_cycles"]
            ),
            "applied_stream_mask": 3,
            "applied_source": 1,
            "data_payload_bytes": adc_payload_bytes,
            "adc_pairs_per_frame": int(layout["adc_items_per_frame"]),
            "gpio_samples_per_frame": int(layout["gpio_items_per_frame"]),
            "frame_coverage_ticks": int(profile["frame_coverage_ticks"][mode_name]),
            "adc_edma_priorities": [3, 2] if mode_name == "INPUT" else [2, 1],
            "adc_pairs_per_buffer": int(layout["adc_items_per_frame"]),
            "adc_dma_ring_bytes": (
                int(contract["combined_acquisition"]["adc_dma_ring_depth"])
                * aligned_adc_payload
            ),
            "selected_rate_profile": int(profile["value"]),
            "applied_aux_bank_mode": mode_value,
            "gpio_item_bytes": int(layout["gpio_bytes_per_item"]),
        }
    )
    return values


def _apply_nested_override(values: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor: Any = values
    for part in parts[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    final = parts[-1]
    if isinstance(cursor, list):
        cursor[int(final)] = copy.deepcopy(value)
    else:
        cursor[final] = copy.deepcopy(value)


def expand_v2_golden_fixtures(
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Expand the compact v2 seeds into exhaustive deterministic wire vectors."""

    seeds = copy.deepcopy(list(contract["golden_fixtures"]))
    expanded: list[dict[str, Any]] = list(seeds)
    plan = contract["golden_vector_plan"]
    profiles = contract["rate_profiles"]
    modes = tuple(contract["auxiliary_input"]["supported_modes"])
    base_info = _fixture_by_name(seeds, "info-response")
    base_info_values = base_info["payload"]["values"]

    if plan["generate_gpio_mode_profile_matrix"]:
        for mode_index, mode_name in enumerate(modes):
            layout = contract["auxiliary_input"]["layouts"][mode_name]
            for profile in profiles:
                slug = _profile_slug(str(profile["name"]))
                width = int(layout["gpio_width_bits"])
                expanded.append(
                    {
                        "name": f"gpio-{width}bit-{slug}",
                        "kind": "GPIO_DATA",
                        "aux_bank_mode": mode_name,
                        "rate_profile": str(profile["name"]),
                        "flags": ["SYNTHETIC", "EPOCH_START"],
                        "run_id": 100 + mode_index * 10 + int(profile["value"]),
                        "sequence": 0,
                        "request_id": 0,
                        "first_sample_ticks": 0,
                        "item_count": int(layout["gpio_items_per_frame"]),
                        "payload": {
                            "pattern": (
                                "gpio_byte_ramp"
                                if mode_name == "DISABLED"
                                else "gpio_u16_bank_ramp"
                            ),
                            "start_index": 17 * int(profile["value"]),
                        },
                        "expectation": "accept",
                        "case": "gpio-mode-profile-matrix",
                    }
                )

    generated_requests: set[str] = set()
    if plan["generate_configure_mode_profile_matrix"]:
        for mode_index, mode_name in enumerate(modes):
            for profile in profiles:
                slug = _profile_slug(str(profile["name"]))
                stem = f"configure-{mode_name.lower()}-{slug}"
                request_name = f"{stem}-request"
                request_id = 1000 + mode_index * 10 + int(profile["value"])
                configuration = _v2_configuration_values(contract, mode_name, profile)
                expanded.extend(
                    [
                        {
                            "name": request_name,
                            "kind": "CONFIGURE_REQUEST",
                            "request_id": request_id,
                            "payload": {
                                "schema": "configure_request",
                                "values": configuration,
                            },
                            "expectation": "accept",
                            "case": "configure-mode-profile-matrix",
                            "aux_bank_mode": mode_name,
                            "rate_profile": str(profile["name"]),
                        },
                        {
                            "name": f"{stem}-response",
                            "kind": "CONFIGURE_RESPONSE",
                            "request_id": request_id,
                            "payload": {
                                "schema": "configure_response",
                                "values": {
                                    "response_status": 0,
                                    "error_code": 0,
                                    **configuration,
                                },
                            },
                            "expectation": "accept",
                            "case": "configure-mode-profile-matrix",
                            "correlates_to": request_name,
                            "aux_bank_mode": mode_name,
                            "rate_profile": str(profile["name"]),
                        },
                    ]
                )
                generated_requests.add(request_name)

    if plan["generate_info_mode_profile_matrix"]:
        for mode_index, mode_name in enumerate(modes):
            for profile in profiles:
                slug = _profile_slug(str(profile["name"]))
                expanded.append(
                    {
                        "name": f"info-{mode_name.lower()}-{slug}-response",
                        "kind": "INFO_RESPONSE",
                        "request_id": 1100 + mode_index * 10 + int(profile["value"]),
                        "payload": {
                            "schema": "info_response",
                            "values": _v2_info_values(
                                contract, base_info_values, mode_name, profile
                            ),
                        },
                        "expectation": "accept",
                        "case": "info-mode-profile-matrix",
                        "aux_bank_mode": mode_name,
                        "rate_profile": str(profile["name"]),
                    }
                )

    configure_seed = _fixture_by_name(seeds, "configure-request")
    configure_response_seed = _fixture_by_name(seeds, "configure-response")
    error_codes = enum_map(contract["enums"]["error_code"])
    for index, malformed in enumerate(plan["malformed_cases"]):
        name = str(malformed["name"])
        target = str(malformed["target"])
        request_id = 2000 + index
        if target == "configure_request":
            values = copy.deepcopy(configure_seed["payload"]["values"])
            values.update(copy.deepcopy(malformed.get("overrides", {})))
            request_name = f"malformed-{name}-configure-request"
            expanded.append(
                {
                    "name": request_name,
                    "kind": "CONFIGURE_REQUEST",
                    "request_id": request_id,
                    "payload": {"schema": "configure_request", "values": values},
                    "expectation": "reject",
                    "case": name,
                    "expected_rejection": str(malformed["expected_rejection"]),
                    "reason": str(malformed["reason"]),
                    "expected_error_code": str(malformed["error_code"]),
                }
            )
            expanded.append(
                {
                    "name": f"malformed-{name}-configure-error-response",
                    "kind": "CONFIGURE_RESPONSE",
                    "flags": ["RESPONSE_ERROR"],
                    "request_id": request_id,
                    "payload": {
                        "schema": "response_prefix",
                        "values": {
                            "response_status": 1,
                            "error_code": error_codes[str(malformed["error_code"])],
                        },
                    },
                    "expectation": "accept-error",
                    "case": name,
                    "correlates_to": request_name,
                    "expected_error_code": str(malformed["error_code"]),
                }
            )
        elif target == "info_response":
            values = copy.deepcopy(base_info_values)
            values.update(copy.deepcopy(malformed.get("overrides", {})))
            for path, value in malformed.get("nested_overrides", {}).items():
                _apply_nested_override(values, str(path), value)
            expanded.append(
                {
                    "name": f"malformed-{name}-info-response",
                    "kind": "INFO_RESPONSE",
                    "request_id": request_id,
                    "payload": {"schema": "info_response", "values": values},
                    "expectation": "reject",
                    "case": name,
                    "expected_rejection": str(malformed["expected_rejection"]),
                    "reason": str(malformed["reason"]),
                }
            )
        else:
            values = copy.deepcopy(configure_response_seed["payload"]["values"])
            values.update(copy.deepcopy(malformed.get("overrides", {})))
            request_fixture = str(malformed["request_fixture"])
            if request_fixture not in generated_requests:
                raise ContractError(
                    f"malformed fixture {name} references unknown {request_fixture}"
                )
            expanded.append(
                {
                    "name": f"malformed-{name}-configure-response",
                    "kind": "CONFIGURE_RESPONSE",
                    "request_id": 1000,
                    "payload": {"schema": "configure_response", "values": values},
                    "expectation": "reject-client",
                    "case": name,
                    "correlates_to": request_fixture,
                    "expected_rejection": str(malformed["expected_rejection"]),
                    "reason": str(malformed["reason"]),
                }
            )

    names = [str(fixture["name"]) for fixture in expanded]
    if len(names) != len(set(names)):
        raise ContractError("expanded protocol-v2 fixture names are not unique")
    return expanded


def build_golden_frames(
    contract: Mapping[str, Any],
    fixtures: Sequence[Mapping[str, Any]] | None = None,
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
    selected_fixtures = contract["golden_fixtures"] if fixtures is None else fixtures
    for fixture in selected_fixtures:
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
        response_error = "RESPONSE_ERROR" in fixture.get("flags", [])
        expected_schema = (
            kind_spec.get("error_payload_schema", kind_spec["payload_schema"])
            if response_error
            else kind_spec["payload_schema"]
        )
        if "schema" in payload_spec and payload_spec["schema"] != expected_schema:
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
            if int(contract["protocol_version"]) == 1:
                expected_total_length = int(limits["data_frame_bytes"])
                expected_item_count = (
                    int(contract["data_layouts"]["adc"]["items_per_frame"])
                    if kind_name == "ADC_DATA"
                    else int(contract["data_layouts"]["gpio"]["items_per_frame"])
                )
                period_ticks = int(
                    contract["timing"][
                        "adc_pair_period_ticks"
                        if kind_name == "ADC_DATA"
                        else "gpio_sample_period_ticks"
                    ]
                )
            else:
                mode_name = str(fixture.get("aux_bank_mode", ""))
                profile_name = str(fixture.get("rate_profile", ""))
                if mode_name not in contract["auxiliary_input"]["layouts"]:
                    raise ContractError(
                        f"v2 data fixture {fixture_name} has no auxiliary mode"
                    )
                profiles = {
                    str(profile["name"]): profile
                    for profile in contract["rate_profiles"]
                }
                if profile_name not in profiles:
                    raise ContractError(
                        f"v2 data fixture {fixture_name} has no rate profile"
                    )
                layout = contract["auxiliary_input"]["layouts"][mode_name]
                expected_total_length = int(
                    layout[
                        "adc_total_frame_bytes"
                        if kind_name == "ADC_DATA"
                        else "gpio_total_frame_bytes"
                    ]
                )
                expected_item_count = int(
                    layout[
                        "adc_items_per_frame"
                        if kind_name == "ADC_DATA"
                        else "gpio_items_per_frame"
                    ]
                )
                period_ticks = int(
                    profiles[profile_name][
                        "adc_pair_period_ticks"
                        if kind_name == "ADC_DATA"
                        else "gpio_sample_period_ticks"
                    ]
                )
            if total_length != expected_total_length:
                raise ContractError(
                    f"fixture {fixture_name} has total length {total_length}; "
                    f"expected {expected_total_length}"
                )
            if item_count != expected_item_count:
                raise ContractError(
                    f"fixture {fixture_name} has item count {item_count}; "
                    f"expected {expected_item_count}"
                )
            if first_sample_ticks % period_ticks:
                raise ContractError(
                    f"fixture {fixture_name} timestamp is not profile-aligned"
                )
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
        if int(contract["protocol_version"]) == 2:
            manifest_entry["expectation"] = str(fixture.get("expectation", "accept"))
            for key in (
                "aux_bank_mode",
                "case",
                "correlates_to",
                "expected_error_code",
                "expected_rejection",
                "rate_profile",
                "reason",
            ):
                if key in fixture:
                    manifest_entry[key] = fixture[key]
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


def expected_v2_outputs(
    contract: Mapping[str, Any], source_bytes: bytes
) -> dict[Path, bytes]:
    """Return every disjoint generated protocol-v2 path and exact contents."""

    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    fixtures = expand_v2_golden_fixtures(contract)
    fixture_outputs, manifest_entries = build_golden_frames(contract, fixtures)
    generated = contract["generated_outputs"]
    fixture_directory = REPOSITORY_ROOT / str(generated["fixture_directory"])
    manifest_path = REPOSITORY_ROOT / str(generated["fixture_manifest"])
    manifest = {
        "byte_order": contract["byte_order"],
        "extension": contract["extension"],
        "fixtures": manifest_entries,
        "generator": "tools/generate_protocol.py",
        "protocol_version": int(contract["protocol_version"]),
        "source": "protocol/protocol-v2.json",
        "source_sha256": source_sha256,
        "v1_source": contract["extends"]["source"],
        "v1_source_sha256": contract["extends"]["source_sha256"],
    }
    outputs = {
        REPOSITORY_ROOT / str(generated["python_constants"]): render_python_v2(
            contract, source_sha256
        ),
        REPOSITORY_ROOT / str(generated["cpp_constants"]): render_cpp_v2(
            contract, source_sha256
        ),
        manifest_path: (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    }
    outputs.update(
        {
            fixture_directory / name: contents
            for name, contents in fixture_outputs.items()
        }
    )
    return outputs


def expected_all_outputs(
    v1_contract: Mapping[str, Any],
    v1_source_bytes: bytes,
    v2_contract: Mapping[str, Any],
    v2_source_bytes: bytes,
) -> dict[Path, bytes]:
    """Return the union of frozen-v1 and experimental-v2 generated outputs."""

    v1_outputs = expected_outputs(v1_contract, v1_source_bytes)
    v2_outputs = expected_v2_outputs(v2_contract, v2_source_bytes)
    overlap = set(v1_outputs) & set(v2_outputs)
    if overlap:
        raise ContractError(
            "protocol-v1 and protocol-v2 generated paths overlap: "
            + ", ".join(relative_paths(sorted(overlap)))
        )
    return {**v1_outputs, **v2_outputs}


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
    fixture_directories = {path.parent for path in outputs if path.suffix == ".bin"}
    for fixture_directory in fixture_directories:
        expected_fixture_paths = {
            path for path in outputs if path.parent == fixture_directory
        }
        drifted.extend(
            path
            for path in fixture_directory.glob("*.bin")
            if path not in expected_fixture_paths
        )
    drifted = list(dict.fromkeys(drifted))
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
    fixture_directories = {path.parent for path in outputs if path.suffix == ".bin"}
    for fixture_directory in fixture_directories:
        expected_fixture_paths = {
            path for path in outputs if path.parent == fixture_directory
        }
        for path in fixture_directory.glob("*.bin"):
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
    parser.add_argument(
        "--protocol",
        choices=("all", "v1", "v2"),
        default="all",
        help="select generated protocol outputs (default: all)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        v1_contract, v1_source_bytes = load_contract()
        validate_contract(v1_contract)
        if args.protocol == "v1":
            outputs = expected_outputs(v1_contract, v1_source_bytes)
        else:
            v2_contract, v2_source_bytes = load_contract(V2_SOURCE_PATH)
            validate_v2_contract(v2_contract, v1_contract, v1_source_bytes)
            if args.protocol == "v2":
                outputs = expected_v2_outputs(v2_contract, v2_source_bytes)
            else:
                outputs = expected_all_outputs(
                    v1_contract,
                    v1_source_bytes,
                    v2_contract,
                    v2_source_bytes,
                )
    except (ContractError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Invalid protocol contract: {error}", file=sys.stderr)
        return 2
    if args.check:
        return check_outputs(outputs)
    return write_outputs(outputs)


if __name__ == "__main__":
    raise SystemExit(main())
