"""Independent exhaustive and property-style tests for protocol-v2 RLE."""

from __future__ import annotations

import json
import math
import random
import struct
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

from thingdaq import (
    ConfigurationEncoding,
    FrameEncoding,
    IncrementalV2FrameParser,
    V2ChecksumMismatchError,
    V2FrameValidationError,
    V2RLEValidationError,
    compute_v2_checksum,
    count_rle_runs,
    decode_rle_payload,
    decode_v2_data_block,
    decode_v2_frame,
    encode_rle_payload,
    encode_v2_data_frame,
)
from thingdaq._generated import protocol_v2_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "protocol/fixtures-v2"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
_TRAILER = struct.Struct("<I")


def _shape(
    kind: constants.FrameKind,
) -> tuple[int, int, int, int, int]:
    if kind is constants.FrameKind.ADC_DATA:
        return (
            constants.ADC_BYTES_PER_PAIR,
            constants.ADC_PAIRS_PER_FRAME,
            constants.ADC_RLE_RECORD_BYTES,
            constants.ADC_RLE_MAX_SELECTED_RUNS,
            constants.ADC_RLE_MAX_SELECTED_FRAME_BYTES,
        )
    if kind is constants.FrameKind.GPIO_DATA:
        return (
            1,
            constants.GPIO_SAMPLES_PER_FRAME,
            constants.GPIO_RLE_RECORD_BYTES,
            constants.GPIO_RLE_MAX_SELECTED_RUNS,
            constants.GPIO_RLE_MAX_SELECTED_FRAME_BYTES,
        )
    raise TypeError("test data kind must be ADC_DATA or GPIO_DATA")


def _items(item_size: int) -> tuple[bytes, ...]:
    if item_size == constants.ADC_BYTES_PER_PAIR:
        return (
            struct.pack("<HH", 0x0123, 0x0456),
            struct.pack("<HH", 0x0789, 0x0ABC),
            struct.pack("<HH", 0x0357, 0x0246),
        )
    if item_size == 1:
        return (b"\x35", b"\xca", b"\x5a")
    raise ValueError("test logical item width is unsupported")


def _payload_for_runs(item_size: int, run_lengths: tuple[int, ...]) -> bytes:
    values = _items(item_size)
    return b"".join(
        values[index % len(values)] * run_length
        for index, run_length in enumerate(run_lengths)
    )


def _payload_with_run_count(
    kind: constants.FrameKind,
    run_count: int,
) -> bytes:
    item_size, item_count, _, _, _ = _shape(kind)
    base_length, longer_runs = divmod(item_count, run_count)
    if base_length == 0:
        raise ValueError("run count exceeds the logical frame item count")
    run_lengths = tuple(
        base_length + (index < longer_runs) for index in range(run_count)
    )
    payload = _payload_for_runs(item_size, run_lengths)
    if len(payload) != constants.DATA_PAYLOAD_BYTES:
        raise AssertionError("test payload did not fill one logical data frame")
    return payload


def _payload_with_uniform_runs(
    kind: constants.FrameKind,
    requested_run_length: int,
) -> tuple[bytes, int]:
    item_size, item_count, _, _, _ = _shape(kind)
    run_lengths: list[int] = []
    remaining = item_count
    while remaining:
        selected = min(requested_run_length, remaining)
        run_lengths.append(selected)
        remaining -= selected
    return (
        _payload_for_runs(item_size, tuple(run_lengths)),
        len(run_lengths),
    )


def _encode_data(
    kind: constants.FrameKind,
    payload: bytes,
    *,
    sequence: int = 0,
    encoding: ConfigurationEncoding = ConfigurationEncoding.RLE_AUTO,
) -> bytes:
    return encode_v2_data_frame(
        kind,
        payload,
        configuration_encoding=encoding,
        flags=(constants.FrameFlag.EPOCH_START if sequence == 0 else 0),
        run_id=0x524C_4501,
        sequence=sequence,
        first_sample_ticks=sequence * constants.FRAME_COVERAGE_TICKS,
    )


