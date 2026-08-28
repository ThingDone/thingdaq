"""Host-compiled tests for deployable firmware checksum candidates."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CHECKSUM_HEADER = FIRMWARE_SOURCE / "checksum.h"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/checksum_candidates_test.cpp"


class ChecksumCandidateTests(unittest.TestCase):
    def test_portable_candidates_match_independent_references(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-checksum-") as directory:
            executable = Path(directory) / "checksum-candidates-test"
            compile_result = subprocess.run(
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
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
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

    def test_checksum_module_is_fixed_capacity_and_portable(self) -> None:
        source = CHECKSUM_HEADER.read_text(encoding="utf-8")
        for token in (
            "#include <Arduino",
            "std::vector",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "arm_dcache",
            "DMAMEM",
            "IntervalTimer",
            "attachInterrupt",
            "usb_serial_",
            "ENET_",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("kCrc32cReflectedPolynomial = 0x82F63B78U", source)
        self.assertIn("kCrc32IsoHdlcReflectedPolynomial", source)
        self.assertIn("kCrcTableSlices = 8U", source)
        self.assertIn("kCrcTableBytes", source)
        self.assertIn("enum class Algorithm", source)


if __name__ == "__main__":
    unittest.main()
