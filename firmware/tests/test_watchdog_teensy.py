"""Exercise the real watchdog adapter's bounded handshakes with fake registers."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WatchdogTests(unittest.TestCase):
    def test_register_handshakes_and_failures(self):
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            executable = Path(directory) / "watchdog-test"
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    "-DARDUINO_TEENSY40",
                    "-D__IMXRT1062__",
                    "-DTHINGDAQ_HOST_REGISTER_TEST",
                    "-I",
                    str(ROOT / "tests/fakes/watchdog"),
                    "-I",
                    str(ROOT / "tests/fakes/teensy40"),
                    "-I",
                    str(ROOT / "src"),
                    str(ROOT / "tests/watchdog_teensy_test.cpp"),
                    str(ROOT / "src/watchdog_teensy.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            for mode in (
                "narrow",
                "wide",
                "masked",
                "unlock-failure",
                "config-failure",
            ):
                with self.subTest(mode=mode):
                    subprocess.run([str(executable), mode], check=True, timeout=3)
