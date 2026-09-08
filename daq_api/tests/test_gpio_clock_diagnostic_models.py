"""Typed host coverage for the isolated GPIO clock/DMA diagnostic."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from thingdone_daq import (
    Capability,
    DeviceCapabilityError,
    ErrorCode,
    FrameKind,
    FrameValidationError,
    GpioClockDiagnosticRequest,
    GpioClockDiagnosticResult,
    GpioClockError,
    SimulatedDevice,
    ThingDAQ,
    decode_frame,
    decode_response,
    encode_frame,
)
from thingdone_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"


class GpioClockDiagnosticModelTests(unittest.TestCase):
    def test_request_matches_golden_vector_and_derives_exact_plan(self) -> None:
        request = GpioClockDiagnosticRequest(rate_hz=1_000_000, event_count=4096)
        fixture = decode_frame(
            (FIXTURE_DIRECTORY / "gpio-clock-diagnostic-request.bin").read_bytes()
        )

        self.assertEqual(
            request, GpioClockDiagnosticRequest.from_payload(fixture.payload)
        )
        self.assertEqual(fixture.payload, request.to_payload())
        self.assertEqual(23, request.pit_load_value)
        self.assertEqual(2_457_600, request.expected_elapsed_cycles)
        self.assertEqual(8_208, request.tcd_major_count)

    def test_golden_response_exposes_route_registers_counts_and_rate(self) -> None:
        frame = decode_frame(
            (FIXTURE_DIRECTORY / "gpio-clock-diagnostic-response.bin").read_bytes()
        )
        response = decode_response(frame)

        self.assertTrue(response.ok)
        self.assertIsInstance(response.value, GpioClockDiagnosticResult)
        assert isinstance(response.value, GpioClockDiagnosticResult)
        result = response.value
        self.assertTrue(result.healthy)
        self.assertEqual(GpioClockError.NONE, result.hardware_error_flags)
        self.assertEqual(1_000_000.0, result.measured_rate_hz)
        self.assertEqual(0, result.count_error)
        self.assertEqual(
            (0, 56, 0, 2, 30, 0),
            (
                result.pit_channel,
                result.xbar_input,
                result.xbar_output,
                result.edma_channel,
                result.dmamux_source,
                result.edma_priority,
            ),
        )
        self.assertEqual(4, result.tcd_nbytes)
        self.assertEqual(0, result.tcd_soff)
        self.assertEqual(1 << 2, result.dma_erq_configured)

    def test_request_rejects_approximate_or_unbounded_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "selection is invalid"):
            GpioClockDiagnosticRequest(rate_hz=3_999_999, event_count=32)
        with self.assertRaisesRegex(ValueError, "duration bound"):
            GpioClockDiagnosticRequest(
                rate_hz=constants.GPIO_CLOCK_MIN_RATE_HZ,
                event_count=constants.GPIO_CLOCK_MAX_EVENT_COUNT,
            )
        with self.assertRaisesRegex(ValueError, "selection is invalid"):
            GpioClockDiagnosticRequest(rate_hz=4_000_000, event_count=31)

    def test_wire_validator_rejects_count_or_unknown_flag_corruption(self) -> None:
        frame = decode_frame(
            (FIXTURE_DIRECTORY / "gpio-clock-diagnostic-response.bin").read_bytes()
        )
        payload = bytearray(frame.payload)
        struct.pack_into(
            "<I",
            payload,
            constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_SCHEDULED_EVENT_COUNT_OFFSET,
            4095,
        )
        with self.assertRaisesRegex(FrameValidationError, "evidence is inconsistent"):
            encode_frame(
                FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
                payload,
                request_id=frame.header.request_id,
            )

        payload = bytearray(frame.payload)
        struct.pack_into(
            "<I",
            payload,
            constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_SAMPLE_COUNT_OFFSET,
            4094,
        )
        struct.pack_into(
            "<H",
            payload,
            constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_CITER_FINAL_OFFSET,
            4114,
        )
        with self.assertRaisesRegex(FrameValidationError, "evidence is inconsistent"):
            encode_frame(
                FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
                payload,
                request_id=frame.header.request_id,
            )

        payload = bytearray(frame.payload)
        struct.pack_into(
            "<I",
            payload,
            constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_HARDWARE_ERROR_FLAGS_OFFSET,
            1 << 31,
        )
        with self.assertRaisesRegex(FrameValidationError, "evidence is inconsistent"):
            encode_frame(
                FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
                payload,
                request_id=frame.header.request_id,
            )

    def test_simulator_rejects_target_only_command_without_state_change(self) -> None:
        device = SimulatedDevice()
        before = device.status()
        request = GpioClockDiagnosticRequest(rate_hz=4_000_000, event_count=64)
        response = decode_response(
            decode_frame(
                device.receive(
                    encode_frame(
                        FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST,
                        request.to_payload(),
                        request_id=55,
                    )
                )[0]
            )
        )

        self.assertFalse(response.ok)
        self.assertEqual(ErrorCode.UNSUPPORTED_CONFIGURATION, response.error_code)
        self.assertEqual(before, device.status())

        with ThingDAQ.simulated() as daq:
            info = daq.info()
            self.assertFalse(info.supports_capability(Capability.GPIO_CLOCK_DIAGNOSTIC))
            with self.assertRaises(DeviceCapabilityError):
                daq.gpio_clock_diagnostic(event_count=64)


if __name__ == "__main__":
    unittest.main()
