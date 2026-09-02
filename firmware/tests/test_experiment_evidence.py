"""Focused fail-closed tests for experiment evidence and rendering."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from firmware.tools import experiment_evidence as evidence

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "experiments/experiment-matrix.json"
GOLDEN_JSON_SHA256 = "467d38d1c42c79a95d2522dff05ed97b895a17b42c8513b1467ea10e6f4131d4"
GOLDEN_MARKDOWN_SHA256 = (
    "d508f4d4f3d41284a69585ed0dc4035b3fc4b80dcb66a1fa10dd29a6296d24d7"
)


def _matrix() -> evidence.ExperimentMatrix:
    return evidence.load_experiment_matrix(MATRIX_PATH)


def _acceptance_values(operator: str) -> tuple[object, object]:
    values: dict[str, tuple[object, object]] = {
        "all": (True, {"complete": True}),
        "between_inclusive": ([0, 1], 0.5),
        "byte_equal": ("byte-identical", "byte-identical"),
        "eq": (True, True),
        "exact_conservation": (
            True,
            {"frames": {"left": 4, "right": 4}},
        ),
        "gte": (1, 1),
        "hash_equal": ({"artifact": "a" * 64}, {"artifact": "a" * 64}),
        "lte": (1.0, 0.25),
        "none": (None, None),
        "present": (["source.commit"], {"source": {"commit": "1" * 40}}),
    }
    return copy.deepcopy(values[operator])


def _report(matrix: evidence.ExperimentMatrix) -> dict[str, Any]:
    input_record = {
        "path": "experiments/experiment-matrix.json",
        "sha256": "a" * 64,
    }
    command = {
        "argv": ["python3", "firmware/tools/experiment_evidence.py"],
        "network": False,
        "serial_hardware": False,
        "firmware_upload": False,
        "user_input": False,
    }
    evidence_records = [
        {
            "id": "host-validation",
            "level": "host",
            "result": "PASS",
            "reason": None,
            "method": "Offline schema validation and deterministic rendering.",
            "command": copy.deepcopy(command),
            "inputs": [copy.deepcopy(input_record)],
            "host_os_family": "TestOS",
            "host_architecture": "test-architecture",
            "toolchain_identity": "Python test-runtime",
        },
        {
            "id": "simulator-capture",
            "level": "simulated",
            "result": "PASS",
            "reason": None,
            "method": "Deterministic in-memory protocol simulation.",
            "command": copy.deepcopy(command),
            "inputs": [copy.deepcopy(input_record)],
            "simulator_identity": "thingdaq-test-simulator",
            "protocol_identity": "protocol-v1 sha256:" + "b" * 64,
            "deterministic_budget": "four complete frames",
        },
    ]
    acceptance_records: list[dict[str, Any]] = []
    for check_id in matrix.experiment("baseline")["required_acceptance_checks"]:
        definition = matrix.acceptance_checks[check_id]
        expected, observed = _acceptance_values(str(definition["operator"]))
        levels = list(definition["required_evidence_levels"])
        evidence_id = "host-validation" if "host" in levels else "simulator-capture"
        acceptance_records.append(
            {
                "id": check_id,
                "description": definition["description"],
                "state": "PASS",
                "reason": None,
                "operator": definition["operator"],
                "expected": expected,
                "observed": observed,
                "evidence_ids": [evidence_id],
                "required_evidence_levels": levels,
            }
        )

    metrics: list[dict[str, Any]] = []
    for name, value in (
        ("measurement_duration_seconds", 1.0),
        ("gpio_samples_observed", 4_064),
    ):
        definition = matrix.metric_definitions[name]
        metrics.append(
            {
                "name": name,
                "value": value,
                "unit": definition["unit"],
                "denominator": definition["denominator"],
                "scope": definition["scope"],
                "evidence_level": "simulated",
                "evidence_ids": ["simulator-capture"],
            }
        )

    experiment = matrix.experiment("baseline")
    return {
        "schema_version": matrix.report_contract["schema_version"],
        "matrix_schema_version": matrix.schema_version,
        "experiment_id": "baseline",
        "title": experiment["title"],
        "created": "2026-09-01",
        "result": "PASS",
        "reason": None,
        "summary": "Deterministic fixture for the experiment evidence contract.",
        "identity": {
            "repository": matrix.report_contract["identity"]["repository"],
            "branch": "main",
            "baseline_branch": matrix.data["branches"]["baseline"],
            "baseline_commit": "1" * 40,
            "source_commit": "2" * 40,
            "source_tree": "3" * 40,
            "source_clean": True,
            "source_id": "4" * 64,
            "protocol_contract_path": "protocol/protocol-v1.json",
            "protocol_version": 1,
            "protocol_sha256": "5" * 64,
            "toolchains": [
                {
                    "name": "python",
                    "version": "3.test",
                    "identity": "CPython test-runtime",
                }
            ],
        },
        "evidence": evidence_records,
        "metrics": metrics,
        "acceptance": acceptance_records,
        "limitations": [
            copy.deepcopy(matrix.claim_limitations[limitation_id])
            for limitation_id in experiment["required_limitations"]
        ],
        "artifacts": [],
        "related": [
            "[[Evidence-Index]]",
            "[[Protocol-V1]]",
            "[[System-Overview]]",
            "[[soak-harness]]",
        ],
    }


class ExperimentMatrixValidationTests(unittest.TestCase):
    def test_matrix_rejects_missing_provenance_and_unknown_taxonomy(self) -> None:
        raw = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

        missing_provenance = copy.deepcopy(raw)
        missing_provenance["report_contract"]["identity"]["required_fields"].remove(
            "source_commit"
        )
        with self.assertRaisesRegex(
            evidence.MatrixValidationError,
            "source_commit",
        ):
            evidence.validate_experiment_matrix(missing_provenance)

        unknown_state = copy.deepcopy(raw)
        unknown_state["result_states"].append("MAYBE")
        unknown_state["result_state_semantics"]["MAYBE"] = {
            "meaning": "Not part of the common taxonomy.",
            "reason_required": True,
            "reason_must_be_null": False,
        }
        with self.assertRaisesRegex(evidence.MatrixValidationError, "four common"):
            evidence.validate_experiment_matrix(unknown_state)

        unknown_level = copy.deepcopy(raw)
        unknown_level["evidence_levels"].append("emulated")
        unknown_level["evidence_level_semantics"]["emulated"] = {
            "meaning": "An undeclared evidence implementation.",
            "physical_claims_allowed": False,
        }
        unknown_level["report_contract"]["evidence_record"][
            "conditional_identity_fields"
        ]["emulated"] = ["simulator_identity"]
        with self.assertRaisesRegex(evidence.MatrixValidationError, "not implemented"):
            evidence.validate_experiment_matrix(unknown_level)

    def test_report_schema_rejects_every_fail_closed_boundary(self) -> None:
        matrix = _matrix()

        def missing_provenance(report: dict[str, Any]) -> None:
            del report["identity"]["source_commit"]

        def unknown_state(report: dict[str, Any]) -> None:
            report["result"] = "MAYBE"

        def unknown_level(report: dict[str, Any]) -> None:
            report["evidence"][0]["level"] = "emulated"

        def incomparable_unit(report: dict[str, Any]) -> None:
            report["metrics"][0]["unit"] = "byte"

        def malformed_acceptance(report: dict[str, Any]) -> None:
            del report["acceptance"][0]["operator"]

        def secret(report: dict[str, Any]) -> None:
            report["evidence"][0]["method"] = "api_key=must-not-be-recorded"

        def absolute_path(report: dict[str, Any]) -> None:
            report["evidence"][0]["command"]["argv"].append("/tmp/capture.bin")

        def pass_reason(report: dict[str, Any]) -> None:
            report["acceptance"][0]["reason"] = "PASS must not explain a failure"

        def fail_without_reason(report: dict[str, Any]) -> None:
            record = next(
                item
                for item in report["acceptance"]
                if item["id"] == "provenance_clean"
            )
            record["state"] = "FAIL"
            record["observed"] = False
            report["result"] = "FAIL"
            report["reason"] = "A required acceptance check failed."

        cases: tuple[tuple[str, Callable[[dict[str, Any]], None], str], ...] = (
            ("missing provenance", missing_provenance, "source_commit"),
            ("unknown state", unknown_state, "unknown result state"),
            ("unknown evidence level", unknown_level, "unknown evidence level"),
            ("incomparable unit", incomparable_unit, "does not match"),
            ("malformed acceptance", malformed_acceptance, "missing required fields"),
            ("credential content", secret, "credential-shaped"),
            ("absolute path", absolute_path, "absolute POSIX path"),
            ("PASS reason", pass_reason, "must be null for PASS"),
            ("FAIL reason", fail_without_reason, "required for FAIL"),
        )
        for name, mutate, pattern in cases:
            with self.subTest(name=name):
                report = _report(matrix)
                mutate(report)
                with self.assertRaisesRegex(evidence.ReportValidationError, pattern):
                    evidence.prepare_report(matrix, report, tracked_report=False)


class ExperimentRenderingTests(unittest.TestCase):
    def test_json_and_markdown_match_golden_hashes_and_structure(self) -> None:
        matrix = _matrix()
        normalized = evidence.prepare_report(
            matrix,
            _report(matrix),
            tracked_report=False,
        )
        json_text = evidence.canonical_json_text(normalized)
        markdown = evidence.render_markdown(matrix, normalized)

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
        for link in (
            "[[Evidence-Index]]",
            "[[Protocol-V1]]",
            "[[System-Overview]]",
            "[[soak-harness]]",
        ):
            self.assertIn(link, markdown)
        for section in evidence.MARKDOWN_REQUIRED_SECTIONS:
            self.assertIn(f"## {section}\n", markdown)

    def test_normalization_has_stable_ordering(self) -> None:
        matrix = _matrix()
        canonical = evidence.prepare_report(
            matrix,
            _report(matrix),
            tracked_report=False,
        )
        shuffled = _report(matrix)
        for field in ("evidence", "metrics", "acceptance", "limitations"):
            shuffled[field].reverse()
        shuffled["identity"]["toolchains"].reverse()
        shuffled["related"].reverse()

        observed = evidence.prepare_report(
            matrix,
            shuffled,
            tracked_report=False,
        )
        self.assertEqual(
            evidence.canonical_json_text(canonical),
            evidence.canonical_json_text(observed),
        )
        self.assertEqual(
            evidence.render_markdown(matrix, canonical),
            evidence.render_markdown(matrix, observed),
        )

    def test_atomic_write_failure_preserves_target_and_removes_staging_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "report.json"
            target.write_text("original\n", encoding="utf-8")

            with (
                patch.object(
                    evidence.os,
                    "replace",
                    side_effect=OSError("injected replace failure"),
                ),
                self.assertRaisesRegex(OSError, "injected replace failure"),
            ):
                evidence.atomic_write_text(target, "replacement\n")

            self.assertEqual("original\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(parent.glob(".report.json.*.tmp")))

    def test_two_writes_are_byte_identical_and_check_rejects_stale_output(
        self,
    ) -> None:
        matrix = _matrix()
        report = _report(matrix)
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            first_json = parent / "first.json"
            first_markdown = parent / "first.md"
            second_json = parent / "second.json"
            second_markdown = parent / "second.md"
            evidence.write_report_pair(
                matrix,
                report,
                first_json,
                first_markdown,
                verify_files=False,
            )
            evidence.write_report_pair(
                matrix,
                report,
                second_json,
                second_markdown,
                verify_files=False,
            )

            self.assertEqual(first_json.read_bytes(), second_json.read_bytes())
            self.assertEqual(
                first_markdown.read_bytes(),
                second_markdown.read_bytes(),
            )
            evidence.check_report_pair(
                matrix,
                first_json,
                first_json,
                first_markdown,
                verify_files=False,
            )
            first_markdown.write_text(
                first_markdown.read_text(encoding="utf-8") + "stale\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(evidence.EvidenceDriftError, "stale"):
                evidence.check_report_pair(
                    matrix,
                    first_json,
                    first_json,
                    first_markdown,
                    verify_files=False,
                )

    def test_contradictory_failure_cannot_be_rendered_as_pass(self) -> None:
        matrix = _matrix()
        report = _report(matrix)
        queue_check = next(
            item for item in report["acceptance"] if item["id"] == "queue_bounds"
        )
        queue_check["observed"] = 1.5

        with self.assertRaisesRegex(
            evidence.ReportValidationError,
            "PASS contradicts",
        ):
            evidence.render_markdown(matrix, report)


if __name__ == "__main__":
    unittest.main()
