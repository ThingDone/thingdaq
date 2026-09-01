---
type: proposal
title: 1 MHz Parallel Output Idea
created: 2026-09-01
updated: 2026-09-01
tags:
  - teensy-daq
  - digital-output
  - dma
  - deferred
related:
  - '[[System-Overview]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Protocol-V1]]'
  - '[[Hardware-Safety]]'
---

# 1 MHz parallel output idea

> [!IMPORTANT]
> This is a deferred design proposal, not an implemented or validated feature.
> Existing firmware drives no user output pins. Every resource assignment,
> timing statement, memory trade, and acceptance criterion below must be
> reviewed against the then-current firmware before implementation.

## Decision summary

Add an optional, preloaded parallel-digital output program that runs at an
exact nominal 1 MHz while the existing physical acquisition remains active:

- ADC0 continues at 1 MS/s on A0/D14.
- ADC1 continues at 1 MS/s on A1/D15, nominally 500 ns after ADC0.
- GPIO D6-D13 continues as an eight-bit input snapshot at 4 MS/s.
- A proposed eight-bit output bank on D16-D23 updates at 1 MS/s.
- Python uploads the complete compact program before `START`; USB and desktop
  scheduling never participate in individual output transitions.
- The program is a sequence of run-length-encoded output states with optional
  finite or infinite whole-program repetition. There are no conditional
  branches or input-dependent transitions.
- Normal completion, explicit `STOP`, or output underrun disables output DMA
  and leaves the pins configured as outputs holding their last driven state.

Simultaneous ADC, GPIO-input, and parallel-output operation is the purpose of
the feature and is therefore a required acceptance gate, not a future
enhancement. Reducing the output rate below 1 MHz is a fallback only if the
combined physical campaign cannot meet the existing loss and timing gates.

## Scope and non-goals

### Initial scope

| Property | Proposed value |
| --- | --- |
| Output type | Parallel push-pull digital GPIO |
| Logical width | 8 bits |
| Proposed pins | D16-D23, logical bit 0 through bit 7 |
| Update rate | Fixed 1,000,000 states/s |
| Time quantum | 1 us, or 8 ticks in the existing 8 MHz timestamp domain |
| Program source | Preloaded from the typed Python API |
| Program form | RLE state segments plus whole-program repetition |
| Start relationship | Same acquisition epoch and hardware master schedule |
| End behavior | Disable DMA and hold the final pin state |
| Runtime host dependency | None after a program has been committed and armed |

### Explicit non-goals for the first implementation

- Arbitrary output rates or per-program clock selection.
- Host-streamed just-in-time samples.
- Conditional branches, input-triggered transitions, or general-purpose bytecode.
- Nested loops or subroutine calls; only whole-program finite/infinite repeat.
- Analog output, PWM synthesis, SPI, UART, I2S, FlexIO, or external-DAC support.
- Output-only runs or output combined with every existing acquisition profile.
  The first executable profile should be physical combined ADC plus GPIO input.
- A guarantee that pins retain their level through MCU reset, power loss, or
  bootloader entry. Those events return pads to reset behavior and are outside
  the software `STOP`/hold contract.

## Why simultaneous operation appears feasible

The current target is a 600 MHz Teensy 4.0 / i.MX RT1062 with 32 eDMA channels.
The central registry reserves only eDMA channels 0, 1, and 2 for ADC0, ADC1,
and GPIO input respectively. PIT0 supplies the exact 4 MHz master event and
PIT1 divides it by four for the exact 1 MHz ADC-pair event. PIT1 already fans
out through XBARA1 input 57 to both ADC_ETC trigger outputs.

The proposed output path adds one 32-bit memory-to-peripheral transfer per
microsecond. Its application-level transfer rate is 4 MB/s from the output
ring, compared with the existing 16 MB/s raw GPIO capture writes and 4 MB/s of
combined ADC result writes. These payload rates do not prove bus margin, but
they make 1 MHz a reasonable first physical target rather than a rate that
should be reduced preemptively.

The output pins are on a different standard GPIO bank from D6-D13. This avoids
direction and data-register overlap with the GPIO input capture. ADC result DMA
requests occur after conversion completion rather than at the PIT1 trigger
instant, further separating the proposed output write from the ADC result
transfers. Actual arbitration latency and jitter remain hardware-measurement
questions.

