"""Focused typed-codec and opt-in protocol-v2 client tests."""

from __future__ import annotations

import struct
import unittest
from collections import deque
from pathlib import Path
from threading import RLock

from thingdaq import (
    ADCBlock,
    ConfigurationEncoding,
    DAQConfiguration,
    DeviceCapabilityError,
    FrameEncoding,
    InMemoryTransport,
    RawFallbackReason,
    Source,
    StreamMask,
    ThingDAQ,
    V2EncodingNotNegotiatedError,
    V2RLEValidationError,
    count_rle_runs,
    decode_rle_payload,
    decode_v2_data_block,
    decode_v2_frame,
    encode_rle_payload,
    encode_v2_data_frame,
    encode_v2_frame,
)
from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.cli import build_parser
from thingdaq.protocol_v2 import IncrementalV2FrameParser, V2Frame

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "protocol" / "fixtures-v2"


def _fixture(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


class _V2FixtureTransport:
    """Small stateful v2 peer used only to exercise the public host lifecycle."""

    def __init__(self, *, rle_capable: bool = True) -> None:
        self._parser = IncrementalV2FrameParser()
        self._pending = bytearray()
        self._stream_frames: deque[bytes] = deque()
        self._lock = RLock()
        self._open = True
        self._configuration_payload: bytes | None = None
        self.requests: list[constants.FrameKind] = []
        self.run_id = 7

        info = decode_v2_frame(_fixture("info-response.bin"))
        info_payload = bytearray(info.payload)
        if not rle_capable:
            capability_bits = struct.unpack_from(
                "<I",
                info_payload,
                constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
            )[0]
            struct.pack_into(
                "<I",
                info_payload,
                constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
                capability_bits & ~int(constants.Capability.RLE_STREAMING),
            )
        self._info_payload = bytes(info_payload)
        self._stop_payload = decode_v2_frame(_fixture("stop-response.bin")).payload

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def write(self, data: bytes | bytearray | memoryview) -> int:
        incoming = bytes(data)
        with self._lock:
            if not self._open:
                raise RuntimeError("transport is closed")
            for request in self._parser.feed(incoming):
                self.requests.append(request.header.kind)
                response = self._response(request)
                if response is not None:
                    self._pending.extend(response)
        return len(incoming)

    def read(self, size: int) -> bytes:
        with self._lock:
            if not self._open:
                raise RuntimeError("transport is closed")
            returned = min(size, len(self._pending))
            chunk = bytes(self._pending[:returned])
            del self._pending[:returned]
            return chunk

    def flush(self) -> None:
        return None

    def close(self) -> None:
        with self._lock:
            self._open = False
            self._pending.clear()

    def request_stream_frame(self) -> None:
        with self._lock:
            if self._stream_frames:
                self._pending.extend(self._stream_frames.popleft())

    def queue_stream_bytes(self, *frames: bytes) -> None:
        with self._lock:
            self._stream_frames.extend(frames)

    def _response(self, request: V2Frame) -> bytes | None:
        request_id = request.header.request_id
        if request.header.kind is constants.FrameKind.INFO_REQUEST:
            return encode_v2_frame(
                constants.FrameKind.INFO_RESPONSE,
                self._info_payload,
                request_id=request_id,
            )
        if request.header.kind is constants.FrameKind.CONFIGURE_REQUEST:
            self._configuration_payload = request.payload
            return encode_v2_frame(
                constants.FrameKind.CONFIGURE_RESPONSE,
                b"\0\0\0\0" + request.payload,
                request_id=request_id,
            )
        if request.header.kind is constants.FrameKind.START_REQUEST:
            if self._configuration_payload is None:
                raise AssertionError("START arrived before CONFIGURE")
            return encode_v2_frame(
                constants.FrameKind.START_RESPONSE,
                b"\0\0\0\0" + self._configuration_payload,
                run_id=self.run_id,
                request_id=request_id,
            )
        if request.header.kind is constants.FrameKind.STOP_REQUEST:
            return encode_v2_frame(
                constants.FrameKind.STOP_RESPONSE,
                self._stop_payload,
                run_id=self.run_id,
                request_id=request_id,
            )
        return None


class RLECodecTests(unittest.TestCase):
    def test_bytes_like_codec_is_canonical_and_bounded(self) -> None:
        logical = memoryview(b"A" * 17 + b"B" * 3 + b"C" * 12)
        encoded = encode_rle_payload(logical, item_size=1, max_items=32)
        self.assertEqual(
            struct.pack("<HcHcHc", 17, b"A", 3, b"B", 12, b"C"),
            encoded,
        )
        self.assertEqual(3, count_rle_runs(logical, item_size=1, max_items=32))
        self.assertEqual(
            bytes(logical),
            decode_rle_payload(
                bytearray(encoded),
                item_size=1,
                item_count=32,
                max_items=32,
            ),
        )

        with self.assertRaisesRegex(V2RLEValidationError, "advertised item bound"):
            decode_rle_payload(
                struct.pack("<Hc", 2, b"A"),
                item_size=1,
                item_count=1,
                max_items=1,
            )

    def test_generated_rle_vectors_reconstruct_existing_block_models(self) -> None:
        for name, block_type, expected_runs in (
            ("adc-rle-data.bin", ADCBlock, 3),
            ("gpio-rle-data.bin", object, 3),
        ):
            with self.subTest(name=name):
                frame = decode_v2_frame(_fixture(name))
                block = decode_v2_data_block(
                    frame,
                    negotiated_encoding=ConfigurationEncoding.RLE_AUTO,
                )
                self.assertIsInstance(block, block_type)
                diagnostics = block.encoding_diagnostics
                self.assertIsNotNone(diagnostics)
                assert diagnostics is not None
                self.assertEqual(FrameEncoding.RLE, diagnostics.frame_encoding)
                self.assertEqual(expected_runs, diagnostics.run_count)
                self.assertEqual(4048, diagnostics.decoded_bytes)
                self.assertGreater(diagnostics.savings, 4000)
                self.assertEqual(frame.payload, diagnostics.encoded_payload)
                self.assertIsNone(diagnostics.raw_fallback_reason)

    def test_adaptive_encoding_selects_rle_only_when_strictly_smaller(self) -> None:
        constant_adc = struct.pack("<HH", 123, 456) * constants.ADC_PAIRS_PER_FRAME
        rle_wire = encode_v2_data_frame(
            constants.FrameKind.ADC_DATA,
            constant_adc,
            configuration_encoding=ConfigurationEncoding.RLE_AUTO,
            flags=constants.FrameFlag.EPOCH_START,
            run_id=1,
            sequence=0,
            first_sample_ticks=0,
        )
        rle_frame = decode_v2_frame(rle_wire)
        self.assertEqual(FrameEncoding.RLE, rle_frame.header.encoding)
        self.assertEqual(
            constant_adc,
            decode_v2_data_block(
                rle_frame,
                negotiated_encoding=ConfigurationEncoding.RLE_AUTO,
            ).payload,
        )

        alternating_gpio = bytes(index & 1 for index in range(4048))
        raw_wire = encode_v2_data_frame(
            constants.FrameKind.GPIO_DATA,
            alternating_gpio,
            configuration_encoding=ConfigurationEncoding.RLE_AUTO,
            flags=constants.FrameFlag.EPOCH_START,
            run_id=1,
            sequence=0,
            first_sample_ticks=0,
        )
        raw_frame = decode_v2_frame(raw_wire)
        self.assertEqual(FrameEncoding.RAW, raw_frame.header.encoding)
        raw_block = decode_v2_data_block(
            raw_frame,
            negotiated_encoding=ConfigurationEncoding.RLE_AUTO,
        )
        diagnostics = raw_block.encoding_diagnostics
        assert diagnostics is not None
        self.assertIs(raw_block.payload, diagnostics.encoded_payload)
        self.assertEqual(0, diagnostics.savings)
        self.assertEqual(4048, diagnostics.run_count)
        self.assertEqual(
            RawFallbackReason.RLE_NOT_SMALLER,
            diagnostics.raw_fallback_reason,
        )

    def test_raw_negotiation_rejects_an_rle_selector(self) -> None:
        frame = decode_v2_frame(_fixture("adc-rle-data.bin"))
        with self.assertRaises(V2EncodingNotNegotiatedError):
            decode_v2_data_block(
                frame,
                negotiated_encoding=ConfigurationEncoding.RAW,
            )


class V2PublicClientTests(unittest.TestCase):
    def test_default_configuration_bytes_and_cli_remain_raw(self) -> None:
        configuration = DAQConfiguration(
            stream_mask=StreamMask.ADC | StreamMask.GPIO,
            source=Source.SYNTHETIC,
        )
        self.assertEqual(ConfigurationEncoding.RAW, configuration.encoding)
        self.assertEqual(
            b"\x03\x01\x01\x00\x00\x10\x00\x00", configuration.to_payload()
        )
        parsed = build_parser().parse_args(["configure", "--simulate"])
        self.assertEqual("raw", parsed.encoding)
        parsed = build_parser().parse_args(
            ["configure", "--simulate", "--encoding", "rle-auto"]
        )
        self.assertEqual("rle-auto", parsed.encoding)

    def test_v1_session_rejects_explicit_rle_with_typed_error(self) -> None:
        daq = ThingDAQ.simulated(synchronization_retry_delay=0)
        try:
            with self.assertRaisesRegex(
                DeviceCapabilityError,
                "protocol-v2 RLE session",
            ):
                daq.configure(
                    adc=True,
                    gpio=False,
                    source=Source.SYNTHETIC,
                    encoding=ConfigurationEncoding.RLE_AUTO,
                )
        finally:
            daq.close()

        with self.assertRaisesRegex(
            DeviceCapabilityError,
            "did not provide protocol-v2 INFO",
        ):
            ThingDAQ.open(
                InMemoryTransport(),
                encoding=ConfigurationEncoding.RLE_AUTO,
                command_timeout=0.02,
                shutdown_timeout=0.1,
                synchronization_attempts=2,
                synchronization_retry_delay=0,
            )

    def test_capability_is_required_before_configure_is_sent(self) -> None:
        transport = _V2FixtureTransport(rle_capable=False)
        with self.assertRaisesRegex(DeviceCapabilityError, "RLE_STREAMING"):
            ThingDAQ.open(
                transport,
                encoding=ConfigurationEncoding.RLE_AUTO,
                command_timeout=0.2,
                shutdown_timeout=0.2,
                synchronization_retry_delay=0,
            )
        self.assertNotIn(constants.FrameKind.CONFIGURE_REQUEST, transport.requests)

    def test_mixed_rle_raw_run_uses_logical_continuity_and_stops(self) -> None:
        transport = _V2FixtureTransport()
        rle_payload = decode_v2_frame(_fixture("adc-rle-data.bin")).payload
        raw_payload = decode_v2_frame(_fixture("adc-raw-fallback-data.bin")).payload
        transport.queue_stream_bytes(
            encode_v2_frame(
                constants.FrameKind.ADC_DATA,
                rle_payload,
                flags=constants.FrameFlag.SYNTHETIC | constants.FrameFlag.EPOCH_START,
                encoding=FrameEncoding.RLE,
                run_id=transport.run_id,
                sequence=0,
                first_sample_ticks=0,
                item_count=constants.ADC_PAIRS_PER_FRAME,
            ),
            encode_v2_frame(
                constants.FrameKind.ADC_DATA,
                raw_payload,
                flags=constants.FrameFlag.SYNTHETIC,
                encoding=FrameEncoding.RAW,
                run_id=transport.run_id,
                sequence=1,
                first_sample_ticks=constants.FRAME_COVERAGE_TICKS,
                item_count=constants.ADC_PAIRS_PER_FRAME,
            ),
        )

        with ThingDAQ.open(
            transport,
            encoding=ConfigurationEncoding.RLE_AUTO,
            command_timeout=0.2,
            block_timeout=0.2,
            shutdown_timeout=0.2,
            synchronization_retry_delay=0,
        ) as daq:
            applied = daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
                encoding=ConfigurationEncoding.RLE_AUTO,
            )
            self.assertEqual(ConfigurationEncoding.RLE_AUTO, applied.encoding)
            self.assertEqual(transport.run_id, daq.start())
            first = daq.read_block(timeout=0.2)
            second = daq.read_block(timeout=0.2)
            self.assertIsInstance(first, ADCBlock)
            self.assertIsInstance(second, ADCBlock)
            assert isinstance(first, ADCBlock)
            assert isinstance(second, ADCBlock)
            self.assertEqual(0, first.sequence)
            self.assertEqual(1, second.sequence)
            self.assertEqual(first.end_tick_exclusive, second.first_sample_ticks)
            self.assertEqual(
                FrameEncoding.RLE, first.encoding_diagnostics.frame_encoding
            )
            self.assertEqual(
                FrameEncoding.RAW, second.encoding_diagnostics.frame_encoding
            )
            self.assertEqual(
                RawFallbackReason.RLE_NOT_SMALLER,
                second.encoding_diagnostics.raw_fallback_reason,
            )

        self.assertIn(constants.FrameKind.STOP_REQUEST, transport.requests)

    def test_decode_rejections_recover_before_deterministic_stop(self) -> None:
        transport = _V2FixtureTransport()
        valid_payload = decode_v2_frame(_fixture("adc-rle-data.bin")).payload
        valid = encode_v2_frame(
            constants.FrameKind.ADC_DATA,
            valid_payload,
            flags=constants.FrameFlag.SYNTHETIC | constants.FrameFlag.EPOCH_START,
            encoding=FrameEncoding.RLE,
            run_id=transport.run_id,
            sequence=0,
            first_sample_ticks=0,
            item_count=constants.ADC_PAIRS_PER_FRAME,
        )
        transport.queue_stream_bytes(
            _fixture("adc-rle-checksum-corruption.bin")
            + _fixture("adc-rle-truncated-item.bin")
            + valid
        )

        with ThingDAQ.open(
            transport,
            encoding=ConfigurationEncoding.RLE_AUTO,
            command_timeout=0.2,
            block_timeout=0.2,
            shutdown_timeout=0.2,
            synchronization_retry_delay=0,
        ) as daq:
            daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
                encoding=ConfigurationEncoding.RLE_AUTO,
            )
            daq.start()
            block = daq.read_block(timeout=0.2)
            self.assertIsInstance(block, ADCBlock)
            self.assertEqual(1, daq.parser_counters.checksum_errors)
            self.assertEqual(1, daq.parser_counters.payload_errors)

        self.assertIn(constants.FrameKind.STOP_REQUEST, transport.requests)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