class RLEPayloadPropertyTests(unittest.TestCase):
    def test_every_frame_local_single_run_length_round_trips_both_widths(
        self,
    ) -> None:
        """Exercise every valid run length in both maximum logical frames."""

        for item_size, maximum_items in (
            (1, constants.GPIO_SAMPLES_PER_FRAME),
            (constants.ADC_BYTES_PER_PAIR, constants.ADC_PAIRS_PER_FRAME),
        ):
            item = _items(item_size)[0]
            for run_length in range(1, maximum_items + 1):
                logical = item * run_length
                encoded = encode_rle_payload(
                    memoryview(logical),
                    item_size=item_size,
                    max_items=maximum_items,
                )
                expected = run_length.to_bytes(2, "little") + item
                if encoded != expected:
                    self.fail(
                        f"item_size={item_size}, run_length={run_length} "
                        "did not encode as one little-endian record"
                    )
                decoded = decode_rle_payload(
                    bytearray(encoded),
                    item_size=item_size,
                    item_count=run_length,
                    max_items=maximum_items,
                )
                if decoded != logical:
                    self.fail(
                        f"item_size={item_size}, run_length={run_length} "
                        "did not round trip"
                    )

        maximum = constants.RLE_RUN_LENGTH_MAX
        encoded_maximum = encode_rle_payload(
            b"Z" * maximum,
            item_size=1,
            max_items=maximum,
        )
        self.assertEqual(b"\xff\xffZ", encoded_maximum)
        with self.assertRaisesRegex(V2RLEValidationError, "u16 run"):
            encode_rle_payload(
                b"Z" * (maximum + 1),
                item_size=1,
                max_items=maximum + 1,
            )

    def test_every_positive_composition_is_canonical_and_count_exact(self) -> None:
        """All 128 ordered positive compositions of eight items are valid."""

        item_count = 8
        for item_size in (1, constants.ADC_BYTES_PER_PAIR):
            values = _items(item_size)
            for separators in range(1 << (item_count - 1)):
                run_lengths: list[int] = []
                current = 1
                for boundary in range(item_count - 1):
                    if separators & (1 << boundary):
                        run_lengths.append(current)
                        current = 1
                    else:
                        current += 1
                run_lengths.append(current)
                encoded = b"".join(
                    length.to_bytes(2, "little") + values[index % len(values)]
                    for index, length in enumerate(run_lengths)
                )
                logical = _payload_for_runs(item_size, tuple(run_lengths))
                self.assertEqual(
                    logical,
                    decode_rle_payload(
                        encoded,
                        item_size=item_size,
                        item_count=item_count,
                        max_items=item_count,
                    ),
                )
                self.assertEqual(
                    encoded,
                    encode_rle_payload(
                        logical,
                        item_size=item_size,
                        max_items=item_count,
                    ),
                )

    def test_malformed_record_classes_fail_before_any_payload_is_exposed(
        self,
    ) -> None:
        for item_size in (1, constants.ADC_BYTES_PER_PAIR):
            first, second, _ = _items(item_size)
            cases = {
                "zero_run": b"\0\0" + first,
                "decoded_count_overflow": (9).to_bytes(2, "little") + first,
                "count_mismatch": (7).to_bytes(2, "little") + first,
                "adjacent_equal_runs": (
                    (1).to_bytes(2, "little")
                    + first
                    + (7).to_bytes(2, "little")
                    + first
                ),
                "truncated_item": (4).to_bytes(2, "little") + second[:-1],
            }
            for expected_reason, encoded in cases.items():
                with self.subTest(
                    item_size=item_size,
                    expected_reason=expected_reason,
                ):
                    with self.assertRaises(V2RLEValidationError) as raised:
                        decode_rle_payload(
                            encoded,
                            item_size=item_size,
                            item_count=8,
                            max_items=8,
                        )
                    self.assertEqual(expected_reason, raised.exception.reason)

    def test_seeded_multi_run_round_trips_are_deterministic_for_both_widths(
        self,
    ) -> None:
        for item_size, item_count, seed in (
            (1, constants.GPIO_SAMPLES_PER_FRAME, 0x4750_494F),
            (
                constants.ADC_BYTES_PER_PAIR,
                constants.ADC_PAIRS_PER_FRAME,
                0x4144_4332,
            ),
        ):
            randomizer = random.Random(seed)
            for case_index in range(64):
                remaining = item_count
                run_lengths: list[int] = []
                while remaining:
                    selected = min(remaining, randomizer.randint(1, 97))
                    run_lengths.append(selected)
                    remaining -= selected
                logical = _payload_for_runs(item_size, tuple(run_lengths))
                encoded = encode_rle_payload(
                    bytearray(logical),
                    item_size=item_size,
                    max_items=item_count,
                )
                self.assertEqual(
                    len(run_lengths),
                    count_rle_runs(
                        memoryview(logical),
                        item_size=item_size,
                        max_items=item_count,
                    ),
                )
                self.assertEqual(
                    logical,
                    decode_rle_payload(
                        memoryview(encoded),
                        item_size=item_size,
                        item_count=item_count,
                        max_items=item_count,
                    ),
                    f"seeded case {case_index} failed for item_size={item_size}",
                )


