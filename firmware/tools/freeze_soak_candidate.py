#!/usr/bin/env python3
"""Create or verify the immutable Phase 11 soak-candidate freeze record."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "firmware/soak/candidate-freeze.json"
CANDIDATE_PATH = REPOSITORY_ROOT / "firmware/soak/candidate.json"
BUILD_OUTPUT_DIRECTORY = (
    REPOSITORY_ROOT
    / "firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std"
)
DEFAULT_STAGE_DIRECTORY = (
    REPOSITORY_ROOT / ".maestro/playbooks/Working/phase-11-soak-candidate-00001/frozen"
)
PROTECTED_INPUTS = (
    "daq_api/MANIFEST.in",
    "daq_api/README.md",
    "daq_api/pyproject.toml",
    "daq_api/examples",
    "daq_api/src",
    "daq_api/tests",
    "firmware/firmware.ino",
    "firmware/soak/candidate.json",
    "firmware/soak/validator.py",
    "firmware/src",
    "firmware/tests",
    "firmware/tools",
    "protocol",
    "tools",
)
EXCLUDED_DIRECTORY_NAMES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
}
REQUIRED_ARTIFACT_SUFFIXES = {".elf", ".hex", ".map"}
SHA256_LENGTH = 64
LOCK_SCHEMA_VERSION = 1


class FreezeError(RuntimeError):
    """The build or protected-tree state cannot be frozen or verified."""


def load_object(path: Path) -> dict[str, Any]:
    """Read one JSON object with a stable operator-facing error."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FreezeError(f"could not read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise FreezeError(f"{path} must contain one JSON object")
    return value


