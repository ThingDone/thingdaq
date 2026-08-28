---
type: reference
title: System Overview
created: 2026-08-27
tags:
  - teensy-daq
  - architecture
  - foundation
related:
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
---

# System overview

Teensy DAQ is split into three independently testable areas:

- `firmware/` owns the Teensy 4.0 Arduino sketch, portable C++ modules,
  repository-local build tooling, and host-side firmware tests.
- `daq_api/` owns an installable Python src-layout package and its tests.
- `doc/` owns structured architecture, protocol, decision, reference, and
  result artifacts.

The intended runtime boundary is a versioned binary protocol carried over the
Teensy 4.0 native USB CDC byte stream. The Python package exposes one
synchronous `TeensyDAQ` facade over a minimal `ByteTransport` interface.
`InMemoryTransport` and `SimulatedDevice` exercise that exact byte boundary,
including partial reads and writes. `SerialTransport` implements bounded
PySerial I/O at the same boundary, while `BackgroundReader` owns incremental
parsing, concurrent request-ID correlation, and bounded decoded block/event
queues. The public facade always uses that reader for INFO, CONFIGURE, START,
GET_STATUS, RESET_STATS, STOP, and streaming; simulator operation has no
parallel decoder or synchronous parsing shortcut. Metadata-first discovery
filters PySerial enumeration for the Teensy
USB Serial VID/PID before opening anything, then validates plausible devices
with a bounded INFO request. Discovery identity comes from the hardware serial,
not the transient COM or `/dev` endpoint, and one inaccessible candidate cannot
abort the rest of a scan. Reopening a discovery result repeats INFO and checks
the selected serial so a hot-reused path fails closed.

The typed surface consists of `DeviceInfo` with nested `DeviceCapabilities`,
`DAQConfiguration`, `Status`, `ADCBlock`, `GPIOBlock`, and `StreamGap`, plus
separate `FirmwareCounters`, `HostCounters`, and `LossCounters`. Reader host
queue drops remain distinct from firmware flags and firmware GET_STATUS
counters. Production iterators emit a visible gap before continuing with the
current block; strict/test mode raises with that gap and block attached. Raw ADC
converter identity, explicit interleaving, and lazy packed-GPIO channel views
require no NumPy dependency. These layers can be swapped without changing the
public state machine or block-streaming calls.

The simulator provides the runnable host-side acquisition model: bounded
BOOT-to-IDLE startup; IDLE, CONFIGURED, and RUNNING transitions; monotonically
allocated run IDs; independent ADC/GPIO sequences; 8 MHz epoch timestamps; and
deterministic synthetic payloads. Wire constants are generated from
`protocol/protocol-v1.json` rather than maintained independently in C++ and
Python. Its in-memory transport grants one data-frame credit per public block
request, keeping offline counters deterministic without bypassing background
reading. See [[Protocol-V1]] for the wire contract,
[[ADR-001-Wire-Protocol]] for its framing decisions, and
[[Foundation-Reuse-Inventory]] for the source and pattern audit. Physical ADC,
GPIO, and USB acquisition remain future firmware work.
