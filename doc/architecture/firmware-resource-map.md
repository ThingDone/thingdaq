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
acquisition modules cannot silently compete. Phase 05 does not enable the PIT,
XBAR, ADC_ETC, or eDMA acquisition path, but it advertises both data layouts
for the CPU-generated synthetic source. The generators and packetizer remain
cooperative and do not claim physical acquisition resources. See
[[System-Overview]] for that boundary and
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

The four-tick (500 ns) ADC1 phase is exact synthetic timestamp metadata, not a
physical aperture claim. Future hardware work must prove trigger and aperture
timing before enabling the physical source capability.

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
| Aligned complete-frame packet pool | 106 × 4,096-byte buffers | Packetizer |
| Per-source ready queues | 106 ADC + 106 GPIO indexes; shared pool limits actual ownership to 106 | Packetizer |
| Complete-frame transmit queue | 106 indexes | Packetizer / USB transport |
| Synthetic generation per loop | 4 complete frame attempts | Synthetic source |
| Ready-to-transmit promotions per loop | 4 frames | Packetizer |
| USB receive work per loop | 1,024 bytes | USB transport |
| USB transmit work per loop | 2,048 bytes | USB transport |
| Maximum USB write request | 2,048 bytes | USB transport / one pinned core TX buffer |
| Minimum admitted write capacity | 512 bytes, or the exact shorter frame tail/control frame | USB transport |
| USB read calls per loop | 8 | USB transport |
| USB write calls per loop | 8 | USB transport |
| Pinned core TX ring (core-owned) | 4 × 2,048 bytes | Teensy USB Serial |

The 64-byte parser capacity covers the generated 56-byte maximum command plus
three possible bytes of the next magic and alignment slack. The separate
128-byte scratch preserves already-read bytes when the complete-command queue
fills. Control responses reserve the generated 1,024-byte defensive maximum
even though current typed responses are smaller. The byte and call limits both
bound each cooperative-loop visit, including a backend that repeatedly returns
short or zero-length operations. Data writes wait for one 512-byte high-speed
USB packet of reported capacity and are offered in blocks up to the core's
2,048-byte TX buffer; exact smaller control frames/tails are allowed, while
unexpected prefixes remain owned for continuation. These values are capacities,
never heap-growth hints.

At the nominal combined framed rate, one 4,096-byte application buffer covers
0.506 ms. The 106-frame pool therefore retains 53.636 ms of complete frames,
and the pinned core's 8,192-byte TX ring contributes 1.012 ms more. The
original 96-frame pool exposed loss after Phase 05 clean host receive intervals
reached 53.293 ms. The ten-frame repair remains fixed and linker verification
requires at least 32 KiB of DTCM for locals/stack; no queue can grow at runtime.
Normal real-time mode admits only coverage intervals elapsed on the shared
8 MHz epoch. The explicitly selected unpaced diagnostic remains bounded to four
frames per service call and waits when no packet buffer is free.

## Memory reservations

| Use | Region | Calculation | Reserved bytes | Alignment | Future owner |
| --- | --- | ---: | ---: | ---: | --- |
| Command parser | DTCM / RAM1 | fixed | 64 | 4 | Control plane |
| USB RX scratch | DTCM / RAM1 | fixed | 128 | 4 | USB transport |
| Command queue | DTCM / RAM1 | `4 × 56` | 224 | 4 | Control plane |
| Response queue | DTCM / RAM1 | `4 × 1,024` | 4,096 | 4 | USB transport |
| Complete packet buffers | DTCM / RAM1 | `106 × 4,096` | 434,176 | 32 | Packetizer |
| Packet records, queue indexes, and telemetry | DTCM / RAM1 | compile-time ceiling | 4,160 | 32 | Packetizer |
| ADC DMA ring | OCRAM / RAM2 | `4 × align32(4,048)` | 16,256 | 32 | ADC capture |
| Raw GPIO DMA ring | OCRAM / RAM2 | `4 × 4,048 × 4` | 64,768 | 32 | GPIO capture |
| Packed GPIO ring | OCRAM / RAM2 | `4 × align32(4,048)` | 16,256 | 32 | GPIO packer |
| Checksum benchmark DTCM buffer | DTCM / RAM1 | `1 × 4,096` | 4,096 | 32 | Checksum benchmark |
| Checksum benchmark OCRAM buffer | OCRAM / RAM2 `.dmabuffers` | `1 × 4,096` | 4,096 | 32 | Checksum benchmark |
| **RAM1 subtotal** |  |  | **446,944** |  |  |
| **RAM2 subtotal** |  |  | **101,376** |  |  |

The application packet pool is instantiated now as aligned ordinary global
storage in cacheless DTCM/RAM1. Teensy USB Serial copies from it into the
core-owned aligned `DMAMEM` TX ring and flushes that destination before USB
DMA, so the project must not flush or invalidate packet buffers. Actual
DMA-visible acquisition rings remain future `DMAMEM` OCRAM/RAM2 allocations:
they begin on 32-byte cache boundaries, occupy whole cache lines, and require
explicit cache maintenance at ownership transitions. Compile-time checks bind
the packet storage type to 434,176 bytes, cap pipeline metadata at 4,160 bytes,
and reject zero-sized, non-power-of-two, misaligned, or over-budget registry
entries.

The optional IDLE-only checksum benchmark owns no PIT, XBAR, ADC_ETC, eDMA, or
USB resource. Its ordinary global buffer is link-verified inside DTCM; its
`.dmabuffers` global is link-verified inside DMA-visible OCRAM. Both are exact,
isolated 4,096-byte allocations so a whole-line cache invalidation cannot harm
another owner. The DWT counter is enabled without resetting it, each timed
interval restores the prior interrupt mask, and no benchmark work overlaps an
acquisition epoch. The build manifest records both addresses and the combined
8,192-byte working set.

## Ownership transitions

The implemented packet pipeline uses explicit complete-buffer states:

```text
FREE -> FILLING -> READY -> TRANSMITTING -> FREE
```

Only `FILLING` exposes the 4,048-byte payload as mutable. Finalization validates
the exact payload count and writes the header plus checksum in place before a
buffer can enter its source's bounded `READY` queue. Bounded alternating
promotion transfers ownership to the transmit-index queue and makes the frame
immutable. STOP cancels incomplete `FILLING` work and drains complete `READY`
and `TRANSMITTING` frames. START returns `BUSY` until every prior-run owner is
`FREE`; only then are queues and sequences reset, so a partially emitted frame
cannot be abandoned and stale data cannot cross an acknowledged epoch.
Command responses are selected before unsent data at each frame boundary; an
active data frame finishes first. Partial and zero writes retain both frame
ownership and the byte offset for a later bounded loop visit.

ADC interleaved DMA storage will become ready only after both ADC eDMA
completions. GPIO raw storage will become ready after its eDMA major loop, then
move to a distinct packed buffer. Those future acquisition transitions do not
change the packet-pool contract. No project ISR fills or frames packets,
calculates checksums, mutates queues, writes USB, waits, or performs broad
control-state mutation. Synthetic pacing installs no ISR at all: the narrow
Teensy adapter polls and extends `micros()` once per cooperative service step.
