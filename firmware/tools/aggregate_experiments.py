#!/usr/bin/env python3
"""Aggregate immutable experiment evidence without checking out candidate code."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

try:
    from firmware.tools import experiment_evidence as evidence
except (
    ModuleNotFoundError
):  # Direct execution: python3 firmware/tools/aggregate_experiments.py
    import experiment_evidence as evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_PATH = "experiments/experiment-matrix.json"
DEFAULT_JSON_OUTPUT = "doc/results/experiments/clock-compression-io-report.json"
DEFAULT_MARKDOWN_OUTPUT = "doc/results/experiments/clock-compression-io-report.md"
DEFAULT_CREATED = "2026-09-04"
AGGREGATE_SCHEMA_VERSION = 1

BASELINE_COMMIT = "b23004defeca465da0ae2d2884c4fef71979e5d4"
CLOCK_HEAD_COMMIT = "2d2977af937f3d689ce6e47a8e44c6e0a2df5440"
CLOCK_SOURCE_COMMIT = "6b3ae88f5f5c2f27e49311084ec02ec85b9707f6"
CLOCK_SERVICE_SHA256 = (
    "21a4566ae18edd888772c5243cb722ee14311037f58446edf8aa7e2549ed619d"
)
CLOCK_SUMMARY_SHA256 = (
    "55491e1d05084a32b72a821a728e014ac21861a1d180dfbc28a6a3d10fcbaee8"
)
CLOCK_ADR_SHA256 = "b0714310b724df23a2bd662f1d8839539d3117e5bf7ac73f1aaefa25655837ce"
CLOCK_JOB_ID = "fe5bb7ba-7469-4fd2-bce3-62f7a43c9de4"
CLOCK_BUILD_ID = "thingdaq-2dbd6a60fe4409cd"
CLOCK_SOURCE_ID = "4e3b4a2ff9376c0dca4f0781dfbfdc58b265e743ed7c30dc71cd6d74f8b400da"
CLOCK_HEX_SHA256 = "11d3b89666d83245b78fbb5e1a52a918c828fd9e859cd6f70a005d610dbb1651"

DEFAULT_CLOCK_SERVICE_PATH = (
    ".maestro/playbooks/2026-09-01-Teensydaq/Working/"
    "clock-450mhz-physical-campaign-00001/smoke-450-attempt2-service-result.json"
)
DEFAULT_CLOCK_SUMMARY_PATH = (
    ".maestro/playbooks/2026-09-01-Teensydaq/Working/"
    "clock-450mhz-physical-campaign-00001/result-summary.md"
)
DEFAULT_CLOCK_ADR_PATH = "doc/decisions/adr-005-experimental-clock-profiles.md"

RELATED_LINKS = (
    "[[Experiment-Baseline]]",
    "[[Evidence-Index]]",
    "[[Protocol-V1]]",
    "[[Acquisition-Pipeline]]",
    "[[Firmware-Resource-Map]]",
    "[[Hardware-Safety]]",
    "[[1-MHz-Parallel-Output-Idea]]",
)


class AggregationError(Exception):
    """An input or conclusion violates the aggregate evidence contract."""


@dataclass(frozen=True, slots=True)
class InputSpec:
    """One canonical report read from one explicit Git revision."""

    experiment_id: str
    role: str
    revision: str
    report_path: str
    expected_commit: str | None = None


DEFAULT_INPUTS = (
    InputSpec(
        "baseline",
        "baseline",
        "origin/experiment/baseline-2026-09-01",
        "doc/results/experiments/baseline.json",
        BASELINE_COMMIT,
    ),
    InputSpec(
        "rle-streaming",
        "candidate",
        "origin/experiment/rle-streaming",
        "doc/results/experiments/rle-streaming.json",
        "2bf5a24b2ac6271fe24e3f9b3890edb6c150f3fb",
    ),
    InputSpec(
        "aux-input-bank",
        "candidate",
        "origin/experiment/aux-input-bank",
        "doc/results/experiments/aux-input-bank.json",
        "c7ecb9a7aeed1291be8f3e50d496246e149e781c",
    ),
    InputSpec(
        "aux-output-bank",
        "candidate",
        "origin/experiment/aux-output-bank",
        "doc/results/experiments/aux-output-bank.json",
        "03cc2ec9f8405345add9919097448283703fd0a3",
    ),
)
INPUT_ORDER = {
    "baseline": 0,
    "rle-streaming": 1,
    "aux-input-bank": 2,
    "aux-output-bank": 3,
}

CLOCK_ADR_ASSERTIONS = (
    ("baseline_commit", BASELINE_COMMIT),
    ("clock_source_commit", CLOCK_SOURCE_COMMIT),
    ("build_id", CLOCK_BUILD_ID),
    ("source_id", CLOCK_SOURCE_ID),
    ("hex_sha256", CLOCK_HEX_SHA256),
    ("job_id", CLOCK_JOB_ID),
    ("clock_tree", "450/150/37.5/24 MHz"),
    ("adc_resolution", "12-bit"),
    ("completion_counts", "`[8, 8]`"),
    ("completion_timing", "222-DWT-cycle median"),
    ("validation_count", "all 404 checks"),
    ("capture_duration", "10.003074 seconds"),
    ("adc_rate", "999,852.20"),
    ("gpio_rate", "3,999,004.12"),
    ("payload_rate", "7,998,412.92"),
    ("acquisition_utilization", "74.14% median and 74.18%"),
    ("usb_utilization", "11.43% median and 11.49%"),
    ("packet_high_water", "20 of 200 buffers"),
    ("stop_tail", "733 ADC pairs and 2,935 GPIO samples"),
    (
        "claim_scope",
        "not analog accuracy, endurance, power, thermal benefit, or lifetime",
    ),
)

CLOCK_ZERO_ERROR_FIELDS = (
    "adc_destination_mismatches",
    "adc_dma_error_events",
    "adc_etc_error_events",
    "adc_etc_error_flags",
    "adc_frames_dropped",
    "adc_frames_dropped_after_framing",
    "adc_frames_dropped_after_promotion",
    "adc_frames_evicted",
    "adc_frames_evicted_after_promotion",
    "adc_overwritten_conversions",
    "adc_packer_chronology_errors",
    "adc_packer_pipeline_errors",
    "adc_packer_source_errors",
    "adc_payload_bytes_dropped",
    "adc_raw_drop_pairs_projected",
    "adc_raw_gap_pairs",
    "adc_raw_invariant_errors",
    "adc_raw_ring_overruns",
    "adc_resource_conflicts",
    "adc_schedule_exhaustions",
    "adc_stale_completions",
    "adc_stale_interrupts",
    "adc_start_errors",
    "adc_stop_errors",
    "bad_checksums",
    "bad_flags",
    "bad_lengths",
    "bad_payloads",
    "bad_request_ids",
    "bad_types",
    "bad_versions",
    "clock_health_error_flags",
    "clock_mismatch_count",
    "commands_rejected",
    "gpio_duplicate_samples_ignored",
    "gpio_frames_dropped",
    "gpio_frames_dropped_after_framing",
    "gpio_frames_dropped_after_promotion",
    "gpio_frames_evicted",
    "gpio_frames_evicted_after_promotion",
    "gpio_hardware_errors",
    "gpio_packer_chronology_errors",
    "gpio_packer_drop_samples_projected",
    "gpio_packer_pipeline_errors",
    "gpio_packer_samples_dropped",
    "gpio_packer_source_errors",
    "gpio_payload_bytes_dropped",
    "gpio_raw_drop_samples_projected",
    "gpio_raw_invariant_errors",
    "gpio_raw_ring_overruns",
    "gpio_resource_conflicts",
    "gpio_stale_dma_completions",
    "gpio_start_errors",
    "gpio_stop_errors",
    "health_adc_hardware_error_count",
    "health_adc_trigger_error_count",
    "packet_capacity_drops_without_evictable_frame",
    "packet_encoding_rejections",
    "packet_invalid_operations",
    "packet_pool_exhaustions",
    "packet_pressure_evictions",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
    "parser_errors",
    "response_queue_rejections",
    "response_reservations_abandoned",
    "service_counter_error_count",
    "state_errors",
    "timeouts",
    "transport_errors",
    "usb_io_errors",
)


def _fail(message: str) -> NoReturn:
    raise AggregationError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_git(root: Path, arguments: Sequence[str], *, text: bool = True) -> Any:
    command = ["git", "-C", str(root), *arguments]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=text,
        )
    except OSError as error:
        raise AggregationError(f"could not run git: {error}") from error
    if completed.returncode != 0:
        stderr = (
            completed.stderr.strip()
            if text
            else completed.stderr.decode(errors="replace").strip()
        )
        _fail(f"git {' '.join(arguments)} failed: {stderr or 'no diagnostic'}")
    return completed.stdout


def _resolve_commit(root: Path, revision: str) -> str:
    value = str(
        _run_git(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"])
    ).strip()
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        _fail(f"revision did not resolve to a full lowercase commit: {revision!r}")
    return value


def _tree(root: Path, commit: str) -> str:
    return str(_run_git(root, ["rev-parse", "--verify", f"{commit}^{{tree}}"])).strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        _fail(completed.stderr.strip() or "git merge-base failed")
    return completed.returncode == 0


def _git_blob(root: Path, commit: str, path: str) -> bytes:
    try:
        relative = evidence.validate_repository_relative_path(path, "Git blob path")
    except evidence.EvidenceError as error:
        raise AggregationError(str(error)) from error
    return bytes(
        _run_git(root, ["cat-file", "blob", f"{commit}:{relative}"], text=False)
    )


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda token: _fail(f"{label}: non-finite {token}"),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise AggregationError(f"{label}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        _fail(f"{label}: must contain one JSON object")
    return value


def _require_mapping(
    owner: Mapping[str, Any], key: str, location: str
) -> dict[str, Any]:
    value = owner.get(key)
    if not isinstance(value, dict):
        _fail(f"{location}.{key}: must be an object")
    return value


def _require_list(owner: Mapping[str, Any], key: str, location: str) -> list[Any]:
    value = owner.get(key)
    if not isinstance(value, list):
        _fail(f"{location}.{key}: must be an array")
    return value


def _require_number(value: Any, location: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _fail(f"{location}: must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        _fail(f"{location}: must be finite")
    return value


def _require_equal(actual: Any, expected: Any, location: str) -> None:
    if actual != expected:
        _fail(f"{location}: expected {expected!r}, observed {actual!r}")


def _local_file(root: Path, relative: str) -> Path:
    try:
        normalized = evidence.validate_repository_relative_path(
            relative, "local evidence path"
        )
    except evidence.EvidenceError as error:
        raise AggregationError(str(error)) from error
    selected = (root / normalized).resolve()
    try:
        selected.relative_to(root.resolve())
    except ValueError as error:
        raise AggregationError(
            f"local evidence path escapes repository: {relative}"
        ) from error
    return selected


def _read_hashed_local(root: Path, relative: str, expected_sha256: str) -> bytes:
    selected = _local_file(root, relative)
    try:
        data = selected.read_bytes()
    except OSError as error:
        raise AggregationError(f"could not read {relative}: {error}") from error
    digest = _sha256(data)
    if digest != expected_sha256:
        _fail(
            f"{relative}: SHA-256 mismatch; expected {expected_sha256}, observed {digest}"
        )
    return data


def _markdown_path(report_path: str) -> str:
    if not report_path.endswith(".json"):
        _fail(f"report path must end in .json: {report_path}")
    return report_path[:-5] + ".md"


def _declared_file_manifest(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for item in report["artifacts"]:
        record = {
            "kind": item["kind"],
            "path": item["path"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "source": "artifact",
        }
        records[(str(record["path"]), str(record["sha256"]))] = record
    for evidence_record in report["evidence"]:
        for item in evidence_record["inputs"]:
            key = (str(item["path"]), str(item["sha256"]))
            records.setdefault(
                key,
                {
                    "kind": "evidence-input",
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "size_bytes": None,
                    "source": "evidence-input",
                },
            )
    return [records[key] for key in sorted(records)]


def _nonpass_incidents(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for item in report["evidence"]:
        if item["result"] != "PASS":
            incidents.append(
                {
                    "kind": "evidence",
                    "id": item["id"],
                    "state": item["result"],
                    "reason": item["reason"],
                }
            )
    for item in report["acceptance"]:
        if item["state"] != "PASS":
            incidents.append(
                {
                    "kind": "acceptance",
                    "id": item["id"],
                    "state": item["state"],
                    "reason": item["reason"],
                    "observed": item["observed"],
                }
            )
    return sorted(incidents, key=lambda item: (str(item["kind"]), str(item["id"])))


def _load_matrix(
    root: Path, baseline_commit: str
) -> tuple[evidence.ExperimentMatrix, bytes]:
    matrix_bytes = _git_blob(root, baseline_commit, DEFAULT_MATRIX_PATH)
    raw = _json_object(matrix_bytes, DEFAULT_MATRIX_PATH)
    try:
        matrix = evidence.validate_experiment_matrix(
            raw, path=Path(DEFAULT_MATRIX_PATH)
        )
    except evidence.EvidenceError as error:
        raise AggregationError(f"baseline matrix rejected: {error}") from error
    return matrix, matrix_bytes


def load_report_input(
    root: Path,
    matrix: evidence.ExperimentMatrix,
    matrix_bytes: bytes,
    spec: InputSpec,
    baseline_commit: str,
) -> dict[str, Any]:
    """Read and validate a canonical report pair directly from Git objects."""

    commit = _resolve_commit(root, spec.revision)
    if spec.expected_commit is not None and commit != spec.expected_commit:
        _fail(
            f"{spec.experiment_id}: revision moved; expected {spec.expected_commit}, observed {commit}"
        )
    if spec.role == "candidate" and not _is_ancestor(root, baseline_commit, commit):
        _fail(
            f"{spec.experiment_id}: candidate is not descended from {baseline_commit}"
        )

    candidate_matrix = _git_blob(root, commit, DEFAULT_MATRIX_PATH)
    if candidate_matrix != matrix_bytes:
        _fail(
            f"{spec.experiment_id}: experiment matrix differs from the frozen baseline"
        )

    report_bytes = _git_blob(root, commit, spec.report_path)
    markdown_path = _markdown_path(spec.report_path)
    markdown_bytes = _git_blob(root, commit, markdown_path)
    raw = _json_object(report_bytes, f"{spec.revision}:{spec.report_path}")
    try:
        normalized = evidence.prepare_report(
            matrix,
            raw,
            tracked_report=True,
            output_paths=(spec.report_path, markdown_path),
        )
        canonical_json = evidence.canonical_json_text(normalized).encode("utf-8")
        canonical_markdown = evidence.render_markdown(
            matrix,
            normalized,
            tracked_report=True,
            output_paths=(spec.report_path, markdown_path),
        ).encode("utf-8")
    except evidence.EvidenceError as error:
        raise AggregationError(
            f"{spec.experiment_id}: report rejected: {error}"
        ) from error
    if report_bytes != canonical_json:
        _fail(f"{spec.experiment_id}: committed JSON is not canonical")
    if markdown_bytes != canonical_markdown:
        _fail(f"{spec.experiment_id}: committed Markdown does not reproduce from JSON")
    _require_equal(normalized["experiment_id"], spec.experiment_id, "experiment_id")

    identity = normalized["identity"]
    source_commit = str(identity["source_commit"])
    if not _is_ancestor(root, source_commit, commit):
        _fail(f"{spec.experiment_id}: declared source commit is not in the revision")
    _require_equal(
        _tree(root, source_commit), identity["source_tree"], "identity.source_tree"
    )
    if spec.role == "candidate":
        _require_equal(
            identity["baseline_commit"], baseline_commit, "identity.baseline_commit"
        )
        _require_equal(
            identity["branch"],
            matrix.experiment(spec.experiment_id)["branch"],
            "identity.branch",
        )
    protocol_bytes = _git_blob(
        root, source_commit, str(identity["protocol_contract_path"])
    )
    _require_equal(
        _sha256(protocol_bytes), identity["protocol_sha256"], "identity.protocol_sha256"
    )

    return {
        "experiment_id": spec.experiment_id,
        "role": spec.role,
        "revision": spec.revision,
        "revision_commit": commit,
        "revision_tree": _tree(root, commit),
        "report_path": spec.report_path,
        "report_sha256": _sha256(report_bytes),
        "markdown_path": markdown_path,
        "markdown_sha256": _sha256(markdown_bytes),
        "matrix_sha256": _sha256(candidate_matrix),
        "declared_files": _declared_file_manifest(normalized),
        "incidents": _nonpass_incidents(normalized),
        "report": normalized,
    }


def _metric_line_records(stdout: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line in stdout.splitlines():
        if not line.startswith("METRIC "):
            continue
        value = _json_object(line[len("METRIC ") :].encode("utf-8"), "METRIC")
        name = value.get("name")
        if not isinstance(name, str) or not name:
            _fail("METRIC.name must be non-empty text")
        if name in records:
            _fail(f"duplicate METRIC name: {name}")
        records[name] = value
    return records


def _clock_result(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith("CLOCK_RESULT ")]
    if len(lines) != 1:
        _fail(
            f"clock service evidence must contain one CLOCK_RESULT; observed {len(lines)}"
        )
    return _json_object(
        lines[0][len("CLOCK_RESULT ") :].encode("utf-8"), "CLOCK_RESULT"
    )


def _clock_metric(
    name: str,
    value: float,
    unit: str,
    denominator: str,
    scope: str,
    *,
    reconciliation: str,
) -> dict[str, Any]:
    _require_number(value, f"clock metric {name}")
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "denominator": denominator,
        "scope": scope,
        "evidence_level": "rig",
        "evidence_ids": ["clock-450-physical-smoke"],
        "adr_reconciliation": reconciliation,
    }


def load_clock_supplement(
    root: Path,
    baseline_commit: str,
    *,
    revision: str,
    expected_commit: str | None,
    adr_path: str,
    service_path: str,
    service_sha256: str,
    summary_path: str,
    summary_sha256: str,
) -> dict[str, Any]:
    """Validate the sole authorized local evidence exception and its ADR."""

    commit = _resolve_commit(root, revision)
    if expected_commit is not None and commit != expected_commit:
        _fail(f"clock-450mhz: expected {expected_commit}, observed {commit}")
    if not _is_ancestor(root, baseline_commit, commit):
        _fail("clock-450mhz: revision does not descend from the frozen baseline")
    if not _is_ancestor(root, CLOCK_SOURCE_COMMIT, commit):
        _fail("clock-450mhz: physical build commit is not in the candidate history")

    adr_bytes = _git_blob(root, commit, adr_path)
    if expected_commit is not None and _sha256(adr_bytes) != CLOCK_ADR_SHA256:
        _fail("clock-450mhz: committed ADR SHA-256 is not the authorized value")
    try:
        adr_text = adr_bytes.decode("utf-8")
    except UnicodeError as error:
        raise AggregationError(f"clock ADR is not UTF-8: {error}") from error
    reconciliation: list[dict[str, str]] = []
    for field, fragment in CLOCK_ADR_ASSERTIONS:
        if fragment not in adr_text:
            _fail(f"clock ADR does not reconcile {field}: missing {fragment!r}")
        reconciliation.append(
            {"field": field, "status": "MATCH", "adr_fragment": fragment}
        )

    service_bytes = _read_hashed_local(root, service_path, service_sha256)
    summary_bytes = _read_hashed_local(root, summary_path, summary_sha256)
    service = _json_object(service_bytes, service_path)
    stdout = service.get("stdout")
    if not isinstance(stdout, str):
        _fail("clock service result stdout must be text")
    metrics = _metric_line_records(stdout)
    result = _clock_result(stdout)

    _require_equal(service.get("test_id"), CLOCK_JOB_ID, "service.test_id")
    _require_equal(service.get("exit_code"), 0, "service.exit_code")
    _require_equal(service.get("completed"), True, "service.completed")
    _require_equal(service.get("program_success"), True, "service.program_success")
    _require_equal(result.get("result"), "PASS", "CLOCK_RESULT.result")
    _require_equal(
        result.get("performance_result"), "PASS", "CLOCK_RESULT.performance_result"
    )
    validation = _require_mapping(result, "validation", "CLOCK_RESULT")
    _require_equal(validation.get("checks"), 404, "CLOCK_RESULT.validation.checks")
    _require_equal(validation.get("failures"), [], "CLOCK_RESULT.validation.failures")
    if len(metrics) != 404 or any(
        item.get("pass") is not True for item in metrics.values()
    ):
        _fail("clock service result must contain 404 distinct passing METRIC records")

    declared = _require_mapping(result, "declared_identity", "CLOCK_RESULT")
    identity = _require_mapping(result, "identity", "CLOCK_RESULT")
    profile = _require_mapping(identity, "clock_profile", "CLOCK_RESULT.identity")
    _require_equal(
        declared.get("firmware_artifact_sha256"), CLOCK_HEX_SHA256, "firmware HEX"
    )
    _require_equal(declared.get("source_id"), CLOCK_SOURCE_ID, "firmware source ID")
    _require_equal(
        identity.get("firmware_build_id"), CLOCK_BUILD_ID, "firmware build ID"
    )
    for field, expected in (
        ("cpu_hz", 450_000_000),
        ("dwt_hz", 450_000_000),
        ("ipg_hz", 150_000_000),
        ("adc_hz", 37_500_000),
        ("pit_hz", 24_000_000),
        ("phase_dwt_cycles", 225),
        ("phase_tolerance_dwt_cycles", 90),
    ):
        _require_equal(profile.get(field), expected, f"clock_profile.{field}")
    _require_equal(
        metrics["identity.adc_resolution_bits"].get("actual"), 12, "ADC resolution"
    )
    _require_equal(
        metrics["identity.adc.completion_counts"].get("actual"),
        [8, 8],
        "completion counts",
    )
    _require_equal(
        metrics["identity.adc.completion_timing_cycles"].get("actual"),
        222,
        "completion timing",
    )

    cleanup = _require_mapping(result, "cleanup", "CLOCK_RESULT")
    _require_equal(cleanup.get("stop_succeeded"), True, "cleanup.stop_succeeded")
    _require_equal(cleanup.get("idle_confirmed"), True, "cleanup.idle_confirmed")
    run = _require_mapping(result, "run", "CLOCK_RESULT")
    counters = _require_mapping(run, "final_error_counters", "CLOCK_RESULT.run")
    for name in CLOCK_ZERO_ERROR_FIELDS:
        _require_equal(counters.get(name), 0, f"final_error_counters.{name}")
    for name, expected in (
        ("adc_stop_pairs_discarded", 733),
        ("adc_raw_pairs_lost", 733),
        ("adc_items_dropped", 733),
        ("gpio_raw_samples_lost", 2935),
        ("gpio_items_dropped", 2935),
        ("adc_completion_mismatches", 1),
        ("adc_incomplete_buffers", 1),
        ("adc_incomplete_conversions", 1),
    ):
        _require_equal(counters.get(name), expected, f"final_error_counters.{name}")

    telemetry = _require_mapping(result, "telemetry", "CLOCK_RESULT")
    windows = _require_mapping(telemetry, "windows", "CLOCK_RESULT.telemetry")
    steady = _require_mapping(windows, "steady_state", "CLOCK_RESULT.telemetry.windows")
    acquisition = _require_mapping(
        steady, "acquisition_service_utilization_basis_points", "steady_state"
    )
    usb = _require_mapping(
        steady, "usb_service_utilization_basis_points", "steady_state"
    )
    queues = _require_mapping(steady, "queue_high_water_maxima", "steady_state")
    temperature = _require_mapping(
        steady, "temperature_millidegrees_celsius", "steady_state"
    )
    command_latency = _require_mapping(
        run, "command_latency_seconds", "CLOCK_RESULT.run"
    )
    status_latency = _require_mapping(run, "status_latency_seconds", "CLOCK_RESULT.run")

    normalized_metrics = [
        _clock_metric(
            "measurement_duration_seconds",
            run["capture_elapsed_seconds"],
            "second",
            "none",
            "streaming_window",
            reconciliation="ADR_ROUNDED",
        ),
        _clock_metric(
            "adc_pair_rate_hz",
            run["adc_pair_rate_hz"],
            "adc_pair_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
            reconciliation="ADR_ROUNDED",
        ),
        _clock_metric(
            "gpio_sample_rate_hz",
            run["gpio_sample_rate_hz"],
            "gpio_sample_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
            reconciliation="ADR_ROUNDED",
        ),
        _clock_metric(
            "combined_payload_rate_bytes_per_second",
            run["combined_payload_bytes_per_second"],
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
            reconciliation="ADR_ROUNDED",
        ),
        _clock_metric(
            "command_latency_maximum_milliseconds",
            command_latency["maximum"] * 1000,
            "millisecond",
            "command_latency_samples",
            "run",
            reconciliation="SERVICE_SUPPLEMENT",
        ),
        _clock_metric(
            "packet_owned_high_water_frames",
            queues["packet_owned"],
            "frame",
            "none",
            "streaming_window",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "packet_buffer_capacity_frames",
            200,
            "frame",
            "none",
            "artifact",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "cpu_clock_hz",
            profile["cpu_hz"],
            "hertz",
            "none",
            "artifact",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "ipg_clock_hz",
            profile["ipg_hz"],
            "hertz",
            "none",
            "artifact",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "adc_clock_hz",
            profile["adc_hz"],
            "hertz",
            "none",
            "artifact",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "pit_clock_hz",
            profile["pit_hz"],
            "hertz",
            "none",
            "artifact",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "on_chip_temperature_celsius",
            temperature["median"] / 1000,
            "degree_celsius",
            "none",
            "declared_temperature_window",
            reconciliation="SERVICE_SUPPLEMENT",
        ),
        _clock_metric(
            "acquisition_service_utilization_ratio",
            acquisition["median"] / 10000,
            "ratio",
            "service_cycles",
            "streaming_window",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "usb_service_utilization_ratio",
            usb["median"] / 10000,
            "ratio",
            "service_cycles",
            "streaming_window",
            reconciliation="ADR_EXACT",
        ),
        _clock_metric(
            "parser_errors",
            counters["parser_errors"],
            "event",
            "none",
            "run",
            reconciliation="ADR_ZERO_ERROR_ROLLUP",
        ),
        _clock_metric(
            "transport_errors",
            counters["transport_errors"],
            "event",
            "none",
            "run",
            reconciliation="ADR_ZERO_ERROR_ROLLUP",
        ),
    ]

    clock = {
        "experiment_id": "clock-450mhz",
        "role": "candidate",
        "revision": revision,
        "revision_commit": commit,
        "revision_tree": _tree(root, commit),
        "result": result["result"],
        "performance_result": result["performance_result"],
        "evidence_level": "rig",
        "classification": "bounded 10-second physical functional smoke",
        "reason": result.get("reason"),
        "evidence": [
            {
                "id": "clock-450-physical-smoke",
                "level": "rig",
                "result": "PASS",
                "reason": None,
                "job_id": CLOCK_JOB_ID,
                "firmware_build_id": CLOCK_BUILD_ID,
                "firmware_artifact_sha256": CLOCK_HEX_SHA256,
            }
        ],
        "identity": {
            "baseline_commit": baseline_commit,
            "source_commit": CLOCK_SOURCE_COMMIT,
            "source_tree": _tree(root, CLOCK_SOURCE_COMMIT),
            "source_id": CLOCK_SOURCE_ID,
            "build_id": CLOCK_BUILD_ID,
            "hex_sha256": CLOCK_HEX_SHA256,
            "job_id": CLOCK_JOB_ID,
            "hardware_serial": identity["hardware_serial"],
            "protocol_version": identity["protocol_version"],
            "clock_profile": profile,
            "adc_resolution_bits": 12,
        },
        "input_manifest": [
            {
                "kind": "committed-adr",
                "path": adr_path,
                "revision_commit": commit,
                "sha256": _sha256(adr_bytes),
            },
            {
                "kind": "authorized-local-service-result",
                "path": service_path,
                "sha256": service_sha256,
            },
            {
                "kind": "authorized-local-summary",
                "path": summary_path,
                "sha256": summary_sha256,
            },
        ],
        "adr_reconciliation": reconciliation,
        "validation": validation,
        "cleanup": cleanup,
        "metrics": normalized_metrics,
        "observations": {
            "completion_counts": [8, 8],
            "completion_median_dwt_cycles": 222,
            "completion_expected_dwt_cycles": 225,
            "completion_tolerance_dwt_cycles": 90,
            "acquisition_utilization_basis_points": acquisition,
            "usb_utilization_basis_points": usb,
            "queue_high_water_maxima": queues,
            "status_latency_seconds": status_latency,
            "command_latency_seconds": command_latency,
            "temperature_millidegrees_celsius": temperature,
            "stop_tail": {
                "adc_pairs": 733,
                "gpio_samples": 2935,
                "incomplete_completion": 1,
            },
            "zero_error_fields": list(CLOCK_ZERO_ERROR_FIELDS),
        },
        "acceptance": [
            {"id": "physical_functional_smoke", "state": "PASS", "reason": None},
            {
                "id": "same_board_ab_performance",
                "state": "NOT_RUN",
                "reason": "No same-board controlled 600/450 MHz comparison was executed.",
            },
            {
                "id": "endurance",
                "state": "NOT_RUN",
                "reason": "The physical run was bounded to ten seconds.",
            },
            {
                "id": "analog_accuracy_aperture",
                "state": "NOT_RUN",
                "reason": "No external analog stimulus was exercised.",
            },
            {
                "id": "power",
                "state": "NOT_RUN",
                "reason": "Core voltage is a profile target; rail power was not measured.",
            },
            {
                "id": "comparative_thermal_benefit",
                "state": "NOT_RUN",
                "reason": "On-chip temperature was observed without a controlled comparison.",
            },
            {
                "id": "reliability_lifetime",
                "state": "NOT_RUN",
                "reason": "A ten-second smoke cannot establish reliability or lifetime.",
            },
        ],
        "incidents": [
            {
                "id": "initial_programming_write",
                "state": "RECOVERED",
                "reason": "The first programming write failed; the bounded HalfKay retry succeeded in the same job.",
            },
            {
                "id": "immediate_stop_tail",
                "state": "RECONCILED",
                "reason": "The discarded partial generation reconciled exactly and cleanup reached IDLE.",
            },
        ],
        "limitations": [
            "No controlled same-board A/B performance comparison.",
            "No endurance evidence.",
            "No analog accuracy or aperture evidence.",
            "No measured power or comparative thermal benefit.",
            "No reliability or lifetime evidence.",
            "On-chip temperature is not ambient, power, or junction characterization.",
        ],
    }
    try:
        evidence.validate_content_policy(clock, "clock_450mhz")
    except evidence.EvidenceError as error:
        raise AggregationError(f"clock-450mhz: unsafe content: {error}") from error
    if (
        b"Result: `PASS`" not in summary_bytes
        or CLOCK_JOB_ID.encode() not in summary_bytes
    ):
        _fail("clock summary does not reconcile PASS and job identity")
    return clock


def _duration_basis(
    metrics: Sequence[Mapping[str, Any]], metric: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        metric.get("scope") != "streaming_window"
        or metric.get("name") == "measurement_duration_seconds"
    ):
        return {"status": "NOT_APPLICABLE", "seconds": None}
    evidence_ids = {str(value) for value in metric.get("evidence_ids", [])}
    candidates = [
        candidate
        for candidate in metrics
        if candidate.get("name") == "measurement_duration_seconds"
        and candidate.get("scope") == "streaming_window"
        and candidate.get("evidence_level") == metric.get("evidence_level")
        and evidence_ids.intersection(
            str(value) for value in candidate.get("evidence_ids", [])
        )
    ]
    if len(candidates) != 1:
        return {"status": "UNAVAILABLE", "seconds": None}
    return {"status": "EXACT", "seconds": candidates[0]["value"]}


def _metric_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    duration = record["duration_basis"]
    return (
        record["unit"],
        record["denominator"],
        record["scope"],
        record["evidence_level"],
        duration["status"],
        duration["seconds"],
    )


def _comparison_reasons(records: Sequence[Mapping[str, Any]]) -> list[str]:
    fields = (
        ("unit", lambda item: item["unit"]),
        ("denominator", lambda item: item["denominator"]),
        ("scope", lambda item: item["scope"]),
        ("evidence level", lambda item: item["evidence_level"]),
        (
            "duration scope",
            lambda item: evidence.canonical_json_text(item["duration_basis"]).strip(),
        ),
    )
    return [
        f"{label} differs"
        for label, getter in fields
        if len({getter(item) for item in records}) > 1
    ]


def group_metrics(experiments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group exact JSON values without averaging or crossing evidence scopes."""

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for experiment in experiments:
        report = experiment.get("report", experiment)
        metrics = report.get("metrics")
        if not isinstance(metrics, list):
            _fail(f"{experiment.get('experiment_id')}: metrics must be an array")
        identity = report.get("identity")
        if not isinstance(identity, Mapping):
            _fail(f"{experiment.get('experiment_id')}: identity must be an object")
        artifact_identity = {
            "source_commit": identity.get("source_commit"),
            "source_id": identity.get("source_id"),
            "build_id": identity.get("build_id"),
            "hex_sha256": identity.get("hex_sha256"),
        }
        for metric in metrics:
            if not isinstance(metric, Mapping):
                _fail("metric record must be an object")
            record = {
                "experiment_id": experiment["experiment_id"],
                "artifact_identity": artifact_identity,
                "name": metric["name"],
                "value": metric["value"],
                "unit": metric["unit"],
                "denominator": metric["denominator"],
                "scope": metric["scope"],
                "evidence_level": metric["evidence_level"],
                "evidence_ids": list(metric["evidence_ids"]),
                "duration_basis": _duration_basis(metrics, metric),
            }
            by_name[str(metric["name"])].append(record)

    groups: list[dict[str, Any]] = []
    for name in sorted(by_name):
        records = sorted(
            by_name[name],
            key=lambda item: (
                str(item["experiment_id"]),
                evidence.canonical_json_text(item["artifact_identity"]),
            ),
        )
        signatures = {_metric_signature(item) for item in records}
        if len(records) == 1:
            status = "SIDE_BY_SIDE_ONLY"
            reasons = ["No peer value with the same metric name is present."]
        elif len(signatures) == 1:
            status = "COMPARABLE"
            reasons = [
                "Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."
            ]
        else:
            status = "NONCOMPARABLE"
            reasons = _comparison_reasons(records)
        groups.append(
            {
                "name": name,
                "status": status,
                "reasons": reasons,
                "values": records,
                "derived_value": None,
            }
        )
    return groups


