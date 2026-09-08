"""Typed host coverage for actual dual-ADC initialization telemetry."""

from __future__ import annotations

import unittest
from typing import TypedDict

from thingdone_daq import AdcTriggerMetadata, DeviceInfo, Status
from thingdone_daq._generated import protocol_constants as constants
from thingdone_daq.protocol import FrameValidationError

READY_FLAGS = (
    constants.AdcConfigurationFlag.INITIALIZED
    | constants.AdcConfigurationFlag.NO_HARDWARE_AVERAGING
    | constants.AdcConfigurationFlag.HIGH_SPEED
    | constants.AdcConfigurationFlag.SHORTEST_SAMPLE
    | constants.AdcConfigurationFlag.ROUTES_VALIDATED
    | constants.AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
    | constants.AdcConfigurationFlag.CALIBRATION_COMPLETE
    | constants.AdcConfigurationFlag.PRIMARY_12_BIT
)


class AdcReadyMetadata(TypedDict):
    adc_configuration_flags: constants.AdcConfigurationFlag
    adc_calibration_states: tuple[
        constants.AdcCalibrationState, constants.AdcCalibrationState
    ]
    adc_calibration_cycles: tuple[int, int]


class AdcInitializationModelTests(unittest.TestCase):
    def test_exact_trigger_schedule_and_completion_timing_round_trip(self) -> None:
        trigger = AdcTriggerMetadata(
            configuration_flags=constants.AdcTriggerConfigurationFlag(
                constants.KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK
            ),
            ccm_cscmr1_configured=0x40,
            ccm_ccgr1_configured=0x00103000,
            ccm_ccgr2_configured=0x00C00000,
            pair_tctrl_configured=4,
            trigger_counter_configured=(0, 75),
            completion_counts=(1, 1),
            completion_delta_cycles=300,
            diagnostic_elapsed_cycles=600,
            xbar_sel_configured=(0x3900, 0x3900),
        )
        info = DeviceInfo(
            device_state=constants.DeviceState.IDLE,
            build_id="thingdaq-adc-trigger",
            adc_trigger=trigger,
        )

        decoded = DeviceInfo.from_payload(info.to_payload())
        self.assertEqual(trigger, decoded.adc_trigger)
        self.assertTrue(decoded.adc_trigger.ready)
        self.assertEqual(500.0, decoded.adc_trigger.completion_timing_delta_ns)
        self.assertEqual((0, 4), decoded.adc_trigger.trigger_queues)
        self.assertEqual((1, 76), decoded.adc_trigger.effective_delays)

    def test_trigger_failure_is_observable_and_bad_timing_is_rejected(self) -> None:
        failed = AdcTriggerMetadata(
            configuration_flags=(
                constants.AdcTriggerConfigurationFlag.CONFIGURED_STOPPED
                | constants.AdcTriggerConfigurationFlag.CLOCKS_VALID
            ),
            error_flags=constants.AdcTriggerError.XBAR_CONFIG_MISMATCH,
        )
        status = Status(
            device_state=constants.DeviceState.IDLE,
            stream_mask=constants.StreamMask.NONE,
            source=constants.Source.HARDWARE,
            data_checksum_algorithm=constants.DEFAULT_CHECKSUM_ALGORITHM,
            adc_trigger=failed,
        )
        decoded = Status.from_payload(status.to_payload())
        self.assertEqual(
            constants.AdcTriggerError.XBAR_CONFIG_MISMATCH,
            decoded.adc_trigger.error_flags,
        )
        self.assertFalse(decoded.adc_trigger.ready)

        timeout = AdcTriggerMetadata(
            configuration_flags=(
                constants.AdcTriggerConfigurationFlag.CONFIGURED_STOPPED
                | constants.AdcTriggerConfigurationFlag.ARM_SEQUENCE_EXERCISED
                | constants.AdcTriggerConfigurationFlag.STOPPED_AFTER_DIAGNOSTIC
            ),
            error_flags=(
                constants.AdcTriggerError.DIAGNOSTIC_TIMEOUT
                | constants.AdcTriggerError.COMPLETION_COUNT_MISMATCH
            ),
            diagnostic_elapsed_cycles=(
                constants.ADC_TRIGGER_DWT_CLOCK_HZ
                * constants.ADC_TRIGGER_DIAGNOSTIC_DEADLINE_US
                // 1_000_000
                + 1
            ),
        )
        self.assertFalse(timeout.ready)

        with self.assertRaisesRegex(ValueError, "completion timing"):
            AdcTriggerMetadata(
                configuration_flags=(
                    constants.AdcTriggerConfigurationFlag.ARM_SEQUENCE_EXERCISED
                    | constants.AdcTriggerConfigurationFlag.COMPLETION_TIMING_VALID
                    | constants.AdcTriggerConfigurationFlag.STOPPED_AFTER_DIAGNOSTIC
                ),
                completion_counts=(1, 1),
                completion_delta_cycles=500,
            )

    def test_info_and_status_round_trip_actual_success_snapshot(self) -> None:
        metadata: AdcReadyMetadata = {
            "adc_configuration_flags": READY_FLAGS,
            "adc_calibration_states": (
                constants.AdcCalibrationState.SUCCEEDED,
                constants.AdcCalibrationState.SUCCEEDED,
            ),
            "adc_calibration_cycles": (12_345, 23_456),
        }
        info = DeviceInfo(
            device_state=constants.DeviceState.IDLE,
            build_id="thingdaq-adc-init",
            **metadata,
        )
        status = Status(
            device_state=constants.DeviceState.IDLE,
            stream_mask=constants.StreamMask.NONE,
            source=constants.Source.HARDWARE,
            data_checksum_algorithm=constants.DEFAULT_CHECKSUM_ALGORITHM,
            **metadata,
        )

        self.assertEqual(info, DeviceInfo.from_payload(info.to_payload()))
        self.assertEqual(status, Status.from_payload(status.to_payload()))
        self.assertEqual((14, 15), info.adc_pins)
        self.assertEqual((1, 2), status.adc_peripherals)
        self.assertEqual((7, 8), info.adc_channels)
        self.assertEqual(37_500_000, status.adc_clock_hz)
        self.assertEqual(0, info.adc_hardware_average_count)

    def test_authorized_10_bit_fallback_is_unambiguous(self) -> None:
        fallback_flags = (
            READY_FLAGS & ~constants.AdcConfigurationFlag.PRIMARY_12_BIT
        ) | constants.AdcConfigurationFlag.FALLBACK_10_BIT
        info = DeviceInfo(
            device_state=constants.DeviceState.IDLE,
            build_id="thingdaq-adc-fallback",
            adc_resolution_bits=10,
            adc_code_max=1023,
            adc_conversion_mode=1,
            adc_configuration_flags=fallback_flags,
            adc_calibration_states=(
                constants.AdcCalibrationState.SUCCEEDED,
                constants.AdcCalibrationState.SUCCEEDED,
            ),
            adc_calibration_cycles=(100, 200),
        )

        decoded = DeviceInfo.from_payload(info.to_payload())
        self.assertEqual(10, decoded.adc_resolution_bits)
        self.assertEqual(1023, decoded.adc_code_max)
        self.assertTrue(
            decoded.adc_configuration_flags
            & constants.AdcConfigurationFlag.FALLBACK_10_BIT
        )
        self.assertFalse(
            decoded.adc_configuration_flags
            & constants.AdcConfigurationFlag.PRIMARY_12_BIT
        )

    def test_independent_failure_states_and_errors_are_preserved(self) -> None:
        status = Status(
            device_state=constants.DeviceState.IDLE,
            stream_mask=constants.StreamMask.NONE,
            source=constants.Source.HARDWARE,
            data_checksum_algorithm=constants.DEFAULT_CHECKSUM_ALGORITHM,
            adc_calibration_states=(
                constants.AdcCalibrationState.TIMED_OUT,
                constants.AdcCalibrationState.SUCCEEDED,
            ),
            adc_calibration_cycles=(6_000_000, 500),
            adc_initialization_error_flags=(
                constants.AdcInitializationError.ADC0_CALIBRATION_TIMEOUT
            ),
        )

        decoded = Status.from_payload(status.to_payload())
        self.assertEqual(
            constants.AdcCalibrationState.TIMED_OUT,
            decoded.adc_calibration_states[0],
        )
        self.assertEqual(
            constants.AdcCalibrationState.SUCCEEDED,
            decoded.adc_calibration_states[1],
        )
        self.assertEqual(
            constants.AdcInitializationError.ADC0_CALIBRATION_TIMEOUT,
            decoded.adc_initialization_error_flags,
        )

    def test_resolution_cannot_be_silently_misadvertised(self) -> None:
        payload = bytearray(
            DeviceInfo(
                device_state=constants.DeviceState.IDLE,
                build_id="thingdaq-adc-primary",
            ).to_payload()
        )
        payload[constants.INFO_RESPONSE_ADC_RESOLUTION_BITS_OFFSET] = 10
        with self.assertRaisesRegex((FrameValidationError, ValueError), "ADC"):
            DeviceInfo.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
