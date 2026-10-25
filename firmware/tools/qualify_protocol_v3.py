#!/usr/bin/env python3
"""Plan, run/resume, or independently validate exact-candidate qualification.

All rig HTTP is delegated to run_input_isolation, including idempotent admission,
5xx retries, queue-aware deadlines and retained-job recovery.
"""

from __future__ import annotations

import argparse
import ast
import base64
import io
import json
import os
import re
import shlex
import subprocess
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import run_input_isolation as rig
from protocol_v3_qualification import POLICY, json_hash, matrix, validate_evidence
from thingdone_daq import __version__
from thingdone_daq._generated import protocol_constants as v1
from thingdone_daq._generated import protocol_v2_constants as v2
from thingdone_daq._generated import protocol_v3_constants as v3
from thingdone_daq.models_v3 import V3Capabilities, V3Clocks, V3Settings

ROOT = Path(__file__).resolve().parents[2]
WORKER = "firmware/tests/rig_protocol_v3_qualification.py"
POLICY_SOURCE = "firmware/tools/protocol_v3_qualification.py"
RUNNER_INPUTS = (
    WORKER,
    POLICY_SOURCE,
    "firmware/tools/qualify_protocol_v3.py",
    "firmware/tools/run_input_isolation.py",
    "firmware/tests/rig_release_sdk.py",
    "firmware/soak/validator.py",
)


def save(path, value):
    # Atomic checkpoint: never expose a partially written acceptance record.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def sdk_archive(root=ROOT):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((root / "daq_api/src/thingdone_daq").rglob("*.py")):
            entry = zipfile.ZipInfo(path.relative_to(root / "daq_api/src").as_posix())
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    return output.getvalue()


def input_identity(root=ROOT):
    """Record this mapping in the new candidate; metadata-only commits may follow."""
    return {
        "sdk_version": __version__,
        "sdk_archive_sha256": rig.digest(sdk_archive(root)),
        "runner_sha256": {
            name: rig.digest((root / name).read_bytes()) for name in RUNNER_INPUTS
        },
        "schema_sha256": {
            name: rig.digest((root / "protocol" / name).read_bytes())
            for name in ("protocol-v1.json", "protocol-v2.json", "protocol-v3.json")
        },
    }


def check_candidate(candidate):
    if candidate.get("policy") != POLICY or candidate.get("source_dirty") is not False:
        raise ValueError("candidate policy/clean source identity required")
    if not re.fullmatch("[0-9a-f]{40}", candidate.get("source_revision", "")):
        raise ValueError("full source revision required")
    for name in ("firmware_sha256", "build_manifest_sha256"):
        if not re.fullmatch("[0-9a-f]{64}", candidate.get(name, "")):
            raise ValueError(f"invalid {name}")
    identity = candidate["identity"]
    if (
        set(identity)
        != {"hardware_serial", "build_id", "firmware_version", "board_id", "mcu_id"}
        or not isinstance(identity["hardware_serial"], str)
        or not identity["hardware_serial"]
        or not identity["build_id"]
        or not identity["firmware_version"]
        or identity["board_id"] != 1
        or identity["mcu_id"] != 1
    ):
        raise ValueError("complete physical board/build identity required")
    if candidate["inputs"] != input_identity():
        raise ValueError("SDK/schema/runner inputs differ from candidate")
    rows = matrix(candidate["capabilities_hex"])
    if candidate["matrix"] != rows:
        raise ValueError("candidate matrix differs from policy")
    return rows


