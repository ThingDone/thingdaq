"""Independent contract tests for deterministic experiment aggregation."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from firmware.tools import aggregate_experiments as aggregate

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    ROOT / "firmware/tests/fixtures/aggregate_experiments/branch-reports.json"
)
GOLDEN_JSON_SHA256 = "fd7e4121947841ee843ffec909d38a0566226ce28b63a1bf58f99b11c5b92a44"
GOLDEN_MARKDOWN_SHA256 = (
    "8b6404494e788dc61d5287ed2f9d7f3f854196073312f22caee633357d0d2eee"
)


def _fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("aggregate fixture must be an object")
    return value


def _experiments() -> list[dict[str, Any]]:
    return copy.deepcopy(_fixture()["experiments"])


def _conclusions() -> list[dict[str, Any]]:
    return [
        {
            "id": "clock-smoke",
            "statement": "The bounded clock smoke passed on its own artifact.",
            "claim_scope": "physical",
            "artifact_claim": "single_build",
            "evidence_refs": [
                {
                    "experiment_id": "clock-450mhz",
                    "evidence_id": "clock-rig",
                }
            ],
        },
        {
            "id": "separate-host-results",
            "statement": "Baseline and RLE evidence remain separate results.",
            "claim_scope": "nonphysical",
            "artifact_claim": "separate",
            "evidence_refs": [
                {
                    "experiment_id": "baseline",
                    "evidence_id": "baseline-host",
                },
                {
                    "experiment_id": "rle-streaming",
                    "evidence_id": "rle-simulation",
                },
            ],
        },
    ]


def _render_fixture() -> dict[str, Any]:
    fixture = _fixture()
    experiments = copy.deepcopy(fixture["experiments"])
    manifest: list[dict[str, Any]] = []
    for item in experiments:
        manifest.append(
            {
                "experiment_id": item["experiment_id"],
                "revision": item["revision"],
                "revision_commit": item["revision_commit"],
                "revision_tree": item["revision_tree"],
                "inputs": [
                    {
                        "kind": "fixture-report",
                        "path": "firmware/tests/fixtures/aggregate_experiments/branch-reports.json",
                        "sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    return {
        "schema_version": 1,
        "kind": "thingdaq-experiment-aggregate",
        "title": "Fixture Clock, Compression, and I/O Evidence",
        "created": "2026-09-04",
        "related": list(aggregate.RELATED_LINKS),
        "baseline_commit": experiments[0]["revision_commit"],
        "matrix": {
            "path": aggregate.DEFAULT_MATRIX_PATH,
            "schema_version": 1,
            "sha256": "f" * 64,
        },
        "aggregation_policy": {
            "json_is_source_of_truth": True,
            "rounded_markdown_is_input": False,
            "cross_artifact_values_are_combined": False,
            "lower_evidence_promoted_to_physical": False,
            "untested_cross_branch_combination_is_verified": False,
        },
        "input_manifest": manifest,
        "experiments": experiments,
        "metric_groups": aggregate.group_metrics(experiments),
        "conclusions": aggregate.validate_conclusions(_conclusions(), experiments),
        "recommendations": aggregate.validate_recommendations(
            fixture["recommendations"], experiments
        ),
        "claim_limitations": [
            "Fixture candidates remain independent artifacts.",
            "Missing physical gates remain visible.",
        ],
    }


class AggregateFixtureTests(unittest.TestCase):
    def test_fixture_covers_all_raw_states_and_missing_fields(self) -> None:
        experiments = _experiments()
        states = {
            str(item.get("state", item.get("result")))
            for experiment in experiments
            for item in [
                {"result": experiment["report"]["result"]}
                if "report" in experiment
                else {"result": experiment["result"]},
                *experiment.get("report", experiment)["acceptance"],
            ]
        }
        self.assertEqual({"PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"}, states)

        missing_metrics = copy.deepcopy(experiments[0])
        del missing_metrics["report"]["metrics"]
        with self.assertRaisesRegex(
            aggregate.AggregationError, "metrics must be an array"
        ):
            aggregate.group_metrics([missing_metrics])

        missing_decision_field = copy.deepcopy(_fixture()["recommendations"][0])
        del missing_decision_field["branch_commit"]
        with self.assertRaisesRegex(
            aggregate.AggregationError, "fields must be exactly"
        ):
            aggregate.validate_recommendations([missing_decision_field], experiments)

    def test_wrong_ancestry_and_hash_mismatch_fail_closed(self) -> None:
        spec = aggregate.InputSpec(
            "candidate",
            "candidate",
            "fixture/candidate",
            "doc/results/experiments/candidate.json",
        )
        with (
            patch.object(aggregate, "_resolve_commit", return_value="2" * 40),
            patch.object(aggregate, "_is_ancestor", return_value=False),
            self.assertRaisesRegex(aggregate.AggregationError, "not descended"),
        ):
            aggregate.load_report_input(
                ROOT,
                unittest.mock.Mock(),
                b"matrix",
                spec,
                "1" * 40,
            )

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            temporary_root = Path(temporary_directory)
            evidence_path = temporary_root / "evidence.json"
            evidence_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(aggregate.AggregationError, "SHA-256 mismatch"):
                aggregate._read_hashed_local(temporary_root, "evidence.json", "0" * 64)

    def test_incomparable_units_denominators_and_evidence_stay_separate(
        self,
    ) -> None:
        groups = {
            group["name"]: group for group in aggregate.group_metrics(_experiments())
        }
        logical_rate = groups["logical_rate"]
        self.assertEqual("NONCOMPARABLE", logical_rate["status"])
        self.assertIsNone(logical_rate["derived_value"])
        self.assertEqual(4, len(logical_rate["values"]))
        for reason in (
            "unit differs",
            "denominator differs",
            "evidence level differs",
        ):
            self.assertIn(reason, logical_rate["reasons"])
        self.assertEqual(
            {item["experiment_id"] for item in logical_rate["values"]},
            {
                "baseline",
                "rle-streaming",
                "aux-input-bank",
                "clock-450mhz",
            },
        )

    def test_duplicate_candidates_and_unsafe_content_are_rejected(self) -> None:
        experiments = _experiments()
        with self.assertRaisesRegex(
            aggregate.AggregationError, "duplicate experiment identity"
        ):
            aggregate.validate_recommendations([], [*experiments, experiments[1]])

        for unsafe in (
            "api_key=fixture-secret-must-not-leak",
            "/tmp/private-fixture-capture.json",
        ):
            with self.subTest(unsafe=unsafe):
                candidate = copy.deepcopy(experiments[1])
                candidate["report"]["evidence"][0]["reason"] = unsafe
                with self.assertRaisesRegex(
                    aggregate.evidence.EvidenceError,
                    "credential-shaped|absolute POSIX path",
                ):
                    aggregate.evidence.validate_content_policy(
                        candidate, "fixture_candidate"
                    )


class AggregateDecisionPolicyTests(unittest.TestCase):
    def test_recommendations_retain_outcomes_levels_and_unavailable_gates(
        self,
    ) -> None:
        fixture = _fixture()
        normalized = aggregate.validate_recommendations(
            fixture["recommendations"], fixture["experiments"]
        )
        by_experiment = {item["experiment_id"]: item for item in normalized}

        self.assertEqual(["host"], by_experiment["baseline"]["evidence_levels"])
        self.assertEqual(
            {"PASS", "INCONCLUSIVE", "NOT_RUN"},
            {
                item["state"]
                for item in by_experiment["rle-streaming"]["acceptance_outcomes"]
            },
        )
        self.assertEqual(
            "FAIL",
            by_experiment["aux-input-bank"]["acceptance_outcomes"][0]["state"],
        )
        not_run = next(
            item
            for item in by_experiment["clock-450mhz"]["acceptance_outcomes"]
            if item["state"] == "NOT_RUN"
        )
        self.assertIn("No controlled", not_run["reason"])

    def test_invalid_decisions_and_contradictory_claims_fail_closed(self) -> None:
        fixture = _fixture()
        experiments = fixture["experiments"]
        recommendations = fixture["recommendations"]

        invalid_adopt = copy.deepcopy(recommendations[1])
        invalid_adopt["decision"] = "ADOPT"
        with self.assertRaisesRegex(
            aggregate.AggregationError, "ADOPT may cite only passed"
        ):
            aggregate.validate_recommendations([invalid_adopt], experiments)

        invalid_reject = copy.deepcopy(recommendations[0])
        invalid_reject["decision"] = "REJECT"
        with self.assertRaisesRegex(
            aggregate.AggregationError, "REJECT requires a cited failed"
        ):
            aggregate.validate_recommendations([invalid_reject], experiments)

        physical_simulation = copy.deepcopy(_conclusions()[0])
        physical_simulation["evidence_refs"] = [
            {
                "experiment_id": "rle-streaming",
                "evidence_id": "rle-simulation",
            }
        ]
        with self.assertRaisesRegex(
            aggregate.AggregationError, "physical conclusion cites nonphysical"
        ):
            aggregate.validate_conclusions([physical_simulation], experiments)

        invented_combined_build = copy.deepcopy(_conclusions()[1])
        invented_combined_build["artifact_claim"] = "single_build"
        with self.assertRaisesRegex(
            aggregate.AggregationError, "single-build conclusion combines"
        ):
            aggregate.validate_conclusions([invented_combined_build], experiments)

    def test_aggregate_policy_never_promotes_an_untested_combination(self) -> None:
        rendered = _render_fixture()
        policy = rendered["aggregation_policy"]
        self.assertFalse(policy["cross_artifact_values_are_combined"])
        self.assertFalse(policy["lower_evidence_promoted_to_physical"])
        self.assertFalse(policy["untested_cross_branch_combination_is_verified"])
        self.assertIn(
            "Independent branch results are not evidence",
            aggregate.render_markdown(rendered),
        )


class AggregateRenderingTests(unittest.TestCase):
    def test_json_and_markdown_match_golden_hashes_and_layout(self) -> None:
        rendered = _render_fixture()
        json_text, markdown = aggregate._require_deterministic(rendered)
        self.assertEqual(
            GOLDEN_JSON_SHA256,
            hashlib.sha256(json_text.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            GOLDEN_MARKDOWN_SHA256,
            hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        )
        self.assertTrue(markdown.startswith("---\ntype: report\ntitle:"))
        front_matter = markdown.split("---", 2)[1]
        for field in ("type:", "title:", "created:", "tags:", "related:"):
            self.assertIn(field, front_matter)
        for link in aggregate.RELATED_LINKS:
            self.assertIn(link, markdown)
        for heading in (
            "Executive outcomes",
            "Reproducible input manifest",
            "Metric comparability",
            "Source outcomes and limitations",
            "Evidence-backed conclusions",
            "Recommendations",
            "Aggregate claim limitations",
        ):
            self.assertEqual(1, markdown.count(f"## {heading}\n"))
        self.assertEqual(
            1,
            markdown.count("| Experiment | Revision | Commit | Tree | Inputs |"),
        )
        for state in ("PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"):
            self.assertIn(f"**{state}**", markdown)

    def test_repeated_aggregation_is_byte_identical(self) -> None:
        first = aggregate._render_pair(_render_fixture())
        second = aggregate._render_pair(_render_fixture())
        self.assertEqual(first[0].encode("utf-8"), second[0].encode("utf-8"))
        self.assertEqual(first[1].encode("utf-8"), second[1].encode("utf-8"))

    def test_atomic_failure_preserves_target_and_validation_writes_nothing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "aggregate.json"
            target.write_text("original\n", encoding="utf-8")
            with (
                patch.object(
                    aggregate.evidence.os,
                    "replace",
                    side_effect=OSError("injected aggregate replace failure"),
                ),
                self.assertRaisesRegex(OSError, "injected aggregate replace failure"),
            ):
                aggregate.evidence.atomic_write_text(target, "replacement\n")
            self.assertEqual("original\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(parent.glob(".aggregate.json.*.tmp")))

        with (
            patch.object(
                aggregate,
                "build_aggregate",
                side_effect=aggregate.AggregationError("fixture validation failed"),
            ),
            patch.object(aggregate.evidence, "atomic_write_text") as writer,
        ):
            self.assertEqual(1, aggregate.main([]))
            writer.assert_not_called()


class AggregateExactCrossAnalysisTests(unittest.TestCase):
    def test_exact_branch_inputs_build_required_cross_analysis(self) -> None:
        required_local = (
            ROOT / aggregate.DEFAULT_CLOCK_SERVICE_PATH,
            ROOT / aggregate.DEFAULT_CLOCK_SUMMARY_PATH,
        )
        if not all(path.is_file() for path in required_local):
            self.skipTest("authorized clock evidence is not present in this checkout")
        try:
            rendered = aggregate.build_aggregate(
                ROOT,
                tuple(
                    replace(spec, revision=spec.expected_commit or spec.revision)
                    for spec in aggregate.DEFAULT_INPUTS
                ),
                created=aggregate.DEFAULT_CREATED,
                clock_revision="origin/experiment/clock-450mhz",
                expected_clock_commit=aggregate.CLOCK_HEAD_COMMIT,
                clock_adr_path=aggregate.DEFAULT_CLOCK_ADR_PATH,
                clock_service_path=aggregate.DEFAULT_CLOCK_SERVICE_PATH,
                clock_service_sha256=aggregate.CLOCK_SERVICE_SHA256,
                clock_summary_path=aggregate.DEFAULT_CLOCK_SUMMARY_PATH,
                clock_summary_sha256=aggregate.CLOCK_SUMMARY_SHA256,
            )
        except aggregate.AggregationError as error:
            if "git rev-parse" in str(error) or "git cat-file" in str(error):
                self.skipTest(f"candidate Git refs are unavailable: {error}")
            raise

        analysis = rendered["cross_experiment_analysis"]
        clock = analysis["clock_450mhz"]
        self.assertEqual(12, clock["adc_resolution_bits"])
        self.assertEqual(450_000_000, clock["clock_tree_hz"]["cpu_hz"])
        self.assertEqual([8, 8], clock["phase_and_completion"]["completion_counts"])
        self.assertEqual("SIDE_BY_SIDE_ONLY", clock["comparison_to_600mhz"]["status"])
        self.assertIsNone(clock["comparison_to_600mhz"]["derived_delta"])
        self.assertFalse(clock["historical_528mhz_context"]["canonical_input"])

        rle = analysis["rle_streaming"]
        self.assertTrue(rle["logical_equality"]["host_corpus_raw_rle_equal"])
        physical = {item["stream"]: item for item in rle["matched_physical"]["streams"]}
        self.assertEqual(0.0, physical["ADC"]["complete_wire_reduction_ratio"])
        self.assertEqual(
            0.987548828125,
            physical["GPIO"]["complete_wire_reduction_ratio"],
        )
        self.assertEqual("FAIL", physical["COMBINED"]["overall_value_result"])
        self.assertEqual("PASS", rle["protocol_v1_compatibility"]["result"])
        self.assertEqual("INCONCLUSIVE", rle["endurance"]["result"])

        aux_input = analysis["aux_input_bank"]
        self.assertIsNone(aux_input["highest_sustained_raw_profile"])
        self.assertEqual("FAIL_BEFORE_START", aux_input["eight_input_regression"])
        self.assertEqual(4, len(aux_input["rate_profiles"]))
        maximum = aux_input["rate_profiles"][0]
        self.assertEqual(
            8_000_000,
            maximum["eight_input"]["combined_payload_bytes_per_second"],
        )
        self.assertEqual(
            12_000_000,
            maximum["sixteen_input"]["combined_payload_bytes_per_second"],
        )
        self.assertEqual(
            "NOT_RUN", aux_input["processing_and_queues"]["target_processing_load"]
        )

        aux_output = analysis["aux_output_bank"]
        self.assertEqual("PASS", aux_output["host_output_correctness"]["result"])
        self.assertEqual("NOT_RUN", aux_output["physical_output_correctness"]["result"])
        self.assertEqual("NOT_RUN", aux_output["loopback"]["lag_stability"])
        self.assertEqual("PASS", aux_output["combined_adc_gpio_preservation"]["result"])
        self.assertEqual(
            38_461, aux_output["refill_margin"]["packet_and_usb_margin_us"]
        )
        self.assertTrue(
            aux_output["host_lifecycle_safety"]["stop_holds_observed_latch"]
        )
        self.assertEqual(0, aux_output["nondriving_controls"]["drive_requests_written"])

        interactions = {
            item["id"]: item for item in analysis["shared_conflicts_and_synergies"]
        }
        self.assertEqual(
            3,
            interactions["dma_xbar_and_memory_ownership"]["resource_identity"][
                "edma_channel"
            ],
        )
        self.assertEqual(
            3,
            len(
                set(
                    interactions["independent_protocol_v2_extensions"][
                        "protocol_v2_sha256"
                    ].values()
                )
            ),
        )
        self.assertFalse(interactions["combined_binary_not_tested"]["verified"])

        policy = rendered["recommendation_policy"]
        recommendations = {
            item["experiment_id"]: item for item in policy["experiment_recommendations"]
        }
        self.assertEqual(
            {
                "clock-450mhz": "CONTINUE",
                "rle-streaming": "CONTINUE",
                "aux-input-bank": "REJECT",
                "aux-output-bank": "CONTINUE",
            },
            {
                experiment_id: item["decision"]
                for experiment_id, item in recommendations.items()
            },
        )
        for experiment_id, item in recommendations.items():
            source = next(
                candidate
                for candidate in rendered["experiments"]
                if candidate["experiment_id"] == experiment_id
            )
            self.assertEqual(source["revision_commit"], item["branch_commit"])
            self.assertTrue(item["acceptance_outcomes"])
        self.assertEqual(
            {
                "cpu_hz": 600_000_000,
                "protocol_version": 1,
                "stream_encoding": "RAW",
                "gpio_width_bits": 8,
                "auxiliary_bank_mode": "DISABLED",
            },
            {
                key: policy["production_defaults"][key]
                for key in (
                    "cpu_hz",
                    "protocol_version",
                    "stream_encoding",
                    "gpio_width_bits",
                    "auxiliary_bank_mode",
                )
            },
        )
        self.assertIn(
            "Python-only prototype", policy["python_client_migration"]["scope"]
        )
        self.assertEqual(5, len(policy["staged_integration"]))

        matrix = policy["compound_test_matrix"]
        self.assertEqual(1, matrix["immutable_artifact_count"])
        self.assertEqual(24, matrix["configuration_count"])
        self.assertEqual(24, len(matrix["configurations"]))
        self.assertEqual(24, len({item["id"] for item in matrix["configurations"]}))
        for configuration in matrix["configurations"]:
            self.assertIn(configuration["bank_mode"], {"DISABLED", "INPUT", "OUTPUT"})
            self.assertEqual(
                configuration["bank_mode"] == "INPUT",
                configuration["gpio_width_bits"] == 16,
            )
            self.assertEqual(
                configuration["bank_mode"] == "OUTPUT",
                configuration["output_rate_hz"] == 1_000_000,
            )
        self.assertEqual(
            {
                "protocol-v1 RAW",
                "eight-input frames with D16-D23 disabled",
                "600 MHz production build profile",
            },
            {item["path"] for item in policy["rollback_paths"]},
        )
        self.assertIn("human measurements", policy["follow_up"]["classification"])

        markdown = aggregate.render_markdown(rendered)
        headings = (
            "## Cross-experiment analysis",
            "### 450 MHz physical smoke",
            "### RAW versus RLE_AUTO",
            "### Eight-input versus 16-input acquisition",
            "### Auxiliary output",
            "### Shared conflicts and synergies",
            "### Production defaults and optional capabilities",
            "### Python client compatibility and migration cost",
            "## Staged integration and rollback plan",
            "## Minimum compound test matrix",
            "## Human follow-up",
        )
        for heading in headings:
            self.assertEqual(1, markdown.splitlines().count(heading))

        tampered = copy.deepcopy(rendered["experiments"])
        output = next(
            item for item in tampered if item["experiment_id"] == "aux-output-bank"
        )
        output["report"]["result"] = "PASS"
        with self.assertRaisesRegex(
            aggregate.AggregationError, "recommendation_result"
        ):
            aggregate.build_recommendation_policy(tampered, analysis)

    def test_protocol_extension_hash_mismatch_fails_closed(self) -> None:
        payload = b'{"extension":"rle-streaming","protocol_version":2}\n'
        experiment = {
            "experiment_id": "rle-streaming",
            "revision_commit": "1" * 40,
            "declared_files": [
                {
                    "path": "protocol/protocol-v2.json",
                    "sha256": "0" * 64,
                }
            ],
        }
        with (
            patch.object(aggregate, "_git_blob", return_value=payload),
            self.assertRaisesRegex(aggregate.AggregationError, "protocol_v2_sha256"),
        ):
            aggregate.load_protocol_extension(ROOT, experiment)


class AggregateRepositorySafetyTests(unittest.TestCase):
    def test_aggregator_has_a_read_only_git_and_import_surface(self) -> None:
        source_path = ROOT / "firmware/tools/aggregate_experiments.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        imports: set[str] = set()
        string_literals: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                string_literals.add(node.value)

        for candidate_module in (
            "rle_streaming",
            "aux_input_bank",
            "aux_output_bank",
            "clock_450mhz",
        ):
            self.assertNotIn(candidate_module, imports)

        forbidden_git_actions = {
            "checkout",
            "cherry-pick",
            "commit",
            "fetch",
            "merge",
            "pull",
            "push",
            "rebase",
            "reset",
            "switch",
            "update-ref",
            "worktree",
        }
        self.assertTrue(forbidden_git_actions.isdisjoint(string_literals))
        for allowed_action in ("cat-file", "merge-base", "rev-parse"):
            self.assertIn(allowed_action, string_literals)


if __name__ == "__main__":
    unittest.main()
