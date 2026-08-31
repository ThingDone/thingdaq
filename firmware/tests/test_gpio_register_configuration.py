"""Host-compiled isolation checks for the target GPIO register route."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
FAKE_TEENSY_INCLUDE = REPOSITORY_ROOT / "firmware/tests/fakes/teensy40"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/gpio_register_configuration_test.cpp"


class GpioRegisterConfigurationTests(unittest.TestCase):
    def test_reserved_gpio_pit_xbar_and_edma_registers_are_isolated(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for target-register adapter tests")

        with tempfile.TemporaryDirectory(
            prefix="thingdaq-gpio-registers-"
        ) as directory:
            executable = Path(directory) / "gpio-register-configuration-test"
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
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )


if __name__ == "__main__":
    unittest.main()