def prepare_candidate(manifest_path, serial):
    """Build the new policy projection without claiming a freeze or rig PASS.

    Preserve the artifact/firmware/board fields consumed by the existing
    freeze_soak_candidate tool; all new qualification fields are additive.
    """
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    source, public = manifest["source"], manifest["public_protocol"]
    if source["firmware_inputs_clean"] is not True or not public["enabled"]:
        raise ValueError("prepare requires a clean public-v3 build manifest")
    configurations = tuple(V3Settings(**row) for row in public["configurations"])
    rate_ids = {s.rate_profile for s in configurations}
    canonical = V3Capabilities.canonical()
    # encodeV3CapabilitiesResponse uses the existing v1 packet pages and v2
    # control-frame storage, not the larger generic v3 wire maxima.
    samples = v1.MAX_DATA_FRAME_BYTES - v3.MIN_FRAME_BYTES - v3.DATA_PREFIX_BYTES
    caps = replace(
        canonical,
        defaults=V3Settings(**public["defaults"]),
        cpu_profiles=(V3Clocks(**public["clocks"]),),
        rate_profiles=tuple(
            p for p in canonical.rate_profiles if p.rate_profile in rate_ids
        ),
        configurations=configurations,
        max_data_frame_bytes=v1.MAX_DATA_FRAME_BYTES,
        max_control_frame_bytes=v2.MAX_CONTROL_FRAME_BYTES,
        max_logical_payload_bytes=samples,
        max_encoded_sample_bytes=samples,
        max_adc_pairs=samples // 4,
        max_gpio8_samples=samples,
        max_gpio16_samples=samples // 2,
    )
    artifact = next(
        row for row in manifest["artifacts"] if row["path"] == "firmware.ino.hex"
    )
    version = public["firmware_version"]
    candidate = {
        "schema_version": 1,
        "policy": POLICY,
        "source_revision": source["git_commit"],
        "source_dirty": False,
        "firmware_sha256": artifact["sha256"],
        "build_manifest_sha256": rig.digest(manifest_bytes),
        "artifact": {"name": artifact["path"], "sha256": artifact["sha256"]},
        "firmware": {
            "version": version,
            "source_id": source["source_id"],
            "build_id": source["build_id"],
        },
        "board": {
            "fqbn": manifest["target"]["fqbn"],
            "hardware_serial": serial,
            "board_id": 1,
            "mcu_id": 1,
        },
        "protocol": {"version": 3, "checksum_algorithm": 1, "checksum_name": "ADLER32"},
        "identity": {
            "hardware_serial": serial,
            "board_id": 1,
            "mcu_id": 1,
            "build_id": source["build_id"],
            "firmware_version": ".".join(map(str, version)),
        },
        "inputs": input_identity(),
        "capabilities_hex": caps.to_payload().hex(),
        "matrix": matrix(caps.to_payload().hex()),
        "physical_qualification": "NOT_RUN",
    }
    check_candidate(candidate)
    return candidate


def resource_program():
    """Bundle existing boundary probes without copying or importing rig mains.

    Both owners remain standalone rig programs. Select their unchanged function
    definitions, and freeze the complete source files in RUNNER_INPUTS.
    """
    program = ""
    for module, path, names in (
        ("rig_release_sdk", "firmware/tests/rig_release_sdk.py", {"host_cpu"}),
        (
            "firmware.soak.validator",
            "firmware/soak/validator.py",
            {"_cgroup_cpu_statistics", "CpuTracker"},
        ),
    ):
        source = (ROOT / path).read_text()
        definitions = [
            node
            for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        ]
        if {node.name for node in definitions} != names:
            raise ValueError(f"missing resource probes in {path}")
        selected = "import os, platform\nfrom pathlib import Path\n" + "\n\n".join(
            ast.get_source_segment(source, node) for node in definitions
        )
        program += (
            f"resources = types.ModuleType({module!r})\n"
            "sys.modules[resources.__name__] = resources\n"
            f"exec(compile({selected!r}, {path!r}, 'exec'), resources.__dict__)\n"
        )
    return program


def make_program(candidate, cell):
    package = base64.b64encode(sdk_archive()).decode()
    settings = {
        "QUALIFICATION_CANDIDATE": json.dumps(candidate, sort_keys=True),
        "QUALIFICATION_CELL": json.dumps(cell, sort_keys=True),
    }
    # Follow the existing rig SDK bundling convention. Neither the service nor
    # the worker downloads code or installs a different package at execution.
    return (
        (
            "import base64, pathlib, sys, tempfile, types\n"
            "sdk_dir = tempfile.TemporaryDirectory(prefix='thingdaq-qualification-')\n"
            "sdk_path = pathlib.Path(sdk_dir.name) / 'sdk.zip'\n"
            f"sdk_path.write_bytes(base64.b64decode({package!r}))\n"
            "sys.path.insert(0, str(sdk_path))\n"
            "policy = types.ModuleType('protocol_v3_qualification')\n"
            "sys.modules[policy.__name__] = policy\n"
            f"exec(compile({(ROOT / POLICY_SOURCE).read_text()!r}, 'policy.py', 'exec'), policy.__dict__)\n"
        )
        + resource_program()
        + rig.make_program((ROOT / WORKER).read_text(), settings)
    )


