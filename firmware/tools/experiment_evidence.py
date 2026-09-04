#!/usr/bin/env python3
"""Validate, render, write, and check deterministic experiment evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, NoReturn

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_PATH = REPOSITORY_ROOT / "experiments/experiment-matrix.json"
PROTOCOL_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
BUILD_HELPER_PATH = REPOSITORY_ROOT / "firmware/tools/build_firmware.py"

REPORT_REQUIRED_FIELDS = {
    "schema_version",
    "matrix_schema_version",
    "experiment_id",
    "title",
    "created",
    "result",
    "reason",
    "identity",
    "evidence",
    "metrics",
    "acceptance",
    "limitations",
    "artifacts",
}
REPORT_OPTIONAL_FIELDS = {"related", "summary"}
IDENTITY_REQUIRED_FIELDS = {
    "repository",
    "branch",
    "baseline_branch",
    "baseline_commit",
    "source_commit",
    "source_tree",
    "source_clean",
    "source_id",
    "protocol_contract_path",
    "protocol_version",
    "protocol_sha256",
    "toolchains",
}
TOOLCHAIN_REQUIRED_FIELDS = {"name", "version", "identity"}
EVIDENCE_REQUIRED_FIELDS = {
    "id",
    "level",
    "result",
    "reason",
    "method",
    "command",
    "inputs",
}
CONDITIONAL_EVIDENCE_FIELDS = {
    "analytic": {"method_version"},
    "simulated": {
        "simulator_identity",
        "protocol_identity",
        "deterministic_budget",
    },
    "host": {"host_os_family", "host_architecture", "toolchain_identity"},
    "rig": {
        "hardware_serial",
        "firmware_build_id",
        "firmware_artifact_sha256",
        "fixture_declaration_sha256",
        "job_id",
    },
    "manual": {
        "procedure",
        "observer_role",
        "instrument_identity",
        "record_sha256",
    },
}
COMMAND_REQUIRED_FIELDS = {
    "argv",
    "network",
    "serial_hardware",
    "firmware_upload",
    "user_input",
}
INPUT_REQUIRED_FIELDS = {"path", "sha256"}
METRIC_REQUIRED_FIELDS = {
    "name",
    "value",
    "unit",
    "denominator",
    "scope",
    "evidence_level",
    "evidence_ids",
}
ACCEPTANCE_REQUIRED_FIELDS = {
    "id",
    "description",
    "state",
    "reason",
    "operator",
    "expected",
    "observed",
    "evidence_ids",
    "required_evidence_levels",
}
LIMITATION_REQUIRED_FIELDS = {
    "id",
    "statement",
    "applies_to_evidence_levels",
}
ARTIFACT_REQUIRED_FIELDS = {"kind", "path", "size_bytes", "sha256"}
SUPPORTED_OPERATORS = {
    "all",
    "between_inclusive",
    "byte_equal",
    "eq",
    "exact_conservation",
    "gte",
    "hash_equal",
    "lte",
    "none",
    "present",
}
MARKDOWN_REQUIRED_SECTIONS = {
    "Outcome",
    "Identity and provenance",
    "Evidence levels",
    "Metrics",
    "Acceptance",
    "Claim limitations",
    "Artifacts and reproduction",
}
BASE_WIKI_LINKS = (
    "[[Evidence-Index]]",
    "[[Protocol-V1]]",
    "[[System-Overview]]",
)
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"(?:^|[\s='\"(])[A-Za-z]:[\\/]")
UNC_PATH_PATTERN = re.compile(r"(?:^|[\s='\"(])\\\\[^\\\s]+\\")
POSIX_ABSOLUTE_PATTERN = re.compile(r"(?:^|[\s='\"(])/(?!/)[A-Za-z0-9._-]")
MUTABLE_PORT_PATTERN = re.compile(
    r"(?:^|[\s='\"(])(?:COM[0-9]+\b|/dev/(?:tty|cu\.)[^\s'\"]*)",
    re.IGNORECASE,
)
MUTABLE_IDENTIFIER_OPTION_PATTERN = re.compile(
    r"^--?(?:com-port|device-path|port|port-name|rig|rig-name|serial-port|tty)(?:$|[=_-])",
    re.IGNORECASE,
)
CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:api[_-]?key|authorization|cookie|credential|password|private[_-]?key|secret|token)\s*[:=]",
    re.IGNORECASE,
)
CREDENTIAL_OPTION_PATTERN = re.compile(
    r"^--?(?:api[-_]?key|authorization|cookie|credential|password|private[-_]?key|secret|token)(?:$|[=_-])",
    re.IGNORECASE,
)
WIKI_LINK_PATTERN = re.compile(r"^\[\[[^\[\]\r\n]+\]\]$")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "privatekey",
    "secret",
    "token",
)
MUTABLE_IDENTIFIER_KEYS = {
    "com_port",
    "device_port",
    "device_path",
    "port",
    "port_name",
    "rig_name",
    "serial_port",
    "tty",
}
HOST_IDENTITY_KEYS = {
    "cwd",
    "current_working_directory",
    "environment",
    "environment_variables",
    "hostname",
    "temporary_directory",
    "tmpdir",
    "user",
    "username",
    "working_directory",
    "workdir",
}
NONDETERMINISTIC_TIME_KEYS = {
    "current_time",
    "generated_at",
    "generated_timestamp",
    "generated_utc",
    "rendered_at",
    "rendered_utc",
}
BULK_DATA_KEYS = {
    "bulk_data",
    "capture_data",
    "environment_dump",
    "raw_data",
    "raw_samples",
    "sample_array",
    "samples",
}
MAX_STRUCTURED_LIST_ITEMS = 4096

UNIT_ALIASES = {
    "adc pair": "adc_pair",
    "adc pairs": "adc_pair",
    "adc pair/s": "adc_pair_per_second",
    "adc pairs/s": "adc_pair_per_second",
    "adc_pair/s": "adc_pair_per_second",
    "adc pair per second": "adc_pair_per_second",
    "adc pairs per second": "adc_pair_per_second",
    "bit": "bit",
    "bits": "bit",
    "byte": "byte",
    "bytes": "byte",
    "b/s": "byte_per_second",
    "byte/s": "byte_per_second",
    "bytes/s": "byte_per_second",
    "byte per second": "byte_per_second",
    "bytes per second": "byte_per_second",
    "cycle": "cycle",
    "cycles": "cycle",
    "degree celsius": "degree_celsius",
    "degrees celsius": "degree_celsius",
    "celsius": "degree_celsius",
    "event": "event",
    "events": "event",
    "frame": "frame",
    "frames": "frame",
    "gpio sample": "gpio_sample",
    "gpio samples": "gpio_sample",
    "gpio sample/s": "gpio_sample_per_second",
    "gpio samples/s": "gpio_sample_per_second",
    "gpio_sample/s": "gpio_sample_per_second",
    "gpio sample per second": "gpio_sample_per_second",
    "gpio samples per second": "gpio_sample_per_second",
    "hz": "hertz",
    "hertz": "hertz",
    "millisecond": "millisecond",
    "milliseconds": "millisecond",
    "ms": "millisecond",
    "ratio": "ratio",
    "second": "second",
    "seconds": "second",
    "s": "second",
    "tick": "tick",
    "ticks": "tick",
}


class EvidenceError(RuntimeError):
    """Base class for fail-closed evidence errors."""


class MatrixValidationError(EvidenceError):
    """The experiment matrix is malformed or internally inconsistent."""


class ReportValidationError(EvidenceError):
    """An experiment report violates the matrix contract."""


class EvidenceDriftError(EvidenceError):
    """A checked artifact is missing, stale, or nondeterministic."""


@dataclass(frozen=True, slots=True)
class ExperimentMatrix:
    """Validated experiment contract plus stable lookup indexes."""

    path: Path
    data: dict[str, Any]
    metric_definitions: dict[str, dict[str, Any]]
    acceptance_checks: dict[str, dict[str, Any]]
    claim_limitations: dict[str, dict[str, Any]]
    experiments: dict[str, dict[str, Any]]
    metric_order: dict[str, int]
    acceptance_order: dict[str, int]
    limitation_order: dict[str, int]
    evidence_level_order: dict[str, int]

    @property
    def schema_version(self) -> int:
        """Return the matrix schema version."""

        return int(self.data["schema_version"])

    @property
    def report_contract(self) -> dict[str, Any]:
        """Return the validated report contract."""

        return _mapping(self.data, "report_contract", MatrixValidationError)

    def experiment(self, experiment_id: str) -> dict[str, Any]:
        """Return one declared experiment or reject an unknown identifier."""

        try:
            return self.experiments[experiment_id]
        except KeyError as error:
            raise ReportValidationError(
                f"experiment_id is not declared by the matrix: {experiment_id!r}"
            ) from error

    def expected_paths(self, experiment_id: str) -> tuple[str, str]:
        """Return the canonical JSON and Markdown paths for an experiment."""

        experiment = self.experiment(experiment_id)
        artifact_id = _text(experiment, "artifact", ReportValidationError)
        artifacts = _mapping(self.data, "expected_artifacts", MatrixValidationError)
        artifact = _mapping(artifacts, artifact_id, MatrixValidationError)
        return (
            _text(artifact, "json", MatrixValidationError),
            _text(artifact, "markdown", MatrixValidationError),
        )


def _raise(error_type: type[EvidenceError], location: str, detail: str) -> NoReturn:
    raise error_type(f"{location}: {detail}")


def _mapping(
    owner: Mapping[str, Any],
    name: str,
    error_type: type[EvidenceError],
    *,
    location: str | None = None,
) -> dict[str, Any]:
    value = owner.get(name)
    if not isinstance(value, dict):
        _raise(error_type, location or name, "must be an object")
    return value


def _list(
    owner: Mapping[str, Any],
    name: str,
    error_type: type[EvidenceError],
    *,
    location: str | None = None,
) -> list[Any]:
    value = owner.get(name)
    if not isinstance(value, list):
        _raise(error_type, location or name, "must be an array")
    return value


def _text(
    owner: Mapping[str, Any],
    name: str,
    error_type: type[EvidenceError],
    *,
    location: str | None = None,
) -> str:
    value = owner.get(name)
    if not isinstance(value, str) or not value.strip():
        _raise(error_type, location or name, "must be non-empty text")
    return value


def _integer(
    owner: Mapping[str, Any],
    name: str,
    error_type: type[EvidenceError],
    *,
    minimum: int | None = None,
    location: str | None = None,
) -> int:
    value = owner.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        _raise(error_type, location or name, "must be an integer")
    if minimum is not None and value < minimum:
        _raise(error_type, location or name, f"must be at least {minimum}")
    return value


def _boolean(
    owner: Mapping[str, Any],
    name: str,
    error_type: type[EvidenceError],
    *,
    location: str | None = None,
) -> bool:
    value = owner.get(name)
    if not isinstance(value, bool):
        _raise(error_type, location or name, "must be true or false")
    return value


def _string_list(
    owner: Mapping[str, Any],
    name: str,
    error_type: type[EvidenceError],
    *,
    nonempty: bool = False,
    location: str | None = None,
) -> list[str]:
    raw = _list(owner, name, error_type, location=location)
    if nonempty and not raw:
        _raise(error_type, location or name, "must not be empty")
    result: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            _raise(
                error_type,
                f"{location or name}[{index}]",
                "must be non-empty text",
            )
        result.append(value)
    return result


def _require_fields(
    value: Mapping[str, Any],
    required: Sequence[str],
    error_type: type[EvidenceError],
    location: str,
) -> None:
    missing = [name for name in required if name not in value]
    if missing:
        _raise(error_type, location, "missing required fields: " + ", ".join(missing))


def _unique(
    values: Sequence[str], error_type: type[EvidenceError], location: str
) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        _raise(error_type, location, "contains duplicates: " + ", ".join(duplicates))


def _require_exact_names(
    values: Sequence[str],
    expected: set[str],
    error_type: type[EvidenceError],
    location: str,
) -> None:
    observed = set(values)
    if observed == expected:
        return
    details: list[str] = []
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unsupported " + ", ".join(extra))
    _raise(error_type, location, "; ".join(details))


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def load_json_object(
    path: Path,
    *,
    error_type: type[EvidenceError] = ReportValidationError,
) -> dict[str, Any]:
    """Load one strict JSON object, rejecting duplicates and non-finite numbers."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise error_type(f"could not load {path}: {error}") from error
    if not isinstance(value, dict):
        raise error_type(f"{path} must contain one JSON object")
    return value


