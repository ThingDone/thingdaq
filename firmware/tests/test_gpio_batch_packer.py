"""Host-compiled GPIO batch mapping, framing, ownership, and speed checks."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/gpio_batch_packer_test.cpp"
CPP_BENCHMARK = REPOSITORY_ROOT / "firmware/tests/gpio_batch_packer_benchmark.cpp"
PRODUCTION_SOURCES = (
    FIRMWARE_SOURCE / "gpio_batch_packer.h",
    FIRMWARE_SOURCE / "gpio_batch_packer.cpp",
)


def _compile(
    compiler: str, source: Path, output: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
            str(source),
            str(FIRMWARE_SOURCE / "gpio_batch_packer.cpp"),
            str(FIRMWARE_SOURCE / "gpio_raw_capture.cpp"),
            str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
            str(FIRMWARE_SOURCE / "usb_transport.cpp"),
            str(FIRMWARE_SOURCE / "statistics.cpp"),
            str(FIRMWARE_SOURCE / "protocol.cpp"),
            str(FIRMWARE_SOURCE / "checksum.cpp"),
            "-o",
            str(output),
        ],
        capture_output=True,
        check=False,
        text=True,
    )


class GpioBatchPackerTests(unittest.TestCase):
    def test_mapping_framing_gaps_counters_and_diagnostic_boundary(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-gpio-packer-") as directory:
            executable = Path(directory) / "gpio-batch-packer-test"
            compiled = _compile(compiler, CPP_TEST, executable)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )

    def test_selected_batch_algorithm_is_measured_with_host_headroom(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for the packing benchmark")

        with tempfile.TemporaryDirectory(
            prefix="teensy-daq-gpio-pack-bench-"
        ) as directory:
            executable = Path(directory) / "gpio-batch-packer-benchmark"
            compiled = _compile(compiler, CPP_BENCHMARK, executable)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )
            match = re.search(r"payload_mb_s=([0-9]+(?:\.[0-9]+)?)", completed.stdout)
            self.assertIsNotNone(match, completed.stdout)
            assert match is not None
            self.assertGreaterEqual(float(match.group(1)), 40.0)
            self.assertIn("algorithm=shift-mask-unrolled-4", completed.stdout)
            self.assertIn("target_payload_mb_s=4.000", completed.stdout)

    def test_production_packer_is_fixed_capacity_and_main_loop_only(self) -> None:
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
            "digitalRead(",
            "pinMode(",
            "attachInterrupt",
            "IntervalTimer",
            "DMAChannel",
            "arm_dcache",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("packGpio2Batch", source)
        self.assertIn("FixedQueue", source)
        self.assertIn("recordSourceFrameDrops", source)
        self.assertIn("expected_pressure_drop", source)
        self.assertIn("kPackedWireBytesPerSample = 1U", source)
        self.assertNotIn("pipeline.freeBuffers()", source)
        self.assertNotIn("sizeof(std::uint32_t) * sample_count", source)


if __name__ == "__main__":
    unittest.main()
