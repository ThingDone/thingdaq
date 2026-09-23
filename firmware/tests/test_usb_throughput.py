"""Verify actual diagnostic firmware bytes with the independent host checker."""

import importlib.util
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "usb_rig", ROOT / "firmware/tests/rig_usb_throughput.py"
)
rig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rig)


def test_firmware_commands_frames_pacing_partial_writes_and_disconnect(tmp_path):
    executable = tmp_path / "usb-test"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DTHINGDAQ_EXPERIMENT_USB_THROUGHPUT=1",
            "-DARDUINO_TEENSY40=1",
            "-D__IMXRT1062__=1",
            f"-I{ROOT / 'firmware/tests/fixtures/usb-throughput'}",
            f"-I{ROOT / 'firmware/tests/fakes/teensy40'}",
            f"-I{ROOT / 'firmware/src'}",
            str(ROOT / "firmware/tests/usb_throughput_test.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(executable), str(tmp_path)], check=True, capture_output=True)
    for mode in rig.MODES:
        data = (tmp_path / f"mode-{mode}.bin").read_bytes()
        ack = rig.HEADER.unpack(data[:32])
        assert ack[0] == b"TDACK001" and ack[2] == mode
        checker = rig.Checker(ack[1], mode)
        offset = 32
        while offset < len(data):
            size = struct.unpack_from("<I", data, offset + 16)[0]
            checker.accept(data[offset : offset + size])
            offset += size
        assert checker.done and checker.sequence == 6
        assert (
            checker.done["short_writes"] > 0
            if mode == 4
            else checker.done["short_writes"] == 0
        )


def test_host_rejects_corruption_and_sequence_gaps():
    frame = bytearray(
        rig.HEADER.pack(b"TDATA001", 1, 0, 4096, 2, 0, 4064) + rig.PATTERNS[4096]
    )
    rig.Checker(1, 1).accept(frame)
    frame[-1] ^= 1
    with pytest.raises(ValueError, match="corruption"):
        rig.Checker(1, 1).accept(frame)
    frame[-1] ^= 1
    struct.pack_into("<I", frame, 12, 1)
    with pytest.raises(ValueError, match="sequence"):
        rig.Checker(1, 1).accept(frame)
