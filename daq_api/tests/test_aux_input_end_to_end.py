"""Independent model, NumPy, alignment, simulator, and cleanup tests."""

from __future__ import annotations

import struct
import unittest

from thingdaq import (
    ADCBlock,
    AdcBlockMetadata,
    AdcTriggerMetadata,
    AlignedInterval,
    AlignmentLoss,
    AuxBankMode,
    ChecksumAlgorithm,
    DAQConfiguration,
    DAQShutdownError,
    DeviceCommandError,
    DeviceState,
    ErrorCode,
    FrameFlag,
    FrameKind,
    GPIOBlock,
    InMemoryTransport,
    RateProfile,
    SimulatedDevice,
    Source,
    StreamGap,
    StreamMask,
    SyntheticGPIOPattern,
    SyntheticPatternError,
    ThingDAQ,
    TimestampAligner,
    UnexpectedMessageError,
    synthetic_adc_payload,
    synthetic_gpio_bank_bytes,
    synthetic_gpio_payload,
    synthetic_gpio_value,
    validate_synthetic_gpio_payload,
)
from thingdaq._generated import protocol_v2_constants as constants

_SUCCESS_PREFIX = bytes(4)


def _independent_bank_formula(
    sample_index: int,
    pattern: SyntheticGPIOPattern,
) -> tuple[int, int]:
    if pattern is SyntheticGPIOPattern.ALL_ZERO:
        return 0, 0
    if pattern is SyntheticGPIOPattern.WALKING_BIT:
        return 1 << (sample_index % 8), 1 << ((sample_index + 3) % 8)
    if pattern is SyntheticGPIOPattern.COUNTER:
        return sample_index & 0xFF, (3 * sample_index + 0x55) & 0xFF
    return (
        0xAA if sample_index % 2 == 0 else 0x55,
        0x0F if sample_index % 2 == 0 else 0xF0,
    )


def _configuration(mode: AuxBankMode, profile: RateProfile) -> DAQConfiguration:
    return DAQConfiguration(
        stream_mask=StreamMask.ADC | StreamMask.GPIO,
        source=Source.SYNTHETIC,
        aux_bank_mode=mode,
        rate_profile=profile,
    )


