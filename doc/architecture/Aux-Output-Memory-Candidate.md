---
type: analysis
title: Auxiliary Output Memory Repartition Candidate
created: 2026-09-04
tags:
  - thingdaq
  - digital-output
  - firmware
  - memory
  - dma
related:
  - '[[ADR-008-Experimental-Aux-Output-Bank]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Acquisition-Pipeline]]'
  - '[[1-MHz-Parallel-Output-Idea]]'
---

# Auxiliary output memory repartition candidate

This note fixes the linker-accounted candidate for the portable output
prototype described by [[ADR-008-Experimental-Aux-Output-Bank]]. It is an
allocation proof, not an active target allocation: the Teensy sketch does not
instantiate the program store, DMA state blocks, descriptors, or output
adapter in this phase, and D16-D23 remain unowned inputs.

## Current accepted map evidence

`firmware/tests/fixtures/combined_acquisition.map` is the frozen map consumed
by the same parser as `firmware/tools/build_firmware.py`. The focused portable
engine test asserts these exact values rather than relying on prose:

| Current item | Region | Bytes | Packet pages |
| --- | --- | ---: | ---: |
| Packet primary bank | DTCM/RAM1 | 430,080 | 105 |
| Packet reserve bank | OCRAM/RAM2 | 389,120 | 95 |
| All packet payload storage | split | 819,200 | 200 |
| RAM1 variables | DTCM/RAM1 | 456,992 | — |
| RAM1 code | DTCM/RAM1 | 32,744 | — |
| RAM1 padding | DTCM/RAM1 | 24 | — |
| RAM1 remaining for locals/stack | DTCM/RAM1 | 34,528 | — |
| RAM2 variables | OCRAM/RAM2 | 520,192 | — |
| RAM2 remaining for heap | OCRAM/RAM2 | 4,096 | — |

The 4,096-byte RAM2 remainder cannot hold a useful four-block output ring.
The candidate therefore exchanges existing packet pages rather than adding a
new unrelated OCRAM reservation.

## Exact six-page exchange

| Candidate item | Region | Bytes | Derivation |
| --- | --- | ---: | --- |
| Canonical segment payload | DTCM/RAM1 | 8,192 | 1,024 segments × 8 bytes; replaces 2 primary packet pages |
| Packet primary bank | DTCM/RAM1 | 421,888 | 103 × 4,096-byte pages |
| Output DMA allocation | OCRAM/RAM2 | 16,384 | replaces 4 reserve packet pages |
| Four eDMA TCDs | OCRAM/RAM2 | 128 | 4 × 32-byte descriptors inside the output allocation |
| Toggle-state payload | OCRAM/RAM2 | 16,256 | 16,384 − 128 bytes |
| Toggle-state block | OCRAM/RAM2 | 4,064 | 1,016 `u32` states per block |
| Packet reserve bank | OCRAM/RAM2 | 372,736 | 91 × 4,096-byte pages |

The compile-time equations in `firmware/src/board_config.h` prove:

$$
(103 \times 4096) + 8192 = 105 \times 4096 = 430080
$$

$$
(91 \times 4096) + 16384 = 95 \times 4096 = 389120
$$

Thus the candidate preserves the current aggregate packet-payload reservation
in both memory regions. It leaves 194 packet pages and 98,164 microseconds of
nominal combined framed retention, compared with 200 pages and 101,200
microseconds today. The 98.164 ms candidate still exceeds the historical
60.715 ms service gap, but that comparison is not throughput acceptance: new
DMA traffic, cache flushes, expansion work, and target metadata can change the
measured margin.

## What remains linker-accounted

`ProgramStorage` is exactly 8,192 bytes and `DmaBlockStorage` is exactly 16,256
bytes by host-compiled `static_assert`. Program metadata, four ownership
records, playback telemetry, the future four TCDs, the target adapter, and code
growth still require an actual target linker map. A later target phase must
apply the 103/91 packet counts, place the program and output allocation in the
declared regions, verify non-overlap and alignment, and retain at least 32 KiB
of RAM1 locals/stack headroom before any physical-output claim is permitted.

See [[Firmware-Resource-Map]] for current owners and
[[Acquisition-Pipeline]] for the existing trigger-first STOP boundary.
