"""Tests for the reusable transport, simulated device, and public facade."""

from __future__ import annotations

import unittest

from teensy_daq import (
    AdcBlock,
    ByteTransport,
    ChecksumAlgorithm,
    Configuration,
    DeviceCommandError,
    DeviceState,
    ErrorCode,
    FrameFlag,
    FrameKind,
    GpioBlock,
    InMemoryTransport,
    SimulatedDevice,
    SimulatorInputError,
    Source,
    StreamMask,
    TeensyDAQ,
    TransportClosedError,
    decode_frame,
    decode_response,
    encode_frame,
    synthetic_adc0_code,
    synthetic_adc1_code,
    synthetic_gpio_byte,
)
from teensy_daq._generated import protocol_constants as constants


class SimulatedDeviceTests(unittest.TestCase):
    def test_boot_transition_is_explicit_bounded_and_idempotent(self) -> None:
        device = SimulatedDevice(auto_boot=False)

        self.assertEqual(DeviceState.BOOT, device.state)
        device.finish_boot()
        self.assertEqual(DeviceState.IDLE, device.state)
        device.finish_boot()
        self.assertEqual(DeviceState.IDLE, device.state)

        with self.assertRaises(SimulatorInputError):
            device.receive(b"x" * (device.max_receive_bytes + 1))

    def test_request_batch_limit_returns_busy_without_applying_extra_work(
        self,
    ) -> None:
        device = SimulatedDevice(max_requests_per_receive=1)
        first = encode_frame(FrameKind.INFO_REQUEST, request_id=1)
        second = encode_frame(FrameKind.INFO_REQUEST, request_id=2)

        responses = device.receive(first + second)
        decoded = [decode_response(decode_frame(response)) for response in responses]

        self.assertEqual(2, len(decoded))
        self.assertTrue(decoded[0].ok)
        self.assertFalse(decoded[1].ok)
        self.assertEqual(ErrorCode.BUSY, decoded[1].error_code)


class TeensyDAQControlTests(unittest.TestCase):
    def test_info_status_and_stop_are_idempotent_over_partial_io(self) -> None:
        transport = InMemoryTransport(read_chunk_size=5, write_chunk_size=2)
        daq = TeensyDAQ.open(transport, read_size=11)

        first_info = daq.info()
        second_info = daq.info()
        initial_status = daq.status()

        self.assertEqual(first_info, second_info)
        self.assertEqual(DeviceState.IDLE, first_info.device_state)
        self.assertTrue(first_info.supports_source(Source.SYNTHETIC))
        self.assertFalse(first_info.supports_source(Source.HARDWARE))
        self.assertEqual(DeviceState.IDLE, initial_status.device_state)
        self.assertEqual(StreamMask.NONE, initial_status.stream_mask)
        self.assertEqual(DeviceState.IDLE, daq.stop())
        self.assertEqual(DeviceState.IDLE, daq.stop())

        with self.assertRaises(DeviceCommandError) as raised:
            daq.start()
        self.assertEqual(ErrorCode.INVALID_STATE, raised.exception.error_code)
        self.assertEqual(0, transport.device.run_id)

        daq.close()
        self.assertFalse(transport.is_open)

    def test_configuration_is_atomic_and_simulator_rejects_hardware_source(
        self,
    ) -> None:
        with TeensyDAQ.simulated() as daq:
            applied = daq.configure(adc=True, gpio=False)
            self.assertEqual(StreamMask.ADC, applied.stream_mask)
            self.assertEqual(Source.SYNTHETIC, applied.source)

            unsupported = Configuration(
                stream_mask=StreamMask.GPIO,
                source=Source.HARDWARE,
            )
            with self.assertRaises(DeviceCommandError) as raised:
                daq.configure(unsupported)
            self.assertEqual(
                ErrorCode.UNSUPPORTED_CONFIGURATION,
                raised.exception.error_code,
            )

            status = daq.status()
            self.assertEqual(DeviceState.CONFIGURED, status.device_state)
            self.assertEqual(StreamMask.ADC, status.stream_mask)
            self.assertEqual(Source.SYNTHETIC, status.source)

            unsupported_checksum = Configuration(
                stream_mask=StreamMask.ADC,
                source=Source.SYNTHETIC,
                data_checksum_algorithm=ChecksumAlgorithm.CRC32C,
            )
            with self.assertRaises(DeviceCommandError) as checksum_error:
                daq.configure(unsupported_checksum)
            self.assertEqual(
                ErrorCode.UNSUPPORTED_CHECKSUM,
                checksum_error.exception.error_code,
            )

    def test_start_rejects_reentry_and_allocates_monotonic_run_ids(self) -> None:
        with TeensyDAQ.simulated() as daq:
            daq.configure()
            first_run = daq.start()

            with self.assertRaises(DeviceCommandError) as raised:
                daq.start()
            self.assertEqual(ErrorCode.INVALID_STATE, raised.exception.error_code)
            self.assertEqual(first_run, daq.run_id)

            daq.stop()
            daq.configure()
            second_run = daq.start()

            self.assertEqual(first_run + 1, second_run)


