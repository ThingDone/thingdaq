"""Public layout metadata, wire accounting and short writes through runtime."""

from __future__ import annotations

import subprocess

import pytest
from test_firmware_runtime import COMPILE_SOURCES, FIRMWARE_SOURCE, REPOSITORY_ROOT
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import decode_v3_response
from thingdone_daq.protocol_v3 import V3FrameParser


@pytest.fixture(scope="module", params=[450, 600])
def runtime_binary(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("v3-layout") / "runtime"
    flags = [
        "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
        f"-DTHINGDAQ_EXPERIMENT_CPU_HZ={request.param}000000U",
    ]
    compiled = subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wconversion",
            "-Wsign-conversion",
            "-pedantic",
            "-fno-exceptions",
            "-fno-rtti",
            *flags,
            f"-I{FIRMWARE_SOURCE}",
            str(REPOSITORY_ROOT / "firmware/tests/v3_layout_runtime_test.cpp"),
            *(str(path) for path in COMPILE_SOURCES),
            "-o",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    return output, request.param


@pytest.mark.parametrize("width", [8, 16])
@pytest.mark.parametrize("compressed", [False, True])
def test_selected_layout_and_wire_accounting(runtime_binary, width, compressed):
    binary, cpu = runtime_binary
    if compressed and cpu == 450:
        pytest.skip("450 MHz advertises RAW only")
    result = subprocess.run(
        [str(binary), str(width), str(int(compressed))], check=True, capture_output=True
    )
    parser = V3FrameParser()
    frames = []
    for at in range(0, len(result.stdout), 5):
        frames.extend(parser.feed(result.stdout[at : at + 5]))
    replies = {
        f.header.request_id: decode_v3_response(f)
        for f in frames
        if f.header.kind not in (1, 2)
    }
    assert len(replies) == 12
    assert replies[7].error_code == c.ErrorCode.BUSY
    assert all(r.error_code == c.ErrorCode.OK for i, r in replies.items() if i != 7)
    assert replies[6].value.state == c.DeviceState.DRAINING
    for run, status_id, multiplier in [(1, 8, 2), (2, 12, 1)]:
        status = replies[status_id].value
        assert status.state == c.DeviceState.STOPPED and status.pending_frames == 0
        for kind, name, count in [
            (1, "adc", 1008),
            (2, "gpio", 4032 if width == 8 else 2016),
        ]:
            data = [
                f for f in frames if f.header.kind == kind and f.header.run_id == run
            ]
            assert len(data) == 4032 // count * multiplier
            assert getattr(status, f"{name}_items_per_frame") == count
            assert getattr(status, f"{name}_max_frame_bytes") == 4092
            assert getattr(status, f"{name}_retention_ticks") == 200 * count * 8
            assert getattr(status, f"{name}_wire_bytes_transmitted") == sum(
                f.header.total_length for f in data
            )
            assert getattr(status, f"{name}_items_produced") == len(data) * count
            assert getattr(status, f"{name}_items_dropped") == 0
            assert getattr(status, f"{name}_codec_deadline_drops") == 0
            assert getattr(status, f"{name}_codec_resource_drops") == 0
            assert getattr(status, f"{name}_codec_completed") == (
                len(data) if compressed else 0
            )
            assert getattr(status, f"{name}_codec_raw") == (
                len(data) // 2 if compressed and kind == 2 else 0
            )
            for sequence, frame in enumerate(data):
                assert frame.header.sequence == sequence
                assert frame.header.item_count == count
                assert frame.header.first_sample_ticks == sequence * count * 8
                assert frame.header.total_length == (
                    3084
                    if compressed and kind == 1
                    else 62 + width // 8
                    if compressed and kind == 2 and sequence % 2 == 0
                    else 4092
                )
