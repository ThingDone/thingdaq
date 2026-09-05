---
type: analysis
title: 'ADR 003: GPIO Clock and DMA'
created: 2026-08-28
updated: 2026-08-28
tags:
  - thingdaq
  - decision
  - gpio
  - pit
  - xbar
  - edma
  - phase-06
related:
  - '[[Firmware-Resource-Map]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[System-Overview]]'
---

# ADR 003: GPIO clock and DMA

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

## Status

Accepted and verified on the Teensy 4.0 rig. The fixed production clock route
is 24 MHz PERCLK through PIT0, XBARA1 input 56/output 0 with **rising-edge-only**
DMA request generation, DMAMUX source 30, and eDMA channel 2. The optional
IDLE-only clock diagnostic is advertised. The pad remap and raw capture ring
are integrated as the advertised GPIO-only hardware source, and the
cooperative batch packer feeds the fixed packet queues with the normal packed
GPIO layout. The advertised fail-closed capture diagnostic reuses that
production path without driving D6-D13.

## Context

Protocol v1 presents GPIO samples as one byte in D6-through-D13 order at an
immutable production rate of 4 MHz. The i.MX RT1062 eDMA engine cannot read the
Teensy core's fast GPIO7 alias, so acquisition must selectively return only
those pads to the standard GPIO2 alias and copy fixed-width `GPIO2_PSR` words
into DMA-visible storage. The CPU packer extracts the eight sparse bits into the
wire order defined by [[Protocol-V1]].

The registry in `firmware/src/board_config.h` already reserved PIT0, XBAR1
request 0, eDMA channel 2, and four raw GPIO DMA buffers. This review checked
those reservations against all other firmware owners before accepting them.
It also checked the exact pinned implementation rather than assuming current
upstream library behavior applies to Teensy core 1.62.0.

## Audited baseline

The implementation baseline is Teensy core
`/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0`, as pinned by the
firmware build. The following inputs were reinspected on 2026-08-28:

| Source | Finding used by this decision |
| --- | --- |
| `cores/teensy4/core_pins.h` | D6-D13 all use the GPIO7 fast alias; their port bits are 10, 17, 16, 11, 0, 2, 1, and 3. |
| `cores/teensy4/startup.c` | Startup selects the 24 MHz peripheral clock for PIT/GPT, enables PIT, clears all PIT channels, and writes all ones to `IOMUXC_GPR_GPR27` to select GPIO7. |
| `cores/teensy4/imxrt.h` | PIT trigger 0 is XBARA1 input 56; DMA request 30 is XBARA1 output 0 and DMAMUX source 30; the RT1062 exposes four PIT and 32 eDMA channels. |
| `cores/teensy4/IntervalTimer.cpp` | `IntervalTimer` scans for the first PIT channel whose control register is unused, so it cannot enforce this project's PIT0/PIT1 ownership. |
| `cores/teensy4/DMAChannel.{h,cpp}` | Default allocation selects an available channel dynamically; fixed project ownership therefore requires an explicit channel. |
| `libraries/OctoWS2811/OctoWS2811_imxrt.cpp` | Reusable patterns are selective fast-to-standard GPIO remapping, XBAR edge-triggered DMA, explicit TCD setup, aligned `DMAMEM`, and cache maintenance. Its dual-edge setting is specific to its QuadTimer waveform and over-counts the PIT source at 4 MHz; its concrete timer/XBAR/DMA owners are not reusable concurrently. |
| `libraries/ADC/AnalogBufferDMA.cpp` and DMA examples | Reusable patterns are 32-byte aligned OCRAM buffers, scatter/gather major loops, and cache invalidation. Their first-free DMA allocation policy is not reused. |

