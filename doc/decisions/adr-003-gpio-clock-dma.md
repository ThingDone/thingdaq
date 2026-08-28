---
type: analysis
title: 'ADR 003: GPIO Clock and DMA'
created: 2026-08-28
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

Accepted as the Phase 06 resource assignment and hardware-spike order. The
register path remains a candidate until it is measured on the Teensy 4.0 rig;
this decision does not enable or advertise the physical GPIO source. A failed
candidate must follow the ordered fallbacks below and update both this record
and the centralized registry before the physical capability can be enabled.

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
| `libraries/OctoWS2811/OctoWS2811_imxrt.cpp` | Reusable patterns are selective fast-to-standard GPIO remapping, XBAR edge-triggered DMA, explicit TCD setup, aligned `DMAMEM`, and cache maintenance. Its concrete timer/XBAR/DMA owners are not reusable concurrently. |
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

### Primary clock and DMA route

The isolated hardware spike will use this fixed path:

```text
24 MHz PERCLK -> PIT0 (LDVAL 5) -> XBARA1 input 56
               -> XBARA1 output 0 -> DMAMUX source 30
               -> eDMA channel 2 -> 32-bit GPIO2_PSR samples
```

NXP PIT arithmetic is `period = LDVAL + 1` clocks, so six 24 MHz clocks are
250 ns and the candidate event rate is exactly 4 MHz. The spike must verify
the clock selector, divider, request-edge behavior, event/sample ratio, and
elapsed DWT cycles on silicon before treating that arithmetic as evidence of a
working acquisition route.

eDMA channels 0 and 1 remain reserved for ADC1 and ADC2 through DMAMUX sources
24 and 88. GPIO owns fixed channel 2 and DMAMUX source 30. The raw destination
is the already budgeted four-buffer, 32-byte-aligned OCRAM ring; each transfer
is a fixed 32-bit source read and destination write. Channel priority, TCD
linkage, cache ownership, and major-loop interrupt policy are implementation
details for the subsequent acquisition task and may not change these owners
silently.

## Reused patterns and boundaries

- Reuse the narrow OctoWS2811 GPR-mask technique, XBAR edge/DMA-enable
  configuration shape, explicit TCD construction, and cache-line discipline.
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

## Ordered fallbacks

If the primary route does not produce one GPIO word per measured event on the
rig, preserve the exact 4 MHz requirement and investigate in this order:

1. Keep PIT0 and try the next free XBARA1 DMA request pair: output 1/source 31,
   then output 2/source 94, then output 3/source 95. Reserve the selected pair
   centrally before using it.
2. If PIT0 itself is the conflict, test PIT2/input 58 and then PIT3/input 59
   with the same 24 MHz, `LDVAL=5` arithmetic. PIT1 stays reserved for the ADC
   acquisition schedule.
3. Only after those routes fail, measure an explicitly configured QuadTimer,
   FlexPWM, or FlexIO source and accept one only if its production event is
   exactly 4 MHz and its complete resource set is conflict-free.
4. If none is proven, keep the physical GPIO capability disabled and report
   the hardware error. Never substitute an approximate rate or silently
   change capability metadata.

Every accepted fallback requires an updated [[Firmware-Resource-Map]], core
macro assertions where available, register-configuration tests, and measured
rig evidence in the Phase 06 result record.

## Consequences

- Packed GPIO order and standard-port bit identities can no longer drift from
  the pinned core without a target compile failure.
- Host compilation validates duplicate, range, order, and exact-mask errors
  without depending on Teensy headers.
- The resource assignment is deterministic and reviewable; acquisition code
  cannot silently use a first-free timer, XBAR output, or DMA channel.
- This decision deliberately makes no claim about external pad transitions,
  sustained DMA/cache correctness, or the candidate route's silicon behavior.
  Those claims require the later isolated spike and full Phase 06 gate.
