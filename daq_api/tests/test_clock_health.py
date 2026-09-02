"""Clock-profile and bounded runtime-health model/client checks."""

from __future__ import annotations

import struct
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
    FrameValidationError,
    IncrementalFrameParser,
    InMemoryTransport,
    Source,
    Status,
    StreamMask,
    TemperatureStatus,
    ThingDAQ,
    UnexpectedMessageError,
    compute_checksum,
    decode_frame,
    encode_frame,
)
from thingdaq._generated import protocol_constants as constants
from thingdaq.simulator import SimulatedDevice


def _trigger_for(profile_id: ClockProfile) -> AdcTriggerMetadata:
    profile = constants.CLOCK_PROFILE_SPECS[profile_id]
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


def _valid_health(profile_id: ClockProfile, *, sequence: int = 1) -> ClockHealthSample:
    profile = ClockProfileMetadata.for_profile(profile_id)
    return ClockHealthSample(
        sample_sequence=sequence,
        sample_ticks=sequence * 8_000,
        clock_profile=profile,
        temperature_status=TemperatureStatus.VALID,
        flags=(
            ClockHealthFlag.CLOCKS_VALID
            | ClockHealthFlag.TEMPERATURE_VALID
            | ClockHealthFlag.UTILIZATION_VALID
        ),
        runtime_cpu_clock_hz=profile.cpu_clock_hz,
        runtime_ipg_clock_hz=profile.ipg_clock_hz,
        runtime_adc_clock_hz=profile.adc_clock_hz,
        runtime_pit_clock_hz=profile.pit_clock_hz,
        runtime_dwt_clock_hz=profile.dwt_clock_hz,
        temperature_millidegrees_celsius=42_125,
        acquisition_service_utilization_basis_points=1_250,
        usb_service_utilization_basis_points=625,
        error_flags=ClockHealthError.NONE,
    )


class ExactProfileDevice(SimulatedDevice):
    """Return internally consistent INFO/STATUS for either generated profile."""

    def __init__(self, profile_id: ClockProfile) -> None:
        super().__init__(build_id=f"clock-{int(profile_id)}-test")
        self.profile = ClockProfileMetadata.for_profile(profile_id)
        self.trigger = _trigger_for(profile_id)
        self.health_sequence = 0

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        info = DeviceInfo(
            device_state=self.state,
            build_id=f"clock-{int(self.profile.profile)}-test",
            clock_profile=self.profile,
            adc_ipg_clock_hz=self.profile.ipg_clock_hz,
            adc_clock_hz=self.profile.adc_clock_hz,
            adc_trigger=self.trigger,
        )
        return self._success_response(request, info.to_payload())

    def status(self) -> Status:
        self.health_sequence += 1
        return Status(
            DeviceState.IDLE,
            StreamMask.NONE,
            Source.HARDWARE,
            ChecksumAlgorithm.ADLER32,
            clock_health=_valid_health(
                self.profile.profile, sequence=self.health_sequence
            ),
            adc_ipg_clock_hz=self.profile.ipg_clock_hz,
            adc_clock_hz=self.profile.adc_clock_hz,
            adc_trigger=self.trigger,
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
            adc_trigger=_trigger_for(ClockProfile.EXPERIMENTAL_528_MHZ),
        )


