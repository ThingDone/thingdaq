"""Contract checks for the isolated experimental protocol-v2 RLE extension."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any, ClassVar

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
V2_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
V1_FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
V1_MANIFEST_PATH = V1_FIXTURE_DIRECTORY / "manifest.json"
ADR_PATH = REPOSITORY_ROOT / "doc/decisions/adr-006-experimental-rle-streaming.md"

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


def _field(
    contract: dict[str, Any], schema_name: str, field_name: str
) -> dict[str, Any]:
    fields = contract["payload_schemas"][schema_name]["fields"]
    return _by_name(fields)[field_name]


class ProtocolV2ContractTests(unittest.TestCase):
    v1: ClassVar[dict[str, Any]]
    v2: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = json.loads(V1_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.v2 = json.loads(V2_CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_v2_pins_v1_and_uses_disjoint_generated_outputs(self) -> None:
        self.assertEqual(1, self.v1["protocol_version"])
        self.assertEqual(2, self.v2["protocol_version"])
        self.assertEqual("experimental", self.v2["status"])
        self.assertEqual("rle-streaming", self.v2["extension"])
        self.assertEqual(
            _FROZEN_V1_SHA256["protocol/protocol-v1.json"],
            self.v2["extends"]["source_sha256"],
        )
        self.assertEqual(
            "protocol/protocol-v1.json",
            self.v2["extends"]["source"],
        )

        v1_outputs = {
            "daq_api/src/thingdaq/_generated/protocol_constants.py",
            "firmware/src/generated/protocol_constants.h",
            "protocol/fixtures",
            "protocol/fixtures/manifest.json",
        }
        v2_outputs = set(self.v2["generated_outputs"].values())
        self.assertTrue(v1_outputs.isdisjoint(v2_outputs))
        self.assertEqual(len(v2_outputs), len(self.v2["generated_outputs"]))

    def test_frozen_v1_sources_and_fixture_bytes_are_unchanged(self) -> None:
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

    def test_header_and_configure_reuse_only_former_reserved_bytes(self) -> None:
        v1_header_field = self.v1["header"]["fields"][6]
        v2_header_field = self.v2["header"]["fields"][6]
        self.assertEqual(
            {"name": "reserved", "offset": 11, "type": "u8", "required": 0},
            v1_header_field,
        )
        self.assertEqual(
            {
                "name": "encoding",
                "offset": 11,
                "type": "u8",
                "enum": "frame_encoding",
                "control_required": 0,
            },
            v2_header_field,
        )
        self.assertEqual(0, self.v2["compression"]["control_header_encoding"])

        request_encoding = _field(self.v2, "configure_request", "encoding")
        response_encoding = _field(self.v2, "configure_response", "encoding")
        self.assertEqual(3, request_encoding["offset"])
        self.assertEqual(7, response_encoding["offset"])
        self.assertEqual("configuration_encoding", request_encoding["enum"])
        self.assertEqual("configuration_encoding", response_encoding["enum"])
        self.assertEqual(8, self.v2["payload_schemas"]["configure_request"]["size"])
        self.assertEqual(12, self.v2["payload_schemas"]["configure_response"]["size"])

        self.assertEqual(
            {"RAW": 0, "RLE_AUTO": 1},
            {
                name: int(entry["value"])
                for name, entry in _by_name(
                    self.v2["enums"]["configuration_encoding"]
                ).items()
            },
        )
        self.assertEqual(
            {"RAW": 0, "RLE": 1},
            {
                name: int(entry["value"])
                for name, entry in _by_name(self.v2["enums"]["frame_encoding"]).items()
            },
        )

    def test_rle_requires_explicit_capability_negotiation(self) -> None:
        v1_capabilities = self.v1["enums"]["capability_bits"]
        v2_capabilities = self.v2["enums"]["capability_bits"]
        self.assertEqual(v1_capabilities, v2_capabilities[:-1])
        self.assertEqual(
            {"name": "RLE_STREAMING", "value": 0x200},
            v2_capabilities[-1],
        )

        compression = self.v2["compression"]
        self.assertEqual("RLE_STREAMING", compression["capability"])
        self.assertEqual("RAW", compression["default_configuration_encoding"])
        self.assertEqual("RLE_AUTO", compression["explicit_configuration_encoding"])
        self.assertEqual(["RAW"], compression["configured_frame_encodings"]["RAW"])
        self.assertEqual(
            ["RAW", "RLE"],
            compression["configured_frame_encodings"]["RLE_AUTO"],
        )
        self.assertIn("protocol v1", self.v2["compatibility"]["default_client"])
        self.assertIn("RLE_STREAMING", self.v2["compatibility"]["version_selection"])

    def test_rle_records_are_little_endian_frame_local_and_canonical(self) -> None:
        run_length = self.v2["compression"]["run_length"]
        self.assertEqual(
            {
                "type": "u16",
                "byte_order": "little",
                "minimum": 1,
                "maximum": 0xFFFF,
            },
            run_length,
        )
        self.assertEqual(2, self.v2["scalar_types"]["u16"]["width"])

        adc_record = self.v2["payload_schemas"]["adc_rle_record"]
        gpio_record = self.v2["payload_schemas"]["gpio_rle_record"]
        self.assertEqual(6, adc_record["size"])
        self.assertEqual(3, gpio_record["size"])
        self.assertEqual(
            {"name": "run_length", "offset": 0, "type": "u16", "minimum": 1},
            adc_record["fields"][0],
        )
        self.assertEqual(adc_record["fields"][0], gpio_record["fields"][0])
        self.assertEqual(
            {
                "name": "item",
                "offset": 2,
                "type": "repeated_u16_pair",
                "count": 1,
                "order": ["adc0", "adc1"],
            },
            adc_record["fields"][1],
        )
        self.assertEqual(
            {"name": "item", "offset": 2, "type": "bytes", "count": 1},
            gpio_record["fields"][1],
        )

        canonical = self.v2["compression"]["canonicalization"]
        self.assertEqual("forbidden", canonical["adjacent_equal_records"])
        self.assertTrue(canonical["coalesce_adjacent_equal_items"])
        self.assertTrue(canonical["records_are_frame_local"])
        self.assertFalse(canonical["record_split_across_frames"])
        self.assertEqual(
            "sum(run_length) == header.item_count",
            canonical["decoded_count_rule"],
        )

    def test_adaptive_selection_retains_exact_logical_bounds(self) -> None:
        envelope_bytes = int(self.v2["header"]["size"]) + int(
            self.v2["trailer"]["size"]
        )
        selection = self.v2["compression"]["adaptive_selection"]
        self.assertEqual(48, envelope_bytes)
        self.assertEqual(envelope_bytes, selection["envelope_bytes"])
        self.assertEqual("complete_wire_length", selection["comparison"])
        self.assertEqual("RAW", selection["tie_encoding"])
        self.assertEqual("RAW", selection["fallback_encoding"])
        self.assertFalse(selection["expansion_allowed"])

        expected_streams = {
            "ADC_DATA": ("adc", 8),
            "GPIO_DATA": ("gpio", 2),
        }
        for kind, (layout_name, period_ticks) in expected_streams.items():
            with self.subTest(kind=kind):
                stream = self.v2["compression"]["streams"][kind]
                layout = self.v2["data_layouts"][layout_name]
                item_count = int(stream["logical_items_per_frame"])
                item_bytes = int(stream["logical_item_bytes"])
                raw_payload_bytes = item_count * item_bytes
                record_bytes = 2 + item_bytes
                maximum_selected_runs = (raw_payload_bytes - 1) // record_bytes

                self.assertEqual(int(layout["items_per_frame"]), item_count)
                self.assertEqual(int(layout["bytes_per_item"]), item_bytes)
                self.assertEqual(int(layout["payload_bytes"]), raw_payload_bytes)
                self.assertEqual(
                    item_count * period_ticks, stream["frame_coverage_ticks"]
                )
                self.assertEqual(record_bytes, stream["rle_record_bytes"])
                self.assertEqual(record_bytes, stream["minimum_rle_payload_bytes"])
                self.assertEqual(
                    maximum_selected_runs, stream["maximum_selected_run_count"]
                )
                self.assertEqual(
                    maximum_selected_runs * record_bytes,
                    stream["maximum_selected_payload_bytes"],
                )
                self.assertEqual(
                    envelope_bytes + raw_payload_bytes, stream["raw_total_bytes"]
                )
                self.assertEqual(4096, stream["raw_total_bytes"])
                self.assertEqual(
                    envelope_bytes + stream["maximum_selected_payload_bytes"],
                    stream["maximum_selected_total_bytes"],
                )
                self.assertLess(
                    stream["maximum_selected_total_bytes"],
                    stream["raw_total_bytes"],
                )
                self.assertLessEqual(
                    stream["maximum_selected_total_bytes"],
                    self.v2["limits"]["max_data_frame_bytes"],
                )

        minimum_record_bytes = min(
            stream["minimum_rle_payload_bytes"]
            for stream in self.v2["compression"]["streams"].values()
        )
        self.assertEqual(
            envelope_bytes + minimum_record_bytes,
            self.v2["limits"]["min_rle_data_frame_bytes"],
        )

    def test_checksum_precedes_decode_and_headers_describe_logical_items(self) -> None:
        checksum = self.v2["compression"]["checksum"]
        self.assertFalse(checksum["decode_before_checksum"])
        self.assertEqual(
            [
                "validate bounded header and transmitted lengths",
                "validate checksum over transmitted header and encoded payload",
                "decode and validate RLE records",
            ],
            checksum["validation_order"],
        )
        self.assertIn("encoded payload", checksum["coverage"])
        self.assertTrue(
            all(self.v2["compression"]["logical_header_semantics"].values())
        )

    def test_seed_vectors_are_v2_raw_and_echo_the_encoding(self) -> None:
        fixtures = _by_name(self.v2["golden_fixtures"])
        self.assertEqual("RAW", fixtures["adc-data"]["encoding"])
        self.assertEqual("RAW", fixtures["gpio-data"]["encoding"])
        self.assertEqual(
            0,
            fixtures["configure-request"]["payload"]["values"]["encoding"],
        )
        self.assertEqual(
            0,
            fixtures["configure-response"]["payload"]["values"]["encoding"],
        )
        self.assertEqual(
            0,
            fixtures["start-response"]["payload"]["values"]["encoding"],
        )
        info = fixtures["info-response"]["payload"]["values"]
        self.assertEqual(2, info["protocol_version"])
        self.assertEqual(0x3FF, info["capability_bits"])
        self.assertEqual("synthetic-golden-v2", info["build_id"])

    def test_adr_links_and_normative_values_match_the_source(self) -> None:
        adr = ADR_PATH.read_text(encoding="utf-8")
        self.assertTrue(adr.startswith("---\ntype: analysis\n"))
        for target in (
            "[[ADR-001-Wire-Protocol]]",
            "[[Protocol-V1]]",
            "[[Acquisition-Pipeline]]",
            "[[Experiment-Baseline]]",
        ):
            with self.subTest(target=target):
                self.assertIn(target, adr)

        for value in (
            "`RLE_STREAMING` capability bit (`0x00000200`)",
            "`RAW` is `0`; `RLE_AUTO` is `1`",
            "Header byte 11",
            "protocol/protocol-v2.json",
        ):
            with self.subTest(value=value):
                self.assertIn(value, adr)


if __name__ == "__main__":
    unittest.main()
