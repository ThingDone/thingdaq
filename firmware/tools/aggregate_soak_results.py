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
                "monotonic_increase": len(values) >= 2
                and all(left < right for left, right in pairwise(values)),
                "monotonic_decrease": len(values) >= 2
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
    fields = ("source_id", "build_id", "artifact_sha256", "protocol_version")
    values: dict[str, set[Any]] = {name: set() for name in fields}
    for run in runs:
        if run["classification"] != CLASS_ACCEPTED:
            continue
        expected = run["identity"].get("expected")
        if not isinstance(expected, Mapping):
            continue
        for name in fields:
            value = expected.get(name)
            if isinstance(value, (str, int)):
                values[name].add(value)
    return {name: sorted(items, key=str) for name, items in values.items()}


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fragments = [fragment for path in args.inputs for fragment in parse_path(path)]
        aggregate_result = aggregate(group_fragments(fragments))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
