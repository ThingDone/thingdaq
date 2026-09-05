---
type: report
title: "ThingDAQ Auxiliary Input Bank Experiment"
created: 2026-09-02
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
  - "[[Experiment-Baseline]]"
  - "[[Hardware-Safety]]"
  - "[[Quickstart]]"
---

# ThingDAQ Auxiliary Input Bank Experiment

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

## Outcome

**PASS**

The isolated protocol/Python/simulator/portable-C++ prototype passed every declared local gate while preserving protocol v1 and the default eight-input path. The full-rate 12 MB/s payload value remains an analytic load hypothesis, not physical USB or target-runtime acceptance.

### Exact baseline ancestry and isolation

| Field | Exact result |
| --- | --- |
| Baseline / merge base | `b23004defeca465da0ae2d2884c4fef71979e5d4` |
| Prototype source commit | `cfe41fe556c166c3bfb6d8473f06c1dd922b0cd0` |
| Source tree | `680a4a0840c4408cb5f6178caa3d2d3d518fe4f0` |
| Baseline-to-source rev-list | 0 behind, 7 ahead |
| Foreign experiment ancestry | clock=false, RLE=false |
| Protocol v1 | 27 canonical/generated/fixture paths byte-identical |

### Declared GPIO layouts

| Mode | GPIO wire bits | Item | GPIO items/frame | ADC pairs/frame | GPIO / ADC frame bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| `DISABLED` | D6-D13 -> 0-7 | 1 B / 8 bit | 4,048 | 1,012 | 4,096 / 4,096 |
| `INPUT` | D6-D13 -> 0-7; D16-D23 -> 8-15 (little-endian) | 2 B / 16 bit | 2,024 | 506 | 4,096 / 2,072 |

The auxiliary port order is GPIO1 bits `23,22,17,16,26,27,24,25` with mask `0x0FC30000`; these are provisional portable-contract values and have not been exercised on silicon.

### Exact rate profiles

