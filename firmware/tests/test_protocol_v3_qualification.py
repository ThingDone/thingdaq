"""Offline implementation checks; none of these fixtures is physical evidence."""

from __future__ import annotations

import contextlib
import copy
import importlib
import io
import json
import shlex
import struct
import subprocess
import sys
import zlib
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from test_rig_http_retry import Clock, reply
from test_v3_cross_language import (
    capabilities,
    command,
    cpp,  # noqa: F401 - reuse the existing portable firmware fixture
    exchange,
    replies,
    request,
)
from thingdone_daq import DAQConfiguration
from thingdone_daq._generated import protocol_v2_constants as legacy
from thingdone_daq.models_v3 import V3Capabilities, V3Settings
from thingdone_daq.protocol_v2 import TemperatureReading, encode_v2_frame
from thingdone_daq.protocol_v3 import encode_adc_payload, encode_v3_frame
from thingdone_daq.simulator import SimulatedDevice
from thingdone_daq.simulator_v3 import SimulatedV3Device
from thingdone_daq.transport import InMemoryTransport

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
policy = importlib.import_module("protocol_v3_qualification")
runner = importlib.import_module("qualify_protocol_v3")
worker = importlib.import_module("rig_protocol_v3_qualification")


@pytest.mark.parametrize(
    "setup,delay,accepted",
    [
        ({"cpu.max": "50000 100000", "affinity": [0, 1]}, 0, False),
        ({"cpu.max": "200000 100000", "affinity": [0]}, 0, False),
        ({}, 0, False),
        ({"cpu.max": "200000 100000", "affinity": [0, 1]}, 0, True),
        ({"cpu.max": "200000 100000", "affinity": [0, 1]}, 2, True),
    ],
    ids=["half-core", "one-cpu-affinity", "missing", "two-cores", "delayed"],
)
def test_worker_cpu_admission_before_serial(
    monkeypatch, capsys, setup, delay, accepted
):
    # Reproduce the failed rig's half-core allocation at the actual entry point.
    # Stub only OS/serial boundaries, retaining the production admission loop.
    clock = Clock()
    opened, captures = [], []
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(worker.time, "sleep", clock.sleep)
    monkeypatch.setattr(
        worker, "host_cpu", lambda: setup if clock.now >= delay else {}, raising=False
    )
    monkeypatch.setattr(
        worker, "SerialTransport", lambda port: opened.append((port, clock.now))
    )

    def capture(*args):
        captures.append(args)
        return {"outcome": "PASS"}

    monkeypatch.setattr(worker, "run", capture)
    monkeypatch.setenv("QUALIFICATION_CANDIDATE", "{}")
    monkeypatch.setenv("QUALIFICATION_CELL", '{"id":"cpu-regression"}')
    monkeypatch.setenv("SERIAL_PORT", "test-only")
    assert worker.main() == (0 if accepted else 1)
    record = json.loads(capsys.readouterr().out.removeprefix("QUALIFICATION "))
    if accepted:
        assert opened == [("test-only", delay)]
        assert len(captures) == 1
    else:
        assert opened == captures == []
        assert clock.now == 30
        assert record["outcome"] == "FAIL" and record["captures"] == []


@pytest.mark.parametrize("fault", [None, "ambiguous", "readback"])
def test_cpu_allocation_targets_only_accepted_job_and_rechecks_on_resume(
    monkeypatch, tmp_path, fault
):
    job = "4e475671-5925-4e12-908b-c93d8711053a"

    class Container:
        def __init__(self, name):
            self.id = name
            self.attrs = {
                "Mounts": [{"Source": "/jobs/" + name, "Destination": "/storage"}],
                "HostConfig": {"CpuQuota": 50000, "CpuPeriod": 100000},
            }
            self.updates = []

        def update(self, **kwargs):
            self.updates.append(kwargs)
            if fault != "readback":
                self.attrs["HostConfig"] = {
                    "CpuQuota": kwargs["cpu_quota"],
                    "CpuPeriod": kwargs["cpu_period"],
                }

        def reload(self):
            pass

    selected, other = Container(job), Container("other-job")
    containers = []
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "docker",
        SimpleNamespace(
            from_env=lambda: SimpleNamespace(
                containers=SimpleNamespace(list=lambda: containers)
            )
        ),
    )

    def ssh(command, **kwargs):
        calls.append(command)
        assert command[0] == "ssh" and kwargs["timeout"] == 10 and kwargs["check"]
        output = io.StringIO()
        # Execute the emitted remote program against fake Docker, not a canned receipt.
        with contextlib.redirect_stdout(output):
            exec(shlex.split(command[-1])[-1], {})  # noqa: S102 - trusted runner source
        return SimpleNamespace(stdout=output.getvalue())

    monkeypatch.setattr(runner.subprocess, "run", ssh)
    provision = runner.allocate_job_cpu("http://rig.invalid", tmp_path)
    provision(job)  # Container not created yet: must retry, not cache success.
    receipt = tmp_path / "cpu-allocation.json"
    assert not receipt.exists()
    containers.extend([selected, other])
    if fault == "ambiguous":
        containers.append(Container(job))
    if fault:
        with pytest.raises(AssertionError):
            provision(job)
        assert not receipt.exists()
        assert other.updates == []
        if fault == "ambiguous":
            assert selected.updates == []
        return
    provision(job)
    provision(job)
    assert len(calls) == 2
    assert selected.updates == [{"cpu_quota": 200000, "cpu_period": 100000}]
    assert other.updates == []
    assert json.loads(receipt.read_text())["job_id"] == job
    selected.attrs["HostConfig"]["CpuQuota"] = 50000
    runner.allocate_job_cpu("http://rig.invalid", tmp_path)(job)
    assert len(calls) == 3 and len(selected.updates) == 2
    assert json.loads(receipt.read_text())["before_quota"] == 50000


def test_bundled_resource_probes_run_without_repository_imports():
    program = "import sys, types\n" + runner.resource_program()
    program += (
        "from rig_release_sdk import host_cpu\n"
        "from firmware.soak.validator import CpuTracker\n"
        "assert 'affinity' in host_cpu()\n"
        "cpu = CpuTracker(); cpu.sample(); assert 'delta' in cpu.summary()\n"
    )
    subprocess.run([sys.executable, "-I", "-c", program], check=True)


