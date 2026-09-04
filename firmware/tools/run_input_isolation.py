#!/usr/bin/env python3
"""Run one cold-boot input experiment; retain firmware, runner and raw evidence.

Uses the auxiliary-input branch's existing standalone validator. No pin drives,
loopback declaration, compression or output engine is used.
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

BOARD = "teensy:avr:teensy40"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_hex(firmware: bytes, manifest: dict) -> None:
    record = next(
        row for row in manifest["artifacts"] if row["path"] == "firmware.ino.hex"
    )
    if record["sha256"] != digest(firmware) or record["size_bytes"] != len(firmware):
        raise ValueError(
            "HEX does not match the build manifest; rebuild before submitting"
        )


def experiment_settings(manifest: dict) -> dict[str, str]:
    """Use only explicit build-manifest selections, never inferred filenames."""
    experiment = manifest.get("input_experiment")
    if experiment is None:
        return {"AUX_INPUT_EQUAL_RATES": "0", "AUX_INPUT_CPU_MHZ": "600"}
    cpu = experiment["cpu_mhz"]
    equal = experiment["equal_rates"]
    if cpu not in (600, 450) or not isinstance(equal, bool):
        raise ValueError("unsupported input experiment clock/rate selection")
    expected_fqbn = f"teensy:avr:teensy40:usb=serial,speed={cpu},opt=o2std"
    if manifest["target"]["fqbn"] != expected_fqbn:
        raise ValueError("experiment CPU disagrees with compiled target")
    return {"AUX_INPUT_EQUAL_RATES": "1" if equal else "0",
            "AUX_INPUT_CPU_MHZ": str(cpu)}


def classify_result(result: dict) -> dict:
    details = result.get("results", {})
    evidence = [
        json.loads(line[9:])
        for line in details.get("stdout", "").splitlines()
        if line.startswith("EVIDENCE ")
    ]
    if not details.get("completed") or not details.get("program_success"):
        outcome = "INFRASTRUCTURE_FAIL"
    elif (
        details.get("exit_code") == 0
        and evidence
        and all(row.get("result") == "PASS" for row in evidence)
    ):
        outcome = "PASS"
    else:
        outcome = "TEST_FAIL"
    return {
        "outcome": outcome,
        "test_id": details.get("test_id"),
        "exit_code": details.get("exit_code"),
        "message": details.get("message"),
        "evidence": evidence,
    }


def make_program(
    source: str,
    settings: dict[str, str],
    *,
    cycle: bool = False,
    profiles: tuple[int, ...] | None = None,
) -> str:
    # Register a real module for dataclasses; avoid altering the validator text.
    program = (
        "import os, sys, types\n"
        f"os.environ.update({settings!r})\n"
        "rig = types.ModuleType('input_isolation_rig')\n"
        "sys.modules[rig.__name__] = rig\n"
        f"exec(compile({source!r}, 'rig_aux_input_capture.py', 'exec'), rig.__dict__)\n"
    )
    if cycle and profiles is not None:
        raise ValueError("choose either cycle or explicit profiles")
    sequence = (0, 1, 2, 3, 0) if cycle else profiles
    if sequence is not None:
        if not sequence or any(profile not in range(4) for profile in sequence):
            raise ValueError("profiles must contain IDs 0..3")
        program += (
            f"for profile in {sequence!r}:\n"
            "    os.environ['AUX_INPUT_RATE_PROFILE'] = str(profile)\n"
            "    result = rig.main()\n"
            "    if result: sys.exit(result)\n"
            "sys.exit(0)\n"
        )
    else:
        program += "sys.exit(rig.main())\n"
    return program


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--build-dir", type=Path,
                        help="explicit build directory; experimental settings come from its manifest")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument(
        "--case",
        choices=("CONTROL_GPIO", "CONTROL_COMBINED", "INPUT_GPIO", "INPUT_COMBINED"),
        required=True,
    )
    parser.add_argument("--profile", type=int, choices=range(4), required=True)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--serial", type=int, default=20428100)
    parser.add_argument("--diagnostic", action="store_true")
    sequence_group = parser.add_mutually_exclusive_group()
    sequence_group.add_argument(
        "--cycle", action="store_true", help="exercise 0,1,2,3,0 without reflashing"
    )
    sequence_group.add_argument(
        "--profiles", type=int, nargs="+", choices=range(4),
        help="explicit profile sequence without reflashing; stops on first failure",
    )
    parser.add_argument("--service", default="http://192.168.150.14:5000")
    parser.add_argument(
        "--auth-file", type=Path, default=Path("/home/bill/.fw_api_key")
    )
    args = parser.parse_args()
    # Only live submission needs the service client's optional HTTP dependency.
    import requests

    if not 1 <= args.seconds <= 600:
        parser.error("--seconds must be 1..600")
    if args.evidence_dir.exists():
        parser.error("evidence directory already exists; choose a new immutable run")
    if stat.S_IMODE(args.auth_file.stat().st_mode) & 0o077:
        parser.error("credential file must be private")
    auth = args.auth_file.read_text().strip()
    build = args.build_dir or (
        args.worktree
        / "firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std"
    )
    firmware = (build / "firmware.ino.hex").read_bytes()
    manifest_bytes = (build / "build-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    verify_hex(firmware, manifest)
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
    experiment = manifest.get("input_experiment")
    settings.update(experiment_settings(manifest))
    profiles = tuple(args.profiles) if args.profiles is not None else None
    sequence = [0, 1, 2, 3, 0] if args.cycle else list(profiles or (args.profile,))
    program = make_program(source, settings, cycle=args.cycle, profiles=profiles)
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("firmware.ino.hex", firmware)

    def get(endpoint):
        response = requests.get(f"{args.service}/{endpoint}", timeout=10)
        response.raise_for_status()
        return response.json()

    def post(endpoint, fields):
        response = requests.post(
            f"{args.service}/{endpoint}", json={"auth": auth, **fields}, timeout=30
        )
        response.raise_for_status()
        return response.json()

    health = get("health")
    checks = health.get("checks", {})
    expected = {
        "coordinator_mode": "normal",
        "queue_depth": 0,
        "worker_thread_alive": True,
        "docker_reachable": True,
        "hub_reachable": True,
    }
    if health.get("status") != "healthy" or any(
        checks.get(k) != v for k, v in expected.items()
    ):
        raise RuntimeError("service not idle/healthy; no submission made")
    args.evidence_dir.mkdir(parents=True)

    def save(name, value):
        (args.evidence_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n"
        )

    save(
        "provenance.json",
        {
            "settings": settings,
            "hex_sha256": digest(firmware),
            "runner_sha256": digest(source.encode()),
            "program_sha256": digest(program.encode()),
            "service": args.service,
            "version": get("version"),
            "health": health,
            "build_id": build_id,
            "manifest_sha256": digest(manifest_bytes),
            "source": manifest["source"],
            "input_experiment": experiment,
            "profile_sequence": sequence,
        },
    )
    (args.evidence_dir / "firmware.ino.hex").write_bytes(firmware)
    (args.evidence_dir / "build-manifest.json").write_bytes(manifest_bytes)
    (args.evidence_dir / "rig-program.py").write_text(program)
    started = post(
        "start",
        {
            "python": program,
            "board": BOARD,
            "binary": base64.b64encode(archive_bytes.getvalue()).decode(),
        },
    )
    save("start.json", started)
    test_id = started["test_id"]
    print(
        f"Started {test_id}: {args.case} profile={args.profile} seconds={args.seconds}",
        flush=True,
    )
    deadline = time.monotonic() + (args.seconds + 5) * len(sequence) + 120
    while time.monotonic() < deadline:
        status = post("status", {"test_id": test_id})
        save("status.json", status)
        if status.get("status") not in {"running", "busy", "queued", "pending"}:
            result = post("results", {"test_id": test_id})
            save("results.json", result)
            summary = classify_result(result)
            save("summary.json", summary)
            details = result.get("results", {})
            if not details.get("program_success"):
                print(f"Infrastructure failure: {details.get('message')}", flush=True)
            for line in details.get("stdout", "").splitlines():
                if line.startswith("EVIDENCE ") or any(
                    word in line for word in ('"fatal"', '"debug_trace"')
                ):
                    print(line, flush=True)
            return 0 if summary["outcome"] == "PASS" else 1
        time.sleep(1)
    raise RuntimeError(
        f"job {test_id} exceeded deadline; inspect before further submissions"
    )


if __name__ == "__main__":
    raise SystemExit(main())
