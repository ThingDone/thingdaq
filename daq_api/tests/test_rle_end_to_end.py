"""Independent client, loss, alignment, NumPy, and cleanup RLE tests."""

from __future__ import annotations

import importlib.util
import unittest
from dataclasses import replace

from thingdaq import (
    ADCBlock,
    AlignedInterval,
    ConfigurationEncoding,
    DeviceCapabilityError,
    ExperimentalSimulatedDevice,
    ExperimentalSourcePattern,
    FrameEncoding,
    GPIOBlock,
    InMemoryTransport,
    Source,
    StreamGap,
    ThingDAQ,
    TimestampAligner,
    UnexpectedMessageError,
    UnexpectedStreamValidationError,
    V2Capability,
    V2Frame,
    decode_v2_data_block,
    decode_v2_frame,
    encode_v2_data_frame,
    encode_v2_frame,
    synthetic_adc_payload,
    synthetic_gpio_payload,
)
from thingdaq._generated import protocol_constants as v1_constants
from thingdaq._generated import protocol_v2_constants as v2_constants
from thingdaq.models import Info
from thingdaq.simulator import SimulatorRequest, experimental_gpio_payload

NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None


def _open_rle(
    transport: InMemoryTransport,
    *,
    strict: bool = False,
) -> ThingDAQ:
    return ThingDAQ.open(
        transport,
        strict=strict,
        encoding=ConfigurationEncoding.RLE_AUTO,
        command_timeout=0.5,
        block_timeout=0.5,
        shutdown_timeout=0.5,
        synchronization_retry_delay=0,
    )


def _raw_v2_gpio_block() -> tuple[V2Frame, GPIOBlock]:
    logical = experimental_gpio_payload(
        ExperimentalSourcePattern.HIGH_ENTROPY,
    )
    wire = encode_v2_data_frame(
        v2_constants.FrameKind.GPIO_DATA,
        logical,
        configuration_encoding=ConfigurationEncoding.RLE_AUTO,
        flags=v2_constants.FrameFlag.EPOCH_START,
        run_id=9,
        sequence=0,
        first_sample_ticks=0,
    )
    frame = decode_v2_frame(wire)
    block = decode_v2_data_block(
        frame,
        negotiated_encoding=ConfigurationEncoding.RLE_AUTO,
    )
    if not isinstance(block, GPIOBlock):  # pragma: no cover - fixed kind
        raise TypeError("GPIO frame decoded as a non-GPIO block")
    return frame, block


class _NoRLECapabilityDevice(ExperimentalSimulatedDevice):
    def _build_info(self) -> Info:
        info = super()._build_info()
        return replace(
            info,
            capability_bits=v2_constants.Capability(
                int(info.capability_bits) & ~int(v2_constants.Capability.RLE_STREAMING)
            ),
        )


class _ConfigurationEchoMismatchDevice(ExperimentalSimulatedDevice):
    def _handle_configure(self, request: SimulatorRequest) -> bytes:
        wire = super()._handle_configure(request)
        frame = decode_v2_frame(wire)
        payload = bytearray(frame.payload)
        payload[v2_constants.CONFIGURE_RESPONSE_ENCODING_OFFSET] = int(
            ConfigurationEncoding.RAW
        )
        return encode_v2_frame(
            frame.header.kind,
            payload,
            flags=frame.header.flags,
            checksum_algorithm=frame.header.checksum_algorithm,
            run_id=frame.header.run_id,
            request_id=frame.header.request_id,
        )


class _OneRLEGapDevice(ExperimentalSimulatedDevice):
    """Drop ADC sequence one and return sequence two with exact gap evidence."""

    def __init__(self) -> None:
        super().__init__(
            encoding=ConfigurationEncoding.RLE_AUTO,
            adc_pattern=ExperimentalSourcePattern.CONSTANT,
        )
        self._gap_injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None:
            return None
        frame = decode_v2_frame(wire)
        if (
            not self._gap_injected
            and frame.header.kind is v2_constants.FrameKind.ADC_DATA
            and frame.header.sequence == 1
        ):
            self._gap_injected = True
            self._adc_items_dropped += v2_constants.ADC_PAIRS_PER_FRAME
            replacement = super().next_data_frame()
            if replacement is None:  # pragma: no cover - RUNNING invariant
                raise AssertionError("gap injection could not obtain a replacement")
            frame = decode_v2_frame(replacement)
            return encode_v2_frame(
                frame.header.kind,
                frame.payload,
                flags=(
                    frame.header.flags
                    | v2_constants.FrameFlag.GAP_BEFORE
                    | v2_constants.FrameFlag.OVERRUN_BEFORE
                ),
                checksum_algorithm=frame.header.checksum_algorithm,
                encoding=frame.header.encoding,
                run_id=frame.header.run_id,
                sequence=frame.header.sequence,
                first_sample_ticks=frame.header.first_sample_ticks,
                item_count=frame.header.item_count,
            )
        return wire


