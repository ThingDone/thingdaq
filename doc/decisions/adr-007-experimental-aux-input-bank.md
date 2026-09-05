---
type: analysis
title: 'ADR 007: Experimental Auxiliary Input Bank'
created: 2026-09-02
updated: 2026-09-04
tags:
  - thingdaq
  - decision
  - protocol
  - gpio
  - dma
  - variable-rate
  - experiment
related:
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Hardware-Safety]]'
  - '[[Experiment-Baseline]]'
  - '[[Protocol-V1]]'
---

# ADR 007: Experimental auxiliary input bank

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

## Status

Accepted for the isolated `experiment/aux-input-bank` prototype. This decision
defines an opt-in protocol-v2 experiment. It does not change the production
protocol-v1 contract, its D6-D13 default, any v1 generated constant or golden
fixture, or the target implementation accepted by
[[ADR-003-GPIO-Clock-DMA]].

The D16-D23 mapping and target resources are now implemented by the target
adapter and exposed through protocol-v2 metadata. Host and simulator evidence
still cannot establish external transition capture, pad order, electrical
compatibility, signal integrity, or sustainable USB throughput. The 3.3 V-only
requirements and non-driving test boundary in [[Hardware-Safety]] remain in
force.

## Context

[[Protocol-V1]] publishes one packed byte per GPIO sample: D6-D13 occupy bits
0-7 at 4 MHz. ADC0 and ADC1 form one four-byte pair at 1 MHz. Both streams use
4,048-byte payloads, so 4,048 GPIO samples and 1,012 ADC pairs each cover 8,096
ticks in the common 8 MHz timestamp domain.

The proposed experiment adds D16-D23 as a second synchronous input bank and
also tests exact reduced-rate schedules. The frozen [[Experiment-Baseline]]
already owns PIT0/PIT1, both ADC_ETC routes, eDMA channels 0-2, the GPIO2 raw
ring, packet storage, and the lifecycle described by
[[Acquisition-Pipeline]]. A safe extension must preserve the established
primary bit positions, retain the one-bank path as the default, avoid pin APIs
in the sampling loop, and describe every new owner before target register code
is written. [[Firmware-Resource-Map]] remains authoritative for resources that
have actually been implemented and measured.

The same D16-D23 pads are proposed for a separate output experiment. Input and
output ownership are mutually exclusive across branches; this branch never
drives them.

## Decision

The canonical experimental source is `protocol/protocol-v2.json`. It is a
complete versioned contract pinned to the SHA-256 of
`protocol/protocol-v1.json`, with disjoint generated constant and fixture
paths. Protocol v1 remains authoritative for ordinary clients and firmware.

### Negotiation and whole-bank safety

The generated `AuxBankMode` has exactly two values:

| Value | Mode | Meaning |
| ---: | --- | --- |
| `0` | `DISABLED` | Retain the established D6-D13 one-byte path. |
| `1` | `INPUT` | Configure every D16-D23 pad as an input and join both banks. |

There is no per-pin direction bitmap. Values used to represent mixed
directions or output are invalid rather than future-compatible aliases. An
`INPUT` transition configures all pads as inputs before selectively returning
their mask from fast GPIO6 to DMA-visible GPIO1. STOP, fault, and rollback
restore a safe input state. OUTPUT is unsupported on this branch.

The experimental contract assigns `AUXILIARY_INPUT_BANK` capability bit
`0x00000200` and `EXACT_RATE_PROFILES` bit `0x00000400`. The ordinary default
(`DISABLED`, 1 MHz ADC pairs, 4 MHz GPIO) continues to use v1. An explicit
`INPUT` request or any reduced profile enters v2 negotiation and requires a
stable v2 INFO response advertising the required capabilities and exact
metadata before CONFIGURE.

The v2 CONFIGURE request is 16 bytes. It preserves stream, source, checksum,
and maximum-frame fields, uses former reserved byte 3 for `aux_bank_mode`, and
adds exact little-endian `u32 adc_pair_rate_hz` and
`u32 gpio_sample_rate_hz` fields at offsets 8 and 12. The 20-byte CONFIGURE and
START response body echoes the exact applied mode and rates. A changed or
contradictory echo rejects START; the host never silently selects a nearest
rate or different bank mode.

