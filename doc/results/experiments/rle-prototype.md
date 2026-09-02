---
type: report
title: "ThingDAQ Negotiated RLE Experiment"
created: 2026-09-02
tags:
  - thingdaq
  - experiment-evidence
  - rle-streaming
related:
  - "[[Evidence-Index]]"
  - "[[Protocol-V1]]"
  - "[[System-Overview]]"
  - "[[baseline]]"
  - "[[ADR-006-Experimental-RLE-Streaming]]"
  - "[[Experiment-Baseline]]"
  - "[[Quickstart]]"
---

# ThingDAQ Negotiated RLE Experiment

## Outcome

**PASS**

The negotiated protocol-v2 Python/simulator prototype passed every local correctness,
no-expansion, bounded-memory, decode-headroom, build, and compatibility gate.
Compression remains opt-in and simulated/host-only.

### Exact corpus compression

All ratios retain their measured complete-wire numerator and RAW complete-wire denominator.

| Workload | RAW / selected payload bytes | RAW / selected wire bytes | Exact wire ratio | Runs | RLE / fallback frames |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gpio-constant` | 32,384 / 24 | 32,768 / 408 | 408/32768 = 0.012451172 | 8 | 8 / 0 |
| `gpio-long-digital-holds` | 32,384 / 213 | 32,768 / 597 | 597/32768 = 0.018218994 | 71 | 8 / 0 |
| `gpio-sparse-single-bit-changes` | 32,384 / 48 | 32,768 / 432 | 432/32768 = 0.013183594 | 16 | 8 / 0 |
| `gpio-alternating-bytes` | 32,384 / 32,384 | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 32,384 | 0 / 8 |
| `gpio-pseudo-random-bytes` | 32,384 / 32,384 | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 32,246 | 0 / 8 |
| `adc-constant-pairs` | 32,384 / 48 | 32,768 / 432 | 432/32768 = 0.013183594 | 8 | 8 / 0 |
| `adc-independent-slow-channels` | 32,384 / 9,936 | 32,768 / 10,320 | 10320/32768 = 0.314941406 | 1,656 | 8 / 0 |
| `adc-quantization-noise` | 32,384 / 32,384 | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 7,953 | 0 / 8 |
| `adc-high-entropy` | 32,384 / 32,384 | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 8,096 | 0 / 8 |

### Host codec throughput

Values are the slowest retained batch across all nine workloads for each path; headroom uses the exact 4,000,000 logical B/s per-stream denominator.

| Run | Path | Limiting workload | Minimum logical B/s | Target headroom |
| ---: | --- | --- | ---: | ---: |
| 1 | `raw_encode` | `adc-high-entropy` | 39828880.974819 | 9.957220244x |
| 1 | `rle_auto_encode` | `gpio-pseudo-random-bytes` | 3772978.487382 | 0.943244622x |
| 1 | `raw_decode` | `gpio-pseudo-random-bytes` | 6094371.687918 | 1.523592922x |
| 1 | `rle_auto_decode` | `gpio-alternating-bytes` | 6181090.854221 | 1.545272714x |
| 2 | `raw_encode` | `adc-quantization-noise` | 40959654.439391 | 10.239913610x |
| 2 | `rle_auto_encode` | `gpio-pseudo-random-bytes` | 3439740.145490 | 0.859935036x |
| 2 | `raw_decode` | `gpio-long-digital-holds` | 6195371.939035 | 1.548842985x |
| 2 | `rle_auto_decode` | `gpio-alternating-bytes` | 5277575.761053 | 1.319393940x |

### Determinism, compatibility, and build closure

| Gate | Exact observation |
| --- | --- |
| Simulator demonstration | Two byte-identical outputs; SHA-256 `d958c5a9f59b57dbcf4638b4ab3413ee1f758694462a368f39f43d0c65558aee` |
| Corpus normalization | Two byte-identical timing-independent outputs; SHA-256 `48af28678522ed58879db3aa01ad4e5b733f56b25a007d09f4e62301dfda531a` |
| Complete regression | 487 passed, 8 expected skips, 14,493 subtests |
| Focused RLE/docs gate | 73 passed, 1 expected skip, 1,802 subtests |
| Ruff / MyPy | 140 files formatted and lint-clean; 29 sources type-clean |
| Protocol v1 | 27 source/generated/fixture paths byte-identical to baseline; fixture tree `58f3800a8450714f58ec486249521aacb68eb2e4` |
| Pinned firmware | 600 MHz, USB Serial, `-O2`; flash 126,972 B, RAM1 489,760 B, RAM2 520,192 B |

The firmware build is a no-upload compile of the unchanged default v1 path. The isolated generated v2 constants header changes build identity bookkeeping, so this report does not claim a byte-identical firmware artifact or target-side RLE execution.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/rle-streaming |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | 3aeefc435f1e1d020772670467ea60227ad7aeaa |
| source_tree | 81417d52c6e57aa59c027ba8206716f48579b9f8 |
| source_clean | true |
| source_id | 07df743de1619a41d55a929a693510e6497fa2d22783ac92ba84ad762e62b5dc |
| protocol_contract_path | protocol/protocol-v1.json |
| protocol_version | 1 |
| protocol_sha256 | 014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222 |

### Toolchains

| Name | Version | Identity |
| --- | --- | --- |
| arduino-cli | 1.4.1 | arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z |
| arm-none-eabi-g++ | 15.2.1 | arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203 |
| python | 3.12.3 | CPython 3.12.3 |
| teensy-core | 1.62.0 | teensy:avr 1.62.0 |

## Evidence levels

| Label | Meaning | Physical claims allowed |
| --- | --- | ---: |
| **simulated** | Execution against the deterministic in-memory model; no firmware target, USB link, or electrical behavior is implied. | false |
| **host** | Execution on the host, including native tests, benchmarks, and no-upload firmware builds; target runtime behavior is not implied. | false |

### Evidence records

| ID | Evidence level | Result | Method | Command |
| --- | --- | --- | --- | --- |
| evidence-framework | **host** | PASS | Fail-closed shared schema validation, file/hash verification, normalization, and repeat rendering. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/rle-prototype.json --json-output doc/results/experiments/rle-prototype.json --markdown-output doc/results/experiments/rle-prototype.md --check` |
| firmware-build | **host** | PASS | Pinned Teensy 4.0 no-upload compilation plus build-manifest, map, memory, and target-property validation. | `python3 firmware/tools/build_firmware.py` |
| host-corpus-benchmark | **host** | PASS | Two executions of the production RAW/RLE_AUTO codec over the fixed nine-workload, 72-frame corpus. | `python -m thingdaq.rle_benchmark --pretty` |
| host-regression | **host** | PASS | Protocol drift, focused RLE/docs, Ruff, MyPy, and complete Python/portable-host-C++ regression gates. | `python -m pytest -q` |
| protocol-v1-compatibility | **host** | PASS | Byte comparison of the canonical v1 contract and all 26 generated v1 outputs against the immutable baseline branch. | `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h` |
| simulator-demo | **simulated** | PASS | Two bounded public RAW-versus-RLE_AUTO simulator runs with exact decoded-block equality across six ADC/GPIO source patterns. | `python daq_api/examples/rle_compression.py` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| flash_used_bytes | 126972 | byte | none | artifact | **host** | ["firmware-build"] |
| flash_headroom_bytes | 1904644 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_used_bytes | 489760 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_headroom_bytes | 34528 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_used_bytes | 520192 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["firmware-build"] |
| cpu_clock_hz | 600000000 | hertz | none | artifact | **host** | ["firmware-build"] |
| logical_raw_bytes | 291456 | byte | none | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| logical_raw_bytes | 97152 | byte | none | declared_codec_workload | **simulated** | ["simulator-demo"] |
| encoded_wire_bytes | 143261 | byte | none | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| encoded_wire_bytes | 37745 | byte | none | declared_codec_workload | **simulated** | ["simulator-demo"] |
| encoded_to_raw_ratio | 0.49153560057092666 | ratio | logical_raw_bytes | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| encoded_to_raw_ratio | 0.38851490447957837 | ratio | logical_raw_bytes | declared_codec_workload | **simulated** | ["simulator-demo"] |
| codec_throughput_bytes_per_second | 5277575.761053098 | byte_per_second | streaming_elapsed_seconds | declared_codec_benchmark | **host** | ["host-corpus-benchmark"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/rle-streaming","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"3aeefc435f1e1d020772670467ea60227ad7aeaa","source_id":"07df743de1619a41d55a929a693510e6497fa2d22783ac92ba84ad762e62b5dc","source_tree":"81417d52c6e57aa59c027ba8206716f48579b9f8","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["evidence-framework"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"c30531ac1aef1a7dfcb555f2606f53169aacbae5fb8e7427b1b6cae170f6f816","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"d91c62fd205565c207cffcf5a3943701e2ae95d5e7fbc715331ce21ff0c4c3fc","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"109f3d151ee6f37f98def28d531ce320b04e67d3e1b2bace18fa22aaebc345d4","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"84b1731517a92c35195e05acfb34c6b5bea62ee0719e17b734e005bd0eda3457"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"c30531ac1aef1a7dfcb555f2606f53169aacbae5fb8e7427b1b6cae170f6f816","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"d91c62fd205565c207cffcf5a3943701e2ae95d5e7fbc715331ce21ff0c4c3fc","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"109f3d151ee6f37f98def28d531ce320b04e67d3e1b2bace18fa22aaebc345d4","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"84b1731517a92c35195e05acfb34c6b5bea62ee0719e17b734e005bd0eda3457"} | — | ["firmware-build"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"network_unused":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["firmware-build"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"benchmark_normalized_run_1":"48af28678522ed58879db3aa01ad4e5b733f56b25a007d09f4e62301dfda531a","benchmark_normalized_run_2":"48af28678522ed58879db3aa01ad4e5b733f56b25a007d09f4e62301dfda531a","demo_run_1":"d958c5a9f59b57dbcf4638b4ab3413ee1f758694462a368f39f43d0c65558aee","demo_run_2":"d958c5a9f59b57dbcf4638b4ab3413ee1f758694462a368f39f43d0c65558aee","report_json":"byte-identical","report_markdown":"byte-identical"} | {"benchmark_normalized_run_1":"48af28678522ed58879db3aa01ad4e5b733f56b25a007d09f4e62301dfda531a","benchmark_normalized_run_2":"48af28678522ed58879db3aa01ad4e5b733f56b25a007d09f4e62301dfda531a","demo_run_1":"d958c5a9f59b57dbcf4638b4ab3413ee1f758694462a368f39f43d0c65558aee","demo_run_2":"d958c5a9f59b57dbcf4638b4ab3413ee1f758694462a368f39f43d0c65558aee","report_json":"byte-identical","report_markdown":"byte-identical"} | — | ["evidence-framework","host-corpus-benchmark"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **PASS** | true | {"bounded_capture":true,"cleanup":true,"configure":true,"info":true,"start":true,"status":true,"stop":true} | — | ["simulator-demo"] |
| synthetic_formulas_exact | Every validated synthetic ADC pair and GPIO sample matches the declared deterministic formula and chronology. | **PASS** | all RAW and RLE_AUTO logical blocks were byte-identical | all RAW and RLE_AUTO logical blocks were byte-identical | — | ["simulator-demo"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **PASS** | true | {"decoded_equality":true,"firmware_drops_zero":true,"host_queue_drops_zero":true,"parser_errors_zero":true,"sequence_gaps_zero":true,"transport_errors_zero":true} | — | ["simulator-demo"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **PASS** | true | {"benchmark_frame_selection":{"left":72,"right":72},"benchmark_workload_round_trip":{"left":9,"right":9},"demo_frame_selection":{"left":24,"right":24},"demo_raw_payload":{"left":97152,"right":97152}} | — | ["simulator-demo"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **PASS** | 0 | 0 | — | ["simulator-demo"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"device_idle":true,"reader_closed":true,"transport_closed":true} | — | ["simulator-demo"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"analog_performance_untested":true,"build_is_not_target_runtime":true,"compression_is_workload_dependent":true,"cross_branch_combinations_untested":true,"external_gpio_timing_untested":true,"simulation_is_not_physical":true} | — | ["evidence-framework"] |

## Claim limitations

| Limitation | Statement | Applies to evidence levels |
| --- | --- | --- |
| simulation_is_not_physical | Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality. | ["simulated"] |
| build_is_not_target_runtime | A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB. | ["host"] |
| analog_performance_untested | Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing. | ["analytic","simulated","host","rig"] |
| external_gpio_timing_untested | Without a declared external stimulus, evidence does not establish pad mapping, voltage thresholds, transition timing, jitter, or signal integrity. | ["analytic","simulated","host","rig"] |
| compression_is_workload_dependent | Compression results apply only to the declared workload and framing; they do not promise savings for noisy or incompressible inputs. | ["analytic","simulated","host","rig"] |
| cross_branch_combinations_untested | Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact. | ["analytic","simulated","host","rig","manual"] |

## Artifacts and reproduction

| Kind | Repository-relative path | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 12911 | `c30531ac1aef1a7dfcb555f2606f53169aacbae5fb8e7427b1b6cae170f6f816` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1807828 | `d91c62fd205565c207cffcf5a3943701e2ae95d5e7fbc715331ce21ff0c4c3fc` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 357227 | `109f3d151ee6f37f98def28d531ce320b04e67d3e1b2bace18fa22aaebc345d4` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 828461 | `84b1731517a92c35195e05acfb34c6b5bea62ee0719e17b734e005bd0eda3457` |

### Commands

- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/rle-prototype.json --json-output doc/results/experiments/rle-prototype.json --markdown-output doc/results/experiments/rle-prototype.md --check`
- `firmware-build` (host): `python3 firmware/tools/build_firmware.py`
- `host-corpus-benchmark` (host): `python -m thingdaq.rle_benchmark --pretty`
- `host-regression` (host): `python -m pytest -q`
- `protocol-v1-compatibility` (host): `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h`
- `simulator-demo` (simulated): `python daq_api/examples/rle_compression.py`
