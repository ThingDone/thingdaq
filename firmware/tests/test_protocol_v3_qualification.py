"""Offline implementation checks; none of these fixtures is physical evidence."""

from __future__ import annotations

import copy
import importlib
import json
import struct
import sys
import zlib
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
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
from thingdone_daq.simulator_v3 import SimulatedV3Device
from thingdone_daq.transport import InMemoryTransport

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
policy = importlib.import_module("protocol_v3_qualification")
runner = importlib.import_module("qualify_protocol_v3")
worker = importlib.import_module("rig_protocol_v3_qualification")


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

    def with_temperature(data):
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

    def submit(service, auth, firmware, program, directory, timeout):
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
        items = frames * 1008
        dropped = 1008 if active and cell["kind"] == "stall" else 0
        wire = worker.empty_stream()
        wire.update(
            frames=frames,
            items=items,
            end_item=items,
            versions=[2 if cell["kind"] == "legacy" else 3],
            run_ids=[run_id],
            sample_checks=1,
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


def test_prepare_retains_existing_freezer_identity_contract(tmp_path):
    frozen = candidate()
    caps = normal_capabilities()
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
    assert prepared["capabilities_hex"] == frozen["capabilities_hex"]
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


def test_complete_transcript_gate_and_failed_retry_lineage():
    frozen = candidate()
    records = []
    for index, cell in enumerate(frozen["matrix"]):
        row = {
            "cell_id": cell["id"],
            "cell": cell,
            "job_id": f"fake-job-{index}",
            "candidate_sha256": policy.json_hash(frozen),
            "outcome": "PASS",
            "physical": True,
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
    assert policy.validate_evidence(frozen, records)["outcome"] == "PASS"
    assert policy.validate_evidence(frozen, records[:-1])["outcome"] == "INCONCLUSIVE"
    failed = copy.deepcopy(records[0])
    failed.update(job_id="earlier-failed-job", outcome="FAIL")
    result = policy.validate_evidence(frozen, [failed, *records])
    assert result["outcome"] == "FAIL"
    assert len(result["attempts"]) == len(records) + 1
