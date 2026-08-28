"""Focused tests for the synchronous public API completed in Phase 02."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from teensy_daq import (
    ADCBlock,
    AdcConverter,
    BoardId,
    Capability,
    ChecksumAlgorithm,
    DAQConfiguration,
    DAQStateError,
    DeviceCapabilities,
    DeviceInfo,
    DeviceState,
    DiscoveredDevice,
    FirmwareCounters,
    Frame,
    FrameFlag,
    FrameKind,
    HostCounters,
    InMemoryTransport,
    LossCounters,
    LossOrigin,
    McuId,
    SerialPortCandidate,
    SimulatedDevice,
    Source,
    Status,
    StreamGap,
    StreamMask,
    TeensyDAQ,
    UnexpectedStreamGapError,
    decode_frame,
    encode_frame,
)
from teensy_daq._generated import protocol_constants as constants


class PhysicalInfoDevice(SimulatedDevice):
    """Simulator command peer with a physical identity for open-selection tests."""

    def __init__(self, hardware_serial: int) -> None:
        super().__init__()
        self.hardware_serial = hardware_serial

    def _handle_info(self, request: Frame) -> bytes:
        info = DeviceInfo(
            device_state=self.state,
            build_id="tdaq-0123456789abcdef",
            hardware_serial=self.hardware_serial,
            firmware_version=(0, 3, 0),
            board_id=BoardId.TEENSY_40,
            mcu_id=McuId.IMXRT1062,
            capability_bits=(
                Capability.ADC_STREAM
                | Capability.GPIO_STREAM
                | Capability.HARDWARE_SOURCE
                | Capability.SYNTHETIC_SOURCE
                | Capability.RESET_STATS
                | Capability.PING
            ),
        )
        return self._success_response(request, info.to_payload())


class FirmwareGapDevice(SimulatedDevice):
    """Skip ADC sequence one and mark sequence two as a firmware overrun."""

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
            and frame.header.kind is FrameKind.ADC_DATA
            and frame.header.sequence == 1
        ):
            self._gap_injected = True
            self._adc_items_dropped += constants.ADC_PAIRS_PER_FRAME
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


class StartBurstTransport(InMemoryTransport):
    """Append three ADC frames behind START to force two host queue evictions."""

    def __init__(self) -> None:
        super().__init__()
        self._burst_added = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        request = decode_frame(bytes(data))
        written = super().write(data)
        if request.header.kind is FrameKind.START_REQUEST and not self._burst_added:
            self._burst_added = True
            with self._lock:
                for _ in range(3):
                    wire = self.device.next_data_frame()
                    assert wire is not None
                    self._pending.extend(wire)
        return written


class PublicModelTests(unittest.TestCase):
    def test_canonical_models_validate_and_preserve_phase01_alias_behavior(
        self,
    ) -> None:
        with TeensyDAQ.simulated() as daq:
            info = daq.info()
            self.assertIsInstance(info, DeviceInfo)
            self.assertIsInstance(info.capabilities, DeviceCapabilities)
            self.assertTrue(info.capabilities.supports_source(Source.SYNTHETIC))

            configuration = daq.configure(adc=True, gpio=False)
            self.assertIsInstance(configuration, DAQConfiguration)
            daq.start()
            block = daq.read_block()
            self.assertIsInstance(block, ADCBlock)
            assert isinstance(block, ADCBlock)
            self.assertEqual((0, 1), block.pair(0))
            first_sample = next(block.interleaved())
            self.assertEqual(AdcConverter.ADC0, first_sample.converter)
            self.assertEqual("A0", first_sample.pin)
            daq.stop()

            generation = daq.reset_stats()
            status = daq.status()
            self.assertEqual(generation, status.stats_generation)
            self.assertIsInstance(status.counters, FirmwareCounters)
            counters = daq.loss_counters(refresh=False)
            self.assertIsInstance(counters, LossCounters)
            self.assertIsInstance(counters.host, HostCounters)
            self.assertFalse(counters.has_loss)

        with self.assertRaises(ValueError):
            DAQConfiguration(StreamMask.NONE, Source.SYNTHETIC)
        with self.assertRaises(ValueError):
            Status(
                DeviceState.IDLE,
                StreamMask.ADC,
                Source.SYNTHETIC,
                ChecksumAlgorithm.ADLER32,
            )
        with self.assertRaises(ValueError):
            HostCounters(host_block_queue_drops=-1)

    def test_public_state_errors_are_explicit_before_illegal_commands(self) -> None:
        with TeensyDAQ.simulated() as daq:
            with self.assertRaises(DAQStateError) as idle_start:
                daq.start()
            self.assertEqual(DeviceState.IDLE, idle_start.exception.state)

            daq.configure()
            daq.start()
            with self.assertRaises(DAQStateError) as running_configure:
                daq.configure()
            self.assertEqual(DeviceState.RUNNING, running_configure.exception.state)


class PublicOpenTests(unittest.TestCase):
    def test_hardware_serial_selection_reopens_the_current_port_and_reprobes_info(
        self,
    ) -> None:
        hardware_serial = 12345670
        candidate = SerialPortCandidate(
            port="COM19",
            vid=0x16C0,
            pid=0x0483,
            serial_number=str(hardware_serial),
            product="Teensy DAQ",
        )
        discovered = DiscoveredDevice(
            candidate=candidate,
            info=DeviceInfo(
                device_state=DeviceState.IDLE,
                build_id="tdaq-0123456789abcdef",
                hardware_serial=hardware_serial,
                firmware_version=(0, 3, 0),
                board_id=BoardId.TEENSY_40,
                mcu_id=McuId.IMXRT1062,
                capability_bits=(
                    Capability.ADC_STREAM
                    | Capability.GPIO_STREAM
                    | Capability.HARDWARE_SOURCE
                    | Capability.SYNTHETIC_SOURCE
                    | Capability.RESET_STATS
                    | Capability.PING
                ),
            ),
        )
        opened: list[str] = []

        def open_transport(port: str) -> InMemoryTransport:
            opened.append(port)
            return InMemoryTransport(PhysicalInfoDevice(hardware_serial))

        with (
            patch(
                "teensy_daq.client.discover_devices",
                return_value=(discovered,),
            ),
            TeensyDAQ.open(
                hardware_serial=hardware_serial,
                serial_transport_factory=open_transport,
            ) as daq,
        ):
            self.assertEqual(["COM19"], opened)
            device_info = daq.device_info
            self.assertIsNotNone(device_info)
            assert device_info is not None
            self.assertEqual(hardware_serial, device_info.hardware_serial)
            applied = daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
            )
            self.assertIsInstance(applied, DAQConfiguration)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            self.assertEqual(DeviceState.RUNNING, daq.status().device_state)
            daq.stop()
            self.assertGreater(daq.reset_stats(), 0)
            self.assertGreaterEqual(daq.reader_counters.responses_matched, 6)


class PublicGapPolicyTests(unittest.TestCase):
    def test_production_mode_emits_firmware_gap_then_current_block(self) -> None:
        transport = InMemoryTransport(FirmwareGapDevice())
        with TeensyDAQ.open(transport) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            items = list(daq.blocks(2))

            self.assertEqual([ADCBlock, StreamGap, ADCBlock], [type(x) for x in items])
            gap = items[1]
            assert isinstance(gap, StreamGap)
            self.assertEqual(LossOrigin.FIRMWARE, gap.origin)
            self.assertTrue(gap.firmware_reported)
            self.assertTrue(gap.firmware_overrun)
            self.assertEqual(0, gap.host_queue_drops)
            self.assertEqual(1, gap.missing_frames)
            counters = daq.loss_counters()
            self.assertEqual(1, counters.observed_stream_gaps)
            self.assertEqual(
                constants.ADC_PAIRS_PER_FRAME,
                counters.firmware.adc_items_dropped,
            )
            self.assertEqual(0, counters.host.host_block_queue_drops)

    def test_strict_mode_raises_with_gap_and_current_block_attached(self) -> None:
        transport = InMemoryTransport(FirmwareGapDevice())
        with TeensyDAQ.open(transport, strict=True) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            with self.assertRaises(UnexpectedStreamGapError) as raised:
                daq.read_block()

            self.assertEqual(LossOrigin.FIRMWARE, raised.exception.gap.origin)
            self.assertEqual(2, raised.exception.block.sequence)
            counters = daq.loss_counters()
            self.assertEqual(
                constants.ADC_PAIRS_PER_FRAME,
                counters.firmware.adc_items_dropped,
            )
            self.assertEqual(0, counters.host.host_block_queue_drops)

    def test_host_queue_loss_is_never_reported_as_firmware_loss(self) -> None:
        transport = StartBurstTransport()
        with TeensyDAQ.open(transport, max_buffered_blocks=1) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            for _ in range(1_000):
                if daq.reader_counters.host_block_queue_drops == 2:
                    break
                time.sleep(0.001)
            else:
                self.fail("reader did not account for the injected queue evictions")

            items = list(daq.blocks(1))
            self.assertEqual([StreamGap, ADCBlock], [type(item) for item in items])
            gap = items[0]
            assert isinstance(gap, StreamGap)
            self.assertEqual(LossOrigin.HOST_QUEUE, gap.origin)
            self.assertFalse(gap.firmware_reported)
            self.assertFalse(gap.firmware_overrun)
            self.assertEqual(2, gap.host_queue_drops)
            self.assertEqual(2, daq.host_counters.host_block_queue_drops)
            counters = daq.loss_counters()
            self.assertEqual(0, counters.firmware.items_dropped)
            self.assertEqual(2, counters.host.host_block_queue_drops)

    def test_strict_host_queue_loss_raises_without_firmware_attribution(self) -> None:
        transport = StartBurstTransport()
        with TeensyDAQ.open(
            transport,
            strict=True,
            max_buffered_blocks=1,
        ) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            for _ in range(1_000):
                if daq.reader_counters.host_block_queue_drops == 2:
                    break
                time.sleep(0.001)
            else:
                self.fail("reader did not account for the injected queue evictions")

            with self.assertRaises(UnexpectedStreamGapError) as raised:
                daq.read_block()

            gap = raised.exception.gap
            self.assertEqual(LossOrigin.HOST_QUEUE, gap.origin)
            self.assertFalse(gap.firmware_reported)
            self.assertFalse(gap.firmware_overrun)
            self.assertEqual(2, gap.host_queue_drops)
            self.assertEqual(2, raised.exception.block.sequence)
            counters = daq.loss_counters()
            self.assertEqual(0, counters.firmware.items_dropped)
            self.assertEqual(2, counters.host.host_block_queue_drops)
            self.assertEqual(1, counters.observed_stream_gaps)


if __name__ == "__main__":
    unittest.main()
