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


def _experiment_by_id(
    experiments: Sequence[Mapping[str, Any]], experiment_id: str
) -> Mapping[str, Any]:
    matches = [
        item for item in experiments if item.get("experiment_id") == experiment_id
    ]
    if len(matches) != 1:
        _fail(f"cross-experiment analysis requires exactly one {experiment_id!r} input")
    return matches[0]


def _report_for(experiment: Mapping[str, Any]) -> Mapping[str, Any]:
    report = experiment.get("report", experiment)
    if not isinstance(report, Mapping):
        _fail(f"{experiment.get('experiment_id')}: report must be an object")
    return report


def _evidence_by_id(
    report: Mapping[str, Any], experiment_id: str, evidence_id: str
) -> Mapping[str, Any]:
    records = _require_list(report, "evidence", experiment_id)
    matches = [
        item
        for item in records
        if isinstance(item, Mapping) and item.get("id") == evidence_id
    ]
    if len(matches) != 1:
        _fail(f"{experiment_id}: requires evidence {evidence_id!r}")
    return matches[0]


def _nested_mapping(
    owner: Mapping[str, Any], location: str, *keys: str
) -> Mapping[str, Any]:
    value: Any = owner
    traversed = location
    for key in keys:
        if not isinstance(value, Mapping):
            _fail(f"{traversed}: must be an object")
        value = value.get(key)
        traversed = f"{traversed}.{key}"
    if not isinstance(value, Mapping):
        _fail(f"{traversed}: must be an object")
    return value


def _nested_list(owner: Mapping[str, Any], location: str, *keys: str) -> list[Any]:
    value: Any = owner
    traversed = location
    for key in keys:
        if not isinstance(value, Mapping):
            _fail(f"{traversed}: must be an object")
        value = value.get(key)
        traversed = f"{traversed}.{key}"
    if not isinstance(value, list):
        _fail(f"{traversed}: must be an array")
    return value


def _metric_value(
    report: Mapping[str, Any],
    experiment_id: str,
    name: str,
    *,
    evidence_level: str | None = None,
) -> Any:
    metrics = _require_list(report, "metrics", experiment_id)
    matches = [
        item
        for item in metrics
        if isinstance(item, Mapping)
        and item.get("name") == name
        and (evidence_level is None or item.get("evidence_level") == evidence_level)
    ]
    if len(matches) != 1:
        suffix = f" at {evidence_level}" if evidence_level is not None else ""
        _fail(f"{experiment_id}: requires one metric {name!r}{suffix}")
    return matches[0].get("value")


def _acceptance_state(
    report: Mapping[str, Any], experiment_id: str, acceptance_id: str
) -> dict[str, Any]:
    acceptance = _require_list(report, "acceptance", experiment_id)
    matches = [
        item
        for item in acceptance
        if isinstance(item, Mapping) and item.get("id") == acceptance_id
    ]
    if len(matches) != 1:
        _fail(f"{experiment_id}: requires acceptance {acceptance_id!r}")
    return {
        "state": matches[0].get("state"),
        "reason": matches[0].get("reason"),
    }


def _declared_sha256(experiment: Mapping[str, Any], path: str) -> str:
    records = experiment.get("declared_files")
    if not isinstance(records, list):
        _fail(f"{experiment.get('experiment_id')}: declared_files must be an array")
    hashes = {
        str(item.get("sha256"))
        for item in records
        if isinstance(item, Mapping) and item.get("path") == path
    }
    if len(hashes) != 1:
        _fail(
            f"{experiment.get('experiment_id')}: requires one declared hash for {path}"
        )
    return hashes.pop()


def load_protocol_extension(
    root: Path, experiment: Mapping[str, Any]
) -> dict[str, Any]:
    """Read one declared protocol-v2 contract from the candidate Git object."""

    experiment_id = str(experiment["experiment_id"])
    path = "protocol/protocol-v2.json"
    expected_sha256 = _declared_sha256(experiment, path)
    commit = str(experiment["revision_commit"])
    data = _git_blob(root, commit, path)
    digest = _sha256(data)
    _require_equal(digest, expected_sha256, f"{experiment_id}.protocol_v2_sha256")
    contract = _json_object(data, f"{commit}:{path}")
    _require_equal(contract.get("protocol_version"), 2, f"{experiment_id}.protocol")
    _require_equal(
        contract.get("extension"), experiment_id, f"{experiment_id}.extension"
    )
    return {
        "path": path,
        "sha256": digest,
        "extension": contract["extension"],
        "contract": contract,
    }


def _half_rational(value: str, location: str) -> str:
    try:
        numerator_text, denominator_text = value.split("/", 1)
        numerator = int(numerator_text)
        denominator = int(denominator_text)
    except (ValueError, AttributeError) as error:
        raise AggregationError(f"{location}: invalid exact rational") from error
    if denominator <= 0 or numerator % 2 != 0:
        _fail(f"{location}: cannot be halved exactly")
    return f"{numerator // 2}/{denominator}"


def _sum_rationals(left: str, right: str, location: str) -> str:
    try:
        left_numerator, left_denominator = (int(item) for item in left.split("/", 1))
        right_numerator, right_denominator = (int(item) for item in right.split("/", 1))
    except (ValueError, AttributeError) as error:
        raise AggregationError(f"{location}: invalid exact rational") from error
    if left_denominator != right_denominator or left_denominator <= 0:
        _fail(f"{location}: rational denominators differ")
    return f"{left_numerator + right_numerator}/{left_denominator}"


