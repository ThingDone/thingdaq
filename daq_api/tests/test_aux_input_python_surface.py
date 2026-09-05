"""Focused typed API, simulator, alignment, NumPy, and CLI aux-bank tests."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace

import thingdaq
from thingdaq import (
    ADCBlock,
    AdcBlockMetadata,
    AdcTriggerMetadata,
    AlignedInterval,
    AlignmentLoss,
    AuxBankMode,
    DAQConfiguration,
    DeviceState,
    FrameFlag,
    FrameValidationError,
    GPIOBlock,
    GPIOLayout,
    InMemoryTransport,
    RateProfile,
    RateProfileTiming,
    SessionRecoveryPolicy,
    SimulatedDevice,
    Source,
    StreamGap,
    StreamMask,
    SyntheticGPIOPattern,
    ThingDAQ,
    TimestampAligner,
    TimestampAlignmentError,
    UnexpectedMessageError,
    analyze_stream_continuity,
    synthetic_adc_payload,
    synthetic_gpio_bank_bytes,
    synthetic_gpio_payload,
    synthetic_gpio_value,
)
from thingdaq._generated import protocol_constants as v1_constants
from thingdaq._generated import protocol_v2_constants as v2_constants
from thingdaq.cli import CliExitCode, build_parser, main
from thingdaq.protocol_v2 import decode_v2_frame, encode_v2_frame


def _configuration(
    mode: AuxBankMode,
    profile: RateProfile,
) -> DAQConfiguration:
    return DAQConfiguration(
        stream_mask=StreamMask.ADC | StreamMask.GPIO,
        source=Source.SYNTHETIC,
        aux_bank_mode=mode,
        rate_profile=profile,
    )


def _flags(sequence: int) -> FrameFlag:
    flags = FrameFlag.SYNTHETIC
    if sequence == 0:
        flags |= FrameFlag.EPOCH_START
    return flags


def _adc_block(
    configuration: DAQConfiguration,
    interval: int,
    *,
    run_id: int = 1,
) -> ADCBlock:
    timing = configuration.rate_timing
    layout = configuration.gpio_layout
    first_ticks = interval * timing.frame_coverage_ticks(configuration.aux_bank_mode)
    return ADCBlock(
        run_id=run_id,
        sequence=interval,
        first_sample_ticks=first_ticks,
        payload=synthetic_adc_payload(
            first_ticks // timing.adc_pair_period_ticks,
            layout.adc_items_per_frame,
        ),
        flags=_flags(interval),
        metadata=AdcBlockMetadata(
            source=Source.SYNTHETIC,
            pair_rate_hz=timing.adc_pair_rate_hz,
            pair_period_ticks=timing.adc_pair_period_ticks,
            adc1_phase_ticks=timing.adc1_phase_ticks,
            trigger=AdcTriggerMetadata.for_rate_profile(configuration.rate_profile),
        ),
        aux_bank_mode=configuration.aux_bank_mode,
        rate_profile=configuration.rate_profile,
        protocol_version=configuration.protocol_version,
    )


def _gpio_block(
    configuration: DAQConfiguration,
    interval: int,
    *,
    run_id: int = 1,
) -> GPIOBlock:
    timing = configuration.rate_timing
    layout = configuration.gpio_layout
    first_ticks = interval * timing.frame_coverage_ticks(configuration.aux_bank_mode)
    return GPIOBlock(
        run_id=run_id,
        sequence=interval,
        first_sample_ticks=first_ticks,
        payload=synthetic_gpio_payload(
            first_ticks // timing.gpio_sample_period_ticks,
            layout.items_per_frame,
            aux_bank_mode=configuration.aux_bank_mode,
        ),
        flags=_flags(interval),
        aux_bank_mode=configuration.aux_bank_mode,
        rate_profile=configuration.rate_profile,
        protocol_version=configuration.protocol_version,
    )


class TypedAuxiliaryModelTests(unittest.TestCase):
    def test_default_configuration_is_byte_for_byte_protocol_v1(self) -> None:
        configuration = DAQConfiguration(
            stream_mask=StreamMask.ADC | StreamMask.GPIO,
            source=Source.SYNTHETIC,
        )

        self.assertIs(AuxBankMode.DISABLED, configuration.aux_bank_mode)
        self.assertIs(
            RateProfile.ADC_1MHZ_GPIO_4MHZ,
            configuration.rate_profile,
        )
        self.assertEqual(v1_constants.PROTOCOL_VERSION, configuration.protocol_version)
        self.assertEqual(
            v1_constants.CONFIGURE_REQUEST_PAYLOAD_SIZE, len(configuration.to_payload())
        )
        self.assertEqual(
            configuration,
            DAQConfiguration.from_payload(configuration.to_payload()),
        )
        self.assertEqual(
            GPIOLayout.from_mode(AuxBankMode.DISABLED), configuration.gpio_layout
        )

    def test_generated_profiles_and_layouts_are_exact_and_closed(self) -> None:
        expected_rates = (
            (1_000_000, 4_000_000),
            (500_000, 2_000_000),
            (250_000, 1_000_000),
            (125_000, 500_000),
            (1_000_000, 1_000_000),
        )
        self.assertEqual(
            expected_rates,
            tuple(
                (
                    RateProfileTiming.from_profile(profile).adc_pair_rate_hz,
                    RateProfileTiming.from_profile(profile).gpio_sample_rate_hz,
                )
                for profile in RateProfile
            ),
        )
        for profile, rates in zip(RateProfile, expected_rates, strict=True):
            with self.subTest(profile=profile.name):
                timing = RateProfileTiming.from_profile(profile)
                self.assertEqual(profile, RateProfileTiming.from_rates(*rates).profile)
                self.assertEqual(
                    timing.disabled_frame_coverage_ticks,
                    1_012 * timing.adc_pair_period_ticks,
                )
                self.assertEqual(
                    timing.input_frame_coverage_ticks,
                    506 * timing.adc_pair_period_ticks,
                )
                self.assertEqual(
                    timing.gpio_sample_rate_hz,
                    (1 if profile is RateProfile.ADC_1MHZ_GPIO_1MHZ else 4)
                    * timing.adc_pair_rate_hz,
                )

        disabled = GPIOLayout.from_mode(AuxBankMode.DISABLED)
        enabled = GPIOLayout.from_mode(AuxBankMode.INPUT)
        self.assertEqual(
            (8, 1, 4_048, 1_012),
            (
                disabled.packed_width_bits,
                disabled.item_bytes,
                disabled.items_per_frame,
                disabled.adc_items_per_frame,
            ),
        )
        self.assertEqual(
            (16, 2, 2_024, 506),
            (
                enabled.packed_width_bits,
                enabled.item_bytes,
                enabled.items_per_frame,
                enabled.adc_items_per_frame,
            ),
        )
        with self.assertRaisesRegex(ValueError, "exact generated"):
            RateProfileTiming.from_rates(200_000, 800_000)


class GPIOBlockAndNumPyTests(unittest.TestCase):
    def test_sixteen_bit_samples_maps_channels_and_legacy_errors(self) -> None:
        payload = b"\xff\xff\x34\x12" + bytes(v2_constants.DATA_PAYLOAD_BYTES - 4)
        block = GPIOBlock(
            run_id=5,
            sequence=0,
            first_sample_ticks=0,
            payload=payload,
            flags=FrameFlag.EPOCH_START,
            aux_bank_mode=AuxBankMode.INPUT,
            protocol_version=v2_constants.PROTOCOL_VERSION,
        )

        self.assertEqual(0xFFFF, block.sample(0))
        self.assertEqual(0x1234, block.sample(1))
        self.assertEqual(0xFFFF, block.sample_mask)
        self.assertEqual(16, block.packed_width_bits)
        self.assertEqual(tuple(range(6, 14)), block.primary_pins_by_bit)
        self.assertEqual(tuple(range(16, 24)), block.auxiliary_pins_by_bit)
        self.assertEqual(
            (*range(6, 14), *range(16, 24)),
            block.pins_by_bit,
        )
        for pin in (*range(6, 14), *range(16, 24)):
            with self.subTest(pin=pin):
                self.assertTrue(block.channel(pin)[0])
        with self.assertRaisesRegex(ValueError, "D16 through D23"):
            block.channel(14)

        legacy = GPIOBlock(
            run_id=5,
            sequence=0,
            first_sample_ticks=0,
            payload=synthetic_gpio_payload(0),
            flags=FrameFlag.EPOCH_START,
        )
        self.assertEqual(8, legacy.packed_width_bits)
        self.assertEqual(0xFF, legacy.sample_mask)
        self.assertEqual(0, legacy.sample(0))
        self.assertEqual(v1_constants.GPIO_SAMPLES_PER_FRAME, len(legacy.samples))
        with self.assertRaisesRegex(ValueError, "D6 through D13"):
            legacy.channel(16)
        with self.assertRaisesRegex(TypeError, "D6 through D13"):
            legacy.channel(True)

    def test_negotiated_layout_rejects_another_valid_wire_shape(self) -> None:
        configuration = _configuration(
            AuxBankMode.INPUT,
            RateProfile.ADC_1MHZ_GPIO_4MHZ,
        )
        wire = encode_v2_frame(
            v2_constants.FrameKind.GPIO_DATA,
            bytes(v2_constants.DATA_PAYLOAD_BYTES),
            flags=v2_constants.FrameFlag.EPOCH_START,
            run_id=1,
            item_count=4_048,
        )
        frame = decode_v2_frame(wire)
        with self.assertRaisesRegex(FrameValidationError, "negotiated layout"):
            GPIOBlock.from_v2_frame(frame, configuration)

    def test_numpy_keeps_uint8_and_adds_zero_copy_little_endian_uint16(self) -> None:
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy optional dependency is not installed")

        legacy = _gpio_block(
            _configuration(
                AuxBankMode.DISABLED,
                RateProfile.ADC_1MHZ_GPIO_4MHZ,
            ),
            0,
        )
        extended = GPIOBlock(
            run_id=7,
            sequence=0,
            first_sample_ticks=0,
            payload=b"\x34\x12" + bytes(v2_constants.DATA_PAYLOAD_BYTES - 2),
            flags=FrameFlag.EPOCH_START,
            aux_bank_mode=AuxBankMode.INPUT,
            protocol_version=v2_constants.PROTOCOL_VERSION,
        )
        legacy_view = legacy.as_numpy()
        extended_view = extended.as_numpy()

        self.assertEqual(np.dtype("u1"), legacy_view.packed.dtype)
        self.assertEqual(np.dtype("<u2"), extended_view.packed.dtype)
        self.assertEqual("<u2", extended_view.packed.dtype.str)
        self.assertEqual(0x1234, int(extended_view.packed[0]))
        self.assertFalse(legacy_view.packed.flags.writeable)
        self.assertFalse(extended_view.packed.flags.writeable)
        self.assertIs(extended.payload, extended_view.payload_owner)
        raw_bytes = np.frombuffer(extended.payload, dtype=np.dtype("u1"))
        self.assertTrue(np.shares_memory(raw_bytes, extended_view.packed))
        self.assertEqual(tuple(range(16)), extended_view.bits)
        self.assertEqual((*range(6, 14), *range(16, 24)), extended_view.pins)
        self.assertTrue(bool(extended_view.channel(17).values[0]))
        self.assertFalse(bool(extended_view.channel(23).values[0]))


class VariableRateAlignmentTests(unittest.TestCase):
    def test_selected_periods_align_and_dynamic_gaps_retain_exact_units(self) -> None:
        configuration = _configuration(
            AuxBankMode.INPUT,
            RateProfile.ADC_250KHZ_GPIO_1MHZ,
        )
        timing = configuration.rate_timing
        coverage = timing.input_frame_coverage_ticks
        adc0 = _adc_block(configuration, 0, run_id=21)
        gpio0 = _gpio_block(configuration, 0, run_id=21)
        aligner = TimestampAligner()

        self.assertEqual((), aligner.push(adc0))
        output = aligner.push(gpio0)
        self.assertEqual(1, len(output))
        interval = output[0]
        self.assertIsInstance(interval, AlignedInterval)
        assert isinstance(interval, AlignedInterval)
        self.assertTrue(interval.complete)
        self.assertEqual(coverage, interval.frame_coverage_ticks)
        self.assertEqual(coverage, interval.end_tick_exclusive)

        current = _gpio_block(configuration, 2, run_id=21)
        gap = analyze_stream_continuity(
            current,
            expected_sequence=1,
            expected_first_sample_ticks=coverage,
            active_run_id=21,
            previous_sequence=0,
        )
        self.assertIsInstance(gap, StreamGap)
        assert isinstance(gap, StreamGap)
        self.assertEqual(timing.gpio_sample_period_ticks, gap.item_period_ticks)
        self.assertEqual(2_024, gap.items_per_frame)
        self.assertEqual(2_024, gap.missing_items)
        self.assertEqual(coverage, gap.missing_duration_ticks)

    def test_same_coverage_different_profiles_never_cross_and_runs_flush(self) -> None:
        disabled_500k = _configuration(
            AuxBankMode.DISABLED,
            RateProfile.ADC_500KHZ_GPIO_2MHZ,
        )
        input_250k = _configuration(
            AuxBankMode.INPUT,
            RateProfile.ADC_250KHZ_GPIO_1MHZ,
        )
        self.assertEqual(
            disabled_500k.rate_timing.disabled_frame_coverage_ticks,
            input_250k.rate_timing.input_frame_coverage_ticks,
        )
        aligner = TimestampAligner()
        aligner.push(_adc_block(disabled_500k, 0, run_id=31))
        with self.assertRaisesRegex(TimestampAlignmentError, "mode/rate profile"):
            aligner.push(_gpio_block(input_250k, 0, run_id=31))

        aligner = TimestampAligner()
        old_adc = _adc_block(input_250k, 0, run_id=40)
        new_gpio = _gpio_block(input_250k, 0, run_id=41)
        aligner.push(old_adc)
        boundary = aligner.push(new_gpio)
        self.assertEqual(
            [AlignmentLoss, AlignedInterval], [type(item) for item in boundary]
        )
        completed = aligner.push(_adc_block(input_250k, 0, run_id=41))
        self.assertEqual(1, len(completed))
        self.assertEqual(41, completed[0].run_id)


class SimulatorAndCliSurfaceTests(unittest.TestCase):
    def test_every_mode_profile_and_pattern_has_exact_info_status_and_data(
        self,
    ) -> None:
        for mode in AuxBankMode:
            for profile in RateProfile:
                for pattern in SyntheticGPIOPattern:
                    with (
                        self.subTest(
                            mode=mode.name,
                            profile=profile.name,
                            pattern=pattern.value,
                        ),
                        ThingDAQ.simulated(
                            gpio_pattern=pattern,
                            strict=True,
                        ) as daq,
                    ):
                        configuration = daq.configure(
                            adc=True,
                            gpio=True,
                            source=Source.SYNTHETIC,
                            aux_bank_mode=mode,
                            rate_profile=profile,
                        )
                        info = daq.info()
                        self.assertEqual(
                            configuration.protocol_version,
                            info.protocol_version,
                        )
                        self.assertEqual(configuration, info.applied_configuration)
                        self.assertTrue(
                            info.capabilities.supports_configuration(configuration)
                        )
                        self.assertEqual(
                            configuration.adc_pair_rate_hz,
                            info.adc_pair_rate_hz,
                        )
                        self.assertEqual(
                            configuration.gpio_sample_rate_hz,
                            info.gpio_sample_rate_hz,
                        )
                        if configuration.uses_protocol_v2:
                            self.assertIsNotNone(info.auxiliary)
                        else:
                            self.assertIsNone(info.auxiliary)

                        run_id = daq.start()
                        adc = daq.read_block(timeout=0.5)
                        gpio = daq.read_block(timeout=0.5)
                        self.assertIsInstance(adc, ADCBlock)
                        self.assertIsInstance(gpio, GPIOBlock)
                        assert isinstance(adc, ADCBlock)
                        assert isinstance(gpio, GPIOBlock)
                        layout = configuration.gpio_layout
                        timing = configuration.rate_timing
                        self.assertEqual(run_id, adc.run_id)
                        self.assertEqual(run_id, gpio.run_id)
                        self.assertEqual(layout.adc_items_per_frame, adc.item_count)
                        self.assertEqual(layout.items_per_frame, gpio.item_count)
                        self.assertEqual(
                            timing.frame_coverage_ticks(mode),
                            adc.frame_coverage_ticks,
                        )
                        self.assertEqual(
                            adc.frame_coverage_ticks
                            * (4 if profile is RateProfile.ADC_1MHZ_GPIO_1MHZ else 1),
                            gpio.frame_coverage_ticks,
                        )
                        self.assertEqual(
                            synthetic_gpio_value(
                                gpio.first_sample_index,
                                aux_bank_mode=mode,
                                pattern=pattern,
                            ),
                            gpio.sample(0),
                        )
                        primary, auxiliary = synthetic_gpio_bank_bytes(
                            gpio.first_sample_index,
                            pattern,
                        )
                        self.assertEqual(primary, gpio.sample(0) & 0xFF)
                        if mode is AuxBankMode.INPUT:
                            self.assertEqual(auxiliary, gpio.sample(0) >> 8)

                        aligned = TimestampAligner()
                        if profile is RateProfile.ADC_1MHZ_GPIO_1MHZ:
                            with self.assertRaisesRegex(ValueError, "four ADC frames"):
                                aligned.push(adc)
                            with self.assertRaisesRegex(ValueError, "four ADC frames"):
                                aligned.push(gpio)
                        else:
                            self.assertEqual((), aligned.push(adc))
                            self.assertEqual(1, len(aligned.push(gpio)))
                        status = daq.status()
                        self.assertEqual(configuration, status.configuration)
                        self.assertEqual(
                            timing.adc_pair_rate_hz,
                            status.adc_trigger.pair_rate_hz,
                        )
                        self.assertEqual(
                            timing.gpio_sample_rate_hz,
                            status.adc_trigger.gpio_master_rate_hz,
                        )

    def test_formula_families_are_independent_and_deterministic(self) -> None:
        self.assertEqual((0, 0), synthetic_gpio_bank_bytes(0, "all-zero"))
        self.assertEqual((0x01, 0x08), synthetic_gpio_bank_bytes(0, "walking-bit"))
        self.assertEqual((0x00, 0x55), synthetic_gpio_bank_bytes(0, "counter"))
        self.assertEqual((0xAA, 0x0F), synthetic_gpio_bank_bytes(0, "high-transition"))
        self.assertEqual((0x55, 0xF0), synthetic_gpio_bank_bytes(1, "high-transition"))

    def test_stopped_status_retains_exact_v2_counter_units(self) -> None:
        with ThingDAQ.simulated() as daq:
            configuration = daq.configure(
                source=Source.SYNTHETIC,
                aux_bank_mode=AuxBankMode.INPUT,
                rate_profile=RateProfile.ADC_250KHZ_GPIO_1MHZ,
            )
            daq.start()
            daq.read_block(timeout=0.5)
            daq.read_block(timeout=0.5)
            running = daq.status()
            daq.stop()
            stopped = daq.status()

            self.assertEqual(configuration, running.configuration)
            self.assertIsNone(stopped.configuration)
            self.assertEqual(
                configuration.gpio_layout.adc_payload_bytes,
                stopped.adc_payload_bytes_transmitted,
            )
            self.assertEqual(
                configuration.gpio_layout.payload_bytes,
                stopped.gpio_payload_bytes_transmitted,
            )
            self.assertEqual(
                running.data_payload_bytes_transmitted,
                stopped.data_payload_bytes_transmitted,
            )
            self.assertEqual(
                configuration.rate_profile,
                RateProfileTiming.from_rates(
                    stopped.adc_trigger.pair_rate_hz,
                    stopped.adc_trigger.gpio_master_rate_hz,
                ).profile,
            )

    def test_start_rejects_applied_configuration_drift_after_configure(self) -> None:
        device = SimulatedDevice()
        with ThingDAQ.open(InMemoryTransport(device)) as daq:
            configured = daq.configure(
                source=Source.SYNTHETIC,
                aux_bank_mode=AuxBankMode.INPUT,
                rate_profile=RateProfile.ADC_250KHZ_GPIO_1MHZ,
            )
            device._configuration = replace(
                configured,
                rate_profile=RateProfile.ADC_125KHZ_GPIO_500KHZ,
            )
            with self.assertRaisesRegex(UnexpectedMessageError, "before START"):
                daq.start()

    def test_v1_client_can_still_stop_a_preserved_v2_session(self) -> None:
        device = SimulatedDevice()
        owner = ThingDAQ.open(InMemoryTransport(device))
        owner.configure(
            source=Source.SYNTHETIC,
            aux_bank_mode=AuxBankMode.INPUT,
            rate_profile=RateProfile.ADC_500KHZ_GPIO_2MHZ,
        )
        owner.close(stop=False)

        fallback = ThingDAQ.open(
            InMemoryTransport(device),
            session_policy=SessionRecoveryPolicy.STOP,
        )
        self.assertEqual(DeviceState.IDLE, fallback.state)
        self.assertEqual(DeviceState.IDLE, device.state)
        fallback.close(stop=False)

    def test_cli_parses_and_reports_exact_auxiliary_configuration(self) -> None:
        arguments = build_parser().parse_args(
            [
                "monitor",
                "--simulate",
                "--aux-bank-mode",
                "input",
                "--rate-profile",
                "adc_250khz_gpio_1mhz",
                "--gpio-pattern",
                "walking-bit",
                "--gpio-channel",
                "D23",
            ]
        )
        self.assertEqual("input", arguments.aux_bank_mode)
        self.assertEqual("adc_250khz_gpio_1mhz", arguments.rate_profile)
        self.assertEqual("walking-bit", arguments.gpio_pattern)
        self.assertEqual([23], arguments.gpio_channel)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "configure",
                    "--simulate",
                    "--source",
                    "synthetic",
                    "--aux-bank-mode",
                    "input",
                    "--rate-profile",
                    "adc_250khz_gpio_1mhz",
                    "--json",
                ]
            )
        self.assertEqual(CliExitCode.OK, exit_code, stderr.getvalue())
        applied = json.loads(stdout.getvalue())["applied_configuration"]
        self.assertEqual(2, applied["protocol_version"])
        self.assertEqual("INPUT", applied["aux_bank_mode"])
        self.assertEqual("ADC_250KHZ_GPIO_1MHZ", applied["rate_profile"])
        self.assertEqual(250_000, applied["adc_pair_rate_hz"])
        self.assertEqual(1_000_000, applied["gpio_sample_rate_hz"])
        self.assertEqual(16, applied["gpio_packed_width_bits"])

    def test_new_models_and_patterns_are_public_exports(self) -> None:
        required = {
            "AuxBankMode",
            "AuxiliaryInputMetadata",
            "GPIOLayout",
            "RATE_PROFILE_TIMINGS",
            "RateProfile",
            "RateProfileTiming",
            "SyntheticGPIOPattern",
            "synthetic_gpio_bank_bytes",
            "synthetic_gpio_value",
        }
        self.assertTrue(required.issubset(thingdaq.__all__))
        for name in required:
            with self.subTest(name=name):
                self.assertTrue(hasattr(thingdaq, name))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
