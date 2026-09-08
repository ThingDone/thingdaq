"""Focused GPIO block, capability, timestamp, and strict-gap tests."""

from __future__ import annotations

import unittest
from collections.abc import Sequence

from thingdone_daq import (
    BoardId,
    Capability,
    ConfigurationProfile,
    DeviceInfo,
    DeviceState,
    FrameFlag,
    FrameKind,
    GPIOBlock,
    GpioCaptureDiagnosticFlag,
    GpioCaptureDiagnosticMode,
    GpioChannelView,
    InMemoryTransport,
    McuId,
    SimulatedDevice,
    Source,
    StreamMask,
    ThingDAQ,
    UnexpectedStreamGapError,
    decode_frame,
    encode_frame,
)
from thingdone_daq._generated import protocol_constants as constants


class GpioGapDevice(SimulatedDevice):
    """Skip GPIO sequence one and flag sequence two as a firmware overrun."""

    def __init__(self) -> None:
        super().__init__()
        self._gap_injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None:
            return None
        frame = decode_frame(wire)
        if (
            not self._gap_injected
            and frame.header.kind is FrameKind.GPIO_DATA
            and frame.header.sequence == 1
        ):
            self._gap_injected = True
            self._gpio_items_dropped += constants.GPIO_SAMPLES_PER_FRAME
            replacement = super().next_data_frame()
            assert replacement is not None
            frame = decode_frame(replacement)
            return encode_frame(
                frame.header.kind,
                frame.payload,
                flags=frame.header.flags
                | FrameFlag.GAP_BEFORE
                | FrameFlag.OVERRUN_BEFORE,
                checksum_algorithm=frame.header.checksum_algorithm,
                run_id=frame.header.run_id,
                sequence=frame.header.sequence,
                request_id=frame.header.request_id,
                first_sample_ticks=frame.header.first_sample_ticks,
                item_count=frame.header.item_count,
            )
        return wire


