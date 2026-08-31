"""Independent checksum parity, corruption, and negotiation regression tests.

The corruption cases below are deterministic samples for accidental-error
detection. They are not a proof of minimum distance, authentication, or any
other security property.
"""

from __future__ import annotations

import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path

from thingdaq import (
    ChecksumAlgorithmMismatchError,
    ChecksumMismatchError,
    GPIOBlock,
    IncrementalFrameParser,
    ThingDAQ,
    UnsupportedChecksumError,
    compute_checksum,
    decode_frame,
    encode_frame,
)
from thingdaq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/checksum_correctness_test.cpp"
ALGORITHMS = tuple(sorted(constants.SUPPORTED_CHECKSUM_ALGORITHMS, key=int))
EDGE_LENGTHS = (
    0,
    1,
    2,
    3,
    4,
    7,
    8,
    15,
    16,
    31,
    32,
    33,
    63,
    64,
    65,
    127,
    128,
    129,
    255,
    256,
    257,
    511,
    512,
    513,
    1_023,
    4_091,
    4_092,
    4_093,
    4_096,
    5_551,
    5_552,
    5_553,
    8_191,
)
PUBLISHED_VECTORS = {
    b"": (0x00000001, 0x00000000, 0x00000000),
    b"a": (0x00620062, 0xC1D04330, 0xE8B7BE43),
    b"Wikipedia": (0x11E60398, 0x2D0E3663, 0xADAAC02E),
    b"123456789": (0x091E01DE, 0xE3069283, 0xCBF43926),
    b"The quick brown fox jumps over the lazy dog": (
        0x5BDC0FDA,
        0x22620404,
        0x414FA339,
    ),
}


def _reference_adler32(data: bytes) -> int:
    first = 1
    second = 0
    for value in data:
        first = (first + value) % 65_521
        second = (second + first) % 65_521
    return (second << 16) | first


def _reference_reflected_crc32(data: bytes, polynomial: int) -> int:
    remainder = 0xFFFFFFFF
    for value in data:
        remainder ^= value
        for _ in range(8):
            remainder = (remainder >> 1) ^ (polynomial if remainder & 1 else 0)
    return remainder ^ 0xFFFFFFFF


def _reference_checksum(data: bytes, algorithm: constants.ChecksumAlgorithm) -> int:
    if algorithm is constants.ChecksumAlgorithm.ADLER32:
        return _reference_adler32(data)
    if algorithm is constants.ChecksumAlgorithm.CRC32C:
        return _reference_reflected_crc32(data, 0x82F63B78)
    if algorithm is constants.ChecksumAlgorithm.CRC32_ISO_HDLC:
        return _reference_reflected_crc32(data, 0xEDB88320)
    raise AssertionError(f"test reference has no algorithm {algorithm!r}")


def _deterministic_corpus() -> tuple[bytes, ...]:
    randomizer = random.Random(0xC5_EED_05)
    corpus = [randomizer.randbytes(length) for length in EDGE_LENGTHS]
    for _ in range(64):
        corpus.append(randomizer.randbytes(randomizer.randrange(0, 8_192)))
    return tuple(corpus)


def _corpus_wire(corpus: Iterable[bytes]) -> bytes:
    items = tuple(corpus)
    wire = bytearray(struct.pack("<I", len(items)))
    for item in items:
        wire.extend(struct.pack("<I", len(item)))
        wire.extend(item)
    return bytes(wire)


