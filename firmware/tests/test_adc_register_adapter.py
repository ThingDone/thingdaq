"""Host-compiled fake-register tests for the Teensy dual-ADC adapters."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
FAKE_TEENSY_INCLUDE = REPOSITORY_ROOT / "firmware/tests/fakes/teensy40"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/adc_register_adapter_test.cpp"


class AdcRegisterAdapterTests(unittest.TestCase):
    def test_etc_probe_preserves_dma_handshake_until_capture_teardown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="thingdaq-adc-request-") as directory:
            executable = Path(directory) / "adc-request"
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-DTHINGDAQ_EXPERIMENT_ADC_ETC_PROBE=1",
                    "-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1",
                    "-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1",
                    "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
                    "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
                    f"-I{FAKE_TEENSY_INCLUDE}",
                    f"-I{FIRMWARE_SOURCE}",
                    str(
                        REPOSITORY_ROOT
                        / "firmware/tests/adc_request_probe_register_test.cpp"
                    ),
                    "-o",
                    str(executable),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_timer_enable_through_completion_observation_stays_in_itcm(self) -> None:
        source = (FIRMWARE_SOURCE / "adc_trigger_teensy.cpp").read_text()
        start = source.index("bool armTimersAndObserve(bool completion_diagnostic)")
        end = source.index("\n}\n", start)
        hot = source[start:end]
        self.assertTrue(
            source[:start].rstrip().endswith("THINGDAQ_ADC_TRIGGER_TARGET_HOT_CODE")
        )
        self.assertLess(
            hot.index("masterPit().TCTRL = PIT_TCTRL_TEN"),
            hot.index("captureCompletionStatusTransitions()"),
        )
        cold_start = source.index("bool armFromStopped(bool completion_diagnostic)")
        cold_end = source.index(
            "return armTimersAndObserve(completion_diagnostic)", cold_start
        )
        self.assertNotIn("TCTRL = PIT_TCTRL_TEN", source[cold_start:cold_end])

    def test_routes_timing_order_and_resource_isolation(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for target-register adapter tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-adc-registers-") as directory:
            executable = Path(directory) / "adc-register-adapter-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O3",
                    "-flto",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    "-fno-exceptions",
                    "-fno-rtti",
                    f"-I{FAKE_TEENSY_INCLUDE}",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )


if __name__ == "__main__":
    unittest.main()