### Pin and wire order

The 16-bit GPIO item is an unsigned little-endian value. Existing primary-bank
positions never move:

| Wire bit | Teensy pin | DMA-visible source |
| ---: | ---: | --- |
| 0 | D6 | GPIO2 bit 10 |
| 1 | D7 | GPIO2 bit 17 |
| 2 | D8 | GPIO2 bit 16 |
| 3 | D9 | GPIO2 bit 11 |
| 4 | D10 | GPIO2 bit 0 |
| 5 | D11 | GPIO2 bit 2 |
| 6 | D12 | GPIO2 bit 1 |
| 7 | D13 | GPIO2 bit 3 |
| 8 | D16 | GPIO1 bit 23 |
| 9 | D17 | GPIO1 bit 22 |
| 10 | D18 | GPIO1 bit 17 |
| 11 | D19 | GPIO1 bit 16 |
| 12 | D20 | GPIO1 bit 26 |
| 13 | D21 | GPIO1 bit 27 |
| 14 | D22 | GPIO1 bit 24 |
| 15 | D23 | GPIO1 bit 25 |

The auxiliary GPIO1/GPIO6 aggregate mask is `0x0FC30000`, selected through
`IOMUXC_GPR_GPR26`. Only that mask may be changed. The primary GPIO2/GPIO7 mask
remains `0x00030C0F` through GPR27. A joined value is formed from matched raw
sample instants as `primary | (auxiliary << 8)` and serialized least
significant byte first.

### Exact rate profiles

Only these `(ADC pair rate, GPIO rate)` pairs are valid:

| Profile | ADC pairs/s | GPIO samples/s | ADC period ticks | ADC1 phase ticks | GPIO period ticks | PIT0 divide/load | ADC1 phase IPG cycles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ADC_1MHZ_GPIO_4MHZ` | 1,000,000 | 4,000,000 | 8 | 4 | 2 | 6 / 5 | 75 |
| `ADC_500KHZ_GPIO_2MHZ` | 500,000 | 2,000,000 | 16 | 8 | 4 | 12 / 11 | 150 |
| `ADC_250KHZ_GPIO_1MHZ` | 250,000 | 1,000,000 | 32 | 16 | 8 | 24 / 23 | 300 |
| `ADC_125KHZ_GPIO_500KHZ` | 125,000 | 500,000 | 64 | 32 | 16 | 48 / 47 | 600 |

GPIO is exactly four times the ADC-pair rate. The chained ADC PIT divider/load
is exactly 4/3 at every profile. All timestamp periods divide 8 MHz, all PIT0
periods divide 24 MHz, and the half-period ADC1 phase is integral at 150 MHz
IPG. ADC_ETC predivider remains zero, ADC0 has raw/effective delays 0/1, and
ADC1 has raw/effective delays `phase_ipg_cycles` and
`phase_ipg_cycles + 1`. The ADC1-to-ADC0 difference is therefore exactly half
of the selected ADC-pair period. The corresponding expected 600 MHz DWT deltas
are 300, 600, 1,200, and 2,400 cycles.

Arbitrary rates, a non-4:1 pair, a nonintegral timestamp period or phase, an
unlisted PIT divisor, or contradictory INFO/configuration values are rejected
before hardware mutation. INFO carries all four complete profile records, and
the active legacy timing fields echo the selected profile. Generated firmware
must read back the selected PIT loads, ADC_ETC predivider/delays, IPG phase,
timestamp divisors, and active frame counts before START succeeds.

### Mode-specific frame layouts

The 44-byte header and four-byte checksum trailer are unchanged. The configured
4,096-byte value is the maximum and remains the exact GPIO frame size. Frame
contents are:

| Mode | Stream | Item bytes | Items/frame | Payload bytes | Total bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| `DISABLED` | ADC | 4 | 1,012 pairs | 4,048 | 4,096 |
| `DISABLED` | GPIO | 1 | 4,048 samples | 4,048 | 4,096 |
| `INPUT` | ADC | 4 | 506 pairs | 2,024 | 2,072 |
| `INPUT` | GPIO | 2 | 2,024 samples | 4,048 | 4,096 |

Halving both item counts in `INPUT` mode makes the ADC and GPIO frames cover
the same interval at every profile. Their shared coverage is 4,048, 8,096,
16,192, or 32,384 timestamp ticks from fastest to slowest. `DISABLED` retains
the exact v1 counts and covers 8,096, 16,192, 32,384, or 64,768 ticks.

The shorter ADC frame is deliberate. Padding it to 4,096 bytes would either
invent samples or give the two streams different coverage. Header
`payload_length` and `item_count` identify the exact generated layout.

### INFO and STATUS target metadata

The v2 INFO body extends the v1 prefix to 632 bytes. It reports:

- supported and selected rate profiles and auxiliary modes;
- active GPIO width and item bytes, both pin maps and GPIO port-bit maps;
- both mode-specific ADC/GPIO frame counts;
- the complete four-record PIT, timestamp, IPG, ADC_ETC, DWT, and coverage
  table;
- GPIO1/GPIO6/GPR26 and GPIO2/GPIO7/GPR27 masks;
- paired-join requirement and raw-ring depth; and
- actual PIT0/XBARA1/DMAMUX/eDMA identities and fixed arbitration order.

INPUT mode fans PIT0/XBARA1 input 56 to existing output 0 and
new output 1. Output 1 maps through DMAMUX source 31 to eDMA channel 3. The
enabled-mode priority order is ADC0 `3`, ADC1 `2`, primary GPIO `1`, auxiliary
GPIO `0`; both ADC result reads remain above both GPIO reads, and the primary
read wins before the auxiliary read. This ordering does not claim simultaneous
pad aperture. The one-bank implementation retains its established priorities
when the auxiliary bank is disabled.

Both GPIO DMA paths use fixed-capacity generation-indexed ownership. A join is
publishable only when primary and auxiliary generation, first timestamp, and
count agree. A stale completion is never paired with a newer bank. Exact skew,
overrun, cancellation, rollback, and STOP-tail counters are implemented in the
portable joiner and target adapter.

Protocol-v2 STATUS is 1,476 bytes. Its complete 1,228-byte v1 prefix retains
the original offsets and projects joined logical GPIO samples. The extension
reports the selected mode/profile, item width, exact rates and coverage,
packet-retention time, per-bank READY depth/high-water, major loops, captures,
overruns and stale completions, plus paired join, delivery, skew, cancellation,
cache, hardware and lifecycle counters. GPIO processing CPU utilization uses
the established 0–10,000 basis-point scale for both one-bank and joined paths.

The v2 GPIO capture diagnostic is 272 bytes and preserves the accepted
144-byte diagnostic prefix exactly. It performs one bounded, IDLE-only paired
capture through the real PIT/XBARA/eDMA routes, reports GPIO1/GPR26 and
GPIO2/GPR27 register evidence, both TCD paths, raw/packed stable observations,
sample counts and cache ownership transitions. The registered fixture provides
no auxiliary stimulus, so `aux_electrically_unstimulated` is true and
`aux_external_transition_checks_run` remains false; observed values never
become a claim that external transitions were validated.

### Target registry and linked-memory checkpoint

The target registry now reserves D16-D23 under one auxiliary-capture owner,
GPIO1 bits `23,22,17,16,26,27,24,25`, PIT0 fan-out from XBARA1 input 56 to
outputs 0 and 1, DMAMUX sources 30 and 31, and eDMA channels 2 and 3. Because
outputs 0 and 1 share selector register 0, their independent read-modify-write
masks are `0x00FF` and `0xFF00`; a paired update uses `0xFFFF`. Compile-time
validation rejects duplicate pins, GPIO port/bits, XBAR outputs, DMA
channels/sources, IRQs/vectors, physical allocations, and overlapping logical
views.

The linked target keeps the v1 200-frame packet pool. INPUT uses two disjoint
32,384-byte raw-ring views over the existing 64,768-byte GPIO allocation, and
both GPIO layouts continue to use the same four 4,064-byte packed-buffer
strides. The new state leases 992 bytes from the existing 4,096-byte OCRAM
checksum scratch; checksum benchmarking is IDLE-only and the lease is
INPUT-acquisition-only.

| INPUT workspace view | Physical symbol / offset | Bytes | Owner |
| --- | --- | ---: | --- |
| Paired join state | `g_checksum_benchmark_ocram_buffer + 0` | 768 | GPIO join |
| Auxiliary TCD bank | `g_checksum_benchmark_ocram_buffer + 768` | 160 | Auxiliary GPIO capture |
| Primary INPUT pressure sink | `g_checksum_benchmark_ocram_buffer + 928` | 32 | GPIO capture |
| Auxiliary pressure sink | `g_checksum_benchmark_ocram_buffer + 960` | 32 | Auxiliary GPIO capture |

The inspected image placed that physical scratch at `0x20267220`, kept the
105-frame DTCM bank at `0x20001EC0` and the 95-frame OCRAM bank at
`0x20200000`, and linked `.bss.dma` over
`0x20200000..0x2027F000`. The Teensy summary retained 33,344 RAM1 bytes for
locals/stack and the required 4,096-byte RAM2 heap floor. Manifest schema 11
cross-checks those section bounds, all 13 physical managed allocations, the
four non-overlapping workspace views, and rejects an undocumented packet
capacity change.

With 200 packet frames, the exact complete two-stream retention is:

| Profile | `DISABLED` | `INPUT` | `INPUT` single stream |
| --- | ---: | ---: | ---: |
| `ADC_1MHZ_GPIO_4MHZ` | 101.200 ms | 50.600 ms | 101.200 ms |
| `ADC_500KHZ_GPIO_2MHZ` | 202.400 ms | 101.200 ms | 202.400 ms |
| `ADC_250KHZ_GPIO_1MHZ` | 404.800 ms | 202.400 ms | 404.800 ms |
| `ADC_125KHZ_GPIO_500KHZ` | 809.600 ms | 404.800 ms | 809.600 ms |

INPUT eDMA arbitration is fixed in descending order as ADC0 `3`, ADC1 `2`,
primary GPIO `1`, and auxiliary GPIO `0`; auxiliary channel 3 owns IRQ 3,
vector 19, at NVIC priority 64. This is only an eDMA service order. It does not
promise pad-level simultaneity, which remains a target-measurement question.

## Consequences

- Ordinary clients, v1 frames, D6-D13 bit positions, and default rates remain
  unchanged and form the compatibility oracle.
- An auxiliary GPIO sample doubles payload bandwidth from 4 MB/s to 8 MB/s.
  Full combined payload is therefore 12 MB/s. This is an analytic load
  hypothesis until host benchmarks and physical USB tests accept it.
- The experimental generator, Python API, simulator, portable joiner, target
  adapter, and fixtures must consume one contract and reject metadata drift.
- The target must reserve one additional XBAR output, DMAMUX source, eDMA
  channel, IRQ owner, raw ring, overflow sink, descriptor chain, and paired
  join state before enabling INPUT mode.
- This branch cannot be combined with the D16-D23 output proposal without a
  new ownership decision and compound validation campaign.

## Alternatives considered

### Permit per-pin INPUT/OUTPUT mixing

Rejected because it creates electrical contention risk, ambiguous packed
width, combinatorial capability metadata, and teardown states that this input
experiment does not need. Whole-bank INPUT or DISABLED is structural and
fail-closed.

### Renumber D6-D13 above the new bank

Rejected because every existing GPIO byte, channel index, NumPy column, test
fixture, and captured file relies on D6-D13 occupying bits 0-7.

### Accept arbitrary numeric rates

Rejected because rounding independent clock domains would make timestamps,
ADC phase, readback, and cross-language fixtures disagree. Four complete exact
profiles are sufficient to measure load scaling without an open-ended clock
API.

### Keep 1,012 ADC pairs in INPUT mode

Rejected because one ADC frame would cover twice the interval of a 2,024-item
16-bit GPIO frame. Equal-coverage pairing and loss accounting require 506 ADC
pairs.

### Modify protocol v1 in place

Rejected because v1 requires an eight-byte CONFIGURE request, fixed one-byte
GPIO items, fixed data-frame counts, and reserved capabilities. Reinterpreting
those bytes would turn strict compatibility checks into ambiguous behavior.
