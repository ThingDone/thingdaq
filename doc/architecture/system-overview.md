---
type: reference
title: System Overview
created: 2026-08-27
updated: 2026-08-28
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

## Firmware streaming foundation

The Phase 03 control plane and Phase 04 synthetic packet path centralize these
authorities:

| Authority | Responsibility |
| --- | --- |
| `firmware/src/firmware_identity.h` | Product, board, MCU, CPU, core, compiler, USB/menu, semantic firmware, protocol, source, build, and timestamp identity |
| `firmware/src/board_config.h` | The single pin, timer, XBAR, ADC_ETC, eDMA, queue, DMA-memory, alignment, and future-owner registry |
| `firmware/src/firmware_capabilities.h` | The exact INFO metadata projected from generated protocol constants and the resource registry |
| `firmware/src/gpio_clock_diagnostic.{h,cpp}` | Portable exact-rate planning, duration bounds, and dead/duplicate/count-error classification |
| `firmware/src/gpio_clock_diagnostic_teensy.{h,cpp}` | The guarded PIT0/XBARA1/eDMA register adapter and isolated OCRAM sentinel transfer |
| `firmware/src/gpio_capture_diagnostic.{h,cpp}` | Fail-closed fixture-policy selection and capture/safety/validation-coverage classification |
| `firmware/src/gpio_capture_diagnostic_teensy.{h,cpp}` | The guarded input-only production-ring diagnostic for the documentation-only Port 15 fixture |
| `firmware/src/synthetic_source.{h,cpp}` | Deterministic ADC/GPIO formulas, shared epoch, real-time and unpaced-diagnostic scheduling, and bounded source telemetry |
| `firmware/src/packet_buffer_pipeline.{h,cpp}` | Fixed aligned complete-frame storage, explicit ownership transitions, per-source sequences/counters, bounded ready/transmit index queues, and high-water telemetry |
| `firmware/src/usb_transport.{h,cpp}` | Portable bounded CDC receive/transmit scheduling, complete command/response queues, frame ownership, and transport diagnostics |
| `firmware/src/teensy_usb.{h,cpp}` | The narrow Teensy-core byte-stream adapter, product descriptor override, and bridge to the core-generated chip serial number |
| `firmware/src/teensy_clock.{h,cpp}` | The narrow polled Teensy `micros()` to unsigned 64-bit 8 MHz adapter |
| `firmware/src/firmware_runtime.{h,cpp}` | Portable cooperative integration of receive, one-command dispatch, control events, paced generation, counters, and transmit |

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

## Complete-frame packet pipeline

The deterministic synthetic source uses a 200-entry pool of aligned 4,096-byte
frames: 106 in a primary DTCM bank and 94 in an OCRAM reserve bank. The pool is
fixed storage with no steady-path allocation. `beginFill()` assigns the next
independent ADC or GPIO sequence and
records source production before asking for a free buffer, so pool exhaustion
remains visible as both a drop counter and a later sequence gap. Only a valid
fill lease can access the 4,048-byte payload region; the source does not bypass
framing or transport in either pacing mode.

Finalization rejects a short payload, validates the source-specific wire
layout, and constructs the fixed header and Adler-32 trailer in place. Only
then does ownership move from `FILLING` to a bounded per-source `READY` queue.
A bounded alternating service moves complete frames into the transmit-index
queue as immutable `TRANSMITTING` buffers. `CdcTransport` consumes that queue
through the existing lower-priority interface and releases the front buffer
only after all 4,096 bytes succeed. A new response may overtake unsent data at
a boundary, but never an active frame. Starting another run is rejected while
transport owns any frame.

The primary packet bytes live in aligned DTCM/RAM1; the fixed reserve is an
aligned, CPU-owned `DMAMEM` OCRAM/RAM2 bank. Inspection of the pinned Teensy
1.62 `usb_serial.c` confirms that its public block-write path copies application
bytes from either bank into a separate core-owned four-by-2,048-byte OCRAM ring
and flushes that destination before USB DMA. The project's 2,048-byte TX visit
bound matches one core buffer and uses its conservative
`availableForWrite()` signal; a zero or prefix return retains the application
frame and offset. The 200 project buffers cover 101.200 ms at the target framed
rate, with another 1.012 ms in the core ring. The OCRAM reserve was added after
the CRC campaign measured a 60.715 ms service gap beyond the 54.648 ms combined
primary/core coverage. The exact linker gate preserves at least 32 KiB of DTCM
for locals/stack. See
[[Foundation-Reuse-Inventory]] and [[Firmware-Resource-Map]] for the pinned
source audit and compile-time budget.

## Cooperative runtime integration

