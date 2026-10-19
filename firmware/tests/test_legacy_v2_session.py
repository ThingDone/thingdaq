"""Actual runtime sessions retain public v2 bytes even in private-codec builds."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest
from test_firmware_runtime import COMPILE_SOURCES, FIRMWARE_SOURCE, REPOSITORY_ROOT
from thingdone_daq._generated.protocol_v3_constants import DeviceState, ErrorCode
from thingdone_daq.models import decode_response
from thingdone_daq.models_v3 import decode_v3_response
from thingdone_daq.protocol_v2 import IncrementalCompatibleFrameParser
from thingdone_daq.protocol_v3 import V3FrameParser


@pytest.fixture(scope="module", params=[False, True])
def runtime_binary(request, tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("legacy-session") / "runtime"
    flags = ["-DTHINGDAQ_RELEASE_FIXED_1MHZ=1"]
    if request.param:
        flags += [
            "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
            "-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1",
            "-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1",
            "-DTHINGDAQ_DEFERRED_CODECS=1",
            "-DTHINGDAQ_ADC_PACK12=1",
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
            str(REPOSITORY_ROOT / "firmware/tests/legacy_v2_session_test.cpp"),
            *(str(path) for path in COMPILE_SOURCES),
            "-o",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    return output


@pytest.mark.parametrize("width", [8, 16])
def test_raw_layout_mode_switch_and_partial_usb_tail(runtime_binary, width):
    result = subprocess.run(
        [str(runtime_binary), str(width)], check=True, capture_output=True
    )
    data = result.stdout
    replies = {}
    frames = []
    while data:
        size = struct.unpack_from("<I", data, 12)[0]
        assert 48 <= size <= len(data)
        wire, data = data[:size], data[size:]
        assert wire[4] in (1, 2, 3)  # no private codec version
        parser = V3FrameParser() if wire[4] == 3 else IncrementalCompatibleFrameParser()
        parsed = []
        for at in range(0, len(wire), 5):
            parsed.extend(parser.feed(wire[at : at + 5]))
        assert len(parsed) == 1
        frame = parsed[0]
        if wire[5] in (1, 2):
            frames.append(frame)
        else:
            response = (
                decode_v3_response(frame) if wire[4] == 3 else decode_response(frame)
            )
            replies[response.request_id] = response
    assert len(replies) == 18
    assert (
        replies[3].error_code == ErrorCode.UNSUPPORTED_CONFIGURATION
    )  # UNSUPPORTED_CONFIGURATION
    assert replies[10].error_code == ErrorCode.BUSY  # BUSY while legacy USB tail drains
    assert int(replies[12].error_code) == 0  # same settings accepted after drain
    assert (
        replies[18].error_code == ErrorCode.UNSUPPORTED_VERSION
    )  # v1 CONFIGURE stays unsupported
    assert all(
        int(reply.error_code) == 0
        for key, reply in replies.items()
        if key not in (3, 10, 18)
    )
    assert replies[11].value.pending_frames > 0
    assert replies[11].value.state == DeviceState.DRAINING  # DRAINING
    for run_id in (1, 2):
        for kind in (1, 2):
            selected = [
                f for f in frames if f.header.run_id == run_id and f.header.kind == kind
            ]
            count = (506 if width == 16 else 1012) if kind == 1 else 32384 // width
            assert len(selected) == 32384 // (count * 8)
            for sequence, frame in enumerate(selected):
                assert frame.header.version == 2
                assert frame.header.sequence == sequence
                assert frame.header.item_count == count
                assert frame.header.first_sample_ticks == sequence * count * 8
                if kind == 1:
                    assert len(frame.payload) == count * 4
                    values = struct.unpack(f"<{count * 2}H", frame.payload)
                    assert values == tuple(
                        (sequence * count * 2 + i) % 4096 for i in range(count * 2)
                    )
                else:
                    assert len(frame.payload) == 4048
                    values = struct.unpack(
                        f"<{count}{'H' if width == 16 else 'B'}", frame.payload
                    )
                    assert values == tuple(
                        (sequence * count + i) % (1 << width) for i in range(count)
                    )
