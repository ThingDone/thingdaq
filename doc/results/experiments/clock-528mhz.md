---
type: report
title: "ThingDAQ 528 MHz Clock Experiment"
created: 2026-09-02
tags:
  - thingdaq
  - experiment-evidence
  - clock-528mhz
related:
  - "[[Evidence-Index]]"
  - "[[Protocol-V1]]"
  - "[[System-Overview]]"
  - "[[baseline]]"
  - "[[ADR-003-GPIO-Clock-DMA]]"
  - "[[ADR-004-ADC-Trigger-DMA]]"
  - "[[ADR-005-Experimental-Clock-Profiles]]"
  - "[[Experiment-Baseline]]"
---

# ThingDAQ 528 MHz Clock Experiment

## Outcome

**INCONCLUSIVE**

The exact production 600 MHz and experimental 528 MHz no-upload builds passed deterministic local validation with a common firmware source identity, identical allocatable target layout, identical memory use, and unchanged nominal 1 MHz ADC-pair and 4 MHz GPIO schedules. The fresh replacement-board rig, performance-compatibility, and thermal-benefit levels remain **INCONCLUSIVE** because campaign `clock-528mhz-physical-campaign-00003` stopped before firmware programming in both bounded 600 MHz prerequisite attempts.

### Exact profile evidence

The 600 MHz control uses `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`, build `thingdaq-e1364ec283663ec2`, and HEX SHA-256 `ae4602195e6b2c63bb70b826a85ca7f4aee898e750384d1ea3b3e4e7921cb0aa`; its CPU/IPG/ADC/PIT/DWT clocks are 600/150/37.5/24/600 MHz, its nominal phase is 75 IPG cycles or 300 DWT cycles, and its conservative 12-bit conversion time/margin is 866,667/133,333 ps. The 528 MHz candidate uses `teensy:avr:teensy40:usb=serial,speed=528,opt=o2std`, build `thingdaq-3842de65930ac76d`, and HEX SHA-256 `3f2987f5d2c35637a79f5a74950f44e38575a6c715b6e476aa8a37e13fb437f0`; its clocks are 528/132/33/24/528 MHz, its nominal phase is 66 IPG cycles or 264 DWT cycles, and its conversion time/margin is 984,849/15,151 ps. The profile voltage values, 1,250 mV and 1,175 mV respectively, are core targets rather than measured rails.

### Replacement-board campaign disposition

Fresh 600 MHz smoke jobs `653e1775-53b6-41ce-94a1-5f8457dca224` and `af097495-abab-450a-9f46-802fecf3addb` each powered service hub port 15, but the replacement Teensy did not enumerate within the fixed 20-second bound. Both service jobs ended before programming with exit `-100`, `program_success` unavailable, and zero runner-output bytes; the service recovered to healthy, normal, queue-depth-zero state after each attempt. No historical hardware serial was supplied as an expectation or acceptance rule. Because no target was programmed, the replacement board's required nonzero serial was unobservable rather than mismatched. The 528 MHz smoke and planned 600/528/528/600 ABBA endurance sequence were not submitted. Consequently every physical rate, loss, latency, service-load, queue, memory, temperature-trace, and temperature-statistic field is explicitly null or empty, and no rig metric is inferred.

Only campaign `00003` supplies the current physical conclusion. Campaigns `00001` and `00002` remain immutable superseded history and contribute no current measurement or grade. Performance compatibility and thermal benefit are graded separately and both remain **INCONCLUSIVE**.

### Claim boundary

The experiment does not demonstrate performance compatibility or thermal benefit. On-chip temperature would not establish ambient temperature, electrical power, junction characterization, physical ADC aperture, or part lifetime; none of those quantities was measured. The isolated profile result also does not establish compatibility with changes from any other experiment branch.

