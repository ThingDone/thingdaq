"""Offline coverage for the cold-boot experiment submission wrapper."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "input_isolation", Path(__file__).parents[1] / "tools/run_input_isolation.py"
)
isolation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(isolation)


def test_program_preserves_future_imports_and_registers_dataclasses(monkeypatch):
    source = """from __future__ import annotations
from dataclasses import dataclass
import os
@dataclass
class Case:
    width: int = 8
def main():
    assert Case().width == 8
    assert os.environ["AUX_INPUT_RUN_DIAGNOSTIC"] == "0"
    assert os.environ["AUX_INPUT_TEMPERATURE"] == "1"
    return 7
if __name__ == "__main__":
    raise AssertionError("must call main only once")
"""
    monkeypatch.setenv("AUX_INPUT_RUN_DIAGNOSTIC", "1")
    monkeypatch.setenv("AUX_INPUT_TEMPERATURE", "0")
    try:
        with pytest.raises(SystemExit) as stopped:
            exec(  # noqa: S102 - locally authored runner regression
                isolation.make_program(
                    source,
                    {"AUX_INPUT_RUN_DIAGNOSTIC": "0", "AUX_INPUT_TEMPERATURE": "1"},
                ),
                {},
            )
        assert stopped.value.code == 7
    finally:
        sys.modules.pop("input_isolation_rig", None)


def test_digest_is_sha256():
    assert (
        isolation.digest(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_explicit_cases_alternate_width_without_reloading(monkeypatch):
    monkeypatch.setenv("AUX_INPUT_CASE", "CONTROL_COMBINED")
    monkeypatch.setenv("AUX_INPUT_RATE_PROFILE", "0")
    source = """import os
from types import SimpleNamespace
START_REQUEST, START_RESPONSE = 18, 146
ProtocolFailure = ValueError
events = []
def response_success(frame, kind): pass
def emit_event(name, **fields): events.append(fields)
class SerialLink:
    run_id = 0
    def exchange(self, kind):
        SerialLink.run_id += 1
        return SimpleNamespace(run_id=SerialLink.run_id), 0.01
observed = []
def main():
    observed.append((os.environ['AUX_INPUT_CASE'], int(os.environ['AUX_INPUT_RATE_PROFILE'])))
    SerialLink().exchange(START_REQUEST)
    return 0