def allocate_job_cpu(service, directory):
    """Provision only the accepted job's container; never change service defaults.

    The worker independently waits for/readbacks this allocation before serial
    open. A resume rechecks live Docker state instead of trusting a saved receipt.
    Queue waiting stays entirely inside the existing rig request loop.
    """
    verified = False

    def provision(test_id):
        nonlocal verified
        if verified:
            return
        if str(uuid.UUID(test_id)) != test_id:
            raise ValueError("invalid rig job ID")
        script = f"""import docker, json
client = docker.from_env()
job = {test_id!r}
matched = [c for c in client.containers.list() if any(
    m['Destination'] == '/storage' and m['Source'].rstrip('/').endswith('/' + job)
    for m in c.attrs['Mounts'])]
assert len(matched) <= 1, 'ambiguous job container'
for container in matched:
    before = container.attrs['HostConfig']
    container.update(cpu_quota=200000, cpu_period=100000)
    container.reload()
    after = container.attrs['HostConfig']
    assert after['CpuQuota'] == 200000 and after['CpuPeriod'] == 100000
    print(json.dumps(dict(job_id=job, container_id=container.id,
        before_quota=before['CpuQuota'], before_period=before['CpuPeriod'],
        quota=after['CpuQuota'], period=after['CpuPeriod'])))
"""
        host = os.environ.get("FW_RIG_SSH", f"bill@{urlsplit(service).hostname}")
        command = shlex.join(
            ["/home/bill/.virtualenvs/remote_firmware_testing/bin/python", "-c", script]
        )
        response = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        if response:
            receipt = json.loads(response)
            if (receipt["job_id"], receipt["quota"], receipt["period"]) != (
                test_id,
                200000,
                100000,
            ):
                raise ValueError("job CPU allocation readback mismatch")
            save(directory / "cpu-allocation.json", receipt)
            verified = True

    return provision


def retained_records(candidate, output):
    """Derive records from authoritative saved results; never trust summary.json."""
    records = []
    for directory in sorted(output.glob("*/attempt-*")):
        label = directory.parent.name
        record = {"cell_id": label, "outcome": "INCONCLUSIVE", "job_id": None}
        try:
            provenance = json.loads((directory / "provenance.json").read_text())
            if provenance["candidate_sha256"] != json_hash(candidate):
                raise ValueError("saved candidate mismatch")
            cell = next(row for row in candidate["matrix"] if row["id"] == label)
            expected_program = make_program(candidate, cell)
            program = (directory / "rig-program.py").read_text()
            firmware = (directory / "firmware.ino.hex").read_bytes()
            if (
                program != expected_program
                or rig.digest(firmware) != candidate["firmware_sha256"]
            ):
                raise ValueError("saved program/firmware identity mismatch")
            submission = json.loads((directory / "submission.json").read_text())
            if (
                submission["program_sha256"] != rig.digest(program.encode())
                or submission["firmware_sha256"] != candidate["firmware_sha256"]
                or submission["service"] != provenance["service"]
            ):
                raise ValueError("submission input identity mismatch")
            job = json.loads((directory / "start.json").read_text())["test_id"]
            result = json.loads((directory / "results.json").read_text())["results"]
            if result.get("test_id") != job:
                raise ValueError("service result job ID mismatch")
            evidence = [
                json.loads(line.removeprefix("QUALIFICATION "))
                for line in result.get("stdout", "").splitlines()
                if line.startswith("QUALIFICATION ")
            ]
            if len(evidence) != 1:
                raise ValueError("missing/duplicate worker record")
            record = evidence[0]
            setup = record.get("host_setup", {})
            if (
                setup.get("cpu.max", "").split() != ["200000", "100000"]
                or len(setup.get("affinity", [])) < 2
            ):
                raise ValueError("missing/insufficient worker CPU allocation")
            record["job_id"] = job
            if not (
                result.get("completed") is True
                and result.get("program_success") is True
                and result.get("exit_code") == 0
            ):
                record["outcome"] = "FAIL"
            record["raw_result_path"] = str(directory / "results.json")
        except (OSError, KeyError, TypeError, ValueError, StopIteration) as error:
            record["outcome"] = "INCONCLUSIVE" if isinstance(error, OSError) else "FAIL"
            record["retention_error"] = str(error)
        records.append(record)
    return records


def evaluate(candidate, output):
    records = retained_records(candidate, output)
    result = validate_evidence(candidate, records)
    incomplete = [r for r in records if r.get("retention_error")]
    result["retention_errors"] = incomplete
    save(output / "qualification.json", result)
    return result


def verify_artifacts(candidate, firmware_path, manifest_path):
    firmware = firmware_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    if rig.digest(firmware) != candidate["firmware_sha256"]:
        raise ValueError("firmware differs from candidate")
    if rig.digest(manifest_bytes) != candidate["build_manifest_sha256"]:
        raise ValueError("build manifest differs from candidate")
    manifest = json.loads(manifest_bytes)
    rig.verify_hex(firmware, manifest)
    if (
        manifest["source"]["git_commit"] != candidate["source_revision"]
        or manifest["source"]["firmware_inputs_clean"] is not True
        or manifest["source"]["build_id"] != candidate["identity"]["build_id"]
        or manifest["release_policy"]["core_hz"] != 600_000_000
        or manifest["release_policy"]["protocol_version"] != 3
        or manifest.get("input_experiment")
    ):
        raise ValueError("candidate build provenance/defaults mismatch")
    # Do not allow tracked or untracked input edits to borrow a clean identity.
    dirty = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "firmware/src",
            "firmware/firmware.ino",
            "firmware/tools",
            *RUNNER_INPUTS,
            "daq_api/src",
            "protocol",
            "tools",
        ],
        text=True,
    )
    if dirty.strip():
        raise ValueError("qualification inputs are dirty; commit and freeze first")
    subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--exit-code",
            "--quiet",
            candidate["source_revision"],
            "--",
            "firmware/src",
            "firmware/firmware.ino",
            "firmware/tools",
            *RUNNER_INPUTS,
            "daq_api/src",
            "protocol",
            "tools",
        ],
        check=True,
    )
    return firmware