class AdaptiveFrameBoundaryTests(unittest.TestCase):
    def test_exact_maximum_selected_frames_and_first_fallback_are_pinned(
        self,
    ) -> None:
        for kind in (
            constants.FrameKind.ADC_DATA,
            constants.FrameKind.GPIO_DATA,
        ):
            _, _, record_bytes, maximum_runs, maximum_frame_bytes = _shape(kind)
            for run_count in (maximum_runs - 1, maximum_runs, maximum_runs + 1):
                with self.subTest(kind=kind.name, run_count=run_count):
                    logical = _payload_with_run_count(kind, run_count)
                    wire = _encode_data(kind, logical)
                    frame = decode_v2_frame(wire)
                    block = decode_v2_data_block(
                        frame,
                        negotiated_encoding=ConfigurationEncoding.RLE_AUTO,
                    )
                    self.assertEqual(logical, block.payload)
                    diagnostics = block.encoding_diagnostics
                    self.assertIsNotNone(diagnostics)
                    assert diagnostics is not None
                    self.assertEqual(run_count, diagnostics.run_count)
                    if run_count <= maximum_runs:
                        self.assertIs(FrameEncoding.RLE, frame.header.encoding)
                        self.assertEqual(run_count * record_bytes, len(frame.payload))
                        if run_count == maximum_runs:
                            self.assertEqual(maximum_frame_bytes, len(wire))
                    else:
                        self.assertIs(FrameEncoding.RAW, frame.header.encoding)
                        self.assertEqual(constants.DATA_FRAME_BYTES, len(wire))

    def test_uniform_run_lengths_around_both_fallback_boundaries(self) -> None:
        cases = (
            (constants.FrameKind.ADC_DATA, range(1, 7)),
            (constants.FrameKind.GPIO_DATA, range(1, 9)),
        )
        for kind, run_lengths in cases:
            _, _, record_bytes, _, _ = _shape(kind)
            for requested_run_length in run_lengths:
                with self.subTest(
                    kind=kind.name,
                    requested_run_length=requested_run_length,
                ):
                    logical, run_count = _payload_with_uniform_runs(
                        kind,
                        requested_run_length,
                    )
                    frame = decode_v2_frame(_encode_data(kind, logical))
                    expected = (
                        FrameEncoding.RLE
                        if run_count * record_bytes < constants.DATA_PAYLOAD_BYTES
                        else FrameEncoding.RAW
                    )
                    self.assertIs(expected, frame.header.encoding)
                    self.assertEqual(
                        logical,
                        decode_v2_data_block(
                            frame,
                            negotiated_encoding=ConfigurationEncoding.RLE_AUTO,
                        ).payload,
                    )

        self.assertGreaterEqual(
            math.ceil(constants.ADC_PAIRS_PER_FRAME / 1)
            * constants.ADC_RLE_RECORD_BYTES,
            constants.DATA_PAYLOAD_BYTES,
        )
        self.assertLess(
            math.ceil(constants.ADC_PAIRS_PER_FRAME / 2)
            * constants.ADC_RLE_RECORD_BYTES,
            constants.DATA_PAYLOAD_BYTES,
        )
        self.assertGreaterEqual(
            math.ceil(constants.GPIO_SAMPLES_PER_FRAME / 3)
            * constants.GPIO_RLE_RECORD_BYTES,
            constants.DATA_PAYLOAD_BYTES,
        )
        self.assertLess(
            math.ceil(constants.GPIO_SAMPLES_PER_FRAME / 4)
            * constants.GPIO_RLE_RECORD_BYTES,
            constants.DATA_PAYLOAD_BYTES,
        )


class RLEParserAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_checksum_is_rejected_before_an_invalid_rle_record_is_examined(
        self,
    ) -> None:
        wire = bytearray((FIXTURE_ROOT / "gpio-rle-zero-run.bin").read_bytes())
        wire[-1] ^= 0x80
        with self.assertRaises(V2ChecksumMismatchError) as raised:
            decode_v2_frame(wire)
        self.assertEqual("checksum_mismatch", raised.exception.reason)

    def test_every_declared_malformed_vector_recovers_byte_by_byte(self) -> None:
        sentinel = (FIXTURE_ROOT / "ping-request.bin").read_bytes()
        for entry in self.manifest["malformed_fixtures"]:
            malformed = (FIXTURE_ROOT / entry["file"]).read_bytes()
            with self.subTest(fixture=entry["file"]):
                with self.assertRaises(V2FrameValidationError) as raised:
                    decode_v2_frame(malformed)
                self.assertEqual(entry["expected_error"], raised.exception.reason)

                parser = IncrementalV2FrameParser()
                decoded = []
                for value in malformed + sentinel:
                    decoded.extend(parser.feed(bytes((value,))))
                    self.assertLessEqual(
                        parser.buffered_bytes,
                        parser.max_buffered_bytes,
                    )
                self.assertEqual([sentinel], [frame.to_bytes() for frame in decoded])
                self.assertGreater(parser.corruption_events, 0)
                self.assertEqual(0, parser.buffered_bytes)

    def test_mixed_raw_rle_stream_survives_every_relevant_chunk_boundary(
        self,
    ) -> None:
        adc_rle = _encode_data(
            constants.FrameKind.ADC_DATA,
            _payload_with_run_count(constants.FrameKind.ADC_DATA, 3),
            sequence=0,
        )
        gpio_raw = _encode_data(
            constants.FrameKind.GPIO_DATA,
            _payload_with_run_count(
                constants.FrameKind.GPIO_DATA,
                constants.GPIO_RLE_MAX_SELECTED_RUNS + 1,
            ),
            sequence=0,
        )
        adc_raw = _encode_data(
            constants.FrameKind.ADC_DATA,
            _payload_with_run_count(
                constants.FrameKind.ADC_DATA,
                constants.ADC_RLE_MAX_SELECTED_RUNS + 1,
            ),
            sequence=1,
        )
        gpio_rle = _encode_data(
            constants.FrameKind.GPIO_DATA,
            _payload_with_run_count(constants.FrameKind.GPIO_DATA, 5),
            sequence=1,
        )
        expected_wire = (adc_rle, gpio_raw, adc_raw, gpio_rle)
        stream = b"".join(expected_wire)
        chunk_sizes = tuple(range(1, constants.MIN_FRAME_BYTES + 1)) + (
            constants.DATA_FRAME_BYTES - 1,
            constants.DATA_FRAME_BYTES,
            constants.DATA_FRAME_BYTES + 1,
            len(stream),
        )
        for chunk_size in chunk_sizes:
            with self.subTest(chunk_size=chunk_size):
                parser = IncrementalV2FrameParser()
                decoded = []
                for offset in range(0, len(stream), chunk_size):
                    decoded.extend(parser.feed(stream[offset : offset + chunk_size]))
                self.assertEqual(
                    expected_wire,
                    tuple(frame.to_bytes() for frame in decoded),
                )
                self.assertEqual(0, parser.corruption_events)
                self.assertEqual(0, parser.buffered_bytes)
                self.assertLessEqual(
                    parser.high_water_mark,
                    parser.max_buffered_bytes,
                )

        compact_stream = adc_rle + gpio_rle
        for split in range(len(compact_stream) + 1):
            parser = IncrementalV2FrameParser()
            decoded = parser.feed(compact_stream[:split])
            decoded.extend(parser.feed(compact_stream[split:]))
            if tuple(frame.to_bytes() for frame in decoded) != (adc_rle, gpio_rle):
                self.fail(f"parser failed at exhaustive split offset {split}")

    def test_compression_bomb_fails_without_decoded_allocation_or_growth(
        self,
    ) -> None:
        bomb = (FIXTURE_ROOT / "gpio-rle-overflowing-run.bin").read_bytes()
        sentinel = (FIXTURE_ROOT / "ping-request.bin").read_bytes()
        encoded_payload = bomb[constants.HEADER_SIZE : -constants.TRAILER_SIZE]

        with patch("thingdaq.protocol_v2.bytearray", create=True) as allocation:
            allocation.side_effect = AssertionError("decoded allocation attempted")
            with self.assertRaises(V2RLEValidationError) as raised:
                decode_rle_payload(
                    encoded_payload,
                    item_size=1,
                    item_count=constants.GPIO_SAMPLES_PER_FRAME,
                    max_items=constants.GPIO_SAMPLES_PER_FRAME,
                )
        allocation.assert_not_called()
        self.assertEqual("decoded_count_overflow", raised.exception.reason)

        parser = IncrementalV2FrameParser()
        tracemalloc.start()
        try:
            decoded = parser.feed(bomb + sentinel)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual([sentinel], [frame.to_bytes() for frame in decoded])
        self.assertLess(peak_bytes, 64 * 1024)
        self.assertEqual(
            constants.MAX_DATA_FRAME_BYTES + len(constants.MAGIC_BYTES) - 1,
            parser.max_buffered_bytes,
        )
        self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)
        self.assertEqual(0, parser.buffered_bytes)

    def test_independent_checksum_matches_each_selected_maximum_frame(self) -> None:
        for kind in (
            constants.FrameKind.ADC_DATA,
            constants.FrameKind.GPIO_DATA,
        ):
            _, _, _, maximum_runs, _ = _shape(kind)
            wire = _encode_data(kind, _payload_with_run_count(kind, maximum_runs))
            observed = _TRAILER.unpack_from(wire, len(wire) - _TRAILER.size)[0]
            self.assertEqual(compute_v2_checksum(wire[:-4]), observed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
