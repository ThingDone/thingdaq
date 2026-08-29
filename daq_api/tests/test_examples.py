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


if __name__ == "__main__":
    unittest.main()
