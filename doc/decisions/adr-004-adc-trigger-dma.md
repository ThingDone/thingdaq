---
type: analysis
title: 'ADR 004: ADC Trigger and DMA'
created: 2026-08-28
updated: 2026-08-28
tags:
  - teensy-daq
  - decision
  - adc
  - adc-etc
  - pit
  - xbar
  - edma
  - phase-07
related:
  - '[[Firmware-Resource-Map]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[System-Overview]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[Phase-07-Dual-ADC]]'
---

# ADR 004: ADC trigger and DMA

## Status

Accepted as the Phase 07 converter and resource contract. Logical ADC0 is
permanently bound to Teensy A0 through NXP ADC1 channel 7; logical ADC1 is
permanently bound to Teensy A1 through NXP ADC2 channel 8. The register-level
initializer and independently bounded calibration are implemented and pass
host and pinned-target build gates. The exact trigger schedule, stopped arm/
teardown order, bounded conversion-completion diagnostic, and INFO/STATUS
evidence are also implemented and pass host and pinned-target build gates.
The fixed dual-eDMA register adapter and cache-safe paired ring are implemented
and pass host plus pinned-target build gates. Physical lifecycle/packet
integration and the sequential on-silicon trigger, calibration, DMA,
10-second smoke, and 60-second full-rate gates now pass in
[[Phase-07-Dual-ADC]]. This decision is silicon-verified for the digital
acquisition and transport path. Because the accepted A0/A1 inputs were
unstimulated, analog accuracy and sample-and-hold aperture remain explicitly
outside that claim.

## Context

[[Protocol-V1]] requires two raw converter streams at 1 MS/s each, stored as
`adc0, adc1` pairs, with a nominal 500 ns ADC1 phase. Both RT1062 ADC modules
can sample both A0 and A1. Pin validity alone therefore cannot preserve
converter identity: generic `analogRead(A0)` selects NXP ADC1, and a library
call made against the other ADC object can legally select the same pad. The
project needs one compile-time route table that owns the module, pad, input
channel, ADC_ETC queue, XBAR route, and eDMA channel together.

The central [[Firmware-Resource-Map]] already reserved PIT1, XBAR outputs 103
and 107, ADC_ETC queues 0 and 4, and eDMA channels 0 and 1. This review checked
those reservations against the implemented GPIO, packet, USB, control, and
diagnostic modules before making the ADC tuple authoritative.

## Audited baseline and reused code

The pinned implementation baseline is Teensy core and bundled libraries at
`/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0`. The following
sources were reinspected on 2026-08-28:

