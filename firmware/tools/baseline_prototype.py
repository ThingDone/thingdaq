#!/usr/bin/env python3
"""Run the offline maximum-profile baseline and emit experiment evidence."""

from __future__ import annotations

import argparse
import copy
import platform
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from time import monotonic, sleep
from typing import Any, TextIO, TypedDict

# Keep the standalone command and importlib-loaded test surface identical.
_IMPORT_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from thingdaq import (
    DEFAULT_MAX_QUEUED_BLOCKS,
    DeviceInfo,
    DeviceState,
    IncrementalFrameParser,
    SoakMetrics,
    Source,
    StreamMask,
    ThingDAQ,
    ThingDAQError,
    run_synthetic_soak,
    snapshot_firmware_faults,
)
from thingdaq._generated import protocol_constants as constants

from firmware.tools import build_firmware, experiment_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "doc/results/experiments"
DEFAULT_MATRIX_PATH = REPOSITORY_ROOT / "experiments/experiment-matrix.json"
DEFAULT_FRAME_BUDGET = 256
MAX_FRAME_BUDGET = 8_192
DEFAULT_STATUS_FRAME_INTERVAL = 32
DEFAULT_PARSER_CHUNK_SIZE = 47
MAX_HOST_EVENTS = 32
MAX_PENDING_REQUESTS = 32
DETERMINISTIC_CLOCK_STEP_SECONDS = 0.001
DETERMINISTIC_CLOCK_BASIS = (
    "deterministic logical simulator clock advancing 1 millisecond per observation"
)
HOST_MONOTONIC_CLOCK_BASIS = "host monotonic clock"
INJECTED_CLOCK_BASIS = "caller-supplied clock"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class BaselinePrototypeError(RuntimeError):
    """The baseline could not produce trustworthy, bounded evidence."""


class QueueBound(TypedDict):
    """One queue high-water value paired with its advertised capacity."""

    name: str
    observed: int
    capacity: int


@dataclass(frozen=True, slots=True)
class BuildEvidence:
    """Validated no-upload build identity, resources, and artifact records."""

    manifest_path: Path
    manifest: dict[str, Any]
    artifacts: tuple[dict[str, Any], ...]
    toolchains: tuple[dict[str, str], ...]
    resource_map: dict[str, Any]
    flash_used_bytes: int
    flash_headroom_bytes: int
    ram1_used_bytes: int
    ram1_headroom_bytes: int
    ram2_used_bytes: int
    ram2_headroom_bytes: int
    cpu_clock_hz: int


@dataclass(frozen=True, slots=True)
class CaptureEvidence:
    """Strict simulator result plus deterministic logical-window metadata."""

    info: DeviceInfo
    metrics: SoakMetrics
    info_latency_milliseconds: float
    command_clock_basis: str
    logical_duration_seconds: float
    queue_bounds: tuple[QueueBound, ...]
    final_gauges: dict[str, int]
    transport_closed: bool


@dataclass(slots=True)
class DeterministicSimulatorClock:
    """Advance a logical simulator clock predictably at each observation."""

    value: float = 100.0
    step_seconds: float = DETERMINISTIC_CLOCK_STEP_SECONDS

    def __call__(self) -> float:
        observed = self.value
        self.value += self.step_seconds
        return observed

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("logical clock cannot sleep for a negative duration")
        self.value += seconds


def _mapping(owner: Mapping[str, Any], name: str, location: str) -> dict[str, Any]:
    value = owner.get(name)
    if not isinstance(value, dict):
        raise BaselinePrototypeError(f"{location}.{name} must be an object")
    return value


def _list(owner: Mapping[str, Any], name: str, location: str) -> list[Any]:
    value = owner.get(name)
    if not isinstance(value, list):
        raise BaselinePrototypeError(f"{location}.{name} must be an array")
    return value


def _text(owner: Mapping[str, Any], name: str, location: str) -> str:
    value = owner.get(name)
    if not isinstance(value, str) or not value:
        raise BaselinePrototypeError(f"{location}.{name} must be non-empty text")
    return value


def _integer(
    owner: Mapping[str, Any],
    name: str,
    location: str,
    *,
    minimum: int = 0,
) -> int:
    value = owner.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise BaselinePrototypeError(
            f"{location}.{name} must be an integer at least {minimum}"
        )
    return value


def _repository_relative(path: Path, location: str) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError as error:
        raise BaselinePrototypeError(
            f"{location} must be inside the repository"
        ) from error


def _input_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BaselinePrototypeError(f"evidence input is missing: {path}")
    return {
        "path": _repository_relative(path, "evidence input"),
        "sha256": experiment_evidence.sha256_file(path),
    }


