---
type: analysis
title: 'ADR 003: GPIO Clock and DMA'
created: 2026-08-28
updated: 2026-08-28
tags:
  - teensy-daq
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

## Status

Accepted and verified on the Teensy 4.0 rig. The fixed production clock route
is 24 MHz PERCLK through PIT0, XBARA1 input 56/output 0 with **rising-edge-only**
DMA request generation, DMAMUX source 30, and eDMA channel 2. The optional
IDLE-only clock diagnostic is advertised; this decision still does not enable
or advertise the physical GPIO source, whose pad mapping and capture ring are
later Phase 06 work.

## Context

Protocol v1 presents GPIO samples as one byte in D6-through-D13 order at an
immutable production rate of 4 MHz. The i.MX RT1062 eDMA engine cannot read the
Teensy core's fast GPIO7 alias, so acquisition must selectively return only
those pads to the standard GPIO2 alias and copy fixed-width `GPIO2_PSR` words
into DMA-visible storage. The later CPU packer will extract the eight sparse
bits into the wire order defined by [[Protocol-V1]].

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
windows each. The final `tdaq-e5da045334978b23` image captured 8,192 samples
in every production window while the independently timed DWT window covered
8,193 boundaries, within the explicit one-event tolerance, with zero
hardware/eDMA errors.

eDMA channels 0 and 1 remain reserved for ADC1 and ADC2 through DMAMUX sources
24 and 88. GPIO owns fixed channel 2 at priority 2 and DMAMUX source 30. The
isolated diagnostic transfers one fixed sentinel word into another word in a
dedicated 32-byte-aligned OCRAM cache line; it does not remap or sample a pad.
The later physical path will use the already budgeted four-buffer OCRAM ring
and fixed-width `GPIO2_PSR` reads. Channel priority, TCD linkage, cache
ownership, and major-loop interrupt policy may not change these owners
silently.

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
  the target; external pad transitions and sustained capture remain unproven.
- Packed GPIO order and standard-port bit identities can no longer drift from
  the pinned core without a target compile failure.
- Host compilation validates duplicate, range, order, and exact-mask errors
  without depending on Teensy headers.
- The resource assignment is deterministic and reviewable; acquisition code
  cannot silently use a first-free timer, XBAR output, or DMA channel.
- The optional diagnostic is bounded to IDLE, never remaps D6-D13, and reports
  raw register/count evidence. Physical GPIO capability remains disabled until
  later Phase 06 mapping, rotating-buffer, packing, and streaming gates pass.
