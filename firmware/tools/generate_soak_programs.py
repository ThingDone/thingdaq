#!/usr/bin/env python3
"""Generate deterministic rig and standalone/installed Windows soak programs."""

from __future__ import annotations

import argparse
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
    config = {
        "mode": "physical-combined",
        "entry_point": entry_point,
        "generator_schema_version": 1,
        "candidate": windows_candidate,
        "candidate_sha256": candidate_sha,
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


def write_path_or_check(path: Path, expected: str, *, check: bool) -> list[str]:
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
        path.chmod(0o755)
    return [display]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on output drift")
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_PATH)
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
        rendered = render_programs(validator_source, candidate)
        windows_rendered = render_windows_program(
            validator_source,
            driver_source,
            candidate,
        )
        package_rendered = render_windows_program(
            validator_source,
            driver_source,
            candidate,
            entry_point="installed-package",
        )
        changed = write_or_check(
            rendered,
            args.output_directory,
            check=args.check,
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
                "outputs": sorted(
                    [*rendered, str(args.windows_output), str(args.package_output)]
                ),
                "updated": changed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
