"""Regression checks for the generated 528 MHz experiment report."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from firmware.tools import experiment_evidence as evidence

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "experiments/experiment-matrix.json"
REPORT_JSON = ROOT / "doc/results/experiments/clock-528mhz.json"
REPORT_MARKDOWN = ROOT / "doc/results/experiments/clock-528mhz.md"
REPORT_OUTPUTS = (
    "doc/results/experiments/clock-528mhz.json",
    "doc/results/experiments/clock-528mhz.md",
)


class ClockExperimentReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = evidence.load_experiment_matrix(MATRIX_PATH)
        self.report = evidence.load_json_object(REPORT_JSON)

    def test_report_is_canonical_and_preserves_inconclusive_rig_evidence(
        self,
    ) -> None:
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

        records = {str(record["id"]): record for record in normalized["evidence"]}
        self.assertEqual("PASS", records["dual-profile-local-gate"]["result"])
        physical = records["physical-campaign"]
        self.assertEqual("INCONCLUSIVE", physical["result"])
        self.assertFalse(physical["scope_limitations"]["physical_data_collected"])
        self.assertEqual(
            [],
            physical["physical_measurements"][
                "abba_temperature_trace_millidegrees_celsius"
            ],
        )
        self.assertIsNone(
            physical["physical_measurements"]["abba_temperature_statistics"]
        )
        self.assertFalse(
            any(metric["evidence_level"] == "rig" for metric in normalized["metrics"])
        )

    def test_report_pins_both_profiles_and_every_campaign_job(self) -> None:
        local_gate = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "dual-profile-local-gate"
        )
        profiles: dict[str, dict[str, Any]] = local_gate["profiles"]
        self.assertEqual(
            "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
            profiles["600"]["fqbn"],
        )
        self.assertEqual(
            "teensy:avr:teensy40:usb=serial,speed=528,opt=o2std",
            profiles["528"]["fqbn"],
        )
        self.assertEqual(
            133_333, profiles["600"]["primary_conversion_margin_picoseconds"]
        )
        self.assertEqual(
            15_151, profiles["528"]["primary_conversion_margin_picoseconds"]
        )

        physical = next(
            record
            for record in self.report["evidence"]
            if record["id"] == "physical-campaign"
        )
        self.assertEqual(
            {
                "3828ce14-97f8-436b-a979-03ea0a634316",
                "1debfc21-6999-494f-9c36-1995990e8f36",
                "b65cacb4-1161-424f-a03c-1ad38b85c272",
            },
            {str(attempt["job_id"]) for attempt in physical["attempts"]},
        )
        self.assertEqual(
            "INCONCLUSIVE",
            physical["decisions"]["performance_compatibility"]["result"],
        )
        self.assertEqual(
            "INCONCLUSIVE",
            physical["decisions"]["thermal_benefit"]["result"],
        )


if __name__ == "__main__":
    unittest.main()
