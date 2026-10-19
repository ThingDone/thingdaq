---
type: analysis
title: Teensy 4.0 runtime clock dependency audit
created: 2026-10-19
tags:
  - firmware
  - teensy40
  - runtime-clock
  - protocol-v3
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-firmware-portable]]'
  - '[[adc-clock-options]]'
  - '[[watchdog-disabled-20260927]]'
---

# Runtime clock dependency audit

Phase 04 task 1, audited against repository commit `24df6fd` and the locally
installed `teensy:avr@1.62.0`. This is an implementation reference, not a runtime
adapter or physical qualification. The worktree was clean before the audit.
No task images were supplied. No hardware was flashed or clocked.

## Reuse boundaries

Use the installed core's C function `uint32_t set_arm_clock(uint32_t)` from
`cores/teensy4/clockspeed.c`; declare it with C linkage in the target adapter
(the inspected `core_pins.h`/`wiring.h` do not declare it). Startup itself calls
this function. Do not duplicate its DCDC/PLL sequence.

Reuse `settings::Application` and ControlState's exact apply/readback/rollback
boundary in `v3_settings.h` and `control_state.cpp`. The existing
`FixedBuildApplication` only selects software settings and echoes generated
clock metadata: it is not hardware readback. `variable_rate::Scheduler` already
provides derivation, transaction, readback and rollback machinery; extend that
path instead of building another timer scheduler. Its current target rollback
writes the saved registers and returns true without verifying the restored
registers, so it is insufficient as proof of clock rollback.

The canonical v3 JSON and generated `kCpuProfiles`, `kRateProfiles` and
`kSelectableConfigurations` already contain the public values. Derive a typed
projection from these definitions rather than maintaining another independent
clock/encoding table. Legacy generated v1/v2 definitions are compatibility
contracts, not mutable active-board state.

## Pinned core behavior

Source root: `/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/`.
`arduino-cli core list` confirms 1.62.0. The package's compile identity remains
`TEENSYDUINO=160`, as enforced by `firmware_identity.h`; do not infer the package
version from that macro. The repository builder pins GCC 15.2.1.

`clockspeed.c:set_arm_clock` performs these operations in order:

1. Compute the required voltage; raise DCDC voltage and wait for DC_OK before
   raising frequency. Unmodified local policy selects 1,250 mV at 600 MHz and
   1,150 mV at 450 MHz (wide-temperature boost is commented out).
2. Switch PERIPH to an alternate source while changing ARM PLL: USB PLL / 4
   (120 MHz) if its enable/power/lock/USB-clock bits are set, otherwise the
   24 MHz crystal. Wait for clock mux handshakes.
3. Compute ARM/AHB dividers and round PLL multiplication to 12 MHz steps;
   reprogram PLL_ARM when necessary, then wait for lock. Program ARM/AHB
   divisors and wait for their handshakes.
4. Set IPG divisor to `ceil(actual_cpu / 150 MHz)`, capped at four; switch back
   from the alternate PERIPH source and wait for its handshake.
5. Update `F_CPU_ACTUAL`, `F_BUS_ACTUAL`, and
   `scale_cpu_cycles_to_microseconds`; reduce DCDC voltage afterwards if needed.
   Return the computed frequency.

| Derived value | 600 MHz profile | 450 MHz profile |
| --- | ---: | ---: |
| PLL_ARM multiplier / output | 100 / 1,200 MHz | 75 / 900 MHz |
| ARM divisor / AHB divisor | 2 / 1 | 2 / 1 |
| IPG divisor / final clock | 4 / 150 MHz | 3 / 150 MHz |
| ADC ADICLK=1, ADIV=1 | 37.5 MHz | 37.5 MHz |
| PIT PERCLK crystal / divisor | 24 MHz / 1 | 24 MHz / 1 |
| Wire timestamp domain | 8 MHz | 8 MHz |
| 1 MHz PIT0 divider / LDVAL | 24 / 23 | 24 / 23 |
| Chained PIT1 divider / LDVAL | 1 / 0 | 1 / 0 |
| ADC_ETC predivider / chain length | 0 / 1 | 0 / 1 |
| ADC0/ADC1 initial delay | 0 / 75 IPG cycles | 0 / 75 IPG cycles |
| Effective delays / relative phase | 1 / 76 / 75 IPG cycles | 1 / 76 / 75 IPG cycles |
| ADC1 relative phase | 4 timestamp ticks | 4 timestamp ticks |
| Completion expected / tolerance | 300 / 120 DWT cycles | 225 / 90 DWT cycles |
| ADC calibration / stop deadline (10 ms) | 6,000,000 cycles | 4,500,000 cycles |
| Trigger diagnostic deadline (2 ms) | 1,200,000 cycles | 900,000 cycles |
| DMA alignment window (10 us) | 6,000 cycles | 4,500 cycles |

