"""Deterministic adversarial and partition tests for the stream parser."""

from __future__ import annotations

import json
import random
import struct
import unittest
import zlib
from pathlib import Path

from thingdone_daq import IncrementalFrameParser
from thingdone_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
MANIFEST = json.loads((FIXTURE_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
FIXTURES = tuple(
    (FIXTURE_DIRECTORY / entry["file"]).read_bytes() for entry in MANIFEST["fixtures"]
)


def _rechecksum(frame: bytes | bytearray) -> bytes:
    result = bytearray(frame)
    checksum = zlib.adler32(result[: -constants.TRAILER_SIZE]) & 0xFFFFFFFF
    struct.pack_into("<I", result, len(result) - constants.TRAILER_SIZE, checksum)
    return bytes(result)


def _set_field(
    frame: bytes,
    field_format: str,
    offset: int,
    value: int,
    *,
    rechecksum: bool = False,
) -> bytes:
    result = bytearray(frame)
    struct.pack_into(field_format, result, offset, value)
    return _rechecksum(result) if rechecksum else bytes(result)


def _partition(data: bytes, randomizer: random.Random) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        chunk_size = randomizer.randint(1, min(5_000, len(data) - offset))
        chunks.append(data[offset : offset + chunk_size])
        offset += chunk_size
    return tuple(chunks)


class AdversarialParserTests(unittest.TestCase):
    def test_seeded_random_partitions_preserve_all_frames(self) -> None:
        expected = FIXTURES * 3
        stream = b"".join(expected)

        for seed in (0, 1, 2, 7, 19, 41, 101, 257, 1_001, 65_537):
            with self.subTest(seed=seed):
                parser = IncrementalFrameParser()
                decoded = []
                for chunk in _partition(stream, random.Random(seed)):
                    decoded.extend(parser.feed(chunk))
                    self.assertLessEqual(
                        parser.buffered_bytes,
                        parser.max_buffered_bytes,
                    )
                    self.assertLessEqual(
                        parser.high_water_mark,
                        parser.max_buffered_bytes,
                    )

                self.assertEqual(expected, tuple(frame.to_bytes() for frame in decoded))
                self.assertEqual(0, parser.buffered_bytes)
                self.assertEqual(len(expected), parser.frames_decoded)

    def test_one_chunk_can_hold_many_complete_frames(self) -> None:
        info = (FIXTURE_DIRECTORY / "info-request.bin").read_bytes()
        ping = (FIXTURE_DIRECTORY / "ping-request.bin").read_bytes()
        expected = (info, ping) * 512
        parser = IncrementalFrameParser()

        decoded = parser.feed(b"".join(expected))

        self.assertEqual(expected, tuple(frame.to_bytes() for frame in decoded))
        self.assertEqual(1_024, parser.frames_decoded)
        self.assertEqual(0, parser.buffered_bytes)
        self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)

    def test_long_noise_retains_each_possible_partial_magic_suffix(self) -> None:
        info = (FIXTURE_DIRECTORY / "info-request.bin").read_bytes()
        noise = b"\xa5" * 250_000

        for suffix_length in range(len(constants.MAGIC_BYTES)):
            with self.subTest(suffix_length=suffix_length):
                parser = IncrementalFrameParser()
                suffix = constants.MAGIC_BYTES[:suffix_length]

                self.assertEqual([], parser.feed(noise + suffix))
                self.assertEqual(suffix_length, parser.buffered_bytes)
                self.assertLessEqual(
                    parser.high_water_mark,
                    parser.max_buffered_bytes,
                )

                continuation = (
                    info
                    if suffix_length == 0
                    else constants.MAGIC_BYTES[suffix_length:]
                    + info[len(constants.MAGIC_BYTES) :]
                )
                decoded = parser.feed(continuation)

                self.assertEqual([info], [frame.to_bytes() for frame in decoded])
                self.assertEqual(0, parser.buffered_bytes)
                self.assertEqual(len(noise), parser.bytes_discarded)

    def test_each_structural_or_checksum_corruption_reaches_next_frame(self) -> None:
        info = (FIXTURE_DIRECTORY / "info-request.bin").read_bytes()
        adc = (FIXTURE_DIRECTORY / "adc-data.bin").read_bytes()
        following = (FIXTURE_DIRECTORY / "ping-request.bin").read_bytes()

        bad_magic = bytearray(info)
        bad_magic[0] ^= 0x01
        bad_checksum = bytearray(info)
        bad_checksum[-1] ^= 0x80
        corruptions = {
            "magic": bytes(bad_magic),
            "version": _set_field(
                info,
                "<B",
                constants.HEADER_VERSION_OFFSET,
                constants.PROTOCOL_VERSION + 1,
            ),
            "kind": _set_field(
                info,
                "<B",
                constants.HEADER_KIND_OFFSET,
                0x7E,
            ),
            "flags": _set_field(
                info,
                "<H",
                constants.HEADER_FLAGS_OFFSET,
                0x4000,
            ),
            "header length": _set_field(
                info,
                "<H",
                constants.HEADER_HEADER_LENGTH_OFFSET,
                constants.HEADER_SIZE - 1,
            ),
            "checksum ID": _set_field(
                info,
                "<B",
                constants.HEADER_CHECKSUM_ALGORITHM_OFFSET,
                constants.ChecksumAlgorithm.CRC32C,
            ),
            "header reserved": _set_field(
                info,
                "<B",
                constants.HEADER_RESERVED_OFFSET,
                1,
            ),
            "total length": _set_field(
                info,
                "<I",
                constants.HEADER_TOTAL_LENGTH_OFFSET,
                0xFFFFFFFF,
            ),
            "payload length": _set_field(
                info,
                "<I",
                constants.HEADER_PAYLOAD_LENGTH_OFFSET,
                1,
            ),
            "control run ID": _set_field(
                info,
                "<I",
                constants.HEADER_RUN_ID_OFFSET,
                1,
            ),
            "control sequence": _set_field(
                info,
                "<I",
                constants.HEADER_SEQUENCE_OFFSET,
                1,
            ),
            "request ID": _set_field(
                info,
                "<I",
                constants.HEADER_REQUEST_ID_OFFSET,
                0,
            ),
            "control timestamp": _set_field(
                info,
                "<Q",
                constants.HEADER_FIRST_SAMPLE_TICKS_OFFSET,
                8,
            ),
            "control count": _set_field(
                info,
                "<I",
                constants.HEADER_ITEM_COUNT_OFFSET,
                1,
            ),
            "data count": _set_field(
                adc,
                "<I",
                constants.HEADER_ITEM_COUNT_OFFSET,
                constants.ADC_PAIRS_PER_FRAME - 1,
            ),
            "checksum trailer": bytes(bad_checksum),
        }

        for name, corrupt in corruptions.items():
            with self.subTest(corruption=name):
                parser = IncrementalFrameParser()
                decoded = parser.feed(corrupt + following)

                self.assertEqual([following], [frame.to_bytes() for frame in decoded])
                self.assertEqual(0, parser.buffered_bytes)
                self.assertGreaterEqual(parser.resynchronizations, 1)
                self.assertLessEqual(
                    parser.high_water_mark,
                    parser.max_buffered_bytes,
                )

    def test_embedded_magic_survives_and_edit_faults_resynchronize(self) -> None:
        gpio = bytearray((FIXTURE_DIRECTORY / "gpio-data.bin").read_bytes())
        embedded_at = constants.HEADER_SIZE + 777
        gpio[embedded_at : embedded_at + len(constants.MAGIC_BYTES)] = (
            constants.MAGIC_BYTES
        )
        embedded = _rechecksum(gpio)
        following = (FIXTURE_DIRECTORY / "get-status-request.bin").read_bytes()

        parser = IncrementalFrameParser()
        decoded = parser.feed(embedded[: embedded_at + 2])
        decoded.extend(parser.feed(embedded[embedded_at + 2 :]))
        self.assertEqual([embedded], [frame.to_bytes() for frame in decoded])

        edited_frames = {
            "truncation": embedded[:-7],
            "deletion": embedded[:1_500] + embedded[1_501:],
            "duplication": embedded[:1_500] + embedded[1_499:1_500] + embedded[1_500:],
        }
        for name, edited in edited_frames.items():
            with self.subTest(edit=name):
                parser = IncrementalFrameParser()
                recovered = parser.feed(edited + following)

                self.assertEqual(
                    [following],
                    [frame.to_bytes() for frame in recovered],
                )
                self.assertEqual(0, parser.buffered_bytes)
                self.assertGreater(parser.corruption_events, 0)

    def test_sequence_wrap_frames_are_not_mistaken_for_corruption(self) -> None:
        adc = (FIXTURE_DIRECTORY / "adc-data.bin").read_bytes()
        before_wrap = _set_field(
            adc,
            "<H",
            constants.HEADER_FLAGS_OFFSET,
            constants.FrameFlag.SYNTHETIC,
            rechecksum=True,
        )
        before_wrap = _set_field(
            before_wrap,
            "<I",
            constants.HEADER_SEQUENCE_OFFSET,
            0xFFFFFFFF,
            rechecksum=True,
        )
        before_wrap = _set_field(
            before_wrap,
            "<Q",
            constants.HEADER_FIRST_SAMPLE_TICKS_OFFSET,
            8,
            rechecksum=True,
        )
        after_wrap = _set_field(
            before_wrap,
            "<I",
            constants.HEADER_SEQUENCE_OFFSET,
            0,
            rechecksum=True,
        )
        after_wrap = _set_field(
            after_wrap,
            "<Q",
            constants.HEADER_FIRST_SAMPLE_TICKS_OFFSET,
            16,
            rechecksum=True,
        )
        parser = IncrementalFrameParser()

        decoded = []
        stream = before_wrap + after_wrap
        for chunk in _partition(stream, random.Random(0x5E0A)):
            decoded.extend(parser.feed(chunk))

        self.assertEqual([0xFFFFFFFF, 0], [frame.header.sequence for frame in decoded])
        self.assertEqual(0, parser.corruption_events)
        self.assertEqual(0, parser.buffered_bytes)

    def test_seeded_fault_fuzz_makes_bounded_forward_progress(self) -> None:
        ping = (FIXTURE_DIRECTORY / "ping-request.bin").read_bytes()
        sentinels = (
            (FIXTURE_DIRECTORY / "info-request.bin").read_bytes(),
            (FIXTURE_DIRECTORY / "start-request.bin").read_bytes(),
            (FIXTURE_DIRECTORY / "get-status-request.bin").read_bytes(),
        )

        for seed in range(32):
            with self.subTest(seed=seed):
                randomizer = random.Random(0xDA0_000 + seed)
                parts: list[bytes] = []
                expected: list[bytes] = []
                for iteration in range(24):
                    noise_length = randomizer.randint(0, 96)
                    parts.append(
                        bytes(randomizer.randrange(0xEF) for _ in range(noise_length))
                    )
                    fault = randomizer.choice(
                        (
                            "magic",
                            "version",
                            "flags",
                            "checksum",
                            "delete",
                            "duplicate",
                            "truncate",
                        )
                    )
                    damaged = bytearray(ping)
                    if fault == "magic":
                        damaged[0] ^= 1
                    elif fault == "version":
                        damaged[constants.HEADER_VERSION_OFFSET] = 0xFF
                    elif fault == "flags":
                        struct.pack_into(
                            "<H",
                            damaged,
                            constants.HEADER_FLAGS_OFFSET,
                            0x0100,
                        )
                    elif fault == "checksum":
                        damaged[-1] ^= 1
                    elif fault == "delete":
                        del damaged[constants.HEADER_SIZE + 2]
                    elif fault == "duplicate":
                        damaged.insert(
                            constants.HEADER_SIZE + 2,
                            damaged[constants.HEADER_SIZE + 1],
                        )
                    else:
                        del damaged[-randomizer.randint(1, 12) :]
                    parts.append(bytes(damaged))

                    sentinel = sentinels[iteration % len(sentinels)]
                    parts.append(sentinel)
                    expected.append(sentinel)

                stream = b"".join(parts)
                parser = IncrementalFrameParser()
                decoded = []
                received = 0
                for chunk in _partition(stream, randomizer):
                    decoded.extend(parser.feed(chunk))
                    received += len(chunk)
                    self.assertEqual(received, parser.bytes_received)
                    self.assertLessEqual(
                        parser.buffered_bytes,
                        parser.max_buffered_bytes,
                    )
                    self.assertLessEqual(
                        parser.high_water_mark,
                        parser.max_buffered_bytes,
                    )

                accepted_bytes = sum(len(frame) for frame in expected)
                self.assertEqual(expected, [frame.to_bytes() for frame in decoded])
                self.assertEqual(0, parser.buffered_bytes)
                self.assertEqual(
                    len(stream),
                    parser.bytes_discarded + accepted_bytes,
                )
                self.assertGreater(parser.corruption_events, 0)
                self.assertGreater(parser.resynchronizations, 0)


if __name__ == "__main__":
    unittest.main()
