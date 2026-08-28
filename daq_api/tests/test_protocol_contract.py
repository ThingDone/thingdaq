"""Cross-language and golden-vector checks for the protocol-v1 contract."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path
from typing import Any, ClassVar

from teensy_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
MANIFEST_PATH = FIXTURE_DIRECTORY / "manifest.json"
GENERATOR_PATH = REPOSITORY_ROOT / "tools/generate_protocol.py"
CPP_CONSTANTS_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_constants.h"


class ProtocolContractTests(unittest.TestCase):
    contract: ClassVar[dict[str, Any]]
    manifest: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_header_and_frame_sizes_preserve_equal_stream_coverage(self) -> None:
        self.assertEqual("little", self.contract["byte_order"])
        self.assertEqual(0xDEADBEEF, constants.MAGIC)
        self.assertEqual(b"\xef\xbe\xad\xde", constants.MAGIC_BYTES)
        self.assertEqual(
            constants.HEADER_SIZE, struct.calcsize(constants.HEADER_STRUCT_FORMAT)
        )
        self.assertEqual(4096, constants.DATA_FRAME_BYTES)
        self.assertEqual(
            constants.DATA_FRAME_BYTES,
            constants.HEADER_SIZE
            + constants.DATA_PAYLOAD_BYTES
            + constants.TRAILER_SIZE,
        )

        adc_ticks = constants.ADC_PAIRS_PER_FRAME * constants.ADC_PAIR_PERIOD_TICKS
        gpio_ticks = (
            constants.GPIO_SAMPLES_PER_FRAME * constants.GPIO_SAMPLE_PERIOD_TICKS
        )
        self.assertEqual(constants.FRAME_COVERAGE_TICKS, adc_ticks)
        self.assertEqual(adc_ticks, gpio_ticks)
        self.assertEqual(8096, adc_ticks)

    def test_adler32_is_enabled_while_crc32c_keeps_a_stable_id(self) -> None:
        self.assertEqual(1, constants.ChecksumAlgorithm.ADLER32)
        self.assertEqual(2, constants.ChecksumAlgorithm.CRC32C)
        self.assertEqual(
            constants.ChecksumAlgorithm.ADLER32,
            constants.DEFAULT_CHECKSUM_ALGORITHM,
        )
        self.assertEqual(
            frozenset({constants.ChecksumAlgorithm.ADLER32}),
            constants.SUPPORTED_CHECKSUM_ALGORITHMS,
        )

    def test_request_kinds_have_typed_response_kinds_and_error_codes(self) -> None:
        expected_pairs = {
            constants.FrameKind.INFO_REQUEST: constants.FrameKind.INFO_RESPONSE,
            constants.FrameKind.CONFIGURE_REQUEST: constants.FrameKind.CONFIGURE_RESPONSE,
            constants.FrameKind.START_REQUEST: constants.FrameKind.START_RESPONSE,
            constants.FrameKind.STATUS_REQUEST: constants.FrameKind.STATUS_RESPONSE,
            constants.FrameKind.STOP_REQUEST: constants.FrameKind.STOP_RESPONSE,
        }
        self.assertEqual(expected_pairs, constants.REQUEST_RESPONSE_KIND)
        self.assertEqual(0, constants.ErrorCode.OK)
        self.assertGreater(constants.ErrorCode.CHECKSUM_MISMATCH, 0)
        self.assertLessEqual(
            constants.INFO_RESPONSE_PAYLOAD_SIZE
            + constants.HEADER_SIZE
            + constants.TRAILER_SIZE,
            constants.MAX_CONTROL_FRAME_BYTES,
        )

    def test_generated_python_and_cpp_record_the_same_source_hash(self) -> None:
        source_hash = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
        cpp_constants = CPP_CONSTANTS_PATH.read_text(encoding="utf-8")

        self.assertEqual(source_hash, constants.SOURCE_SHA256)
        self.assertEqual(source_hash, self.manifest["source_sha256"])
        self.assertIn(source_hash, cpp_constants)
        self.assertIn("kMagic = 0xDEADBEEFU", cpp_constants)
        self.assertIn("kDataFrameBytes = 4096U", cpp_constants)

    def test_every_frame_kind_has_a_structurally_valid_golden_frame(self) -> None:
        entries = self.manifest["fixtures"]
        self.assertEqual(
            {kind.name for kind in constants.FrameKind},
            {entry["kind"] for entry in entries},
        )

        for entry in entries:
            with self.subTest(fixture=entry["file"]):
                frame = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
                header = struct.unpack(
                    constants.HEADER_STRUCT_FORMAT,
                    frame[: constants.HEADER_SIZE],
                )
                (
                    magic,
                    version,
                    kind,
                    flags,
                    header_length,
                    checksum_algorithm,
                    reserved,
                    total_length,
                    payload_length,
                    run_id,
                    sequence,
                    request_id,
                    first_sample_ticks,
                    item_count,
                ) = header
                trailer_checksum = struct.unpack("<I", frame[-4:])[0]

                self.assertEqual(constants.MAGIC, magic)
                self.assertEqual(constants.PROTOCOL_VERSION, version)
                self.assertEqual(constants.FrameKind[entry["kind"]], kind)
                self.assertEqual(entry["flags"], flags)
                self.assertEqual(constants.HEADER_SIZE, header_length)
                self.assertEqual(
                    constants.ChecksumAlgorithm.ADLER32, checksum_algorithm
                )
                self.assertEqual(0, reserved)
                self.assertEqual(len(frame), total_length)
                self.assertEqual(entry["total_length"], total_length)
                self.assertEqual(entry["payload_length"], payload_length)
                self.assertEqual(
                    total_length - constants.MIN_FRAME_BYTES, payload_length
                )
                self.assertEqual(entry["run_id"], run_id)
                self.assertEqual(entry["sequence"], sequence)
                self.assertEqual(entry["request_id"], request_id)
                self.assertEqual(entry["first_sample_ticks"], first_sample_ticks)
                self.assertEqual(entry["item_count"], item_count)
                self.assertEqual(
                    zlib.adler32(frame[:-4]) & 0xFFFFFFFF, trailer_checksum
                )
                self.assertEqual(entry["checksum"], f"0x{trailer_checksum:08x}")
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(frame).hexdigest()
                )
                self.assertEqual(
                    entry["payload_sha256"],
                    hashlib.sha256(
                        frame[
                            constants.HEADER_SIZE : constants.HEADER_SIZE
                            + payload_length
                        ]
                    ).hexdigest(),
                )

    def test_data_golden_payloads_use_the_defined_wire_order(self) -> None:
        adc_frame = (FIXTURE_DIRECTORY / "adc-data.bin").read_bytes()
        gpio_frame = (FIXTURE_DIRECTORY / "gpio-data.bin").read_bytes()
        adc_payload = adc_frame[constants.HEADER_SIZE : -constants.TRAILER_SIZE]
        gpio_payload = gpio_frame[constants.HEADER_SIZE : -constants.TRAILER_SIZE]

        self.assertEqual((0, 1, 2, 3), struct.unpack_from("<HHHH", adc_payload))
        last_pair_offset = (constants.ADC_PAIRS_PER_FRAME - 1) * 4
        self.assertEqual(
            (2022, 2023), struct.unpack_from("<HH", adc_payload, last_pair_offset)
        )
        self.assertEqual(bytes(range(16)), gpio_payload[:16])
        self.assertEqual(4048, len(gpio_payload))

    def test_generator_check_mode_detects_no_drift(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(GENERATOR_PATH), "--check"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Protocol outputs are current", completed.stdout)


if __name__ == "__main__":
    unittest.main()
