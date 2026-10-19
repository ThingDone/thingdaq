"""Public codec policies on existing packet pages, without experiment defines."""

import subprocess
from itertools import pairwise
from pathlib import Path

import pytest
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.protocol_v3 import V3FrameParser, decode_data_payload

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("experiments", [False, True])
def test_public_codecs(tmp_path, experiments):
    executable = tmp_path / "codecs"
    flags = (
        [
            "-DTHINGDAQ_EXPERIMENT_GPIO_RLE=1",
            "-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1",
            "-DTHINGDAQ_DEFERRED_CODECS=1",
            "-DTHINGDAQ_ADC_PACK12=1",
        ]
        if experiments
        else []
    )
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
            "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
            "-DTHINGDAQ_EXPERIMENT_CPU_HZ=600000000U",
            *flags,
            "-I" + str(ROOT / "firmware/src"),
            str(ROOT / "firmware/tests/v3_codec_pipeline_test.cpp"),
            *(
                str(ROOT / "firmware/src" / name)
                for name in (
                    "packet_buffer_pipeline.cpp",
                    "rle_encoder.cpp",
                    "usb_transport.cpp",
                    "statistics.cpp",
                    "protocol.cpp",
                    "checksum.cpp",
                )
            ),
            "-o",
            str(executable),
        ],
        check=True,
    )
    wire = tmp_path / "wire.bin"
    subprocess.run([str(executable), str(wire)], check=True)
    parser = V3FrameParser()
    frames = []
    data = wire.read_bytes()
    for offset in range(0, len(data), 7):
        frames.extend(parser.feed(data[offset : offset + 7]))
    assert parser.checksum_errors == 0 and parser.bytes_discarded == 0
    assert len(frames) == 128
    epoch = 0
    for width in (8, 16):
        for policies in range(4):
            for algorithm in (1,):
                for maximum in (False, True):
                    for pattern in range(4):
                        epoch += 1
                        pair = frames[(epoch - 1) * 2 : epoch * 2]
                        assert {f.header.kind for f in pair} == {
                            c.FrameKind.ADC_DATA,
                            c.FrameKind.GPIO_DATA,
                        }
                        for frame in pair:
                            h = frame.header
                            assert h.run_id == epoch and h.sequence == 0
                            assert h.first_sample_ticks == 0 and h.flags == 4
                            assert h.checksum_algorithm == algorithm
                            decoded = decode_data_payload(
                                h.kind, frame.payload, h.item_count
                            )
                            if h.kind == c.FrameKind.ADC_DATA:
                                count = 1009 if maximum else 12
                                values = [
                                    v
                                    for i in range(count)
                                    for v in (
                                        4095 if i % 2 else i % 4096,
                                        0 if i % 2 else i * 31 % 4096,
                                    )
                                ]
                                expected = b"".join(
                                    v.to_bytes(2, "little") for v in values
                                )
                                encoding = (
                                    c.Encoding.ADC_PACK12
                                    if policies & 2
                                    else c.Encoding.RAW
                                )
                                encoded_bytes = count * (3 if policies & 2 else 4)
                            else:
                                count = (
                                    (4036 if width == 8 else 2018) if maximum else 12
                                )
                                values = [
                                    (
                                        0
                                        if pattern == 0
                                        else i % 2
                                        if pattern == 1
                                        else i // (3 if width == 8 else 2)
                                        if pattern == 2
                                        else i // 8
                                    )
                                    % 256
                                    + (0xAB00 if width == 16 else 0)
                                    for i in range(count)
                                ]
                                expected = b"".join(
                                    v.to_bytes(width // 8, "little") for v in values
                                )
                                runs = 1 + sum(a != b for a, b in pairwise(values))
                                compressed = bool(policies & 1) and runs * (
                                    2 + width // 8
                                ) < len(expected)
                                encoding = (
                                    c.Encoding.GPIO_RLE
                                    if compressed
                                    else c.Encoding.RAW
                                )
                                encoded_bytes = (
                                    runs * (2 + width // 8)
                                    if compressed
                                    else len(expected)
                                )
                            assert h.item_count == count
                            assert (
                                decoded.payload == expected
                                and decoded.encoding == encoding
                            )
                            assert h.total_length == 60 + encoded_bytes <= 4096
