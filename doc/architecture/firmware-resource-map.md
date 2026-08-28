---
type: reference
title: Firmware Resource Map
created: 2026-08-28
tags:
  - teensy-daq
  - teensy-4-0
  - firmware
  - resource-ownership
related:
  - '[[System-Overview]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
---

# Firmware resource map

This is the human-readable projection of the compile-time registry in
`firmware/src/board_config.h`. Numeric allocations are reserved now so future
acquisition modules cannot silently compete. Phase 03 does not enable the PIT,
XBAR, ADC_ETC, or eDMA acquisition path and does not advertise ADC/GPIO stream
support. See [[System-Overview]] for that capability boundary and
[[Protocol-V1]] with [[ADR-001-Wire-Protocol]] for the wire metadata.

## Fixed platform

| Property | Required identity |
| --- | --- |
| Board | Teensy 4.0 (`ARDUINO_TEENSY40`) |
| MCU | NXP i.MX RT1062, Arm Cortex-M7 (`__IMXRT1062__`) |
| CPU | 600,000,000 Hz |
| Core | `teensy:avr` 1.62.0; pinned compile macro `TEENSYDUINO=160` |
| Toolchain | Arm GNU 15.2.1, GNU C++17 |
| USB | USB Serial, `Teensy DAQ` product, legitimate Teensy `0x16C0:0x0483` VID/PID, core-generated chip serial |
| Optimization | `o2std`, standard `-O2` |
| Cache line | 32 bytes |
| RAM1 / RAM2 budget | 512 KiB DTCM / 512 KiB OCRAM |

The build helper and `firmware_identity.h` both fail closed on identities they
can observe. The installed core itself remains unmodified.

## Pin ownership

| Logical use | Teensy pin | Peripheral interpretation | Future owner |
| --- | ---: | --- | --- |
| ADC0 input | A0 / D14 | NXP ADC1 | ADC0 capture |
| ADC1 input | A1 / D15 | NXP ADC2 | ADC1 capture |
| GPIO bit 0 | D6 | GPIO7 fast alias; selectively remap to GPIO2 for DMA | GPIO capture |
| GPIO bit 1 | D7 | Same | GPIO capture |
| GPIO bit 2 | D8 | Same | GPIO capture |
| GPIO bit 3 | D9 | Same | GPIO capture |
| GPIO bit 4 | D10 | Same | GPIO capture |
| GPIO bit 5 | D11 | Same | GPIO capture |
| GPIO bit 6 | D12 | Same | GPIO capture |
| GPIO bit 7 | D13 | Same | GPIO capture |

All ten pin IDs are compile-time range checked against the Teensy 4.0's 40
digital pin IDs and checked for duplicates. The D6-through-D13 array is also
compared byte-for-byte with the generated [[Protocol-V1]] GPIO pin map.

## Timer and trigger reservations

| Resource | Numeric ID | Planned route | Future owner |
| --- | ---: | --- | --- |
| PIT channel | 0 | 24 MHz / 6 candidate for exact 4 MHz GPIO event | GPIO capture |
| PIT channel | 1 | Chained / 4 candidate for exact 1 MHz ADC-pair event | Acquisition clock |
| XBAR input | 56 | `XBARA1_IN_PIT_TRIGGER0` | GPIO capture |
| XBAR input | 57 | `XBARA1_IN_PIT_TRIGGER1`, deliberate fan-out | ADC0 and ADC1 capture |
| XBAR output | 0 | `XBARA1_OUT_DMA_CH_MUX_REQ30` | GPIO capture |
| XBAR output | 103 | `XBARA1_OUT_ADC_ETC_TRIG00` | ADC0 capture |
| XBAR output | 107 | `XBARA1_OUT_ADC_ETC_TRIG10` | ADC1 capture |
| ADC_ETC trigger queue | 0 | NXP ADC1 / logical ADC0 | ADC0 capture |
| ADC_ETC trigger queue | 4 | NXP ADC2 / logical ADC1, planned relative delay | ADC1 capture |

PIT channels, XBAR outputs, ADC_ETC queues, and ADC peripheral ownership must
be unique. Repeated XBAR input 57 is legal because one event intentionally
fans out to two distinct outputs. Core macro assertions guarantee the pinned
numeric XBAR identities have not drifted. `IntervalTimer` or another owner may
not claim PIT0/PIT1 while acquisition is active; an external library conflict
cannot be discovered by a C++ constant alone and must be rejected during
integration review.

