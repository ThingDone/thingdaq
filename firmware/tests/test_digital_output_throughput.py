"""Compile and run the portable output expansion throughput/memory gate."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_BENCHMARK = REPOSITORY_ROOT / "firmware/tests/digital_output_engine_benchmark.cpp"


class DigitalOutputThroughputTests(unittest.TestCase):
    def test_expansion_has_tenfold_host_rate_headroom_and_fixed_memory(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for the output expansion benchmark")

        with tempfile.TemporaryDirectory(
            prefix="thingdaq-output-expand-bench-"
        ) as directory:
            executable = Path(directory) / "digital-output-engine-benchmark"
            compiled = subprocess.run(
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
                    str(CPP_BENCHMARK),
                    str(FIRMWARE_SOURCE / "digital_output_program.cpp"),
                    str(FIRMWARE_SOURCE / "digital_output_engine.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )

        print(f"AUX_OUTPUT_EXPANSION_BENCHMARK {completed.stdout.strip()}")
        match = re.search(r"states_per_second=([0-9]+(?:\.[0-9]+)?)", completed.stdout)
        self.assertIsNotNone(match, completed.stdout)
        assert match is not None
        self.assertGreaterEqual(float(match.group(1)), 10_000_000.0)
        for field in (
            "algorithm=rle-to-gpio1-toggle",
            "target_states_per_second=1000000.000",
            "required_headroom_ratio=10.000",
            "max_blocks_per_service=1",
            "states_per_block=1016",
            "program_storage_bytes=8192",
            "dma_state_storage_bytes=16256",
            "dma_descriptor_candidate_bytes=128",
            "total_candidate_bytes=24576",
            "physical_timing_acceptance=false",
            "target_runtime_acceptance=false",
        ):
            with self.subTest(field=field):
                self.assertIn(field, completed.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