These are source-derived target values, not measured transition results. IPG
is temporarily different during the alternate-source phase even though both
final profiles use 150 MHz. Stop acquisition before invoking the core.

**Blocking design constraint for the later adapter:** the core function has
unbounded DC_OK, PLL-lock and CCM-handshake loops, no timeout result, no yield,
and no rollback. A wrapper deadline checked after return cannot bound a stuck
call. It also contains a TODO about safe IPG divider changes. Returning the
requested frequency and updating globals is not independent register readback.
Verify PLL lock/bypass/power/multiplier, mux selection, ARM/AHB/IPG divisors,
PERCLK source/divisor and ADC configuration as well as both globals. The later
adapter must resolve failure containment before claiming bounded commands;
portable failure injection alone cannot establish this property of the core.
Do not replace the core with an improvised PLL sequence or silently change
watchdog policy to conceal the limitation.

## Time, USB, temperature and watchdog

- `startup.c` selects crystal-derived PERCLK for PIT/GPT. `set_arm_clock` does
  not change `CCM_CSCMR1`. Existing `gpio_dma_route_teensy.h` masks and readbacks
  should remain authoritative for 24 MHz PIT selection.
- SysTick uses the independent 100 kHz external source, reload 99, generating
  milliseconds. `EventResponder.cpp:systick_isr` records the DWT count and
  increments the millisecond count. DWT remains enabled and is not reset by
  `set_arm_clock`; its rate follows CPU frequency, including the transition.
- `delay.c:micros` combines the last SysTick millisecond/DWT snapshot with the
  current conversion scale, clamping the fraction to 1,000 us. The clock routine
  changes the scale without rebasing the SysTick DWT snapshot. A sample spanning
  the change can therefore be mis-scaled or go backwards (notably on an upshift).
  `TeensyTickClock::nowTicks` treats *every* backwards 32-bit micros delta as wrap,
  potentially producing a roughly 71-minute forward jump. Preserve accumulated
  time using an independent elapsed-time anchor and a verified rebase; simply
  zeroing the DWT or subtracting with the new frequency is insufficient. Do not
  lose stopped elapsed time. Sample timestamps remain logical 8 MHz run-relative
  periods; each START already creates a new run epoch.
- Core `delayMicroseconds`, `delayNanoseconds` and wiring conversion macros use
  `F_CPU_ACTUAL`. They are suitable only for intervals at a stable CPU rate.
  Rebase/reset acquisition completion windows, benchmark sessions and packer
  cycle profiling across transitions; never convert mixed-frequency intervals.
- The clock routine reads USB PLL state but does not reprogram USB PLL or reset
  USB. `usb.c` uses PLL3; CDC flush uses `USB1_GPTIMER0` (75 us), and its transmit
  timeout uses SysTick milliseconds. `usb.c:schedule_transfer` has a fixed
  2,400-DWT-cycle tripwire retry bound (4 us at 600 MHz, about 5.33 us at 450 MHz).
  Leave this pinned implementation and the project's `UsbTransmitGuard` capacity
  recheck untouched unless physical evidence requires a correction. Interrupts
  are not masked by `set_arm_clock` itself, but main-loop work cannot progress
  inside a stuck handshake. Source separation does not prove USB continuity.
- `temperature_teensy.cpp` reads the already-running monitor once;
  `temperature.h:decode` returns NOT_READY if FINISHED is clear. Production has
  no CPU-derived temperature readiness deadline. Core `tempmonGetTemp` has an
  unbounded FINISHED wait, but this firmware does not call it; retain the
  nonblocking reader. The core initializes the monitor with frequency field 3.
- `runtime_health_teensy.cpp` scans stack canaries and reports reset/watchdog
  state; it has no DWT conversion. `watchdog_teensy.cpp` selects 32,768 Hz / 256,
  timeout 512 ticks (4 s), independent of CPU/IPG, with a 2,000,000-poll setup
  bound and a 128-bus-clock register-write window. **The current sketch comments
  out `watchdog::begin()`**; refresh is consequently inert. Neither enabled
  recovery nor a bounded PLL failure can be assumed. Preserve this documented
  policy pending an explicit, proven adapter dependency.

## Runtime dependency inventory

