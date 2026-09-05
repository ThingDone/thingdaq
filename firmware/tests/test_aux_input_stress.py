"""Compile and run the independent auxiliary-input fixed-capacity stress gate."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/aux_input_stress_test.cpp"


class AuxiliaryInputStressTests(unittest.TestCase):
    def test_scheduler_packing_generation_pressure_and_stop_stress(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-aux-stress-") as directory:
            executable = Path(directory) / "aux-input-stress-test"
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
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "variable_rate_scheduler.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_dual_bank_capture.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_dual_bank_packer.cpp"),
                    str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
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
            self.assertEqual(
                "auxiliary-input fixed-capacity stress checks passed",
                run_result.stdout.strip(),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
