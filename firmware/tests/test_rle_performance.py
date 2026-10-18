"""Independent canonical output, ownership, fallback and evidence validation."""

import ctypes
import importlib.util
import random
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "rle_collector", Path(__file__).with_name("rig_rle_benchmark.py")
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


@pytest.fixture(scope="module")
def kernel(tmp_path_factory):
    directory = tmp_path_factory.mktemp("rle-kernel")
    source = directory / "candidate.cpp"
    source.write_text(
        '#define RLE_SINGLE_ATTRIBUTES __attribute__((optimize("O3")))\n#include "single_pass.h"\n'
    )
    library = directory / "candidate.so"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            "-fPIC",
            "-I",
            str(ROOT / "firmware/experiments/rle_performance"),
            str(source),
            "-o",
            str(library),
        ],
        check=True,
    )

    class Result(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_uint32), ("error", ctypes.c_uint32)]

    function = ctypes.CDLL(str(library)).single_pass
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    function.restype = Result
    return function


def check_kernel(kernel, source, offset):
    reference = collector.encode_reference(source)
    initial = b"\xa5" * offset + source + b"\xa5" * (4112 - len(source) - offset)
    incoming = ctypes.create_string_buffer(initial, len(initial))
    outgoing = ctypes.create_string_buffer(b"\xa5" * 4112, 4112)
    result = kernel(ctypes.byref(incoming, offset), ctypes.byref(outgoing, offset))
    assert result.error == 0 and result.bytes == len(reference)
    assert incoming.raw == initial
    assert outgoing.raw[:offset] == b"\xa5" * offset
    if reference:
        assert outgoing.raw[offset : offset + result.bytes] == reference
    limit = offset + (len(reference) if reference else 4044)
    assert outgoing.raw[limit:] == b"\xa5" * (4112 - limit)


@pytest.mark.parametrize("pattern", collector.PATTERNS)
@pytest.mark.parametrize("offset", [0, 1, 2, 3])
def test_known_patterns_and_unaligned_buffers(kernel, pattern, offset):
    check_kernel(kernel, collector.corpus(pattern), offset)


def test_seeded_run_distributions(kernel):
    rng = random.Random(24680)
    for case in range(240):
        values = []
        while len(values) < 2024:
            run = rng.randint(1, (1, 2, 3, 4, 32, 512)[case % 6])
            values.extend([rng.randrange(65536)] * run)
        import struct

        check_kernel(kernel, struct.pack("<2024H", *values[:2024]), case % 4)


def transcript():
    rows = [
        "cpu_hz=600000000,opt=O2,warm_cache=1,interrupts_enabled=1,trials=31,acquisition=0",
        "variant,pattern,region," + ",".join(collector.FIELDS),
    ]
    for variant in collector.VARIANTS:
        for pattern in collector.PATTERNS:
            oracle = collector.expected(pattern)
            for region in ("dtcm", "ocram"):
                fields = [
                    2024,
                    100,
                    110,
                    120,
                    *(oracle[k] for k in collector.FIELDS[4:]),
                ]
                rows.append(",".join([variant, pattern, region, *map(str, fields)]))
    return rows + ["done"]


def test_complete_transcript():
    assert len(collector.parse_transcript(transcript(), "O2")) == 224
    assert collector.expected("constant")["encoded_bytes"] == 4
    assert collector.expected("runs2")["encoded_bytes"] == 0


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "clock", "digest", "input", "size", "cycles", "done"],
)
def test_bad_evidence_rejected(mutation):
    lines = transcript()
    if mutation == "missing":
        lines.pop(2)
    elif mutation == "duplicate":
        lines[3] = lines[2]
    elif mutation == "clock":
        lines[0] = lines[0].replace("600000000", "450000000")
    elif mutation == "done":
        lines[-1] = "ERROR"
    else:
        parts = lines[2].split(",")
        field = {"digest": 8, "input": 9, "size": 7, "cycles": 5}[mutation]
        parts[field] = "0"
        lines[2] = ",".join(parts)
    with pytest.raises(ValueError):
        collector.parse_transcript(lines, "O2")


def test_frozen_upload_composes_collectors(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "firmware/tools"))
    import run_m7_benchmark as runner

    monkeypatch.setitem(__import__("sys").modules, "rig_m7_benchmark", None)
    namespace = {"__name__": "input_isolation_rig"}
    exec(compile(runner.benchmark_source("rle"), "upload", "exec"), namespace)  # noqa: S102 - execute our frozen upload in a test
    assert len(namespace["parse_transcript"](transcript(), "O2")) == 224
    collector_module = __import__("sys").modules["rig_m7_benchmark"]
    seen = {}

    def stub(**kwargs):
        seen.update(kwargs)
        return 42

    monkeypatch.setattr(collector_module, "main", stub)
    assert namespace["main"]() == 42
    assert seen["validator"] == "rle-dwt" and seen["pass_timeout"] == 60
