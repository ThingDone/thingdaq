#!/usr/bin/env python3
"""Aggregate saved remote-service results and Phase 11 soak metadata."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

AGGREGATE_SCHEMA_VERSION = 1
SOAK_RESULT_PREFIX = "SOAK_RESULT "
JOB_ID_PATTERN = re.compile(
    r"(?:JOB_ID|TEST_ID|job_id|test_id)\s*[=:]\s*"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
CLASS_ACCEPTED = "accepted"
CLASS_TEST_FAILURE = "test_failure"
CLASS_PROGRAM_FAILURE = "program_failure"
CLASS_UPLOAD_FAILURE = "upload_failure"
CLASS_SERVICE_FAILURE = "service_failure"
CLASS_EVIDENCE_FAILURE = "evidence_failure"

PHASE_11_REQUIRED_MODE_COUNTS = {
    "synthetic": 2,
    "physical-combined": 3,
    "control-stress": 1,
}
PHASE_11_MEASURED_DURATION_SECONDS = 600.0
PHASE_11_RATE_TOLERANCE_FRACTION = 0.01
PHASE_04_STATUS_P99_LIMIT_MILLISECONDS = 100.0
PHASE_04_STATUS_MAXIMUM_LIMIT_MILLISECONDS = 250.0
PHASE_04_COMMAND_MAXIMUM_LIMIT_MILLISECONDS = 500.0
MAX_RSS_GROWTH_BYTES = 32 * 1024 * 1024
MAX_TRACED_GROWTH_BYTES = 16 * 1024 * 1024
ADC_PAIRS_PER_FRAME = 1_012
ADC_BYTES_PER_PAIR = 4
GPIO_SAMPLES_PER_FRAME = 4_048
DATA_PAYLOAD_BYTES = 4_048
DATA_FRAME_BYTES = 4_096
TARGET_PAYLOAD_BYTES_PER_SECOND = 8_000_000.0
TARGET_FRAMED_BYTES_PER_SECOND = (
    TARGET_PAYLOAD_BYTES_PER_SECOND * DATA_FRAME_BYTES / DATA_PAYLOAD_BYTES
)
TARGET_ADC_PAIR_RATE_HZ = 1_000_000.0
TARGET_GPIO_SAMPLE_RATE_HZ = 4_000_000.0

REQUIRED_ZERO_ERROR_COUNTERS = (
    "adc_destination_mismatches",
    "adc_dma_error_events",
    "adc_etc_error_events",
    "adc_etc_error_flags",
    "adc_overwritten_conversions",
    "adc_packer_chronology_errors",
    "adc_packer_pipeline_errors",
    "adc_packer_source_errors",
    "adc_raw_invariant_errors",
    "adc_raw_ring_overruns",
    "adc_resource_conflicts",
    "adc_schedule_exhaustions",
    "adc_stale_completions",
    "adc_stale_interrupts",
    "adc_start_errors",
    "adc_stop_errors",
    "bad_checksums",
    "bad_lengths",
    "bad_types",
    "bad_versions",
    "gpio_hardware_errors",
    "gpio_packer_chronology_errors",
    "gpio_packer_pipeline_errors",
    "gpio_packer_samples_dropped",
    "gpio_packer_source_errors",
    "gpio_raw_invariant_errors",
    "gpio_raw_ring_overruns",
    "gpio_resource_conflicts",
    "gpio_stale_dma_completions",
    "gpio_start_errors",
    "gpio_stop_errors",
    "packet_encoding_rejections",
    "packet_invalid_operations",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
    "parser_errors",
    "partial_usb_writes",
    "state_errors",
    "timeouts",
    "transport_errors",
    "usb_io_errors",
    "usb_rx_stall_events",
)


class AggregateError(RuntimeError):
    """An input cannot be represented without guessing."""


@dataclass
class Fragment:
    path: str
    job_id: str | None = None
    service: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    soak: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class JobRecord:
    job_id: str
    paths: list[str] = field(default_factory=list)
    service: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    soak: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def merge(self, fragment: Fragment) -> None:
        self.paths.append(fragment.path)
        self.warnings.extend(fragment.warnings)
        if fragment.service is not None:
            if self.service is not None and self.service != fragment.service:
                self.warnings.append("conflicting service-result fragments")
            self.service = fragment.service
        if fragment.soak is not None:
            if self.soak is not None and self.soak != fragment.soak:
                self.warnings.append("conflicting SOAK_RESULT fragments")
            self.soak = fragment.soak
        self.metadata = deep_merge(self.metadata, fragment.metadata)


def deep_merge(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(left)
    for key, value in right.items():
        previous = result.get(key)
        if isinstance(previous, dict) and isinstance(value, dict):
            result[key] = deep_merge(previous, value)
        else:
            result[key] = value
    return result


def _json_object(value: object, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AggregateError(f"{owner} must be a JSON object")
    return value


def _extract_soak_result(stdout: str) -> tuple[dict[str, Any] | None, list[str]]:
    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    saw_prefix = False
    for line in stdout.splitlines():
        if not line.startswith(SOAK_RESULT_PREFIX):
            continue
        saw_prefix = True
        encoded = line[len(SOAK_RESULT_PREFIX) :]
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as error:
            warnings.append(f"truncated/invalid SOAK_RESULT JSON: {error}")
            continue
        if not isinstance(value, dict):
            warnings.append("SOAK_RESULT payload is not an object")
            continue
        matches.append(value)
    if len(matches) > 1:
        warnings.append("stdout contains multiple SOAK_RESULT records")
    if saw_prefix and not matches:
        warnings.append("stdout contains no complete SOAK_RESULT record")
    return (matches[-1] if matches else None), warnings


def _job_id_from_mapping(value: Mapping[str, Any]) -> str | None:
    for name in ("job_id", "test_id"):
        candidate = value.get(name)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _fragment_from_service(
    path: Path,
    service: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> Fragment:
    service_object = dict(service)
    stdout = service_object.get("stdout")
    soak: dict[str, Any] | None = None
    warnings: list[str] = []
    if isinstance(stdout, str):
        soak, warnings = _extract_soak_result(stdout)
    else:
        warnings.append("service result stdout is missing or not text")
    return Fragment(
        path=str(path),
        job_id=_job_id_from_mapping(service_object),
        service=service_object,
        metadata=dict(metadata or {}),
        soak=soak,
        warnings=warnings,
    )


def parse_json_fragment(path: Path, value: Mapping[str, Any]) -> list[Fragment]:
    fragments: list[Fragment] = []
    if isinstance(value.get("jobs"), list):
        for index, raw_job in enumerate(value["jobs"]):
            job = _json_object(raw_job, f"{path}:jobs[{index}]")
            service = job.get("service_result") or job.get("service")
            metadata = job.get("job_metadata") or job.get("metadata") or {}
            if service is None:
                fragments.append(
                    Fragment(
                        path=f"{path}#jobs[{index}]",
                        job_id=_job_id_from_mapping(job),
                        metadata=_json_object(metadata, "job metadata"),
                        soak=(
                            _json_object(job["soak_result"], "soak_result")
                            if isinstance(job.get("soak_result"), dict)
                            else None
                        ),
                        warnings=["job bundle has no service result"],
                    )
                )
            else:
                fragment = _fragment_from_service(
                    path,
                    _json_object(service, "service_result"),
                    _json_object(metadata, "job_metadata"),
                )
                fragment.path = f"{path}#jobs[{index}]"
                fragment.job_id = fragment.job_id or _job_id_from_mapping(job)
                fragments.append(fragment)
        return fragments

    if isinstance(value.get("results"), dict):
        metadata = value.get("job_metadata") or value.get("metadata") or {}
        return [
            _fragment_from_service(
                path,
                _json_object(value["results"], "results"),
                _json_object(metadata, "metadata"),
            )
        ]
    if isinstance(value.get("service_result"), dict):
        metadata = value.get("job_metadata") or value.get("metadata") or {}
        fragment = _fragment_from_service(
            path,
            _json_object(value["service_result"], "service_result"),
            _json_object(metadata, "job_metadata"),
        )
        fragment.job_id = fragment.job_id or _job_id_from_mapping(value)
        if isinstance(value.get("soak_result"), dict):
            fragment.soak = _json_object(value["soak_result"], "soak_result")
        return [fragment]
    if any(name in value for name in ("exit_code", "program_success", "completed")):
        return [_fragment_from_service(path, value)]
    if value.get("schema_version") == 1 and value.get("mode") is not None:
        return [
            Fragment(
                path=str(path),
                job_id=_job_id_from_mapping(value),
                soak=dict(value),
                warnings=["standalone SOAK_RESULT has no service result"],
            )
        ]
    metadata = dict(value)
    return [
        Fragment(
            path=str(path),
            job_id=_job_id_from_mapping(metadata),
            metadata=metadata,
        )
    ]


def parse_text_fragment(path: Path, text: str) -> Fragment:
    soak, warnings = _extract_soak_result(text)
    match = JOB_ID_PATTERN.search(text)
    metadata: dict[str, Any] = {}
    for line in text.splitlines():
        name, separator, raw_value = line.partition("=")
        if not separator:
            continue
        if name in {
            "CLIENT_RUN_STARTED_UTC",
            "CLIENT_RUN_COMPLETED_UTC",
            "ARTIFACT_SHA256",
            "PROGRAM_SHA256",
            "SOURCE_ID",
            "BUILD_ID",
        }:
            metadata[name.lower()] = raw_value.strip()
    return Fragment(
        path=str(path),
        job_id=match.group(1) if match else None,
        metadata=metadata,
        soak=soak,
        warnings=[*warnings, "client log has no authoritative service result"],
    )


def parse_path(path: Path) -> list[Fragment]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise AggregateError(f"could not read {path}: {error}") from error
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return [parse_text_fragment(path, text)]
    return parse_json_fragment(path, _json_object(value, str(path)))


def group_fragments(fragments: Iterable[Fragment]) -> list[JobRecord]:
    grouped: dict[str, JobRecord] = {}
    anonymous = 0
    for fragment in fragments:
        job_id = fragment.job_id
        if job_id is None:
            anonymous += 1
            job_id = f"unknown:{anonymous}:{Path(fragment.path).name}"
            fragment.warnings.append("job/test ID is missing")
        record = grouped.setdefault(job_id, JobRecord(job_id))
        record.merge(fragment)
    return list(grouped.values())


def nested(value: Mapping[str, Any] | None, *path: str) -> Any:
    current: Any = value
    for name in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(name)
    return current


def first_value(value: Mapping[str, Any], paths: Iterable[tuple[str, ...]]) -> Any:
    for path in paths:
        result = nested(value, *path)
        if result is not None:
            return result
    return None


def normalize_metadata(record: JobRecord) -> dict[str, Any]:
    metadata = record.metadata
    result = {
        "artifact_sha256": first_value(
            metadata,
            (
                ("artifact_sha256",),
                ("artifact", "sha256"),
                ("firmware_artifact", "sha256"),
            ),
        ),
        "program_sha256": first_value(
            metadata,
            (("program_sha256",), ("program", "sha256")),
        ),
        "source_id": first_value(
            metadata,
            (("source_id",), ("firmware", "source_id")),
        ),
        "build_id": first_value(
            metadata,
            (("build_id",), ("firmware", "build_id")),
        ),
        "client_started_utc": first_value(
            metadata,
            (
                ("client_started_utc",),
                ("client_run_started_utc",),
                ("started_utc",),
            ),
        ),
        "client_completed_utc": first_value(
            metadata,
            (
                ("client_completed_utc",),
                ("client_run_completed_utc",),
                ("completed_utc",),
            ),
        ),
        "service_version": first_value(
            metadata,
            (("service_version",), ("service", "version")),
        ),
        "client_version": first_value(
            metadata,
            (("client_version",), ("client", "version")),
        ),
    }
    return result


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def identity_problems(record: JobRecord, metadata: Mapping[str, Any]) -> list[str]:
    soak = record.soak
    if soak is None:
        return []
    expected = nested(soak, "expected")
    observed = nested(soak, "observed_identity")
    problems: list[str] = []
    if not isinstance(expected, Mapping):
        return ["SOAK_RESULT expected identity is missing"]
    if not isinstance(observed, Mapping):
        problems.append("SOAK_RESULT observed identity is missing")
    else:
        for name in (
            "protocol_version",
            "firmware_version",
            "build_id",
            "hardware_serial",
            "board_id",
            "mcu_id",
        ):
            if expected.get(name) != observed.get(name):
                problems.append(f"expected/observed {name} mismatch")
    for name in ("artifact_sha256", "source_id", "build_id"):
        expected_value = expected.get(name)
        metadata_value = metadata.get(name)
        if not isinstance(expected_value, str) or not expected_value:
            problems.append(f"expected {name} is missing")
        if not isinstance(metadata_value, str) or not metadata_value:
            problems.append(f"job metadata {name} is missing")
        elif metadata_value != expected_value:
            problems.append(f"job metadata {name} mismatch")
    artifact_sha = metadata.get("artifact_sha256")
    if isinstance(artifact_sha, str) and not SHA256_PATTERN.fullmatch(artifact_sha):
        problems.append("job metadata artifact_sha256 is malformed")
    program_expected = nested(soak, "program", "sha256")
    program_metadata = metadata.get("program_sha256")
    if not isinstance(program_metadata, str) or not program_metadata:
        problems.append("job metadata program_sha256 is missing")
    elif program_metadata != program_expected:
        problems.append("job metadata program_sha256 mismatch")
    if _aware_datetime(metadata.get("client_started_utc")) is None:
        problems.append("client_started_utc is missing or timezone-naive")
    if _aware_datetime(metadata.get("client_completed_utc")) is None:
        problems.append("client_completed_utc is missing or timezone-naive")
    return problems


def classify(record: JobRecord) -> tuple[str, str, list[str]]:
    service = record.service
    metadata = normalize_metadata(record)
    problems = list(record.warnings)
    if service is None:
        return CLASS_SERVICE_FAILURE, "infrastructure_retry_once", problems
    completed = service.get("completed")
    program_success = service.get("program_success")
    exit_code = service.get("exit_code")
    message = service.get("message")
    if completed is not True:
        problems.append("service result is not terminal completed=true")
        return CLASS_SERVICE_FAILURE, "infrastructure_retry_once", problems
    if (
        program_success is False
        or exit_code == -130
        or (isinstance(message, str) and "loading program" in message.lower())
    ):
        return CLASS_UPLOAD_FAILURE, "infrastructure_retry_once", problems
    if program_success is not True or not isinstance(exit_code, int) or exit_code < 0:
        problems.append("service/programming status is incomplete or negative")
        return CLASS_SERVICE_FAILURE, "infrastructure_retry_once", problems
    soak = record.soak
    if soak is None:
        problems.append("test program emitted no complete SOAK_RESULT")
        return CLASS_PROGRAM_FAILURE, "diagnose_harness", problems
    if soak.get("schema_version") != 1 or soak.get("mode") not in {
        "synthetic",
        "physical-combined",
        "control-stress",
    }:
        problems.append("SOAK_RESULT schema or mode is invalid")
        return CLASS_PROGRAM_FAILURE, "diagnose_harness", problems
    if exit_code != 0 or soak.get("result") != "PASS":
        return CLASS_TEST_FAILURE, "release_candidate_failure", problems
    evidence_problems = identity_problems(record, metadata)
    if evidence_problems:
        problems.extend(evidence_problems)
        return CLASS_EVIDENCE_FAILURE, "diagnose_harness", problems
    return CLASS_ACCEPTED, "count", problems


def _finite_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if math.isfinite(converted):
            return converted
    return None


def comparable_metrics(soak: Mapping[str, Any] | None) -> dict[str, float | int | None]:
    if soak is None:
        return {}
    metrics = nested(soak, "metrics")
    timing = nested(soak, "timing")
    if not isinstance(metrics, Mapping):
        metrics = {}
    if not isinstance(timing, Mapping):
        timing = {}
    status = nested(metrics, "latency", "status")
    commands = nested(metrics, "latency", "all_commands")
    memory = nested(metrics, "memory")
    queues = nested(metrics, "maximum_queues")
    if not isinstance(status, Mapping):
        status = {}
    if not isinstance(commands, Mapping):
        commands = {}
    if not isinstance(memory, Mapping):
        memory = {}
    if not isinstance(queues, Mapping):
        queues = {}
    status_p99 = _finite_number(status.get("p99_seconds"))
    status_max = _finite_number(status.get("maximum_seconds"))
    command_max = _finite_number(commands.get("maximum_seconds"))
    return {
        "measured_duration_seconds": _finite_number(
            timing.get("measured_duration_seconds")
        ),
        "measured_elapsed_seconds": _finite_number(
            timing.get("measured_elapsed_seconds")
        ),
        "streaming_elapsed_seconds": _finite_number(
            timing.get("streaming_elapsed_seconds")
        ),
        "payload_bytes": _integer_or_none(metrics.get("payload_bytes")),
        "framed_bytes": _integer_or_none(metrics.get("framed_bytes")),
        "payload_bytes_per_second": _finite_number(
            metrics.get("payload_bytes_per_streaming_second")
        ),
        "framed_bytes_per_second": _finite_number(
            metrics.get("framed_bytes_per_streaming_second")
        ),
        "adc_pair_rate_hz": _finite_number(metrics.get("adc_pair_rate_hz")),
        "gpio_sample_rate_hz": _finite_number(metrics.get("gpio_sample_rate_hz")),
        "status_p99_milliseconds": (
            status_p99 * 1_000 if status_p99 is not None else None
        ),
        "status_maximum_milliseconds": (
            status_max * 1_000 if status_max is not None else None
        ),
        "command_maximum_milliseconds": (
            command_max * 1_000 if command_max is not None else None
        ),
        "traced_growth_bytes": _integer_or_none(
            nested(memory, "tracemalloc", "growth_bytes")
        ),
        "rss_growth_bytes": _integer_or_none(
            nested(memory, "process_rss", "growth_bytes")
        ),
        "minimum_available_bytes": _integer_or_none(
            memory.get("minimum_available_bytes")
        ),
        "packet_owned_high_water_frames": _integer_or_none(
            queues.get("packet_owned_high_water")
        ),
        "packet_ready_high_water_frames": _integer_or_none(
            queues.get("packet_ready_high_water")
        ),
        "packet_transmit_high_water_frames": _integer_or_none(
            queues.get("packet_transmit_high_water")
        ),
    }


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def record_summary(record: JobRecord) -> dict[str, Any]:
    classification, disposition, problems = classify(record)
    service = record.service or {}
    metadata = normalize_metadata(record)
    return {
        "job_id": record.job_id,
        "classification": classification,
        "disposition": disposition,
        "mode": record.soak.get("mode") if record.soak else None,
        "paths": sorted(set(record.paths)),
        "service": {
            "completed": service.get("completed"),
            "program_success": service.get("program_success"),
            "exit_code": service.get("exit_code"),
            "message": service.get("message"),
            "timestamp": service.get("timestamp"),
        },
        "test_exit_status": service.get("exit_code"),
        "job_metadata": metadata,
        "identity": {
            "expected": nested(record.soak, "expected"),
            "observed": nested(record.soak, "observed_identity"),
        },
        "metrics": comparable_metrics(record.soak),
        "failure": nested(record.soak, "failure"),
        "problems": sorted(set(problems)),
    }


def apply_sequential_checks(runs: list[dict[str, Any]]) -> bool:
    accepted = [run for run in runs if run["classification"] == CLASS_ACCEPTED]
    accepted.sort(
        key=lambda run: (
            _aware_datetime(run["job_metadata"].get("client_started_utc"))
            or datetime.max.replace(tzinfo=timezone.utc)
        )
    )
    sequential = True
    previous_end: datetime | None = None
    for run in accepted:
        started = _aware_datetime(run["job_metadata"].get("client_started_utc"))
        completed = _aware_datetime(run["job_metadata"].get("client_completed_utc"))
        nonoverlap = (
            started is not None
            and completed is not None
            and started <= completed
            and (previous_end is None or started >= previous_end)
        )
        run["sequential_to_previous"] = nonoverlap
        sequential = sequential and nonoverlap
        if completed is not None:
            previous_end = completed
    return sequential


TREND_METRICS = (
    "payload_bytes_per_second",
    "framed_bytes_per_second",
    "adc_pair_rate_hz",
    "gpio_sample_rate_hz",
    "status_p99_milliseconds",
    "command_maximum_milliseconds",
    "traced_growth_bytes",
    "rss_growth_bytes",
    "packet_owned_high_water_frames",
)


def trend_summary(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run["classification"] == CLASS_ACCEPTED and isinstance(run["mode"], str):
            grouped[run["mode"]].append(run)
    result: dict[str, Any] = {}
    for mode, mode_runs in grouped.items():
        mode_result: dict[str, Any] = {}
        for metric in TREND_METRICS:
            values = [
                value
                for run in mode_runs
                if (value := _finite_number(run["metrics"].get(metric))) is not None
            ]
            if not values:
                continue
            mean = sum(values) / len(values)
            mode_result[metric] = {
                "unit": metric_unit(metric),
                "values": values,
                "minimum": min(values),
                "maximum": max(values),
                "mean": mean,
                "relative_spread": (
                    (max(values) - min(values)) / abs(mean) if mean else 0.0
                ),
                "monotonic_increase": len(values) >= 3
                and all(left < right for left, right in pairwise(values)),
                "monotonic_decrease": len(values) >= 3
                and all(left > right for left, right in pairwise(values)),
            }
        result[mode] = mode_result
    return result


def metric_unit(name: str) -> str:
    if name.endswith("_milliseconds"):
        return "ms"
    if name.endswith("_bytes_per_second"):
        return "B/s"
    if name.endswith("_rate_hz"):
        return "Hz"
    if name.endswith("_bytes"):
        return "B"
    if name.endswith("_frames"):
        return "frames"
    return "count"


def identity_sets(runs: Iterable[dict[str, Any]]) -> dict[str, list[Any]]:
    fields = (
        "source_id",
        "build_id",
        "artifact_sha256",
        "protocol_version",
        "firmware_version",
    )
    values: dict[str, dict[str, Any]] = {name: {} for name in fields}
    for run in runs:
        if run["classification"] != CLASS_ACCEPTED:
            continue
        expected = run["identity"].get("expected")
        if not isinstance(expected, Mapping):
            continue
        for name in fields:
            value = expected.get(name)
            if isinstance(value, (str, int, list)):
                key = json.dumps(value, sort_keys=True, separators=(",", ":"))
                values[name][key] = value
    return {
        name: [items[key] for key in sorted(items)] for name, items in values.items()
    }


def _required_integer(
    value: Mapping[str, Any],
    name: str,
    owner: str,
    problems: list[str],
) -> int | None:
    result = _integer_or_none(value.get(name))
    if result is None:
        problems.append(f"{owner}.{name} is missing or not an integer")
    return result


def _required_number(
    value: Mapping[str, Any],
    name: str,
    owner: str,
    problems: list[str],
) -> float | None:
    result = _finite_number(value.get(name))
    if result is None:
        problems.append(f"{owner}.{name} is missing or not finite")
    return result


def _mapping_field(
    value: Mapping[str, Any],
    name: str,
    owner: str,
    problems: list[str],
) -> Mapping[str, Any] | None:
    result = value.get(name)
    if not isinstance(result, Mapping):
        problems.append(f"{owner}.{name} is missing or not an object")
        return None
    return result


def _conservation_problems(
    counters: Mapping[str, Any],
    *,
    owner: str,
    source: str,
    expected_pressure_loss: bool,
) -> list[str]:
    problems: list[str] = []
    values: dict[str, int] = {}

    def read(name: str) -> int | None:
        if name not in values:
            result = _required_integer(counters, name, owner, problems)
            if result is not None:
                values[name] = result
        return values.get(name)

    def read_optional(name: str) -> int | None:
        if name not in counters:
            return None
        return read(name)

    for name in REQUIRED_ZERO_ERROR_COUNTERS:
        current = read(name)
        if current not in {None, 0}:
            problems.append(f"{owner}.{name}={current}, expected zero")

    for prefix, items_per_frame, item_bytes in (
        ("adc", ADC_PAIRS_PER_FRAME, ADC_BYTES_PER_PAIR),
        ("gpio", GPIO_SAMPLES_PER_FRAME, 1),
    ):
        generated = read(f"{prefix}_frames_generated")
        framed = read(f"{prefix}_frames_framed_pipeline")
        emitted = read(f"{prefix}_frames_emitted")
        transmitted = read(f"{prefix}_frames_transmitted")
        dropped = read(f"{prefix}_frames_dropped")
        filling = read_optional(f"{prefix}_packet_filling_depth")
        ready = read_optional(f"{prefix}_packet_ready_depth")
        transmitting = read_optional(f"{prefix}_packet_transmit_depth")
        dropped_after_framing = read_optional(f"{prefix}_frames_dropped_after_framing")
        dropped_after_promotion = read_optional(
            f"{prefix}_frames_dropped_after_promotion"
        )
        stage_values = (
            generated,
            framed,
            emitted,
            transmitted,
            dropped,
        )
        if any(item is None for item in stage_values):
            continue
        assert generated is not None
        assert framed is not None
        assert emitted is not None
        assert transmitted is not None
        assert dropped is not None
        if not generated >= framed >= emitted >= transmitted:
            problems.append(f"{owner}.{prefix} frame stages are not conservative")
        if generated != transmitted + dropped:
            problems.append(f"{owner}.{prefix} produced-frame conservation failed")
        detailed_stages = (
            filling,
            ready,
            transmitting,
            dropped_after_framing,
            dropped_after_promotion,
        )
        if all(value is not None for value in detailed_stages):
            assert filling is not None
            assert ready is not None
            assert transmitting is not None
            assert dropped_after_framing is not None
            assert dropped_after_promotion is not None
            if (
                generated != transmitted + dropped + filling + ready + transmitting
                or framed != transmitted + ready + transmitting + dropped_after_framing
                or emitted != transmitted + transmitting + dropped_after_promotion
            ):
                problems.append(
                    f"{owner}.{prefix} detailed queue/drop conservation failed"
                )

        expected_items = {
            f"{prefix}_items_generated": generated * items_per_frame,
            f"{prefix}_items_framed_pipeline": framed * items_per_frame,
            f"{prefix}_items_emitted": emitted * items_per_frame,
            f"{prefix}_items_transmitted_pipeline": transmitted * items_per_frame,
        }
        for name, expected in expected_items.items():
            actual = read(name)
            if actual is not None and actual != expected:
                problems.append(f"{owner}.{name}={actual}, expected {expected}")

        tail = 0
        if source == "hardware":
            tail_name = (
                "adc_stop_pairs_discarded"
                if prefix == "adc"
                else "gpio_raw_samples_lost"
            )
            tail_value = read(tail_name)
            if tail_value is not None:
                tail = tail_value
                limit = 2 * items_per_frame if prefix == "adc" else items_per_frame
                if not 0 <= tail < limit:
                    problems.append(f"{owner}.{tail_name}={tail} is out of bounds")
        items_dropped = read(f"{prefix}_items_dropped")
        if (
            items_dropped is not None
            and items_dropped != dropped * items_per_frame + tail
        ):
            problems.append(f"{owner}.{prefix} dropped-item conservation failed")
        payload_dropped = read(f"{prefix}_payload_bytes_dropped")
        expected_payload_dropped = dropped * items_per_frame * item_bytes
        if payload_dropped is not None and payload_dropped != expected_payload_dropped:
            problems.append(f"{owner}.{prefix} dropped-byte conservation failed")

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
            actual = read(name)
            if actual is not None and actual != expected:
                problems.append(f"{owner}.{name}={actual}, expected {expected}")

    adc_payload = read("adc_payload_bytes_transmitted")
    gpio_payload = read("gpio_payload_bytes_transmitted")
    total_payload = read("data_payload_bytes_transmitted")
    if (
        adc_payload is not None
        and gpio_payload is not None
        and total_payload is not None
        and total_payload != adc_payload + gpio_payload
    ):
        problems.append(f"{owner}.data payload-byte conservation failed")
    adc_framed = read("adc_framed_bytes_transmitted")
    gpio_framed = read("gpio_framed_bytes_transmitted")
    total_framed = read("data_framed_bytes_transmitted")
    if (
        adc_framed is not None
        and gpio_framed is not None
        and total_framed is not None
        and total_framed != adc_framed + gpio_framed
    ):
        problems.append(f"{owner}.data framed-byte conservation failed")

    adc_dropped = read("adc_frames_dropped")
    gpio_dropped = read("gpio_frames_dropped")
    adc_evicted = read_optional("adc_frames_evicted")
    gpio_evicted = read_optional("gpio_frames_evicted")
    pressure = read_optional("packet_pressure_evictions")
    capacity = read_optional("packet_capacity_drops_without_evictable_frame")
    pool = read_optional("packet_pool_exhaustions")
    pressure_values = (
        adc_dropped,
        gpio_dropped,
        adc_evicted,
        gpio_evicted,
        pressure,
        capacity,
        pool,
    )
    if expected_pressure_loss and any(item is None for item in pressure_values):
        problems.append(f"{owner}.expected pressure-loss counters are missing")
    elif all(item is not None for item in pressure_values):
        assert adc_dropped is not None
        assert gpio_dropped is not None
        assert adc_evicted is not None
        assert gpio_evicted is not None
        assert pressure is not None
        assert capacity is not None
        assert pool is not None
        if pressure != adc_evicted + gpio_evicted:
            problems.append(f"{owner}.pressure-eviction conservation failed")
        if adc_dropped + gpio_dropped != pressure + capacity:
            problems.append(f"{owner}.shared drop conservation failed")
        if expected_pressure_loss:
            if pressure <= 0 or pool != pressure or capacity != 0:
                problems.append(f"{owner}.expected pressure loss did not reconcile")
        elif any(pressure_values):
            problems.append(f"{owner}.unexpected packet/drop counter is nonzero")
    return problems


def _run_release_evidence(
    record: JobRecord,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    categories: dict[str, list[str]] = {
        "duration_and_evidence": [],
        "rates": [],
        "latency": [],
        "resources": [],
        "conservation": [],
    }
    summary: dict[str, Any] = {
        "job_id": record.job_id,
        "mode": record.soak.get("mode") if record.soak else None,
        "epoch_count": None,
        "conserved_epoch_count": 0,
        "synthetic_formula_epoch_count": 0,
        "negative_subcase_count": 0,
    }
    soak = record.soak
    if not isinstance(soak, Mapping):
        categories["duration_and_evidence"].append("SOAK_RESULT is missing")
        return summary, categories
    mode = soak.get("mode")
    owner = f"job {record.job_id}"
    timing = _mapping_field(
        soak,
        "timing",
        owner,
        categories["duration_and_evidence"],
    )
    metrics = _mapping_field(
        soak,
        "metrics",
        owner,
        categories["duration_and_evidence"],
    )
    program = _mapping_field(
        soak,
        "program",
        owner,
        categories["duration_and_evidence"],
    )
    cleanup = _mapping_field(
        soak,
        "cleanup",
        owner,
        categories["duration_and_evidence"],
    )
    if cleanup is not None and cleanup.get("normal_close") is not True:
        categories["duration_and_evidence"].append(
            f"{owner}.cleanup.normal_close is not true"
        )
    if _aware_datetime(soak.get("completed_utc")) is None:
        categories["duration_and_evidence"].append(
            f"{owner}.completed_utc is missing or timezone-naive"
        )
    if program is not None:
        for name in ("sha256", "validator_sha256", "candidate_sha256"):
            value = program.get(name)
            if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
                categories["duration_and_evidence"].append(
                    f"{owner}.program.{name} is missing or malformed"
                )

    if timing is not None:
        nominal = _required_number(
            timing,
            "measured_duration_seconds",
            f"{owner}.timing",
            categories["duration_and_evidence"],
        )
        measured = _required_number(
            timing,
            "measured_elapsed_seconds",
            f"{owner}.timing",
            categories["duration_and_evidence"],
        )
        streaming = _required_number(
            timing,
            "streaming_elapsed_seconds",
            f"{owner}.timing",
            categories["duration_and_evidence"],
        )
        if nominal is not None and nominal != PHASE_11_MEASURED_DURATION_SECONDS:
            categories["duration_and_evidence"].append(
                f"{owner} nominal duration {nominal} is not 600 seconds"
            )
        if measured is not None and measured < PHASE_11_MEASURED_DURATION_SECONDS:
            categories["duration_and_evidence"].append(
                f"{owner} measured only {measured} seconds"
            )
        if streaming is not None and streaming <= 0:
            categories["duration_and_evidence"].append(
                f"{owner} streaming duration is not positive"
            )

    timed_totals = {
        "payload_bytes": 0,
        "framed_bytes": 0,
        "adc_pairs": 0,
        "gpio_samples": 0,
    }
    timed_seconds = 0.0
    epochs = soak.get("epochs")
    if not isinstance(epochs, list) or not epochs:
        categories["duration_and_evidence"].append(
            f"{owner}.epochs is missing or empty"
        )
        epochs = []
    elif any(not isinstance(epoch, Mapping) for epoch in epochs):
        categories["duration_and_evidence"].append(
            f"{owner}.epochs contains a non-object"
        )
        epochs = []
    summary["epoch_count"] = len(epochs)
    if mode in {"synthetic", "physical-combined"} and len(epochs) != 1:
        categories["duration_and_evidence"].append(
            f"{owner} continuous mode must contain exactly one epoch"
        )
    if mode == "control-stress" and len(epochs) < 2:
        categories["duration_and_evidence"].append(
            f"{owner} control-stress evidence must contain multiple epochs"
        )

    negative_evidence: list[Mapping[str, Any]] = []
    for index, raw_epoch in enumerate(epochs, start=1):
        assert isinstance(raw_epoch, Mapping)
        epoch_owner = f"{owner}.epochs[{index - 1}]"
        source = raw_epoch.get("source")
        expected_source = (
            "synthetic"
            if mode == "synthetic" or (mode == "control-stress" and index % 2 == 0)
            else "hardware"
        )
        if source != expected_source:
            categories["duration_and_evidence"].append(
                f"{epoch_owner}.source={source!r}, expected {expected_source!r}"
            )
        if raw_epoch.get("run_id") != index:
            categories["duration_and_evidence"].append(
                f"{epoch_owner}.run_id is not the sequential value {index}"
            )
        if raw_epoch.get("stats_generation") != 2 * index + 1:
            categories["duration_and_evidence"].append(
                f"{epoch_owner}.stats_generation is not {2 * index + 1}"
            )
        elapsed = _required_number(
            raw_epoch,
            "measured_elapsed_seconds",
            epoch_owner,
            categories["duration_and_evidence"],
        )
        if elapsed is not None:
            timed_seconds += elapsed
        parser = _mapping_field(
            raw_epoch,
            "parser",
            epoch_owner,
            categories["duration_and_evidence"],
        )
        if parser is not None:
            for name in ("errors", "bytes_discarded", "buffered_bytes"):
                value = _required_integer(
                    parser,
                    name,
                    f"{epoch_owner}.parser",
                    categories["duration_and_evidence"],
                )
                if value not in {None, 0}:
                    categories["conservation"].append(
                        f"{epoch_owner}.parser.{name}={value}, expected zero"
                    )
        timed = _mapping_field(
            raw_epoch,
            "timed",
            epoch_owner,
            categories["duration_and_evidence"],
        )
        if timed is not None:
            adc_frames = _required_integer(
                timed,
                "adc_frames",
                f"{epoch_owner}.timed",
                categories["duration_and_evidence"],
            )
            gpio_frames = _required_integer(
                timed,
                "gpio_frames",
                f"{epoch_owner}.timed",
                categories["duration_and_evidence"],
            )
            adc_pairs = _required_integer(
                timed,
                "adc_pairs",
                f"{epoch_owner}.timed",
                categories["duration_and_evidence"],
            )
            gpio_samples = _required_integer(
                timed,
                "gpio_samples",
                f"{epoch_owner}.timed",
                categories["duration_and_evidence"],
            )
            payload = _required_integer(
                timed,
                "payload_bytes",
                f"{epoch_owner}.timed",
                categories["duration_and_evidence"],
            )
            framed = _required_integer(
                timed,
                "framed_bytes",
                f"{epoch_owner}.timed",
                categories["duration_and_evidence"],
            )
            if all(
                value is not None
                for value in (
                    adc_frames,
                    gpio_frames,
                    adc_pairs,
                    gpio_samples,
                    payload,
                    framed,
                )
            ):
                assert adc_frames is not None
                assert gpio_frames is not None
                assert adc_pairs is not None
                assert gpio_samples is not None
                assert payload is not None
                assert framed is not None
                if adc_pairs != adc_frames * ADC_PAIRS_PER_FRAME:
                    categories["conservation"].append(
                        f"{epoch_owner} timed ADC frame/item equation failed"
                    )
                if gpio_samples != gpio_frames * GPIO_SAMPLES_PER_FRAME:
                    categories["conservation"].append(
                        f"{epoch_owner} timed GPIO frame/item equation failed"
                    )
                if payload != adc_pairs * ADC_BYTES_PER_PAIR + gpio_samples:
                    categories["conservation"].append(
                        f"{epoch_owner} timed payload-byte equation failed"
                    )
                if framed != (adc_frames + gpio_frames) * DATA_FRAME_BYTES:
                    categories["conservation"].append(
                        f"{epoch_owner} timed framed-byte equation failed"
                    )
                timed_totals["adc_pairs"] += adc_pairs
                timed_totals["gpio_samples"] += gpio_samples
                timed_totals["payload_bytes"] += payload
                timed_totals["framed_bytes"] += framed

        negative = raw_epoch.get("expected_negative_subcase")
        expected_pressure_loss = isinstance(negative, Mapping)
        if expected_pressure_loss:
            assert isinstance(negative, Mapping)
            negative_evidence.append(negative)
            if (
                negative.get("name") != "serial_read_stall_pressure"
                or negative.get("result") != "PASS"
                or negative.get("final_state") != "IDLE"
            ):
                categories["conservation"].append(
                    f"{epoch_owner} named pressure-loss evidence is invalid"
                )
            loss = negative.get("loss")
            if not isinstance(loss, Mapping):
                categories["conservation"].append(
                    f"{epoch_owner} pressure-loss counters are missing"
                )
            elif timed is not None:
                for prefix in ("adc", "gpio"):
                    missing = timed.get(f"{prefix}_missing_frames")
                    lost = loss.get(f"{prefix}_frames")
                    if not isinstance(missing, int) or missing != lost or missing <= 0:
                        categories["conservation"].append(
                            f"{epoch_owner} {prefix} named loss does not match gaps"
                        )
                pressure = loss.get("packet_pressure_evictions")
                adc_loss = loss.get("adc_frames")
                gpio_loss = loss.get("gpio_frames")
                if (
                    not isinstance(pressure, int)
                    or not isinstance(adc_loss, int)
                    or not isinstance(gpio_loss, int)
                    or pressure != adc_loss + gpio_loss
                    or loss.get("packet_pool_exhaustions") != pressure
                    or loss.get("packet_capacity_drops_without_evictable_frame") != 0
                ):
                    categories["conservation"].append(
                        f"{epoch_owner} named shared pressure loss does not reconcile"
                    )
        elif timed is not None:
            for prefix in ("adc", "gpio"):
                missing = timed.get(f"{prefix}_missing_frames", 0)
                if missing != 0:
                    categories["conservation"].append(
                        f"{epoch_owner} has unexpected {prefix} frame loss"
                    )

        fixture = raw_epoch.get("fixture_scope")
        if source == "synthetic":
            if not isinstance(fixture, Mapping) or (
                fixture.get("synthetic_formulas") != "all-payload-items"
            ):
                categories["duration_and_evidence"].append(
                    f"{epoch_owner} lacks all-item synthetic formula evidence"
                )
            else:
                summary["synthetic_formula_epoch_count"] += 1
        status = _mapping_field(
            raw_epoch,
            "status",
            epoch_owner,
            categories["duration_and_evidence"],
        )
        counters = (
            _mapping_field(
                status,
                "final_counters",
                f"{epoch_owner}.status",
                categories["duration_and_evidence"],
            )
            if status is not None
            else None
        )
        if counters is not None:
            if counters.get("device_state") != 1:
                categories["conservation"].append(
                    f"{epoch_owner} did not finish in IDLE"
                )
            conservation = _conservation_problems(
                counters,
                owner=f"{epoch_owner}.status.final_counters",
                source=str(source),
                expected_pressure_loss=expected_pressure_loss,
            )
            categories["conservation"].extend(conservation)
            if not conservation:
                summary["conserved_epoch_count"] += 1

    summary["negative_subcase_count"] = len(negative_evidence)
    root_negative = soak.get("negative_subcases", [])
    if mode == "control-stress":
        if (
            not isinstance(root_negative, list)
            or len(root_negative) != 1
            or len(negative_evidence) != 1
            or root_negative != negative_evidence
        ):
            categories["conservation"].append(
                f"{owner} must contain exactly one matching named negative subcase"
            )
    elif negative_evidence or root_negative not in (None, []):
        categories["conservation"].append(
            f"{owner} non-control mode contains negative-loss evidence"
        )

    if metrics is not None:
        epoch_count = _required_integer(
            metrics,
            "epoch_count",
            f"{owner}.metrics",
            categories["duration_and_evidence"],
        )
        if epoch_count is not None and epoch_count != len(epochs):
            categories["duration_and_evidence"].append(
                f"{owner}.metrics.epoch_count does not match epochs"
            )
        for name, expected in timed_totals.items():
            actual = _required_integer(
                metrics,
                name,
                f"{owner}.metrics",
                categories["duration_and_evidence"],
            )
            if actual is not None and actual != expected:
                categories["conservation"].append(
                    f"{owner}.metrics.{name} does not equal timed epoch total"
                )
        rate_targets = {
            "payload_bytes_per_streaming_second": TARGET_PAYLOAD_BYTES_PER_SECOND,
            "framed_bytes_per_streaming_second": TARGET_FRAMED_BYTES_PER_SECOND,
            "adc_pair_rate_hz": TARGET_ADC_PAIR_RATE_HZ,
            "gpio_sample_rate_hz": TARGET_GPIO_SAMPLE_RATE_HZ,
        }
        for name, target in rate_targets.items():
            actual_rate = _required_number(
                metrics,
                name,
                f"{owner}.metrics",
                categories["rates"],
            )
            if (
                actual_rate is not None
                and abs(actual_rate - target) / target
                > PHASE_11_RATE_TOLERANCE_FRACTION
            ):
                categories["rates"].append(
                    f"{owner}.metrics.{name}={actual_rate} is outside {target} +/-1%"
                )
        if timing is not None:
            streaming = _finite_number(timing.get("streaming_elapsed_seconds"))
            if streaming is not None and not math.isclose(
                streaming, timed_seconds, rel_tol=1e-9, abs_tol=1e-6
            ):
                categories["conservation"].append(
                    f"{owner} streaming duration does not equal epoch durations"
                )

        latency = _mapping_field(
            metrics,
            "latency",
            f"{owner}.metrics",
            categories["latency"],
        )
        if latency is not None:
            status_latency = _mapping_field(
                latency,
                "status",
                f"{owner}.metrics.latency",
                categories["latency"],
            )
            commands = _mapping_field(
                latency,
                "all_commands",
                f"{owner}.metrics.latency",
                categories["latency"],
            )
            if status_latency is not None:
                p99 = _required_number(
                    status_latency,
                    "p99_seconds",
                    f"{owner}.metrics.latency.status",
                    categories["latency"],
                )
                maximum = _required_number(
                    status_latency,
                    "maximum_seconds",
                    f"{owner}.metrics.latency.status",
                    categories["latency"],
                )
                if p99 is not None and p99 * 1_000 > (
                    PHASE_04_STATUS_P99_LIMIT_MILLISECONDS
                ):
                    categories["latency"].append(
                        f"{owner} STATUS p99 exceeds the Phase 04 limit"
                    )
                if maximum is not None and maximum * 1_000 > (
                    PHASE_04_STATUS_MAXIMUM_LIMIT_MILLISECONDS
                ):
                    categories["latency"].append(
                        f"{owner} STATUS maximum exceeds the Phase 04 limit"
                    )
            if commands is not None:
                maximum = _required_number(
                    commands,
                    "maximum_seconds",
                    f"{owner}.metrics.latency.all_commands",
                    categories["latency"],
                )
                if maximum is not None and maximum * 1_000 > (
                    PHASE_04_COMMAND_MAXIMUM_LIMIT_MILLISECONDS
                ):
                    categories["latency"].append(
                        f"{owner} command maximum exceeds the Phase 04 limit"
                    )

        memory = _mapping_field(
            metrics,
            "memory",
            f"{owner}.metrics",
            categories["resources"],
        )
        if memory is not None:
            traced = nested(memory, "tracemalloc", "growth_bytes")
            rss = nested(memory, "process_rss", "growth_bytes")
            available = memory.get("minimum_available_bytes")
            if not isinstance(traced, int):
                categories["resources"].append(
                    f"{owner} tracemalloc growth evidence is missing"
                )
            elif traced > MAX_TRACED_GROWTH_BYTES:
                categories["resources"].append(
                    f"{owner} tracemalloc growth exceeds its bound"
                )
            if not isinstance(rss, int):
                categories["resources"].append(
                    f"{owner} RSS growth evidence is missing"
                )
            elif rss > MAX_RSS_GROWTH_BYTES:
                categories["resources"].append(f"{owner} RSS growth exceeds its bound")
            if not isinstance(available, int) or available <= 0:
                categories["resources"].append(
                    f"{owner} available-memory evidence is missing"
                )
        queues = _mapping_field(
            metrics,
            "maximum_queues",
            f"{owner}.metrics",
            categories["resources"],
        )
        if queues is not None:
            for name, limit in (
                ("packet_owned_high_water", 200),
                ("packet_ready_high_water", 200),
                ("packet_transmit_high_water", 200),
            ):
                value = _required_integer(
                    queues,
                    name,
                    f"{owner}.metrics.maximum_queues",
                    categories["resources"],
                )
                if value is not None and not 0 <= value <= limit:
                    categories["resources"].append(
                        f"{owner} queue {name}={value} exceeds {limit}"
                    )
    return summary, categories


def aggregate(records: list[JobRecord]) -> dict[str, Any]:
    runs = [record_summary(record) for record in records]
    runs.sort(
        key=lambda run: (
            _aware_datetime(run["job_metadata"].get("client_started_utc")) is None,
            run["job_metadata"].get("client_started_utc") or "",
            run["job_id"],
        )
    )
    sequential = apply_sequential_checks(runs)
    counts = Counter(run["classification"] for run in runs)
    mode_counts = Counter(
        run["mode"]
        for run in runs
        if run["classification"] == CLASS_ACCEPTED and run["mode"] is not None
    )
    identities = identity_sets(runs)
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "run_count": len(runs),
        "classification_counts": dict(sorted(counts.items())),
        "accepted_mode_counts": dict(sorted(mode_counts.items())),
        "accepted_jobs_are_sequential": sequential,
        "accepted_identity_sets": identities,
        "accepted_identity_is_uniform": all(
            len(values) <= 1 for values in identities.values()
        ),
        "trends": trend_summary(runs),
        "runs": runs,
    }


def load_campaign_indexes(paths: Iterable[Path]) -> list[tuple[str, dict[str, Any]]]:
    """Load explicit accepted/excluded campaign lineage without guessing."""

    result: list[tuple[str, dict[str, Any]]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AggregateError(
                f"could not load campaign index {path}: {error}"
            ) from error
        result.append((str(path), _json_object(value, str(path))))
    return result


def evaluate_phase_11_release(
    records: list[JobRecord],
    aggregate_result: Mapping[str, Any],
    campaign_indexes: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Apply the complete Phase 11 cross-run acceptance policy fail closed."""

    categories: dict[str, list[str]] = {
        "records": [],
        "identity": [],
        "duration_and_evidence": [],
        "rates": [],
        "latency": [],
        "resources": [],
        "conservation": [],
        "campaign_indexes": [],
    }
    run_summaries: list[dict[str, Any]] = []
    classifications = aggregate_result.get("classification_counts")
    if classifications != {CLASS_ACCEPTED: len(records)}:
        categories["records"].append(
            "every release-gate input must classify as accepted"
        )
    mode_counts = aggregate_result.get("accepted_mode_counts")
    if not isinstance(mode_counts, Mapping):
        categories["records"].append("accepted mode counts are missing")
        mode_counts = {}
    for mode, required in PHASE_11_REQUIRED_MODE_COUNTS.items():
        actual = mode_counts.get(mode)
        if not isinstance(actual, int) or actual < required:
            categories["records"].append(
                f"{mode} has {actual!r} accepted jobs; at least {required} are required"
            )
    if aggregate_result.get("accepted_jobs_are_sequential") is not True:
        categories["records"].append("accepted jobs overlap or have invalid timestamps")
    identity_values = aggregate_result.get("accepted_identity_sets")
    if not isinstance(identity_values, Mapping):
        categories["identity"].append("accepted identity sets are missing")
        identity_values = {}
    for name in (
        "source_id",
        "build_id",
        "artifact_sha256",
        "protocol_version",
        "firmware_version",
    ):
        values = identity_values.get(name)
        if not isinstance(values, list) or len(values) != 1:
            categories["identity"].append(
                f"accepted {name} must contain exactly one value, found {values!r}"
            )

    program_sets: dict[str, set[str]] = defaultdict(set)
    accepted_ids: set[str] = set()
    for record in records:
        classification = classify(record)[0]
        if classification == CLASS_ACCEPTED:
            accepted_ids.add(record.job_id)
        summary, run_categories = _run_release_evidence(record)
        run_summaries.append(summary)
        for name, problems in run_categories.items():
            categories[name].extend(problems)
        if record.soak is not None:
            record_mode = record.soak.get("mode")
            program_sha256 = nested(record.soak, "program", "sha256")
            if isinstance(record_mode, str) and isinstance(program_sha256, str):
                program_sets[record_mode].add(program_sha256)
    for mode, expected_count in PHASE_11_REQUIRED_MODE_COUNTS.items():
        values = program_sets.get(mode, set())
        if mode_counts.get(mode, 0) >= expected_count and len(values) != 1:
            categories["identity"].append(
                f"accepted {mode} program SHA-256 must be uniform"
            )

    trends = aggregate_result.get("trends")
    if not isinstance(trends, Mapping):
        categories["rates"].append("cross-run trends are missing")
        trends = {}
    for mode, count in mode_counts.items():
        if not isinstance(mode, str) or not isinstance(count, int):
            continue
        mode_trends = trends.get(mode)
        if not isinstance(mode_trends, Mapping):
            categories["rates"].append(f"{mode} cross-run trends are missing")
            continue
        for metric in (
            "payload_bytes_per_second",
            "framed_bytes_per_second",
            "adc_pair_rate_hz",
            "gpio_sample_rate_hz",
        ):
            trend = mode_trends.get(metric)
            if not isinstance(trend, Mapping):
                categories["rates"].append(f"{mode} {metric} trend is missing")
                continue
            values = trend.get("values")
            spread = _finite_number(trend.get("relative_spread"))
            if not isinstance(values, list) or len(values) != count:
                categories["rates"].append(
                    f"{mode} {metric} trend does not contain every accepted run"
                )
            if spread is None or spread > PHASE_11_RATE_TOLERANCE_FRACTION:
                categories["rates"].append(
                    f"{mode} {metric} relative spread exceeds 1%"
                )
        for metric in (
            "traced_growth_bytes",
            "rss_growth_bytes",
            "packet_owned_high_water_frames",
        ):
            trend = mode_trends.get(metric)
            if not isinstance(trend, Mapping):
                categories["resources"].append(f"{mode} {metric} trend is missing")
            elif trend.get("monotonic_increase") is True:
                categories["resources"].append(
                    f"{mode} {metric} worsens monotonically across three or more runs"
                )

    expected_campaigns = {
        "phase-11-synthetic",
        "phase-11-physical-combined",
        "phase-11-control-stress",
    }
    seen_campaigns: set[str] = set()
    indexed_accepted: set[str] = set()
    excluded: list[dict[str, Any]] = []
    infrastructure: list[dict[str, Any]] = []

    def validate_lineage_record(
        raw: object,
        *,
        owner: str,
        infrastructure_record: bool,
    ) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            categories["campaign_indexes"].append(f"{owner} is not an object")
            return None
        result = dict(raw)
        required = ("job_id", "classification", "reason", "bundle")
        for name in required:
            value = result.get(name)
            if not isinstance(value, str) or not value:
                categories["campaign_indexes"].append(
                    f"{owner}.{name} is missing or empty"
                )
        bundle = result.get("bundle")
        if isinstance(bundle, str) and bundle and not Path(bundle).is_file():
            categories["campaign_indexes"].append(
                f"{owner}.bundle does not exist: {bundle}"
            )
        classification = result.get("classification")
        if infrastructure_record and classification not in {
            CLASS_UPLOAD_FAILURE,
            CLASS_SERVICE_FAILURE,
        }:
            categories["campaign_indexes"].append(
                f"{owner}.classification is not an infrastructure class"
            )
        return result

    for path, index in campaign_indexes:
        owner = f"campaign index {path}"
        if index.get("schema_version") != 1:
            categories["campaign_indexes"].append(f"{owner}.schema_version must be 1")
        campaign = index.get("campaign")
        if not isinstance(campaign, str) or campaign not in expected_campaigns:
            categories["campaign_indexes"].append(
                f"{owner}.campaign is missing or unexpected"
            )
        elif campaign in seen_campaigns:
            categories["campaign_indexes"].append(
                f"campaign {campaign} appears more than once"
            )
        else:
            seen_campaigns.add(campaign)
        raw_accepted = index.get("accepted")
        if not isinstance(raw_accepted, list):
            categories["campaign_indexes"].append(f"{owner}.accepted is not a list")
        else:
            for item_index, raw in enumerate(raw_accepted):
                item_owner = f"{owner}.accepted[{item_index}]"
                if not isinstance(raw, Mapping):
                    categories["campaign_indexes"].append(
                        f"{item_owner} is not an object"
                    )
                    continue
                job_id = raw.get("job_id")
                bundle = raw.get("bundle")
                if not isinstance(job_id, str) or not job_id:
                    categories["campaign_indexes"].append(
                        f"{item_owner}.job_id is missing"
                    )
                else:
                    if job_id in indexed_accepted:
                        categories["campaign_indexes"].append(
                            f"accepted job {job_id} appears more than once"
                        )
                    indexed_accepted.add(job_id)
                if not isinstance(bundle, str) or not bundle:
                    categories["campaign_indexes"].append(
                        f"{item_owner}.bundle is missing"
                    )
                elif not Path(bundle).is_file():
                    categories["campaign_indexes"].append(
                        f"{item_owner}.bundle does not exist: {bundle}"
                    )
        raw_excluded = index.get("excluded")
        if not isinstance(raw_excluded, list):
            categories["campaign_indexes"].append(f"{owner}.excluded is not a list")
        else:
            for item_index, raw in enumerate(raw_excluded):
                result = validate_lineage_record(
                    raw,
                    owner=f"{owner}.excluded[{item_index}]",
                    infrastructure_record=False,
                )
                if result is not None:
                    result["campaign"] = campaign
                    excluded.append(result)
        if "infrastructure_incidents" not in index:
            categories["campaign_indexes"].append(
                f"{owner}.infrastructure_incidents is absent"
            )
        raw_infrastructure = index.get("infrastructure_incidents")
        if not isinstance(raw_infrastructure, list):
            categories["campaign_indexes"].append(
                f"{owner}.infrastructure_incidents is not a list"
            )
        else:
            for item_index, raw in enumerate(raw_infrastructure):
                result = validate_lineage_record(
                    raw,
                    owner=f"{owner}.infrastructure_incidents[{item_index}]",
                    infrastructure_record=True,
                )
                if result is not None:
                    result["campaign"] = campaign
                    infrastructure.append(result)

    if seen_campaigns != expected_campaigns:
        missing = sorted(expected_campaigns - seen_campaigns)
        categories["campaign_indexes"].append(
            f"required campaign indexes are missing: {missing}"
        )
    if indexed_accepted != accepted_ids:
        categories["campaign_indexes"].append(
            "campaign-index accepted job IDs do not exactly match aggregate inputs"
        )
    excluded_ids = {
        item.get("job_id")
        for item in [*excluded, *infrastructure]
        if isinstance(item.get("job_id"), str)
    }
    overlap = sorted(accepted_ids & excluded_ids)
    if overlap:
        categories["campaign_indexes"].append(
            f"jobs appear in both accepted and excluded lineage: {overlap}"
        )

    checks = {name: not problems for name, problems in categories.items()}
    problems = [
        f"{name}: {problem}"
        for name, category_problems in categories.items()
        for problem in category_problems
    ]
    return {
        "policy": "phase-11-release-v1",
        "result": "PASS" if not problems else "FAIL",
        "checks": checks,
        "problems": problems,
        "limits": {
            "required_mode_counts": PHASE_11_REQUIRED_MODE_COUNTS,
            "measured_duration_seconds": PHASE_11_MEASURED_DURATION_SECONDS,
            "rate_tolerance_fraction": PHASE_11_RATE_TOLERANCE_FRACTION,
            "status_p99_milliseconds": PHASE_04_STATUS_P99_LIMIT_MILLISECONDS,
            "status_maximum_milliseconds": (PHASE_04_STATUS_MAXIMUM_LIMIT_MILLISECONDS),
            "command_maximum_milliseconds": (
                PHASE_04_COMMAND_MAXIMUM_LIMIT_MILLISECONDS
            ),
            "rss_growth_bytes": MAX_RSS_GROWTH_BYTES,
            "traced_growth_bytes": MAX_TRACED_GROWTH_BYTES,
        },
        "accepted_program_sha256_sets": {
            mode: sorted(values) for mode, values in sorted(program_sets.items())
        },
        "run_evidence": run_summaries,
        "campaign_indexes": [path for path, _index in campaign_indexes],
        "excluded_jobs": sorted(excluded, key=lambda item: str(item.get("job_id"))),
        "infrastructure_incidents": sorted(
            infrastructure, key=lambda item: str(item.get("job_id"))
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, help="also write aggregate JSON here")
    parser.add_argument("--pretty", action="store_true", help="indent stdout JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 unless every input classifies as accepted",
    )
    parser.add_argument(
        "--phase-11-release",
        action="store_true",
        help="apply the complete six-job Phase 11 release gate",
    )
    parser.add_argument(
        "--campaign-index",
        action="append",
        default=[],
        type=Path,
        help="accepted/excluded campaign index (repeat for each soak mode)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fragments = [fragment for path in args.inputs for fragment in parse_path(path)]
        records = group_fragments(fragments)
        aggregate_result = aggregate(records)
        if args.phase_11_release:
            indexes = load_campaign_indexes(args.campaign_index)
            aggregate_result["release_gate"] = evaluate_phase_11_release(
                records,
                aggregate_result,
                indexes,
            )
    except AggregateError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    encoded = json.dumps(
        aggregate_result,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    )
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.strict and aggregate_result["classification_counts"] != {
        CLASS_ACCEPTED: aggregate_result["run_count"]
    }:
        return 1
    if args.phase_11_release and aggregate_result["release_gate"]["result"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
