#!/usr/bin/env python3
"""Prove standalone and installed soak entry paths remain conformant."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STANDALONE_PATH = REPOSITORY_ROOT / "daq_api/scripts/windows_soak.py"
INSTALLED_PATH = REPOSITORY_ROOT / "daq_api/src/teensy_daq/soak.py"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
CONFIG_BLOCK = re.compile(
    r"^# <soak-generated-config>\n.*?^# </soak-generated-config>$",
    re.MULTILINE | re.DOTALL,
)
COMMAND_FIXTURES = (
    ("info-request.bin", "INFO_REQUEST", 1, None),
    ("configure-request.bin", "CONFIGURE_REQUEST", 2, "configuration"),
    ("start-request.bin", "START_REQUEST", 3, None),
    ("get-status-request.bin", "GET_STATUS_REQUEST", 4, None),
    ("stop-request.bin", "STOP_REQUEST", 5, None),
    ("reset-stats-request.bin", "RESET_STATS_REQUEST", 6, None),
)
EXPECTED_GRADES = {
    "valid": ("PASS", None),
    "checksum_corruption": ("FAIL", "checksum_corruption"),
    "pattern_error": ("FAIL", "pattern_error"),
    "source_gap": ("FAIL", "source_gap"),
}


class ConformanceError(RuntimeError):
    """The two entry paths or their pinned fixtures disagree."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_module(path: Path, role: str) -> ModuleType:
    if not path.is_file():
        raise ConformanceError(f"missing {role} implementation: {path}")
    name = f"_teensy_daq_soak_conformance_{role.replace('-', '_')}"
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ConformanceError(f"could not load {role} implementation: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException as error:
        raise ConformanceError(
            f"could not import {role} implementation: {type(error).__name__}: {error}"
        ) from error
    return module


def _mapping(owner: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = owner.get(name)
    if not isinstance(value, Mapping):
        raise ConformanceError(f"conformance vector {name} is not an object")
    return value


def _normalized_source(path: Path) -> bytes:
    source = path.read_text(encoding="utf-8")
    matches = CONFIG_BLOCK.findall(source)
    if len(matches) != 1:
        raise ConformanceError(f"{path} must contain one generated-config block")
    normalized = CONFIG_BLOCK.sub(
        "# <soak-generated-config>\n"
        "# role-specific metadata normalized by conformance gate\n"
        "# </soak-generated-config>",
        source,
        count=1,
    )
    return normalized.encode("utf-8")


def _configuration_payload(module: ModuleType) -> bytes:
    return module.CONFIGURATION.pack(
        module.STREAM_BOTH,
        module.SOURCE_SYNTHETIC,
        module.CHECKSUM_ADLER32,
        0,
        module.DATA_FRAME_BYTES,
    )


def _verify_commands(module: ModuleType, role: str) -> list[dict[str, object]]:
    configuration = _configuration_payload(module)
    results: list[dict[str, object]] = []
    for filename, kind_name, request_id, payload_kind in COMMAND_FIXTURES:
        fixture = (FIXTURE_DIRECTORY / filename).read_bytes()
        payload = configuration if payload_kind == "configuration" else b""
        encoded = module.encode_request(
            int(getattr(module, kind_name)),
            request_id,
            payload,
        )
        if encoded != fixture:
            raise ConformanceError(
                f"{role} command encoding differs from {filename}: "
                f"{_sha256(encoded)} != {_sha256(fixture)}"
            )
        results.append(
            {
                "fixture": filename,
                "size_bytes": len(fixture),
                "sha256": _sha256(fixture),
            }
        )
    return results


def _verify_vector(module: ModuleType, role: str) -> dict[str, object]:
    raw = module.soak_conformance_vector()
    if not isinstance(raw, dict):
        raise ConformanceError(f"{role} conformance vector is not an object")
    vector: dict[str, object] = raw
    if vector.get("schema_version") != 1:
        raise ConformanceError(f"{role} conformance schema is not version 1")

    frames = _mapping(vector, "frames")
    expected_transcript = (FIXTURE_DIRECTORY / "adc-data.bin").read_bytes() + (
        FIXTURE_DIRECTORY / "gpio-data.bin"
    ).read_bytes()
    if frames.get("transcript_bytes") != len(expected_transcript) or frames.get(
        "transcript_sha256"
    ) != _sha256(expected_transcript):
        raise ConformanceError(
            f"{role} generated frame transcript differs from protocol fixtures"
        )

    grades = _mapping(vector, "grades")
    for name, expected_grade in EXPECTED_GRADES.items():
        grade = _mapping(grades, name)
        observed = (grade.get("result"), grade.get("failure_category"))
        if observed != expected_grade:
            raise ConformanceError(
                f"{role} grade {name!r} is {observed!r}, expected {expected_grade!r}"
            )

    valid = _mapping(grades, "valid")
    metrics = _mapping(valid, "metrics")
    expected_metrics = {
        "adc_pair_rate_hz": float(module.ADC_PAIR_RATE_HZ),
        "gpio_sample_rate_hz": float(module.GPIO_SAMPLE_RATE_HZ),
        "payload_bytes_per_second": float(
            module.TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND
        ),
        "framed_bytes_per_second": float(
            module.TARGET_COMBINED_FRAMED_BYTES_PER_SECOND
        ),
    }
    for name, expected_metric in expected_metrics.items():
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConformanceError(f"{role} metric {name!r} is not numeric")
        if not math.isclose(float(value), expected_metric, rel_tol=1e-12, abs_tol=1e-9):
            raise ConformanceError(
                f"{role} metric {name!r} is {value!r}, expected {expected_metric!r}"
            )
    return vector


def check_conformance(
    standalone_path: Path = STANDALONE_PATH,
    installed_path: Path = INSTALLED_PATH,
) -> dict[str, object]:
    standalone_source = _normalized_source(standalone_path)
    installed_source = _normalized_source(installed_path)
    if standalone_source != installed_source:
        raise ConformanceError(
            "standalone and installed implementations differ outside generated metadata"
        )

    standalone = _load_module(standalone_path, "windows-standalone")
    installed = _load_module(installed_path, "installed-package")
    modules = (
        ("windows-standalone", standalone),
        ("installed-package", installed),
    )
    for expected_role, module in modules:
        config = getattr(module, "GENERATED_CONFIG", None)
        if (
            not isinstance(config, Mapping)
            or config.get("entry_point") != expected_role
        ):
            raise ConformanceError(
                f"{expected_role} generated metadata has the wrong entry point"
            )

    command_fixtures = _verify_commands(standalone, "windows-standalone")
    installed_commands = _verify_commands(installed, "installed-package")
    if command_fixtures != installed_commands:
        raise ConformanceError(
            "entry paths produced different command fixture evidence"
        )

    standalone_vector = _verify_vector(standalone, "windows-standalone")
    installed_vector = _verify_vector(installed, "installed-package")
    if standalone_vector != installed_vector:
        raise ConformanceError(
            "entry paths produced different deterministic conformance vectors"
        )

    vector_sha256 = _sha256(_canonical_json_bytes(standalone_vector))
    normalized_sha256 = _sha256(standalone_source)
    return {
        "schema_version": 1,
        "result": "PASS",
        "checks": {
            "normalized_implementation_bytes_identical": True,
            "protocol_command_fixtures_identical": True,
            "fragmented_frame_transcript_identical": True,
            "metrics_identical": True,
            "fixture_grades_identical": True,
        },
        "entry_points": [role for role, _module in modules],
        "normalized_implementation_sha256": normalized_sha256,
        "conformance_vector_sha256": vector_sha256,
        "command_fixtures": command_fixtures,
        "grades": {
            name: {"result": result, "failure_category": category}
            for name, (result, category) in EXPECTED_GRADES.items()
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standalone", type=Path, default=STANDALONE_PATH)
    parser.add_argument("--installed", type=Path, default=INSTALLED_PATH)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = check_conformance(arguments.standalone, arguments.installed)
    except (ConformanceError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            result,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
            separators=None if arguments.pretty else (",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
