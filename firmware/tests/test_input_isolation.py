"""Offline coverage for the cold-boot experiment submission wrapper."""

import importlib.util
import sys
from pathlib import Path

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
            exec(isolation.make_program(source, {"AUX_INPUT_RUN_DIAGNOSTIC": "0", "AUX_INPUT_TEMPERATURE": "1"}), {})  # noqa: S102 - locally authored test fixture
        assert stopped.value.code == 7
    finally:
        sys.modules.pop("input_isolation_rig", None)


def test_digest_is_sha256():
    assert (
        isolation.digest(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


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
    for sequence in ((), (-1,), (4,)):
        with pytest.raises(ValueError, match="IDs 0..3"):
            isolation.make_program("", {}, profiles=sequence)
    with pytest.raises(ValueError, match="either cycle"):
        isolation.make_program("", {}, cycle=True, profiles=(1,))


def test_experimental_clock_and_rate_settings_follow_verified_manifest():
    assert isolation.experiment_settings({}) == {
        "AUX_INPUT_EQUAL_RATES": "0", "AUX_INPUT_CPU_MHZ": "600"}
    manifest = {
        "input_experiment": {"cpu_mhz": 450, "equal_rates": True},
        "target": {"fqbn": "teensy:avr:teensy40:usb=serial,speed=450,opt=o2std"},
    }
    assert isolation.experiment_settings(manifest) == {
        "AUX_INPUT_EQUAL_RATES": "1", "AUX_INPUT_CPU_MHZ": "450"}
    manifest["input_experiment"]["cpu_mhz"] = 600
    with pytest.raises(ValueError, match="disagrees"):
        isolation.experiment_settings(manifest)
    manifest["input_experiment"]["equal_rates"] = "false"
    with pytest.raises(ValueError, match="unsupported"):
        isolation.experiment_settings(manifest)