class _CorruptThenRecoverDevice(ExperimentalSimulatedDevice):
    """Emit one bad-checksum frame followed by a valid frame in one read."""

    def __init__(self) -> None:
        super().__init__(
            encoding=ConfigurationEncoding.RLE_AUTO,
            adc_pattern=ExperimentalSourcePattern.CONSTANT,
        )
        self._corruption_injected = False

    def next_data_frame(self) -> bytes | None:
        first = super().next_data_frame()
        if first is None or self._corruption_injected:
            return first
        self._corruption_injected = True
        following = super().next_data_frame()
        if following is None:  # pragma: no cover - RUNNING invariant
            raise AssertionError("corruption injection could not obtain recovery data")
        corrupt = bytearray(first)
        corrupt[-1] ^= 0x80
        return bytes(corrupt) + following


class CompatibilityAndNegotiationTests(unittest.TestCase):
    def test_protocol_v1_client_device_defaults_and_formulas_remain_unchanged(
        self,
    ) -> None:
        with ThingDAQ.simulated(
            read_chunk_size=17,
            write_chunk_size=3,
            synchronization_retry_delay=0,
        ) as daq:
            info = daq.device_info
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(v1_constants.PROTOCOL_VERSION, info.protocol_version)
            applied = daq.configure()
            self.assertIs(ConfigurationEncoding.RAW, applied.encoding)
            daq.start()
            adc = daq.read_block()
            gpio = daq.read_block()

        self.assertIsInstance(adc, ADCBlock)
        self.assertIsInstance(gpio, GPIOBlock)
        assert isinstance(adc, ADCBlock)
        assert isinstance(gpio, GPIOBlock)
        self.assertEqual(synthetic_adc_payload(0), adc.payload)
        self.assertEqual(synthetic_gpio_payload(0), gpio.payload)
        self.assertIsNone(adc.encoding_diagnostics)
        self.assertIsNone(gpio.encoding_diagnostics)

    def test_v2_configuration_echo_and_mixed_rle_raw_frames_are_public(self) -> None:
        device = ExperimentalSimulatedDevice(
            encoding=ConfigurationEncoding.RLE_AUTO,
            adc_pattern=ExperimentalSourcePattern.CONSTANT,
            gpio_pattern=ExperimentalSourcePattern.HIGH_ENTROPY,
        )
        transport = InMemoryTransport(
            device,
            read_chunk_size=19,
            write_chunk_size=3,
        )
        with _open_rle(transport) as daq:
            info = daq.device_info
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(v2_constants.PROTOCOL_VERSION, info.protocol_version)
            self.assertTrue(info.capabilities.supports(V2Capability.RLE_STREAMING))
            applied = daq.configure(
                adc=True,
                gpio=True,
                source=Source.SYNTHETIC,
                encoding=ConfigurationEncoding.RLE_AUTO,
            )
            self.assertIs(ConfigurationEncoding.RLE_AUTO, applied.encoding)
            daq.start()
            adc = daq.read_block()
            gpio = daq.read_block()

            self.assertIsInstance(adc, ADCBlock)
            self.assertIsInstance(gpio, GPIOBlock)
            assert isinstance(adc, ADCBlock)
            assert isinstance(gpio, GPIOBlock)
            self.assertIs(
                FrameEncoding.RLE,
                adc.encoding_diagnostics.frame_encoding,
            )
            self.assertIs(
                FrameEncoding.RAW,
                gpio.encoding_diagnostics.frame_encoding,
            )

            aligner = TimestampAligner(max_pending_intervals=1)
            self.assertEqual((), aligner.push(adc))
            outputs = aligner.push(gpio)
            self.assertEqual(1, len(outputs))
            interval = outputs[0]
            self.assertIsInstance(interval, AlignedInterval)
            assert isinstance(interval, AlignedInterval)
            self.assertTrue(interval.complete)
            self.assertIs(adc, interval.adc)
            self.assertIs(gpio, interval.gpio)
            self.assertEqual(adc.first_sample_ticks, gpio.first_sample_ticks)

    def test_missing_rle_capability_is_rejected_before_configuration(self) -> None:
        device = _NoRLECapabilityDevice(
            encoding=ConfigurationEncoding.RLE_AUTO,
        )
        transport = InMemoryTransport(device)
        with self.assertRaisesRegex(DeviceCapabilityError, "RLE_STREAMING"):
            _open_rle(transport)
        self.assertFalse(transport.is_open)
        self.assertIs(v1_constants.DeviceState.IDLE, device.status().device_state)

        with self.assertRaises(DeviceCapabilityError):
            ThingDAQ.simulated(
                encoding=ConfigurationEncoding.RLE_AUTO,
                synchronization_retry_delay=0,
            )

    def test_mismatched_configuration_echo_closes_and_stops_the_peer(self) -> None:
        device = _ConfigurationEchoMismatchDevice(
            encoding=ConfigurationEncoding.RLE_AUTO,
        )
        transport = InMemoryTransport(device)
        daq = _open_rle(transport)
        try:
            with self.assertRaisesRegex(
                UnexpectedMessageError,
                "differs from the request",
            ):
                daq.configure(
                    source=Source.SYNTHETIC,
                    encoding=ConfigurationEncoding.RLE_AUTO,
                )
        finally:
            daq.close()
        self.assertFalse(transport.is_open)
        self.assertIs(v1_constants.DeviceState.IDLE, device.status().device_state)


