#!/usr/bin/env python3
"""Compile and compare firmware checksum dispatch on this host (not Teensy)."""

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLAGS = {
    "baseline": [],
    "unrolled": ["-DTHINGDAQ_EXPERIMENT_ADLER_UNROLL=1"],
    "none": ["-DTHINGDAQ_EXPERIMENT_NO_DATA_CHECKSUM=1"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    scratch = ROOT / "firmware/build/tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    inputs = [
        ROOT / "firmware/tests/checksum_performance_benchmark.cpp",
        ROOT / "firmware/src/protocol.cpp",
        ROOT / "firmware/src/checksum.cpp",
    ]
    with tempfile.TemporaryDirectory(dir=scratch) as temporary:
        for mode, flags in FLAGS.items():
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{ROOT / 'firmware/src'}",
                    *flags,
                    *map(str, inputs),
                    "-o",
                    str(Path(temporary) / mode),
                ],
                check=True,
            )
        for repeat in range(9):
            modes = list(FLAGS)
            modes = modes[repeat % 3 :] + modes[: repeat % 3]
            for mode in modes:
                output = subprocess.check_output(
                    [str(Path(temporary) / mode)], text=True
                )
                for line in output.splitlines():
                    row = json.loads(line)
                    row.update(mode=mode, repeat=repeat)
                    row["mb_s"] = (
                        row["coverage_bytes"] * row["iterations"] / row["seconds"] / 1e6
                    )
                    row["ns_per_call"] = row["seconds"] * 1e9 / row["iterations"]
                    rows.append(row)
    for size in (2068, 4092):
        digests = {
            row["digest"]
            for row in rows
            if row["coverage_bytes"] == size and row["mode"] != "none"
        }
        assert len(digests) == 1, "optimized checksum changed results"
    summary = [
        {
            "mode": mode,
            "coverage_bytes": size,
            "median_ns_per_call": statistics.median(
                row["ns_per_call"]
                for row in rows
                if row["mode"] == mode and row["coverage_bytes"] == size
            ),
        }
        for mode in FLAGS
        for size in (2068, 4092)
    ]
    result = {
        "schema": "checksum-firmware-host-experiment-v1",
        "scope": "native host; not Cortex-M7 or USB throughput",
        "none_mode_note": "No payload bytes are read in none mode; mb_s is only equivalent coverage, not memory bandwidth.",
        "platform": platform.platform(),
        "compiler": subprocess.check_output(
            ["g++", "--version"], text=True
        ).splitlines()[0],
        "optimization": "-O2, separate translation units, no LTO",
        "inputs_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs
        },
        "rows": rows,
        "summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
