"""Metadata-driven CLI selection, lifecycle output and simulator compatibility."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from thingdone_daq import (
    ADCBlock,
    CalibrationRecord,
    ConverterCalibration,
    InMemoryTransport,
    ThingDAQ,
    V3Settings,
    save_calibration,
)
from thingdone_daq._generated import protocol_constants as legacy
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.cli import CaptureInterruptedError, CliExitCode, main
from thingdone_daq.simulator_v3 import SimulatedV3Device


@pytest.fixture
def sessions(monkeypatch):
    opened = []
    original = ThingDAQ.simulated

    def simulated(**options):
        daq = original(**options)
        opened.append(daq)
        return daq

    monkeypatch.setattr(ThingDAQ, "simulated", simulated)
    yield opened
    for daq in opened:
        assert not daq.transport.is_open
        assert not daq.reader.is_running


def run_cli(capsys, command, *options, version=3, json_output=True):
    args = [command, "--simulate", "--simulator-version", str(version), *options]
    if json_output:
        args.append("--json")
    result = main(args)
    captured = capsys.readouterr()
    assert result == CliExitCode.OK, captured.err
    assert captured.err == ""
    return json.loads(captured.out) if json_output else captured.out


@pytest.mark.parametrize(
    "version,gpio_rate", [(1, 4_000_000), (2, 1_000_000), (3, 1_000_000)]
)
def test_cli_personas_negotiate_and_preserve_omitted_defaults(
    capsys, sessions, version, gpio_rate
):
    report = run_cli(capsys, "configure", version=version)
    daq = sessions[-1]
    assert daq.device_info.protocol_version == version
    applied = report["applied_configuration"]
    settings = applied["settings"] if version == 3 else applied
    assert settings["adc_pair_rate_hz"] == 1_000_000
    assert settings["gpio_sample_rate_hz"] == gpio_rate
    assert settings["aux_bank_mode"] == "DISABLED"
    if version == 3:
        assert settings["cpu_profile"] == "CPU_600MHZ"
        assert settings["gpio_policy"] == "RLE_AUTO"
        assert settings["adc_policy"] == "PACK12"
        assert settings["source"] == "HARDWARE"
        assert report["state"] == "STOPPED"
    else:
        assert settings["data_checksum_algorithm"] == "ADLER32"
        assert settings["source"] == "SYNTHETIC"
        assert report["state"] == "CONFIGURED"


def test_probe_json_has_exact_defaults_tables_and_readback(capsys, sessions):
    report = run_cli(capsys, "info")
    capabilities = report["capabilities"]
    assert report["info"]["protocol_version"] == 3
    assert len(capabilities["configurations"]) == 48
    assert len(capabilities["cpu_profiles"]) == 1
    assert len(capabilities["rate_profiles"]) == 1
    assert report["defaults"] == capabilities["defaults"]
    assert report["active_settings"]["settings"] == report["defaults"]
    assert report["active_settings"]["clocks"] == report["info"]["clocks"]
    assert report["state"] == "STOPPED"


def test_probe_human_has_same_metadata_and_does_not_mutate_settings(
    capsys, monkeypatch
):
    device = SimulatedV3Device()
    with ThingDAQ.open(InMemoryTransport(device)) as setup:
        setup.configure(
            cpu_profile=c.CpuProfile.CPU_600MHZ,
            gpio_policy=c.GpioPolicy.RAW,
            adc_policy=c.AdcPolicy.RAW,
        )
    daq = ThingDAQ.open(InMemoryTransport(device))
    before = daq.get_settings()
    monkeypatch.setattr("thingdone_daq.cli._open_device", lambda _: daq)
    with patch.object(
        daq, "configure", side_effect=AssertionError("probe mutated device")
    ):
        output = run_cli(capsys, "probe", json_output=False)
    assert "defaults.cpu_profile=CPU_600MHZ" in output
    assert "active_settings.settings.cpu_profile=CPU_600MHZ" in output
    assert "active_settings.clocks.cpu_clock_hz=600000000" in output
    assert "capabilities.configurations[47]." in output
    assert "capabilities.cpu_profiles[0].cpu_clock_hz=600000000" in output
    assert "capabilities.cpu_profiles[1]." not in output
    assert "defaults.gpio_policy=RLE_AUTO" in output
    assert "active_settings.settings.gpio_policy=RAW" in output
    with ThingDAQ.open(InMemoryTransport(device)) as check:
        assert check.get_settings() == before
    assert not daq.is_open


@pytest.mark.parametrize(
    "record",
    [
        r
        for r in c.SELECTABLE_CONFIGURATIONS
        if V3Settings.from_bytes(r).cpu_profile == c.CpuProfile.CPU_600MHZ
    ],
)
def test_cli_can_select_every_advertised_tuple(capsys, sessions, record):
    settings = V3Settings.from_bytes(record)
    stream = {1: "adc", 2: "gpio", 3: "both"}[int(settings.stream_mask)]
    report = run_cli(
        capsys,
        "configure",
        "--streams",
        stream,
        "--source",
        settings.source.name.lower(),
        "--cpu-profile",
        settings.cpu_profile.name.lower(),
        "--rate-profile",
        settings.rate_profile.name.lower(),
        "--gpio-policy",
        settings.gpio_policy.name.lower(),
        "--adc-policy",
        settings.adc_policy.name.lower(),
        "--aux-bank-mode",
        settings.aux_bank_mode.name.lower(),
        "--adc-pair-rate-hz",
        str(settings.adc_pair_rate_hz),
        "--gpio-sample-rate-hz",
        str(settings.gpio_sample_rate_hz),
        "--adc-resolution-bits",
        str(settings.adc_resolution_bits),
    )
    assert sessions[-1].configuration == settings
    assert (
        report["applied_configuration"]["settings"]["cpu_profile"]
        == settings.cpu_profile.name
    )
    clocks = report["applied_configuration"]["clocks"]
    assert clocks["cpu_clock_hz"] == 600_000_000
    assert clocks["cpu_profile"] == settings.cpu_profile.name


@pytest.mark.parametrize(
    "options",
    [
        ["--cpu-profile", "cpu_450mhz"],
        ["--cpu-profile", "cpu_450mhz", "--gpio-policy", "raw", "--adc-policy", "raw"],
        ["--gpio-sample-rate-hz", "4000000"],
        ["--adc-pair-rate-hz", "500000"],
        ["--adc-resolution-bits", "10"],
        ["--rate-profile", "adc_1mhz_gpio_4mhz"],
        ["--checksum", "crc32c"],
        ["--checksum", "crc32-iso-hdlc"],
        ["--streams", "none"],
    ],
)
def test_unsupported_v3_selection_is_actionable_and_does_not_configure(
    capsys, sessions, options
):
    with patch(
        "thingdone_daq.session_v3.V3Session.configure",
        side_effect=AssertionError("invalid tuple reached CONFIGURE"),
    ):
        result = main(
            ["configure", "--simulate", "--simulator-version", "3", "--json", *options]
        )
    captured = capsys.readouterr()
    assert result == CliExitCode.UNSUPPORTED_CAPABILITY
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["category"] == "unsupported-capability"
    assert "advertised" in error["message"]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "flag,value",
    [
        ("--cpu-profile", "cpu_600mhz"),
        ("--gpio-policy", "raw"),
        ("--adc-policy", "pack12"),
    ],
)
def test_v3_selectors_on_legacy_fail_without_mutation(
    capsys, sessions, version, flag, value
):
    result = main(
        [
            "configure",
            "--simulate",
            "--simulator-version",
            str(version),
            flag,
            value,
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)["error"]
    assert result == CliExitCode.UNSUPPORTED_CAPABILITY
    assert "requires protocol v3" in error["message"]
    assert sessions[-1].configuration is None


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize(
    "command", ["status", "stop", "start", "configure", "reconcile"]
)
def test_v3_lifecycle_output(capsys, sessions, command, json_output):
    output = run_cli(capsys, command, json_output=json_output)
    if command == "reconcile":
        # V3 conservation coverage is deliberately limited to advertised counters.
        assert output["exact"] if json_output else "conservation=PASS" in output
    elif command in {"start", "configure"}:
        if json_output:
            assert output["applied_configuration"]["settings"]["adc_policy"] == "PACK12"
        else:
            assert "settings.adc_policy=PACK12" in output
            assert "clocks.cpu_clock_hz=600000000" in output
    else:
        assert "STOPPED" in (json.dumps(output) if json_output else output)


@pytest.mark.parametrize("json_output", [False, True])
def test_compressed_capture_reports_readback_wire_bytes_and_missing_telemetry(
    capsys, sessions, json_output
):
    output = run_cli(
        capsys,
        "capture",
        "--duration",
        "0.04",
        "--aux-bank-mode",
        "input",
        "--gpio-channel",
        "D16",
        "--strict-loss",
        json_output=json_output,
    )
    assert sessions[-1].state == c.DeviceState.STOPPED
    if json_output:
        assert output["final_state"] == "STOPPED"
        assert output["configuration"]["settings"]["gpio_width_bits"] == 16
        summary = output["summary"]
        assert summary["adc_blocks"] > 0 and summary["gpio_blocks"] > 0
        assert 0 < summary["adc_wire_bytes"] < summary["adc_payload_bytes"]
        assert summary["packet_ready_high_water"] is None
        assert summary["packet_transmit_high_water"] is None
        assert output["sample_preview"][0]["encoding"] == "ADC_PACK12"
        assert any(
            row.get("packed_width_bits") == 16 for row in output["sample_preview"]
        )
    else:
        assert "settings.gpio_width_bits=16" in output
        assert "final_state=STOPPED" in output
        assert "adc_wire_Bps=" in output
        assert "packet_ready_hwm=None" in output


def test_v3_capture_interruption_stops_and_closes(capsys, sessions):
    with patch.object(
        ThingDAQ, "read_block", side_effect=CaptureInterruptedError("SIGINT")
    ):
        result = main(
            [
                "capture",
                "--simulate",
                "--simulator-version",
                "3",
                "--duration",
                "0.04",
                "--json",
            ]
        )
    assert result == CliExitCode.INTERRUPTED
    assert json.loads(capsys.readouterr().err)["error"]["category"] == "interrupted"
    assert sessions[-1].state == c.DeviceState.STOPPED


def test_v3_calibrated_capture_uses_explicit_simulator_identity(
    capsys, sessions, tmp_path
):
    from datetime import datetime, timezone

    calibration = CalibrationRecord(
        hardware_serial=12345,
        analog_front_end_profile="fixture",
        adc_resolution_bits=12,
        adc_code_range=(0, 4095),
        adc_input_range_volts=(0.0, 3.3),
        adc0=ConverterCalibration(offset=0, gain=0.001),
        adc1=ConverterCalibration(offset=0, gain=0.002),
        provenance="v3 CLI regression",
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    path = tmp_path / "calibration.json"
    save_calibration(path, calibration)
    output = run_cli(
        capsys,
        "capture",
        "--duration",
        "0.02",
        "--streams",
        "adc",
        "--adc-output",
        "calibrated",
        "--calibration",
        str(path),
        "--calibration-hardware-serial",
        "12345",
        "--analog-front-end-profile",
        "fixture",
    )
    for row in output["sample_preview"]:
        assert row["calibrated"]
        assert row["adc0"]["voltage"] == row["adc0"]["raw_code"] * 0.001
        assert row["adc1"]["voltage"] == row["adc1"]["raw_code"] * 0.002


def test_v2_persona_retains_release_rates_after_stop_and_reopen():
    with ThingDAQ.simulated(protocol_version=2, strict=True) as daq:
        device = daq.transport.device
        daq.configure()
        daq.start()
        assert isinstance(daq.read_block(), ADCBlock)
        assert daq.stop() == legacy.DeviceState.IDLE
        info = daq.info()
        assert info.protocol_version == 2
        assert info.gpio_sample_rate_hz == 1_000_000
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        assert daq.device_info.protocol_version == 2
        assert daq.configure().gpio_sample_rate_hz == 1_000_000


def test_simulator_persona_flag_requires_simulation(capsys):
    with patch.object(ThingDAQ, "open", side_effect=AssertionError("opened hardware")):
        result = main(["probe", "--simulator-version", "3", "--json"])
    assert result == CliExitCode.DEVICE_ERROR
    assert (
        "requires --simulate" in json.loads(capsys.readouterr().err)["error"]["message"]
    )


def test_cli_does_not_report_success_when_readback_disagrees(capsys, monkeypatch):
    device = SimulatedV3Device()
    daq = ThingDAQ.open(InMemoryTransport(device))
    monkeypatch.setattr("thingdone_daq.cli._open_device", lambda _: daq)
    original = device._reply

    def mismatched(kind, request_id, value=None, error=c.ErrorCode.OK):
        if kind == c.CommandKind.GET_SETTINGS:
            value = replace(
                value, settings=replace(value.settings, gpio_policy=c.GpioPolicy.RAW)
            )
        return original(kind, request_id, value, error)

    monkeypatch.setattr(device, "_reply", mismatched)
    result = main(["configure", "--simulate", "--json"])
    output = capsys.readouterr()
    assert result != CliExitCode.OK
    assert output.out == ""
    assert (
        "GET_SETTINGS differs from CONFIGURE echo"
        in json.loads(output.err)["error"]["message"]
    )
    assert not daq.transport.is_open
    assert not daq.reader.is_running


@pytest.mark.parametrize("json_output", [True, False])
def test_status_diagnostics_preserve_unavailable_measurements(
    capsys, sessions, json_output
):
    output = run_cli(capsys, "status", json_output=json_output)
    if json_output:
        status = output["status"]
        assert status["adc_codec_completed"] is None
        assert status["adc_encoded_bytes_transmitted"] is None
        assert status["transport_errors"] is None
        assert status["adc_frames_produced"] == 0
    else:
        assert "adc_codec_completed=None" in output
        assert "adc_encoded_bytes_transmitted=None" in output
        assert "transport_errors=None" in output
