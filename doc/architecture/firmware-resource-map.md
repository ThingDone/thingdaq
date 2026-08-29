---
type: reference
title: Firmware Resource Map
created: 2026-08-28
updated: 2026-08-29
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
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[Acquisition-Pipeline]]'
---

# Firmware resource map

This is the human-readable projection of the compile-time registry in
`firmware/src/board_config.h`. Numeric allocations are fixed so acquisition
modules cannot silently compete. Phase 06 has silicon-verified the isolated
PIT/XBAR/eDMA clock path in [[ADR-003-GPIO-Clock-DMA]] and advertises its
IDLE-only diagnostic plus the integrated physical GPIO path. Phase 07 fixes
the complete logical-converter routes and implements their PIT/XBAR/ADC_ETC
schedule, stopped arm/teardown, bounded completion-timing diagnostic, fixed
dual-eDMA TCDs, cache-safe paired ring, cooperative frame packer, and
START/STOP integration in [[ADR-004-ADC-Trigger-DMA]]. Firmware now accepts
either ADC-only or GPIO-only physical acquisition while keeping combined
physical ownership disabled. The existing synthetic generators use the same
packet/checksum queues without claiming physical acquisition resources. See
[[System-Overview]] for the lifecycle boundary and [[Protocol-V1]] with
[[ADR-001-Wire-Protocol]] for the wire metadata.

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

| Logical use | Teensy pin | Peripheral interpretation | Owner |
| --- | ---: | --- | --- |
| ADC0 input | A0 / D14 | `GPIO_AD_B1_02`, NXP ADC1 channel 7 | ADC0 capture |
| ADC1 input | A1 / D15 | `GPIO_AD_B1_03`, NXP ADC2 channel 8 | ADC1 capture |
| GPIO bit 0 | D6 | GPIO7 bit 10; selectively remap to GPIO2 bit 10 | GPIO capture |
| GPIO bit 1 | D7 | GPIO7 bit 17; selectively remap to GPIO2 bit 17 | GPIO capture |
| GPIO bit 2 | D8 | GPIO7 bit 16; selectively remap to GPIO2 bit 16 | GPIO capture |
| GPIO bit 3 | D9 | GPIO7 bit 11; selectively remap to GPIO2 bit 11 | GPIO capture |
| GPIO bit 4 | D10 | GPIO7 bit 0; selectively remap to GPIO2 bit 0 | GPIO capture |
| GPIO bit 5 | D11 | GPIO7 bit 2; selectively remap to GPIO2 bit 2 | GPIO capture |
| GPIO bit 6 | D12 | GPIO7 bit 1; selectively remap to GPIO2 bit 1 | GPIO capture |
| GPIO bit 7 | D13 | GPIO7 bit 3; selectively remap to GPIO2 bit 3 | GPIO capture |

All ten pin IDs are compile-time range checked against the Teensy 4.0's 40
digital pin IDs and checked for duplicates. The D6-through-D13 array is also
compared byte-for-byte with the generated [[Protocol-V1]] GPIO pin map. The
standard-port bits are independently range/duplicate checked, compile-time
matched to the pinned `CORE_PIN*_BIT` values, and combined into the exact
GPIO2/GPR27 mask `0x00030C0F`. Arduino target builds fail closed unless they
identify a Teensy 4.0 with an i.MX RT1062.

Both NXP ADC modules can see A0 and A1, so pin validity cannot select a
converter. The compile-time `AdcConverterConfiguration` table additionally
locks logical ID, Teensy ADC-library module, pad, NXP peripheral/input channel,
ADC_ETC queue, XBAR route, eDMA channel/source, and owner in one tuple. Host
tests reject missing tuples, crossed ADC_ETC queues, and duplicate DMA owners;
exact-value assertions prevent a legal-but-wrong A0/A1 swap.

## Timer and trigger reservations

