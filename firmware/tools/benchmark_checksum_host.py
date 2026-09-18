#!/usr/bin/env python3
"""A/B the actual v2 incremental parser with and without data checksum work.

Offline only: zero trailers and a temporary backend replacement are scoped to
this process. Structural validation and parser accounting are unchanged.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from thingdone_daq import protocol_v2 as protocol
from thingdone_daq._generated import protocol_v2_constants as c

ROOT = Path(__file__).resolve().parents[2]


def corpus(width: int) -> tuple[bytes, ...]:
    # Current release: 1012/506 ADC pairs/frame for 8/16 GPIO inputs;
    # one GPIO frame spans four ADC frames in either mode.
    pairs = 1012 if width == 8 else 506
    adc_payload = bytes((i % 256 if i % 2 == 0 else i % 16) for i in range(pairs * 4))
    return tuple(
        protocol.encode_v2_frame(
            c.FrameKind.ADC_DATA,
            adc_payload,
            run_id=1,
            sequence=sequence,
            item_count=pairs,
            flags=c.FrameFlag.EPOCH_START if sequence == 0 else c.FrameFlag.NONE,
            first_sample_ticks=sequence * pairs * 8,
        )
        for sequence in range(4)
    )


def benchmark(*, repeats: int = 9, groups: int = 2000) -> dict:
    rows = []
    original = protocol.compute_v2_checksum

    # This callable replaces the complete checksum dispatch, matching removal
    # of the computation (the four-byte trailer remains for identical framing).
    def disabled(data, algorithm):
        return 0

    for width in (8, 16):
        frames = corpus(width) + (
            protocol.encode_v2_frame(
                c.FrameKind.GPIO_DATA,
                bytes(4048),
                run_id=1,
                item_count=4048 * 8 // width,
                flags=c.FrameFlag.EPOCH_START,
            ),
        )
        normal = b"".join(frames)
        unchecked = b"".join(frame[:-4] + bytes(4) for frame in frames)
        inputs = {"baseline": normal, "none": unchecked}
        payload_bytes = sum(len(frame) - 48 for frame in frames)
        for repeat in range(repeats):
            # Alternate order to reduce warmup / frequency / scheduling bias.
            for mode in (
                ("baseline", "none") if repeat % 2 == 0 else ("none", "baseline")
            ):
                with patch.object(
                    protocol,
                    "compute_v2_checksum",
                    original if mode == "baseline" else disabled,
                ):
                    parser = protocol.IncrementalCompatibleFrameParser()
                    for _ in range(32):
                        assert len(parser.feed(inputs[mode])) == 5
                    started = time.perf_counter_ns()
                    cpu_started = time.process_time_ns()
                    count = 0
                    for _ in range(groups):
                        count += len(parser.feed(inputs[mode]))
                    cpu = (time.process_time_ns() - cpu_started) / 1e9
                    wall = (time.perf_counter_ns() - started) / 1e9
                    assert count == 5 * groups
                    assert parser.counters.checksum_errors == 0
                    rows.append(
                        {
                            "mode": mode,
                            "gpio_width": width,
                            "repeat": repeat,
                            "frames": count,
                            "groups": groups,
                            "seconds": wall,
                            "cpu_seconds": cpu,
                            "payload_mb_s": payload_bytes * groups / wall / 1e6,
                            "payload_mb_cpu_s": payload_bytes * groups / cpu / 1e6,
                            "parser_counters": dataclasses.asdict(parser.counters),
                        }
                    )
    summaries = []
    for width in (8, 16):
        selected = [row for row in rows if row["gpio_width"] == width]
        medians = {
            mode: statistics.median(
                row["payload_mb_s"] for row in selected if row["mode"] == mode
            )
            for mode in ("baseline", "none")
        }
        summaries.append(
            {
                "gpio_width": width,
                "median_payload_mb_s": medians,
                "speedup_percent": (medians["none"] / medians["baseline"] - 1) * 100,
            }
        )
    return {
        "schema": "checksum-host-experiment-v1",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "scope": "in-memory v2 incremental parsing; excludes serial reader, block conversion and application",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rows": rows,
        "summary": summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--groups", type=int, default=2000)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 31 or not 1 <= args.groups <= 10000:
        parser.error("repeats must be 1..31 and groups 1..10000")
    result = benchmark(repeats=args.repeats, groups=args.groups)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
