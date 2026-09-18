---
type: result
title: Checksum Simplification Experiment
created: 2026-09-18
tags:
  - checksum
  - performance
  - experiment
related:
  - '[[Protocol-V2]]'
  - '[[Firmware-Runtime-Hardening]]'
---

# Checksum simplification experiment

Branch: `experiment/checksum-performance`, based on `370ae2a`.

**There is measurable CPU headroom to recover, but no demonstrated increase
in live acquisition throughput.** Removing checksum computation improved the
local v2 parser's median throughput by **20.5–24.1%**. An exact, four-byte
Adler-32 loop reduced native-host firmware checksum time by **26.7–28.2%**
without changing the checksum. Cortex-M7 performance remains unmeasured because
the baseline disconnected and subsequent firmware uploads failed.

Retain Adler-32 for production. The unrolled implementation is the promising
candidate for the next hardware comparison; checksum removal loses corruption
detection and did not establish a live-stream benefit in this experiment.
Production builds and public SDK behavior remain unchanged. No acquisition
clock or supported sample rate was increased.

## Variants

| Mode | Firmware | Host | Compatibility |
| --- | --- | --- | --- |
| `baseline` | Existing Adler-32 | Existing validation | Unchanged |
| `unrolled` | Four-byte weighted sums; same 5552-byte reduction bound | Existing validation | Exact Adler-32, unchanged wire format |
| `none` | Skip data-frame checksum scan, emit zero trailer | Experiment-only adapter expects zero | Deliberately incompatible research format |

The `none` variant retains the four-byte trailer and existing algorithm ID to
isolate computation cost. It is **not** a new supported algorithm or protocol.
An ordinary host rejects its data. It still checks control messages, lengths,
headers, sequence gaps and loss counters; payload/header corruption can pass
undetected. A regression test demonstrates that lost protection explicitly.
The build manifest records mode, compatibility and distinct source/build IDs;
the hardware runner requires an explicit `--checksum-experiment` flag and a
matching manifest. No normal SDK path exposes a checksum-disable setting.

## Local measurements

Host: x86_64 Linux, CPython 3.12.3, GCC 13.3.0. Nine repetitions per cell;
order alternates for Python and rotates for C++. Final measurements were run
sequentially after the test suite, without concurrent experiment compilation.
Raw repetitions and identities are retained in
[checksum-host.json](checksum-host.json) and
[checksum-firmware-host.json](checksum-firmware-host.json).

The Python workload uses the actual compatible incremental parser, including
header/payload validation and buffer accounting, with the release's four ADC
frames per GPIO frame. Each sample parses 2000 groups after 32 warmup groups.
Eight-input mode uses 1012 ADC pairs/frame and 4048 GPIO samples/frame;
sixteen-input mode uses 506 pairs/frame and 2024 GPIO samples/frame.

| Combined workload | Adler-32 payload MB/s | No checksum payload MB/s | Throughput improvement |
| --- | ---: | ---: | ---: |
| ADC + 8 GPIO | 309.53 | 384.01 | 24.06% |
| ADC + 16 GPIO | 209.92 | 253.01 | 20.53% |

These are **in-memory parser capacities**, excluding serial I/O, reader threads,
block conversion, application work and firmware. They are not actual USB rates.
The production host already uses C-backed `zlib.adler32`; a pure Python sum or
XOR would not be a sensible replacement for that accelerated implementation.

The C++ benchmark calls the real firmware `computeChecksum` path, compiled
with `-O2` and separate translation units. It mutates an input byte and exposes
every result to prevent removal/hoisting. Each cell runs 20,000 calls after
64 warmups; baseline/unrolled digests must agree. Coverage includes the
44-byte header and excludes the trailer.

| Coverage | Baseline ns/call | Unrolled ns/call | No scan ns/call | Unrolled time reduction |
| --- | ---: | ---: | ---: | ---: |
| 2068 bytes | 511.67 | 375.21 | 2.43 | 26.67% |
| 4092 bytes | 959.44 | 689.25 | 2.20 | 28.16% |

These timings are **native x86_64**, not Teensy cycles. The no-scan cost measures
only dispatch/loop overhead; its equivalent byte rate is not memory bandwidth.
The pinned Teensy compiler emits a 236-byte unrolled Adler body versus 120 bytes
for baseline. Exact symbol-size and linked-memory checks remain enforced.

## Hardware attempts and limits

