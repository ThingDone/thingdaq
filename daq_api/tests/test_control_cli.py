"""Focused Phase 03 control-profile, synchronization, and CLI tests."""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from teensy_daq import (
    Capability,
    DAQConfiguration,
    DAQStateError,
    DeviceCapabilityError,
    DeviceDisconnectedError,
    DeviceIdentityMismatchError,
    DeviceState,
    ExpectedDeviceIdentity,
    FrameKind,
    InMemoryTransport,
    SerialPortBusyError,
    SerialPortCandidate,
    SimulatedDevice,
    Source,
    Status,
    StreamMask,
    TeensyDAQ,
    TransportTimeoutError,
    decode_frame,
)
from teensy_daq.cli import CliExitCode, _execute, main


class ResetNoiseTransport(InMemoryTransport):
    """Drop the first INFO reply after emitting unframed CDC startup noise."""

    def __init__(self) -> None:
        super().__init__(SimulatedDevice(control_only=True))
        self.info_writes = 0

    def write(self, data: bytes | bytearray | memoryview) -> int:
        wire = bytes(data)
        request = decode_frame(wire)
        if request.header.kind is FrameKind.INFO_REQUEST:
            self.info_writes += 1
            if self.info_writes == 1:
                with self._lock:
                    self._require_open()
                    self._pending.extend(b"boot noise\r\n\xef\xbe")
                return len(wire)
        return super().write(wire)


class ChangingIdentityDevice(SimulatedDevice):
    """Return a different build ID on each INFO synchronization probe."""

    def __init__(self) -> None:
        super().__init__(control_only=True)
        self.info_count = 0

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        self.info_count += 1
        self._build_id = f"control-simulator-{self.info_count}"
        return super()._handle_info(request)


class Phase03ControlProfileTests(unittest.TestCase):
    def test_zero_stream_models_round_trip_only_for_hardware_control(self) -> None:
        configuration = DAQConfiguration.control_only()

        self.assertTrue(configuration.is_control_only)
        self.assertEqual(StreamMask.NONE, configuration.stream_mask)
        self.assertEqual(
            configuration,
            DAQConfiguration.from_payload(configuration.to_payload()),
        )
        with self.assertRaisesRegex(ValueError, "requires the hardware source"):
            DAQConfiguration(StreamMask.NONE, Source.SYNTHETIC)

        status = Status(
            DeviceState.RUNNING,
            StreamMask.NONE,
            Source.HARDWARE,
            configuration.data_checksum_algorithm,
        )
        self.assertEqual(status, Status.from_payload(status.to_payload()))
        with self.assertRaisesRegex(ValueError, "requires hardware source"):
            Status(
                DeviceState.CONFIGURED,
                StreamMask.NONE,
                Source.SYNTHETIC,
                configuration.data_checksum_algorithm,
            )

    def test_control_only_simulator_has_full_api_parity(self) -> None:
        with TeensyDAQ.simulated(control_only=True) as daq:
            info = daq.device_info
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(StreamMask.NONE, info.supported_stream_mask)
            self.assertEqual((0, 3, 0), info.firmware_version)
            self.assertTrue(info.supports_capability(Capability.HARDWARE_SOURCE))
            self.assertTrue(info.supports_capability(Capability.RESET_STATS))

            applied = daq.configure_control_only()
            run_id = daq.start()
            running = daq.status()
            self.assertTrue(applied.is_control_only)
            self.assertGreater(run_id, 0)
            self.assertEqual(DeviceState.RUNNING, running.device_state)
            self.assertEqual(StreamMask.NONE, running.stream_mask)
            self.assertEqual(Source.HARDWARE, running.source)
            self.assertEqual(DeviceState.IDLE, daq.stop())
            generation = daq.reset_stats()
            self.assertEqual(generation, daq.status().stats_generation)

    def test_nonstopping_close_preserves_one_shot_cli_state(self) -> None:
        device = SimulatedDevice(control_only=True)

        configured = TeensyDAQ.open(InMemoryTransport(device))
        configured.configure_control_only()
        configured.close(stop=False)
        self.assertEqual(DeviceState.CONFIGURED, device.state)

        running = TeensyDAQ.open(InMemoryTransport(device))
        run_id = running.start()
        running.close(stop=False)
        self.assertGreater(run_id, 0)
        self.assertEqual(DeviceState.RUNNING, device.state)

        stopped = TeensyDAQ.open(InMemoryTransport(device))
        stopped.stop()
        stopped.close(stop=False)
        self.assertEqual(DeviceState.IDLE, device.state)


