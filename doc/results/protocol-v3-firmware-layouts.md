---
type: report
title: Public v3 run layouts, USB guards and codec status
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - transport
  - portable-validation
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-firmware-codecs]]'
  - '[[protocol-v3-firmware-transactions]]'
---

# Public v3 layouts and transport

Completes the fifth Phase 03 task. Public v3 START now connects the selected
settings to acquisition, packet encoding and USB. No hardware was accessed or
flashed. No task images were supplied or analyzed.

## Selected layout and memory

| Stream | Logical items/frame | Decoded bytes | RAW wire bytes | Coverage at 8 MHz |
| --- | ---: | ---: | ---: | ---: |
| ADC | 1008 pairs | 4032 | 4092 | 8064 ticks |
| GPIO8 | 4032 samples | 4032 | 4092 | 32256 ticks |
| GPIO16 | 2016 samples | 4032 | 4092 | 16128 ticks |

The larger ADC block class is reused for both GPIO widths, with four fewer pairs
than the private 1012-pair layout so the v3 prefix fits existing packet pages.
The decoded payload is cache-line aligned. PACK12 ADC frames occupy 3084 bytes;
GPIO RLE lengths remain data-dependent. The maximum packet storage remains
200 pages of 4096 bytes, with the existing primary/reserve split. No frame
storage was added and no required memory threshold was relaxed.

ADC capture already accepts a per-run pair count. GPIO16 now carries a per-epoch
count through its existing paired ring, descriptor/readback, timestamps,
completion checks, leases and STOP accounting. GPIO8 retains existing raw DMA
blocks and reframes them through its existing packed ring. ADC auxiliary-priority
selection is explicit for v3 instead of inferred from an old short ADC count.
Legacy v2 retains exact 1012/506 ADC pairs and 4048/2024 GPIO samples, including
when private codec flags are enabled.

## Transport and public metadata

Packet ownership and USB share an O(1) v3 envelope/prefix guard. It checks the
actual wire length, logical count, decoded size, width, permitted encoding,
reserved fields, flags and timestamps. It does not repeat a payload checksum on
each USB short write: packet pages are checksummed before publication and remain
immutable while held by USB. RAW, PACK12 and profitable RLE use the same guard.

Fair scheduling now compares logical time coverage for v3. Equal packet counts
would stall the shorter ADC frames behind GPIO. Byte counters distinguish
logical decoded payload bytes from accumulated actual wire bytes. Retention
uses logical counts and periods, never compressed bytes.

The generated public GET_STATUS payload grows from 80 to 256 bytes. Its first
80 bytes and the separate 16-byte STOP payload retain their meanings. Both the
C++ serializer and Python `V3Status` expose per-stream codec completions, RAW
fallbacks, deadline/resource drops, work ticks, maximum work/age ticks, completed
wire-byte totals, selected item counts, RAW frame ceilings and retention bounds.
Retention is an upper bound assuming all shared pages belong to that stream;
it is not simultaneous retention guaranteed for both streams. Codec counts and
maxima saturate at u32, accumulated work at u64. RAW-policy runs bypass codec work.
Legacy private diagnostic pages remain available without changing v1/v2 bytes.
The revised pre-release v3 schema requires regenerated v3 consumers/fixtures.

START preserves exact settings/clock echoes, resets the run epoch and can use
boot defaults or retained settings. STOP preserves settings and final counters;
a bounded raw-tail drain runs before its response snapshots pending frames.
Busy drain and repeated STOP/restart are covered. Legacy INFO/STATUS probes during
a running v3 session return a typed unsupported-configuration error without
mutating the session, since their schemas cannot represent the active layout.
V3 probes remain available; legacy discovery while stopped remains unchanged.

## Validation

- Full firmware/Python regression: **1766 passed, 5 expected skips, 16,773
  subtests**, in 232.78 seconds. Three skips are the existing equal-rate override
  exclusions; two exclude unadvertised 450 MHz compression.
- Focused v3 control/layout/ring checks: 100 passed, 2 expected RAW-only 450 MHz
  exclusions, 12 subtests. Existing legacy-session, ADC and GPIO8 packer checks
  also passed during integration.
- Tests exercise 3-byte command reads, 7-byte USB writes, public Python decoding
  in 5-byte chunks, repeated epochs, busy configuration during a partial tail,
  exact wire totals, logical coverage/fairness, retention, malformed prefixes,
  per-epoch raw ring counts, forged leases and exact incomplete STOP samples.
- Full linked builds at 450 MHz and 600 MHz pass existing stack/heap, packet
  storage, managed-memory, linker-map and checksum placement gates. Both leave
  33,024 bytes for locals/stack and 4,096 bytes for heap. Discovery tables now
  reside in program flash; runtime construction and synthetic start reside in
  existing flash code sections. The 600 MHz build uses an isolated verification
  override, not a published release artifact.
- Documentation/build-configuration checks: 23 passed, 1043 subtests.
- Generator: all 142 outputs current. Ruff format/check: 195 files pass.
  Mypy: all 33 source files pass. Whitespace checks pass.

Logs, temporary binaries, target objects and the isolated 600 MHz build are
ignored artifacts under `.maestro/playbooks/Working/layout-*` and
`phase03-layout-*`. The normal 450 MHz build output is under `firmware/build/`.

These are portable and linked-image results. They do not establish physical
capture accuracy, runtime clock switching, sustained USB throughput or loss
qualification. The following playbook tasks retain their broader protocol and
cross-language test scope.
