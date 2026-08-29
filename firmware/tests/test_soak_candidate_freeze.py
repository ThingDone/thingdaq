"""Tests for the fail-closed Phase 11 soak-candidate freeze boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FREEZER_PATH = REPOSITORY_ROOT / "firmware/tools/freeze_soak_candidate.py"
SPEC = importlib.util.spec_from_file_location("freeze_soak_candidate", FREEZER_PATH)
assert SPEC is not None and SPEC.loader is not None
freezer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = freezer
SPEC.loader.exec_module(freezer)


class SoakCandidateFreezeTests(unittest.TestCase):
    def test_repository_protected_set_is_stable_and_excludes_generated_junk(
        self,
    ) -> None:
        paths = freezer.collect_protected_files()
        relative = {freezer.repository_path(path) for path in paths}

        self.assertIn("firmware/soak/candidate.json", relative)
        self.assertIn("firmware/soak/validator.py", relative)
        self.assertIn("firmware/tests/generated/rig_soak_synthetic.py", relative)
        self.assertIn("firmware/src/generated/protocol_constants.h", relative)
        self.assertIn(
            "daq_api/src/teensy_daq/_generated/protocol_constants.py", relative
        )
        self.assertIn("protocol/fixtures/manifest.json", relative)
        self.assertIn("firmware/tools/freeze_soak_candidate.py", relative)
        self.assertFalse(any("__pycache__" in path for path in relative))
        self.assertFalse(any("/build/" in path for path in relative))
        self.assertEqual(len(relative), len(paths))

        records = freezer.file_records(paths)
        self.assertEqual(
            freezer.records_tree_sha256(records),
            freezer.records_tree_sha256(list(records)),
        )

    def test_rebuild_validation_requires_identical_manifest_bound_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="soak-freeze-build-") as raw:
            root = Path(raw)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            manifest = self._write_build(first)
            self._write_build(second)

            observed_manifest, artifacts, hashes = freezer.validate_rebuilds(
                first, second
            )
            self.assertEqual(manifest, observed_manifest)
            self.assertEqual(hashes["first"], hashes["second"])
            self.assertEqual(
                {"firmware.elf", "firmware.hex", "firmware.map"},
                {record["path"] for record in artifacts},
            )

            (second / "firmware.hex").write_bytes(b"different")
            with self.assertRaisesRegex(
                freezer.FreezeError, "disagrees with its manifest"
            ):
                freezer.validate_rebuilds(first, second)

    def test_verify_fails_on_source_addition_change_and_staged_artifact_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="soak-freeze-tree-") as raw:
            root = Path(raw)
            self._write_minimum_protected_tree(root)
            stage = root / "stage"
            stage.mkdir()
            staged_artifact = stage / "firmware.hex"
            staged_artifact.write_bytes(b"hex")
            candidate_path = root / "firmware/soak/candidate.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            protected = freezer.file_records(
                freezer.collect_protected_files(root=root), root=root
            )
            staged = freezer.file_records((staged_artifact,), root=root)
            freeze = {
                "schema_version": freezer.LOCK_SCHEMA_VERSION,
                "candidate": {
                    "path": "firmware/soak/candidate.json",
                    "sha256": freezer.canonical_json_sha256(candidate),
                    "artifact_name": "firmware.hex",
                    "artifact_sha256": "a" * 64,
                    "source_id": "b" * 64,
                    "build_id": "tdaq-bbbbbbbbbbbbbbbb",
                    "fqbn": "test:fqbn",
                },
                "protected": {
                    "tree_sha256": freezer.records_tree_sha256(protected),
                    "files": protected,
                },
                "staged": {"directory": "stage", "files": staged},
            }

            result = freezer.verify_freeze(freeze, root=root)
            self.assertEqual("PASS", result["result"])

            source = root / "firmware/soak/validator.py"
            source.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(freezer.FreezeError, "changed firmware"):
                freezer.verify_freeze(freeze, root=root)
            source.write_text("validator\n", encoding="utf-8")

            added = root / "tools/new_source.py"
            added.write_text("new\n", encoding="utf-8")
            with self.assertRaisesRegex(
                freezer.FreezeError, "added tools/new_source.py"
            ):
                freezer.verify_freeze(freeze, root=root)
            added.unlink()

            staged_artifact.write_bytes(b"drift")
            with self.assertRaisesRegex(
                freezer.FreezeError, "changed stage/firmware.hex"
            ):
                freezer.verify_freeze(freeze, root=root)

    @staticmethod
    def _write_build(directory: Path) -> dict[str, object]:
        artifact_values = {
            "firmware.elf": b"elf",
            "firmware.hex": b"hex",
            "firmware.map": b"map",
        }
        artifacts = []
        for name, value in artifact_values.items():
            path = directory / name
            path.write_bytes(value)
            artifacts.append(
                {
                    "path": name,
                    "size_bytes": len(value),
                    "sha256": freezer.sha256_bytes(value),
                }
            )
        manifest: dict[str, object] = {
            "schema_version": 10,
            "target": {"fqbn": "test:fqbn"},
            "source": {
                "source_id": "b" * 64,
                "build_id": "tdaq-bbbbbbbbbbbbbbbb",
                "firmware_inputs_clean": True,
                "firmware_input_changes": [],
            },
            "memory_usage": {"ram": 1},
            "binary_inspection": {"map": "checked"},
            "artifacts": artifacts,
        }
        (directory / "build-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return manifest

    @staticmethod
    def _write_minimum_protected_tree(root: Path) -> None:
        for relative in freezer.PROTECTED_INPUTS:
            path = root / relative
            if Path(relative).suffix or relative.endswith("firmware.ino"):
                path.parent.mkdir(parents=True, exist_ok=True)
                if relative == "firmware/soak/candidate.json":
                    path.write_text(
                        json.dumps(
                            {
                                "artifact": {
                                    "name": "firmware.hex",
                                    "sha256": "a" * 64,
                                },
                                "firmware": {
                                    "source_id": "b" * 64,
                                    "build_id": "tdaq-bbbbbbbbbbbbbbbb",
                                },
                                "board": {"fqbn": "test:fqbn"},
                            }
                        ),
                        encoding="utf-8",
                    )
                else:
                    path.write_text("validator\n", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)
                (path / "tracked.py").write_text("tracked\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
