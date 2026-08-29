"""Public export and bounded CLI lifecycle coverage for Phase 10."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch

import teensy_daq
from teensy_daq import (
    CalibrationRecord,
    ConverterCalibration,
    DeviceState,
    InMemoryTransport,
    SerialPortCandidate,
    SimulatedDevice,
    TeensyDAQ,
    low_level,
    save_calibration,
)
from teensy_daq.cli import CaptureInterruptedError, CliExitCode, build_parser, main


def _calibration_record() -> CalibrationRecord:
    return CalibrationRecord(
        hardware_serial=12_345_670,
        analog_front_end_profile="buffer-a",
        adc_resolution_bits=12,
        adc_code_range=(0, 4095),
        adc_input_range_volts=(0.0, 3.3),
        adc0=ConverterCalibration(offset=-0.1, gain=0.001),
        adc1=ConverterCalibration(offset=0.2, gain=0.002),
        provenance="Phase 10 CLI fixture",
        created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )


class PublicNamespaceTests(unittest.TestCase):
    def test_root_exports_are_explicit_and_low_level_access_is_named(self) -> None:
        self.assertIn("__version__", teensy_daq.__all__)
        self.assertIn("low_level", teensy_daq.__all__)
        self.assertIs(teensy_daq.Frame, low_level.Frame)
        self.assertIs(teensy_daq.BackgroundReader, low_level.BackgroundReader)
        self.assertIs(teensy_daq.SerialTransport, low_level.SerialTransport)
        self.assertIs(
            teensy_daq.FrameKind,
            low_level.protocol_constants.FrameKind,
        )

    def test_facade_context_manager_is_typed_and_closes_deterministically(self) -> None:
        hints = get_type_hints(TeensyDAQ.__enter__)
        self.assertIs(TeensyDAQ, hints["return"])

        daq = TeensyDAQ.simulated()
        with daq as entered:
            self.assertIs(daq, entered)
            self.assertTrue(daq.is_open)
        self.assertFalse(daq.is_open)


class JsonCliLifecycleTests(unittest.TestCase):
    def test_metadata_list_json_never_opens_a_candidate(self) -> None:
        candidate = SerialPortCandidate(
            port="COM9",
            vid=0x16C0,
            pid=0x0483,
            serial_number="12345670",
            product="Teensy DAQ",
        )
        stdout = io.StringIO()
        with (
            patch("teensy_daq.cli.enumerate_candidates", return_value=(candidate,)),
            patch("teensy_daq.cli._open_device") as open_device,
            redirect_stdout(stdout),
        ):
            exit_code = main(["list", "--json"])

        self.assertEqual(CliExitCode.OK, exit_code)
        open_device.assert_not_called()
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["metadata_only"])
        self.assertEqual("COM9", payload["candidates"][0]["port"])

    def test_info_and_status_have_single_document_json_output(self) -> None:
        for command, container in (("info", "info"), ("status", "status")):
            with self.subTest(command=command):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = main([command, "--simulate", "--json"])
                self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
                payload = json.loads(stdout.getvalue())
                self.assertIn(container, payload)
                self.assertEqual("IDLE", payload[container]["device_state"])

    def test_json_capture_exposes_raw_selected_gpio_and_both_loss_domains(
        self,
    ) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "capture",
                    "--simulate",
                    "--duration",
                    "0.02",
                    "--status-interval",
                    "0.01",
                    "--block-timeout",
                    "0.002",
                    "--sample-limit",
                    "2",
                    "--gpio-channel",
                    "D6",
                    "--gpio-channel",
                    "13",
                    "--strict-loss",
                    "--json",
                ]
            )

        self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual("IDLE", payload["final_state"])
        self.assertEqual(["D6", "D13"], payload["gpio_channels"])
        adc = next(row for row in payload["sample_preview"] if row["stream"] == "adc")
        gpio = next(row for row in payload["sample_preview"] if row["stream"] == "gpio")
        self.assertFalse(adc["calibrated"])
        self.assertIn("raw_code", adc["adc0"])
        self.assertEqual({"D6", "D13"}, set(gpio["channels"]))
        self.assertEqual(
            0,
            payload["loss_counters"]["firmware"]["adc_items_dropped"],
        )
        self.assertEqual(
            0,
            payload["loss_counters"]["host"]["host_block_queue_drops"],
        )

    def test_calibrated_json_capture_retains_raw_codes_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calibration_path = Path(directory) / "calibration.json"
            save_calibration(calibration_path, _calibration_record())
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "capture",
                        "--simulate",
                        "--streams",
                        "adc",
                        "--duration",
                        "0.01",
                        "--status-interval",
                        "0.005",
                        "--block-timeout",
                        "0.001",
                        "--sample-limit",
                        "1",
                        "--adc-output",
                        "calibrated",
                        "--calibration",
                        str(calibration_path),
                        "--calibration-hardware-serial",
                        "12345670",
                        "--analog-front-end-profile",
                        "buffer-a",
                        "--json",
                    ]
                )

        self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        sample = payload["sample_preview"][0]
        self.assertTrue(sample["calibrated"])
        self.assertEqual(0, sample["adc0"]["raw_code"])
        self.assertAlmostEqual(-0.1, sample["adc0"]["voltage"])
        self.assertEqual("Phase 10 CLI fixture", payload["calibration"]["provenance"])

    def test_interrupt_error_stops_and_closes_before_json_diagnostic(self) -> None:
        device = SimulatedDevice()
        daq = TeensyDAQ.open(InMemoryTransport(device))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("teensy_daq.cli._open_device", return_value=daq),
            patch.object(
                daq,
                "read_block",
                side_effect=CaptureInterruptedError("SIGTERM"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = main(
                [
                    "capture",
                    "--simulate",
                    "--duration",
                    "1",
                    "--status-interval",
                    "0.2",
                    "--block-timeout",
                    "0.01",
                    "--json",
                ]
            )

        self.assertEqual(CliExitCode.INTERRUPTED, exit_code)
        self.assertEqual("", stdout.getvalue())
        diagnostic = json.loads(stderr.getvalue())
        self.assertEqual("interrupted", diagnostic["error"]["category"])
        self.assertEqual(DeviceState.IDLE, device.state)
        self.assertFalse(daq.is_open)


class HumanCliLifecycleTests(unittest.TestCase):
    def test_human_capture_marks_raw_data_and_prints_loss_counters(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "monitor",
                    "--simulate",
                    "--duration",
                    "0.01",
                    "--status-interval",
                    "0.005",
                    "--block-timeout",
                    "0.001",
                    "--sample-limit",
                    "1",
                    "--gpio-channel",
                    "D6",
                ]
            )

        rendered = stdout.getvalue()
        self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
        self.assertIn("adc0_raw=0", rendered)
        self.assertIn("calibrated=false", rendered)
        self.assertIn("D6=", rendered)
        self.assertIn("firmware_adc_frames_dropped=0", rendered)
        self.assertIn("host_block_queue_drops=0", rendered)

    def test_parser_rejects_unknown_gpio_channels_actionably(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["capture", "--simulate", "--gpio-channel", "D5"])


if __name__ == "__main__":
    unittest.main()
