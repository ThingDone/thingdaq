---
type: report
title: "ThingDAQ Auxiliary Input Bank Experiment"
created: 2026-09-04
tags:
  - thingdaq
  - experiment-evidence
  - aux-input-bank
related:
  - "[[Evidence-Index]]"
  - "[[Protocol-V1]]"
  - "[[System-Overview]]"
  - "[[baseline]]"
  - "[[ADR-007-Experimental-Aux-Input-Bank]]"
  - "[[Acquisition-Pipeline]]"
  - "[[Aux-Input-Prototype]]"
  - "[[Hardware-Safety]]"
---

# ThingDAQ Auxiliary Input Bank Experiment

## Outcome

**FAIL**

The immutable auxiliary-input candidate is **FAIL** on the identified Teensy. The service was available, but two identity-pinned attempts reproduced an IDLE paired-DMA diagnostic failure before START. Consequently no raw profile qualified, and the required stop-on-reproduction policy prevented lower-rate, 60-second, 600-second, and profile-cycle runs.

### Campaign decision

| Decision field | Result |
| --- | --- |
| Highest sustained raw profile | **None** |
| Target-rate campaign | **FAIL** |
| Rig conclusion | Conclusive candidate failure |
| Service availability | Available: remote-firmware-testing 1.2.0, API v1, healthy/normal, queue depth 0 |
| Eight-input regression | **FAIL before START** in CONTROL_COMBINED; no primary-bank streaming regression claim is available |
| Final safety state | Both reproductions reported FINAL_INPUT_SAFE; cleanup STOP returned IDLE |
| Electrical stimulus | Not declared; D16-D23 is ELECTRICALLY_UNSTIMULATED and external transition/pin-order checks are NOT_RUN |

### Combined 16-input profile matrix

| ADC / GPIO | Payload (ADC + GPIO = total) | Framed (ADC + GPIO = total) | Campaign result | Reason |
| --- | ---: | ---: | --- | --- |
| 1 MHz / 4 MHz | 4 + 8 = 12 MB/s | 4.047431 + 8.094862 = 12.189723 MB/s (`3084000000/253` B/s) | **FAIL** | Two five-second eight-input control smokes reproduced the pre-START diagnostic failure; the 16-input stream was not entered. |
| 500 kHz / 2 MHz | 2 + 4 = 6 MB/s | 2.023715 + 4.047431 = 6.094862 MB/s (`1542000000/253` B/s) | NOT_RUN | Escalation stopped after reproducible safety/resource failure. |
| 250 kHz / 1 MHz | 1 + 2 = 3 MB/s | 1.011858 + 2.023715 = 3.047431 MB/s (`771000000/253` B/s) | NOT_RUN | Escalation stopped after reproducible safety/resource failure. |
| 125 kHz / 500 kHz | 0.5 + 1 = 1.5 MB/s | 0.505929 + 1.011858 = 1.523715 MB/s (`385500000/253` B/s) | NOT_RUN | Escalation stopped after reproducible safety/resource failure. |

### Pin and resource map

| Bank | Pins and wire order | DMA-visible GPIO | Route |
| --- | --- | --- | --- |
| Primary | D6-D13 | GPIO2 bits `10,17,16,11,0,2,1,3` | PIT0 / XBARA1 input 56 / output 0 / DMAMUX 30 / eDMA 2 |
| Auxiliary | D16-D23 | GPIO1 bits `23,22,17,16,26,27,24,25`, mask `0x0FC30000`; selectively remapped from GPIO6 through GPR26 | PIT0 / XBARA1 input 56 / output 1 / DMAMUX 31 / eDMA 3 / IRQ 3 / vector 19 / NVIC priority 64 |

The fixed eDMA service order is ADC0, ADC1, primary GPIO, auxiliary GPIO with priorities `3,2,1,0`. This is arbitration order only and is not a pad-level simultaneity claim. Both raw bank rings have depth four.

### Memory and retention

| Item | Exact result |
| --- | --- |
| Raw GPIO storage | One 64,768-byte allocation split into two non-overlapping 32,384-byte INPUT views |
| INPUT workspace | 992 bytes leased from the IDLE-only 4,096-byte OCRAM checksum workspace; 3,104 bytes remain unused |
| Packet pool | 105 DTCM + 95 OCRAM = 200 frames; no capacity change; all 13 managed allocations passed overlap validation |
| RAM1 locals/stack | 34,528 bytes free |
| RAM2 heap | 4,096 bytes free |
| 16-input combined retention | 50.6 / 101.2 / 202.4 / 404.8 ms from highest to lowest profile |
| Default 8-input combined retention | 101.2 / 202.4 / 404.8 / 809.6 ms from highest to lowest profile |

