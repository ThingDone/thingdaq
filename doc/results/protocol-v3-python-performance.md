---
type: report
title: Python v3 decoding and streaming performance
created: 2026-10-19
tags:
  - protocol-v3
  - python
  - performance
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-python-inspection]]'
  - '[[deferred-codecs-20261018]]'
---

# Python v3 decoding and streaming performance

The standard-library parser/block path now has reproducible RAW, PACK12,
compressible GPIO RLE, and worst-case RAW fallback measurements in
`daq_api/tests/test_streaming_correctness_performance.py`. No production decoder
or legacy performance threshold changed. These measurements are informational;
normal tests enforce exact payload/count accounting and fixed memory bounds.

## Reproduction

From the repository root, with the existing development environment:

```bash
.venv/bin/python -m pytest -q -s daq_api/tests/test_streaming_correctness_performance.py
```

For only the new coverage, append `-k V3Codec`. Output contains two JSON records:
`PHASE02_V3_BENCHMARK` (timing, host information, rates and relative costs) and
`PHASE02_V3_MEMORY` (count accounting, parser high water and memory). The retained
[machine-readable evidence](protocol-v3-python-performance.json) includes all
measurements, the command, and a SHA-256 of the measured test source.

The same coverage can run without importing NumPy, using only the standard
library test runner:

```bash
PYTHONPATH=daq_api/src:daq_api/tests .venv/bin/python - <<'PY'
import importlib.abc
import sys
import unittest

class NoNumpy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'numpy':
            raise AssertionError('benchmark must not import NumPy')

sys.meta_path.insert(0, NoNumpy())
unittest.main(
    module='test_streaming_correctness_performance',
    argv=['benchmark', 'V3CodecPerformanceTests'],
)
PY
```

## Workload and measurement boundaries

Ten profiles cover ADC RAW/PACK12 and GPIO8/GPIO16 RAW/RLE_AUTO with either
64-sample runs or transitions every sample. Every compressed/fallback profile
has a RAW baseline containing exactly the same logical samples. Alternating
GPIO forces RLE_AUTO to emit byte-identical RAW frames. ADC values reuse the
existing synthetic generators. Expected decoded payloads are independently
constructed from scalar values using `struct.pack`/`int.to_bytes`.

Each capture has 64 maximum-size logical frames (4,048 decoded bytes each),
followed by a 17-item short frame. ADC items are **pairs**, GPIO items are packed
samples across the selected 8 or 16 pins. Reported samples/second therefore
means ADC pairs/second or GPIO packed samples/second, not summed channel values.

The existing seeded chunk-range helper uses seed `0xDA03B001`, with 1,024-byte
and 16,384-byte maximum chunks. Each timed batch replays a capture eight times
(520 frames); three batches rotate profile order and report individual wall/CPU
times and median cost relative to the matching RAW profile at that chunk size.
Relative cost is elapsed time divided by baseline elapsed time; greater than
one means slower. Rates use logical items, so compressed bytes cannot inflate
reported sample throughput.

Fixture encoding and chunk generation precede timing. Each profile warms up
once. Timed consumption uses `IncrementalCompatibleFrameParser(include_v3=True)`
and `decode_v3_block`, as the reader does, including their current validation
work. It also compares decoded bytes, sequence, timestamps and actual encoding,
reconciles counters, and retains eight blocks in a bounded deque. It is not an
isolated codec microbenchmark. NumPy is neither imported nor needed.

Memory is measured in a separate warmed pass, using eight replays and seeded
chunks of at most 4,093 bytes. Input captures, expected payloads and chunk tables
are allocated before tracing. Deterministic assertions enforce:

- Exact 520-frame, logical-item, wire-byte and decoded-byte totals per profile;
  zero parser corruption, discards or trailing bytes.
- Parser high water within the production parser bound.
- Eight retained blocks and at most 64,864 bytes of their decoded plus encoded
  payload storage, independent of replay duration.
- Traced transient allocation below 2 MiB and retained allocation after return
  and garbage collection below 128 KiB, using generous fixed ceilings.

The payload bound counts both representations conservatively. It excludes
Python object overhead; the traced peak includes that overhead and transient
decoder/parser allocations. Tracemalloc measures Python allocations, not RSS.

## Recorded results

CPython 3.12.3, Linux 6.17.0-35-generic, x86-64. The table uses median timing at
16,384-byte maximum chunks. Byte totals cover eight replays; deque payload peak
and traced peak come from the separate memory pass described above.

| Profile | Million logical items/s | Wire bytes | Decoded bytes | Deque payload peak bytes | Traced peak bytes | RAW-relative wall cost |
|---|---:|---:|---:|---:|---:|---:|
| adc-raw | 15.84 | 2,104,320 | 2,073,120 | 64,864 | 115,052 | 1.00 |
| adc-pack12 | 11.37 | 1,586,040 | 2,073,120 | 56,768 | 109,452 | 1.39 |
| gpio8-runs-raw | 78.99 | 2,103,912 | 2,072,712 | 64,864 | 110,590 | 1.00 |
| gpio8-runs-rle-auto | 36.16 | 129,528 | 2,072,712 | 34,016 | 79,266 | 2.18 |
| gpio8-alternating-raw | 78.59 | 2,103,912 | 2,072,712 | 64,864 | 110,590 | 1.00 |
| gpio8-alternating-rle-auto | 78.89 | 2,103,912 | 2,072,712 | 64,864 | 110,590 | 1.00 |
| gpio16-runs-raw | 39.44 | 2,104,048 | 2,072,848 | 64,864 | 110,590 | 1.00 |
| gpio16-runs-rle-auto | 22.42 | 97,792 | 2,072,848 | 33,520 | 80,179 | 1.76 |
| gpio16-alternating-raw | 39.25 | 2,104,048 | 2,072,848 | 64,864 | 110,582 | 1.00 |
| gpio16-alternating-rle-auto | 39.29 | 2,104,048 | 2,072,848 | 64,864 | 110,582 | 1.00 |

Compression reduces wire traffic while increasing decode cost in these samples.
PACK12 saves exactly one transmitted byte per ADC pair. RAW fallback has the
same wire and decoded byte totals as its baseline; small timing differences are
measurement noise. The JSON retains the shorter-chunk results and CPU times too.

## Limits

This is offline parser/block consumption with bounded retention. It excludes
USB, firmware encoding cost, background-reader scheduling, negotiation, STOP
drain, and application processing beyond these checks. Replays restart the same
captured epoch; this benchmark does not test lifecycle or loss semantics. GPIO
cases are measured separately from ADC; no timestamp alignment is claimed.
Short host timings are sensitive to scheduling and machine load. No new v3
wall-clock gate or hardware throughput claim is made. The existing legacy
1.25× headroom gate remains unchanged and passed in the recorded run.

Validation: full `daq_api/tests` suite passed (1,255 tests, 15,873 subtests);
focused streaming suite passed (7 tests, 12 subtests); the fresh NumPy-blocked
process passed both new tests. Generator drift (142 files), Ruff lint/format
(104 files), mypy (33 source files), documentation/layout checks (8 tests,
1,102 subtests), evidence source hash/rate checks and whitespace checks passed.
