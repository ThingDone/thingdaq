"""Host-compiled fake-register tests for the Teensy dual-ADC adapters."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
FAKE_TEENSY_INCLUDE = REPOSITORY_ROOT / "firmware/tests/fakes/teensy40"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/adc_register_adapter_test.cpp"


class AdcRegisterAdapterTests(unittest.TestCase):
    def test_routes_timing_order_and_resource_isolation(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for target-register adapter tests")

        for profile_mhz, cpu_hz, bus_hz in (
            (600, 600_000_000, 150_000_000),
            (528, 528_000_000, 132_000_000),
            (450, 450_000_000, 150_000_000),
        ):
            with (
                self.subTest(profile_mhz=profile_mhz),
                tempfile.TemporaryDirectory(
                    prefix=f"thingdaq-adc-registers-{profile_mhz}-"
                ) as directory,
            ):
                executable = Path(directory) / "adc-register-adapter-test"
                compiled = subprocess.run(
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
                        f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile_mhz}",
                        f"-DTHINGDAQ_EXPECTED_CPU_HZ={cpu_hz}",
                        f"-DTHINGDAQ_EXPECTED_BUS_HZ={bus_hz}",
                        f"-I{FAKE_TEENSY_INCLUDE}",
                        f"-I{FIRMWARE_SOURCE}",
                        str(CPP_TEST),
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
                    0, completed.returncode, completed.stdout + completed.stderr
                )


if __name__ == "__main__":
    unittest.main()