Paths below are under `firmware/src/` unless stated otherwise. The audit searched
all source and generated timing definitions for CPU/IPG/ADC constants, literal
450/528/600/132/150 MHz rates, DWT access/conversion, divisors, timing periods and
static assertions, then followed the consumers below. Test and research-only
constants are not additional public capabilities.

| Consumer | Dependency / bounded refactor |
| --- | --- |
| `input_experiment_profile.h` | Compile-time CPU/IPG/ADC, `scaleIpg`, `scaleDwt`, research 528 MHz/equal rates. Keep experimental/storage switches separate from active public timing. |
| `rate_profile_table.h` | Flash constexpr table scales phase/completion and frame coverage; `legacyTimingFor` preserves original generated values. Introduce active timing without changing legacy validators. |
| `variable_rate_scheduler.{h,cpp}` | `kContractClocks` equality rejects another CPU; derivation checks exact divisions and generated timing equality. Reuse arithmetic and overflow guards with the selected profile. |
| `variable_rate_scheduler_teensy.cpp` | Cached selected/pending `Schedule`, peripheral register snapshot, CPU/bus/PERCLK checks. Restore caches and verify peripherals as well as clocks on rollback. |
| `adc_initializer.{h,cpp}`, `adc_initializer_teensy.cpp` | Default ADC clocks and 10 ms calibration cycles; DWT checks reject another CPU. CFG fixes IPG/4; explicit bounded initializer overrides the core's unbounded `analog_init`. Reinitialize through this owner. |
| `adc_trigger.{h,cpp}`, `adc_trigger_teensy.cpp` | Snapshot defaults, 2 ms deadlines, scaled phase/completion/tolerance and DWT probes; live register configuration consumes selected schedule. Refresh metadata and diagnostic state after applying clocks. Preserve ITCM timer-enable-to-observation ordering. |
| `adc_dma_capture_teensy.cpp` | 10 ms stop boundary, 10 us alignment, DWT observation/fault trace; active ADC1 DMAMUX/ADC_ETC route and DMA requests must be quiesced/restored. Public-v3 route selection already exists separately from private codec flags. |
| `gpio_raw_capture_teensy.cpp` | 10 ms DWT stop boundary; cached `g_pit_load` starts at historical 4 MHz load 5 but configure replaces it with derived load. Refresh from accepted schedule, not legacy production constants. |
| `gpio_dual_bank_capture_teensy.cpp`, `gpio_dma_route_teensy.h` | Shared PIT/XBAR/DMA ownership, selected schedule and paired descriptors; fixed masks/gates are reusable. Quiesce both banks, preserve unrelated register bits. |
| `gpio_clock_diagnostic.{h,cpp}`, `gpio_clock_diagnostic_teensy.cpp` | PIT divider, rational DWT/event measurement, actual-counter check and expected-count arithmetic use compile-time CPU. Retain rational arithmetic (450 MHz / 4 MHz is 112.5). |
| `gpio_capture_diagnostic{,_teensy}.{h,cpp}` | Historical diagnostic plan and 10 ms capture window/DWT frequency; currently disabled by fixed-rate release capabilities. Do not broaden advertised diagnostics as a side effect. |
| `checksum_benchmark{,_teensy}.cpp` | Rejects counters differing from build CPU; reports cycle/frequency-based throughput and utilization. Snapshot the active frequency for one complete benchmark. |
| `gpio_batch_packer{,_teensy}.cpp` | Counter begin checks build CPU; elapsed/active cycles span profiling windows. Counters/ratio need a fresh epoch, not a new buffer allocation. |
| `protocol.{h,cpp}`, `firmware_capabilities.h` | Default ADC/trigger clocks, INFO/diagnostic encode/decode constraints, completion tolerances and benchmark/GPIO cycle arithmetic. Distinguish active metadata from frozen v1/v2 wire expectations; do not globally substitute generated constants. |
| `v3_settings.h`, `control_state.cpp` | Build-only profile/defaults and adapter; v3 exact tuple membership/readback, rollback fault gate; v2 CONFIGURE uses build-profile RAW projection today. V2 INFO must remain read-only. |
| `firmware_runtime.cpp`, `acquisition_controller.{h,cpp}` | Boot caches initializer/trigger metadata; readiness gates precede control dispatch. Reuse ownership checks and refresh cached readiness after reinitialization. `dataPathQuiescent` covers packet/synthetic/acquisition, not all transport/core-USB state; explicitly handle response ownership and queued commands. |
| `teensy_clock.{h,cpp}`, `synthetic_source.{h,cpp}` | Micros extension feeds absolute 8 MHz pacing. Keep logical periods and START epoch; handle the transition discontinuity described above. |
| `stream_layout.h`, `adc_frame_packer.{h,cpp}`, GPIO packers, `packet_buffer_pipeline.{h,cpp}`, `deferred_codec.h`, `usb_transport.cpp` | Layout-selected logical counts/periods, retention/fairness and 80,000-tick codec deadline live in the 8 MHz domain, not CPU cycles. Keep those units; flush ownership before switching. |
| `temperature{,_teensy}.*`, `runtime_health{,_teensy}.*`, `watchdog_teensy.cpp`, `teensy_usb.cpp` | Stable peripheral/snapshot mechanisms and the caveats in the preceding section. |