"""
    try:
        with pytest.raises(SystemExit) as stopped:
            exec(  # noqa: S102 - locally authored runner regression
                isolation.make_program(
                    source,
                    {},
                    profiles=(0, 1),
                    cases=("CONTROL_COMBINED", "INPUT_COMBINED"),
                ),
                {},
            )
        assert stopped.value.code == 0
        assert sys.modules["input_isolation_rig"].observed == [
            ("CONTROL_COMBINED", 0),
            ("INPUT_COMBINED", 1),
        ]
        assert [
            event["run_id"] for event in sys.modules["input_isolation_rig"].events
        ] == [1, 2]
    finally:
        sys.modules.pop("input_isolation_rig", None)
    for cases in (("INPUT_COMBINED",), ("INVALID", "INPUT_COMBINED")):
        with pytest.raises(ValueError, match="one valid case"):
            isolation.make_program(source, {}, profiles=(0, 1), cases=cases)
    try:
        reset_source = source.replace("SerialLink.run_id += 1", "SerialLink.run_id = 1")
        with pytest.raises(ValueError, match="run ID reset/jump"):
            exec(  # noqa: S102 - locally authored runner regression
                isolation.make_program(
                    reset_source,
                    {},
                    profiles=(0, 1),
                    cases=("CONTROL_COMBINED", "INPUT_COMBINED"),
                ),
                {},
            )
    finally:
        sys.modules.pop("input_isolation_rig", None)


def test_stale_build_is_rejected():
    manifest = {
        "artifacts": [
            {
                "path": "firmware.ino.hex",
                "size_bytes": 3,
                "sha256": isolation.digest(b"abc"),
            }
        ]
    }
    isolation.verify_hex(b"abc", manifest)
    with pytest.raises(ValueError, match="HEX does not match"):
        isolation.verify_hex(b"bad", manifest)


def test_large_frame_manifest_requires_matching_opt_in_and_wire_validator():
    manifest = {"input_experiment": {"large_adc_frame": True}}
    assert isolation.frame_experiment_settings(
        manifest, enabled=True, host_api=False
    ) == {"AUX_INPUT_LARGE_ADC_FRAME": "1"}
    for enabled, host_api in ((False, False), (True, True)):
        with pytest.raises(ValueError):
            isolation.frame_experiment_settings(
                manifest, enabled=enabled, host_api=host_api
            )
    with pytest.raises(ValueError):
        isolation.frame_experiment_settings({}, enabled=True, host_api=False)
    with pytest.raises(ValueError):
        isolation.frame_experiment_settings(
            {"input_experiment": {"large_adc_frame": "false"}},
            enabled=False,
            host_api=False,
        )


def test_service_success_does_not_mean_firmware_passed():
    result = {
        "status": "success",
        "results": {
            "completed": True,
            "program_success": True,
            "exit_code": 1,
            "stdout": "",
        },
    }
    assert isolation.classify_result(result)["outcome"] == "TEST_FAIL"
    result["results"]["program_success"] = False
    assert isolation.classify_result(result)["outcome"] == "INFRASTRUCTURE_FAIL"
    result["results"].update(program_success=True, exit_code=0)
    assert isolation.classify_result(result)["outcome"] == "TEST_FAIL"
    result["results"]["stdout"] = 'EVIDENCE {"result":"PASS"}\n'
    assert isolation.classify_result(result)["outcome"] == "PASS"
    assert (
        isolation.classify_result(result, expected_cells=2)["outcome"]
        == "INFRASTRUCTURE_FAIL"
    )
    result["results"]["exit_code"] = -110
    summary = isolation.classify_result(result)
    assert summary["outcome"] == "INFRASTRUCTURE_FAIL"
    assert summary["evidence"] == [{"result": "PASS"}]


@pytest.mark.parametrize(
    "flag,setting",
    [
        ("gpio_preempt_probe", "AUX_INPUT_GPIO_PREEMPT_PROBE"),
        ("adc_etc_probe", "AUX_INPUT_ADC_ETC_PROBE"),
    ],
)
def test_dma_probes_require_phase_readback_and_private_rle(flag, setting):
    manifest = {
        "input_experiment": {
            "gpio_rle": True,
            "large_adc_frame": True,
            "release_fixed_1mhz": True,
            "cpu_mhz": 600,
            "gpio_rle_wire_version": 130,
            flag: True,
        }
    }
    with pytest.raises(ValueError, match="--adc-phase"):
        isolation.gpio_rle_settings(manifest, enabled=True, host_api=False)
    assert isolation.gpio_rle_settings(
        manifest, enabled=True, host_api=False, adc_phase=True
    ) == {
        "AUX_INPUT_GPIO_RLE": "1",
        "AUX_INPUT_ADC_PHASE": "1",
        setting: "1",
    }
    with pytest.raises(ValueError):
        isolation.gpio_rle_settings({}, enabled=False, host_api=False, adc_phase=True)
    manifest["input_experiment"].update(gpio_preempt_probe=True, adc_etc_probe=True)
    with pytest.raises(ValueError):
        isolation.gpio_rle_settings(
            manifest, enabled=True, host_api=False, adc_phase=True
        )


def test_long_sequences_must_fit_below_container_limit():
    assert isolation.validate_program_budget(600, 1) == 635
    assert isolation.validate_program_budget(10, 20) == 330
    for seconds, cells in ((600, 2), (600, 0), (float("nan"), 1), (float("inf"), 1)):
        with pytest.raises(ValueError, match="split into separate jobs"):
            isolation.validate_program_budget(seconds, cells)


def test_corrected_rle_selects_adc_etc_metadata_without_a_probe():
    manifest = {
        "input_experiment": {
            "gpio_rle": True,
            "large_adc_frame": True,
            "release_fixed_1mhz": True,
            "cpu_mhz": 600,
            "gpio_rle_wire_version": 130,
            "adc_etc_request": True,
        }
    }
    assert isolation.gpio_rle_settings(manifest, enabled=True, host_api=False) == {
        "AUX_INPUT_GPIO_RLE": "1",
        "AUX_INPUT_ADC_ETC_REQUEST": "1",
    }
    manifest["input_experiment"]["adc_etc_probe"] = True
    with pytest.raises(ValueError):
        isolation.gpio_rle_settings(
            manifest, enabled=True, host_api=False, adc_phase=True
        )


def test_cycle_changes_only_rate_without_reloading_firmware(monkeypatch):
    monkeypatch.setenv("AUX_INPUT_RATE_PROFILE", "0")
    source = """import os
profiles = []
def main():
    profiles.append(int(os.environ["AUX_INPUT_RATE_PROFILE"]))
    return 0
"""
    try:
        with pytest.raises(SystemExit) as stopped:
            exec(isolation.make_program(source, {}, cycle=True), {})  # noqa: S102 - locally authored test fixture
        assert stopped.value.code == 0
        assert sys.modules["input_isolation_rig"].profiles == [0, 1, 2, 3, 0]
    finally:
        sys.modules.pop("input_isolation_rig", None)


def test_explicit_profiles_skip_known_failure_but_stop_on_new_failure(monkeypatch):
    monkeypatch.setenv("AUX_INPUT_RATE_PROFILE", "0")
    source = """import os