Static initialization order is explicit at both ownership levels. The sketch
declares the concrete Teensy CDC byte stream, aligned packet storage, and tick
clock before `FirmwareRuntime`. The runtime declares `ControlState` (which owns
`Statistics`), `PacketBufferPipeline`, and `SyntheticSource` before
`CdcTransport` stores references. The pinned Teensy core initializes USB and its chip-derived
serial descriptor before global C++ construction. `setup()` then passes that
numeric serial to the one BOOT → IDLE transition; it never opens a serial
facade, waits for DTR, or emits an unframed byte.

Every `loop()` calls one portable runtime service step in this fixed order:

1. receive at most 1,024 bytes and eight core read calls;
2. dequeue and dispatch at most one complete command when a response slot is
   reserved;
3. preflight START ownership, consume the bounded START-epoch/STOP event mask
   in main-loop context, or run one explicitly requested IDLE-only diagnostic,
   and admit a successful response only after the corresponding resources
   accept it;
4. poll one 8 MHz clock value and generate at most two due synthetic frames;
5. promote at most four complete ready frames into transport ownership; and
6. transmit at most 2,048 bytes and eight core write calls, requesting at most
   one 2,048-byte core buffer per call and avoiding intentional sub-512-byte
   data chunks except exact frame tails.

Valid typed rejections such as INVALID_STATE or UNSUPPORTED_CONFIGURATION are
normal protocol outcomes and leave the prior state atomic. A response encoding
or queue-invariant failure is an internal fault: the runtime clears an
unconsumed START event, signals STOP if work could exist, drops the applied
configuration, and returns to IDLE while retaining run/build/statistics
provenance. It attempts a typed INTERNAL_ERROR response before abandoning the
reserved slot, so a recoverable firmware fault cannot wedge all later command
processing.

STOP halts source admission before the response is queued, cancels only an
incomplete producer-owned fill, and drains complete ready/transport-owned data.
CONFIGURE may proceed during that bounded drain, but START receives typed
`BUSY` until packet ownership is quiescent. BUSY leaves state, run ID,
statistics generation, and epoch untouched. A successful retry first resets
the queues, arms the packet/source epoch, and then queues START success, which
prevents prior-run data from appearing after the acknowledged new epoch.

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

## Phase 06 physical GPIO capabilities

Firmware advertises both `SYNTHETIC_SOURCE` and `HARDWARE_SOURCE`. Synthetic
CONFIGURE accepts every nonempty ADC/GPIO subset; hardware CONFIGURE accepts
only the GPIO stream. Physical ADC, combined physical ADC/GPIO, zero-stream,
and busy-resource requests fail before changing pin or peripheral registers.

Physical START performs a read-only resource/quiescence preflight, snapshots
one 8 MHz epoch, then arms packet storage, the packed ring, raw DMA buffers,
and eDMA descriptors before enabling PIT0 last. STOP disables PIT0, the eDMA
request, DMAMUX, and XBAR DMA output in deterministic reverse order. Complete
old-run work drains under bounded loop budgets, and CONFIGURE/START return
`BUSY` until quiescent; stale DMA interrupts are counted and cannot cross into
the next run.

The optional IDLE-only `GPIO_CLOCK_DIAGNOSTIC` retains its isolated sentinel
transfer. `GPIO_CAPTURE_DIAGNOSTIC` now advertises the fail-closed capture
facade. Its fixture policy cannot be overridden by a host request: prose-only
or absent metadata selects non-driving capture, and only an exact machine-
readable declaration may identify a fixture stimulus or authorize an output
sweep. The current Port 15 declaration is prose-only, so the adapter captures
one production-rate raw buffer, analyzes 256 words, reports register/count and
packed-value evidence, drains every lease, and restores D6-D13 as GPIO2 inputs.
[[ADR-003-GPIO-Clock-DMA]] records the fixed hardware route.

One successful START allocates the next nonzero run ID and captures one shared
clock reading. Data timestamps are unsigned 64-bit 8 MHz ticks relative to that
epoch: each stream begins at zero and every frame covers 8,096 ticks. ADC frames
contain 1,012 little-endian `(ADC0, ADC1)` pairs where `ADC0[n] = 2n` and
`ADC1[n] = 2n + 1` modulo 12 bits. ADC0 is at each pair timestamp and ADC1 has
the advertised four-tick phase. GPIO frames contain 4,048 samples where
`GPIO[m] = m mod 256`; bits zero through seven correspond to D6 through D13.
Independent stream sequences, formula indexes, and timestamps continue across
every frame boundary and reset only at the next START.