### Static assertions and storage that must remain fixed

`F_CPU == input_experiment::kCpuHz` appears in the ADC initializer/trigger,
checksum benchmark, GPIO clock/capture diagnostics and GPIO packer target files;
`firmware_identity.h` also preprocessor-checks it. These remain valid as *boot
build* identity checks, not constraints on the active profile. The old messages
claiming a pinned 600 MHz target are misleading for the existing 450 MHz build.
Replace runtime equality checks against build constants with active readback.

`adc_initializer.h`, `adc_trigger.h`, DMA/raw-GPIO and capture-diagnostic target
files assert compile-time deadline/phase formulas. Validate both typed profiles
at compile time and the selected projection at runtime rather than removing
these guarantees. `input_experiment_profile.h`'s 600 MHz/private-RLE assertion
and deferred-codec preprocessor guards describe private build combinations;
public policy-driven codecs already work independently of these flags.

Keep board resource identities, IRQ/priorities, cache-line alignment, descriptor
sizes, ADC/GPIO rings, packet pages, queue bounds, stack and memory overlap
assertions fixed. In particular `board_config.h:kAdcDmaActivePipelineDepth` and
its DMA target assertion select 4 versus 6 at build time; they are storage/
pipeline policy, not runtime clock divisors. Do not resize them on CONFIGURE.
V3's 4,032 decoded bytes, 1,008 ADC pairs, 4,032 GPIO8 or 2,016 GPIO16 samples
already fit the 4,096-byte pages. Legacy 4 MHz GPIO constants/assertions in
capabilities, raw capture, trigger and synthetic code remain legacy contracts.
Fixed-release rate masks/rejections in `protocol.cpp` and `control_state.cpp`
keep 1 MHz sampling; experimental 528 MHz and historical rates stay excluded.

## Validation and implementation handoff

The next task should add only the authoritative typed timing projection and
exact supported tuples: 600/150 MHz RAW/PACK12/RLE_AUTO combinations already in
the v3 table, 450/150 MHz RAW-only, both sampled at 1 MHz. Across stream masks,
sources and GPIO widths, the existing reference table has 48 + 12 complete
records; advertising both clocks on hardware waits for a usable adapter.

Existing tests to extend: `test_input_rate_clock.py`, `test_adc_initializer.py`,
`test_adc_trigger.py`, `test_adc_register_adapter.py` (shared fake Teensy
registers), `test_gpio_clock_diagnostic.py`, `test_control_state.py`,
`test_firmware_runtime.py`, `test_runtime_health.py`, and the v3 layout/lifecycle
harnesses. Include mixed-frequency micros regression, actual clock mismatch,
rollback verification and START inhibition, not only a fake successful core call.

The target path remains `firmware/tools/build_firmware.py` with experiment-builder
internals for isolated 600 MHz candidates. Do not overwrite the 450 MHz release
artifact. Preserve core/compiler/USB/-O2 provenance, flash placement, static
allocation/overlap and linked-memory gates: RAM1 locals/stack >= 32,768 bytes;
RAM2 heap/headroom >= 4,096 bytes. This audit does not run a new target build or
claim physical transition timing, USB continuity or rollback qualification.

## Audit checks performed

```bash
TMPDIR="$PWD/.maestro/playbooks/Working" .venv/bin/python -m pytest -q \
  firmware/tests/test_input_rate_clock.py \
  firmware/tests/test_adc_register_adapter.py \
  firmware/tests/test_adc_initializer.py \
  firmware/tests/test_adc_trigger.py \
  firmware/tests/test_gpio_clock_diagnostic.py \
  firmware/tests/test_runtime_health.py \
  firmware/tests/test_temperature.py \
  firmware/tests/test_watchdog_teensy.py \
  firmware/tests/test_build_configuration.py \
  --basetemp=.maestro/playbooks/Working/phase04-audit-pytest
```

