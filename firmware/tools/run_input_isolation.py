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
CASES = ("CONTROL_GPIO", "CONTROL_COMBINED", "INPUT_GPIO", "INPUT_COMBINED")


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
    if manifest.get("release_policy", {}).get("fixed_1mhz") is True:
        if (
            manifest["target"]["fqbn"]
            != "teensy:avr:teensy40:usb=serial,speed=450,opt=o2std"
        ):
            raise ValueError("release CPU disagrees with compiled target")
        return {
            "AUX_INPUT_EQUAL_RATES": "0",
            "AUX_INPUT_CPU_MHZ": "450",
            "AUX_INPUT_RELEASE_FIXED_1MHZ": "1",
        }
    if experiment is None:
        return {"AUX_INPUT_EQUAL_RATES": "0", "AUX_INPUT_CPU_MHZ": "600"}
    cpu = experiment["cpu_mhz"]
    equal = experiment["equal_rates"]
    if cpu not in (600, 450) or not isinstance(equal, bool):
        raise ValueError("unsupported input experiment clock/rate selection")
    expected_fqbn = f"teensy:avr:teensy40:usb=serial,speed={cpu},opt=o2std"
    if manifest["target"]["fqbn"] != expected_fqbn:
        raise ValueError("experiment CPU disagrees with compiled target")
    return {
        "AUX_INPUT_EQUAL_RATES": "1" if equal else "0",
        "AUX_INPUT_CPU_MHZ": str(cpu),
    }


def validate_program_budget(seconds: float, cells: int) -> float:
    # Same 120-second margin below the 900-second container limit documented
    # by doc/guides/soak-harness.md. Keep separate long cells in separate jobs.
    planned = 30 + (seconds + 5) * cells
    if not 1 <= seconds <= 600 or cells < 1 or planned > 780:
        raise ValueError(
            "sequence exceeds the safe service runtime budget; split into separate jobs"
        )
    return planned


