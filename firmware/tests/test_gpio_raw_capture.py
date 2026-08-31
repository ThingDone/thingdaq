"""Host-compiled ownership, cache, pressure, and statistics checks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/gpio_raw_capture_test.cpp"


class GpioRawCaptureTests(unittest.TestCase):
    def test_rotating_dma_ownership_and_exact_overrun_accounting(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-gpio-raw-") as directory:
            executable = Path(directory) / "gpio-raw-capture-test"
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
                    str(FIRMWARE_SOURCE / "gpio_raw_capture.cpp"),
                    str(FIRMWARE_SOURCE / "statistics.cpp"),
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

    def test_portable_layer_has_no_heap_or_hardware_dependency(self) -> None:
        source = "\n".join(
            (FIRMWARE_SOURCE / name).read_text(encoding="utf-8")
            for name in ("gpio_raw_capture.h", "gpio_raw_capture.cpp")
        )
        for token in (
            "std::vector",
            "std::deque",
            "malloc(",
            "calloc(",
            "realloc(",
            "operator new",
            "core_pins.h",
            "imxrt.h",
            "arm_dcache",
            "attachInterrupt",
            "IntervalTimer",
            "DMAChannel",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("kOverflowDestination", source)
        self.assertIn("invalidateBeforeCpuRead", source)
        self.assertIn("discardBeforeDmaWrite", source)

    def test_target_adapter_uses_fixed_gpio_psr_scatter_gather_route(self) -> None:
        raw_source = (FIRMWARE_SOURCE / "gpio_raw_capture_teensy.cpp").read_text(
            encoding="utf-8"
        )
        route_source = (FIRMWARE_SOURCE / "gpio_dma_route_teensy.h").read_text(
            encoding="utf-8"
        )
        source = raw_source + "\n" + route_source

        for token in (
            "&GPIO2_PSR",
            "descriptor.SOFF = 0",
            "DMA_TCD_CSR_ESG | DMA_TCD_CSR_INTMAJOR",
            "protocol_v1::kGpioSamplesPerFrame",
            "DMA_DCHPRI2",
            "board::kGpioEdmaPriority",
            "gpio_dma_route::clearEdmaChannelState()",
            "gpio_dma_route::enableEdmaRequest()",
            "gpio_dma_route::disableEdmaRequest()",
            "tcd.CSR | DMA_TCD_CSR_DREQ",
            "waitForCompleteStopBoundary()",
            "onMajorLoopComplete",
            "selectStandardGpioInputs(IOMUXC_GPR_GPR27, GPIO2_GDIR)",
            "arm_dcache_flush_delete(&g_gpio_raw_dma_descriptors",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

        for token in (
            "DMA_TCD_CSR_INTHALF",
            "IntervalTimer",
            "DMAChannel",
            "digitalRead(",
            "digitalWrite(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