Reason: The exact 600 MHz and 528 MHz profiles passed the complete local gate, but replacement-board campaign 00003 could not program or start either bounded 600 MHz smoke attempt, so its hardware serial and every physical performance and thermal measurement remained unobservable.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/clock-528mhz |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | 919f7069607d9d2c3a38bfd40e983736e6748cdd |
| source_tree | 2a788f1ee19c96f886aed10ae2681cbd60bb5da5 |
| source_clean | true |
| source_id | e1364ec283663ec2e7629e5cc2fed9e1de004bfc8afba49d7017ed4da70023b1 |
| protocol_contract_path | protocol/protocol-v1.json |
| protocol_version | 1 |
| protocol_sha256 | 4bf3ce7074766f54bf7c7f279d926d9fcc122584ce20715d190d444ae4206abb |

### Toolchains

| Name | Version | Identity |
| --- | --- | --- |
| arduino-cli | 1.4.1 | arduino-cli Version 1.4.1 Commit e39419312 Date 2026-01-19T16:13:12Z |
| arm-none-eabi-g++ | 15.2.1 | Arm GNU Toolchain 15.2.Rel1 build arm-15.86 15.2.1 20251203 |
| python | 3.12.3 | CPython 3.12.3 |
| teensy-core | 1.62.0 | teensy:avr 1.62.0 |

## Evidence levels

| Label | Meaning | Physical claims allowed |
| --- | --- | ---: |
| **host** | Execution on the host, including native tests, benchmarks, and no-upload firmware builds; target runtime behavior is not implied. | false |
| **rig** | Autonomous execution on identified hardware with a hashed fixture declaration and bounded cleanup. | true |

### Evidence records

