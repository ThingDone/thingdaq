"""Execute every documented example against the no-hardware simulator path."""

from __future__ import annotations

import io
import os
import runpy
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from thingdone_daq import ThingDAQ

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
EXAMPLES_ROOT = PACKAGE_ROOT / "examples"
EXAMPLE_SCRIPTS = tuple(
    path for path in sorted(EXAMPLES_ROOT.glob("*.py")) if not path.name.startswith("_")
)


class SimulatorExampleTests(unittest.TestCase):
    def test_protocol_upgrade_sample_mismatch_closes_transport(self) -> None:
        demo = runpy.run_path(str(EXAMPLES_ROOT / "protocol_upgrade.py"))
        main = demo["main"]
        sessions = []
        simulated = ThingDAQ.simulated

        def open_session(**options):
            session = simulated(**options)
            sessions.append(session)
            return session

        with (
            patch.object(ThingDAQ, "simulated", side_effect=open_session),
            patch.dict(
                main.__globals__,
                {"synthetic_v3_adc_payload": lambda first, count: bytes(count * 4)},
            ),
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(AssertionError, "ADC channel values differ"),
        ):
            main()
        self.assertEqual(1, len(sessions))
        self.assertFalse(sessions[0].transport.is_open)
        self.assertFalse(sessions[0].reader.is_running)

    def test_every_public_example_runs_offline_and_identifies_itself(self) -> None:
        self.assertEqual(11, len(EXAMPLE_SCRIPTS))
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
                if script.name == "protocol_upgrade.py":
                    self.assert_protocol_upgrade_results(completed.stdout)

    def assert_protocol_upgrade_results(self, output: str) -> None:
        lines = output.splitlines()
        self.assertIn("simulated=true physical_required=false", lines[0])
        self.assertIn("hardware_throughput=not_measured", lines[0])
        self.assertIn("board=TEENSY_40", lines[1])
        self.assertIn("protocol=3", lines[1])
        self.assertIn(
            "compatibility persona=v3 negotiated=v3 compressed_capture=exact PASS",
            lines,
        )
        for version, gpio_rate in ((1, 4_000_000), (2, 1_000_000)):
            self.assertIn(
                f"compatibility persona=v{version} negotiated=v{version} "
                f"adc_pair_rate_hz=1000000 gpio_sample_rate_hz={gpio_rate} "
                "equality=exact loss=none final_state=IDLE "
                "transport_closed=true reader_stopped=true PASS",
                lines,
            )
        self.assertIn("supported_tuples=60", lines)
        self.assertEqual(60, sum(line.startswith("tuple[") for line in lines))
        self.assertIn(
            "defaults: ADC|GPIO HARDWARE ADLER32 3 CPU_600MHZ "
            "ADC_1MHZ_GPIO_1MHZ DISABLED 8 RLE_AUTO PACK12 12 1000000 1000000",
            lines,
        )
        clocks = [line for line in lines if line.startswith("applied_cpu_hz=")]
        self.assertEqual(
            [
                f"applied_cpu_hz={cpu} ipg_hz=150000000 adc_hz=37500000 "
                "pit_hz=24000000 timestamp_hz=8000000 readback=exact"
                for cpu in (600000000, 450000000, 600000000)
            ],
            clocks,
        )
        for run in (1, 2, 3):
            compressed = run != 2
            adc_bytes = 6072 if compressed else 8096
            gpio_bytes = 4051 if compressed else 8096
            expected = [
                f"run={run} running_reconfiguration=INVALID_STATE settings_unchanged=true",
                (
                    f"run={run} stream=adc frames=2 items=2024 equality=exact "
                    f"raw_sample_bytes=8096 transmitted_sample_bytes={adc_bytes} "
                    f"transmitted_frame_bytes={adc_bytes + 120}"
                ),
                (
                    f"run={run} adc_packing_saved_bytes={2024 if compressed else 0} "
                    f"adc_packing_savings_percent={25.0 if compressed else 0.0}"
                ),
                (
                    f"run={run} stream=gpio frames=2 items=8096 equality=exact "
                    f"raw_sample_bytes=8096 transmitted_sample_bytes={gpio_bytes} "
                    f"transmitted_frame_bytes={gpio_bytes + 120}"
                ),
                (
                    f"run={run} gpio_rle_frames={1 if compressed else 0} "
                    f"gpio_raw_frames={1 if compressed else 2} "
                    f"gpio_fallback_frames={1 if compressed else 0}"
                ),
                f"run={run} state=STOPPED pending_frames=0 readback=exact loss=none",
            ]
            self.assertEqual(
                expected, [line for line in lines if line.startswith(f"run={run} ")]
            )
        self.assertEqual(
            "PASS runs=3 equality=exact final_state=STOPPED "
            "transport_closed=true reader_stopped=true",
            lines[-1],
        )


if __name__ == "__main__":
    unittest.main()