class RLEContinuityAndCleanupTests(unittest.TestCase):
    def test_rle_gap_uses_logical_counts_and_recovers_to_compressed_data(self) -> None:
        device = _OneRLEGapDevice()
        transport = InMemoryTransport(device, read_chunk_size=23, write_chunk_size=5)
        with _open_rle(transport) as daq:
            daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
                encoding=ConfigurationEncoding.RLE_AUTO,
            )
            daq.start()
            first = daq.read_block()
            gap = daq.read_block()
            recovered = daq.read_block()
            losses = daq.loss_counters()

        self.assertIsInstance(first, ADCBlock)
        self.assertIsInstance(gap, StreamGap)
        self.assertIsInstance(recovered, ADCBlock)
        assert isinstance(first, ADCBlock)
        assert isinstance(gap, StreamGap)
        assert isinstance(recovered, ADCBlock)
        self.assertEqual(0, first.sequence)
        self.assertEqual(2, recovered.sequence)
        self.assertEqual(1, gap.missing_frames)
        self.assertEqual(v2_constants.ADC_PAIRS_PER_FRAME, gap.missing_items)
        self.assertEqual(
            v2_constants.FRAME_COVERAGE_TICKS,
            gap.missing_end_ticks - gap.missing_start_ticks,
        )
        self.assertIs(
            FrameEncoding.RLE,
            recovered.encoding_diagnostics.frame_encoding,
        )
        self.assertEqual(1, losses.observed_stream_gaps)
        self.assertEqual(
            v2_constants.ADC_PAIRS_PER_FRAME,
            losses.firmware.adc_items_dropped,
        )

    def test_corrupt_rle_frame_recovers_then_error_cleanup_stops_and_closes(
        self,
    ) -> None:
        device = _CorruptThenRecoverDevice()
        transport = InMemoryTransport(device, read_chunk_size=13, write_chunk_size=3)
        with (
            self.assertRaises(UnexpectedStreamValidationError),
            _open_rle(transport) as daq,
        ):
            daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
                encoding=ConfigurationEncoding.RLE_AUTO,
            )
            daq.start()
            gap = daq.read_block()
            recovered = daq.read_block()
            self.assertIsInstance(gap, StreamGap)
            self.assertIsInstance(recovered, ADCBlock)
            assert isinstance(recovered, ADCBlock)
            self.assertEqual(1, recovered.sequence)
            self.assertIs(
                FrameEncoding.RLE,
                recovered.encoding_diagnostics.frame_encoding,
            )
            self.assertEqual(1, daq.parser_counters.checksum_errors)
            daq.validate_stream_health()

        self.assertFalse(transport.is_open)
        self.assertIs(v1_constants.DeviceState.IDLE, device.status().device_state)


class RLENumPyAndZeroCopyTests(unittest.TestCase):
    def test_raw_v2_payload_is_shared_through_block_and_diagnostics(self) -> None:
        frame, block = _raw_v2_gpio_block()
        self.assertIs(FrameEncoding.RAW, frame.header.encoding)
        diagnostics = block.encoding_diagnostics
        self.assertIsNotNone(diagnostics)
        assert diagnostics is not None
        self.assertIs(frame.payload, block.payload)
        self.assertIs(block.payload, diagnostics.encoded_payload)

    @unittest.skipUnless(NUMPY_AVAILABLE, "NumPy is an optional dependency")
    def test_raw_v2_numpy_view_keeps_the_exact_payload_owner(self) -> None:
        import numpy

        _, block = _raw_v2_gpio_block()
        view = block.as_numpy()
        self.assertIs(block.payload, view.payload_owner)
        self.assertFalse(view.packed.flags.owndata)
        self.assertFalse(view.packed.flags.writeable)
        self.assertTrue(
            numpy.shares_memory(
                view.packed,
                numpy.frombuffer(block.payload, dtype=numpy.uint8),
            )
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
