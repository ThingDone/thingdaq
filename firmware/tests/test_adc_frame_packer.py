"""Host-compiled physical ADC packetization and epoch-boundary checks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/adc_frame_packer_test.cpp"


class AdcFramePackerTests(unittest.TestCase):
    def test_pair_layout_timestamps_gaps_checksums_and_epochs(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-adc-packer-") as directory:
            executable = Path(directory) / "adc-frame-packer-test"
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
                    str(FIRMWARE_SOURCE / "adc_frame_packer.cpp"),
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
            self.assertEqual(
                0,
                compile_result.returncode,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0,
                run_result.returncode,
                run_result.stdout + run_result.stderr,
            )

    def test_production_bridge_is_fixed_capacity_and_cooperative(self) -> None:
        source = "\n".join(
            (FIRMWARE_SOURCE / name).read_text(encoding="utf-8")
            for name in ("adc_frame_packer.h", "adc_frame_packer.cpp")
        )
        for token in (
            "std::vector",
            "std::deque",
            "malloc(",
            "calloc(",
            "realloc(",
            "operator new",
            "attachInterrupt",
            "DMAChannel",
            "nowTicks",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("handle.first_pair * protocol_v1::kAdcPairPeriodTicks", source)
        self.assertIn("std::memcpy(payload.data, handle.pairs", source)
        self.assertIn("recordSourceFrameDrops(packet::Stream::kAdc", source)


if __name__ == "__main__":
    unittest.main()
