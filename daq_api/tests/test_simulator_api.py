"""Tests for the reusable transport, simulated device, and public facade."""

from __future__ import annotations

import unittest

from thingdone_daq import (
    AdcBlock,
    ByteTransport,
    Capability,
    ChecksumAlgorithm,
    Configuration,
    DeviceCommandError,
    DeviceState,
    ErrorCode,
    FrameFlag,
    FrameKind,
    GpioBlock,
    Info,
    InMemoryTransport,
    SimulatedDevice,
    SimulatorInputError,
    Source,
    StreamMask,
    ThingDAQ,
    TransportClosedError,
    UnexpectedMessageError,
    decode_frame,
    decode_response,
    encode_frame,
    synthetic_adc0_code,
    synthetic_adc1_code,
    synthetic_gpio_byte,
)
from thingdone_daq._generated import protocol_constants as constants


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

    def test_ping_echoes_nonce_and_reset_stats_advances_generation(self) -> None:
        device = SimulatedDevice()
        nonce = 0x0123456789ABCDEF
        info_wire = encode_frame(FrameKind.INFO_REQUEST, request_id=1)
        ping_wire = encode_frame(
            FrameKind.PING_REQUEST,
            nonce.to_bytes(8, "little"),
            request_id=2,
        )
        reset_wire = encode_frame(FrameKind.RESET_STATS_REQUEST, request_id=3)

        info = decode_response(decode_frame(device.receive(info_wire)[0]))
        ping = decode_response(decode_frame(device.receive(ping_wire)[0]))
        reset = decode_response(decode_frame(device.receive(reset_wire)[0]))

        self.assertIsInstance(info.value, Info)
        assert isinstance(info.value, Info)
        self.assertEqual(nonce, ping.value)
        self.assertEqual(2, reset.value)
        self.assertEqual(2, device.status().stats_generation)
        self.assertTrue(info.value.supports_capability(Capability.PING))
        self.assertTrue(info.value.supports_capability(Capability.RESET_STATS))

    def test_duplicate_request_ids_are_rejected_until_a_new_session(self) -> None:
        device = SimulatedDevice()
        request = encode_frame(FrameKind.INFO_REQUEST, request_id=7)

        first = decode_response(decode_frame(device.receive(request)[0]))
        duplicate = decode_response(decode_frame(device.receive(request)[0]))

        self.assertTrue(first.ok)
        self.assertFalse(duplicate.ok)
        self.assertEqual(ErrorCode.INVALID_REQUEST_ID, duplicate.error_code)
        self.assertEqual(1, device.status().bad_request_ids)

        device.receive(request[:17])
        device.begin_host_session()
        reopened = decode_response(decode_frame(device.receive(request)[0]))
        self.assertTrue(reopened.ok)
        self.assertEqual(DeviceState.IDLE, device.state)

    def test_in_memory_transport_preflights_batched_response_capacity(self) -> None:
        device = SimulatedDevice()
        transport = InMemoryTransport(
            device,
            max_pending_bytes=(
                constants.DATA_FRAME_BYTES + constants.MAX_CONTROL_FRAME_BYTES
            ),
        )
        configuration = Configuration(
            stream_mask=StreamMask.ADC,
            source=Source.SYNTHETIC,
            data_checksum_algorithm=ChecksumAlgorithm.ADLER32,
            data_frame_bytes=constants.DATA_FRAME_BYTES,
        )
        device.receive(
            encode_frame(
                FrameKind.CONFIGURE_REQUEST,
                configuration.to_payload(),
                request_id=1,
            )
        )
        device.receive(encode_frame(FrameKind.START_REQUEST, request_id=2))
        transport.request_stream_frame()
        self.assertEqual(1, len(transport.read(1)))

        first_request = encode_frame(FrameKind.GET_STATUS_REQUEST, request_id=3)
        second_request = encode_frame(FrameKind.GET_STATUS_REQUEST, request_id=4)
        batch = first_request + second_request
        accepted = transport.write(batch)
        self.assertEqual(constants.MIN_FRAME_BYTES, accepted)
        self.assertEqual(0, transport.write(batch[accepted:]))

        self.assertEqual(
            constants.DATA_FRAME_BYTES - 1,
            len(transport.read(constants.DATA_FRAME_BYTES - 1)),
        )
        first_response = decode_frame(transport.read(constants.MAX_CONTROL_FRAME_BYTES))
        self.assertEqual(3, first_response.header.request_id)
        self.assertEqual(len(second_request), transport.write(batch[accepted:]))
        second_response = decode_frame(
            transport.read(constants.MAX_CONTROL_FRAME_BYTES)
        )
        self.assertEqual(4, second_response.header.request_id)


