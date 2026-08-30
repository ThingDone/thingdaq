#!/usr/bin/env python3
"""Generate deterministic rig and standalone/installed Windows soak programs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "firmware/soak/validator.py"
WINDOWS_DRIVER_PATH = REPOSITORY_ROOT / "firmware/soak/windows_driver.inc"
CANDIDATE_PATH = REPOSITORY_ROOT / "firmware/soak/candidate.json"
CANDIDATE_FREEZE_PATH = REPOSITORY_ROOT / "firmware/soak/candidate-freeze.json"
PROTOCOL_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
VALIDATION_MANIFEST_PATH = REPOSITORY_ROOT / "firmware/soak/validation-manifest.json"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "firmware/tests/generated"
WINDOWS_OUTPUT_PATH = REPOSITORY_ROOT / "daq_api/scripts/windows_soak.py"
PACKAGE_OUTPUT_PATH = REPOSITORY_ROOT / "daq_api/src/teensy_daq/soak.py"
OUTPUTS = {
    "synthetic": "rig_soak_synthetic.py",
    "physical-combined": "rig_soak_physical_combined.py",
    "control-stress": "rig_soak_control_stress.py",
}
CONFIG_BLOCK = re.compile(
    r"^# <soak-generated-config>\n.*?^# </soak-generated-config>$",
    re.MULTILINE | re.DOTALL,
)
CLI_BLOCK = re.compile(
    r"^# <soak-cli>\n.*?^# </soak-cli>$",
    re.MULTILINE | re.DOTALL,
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
VALIDATION_MANIFEST_SCHEMA_VERSION = 1
PHASE_11_EVIDENCE_LINK = "[[Phase-11-Soak-Evidence]]"
HOST_PARSER_ZERO_FIELDS = (
    "bytes_discarded",
    "errors",
    "buffered_bytes",
)
HOST_STREAM_ZERO_FIELDS = (
    "adc_missing_frames",
    "gpio_missing_frames",
    "adc_gap_flag_frames",
    "gpio_gap_flag_frames",
)
FINAL_IDLE_ZERO_GAUGES = (
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


class GenerationError(RuntimeError):
    """A candidate or canonical-source invariant prevents generation."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GenerationError(f"could not read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise GenerationError(f"{path} must contain one JSON object")
    return value


