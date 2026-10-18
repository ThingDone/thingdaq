"""Cross-language GPIO-only RLE, selected bytes, corruption and ownership gates."""

import importlib.util
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def rig_module(monkeypatch, enabled=True):
    monkeypatch.setenv("AUX_INPUT_LARGE_ADC_FRAME", "1")
    monkeypatch.setenv("AUX_INPUT_GPIO_RLE", str(int(enabled)))
    spec = importlib.util.spec_from_file_location(
        "gpio_rle_rig", ROOT / "firmware/tests/rig_aux_input_capture.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wire_bundle(tmp_path_factory):
    directory = tmp_path_factory.mktemp("gpio-rle")
    executable = directory / "oracle"
    command = [
        "g++",
        "-std=c++17",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wconversion",
        "-Wsign-conversion",
        "-DTHINGDAQ_TESTING=1",
        "-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1",
        "-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1",
        "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
        "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
        f"-I{ROOT / 'firmware/src'}",
        str(ROOT / "firmware/tests/gpio_rle_test.cpp"),
    ]
    command += [
        str(ROOT / "firmware/src" / name)
        for name in (
            "packet_buffer_pipeline.cpp",
            "rle_encoder.cpp",
            "usb_transport.cpp",
            "statistics.cpp",
            "protocol.cpp",
            "checksum.cpp",
        )
    ]
    result = subprocess.run(
        [*command, "-o", str(executable)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = directory / "wire.bin"
    status = directory / "status.bin"
    result = subprocess.run(
        [str(executable), str(output), str(status)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output.read_bytes(), status.read_bytes()


def test_real_firmware_mixed_frames_decode_exactly(monkeypatch, wire):
    rig = rig_module(monkeypatch)
    parser = rig.FrameParser()
    frames = []
    for offset in range(0, len(wire), 7):
        frames.extend(parser.feed(wire[offset : offset + 7]))
    assert parser.errors == parser.bytes_discarded == 0
    assert len(frames) == 4
    validator = rig.AcquisitionValidator(
        1,
        rig.CHECKSUM_ADLER32,
        rig.RUN_CASES["INPUT_GPIO"],
        rig.PROFILE_BY_VALUE[4],
        None,
    )
    for kind, frame in enumerate(frames):
        random = 42
        expected = []
        for i in range(2024):
            random = (random * 1664525 + 1013904223) & 0xFFFFFFFF
            expected.append(
                (
                    0xABCD
                    if kind == 0
                    else i // 40
                    if kind == 1
                    else i % 2
                    if kind == 2
                    else random >> 8
                )
                & 0xFFFF
            )
        assert frame.payload == struct.pack("<2024H", *expected)
        assert frame.gpio_rle == (kind < 2)
        validator.accept(frame)
    assert validator.gpio.framed_bytes == len(wire)
    assert validator.gpio.payload_bytes == 4 * 4048
    assert validator.gpio_rle_frames == validator.gpio_raw_frames == 2
    assert validator.gpio.expected_ticks == 4 * 16192


def test_ordinary_validator_rejects_private_version(monkeypatch, wire):
    rig = rig_module(monkeypatch, False)
    parser = rig.FrameParser()
    assert parser.feed(wire[:52]) == []
    assert parser.header_errors > 0


@pytest.mark.parametrize(
    "payload",
    [
        struct.pack("<HH", 0, 1),
        struct.pack("<HH", 2025, 1),
        struct.pack("<HH", 2023, 1),
        b"123",
        b"",
        struct.pack("<HHHH", 1024, 1, 1000, 1),
        struct.pack("<HHHH", 2024, 1, 1, 2),
    ],
)
def test_bad_runs_rejected(monkeypatch, payload):
    rig = rig_module(monkeypatch)
    with pytest.raises(rig.ProtocolFailure):
        rig.decode_gpio_rle(payload, 2024)


def test_corruption_count_and_version_rejected_before_acceptance(monkeypatch, wire):
    rig = rig_module(monkeypatch)
    for index, rechecksum in (
        (44, False),
        (44, True),
        (40, True),
        (5, True),
        (11, True),
    ):
        broken = bytearray(wire[:52])
        broken[index] ^= 1
        if rechecksum:
            struct.pack_into("<I", broken, 48, zlib.adler32(broken[:48]))
        parser = rig.FrameParser()
        assert parser.feed(bytes(broken)) == []
        assert parser.errors > 0


def test_rle_build_identity_and_manifest_opt_in(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "firmware/tools"))
    import build_input_experiment as build
    import run_input_isolation as run

    identity = build.base.BuildIdentity(
        "a" * 64, "thingdaq-aaaaaaaaaaaaaaaa", 1, "1970-01-01T00:00:01Z"
    )
    assert build.experiment_identity(
        identity, 600, False, release_fixed_1mhz=True, large_adc_frame=True
    ) != build.experiment_identity(
        identity,
        600,
        False,
        release_fixed_1mhz=True,
        large_adc_frame=True,
        gpio_rle=True,
    )
    manifest = {
        "input_experiment": {
            "cpu_mhz": 600,
            "release_fixed_1mhz": True,
            "large_adc_frame": True,
            "gpio_rle": True,
            "gpio_rle_wire_version": 130,
        }
    }
    assert run.gpio_rle_settings(manifest, enabled=True, host_api=False) == {
        "AUX_INPUT_GPIO_RLE": "1"
    }
    for enabled, host_api in ((False, False), (True, True)):
        with pytest.raises(ValueError):
            run.gpio_rle_settings(manifest, enabled=enabled, host_api=host_api)


def test_start_burst_uses_selected_wire_size_and_bounds_decoded_memory(
    monkeypatch, wire
):
    rig = rig_module(monkeypatch)
    short = rig.FrameParser().feed(wire[:52])[0]
    buffer = rig.StartFrameBuffer()
    # A normal 64 KiB read can exceed the old 17-frame larger-ADC limit.
    for _ in range(40):
        buffer.append(short)
    assert buffer.wire_bytes == 40 * 52
    assert len(buffer.frames) == 40
    assert buffer.frame_limit * 4048 < 5 * 1024 * 1024
    for _ in range(buffer.frame_limit - 40):
        buffer.append(short)
    with pytest.raises(rig.ProtocolFailure, match="bounded deferral"):
        buffer.append(short)
    # The larger frame-count allowance must not allow unbounded RAW buffering.
    raw = next(frame for frame in rig.FrameParser().feed(wire) if not frame.gpio_rle)
    buffer = rig.StartFrameBuffer()
    for _ in range((rig.SERIAL_READ_BYTES + rig.MAX_FRAME_BYTES) // raw.wire_bytes):
        buffer.append(raw)
    with pytest.raises(rig.ProtocolFailure, match="bounded deferral"):
        buffer.append(raw)


def test_ordinary_start_frame_count_bound_is_unchanged(monkeypatch):
    rig = rig_module(monkeypatch, False)
    assert rig.StartFrameBuffer().frame_limit == 17


@pytest.fixture(scope="module")
def wire(wire_bundle):
    return wire_bundle[0]


def test_private_fault_status_roundtrip_and_reset(monkeypatch, wire_bundle):
    rig = rig_module(monkeypatch)
    parser = rig.FrameParser()
    frames = [
        frame
        for offset in range(0, len(wire_bundle[1]), 4096)
        for frame in parser.feed(wire_bundle[1][offset : offset + 4096])
    ]
    assert len(frames) == 147 and parser.errors == parser.bytes_discarded == 0
    statuses = [rig.decode_status(frame).values for frame in frames]
    for index in (*range(49), *range(98, 147)):
        assert all(
            statuses[index]["adc_fault_" + name] == 0 for name in rig.DMA_FAULT_FIELDS
        )
    assert statuses[49]["adc_fault_reason"] == 1
    for name, expected in zip(rig.DMA_FAULT_FIELDS, (1, 2, 3, 4, 17, 34)):
        assert statuses[49]["adc_fault_" + name] == expected
    for page in range(1, 49):
        values = statuses[49 + page]
        assert values["adc_fault_reason"] == 1
        assert values["adc_fault_page"] == page
        assert values["adc_fault_word0"] == (2 * page - 1) * 23
        assert values["adc_fault_word1"] == 2 * page * 23
    assert "adc_fault_reason" in rig.ZERO_ERROR_FIELDS
    ordinary = rig_module(monkeypatch, False)
    parser = ordinary.FrameParser()
    for offset in range(0, len(wire_bundle[1]), 4096):
        assert parser.feed(wire_bundle[1][offset : offset + 4096]) == []
    assert parser.header_errors > 0
