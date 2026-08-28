---
type: research
title: Foundation Reuse Inventory
created: 2026-08-27
tags:
  - teensy-daq
  - teensy-4-0
  - reuse-audit
  - foundation
related:
  - '[[System-Overview]]'
  - '[[Protocol-V1]]'
---

# Foundation reuse inventory

This audit records the build, USB, protocol, and acquisition patterns reviewed
before the repository scaffold was created. It prevents later work from
silently duplicating a proven local implementation or adopting an incompatible
one.

## Required project sources inspected

| Source | Relevant outcome |
| --- | --- |
| `README.md` | Preserve Teensy 4.0, dual ADC, eight GPIO inputs, USB CDC, native Python API, deterministic test mode, and framed data as product goals. The original byte layout remains an input, not a settled specification. |
| `brainstormed_plan.md` | Use independent firmware/API boundaries, an 8 MHz `uint64` timebase, fixed 4096-byte data frames, bounded commands, per-stream sequences, and a simulator-first vertical slice. |
| `/home/bill/agents/fw_experiments/docs/guides/new-firmware-projects.md` | Compile locally with one exact FQBN and pinned core, export a rig-ready artifact, bound every serial wait, keep the rig test self-contained, and retain deterministic host fixtures. |
| Current repository and history | The repository initially contained only the product-intent `README.md`; no build helper, package, protocol codec, or documentation tree was available to extend. |

## Reusable local patterns

| Area | Source reviewed | Decision |
| --- | --- | --- |
| Arduino build boundary | `/home/bill/agents/fw_experiments/tools/run_fleet.py` and the new-project guide | Reuse the exact `arduino-cli compile` boundary and per-FQBN output isolation concept in a small repository-local helper. Do not vendor the fleet runner, which owns unrelated multi-board and rig policy. |
| Bounded native USB startup | `/home/bill/agents/fw_experiments/experiments/exp000-hello-serial/hello_serial/hello_serial.ino` | Preserve the measured Teensy macros (`ARDUINO_TEENSY40` and `__IMXRT1062__`) and the rule that `Serial` must never be awaited indefinitely. |
| Portable firmware tests | `exp000-hello-serial/raw/common/hello_protocol.c` and `tests/test_hello_protocol.py` | Keep protocol/control modules free of Arduino dependencies where practical and compile the real portable source against a host stub instead of rewriting it in tests. |
| Rig-side serial behavior | `exp000-hello-serial/test_hello_serial.py` | Reuse bounded settle, drain, synchronization, retry, and diagnostic principles when hardware acceptance tests are introduced. Do not copy a hardware test into the offline package suite. |
| USB identity | Teensy 1.62.0 `cores/teensy4/usb_desc.c` and `usb_desc.h` | Override the weak product descriptor in project source when identity is implemented; retain the core-generated hardware serial number and the Teensy-owned `0x16C0:0x0483` USB Serial identity. Never patch the installed core or invent a VID/PID. |
| USB transport pressure | Teensy 1.62.0 `cores/teensy4/usb_serial.c` and `usb_serial.h` | Treat writes as bounded and potentially partial. Use `availableForWrite()`/returned byte counts rather than assuming a whole application frame is accepted atomically. High-speed CDC packets are 512 bytes, but the API remains a byte stream. |
| DMA and cache ownership | Teensy 1.62.0 ADC DMA example, `AnalogBufferDMA.cpp`, and `OctoWS2811_imxrt.cpp` | Reuse `DMAMEM`, 32-byte alignment, explicit cache maintenance, TCD/scatter-gather patterns, selective fast-to-standard GPIO remapping, and XBAR-triggered DMA concepts during hardware phases. Do not copy the examples before ownership and resource allocation are specified. |
| ADC triggering | Teensy 1.62.0 `libraries/ADC/ADC_Module.cpp` | Treat QuadTimer/XBAR/ADC_ETC routing as reference only. Its independently started timers do not provide the required 500 ns phase contract, so later acquisition code must own synchronized timing setup. |

## Protocol search outcome

No nearby project provides a reusable incremental binary parser with the
required version, kind, validated lengths, run identity, per-stream sequence,
8 MHz timestamp, item count, checksum selection, and bounded resynchronization.

`/home/bill/agents/growth/fan_controls.py` was specifically reviewed because it
uses the same `0xDEADBEEF` value. It is intentionally not reused: its sync word
is big endian while other fields are little endian, it uses a simple byte-sum,
and its serial path assumes one fixed-size read returns one response. Teensy
DAQ will instead generate C++ and Python constants from one machine-readable
wire contract and implement an incremental bounded parser in a later task.

## Pinned foundation facts

- Board/core: Teensy 4.0, `teensy:avr` 1.62.0.
- Installed core: `/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0`.
- Installed compiler: Arm GNU 15.2.1 from the Teensy tool bundle.
- Exact planned build target:
  `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`.
- `boards.txt` confirms the `serial`, `600`, and `o2std` menu identifiers map to
  USB Serial, 600 MHz, and `-O2` respectively.
- Arduino CLI observed during the audit: 1.4.1.

These values are recorded here for orientation. The reproducible build helper
and its executable version checks belong to the next build-configuration task.
