---
type: reference
title: System Overview
created: 2026-08-27
tags:
  - teensy-daq
  - architecture
  - firmware-control-plane
related:
  - '[[Firmware-Resource-Map]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
---

# System overview

Teensy DAQ has three independently testable areas:

- `firmware/` owns the Teensy 4.0 sketch boundary, portable C++ modules,
  repository-local build tooling, and host-compiled firmware tests.
- `daq_api/` owns the installable Python package, serial adapters, synchronous
  API, simulator, typed models, and host tests.
- `doc/` owns structured architecture, protocol, decision, reference, and
  result artifacts.

The native USB CDC byte stream is the only firmware/host boundary. Both sides
use the generated little-endian contract in [[Protocol-V1]], whose framing
decision is recorded in [[ADR-001-Wire-Protocol]]. USB packet boundaries are
never application frame boundaries.

## Firmware control-plane foundation

Phase 03 introduces three portable, header-only authorities before parser or
control-state implementation:

| Authority | Responsibility |
| --- | --- |
| `firmware/src/firmware_identity.h` | Product, board, MCU, CPU, core, compiler, USB/menu, semantic firmware, protocol, source, build, and timestamp identity |
| `firmware/src/board_config.h` | The single pin, timer, XBAR, ADC_ETC, eDMA, queue, DMA-memory, alignment, and future-owner registry |
| `firmware/src/firmware_capabilities.h` | The exact INFO metadata projected from generated protocol constants and the resource registry |

`firmware/firmware.ino` consumes these authorities and owns only the Arduino
startup boundary. Portable protocol and state code must not grow board or build
constants of its own. [[Firmware-Resource-Map]] records every reservation and
the distinction between present control support and future acquisition work.

The required target is exact:

```text
teensy:avr:teensy40:usb=serial,speed=600,opt=o2std
```

That means Teensy 4.0, i.MX RT1062/Cortex-M7, 600 MHz, USB Serial, standard
`-O2`, Teensy core 1.62.0, GNU C++17, and Arm GNU 15.2.1. The build helper
checks resolved Arduino properties and compiler identity. The firmware header
also rejects a wrong board, MCU, CPU frequency, USB mode, core compile macro,
language mode, unvalidated optimization selection, or compiler major/minor at
compile time. The helper establishes the optimization marker only after the
resolved menu property equals `-O2`.

## Reproducible build identity

`firmware/tools/build_firmware.py` hashes stable relative paths and bytes for
`firmware/firmware.ino`, every non-hidden file under `firmware/src/`, and
`protocol/protocol-v1.json`. The full lowercase SHA-256 is the source ID. The
wire-safe build ID is `tdaq-` followed by the first 16 source-ID digits and is
therefore well inside INFO's 31-ASCII-byte limit.

Build metadata never uses C/C++ `__DATE__` or `__TIME__`. Its UTC timestamp is:

1. `SOURCE_DATE_EPOCH`, when explicitly supplied; otherwise
2. the latest Git commit timestamp affecting the firmware input set.

The helper exports that epoch to the compiler, formats it as
`YYYY-MM-DDTHH:MM:SSZ`, embeds both forms, and records the policy and complete
source input list in the build manifest. Rebuilding the same source with the
same epoch therefore produces identical application build metadata. The
source ID, rather than wall-clock time, is the stale-image compatibility key.

## Truthful Phase 03 capabilities

Phase 03 is control-only. Its capability metadata deliberately reports:

- supported stream mask `0`: neither ADC nor GPIO data exists yet;
- hardware source mask `1` and `HARDWARE_SOURCE`: hardware is the selected
  identity for the milestone's zero-stream configuration;
- `RESET_STATS` and `PING`, which are control-plane features in this phase;
- no `ADC_STREAM`, `GPIO_STREAM`, `SYNTHETIC_SOURCE`, or synthetic data claim;
- Adler-32 support and the generated protocol/frame/command limits;
- the intended 8 MHz timestamp scale, 1 MHz ADC-pair rate, ADC0-at-zero and
  ADC1-at-four-ticks phase convention, 4 MHz GPIO rate, 12-bit samples in
  16-bit containers, and D6-through-D13 bit map as future-layout metadata.

Publishing intended physical layout does not imply stream availability. Host
code must gate configuration on the stream and capability masks, not infer
support from a nonzero rate or a published pin map.

## Host architecture

The Python package exposes one synchronous `TeensyDAQ` facade over a minimal
`ByteTransport` interface. `InMemoryTransport` and `SimulatedDevice` exercise
that exact byte boundary, including partial reads and writes. `SerialTransport`
implements bounded PySerial I/O, while `BackgroundReader` owns incremental
parsing, concurrent request-ID correlation, and bounded decoded block/event
queues. The public facade uses the same reader for INFO, CONFIGURE, START,
GET_STATUS, RESET_STATS, STOP, and streaming; simulator operation has no
parallel decoder or synchronous parsing shortcut.

Metadata-first discovery filters PySerial enumeration for the legitimate
Teensy USB Serial VID/PID before opening anything, then validates plausible
devices with bounded INFO. Discovery identity comes from the chip-derived
hardware serial, not the transient COM or `/dev` endpoint. Reopening a result
repeats INFO and checks that identity so a hot-reused path fails closed.

The typed surface consists of `DeviceInfo` with nested `DeviceCapabilities`,
`DAQConfiguration`, `Status`, `ADCBlock`, `GPIOBlock`, and `StreamGap`, plus
separate `FirmwareCounters`, `HostCounters`, and `LossCounters`. Reader queue
drops remain distinct from firmware GET_STATUS counters. Production iterators
emit a visible gap before continuing; strict mode raises with the gap and
current block attached.

The simulator remains the runnable acquisition model until physical streaming
is implemented. It has bounded BOOT-to-IDLE startup, explicit states,
monotonic run IDs, independent stream sequences, 8 MHz epoch timestamps, and
deterministic synthetic payloads. Its broader simulated capabilities must not
be copied into the Phase 03 physical firmware's capability mask.

## Runtime ownership rule

The cooperative main loop will own command parsing, response encoding, state
mutation, checksums, and USB writes. Future ISRs may only acknowledge hardware,
rotate explicitly owned buffers, update bounded counters, and signal work.
They must not parse, checksum, write USB, wait, or perform broad state changes.
This keeps the control plane responsive when the reserved acquisition
resources in [[Firmware-Resource-Map]] are eventually enabled.
