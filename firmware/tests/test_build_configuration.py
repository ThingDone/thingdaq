"""Tests for the pinned firmware build boundary and cooperative sketch."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_HELPER_PATH = REPOSITORY_ROOT / "firmware/tools/build_firmware.py"
SPEC = importlib.util.spec_from_file_location("build_firmware", BUILD_HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
build_firmware = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_firmware
SPEC.loader.exec_module(build_firmware)


class BuildConfigurationTests(unittest.TestCase):
    def test_helper_pins_the_complete_target_and_export_directory(self) -> None:
        identity = build_firmware.BuildIdentity(
            source_id="a" * 64,
            build_id="tdaq-aaaaaaaaaaaaaaaa",
            timestamp_epoch=1_700_000_000,
            timestamp_utc="2023-11-14T22:13:20Z",
        )
        command = build_firmware.compile_command(
            Path("/tools/arduino-cli"),
            identity,
            "-D__IMXRT1062__ -DTEENSYDUINO=160",
            "-Wl,--gc-sections -T/imxrt1062.ld",
        )

        self.assertEqual("teensy:avr", build_firmware.CORE_ID)
        self.assertEqual("1.62.0", build_firmware.CORE_VERSION)
        self.assertEqual(3, build_firmware.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(
            "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
            build_firmware.FQBN,
        )
        self.assertEqual("/tools/arduino-cli", command[0])
        self.assertIn("--export-binaries", command)
        self.assertEqual(
            str(build_firmware.OUTPUT_DIRECTORY),
            command[command.index("--output-dir") + 1],
        )
        self.assertEqual("compile", command[1])
        self.assertNotIn("upload", command)
        self.assertIn("--clean", command)
        self.assertEqual("all", command[command.index("--warnings") + 1])
        build_properties = [
            command[index + 1]
            for index, value in enumerate(command)
            if value == "--build-property"
        ]
        definitions = next(
            value for value in build_properties if value.startswith("build.flags.defs=")
        )
        self.assertIn("-DTEENSY_DAQ_SOURCE_ID_WORD0=0x" + "a" * 16 + "ULL", definitions)
        self.assertIn("-DTEENSY_DAQ_SOURCE_ID_WORD3=0x" + "a" * 16 + "ULL", definitions)
        self.assertIn("-DTEENSY_DAQ_BUILD_EPOCH=1700000000ULL", definitions)
        self.assertIn("-DTEENSY_DAQ_BUILD_YEAR=2023U", definitions)
        self.assertIn("-DTEENSY_DAQ_BUILD_SECOND=20U", definitions)
        self.assertIn("-DTEENSY_DAQ_OPTIMIZATION_O2STD=1", definitions)
        linker_flags = next(
            value for value in build_properties if value.startswith("build.flags.ld=")
        )
        self.assertIn("-Wl,--gc-sections -T/imxrt1062.ld", linker_flags)
        self.assertIn(
            f"-Wl,-Map={build_firmware.OUTPUT_DIRECTORY / build_firmware.LINKER_MAP_NAME},--cref",
            linker_flags,
        )

    def test_memory_summary_is_recorded_exactly(self) -> None:
        summary = build_firmware.parse_memory_usage(
            """Memory Usage on Teensy 4.0:
  FLASH: code:22368, data:4040, headers:8404   free for files:1996804
   RAM1: variables:10080, code:20648, padding:12120   free for local variables:481440
   RAM2: variables:12416  free for malloc/new:511872