### Diagnostic, queues, load, loss, and conservation

Both counting jobs reported error flags `0x50` (`CAPTURE_TIMEOUT | NO_COMPLETE_BUFFER`), `DMA_ERR=1`, `AUX_DMA_ERR=1`, zero complete buffers from both banks, zero analyzed auxiliary samples, and zero CPU cache invalidations after seven DMA-side discards per bank. The primary TCD BITER was 2024 rather than the validator's expected 4048 and primary eDMA priority was 1 rather than expected 0. The absence of any complete bank buffer is independently disqualifying regardless of those two grading mismatches.

Because failure occurred before START, streaming queue high-water, CPU load, command latency, complete-frame loss, timestamp/rate, event-ratio, parser, transport, and end-to-end conservation measurements are **NOT_RUN**, not zero. Diagnostic conservation itself failed: neither bank published a complete block for cooperative acquisition. The final input-safety and IDLE cleanup checks passed.

### Incident and claim boundaries

The option-qualified board submission was rejected before power/programming under job `05162896-d451-473e-8fce-d2aba7bb4cd1`; it is excluded infrastructure lineage. Job `151ed05d-ecc4-41c9-a95a-122d16a29a38` discovered replacement serial 20428100 and intentionally failed closed against the historical serial. Counting jobs `7155044f-9a98-4ea3-a574-4ce458694a60` and `90666c7b-4afd-49ac-98e7-225f9f4399da` then pinned serial 20428100 and reproduced the candidate failure.

Constant or unstimulated values are transport data only. This report makes no claim about external D16-D23 transition fidelity, pin order, thresholds, timing, jitter, signal integrity, ADC analog performance, or compatibility with the clock, RLE, or auxiliary-output experiment branches. See [[Aux-Input-Prototype]], [[ADR-007-Experimental-Aux-Input-Bank]], [[Acquisition-Pipeline]], and [[Hardware-Safety]].

