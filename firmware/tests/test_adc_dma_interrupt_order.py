"""Execute the target's DMA service logic with deterministic interrupt ordering."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=[4, 6])
def interrupt_order_executable(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("adc-interrupt-order")
    source = (ROOT / "firmware/src/adc_dma_capture_teensy.cpp").read_text()
    functions = []
    for signature in (
        "std::size_t waitForAlignedPipeline()",
        "bool servicePendingDmaPair()",
    ):
        start = source.index(signature)
        end = source.index("\n}\n", start) + 3
        functions.append(source[start:end])
    (directory / "adc_dma_service_under_test.h").write_text("\n".join(functions))
    executable = directory / "interrupt-order"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-DTEST_PIPELINE_DEPTH={request.param}",
            f"-I{directory}",
            str(ROOT / "firmware/tests/adc_dma_interrupt_order_test.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
    )
    return executable


@pytest.mark.parametrize(
    "scenario",
    [
        "ordinary-completion",
        "latched-accounted-completion",
        "new-completion-during-processing",
        "no-new-progress",
        "skew",
        "outside-window",
        "invalid-destination",
        "dma-error",
        "ring-rejection",
    ],
)
def test_dma_interrupt_order(interrupt_order_executable, scenario):
    subprocess.run(
        [str(interrupt_order_executable), scenario],
        check=True,
        capture_output=True,
    )
