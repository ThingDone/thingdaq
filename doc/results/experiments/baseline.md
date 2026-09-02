---
type: report
title: "ThingDAQ Experiment Baseline"
created: 2026-09-01
tags:
  - thingdaq
  - experiment-evidence
  - baseline
related:
  - "[[Evidence-Index]]"
  - "[[Protocol-V1]]"
  - "[[System-Overview]]"
  - "[[soak-harness]]"
---

# ThingDAQ Experiment Baseline

## Outcome

**PASS**

The public in-memory API completed the maximum protocol-v1 profile with exact formulas, chronology, health, conservation, and cleanup; the pinned 600 MHz firmware compiled without upload and its manifest, map, artifact hashes, clocks, and memory resources were verified. This is simulated and host build evidence, not physical DAQ or USB evidence.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | main |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | becb45360afef2ae8375c4ce4a32061d47cb6570 |
| source_commit | becb45360afef2ae8375c4ce4a32061d47cb6570 |
| source_tree | 0a1a41ce828269ca01294defc05c74ccb5c3f588 |
| source_clean | true |
| source_id | e27556de5b898f281dfbae8a9a1fefb486a4fa38a885516e2fac5ce6974ba673 |
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
| evidence-framework | **host** | PASS | Fail-closed matrix validation followed by two canonical JSON and Markdown renders before atomic replacement. | `python3 firmware/tools/experiment_evidence.py --report baseline-input.json` |
| firmware-build | **host** | PASS | Pinned no-upload Teensy 4.0 compilation, manifest hash validation, linker-map inspection, and memory/resource accounting. | `python3 firmware/tools/build_firmware.py` |
| simulator-capture | **simulated** | PASS | Public ThingDAQ facade over the deterministic in-memory protocol peer, with strict per-item formulas, chronology, health, STOP/drain, and exact counter reconciliation. | `python3 firmware/tools/baseline_prototype.py --frame-budget 256 --parser-chunk-size 47 --status-every-frames 32` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| measurement_duration_seconds | 0.129536 | second | none | streaming_window | **simulated** | ["simulator-capture"] |
| adc_pairs_observed | 129536 | adc_pair | none | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_samples_observed | 518144 | gpio_sample | none | streaming_window | **simulated** | ["simulator-capture"] |
| adc_frames_observed | 128 | frame | none | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_frames_observed | 128 | frame | none | streaming_window | **simulated** | ["simulator-capture"] |
| adc_payload_bytes | 518144 | byte | none | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_payload_bytes | 518144 | byte | none | streaming_window | **simulated** | ["simulator-capture"] |
| combined_payload_bytes | 1036288 | byte | none | streaming_window | **simulated** | ["simulator-capture"] |
| adc_framed_bytes | 524288 | byte | none | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_framed_bytes | 524288 | byte | none | streaming_window | **simulated** | ["simulator-capture"] |
| combined_framed_bytes | 1048576 | byte | none | streaming_window | **simulated** | ["simulator-capture"] |
| adc_pair_rate_hz | 999999.9999999999 | adc_pair_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_sample_rate_hz | 3999999.9999999995 | gpio_sample_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| adc_payload_rate_bytes_per_second | 3999999.9999999995 | byte_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_payload_rate_bytes_per_second | 3999999.9999999995 | byte_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| combined_payload_rate_bytes_per_second | 7999999.999999999 | byte_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| adc_framed_rate_bytes_per_second | 4047430.8300395254 | byte_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_framed_rate_bytes_per_second | 4047430.8300395254 | byte_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| combined_framed_rate_bytes_per_second | 8094861.660079051 | byte_per_second | streaming_elapsed_seconds | streaming_window | **simulated** | ["simulator-capture"] |
| sequence_gap_frames | 0 | frame | none | streaming_window | **simulated** | ["simulator-capture"] |
| adc_sequence_gap_frames | 0 | frame | none | streaming_window | **simulated** | ["simulator-capture"] |
| gpio_sequence_gap_frames | 0 | frame | none | streaming_window | **simulated** | ["simulator-capture"] |
| firmware_dropped_frames | 0 | frame | none | run | **simulated** | ["simulator-capture"] |
| adc_frames_dropped | 0 | frame | none | run | **simulated** | ["simulator-capture"] |
| gpio_frames_dropped | 0 | frame | none | run | **simulated** | ["simulator-capture"] |
| firmware_dropped_items | 0 | event | none | run | **simulated** | ["simulator-capture"] |
| adc_pairs_dropped | 0 | adc_pair | none | run | **simulated** | ["simulator-capture"] |
| gpio_samples_dropped | 0 | gpio_sample | none | run | **simulated** | ["simulator-capture"] |
| host_queue_drops | 0 | event | none | run | **simulated** | ["simulator-capture"] |
| parser_errors | 0 | event | none | run | **simulated** | ["simulator-capture"] |
| transport_errors | 0 | event | none | run | **simulated** | ["simulator-capture"] |
| conservation_failures | 0 | event | none | final_status | **simulated** | ["simulator-capture"] |
| command_latency_p99_milliseconds | 1.0000000000047748 | millisecond | command_latency_samples | run | **simulated** | ["simulator-capture"] |
| command_latency_maximum_milliseconds | 1.0000000000047748 | millisecond | command_latency_samples | run | **simulated** | ["simulator-capture"] |
| packet_owned_high_water_frames | 0 | frame | none | run | **simulated** | ["simulator-capture"] |
| packet_buffer_capacity_frames | 200 | frame | none | artifact | **simulated** | ["simulator-capture"] |
| flash_used_bytes | 126972 | byte | none | artifact | **host** | ["firmware-build"] |
| flash_headroom_bytes | 1904644 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_used_bytes | 489760 | byte | none | artifact | **host** | ["firmware-build"] |
| ram1_headroom_bytes | 34528 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_used_bytes | 520192 | byte | none | artifact | **host** | ["firmware-build"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["firmware-build"] |
| cpu_clock_hz | 600000000 | hertz | none | artifact | **host** | ["firmware-build"] |
| ipg_clock_hz | 150000000 | hertz | none | artifact | **host** | ["firmware-build"] |
| adc_clock_hz | 37500000 | hertz | none | artifact | **host** | ["firmware-build"] |
| pit_clock_hz | 24000000 | hertz | none | artifact | **host** | ["firmware-build"] |
| timestamp_clock_hz | 8000000 | hertz | none | artifact | **simulated** | ["simulator-capture"] |
| adc_phase_ticks | 4 | tick | none | artifact | **simulated** | ["simulator-capture"] |
| gpio_width_bits | 8 | bit | none | artifact_profile | **simulated** | ["simulator-capture"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","branch":"main","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","source_id":"e27556de5b898f281dfbae8a9a1fefb486a4fa38a885516e2fac5ce6974ba673","source_tree":"0a1a41ce828269ca01294defc05c74ccb5c3f588","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["evidence-framework"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"7ecbe73a973ab12d45199300301aba784e905305d963fa11ba4ceba41fd5d56e","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"b3ae54862e9f6360b3623614bdf69c6aaf9fdf2476dda65829b49514d3fbaa4c","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"8566e88fd27f3fef07ae0ada3bca928a545851f6e0eb3d509dbec71df2f3ff44"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"7ecbe73a973ab12d45199300301aba784e905305d963fa11ba4ceba41fd5d56e","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"b3ae54862e9f6360b3623614bdf69c6aaf9fdf2476dda65829b49514d3fbaa4c","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"8566e88fd27f3fef07ae0ada3bca928a545851f6e0eb3d509dbec71df2f3ff44"} | — | ["firmware-build"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"network_unused":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["firmware-build"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"json":"byte-identical","markdown":"byte-identical"} | {"json":"byte-identical","markdown":"byte-identical"} | — | ["evidence-framework"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **PASS** | true | {"bounded_capture":true,"configure":true,"final_status":true,"info":true,"running_status":true,"start":true,"stop":true} | — | ["simulator-capture"] |
| synthetic_formulas_exact | Every validated synthetic ADC pair and GPIO sample matches the declared deterministic formula and chronology. | **PASS** | every logical item and timestamp matched | every logical item and timestamp matched | — | ["simulator-capture"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **PASS** | true | {"firmware_drops_zero":true,"gaps_zero":true,"host_queue_drops_zero":true,"parser_errors_zero":true,"transport_errors_zero":true} | — | ["simulator-capture"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **PASS** | true | {"adc_firmware_to_wire_frames":{"left":128,"right":128},"adc_framed_bytes":{"left":524288,"right":524288},"adc_items":{"left":129536,"right":129536},"adc_payload_bytes":{"left":518144,"right":518144},"adc_wire_to_consumer_frames":{"left":128,"right":128},"combined_framed_bytes":{"left":1048576,"right":1048576},"combined_payload_bytes":{"left":1036288,"right":1036288},"gpio_firmware_to_wire_frames":{"left":128,"right":128},"gpio_framed_bytes":{"left":524288,"right":524288},"gpio_items":{"left":518144,"right":518144},"gpio_payload_bytes":{"left":518144,"right":518144},"gpio_wire_to_consumer_frames":{"left":128,"right":128}} | — | ["simulator-capture"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **PASS** | 1.0 | 0.9992681141741888 | — | ["simulator-capture"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"all_gauges_zero":true,"state_idle":true,"stream_mask_empty":true,"transport_closed":true} | — | ["simulator-capture"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"analog_performance_untested":true,"build_is_not_target_runtime":true,"cross_branch_combinations_untested":true,"external_gpio_timing_untested":true,"live_usb_untested":true,"simulation_is_not_physical":true,"temperature_power_lifetime_scope":true} | — | ["evidence-framework"] |

## Claim limitations

| Limitation | Statement | Applies to evidence levels |
| --- | --- | --- |
| simulation_is_not_physical | Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality. | ["simulated"] |
| build_is_not_target_runtime | A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB. | ["host"] |
| analog_performance_untested | Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing. | ["analytic","simulated","host","rig"] |
| external_gpio_timing_untested | Without a declared external stimulus, evidence does not establish pad mapping, voltage thresholds, transition timing, jitter, or signal integrity. | ["analytic","simulated","host","rig"] |
| live_usb_untested | In-memory transport and host-only evidence do not establish sustained behavior on a live USB controller or operating system. | ["simulated","host"] |
| temperature_power_lifetime_scope | On-chip temperature is not ambient temperature, power, junction characterization, or evidence of part lifetime; those claims require separately declared evidence. | ["analytic","simulated","host","rig","manual"] |
| cross_branch_combinations_untested | Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact. | ["analytic","simulated","host","rig","manual"] |

## Artifacts and reproduction

| Kind | Repository-relative path | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 12733 | `7ecbe73a973ab12d45199300301aba784e905305d963fa11ba4ceba41fd5d56e` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1805372 | `b3ae54862e9f6360b3623614bdf69c6aaf9fdf2476dda65829b49514d3fbaa4c` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 357227 | `da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 828461 | `8566e88fd27f3fef07ae0ada3bca928a545851f6e0eb3d509dbec71df2f3ff44` |

### Commands

- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report baseline-input.json`
- `firmware-build` (host): `python3 firmware/tools/build_firmware.py`
- `simulator-capture` (simulated): `python3 firmware/tools/baseline_prototype.py --frame-budget 256 --parser-chunk-size 47 --status-every-frames 32`
