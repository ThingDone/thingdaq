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

    def test_report_is_canonical_and_preserves_rig_inconclusive(self) -> None:
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
        self.assertEqual("INCONCLUSIVE", records["physical-campaign"]["result"])
        self.assertFalse(
            records["physical-campaign"]["scope_limitations"]["physical_data_collected"]
        )
        self.assertFalse(
            any(metric["evidence_level"] == "rig" for metric in normalized["metrics"])
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
            "7c639104f78866eb7e6191b58b2bc5349342e480",
            identity["source_commit"],
        )
        self.assertEqual(
            "85f2698ba97fb1defe827c4c12b5cd1e746a7ccc518b7868d4135a5b50605d8b",
            identity["source_id"],
        )
        self.assertEqual(
            "014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222",
            identity["protocol_sha256"],
        )

        physical = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "physical-campaign"
        )
        self.assertEqual(
            "2b9990ee46b3f9eff999d285c7e3fefb13947e79fda5d977b336ad75dab19aa3",
            physical["protocols"]["v2_sha256"],
        )
        self.assertEqual("thingdaq-85f2698ba97fb1de", physical["firmware_build_id"])
        self.assertEqual(
            "856006e31046e0166287ca281e407f54d71f25eae4f7fd32b04484c3532da6da",
            physical["firmware_artifact_sha256"],
        )
        self.assertEqual(
            "760c99e79fe50a4634a17e7c6bb205af36f0ec4c9844ac91b1acec909873d515",
            physical["campaign_index_sha256"],
        )
        self.assertEqual(
            {
                "d9c0e047-1152-4c63-b5dd-506a905bc7db",
                "816e750c-002a-4212-b7f9-c1e390fecb27",
            },
            {str(attempt["job_id"]) for attempt in physical["attempts"]},
        )
        self.assertEqual([], physical["accepted_runs"])
        self.assertTrue(
            all(not attempt["runner_started"] for attempt in physical["attempts"])
        )
        for stream in ("adc", "gpio", "combined"):
            self.assertTrue(
                all(
                    value is None
                    for value in physical["physical_measurements"][stream].values()
                )
            )
        self.assertEqual(
            "INCONCLUSIVE",
            physical["decisions"]["physical_bandwidth_benefit"]["result"],
        )

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
