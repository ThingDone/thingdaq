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

Phase 03 centralizes three portable identity/resource authorities:

| Authority | Responsibility |
| --- | --- |
| `firmware/src/firmware_identity.h` | Product, board, MCU, CPU, core, compiler, USB/menu, semantic firmware, protocol, source, build, and timestamp identity |
| `firmware/src/board_config.h` | The single pin, timer, XBAR, ADC_ETC, eDMA, queue, DMA-memory, alignment, and future-owner registry |
| `firmware/src/firmware_capabilities.h` | The exact INFO metadata projected from generated protocol constants and the resource registry |
| `firmware/src/usb_transport.{h,cpp}` | Portable bounded CDC receive/transmit scheduling, complete command/response queues, frame ownership, and transport diagnostics |
| `firmware/src/teensy_usb.{h,cpp}` | The narrow Teensy-core byte-stream adapter, product descriptor override, and bridge to the core-generated chip serial number |
| `firmware/src/firmware_runtime.{h,cpp}` | Portable cooperative integration of receive, one-command dispatch, control events, fail-safe recovery, and transmit |

`firmware/firmware.ino` consumes these authorities and owns only the Arduino
startup boundary. `firmware/src/firmware_runtime.{h,cpp}` owns the cooperative
main-loop sequence. `firmware/src/protocol.{h,cpp}` owns bounded frame parsing
and encoding, `firmware/src/control_state.{h,cpp}` owns legal post-boot command
dispatch and state transitions, and `firmware/src/statistics.{h,cpp}` owns
saturating diagnostics and statistics generations. Portable protocol and state
code must not grow board or build constants of its own. [[Firmware-Resource-Map]]
records every reservation and the distinction between present control support
and future acquisition work.

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

## USB identity and boot contract

The project supplies the strong `usb_string_product_name` descriptor expected
by the pinned core, encoded as UTF-16 `Teensy DAQ`. It does not replace the
manufacturer, serial descriptor, VID, or PID: USB Serial remains PJRC's
legitimate `0x16C0:0x0483`, and `usb_init_serialnumber()` still derives the
decimal serial string from the i.MX RT1062 fuse. The adapter exposes INFO's
numeric hardware serial by decoding those same core-generated descriptor code
units, so enumeration and protocol identity cannot silently diverge.

Native USB initialization happens before Arduino `setup()`. The sketch does
not call `Serial.begin()`, wait for `Serial`/DTR, or place a startup banner in
the framed command stream. It therefore completes bounded BOOT work even when
no host enumerates or opens the port. The Teensy adapter uses the core's direct
CDC available/read/write-capacity/write functions and never gates command
service on the host-open boolean.

## Bounded CDC transport

`CdcTransport` accepts arbitrary USB chunks into a fixed 128-byte scratch
buffer and feeds the existing incremental parser. Complete decoded commands
enter a four-entry FIFO. A command can leave that FIFO only when one of the
four complete-response slots is reserved, preventing a valid request from
being consumed and then losing its response to queue pressure. Parser
rejection deltas are projected into the shared firmware statistics exactly
once.

Receive and transmit service calls process at most 1,024 and 2,048 bytes,
respectively, and each performs at most eight core read or write calls. A zero
read/write or unavailable endpoint returns control to the cooperative loop
without spinning. Partial writes retain the frame and offset at the queue
front; no other frame may interleave until it completes. At a frame boundary,
queued command responses precede an optional lower-priority data source. If a
data frame has already emitted bytes, it finishes before a newly queued
response, preserving byte-stream framing.

The transport snapshot exposes current/high-water command and response queue
depths, optional lower-priority depth, pending RX and active TX offsets, byte
and call totals, partial/zero operations, I/O errors, budget exhaustion, and
current/consecutive/maximum stall counts. It also counts the last-resort
abandonment of a reserved response slot, which releases command backpressure
only after the runtime cannot encode either the requested response or a typed
INTERNAL_ERROR. Normal no-host backpressure is a stall, not a blocking wait or
a fabricated transport failure.

## Cooperative runtime integration

Static initialization order is explicit at both ownership levels. The sketch
declares the concrete Teensy CDC byte stream before `FirmwareRuntime`, and the
runtime declares `ControlState` (which owns `Statistics`) before `CdcTransport`
stores references to them. The pinned Teensy core initializes USB and its
chip-derived serial descriptor before global C++ construction. `setup()` then
passes that numeric serial to the one BOOT → IDLE transition; it never opens a
serial facade, waits for DTR, or emits an unframed byte.

Every `loop()` calls one portable runtime service step in this fixed order:

1. receive at most 1,024 bytes and eight core read calls;
2. dequeue and dispatch at most one complete command when a response slot is
   reserved;
3. consume the bounded START-epoch/STOP event mask in main-loop context; and
4. transmit at most 2,048 bytes and eight core write calls.

Valid typed rejections such as INVALID_STATE or UNSUPPORTED_CONFIGURATION are
normal protocol outcomes and leave the prior state atomic. A response encoding
or queue-invariant failure is an internal fault: the runtime clears an
unconsumed START event, signals STOP if work could exist, drops the applied
configuration, and returns to IDLE while retaining run/build/statistics
provenance. It attempts a typed INTERNAL_ERROR response before abandoning the
reserved slot, so a recoverable firmware fault cannot wedge all later command
processing.

The end-to-end INFO response carries the protocol version, semantic firmware
version, exact Teensy 4.0 and i.MX RT1062 IDs, core-derived hardware serial,
source-derived build ID, and truthful support masks. A host can therefore
reject a wrong target, incompatible protocol/firmware, unexpected physical
device, stale build, or unsupported operation before sending state-changing
commands.

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

The milestone's sole applied configuration is `{streams=0, source=hardware,
checksum=Adler-32, data_frame_bytes=4096}`. This explicit control-only profile
allows the real firmware to prove CONFIGURE → START → STATUS → STOP without
emitting data or setting ADC/GPIO capability bits. START allocates the next
nonzero run ID, resets the statistics generation and acquisition epoch, and
signals bounded main-loop work. STOP retains the run ID, discards the applied
configuration, and idempotently returns to IDLE.

The detailed statistics snapshot distinguishes successful and rejected
commands, checksum/length/type/version parser failures, invalid-state errors,
transport timeouts, and partial USB writes. Data/parser/transport aggregates
are projected into the fixed v1 GET_STATUS payload; the detailed fields remain
available to tests and later status-schema extensions. Every counter saturates,
and successful START or RESET_STATS clears the snapshot, advances the nonzero
generation, then records that successful command as the first event in the new
generation.

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

The cooperative main loop owns command parsing, response encoding, state
mutation, checksums, and USB writes. `ControlState` exposes only compact
START-epoch and STOP event bits for integration with acquisition. Future ISRs
may only acknowledge hardware, rotate explicitly owned buffers, update bounded
counters, and signal work.
They must not parse, checksum, write USB, wait, or perform broad state changes.
This keeps the control plane responsive when the reserved acquisition
resources in [[Firmware-Resource-Map]] are eventually enabled.
