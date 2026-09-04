---
type: report
title: "ThingDAQ Auxiliary Output Bank Experiment"
created: 2026-09-04
tags:
  - thingdaq
  - experiment-evidence
  - aux-output-bank
related:
  - "[[Evidence-Index]]"
  - "[[Protocol-V1]]"
  - "[[System-Overview]]"
  - "[[baseline]]"
  - "[[1-MHz-Parallel-Output-Idea]]"
  - "[[ADR-008-Experimental-Aux-Output-Bank]]"
  - "[[Acquisition-Pipeline]]"
  - "[[Aux-Output-Memory-Candidate]]"
  - "[[Aux-Output-Prototype]]"
  - "[[Hardware-Safety]]"
---

# ThingDAQ Auxiliary Output Bank Experiment

## Outcome

**INCONCLUSIVE**

The final candidate conclusion is **INCONCLUSIVE for physical output** because the remote service exposed no machine-readable protected-loopback declaration. The safety interlock therefore wrote exactly zero ARM/START requests. Local target/lifecycle evidence passed, and the repaired immutable image passed the mandatory no-output maximum-rate physical combined regression.

### Campaign identity and decision

| Field | Exact result |
| --- | --- |
| Baseline / branch source | `b23004defeca465da0ae2d2884c4fef71979e5d4` / `42e85a587bb784ede8177c7af710009be69ffa29` |
| Firmware source / build | `8a29c9d2af9c06657be59f15641b1370704d2abe` / `thingdaq-8c98b280873e15de` |
| HEX SHA-256 | `3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8` |
| Identified hardware | Teensy serial `20428100` |
| Fixture declaration | Absent; canonical empty SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Physical output decision | **NOT_RUN**; no output pin was armed or driven |
| Loopback lag / stability | **NOT_MEASURED / NOT_RUN** |

### Output resource and memory map

| Item | Exact allocation |
| --- | --- |
| Pins and GPIO | D16-D23 in logical order; GPIO1/GPIO6 bits `23,22,17,16,26,27,24,25`; mask `0x0FC30000` |
| Trigger and DMA | PIT1; XBARA1 input 57 to output 1; DMAMUX 31; eDMA channel/IRQ 3; vector 19; NVIC priority 56 |
| Arbitration | ADC0 3 > ADC1 2 > auxiliary output 1 > GPIO input 0 |
| Program | `0x20068ec0`, 8,192-byte DTCM store, 1,024 eight-byte segments |
| Output DMA | four 32-byte descriptors at `0x20200000`; four 4,064-byte/1,016-state blocks at `0x20200080` |
| Packet banks | 103 DTCM frames at `0x20001ec0` + 91 OCRAM frames at `0x20204000` = 194 frames |
| Retention | 98.164 ms packet-only; 99.176 ms with USB; 38.461 ms margin over the historical 60.715 ms gap |
| Linked headroom | 32,768 bytes RAM1 locals/stack; 4,096 bytes RAM2 heap |

The common XBAR selector/control register halves are updated by read-modify-write, all managed allocations are non-overlapping, and the DMA-read output ring is cache flushed before publication.

### Pattern, epoch, preservation, and conservation results

| Check | Result |
| --- | --- |
| Walking bit, long hold, every-1-us transition, finite/infinite repeat, varied STOP phase | **NOT_RUN**: protected fixture declaration absent |
| Disconnect/reopen, host stall, deliberate underrun recovery | **NOT_RUN**: protected fixture declaration absent |
| 60-second and 600-second combined output campaigns | **NOT_RUN**: protected fixture declaration absent |
| Shared output/input epoch and four-samples-per-state grading | **NOT_RUN**; no loopback lag was inferred |
| No-output combined physical regression | **PASS**, job `86c8d003-a809-4186-8702-6092ed4d0d4f`, 352 checks over 10.000572 seconds |
| Non-driving output controls | **PASS**, job `601bbf65-65d4-4b8c-b032-7100b5963c1d`; zero drive writes; final IDLE |

The no-output regression observed 10,256,620 ADC pairs and 41,026,480 GPIO samples in 10,135 frames per stream at 1,000,001.196 ADC pairs/s and 3,999,600.007 GPIO samples/s. Both streams ended at timestamp 82,052,960 ticks. All complete-frame, sequence, parser, transport, pool, hardware, and conservation errors were zero. The bounded STOP tails were exactly 76 ADC pairs and 306 GPIO samples and reconciled captured to transmitted counts. Packet ownership peaked at 37 of 194, GPIO processing load was 2,238 basis points, maximum STATUS latency was 2.102 ms, maximum command latency was 20.995 ms, and host RSS growth was 200,704 bytes.

