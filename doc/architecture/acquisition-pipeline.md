---
type: analysis
title: Acquisition Pipeline
created: 2026-08-28
tags:
  - teensy-daq
  - architecture
  - acquisition
  - resource-audit
  - phase-08
related:
  - '[[Firmware-Resource-Map]]'
  - '[[System-Overview]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[Protocol-V1]]'
  - '[[Phase-06-GPIO-DMA]]'
  - '[[Phase-07-Dual-ADC]]'
---

# Acquisition pipeline

## Status and scope

Phase 08 begins with one portable `acquisition::Controller` around the proven
Phase 06 GPIO and Phase 07 ADC engines. It is now the only firmware-runtime
boundary that initializes, preflights, starts, stops, drains, services, and
publishes telemetry for physical acquisition. `FirmwareRuntime` retains the
control protocol, synthetic source, common packet pool, and USB scheduler but
no longer owns per-peripheral lifecycle state or sequencing.

The controller preserves the accepted ADC-only and GPIO-only behavior and now
executes an ADC-plus-GPIO request as one atomic internal resource transaction.
It owns one run ID, one 8 MHz epoch, and one shared hardware schedule across
both paths. [[Protocol-V1]] now advertises and validates the exact hardware and
synthetic ADC-only, GPIO-only, and combined profile matrix, publishes its
complete fixed resource metadata, and exposes the controller/packet/USB
telemetry through INFO and STATUS. Physical acceptance evidence still awaits
the dedicated Phase 08 rig campaign.

## Evidence reinspected

The audit used the checked-in [[Firmware-Resource-Map]], the current target
adapters, the exact linker-verified Phase 07 image, and the accepted physical
results in [[Phase-06-GPIO-DMA]] and [[Phase-07-Dual-ADC]]. It also reinspected
the pinned Teensy core 1.62.0 `IntervalTimer` and `DMAChannel` implementations
and the bundled `OctoWS2811` XBAR/eDMA setup.

| Evidence | Retained conclusion |
| --- | --- |
| [[ADR-003-GPIO-Clock-DMA]] and Phase 06 target results | PIT0 at 24 MHz / 6 produces the verified 4 MHz GPIO master; XBARA1 output 0, DMAMUX 30, and eDMA 2 are the accepted rising-edge path. |
| [[ADR-004-ADC-Trigger-DMA]] and Phase 07 target results | Chained PIT1 divides the same master by four; ADC_ETC queues 0/4 feed fixed eDMA 0/1 and passed 1 MS/s-per-converter capture. |
| Pinned `IntervalTimer.cpp` | It dynamically takes an unused PIT channel and cannot enforce this project's PIT0/PIT1 ownership; it remains excluded. |
| Pinned `DMAChannel.cpp` | Its allocator and priority helpers are dynamic; acquisition continues to bind channels 0, 1, and 2 directly. |
| Pinned `OctoWS2811_imxrt.cpp` | Its selective GPIO remap/cache/TCD patterns remain useful precedent, but it collides with XBAR DMA outputs 0-2 and sources 30/31/94 and cannot coexist. |
| Current packet and ownership modules | The existing fixed packet pool, alternating ready-frame promotion, source-specific sequences, DMA rings, cache transitions, and complete-frame USB continuation are reusable without another buffer layer. |

No new timing or electrical claim is inferred from this code refactor. The
latest target evidence remains the single-source Phase 06/07 campaigns, and
their unstimulated-input limitations still apply.

## One clock tree, distinct data routes

The apparent PIT0 collision is intentional clock sharing. It must have one
schedule owner rather than two independently started timer owners:

```text
24 MHz PERCLK
    |
    +-> PIT0, LDVAL=5, 4 MHz master
         |
         +-> XBARA1 input 56 -> output 0 -> DMAMUX 30 -> eDMA 2
         |                                           -> GPIO2_PSR ring
         |
         +-> chained PIT1, LDVAL=3, 1 MHz pair event
              |
              +-> XBARA1 input 57 -> output 103 -> ADC_ETC 0
              |                                      -> ADC1 -> eDMA 0
              |
              +-> XBARA1 input 57 -> output 107 -> ADC_ETC 4
                                                     -> ADC2 -> eDMA 1
```