def require_mapping(owner: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Return a required child object."""

    value = owner.get(name)
    if not isinstance(value, dict):
        raise FreezeError(f"{name} must be an object")
    return value


def sha256_bytes(value: bytes) -> str:
    """Hash an in-memory value."""

    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file without loading a large firmware artifact at once."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise FreezeError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def canonical_json_sha256(value: object) -> str:
    """Hash JSON by semantic content rather than indentation."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def repository_path(path: Path, *, root: Path = REPOSITORY_ROOT) -> str:
    """Return a repository-relative path and reject path escapes."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise FreezeError(f"path is outside the repository: {path}") from error


def _is_excluded(path: Path, *, root: Path) -> bool:
    relative = path.relative_to(root)
    return (
        any(
            part in EXCLUDED_DIRECTORY_NAMES
            or part.endswith(".egg-info")
            or part.startswith(".")
            for part in relative.parts
        )
        or path.suffix == ".pyc"
    )


def collect_protected_files(*, root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    """Collect every source, test, package, protocol, and generated input."""

    files: set[Path] = set()
    for relative in PROTECTED_INPUTS:
        selected = root / relative
        if selected.is_file():
            files.add(selected.resolve())
            continue
        if selected.is_dir():
            files.update(
                path.resolve()
                for path in selected.rglob("*")
                if path.is_file() and not _is_excluded(path, root=root)
            )
            continue
        raise FreezeError(f"protected input does not exist: {relative}")
    if not files:
        raise FreezeError("protected input set is empty")
    return tuple(sorted(files, key=lambda path: repository_path(path, root=root)))


def file_records(
    paths: Sequence[Path], *, root: Path = REPOSITORY_ROOT
) -> list[dict[str, object]]:
    """Describe a stable set of files by path, length, and SHA-256."""

    return [
        {
            "path": repository_path(path, root=root),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def records_tree_sha256(records: Sequence[Mapping[str, object]]) -> str:
    """Hash the ordered path/size/digest triples in a protected tree."""

    digest = hashlib.sha256()
    for record in records:
        path = record.get("path")
        size = record.get("size_bytes")
        checksum = record.get("sha256")
        if (
            not isinstance(path, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(checksum, str)
        ):
            raise FreezeError("file record is malformed")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(checksum.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def manifest_artifacts(
    build_directory: Path,
    manifest: Mapping[str, Any],
) -> list[dict[str, object]]:
    """Validate and return the artifacts declared by one build manifest."""

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise FreezeError("build manifest artifacts must be a list")
    records: list[dict[str, object]] = []
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            raise FreezeError("build manifest artifact entry must be an object")
        relative = raw.get("path")
        expected_size = raw.get("size_bytes")
        expected_sha256 = raw.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != SHA256_LENGTH
        ):
            raise FreezeError("build manifest artifact entry is malformed")
        path = build_directory / relative
        if not path.is_file():
            raise FreezeError(f"build artifact is missing: {path}")
        actual_size = path.stat().st_size
        actual_sha256 = sha256_file(path)
        if actual_size != expected_size or actual_sha256 != expected_sha256:
            raise FreezeError(f"build artifact disagrees with its manifest: {path}")
        records.append(
            {
                "path": relative,
                "size_bytes": actual_size,
                "sha256": actual_sha256,
            }
        )
    records.sort(key=lambda item: str(item["path"]))
    suffixes = {Path(str(record["path"])).suffix.lower() for record in records}
    missing = REQUIRED_ARTIFACT_SUFFIXES - suffixes
    if missing:
        raise FreezeError(
            "build manifest is missing required artifacts: "
            + ", ".join(sorted(missing))
        )
    return records


def validate_candidate_build(
    candidate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, object]],
) -> None:
    """Require the generated-program candidate to describe the built image."""

    artifact = require_mapping(candidate, "artifact")
    firmware = require_mapping(candidate, "firmware")
    board = require_mapping(candidate, "board")
    source = require_mapping(manifest, "source")
    target = require_mapping(manifest, "target")
    artifact_name = artifact.get("name")
    matches = [record for record in artifacts if record.get("path") == artifact_name]
    if len(matches) != 1 or matches[0].get("sha256") != artifact.get("sha256"):
        raise FreezeError("candidate artifact identity does not match the build")
    comparisons = (
        ("source_id", firmware.get("source_id"), source.get("source_id")),
        ("build_id", firmware.get("build_id"), source.get("build_id")),
        ("fqbn", board.get("fqbn"), target.get("fqbn")),
    )
    mismatches = [name for name, left, right in comparisons if left != right]
    if mismatches:
        raise FreezeError("candidate/build identity mismatch: " + ", ".join(mismatches))
    if (
        source.get("firmware_inputs_clean") is not True
        or source.get("firmware_input_changes") != []
    ):
        raise FreezeError("build manifest reports dirty firmware inputs")


def validate_rebuilds(
    first_directory: Path,
    second_directory: Path,
) -> tuple[dict[str, Any], list[dict[str, object]], dict[str, str]]:
    """Require two manifests and every exported artifact to be identical."""

    first_manifest_path = first_directory / "build-manifest.json"
    second_manifest_path = second_directory / "build-manifest.json"
    first_manifest = load_object(first_manifest_path)
    second_manifest = load_object(second_manifest_path)
    first_artifacts = manifest_artifacts(first_directory, first_manifest)
    second_artifacts = manifest_artifacts(second_directory, second_manifest)
    if first_artifacts != second_artifacts:
        raise FreezeError("the two builds did not reproduce every artifact")
    stable_sections = (
        "schema_version",
        "target",
        "source",
        "memory_usage",
        "binary_inspection",
    )
    if any(
        first_manifest.get(name) != second_manifest.get(name)
        for name in stable_sections
    ):
        raise FreezeError("the two build manifests disagree in a stable section")
    manifest_hashes = {
        "first": sha256_file(first_manifest_path),
        "second": sha256_file(second_manifest_path),
    }
    if manifest_hashes["first"] != manifest_hashes["second"]:
        raise FreezeError("the two build manifests are not byte-identical")
    return second_manifest, second_artifacts, manifest_hashes


def current_git_commit(*, root: Path = REPOSITORY_ROOT) -> str:
    """Resolve the full commit that owns the protected snapshot."""

    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    commit = result.stdout.strip()
    if (
        result.returncode
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise FreezeError("Git did not report a full lowercase commit identity")
    return commit


def require_clean_protected_inputs(*, root: Path = REPOSITORY_ROOT) -> None:
    """Refuse to freeze uncommitted source or generated changes."""

    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "daq_api",
            "firmware",
            "protocol",
            "tools",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode:
        raise FreezeError("could not inspect protected Git state")
    permitted = "firmware/soak/candidate-freeze.json"
    changes = []
    for line in result.stdout.splitlines():
        path = line[3:].split(" -> ")[-1]
        if path != permitted:
            changes.append(line)
    if changes:
        raise FreezeError(
            "protected inputs have uncommitted changes: " + "; ".join(changes)
        )


def _copy_staged_build(
    build_directory: Path,
    artifact_records: Sequence[Mapping[str, object]],
    stage_directory: Path,
    *,
    root: Path = REPOSITORY_ROOT,
) -> list[dict[str, object]]:
    """Copy the accepted manifest/artifacts into a dedicated immutable stage."""

    if stage_directory.exists() and any(stage_directory.iterdir()):
        raise FreezeError(f"stage directory is not empty: {stage_directory}")
    stage_directory.mkdir(parents=True, exist_ok=True)
    names = ["build-manifest.json"] + [
        str(record["path"]) for record in artifact_records
    ]
    for name in names:
        source = build_directory / name
        destination = stage_directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return file_records(
        tuple(stage_directory / name for name in sorted(names)),
        root=root,
    )


def create_freeze(
    *,
    first_build_directory: Path,
    second_build_directory: Path,
    stage_directory: Path,
    candidate_path: Path = CANDIDATE_PATH,
    root: Path = REPOSITORY_ROOT,
    base_commit: str | None = None,
) -> dict[str, Any]:
    """Validate two builds, stage the second, and create the freeze object."""

    manifest, artifacts, manifest_hashes = validate_rebuilds(
        first_build_directory, second_build_directory
    )
    candidate = load_object(candidate_path)
    validate_candidate_build(candidate, manifest, artifacts)
    protected = file_records(collect_protected_files(root=root), root=root)
    staged = _copy_staged_build(
        second_build_directory, artifacts, stage_directory, root=root
    )
    source = require_mapping(manifest, "source")
    target = require_mapping(manifest, "target")
    compiler = require_mapping(manifest, "compiler")
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate": {
            "path": repository_path(candidate_path, root=root),
            "sha256": canonical_json_sha256(candidate),
            "artifact_name": require_mapping(candidate, "artifact").get("name"),
            "artifact_sha256": require_mapping(candidate, "artifact").get("sha256"),
            "source_id": source.get("source_id"),
            "build_id": source.get("build_id"),
            "fqbn": target.get("fqbn"),
        },
        "protected": {
            "base_git_commit": base_commit or current_git_commit(root=root),
            "tree_sha256": records_tree_sha256(protected),
            "file_count": len(protected),
            "files": protected,
        },
        "build": {
            "manifest_schema_version": manifest.get("schema_version"),
            "core_id": target.get("core_id"),
            "core_version": target.get("core_version"),
            "compiler_identity": compiler.get("identity"),
            "source": source,
            "memory_usage": manifest.get("memory_usage"),
            "binary_inspection": manifest.get("binary_inspection"),
        },
        "reproducibility": {
            "build_count": 2,
            "byte_identical": True,
            "manifest_sha256": manifest_hashes,
            "artifacts": artifacts,
        },
        "staged": {
            "directory": repository_path(stage_directory, root=root),
            "files": staged,
        },
    }


def write_freeze(path: Path, freeze: Mapping[str, Any]) -> None:
    """Persist one human-readable deterministic-key-order freeze record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _record_differences(
    expected: Sequence[Mapping[str, object]],
    actual: Sequence[Mapping[str, object]],
) -> list[str]:
    expected_by_path = {str(record.get("path")): record for record in expected}
    actual_by_path = {str(record.get("path")): record for record in actual}
    problems = [
        f"missing {path}" for path in sorted(expected_by_path.keys() - actual_by_path)
    ]
    problems.extend(
        f"added {path}" for path in sorted(actual_by_path.keys() - expected_by_path)
    )
    problems.extend(
        f"changed {path}"
        for path in sorted(expected_by_path.keys() & actual_by_path)
        if expected_by_path[path] != actual_by_path[path]
    )
    return problems


def verify_freeze(
    freeze: Mapping[str, Any], *, root: Path = REPOSITORY_ROOT
) -> dict[str, object]:
    """Fail closed if any protected or staged byte no longer matches."""

    if freeze.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise FreezeError(f"freeze schema_version must be {LOCK_SCHEMA_VERSION}")
    candidate_record = require_mapping(freeze, "candidate")
    protected = require_mapping(freeze, "protected")
    staged = require_mapping(freeze, "staged")
    expected_protected = protected.get("files")
    expected_staged = staged.get("files")
    if not isinstance(expected_protected, list) or not all(
        isinstance(record, dict) for record in expected_protected
    ):
        raise FreezeError("protected.files must be a list of objects")
    if not isinstance(expected_staged, list) or not all(
        isinstance(record, dict) for record in expected_staged
    ):
        raise FreezeError("staged.files must be a list of objects")

    actual_protected = file_records(collect_protected_files(root=root), root=root)
    differences = _record_differences(expected_protected, actual_protected)
    actual_tree = records_tree_sha256(actual_protected)
    if actual_tree != protected.get("tree_sha256"):
        differences.append("protected tree digest changed")

    stage_directory_value = staged.get("directory")
    if not isinstance(stage_directory_value, str):
        raise FreezeError("staged.directory must be text")
    stage_directory = (root / stage_directory_value).resolve()
    repository_path(stage_directory, root=root)
    actual_staged_paths: list[Path] = []
    for record in expected_staged:
        record_path = record.get("path")
        if not isinstance(record_path, str):
            raise FreezeError("staged file path must be text")
        try:
            relative = Path(record_path).relative_to(stage_directory_value)
        except ValueError as error:
            raise FreezeError(
                f"staged file is outside staged.directory: {record_path}"
            ) from error
        selected = (stage_directory / relative).resolve()
        repository_path(selected, root=root)
        actual_staged_paths.append(selected)
    if not all(path.is_file() for path in actual_staged_paths):
        missing = [str(path) for path in actual_staged_paths if not path.is_file()]
        differences.extend(f"missing staged artifact {path}" for path in missing)
    else:
        actual_staged = file_records(actual_staged_paths, root=root)
        differences.extend(_record_differences(expected_staged, actual_staged))

    candidate_path_value = candidate_record.get("path")
    if not isinstance(candidate_path_value, str):
        raise FreezeError("candidate.path must be text")
    candidate_path = (root / candidate_path_value).resolve()
    repository_path(candidate_path, root=root)
    candidate = load_object(candidate_path)
    if canonical_json_sha256(candidate) != candidate_record.get("sha256"):
        differences.append("candidate semantic digest changed")
    artifact = require_mapping(candidate, "artifact")
    firmware = require_mapping(candidate, "firmware")
    board = require_mapping(candidate, "board")
    identity_fields = (
        ("artifact_name", artifact.get("name")),
        ("artifact_sha256", artifact.get("sha256")),
        ("source_id", firmware.get("source_id")),
        ("build_id", firmware.get("build_id")),
        ("fqbn", board.get("fqbn")),
    )
    differences.extend(
        f"candidate {name} changed"
        for name, actual in identity_fields
        if candidate_record.get(name) != actual
    )
    if differences:
        raise FreezeError(
            "soak candidate freeze verification failed: " + "; ".join(differences)
        )
    return {
        "result": "PASS",
        "protected_file_count": len(actual_protected),
        "protected_tree_sha256": actual_tree,
        "artifact_sha256": candidate_record.get("artifact_sha256"),
        "source_id": candidate_record.get("source_id"),
        "build_id": candidate_record.get("build_id"),
        "fqbn": candidate_record.get("fqbn"),
        "staged_directory": stage_directory_value,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the create/check command line."""

    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_PATH)
    parser.add_argument("--first-build-directory", type=Path)
    parser.add_argument(
        "--second-build-directory", type=Path, default=BUILD_OUTPUT_DIRECTORY
    )
    parser.add_argument("--stage-directory", type=Path, default=DEFAULT_STAGE_DIRECTORY)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Create a candidate freeze or verify the existing one."""

    arguments = build_parser().parse_args(argv)
    try:
        if arguments.create:
            if arguments.first_build_directory is None:
                raise FreezeError("--create requires --first-build-directory")
            require_clean_protected_inputs()
            freeze = create_freeze(
                first_build_directory=arguments.first_build_directory,
                second_build_directory=arguments.second_build_directory,
                stage_directory=arguments.stage_directory,
                candidate_path=arguments.candidate,
            )
            write_freeze(arguments.lock, freeze)
            result = verify_freeze(freeze)
            result["action"] = "created"
            result["lock"] = repository_path(arguments.lock)
        else:
            result = verify_freeze(load_object(arguments.lock))
            result["action"] = "checked"
            result["lock"] = repository_path(arguments.lock)
    except (FreezeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