class ThingDAQControlTests(unittest.TestCase):
    def test_info_status_and_stop_are_idempotent_over_partial_io(self) -> None:
        transport = InMemoryTransport(read_chunk_size=5, write_chunk_size=2)
        daq = ThingDAQ.open(transport, read_size=11)

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
        with ThingDAQ.simulated() as daq:
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

            for checksum in (
                ChecksumAlgorithm.CRC32C,
                ChecksumAlgorithm.CRC32_ISO_HDLC,
            ):
                applied_checksum = daq.configure(
                    Configuration(
                        stream_mask=StreamMask.ADC,
                        source=Source.SYNTHETIC,
                        data_checksum_algorithm=checksum,
                    )
                )
                self.assertEqual(checksum, applied_checksum.data_checksum_algorithm)
                self.assertEqual(checksum, daq.status().data_checksum_algorithm)

    def test_start_rejects_reentry_and_allocates_monotonic_run_ids(self) -> None:
        with ThingDAQ.simulated() as daq:
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

    def test_state_transitions_and_queries_are_stable_in_every_state(self) -> None:
        with ThingDAQ.simulated(read_chunk_size=7, write_chunk_size=3) as daq:
            idle_info = daq.info()
            self.assertEqual(DeviceState.IDLE, idle_info.device_state)
            self.assertEqual(daq.status(), daq.status())

            first_configuration = daq.configure(adc=True, gpio=False)
            second_configuration = daq.configure(adc=False, gpio=True)
            self.assertEqual(StreamMask.ADC, first_configuration.stream_mask)
            self.assertEqual(StreamMask.GPIO, second_configuration.stream_mask)
            self.assertEqual(DeviceState.CONFIGURED, daq.info().device_state)
            self.assertEqual(daq.status(), daq.status())

            run_id = daq.start()
            first_running_info = daq.info()
            second_running_info = daq.info()
            self.assertEqual(first_running_info, second_running_info)
            self.assertEqual(DeviceState.RUNNING, first_running_info.device_state)
            self.assertEqual(run_id, daq.run_id)

            with self.assertRaises(DeviceCommandError) as raised:
                daq.configure(adc=True, gpio=True)
            self.assertEqual(ErrorCode.INVALID_STATE, raised.exception.error_code)
            self.assertEqual(DeviceState.RUNNING, daq.status().device_state)
            active_configuration = daq.configuration
            self.assertIsNotNone(active_configuration)
            assert active_configuration is not None
            self.assertEqual(StreamMask.GPIO, active_configuration.stream_mask)

            self.assertEqual(DeviceState.IDLE, daq.stop())
            self.assertEqual(DeviceState.IDLE, daq.stop())
            self.assertEqual(DeviceState.IDLE, daq.info().device_state)
            self.assertIsNone(daq.configuration)


class ThingDAQStreamingTests(unittest.TestCase):
    def test_every_advertised_checksum_streams_through_the_shared_codec(self) -> None:
        for checksum in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            with self.subTest(checksum=checksum.name), ThingDAQ.simulated() as daq:
                applied = daq.configure(
                    Configuration(
                        stream_mask=StreamMask.ADC,
                        source=Source.SYNTHETIC,
                        data_checksum_algorithm=checksum,
                    )
                )
                run_id = daq.start()
                block = daq.read_block(timeout=0.5)

                self.assertIsInstance(block, AdcBlock)
                self.assertEqual(run_id, block.run_id)
                self.assertEqual(checksum, applied.data_checksum_algorithm)
                self.assertEqual(checksum, daq.status().data_checksum_algorithm)
                daq.stop()

    def test_active_run_identity_rejects_stale_data_blocks(self) -> None:
        with ThingDAQ.simulated() as daq:
            daq.configure(adc=True, gpio=False)
            active_run = daq.start()
            stale = AdcBlock(
                active_run + 1,
                0,
                0,
                bytes(constants.ADC_DATA_PAYLOAD_SIZE),
                FrameFlag.EPOCH_START,
            )

            with self.assertRaisesRegex(UnexpectedMessageError, "stale data run"):
                daq._queue_block(stale)

    def test_both_streams_have_independent_sequences_timestamps_and_patterns(
        self,
    ) -> None:
        transport = InMemoryTransport(read_chunk_size=17, write_chunk_size=3)
        with ThingDAQ.open(transport, read_size=31) as daq:
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

            data_blocks = (first_adc, first_gpio, second_adc, second_gpio)
            self.assertEqual([0, 0, 1, 1], [block.sequence for block in data_blocks])
            self.assertEqual(
                [
                    0,
                    0,
                    constants.FRAME_COVERAGE_TICKS,
                    constants.FRAME_COVERAGE_TICKS,
                ],
                [block.first_sample_ticks for block in data_blocks],
            )
            self.assertTrue(first_adc.flags & FrameFlag.SYNTHETIC)
            self.assertTrue(first_adc.flags & FrameFlag.EPOCH_START)
            self.assertTrue(first_gpio.flags & FrameFlag.EPOCH_START)
            self.assertEqual(FrameFlag.SYNTHETIC, second_adc.flags)
            self.assertEqual(FrameFlag.SYNTHETIC, second_gpio.flags)
            self.assertTrue(all(block.run_id == run_id for block in data_blocks))

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
            assert isinstance(restarted, AdcBlock)
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
            ThingDAQ.open(transport) as daq,
        ):
            daq.configure()
            daq.start()
            raise RuntimeError("user failure")

        self.assertEqual(DeviceState.IDLE, transport.device.state)
        self.assertFalse(transport.is_open)
        with self.assertRaises(TransportClosedError):
            transport.read(1)

    def test_context_manager_stops_and_closes_after_success(self) -> None:
        transport = InMemoryTransport(read_chunk_size=13, write_chunk_size=5)

        with ThingDAQ.open(transport, read_size=17) as daq:
            daq.configure()
            daq.start()
            self.assertIsInstance(daq.read_block(), AdcBlock)

        self.assertEqual(DeviceState.IDLE, transport.device.state)
        self.assertFalse(transport.is_open)
        with self.assertRaises(TransportClosedError):
            transport.write(b"request")


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