The normal `realtime` source waits until a full frame's logical samples are due
at the advertised rates. `unpaced-diagnostic` is a separate explicit mode for
throughput headroom work; it removes only the deadline and waits on fixed-buffer
backpressure instead of fabricating unscheduled drops. Both modes execute the
same payload builder, in-place frame/checksum encoder, ownership queues, and
CDC transport. No pacing ISR is installed: the narrow Teensy clock adapter
extends cooperative `micros()` deltas and the portable source polls it once per
loop.

The detailed statistics snapshot distinguishes successful and rejected
commands, parser/transport failures, and exact per-stream generated, framed,
emitted, transmitted, and dropped frame/item totals. Protocol-v1 GET_STATUS
also publishes GPIO captured/packed/framed/transmitted sample counts, raw and
packed losses, ring overruns, queue depths/high-water marks, resource
conflicts, lifecycle errors, and stale DMA completions. Every counter
saturates, and a successful START or RESET_STATS advances the nonzero
statistics generation.

## Host architecture

The Python package exposes one synchronous `TeensyDAQ` facade over a minimal
`ByteTransport` interface. `InMemoryTransport` and `SimulatedDevice` exercise
that exact byte boundary, including partial reads and writes. `SerialTransport`
implements bounded PySerial I/O, while `BackgroundReader` owns incremental
parsing, concurrent request-ID correlation, and bounded decoded block/event
queues. Its optional `readinto` fast path reuses one 64 KiB receive buffer;
the default 512-frame decoded queue remains bounded while covering a full
large read and ordinary command-response jitter. Per-source receive/drop and
queue/parser high-water telemetry makes that storage policy measurable. The
public facade uses the same reader for INFO, CONFIGURE, START, GET_STATUS,
STOP, RESET_STATS, and streaming; simulator operation has no parallel decoder
or synchronous parsing shortcut.

Metadata-first discovery filters PySerial enumeration for the legitimate
Teensy USB Serial VID/PID before opening anything, then validates plausible
devices with bounded INFO. Discovery identity comes from the chip-derived
hardware serial, not the transient COM or `/dev` endpoint. Reopening a result
uses a throwaway INFO followed by an authoritative identity-equal INFO and
checks the protocol, Phase 03-or-newer semantic firmware, source-derived build
ID, board/MCU pair, and hardware serial. Reset noise plus timeout/BOOT/BUSY
retries remain explicitly bounded, and a hot-reused path or changed image
fails closed before any state-changing operation.

`DAQConfiguration.control_only()` and
`TeensyDAQ.configure_control_only()` remain available for probing Phase 03
images; current firmware rejects that legacy profile in favor of nonempty
synthetic or GPIO-only physical acquisition. `TeensyDAQ.simulated(control_only=True)` continues to
exercise the older schema. The
`teensy-daq` command-line entry point lists candidates, probes identity, prints
status, configures the advertised physical GPIO profile (with a legacy
control-only fallback), starts, stops, and resets safe counters. Its one-shot
configure/start commands deliberately close the PySerial handle without STOP
so state persists across invocations; normal context-manager cleanup retains
the safe STOP-on-close policy.

The typed surface consists of `DeviceInfo` with nested `DeviceCapabilities`,
`DAQConfiguration`, `Status`, `ADCBlock`, `GPIOBlock`, and `StreamGap`, plus
separate `FirmwareCounters`, `HostCounters`, and `LossCounters`. Reader queue
drops remain distinct from firmware GET_STATUS counters. Production iterators
emit a visible gap before continuing; strict mode raises with the gap and
current block attached. Synthetic strict mode additionally checks full payload
formulas in bulk cyclic views, parser health, and explicit firmware/host
counters without requiring NumPy. `run_synthetic_soak()` layers bounded
duration/frame-count execution over the same synchronous API and reports
payload versus framed throughput, command latency percentiles, queue/parser
and Python-allocation high-water marks, graceful STOP/final STATUS, and exact
firmware-to-wire-to-consumer reconciliation.

The simulator and firmware now share the deterministic acquisition formulas,
run/sequence semantics, and 8 MHz epoch timestamps. The simulator may still
offer different buffering and demand-generation behavior; firmware acceptance
must exercise the real fixed packet and CDC path.

## Runtime ownership rule

The cooperative main loop owns synthetic pattern construction, command parsing,
response encoding, state mutation, checksums, queue ownership, and USB writes.
`ControlState` exposes only compact START-epoch and STOP event bits. Future
physical-acquisition ISRs may only acknowledge hardware, rotate explicitly
owned buffers, update bounded counters, and signal work. They must not build
patterns, parse, checksum, write USB, wait, or perform broad state changes.
This keeps the control plane responsive when the reserved resources in
[[Firmware-Resource-Map]] are eventually enabled.
