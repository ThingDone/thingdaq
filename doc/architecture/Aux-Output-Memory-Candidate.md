---
type: analysis
title: Auxiliary Output Memory Repartition
created: 2026-09-04
updated: 2026-09-04
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

# Auxiliary output memory repartition

This note records the active linker-accounted allocation for the output path
described by [[ADR-008-Experimental-Aux-Output-Bank]]. The Teensy image now
reserves the program store, DMA state blocks, and descriptors and binds them
to the ARM-only GPIO1/eDMA adapter. Constructing the facade or uploading and
committing a program remains register-free; D16-D23 stay inputs until ARM.

## Accepted pre-repartition map evidence

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

## Linked six-page exchange

| Linked item | Region and address | Bytes | Derivation |
| --- | --- | ---: | --- |
| Packet primary bank | DTCM/RAM1 `0x20001ac0` | 421,888 | 103 × 4,096-byte pages |
| Canonical segment payload | DTCM/RAM1 `0x20068ac0` | 8,192 | 1,024 segments × 8 bytes; replaces 2 primary packet pages |
| Four eDMA TCDs | OCRAM/RAM2 `0x20200000` | 128 | 4 × 32-byte descriptors |
| Toggle-state payload | OCRAM/RAM2 `0x20200080` | 16,256 | 4 × 4,064-byte blocks |
| Toggle-state block | OCRAM/RAM2 | 4,064 | 1,016 `u32` states per block |
| Packet reserve bank | OCRAM/RAM2 `0x20204000` | 372,736 | 91 × 4,096-byte pages |

The compile-time equations in `firmware/src/board_config.h` prove:

$$
(103 \times 4096) + 8192 = 105 \times 4096 = 430080
$$

$$
(91 \times 4096) + 16384 = 95 \times 4096 = 389120
$$

Thus the repartition preserves the previous aggregate packet-payload reservation
in both memory regions. It leaves 194 packet pages and 98,164 microseconds of
nominal combined framed retention, compared with 200 pages and 101,200
microseconds today. The 98.164 ms candidate still exceeds the historical
60.715 ms service gap, but that comparison is not throughput acceptance: new
DMA traffic, cache flushes, expansion work, and target metadata can change the
measured margin.

## Build bounds and remaining work

The pinned 600 MHz adapter build reports 457,632 RAM1 variable bytes and 33,888
bytes for locals/stack, plus 520,192 RAM2 variable bytes and the required 4,096-byte
heap floor. Manifest schema 11 records every address, size, alignment, region,
packet count, retention interval, IRQ identity, arbitration priority, and the
successful all-allocation non-overlap check. The 194 packets retain 98.164 ms;
the core TX ring raises that to 99.176 ms, leaving respective 37.449 ms and
38.461 ms margins over the historical 60.715 ms service gap.

The target now flushes complete source blocks and their 32-byte TCDs before
publishing DMA ownership, services at most one refill block per visit, and
joins the existing ADC/GPIO controller before its final common PIT arm. STOP
and target faults stop the common trigger before channel 3, observe the live
TCD and GPIO1 latch, and retain the physical hold; CLEAR alone returns the bank
to GPIO6 inputs. Protocol telemetry, fixture interlocks, loopback grading, and
physical timing remain later work, so this build makes no pad-timing or
signal-integrity claim.

See [[Firmware-Resource-Map]] for current owners and
[[Acquisition-Pipeline]] for the existing trigger-first STOP boundary.
