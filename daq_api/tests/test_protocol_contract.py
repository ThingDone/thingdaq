"""Cross-language and golden-vector checks for the protocol-v1 contract."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import struct
import subprocess
import sys
import unittest
import zlib
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

from teensy_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
MANIFEST_PATH = FIXTURE_DIRECTORY / "manifest.json"
GENERATOR_PATH = REPOSITORY_ROOT / "tools/generate_protocol.py"
CPP_CONSTANTS_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_constants.h"
PROTOCOL_DOCUMENT_PATH = REPOSITORY_ROOT / "doc/protocol/protocol-v1.md"
ADR_PATH = REPOSITORY_ROOT / "doc/decisions/adr-001-wire-protocol.md"
GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_protocol", GENERATOR_PATH
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
generate_protocol = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_protocol)


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

    def test_checksum_ids_and_bootstrap_algorithm_are_stable(self) -> None:
        self.assertEqual(1, constants.ChecksumAlgorithm.ADLER32)
        self.assertEqual(2, constants.ChecksumAlgorithm.CRC32C)
        self.assertEqual(3, constants.ChecksumAlgorithm.CRC32_ISO_HDLC)
        self.assertEqual(
            constants.ChecksumAlgorithm.ADLER32,
            constants.BOOTSTRAP_CHECKSUM_ALGORITHM,
        )
        self.assertEqual(
            constants.ChecksumAlgorithm.ADLER32,
            constants.DEFAULT_CHECKSUM_ALGORITHM,
        )
        self.assertEqual(
            frozenset(
                {
                    constants.ChecksumAlgorithm.ADLER32,
                    constants.ChecksumAlgorithm.CRC32C,
                    constants.ChecksumAlgorithm.CRC32_ISO_HDLC,
                }
            ),
            constants.SUPPORTED_CHECKSUM_ALGORITHMS,
        )
        self.assertEqual(0b1110, constants.SUPPORTED_CHECKSUM_MASK)

    def test_request_kinds_have_typed_response_kinds_and_error_codes(self) -> None:
        expected_pairs = {
            constants.FrameKind.INFO_REQUEST: constants.FrameKind.INFO_RESPONSE,
            constants.FrameKind.CONFIGURE_REQUEST: constants.FrameKind.CONFIGURE_RESPONSE,
            constants.FrameKind.START_REQUEST: constants.FrameKind.START_RESPONSE,
            constants.FrameKind.GET_STATUS_REQUEST: (
                constants.FrameKind.GET_STATUS_RESPONSE
            ),
            constants.FrameKind.STOP_REQUEST: constants.FrameKind.STOP_RESPONSE,
            constants.FrameKind.RESET_STATS_REQUEST: (
                constants.FrameKind.RESET_STATS_RESPONSE
            ),
            constants.FrameKind.PING_REQUEST: constants.FrameKind.PING_RESPONSE,
            constants.FrameKind.CHECKSUM_BENCHMARK_REQUEST: (
                constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE
            ),
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

    def test_command_ids_capabilities_and_bounds_are_generated_once(self) -> None:
        expected_commands = {
            constants.CommandKind.INFO: constants.FrameKind.INFO_REQUEST,
            constants.CommandKind.CONFIGURE: constants.FrameKind.CONFIGURE_REQUEST,
            constants.CommandKind.START: constants.FrameKind.START_REQUEST,
            constants.CommandKind.GET_STATUS: constants.FrameKind.GET_STATUS_REQUEST,
            constants.CommandKind.STOP: constants.FrameKind.STOP_REQUEST,
            constants.CommandKind.RESET_STATS: (
                constants.FrameKind.RESET_STATS_REQUEST
            ),
            constants.CommandKind.PING: constants.FrameKind.PING_REQUEST,
            constants.CommandKind.CHECKSUM_BENCHMARK: (
                constants.FrameKind.CHECKSUM_BENCHMARK_REQUEST
            ),
        }
        self.assertEqual(expected_commands, constants.COMMAND_REQUEST_KIND)
        for command, request_kind in expected_commands.items():
            with self.subTest(command=command.name):
                response_kind = constants.COMMAND_RESPONSE_KIND[command]
                self.assertEqual(int(command), int(request_kind))
                self.assertEqual(int(request_kind) | 0x80, int(response_kind))
                self.assertEqual(
                    command, constants.COMMAND_BY_REQUEST_KIND[request_kind]
                )
                self.assertEqual(
                    command, constants.COMMAND_BY_RESPONSE_KIND[response_kind]
                )

        self.assertEqual(4096, constants.MAX_DATA_FRAME_BYTES)
        self.assertEqual(56, constants.MAX_COMMAND_FRAME_BYTES)
        self.assertEqual(8, constants.MAX_COMMAND_PAYLOAD_BYTES)
        self.assertEqual(
            0x7F,
            int(
                constants.Capability.ADC_STREAM
                | constants.Capability.GPIO_STREAM
                | constants.Capability.HARDWARE_SOURCE
                | constants.Capability.SYNTHETIC_SOURCE
                | constants.Capability.RESET_STATS
                | constants.Capability.PING
                | constants.Capability.CHECKSUM_BENCHMARK
            ),
        )
        self.assertEqual(0x7F, constants.KNOWN_CAPABILITY_MASK)

    def test_scalar_field_table_and_control_schemas_are_unambiguous(self) -> None:
        self.assertEqual(
            {
                "u8": {"width": 1, "signed": False},
                "u16": {"width": 2, "signed": False},
                "u32": {"width": 4, "signed": False},
                "u64": {"width": 8, "signed": False},
            },
            self.contract["scalar_types"],
        )
        self.assertEqual(98, constants.INFO_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(56, constants.STATUS_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(8, constants.RESET_STATS_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(8, constants.PING_REQUEST_PAYLOAD_SIZE)
        self.assertEqual(12, constants.PING_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(8, constants.CHECKSUM_BENCHMARK_REQUEST_PAYLOAD_SIZE)
        self.assertEqual(96, constants.CHECKSUM_BENCHMARK_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(600_000_000, constants.CHECKSUM_BENCHMARK_CYCLE_COUNTER_HZ)
        self.assertEqual(
            8_100_000,
            constants.CHECKSUM_BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND,
        )
        self.assertEqual(8, constants.FrameFlag.OVERRUN_BEFORE)

    def test_generated_python_and_cpp_record_the_same_source_hash(self) -> None:
        source_hash = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
        cpp_constants = CPP_CONSTANTS_PATH.read_text(encoding="utf-8")

        self.assertEqual(source_hash, constants.SOURCE_SHA256)
        self.assertEqual(source_hash, self.manifest["source_sha256"])
        self.assertIn(source_hash, cpp_constants)
        self.assertIn("kMagic = 0xDEADBEEFU", cpp_constants)
        self.assertIn("kDataFrameBytes = 4096U", cpp_constants)

    def test_normative_tables_and_adr_links_track_the_contract(self) -> None:
        protocol_document = PROTOCOL_DOCUMENT_PATH.read_text(encoding="utf-8")
        adr = ADR_PATH.read_text(encoding="utf-8")

        for field in self.contract["header"]["fields"]:
            with self.subTest(header_field=field["name"]):
                self.assertIn(
                    f"| {field['offset']} | {generate_protocol.field_width(field)} "
                    f"| `{field['type']}` | No |",
                    protocol_document,
                )
        for kind in self.contract["frame_kinds"]:
            with self.subTest(frame_kind=kind["name"]):
                self.assertIn(
                    f"| `0x{kind['value']:02X}` | `{kind['name']}` |",
                    protocol_document,
                )
        for capability in self.contract["enums"]["capability_bits"]:
            with self.subTest(capability=capability["name"]):
                self.assertIn(
                    f"| `0x{capability['value']:08X}` | `{capability['name']}` |",
                    protocol_document,
                )

        self.assertIn("[[ADR-001-Wire-Protocol]]", protocol_document)
        self.assertIn("[[Protocol-V1]]", adr)
        self.assertTrue(protocol_document.startswith("---\ntype: reference\n"))
        self.assertTrue(adr.startswith("---\ntype: analysis\n"))

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

    def test_generator_check_reports_drift_without_rewriting_output(self) -> None:
        stderr = io.StringIO()
        generated_path = REPOSITORY_ROOT / "protocol/fixtures/stale-output.bin"

        with (
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "read_bytes", return_value=b"stale"),
            patch.object(Path, "write_bytes") as write_bytes,
            redirect_stderr(stderr),
        ):
            result = generate_protocol.check_outputs(
                {generated_path: b"expected generated bytes"}
            )

        self.assertEqual(1, result)
        self.assertIn(
            "Generated protocol files are missing or stale", stderr.getvalue()
        )
        self.assertIn("protocol/fixtures/stale-output.bin", stderr.getvalue())
        write_bytes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