| Source | Finding and reuse boundary |
| --- | --- |
| `libraries/ADC/ADC.cpp` | Both Teensy 4.0 module tables map A0 to channel 7 and A1 to channel 8. This proves electrical routing but also proves that caller order cannot establish logical identity. |
| `libraries/ADC/ADC_Module.cpp` | Library module `adc0` wraps NXP ADC1 with ADC_ETC trigger 0 / `TRIG00`; `adc1` wraps NXP ADC2 with trigger 4 / `TRIG10`. The identities and register-shaping patterns are reused. `startQuadTimer()` is not called because it owns QuadTimer4, mutates shared ADC_ETC state, and does not provide this design's independent initial delays. |
| `libraries/ADC/AnalogBufferDMA.cpp` and examples | The RT1062 mapping `ADC1_R0`/DMAMUX 24 and `ADC2_R0`/DMAMUX 88, aligned OCRAM buffers, scatter/gather TCD shape, completion handling, and cache invalidation are reused as reviewed patterns. Dynamic first-free DMA allocation and separate non-interleaved buffer policy are not reused. |
| `cores/teensy4/analog.c` | `pin_to_channel` confirms A0/D14 is `GPIO_AD_B1_02`, channel 7, and A1/D15 is `GPIO_AD_B1_03`, channel 8. Its generic module selection, cooperative unbounded calibration wait, default averaging, and single-read polling are not suitable for the production path. |
| `cores/teensy4/core_pins.h` and `pins_arduino.h` | `A0 == 14`, `A1 == 15`, and their pad-control identities are fixed for Teensy 4.0. Target compilation continues to assert the pin aliases. |
| `cores/teensy4/imxrt.h` | Confirms XBAR input/output numbers, ADC/ADC_ETC registers, DMAMUX sources 24/88, 32 eDMA channels, and 32-byte TCD alignment used by the registry and later register adapter. |
| `cores/teensy4/clockspeed.c` | At the pinned 600 MHz CPU menu, the core selects a 150 MHz IPG/bus clock. The trigger adapter checks `F_BUS_ACTUAL`, the configured 24 MHz PERCLK root, and the relevant PIT/XBAR/ADC gates before arming. |
| `firmware/src/board_config.h` | Existing fixed pin, PIT, XBAR, ADC_ETC, eDMA, and OCRAM reservations are composed into one `AdcConverterConfiguration` table instead of duplicated in a new module. Compile-time validators reject incomplete, crossed-queue, duplicate-channel, range, and ownership errors. |
| `firmware/src/gpio_dma_route_teensy.h` and `gpio_raw_capture{,_teensy}.{h,cpp}` | Reuse the stopped-before-route arm order, fixed register ownership, diagnostic snapshots, overflow sink, scatter/gather TCD shape, leases, and fail-safe teardown patterns. ADC adds a two-channel generation barrier and shared cache ownership rather than duplicating the GPIO state machine verbatim. |
| Packet/control modules | Reuse the fixed packet pool, alternating source promotion, START epoch, run/sequence accounting, common statistics, and bounded USB service. No ADC-specific allocation or second transport queue is introduced by this decision. |

