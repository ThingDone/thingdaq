"""Combined ADC/GPIO ownership, scheduling, and linked-memory tests."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIRECTORY = REPOSITORY_ROOT / "firmware"
FIRMWARE_SOURCE = FIRMWARE_DIRECTORY / "src"
CPP_TEST = FIRMWARE_DIRECTORY / "tests/combined_dma_pipeline_test.cpp"
MAP_FIXTURE = FIRMWARE_DIRECTORY / "tests/fixtures/combined_acquisition.map"
BUILD_HELPER_PATH = FIRMWARE_DIRECTORY / "tools/build_firmware.py"
SPEC = importlib.util.spec_from_file_location(
    "combined_acquisition_build_firmware", BUILD_HELPER_PATH
)
assert SPEC is not None and SPEC.loader is not None
build_firmware = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_firmware
SPEC.loader.exec_module(build_firmware)

Span = tuple[str, int, int]


def _span(name: str, allocation: dict[str, Any]) -> Span:
    start = int(allocation["address"], 16)
    return name, start, start + int(allocation["bytes"])


def _assert_disjoint(spans: list[Span]) -> None:
    ordered = sorted(spans, key=lambda span: span[1])
    for previous, current in pairwise(ordered):
        if current[1] < previous[2]:
            raise AssertionError(
                f"{previous[0]} overlaps {current[0]} in linked memory"
            )


def _memory_regions(linker_map: str) -> dict[str, tuple[int, int]]:
    regions: dict[str, tuple[int, int]] = {}
    for name, origin, length in re.findall(
        r"^(DTCM|RAM)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+rw$",
        linker_map,
        flags=re.MULTILINE,
    ):
        start = int(origin, 16)
        regions[name] = (start, start + int(length, 16))
    return regions


def _section(linker_map: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"^{re.escape(name)}\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)$",
        linker_map,
        flags=re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"linker map is missing {name}")
    start = int(match.group(1), 16)
    return start, start + int(match.group(2), 16)


def _combined_spans(linker_map: str) -> tuple[list[Span], dict[str, Any]]:
    packet = build_firmware.packet_buffer_usage(linker_map)
    adc = build_firmware.adc_dma_buffer_usage(linker_map)
    gpio_raw = build_firmware.gpio_raw_dma_buffer_usage(linker_map)
    gpio_packed = build_firmware.gpio_packed_buffer_usage(linker_map)
    usb_tx_record = build_firmware.parse_nm_symbols(linker_map).get("txbuffer")
    if usb_tx_record is None:
        raise AssertionError("linker map is missing the pinned USB TX ring")
    usb_tx_address, usb_tx_bytes, usb_tx_type = usb_tx_record
    if usb_tx_type.upper() != "B":
        raise AssertionError("pinned USB TX ring is not writable storage")
    usb_tx = {
        "address": f"0x{usb_tx_address:08x}",
        "bytes": usb_tx_bytes,
    }
    spans = [
        *(
            _span(f"packet:{name}", allocation)
            for name, allocation in packet["banks"].items()
        ),
        *(
            _span(f"adc:{name}", allocation)
            for name, allocation in adc["allocations"].items()
        ),
        *(
            _span(f"gpio-raw:{name}", allocation)
            for name, allocation in gpio_raw["allocations"].items()
        ),
        _span("gpio-packed:RING", gpio_packed),
        _span("usb:TX", usb_tx),
    ]
    return spans, {
        "packet": packet,
        "adc": adc,
        "gpio_raw": gpio_raw,
        "gpio_packed": gpio_packed,
        "usb_tx": usb_tx,
    }


class CombinedAcquisitionTests(unittest.TestCase):
    def test_concurrent_dma_pipeline_pressure_wrap_and_reuse(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(
            prefix="teensy-daq-combined-acquisition-"
        ) as directory:
            executable = Path(directory) / "combined-acquisition-test"
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
                    "-DTEENSY_DAQ_TESTING=1",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "adc_dma_capture.cpp"),
                    str(FIRMWARE_SOURCE / "adc_frame_packer.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_raw_capture.cpp"),
                    str(FIRMWARE_SOURCE / "gpio_batch_packer.cpp"),
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
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )

    def test_linker_map_proves_combined_memory_budget_and_non_overlap(self) -> None:
        linker_map = MAP_FIXTURE.read_text(encoding="utf-8")
        memory = build_firmware.parse_memory_usage(linker_map)
        build_firmware.validate_memory_headroom(memory)
        regions = _memory_regions(linker_map)
        spans, resources = _combined_spans(linker_map)

        self.assertEqual(
            {"DTCM": (0x20000000, 0x20080000), "RAM": (0x20200000, 0x20280000)},
            regions,
        )
        _assert_disjoint(spans)
        for name, start, end in spans:
            region = (
                regions["DTCM"] if name == "packet:DTCM_PRIMARY" else regions["RAM"]
            )
            with self.subTest(allocation=name):
                self.assertGreaterEqual(start, region[0])
                self.assertLessEqual(end, region[1])

        ram1_buffer_bytes = resources["packet"]["banks"]["DTCM_PRIMARY"]["bytes"]
        ram2_buffer_bytes = (
            resources["packet"]["banks"]["OCRAM_RESERVE"]["bytes"]
            + resources["adc"]["total_bytes"]
            + resources["gpio_raw"]["total_bytes"]
            + resources["gpio_packed"]["bytes"]
        )
        self.assertEqual(430_080, ram1_buffer_bytes)
        self.assertEqual(495_264, ram2_buffer_bytes)
        self.assertEqual(8_192, resources["usb_tx"]["bytes"])
        self.assertLessEqual(ram1_buffer_bytes, regions["DTCM"][1] - regions["DTCM"][0])
        ram2_and_usb_bytes = ram2_buffer_bytes + resources["usb_tx"]["bytes"]
        self.assertEqual(503_456, ram2_and_usb_bytes)
        self.assertLessEqual(
            ram2_and_usb_bytes,
            regions["RAM"][1] - regions["RAM"][0],
        )
        self.assertGreaterEqual(memory["ram1"]["free_for_locals_bytes"], 32_768)

        dma_start, dma_end = _section(linker_map, ".bss.dma")
        self.assertEqual(regions["RAM"][0], dma_start)
        self.assertEqual(memory["ram2"]["variables_bytes"], dma_end - dma_start)
        self.assertEqual(
            memory["ram2"]["free_for_heap_bytes"], regions["RAM"][1] - dma_end
        )

    def test_combined_map_overlap_guard_rejects_two_storage_owners(self) -> None:
        linker_map = MAP_FIXTURE.read_text(encoding="utf-8")
        spans, _ = _combined_spans(linker_map)
        adc_ring = next(span for span in spans if span[0] == "adc:RING")
        conflicting = [
            span
            if span[0] != "gpio-packed:RING"
            else (span[0], adc_ring[1], adc_ring[2])
            for span in spans
        ]
        with self.assertRaisesRegex(AssertionError, "overlaps"):
            _assert_disjoint(conflicting)


if __name__ == "__main__":
    unittest.main()