def run_campaign(args, candidate, rows):
    output = args.output
    if output.exists() and not args.resume:
        raise ValueError("existing evidence requires --resume")
    firmware = verify_artifacts(candidate, args.firmware, args.build_manifest)
    auth = os.environ["FW_RIG_AUTH"]
    output.mkdir(parents=True, exist_ok=True)
    saved = output / "candidate.json"
    if saved.exists() and json.loads(saved.read_text()) != candidate:
        raise ValueError("campaign belongs to another candidate")
    save(saved, candidate)
    if args.cell:
        rows = [row for row in rows if row["id"] == args.cell]
        if not rows:
            raise ValueError("unknown matrix cell")
    for cell in rows:
        directory = output / cell["id"] / "attempt-001"
        if (directory / "results.json").exists():
            continue
        directory.mkdir(parents=True, exist_ok=True)
        program = make_program(candidate, cell)
        planned = rig.validate_program_budget(max(1, cell["seconds"]), cell["cycles"])
        if (directory / "submission.json").exists() and not args.resume:
            raise ValueError("retained submission requires --resume")
        if (directory / "provenance.json").exists():
            previous = json.loads((directory / "provenance.json").read_text())
            if (
                previous["candidate_sha256"] != json_hash(candidate)
                or previous["service"] != args.service
                or (directory / "rig-program.py").read_text() != program
                or (directory / "firmware.ino.hex").read_bytes() != firmware
            ):
                raise ValueError("retained request differs; do not resubmit")
        else:
            save(
                directory / "provenance.json",
                {
                    "candidate_sha256": json_hash(candidate),
                    "service": args.service,
                    "cell": cell,
                    "planned_program_seconds": planned,
                    "inputs": candidate["inputs"],
                    "source_revision": candidate["source_revision"],
                    "source_dirty": False,
                    "firmware_sha256": candidate["firmware_sha256"],
                },
            )
            (directory / "firmware.ino.hex").write_bytes(firmware)
            (directory / "rig-program.py").write_text(program)
        try:
            # Existing helper reconciles saved tag or follows saved job ID.
            rig.submit_program(
                args.service,
                auth,
                firmware,
                program,
                directory,
                planned + 90,
                on_active=allocate_job_cpu(args.service, directory),
            )
        except Exception as error:
            save(
                directory / "client-error.json",
                {"error": f"{type(error).__name__}: {error}"},
            )
            evaluate(candidate, output)
            raise
        result = evaluate(candidate, output)
        print(
            json.dumps({"cell_id": cell["id"], "campaign": result["outcome"]}),
            flush=True,
        )
        if result["outcome"] == "FAIL":
            # Retain failure and allow an operator to inspect before another flash.
            return result
    return evaluate(candidate, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("inputs", "prepare", "plan", "run", "validate")
    )
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--service", default=os.environ.get("FW_RIG_SERVICE"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cell")
    parser.add_argument("--hardware-serial")
    args = parser.parse_args(argv)
    if args.action == "inputs":
        print(json.dumps(input_identity(), indent=2, sort_keys=True))
        return 0
    if args.action == "prepare":
        if not all((args.build_manifest, args.hardware_serial, args.output)):
            parser.error(
                "prepare requires --build-manifest, --hardware-serial, --output"
            )
        if args.output.exists():
            parser.error("candidate already exists; choose a new path")
        save(args.output, prepare_candidate(args.build_manifest, args.hardware_serial))
        return 0
    if not args.candidate:
        parser.error("--candidate is required")
    candidate = json.loads(args.candidate.read_text())
    rows = check_candidate(candidate)
    if args.action == "plan":
        print(
            json.dumps(
                {"policy": POLICY, "outcome": "NOT_RUN", "matrix": rows}, indent=2
            )
        )
        return 0
    if not args.output:
        parser.error("--output is required")
    if args.action == "run":
        if not all((args.firmware, args.build_manifest, args.service)):
            parser.error("run requires --firmware, --build-manifest, --service")
        result = run_campaign(args, candidate, rows)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        result = evaluate(candidate, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
