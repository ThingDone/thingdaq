---
type: analysis
title: 'ADR 005: Experimental Clock Profiles'
created: 2026-09-01
tags:
  - thingdaq
  - decision
  - clock-profile
  - teensy-4-0
  - experiment
related:
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[Protocol-V1]]'
  - '[[Experiment-Baseline]]'
---

# ADR 005: Experimental clock profiles

## Status

Accepted as the design boundary for the isolated 528 MHz experiment. The
`experiment/clock-528mhz` branch is experimental and descends from the exact
pushed `experiment/baseline-2026-09-01` commit
`b23004defeca465da0ae2d2884c4fef71979e5d4`. The 600 MHz profile remains the
production default. This decision records the inspected boundary; it does not
itself claim a working 528 MHz build or any physical, thermal, power, or
lifetime result.

The candidate was created at
`.maestro/playbooks/Working/clock-528mhz` and was clean at the baseline commit
before this record was edited. The remote baseline ref resolved to the same
commit, and `git merge-base --is-ancestor` verified the candidate ancestry.
The primary `main` worktree was not switched or edited for the experiment.

## Context

The accepted production firmware and its generated host contract currently
encode one 600 MHz clock tree in build selection, compile-time identity,
diagnostics, calibration, trigger timing, generated constants, Python
validation, rig programs, manifests, and historical evidence. Selecting the
pinned Teensy 4.0 528 MHz menu option changes the CPU, DWT, IPG, ADC, phase,
deadline, and core-voltage targets, but it does not change the 24 MHz PIT root
that produces the nominal acquisition schedule.

The experiment therefore needs two explicit profiles from one source tree. It
must preserve the existing [[Protocol-V1]] raw ADC/GPIO frame layout and stream
semantics while advertising the values that actually apply to the selected
profile. A host must not infer clocks from a familiar board, build ID, nominal
sample rate, or historical 600 MHz constant.

## Pinned-core audit

The inspected core is the installed `teensy:avr` 1.62.0 package at
`/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0`. Arduino CLI reports
the pinned Arm compiler as 15.2.1. `arduino-cli compile --show-properties`
resolved both exact targets to Teensy 4.0, USB Serial, GNU C++17, and `-O2`;
the required build properties differ only in `build.fcpu`.

| Pinned source | SHA-256 | Finding used by this decision |
| --- | --- | --- |
| `boards.txt` | `b58e03c4ccfd5a6f471ba05350987e0f845d0885255dd26fe163422d67c48714` | Teensy 4.0 exposes `speed=600` and `speed=528`, resolving `build.fcpu` to `600000000` and `528000000` respectively. |
| `cores/teensy4/clockspeed.c` | `3cc8a1e339eb8ee85edd8480ca364dc63c529dddfd7336ab1285649d1ec6fa63` | `set_arm_clock()` chooses `div_ipg = ceil(frequency / 150000000)`, then publishes `F_CPU_ACTUAL=frequency` and `F_BUS_ACTUAL=frequency/div_ipg`. Both profiles use divider 4, producing 150 MHz at 600 MHz and 132 MHz at 528 MHz. Its DCDC policy targets 1250 mV above 528 MHz through 600 MHz and 1175 mV at 528 MHz. |
| `cores/teensy4/startup.c` | `2307f20018fde63cf5ccb4e0d7de14047f8cb0fb5a567b474894d814c330de40` | Before applying `F_CPU`, startup selects the undivided 24 MHz oscillator as PERCLK for PIT/GPT. The acquisition PIT root therefore remains independent of the CPU menu selection. |
| `cores/teensy4/tempmon.c` | `d3572899cd9f123ddf6c5e1f6109e27c659b0ab266b1ba27dd6df9bc5d4c1afb` | The core initializes TEMPMON from OCOTP calibration data, but `tempmonGetTemp()` busy-waits without a deadline for the ready bit and returns a float. Runtime health sampling must reuse the calibrated register formula behind a bounded readiness check rather than call this unbounded API in acquisition service. |

The core voltage values are configuration targets, not measured rail voltage,
power, or junction characterization. The on-chip sensor is likewise not an
ambient-temperature or part-lifetime instrument.

## Profile arithmetic

The project-owned ADC configuration divides synchronous IPG by four. The
accepted half-microsecond ADC phase remains a time requirement, so its integer
cycle representation changes with the profile. DWT follows the actual CPU
clock, while PIT remains fixed.

