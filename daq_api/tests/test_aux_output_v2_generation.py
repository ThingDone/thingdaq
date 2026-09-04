"""Generated-surface and golden-vector tests for auxiliary output protocol v2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import unittest
import zlib
from pathlib import Path
from typing import Any, ClassVar

from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.output import DigitalOutputAppendEcho, DigitalOutputStatus
from thingdaq.protocol import IncrementalFrameParser
from thingdaq.protocol_v2 import V2Frame, decode_v2_response, encode_v2_frame

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
V2_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
GENERATOR_PATH = REPOSITORY_ROOT / "tools/generate_protocol.py"
MANIFEST_PATH = REPOSITORY_ROOT / "protocol/fixtures-v2/manifest.json"
CPP_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_v2_constants.h"

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_protocol_v2_test", GENERATOR_PATH
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
generate_protocol = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_protocol)

_FROZEN_V1_HASHES = {
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


class AuxOutputV2GenerationTests(unittest.TestCase):
    v1: ClassVar[dict[str, Any]]
    v2: ClassVar[dict[str, Any]]
    source_bytes: ClassVar[bytes]
    manifest: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
        cls.source_bytes = V2_PATH.read_bytes()
        cls.v2 = json.loads(cls.source_bytes)
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_v2_outputs_are_deterministic_current_and_disjoint(self) -> None:
        generate_protocol.validate_v2_contract(self.v2, self.v1, V1_PATH.read_bytes())
        first = generate_protocol.expected_v2_outputs(self.v2, self.source_bytes)
        second = generate_protocol.expected_v2_outputs(self.v2, self.source_bytes)
        self.assertEqual(first, second)
        self.assertEqual(55, len(first))
        for path, expected in first.items():
            with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                self.assertEqual(expected, path.read_bytes())
                self.assertNotIn(
                    path,
                    generate_protocol.expected_outputs(self.v1, V1_PATH.read_bytes()),
                )

    def test_v1_sources_and_outputs_remain_byte_stable(self) -> None:
        for relative_path, expected in _FROZEN_V1_HASHES.items():
            with self.subTest(path=relative_path):
                contents = (REPOSITORY_ROOT / relative_path).read_bytes()
                self.assertEqual(expected, hashlib.sha256(contents).hexdigest())

    def test_generated_python_and_cpp_publish_exact_output_metadata(self) -> None:
        self.assertEqual(2, constants.PROTOCOL_VERSION)
        self.assertEqual(1_000_000, constants.OUTPUT_RATE_HZ)
        self.assertEqual(8, constants.OUTPUT_PERIOD_TICKS)
        self.assertEqual(1024, constants.OUTPUT_SEGMENT_CAPACITY)
        self.assertEqual(0xFF, constants.OUTPUT_LEGAL_STATE_MASK)
        self.assertEqual(tuple(range(16, 24)), constants.OUTPUT_PINS_BY_LOGICAL_BIT)
        self.assertEqual(
            (23, 22, 17, 16, 26, 27, 24, 25),
            constants.OUTPUT_GPIO_BITS_BY_LOGICAL_BIT,
        )
        self.assertEqual(0x0FC30000, constants.OUTPUT_GPIO_AGGREGATE_MASK)
        self.assertEqual((3, 2), constants.OUTPUT_ADC_EDMA_PRIORITIES)
        self.assertEqual(1, constants.OUTPUT_EDMA_PRIORITY)
        self.assertEqual(0, constants.OUTPUT_GPIO_EDMA_PRIORITY)
        self.assertEqual(
            (3, 19, 56),
            (
                constants.OUTPUT_DMA_IRQ_NUMBER,
                constants.OUTPUT_DMA_VECTOR_INDEX,
                constants.OUTPUT_DMA_IRQ_PRIORITY,
            ),
        )
        self.assertEqual(8_192, constants.OUTPUT_PROGRAM_STORAGE_BYTES)
        self.assertEqual(16_256, constants.OUTPUT_DMA_RING_BYTES)
        self.assertEqual(128, constants.OUTPUT_DMA_DESCRIPTOR_BYTES)
        self.assertEqual(
            (103, 91),
            (
                constants.OUTPUT_PACKET_PRIMARY_COUNT,
                constants.OUTPUT_PACKET_RESERVE_COUNT,
            ),
        )
        self.assertEqual(98_164, constants.OUTPUT_PACKET_RETENTION_US)
        self.assertEqual(99_176, constants.OUTPUT_PACKET_AND_USB_RETENTION_US)
        self.assertEqual(0x200, int(constants.Capability.PRELOADED_AUXILIARY_OUTPUT))
        self.assertEqual(0x400, int(constants.Capability.COMMON_EPOCH_OUTPUT))
        self.assertEqual(32, int(constants.CommandKind.OUTPUT_BEGIN))
        self.assertEqual(37, int(constants.CommandKind.OUTPUT_CLEAR))
        self.assertEqual(6, int(constants.OutputState.FAULTED))
        self.assertEqual(9, int(constants.OutputError.RELEASE_FAILED))

        cpp = CPP_PATH.read_text(encoding="utf-8")
        for token in (
            "namespace thingdaq::protocol_v2",
            "kOutputRateHz = 1000000U",
            "kOutputSegmentCapacity = 1024U",
            "kOutputGpioAggregateMask = 264437760U",
            "enum class OutputState : std::uint8_t",
            "kOutputStatusResponse = 164U",
        ):
            with self.subTest(token=token):
                self.assertIn(token, cpp)

    def test_every_output_request_is_bounded_and_has_a_response(self) -> None:
        kinds = {entry["name"]: entry for entry in self.v2["frame_kinds"]}
        schemas = self.v2["payload_schemas"]
        commands = [
            entry
            for entry in self.v2["command_kinds"]
            if entry["name"].startswith("OUTPUT_")
        ]
        self.assertEqual(6, len(commands))
        for command in commands:
            request = kinds[command["request_kind"]]
            response = kinds[command["response_kind"]]
            with self.subTest(command=command["name"]):
                self.assertLessEqual(
                    schemas[request["payload_schema"]]["size"],
                    constants.MAX_COMMAND_PAYLOAD_BYTES,
                )
                self.assertEqual(command["value"] | 0x80, response["value"])
                self.assertEqual(command["response_kind"], request["response_kind"])

    def test_manifest_covers_lifecycle_and_every_named_rejection(self) -> None:
        entries = self.manifest["fixtures"]
        states = {
            entry["expected"]["output_state"]
            for entry in entries
            if entry.get("expected", {}).get("outcome") == "success"
            and "output_state" in entry["expected"]
        }
        errors = {
            entry["expected"]["case"]: entry["expected"]["output_error"]
            for entry in entries
            if entry.get("expected", {}).get("outcome") == "error"
        }
        self.assertEqual(
            {"EMPTY", "LOADING", "COMMITTED", "ARMED", "RUNNING", "HELD", "FAULTED"},
            states,
        )
        self.assertEqual(
            {
                "zero_duration",
                "high_state_bits",
                "adjacent_duplicate",
                "duration_overflow",
                "capacity_exceeded",
                "checksum_mismatch",
                "generation_mismatch",
                "illegal_lifecycle",
                "truncated_upload",
                "stale_replay",
            },
            set(errors),
        )
        self.assertEqual("TRUNCATED_UPLOAD", errors["truncated_upload"])
        self.assertEqual("GENERATION_MISMATCH", errors["stale_replay"])

    def test_every_v2_frame_has_valid_header_checksum_and_manifest_hash(self) -> None:
        for entry in self.manifest["fixtures"]:
            frame = (MANIFEST_PATH.parent / entry["file"]).read_bytes()
            with self.subTest(fixture=entry["file"]):
                self.assertEqual(0xDEADBEEF, struct.unpack_from("<I", frame)[0])
                self.assertEqual(2, frame[4])
                self.assertEqual(len(frame), struct.unpack_from("<I", frame, 12)[0])
                self.assertEqual(
                    zlib.adler32(frame[:-4]) & 0xFFFFFFFF,
                    struct.unpack_from("<I", frame, len(frame) - 4)[0],
                )
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(frame).hexdigest()
                )
                if entry["kind"].startswith("OUTPUT_"):
                    self.assertNotEqual(0, entry["run_id"])

    def test_successful_operation_pairs_echo_request_and_generation(self) -> None:
        entries = {entry["file"]: entry for entry in self.manifest["fixtures"]}
        for operation in ("begin", "append", "commit", "arm", "status", "clear"):
            request = entries[f"output-{operation}-request.bin"]
            response = entries[f"output-{operation}-response.bin"]
            with self.subTest(operation=operation):
                self.assertEqual(request["request_id"], response["request_id"])
                self.assertEqual(request["run_id"], response["run_id"])
                self.assertLessEqual(request["payload_length"], 8)

    def test_every_info_and_output_golden_crosses_byte_fragmented_parser(self) -> None:
        syntactically_invalid = {
            "output-malformed-zero-duration.bin",
            "output-malformed-high-state-bits.bin",
        }
        selected = [
            entry
            for entry in self.manifest["fixtures"]
            if entry["kind"].startswith("OUTPUT_")
            or entry["kind"] in {"INFO_REQUEST", "INFO_RESPONSE"}
        ]
        self.assertEqual(31, len(selected))
        for entry in selected:
            with self.subTest(fixture=entry["file"]):
                parser = IncrementalFrameParser(accept_protocol_v2=True)
                decoded: list[object] = []
                wire = (MANIFEST_PATH.parent / entry["file"]).read_bytes()
                for byte in wire:
                    decoded.extend(parser.feed(bytes((byte,))))
                if entry["file"] in syntactically_invalid:
                    self.assertEqual([], decoded)
                    self.assertEqual(1, parser.payload_errors)
                    continue
                self.assertEqual(1, len(decoded))
                frame = decoded[0]
                self.assertIsInstance(frame, V2Frame)
                assert isinstance(frame, V2Frame)
                self.assertEqual(entry["kind"], frame.header.kind.name)
                self.assertEqual(entry["run_id"], frame.header.run_id)
                self.assertEqual(entry["request_id"], frame.header.request_id)
                self.assertEqual(wire, frame.to_bytes())
                self.assertEqual(0, parser.errors)

    def test_every_success_response_decodes_to_exact_typed_surface(self) -> None:
        successful = [
            entry
            for entry in self.manifest["fixtures"]
            if entry.get("expected", {}).get("outcome") == "success"
        ]
        self.assertEqual(13, len(successful))
        for entry in successful:
            with self.subTest(fixture=entry["file"]):
                parser = IncrementalFrameParser(accept_protocol_v2=True)
                frames = parser.feed(
                    (MANIFEST_PATH.parent / entry["file"]).read_bytes()
                )
                self.assertEqual(1, len(frames))
                frame = frames[0]
                assert isinstance(frame, V2Frame)
                response = decode_v2_response(frame)
                self.assertTrue(response.ok)
                if frame.header.kind is constants.FrameKind.OUTPUT_APPEND_RESPONSE:
                    self.assertIsInstance(response.value, DigitalOutputAppendEcho)
                else:
                    self.assertIsInstance(response.value, DigitalOutputStatus)
                    assert isinstance(response.value, DigitalOutputStatus)
                    self.assertIs(
                        constants.OutputState[entry["expected"]["output_state"]],
                        response.value.state,
                    )

    def test_every_output_response_and_error_enum_decodes_as_typed_failure(
        self,
    ) -> None:
        response_kinds = tuple(
            kind
            for kind in constants.FrameKind
            if kind.name.startswith("OUTPUT_") and kind.name.endswith("_RESPONSE")
        )
        output_errors = tuple(
            error
            for error in constants.OutputError
            if error is not constants.OutputError.NONE
        )
        self.assertEqual(6, len(response_kinds))
        self.assertEqual(9, len(output_errors))
        for kind in response_kinds:
            for output_error in output_errors:
                with self.subTest(kind=kind.name, output_error=output_error.name):
                    payload = bytearray(constants.OUTPUT_STATUS_RESPONSE_PAYLOAD_SIZE)
                    payload[0] = int(constants.ResponseStatus.ERROR)
                    struct.pack_into(
                        "<H", payload, 2, int(constants.ErrorCode.INVALID_PAYLOAD)
                    )
                    payload[constants.OUTPUT_STATUS_RESPONSE_OUTPUT_ERROR_OFFSET] = int(
                        output_error
                    )
                    wire = encode_v2_frame(
                        kind,
                        payload,
                        flags=constants.FrameFlag.RESPONSE_ERROR,
                        run_id=99,
                        request_id=100,
                    )
                    frames = IncrementalFrameParser(accept_protocol_v2=True).feed(wire)
                    self.assertEqual(1, len(frames))
                    frame = frames[0]
                    assert isinstance(frame, V2Frame)
                    response = decode_v2_response(frame)
                    self.assertFalse(response.ok)
                    self.assertIs(output_error, response.output_error)
                    self.assertIsNone(response.value)

    def test_default_v1_parser_rejects_v2_without_weakening_v1_bytes(self) -> None:
        v2_wire = (MANIFEST_PATH.parent / "output-status-request.bin").read_bytes()
        parser = IncrementalFrameParser()
        self.assertEqual([], parser.feed(v2_wire))
        self.assertGreater(parser.header_errors, 0)

        v1_manifest = json.loads(
            (REPOSITORY_ROOT / "protocol/fixtures/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        v1_parser = IncrementalFrameParser()
        decoded = []
        for entry in v1_manifest["fixtures"]:
            decoded.extend(
                v1_parser.feed(
                    (REPOSITORY_ROOT / "protocol/fixtures" / entry["file"]).read_bytes()
                )
            )
        self.assertEqual(len(v1_manifest["fixtures"]), len(decoded))
        self.assertEqual(0, v1_parser.errors)


if __name__ == "__main__":
    unittest.main()