def classify_result(result: dict, *, expected_cells: int | None = None) -> dict:
    details = result.get("results", {})
    evidence = [
        json.loads(line[9:])
        for line in details.get("stdout", "").splitlines()
        if line.startswith("EVIDENCE ")
    ]
    exit_code = details.get("exit_code")
    if (
        not details.get("completed")
        or not details.get("program_success")
        or (isinstance(exit_code, int) and exit_code < 0)
    ):
        outcome = "INFRASTRUCTURE_FAIL"
    elif (
        details.get("exit_code") == 0
        and evidence
        and all(row.get("result") == "PASS" for row in evidence)
    ):
        outcome = (
            "PASS"
            if expected_cells is None or len(evidence) == expected_cells
            else "INFRASTRUCTURE_FAIL"
        )
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
    cases: tuple[str, ...] | None = None,
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
    if cases is not None and (
        sequence is None
        or len(cases) != len(sequence)
        or any(case not in CASES for case in cases)
    ):
        raise ValueError("cases must name one valid case per selected profile")
    if cases is not None:
        # Observe the real START replies through the existing exchange path.
        # A reboot between cells must not masquerade as a successful transition.
        program += (
            "last_started_run_id = None\n"
            "original_exchange = rig.SerialLink.exchange\n"
            "def tracked_exchange(link, kind, *args, **kwargs):\n"
            "    global last_started_run_id\n"
            "    frame, latency = original_exchange(link, kind, *args, **kwargs)\n"
            "    if kind == rig.START_REQUEST:\n"
            "        rig.response_success(frame, rig.START_RESPONSE)\n"
            "        expected = (((last_started_run_id + 1) & 0xffffffff) or 1) if last_started_run_id is not None else frame.run_id\n"
            "        if frame.run_id != expected:\n"
            "            raise rig.ProtocolFailure(f'run ID reset/jump across sequence: expected {expected}, got {frame.run_id}')\n"
            "        last_started_run_id = frame.run_id\n"
            "        rig.emit_event('sequence_start', run_id=frame.run_id, case=os.environ['AUX_INPUT_CASE'], profile=os.environ['AUX_INPUT_RATE_PROFILE'])\n"
            "    return frame, latency\n"
            "rig.SerialLink.exchange = tracked_exchange\n"
        )
    if sequence is not None:
        if not sequence or any(profile not in range(5) for profile in sequence):
            raise ValueError("profiles must contain IDs 0..4")
        program += f"for index, profile in enumerate({sequence!r}):\n"
        if cases is not None:
            program += f"    os.environ['AUX_INPUT_CASE'] = {cases!r}[index]\n"
        program += (
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
    parser.add_argument(
        "--build-dir",
        type=Path,
        help="explicit build directory; experimental settings come from its manifest",
    )
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument(
        "--case",
        choices=CASES,
        required=True,
    )
    parser.add_argument("--profile", type=int, choices=range(5), required=True)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--serial", type=int, default=20428100)
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument(
        "--temperature",
        action="store_true",
        help="require die temperature before, during and after each run",
    )
    parser.add_argument(
        "--host-api",
        action="store_true",
        help="validate the public SDK against the release firmware",
    )
    sequence_group = parser.add_mutually_exclusive_group()
    sequence_group.add_argument(
        "--cycle", action="store_true", help="exercise 0,1,2,3,0 without reflashing"
    )
    sequence_group.add_argument(
        "--profiles",
        type=int,
        nargs="+",
        choices=range(5),
        help="explicit profile sequence without reflashing; stops on first failure",
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=CASES,
        help="one case per --profiles/--cycle cell; changes width without reflashing",
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
    validator = "rig_release_sdk.py" if args.host_api else "rig_aux_input_capture.py"
    source = (args.worktree / "firmware/tests" / validator).read_text()
    build_id = manifest["source"]["build_id"]
    settings = {
        "AUX_INPUT_CASE": args.case,
        "AUX_INPUT_RATE_PROFILE": str(args.profile),
        "AUX_INPUT_CAPTURE_SECONDS": str(args.seconds),
        "AUX_INPUT_RUN_DIAGNOSTIC": "1" if args.diagnostic else "0",
        "AUX_INPUT_TEMPERATURE": "1" if args.temperature else "0",
        "EXPECTED_HARDWARE_SERIAL": str(args.serial),
        "EXPECTED_BUILD_ID": build_id,
    }
    experiment = manifest.get("input_experiment")
    settings.update(experiment_settings(manifest))
    profiles = tuple(args.profiles) if args.profiles is not None else None
    sequence = [0, 1, 2, 3, 0] if args.cycle else list(profiles or (args.profile,))
    try:
        planned_program_seconds = validate_program_budget(args.seconds, len(sequence))
    except ValueError as error:
        parser.error(str(error))
    cases = tuple(args.cases) if args.cases is not None else None
    if cases is not None and (
        not (args.cycle or profiles) or len(cases) != len(sequence)
    ):
        parser.error("--cases needs one case per --profiles/--cycle cell")
    program = make_program(
        source, settings, cycle=args.cycle, profiles=profiles, cases=cases
    )
    if args.host_api:
        if args.cycle or profiles or cases:
            parser.error("--host-api runs its own bounded mode sequence")
        package_bytes = io.BytesIO()
        with zipfile.ZipFile(package_bytes, "w", zipfile.ZIP_DEFLATED) as package:
            for path in sorted((args.worktree / "daq_api/src/thingdaq").rglob("*.py")):
                package.writestr(
                    str(path.relative_to(args.worktree / "daq_api/src")),
                    path.read_bytes(),
                )
        encoded = base64.b64encode(package_bytes.getvalue()).decode()
        program = (
            "import base64, pathlib, sys, tempfile\n"
            "package_dir = tempfile.TemporaryDirectory(prefix='thingdaq-sdk-')\n"
            "package_path = pathlib.Path(package_dir.name) / 'thingdaq.zip'\n"
            f"package_path.write_bytes(base64.b64decode({encoded!r}))\n"
            "sys.path.insert(0, str(package_path))\n"
        ) + program
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
            "case_sequence": list(cases or (args.case,) * len(sequence)),
            "planned_program_seconds": planned_program_seconds,
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
            summary = classify_result(result, expected_cells=len(sequence))
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
