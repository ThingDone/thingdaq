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


if __name__ == "__main__":
    unittest.main()