The 500 ns ADC phase is metadata, not a hardware claim in this phase. Future
hardware work must prove trigger and aperture timing before enabling either
stream capability.

## eDMA reservations

| eDMA channel | DMAMUX source | Core identity | Future owner |
| ---: | ---: | --- | --- |
| 0 | 24 | `DMAMUX_SOURCE_ADC1` | ADC0 capture |
| 1 | 88 | `DMAMUX_SOURCE_ADC2` | ADC1 capture |
| 2 | 30 | `DMAMUX_SOURCE_XBAR1_0` | GPIO capture |

All eDMA channels must be below 32, all DMAMUX sources below 128, and neither
set may contain duplicates. Pinned core macros are asserted against all three
source numbers. Acquisition code must bind these exact channels rather than
use an unconstrained first-free allocator.

## Queue and per-loop bounds

| Bound | Value | Owner |
| --- | ---: | --- |
| Incremental command parser storage | 64 bytes | Control plane |
| USB receive scratch | 128 bytes | USB transport |
| Complete command queue | 4 frames | Control plane |
| Complete response queue | 4 frames | USB transport |
| ADC DMA ring | 4 buffers | ADC capture |
| Raw GPIO DMA ring | 4 buffers | GPIO capture |
| Packed GPIO ring | 4 buffers | GPIO packer |
| Complete data transmit queue | 4 frames | Packetizer |
| USB receive work per loop | 1,024 bytes | USB transport |
| USB transmit work per loop | 2,048 bytes | USB transport |
| USB read calls per loop | 8 | USB transport |
| USB write calls per loop | 8 | USB transport |

The 64-byte parser capacity covers the generated 56-byte maximum command plus
three possible bytes of the next magic and alignment slack. The separate
128-byte scratch preserves already-read bytes when the complete-command queue
fills. Control responses reserve the generated 1,024-byte defensive maximum
even though current typed responses are smaller. The byte and call limits both
bound each cooperative-loop visit, including a backend that repeatedly returns
short or zero-length operations. These values are capacities, never
heap-growth hints.

## Memory reservations

| Use | Region | Calculation | Reserved bytes | Alignment | Future owner |
| --- | --- | ---: | ---: | ---: | --- |
| Command parser | DTCM / RAM1 | fixed | 64 | 4 | Control plane |
| USB RX scratch | DTCM / RAM1 | fixed | 128 | 4 | USB transport |
| Command queue | DTCM / RAM1 | `4 × 56` | 224 | 4 | Control plane |
| Response queue | DTCM / RAM1 | `4 × 1,024` | 4,096 | 4 | USB transport |
| ADC DMA ring | OCRAM / RAM2 | `4 × align32(4,048)` | 16,256 | 32 | ADC capture |
| Raw GPIO DMA ring | OCRAM / RAM2 | `4 × 4,048 × 4` | 64,768 | 32 | GPIO capture |
| Packed GPIO ring | OCRAM / RAM2 | `4 × align32(4,048)` | 16,256 | 32 | GPIO packer |
| Data transmit queue | OCRAM / RAM2 | `4 × 4,096` | 16,384 | 32 | Packetizer |
| **RAM1 subtotal** |  |  | **4,512** |  |  |
| **RAM2 subtotal** |  |  | **113,664** |  |  |

DMA-visible buffers belong in `DMAMEM` OCRAM/RAM2, begin on 32-byte cache
boundaries, occupy whole cache lines, and require explicit cache maintenance at
ownership transitions. The registry reserves bytes but does not instantiate
these future rings. Compile-time checks reject zero-sized, non-power-of-two,
misaligned, or over-budget allocations.

## Ownership transitions

Future acquisition code must use explicit complete-buffer states:

```text
FREE -> DMA_FILLING -> READY -> PACKING/FRAMING -> QUEUED -> FREE
```

ADC interleaved storage is READY only after both ADC eDMA completions. GPIO raw
storage becomes READY after its eDMA major loop, then moves to a distinct
packed buffer. A complete frame admitted to the USB queue cannot be abandoned
after its first byte is transmitted. Command responses are selected before
unsent data at each frame boundary; a data frame that has already emitted
bytes finishes before a new response. Partial and zero writes retain both
frame ownership and the byte offset for a later bounded loop visit. When an
unsent data queue is full, loss policy operates on whole buffers and reports
counters/gap flags defined by [[Protocol-V1]]. No ISR parses commands,
calculates checksums, writes USB, waits, or performs broad control-state
mutation.