The independent primary references are the NXP
[i.MX RT1060 reference-manual page](https://www.nxp.com/products/i.MX-RT1060?tab=Documentation_Tab),
[MIMXRT1062 device API](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/api/devices/MIMXRT1062/index.html),
[i.MX RT1060 data sheet](https://cache.nxp.com/docs/en/nxp/data-sheets/IMXRT1060CEC.pdf),
and the official
[ADC_ETC eDMA example](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/examples/driver_examples/adc_etc/adc_etc_edma/readme.html).
They confirm the PIT-to-XBAR-to-ADC_ETC-to-ADC-to-eDMA topology, the ADC_ETC
queue split, ADC timing fields, and DMA transfer requirements.

## Decision

### Permanent converter routes

`board::kAdcConverterConfigurations` is the sole authoritative ADC route
table. Existing pin, XBAR, ADC_ETC, and eDMA allocation projections derive
their ADC entries from these tuples:

| Logical result | Library module | Teensy pad | NXP ADC/input | ADC_ETC/XBAR | Result DMA |
| --- | ---: | --- | --- | --- | --- |
| ADC0 | `adc0` / 0 | A0/D14, `GPIO_AD_B1_02` | ADC1 channel 7 | async trigger 0, PIT1 input 57 to output 103 (`TRIG00`) | `ADC1_R0`, DMAMUX 24, eDMA 0 |
| ADC1 | `adc1` / 1 | A1/D15, `GPIO_AD_B1_03` | ADC2 channel 8 | async trigger 4, PIT1 input 57 to output 107 (`TRIG10`) | `ADC2_R0`, DMAMUX 88, eDMA 1 |

The ADC_ETC chain length is one conversion and each queue selects result slot
zero. Trigger queues 0-3 belong to ADC1 and queues 4-7 belong to ADC2. Queue 0
and queue 4 are configured independently with `SYNC_MODE=0`; ADC_ETC sync mode
would make trigger 0 own both initial delays and therefore cannot express the
required relative phase. `TSC_BYPASS` must be clear so queue 4 controls ADC2.

The implemented DMA adapter writes ADC0 halfwords at pair offset 0 and ADC1
halfwords at pair offset 2, both with a four-byte destination stride. Channel
0 reads `ADC1_R0` through DMAMUX source 24 and channel 1 reads `ADC2_R0`
through source 88. Both use 16-bit source/destination attributes, two-byte
minor transfers, equal 1,012-result major loops, fixed priorities 2/1 above
GPIO priority 0, major
completion interrupts, and five scatter/gather descriptors per channel.

Four 4,064-byte cache-line-aligned OCRAM buffers each contain 1,012 native
`{uint16_t adc0, uint16_t adc1}` pairs plus alignment padding. Both channel
descriptors for a generation target the same buffer. The first completion can
schedule future work but cannot publish data; only the second completion with
the same nonzero run epoch and modulo-32-bit DMA generation crosses the shared
barrier. A duplicate, stale-epoch, wrong-destination, or excessive channel-lead
event cannot advance CPU ownership.

Cache deletion precedes initial DMA ownership and every transition back to
`FREE`. CPU acquisition invalidates the complete buffer only after the paired
barrier. Tainted generations enter `DISCARD_PENDING` and are cache-cleaned by
bounded cooperative service, never by an ISR. When all four consumer buffers
are owned, both channels use separate halfwords of an isolated 32-byte sink
with zero destination stride. Each completed sink generation advances one
ring-overrun event and exactly 1,012 lost pairs while acquisition remains live.
ADC_ETC trigger-error bits count overwritten converter results and taint the
active generation; mismatched completions, unequal STOP progress, DMA faults,
schedule exhaustion, and rejected stale interrupts have independent counters.
Complete corrupt blocks and partial STOP work contribute exact discarded-pair
counts.

Both channel TCDs retain `INTMAJOR`, but only the later ADC1 NVIC line
dispatches. Numeric eDMA priority 2 is highest, so the earlier ADC0 result runs
ahead of ADC1 at priority 1; continuous GPIO traffic runs at priority 0. The
ADC1 handler waits at most 10 us for both visible `DMA_INT` bits, then consumes
the generation in ADC0-to-ADC1 order. An incomplete pair faults before software
ownership can advance, while a matching pair is the only path that makes the
buffer ready.

Normal STOP first waits for both live channels to enter the first quarter of
the same DMA generation, then atomically sets `DREQ` on both active TCDs while
triggers remain live. This avoids a channel-transition race while retaining
ample time before the next boundary. It waits at most 10 ms and 2,000,000 polls
for both request-enable bits to clear at the matching major-loop boundary,
then stops the shared trigger schedule before disabling ADC DMA requests,
interrupts, and routes. This preserves every complete paired generation
without treating an arbitrary command arrival point as data loss.
A boundary timeout remains fail-safe: it is reported as a STOP error, triggers
are still disabled before DMA teardown, and any actual partial progress is
accounted exactly by the paired ring.

### Shared clock and phase arithmetic

The accepted [[ADR-003-GPIO-Clock-DMA]] clock is a 24 MHz peripheral root with
PIT0 `LDVAL=5`:

```text
24,000,000 / (5 + 1) = 4,000,000 GPIO events/s
4,000,000 / (3 + 1) = 1,000,000 ADC-pair events/s
```

PIT1 is reserved in chained mode with `LDVAL=3`, so each ADC pair event follows
exactly four GPIO periods. At the protocol's 8 MHz sample epoch, pair `n` is at
tick `8n` and ADC1 is at tick `8n + 4`.

ADC_ETC runs from the pinned 150 MHz IPG clock. With `PRE_DIVIDER=0`, the
effective initial delay is `(INIT_DELAY + 1)` IPG cycles. The selected raw
values account for that unavoidable minimum:

| Queue | Raw `INIT_DELAY` | Effective delay | Time from synchronized trigger |
| ---: | ---: | ---: | ---: |
| ADC0 / trigger 0 | 0 | 1 IPG cycle | 6.667 ns nominal |
| ADC1 / trigger 4 | 75 | 76 IPG cycles | 506.667 ns nominal |

The difference is exactly `76 - 1 = 75` IPG cycles, and
`75 / 150 MHz = 500 ns`. Using 74 for the second raw field would be one cycle
short. These values describe digital trigger timing, not analog aperture.

### Implemented stopped arm and completion diagnostic

`adc_trigger_teensy.cpp` owns the exact clock/trigger register sequence. It
first verifies both calibrated converters and rejects an already-running PIT,
enabled ADC_ETC trigger, or active ADC. While stopped, it selects the same
verified 24 MHz PERCLK root used by GPIO, writes PIT0 `LDVAL=5`, writes chained
PIT1 `LDVAL=3`, fans XBARA1 input 57 to outputs 103/107, configures asynchronous
one-segment queues 0/4, clears `SOFTRST` and then `TSC_BYPASS` with the two
successive `CTRL` writes required by the reset-state behavior observed on the
i.MX RT1062 and used by PJRC's ADC setup, writes raw initial delays 0/75, and
switches ADC1/ADC2 command slot zero to hardware-trigger mode. Every clock,
route, queue, delay, and hardware-trigger setting is read back before arming.

The BOOT diagnostic clears ADC_ETC/NVIC state, leaves the three ADC_ETC IRQ
lines disabled, briefly masks interrupts, enables queues 0/4 and chained PIT1,
and enables the 4 MHz PIT0 master last. A bounded ITCM loop timestamps the
first queue-0 Done0 and queue-4 Done1 status transitions with the free-running
600 MHz DWT counter, clears each observed status bit, and retains the first
ADC_ETC trigger-error state. This avoids mistaking NVIC tail-chaining latency
for the programmed hardware phase when both equal-priority completion IRQs
have become pending before either handler runs. The target poll and portable
scheduler retain independent 2,000 us and 2,000,000-poll ceilings. Teardown
stops PIT0 first, disables both queues, waits boundedly for both ADCs to become
idle, disables and acknowledges the IRQ lines, and verifies the stopped state.

Identically configured conversions should complete 300 DWT cycles apart. The
cross-check accepts ±120 DWT cycles to cover register-observation variation and
publishes the observed delta, expected delta, tolerance, elapsed cycles,
completion counts, trigger-error count, final IRQ words, and configured
CCM/PIT/XBAR/ADC_ETC register evidence through INFO and STATUS. This is
conversion-completion timing only. It does not observe either ADC's analog
sample-and-hold aperture and must never be presented as aperture or phase
accuracy evidence. The accepted target rig in [[Phase-07-Dual-ADC]] preserves
that distinction.

### Implemented initialization and conversion setting

The implemented primary configuration is 12-bit, one `uint16_t` result,
no hardware averaging, high-speed mode, short sample mode, and the shortest
`ADSTS=00` setting. Select synchronous IPG as the ADC clock source and divide
150 MHz by four, yielding `fADCK = 37.5 MHz`, below the data sheet's 40 MHz
high-speed ceiling.

The reference-manual first/single-conversion budget is:

```text
SFCAdder = 4 ADCK + 2 IPG clocks
12-bit BCT = 25 ADCK
short-sample adder = 3 ADCK
total = 32 / 37.5 MHz + 2 / 150 MHz
      = 866.667 ns
headroom before the same module's next 1 us trigger = 133.333 ns
```

Teensy core startup normally calls its `analog_init()` implementation before
C++ construction; that implementation calibrates both ADCs with unbounded
busy loops. `adc_initializer_teensy.cpp` resolves that archive hook to a no-op
that touches no project object, then overwrites the generic ADC configuration
at the application BOOT boundary. It configures A0/A1 as non-driving analog
inputs, disables all command slots, binds the modules through the fixed route
table, checks the live `F_BUS_ACTUAL` IPG rate, and reads the mux, pad,
clock-gate, CFG, GC, GS, and HC registers back.
It does not depend on ADC library object or call order. Both calibrations start
independently and are polled together against wrap-safe 600 MHz DWT elapsed
cycles. Each has a 10,000 us deadline, and an independent 8,000,000-iteration
poll ceiling remains a second hard bound if the cycle counter stops advancing.
A route, configuration, clock, calibration, timeout, or post-calibration
readback fault is retained separately for each converter and leaves physical
ADC acquisition unavailable. Any future attempt to link the core `analogRead`
path will surface a duplicate initialization-hook link failure rather than
silently reintroducing the unbounded calibration path.

INFO and STATUS report the actual resolution, two-byte container, code range,
nominal VREFH/VREFL 3.3 V reference and 0-3.3 V input range, synchronous IPG
clock/divider, ADCK rate, averaging count, sample clocks, CFG mode, fixed
pin/peripheral/channel identities, deadline, per-converter calibration state
and cycles, configuration flags, and initialization errors. An uninitialized
or failed snapshot never carries the `INITIALIZED` flag.

The arithmetic plus bounded completion matching verifies the programmed
digital path, and [[Phase-07-Dual-ADC]] proves full-rate paired capture and
transport on silicon. Neither is full-rate analog-accuracy evidence. The
shortest sample setting places an explicit low-source-impedance requirement on
any accuracy fixture.
Unstimulated or high-impedance A0/A1 data can prove routing and code range but
cannot prove 12-bit accuracy, analog bandwidth, aperture, phase, or settling.

### Fallback policy

The initializer defaults to the 12-bit configuration above. Its resolution
selector can choose 10-bit only when a completed gate records corrected
configuration, exact-rate and calibration verification, and then a remaining
timing-budget or conversion-error failure. An incomplete gate, route error, or
calibration error cannot authorize fallback. The completed full-rate target
gate passed at 12 bits with exact-rate, calibration, trigger, DMA, and zero-
error evidence, so fallback was not authorized and the accepted build remains
explicitly 12-bit. A future regression may select 10-bit only when that same
defined gate still fails at the exact 1 MHz-per-converter rate after clocks,
calibration, trigger queues, and DMA ownership have been verified. A 10-bit
fallback keeps the `uint16_t` container and the permanent ADC0/A0 and ADC1/A1
routes, but must
change advertised resolution/code range, update this ADR, and rerun every
local and physical acceptance test. It is never silent and never triggered by
the numeric values observed on floating or unstimulated inputs.

No fallback may swap converters or pins, use an approximate sample rate,
remove the 500 ns delay difference, enable averaging, or dynamically allocate
a timer/XBAR/DMA resource. If chained PIT1 cannot be proven, acquisition stays
disabled until a conflict-free source produces exactly 1 MHz from the shared
clock contract; accepting that source requires synchronized updates to
`board_config.h`, [[Firmware-Resource-Map]], this ADR, register tests, and rig
evidence. If neither resolution passes the defined timing/error gate, physical
ADC capability remains unavailable rather than weakening metadata.

## Consequences

- Converter identity is now independent of ADC library call order; any later
  module/pin, queue, XBAR output, or DMA reassignment fails compile-time tests.
- The shared XBAR input 57 is intentional fan-out. Outputs 103/107, ADC_ETC
  queues 0/4, ADC peripherals 1/2, eDMA channels 0/1, and DMAMUX sources 24/88
  remain unique and cannot conflict with GPIO channel 2/source 30.
- The initial 12-bit timing calculation fits one microsecond but has narrow
  headroom. The completed physical gate, not this arithmetic alone, accepts it.
- Bounded low-level initialization, calibration, trigger arm/teardown, and
  completion matching run before BOOT enters IDLE, and their exact snapshots
  are visible in INFO/STATUS. The runtime now arms fixed interleaved DMA,
  packetizes paired generations, projects complete STATUS accounting, and has
  passed sequential on-silicon target evidence in [[Phase-07-Dual-ADC]].
