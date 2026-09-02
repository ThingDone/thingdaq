"""Independent generation, vector, and bounded-parser checks for protocol v2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import struct
import tempfile
import tracemalloc
import unittest
import zlib
from pathlib import Path
from typing import Any, ClassVar

from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.protocol_v2 import (
    MAX_V2_BUFFERED_BYTES,
    IncrementalV2FrameParser,
    V2FrameValidationError,
    decode_v2_frame,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
V2_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures-v2"
MANIFEST_PATH = FIXTURE_DIRECTORY / "manifest.json"
GENERATOR_PATH = REPOSITORY_ROOT / "tools/generate_protocol.py"
CPP_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_v2_constants.h"

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_protocol_v2_vector_test",
    GENERATOR_PATH,
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
generate_protocol = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_protocol)

_HEADER = struct.Struct("<IBBHHBBIIIIIQI")
_TRAILER = struct.Struct("<I")
_FROZEN_V1_SHA256 = {
    "protocol/protocol-v1.json": (
        "014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222"
    ),
    "protocol/fixtures/manifest.json": (
        "e354b6dd7749b4dcea9ee233297f5712f645c2d0a1444d990e22f02303c99568"
    ),
    "daq_api/src/thingdaq/_generated/protocol_constants.py": (
        "a5dc4cd73dd12e291c03d536c2937d14ad1d0ca84b9c8a2860ad2797fbf15961"
    ),
    "firmware/src/generated/protocol_constants.h": (
        "9604390433f7d8227432d341ecc65b9292002797da9457937ed4d5d3cc096290"
    ),
}


def _fixture(name: str) -> bytes:
    return (FIXTURE_DIRECTORY / f"{name}.bin").read_bytes()


def _reference_checksum(frame_without_trailer: bytes, algorithm: str) -> int:
    if algorithm == "ADLER32":
        return zlib.adler32(frame_without_trailer) & 0xFFFFFFFF
    if algorithm == "CRC32_ISO_HDLC":
        return zlib.crc32(frame_without_trailer) & 0xFFFFFFFF
    if algorithm == "CRC32C":
        remainder = 0xFFFFFFFF
        for value in frame_without_trailer:
            remainder ^= value
            for _ in range(8):
                remainder = (remainder >> 1) ^ (0x82F63B78 if remainder & 1 else 0)
        return remainder ^ 0xFFFFFFFF
    raise AssertionError(f"unexpected checksum algorithm {algorithm}")


def _split_stream(stream: bytes) -> tuple[bytes, ...]:
    frames: list[bytes] = []
    offset = 0
    while offset < len(stream):
        if len(stream) - offset < _HEADER.size:
            raise AssertionError("stream ends inside a header")
        total_length = struct.unpack_from("<I", stream, offset + 12)[0]
        end = offset + total_length
        if end > len(stream):
            raise AssertionError("stream ends inside a declared frame")
        frames.append(stream[offset:end])
        offset = end
    return tuple(frames)


def _expand_rle(payload: bytes, item_bytes: int) -> tuple[bytes, int]:
    record_bytes = item_bytes + 2
    if len(payload) % record_bytes:
        raise AssertionError("incomplete independent RLE record")
    expanded = bytearray()
    run_count = 0
    for offset in range(0, len(payload), record_bytes):
        run_length = struct.unpack_from("<H", payload, offset)[0]
        item = payload[offset + 2 : offset + record_bytes]
        expanded.extend(item * run_length)
        run_count += 1
    return bytes(expanded), run_count


def _canonical_rle_size(raw_payload: bytes, item_bytes: int) -> int:
    previous: bytes | None = None
    run_count = 0
    for offset in range(0, len(raw_payload), item_bytes):
        item = raw_payload[offset : offset + item_bytes]
        if item != previous:
            run_count += 1
            previous = item
    return run_count * (item_bytes + 2)


def _partition(data: bytes, seed: int) -> tuple[bytes, ...]:
    randomizer = random.Random(seed)
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        size = randomizer.randint(1, min(701, len(data) - offset))
        chunks.append(data[offset : offset + size])
        offset += size
    return tuple(chunks)


class ProtocolV2VectorTests(unittest.TestCase):
    contract: ClassVar[dict[str, Any]]
    manifest: ClassVar[dict[str, Any]]
    fixture_entries: ClassVar[dict[str, dict[str, Any]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(V2_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.fixture_entries = {
            str(entry["file"]): entry for entry in cls.manifest["fixtures"]
        }

    def test_both_versions_generate_deterministically_to_disjoint_paths(self) -> None:
        v1_contract, v1_source = generate_protocol.load_contract(V1_CONTRACT_PATH)
        v2_contract, v2_source = generate_protocol.load_contract(V2_CONTRACT_PATH)
        generate_protocol.validate_contract(v1_contract)
        generate_protocol.validate_contract(v2_contract)

        v1_first = generate_protocol.expected_outputs(v1_contract, v1_source)
        v1_second = generate_protocol.expected_outputs(v1_contract, v1_source)
        v2_first = generate_protocol.expected_outputs(v2_contract, v2_source)
        v2_second = generate_protocol.expected_outputs(v2_contract, v2_source)

        self.assertEqual(v1_first, v1_second)
        self.assertEqual(v2_first, v2_second)
        self.assertEqual(26, len(v1_first))
        self.assertEqual(44, len(v2_first))
        self.assertTrue(set(v1_first).isdisjoint(v2_first))
        for outputs in (v1_first, v2_first):
            for path, expected in outputs.items():
                with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                    self.assertTrue(path.is_file())
                    self.assertEqual(expected, path.read_bytes())
            self.assertEqual([], generate_protocol.orphaned_fixture_paths(outputs))

    def test_orphan_detection_covers_both_fixture_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            outputs: dict[Path, bytes] = {}
            expected_orphans: list[Path] = []
            for directory_name in ("fixtures", "fixtures-v2"):
                directory = root / directory_name
                directory.mkdir()
                manifest = directory / "manifest.json"
                expected = directory / "expected.bin"
                orphan = directory / "orphan.bin"
                manifest.write_text("{}\n", encoding="utf-8")
                expected.write_bytes(b"expected")
                orphan.write_bytes(b"orphan")
                outputs[manifest] = b"{}\n"
                outputs[expected] = b"expected"
                expected_orphans.append(orphan)

            self.assertEqual(
                sorted(expected_orphans),
                generate_protocol.orphaned_fixture_paths(outputs),
            )

    def test_original_v1_artifacts_remain_byte_for_byte_frozen(self) -> None:
        for relative_path, expected_sha256 in _FROZEN_V1_SHA256.items():
            with self.subTest(path=relative_path):
                contents = (REPOSITORY_ROOT / relative_path).read_bytes()
                self.assertEqual(
                    expected_sha256,
                    hashlib.sha256(contents).hexdigest(),
                )
        v1_manifest = json.loads(
            (REPOSITORY_ROOT / "protocol/fixtures/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(23, len(v1_manifest["fixtures"]))
        for entry in v1_manifest["fixtures"]:
            contents = (
                REPOSITORY_ROOT / "protocol/fixtures" / entry["file"]
            ).read_bytes()
            self.assertEqual(
                entry["frame_sha256"], hashlib.sha256(contents).hexdigest()
            )

    def test_v2_constants_and_cpp_header_match_the_extension_contract(self) -> None:
        source_sha256 = hashlib.sha256(V2_CONTRACT_PATH.read_bytes()).hexdigest()
        cpp = CPP_PATH.read_text(encoding="utf-8")
        self.assertEqual(source_sha256, constants.SOURCE_SHA256)
        self.assertEqual(source_sha256, self.manifest["source_sha256"])
        self.assertIn(f"Source SHA-256: {source_sha256}", cpp)
        self.assertIn("namespace thingdaq::protocol_v2", cpp)
        self.assertEqual(2, constants.PROTOCOL_VERSION)
        self.assertEqual(11, constants.HEADER_ENCODING_OFFSET)
        self.assertEqual(0, constants.ConfigurationEncoding.RAW)
        self.assertEqual(1, constants.ConfigurationEncoding.RLE_AUTO)
        self.assertEqual(0, constants.FrameEncoding.RAW)
        self.assertEqual(1, constants.FrameEncoding.RLE)
        self.assertEqual(0x200, constants.Capability.RLE_STREAMING)
        self.assertEqual(6, constants.ADC_RLE_RECORD_BYTES)
        self.assertEqual(3, constants.GPIO_RLE_RECORD_BYTES)
        self.assertEqual(674, constants.ADC_RLE_MAX_SELECTED_RUNS)
        self.assertEqual(1_349, constants.GPIO_RLE_MAX_SELECTED_RUNS)
        self.assertLess(
            constants.ADC_RLE_MAX_SELECTED_FRAME_BYTES,
            constants.DATA_FRAME_BYTES,
        )
        self.assertLess(
            constants.GPIO_RLE_MAX_SELECTED_FRAME_BYTES,
            constants.DATA_FRAME_BYTES,
        )

    def test_every_valid_fixture_has_an_independent_exact_envelope(self) -> None:
        self.assertEqual(44, _HEADER.size)
        self.assertEqual(31, len(self.manifest["fixtures"]))
        generated_files = (
            {entry["file"] for entry in self.manifest["fixtures"]}
            | {entry["file"] for entry in self.manifest["streams"]}
            | {entry["file"] for entry in self.manifest["malformed_fixtures"]}
        )
        self.assertEqual(
            generated_files,
            {path.name for path in FIXTURE_DIRECTORY.glob("*.bin")},
        )

        kind_values = {
            entry["name"]: int(entry["value"]) for entry in self.contract["frame_kinds"]
        }
        for entry in self.manifest["fixtures"]:
            frame = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            fields = _HEADER.unpack_from(frame)
            observed_checksum = _TRAILER.unpack_from(frame, len(frame) - 4)[0]
            expected_checksum = _reference_checksum(
                frame[:-4], str(entry["checksum_algorithm"])
            )
            with self.subTest(fixture=entry["file"]):
                self.assertEqual(0xDEADBEEF, fields[0])
                self.assertEqual(2, fields[1])
                self.assertEqual(kind_values[entry["kind"]], fields[2])
                self.assertEqual(44, fields[4])
                self.assertEqual(entry["encoding_selector"], fields[6])
                self.assertEqual(len(frame), fields[7])
                self.assertEqual(len(frame) - 48, fields[8])
                self.assertEqual(entry["item_count"], fields[13])
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(frame).hexdigest()
                )
                self.assertEqual(expected_checksum, observed_checksum)
                self.assertEqual(frame, decode_v2_frame(frame).to_bytes())

    def test_raw_and_rle_adc_gpio_vectors_encode_exact_logical_items(self) -> None:
        adc = decode_v2_frame(_fixture("adc-rle-data"))
        gpio = decode_v2_frame(_fixture("gpio-rle-data"))
        expected_adc_payload = b"".join(
            (
                struct.pack("<HHH", 400, 291, 1110),
                struct.pack("<HHH", 1, 16, 32),
                struct.pack("<HHH", 611, 2748, 3567),
            )
        )
        expected_gpio_payload = b"".join(
            (
                struct.pack("<HB", 2048, 0),
                struct.pack("<HB", 1000, 255),
                struct.pack("<HB", 1000, 85),
            )
        )
        self.assertEqual(expected_adc_payload, adc.payload)
        self.assertEqual(expected_gpio_payload, gpio.payload)

        expanded_adc, adc_runs = _expand_rle(adc.payload, 4)
        expanded_gpio, gpio_runs = _expand_rle(gpio.payload, 1)
        self.assertEqual(constants.DATA_PAYLOAD_BYTES, len(expanded_adc))
        self.assertEqual(constants.DATA_PAYLOAD_BYTES, len(expanded_gpio))
        self.assertEqual(3, adc_runs)
        self.assertEqual(3, gpio_runs)
        self.assertEqual(adc_runs, adc.run_count)
        self.assertEqual(gpio_runs, gpio.run_count)

        for name, item_bytes in (
            ("adc-raw-fallback-data", 4),
            ("gpio-raw-fallback-data", 1),
        ):
            with self.subTest(fallback=name):
                frame = decode_v2_frame(_fixture(name))
                self.assertEqual(constants.FrameEncoding.RAW, frame.header.encoding)
                self.assertGreaterEqual(
                    _canonical_rle_size(frame.payload, item_bytes),
                    len(frame.payload),
                )
                self.assertEqual(
                    "rle_not_smaller",
                    self.fixture_entries[f"{name}.bin"]["selection_reason"],
                )

    def test_mixed_streams_are_exact_raw_rle_raw_sequences(self) -> None:
        expected = {
            "adc-mixed-raw-rle-stream.bin": (
                "adc-data.bin",
                "adc-rle-data.bin",
                "adc-raw-fallback-data.bin",
            ),
            "gpio-mixed-raw-rle-stream.bin": (
                "gpio-data.bin",
                "gpio-rle-data.bin",
                "gpio-raw-fallback-data.bin",
            ),
        }
        for entry in self.manifest["streams"]:
            stream = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            frames = _split_stream(stream)
            with self.subTest(stream=entry["file"]):
                self.assertEqual(expected[entry["file"]], tuple(entry["frames"]))
                self.assertEqual(
                    b"".join(
                        (FIXTURE_DIRECTORY / file_name).read_bytes()
                        for file_name in expected[entry["file"]]
                    ),
                    stream,
                )
                self.assertEqual(
                    [
                        constants.FrameEncoding.RAW,
                        constants.FrameEncoding.RLE,
                        constants.FrameEncoding.RAW,
                    ],
                    [decode_v2_frame(frame).header.encoding for frame in frames],
                )
                self.assertEqual(
                    [0, 1, 2],
                    [decode_v2_frame(frame).header.sequence for frame in frames],
                )
                self.assertEqual(
                    entry["stream_sha256"], hashlib.sha256(stream).hexdigest()
                )

    def test_capability_and_configuration_vectors_pin_negotiation_bytes(self) -> None:
        info = decode_v2_frame(_fixture("info-response"))
        capability_bits = struct.unpack_from(
            "<I", info.payload, constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET
        )[0]
        self.assertEqual(constants.KNOWN_CAPABILITY_MASK, capability_bits)
        self.assertTrue(capability_bits & int(constants.Capability.RLE_STREAMING))

        request = decode_v2_frame(_fixture("configure-rle-request"))
        configure = decode_v2_frame(_fixture("configure-rle-response"))
        start = decode_v2_frame(_fixture("start-rle-response"))
        self.assertEqual(
            constants.ConfigurationEncoding.RLE_AUTO,
            request.payload[constants.CONFIGURE_REQUEST_ENCODING_OFFSET],
        )
        for response in (configure, start):
            self.assertEqual(
                constants.ConfigurationEncoding.RLE_AUTO,
                response.payload[constants.CONFIGURE_RESPONSE_ENCODING_OFFSET],
            )
            self.assertEqual(constants.FrameEncoding.RAW, response.header.encoding)

    def test_every_malformed_fixture_has_the_declared_rejection(self) -> None:
        expected_errors = {
            "zero_run",
            "decoded_count_overflow",
            "truncated_item",
            "adjacent_equal_runs",
            "count_mismatch",
            "illegal_selector",
            "invalid_length",
            "checksum_mismatch",
        }
        self.assertEqual(8, len(self.manifest["malformed_fixtures"]))
        self.assertEqual(
            expected_errors,
            {entry["expected_error"] for entry in self.manifest["malformed_fixtures"]},
        )
        for entry in self.manifest["malformed_fixtures"]:
            frame = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            with self.subTest(fixture=entry["file"]):
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(frame).hexdigest()
                )
                with self.assertRaises(V2FrameValidationError) as captured:
                    decode_v2_frame(frame)
                self.assertEqual(entry["expected_error"], captured.exception.reason)
                if entry["expected_error"] != "checksum_mismatch":
                    self.assertEqual(
                        _reference_checksum(frame[:-4], "ADLER32"),
                        _TRAILER.unpack_from(frame, len(frame) - 4)[0],
                    )

    def test_parser_recovers_after_each_malformed_frame_within_v1_bounds(self) -> None:
        sentinel = _fixture("ping-request")
        for entry in self.manifest["malformed_fixtures"]:
            malformed = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            for seed in (0, 1, 7, 31):
                with self.subTest(fixture=entry["file"], seed=seed):
                    parser = IncrementalV2FrameParser()
                    decoded = []
                    for chunk in _partition(malformed + sentinel, seed):
                        decoded.extend(parser.feed(chunk))
                        self.assertLessEqual(
                            parser.buffered_bytes,
                            parser.max_buffered_bytes,
                        )
                        self.assertLessEqual(
                            parser.high_water_mark,
                            parser.max_buffered_bytes,
                        )
                    self.assertEqual(
                        [sentinel], [frame.to_bytes() for frame in decoded]
                    )
                    self.assertEqual(0, parser.buffered_bytes)
                    self.assertGreater(parser.corruption_events, 0)
                    self.assertGreater(parser.resynchronizations, 0)
                    if entry["expected_error"] == "checksum_mismatch":
                        self.assertGreater(parser.checksum_errors, 0)

    def test_parser_preserves_mixed_streams_under_arbitrary_chunking(self) -> None:
        expected = tuple(
            (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            for entry in self.manifest["fixtures"]
        )
        stream = b"".join(expected)
        for seed in (0, 2, 19, 257, 65_537):
            with self.subTest(seed=seed):
                parser = IncrementalV2FrameParser()
                decoded = []
                for chunk in _partition(stream, seed):
                    decoded.extend(parser.feed(chunk))
                self.assertEqual(expected, tuple(frame.to_bytes() for frame in decoded))
                self.assertEqual(len(expected), parser.frames_decoded)
                self.assertEqual(0, parser.corruption_events)
                self.assertEqual(0, parser.buffered_bytes)
                self.assertLessEqual(parser.high_water_mark, MAX_V2_BUFFERED_BYTES)

    def test_overflowing_run_cannot_drive_a_decoded_allocation(self) -> None:
        overflowing = _fixture("gpio-rle-overflowing-run")
        sentinel = _fixture("ping-request")
        parser = IncrementalV2FrameParser()
        tracemalloc.start()
        try:
            decoded = parser.feed(overflowing + sentinel)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual([sentinel], [frame.to_bytes() for frame in decoded])
        self.assertLess(peak_bytes, 64 * 1024)
        self.assertEqual(MAX_V2_BUFFERED_BYTES, parser.max_buffered_bytes)
        self.assertEqual(0, parser.buffered_bytes)


if __name__ == "__main__":
    unittest.main()
