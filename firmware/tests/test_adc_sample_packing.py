"""Host round-trip tests for experimental ADC sample packing."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AdcSamplePackingTests(unittest.TestCase):
    def test_exhaustive_round_trips(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required")
        with tempfile.TemporaryDirectory(prefix="thingdaq-adc-packing-") as directory:
            executable = Path(directory) / "adc-sample-packing-test"
            result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O3",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    f"-I{ROOT / 'firmware/src'}",
                    str(ROOT / "firmware/tests/adc_sample_packing_test.cpp"),
                    str(ROOT / "firmware/src/adc_sample_packing.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = subprocess.run(
                [str(executable)], capture_output=True, text=True, check=False
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
