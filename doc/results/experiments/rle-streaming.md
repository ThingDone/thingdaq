---
type: report
title: "ThingDAQ Negotiated RLE Experiment"
created: 2026-09-04
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

The replacement-board `00003` campaign supersedes the obsolete no-programming
physical rollup. Its immutable `final4` candidate passed ten strictly sequential
short stages, including both negotiated smokes, all five synthetic patterns, and
the matched 60-second physical RAW/RLE comparison. Rig correctness and the report
remain **INCONCLUSIVE** because neither bounded 600-second endurance attempt
completed without upstream serial byte loss. The separately measurable physical
bandwidth-value conclusion is **FAIL**: combined wire volume fell 49.377441%, but
encoder utilization increased 10.205324 percentage points, 0.205324 points above
the fixed 10-point maximum.

### Exact replacement-board evidence identity

| Identity | Exact value |
| --- | --- |
| Frozen baseline | `b23004defeca465da0ae2d2884c4fef71979e5d4` |
| Candidate branch/checkpoint | `experiment/rle-streaming` at `dca4343616a78ab71dedf08155359aeddd017859` |
| Firmware source / build | `db824f42af030d7ed226900d3b68379962f7515f66734e51e4309773b04f5c4d` / `thingdaq-db824f42af030d7e` |
| Build target / service target | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` / `teensy:avr:teensy40` |
| Manifest | 13,025 bytes; SHA-256 `903285a0642d689670dfb771d5cec7153d5558c951181657a7497d8b140e088d` |
| Candidate HEX | 388,911 bytes; SHA-256 `b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248` |
| Protocol v1 / v2 | `014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222` / `2b9990ee46b3f9eff999d285c7e3fefb13947e79fda5d977b336ad75dab19aa3` |
| Replacement hardware serial | `20428100` (observed, nonzero, stable, and non-grading) |
| Campaign index | `rle-streaming-physical-campaign-00003`; SHA-256 `681c74f20f35012af01b438561de7c4d25ec0b91a3fb247d0e0255e35b960f21` |
| Independent campaign validation | 9,091 checks; 107 unique sequential jobs |

Only campaign `00003` supplies current physical conclusions. Campaigns `00001`
and `00002` remain immutable superseded provenance with manifest SHA-256 values
`677059aef906c136a0b5fb1f0def317b5fc246339173c018a2850f85b98babb0` and
`9030098494c1e48a68e182f2b416203fd35a793b384c303cf9ee0106d66b9898`; none of their
measurements or earlier board expectations enter the current grades.

### Accepted final4 sequence

| # | Stage | Service job | Result |
| ---: | --- | --- | --- |
| 1 | `final4-v1-raw-physical-combined-smoke` | `74a69541-ed2c-4ffb-9f01-c64c941b9dd3` | PASS |
| 2 | `final4-resample-v2-raw-smoke` | `b780d490-fa3a-4248-998c-0b06fa61d91c` | PASS |
| 3 | `final4-resample-v2-rle-auto-smoke` | `9ddbeb1d-41e6-4522-ad5b-9989632855fd` | PASS |
| 4 | `final4-resample-synthetic-constant-rle-auto` | `9832bb0a-fe99-4802-92c6-9501f737112a` | PASS |
| 5 | `final4-resample-synthetic-sparse-hold-rle-auto` | `25dcc047-cc6b-438a-81c2-15ccd6838ad0` | PASS |
| 6 | `final4-resample-synthetic-slow-adc-rle-auto` | `a80b863d-8b11-4b2f-9a85-8d53c3345f61` | PASS |
| 7 | `final4-resample-synthetic-alternating-rle-auto` | `d165c5d0-d6bc-4588-8f39-702896c5dae9` | PASS |
| 8 | `final4-resample-synthetic-incompressible-rle-auto` | `b9cf56b7-9351-4566-9572-61075e0a0fee` | PASS |
| 9 | `final4-resample-physical-combined-v2-raw-matched` | `1242edca-de9e-49d8-9093-15232c79686e` | PASS |
| 10 | `final4-resample-physical-combined-v2-rle-auto-matched` | `9686bce1-f4aa-4974-9a34-2e6c01c62f85` | PASS |

Every accepted job programmed the exact candidate, emitted nonempty runner
output, advertised build `thingdaq-db824f42af030d7e` and serial `20428100`, ran
without active loss/error counters, attempted STOP, and confirmed final IDLE.

### Matched physical RAW versus RLE_AUTO

The RAW and RLE_AUTO steady windows were
60.004249938 and 60.004813458
seconds. Complete-wire ratios use the RLE_AUTO selected wire bytes divided by
the same run's RAW-equivalent complete wire bytes.

| Stream | Logical bytes | RLE payload bytes | RAW-equivalent / selected wire bytes | Ratio / reduction | RAW / RLE frames; runs | Encode cycles / utilization delta | Grade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ADC | 260,015,184 | 260,015,184 | 263,098,368 / 263,098,368 | 1.000000000 / 0.000000% | 64,233 / 0; 0 | 1,797,982,213 / 4.609870 pp | **FAIL** |
| GPIO | 260,015,184 | 192,699 | 263,098,368 / 3,275,883 | 0.012451172 / 98.754883% | 0 / 64,233; 64,233 | 2,182,388,768 / 5.595455 pp | **PASS** |
| COMBINED | 520,030,368 | 260,207,883 | 526,196,736 / 266,374,251 | 0.506225586 / 49.377441% | 64,233 / 64,233; 64,233 | 3,980,370,981 / 10.205324 pp | **FAIL** |

ADC remained entirely RAW and therefore failed the 20% bandwidth rule. GPIO
selected one canonical RLE run per frame and passed both value limits. Combined
bandwidth passed, but the processing-cost limit failed without rounding.

### Throughput, fallback, queues, latency, and memory

| Path | RAW operand | RLE_AUTO operand |
| --- | ---: | ---: |
| ADC host decode B/s | 212643149.070423 | 215047155.102205 |
| ADC wall logical B/s | 3999972.265935 | 3999937.600673 |
| GPIO host decode B/s | 625681129.039770 | 285224981.058438 |
| GPIO wall logical B/s | 3999972.265935 | 3999937.600673 |
| COMBINED host decode B/s | 317411314.611757 | 245213819.867839 |
| COMBINED wall logical B/s | 7999944.531869 | 7999875.201346 |
| Combined firmware encode cycles | 0 | 3,980,370,981 |
| Combined firmware encode load | 0.000000000 | 0.102053242 |
| Packet-owned high water | 46 / 200 pages | 26 / 200 pages |
| Temporary-page high water | 0 | 1 |
| STATUS latency p99 / max | 2.267283 / 2.601606 ms | 4.250181 / 4.252566 ms |
| Host RSS maximum | 22,003,712 bytes | 22,016,000 bytes |

RLE_AUTO produced 64,233 ADC RAW fallbacks, all `not_smaller`, and zero GPIO fallbacks. Encoder-failure and temporary-page-unavailable fallbacks were zero for both streams. Across all nine accepted v2 jobs, packet ownership peaked at 119/200 pages, temporary ownership at 1/1 page, host RSS at 22,016,000 bytes, maximum STATUS latency at 24.876835 ms, and the slowest combined host decode path sustained 20387963.942916 logical B/s.

Every accepted RAW and RLE stream exactly conserved logical payload, selected
payload, 48-byte-per-frame envelope, representation partition, queued/transmitted
bytes, and combined ADC+GPIO totals. The matched jobs reported zero checksum,
header, payload, stale-response, transport, capacity, eviction, encoding, DMA,
and queue-rejection errors. Their only incomplete items were explicitly
reconciled STOP tails: RAW 496 ADC pairs / 1987 GPIO samples and RLE_AUTO 1010 / 4042.

### Deterministic synthetic patterns

| Pattern | Service job | ADC / GPIO / combined wire ratio | RAW / RLE frames; runs | Encode load | Combined decode B/s |
| --- | --- | ---: | ---: | ---: | ---: |
| `constant` | `9832bb0a-fe99-4802-92c6-9501f737112a` | 0.013183594 / 0.012451172 / 0.012817383 | 0 / 21,800; 21,800 | 0.072158331 | 381187051.598560 |
| `sparse-hold` | `25dcc047-cc6b-438a-81c2-15ccd6838ad0` | 0.014668945 / 0.013189154 / 0.013929049 | 0 / 20,286; 40,791 | 0.272728629 | 182244417.004642 |
| `slow-adc` | `a80b863d-8b11-4b2f-9a85-8d53c3345f61` | 0.314941406 / 0.197021484 / 0.255981445 | 0 / 21,758; 5,004,340 | 0.377336967 | 20387963.942916 |
| `alternating` | `d165c5d0-d6bc-4588-8f39-702896c5dae9` | 1.000000000 / 1.000000000 / 1.000000000 | 21,744 / 0; 0 | 0.083929605 | 1504230392.659250 |
| `incompressible` | `b9cf56b7-9351-4566-9572-61075e0a0fee` | 1.000000000 / 1.000000000 / 1.000000000 | 21,746 / 0; 0 | 0.084122244 | 34786802.466302 |

Constant, sparse-hold, and slow-ADC met their declared compression bounds;
alternating and incompressible selected only RAW frames and never expanded.
Formula, timestamp, sequence, checksum-before-decode, conservation, cleanup,
and stable-identity checks passed for every accepted pattern.

### Endurance incident and separate conclusions

| Attempt | Service job | Failure | Reader high water / capacity | STATUS samples | Cleanup |
| --- | --- | --- | ---: | ---: | --- |
| 1 | `936b1df9-1629-4f4f-87c7-1be44e8a5005` | ADC checksum mismatch | 32,768 / 524,288 bytes | 68 | STOP `true`, IDLE `true` |
| 2 | `d1020be8-a74c-4997-8049-840f0c66cd6b` | 1,855 ADC-like bytes without a frame prefix | 32,768 / 524,288 bytes | 98 | STOP `true`, IDLE `true` |

Both queues ended at zero bytes/chunks, ruling out userspace queue saturation
without locating the loss among the remote USB/TTY path, hub/cable, kernel
buffering, container scheduling, or target-to-host transport. No passing
600-second observation exists. The user authorized deferring another identical
hardware attempt; this closes the machine task disposition but does not convert
the campaign, endurance qualification, or merge recommendation into PASS.

| Conclusion | Grade |
| --- | --- |
| Local correctness | **PASS** |
| Protocol-v1 compatibility | **PASS** |
| Accepted short-stage correctness | **PASS** |
| 600-second endurance / overall rig correctness | **INCONCLUSIVE** |
| ADC physical bandwidth value | **FAIL** |
| GPIO physical bandwidth value | **PASS** |
| Combined physical bandwidth value | **FAIL** |
| Overall report | **INCONCLUSIVE** |

### Compatibility and limitations

Protocol-v1 source, generated output, fixtures, and default RAW behavior remain
byte-compatible with the frozen baseline. Compression conclusions apply only to
the declared workloads and framing. The campaign does not establish ADC accuracy,
noise, ENOB, linearity, external GPIO timing, signal integrity, or compatibility
with the separate clock or auxiliary-bank branches. See [[RLE-Prototype]],
[[ADR-006-Experimental-RLE-Streaming]], [[Protocol-V1]], and
[[Acquisition-Pipeline]].

Reason: The immutable final4 candidate passed the first ten strictly sequential stages through the matched physical RAW/RLE comparison. Both bounded 600-second endurance attempts then lost bytes upstream of a continuously drained 512 KiB userspace queue: the first detected one ADC checksum mismatch after 68 STATUS samples and the retry received 1,855 ADC-like payload bytes without the frame prefix after 98 samples. Both queues peaked at only 32 KiB, ended empty, and reached clean final IDLE. No passing 600-second observation exists, so rig correctness and the task remain inconclusive. The separately measurable physical value conclusion is FAIL because encoder utilization increased by 10.205324 percentage points, above the original 10-point maximum, despite a 49.377441% wire reduction.

## Identity and provenance

| Field | Value |
| --- | --- |
| repository | https://github.com/ThingDone/thingdaq.git |
| branch | experiment/rle-streaming |
| baseline_branch | experiment/baseline-2026-09-01 |
| baseline_commit | b23004defeca465da0ae2d2884c4fef71979e5d4 |
| source_commit | dca4343616a78ab71dedf08155359aeddd017859 |
| source_tree | 055d03da63298913b33f18edf0dfc06fa109d2c6 |
| source_clean | true |
| source_id | db824f42af030d7ed226900d3b68379962f7515f66734e51e4309773b04f5c4d |
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
| evidence-framework | **host** | PASS | The campaign-specific validator first performed 9,091 fail-closed identity, artifact, sequencing, measurement, conservation, cleanup, no-secret, and no-bulk-data checks. The shared experiment reporter then validated files, schema, Git identity, normalization, and two canonical renders. | `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/rle-streaming.json --json-output doc/results/experiments/rle-streaming.json --markdown-output doc/results/experiments/rle-streaming.md --check` |
| host-corpus-benchmark | **host** | PASS | Production protocol-v2 RAW/RLE_AUTO codec over the fixed nine-workload, 72-frame corpus with exact round-trip, no-expansion, throughput, and bounded-memory grading. | `python3 -m thingdaq.rle_benchmark --pretty` |
| local-firmware-gate | **host** | PASS | Current final4 candidate validation: complete repository regression, focused runner regression, protocol drift, Ruff, focused MyPy, target build/linker gates, and unchanged v1 compatibility. | `python3 -m pytest -q` |
| physical-accepted-campaign | **rig** | PASS | Ten strictly sequential final4 jobs programmed and ran the exact candidate; the campaign validator reconciled every accepted runner result, identity, checksum, formula, counter, queue, and cleanup field. | `python3 .maestro/playbooks/2026-09-01-Teensydaq/Working/rle-streaming-physical-campaign-00003/validate_completed_campaign.py` |
| physical-campaign | **rig** | INCONCLUSIVE | Replacement-board campaign 00003 with a fail-closed 9,091-check evidence validator; current conclusions combine the accepted short-stage evidence and the unresolved bounded endurance incident without importing measurements from superseded campaigns 00001 or 00002. | `python3 .maestro/playbooks/2026-09-01-Teensydaq/Working/rle-streaming-physical-campaign-00003/validate_completed_campaign.py` |
| physical-endurance-campaign | **rig** | INCONCLUSIVE | Two sequential 600-second RLE_AUTO attempts with repeated STATUS sampling, a dedicated fixed 512 KiB serial-reader queue, bounded retry, and mandatory STOP/final-IDLE cleanup. | `python3 .maestro/playbooks/2026-09-01-Teensydaq/Working/rle-streaming-physical-campaign-00003/validate_completed_campaign.py` |
| protocol-v1-compatibility | **host** | PASS | Byte comparison of the protocol-v1 contract and all generated v1 outputs and fixtures against the immutable baseline, plus a clean default v1/RAW simulator lifecycle. | `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h` |
| simulated-rig-gate | **simulated** | PASS | Stateful partial-I/O fake-device execution of all target patterns and fail-closed codec, counter, disconnect, and cleanup faults through the standalone rig. | `python3 -m pytest -q firmware/tests/test_rig_rle_streaming.py` |

## Metrics

| Metric | Value | Unit | Denominator | Scope | Evidence level | Evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| measurement_duration_seconds | 60.00481345807202 | second | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| adc_frames_observed | 64233 | frame | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| gpio_frames_observed | 64233 | frame | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| adc_payload_bytes | 260015184 | byte | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| gpio_payload_bytes | 260015184 | byte | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| combined_payload_bytes | 520030368 | byte | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| adc_framed_bytes | 263098368 | byte | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| gpio_framed_bytes | 3275883 | byte | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| combined_framed_bytes | 266374251 | byte | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| sequence_gap_frames | 0 | frame | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| adc_sequence_gap_frames | 0 | frame | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| gpio_sequence_gap_frames | 0 | frame | none | streaming_window | **rig** | ["physical-accepted-campaign"] |
| host_queue_drops | 0 | event | none | run | **rig** | ["physical-accepted-campaign"] |
| parser_errors | 0 | event | none | run | **rig** | ["physical-accepted-campaign"] |
| transport_errors | 0 | event | none | run | **rig** | ["physical-accepted-campaign"] |
| conservation_failures | 0 | event | none | final_status | **rig** | ["physical-accepted-campaign"] |
| command_latency_p99_milliseconds | 4.250181140378118 | millisecond | command_latency_samples | run | **rig** | ["physical-accepted-campaign"] |
| command_latency_maximum_milliseconds | 4.252566024661064 | millisecond | command_latency_samples | run | **rig** | ["physical-accepted-campaign"] |
| packet_owned_high_water_frames | 26 | frame | none | run | **rig** | ["physical-accepted-campaign"] |
| packet_buffer_capacity_frames | 200 | frame | none | artifact | **host** | ["local-firmware-gate"] |
| flash_used_bytes | 138236 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| flash_headroom_bytes | 1893380 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram1_used_bytes | 491488 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram1_headroom_bytes | 32800 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram2_used_bytes | 520192 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| ram2_headroom_bytes | 4096 | byte | none | artifact | **host** | ["local-firmware-gate"] |
| cpu_clock_hz | 600000000 | hertz | none | artifact | **host** | ["local-firmware-gate"] |
| logical_raw_bytes | 291456 | byte | none | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| logical_raw_bytes | 520030368 | byte | none | declared_codec_workload | **rig** | ["physical-accepted-campaign"] |
| encoded_wire_bytes | 143261 | byte | none | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| encoded_wire_bytes | 266374251 | byte | none | declared_codec_workload | **rig** | ["physical-accepted-campaign"] |
| encoded_to_raw_ratio | 0.49153560057092666 | ratio | logical_raw_bytes | declared_codec_workload | **host** | ["host-corpus-benchmark"] |
| encoded_to_raw_ratio | 0.5122282608695652 | ratio | logical_raw_bytes | declared_codec_workload | **rig** | ["physical-accepted-campaign"] |
| codec_throughput_bytes_per_second | 6001442.92401875 | byte_per_second | streaming_elapsed_seconds | declared_codec_benchmark | **host** | ["host-corpus-benchmark"] |
| codec_throughput_bytes_per_second | 245213819.86783877 | byte_per_second | streaming_elapsed_seconds | declared_codec_benchmark | **rig** | ["physical-accepted-campaign"] |

## Acceptance

| Check | Description | State | Expected | Observed | Reason | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| schema_valid | The matrix and report validate fail closed with no unknown state, level, metric, check, or limitation identifiers. | **PASS** | true | {"content_policy":true,"hashes":true,"matrix":true,"normalized_report":true} | — | ["evidence-framework"] |
| identity_complete | Required Git, source, protocol, toolchain, branch, and baseline identities are present and syntactically valid. | **PASS** | ["repository","branch","baseline_branch","baseline_commit","source_commit","source_tree","source_clean","source_id","protocol_contract_path","protocol_version","protocol_sha256","toolchains"] | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/rle-streaming","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"dca4343616a78ab71dedf08155359aeddd017859","source_id":"db824f42af030d7ed226900d3b68379962f7515f66734e51e4309773b04f5c4d","source_tree":"055d03da63298913b33f18edf0dfc06fa109d2c6","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} | — | ["evidence-framework"] |
| provenance_clean | Tracked canonical evidence was generated from the declared clean source commit and tree. | **PASS** | true | true | — | ["evidence-framework"] |
| artifact_hashes_verified | Every referenced input, firmware, map, manifest, and output artifact matches its declared SHA-256 and size. | **PASS** | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"903285a0642d689670dfb771d5cec7153d5558c951181657a7497d8b140e088d","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"5b2793c8d43dc16640e6ad234e8f170ad7ce6f054c4b71d623b1e6f345516f74","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"ac898ed5214200bb00ad8e6a8f7c3378dc20738f14e635ccf6f87f0dc3537897"} | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"903285a0642d689670dfb771d5cec7153d5558c951181657a7497d8b140e088d","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"5b2793c8d43dc16640e6ad234e8f170ad7ce6f054c4b71d623b1e6f345516f74","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"ac898ed5214200bb00ad8e6a8f7c3378dc20738f14e635ccf6f87f0dc3537897"} | — | ["local-firmware-gate"] |
| firmware_build_no_upload | The exact declared firmware profile compiles with the pinned toolchain without enumerating hardware or uploading firmware. | **PASS** | true | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"network_unused":true,"repeated_outputs_identical":true,"serial_hardware_unused":true,"upload_unused":true} | — | ["local-firmware-gate"] |
| deterministic_output | Two renders from identical normalized inputs are byte-identical JSON and Markdown. | **PASS** | {"firmware_build_1":"byte-identical","firmware_build_2":"byte-identical","report_json":"byte-identical","report_markdown":"byte-identical"} | {"firmware_build_1":"byte-identical","firmware_build_2":"byte-identical","report_json":"byte-identical","report_markdown":"byte-identical"} | — | ["evidence-framework","local-firmware-gate"] |
| lifecycle_complete | INFO, CONFIGURE, START, bounded data capture, STATUS, STOP, and cleanup complete in the declared order. | **INCONCLUSIVE** | true | {"accepted_short_stages":10,"default_v1_raw_simulator":true,"passing_endurance_600_seconds":false,"physical_configure":true,"physical_idle":true,"physical_info":true,"physical_start":true,"physical_status":true,"physical_stop":true,"simulated_fake_device":true} | All ten accepted short stages and both failed endurance attempts completed STOP/final-IDLE cleanup, but no 600-second acquisition completed without upstream serial byte loss. | ["physical-campaign","simulated-rig-gate"] |
| synthetic_formulas_exact | Every validated synthetic ADC pair and GPIO sample matches the declared deterministic formula and chronology. | **PASS** | all five target patterns match exact formulas and chronology | all five target patterns match exact formulas and chronology | — | ["physical-accepted-campaign","simulated-rig-gate"] |
| stream_health | Sequence gaps, loss, parser errors, transport errors, host-queue drops, and unexplained firmware errors are zero unless a named negative case declares and reconciles them. | **INCONCLUSIVE** | true | {"accepted_short_stage_active_errors_zero":true,"accepted_short_stage_parser_errors":0,"accepted_short_stage_sequence_gaps":0,"accepted_short_stage_transport_errors":0,"endurance_checksum_mismatches":1,"endurance_missing_prefix_events":1,"endurance_userspace_queue_saturated":false,"failure_layer_localized":false,"simulated_fake_device":true} | All ten accepted short stages had zero active loss/error counters, but both endurance attempts lost wire bytes upstream of a nonsaturated userspace queue; the responsible remote transport layer is unresolved. | ["physical-campaign","simulated-rig-gate"] |
| counter_conservation | All applicable frame, item, payload-byte, framed-byte, queue, loss, and source-stage equations are exact and nonsaturated. | **INCONCLUSIVE** | true | {"accepted_physical_raw":true,"accepted_physical_rle_auto":true,"accepted_synthetic_patterns":true,"host_corpus":true,"passing_endurance_600_seconds":null,"simulated_fake_device":true} | Logical, encoded-payload, selected-wire, frame-partition, queue, and cleanup equations were exact for every accepted stage; corrupted/incomplete endurance input prevented a complete 600-second conservation observation. | ["physical-campaign","simulated-rig-gate"] |
| queue_bounds | Every observed queue depth and high-water value is at or below its same-artifact advertised capacity. | **PASS** | 200 | 119 | — | ["physical-accepted-campaign","simulated-rig-gate"] |
| final_idle_cleanup | STOP and final cleanup leave IDLE with every required ownership and transport gauge at zero. | **PASS** | true | {"accepted_v2_runs_stop_and_idle":true,"endurance_attempts_stop_and_idle":true,"endurance_reader_empty":true,"service_queue_depth_zero":true,"simulated_positive_cases_idle":true} | — | ["physical-accepted-campaign","simulated-rig-gate"] |
| claim_scope_complete | Every required limitation is explicit and no conclusion exceeds the evidence level that supports it. | **PASS** | true | {"analog_performance_untested":true,"bandwidth_value_fail_reported_separately":true,"build_is_not_target_runtime":true,"campaign_00003_only_for_current_physical_conclusions":true,"campaigns_00001_00002_superseded_only":true,"compression_is_workload_dependent":true,"cross_branch_combinations_untested":true,"endurance_pass_not_claimed":true,"external_gpio_timing_untested":true,"replacement_serial_is_non_grading":true,"rig_correctness_inconclusive":true,"simulation_is_not_physical":true} | — | ["evidence-framework"] |

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
| firmware-build-manifest | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` | 13025 | `903285a0642d689670dfb771d5cec7153d5558c951181657a7497d8b140e088d` |
| firmware-eep | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| firmware-elf | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` | 1931952 | `5b2793c8d43dc16640e6ad234e8f170ad7ce6f054c4b71d623b1e6f345516f74` |
| firmware-hex | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` | 388911 | `b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248` |
| firmware-map | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` | 841281 | `ac898ed5214200bb00ad8e6a8f7c3378dc20738f14e635ccf6f87f0dc3537897` |

### Commands

- `evidence-framework` (host): `python3 firmware/tools/experiment_evidence.py --report doc/results/experiments/rle-streaming.json --json-output doc/results/experiments/rle-streaming.json --markdown-output doc/results/experiments/rle-streaming.md --check`
- `host-corpus-benchmark` (host): `python3 -m thingdaq.rle_benchmark --pretty`
- `local-firmware-gate` (host): `python3 -m pytest -q`
- `physical-accepted-campaign` (rig): `python3 .maestro/playbooks/2026-09-01-Teensydaq/Working/rle-streaming-physical-campaign-00003/validate_completed_campaign.py`
- `physical-campaign` (rig): `python3 .maestro/playbooks/2026-09-01-Teensydaq/Working/rle-streaming-physical-campaign-00003/validate_completed_campaign.py`
- `physical-endurance-campaign` (rig): `python3 .maestro/playbooks/2026-09-01-Teensydaq/Working/rle-streaming-physical-campaign-00003/validate_completed_campaign.py`
- `protocol-v1-compatibility` (host): `git diff --exit-code experiment/baseline-2026-09-01 HEAD -- protocol/protocol-v1.json protocol/fixtures daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h`
- `simulated-rig-gate` (simulated): `python3 -m pytest -q firmware/tests/test_rig_rle_streaming.py`