The official NXP RT1062 definitions independently confirm the PIT-to-XBARA and
XBARA-to-DMAMUX identities, GPIO2/GPIO7 selection through GPR27, and 32-byte
TCD alignment. The primary references are the
[i.MX RT1060 reference-manual page](https://www.nxp.com/products/i.MX-RT1060?tab=Documentation_Tab),
[MIMXRT1062 device API](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/api/devices/MIMXRT1062/index.html),
[PIT training note](https://www.nxp.com/docs/en/supporting-information/Periodic-Interrupt-Timer-Training.pdf),
[PIT example](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/examples/driver_examples/pit/readme.html),
[XBARA example](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/examples/driver_examples/xbara/readme.html),
and [eDMA examples](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/examples/driver_examples/edma/index.html).
The official
[XBARA API](https://mcuxpresso.nxp.com/api_doc/dev/1262/group__xbara.html)
defines active-edge value 1 as rising-only and value 3 as rising-and-falling;
the accepted configuration uses value 1.
The exact reviewed NXP header revision is commit
[`8a289764`](https://github.com/nxp-mcuxpresso/legacy-mcux-sdk/blob/8a289764d763ad06e0c3a05c885644ed98b970af/devices/MIMXRT1062/MIMXRT1062.h).

## Decision

### Board and pin identity

Target compilation fails unless Arduino identifies a Teensy 4.0 and the
i.MX RT1062. Portable host tests remain possible because they do not define
`ARDUINO`. The production mapping is centralized and compile-time checked
against the pinned `CORE_PIN*_BIT` and `CORE_PIN*_BITMASK` definitions:

| Packed wire bit | Teensy pin | Standard GPIO source bit |
| ---: | ---: | ---: |
| 0 | D6 | GPIO2 bit 10 |
| 1 | D7 | GPIO2 bit 17 |
| 2 | D8 | GPIO2 bit 16 |
| 3 | D9 | GPIO2 bit 11 |
| 4 | D10 | GPIO2 bit 0 |
| 5 | D11 | GPIO2 bit 2 |
| 6 | D12 | GPIO2 bit 1 |
| 7 | D13 | GPIO2 bit 3 |

The combined GPIO2/GPR27 mask is exactly `0x00030C0F`. Future register code
must use a read-modify-write that clears only this mask in
`IOMUXC_GPR_GPR27`, clears only this mask in `GPIO2_GDIR` for input, and reads
the fixed 32-bit `GPIO2_PSR` address. Unrelated GPR and direction bits remain
owned by the core or other peripherals.

### Verified clock and DMA route

The isolated hardware spike uses this fixed path:

```text
24 MHz PERCLK -> PIT0 (LDVAL 5) -> XBARA1 input 56
               -> rising-edge detector -> XBARA1 output 0
               -> DMAMUX source 30 -> eDMA channel 2
               -> 32-bit diagnostic transfer (later: GPIO2_PSR samples)
```

NXP PIT arithmetic is `period = LDVAL + 1` clocks, so six 24 MHz clocks are
250 ns and the event rate is exactly 4 MHz. Hardware jobs
`f8ffbc96-4259-4f82-a42a-a6b8415a1b0f` and final-image job
`db75db1e-45c0-4f66-a09a-bb4adee26b77` verified the clock selector, divider,
rising-edge request mode (`XBARA1_CTRL0=0x0005`), event/sample ratio, and
elapsed 600 MHz DWT cycles at 1 kHz, 1 MHz, and three consecutive 4 MHz
windows each. The final pre-rename `tdaq-e5da045334978b23` image captured 8,192 samples
in every production window while the independently timed DWT window covered
8,193 boundaries, within the explicit one-event tolerance, with zero
hardware/eDMA errors.

eDMA channels 0 and 1 remain reserved for ADC1 and ADC2 through DMAMUX sources
24 and 88. GPIO owns fixed channel 2 and DMAMUX source 30. Its production
priority is 0, below paired ADC priorities 2/1, so the continuous 4 MHz request
cannot delay either converter-result transfer past the paired boundary. The
isolated diagnostic transfers one fixed sentinel word into another word in a
dedicated 32-byte-aligned OCRAM cache line; it does not remap or sample a pad.
The physical adapter uses the budgeted four-buffer OCRAM ring and fixed-width
`GPIO2_PSR` reads. Channel priority, TCD linkage, cache
ownership, and major-loop interrupt policy may not change these owners
silently.

### Raw capture and pressure policy

The physical adapter applies one narrow read-modify-write on START and every
STOP/error path: it clears only `0x00030C0F` in `GPIO2_GDIR`, then clears only
the same bits in `IOMUXC_GPR_GPR27`. Making GPIO2 inputs first guarantees that
switching D6-D13 away from the startup GPIO7 aliases cannot expose an output;
all unrelated direction and alias bits are preserved.

At the production rate, channel 2 reads the fixed 32-bit `GPIO2_PSR` source
with `SOFF=0` and writes 4,048 words into each cache-line-aligned OCRAM raw
buffer. Five 32-byte TCDs provide scatter/gather descriptors for the four
consumer buffers plus one overflow destination. Each consumer descriptor uses
`DOFF=4`; the overflow descriptor uses `DOFF=0` and repeatedly overwrites one
isolated 32-byte cache line. `INTMAJOR` fires once per 4,048 samples (about
988 Hz), never once per 4 MHz sample, and channel priority remains fixed at 2.

The ownership state machine always reserves both an active and one look-ahead
destination. A completed consumer buffer becomes `READY`; only a `FREE` buffer
may become the later `DMA_QUEUED` destination. If none is free, the look-ahead
link selects the DMA-only sink, so capture continues without overwriting a
`READY`, `PACKING`, or `RELEASING` buffer. Every completed sink major loop is
exactly 4,048 lost samples. Normal STOP sets the active TCD's `DREQ` bit and
waits at most 10 ms for its next complete major-loop boundary, so a healthy
shutdown retains the last complete buffer and creates no partial-tail loss. A
timed-out or otherwise abnormal stop still fails safe immediately, accounts a
partial sink or consumer loop from `BITER-CITER`, and increments the STOP error
counter. Cumulative pressure/abnormal-stop loss feeds the common statistics
model and contributes to its GPIO-drop projection.

Cache maintenance is part of ownership, not an incidental call in packing.
All consumer buffers and the sink are deleted before DMA ownership, a completed
buffer is invalidated only after it atomically enters `PACKING`, and release
deletes it before it becomes `FREE`. The major-loop ISR performs no cache
operation, packing, framing, checksum, allocation, or USB work. A stale lease
cannot release a reused buffer, and STOP retains complete `READY` buffers and
valid `PACKING` leases for deterministic draining before another epoch.

### Batch packing, framing, and raw diagnostics

The selected hot primitive is the allocation-free
`shift-mask-unrolled-4` batch loop. It gathers GPIO2 source bits
`10,17,16,11,0,2,1,3` into output bits `0..7`, so every sample occupies exactly
one wire payload byte in D6-through-D13 order. One source acquire/release
dispatch occurs per raw batch; there is no virtual pin call, `digitalRead`, or
per-sample interrupt. A repeatable host `-O3 -flto` microbenchmark measured
2,481.196 MB/s of packed payload on the implementation host against the 4 MB/s
requirement. That number selects and guards the batch implementation locally;
the later full GPIO gate remains responsible for target DWT/CPU headroom.

Four 4,064-byte-stride packed buffers in OCRAM separate short raw-lease
ownership from packet/checksum work. They use
`FREE -> FILLING -> READY -> FRAMING -> FREE`; complete buffers then enter the
existing fixed packet `READY` and `TRANSMITTING` queues. The assembler follows
canonical 4,048-sample boundaries even when raw batches split them. Each record
stores its first absolute sample, which becomes `first_sample * 2` at the 8 MHz
wire timebase. The packet epoch supplies run ID, independent GPIO sequence, and
selected checksum. Raw or packed drops are inserted before the next retained
frame, producing an exact sequence skip plus `GAP_BEFORE | OVERRUN_BEFORE` and
timestamp evidence.

Native progress exposes produced, packed, framed, transmitted, and dropped
frames/samples plus raw-gap and packer-pressure components. Projection markers
identify pre-packet loss already charged to a packet sequence slot; the common
statistics model subtracts those markers from raw/packer additions so one loss
cannot be reported twice.

Raw GPIO2 words remain available only through
`BoundedRawWordDiagnostic`, which exposes at most 256 samples from one leased
buffer for internal troubleshooting and has no frame or transport encoder. The
normal capabilities and GPIO wire contract continue to advertise only one
packed byte per 4 MHz sample, never the 16 MB/s internal word stream.

### Autonomous fixture policy and diagnostic coverage

The registered remote-firmware fixture material was inspected before adding a
pad diagnostic. The public platform catalog identifies Port 15 as a Teensy 4.0
and points to `HOWTO.md`,
`docs/validation/incoming-board-bringup-2026-08-16.md`, and
`lab/reference_firmware/arduino_serial_ping/README.md`. Those documents record
the board, USB serial, hub port, loader, and serial-test path. They do **not**
state that D6-D13 are unconnected or safe to drive, and they contain no
machine-readable loopback or stimulus declaration. That absence is not treated
as permission.

`gpio_capture_diagnostic.{h,cpp}` therefore makes fixture authorization a
build-time policy rather than a host-selected request. Absent or prose-only
metadata always selects `kNonDrivingCapture`. A future machine-readable
declaration is accepted only when it has a schema and fixture identity and
names exactly the D6-D13 pin mask. An output sweep additionally requires the
explicit `kExplicitlySafe` value; a declared stimulus has its own nonzero
identity and selects an input-only stimulus mode. Invalid or partial metadata
falls back to non-driving capture and retains an error flag.

The current Teensy adapter implements only the selected non-driving path. It
clears the exact GDIR/GPR27 mask to inputs, starts the production 4 MHz
`GPIO2_PSR` raw ring, waits at most 6,000,000 DWT cycles for one complete
4,048-word DMA buffer, stops the timer/request/channel, analyzes only a bounded
256-word lease with the production pack primitive, drains every ready lease,
and verifies the ring is quiescent and the pins remain standard GPIO2 inputs.
Its snapshot separates capture evidence (counts, TCD/route registers, raw and
packed AND/OR values, and observed transitions) from validation coverage. It
always reports output drive and external-transition validation as not
exercised on this fixture. A transition on an undriven input is merely an
observation and cannot become electrical or mapping evidence.

The target path contains no GPIO data-register, `pinMode`, or `digitalWrite`
operation. Exhaustive PSR-to-packed mapping remains independently proven for
all 256 values by the optimized host-C++ packer test. The capture diagnostic is
intentionally not yet a wire command or capability; the later physical-mode
integration owns its atomic IDLE command exposure and INFO metadata.

## Reused patterns and boundaries

- Reuse the narrow OctoWS2811 GPR-mask technique, XBAR edge/DMA-enable
  configuration shape, explicit TCD construction, and cache-line discipline;
  use the PIT-proven rising edge rather than copying its dual-edge mode.
- Reuse the ADC DMA examples' aligned `DMAMEM` and scatter/gather ownership
  patterns after adapting them to a fixed channel and a read-only peripheral
  source.
- Keep all configuration in project-owned register adapters so diagnostic
  snapshots and host-side register tests can prove exactly what changed.
- Do not instantiate `IntervalTimer`, `DMAChannel` with its default allocator,
  OctoWS2811, or `AnalogBufferDMA` in the acquisition path. They conceal or
  dynamically select resources that this registry owns explicitly.
- Do not copy OctoWS2811's QuadTimer frequency assumptions. Its code proves a
  useful routing pattern, not this project's exact 4 MHz PIT schedule.

## Conflicts

| Potential owner | Conflict | Resolution |
| --- | --- | --- |
| `IntervalTimer` | May claim PIT0 or PIT1 dynamically. | Prohibited while acquisition resources are compiled in; configure PIT registers explicitly. |
| OctoWS2811 | Uses QuadTimer4, XBARA1 outputs 0-2, DMAMUX sources 30/31/94, and dynamically allocated eDMA channels. | Reference implementation only; it cannot coexist with acquisition. |
| `DMAChannel` / ADC DMA helpers | First-free allocation can take channels 0-2 or alter priority. | Bind ADC to channels 0/1 and GPIO to channel 2 through project adapters. |
| Pin multiplexing and the D13 LED | D6-D13 are exclusive capture pads; D10-D13 also have common board-level alternate uses. | Reject conflicting configuration before changing mux/GPR state and restore safe inputs on STOP/error. |
| Teensy startup | Writes all ones to GPR27, selecting GPIO7. | Apply the narrow `0x00030C0F` clear only when arming GPIO capture. |
| USB Serial | Uses its own core-owned USB DMA buffers rather than project eDMA channels. | Preserve its separate ownership; no channel change is required. |

## Hardware-spike findings and retained fallback order

The first implementation inherited OctoWS2811's dual-edge mode. The spike
then followed the identity fallbacks in order before isolating edge polarity:

| Job | PIT/input | XBAR output/source | Result |
| --- | --- | --- | --- |
| `775a4457-4bd4-410d-8d62-5e82d7407da1` | PIT0 / 56 | 0 / 30 | Low rates passed; 4 MHz produced 8,443 samples for 8,193 scheduled. |
| `c1655c5d-09c9-451e-81b0-f488a71ac854` | PIT0 / 56 | 1 / 31 | Rejected at 1 kHz: 64 samples for 32 scheduled. |
| `45938e6e-376e-4ef1-a480-40f079f70453` | PIT0 / 56 | 2 / 94 | Rejected at 1 kHz: 64 samples for 32 scheduled. |
| `909a7745-18ff-4638-a391-4984cecb1440` | PIT0 / 56 | 3 / 95 | Two 4 MHz windows passed; the third produced 12,288 samples for 8,193 scheduled. |
| `8a967689-6fc4-48c8-aced-3c01541efe90` | PIT2 / 58 | 3 / 95 | 4 MHz produced 12,288 samples for 8,192 scheduled. |
| `50dedf8b-046b-42f7-89ca-0258112b3734` | PIT3 / 59 | 3 / 95 | 4 MHz produced 12,288 samples for 8,192 scheduled. |
| `f8ffbc96-4259-4f82-a42a-a6b8415a1b0f` | PIT0 / 56 | 0 / 30, rising-only | Accepted: low rates and three repeated 4 MHz windows all had exact event/sample counts and zero error flags. |
| `db75db1e-45c0-4f66-a09a-bb4adee26b77` | PIT0 / 56 | 0 / 30, rising-only | Final image accepted: low rates had exact counts; all three 4 MHz windows had 8,192 samples for 8,193 DWT-scheduled boundaries, within tolerance, with zero error flags. |

These results reject dual-edge request generation, not the exact PIT divisor.
If the accepted path regresses on another board, preserve rising-edge mode and
retry outputs 1/source 31, 2/source 94, and 3/source 95 in that order, followed
by PIT2/input 58 and PIT3/input 59. PIT1 stays reserved for ADC acquisition.
Only then may a conflict-free QuadTimer, FlexPWM, or FlexIO source be measured;
it is acceptable only at exactly 4 MHz. An accepted fallback requires an
updated [[Firmware-Resource-Map]], core macro assertions, register tests, and
rig evidence. Never substitute an approximate rate or silently weaken
capability metadata.

## Consequences

- The exact PIT divisor and rising-edge PIT/XBARA/eDMA event path are proven on
  the target; the physical adapter now uses it for `GPIO2_PSR`, but external
  pad transitions and sustained streaming remain unproven.
- The registered fixture does not authorize D6-D13 output drive and supplies no
  loopback or stimulus identity. The autonomous capture diagnostic therefore
  remains input-only; external transition, pad-electrical, and self-driven
  stable-window validation are explicitly unexercised.
- Packed GPIO order and standard-port bit identities can no longer drift from
  the pinned core without a target compile failure.
- Host compilation validates duplicate, range, order, and exact-mask errors
  without depending on Teensy headers.
- The resource assignment is deterministic and reviewable; acquisition code
  cannot silently use a first-free timer, XBAR output, or DMA channel.
- The linked image contains 64,768 bytes of raw consumer storage, a 32-byte
  pressure sink, 160 bytes of TCDs, and 16,256 bytes of packed storage in
  OCRAM. The overflow policies trade retention—not live sampling or buffer
  safety—when downstream work falls behind.
- The advertised GPIO clock diagnostic remains bounded to IDLE, never remaps
  D6-D13, and reports isolated clock/register/count evidence. The advertised
  capture diagnostic reuses the raw ring and restores safe inputs. Physical
  GPIO CONFIGURE/START/STOP now owns the same declared route, rejects conflicts
  before mutation, and exposes stage/resource/error evidence in INFO/STATUS.
