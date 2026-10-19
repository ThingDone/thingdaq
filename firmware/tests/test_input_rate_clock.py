"""Compile real scheduler/layout/packet code for every research build selection."""

import importlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("cpu", [600_000_000, 450_000_000, 528_000_000])
@pytest.mark.parametrize("equal", [0, 1])
@pytest.mark.parametrize("release", [False, True])
def test_input_rate_clock(cpu, equal, release, tmp_path):
    if release and equal:
        pytest.skip("fixed-rate policy does not support the equal-rate override")
    source = ROOT / "firmware/src"
    executable = tmp_path / "input-rate-clock"
    compiled = subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-DTHINGDAQ_EXPERIMENT_CPU_HZ={cpu}U",
            f"-DTHINGDAQ_EXPERIMENT_EQUAL_RATES={equal}",
            f"-DTHINGDAQ_RELEASE_FIXED_1MHZ={int(release)}",
            f"-I{source}",
            str(ROOT / "firmware/tests/input_rate_clock_test.cpp"),
            *(
                str(source / name)
                for name in (
                    "variable_rate_scheduler.cpp",
                    "packet_buffer_pipeline.cpp",
                    "rle_encoder.cpp",
                    "protocol.cpp",
                    "checksum.cpp",
                    "gpio_clock_diagnostic.cpp",
                )
            ),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_build_identity_distinguishes_clock_and_ratio(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "firmware/tools"))
    builder = importlib.import_module("build_input_experiment")
    original = builder.base.BuildIdentity(
        source_id="a" * 64,
        build_id="thingdaq-aaaaaaaaaaaaaaaa",
        timestamp_epoch=1788552674,
        timestamp_utc="2026-09-04T20:11:14Z",
    )
    identities = [
        builder.experiment_identity(original, cpu, equal)
        for cpu in (600, 450, 528)
        for equal in (False, True)
    ]
    assert len({identity.build_id for identity in identities}) == 6
    assert all(
        identity.timestamp_epoch == original.timestamp_epoch for identity in identities
    )
    assert builder.experiment_identity(original, 600, False) == identities[0]
    small = builder.experiment_identity(original, 450, False, release_fixed_1mhz=True)
    large = builder.experiment_identity(
        original, 450, False, release_fixed_1mhz=True, large_adc_frame=True
    )
    assert len({small.build_id, large.build_id, *(i.build_id for i in identities)}) == 8
    rle = builder.experiment_identity(
        original,
        600,
        False,
        release_fixed_1mhz=True,
        large_adc_frame=True,
        gpio_rle=True,
    )
    probe = builder.experiment_identity(
        original,
        600,
        False,
        release_fixed_1mhz=True,
        large_adc_frame=True,
        gpio_rle=True,
        gpio_preempt_probe=True,
    )
    assert probe.build_id != rle.build_id
    etc_probe = builder.experiment_identity(
        original,
        600,
        False,
        release_fixed_1mhz=True,
        large_adc_frame=True,
        gpio_rle=True,
        adc_etc_probe=True,
    )
    assert etc_probe.build_id not in (probe.build_id, rle.build_id)


def test_large_frame_manifest_retention_matches_fixed_release_layout(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "firmware/tools"))
    builder = importlib.import_module("build_input_experiment")
    retention = builder.large_frame_retention({"total_frames": 200})
    assert len(retention["profiles"]) == 1
    profile = retention["profiles"][0]
    assert profile["adc_pair_rate_hz"] == profile["gpio_sample_rate_hz"] == 1_000_000
    for mode in ("DISABLED", "INPUT"):
        assert profile["modes"][mode] == {
            "coverage_ticks": 8096,
            "combined_retention_us": 101200,
            "single_stream_retention_us": 202400,
        }
