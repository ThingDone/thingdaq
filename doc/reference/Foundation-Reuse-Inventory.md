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
  - '[[Firmware-Resource-Map]]'
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

These values are enforced by the reproducible build helper and compile-time
identity checks described in [[System-Overview]].

## Phase 03 reinspection

Before the firmware identity and registry modules were added, the complete
Phase 01-02 repository was reinspected: the sketch and build helper, generated
C++ constants, protocol generator and source contract, Python codec/models,
simulator, transport/reader/client/discovery layers, every Python and firmware
test module, and the structured documentation. No portable C++ protocol or
resource module existed to extend; the reusable authority remains the
generated `protocol_constants.h` rather than copied numeric protocol values.

The pinned and nearby implementation sources were also reinspected on
2026-08-28:

| Source | Reconfirmed implementation constraint |
| --- | --- |
| Teensy 1.62.0 `boards.txt` and `platform.txt` | Teensy 4.0 resolves `ARDUINO_TEENSY40`, `__IMXRT1062__`, `TEENSYDUINO=160`, 600 MHz, USB Serial, GNU C++17, and `-O2`; the build helper must verify the installed package version separately. |
| Teensy 1.62.0 `cores/teensy4/usb_desc.c` / `.h` | USB Serial retains PJRC's `0x16C0:0x0483`; only the weak product descriptor should later be overridden. The core derives the serial string from `HW_OCOTP_MAC0`, so firmware must not replace it. |
| Teensy 1.62.0 `cores/teensy4/usb_serial.c` / `.h` | High-speed CDC packets are 512 bytes; the core uses four 2,048-byte TX buffers and eight RX transfers. Writes can return zero/partial after bounded core waits, so future transport must inspect `availableForWrite()` and returned counts. |
| Teensy 1.62.0 `ADC_Module.cpp` | Its two timer paths use QuadTimer4 channels 0/3, XBAR ADC_ETC outputs 103/107, and trigger queues 0/4, but start independently. Reuse the identities, not its unsynchronized phase behavior. |
| Teensy 1.62.0 `AnalogBufferDMA.cpp` and DMA examples | ADC1/ADC2 DMAMUX sources are 24/88. DMA buffers use `DMAMEM`, 32-byte alignment, and cache invalidation; fixed ownership must replace unconstrained first-free channel allocation. |
| Teensy 1.62.0 `OctoWS2811_imxrt.cpp` | Selective fast-to-standard GPIO remapping and XBAR-triggered DMA remain the proven pattern for future D6-D13 capture. |
| Nearby `exp000-hello-serial` firmware, portable parser, and rig test | Preserve bounded native-USB startup, portable host compilation, finite synchronization/drain windows, and independent graded requests. |

The resulting fixed reservations and compile-time invariants are documented in
[[Firmware-Resource-Map]]. Their presence is not evidence that acquisition is
implemented; [[System-Overview]] defines the Phase 03 control-only capability
mask.

## Phase 04 packet and USB reinspection

Before adding packet storage, the complete Phase 03 firmware closure was
reinspected: `board_config.h`, the portable protocol encoder/decoder,
`CdcTransport`, `FirmwareRuntime`, control events/statistics, the thin sketch,
all host-C++ wrappers, and the Phase 03 local/rig evidence. The existing
`LowerPriorityFrameSource` seam and active-frame byte offset are reused. In
particular, `CdcTransport` already gives a partially written lower-priority
frame immutable ownership until the final byte succeeds, and response priority
applies only at a frame boundary. No second USB scheduler or queue utility was
introduced; the packet pipeline reuses the existing fixed FIFO template.

The exact installed Teensy 1.62.0 sources were then reread at
`/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4`:

| Pinned source | Finding used by Phase 04 |
| --- | --- |
| `usb_serial.c` | USB Serial owns four 2,048-byte TX buffers (`TX_NUM=4`, `TX_SIZE=2048`) and four transfer descriptors. The byte-copy destination is 32-byte-aligned `DMAMEM`; the core calls `arm_dcache_flush_delete()` immediately before `usb_transmit()`. |
| `usb_serial.c` | `usb_serial_write_buffer_free()` deliberately excludes the current TX head and reports only idle non-head buffers. With the project TX visit capped at 2,048 bytes, a positive result is the core's conservative pattern for avoiding its 120 ms fallback wait; zero capacity returns to the cooperative loop. |
| `usb_serial.c` | `usb_serial_write()` may still return zero or a prefix on disconnect/timeout. Therefore the application must retain its frame and byte offset and retry later; it must never infer atomic acceptance from the 4,096-byte application-frame size. |
| `usb_serial.c` / `usb_desc.h` | High-speed CDC packets are 512 bytes, but the core coalesces them in 2,048-byte buffers and its 75 us one-shot flush handles short writes. Application framing remains independent of both sizes. |
| `usb_serial.h` | `availableForWrite()` and the returned count from block `write()` are the only public capacity/progress signals; `flush()` is not a completion fence for host receipt. |

This copy boundary determines the memory rule in [[Firmware-Resource-Map]].
Application packet frames are aligned CPU-owned DTCM/RAM1, because the core
copies them into its own DMA-visible storage. Marking the project pool
`DMAMEM` would consume OCRAM and introduce a cache-ownership story without
enabling zero-copy USB. Future ADC/GPIO rings that are actually read or written
by eDMA remain aligned `DMAMEM` OCRAM/RAM2 and require explicit cache
maintenance. The 64-frame application pool covers about 32.4 ms at the nominal
combined framed rate and retains four 64 KiB host-read batches; the core's
8,192-byte TX ring adds about another 1.0 ms.

The final scheduler therefore caps each request at one 2,048-byte core buffer
and waits for at least 512 bytes of reported capacity (or an exact shorter
control frame/data tail) rather than intentionally issuing byte-at-a-time
writes. Backend-returned prefixes and zero writes retain active-frame ownership.
STOP drains complete work, and the control plane returns BUSY without mutation
until the prior packet run is quiescent; successful START admission occurs only
after the next packet/source epoch is armed.