## Proposed pin profile

The pinned Teensy core maps D16-D23 to the fast GPIO6 aliases of standard
GPIO1. Clearing only their IOMUXC GPR26 fast-GPIO selection bits makes the same
pads visible to eDMA through GPIO1 without changing A0/A1 or any unrelated pin.

| Logical output bit | Teensy pin | GPIO1 bit |
| ---: | ---: | ---: |
| 0 | D16 | 23 |
| 1 | D17 | 22 |
| 2 | D18 | 17 |
| 3 | D19 | 16 |
| 4 | D20 | 26 |
| 5 | D21 | 27 |
| 6 | D22 | 24 |
| 7 | D23 | 25 |

The exact standard-port mask is provisionally `0x0FC30000`. The future
`board_config.h` entry must compile-time check every pin, bit, owner, duplicate,
core macro, and generated protocol mapping in the same style as D6-D13.

Eight pins are the recommended initial public width because they provide a
natural byte-wide Python state and a clean contiguous header-pin group. The
internal wire state can remain a 32-bit mask, with every bit above bit 7
required to be zero, so a later same-bank expansion does not require changing
the basic RLE segment representation.

All pins remain 3.3 V-only. External loads, level translation, contention,
series protection, and fixture authorization must be added to the hardware
safety contract before any physical output test.

## Proposed timing topology

```text
24 MHz PIT clock
    |
    +-- PIT0: divide by 6 -> exact 4 MHz event
            |
            +-- XBARA1 -> eDMA channel 2 -> GPIO2_PSR input capture
            |
            +-- chained PIT1: divide by 4 -> exact 1 MHz event
                    |
                    +-- XBARA1 -> ADC_ETC trigger 0 -> ADC0
                    |
                    +-- XBARA1 -> ADC_ETC trigger 4 -> ADC1 (+500 ns)
                    |
                    +-- XBARA1 output 1 / DMAMUX source 31
                            -> eDMA channel 3
                            -> GPIO1_DR_TOGGLE output update
```

This topology reuses PIT1 rather than reserving another timer. The proposed new
fixed resources are:

| Resource | Proposed ID | Purpose |
| --- | ---: | --- |
| XBARA1 input | 57 | Existing PIT1 event, deliberately fanned out again |
| XBARA1 output | 1 | `XBARA1_OUT_DMA_CH_MUX_REQ31` |
| DMAMUX source | 31 | `DMAMUX_SOURCE_XBAR1_1` |
| eDMA channel | 3 | Output-ring reads and GPIO1 toggle writes |

XBARA1 output 1 shares a control register with the existing GPIO-capture output
0. The target adapter must use deliberate masks/read-modify-write operations so
configuring output 1 cannot alter output 0's accepted rising-edge behavior.
OctoWS2811 uses overlapping XBAR/DMAMUX resources and remains incompatible with
this firmware resource map.

The existing fixed eDMA priority order is ADC0 `2`, ADC1 `1`, GPIO input `0`.
One candidate extension is ADC0 `3`, ADC1 `2`, output `1`, GPIO input `0`, which
preserves the relative acquisition order while inserting output above the GPIO
read. The exact DCHPRI configuration and the behavior of coincident PIT0/PIT1
requests must be proved on silicon. In particular, a physical loopback may see
the new output state in either the nominally coincident GPIO sample or a later
sample depending on DMA arbitration and pad propagation. The protocol must not
promise that phase until it is measured.

### Nominal shared-epoch schedule

| 8 MHz timestamp tick | 0 | 2 | 4 | 6 | 8 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPIO input sample | yes | yes | yes | yes | yes |
| Parallel output update | yes |  |  |  | yes |
| ADC0 trigger | yes |  |  |  | yes |
| ADC1 trigger |  |  | yes |  |  |

The output's nominal first-update ticks are therefore `0, 8, 16, ...`. This is
digital schedule metadata, not yet a claim about the physical pad transition
time.

## Program model

The canonical program is an ordered list of fixed-size RLE segments:

```text
uint32 duration_samples
uint32 logical_state_mask
```

Each record is eight bytes. `duration_samples` is a strictly positive number
of 1 us output intervals. Only logical state bits 0-7 are accepted initially.
Adjacent segments with the same state should be coalesced by Python and may be
rejected or normalized by firmware.

