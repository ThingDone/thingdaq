"""Host-compiled tests for bounded firmware RLE and adaptive ownership."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/rle_encoder_test.cpp"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures-v2"
PRODUCTION_SOURCES = (
    FIRMWARE_SOURCE / "rle_encoder.h",
    FIRMWARE_SOURCE / "rle_encoder.cpp",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.h",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp",
)


class RLEEncoderTests(unittest.TestCase):
    def test_portable_codec_and_adaptive_page_ownership(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-rle-") as directory:
            executable = Path(directory) / "rle-encoder-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    "-fno-exceptions",
                    "-fno-rtti",
                    "-DTHINGDAQ_TESTING=1",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "rle_encoder.cpp"),
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
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable), str(FIXTURE_DIRECTORY)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )

    def test_production_transform_is_allocation_and_isr_free(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in PRODUCTION_SOURCES
        )
        for token in (
            "std::vector",
            "std::deque",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "new ",
            "delete ",
            "arm_dcache",
            "attachInterrupt",
            "IntervalTimer",
            "DMAChannel",
            "isr(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertIn("BufferState::kTransforming", source)
        self.assertIn("takeTransformBuffer", source)
        self.assertIn("plan.encoded_frame_bytes <", source)


if __name__ == "__main__":
    unittest.main()
