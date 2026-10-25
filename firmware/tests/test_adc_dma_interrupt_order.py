"""Execute the target's DMA service logic with deterministic interrupt ordering."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=[(4, False), (6, False), (4, True)])
def interrupt_order_executable(tmp_path_factory, request):
    depth, diagnostic = request.param
    directory = tmp_path_factory.mktemp("adc-interrupt-order")
    source = (ROOT / "firmware/src/adc_dma_capture_teensy.cpp").read_text()
    functions = []
    for signature in (
        "std::size_t waitForSafePipelineProgress()",
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
            f"-DTEST_PIPELINE_DEPTH={depth}",
            *(["-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1"] if diagnostic else []),
            f"-I{directory}",
            f"-I{ROOT / 'firmware/src'}",
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
        "adc0-one-ahead",
        "adc1-one-ahead",
        "adc0-ahead-no-common",
        "adc1-ahead-no-common",
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


@pytest.fixture(scope="module")
def stop_boundary_executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp("adc-stop-boundary")
    source = (ROOT / "firmware/src/adc_dma_capture_teensy.cpp").read_text()
    functions = []
    for signature in (
        "constexpr std::uint16_t stopBoundaryArmMinimumPairs(",
        "bool waitForCompleteStopBoundary()",
    ):
        start = source.index(signature)
        end = source.index("\n}\n", start) + 3
        functions.append(source[start:end])
    (directory / "adc_dma_stop_under_test.h").write_text("\n".join(functions))
    executable = directory / "stop-boundary"
    subprocess.run(
        ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
         f"-I{directory}",
         str(ROOT / "firmware/tests/adc_dma_stop_boundary_test.cpp"),
         "-o", str(executable)],
        check=True, capture_output=True,
    )
    return executable


@pytest.mark.parametrize("scenario", [
    "ordinary", "adc0-done", "adc1-done", "both-done", "unprepared",
    "faulted", "insufficient-headroom",
])
def test_stop_boundary_preserves_scatter_gather(stop_boundary_executable, scenario):
    subprocess.run([str(stop_boundary_executable), scenario], check=True, capture_output=True)