| Resource | Numeric ID | Planned route | Owner |
| --- | ---: | --- | --- |
| PIT channel | 0 | 24 MHz / 6, verified exact 4 MHz GPIO event | GPIO capture |
| PIT channel | 1 | Chained from PIT0 with `LDVAL=3`; selected exact 1 MHz ADC-pair event | Acquisition clock |
| XBAR input | 56 | `XBARA1_IN_PIT_TRIGGER0` | GPIO capture |
| XBAR input | 57 | `XBARA1_IN_PIT_TRIGGER1`, deliberate fan-out | ADC0 and ADC1 capture |
| XBAR output | 0 | `XBARA1_OUT_DMA_CH_MUX_REQ30`, rising-edge DMA | GPIO capture |
| XBAR output | 103 | `XBARA1_OUT_ADC_ETC_TRIG00` | ADC0 capture |
| XBAR output | 107 | `XBARA1_OUT_ADC_ETC_TRIG10` | ADC1 capture |
| ADC_ETC trigger queue | 0 | NXP ADC1 / logical ADC0, async raw initial delay 0 | ADC0 capture |
| ADC_ETC trigger queue | 4 | NXP ADC2 / logical ADC1, async raw initial delay 75 | ADC1 capture |

The accepted GPIO route is 24 MHz PERCLK to PIT0 with `LDVAL=5`, then XBARA1
input 56 to rising-edge-only output 0 and DMAMUX source 30. Six timer clocks
give the exact 4 MHz event. Final-image hardware job
`db75db1e-45c0-4f66-a09a-bb4adee26b77` passed 1 kHz, 1 MHz, and three repeated
4 MHz windows; each production window had 8,192 samples for 8,193
DWT-scheduled boundaries, within the explicit one-event tolerance, and zero
hardware/eDMA errors. [[ADR-003-GPIO-Clock-DMA]] records the rejected
dual-edge routes and retained fallback order.

PIT channels, XBAR outputs, ADC_ETC queues, and ADC peripheral ownership must
be unique. Repeated XBAR input 57 is legal because one event intentionally
fans out to two distinct outputs. Core macro assertions guarantee the pinned
numeric XBAR identities have not drifted. `IntervalTimer` or another owner may
not claim PIT0/PIT1 while acquisition is active; an external library conflict
cannot be discovered by a C++ constant alone and must be rejected during
integration review.

OctoWS2811 also owns XBARA1 outputs 0-2 and DMAMUX sources 30/31/94 when used;
it is a reviewed pattern source and cannot coexist with this acquisition map.

[[ADR-004-ADC-Trigger-DMA]] records the implemented but not yet
silicon-verified ADC schedule.
Chained PIT1 divides the verified 4 MHz PIT0 event by four. In the 150 MHz
ADC_ETC/IPG domain with predivider zero, raw initial delays 0 and 75 become
effective delays of 1 and 76 cycles; their difference is exactly 75 cycles, or
500 ns. This four-tick phase is digital trigger/timestamp metadata, not a
physical aperture claim. The BOOT diagnostic records the first ADC_ETC
conversion-completion status transitions against DWT under a bounded,
interrupt-masked poll, accepts an explicit 300 ± 120 cycle completion delta,
and exposes configured registers, counts, and errors in INFO/STATUS. Later
hardware work must still keep completion timing separate from analog aperture
before making a physical analog-timing claim.

## eDMA reservations

| eDMA channel | DMAMUX source | Core identity | Owner |
| ---: | ---: | --- | --- |
| 0 | 24 | `DMAMUX_SOURCE_ADC1` | ADC0 capture |
| 1 | 88 | `DMAMUX_SOURCE_ADC2` | ADC1 capture |
| 2 | 30 | `DMAMUX_SOURCE_XBAR1_0` | GPIO capture |

