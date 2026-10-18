"""Check the actual stopped-setup writes for ordinary and experimental DMA."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("rle", [False, True])
def test_reserved_priorities_and_preemption_match_ordinary_setup(tmp_path, rle):
    executable = tmp_path / "priority"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DARDUINO_TEENSY40=1",
            "-D__IMXRT1062__=1",
            *(
                [
                    "-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1",
                    "-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1",
                    "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
                    "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
                ]
                if rle
                else []
            ),
            f"-I{ROOT / 'firmware/tests/fakes/teensy40'}",
            f"-I{ROOT / 'firmware/src'}",
            str(ROOT / "firmware/tests/edma_priority_test.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True)
