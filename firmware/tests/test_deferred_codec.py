"""Deferred ownership, deadlines, optional codecs and independent wire roundtrip."""

import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "rle,adc", [(False, False), (True, False), (False, True), (True, True)]
)
def test_deferred_matrix(tmp_path, monkeypatch, rle, adc):
    binary = tmp_path / "test"
    flags = [
        "-DTHINGDAQ_DEFERRED_CODECS=1",
        "-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1",
        "-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1",
        "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
        "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
    ]
    if not rle:
        flags.append("-DTHINGDAQ_DISABLE_GPIO_RLE=1")
    if adc:
        flags.append("-DTHINGDAQ_ADC_PACK12=1")
    sources = [
        "packet_buffer_pipeline.cpp",
        "rle_encoder.cpp",
        "usb_transport.cpp",
        "statistics.cpp",
        "protocol.cpp",
        "checksum.cpp",
    ]
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wconversion",
            *flags,
            "-I" + str(ROOT / "firmware/src"),
            str(ROOT / "firmware/tests/deferred_codec_test.cpp"),
            *(str(ROOT / "firmware/src" / name) for name in sources),
            "-o",
            str(binary),
        ],
        check=True,
    )
    wire = tmp_path / "wire"
    subprocess.run([str(binary), str(wire)], check=True)
    # Existing standalone decoder imported with its explicit private selections.
    import test_gpio_rle

    monkeypatch.setenv("AUX_INPUT_ADC_PACK12", str(int(adc)))
    rig = test_gpio_rle.rig_module(monkeypatch)
    parser = rig.FrameParser()
    frames = []
    data = wire.read_bytes()
    for offset in range(0, len(data), 7):
        frames.extend(parser.feed(data[offset : offset + 7]))
    assert parser.errors == 0 and parser.bytes_discarded == 0
    assert len(frames) == 2
    for frame in frames:
        values = struct.unpack("<2024H", frame.payload)
        if frame.kind == rig.ADC_DATA:
            assert values == tuple(i * 31 % 4096 for i in range(2024))
            assert frame.adc_pack12 == adc
            assert frame.wire_bytes == (3084 if adc else 4096)
        else:
            assert values == tuple(i // 32 for i in range(2024))
            assert frame.gpio_rle == rle
    if adc:
        # Wrong private opt-in, count and truncated length must fail closed.
        for payload, count in ((b"\0" * 3035, 1012), (b"\0" * 3036, 1011)):
            with pytest.raises(rig.ProtocolFailure):
                rig.decode_adc12(payload, count)


def test_codec_manifest_selection_and_identity(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "firmware/tools"))
    import build_input_experiment as builder
    import run_input_isolation as runner

    identity = builder.base.BuildIdentity(
        "a" * 64, "thingdaq-aaaaaaaaaaaaaaaa", 1, "1970-01-01T00:00:01Z"
    )
    ids = set()
    for rle in (False, True):
        for adc in (False, True):
            ids.add(
                builder.experiment_identity(
                    identity,
                    600,
                    False,
                    release_fixed_1mhz=True,
                    large_adc_frame=True,
                    gpio_rle=True,
                    deferred_codecs=True,
                    disable_gpio_rle=not rle,
                    adc_pack12=adc,
                ).build_id
            )
            manifest = {
                "input_experiment": {
                    "gpio_rle": True,
                    "gpio_rle_wire_version": 130,
                    "large_adc_frame": True,
                    "release_fixed_1mhz": True,
                    "cpu_mhz": 600,
                    "deferred_codecs": True,
                    "encode_gpio_rle": rle,
                    "adc_pack12": adc,
                }
            }
            env = runner.gpio_rle_settings(manifest, enabled=True, host_api=False)
            assert env["AUX_INPUT_RLE_ENABLED"] == str(int(rle))
            assert env["AUX_INPUT_ADC_PACK12"] == str(int(adc))
    assert len(ids) == 4
    manifest["input_experiment"]["adc_pack12"] = "yes"
    with pytest.raises(ValueError, match="codec manifest"):
        runner.gpio_rle_settings(manifest, enabled=True, host_api=False)


def test_adc_decode_boundary_and_random_values(monkeypatch):
    import random

    import test_gpio_rle

    rig = test_gpio_rle.rig_module(monkeypatch)
    rng = random.Random(20261018)
    for _ in range(20):
        values = [0, 4095, 4095, 0, *[rng.randrange(4096) for _ in range(2020)]]
        packed = b"".join(
            (a | (b << 12)).to_bytes(3, "little")
            for a, b in zip(values[::2], values[1::2])
        )
        assert rig.decode_adc12(packed, 1012) == struct.pack("<2024H", *values)
