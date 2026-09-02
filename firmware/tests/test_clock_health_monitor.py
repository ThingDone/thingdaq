"""Host-compiled tests for bounded clock-health monitoring."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/clock_health_test.cpp"
TARGET_CPP_TEST = REPOSITORY_ROOT / "firmware/tests/clock_health_teensy_test.cpp"
FAKE_TEENSY_INCLUDE = REPOSITORY_ROOT / "firmware/tests/fakes/teensy40"


class ClockHealthTests(unittest.TestCase):
    def test_portable_monitor_reports_bounded_health_states(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-clock-health-") as directory:
            for profile, cpu_hz, bus_hz in (
                (600, 600_000_000, 150_000_000),
                (528, 528_000_000, 132_000_000),
            ):
                with self.subTest(profile=profile):
                    executable = Path(directory) / f"clock-health-test-{profile}"
                    result = subprocess.run(
                        [
                            compiler,
                            "-std=c++17",
                            "-Wall",
                            "-Wextra",
                            "-Werror",
                            "-Wconversion",
                            "-Wsign-conversion",
                            "-pedantic",
                            "-fno-exceptions",
                            "-fno-rtti",
                            f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile}",
                            f"-DTHINGDAQ_EXPECTED_CPU_HZ={cpu_hz}",
                            f"-DTHINGDAQ_EXPECTED_BUS_HZ={bus_hz}",
                            f"-I{FIRMWARE_SOURCE}",
                            str(CPP_TEST),
                            str(FIRMWARE_SOURCE / "clock_health.cpp"),
                            "-o",
                            str(executable),
                        ],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    self.assertEqual(
                        0, result.returncode, result.stdout + result.stderr
                    )
                    run = subprocess.run(
                        [str(executable)],
                        capture_output=True,
                        check=False,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(0, run.returncode, run.stdout + run.stderr)

    def test_target_adapter_bounds_sensor_and_validates_clock_readbacks(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for target-register adapter tests")

        with tempfile.TemporaryDirectory(
            prefix="thingdaq-clock-health-target-"
        ) as directory:
            for profile, cpu_hz, bus_hz in (
                (600, 600_000_000, 150_000_000),
                (528, 528_000_000, 132_000_000),
            ):
                with self.subTest(profile=profile):
                    executable = Path(directory) / f"clock-health-target-{profile}"
                    result = subprocess.run(
                        [
                            compiler,
                            "-std=c++17",
                            "-O3",
                            "-flto",
                            "-Wall",
                            "-Wextra",
                            "-Werror",
                            "-Wconversion",
                            "-Wsign-conversion",
                            "-pedantic",
                            "-fno-exceptions",
                            "-fno-rtti",
                            f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile}",
                            f"-DTHINGDAQ_EXPECTED_CPU_HZ={cpu_hz}",
                            f"-DTHINGDAQ_EXPECTED_BUS_HZ={bus_hz}",
                            f"-I{FAKE_TEENSY_INCLUDE}",
                            f"-I{FIRMWARE_SOURCE}",
                            str(TARGET_CPP_TEST),
                            "-o",
                            str(executable),
                        ],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    self.assertEqual(
                        0, result.returncode, result.stdout + result.stderr
                    )
                    run = subprocess.run(
                        [str(executable)],
                        capture_output=True,
                        check=False,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(0, run.returncode, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
