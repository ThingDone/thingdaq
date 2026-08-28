"""Host-compiled paired ADC DMA ownership and target-shape checks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/adc_dma_capture_test.cpp"


class AdcDmaCaptureTests(unittest.TestCase):
    def test_dual_barrier_cache_rotation_and_exact_loss_accounting(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="teensy-daq-adc-dma-") as directory:
            executable = Path(directory) / "adc-dma-capture-test"
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
                    str(FIRMWARE_SOURCE / "adc_dma_capture.cpp"),
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

    def test_portable_core_has_no_heap_or_hardware_dependency(self) -> None:
        source = "\n".join(
            (FIRMWARE_SOURCE / name).read_text(encoding="utf-8")
            for name in (
                "dma_buffer_ownership.h",
                "adc_dma_capture.h",
                "adc_dma_capture.cpp",
            )
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
            "DMAChannel",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

        self.assertIn("kAllConvertersMask", source)
        self.assertIn("serviceDiscarded", source)
        self.assertIn("recordAdcEtcError", source)

    def test_target_adapter_uses_fixed_interleaved_halfword_tcds(self) -> None:
        source = (FIRMWARE_SOURCE / "adc_dma_capture_teensy.cpp").read_text(
            encoding="utf-8"
        )
        for token in (
            "&ADC1_R0",
            "&ADC2_R0",
            "DMA_TCD_ATTR_SSIZE(1U) | DMA_TCD_ATTR_DSIZE(1U)",
            "descriptor.SOFF = 0",
            "descriptor.NBYTES_MLNO = sizeof(std::uint16_t)",
            "static_cast<std::int16_t>(sizeof(SamplePair))",
            "protocol_v1::kAdcPairsPerFrame",
            "DMA_TCD_CSR_ESG | DMA_TCD_CSR_INTMAJOR",
            "DMA_DCHPRI0",
            "DMA_DCHPRI1",
            "DMAMUX_SOURCE_ADC1",
            "DMAMUX_SOURCE_ADC2",
            "ADC_GC_DMAEN",
            "arm_dcache_flush_delete(&g_adc_dma_descriptors",
            "NVIC_SET_PRIORITY(IRQ_ADC_ETC_ERR, board::kAdcEdmaIrqPriority)",
            "recordAdcEtcError",
            "onMajorLoopComplete",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

        for token in (
            "DMA_TCD_CSR_INTHALF",
            "DMAChannel",
            "analogRead(",
            "std::vector",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