All attempts used the existing remote service and Teensy 4.0 serial `20428100`,
450 MHz core and release profile 4. The service initially reported healthy and
idle. No external input stimulus was declared. Complete submitted identities,
result summaries and stdout/stderr are in
[checksum-rig-attempts.json](checksum-rig-attempts.json); local full artifacts
remain under `doc/results/raw/checksum-performance/`.

| Attempt | Job | Outcome |
| --- | --- | --- |
| Baseline SDK, checksum microbenchmark first | `99abfee2-172f-405b-8fdf-09af05f061d1` | Device disconnected before a benchmark result |
| Baseline SDK, streaming first | `a8a92b76-b501-4dd6-8e09-a5bee4551087` | ADC-only capture disconnected after 1.056 s; no completed cell |
| Unrolled, independent combined validator | `1549882a-1535-444a-be21-3fa4506d85d4` | Firmware programming failed, service error `-110`; capture never ran |
| No checksum, independent combined validator | `a14132d7-3e53-480d-9fba-5acab3346cc1` | Firmware programming failed, service error `-110`; capture never ran |

The baseline streaming failure recorded 1028 decoded frames, zero checksum,
header or payload errors, zero resynchronizations, and zero host block drops.
The remote SDK container reported a half-core quota (`50000 100000`). These
observations do not establish the disconnect's cause. The baseline included
the current runtime-hardening commit, whose existing report explicitly says
it had not yet been hardware-qualified. No unrelated watchdog/USB change was
made to get this experiment to pass.

There is no valid on-device checksum timing, paired live-throughput result,
lossless no-checksum run, or new maximum sample-rate claim. The last confirmed
successful flash was the baseline (checksums enabled); the two modified
variants were not confirmed flashed. Resolve the device/loader availability
and baseline stability before resuming the A/B campaign.

## Validation

The final focused checksum/protocol/runner suite passed 33 tests and 391 subtests,
including three new experiment tests covering independent C++ Adler references,
firmware control/data separation and host corruption-detection boundaries.
The Adler check also covers all-255 inputs at reduction boundaries and 1 MiB.
All three variants passed the pinned Teensy build and memory gates; final build
identities, HEX hashes and memory usage are in [checksum-builds.json](checksum-builds.json).
The final baseline rebuild has a different source fingerprint from the attempted
baseline because the conditional unrolled code-size declaration was added;
its default checksum behavior is identical. Ruff,
formatting, generated protocol checks (111 outputs) and diff checks passed.

The broad run passed 588 tests and 16,336 subtests but had five reported failures:
four timing assertions and the pre-existing untracked
`doc/results/firmware-analysis-2026-09-12.md` missing required front matter.
The six throughput/streaming tests (including the failed timing cases) then
passed in isolation with two subtests. Documentation validation passed four
tests and 57 subtests on a staged export so that unrelated user file remains
untouched and uncommitted.
This evidence is not a claim that the initial broad run passed.

## Reproduction

```bash
.venv/bin/python firmware/tools/benchmark_checksum_host.py \
  --output doc/results/scratch/checksum-host.json
.venv/bin/python firmware/tools/benchmark_checksum_firmware_host.py \
  --output doc/results/scratch/checksum-firmware-host.json
TMPDIR="$PWD/firmware/build/tmp" .venv/bin/python -m pytest \
  firmware/tests/test_checksum_experiment.py -q

# Repeat separately for baseline, unrolled and none.
TMPDIR="$PWD/firmware/build/tmp" \
ARDUINO_BUILD_CACHE_PATH="$PWD/firmware/build/cache" \
.venv/bin/python firmware/tools/build_checksum_experiment.py --mode unrolled

# Requires an idle, healthy service and working device/programmer.
.venv/bin/python firmware/tools/run_input_isolation.py \
  --worktree "$PWD" --build-dir firmware/build/checksum-unrolled \
  --evidence-dir doc/results/raw/checksum-performance/unrolled-retry \
  --case INPUT_COMBINED --profile 4 --seconds 60 \
  --checksum-experiment --service http://192.168.150.14:5000
```

Add `--host-api` for the five-cell public SDK sequence and on-device checksum
microbenchmarks (the capture duration is divided among five cells). Repeat and
alternate variants once the baseline is stable; retain CPU time, control
latency, queue pressure and loss results alongside throughput. Fixed-rate
acquisition can show lower CPU cost without a higher delivered sample rate.
