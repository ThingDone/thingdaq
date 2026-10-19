"""Independent C++ contract oracles and public-codec pressure regressions."""

import subprocess

import pytest
from test_pressure_recovery import FIRMWARE_SOURCE, PRODUCTION_SOURCES, REPOSITORY_ROOT


@pytest.fixture(scope="module")
def portable_binary(tmp_path_factory):
    executable = tmp_path_factory.mktemp("v3-portable") / "regressions"
    subprocess.run(
        [
            "g++",
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
            "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
            "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
            f"-I{FIRMWARE_SOURCE}",
            str(REPOSITORY_ROOT / "firmware/tests/v3_portable_regressions_test.cpp"),
            *(str(FIRMWARE_SOURCE / name) for name in PRODUCTION_SOURCES),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return executable


@pytest.mark.parametrize(
    "scenario", ["bytes", "shapes", "pressure", "leases", "maximum"]
)
def test_public_contract_adversarial_cases(portable_binary, scenario):
    result = subprocess.run(
        [str(portable_binary), scenario], check=False, capture_output=True, timeout=60
    )
    assert result.returncode == 0, result.stderr.decode()
