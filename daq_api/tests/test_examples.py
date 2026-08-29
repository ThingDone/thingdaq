"""Execute every documented example against the no-hardware simulator path."""

from __future__ import annotations

import os
import subprocess
import sys
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
        self.assertEqual(9, len(EXAMPLE_SCRIPTS))
        environment = os.environ.copy()
        source_path = str(PACKAGE_ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (source_path, environment.get("PYTHONPATH")))
        )

        for script in EXAMPLE_SCRIPTS:
            with self.subTest(example=script.name):
                completed = subprocess.run(
                    [sys.executable, str(script)],
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


if __name__ == "__main__":
    unittest.main()