def _flip_bit_burst(data: bytes, start: int, width: int) -> bytes:
    result = bytearray(data)
    for bit in range(start, start + width):
        result[bit // 8] ^= 1 << (bit % 8)
    return bytes(result)


class CrossLanguageChecksumCorrectnessTests(unittest.TestCase):
    def test_published_values_and_independent_python_references(self) -> None:
        for data, expected_values in PUBLISHED_VECTORS.items():
            for algorithm, expected in zip(ALGORITHMS, expected_values, strict=True):
                with self.subTest(data=data, algorithm=algorithm.name):
                    self.assertEqual(expected, _reference_checksum(data, algorithm))
                    self.assertEqual(expected, compute_checksum(data, algorithm))

    def test_cpp_and_python_emit_identical_little_endian_values(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        corpus = _deterministic_corpus()
        expected = bytearray()
        for case_index, data in enumerate(corpus):
            for algorithm in ALGORITHMS:
                reference = _reference_checksum(data, algorithm)
                with self.subTest(case=case_index, algorithm=algorithm.name):
                    self.assertEqual(reference, compute_checksum(data, algorithm))
                expected.extend(struct.pack("<I", reference))

        with tempfile.TemporaryDirectory(
            prefix="thingdaq-checksum-correctness-"
        ) as directory:
            temporary = Path(directory)
            executable = temporary / "checksum-correctness-test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O3",
                    "-flto",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    "-fno-exceptions",
                    "-fno-rtti",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "checksum.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                compile_result.returncode,
                compile_result.stdout + compile_result.stderr,
            )

            built_in_result = subprocess.run(
                [str(executable)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                built_in_result.returncode,
                built_in_result.stdout + built_in_result.stderr,
            )

            corpus_path = temporary / "corpus.bin"
            result_path = temporary / "checksums.bin"
            corpus_path.write_bytes(_corpus_wire(corpus))
            agreement_result = subprocess.run(
                [str(executable), str(corpus_path), str(result_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                agreement_result.returncode,
                agreement_result.stdout + agreement_result.stderr,
            )
            self.assertEqual(bytes(expected), result_path.read_bytes())


class ChecksumCorruptionTests(unittest.TestCase):
    @staticmethod
    def _detected_count(
        original: bytes,
        variants: Iterable[bytes],
        algorithm: constants.ChecksumAlgorithm,
    ) -> tuple[int, int]:
        original_checksum = compute_checksum(original, algorithm)
        cases = tuple(variants)
        detected = sum(
            compute_checksum(candidate, algorithm) != original_checksum
            for candidate in cases
        )
        return detected, len(cases)

    def test_sampled_bit_burst_transposition_and_edit_faults_are_detected(
        self,
    ) -> None:
        original = bytes(range(64))
        single_bits = tuple(
            _flip_bit_burst(original, bit, 1) for bit in range(len(original) * 8)
        )
        short_bursts = tuple(
            _flip_bit_burst(original, start, width)
            for width in range(2, 17)
            for start in (0, 3, 31, 127, 255, 400)
        )
        transposition_pairs = tuple((index, index + 1) for index in range(63)) + (
            (0, 63),
            (1, 32),
            (7, 48),
            (15, 16),
        )
        transpositions: list[bytes] = []
        for first, second in transposition_pairs:
            changed = bytearray(original)
            changed[first], changed[second] = changed[second], changed[first]
            transpositions.append(bytes(changed))
        edits = tuple(
            original[:position] + bytes((value,)) + original[position:]
            for position in (0, 1, 31, 63, 64)
            for value in (0x00, 0xFF, 0xA5)
        ) + tuple(
            original[:position] + original[position + 1 :]
            for position in (0, 1, 31, 62, 63)
        )

        families = {
            "single-bit": single_bits,
            "short-burst": short_bursts,
            "transposition": tuple(transpositions),
            "insert-delete": edits,
        }
        for algorithm in ALGORITHMS:
            for family, variants in families.items():
                with self.subTest(algorithm=algorithm.name, family=family):
                    self.assertEqual(
                        (len(variants), len(variants)),
                        self._detected_count(original, variants, algorithm),
                    )

    def test_header_payload_and_trailer_faults_fail_for_every_algorithm(self) -> None:
        payload = bytes(
            (index * 73 + 19) & 0xFF for index in range(constants.DATA_PAYLOAD_BYTES)
        )
        for algorithm in ALGORITHMS:
            frame = encode_frame(
                constants.FrameKind.GPIO_DATA,
                payload,
                flags=constants.FrameFlag.SYNTHETIC,
                checksum_algorithm=algorithm,
                run_id=17,
                sequence=1,
                first_sample_ticks=8,
                item_count=constants.GPIO_SAMPLES_PER_FRAME,
            )
            offsets = {
                "header": constants.HEADER_RUN_ID_OFFSET,
                "payload": constants.HEADER_SIZE + 1_337,
                "trailer": len(frame) - 1,
            }
            for region, offset in offsets.items():
                corrupted = bytearray(frame)
                corrupted[offset] ^= 0x40
                with (
                    self.subTest(algorithm=algorithm.name, region=region),
                    self.assertRaises(ChecksumMismatchError),
                ):
                    decode_frame(corrupted)

    def test_parser_resynchronizes_after_each_candidate_has_a_bad_trailer(
        self,
    ) -> None:
        following = encode_frame(constants.FrameKind.INFO_REQUEST, request_id=99)
        payload = bytes(constants.DATA_PAYLOAD_BYTES)
        for algorithm in ALGORITHMS:
            corrupted = bytearray(
                encode_frame(
                    constants.FrameKind.GPIO_DATA,
                    payload,
                    flags=constants.FrameFlag.SYNTHETIC,
                    checksum_algorithm=algorithm,
                    run_id=7,
                    sequence=3,
                    first_sample_ticks=16,
                    item_count=constants.GPIO_SAMPLES_PER_FRAME,
                )
            )
            corrupted[-1] ^= 0x80
            parser = IncrementalFrameParser()

            decoded = parser.feed(corrupted[:47])
            decoded.extend(parser.feed(corrupted[47:] + following))

            with self.subTest(algorithm=algorithm.name):
                self.assertEqual([following], [frame.to_bytes() for frame in decoded])
                self.assertEqual(1, parser.checksum_errors)
                self.assertEqual(1, parser.resynchronizations)
                self.assertEqual(len(corrupted), parser.bytes_discarded)
                self.assertEqual(0, parser.buffered_bytes)


class ChecksumNegotiationRegressionTests(unittest.TestCase):
    def test_bootstrap_and_unsupported_ids_fail_closed(self) -> None:
        control = encode_frame(constants.FrameKind.INFO_REQUEST, request_id=1)
        self.assertIs(
            constants.ChecksumAlgorithm.ADLER32,
            decode_frame(control).header.checksum_algorithm,
        )
        for algorithm in ALGORITHMS[1:]:
            with (
                self.subTest(algorithm=algorithm.name),
                self.assertRaises(ChecksumAlgorithmMismatchError),
            ):
                encode_frame(
                    constants.FrameKind.INFO_REQUEST,
                    request_id=1,
                    checksum_algorithm=algorithm,
                )
        for unsupported in (constants.ChecksumAlgorithm.NONE_RESERVED, 0xFE):
            with (
                self.subTest(unsupported=unsupported),
                self.assertRaises(UnsupportedChecksumError),
            ):
                compute_checksum(b"unsupported", unsupported)

    def test_each_negotiated_algorithm_survives_a_complete_configuration_run(
        self,
    ) -> None:
        with ThingDAQ.simulated() as daq:
            for algorithm in ALGORITHMS:
                with self.subTest(algorithm=algorithm.name):
                    applied = daq.configure(
                        adc=False,
                        gpio=True,
                        checksum_algorithm=algorithm,
                    )
                    self.assertIs(algorithm, applied.data_checksum_algorithm)
                    self.assertIs(
                        algorithm,
                        daq.status().data_checksum_algorithm,
                    )
                    daq.start()
                    block = daq.read_block()
                    self.assertIsInstance(block, GPIOBlock)
                    assert isinstance(block, GPIOBlock)
                    self.assertIs(algorithm, block.data_checksum_algorithm)
                    daq.stop()


if __name__ == "__main__":
    unittest.main()
