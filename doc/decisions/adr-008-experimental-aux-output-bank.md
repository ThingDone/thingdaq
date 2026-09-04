---
type: analysis
title: 'ADR 008: Experimental Auxiliary Output Bank'
created: 2026-09-04
tags:
  - thingdaq
  - decision
  - protocol
  - digital-output
  - dma
  - experiment
related:
  - '[[1-MHz-Parallel-Output-Idea]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Protocol-V1]]'
  - '[[Hardware-Safety]]'
---

# ADR 008: Experimental auxiliary output bank

## Status

Accepted for the isolated `experiment/aux-output-bank` prototype. This ADR
freezes a noninteractive protocol-v2 design contract; it does not authorize
physical output, alter the production protocol-v1 contract, or change any
default acquisition behavior. Target pin driving remains prohibited until a
later task implements the adapter and a declared rig fixture explicitly
authorizes the electrical setup under [[Hardware-Safety]].

The simulator and portable engine planned by this experiment can establish
logical scheduling and lifecycle behavior, but cannot establish pad timing,
electrical compatibility, signal integrity, DMA arbitration, or sustained USB
performance on a Teensy. Reset, power loss, and bootloader entry are outside
the software hold guarantee.

## Context

[[Protocol-V1]] defines a strict acquisition-only wire contract. Unknown
versions and capability bits are rejected, control request bodies are bounded
to eight bytes, and D16-D23 are not owned. The current physical schedule in
[[Acquisition-Pipeline]] uses PIT0 as the 4 MHz master and chained PIT1 as the
1 MHz ADC-pair epoch. [[Firmware-Resource-Map]] owns eDMA channels 0-2 and the
existing ADC/GPIO routes.

[[1-MHz-Parallel-Output-Idea]] proposes using D16-D23 as an eight-bit output
bank driven from preloaded run-length-encoded data. The experiment needs an
exact program model, an all-or-nothing direction rule, deterministic terminal
states, and fault behavior before adding upload, simulator, portable-engine,
or target-register code.

The frozen baseline has only 4,096 bytes of RAM2 headroom and 34,528 bytes of
RAM1 local/stack headroom. A future 1,024-segment store and output ring must
therefore use a linker-accounted packet-page repartition; this ADR makes no new
target allocation.

## Decision

The canonical experimental source is `protocol/protocol-v2.json`. It is a
complete versioned contract pinned to the SHA-256 of
`protocol/protocol-v1.json`, and it declares generated constants and fixtures
at paths disjoint from v1. Protocol v1 remains authoritative unless a host
explicitly requests and successfully negotiates auxiliary output.

### Whole-bank direction and safe activation

The D16-D23 bank has exactly two public modes:

| Value | Mode | Meaning |
| ---: | --- | --- |
| `0` | `DISABLED` | The program is absent or released and all eight pads are high-impedance inputs. |
| `1` | `OUTPUT` | All eight pads are push-pull outputs under the committed program owner. |

There is no INPUT mode and no per-pin direction mask. Mixed directions and all
other scalar values are invalid. Merely beginning, appending, or committing an
upload cannot drive a pad. The pins remain inputs until an explicit committed
program is armed. Successful ARM transfers whole-bank ownership, configures
all eight pads as outputs, and physically emits the declared idle state;
program playback does not begin until the common `START` transition succeeds.

The logical-to-physical map is fixed:

| Logical bit | Teensy pin | GPIO1 bit |
| ---: | ---: | ---: |
| 0 | D16 | 23 |
| 1 | D17 | 22 |
| 2 | D18 | 17 |
| 3 | D19 | 16 |
| 4 | D20 | 26 |
| 5 | D21 | 27 |
| 6 | D22 | 24 |
| 7 | D23 | 25 |

The standard-port mask is `0x0FC30000`, using the GPIO6/GPIO1 aliases selected
through IOMUXC GPR26. All eight pins are 3.3 V-only. The target implementation
must validate the entire map and direction before changing any mux, direction,
or data register.

### Fixed schedule and common epoch

Output is preloaded and device-timed at exactly 1,000,000 intervals per second.
One output interval is one microsecond, or eight ticks in the existing 8 MHz
timestamp domain. PIT1 is the shared 1 MHz event source for both output and the
ADC-pair schedule. Host USB timing controls upload transactions only; it never
controls an individual output edge.

The first output event occurs at common tick zero. It changes the declared idle
state to the first segment state and shares the same epoch as the first ADC0
trigger and the nominal first GPIO input sample. This is schedule metadata,
not a claim about which coincident DMA access or external pad transition wins
on silicon.

`START` remains the single atomic epoch transition. If acquisition or armed
output cannot prepare, validate, arm, or start, the controller rolls back the
entire transition and no partial run is observable.

### Canonical program

A program is an ordered sequence of at most 1,024 canonical segments. Each
segment has this eight-byte logical representation:

```text
u32 duration_samples
u32 logical_state_mask
```

`duration_samples` is a strictly positive count of one-microsecond intervals.
Only bits 0-7 of `logical_state_mask` are legal. Adjacent segments with equal
states are coalesced by the typed builder; the canonical wire contract rejects
an adjacent duplicate so Python, simulator, and firmware checksum exactly the
same sequence. Coalescing must detect `u32` duration overflow rather than wrap.