Result: **41 passed, 3 skipped, 6 subtests passed**. The three skips are the
explicitly unsupported fixed-release + equal-rate experiment combinations.
These tests compile existing portable and fake-register paths and exercise the
builder's gates; they do not compile or execute a new hardware clock adapter.
No production code changed and no new production test is needed for this audit.
The profile calculations, document front matter, local file references and core
fingerprints were also checked, along with `git diff --check`.

## Task 2: typed profile and timing projection

Implemented 2026-10-19. `firmware/src/board_profile.h` provides typed CPU and
rate views over the generated v3 Flash tables. There is no second persisted
table and no change to `protocol-v3.json`. `settings::defaultsFor` derives the
600 MHz compressed default or the 450 MHz RAW default using exact tuple
membership; an unknown CPU has no usable default.

`variable_rate::derive(settings::Record)` validates the entire tuple before
reusing the existing exact-divider arithmetic. `runtime_timing::project` in
`firmware/src/runtime_timing.h` packages the schedule, ADC settings, unready
trigger snapshot, completion tolerance, calibration/diagnostic/stop/alignment
cycle budgets and expected v3 clock metadata. Its values match the clock table
above. `gpio_clock::makePlan(request, CpuProfile)` projects diagnostic windows
with rational rounding, including 113 cycles per event and 11,363 cycles for
101 events at 4 MHz with a 450 MHz CPU.

The public projection accepts exactly 48 configurations at 600 MHz and 12 at
450 MHz, all at 1 MHz with 8 MHz timestamps. The 450 MHz tuples are RAW-only;
600 MHz permits the generated RAW/PACK12 and RAW/RLE_AUTO combinations. Research
528 MHz builds and historical rate experiments cannot extend this set.

Compatibility remains explicit: the legacy `derive(RateProfile, ClockDomains)`
and `deriveForRates` overloads retain build-clock checks and generated v2
validation. `legacyTimingFor`, v1/v2 validators, layouts and serializers are
unchanged; v3 timing snapshots do not replace their metadata contracts.
Portable control tests still exercise v2/v3 sessions and read-only queries.

These APIs calculate **expected** settings, not hardware readback. Production
still uses `FixedBuildApplication`, advertising only its build clock. The next
adapter task must apply/read back clocks before publishing this projection;
the later acquisition task must pass it to hardware owners and rebase counters.
No clock transition, target candidate build or physical qualification is claimed
by this task. See [[protocol-v3-upgrade]] for the remaining integration work.

Validation: `test_input_rate_clock.py` passed 11 cases with three intentional
fixed-release/equal-rate skips. Its C++ harness now checks all 60 tuples under
all nine supported research/release build combinations, rejects corrupted
settings and 450 MHz compression, checks timing/defaults/wire clocks, and keeps
legacy build-clock rejection intact. The auxiliary-input, v3 control/layout/
portable-regression, protocol, control-state, ADC initializer/trigger/register,
GPIO clock, firmware-runtime and build-configuration suites passed **138 tests
and 47 subtests**, with two intentional 450 MHz compression skips. Generator
drift (142 files), repository Ruff formatting/lint and SDK mypy checks passed.
No task images were supplied or analyzed.

## Installed source fingerprints

SHA-256 of the inspected local core files (relative to `cores/teensy4/`).
These pin the implementation evidence even if a local package is later edited.

| File | SHA-256 |
| --- | --- |
| `clockspeed.c` | `3cc8a1e339eb8ee85edd8480ca364dc63c529dddfd7336ab1285649d1ec6fa63` |
| `startup.c` | `2307f20018fde63cf5ccb4e0d7de14047f8cb0fb5a567b474894d814c330de40` |
| `delay.c` | `5348418c09c04b772b9790f23f839e191251891afd17fe4e37f42311526ba729` |
| `EventResponder.cpp` | `888c352e777c6e69dac4d8e3636b275b64a91b9e8a4a92c8dc512e5511929cdd` |
| `core_pins.h` | `c7f002d6763f05fd0ec68ebb879220baee79b48f6a22dd45de0ce88ae0e0e5bc` |
| `wiring.h` | `5eaa8d00443dd3aa32044cbe5f6d2aeb65654a58b3a3709e220f74436c1b886b` |
| `usb.c` | `8cb03e83e90527e5574c7977bc8957edbc16f27c2b210c7949a507158f8bf78c` |
| `usb_serial.c` | `a675e0479e27cbad3a8e0fa6b918020af5b0f8894be43ebc495832995f5d842c` |
| `tempmon.c` | `d3572899cd9f123ddf6c5e1f6109e27c659b0ab266b1ba27dd6df9bc5d4c1afb` |
