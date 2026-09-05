"""Host-compiled variable-rate scheduler and auxiliary GPIO join tests."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/aux_input_portable_test.cpp"


class AuxiliaryInputPortableTests(unittest.TestCase):
    def test_scheduler_joiner_packer_and_dynamic_packet_layouts(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-aux-portable-") as directory:
            executable = Path(directory) / "aux-input-portable-test"
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
                    str(FIRMWARE_SOURCE / "variable_rate_scheduler.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_dual_bank_capture.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_dual_bank_packer.cpp"),
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

    def test_portable_sources_have_no_heap_or_target_dependencies(self) -> None:
        source = "\n".join(
            (FIRMWARE_SOURCE / name).read_text(encoding="utf-8")
            for name in (
                "rate_profile_table.h",
                "stream_layout.h",
                "variable_rate_scheduler.h",
                "variable_rate_scheduler.cpp",
                "gpio_dual_bank_capture.h",
                "gpio_dual_bank_capture.cpp",
                "gpio_dual_bank_packer.h",
                "gpio_dual_bank_packer.cpp",
            )
        )
        for token in (
            "std::vector",
            "std::deque",
            "malloc(",
            "calloc(",
            "realloc(",
            "operator new",
            "Arduino.h",
            "core_pins.h",
            "imxrt.h",
            "digitalRead(",
            "pinMode(",
            "DMAChannel",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("std::array", source)
        self.assertIn("rollbackTransaction", source)
        self.assertIn("generation_skew_events", source)
        self.assertIn("packDualBankWord", source)


if __name__ == "__main__":
    unittest.main()
