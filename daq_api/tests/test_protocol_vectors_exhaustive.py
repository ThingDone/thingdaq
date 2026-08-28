"""Independent wire-vector tests for every protocol-v1 frame kind."""

from __future__ import annotations

import hashlib
import json
import struct
import unittest
from dataclasses import dataclass
from pathlib import Path

from teensy_daq import compute_checksum, decode_frame, encode_frame

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
MANIFEST_PATH = FIXTURE_DIRECTORY / "manifest.json"

_HEADER = struct.Struct("<IBBHHBBIIIIIQI")
_TRAILER = struct.Struct("<I")
_ADLER_MODULUS = 65_521
_KIND_NAMES = {
    0x01: "ADC_DATA",
    0x02: "GPIO_DATA",
    0x10: "INFO_REQUEST",
    0x11: "CONFIGURE_REQUEST",
    0x12: "START_REQUEST",
    0x13: "GET_STATUS_REQUEST",
    0x14: "STOP_REQUEST",
    0x15: "RESET_STATS_REQUEST",
    0x16: "PING_REQUEST",
    0x90: "INFO_RESPONSE",
    0x91: "CONFIGURE_RESPONSE",
    0x92: "START_RESPONSE",
    0x93: "GET_STATUS_RESPONSE",
    0x94: "STOP_RESPONSE",
    0x95: "RESET_STATS_RESPONSE",
    0x96: "PING_RESPONSE",
    0x9F: "ERROR_RESPONSE",
}


def _reference_adler32(data: bytes) -> int:
    """Compute RFC 1950 Adler-32 without using the production implementation."""

    first = 1
    second = 0
    for byte in data:
        first = (first + byte) % _ADLER_MODULUS
        second = (second + first) % _ADLER_MODULUS
    return (second << 16) | first


@dataclass(frozen=True, slots=True)
class _GoldenVector:
    name: str
    kind: int
    payload: bytes
    flags: int = 0
    run_id: int = 0
    sequence: int = 0
    request_id: int = 0
    first_sample_ticks: int = 0
    item_count: int = 0


def _info_payload() -> bytes:
    payload = bytearray(98)
    struct.pack_into("<BBHBBBB", payload, 0, 0, 0, 0, 1, 1, 3, 3)
    struct.pack_into(
        "<IIIIIII",
        payload,
        8,
        2,
        0x3F,
        8_000_000,
        4_096,
        1_024,
        1_000_000,
        4_000_000,
    )
    struct.pack_into("<HHHBBBB", payload, 36, 8, 4, 2, 12, 2, 8, 0)
    payload[46:54] = bytes(range(6, 14))
    struct.pack_into("<I4BHH", payload, 54, 0x12345678, 0, 0, 0, 0, 0, 0)
    build_id = b"synthetic-golden-v1"
    payload[66 : 66 + len(build_id)] = build_id
    return bytes(payload)


def _golden_vectors() -> tuple[_GoldenVector, ...]:
    adc_payload = b"".join(
        struct.pack("<HH", 2 * pair_index, 2 * pair_index + 1)
        for pair_index in range(1_012)
    )
    gpio_payload = bytes(index & 0xFF for index in range(4_048))
    configuration = struct.pack("<BBBBI", 3, 1, 1, 0, 4_096)
    success_prefix = struct.pack("<BBH", 0, 0, 0)

    return (
        _GoldenVector(
            "adc-data",
            0x01,
            adc_payload,
            flags=0x0005,
            run_id=7,
            item_count=1_012,
        ),
        _GoldenVector(
            "gpio-data",
            0x02,
            gpio_payload,
            flags=0x0005,
            run_id=7,
            item_count=4_048,
        ),
        _GoldenVector("info-request", 0x10, b"", request_id=1),
        _GoldenVector(
            "configure-request",
            0x11,
            configuration,
            request_id=2,
        ),
        _GoldenVector("start-request", 0x12, b"", request_id=3),
        _GoldenVector("get-status-request", 0x13, b"", request_id=4),
        _GoldenVector("stop-request", 0x14, b"", request_id=5),
        _GoldenVector("reset-stats-request", 0x15, b"", request_id=6),
        _GoldenVector(
            "ping-request",
            0x16,
            struct.pack("<Q", 0x0123456789ABCDEF),
            request_id=7,
        ),
        _GoldenVector("info-response", 0x90, _info_payload(), request_id=1),
        _GoldenVector(
            "configure-response",
            0x91,
            success_prefix + configuration,
            request_id=2,
        ),
        _GoldenVector(
            "start-response",
            0x92,
            success_prefix + configuration,
            run_id=7,
            request_id=3,
        ),
        _GoldenVector(
            "get-status-response",
            0x93,
            struct.pack(
                "<BBHBBBBIQQQQIII",
                0,
                0,
                0,
                3,
                3,
                1,
                1,
                4_096,
                1,
                1,
                0,
                0,
                0,
                0,
                2,
            ),
            run_id=7,
            request_id=4,
        ),
        _GoldenVector(
            "stop-response",
            0x94,
            struct.pack("<BBHBBH", 0, 0, 0, 1, 0, 0),
            run_id=7,
            request_id=5,
        ),
        _GoldenVector(
            "reset-stats-response",
            0x95,
            struct.pack("<BBHI", 0, 0, 0, 3),
            run_id=7,
            request_id=6,
        ),
        _GoldenVector(
            "ping-response",
            0x96,
            struct.pack("<BBHQ", 0, 0, 0, 0x0123456789ABCDEF),
            run_id=7,
            request_id=7,
        ),
        _GoldenVector(
            "error-response",
            0x9F,
            struct.pack("<BBHBBH", 1, 0, 2, 0xFE, 1, 0),
            flags=0x8000,
            request_id=8,
        ),
    )


