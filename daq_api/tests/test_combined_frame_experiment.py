"""Cross-language checks for the combined no-checksum frame experiment."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from thingdone_daq.combined_frame_experiment import (
    CombinedSequenceTracker,
    decode_combined_frame,
)

ROOT = Path(__file__).resolve().parents[2]


class CombinedFrameExperimentTests(unittest.TestCase):
    def test_firmware_frames_decode_and_expose_integrity_loss(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required")
        with tempfile.TemporaryDirectory(prefix="thingdaq-combined-frame-") as temp:
            directory = Path(temp)
            executable = directory / "combined-frame-oracle"
            frame8 = directory / "combined8.bin"
            frame16 = directory / "combined16.bin"
            result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O3",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    f"-I{ROOT / 'firmware/src'}",
                    str(ROOT / "firmware/tests/combined_frame_experiment_oracle.cpp"),
                    str(ROOT / "firmware/src/combined_frame_experiment.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = subprocess.run(
                [str(executable), str(frame8), str(frame16)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            decoded8 = decode_combined_frame(
                frame8.read_bytes(), gpio_bytes_per_sample=1
            )
            decoded16 = decode_combined_frame(
                frame16.read_bytes(), gpio_bytes_per_sample=2
            )
            self.assertEqual((5104, 6116), (frame8.stat().st_size, frame16.stat().st_size))
            self.assertEqual((1, 2, 0xA5), (decoded8.adc0[0], decoded8.adc1[0], decoded8.gpio[0]))
            self.assertEqual(0x1234, decoded16.gpio[0])

            corrupted = bytearray(frame8.read_bytes())
            corrupted[44 + 5 * 100] ^= 0x01
            changed = decode_combined_frame(bytes(corrupted), gpio_bytes_per_sample=1)
            self.assertNotEqual(decoded8.adc0[100], changed.adc0[100])

            tracker = CombinedSequenceTracker()
            self.assertEqual(0, tracker.observe(decoded8))
            jumped_wire = bytearray(frame8.read_bytes())
            jumped_wire[24:28] = (13).to_bytes(4, "little")
            jumped = decode_combined_frame(bytes(jumped_wire), gpio_bytes_per_sample=1)
            self.assertEqual(1, tracker.observe(jumped))
            self.assertEqual(1, tracker.dropped_frames)


if __name__ == "__main__":
    unittest.main()