Host fake-register and stress evidence separately passed atomic toggle expansion, shared-register preservation, pre-clock rollback, finite completion, STOP/fault latch hold, CLEAR-to-input release, repeated lifecycle, forced underrun/resource/readback faults, stale-completion rejection, and exact output conservation. These are implementation/lifecycle results, not physical waveform measurements.

### Incidents and boundaries

Job `50c81cf9-21dd-44cd-986b-a1d45a4deb0a` was rejected before power because the option-qualified catalog entry lacked a hub port. Original-image jobs `5cee87df-af4e-4d76-bfc8-97982a395a36` and `8655a7f7-783a-4986-aae7-c7f77f7ed92e` reproduced eDMA priority error `DMA_ES=0x800040c8`; diagnostic job `66278a41-be0d-47ad-a63e-f80974064c65` isolated the reserved-channel collision. The repaired image then passed. Jobs `e6f0a1f0-3b8d-4649-b14e-89d390f2cf58` and `f9bd3504-0f97-4382-9df5-b5fe415f15cb` were bounded runner/envelope diagnostics with zero drive writes, not firmware failures.

No pad was driven, so this report establishes no measured output rate, physical pattern fidelity, loopback lag, hold voltage, edge timing, jitter, voltage level, or signal integrity. Even an eventual firmware-observed loopback cannot independently certify those properties; logic-analyzer or oscilloscope evidence remains required. ADC values were checked only for transport continuity and conservation, not accuracy, noise, ENOB, linearity, bandwidth, or aperture timing. No compatibility claim is made for combining this branch with the clock, RLE, or auxiliary-input candidates. See [[Aux-Output-Prototype]], [[ADR-008-Experimental-Aux-Output-Bank]], [[1-MHz-Parallel-Output-Idea]], and [[Hardware-Safety]].

Reason: The protected D16-D23-to-D6-D13 fixture declaration was absent, so all physical-output and loopback checks remained NOT_RUN despite passing local lifecycle and physical no-output regressions.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/aux-output-bank |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | 42e85a587bb784ede8177c7af710009be69ffa29 |
| source_tree | 769c736ffecebeab39728ce7b8fcc0bb0ae78505 |
| source_clean | true |
| source_id | 8c98b280873e15de4a83255e28a6e444f7d31b69d040dd5c18d2a5825f790f1d |
| protocol_contract_path | protocol/protocol-v1.json |
| protocol_version | 1 |
| protocol_sha256 | 014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222 |

### Toolchains

| Name | Version | Identity |
| --- | --- | --- |
| arduino-cli | 1.4.1 | arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z |
| arm-none-eabi-g++ | 15.2.1 | arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203 |
| g++ | 13.3.0 | g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 |
| python | 3.12.3 | CPython 3.12.3 |
| teensy-core | 1.62.0 | teensy:avr 1.62.0 |

## Evidence levels

| Label | Meaning | Physical claims allowed |
| --- | --- | ---: |
| **analytic** | A deterministic calculation or static inspection with hashed inputs; no implementation execution is implied. | false |
| **host** | Execution on the host, including native tests, benchmarks, and no-upload firmware builds; target runtime behavior is not implied. | false |
| **rig** | Autonomous execution on identified hardware with a hashed fixture declaration and bounded cleanup. | true |

### Evidence records