def _reference_frame(vector: _GoldenVector) -> bytes:
    total_length = _HEADER.size + len(vector.payload) + _TRAILER.size
    body = (
        _HEADER.pack(
            0xDEADBEEF,
            1,
            vector.kind,
            vector.flags,
            _HEADER.size,
            1,
            0,
            total_length,
            len(vector.payload),
            vector.run_id,
            vector.sequence,
            vector.request_id,
            vector.first_sample_ticks,
            vector.item_count,
        )
        + vector.payload
    )
    return body + _TRAILER.pack(_reference_adler32(body))


class ExhaustiveProtocolVectorTests(unittest.TestCase):
    def test_canonical_empty_and_nonempty_adler32_vectors(self) -> None:
        vectors = (
            (b"", 0x00000001),
            (b"a", 0x00620062),
            (b"Wikipedia", 0x11E60398),
            (b"123456789", 0x091E01DE),
        )

        for payload, expected in vectors:
            with self.subTest(payload=payload):
                self.assertEqual(expected, _reference_adler32(payload))
                self.assertEqual(expected, compute_checksum(payload))

    def test_every_frame_kind_matches_an_independent_wire_image(self) -> None:
        vectors = _golden_vectors()
        self.assertEqual(17, len(vectors))
        self.assertEqual(17, len({vector.kind for vector in vectors}))
        self.assertEqual(
            {f"{vector.name}.bin" for vector in vectors},
            {path.name for path in FIXTURE_DIRECTORY.glob("*.bin")},
        )

        for vector in vectors:
            with self.subTest(kind=f"0x{vector.kind:02x}"):
                expected = _reference_frame(vector)
                fixture = (FIXTURE_DIRECTORY / f"{vector.name}.bin").read_bytes()
                encoded = encode_frame(
                    vector.kind,
                    vector.payload,
                    flags=vector.flags,
                    run_id=vector.run_id,
                    sequence=vector.sequence,
                    request_id=vector.request_id,
                    first_sample_ticks=vector.first_sample_ticks,
                    item_count=vector.item_count,
                )
                decoded = decode_frame(expected)

                self.assertEqual(expected, fixture)
                self.assertEqual(expected, encoded)
                self.assertEqual(vector.kind, int(decoded.header.kind))
                self.assertEqual(vector.payload, decoded.payload)
                self.assertEqual(expected, decoded.to_bytes())

    def test_fixture_manifest_matches_independent_frames_byte_for_byte(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = {entry["file"]: entry for entry in manifest["fixtures"]}
        vectors = _golden_vectors()

        self.assertEqual(
            {f"{vector.name}.bin" for vector in vectors},
            set(entries),
        )
        for vector in vectors:
            filename = f"{vector.name}.bin"
            frame = _reference_frame(vector)
            entry = entries[filename]
            checksum = _TRAILER.unpack_from(frame, len(frame) - _TRAILER.size)[0]

            with self.subTest(filename=filename):
                self.assertEqual(_KIND_NAMES[vector.kind], entry["kind"])
                self.assertEqual(len(frame), entry["total_length"])
                self.assertEqual(len(vector.payload), entry["payload_length"])
                self.assertEqual(vector.flags, entry["flags"])
                self.assertEqual(vector.run_id, entry["run_id"])
                self.assertEqual(vector.sequence, entry["sequence"])
                self.assertEqual(vector.request_id, entry["request_id"])
                self.assertEqual(
                    vector.first_sample_ticks,
                    entry["first_sample_ticks"],
                )
                self.assertEqual(vector.item_count, entry["item_count"])
                self.assertEqual(f"0x{checksum:08x}", entry["checksum"])
                self.assertEqual(
                    hashlib.sha256(frame).hexdigest(), entry["frame_sha256"]
                )
                self.assertEqual(
                    hashlib.sha256(vector.payload).hexdigest(),
                    entry["payload_sha256"],
                )
                if len(frame) <= 256:
                    self.assertEqual(frame.hex(), entry["frame_hex"])
                else:
                    self.assertNotIn("frame_hex", entry)


if __name__ == "__main__":
    unittest.main()