The canonical checksum is computed over the exact concatenation of the
little-endian eight-byte segment records, without transport headers or program
metadata. Program metadata separately contains a declared eight-bit idle state
and a `u32 repeat_count`.

`repeat_count = 0` means repeat forever. A positive value `N` means exactly
`N` complete plays of the whole segment sequence. Zero segments cannot be
committed or armed. A segment duration of zero, high state bits, adjacent equal
states, more than 1,024 segments, an overflowed coalesced duration, a checksum
mismatch, or an incomplete upload is rejected without changing the last
committed program.

### Upload generations and immutability

Output operations remain within the existing eight-byte command-body maximum.
For output commands, the otherwise data-oriented header `run_id` carries a
nonzero upload generation and is echoed by the response. This avoids weakening
the eight-byte segment representation:

- `OUTPUT_BEGIN` carries `u32 repeat_count` and `u32 idle_state_mask`.
- `OUTPUT_APPEND` carries exactly one canonical segment.
- `OUTPUT_COMMIT` carries `u32 segment_count` and the end-to-end `u32`
  canonical checksum.
- `OUTPUT_ARM`, `OUTPUT_STATUS`, and `OUTPUT_CLEAR` have empty request bodies.

`request_id` retains its existing response-correlation role; it is not an
upload generation. Begin, append, commit, and arm require the same nonzero
generation. Device state, generation, accepted-segment count, and exact echoed
values make retries and stale/mixed uploads distinguishable. Upload mutations
are accepted only in controller `IDLE`. Once committed, segment bytes,
metadata, checksum, and generation are immutable until `OUTPUT_CLEAR`.
`OUTPUT_STATUS` is query-only and remains valid in IDLE, CONFIGURED, and
RUNNING; querying it never advances output time.

The next protocol-generator task assigns frame IDs, response schemas, complete
metadata, typed errors, and golden vectors from this frozen design. It must not
alter any v1 source, generated constant, fixture, manifest, or default byte.

### Lifecycle and terminal behavior

The output lifecycle is:

```text
EMPTY -> LOADING -> COMMITTED -> ARMED -> RUNNING -> HELD
                                           |          |
                                           +-> FAULTED
```

`OUTPUT_BEGIN` starts a fresh loading generation without changing pins.
Successful commit atomically replaces the prior committed program. ARM is
valid only for that committed generation while the controller is IDLE. The
successful common `START` changes ARMED to RUNNING and emits the first state at
tick zero.

Finite completion disables output DMA after the final interval and holds the
last state physically emitted. Explicit common `STOP` orders trigger shutdown
before DMA shutdown and likewise holds the last physically emitted state. It
does not infer the state from the program cursor. Acquisition may stop for its
own fault using the existing rules; any output underrun or output DMA fault
instead stops the entire common run because alignment is no longer valid.
Such a fault disables output DMA, holds the last emitted state, latches the
generation, state, tick, counters, and error evidence, and enters `FAULTED`.

Held output is intentionally still driven. The only operation that disarms,
erases the committed/loading program, clears the latched output fault, and
returns every D16-D23 pad to a high-impedance input is explicit
`OUTPUT_CLEAR`. CLEAR is valid only while the common controller is IDLE. It
must be implemented as a fail-closed release transaction; a direction-restore
failure remains fault evidence rather than being reported as safely released.

Reset, power loss, bootloader entry, or loss of MCU power never promises a held
output state. They return pads according to hardware reset behavior.

## Consequences

- Ordinary acquisition remains protocol v1 and preserves every default byte.
- Output requires explicit v2 capability, exact pin-map/rate/capacity/timing
  agreement, a fully committed program, and an explicit ARM.
- The host can build and upload ahead of time without participating in
  real-time playback.
- A common-run output fault is intentionally fail-stop for acquisition because
  continuing would create data whose output alignment is known to be invalid.
- STOP and finite completion retain a driven voltage; callers must use CLEAR
  when high impedance is required.
- A 1,024-record program consumes 8,192 bytes before output blocks and
  metadata. Target feasibility depends on a measured packet-page repartition,
  not the baseline's remaining RAM2.
- This branch is mutually exclusive with the D16-D23 auxiliary-input branch.

## Alternatives considered

### Permit mixed or input directions

Rejected because direction bitmaps multiply lifecycle and electrical-contention
states. The experiment needs one output byte, so whole-bank ownership is the
smallest fail-closed contract.

### Stream edges from the host

Rejected because USB and desktop scheduling cannot provide deterministic
microsecond edge timing. Upload is deliberately outside the real-time run.

### Normalize adjacent duplicates in firmware

Rejected as the wire rule because two representations would describe the same
program and make end-to-end checksum agreement ambiguous. Python may coalesce
before upload; firmware validates one canonical representation.

### Return pins to input on STOP

Rejected because it would not implement the required last-state hold and would
make finite completion differ from explicit STOP. CLEAR is the separate,
explicit release boundary.

### Continue acquisition after output underrun

Rejected because the host could no longer associate samples with the declared
output program. The common epoch stops and preserves fault evidence.

### Modify protocol v1 in place

Rejected because v1 reserves unknown capability bits, has no output lifecycle,
and treats control header `run_id` as zero. The isolated v2 contract can define
generation semantics without reinterpreting any v1 byte.
