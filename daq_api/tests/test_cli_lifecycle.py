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

import thingdaq
from thingdaq import (
    CalibrationRecord,
    ConverterCalibration,
    DeviceState,
    InMemoryTransport,
    SerialPortCandidate,
    SimulatedDevice,
    ThingDAQ,
    low_level,
    save_calibration,
)
from thingdaq.cli import CaptureInterruptedError, CliExitCode, build_parser, main


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
        self.assertIn("__version__", thingdaq.__all__)
        self.assertIn("low_level", thingdaq.__all__)
        self.assertIs(thingdaq.Frame, low_level.Frame)
        self.assertIs(thingdaq.BackgroundReader, low_level.BackgroundReader)
        self.assertIs(thingdaq.SerialTransport, low_level.SerialTransport)
        self.assertIs(
            thingdaq.FrameKind,
            low_level.protocol_constants.FrameKind,
        )

    def test_facade_context_manager_is_typed_and_closes_deterministically(self) -> None:
        hints = get_type_hints(ThingDAQ.__enter__)
        self.assertIs(ThingDAQ, hints["return"])

        daq = ThingDAQ.simulated()
        with daq as entered:
            self.assertIs(daq, entered)
            self.assertTrue(daq.is_open)
        self.assertFalse(daq.is_open)

    def test_phase10_exports_and_return_annotations_are_stable(self) -> None:
        required_exports = {
            "__version__",
            "ThingDAQ",
            "DeviceCapabilities",
            "DAQConfiguration",
            "ADCBlock",
            "GPIOBlock",
            "CalibrationRecord",
            "CalibrationDatabase",
            "CalibrationStore",
            "ConverterCalibration",
            "CalibratedAdcChannels",
            "CalibratedAdcSample",
            "calibrated_channels",
            "calibrated_interleaved",
            "estimate_offset_gain",
            "save_calibration",
            "load_calibration",
            "DeviceCapabilityError",
            "DAQClosedError",
            "DAQShutdownError",
            "DAQStateError",
            "UnexpectedMessageError",
            "low_level",
        }
        exported = thingdaq.__all__

        self.assertEqual(len(exported), len(set(exported)))
        self.assertTrue(required_exports.issubset(exported))
        for name in required_exports:
            with self.subTest(name=name):
                self.assertTrue(hasattr(thingdaq, name))

        method_returns = {
            ThingDAQ.__enter__: ThingDAQ,
            ThingDAQ.open: ThingDAQ,
            ThingDAQ.simulated: ThingDAQ,
            ThingDAQ.info: thingdaq.DeviceInfo,
            ThingDAQ.configure: thingdaq.DAQConfiguration,
            ThingDAQ.start: int,
            ThingDAQ.status: thingdaq.Status,
            ThingDAQ.stop: DeviceState,
        }
        for method, expected in method_returns.items():
            with self.subTest(method=method.__name__):
                self.assertIs(expected, get_type_hints(method)["return"])
        self.assertIs(
            thingdaq.ConverterCalibration,
            get_type_hints(thingdaq.estimate_offset_gain)["return"],
        )
        self.assertIs(
            thingdaq.CalibratedAdcChannels,
            get_type_hints(
                thingdaq.calibrated_channels,
                localns={"ADCBlock": thingdaq.ADCBlock},
            )["return"],
        )

    def test_documented_exception_hierarchy_is_stable(self) -> None:
        facade_errors = (
            thingdaq.DAQClosedError,
            thingdaq.CommandTimeoutError,
            thingdaq.DAQShutdownError,
            thingdaq.BlockTimeoutError,
            thingdaq.DeviceCommandError,
            thingdaq.MultipleDevicesFoundError,
            thingdaq.DeviceIdentityMismatchError,
            thingdaq.DeviceSynchronizationError,
            thingdaq.UnexpectedMessageError,
            thingdaq.UnexpectedStreamGapError,
            thingdaq.UnexpectedHostQueueLossError,
            thingdaq.UnexpectedStreamAnomalyError,
        )
        for error_type in facade_errors:
            with self.subTest(error=error_type.__name__):
                self.assertTrue(issubclass(error_type, thingdaq.ThingDAQError))

        self.assertTrue(issubclass(thingdaq.DAQStateError, thingdaq.DeviceCommandError))
        self.assertTrue(
            issubclass(
                thingdaq.DeviceCapabilityError,
                thingdaq.DeviceCommandError,
            )
        )
        self.assertTrue(
            issubclass(
                thingdaq.UnexpectedStreamValidationError,
                thingdaq.UnexpectedMessageError,
            )
        )
        self.assertTrue(
            issubclass(thingdaq.DeviceNotFoundError, thingdaq.DiscoveryError)
        )
        self.assertTrue(
            issubclass(
                thingdaq.CalibrationFormatError,
                thingdaq.CalibrationError,
            )
        )
        self.assertTrue(
            issubclass(
                thingdaq.CalibrationMismatchError,
                thingdaq.CalibrationError,
            )
        )


class JsonCliLifecycleTests(unittest.TestCase):
    def test_configure_reports_exact_echo_and_fixed_capability_requirements(
        self,
    ) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "configure",
                    "--simulate",
                    "--streams",
                    "both",
                    "--source",
                    "synthetic",
                    "--checksum",
                    "crc32c",
                    "--adc-pair-rate-hz",
                    "1000000",
                    "--gpio-sample-rate-hz",
                    "4000000",
                    "--adc-resolution-bits",
                    "12",
                    "--json",
                ]
            )

        self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
        applied = json.loads(stdout.getvalue())["applied_configuration"]
        self.assertEqual("SYNTHETIC_COMBINED", applied["profile"])
        self.assertEqual("CRC32C", applied["data_checksum_algorithm"])
        self.assertEqual(4096, applied["data_frame_bytes"])
        self.assertEqual(1_000_000, applied["adc_pair_rate_hz"])
        self.assertEqual(4_000_000, applied["gpio_sample_rate_hz"])
        self.assertEqual(12, applied["adc_resolution_bits"])

    def test_configure_rejects_wrong_resolution_as_unsupported_capability(
        self,
    ) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "configure",
                    "--simulate",
                    "--streams",
                    "adc",
                    "--source",
                    "synthetic",
                    "--adc-resolution-bits",
                    "10",
                    "--json",
                ]
            )

        self.assertEqual(CliExitCode.UNSUPPORTED_CAPABILITY, exit_code)
        self.assertEqual("", stdout.getvalue())
        error = json.loads(stderr.getvalue())["error"]
        self.assertEqual("unsupported-capability", error["category"])
        self.assertIn("advertises exactly 12 bits", error["message"])

    def test_metadata_list_json_never_opens_a_candidate(self) -> None:
        candidate = SerialPortCandidate(
            port="COM9",
            vid=0x16C0,
            pid=0x0483,
            serial_number="12345670",
            product="ThingDAQ",
        )
        stdout = io.StringIO()
        with (
            patch("thingdaq.cli.enumerate_candidates", return_value=(candidate,)),
            patch("thingdaq.cli._open_device") as open_device,
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
        daq = ThingDAQ.open(InMemoryTransport(device))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("thingdaq.cli._open_device", return_value=daq),
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