class SynchronizationAndIdentityTests(unittest.TestCase):
    def test_open_retries_reset_noise_then_discards_one_valid_probe(self) -> None:
        transport = ResetNoiseTransport()

        with TeensyDAQ.open(
            transport,
            command_timeout=0.02,
            synchronization_attempts=3,
            synchronization_retry_delay=0,
        ) as daq:
            self.assertIsNotNone(daq.verified_identity)
            self.assertEqual(3, transport.info_writes)
            self.assertEqual(1, daq.reader_counters.request_timeouts)
            self.assertEqual(1, daq.parser_counters.resynchronizations)
            self.assertGreater(daq.parser_counters.bytes_discarded, 0)
            self.assertTrue(daq.configure_control_only().is_control_only)

    def test_changing_or_explicitly_wrong_identity_fails_before_mutation(self) -> None:
        changing = ChangingIdentityDevice()
        with self.assertRaisesRegex(
            DeviceIdentityMismatchError, "changed between synchronization"
        ):
            TeensyDAQ.open(InMemoryTransport(changing))
        self.assertEqual(DeviceState.IDLE, changing.state)

        with self.assertRaisesRegex(DeviceIdentityMismatchError, "build ID"):
            TeensyDAQ.simulated(
                control_only=True,
                expected_identity=ExpectedDeviceIdentity(build_id="wrong-build"),
            )


class ControlCliTests(unittest.TestCase):
    def test_list_probe_status_and_configure_have_machine_readable_output(self) -> None:
        candidate = SerialPortCandidate(
            port="COM9",
            vid=0x16C0,
            pid=0x0483,
            serial_number="12345670",
            product="Teensy DAQ",
            location="1-2.3",
        )
        list_output = io.StringIO()
        with patch("teensy_daq.cli.enumerate_candidates", return_value=(candidate,)):
            result = _execute(
                argparse.Namespace(action="list"),
                list_output,
            )
        self.assertEqual(CliExitCode.OK, result)
        self.assertIn("candidate_count=1", list_output.getvalue())
        self.assertIn("port=COM9", list_output.getvalue())
        self.assertIn("usb_serial=12345670", list_output.getvalue())

        for command, expected_text in (
            ("probe", "build_id=teensy-daq-simulator-v1"),
            ("status", "stats_generation=1"),
            ("configure", "profile=control-only"),
            ("reset-stats", "stats_generation=2"),
        ):
            with self.subTest(command=command):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = main([command, "--simulate"])
                self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
                self.assertIn(expected_text, stdout.getvalue())

    def test_cli_diagnostics_are_typed_and_have_stable_exit_codes(self) -> None:
        allowed = frozenset({DeviceState.CONFIGURED})
        cases = (
            (
                TransportTimeoutError("timed out"),
                CliExitCode.TIMEOUT,
                "[timeout]",
            ),
            (
                SerialPortBusyError("locked"),
                CliExitCode.BUSY_PORT,
                "[busy-port]",
            ),
            (
                DeviceIdentityMismatchError("wrong build"),
                CliExitCode.WRONG_DEVICE,
                "[wrong-device]",
            ),
            (
                DeviceCapabilityError("RESET_STATS unavailable"),
                CliExitCode.UNSUPPORTED_CAPABILITY,
                "[unsupported-capability]",
            ),
            (
                DeviceDisconnectedError("vanished"),
                CliExitCode.DISCONNECTED,
                "[disconnected]",
            ),
            (
                DAQStateError("start", DeviceState.IDLE, allowed),
                CliExitCode.INVALID_STATE,
                "[invalid-state]",
            ),
        )
        for error, expected_code, expected_category in cases:
            with self.subTest(error=type(error).__name__):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch("teensy_daq.cli._execute", side_effect=error),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = main(["list"])
                self.assertEqual(expected_code, exit_code)
                self.assertEqual("", stdout.getvalue())
                self.assertIn(expected_category, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