class TeensyDAQStreamingTests(unittest.TestCase):
    def test_both_streams_have_independent_sequences_timestamps_and_patterns(
        self,
    ) -> None:
        transport = InMemoryTransport(read_chunk_size=17, write_chunk_size=3)
        with TeensyDAQ.open(transport, read_size=31) as daq:
            daq.configure(adc=True, gpio=True)
            run_id = daq.start()
            blocks = list(daq.blocks(4))

            self.assertEqual(
                [AdcBlock, GpioBlock, AdcBlock, GpioBlock],
                [type(block) for block in blocks],
            )
            first_adc, first_gpio, second_adc, second_gpio = blocks
            assert isinstance(first_adc, AdcBlock)
            assert isinstance(first_gpio, GpioBlock)
            assert isinstance(second_adc, AdcBlock)
            assert isinstance(second_gpio, GpioBlock)

            self.assertEqual([0, 0, 1, 1], [block.sequence for block in blocks])
            self.assertEqual(
                [
                    0,
                    0,
                    constants.FRAME_COVERAGE_TICKS,
                    constants.FRAME_COVERAGE_TICKS,
                ],
                [block.first_sample_ticks for block in blocks],
            )
            self.assertTrue(first_adc.flags & FrameFlag.SYNTHETIC)
            self.assertTrue(first_adc.flags & FrameFlag.EPOCH_START)
            self.assertTrue(first_gpio.flags & FrameFlag.EPOCH_START)
            self.assertEqual(FrameFlag.SYNTHETIC, second_adc.flags)
            self.assertEqual(FrameFlag.SYNTHETIC, second_gpio.flags)
            self.assertTrue(all(block.run_id == run_id for block in blocks))

            self.assertEqual((0, 1), first_adc.pair(0))
            adc_index = constants.ADC_PAIRS_PER_FRAME
            self.assertEqual(
                (
                    synthetic_adc0_code(adc_index),
                    synthetic_adc1_code(adc_index),
                ),
                second_adc.pair(0),
            )
            self.assertEqual(0, first_gpio.sample(0))
            self.assertEqual(
                synthetic_gpio_byte(constants.GPIO_SAMPLES_PER_FRAME),
                second_gpio.sample(0),
            )

            status = daq.status()
            self.assertEqual(DeviceState.RUNNING, status.device_state)
            self.assertEqual(2, status.adc_frames_emitted)
            self.assertEqual(2, status.gpio_frames_emitted)
            self.assertEqual(0, status.adc_items_dropped)
            self.assertEqual(0, status.gpio_items_dropped)
            self.assertEqual(0, status.parser_errors)
            self.assertEqual(0, status.transport_errors)

            self.assertEqual(DeviceState.IDLE, daq.stop())
            idle_status = daq.status()
            self.assertEqual(DeviceState.IDLE, idle_status.device_state)
            self.assertEqual(StreamMask.NONE, idle_status.stream_mask)
            self.assertEqual(2, idle_status.adc_frames_emitted)
            self.assertEqual(2, idle_status.gpio_frames_emitted)

            daq.configure(adc=True, gpio=False)
            self.assertEqual(run_id + 1, daq.start())
            restarted = daq.read_block()
            self.assertIsInstance(restarted, AdcBlock)
            self.assertEqual(0, restarted.sequence)
            self.assertEqual(0, restarted.first_sample_ticks)
            self.assertTrue(restarted.flags & FrameFlag.EPOCH_START)
            reset_status = daq.status()
            self.assertEqual(1, reset_status.adc_frames_emitted)
            self.assertEqual(0, reset_status.gpio_frames_emitted)

    def test_context_manager_stops_and_closes_after_user_failure(self) -> None:
        transport = InMemoryTransport()

        with (
            self.assertRaisesRegex(RuntimeError, "user failure"),
            TeensyDAQ.open(transport) as daq,
        ):
            daq.configure()
            daq.start()
            raise RuntimeError("user failure")

        self.assertEqual(DeviceState.IDLE, transport.device.state)
        self.assertFalse(transport.is_open)
        with self.assertRaises(TransportClosedError):
            transport.read(1)


class TransportBoundaryTests(unittest.TestCase):
    def test_in_memory_transport_satisfies_public_byte_transport_protocol(
        self,
    ) -> None:
        transport = InMemoryTransport()

        self.assertIsInstance(transport, ByteTransport)
        transport.close()
        transport.close()
        self.assertFalse(transport.is_open)


if __name__ == "__main__":
    unittest.main()