| ID | Evidence level | Result | Method | Command |
| --- | --- | --- | --- | --- |
| branch-isolation | **host** | PASS | Git object inspection proves exact baseline descent and identifies the isolated twenty-commit experiment history before report generation. | `git merge-base b23004defeca465da0ae2d2884c4fef71979e5d4 42e85a587bb784ede8177c7af710009be69ffa29` |
| evidence-framework | **host** | PASS | Fail-closed shared-schema validation, referenced-file and artifact verification, secret/mutable-identity rejection, normalization, and deterministic JSON/Markdown rendering. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-output-bank.json --check` |
| firmware-build | **host** | PASS | Two byte-identical pinned Teensy 4.0/core 1.62 no-upload builds with manifest, linker-map, cache-region, resource, and retention validation. | `python3 firmware/tools/build_firmware.py` |
| output-host-lifecycle | **host** | PASS | Fresh protocol/Python/portable/target/fake-rig/evidence tests plus the retained clean local gate exercise output lifecycle, conservation, interlocks, fault injection, and bounded refill. | `env PYTHONPATH=daq_api/src python3 -m pytest -q daq_api/tests/test_aux_output_v2_contract.py daq_api/tests/test_aux_output_v2_generation.py firmware/tests/test_digital_output_engine.py firmware/tests/test_digital_output_conformance.py firmware/tests/test_digital_output_teensy.py firmware/tests/test_digital_output_throughput.py firmware/tests/test_rig_aux_output_loopback.py firmware/tests/test_experiment_evidence.py` |
| output-resource-and-memory-map | **analytic** | PASS | Exact linker-manifest and central-registry inspection for the complete 1 MHz output path. | `python3 -m pytest -q firmware/tests/test_build_firmware.py firmware/tests/test_digital_output_teensy.py` |
| protected-loopback-campaign | **rig** | NOT_RUN | Prepared walking-bit, long-hold, every-microsecond-transition, finite/infinite-repeat, varied-STOP, disconnect/reopen, host-stall, underrun-recovery, 60-second, and 600-second checks. | `python3 firmware/tests/rig_aux_output_loopback.py --mode endurance` |
| remote-service-preflight | **host** | PASS | Finite ten-second service, worker, queue, board-catalog, and machine-readable fixture-metadata preflight. | `remote-firmware-testing preflight --deadline-seconds 10` |
| rig-no-output-combined | **rig** | PASS | Maximum-rate physical combined ADC/GPIO regression using the repaired immutable image while the auxiliary output bank remained disabled. | `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig_combined_capture.py` |
| rig-nondriving-output-controls | **rig** | PASS | Protocol-v2 OUTPUT_STATUS, unarmed upload, malformed APPEND rejection, CLEAR, final STATUS, and final CLEAR without any ARM or START write. | `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig_aux_output_loopback.py` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| measurement_duration_seconds | 10.000572039047256 | second | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| adc_pairs_observed | 10256620 | adc_pair | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| gpio_samples_observed | 41026480 | gpio_sample | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| adc_frames_observed | 10135 | frame | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| gpio_frames_observed | 10135 | frame | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| adc_payload_bytes | 41026480 | byte | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| gpio_payload_bytes | 41026480 | byte | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| combined_payload_bytes | 82052960 | byte | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| adc_framed_bytes | 41512960 | byte | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| gpio_framed_bytes | 41512960 | byte | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| combined_framed_bytes | 83025920 | byte | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| adc_pair_rate_hz | 1000001.196026857 | adc_pair_per_second | streaming_elapsed_seconds | streaming_window | **rig** | ["rig-no-output-combined"] |
| gpio_sample_rate_hz | 3999600.007262244 | gpio_sample_per_second | streaming_elapsed_seconds | streaming_window | **rig** | ["rig-no-output-combined"] |
| sequence_gap_frames | 0 | frame | none | streaming_window | **rig** | ["rig-no-output-combined"] |
| firmware_dropped_frames | 0 | frame | none | run | **rig** | ["rig-no-output-combined"] |
| host_queue_drops | 0 | event | none | run | **rig** | ["rig-no-output-combined"] |
| parser_errors | 0 | event | none | run | **rig** | ["rig-no-output-combined"] |
| transport_errors | 0 | event | none | run | **rig** | ["rig-no-output-combined"] |
| conservation_failures | 0 | event | none | final_status | **rig** | ["rig-no-output-combined"] |
| command_latency_p99_milliseconds | 2.102050930261612 | millisecond | command_latency_samples | run | **rig** | ["rig-no-output-combined"] |
| command_latency_maximum_milliseconds | 20.994924940168858 | millisecond | command_latency_samples | run | **rig** | ["rig-no-output-combined"] |
| packet_owned_high_water_frames | 37 | frame | none | run | **rig** | ["rig-no-output-combined"] |
| packet_buffer_capacity_frames | 194 | frame | none | artifact | **rig** | ["rig-no-output-combined"] |
| flash_used_bytes | 132956 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_headroom_bytes | 32768 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["firmware-build"] |
| output_state_rate_hz | 1000000 | hertz | streaming_elapsed_seconds | output_window | **analytic** | ["output-resource-and-memory-map"] |
| output_underruns | 0 | event | none | run | **host** | ["output-host-lifecycle"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/aux-output-bank","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","source_id":"8c98b280873e15de4a83255e28a6e444f7d31b69d040dd5c18d2a5825f790f1d","source_tree":"769c736ffecebeab39728ce7b8fcc0bb0ae78505","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","name":"g++","version":"13.3.0"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["branch-isolation"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"b989f52131b70f6e88472258b09496d96cf2123bee90186092404bd9212731a3","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"4c19383237f5537a80103014a2a0dfbde00795fcdcedce2f8859188ade54d110","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"0c6a160e87507e4f66c43fba8f0dc8e2a6461718e57a1429adc26702df59ba8f"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"b989f52131b70f6e88472258b09496d96cf2123bee90186092404bd9212731a3","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"4c19383237f5537a80103014a2a0dfbde00795fcdcedce2f8859188ade54d110","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"0c6a160e87507e4f66c43fba8f0dc8e2a6461718e57a1429adc26702df59ba8f"} | — | ["firmware-build"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"repeat_outputs_byte_identical":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["firmware-build"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"json":"byte-identical","markdown":"byte-identical"} | {"json":"byte-identical","markdown":"byte-identical"} | — | ["evidence-framework","output-host-lifecycle"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **NOT_RUN** | — | — | The complete physical-output lifecycle requires an exact protected-loopback fixture declaration, which was absent. | [] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **PASS** | true | {"complete_frame_loss_zero":true,"hardware_errors_zero":true,"no_output_combined_passed":true,"parser_errors_zero":true,"sequence_gaps_zero":true,"stop_tails_reconciled":true,"transport_errors_zero":true} | — | ["rig-no-output-combined"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **PASS** | true | {"adc_capture":{"left":10256696,"right":10256696},"adc_pipeline":{"left":10256620,"right":10256620},"combined_framed":{"left":83025920,"right":83025920},"combined_payload":{"left":82052960,"right":82052960},"gpio_capture":{"left":41026786,"right":41026786},"gpio_pipeline":{"left":41026480,"right":41026480},"promoted_frames":{"left":20270,"right":20270}} | — | ["rig-no-output-combined"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **PASS** | 194 | 37 | — | ["rig-no-output-combined"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"drive_requests_zero":true,"no_output_regression_idle":true,"nondriving_controls_idle":true,"output_bank_disabled":true,"queues_empty":true} | — | ["rig-no-output-combined","rig-nondriving-output-controls"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"analog_performance_claim_absent":true,"cross_branch_claim_absent":true,"host_target_distinction_explicit":true,"incidents_classified":true,"independent_timing_claim_absent":true,"loopback_lag_unmeasured_explicit":true,"physical_output_not_run_explicit":true,"signal_integrity_claim_absent":true} | — | ["output-host-lifecycle","output-resource-and-memory-map","remote-service-preflight"] |

## Claim limitations

| Limitation | Statement | Applies to evidence levels |
| --- | --- | --- |
| simulation_is_not_physical | Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality. | ["simulated"] |
| build_is_not_target_runtime | A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB. | ["host"] |
| analog_performance_untested | Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing. | ["analytic","simulated","host","rig"] |
| aux_output_authorization_scope | Physical output checks may run only with an exact hashed safety/fixture authorization; absent authorization remains NOT_RUN and cannot be promoted to PASS. | ["rig","manual"] |
| loopback_is_not_independent_measurement | Firmware observing its own looped-back output is not independent certification of pad-level timing, voltage, jitter, or signal integrity. | ["rig"] |
| cross_branch_combinations_untested | Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact. | ["analytic","simulated","host","rig","manual"] |

## Artifacts and reproduction

| Kind | Repository-relative path | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 16476 | `b989f52131b70f6e88472258b09496d96cf2123bee90186092404bd9212731a3` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 2021084 | `4c19383237f5537a80103014a2a0dfbde00795fcdcedce2f8859188ade54d110` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 397551 | `3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 900335 | `0c6a160e87507e4f66c43fba8f0dc8e2a6461718e57a1429adc26702df59ba8f` |