| Property | Production/control profile | Experimental candidate profile |
| --- | ---: | ---: |
| Profile identity | `600` | `528` |
| Exact FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` | `teensy:avr:teensy40:usb=serial,speed=528,opt=o2std` |
| Resolved `build.fcpu`, required `F_CPU`, runtime `F_CPU_ACTUAL` | 600,000,000 Hz | 528,000,000 Hz |
| Core voltage target selected by Teensy 1.62.0 | 1,250 mV | 1,175 mV |
| IPG divider and runtime `F_BUS_ACTUAL` | 4; 150,000,000 Hz | 4; 132,000,000 Hz |
| ADC divider and clock | 4; 37,500,000 Hz | 4; 33,000,000 Hz |
| ADC resolution after full-rate timing/error gate | 12-bit primary | 10-bit explicit fallback |
| Nominal 500 ns phase | 75 IPG cycles | 66 IPG cycles |
| Nominal 500 ns diagnostic target | 300 DWT cycles | 264 DWT cycles |
| PIT root | 24,000,000 Hz | 24,000,000 Hz |
| GPIO / ADC-pair schedule | 4,000,000 / 1,000,000 samples/s | 4,000,000 / 1,000,000 samples/s |

These are required values to validate, not values to assume. Target code must
read back the clock tree and fail before START when the resolved build,
`F_CPU`, `F_CPU_ACTUAL`, `F_BUS_ACTUAL`, ADC divider/clock, or PIT source
contradicts the selected profile.

## Repository clock-assumption audit

Before editing, the repository was searched for literal and formatted forms of
`600000000`, `150000000`, and `37500000`, plus their MHz, FQBN, and output-path
forms. The results divide into these change boundaries:

| Surface | Existing 600 MHz assumption and required treatment |
| --- | --- |
| Build and target identity | `firmware/tools/build_firmware.py` owns the one exact 600 MHz FQBN, `build.fcpu`, output directory, source/build identity, linker map, artifacts, and resource gates. `firmware/src/firmware_identity.h` rejects every `F_CPU` except 600 MHz. Both must become an explicit two-profile, fail-closed boundary while leaving `600` as the no-argument default. |
| Firmware timing adapters | `gpio_clock_diagnostic{,_teensy}.{h,cpp}`, `gpio_capture_diagnostic_teensy.cpp`, `adc_initializer_teensy.cpp`, `adc_trigger_teensy.cpp`, `checksum_benchmark_teensy.cpp`, and `gpio_batch_packer_teensy.cpp` compare DWT/runtime clocks with generated 600 MHz constants or describe 600 MHz arithmetic. The portable planning and runner seams are reusable; the selected profile must supply the actual clock values. |
| Protocol authority and generation | `protocol/protocol-v1.json` owns checksum, GPIO DWT, ADC/IPG, calibration, trigger, INFO/STATUS, diagnostic, and example values. `tools/generate_protocol.py` additionally hard-rejects a checksum cycle counter other than 600 MHz. `firmware/src/generated/protocol_constants.h`, `daq_api/src/thingdaq/_generated/protocol_constants.py`, and binary fixture manifests are generated outputs and must never be hand-edited. Digit sequences inside existing `frame_hex` strings are encoded fixture bytes, not independent decimal assumptions. |
| Python validation and simulation | `daq_api/src/thingdaq/models.py` validates INFO, STATUS, GPIO clock evidence, ADC clocks, phase, and load against generated single-profile constants. `simulator.py`, `soak.py`, and `daq_api/scripts/windows_soak.py` carry the accepted 600 MHz identity or manifest. Contradictory advertised and observed clocks must become a model/client error rather than being normalized to the default. |
| Self-contained rig programs | `firmware/tests/rig_checksum_benchmark.py`, `rig_gpio_capture.py`, `rig_adc_capture.py`, and `rig_combined_capture.py` embed 600/150/37.5 MHz constants and derived deadlines. The combined-capture validator already supplies the physical maximum-rate, counter-conservation, fragmentation, timeout, and cleanup foundation for the clock comparison rig. |
| Host fakes and tests | `firmware/tests/fakes/teensy40/core_pins.h` fixes `F_CPU`, `F_CPU_ACTUAL`, and `F_BUS_ACTUAL` to the production tree. Build, protocol, ADC, GPIO, checksum, model, simulator, soak, and rig tests contain explicit production examples. Future profile tests must parameterize true clock behavior while retaining 600 MHz golden vectors where they are intentionally byte-stable. |
| Candidate and endurance manifests | `firmware/soak/candidate.json`, `candidate-freeze.json`, `validation-manifest.json`, `firmware/soak/validator.py`, `firmware/tools/freeze_soak_candidate.py`, generated soak programs, and the embedded package soak manifest identify the frozen 600 MHz release candidate. They are historical/production authorities and must not be silently rewritten into a 528 MHz candidate. Experimental builds need isolated manifests and artifact hashes. |
| Documentation and evidence | `README.md`, `daq_api/README.md`, `brainstormed_plan.md`, architecture/decision/protocol/reference documents, the soak guide, checksum research, and phase result reports describe either the 600 MHz production contract or immutable historical evidence. Normative text may become profile-aware; historical results, job identities, hashes, formulas, and measured 600 MHz values remain unchanged. [[Experiment-Baseline]] is the immutable comparison authority. |

This audit also covered the exact-value occurrences in protocol-vector,
build-configuration, ADC-initialization, GPIO-diagnostic, checksum-benchmark,
baseline-prototype, and rig fake-device tests. Those tests are inputs to the
later clock-specific test task; they are not evidence that 528 MHz already
works.

## Reuse map

| Need | Existing authority to extend |
| --- | --- |
| Exact builds, manifests, deterministic identities, hashes, map/resource gates | `firmware/tools/build_firmware.py` and `firmware/tests/test_build_configuration.py` |
| PIT/DWT plan, runtime readback, bounded window, register snapshot, error flags | `gpio_clock_diagnostic{,_teensy}.{h,cpp}` and its host-C++ tests |
| DWT measurement overhead and throughput profiling | `checksum_benchmark{,_teensy}.{h,cpp}` and `rig_checksum_benchmark.py` |
| Acquisition processing cycles and CPU utilization | `GpioBatchPacker` plus `TeensyCycleCounter`; extend the same bounded cycle-accounting pattern to acquisition and USB service windows |
| ADC clock/divider, calibration deadlines, phase, trigger completion, START rollback | `adc_initializer{,_teensy}` and `adc_trigger{,_teensy}` portable platform seams and host tests |
| STATUS counters and queue high waters | `Statistics::wireStatus()`, packet/USB progress, GPIO raw/packer progress, and ADC capture/packer progress |
| Fake clock/register behavior | `firmware/tests/fakes/teensy40`, the portable platform fakes, and host-compiled Teensy adapter tests |
| Maximum-rate physical validation and cleanup | `firmware/tests/rig_combined_capture.py` and `test_rig_combined_capture.py` |
| Sequential remote submission | The service-owned `run_my_program.py` client, whose inspected source and last accepted workspace copy are byte-identical at SHA-256 `23115388d9a62384cca074ac976c24986d77bd98538713901db3ec810e5c84ec`; fetch/preflight it again before use and keep credentials out of arguments, logs, and the repository |
| Experiment report schema and rendering | `experiments/experiment-matrix.json` already declares `clock-528mhz`, clock/temperature/utilization metrics, claim limitations, and canonical report paths; `firmware/tools/experiment_evidence.py` validates and renders the report pair |

## Decision

1. Only explicit `600` and `528` CPU profiles are valid. The production
   default remains `600`; an omitted profile must never select 528 MHz. Every
   other speed fails before compilation or START.
2. The firmware advertises selected profile identity and actual CPU, DWT, IPG,
   ADC, and PIT clocks, core-voltage target, and phase-cycle metadata. Runtime
   readbacks are checked against the selected profile. Python rejects missing
   or contradictory values; it never infers them from board type or sample
   rate.
3. All DWT deadlines, throughput denominators, calibration/conversion bounds,
   service utilization, and phase arithmetic derive from verified actual
   clocks. The 24 MHz PIT schedule and nominal acquisition rates do not change.
4. The existing protocol-v1 raw ADC and GPIO data frame header, payload layout,
   sequence/timestamp semantics, checksum behavior, and nominal sample rates
   remain compatible. The 600 MHz profile retains primary 12-bit ADC codes;
   the 528 MHz profile uses the protocol's explicit 10-bit fallback after its
   corrected full-rate 12-bit gate produced both ADC_ETC queue errors. INFO and
   STATUS advertise the selected resolution, CFG mode, and code maximum. The
   600 MHz profile remains the control behavior and must preserve its accepted
   raw bytes.
5. Temperature and service-health sampling is bounded and acquisition-safe.
   TEMPMON timeout, invalid calibration, non-finite conversion, or unavailable
   data is represented explicitly; no health query may wait indefinitely.
6. Experimental manifests, output directories, build identities, and artifact
   hashes are profile-specific. Repeated artifacts for one profile must be
   deterministic; different profile metadata is legitimate and must not mask
   unexpected code, data, map, or resource drift.
7. Performance compatibility and thermal benefit are separate outcomes.
   On-chip temperature can support only the declared comparison under the
   recorded fixture and ambient limitations. It cannot support power, junction
   temperature, reliability, or lifetime claims.

## Consequences

- Later implementation tasks must modify the protocol source and regenerate
  outputs rather than patch generated C++ or Python constants.
- The same source can produce an unchanged production/control profile and an
  isolated experimental profile, with enough advertised evidence for the host
  to validate each one independently.
- Existing historical 600 MHz reports remain reproducible and are not
  reinterpreted as profile-neutral evidence.
- The 528 MHz branch is not eligible for production or cross-branch synthesis
  until its local gates and same-board physical campaign are complete.
