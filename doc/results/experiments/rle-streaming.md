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
  - "[[Acquisition-Pipeline]]"
  - "[[RLE-Firmware-Integration]]"
  - "[[RLE-Prototype]]"
---

# ThingDAQ Negotiated RLE Experiment

## Outcome

**INCONCLUSIVE**

The final negotiated-RLE candidate passes the complete local firmware, codec,
fake-device, compatibility, resource, and deterministic-build gates. The live
rig and physical-bandwidth conclusions remain **INCONCLUSIVE**: the Teensy did
not enumerate in the prerequisite protocol-v1/RAW smoke or its one permitted
infrastructure retry, so firmware was never programmed and no physical stream
or target encode measurement began.

### Exact candidate identity

| Identity | Exact value |
| --- | --- |
| Frozen baseline | `b23004defeca465da0ae2d2884c4fef71979e5d4` |
| Verified branch checkpoint | `7c639104f78866eb7e6191b58b2bc5349342e480` on `experiment/rle-streaming` |
| Source tree / firmware source | `04d07aab4a1440551c69a5cc1d135d59b0376a51` / `85f2698ba97fb1defe827c4c12b5cd1e746a7ccc518b7868d4135a5b50605d8b` |
| Protocol v1 | SHA-256 `014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222` |
| Protocol v2 | SHA-256 `2b9990ee46b3f9eff999d285c7e3fefb13947e79fda5d977b336ad75dab19aa3` |
| Artifact provenance commit | `f831c89fe15abec05b89df2e6aa60f07a1dcf2b6` |
| Build / target | `thingdaq-85f2698ba97fb1de` / `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Candidate HEX | 386,057 bytes; SHA-256 `856006e31046e0166287ca281e407f54d71f25eae4f7fd32b04484c3532da6da` |
| Campaign index | SHA-256 `760c99e79fe50a4634a17e7c6bb205af36f0ec4c9844ac91b1acec909873d515` |
| Remote attempts | `d9c0e047-1152-4c63-b5dd-506a905bc7db`, `816e750c-002a-4212-b7f9-c1e390fecb27` |

### Codec definition

Protocol v2 retains the 44-byte header and four-byte checksum trailer. RAW
carries the unchanged 4,048-byte payload. Each canonical little-endian RLE
record is `u16 run_length` plus one complete item: six bytes for one four-byte
ADC pair or three bytes for one packed GPIO byte. Runs are positive, coalesced,
frame-local, and must decode to exactly 1,012 ADC pairs or 4,048 GPIO samples.
Every frame independently preserves sequence, first timestamp, flags, and
8,096-tick coverage. Firmware sizes first and selects RLE only when the complete
wire frame is strictly smaller; ties, expansion, page pressure, or a counted
encoder failure select intact RAW. The selected header and payload are checksummed
before publication, and hosts validate bounded length and checksum before bounded
canonical decompression. The largest selectable RLE representation is 674 ADC
records / 4,092 wire bytes or 1,349 GPIO records / 4,095 wire bytes.

### Complete local gate

| Gate | Exact observation |
| --- | --- |
| Protocol generation | 70 v1/v2 outputs current |
| Focused codec/protocol/rig | 72 passed, 1 skipped, 415 C++ subtests |
| Parser/performance | 29 passed, 11,511 subtests; 4,099-byte parser high water; 2.0396x minimum full-rate headroom |
| Documentation/layout | 8 passed, 643 subtests |
| Complete regression | 500 passed, 8 skipped, 14,589 subtests |
| Ruff / MyPy | 140 files format/lint clean; 29 source files type clean |
| Repeated target build | Two byte-identical builds; `thingdaq-85f2698ba97fb1de` |
| Memory / retention | flash 137,212 B; RAM1 491,488 B with 32,800 B local/stack headroom; RAM2 520,192 B with 4,096 B free; 105 DTCM + 95 OCRAM packet pages |
| Default v1/RAW workflow | 2 ADC + 2 GPIO frames, zero gaps/drops/errors, final IDLE: `true` |

### Corpus compression and conservation

Every workload contains eight complete frames. Ratios below use selected complete
wire bytes divided by RAW complete-wire bytes; logical-to-wire ratios are also
retained in JSON. Envelope conservation is exact: RAW wire equals logical payload
plus 48 bytes per frame, and selected wire equals selected payload plus the same
48-byte envelope per frame.

| Stream | Workloads / frames | Logical / selected payload bytes | RAW / selected wire bytes | Exact selected/RAW wire ratio | Runs | RLE / fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ADC | 4 / 32 | 129,536 / 74,752 | 131,072 / 76,288 | 76288/131072 = 0.582031250 | 17,713 | 16 / 16 |
| GPIO | 5 / 40 | 161,920 / 65,053 | 163,840 / 66,973 | 66973/163840 = 0.408770752 | 64,725 | 24 / 16 |
| COMBINED | 9 / 72 | 291,456 / 139,805 | 294,912 / 143,261 | 143261/294912 = 0.485775418 | 82,438 | 40 / 32 |

| Workload | Stream | RAW / selected wire bytes | Exact ratio | Runs | RLE / fallback |
| --- | --- | ---: | ---: | ---: | ---: |
| `gpio-constant` | GPIO | 32,768 / 408 | 408/32768 = 0.012451172 | 8 | 8 / 0 |
| `gpio-long-digital-holds` | GPIO | 32,768 / 597 | 597/32768 = 0.018218994 | 71 | 8 / 0 |
| `gpio-sparse-single-bit-changes` | GPIO | 32,768 / 432 | 432/32768 = 0.013183594 | 16 | 8 / 0 |
| `gpio-alternating-bytes` | GPIO | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 32,384 | 0 / 8 |
| `gpio-pseudo-random-bytes` | GPIO | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 32,246 | 0 / 8 |
| `adc-constant-pairs` | ADC | 32,768 / 432 | 432/32768 = 0.013183594 | 8 | 8 / 0 |
| `adc-independent-slow-channels` | ADC | 32,768 / 10,320 | 10320/32768 = 0.314941406 | 1,656 | 8 / 0 |
| `adc-quantization-noise` | ADC | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 7,953 | 0 / 8 |
| `adc-high-entropy` | ADC | 32,768 / 32,768 | 32768/32768 = 1.000000000 | 8,096 | 0 / 8 |

### Encode/decode throughput and load

The host rows are the slowest measured batch in this report-generation run
over the current protocol-v2 codec. They are host diagnostics, not firmware
cycle measurements. Headroom uses the exact 4,000,000 logical B/s per-stream
denominator. The complete local gate independently retained 1.5246x minimum
decoder and 2.0396x parser headroom.

| Host path | Limiting workload | Minimum logical B/s | Per-stream headroom |
| --- | --- | ---: | ---: |
| `raw_encode` | `adc-constant-pairs` | 39624005.638328 | 9.906001410x |
| `rle_auto_encode` | `gpio-alternating-bytes` | 3791717.794384 | 0.947929449x |
| `raw_decode` | `gpio-alternating-bytes` | 6190418.048660 | 1.547604512x |
| `rle_auto_decode` | `gpio-alternating-bytes` | 6001442.924019 | 1.500360731x |
| Host codec peak memory | all four paths | 33,711 bytes | 65,536-byte ceiling |
| Firmware encode cycles/load | not observed | — | target never ran |

### Physical campaign and workload value

| Physical stream | Logical bytes | Encoded payload / complete wire | RLE / fallback / runs | Complete-wire ratio | Processing utilization |
| --- | ---: | ---: | ---: | ---: | ---: |
| ADC | not observed | not observed | not observed | **INCONCLUSIVE** | not observed |
| GPIO | not observed | not observed | not observed | **INCONCLUSIVE** | not observed |
| Combined | not observed | not observed | not observed | **INCONCLUSIVE** | not observed |

The physical value rule required matched RLE_AUTO complete-wire bytes at least
20% below RAW without more than a 10 percentage-point processing-utilization
increase. Neither operand was observed, so no ADC, GPIO, combined-bandwidth,
or encode-load value conclusion is made.

### Fallbacks, errors, queues, and incident

The corpus selected 40 RLE and 32 size-driven RAW fallback frames; every
alternating, pseudo-random, quantization-noise, and high-entropy frame fell
back without expansion. Host/target-fake tests separately covered page-pressure
and injected-encoder-failure fallback, one-page temporary ownership, exact
saturating counters, mixed streams, partial USB writes, reconnect, STOP, and
cleanup. The packet pool remained exactly 200 pages; the live service queue
returned to zero after both attempts. No live firmware error, queue, fallback,
latency, loss, or conservation value exists because the runner never started.

Both jobs failed with `infrastructure_board_unavailable`: Board teensy:avr:teensy40 did not appear on any serial port within 20s of powering hub port 15.
The service recovered after each attempt. Every v2 smoke, all five target
synthetic patterns, the matched RAW/RLE_AUTO physical comparison, and the
600-second endurance run were intentionally not submitted after the prerequisite
failed.

### Compatibility and limitations

All 27 protocol-v1 source/generated/fixture paths are byte-identical to the frozen baseline; the v1 fixture tree is `58f3800a8450714f58ec486249521aacb68eb2e4`. RLE remains explicit protocol-v2-only negotiation, and STOP/reconnect restore v1/RAW defaults.
Corpus savings are workload-specific. No target runtime, live USB acquisition,
physical ADC/GPIO quality, external timing, or cross-experiment branch combination
was established. See [[RLE-Prototype]], [[ADR-006-Experimental-RLE-Streaming]],
[[Protocol-V1]], and [[Acquisition-Pipeline]] for the host prototype, negotiated
contract, compatibility boundary, and acquisition ownership model.

Reason: The Teensy 4.0 did not enumerate within the remote service's fixed 20-second power-on window for the prerequisite protocol-v1/RAW physical-combined smoke or its one identical infrastructure retry. Neither attempt programmed firmware or started the rig, so every downstream v2, synthetic-pattern, matched physical, and endurance job was intentionally not submitted.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/rle-streaming |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | 7c639104f78866eb7e6191b58b2bc5349342e480 |
| source_tree | 04d07aab4a1440551c69a5cc1d135d59b0376a51 |
| source_clean | true |
| source_id | 85f2698ba97fb1defe827c4c12b5cd1e746a7ccc518b7868d4135a5b50605d8b |
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
| **rig** | Autonomous execution on identified hardware with a hashed fixture declaration and bounded cleanup. | true |

### Evidence records

| ID | Evidence level | Result | Method | Command |
| --- | --- | --- | --- | --- |
| evidence-framework | **host** | PASS | Fail-closed matrix validation, file/hash and Git identity verification, normalization, and two canonical shared-reporter renders. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/rle-streaming.json --json-output doc/results/experiments/rle-streaming.json --markdown-output doc/results/experiments/rle-streaming.md --check` |
| host-corpus-benchmark | **host** | PASS | Production protocol-v2 RAW/RLE_AUTO codec over the fixed nine-workload, 72-frame corpus with exact round-trip, no-expansion, throughput, and bounded-memory grading. | `python3 -m thingdaq.rle_benchmark --pretty` |
| local-firmware-gate | **host** | PASS | Complete protocol, portable C++ codec, packet/USB/runtime, rig, parser/performance, style, typing, documentation, regression, deterministic-build, and default-v1 simulator gate. | `python3 -m pytest -q` |
| physical-campaign | **rig** | INCONCLUSIVE | Credential-safe service preflight and strictly sequential bounded prerequisite submissions with one identical infrastructure retry; downstream stages were not submitted after the board remained unavailable. | `python3 firmware/tests/rig_rle_streaming.py` |
| protocol-v1-compatibility | **host** | PASS | Byte comparison of the protocol-v1 contract and all generated v1 outputs and fixtures against the immutable baseline, plus a clean default v1/RAW simulator lifecycle. | `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h` |
| simulated-rig-gate | **simulated** | PASS | Stateful partial-I/O fake-device execution of all target patterns and fail-closed codec, counter, disconnect, and cleanup faults through the standalone rig. | `python3 -m pytest -q firmware/tests/test_rig_rle_streaming.py` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| packet_buffer_capacity_frames | 200 | frame | none | artifact | **host** | ["local-firmware-gate"] |
| flash_used_bytes | 137212 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| flash_headroom_bytes | 1894404 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram1_used_bytes | 491488 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram1_headroom_bytes | 32800 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram2_used_bytes | 520192 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| cpu_clock_hz | 600000000 | hertz | none | artifact | **host** | ["local-firmware-gate"] |
| logical_raw_bytes | 291456 | byte | none | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| encoded_wire_bytes | 143261 | byte | none | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| encoded_to_raw_ratio | 0.49153560057092666 | ratio | logical_raw_bytes | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| codec_throughput_bytes_per_second | 6001442.92401875 | byte_per_second | streaming_elapsed_seconds | declared_codec_benchmark | **host** | ["host-corpus-benchmark"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"content_policy":true,"hashes":true,"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/rle-streaming","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"7c639104f78866eb7e6191b58b2bc5349342e480","source_id":"85f2698ba97fb1defe827c4c12b5cd1e746a7ccc518b7868d4135a5b50605d8b","source_tree":"04d07aab4a1440551c69a5cc1d135d59b0376a51","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["evidence-framework"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"c480d2c1c19446abda61c5fb056135d6269d53eaad7f9a11e2b0d7445c39f7ae","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"f29723328d722b4721ca4aea384b657986574e98e2e108098c3ac99e720faf60","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"856006e31046e0166287ca281e407f54d71f25eae4f7fd32b04484c3532da6da","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"59fe7bb71a9ddb2defc77e5befdde101a5c6de45b9b9f724bd595e2a50cf1a2b"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"c480d2c1c19446abda61c5fb056135d6269d53eaad7f9a11e2b0d7445c39f7ae","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"f29723328d722b4721ca4aea384b657986574e98e2e108098c3ac99e720faf60","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"856006e31046e0166287ca281e407f54d71f25eae4f7fd32b04484c3532da6da","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"59fe7bb71a9ddb2defc77e5befdde101a5c6de45b9b9f724bd595e2a50cf1a2b"} | — | ["local-firmware-gate"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"network_unused":true,"repeated_outputs_identical":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["local-firmware-gate"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"firmware_build_1":"byte-identical","firmware_build_2":"byte-identical","report_json":"byte-identical","report_markdown":"byte-identical"} | {"firmware_build_1":"byte-identical","firmware_build_2":"byte-identical","report_json":"byte-identical","report_markdown":"byte-identical"} | — | ["evidence-framework","local-firmware-gate"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **INCONCLUSIVE** | true | {"default_v1_raw_simulator":true,"physical_capture":null,"physical_configure":null,"physical_idle":null,"physical_info":null,"physical_start":null,"physical_status":null,"physical_stop":null,"simulated_fake_device":true} | The board never enumerated, so INFO, CONFIGURE, START, capture, STATUS, STOP, and firmware IDLE cleanup were not exercised on target. | ["physical-campaign","simulated-rig-gate"] |
| synthetic_formulas_exact | Every validated synthetic ADC pair and GPIO sample matches the declared deterministic formula and chronology. | **INCONCLUSIVE** | all five target patterns match exact formulas and chronology | {"physical_target":null,"target_fake_and_source_tests":true} | All five formulas passed fake-device and target-source tests, but none ran on the physical target. | ["physical-campaign","simulated-rig-gate"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **INCONCLUSIVE** | true | {"physical_codec_errors":null,"physical_complete_frame_loss":null,"physical_dma_cache_errors":null,"physical_parser_errors":null,"physical_sequence_gaps":null,"physical_transport_errors":null,"simulated_fake_device":true} | No live stream began, so rates, loss, parser, transport, DMA, cache, codec, latency, and utilization counters were not observed. | ["physical-campaign","simulated-rig-gate"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **INCONCLUSIVE** | true | {"host_adc":{"frame_selection":{"left":32,"right":32},"logical_raw":{"left":129536,"right":129536},"raw_wire":{"left":131072,"right":131072},"selected_wire":{"left":76288,"right":76288}},"host_combined":{"frame_selection":{"left":72,"right":72},"logical_raw":{"left":291456,"right":291456},"raw_wire":{"left":294912,"right":294912},"selected_wire":{"left":143261,"right":143261}},"host_gpio":{"frame_selection":{"left":40,"right":40},"logical_raw":{"left":161920,"right":161920},"raw_wire":{"left":163840,"right":163840},"selected_wire":{"left":66973,"right":66973}},"physical":null,"simulated_fake_device":true} | Host corpus and fake-device equations were exact, but no physical logical, encoded-payload, wire, queue, or loss counters were emitted. | ["physical-campaign","simulated-rig-gate"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **INCONCLUSIVE** | {"packet_capacity_frames":200} | {"local_packet_capacity_frames":200,"local_temporary_page_maximum":1,"physical_host_high_water":null,"physical_packet_high_water":null,"service_queue_depth_after_attempts":0} | The 200-page local bound and service queue recovery passed, but target and host acquisition queue high-water values were never instantiated. | ["physical-campaign","simulated-rig-gate"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **INCONCLUSIVE** | true | {"default_v1_raw_simulator_idle":true,"physical_firmware_idle_confirmed":null,"physical_stop_attempted":false,"service_queue_depth":0,"service_recovered_after_each_attempt":true,"simulated_positive_cases_idle":true} | No firmware session existed to STOP or query for IDLE; only service recovery to queue depth zero was observable. | ["physical-campaign","simulated-rig-gate"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"analog_performance_untested":true,"build_is_not_target_runtime":true,"compression_is_workload_dependent":true,"cross_branch_combinations_untested":true,"external_gpio_timing_untested":true,"firmware_encode_load_not_claimed":true,"physical_adc_ratio_not_claimed":true,"physical_bandwidth_benefit_inconclusive":true,"physical_gpio_ratio_not_claimed":true,"rig_correctness_inconclusive":true,"simulation_is_not_physical":true} | — | ["evidence-framework"] |

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
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 13026 | `c480d2c1c19446abda61c5fb056135d6269d53eaad7f9a11e2b0d7445c39f7ae` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1922896 | `f29723328d722b4721ca4aea384b657986574e98e2e108098c3ac99e720faf60` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 386057 | `856006e31046e0166287ca281e407f54d71f25eae4f7fd32b04484c3532da6da` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 840531 | `59fe7bb71a9ddb2defc77e5befdde101a5c6de45b9b9f724bd595e2a50cf1a2b` |

### Commands

- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/rle-streaming.json --json-output doc/results/experiments/rle-streaming.json --markdown-output doc/results/experiments/rle-streaming.md --check`
- `host-corpus-benchmark` (host): `python3 -m thingdaq.rle_benchmark --pretty`
- `local-firmware-gate` (host): `python3 -m pytest -q`
- `physical-campaign` (rig): `python3 firmware/tests/rig_rle_streaming.py`
- `protocol-v1-compatibility` (host): `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h`
- `simulated-rig-gate` (simulated): `python3 -m pytest -q firmware/tests/test_rig_rle_streaming.py`
