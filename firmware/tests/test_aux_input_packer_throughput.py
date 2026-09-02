"""Compile and run the auxiliary-input packer throughput and memory gate."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_BENCHMARK = REPOSITORY_ROOT / "firmware/tests/gpio_dual_bank_packer_benchmark.cpp"


class AuxiliaryInputPackerThroughputTests(unittest.TestCase):
    def test_dual_bank_packer_has_tenfold_host_payload_headroom(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for the dual-bank packing benchmark")

        with tempfile.TemporaryDirectory(
            prefix="thingdaq-aux-pack-bench-"
        ) as directory:
            executable = Path(directory) / "gpio-dual-bank-packer-benchmark"
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
                    str(FIRMWARE_SOURCE / "gpio_dual_bank_packer.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_batch_packer.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_dual_bank_capture.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_raw_capture.cpp"),
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
                compiled.returncode,
                compiled.stdout + compiled.stderr,
            )
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0,
                completed.returncode,
                completed.stdout + completed.stderr,
            )

        print(f"AUX_INPUT_PACKER_BENCHMARK {completed.stdout.strip()}")
        match = re.search(r"payload_mb_s=([0-9]+(?:\.[0-9]+)?)", completed.stdout)
        self.assertIsNotNone(match, completed.stdout)
        assert match is not None
        self.assertGreaterEqual(float(match.group(1)), 80.0)
        for field in (
            "algorithm=dual-bank-shift-mask",
            "target_gpio_payload_mb_s=8.000",
            "full_combined_payload_hypothesis_mb_s=12.000",
            "required_headroom_ratio=10.000",
            "paired_raw_storage_bytes=64768",
            "overflow_sink_bytes=64",
            "physical_usb_acceptance=false",
            "target_runtime_acceptance=false",
        ):
            with self.subTest(field=field):
                self.assertIn(field, completed.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