Example:

```text
(10, 0b00000001)  # hold output bit 0 high for 10 us
( 5, 0b00000101)  # hold output bits 0 and 2 high for 5 us
(20, 0b00000000)  # hold all outputs low for 20 us
```

Program-level metadata supplies an initial/idle state and repeat count:

- repeat count `1`: play once, then hold the final state;
- repeat count `N`: play the complete sequence exactly `N` times;
- repeat count `0`: repeat indefinitely until explicit `STOP` or a fault.

A 32-bit duration can represent a single hold of approximately 71.6 minutes.
Long or indefinitely repeating patterns therefore remain compact. The worst
case is a different state every microsecond, where the proposed 1,024-record
program capacity represents 1.024 ms before repetition.

This is intentionally not a general state machine. Python may offer convenient
builder methods, but it compiles them to the same segment list. Firmware owns
only validation, bounded expansion, whole-program repetition, and DMA playback.

## Protocol direction

Treat output support as protocol v2 rather than silently extending v1. Protocol
v1 declares unknown capability bits invalid, and output needs new capabilities,
commands, INFO metadata, status, and errors. A v2-aware Python package may
continue to support v1 devices without output.

The existing eight-byte maximum command payload conveniently holds one complete
RLE segment. A conservative initial command set is:

| Command | Purpose |
| --- | --- |
| `OUTPUT_BEGIN` | Select the fixed pin profile, idle state, repeat policy, and new program generation |
| `OUTPUT_APPEND` | Append one eight-byte RLE segment |
| `OUTPUT_COMMIT` | Validate segment count, total duration, and program checksum; make the program immutable |
| `OUTPUT_ARM` | Associate the committed program with the next combined `START` |
| `OUTPUT_STATUS` | Return program, playback, held-state, queue, and error telemetry |
| `OUTPUT_CLEAR` | Disarm and release a committed program while not running |

The existing `START` remains the one atomic epoch transition for acquisition
and an armed output program. The existing `STOP` remains the one command that
stops all active work. Upload is IDLE-only and completes before `CONFIGURE` and
`START`; no output-program bytes are accepted during RUNNING.

One segment per request is intentionally simple and preserves the bounded
command parser. It may make a 1,024-segment upload slower, but upload is outside
the real-time run. The host may later pipeline requests within the existing
bounded command window if measurement justifies that complexity. A large bulk
receive frame should not be introduced without a separate streaming-parser and
memory analysis.

## Illustrative Python API

Names are provisional; the important boundary is a typed, completely preloaded
program rather than host-timed writes.

```python
from teensy_daq import DigitalOutputProgram, TeensyDAQ

program = DigitalOutputProgram(
    pins=range(16, 24),
    rate_hz=1_000_000,
    idle_state=0,
)
program.hold(0b0000_0001, samples=10)
program.hold(0b0000_0101, samples=5)
program.hold(0b0000_0000, samples=20)
program.repeat_forever()

with TeensyDAQ.open() as daq:
    committed = daq.outputs.upload(program)
    daq.outputs.arm(committed)
    daq.configure(adc=True, gpio=True, source="hardware")
    daq.start()
    # ADC and GPIO blocks continue through the existing reader API.
    daq.stop()  # Output DMA stops; D16-D23 hold their last state.
```

The simulator should expose a deterministic output trace or query surface so
program building, segment boundaries, repeat counts, common timestamps, STOP,
and hold behavior can be tested without hardware.

## DMA data representation

The program store contains logical absolute states; the DMA ring contains
physical GPIO1 toggle masks. For each output tick, the bounded expander computes:

```text
logical_delta = previous_logical_state XOR next_logical_state
physical_toggle_mask = map_logical_bits_to_gpio1(logical_delta)
```

The DMA channel writes `physical_toggle_mask` to `GPIO1_DR_TOGGLE`. A hold tick
writes zero. This gives one 32-bit transfer per output interval, changes all
selected pins atomically at the GPIO register boundary, and cannot overwrite
unrelated GPIO1 data bits.

Before arming, D16-D23 remain inputs. Arming selects standard GPIO1, configures
only the registered bits as outputs, and drives the declared idle state. The
first PIT1 output request changes from that idle state to the first program
state. Output DMA is the only writer to the selected data bits while running.

