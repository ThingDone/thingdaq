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

        with tempfile.TemporaryDirectory(prefix="teensy-daq-cpp-") as directory:
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
