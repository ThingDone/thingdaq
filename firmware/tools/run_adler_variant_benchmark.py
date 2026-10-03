#!/usr/bin/env python3
"""Submit the protocol-v2 Adler experiment to the established Teensy rig."""

from __future__ import annotations

import argparse
import base64
import io
import json
import stat
import zipfile
from pathlib import Path

import run_input_isolation as rig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--service", required=True)
    parser.add_argument("--serial", type=int, default=20428100)
    parser.add_argument("--auth-file", type=Path, default=Path.home() / ".fw_api_key")
    args = parser.parse_args()
    if args.evidence_dir.exists():
        parser.error("choose a new immutable evidence directory")
    if stat.S_IMODE(args.auth_file.stat().st_mode) & 0o077:
        parser.error("credential file must be private")

    firmware = (args.build_dir / "firmware.ino.hex").read_bytes()
    manifest_bytes = (args.build_dir / "build-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    rig.verify_hex(firmware, manifest)
    source = (args.worktree / "firmware/tests/rig_adler_variant_benchmark.py").read_text()
    program = rig.make_program(
        source,
        {
            "EXPECTED_HARDWARE_SERIAL": str(args.serial),
            "EXPECTED_BUILD_ID": manifest["source"]["build_id"],
        },
    )
    package_bytes = io.BytesIO()
    with zipfile.ZipFile(package_bytes, "w", zipfile.ZIP_DEFLATED) as package:
        for path in sorted((args.worktree / "daq_api/src/thingdone_daq").rglob("*.py")):
            package.writestr(
                str(path.relative_to(args.worktree / "daq_api/src")), path.read_bytes()
            )
    program = (
        "import base64, pathlib, sys, tempfile\n"
        "package_dir = tempfile.TemporaryDirectory(prefix='thingdaq-sdk-')\n"
        "package_path = pathlib.Path(package_dir.name) / 'thingdone_daq.zip'\n"
        f"package_path.write_bytes(base64.b64decode({base64.b64encode(package_bytes.getvalue()).decode()!r}))\n"
        "sys.path.insert(0, str(package_path))\n"
    ) + program

    health = rig.service_preflight(args.service)
    args.evidence_dir.mkdir(parents=True)
    (args.evidence_dir / "preflight.json").write_text(
        json.dumps(health, indent=2, sort_keys=True) + "\n"
    )
    (args.evidence_dir / "build-manifest.json").write_bytes(manifest_bytes)
    (args.evidence_dir / "rig-program.py").write_text(program)
    result = rig.submit_program(
        args.service,
        args.auth_file.read_text().strip(),
        firmware,
        program,
        args.evidence_dir,
        180,
    )
    summary = rig.classify_result(result, expected_cells=1)
    (args.evidence_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary), flush=True)
    return 0 if summary["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
