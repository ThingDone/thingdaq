"""Independent wire-vector tests for every protocol-v1 frame kind."""

from __future__ import annotations

import hashlib
import json
import struct
import unittest
from dataclasses import dataclass
from pathlib import Path

from thingdaq import compute_checksum, decode_frame, encode_frame

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
    0x17: "CHECKSUM_BENCHMARK_REQUEST",
    0x18: "GPIO_CLOCK_DIAGNOSTIC_REQUEST",
    0x19: "GPIO_CAPTURE_DIAGNOSTIC_REQUEST",
    0x90: "INFO_RESPONSE",
    0x91: "CONFIGURE_RESPONSE",
    0x92: "START_RESPONSE",
    0x93: "GET_STATUS_RESPONSE",
    0x94: "STOP_RESPONSE",
    0x95: "RESET_STATS_RESPONSE",
    0x96: "PING_RESPONSE",
    0x97: "CHECKSUM_BENCHMARK_RESPONSE",
    0x98: "GPIO_CLOCK_DIAGNOSTIC_RESPONSE",
    0x99: "GPIO_CAPTURE_DIAGNOSTIC_RESPONSE",
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


def _pack_adc_trigger_reference(payload: bytearray, base: int) -> None:
    """Pack the independent default trigger-plan image used by fixtures."""

    struct.pack_into(
        "<IIIII",
        payload,
        base + 8,
        24_000_000,
        600_000_000,
        4_000_000,
        1_000_000,
        150_000_000,
    )
    payload[base + 28 : base + 40] = bytes((0, 1, 5, 3, 0, 1, 57, 57, 103, 107, 0, 4))
    struct.pack_into("<HHHHH", payload, base + 40, 0, 75, 1, 76, 75)
    struct.pack_into("<II", payload, base + 124, 300, 120)


def _info_payload() -> bytes:
    payload = bytearray(376)
    struct.pack_into("<BBHBBBB", payload, 0, 0, 0, 0, 1, 1, 3, 3)
    struct.pack_into(
        "<IIIIIII",
        payload,
        8,
        14,
        0x1FF,
        8_000_000,
        4_096,
        1_280,
        1_000_000,
        4_000_000,
    )
    struct.pack_into("<HHHBBBB", payload, 36, 8, 4, 2, 12, 2, 8, 1)
    payload[46:54] = bytes(range(6, 14))
    struct.pack_into("<I4BHH", payload, 54, 0x12345678, 0, 0, 0, 0, 0, 0)
    build_id = b"synthetic-golden-v1"
    payload[66 : 66 + len(build_id)] = build_id
    struct.pack_into("<BBBBH", payload, 98, 8, 4, 4, 0, 3)
    struct.pack_into("<IIIH", payload, 104, 4048, 64768, 16256, 200)
    struct.pack_into("<BBBBBBBB", payload, 120, 0, 56, 0, 2, 30, 0, 1, 0)
    struct.pack_into(
        "<HHBBBBHHHBBH",
        payload,
        128,
        0,
        4095,
        1,
        1,
        4,
        0,
        3300,
        0,
        3300,
        3,
        2,
        142,
    )
    struct.pack_into("<BBBBBBBBH", payload, 146, 0, 0, 14, 15, 1, 2, 7, 8, 0)
    struct.pack_into("<IIIIII", payload, 156, 150_000_000, 37_500_000, 10_000, 0, 0, 0)
    _pack_adc_trigger_reference(payload, 180)
    struct.pack_into("<BBHHHHHI", payload, 324, 0, 0, 63, 4048, 1012, 4048, 0, 8096)
    payload[340:350] = bytes((8, 4, 0, 1, 2, 1, 24, 88, 48, 64))
    struct.pack_into(
        "<HIHHHHHBBII",
        payload,
        350,
        1012,
        32512,
        200,
        105,
        95,
        200,
        200,
        4,
        4,
        4_000_000,
        4_047_431,
    )
    return bytes(payload)


