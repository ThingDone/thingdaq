"""Host-compiled tests for the portable checksum microbenchmark runner."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/checksum_benchmark_test.cpp"
BENCHMARK_SOURCE = FIRMWARE_SOURCE / "checksum_benchmark.cpp"
CHECKSUM_SOURCE = FIRMWARE_SOURCE / "checksum.cpp"


class ChecksumBenchmarkTests(unittest.TestCase):
    def test_counter_cache_vector_and_duration_semantics(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-benchmark-") as directory:
            executable = Path(directory) / "checksum-benchmark-test"
            compile_result = subprocess.run(
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
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "checksum_benchmark.cpp"),
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

    def test_compiler_optimization_guards_are_explicit(self) -> None:
        benchmark_source = BENCHMARK_SOURCE.read_text(encoding="utf-8")
        checksum_source = CHECKSUM_SOURCE.read_text(encoding="utf-8")

        self.assertIn("volatile std::uint32_t g_published_digest", benchmark_source)
        self.assertIn('__asm__ volatile(""', benchmark_source)
        self.assertGreaterEqual(benchmark_source.count("compilerBarrier("), 8)
        self.assertIn("g_published_digest = digest", benchmark_source)
        self.assertIn("noinline, noipa, used", checksum_source)


if __name__ == "__main__":
    unittest.main()