All eDMA channels must be below 32, all DMAMUX sources below 128, and neither
set may contain duplicates. Pinned core macros are asserted against all three
source numbers. Acquisition code must bind these exact channels rather than
use an unconstrained first-free allocator. ADC0/ADC1 use fixed priority values
2/1, above GPIO's priority 0, use NVIC priority 48, and each own eight 32-byte
generation-indexed scatter/gather TCDs. Channel 0 reads `ADC1_R0` and channel 1 reads `ADC2_R0`;
both transfer 16-bit results with `NBYTES=2`, `BITER=CITER=1,012`, and
`DOFF=4` for consumer buffers. Both completion IRQs and the production
ADC_ETC error IRQ share priority 48. Only the later ADC1 completion line
dispatches; after a bounded flag-reconciliation wait, its handler identifies
the active entry in a four-generation prelinked pipeline from `DADDR` and
`DLASTSGA`, then consumes every inferred paired generation once in fixed
ADC0-to-ADC1 order. Runtime updates touch only descriptors at least two
generations ahead, never the active hardware TCD link. ADC0's NVIC line remains
reserved but masked.

## Queue and per-loop bounds

| Bound | Value | Owner |
| --- | ---: | --- |
| Incremental command parser storage | 64 bytes | Control plane |
| USB receive scratch | 128 bytes | USB transport |
| Complete command queue | 4 frames | Control plane |
| Complete response queue | 4 frames | USB transport |
| ADC DMA ring | 6 buffers | ADC capture |
| ADC DMA pressure sink | 1 isolated cache line shared at distinct halfwords | ADC capture |
| ADC scatter/gather TCDs | 2 channels × 8 descriptors | ADC capture |
| ADC DMA generations consumed per loop | 2 buffers; up to all 6 while stopping | ADC packer |
| Raw GPIO DMA ring | 4 buffers | GPIO capture |
| Raw GPIO pressure sink | 1 isolated cache line | GPIO capture |
| Raw GPIO scatter/gather TCDs | 5 descriptors | GPIO capture |
| Packed GPIO ring | 4 buffers | GPIO packer |
| Raw batches consumed per loop | 2 buffers | GPIO packer |
| Packed frames finalized per loop | 2 frames | GPIO packer / packetizer |
| Aligned complete-frame packet pool | 105 DTCM + 95 OCRAM = 200 × 4,096-byte buffers | Packetizer |
| Per-source ready queues | 200 ADC + 200 GPIO one-byte indexes (400 bytes); shared pool limits actual ownership to 200 | Packetizer |
| Complete-frame transmit queue | 200 one-byte indexes (200 bytes) | Packetizer / USB transport |
| Synthetic generation per loop | 2 complete frame attempts | Synthetic source |
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
fills. Control responses reserve the generated 1,280-byte defensive maximum
even though current typed responses are smaller. The byte and call limits both
bound each cooperative-loop visit, including a backend that repeatedly returns
short or zero-length operations. Data writes wait for one 512-byte high-speed
USB packet of reported capacity and are offered in blocks up to the core's
2,048-byte TX buffer; exact smaller control frames/tails are allowed, while
unexpected prefixes remain owned for continuation. These values are capacities,
never heap-growth hints.

At the nominal combined framed rate, one 4,096-byte application buffer covers
0.506 ms. The 200-frame pool therefore retains 101.200 ms of complete frames,
and the pinned core's 8,192-byte TX ring contributes 1.012 ms more. Its
105-frame DTCM primary retains 53.130 ms and its 95-frame OCRAM reserve retains
48.070 ms; together they cover the 60.715 ms service gap observed by the Phase
05 CRC campaign. Linker verification
still requires at least 32 KiB of DTCM for locals/stack, and no queue can grow at
runtime. Normal real-time mode admits only coverage intervals elapsed on the
shared 8 MHz epoch. The explicitly selected unpaced diagnostic remains bounded
to two frames per service call and waits when no packet buffer is free.

## Memory reservations

