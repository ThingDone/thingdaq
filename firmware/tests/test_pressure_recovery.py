"""Host-compiled adversarial firmware pressure and recovery tests."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/pressure_recovery_test.cpp"

PRODUCTION_SOURCES = (
    "acquisition_controller.cpp",
    "firmware_runtime.cpp",
    "adc_initializer.cpp",
    "adc_trigger.cpp",
    "adc_frame_packer.cpp",
    "packet_buffer_pipeline.cpp",
    "synthetic_source.cpp",
    "control_state.cpp",
    "usb_transport.cpp",
    "statistics.cpp",
    "protocol.cpp",
    "checksum.cpp",
    "checksum_benchmark.cpp",
    "clock_health.cpp",
    "gpio_clock_diagnostic.cpp",
    "gpio_raw_capture.cpp",
    "gpio_batch_packer.cpp",
    "gpio_capture_diagnostic.cpp",
)


class FirmwarePressureRecoveryTests(unittest.TestCase):
    def test_pressure_and_recovery_matrix(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(
            prefix="thingdaq-pressure-recovery-"
        ) as directory:
            executable = Path(directory) / "pressure-recovery-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    "-fno-exceptions",
                    "-fno-rtti",
                    "-DTHINGDAQ_TESTING=1",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    *(str(FIRMWARE_SOURCE / source) for source in PRODUCTION_SOURCES),
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
