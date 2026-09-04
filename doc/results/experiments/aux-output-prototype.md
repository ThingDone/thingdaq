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
  - "[[Hardware-Safety]]"
---

# ThingDAQ Auxiliary Output Bank Experiment

## Outcome

**PASS**

The isolated preloaded-output protocol, Python client, deterministic simulator, and portable C++ engine passed every declared local prototype gate while the target adapter remains deliberately absent and D16-D23 remain inputs in the unchanged default firmware.

### Prototype contract and fixed budget

| Item | Exact result |
| --- | ---: |
| Logical output rate / timestamp period | 1,000,000 states/s / 8 ticks |
| Canonical capacity | 1,024 segments (8,192 B) |
| Cooperative expansion bound | 1 block / service visit; 1,016 states / block |
| Four-block DMA candidate | 16,384 B (128 B descriptors + 16,256 B states) |
| Total program + DMA candidate | 24,576 B exchanged for 6 packet pages |
| Candidate packet retention | 194 pages / 98.164 ms nominal combined framing |

### Local validation result

| Gate | Exact result |
| --- | --- |
| Simulator determinism | Two 2,598-byte transcripts byte-identical; SHA-256 `a005c0d49502443a45da4dd416a30168029aa8673ca809c73a4a587230b351e6` |
| Output expansion benchmark | 305,662,189.756 and 331,904,014.333 states/s; minimum 305.662x host headroom over 1 MHz |
| Portable service bound | Exactly one 1,016-state block per cooperative service visit |
| Complete regression | 486 passed; 14,527 subtests |
| Pinned default build | Two byte-identical 600 MHz no-upload builds; build `thingdaq-3f3391603dc7c763` |
| Default linker budget | 95,084 B code; 23,496 B data; 34,528 B RAM1 locals/stack; 4,096 B RAM2 heap |