| Use | Region | Calculation | Reserved bytes | Alignment | Owner |
| --- | --- | ---: | ---: | ---: | --- |
| Command parser | DTCM / RAM1 | fixed | 64 | 4 | Control plane |
| USB RX scratch | DTCM / RAM1 | fixed | 128 | 4 | USB transport |
| Command queue | DTCM / RAM1 | `4 × 56` | 224 | 4 | Control plane |
| Response queue | DTCM / RAM1 | `4 × 1,280` | 5,120 | 4 | USB transport |
| Primary packet buffers | DTCM / RAM1 | `105 × 4,096` | 430,080 | 32 | Packetizer |
| Packet records, queue indexes, and telemetry | DTCM / RAM1 | compile-time ceiling | 8,192 | 32 | Packetizer |
| GPIO packer state and telemetry | DTCM / RAM1 | compile-time ceiling | 2,048 | 32 | GPIO packer |
| ADC packer state and telemetry | DTCM / RAM1 | compile-time ceiling | 512 | 8 | ADC packer |
| ADC DMA ring | OCRAM / RAM2 | `6 × align32(4,048)` | 24,384 | 32 | ADC capture |
| ADC DMA pressure sink | OCRAM / RAM2 | one isolated cache line | 32 | 32 | ADC capture |
| ADC TCD banks | OCRAM / RAM2 | `2 × 8 × 32` | 512 | 32 | ADC capture |
| Raw GPIO DMA ring | OCRAM / RAM2 | `4 × 4,048 × 4` | 64,768 | 32 | GPIO capture |
| Raw GPIO pressure sink | OCRAM / RAM2 | one isolated cache line | 32 | 32 | GPIO capture |
| Raw GPIO TCD bank | OCRAM / RAM2 | `5 × 32` | 160 | 32 | GPIO capture |
| Packed GPIO ring | OCRAM / RAM2 | `4 × align32(4,048)` | 16,256 | 32 | GPIO packer |
| GPIO clock diagnostic sink | OCRAM / RAM2 `.dmabuffers` | one isolated cache line | 32 | 32 | GPIO capture |
| Packet-buffer reserve | OCRAM / RAM2 `.dmabuffers` | `95 × 4,096` | 389,120 | 32 | Packetizer |
| Checksum benchmark DTCM buffer | DTCM / RAM1 | `1 × 4,096` | 4,096 | 32 | Checksum benchmark |
| Checksum benchmark OCRAM buffer | OCRAM / RAM2 `.dmabuffers` | `1 × 4,096` | 4,096 | 32 | Checksum benchmark |
| **RAM1 subtotal** |  |  | **450,464** |  |  |
| **RAM2 subtotal** |  |  | **499,392** |  |  |

The simultaneous combined-acquisition subset is 440,832 RAM1 bytes for the
primary packet bank, packet records/index queues, and both packer-state budgets,
plus 495,264 RAM2 bytes for the reserve packet bank and all ADC/raw-GPIO/packed
GPIO DMA storage. Adding the pinned core's 8,192-byte USB TX ring makes the
combined RAM2 buffer footprint 503,456 bytes. Compile-time assertions enforce
all three totals against their real memory regions; the linker/map gate remains
authoritative for unrelated core globals and final stack/heap headroom.

The application packet pool is split between an aligned ordinary-global DTCM
primary and an aligned `DMAMEM` OCRAM reserve. Both are CPU-owned; Teensy USB
Serial copies from either bank into its separate core-owned TX ring and flushes
that destination before USB DMA. The raw GPIO ring, pressure sink, TCD bank,
and packed GPIO ring are distinct `.dmabuffers` allocations. The ADC pair
ring, pressure sink, and two TCD banks are likewise concrete `.dmabuffers`
allocations. Raw ownership uses explicit cache maintenance; the packed ring
remains CPU-owned and cached.
Compile-time checks bind the two packet banks to 819,200 total bytes, cap
pipeline metadata at 8,192 bytes, GPIO packer state at 2,048 bytes, and ADC
packer state at 512 bytes, and
reject zero-sized, non-power-of-two, misaligned, or over-budget registry
entries. The build manifest additionally checks the linked addresses and sizes
of both packet banks, the isolated GPIO clock diagnostic cache line, all three
ADC DMA allocations, all three raw GPIO DMA allocations, and the four-buffer
packed ring.