GPIO and ADC do not compete for XBAR outputs, ADC_ETC queues, DMAMUX sources,
or eDMA channels. They do share PIT0 configuration and enable state. The ADC
trigger adapter configures the complete stopped PIT0/PIT1 schedule and reuses
`gpio_dma_route_teensy.h` for the 24 MHz root. GPIO standalone operation keeps
its `prepare`-then-PIT0-start convenience path. Combined operation uses the
split GPIO `prepare()` path, which configures the raw ring, cache ownership,
eDMA channel 2, DMAMUX 30, XBAR output 0, and input-safe pin mapping while
leaving PIT0 stopped. The ADC trigger scheduler is then the only schedule
owner.

The documented combined START commit order is:

1. validate the full fixed physical configuration and perform read-only
   resource inspection for both paths;
2. reserve the controller run ID, stream mask, and epoch after verifying the
   common packet epoch;
3. reset both packers to that run ID and epoch;
4. reset and prime the ADC paired-DMA ring and channels 0/1;
5. reset and prime the GPIO raw-DMA ring and channel 2, including XBAR/DMAMUX,
   while PIT0 remains stopped;
6. reload and clear PIT0/PIT1, enable ADC_ETC queues, enable chained PIT1, and
   enable PIT0 last to commit the shared schedule.

Every failure before the final commit unwinds all owners prepared so far,
stops common packet production, and clears the reserved run identity. A failed
final arm performs trigger cleanup before the controller quiesces GPIO DMA,
ADC DMA, both packers, and the packet epoch.

## Compile-time conflict contract

`board::kAcquisitionResourceContract` is the aggregate compile-time result.
The controller copies it into every audit, while `static_assert` prevents an
invalid production contract from compiling.

| Resource class | Compile-time checks | Accepted allocation |
| --- | --- | --- |
| Pins | Board range, duplicate pin/pad/port-bit rejection, exact protocol order, fixed converter tuples | A0/D14, A1/D15, and D6-D13 are disjoint |
| PIT | Range and duplicate channel rejection | PIT0 master and chained PIT1 |
| XBAR | Input/output range and unique output rejection; repeated input fan-out allowed | GPIO output 0; ADC outputs 103/107 |
| ADC_ETC | Queue/peripheral range and uniqueness | Queue 0/ADC1 and queue 4/ADC2 |
| eDMA/DMAMUX | Range plus unique channel/source rejection | ADC 0/24, ADC 1/88, GPIO 2/30 |
| DMA arbitration | Distinct fixed channel priorities | ADC 0/1, GPIO 2 |
| NVIC priorities | Complete logical allocation, equal ADC generation/error priority, ADC before GPIO | production ADC 48; GPIO 64 |
| BOOT diagnostic IRQ | Kept separate from production allocation and required to be higher urgency | ADC completion diagnostic 32; disabled before production ownership |
| DMA memory | Nonzero power-of-two alignment, unique use, RAM1/RAM2 budgets, DMA destinations in OCRAM | ADC/raw-GPIO rings, sinks, and TCD banks in RAM2 |
| Cache regions | Every DMA/cache-sensitive allocation occupies complete 32-byte lines | DMA rings/sinks/TCDs, packet banks, packed GPIO, diagnostic and checksum buffers |

Host compile tests include negative contracts for duplicate interrupt users,
unsafe IRQ ordering, a reused eDMA arbitration priority, a DMA ring placed in
DTCM, and an under-aligned cached ring. Existing negative tests continue to
cover every pin, PIT, XBAR, ADC_ETC, eDMA, DMAMUX, size, and alignment
collision.

## Runtime atomic preflight

`Controller::inspect(configuration, next_run_id)` performs no arm, route,
cache, DMA, or timer write. For every requested physical source it checks:

1. a recognized hardware-only stream profile, exact fixed frame size, and
   supported data checksum;
2. a nonzero prospective run ID and the complete static contract above;
3. controller active, draining, and start-reservation state;
4. presence of the capture, packer, and trigger components;
5. stopped/ready ADC trigger evidence;
6. packer quiescence;
7. each target facade's read-only `inspectStart()` result.

The target facade checks cover live PIT/ADC_ETC activity and ADC conversion
state, eDMA request bits, ADC DMA enables, DMAMUX enables, the GPIO XBAR request
state, raw-ring quiescence, and nonzero ADC epoch. A resource-busy result is
projected into the existing per-source conflict counter. For a combined plan,
both engine inspections always run and either failure rejects the whole audit
before the controller reserves or mutates an owner. Immediately before START,
the controller also verifies that packet production already owns the same run
ID and requested checksum.

