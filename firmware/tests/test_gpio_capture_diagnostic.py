"""Host coverage for safe autonomous GPIO diagnostic policy and evidence."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/gpio_capture_diagnostic_test.cpp"


class GpioCaptureDiagnosticTests(unittest.TestCase):
    def test_fail_closed_fixture_selection_and_evidence_classification(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(
            prefix="teensy-daq-gpio-diagnostic-"
        ) as directory:
            executable = Path(directory) / "gpio-capture-diagnostic-test"
            compile_result = subprocess.run(
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
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "gpio_capture_diagnostic.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                compile_result.returncode,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                [str(executable)], capture_output=True, check=False, text=True
            )
            self.assertEqual(
                0,
                run_result.returncode,
                run_result.stdout + run_result.stderr,
            )

    def test_target_path_is_production_capture_and_contains_no_output_write(
        self,
    ) -> None:
        source = (FIRMWARE_SOURCE / "gpio_capture_diagnostic_teensy.cpp").read_text(
            encoding="utf-8"
        )

        for token in (
            "gpio_capture::teensyRawCapture()",
            "gpio_capture::BoundedRawWordDiagnostic",
            "gpio_packer::packGpio2Word",
            "selectStandardGpioInputs(IOMUXC_GPR_GPR27, GPIO2_GDIR)",
            "kDiagnosticTimeoutCycles",
            "capture.stop()",
            "final.ring.quiescent",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

        for token in (
            "GPIO2_DR",
            "GPIO2_DR_SET",
            "GPIO2_DR_CLEAR",
            "digitalWrite(",
            "pinMode(",
            "OUTPUT",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        fixture_header = (
            FIRMWARE_SOURCE / "gpio_capture_diagnostic_teensy.h"
        ).read_text(encoding="utf-8")
        self.assertIn("MetadataKind::kDocumentationOnly", fixture_header)
        self.assertIn("DriveSafety::kUnspecified", fixture_header)


if __name__ == "__main__":
    unittest.main()