The expansion rate is a host measurement, the memory repartition is a linker-accounted candidate, and all transition timing is simulated. No target output registers, USB runtime, D16-D23 drive, pad-level timing, voltage, jitter, signal-integrity, loopback, or cross-branch combination has been exercised or accepted.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/aux-output-bank |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | 4dc24bc1de0ae0151bfdbc35c9df369d23085e98 |
| source_tree | b884eb586654c80eb08332e37c9e315a17f4252b |
| source_clean | true |
| source_id | 3f3391603dc7c763e237bed5490ddd6bdf4d49a625796058150ec847272a4db4 |
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
| aux-output-simulator-demonstration | **simulated** | PASS | public protocol-v2 upload/arm/status/CLEAR commands, explicit common-clock advancement, bounded transition/state queries, combined ADC/GPIO block reads, STOP, and injected underrun | `python daq_api/examples/preloaded_output.py` |
| branch-isolation | **host** | PASS | Git object checks prove exact baseline descent and identify the isolated eight-commit experiment history. | `git merge-base --is-ancestor experiment/baseline-2026-09-01 HEAD` |
| evidence-framework | **host** | PASS | Fail-closed shared schema validation, referenced-file/hash verification, normalization, and repeated deterministic rendering. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-output-prototype.json --json-output doc/results/experiments/aux-output-prototype.json --markdown-output doc/results/experiments/aux-output-prototype.md --check` |
| firmware-build | **host** | PASS | Two exact pinned Teensy 4.0 600 MHz no-upload builds plus byte comparison, manifest validation, linker-map inspection, and memory/resource accounting. | `python3 firmware/tools/build_firmware.py` |
| host-regression | **host** | PASS | Generated drift, focused output, documentation/layout, Ruff, MyPy, and complete Python/portable-host-C++ regression gates. | `python -m pytest -q` |
| output-expansion-benchmark | **host** | PASS | Two strict C++17/O3/LTO runs of the real RLE-to-GPIO1-toggle expansion path, including DMA completion, bounded one-block refill, cache, and critical-section boundaries. | `python -m pytest -q -s firmware/tests/test_digital_output_throughput.py` |
| output-memory-budget | **analytic** | PASS | Exact packet-page exchange and fixed C++ storage equations checked against the accepted default linker map. | `python -m pytest -q firmware/tests/test_digital_output_engine.py` |
| portable-output-validation | **host** | PASS | Strict host-compiled ownership, wrap, refill, finite/infinite, cancellation, underrun, generation reuse, transactional START, STOP/fault ordering, and cross-language conformance gates. | `python -m pytest -q firmware/tests/test_digital_output_engine.py firmware/tests/test_digital_output_conformance.py` |
| protocol-v1-compatibility | **host** | PASS | Byte comparison preserves the canonical v1 contract, generated Python/C++ constants, and all frozen v1 fixtures exactly. | `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| timestamp_clock_hz | 8000000 | hertz | none | artifact | **simulated** | ["aux-output-simulator-demonstration"] |
| output_state_rate_hz | 1000000 | hertz | streaming_elapsed_seconds | output_window | **analytic** | ["output-memory-budget"] |
| output_state_rate_hz | 305662189.756 | hertz | streaming_elapsed_seconds | output_window | **host** | ["output-expansion-benchmark"] |
| output_state_rate_hz | 1000000.0 | hertz | streaming_elapsed_seconds | output_window | **simulated** | ["aux-output-simulator-demonstration"] |
| output_underruns | 0 | event | none | run | **host** | ["output-expansion-benchmark"] |
| output_underruns | 1 | event | none | run | **simulated** | ["aux-output-simulator-demonstration"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | true | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/aux-output-bank","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"4dc24bc1de0ae0151bfdbc35c9df369d23085e98","source_id":"3f3391603dc7c763e237bed5490ddd6bdf4d49a625796058150ec847272a4db4","source_tree":"b884eb586654c80eb08332e37c9e315a17f4252b","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","name":"g++","version":"13.3.0"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["branch-isolation"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"0f7bd57e137439b08c1c8201e0cdef3f02fd7a010f98e1f361238089549e3316","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"6edfcb2147c0da1f89b675c623a3a9b27776d8ff759da45f54ae4989f84fd421","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"6ab5b38995003d36b2266542c388dbc6ef7843869b5ed0c82a03430e505b6b13","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"c2f3f495dce7c81bea35b658ae7962b384d9e63cac92b23cb88265db0c081743"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"0f7bd57e137439b08c1c8201e0cdef3f02fd7a010f98e1f361238089549e3316","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"6edfcb2147c0da1f89b675c623a3a9b27776d8ff759da45f54ae4989f84fd421","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"6ab5b38995003d36b2266542c388dbc6ef7843869b5ed0c82a03430e505b6b13","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"c2f3f495dce7c81bea35b658ae7962b384d9e63cac92b23cb88265db0c081743"} | — | ["firmware-build"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"network_unused":true,"repeat_outputs_byte_identical":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["firmware-build"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"canonical_json_render":"byte-identical","canonical_markdown_render":"byte-identical","simulator_stdout_run_1":"a005c0d49502443a45da4dd416a30168029aa8673ca809c73a4a587230b351e6","simulator_stdout_run_2":"a005c0d49502443a45da4dd416a30168029aa8673ca809c73a4a587230b351e6"} | {"canonical_json_render":"byte-identical","canonical_markdown_render":"byte-identical","simulator_stdout_run_1":"a005c0d49502443a45da4dd416a30168029aa8673ca809c73a4a587230b351e6","simulator_stdout_run_2":"a005c0d49502443a45da4dd416a30168029aa8673ca809c73a4a587230b351e6"} | — | ["evidence-framework","host-regression"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **PASS** | true | {"bounded_adc_gpio_capture":true,"clear_release":true,"configure_combined":true,"fault_status":true,"finite_completion":true,"infinite_stop_hold":true,"output_arm":true,"output_begin_append_commit":true,"start_common_epoch":true} | — | ["aux-output-simulator-demonstration"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **PASS** | true | {"combined_blocks_present":true,"injected_underrun_reconciled":true,"run_ids_exact":true,"unexpected_loss_events_zero":true} | — | ["aux-output-simulator-demonstration"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **PASS** | true | {"combined_blocks":{"left":6,"right":6},"injected_faults":{"left":1,"right":1},"scenarios":{"left":3,"right":3},"transitions":{"left":18,"right":18}} | — | ["aux-output-simulator-demonstration"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **PASS** | 4096 | 8 | — | ["aux-output-simulator-demonstration"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"all_output_banks_disabled":true,"all_output_pins_released":true,"all_transports_closed":true,"fault_clear_empty":true,"finite_clear_empty":true,"infinite_clear_empty":true} | — | ["aux-output-simulator-demonstration"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"cross_branch_acceptance_absent":true,"host_benchmark_labeled_nontarget":true,"memory_budget_labeled_candidate":true,"physical_fixture_declaration_absent":true,"physical_output_claim_absent":true,"simulated_timing_labeled":true} | — | ["aux-output-simulator-demonstration","evidence-framework","output-expansion-benchmark","output-memory-budget"] |

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
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 13108 | `0f7bd57e137439b08c1c8201e0cdef3f02fd7a010f98e1f361238089549e3316` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1823268 | `6edfcb2147c0da1f89b675c623a3a9b27776d8ff759da45f54ae4989f84fd421` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 357227 | `6ab5b38995003d36b2266542c388dbc6ef7843869b5ed0c82a03430e505b6b13` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 850916 | `c2f3f495dce7c81bea35b658ae7962b384d9e63cac92b23cb88265db0c081743` |

### Commands

- `aux-output-simulator-demonstration` (simulated): `python daq_api/examples/preloaded_output.py`
- `branch-isolation` (host): `git merge-base --is-ancestor experiment/baseline-2026-09-01 HEAD`
- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/aux-output-prototype.json --json-output doc/results/experiments/aux-output-prototype.json --markdown-output doc/results/experiments/aux-output-prototype.md --check`
- `firmware-build` (host): `python3 firmware/tools/build_firmware.py`
- `host-regression` (host): `python -m pytest -q`
- `output-expansion-benchmark` (host): `python -m pytest -q -s firmware/tests/test_digital_output_throughput.py`
- `output-memory-budget` (analytic): `python -m pytest -q firmware/tests/test_digital_output_engine.py`
- `portable-output-validation` (host): `python -m pytest -q firmware/tests/test_digital_output_engine.py firmware/tests/test_digital_output_conformance.py`
- `protocol-v1-compatibility` (host): `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h`
