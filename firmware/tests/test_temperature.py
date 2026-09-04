"""Portable calibrated sensor and real protocol/state-machine coverage."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_temperature_sensor_and_command(tmp_path):
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
            str(ROOT / "firmware/tests/temperature_test.cpp"),
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