The optional IDLE-only checksum benchmark owns no PIT, XBAR, ADC_ETC, eDMA, or
USB resource. Its ordinary global buffer is link-verified inside DTCM; its
`.dmabuffers` global is link-verified inside DMA-visible OCRAM. Both are exact,
isolated 4,096-byte allocations so a whole-line cache invalidation cannot harm
another owner. The DWT counter is enabled without resetting it, each timed
interval restores the prior interrupt mask, and no benchmark work overlaps an
acquisition epoch. The build manifest records both addresses and the combined
8,192-byte working set.

The optional GPIO clock diagnostic owns PIT0, XBARA1 input 56/output 0,
DMAMUX source 30, and eDMA channel 2 only while IDLE. Its 32-byte aligned
`.dmabuffers` cache line contains a fixed source sentinel and fixed destination
word, so each event proves the trigger/count path without touching a pad or
the raw GPIO ring. The diagnostic disables PIT, eDMA requests, DMAMUX,
and XBAR DMA generation before returning its read-only snapshot.

The advertised autonomous GPIO capture diagnostic adds no DMA buffer or
peripheral reservation. It runs only when the same raw-capture owner is
quiescent, reuses the production PIT0/XBARA1/eDMA channel 2 route and raw ring,
and leases at most 256 words from one complete buffer for observation. The
registered Port 15 fixture supplies documentation only—not an output-safety,
loopback, or stimulus declaration—so this adapter has no output-register path.
It snapshots GPR27/GDIR/PSR and DMA state before, during, and after capture;
stops and drains the ring; and verifies D6-D13 remain standard GPIO2 inputs
before IDLE.

## Ownership transitions

The implemented packet pipeline uses explicit complete-buffer states:

```text
FREE -> FILLING -> READY -> TRANSMITTING -> FREE
```

Only `FILLING` exposes the 4,048-byte payload as mutable. Finalization validates
the exact payload count and writes the header plus checksum in place before a
buffer can enter its source's bounded `READY` queue. For a combined epoch,
bounded promotion uses each source's equal-duration `emitted + dropped`
coverage and a rotating tie-break so a retained source can lead its peer by at
most one frame; counted missing intervals consume fairness slots without
changing the independent sequences. Single-source epochs skip the peer wait.
Promotion transfers ownership to the transmit-index queue and makes the frame
immutable. STOP cancels incomplete `FILLING` work, relaxes the active-run
fairness wait, and drains complete `READY` and `TRANSMITTING` frames. START
returns `BUSY` until every prior-run owner is `FREE`; only then are queues and
sequences reset, so a partially emitted frame cannot be abandoned and stale
data cannot cross an acknowledged epoch.
Command responses are selected before unsent data at each frame boundary; an
active data frame finishes first. Partial and zero writes retain both frame
ownership and the byte offset for a later bounded loop visit.

The implemented GPIO raw ownership path is:

```text
FREE -> DMA_QUEUED -> DMA_ACTIVE -> READY -> PACKING -> RELEASING -> FREE
```

One active and one look-ahead destination are always DMA-owned. If no consumer
buffer is `FREE`, the future descriptor selects a separate 32-byte sink with
`DOFF=0`; each 4,048-sample sink completion advances exact capture/loss/overrun
counters while `READY`, `PACKING`, and `RELEASING` buffers remain untouched.
Cache deletion occurs before a buffer becomes `FREE` or DMA-owned, and cache
invalidation occurs after it atomically becomes `PACKING`; neither occurs in
the roughly 988 Hz major-loop ISR. STOP disables the hardware first, accounts
a partial active loop from its minor count, restores D6-D13 as GPIO2 inputs,
and leaves complete CPU-owned buffers drainable before restart.

The implemented cooperative GPIO packing path is:

```text
raw PACKING lease -> packed FREE -> FILLING -> READY -> FRAMING -> FREE
                                      |                     |
                                      +-> common packet FILLING -> READY
                                                           -> TRANSMITTING
```

