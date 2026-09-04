"""Compile real scheduler/layout/packet code for every research build selection."""
import importlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("cpu", [600_000_000, 450_000_000])
@pytest.mark.parametrize("equal", [0, 1])
def test_input_rate_clock(cpu, equal, tmp_path):
    source = ROOT / "firmware/src"
    executable = tmp_path / "input-rate-clock"
    compiled = subprocess.run([
        "g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
        f"-DTHINGDAQ_EXPERIMENT_CPU_HZ={cpu}U",
        f"-DTHINGDAQ_EXPERIMENT_EQUAL_RATES={equal}", f"-I{source}",
        str(ROOT / "firmware/tests/input_rate_clock_test.cpp"),
        *(str(source / name) for name in (
            "variable_rate_scheduler.cpp", "packet_buffer_pipeline.cpp",
            "protocol.cpp", "checksum.cpp", "gpio_clock_diagnostic.cpp")), "-o", str(executable),
    ], capture_output=True, text=True, check=False)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_build_identity_distinguishes_clock_and_ratio(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "firmware/tools"))
    builder = importlib.import_module("build_input_experiment")
    original = builder.base.BuildIdentity(
        source_id="a" * 64, build_id="thingdaq-aaaaaaaaaaaaaaaa",
        timestamp_epoch=1788552674, timestamp_utc="2026-09-04T20:11:14Z")
    identities = [builder.experiment_identity(original, cpu, equal)
                  for cpu in (600, 450) for equal in (False, True)]
    assert len({identity.build_id for identity in identities}) == 4
    assert all(identity.timestamp_epoch == original.timestamp_epoch for identity in identities)
    assert builder.experiment_identity(original, 600, False) == identities[0]
