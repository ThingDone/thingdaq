#!/usr/bin/env python3
"""Run one cold-boot input experiment; retain firmware, runner and raw evidence.

Uses the auxiliary-input branch's existing standalone validator. No pin drives,
loopback declaration, compression, output engine or CPU-clock changes are used.
The paired-bank diagnostic is opt-in, not a prerequisite for eight-pin tests.
The submission/preflight pattern follows the existing physical campaign helper.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import stat
import time
import zipfile
from pathlib import Path

import requests

BOARD = "teensy:avr:teensy40"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_program(source: str, settings: dict[str, str]) -> str:
    # Register a real module for dataclasses; avoid altering the validator text.
    return (
        "import os, sys, types\n"
        f"os.environ.update({settings!r})\n"
        "rig = types.ModuleType('input_isolation_rig')\n"
        "sys.modules[rig.__name__] = rig\n"
        f"exec(compile({source!r}, 'rig_aux_input_capture.py', 'exec'), rig.__dict__)\n"
        "sys.exit(rig.main())\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--case", choices=("CONTROL_GPIO", "CONTROL_COMBINED",
                                         "INPUT_GPIO", "INPUT_COMBINED"), required=True)
    parser.add_argument("--profile", type=int, choices=range(4), required=True)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--serial", type=int, default=20428100)
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--service", default="http://192.168.150.14:5000")
    parser.add_argument("--auth-file", type=Path, default=Path("/home/bill/.fw_api_key"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error("--seconds must be 1..600")
    if args.evidence_dir.exists():
        parser.error("evidence directory already exists; choose a new immutable run")
    if stat.S_IMODE(args.auth_file.stat().st_mode) & 0o077:
        parser.error("credential file must be private")
    auth = args.auth_file.read_text().strip()
    build = args.worktree / "firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std"
    firmware = (build / "firmware.ino.hex").read_bytes()
    manifest_bytes = (build / "build-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    source = (args.worktree / "firmware/tests/rig_aux_input_capture.py").read_text()
    build_id = manifest["source"]["build_id"]
    settings = {
        "AUX_INPUT_CASE": args.case,
        "AUX_INPUT_RATE_PROFILE": str(args.profile),
        "AUX_INPUT_CAPTURE_SECONDS": str(args.seconds),
        "AUX_INPUT_RUN_DIAGNOSTIC": "1" if args.diagnostic else "0",
        "EXPECTED_HARDWARE_SERIAL": str(args.serial),
        "EXPECTED_BUILD_ID": build_id,
    }
    program = make_program(source, settings)
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("firmware.ino.hex", firmware)

    def get(endpoint):
        response = requests.get(f"{args.service}/{endpoint}", timeout=10)
        response.raise_for_status()
        return response.json()

    def post(endpoint, fields):
        response = requests.post(f"{args.service}/{endpoint}",
                                 json={"auth": auth, **fields}, timeout=30)
        response.raise_for_status()
        return response.json()

    health = get("health")
    checks = health.get("checks", {})
    expected = {"coordinator_mode": "normal", "queue_depth": 0,
                "worker_thread_alive": True, "docker_reachable": True,
                "hub_reachable": True}
    if health.get("status") != "healthy" or any(checks.get(k) != v for k, v in expected.items()):
        raise RuntimeError("service not idle/healthy; no submission made")
    args.evidence_dir.mkdir(parents=True)

    def save(name, value):
        (args.evidence_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    save("provenance.json", {"settings": settings, "hex_sha256": digest(firmware),
                            "runner_sha256": digest(source.encode()),
                            "program_sha256": digest(program.encode()),
                            "service": args.service, "version": get("version"),
                            "health": health, "build_id": build_id})
    (args.evidence_dir / "firmware.ino.hex").write_bytes(firmware)
    (args.evidence_dir / "build-manifest.json").write_bytes(manifest_bytes)
    (args.evidence_dir / "rig-program.py").write_text(program)
    started = post("start", {"python": program, "board": BOARD,
                             "binary": base64.b64encode(archive_bytes.getvalue()).decode()})
    save("start.json", started)
    test_id = started["test_id"]
    print(f"Started {test_id}: {args.case} profile={args.profile} seconds={args.seconds}", flush=True)
    deadline = time.monotonic() + args.seconds + 120
    while time.monotonic() < deadline:
        status = post("status", {"test_id": test_id})
        save("status.json", status)
        if status.get("status") not in {"running", "busy", "queued", "pending"}:
            result = post("results", {"test_id": test_id})
            save("results.json", result)
            print(json.dumps(result, sort_keys=True), flush=True)
            return 0
        time.sleep(1)
    raise RuntimeError(f"job {test_id} exceeded deadline; inspect before further submissions")


if __name__ == "__main__":
    raise SystemExit(main())
