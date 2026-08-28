"""Tests for the pinned firmware build boundary and boot skeleton."""

from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_HELPER_PATH = REPOSITORY_ROOT / "firmware/tools/build_firmware.py"
SPEC = importlib.util.spec_from_file_location("build_firmware", BUILD_HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
build_firmware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_firmware)


class BuildConfigurationTests(unittest.TestCase):
    def test_helper_pins_the_complete_target_and_export_directory(self) -> None:
        command = build_firmware.compile_command(Path("/tools/arduino-cli"))

        self.assertEqual("teensy:avr", build_firmware.CORE_ID)
        self.assertEqual("1.62.0", build_firmware.CORE_VERSION)
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

    def test_foundation_sketch_has_a_bounded_idle_boot(self) -> None:
        sketch = (REPOSITORY_ROOT / "firmware/firmware.ino").read_text(encoding="utf-8")

        self.assertIn('kBuildId[] = "teensy-daq-foundation-0.0.0"', sketch)
        self.assertIn("DeviceState::kIdle", sketch)
        self.assertIn("while (!Serial &&", sketch)
        self.assertIn("kSerialWaitMilliseconds", sketch)
        self.assertIn("acquisition=unsupported", sketch)
        self.assertNotIn("while (!Serial) {", sketch)
        self.assertIn("src/generated/protocol_constants.h", sketch)


if __name__ == "__main__":
    unittest.main()
