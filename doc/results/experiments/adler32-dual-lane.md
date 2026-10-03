---
type: result
title: Adler-32 Dual-Lane Experiment
created: 2026-10-02
tags:
  - checksum
  - adler32
  - experiment
related:
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[Checksum-Candidates]]'
  - '[[Phase-05-Checksum-Benchmark]]'
---

# Adler-32 dual-lane experiment

Branch: `experiment/adler32-dual-lane`, based on `302249a`.

**The experimental dual-lane implementation is substantially faster than the
current byte loop on Teensy, but it does not justify a distinct production wire
ID.** It produces the exact RFC 1950 Adler-32 value, so a normal Adler receiver
can validate it. ID 4 exists only to select and measure the implementation in
this experiment.

## Variant selection

ADR-001, ADR-002, and `doc/research/checksum-candidates.md` do not name an
Adler variant. They only define standard Adler-32 and leave additional scalar
unrolling as future work. This experiment therefore selected a two-lane exact
implementation: each bounded block is split into independent accumulator
chains and combined with the Adler concatenation identity. It is the strongest
portable candidate because it exposes instruction-level parallelism without a
table, alignment requirement, changed checksum value, or extra memory pass.

A four-byte weighted-sum implementation is included as the baseline
alternative. It also returns exact standard Adler-32 and is not assigned a wire
ID. The host result shows why it remains a credible simpler choice.

## Correctness

The firmware test compares byte-loop, four-byte unrolled, and dual-lane
implementations with an independent byte-at-a-time reference for 18 lengths,
two alignments, odd/even inputs, the 4,092-byte production coverage, the
5,552-byte reduction boundary, and multiple reduction blocks. Empty input and
`123456789` retain `0x00000001` and `0x091e01de`. The Python host maps
experimental ID 4 to `zlib.adler32`, so encoded and decoded wire frames are
checked by an independent C implementation.

## Host throughput

GCC 13.3.0 compiled separate firmware translation units with `-O3`. Seven
sequential repetitions each processed 200,000 exact 4,092-byte checksum
coverages after 2,048 warmups. The table reports medians; all implementations
published the same digest (`1670487040`).

| Implementation | Median ns/call | Median MB/s | Versus byte loop |
| --- | ---: | ---: | ---: |
| Current byte loop | 1,259.139 | 3,249.841 | baseline |
| Four-byte weighted/unrolled | 993.637 | 4,118.206 | 21.1% less time |
| Dual lane + concatenate | 1,038.235 | 3,941.306 | 17.5% less time |

The host favors the simpler four-byte unroll by 4.3% over dual lane. These are
native x86-64 implementation timings, not USB or end-to-end SDK throughput.

## Teensy Phase-05 measurement

Rig preflight was healthy and idle. Job
`67e1164c-0d9b-44b9-abb0-3af9e7f4e611` ran the established Phase-05 shape:
the production 4,092-byte header-plus-payload coverage, four batches of 256
operations, hot DTCM and cold-invalidated OCRAM. The target was Teensy 4.0
serial `20428100` at 450 MHz. No acquisition or electrical stimulus ran.

| Implementation | Memory/cache | cycles/B | MB/s | Projected CPU at 8.1 MB/s |
| --- | --- | ---: | ---: | ---: |
| Current byte loop | hot DTCM | 4.02467 | 111.810 | 7.244% |
| Dual lane | hot DTCM | 3.03055 | 148.488 | 5.455% |
| Current byte loop | cold OCRAM | 4.81317 | 93.493 | 8.664% |
| Dual lane | cold OCRAM | 3.78835 | 118.785 | 6.819% |

Dual lane reduced hot target time by 24.7% and cold target time by 21.3%.
Its linked body is 260 bytes versus 120 bytes for the current byte loop; both
use zero table bytes. The benchmark reported 28,664 stack bytes free and
confirmed `watchdog_enabled=false`, `watchdog_timeout_ms=0`.

## Recommendation

Do not standardize checksum ID 4: it is wire-equivalent to Adler-32 and would
create needless negotiation surface. Port the exact four-byte unrolled body
under existing ID 1 first, then repeat the same on-target benchmark; the host
favored it, while this experiment proves that dependency-breaking can recover
about 21–25% of target checksum time. Retain standard Adler-32 semantics and
the existing Phase-05 qualification policy.

Raw target replies, the immutable submitted program, and the matching build
manifest are under `doc/results/raw/adler32-dual-lane/phase05-target/`.