DMA source blocks require CPU-to-DMA cache flushes and explicit ownership. A
candidate block lifecycle is:

```text
FREE -> CPU_FILLING -> DMA_READY -> DMA_READING -> FREE
```

The DMA completion ISR should only acknowledge the channel and publish bounded
ownership progress. RLE interpretation and block filling stay in the
cooperative main loop, before and between the existing physical-acquisition and
USB service visits. A generation-indexed ring must prevent the CPU from
refilling a block that hardware can still read.

## Memory budget proposal

The current accepted image leaves only 4,096 bytes free in RAM2 and retains a
32 KiB minimum RAM1 allowance for stack/locals. A useful output program and
DMA ring therefore cannot be added as unrelated static allocations.

Repartition six existing packet pages without changing the aggregate static RAM
reservation:

| Use | Region | Proposed reservation |
| --- | --- | ---: |
| RLE program store | DTCM/RAM1 | 2 x 4,096 = 8,192 bytes |
| Output DMA allocation | OCRAM/RAM2 | 4 x 4,096 = 16,384 bytes |
| Output TCDs inside OCRAM allocation | OCRAM/RAM2 | 4 x 32 = 128 bytes |
| Usable DMA state words | OCRAM/RAM2 | 16,256 bytes = 4,064 states |

Four data blocks of 4,064 bytes each contain 1,016 32-bit updates per block.
At 1 MHz the complete ring provides 4.064 ms of refill runway.

The packet pool would change provisionally from 105 DTCM plus 95 OCRAM buffers
to 103 DTCM plus 91 OCRAM buffers, or 194 total. At the current nominal combined
framed rate, 194 packet buffers retain approximately 98.164 ms instead of
101.200 ms. That still exceeds the historical 60.715 ms service gap, but the
output path changes bus and CPU behavior; none of the old margin or soak
evidence transfers automatically.

The final linker/map gate must account for the program store, DMA ring,
descriptors, output engine state, vector entries, and any protocol/status
growth while preserving the existing stack/locals floor and RAM2 bounds.

## Firmware ownership and lifecycle

### Proposed modules

| Module | Responsibility |
| --- | --- |
| `digital_output_program.{h,cpp}` | Portable segment validation, capacity, duration, repeat, and cursor rules |
| `digital_output_engine.{h,cpp}` | Portable block ownership, RLE expansion, progress, completion, underrun, and hold state |
| `digital_output_teensy.{h,cpp}` | D16-D23 mux/direction, PIT1/XBAR/DMAMUX/eDMA channel 3, cache, IRQ, and register snapshots |
| `board_config.h` additions | Pins, GPIO bits, XBAR route, DMA channel/source/priority, IRQ, memory, and owner registry |
| protocol/Python additions | v2 commands, capabilities, metadata, models, API, simulator, errors, and fixtures |

Names may change after a repository-wide reuse search. The output path should
compose with the existing controller, buffer-ownership, protocol-generation,
statistics, and simulator patterns rather than duplicate them.

### Arm and START

1. Validate and commit the complete RLE program while IDLE.
2. Reserve/reinitialize every output buffer and prefill the complete DMA ring.
3. Configure the selected pads, output direction, and idle state.
4. Prepare output TCDs and enable their request path without starting PIT0.
5. Prepare GPIO input and ADC capture through the existing combined controller.
6. Arm ADC_ETC and every DMA path.
7. Enable the common PIT0/PIT1 schedule last.
8. Acknowledge `START` only after every owner accepted the epoch.

Any failure before step 7 must roll back without an output transition. Any
readback failure after partial setup must disable trigger generation first,
quiesce output DMA, leave the pins holding the actual latch state, and recover
the control plane consistently.

### Runtime service

- Give output block reclamation/refill an explicit bounded visit before long
  checksum/USB work and again between existing acquisition/USB visits.
- Never wait for the host or allocate memory in the active path.
- Continue ADC, GPIO input, and output across a DTR/USB disconnect, matching the
  current autonomous acquisition policy. Session-local commands are abandoned,
  but the committed program and run remain device-owned.
- Keep output telemetry separate from ADC/GPIO loss accounting while exposing
  the common run ID and epoch.

### Completion, STOP, and faults

