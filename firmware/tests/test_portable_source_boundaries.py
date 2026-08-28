"""Dependency-boundary tests for portable firmware protocol/control code."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIRECTORY = REPOSITORY_ROOT / "firmware"
FIRMWARE_SOURCE = FIRMWARE_DIRECTORY / "src"

PORTABLE_PROTOCOL_CONTROL_ROOTS = (
    FIRMWARE_SOURCE / "protocol.h",
    FIRMWARE_SOURCE / "protocol.cpp",
    FIRMWARE_SOURCE / "statistics.h",
    FIRMWARE_SOURCE / "statistics.cpp",
    FIRMWARE_SOURCE / "control_state.h",
    FIRMWARE_SOURCE / "control_state.cpp",
)
PORTABLE_TRANSLATION_UNITS = (
    FIRMWARE_SOURCE / "protocol.cpp",
    FIRMWARE_SOURCE / "statistics.cpp",
    FIRMWARE_SOURCE / "control_state.cpp",
)
HARDWARE_API_HEADERS = {
    "Arduino.h",
    "core_pins.h",
    "imxrt.h",
    "usb_desc.h",
    "usb_names.h",
    "usb_serial.h",
}
EXPECTED_HARDWARE_INCLUDE_OWNERS = {
    FIRMWARE_SOURCE / "board_config.h": {"core_pins.h", "imxrt.h"},
    FIRMWARE_SOURCE / "adc_initializer_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "adc_trigger_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "checksum_benchmark_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "gpio_clock_diagnostic_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "gpio_capture_diagnostic_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "gpio_raw_capture_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "gpio_batch_packer_teensy.cpp": {
        "core_pins.h",
        "imxrt.h",
    },
    FIRMWARE_SOURCE / "teensy_usb.cpp": {
        "Arduino.h",
        "usb_desc.h",
        "usb_names.h",
        "usb_serial.h",
    },
    FIRMWARE_SOURCE / "teensy_clock.cpp": {"Arduino.h"},
}
_QUOTED_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_ANGLE_INCLUDE = re.compile(r"^\s*#\s*include\s+<([^>]+)>", re.MULTILINE)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _project_dependency_closure(roots: tuple[Path, ...]) -> set[Path]:
    pending = list(roots)
    visited: set[Path] = set()
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        visited.add(path)
        for include in _QUOTED_INCLUDE.findall(_source(path)):
            candidates = (path.parent / include, FIRMWARE_SOURCE / include)
            dependency = next(
                (
                    candidate.resolve()
                    for candidate in candidates
                    if candidate.is_file()
                ),
                None,
            )
            if dependency is not None and dependency not in visited:
                pending.append(dependency)
    return visited


class PortableSourceBoundaryTests(unittest.TestCase):
    def test_protocol_control_closure_has_no_arduino_api_dependency(self) -> None:
        closure = _project_dependency_closure(PORTABLE_PROTOCOL_CONTROL_ROOTS)
        expected_roots = {path.resolve() for path in PORTABLE_PROTOCOL_CONTROL_ROOTS}
        self.assertTrue(expected_roots <= closure)
        self.assertTrue(
            all(path.is_relative_to(FIRMWARE_SOURCE.resolve()) for path in closure),
            closure,
        )

        observed_hardware_headers: set[str] = set()
        sources: list[str] = []
        for path in closure:
            source = _source(path)
            sources.append(source)
            observed_hardware_headers.update(
                set(_ANGLE_INCLUDE.findall(source)) & HARDWARE_API_HEADERS
            )
        combined_source = "\n".join(sources)

        self.assertEqual(set(), observed_hardware_headers)
        self.assertNotIn("teensy_usb.h", {path.name for path in closure})
        for token in (
            "Serial.",
            "usb_serial_",
            "digitalRead(",
            "digitalWrite(",
            "analogRead(",
            "delay(",
            "yield(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, combined_source)

    def test_hardware_headers_are_confined_to_guarded_narrow_adapters(self) -> None:
        observed: dict[Path, set[str]] = {}
        for path in FIRMWARE_SOURCE.rglob("*"):
            if path.suffix not in {".h", ".cpp"}:
                continue
            headers = set(_ANGLE_INCLUDE.findall(_source(path))) & HARDWARE_API_HEADERS
            if headers:
                observed[path] = headers

        self.assertEqual(EXPECTED_HARDWARE_INCLUDE_OWNERS, observed)
        target_guard = "#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)"
        for adapter in EXPECTED_HARDWARE_INCLUDE_OWNERS:
            with self.subTest(adapter=adapter.name):
                self.assertIn(target_guard, _source(adapter))

        usb_adapter = _source(FIRMWARE_SOURCE / "teensy_usb.cpp")
        usb_interface = _source(FIRMWARE_SOURCE / "usb_transport.h")
        self.assertIn("class CdcByteStream", usb_interface)
        self.assertIn("TeensyCdcByteStream::read", usb_adapter)
        self.assertIn("TeensyCdcByteStream::write", usb_adapter)

    def test_gpio_stop_requests_a_complete_dma_boundary_before_shutdown(self) -> None:
        adapter = _source(FIRMWARE_SOURCE / "gpio_raw_capture_teensy.cpp")
        boundary = adapter.index("bool waitForCompleteStopBoundary()")
        dreq = adapter.index("DMA_TCD_CSR_DREQ", boundary)
        wait = adapter.index("DMA_ERQ & gpio_dma_route::kEdmaChannelMask", dreq)
        stop = adapter.index("StopReport stopHardware()", wait)
        request = adapter.index("waitForCompleteStopBoundary()", stop)
        disable = adapter.index("disableHardware();", request)
        partial = adapter.index("activeSamples()", disable)

        self.assertLess(boundary, dreq)
        self.assertLess(dreq, wait)
        self.assertLess(stop, request)
        self.assertLess(request, disable)
        self.assertLess(disable, partial)
        self.assertIn("kStopBoundaryTimeoutCycles", adapter[boundary:stop])
        self.assertIn("partial_samples != 0U", adapter[stop:])

    def test_adc_target_owns_the_core_startup_hook_without_calibrating_early(
        self,
    ) -> None:
        adapter = _source(FIRMWARE_SOURCE / "adc_initializer_teensy.cpp")

        hook = adapter.index('extern "C" TEENSY_DAQ_ADC_TARGET_CODE')
        initializer = adapter.index("namespace teensy_daq::adc", hook)
        deferred_body = adapter[hook:initializer]
        self.assertIn("void analog_init(void) {}", deferred_body)
        self.assertNotIn("ADC1", deferred_body)
        self.assertNotIn("ADC2", deferred_body)
        self.assertNotIn("while", deferred_body)
        self.assertIn("F_BUS_ACTUAL != settings.ipg_clock_hz", adapter)
        self.assertIn("F_BUS_ACTUAL == settings.ipg_clock_hz", adapter)

    def test_host_dependency_output_excludes_teensy_core_and_adapters(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        completed = subprocess.run(
            [
                compiler,
                "-std=c++17",
                f"-I{FIRMWARE_SOURCE}",
                "-MM",
                *(str(path) for path in PORTABLE_TRANSLATION_UNITS),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertNotIn(".arduino15", completed.stdout)
        self.assertNotIn("teensy_usb", completed.stdout)
        self.assertNotIn("board_config", completed.stdout)


if __name__ == "__main__":
    unittest.main()