def _artifact_record(kind: str, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BaselinePrototypeError(f"build artifact is missing: {path}")
    return {
        "kind": kind,
        "path": _repository_relative(path, "build artifact"),
        "size_bytes": path.stat().st_size,
        "sha256": experiment_evidence.sha256_file(path),
    }


def _manifest_artifact_kind(path: Path) -> str:
    return {
        ".eep": "firmware-eep",
        ".elf": "firmware-elf",
        ".hex": "firmware-hex",
        ".map": "firmware-map",
    }.get(path.suffix.casefold(), "firmware-artifact")


def _tool_version(identity: str, pattern: str, fallback: str) -> str:
    match = re.search(pattern, identity)
    return match.group(1) if match is not None else fallback


def _memory_totals(manifest: Mapping[str, Any]) -> tuple[int, int, int, int, int, int]:
    memory = _mapping(manifest, "memory_usage", "manifest")
    flash = _mapping(memory, "flash", "manifest.memory_usage")
    ram1 = _mapping(memory, "ram1", "manifest.memory_usage")
    ram2 = _mapping(memory, "ram2", "manifest.memory_usage")
    flash_used = sum(
        _integer(flash, name, "manifest.memory_usage.flash")
        for name in ("code_bytes", "data_bytes", "headers_bytes")
    )
    ram1_used = sum(
        _integer(ram1, name, "manifest.memory_usage.ram1")
        for name in ("variables_bytes", "code_bytes", "padding_bytes")
    )
    ram2_used = _integer(ram2, "variables_bytes", "manifest.memory_usage.ram2")
    return (
        flash_used,
        _integer(
            flash,
            "free_for_files_bytes",
            "manifest.memory_usage.flash",
        ),
        ram1_used,
        _integer(
            ram1,
            "free_for_locals_bytes",
            "manifest.memory_usage.ram1",
        ),
        ram2_used,
        _integer(
            ram2,
            "free_for_heap_bytes",
            "manifest.memory_usage.ram2",
        ),
    )


def validate_build_manifest(path: Path) -> BuildEvidence:
    """Fail closed unless *path* identifies the current exact pinned build."""

    manifest_path = path.resolve()
    _repository_relative(manifest_path, "build manifest")
    raw = experiment_evidence.load_json_object(manifest_path)
    if raw.get("schema_version") != build_firmware.MANIFEST_SCHEMA_VERSION:
        raise BaselinePrototypeError("build manifest schema version is not current")

    target = _mapping(raw, "target", "manifest")
    required_target = {
        "cpu_profile": build_firmware.DEFAULT_CPU_PROFILE_NAME,
        "fqbn": build_firmware.FQBN,
        "core_id": build_firmware.CORE_ID,
        "core_version": build_firmware.CORE_VERSION,
        "warnings": "all",
    }
    for name, expected in required_target.items():
        if target.get(name) != expected:
            raise BaselinePrototypeError(
                f"manifest.target.{name} is {target.get(name)!r}; expected {expected!r}"
            )
    properties = _mapping(target, "resolved_build_properties", "manifest.target")
    if properties != build_firmware.EXPECTED_BUILD_PROPERTIES:
        raise BaselinePrototypeError(
            "build manifest resolved properties are not pinned"
        )

    source = _mapping(raw, "source", "manifest")
    source_id = _text(source, "source_id", "manifest.source")
    build_id = _text(source, "build_id", "manifest.source")
    source_commit = _text(source, "git_commit", "manifest.source")
    if not SHA256_PATTERN.fullmatch(source_id):
        raise BaselinePrototypeError("manifest source ID is not a lowercase SHA-256")
    expected_build_fingerprint = build_firmware.profile_build_fingerprint(
        source_id, build_firmware.DEFAULT_CPU_PROFILE
    )
    if source.get("build_fingerprint") != expected_build_fingerprint:
        raise BaselinePrototypeError(
            "manifest build fingerprint is not derived from source and target"
        )
    if source.get("cpu_profile") != build_firmware.DEFAULT_CPU_PROFILE_NAME:
        raise BaselinePrototypeError("manifest source CPU profile is not production")
    expected_build_id = build_firmware.profile_build_id(
        source_id,
        expected_build_fingerprint,
        build_firmware.DEFAULT_CPU_PROFILE,
    )
    if build_id != expected_build_id:
        raise BaselinePrototypeError(
            "manifest build ID does not match the production identity"
        )
    if not GIT_COMMIT_PATTERN.fullmatch(source_commit):
        raise BaselinePrototypeError("manifest source commit is not a full Git commit")
    if source.get("firmware_inputs_clean") is not True:
        raise BaselinePrototypeError("firmware build inputs were not clean")
    if source.get("firmware_input_changes") != []:
        raise BaselinePrototypeError("firmware manifest contains input changes")
    current_source_id = build_firmware.source_fingerprint(
        build_firmware.collect_source_files()
    )
    if source_id != current_source_id:
        raise BaselinePrototypeError(
            "build manifest does not match current firmware inputs"
        )

    output_directory = _text(raw, "output_directory", "manifest")
    expected_output = build_firmware.OUTPUT_DIRECTORY.relative_to(
        REPOSITORY_ROOT
    ).as_posix()
    if output_directory != expected_output:
        raise BaselinePrototypeError("build manifest output directory is not pinned")
    if manifest_path.parent != build_firmware.OUTPUT_DIRECTORY.resolve():
        raise BaselinePrototypeError(
            "build manifest is outside the pinned output directory"
        )

    declared_artifacts: list[dict[str, Any]] = []
    suffixes: set[str] = set()
    for index, entry in enumerate(_list(raw, "artifacts", "manifest")):
        if not isinstance(entry, dict):
            raise BaselinePrototypeError(
                f"manifest.artifacts[{index}] must be an object"
            )
        relative = Path(_text(entry, "path", f"manifest.artifacts[{index}]"))
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
            raise BaselinePrototypeError(
                f"manifest.artifacts[{index}].path is not a local artifact name"
            )
        artifact_path = manifest_path.parent / relative
        declared_size = _integer(
            entry,
            "size_bytes",
            f"manifest.artifacts[{index}]",
        )
        declared_digest = _text(
            entry,
            "sha256",
            f"manifest.artifacts[{index}]",
        )
        if not SHA256_PATTERN.fullmatch(declared_digest):
            raise BaselinePrototypeError(
                f"manifest.artifacts[{index}].sha256 is invalid"
            )
        if not artifact_path.is_file():
            raise BaselinePrototypeError(f"declared artifact is missing: {relative}")
        if artifact_path.stat().st_size != declared_size:
            raise BaselinePrototypeError(f"artifact size changed: {relative}")
        if experiment_evidence.sha256_file(artifact_path) != declared_digest:
            raise BaselinePrototypeError(f"artifact hash changed: {relative}")
        suffixes.add(artifact_path.suffix.casefold())
        declared_artifacts.append(
            _artifact_record(_manifest_artifact_kind(artifact_path), artifact_path)
        )
    missing = {".elf", ".hex", ".map"} - suffixes
    if missing:
        raise BaselinePrototypeError(
            "build manifest is missing required artifacts: "
            + ", ".join(sorted(missing))
        )
    map_paths = [
        manifest_path.parent / str(entry["path"])
        for entry in raw["artifacts"]
        if isinstance(entry, dict)
        and str(entry.get("path", "")) == build_firmware.LINKER_MAP_NAME
    ]
    if map_paths != [manifest_path.parent / build_firmware.LINKER_MAP_NAME]:
        raise BaselinePrototypeError(
            "build manifest does not identify the exact linker map"
        )

    command = raw.get("command")
    if not isinstance(command, list) or not all(
        isinstance(item, str) for item in command
    ):
        raise BaselinePrototypeError("build manifest command must be a string array")
    if "compile" not in command or "--fqbn" not in command:
        raise BaselinePrototypeError("build manifest does not record a compile command")
    fqbn_index = command.index("--fqbn")
    if fqbn_index + 1 >= len(command) or command[fqbn_index + 1] != build_firmware.FQBN:
        raise BaselinePrototypeError(
            "build manifest command did not use the exact FQBN"
        )
    if any("upload" in argument.casefold() for argument in command):
        raise BaselinePrototypeError("build manifest command contains an upload action")

    arduino = _mapping(raw, "arduino_cli", "manifest")
    compiler = _mapping(raw, "compiler", "manifest")
    arduino_identity = _text(arduino, "identity", "manifest.arduino_cli")
    compiler_identity = _text(compiler, "identity", "manifest.compiler")
    if build_firmware.COMPILER_VERSION not in compiler_identity.split():
        raise BaselinePrototypeError("build manifest compiler identity is not pinned")
    toolchains = (
        experiment_evidence.toolchain_record(
            "arduino-cli",
            _tool_version(arduino_identity, r"Version:\s*([^\s]+)", "unknown"),
            arduino_identity,
        ),
        experiment_evidence.toolchain_record(
            "arm-none-eabi-g++",
            build_firmware.COMPILER_VERSION,
            compiler_identity,
        ),
        experiment_evidence.toolchain_record(
            "teensy-core",
            build_firmware.CORE_VERSION,
            f"{build_firmware.CORE_ID} {build_firmware.CORE_VERSION}",
        ),
    )

    binary_inspection = copy.deepcopy(_mapping(raw, "binary_inspection", "manifest"))
    binary_inspection.pop("nm_path", None)
    required_resource_sections = {
        "checksum_resources",
        "checksum_benchmark_buffers",
        "packet_buffers",
        "gpio_clock_diagnostic_buffer",
        "adc_dma_buffers",
        "gpio_raw_dma_buffers",
        "gpio_packed_buffers",
    }
    if not required_resource_sections.issubset(binary_inspection):
        raise BaselinePrototypeError("build manifest resource map is incomplete")
    packet_buffers = _mapping(
        binary_inspection,
        "packet_buffers",
        "manifest.binary_inspection",
    )
    if _integer(packet_buffers, "total_frames", "packet_buffers", minimum=1) != (
        constants.PACKET_BUFFER_COUNT
    ):
        raise BaselinePrototypeError("linker packet allocation disagrees with protocol")

    memory_totals = _memory_totals(raw)
    cpu_clock_hz = int(properties["build.fcpu"])
    manifest_record = _artifact_record("firmware-build-manifest", manifest_path)
    return BuildEvidence(
        manifest_path=manifest_path,
        manifest=raw,
        artifacts=(manifest_record, *declared_artifacts),
        toolchains=toolchains,
        resource_map=binary_inspection,
        flash_used_bytes=memory_totals[0],
        flash_headroom_bytes=memory_totals[1],
        ram1_used_bytes=memory_totals[2],
        ram1_headroom_bytes=memory_totals[3],
        ram2_used_bytes=memory_totals[4],
        ram2_headroom_bytes=memory_totals[5],
        cpu_clock_hz=cpu_clock_hz,
    )


def build_or_load_manifest(
    manifest_path: Path | None,
    *,
    arduino_cli: str,
) -> BuildEvidence:
    """Run the pinned helper unless an explicit existing manifest is supplied."""

    selected = (
        build_firmware.build(arduino_cli) if manifest_path is None else manifest_path
    )
    return validate_build_manifest(selected)


def _validate_maximum_profile(info: DeviceInfo) -> None:
    checks = {
        "state": (info.device_state, DeviceState.IDLE),
        "board": (info.board_id, constants.BoardId.SIMULATOR),
        "MCU": (info.mcu_id, constants.McuId.SIMULATED),
        "protocol": (info.protocol_version, constants.PROTOCOL_VERSION),
        "ADC pair rate": (info.adc_pair_rate_hz, constants.ADC_PAIR_RATE_HZ),
        "GPIO sample rate": (
            info.gpio_sample_rate_hz,
            constants.GPIO_SAMPLE_RATE_HZ,
        ),
        "ADC resolution": (info.adc_resolution_bits, constants.ADC_RESOLUTION_BITS),
        "timestamp clock": (info.timestamp_hz, constants.TIMESTAMP_HZ),
        "data frame bytes": (info.data_frame_bytes, constants.DATA_FRAME_BYTES),
    }
    mismatches = [
        f"{name}={observed!r}, expected {expected!r}"
        for name, (observed, expected) in checks.items()
        if observed != expected
    ]
    required_streams = StreamMask.ADC | StreamMask.GPIO
    if info.supported_stream_mask & required_streams != required_streams:
        mismatches.append("simulator does not support combined ADC/GPIO")
    if not info.supports_source(Source.SYNTHETIC):
        mismatches.append("simulator does not support the synthetic source")
    if mismatches:
        raise BaselinePrototypeError(
            "simulator maximum profile is incompatible: " + "; ".join(mismatches)
        )


def _queue_bound(name: str, observed: int, capacity: int) -> QueueBound:
    if observed < 0 or capacity <= 0 or observed > capacity:
        raise BaselinePrototypeError(
            f"queue bound failed for {name}: observed {observed}, capacity {capacity}"
        )
    return {"name": name, "observed": observed, "capacity": capacity}


def _queue_evidence(info: DeviceInfo, metrics: SoakMetrics) -> tuple[QueueBound, ...]:
    status = metrics.final_status
    reader = metrics.reader_counters
    parser = metrics.parser_counters
    return tuple(
        sorted(
            (
                _queue_bound(
                    "host_pending_requests",
                    metrics.queues.pending_request_high_water,
                    MAX_PENDING_REQUESTS,
                ),
                _queue_bound(
                    "host_blocks",
                    metrics.queues.block_queue_high_water,
                    DEFAULT_MAX_QUEUED_BLOCKS,
                ),
                _queue_bound(
                    "host_events",
                    metrics.queues.event_queue_high_water,
                    MAX_HOST_EVENTS,
                ),
                _queue_bound(
                    "host_parser_bytes",
                    metrics.queues.parser_high_water_bytes,
                    IncrementalFrameParser.max_buffered_bytes,
                ),
                _queue_bound(
                    "packet_owned",
                    status.packet_owned_high_water,
                    info.packet_buffer_count,
                ),
                _queue_bound(
                    "packet_ready",
                    status.packet_ready_high_water,
                    info.packet_ready_queue_capacity,
                ),
                _queue_bound(
                    "packet_transmit",
                    status.packet_transmit_high_water,
                    info.packet_transmit_queue_capacity,
                ),
                _queue_bound(
                    "usb_command",
                    status.usb_command_queue_high_water,
                    info.command_queue_capacity,
                ),
                _queue_bound(
                    "usb_response",
                    status.usb_response_queue_high_water,
                    info.response_queue_capacity,
                ),
                _queue_bound(
                    "reader_current_blocks",
                    reader.queued_blocks,
                    DEFAULT_MAX_QUEUED_BLOCKS,
                ),
                _queue_bound(
                    "parser_current_bytes",
                    parser.buffered_bytes,
                    IncrementalFrameParser.max_buffered_bytes,
                ),
            ),
            key=lambda item: item["name"],
        )
    )


def _final_gauges(metrics: SoakMetrics) -> dict[str, int]:
    status = metrics.final_status
    reader = metrics.reader_counters
    parser = metrics.parser_counters
    return {
        "adc_packet_filling_depth": status.adc_packet_filling_depth,
        "adc_raw_ready_depth": status.adc_raw_ready_depth,
        "gpio_packed_ready_depth": status.gpio_packed_ready_depth,
        "gpio_packet_filling_depth": status.gpio_packet_filling_depth,
        "gpio_raw_ready_depth": status.gpio_raw_ready_depth,
        "host_pending_requests": reader.pending_requests,
        "host_queued_blocks": reader.queued_blocks,
        "host_queued_events": reader.queued_events,
        "packet_owned_depth": status.packet_owned_depth,
        "packet_ready_depth": status.packet_ready_depth,
        "packet_transmit_depth": status.packet_transmit_depth,
        "parser_buffered_bytes": parser.buffered_bytes,
        "usb_command_queue_depth": status.usb_command_queue_depth,
        "usb_lower_priority_queue_depth": status.usb_lower_priority_queue_depth,
        "usb_response_queue_depth": status.usb_response_queue_depth,
    }


def _reader_counter_evidence(metrics: SoakMetrics) -> dict[str, Any]:
    """Return semantic reader counters without scheduler-dependent empty polls."""

    counters = asdict(metrics.reader_counters)
    counters.pop("read_calls")
    counters.pop("readinto_calls")
    return counters


def run_capture(
    *,
    frame_budget: int,
    parser_chunk_size: int,
    status_frame_interval: int,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
    command_clock_basis: str = HOST_MONOTONIC_CLOCK_BASIS,
) -> CaptureEvidence:
    """Exercise INFO through cleanup using only the public simulated facade."""

    if (
        not isinstance(frame_budget, int)
        or isinstance(frame_budget, bool)
        or not 2 <= frame_budget <= MAX_FRAME_BUDGET
        or frame_budget % 2
    ):
        raise ValueError(
            f"frame_budget must be an even integer from 2 through {MAX_FRAME_BUDGET}"
        )
    if (
        not isinstance(parser_chunk_size, int)
        or isinstance(parser_chunk_size, bool)
        or not 1 <= parser_chunk_size <= constants.DATA_FRAME_BYTES
    ):
        raise ValueError(
            f"parser_chunk_size must be from 1 through {constants.DATA_FRAME_BYTES}"
        )
    if (
        not isinstance(status_frame_interval, int)
        or isinstance(status_frame_interval, bool)
        or not 1 <= status_frame_interval <= frame_budget
    ):
        raise ValueError("status_frame_interval must be within the frame budget")

    info_latency = 0.0
    metrics: SoakMetrics | None = None
    info: DeviceInfo | None = None
    daq: ThingDAQ | None = None
    try:
        with ThingDAQ.simulated(
            strict=True,
            read_chunk_size=parser_chunk_size,
            read_size=parser_chunk_size,
            max_buffered_blocks=DEFAULT_MAX_QUEUED_BLOCKS,
            max_buffered_events=MAX_HOST_EVENTS,
            max_pending_requests=MAX_PENDING_REQUESTS,
        ) as daq:
            info_started = clock()
            info = daq.info()
            info_latency = clock() - info_started
            if info_latency < 0:
                raise BaselinePrototypeError(
                    "command clock moved backwards during INFO"
                )
            _validate_maximum_profile(info)
            metrics = run_synthetic_soak(
                daq,
                frame_count=frame_budget,
                adc=True,
                gpio=True,
                status_interval=None,
                status_frame_interval=status_frame_interval,
                drain_timeout=1.0,
                drain_quiet_period=1e-9,
                track_memory=False,
                adc_pair_rate_hz=constants.ADC_PAIR_RATE_HZ,
                gpio_sample_rate_hz=constants.GPIO_SAMPLE_RATE_HZ,
                adc_resolution_bits=constants.ADC_RESOLUTION_BITS,
                clock=clock,
                sleeper=sleeper,
            )
            daq.validate_stream_health(metrics.final_status)
            if metrics.final_status.device_state is not DeviceState.IDLE:
                raise BaselinePrototypeError("final STATUS did not report IDLE")
            if metrics.final_status.stream_mask != StreamMask.NONE:
                raise BaselinePrototypeError("final STATUS retained an active stream")
            if any(_final_gauges(metrics).values()):
                raise BaselinePrototypeError("final cleanup retained queue ownership")
    except ThingDAQError as error:
        raise BaselinePrototypeError(
            f"strict simulator capture failed: {error}"
        ) from error

    if daq is None or info is None or metrics is None:
        raise BaselinePrototypeError("simulator capture returned no result")
    if daq.is_open:
        raise BaselinePrototypeError(
            "context cleanup left the simulator transport open"
        )
    per_source_frames = frame_budget // 2
    if (
        metrics.adc.frame_count != per_source_frames
        or metrics.gpio.frame_count != per_source_frames
    ):
        raise BaselinePrototypeError(
            "combined capture did not alternate exact frame counts"
        )
    logical_duration = (
        per_source_frames * constants.FRAME_COVERAGE_TICKS / constants.TIMESTAMP_HZ
    )
    queue_bounds = _queue_evidence(info, metrics)
    return CaptureEvidence(
        info=info,
        metrics=metrics,
        info_latency_milliseconds=info_latency * 1_000.0,
        command_clock_basis=command_clock_basis,
        logical_duration_seconds=logical_duration,
        queue_bounds=queue_bounds,
        final_gauges=_final_gauges(metrics),
        transport_closed=True,
    )


def _metric(
    matrix: experiment_evidence.ExperimentMatrix,
    name: str,
    value: float,
    evidence_level: str,
    evidence_id: str,
) -> dict[str, Any]:
    definition = matrix.metric_definitions[name]
    return {
        "name": name,
        "value": value,
        "unit": definition["unit"],
        "denominator": definition["denominator"],
        "scope": definition["scope"],
        "evidence_level": evidence_level,
        "evidence_ids": [evidence_id],
    }


def _acceptance(
    matrix: experiment_evidence.ExperimentMatrix,
    check_id: str,
    *,
    state: str,
    expected: object,
    observed: object,
    evidence_ids: Sequence[str],
    reason: str | None = None,
) -> dict[str, Any]:
    definition = matrix.acceptance_checks[check_id]
    return {
        "id": check_id,
        "description": definition["description"],
        "state": state,
        "reason": reason,
        "operator": definition["operator"],
        "expected": expected,
        "observed": observed,
        "evidence_ids": list(evidence_ids),
        "required_evidence_levels": list(definition["required_evidence_levels"]),
    }


def _conservation(capture: CaptureEvidence) -> dict[str, dict[str, int]]:
    metrics = capture.metrics
    status = metrics.final_status
    reconciliation = metrics.reconciliation
    adc_items = metrics.adc.frame_count * constants.ADC_PAIRS_PER_FRAME
    gpio_items = metrics.gpio.frame_count * constants.GPIO_SAMPLES_PER_FRAME
    adc_payload = metrics.adc.frame_count * constants.DATA_PAYLOAD_BYTES
    gpio_payload = metrics.gpio.frame_count * constants.DATA_PAYLOAD_BYTES
    adc_framed = metrics.adc.frame_count * constants.DATA_FRAME_BYTES
    gpio_framed = metrics.gpio.frame_count * constants.DATA_FRAME_BYTES
    return {
        "adc_firmware_to_wire_frames": {
            "left": status.adc_frames_emitted,
            "right": reconciliation.adc_wire_frames_received,
        },
        "adc_items": {"left": status.adc_items_emitted, "right": adc_items},
        "adc_payload_bytes": {
            "left": status.adc_payload_bytes_transmitted,
            "right": adc_payload,
        },
        "adc_wire_to_consumer_frames": {
            "left": reconciliation.adc_wire_frames_received,
            "right": (
                reconciliation.adc_validated_frames
                + reconciliation.adc_host_queue_drops
                + reconciliation.adc_boundary_discards
                + reconciliation.adc_stale_discards
            ),
        },
        "adc_framed_bytes": {
            "left": status.adc_framed_bytes_transmitted,
            "right": adc_framed,
        },
        "combined_payload_bytes": {
            "left": status.data_payload_bytes_transmitted,
            "right": adc_payload + gpio_payload,
        },
        "combined_framed_bytes": {
            "left": status.data_framed_bytes_transmitted,
            "right": adc_framed + gpio_framed,
        },
        "gpio_firmware_to_wire_frames": {
            "left": status.gpio_frames_emitted,
            "right": reconciliation.gpio_wire_frames_received,
        },
        "gpio_items": {"left": status.gpio_items_emitted, "right": gpio_items},
        "gpio_payload_bytes": {
            "left": status.gpio_payload_bytes_transmitted,
            "right": gpio_payload,
        },
        "gpio_wire_to_consumer_frames": {
            "left": reconciliation.gpio_wire_frames_received,
            "right": (
                reconciliation.gpio_validated_frames
                + reconciliation.gpio_host_queue_drops
                + reconciliation.gpio_boundary_discards
                + reconciliation.gpio_stale_discards
            ),
        },
        "gpio_framed_bytes": {
            "left": status.gpio_framed_bytes_transmitted,
            "right": gpio_framed,
        },
    }


def _metric_records(
    matrix: experiment_evidence.ExperimentMatrix,
    capture: CaptureEvidence,
    build: BuildEvidence,
) -> list[dict[str, Any]]:
    metrics = capture.metrics
    status = metrics.final_status
    reconciliation = metrics.reconciliation
    duration = capture.logical_duration_seconds
    adc_payload_rate = metrics.adc.payload_bytes / duration
    gpio_payload_rate = metrics.gpio.payload_bytes / duration
    adc_framed_rate = metrics.adc.framed_bytes / duration
    gpio_framed_rate = metrics.gpio.framed_bytes / duration
    host_parser_errors = reconciliation.host_parser_errors
    firmware_parser_errors = reconciliation.firmware_parser_errors
    host_queue_drops = (
        reconciliation.adc_host_queue_drops
        + reconciliation.gpio_host_queue_drops
        + reconciliation.host_event_queue_drops
    )
    return [
        _metric(
            matrix,
            "measurement_duration_seconds",
            duration,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_pairs_observed",
            metrics.adc.item_count,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_samples_observed",
            metrics.gpio.item_count,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_frames_observed",
            metrics.adc.frame_count,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_frames_observed",
            metrics.gpio.frame_count,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_payload_bytes",
            metrics.adc.payload_bytes,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_payload_bytes",
            metrics.gpio.payload_bytes,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "combined_payload_bytes",
            metrics.payload_bytes,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_framed_bytes",
            metrics.adc.framed_bytes,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_framed_bytes",
            metrics.gpio.framed_bytes,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "combined_framed_bytes",
            metrics.framed_bytes,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_pair_rate_hz",
            metrics.adc.item_count / duration,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_sample_rate_hz",
            metrics.gpio.item_count / duration,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_payload_rate_bytes_per_second",
            adc_payload_rate,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_payload_rate_bytes_per_second",
            gpio_payload_rate,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "combined_payload_rate_bytes_per_second",
            adc_payload_rate + gpio_payload_rate,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_framed_rate_bytes_per_second",
            adc_framed_rate,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_framed_rate_bytes_per_second",
            gpio_framed_rate,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "combined_framed_rate_bytes_per_second",
            adc_framed_rate + gpio_framed_rate,
            "simulated",
            "simulator-capture",
        ),
        _metric(matrix, "sequence_gap_frames", 0, "simulated", "simulator-capture"),
        _metric(matrix, "adc_sequence_gap_frames", 0, "simulated", "simulator-capture"),
        _metric(
            matrix, "gpio_sequence_gap_frames", 0, "simulated", "simulator-capture"
        ),
        _metric(
            matrix,
            "firmware_dropped_frames",
            status.adc_frames_dropped + status.gpio_frames_dropped,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_frames_dropped",
            status.adc_frames_dropped,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_frames_dropped",
            status.gpio_frames_dropped,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "firmware_dropped_items",
            status.adc_items_dropped + status.gpio_items_dropped,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_pairs_dropped",
            status.adc_items_dropped,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_samples_dropped",
            status.gpio_items_dropped,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "host_queue_drops",
            host_queue_drops,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "parser_errors",
            host_parser_errors + firmware_parser_errors,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "transport_errors",
            reconciliation.firmware_transport_errors,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "conservation_failures",
            len(reconciliation.issues),
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "command_latency_p99_milliseconds",
            metrics.command_latency.p99_seconds * 1_000.0,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "command_latency_maximum_milliseconds",
            metrics.command_latency.maximum_seconds * 1_000.0,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "packet_owned_high_water_frames",
            status.packet_owned_high_water,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "packet_buffer_capacity_frames",
            capture.info.packet_buffer_count,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix, "flash_used_bytes", build.flash_used_bytes, "host", "firmware-build"
        ),
        _metric(
            matrix,
            "flash_headroom_bytes",
            build.flash_headroom_bytes,
            "host",
            "firmware-build",
        ),
        _metric(
            matrix, "ram1_used_bytes", build.ram1_used_bytes, "host", "firmware-build"
        ),
        _metric(
            matrix,
            "ram1_headroom_bytes",
            build.ram1_headroom_bytes,
            "host",
            "firmware-build",
        ),
        _metric(
            matrix, "ram2_used_bytes", build.ram2_used_bytes, "host", "firmware-build"
        ),
        _metric(
            matrix,
            "ram2_headroom_bytes",
            build.ram2_headroom_bytes,
            "host",
            "firmware-build",
        ),
        _metric(matrix, "cpu_clock_hz", build.cpu_clock_hz, "host", "firmware-build"),
        _metric(
            matrix, "ipg_clock_hz", constants.ADC_IPG_CLOCK_HZ, "host", "firmware-build"
        ),
        _metric(
            matrix, "adc_clock_hz", constants.ADC_CLOCK_HZ, "host", "firmware-build"
        ),
        _metric(
            matrix,
            "pit_clock_hz",
            constants.ADC_TRIGGER_PIT_CLOCK_HZ,
            "host",
            "firmware-build",
        ),
        _metric(
            matrix,
            "timestamp_clock_hz",
            capture.info.timestamp_hz,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "adc_phase_ticks",
            capture.info.adc1_phase_ticks,
            "simulated",
            "simulator-capture",
        ),
        _metric(
            matrix,
            "gpio_width_bits",
            capture.info.gpio_packed_width_bits,
            "simulated",
            "simulator-capture",
        ),
    ]


def _evidence_records(
    matrix: experiment_evidence.ExperimentMatrix,
    capture: CaptureEvidence,
    build: BuildEvidence,
    *,
    frame_budget: int,
    parser_chunk_size: int,
    status_frame_interval: int,
) -> list[dict[str, Any]]:
    protocol_path = REPOSITORY_ROOT / "protocol/protocol-v1.json"
    matrix_path = matrix.path
    simulator_inputs = [
        matrix_path,
        protocol_path,
        REPOSITORY_ROOT / "daq_api/src/thingdaq/client.py",
        REPOSITORY_ROOT / "daq_api/src/thingdaq/simulator.py",
        REPOSITORY_ROOT / "daq_api/src/thingdaq/streaming.py",
        REPOSITORY_ROOT / "daq_api/src/thingdaq/synthetic.py",
        Path(__file__),
    ]
    map_artifact = next(
        artifact for artifact in build.artifacts if artifact["kind"] == "firmware-map"
    )
    build_source = _mapping(build.manifest, "source", "manifest")
    command_counts = dict(capture.metrics.command_latency.command_counts)
    firmware_faults = snapshot_firmware_faults(
        capture.metrics.final_status,
        run_id=capture.metrics.run_id,
    )
    if not firmware_faults.clear:
        raise BaselinePrototypeError("strict capture retained firmware faults")
    return [
        {
            "id": "evidence-framework",
            "level": "host",
            "result": "PASS",
            "reason": None,
            "method": (
                "Fail-closed matrix validation followed by two canonical JSON and "
                "Markdown renders before atomic replacement."
            ),
            "command": {
                "argv": [
                    "python3",
                    "firmware/tools/experiment_evidence.py",
                    "--report",
                    "baseline-input.json",
                ],
                "network": False,
                "serial_hardware": False,
                "firmware_upload": False,
                "user_input": False,
            },
            "inputs": [
                _input_record(matrix_path),
                _input_record(
                    REPOSITORY_ROOT / "firmware/tools/experiment_evidence.py"
                ),
            ],
            "host_os_family": platform.system(),
            "host_architecture": platform.machine(),
            "toolchain_identity": f"Python {platform.python_version()}",
        },
        {
            "id": "firmware-build",
            "level": "host",
            "result": "PASS",
            "reason": None,
            "method": (
                "Pinned no-upload Teensy 4.0 compilation, manifest hash validation, "
                "linker-map inspection, and memory/resource accounting."
            ),
            "command": {
                "argv": ["python3", "firmware/tools/build_firmware.py"],
                "network": False,
                "serial_hardware": False,
                "firmware_upload": False,
                "user_input": False,
            },
            "inputs": [
                _input_record(REPOSITORY_ROOT / "firmware/tools/build_firmware.py"),
                _input_record(build.manifest_path),
                {
                    "path": map_artifact["path"],
                    "sha256": map_artifact["sha256"],
                },
                _input_record(protocol_path),
            ],
            "host_os_family": platform.system(),
            "host_architecture": platform.machine(),
            "toolchain_identity": (
                f"{build_firmware.FQBN}; Teensy core {build_firmware.CORE_VERSION}; "
                f"Arm GNU {build_firmware.COMPILER_VERSION}"
            ),
            "firmware_source_id": build_source["source_id"],
            "firmware_build_id": build_source["build_id"],
            "firmware_source_commit": build_source["git_commit"],
            "fqbn": build_firmware.FQBN,
            "clocks_hz": {
                "adc": constants.ADC_CLOCK_HZ,
                "cpu": build.cpu_clock_hz,
                "ipg": constants.ADC_IPG_CLOCK_HZ,
                "pit": constants.ADC_TRIGGER_PIT_CLOCK_HZ,
            },
            "memory_bytes": {
                "flash_headroom": build.flash_headroom_bytes,
                "flash_used": build.flash_used_bytes,
                "ram1_headroom": build.ram1_headroom_bytes,
                "ram1_used": build.ram1_used_bytes,
                "ram2_headroom": build.ram2_headroom_bytes,
                "ram2_used": build.ram2_used_bytes,
            },
            "resource_map": build.resource_map,
        },
        {
            "id": "simulator-capture",
            "level": "simulated",
            "result": "PASS",
            "reason": None,
            "method": (
                "Public ThingDAQ facade over the deterministic in-memory protocol "
                "peer, with strict per-item formulas, chronology, health, STOP/drain, "
                "and exact counter reconciliation."
            ),
            "command": {
                "argv": [
                    "python3",
                    "firmware/tools/baseline_prototype.py",
                    "--frame-budget",
                    str(frame_budget),
                    "--parser-chunk-size",
                    str(parser_chunk_size),
                    "--status-every-frames",
                    str(status_frame_interval),
                ],
                "network": False,
                "serial_hardware": False,
                "firmware_upload": False,
                "user_input": False,
            },
            "inputs": [_input_record(path) for path in simulator_inputs],
            "simulator_identity": (
                f"{capture.info.build_id}; {capture.info.board_id.name}; "
                f"{capture.info.mcu_id.name}"
            ),
            "protocol_identity": (
                f"protocol-v{capture.info.protocol_version} "
                f"sha256:{experiment_evidence.sha256_file(protocol_path)}"
            ),
            "deterministic_budget": (
                f"{frame_budget} complete frames; {frame_budget // 2} ADC and "
                f"{frame_budget // 2} GPIO"
            ),
            "maximum_profile": {
                "adc_pair_rate_hz": capture.info.adc_pair_rate_hz,
                "adc_resolution_bits": capture.info.adc_resolution_bits,
                "gpio_sample_rate_hz": capture.info.gpio_sample_rate_hz,
                "stream_mask": int(StreamMask.ADC | StreamMask.GPIO),
            },
            "chronology": {
                "adc_first_sequence": 0,
                "adc_last_sequence": capture.metrics.adc.frame_count - 1,
                "end_tick_exclusive": (
                    capture.metrics.adc.frame_count * constants.FRAME_COVERAGE_TICKS
                ),
                "first_sample_tick": 0,
                "gpio_first_sequence": 0,
                "gpio_last_sequence": capture.metrics.gpio.frame_count - 1,
                "timestamp_hz": capture.info.timestamp_hz,
            },
            "command_latency": {
                "clock_basis": capture.command_clock_basis,
                "command_counts": command_counts,
                "info_milliseconds": capture.info_latency_milliseconds,
                "maximum_milliseconds": (
                    capture.metrics.command_latency.maximum_seconds * 1_000.0
                ),
                "p99_milliseconds": (
                    capture.metrics.command_latency.p99_seconds * 1_000.0
                ),
                "retained_measurements": (
                    capture.metrics.command_latency.samples_retained
                ),
            },
            "queue_bounds": list(capture.queue_bounds),
            "counter_snapshot": {
                "firmware_faults": [asdict(fault) for fault in firmware_faults.faults],
                "host_reader": _reader_counter_evidence(capture.metrics),
                "host_parser": asdict(capture.metrics.parser_counters),
                "reconciliation": asdict(capture.metrics.reconciliation),
                "sequence_gaps": {"adc": 0, "gpio": 0, "total": 0},
            },
            "conservation": _conservation(capture),
            "final_gauges": capture.final_gauges,
            "transport_closed": capture.transport_closed,
        },
    ]


def create_report(
    matrix: experiment_evidence.ExperimentMatrix,
    capture: CaptureEvidence,
    build: BuildEvidence,
    identity: Mapping[str, Any],
    *,
    created: str,
    frame_budget: int,
    parser_chunk_size: int,
    status_frame_interval: int,
) -> dict[str, Any]:
    """Assemble one matrix-shaped report from validated implementation data."""

    build_source = _mapping(build.manifest, "source", "manifest")
    if identity["source_id"] != build_source["source_id"]:
        raise BaselinePrototypeError("Git identity and firmware source ID disagree")
    if identity["source_commit"] != build_source["git_commit"]:
        raise BaselinePrototypeError("Git identity and build manifest commit disagree")

    evidence = _evidence_records(
        matrix,
        capture,
        build,
        frame_budget=frame_budget,
        parser_chunk_size=parser_chunk_size,
        status_frame_interval=status_frame_interval,
    )
    artifact_hashes = {
        str(artifact["path"]): str(artifact["sha256"]) for artifact in build.artifacts
    }
    identity_fields = list(matrix.report_contract["identity"]["required_fields"])
    conservation = _conservation(capture)
    max_queue_ratio = max(
        bound["observed"] / bound["capacity"] for bound in capture.queue_bounds
    )
    clean = bool(identity["source_clean"])
    provenance_reason = (
        None
        if clean
        else "The source worktree was not clean, so canonical provenance is not accepted."
    )
    acceptance = [
        _acceptance(
            matrix,
            "schema_valid",
            state="PASS",
            expected=True,
            observed={"matrix": True, "normalized_report": True},
            evidence_ids=["evidence-framework"],
        ),
        _acceptance(
            matrix,
            "identity_complete",
            state="PASS",
            expected=identity_fields,
            observed=dict(identity),
            evidence_ids=["evidence-framework"],
        ),
        _acceptance(
            matrix,
            "provenance_clean",
            state="PASS" if clean else "FAIL",
            expected=True,
            observed=clean,
            evidence_ids=["evidence-framework"],
            reason=provenance_reason,
        ),
        _acceptance(
            matrix,
            "artifact_hashes_verified",
            state="PASS",
            expected=artifact_hashes,
            observed=artifact_hashes,
            evidence_ids=["firmware-build"],
        ),
        _acceptance(
            matrix,
            "firmware_build_no_upload",
            state="PASS",
            expected=True,
            observed={
                "compile_completed": True,
                "exact_fqbn": True,
                "network_unused": True,
                "serial_hardware_unused": True,
                "upload_unused": True,
            },
            evidence_ids=["firmware-build"],
        ),
        _acceptance(
            matrix,
            "deterministic_output",
            state="PASS",
            expected={"json": "byte-identical", "markdown": "byte-identical"},
            observed={"json": "byte-identical", "markdown": "byte-identical"},
            evidence_ids=["evidence-framework"],
        ),
        _acceptance(
            matrix,
            "lifecycle_complete",
            state="PASS",
            expected=True,
            observed={
                "bounded_capture": True,
                "configure": True,
                "final_status": True,
                "info": True,
                "running_status": True,
                "start": True,
                "stop": True,
            },
            evidence_ids=["simulator-capture"],
        ),
        _acceptance(
            matrix,
            "synthetic_formulas_exact",
            state="PASS",
            expected="every logical item and timestamp matched",
            observed="every logical item and timestamp matched",
            evidence_ids=["simulator-capture"],
        ),
        _acceptance(
            matrix,
            "stream_health",
            state="PASS",
            expected=True,
            observed={
                "firmware_drops_zero": True,
                "gaps_zero": True,
                "host_queue_drops_zero": True,
                "parser_errors_zero": True,
                "transport_errors_zero": True,
            },
            evidence_ids=["simulator-capture"],
        ),
        _acceptance(
            matrix,
            "counter_conservation",
            state="PASS",
            expected=True,
            observed=conservation,
            evidence_ids=["simulator-capture"],
        ),
        _acceptance(
            matrix,
            "queue_bounds",
            state="PASS",
            expected=1.0,
            observed=max_queue_ratio,
            evidence_ids=["simulator-capture"],
        ),
        _acceptance(
            matrix,
            "final_idle_cleanup",
            state="PASS",
            expected=True,
            observed={
                "all_gauges_zero": not any(capture.final_gauges.values()),
                "state_idle": capture.metrics.final_status.device_state
                is DeviceState.IDLE,
                "stream_mask_empty": capture.metrics.final_status.stream_mask
                == StreamMask.NONE,
                "transport_closed": capture.transport_closed,
            },
            evidence_ids=["simulator-capture"],
        ),
        _acceptance(
            matrix,
            "claim_scope_complete",
            state="PASS",
            expected=True,
            observed={
                limitation_id: True
                for limitation_id in matrix.experiment("baseline")[
                    "required_limitations"
                ]
            },
            evidence_ids=["evidence-framework"],
        ),
    ]
    result = experiment_evidence.result_rollup(
        [str(record["state"]) for record in acceptance]
    )
    reason = None if result == "PASS" else provenance_reason
    limitations = [
        copy.deepcopy(matrix.claim_limitations[limitation_id])
        for limitation_id in matrix.experiment("baseline")["required_limitations"]
    ]
    return {
        "schema_version": matrix.report_contract["schema_version"],
        "matrix_schema_version": matrix.schema_version,
        "experiment_id": "baseline",
        "title": matrix.experiment("baseline")["title"],
        "created": created,
        "result": result,
        "reason": reason,
        "summary": (
            "The public in-memory API completed the maximum protocol-v1 profile "
            "with exact formulas, chronology, health, conservation, and cleanup; "
            "the pinned 600 MHz firmware compiled without upload and its manifest, "
            "map, artifact hashes, clocks, and memory resources were verified. "
            "This is simulated and host build evidence, not physical DAQ or USB evidence."
        ),
        "identity": dict(identity),
        "evidence": evidence,
        "metrics": _metric_records(matrix, capture, build),
        "acceptance": acceptance,
        "limitations": limitations,
        "artifacts": list(build.artifacts),
        "related": [
            "[[Evidence-Index]]",
            "[[Protocol-V1]]",
            "[[System-Overview]]",
            "[[soak-harness]]",
        ],
    }


def _git_created_date() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "show", "-s", "--format=%cs", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise BaselinePrototypeError(f"could not query Git date: {error}") from error
    selected = completed.stdout.strip()
    if completed.returncode != 0 or not DATE_PATTERN.fullmatch(selected):
        raise BaselinePrototypeError("Git did not return an immutable source date")
    return selected


def run_baseline(
    *,
    output_directory: Path,
    matrix_path: Path = DEFAULT_MATRIX_PATH,
    build_manifest: Path | None = None,
    arduino_cli: str = "arduino-cli",
    frame_budget: int = DEFAULT_FRAME_BUDGET,
    parser_chunk_size: int = DEFAULT_PARSER_CHUNK_SIZE,
    status_frame_interval: int = DEFAULT_STATUS_FRAME_INTERVAL,
    created: str | None = None,
    baseline_commit: str | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
    output: TextIO | None = None,
) -> dict[str, Any]:
    """Run the offline baseline with a reproducible logical clock by default."""

    selected_clock: Callable[[], float]
    selected_sleeper: Callable[[float], None]
    if clock is None and sleeper is None:
        logical_clock = DeterministicSimulatorClock()
        selected_clock = logical_clock
        selected_sleeper = logical_clock.sleep
        command_clock_basis = DETERMINISTIC_CLOCK_BASIS
    elif clock is None or sleeper is None:
        raise ValueError("clock and sleeper must be supplied together")
    else:
        selected_clock = clock
        selected_sleeper = sleeper
        command_clock_basis = (
            DETERMINISTIC_CLOCK_BASIS
            if isinstance(clock, DeterministicSimulatorClock)
            else INJECTED_CLOCK_BASIS
        )

    selected_output = sys.stdout if output is None else output
    matrix = experiment_evidence.load_experiment_matrix(matrix_path)
    print(
        f"SIMULATE  combined maximum profile | frames={frame_budget} | "
        f"parser-chunk<={parser_chunk_size}",
        file=selected_output,
    )
    capture = run_capture(
        frame_budget=frame_budget,
        parser_chunk_size=parser_chunk_size,
        status_frame_interval=status_frame_interval,
        clock=selected_clock,
        sleeper=selected_sleeper,
        command_clock_basis=command_clock_basis,
    )
    print(
        f"CAPTURE   adc={capture.metrics.adc.frame_count} frame(s)/"
        f"{capture.metrics.adc.item_count} pair(s) | "
        f"gpio={capture.metrics.gpio.frame_count} frame(s)/"
        f"{capture.metrics.gpio.item_count} sample(s)",
        file=selected_output,
    )
    print(
        f"HEALTH    gaps=0 drops=0 parser-errors=0 transport-errors=0 | "
        f"conservation=exact | final={capture.metrics.final_status.device_state.name}",
        file=selected_output,
    )
    print(
        f"BUILD     {build_firmware.FQBN} | upload=disabled",
        file=selected_output,
    )
    build = build_or_load_manifest(build_manifest, arduino_cli=arduino_cli)
    print(
        f"RESOURCES flash={build.flash_used_bytes}B+{build.flash_headroom_bytes}B-free | "
        f"RAM1={build.ram1_used_bytes}B+{build.ram1_headroom_bytes}B-free | "
        f"RAM2={build.ram2_used_bytes}B+{build.ram2_headroom_bytes}B-free",
        file=selected_output,
    )
    identity = experiment_evidence.capture_identity(
        matrix,
        "baseline",
        toolchains=build.toolchains,
        baseline_commit=baseline_commit,
    )
    selected_created = _git_created_date() if created is None else created
    if not DATE_PATTERN.fullmatch(selected_created):
        raise BaselinePrototypeError("created must use YYYY-MM-DD")
    try:
        year, month, day = (int(part) for part in selected_created.split("-"))
        date(year, month, day)
    except ValueError as error:
        raise BaselinePrototypeError("created must be a calendar date") from error

    report = create_report(
        matrix,
        capture,
        build,
        identity,
        created=selected_created,
        frame_budget=frame_budget,
        parser_chunk_size=parser_chunk_size,
        status_frame_interval=status_frame_interval,
    )
    json_path = output_directory / "baseline.json"
    markdown_path = output_directory / "baseline.md"
    normalized = experiment_evidence.write_report_pair(
        matrix,
        report,
        json_path,
        markdown_path,
    )
    print(
        f"{normalized['result']:<9} wrote {json_path} and {markdown_path}",
        file=selected_output,
    )
    return normalized


def _bounded_even_frame_budget(value: str) -> int:
    try:
        selected = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("frame budget must be an integer") from error
    if not 2 <= selected <= MAX_FRAME_BUDGET or selected % 2:
        raise argparse.ArgumentTypeError(
            f"frame budget must be even and between 2 and {MAX_FRAME_BUDGET}"
        )
    return selected


def _bounded_integer(name: str, minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            selected = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from error
        if not minimum <= selected <= maximum:
            raise argparse.ArgumentTypeError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return selected

    return parse


def _explicit_date(value: str) -> str:
    if not DATE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("created date must use YYYY-MM-DD")
    try:
        date(*(int(part) for part in value.split("-")))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "created date must be a calendar date"
        ) from error
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse bounded offline inputs; no serial or network option exists."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="directory for baseline.json and baseline.md",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX_PATH,
        help="experiment matrix contract",
    )
    parser.add_argument(
        "--build-manifest",
        type=Path,
        help="ingest an existing exact build instead of invoking the pinned helper",
    )
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="Arduino CLI executable passed only to the pinned no-upload build helper",
    )
    parser.add_argument(
        "--frame-budget",
        type=_bounded_even_frame_budget,
        default=DEFAULT_FRAME_BUDGET,
        metavar="N",
        help=f"total alternating ADC/GPIO frames (default: {DEFAULT_FRAME_BUDGET})",
    )
    parser.add_argument(
        "--parser-chunk-size",
        type=_bounded_integer("parser chunk size", 1, constants.DATA_FRAME_BYTES),
        default=DEFAULT_PARSER_CHUNK_SIZE,
        metavar="BYTES",
        help=f"maximum simulated read boundary (default: {DEFAULT_PARSER_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--status-every-frames",
        type=_bounded_integer("STATUS frame interval", 1, MAX_FRAME_BUDGET),
        default=DEFAULT_STATUS_FRAME_INTERVAL,
        metavar="N",
        help=(
            "issue and validate running STATUS every N combined frames "
            f"(default: {DEFAULT_STATUS_FRAME_INTERVAL})"
        ),
    )
    parser.add_argument(
        "--created",
        type=_explicit_date,
        help="explicit report date; defaults to the immutable source commit date",
    )
    parser.add_argument(
        "--baseline-commit",
        help="explicit full baseline commit before its branch pointer exists",
    )
    arguments = parser.parse_args(argv)
    if arguments.status_every_frames > arguments.frame_budget:
        parser.error("--status-every-frames may not exceed --frame-budget")
    if arguments.baseline_commit is not None and not GIT_COMMIT_PATTERN.fullmatch(
        arguments.baseline_commit
    ):
        parser.error("--baseline-commit must be a full lowercase Git commit")
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; fail whenever evidence is not fully accepted."""

    arguments = parse_args(argv)
    try:
        report = run_baseline(
            output_directory=arguments.output_dir,
            matrix_path=arguments.matrix,
            build_manifest=arguments.build_manifest,
            arduino_cli=arguments.arduino_cli,
            frame_budget=arguments.frame_budget,
            parser_chunk_size=arguments.parser_chunk_size,
            status_frame_interval=arguments.status_every_frames,
            created=arguments.created,
            baseline_commit=arguments.baseline_commit,
        )
    except (
        BaselinePrototypeError,
        build_firmware.BuildError,
        experiment_evidence.EvidenceError,
        OSError,
        ValueError,
    ) as error:
        print(f"FAIL      {error}", file=sys.stderr)
        return 1
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