- **Finite program completion:** disable channel 3 requests after the final
  update and hold the final state while acquisition may continue.
- **Explicit STOP:** disable the shared PIT trigger source first, quiesce output
  DMA, read/record the actual GPIO1 latch state, and leave the selected pins as
  outputs at that state while the input paths drain normally.
- **Output underrun:** never replay stale memory implicitly. Disable output DMA,
  hold the last physically driven state, latch an output fault, and recover the
  device according to the selected fail-stop policy. The first implementation
  should stop the common run because output/acquisition alignment is no longer
  valid.
- **Internal acquisition fault:** stop the shared schedule and output path with
  the same hold semantics before returning control state to IDLE.
- **MCU reset or power loss:** holding is not guaranteed; document the hardware
  reset state separately.

`STOP` is a control-plane operation, not a precisely scheduled waveform event.
The pins hold the state reached when firmware services and quiesces the stop,
not necessarily the state present when Python began sending the command.

## Required telemetry

INFO should advertise at least:

- output capability and fixed 1 MHz rate;
- logical width and exact logical-bit-to-Teensy-pin/GPIO-bit mapping;
- program-segment and repeat limits;
- program and DMA storage capacity;
- output clock, XBAR, eDMA, IRQ, and memory identities;
- supported completion/STOP behavior.

STATUS/output status should expose at least:

- program generation/identifier, committed segment count, and checksum;
- output state (`EMPTY`, `LOADING`, `COMMITTED`, `ARMED`, `RUNNING`, `HELD`, or
  `FAULTED`);
- declared idle state and last physically held state;
- current segment, remaining duration, repeat index, and repeat limit;
- states expanded, DMA states emitted, and completed blocks;
- current/high-water ready depth and refill lead;
- underruns, invalid operations, cache flushes, DMA errors, resource conflicts,
  start/stop errors, and unexpected output-drive events;
- common run ID, start tick, completion tick, and hold tick where observable.

Counters must be saturating or explicitly wrapping according to the protocol's
declared semantics, and reset behavior must be defined alongside the existing
statistics generation.

## Staged implementation plan

### 1. Freeze the semantic contract

- Confirm the initial eight-pin profile and exact logical ordering.
- Define RLE boundary semantics, first-update timing, repeat counting, empty and
  one-segment programs, maximum duration, program checksum, and hold behavior.
- Decide whether an output fault stops the entire combined run; the recommended
  initial policy is yes.
- Record a protocol-v2 compatibility decision before changing generated files.

### 2. Implement protocol, Python, and simulator first

- Extend the machine-readable protocol source and generator rather than hand
  editing constants.
- Add exhaustive golden request/response fixtures and drift tests.
- Add immutable Python program/segment models, builder validation, typed device
  capability errors, and state-aware upload/arm/clear methods.
- Model the exact 1 us schedule, repetitions, completion, STOP, disconnect, and
  underrun in the deterministic simulator.
- Ensure v1 devices remain usable for acquisition and report output as absent.

### 3. Implement portable firmware logic

- Add segment/program validation independent of Teensy headers.
- Add fixed program storage and the four-block ownership state machine.
- Expand logical states to physical delta masks with bounded work per service.
- Prove wraparound, finite/infinite repeat, generation reuse, cancellation,
  completion, underrun, and counter conservation in host-compiled C++ tests.
- Extend the existing runtime/controller transaction so output participates in
  readiness, rollback, common START, STOP, and fault recovery.

### 4. Build an isolated target diagnostic

- Reserve D16-D23, XBAR output 1, DMAMUX source 31, eDMA channel 3, the new IRQ,
  and the repartitioned memory in the central registry.
- Prove selective GPIO6-to-GPIO1 remapping and output-only direction changes.
- Prove a short known pattern at 1 MHz with GPIO1 toggle writes and no input
  acquisition active.
- Snapshot and verify every clock, XBAR, DMAMUX, eDMA, GPIO, cache, interrupt,
  and teardown register before integrating the path into normal START.

### 5. Integrate simultaneous combined acquisition

- Prefill and arm output before the existing common clock starts.
- Service output ownership at bounded points in `FirmwareRuntime::service()`.
- Preserve ADC-over-output-over-GPIO priority and verify no IRQ starvation.
- Extend INFO, STATUS, statistics, build manifests, resource documentation,
  hardware safety guidance, API documentation, examples, and recovery tooling.
