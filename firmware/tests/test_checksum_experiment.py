"""Correctness and deliberate incompatibility boundaries for checksum research."""

from __future__ import annotations

import importlib.util
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest
from thingdone_daq import protocol_v2 as protocol
from thingdone_daq._generated import protocol_v2_constants as c

ROOT = Path(__file__).resolve().parents[2]


def adapter():
    spec = importlib.util.spec_from_file_location(
        "checksum_experiment_adapter",
        ROOT / "firmware/tests/checksum_experiment_adapter.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unrolled_adler_matches_independent_references():
    with tempfile.TemporaryDirectory() as directory:
        executable = Path(directory) / "checksum"
        subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DTHINGDAQ_EXPERIMENT_ADLER_UNROLL=1",
                f"-I{ROOT / 'firmware/src'}",
                str(ROOT / "firmware/tests/checksum_correctness_test.cpp"),
                str(ROOT / "firmware/src/checksum.cpp"),
                "-o",
                str(executable),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run([str(executable)], check=True, capture_output=True)
        # Worst-case sums at the reduction boundary and across repeated blocks.
        corpus = [
            bytes([255]) * size
            for size in (3, 4, 5, 5551, 5552, 5553, 11103, 11104, 11105, 1048576)
        ]
        input_path = Path(directory) / "corpus.bin"
        output_path = Path(directory) / "checksums.bin"
        input_path.write_bytes(
            struct.pack("<I", len(corpus))
            + b"".join(struct.pack("<I", len(data)) + data for data in corpus)
        )
        subprocess.run(
            [str(executable), str(input_path), str(output_path)],
            check=True,
            capture_output=True,
        )
        checksums = output_path.read_bytes()
        for index, data in enumerate(corpus):
            assert struct.unpack_from("<I", checksums, index * 12)[0] == zlib.adler32(
                data
            )


def test_none_keeps_controls_and_exposes_lost_corruption_detection():
    original = protocol.compute_v2_checksum
    unchecked = adapter()._experiment_data_checksum(original)
    fixture = (ROOT / "protocol/fixtures-v2/gpio-data.bin").read_bytes()
    control = (ROOT / "protocol/fixtures-v2/ping-request.bin").read_bytes()
    no_checksum = fixture[:-4] + bytes(4)
    with pytest.raises(protocol.V2ChecksumMismatchError):
        protocol.decode_v2_frame(no_checksum)
    assert unchecked(control[:-4], c.ChecksumAlgorithm.ADLER32) == original(
        control[:-4], c.ChecksumAlgorithm.ADLER32
    )
    with patch.object(protocol, "compute_v2_checksum", unchecked):
        assert protocol.decode_v2_frame(control).to_bytes() == control
        assert protocol.decode_v2_frame(no_checksum).checksum == 0
        damaged = bytearray(no_checksum)
        damaged[c.HEADER_SIZE + 3] ^= 0x40
        # Deliberately document the lost protection; this must never be release
        # acceptance evidence simply because a no-checksum stream had no gaps.
        assert (
            protocol.decode_v2_frame(damaged).payload
            != protocol.decode_v2_frame(no_checksum).payload
        )
        parser = protocol.IncrementalCompatibleFrameParser()
        assert len(parser.feed(no_checksum + control)) == 2
        assert parser.counters.checksum_errors == 0
    assert protocol.compute_v2_checksum is original


def test_firmware_none_keeps_control_checksum(tmp_path):
    source = tmp_path / "boundary.cpp"
    source.write_text("""
#include <array>
#include "protocol.h"
#include "checksum.h"
int main() {
  std::array<std::uint8_t, 64> data{};
  std::uint32_t result = 123;
  for (auto kind : {1, 2, 16, 128}) {
    data[5] = static_cast<std::uint8_t>(kind);
    auto status = thingdaq::protocol::computeChecksum(
      thingdaq::protocol_v1::ChecksumAlgorithm::kAdler32,
      {data.data(), data.size()}, result);
    if (!status.ok()) return 1;
    const auto expected = kind <= 2 ? 0U :
      thingdaq::checksum::adler32(data.data(), data.size());
    if (result != expected) return 2;
  }
  auto status = thingdaq::protocol::computeChecksum(
    thingdaq::protocol_v1::ChecksumAlgorithm::kNoneReserved,
    {data.data(), data.size()}, result);
  return status.ok() ? 3 : 0;
}
""")
    executable = tmp_path / "boundary"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DTHINGDAQ_EXPERIMENT_NO_DATA_CHECKSUM=1",
            f"-I{ROOT / 'firmware/src'}",
            str(source),
            str(ROOT / "firmware/src/protocol.cpp"),
            str(ROOT / "firmware/src/checksum.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True)