profiles = []
def main():
    profile = int(os.environ["AUX_INPUT_RATE_PROFILE"])
    profiles.append(profile)
    return 1 if profile == 3 else 0
"""
    try:
        with pytest.raises(SystemExit) as stopped:
            exec(isolation.make_program(source, {}, profiles=(1, 2, 3, 1)), {})  # noqa: S102 - locally authored test fixture
        assert stopped.value.code == 1
        assert sys.modules["input_isolation_rig"].profiles == [1, 2, 3]
    finally:
        sys.modules.pop("input_isolation_rig", None)


def test_invalid_profile_sequences_are_rejected():
    for sequence in ((), (-1,), (5,)):
        with pytest.raises(ValueError, match="IDs 0..4"):
            isolation.make_program("", {}, profiles=sequence)
    with pytest.raises(ValueError, match="either cycle"):
        isolation.make_program("", {}, cycle=True, profiles=(1,))


def test_experimental_clock_and_rate_settings_follow_verified_manifest():
    assert isolation.experiment_settings({}) == {
        "AUX_INPUT_EQUAL_RATES": "0",
        "AUX_INPUT_CPU_MHZ": "600",
    }
    manifest = {
        "input_experiment": {"cpu_mhz": 450, "equal_rates": True},
        "target": {"fqbn": "teensy:avr:teensy40:usb=serial,speed=450,opt=o2std"},
    }
    assert isolation.experiment_settings(manifest) == {
        "AUX_INPUT_EQUAL_RATES": "1",
        "AUX_INPUT_CPU_MHZ": "450",
    }
    manifest["input_experiment"]["cpu_mhz"] = 600
    with pytest.raises(ValueError, match="disagrees"):
        isolation.experiment_settings(manifest)
    manifest["input_experiment"]["equal_rates"] = "false"
    with pytest.raises(ValueError, match="unsupported"):
        isolation.experiment_settings(manifest)


def test_submission_retains_result_without_treating_service_success_as_pass(
    monkeypatch, tmp_path
):
    import requests

    calls = []
    result = {
        "results": {"completed": True, "program_success": False, "exit_code": -130}
    }

    def post(url, **kwargs):
        calls.append(url.rsplit("/", 1)[1])
        values = {
            "start": {"test_id": "test-job"},
            "status": {"status": "success"},
            "results": result,
        }
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: values[calls[-1]]
        )

    monkeypatch.setattr(isolation, "service_preflight", lambda _: {"status": "healthy"})
    monkeypatch.setattr(requests, "post", post)
    observed = isolation.submit_program(
        "http://unused.invalid", "test-key", b"hex", "pass", tmp_path, 1
    )
    assert observed == result
    assert calls == ["start", "status", "results"]
    assert json.loads((tmp_path / "results.json").read_text()) == result
    assert isolation.classify_result(observed)["outcome"] == "INFRASTRUCTURE_FAIL"


def test_ambiguous_submission_timeout_is_never_retried(monkeypatch, tmp_path):
    import requests

    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise requests.Timeout("ambiguous submission")

    monkeypatch.setattr(isolation, "service_preflight", lambda _: {"status": "healthy"})
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(requests.Timeout):
        isolation.submit_program(
            "http://unused.invalid", "test-key", b"hex", "pass", tmp_path, 1
        )
    assert calls == ["http://unused.invalid/start"]


def test_unhealthy_preflight_prevents_submission(monkeypatch, tmp_path):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"status": "healthy", "checks": {"queue_depth": 1}},
        ),
    )
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: pytest.fail("must not submit")
    )
    with pytest.raises(RuntimeError, match="not healthy"):
        isolation.submit_program(
            "http://unused.invalid", "test-key", b"hex", "pass", tmp_path, 1
        )


@pytest.mark.parametrize("cpu", [450, 528, 600])
def test_fixed_rate_clock_manifest_requires_matching_target(cpu):
    manifest = {
        "input_experiment": {
            "cpu_mhz": cpu,
            "equal_rates": False,
            "release_fixed_1mhz": True,
        },
        "release_policy": {"fixed_1mhz": True, "core_hz": cpu * 1_000_000},
        "target": {"fqbn": f"teensy:avr:teensy40:usb=serial,speed={cpu},opt=o2std"},
    }
    assert isolation.experiment_settings(manifest) == {
        "AUX_INPUT_EQUAL_RATES": "0",
        "AUX_INPUT_CPU_MHZ": str(cpu),
        "AUX_INPUT_RELEASE_FIXED_1MHZ": "1",
    }
    if cpu != 450:
        with pytest.raises(ValueError, match="independent wire"):
            isolation.frame_experiment_settings(manifest, enabled=False, host_api=True)
    manifest["release_policy"]["core_hz"] = 123_000_000
    with pytest.raises(ValueError, match="disagrees"):
        isolation.experiment_settings(manifest)