### Commands

- `branch-isolation` (host): `git merge-base b23004defeca465da0ae2d2884c4fef71979e5d4 42e85a587bb784ede8177c7af710009be69ffa29`
- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-output-bank.json --check`
- `firmware-build` (host): `python3 firmware/tools/build_firmware.py`
- `output-host-lifecycle` (host): `env PYTHONPATH=daq_api/src python3 -m pytest -q daq_api/tests/test_aux_output_v2_contract.py daq_api/tests/test_aux_output_v2_generation.py firmware/tests/test_digital_output_engine.py firmware/tests/test_digital_output_conformance.py firmware/tests/test_digital_output_teensy.py firmware/tests/test_digital_output_throughput.py firmware/tests/test_rig_aux_output_loopback.py firmware/tests/test_experiment_evidence.py`
- `output-resource-and-memory-map` (analytic): `python3 -m pytest -q firmware/tests/test_build_firmware.py firmware/tests/test_digital_output_teensy.py`
- `protected-loopback-campaign` (rig): `python3 firmware/tests/rig_aux_output_loopback.py --mode endurance`
- `remote-service-preflight` (host): `remote-firmware-testing preflight --deadline-seconds 10`
- `rig-no-output-combined` (rig): `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig_combined_capture.py`
- `rig-nondriving-output-controls` (rig): `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig_aux_output_loopback.py`
