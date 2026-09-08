"""Focused tests for strict synthetic validation and reusable soak metrics."""

from __future__ import annotations

import unittest

from thingdone_daq import (
    ADCBlock,
    DeviceState,
    FrameKind,
    GPIOBlock,
    InMemoryTransport,
    SimulatedDevice,
    SyntheticPatternError,
    ThingDAQ,
    UnexpectedStreamValidationError,
    decode_frame,
    encode_frame,
    run_synthetic_soak,
    synthetic_adc_payload,
    synthetic_gpio_payload,
    validate_synthetic_adc_payload,
    validate_synthetic_gpio_payload,
)
from thingdone_daq._generated import protocol_constants as constants


class FormulaCorruptDevice(SimulatedDevice):
    """Emit one structurally valid ADC frame with the wrong ramp value."""

    def __init__(self) -> None:
        super().__init__()
        self._corrupted = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None or self._corrupted:
            return wire
        frame = decode_frame(wire)
        if frame.header.kind is not FrameKind.ADC_DATA:
            return wire
        payload = bytearray(frame.payload)
        payload[0] ^= 0x02
        self._corrupted = True
        return encode_frame(
            frame.header.kind,
            payload,
            flags=frame.header.flags,
            checksum_algorithm=frame.header.checksum_algorithm,
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            item_count=frame.header.item_count,
        )


class RecordingReadIntoTransport(InMemoryTransport):
    """Record which caller-owned storage objects service reader I/O."""

    def __init__(self) -> None:
        super().__init__(read_chunk_size=17, write_chunk_size=3)
        self.read_buffer_ids: set[int] = set()

    def readinto(self, buffer: bytearray | memoryview) -> int:
        view = memoryview(buffer)
        try:
            self.read_buffer_ids.add(id(view.obj))
        finally:
            view.release()
        return super().readinto(buffer)


class SyntheticPayloadValidationTests(unittest.TestCase):
    def test_cyclic_validators_cover_wraps_and_report_first_bad_item(self) -> None:
        adc_start = (1 << (constants.ADC_RESOLUTION_BITS - 1)) - 3
        adc_payload = synthetic_adc_payload(adc_start, 9)
        validate_synthetic_adc_payload(adc_payload, adc_start, 9)
        bad_adc = bytearray(adc_payload)
        bad_adc[4 * 5] ^= 0x02
        with self.assertRaisesRegex(SyntheticPatternError, f"ADC pair {adc_start + 5}"):
            validate_synthetic_adc_payload(bad_adc, adc_start, 9)

        gpio_start = 253
        gpio_payload = synthetic_gpio_payload(gpio_start, 9)
        validate_synthetic_gpio_payload(gpio_payload, gpio_start, 9)
        bad_gpio = bytearray(gpio_payload)
        bad_gpio[4] ^= 0x01
        with self.assertRaisesRegex(
            SyntheticPatternError,
            f"GPIO sample {gpio_start + 4}",
        ):
            validate_synthetic_gpio_payload(bad_gpio, gpio_start, 9)

    def test_block_payload_views_are_zero_copy_and_adc_pairs_are_lazy(self) -> None:
        adc = ADCBlock(
            run_id=1,
            sequence=0,
            first_sample_ticks=0,
            payload=synthetic_adc_payload(0),
        )
        gpio = GPIOBlock(
            run_id=1,
            sequence=0,
            first_sample_ticks=0,
            payload=synthetic_gpio_payload(0),
        )

        self.assertIs(adc.payload, adc.payload_view.obj)
        self.assertIs(gpio.payload, gpio.payload_view.obj)
        pairs = adc.pairs()
        self.assertEqual((0, 1), next(pairs))
        self.assertEqual((2, 3), next(pairs))
        self.assertEqual(0, gpio.payload_view[0])
        self.assertEqual(255, gpio.payload_view[255])


class StrictStreamingTests(unittest.TestCase):
    def test_strict_facade_rejects_a_formula_error_with_valid_framing(self) -> None:
        transport = InMemoryTransport(FormulaCorruptDevice())
        with ThingDAQ.open(transport, strict=True) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            with self.assertRaises(UnexpectedStreamValidationError) as raised:
                daq.read_block()

            self.assertEqual("synthetic_pattern", raised.exception.category)

    def test_explicit_health_check_rejects_firmware_transport_errors(self) -> None:
        transport = InMemoryTransport()
        with ThingDAQ.open(transport, strict=True) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            transport.device.record_transport_error()

            with self.assertRaises(UnexpectedStreamValidationError) as raised:
                daq.validate_stream_health()

            self.assertEqual(
                "firmware_transport_errors",
                raised.exception.category,
            )


class SyntheticSoakTests(unittest.TestCase):
    def test_soak_stops_and_returns_to_idle_after_validation_failure(self) -> None:
        transport = InMemoryTransport(
            FormulaCorruptDevice(),
            read_chunk_size=19,
            write_chunk_size=2,
        )
        with ThingDAQ.open(transport) as daq:
            with self.assertRaises(UnexpectedStreamValidationError) as raised:
                run_synthetic_soak(
                    daq,
                    frame_count=2,
                    status_interval=None,
                    track_memory=False,
                )

            self.assertEqual("synthetic_pattern", raised.exception.category)
            self.assertEqual(DeviceState.IDLE, daq.state)
            self.assertEqual(DeviceState.IDLE, transport.device.state)

    def test_soak_reports_rates_latency_queues_memory_and_exact_counters(self) -> None:
        transport = RecordingReadIntoTransport()
        with ThingDAQ.open(transport, read_size=64 * 1024) as daq:
            metrics = run_synthetic_soak(
                daq,
                frame_count=6,
                status_interval=None,
            )

            self.assertEqual(DeviceState.IDLE, daq.state)
            self.assertEqual(DeviceState.IDLE, metrics.final_status.device_state)
            self.assertEqual(3, metrics.adc.frame_count)
            self.assertEqual(3, metrics.gpio.frame_count)
            self.assertEqual(
                3 * constants.ADC_DATA_PAYLOAD_SIZE,
                metrics.adc.payload_bytes,
            )
            self.assertEqual(6 * constants.DATA_FRAME_BYTES, metrics.framed_bytes)
            self.assertGreater(metrics.payload_bytes_per_second, 0.0)
            self.assertGreater(metrics.framed_bytes_per_second, 0.0)
            self.assertGreaterEqual(metrics.command_latency.count, 4)
            self.assertGreaterEqual(
                metrics.command_latency.maximum_seconds,
                metrics.command_latency.p99_seconds,
            )
            self.assertEqual(64 * 1024, metrics.queues.reusable_read_buffer_bytes)
            self.assertLessEqual(
                metrics.queues.parser_high_water_bytes,
                constants.DATA_FRAME_BYTES + len(constants.MAGIC_BYTES) - 1,
            )
            self.assertTrue(metrics.memory.enabled)
            self.assertGreaterEqual(metrics.memory.peak_bytes, 0)
            self.assertGreater(metrics.reader_counters.readinto_calls, 0)
            self.assertEqual(1, len(transport.read_buffer_ids))
            self.assertTrue(metrics.reconciliation.ok)
            self.assertEqual(
                metrics.reconciliation.adc_firmware_frames_emitted,
                metrics.reconciliation.adc_wire_frames_received,
            )
            self.assertEqual(
                metrics.reconciliation.gpio_firmware_frames_emitted,
                metrics.reconciliation.gpio_wire_frames_received,
            )


if __name__ == "__main__":
    unittest.main()