def _block_pair(
    configuration: DAQConfiguration,
    sequence: int,
    *,
    run_id: int = 37,
) -> tuple[ADCBlock, GPIOBlock]:
    timing = configuration.rate_timing
    layout = configuration.gpio_layout
    coverage = timing.frame_coverage_ticks(configuration.aux_bank_mode)
    first_ticks = sequence * coverage
    flags = FrameFlag.SYNTHETIC
    if sequence == 0:
        flags |= FrameFlag.EPOCH_START
    adc = ADCBlock(
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=first_ticks,
        payload=synthetic_adc_payload(
            first_ticks // timing.adc_pair_period_ticks,
            layout.adc_items_per_frame,
        ),
        flags=flags,
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
    gpio = GPIOBlock(
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=first_ticks,
        payload=synthetic_gpio_payload(
            first_ticks // timing.gpio_sample_period_ticks,
            layout.items_per_frame,
            aux_bank_mode=configuration.aux_bank_mode,
        ),
        flags=flags,
        aux_bank_mode=configuration.aux_bank_mode,
        rate_profile=configuration.rate_profile,
        protocol_version=configuration.protocol_version,
    )
    return adc, gpio


class _ConfigureEchoMismatchDevice(SimulatedDevice):
    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        super()._handle_configure(request)
        changed = _configuration(
            AuxBankMode.INPUT,
            RateProfile.ADC_125KHZ_GPIO_500KHZ,
        )
        return self._success_response(
            request,
            _SUCCESS_PREFIX
            + changed.to_payload(protocol_version=constants.PROTOCOL_VERSION),
        )


class _StartEchoMismatchDevice(SimulatedDevice):
    def _handle_start(self, request):  # type: ignore[no-untyped-def]
        super()._handle_start(request)
        changed = _configuration(
            AuxBankMode.DISABLED,
            RateProfile.ADC_500KHZ_GPIO_2MHZ,
        )
        return self._success_response(
            request,
            _SUCCESS_PREFIX
            + changed.to_payload(protocol_version=constants.PROTOCOL_VERSION),
            run_id=self.run_id,
        )


class _StopFailureDevice(SimulatedDevice):
    def _handle_stop(self, request):  # type: ignore[no-untyped-def]
        return self._typed_error(request, ErrorCode.INTERNAL_ERROR)


class AuxiliaryBlockAndChannelPropertyTests(unittest.TestCase):
    def test_both_widths_and_every_profile_cross_frame_boundaries(self) -> None:
        selected_offsets = (0, 1, 7, 8, 255)
        for mode in AuxBankMode:
            for profile in RateProfile:
                device = SimulatedDevice(gpio_pattern=SyntheticGPIOPattern.COUNTER)
                transport = InMemoryTransport(
                    device,
                    read_chunk_size=19,
                    write_chunk_size=3,
                )
                with (
                    self.subTest(mode=mode.name, profile=profile.name),
                    ThingDAQ.open(
                        transport,
                        strict=True,
                        synchronization_retry_delay=0,
                        synthetic_gpio_pattern=SyntheticGPIOPattern.COUNTER,
                    ) as daq,
                ):
                    configuration = daq.configure(
                        source=Source.SYNTHETIC,
                        aux_bank_mode=mode,
                        rate_profile=profile,
                    )
                    run_id = daq.start()
                    items = tuple(daq.blocks(4, timeout=0.5))
                    self.assertEqual(4, len(items))
                    self.assertTrue(
                        all(isinstance(item, (ADCBlock, GPIOBlock)) for item in items)
                    )
                    adc_blocks = tuple(
                        item for item in items if isinstance(item, ADCBlock)
                    )
                    gpio_blocks = tuple(
                        item for item in items if isinstance(item, GPIOBlock)
                    )
                    self.assertEqual(
                        (0, 1), tuple(block.sequence for block in adc_blocks)
                    )
                    self.assertEqual(
                        (0, 1), tuple(block.sequence for block in gpio_blocks)
                    )
                    self.assertEqual(
                        {configuration.gpio_layout.adc_items_per_frame},
                        {block.item_count for block in adc_blocks},
                    )
                    self.assertEqual(
                        {configuration.gpio_layout.items_per_frame},
                        {block.item_count for block in gpio_blocks},
                    )
                    coverage = configuration.rate_timing.frame_coverage_ticks(mode)
                    self.assertEqual(
                        (0, coverage),
                        tuple(block.first_sample_ticks for block in adc_blocks),
                    )
                    self.assertEqual(
                        (0, coverage),
                        tuple(block.first_sample_ticks for block in gpio_blocks),
                    )

                    for block in gpio_blocks:
                        offsets = (*selected_offsets, block.item_count - 1)
                        for offset in offsets:
                            sample_index = block.first_sample_index + offset
                            primary, auxiliary = _independent_bank_formula(
                                sample_index,
                                SyntheticGPIOPattern.COUNTER,
                            )
                            expected = (
                                primary
                                if mode is AuxBankMode.DISABLED
                                else primary | (auxiliary << 8)
                            )
                            self.assertEqual(expected, block.sample(offset))
                            self.assertEqual(
                                block.first_sample_ticks
                                + offset
                                * configuration.rate_timing.gpio_sample_period_ticks,
                                block.sample_ticks(offset),
                            )
                            for bit, pin in enumerate(block.pins_by_bit):
                                self.assertEqual(
                                    bool(expected & (1 << bit)),
                                    block.channel(pin)[offset],
                                )

                    if mode is AuxBankMode.DISABLED:
                        for pin in range(16, 24):
                            with self.assertRaises(ValueError):
                                gpio_blocks[0].channel(pin)
                    else:
                        self.assertEqual(0xFFFF, gpio_blocks[0].sample_mask)
                        self.assertEqual(
                            tuple(range(16, 24)), gpio_blocks[0].auxiliary_pins_by_bit
                        )

                    status = daq.validate_stream_health()
                    self.assertEqual(run_id, adc_blocks[0].run_id)
                    self.assertEqual(configuration, status.configuration)
                    self.assertGreaterEqual(status.adc_frames_transmitted, 2)
                    self.assertGreaterEqual(status.gpio_frames_transmitted, 2)
                self.assertFalse(transport.is_open)
                self.assertIs(DeviceState.IDLE, device.state)

    def test_every_formula_is_independent_for_both_widths(self) -> None:
        for pattern in SyntheticGPIOPattern:
            for mode in AuxBankMode:
                start = 253
                count = 19
                payload = synthetic_gpio_payload(
                    start,
                    count,
                    aux_bank_mode=mode,
                    pattern=pattern,
                )
                item_bytes = 1 if mode is AuxBankMode.DISABLED else 2
                self.assertEqual(count * item_bytes, len(payload))
                for offset in range(count):
                    sample_index = start + offset
                    primary, auxiliary = _independent_bank_formula(
                        sample_index,
                        pattern,
                    )
                    expected = (
                        primary
                        if mode is AuxBankMode.DISABLED
                        else primary | (auxiliary << 8)
                    )
                    observed = (
                        payload[offset]
                        if item_bytes == 1
                        else struct.unpack_from("<H", payload, 2 * offset)[0]
                    )
                    with self.subTest(
                        pattern=pattern.value,
                        mode=mode.name,
                        sample_index=sample_index,
                    ):
                        self.assertEqual(
                            (primary, auxiliary),
                            synthetic_gpio_bank_bytes(sample_index, pattern),
                        )
                        self.assertEqual(
                            expected,
                            synthetic_gpio_value(
                                sample_index,
                                aux_bank_mode=mode,
                                pattern=pattern,
                            ),
                        )
                        self.assertEqual(expected, observed)

    def test_big_endian_word_bytes_are_not_silently_treated_as_wire_order(self) -> None:
        count = constants.AUX_BANK_LAYOUTS[AuxBankMode.INPUT]["gpio_items_per_frame"]
        correct = synthetic_gpio_payload(
            0,
            count,
            aux_bank_mode=AuxBankMode.INPUT,
            pattern=SyntheticGPIOPattern.COUNTER,
        )
        swapped = b"".join(
            correct[offset : offset + 2][::-1] for offset in range(0, len(correct), 2)
        )
        validate_synthetic_gpio_payload(
            correct,
            0,
            count,
            aux_bank_mode=AuxBankMode.INPUT,
            pattern=SyntheticGPIOPattern.COUNTER,
        )
        with self.assertRaises(SyntheticPatternError):
            validate_synthetic_gpio_payload(
                swapped,
                0,
                count,
                aux_bank_mode=AuxBankMode.INPUT,
                pattern=SyntheticGPIOPattern.COUNTER,
            )

        block = GPIOBlock(
            run_id=3,
            sequence=0,
            first_sample_ticks=0,
            payload=swapped,
            flags=FrameFlag.SYNTHETIC | FrameFlag.EPOCH_START,
            aux_bank_mode=AuxBankMode.INPUT,
            protocol_version=constants.PROTOCOL_VERSION,
        )
        self.assertEqual(0x0055, block.sample(0))
        self.assertNotEqual(0x5500, block.sample(0))


class AuxiliaryNumPyPropertyTests(unittest.TestCase):
    def test_numpy_views_preserve_width_ownership_channels_and_rate_ticks(self) -> None:
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy is an optional dependency")

        for mode in AuxBankMode:
            for profile in RateProfile:
                configuration = _configuration(mode, profile)
                _, block = _block_pair(configuration, 1)
                view = block.as_numpy()
                expected_dtype = np.dtype(
                    "u1" if mode is AuxBankMode.DISABLED else "<u2"
                )
                with self.subTest(mode=mode.name, profile=profile.name):
                    self.assertEqual(expected_dtype, view.packed.dtype)
                    self.assertEqual((block.item_count,), view.packed.shape)
                    self.assertFalse(view.packed.flags.writeable)
                    self.assertFalse(view.packed.flags.owndata)
                    self.assertIs(block.payload, view.payload_owner)
                    self.assertTrue(
                        np.shares_memory(
                            view.packed,
                            np.frombuffer(block.payload, dtype=np.dtype("u1")),
                        )
                    )
                    offsets = np.asarray((0, 1, 255, block.item_count - 1))
                    expected_ticks = (
                        block.first_sample_ticks + offsets * block.sample_period_ticks
                    )
                    np.testing.assert_array_equal(
                        expected_ticks,
                        view.timestamps()[offsets],
                    )
                    channels = view.channels(block.pins_by_bit)
                    self.assertEqual(
                        (block.item_count, block.packed_width_bits),
                        channels.values.shape,
                    )
                    self.assertFalse(channels.values.flags.writeable)
                    for bit, pin in enumerate(block.pins_by_bit):
                        expected = np.not_equal(
                            np.bitwise_and(view.packed, 1 << bit),
                            0,
                        )
                        np.testing.assert_array_equal(
                            expected,
                            channels.for_pin(pin),
                        )


class VariableRateGapAndAlignmentPropertyTests(unittest.TestCase):
    def test_a_missing_interval_keeps_exact_units_for_every_mode_profile(self) -> None:
        for mode in AuxBankMode:
            for profile in RateProfile:
                configuration = _configuration(mode, profile)
                interval_zero = _block_pair(configuration, 0)
                interval_two = _block_pair(configuration, 2)
                aligner = TimestampAligner(max_pending_intervals=1)
                output = []
                for block in (*interval_zero, *interval_two):
                    output.extend(aligner.push(block))
                output.extend(aligner.finish())
                intervals = [
                    item for item in output if isinstance(item, AlignedInterval)
                ]
                losses = [item for item in output if isinstance(item, AlignmentLoss)]
                gaps = [item for item in output if isinstance(item, StreamGap)]
                coverage = configuration.rate_timing.frame_coverage_ticks(mode)
                with self.subTest(mode=mode.name, profile=profile.name):
                    self.assertEqual(
                        (0, 2 * coverage),
                        tuple(item.first_sample_ticks for item in intervals),
                    )
                    self.assertTrue(all(item.complete for item in intervals))
                    self.assertEqual(1, len(losses))
                    self.assertEqual(coverage, losses[0].first_sample_ticks)
                    self.assertEqual(coverage, losses[0].missing_duration_ticks)
                    self.assertEqual(2, len(gaps))
                    self.assertEqual(
                        {FrameKind.ADC_DATA, FrameKind.GPIO_DATA},
                        {gap.kind for gap in gaps},
                    )
                    for gap in gaps:
                        expected_items = (
                            configuration.gpio_layout.adc_items_per_frame
                            if gap.kind is FrameKind.ADC_DATA
                            else configuration.gpio_layout.items_per_frame
                        )
                        expected_period = (
                            configuration.rate_timing.adc_pair_period_ticks
                            if gap.kind is FrameKind.ADC_DATA
                            else configuration.rate_timing.gpio_sample_period_ticks
                        )
                        self.assertEqual(1, gap.missing_frames)
                        self.assertEqual(expected_items, gap.missing_items)
                        self.assertEqual(expected_period, gap.item_period_ticks)
                        self.assertEqual(coverage, gap.missing_duration_ticks)


class AuxiliaryLifecycleCleanupTests(unittest.TestCase):
    def test_configure_echo_failure_still_stops_and_closes(self) -> None:
        device = _ConfigureEchoMismatchDevice()
        transport = InMemoryTransport(device, read_chunk_size=11, write_chunk_size=3)
        with (
            self.assertRaisesRegex(
                UnexpectedMessageError,
                "CONFIGURE applied configuration differs",
            ),
            ThingDAQ.open(
                transport,
                synchronization_retry_delay=0,
            ) as daq,
        ):
            daq.configure(
                source=Source.SYNTHETIC,
                aux_bank_mode=AuxBankMode.INPUT,
                rate_profile=RateProfile.ADC_250KHZ_GPIO_1MHZ,
            )
        self.assertFalse(transport.is_open)
        self.assertIs(DeviceState.IDLE, device.state)

    def test_start_echo_failure_still_stops_and_closes(self) -> None:
        device = _StartEchoMismatchDevice()
        transport = InMemoryTransport(device, read_chunk_size=13, write_chunk_size=2)
        with (
            self.assertRaisesRegex(
                UnexpectedMessageError,
                "START applied configuration differs",
            ),
            ThingDAQ.open(
                transport,
                synchronization_retry_delay=0,
            ) as daq,
        ):
            daq.configure(
                source=Source.SYNTHETIC,
                aux_bank_mode=AuxBankMode.INPUT,
                rate_profile=RateProfile.ADC_250KHZ_GPIO_1MHZ,
            )
            daq.start()
        self.assertFalse(transport.is_open)
        self.assertIs(DeviceState.IDLE, device.state)

    def test_stop_failure_is_reported_after_transport_cleanup(self) -> None:
        device = _StopFailureDevice()
        transport = InMemoryTransport(device, read_chunk_size=17, write_chunk_size=3)
        daq = ThingDAQ.open(transport, synchronization_retry_delay=0)
        daq.configure(
            source=Source.SYNTHETIC,
            checksum_algorithm=ChecksumAlgorithm.CRC32C,
            aux_bank_mode=AuxBankMode.INPUT,
            rate_profile=RateProfile.ADC_500KHZ_GPIO_2MHZ,
        )
        daq.start()
        with self.assertRaises(DAQShutdownError) as raised:
            daq.close()
        self.assertIsInstance(raised.exception.stop_error, DeviceCommandError)
        self.assertIsNone(raised.exception.reader_error)
        self.assertFalse(daq.is_open)
        self.assertFalse(transport.is_open)
        self.assertIs(DeviceState.RUNNING, device.state)
        daq.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