class GPIOBlockTests(unittest.TestCase):
    def test_channels_are_lazy_and_retain_exact_d6_through_d13_metadata(
        self,
    ) -> None:
        packed = bytearray(constants.GPIO_DATA_PAYLOAD_SIZE)
        for bit in range(len(constants.GPIO_PINS_BY_BIT)):
            packed[bit] = 1 << bit
        block = GPIOBlock(
            run_id=7,
            sequence=3,
            first_sample_ticks=246_912,
            payload=bytes(packed),
        )

        self.assertIsInstance(block.samples, memoryview)
        self.assertIs(block.samples.obj, block.payload)
        self.assertEqual(constants.GPIO_PINS_BY_BIT, tuple(range(6, 14)))
        for bit, pin in enumerate(constants.GPIO_PINS_BY_BIT):
            with self.subTest(bit=bit, pin=pin):
                channel = block.channel(pin)
                self.assertIsInstance(channel, GpioChannelView)
                self.assertIsInstance(channel, Sequence)
                self.assertNotIsInstance(channel, (list, tuple))
                self.assertEqual(pin, channel.pin)
                self.assertEqual(bit, channel.bit)
                self.assertTrue(channel[bit])
                self.assertEqual(
                    1,
                    sum(channel[: len(constants.GPIO_PINS_BY_BIT)]),
                )
                self.assertEqual(channel[-1], channel[block.item_count - 1])

        with self.assertRaisesRegex(ValueError, "D6 through D13"):
            block.channel(5)
        with self.assertRaisesRegex(TypeError, "D6 through D13"):
            block.channel(True)

    def test_timestamp_reconstruction_uses_one_two_tick_snapshot_period(
        self,
    ) -> None:
        first_sample_index = 123_456
        first_tick = first_sample_index * constants.GPIO_SAMPLE_PERIOD_TICKS
        block = GPIOBlock(
            run_id=9,
            sequence=11,
            first_sample_ticks=first_tick,
            payload=bytes(constants.GPIO_DATA_PAYLOAD_SIZE),
            flags=FrameFlag.GAP_BEFORE | FrameFlag.OVERRUN_BEFORE,
        )

        self.assertEqual(first_sample_index, block.first_sample_index)
        self.assertEqual(first_tick, block.sample_ticks(0))
        self.assertEqual(
            first_tick
            + (constants.GPIO_SAMPLES_PER_FRAME - 1)
            * constants.GPIO_SAMPLE_PERIOD_TICKS,
            block.sample_ticks(-1),
        )
        self.assertEqual(
            first_tick + constants.FRAME_COVERAGE_TICKS,
            block.end_tick_exclusive,
        )
        with self.assertRaisesRegex(IndexError, "GPIO sample index"):
            block.sample_ticks(constants.GPIO_SAMPLES_PER_FRAME)

    def test_strict_mode_reports_gpio_gap_with_current_block_attached(self) -> None:
        transport = InMemoryTransport(GpioGapDevice())
        with ThingDAQ.open(transport, strict=True) as daq:
            daq.configure(adc=False, gpio=True, source=Source.SYNTHETIC)
            daq.start()
            first = daq.read_block()
            self.assertIsInstance(first, GPIOBlock)
            assert isinstance(first, GPIOBlock)
            self.assertEqual(0, first.sequence)

            with self.assertRaises(UnexpectedStreamGapError) as raised:
                daq.read_block()

            self.assertIsInstance(raised.exception.block, GPIOBlock)
            self.assertEqual(FrameKind.GPIO_DATA, raised.exception.gap.kind)
            self.assertEqual(1, raised.exception.gap.missing_frames)
            self.assertEqual(
                constants.GPIO_SAMPLES_PER_FRAME,
                raised.exception.gap.missing_items,
            )
            self.assertEqual(2, raised.exception.block.sequence)
            self.assertEqual(
                2 * constants.FRAME_COVERAGE_TICKS,
                raised.exception.block.first_sample_ticks,
            )
            self.assertTrue(raised.exception.gap.firmware_reported)
            self.assertTrue(raised.exception.gap.firmware_overrun)

    def test_physical_and_synthetic_info_decode_the_same_gpio_wire_layout(
        self,
    ) -> None:
        physical = DeviceInfo(
            device_state=DeviceState.IDLE,
            build_id="thingdaq-0123456789abcdef",
            hardware_serial=12_345_670,
            firmware_version=(0, 7, 0),
            board_id=BoardId.TEENSY_40,
            mcu_id=McuId.IMXRT1062,
            supported_stream_mask=StreamMask.GPIO,
            supported_source_mask=1 << int(Source.HARDWARE),
            supported_configuration_mask=ConfigurationProfile.HARDWARE_GPIO,
            capability_bits=(
                Capability.GPIO_STREAM
                | Capability.HARDWARE_SOURCE
                | Capability.RESET_STATS
                | Capability.PING
                | Capability.GPIO_CAPTURE_DIAGNOSTIC
            ),
            gpio_capture_diagnostic_mode=(
                GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
            ),
            gpio_capture_diagnostic_flags=(
                GpioCaptureDiagnosticFlag.AVAILABLE
                | GpioCaptureDiagnosticFlag.DECLARATION_VALID
            ),
        )
        synthetic = DeviceInfo(
            device_state=DeviceState.IDLE,
            build_id="synthetic-gpio-layout",
            supported_stream_mask=StreamMask.GPIO,
            supported_source_mask=1 << int(Source.SYNTHETIC),
            supported_configuration_mask=ConfigurationProfile.SYNTHETIC_GPIO,
            applied_source=Source.SYNTHETIC,
            capability_bits=(
                Capability.GPIO_STREAM
                | Capability.SYNTHETIC_SOURCE
                | Capability.RESET_STATS
                | Capability.PING
            ),
        )

        decoded_physical = DeviceInfo.from_payload(physical.to_payload())
        decoded_synthetic = DeviceInfo.from_payload(synthetic.to_payload())

        self.assertTrue(decoded_physical.supports_source(Source.HARDWARE))
        self.assertFalse(decoded_physical.supports_source(Source.SYNTHETIC))
        self.assertTrue(decoded_synthetic.supports_source(Source.SYNTHETIC))
        self.assertFalse(decoded_synthetic.supports_source(Source.HARDWARE))
        self.assertTrue(
            decoded_physical.supports_capability(Capability.GPIO_CAPTURE_DIAGNOSTIC)
        )
        self.assertFalse(
            decoded_synthetic.supports_capability(Capability.GPIO_CAPTURE_DIAGNOSTIC)
        )

        for decoded in (decoded_physical, decoded_synthetic):
            with self.subTest(source_mask=decoded.supported_source_mask):
                capabilities = decoded.capabilities
                self.assertEqual(tuple(range(6, 14)), capabilities.gpio_pin_map)
                self.assertEqual(4_000_000, capabilities.gpio_sample_rate_hz)
                self.assertEqual(2, capabilities.gpio_sample_period_ticks)
                self.assertEqual(8, capabilities.gpio_packed_width_bits)
                self.assertEqual(0, capabilities.gpio_pit_channel)
                self.assertEqual(2, capabilities.gpio_edma_channel)


if __name__ == "__main__":
    unittest.main()
