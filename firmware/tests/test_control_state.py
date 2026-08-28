"""Host-compiled tests for firmware control state and statistics."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/control_state_test.cpp"
PRODUCTION_FILES = (
    FIRMWARE_SOURCE / "control_state.h",
    FIRMWARE_SOURCE / "control_state.cpp",
    FIRMWARE_SOURCE / "statistics.h",
    FIRMWARE_SOURCE / "statistics.cpp",
)


class FirmwareControlStateTests(unittest.TestCase):
    def test_control_state_and_statistics_are_bounded_and_deterministic(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-control-") as directory:
            executable = Path(directory) / "control-state-test"
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
                    str(FIRMWARE_SOURCE / "control_state.cpp"),
                    str(FIRMWARE_SOURCE / "statistics.cpp"),
                    str(FIRMWARE_SOURCE / "protocol.cpp"),
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

    def test_portable_control_modules_have_no_arduino_or_heap_dependency(self) -> None:
        production_source = "\n".join(
            path.read_text(encoding="utf-8") for path in PRODUCTION_FILES
        )
        forbidden = (
            "#include <Arduino",
            "std::vector",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "delay(",
            "yield(",
            "Serial.",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, production_source)

        self.assertIn("kControlOnlyConfiguration", production_source)
        self.assertIn("kStartEpoch", production_source)
        self.assertIn("partial_usb_writes", production_source)


if __name__ == "__main__":
    unittest.main()
