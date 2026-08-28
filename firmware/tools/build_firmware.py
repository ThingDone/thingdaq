#!/usr/bin/env python3
"""Verify the pinned Teensy toolchain and export the foundation firmware."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKETCH_DIRECTORY = REPOSITORY_ROOT / "firmware"
FQBN = "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std"
CORE_ID = "teensy:avr"
CORE_VERSION = "1.62.0"
OUTPUT_DIRECTORY = (
    SKETCH_DIRECTORY / "build" / ("teensy.avr.teensy40.usb_serial.speed_600.opt_o2std")
)
MANIFEST_NAME = "build-manifest.json"
ARTIFACT_SUFFIXES = {".bin", ".eep", ".elf", ".hex", ".map"}


class BuildError(RuntimeError):
    """A reproducibility check or firmware build failed."""


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one tool command and retain output for diagnostics and provenance."""

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise BuildError(f"could not run {command[0]!r}: {error}") from error

    if result.returncode != 0:
        detail = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise BuildError(
            f"command failed with exit code {result.returncode}: "
            f"{shlex.join(command)}\n{detail}"
        )
    return result


def installed_core_version(core_inventory: Any, core_id: str) -> str | None:
    """Extract an installed core version from Arduino CLI's JSON inventory."""

    if not isinstance(core_inventory, dict):
        return None
    platforms = core_inventory.get("platforms", [])
    if not isinstance(platforms, list):
        return None
    for platform in platforms:
        if isinstance(platform, dict) and platform.get("id") == core_id:
            version = platform.get("installed_version")
            return version if isinstance(version, str) else None
    return None


def parse_build_properties(output: str) -> dict[str, str]:
    """Parse the resolved key=value properties printed by Arduino CLI."""

    properties: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def resolve_compiler(properties: dict[str, str]) -> Path:
    """Resolve the C++ compiler executable selected by the pinned core."""

    compiler_name = properties.get("compiler.cpp.cmd")
    compiler_directory = properties.get("compiler.path")
    if compiler_name and compiler_directory:
        compiler = Path(compiler_name)
        if not compiler.is_absolute():
            compiler = Path(compiler_directory) / compiler
        if compiler.is_file():
            return compiler.resolve()

    recipe = properties.get("recipe.cpp.o.pattern", "")
    if recipe:
        recipe_compiler = Path(shlex.split(recipe)[0])
        if recipe_compiler.is_file():
            return recipe_compiler.resolve()

    raise BuildError("Arduino CLI did not resolve an executable C++ compiler")


def compile_command(arduino_cli: Path) -> list[str]:
    """Return the immutable command used for every supported firmware build."""

    return [
        str(arduino_cli),
        "compile",
        "--fqbn",
        FQBN,
        "--export-binaries",
        "--output-dir",
        str(OUTPUT_DIRECTORY),
        str(SKETCH_DIRECTORY),
    ]


def sha256(path: Path) -> str:
    """Hash one exported build artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(arduino_cli_name: str) -> Path:
    """Validate tool identities, compile the exact target, and write a manifest."""

    resolved_cli = shutil.which(arduino_cli_name)
    if resolved_cli is None:
        raise BuildError(f"Arduino CLI executable not found: {arduino_cli_name!r}")
    arduino_cli = Path(resolved_cli).resolve()

    cli_identity = run_command([str(arduino_cli), "version"]).stdout.strip()
    core_result = run_command([str(arduino_cli), "core", "list", "--format", "json"])
    try:
        core_inventory = json.loads(core_result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError("Arduino CLI returned invalid core inventory JSON") from error

    installed_version = installed_core_version(core_inventory, CORE_ID)
    if installed_version != CORE_VERSION:
        found = installed_version or "not installed"
        raise BuildError(
            f"requires {CORE_ID} {CORE_VERSION}, but found {found}; "
            "install the pinned core before building"
        )

    properties_result = run_command(
        [
            str(arduino_cli),
            "compile",
            "--fqbn",
            FQBN,
            "--show-properties",
            str(SKETCH_DIRECTORY),
        ]
    )
    properties = parse_build_properties(properties_result.stdout)
    compiler = resolve_compiler(properties)
    compiler_identity = run_command([str(compiler), "--version"]).stdout.strip()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    command = compile_command(arduino_cli)
    compile_result = run_command(command)
    if compile_result.stdout:
        print(compile_result.stdout, end="")
    if compile_result.stderr:
        print(compile_result.stderr, end="", file=sys.stderr)

    artifacts = sorted(
        path
        for path in OUTPUT_DIRECTORY.rglob("*")
        if path.is_file() and path.suffix.lower() in ARTIFACT_SUFFIXES
    )
    if not any(path.suffix.lower() == ".hex" for path in artifacts):
        raise BuildError(f"compile produced no HEX artifact in {OUTPUT_DIRECTORY}")

    manifest = {
        "schema_version": 1,
        "target": {
            "fqbn": FQBN,
            "core_id": CORE_ID,
            "core_version": installed_version,
        },
        "arduino_cli": {
            "path": str(arduino_cli),
            "identity": cli_identity,
        },
        "compiler": {
            "path": str(compiler),
            "identity": compiler_identity.splitlines()[0],
        },
        "command": command,
        "sketch_directory": str(SKETCH_DIRECTORY.relative_to(REPOSITORY_ROOT)),
        "output_directory": str(OUTPUT_DIRECTORY.relative_to(REPOSITORY_ROOT)),
        "artifacts": [
            {
                "path": str(path.relative_to(OUTPUT_DIRECTORY)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in artifacts
        ],
    }
    manifest_path = OUTPUT_DIRECTORY / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Arduino CLI: {cli_identity.splitlines()[0]}")
    print(f"Teensy core: {CORE_ID} {installed_version}")
    print(f"Compiler: {compiler_identity.splitlines()[0]}")
    print(f"Build manifest: {manifest_path}")
    return manifest_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the one host-specific override without weakening target pins."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="Arduino CLI executable name or path (default: arduino-cli)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""

    arguments = parse_args(argv)
    try:
        build(arguments.arduino_cli)
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