| Profile | ADC pairs/s | GPIO samples/s | ADC/GPIO period ticks | ADC1 phase ticks | PIT0 load | Coverage ticks (8/16 bit) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ADC_1MHZ_GPIO_4MHZ` | 1,000,000 | 4,000,000 | 8 / 2 | 4 | 5 | 8,096 / 4,048 |
| `ADC_500KHZ_GPIO_2MHZ` | 500,000 | 2,000,000 | 16 / 4 | 8 | 11 | 16,192 / 8,096 |
| `ADC_250KHZ_GPIO_1MHZ` | 250,000 | 1,000,000 | 32 / 8 | 16 | 23 | 32,384 / 16,192 |
| `ADC_125KHZ_GPIO_500KHZ` | 125,000 | 500,000 | 64 / 16 | 32 | 47 | 64,768 / 32,384 |

### Analytic payload and complete-frame load

| Scenario | Mode | ADC/GPIO rate | Width | Coverage ticks | Payload B/s | Framed B/s (exact) | Framed increase |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `gpio-only-8bit-4mhz` | `DISABLED` | - / 4,000,000 | 8 | 8,096 | 4000000 | 1024000000/253 | 1 (0.000000%) |
| `gpio-only-16bit-4mhz` | `INPUT` | - / 4,000,000 | 16 | 4,048 | 8000000 | 2048000000/253 | 2 (100.000000%) |
| `combined-8bit-1mhz_gpio_4mhz` | `DISABLED` | 1,000,000 / 4,000,000 | 8 | 8,096 | 8000000 | 2048000000/253 | 1 (0.000000%) |
| `combined-16bit-1mhz_gpio_4mhz` | `INPUT` | 1,000,000 / 4,000,000 | 16 | 4,048 | 12000000 | 3084000000/253 | 771/512 (50.585938%) |
| `combined-8bit-500khz_gpio_2mhz` | `DISABLED` | 500,000 / 2,000,000 | 8 | 16,192 | 4000000 | 1024000000/253 | 1 (0.000000%) |
| `combined-16bit-500khz_gpio_2mhz` | `INPUT` | 500,000 / 2,000,000 | 16 | 8,096 | 6000000 | 1542000000/253 | 771/512 (50.585938%) |
| `combined-8bit-250khz_gpio_1mhz` | `DISABLED` | 250,000 / 1,000,000 | 8 | 32,384 | 2000000 | 512000000/253 | 1 (0.000000%) |
| `combined-16bit-250khz_gpio_1mhz` | `INPUT` | 250,000 / 1,000,000 | 16 | 16,192 | 3000000 | 771000000/253 | 771/512 (50.585938%) |
| `combined-8bit-125khz_gpio_500khz` | `DISABLED` | 125,000 / 500,000 | 8 | 64,768 | 1000000 | 256000000/253 | 1 (0.000000%) |
| `combined-16bit-125khz_gpio_500khz` | `INPUT` | 125,000 / 500,000 | 16 | 32,384 | 1500000 | 385500000/253 | 771/512 (50.585938%) |

### Simulator and host evidence

| Gate | Exact result |
| --- | --- |
| Simulator matrix | 10 scenarios, 4 formulas, 40 captures, 64 ADC frames, 80 GPIO frames; 48,576 ADC pairs, 242,880 primary samples, and 80,960 auxiliary samples validated |
| Simulator determinism | Two stdout runs SHA-256 `115710528a32c141c4ec1cf4171597be3ecfa5439f2394522bb9c430923df4d6`; two JSON/Markdown pairs byte-identical |
| v2 parser run 1 | 64 KiB / 16 KiB / 1 KiB randomized chunks: 2.183376x / 2.115956x / 1.949990x framed-load headroom |
| v2 parser run 2 | 64 KiB / 16 KiB / 1 KiB randomized chunks: 2.147679x / 2.097541x / 1.964486x framed-load headroom |
| Dual-bank packer | 1,722.947 and 1,786.668 MB/s; 215.368x and 223.334x over the 8 MB/s GPIO payload target |
| Portable conservation | 256 profile IDs, 65,536 byte pairs, 2,048 generations across wrap, pressure/skew/STOP/rollback/fault tails, and 224 cross-language cases all exact |
| Complete regression | 485 passed, 9 expected skips, 15,909 subtests |
| Pinned default build | Two byte-identical 600 MHz no-upload builds; build `thingdaq-206657dc04b89960`; 131,068 B flash, 33,344 B RAM1 and 4,096 B RAM2 headroom |

Portable raw storage is fixed at 64,768 bytes plus a 64-byte overflow sink; host object sizes are 728 bytes for join state and 264 bytes for packer state. The clean default ELF contains no linked auxiliary joiner, packer, or variable-rate scheduler symbol.

No target register adapter, live USB run, physical D16-D23 stimulus, external pin-order/timing check, electrical validation, ADC performance measurement, or cross-branch combination has run. Those limitations remain requirements for Phase 06 rather than claims of this prototype.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/aux-input-bank |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | cfe41fe556c166c3bfb6d8473f06c1dd922b0cd0 |
| source_tree | 680a4a0840c4408cb5f6178caa3d2d3d518fe4f0 |
| source_clean | true |
| source_id | 206657dc04b899604e1c3d2865848749b4ecec3de511d2a7ed7f5fc7c51e980d |
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
| **simulated** | Execution against the deterministic in-memory model; no firmware target, USB link, or electrical behavior is implied. | false |
| **host** | Execution on the host, including native tests, benchmarks, and no-upload firmware builds; target runtime behavior is not implied. | false |

### Evidence records

| ID | Evidence level | Result | Method | Command |
| --- | --- | --- | --- | --- |
| aux-input-simulator-matrix | **simulated** | PASS | Two deterministic bounded public-API matrices covering every exact mode/profile and four independent GPIO formulas with exact ADC phase, timestamps, STATUS conservation, STOP, and closed cleanup. | `python daq_api/examples/aux_input_matrix.py --frames-per-stream 2 --pattern all-zero --pattern walking-bit --pattern counter --pattern high-transition` |
| aux-input-workload-analysis | **analytic** | PASS | Exact rational workload calculation from the generated v2 layouts, all four rate profiles, item counts, and complete-frame sizes. | `python daq_api/examples/aux_input_matrix.py --frames-per-stream 2 --pattern all-zero --pattern walking-bit --pattern counter --pattern high-transition` |
| branch-isolation | **host** | PASS | Git object checks prove exact baseline descent and exclude the independent clock and RLE histories. | `git merge-base --is-ancestor experiment/baseline-2026-09-01 HEAD` |
| evidence-framework | **host** | PASS | Fail-closed shared schema validation, referenced-file/hash verification, normalization, and repeated deterministic rendering. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-input-prototype.json --json-output doc/results/experiments/aux-input-prototype.json --markdown-output doc/results/experiments/aux-input-prototype.md --check` |
| firmware-build | **host** | PASS | Two exact pinned Teensy 4.0 600 MHz no-upload builds plus manifest, map, memory, and linked-symbol inspection. | `python3 firmware/tools/build_firmware.py` |
| host-packer-benchmark | **host** | PASS | Two strict C++17/O3/LTO executions of the real dual-bank shift/mask gather and little-endian serialization path. | `python -m pytest -q -s firmware/tests/test_aux_input_packer_throughput.py` |
| host-parser-benchmark | **host** | PASS | Two full-rate protocol-v2 parser, typed-block, chronology, and formula-validation runs over deterministic randomized chunk profiles. | `python -m pytest -q -s daq_api/tests/test_aux_input_throughput.py` |
| host-regression | **host** | PASS | Generated drift, focused auxiliary, documentation/layout, Ruff, MyPy, and complete Python/portable-host-C++ regression gates. | `python -m pytest -q` |
| portable-conservation | **host** | PASS | Strict host-compiled scheduler, paired-ring, packer, packet, pressure, STOP-tail, and Python/C++ golden-equivalence gates. | `python -m pytest -q firmware/tests/test_aux_input_portable.py firmware/tests/test_aux_input_stress.py daq_api/tests/test_aux_input_cross_language.py` |
| protocol-v1-compatibility | **host** | PASS | Byte comparison of the canonical v1 contract and all 26 generated v1 outputs against the immutable baseline. | `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| adc_pairs_observed | 48576 | adc_pair | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| gpio_samples_observed | 242880 | gpio_sample | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| adc_frames_observed | 64 | frame | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| gpio_frames_observed | 80 | frame | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| combined_payload_bytes | 518144 | byte | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| combined_framed_bytes | 525056 | byte | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| adc_pair_rate_hz | 1000000 | adc_pair_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_sample_rate_hz | 4000000 | gpio_sample_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| adc_payload_rate_bytes_per_second | 4000000.0 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_payload_rate_bytes_per_second | 8000000.0 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_payload_rate_bytes_per_second | 1722947000.0 | byte_per_second | streaming_elapsed_seconds | streaming_window | **host** | ["host-packer-benchmark"] |
| combined_payload_rate_bytes_per_second | 12000000.0 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| adc_framed_rate_bytes_per_second | 4094861.6600790513 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| gpio_framed_rate_bytes_per_second | 8094861.660079052 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| combined_framed_rate_bytes_per_second | 12189723.320158103 | byte_per_second | streaming_elapsed_seconds | streaming_window | **analytic** | ["aux-input-workload-analysis"] |
| combined_framed_rate_bytes_per_second | 23769843.309129972 | byte_per_second | streaming_elapsed_seconds | streaming_window | **host** | ["host-parser-benchmark"] |
| sequence_gap_frames | 0 | frame | none | streaming_window | **simulated** | ["aux-input-simulator-matrix"] |
| host_queue_drops | 0 | event | none | run | **simulated** | ["aux-input-simulator-matrix"] |
| parser_errors | 0 | event | none | run | **simulated** | ["aux-input-simulator-matrix"] |
| transport_errors | 0 | event | none | run | **simulated** | ["aux-input-simulator-matrix"] |
| conservation_failures | 0 | event | none | final_status | **simulated** | ["aux-input-simulator-matrix"] |
| flash_used_bytes | 131068 | byte | none | artifact | **host** | ["firmware-build"] |
| flash_headroom_bytes | 1900548 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_used_bytes | 490944 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_headroom_bytes | 33344 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_used_bytes | 520192 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["firmware-build"] |
| cpu_clock_hz | 600000000 | hertz | none | artifact | **host** | ["firmware-build"] |
| ipg_clock_hz | 150000000 | hertz | none | artifact | **analytic** | ["aux-input-workload-analysis"] |
| adc_clock_hz | 37500000 | hertz | none | artifact | **analytic** | ["aux-input-workload-analysis"] |
| pit_clock_hz | 24000000 | hertz | none | artifact | **analytic** | ["aux-input-workload-analysis"] |
| timestamp_clock_hz | 8000000 | hertz | none | artifact | **analytic** | ["aux-input-workload-analysis"] |
| adc_phase_ticks | 4 | tick | none | artifact | **analytic** | ["aux-input-workload-analysis"] |
| gpio_width_bits | 16 | bit | none | artifact_profile | **analytic** | ["aux-input-workload-analysis"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/aux-input-bank","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"cfe41fe556c166c3bfb6d8473f06c1dd922b0cd0","source_id":"206657dc04b899604e1c3d2865848749b4ecec3de511d2a7ed7f5fc7c51e980d","source_tree":"680a4a0840c4408cb5f6178caa3d2d3d518fe4f0","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","name":"g++","version":"13.3.0"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["branch-isolation"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"6b5e5659c8a80aeb8978fea1738f0912762bba9c247592fe541a5459057016cd","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"8ff953c9783ff2cac580f4557551f35671b41b380f2aa75c56ad5f90efe1fa8d","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"c2c5077972e7d571b63f5d51ef398feaf4605304f5aa7c5afa1f154867e12129","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"78c1f1be07f9cd00e77a6d09898797dd1b4013f62c22c3cbe02f73a957c4ed67"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"6b5e5659c8a80aeb8978fea1738f0912762bba9c247592fe541a5459057016cd","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"8ff953c9783ff2cac580f4557551f35671b41b380f2aa75c56ad5f90efe1fa8d","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"c2c5077972e7d571b63f5d51ef398feaf4605304f5aa7c5afa1f154867e12129","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"78c1f1be07f9cd00e77a6d09898797dd1b4013f62c22c3cbe02f73a957c4ed67"} | — | ["firmware-build"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"network_unused":true,"repeat_outputs_byte_identical":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["firmware-build"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"canonical_json_render":"byte-identical","canonical_markdown_render":"byte-identical","matrix_stdout_run_1":"115710528a32c141c4ec1cf4171597be3ecfa5439f2394522bb9c430923df4d6","matrix_stdout_run_2":"115710528a32c141c4ec1cf4171597be3ecfa5439f2394522bb9c430923df4d6","temporary_json_run_1":"a2eefc4bcb6b6574025b0e99dd05bb022281cc0c0e62f64e135983901c74e0a8","temporary_json_run_2":"a2eefc4bcb6b6574025b0e99dd05bb022281cc0c0e62f64e135983901c74e0a8","temporary_markdown_run_1":"46184d10f0b4632509f82bb4f235bd5bfe9c849d8fd118301a1bfd8a67b20883","temporary_markdown_run_2":"46184d10f0b4632509f82bb4f235bd5bfe9c849d8fd118301a1bfd8a67b20883"} | {"canonical_json_render":"byte-identical","canonical_markdown_render":"byte-identical","matrix_stdout_run_1":"115710528a32c141c4ec1cf4171597be3ecfa5439f2394522bb9c430923df4d6","matrix_stdout_run_2":"115710528a32c141c4ec1cf4171597be3ecfa5439f2394522bb9c430923df4d6","temporary_json_run_1":"a2eefc4bcb6b6574025b0e99dd05bb022281cc0c0e62f64e135983901c74e0a8","temporary_json_run_2":"a2eefc4bcb6b6574025b0e99dd05bb022281cc0c0e62f64e135983901c74e0a8","temporary_markdown_run_1":"46184d10f0b4632509f82bb4f235bd5bfe9c849d8fd118301a1bfd8a67b20883","temporary_markdown_run_2":"46184d10f0b4632509f82bb4f235bd5bfe9c849d8fd118301a1bfd8a67b20883"} | — | ["evidence-framework","host-regression"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **PASS** | true | {"bounded_capture":true,"capture_matrix_complete":true,"close":true,"configure":true,"info":true,"scenario_matrix_complete":true,"start":true,"status":true,"stop":true} | — | ["aux-input-simulator-matrix"] |
| synthetic_formulas_exact | Every validated synthetic ADC pair and GPIO sample matches the declared deterministic formula and chronology. | **PASS** | every ADC code/timestamp and both GPIO bank formulas matched | every ADC code/timestamp and both GPIO bank formulas matched | — | ["aux-input-simulator-matrix"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **PASS** | true | {"firmware_drops_zero":true,"host_queue_drops_zero":true,"parser_errors_zero":true,"sequence_gaps_zero":true,"transport_errors_zero":true} | — | ["aux-input-simulator-matrix"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **PASS** | true | {"adc_frames":{"left":64,"right":64},"adc_pairs":{"left":48576,"right":48576},"auxiliary_gpio_samples":{"left":80960,"right":80960},"capture_selection":{"left":40,"right":40},"framed_bytes":{"left":525056,"right":525056},"gpio_frames":{"left":80,"right":80},"payload_bytes":{"left":518144,"right":518144},"primary_gpio_samples":{"left":242880,"right":242880},"scenario_selection":{"left":10,"right":10},"status_framed_bytes":true,"status_payload_bytes":true} | — | ["aux-input-simulator-matrix"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **PASS** | 0 | 0 | — | ["aux-input-simulator-matrix"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"device_idle":true,"reader_closed":true,"stream_mask_empty":true,"transport_closed":true} | — | ["aux-input-simulator-matrix"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"analytic_load_labeled_hypothesis":true,"cross_branch_acceptance_absent":true,"external_stimulus_acceptance_absent":true,"host_benchmarks_labeled_nontarget":true,"physical_usb_acceptance_absent":true,"simulation_labeled_nonphysical":true,"target_register_acceptance_absent":true} | — | ["aux-input-simulator-matrix","aux-input-workload-analysis","evidence-framework"] |

## Claim limitations

| Limitation | Statement | Applies to evidence levels |
| --- | --- | --- |
| simulation_is_not_physical | Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality. | ["simulated"] |
| build_is_not_target_runtime | A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB. | ["host"] |
| analog_performance_untested | Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing. | ["analytic","simulated","host","rig"] |
| external_gpio_timing_untested | Without a declared external stimulus, evidence does not establish pad mapping, voltage thresholds, transition timing, jitter, or signal integrity. | ["analytic","simulated","host","rig"] |
| live_usb_untested | In-memory transport and host-only evidence do not establish sustained behavior on a live USB controller or operating system. | ["simulated","host"] |
| aux_input_stimulus_scope | An unstimulated auxiliary input bank can establish transport and ownership behavior but not external pin order, transition capture, or electrical compatibility. | ["simulated","host","rig"] |
| cross_branch_combinations_untested | Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact. | ["analytic","simulated","host","rig","manual"] |

## Artifacts and reproduction

| Kind | Repository-relative path | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 13284 | `6b5e5659c8a80aeb8978fea1738f0912762bba9c247592fe541a5459057016cd` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1883044 | `8ff953c9783ff2cac580f4557551f35671b41b380f2aa75c56ad5f90efe1fa8d` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 368747 | `c2c5077972e7d571b63f5d51ef398feaf4605304f5aa7c5afa1f154867e12129` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 875701 | `78c1f1be07f9cd00e77a6d09898797dd1b4013f62c22c3cbe02f73a957c4ed67` |

### Commands

- `aux-input-simulator-matrix` (simulated): `python daq_api/examples/aux_input_matrix.py --frames-per-stream 2 --pattern all-zero --pattern walking-bit --pattern counter --pattern high-transition`
- `aux-input-workload-analysis` (analytic): `python daq_api/examples/aux_input_matrix.py --frames-per-stream 2 --pattern all-zero --pattern walking-bit --pattern counter --pattern high-transition`
- `branch-isolation` (host): `git merge-base --is-ancestor experiment/baseline-2026-09-01 HEAD`
- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-input-prototype.json --json-output doc/results/experiments/aux-input-prototype.json --markdown-output doc/results/experiments/aux-input-prototype.md --check`
- `firmware-build` (host): `python3 firmware/tools/build_firmware.py`
- `host-packer-benchmark` (host): `python -m pytest -q -s firmware/tests/test_aux_input_packer_throughput.py`
- `host-parser-benchmark` (host): `python -m pytest -q -s daq_api/tests/test_aux_input_throughput.py`
- `host-regression` (host): `python -m pytest -q`
- `portable-conservation` (host): `python -m pytest -q firmware/tests/test_aux_input_portable.py firmware/tests/test_aux_input_stress.py daq_api/tests/test_aux_input_cross_language.py`
- `protocol-v1-compatibility` (host): `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h`
