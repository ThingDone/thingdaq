"""Host-compiled coverage for the portable GPIO clock diagnostic runner."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/gpio_clock_diagnostic_test.cpp"


class GpioClockDiagnosticTests(unittest.TestCase):
    def test_exact_plans_bounds_and_fault_classification(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-gpio-clock-") as directory:
            for profile, cpu_hz, bus_hz in (
                (600, 600_000_000, 150_000_000),
                (528, 528_000_000, 132_000_000),
                (450, 450_000_000, 150_000_000),
            ):
                with self.subTest(profile=profile):
                    executable = (
                        Path(directory) / f"gpio-clock-diagnostic-test-{profile}"
                    )
                    compile_result = subprocess.run(
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
                            f"-I{FIRMWARE_SOURCE}",
                            str(CPP_TEST),
                            str(FIRMWARE_SOURCE / "gpio_clock_diagnostic.cpp"),
                            str(FIRMWARE_SOURCE / "protocol.cpp"),
                            str(FIRMWARE_SOURCE / "checksum.cpp"),
                            "-o",
                            str(executable),
                        ],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    self.assertEqual(
                        0,
                        compile_result.returncode,
                        compile_result.stdout + compile_result.stderr,
                    )
                    run_result = subprocess.run(
                        [str(executable)], capture_output=True, check=False, text=True
                    )
                    self.assertEqual(
                        0,
                        run_result.returncode,
                        run_result.stdout + run_result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
