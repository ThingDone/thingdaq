"""Host-compiled tests for bounded dual-ADC initialization policy."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/adc_initializer_test.cpp"


class AdcInitializerTests(unittest.TestCase):
    def test_bounded_independent_initialization_and_fallback_policy(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-adc-init-") as directory:
            for profile, cpu_hz, bus_hz in (
                (600, 600_000_000, 150_000_000),
                (528, 528_000_000, 132_000_000),
                (450, 450_000_000, 150_000_000),
            ):
                with self.subTest(profile=profile):
                    executable = Path(directory) / f"adc-initializer-test-{profile}"
                    compiled = subprocess.run(
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
                            str(FIRMWARE_SOURCE / "adc_initializer.cpp"),
                            "-o",
                            str(executable),
                        ],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    self.assertEqual(
                        0, compiled.returncode, compiled.stdout + compiled.stderr
                    )
                    completed = subprocess.run(
                        [str(executable)], capture_output=True, check=False, text=True
                    )
                    self.assertEqual(
                        0,
                        completed.returncode,
                        completed.stdout + completed.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