## Controller ownership

The controller composes storage-owning modules rather than replacing them:

```text
ControlState START event
    -> common PacketBufferPipeline epoch
    -> acquisition::Controller
         -> ADC packer -> paired ADC DMA ring -> ADC trigger scheduler
         -> GPIO packer -> raw GPIO DMA ring
    -> fair ready-frame promotion
    -> response-first CDC transport
```

For single-source and internally executable combined runs, the controller
preserves these invariants:

- one nonzero run ID is the DMA ownership epoch and packet run identity;
- packer and DMA storage are armed before a source trigger is enabled;
- ADC STOP requests a paired DMA boundary, disables the trigger schedule, then
  tears down DMA;
- GPIO STOP retains its accepted complete-boundary behavior and restores input
  safety;
- combined STOP and fault disable the shared PIT/ADC_ETC source first, quiesce
  GPIO DMA and restore GPIO inputs, then quiesce ADC DMA;
- complete old-run raw and packed work drains before packet production stops,
  while the capture rings account for and discard only an incomplete active
  DMA buffer;
- CONFIGURE/START remain busy until raw, packed, packet, and USB ownership are
  quiescent;
- raw and packer telemetry is published only when its run ID matches the
  current statistics generation.

The run identity remains reserved through the complete-frame drain and is
cleared only when both source paths are quiescent. Hardware capture faults and
packer source/pipeline faults enter the same source-first stop path. The
runtime then returns protocol state to IDLE and consumes the generated STOP
event in the same cooperative visit, making cleanup retryable without exposing
a stale RUNNING state.

The physical report is now a base of the cooperative runtime report, so all
existing status flags and lifecycle tests remain source compatible while the
sequencing implementation has one owner.

## Combined packet and USB scheduling

The common packet epoch now snapshots the configured stream mask together with
the run ID and checksum. A producer for a disabled stream is rejected before
it can reserve a packet buffer, and the acquisition controller refuses to arm
if its complete requested mask differs from the packet epoch. ADC-only and
GPIO-only runs therefore use the same queues without waiting for an absent
peer, while combined runs enable equal-coverage scheduling.

Each ADC frame and GPIO frame covers exactly 8,096 timestamp ticks. During an
active combined run, ready-frame promotion compares each source's cumulative
`emitted + dropped` frame count. It may promote a source whose accounted
coverage is tied with or behind its peer, which permits at most a one-frame
lead. A counted source drop consumes its independent sequence and fairness
slot, so retained coverage can advance without pretending that the missing
frame existed. At equal coverage the existing rotating preference alternates
ADC and GPIO. Once production stops, the coverage wait is relaxed and every
remaining complete frame drains; STOP cannot strand a legitimate unmatched
tail.

The downstream CDC rules remain unchanged and are shared by synthetic and
physical acquisition:

- a complete ready frame becomes immutable transport ownership before any byte
  is offered to USB;
- once a write accepts a prefix, that frame finishes before any response or
  peer data frame, preserving byte-stream framing;
- queued command responses have priority at the next frame boundary and both
  command and response work remain bounded;
- packet, packed, and raw-ring pressure can discard only work that has not
  begun USB transmission; the later Phase 09 policy selects which complete
  unsent block to discard under a deliberately sustained stall.

Native telemetry keeps independent produced, packed/consumed, framed, emitted,
transmitted, and dropped item/frame counters. `PipelineSnapshot` additionally
derives per-source payload-byte totals and complete framed-byte totals, reports
current/per-source/aggregate queue depths and high waters, and exposes fairness
deferrals and accounted-coverage skew. `TransportSnapshot` supplies the shared
USB byte, partial-write, write-stall, command/response queue, and queue
high-water counters. The nominal model is 4,000,000 payload bytes/s per source
(8,000,000 combined) and 4,047,431 framed data bytes/s per source (8,094,862
combined, rounded to the nearest byte/s). Control-response bytes remain a
separate part of total USB bytes rather than being mislabeled as acquisition
payload.

## Timing model retained for combined work

All time derives from the START snapshot in the advertised 8 MHz domain; no
DMA or interrupt timestamp defines sample time.

| Item | Nominal time |
| --- | --- |
| GPIO byte `m` | `epoch + 2m` ticks |
| ADC pair `n` / ADC0 | `epoch + 8n` ticks |
| ADC1 in pair `n` | `epoch + 8n + 4` ticks |

