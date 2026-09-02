"""Clock-profile and bounded runtime-health model/client checks."""

from __future__ import annotations

import unittest
from dataclasses import replace

from thingdaq import (
    AdcTriggerMetadata,
    ChecksumAlgorithm,
    ClockHealthError,
    ClockHealthFlag,
    ClockHealthSample,
    ClockProfile,
    ClockProfileMetadata,
    DeviceInfo,
    DeviceState,
    IncrementalFrameParser,
    InMemoryTransport,
    Source,
    Status,
    StreamMask,
    TemperatureStatus,
    ThingDAQ,
    UnexpectedMessageError,
    encode_frame,
)
from thingdaq._generated import protocol_constants as constants
from thingdaq.simulator import SimulatedDevice


def _experimental_trigger() -> AdcTriggerMetadata:
    profile = constants.CLOCK_PROFILE_SPECS[ClockProfile.EXPERIMENTAL_528_MHZ]
    return replace(
        AdcTriggerMetadata(),
        dwt_clock_hz=profile.dwt_hz,
        ipg_clock_hz=profile.ipg_hz,
        initial_delays=(0, profile.phase_ipg_cycles),
        effective_delays=(1, profile.phase_ipg_cycles + 1),
        phase_ipg_cycles=profile.phase_ipg_cycles,
        completion_expected_delta_cycles=profile.phase_dwt_cycles,
        completion_tolerance_cycles=profile.phase_tolerance_dwt_cycles,
    )


class ContradictoryClockDevice(SimulatedDevice):
    """Advertise production clocks but report one explicit runtime mismatch."""

    def status(self) -> Status:
        status = super().status()
        health = replace(
            status.clock_health,
            flags=(status.clock_health.flags & ~ClockHealthFlag.CLOCKS_VALID),
            runtime_cpu_clock_hz=528_000_000,
            error_flags=(
                status.clock_health.error_flags | ClockHealthError.CPU_CLOCK_MISMATCH
            ),
            clock_mismatch_count=1,
        )
        return replace(status, clock_health=health)


class ContradictoryProfileDevice(SimulatedDevice):
    """Advertise 600 MHz in INFO but return a valid 528 MHz STATUS."""

    def status(self) -> Status:
        status = super().status()
        profile = ClockProfileMetadata.for_profile(ClockProfile.EXPERIMENTAL_528_MHZ)
        health = ClockHealthSample(
            clock_profile=profile,
            flags=(ClockHealthFlag.CLOCKS_VALID | ClockHealthFlag.UTILIZATION_VALID),
            runtime_cpu_clock_hz=profile.cpu_clock_hz,
            runtime_ipg_clock_hz=profile.ipg_clock_hz,
            runtime_adc_clock_hz=profile.adc_clock_hz,
            runtime_pit_clock_hz=profile.pit_clock_hz,
            runtime_dwt_clock_hz=profile.dwt_clock_hz,
            acquisition_service_utilization_basis_points=0,
            usb_service_utilization_basis_points=0,
            error_flags=ClockHealthError.TEMPERATURE_UNAVAILABLE,
        )
        return replace(
            status,
            clock_health=health,
            adc_ipg_clock_hz=profile.ipg_clock_hz,
            adc_clock_hz=profile.adc_clock_hz,
            adc_trigger=_experimental_trigger(),
        )


class ClockProfileModelTests(unittest.TestCase):
    def test_info_round_trips_the_experimental_generated_profile(self) -> None:
        profile = ClockProfileMetadata.for_profile(ClockProfile.EXPERIMENTAL_528_MHZ)
        info = DeviceInfo(
            device_state=DeviceState.IDLE,
            build_id="clock-528-test",
            clock_profile=profile,
            adc_ipg_clock_hz=profile.ipg_clock_hz,
            adc_clock_hz=profile.adc_clock_hz,
            adc_trigger=_experimental_trigger(),
        )

        wire = encode_frame(
            constants.FrameKind.INFO_RESPONSE,
            info.to_payload(),
            request_id=1,
        )
        frames = IncrementalFrameParser().feed(wire)

        self.assertEqual(1, len(frames))
        self.assertEqual(info, DeviceInfo.from_payload(frames[0].payload))
        self.assertEqual(528_000_000, info.clock_profile.cpu_clock_hz)
        self.assertEqual(33_000_000, info.adc_clock_hz)

    def test_advertised_profile_rejects_contradictory_generated_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "advertised clocks contradict"):
            ClockProfileMetadata(
                profile=ClockProfile.EXPERIMENTAL_528_MHZ,
                cpu_clock_hz=600_000_000,
            )

    def test_health_round_trip_preserves_finite_sensor_and_load_values(self) -> None:
        health = ClockHealthSample(
            sample_sequence=7,
            sample_ticks=80_000,
            temperature_status=TemperatureStatus.VALID,
            flags=(
                ClockHealthFlag.CLOCKS_VALID
                | ClockHealthFlag.TEMPERATURE_VALID
                | ClockHealthFlag.UTILIZATION_VALID
            ),
            temperature_millidegrees_celsius=42_125,
            acquisition_service_utilization_basis_points=1_250,
            usb_service_utilization_basis_points=625,
            error_flags=ClockHealthError.NONE,
        )
        status = Status(
            DeviceState.IDLE,
            StreamMask.NONE,
            Source.HARDWARE,
            ChecksumAlgorithm.ADLER32,
            clock_health=health,
        )

        decoded = Status.from_payload(status.to_payload())
        self.assertEqual(health, decoded.clock_health)
        self.assertEqual(42.125, decoded.clock_health.temperature_celsius)
        self.assertEqual(0.125, decoded.clock_health.acquisition_service_utilization)

    def test_sensor_and_load_unavailability_are_explicit(self) -> None:
        health = ClockHealthSample()

        self.assertIsNone(health.temperature_celsius)
        self.assertIsNone(health.usb_service_utilization)
        self.assertTrue(health.error_flags & ClockHealthError.TEMPERATURE_UNAVAILABLE)
        self.assertTrue(health.error_flags & ClockHealthError.UTILIZATION_UNAVAILABLE)
        with self.assertRaisesRegex(ValueError, "finite bounded integer"):
            replace(
                health,
                temperature_status=TemperatureStatus.VALID,
                flags=health.flags | ClockHealthFlag.TEMPERATURE_VALID,
                temperature_millidegrees_celsius=200_000,
                error_flags=(
                    health.error_flags & ~ClockHealthError.TEMPERATURE_UNAVAILABLE
                ),
            )


class ClockHealthClientTests(unittest.TestCase):
    def test_client_rejects_status_profile_that_contradicts_info(self) -> None:
        transport = InMemoryTransport(ContradictoryProfileDevice())
        with ThingDAQ(transport) as daq:
            daq.synchronize()
            with self.assertRaisesRegex(
                UnexpectedMessageError, "profile contradicts synchronized INFO"
            ):
                daq.status()

    def test_client_rejects_runtime_clocks_that_contradict_info(self) -> None:
        transport = InMemoryTransport(ContradictoryClockDevice())
        with ThingDAQ(transport) as daq:
            daq.synchronize()
            with self.assertRaisesRegex(
                UnexpectedMessageError, "runtime clocks that contradict"
            ):
                daq.status()


if __name__ == "__main__":
    unittest.main()