"""
        )

        self.assertEqual(22_368, summary["flash"]["code_bytes"])
        self.assertEqual(4_040, summary["flash"]["data_bytes"])
        self.assertEqual(10_080, summary["ram1"]["variables_bytes"])
        self.assertEqual(12_416, summary["ram2"]["variables_bytes"])
        with self.assertRaisesRegex(build_firmware.BuildError, "missing ram2"):
            build_firmware.parse_memory_usage(
                "FLASH: code:1, data:2, headers:3 free for files:4\nRAM1: variables:5, code:6, padding:7 free for local variables:8"
            )

    def test_core_mismatch_stops_before_compile_or_upload(self) -> None:
        responses = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="arduino-cli Version: 1.4.1\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    '{"platforms": [{"id": "teensy:avr", '
                    '"installed_version": "1.61.0"}]}\n'
                ),
                stderr="",
            ),
        ]

        with (
            patch.object(
                build_firmware.shutil,
                "which",
                return_value="/tools/arduino-cli",
            ),
            patch.object(
                build_firmware,
                "run_command",
                side_effect=responses,
            ) as run_command,
            self.assertRaisesRegex(
                build_firmware.BuildError,
                "requires teensy:avr 1.62.0",
            ),
        ):
            build_firmware.build("arduino-cli")

        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(2, len(commands))
        self.assertFalse(any("compile" in command for command in commands))
        self.assertFalse(any("upload" in command for command in commands))

    def test_core_inventory_must_report_the_pinned_version(self) -> None:
        inventory = {
            "platforms": [
                {"id": "arduino:avr", "installed_version": "1.8.6"},
                {"id": "teensy:avr", "installed_version": "1.62.0"},
            ]
        }

        self.assertEqual(
            "1.62.0",
            build_firmware.installed_core_version(inventory, "teensy:avr"),
        )
        self.assertIsNone(
            build_firmware.installed_core_version(inventory, "missing:core")
        )

    def test_source_fingerprint_is_path_aware_and_timestamp_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="teensy-daq-source-") as directory:
            root = Path(directory)
            first = root / "first.h"
            second = root / "second.h"
            first.write_bytes(b"same bytes\n")
            second.write_bytes(b"same bytes\n")

            first_hash = build_firmware.source_fingerprint([first], root=root)
            repeated_hash = build_firmware.source_fingerprint([first], root=root)
            second_hash = build_firmware.source_fingerprint([second], root=root)

        self.assertEqual(first_hash, repeated_hash)
        self.assertNotEqual(first_hash, second_hash)

    def test_source_date_epoch_is_validated_and_formatted_in_utc(self) -> None:
        epoch = build_firmware.resolve_build_epoch({"SOURCE_DATE_EPOCH": "0"})
        self.assertEqual(0, epoch)
        with self.assertRaisesRegex(build_firmware.BuildError, "decimal integer"):
            build_firmware.resolve_build_epoch({"SOURCE_DATE_EPOCH": "tomorrow"})

    def test_resolved_target_properties_fail_closed(self) -> None:
        properties = {
            **build_firmware.EXPECTED_BUILD_PROPERTIES,
            "build.flags.defs": "-D__IMXRT1062__ -DTEENSYDUINO=160",
            "build.flags.cpp": "-std=gnu++17 -fno-exceptions",
        }
        build_firmware.validate_build_properties(properties)

        properties["build.fcpu"] = "528000000"
        with self.assertRaisesRegex(build_firmware.BuildError, "build.fcpu"):
            build_firmware.validate_build_properties(properties)

    def test_sketch_boot_is_independent_of_host_open_and_has_no_banner(self) -> None:
        sketch = (REPOSITORY_ROOT / "firmware/firmware.ino").read_text(encoding="utf-8")
        usb_adapter = (REPOSITORY_ROOT / "firmware/src/teensy_usb.cpp").read_text(
            encoding="utf-8"
        )
        usb_header = (REPOSITORY_ROOT / "firmware/src/teensy_usb.h").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("kBuildId[] =", sketch)
        self.assertIn('include "src/firmware_runtime.h"', sketch)
        self.assertIn('include "src/teensy_usb.h"', sketch)
        self.assertIn("firmware_runtime.begin", sketch)
        self.assertIn("hardwareSerialNumber()", sketch)
        self.assertIn("firmware_runtime.service()", sketch)
        self.assertNotIn("while (!Serial", sketch)
        self.assertNotIn("Serial.begin(115200)", sketch)
        self.assertNotIn("Serial.print", sketch)
        self.assertIn('include "firmware_identity.h"', usb_header)
        self.assertIn("usb_string_product_name =", usb_adapter)
        self.assertNotIn("usb_string_serial_number =", usb_adapter)


if __name__ == "__main__":
    unittest.main()
