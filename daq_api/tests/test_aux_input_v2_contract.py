"""Contract checks for the isolated auxiliary-input protocol-v2 extension."""

from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path
from typing import Any, ClassVar

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
V2_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
V1_FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
V1_MANIFEST_PATH = V1_FIXTURE_DIRECTORY / "manifest.json"
ADR_PATH = REPOSITORY_ROOT / "doc/decisions/adr-007-experimental-aux-input-bank.md"
DOC_INDEX_PATH = REPOSITORY_ROOT / "doc/README.md"
BASELINE_ALIAS_PATH = REPOSITORY_ROOT / "doc/results/experiments/Experiment-Baseline.md"

_FROZEN_V1_SHA256 = {
    "protocol/protocol-v1.json": (
        "014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222"
    ),
    "protocol/fixtures/manifest.json": (
        "e354b6dd7749b4dcea9ee233297f5712f645c2d0a1444d990e22f02303c99568"
    ),
    "daq_api/src/thingdone_daq/_generated/protocol_constants.py": (
        "a5dc4cd73dd12e291c03d536c2937d14ad1d0ca84b9c8a2860ad2797fbf15961"
    ),
    "firmware/src/generated/protocol_constants.h": (
        "9604390433f7d8227432d341ecc65b9292002797da9457937ed4d5d3cc096290"
    ),
}

_INTEGER_WIDTHS = {"u8": 1, "u16": 2, "u32": 4, "u64": 8}


def _by_name(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(entry["name"]): entry for entry in entries}


def _field(
    contract: dict[str, Any], schema_name: str, field_name: str
) -> dict[str, Any]:
    fields = contract["payload_schemas"][schema_name]["fields"]
    return _by_name(fields)[field_name]


def _fixture(contract: dict[str, Any], name: str) -> dict[str, Any]:
    return _by_name(contract["golden_fixtures"])[name]


def _field_width(contract: dict[str, Any], field: dict[str, Any]) -> int:
    field_type = str(field["type"])
    if field_type in _INTEGER_WIDTHS:
        return _INTEGER_WIDTHS[field_type]
    if field_type in {"bytes", "nul_ascii", "u8_array"}:
        return int(field["count"])
    if field_type == "repeated_u16":
        return int(field["count"]) * 2
    if field_type == "repeated_u16_pair":
        return int(field["count"]) * 4
    if field_type == "repeated_schema":
        schema = contract["payload_schemas"][str(field["schema"])]
        return int(field["count"]) * int(schema["size"])
    raise AssertionError(f"unhandled field type {field_type}")


