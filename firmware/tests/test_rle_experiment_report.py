"""Regression checks for the generated negotiated-RLE experiment report."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from firmware.tools import experiment_evidence as evidence

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "experiments/experiment-matrix.json"
REPORT_JSON = ROOT / "doc/results/experiments/rle-streaming.json"
REPORT_MARKDOWN = ROOT / "doc/results/experiments/rle-streaming.md"
REPORT_OUTPUTS = (
    "doc/results/experiments/rle-streaming.json",
    "doc/results/experiments/rle-streaming.md",
)


class RLEExperimentReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = evidence.load_experiment_matrix(MATRIX_PATH)
        self.report = evidence.load_json_object(REPORT_JSON)

    def test_report_is_canonical_and_preserves_separate_campaign_grades(self) -> None:
        normalized = evidence.prepare_report(
            self.matrix,
            self.report,
            tracked_report=True,
            output_paths=REPORT_OUTPUTS,
        )
        self.assertEqual("INCONCLUSIVE", normalized["result"])
        self.assertEqual(
            REPORT_MARKDOWN.read_text(encoding="utf-8"),
            evidence.render_markdown(
                self.matrix,
                normalized,
                tracked_report=True,
                output_paths=REPORT_OUTPUTS,
            ),
        )
        self.assertTrue(
            {
                "[[RLE-Prototype]]",
                "[[ADR-006-Experimental-RLE-Streaming]]",
                "[[Protocol-V1]]",
                "[[Acquisition-Pipeline]]",
            }.issubset(normalized["related"])
        )

        records = {str(record["id"]): record for record in normalized["evidence"]}
        self.assertEqual("PASS", records["local-firmware-gate"]["result"])
        self.assertEqual("PASS", records["simulated-rig-gate"]["result"])
        self.assertEqual("PASS", records["protocol-v1-compatibility"]["result"])
        self.assertEqual("PASS", records["physical-accepted-campaign"]["result"])
        self.assertEqual(
            "INCONCLUSIVE", records["physical-endurance-campaign"]["result"]
        )
        self.assertEqual("INCONCLUSIVE", records["physical-campaign"]["result"])
        self.assertTrue(
            records["physical-accepted-campaign"]["scope_limitations"][
                "physical_data_collected"
            ]
        )
        self.assertTrue(
            any(metric["evidence_level"] == "rig" for metric in normalized["metrics"])
        )
        self.assertEqual(
            "FAIL",
            records["physical-campaign"]["decisions"]["physical_bandwidth_benefit"][
                "result"
            ],
        )
        self.assertEqual(
            "INCONCLUSIVE",
            records["physical-campaign"]["decisions"]["rig_correctness"]["result"],
        )

    def test_report_pins_candidate_protocol_build_and_campaign_identities(
        self,
    ) -> None:
        identity = self.report["identity"]
        self.assertEqual(
            "b23004defeca465da0ae2d2884c4fef71979e5d4",
            identity["baseline_commit"],
        )
        self.assertEqual(
            "dca4343616a78ab71dedf08155359aeddd017859",
            identity["source_commit"],
        )
        self.assertEqual(
            "db824f42af030d7ed226900d3b68379962f7515f66734e51e4309773b04f5c4d",
            identity["source_id"],
        )
        self.assertEqual(
            "014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222",
            identity["protocol_sha256"],
        )

        physical = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "physical-accepted-campaign"
        )
        self.assertEqual(
            "2b9990ee46b3f9eff999d285c7e3fefb13947e79fda5d977b336ad75dab19aa3",
            physical["protocols"]["v2_sha256"],
        )
        self.assertEqual("thingdaq-db824f42af030d7e", physical["firmware_build_id"])
        self.assertEqual(
            "b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248",
            physical["firmware_artifact_sha256"],
        )
        self.assertEqual(
            "681c74f20f35012af01b438561de7c4d25ec0b91a3fb247d0e0255e35b960f21",
            physical["campaign_index_sha256"],
        )
        self.assertEqual(
            "rle-streaming-physical-campaign-00003",
            physical["campaign_id"],
        )
        self.assertEqual(20428100, physical["hardware_serial"])
        self.assertFalse(
            physical["scope_limitations"]["hardware_serial_used_as_acceptance_rule"]
        )
        self.assertEqual(
            [
                "74a69541-ed2c-4ffb-9f01-c64c941b9dd3",
                "b780d490-fa3a-4248-998c-0b06fa61d91c",
                "9ddbeb1d-41e6-4522-ad5b-9989632855fd",
                "9832bb0a-fe99-4802-92c6-9501f737112a",
                "25dcc047-cc6b-438a-81c2-15ccd6838ad0",
                "a80b863d-8b11-4b2f-9a85-8d53c3345f61",
                "d165c5d0-d6bc-4588-8f39-702896c5dae9",
                "b9cf56b7-9351-4566-9572-61075e0a0fee",
                "1242edca-de9e-49d8-9093-15232c79686e",
                "9686bce1-f4aa-4974-9a34-2e6c01c62f85",
            ],
            [run["job_id"] for run in physical["accepted_runs"]],
        )

        campaign = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "physical-campaign"
        )
        self.assertEqual(
            [
                "rle-streaming-physical-campaign-00001",
                "rle-streaming-physical-campaign-00002",
            ],
            [row["campaign_id"] for row in campaign["preserved_history"]],
        )
        self.assertTrue(
            all(
                row["disposition"] == "immutable_superseded_provenance_only"
                for row in campaign["preserved_history"]
            )
        )

    def test_physical_rollup_conserves_bytes_and_recomputes_grades(self) -> None:
        physical = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "physical-accepted-campaign"
        )
        matched = physical["matched_physical"]
        self.assertLess(matched["duration_difference_seconds"], 0.1)
        expected = {
            "adc": (260015184, 260015184, 263098368, 1.0, 64233, 0, 0, "FAIL"),
            "gpio": (
                260015184,
                192699,
                3275883,
                0.012451171875,
                0,
                64233,
                64233,
                "PASS",
            ),
            "combined": (
                520030368,
                260207883,
                266374251,
                0.5062255859375,
                64233,
                64233,
                64233,
                "FAIL",
            ),
        }
        for stream, values in expected.items():
            with self.subTest(stream=stream):
                record = matched["streams"][stream]
                selected = record["rle_auto"]
                grade = record["grade"]
                self.assertEqual(values[0], selected["logical_payload_bytes"])
                self.assertEqual(values[1], selected["encoded_payload_bytes"])
                self.assertEqual(values[2], selected["complete_wire_bytes"])
                self.assertEqual(values[3], grade["complete_wire_ratio"])
                self.assertEqual(values[4], selected["raw_frames"])
                self.assertEqual(values[5], selected["rle_frames"])
                self.assertEqual(values[6], selected["rle_runs"])
                self.assertEqual(values[7], grade["result"])
                self.assertEqual(
                    selected["complete_wire_bytes"]
                    / selected["raw_equivalent_complete_wire_bytes"],
                    grade["complete_wire_ratio"],
                )
                self.assertEqual(
                    1.0 - grade["complete_wire_ratio"],
                    grade["complete_wire_reduction_ratio"],
                )
                for equation in record["conservation"].values():
                    self.assertEqual(equation["left"], equation["right"])

        combined = matched["streams"]["combined"]
        self.assertEqual(
            10.205324234404214,
            combined["grade"]["processing_utilization_delta_percentage_points"],
        )
        self.assertEqual("PASS", combined["grade"]["bandwidth_reduction_result"])
        self.assertEqual("FAIL", combined["grade"]["processing_utilization_result"])
        self.assertEqual(
            64233,
            physical["performance"]["rle_auto"]["firmware"]["streams"]["adc"][
                "fallback_frames"
            ],
        )
        self.assertEqual(
            {
                "encoder_failure": 0,
                "not_smaller": 64233,
                "temporary_page_unavailable": 0,
            },
            physical["performance"]["rle_auto"]["firmware"]["streams"]["adc"][
                "fallback_reasons"
            ],
        )
        self.assertTrue(physical["health"]["all_validated_active_errors_zero"])
        self.assertEqual(
            0, sum(physical["health"]["validated_active_error_fields"].values())
        )
        self.assertLessEqual(
            physical["performance"]["accepted_v2_maxima"]["packet_owned_high_water"],
            200,
        )
        self.assertLessEqual(
            physical["performance"]["accepted_v2_maxima"]["temporary_page_high_water"],
            1,
        )

    def test_endurance_incident_remains_inconclusive_and_cleaned_up(self) -> None:
        endurance = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "physical-endurance-campaign"
        )
        self.assertEqual(0, endurance["passing_attempts"])
        self.assertEqual(600.0, endurance["requested_seconds"])
        self.assertEqual(
            [
                "936b1df9-1629-4f4f-87c7-1be44e8a5005",
                "d1020be8-a74c-4997-8049-840f0c66cd6b",
            ],
            [row["job_id"] for row in endurance["attempts"]],
        )
        self.assertIn("checksum mismatch", endurance["attempts"][0]["reason"])
        self.assertIn(
            "wire bytes precede frame magic", endurance["attempts"][1]["reason"]
        )
        for attempt in endurance["attempts"]:
            with self.subTest(job_id=attempt["job_id"]):
                reader = attempt["serial_reader"]
                self.assertEqual(32768, reader["high_water_bytes"])
                self.assertEqual(524288, reader["capacity_bytes"])
                self.assertLess(reader["high_water_bytes"], reader["capacity_bytes"])
                self.assertEqual(0, reader["final_bytes"])
                self.assertEqual(0, reader["final_chunks"])
                self.assertTrue(attempt["cleanup"]["stop_succeeded"])
                self.assertTrue(attempt["cleanup"]["idle_confirmed"])
                self.assertEqual([], attempt["cleanup"]["errors"])

    def test_codec_corpus_fallbacks_and_conservation_are_exact(self) -> None:
        corpus = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "host-corpus-benchmark"
        )
        codec: dict[str, Any] = corpus["codec_definition"]
        self.assertEqual(44, codec["envelope"]["header_bytes"])
        self.assertEqual(4, codec["envelope"]["trailer_bytes"])
        self.assertEqual(674, codec["adc"]["maximum_selected_runs"])
        self.assertEqual(1349, codec["gpio"]["maximum_selected_runs"])
        self.assertEqual(
            "rle wire bytes strictly less than raw wire bytes",
            codec["adaptive_selection"]["rle_selected_when"],
        )

        aggregates = {str(item["stream"]): item for item in corpus["stream_aggregates"]}
        expected = {
            "ADC": (129536, 131072, 76288, 0.58203125, 16, 16, 17713),
            "GPIO": (
                161920,
                163840,
                66973,
                0.408770751953125,
                24,
                16,
                64725,
            ),
            "COMBINED": (
                291456,
                294912,
                143261,
                0.4857754177517361,
                40,
                32,
                82438,
            ),
        }
        for stream, values in expected.items():
            with self.subTest(stream=stream):
                aggregate = aggregates[stream]
                self.assertEqual(values[0], aggregate["logical_payload_bytes"])
                self.assertEqual(values[1], aggregate["raw_complete_wire_bytes"])
                self.assertEqual(values[2], aggregate["selected_complete_wire_bytes"])
                self.assertEqual(
                    values[3], aggregate["selected_to_raw_complete_wire_ratio"]
                )
                self.assertEqual(values[4], aggregate["rle_frames"])
                self.assertEqual(values[5], aggregate["fallback_frames"])
                self.assertEqual(values[6], aggregate["run_count"])
                for equation in aggregate["conservation"].values():
                    self.assertEqual(equation["left"], equation["right"])

        workloads = {str(item["name"]): item for item in corpus["workloads"]}
        for name in (
            "gpio-alternating-bytes",
            "gpio-pseudo-random-bytes",
            "adc-quantization-noise",
            "adc-high-entropy",
        ):
            self.assertEqual(8, workloads[name]["fallback_frames"])
            self.assertEqual(1.0, workloads[name]["complete_wire_ratio"]["value"])
            self.assertTrue(workloads[name]["no_expansion"])


if __name__ == "__main__":
    unittest.main()
