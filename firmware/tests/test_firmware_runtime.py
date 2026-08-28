"""Host-compiled integration checks for the cooperative firmware runtime."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIRECTORY = REPOSITORY_ROOT / "firmware"
FIRMWARE_SOURCE = FIRMWARE_DIRECTORY / "src"
CPP_TEST = FIRMWARE_DIRECTORY / "tests/firmware_runtime_test.cpp"
PORTABLE_SOURCES = (
    FIRMWARE_SOURCE / "firmware_runtime.h",
    FIRMWARE_SOURCE / "firmware_runtime.cpp",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.h",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp",
    FIRMWARE_SOURCE / "synthetic_source.h",
    FIRMWARE_SOURCE / "synthetic_source.cpp",
)


class FirmwareRuntimeTests(unittest.TestCase):
    def test_runtime_integrates_the_complete_control_plane(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-runtime-") as directory:
            executable = Path(directory) / "firmware-runtime-test"
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
                    str(FIRMWARE_SOURCE / "firmware_runtime.cpp"),
                    str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
                    str(FIRMWARE_SOURCE / "synthetic_source.cpp"),
                    str(FIRMWARE_SOURCE / "control_state.cpp"),
                    str(FIRMWARE_SOURCE / "usb_transport.cpp"),
                    str(FIRMWARE_SOURCE / "statistics.cpp"),
                    str(FIRMWARE_SOURCE / "protocol.cpp"),
                    str(FIRMWARE_SOURCE / "checksum.cpp"),
                    str(FIRMWARE_SOURCE / "checksum_benchmark.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_clock_diagnostic.cpp"),
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

    def test_runtime_is_portable_and_sketch_stays_thin(self) -> None:
        runtime_source = "\n".join(
            path.read_text(encoding="utf-8") for path in PORTABLE_SOURCES
        )
        sketch = (FIRMWARE_DIRECTORY / "firmware.ino").read_text(encoding="utf-8")
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
            "attachInterrupt",
            "IntervalTimer",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, runtime_source)

        self.assertIn('include "src/firmware_runtime.h"', sketch)
        self.assertIn('include "src/teensy_clock.h"', sketch)
        self.assertIn('include "src/teensy_usb.h"', sketch)
        self.assertIn("TeensyCdcByteStream", sketch)
        self.assertIn("FirmwareRuntime", sketch)
        self.assertIn("hardwareSerialNumber()", sketch)
        self.assertIn("firmware_runtime.service()", sketch)
        self.assertNotIn("Serial.", sketch)
        self.assertLessEqual(len(sketch.splitlines()), 42)


if __name__ == "__main__":
    unittest.main()
