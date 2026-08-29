"""Host-compiled checks for bounded Teensy CDC identity and transport."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIRECTORY = REPOSITORY_ROOT / "firmware"
FIRMWARE_SOURCE = FIRMWARE_DIRECTORY / "src"
CPP_TEST = FIRMWARE_DIRECTORY / "tests/usb_transport_test.cpp"
PORTABLE_SOURCES = (
    FIRMWARE_SOURCE / "usb_transport.h",
    FIRMWARE_SOURCE / "usb_transport.cpp",
)


class FirmwareUsbTransportTests(unittest.TestCase):
    def test_transport_is_bounded_and_preserves_frame_ownership(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-usb-") as directory:
            executable = Path(directory) / "usb-transport-test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
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
                    str(FIRMWARE_SOURCE / "usb_transport.cpp"),
                    str(FIRMWARE_SOURCE / "teensy_usb.cpp"),
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

    def test_portable_transport_has_no_arduino_or_heap_dependency(self) -> None:
        portable_source = "\n".join(
            path.read_text(encoding="utf-8") for path in PORTABLE_SOURCES
        )
        forbidden = (
            "#include <Arduino",
            "std::vector",
            "std::deque",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "delay(",
            "yield(",
            "Serial.",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, portable_source)

        self.assertIn("std::array", portable_source)
        self.assertIn("kUsbRxBudgetBytesPerLoop", portable_source)
        self.assertIn("kUsbTxCallsPerVisit", portable_source)
        self.assertIn("LowerPriorityFrameSource", portable_source)

    def test_teensy_adapter_uses_core_identity_without_dtr_gating(self) -> None:
        adapter = (FIRMWARE_SOURCE / "teensy_usb.cpp").read_text(encoding="utf-8")
        sketch = (FIRMWARE_DIRECTORY / "firmware.ino").read_text(encoding="utf-8")

        self.assertIn("usb_string_product_name =", adapter)
        self.assertNotIn("usb_string_serial_number =", adapter)
        self.assertIn("usb_serial_available()", adapter)
        self.assertIn("usb_serial_read(", adapter)
        self.assertIn("usb_serial_write_buffer_free()", adapter)
        self.assertIn("usb_serial_write(", adapter)
        self.assertNotIn("usb_cdc_line_rtsdtr", adapter)
        self.assertNotIn("while (!Serial", sketch)
        self.assertNotIn("Serial.begin(115200)", sketch)
        self.assertNotIn("Serial.print", sketch)


if __name__ == "__main__":
    unittest.main()