class AuxInputV2ContractTests(unittest.TestCase):
    v1: ClassVar[dict[str, Any]]
    v2: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = json.loads(V1_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.v2 = json.loads(V2_CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_v2_pins_v1_and_uses_disjoint_generated_outputs(self) -> None:
        self.assertEqual(1, self.v1["protocol_version"])
        self.assertEqual(2, self.v2["protocol_version"])
        self.assertEqual("release-1.1.0", self.v2["status"])
        self.assertEqual("aux-input-bank-fixed-1mhz-temperature", self.v2["extension"])
        self.assertEqual(
            _FROZEN_V1_SHA256["protocol/protocol-v1.json"],
            self.v2["extends"]["source_sha256"],
        )
        self.assertEqual("protocol/protocol-v1.json", self.v2["extends"]["source"])

        v1_outputs = {
            "daq_api/src/thingdone_daq/_generated/protocol_constants.py",
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

    def test_aux_bank_is_whole_input_or_disabled_and_never_output(self) -> None:
        modes = {
            name: int(entry["value"])
            for name, entry in _by_name(self.v2["enums"]["aux_bank_mode"]).items()
        }
        self.assertEqual({"DISABLED": 0, "INPUT": 1}, modes)

        auxiliary = self.v2["auxiliary_input"]
        self.assertEqual(["DISABLED", "INPUT"], auxiliary["supported_modes"])
        self.assertEqual("whole_bank", auxiliary["direction_granularity"])
        self.assertFalse(auxiliary["output_supported"])
        self.assertNotIn("per_pin", _by_name(self.v2["enums"]["aux_bank_mode"]))
        self.assertEqual(
            {"MIXED": 2, "OUTPUT": 3},
            {
                str(entry["name"]): int(entry["value"])
                for entry in auxiliary["rejected_mode_examples"]
            },
        )

        capabilities = _by_name(self.v2["enums"]["capability_bits"])
        self.assertEqual(0x200, capabilities["AUXILIARY_INPUT_BANK"]["value"])
        self.assertEqual(0x400, capabilities["EXACT_RATE_PROFILES"]["value"])

    def test_little_endian_layout_preserves_primary_bit_positions(self) -> None:
        wire = self.v2["auxiliary_input"]["wire_layout"]
        self.assertEqual("little", wire["byte_order"])
        self.assertEqual(list(range(6, 14)), wire["primary_bits"]["pins"])
        self.assertEqual(list(range(16, 24)), wire["auxiliary_bits"]["pins"])
        self.assertEqual(
            (0, 7), (wire["primary_bits"]["first"], wire["primary_bits"]["last"])
        )
        self.assertEqual(
            (8, 15), (wire["auxiliary_bits"]["first"], wire["auxiliary_bits"]["last"])
        )
        self.assertTrue(wire["preserve_primary_positions"])
        self.assertEqual(0xFFFF, wire["maximum_value"])

        primary = 0xA5
        auxiliary = 0x3C
        joined = primary | (auxiliary << 8)
        self.assertEqual(b"\xa5\x3c", struct.pack("<H", joined))

        layouts = self.v2["data_layouts"]
        self.assertEqual(list(range(6, 14)), layouts["gpio"]["pins_by_bit"])
        self.assertEqual(
            [*range(6, 14), *range(16, 24)],
            layouts["gpio_aux_input"]["pins_by_bit"],
        )
        self.assertEqual(2, layouts["gpio_aux_input"]["bytes_per_item"])
        self.assertEqual("little", layouts["gpio_aux_input"]["byte_order"])

    def test_pin_maps_masks_and_provisional_resources_are_exact(self) -> None:
        banks = self.v2["auxiliary_input"]["pin_banks"]
        self.assertEqual(
            [10, 17, 16, 11, 0, 2, 1, 3],
            banks["primary"]["standard_gpio_bits_by_wire_bit"],
        )
        self.assertEqual(0x00030C0F, banks["primary"]["aggregate_mask"])
        self.assertEqual(
            [23, 22, 17, 16, 26, 27, 24, 25],
            banks["auxiliary"]["standard_gpio_bits_by_wire_bit"],
        )
        self.assertEqual(0x0FC30000, banks["auxiliary"]["aggregate_mask"])
        self.assertEqual(
            (1, 6, 26),
            tuple(
                banks["auxiliary"][key]
                for key in ("standard_gpio", "fast_gpio", "fast_select_gpr")
            ),
        )

        resources = self.v2["auxiliary_input"]["provisional_resources"]
        self.assertEqual(
            (0, 56), (resources["clock_pit_channel"], resources["xbar_input"])
        )
        self.assertEqual(
            (0, 1),
            (resources["primary_xbar_output"], resources["auxiliary_xbar_output"]),
        )
        self.assertEqual(
            (30, 31),
            (resources["primary_dmamux_source"], resources["auxiliary_dmamux_source"]),
        )
        self.assertEqual(
            (2, 3),
            (resources["primary_edma_channel"], resources["auxiliary_edma_channel"]),
        )
        self.assertEqual([3, 2, 1, 0], resources["enabled_mode_edma_priorities"])
        self.assertEqual(
            ["ADC0", "ADC1", "PRIMARY_GPIO", "AUXILIARY_GPIO"],
            resources["enabled_mode_edma_priority_order"],
        )
        self.assertTrue(resources["paired_join_required"])

    def test_exact_rate_profiles_have_integral_generated_timing(self) -> None:
        timing = self.v2["timing"]
        timestamp_hz = int(timing["timestamp_hz"])
        pit_hz = int(timing["pit_clock_hz"])
        ipg_hz = int(timing["ipg_clock_hz"])
        dwt_hz = int(timing["dwt_clock_hz"])
        profiles = self.v2["rate_profiles"]
        self.assertEqual(5, len(profiles))
        self.assertEqual(0x1F, timing["supported_rate_profile_mask"])

        enum_profiles = {
            name: int(entry["value"])
            for name, entry in _by_name(self.v2["enums"]["rate_profile"]).items()
        }
        self.assertEqual(
            {str(profile["name"]): int(profile["value"]) for profile in profiles},
            enum_profiles,
        )

        expected_pairs = [
            (1_000_000, 4_000_000),
            (500_000, 2_000_000),
            (250_000, 1_000_000),
            (125_000, 500_000),
            (1_000_000, 1_000_000),
        ]
        self.assertEqual(
            expected_pairs,
            [
                (int(profile["adc_pair_rate_hz"]), int(profile["gpio_sample_rate_hz"]))
                for profile in profiles
            ],
        )

        for profile in profiles:
            with self.subTest(profile=profile["name"]):
                adc_rate = int(profile["adc_pair_rate_hz"])
                gpio_rate = int(profile["gpio_sample_rate_hz"])
                ratio = 1 if profile["value"] == 4 else 4
                self.assertEqual(ratio, profile["gpio_to_adc_ratio"])
                self.assertEqual(adc_rate * ratio, gpio_rate)
                self.assertEqual(0, timestamp_hz % adc_rate)
                self.assertEqual(0, timestamp_hz % gpio_rate)
                self.assertEqual(
                    timestamp_hz // adc_rate, profile["adc_pair_period_ticks"]
                )
                self.assertEqual(
                    timestamp_hz // gpio_rate, profile["gpio_sample_period_ticks"]
                )
                self.assertEqual(
                    profile["adc_pair_period_ticks"] // 2, profile["adc1_phase_ticks"]
                )
                self.assertEqual(0, pit_hz % gpio_rate)
                self.assertEqual(
                    pit_hz // gpio_rate, profile["gpio_master_pit_divider"]
                )
                self.assertEqual(
                    profile["gpio_master_pit_divider"] - 1,
                    profile["gpio_master_pit_load"],
                )
                self.assertEqual(ratio, profile["adc_pair_pit_divider"])
                self.assertEqual(ratio - 1, profile["adc_pair_pit_load"])
                self.assertEqual(0, profile["adc_etc_predivider"])
                self.assertEqual(1, profile["adc_etc_chain_length"])
                self.assertEqual(
                    ipg_hz // (2 * adc_rate), profile["adc1_phase_ipg_cycles"]
                )
                self.assertEqual(0, profile["adc0_initial_delay"])
                self.assertEqual(
                    profile["adc1_phase_ipg_cycles"], profile["adc1_initial_delay"]
                )
                self.assertEqual(1, profile["adc0_effective_delay"])
                self.assertEqual(
                    profile["adc1_initial_delay"] + 1, profile["adc1_effective_delay"]
                )
                self.assertEqual(
                    dwt_hz // (2 * adc_rate), profile["completion_expected_dwt_cycles"]
                )

    def test_mode_specific_frames_have_equal_stream_coverage(self) -> None:
        layouts = self.v2["auxiliary_input"]["layouts"]
        self.assertEqual(
            {
                "gpio_width_bits": 8,
                "gpio_bytes_per_item": 1,
                "gpio_items_per_frame": 4048,
                "gpio_payload_bytes": 4048,
                "gpio_total_frame_bytes": 4096,
                "adc_bytes_per_item": 4,
                "adc_items_per_frame": 1012,
                "adc_payload_bytes": 4048,
                "adc_total_frame_bytes": 4096,
            },
            layouts["DISABLED"],
        )
        self.assertEqual(506, layouts["INPUT"]["adc_items_per_frame"])
        self.assertEqual(2024, layouts["INPUT"]["gpio_items_per_frame"])
        self.assertEqual(2, layouts["INPUT"]["gpio_bytes_per_item"])
        self.assertEqual(2024, layouts["INPUT"]["adc_payload_bytes"])
        self.assertEqual(2072, layouts["INPUT"]["adc_total_frame_bytes"])

        for profile in self.v2["rate_profiles"]:
            for mode, layout in layouts.items():
                with self.subTest(profile=profile["name"], mode=mode):
                    adc_coverage = int(layout["adc_items_per_frame"]) * int(
                        profile["adc_pair_period_ticks"]
                    )
                    gpio_coverage = int(layout["gpio_items_per_frame"]) * int(
                        profile["gpio_sample_period_ticks"]
                    )
                    self.assertEqual(
                        adc_coverage * (4 if profile["value"] == 4 else 1),
                        gpio_coverage,
                    )
                    self.assertEqual(
                        adc_coverage, profile["frame_coverage_ticks"][mode]
                    )

    def test_extended_configure_and_info_schemas_are_complete(self) -> None:
        request = self.v2["payload_schemas"]["configure_request"]
        response = self.v2["payload_schemas"]["configure_response"]
        self.assertEqual(16, request["size"])
        self.assertEqual(20, response["size"])
        self.assertEqual(64, self.v2["limits"]["max_command_frame_bytes"])
        self.assertEqual(16, self.v2["limits"]["max_command_payload_bytes"])
        self.assertEqual(
            3, _field(self.v2, "configure_request", "aux_bank_mode")["offset"]
        )
        self.assertEqual(
            8, _field(self.v2, "configure_request", "adc_pair_rate_hz")["offset"]
        )
        self.assertEqual(
            12, _field(self.v2, "configure_request", "gpio_sample_rate_hz")["offset"]
        )
        self.assertEqual(
            7, _field(self.v2, "configure_response", "aux_bank_mode")["offset"]
        )
        self.assertEqual(
            12, _field(self.v2, "configure_response", "adc_pair_rate_hz")["offset"]
        )
        self.assertEqual(
            16, _field(self.v2, "configure_response", "gpio_sample_rate_hz")["offset"]
        )

        info = self.v2["payload_schemas"]["info_response"]
        self.assertEqual(680, info["size"])
        table = _field(self.v2, "info_response", "rate_profiles")
        self.assertEqual(
            {
                "offset": 440,
                "type": "repeated_schema",
                "schema": "rate_profile_info",
                "count": 5,
            },
            {key: table[key] for key in ("offset", "type", "schema", "count")},
        )
        self.assertEqual(48, self.v2["payload_schemas"]["rate_profile_info"]["size"])

        for schema_name, schema in self.v2["payload_schemas"].items():
            occupancy = [False] * int(schema["size"])
            for field in schema["fields"]:
                width = _field_width(self.v2, field)
                start = int(field["offset"])
                self.assertLessEqual(start + width, len(occupancy), schema_name)
                for index in range(start, start + width):
                    self.assertFalse(occupancy[index], f"{schema_name} byte {index}")
                    occupancy[index] = True
            self.assertTrue(all(occupancy), schema_name)

    def test_seed_metadata_matches_generated_profile_contract(self) -> None:
        request_values = _fixture(self.v2, "configure-request")["payload"]["values"]
        response_values = _fixture(self.v2, "configure-response")["payload"]["values"]
        start_values = _fixture(self.v2, "start-response")["payload"]["values"]
        expected = {
            "aux_bank_mode": 0,
            "adc_pair_rate_hz": 1_000_000,
            "gpio_sample_rate_hz": 4_000_000,
        }
        for values in (request_values, response_values, start_values):
            with self.subTest(values=values):
                self.assertEqual(expected, {key: values[key] for key in expected})

        info = _fixture(self.v2, "info-response")["payload"]["values"]
        self.assertEqual(2, info["protocol_version"])
        self.assertEqual(0x7FF, info["capability_bits"])
        self.assertEqual(0x1F, info["supported_rate_profile_mask"])
        self.assertEqual(0x03, info["supported_aux_bank_mode_mask"])
        self.assertEqual(5, info["rate_profile_count"])
        self.assertEqual(8, info["gpio_pin_count"])
        self.assertEqual(1, info["gpio_item_bytes"])
        self.assertEqual(8, info["gpio_packed_width_bits"])

        for source, encoded in zip(
            self.v2["rate_profiles"], info["rate_profiles"], strict=True
        ):
            with self.subTest(profile=source["name"]):
                self.assertEqual(source["value"], encoded["rate_profile"])
                for field in (
                    "adc_pair_rate_hz",
                    "gpio_sample_rate_hz",
                    "adc_pair_period_ticks",
                    "adc1_phase_ticks",
                    "gpio_sample_period_ticks",
                    "gpio_master_pit_divider",
                    "gpio_master_pit_load",
                    "adc_pair_pit_divider",
                    "adc_pair_pit_load",
                    "adc_etc_predivider",
                    "adc_etc_chain_length",
                    "adc0_initial_delay",
                    "adc1_initial_delay",
                    "adc0_effective_delay",
                    "adc1_effective_delay",
                    "adc1_phase_ipg_cycles",
                    "completion_expected_dwt_cycles",
                ):
                    self.assertEqual(source[field], encoded[field])
                self.assertEqual(
                    source["frame_coverage_ticks"]["DISABLED"],
                    encoded["disabled_frame_coverage_ticks"],
                )
                self.assertEqual(
                    source["frame_coverage_ticks"]["INPUT"],
                    encoded["input_frame_coverage_ticks"],
                )

    def test_adr_and_docgraph_links_track_normative_contract(self) -> None:
        adr = ADR_PATH.read_text(encoding="utf-8")
        self.assertTrue(adr.startswith("---\ntype: analysis\n"))
        for target in (
            "[[ADR-003-GPIO-Clock-DMA]]",
            "[[Acquisition-Pipeline]]",
            "[[Firmware-Resource-Map]]",
            "[[Hardware-Safety]]",
            "[[Experiment-Baseline]]",
        ):
            with self.subTest(target=target):
                self.assertIn(target, adr)

        for value in (
            "protocol/protocol-v2.json",
            "`0x0FC30000`",
            "506 pairs",
            "2,024 samples",
            "12 MB/s",
            "OUTPUT is unsupported",
        ):
            with self.subTest(value=value):
                self.assertIn(value, adr)

        doc_index = DOC_INDEX_PATH.read_text(encoding="utf-8")
        self.assertIn("[[ADR-007-Experimental-Aux-Input-Bank]]", doc_index)
        self.assertIn("[[Experiment-Baseline]]", doc_index)
        baseline_alias = BASELINE_ALIAS_PATH.read_text(encoding="utf-8")
        self.assertTrue(baseline_alias.startswith("---\ntype: reference\n"))
        self.assertIn("[[baseline]]", baseline_alias)


if __name__ == "__main__":
    unittest.main()