def normal_capabilities():
    caps = V3Capabilities.canonical()
    return replace(
        caps,
        cpu_profiles=tuple(
            p for p in caps.cpu_profiles if p.cpu_clock_hz == 600_000_000
        ),
        configurations=tuple(s for s in caps.configurations if s.cpu_profile == 1),
    )


def candidate():
    caps = normal_capabilities()
    return {
        "policy": policy.POLICY,
        "source_revision": "a" * 40,
        "source_dirty": False,
        "firmware_sha256": runner.rig.digest(b"firmware"),
        "build_manifest_sha256": "b" * 64,
        "identity": {
            "hardware_serial": "12345",
            "build_id": "thingdaq-test",
            "firmware_version": "1.2.0",
            "board_id": 1,
            "mcu_id": 1,
        },
        "inputs": runner.input_identity(),
        "capabilities_hex": caps.to_payload().hex(),
        "matrix": policy.matrix(caps.to_payload().hex()),
    }


def test_matrix_complete_bounded_and_missing_physical_never_passes():
    frozen = candidate()
    rows = runner.check_candidate(frozen)
    smoke = [row for row in rows if row["kind"] == "smoke"]
    assert len(smoke) == 48
    assert {s["settings_hex"] for s in smoke} == {
        s.to_bytes().hex() for s in normal_capabilities().configurations
    }
    assert all(s["seconds"] == 60 for s in smoke)
    assert len([r for r in rows if r["kind"] == "soak" and r["seconds"] == 600]) == 3
    assert next(r for r in rows if r["kind"] == "lifecycle")["cycles"] == 20
    assert len([r for r in rows if r["kind"] == "legacy"]) == 6
    for row in rows:
        assert (
            runner.rig.validate_program_budget(max(1, row["seconds"]), row["cycles"])
            <= 780
        )
    assert policy.validate_evidence(frozen, [])["outcome"] == "NOT_RUN"
    frozen["inputs"]["sdk_archive_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="inputs differ"):
        runner.check_candidate(frozen)


def test_negative_matrix_matches_firmware_errors_and_preserves_settings(cpp):  # noqa: F811
    caps = capabilities(cpp)
    if cpp[1] != 600:
        with pytest.raises(ValueError, match="fixed-600"):
            policy.matrix(caps.to_payload().hex())
        return
    cell = next(
        r for r in policy.matrix(caps.to_payload().hex()) if r["kind"] == "negative"
    )
    operations = []
    for index, payload in enumerate(cell["rejected_hex"]):
        operations.extend(
            (
                request(command(17, bytes.fromhex(payload), 3 * index + 1)),
                request(command(29, request_id=3 * index + 2)),
                request(command(16, request_id=3 * index + 3)),
            )
        )
    frames, _ = exchange(cpp, operations)
    responses = replies(frames)
    for index, payload in enumerate(cell["rejected_hex"]):
        assert responses[3 * index + 1].error_code == cell["expected_errors"][payload]
        assert responses[3 * index + 2].value.settings == caps.defaults
        assert responses[3 * index + 3].value.clocks.cpu_clock_hz == 600_000_000


def test_wire_oracle_matches_all_portable_firmware_tuples(cpp):  # noqa: F811
    caps = capabilities(cpp)
    operations = []
    for run, settings in enumerate(caps.configurations, 1):
        base = run * 10
        operations.extend(
            (
                request(command(17, settings.to_bytes(), base)),
                request(command(18, request_id=base + 1)),
                "P 0",
                "P 1",
                "P 2",
                "P 3",
                request(command(20, request_id=base + 2)),
                request(command(19, request_id=base + 3)),
            )
        )
    frames, _ = exchange(cpp, operations, mode="codec")
    for run, settings in enumerate(caps.configurations, 1):
        tap = worker.WireTap(None)
        tap.reset(settings.gpio_width_bits // 8)
        data = [f for f in frames if f.header.run_id == run and f.header.kind in (1, 2)]
        wire = b"".join(f.to_bytes() for f in data)
        for offset in range(0, len(wire), 137):
            tap.accept(wire[offset : offset + 137])
        snapshot = tap.snapshot()
        assert snapshot["errors"] == snapshot["partial_bytes"] == 0
        for name, bit in (("adc", 1), ("gpio", 2)):
            row = snapshot[name]
            source_frames = [f for f in data if f.header.kind == bit]
            assert row["items"] == sum(f.header.item_count for f in source_frames)
            assert row["frames"] == len(source_frames)
            assert row["gap_items"] == 0
            if int(settings.stream_mask) & bit:
                assert row["sample_checks"] > 0
                assert row["versions"] == [3]
                assert row["wire_bytes"] == sum(
                    f.header.total_length for f in source_frames
                )
                assert row["encoded_bytes"] == sum(
                    len(f.payload) - 12 for f in source_frames
                )


def test_oracle_rejects_corruption_private_frames_and_unflagged_gaps():
    payload = encode_adc_payload([(1, 2)] * 12)
    frame = encode_v3_frame(1, payload, run_id=1, item_count=12)
    tap = worker.WireTap(None)
    tap.accept(frame)
    assert tap.snapshot()["adc"]["items"] == 12
    for offset, value in ((4, 0x83), (48, frame[48] ^ 1)):
        broken = bytearray(frame)
        broken[offset] = value
        with pytest.raises(ValueError):
            worker.WireTap(None).accept(broken)
    gap = encode_v3_frame(
        1, payload, run_id=1, item_count=12, sequence=2, first_sample_ticks=192
    )
    with pytest.raises(ValueError, match="unflagged"):
        worker.WireTap(None).accept(gap)


def test_invalid_negative_payload_reaches_wire_with_partial_writes():
    output = bytearray()
    transport = SimpleNamespace(
        write=lambda data: output.extend(data[:7]) or min(len(data), 7)
    )
    tap = worker.WireTap(transport)
    settings = V3Settings.defaults().to_bytes()
    invalid = settings[:4] + b"\x03" + settings[5:]
    tap.override_configure = invalid
    request_wire = encode_v3_frame(17, settings, request_id=19)
    assert tap.write(request_wire) == len(request_wire)
    assert output[44:-4] == invalid
    assert int.from_bytes(output[-4:], "little") == zlib.adler32(output[:-4])
    assert struct.unpack_from("<I", output, 28)[0] == 19


def test_temperature_retry_and_abort(monkeypatch):
    readings = iter(
        (
            TemperatureReading(legacy.TemperatureStatus.NOT_READY, None),
            TemperatureReading(legacy.TemperatureStatus.VALID, 79999),
        )
    )
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        worker,
        "legacy_command",
        lambda daq, _: SimpleNamespace(value=daq.get_temperature()),
    )
    samples = []
    worker.temperature(
        SimpleNamespace(get_temperature=lambda: next(readings)), samples, "before"
    )
    assert len(samples) == 2
    with pytest.raises(ValueError, match="80 C"):
        worker.temperature(
            SimpleNamespace(
                get_temperature=lambda: TemperatureReading(
                    legacy.TemperatureStatus.VALID, 80000
                )
            ),
            [],
            "running",
        )
    with pytest.raises(ValueError, match="retry budget"):
        worker.temperature(
            SimpleNamespace(
                get_temperature=lambda: TemperatureReading(
                    legacy.TemperatureStatus.NOT_READY, None
                )
            ),
            [],
            "running",
        )


def test_worker_never_accepts_simulator_as_physical():
    frozen = candidate()
    record = worker.run(
        frozen, frozen["matrix"][0], InMemoryTransport(device=SimulatedV3Device())
    )
    assert record["outcome"] == "FAIL"
    assert record["physical"] is False
    assert record["info"]["simulated"] is True


def test_worker_lifecycle_executes_and_retains_partial_failure(monkeypatch):
    frozen = candidate()
    device = SimulatedV3Device(build_id="thingdaq-test")
    original_info = device.info
    monkeypatch.setattr(
        device,
        "info",
        lambda: replace(
            original_info(),
            simulated=False,
            hardware_serial="12345",
            firmware_version="1.2.0",
        ),
    )
    receive = device.receive
    # The v3 simulator lacks the physical firmware's legacy ownership STATUS.
    # Reuse the v2 wire fixture for this orchestration-only readback.
    legacy_device = SimulatedDevice(protocol_version=2)

    def with_temperature(data):
        if data[4:6] == bytes((2, legacy.FrameKind.GET_STATUS_REQUEST)):
            return legacy_device.receive(data)
        if data[4:6] == bytes((2, legacy.FrameKind.GET_TEMPERATURE_REQUEST)):
            return (
                encode_v2_frame(
                    legacy.FrameKind.GET_TEMPERATURE_RESPONSE,
                    struct.pack("<BBHBBHi", 0, 0, 0, 0, 0, 0, 45000),
                    request_id=struct.unpack_from("<I", data, 28)[0],
                ),
            )
        return receive(data)

    monkeypatch.setattr(device, "receive", with_temperature)
    # The simulator deliberately has no physical rate or hardware diagnostics.
    # Exercise worker orchestration separately from the fail-closed policy.
    monkeypatch.setattr(worker, "validate_capture", lambda *_: [])
    monkeypatch.setattr(worker, "clock_measurement", lambda _: clock_fixture())
    monkeypatch.setattr(
        worker.WireTap,
        "request_stream_frame",
        lambda self: self.transport.request_stream_frame(),
        raising=False,
    )
    cell = dict(
        next(r for r in frozen["matrix"] if r["kind"] == "lifecycle"),
        cycles=2,
        seconds=0.03,
    )
    record = worker.run(
        frozen, cell, InMemoryTransport(device=device, stream_interval=0.001)
    )
    assert record["outcome"] == "PASS", record.get("error")
    assert [r["run_id"] for r in record["captures"]] == [1, 2]
    assert [r["settings_hex"] for r in record["captures"]] == [
        cell["settings_hex"],
        cell["alternate_hex"],
    ]
    assert all(r["stopped"] for r in record["captures"])
    # Even a locally passing orchestrator transcript is not qualifying evidence.
    record["job_id"] = "offline-fixture"
    assert policy.validate_evidence(frozen, [record])["outcome"] == "FAIL"


def test_saved_attempt_resume_uses_same_program_and_retains_failure(
    monkeypatch, tmp_path
):
    frozen = candidate()
    cell = frozen["matrix"][0]
    calls = []
    monkeypatch.setenv("FW_RIG_AUTH", "test-only")
    monkeypatch.setattr(runner, "verify_artifacts", lambda *_: b"firmware")

    def submit(service, auth, firmware, program, directory, timeout, **kwargs):
        calls.append((firmware, program, directory))
        runner.save(
            directory / "submission.json",
            {
                "agent_name": "retained",
                "service": service,
                "program_sha256": runner.rig.digest(program.encode()),
                "firmware_sha256": runner.rig.digest(firmware),
            },
        )
        raise OSError("temporary transport interruption")

    monkeypatch.setattr(runner.rig, "submit_program", submit)
    args = SimpleNamespace(
        output=tmp_path / "campaign",
        resume=False,
        firmware=None,
        build_manifest=None,
        cell=cell["id"],
        service="http://fake.invalid",
    )
    with pytest.raises(OSError):
        runner.run_campaign(args, frozen, [cell])
    args.resume = True
    with pytest.raises(OSError):
        runner.run_campaign(args, frozen, [cell])
    assert calls[0] == calls[1]
    assert (calls[0][2] / "client-error.json").exists()
    result = json.loads((args.output / "qualification.json").read_text())
    assert result["outcome"] == "INCONCLUSIVE"
    assert result["retention_errors"]
    compile(calls[0][1], "bundled-qualification.py", "exec")


def test_failed_capture_cannot_be_erased_by_later_pass_label():
    frozen = candidate()
    cell = frozen["matrix"][0]
    base = {
        "cell_id": cell["id"],
        "cell": cell,
        "candidate_sha256": policy.json_hash(frozen),
        "physical": True,
        "info": {**frozen["identity"], "protocol_version": 3, "simulated": False},
        "capabilities_hex": frozen["capabilities_hex"],
        "captures": [],
    }
    result = policy.validate_evidence(
        frozen,
        [
            {**base, "job_id": "failed", "outcome": "FAIL"},
            {**base, "job_id": "retry", "outcome": "PASS"},
        ],
    )
    assert result["outcome"] == "FAIL"
    assert any("retained attempt outcome FAIL" in p for p in result["problems"])


def clock_fixture():
    return {
        "request": {"rate_hz": 1_000_000, "event_count": 8192},
        "dwt_counter_hz": 600_000_000,
        "pit_clock_hz": 24_000_000,
        "pit_load_value": 23,
        "hardware_error_flags": 0,
        "dwt_elapsed_cycles": 8192 * 600,
        "scheduled_event_count": 8192,
        "dma_sample_count": 8192,
    }


def measured_fixture(cell, run_id=1):
    """Artificial accounting transcript for the policy, never saved as rig data."""
    settings = V3Settings.from_bytes(bytes.fromhex(cell["settings_hex"]))
    caps = normal_capabilities()
    clocks = asdict(caps.cpu_profiles[0])
    status = {name: 0 for name in policy.HEALTH_FIELDS}
    status.update(state=1, device_state=1, pending_frames=0, packet_owned_depth=0)
    row = {
        "settings_hex": cell["settings_hex"],
        "readback_hex": cell["settings_hex"],
        "capabilities_hex": caps.to_payload().hex(),
        "run_id": run_id,
        "clocks_before": clocks,
        "clocks_after": clocks,
        "clock_measurements": [clock_fixture(), clock_fixture()],
        "duration_seconds": cell["seconds"],
        "stopped": True,
        "temperatures": [
            {"phase": phase, "status": "VALID", "celsius": 45}
            for phase in ("before", "running", "after")
        ],
        "parser_errors": 0,
        "host_queue_drops": 0,
        "stream_anomalies": 0,
        "oracle": {"errors": 0, "partial_bytes": 0},
        "status": status,
        "sdk_items": {},
        "reader_delta": {},
        "stall_seconds": cell.get("stall_seconds", 0),
    }
    for name, bit, width in (("adc", 1, 4), ("gpio", 2, settings.gpio_width_bits // 8)):
        active = bool(int(settings.stream_mask) & bit)
        frames = 60000 if active else 0
        layout = policy.GPIOLayout.from_mode(settings.aux_bank_mode)
        items = frames * (
            (layout.adc_items_per_frame if name == "adc" else layout.items_per_frame)
            if cell["kind"] == "legacy"
            else 1008
        )
        dropped = 1008 if active and cell["kind"] == "stall" else 0
        wire = worker.empty_stream()
        wire.update(
            frames=frames,
            items=items,
            end_item=items,
            versions=[2 if cell["kind"] == "legacy" else 3],
            run_ids=[run_id],
            sample_checks=1,
            synthetic_checks=2 if settings.source == 1 else 0,
            logical_bytes=items * width,
            encoded_bytes=items * width,
            wire_bytes=items * width + frames * 60,
            first_host_seconds=0,
            last_host_seconds=60,
            first_ticks=0,
            last_ticks=480000000,
            encodings={"0": 30000, "1": 30000},
        )
        row["oracle"][name] = wire
        row["sdk_items"][name] = items
        for metric, sdk_metric in (
            ("frames", "frames"),
            ("items", "items"),
            ("logical_bytes", "decoded_bytes"),
            ("wire_bytes", "wire_bytes"),
        ):
            row["reader_delta"][f"{name}_{sdk_metric}_received"] = wire[metric]
        for prefix in ("produced", "generated"):
            status[f"{name}_frames_{prefix}"] = frames + (1 if dropped else 0)
            status[f"{name}_items_{prefix}"] = items + dropped
        status[f"{name}_frames_dropped"] = 1 if dropped else 0
        status[f"{name}_frames_transmitted"] = frames
        status[f"{name}_items_dropped"] = dropped
        for metric in ("logical_bytes", "encoded_bytes", "wire_bytes"):
            status[f"{name}_{metric}_transmitted"] = wire[metric]
        status[f"{name}_codec_deadline_drops"] = 0
        status[f"{name}_codec_resource_drops"] = 0
        status[f"{name}_codec_raw"] = 30000 if active else 0
    status.update(
        adc_stop_pairs_discarded=0,
        adc_raw_pairs_lost=0,
        adc_incomplete_buffers=0,
        adc_incomplete_conversions=0,
        adc_completion_mismatches=0,
        adc_pairs_captured=status["adc_items_generated"],
        adc_pairs_delivered=status["adc_items_generated"],
        gpio_stop_samples_discarded=0,
        gpio_raw_samples_lost=0,
        gpio_samples_delivered=status["gpio_items_generated"],
    )
    return row


def test_capture_policy_accepts_complete_accounting_and_rejects_mutations():
    for cell in candidate()["matrix"]:
        if cell["kind"] == "negative":
            continue
        measurement = measured_fixture(cell)
        assert policy.validate_capture(cell, measurement) == [], cell["id"]
        broken = copy.deepcopy(measurement)
        broken["clocks_after"]["cpu_clock_hz"] = 450_000_000
        assert policy.validate_capture(cell, broken)
        broken = copy.deepcopy(measurement)
        name = "adc" if broken["oracle"]["adc"]["items"] else "gpio"
        broken["oracle"][name]["gap_items"] += 1
        assert policy.validate_capture(cell, broken)
        broken = copy.deepcopy(measurement)
        broken["temperatures"][1]["celsius"] = 80
        assert policy.validate_capture(cell, broken)


def test_prepare_retains_existing_freezer_identity_contract(tmp_path, cpp):  # noqa: F811
    if cpp[1] != 600:
        return  # Candidate preparation targets the standard fixed-600 build.
    frozen = candidate()
    # Compare the complete payload to the real portable firmware encoder,
    # including its smaller packet/control limits, not the generic SDK persona.
    caps = capabilities(cpp)
    manifest = {
        "source": {
            "git_commit": frozen["source_revision"],
            "source_id": "f" * 64,
            "build_id": "thingdaq-test",
            "firmware_inputs_clean": True,
            "firmware_input_changes": [],
        },
        "target": {"fqbn": "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std"},
        "public_protocol": {
            "enabled": True,
            "defaults": asdict(caps.defaults),
            "configurations": [asdict(s) for s in caps.configurations],
            "clocks": asdict(caps.cpu_profiles[0]),
            "firmware_version": [1, 2, 0],
        },
        "artifacts": [
            {"path": "firmware.ino.hex", "sha256": frozen["firmware_sha256"]}
        ],
    }
    path = tmp_path / "build-manifest.json"
    runner.save(path, manifest)
    prepared = runner.prepare_candidate(path, "12345")
    freezer = importlib.import_module("freeze_soak_candidate")
    freezer.validate_candidate_build(prepared, manifest, manifest["artifacts"])
    assert prepared["capabilities_hex"] == caps.to_payload().hex()
    assert prepared["physical_qualification"] == "NOT_RUN"
    assert runner.check_candidate(prepared) == frozen["matrix"]


def test_legacy_wire_accounting_uses_pipeline_generation_counters(cpp):  # noqa: F811
    for mode in (0, 1):
        settings = DAQConfiguration(3, 1, aux_bank_mode=mode, rate_profile=4)
        operations = [
            request(
                encode_v2_frame(
                    17, settings.to_payload(protocol_version=2), request_id=1
                )
            ),
            request(encode_v2_frame(18, request_id=2)),
            "T 64768",
            request(encode_v2_frame(20, request_id=3)),
            request(encode_v2_frame(19, request_id=4)),
        ]
        frames, _ = exchange(cpp, operations)
        responses = replies(frames)
        assert responses[1].value == settings
        tap = worker.WireTap(None)
        tap.reset(2 if mode else 1)
        for frame in frames:
            tap.accept(frame.to_bytes())
        status = responses[4].value
        for name in ("adc", "gpio"):
            wire = tap.snapshot()[name]
            assert wire["versions"] == [2]
            assert wire["frames"] == getattr(status, f"{name}_frames_generated")
            assert wire["items"] == getattr(status, f"{name}_items_generated")
            assert wire["gap_items"] == 0


def complete_records(frozen):
    """Synthetic complete matrix, used only for offline rejection tests."""
    records = []
    for index, cell in enumerate(frozen["matrix"]):
        row = {
            "cell_id": cell["id"],
            "cell": cell,
            "job_id": f"fake-job-{index}",
            "candidate_sha256": policy.json_hash(frozen),
            "outcome": "PASS",
            "physical": True,
            "host_setup": {"cpu.max": "200000 100000", "affinity": [0, 1]},
            "info": {**frozen["identity"], "protocol_version": 3, "simulated": False},
            "capabilities_hex": frozen["capabilities_hex"],
            "captures": [],
        }
        if cell["kind"] == "negative":
            row["temperatures"] = [
                {"phase": p, "status": "VALID", "celsius": 45}
                for p in ("before", "after")
            ]
            row["rejections"] = [
                {
                    "settings_hex": s,
                    "error_code": cell["expected_errors"][s],
                    "before": cell["settings_hex"],
                    "after": cell["settings_hex"],
                    "cpu_clock_hz": 600_000_000,
                    "state": 1,
                }
                for s in cell["rejected_hex"]
            ]
        else:
            for cycle in range(cell["cycles"]):
                selected = dict(cell)
                if cycle % 2 and "alternate_hex" in cell:
                    selected["settings_hex"] = cell["alternate_hex"]
                row["captures"].append(measured_fixture(selected, cycle + 1))
        records.append(row)
    return records


def test_complete_transcript_gate_and_failed_retry_lineage():
    frozen = candidate()
    records = complete_records(frozen)
    assert policy.validate_evidence(frozen, records)["outcome"] == "PASS"
    assert policy.validate_evidence(frozen, records[:-1])["outcome"] == "INCONCLUSIVE"
    failed = copy.deepcopy(records[0])
    failed.update(job_id="earlier-failed-job", outcome="FAIL")
    result = policy.validate_evidence(frozen, [failed, *records])
    assert result["outcome"] == "FAIL"
    assert len(result["attempts"]) == len(records) + 1


@pytest.mark.parametrize(
    "path,value,reason",
    [
        (("candidate_sha256",), "0" * 64, "candidate identity mismatch"),
        (("physical",), False, "physical evidence missing"),
        (("info", "hardware_serial"), "other-board", "observed hardware_serial"),
        (("info", "build_id"), "other-build", "observed build_id"),
        (("info", "firmware_version"), "1.1.0", "observed firmware_version"),
        (("info", "protocol_version"), 0x83, "nonphysical/nonpublic INFO"),
        (("cell", "seconds"), 1, "matrix cell changed"),
        (("captures", 0, "readback_hex"), "", "stale settings readback"),
        (
            ("captures", 0, "clocks_after", "cpu_clock_hz"),
            450_000_000,
            "stale final clocks",
        ),
        (
            ("captures", 0, "clock_measurements", 1, "dma_sample_count"),
            8000,
            "physical DWT/PIT/eDMA clock measurement failed",
        ),
        (
            ("captures", 0, "temperatures", 1, "celsius"),
            80,
            "thermal abort",
        ),
        (("captures", 0, "parser_errors"), 1, "SDK parser corruption"),
        (("captures", 0, "oracle", "adc", "versions"), [0x82], "private/wrong version"),
        (("captures", 0, "oracle", "adc", "versions"), [0x83], "private/wrong version"),
        (("captures", 0, "oracle", "adc", "gap_items"), 1, "unexplained sample gap"),
        (
            ("captures", 0, "status", "adc_items_produced"),
            60_480_001,
            "item conservation",
        ),
        (("captures", 0, "status", "transport_errors"), None, "unavailable/nonzero"),
        (("captures",), [], "missing captures/lifecycle cycles"),
    ],
)
def test_complete_evidence_rejects_single_fault_despite_pass_label(path, value, reason):
    frozen = candidate()
    records = complete_records(frozen)
    assert policy.validate_evidence(frozen, records)["outcome"] == "PASS"
    # Choose a combined cell so both streams must be checked.
    record = next(
        r
        for r in records
        if r["cell"]["kind"] == "smoke"
        and V3Settings.from_bytes(bytes.fromhex(r["cell"]["settings_hex"])).stream_mask
        == 3
    )
    # Do not mutate the candidate through a shared cell reference.
    index = records.index(record)
    records[index] = copy.deepcopy(record)
    target = records[index]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    result = policy.validate_evidence(frozen, records)
    assert result["outcome"] == "FAIL"
    assert any(reason in problem for problem in result["problems"])
    assert not result["checks"]["all_attempts_valid"]


def test_complete_matrix_cannot_hide_an_unresolved_earlier_attempt():
    frozen = candidate()
    records = complete_records(frozen)
    pending = {
        "cell_id": records[0]["cell_id"],
        "outcome": "INCONCLUSIVE",
        "retention_error": "results.json unavailable after interrupted retrieval",
    }
    result = policy.validate_evidence(frozen, [pending, *records])
    assert result["missing_cells"] == []
    assert not result["checks"]["all_attempts_valid"]
    assert result["outcome"] == result["physical_qualification"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "kind", ["smoke", "lifecycle", "soak", "stall", "fallback", "legacy", "negative"]
)
def test_missing_required_matrix_cell_is_never_pass(kind):
    frozen = candidate()
    records = complete_records(frozen)
    missing = next(r for r in records if r["cell"]["kind"] == kind)
    records.remove(missing)
    result = policy.validate_evidence(frozen, records)
    assert result["outcome"] == "INCONCLUSIVE"
    assert result["missing_cells"] == [missing["cell_id"]]
    assert not result["checks"]["matrix_complete"]


@pytest.mark.parametrize(
    "fault",
    [
        "firmware",
        "manifest",
        "source_revision",
        "dirty_build",
        "build_id",
        "cpu",
        "protocol",
        "experiment",
        "dirty_worktree",
        "changed_inputs",
    ],
)
def test_artifact_verification_rejects_stale_or_nonstandard_builds(
    monkeypatch, tmp_path, fault
):
    frozen = candidate()
    firmware_path = tmp_path / "firmware.ino.hex"
    manifest_path = tmp_path / "build-manifest.json"
    firmware_path.write_bytes(b"firmware")
    manifest = {
        "source": {
            "git_commit": frozen["source_revision"],
            "firmware_inputs_clean": True,
            "build_id": frozen["identity"]["build_id"],
        },
        "release_policy": {"core_hz": 600_000_000, "protocol_version": 3},
        "artifacts": [
            {
                "path": "firmware.ino.hex",
                "sha256": frozen["firmware_sha256"],
                "size_bytes": 8,
            }
        ],
    }
    # Isolate the git boundary; hashes and build-policy verification remain real.
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: None)
    runner.save(manifest_path, manifest)
    frozen["build_manifest_sha256"] = runner.rig.digest(manifest_path.read_bytes())
    assert runner.verify_artifacts(frozen, firmware_path, manifest_path) == b"firmware"
    if fault == "firmware":
        firmware_path.write_bytes(b"another-image")
    elif fault == "manifest":
        manifest_path.write_text(manifest_path.read_text() + "\n")
    elif fault == "dirty_worktree":
        monkeypatch.setattr(
            runner.subprocess, "check_output", lambda *a, **k: "?? protocol/new.json\n"
        )
    elif fault == "changed_inputs":

        def changed(*args, **kwargs):
            raise runner.subprocess.CalledProcessError(1, args[0])

        monkeypatch.setattr(runner.subprocess, "run", changed)
    else:
        if fault == "source_revision":
            manifest["source"]["git_commit"] = "c" * 40
        elif fault == "dirty_build":
            manifest["source"]["firmware_inputs_clean"] = False
        elif fault == "build_id":
            manifest["source"]["build_id"] = "other-build"
        elif fault == "cpu":
            manifest["release_policy"]["core_hz"] = 450_000_000
        elif fault == "protocol":
            manifest["release_policy"]["protocol_version"] = 2
        else:
            manifest["input_experiment"] = {"enabled": True}
        runner.save(manifest_path, manifest)
        frozen["build_manifest_sha256"] = runner.rig.digest(manifest_path.read_bytes())
    expected = {
        "firmware": "firmware differs",
        "manifest": "build manifest differs",
        "dirty_worktree": "inputs are dirty",
    }.get(fault, "provenance/defaults mismatch")
    if fault == "changed_inputs":
        with pytest.raises(runner.subprocess.CalledProcessError):
            runner.verify_artifacts(frozen, firmware_path, manifest_path)
    else:
        with pytest.raises(ValueError, match=expected):
            runner.verify_artifacts(frozen, firmware_path, manifest_path)


@pytest.mark.parametrize(
    "path",
    [
        ("sdk_version",),
        ("sdk_archive_sha256",),
        *(("runner_sha256", name) for name in runner.RUNNER_INPUTS),
        *(("schema_sha256", f"protocol-v{version}.json") for version in (1, 2, 3)),
    ],
)
def test_candidate_binds_every_sdk_schema_and_runner_input(path):
    frozen = candidate()
    target = frozen["inputs"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "stale"
    with pytest.raises(ValueError, match="inputs differ"):
        runner.check_candidate(frozen)


@pytest.fixture
def retained_attempt(tmp_path):
    frozen = candidate()
    record = complete_records(frozen)[0]
    directory = tmp_path / record["cell_id"] / "attempt-001"
    directory.mkdir(parents=True)
    program = runner.make_program(frozen, record["cell"])
    (directory / "rig-program.py").write_text(program)
    (directory / "firmware.ino.hex").write_bytes(b"firmware")
    runner.save(
        directory / "provenance.json",
        {
            "candidate_sha256": policy.json_hash(frozen),
            "service": "http://fake.invalid",
        },
    )
    runner.save(
        directory / "submission.json",
        {
            "program_sha256": runner.rig.digest(program.encode()),
            "firmware_sha256": frozen["firmware_sha256"],
            "service": "http://fake.invalid",
        },
    )
    runner.save(directory / "start.json", {"test_id": record["job_id"]})
    runner.save(
        directory / "results.json",
        {
            "results": {
                "test_id": record["job_id"],
                "completed": True,
                "program_success": True,
                "exit_code": 0,
                "stdout": "QUALIFICATION " + json.dumps(record),
            }
        },
    )
    return frozen, tmp_path, directory


@pytest.mark.parametrize(
    "setup",
    [
        None,
        {"cpu.max": "50000 100000", "affinity": [0, 1]},
        {"cpu.max": "200000 100000", "affinity": [0]},
    ],
    ids=["missing", "half-core", "one-cpu-affinity"],
)
def test_retained_pass_requires_worker_cpu_readback(retained_attempt, setup):
    frozen, output, directory = retained_attempt
    assert runner.retained_records(frozen, output)[0]["outcome"] == "PASS"
    path = directory / "results.json"
    saved = json.loads(path.read_text())
    record = json.loads(saved["results"]["stdout"].removeprefix("QUALIFICATION "))
    if setup is None:
        record.pop("host_setup")
    else:
        record["host_setup"] = setup
    saved["results"]["stdout"] = "QUALIFICATION " + json.dumps(record)
    runner.save(path, saved)
    result = runner.retained_records(frozen, output)[0]
    assert result["outcome"] != "PASS"
    assert "worker CPU allocation" in result["retention_error"]


@pytest.mark.parametrize(
    "filename,key,value,reason",
    [
        ("provenance.json", "candidate_sha256", "stale", "saved candidate mismatch"),
        ("submission.json", "program_sha256", "stale", "submission input identity"),
        ("submission.json", "firmware_sha256", "stale", "submission input identity"),
        (
            "submission.json",
            "service",
            "http://other.invalid",
            "submission input identity",
        ),
        ("start.json", "test_id", "other-job", "service result job ID mismatch"),
        (
            "rig-program.py",
            None,
            "# changed program",
            "saved program/firmware identity",
        ),
        (
            "firmware.ino.hex",
            None,
            "changed firmware",
            "saved program/firmware identity",
        ),
    ],
)
def test_retained_evidence_rejects_artifact_identity_tampering(
    retained_attempt, filename, key, value, reason
):
    frozen, output, directory = retained_attempt
    assert runner.retained_records(frozen, output)[0]["outcome"] == "PASS"
    path = directory / filename
    if key is None:
        path.write_text(value)
    else:
        data = json.loads(path.read_text())
        data[key] = value
        runner.save(path, data)
    # A cached PASS summary is never authoritative.
    runner.save(directory / "summary.json", {"outcome": "PASS"})
    result = runner.evaluate(frozen, output)
    assert result["outcome"] == "FAIL"
    assert reason in result["retention_errors"][0]["retention_error"]


@pytest.mark.parametrize(
    "key,value", [("completed", False), ("program_success", False), ("exit_code", 1)]
)
def test_service_failure_overrides_worker_pass(retained_attempt, key, value):
    frozen, output, directory = retained_attempt
    path = directory / "results.json"
    data = json.loads(path.read_text())
    data["results"][key] = value
    runner.save(path, data)
    assert runner.evaluate(frozen, output)["outcome"] == "FAIL"


def test_campaign_recovers_accepted_5xx_and_interrupted_results_without_resubmission(
    monkeypatch, tmp_path
):
    frozen = candidate()
    record = complete_records(frozen)[0]
    cell = record["cell"]
    output = tmp_path / "campaign"
    directory = output / cell["id"] / "attempt-001"
    clock = Clock()
    monkeypatch.setattr(runner.rig.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(runner.rig.time, "sleep", clock.sleep)
    monkeypatch.setenv("FW_RIG_AUTH", "offline-secret")
    monkeypatch.setattr(runner, "verify_artifacts", lambda *_: b"firmware")
    monkeypatch.setattr(runner.rig, "service_preflight", lambda _: {})
    events = []
    statuses = iter([{"status": "queued"}] * 1000 + [{"status": "success"}] * 2)
    results_requested = 0

    def post(url, **kwargs):
        nonlocal results_requested
        endpoint = url.rsplit("/", 1)[1]
        events.append(endpoint)
        if endpoint == "start":
            saved = json.loads((directory / "submission.json").read_text())
            assert kwargs["json"]["agent_name"] == saved["agent_name"]
            return reply(503)
        assert kwargs["json"]["test_id"] == record["job_id"]
        if endpoint == "status":
            return reply(body=next(statuses))
        assert endpoint == "results"
        results_requested += 1
        if results_requested == 1:
            raise OSError("interrupted result retrieval")
        return reply(
            body={
                "results": {
                    "test_id": record["job_id"],
                    "completed": True,
                    "program_success": True,
                    "exit_code": 0,
                    "stdout": "QUALIFICATION " + json.dumps(record),
                }
            }
        )

    def recover(service, submission, evidence_dir):
        events.append("journal")
        assert evidence_dir == directory
        assert submission == json.loads((directory / "submission.json").read_text())
        started = {"test_id": record["job_id"]}
        runner.save(directory / "start.json", started)
        return started

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(runner.rig, "recover_submission", recover)
    args = SimpleNamespace(
        output=output,
        resume=False,
        firmware=None,
        build_manifest=None,
        cell=cell["id"],
        service="http://fake.invalid",
    )
    with pytest.raises(OSError, match="interrupted"):
        runner.run_campaign(args, frozen, [cell])
    assert events[:2] == ["start", "journal"]
    assert clock.now >= 1000  # Queue time exceeds this cell's execution budget.
    assert (
        json.loads((output / "qualification.json").read_text())["outcome"]
        == "INCONCLUSIVE"
    )
    args.resume = True
    result = runner.run_campaign(args, frozen, [cell])
    assert result["outcome"] == "INCONCLUSIVE"  # Other matrix cells remain unrun.
    assert result["attempts"][0]["outcome"] == "PASS"
    assert result["retention_errors"] == []
    assert (directory / "client-error.json").exists()
    assert events.count("start") == events.count("journal") == 1
    previous_events = events[:]
    assert runner.run_campaign(args, frozen, [cell]) == result
    assert events == previous_events  # Completed jobs are never submitted again.


@pytest.mark.parametrize("width", [8, 16])
@pytest.mark.parametrize("policies", [0, 1, 2, 3])
def test_real_synthetic_generator_reaches_fallback_gate(cpp, width, policies):  # noqa: F811
    # Drive the actual SyntheticSource through runtime/control/packet/USB, not
    # the codec fixture's hand-filled pages or measured_fixture's counters.
    from thingdone_daq.protocol_v3 import decode_v3_block
    from thingdone_daq.synthetic import validate_synthetic_block

    if cpp[1] != 600 and policies:
        pytest.skip("historical 450 MHz advertises RAW only")
    caps = capabilities(cpp)
    settings = next(
        s
        for s in caps.configurations
        if s.source == 1
        and s.stream_mask == 3
        and s.gpio_width_bits == width
        and int(s.gpio_policy) == policies & 1
        and int(s.adc_policy) == (policies >> 1) & 1
    )
    frames, _ = exchange(
        cpp,
        [
            request(command(17, settings.to_bytes(), 1)),
            request(command(18, request_id=2)),
            *["T 32256"] * 6,
            request(command(20, request_id=3)),
            request(command(19, request_id=4)),
        ],
    )
    data = [f for f in frames if f.header.kind in (1, 2)]
    tap = worker.WireTap(None)
    tap.reset(width // 8, synthetic=True)
    for frame in data:
        block = decode_v3_block(frame, settings=settings)
        validate_synthetic_block(block)
        tap.accept(frame.to_bytes())
    oracle = tap.snapshot()
    assert oracle["errors"] == oracle["partial_bytes"] == 0
    for name in ("adc", "gpio"):
        assert oracle[name]["gap_items"] == 0
        assert oracle[name]["synthetic_checks"] == len(oracle[name]["encodings"])
    assert set(oracle["gpio"]["encodings"]) == ({"0", "1"} if policies & 1 else {"0"})
    if policies == 3:
        cell = next(
            r
            for r in policy.matrix(caps.to_payload().hex())
            if r["id"] == f"fallback-{int(width == 16)}"
        )
        measured = measured_fixture(cell)
        # Only the encoding/source coverage comes from the portable generator;
        # duration/health remain explicit unit fixtures, never hardware credit.
        for name in ("adc", "gpio"):
            for key in ("encodings", "synthetic_checks"):
                measured["oracle"][name][key] = oracle[name][key]
        assert policy.validate_capture(cell, measured) == []
        measured["oracle"]["gpio"]["encodings"] = {"0": 1}
        assert "RLE/RAW fallback unobserved" in policy.validate_capture(cell, measured)
        measured["oracle"]["gpio"]["synthetic_checks"] = 0
        assert (
            "gpio missing independent synthetic source check"
            in policy.validate_capture(cell, measured)
        )


@pytest.mark.parametrize(
    "kind,fault",
    [("legacy", None), ("smoke", None), ("legacy", "drain"), ("legacy", "close")],
)
def test_worker_closes_validated_legacy_capture_without_cross_version_stop(
    monkeypatch, kind, fault
):
    frozen = candidate()
    device = SimulatedV3Device(build_id="thingdaq-test")
    legacy_device = SimulatedDevice(protocol_version=2)
    original_info, receive = device.info, device.receive
    monkeypatch.setattr(
        device,
        "info",
        lambda: replace(
            original_info(),
            simulated=False,
            hardware_serial="12345",
            firmware_version="1.2.0",
        ),
    )
    sent, mode = [], {"legacy": False}

    def peer(data):
        version, command_kind = data[4:6]
        request_id = struct.unpack_from("<I", data, 28)[0]
        sent.append((version, command_kind))
        if version == 2 and command_kind == 20:
            mode["legacy"] = True
            return legacy_device.receive(data)
        if version == 3 and command_kind == 20 and mode["legacy"]:
            # Exact rejection retained in hardware job e942cc96 and reproduced
            # with production control/runtime in the separate test below.
            return (
                encode_v3_frame(
                    0x94, struct.pack("<HH", 1, 7), flags=0x8000, request_id=request_id
                ),
            )
        return receive(data)

    monkeypatch.setattr(device, "receive", peer)

    def capture(daq, tap, cell, settings, record):
        measured = measured_fixture(cell)
        record["captures"].append(measured)
        assert policy.validate_capture(cell, measured) == []
        if kind == "legacy":
            worker.legacy_command(daq, 20)
        if fault == "drain":
            raise ValueError("incomplete STOP drain")
        if fault == "close":
            close = daq.close

            def failed_close(*, stop=True):
                close(stop=stop)
                raise OSError("reader close failure")

            monkeypatch.setattr(daq, "close", failed_close)

    # Measurement values are explicit fixtures; SDK context exit, reader,
    # commands, error decoding and transport closure remain production code.
    monkeypatch.setattr(worker, "capture", capture)
    cell = next(row for row in frozen["matrix"] if row["kind"] == kind)
    transport = InMemoryTransport(device=device)
    record = worker.run(frozen, cell, transport)
    assert record["outcome"] == ("FAIL" if fault else "PASS"), record.get("error")
    assert not transport.is_open
    if kind == "legacy" and fault is None:
        assert [pair for pair in sent if pair[1] == 20] == [(2, 20)]
    if fault == "drain":
        assert record["error"] == "ValueError: incomplete STOP drain"
    if fault == "close":
        assert record["error"] == "OSError: reader close failure"


def test_production_legacy_stop_readbacks_do_not_allow_v3_cleanup_stop(cpp):  # noqa: F811
    configuration = DAQConfiguration(1, 1, aux_bank_mode=0, rate_profile=4)
    frames, _ = exchange(
        cpp,
        [
            request(
                encode_v2_frame(
                    17, configuration.to_payload(protocol_version=2), request_id=1
                )
            ),
            request(encode_v2_frame(18, request_id=2)),
            "T 32384",
            request(encode_v2_frame(20, request_id=3)),
            request(encode_v2_frame(19, request_id=4)),
            request(command(29, request_id=5)),
            request(command(16, request_id=6)),
            request(command(20, request_id=7)),
        ],
    )
    responses = replies(frames)
    assert all(responses[i].error_code == 0 for i in range(1, 7))
    assert int(responses[4].value.device_state) == 1
    assert responses[4].value.packet_owned_depth == 0
    assert int(responses[7].error_code) == 7


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "adc_items_dropped",
        "gpio_items_dropped",
        "adc_raw_pairs_lost",
        "gpio_raw_samples_lost",
        "adc_stop_pairs_discarded",
        "gpio_stop_samples_discarded",
        "adc_pairs_captured",
        "adc_pairs_delivered",
        "gpio_samples_delivered",
        "adc_incomplete_buffers",
        "adc_completion_mismatches",
        "adc_incomplete_conversions",
        "adc_bound",
        "gpio_bound",
        "missing_tail",
        "frame_drop",
        "gap",
    ],
)
def test_retained_legacy_physical_stop_tail_conservation(fault):
    fixture = json.loads(
        (TOOLS.parent / "tests/fixtures/legacy_stop_tail_capture.json").read_text()
    )
    cell, capture = fixture["cell"], fixture["capture"]
    status = capture["status"]
    if fault in status:
        status[fault] += (
            10000
            if fault
            in (
                "adc_incomplete_buffers",
                "adc_completion_mismatches",
                "adc_incomplete_conversions",
            )
            else 1
        )
    elif fault == "adc_bound":
        status["adc_stop_pairs_discarded"] = status["adc_raw_pairs_lost"] = status[
            "adc_items_dropped"
        ] = 2024
        status["adc_pairs_captured"] = status["adc_items_generated"] + 2024
    elif fault == "gpio_bound":
        status["gpio_stop_samples_discarded"] = status[
            "gpio_raw_samples_lost"
        ] = status["gpio_items_dropped"] = 4048
    elif fault == "missing_tail":
        del status["adc_stop_pairs_discarded"]
    elif fault == "frame_drop":
        status["adc_frames_dropped"] += 1
    elif fault == "gap":
        capture["oracle"]["adc"]["gap_items"] += 1
        capture["oracle"]["adc"]["end_item"] += 1
    problems = policy.validate_capture(cell, capture)
    assert bool(problems) == (fault is not None), (fault, problems)