Reason: Two identity-pinned immutable-artifact attempts reproduced a paired-DMA diagnostic failure before START; no profile established sustainable raw acquisition.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/aux-input-bank |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | e36f94dc7de82f760b2bbe18bc94fa971dc073e6 |
| source_tree | 52a6577e01d8b8d8fb8243e2e131be61a7401677 |
| source_clean | true |
| source_id | c1f05b3a2ebfc8b372a176852de0b16740d6739db6897f76de510d01831a7ac8 |
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
| aux-input-workload-analysis | **analytic** | PASS | Exact rational payload and complete-frame rate calculation for all four protocol-v2 INPUT profiles. | `python3 daq_api/examples/aux_input_matrix.py` |
| branch-isolation | **host** | PASS | Git object and merge-base inspection of the isolated auxiliary-input checkpoint. | `git merge-base b23004defeca465da0ae2d2884c4fef71979e5d4 e36f94dc7de82f760b2bbe18bc94fa971dc073e6` |
| evidence-framework | **host** | PASS | Fail-closed shared-schema validation, referenced-file verification, and deterministic JSON/Markdown rendering. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-input-bank.json --check` |
| firmware-build | **host** | PASS | Two exact pinned Teensy 4.0 no-upload builds plus manifest, map, ownership, capacity, and headroom inspection. | `python3 firmware/tools/build_firmware.py` |
| host-regression | **host** | PASS | Protocol drift, focused target/portable/Python/fake-rig, throughput, static-analysis, documentation/layout, and complete regression gates. | `python3 -m pytest -q` |
| rig-cleanup-safety | **rig** | PASS | Bounded cleanup observations retained by both identity-pinned failing jobs. | `remote-firmware-testing cleanup 90666c7b-4afd-49ac-98e7-225f9f4399da` |
| rig-rate-campaign | **rig** | FAIL | Bounded immutable-HEX remote upload and self-cleaning PySerial validation on the identified Teensy. | `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig-program.py` |
| rig-rate-campaign-reproduction | **rig** | FAIL | A second strictly sequential maximum-rate control submission using the same HEX, source ID, build ID, board identity, and validator. | `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig-program.py` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| adc_pair_rate_hz | 1000000 | adc_pair_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_sample_rate_hz | 4000000 | gpio_sample_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| adc_payload_rate_bytes_per_second | 4000000 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_payload_rate_bytes_per_second | 8000000 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| combined_payload_rate_bytes_per_second | 12000000 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| adc_framed_rate_bytes_per_second | 4047430.830039526 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_framed_rate_bytes_per_second | 8094861.660079052 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| combined_framed_rate_bytes_per_second | 12189723.320158103 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| packet_buffer_capacity_frames | 200 | frame | none | artifact | **host** | ["firmware-build"] |
| flash_used_bytes | 150824 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_headroom_bytes | 34528 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["firmware-build"] |
| gpio_width_bits | 16 | bit | none | artifact_profile | **analytic** | ["aux-input-workload-analysis"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/aux-input-bank","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","source_id":"c1f05b3a2ebfc8b372a176852de0b16740d6739db6897f76de510d01831a7ac8","source_tree":"52a6577e01d8b8d8fb8243e2e131be61a7401677","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","name":"g++","version":"13.3.0"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["branch-isolation"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"682c66df9d4d45b3441d576bc63bad106970c14293ee71186fbf42087fec1fc5","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"a10f0b19a2cc2a07f46b6d0b20c84b67e8f9862ddaaea9f027389db665ed7741","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"6ade9731134a87475672607d746cb2b338fb923ccc72a7aeb04a075a88c9cb95","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"1b9e1cb295ea9975e4e92089dce25c545566713b2e8c10a3bf9c48edd63600ff"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"682c66df9d4d45b3441d576bc63bad106970c14293ee71186fbf42087fec1fc5","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"a10f0b19a2cc2a07f46b6d0b20c84b67e8f9862ddaaea9f027389db665ed7741","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"6ade9731134a87475672607d746cb2b338fb923ccc72a7aeb04a075a88c9cb95","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"1b9e1cb295ea9975e4e92089dce25c545566713b2e8c10a3bf9c48edd63600ff"} | — | ["firmware-build"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"repeat_outputs_byte_identical":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["firmware-build"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"json":"byte-identical","markdown":"byte-identical"} | {"json":"byte-identical","markdown":"byte-identical"} | — | ["evidence-framework","host-regression"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **FAIL** | true | {"bounded_capture":false,"configure":false,"diagnostic":false,"info":true,"start":false,"status":false,"stop_cleanup":true} | Both counting attempts failed in the IDLE diagnostic before CONFIGURE/START. | ["rig-rate-campaign","rig-rate-campaign-reproduction"] |
| synthetic_formulas_exact | Every validated synthetic ADC pair and GPIO sample matches the declared deterministic formula and chronology. | **NOT_RUN** | every ADC code/timestamp and both GPIO bank formulas matched | — | No physical streaming window opened. | [] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **FAIL** | true | {"cleanup_idle":true,"complete_auxiliary_buffer_present":false,"complete_primary_buffer_present":false,"dma_errors_zero":false} | Both banks timed out without a complete DMA buffer and reported DMA errors. | ["rig-rate-campaign","rig-rate-campaign-reproduction"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **FAIL** | true | {"auxiliary_complete_buffers":{"left":0,"right":1},"cache_acquisition":{"left":0,"right":14},"primary_complete_buffers":{"left":0,"right":1}} | Diagnostic ownership/conservation failed before streaming; end-to-end run conservation was not measured. | ["rig-rate-campaign","rig-rate-campaign-reproduction"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **NOT_RUN** | 0 | — | No streaming queue observations exist because START was never reached. | [] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"cleanup_stop_completed":true,"device_idle":true,"final_input_safe":true} | — | ["rig-cleanup-safety"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"candidate_failure_not_infrastructure":true,"cross_branch_claim_absent":true,"highest_profile_absent":true,"not_run_profiles_explicit":true,"signal_integrity_claim_absent":true,"unstimulated_values_not_physical_evidence":true} | — | ["aux-input-workload-analysis","evidence-framework"] |

## Claim limitations

| Limitation | Statement | Applies to evidence levels |
| --- | --- | --- |
| simulation_is_not_physical | Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality. | ["simulated"] |
| build_is_not_target_runtime | A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB. | ["host"] |
| analog_performance_untested | Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing. | ["analytic","simulated","host","rig"] |
| aux_input_stimulus_scope | An unstimulated auxiliary input bank can establish transport and ownership behavior but not external pin order, transition capture, or electrical compatibility. | ["simulated","host","rig"] |
| cross_branch_combinations_untested | Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact. | ["analytic","simulated","host","rig","manual"] |

## Artifacts and reproduction

| Kind | Repository-relative path | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 29580 | `682c66df9d4d45b3441d576bc63bad106970c14293ee71186fbf42087fec1fc5` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 2294388 | `a10f0b19a2cc2a07f46b6d0b20c84b67e8f9862ddaaea9f027389db665ed7741` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 449404 | `6ade9731134a87475672607d746cb2b338fb923ccc72a7aeb04a075a88c9cb95` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 938809 | `1b9e1cb295ea9975e4e92089dce25c545566713b2e8c10a3bf9c48edd63600ff` |
| local-gate | `doc/results/phase-06-aux-input-local-gate.md` | 6368 | `4a2f5cb8ac527c3edb416a03d97573a99d3179c8adb5902ff692b742a5cedf86` |
| rig-campaign-index | `.maestro/playbooks/Working/aux-input-rate-campaign/campaign-index.json` | 3493 | `653750ed44200372f74ed85faa3699caf788daec0755ac3ead832e215fcb0327` |
| rig-job-record | `.maestro/playbooks/Working/aux-input-rate-campaign/01-control-combined-max-smoke/job-record.json` | 837 | `8f56561064b5d4c007cfb73af73d7d75fce12d8f975075217d67dc117b592454` |
| rig-job-record | `.maestro/playbooks/Working/aux-input-rate-campaign/01b-control-combined-max-smoke/job-record.json` | 835 | `648d69fca59c98ccef9d55071b4cddfc0843ba1a26deabb8ee4fc02eaf23b449` |
| rig-job-record | `.maestro/playbooks/Working/aux-input-rate-campaign/02-control-combined-max-smoke/job-record.json` | 834 | `1eb261699b7e2f18210128d1814f76bdb1f5f73a9ad03cda4ee4f3156e1bb254` |
| rig-job-record | `.maestro/playbooks/Working/aux-input-rate-campaign/03-control-combined-max-smoke-reproduction/job-record.json` | 847 | `680bafbc60a434eea8a89ffac8f415076e3b1fddb204b8cc983c642eaaaf5935` |
| rig-job-result | `.maestro/playbooks/Working/aux-input-rate-campaign/01-control-combined-max-smoke/results-response.json` | 561 | `63e826c06bbd7849c8a9142905dc737d5a0f1f3f1d5b41919e7f45028a8088ea` |
| rig-job-result | `.maestro/playbooks/Working/aux-input-rate-campaign/01b-control-combined-max-smoke/results-response.json` | 2401 | `b739c6df8bfd8d4e40449378f5c0e63bbc24790171d4b1e01ac4319acb3dc1fe` |
| rig-job-result | `.maestro/playbooks/Working/aux-input-rate-campaign/02-control-combined-max-smoke/results-response.json` | 4704 | `e92cd568ad7cc91304c9b206e5a7c68217ca669925d16d7036d1204b83419224` |
| rig-job-result | `.maestro/playbooks/Working/aux-input-rate-campaign/03-control-combined-max-smoke-reproduction/results-response.json` | 4704 | `90ba3890694363a4949bcf7afd4b116e69b3da8bd66cf5878c49dee27f0bc3b4` |

### Commands

- `aux-input-workload-analysis` (analytic): `python3 daq_api/examples/aux_input_matrix.py`
- `branch-isolation` (host): `git merge-base b23004defeca465da0ae2d2884c4fef71979e5d4 e36f94dc7de82f760b2bbe18bc94fa971dc073e6`
- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-input-bank.json --check`
- `firmware-build` (host): `python3 firmware/tools/build_firmware.py`
- `host-regression` (host): `python3 -m pytest -q`
- `rig-cleanup-safety` (rig): `remote-firmware-testing cleanup 90666c7b-4afd-49ac-98e7-225f9f4399da`
- `rig-rate-campaign` (rig): `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig-program.py`
- `rig-rate-campaign-reproduction` (rig): `remote-firmware-testing submit teensy:avr:teensy40 firmware.ino.hex rig-program.py`
