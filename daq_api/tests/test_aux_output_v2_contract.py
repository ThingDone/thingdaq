"""Independent tests for the frozen experimental auxiliary-output contract."""

from __future__ import annotations

import hashlib
import json
import struct
import unittest
import zlib
from pathlib import Path
from typing import Any, ClassVar

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
V2_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
V1_FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
V1_MANIFEST_PATH = V1_FIXTURE_DIRECTORY / "manifest.json"
ADR_PATH = REPOSITORY_ROOT / "doc/decisions/adr-008-experimental-aux-output-bank.md"
DOC_INDEX_PATH = REPOSITORY_ROOT / "doc/README.md"

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


def _by_name(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(entry["name"]): entry for entry in entries}


class AuxOutputV2ContractTests(unittest.TestCase):
    v1: ClassVar[dict[str, Any]]
    v2: ClassVar[dict[str, Any]]
    output: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = json.loads(V1_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.v2 = json.loads(V2_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.output = cls.v2["auxiliary_output"]

    def test_v2_pins_v1_and_uses_disjoint_generated_outputs(self) -> None:
        self.assertEqual(1, self.v1["protocol_version"])
        self.assertEqual(2, self.v2["protocol_version"])
        self.assertEqual("experimental", self.v2["status"])
        self.assertEqual("aux-output-bank", self.v2["extension"])
        self.assertEqual(
            _FROZEN_V1_SHA256["protocol/protocol-v1.json"],
            self.v2["extends"]["source_sha256"],
        )
        self.assertEqual("protocol/protocol-v1.json", self.v2["extends"]["source"])

        v1_outputs = {
            "daq_api/src/thingdaq/_generated/protocol_constants.py",
            "firmware/src/generated/protocol_constants.h",
            "protocol/fixtures",
            "protocol/fixtures/manifest.json",
        }
        v2_outputs = set(self.v2["generated_outputs"].values())
        self.assertTrue(v1_outputs.isdisjoint(v2_outputs))
        self.assertEqual(len(v2_outputs), len(self.v2["generated_outputs"]))

    def test_frozen_v1_sources_generated_files_and_fixtures_are_unchanged(
        self,
    ) -> None:
        for relative_path, expected_hash in _FROZEN_V1_SHA256.items():
            with self.subTest(path=relative_path):
                contents = (REPOSITORY_ROOT / relative_path).read_bytes()
                self.assertEqual(expected_hash, hashlib.sha256(contents).hexdigest())

        manifest = json.loads(V1_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            _FROZEN_V1_SHA256["protocol/protocol-v1.json"],
            manifest["source_sha256"],
        )
        self.assertEqual(23, len(manifest["fixtures"]))
        for entry in manifest["fixtures"]:
            with self.subTest(fixture=entry["file"]):
                fixture = (V1_FIXTURE_DIRECTORY / entry["file"]).read_bytes()
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(fixture).hexdigest()
                )

    def test_default_acquisition_contract_remains_v1(self) -> None:
        for key in (
            "byte_order",
            "magic",
            "scalar_types",
            "header",
            "trailer",
            "limits",
            "configuration_semantics",
            "timing",
            "data_layouts",
            "flags",
            "checksum_algorithms",
            "bootstrap_checksum_algorithm",
            "default_checksum_algorithm",
        ):
            with self.subTest(key=key):
                self.assertEqual(self.v1[key], self.v2[key])

        v1_error = self.v1["frame_kinds"][-1]
        self.assertEqual(
            self.v1["frame_kinds"][:-1],
            self.v2["frame_kinds"][: len(self.v1["frame_kinds"]) - 1],
        )
        self.assertEqual(v1_error, self.v2["frame_kinds"][-1])
        self.assertEqual(
            self.v1["command_kinds"],
            self.v2["command_kinds"][: len(self.v1["command_kinds"])],
        )
        for schema_name, v1_schema in self.v1["payload_schemas"].items():
            with self.subTest(schema=schema_name):
                if schema_name == "info_response":
                    self.assertEqual(
                        v1_schema["fields"],
                        self.v2["payload_schemas"][schema_name]["fields"][
                            : len(v1_schema["fields"])
                        ],
                    )
                else:
                    self.assertEqual(v1_schema, self.v2["payload_schemas"][schema_name])

        self.assertEqual(
            _by_name(self.v1["enums"]["capability_bits"]),
            {
                name: entry
                for name, entry in _by_name(self.v2["enums"]["capability_bits"]).items()
                if name not in {"PRELOADED_AUXILIARY_OUTPUT", "COMMON_EPOCH_OUTPUT"}
            },
        )

    def test_bank_is_whole_output_or_disabled_and_defaults_safe(self) -> None:
        modes = {
            name: int(entry["value"])
            for name, entry in _by_name(self.v2["enums"]["output_bank_mode"]).items()
        }
        self.assertEqual({"DISABLED": 0, "OUTPUT": 1}, modes)
        self.assertEqual(["DISABLED", "OUTPUT"], self.output["supported_modes"])
        self.assertEqual("whole_bank", self.output["direction_granularity"])
        self.assertNotIn("INPUT", modes)
        self.assertIn("mixed direction", self.output["direction_rule"])
        self.assertIn("inputs", self.output["pins_remain_inputs_until"])

        capabilities = _by_name(self.v2["enums"]["capability_bits"])
        self.assertEqual(0x200, capabilities["PRELOADED_AUXILIARY_OUTPUT"]["value"])
        self.assertEqual(0x400, capabilities["COMMON_EPOCH_OUTPUT"]["value"])

    def test_pin_map_rate_and_common_epoch_are_exact(self) -> None:
        pins = self.output["pin_bank"]
        self.assertEqual(list(range(16, 24)), pins["teensy_pins_by_logical_bit"])
        self.assertEqual(
            [23, 22, 17, 16, 26, 27, 24, 25],
            pins["standard_gpio_bits_by_logical_bit"],
        )
        self.assertEqual(0x0FC30000, pins["aggregate_mask"])
        self.assertEqual(
            (1, 6, 26),
            tuple(
                pins[key]
                for key in (
                    "standard_gpio",
                    "fast_gpio",
                    "fast_select_gpr",
                )
            ),
        )

        timing = self.output["timing"]
        self.assertTrue(timing["preloaded"])
        self.assertFalse(timing["host_edge_scheduling"])
        self.assertEqual(1_000_000, timing["output_rate_hz"])
        self.assertEqual(1, timing["duration_quantum_us"])
        self.assertEqual(8_000_000, timing["timestamp_hz"])
        self.assertEqual(8, timing["output_period_ticks"])
        self.assertEqual("PIT1", timing["clock_owner"])
        self.assertEqual(0, timing["first_event_tick"])

    def test_segment_encoding_canonicalization_checksum_and_capacity(self) -> None:
        program = self.output["program"]
        schema = program["segment_schema"]
        self.assertEqual(8, schema["size"])
        self.assertEqual("little", schema["byte_order"])
        self.assertEqual(
            [
                {"name": "duration_samples", "offset": 0, "type": "u32"},
                {"name": "logical_state_mask", "offset": 4, "type": "u32"},
            ],
            schema["fields"],
        )
        self.assertEqual(1, program["duration_min"])
        self.assertEqual(0xFFFFFFFF, program["duration_max"])
        self.assertEqual(0xFF, program["legal_state_mask"])
        self.assertEqual(1024, program["capacity_segments"])
        self.assertEqual(1, program["minimum_committed_segments"])
        for rejection in ("Adjacent equal", "overflow", "zero duration", "bit above"):
            with self.subTest(rejection=rejection):
                self.assertIn(rejection, program["canonicalization"])

        records = struct.pack("<II", 10, 0x01) + struct.pack("<II", 5, 0xA5)
        self.assertEqual(
            zlib.adler32(records) & 0xFFFFFFFF,
            zlib.adler32(bytes.fromhex("0a0000000100000005000000a5000000"))
            & 0xFFFFFFFF,
        )
        self.assertEqual("ADLER32", program["checksum"]["algorithm"])
        self.assertTrue(program["checksum"]["end_to_end"])

    def test_repeat_and_tick_zero_semantics_are_unambiguous(self) -> None:
        program = self.output["program"]
        timing = self.output["timing"]
        self.assertEqual("u32", program["repeat_count_type"])
        self.assertEqual(0, program["repeat_forever_value"])
        self.assertIn("exactly N times", program["positive_repeat_semantics"])
        self.assertEqual(0, timing["first_event_tick"])
        self.assertIn("idle state", timing["first_event_semantics"])
        self.assertIn("first segment state", timing["first_event_semantics"])

    def test_uploads_are_idle_only_bounded_and_generation_correlated(self) -> None:
        upload = self.output["upload"]
        self.assertEqual("IDLE", upload["mutation_controller_state"])
        self.assertEqual(
            ["IDLE", "CONFIGURED", "RUNNING"],
            upload["status_allowed_controller_states"],
        )
        self.assertEqual("header.run_id", upload["generation_location"])
        self.assertEqual("u32", upload["generation_type"])
        self.assertFalse(upload["generation_zero_valid"])
        self.assertEqual(8, upload["max_command_payload_bytes"])
        self.assertIn("request_id", upload["generation_semantics"])

        expected_sizes = {
            "OUTPUT_BEGIN": 8,
            "OUTPUT_APPEND": 8,
            "OUTPUT_COMMIT": 8,
            "OUTPUT_ARM": 0,
            "OUTPUT_STATUS": 0,
            "OUTPUT_CLEAR": 0,
        }
        self.assertEqual(
            expected_sizes,
            {
                name: operation["payload_size"]
                for name, operation in upload["operations"].items()
            },
        )
        self.assertTrue(all(size <= 8 for size in expected_sizes.values()))
        self.assertIn(
            "physically emit the declared idle state",
            upload["operations"]["OUTPUT_ARM"]["semantics"],
        )

    def test_completion_stop_fault_and_clear_have_distinct_terminal_rules(self) -> None:
        lifecycle = self.output["lifecycle"]
        states = {
            name: int(entry["value"])
            for name, entry in _by_name(self.v2["enums"]["output_state"]).items()
        }
        self.assertEqual(
            {
                "EMPTY": 0,
                "LOADING": 1,
                "COMMITTED": 2,
                "ARMED": 3,
                "RUNNING": 4,
                "HELD": 5,
                "FAULTED": 6,
            },
            states,
        )
        self.assertIn("last physically emitted state", lifecycle["finite_completion"])
        self.assertIn("last physically emitted state", lifecycle["stop"])
        self.assertIn("stops the entire common run", lifecycle["fault"])
        self.assertIn("latches evidence", lifecycle["fault"])
        self.assertIn("OUTPUT_CLEAR", lifecycle["release"])
        self.assertIn("high-impedance inputs", lifecycle["release"])
        self.assertIn("never promises", lifecycle["reset"])

    def test_adr_and_docgraph_links_track_normative_contract(self) -> None:
        adr = ADR_PATH.read_text(encoding="utf-8")
        self.assertTrue(adr.startswith("---\ntype: analysis\n"))
        for target in (
            "[[1-MHz-Parallel-Output-Idea]]",
            "[[Firmware-Resource-Map]]",
            "[[Acquisition-Pipeline]]",
            "[[Protocol-V1]]",
            "[[Hardware-Safety]]",
        ):
            with self.subTest(target=target):
                self.assertIn(target, adr)

        for value in (
            "protocol/protocol-v2.json",
            "`0x0FC30000`",
            "1,024 canonical segments",
            "repeat_count",
            "tick zero",
            "OUTPUT_CLEAR",
            "last physically emitted state",
        ):
            with self.subTest(value=value):
                self.assertIn(value, adr)

        doc_index = DOC_INDEX_PATH.read_text(encoding="utf-8")
        self.assertIn("[[ADR-008-Experimental-Aux-Output-Bank]]", doc_index)


if __name__ == "__main__":
    unittest.main()