| ID | Evidence level | Result | Method | Command |
| --- | --- | --- | --- | --- |
| dual-profile-local-gate | **host** | PASS | Generated-contract, clock, ADC, diagnostic, style, typing, full regression, and four clean no-upload build checks for exact 600 MHz and 528 MHz profiles; the complete repeated output directories were byte-identical within each profile. | `python3 firmware/tools/build_firmware.py --cpu-profile 528 --compare-profile-manifest firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` |
| evidence-framework | **host** | PASS | Fail-closed matrix validation, file and Git identity verification, two deterministic JSON and Markdown renders, and canonical output drift checking. | `python3 firmware/tools/experiment_evidence.py --report clock-528mhz-report-input.json` |
| physical-campaign | **rig** | INCONCLUSIVE | Validated campaign 00003 only: credential-safe service preflight, two strictly sequential bounded replacement-board smoke submissions, one permitted infrastructure retry, programming and runner proof checks, and automatic service recovery checks. Later stages were not submitted after the prerequisite smoke remained inconclusive. | `python3 firmware/tests/rig_clock_comparison.py` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| packet_buffer_capacity_frames | 200 | frame | none | artifact | **host** | ["dual-profile-local-gate"] |
| flash_used_bytes | 99260 | byte | none | artifact | **host** | ["dual-profile-local-gate"] |
| flash_headroom_bytes | 1899524 | byte | none | artifact | **host** | ["dual-profile-local-gate"] |
| ram1_used_bytes | 491168 | byte | none | artifact | **host** | ["dual-profile-local-gate"] |
| ram1_headroom_bytes | 33120 | byte | none | artifact | **host** | ["dual-profile-local-gate"] |
| ram2_used_bytes | 520192 | byte | none | artifact | **host** | ["dual-profile-local-gate"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["dual-profile-local-gate"] |
| cpu_clock_hz | 528000000 | hertz | none | artifact | **host** | ["dual-profile-local-gate"] |
| ipg_clock_hz | 132000000 | hertz | none | artifact | **host** | ["dual-profile-local-gate"] |
| adc_clock_hz | 33000000 | hertz | none | artifact | **host** | ["dual-profile-local-gate"] |
| pit_clock_hz | 24000000 | hertz | none | artifact | **host** | ["dual-profile-local-gate"] |
| timestamp_clock_hz | 8000000 | hertz | none | artifact | **host** | ["dual-profile-local-gate"] |
| adc_phase_ticks | 4 | tick | none | artifact | **host** | ["dual-profile-local-gate"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"campaign_00003_hash":true,"campaign_00003_internal_consistency":true,"campaign_00003_schema":true,"content_policy":true,"current_physical_conclusions_use_only_campaign_00003":true,"hashes":true,"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/clock-528mhz","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"4bf3ce7074766f54bf7c7f279d926d9fcc122584ce20715d190d444ae4206abb","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"919f7069607d9d2c3a38bfd40e983736e6748cdd","source_id":"e1364ec283663ec2e7629e5cc2fed9e1de004bfc8afba49d7017ed4da70023b1","source_tree":"2a788f1ee19c96f886aed10ae2681cbd60bb5da5","toolchains":4} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["evidence-framework"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/build-manifest.json":"aff214c09c60212b5eb7ee29a1dba1ff4535cc2a653e5e07fce579094c1b2e6d","firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.elf":"ff5f884a9638364247796f082c5ad6dd9cadc687433a8e59d79f1eb36e63dcbf","firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.hex":"3f2987f5d2c35637a79f5a74950f44e38575a6c715b6e476aa8a37e13fb437f0","firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.map":"ed252a0ac4ce99228650d3c8373ddc9685ef0dbb8a1d3e5fd7f1dd13ddda0186","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"8ec8818c7660801254278914db7a0c4331542f9784e11c1a3c5667d5378e24af","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"52587f92b81bf2b6a47cd232ea35e825fd3ac88bea57aeaeca403fb2beba598b","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"ae4602195e6b2c63bb70b826a85ca7f4aee898e750384d1ea3b3e4e7921cb0aa","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"8eae4eeac6bc45e3540d2e443425e12c59724b766465f4ad7692364a761ab7d4"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/build-manifest.json":"aff214c09c60212b5eb7ee29a1dba1ff4535cc2a653e5e07fce579094c1b2e6d","firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.elf":"ff5f884a9638364247796f082c5ad6dd9cadc687433a8e59d79f1eb36e63dcbf","firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.hex":"3f2987f5d2c35637a79f5a74950f44e38575a6c715b6e476aa8a37e13fb437f0","firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.map":"ed252a0ac4ce99228650d3c8373ddc9685ef0dbb8a1d3e5fd7f1dd13ddda0186","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"8ec8818c7660801254278914db7a0c4331542f9784e11c1a3c5667d5378e24af","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"52587f92b81bf2b6a47cd232ea35e825fd3ac88bea57aeaeca403fb2beba598b","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"ae4602195e6b2c63bb70b826a85ca7f4aee898e750384d1ea3b3e4e7921cb0aa","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"8eae4eeac6bc45e3540d2e443425e12c59724b766465f4ad7692364a761ab7d4"} | — | ["dual-profile-local-gate"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"exact_fqbns":true,"experimental_528_compiled":true,"isolated_outputs":true,"network_unused":true,"production_600_compiled":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["dual-profile-local-gate"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"json":"byte-identical","markdown":"byte-identical"} | {"json":"byte-identical","markdown":"byte-identical"} | — | ["evidence-framework"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **INCONCLUSIVE** | true | {"abba_temperature_statistics":null,"abba_temperature_trace_millidegrees_celsius":[],"bounded_capture":null,"configure":null,"firmware_idle_cleanup":null,"firmware_programmed":false,"hardware_enumerated":false,"historical_serial_acceptance_rule":false,"info":null,"observed_hardware_serial":null,"program_success":null,"runner_output_bytes":0,"running_status":null,"start":null,"stop":null,"submitted_job_ids":["653e1775-53b6-41ce-94a1-5f8457dca224","af097495-abab-450a-9f46-802fecf3addb"]} | Neither fresh campaign-00003 job enumerated the replacement board, so the firmware lifecycle did not start. | ["physical-campaign"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **INCONCLUSIVE** | true | {"accepted_run_count":0,"acquisition_service_utilization_ratio":null,"adc_pair_rate_hz":null,"cache_errors":null,"command_latency_maximum_milliseconds":null,"command_latency_p99_milliseconds":null,"complete_frame_loss":null,"dma_errors":null,"gpio_sample_rate_hz":null,"measurement_duration_seconds":null,"parser_errors":null,"process_peak_rss_growth_bytes":null,"queue_high_water":null,"sequence_gaps":null,"transport_errors":null,"trigger_errors":null,"usb_service_utilization_ratio":null} | Campaign 00003 produced no accepted physical stream, so rate, loss, error, latency, load, queue, and memory values were rejected as missing rather than inferred. | ["physical-campaign"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **INCONCLUSIVE** | true | {"equations":null,"firmware_counters":null,"host_counters":null} | No campaign-00003 physical counters were emitted because the runner never started. | ["physical-campaign"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **INCONCLUSIVE** | {"packet_capacity_frames":200} | {"host_high_water":null,"packet_high_water_frames":null,"service_queue_depth_after_attempts":0} | Firmware and host acquisition queues were never instantiated for a campaign-00003 run. | ["physical-campaign"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **INCONCLUSIVE** | true | {"firmware_cleanup_applicable":false,"firmware_gauges":null,"firmware_idle_confirmed":null,"firmware_stop_attempted":false,"service_queue_depth":0,"service_recovered_after_each_attempt":true} | No campaign-00003 firmware session existed to STOP or query for IDLE; only service recovery was observable. | ["physical-campaign"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"ambient_temperature_uncontrolled":true,"analog_performance_ungraded":true,"build_not_target_runtime":true,"core_voltage_target_not_measurement":true,"cross_branch_combinations_ungraded":true,"electrical_power_unmeasured":true,"external_gpio_timing_ungraded":true,"live_usb_unobserved":true,"part_lifetime_not_claimed":true,"performance_compatibility_not_claimed":true,"physical_aperture_ungraded":true,"thermal_benefit_not_claimed":true} | — | ["evidence-framework"] |

## Claim limitations

| Limitation | Statement | Applies to evidence levels |
| --- | --- | --- |
| build_is_not_target_runtime | A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB. | ["host"] |
| analog_performance_untested | Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing. | ["analytic","simulated","host","rig"] |
| external_gpio_timing_untested | Without a declared external stimulus, evidence does not establish pad mapping, voltage thresholds, transition timing, jitter, or signal integrity. | ["analytic","simulated","host","rig"] |
| live_usb_untested | In-memory transport and host-only evidence do not establish sustained behavior on a live USB controller or operating system. | ["simulated","host"] |
| temperature_power_lifetime_scope | On-chip temperature is not ambient temperature, power, junction characterization, or evidence of part lifetime; those claims require separately declared evidence. | ["analytic","simulated","host","rig","manual"] |
| cross_branch_combinations_untested | Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact. | ["analytic","simulated","host","rig","manual"] |

## Artifacts and reproduction

| Kind | Repository-relative path | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| firmware-528-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.elf` | 1865220 | `ff5f884a9638364247796f082c5ad6dd9cadc687433a8e59d79f1eb36e63dcbf` |
| firmware-528-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.hex` | 371644 | `3f2987f5d2c35637a79f5a74950f44e38575a6c715b6e476aa8a37e13fb437f0` |
| firmware-528-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/build-manifest.json` | 18192 | `aff214c09c60212b5eb7ee29a1dba1ff4535cc2a653e5e07fce579094c1b2e6d` |
| firmware-528-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_528.opt_o2std/firmware.ino.map` | 846071 | `ed252a0ac4ce99228650d3c8373ddc9685ef0dbb8a1d3e5fd7f1dd13ddda0186` |
| firmware-600-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1865152 | `52587f92b81bf2b6a47cd232ea35e825fd3ac88bea57aeaeca403fb2beba598b` |
| firmware-600-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 371644 | `ae4602195e6b2c63bb70b826a85ca7f4aee898e750384d1ea3b3e4e7921cb0aa` |
| firmware-600-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 18192 | `8ec8818c7660801254278914db7a0c4331542f9784e11c1a3c5667d5378e24af` |
| firmware-600-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 846110 | `8eae4eeac6bc45e3540d2e443425e12c59724b766465f4ad7692364a761ab7d4` |

### Commands

- `dual-profile-local-gate` (host): `python3 firmware/tools/build_firmware.py --cpu-profile 528 --compare-profile-manifest firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json`
- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report clock-528mhz-report-input.json`
- `physical-campaign` (rig): `python3 firmware/tests/rig_clock_comparison.py`
