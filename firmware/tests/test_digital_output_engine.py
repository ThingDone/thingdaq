"""Host-compiled checks for the portable preloaded-output engine."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIRECTORY = REPOSITORY_ROOT / "firmware"
FIRMWARE_SOURCE = FIRMWARE_DIRECTORY / "src"
CPP_TEST = FIRMWARE_DIRECTORY / "tests/digital_output_engine_test.cpp"
MAP_FIXTURE = FIRMWARE_DIRECTORY / "tests/fixtures/combined_acquisition.map"
BUILD_HELPER_PATH = FIRMWARE_DIRECTORY / "tools/build_firmware.py"
SPEC = importlib.util.spec_from_file_location(
    "digital_output_build_firmware", BUILD_HELPER_PATH
)
assert SPEC is not None and SPEC.loader is not None
build_firmware = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_firmware
SPEC.loader.exec_module(build_firmware)


class DigitalOutputEngineTests(unittest.TestCase):
    def test_fixed_capacity_program_expansion_and_ownership(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-output-engine-") as directory:
            executable = Path(directory) / "digital-output-engine-test"
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
                    str(CPP_TEST),
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

    def test_current_map_supports_exact_six_page_repartition_candidate(self) -> None:
        linker_map = MAP_FIXTURE.read_text(encoding="utf-8")
        memory = build_firmware.parse_memory_usage(linker_map)
        packets = build_firmware.packet_buffer_usage(linker_map)

        current_primary = packets["banks"]["DTCM_PRIMARY"]["bytes"]
        current_reserve = packets["banks"]["OCRAM_RESERVE"]["bytes"]
        self.assertEqual(105 * 4096, current_primary)
        self.assertEqual(95 * 4096, current_reserve)
        self.assertEqual(34_528, memory["ram1"]["free_for_locals_bytes"])
        self.assertEqual(4_096, memory["ram2"]["free_for_heap_bytes"])

        program_bytes = 2 * 4096
        dma_allocation_bytes = 4 * 4096
        descriptor_bytes = 4 * 32
        dma_state_bytes = dma_allocation_bytes - descriptor_bytes
        self.assertEqual(16_256, dma_state_bytes)
        self.assertEqual(1_016, dma_state_bytes // 4 // 4)
        self.assertEqual(current_primary, 103 * 4096 + program_bytes)
        self.assertEqual(current_reserve, 91 * 4096 + dma_allocation_bytes)
        self.assertEqual(194 * 8096 // (2 * 8), 98_164)

    def test_portable_sources_have_no_heap_or_target_register_dependency(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                FIRMWARE_SOURCE / "digital_output_program.h",
                FIRMWARE_SOURCE / "digital_output_program.cpp",
                FIRMWARE_SOURCE / "digital_output_engine.h",
                FIRMWARE_SOURCE / "digital_output_engine.cpp",
            )
        )
        self.assertIsNone(
            re.search(r"\b(new\s|malloc\(|calloc\(|realloc\(|free\()", source)
        )
        for token in ("Arduino.h", "core_pins.h", "imxrt.h", "GPIO1_", "DMA_TCD"):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