def build_cross_experiment_analysis(
    experiments: Sequence[Mapping[str, Any]],
    protocol_extensions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the synthesis analysis from validated exact evidence fields."""

    clock = _experiment_by_id(experiments, "clock-450mhz")
    rle = _experiment_by_id(experiments, "rle-streaming")
    aux_input = _experiment_by_id(experiments, "aux-input-bank")
    aux_output = _experiment_by_id(experiments, "aux-output-bank")
    clock_report = _report_for(clock)
    rle_report = _report_for(rle)
    input_report = _report_for(aux_input)
    output_report = _report_for(aux_output)

    rle_protocol = protocol_extensions["rle-streaming"]
    input_protocol = protocol_extensions["aux-input-bank"]
    output_protocol = protocol_extensions["aux-output-bank"]
    rle_contract = _nested_mapping(rle_protocol, "rle_protocol", "contract")
    input_contract = _nested_mapping(input_protocol, "input_protocol", "contract")
    output_contract = _nested_mapping(output_protocol, "output_protocol", "contract")

    clock_observations = _nested_mapping(clock, "clock-450mhz", "observations")
    clock_identity = _nested_mapping(clock_report, "clock-450mhz", "identity")
    clock_profile = _nested_mapping(
        clock_identity, "clock-450mhz.identity", "clock_profile"
    )
    output_build = _evidence_by_id(output_report, "aux-output-bank", "firmware-build")
    output_build_details = _nested_mapping(
        output_build, "aux-output-bank.firmware-build", "build"
    )
    _require_equal(
        output_build_details.get("fqbn"),
        "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
        "aux-output-bank.firmware-build.fqbn",
    )
    output_physical = _evidence_by_id(
        output_report, "aux-output-bank", "rig-no-output-combined"
    )
    output_run = _nested_mapping(
        output_physical, "aux-output-bank.rig-no-output-combined", "run"
    )

    rle_physical = _evidence_by_id(
        rle_report, "rle-streaming", "physical-accepted-campaign"
    )
    matched = _nested_mapping(
        rle_physical, "rle-streaming.physical-accepted-campaign", "matched_physical"
    )
    matched_streams = _nested_mapping(
        matched, "rle-streaming.physical-accepted-campaign.matched_physical", "streams"
    )
    rle_performance = _nested_mapping(
        rle_physical, "rle-streaming.physical-accepted-campaign", "performance"
    )
    physical_streams: list[dict[str, Any]] = []
    for stream_name in ("adc", "gpio", "combined"):
        stream = _nested_mapping(
            matched_streams, "matched_physical.streams", stream_name
        )
        grade = _nested_mapping(
            stream, f"matched_physical.streams.{stream_name}", "grade"
        )
        raw = _nested_mapping(stream, f"matched_physical.streams.{stream_name}", "raw")
        rle_auto = _nested_mapping(
            stream, f"matched_physical.streams.{stream_name}", "rle_auto"
        )
        physical_streams.append(
            {
                "stream": stream_name.upper(),
                "logical_payload_bytes": grade.get("logical_payload_bytes"),
                "raw_complete_wire_bytes": grade.get("raw_complete_wire_bytes"),
                "selected_complete_wire_bytes": grade.get(
                    "selected_complete_wire_bytes"
                ),
                "complete_wire_ratio": grade.get("complete_wire_ratio"),
                "complete_wire_reduction_ratio": grade.get(
                    "complete_wire_reduction_ratio"
                ),
                "raw_frames": grade.get("raw_frames"),
                "rle_frames": grade.get("rle_frames"),
                "fallback_frames": rle_auto.get("raw_frames"),
                "fallback_frequency": {
                    "numerator": rle_auto.get("raw_frames"),
                    "denominator": rle_auto.get("frames"),
                },
                "encode_cycles": grade.get("encode_cycles"),
                "processing_utilization_delta_percentage_points": grade.get(
                    "processing_utilization_delta_percentage_points"
                ),
                "raw_decode_bytes_per_second": raw.get("decode_bytes_per_second"),
                "rle_auto_decode_bytes_per_second": rle_auto.get(
                    "decode_bytes_per_second"
                ),
                "bandwidth_result": grade.get("bandwidth_reduction_result"),
                "processing_result": grade.get("processing_utilization_result"),
                "overall_value_result": grade.get("result"),
            }
        )

    input_workload = _evidence_by_id(
        input_report, "aux-input-bank", "aux-input-workload-analysis"
    )
    input_profiles = _require_list(
        input_workload, "profiles", "aux-input-bank.aux-input-workload-analysis"
    )
    input_build = _evidence_by_id(input_report, "aux-input-bank", "firmware-build")
    input_contract_body = _nested_mapping(
        input_contract, "aux-input-bank.protocol-v2", "auxiliary_input"
    )
    input_layouts = _nested_mapping(
        input_contract_body, "aux-input-bank.protocol-v2.auxiliary_input", "layouts"
    )
    disabled_layout = _nested_mapping(
        input_layouts, "aux-input-bank.protocol-v2.layouts", "DISABLED"
    )
    enabled_layout = _nested_mapping(
        input_layouts, "aux-input-bank.protocol-v2.layouts", "INPUT"
    )
    retention = _nested_mapping(
        input_build, "aux-input-bank.firmware-build", "packet_retention"
    )
    retention_profiles = _nested_list(
        retention, "aux-input-bank.firmware-build.packet_retention", "profiles"
    )
    retention_by_name = {
        str(item.get("profile")): item
        for item in retention_profiles
        if isinstance(item, Mapping)
    }
    profile_comparison: list[dict[str, Any]] = []
    for profile in input_profiles:
        if not isinstance(profile, Mapping):
            _fail("aux-input-bank profile must be an object")
        profile_name = str(profile.get("profile"))
        profile_retention = retention_by_name.get(profile_name)
        if not isinstance(profile_retention, Mapping):
            _fail(f"aux-input-bank: missing retention for {profile_name}")
        modes = _nested_mapping(
            profile_retention,
            f"aux-input-bank.packet_retention.{profile_name}",
            "modes",
        )
        disabled_retention = _nested_mapping(
            modes, f"aux-input-bank.packet_retention.{profile_name}.modes", "DISABLED"
        )
        input_retention = _nested_mapping(
            modes, f"aux-input-bank.packet_retention.{profile_name}.modes", "INPUT"
        )
        adc_framed = _nested_mapping(
            profile,
            f"aux-input-bank.profiles.{profile_name}",
            "adc_framed_bytes_per_second",
        )
        gpio_framed_16 = _nested_mapping(
            profile,
            f"aux-input-bank.profiles.{profile_name}",
            "gpio_framed_bytes_per_second",
        )
        adc_exact = str(adc_framed.get("exact"))
        gpio_16_exact = str(gpio_framed_16.get("exact"))
        gpio_8_exact = _half_rational(
            gpio_16_exact, f"aux-input-bank.profiles.{profile_name}.gpio_framed"
        )
        profile_comparison.append(
            {
                "profile": profile_name,
                "adc_pair_rate_hz": profile.get("adc_pair_rate_hz"),
                "gpio_sample_rate_hz": profile.get("gpio_sample_rate_hz"),
                "eight_input": {
                    "gpio_width_bits": disabled_layout.get("gpio_width_bits"),
                    "adc_payload_bytes_per_second": profile.get(
                        "adc_payload_bytes_per_second"
                    ),
                    "gpio_payload_bytes_per_second": int(
                        profile.get("gpio_payload_bytes_per_second", 0)
                    )
                    // 2,
                    "combined_payload_bytes_per_second": int(
                        profile.get("adc_payload_bytes_per_second", 0)
                    )
                    + int(profile.get("gpio_payload_bytes_per_second", 0)) // 2,
                    "adc_framed_bytes_per_second_exact": adc_exact,
                    "gpio_framed_bytes_per_second_exact": gpio_8_exact,
                    "combined_framed_bytes_per_second_exact": _sum_rationals(
                        adc_exact,
                        gpio_8_exact,
                        f"aux-input-bank.profiles.{profile_name}.eight_input",
                    ),
                    "combined_retention_microseconds": disabled_retention.get(
                        "combined_retention_us"
                    ),
                },
                "sixteen_input": {
                    "gpio_width_bits": enabled_layout.get("gpio_width_bits"),
                    "adc_payload_bytes_per_second": profile.get(
                        "adc_payload_bytes_per_second"
                    ),
                    "gpio_payload_bytes_per_second": profile.get(
                        "gpio_payload_bytes_per_second"
                    ),
                    "combined_payload_bytes_per_second": profile.get(
                        "combined_payload_bytes_per_second"
                    ),
                    "adc_framed_bytes_per_second": adc_framed,
                    "gpio_framed_bytes_per_second": gpio_framed_16,
                    "combined_framed_bytes_per_second": profile.get(
                        "combined_framed_bytes_per_second"
                    ),
                    "combined_retention_microseconds": input_retention.get(
                        "combined_retention_us"
                    ),
                    "campaign_result": profile.get("campaign_result"),
                    "reason": profile.get("reason"),
                },
            }
        )

    output_host = _evidence_by_id(
        output_report, "aux-output-bank", "output-host-lifecycle"
    )
    output_resources = _evidence_by_id(
        output_report, "aux-output-bank", "output-resource-and-memory-map"
    )
    output_loopback = _evidence_by_id(
        output_report, "aux-output-bank", "protected-loopback-campaign"
    )
    output_controls = _evidence_by_id(
        output_report, "aux-output-bank", "rig-nondriving-output-controls"
    )
    output_resource_map = _nested_mapping(
        output_resources,
        "aux-output-bank.output-resource-and-memory-map",
        "resource_map",
    )
    output_memory = _nested_mapping(
        output_resources, "aux-output-bank.output-resource-and-memory-map", "memory_map"
    )
    output_safety = _nested_mapping(
        output_host, "aux-output-bank.output-host-lifecycle", "safety"
    )

    input_resources = _nested_mapping(
        input_build, "aux-input-bank.firmware-build", "pin_and_dma_resources"
    )
    _require_equal(
        input_resources.get("pins"),
        output_resource_map.get("output_pins_by_logical_bit"),
        "shared D16-D23 bank",
    )
    _require_equal(
        input_resources.get("auxiliary_edma_channel"),
        output_resource_map.get("edma_channel"),
        "shared eDMA channel",
    )
    _require_equal(
        input_resources.get("auxiliary_xbar_output"),
        output_resource_map.get("xbar_output"),
        "shared XBAR output",
    )
    protocol_hashes = {
        experiment_id: str(protocol_extensions[experiment_id]["sha256"])
        for experiment_id in (
            "rle-streaming",
            "aux-input-bank",
            "aux-output-bank",
        )
    }
    if len(set(protocol_hashes.values())) != len(protocol_hashes):
        _fail("experimental protocol-v2 contracts must remain independent")

    rle_compatibility = _evidence_by_id(
        rle_report, "rle-streaming", "protocol-v1-compatibility"
    )
    rle_host = _evidence_by_id(rle_report, "rle-streaming", "host-corpus-benchmark")
    rle_simulated = _evidence_by_id(rle_report, "rle-streaming", "simulated-rig-gate")
    rle_endurance = _evidence_by_id(
        rle_report, "rle-streaming", "physical-endurance-campaign"
    )
    rle_compression = _nested_mapping(
        rle_contract, "rle-streaming.protocol-v2", "compression"
    )
    rle_configuration = {
        "default": rle_compression.get("default_configuration_encoding"),
        "opt_in": rle_compression.get("explicit_configuration_encoding"),
        "mixed_selection_permitted": len(
            _nested_mapping(
                rle_compression,
                "rle-streaming.protocol-v2.compression",
                "configured_frame_encodings",
            ).get("RLE_AUTO", [])
        )
        == 2,
    }
    output_contract_body = _nested_mapping(
        output_contract, "aux-output-bank.protocol-v2", "auxiliary_output"
    )
    output_program = _nested_mapping(
        output_contract_body, "aux-output-bank.protocol-v2.auxiliary_output", "program"
    )

    return {
        "clock_450mhz": {
            "source": {
                "revision_commit": clock["revision_commit"],
                "source_commit": clock_identity["source_commit"],
                "evidence_id": "clock-450-physical-smoke",
                "evidence_level": "rig",
                "classification": clock.get("classification"),
            },
            "adc_resolution_bits": clock_identity["adc_resolution_bits"],
            "clock_tree_hz": {
                key: clock_profile[key]
                for key in ("cpu_hz", "ipg_hz", "adc_hz", "pit_hz")
            },
            "rates": {
                name: _metric_value(clock_report, "clock-450mhz", name)
                for name in (
                    "measurement_duration_seconds",
                    "adc_pair_rate_hz",
                    "gpio_sample_rate_hz",
                    "combined_payload_rate_bytes_per_second",
                )
            },
            "loss_and_errors": {
                "zero_error_fields": len(clock_observations["zero_error_fields"]),
                "zero_error_field_names": clock_observations["zero_error_fields"],
                "parser_errors": _metric_value(
                    clock_report, "clock-450mhz", "parser_errors"
                ),
                "transport_errors": _metric_value(
                    clock_report, "clock-450mhz", "transport_errors"
                ),
                "stop_tail": clock_observations["stop_tail"],
            },
            "phase_and_completion": {
                key: clock_observations[key]
                for key in (
                    "completion_counts",
                    "completion_median_dwt_cycles",
                    "completion_expected_dwt_cycles",
                    "completion_tolerance_dwt_cycles",
                )
            },
            "utilization_basis_points": {
                "acquisition": clock_observations[
                    "acquisition_utilization_basis_points"
                ],
                "usb": clock_observations["usb_utilization_basis_points"],
            },
            "queue_high_water_maxima": clock_observations["queue_high_water_maxima"],
            "latency_seconds": {
                "status": clock_observations["status_latency_seconds"],
                "command": clock_observations["command_latency_seconds"],
            },
            "on_chip_temperature_millidegrees_celsius": clock_observations[
                "temperature_millidegrees_celsius"
            ],
            "comparison_to_600mhz": {
                "status": "SIDE_BY_SIDE_ONLY",
                "derived_delta": None,
                "reasons": [
                    "No controlled same-board 600/450 MHz A/B campaign was executed.",
                    "The 600 MHz observation comes from a different auxiliary-output artifact and campaign.",
                    "The exact streaming durations differ, so the aggregate comparability key rejects a pooled performance result.",
                ],
                "clock_450mhz": {
                    "artifact_sha256": clock_identity["hex_sha256"],
                    "duration_seconds": _metric_value(
                        clock_report, "clock-450mhz", "measurement_duration_seconds"
                    ),
                    "adc_pair_rate_hz": _metric_value(
                        clock_report, "clock-450mhz", "adc_pair_rate_hz"
                    ),
                    "gpio_sample_rate_hz": _metric_value(
                        clock_report, "clock-450mhz", "gpio_sample_rate_hz"
                    ),
                    "packet_owned_high_water": _metric_value(
                        clock_report,
                        "clock-450mhz",
                        "packet_owned_high_water_frames",
                    ),
                    "command_latency_maximum_milliseconds": _metric_value(
                        clock_report,
                        "clock-450mhz",
                        "command_latency_maximum_milliseconds",
                    ),
                },
                "clock_600mhz_reference": {
                    "source_experiment": "aux-output-bank",
                    "artifact_sha256": output_physical["firmware_artifact_sha256"],
                    "duration_seconds": output_run["measurement_seconds"],
                    "adc_pair_rate_hz": output_run["adc_pair_rate_hz"],
                    "gpio_sample_rate_hz": output_run["gpio_sample_rate_hz"],
                    "packet_owned_high_water": output_run["packet_owned_high_water"],
                    "command_latency_maximum_milliseconds": output_run[
                        "all_commands_latency_max_ms"
                    ],
                },
            },
            "historical_528mhz_context": {
                "canonical_input": False,
                "role": "historical design context only",
                "cpu_hz": 528_000_000,
                "ipg_hz": 132_000_000,
                "adc_hz": 33_000_000,
                "pit_hz": 24_000_000,
                "adc_resolution_bits": 10,
                "source": "authorized committed clock ADR",
            },
            "unestablished": [
                item["id"]
                for item in clock_report["acceptance"]
                if item["state"] == "NOT_RUN"
            ],
        },
        "rle_streaming": {
            "source": {
                "revision_commit": rle["revision_commit"],
                "source_commit": rle_report["identity"]["source_commit"],
                "protocol_v2_sha256": rle_protocol["sha256"],
            },
            "raw_result": rle_report["result"],
            "configuration": {
                "default": rle_configuration.get("default"),
                "opt_in": rle_configuration.get("opt_in"),
                "mixed_selection_permitted": rle_configuration.get(
                    "mixed_selection_permitted"
                ),
            },
            "logical_equality": {
                "host_corpus_raw_rle_equal": all(
                    item.get("round_trip_equal") is True
                    for item in _nested_list(
                        rle_host,
                        "rle-streaming.host-corpus-benchmark",
                        "workloads",
                    )
                ),
                "physical_selected_payload_conservation": all(
                    isinstance(matched_streams.get(name), Mapping)
                    and isinstance(matched_streams[name].get("conservation"), Mapping)
                    for name in ("adc", "gpio", "combined")
                ),
                "physical_run_caveat": "RAW and RLE_AUTO live physical runs conserve their own logical payloads; changing live inputs are not asserted byte-identical across separate runs.",
            },
            "matched_physical": {
                "raw_duration_seconds": matched.get("raw_steady_seconds"),
                "rle_auto_duration_seconds": matched.get("rle_auto_steady_seconds"),
                "streams": physical_streams,
            },
            "fallback": _nested_mapping(
                rle_performance,
                "rle-streaming.physical-accepted-campaign.performance",
                "rle_auto",
                "firmware",
                "streams",
            ),
            "memory_queues_latency": {
                "raw_queue_high_waters": _nested_mapping(
                    rle_performance,
                    "rle-streaming.performance",
                    "raw",
                    "firmware",
                    "queue_high_waters",
                ),
                "rle_auto_queue_high_waters": _nested_mapping(
                    rle_performance,
                    "rle-streaming.performance",
                    "rle_auto",
                    "firmware",
                    "queue_high_waters",
                ),
                "accepted_v2_maxima": _nested_mapping(
                    rle_performance,
                    "rle-streaming.performance",
                    "accepted_v2_maxima",
                ),
                "raw_host_memory": _nested_mapping(
                    rle_performance,
                    "rle-streaming.performance",
                    "raw",
                    "host",
                    "status",
                    "memory",
                ),
                "rle_auto_host_memory": _nested_mapping(
                    rle_performance,
                    "rle-streaming.performance",
                    "rle_auto",
                    "host",
                    "status",
                    "memory",
                ),
            },
            "evidence_tiers": [
                {
                    "workload": "simulated fake-device protocol and fault cases",
                    "evidence_id": rle_simulated["id"],
                    "level": rle_simulated["level"],
                    "result": rle_simulated["result"],
                },
                {
                    "workload": "host nine-workload codec corpus",
                    "evidence_id": rle_host["id"],
                    "level": rle_host["level"],
                    "result": rle_host["result"],
                },
                {
                    "workload": "physical synthetic patterns and matched live RAW/RLE_AUTO",
                    "evidence_id": rle_physical["id"],
                    "level": rle_physical["level"],
                    "result": rle_physical["result"],
                },
            ],
            "synthetic_rig_patterns": [
                {
                    key: item.get(key)
                    for key in (
                        "pattern",
                        "complete_wire_ratios",
                        "fallback_frames",
                        "firmware_encode_load_ratio",
                        "combined_decode_bytes_per_second",
                        "packet_owned_high_water",
                        "temporary_page_high_water",
                    )
                }
                for item in _nested_list(
                    rle_physical,
                    "rle-streaming.physical-accepted-campaign",
                    "synthetic_patterns",
                )
                if isinstance(item, Mapping)
            ],
            "protocol_v1_compatibility": {
                "result": rle_compatibility["result"],
                "level": rle_compatibility["level"],
                "default_raw": rle_configuration.get("default") == "RAW",
            },
            "endurance": {
                "result": rle_endurance["result"],
                "reason": rle_endurance["reason"],
                "lifecycle": _acceptance_state(
                    rle_report, "rle-streaming", "lifecycle_complete"
                ),
                "stream_health": _acceptance_state(
                    rle_report, "rle-streaming", "stream_health"
                ),
            },
        },
        "aux_input_bank": {
            "source": {
                "revision_commit": aux_input["revision_commit"],
                "source_commit": input_report["identity"]["source_commit"],
                "protocol_v2_sha256": input_protocol["sha256"],
            },
            "raw_result": input_report["result"],
            "layouts": {
                "eight_input": disabled_layout,
                "sixteen_input": enabled_layout,
            },
            "rate_profiles": profile_comparison,
            "highest_sustained_raw_profile": input_workload.get(
                "highest_sustained_raw_profile"
            ),
            "eight_input_regression": _evidence_by_id(
                input_report, "aux-input-bank", "rig-rate-campaign"
            ).get("eight_input_regression"),
            "processing_and_queues": {
                "target_processing_load": "NOT_RUN",
                "target_queue_high_waters": "NOT_RUN",
                "host_packer_16bit_megabytes_per_second": _evidence_by_id(
                    input_report, "aux-input-bank", "host-regression"
                ).get("packer_16bit_megabytes_per_second"),
                "host_parser_minimum_headroom_ratio": _evidence_by_id(
                    input_report, "aux-input-bank", "host-regression"
                ).get("parser_minimum_headroom_ratio"),
            },
            "memory": {
                "packet_retention": retention,
                "auxiliary_workspace": input_build.get("auxiliary_workspace"),
                "raw_gpio_buffers": input_build.get("raw_gpio_buffers"),
            },
            "failure": {
                "lifecycle": _acceptance_state(
                    input_report, "aux-input-bank", "lifecycle_complete"
                ),
                "stream_health": _acceptance_state(
                    input_report, "aux-input-bank", "stream_health"
                ),
                "counter_conservation": _acceptance_state(
                    input_report, "aux-input-bank", "counter_conservation"
                ),
            },
            "electrical_transition_scope": {
                "state": "NOT_RUN",
                "classification": "ELECTRICALLY_UNSTIMULATED",
                "ungraded": [
                    "external D16-D23 pin order",
                    "transition fidelity",
                    "voltage thresholds",
                    "timing and jitter",
                    "signal integrity",
                ],
            },
        },
        "aux_output_bank": {
            "source": {
                "revision_commit": aux_output["revision_commit"],
                "source_commit": output_report["identity"]["source_commit"],
                "protocol_v2_sha256": output_protocol["sha256"],
            },
            "raw_result": output_report["result"],
            "target_output_state_rate_hz": output_resources.get(
                "target_output_state_rate_hz"
            ),
            "host_output_correctness": {
                "result": output_host["result"],
                "method": output_host["method"],
                "fresh_results": output_host["fresh_results"],
            },
            "physical_output_correctness": {
                "result": output_loopback["result"],
                "reason": output_loopback["reason"],
                "patterns": output_loopback.get("patterns"),
            },
            "loopback": {
                "lag_ticks": output_loopback.get("loopback_lag_ticks"),
                "lag_stability": output_loopback.get("loopback_lag_stability"),
            },
            "combined_adc_gpio_preservation": {
                "scope": "auxiliary output disabled",
                "result": output_physical["result"],
                "run": output_run,
            },
            "refill_margin": {
                key: output_memory[key]
                for key in (
                    "historical_maximum_service_gap_us",
                    "packet_retention_us",
                    "packet_and_usb_retention_us",
                    "packet_margin_us",
                    "packet_and_usb_margin_us",
                )
            },
            "host_lifecycle_safety": output_safety,
            "nondriving_controls": {
                "result": output_controls["result"],
                "drive_requests_written": output_controls["drive_requests_written"],
                "final_state": output_controls["final_state"],
                "output_bank_disabled": output_controls["output_bank_disabled"],
            },
            "fixture_safety_declaration": {
                "state": output_loopback["result"],
                "declaration_sha256": output_loopback["fixture_declaration_sha256"],
                "drive_exercised": False,
            },
            "independent_signal_integrity": {
                "state": "NOT_RUN",
                "required_evidence": "logic analyzer or oscilloscope",
            },
        },
        "shared_conflicts_and_synergies": [
            {
                "id": "d16_d23_whole_bank_direction",
                "classification": "CONFLICT",
                "finding": "D16-D23 are one whole bank and cannot be INPUT and OUTPUT simultaneously.",
                "inputs": ["aux-input-bank", "aux-output-bank"],
            },
            {
                "id": "dma_xbar_and_memory_ownership",
                "classification": "CONFLICT",
                "finding": "Auxiliary input and output both claim eDMA channel 3, DMAMUX source 31, XBAR output 1, and overlapping global memory/packet ownership that requires one integrated allocation.",
                "resource_identity": {
                    "edma_channel": input_resources["auxiliary_edma_channel"],
                    "dmamux_source": input_resources["auxiliary_dmamux_source"],
                    "xbar_output": input_resources["auxiliary_xbar_output"],
                    "input_packet_frames": input_build["packet_buffers"][
                        "total_frames"
                    ],
                    "output_packet_frames": output_run["packet_capacity"],
                },
                "inputs": ["aux-input-bank", "aux-output-bank"],
            },
            {
                "id": "independent_protocol_v2_extensions",
                "classification": "CONFLICT",
                "finding": "RLE, auxiliary input, and auxiliary output are three different experimental protocol-v2 contracts, not one additive negotiated contract.",
                "protocol_v2_sha256": protocol_hashes,
                "inputs": [
                    "rle-streaming",
                    "aux-input-bank",
                    "aux-output-bank",
                ],
            },
            {
                "id": "rle_terminology",
                "classification": "DISTINCTION",
                "finding": "Stream RLE_AUTO adaptively selects RAW or RLE independently per data frame; output program segments use duration/state run records for preloaded waveform expansion. They share run-length terminology but are not the same codec or wire format.",
                "stream_mode": rle_configuration.get("opt_in"),
                "output_segment_schema": output_program.get("segment_schema"),
                "inputs": ["rle-streaming", "aux-output-bank"],
            },
            {
                "id": "rate_dependent_frame_layouts",
                "classification": "INTERACTION",
                "finding": "Auxiliary INPUT changes ADC/GPIO item counts and ADC frame length while each selected rate profile changes frame coverage; any unified decoder must negotiate mode, width, frame layout, and rate together.",
                "layouts": {
                    "DISABLED": disabled_layout,
                    "INPUT": enabled_layout,
                },
                "inputs": ["aux-input-bank", "rle-streaming"],
            },
            {
                "id": "shared_raw_defaults",
                "classification": "SYNERGY",
                "finding": "Every branch retains the frozen protocol-v1 raw acquisition contract and keeps its experimental capability opt-in, providing a common rollback boundary.",
                "protocol_v1_sha256": rle_report["identity"]["protocol_sha256"],
                "inputs": [
                    "rle-streaming",
                    "aux-input-bank",
                    "aux-output-bank",
                    "clock-450mhz",
                ],
            },
            {
                "id": "combined_binary_not_tested",
                "classification": "LIMITATION",
                "finding": "Clock, RLE, auxiliary input, and auxiliary output were never built or tested together in one immutable binary.",
                "verified": False,
                "inputs": [
                    "clock-450mhz",
                    "rle-streaming",
                    "aux-input-bank",
                    "aux-output-bank",
                ],
            },
        ],
    }


def _require_acceptance_states(
    report: Mapping[str, Any],
    experiment_id: str,
    expected: Mapping[str, str],
) -> None:
    """Pin a synthesized decision to the exact acceptance states it cites."""

    for acceptance_id, state in expected.items():
        observed = _acceptance_state(report, experiment_id, acceptance_id)["state"]
        _require_equal(
            observed,
            state,
            f"{experiment_id}.recommendation_gate.{acceptance_id}",
        )


def build_recommendation_policy(
    experiments: Sequence[Mapping[str, Any]],
    cross_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive dispositions, integration order, and qualification from evidence."""

    clock = _experiment_by_id(experiments, "clock-450mhz")
    rle = _experiment_by_id(experiments, "rle-streaming")
    aux_input = _experiment_by_id(experiments, "aux-input-bank")
    aux_output = _experiment_by_id(experiments, "aux-output-bank")
    clock_report = _report_for(clock)
    rle_report = _report_for(rle)
    input_report = _report_for(aux_input)
    output_report = _report_for(aux_output)

    for report, experiment_id, expected_result in (
        (clock_report, "clock-450mhz", "PASS"),
        (rle_report, "rle-streaming", "INCONCLUSIVE"),
        (input_report, "aux-input-bank", "FAIL"),
        (output_report, "aux-output-bank", "INCONCLUSIVE"),
    ):
        _require_equal(
            report.get("result"),
            expected_result,
            f"{experiment_id}.recommendation_result",
        )

    _require_acceptance_states(
        clock_report,
        "clock-450mhz",
        {
            "physical_functional_smoke": "PASS",
            "same_board_ab_performance": "NOT_RUN",
            "endurance": "NOT_RUN",
            "analog_accuracy_aperture": "NOT_RUN",
            "power": "NOT_RUN",
            "comparative_thermal_benefit": "NOT_RUN",
            "reliability_lifetime": "NOT_RUN",
        },
    )
    _require_acceptance_states(
        rle_report,
        "rle-streaming",
        {
            "lifecycle_complete": "INCONCLUSIVE",
            "stream_health": "INCONCLUSIVE",
            "counter_conservation": "INCONCLUSIVE",
            "queue_bounds": "PASS",
            "final_idle_cleanup": "PASS",
        },
    )
    _require_acceptance_states(
        input_report,
        "aux-input-bank",
        {
            "lifecycle_complete": "FAIL",
            "synthetic_formulas_exact": "NOT_RUN",
            "stream_health": "FAIL",
            "counter_conservation": "FAIL",
            "queue_bounds": "NOT_RUN",
            "final_idle_cleanup": "PASS",
        },
    )
    _require_acceptance_states(
        output_report,
        "aux-output-bank",
        {
            "lifecycle_complete": "NOT_RUN",
            "stream_health": "PASS",
            "counter_conservation": "PASS",
            "queue_bounds": "PASS",
            "final_idle_cleanup": "PASS",
        },
    )

    authored_recommendations = [
        {
            "experiment_id": "clock-450mhz",
            "decision": "CONTINUE",
            "branch_commit": clock["revision_commit"],
            "acceptance_ids": [
                "physical_functional_smoke",
                "same_board_ab_performance",
                "endurance",
                "analog_accuracy_aperture",
                "power",
                "comparative_thermal_benefit",
                "reliability_lifetime",
            ],
            "evidence_levels": ["rig"],
            "scope": "experimental",
            "rationale": "The ten-second 12-bit physical functional smoke passed, but same-board A/B performance, endurance, externally stimulated analog accuracy/aperture, power, comparative thermal benefit, reliability, and lifetime were not run.",
        },
        {
            "experiment_id": "rle-streaming",
            "decision": "CONTINUE",
            "branch_commit": rle["revision_commit"],
            "acceptance_ids": [
                "lifecycle_complete",
                "stream_health",
                "counter_conservation",
                "queue_bounds",
                "final_idle_cleanup",
            ],
            "evidence_levels": ["host", "rig", "simulated"],
            "scope": "optional_capability",
            "rationale": "Logical conservation, bounded queues, cleanup, compatibility, and useful GPIO wire reduction passed in short runs, but the 600-second physical endurance gate remained inconclusive after upstream serial byte loss and combined-workload value did not pass.",
        },
        {
            "experiment_id": "aux-input-bank",
            "decision": "REJECT",
            "branch_commit": aux_input["revision_commit"],
            "acceptance_ids": [
                "lifecycle_complete",
                "synthetic_formulas_exact",
                "stream_health",
                "counter_conservation",
                "queue_bounds",
                "final_idle_cleanup",
            ],
            "evidence_levels": ["analytic", "host", "rig"],
            "scope": "experimental",
            "rationale": "Reject this branch artifact, not the feature concept: both physical attempts failed before START with incomplete DMA buffers and DMA errors, so no 16-input rate, queue, conservation, processing-load, or electrical-transition claim was established.",
        },
        {
            "experiment_id": "aux-output-bank",
            "decision": "CONTINUE",
            "branch_commit": aux_output["revision_commit"],
            "acceptance_ids": [
                "lifecycle_complete",
                "stream_health",
                "counter_conservation",
                "queue_bounds",
                "final_idle_cleanup",
            ],
            "evidence_levels": ["analytic", "host", "rig"],
            "scope": "optional_capability",
            "rationale": "Host lifecycle semantics and output-disabled physical acquisition passed, but the protected-loopback lifecycle, physical output correctness, lag/stability, and independent signal-integrity gates were not run because no authorized fixture declaration was available.",
        },
    ]
    recommendations = validate_recommendations(authored_recommendations, experiments)

    aux_input_analysis = _nested_mapping(
        cross_analysis, "cross_experiment_analysis", "aux_input_bank"
    )
    profiles = _nested_list(
        aux_input_analysis, "cross_experiment_analysis.aux_input_bank", "rate_profiles"
    )
    rate_profiles: list[dict[str, int | str]] = []
    for index, item in enumerate(profiles):
        if not isinstance(item, Mapping):
            _fail(f"recommendation rate_profiles[{index}]: must be an object")
        profile_id = item.get("profile")
        adc_rate = item.get("adc_pair_rate_hz")
        gpio_rate = item.get("gpio_sample_rate_hz")
        if (
            not isinstance(profile_id, str)
            or not profile_id
            or not isinstance(adc_rate, int)
            or isinstance(adc_rate, bool)
            or adc_rate <= 0
            or not isinstance(gpio_rate, int)
            or isinstance(gpio_rate, bool)
            or gpio_rate <= 0
        ):
            _fail(f"recommendation rate_profiles[{index}]: invalid exact profile")
        rate_profiles.append(
            {
                "id": profile_id,
                "adc_pair_rate_hz": adc_rate,
                "gpio_sample_rate_hz": gpio_rate,
            }
        )
    if len(rate_profiles) != 4:
        _fail("recommendation policy requires all four exact rate profiles")

    configurations = [
        {
            "id": f"450-{encoding.lower()}-{mode.lower()}-{str(profile['id']).lower()}",
            "cpu_hz": 450_000_000,
            "encoding": encoding,
            "bank_mode": mode,
            "gpio_width_bits": 16 if mode == "INPUT" else 8,
            "rate_profile": profile["id"],
            "adc_pair_rate_hz": profile["adc_pair_rate_hz"],
            "gpio_sample_rate_hz": profile["gpio_sample_rate_hz"],
            "output_rate_hz": 1_000_000 if mode == "OUTPUT" else None,
        }
        for mode in ("DISABLED", "INPUT", "OUTPUT")
        for encoding in ("RAW", "RLE_AUTO")
        for profile in rate_profiles
    ]

    return {
        "experiment_recommendations": recommendations,
        "production_defaults": {
            "decision": "RETAIN",
            "cpu_hz": 600_000_000,
            "protocol_version": 1,
            "stream_encoding": "RAW",
            "gpio_width_bits": 8,
            "auxiliary_bank_mode": "DISABLED",
            "reason": "No experimental branch has complete evidence for production-default promotion; the frozen baseline remains the rollback and compatibility boundary.",
        },
        "optional_capabilities": [
            {
                "capability": "450 MHz clock profile",
                "default": "600 MHz",
                "recommendation": "CONTINUE",
                "availability": "experimental build profile only",
            },
            {
                "capability": "RLE_AUTO stream encoding",
                "default": "RAW",
                "recommendation": "CONTINUE",
                "availability": "explicitly negotiated optional capability",
            },
            {
                "capability": "D16-D23 auxiliary input",
                "default": "DISABLED with eight-input frames",
                "recommendation": "REJECT",
                "availability": "exclude the current failed artifact; require a replacement candidate",
            },
            {
                "capability": "D16-D23 preloaded auxiliary output",
                "default": "DISABLED with high-impedance pins",
                "recommendation": "CONTINUE",
                "availability": "explicitly negotiated only after protected physical qualification",
            },
        ],
        "python_client_migration": {
            "scope": "Python-only prototype; no production client migration is authorized",
            "unchanged_path": "Protocol-v1 RAW, eight-input parsing, 600 MHz identity, and output-disabled behavior remain byte-compatible defaults.",
            "costs": [
                {
                    "area": "capability and configuration negotiation",
                    "cost": "HIGH",
                    "work": "Replace three independent experimental-v2 capability documents with one versioned capability/rate/bank-mode contract and reject unsupported combinations atomically.",
                },
                {
                    "area": "RLE_AUTO decoding",
                    "cost": "MEDIUM",
                    "work": "Dispatch each frame by negotiated encoding, validate checksum before decode, enforce canonical frame-local runs, and accept RAW fallback inside RLE_AUTO.",
                },
                {
                    "area": "rate-dependent acquisition layouts",
                    "cost": "HIGH",
                    "work": "Select ADC/GPIO item widths, counts, frame lengths, timestamps, and NumPy dtypes from negotiated mode and exact rate-profile readback.",
                },
                {
                    "area": "auxiliary output lifecycle",
                    "cost": "HIGH",
                    "work": "Add generation-aware upload, commit, arm, status, held/faulted state, STOP semantics, and explicit CLEAR without treating output program runs as stream RLE records.",
                },
            ],
        },
        "staged_integration": [
            {
                "stage": 1,
                "name": "unified protocol-v2 contract",
                "action": "Define one additive capability negotiation and one exact rate/layout/bank-mode readback contract; INPUT and OUTPUT are mutually exclusive whole-bank values.",
                "source_policy": "Reconcile the three candidate contracts; do not merge a candidate branch wholesale.",
                "exit_gate": "Generated protocol bytes, Python parser behavior, unknown-capability rejection, v1 fallback, and all legal/illegal combinations pass locally.",
            },
            {
                "stage": 2,
                "name": "non-default clock profile",
                "action": "Port only the reviewed 450 MHz clock profile behind the retained 600 MHz production build default.",
                "source_policy": "Use the 450 MHz branch as evidence and reviewed source material, not as an already qualified combined implementation.",
                "exit_gate": "Repeat exact clock/readback, phase, error, STOP/IDLE, same-board A/B, and endurance gates before promotion.",
            },
            {
                "stage": 3,
                "name": "optional RLE_AUTO",
                "action": "Integrate adaptive stream compression behind RAW default and explicit capability negotiation.",
                "source_policy": "Preserve per-frame RAW fallback and keep stream compression distinct from output-program run records.",
                "exit_gate": "Logical equality, checksum/decode ordering, fallback, load, queue, compatibility, and uninterrupted endurance pass on the integration artifact.",
            },
            {
                "stage": 4,
                "name": "exclusive auxiliary bank modes",
                "action": "Integrate output only after protected-loopback evidence passes; do not import the rejected input implementation, and admit a replacement INPUT implementation only after its pre-START DMA defect is resolved.",
                "source_policy": "Allocate eDMA channel 3, DMAMUX source 31, XBAR output 1, pins, packet memory, and priorities once in the integrated resource map.",
                "exit_gate": "Each selected mode passes its independent electrical, lifecycle, conservation, load, queue, and rollback gates while the other direction remains unavailable.",
            },
            {
                "stage": 5,
                "name": "one-artifact compound qualification",
                "action": "Freeze one new 450 MHz integration source/build/HEX identity and run the complete local, rig, and endurance matrix without changing it between configurations.",
                "source_policy": "No result from a candidate artifact may fill a missing cell for the new artifact.",
                "exit_gate": "All 24 negotiated configurations and their common/mode-specific gates pass before any combined claim.",
            },
        ],
        "compound_test_matrix": {
            "claim": "450 MHz plus RLE plus auxiliary input/output",
            "claim_interpretation": "INPUT and OUTPUT must each work with 450 MHz and RLE_AUTO on the same immutable build; they are mutually exclusive runtime modes and are never enabled simultaneously.",
            "immutable_artifact_count": 1,
            "axes": {
                "cpu_hz": [450_000_000],
                "stream_encoding": ["RAW", "RLE_AUTO"],
                "auxiliary_bank_mode": ["DISABLED", "INPUT", "OUTPUT"],
                "rate_profiles": rate_profiles,
            },
            "configuration_count": len(configurations),
            "configurations": configurations,
            "qualification_tiers": ["local", "rig_short", "rig_endurance"],
            "common_gates": [
                "one exact source/build/HEX identity across every cell",
                "unified protocol bytes and Python negotiation/parser round trip",
                "exact configured clock, rate, mode, layout, and resource readback",
                "START/STATUS/STOP/final-IDLE lifecycle",
                "zero unexplained ADC, GPIO, DMA, parser, transport, and USB loss/error counters",
                "exact frame, payload, sequence, and STOP-tail conservation",
                "bounded processing utilization, memory retention, queues, latency, and temperature",
                "600 MHz, protocol-v1, RAW, eight-input, output-disabled rollback remains independently usable",
            ],
            "mode_specific_gates": {
                "RLE_AUTO": [
                    "RAW/RLE logical equality for ADC, GPIO, and combined streams",
                    "wire savings and fallback frequency by workload",
                    "encode/decode cost and v1 compatibility",
                ],
                "INPUT": [
                    "externally stimulated D16-D23 bit mapping and transition fidelity",
                    "16-input sustained rates, framed bandwidth, processing load, retention, and queue bounds",
                    "clean whole-bank direction rollback after STOP and every injected failure",
                ],
                "OUTPUT": [
                    "authorized protected fixture and independent timing/signal-integrity capture",
                    "pattern correctness, loopback lag/stability, refill margin, and common-epoch alignment",
                    "finite completion, STOP/hold, CLEAR/high-impedance release, and injected fault behavior",
                ],
            },
        },
        "rollback_paths": [
            {
                "path": "protocol-v1 RAW",
                "preserve_until": "every unified protocol-v2 compatibility and compound-matrix gate passes",
            },
            {
                "path": "eight-input frames with D16-D23 disabled",
                "preserve_until": "INPUT and OUTPUT independently pass every rate and lifecycle cell",
            },
            {
                "path": "600 MHz production build profile",
                "preserve_until": "450 MHz passes controlled same-board comparison, endurance, and required analog/power/thermal gates",
            },
        ],
        "follow_up": {
            "classification": "human measurements and product decisions; not executable aggregation tasks or hidden approval gates",
            "manual_measurements": [
                "Run a longer same-board 600/450 MHz A/B campaign and 450 MHz endurance campaign.",
                "Apply traceable external analog stimulus to grade ADC accuracy and aperture at 450 MHz.",
                "Measure rail power and external temperature if power or comparative thermal benefit will be claimed.",
                "Stimulate D16-D23 externally to verify input mapping, voltage thresholds, transition fidelity, timing, jitter, and signal integrity on a replacement input candidate.",
                "Authorize a protected output fixture and capture output correctness, timing, lag stability, voltage levels, and signal integrity independently.",
            ],
            "user_decisions": [
                "Choose whether 450 MHz, RLE_AUTO, and auxiliary output justify continued integration investment.",
                "Choose whether to redesign the failed auxiliary-input implementation or remove INPUT from the unified contract.",
                "Choose supported rate profiles and whether optional modes must pass every profile before release.",
                "Choose fault policy and safety requirements for a combined acquisition/output product.",
            ],
        },
    }


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
    protocol_extensions = {
        item["experiment_id"]: load_protocol_extension(root, item)
        for item in report_inputs
        if item["experiment_id"]
        in {"rle-streaming", "aux-input-bank", "aux-output-bank"}
    }
    analysis, analysis_manifest = load_analysis(root, analysis_path, all_experiments)
    cross_analysis = build_cross_experiment_analysis(
        all_experiments, protocol_extensions
    )
    recommendation_policy = build_recommendation_policy(all_experiments, cross_analysis)
    if analysis["recommendations"]:
        _require_equal(
            analysis["recommendations"],
            recommendation_policy["experiment_recommendations"],
            "analysis.recommendations",
        )
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
        "cross_experiment_analysis": cross_analysis,
        "conclusions": analysis["conclusions"],
        "recommendations": recommendation_policy["experiment_recommendations"],
        "recommendation_policy": recommendation_policy,
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

    cross_analysis = aggregate.get("cross_experiment_analysis")
    if isinstance(cross_analysis, Mapping):
        clock = cross_analysis["clock_450mhz"]
        lines.extend(
            [
                "",
                "## Cross-experiment analysis",
                "",
                "### 450 MHz physical smoke",
                "",
                "| Category | Exact evidence |",
                "| --- | --- |",
                f"| Source and scope | {_markdown_cell(clock['source'])} |",
                f"| ADC resolution / clock tree | {_markdown_cell({'adc_resolution_bits': clock['adc_resolution_bits'], 'clock_tree_hz': clock['clock_tree_hz']})} |",
                f"| Acquisition rates | {_markdown_cell(clock['rates'])} |",
                f"| Loss, errors, and STOP tail | {_markdown_cell(clock['loss_and_errors'])} |",
                f"| Phase and completion | {_markdown_cell(clock['phase_and_completion'])} |",
                f"| Utilization | {_markdown_cell(clock['utilization_basis_points'])} |",
                f"| Queues and latency | {_markdown_cell({'queue_high_water_maxima': clock['queue_high_water_maxima'], 'latency_seconds': clock['latency_seconds']})} |",
                f"| On-chip temperature | {_markdown_cell(clock['on_chip_temperature_millidegrees_celsius'])} |",
                "",
                "The 450 MHz and 600 MHz observations remain side by side; no delta is calculated.",
                "",
                f"- Comparison: **{_markdown_cell(clock['comparison_to_600mhz']['status'])}** — {_markdown_cell(clock['comparison_to_600mhz']['reasons'])}",
                f"- 450 MHz: {_markdown_cell(clock['comparison_to_600mhz']['clock_450mhz'])}",
                f"- 600 MHz reference: {_markdown_cell(clock['comparison_to_600mhz']['clock_600mhz_reference'])}",
                f"- 528 MHz fallback: {_markdown_cell(clock['historical_528mhz_context'])}",
                f"- Unestablished gates: {_markdown_cell(clock['unestablished'])}",
            ]
        )

        rle = cross_analysis["rle_streaming"]
        lines.extend(
            [
                "",
                "### RAW versus RLE_AUTO",
                "",
                f"Raw result: **{_markdown_cell(rle['raw_result'])}**; configuration: {_markdown_cell(rle['configuration'])}",
                "",
                f"Logical equality boundary: {_markdown_cell(rle['logical_equality'])}",
                "",
                "| Stream | Logical bytes | RAW / selected wire bytes | Wire ratio / reduction | RAW / RLE / fallback frames (frequency) | Encode cycles / utilization delta (pp) | Decode RAW / RLE_AUTO (B/s) | Bandwidth / processing / overall |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for stream in rle["matched_physical"]["streams"]:
            lines.append(
                f"| {_markdown_cell(stream['stream'])} | {_markdown_cell(stream['logical_payload_bytes'])} | {_markdown_cell(stream['raw_complete_wire_bytes'])} / {_markdown_cell(stream['selected_complete_wire_bytes'])} | {_markdown_cell(stream['complete_wire_ratio'])} / {_markdown_cell(stream['complete_wire_reduction_ratio'])} | {_markdown_cell(stream['raw_frames'])} / {_markdown_cell(stream['rle_frames'])} / {_markdown_cell(stream['fallback_frames'])} ({_markdown_cell(stream['fallback_frequency'])}) | {_markdown_cell(stream['encode_cycles'])} / {_markdown_cell(stream['processing_utilization_delta_percentage_points'])} | {_markdown_cell(stream['raw_decode_bytes_per_second'])} / {_markdown_cell(stream['rle_auto_decode_bytes_per_second'])} | {_markdown_cell(stream['bandwidth_result'])} / {_markdown_cell(stream['processing_result'])} / **{_markdown_cell(stream['overall_value_result'])}** |"
            )
        lines.extend(
            [
                "",
                f"- Matched durations: RAW {_markdown_cell(rle['matched_physical']['raw_duration_seconds'])} s; RLE_AUTO {_markdown_cell(rle['matched_physical']['rle_auto_duration_seconds'])} s.",
                f"- Fallback detail: {_markdown_cell(rle['fallback'])}",
                f"- Memory, queues, and latency: {_markdown_cell(rle['memory_queues_latency'])}",
                f"- Evidence tiers: {_markdown_cell(rle['evidence_tiers'])}",
                f"- Synthetic rig patterns: {_markdown_cell(rle['synthetic_rig_patterns'])}",
                f"- Protocol-v1 compatibility: {_markdown_cell(rle['protocol_v1_compatibility'])}",
                f"- Endurance: {_markdown_cell(rle['endurance'])}",
            ]
        )

        aux_input = cross_analysis["aux_input_bank"]
        lines.extend(
            [
                "",
                "### Eight-input versus 16-input acquisition",
                "",
                f"Raw result: **{_markdown_cell(aux_input['raw_result'])}**. Highest sustained 16-input raw profile: {_markdown_cell(aux_input['highest_sustained_raw_profile'])}. Eight-input regression: **{_markdown_cell(aux_input['eight_input_regression'])}**.",
                "",
                "| Profile (ADC / GPIO) | Eight-input payload / framed exact / retention | 16-input payload / framed exact / retention | Campaign result |",
                "| --- | --- | --- | --- |",
            ]
        )
        for profile in aux_input["rate_profiles"]:
            eight = profile["eight_input"]
            sixteen = profile["sixteen_input"]
            eight_summary = {
                "combined_payload_bytes_per_second": eight[
                    "combined_payload_bytes_per_second"
                ],
                "combined_framed_bytes_per_second_exact": eight[
                    "combined_framed_bytes_per_second_exact"
                ],
                "combined_retention_microseconds": eight[
                    "combined_retention_microseconds"
                ],
            }
            sixteen_summary = {
                "combined_payload_bytes_per_second": sixteen[
                    "combined_payload_bytes_per_second"
                ],
                "combined_framed_bytes_per_second_exact": sixteen[
                    "combined_framed_bytes_per_second"
                ]["exact"],
                "combined_retention_microseconds": sixteen[
                    "combined_retention_microseconds"
                ],
            }
            lines.append(
                f"| {_markdown_cell(profile['profile'])} ({_markdown_cell(profile['adc_pair_rate_hz'])} / {_markdown_cell(profile['gpio_sample_rate_hz'])}) | {_markdown_cell(eight_summary)} | {_markdown_cell(sixteen_summary)} | **{_markdown_cell(sixteen['campaign_result'])}** — {_markdown_cell(sixteen['reason'])} |"
            )
        lines.extend(
            [
                "",
                f"- Frame layouts: {_markdown_cell(aux_input['layouts'])}",
                f"- Processing and queues: {_markdown_cell(aux_input['processing_and_queues'])}",
                f"- Memory retention and ownership: {_markdown_cell(aux_input['memory'])}",
                f"- Reproduced failure: {_markdown_cell(aux_input['failure'])}",
                f"- Electrical transition scope: {_markdown_cell(aux_input['electrical_transition_scope'])}",
            ]
        )

        aux_output = cross_analysis["aux_output_bank"]
        lines.extend(
            [
                "",
                "### Auxiliary output",
                "",
                "| Category | Exact evidence |",
                "| --- | --- |",
                f"| Source / raw result | {_markdown_cell(aux_output['source'])} / **{_markdown_cell(aux_output['raw_result'])}** |",
                f"| Host output correctness | {_markdown_cell(aux_output['host_output_correctness'])} |",
                f"| Output correctness | {_markdown_cell(aux_output['physical_output_correctness'])} |",
                f"| Loopback lag / stability | {_markdown_cell(aux_output['loopback'])} |",
                f"| Combined ADC/GPIO preservation | {_markdown_cell(aux_output['combined_adc_gpio_preservation'])} |",
                f"| Refill margin | {_markdown_cell(aux_output['refill_margin'])} |",
                f"| STOP / hold / CLEAR / fault behavior | {_markdown_cell(aux_output['host_lifecycle_safety'])} |",
                f"| Nondriving controls | {_markdown_cell(aux_output['nondriving_controls'])} |",
                f"| Fixture safety declaration | {_markdown_cell(aux_output['fixture_safety_declaration'])} |",
                f"| Independent signal integrity | {_markdown_cell(aux_output['independent_signal_integrity'])} |",
                "",
                "### Shared conflicts and synergies",
                "",
                "| Interaction | Classification | Finding | Exact detail |",
                "| --- | --- | --- | --- |",
            ]
        )
        for interaction in cross_analysis["shared_conflicts_and_synergies"]:
            detail = {
                key: value
                for key, value in interaction.items()
                if key not in {"id", "classification", "finding"}
            }
            lines.append(
                f"| {_markdown_cell(interaction['id'])} | **{_markdown_cell(interaction['classification'])}** | {_markdown_cell(interaction['finding'])} | {_markdown_cell(detail)} |"
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

    recommendation_policy = aggregate.get("recommendation_policy")
    if isinstance(recommendation_policy, Mapping):
        defaults = recommendation_policy["production_defaults"]
        lines.extend(
            [
                "### Production defaults and optional capabilities",
                "",
                f"Production recommendation: **{_markdown_cell(defaults['decision'])}** — {_markdown_cell(defaults['reason'])}",
                "",
                f"Retained default: {_markdown_cell({key: value for key, value in defaults.items() if key not in {'decision', 'reason'}})}",
                "",
                "| Capability | Default | Recommendation | Availability |",
                "| --- | --- | --- | --- |",
            ]
        )
        for capability in recommendation_policy["optional_capabilities"]:
            lines.append(
                f"| {_markdown_cell(capability['capability'])} | {_markdown_cell(capability['default'])} | **{_markdown_cell(capability['recommendation'])}** | {_markdown_cell(capability['availability'])} |"
            )

        migration = recommendation_policy["python_client_migration"]
        lines.extend(
            [
                "",
                "### Python client compatibility and migration cost",
                "",
                f"{_markdown_cell(migration['scope'])}. {_markdown_cell(migration['unchanged_path'])}",
                "",
                "| Area | Cost | Required prototype work |",
                "| --- | --- | --- |",
            ]
        )
        for cost in migration["costs"]:
            lines.append(
                f"| {_markdown_cell(cost['area'])} | **{_markdown_cell(cost['cost'])}** | {_markdown_cell(cost['work'])} |"
            )

        lines.extend(
            [
                "",
                "## Staged integration and rollback plan",
                "",
                "| Stage | Name | Action | Source policy | Exit gate |",
                "| ---: | --- | --- | --- | --- |",
            ]
        )
        for stage in recommendation_policy["staged_integration"]:
            lines.append(
                f"| {_markdown_cell(stage['stage'])} | {_markdown_cell(stage['name'])} | {_markdown_cell(stage['action'])} | {_markdown_cell(stage['source_policy'])} | {_markdown_cell(stage['exit_gate'])} |"
            )
        lines.extend(
            [
                "",
                "### Rollback paths",
                "",
                "| Path | Preserve until |",
                "| --- | --- |",
            ]
        )
        for rollback in recommendation_policy["rollback_paths"]:
            lines.append(
                f"| {_markdown_cell(rollback['path'])} | {_markdown_cell(rollback['preserve_until'])} |"
            )

        matrix = recommendation_policy["compound_test_matrix"]
        lines.extend(
            [
                "",
                "## Minimum compound test matrix",
                "",
                f"Claim boundary: {_markdown_cell(matrix['claim_interpretation'])}",
                "",
                f"Immutable integration artifacts: **{_markdown_cell(matrix['immutable_artifact_count'])}**. Required configurations: **{_markdown_cell(matrix['configuration_count'])}**. Qualification tiers: {_markdown_cell(matrix['qualification_tiers'])}.",
                "",
                f"Axes: {_markdown_cell(matrix['axes'])}",
                "",
                "| Configuration | Encoding | Bank mode / width | Rate profile (ADC / GPIO) | Output rate |",
                "| --- | --- | --- | --- | ---: |",
            ]
        )
        for configuration in matrix["configurations"]:
            lines.append(
                f"| {_markdown_cell(configuration['id'])} | {_markdown_cell(configuration['encoding'])} | {_markdown_cell(configuration['bank_mode'])} / {_markdown_cell(configuration['gpio_width_bits'])}-bit | {_markdown_cell(configuration['rate_profile'])} ({_markdown_cell(configuration['adc_pair_rate_hz'])} / {_markdown_cell(configuration['gpio_sample_rate_hz'])}) | {_markdown_cell(configuration['output_rate_hz'])} |"
            )
        lines.extend(["", "### Common gates", ""])
        lines.extend(f"- {_markdown_cell(gate)}" for gate in matrix["common_gates"])
        lines.extend(["", "### Mode-specific gates", ""])
        for mode, gates in matrix["mode_specific_gates"].items():
            lines.append(f"- **{_markdown_cell(mode)}**")
            lines.extend(f"  - {_markdown_cell(gate)}" for gate in gates)

        follow_up = recommendation_policy["follow_up"]
        lines.extend(
            [
                "",
                "## Human follow-up",
                "",
                f"Classification: {_markdown_cell(follow_up['classification'])}.",
                "",
                "### Manual measurements",
                "",
            ]
        )
        lines.extend(
            f"- {_markdown_cell(item)}" for item in follow_up["manual_measurements"]
        )
        lines.extend(["", "### User decisions", ""])
        lines.extend(
            f"- {_markdown_cell(item)}" for item in follow_up["user_decisions"]
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
