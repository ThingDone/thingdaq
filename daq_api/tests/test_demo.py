"""Focused tests for the executable offline synthetic prototype."""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import serial
import tomllib
from thingdone_daq import DeviceState, InMemoryTransport, ThingDAQ
from thingdone_daq.demo import main, run_demo
from thingdone_daq.models import AdcChannelView

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class OfflineDemoTests(unittest.TestCase):
    def test_demo_validates_both_streams_with_tiny_parser_chunks(self) -> None:
        output = io.StringIO()
        transport = InMemoryTransport(read_chunk_size=7)
        daq = ThingDAQ.open(transport, read_size=7)

        with patch.object(ThingDAQ, "simulated", return_value=daq):
            run_demo(frame_count=2, parser_chunk_size=7, output=output)

        transcript = output.getvalue()
        self.assertIn("streams=ADC+GPIO source=SYNTHETIC", transcript)
        self.assertIn(
            "ADC RAMP  0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15",
            transcript,
        )
        self.assertIn("ADC JOIN  2020, 2021, 2022, 2023 -> 2024, 2025", transcript)
        self.assertIn("GPIO JOIN 0xcc, 0xcd, 0xce, 0xcf -> 0xd0, 0xd1", transcript)
        self.assertIn("COUNTERS  adc=2 gpio=2 dropped=0 errors=0", transcript)
        self.assertIn(
            "FINAL     state=IDLE adc=2 gpio=2 dropped=0 errors=0", transcript
        )
        self.assertIn("CLEANUP   transport=CLOSED", transcript)
        self.assertIn("PASS      validated 2 ADC + 2 GPIO frames", transcript)
        self.assertEqual(DeviceState.IDLE, transport.device.state)
        self.assertFalse(transport.is_open)

    def test_main_returns_nonzero_when_a_sample_mismatches(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        transport = InMemoryTransport(read_chunk_size=13)
        daq = ThingDAQ.open(transport, read_size=13)

        with (
            patch.object(ThingDAQ, "simulated", return_value=daq),
            patch.object(AdcChannelView, "__getitem__", return_value=4095),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(["--frame-count", "1", "--parser-chunk-size", "13"])

        self.assertEqual(1, result)
        self.assertNotIn("PASS", stdout.getvalue())
        self.assertIn("FAIL      ADC synthetic sample", stderr.getvalue())
        self.assertEqual(DeviceState.IDLE, transport.device.state)
        self.assertFalse(transport.is_open)

    def test_cli_needs_no_serial_hardware_network_or_credentials(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                serial,
                "Serial",
                side_effect=AssertionError("serial hardware access attempted"),
            ) as serial_open,
            patch.object(
                serial,
                "serial_for_url",
                side_effect=AssertionError("serial URL access attempted"),
            ) as serial_url_open,
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("rig network access attempted"),
            ) as rig_connection,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(["--frame-count", "1", "--parser-chunk-size", "5"])

        self.assertEqual(0, result, stderr.getvalue())
        self.assertIn("PASS      validated 1 ADC + 1 GPIO frames", stdout.getvalue())
        serial_open.assert_not_called()
        serial_url_open.assert_not_called()
        rig_connection.assert_not_called()

    def test_module_and_console_entry_points_match(self) -> None:
        environment = os.environ.copy()
        source_path = str(PACKAGE_ROOT / "src")
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            source_path
            if existing_python_path is None
            else os.pathsep.join((source_path, existing_python_path))
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "thingdone_daq.demo",
                "--frame-count",
                "1",
                "--parser-chunk-size",
                "31",
            ],
            cwd=PACKAGE_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("PASS      validated 1 ADC + 1 GPIO frames", completed.stdout)
        with (PACKAGE_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)
        self.assertEqual(
            "thingdone_daq.demo:main",
            pyproject["project"]["scripts"]["thingdone-daq-demo"],
        )


if __name__ == "__main__":
    unittest.main()