def _status_payload() -> bytes:
    payload = bytearray(1228)
    struct.pack_into(
        "<BBHBBBBIQQQQIII",
        payload,
        0,
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
    )
    struct.pack_into("<H", payload, 134, 1234)
    struct.pack_into("<BBBB", payload, 172, 12, 2, 0, 0)
    struct.pack_into(
        "<HHBBBBHHHBBH",
        payload,
        176,
        0,
        4095,
        1,
        1,
        4,
        0,
        3300,
        0,
        3300,
        3,
        2,
        142,
    )
    struct.pack_into("<BBBBBB", payload, 194, 14, 15, 1, 2, 7, 8)
    struct.pack_into("<IIIIII", payload, 200, 150_000_000, 37_500_000, 10_000, 0, 0, 0)
    _pack_adc_trigger_reference(payload, 224)
    struct.pack_into(
        "<16Q",
        payload,
        576,
        1,
        1012,
        1,
        1012,
        1012,
        1,
        1012,
        0,
        1,
        4048,
        1,
        4048,
        4048,
        1,
        4048,
        0,
    )
    struct.pack_into(
        "<16Q",
        payload,
        704,
        4048,
        4048,
        4048,
        4048,
        0,
        4096,
        4096,
        4096,
        4048,
        4048,
        4048,
        4048,
        0,
        4096,
        4096,
        4096,
    )
    struct.pack_into("<10H", payload, 832, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2)
    struct.pack_into("<5Q", payload, 852, 2, 0, 0, 8096, 8192)
    struct.pack_into("<18I", payload, 892, 0, 0, 0, 0, 0, 4, *([0] * 12))
    struct.pack_into("<6H", payload, 964, 0, 0, 0, 1, 1, 0)
    struct.pack_into("<4I", payload, 1008, 3, 3, 0, 0)
    return bytes(payload)


def _gpio_clock_diagnostic_payload() -> bytes:
    payload = bytearray(140)
    struct.pack_into("<BBH", payload, 0, 0, 0, 0)
    for offset, value in enumerate(
        (
            1_000_000,
            4_000_000,
            24_000_000,
            23,
            4096,
            4096,
            4096,
            600_000_000,
            2_457_600,
            0,
            64,
            12_288,
            12_582_912,
            192,
            0,
            23,
            22,
            1,
            1,
        )
    ):
        struct.pack_into("<I", payload, 4 + 4 * offset, value)
    struct.pack_into("<HH", payload, 80, 56, 5)
    for offset, value in enumerate(
        (
            0x8000001E,
            2,
            0,
            4,
            0,
            0,
            0x401BC008,
            0x20200000,
            4,
            0x00030C0F,
        )
    ):
        struct.pack_into("<I", payload, 84 + 4 * offset, value)
    struct.pack_into("<HHHH", payload, 124, 4112, 8208, 8, 0x0202)
    struct.pack_into("<BBBBBBH", payload, 132, 0, 56, 0, 2, 30, 0, 0)
    return bytes(payload)


def _gpio_capture_diagnostic_payload() -> bytes:
    payload = bytearray(144)
    struct.pack_into("<BBHBBBB", payload, 0, 0, 0, 0, 0, 1, 0, 0)
    struct.pack_into("<IIIIIIQ", payload, 8, 0, 0, 0, 307, 600_000_000, 607_200, 4055)
    struct.pack_into(
        "<IIIIIIHHHHBBBB",
        payload,
        40,
        4048,
        256,
        7,
        0,
        199695,
        0,
        0,
        0,
        0,
        0,
        0,
        255,
        90,
        90,
    )
    struct.pack_into(
        "<IIIIIIIIIIIIIIHHHBBI",
        payload,
        76,
        199695,
        0,
        0,
        199695,
        0,
        0,
        132099,
        132099,
        132099,
        5,
        1,
        0x8000001E,
        4,
        0,
        4048,
        4048,
        18,
        0,
        0,
        256,
    )
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
        _GoldenVector(
            "checksum-benchmark-request",
            0x17,
            struct.pack("<BBBBHH", 1, 1, 0, 0, 4, 64),
            request_id=8,
        ),
        _GoldenVector(
            "gpio-clock-diagnostic-request",
            0x18,
            struct.pack("<IHH", 1_000_000, 4096, 0),
            request_id=9,
        ),
        _GoldenVector("gpio-capture-diagnostic-request", 0x19, b"", request_id=10),
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
            _status_payload(),
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
            "checksum-benchmark-response",
            0x97,
            struct.pack(
                "<BBHBBBBHHIIIIIIIQQQQIIIIII",
                0,
                0,
                0,
                1,
                1,
                0,
                0,
                4,
                64,
                9,
                600_000_000,
                4,
                120,
                0,
                8_192,
                0x12345678,
                2_304,
                10_240,
                9_216,
                0,
                2_304,
                2_304,
                262_144,
                9_830_400,
                353_894,
                8_100_000,
            ),
            request_id=8,
        ),
        _GoldenVector(
            "gpio-clock-diagnostic-response",
            0x98,
            _gpio_clock_diagnostic_payload(),
            request_id=9,
        ),
        _GoldenVector(
            "gpio-capture-diagnostic-response",
            0x99,
            _gpio_capture_diagnostic_payload(),
            request_id=10,
        ),
        _GoldenVector(
            "error-response",
            0x9F,
            struct.pack("<BBHBBH", 1, 0, 2, 0xFE, 1, 0),
            flags=0x8000,
            request_id=11,
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
        self.assertEqual(23, len(vectors))
        self.assertEqual(23, len({vector.kind for vector in vectors}))
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
