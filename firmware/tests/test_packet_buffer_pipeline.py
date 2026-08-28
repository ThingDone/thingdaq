"""Host checks for the fixed packet-buffer ownership pipeline."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/packet_buffer_pipeline_test.cpp"
PRODUCTION_SOURCES = (
    FIRMWARE_SOURCE / "packet_buffer_pipeline.h",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp",
)


class PacketBufferPipelineTests(unittest.TestCase):
    def test_ownership_pipeline_is_fixed_and_transport_integrated(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-packets-") as directory:
            executable = Path(directory) / "packet-buffer-pipeline-test"
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
                    str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
                    str(FIRMWARE_SOURCE / "usb_transport.cpp"),
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

    def test_pipeline_has_no_heap_hardware_or_isr_work(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in PRODUCTION_SOURCES
        )
        forbidden = (
            "std::vector",
            "std::deque",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "#include <Arduino",
            "arm_dcache",
            "attachInterrupt",
            "IntervalTimer",
            "usb_serial_",
            "Serial.",
            "yield(",
            "delay(",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        for state in ("kFree", "kFilling", "kReady", "kTransmitting"):
            self.assertIn(state, source)
        self.assertIn("std::array", source)
        self.assertIn("FixedQueue", source)
        self.assertIn("encodeDataFrameInPlace", source)
        self.assertIn("kPacketPipelineStateBudgetBytes", source)


if __name__ == "__main__":
    unittest.main()
