"""Focused tests for protocol-v1 encoding, validation, and stream parsing."""

from __future__ import annotations

import json
import struct
import unittest
import zlib
from pathlib import Path

from teensy_daq import (
    ChecksumMismatchError,
    CommandResponse,
    ErrorCode,
    FrameValidationError,
    IncrementalFrameParser,
    compute_checksum,
    decode_frame,
    decode_message,
    encode_frame,
)
from teensy_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
MANIFEST = json.loads((FIXTURE_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))


def _with_adler32(frame: bytearray) -> bytes:
    struct.pack_into("<I", frame, len(frame) - 4, zlib.adler32(frame[:-4]) & 0xFFFFFFFF)
    return bytes(frame)


class ProtocolCoreTests(unittest.TestCase):
    def test_checksum_dispatch_uses_rfc1950_adler32(self) -> None:
        self.assertEqual(0x00000001, compute_checksum(b""))
        self.assertEqual(0x091E01DE, compute_checksum(b"123456789"))
        with self.assertRaisesRegex(FrameValidationError, "unsupported checksum"):
            compute_checksum(b"data", constants.ChecksumAlgorithm.CRC32C)

    def test_every_golden_frame_decodes_and_reencodes_exactly(self) -> None:
        for entry in MANIFEST["fixtures"]:
            with self.subTest(kind=entry["kind"]):
                wire = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
                frame = decode_frame(wire)

                encoded = encode_frame(
                    frame.header.kind,
                    frame.payload,
                    flags=frame.header.flags,
                    checksum_algorithm=frame.header.checksum_algorithm,
                    run_id=frame.header.run_id,
                    sequence=frame.header.sequence,
                    request_id=frame.header.request_id,
                    first_sample_ticks=frame.header.first_sample_ticks,
                    item_count=frame.header.item_count,
                )

                self.assertEqual(wire, frame.to_bytes())
                self.assertEqual(wire, encoded)

    def test_every_golden_checksum_covers_header_and_payload(self) -> None:
        for entry in MANIFEST["fixtures"]:
            wire = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            body = wire[: -constants.TRAILER_SIZE]
            trailer_checksum = struct.unpack_from("<I", wire, len(body))[0]
            offsets = {
                0,
                constants.HEADER_SIZE - 1,
            }
            if entry["payload_length"]:
                offsets.update({constants.HEADER_SIZE, len(body) - 1})

            with self.subTest(kind=entry["kind"], region="complete body"):
                self.assertEqual(trailer_checksum, compute_checksum(body))
            for offset in sorted(offsets):
                with self.subTest(kind=entry["kind"], mutated_offset=offset):
                    mutated = bytearray(body)
                    mutated[offset] ^= 0x01
                    self.assertNotEqual(trailer_checksum, compute_checksum(mutated))

    def test_every_golden_frame_accepts_every_two_chunk_split(self) -> None:
        for entry in MANIFEST["fixtures"]:
            wire = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            for split_point in range(len(wire) + 1):
                with self.subTest(kind=entry["kind"], split_point=split_point):
                    parser = IncrementalFrameParser()
                    decoded = parser.feed(wire[:split_point])
                    decoded.extend(parser.feed(wire[split_point:]))

                    self.assertEqual([wire], [frame.to_bytes() for frame in decoded])
                    self.assertEqual(1, parser.frames_decoded)
                    self.assertEqual(0, parser.buffered_bytes)

    def test_incremental_parser_accepts_arbitrary_read_sizes_and_many_frames(
        self,
    ) -> None:
        expected = [
            (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            for entry in MANIFEST["fixtures"]
        ]
        stream = b"".join(expected)

        for chunk_size in (1, 3, 47, 511, 4096, len(stream)):
            with self.subTest(chunk_size=chunk_size):
                parser = IncrementalFrameParser()
                decoded = []
                for offset in range(0, len(stream), chunk_size):
                    decoded.extend(parser.feed(stream[offset : offset + chunk_size]))

                self.assertEqual(expected, [frame.to_bytes() for frame in decoded])
                self.assertEqual(len(expected), parser.frames_decoded)
                self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)
                self.assertEqual(0, parser.buffered_bytes)

    def test_parser_recovers_from_garbage_partial_magic_and_bad_checksum(self) -> None:
        info = (FIXTURE_DIRECTORY / "info-request.bin").read_bytes()
        status = (FIXTURE_DIRECTORY / "get-status-request.bin").read_bytes()
        corrupt = bytearray(info)
        corrupt[-1] ^= 0x80

        for partial_length in range(1, len(constants.MAGIC_BYTES)):
            with self.subTest(partial_magic_bytes=partial_length):
                parser = IncrementalFrameParser()
                self.assertEqual(
                    [],
                    parser.feed(b"garbage" + constants.MAGIC_BYTES[:partial_length]),
                )
                frames = parser.feed(bytes(corrupt) + status)

                self.assertEqual([status], [frame.to_bytes() for frame in frames])
                self.assertGreaterEqual(parser.errors, 1)
                self.assertGreaterEqual(parser.bytes_discarded, len(b"garbage"))

    def test_parser_storage_is_bounded_even_for_large_garbage_chunks(self) -> None:
        parser = IncrementalFrameParser()
        info = (FIXTURE_DIRECTORY / "info-request.bin").read_bytes()

        self.assertEqual([], parser.feed(b"x" * 100_000 + constants.MAGIC_BYTES[:2]))

        self.assertEqual(2, parser.buffered_bytes)
        self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)
        frames = parser.feed(
            constants.MAGIC_BYTES[2:] + info[len(constants.MAGIC_BYTES) :]
        )
        self.assertEqual([info], [frame.to_bytes() for frame in frames])
        self.assertEqual(0, parser.buffered_bytes)

    def test_decode_rejects_checksum_and_typed_reserved_field_corruption(self) -> None:
        wire = bytearray((FIXTURE_DIRECTORY / "configure-request.bin").read_bytes())
        wire[-1] ^= 1
        with self.assertRaises(ChecksumMismatchError):
            decode_frame(wire)

        wire = bytearray((FIXTURE_DIRECTORY / "configure-request.bin").read_bytes())
        wire[constants.HEADER_SIZE + constants.CONFIGURE_REQUEST_RESERVED_OFFSET] = 1
        with self.assertRaises(FrameValidationError) as raised:
            decode_frame(_with_adler32(wire))
        self.assertEqual(ErrorCode.INVALID_PAYLOAD, raised.exception.error_code)

    def test_overrun_dependency_and_reserved_capability_bits_fail_closed(self) -> None:
        adc = bytearray((FIXTURE_DIRECTORY / "adc-data.bin").read_bytes())
        struct.pack_into(
            "<H",
            adc,
            constants.HEADER_FLAGS_OFFSET,
            int(
                constants.FrameFlag.SYNTHETIC
                | constants.FrameFlag.EPOCH_START
                | constants.FrameFlag.OVERRUN_BEFORE
            ),
        )
        with self.assertRaisesRegex(FrameValidationError, "requires GAP_BEFORE"):
            decode_frame(_with_adler32(adc))

        info = bytearray((FIXTURE_DIRECTORY / "info-response.bin").read_bytes())
        struct.pack_into(
            "<I",
            info,
            constants.HEADER_SIZE + constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
            constants.KNOWN_CAPABILITY_MASK | 0x80000000,
        )
        with self.assertRaisesRegex(FrameValidationError, "reserved capability"):
            decode_frame(_with_adler32(info))

    def test_reset_stats_and_ping_vectors_preserve_generation_and_nonce(self) -> None:
        reset = decode_frame(
            (FIXTURE_DIRECTORY / "reset-stats-response.bin").read_bytes()
        )
        ping_request = decode_frame(
            (FIXTURE_DIRECTORY / "ping-request.bin").read_bytes()
        )
        ping_response = decode_frame(
            (FIXTURE_DIRECTORY / "ping-response.bin").read_bytes()
        )

        reset_message = decode_message(reset)
        ping_message = decode_message(ping_response)
        self.assertIsInstance(reset_message, CommandResponse)
        self.assertIsInstance(ping_message, CommandResponse)
        assert isinstance(reset_message, CommandResponse)
        assert isinstance(ping_message, CommandResponse)
        self.assertEqual(3, reset_message.value)
        self.assertEqual(0x0123456789ABCDEF, ping_message.value)
        self.assertEqual(ping_request.payload, ping_response.payload[4:])

    def test_parser_rejects_implausible_length_before_waiting_for_body(self) -> None:
        invalid = bytearray((FIXTURE_DIRECTORY / "info-request.bin").read_bytes())
        valid = (FIXTURE_DIRECTORY / "get-status-request.bin").read_bytes()
        struct.pack_into(
            "<I", invalid, constants.HEADER_TOTAL_LENGTH_OFFSET, 0xFFFFFFFF
        )
        parser = IncrementalFrameParser()

        frames = parser.feed(invalid + valid)

        self.assertEqual([valid], [frame.to_bytes() for frame in frames])
        self.assertGreaterEqual(parser.errors, 1)
        self.assertEqual(0, parser.buffered_bytes)


if __name__ == "__main__":
    unittest.main()
