"""Host-compiled tests for the portable fixed-capacity protocol layer."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/protocol_primitives_test.cpp"
PROTOCOL_SOURCE = FIRMWARE_SOURCE / "protocol.cpp"
PROTOCOL_HEADER = FIRMWARE_SOURCE / "protocol.h"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"


class ProtocolPrimitiveTests(unittest.TestCase):
    def test_portable_protocol_matches_golden_frames_and_recovers(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-protocol-") as directory:
            executable = Path(directory) / "protocol-primitives-test"
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
                    str(PROTOCOL_SOURCE),
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
                [str(executable), str(FIXTURE_DIRECTORY)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                run_result.returncode,
                run_result.stdout + run_result.stderr,
            )

    def test_production_protocol_has_no_heap_or_packed_wire_access(self) -> None:
        production_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROTOCOL_HEADER, PROTOCOL_SOURCE)
        )
        forbidden = (
            "std::vector",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "#include <Arduino",
            "__attribute__((packed))",
            "#pragma pack",
            "reinterpret_cast",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, production_source)

        self.assertIn("std::array", production_source)
        self.assertIn("loadU32", production_source)
        self.assertIn("storeU32", production_source)
        self.assertIn("kMaxCommandFrameBytes", production_source)


if __name__ == "__main__":
    unittest.main()
