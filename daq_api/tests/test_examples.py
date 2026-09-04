"""Execute every documented example against the no-hardware simulator path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
EXAMPLES_ROOT = PACKAGE_ROOT / "examples"
EXAMPLE_SCRIPTS = tuple(
    path for path in sorted(EXAMPLES_ROOT.glob("*.py")) if not path.name.startswith("_")
)


class SimulatorExampleTests(unittest.TestCase):
    def test_every_public_example_runs_offline_and_identifies_itself(self) -> None:
        self.assertEqual(10, len(EXAMPLE_SCRIPTS))
        environment = os.environ.copy()
        source_path = str(PACKAGE_ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (source_path, environment.get("PYTHONPATH")))
        )

        for script in EXAMPLE_SCRIPTS:
            with self.subTest(example=script.name):
                runner = f"""
import runpy
import socket
import sys
import serial
import serial.tools.list_ports

def forbidden(*args, **kwargs):
    raise AssertionError("default example attempted hardware or network access")

socket.create_connection = forbidden
serial.Serial = forbidden
serial.serial_for_url = forbidden
serial.tools.list_ports.comports = forbidden
script = {str(script)!r}
sys.path.insert(0, {str(EXAMPLES_ROOT)!r})
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""
                completed = subprocess.run(
                    [sys.executable, "-c", runner],
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(
                    0,
                    completed.returncode,
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                self.assertIn(
                    f"example={script.stem}",
                    completed.stdout,
                )
                self.assertEqual("", completed.stderr)

    def test_preloaded_output_example_emits_opt_in_simulated_artifacts(self) -> None:
        script = EXAMPLES_ROOT / "preloaded_output.py"
        environment = os.environ.copy()
        source_path = str(PACKAGE_ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (source_path, environment.get("PYTHONPATH")))
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            json_path = Path(temporary_directory) / "output-demo.json"
            markdown_path = Path(temporary_directory) / "output-demo.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--output",
                    str(json_path),
                ],
                cwd=REPOSITORY_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("timing=SIMULATED", completed.stdout)
            self.assertIn("SIMULATED finite transition tick=0", completed.stdout)
            self.assertIn("SIMULATED infinite stop=HELD", completed.stdout)
            self.assertIn(
                "SIMULATED underrun fault=UNDERRUN output=FAULTED",
                completed.stdout,
            )
            self.assertIn(
                "common_epoch=IDLE streams=NONE data_after_fault=False",
                completed.stdout,
            )
            evidence = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(1, evidence["schema_version"])
            self.assertEqual(1, evidence["matrix_schema_version"])
            self.assertEqual("aux-output-bank", evidence["experiment_id"])
            self.assertEqual("INCONCLUSIVE", evidence["result"])
            simulated = evidence["evidence"][0]
            self.assertEqual("simulated", simulated["level"])
            self.assertFalse(simulated["hardware_accessed"])
            self.assertEqual(
                ["finite", "infinite", "underrun"],
                [scenario["name"] for scenario in simulated["scenarios"]],
            )
            self.assertEqual(
                [0, 16, 24, 48, 64, 72, 96, 96],
                [event["tick"] for event in simulated["scenarios"][0]["transitions"]],
            )
            self.assertEqual("UNDERRUN", simulated["scenarios"][2]["fault"])
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertTrue(markdown.startswith("---\ntype: report\n"))
            self.assertIn("[[ADR-008-Experimental-Aux-Output-Bank]]", markdown)
            self.assertIn("Every timing value is simulated", markdown)


if __name__ == "__main__":
    unittest.main()
