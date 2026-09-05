"""Portable calibrated sensor and real protocol/state-machine coverage."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("release", [False, True])
def test_temperature_sensor_and_command(tmp_path, release):
    source = ROOT / "firmware/src"
    executable = tmp_path / "temperature"
    result = subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wconversion",
            "-Wsign-conversion",
            f"-I{source}",
            *(["-DTHINGDAQ_RELEASE_FIXED_1MHZ=1"] if release else []),
            str(
                ROOT
                / "firmware/tests"
                / ("release_policy_test.cpp" if release else "temperature_test.cpp")
            ),
            *(
                str(source / name)
                for name in (
                    "control_state.cpp",
                    "statistics.cpp",
                    "protocol.cpp",
                    "checksum.cpp",
                )
            ),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    subprocess.run([str(executable)], check=True)
