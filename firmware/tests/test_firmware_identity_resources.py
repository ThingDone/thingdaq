"""Host-compiled checks for firmware identity, capabilities, and resources."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/identity_resource_test.cpp"


class FirmwareIdentityResourceTests(unittest.TestCase):
    def test_identity_header_accepts_only_both_reviewed_clock_profiles(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        for profile_mhz, cpu_hz, bus_hz in (
            (600, 600_000_000, 150_000_000),
            (528, 528_000_000, 132_000_000),
        ):
            with self.subTest(profile_mhz=profile_mhz):
                source = f"""#include "firmware_identity.h"
static_assert(thingdaq::identity::kCpuProfileMhz == {profile_mhz}U);
static_assert(thingdaq::identity::kExpectedCpuHz == {cpu_hz}U);
static_assert(thingdaq::identity::kExpectedBusHz == {bus_hz}U);
static_assert(thingdaq::identity::runtimeClocksMatchProfile(
    {cpu_hz}U, {bus_hz}U));
static_assert(!thingdaq::identity::runtimeClocksMatchProfile(
    {cpu_hz - 1}U, {bus_hz}U));
"""
                result = subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-fsyntax-only",
                        f"-I{FIRMWARE_SOURCE}",
                        f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile_mhz}",
                        f"-DTHINGDAQ_EXPECTED_CPU_HZ={cpu_hz}",
                        f"-DTHINGDAQ_EXPECTED_BUS_HZ={bus_hz}",
                        "-x",
                        "c++",
                        "-",
                    ],
                    input=source,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)

        invalid = subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-fsyntax-only",
                f"-I{FIRMWARE_SOURCE}",
                "-DTHINGDAQ_CPU_PROFILE_MHZ=720",
                "-DTHINGDAQ_EXPECTED_CPU_HZ=720000000",
                "-DTHINGDAQ_EXPECTED_BUS_HZ=144000000",
                "-x",
                "c++",
                "-",
            ],
            input='#include "firmware_identity.h"\n',
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertNotEqual(0, invalid.returncode)
        self.assertIn("explicit 600 or 528 MHz", invalid.stderr)

    def test_board_registry_rejects_unsupported_arduino_targets(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        unsupported_definitions = (
            ("-DARDUINO=10819",),
            ("-DARDUINO=10819", "-DARDUINO_TEENSY41", "-D__IMXRT1062__"),
            ("-DARDUINO=10819", "-DARDUINO_TEENSY40"),
        )
        for definitions in unsupported_definitions:
            with self.subTest(definitions=definitions):
                compile_result = subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-fsyntax-only",
                        f"-I{FIRMWARE_SOURCE}",
                        *definitions,
                        "-x",
                        "c++",
                        "-",
                    ],
                    input='#include "board_config.h"\n',
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertNotEqual(0, compile_result.returncode)
                self.assertIn(
                    "require Teensy 4.0 / i.MX RT1062",
                    compile_result.stderr,
                )

    def test_portable_headers_compile_and_validate_the_production_registry(
        self,
    ) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-cpp-") as directory:
            executable = Path(directory) / "identity-resource-test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
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
                0,
                compile_result.returncode,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                [str(executable)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                run_result.returncode,
                run_result.stdout + run_result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
