"""Dedicated host tests for the complete synthetic firmware pipeline."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIRECTORY = REPOSITORY_ROOT / "firmware"
FIRMWARE_SOURCE = FIRMWARE_DIRECTORY / "src"
CPP_TEST = FIRMWARE_DIRECTORY / "tests/synthetic_pipeline_test.cpp"
PIPELINE_SOURCES = (
    FIRMWARE_SOURCE / "packet_buffer_pipeline.h",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp",
    FIRMWARE_SOURCE / "synthetic_source.h",
    FIRMWARE_SOURCE / "synthetic_source.cpp",
    FIRMWARE_SOURCE / "usb_transport.h",
    FIRMWARE_SOURCE / "usb_transport.cpp",
    FIRMWARE_SOURCE / "protocol.h",
    FIRMWARE_SOURCE / "protocol.cpp",
    FIRMWARE_SOURCE / "firmware_runtime.h",
    FIRMWARE_SOURCE / "firmware_runtime.cpp",
)


class SyntheticPipelineTests(unittest.TestCase):
    def test_complete_pipeline_under_wraparound_and_usb_stalls(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(
            prefix="teensy-daq-synthetic-pipeline-"
        ) as directory:
            executable = Path(directory) / "synthetic-pipeline-test"
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
                    "-DTEENSY_DAQ_TESTING=1",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "synthetic_source.cpp"),
                    str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
                    str(FIRMWARE_SOURCE / "usb_transport.cpp"),
                    str(FIRMWARE_SOURCE / "statistics.cpp"),
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

    def test_heavy_pipeline_work_is_fixed_capacity_and_isr_free(self) -> None:
        sources = {path: path.read_text(encoding="utf-8") for path in PIPELINE_SOURCES}
        combined = "\n".join(sources.values())
        for token in (
            "std::vector",
            "std::deque",
            "std::list",
            "std::map",
            "std::string",
            "std::unordered_map",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "attachInterrupt(",
            "attachInterruptVector(",
            "IntervalTimer",
            "NVIC_ENABLE_IRQ(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, combined)

        isr_definition = re.compile(
            r"(?:^|\n)\s*(?:FASTRUN\s+)?(?:void|ISR)\s+"
            r"[A-Za-z_][A-Za-z0-9_]*(?:_isr|ISR)\s*\(",
            re.IGNORECASE,
        )
        self.assertIsNone(isr_definition.search(combined))

        packet_header = sources[FIRMWARE_SOURCE / "packet_buffer_pipeline.h"]
        source_header = sources[FIRMWARE_SOURCE / "synthetic_source.h"]
        runtime = sources[FIRMWARE_SOURCE / "firmware_runtime.cpp"]
        sketch = (FIRMWARE_DIRECTORY / "firmware.ino").read_text(encoding="utf-8")
        self.assertIn("std::array", packet_header)
        self.assertIn("PacketBufferStorage", packet_header)
        self.assertIn("FixedQueue", packet_header)
        self.assertIn("kPacketBufferStorageBytes", packet_header)
        self.assertIn("kPacketPipelineStateBudgetBytes", packet_header)
        self.assertIn("std::array", source_header)
        self.assertIn("kSyntheticFramesPerLoop", combined)
        self.assertIn("pipeline.beginFill", combined)
        self.assertIn("pipeline.finishFill", combined)
        self.assertIn("encodeDataFrameInPlace", combined)
        self.assertIn("transport_.serviceTransmit()", runtime)
        self.assertLess(
            runtime.index("synthetic_source_.service("),
            runtime.index("packet_pipeline_.serviceReadyFrames()"),
        )
        self.assertLess(
            runtime.index("packet_pipeline_.serviceReadyFrames()"),
            runtime.index("transport_.serviceTransmit()"),
        )
        self.assertIn("firmware_runtime.service()", sketch)
        self.assertNotIn("attachInterrupt", sketch)
        self.assertNotIn("IntervalTimer", sketch)


if __name__ == "__main__":
    unittest.main()
