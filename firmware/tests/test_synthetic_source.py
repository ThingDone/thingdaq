"""Host-compiled checks for deterministic paced firmware sources."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/synthetic_source_test.cpp"
PRODUCTION_SOURCES = (
    FIRMWARE_SOURCE / "synthetic_source.h",
    FIRMWARE_SOURCE / "synthetic_source.cpp",
)


class SyntheticSourceTests(unittest.TestCase):
    def test_realtime_and_unpaced_sources_use_the_packet_pipeline(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-synthetic-") as directory:
            executable = Path(directory) / "synthetic-source-test"
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
                    str(FIRMWARE_SOURCE / "synthetic_source.cpp"),
                    str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
                    str(FIRMWARE_SOURCE / "rle_encoder.cpp"),
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

    def test_source_is_fixed_capacity_cooperative_and_isr_free(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in PRODUCTION_SOURCES
        )
        for token in (
            "std::vector",
            "std::deque",
            "malloc(",
            "calloc(",
            "realloc(",
            "operator new",
            "attachInterrupt",
            "IntervalTimer",
            "ISR(",
            "Serial.",
            "delay(",
            "yield(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("Mode::kRealtime", source)
        self.assertIn("Mode::kUnpacedDiagnostic", source)
        self.assertIn("pipeline.beginFill", source)
        self.assertIn("pipeline.finishFill", source)
        self.assertIn("std::array", source)
        self.assertIn("pattern_ != Pattern::kDefaultRamp", source)
        self.assertIn(".flashmem.synthetic.start", source)
        self.assertIn(".flashmem.synthetic.fill_adc", source)
        self.assertIn(".flashmem.synthetic.fill_gpio", source)


if __name__ == "__main__":
    unittest.main()
