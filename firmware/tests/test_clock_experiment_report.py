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
        self.assertEqual(
            "clock-528mhz-physical-campaign-00003", physical["campaign_id"]
        )
        self.assertEqual(
            "073fff540d685ed32f0e1aff5d7b12935b6b9c7b8d0aef0fce0b80c077d9cb33",
            physical["campaign_index_sha256"],
        )
        self.assertTrue(physical["current_physical_conclusions_source"])
        self.assertEqual("UNOBSERVED_BEFORE_PROGRAMMING", physical["hardware_serial"])
        self.assertIsNone(physical["observed_hardware_serial"])
        self.assertFalse(
            physical["hardware_serial_policy"]["historical_serial_is_acceptance_rule"]
        )
        self.assertFalse(physical["scope_limitations"]["physical_data_collected"])
        self.assertEqual([], physical["accepted_runs"])
        self.assertEqual(
            "UNAVAILABLE_NO_ACCEPTED_RUN",
            physical["physical_measurements"]["status"],
        )
        for field in (
            "measurement_duration_seconds",
            "adc_pair_rate_hz",
            "gpio_sample_rate_hz",
            "complete_frame_loss",
            "command_latency_p99_milliseconds",
            "acquisition_service_utilization_ratio",
            "usb_service_utilization_ratio",
            "queue_high_water",
            "process_peak_rss_growth_bytes",
        ):
            with self.subTest(field=field):
                self.assertIsNone(physical["physical_measurements"][field])
        self.assertEqual(
            [],
            physical["physical_measurements"][
                "abba_temperature_trace_millidegrees_celsius"
            ],
        )
        self.assertIsNone(
            physical["physical_measurements"]["abba_temperature_statistics"]
        )
        self.assertFalse(physical["cleanup"]["runner_cleanup_applicable"])
        self.assertTrue(
            physical["cleanup"]["service_healthy_and_queue_empty_after_each_job"]
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
                "653e1775-53b6-41ce-94a1-5f8457dca224",
                "af097495-abab-450a-9f46-802fecf3addb",
            },
            {str(attempt["job_id"]) for attempt in physical["attempts"]},
        )
        self.assertEqual(
            {
                "clock-528mhz-physical-campaign-00001",
                "clock-528mhz-physical-campaign-00002",
            },
            {
                str(campaign["campaign_id"])
                for campaign in physical["superseded_campaigns"]
            },
        )
        self.assertTrue(
            all(
                campaign["use_for_current_conclusions"] is False
                for campaign in physical["superseded_campaigns"]
            )
        )
        profile_artifacts: dict[str, dict[str, Any]] = physical["profile_artifacts"]
        self.assertEqual(
            "thingdaq-e1364ec283663ec2", profile_artifacts["600"]["build_id"]
        )
        self.assertEqual(
            "thingdaq-3842de65930ac76d", profile_artifacts["528"]["build_id"]
        )
        self.assertTrue(profile_artifacts["600"]["submitted"])
        self.assertFalse(profile_artifacts["528"]["submitted"])
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