def _experiment_evidence_index(
    experiments: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    evidence_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    experiment_index: dict[str, Mapping[str, Any]] = {}
    for experiment in experiments:
        experiment_id = str(experiment["experiment_id"])
        if experiment_id in experiment_index:
            _fail(f"duplicate experiment identity: {experiment_id}")
        experiment_index[experiment_id] = experiment
        report = experiment.get("report", experiment)
        raw_evidence = report.get("evidence")
        if not isinstance(raw_evidence, list):
            _fail(f"{experiment_id}: evidence must be an array")
        for record in raw_evidence:
            if not isinstance(record, Mapping) or not isinstance(record.get("id"), str):
                _fail(f"{experiment_id}: malformed evidence record")
            key = (experiment_id, str(record["id"]))
            if key in evidence_index:
                _fail(f"{experiment_id}: duplicate evidence id {record['id']}")
            evidence_index[key] = record
    return evidence_index, experiment_index


def validate_conclusions(
    conclusions: Sequence[Any], experiments: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Validate claim scope and prohibit invented combined-artifact evidence."""

    evidence_index, experiment_index = _experiment_evidence_index(experiments)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(conclusions):
        location = f"conclusions[{index}]"
        if not isinstance(raw, dict):
            _fail(f"{location}: must be an object")
        required = {
            "id",
            "statement",
            "claim_scope",
            "artifact_claim",
            "evidence_refs",
        }
        if set(raw) != required:
            _fail(f"{location}: fields must be exactly {sorted(required)}")
        conclusion_id = raw["id"]
        statement = raw["statement"]
        if not isinstance(conclusion_id, str) or not conclusion_id:
            _fail(f"{location}.id: must be non-empty text")
        if conclusion_id in seen_ids:
            _fail(f"{location}.id: duplicate conclusion")
        seen_ids.add(conclusion_id)
        if not isinstance(statement, str) or not statement.strip():
            _fail(f"{location}.statement: must be non-empty text")
        claim_scope = raw["claim_scope"]
        if claim_scope not in {"physical", "nonphysical"}:
            _fail(f"{location}.claim_scope: must be physical or nonphysical")
        artifact_claim = raw["artifact_claim"]
        if artifact_claim not in {"separate", "single_build"}:
            _fail(f"{location}.artifact_claim: must be separate or single_build")
        refs = raw["evidence_refs"]
        if not isinstance(refs, list) or not refs:
            _fail(f"{location}.evidence_refs: must be a non-empty array")
        selected_experiments: set[str] = set()
        artifact_ids: set[str] = set()
        selected_levels: set[str] = set()
        normalized_refs: list[dict[str, str]] = []
        for ref_index, ref in enumerate(refs):
            if not isinstance(ref, dict) or set(ref) != {
                "experiment_id",
                "evidence_id",
            }:
                _fail(
                    f"{location}.evidence_refs[{ref_index}]: requires experiment_id and evidence_id"
                )
            experiment_id = ref["experiment_id"]
            evidence_id = ref["evidence_id"]
            if not isinstance(experiment_id, str) or not isinstance(evidence_id, str):
                _fail(f"{location}.evidence_refs[{ref_index}]: ids must be text")
            try:
                selected = evidence_index[(experiment_id, evidence_id)]
                experiment = experiment_index[experiment_id]
            except KeyError as error:
                raise AggregationError(
                    f"{location}: unknown evidence {experiment_id}/{evidence_id}"
                ) from error
            level = str(selected.get("level"))
            selected_levels.add(level)
            selected_experiments.add(experiment_id)
            report = experiment.get("report", experiment)
            identity = report["identity"]
            artifact_ids.add(
                str(
                    identity.get("hex_sha256")
                    or identity.get("source_id")
                    or identity.get("source_commit")
                )
            )
            normalized_refs.append(
                {
                    "experiment_id": experiment_id,
                    "evidence_id": evidence_id,
                    "evidence_level": level,
                }
            )
        if claim_scope == "physical" and not selected_levels.issubset(
            {"rig", "manual"}
        ):
            _fail(
                f"{location}: physical conclusion cites nonphysical evidence levels {sorted(selected_levels - {'rig', 'manual'})}"
            )
        if artifact_claim == "single_build" and len(artifact_ids) != 1:
            _fail(
                f"{location}: single-build conclusion combines {len(artifact_ids)} artifact identities"
            )
        normalized.append(
            {
                "id": conclusion_id,
                "statement": statement,
                "claim_scope": claim_scope,
                "artifact_claim": artifact_claim,
                "evidence_refs": sorted(
                    normalized_refs,
                    key=lambda item: (item["experiment_id"], item["evidence_id"]),
                ),
                "experiment_ids": sorted(selected_experiments),
                "artifact_identity_count": len(artifact_ids),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def validate_recommendations(
    recommendations: Sequence[Any], experiments: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Require every decision to cite exact raw acceptance outcomes and identity."""

    _, experiment_index = _experiment_evidence_index(experiments)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(recommendations):
        location = f"recommendations[{index}]"
        if not isinstance(raw, dict):
            _fail(f"{location}: must be an object")
        required = {
            "experiment_id",
            "decision",
            "branch_commit",
            "acceptance_ids",
            "evidence_levels",
            "scope",
            "rationale",
        }
        if set(raw) != required:
            _fail(f"{location}: fields must be exactly {sorted(required)}")
        experiment_id = raw["experiment_id"]
        if not isinstance(experiment_id, str) or experiment_id in seen:
            _fail(f"{location}.experiment_id: must be unique non-empty text")
        seen.add(experiment_id)
        try:
            experiment = experiment_index[experiment_id]
        except KeyError as error:
            raise AggregationError(
                f"{location}: unknown experiment {experiment_id}"
            ) from error
        if raw["decision"] not in {"ADOPT", "CONTINUE", "DEFER", "REJECT"}:
            _fail(f"{location}.decision: invalid disposition")
        _require_equal(
            raw["branch_commit"],
            experiment["revision_commit"],
            f"{location}.branch_commit",
        )
        if raw["scope"] not in {
            "production_default",
            "optional_capability",
            "experimental",
        }:
            _fail(f"{location}.scope: invalid recommendation scope")
        if not isinstance(raw["rationale"], str) or not raw["rationale"].strip():
            _fail(f"{location}.rationale: must be non-empty text")
        report = experiment.get("report", experiment)
        acceptance = {str(item["id"]): item for item in report["acceptance"]}
        acceptance_ids = raw["acceptance_ids"]
        if not isinstance(acceptance_ids, list) or not acceptance_ids:
            _fail(f"{location}.acceptance_ids: must be a non-empty array")
        if len(set(acceptance_ids)) != len(acceptance_ids) or not set(
            acceptance_ids
        ).issubset(acceptance):
            _fail(f"{location}.acceptance_ids: duplicate or unknown acceptance id")
        evidence_levels = raw["evidence_levels"]
        available_levels = {str(item["level"]) for item in report["evidence"]}
        if (
            not isinstance(evidence_levels, list)
            or not evidence_levels
            or len(set(evidence_levels)) != len(evidence_levels)
            or not set(evidence_levels).issubset(available_levels)
        ):
            _fail(f"{location}.evidence_levels: duplicate, empty, or unavailable level")
        cited_states = {str(acceptance[item]["state"]) for item in acceptance_ids}
        if raw["decision"] == "ADOPT" and cited_states != {"PASS"}:
            _fail(f"{location}: ADOPT may cite only passed acceptance outcomes")
        if raw["decision"] == "REJECT" and "FAIL" not in cited_states:
            _fail(f"{location}: REJECT requires a cited failed acceptance outcome")
        if raw["decision"] in {"CONTINUE", "DEFER"} and not cited_states.intersection(
            {"FAIL", "INCONCLUSIVE", "NOT_RUN"}
        ):
            _fail(
                f"{location}: {raw['decision']} requires a cited incomplete or failed gate"
            )
        normalized.append(
            {
                **raw,
                "acceptance_ids": sorted(acceptance_ids),
                "evidence_levels": sorted(evidence_levels),
                "acceptance_outcomes": [
                    {
                        "id": item,
                        "state": acceptance[item]["state"],
                        "reason": acceptance[item].get("reason"),
                    }
                    for item in sorted(acceptance_ids)
                ],
            }
        )
    return sorted(normalized, key=lambda item: item["experiment_id"])


def load_analysis(
    root: Path, relative: str | None, experiments: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Load optional authored conclusions and decisions under a strict contract."""

    if relative is None:
        return {"conclusions": [], "recommendations": []}, None
    selected = _local_file(root, relative)
    try:
        data = selected.read_bytes()
    except OSError as error:
        raise AggregationError(
            f"could not read analysis input {relative}: {error}"
        ) from error
    raw = _json_object(data, relative)
    if set(raw) != {"schema_version", "conclusions", "recommendations"}:
        _fail(
            "analysis input fields must be exactly schema_version, conclusions, and recommendations"
        )
    _require_equal(raw["schema_version"], 1, "analysis.schema_version")
    conclusions = _require_list(raw, "conclusions", "analysis")
    recommendations = _require_list(raw, "recommendations", "analysis")
    return (
        {
            "conclusions": validate_conclusions(conclusions, experiments),
            "recommendations": validate_recommendations(recommendations, experiments),
        },
        {"kind": "analysis-input", "path": relative, "sha256": _sha256(data)},
    )


def build_aggregate(
    root: Path,
    specs: Sequence[InputSpec],
    *,
    created: str,
    clock_revision: str,
    expected_clock_commit: str | None,
    clock_adr_path: str,
    clock_service_path: str,
    clock_service_sha256: str,
    clock_summary_path: str,
    clock_summary_sha256: str,
    analysis_path: str | None = None,
) -> dict[str, Any]:
    """Build one deterministic aggregate exclusively from validated exact inputs."""

    if len({spec.experiment_id for spec in specs}) != len(specs):
        _fail("duplicate experiment input")
    try:
        date.fromisoformat(created)
    except ValueError as error:
        raise AggregationError("created must be a valid ISO calendar date") from error
    if len(created) != 10:
        _fail("created must use YYYY-MM-DD format")
    ordered_specs = sorted(
        specs,
        key=lambda spec: (
            INPUT_ORDER.get(spec.experiment_id, 10**9),
            spec.experiment_id,
        ),
    )
    baselines = [spec for spec in ordered_specs if spec.role == "baseline"]
    if len(baselines) != 1:
        _fail("exactly one baseline input is required")
    baseline_commit = _resolve_commit(root, baselines[0].revision)
    if (
        baselines[0].expected_commit is not None
        and baseline_commit != baselines[0].expected_commit
    ):
        _fail("baseline revision moved from its expected commit")
    matrix, matrix_bytes = _load_matrix(root, baseline_commit)

    report_inputs = [
        load_report_input(root, matrix, matrix_bytes, spec, baseline_commit)
        for spec in ordered_specs
    ]
    clock = load_clock_supplement(
        root,
        baseline_commit,
        revision=clock_revision,
        expected_commit=expected_clock_commit,
        adr_path=clock_adr_path,
        service_path=clock_service_path,
        service_sha256=clock_service_sha256,
        summary_path=clock_summary_path,
        summary_sha256=clock_summary_sha256,
    )
    all_experiments = [*report_inputs, clock]
    analysis, analysis_manifest = load_analysis(root, analysis_path, all_experiments)
    aggregate = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "kind": "thingdaq-experiment-aggregate",
        "title": "ThingDAQ Clock, Compression, and I/O Experiment Evidence",
        "created": created,
        "related": list(RELATED_LINKS),
        "baseline_commit": baseline_commit,
        "matrix": {
            "path": DEFAULT_MATRIX_PATH,
            "schema_version": matrix.schema_version,
            "sha256": _sha256(matrix_bytes),
        },
        "aggregation_policy": {
            "json_is_source_of_truth": True,
            "rounded_markdown_is_input": False,
            "cross_artifact_values_are_combined": False,
            "lower_evidence_promoted_to_physical": False,
            "untested_cross_branch_combination_is_verified": False,
            "comparability_key": [
                "name",
                "unit",
                "denominator",
                "scope",
                "evidence_level",
                "duration_basis",
            ],
        },
        "input_manifest": [
            {
                "experiment_id": item["experiment_id"],
                "revision": item["revision"],
                "revision_commit": item["revision_commit"],
                "revision_tree": item["revision_tree"],
                "report_path": item["report_path"],
                "report_sha256": item["report_sha256"],
                "markdown_path": item["markdown_path"],
                "markdown_sha256": item["markdown_sha256"],
                "matrix_sha256": item["matrix_sha256"],
            }
            for item in report_inputs
        ]
        + [
            {
                "experiment_id": "clock-450mhz",
                "revision": clock["revision"],
                "revision_commit": clock["revision_commit"],
                "revision_tree": clock["revision_tree"],
                "inputs": clock["input_manifest"],
            }
        ]
        + (
            [
                {
                    "experiment_id": "synthesis-analysis",
                    "revision": "working-tree-input",
                    "revision_commit": None,
                    "revision_tree": None,
                    "inputs": [analysis_manifest],
                }
            ]
            if analysis_manifest is not None
            else []
        ),
        "experiments": all_experiments,
        "metric_groups": group_metrics(all_experiments),
        "conclusions": analysis["conclusions"],
        "recommendations": analysis["recommendations"],
        "claim_limitations": [
            "Independent candidate results do not establish a combined clock, compression, and auxiliary-I/O binary.",
            "A host, analytic, or simulated result is not physical evidence.",
            "Different artifact identities remain separate even when metric definitions are comparable.",
            "Missing live or manual evidence remains FAIL, INCONCLUSIVE, or NOT_RUN exactly as reported.",
        ],
    }
    try:
        evidence.validate_content_policy(aggregate, "aggregate")
    except evidence.EvidenceError as error:
        raise AggregationError(f"aggregate contains unsafe content: {error}") from error
    return aggregate


def _markdown_cell(value: Any) -> str:
    if value is None:
        rendered = "—"
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, (dict, list)):
        rendered = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    else:
        rendered = str(value)
    return (
        rendered.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", "<br>")
    )


def render_markdown(aggregate: Mapping[str, Any]) -> str:
    """Render stable DocGraph-ready Markdown from normalized aggregate JSON."""

    lines = [
        "---",
        "type: report",
        f"title: {json.dumps(aggregate['title'], ensure_ascii=False)}",
        f"created: {aggregate['created']}",
        "tags:",
        "  - thingdaq",
        "  - experiment-evidence",
        "  - synthesis",
        "related:",
        *[f"  - {json.dumps(link)}" for link in aggregate["related"]],
        "---",
        "",
        f"# {aggregate['title']}",
        "",
        "> [!IMPORTANT]",
        "> Independent branch results are not evidence that the features work together in one binary.",
        "",
        "## Executive outcomes",
        "",
        "| Experiment | Revision commit | Raw result | Evidence boundary |",
        "| --- | --- | --- | --- |",
    ]
    for item in aggregate["experiments"]:
        report = item.get("report", item)
        boundary = item.get("classification", "canonical Phase 01 report")
        lines.append(
            f"| {_markdown_cell(item['experiment_id'])} | `{_markdown_cell(item['revision_commit'])}` | **{_markdown_cell(report['result'])}** | {_markdown_cell(boundary)} |"
        )

    lines.extend(
        [
            "",
            "## Reproducible input manifest",
            "",
            f"Frozen baseline: `{aggregate['baseline_commit']}`",
            "",
            f"Matrix: `{aggregate['matrix']['path']}` at SHA-256 `{aggregate['matrix']['sha256']}`",
            "",
            "| Experiment | Revision | Commit | Tree | Inputs |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in aggregate["input_manifest"]:
        inputs = item.get("inputs")
        if inputs is None:
            inputs = [
                {"path": item["report_path"], "sha256": item["report_sha256"]},
                {"path": item["markdown_path"], "sha256": item["markdown_sha256"]},
            ]
        lines.append(
            f"| {_markdown_cell(item['experiment_id'])} | `{_markdown_cell(item['revision'])}` | `{item['revision_commit']}` | `{item['revision_tree']}` | {_markdown_cell(inputs)} |"
        )

    lines.extend(
        [
            "",
            "## Metric comparability",
            "",
            "No values in this section are averaged, pooled, or presented as one build.",
            "",
            "| Metric | Status | Exact values | Reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    for group in aggregate["metric_groups"]:
        values = [
            {
                "experiment": value["experiment_id"],
                "value": value["value"],
                "unit": value["unit"],
                "denominator": value["denominator"],
                "scope": value["scope"],
                "evidence_level": value["evidence_level"],
                "duration_basis": value["duration_basis"],
                "source_commit": value["artifact_identity"]["source_commit"],
            }
            for value in group["values"]
        ]
        lines.append(
            f"| {_markdown_cell(group['name'])} | **{group['status']}** | {_markdown_cell(values)} | {_markdown_cell(group['reasons'])} |"
        )

    lines.extend(["", "## Source outcomes and limitations", ""])
    for item in aggregate["experiments"]:
        report = item.get("report", item)
        lines.extend(
            [
                f"### {item['experiment_id']}",
                "",
                f"Raw result: **{report['result']}**",
                "",
                f"Reason: {_markdown_cell(report.get('reason'))}",
                "",
                "#### Acceptance",
                "",
                "| Check | State | Reason | Observed |",
                "| --- | --- | --- | --- |",
            ]
        )
        for record in report["acceptance"]:
            lines.append(
                f"| {_markdown_cell(record['id'])} | **{_markdown_cell(record['state'])}** | {_markdown_cell(record.get('reason'))} | {_markdown_cell(record.get('observed'))} |"
            )
        lines.extend(
            [
                "",
                "#### Incidents",
                "",
                "| ID | State | Reason |",
                "| --- | --- | --- |",
            ]
        )
        incidents = item.get("incidents", [])
        if not incidents:
            lines.append("| None recorded | — | — |")
        for incident in incidents:
            lines.append(
                f"| {_markdown_cell(incident['id'])} | **{_markdown_cell(incident['state'])}** | {_markdown_cell(incident['reason'])} |"
            )
        lines.extend(["", "#### Claim limitations", ""])
        for limitation in report["limitations"]:
            statement = (
                limitation.get("statement")
                if isinstance(limitation, Mapping)
                else limitation
            )
            lines.append(f"- {_markdown_cell(statement)}")
        if item["experiment_id"] != "clock-450mhz":
            lines.extend(["", "#### Declared artifacts and evidence inputs", ""])
            for declared in item["declared_files"]:
                lines.append(
                    f"- `{_markdown_cell(declared['path'])}` — SHA-256 `{declared['sha256']}`"
                )
        lines.append("")

    lines.extend(["## Evidence-backed conclusions", ""])
    if not aggregate["conclusions"]:
        lines.append("No authored conclusions were supplied.")
    for conclusion in aggregate["conclusions"]:
        lines.append(
            f"- **{_markdown_cell(conclusion['id'])}:** {_markdown_cell(conclusion['statement'])} "
            f"({_markdown_cell(conclusion['claim_scope'])}; {_markdown_cell(conclusion['artifact_claim'])})"
        )
    lines.extend(["", "## Recommendations", ""])
    if not aggregate["recommendations"]:
        lines.append("No authored recommendations were supplied.")
    for recommendation in aggregate["recommendations"]:
        lines.append(
            f"- **{_markdown_cell(recommendation['experiment_id'])}: {_markdown_cell(recommendation['decision'])}** — "
            f"{_markdown_cell(recommendation['rationale'])}"
        )
    lines.append("")

    lines.extend(["## Aggregate claim limitations", ""])
    lines.extend(f"- {limitation}" for limitation in aggregate["claim_limitations"])
    lines.append("")
    return "\n".join(lines)


def _render_pair(aggregate: Mapping[str, Any]) -> tuple[str, str]:
    return evidence.canonical_json_text(aggregate), render_markdown(aggregate)


def _require_deterministic(aggregate: Mapping[str, Any]) -> tuple[str, str]:
    first = _render_pair(aggregate)
    second = _render_pair(aggregate)
    if first != second:
        _fail("two aggregate renders from identical normalized inputs differ")
    return first


def _parse_input(value: str) -> InputSpec:
    fields = value.split("=", 4)
    if len(fields) not in {4, 5}:
        raise argparse.ArgumentTypeError(
            "input must be EXPERIMENT_ID=ROLE=REVISION=REPORT_PATH[=EXPECTED_COMMIT]"
        )
    experiment_id, role, revision, report_path = fields[:4]
    expected = fields[4] if len(fields) == 5 else None
    if role not in {"baseline", "candidate"}:
        raise argparse.ArgumentTypeError("input ROLE must be baseline or candidate")
    if not all((experiment_id, revision, report_path)):
        raise argparse.ArgumentTypeError("input fields must be non-empty")
    return InputSpec(experiment_id, role, revision, report_path, expected)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument(
        "--input",
        action="append",
        type=_parse_input,
        help="replace defaults with EXPERIMENT_ID=ROLE=REVISION=REPORT_PATH[=EXPECTED_COMMIT]",
    )
    parser.add_argument("--clock-revision", default="origin/experiment/clock-450mhz")
    parser.add_argument("--expected-clock-commit", default=CLOCK_HEAD_COMMIT)
    parser.add_argument("--clock-adr-path", default=DEFAULT_CLOCK_ADR_PATH)
    parser.add_argument("--clock-service-result", default=DEFAULT_CLOCK_SERVICE_PATH)
    parser.add_argument("--clock-service-sha256", default=CLOCK_SERVICE_SHA256)
    parser.add_argument("--clock-summary", default=DEFAULT_CLOCK_SUMMARY_PATH)
    parser.add_argument("--clock-summary-sha256", default=CLOCK_SUMMARY_SHA256)
    parser.add_argument("--created", default=DEFAULT_CREATED)
    parser.add_argument(
        "--analysis",
        help="optional repository-relative JSON containing validated conclusions and recommendations",
    )
    parser.add_argument("--json-output", default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", default=DEFAULT_MARKDOWN_OUTPUT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="validate inputs and fail on output drift"
    )
    action.add_argument(
        "--determinism-check",
        action="store_true",
        help="render twice and print hashes without reading or writing outputs",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    root = arguments.repository_root.resolve()
    specs = tuple(arguments.input) if arguments.input else DEFAULT_INPUTS
    try:
        aggregate = build_aggregate(
            root,
            specs,
            created=arguments.created,
            clock_revision=arguments.clock_revision,
            expected_clock_commit=arguments.expected_clock_commit or None,
            clock_adr_path=arguments.clock_adr_path,
            clock_service_path=arguments.clock_service_result,
            clock_service_sha256=arguments.clock_service_sha256,
            clock_summary_path=arguments.clock_summary,
            clock_summary_sha256=arguments.clock_summary_sha256,
            analysis_path=arguments.analysis,
        )
        json_text, markdown_text = _require_deterministic(aggregate)
        json_path = _local_file(root, arguments.json_output)
        markdown_path = _local_file(root, arguments.markdown_output)
        if json_path == markdown_path:
            _fail("JSON and Markdown output paths must differ")
        if json_path.suffix != ".json" or markdown_path.suffix != ".md":
            _fail("aggregate outputs must use .json and .md suffixes")
        if arguments.determinism_check:
            print(f"PASS deterministic JSON sha256={_sha256(json_text.encode())}")
            print(
                f"PASS deterministic Markdown sha256={_sha256(markdown_text.encode())}"
            )
        elif arguments.check:
            try:
                observed_json = json_path.read_text(encoding="utf-8")
                observed_markdown = markdown_path.read_text(encoding="utf-8")
            except OSError as error:
                raise AggregationError(
                    f"could not read aggregate outputs: {error}"
                ) from error
            if observed_json != json_text:
                _fail(
                    f"JSON output is missing, stale, or noncanonical: {arguments.json_output}"
                )
            if observed_markdown != markdown_text:
                _fail(
                    f"Markdown output is missing, stale, or noncanonical: {arguments.markdown_output}"
                )
            print(
                "PASS aggregate inputs, schema, claims, and deterministic outputs are current"
            )
        else:
            evidence.atomic_write_text(json_path, json_text)
            evidence.atomic_write_text(markdown_path, markdown_text)
            print(f"wrote {arguments.json_output} and {arguments.markdown_output}")
    except (AggregationError, evidence.EvidenceError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
