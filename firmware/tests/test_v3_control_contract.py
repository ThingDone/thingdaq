"""Public control bytes through the production C++ parser and dispatcher."""

from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import (
    V3AppliedSettings,
    V3Capabilities,
    V3Info,
    V3Response,
    V3Status,
    V3Stop,
    decode_v3_response,
)
from thingdone_daq.protocol_v3 import V3FrameParser

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "firmware/src"


def command(kind: int, payload: bytes = b"", request_id: int = 1) -> bytes:
    header = struct.pack(
        "<IBBHHBBIIIIIQI",
        0xDEADBEEF,
        3,
        kind,
        0,
        44,
        1,
        0,
        48 + len(payload),
        len(payload),
        0,
        0,
        request_id,
        0,
        0,
    )
    wire = header + payload
    return wire + struct.pack("<I", zlib.adler32(wire))


def patch(wire: bytes, offset: int, value: bytes) -> bytes:
    data = bytearray(wire)
    data[offset : offset + len(value)] = value
    data[-4:] = struct.pack("<I", zlib.adler32(data[:-4]))
    return bytes(data)


@pytest.fixture(scope="module", params=[600000000, 450000000])
def executable(request, tmp_path_factory) -> Path:
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ required")
    output = tmp_path_factory.mktemp("v3-control") / "control"
    result = subprocess.run(
        check=False,
        args=[
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wconversion",
            "-Wsign-conversion",
            "-pedantic",
            "-fno-exceptions",
            "-fno-rtti",
            "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
            f"-DTHINGDAQ_EXPERIMENT_CPU_HZ={request.param}U",
            f"-I{SOURCE}",
            str(ROOT / "firmware/tests/v3_control_contract_test.cpp"),
            *(
                str(SOURCE / name)
                for name in (
                    "control_state.cpp",
                    "statistics.cpp",
                    "protocol.cpp",
                    "checksum.cpp",
                )
            ),
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return output


def exchange(executable: Path, wire: bytes, mode: str = "fixed") -> list[V3Response]:
    result = subprocess.run(
        check=False, args=[str(executable), mode], input=wire, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    parser = V3FrameParser()
    frames = []
    for at in range(0, len(result.stdout), 7):
        frames.extend(parser.feed(result.stdout[at : at + 7]))
    return [decode_v3_response(frame) for frame in frames]


def test_discovery_and_settings_echo(executable: Path) -> None:
    responses = exchange(
        executable,
        b"".join(
            command(k, request_id=i + 1) for i, k in enumerate((16, 28, 29, 19, 20))
        ),
    )
    assert len(responses) == 5
    info, caps, applied, status, stop = [r.value for r in responses]
    assert isinstance(info, V3Info)
    assert isinstance(caps, V3Capabilities)
    assert isinstance(applied, V3AppliedSettings)
    assert isinstance(status, V3Status)
    assert isinstance(stop, V3Stop)
    assert info.hardware_serial == "12345678"
    assert not info.simulated
    assert len(caps.cpu_profiles) == 1
    compressed = info.clocks.cpu_profile == c.CpuProfile.CPU_600MHZ
    assert len(caps.configurations) == (48 if compressed else 12)
    assert caps.max_control_frame_bytes == 1536
    assert caps.max_data_frame_bytes == 4096
    assert caps.defaults.gpio_policy == (
        c.GpioPolicy.RLE_AUTO if compressed else c.GpioPolicy.RAW
    )
    assert caps.defaults.adc_policy == (
        c.AdcPolicy.PACK12 if compressed else c.AdcPolicy.RAW
    )
    assert caps.defaults == applied.settings
    assert info.clocks == applied.clocks
    for settings in caps.configurations:
        assert settings.cpu_profile == info.clocks.cpu_profile
        if not compressed:
            assert settings.gpio_policy == c.GpioPolicy.RAW
            assert settings.adc_policy == c.AdcPolicy.RAW
    for settings in caps.configurations:
        responses = exchange(
            executable, command(17, settings.to_bytes()) + command(29, request_id=2)
        )
        assert (
            responses[0].value
            == responses[1].value
            == V3AppliedSettings(settings, info.clocks)
        )


def test_fake_adapter_does_not_change_production_advertisement(
    executable: Path,
) -> None:
    caps = exchange(executable, command(28), "fake")[0].value
    assert isinstance(caps, V3Capabilities)
    assert len(caps.configurations) == 60
    assert len(caps.cpu_profiles) == 2
    for settings in caps.configurations:
        responses = exchange(
            executable,
            command(17, settings.to_bytes()) + command(29, request_id=2),
            "fake",
        )
        assert responses[0].value == responses[1].value
        assert responses[0].value.settings == settings
    assert len(exchange(executable, command(28))[0].value.cpu_profiles) == 1


@pytest.mark.parametrize("mode", ["fail", "mismatch"])
def test_application_failure_does_not_publish_candidate(
    executable: Path, mode: str
) -> None:
    candidate = c.SELECTABLE_CONFIGURATIONS[-1]
    replies = exchange(
        executable,
        command(29) + command(17, candidate, 2) + command(29, request_id=3),
        mode,
    )
    assert replies[1].error_code == c.ErrorCode.INTERNAL_ERROR
    assert replies[0].value == replies[2].value


@pytest.mark.parametrize("mode", ["running", "draining"])
def test_queries_remain_available_without_sampling_or_reset(
    executable: Path, mode: str
) -> None:
    replies = exchange(
        executable,
        b"".join(command(k, request_id=i + 1) for i, k in enumerate((16, 28, 29, 19))),
        mode,
    )
    assert all(r.error_code == c.ErrorCode.OK for r in replies)
    state = replies[-1].value
    assert isinstance(state, V3Status)
    assert state.state == (
        c.DeviceState.RUNNING if mode == "running" else c.DeviceState.DRAINING
    )
    rejected = exchange(executable, command(17, c.DEFAULT_SETTINGS[0]), mode)[0]
    assert rejected.error_code == (
        c.ErrorCode.INVALID_STATE if mode == "running" else c.ErrorCode.BUSY
    )


@pytest.mark.parametrize(
    "offset,value",
    [
        (0, 0),
        (0, 4),
        (1, 2),
        (2, 2),
        (3, 2),
        (4, 3),
        (5, 1),
        (6, 2),
        (7, 9),
        (8, 2),
        (9, 2),
        (10, 16),
        (11, 1),
    ],
)
def test_settings_enum_and_reserved_validation(
    executable: Path, offset: int, value: int
) -> None:
    wire = patch(command(17, c.DEFAULT_SETTINGS[0]), 44 + offset, bytes([value]))
    replies = exchange(executable, wire, "fake")
    assert len(replies) == 1
    assert replies[0].error_code == c.ErrorCode.INVALID_PAYLOAD


@pytest.mark.parametrize(
    "offset,value",
    [(6, b"\x01"), (12, struct.pack("<I", 2000000)), (16, struct.pack("<I", 1234567))],
)
def test_contradictory_tuple_rejected(
    executable: Path, offset: int, value: bytes
) -> None:
    wire = patch(command(17, c.DEFAULT_SETTINGS[0]), 44 + offset, value)
    assert (
        exchange(executable, wire, "fake")[0].error_code
        == c.ErrorCode.UNSUPPORTED_CONFIGURATION
    )


@pytest.mark.parametrize("kind", [0, 15, *range(21, 28), 30, 255])
def test_reserved_command_ids_have_generic_errors(executable: Path, kind: int) -> None:
    response = exchange(executable, command(kind))[0]
    assert response.kind == c.FrameKind.ERROR_RESPONSE
    assert response.error_code == c.ErrorCode.UNKNOWN_FRAME_KIND
    assert response.rejected_kind == kind


@pytest.mark.parametrize(
    "offset,value,error",
    [
        (6, b"\x01", c.ErrorCode.INVALID_FLAGS),
        (11, b"\x01", c.ErrorCode.INVALID_PAYLOAD),
        (20, b"\x01", c.ErrorCode.INVALID_PAYLOAD),
        (24, b"\x01", c.ErrorCode.INVALID_PAYLOAD),
        (28, bytes(4), c.ErrorCode.INVALID_REQUEST_ID),
        (32, b"\x01", c.ErrorCode.INVALID_PAYLOAD),
        (40, b"\x01", c.ErrorCode.INVALID_PAYLOAD),
        (10, b"\x02", c.ErrorCode.UNSUPPORTED_CHECKSUM),
    ],
)
def test_header_validation(executable: Path, offset: int, value: bytes, error) -> None:
    reply = exchange(executable, patch(command(16), offset, value))[0]
    assert reply.error_code == error


def test_lengths_corruption_resync_and_duplicate(executable: Path) -> None:
    for kind, payload in ((16, b"\0"), (17, bytes(19)), (17, b"")):
        assert (
            exchange(executable, command(kind, payload))[0].error_code
            == c.ErrorCode.INVALID_LENGTH
        )
    bad = bytearray(command(17, c.DEFAULT_SETTINGS[0]))
    bad[-1] ^= 1
    for wire in (
        bytes(bad),
        command(16)[:-1],
        patch(command(16), 12, struct.pack("<I", 0xFFFFFFFF)),
    ):
        assert not exchange(executable, wire)
    replies = exchange(executable, bytes(bad) + command(16, request_id=99))
    assert len(replies) == 1 and replies[0].request_id == 99
    replies = exchange(executable, command(28) + command(28))
    assert replies[1].error_code == c.ErrorCode.INVALID_REQUEST_ID
    assert exchange(executable, command(18))[0].error_code == c.ErrorCode.OK


def test_generated_control_frames_and_reserved_response_bytes(executable: Path) -> None:
    for path in sorted((ROOT / "protocol/fixtures-v3").glob("*.bin")):
        wire = path.read_bytes()
        if wire[5] in (1, 2):
            continue
        result = subprocess.run(
            check=False,
            args=[str(executable), "validate"],
            input=wire,
            capture_output=True,
        )
        assert result.returncode == 0, path.name
    caps = (ROOT / "protocol/fixtures-v3/get_capabilities-response.bin").read_bytes()
    # Reserved fields in prefix, table count, settings, clocks, rates, unused tuple.
    for offset in (1, 7, 47, 57, 58, 105, 106, 122, 124 + 60 * 20):
        result = subprocess.run(
            check=False,
            args=[str(executable), "validate"],
            input=patch(caps, 44 + offset, b"\x01"),
        )
        assert result.returncode == int(c.ErrorCode.INVALID_PAYLOAD), offset


def test_rejected_requests_keep_run_identity(executable: Path) -> None:
    for wire in (command(17, bytes(20)), patch(command(16), 11, b"\x01")):
        response = exchange(executable, wire, "running")[0]
        assert response.run_id == 1
        assert response.error_code == c.ErrorCode.INVALID_PAYLOAD
    response = exchange(executable, command(255, request_id=0))[0]
    assert response.request_id == 0
    assert response.error_code == c.ErrorCode.INVALID_REQUEST_ID


def test_start_serializer_matches_golden_without_starting_acquisition(
    executable: Path,
) -> None:
    result = subprocess.run(
        [str(executable), "serialize-start"], capture_output=True, check=True
    )
    assert (
        result.stdout == (ROOT / "protocol/fixtures-v3/start-response.bin").read_bytes()
    )


def test_transactions_rollback_modes_and_replay(executable: Path) -> None:
    subprocess.run([str(executable), "transactions"], check=True, capture_output=True)


def test_repeated_v2_v3_sessions(executable: Path) -> None:
    result = subprocess.run(
        [str(executable), "sessions"], check=False, capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()