One virtual source acquisition/release pair occurs per raw batch; the hot loop
then operates on contiguous pointers and gathers all eight GPIO2 bits with an
unrolled shift/mask implementation. Canonical 4,048-sample assembly is
independent of raw-buffer boundaries. A complete packed record preserves the
first source-sample index and any preceding raw/packed loss; framing converts
that index to the 8 MHz protocol timebase with exactly two ticks per sample and
uses the packet epoch's run ID, independent GPIO sequence, selected checksum,
and `GAP_BEFORE | OVERRUN_BEFORE` metadata. Complete source drops are inserted
chronologically before the next retained frame so sequence, timestamp, and
counters corroborate one another.

The packed ring is fixed at four CPU-owned OCRAM buffers. If it fills, the
packer consumes and releases later raw leases without allocating or blocking,
counts every discarded source sample, and resumes at the next canonical frame.
Statistics track produced, packed, framed, transmitted, raw-gap, packer-drop,
and packet-drop stages. Projection markers subtract raw/packer losses already
represented by a packet sequence slot, so STATUS never counts one loss twice.
The only raw-word consumer outside the packer is the explicitly named bounded
diagnostic, limited to 256 samples and intentionally lacking a wire encoder.
The fail-closed autonomous runner uses this lease only after stopping one
bounded production-ring capture; it does not add an ownership state or retain
the lease across command dispatch.

The implemented ADC ownership path is:

```text
FREE -> DMA_OWNED -> READY -> READING -> RELEASING -> FREE
                       |
                       +-> DISCARD_PENDING -> RELEASING -> FREE
```

Each scheduled generation assigns the same destination to eDMA channels 0
and 1. Channel 0 writes halfwords at pair offset 0 and channel 1 at offset 2;
both advance four bytes per conversion. One channel completion only sets its
generation bit. The second matching completion atomically makes the buffer
`READY`, unless ADC_ETC/eDMA/mismatch evidence tainted that generation. No
cache operation occurs in either major-loop ISR. CPU acquisition invalidates
the whole aligned buffer only after the dual barrier; release or cooperative
discard deletes the cache lines before `FREE` becomes visible to the ISR.

If all six consumer buffers are owned, both channels rotate to distinct
halfwords in one isolated 32-byte sink with `DOFF=0`. Each paired sink major
loop counts one overrun and exactly 1,012 lost pairs without touching
`READY`/`READING` data. Epoch plus modulo-32-bit DMA generations reject stale
and duplicate completions; a lead beyond one complete major loop taints the
affected bounded schedule while later generations continue. ADC_ETC trigger
errors count overwritten converter results and taint the active generation;
STOP can account unequal partial TCD progress exactly before reclaiming it.

The ADC packetization path is:

```text
raw READING lease -> common packet FILLING -> READY -> TRANSMITTING
                  -> raw RELEASING -> FREE
```

One complete raw generation is exactly one 4,048-byte wire payload, so the
cooperative packer performs one bounded copy without an intermediate ring.
Native little-endian layout preserves ADC0 at pair offset zero and ADC1 at
offset two; compile-time layout and byte-order guards make that assumption
explicit. The raw `first_pair` counter becomes `first_sample_ticks = 8n`,
items remain pairs, and INFO supplies ADC1's additional four-tick phase.
Whole-generation raw gaps consume independent ADC packet sequence slots and
set `GAP_BEFORE | OVERRUN_BEFORE` on the next retained physical frame without
setting `SYNTHETIC`.

Physical ADC START arms packet state and the packer before priming both DMA
channels, then enables PIT/ADC_ETC triggers last. STOP disables triggers before
DMA teardown, drains every complete paired buffer through the selected
checksum and existing queues, and keeps CONFIGURE/START busy until raw, packer,
packet, and transport ownership are all quiescent. DMA leases and packet
records retain the nonzero run epoch, so stale conversions cannot enter a
later run.

GPIO acquisition and packed-frame transitions do not change the packet-pool
contract. No project ISR packs or frames data, calculates checksums, mutates
queues, writes USB, waits, or performs broad control-state mutation. Synthetic
pacing installs no ISR at all: the narrow Teensy adapter polls and extends
`micros()` once per cooperative service step.