def require_mapping(owner: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = owner.get(name)
    if not isinstance(value, dict):
        raise GenerationError(f"{name} must be an object")
    return value


def require_number(owner: Mapping[str, Any], name: str) -> float:
    value = owner.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise GenerationError(f"{name} must be finite numeric")
    result = float(value)
    if not math.isfinite(result):
        raise GenerationError(f"{name} must be finite numeric")
    return result


def require_integer(owner: Mapping[str, Any], name: str, *, minimum: int = 0) -> int:
    value = owner.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise GenerationError(f"{name} must be an integer >= {minimum}")
    return value


def require_list(owner: Mapping[str, Any], name: str) -> list[Any]:
    value = owner.get(name)
    if not isinstance(value, list):
        raise GenerationError(f"{name} must be a list")
    return value


def _enum_entries(contract: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    enums = require_mapping(contract, "enums")
    raw_entries = require_list(enums, name)
    entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    if len(entries) != len(raw_entries) or not entries:
        raise GenerationError(f"protocol enum {name} must contain objects")
    for entry in entries:
        if not isinstance(entry.get("name"), str):
            raise GenerationError(f"protocol enum {name} has an invalid name")
        require_integer(entry, "value")
    return entries


def _enum_sum(contract: Mapping[str, Any], name: str) -> int:
    return sum(int(entry["value"]) for entry in _enum_entries(contract, name))


def _enum_bit_mask(contract: Mapping[str, Any], name: str) -> int:
    return sum(1 << int(entry["value"]) for entry in _enum_entries(contract, name))


def _literal_string_collection(source: str, name: str) -> tuple[str, ...]:
    """Read one literal tuple/set assignment without importing the validator."""

    for node in ast.parse(source).body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if not isinstance(target, ast.Name) or target.id != name or value is None:
            continue
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1
            and not value.keywords
        ):
            value = value.args[0]
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            raise GenerationError(f"validator {name} must be a literal collection")
        entries: list[str] = []
        for entry in value.elts:
            decoded = ast.literal_eval(entry)
            if not isinstance(decoded, str) or not decoded:
                raise GenerationError(f"validator {name} contains a non-string")
            entries.append(decoded)
        if len(entries) != len(set(entries)):
            raise GenerationError(f"validator {name} contains duplicates")
        return tuple(entries)
    raise GenerationError(f"validator is missing literal {name}")


def validate_candidate_freeze(
    candidate: Mapping[str, Any],
    candidate_freeze: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the handoff to the two-build Phase 11 candidate freeze."""

    if candidate_freeze.get("schema_version") != 1:
        raise GenerationError("candidate freeze schema_version must be 1")
    candidate_sha = sha256_bytes(canonical_json_bytes(candidate))
    frozen = require_mapping(candidate_freeze, "candidate")
    artifact = require_mapping(candidate, "artifact")
    board = require_mapping(candidate, "board")
    firmware = require_mapping(candidate, "firmware")
    expected = {
        "sha256": candidate_sha,
        "artifact_name": artifact.get("name"),
        "artifact_sha256": artifact.get("sha256"),
        "source_id": firmware.get("source_id"),
        "build_id": firmware.get("build_id"),
        "fqbn": board.get("fqbn"),
    }
    mismatches = {
        name: {"candidate": value, "freeze": frozen.get(name)}
        for name, value in expected.items()
        if frozen.get(name) != value
    }
    if mismatches:
        raise GenerationError(
            "candidate does not match the accepted freeze: "
            + json.dumps(mismatches, sort_keys=True, separators=(",", ":"))
        )

    reproducibility = require_mapping(candidate_freeze, "reproducibility")
    if (
        reproducibility.get("build_count") != 2
        or reproducibility.get("byte_identical") is not True
    ):
        raise GenerationError(
            "accepted candidate freeze must record two byte-identical builds"
        )
    manifest_hashes = require_mapping(reproducibility, "manifest_sha256")
    first_manifest = manifest_hashes.get("first")
    second_manifest = manifest_hashes.get("second")
    if (
        not isinstance(first_manifest, str)
        or SHA256_PATTERN.fullmatch(first_manifest) is None
        or first_manifest != second_manifest
    ):
        raise GenerationError("candidate freeze build manifests are not identical")
    artifacts = require_list(reproducibility, "artifacts")
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("path") == artifact.get("name")
    ]
    if len(matches) != 1 or matches[0].get("sha256") != artifact.get("sha256"):
        raise GenerationError("candidate freeze does not reproduce the selected HEX")
    hex_size = require_integer(matches[0], "size_bytes", minimum=1)
    return {
        "candidate_semantic_sha256": candidate_sha,
        "firmware_build_manifest_sha256": first_manifest,
        "reproducible_build_count": 2,
        "reproducible_hex_size_bytes": hex_size,
    }


def build_validation_manifest(
    candidate: Mapping[str, Any],
    protocol_contract: Mapping[str, Any],
    candidate_freeze: Mapping[str, Any],
    validator_source: str,
    *,
    candidate_freeze_sha256: str,
    protocol_contract_sha256: str,
) -> dict[str, Any]:
    """Create the path- and credential-free release validation contract."""

    validate_candidate(candidate)
    freeze_evidence = validate_candidate_freeze(candidate, candidate_freeze)
    if SHA256_PATTERN.fullmatch(candidate_freeze_sha256) is None:
        raise GenerationError("candidate freeze SHA-256 is invalid")
    if SHA256_PATTERN.fullmatch(protocol_contract_sha256) is None:
        raise GenerationError("protocol contract SHA-256 is invalid")

    artifact = require_mapping(candidate, "artifact")
    board = require_mapping(candidate, "board")
    firmware = require_mapping(candidate, "firmware")
    protocol = require_mapping(candidate, "protocol")
    timing = require_mapping(protocol_contract, "timing")
    limits = require_mapping(protocol_contract, "limits")
    header = require_mapping(protocol_contract, "header")
    trailer = require_mapping(protocol_contract, "trailer")
    combined = require_mapping(protocol_contract, "combined_acquisition")
    adc_initialization = require_mapping(protocol_contract, "adc_initialization")
    adc_trigger = require_mapping(protocol_contract, "adc_trigger")
    layouts = require_mapping(protocol_contract, "data_layouts")
    adc_layout = require_mapping(layouts, "adc")
    gpio_layout = require_mapping(layouts, "gpio")

    protocol_version = require_integer(protocol_contract, "protocol_version", minimum=1)
    if protocol_version != protocol.get("version"):
        raise GenerationError("candidate and protocol contract versions disagree")
    checksum_entries = require_list(protocol_contract, "checksum_algorithms")
    checksum_matches = [
        entry
        for entry in checksum_entries
        if isinstance(entry, dict)
        and entry.get("value") == protocol.get("checksum_algorithm")
        and entry.get("name") == protocol.get("checksum_name")
    ]
    if (
        len(checksum_matches) != 1
        or checksum_matches[0].get("enabled_in_v1") is not True
    ):
        raise GenerationError(
            "selected candidate checksum is not enabled by protocol v1"
        )
    if (
        protocol.get("checksum_algorithm") != 1
        or protocol.get("checksum_name") != "ADLER32"
    ):
        raise GenerationError(
            "validation manifest supports the selected Adler-32 policy"
        )

    firmware_version = firmware.get("version")
    adc_pins = require_list(adc_initialization, "pins")
    adc_order = require_list(adc_layout, "order")
    gpio_pins = require_list(gpio_layout, "pins_by_bit")
    if len(adc_pins) != len(adc_order) or len(adc_pins) != 2:
        raise GenerationError("ADC pin/order contract must describe two channels")
    if len(gpio_pins) != 8 or len(set(gpio_pins)) != len(gpio_pins):
        raise GenerationError("GPIO pin map must contain eight unique pins")

    data_frame_bytes = require_integer(limits, "data_frame_bytes", minimum=1)
    header_bytes = require_integer(header, "size", minimum=1)
    trailer_bytes = require_integer(trailer, "size", minimum=1)
    adc_payload_bytes = require_integer(adc_layout, "payload_bytes", minimum=1)
    gpio_payload_bytes = require_integer(gpio_layout, "payload_bytes", minimum=1)
    if (
        adc_payload_bytes != gpio_payload_bytes
        or header_bytes + adc_payload_bytes + trailer_bytes != data_frame_bytes
    ):
        raise GenerationError("protocol data frame sizes do not reconcile")
    adc_items = require_integer(adc_layout, "items_per_frame", minimum=1)
    gpio_items = require_integer(gpio_layout, "items_per_frame", minimum=1)
    adc_period = require_integer(timing, "adc_pair_period_ticks", minimum=1)
    gpio_period = require_integer(timing, "gpio_sample_period_ticks", minimum=1)
    frame_coverage_ticks = adc_items * adc_period
    if frame_coverage_ticks != gpio_items * gpio_period:
        raise GenerationError("ADC and GPIO frame coverage does not align")
    timestamp_hz = require_integer(timing, "timestamp_hz", minimum=1)
    adc1_phase_ticks = require_integer(timing, "adc1_phase_ticks")
    phase_numerator = adc1_phase_ticks * 1_000_000_000
    if phase_numerator % timestamp_hz:
        raise GenerationError("ADC phase is not an integral number of nanoseconds")
    trigger_phase_cycles = require_integer(adc_trigger, "phase_ipg_cycles")
    trigger_ipg_hz = require_integer(adc_trigger, "ipg_clock_hz", minimum=1)
    trigger_phase_numerator = trigger_phase_cycles * 1_000_000_000
    if (
        trigger_phase_numerator % trigger_ipg_hz
        or trigger_phase_numerator // trigger_ipg_hz != phase_numerator // timestamp_hz
    ):
        raise GenerationError("ADC timestamp and hardware-trigger phases disagree")

    stream_mask = _enum_sum(protocol_contract, "stream_mask")
    source_mask = _enum_bit_mask(protocol_contract, "source")
    checksum_mask = sum(
        1 << int(entry["value"])
        for entry in checksum_entries
        if isinstance(entry, dict) and entry.get("enabled_in_v1") is True
    )
    capability_entries = _enum_entries(protocol_contract, "capability_bits")
    capability_bits = sum(int(entry["value"]) for entry in capability_entries)
    configuration_mask = _enum_sum(protocol_contract, "configuration_profile")
    container_bits = require_integer(adc_layout, "container_bits", minimum=8)
    if container_bits % 8:
        raise GenerationError("ADC container width must be whole bytes")

    expected_info = {
        "protocol_version": protocol_version,
        "hardware_serial": require_integer(board, "hardware_serial", minimum=1),
        "firmware_version": firmware_version,
        "board_id": require_integer(board, "board_id", minimum=1),
        "mcu_id": require_integer(board, "mcu_id", minimum=1),
        "build_id": firmware.get("build_id"),
        "supported_stream_mask": stream_mask,
        "supported_source_mask": source_mask,
        "supported_checksum_mask": checksum_mask,
        "capability_bits": capability_bits,
        "timestamp_hz": timestamp_hz,
        "data_frame_bytes": data_frame_bytes,
        "max_control_frame_bytes": require_integer(
            limits, "max_control_frame_bytes", minimum=1
        ),
        "adc_pair_rate_hz": require_integer(timing, "adc_pair_rate_hz", minimum=1),
        "gpio_sample_rate_hz": require_integer(
            timing, "gpio_sample_rate_hz", minimum=1
        ),
        "adc_pair_period_ticks": adc_period,
        "adc1_phase_ticks": adc1_phase_ticks,
        "gpio_sample_period_ticks": gpio_period,
        "adc_resolution_bits": require_integer(
            adc_layout, "resolution_bits", minimum=1
        ),
        "adc_container_bytes": container_bits // 8,
        "gpio_pin_count": len(gpio_pins),
        "data_checksum_algorithm": protocol.get("checksum_algorithm"),
        "gpio_pin_map": gpio_pins,
        "supported_configuration_mask": configuration_mask,
        "data_payload_bytes": adc_payload_bytes,
        "adc_pairs_per_frame": adc_items,
        "gpio_samples_per_frame": gpio_items,
        "frame_coverage_ticks": frame_coverage_ticks,
        "adc_dma_ring_depth": require_integer(
            combined, "adc_dma_ring_depth", minimum=1
        ),
        "adc_pair_bytes": require_integer(adc_layout, "bytes_per_item", minimum=1),
        "packet_buffer_count": require_integer(
            combined, "packet_buffer_count", minimum=1
        ),
        "packet_ready_queue_capacity": require_integer(
            combined, "packet_ready_queue_capacity", minimum=1
        ),
        "packet_transmit_queue_capacity": require_integer(
            combined, "packet_transmit_queue_capacity", minimum=1
        ),
        "command_queue_capacity": require_integer(
            combined, "command_queue_capacity", minimum=1
        ),
        "response_queue_capacity": require_integer(
            combined, "response_queue_capacity", minimum=1
        ),
        "nominal_payload_bytes_per_second_per_stream": require_integer(
            combined, "nominal_payload_bytes_per_second_per_stream", minimum=1
        ),
        "nominal_framed_bytes_per_second_per_stream": require_integer(
            combined, "nominal_framed_bytes_per_second_per_stream", minimum=1
        ),
    }

    firmware_zero = _literal_string_collection(validator_source, "_ZERO_ERROR_FIELDS")
    physical_stop_tail = _literal_string_collection(
        validator_source, "_PHYSICAL_STOP_TAIL_FIELDS"
    )
    if not set(physical_stop_tail).issubset(firmware_zero):
        raise GenerationError("physical STOP-tail fields are not validation counters")

    manifest = {
        "schema_version": VALIDATION_MANIFEST_SCHEMA_VERSION,
        "kind": "teensy-daq-release-validation",
        "related": [PHASE_11_EVIDENCE_LINK],
        "accepted_evidence": {
            **freeze_evidence,
            "candidate_freeze_sha256": candidate_freeze_sha256,
            "protocol_contract_sha256": protocol_contract_sha256,
        },
        "firmware": {
            "version": firmware_version,
            "build_id": firmware.get("build_id"),
            "source_id": firmware.get("source_id"),
            "fqbn": board.get("fqbn"),
            "exported_hex": {
                "name": artifact.get("name"),
                "sha256": artifact.get("sha256"),
                "size_bytes": freeze_evidence["reproducible_hex_size_bytes"],
            },
        },
        "protocol": {
            "version": protocol_version,
            "byte_order": protocol_contract.get("byte_order"),
            "checksum": {
                "algorithm": protocol.get("checksum_algorithm"),
                "name": protocol.get("checksum_name"),
                "parameters": {
                    "initial_value": 1,
                    "modulus": 65_521,
                    "width_bits": 32,
                    "trailer_byte_order": trailer.get("byte_order"),
                    "coverage": trailer.get("coverage"),
                },
            },
            "frames": {
                "header_bytes": header_bytes,
                "payload_bytes": adc_payload_bytes,
                "trailer_bytes": trailer_bytes,
                "data_frame_bytes": data_frame_bytes,
                "max_control_frame_bytes": expected_info["max_control_frame_bytes"],
                "adc_pairs_per_frame": adc_items,
                "gpio_samples_per_frame": gpio_items,
                "frame_coverage_ticks": frame_coverage_ticks,
            },
        },
        "acquisition": {
            "timestamp_hz": timestamp_hz,
            "adc_pair_rate_hz": expected_info["adc_pair_rate_hz"],
            "adc_pair_period_ticks": adc_period,
            "adc1_phase_ticks": adc1_phase_ticks,
            "adc1_phase_nanoseconds": phase_numerator // timestamp_hz,
            "adc_trigger_phase_ipg_cycles": trigger_phase_cycles,
            "adc_trigger_ipg_clock_hz": trigger_ipg_hz,
            "gpio_sample_rate_hz": expected_info["gpio_sample_rate_hz"],
            "gpio_sample_period_ticks": gpio_period,
            "adc_resolution_bits": expected_info["adc_resolution_bits"],
            "adc_container_bits": container_bits,
            "adc_pins_by_pair_position": {
                str(name): pin for name, pin in zip(adc_order, adc_pins, strict=True)
            },
            "gpio_pins_by_bit": gpio_pins,
        },
        "capabilities": {
            "bits": capability_bits,
            "names": [str(entry["name"]) for entry in capability_entries],
            "supported_stream_mask": stream_mask,
            "supported_source_mask": source_mask,
            "supported_checksum_mask": checksum_mask,
            "supported_configuration_mask": configuration_mask,
        },
        "expected_info": expected_info,
        "required_zero": {
            "required_value": 0,
            "host_parser_fields": list(HOST_PARSER_ZERO_FIELDS),
            "host_stream_fields": list(HOST_STREAM_ZERO_FIELDS),
            "firmware_during_stream_fields": list(firmware_zero),
            "firmware_final_fields": [
                name for name in firmware_zero if name not in physical_stop_tail
            ],
            "physical_stop_tail_bounded_fields": list(physical_stop_tail),
            "final_idle_gauges": list(FINAL_IDLE_ZERO_GAUGES),
        },
        "release_policy": {
            "identity_override_option": "--diagnostic-identity-override",
            "identity_override_results_are_release_eligible": False,
            "hardware_serial_is_stable_identity": True,
            "mutable_com_port_is_identity": False,
        },
    }
    return manifest


def validate_candidate(candidate: Mapping[str, Any]) -> None:
    if candidate.get("schema_version") != 1:
        raise GenerationError("candidate schema_version must be 1")
    artifact = require_mapping(candidate, "artifact")
    board = require_mapping(candidate, "board")
    firmware = require_mapping(candidate, "firmware")
    protocol = require_mapping(candidate, "protocol")
    soak = require_mapping(candidate, "soak")
    artifact_sha = artifact.get("sha256")
    source_id = firmware.get("source_id")
    if not isinstance(artifact_sha, str) or not SHA256_PATTERN.fullmatch(artifact_sha):
        raise GenerationError("artifact.sha256 must be lowercase SHA-256")
    if not isinstance(source_id, str) or not SHA256_PATTERN.fullmatch(source_id):
        raise GenerationError("firmware.source_id must be lowercase SHA-256")
    if firmware.get("build_id") != f"tdaq-{source_id[:16]}":
        raise GenerationError("firmware.build_id must derive from firmware.source_id")
    version = firmware.get("version")
    if not (
        isinstance(version, list)
        and len(version) == 3
        and all(
            isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255
            for value in version
        )
    ):
        raise GenerationError("firmware.version must contain three uint8 values")
    positive_integers = ("hardware_serial", "board_id", "mcu_id")
    if any(
        not isinstance(board.get(name), int)
        or isinstance(board[name], bool)
        or board[name] <= 0
        for name in positive_integers
    ):
        raise GenerationError("board identity fields must be positive integers")
    if (
        type(protocol.get("version")) is not int
        or protocol.get("version") != 1
        or type(protocol.get("checksum_algorithm")) is not int
        or protocol.get("checksum_algorithm") != 1
        or protocol.get("checksum_name") != "ADLER32"
    ):
        raise GenerationError("candidate must pin protocol v1 and Adler-32")
    measured = require_number(soak, "measured_duration_seconds")
    warmup = require_number(soak, "warmup_seconds")
    status_interval = require_number(soak, "status_interval_seconds")
    info_interval = require_number(soak, "info_interval_seconds")
    control_epoch = require_number(soak, "control_epoch_seconds")
    reopen_every = soak.get("control_reopen_every_epochs")
    hard_deadline = require_number(soak, "hard_deadline_seconds")
    service_limit = require_number(soak, "service_container_limit_seconds")
    if measured != 600.0:
        raise GenerationError("generated rig programs must measure exactly 600 seconds")
    if (
        warmup < 0.0
        or status_interval < 0.05
        or info_interval < status_interval
        or control_epoch < 5.0
        or not isinstance(reopen_every, int)
        or isinstance(reopen_every, bool)
        or reopen_every < 1
    ):
        raise GenerationError("candidate soak cadence/bounds are invalid")
    if not measured + warmup + 30.0 <= hard_deadline < service_limit <= 900.0:
        raise GenerationError(
            "hard deadline must reserve cleanup time and precede the <=900s service limit"
        )


def generated_block(
    mode: str,
    candidate: Mapping[str, Any],
    *,
    candidate_sha256: str,
    validator_sha256: str,
) -> str:
    config = {
        "mode": mode,
        "generator_schema_version": 1,
        "candidate": candidate,
        "candidate_sha256": candidate_sha256,
        "validator_sha256": validator_sha256,
    }
    encoded = json.dumps(config, indent=2, sort_keys=True)
    return (
        "# <soak-generated-config>\n"
        "GENERATED_CONFIG: dict[str, object] = json.loads(\n"
        '    r"""\n'
        f"{encoded}\n"
        '"""\n'
        ")\n"
        "# </soak-generated-config>"
    )


def render_programs(
    validator_source: str,
    candidate: Mapping[str, Any],
) -> dict[str, str]:
    matches = CONFIG_BLOCK.findall(validator_source)
    if len(matches) != 1:
        raise GenerationError(
            "canonical validator must contain exactly one generated-config block"
        )
    candidate_sha = sha256_bytes(canonical_json_bytes(candidate))
    validator_sha = sha256_bytes(validator_source.encode("utf-8"))
    rendered: dict[str, str] = {}
    for mode, filename in OUTPUTS.items():
        block = generated_block(
            mode,
            candidate,
            candidate_sha256=candidate_sha,
            validator_sha256=validator_sha,
        )
        rendered[filename] = CONFIG_BLOCK.sub(block, validator_source, count=1)
    return rendered


def render_windows_program(
    validator_source: str,
    driver_source: str,
    candidate: Mapping[str, Any],
    validation_manifest: Mapping[str, Any],
    *,
    entry_point: str = "windows-standalone",
) -> str:
    """Render one pinned Windows entry path from the canonical core."""

    if entry_point not in {"windows-standalone", "installed-package"}:
        raise GenerationError(f"unsupported Windows entry point {entry_point!r}")

    if len(CONFIG_BLOCK.findall(validator_source)) != 1:
        raise GenerationError(
            "canonical validator must contain exactly one generated-config block"
        )
    if len(CLI_BLOCK.findall(validator_source)) != 1:
        raise GenerationError("canonical validator must contain one soak CLI block")
    if len(CLI_BLOCK.findall(driver_source)) != 1:
        raise GenerationError("Windows driver must contain one soak CLI block")

    windows_candidate = json.loads(json.dumps(candidate))
    soak = require_mapping(windows_candidate, "soak")
    soak.update(
        {
            "measured_duration_seconds": 3_600.0,
            "status_interval_seconds": 1.0,
            "info_interval_seconds": 30.0,
            "hard_deadline_seconds": 3_691.0,
            "service_container_limit_seconds": 3_721.0,
        }
    )
    candidate_sha = sha256_bytes(canonical_json_bytes(candidate))
    windows_profile_sha = sha256_bytes(canonical_json_bytes(windows_candidate))
    validator_sha = sha256_bytes(validator_source.encode("utf-8"))
    driver_sha = sha256_bytes(driver_source.encode("utf-8"))
    validation_manifest_sha = sha256_bytes(canonical_json_bytes(validation_manifest))
    config = {
        "mode": "physical-combined",
        "entry_point": entry_point,
        "generator_schema_version": 1,
        "candidate": windows_candidate,
        "candidate_sha256": candidate_sha,
        "validation_manifest": validation_manifest,
        "validation_manifest_sha256": validation_manifest_sha,
        "validator_sha256": validator_sha,
        "windows_driver_sha256": driver_sha,
        "windows_profile_sha256": windows_profile_sha,
    }
    encoded = json.dumps(config, indent=2, sort_keys=True)
    config_block = (
        "# <soak-generated-config>\n"
        "GENERATED_CONFIG: dict[str, object] = json.loads(\n"
        '    r"""\n'
        f"{encoded}\n"
        '"""\n'
        ")\n"
        "# </soak-generated-config>"
    )
    rendered = CONFIG_BLOCK.sub(lambda _match: config_block, validator_source, count=1)
    return CLI_BLOCK.sub(
        lambda _match: driver_source.rstrip("\n"),
        rendered,
        count=1,
    )


def _manifest_artifact(
    manifest: Mapping[str, Any],
    artifact_name: str,
) -> Mapping[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise GenerationError("build manifest artifacts must be a list")
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("path") == artifact_name
    ]
    if len(matches) != 1:
        raise GenerationError(
            f"build manifest must contain exactly one {artifact_name!r} artifact"
        )
    return matches[0]


def candidate_from_build(
    base: Mapping[str, Any],
    manifest: Mapping[str, Any],
    artifact_path: Path,
) -> dict[str, Any]:
    candidate = json.loads(json.dumps(base))
    artifact = require_mapping(candidate, "artifact")
    firmware = require_mapping(candidate, "firmware")
    board = require_mapping(candidate, "board")
    source = require_mapping(manifest, "source")
    target = require_mapping(manifest, "target")
    artifact_name = artifact_path.name
    manifest_artifact = _manifest_artifact(manifest, artifact_name)
    try:
        artifact_bytes = artifact_path.read_bytes()
    except OSError as error:
        raise GenerationError(
            f"could not read artifact {artifact_path}: {error}"
        ) from error
    actual_sha = sha256_bytes(artifact_bytes)
    if manifest_artifact.get("sha256") != actual_sha:
        raise GenerationError("artifact bytes do not match the build manifest SHA-256")
    source_id = source.get("source_id")
    build_id = source.get("build_id")
    fqbn = target.get("fqbn")
    if not all(
        isinstance(value, str) and value for value in (source_id, build_id, fqbn)
    ):
        raise GenerationError("build manifest source/target identity is incomplete")
    artifact.update({"name": artifact_name, "sha256": actual_sha})
    firmware.update({"source_id": source_id, "build_id": build_id})
    board["fqbn"] = fqbn
    validate_candidate(candidate)
    return candidate


def write_candidate(path: Path, candidate: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")


def write_or_check(
    rendered: Mapping[str, str],
    output_directory: Path,
    *,
    check: bool,
) -> list[str]:
    changed: list[str] = []
    for filename, expected in rendered.items():
        path = output_directory / filename
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual == expected:
            continue
        changed.append(path.relative_to(REPOSITORY_ROOT).as_posix())
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
            path.chmod(0o755)
    return changed


def write_path_or_check(
    path: Path,
    expected: str,
    *,
    check: bool,
    executable: bool = True,
) -> list[str]:
    actual = path.read_text(encoding="utf-8") if path.is_file() else None
    if actual == expected:
        return []
    try:
        display = path.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        display = str(path)
    if not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
        if executable:
            path.chmod(0o755)
    return [display]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on output drift")
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_PATH)
    parser.add_argument(
        "--candidate-freeze",
        type=Path,
        default=CANDIDATE_FREEZE_PATH,
        help="accepted two-build candidate freeze used as release evidence",
    )
    parser.add_argument(
        "--protocol-contract",
        type=Path,
        default=PROTOCOL_PATH,
        help="canonical protocol contract used to derive validation values",
    )
    parser.add_argument(
        "--validation-manifest-output",
        type=Path,
        default=VALIDATION_MANIFEST_PATH,
        help="checked deterministic release validation manifest output path",
    )
    parser.add_argument("--output-directory", type=Path, default=OUTPUT_DIRECTORY)
    parser.add_argument(
        "--windows-output",
        type=Path,
        default=WINDOWS_OUTPUT_PATH,
        help="checked standalone Windows script output path",
    )
    parser.add_argument(
        "--package-output",
        type=Path,
        default=PACKAGE_OUTPUT_PATH,
        help="checked installed-package soak implementation output path",
    )
    parser.add_argument(
        "--build-manifest",
        type=Path,
        help="refresh candidate build/source fields from this manifest",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        help="artifact whose SHA-256 must match --build-manifest",
    )
    parser.add_argument(
        "--update-candidate",
        action="store_true",
        help="persist identity refreshed from --build-manifest/--artifact",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if bool(args.build_manifest) != bool(args.artifact):
        print(
            "ERROR: --build-manifest and --artifact must be supplied together",
            file=sys.stderr,
        )
        return 2
    if args.update_candidate and (args.check or not args.build_manifest):
        print(
            "ERROR: --update-candidate requires build inputs and cannot combine with --check",
            file=sys.stderr,
        )
        return 2
    try:
        candidate = load_object(args.candidate)
        if args.build_manifest:
            candidate = candidate_from_build(
                candidate,
                load_object(args.build_manifest),
                args.artifact,
            )
            if args.update_candidate:
                write_candidate(args.candidate, candidate)
        validate_candidate(candidate)
        validator_source = VALIDATOR_PATH.read_text(encoding="utf-8")
        driver_source = WINDOWS_DRIVER_PATH.read_text(encoding="utf-8")
        candidate_freeze_bytes = args.candidate_freeze.read_bytes()
        protocol_contract_bytes = args.protocol_contract.read_bytes()
        candidate_freeze = load_object(args.candidate_freeze)
        protocol_contract = load_object(args.protocol_contract)
        validation_manifest = build_validation_manifest(
            candidate,
            protocol_contract,
            candidate_freeze,
            validator_source,
            candidate_freeze_sha256=sha256_bytes(candidate_freeze_bytes),
            protocol_contract_sha256=sha256_bytes(protocol_contract_bytes),
        )
        validation_manifest_sha = sha256_bytes(
            canonical_json_bytes(validation_manifest)
        )
        rendered = render_programs(validator_source, candidate)
        windows_rendered = render_windows_program(
            validator_source,
            driver_source,
            candidate,
            validation_manifest,
        )
        package_rendered = render_windows_program(
            validator_source,
            driver_source,
            candidate,
            validation_manifest,
            entry_point="installed-package",
        )
        changed = write_or_check(
            rendered,
            args.output_directory,
            check=args.check,
        )
        changed.extend(
            write_path_or_check(
                args.validation_manifest_output,
                json.dumps(validation_manifest, indent=2, sort_keys=True) + "\n",
                check=args.check,
                executable=False,
            )
        )
        changed.extend(
            write_path_or_check(
                args.windows_output,
                windows_rendered,
                check=args.check,
            )
        )
        changed.extend(
            write_path_or_check(
                args.package_output,
                package_rendered,
                check=args.check,
            )
        )
    except (GenerationError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.check and changed:
        print("Generated soak programs are stale:", file=sys.stderr)
        for path in changed:
            print(f"  {path}", file=sys.stderr)
        return 1
    action = "checked" if args.check else "generated"
    print(
        json.dumps(
            {
                "action": action,
                "candidate_sha256": sha256_bytes(canonical_json_bytes(candidate)),
                "validation_manifest_sha256": validation_manifest_sha,
                "outputs": sorted(
                    [
                        *rendered,
                        str(args.validation_manifest_output),
                        str(args.windows_output),
                        str(args.package_output),
                    ]
                ),
                "updated": changed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