- Keep all existing acquisition profiles unchanged when no output is armed.

### 6. Run local and physical qualification

- Run protocol-generation, formatting, lint, typing, Python, portable C++, exact
  Teensy build, linker/map, distribution, and documentation-integrity gates.
- Use an authorized, current-limited fixture to loop selected outputs into
  D6-D13. At a 1 MHz output rate and 4 MHz input capture, validate four input
  samples per output interval after measuring the actual phase convention.
- Observe output pins with a logic analyzer independently of the firmware's own
  input path so a common implementation error cannot self-certify.
- Exercise ADC and GPIO input simultaneously with the worst-case output pattern
  of one state change every microsecond.
- Exercise long holds, maximal segment counts, finite and infinite repeats,
  explicit STOP at varied phases, output completion while acquisition continues,
  USB close/reopen, host stalls, malformed uploads, and forced underrun/faults.
- Repeat the full combined endurance and control-stress campaigns on one frozen
  artifact. Prior release evidence does not certify the output-enabled image.

## Physical acceptance gates

The feature is not accepted until one immutable output-enabled artifact meets
all of the following:

1. ADC0 and ADC1 retain their configured 1 MS/s schedules and completion/error
   bounds with output active.
2. D6-D13 retain the 4 MS/s input schedule, exact pin mapping, and zero
   unexplained loss in the normal combined run.
3. D16-D23 emit every expected 1 MHz state with no duplicate, skipped, stale,
   or reordered update in the graded interval.
4. The measured relationship among output transitions, GPIO input samples, and
   both ADC triggers is stable and documented without overstating physical ADC
   aperture timing.
5. No output DMA underrun, eDMA error, cache error, resource conflict, ADC
   incomplete buffer, GPIO raw-ring overrun, or unexplained sequence gap occurs
   in the positive endurance campaign.
6. Program completion and explicit STOP leave the pins at the expected measured
   final state for a graded hold interval.
7. Deliberate underrun/fault injection stops new output transitions, holds the
   last physically emitted state, makes the fault visible, and allows bounded
   recovery without protocol desynchronization.
8. USB host stalls and DTR close/reopen do not change the autonomous output or
   acquisition schedules.
9. The final linker/map report preserves every RAM, alignment, cache, vector,
   and stack/locals bound after packet-pool repartitioning.
10. The normal no-output configurations remain byte-for-byte compatible at
    their public API boundary and pass their existing regression campaigns.

## Fallback order if 1 MHz combined operation fails

Do not lower the output rate at the first sign of a problem. Diagnose the
specific failed resource or bound and apply fallbacks in this order:

1. Correct DMA priorities, service ordering, cache ownership, or an accidental
   long critical section while preserving the 1 MHz schedule.
2. Increase output refill runway by trading additional packet pages only if the
   new USB-retention margin remains independently adequate.
3. Reduce expander work through coalescing, precomputation, or a more efficient
   fixed-rate representation.
4. Investigate a native variable-delay transition engine using timer compare
   preload and linked DMA if sparse RLE expansion is the actual bottleneck.
5. Use an independent PIT2/output phase if sharing PIT1 is the source of
   unacceptable coincident-request behavior.
6. Reduce output rate to 500 kHz or 250 kHz only when measured bus or service
   limits remain after the preceding corrections.

## Open decisions when work resumes

- Confirm that eight public output lines are sufficient. D16-D23 remains the
  recommended initial profile; additional same-bank pins should be a later,
  explicitly qualified profile.
- Choose exact protocol-v2 frame identifiers, status layout, capability bits,
  and checksum/commit semantics.
- Set the maximum segment count after measuring protocol object growth and final
  linker headroom; 1,024 is the current memory-budget target.
- Define the measured output-edge jitter and phase tolerances used for grading.
- Decide whether USB disconnect should continue to mean autonomous operation;
  continuation is the current proposal because it matches acquisition.
- Decide whether output-only or ADC-only/GPIO-only plus output profiles are ever
  required. They are intentionally outside the first combined-output scope.
- Design and authorize the physical loopback fixture, including series
  resistance, contention prevention, external-load limits, and observation
  independent of firmware capture.