Thus four GPIO samples cover one ADC pair period, and ADC1 retains its nominal
four-tick phase. These are hardware-schedule relationships from
[[ADR-004-ADC-Trigger-DMA]], not measurements of external pad propagation or
analog aperture. Compile-time assertions require equal ADC/GPIO frame
coverage, the 4:1 GPIO-to-pair period ratio, and the ADC1 half-period phase.
Packers derive each frame timestamp from source completion counters plus the
single START epoch; no ISR entry time participates in a sample timestamp.

## Host timestamp alignment

The Python API keeps independent decoding and delivery as its low-level
contract. `ADCBlock`, `GPIOBlock`, and `StreamGap` therefore leave the reader
queue as soon as the application consumes them; the background reader never
waits for a peer source. The optional `TimestampAligner` composes those typed
objects afterward.

The aligner keys each interval by nonzero run ID and first-sample tick, requires
the fixed 8,096-tick coverage and one physical-or-synthetic source identity,
and emits only monotonically ordered intervals within a run. Its configurable
event-time window holds at most that many unresolved timestamps, permitting
bounded out-of-order delivery. When the watermark passes an unresolved
interval, an `AlignmentLoss` names the missing ADC, GPIO, or both before a
partial `AlignedInterval`; an explicit flush provides the finite timeout/STOP
boundary for the terminal tail. A run change flushes old pending work with a
run-boundary reason and resets both independent sequence expectations. A
source change within one run, duplicate side, late block, invalid coverage, or
inconsistent gap evidence raises a typed alignment error instead of joining
unrelated data.

Per-source continuity remains visible as `StreamGap`, distinct from alignment
loss. The aligned interval also retains those gap objects so a caller cannot
silently concatenate across sequence or timestamp discontinuities. Missing
intervals do not advance source expectations; the next observed block must
therefore independently corroborate the loss in its sequence and timestamp.

No combined sample allocation exists. `AlignedInterval` stores the original
block references and returns memoryviews over their immutable payload bytes.
ADC0/ADC1 channel views and packed GPIO bytes retain their existing layouts.
`NominalEpoch` exposes START-relative tick zero and converts item ticks with the
advertised 8 MHz frequency: ADC pair `n` remains at `t + 8n`, ADC1 at
`t + 8n + 4`, and GPIO byte `m` at `t + 2m`. Its external-latency value remains
explicitly absent because neither GPIO-pad propagation nor ADC aperture
latency has been measured.

## Buffer and cache composition

The controller adds no payload storage. It reuses the four-buffer ADC pair
ring, four-buffer raw GPIO ring, four-buffer packed GPIO ring, isolated sinks,
and the common 200-frame packet pool documented in [[Firmware-Resource-Map]].
READY and TRANSMIT queues contain 400 and 200 one-byte indexes respectively;
the packet buffers change ownership in place rather than being copied into
another payload bank. Compile-time combined buffer totals reserve 440,832
bytes in RAM1 and 486,944 bytes in RAM2. Including the pinned core's four
2,048-byte USB TX buffers brings the simultaneous RAM2 buffer total to 495,136
bytes, still inside the 512 KiB region before the exact linker gate accounts
for all remaining core globals.
The exact pinned combined-lifecycle image uses 455,488 bytes of RAM1 variables,
32,616 bytes of RAM1 code, 152 bytes of alignment padding, and leaves 36,032
bytes for locals/stack. It uses 503,488 bytes of RAM2 variables and leaves
20,800 bytes of heap headroom. Cold controller lifecycle paths and non-measured
checksum-vector preparation remain in flash so the additional orchestration
does not consume another 32 KiB ITCM block.

DMA and CPU ownership remain local to the existing ring state machines. The
controller never receives a mutable DMA pointer and never performs cache
maintenance itself. This preserves the rule that cache deletion/invalidation
occurs only at explicit DMA/CPU ownership transitions and never inside the
cooperative packet or USB layers.

## Remaining combined-enablement work

Combined hardware lifecycle, capability/configuration negotiation, telemetry,
and bounded host monitoring are enabled. Remaining Phase 08 work is the
separate adversarial firmware/Python test expansion, self-contained combined
rig, and 10/60-second physical acceptance campaign. Until that campaign passes,
the profile is implemented and advertised but has no claimed combined target
throughput, loss, or external stimulus evidence.