class ClockProfileModelTests(unittest.TestCase):
    def test_info_and_status_round_trip_both_profiles_under_fragmentation(self) -> None:
        for profile_id in ClockProfile:
            with self.subTest(profile=profile_id.name):
                profile = ClockProfileMetadata.for_profile(profile_id)
                trigger = _trigger_for(profile_id)
                info = DeviceInfo(
                    device_state=DeviceState.IDLE,
                    build_id=f"clock-{profile.cpu_clock_hz}-test",
                    clock_profile=profile,
                    adc_ipg_clock_hz=profile.ipg_clock_hz,
                    adc_clock_hz=profile.adc_clock_hz,
                    adc_trigger=trigger,
                )
                status = Status(
                    DeviceState.IDLE,
                    StreamMask.NONE,
                    Source.HARDWARE,
                    ChecksumAlgorithm.ADLER32,
                    clock_health=_valid_health(profile_id),
                    adc_ipg_clock_hz=profile.ipg_clock_hz,
                    adc_clock_hz=profile.adc_clock_hz,
                    adc_trigger=trigger,
                )
                wire = encode_frame(
                    constants.FrameKind.INFO_RESPONSE,
                    info.to_payload(),
                    request_id=1,
                ) + encode_frame(
                    constants.FrameKind.GET_STATUS_RESPONSE,
                    status.to_payload(),
                    request_id=2,
                )
                parser = IncrementalFrameParser()
                frames = []
                pattern = (1, 2, 7, 31, 509, 3, 4_096)
                offset = 0
                fragment = 0
                while offset < len(wire):
                    width = pattern[fragment % len(pattern)]
                    frames.extend(parser.feed(wire[offset : offset + width]))
                    offset += width
                    fragment += 1

                self.assertEqual(0, parser.errors)
                self.assertEqual(0, parser.buffered_bytes)
                self.assertEqual(2, len(frames))
                self.assertEqual(info, DeviceInfo.from_payload(frames[0].payload))
                self.assertEqual(status, Status.from_payload(frames[1].payload))
                self.assertEqual(profile.cpu_clock_hz, info.clock_profile.cpu_clock_hz)
                self.assertEqual(profile.adc_clock_hz, info.adc_clock_hz)

    def test_advertised_profile_rejects_contradictory_generated_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "advertised clocks contradict"):
            ClockProfileMetadata(
                profile=ClockProfile.EXPERIMENTAL_528_MHZ,
                cpu_clock_hz=600_000_000,
            )

        profile = ClockProfileMetadata.for_profile(ClockProfile.PRODUCTION_600_MHZ)
        info = DeviceInfo(
            device_state=DeviceState.IDLE,
            build_id="clock-wire-contradiction",
            clock_profile=profile,
        )
        wire = bytearray(
            encode_frame(
                constants.FrameKind.INFO_RESPONSE,
                info.to_payload(),
                request_id=1,
            )
        )
        struct.pack_into(
            "<I",
            wire,
            constants.HEADER_SIZE + constants.INFO_RESPONSE_CPU_CLOCK_HZ_OFFSET,
            528_000_000,
        )
        checksum = compute_checksum(
            wire[: -constants.TRAILER_SIZE], constants.BOOTSTRAP_CHECKSUM_ALGORITHM
        )
        struct.pack_into("<I", wire, len(wire) - constants.TRAILER_SIZE, checksum)
        with self.assertRaisesRegex(FrameValidationError, "clocks contradict"):
            decode_frame(wire)

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

    def test_temperature_load_and_queue_bounds_are_inclusive_and_fail_closed(
        self,
    ) -> None:
        base = _valid_health(ClockProfile.EXPERIMENTAL_528_MHZ)
        for temperature in (
            constants.TEMPERATURE_MIN_MILLIDEGREES_CELSIUS,
            constants.TEMPERATURE_MAX_MILLIDEGREES_CELSIUS,
        ):
            with self.subTest(temperature=temperature):
                self.assertEqual(
                    temperature,
                    replace(
                        base, temperature_millidegrees_celsius=temperature
                    ).temperature_millidegrees_celsius,
                )
        for field, invalid in (
            (
                "temperature_millidegrees_celsius",
                constants.TEMPERATURE_MAX_MILLIDEGREES_CELSIUS + 1,
            ),
            ("acquisition_service_utilization_basis_points", 10_001),
            ("usb_service_utilization_basis_points", -1),
            ("adc_raw_ready_high_water", constants.ADC_DMA_RING_DEPTH + 1),
            ("gpio_raw_ready_high_water", constants.GPIO_RAW_RING_DEPTH + 1),
            ("packet_owned_high_water", constants.PACKET_BUFFER_COUNT + 1),
            ("usb_command_queue_high_water", constants.COMMAND_QUEUE_CAPACITY + 1),
            ("usb_response_queue_high_water", constants.RESPONSE_QUEUE_CAPACITY + 1),
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(ValueError),
            ):
                replace(base, **{field: invalid})


class ClockHealthClientTests(unittest.TestCase):
    def test_client_accepts_exact_runtime_health_for_both_profiles(self) -> None:
        for profile_id in ClockProfile:
            with self.subTest(profile=profile_id.name):
                transport = InMemoryTransport(ExactProfileDevice(profile_id))
                with ThingDAQ(transport) as daq:
                    info = daq.synchronize()
                    status = daq.status()
                    self.assertIs(info.clock_profile.profile, profile_id)
                    self.assertEqual(
                        info.clock_profile, status.clock_health.clock_profile
                    )
                    self.assertTrue(
                        status.clock_health.flags & ClockHealthFlag.CLOCKS_VALID
                    )

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