def sha256_file(path: Path) -> str:
    """Hash a file without loading bulk artifacts into memory."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def canonical_json_text(value: object) -> str:
    """Serialize deterministic, human-readable JSON with a final newline."""

    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except (TypeError, ValueError) as error:
        raise ReportValidationError(
            f"report is not finite JSON data: {error}"
        ) from error


def normalize_metric_name(name: str) -> str:
    """Normalize a human-entered metric name to the contract's snake case."""

    if not isinstance(name, str) or not name.strip():
        raise ReportValidationError("metric name must be non-empty text")
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().casefold()).strip("_")
    if not normalized:
        raise ReportValidationError(f"metric name has no identifier content: {name!r}")
    return normalized


def normalize_unit(unit: str) -> str:
    """Normalize unambiguous spelling aliases without converting magnitudes."""

    if not isinstance(unit, str) or not unit.strip():
        raise ReportValidationError("metric unit must be non-empty text")
    candidate = unit.strip().casefold().replace("°", "degree ")
    candidate = re.sub(r"\s+", " ", candidate)
    if candidate in UNIT_ALIASES:
        return UNIT_ALIASES[candidate]
    return re.sub(r"[^a-z0-9]+", "_", candidate).strip("_")


def validate_repository_relative_path(
    value: object,
    location: str,
    *,
    error_type: type[EvidenceError] = ReportValidationError,
) -> str:
    """Return a canonical repository-relative POSIX path or reject it."""

    if not isinstance(value, str) or not value:
        _raise(error_type, location, "must be a non-empty repository-relative path")
    if "\\" in value or "://" in value or value.startswith("file:"):
        _raise(error_type, location, "must use repository-relative POSIX syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        _raise(error_type, location, "must be a normalized relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        _raise(error_type, location, "may not contain empty, dot, or parent segments")
    if CONTROL_CHARACTER_PATTERN.search(value):
        _raise(error_type, location, "contains a control character")
    return value


def _validate_matrix_artifact_paths(
    artifacts: Mapping[str, Any],
    location: str,
) -> None:
    seen: set[str] = set()
    for artifact_id, raw in artifacts.items():
        if not isinstance(artifact_id, str) or not SLUG_PATTERN.fullmatch(artifact_id):
            _raise(
                MatrixValidationError, location, f"invalid artifact id {artifact_id!r}"
            )
        if not isinstance(raw, dict):
            _raise(
                MatrixValidationError, f"{location}.{artifact_id}", "must be an object"
            )
        _require_fields(
            raw,
            ("json", "markdown"),
            MatrixValidationError,
            f"{location}.{artifact_id}",
        )
        json_path = validate_repository_relative_path(
            raw["json"],
            f"{location}.{artifact_id}.json",
            error_type=MatrixValidationError,
        )
        markdown_path = validate_repository_relative_path(
            raw["markdown"],
            f"{location}.{artifact_id}.markdown",
            error_type=MatrixValidationError,
        )
        if not json_path.endswith(".json") or not markdown_path.endswith(".md"):
            _raise(
                MatrixValidationError,
                f"{location}.{artifact_id}",
                "must pair .json and .md outputs",
            )
        if json_path[:-5] != markdown_path[:-3]:
            _raise(
                MatrixValidationError,
                f"{location}.{artifact_id}",
                "JSON and Markdown output stems differ",
            )
        for selected in (json_path, markdown_path):
            if selected in seen:
                _raise(
                    MatrixValidationError,
                    location,
                    f"duplicate output path {selected!r}",
                )
            seen.add(selected)


def validate_experiment_matrix(
    value: Mapping[str, Any],
    *,
    path: Path = DEFAULT_MATRIX_PATH,
) -> ExperimentMatrix:
    """Validate every cross-reference needed to interpret an evidence report."""

    if not isinstance(value, dict):
        raise MatrixValidationError("experiment matrix must be an object")
    _require_fields(
        value,
        (
            "schema_version",
            "kind",
            "project",
            "result_states",
            "result_state_semantics",
            "evidence_levels",
            "evidence_level_semantics",
            "branches",
            "expected_artifacts",
            "intermediate_artifacts",
            "metric_definitions",
            "acceptance_checks",
            "claim_limitations",
            "experiments",
            "report_contract",
        ),
        MatrixValidationError,
        "matrix",
    )
    schema_version = _integer(value, "schema_version", MatrixValidationError, minimum=1)
    if _text(value, "kind", MatrixValidationError) != "thingdaq-experiment-matrix":
        _raise(MatrixValidationError, "kind", "is not thingdaq-experiment-matrix")
    _text(value, "project", MatrixValidationError)

    result_states = _string_list(
        value, "result_states", MatrixValidationError, nonempty=True
    )
    _unique(result_states, MatrixValidationError, "result_states")
    if set(result_states) != {"PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"}:
        _raise(
            MatrixValidationError, "result_states", "must define the four common states"
        )
    result_semantics = _mapping(value, "result_state_semantics", MatrixValidationError)
    if set(result_semantics) != set(result_states):
        _raise(
            MatrixValidationError,
            "result_state_semantics",
            "keys must exactly match result_states",
        )
    for state in result_states:
        semantics = _mapping(
            result_semantics,
            state,
            MatrixValidationError,
            location=f"result_state_semantics.{state}",
        )
        _text(
            semantics,
            "meaning",
            MatrixValidationError,
            location=f"result_state_semantics.{state}.meaning",
        )
        _boolean(
            semantics,
            "reason_required",
            MatrixValidationError,
            location=f"result_state_semantics.{state}.reason_required",
        )
        _boolean(
            semantics,
            "reason_must_be_null",
            MatrixValidationError,
            location=f"result_state_semantics.{state}.reason_must_be_null",
        )

    evidence_levels = _string_list(
        value, "evidence_levels", MatrixValidationError, nonempty=True
    )
    _unique(evidence_levels, MatrixValidationError, "evidence_levels")
    evidence_semantics = _mapping(
        value, "evidence_level_semantics", MatrixValidationError
    )
    semantics_keys = {key for key in evidence_semantics if key != "ordering_policy"}
    if semantics_keys != set(evidence_levels):
        _raise(
            MatrixValidationError,
            "evidence_level_semantics",
            "level keys must exactly match evidence_levels",
        )
    for level in evidence_levels:
        semantics = _mapping(
            evidence_semantics,
            level,
            MatrixValidationError,
            location=f"evidence_level_semantics.{level}",
        )
        _text(
            semantics,
            "meaning",
            MatrixValidationError,
            location=f"evidence_level_semantics.{level}.meaning",
        )
        _boolean(
            semantics,
            "physical_claims_allowed",
            MatrixValidationError,
            location=f"evidence_level_semantics.{level}.physical_claims_allowed",
        )

    branches = _mapping(value, "branches", MatrixValidationError)
    baseline_branch = _text(branches, "baseline", MatrixValidationError)
    candidate_branches = _string_list(
        branches, "candidates", MatrixValidationError, nonempty=True
    )
    if _text(branches, "candidate_base", MatrixValidationError) != baseline_branch:
        _raise(MatrixValidationError, "branches.candidate_base", "must name baseline")
    _unique([baseline_branch, *candidate_branches], MatrixValidationError, "branches")

    expected_artifacts = _mapping(value, "expected_artifacts", MatrixValidationError)
    intermediate_artifacts = _mapping(
        value, "intermediate_artifacts", MatrixValidationError
    )
    _validate_matrix_artifact_paths(expected_artifacts, "expected_artifacts")
    _validate_matrix_artifact_paths(intermediate_artifacts, "intermediate_artifacts")

    contract = _mapping(value, "report_contract", MatrixValidationError)
    if _integer(contract, "schema_version", MatrixValidationError, minimum=1) != 1:
        _raise(MatrixValidationError, "report_contract.schema_version", "unsupported")
    required_report_fields = _string_list(
        contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(
        required_report_fields, MatrixValidationError, "report_contract.required_fields"
    )
    _require_exact_names(
        required_report_fields,
        REPORT_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.required_fields",
    )

    identity_contract = _mapping(contract, "identity", MatrixValidationError)
    identity_required = _string_list(
        identity_contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(
        identity_required,
        MatrixValidationError,
        "report_contract.identity.required_fields",
    )
    _require_exact_names(
        identity_required,
        IDENTITY_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.identity.required_fields",
    )
    toolchain_required = _string_list(
        identity_contract,
        "toolchain_record_required_fields",
        MatrixValidationError,
        nonempty=True,
    )
    _unique(
        toolchain_required,
        MatrixValidationError,
        "report_contract.identity.toolchain_record_required_fields",
    )
    _require_exact_names(
        toolchain_required,
        TOOLCHAIN_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.identity.toolchain_record_required_fields",
    )
    if (
        _text(identity_contract, "repository", MatrixValidationError).startswith("http")
        is False
    ):
        _raise(
            MatrixValidationError,
            "report_contract.identity.repository",
            "must be an HTTP(S) URL",
        )
    try:
        re.compile(
            _text(identity_contract, "git_object_pattern", MatrixValidationError)
        )
        re.compile(_text(identity_contract, "sha256_pattern", MatrixValidationError))
    except re.error as error:
        raise MatrixValidationError(f"identity pattern is invalid: {error}") from error

    evidence_contract = _mapping(contract, "evidence_record", MatrixValidationError)
    evidence_required = _string_list(
        evidence_contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(
        evidence_required,
        MatrixValidationError,
        "report_contract.evidence_record.required_fields",
    )
    _require_exact_names(
        evidence_required,
        EVIDENCE_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.evidence_record.required_fields",
    )
    command_required = _string_list(
        evidence_contract,
        "command_required_fields",
        MatrixValidationError,
        nonempty=True,
    )
    _unique(command_required, MatrixValidationError, "evidence command fields")
    _require_exact_names(
        command_required,
        COMMAND_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.evidence_record.command_required_fields",
    )
    input_required = _string_list(
        evidence_contract,
        "input_record_required_fields",
        MatrixValidationError,
        nonempty=True,
    )
    _unique(input_required, MatrixValidationError, "evidence input fields")
    _require_exact_names(
        input_required,
        INPUT_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.evidence_record.input_record_required_fields",
    )
    conditional = _mapping(
        evidence_contract, "conditional_identity_fields", MatrixValidationError
    )
    if set(conditional) != set(evidence_levels):
        _raise(
            MatrixValidationError,
            "evidence_record.conditional_identity_fields",
            "must cover every evidence level exactly",
        )
    for level in evidence_levels:
        fields = _string_list(conditional, level, MatrixValidationError, nonempty=True)
        if level not in CONDITIONAL_EVIDENCE_FIELDS:
            _raise(
                MatrixValidationError,
                f"evidence_record.conditional_identity_fields.{level}",
                "is not implemented",
            )
        _require_exact_names(
            fields,
            CONDITIONAL_EVIDENCE_FIELDS[level],
            MatrixValidationError,
            f"evidence_record.conditional_identity_fields.{level}",
        )

    metric_contract = _mapping(contract, "metric_record", MatrixValidationError)
    metric_required = _string_list(
        metric_contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(metric_required, MatrixValidationError, "metric required fields")
    _require_exact_names(
        metric_required,
        METRIC_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.metric_record.required_fields",
    )
    allowed_units = set(
        _string_list(
            metric_contract, "allowed_units", MatrixValidationError, nonempty=True
        )
    )
    allowed_denominators = set(
        _string_list(
            metric_contract,
            "allowed_denominators",
            MatrixValidationError,
            nonempty=True,
        )
    )
    comparability_key = _string_list(
        metric_contract, "comparability_key", MatrixValidationError, nonempty=True
    )
    if not set(comparability_key).issubset(set(metric_required)):
        _raise(
            MatrixValidationError,
            "metric_record.comparability_key",
            "uses an unknown field",
        )

    acceptance_contract = _mapping(contract, "acceptance_record", MatrixValidationError)
    acceptance_required = _string_list(
        acceptance_contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(acceptance_required, MatrixValidationError, "acceptance required fields")
    _require_exact_names(
        acceptance_required,
        ACCEPTANCE_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.acceptance_record.required_fields",
    )
    allowed_operators = set(
        _string_list(
            acceptance_contract,
            "allowed_operators",
            MatrixValidationError,
            nonempty=True,
        )
    )
    if allowed_operators != SUPPORTED_OPERATORS:
        _raise(
            MatrixValidationError,
            "report_contract.acceptance_record.allowed_operators",
            "does not match the implemented operators",
        )
    limitation_contract = _mapping(contract, "limitation_record", MatrixValidationError)
    limitation_required = _string_list(
        limitation_contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(limitation_required, MatrixValidationError, "limitation required fields")
    _require_exact_names(
        limitation_required,
        LIMITATION_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.limitation_record.required_fields",
    )
    artifact_contract = _mapping(contract, "artifact_record", MatrixValidationError)
    artifact_required = _string_list(
        artifact_contract, "required_fields", MatrixValidationError, nonempty=True
    )
    _unique(artifact_required, MatrixValidationError, "artifact required fields")
    _require_exact_names(
        artifact_required,
        ARTIFACT_REQUIRED_FIELDS,
        MatrixValidationError,
        "report_contract.artifact_record.required_fields",
    )

    rollup = _mapping(contract, "result_rollup", MatrixValidationError)
    if set(rollup) != {
        *result_states,
        "unknown_or_missing_state",
        "presentation_may_override_validation",
    }:
        _raise(
            MatrixValidationError,
            "report_contract.result_rollup",
            "must define every state and fail-closed presentation policy",
        )
    if rollup.get("presentation_may_override_validation") is not False:
        _raise(
            MatrixValidationError,
            "report_contract.result_rollup.presentation_may_override_validation",
            "must be false",
        )
    markdown_contract = _mapping(contract, "markdown", MatrixValidationError)
    if markdown_contract.get("front_matter_required") is not True:
        _raise(
            MatrixValidationError,
            "report_contract.markdown.front_matter_required",
            "must be true",
        )
    front_matter_fields = _string_list(
        markdown_contract,
        "front_matter_fields",
        MatrixValidationError,
        nonempty=True,
    )
    _require_exact_names(
        front_matter_fields,
        {"type", "title", "created", "tags", "related"},
        MatrixValidationError,
        "report_contract.markdown.front_matter_fields",
    )
    if markdown_contract.get("front_matter_type") != "report":
        _raise(
            MatrixValidationError,
            "report_contract.markdown.front_matter_type",
            "must be report",
        )
    required_sections = _string_list(
        markdown_contract,
        "required_sections",
        MatrixValidationError,
        nonempty=True,
    )
    _require_exact_names(
        required_sections,
        MARKDOWN_REQUIRED_SECTIONS,
        MatrixValidationError,
        "report_contract.markdown.required_sections",
    )
    for policy in ("render_from_validated_data_only", "stable_table_order_required"):
        if markdown_contract.get(policy) is not True:
            _raise(
                MatrixValidationError,
                f"report_contract.markdown.{policy}",
                "must be true",
            )
    content_policy = _mapping(contract, "content_policy", MatrixValidationError)
    required_false_policies = (
        "parent_path_segments_allowed",
        "file_uris_allowed",
        "absolute_posix_paths_allowed",
        "absolute_windows_paths_allowed",
        "credential_values_allowed",
        "mutable_port_identifiers_allowed",
        "mutable_rig_names_allowed",
        "hostnames_allowed",
        "usernames_allowed",
        "working_directories_allowed",
        "temporary_paths_allowed",
        "environment_dumps_allowed",
        "bulk_payloads_allowed",
        "raw_sample_arrays_allowed",
        "output_path_self_references_allowed",
        "nondeterministic_generated_timestamps_allowed",
    )
    if content_policy.get("repository_relative_paths_only") is not True:
        _raise(
            MatrixValidationError,
            "report_contract.content_policy.repository_relative_paths_only",
            "must be true",
        )
    for policy in required_false_policies:
        if content_policy.get(policy) is not False:
            _raise(
                MatrixValidationError,
                f"report_contract.content_policy.{policy}",
                "must be false",
            )

    raw_metrics = _list(value, "metric_definitions", MatrixValidationError)
    if not raw_metrics:
        _raise(MatrixValidationError, "metric_definitions", "must not be empty")
    metric_definitions: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_metrics):
        location = f"metric_definitions[{index}]"
        if not isinstance(raw, dict):
            _raise(MatrixValidationError, location, "must be an object")
        _require_fields(
            raw,
            (
                "name",
                "description",
                "value_type",
                "unit",
                "denominator",
                "scope",
                "allowed_evidence_levels",
                "comparison_group",
            ),
            MatrixValidationError,
            location,
        )
        name = _text(raw, "name", MatrixValidationError, location=f"{location}.name")
        if name != normalize_metric_name(name) or not SLUG_PATTERN.fullmatch(name):
            _raise(
                MatrixValidationError, f"{location}.name", "must be a normalized slug"
            )
        if name in metric_definitions:
            _raise(MatrixValidationError, location, f"duplicate metric {name!r}")
        _text(
            raw,
            "description",
            MatrixValidationError,
            location=f"{location}.description",
        )
        if _text(raw, "value_type", MatrixValidationError) not in {"integer", "number"}:
            _raise(
                MatrixValidationError,
                f"{location}.value_type",
                "must be integer or number",
            )
        unit = _text(raw, "unit", MatrixValidationError)
        denominator = _text(raw, "denominator", MatrixValidationError)
        if unit not in allowed_units:
            _raise(MatrixValidationError, f"{location}.unit", "is not allowed")
        if denominator not in allowed_denominators:
            _raise(MatrixValidationError, f"{location}.denominator", "is not allowed")
        _text(raw, "scope", MatrixValidationError, location=f"{location}.scope")
        levels = _string_list(
            raw, "allowed_evidence_levels", MatrixValidationError, nonempty=True
        )
        _unique(levels, MatrixValidationError, f"{location}.allowed_evidence_levels")
        if not set(levels).issubset(set(evidence_levels)):
            _raise(
                MatrixValidationError,
                f"{location}.allowed_evidence_levels",
                "contains an unknown level",
            )
        _text(
            raw,
            "comparison_group",
            MatrixValidationError,
            location=f"{location}.comparison_group",
        )
        metric_definitions[name] = raw

    raw_checks = _list(value, "acceptance_checks", MatrixValidationError)
    if not raw_checks:
        _raise(MatrixValidationError, "acceptance_checks", "must not be empty")
    acceptance_checks: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_checks):
        location = f"acceptance_checks[{index}]"
        if not isinstance(raw, dict):
            _raise(MatrixValidationError, location, "must be an object")
        _require_fields(
            raw,
            ("id", "description", "required_evidence_levels", "operator"),
            MatrixValidationError,
            location,
        )
        check_id = _text(raw, "id", MatrixValidationError, location=f"{location}.id")
        if not SLUG_PATTERN.fullmatch(check_id) or check_id in acceptance_checks:
            _raise(MatrixValidationError, f"{location}.id", "must be a unique slug")
        _text(
            raw,
            "description",
            MatrixValidationError,
            location=f"{location}.description",
        )
        levels = _string_list(
            raw, "required_evidence_levels", MatrixValidationError, nonempty=True
        )
        _unique(levels, MatrixValidationError, f"{location}.required_evidence_levels")
        if not set(levels).issubset(set(evidence_levels)):
            _raise(
                MatrixValidationError,
                f"{location}.required_evidence_levels",
                "contains an unknown level",
            )
        if _text(raw, "operator", MatrixValidationError) not in allowed_operators:
            _raise(MatrixValidationError, f"{location}.operator", "is not allowed")
        acceptance_checks[check_id] = raw

    raw_limitations = _list(value, "claim_limitations", MatrixValidationError)
    if not raw_limitations:
        _raise(MatrixValidationError, "claim_limitations", "must not be empty")
    claim_limitations: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_limitations):
        location = f"claim_limitations[{index}]"
        if not isinstance(raw, dict):
            _raise(MatrixValidationError, location, "must be an object")
        _require_fields(
            raw,
            ("id", "statement", "applies_to_evidence_levels"),
            MatrixValidationError,
            location,
        )
        limitation_id = _text(
            raw, "id", MatrixValidationError, location=f"{location}.id"
        )
        if (
            not SLUG_PATTERN.fullmatch(limitation_id)
            or limitation_id in claim_limitations
        ):
            _raise(MatrixValidationError, f"{location}.id", "must be a unique slug")
        _text(raw, "statement", MatrixValidationError, location=f"{location}.statement")
        levels = _string_list(
            raw, "applies_to_evidence_levels", MatrixValidationError, nonempty=True
        )
        _unique(levels, MatrixValidationError, f"{location}.applies_to_evidence_levels")
        if not set(levels).issubset(set(evidence_levels)):
            _raise(
                MatrixValidationError,
                f"{location}.applies_to_evidence_levels",
                "contains an unknown level",
            )
        claim_limitations[limitation_id] = raw

    raw_experiments = _list(value, "experiments", MatrixValidationError)
    if not raw_experiments:
        _raise(MatrixValidationError, "experiments", "must not be empty")
    experiments: dict[str, dict[str, Any]] = {}
    artifact_ids = set(expected_artifacts)
    intermediate_ids = set(intermediate_artifacts)
    for index, raw in enumerate(raw_experiments):
        location = f"experiments[{index}]"
        if not isinstance(raw, dict):
            _raise(MatrixValidationError, location, "must be an object")
        _require_fields(
            raw,
            (
                "id",
                "title",
                "role",
                "branch",
                "base_branch",
                "artifact",
                "required_acceptance_checks",
                "required_limitations",
                "candidate_thresholds",
            ),
            MatrixValidationError,
            location,
        )
        experiment_id = _text(
            raw, "id", MatrixValidationError, location=f"{location}.id"
        )
        if not SLUG_PATTERN.fullmatch(experiment_id) or experiment_id in experiments:
            _raise(MatrixValidationError, f"{location}.id", "must be a unique slug")
        _text(raw, "title", MatrixValidationError, location=f"{location}.title")
        role = _text(raw, "role", MatrixValidationError, location=f"{location}.role")
        if role not in {"baseline", "candidate"}:
            _raise(
                MatrixValidationError,
                f"{location}.role",
                "must be baseline or candidate",
            )
        branch = _text(
            raw, "branch", MatrixValidationError, location=f"{location}.branch"
        )
        base_branch = _text(
            raw,
            "base_branch",
            MatrixValidationError,
            location=f"{location}.base_branch",
        )
        if role == "baseline" and branch != baseline_branch:
            _raise(
                MatrixValidationError,
                f"{location}.branch",
                "does not match branches.baseline",
            )
        if role == "baseline" and base_branch != "main":
            _raise(
                MatrixValidationError,
                f"{location}.base_branch",
                "the baseline must descend from main",
            )
        if role == "candidate" and branch not in candidate_branches:
            _raise(
                MatrixValidationError, f"{location}.branch", "is not a candidate branch"
            )
        if role == "candidate" and base_branch != baseline_branch:
            _raise(
                MatrixValidationError,
                f"{location}.base_branch",
                "candidates must descend from the baseline branch",
            )
        artifact_id = _text(
            raw, "artifact", MatrixValidationError, location=f"{location}.artifact"
        )
        if artifact_id not in artifact_ids:
            _raise(
                MatrixValidationError,
                f"{location}.artifact",
                "is not an expected artifact",
            )
        checks = _string_list(
            raw, "required_acceptance_checks", MatrixValidationError, nonempty=True
        )
        _unique(checks, MatrixValidationError, f"{location}.required_acceptance_checks")
        if not set(checks).issubset(acceptance_checks):
            _raise(
                MatrixValidationError,
                f"{location}.required_acceptance_checks",
                "contains an unknown check",
            )
        limitations = _string_list(
            raw, "required_limitations", MatrixValidationError, nonempty=True
        )
        _unique(limitations, MatrixValidationError, f"{location}.required_limitations")
        if not set(limitations).issubset(claim_limitations):
            _raise(
                MatrixValidationError,
                f"{location}.required_limitations",
                "contains an unknown limitation",
            )
        raw_intermediate = raw.get("intermediate_artifacts", [])
        if not isinstance(raw_intermediate, list) or not all(
            isinstance(item, str) for item in raw_intermediate
        ):
            _raise(
                MatrixValidationError,
                f"{location}.intermediate_artifacts",
                "must be an array of ids",
            )
        if not set(raw_intermediate).issubset(intermediate_ids):
            _raise(
                MatrixValidationError,
                f"{location}.intermediate_artifacts",
                "contains an unknown artifact",
            )
        raw_links = raw.get("required_wiki_links", [])
        if not isinstance(raw_links, list) or not all(
            isinstance(link, str) and WIKI_LINK_PATTERN.fullmatch(link)
            for link in raw_links
        ):
            _raise(
                MatrixValidationError,
                f"{location}.required_wiki_links",
                "contains an invalid wiki-link",
            )
        experiments[experiment_id] = raw

    if schema_version != int(value["schema_version"]):
        _raise(MatrixValidationError, "schema_version", "changed during validation")
    return ExperimentMatrix(
        path=path,
        data=dict(value),
        metric_definitions=metric_definitions,
        acceptance_checks=acceptance_checks,
        claim_limitations=claim_limitations,
        experiments=experiments,
        metric_order={name: index for index, name in enumerate(metric_definitions)},
        acceptance_order={name: index for index, name in enumerate(acceptance_checks)},
        limitation_order={name: index for index, name in enumerate(claim_limitations)},
        evidence_level_order={
            name: index for index, name in enumerate(evidence_levels)
        },
    )


def load_experiment_matrix(path: Path = DEFAULT_MATRIX_PATH) -> ExperimentMatrix:
    """Load and fully validate the machine-readable experiment contract."""

    value = load_json_object(path, error_type=MatrixValidationError)
    return validate_experiment_matrix(value, path=path)


def _state_reason(
    matrix: ExperimentMatrix,
    state: object,
    reason: object,
    location: str,
) -> str:
    states = matrix.data["result_states"]
    if not isinstance(state, str) or state not in states:
        _raise(
            ReportValidationError,
            f"{location}.state",
            f"unknown result state {state!r}",
        )
    semantics = _mapping(
        _mapping(matrix.data, "result_state_semantics", MatrixValidationError),
        state,
        MatrixValidationError,
    )
    if semantics["reason_must_be_null"] is True:
        if reason is not None:
            _raise(
                ReportValidationError, f"{location}.reason", f"must be null for {state}"
            )
    elif semantics["reason_required"] is True:
        if not isinstance(reason, str) or not reason.strip():
            _raise(
                ReportValidationError, f"{location}.reason", f"is required for {state}"
            )
    elif reason is not None and (not isinstance(reason, str) or not reason.strip()):
        _raise(
            ReportValidationError,
            f"{location}.reason",
            "must be null or non-empty text",
        )
    return state


def _canonical_level_list(matrix: ExperimentMatrix, values: Sequence[str]) -> list[str]:
    return sorted(
        values, key=lambda level: matrix.evidence_level_order.get(level, 10**9)
    )


def normalize_report(
    matrix: ExperimentMatrix,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalize safe aliases and all semantically unordered report arrays."""

    if not isinstance(report, Mapping):
        raise ReportValidationError("report must be an object")
    normalized = copy.deepcopy(dict(report))

    identity = normalized.get("identity")
    if isinstance(identity, dict):
        toolchains = identity.get("toolchains")
        if isinstance(toolchains, list):
            toolchains.sort(
                key=lambda item: (
                    str(item.get("name", "")) if isinstance(item, dict) else "",
                    str(item.get("version", "")) if isinstance(item, dict) else "",
                    str(item.get("identity", "")) if isinstance(item, dict) else "",
                )
            )

    evidence = normalized.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            inputs = item.get("inputs")
            if isinstance(inputs, list):
                inputs.sort(
                    key=lambda entry: (
                        str(entry.get("path", "")) if isinstance(entry, dict) else ""
                    )
                )
        evidence.sort(
            key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else ""
        )

    metrics = normalized.get("metrics")
    if isinstance(metrics, list):
        for item in metrics:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("name"), str):
                item["name"] = normalize_metric_name(item["name"])
            if isinstance(item.get("unit"), str):
                item["unit"] = normalize_unit(item["unit"])
            if isinstance(item.get("evidence_ids"), list):
                item["evidence_ids"] = sorted(item["evidence_ids"], key=str)
        metrics.sort(
            key=lambda item: (
                (
                    matrix.metric_order.get(str(item.get("name", "")), 10**9),
                    str(item.get("name", "")),
                    str(item.get("scope", "")),
                    str(item.get("evidence_level", "")),
                )
                if isinstance(item, dict)
                else (10**9, "", "", "")
            )
        )

    acceptance = normalized.get("acceptance")
    if isinstance(acceptance, list):
        for item in acceptance:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("evidence_ids"), list):
                item["evidence_ids"] = sorted(item["evidence_ids"], key=str)
            levels = item.get("required_evidence_levels")
            if isinstance(levels, list) and all(
                isinstance(level, str) for level in levels
            ):
                item["required_evidence_levels"] = _canonical_level_list(matrix, levels)
        acceptance.sort(
            key=lambda item: (
                (
                    matrix.acceptance_order.get(str(item.get("id", "")), 10**9),
                    str(item.get("id", "")),
                )
                if isinstance(item, dict)
                else (10**9, "")
            )
        )

    limitations = normalized.get("limitations")
    if isinstance(limitations, list):
        for item in limitations:
            if not isinstance(item, dict):
                continue
            levels = item.get("applies_to_evidence_levels")
            if isinstance(levels, list) and all(
                isinstance(level, str) for level in levels
            ):
                item["applies_to_evidence_levels"] = _canonical_level_list(
                    matrix, levels
                )
        limitations.sort(
            key=lambda item: (
                (
                    matrix.limitation_order.get(str(item.get("id", "")), 10**9),
                    str(item.get("id", "")),
                )
                if isinstance(item, dict)
                else (10**9, "")
            )
        )

    artifacts = normalized.get("artifacts")
    if isinstance(artifacts, list):
        artifacts.sort(
            key=lambda item: (
                (
                    str(item.get("kind", "")),
                    str(item.get("path", "")),
                )
                if isinstance(item, dict)
                else ("", "")
            )
        )

    related = normalized.get("related")
    if isinstance(related, list):
        normalized["related"] = sorted(dict.fromkeys(related), key=str)
    return normalized


def _numeric(value: object, location: str) -> float | int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _raise(ReportValidationError, location, "must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        _raise(ReportValidationError, location, "must be finite")
    return value


def _truth_all(value: object, location: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        if not value:
            _raise(ReportValidationError, location, "must not be empty")
        return all(
            _truth_all(child, f"{location}.{key}") for key, child in value.items()
        )
    if isinstance(value, list):
        if not value:
            _raise(ReportValidationError, location, "must not be empty")
        return all(
            _truth_all(child, f"{location}[{index}]")
            for index, child in enumerate(value)
        )
    _raise(ReportValidationError, location, "must contain boolean outcomes")


def _present(expected: object, observed: object, location: str) -> bool:
    if expected is True:
        return observed not in (None, "", [], {})
    if isinstance(expected, list) and all(isinstance(item, str) for item in expected):
        if not isinstance(observed, Mapping):
            return False
        for field in expected:
            selected: object = observed
            for part in field.split("."):
                if not isinstance(selected, Mapping) or part not in selected:
                    return False
                selected = selected[part]
            if selected in (None, "", [], {}):
                return False
        return True
    _raise(
        ReportValidationError,
        location,
        "present expects true or an array of field paths",
    )


def _conservation_satisfied(observed: object, location: str) -> bool:
    if isinstance(observed, bool):
        return observed
    if not isinstance(observed, Mapping) or not observed:
        _raise(
            ReportValidationError,
            location,
            "must be a boolean or non-empty equation object",
        )
    results: list[bool] = []
    for name, raw in observed.items():
        equation_location = f"{location}.{name}"
        if isinstance(raw, bool):
            results.append(raw)
            continue
        if not isinstance(raw, Mapping):
            _raise(
                ReportValidationError,
                equation_location,
                "must be a boolean or equation",
            )
        if "left" in raw and "right" in raw:
            results.append(raw["left"] == raw["right"])
            continue
        if "lhs" in raw and "rhs" in raw:
            results.append(raw["lhs"] == raw["rhs"])
            continue
        if "residual" in raw:
            residual = _numeric(raw["residual"], f"{equation_location}.residual")
            results.append(residual == 0)
            continue
        _raise(
            ReportValidationError,
            equation_location,
            "must contain left/right, lhs/rhs, or residual",
        )
    return all(results)


def evaluate_operator(
    operator: str,
    expected: object,
    observed: object,
    *,
    location: str = "acceptance",
) -> bool:
    """Evaluate one typed acceptance comparison independently of rendering."""

    if operator == "eq" or operator in {"byte_equal", "hash_equal"}:
        return observed == expected
    if operator == "all":
        if expected is True:
            return _truth_all(observed, f"{location}.observed")
        if isinstance(expected, Mapping):
            if not isinstance(observed, Mapping):
                return False
            return all(
                key in observed and observed[key] == value
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            if not isinstance(observed, Mapping) or not all(
                isinstance(item, str) for item in expected
            ):
                _raise(
                    ReportValidationError,
                    f"{location}.expected",
                    "all field lists require an observed object",
                )
            return all(observed.get(item) is True for item in expected)
        _raise(
            ReportValidationError,
            f"{location}.expected",
            "all expects true, an object, or field names",
        )
    if operator == "between_inclusive":
        observed_number = _numeric(observed, f"{location}.observed")
        if isinstance(expected, Mapping):
            if set(expected) != {"minimum", "maximum"}:
                _raise(
                    ReportValidationError,
                    f"{location}.expected",
                    "must contain minimum and maximum",
                )
            minimum = _numeric(expected["minimum"], f"{location}.expected.minimum")
            maximum = _numeric(expected["maximum"], f"{location}.expected.maximum")
        elif isinstance(expected, list) and len(expected) == 2:
            minimum = _numeric(expected[0], f"{location}.expected[0]")
            maximum = _numeric(expected[1], f"{location}.expected[1]")
        else:
            _raise(
                ReportValidationError,
                f"{location}.expected",
                "must be [minimum, maximum] or an object",
            )
        if minimum > maximum:
            _raise(
                ReportValidationError, f"{location}.expected", "minimum exceeds maximum"
            )
        return minimum <= observed_number <= maximum
    if operator == "gte":
        return _numeric(observed, f"{location}.observed") >= _numeric(
            expected, f"{location}.expected"
        )
    if operator == "lte":
        return _numeric(observed, f"{location}.observed") <= _numeric(
            expected, f"{location}.expected"
        )
    if operator == "present":
        return _present(expected, observed, f"{location}.expected")
    if operator == "none":
        if expected is not None:
            _raise(ReportValidationError, f"{location}.expected", "none expects null")
        return observed in (None, 0, "", [], {})
    if operator == "exact_conservation":
        if expected is not True:
            _raise(
                ReportValidationError,
                f"{location}.expected",
                "exact_conservation expects true",
            )
        return _conservation_satisfied(observed, f"{location}.observed")
    raise ReportValidationError(
        f"{location}.operator: unsupported operator {operator!r}"
    )


def result_rollup(states: Sequence[str]) -> str:
    """Derive the report result from required acceptance states."""

    if not states:
        raise ReportValidationError("acceptance must contain required checks")
    if "FAIL" in states:
        return "FAIL"
    if all(state == "PASS" for state in states):
        return "PASS"
    if all(state == "NOT_RUN" for state in states):
        return "NOT_RUN"
    return "INCONCLUSIVE"


def _validate_content_policy(value: object, location: str = "report") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                _raise(ReportValidationError, location, "object keys must be text")
            key = normalize_metric_name(raw_key)
            compact_key = key.replace("_", "")
            if any(
                fragment.replace("_", "") in compact_key
                for fragment in SENSITIVE_KEY_FRAGMENTS
            ) and child not in (None, "", False, []):
                _raise(
                    ReportValidationError,
                    f"{location}.{raw_key}",
                    "credential-bearing fields are forbidden",
                )
            if compact_key in {
                selected.replace("_", "") for selected in MUTABLE_IDENTIFIER_KEYS
            } and child not in (None, "", False):
                _raise(
                    ReportValidationError,
                    f"{location}.{raw_key}",
                    "mutable port or rig identifiers are forbidden",
                )
            if compact_key in {
                selected.replace("_", "") for selected in HOST_IDENTITY_KEYS
            } and child not in (None, "", False, []):
                _raise(
                    ReportValidationError,
                    f"{location}.{raw_key}",
                    "host-local identity or environment data is forbidden",
                )
            if (
                compact_key
                in {
                    selected.replace("_", "") for selected in NONDETERMINISTIC_TIME_KEYS
                }
                and child is not None
            ):
                _raise(
                    ReportValidationError,
                    f"{location}.{raw_key}",
                    "nondeterministic generated timestamps are forbidden",
                )
            if compact_key in {
                selected.replace("_", "") for selected in BULK_DATA_KEYS
            } and child not in (None, "", [], {}):
                _raise(
                    ReportValidationError,
                    f"{location}.{raw_key}",
                    "bulk or raw sample data is forbidden",
                )
            _validate_content_policy(child, f"{location}.{raw_key}")
        return
    if isinstance(value, list):
        if len(value) > MAX_STRUCTURED_LIST_ITEMS:
            _raise(
                ReportValidationError,
                location,
                "array is bulk data rather than evidence metadata",
            )
        for index, child in enumerate(value):
            _validate_content_policy(child, f"{location}[{index}]")
        return
    if isinstance(value, str):
        if CONTROL_CHARACTER_PATTERN.search(value):
            _raise(ReportValidationError, location, "contains a control character")
        if value.casefold().startswith("file:"):
            _raise(ReportValidationError, location, "file URIs are forbidden")
        if "://" in value and not location.endswith(".repository"):
            _raise(
                ReportValidationError,
                location,
                "hostnames and external URLs are forbidden",
            )
        if WINDOWS_ABSOLUTE_PATTERN.search(value) or UNC_PATH_PATTERN.search(value):
            _raise(ReportValidationError, location, "contains an absolute Windows path")
        if POSIX_ABSOLUTE_PATTERN.search(value):
            _raise(
                ReportValidationError, location, "contains a local absolute POSIX path"
            )
        if MUTABLE_PORT_PATTERN.search(value):
            _raise(
                ReportValidationError,
                location,
                "contains a mutable serial port identifier",
            )
        if MUTABLE_IDENTIFIER_OPTION_PATTERN.search(value):
            _raise(
                ReportValidationError,
                location,
                "contains a mutable port or rig identifier option",
            )
        if CREDENTIAL_ASSIGNMENT_PATTERN.search(value):
            _raise(
                ReportValidationError, location, "contains credential-shaped content"
            )
        if (
            CREDENTIAL_OPTION_PATTERN.search(value)
            or re.search(r"\bBearer\s+\S", value, re.IGNORECASE)
            or "PRIVATE KEY-----" in value
        ):
            _raise(
                ReportValidationError, location, "contains credential-shaped content"
            )
        return
    if isinstance(value, float) and not math.isfinite(value):
        _raise(ReportValidationError, location, "contains a non-finite number")


def validate_content_policy(value: object, location: str = "report") -> None:
    """Reject credentials, mutable host identity, bulk data, and unsafe paths.

    Aggregate and candidate-specific report tools share the Phase 01 content
    boundary through this public wrapper instead of duplicating its policy.
    """

    _validate_content_policy(value, location)


def _validate_identity(
    matrix: ExperimentMatrix,
    identity: Mapping[str, Any],
    *,
    tracked_report: bool,
) -> None:
    contract = _mapping(matrix.report_contract, "identity", MatrixValidationError)
    required = _string_list(contract, "required_fields", MatrixValidationError)
    _require_fields(identity, required, ReportValidationError, "identity")
    repository = _text(identity, "repository", ReportValidationError)
    if repository != contract["repository"]:
        _raise(
            ReportValidationError, "identity.repository", "does not match the matrix"
        )
    _text(identity, "branch", ReportValidationError)
    baseline_branch = _text(identity, "baseline_branch", ReportValidationError)
    matrix_baseline = _mapping(matrix.data, "branches", MatrixValidationError)[
        "baseline"
    ]
    if baseline_branch != matrix_baseline:
        _raise(
            ReportValidationError,
            "identity.baseline_branch",
            "does not match the matrix",
        )
    for field in ("baseline_commit", "source_commit", "source_tree"):
        selected = _text(identity, field, ReportValidationError)
        if not GIT_OBJECT_PATTERN.fullmatch(selected):
            _raise(
                ReportValidationError,
                f"identity.{field}",
                "must be a full lowercase Git object id",
            )
    source_clean = _boolean(identity, "source_clean", ReportValidationError)
    if (
        tracked_report
        and contract.get("source_clean_required_for_tracked_report") is True
        and not source_clean
    ):
        _raise(
            ReportValidationError,
            "identity.source_clean",
            "tracked evidence requires a clean source",
        )
    source_id = _text(identity, "source_id", ReportValidationError)
    if not SHA256_PATTERN.fullmatch(source_id):
        _raise(
            ReportValidationError, "identity.source_id", "must be a lowercase SHA-256"
        )
    protocol_path = validate_repository_relative_path(
        identity.get("protocol_contract_path"), "identity.protocol_contract_path"
    )
    if protocol_path != "protocol/protocol-v1.json":
        _raise(
            ReportValidationError,
            "identity.protocol_contract_path",
            "must identify protocol v1",
        )
    _integer(identity, "protocol_version", ReportValidationError, minimum=1)
    protocol_sha = _text(identity, "protocol_sha256", ReportValidationError)
    if not SHA256_PATTERN.fullmatch(protocol_sha):
        _raise(
            ReportValidationError,
            "identity.protocol_sha256",
            "must be a lowercase SHA-256",
        )
    toolchains = _list(identity, "toolchains", ReportValidationError)
    if not toolchains:
        _raise(ReportValidationError, "identity.toolchains", "must not be empty")
    required_toolchain_fields = _string_list(
        contract, "toolchain_record_required_fields", MatrixValidationError
    )
    names: list[str] = []
    for index, raw in enumerate(toolchains):
        location = f"identity.toolchains[{index}]"
        if not isinstance(raw, dict):
            _raise(ReportValidationError, location, "must be an object")
        _require_fields(raw, required_toolchain_fields, ReportValidationError, location)
        name = _text(raw, "name", ReportValidationError, location=f"{location}.name")
        names.append(name)
        _text(raw, "version", ReportValidationError, location=f"{location}.version")
        tool_identity = _text(
            raw, "identity", ReportValidationError, location=f"{location}.identity"
        )
        if contract.get("toolchain_paths_allowed") is False and (
            WINDOWS_ABSOLUTE_PATTERN.search(tool_identity)
            or POSIX_ABSOLUTE_PATTERN.search(tool_identity)
        ):
            _raise(
                ReportValidationError,
                f"{location}.identity",
                "may not contain a tool path",
            )
    _unique(names, ReportValidationError, "identity.toolchains.name")


def _validate_evidence(
    matrix: ExperimentMatrix,
    raw_evidence: Sequence[Any],
) -> dict[str, dict[str, Any]]:
    contract = _mapping(
        matrix.report_contract, "evidence_record", MatrixValidationError
    )
    required = _string_list(contract, "required_fields", MatrixValidationError)
    command_required = _string_list(
        contract, "command_required_fields", MatrixValidationError
    )
    input_required = _string_list(
        contract, "input_record_required_fields", MatrixValidationError
    )
    conditional = _mapping(
        contract, "conditional_identity_fields", MatrixValidationError
    )
    evidence_levels = set(matrix.data["evidence_levels"])
    records: dict[str, dict[str, Any]] = {}
    input_digests: dict[str, str] = {}
    for index, raw in enumerate(raw_evidence):
        location = f"evidence[{index}]"
        if not isinstance(raw, dict):
            _raise(ReportValidationError, location, "must be an object")
        _require_fields(raw, required, ReportValidationError, location)
        evidence_id = _text(raw, "id", ReportValidationError, location=f"{location}.id")
        if not SLUG_PATTERN.fullmatch(evidence_id) or evidence_id in records:
            _raise(
                ReportValidationError,
                f"{location}.id",
                "must be a unique normalized id",
            )
        level = _text(raw, "level", ReportValidationError, location=f"{location}.level")
        if level not in evidence_levels:
            _raise(
                ReportValidationError,
                f"{location}.level",
                f"unknown evidence level {level!r}",
            )
        _state_reason(matrix, raw.get("result"), raw.get("reason"), location)
        _text(raw, "method", ReportValidationError, location=f"{location}.method")
        command = _mapping(
            raw, "command", ReportValidationError, location=f"{location}.command"
        )
        _require_fields(
            command, command_required, ReportValidationError, f"{location}.command"
        )
        argv = _list(
            command, "argv", ReportValidationError, location=f"{location}.command.argv"
        )
        if not argv or not all(
            isinstance(argument, str) and argument for argument in argv
        ):
            _raise(
                ReportValidationError,
                f"{location}.command.argv",
                "must be a non-empty string array",
            )
        for flag in ("network", "serial_hardware", "firmware_upload", "user_input"):
            _boolean(
                command,
                flag,
                ReportValidationError,
                location=f"{location}.command.{flag}",
            )
        inputs = _list(
            raw, "inputs", ReportValidationError, location=f"{location}.inputs"
        )
        if raw.get("result") != "NOT_RUN" and not inputs:
            _raise(
                ReportValidationError,
                f"{location}.inputs",
                "executed evidence requires at least one hashed input",
            )
        seen_paths: list[str] = []
        for input_index, input_raw in enumerate(inputs):
            input_location = f"{location}.inputs[{input_index}]"
            if not isinstance(input_raw, dict):
                _raise(ReportValidationError, input_location, "must be an object")
            _require_fields(
                input_raw, input_required, ReportValidationError, input_location
            )
            selected_path = validate_repository_relative_path(
                input_raw.get("path"), f"{input_location}.path"
            )
            seen_paths.append(selected_path)
            digest = _text(
                input_raw,
                "sha256",
                ReportValidationError,
                location=f"{input_location}.sha256",
            )
            if not SHA256_PATTERN.fullmatch(digest):
                _raise(
                    ReportValidationError,
                    f"{input_location}.sha256",
                    "must be a lowercase SHA-256",
                )
            previous_digest = input_digests.get(selected_path)
            if previous_digest is not None and previous_digest != digest:
                _raise(
                    ReportValidationError,
                    f"{input_location}.sha256",
                    "conflicts with another record for the same input path",
                )
            input_digests[selected_path] = digest
        _unique(seen_paths, ReportValidationError, f"{location}.inputs.path")
        for field in _string_list(conditional, level, MatrixValidationError):
            if field not in raw or raw[field] in (None, "", [], {}):
                _raise(
                    ReportValidationError,
                    location,
                    f"{level} evidence requires {field!r}",
                )
        records[evidence_id] = raw
    if not records:
        _raise(
            ReportValidationError,
            "evidence",
            "must contain at least one evidence record",
        )
    return records


def _validate_metrics(
    matrix: ExperimentMatrix,
    raw_metrics: Sequence[Any],
    evidence: Mapping[str, Mapping[str, Any]],
) -> None:
    contract = _mapping(matrix.report_contract, "metric_record", MatrixValidationError)
    required = _string_list(contract, "required_fields", MatrixValidationError)
    seen_keys: set[tuple[str, str, str, str, str]] = set()
    for index, raw in enumerate(raw_metrics):
        location = f"metrics[{index}]"
        if not isinstance(raw, dict):
            _raise(ReportValidationError, location, "must be an object")
        _require_fields(raw, required, ReportValidationError, location)
        name = _text(raw, "name", ReportValidationError, location=f"{location}.name")
        definition = matrix.metric_definitions.get(name)
        if definition is None:
            _raise(
                ReportValidationError, f"{location}.name", f"unknown metric {name!r}"
            )
        unit = _text(raw, "unit", ReportValidationError, location=f"{location}.unit")
        denominator = _text(
            raw,
            "denominator",
            ReportValidationError,
            location=f"{location}.denominator",
        )
        scope = _text(raw, "scope", ReportValidationError, location=f"{location}.scope")
        level = _text(
            raw,
            "evidence_level",
            ReportValidationError,
            location=f"{location}.evidence_level",
        )
        for field, observed in (
            ("unit", unit),
            ("denominator", denominator),
            ("scope", scope),
        ):
            if observed != definition[field]:
                _raise(
                    ReportValidationError,
                    f"{location}.{field}",
                    f"does not match {name!r} definition {definition[field]!r}",
                )
        if level not in definition["allowed_evidence_levels"]:
            _raise(
                ReportValidationError,
                f"{location}.evidence_level",
                "is not allowed for this metric",
            )
        metric_value = raw.get("value")
        if definition["value_type"] == "integer":
            if not isinstance(metric_value, int) or isinstance(metric_value, bool):
                _raise(ReportValidationError, f"{location}.value", "must be an integer")
        else:
            _numeric(metric_value, f"{location}.value")
        evidence_ids = _string_list(
            raw,
            "evidence_ids",
            ReportValidationError,
            nonempty=True,
            location=f"{location}.evidence_ids",
        )
        _unique(evidence_ids, ReportValidationError, f"{location}.evidence_ids")
        for evidence_id in evidence_ids:
            selected = evidence.get(evidence_id)
            if selected is None:
                _raise(
                    ReportValidationError,
                    f"{location}.evidence_ids",
                    f"unknown evidence id {evidence_id!r}",
                )
            if selected["level"] != level:
                _raise(
                    ReportValidationError,
                    f"{location}.evidence_ids",
                    "must reference evidence at the metric's level",
                )
        key = (name, unit, denominator, scope, level)
        if key in seen_keys:
            _raise(
                ReportValidationError, location, "duplicates a metric comparability key"
            )
        seen_keys.add(key)


def _validate_acceptance(
    matrix: ExperimentMatrix,
    experiment: Mapping[str, Any],
    raw_acceptance: Sequence[Any],
    evidence: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    contract = _mapping(
        matrix.report_contract, "acceptance_record", MatrixValidationError
    )
    required_fields = _string_list(contract, "required_fields", MatrixValidationError)
    required_ids = _string_list(
        experiment, "required_acceptance_checks", MatrixValidationError
    )
    records: dict[str, Mapping[str, Any]] = {}
    states: dict[str, str] = {}
    for index, raw in enumerate(raw_acceptance):
        location = f"acceptance[{index}]"
        if not isinstance(raw, dict):
            _raise(ReportValidationError, location, "must be an object")
        _require_fields(raw, required_fields, ReportValidationError, location)
        check_id = _text(raw, "id", ReportValidationError, location=f"{location}.id")
        definition = matrix.acceptance_checks.get(check_id)
        if definition is None:
            _raise(
                ReportValidationError,
                f"{location}.id",
                f"unknown acceptance check {check_id!r}",
            )
        if check_id in records:
            _raise(
                ReportValidationError,
                f"{location}.id",
                "duplicates an acceptance check",
            )
        if raw.get("description") != definition["description"]:
            _raise(
                ReportValidationError,
                f"{location}.description",
                "does not match the matrix",
            )
        if raw.get("operator") != definition["operator"]:
            _raise(
                ReportValidationError,
                f"{location}.operator",
                "does not match the matrix",
            )
        levels = _string_list(
            raw,
            "required_evidence_levels",
            ReportValidationError,
            nonempty=True,
            location=f"{location}.required_evidence_levels",
        )
        if levels != _canonical_level_list(
            matrix, definition["required_evidence_levels"]
        ):
            _raise(
                ReportValidationError,
                f"{location}.required_evidence_levels",
                "does not match the matrix",
            )
        state = _state_reason(matrix, raw.get("state"), raw.get("reason"), location)
        evidence_ids = _string_list(
            raw,
            "evidence_ids",
            ReportValidationError,
            location=f"{location}.evidence_ids",
        )
        _unique(evidence_ids, ReportValidationError, f"{location}.evidence_ids")
        referenced_levels: set[str] = set()
        for evidence_id in evidence_ids:
            selected = evidence.get(evidence_id)
            if selected is None:
                _raise(
                    ReportValidationError,
                    f"{location}.evidence_ids",
                    f"unknown evidence id {evidence_id!r}",
                )
            referenced_levels.add(str(selected["level"]))
        allowed_levels = set(definition["required_evidence_levels"])
        if referenced_levels and not referenced_levels.issubset(allowed_levels):
            _raise(
                ReportValidationError,
                f"{location}.evidence_ids",
                "uses an evidence level not permitted by the check",
            )
        if state in {"PASS", "FAIL"} and not evidence_ids:
            _raise(
                ReportValidationError,
                f"{location}.evidence_ids",
                f"{state} requires observed evidence",
            )
        if state == "PASS" and any(
            evidence[evidence_id]["result"] != "PASS" for evidence_id in evidence_ids
        ):
            _raise(
                ReportValidationError,
                f"{location}.evidence_ids",
                "PASS may reference only successful evidence records",
            )
        if state == "NOT_RUN":
            if raw.get("observed") is not None:
                _raise(
                    ReportValidationError,
                    f"{location}.observed",
                    "must be null for NOT_RUN",
                )
            if evidence_ids:
                _raise(
                    ReportValidationError,
                    f"{location}.evidence_ids",
                    "must be empty for NOT_RUN",
                )
        elif state in {"PASS", "FAIL"}:
            if state == "FAIL" and raw.get("observed") is None:
                _raise(
                    ReportValidationError,
                    f"{location}.observed",
                    "FAIL requires a non-null observed value",
                )
            satisfied = evaluate_operator(
                str(raw["operator"]),
                raw.get("expected"),
                raw.get("observed"),
                location=location,
            )
            if state == "PASS" and not satisfied:
                _raise(
                    ReportValidationError,
                    location,
                    "PASS contradicts the observed acceptance outcome",
                )
            if state == "FAIL" and satisfied:
                _raise(
                    ReportValidationError,
                    location,
                    "FAIL contradicts the observed acceptance outcome",
                )
        records[check_id] = raw
        states[check_id] = state
    if set(records) != set(required_ids):
        missing = sorted(set(required_ids) - set(records))
        extra = sorted(set(records) - set(required_ids))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("not required for this experiment " + ", ".join(extra))
        _raise(ReportValidationError, "acceptance", "; ".join(detail))
    return [states[check_id] for check_id in required_ids]


def _validate_limitations(
    matrix: ExperimentMatrix,
    experiment: Mapping[str, Any],
    raw_limitations: Sequence[Any],
) -> None:
    contract = _mapping(
        matrix.report_contract, "limitation_record", MatrixValidationError
    )
    required_fields = _string_list(contract, "required_fields", MatrixValidationError)
    required_ids = set(
        _string_list(experiment, "required_limitations", MatrixValidationError)
    )
    observed_ids: set[str] = set()
    for index, raw in enumerate(raw_limitations):
        location = f"limitations[{index}]"
        if not isinstance(raw, dict):
            _raise(ReportValidationError, location, "must be an object")
        _require_fields(raw, required_fields, ReportValidationError, location)
        limitation_id = _text(
            raw, "id", ReportValidationError, location=f"{location}.id"
        )
        definition = matrix.claim_limitations.get(limitation_id)
        if definition is None:
            _raise(
                ReportValidationError,
                f"{location}.id",
                f"unknown limitation {limitation_id!r}",
            )
        if limitation_id in observed_ids:
            _raise(ReportValidationError, f"{location}.id", "duplicates a limitation")
        if raw.get("statement") != definition["statement"]:
            _raise(
                ReportValidationError,
                f"{location}.statement",
                "does not match the matrix",
            )
        levels = _string_list(
            raw,
            "applies_to_evidence_levels",
            ReportValidationError,
            nonempty=True,
            location=f"{location}.applies_to_evidence_levels",
        )
        if levels != _canonical_level_list(
            matrix, definition["applies_to_evidence_levels"]
        ):
            _raise(
                ReportValidationError,
                f"{location}.applies_to_evidence_levels",
                "does not match the matrix",
            )
        observed_ids.add(limitation_id)
    missing = sorted(required_ids - observed_ids)
    if missing:
        _raise(
            ReportValidationError,
            "limitations",
            "missing required limitations: " + ", ".join(missing),
        )


def _validate_artifacts(
    matrix: ExperimentMatrix,
    raw_artifacts: Sequence[Any],
    *,
    output_paths: Sequence[str],
) -> None:
    contract = _mapping(
        matrix.report_contract, "artifact_record", MatrixValidationError
    )
    required_fields = _string_list(contract, "required_fields", MatrixValidationError)
    seen_paths: list[str] = []
    for index, raw in enumerate(raw_artifacts):
        location = f"artifacts[{index}]"
        if not isinstance(raw, dict):
            _raise(ReportValidationError, location, "must be an object")
        _require_fields(raw, required_fields, ReportValidationError, location)
        kind = _text(raw, "kind", ReportValidationError, location=f"{location}.kind")
        if not SLUG_PATTERN.fullmatch(kind):
            _raise(
                ReportValidationError, f"{location}.kind", "must be a normalized slug"
            )
        selected_path = validate_repository_relative_path(
            raw.get("path"), f"{location}.path"
        )
        if selected_path in output_paths:
            _raise(
                ReportValidationError,
                f"{location}.path",
                "may not self-reference a report output",
            )
        seen_paths.append(selected_path)
        _integer(
            raw,
            "size_bytes",
            ReportValidationError,
            minimum=0,
            location=f"{location}.size_bytes",
        )
        digest = _text(
            raw, "sha256", ReportValidationError, location=f"{location}.sha256"
        )
        if not SHA256_PATTERN.fullmatch(digest):
            _raise(
                ReportValidationError,
                f"{location}.sha256",
                "must be a lowercase SHA-256",
            )
    _unique(seen_paths, ReportValidationError, "artifacts.path")


def validate_report(
    matrix: ExperimentMatrix,
    report: Mapping[str, Any],
    *,
    tracked_report: bool = True,
    output_paths: Sequence[str] = (),
) -> None:
    """Validate normalized evidence without consulting its presentation."""

    if not isinstance(report, Mapping):
        raise ReportValidationError("report must be an object")
    missing = sorted(REPORT_REQUIRED_FIELDS - set(report))
    unknown = sorted(set(report) - REPORT_REQUIRED_FIELDS - REPORT_OPTIONAL_FIELDS)
    if missing:
        _raise(
            ReportValidationError,
            "report",
            "missing required fields: " + ", ".join(missing),
        )
    if unknown:
        _raise(ReportValidationError, "report", "unknown fields: " + ", ".join(unknown))
    if (
        _integer(report, "schema_version", ReportValidationError, minimum=1)
        != matrix.report_contract["schema_version"]
    ):
        _raise(
            ReportValidationError,
            "schema_version",
            "does not match the report contract",
        )
    if (
        _integer(report, "matrix_schema_version", ReportValidationError, minimum=1)
        != matrix.schema_version
    ):
        _raise(
            ReportValidationError, "matrix_schema_version", "does not match the matrix"
        )
    experiment_id = _text(report, "experiment_id", ReportValidationError)
    experiment = matrix.experiment(experiment_id)
    if report.get("title") != experiment["title"]:
        _raise(ReportValidationError, "title", "does not match the experiment title")
    created = _text(report, "created", ReportValidationError)
    if not DATE_PATTERN.fullmatch(created):
        _raise(ReportValidationError, "created", "must be an explicit YYYY-MM-DD date")
    try:
        year, month, day = (int(part) for part in created.split("-"))
        date(year, month, day)
    except ValueError as error:
        raise ReportValidationError(
            f"created is not a calendar date: {created}"
        ) from error
    result = _state_reason(matrix, report.get("result"), report.get("reason"), "report")
    identity = _mapping(report, "identity", ReportValidationError)
    _validate_identity(matrix, identity, tracked_report=tracked_report)
    raw_evidence = _list(report, "evidence", ReportValidationError)
    evidence = _validate_evidence(matrix, raw_evidence)
    _validate_metrics(matrix, _list(report, "metrics", ReportValidationError), evidence)
    states = _validate_acceptance(
        matrix,
        experiment,
        _list(report, "acceptance", ReportValidationError),
        evidence,
    )
    expected_result = result_rollup(states)
    if result != expected_result:
        _raise(
            ReportValidationError,
            "result",
            f"must be {expected_result} for the required acceptance states",
        )
    _validate_limitations(
        matrix,
        experiment,
        _list(report, "limitations", ReportValidationError),
    )
    selected_output_paths = tuple(output_paths) or matrix.expected_paths(experiment_id)
    _validate_artifacts(
        matrix,
        _list(report, "artifacts", ReportValidationError),
        output_paths=selected_output_paths,
    )
    if "summary" in report and (
        not isinstance(report["summary"], str) or not report["summary"].strip()
    ):
        _raise(ReportValidationError, "summary", "must be non-empty text")
    if "related" in report:
        related = _string_list(report, "related", ReportValidationError)
        _unique(related, ReportValidationError, "related")
        if not all(WIKI_LINK_PATTERN.fullmatch(link) for link in related):
            _raise(ReportValidationError, "related", "must contain only wiki-links")
    _validate_content_policy(report)


def prepare_report(
    matrix: ExperimentMatrix,
    report: Mapping[str, Any],
    *,
    tracked_report: bool = True,
    output_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Normalize and validate an evidence report for writing or rendering."""

    normalized = normalize_report(matrix, report)
    validate_report(
        matrix,
        normalized,
        tracked_report=tracked_report,
        output_paths=output_paths,
    )
    second = normalize_report(matrix, normalized)
    if canonical_json_text(normalized) != canonical_json_text(second):
        raise ReportValidationError("report normalization is not idempotent")
    return normalized


def _repository_file(root: Path, relative: str, location: str) -> Path:
    selected = (root / relative).resolve()
    try:
        selected.relative_to(root.resolve())
    except ValueError as error:
        raise ReportValidationError(
            f"{location}: path escapes the repository"
        ) from error
    return selected


def _verify_declared_file(
    root: Path,
    relative: str,
    size_bytes: object | None,
    digest: object,
    location: str,
) -> None:
    selected = _repository_file(root, relative, location)
    if not selected.is_file():
        _raise(ReportValidationError, location, f"declared file is missing: {relative}")
    if size_bytes is not None and selected.stat().st_size != size_bytes:
        _raise(ReportValidationError, location, f"size does not match {relative}")
    if sha256_file(selected) != digest:
        _raise(ReportValidationError, location, f"SHA-256 does not match {relative}")


def verify_report_files(
    report: Mapping[str, Any],
    *,
    root: Path = REPOSITORY_ROOT,
) -> None:
    """Verify protocol, evidence input, artifact, and Git identities on disk."""

    identity = _mapping(report, "identity", ReportValidationError)
    protocol_path = str(identity["protocol_contract_path"])
    _verify_declared_file(
        root,
        protocol_path,
        None,
        identity["protocol_sha256"],
        "identity.protocol_sha256",
    )
    protocol = load_json_object(
        _repository_file(root, protocol_path, "identity.protocol_contract_path"),
        error_type=ReportValidationError,
    )
    if protocol.get("protocol_version") != identity["protocol_version"]:
        _raise(
            ReportValidationError,
            "identity.protocol_version",
            "does not match the protocol contract",
        )
    checked: set[tuple[str, str]] = set()
    for evidence_index, raw_evidence in enumerate(report["evidence"]):
        if not isinstance(raw_evidence, Mapping):
            continue
        for input_index, raw_input in enumerate(raw_evidence["inputs"]):
            relative = str(raw_input["path"])
            digest = str(raw_input["sha256"])
            key = (relative, digest)
            if key in checked:
                continue
            _verify_declared_file(
                root,
                relative,
                None,
                digest,
                f"evidence[{evidence_index}].inputs[{input_index}]",
            )
            checked.add(key)
    for artifact_index, raw_artifact in enumerate(report["artifacts"]):
        _verify_declared_file(
            root,
            str(raw_artifact["path"]),
            raw_artifact["size_bytes"],
            raw_artifact["sha256"],
            f"artifacts[{artifact_index}]",
        )

    source_commit = str(identity["source_commit"])
    source_tree = str(identity["source_tree"])
    try:
        observed_tree = _run_command(
            ["git", "-C", str(root), "rev-parse", f"{source_commit}^{{tree}}"]
        ).strip()
        _run_command(
            [
                "git",
                "-C",
                str(root),
                "cat-file",
                "-e",
                f"{identity['baseline_commit']}^{{commit}}",
            ]
        )
    except EvidenceError as error:
        raise ReportValidationError(
            f"identity Git object verification failed: {error}"
        ) from error
    if observed_tree != source_tree:
        _raise(
            ReportValidationError,
            "identity.source_tree",
            "does not match source_commit",
        )
    try:
        observed_source_id = _firmware_source_fingerprint(root)
    except EvidenceError as error:
        raise ReportValidationError(
            f"identity firmware source verification failed: {error}"
        ) from error
    if observed_source_id != identity["source_id"]:
        _raise(
            ReportValidationError,
            "identity.source_id",
            "does not match the current firmware source inputs",
        )


def _markdown_cell(value: object) -> str:
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


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _related_links(matrix: ExperimentMatrix, report: Mapping[str, Any]) -> list[str]:
    experiment = matrix.experiment(str(report["experiment_id"]))
    selected = list(BASE_WIKI_LINKS)
    if experiment.get("role") == "candidate":
        selected.append("[[baseline]]")
    raw_required = experiment.get("required_wiki_links", [])
    if isinstance(raw_required, list):
        selected.extend(str(link) for link in raw_required)
    raw_related = report.get("related", [])
    if isinstance(raw_related, list):
        selected.extend(str(link) for link in raw_related)
    return list(dict.fromkeys(selected))


def render_markdown(
    matrix: ExperimentMatrix,
    report: Mapping[str, Any],
    *,
    tracked_report: bool = False,
    output_paths: Sequence[str] = (),
) -> str:
    """Render deterministic structured Markdown from validated report data."""

    normalized = prepare_report(
        matrix,
        report,
        tracked_report=tracked_report,
        output_paths=output_paths,
    )
    identity = normalized["identity"]
    evidence = normalized["evidence"]
    metrics = normalized["metrics"]
    acceptance = normalized["acceptance"]
    limitations = normalized["limitations"]
    artifacts = normalized["artifacts"]
    related = _related_links(matrix, normalized)
    evidence_semantics = _mapping(
        matrix.data, "evidence_level_semantics", MatrixValidationError
    )
    used_levels = sorted(
        {str(item["level"]) for item in evidence},
        key=lambda level: matrix.evidence_level_order[level],
    )

    lines = [
        "---",
        "type: report",
        f"title: {_yaml_string(str(normalized['title']))}",
        f"created: {normalized['created']}",
        "tags:",
        "  - thingdaq",
        "  - experiment-evidence",
        f"  - {normalized['experiment_id']}",
        "related:",
        *[f"  - {_yaml_string(link)}" for link in related],
        "---",
        "",
        f"# {normalized['title']}",
        "",
        "## Outcome",
        "",
        f"**{normalized['result']}**",
        "",
    ]
    if normalized.get("summary"):
        lines.extend([str(normalized["summary"]), ""])
    if normalized["reason"] is not None:
        lines.extend([f"Reason: {_markdown_cell(normalized['reason'])}", ""])

    lines.extend(
        [
            "## Identity and provenance",
            "",
            "| Field | Value |",
            "| --- | --- |",
            *[
                f"| {_markdown_cell(field)} | {_markdown_cell(identity[field])} |"
                for field in (
                    "repository",
                    "branch",
                    "baseline_branch",
                    "baseline_commit",
                    "source_commit",
                    "source_tree",
                    "source_clean",
                    "source_id",
                    "protocol_contract_path",
                    "protocol_version",
                    "protocol_sha256",
                )
            ],
            "",
            "### Toolchains",
            "",
            "| Name | Version | Identity |",
            "| --- | --- | --- |",
            *[
                f"| {_markdown_cell(toolchain['name'])} | {_markdown_cell(toolchain['version'])} | {_markdown_cell(toolchain['identity'])} |"
                for toolchain in identity["toolchains"]
            ],
            "",
            "## Evidence levels",
            "",
            "| Label | Meaning | Physical claims allowed |",
            "| --- | --- | ---: |",
            *[
                f"| **{_markdown_cell(level)}** | {_markdown_cell(evidence_semantics[level]['meaning'])} | {_markdown_cell(evidence_semantics[level]['physical_claims_allowed'])} |"
                for level in used_levels
            ],
            "",
            "### Evidence records",
            "",
            "| ID | Evidence level | Result | Method | Command |",
            "| --- | --- | --- | --- | --- |",
            *[
                f"| {_markdown_cell(item['id'])} | **{_markdown_cell(item['level'])}** | {_markdown_cell(item['result'])} | {_markdown_cell(item['method'])} | `{_markdown_cell(shlex.join(item['command']['argv']))}` |"
                for item in evidence
            ],
            "",
            "## Metrics",
            "",
            "| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |",
            "| --- | ---: | --- | --- | --- | --- | --- |",
            *(
                [
                    f"| {_markdown_cell(item['name'])} | {_markdown_cell(item['value'])} | {_markdown_cell(item['unit'])} | {_markdown_cell(item['denominator'])} | {_markdown_cell(item['scope'])} | **{_markdown_cell(item['evidence_level'])}** | {_markdown_cell(item['evidence_ids'])} |"
                    for item in metrics
                ]
                or ["| None recorded | — | — | — | — | — | — |"]
            ),
            "",
            "## Acceptance",
            "",
            "| Check | Description | State | Expected | Observed | Reason | Evidence |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            *[
                f"| {_markdown_cell(item['id'])} | {_markdown_cell(item['description'])} | **{_markdown_cell(item['state'])}** | {_markdown_cell(item['expected'])} | {_markdown_cell(item['observed'])} | {_markdown_cell(item['reason'])} | {_markdown_cell(item['evidence_ids'])} |"
                for item in acceptance
            ],
            "",
            "## Claim limitations",
            "",
            "| Limitation | Statement | Applies to evidence levels |",
            "| --- | --- | --- |",
            *[
                f"| {_markdown_cell(item['id'])} | {_markdown_cell(item['statement'])} | {_markdown_cell(item['applies_to_evidence_levels'])} |"
                for item in limitations
            ],
            "",
            "## Artifacts and reproduction",
            "",
            "| Kind | Repository-relative path | Size (bytes) | SHA-256 |",
            "| --- | --- | ---: | --- |",
            *(
                [
                    f"| {_markdown_cell(item['kind'])} | `{_markdown_cell(item['path'])}` | {_markdown_cell(item['size_bytes'])} | `{_markdown_cell(item['sha256'])}` |"
                    for item in artifacts
                ]
                or ["| None recorded | — | — | — |"]
            ),
            "",
            "### Commands",
            "",
            *[
                f"- `{_markdown_cell(item['id'])}` ({_markdown_cell(item['level'])}): `{_markdown_cell(shlex.join(item['command']['argv']))}`"
                for item in evidence
            ],
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write_text(path: Path, contents: str) -> None:
    """Atomically replace UTF-8 text while cleaning failed staging files."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
    except OSError as error:
        raise EvidenceError(f"could not stage {path}: {error}") from error
    temporary = Path(temporary_name)
    try:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        os.fchmod(descriptor, mode)
        owned_descriptor = descriptor
        descriptor = -1
        with os.fdopen(owned_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _relative_output_paths(
    root: Path,
    paths: Sequence[Path],
) -> tuple[str, ...]:
    relative: list[str] = []
    for path in paths:
        try:
            relative.append(path.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    return tuple(relative)


def _validate_output_paths(json_path: Path, markdown_path: Path) -> None:
    if json_path.resolve() == markdown_path.resolve():
        raise EvidenceError("JSON and Markdown outputs must be different files")
    if json_path.suffix.casefold() != ".json":
        raise EvidenceError(f"JSON output must use a .json suffix: {json_path}")
    if markdown_path.suffix.casefold() != ".md":
        raise EvidenceError(f"Markdown output must use a .md suffix: {markdown_path}")


def write_report_pair(
    matrix: ExperimentMatrix,
    report: Mapping[str, Any],
    json_path: Path,
    markdown_path: Path,
    *,
    root: Path = REPOSITORY_ROOT,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Validate first, then atomically replace deterministic JSON and Markdown."""

    _validate_output_paths(json_path, markdown_path)
    output_paths = _relative_output_paths(root, (json_path, markdown_path))
    expected = matrix.expected_paths(str(report.get("experiment_id", "")))
    tracked = set(output_paths) == set(expected)
    normalized = prepare_report(
        matrix,
        report,
        tracked_report=tracked,
        output_paths=output_paths,
    )
    if verify_files:
        verify_report_files(normalized, root=root)
    json_contents = canonical_json_text(normalized)
    markdown_contents = render_markdown(
        matrix,
        normalized,
        tracked_report=tracked,
        output_paths=output_paths,
    )
    if json_contents != canonical_json_text(normalize_report(matrix, normalized)):
        raise EvidenceDriftError("JSON rendering is nondeterministic")
    if markdown_contents != render_markdown(
        matrix,
        normalized,
        tracked_report=tracked,
        output_paths=output_paths,
    ):
        raise EvidenceDriftError("Markdown rendering is nondeterministic")
    atomic_write_text(json_path, json_contents)
    atomic_write_text(markdown_path, markdown_contents)
    return normalized


def _require_exact_bytes(path: Path, expected: bytes, label: str) -> None:
    try:
        observed = path.read_bytes()
    except OSError as error:
        raise EvidenceDriftError(
            f"{label} is missing or unreadable: {path}: {error}"
        ) from error
    if observed != expected:
        raise EvidenceDriftError(f"{label} is stale or non-canonical: {path}")


def check_report_pair(
    matrix: ExperimentMatrix,
    report_path: Path,
    json_path: Path,
    markdown_path: Path,
    *,
    root: Path = REPOSITORY_ROOT,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Fail on schema, hash, rendering, content-policy, or output drift."""

    _validate_output_paths(json_path, markdown_path)
    raw = load_json_object(report_path)
    output_paths = _relative_output_paths(root, (json_path, markdown_path))
    expected = matrix.expected_paths(str(raw.get("experiment_id", "")))
    tracked = set(output_paths) == set(expected)
    normalized = prepare_report(
        matrix,
        raw,
        tracked_report=tracked,
        output_paths=output_paths,
    )
    if verify_files:
        verify_report_files(normalized, root=root)
    json_contents = canonical_json_text(normalized)
    markdown_contents = render_markdown(
        matrix,
        normalized,
        tracked_report=tracked,
        output_paths=output_paths,
    )
    if json_contents != canonical_json_text(normalize_report(matrix, normalized)):
        raise EvidenceDriftError("two normalized JSON renders differ")
    if markdown_contents != render_markdown(
        matrix,
        normalized,
        tracked_report=tracked,
        output_paths=output_paths,
    ):
        raise EvidenceDriftError("two Markdown renders differ")
    _require_exact_bytes(json_path, json_contents.encode("utf-8"), "JSON report")
    _require_exact_bytes(
        markdown_path, markdown_contents.encode("utf-8"), "Markdown report"
    )
    return normalized


def _run_command(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise EvidenceError(f"could not run {command[0]!r}: {error}") from error
    if completed.returncode != 0:
        detail = "\n".join(
            part.strip()
            for part in (completed.stdout, completed.stderr)
            if part.strip()
        )
        raise EvidenceError(
            f"command failed ({completed.returncode}): {shlex.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    return completed.stdout.strip()


def _load_build_helper() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "_thingdaq_experiment_build_helper",
        BUILD_HELPER_PATH,
    )
    if specification is None or specification.loader is None:
        raise EvidenceError(f"could not load build helper: {BUILD_HELPER_PATH}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException as error:
        raise EvidenceError(f"could not import build helper: {error}") from error
    return module


def _firmware_source_fingerprint(root: Path) -> str:
    """Reuse the pinned build helper's exact firmware-source boundary."""

    helper = _load_build_helper()
    try:
        source_inputs = tuple(
            root / source.relative_to(helper.REPOSITORY_ROOT)
            for source in helper.SOURCE_INPUTS
        )
        source_files = helper.collect_source_files(source_inputs)
        source_id = helper.source_fingerprint(source_files, root=root)
    except BaseException as error:
        raise EvidenceError(
            f"could not capture firmware source identity: {error}"
        ) from error
    if not isinstance(source_id, str) or not SHA256_PATTERN.fullmatch(source_id):
        raise EvidenceError("build helper returned an invalid firmware source identity")
    return source_id


def toolchain_record(name: str, version: str, identity: str) -> dict[str, str]:
    """Create one path-free toolchain identity record."""

    record = {"name": name, "version": version, "identity": identity}
    for field, value in record.items():
        if not isinstance(value, str) or not value.strip():
            raise EvidenceError(f"toolchain {field} must be non-empty text")
        if WINDOWS_ABSOLUTE_PATTERN.search(value) or POSIX_ABSOLUTE_PATTERN.search(
            value
        ):
            raise EvidenceError(f"toolchain {field} may not contain an absolute path")
    return record


def capture_identity(
    matrix: ExperimentMatrix,
    experiment_id: str,
    *,
    root: Path = REPOSITORY_ROOT,
    toolchains: Sequence[Mapping[str, str]] = (),
    baseline_commit: str | None = None,
) -> dict[str, Any]:
    """Capture stable Git, firmware-source, protocol, and toolchain identity."""

    matrix.experiment(experiment_id)
    source_commit = _run_command(["git", "-C", str(root), "rev-parse", "HEAD"])
    source_tree = _run_command(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"])
    branch = _run_command(["git", "-C", str(root), "branch", "--show-current"])
    if not branch:
        branch = "DETACHED"
    status = _run_command(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]
    )
    baseline_branch = str(
        _mapping(matrix.data, "branches", MatrixValidationError)["baseline"]
    )
    if baseline_commit is None:
        try:
            baseline_commit = _run_command(
                ["git", "-C", str(root), "rev-parse", f"{baseline_branch}^{{commit}}"]
            )
        except EvidenceError:
            baseline_commit = source_commit
    if not GIT_OBJECT_PATTERN.fullmatch(baseline_commit):
        raise EvidenceError("baseline commit must be a full lowercase Git object id")

    protocol_relative = PROTOCOL_PATH.relative_to(REPOSITORY_ROOT).as_posix()
    protocol_path = root / protocol_relative
    protocol = load_json_object(protocol_path, error_type=ReportValidationError)
    protocol_version = protocol.get("protocol_version")
    if not isinstance(protocol_version, int) or isinstance(protocol_version, bool):
        raise EvidenceError("protocol contract has no integer protocol_version")

    source_id = _firmware_source_fingerprint(root)
    selected_toolchains = [dict(record) for record in toolchains]
    if not any(record.get("name") == "python" for record in selected_toolchains):
        selected_toolchains.append(
            toolchain_record(
                "python",
                platform.python_version(),
                f"{platform.python_implementation()} {platform.python_version()}",
            )
        )
    selected_toolchains.sort(
        key=lambda record: (
            record.get("name", ""),
            record.get("version", ""),
            record.get("identity", ""),
        )
    )
    identity = {
        "repository": matrix.report_contract["identity"]["repository"],
        "branch": branch,
        "baseline_branch": baseline_branch,
        "baseline_commit": baseline_commit,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "source_clean": not status,
        "source_id": source_id,
        "protocol_contract_path": protocol_relative,
        "protocol_version": protocol_version,
        "protocol_sha256": sha256_file(protocol_path),
        "toolchains": selected_toolchains,
    }
    _validate_identity(matrix, identity, tracked_report=False)
    _validate_content_policy(identity, "identity")
    return identity


def _parse_toolchain_argument(value: str) -> dict[str, str]:
    fields = value.split("=", 2)
    if len(fields) != 3:
        raise argparse.ArgumentTypeError("toolchain must be NAME=VERSION=IDENTITY")
    try:
        return toolchain_record(*fields)
    except EvidenceError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the provenance capture and report write/check surfaces."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX_PATH,
        help="experiment matrix (default: experiments/experiment-matrix.json)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--report",
        type=Path,
        help="input report JSON to validate and render",
    )
    action.add_argument(
        "--capture-identity",
        metavar="EXPERIMENT_ID",
        help="print current normalized identity JSON for an experiment",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="JSON output; defaults to the matrix path for the experiment",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="Markdown output; defaults to the matrix path for the experiment",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="perform fail-closed validation and detect output drift without writing",
    )
    parser.add_argument(
        "--toolchain",
        action="append",
        default=[],
        type=_parse_toolchain_argument,
        metavar="NAME=VERSION=IDENTITY",
        help="additional path-free toolchain identity for --capture-identity",
    )
    parser.add_argument(
        "--baseline-commit",
        help="explicit full baseline commit for --capture-identity",
    )
    arguments = parser.parse_args(argv)
    if arguments.capture_identity is not None:
        if arguments.check or arguments.json_output or arguments.markdown_output:
            parser.error(
                "identity capture cannot be combined with report output options"
            )
    elif arguments.toolchain or arguments.baseline_commit:
        parser.error("--toolchain and --baseline-commit require --capture-identity")
    return arguments


def _report_output_paths(
    matrix: ExperimentMatrix,
    report: Mapping[str, Any],
    json_output: Path | None,
    markdown_output: Path | None,
) -> tuple[Path, Path]:
    expected_json, expected_markdown = matrix.expected_paths(
        str(report.get("experiment_id", ""))
    )
    return (
        json_output if json_output is not None else REPOSITORY_ROOT / expected_json,
        markdown_output
        if markdown_output is not None
        else REPOSITORY_ROOT / expected_markdown,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""

    arguments = parse_args(argv)
    try:
        matrix = load_experiment_matrix(arguments.matrix)
        if arguments.capture_identity is not None:
            identity = capture_identity(
                matrix,
                arguments.capture_identity,
                toolchains=arguments.toolchain,
                baseline_commit=arguments.baseline_commit,
            )
            print(canonical_json_text(identity), end="")
            return 0

        if arguments.report is None:
            raise EvidenceError("--report is required")
        raw = load_json_object(arguments.report)
        json_path, markdown_path = _report_output_paths(
            matrix,
            raw,
            arguments.json_output,
            arguments.markdown_output,
        )
        if arguments.check:
            normalized = check_report_pair(
                matrix,
                arguments.report,
                json_path,
                markdown_path,
            )
            print(
                f"PASS {normalized['experiment_id']}: schema, hashes, content, and deterministic outputs are current"
            )
        else:
            normalized = write_report_pair(
                matrix,
                raw,
                json_path,
                markdown_path,
            )
            print(
                f"{normalized['result']} {normalized['experiment_id']}: wrote {json_path} and {markdown_path}"
            )
    except EvidenceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
