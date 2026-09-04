---
type: report
title: "ThingDAQ Clock, Compression, and I/O Experiment Evidence"
created: 2026-09-04
tags:
  - thingdaq
  - experiment-evidence
  - synthesis
related:
  - "[[Experiment-Baseline]]"
  - "[[Evidence-Index]]"
  - "[[Protocol-V1]]"
  - "[[Acquisition-Pipeline]]"
  - "[[Firmware-Resource-Map]]"
  - "[[Hardware-Safety]]"
  - "[[1-MHz-Parallel-Output-Idea]]"
---

# ThingDAQ Clock, Compression, and I/O Experiment Evidence

> [!IMPORTANT]
> Independent branch results are not evidence that the features work together in one binary.

## Executive outcomes

| Experiment | Revision commit | Raw result | Evidence boundary |
| --- | --- | --- | --- |
| baseline | `b23004defeca465da0ae2d2884c4fef71979e5d4` | **PASS** | canonical Phase 01 report |
| rle-streaming | `2bf5a24b2ac6271fe24e3f9b3890edb6c150f3fb` | **INCONCLUSIVE** | canonical Phase 01 report |
| aux-input-bank | `c7ecb9a7aeed1291be8f3e50d496246e149e781c` | **FAIL** | canonical Phase 01 report |
| aux-output-bank | `03cc2ec9f8405345add9919097448283703fd0a3` | **INCONCLUSIVE** | canonical Phase 01 report |
| clock-450mhz | `2d2977af937f3d689ce6e47a8e44c6e0a2df5440` | **PASS** | bounded 10-second physical functional smoke |

## Reproducible input manifest

Frozen baseline: `b23004defeca465da0ae2d2884c4fef71979e5d4`

Matrix: `experiments/experiment-matrix.json` at SHA-256 `00f0593c3e950b9fb1ce2eca1ecf6c40b47c972f297c3e74e0c20ab46457c2c0`

| Experiment | Revision | Commit | Tree | Inputs |
| --- | --- | --- | --- | --- |
| baseline | `origin/experiment/baseline-2026-09-01` | `b23004defeca465da0ae2d2884c4fef71979e5d4` | `a21a27ee0823734dd570d916acf6912abab4e53f` | [{"path":"doc/results/experiments/baseline.json","sha256":"561d6f5d9bf050388c495e8c113e220b79edb619585dd04e1be72fbead40846b"},{"path":"doc/results/experiments/baseline.md","sha256":"6a7ee1a6f65114e5a446c50be8cbcecca94c6234c357c479ab418400a380cb7a"}] |
| rle-streaming | `origin/experiment/rle-streaming` | `2bf5a24b2ac6271fe24e3f9b3890edb6c150f3fb` | `40455a451832ed8ee4af09a279c9520a4537a2d8` | [{"path":"doc/results/experiments/rle-streaming.json","sha256":"b70f30419e85cfbd75c5febf1b33ada1b685ac9ae289f51fa0e5e6f6dd120e57"},{"path":"doc/results/experiments/rle-streaming.md","sha256":"bdc6571384bdb84cc040662251dc1998ed5c000fc4dc912892ebc43a09f4beed"}] |
| aux-input-bank | `origin/experiment/aux-input-bank` | `c7ecb9a7aeed1291be8f3e50d496246e149e781c` | `d5adedd6c169bbf3355cb28f40c1fc6a448776f0` | [{"path":"doc/results/experiments/aux-input-bank.json","sha256":"567da3549c6219e00be42c97bee94b1dd8512ca4b6593e4d5f512c45c11c5f32"},{"path":"doc/results/experiments/aux-input-bank.md","sha256":"ca6c42e2591fdbe5141b9814c01f33013e0e678291724ea0d103a7cd8f91c551"}] |
| aux-output-bank | `origin/experiment/aux-output-bank` | `03cc2ec9f8405345add9919097448283703fd0a3` | `2a538e0d12cfcfbc8647de479b6ebf3043cf4f68` | [{"path":"doc/results/experiments/aux-output-bank.json","sha256":"36553a966bf752dd87d7c31d476f50ab242e7f69d513ba4542c2ef6ff44f9112"},{"path":"doc/results/experiments/aux-output-bank.md","sha256":"5da3c61b305708e77e9ca1bf97cf695c7d9ee6362c5b6365974a2997b3a800ff"}] |
| clock-450mhz | `origin/experiment/clock-450mhz` | `2d2977af937f3d689ce6e47a8e44c6e0a2df5440` | `a7010c13c660a4520eab2f61918dd39ee36e196a` | [{"kind":"committed-adr","path":"doc/decisions/adr-005-experimental-clock-profiles.md","revision_commit":"2d2977af937f3d689ce6e47a8e44c6e0a2df5440","sha256":"b0714310b724df23a2bd662f1d8839539d3117e5bf7ac73f1aaefa25655837ce"},{"kind":"authorized-local-service-result","path":".maestro/playbooks/2026-09-01-Teensydaq/Working/clock-450mhz-physical-campaign-00001/smoke-450-attempt2-service-result.json","sha256":"21a4566ae18edd888772c5243cb722ee14311037f58446edf8aa7e2549ed619d"},{"kind":"authorized-local-summary","path":".maestro/playbooks/2026-09-01-Teensydaq/Working/clock-450mhz-physical-campaign-00001/result-summary.md","sha256":"55491e1d05084a32b72a821a728e014ac21861a1d180dfbc28a6a3d10fcbaee8"}] |

## Metric comparability

No values in this section are averaged, pooled, or presented as one build.

| Metric | Status | Exact values | Reason |
| --- | --- | --- | --- |
| acquisition_service_utilization_ratio | **SIDE_BY_SIDE_ONLY** | [{"denominator":"service_cycles","duration_basis":{"seconds":10.003074466018006,"status":"EXACT"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"ratio","value":0.7414}] | ["No peer value with the same metric name is present."] |
| adc_clock_hz | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"hertz","value":37500000},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"artifact","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"hertz","value":37500000}] | ["evidence level differs"] |
| adc_framed_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":41512960},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":524288},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":263098368}] | ["evidence level differs","duration scope differs"] |
| adc_framed_rate_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte_per_second","value":4047430.830039526},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte_per_second","value":4047430.8300395254}] | ["evidence level differs","duration scope differs"] |
| adc_frames_dropped | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0}] | ["No peer value with the same metric name is present."] |
| adc_frames_observed | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"frame","value":10135},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":128},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":64233}] | ["evidence level differs","duration scope differs"] |
| adc_pair_rate_hz | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"adc_pair_per_second","value":1000000},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"adc_pair_per_second","value":1000001.196026857},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"adc_pair_per_second","value":999999.9999999999},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":10.003074466018006,"status":"EXACT"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"adc_pair_per_second","value":999852.198839164}] | ["evidence level differs","duration scope differs"] |
| adc_pairs_dropped | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"adc_pair","value":0}] | ["No peer value with the same metric name is present."] |
| adc_pairs_observed | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"adc_pair","value":10256620},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"adc_pair","value":129536}] | ["evidence level differs","duration scope differs"] |
| adc_payload_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":41026480},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":518144},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":260015184}] | ["evidence level differs","duration scope differs"] |
| adc_payload_rate_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte_per_second","value":4000000},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte_per_second","value":3999999.9999999995}] | ["evidence level differs","duration scope differs"] |
| adc_phase_ticks | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"tick","value":4}] | ["No peer value with the same metric name is present."] |
| adc_sequence_gap_frames | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":0}] | ["evidence level differs","duration scope differs"] |
| codec_throughput_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"declared_codec_benchmark","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte_per_second","value":6001442.92401875},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"declared_codec_benchmark","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte_per_second","value":245213819.86783877}] | ["evidence level differs"] |
| combined_framed_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":83025920},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":1048576},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":266374251}] | ["evidence level differs","duration scope differs"] |
| combined_framed_rate_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte_per_second","value":12189723.320158103},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte_per_second","value":8094861.660079051}] | ["evidence level differs","duration scope differs"] |
| combined_payload_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":82052960},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":1036288},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":520030368}] | ["evidence level differs","duration scope differs"] |
| combined_payload_rate_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte_per_second","value":12000000},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte_per_second","value":7999999.999999999},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":10.003074466018006,"status":"EXACT"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"byte_per_second","value":7998412.9151294455}] | ["evidence level differs","duration scope differs"] |
| command_latency_maximum_milliseconds | **NONCOMPARABLE** | [{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"millisecond","value":20.994924940168858},{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"millisecond","value":1.0000000000047748},{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"run","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"millisecond","value":21.335070952773094},{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"run","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"millisecond","value":4.252566024661064}] | ["evidence level differs"] |
| command_latency_p99_milliseconds | **NONCOMPARABLE** | [{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"millisecond","value":2.102050930261612},{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"millisecond","value":1.0000000000047748},{"denominator":"command_latency_samples","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"run","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"millisecond","value":4.250181140378118}] | ["evidence level differs"] |
| conservation_failures | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"final_status","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"final_status","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"final_status","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"event","value":0}] | ["evidence level differs"] |
| cpu_clock_hz | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"hertz","value":600000000},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"artifact","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"hertz","value":450000000},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"hertz","value":600000000}] | ["evidence level differs"] |
| encoded_to_raw_ratio | **NONCOMPARABLE** | [{"denominator":"logical_raw_bytes","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"declared_codec_workload","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"ratio","value":0.49153560057092666},{"denominator":"logical_raw_bytes","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"declared_codec_workload","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"ratio","value":0.5122282608695652}] | ["evidence level differs"] |
| encoded_wire_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"declared_codec_workload","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":143261},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"declared_codec_workload","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":266374251}] | ["evidence level differs"] |
| firmware_dropped_frames | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"frame","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0}] | ["evidence level differs"] |
| firmware_dropped_items | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"event","value":0}] | ["No peer value with the same metric name is present."] |
| flash_headroom_bytes | **COMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":1904644},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":1893380}] | ["Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."] |
| flash_used_bytes | **COMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-input-bank","scope":"artifact","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte","value":150824},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-output-bank","scope":"artifact","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":132956},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":126972},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":138236}] | ["Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."] |
| gpio_framed_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":41512960},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":524288},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":3275883}] | ["evidence level differs","duration scope differs"] |
| gpio_framed_rate_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte_per_second","value":8094861.660079052},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte_per_second","value":4047430.8300395254}] | ["evidence level differs","duration scope differs"] |
| gpio_frames_dropped | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0}] | ["No peer value with the same metric name is present."] |
| gpio_frames_observed | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"frame","value":10135},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":128},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":64233}] | ["evidence level differs","duration scope differs"] |
| gpio_payload_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":41026480},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":518144},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":260015184}] | ["evidence level differs","duration scope differs"] |
| gpio_payload_rate_bytes_per_second | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte_per_second","value":8000000},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte_per_second","value":3999999.9999999995}] | ["evidence level differs","duration scope differs"] |
| gpio_sample_rate_hz | **NONCOMPARABLE** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"UNAVAILABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"streaming_window","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"gpio_sample_per_second","value":4000000},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"gpio_sample_per_second","value":3999600.007262244},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"gpio_sample_per_second","value":3999999.9999999995},{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":10.003074466018006,"status":"EXACT"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"gpio_sample_per_second","value":3999004.119772789}] | ["evidence level differs","duration scope differs"] |
| gpio_samples_dropped | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"gpio_sample","value":0}] | ["No peer value with the same metric name is present."] |
| gpio_samples_observed | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"gpio_sample","value":41026480},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"gpio_sample","value":518144}] | ["evidence level differs","duration scope differs"] |
| gpio_sequence_gap_frames | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":0}] | ["evidence level differs","duration scope differs"] |
| gpio_width_bits | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"analytic","experiment":"aux-input-bank","scope":"artifact_profile","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"bit","value":16},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"artifact_profile","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"bit","value":8}] | ["evidence level differs"] |
| host_queue_drops | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"run","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"event","value":0}] | ["evidence level differs"] |
| ipg_clock_hz | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"hertz","value":150000000},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"artifact","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"hertz","value":150000000}] | ["evidence level differs"] |
| logical_raw_bytes | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"declared_codec_workload","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":291456},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"declared_codec_workload","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":520030368}] | ["evidence level differs"] |
| measurement_duration_seconds | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"second","value":10.000572039047256},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"second","value":0.129536},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"second","value":10.003074466018006},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"second","value":60.00481345807202}] | ["evidence level differs"] |
| on_chip_temperature_celsius | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"declared_temperature_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"degree_celsius","value":37.281}] | ["No peer value with the same metric name is present."] |
| output_state_rate_hz | **SIDE_BY_SIDE_ONLY** | [{"denominator":"streaming_elapsed_seconds","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"analytic","experiment":"aux-output-bank","scope":"output_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"hertz","value":1000000}] | ["No peer value with the same metric name is present."] |
| output_underruns | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"event","value":0}] | ["No peer value with the same metric name is present."] |
| packet_buffer_capacity_frames | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-input-bank","scope":"artifact","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"frame","value":200},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"artifact","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"frame","value":194},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":200},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"artifact","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"frame","value":200},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":200}] | ["evidence level differs"] |
| packet_owned_high_water_frames | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"frame","value":37},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0},{"denominator":"none","duration_basis":{"seconds":10.003074466018006,"status":"EXACT"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"frame","value":20},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"run","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":26}] | ["scope differs","evidence level differs","duration scope differs"] |
| parser_errors | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"run","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"run","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"event","value":0}] | ["evidence level differs"] |
| pit_clock_hz | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"hertz","value":24000000},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"artifact","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"hertz","value":24000000}] | ["evidence level differs"] |
| ram1_headroom_bytes | **COMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-input-bank","scope":"artifact","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte","value":34528},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-output-bank","scope":"artifact","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":32768},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":34528},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":32800}] | ["Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."] |
| ram1_used_bytes | **COMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":489760},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":491488}] | ["Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."] |
| ram2_headroom_bytes | **COMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-input-bank","scope":"artifact","source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","unit":"byte","value":4096},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"aux-output-bank","scope":"artifact","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"byte","value":4096},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":4096},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":4096}] | ["Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."] |
| ram2_used_bytes | **COMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"byte","value":520192},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"host","experiment":"rle-streaming","scope":"artifact","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"byte","value":520192}] | ["Definitions, units, denominators, scope, evidence level, and duration basis are identical; artifact identities remain separate."] |
| sequence_gap_frames | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":10.000572039047256,"status":"EXACT"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"streaming_window","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"frame","value":0},{"denominator":"none","duration_basis":{"seconds":0.129536,"status":"EXACT"},"evidence_level":"simulated","experiment":"baseline","scope":"streaming_window","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"frame","value":0},{"denominator":"none","duration_basis":{"seconds":60.00481345807202,"status":"EXACT"},"evidence_level":"rig","experiment":"rle-streaming","scope":"streaming_window","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"frame","value":0}] | ["evidence level differs","duration scope differs"] |
| timestamp_clock_hz | **SIDE_BY_SIDE_ONLY** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"artifact","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"hertz","value":8000000}] | ["No peer value with the same metric name is present."] |
| transport_errors | **NONCOMPARABLE** | [{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"aux-output-bank","scope":"run","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"simulated","experiment":"baseline","scope":"run","source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"run","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"event","value":0},{"denominator":"none","duration_basis":{"seconds":null,"status":"NOT_APPLICABLE"},"evidence_level":"rig","experiment":"rle-streaming","scope":"run","source_commit":"dca4343616a78ab71dedf08155359aeddd017859","unit":"event","value":0}] | ["evidence level differs"] |
| usb_service_utilization_ratio | **SIDE_BY_SIDE_ONLY** | [{"denominator":"service_cycles","duration_basis":{"seconds":10.003074466018006,"status":"EXACT"},"evidence_level":"rig","experiment":"clock-450mhz","scope":"streaming_window","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6","unit":"ratio","value":0.1143}] | ["No peer value with the same metric name is present."] |

## Cross-experiment analysis

### 450 MHz physical smoke

| Category | Exact evidence |
| --- | --- |
| Source and scope | {"classification":"bounded 10-second physical functional smoke","evidence_id":"clock-450-physical-smoke","evidence_level":"rig","revision_commit":"2d2977af937f3d689ce6e47a8e44c6e0a2df5440","source_commit":"6b3ae88f5f5c2f27e49311084ec02ec85b9707f6"} |
| ADC resolution / clock tree | {"adc_resolution_bits":12,"clock_tree_hz":{"adc_hz":37500000,"cpu_hz":450000000,"ipg_hz":150000000,"pit_hz":24000000}} |
| Acquisition rates | {"adc_pair_rate_hz":999852.198839164,"combined_payload_rate_bytes_per_second":7998412.9151294455,"gpio_sample_rate_hz":3999004.119772789,"measurement_duration_seconds":10.003074466018006} |
| Loss, errors, and STOP tail | {"parser_errors":0,"stop_tail":{"adc_pairs":733,"gpio_samples":2935,"incomplete_completion":1},"transport_errors":0,"zero_error_field_names":["adc_destination_mismatches","adc_dma_error_events","adc_etc_error_events","adc_etc_error_flags","adc_frames_dropped","adc_frames_dropped_after_framing","adc_frames_dropped_after_promotion","adc_frames_evicted","adc_frames_evicted_after_promotion","adc_overwritten_conversions","adc_packer_chronology_errors","adc_packer_pipeline_errors","adc_packer_source_errors","adc_payload_bytes_dropped","adc_raw_drop_pairs_projected","adc_raw_gap_pairs","adc_raw_invariant_errors","adc_raw_ring_overruns","adc_resource_conflicts","adc_schedule_exhaustions","adc_stale_completions","adc_stale_interrupts","adc_start_errors","adc_stop_errors","bad_checksums","bad_flags","bad_lengths","bad_payloads","bad_request_ids","bad_types","bad_versions","clock_health_error_flags","clock_mismatch_count","commands_rejected","gpio_duplicate_samples_ignored","gpio_frames_dropped","gpio_frames_dropped_after_framing","gpio_frames_dropped_after_promotion","gpio_frames_evicted","gpio_frames_evicted_after_promotion","gpio_hardware_errors","gpio_packer_chronology_errors","gpio_packer_drop_samples_projected","gpio_packer_pipeline_errors","gpio_packer_samples_dropped","gpio_packer_source_errors","gpio_payload_bytes_dropped","gpio_raw_drop_samples_projected","gpio_raw_invariant_errors","gpio_raw_ring_overruns","gpio_resource_conflicts","gpio_stale_dma_completions","gpio_start_errors","gpio_stop_errors","health_adc_hardware_error_count","health_adc_trigger_error_count","packet_capacity_drops_without_evictable_frame","packet_encoding_rejections","packet_invalid_operations","packet_pool_exhaustions","packet_pressure_evictions","packet_ready_queue_rejections","packet_transmit_queue_rejections","parser_errors","response_queue_rejections","response_reservations_abandoned","service_counter_error_count","state_errors","timeouts","transport_errors","usb_io_errors"],"zero_error_fields":71} |
| Phase and completion | {"completion_counts":[8,8],"completion_expected_dwt_cycles":225,"completion_median_dwt_cycles":222,"completion_tolerance_dwt_cycles":90} |
| Utilization | {"acquisition":{"count":21,"maximum":7418,"median":7414,"minimum":7405,"p05":7407,"p95":7416,"p99":7418},"usb":{"count":21,"maximum":1149,"median":1143,"minimum":1136,"p05":1137,"p95":1148,"p99":1149}} |
| Queues and latency | {"latency_seconds":{"command":{"count":32,"maximum":0.021335070952773094,"median":0.002072578528895974,"minimum":0.0014937808737158775,"p05":0.00151059590280056,"p95":0.020878439070656896,"p99":0.021335070952773094},"status":{"count":23,"maximum":0.0021783560514450073,"median":0.0020536910742521286,"minimum":0.0014937808737158775,"p05":0.00151059590280056,"p95":0.0021465569734573364,"p99":0.0021783560514450073}},"queue_high_water_maxima":{"adc_raw":1,"gpio_raw":1,"packet_owned":20,"usb_command":1,"usb_response":1}} |
| On-chip temperature | {"count":21,"maximum":38509,"median":37281,"minimum":36053,"p05":36667,"p95":37895,"p99":38509} |

The 450 MHz and 600 MHz observations remain side by side; no delta is calculated.

- Comparison: **SIDE_BY_SIDE_ONLY** — ["No controlled same-board 600/450 MHz A/B campaign was executed.","The 600 MHz observation comes from a different auxiliary-output artifact and campaign.","The exact streaming durations differ, so the aggregate comparability key rejects a pooled performance result."]
- 450 MHz: {"adc_pair_rate_hz":999852.198839164,"artifact_sha256":"11d3b89666d83245b78fbb5e1a52a918c828fd9e859cd6f70a005d610dbb1651","command_latency_maximum_milliseconds":21.335070952773094,"duration_seconds":10.003074466018006,"gpio_sample_rate_hz":3999004.119772789,"packet_owned_high_water":20}
- 600 MHz reference: {"adc_pair_rate_hz":1000001.196026857,"artifact_sha256":"3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8","command_latency_maximum_milliseconds":20.994924940168858,"duration_seconds":10.000572039047256,"gpio_sample_rate_hz":3999600.007262244,"packet_owned_high_water":37,"source_experiment":"aux-output-bank"}
- 528 MHz fallback: {"adc_hz":33000000,"adc_resolution_bits":10,"canonical_input":false,"cpu_hz":528000000,"ipg_hz":132000000,"pit_hz":24000000,"role":"historical design context only","source":"authorized committed clock ADR"}
- Unestablished gates: ["same_board_ab_performance","endurance","analog_accuracy_aperture","power","comparative_thermal_benefit","reliability_lifetime"]

### RAW versus RLE_AUTO

Raw result: **INCONCLUSIVE**; configuration: {"default":"RAW","mixed_selection_permitted":true,"opt_in":"RLE_AUTO"}

Logical equality boundary: {"host_corpus_raw_rle_equal":true,"physical_run_caveat":"RAW and RLE_AUTO live physical runs conserve their own logical payloads; changing live inputs are not asserted byte-identical across separate runs.","physical_selected_payload_conservation":true}

| Stream | Logical bytes | RAW / selected wire bytes | Wire ratio / reduction | RAW / RLE / fallback frames (frequency) | Encode cycles / utilization delta (pp) | Decode RAW / RLE_AUTO (B/s) | Bandwidth / processing / overall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ADC | 260015184 | 263098368 / 263098368 | 1.0 / 0.0 | 64233 / 0 / 64233 ({"denominator":64233,"numerator":64233}) | 1797982213 / 4.609869667662673 | 212643149.0704229 / 215047155.10220528 | FAIL / PASS / **FAIL** |
| GPIO | 260015184 | 263098368 / 3275883 | 0.012451171875 / 0.987548828125 | 0 / 64233 / 0 ({"denominator":64233,"numerator":0}) | 2182388768 / 5.595454566741541 | 625681129.0397698 / 285224981.0584376 | PASS / PASS / **PASS** |
| COMBINED | 520030368 | 526196736 / 266374251 | 0.5062255859375 / 0.4937744140625 | 64233 / 64233 / 64233 ({"denominator":128466,"numerator":64233}) | 3980370981 / 10.205324234404214 | 317411314.6117571 / 245213819.86783877 | PASS / FAIL / **FAIL** |

- Matched durations: RAW 60.004249937832355 s; RLE_AUTO 60.00481345807202 s.
- Fallback detail: {"adc":{"encode_cycles":1797982213,"fallback_frames":64233,"fallback_reasons":{"encoder_failure":0,"not_smaller":64233,"temporary_page_unavailable":0}},"gpio":{"encode_cycles":2182388768,"fallback_frames":0,"fallback_reasons":{"encoder_failure":0,"not_smaller":0,"temporary_page_unavailable":0}}}
- Memory, queues, and latency: {"accepted_v2_maxima":{"host_parser_buffer_high_water_bytes":20479,"host_rss_bytes":22016000,"packet_owned_high_water":119,"packet_transmit_high_water":118,"status_latency_milliseconds":24.876834824681282,"temporary_page_high_water":1},"raw_host_memory":{"rss_end_bytes":22003712,"rss_growth_bytes":8192,"rss_maximum_bytes":22003712,"rss_start_bytes":21995520},"raw_queue_high_waters":{"adc_packet_ready_high_water":1,"adc_packet_transmit_high_water":23,"adc_raw_ready_high_water":1,"gpio_packed_ready_high_water":1,"gpio_packet_ready_high_water":1,"gpio_packet_transmit_high_water":23,"gpio_raw_ready_high_water":1,"packet_owned_high_water":46,"packet_ready_high_water":2,"packet_transmit_high_water":46,"temporary_page_high_water":0,"usb_command_queue_high_water":1,"usb_response_queue_high_water":1},"rle_auto_host_memory":{"rss_end_bytes":22016000,"rss_growth_bytes":8192,"rss_maximum_bytes":22016000,"rss_start_bytes":22007808},"rle_auto_queue_high_waters":{"adc_packet_ready_high_water":1,"adc_packet_transmit_high_water":13,"adc_raw_ready_high_water":1,"gpio_packed_ready_high_water":1,"gpio_packet_ready_high_water":1,"gpio_packet_transmit_high_water":12,"gpio_raw_ready_high_water":1,"packet_owned_high_water":26,"packet_ready_high_water":2,"packet_transmit_high_water":25,"temporary_page_high_water":1,"usb_command_queue_high_water":1,"usb_response_queue_high_water":1}}
- Evidence tiers: [{"evidence_id":"simulated-rig-gate","level":"simulated","result":"PASS","workload":"simulated fake-device protocol and fault cases"},{"evidence_id":"host-corpus-benchmark","level":"host","result":"PASS","workload":"host nine-workload codec corpus"},{"evidence_id":"physical-accepted-campaign","level":"rig","result":"PASS","workload":"physical synthetic patterns and matched live RAW/RLE_AUTO"}]
- Synthetic rig patterns: [{"combined_decode_bytes_per_second":381187051.59856045,"complete_wire_ratios":{"adc":0.01318359375,"combined":0.0128173828125,"gpio":0.012451171875},"fallback_frames":0,"firmware_encode_load_ratio":0.07215833093196648,"packet_owned_high_water":3,"pattern":"constant","temporary_page_high_water":1},{"combined_decode_bytes_per_second":182244417.00464156,"complete_wire_ratios":{"adc":0.014668945023661638,"combined":0.013929049456059597,"gpio":0.013189153888457556},"fallback_frames":0,"firmware_encode_load_ratio":0.2727286293305548,"packet_owned_high_water":3,"pattern":"sparse-hold","temporary_page_high_water":1},{"combined_decode_bytes_per_second":20387963.94291566,"complete_wire_ratios":{"adc":0.31494140625,"combined":0.2559814453125,"gpio":0.197021484375},"fallback_frames":0,"firmware_encode_load_ratio":0.3773369669758122,"packet_owned_high_water":119,"pattern":"slow-adc","temporary_page_high_water":1},{"combined_decode_bytes_per_second":1504230392.6592495,"complete_wire_ratios":{"adc":1.0,"combined":1.0,"gpio":1.0},"fallback_frames":21744,"firmware_encode_load_ratio":0.08392960495806741,"packet_owned_high_water":38,"pattern":"alternating","temporary_page_high_water":0},{"combined_decode_bytes_per_second":34786802.46630194,"complete_wire_ratios":{"adc":1.0,"combined":1.0,"gpio":1.0},"fallback_frames":21746,"firmware_encode_load_ratio":0.08412224379622806,"packet_owned_high_water":114,"pattern":"incompressible","temporary_page_high_water":0}]
- Protocol-v1 compatibility: {"default_raw":true,"level":"host","result":"PASS"}
- Endurance: {"lifecycle":{"reason":"All ten accepted short stages and both failed endurance attempts completed STOP/final-IDLE cleanup, but no 600-second acquisition completed without upstream serial byte loss.","state":"INCONCLUSIVE"},"reason":"Neither bounded 600-second attempt completed: one detected an ADC checksum mismatch and one received 1,855 ADC-like bytes without a frame prefix. The continuously drained reader stayed far below capacity and ended empty, so the loss is upstream of that queue but is not localized within the remote path.","result":"INCONCLUSIVE","stream_health":{"reason":"All ten accepted short stages had zero active loss/error counters, but both endurance attempts lost wire bytes upstream of a nonsaturated userspace queue; the responsible remote transport layer is unresolved.","state":"INCONCLUSIVE"}}

### Eight-input versus 16-input acquisition

Raw result: **FAIL**. Highest sustained 16-input raw profile: —. Eight-input regression: **FAIL_BEFORE_START**.

| Profile (ADC / GPIO) | Eight-input payload / framed exact / retention | 16-input payload / framed exact / retention | Campaign result |
| --- | --- | --- | --- |
| ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | {"combined_framed_bytes_per_second_exact":"2048000000/253","combined_payload_bytes_per_second":8000000,"combined_retention_microseconds":101200} | {"combined_framed_bytes_per_second_exact":"3084000000/253","combined_payload_bytes_per_second":12000000,"combined_retention_microseconds":50600} | **FAIL** — Two five-second eight-input CONTROL_COMBINED smokes failed the paired-DMA diagnostic before START; no streaming window opened. |
| ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | {"combined_framed_bytes_per_second_exact":"1024000000/253","combined_payload_bytes_per_second":4000000,"combined_retention_microseconds":202400} | {"combined_framed_bytes_per_second_exact":"1542000000/253","combined_payload_bytes_per_second":6000000,"combined_retention_microseconds":101200} | **NOT_RUN** — Escalation stopped after the reproducible maximum-rate safety/resource failure. |
| ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | {"combined_framed_bytes_per_second_exact":"512000000/253","combined_payload_bytes_per_second":2000000,"combined_retention_microseconds":404800} | {"combined_framed_bytes_per_second_exact":"771000000/253","combined_payload_bytes_per_second":3000000,"combined_retention_microseconds":202400} | **NOT_RUN** — Escalation stopped after the reproducible maximum-rate safety/resource failure. |
| ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | {"combined_framed_bytes_per_second_exact":"256000000/253","combined_payload_bytes_per_second":1000000,"combined_retention_microseconds":809600} | {"combined_framed_bytes_per_second_exact":"385500000/253","combined_payload_bytes_per_second":1500000,"combined_retention_microseconds":404800} | **NOT_RUN** — Escalation stopped after the reproducible maximum-rate safety/resource failure. |

- Frame layouts: {"eight_input":{"adc_bytes_per_item":4,"adc_items_per_frame":1012,"adc_payload_bytes":4048,"adc_total_frame_bytes":4096,"gpio_bytes_per_item":1,"gpio_items_per_frame":4048,"gpio_payload_bytes":4048,"gpio_total_frame_bytes":4096,"gpio_width_bits":8},"sixteen_input":{"adc_bytes_per_item":4,"adc_items_per_frame":506,"adc_payload_bytes":2024,"adc_total_frame_bytes":2072,"gpio_bytes_per_item":2,"gpio_items_per_frame":2024,"gpio_payload_bytes":4048,"gpio_total_frame_bytes":4096,"gpio_width_bits":16}}
- Processing and queues: {"host_packer_16bit_megabytes_per_second":1594.798,"host_parser_minimum_headroom_ratio":1.958,"target_processing_load":"NOT_RUN","target_queue_high_waters":"NOT_RUN"}
- Memory retention and ownership: {"auxiliary_workspace":{"active_bytes":992,"lease":"INPUT acquisition only; mutually exclusive with IDLE checksum benchmark","physical_storage":{"address":"0x20267220","alignment_bytes":32,"bytes":4096,"range_end_exclusive":"0x20280000","range_start":"0x20200000","symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer","symbol_type":"B"},"unleased_bytes":3104,"views":{"AUXILIARY_DESCRIPTORS":{"address":"0x20267520","alignment_bytes":32,"bytes":160,"offset_bytes":768,"owner":"AUX_GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"AUXILIARY_OVERFLOW_SINK":{"address":"0x202675e0","alignment_bytes":32,"bytes":32,"offset_bytes":960,"owner":"AUX_GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"PAIRED_JOIN_STATE":{"address":"0x20267220","alignment_bytes":32,"bytes":768,"offset_bytes":0,"owner":"GPIO_JOIN","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"PRIMARY_INPUT_OVERFLOW_SINK":{"address":"0x202675c0","alignment_bytes":32,"bytes":32,"offset_bytes":928,"owner":"GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"}}},"packet_retention":{"capacity":{"baseline_frames":200,"change_note":null,"current_frames":200,"delta_frames":0},"combined_complete_intervals":100,"combined_frames_per_interval":2,"profiles":[{"adc_pair_rate_hz":1000000,"gpio_sample_rate_hz":4000000,"modes":{"DISABLED":{"combined_retention_us":101200,"coverage_ticks":8096,"single_stream_retention_us":202400},"INPUT":{"combined_retention_us":50600,"coverage_ticks":4048,"single_stream_retention_us":101200}},"profile":"ADC_1MHZ_GPIO_4MHZ"},{"adc_pair_rate_hz":500000,"gpio_sample_rate_hz":2000000,"modes":{"DISABLED":{"combined_retention_us":202400,"coverage_ticks":16192,"single_stream_retention_us":404800},"INPUT":{"combined_retention_us":101200,"coverage_ticks":8096,"single_stream_retention_us":202400}},"profile":"ADC_500KHZ_GPIO_2MHZ"},{"adc_pair_rate_hz":250000,"gpio_sample_rate_hz":1000000,"modes":{"DISABLED":{"combined_retention_us":404800,"coverage_ticks":32384,"single_stream_retention_us":809600},"INPUT":{"combined_retention_us":202400,"coverage_ticks":16192,"single_stream_retention_us":404800}},"profile":"ADC_250KHZ_GPIO_1MHZ"},{"adc_pair_rate_hz":125000,"gpio_sample_rate_hz":500000,"modes":{"DISABLED":{"combined_retention_us":809600,"coverage_ticks":64768,"single_stream_retention_us":1619200},"INPUT":{"combined_retention_us":404800,"coverage_ticks":32384,"single_stream_retention_us":809600}},"profile":"ADC_125KHZ_GPIO_500KHZ"}],"raw_ring_overlay_preserves_packet_capacity":true,"unused_frames_after_complete_intervals":0},"raw_gpio_buffers":{"allocations":{"DESCRIPTORS":{"address":"0x2026c1c0","alignment_bytes":32,"bytes":160,"range_end_exclusive":"0x20280000","range_start":"0x20200000","symbol":"thingdaq::gpio_capture::g_gpio_raw_dma_descriptors","symbol_type":"B"},"OVERFLOW_SINK":{"address":"0x2026c260","alignment_bytes":32,"bytes":32,"range_end_exclusive":"0x20280000","range_start":"0x20200000","symbol":"thingdaq::gpio_capture::g_gpio_raw_dma_overflow_sink","symbol_type":"B"},"RING":{"address":"0x2026c280","alignment_bytes":32,"bytes":64768,"range_end_exclusive":"0x20280000","range_start":"0x20200000","symbol":"thingdaq::gpio_capture::g_gpio_raw_dma_buffers","symbol_type":"B"}},"mode_views":{"DISABLED":{"PRIMARY":{"DESCRIPTORS":{"address":"0x2026c1c0","bytes":160,"offset_bytes":0,"physical_allocation":"DESCRIPTORS"},"OVERFLOW_SINK":{"address":"0x2026c260","bytes":32,"offset_bytes":0,"physical_allocation":"OVERFLOW_SINK"},"RING":{"address":"0x2026c280","bytes":64768,"offset_bytes":0,"physical_allocation":"RING"}}},"INPUT":{"AUXILIARY":{"DESCRIPTORS":{"address":"0x20267520","alignment_bytes":32,"bytes":160,"offset_bytes":768,"owner":"AUX_GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"OVERFLOW_SINK":{"address":"0x202675e0","alignment_bytes":32,"bytes":32,"offset_bytes":960,"owner":"AUX_GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"RING":{"address":"0x20274100","bytes":32384,"offset_bytes":32384,"physical_allocation":"RING"}},"PRIMARY":{"DESCRIPTORS":{"address":"0x2026c1c0","bytes":160,"offset_bytes":0,"physical_allocation":"DESCRIPTORS"},"OVERFLOW_SINK":{"address":"0x202675c0","alignment_bytes":32,"bytes":32,"offset_bytes":928,"owner":"GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"RING":{"address":"0x2026c280","bytes":32384,"offset_bytes":0,"physical_allocation":"RING"}}}},"packet_storage_repartitioned":false,"shared_input_workspace":{"active_bytes":992,"lease":"INPUT acquisition only; mutually exclusive with IDLE checksum benchmark","physical_storage":{"address":"0x20267220","alignment_bytes":32,"bytes":4096,"range_end_exclusive":"0x20280000","range_start":"0x20200000","symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer","symbol_type":"B"},"unleased_bytes":3104,"views":{"AUXILIARY_DESCRIPTORS":{"address":"0x20267520","alignment_bytes":32,"bytes":160,"offset_bytes":768,"owner":"AUX_GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"AUXILIARY_OVERFLOW_SINK":{"address":"0x202675e0","alignment_bytes":32,"bytes":32,"offset_bytes":960,"owner":"AUX_GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"PAIRED_JOIN_STATE":{"address":"0x20267220","alignment_bytes":32,"bytes":768,"offset_bytes":0,"owner":"GPIO_JOIN","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"},"PRIMARY_INPUT_OVERFLOW_SINK":{"address":"0x202675c0","alignment_bytes":32,"bytes":32,"offset_bytes":928,"owner":"GPIO_CAPTURE","physical_allocation":"CHECKSUM_BENCHMARK_OCRAM","physical_symbol":"thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"}}},"total_bytes":64960}}
- Reproduced failure: {"counter_conservation":{"reason":"Diagnostic ownership/conservation failed before streaming; end-to-end run conservation was not measured.","state":"FAIL"},"lifecycle":{"reason":"Both counting attempts failed in the IDLE diagnostic before CONFIGURE/START.","state":"FAIL"},"stream_health":{"reason":"Both banks timed out without a complete DMA buffer and reported DMA errors.","state":"FAIL"}}
- Electrical transition scope: {"classification":"ELECTRICALLY_UNSTIMULATED","state":"NOT_RUN","ungraded":["external D16-D23 pin order","transition fidelity","voltage thresholds","timing and jitter","signal integrity"]}

### Auxiliary output

| Category | Exact evidence |
| --- | --- |
| Source / raw result | {"protocol_v2_sha256":"d6aae4456917798e439e0f58e8c06555373a7e8dd731586bee3c6fa646245c1c","revision_commit":"03cc2ec9f8405345add9919097448283703fd0a3","source_commit":"42e85a587bb784ede8177c7af710009be69ffa29"} / **INCONCLUSIVE** |
| Host output correctness | {"fresh_results":{"subtests_passed":373,"tests_passed":49},"method":"Fresh protocol/Python/portable/target/fake-rig/evidence tests plus the retained clean local gate exercise output lifecycle, conservation, interlocks, fault injection, and bounded refill.","result":"PASS"} |
| Output correctness | {"patterns":{"disconnect_reopen":"NOT_RUN","every_microsecond_transition":"NOT_RUN","finite_repeat":"NOT_RUN","forced_underrun_recovery":"NOT_RUN","host_stall":"NOT_RUN","infinite_repeat":"NOT_RUN","long_hold":"NOT_RUN","six_hundred_second_endurance":"NOT_RUN","sixty_second_combined":"NOT_RUN","varied_stop_phase":"NOT_RUN","walking_bit":"NOT_RUN"},"reason":"The service supplied no exact protected-loopback fixture declaration, so the interlock prohibited ARM and START and the physical output campaign was not submitted.","result":"NOT_RUN"} |
| Loopback lag / stability | {"lag_stability":"NOT_RUN","lag_ticks":null} |
| Combined ADC/GPIO preservation | {"result":"PASS","run":{"adc_framed_bytes":41512960,"adc_frames":10135,"adc_pair_rate_hz":1000001.196026857,"adc_pairs":10256620,"adc_payload_bytes":41026480,"adc_stop_tail_pairs":76,"all_commands_latency_max_ms":20.994924940168858,"common_final_timestamp_ticks":82052960,"complete_frames_dropped":0,"conservation_failures":0,"gpio_framed_bytes":41512960,"gpio_frames":10135,"gpio_payload_bytes":41026480,"gpio_processing_cpu_basis_points":2238,"gpio_sample_rate_hz":3999600.007262244,"gpio_samples":41026480,"gpio_stop_tail_samples":306,"host_rss_growth_bytes":200704,"measurement_seconds":10.000572039047256,"packet_capacity":194,"packet_owned_high_water":37,"parser_errors":0,"sequence_gaps":0,"status_latency_max_ms":2.102050930261612,"transport_errors":0},"scope":"auxiliary output disabled"} |
| Refill margin | {"historical_maximum_service_gap_us":60715,"packet_and_usb_margin_us":38461,"packet_and_usb_retention_us":99176,"packet_margin_us":37449,"packet_retention_us":98164} |
| STOP / hold / CLEAR / fault behavior | {"clear_releases_all_pins":true,"readback_injection_fail_closed":true,"resource_injection_fail_closed":true,"stale_output_replay_prevented":true,"stop_holds_observed_latch":true,"unauthorized_drive_writes":0,"underrun_injection_fail_closed":true} |
| Nondriving controls | {"drive_requests_written":0,"final_state":"IDLE","output_bank_disabled":true,"result":"PASS"} |
| Fixture safety declaration | {"declaration_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","drive_exercised":false,"state":"NOT_RUN"} |
| Independent signal integrity | {"required_evidence":"logic analyzer or oscilloscope","state":"NOT_RUN"} |

### Shared conflicts and synergies

| Interaction | Classification | Finding | Exact detail |
| --- | --- | --- | --- |
| d16_d23_whole_bank_direction | **CONFLICT** | D16-D23 are one whole bank and cannot be INPUT and OUTPUT simultaneously. | {"inputs":["aux-input-bank","aux-output-bank"]} |
| dma_xbar_and_memory_ownership | **CONFLICT** | Auxiliary input and output both claim eDMA channel 3, DMAMUX source 31, XBAR output 1, and overlapping global memory/packet ownership that requires one integrated allocation. | {"inputs":["aux-input-bank","aux-output-bank"],"resource_identity":{"dmamux_source":31,"edma_channel":3,"input_packet_frames":200,"output_packet_frames":194,"xbar_output":1}} |
| independent_protocol_v2_extensions | **CONFLICT** | RLE, auxiliary input, and auxiliary output are three different experimental protocol-v2 contracts, not one additive negotiated contract. | {"inputs":["rle-streaming","aux-input-bank","aux-output-bank"],"protocol_v2_sha256":{"aux-input-bank":"38d13bfef1dd2155e3adf49a182a099988733d13835bf64703ad78ee24a74a8d","aux-output-bank":"d6aae4456917798e439e0f58e8c06555373a7e8dd731586bee3c6fa646245c1c","rle-streaming":"2b9990ee46b3f9eff999d285c7e3fefb13947e79fda5d977b336ad75dab19aa3"}} |
| rle_terminology | **DISTINCTION** | Stream RLE_AUTO adaptively selects RAW or RLE independently per data frame; output program segments use duration/state run records for preloaded waveform expansion. They share run-length terminology but are not the same codec or wire format. | {"inputs":["rle-streaming","aux-output-bank"],"output_segment_schema":{"byte_order":"little","fields":[{"name":"duration_samples","offset":0,"type":"u32"},{"name":"logical_state_mask","offset":4,"type":"u32"}],"size":8},"stream_mode":"RLE_AUTO"} |
| rate_dependent_frame_layouts | **INTERACTION** | Auxiliary INPUT changes ADC/GPIO item counts and ADC frame length while each selected rate profile changes frame coverage; any unified decoder must negotiate mode, width, frame layout, and rate together. | {"inputs":["aux-input-bank","rle-streaming"],"layouts":{"DISABLED":{"adc_bytes_per_item":4,"adc_items_per_frame":1012,"adc_payload_bytes":4048,"adc_total_frame_bytes":4096,"gpio_bytes_per_item":1,"gpio_items_per_frame":4048,"gpio_payload_bytes":4048,"gpio_total_frame_bytes":4096,"gpio_width_bits":8},"INPUT":{"adc_bytes_per_item":4,"adc_items_per_frame":506,"adc_payload_bytes":2024,"adc_total_frame_bytes":2072,"gpio_bytes_per_item":2,"gpio_items_per_frame":2024,"gpio_payload_bytes":4048,"gpio_total_frame_bytes":4096,"gpio_width_bits":16}}} |
| shared_raw_defaults | **SYNERGY** | Every branch retains the frozen protocol-v1 raw acquisition contract and keeps its experimental capability opt-in, providing a common rollback boundary. | {"inputs":["rle-streaming","aux-input-bank","aux-output-bank","clock-450mhz"],"protocol_v1_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222"} |
| combined_binary_not_tested | **LIMITATION** | Clock, RLE, auxiliary input, and auxiliary output were never built or tested together in one immutable binary. | {"inputs":["clock-450mhz","rle-streaming","aux-input-bank","aux-output-bank"],"verified":false} |

## Source outcomes and limitations

### baseline

Raw result: **PASS**

Reason: —

#### Acceptance

| Check | State | Reason | Observed |
| --- | --- | --- | --- |
| schema_valid | **PASS** | — | {"matrix":true,"normalized_report":true} |
| identity_complete | **PASS** | — | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","branch":"main","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"becb45360afef2ae8375c4ce4a32061d47cb6570","source_id":"e27556de5b898f281dfbae8a9a1fefb486a4fa38a885516e2fac5ce6974ba673","source_tree":"0a1a41ce828269ca01294defc05c74ccb5c3f588","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} |
| provenance_clean | **PASS** | — | true |
| artifact_hashes_verified | **PASS** | — | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"7ecbe73a973ab12d45199300301aba784e905305d963fa11ba4ceba41fd5d56e","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"b3ae54862e9f6360b3623614bdf69c6aaf9fdf2476dda65829b49514d3fbaa4c","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"8566e88fd27f3fef07ae0ada3bca928a545851f6e0eb3d509dbec71df2f3ff44"} |
| firmware_build_no_upload | **PASS** | — | {"compile_completed":true,"exact_fqbn":true,"network_unused":true,"serial_hardware_unused":true,"upload_unused":true} |
| deterministic_output | **PASS** | — | {"json":"byte-identical","markdown":"byte-identical"} |
| lifecycle_complete | **PASS** | — | {"bounded_capture":true,"configure":true,"final_status":true,"info":true,"running_status":true,"start":true,"stop":true} |
| synthetic_formulas_exact | **PASS** | — | every logical item and timestamp matched |
| stream_health | **PASS** | — | {"firmware_drops_zero":true,"gaps_zero":true,"host_queue_drops_zero":true,"parser_errors_zero":true,"transport_errors_zero":true} |
| counter_conservation | **PASS** | — | {"adc_firmware_to_wire_frames":{"left":128,"right":128},"adc_framed_bytes":{"left":524288,"right":524288},"adc_items":{"left":129536,"right":129536},"adc_payload_bytes":{"left":518144,"right":518144},"adc_wire_to_consumer_frames":{"left":128,"right":128},"combined_framed_bytes":{"left":1048576,"right":1048576},"combined_payload_bytes":{"left":1036288,"right":1036288},"gpio_firmware_to_wire_frames":{"left":128,"right":128},"gpio_framed_bytes":{"left":524288,"right":524288},"gpio_items":{"left":518144,"right":518144},"gpio_payload_bytes":{"left":518144,"right":518144},"gpio_wire_to_consumer_frames":{"left":128,"right":128}} |
| queue_bounds | **PASS** | — | 0.9992681141741888 |
| final_idle_cleanup | **PASS** | — | {"all_gauges_zero":true,"state_idle":true,"stream_mask_empty":true,"transport_closed":true} |
| claim_scope_complete | **PASS** | — | {"analog_performance_untested":true,"build_is_not_target_runtime":true,"cross_branch_combinations_untested":true,"external_gpio_timing_untested":true,"live_usb_untested":true,"simulation_is_not_physical":true,"temperature_power_lifetime_scope":true} |

#### Incidents

| ID | State | Reason |
| --- | --- | --- |
| None recorded | — | — |

#### Claim limitations

- Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality.
- A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB.
- Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing.
- Without a declared external stimulus, evidence does not establish pad mapping, voltage thresholds, transition timing, jitter, or signal integrity.
- In-memory transport and host-only evidence do not establish sustained behavior on a live USB controller or operating system.
- On-chip temperature is not ambient temperature, power, junction characterization, or evidence of part lifetime; those claims require separately declared evidence.
- Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact.

#### Declared artifacts and evidence inputs

- `daq_api/src/thingdaq/client.py` — SHA-256 `1fcb1ef47b74c9a2ca0320378dd46f78583493ed21edadeeea86873c93408e66`
- `daq_api/src/thingdaq/simulator.py` — SHA-256 `238727e479defa2077be763c37250607f1d4576f3b34b010b1220eb3da50f6c4`
- `daq_api/src/thingdaq/streaming.py` — SHA-256 `5f296e4dd1db6fce990fffc89cfb8dd0e141a1e29d5ca236257cd7cc4fa91ae0`
- `daq_api/src/thingdaq/synthetic.py` — SHA-256 `1c0dea74d05c50111c699edaf7ff70cb4dcbcdedf8345f3f6e99621cfa66e311`
- `experiments/experiment-matrix.json` — SHA-256 `00f0593c3e950b9fb1ce2eca1ecf6c40b47c972f297c3e74e0c20ab46457c2c0`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` — SHA-256 `7ecbe73a973ab12d45199300301aba784e905305d963fa11ba4ceba41fd5d56e`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` — SHA-256 `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` — SHA-256 `b3ae54862e9f6360b3623614bdf69c6aaf9fdf2476dda65829b49514d3fbaa4c`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` — SHA-256 `da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` — SHA-256 `8566e88fd27f3fef07ae0ada3bca928a545851f6e0eb3d509dbec71df2f3ff44`
- `firmware/tools/baseline_prototype.py` — SHA-256 `5a35bff1deadca8bdac76923311552f20533942d3ccbbcd2666e77228e5bf1cc`
- `firmware/tools/build_firmware.py` — SHA-256 `61cbd926f714ee594a6a31e68c462efb241cab6840ed73ef92d3a8c30210ba71`
- `firmware/tools/experiment_evidence.py` — SHA-256 `c3c0fe5813c72bad3bf5f0b0eab3dc5823f97aca680defaade14710491e152e8`
- `protocol/protocol-v1.json` — SHA-256 `014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222`

### rle-streaming

Raw result: **INCONCLUSIVE**

Reason: The immutable final4 candidate passed the first ten strictly sequential stages through the matched physical RAW/RLE comparison. Both bounded 600-second endurance attempts then lost bytes upstream of a continuously drained 512 KiB userspace queue: the first detected one ADC checksum mismatch after 68 STATUS samples and the retry received 1,855 ADC-like payload bytes without the frame prefix after 98 samples. Both queues peaked at only 32 KiB, ended empty, and reached clean final IDLE. No passing 600-second observation exists, so rig correctness and the task remain inconclusive. The separately measurable physical value conclusion is FAIL because encoder utilization increased by 10.205324 percentage points, above the original 10-point maximum, despite a 49.377441% wire reduction.

#### Acceptance

| Check | State | Reason | Observed |
| --- | --- | --- | --- |
| schema_valid | **PASS** | — | {"content_policy":true,"hashes":true,"matrix":true,"normalized_report":true} |
| identity_complete | **PASS** | — | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/rle-streaming","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"dca4343616a78ab71dedf08155359aeddd017859","source_id":"db824f42af030d7ed226900d3b68379962f7515f66734e51e4309773b04f5c4d","source_tree":"055d03da63298913b33f18edf0dfc06fa109d2c6","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} |
| provenance_clean | **PASS** | — | true |
| artifact_hashes_verified | **PASS** | — | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"903285a0642d689670dfb771d5cec7153d5558c951181657a7497d8b140e088d","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"5b2793c8d43dc16640e6ad234e8f170ad7ce6f054c4b71d623b1e6f345516f74","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"ac898ed5214200bb00ad8e6a8f7c3378dc20738f14e635ccf6f87f0dc3537897"} |
| firmware_build_no_upload | **PASS** | — | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"network_unused":true,"repeated_outputs_identical":true,"serial_hardware_unused":true,"upload_unused":true} |
| deterministic_output | **PASS** | — | {"firmware_build_1":"byte-identical","firmware_build_2":"byte-identical","report_json":"byte-identical","report_markdown":"byte-identical"} |
| lifecycle_complete | **INCONCLUSIVE** | All ten accepted short stages and both failed endurance attempts completed STOP/final-IDLE cleanup, but no 600-second acquisition completed without upstream serial byte loss. | {"accepted_short_stages":10,"default_v1_raw_simulator":true,"passing_endurance_600_seconds":false,"physical_configure":true,"physical_idle":true,"physical_info":true,"physical_start":true,"physical_status":true,"physical_stop":true,"simulated_fake_device":true} |
| synthetic_formulas_exact | **PASS** | — | all five target patterns match exact formulas and chronology |
| stream_health | **INCONCLUSIVE** | All ten accepted short stages had zero active loss/error counters, but both endurance attempts lost wire bytes upstream of a nonsaturated userspace queue; the responsible remote transport layer is unresolved. | {"accepted_short_stage_active_errors_zero":true,"accepted_short_stage_parser_errors":0,"accepted_short_stage_sequence_gaps":0,"accepted_short_stage_transport_errors":0,"endurance_checksum_mismatches":1,"endurance_missing_prefix_events":1,"endurance_userspace_queue_saturated":false,"failure_layer_localized":false,"simulated_fake_device":true} |
| counter_conservation | **INCONCLUSIVE** | Logical, encoded-payload, selected-wire, frame-partition, queue, and cleanup equations were exact for every accepted stage; corrupted/incomplete endurance input prevented a complete 600-second conservation observation. | {"accepted_physical_raw":true,"accepted_physical_rle_auto":true,"accepted_synthetic_patterns":true,"host_corpus":true,"passing_endurance_600_seconds":null,"simulated_fake_device":true} |
| queue_bounds | **PASS** | — | 119 |
| final_idle_cleanup | **PASS** | — | {"accepted_v2_runs_stop_and_idle":true,"endurance_attempts_stop_and_idle":true,"endurance_reader_empty":true,"service_queue_depth_zero":true,"simulated_positive_cases_idle":true} |
| claim_scope_complete | **PASS** | — | {"analog_performance_untested":true,"bandwidth_value_fail_reported_separately":true,"build_is_not_target_runtime":true,"campaign_00003_only_for_current_physical_conclusions":true,"campaigns_00001_00002_superseded_only":true,"compression_is_workload_dependent":true,"cross_branch_combinations_untested":true,"endurance_pass_not_claimed":true,"external_gpio_timing_untested":true,"replacement_serial_is_non_grading":true,"rig_correctness_inconclusive":true,"simulation_is_not_physical":true} |

#### Incidents

| ID | State | Reason |
| --- | --- | --- |
| counter_conservation | **INCONCLUSIVE** | Logical, encoded-payload, selected-wire, frame-partition, queue, and cleanup equations were exact for every accepted stage; corrupted/incomplete endurance input prevented a complete 600-second conservation observation. |
| lifecycle_complete | **INCONCLUSIVE** | All ten accepted short stages and both failed endurance attempts completed STOP/final-IDLE cleanup, but no 600-second acquisition completed without upstream serial byte loss. |
| stream_health | **INCONCLUSIVE** | All ten accepted short stages had zero active loss/error counters, but both endurance attempts lost wire bytes upstream of a nonsaturated userspace queue; the responsible remote transport layer is unresolved. |
| physical-campaign | **INCONCLUSIVE** | The immutable final4 candidate passed the first ten strictly sequential stages through the matched physical RAW/RLE comparison. Both bounded 600-second endurance attempts then lost bytes upstream of a continuously drained 512 KiB userspace queue: the first detected one ADC checksum mismatch after 68 STATUS samples and the retry received 1,855 ADC-like payload bytes without the frame prefix after 98 samples. Both queues peaked at only 32 KiB, ended empty, and reached clean final IDLE. No passing 600-second observation exists, so rig correctness and the task remain inconclusive. The separately measurable physical value conclusion is FAIL because encoder utilization increased by 10.205324 percentage points, above the original 10-point maximum, despite a 49.377441% wire reduction. |
| physical-endurance-campaign | **INCONCLUSIVE** | Neither bounded 600-second attempt completed: one detected an ADC checksum mismatch and one received 1,855 ADC-like bytes without a frame prefix. The continuously drained reader stayed far below capacity and ended empty, so the loss is upstream of that queue but is not localized within the remote path. |

#### Claim limitations

- Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality.
- A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB.
- Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing.
- Without a declared external stimulus, evidence does not establish pad mapping, voltage thresholds, transition timing, jitter, or signal integrity.
- Compression results apply only to the declared workload and framing; they do not promise savings for noisy or incompressible inputs.
- Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact.

#### Declared artifacts and evidence inputs

- `daq_api/src/thingdaq/_generated/protocol_constants.py` — SHA-256 `a5dc4cd73dd12e291c03d536c2937d14ad1d0ca84b9c8a2860ad2797fbf15961`
- `daq_api/src/thingdaq/_generated/protocol_v2_constants.py` — SHA-256 `22028a2c0d25b5e23b14d278cc907198f043ff69cb82070b2d9202626e95e1b7`
- `daq_api/src/thingdaq/protocol_v2.py` — SHA-256 `8f2ce080b603e6b38accf4d7965a5ff1bbcb23e5ef7e91087e4ec3e327bc60ab`
- `daq_api/src/thingdaq/rle_benchmark.py` — SHA-256 `06dda22c1fc0dc5a7efe14c2bf8566a1be6b14ddf403d1e1a4d2721e23576034`
- `experiments/experiment-matrix.json` — SHA-256 `00f0593c3e950b9fb1ce2eca1ecf6c40b47c972f297c3e74e0c20ab46457c2c0`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` — SHA-256 `903285a0642d689670dfb771d5cec7153d5558c951181657a7497d8b140e088d`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` — SHA-256 `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` — SHA-256 `5b2793c8d43dc16640e6ad234e8f170ad7ce6f054c4b71d623b1e6f345516f74`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` — SHA-256 `b4ec27827331e8ed19075c78e74979192720711a0b3e8349b0b978f4c9add248`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` — SHA-256 `ac898ed5214200bb00ad8e6a8f7c3378dc20738f14e635ccf6f87f0dc3537897`
- `firmware/src/generated/protocol_constants.h` — SHA-256 `9604390433f7d8227432d341ecc65b9292002797da9457937ed4d5d3cc096290`
- `firmware/src/rle_encoder.cpp` — SHA-256 `3df710d175c63824d4386dd1c50f7906885eae1e7af02c2ced5cf5c71c6af2e4`
- `firmware/tests/rig_rle_streaming.py` — SHA-256 `c901ca0ed4bf0a607efc6bbaa75562855920775d154f347f055a0727b85c9967`
- `firmware/tests/rle_encoder_test.cpp` — SHA-256 `8815d8a05dddbd24404556b70abd54b42b74a3462d4306c509504d51e3c28f92`
- `firmware/tests/test_rig_rle_streaming.py` — SHA-256 `17ff613a4c67d3b7a11e1b83f6fa327ca1cb487eadf05744ba8fb9aa60726156`
- `firmware/tests/test_rle_encoder.py` — SHA-256 `7347b5dd0a0dbed532e068e29e2b3124620a025009841382bd24a9de86f9e761`
- `firmware/tools/build_firmware.py` — SHA-256 `61cbd926f714ee594a6a31e68c462efb241cab6840ed73ef92d3a8c30210ba71`
- `firmware/tools/experiment_evidence.py` — SHA-256 `c3c0fe5813c72bad3bf5f0b0eab3dc5823f97aca680defaade14710491e152e8`
- `protocol/fixtures/adc-data.bin` — SHA-256 `31a14e47c224fe2b7ef4bda7153b7ea37ecb7905c2b3e9732eb2fcecff2efd6a`
- `protocol/fixtures/checksum-benchmark-request.bin` — SHA-256 `95c062b0b6b8213c4a53278339f600ce86f67c7cdd64f0c485071a722b37602d`
- `protocol/fixtures/checksum-benchmark-response.bin` — SHA-256 `968e404a1d835f71b000be629fead1e4b821dcc9b235e7a8a3901d6ef063af7b`
- `protocol/fixtures/configure-request.bin` — SHA-256 `d78ac3972e6b7d049b6c764f835949d6098f104cce83595f1fcd7197c3b43cf9`
- `protocol/fixtures/configure-response.bin` — SHA-256 `aabf46243e588eb0d7e534ec6fa408f6cb0565c49d8c989e5743f5e25c13c95c`
- `protocol/fixtures/error-response.bin` — SHA-256 `d999ee9858397c7559bf937bb8c96e179e9cd7d158316f0ba4aac059c1efc47a`
- `protocol/fixtures/get-status-request.bin` — SHA-256 `c656785ffd4c3fbc4970ed3d31b134039bab2bc29300f564c0352017d5c17706`
- `protocol/fixtures/get-status-response.bin` — SHA-256 `fb1b9d1b471048f55a2c87b80bb436859e9aa6de4bf9c30d3031a0a694cab979`
- `protocol/fixtures/gpio-capture-diagnostic-request.bin` — SHA-256 `33e8b9e6395b4c0e9ef2f48bc6695b1fc06b79f15d899e1bcfec86629f61e8a6`
- `protocol/fixtures/gpio-capture-diagnostic-response.bin` — SHA-256 `ac24a6d9392364deefef376eda2e95cdc3fd51098d8a6d8231c0a7d9abd2d993`
- `protocol/fixtures/gpio-clock-diagnostic-request.bin` — SHA-256 `7d5fb760c5f6ad97fceb2576e248c0f9cefec7923db55a4e2c3f910dac995c66`
- `protocol/fixtures/gpio-clock-diagnostic-response.bin` — SHA-256 `25352e73531d85c93de82974718ae980caf53e22f8294db861184c55cd17af80`
- `protocol/fixtures/gpio-data.bin` — SHA-256 `2b998c3d3c587d0f3e2dcb71a657912c5081e85c729aae5927d8c3120a310749`
- `protocol/fixtures/info-request.bin` — SHA-256 `29b9b57a1d6fd8ac9599343b0c4a6f99d050d7fea89d8e4eacdf1dea95b45f3c`
- `protocol/fixtures/info-response.bin` — SHA-256 `71fe422700015d43b340aa35d079869370362ffaa8b2a67829f1785725b474c7`
- `protocol/fixtures/manifest.json` — SHA-256 `e354b6dd7749b4dcea9ee233297f5712f645c2d0a1444d990e22f02303c99568`
- `protocol/fixtures/ping-request.bin` — SHA-256 `3861fce26f53e4e1d2939756569b6e6b0819e15be856b878632b1d0b7d3d9cd8`
- `protocol/fixtures/ping-response.bin` — SHA-256 `7a0b37d42dc14845a3673052d2b5ec3472307f404f418a48dd0048db56b66f11`
- `protocol/fixtures/reset-stats-request.bin` — SHA-256 `4411da315ac2363cf323e858bdf89e351b221e80c255b523fc50846551091646`
- `protocol/fixtures/reset-stats-response.bin` — SHA-256 `cc22d2ea1cbcedfdd6863616557560e91db1b411d3782fa2dfe8fa21edc5f337`
- `protocol/fixtures/start-request.bin` — SHA-256 `6a05f4efc6119d9a0576d4629fa28eb2f01036cf3f1d6713d1b5690f179a70dd`
- `protocol/fixtures/start-response.bin` — SHA-256 `9d546cf5cbce61f812dc3f375b3d984c218b27e89af484b19d32839a7dded688`
- `protocol/fixtures/stop-request.bin` — SHA-256 `8025d47b1a62867a2c5b68eab10922f2b1c98c316d1c58254ce0488420013f9b`
- `protocol/fixtures/stop-response.bin` — SHA-256 `2a40df907e291a408b59482dd0267779634788aeb85d0ec8651331074726f13b`
- `protocol/protocol-v1.json` — SHA-256 `014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222`
- `protocol/protocol-v2.json` — SHA-256 `2b9990ee46b3f9eff999d285c7e3fefb13947e79fda5d977b336ad75dab19aa3`
- `tools/generate_protocol.py` — SHA-256 `ef2822b215bca3817d79bf84bd1ce8cc9bce0f62155a8342b286572ef2a5b4c1`

### aux-input-bank

Raw result: **FAIL**

Reason: Two identity-pinned immutable-artifact attempts reproduced a paired-DMA diagnostic failure before START; no profile established sustainable raw acquisition.

#### Acceptance

| Check | State | Reason | Observed |
| --- | --- | --- | --- |
| schema_valid | **PASS** | — | {"matrix":true,"normalized_report":true} |
| identity_complete | **PASS** | — | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/aux-input-bank","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"e36f94dc7de82f760b2bbe18bc94fa971dc073e6","source_id":"c1f05b3a2ebfc8b372a176852de0b16740d6739db6897f76de510d01831a7ac8","source_tree":"52a6577e01d8b8d8fb8243e2e131be61a7401677","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","name":"g++","version":"13.3.0"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} |
| provenance_clean | **PASS** | — | true |
| artifact_hashes_verified | **PASS** | — | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"682c66df9d4d45b3441d576bc63bad106970c14293ee71186fbf42087fec1fc5","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"a10f0b19a2cc2a07f46b6d0b20c84b67e8f9862ddaaea9f027389db665ed7741","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"6ade9731134a87475672607d746cb2b338fb923ccc72a7aeb04a075a88c9cb95","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"1b9e1cb295ea9975e4e92089dce25c545566713b2e8c10a3bf9c48edd63600ff"} |
| firmware_build_no_upload | **PASS** | — | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"repeat_outputs_byte_identical":true,"serial_hardware_unused":true,"upload_unused":true} |
| deterministic_output | **PASS** | — | {"json":"byte-identical","markdown":"byte-identical"} |
| lifecycle_complete | **FAIL** | Both counting attempts failed in the IDLE diagnostic before CONFIGURE/START. | {"bounded_capture":false,"configure":false,"diagnostic":false,"info":true,"start":false,"status":false,"stop_cleanup":true} |
| synthetic_formulas_exact | **NOT_RUN** | No physical streaming window opened. | — |
| stream_health | **FAIL** | Both banks timed out without a complete DMA buffer and reported DMA errors. | {"cleanup_idle":true,"complete_auxiliary_buffer_present":false,"complete_primary_buffer_present":false,"dma_errors_zero":false} |
| counter_conservation | **FAIL** | Diagnostic ownership/conservation failed before streaming; end-to-end run conservation was not measured. | {"auxiliary_complete_buffers":{"left":0,"right":1},"cache_acquisition":{"left":0,"right":14},"primary_complete_buffers":{"left":0,"right":1}} |
| queue_bounds | **NOT_RUN** | No streaming queue observations exist because START was never reached. | — |
| final_idle_cleanup | **PASS** | — | {"cleanup_stop_completed":true,"device_idle":true,"final_input_safe":true} |
| claim_scope_complete | **PASS** | — | {"candidate_failure_not_infrastructure":true,"cross_branch_claim_absent":true,"highest_profile_absent":true,"not_run_profiles_explicit":true,"signal_integrity_claim_absent":true,"unstimulated_values_not_physical_evidence":true} |

#### Incidents

| ID | State | Reason |
| --- | --- | --- |
| counter_conservation | **FAIL** | Diagnostic ownership/conservation failed before streaming; end-to-end run conservation was not measured. |
| lifecycle_complete | **FAIL** | Both counting attempts failed in the IDLE diagnostic before CONFIGURE/START. |
| queue_bounds | **NOT_RUN** | No streaming queue observations exist because START was never reached. |
| stream_health | **FAIL** | Both banks timed out without a complete DMA buffer and reported DMA errors. |
| synthetic_formulas_exact | **NOT_RUN** | No physical streaming window opened. |
| rig-rate-campaign | **FAIL** | The maximum-rate eight-input control failed the IDLE paired-DMA diagnostic before START. |
| rig-rate-campaign-reproduction | **FAIL** | The exact immutable-artifact repetition reproduced the same pre-START DMA failure signature. |

#### Claim limitations

- Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality.
- A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB.
- Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing.
- An unstimulated auxiliary input bank can establish transport and ownership behavior but not external pin order, transition capture, or electrical compatibility.
- Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact.

#### Declared artifacts and evidence inputs

- `.maestro/playbooks/Working/aux-input-rate-campaign/01-control-combined-max-smoke/job-record.json` — SHA-256 `8f56561064b5d4c007cfb73af73d7d75fce12d8f975075217d67dc117b592454`
- `.maestro/playbooks/Working/aux-input-rate-campaign/01-control-combined-max-smoke/results-response.json` — SHA-256 `63e826c06bbd7849c8a9142905dc737d5a0f1f3f1d5b41919e7f45028a8088ea`
- `.maestro/playbooks/Working/aux-input-rate-campaign/01-control-combined-max-smoke/rig-program.py` — SHA-256 `ee4902e7ee29fd72996a9b266989f8e51877b4c40a6e9ec1c81eb44a90645365`
- `.maestro/playbooks/Working/aux-input-rate-campaign/01b-control-combined-max-smoke/job-record.json` — SHA-256 `648d69fca59c98ccef9d55071b4cddfc0843ba1a26deabb8ee4fc02eaf23b449`
- `.maestro/playbooks/Working/aux-input-rate-campaign/01b-control-combined-max-smoke/results-response.json` — SHA-256 `b739c6df8bfd8d4e40449378f5c0e63bbc24790171d4b1e01ac4319acb3dc1fe`
- `.maestro/playbooks/Working/aux-input-rate-campaign/01b-control-combined-max-smoke/rig-program.py` — SHA-256 `ee4902e7ee29fd72996a9b266989f8e51877b4c40a6e9ec1c81eb44a90645365`
- `.maestro/playbooks/Working/aux-input-rate-campaign/02-control-combined-max-smoke/job-record.json` — SHA-256 `1eb261699b7e2f18210128d1814f76bdb1f5f73a9ad03cda4ee4f3156e1bb254`
- `.maestro/playbooks/Working/aux-input-rate-campaign/02-control-combined-max-smoke/results-response.json` — SHA-256 `e92cd568ad7cc91304c9b206e5a7c68217ca669925d16d7036d1204b83419224`
- `.maestro/playbooks/Working/aux-input-rate-campaign/02-control-combined-max-smoke/rig-program.py` — SHA-256 `c1325205bd00738151a75ba462ed82165929a4f53b0c458282da136e7708b0c4`
- `.maestro/playbooks/Working/aux-input-rate-campaign/03-control-combined-max-smoke-reproduction/job-record.json` — SHA-256 `680bafbc60a434eea8a89ffac8f415076e3b1fddb204b8cc983c642eaaaf5935`
- `.maestro/playbooks/Working/aux-input-rate-campaign/03-control-combined-max-smoke-reproduction/results-response.json` — SHA-256 `90ba3890694363a4949bcf7afd4b116e69b3da8bd66cf5878c49dee27f0bc3b4`
- `.maestro/playbooks/Working/aux-input-rate-campaign/03-control-combined-max-smoke-reproduction/rig-program.py` — SHA-256 `c1325205bd00738151a75ba462ed82165929a4f53b0c458282da136e7708b0c4`
- `.maestro/playbooks/Working/aux-input-rate-campaign/campaign-index.json` — SHA-256 `653750ed44200372f74ed85faa3699caf788daec0755ac3ead832e215fcb0327`
- `daq_api/examples/aux_input_matrix.py` — SHA-256 `488de342fa113face7c197c3e068346ad2b25a8583ba3b06e6e7e657236d8857`
- `daq_api/tests/test_aux_input_v2_contract.py` — SHA-256 `0e1e38be6cde760bba5793407388ab66a926ff1f22e11f0c5824089f3eaf3570`
- `doc/results/phase-06-aux-input-local-gate.md` — SHA-256 `4a2f5cb8ac527c3edb416a03d97573a99d3179c8adb5902ff692b742a5cedf86`
- `experiments/experiment-matrix.json` — SHA-256 `00f0593c3e950b9fb1ce2eca1ecf6c40b47c972f297c3e74e0c20ab46457c2c0`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` — SHA-256 `682c66df9d4d45b3441d576bc63bad106970c14293ee71186fbf42087fec1fc5`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` — SHA-256 `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` — SHA-256 `a10f0b19a2cc2a07f46b6d0b20c84b67e8f9862ddaaea9f027389db665ed7741`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` — SHA-256 `6ade9731134a87475672607d746cb2b338fb923ccc72a7aeb04a075a88c9cb95`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` — SHA-256 `1b9e1cb295ea9975e4e92089dce25c545566713b2e8c10a3bf9c48edd63600ff`
- `firmware/src/rate_profile_table.h` — SHA-256 `db66c96c31d70a45861f16b4f9b1feb0e0dce8c9ab5961ae16ef6ecafbce08fd`
- `firmware/tests/rig_aux_input_capture.py` — SHA-256 `a4a153c18b3bb522bbea2474664c77372713393bb5d79b3d733f4a37b6aa0cf3`
- `firmware/tests/test_rig_aux_input_capture.py` — SHA-256 `19dc54ea2c8ee3a1effebf06f2fb851f6f6629d18969e304e097c216d59c17a8`
- `firmware/tools/build_firmware.py` — SHA-256 `42d09a2da955b80670b861ea396c96254120b9fc82326d6e9dba0846b4585311`
- `firmware/tools/experiment_evidence.py` — SHA-256 `c3c0fe5813c72bad3bf5f0b0eab3dc5823f97aca680defaade14710491e152e8`
- `protocol/protocol-v2.json` — SHA-256 `38d13bfef1dd2155e3adf49a182a099988733d13835bf64703ad78ee24a74a8d`

### aux-output-bank

Raw result: **INCONCLUSIVE**

Reason: The protected D16-D23-to-D6-D13 fixture declaration was absent, so all physical-output and loopback checks remained NOT_RUN despite passing local lifecycle and physical no-output regressions.

#### Acceptance

| Check | State | Reason | Observed |
| --- | --- | --- | --- |
| schema_valid | **PASS** | — | {"matrix":true,"normalized_report":true} |
| identity_complete | **PASS** | — | {"baseline_branch":"experiment/baseline-2026-09-01","baseline_commit":"b23004defeca465da0ae2d2884c4fef71979e5d4","branch":"experiment/aux-output-bank","protocol_contract_path":"protocol/protocol-v1.json","protocol_sha256":"014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222","protocol_version":1,"repository":"https://github.com/ThingDone/thingdaq.git","source_clean":true,"source_commit":"42e85a587bb784ede8177c7af710009be69ffa29","source_id":"8c98b280873e15de4a83255e28a6e444f7d31b69d040dd5c18d2a5825f790f1d","source_tree":"769c736ffecebeab39728ce7b8fcc0bb0ae78505","toolchains":[{"identity":"arduino-cli  Version: 1.4.1 Commit: e39419312 Date: 2026-01-19T16:13:12Z","name":"arduino-cli","version":"1.4.1"},{"identity":"arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203","name":"arm-none-eabi-g++","version":"15.2.1"},{"identity":"g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","name":"g++","version":"13.3.0"},{"identity":"CPython 3.12.3","name":"python","version":"3.12.3"},{"identity":"teensy:avr 1.62.0","name":"teensy-core","version":"1.62.0"}]} |
| provenance_clean | **PASS** | — | true |
| artifact_hashes_verified | **PASS** | — | {"firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json":"b989f52131b70f6e88472258b09496d96cf2123bee90186092404bd9212731a3","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep":"c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf":"4c19383237f5537a80103014a2a0dfbde00795fcdcedce2f8859188ade54d110","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex":"3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8","firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map":"0c6a160e87507e4f66c43fba8f0dc8e2a6461718e57a1429adc26702df59ba8f"} |
| firmware_build_no_upload | **PASS** | — | {"compile_completed":true,"exact_fqbn":true,"firmware_inputs_clean":true,"repeat_outputs_byte_identical":true,"serial_hardware_unused":true,"upload_unused":true} |
| deterministic_output | **PASS** | — | {"json":"byte-identical","markdown":"byte-identical"} |
| lifecycle_complete | **NOT_RUN** | The complete physical-output lifecycle requires an exact protected-loopback fixture declaration, which was absent. | — |
| stream_health | **PASS** | — | {"complete_frame_loss_zero":true,"hardware_errors_zero":true,"no_output_combined_passed":true,"parser_errors_zero":true,"sequence_gaps_zero":true,"stop_tails_reconciled":true,"transport_errors_zero":true} |
| counter_conservation | **PASS** | — | {"adc_capture":{"left":10256696,"right":10256696},"adc_pipeline":{"left":10256620,"right":10256620},"combined_framed":{"left":83025920,"right":83025920},"combined_payload":{"left":82052960,"right":82052960},"gpio_capture":{"left":41026786,"right":41026786},"gpio_pipeline":{"left":41026480,"right":41026480},"promoted_frames":{"left":20270,"right":20270}} |
| queue_bounds | **PASS** | — | 37 |
| final_idle_cleanup | **PASS** | — | {"drive_requests_zero":true,"no_output_regression_idle":true,"nondriving_controls_idle":true,"output_bank_disabled":true,"queues_empty":true} |
| claim_scope_complete | **PASS** | — | {"analog_performance_claim_absent":true,"cross_branch_claim_absent":true,"host_target_distinction_explicit":true,"incidents_classified":true,"independent_timing_claim_absent":true,"loopback_lag_unmeasured_explicit":true,"physical_output_not_run_explicit":true,"signal_integrity_claim_absent":true} |

#### Incidents

| ID | State | Reason |
| --- | --- | --- |
| lifecycle_complete | **NOT_RUN** | The complete physical-output lifecycle requires an exact protected-loopback fixture declaration, which was absent. |
| protected-loopback-campaign | **NOT_RUN** | The service supplied no exact protected-loopback fixture declaration, so the interlock prohibited ARM and START and the physical output campaign was not submitted. |

#### Claim limitations

- Simulator evidence does not establish firmware target timing, USB behavior, electrical behavior, or physical signal quality.
- A no-upload build and linker/map inspection do not establish that the artifact ran correctly on a Teensy or over USB.
- Unstimulated or synthetic data do not establish ADC accuracy, noise, ENOB, linearity, bandwidth, source tolerance, or true aperture timing.
- Physical output checks may run only with an exact hashed safety/fixture authorization; absent authorization remains NOT_RUN and cannot be promoted to PASS.
- Firmware observing its own looped-back output is not independent certification of pad-level timing, voltage, jitter, or signal integrity.
- Independent candidate results do not establish that clock, compression, auxiliary input, and auxiliary output changes work together in one artifact.

#### Declared artifacts and evidence inputs

- `experiments/experiment-matrix.json` — SHA-256 `00f0593c3e950b9fb1ce2eca1ecf6c40b47c972f297c3e74e0c20ab46457c2c0`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json` — SHA-256 `b989f52131b70f6e88472258b09496d96cf2123bee90186092404bd9212731a3`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.eep` — SHA-256 `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.elf` — SHA-256 `4c19383237f5537a80103014a2a0dfbde00795fcdcedce2f8859188ade54d110`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex` — SHA-256 `3afc02d303871d106481f71cae3142aa9fc80e80532bd694e59d88cfc3a94bc8`
- `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.map` — SHA-256 `0c6a160e87507e4f66c43fba8f0dc8e2a6461718e57a1429adc26702df59ba8f`
- `firmware/firmware.ino` — SHA-256 `c34eb230606e9f88c5dffed98984fbc8548745753dab5db282672548e85b60ec`
- `firmware/src/board_config.h` — SHA-256 `e3d684bd08eaa8c5aa148e0cbb7d6fa922321e147e9655a5a11620e9feb01afe`
- `firmware/src/digital_output_engine.cpp` — SHA-256 `f530eda963d90df240155d919fc2a2a9a92d1b7c9bf1a0ade6e836183489eb61`
- `firmware/src/digital_output_teensy.cpp` — SHA-256 `4e44e15d04b00d78bbea1b247120533962c559973fec1964b6b7a5c59b2bbbaa`
- `firmware/src/edma_priority_teensy.h` — SHA-256 `89118cb424fbab69a8b209b9ce2733a2607e44756107cf275ccaab0e9a96b337`
- `firmware/tests/digital_output_engine_test.cpp` — SHA-256 `74ee42cdd7ef6d1ae1b754a1f165c5e1364a93c1ced4f8fb9501ba556cfdc6f9`
- `firmware/tests/digital_output_teensy_test.cpp` — SHA-256 `655c80676706ce7b5bd8db913dc757b495b1bc088673b13cff59dc680f3e56bb`
- `firmware/tests/rig_aux_output_loopback.py` — SHA-256 `421cc56def85051568e9a76aa000b02f94a664a437357d363f2af7ce7ffd5f44`
- `firmware/tests/rig_combined_capture.py` — SHA-256 `2c07ce755fa5ddbe2091e3eafbc269c92fa8681be8f365f79ac3bbe8a2d65544`
- `firmware/tests/test_rig_aux_output_loopback.py` — SHA-256 `d04a34a420fc40b66cf3aca73433039faa06576c99fdf692a4948dc618f58164`
- `firmware/tools/build_firmware.py` — SHA-256 `765c878439e94571e600f3892bc236b5db723e4d251e26440d6ea16f5e2c49ed`
- `firmware/tools/experiment_evidence.py` — SHA-256 `c3c0fe5813c72bad3bf5f0b0eab3dc5823f97aca680defaade14710491e152e8`
- `protocol/protocol-v2.json` — SHA-256 `d6aae4456917798e439e0f58e8c06555373a7e8dd731586bee3c6fa646245c1c`

### clock-450mhz

Raw result: **PASS**

Reason: —

#### Acceptance

| Check | State | Reason | Observed |
| --- | --- | --- | --- |
| physical_functional_smoke | **PASS** | — | — |
| same_board_ab_performance | **NOT_RUN** | No same-board controlled 600/450 MHz comparison was executed. | — |
| endurance | **NOT_RUN** | The physical run was bounded to ten seconds. | — |
| analog_accuracy_aperture | **NOT_RUN** | No external analog stimulus was exercised. | — |
| power | **NOT_RUN** | Core voltage is a profile target; rail power was not measured. | — |
| comparative_thermal_benefit | **NOT_RUN** | On-chip temperature was observed without a controlled comparison. | — |
| reliability_lifetime | **NOT_RUN** | A ten-second smoke cannot establish reliability or lifetime. | — |

#### Incidents

| ID | State | Reason |
| --- | --- | --- |
| initial_programming_write | **RECOVERED** | The first programming write failed; the bounded HalfKay retry succeeded in the same job. |
| immediate_stop_tail | **RECONCILED** | The discarded partial generation reconciled exactly and cleanup reached IDLE. |

#### Claim limitations

- No controlled same-board A/B performance comparison.
- No endurance evidence.
- No analog accuracy or aperture evidence.
- No measured power or comparative thermal benefit.
- No reliability or lifetime evidence.
- On-chip temperature is not ambient, power, or junction characterization.

## Evidence-backed conclusions

No authored conclusions were supplied.

## Recommendations

- **aux-input-bank: REJECT** — Reject this branch artifact, not the feature concept: both physical attempts failed before START with incomplete DMA buffers and DMA errors, so no 16-input rate, queue, conservation, processing-load, or electrical-transition claim was established.
- **aux-output-bank: CONTINUE** — Host lifecycle semantics and output-disabled physical acquisition passed, but the protected-loopback lifecycle, physical output correctness, lag/stability, and independent signal-integrity gates were not run because no authorized fixture declaration was available.
- **clock-450mhz: CONTINUE** — The ten-second 12-bit physical functional smoke passed, but same-board A/B performance, endurance, externally stimulated analog accuracy/aperture, power, comparative thermal benefit, reliability, and lifetime were not run.
- **rle-streaming: CONTINUE** — Logical conservation, bounded queues, cleanup, compatibility, and useful GPIO wire reduction passed in short runs, but the 600-second physical endurance gate remained inconclusive after upstream serial byte loss and combined-workload value did not pass.

### Production defaults and optional capabilities

Production recommendation: **RETAIN** — No experimental branch has complete evidence for production-default promotion; the frozen baseline remains the rollback and compatibility boundary.

Retained default: {"auxiliary_bank_mode":"DISABLED","cpu_hz":600000000,"gpio_width_bits":8,"protocol_version":1,"stream_encoding":"RAW"}

| Capability | Default | Recommendation | Availability |
| --- | --- | --- | --- |
| 450 MHz clock profile | 600 MHz | **CONTINUE** | experimental build profile only |
| RLE_AUTO stream encoding | RAW | **CONTINUE** | explicitly negotiated optional capability |
| D16-D23 auxiliary input | DISABLED with eight-input frames | **REJECT** | exclude the current failed artifact; require a replacement candidate |
| D16-D23 preloaded auxiliary output | DISABLED with high-impedance pins | **CONTINUE** | explicitly negotiated only after protected physical qualification |

### Python client compatibility and migration cost

Python-only prototype; no production client migration is authorized. Protocol-v1 RAW, eight-input parsing, 600 MHz identity, and output-disabled behavior remain byte-compatible defaults.

| Area | Cost | Required prototype work |
| --- | --- | --- |
| capability and configuration negotiation | **HIGH** | Replace three independent experimental-v2 capability documents with one versioned capability/rate/bank-mode contract and reject unsupported combinations atomically. |
| RLE_AUTO decoding | **MEDIUM** | Dispatch each frame by negotiated encoding, validate checksum before decode, enforce canonical frame-local runs, and accept RAW fallback inside RLE_AUTO. |
| rate-dependent acquisition layouts | **HIGH** | Select ADC/GPIO item widths, counts, frame lengths, timestamps, and NumPy dtypes from negotiated mode and exact rate-profile readback. |
| auxiliary output lifecycle | **HIGH** | Add generation-aware upload, commit, arm, status, held/faulted state, STOP semantics, and explicit CLEAR without treating output program runs as stream RLE records. |

## Staged integration and rollback plan

| Stage | Name | Action | Source policy | Exit gate |
| ---: | --- | --- | --- | --- |
| 1 | unified protocol-v2 contract | Define one additive capability negotiation and one exact rate/layout/bank-mode readback contract; INPUT and OUTPUT are mutually exclusive whole-bank values. | Reconcile the three candidate contracts; do not merge a candidate branch wholesale. | Generated protocol bytes, Python parser behavior, unknown-capability rejection, v1 fallback, and all legal/illegal combinations pass locally. |
| 2 | non-default clock profile | Port only the reviewed 450 MHz clock profile behind the retained 600 MHz production build default. | Use the 450 MHz branch as evidence and reviewed source material, not as an already qualified combined implementation. | Repeat exact clock/readback, phase, error, STOP/IDLE, same-board A/B, and endurance gates before promotion. |
| 3 | optional RLE_AUTO | Integrate adaptive stream compression behind RAW default and explicit capability negotiation. | Preserve per-frame RAW fallback and keep stream compression distinct from output-program run records. | Logical equality, checksum/decode ordering, fallback, load, queue, compatibility, and uninterrupted endurance pass on the integration artifact. |
| 4 | exclusive auxiliary bank modes | Integrate output only after protected-loopback evidence passes; do not import the rejected input implementation, and admit a replacement INPUT implementation only after its pre-START DMA defect is resolved. | Allocate eDMA channel 3, DMAMUX source 31, XBAR output 1, pins, packet memory, and priorities once in the integrated resource map. | Each selected mode passes its independent electrical, lifecycle, conservation, load, queue, and rollback gates while the other direction remains unavailable. |
| 5 | one-artifact compound qualification | Freeze one new 450 MHz integration source/build/HEX identity and run the complete local, rig, and endurance matrix without changing it between configurations. | No result from a candidate artifact may fill a missing cell for the new artifact. | All 24 negotiated configurations and their common/mode-specific gates pass before any combined claim. |

### Rollback paths

| Path | Preserve until |
| --- | --- |
| protocol-v1 RAW | every unified protocol-v2 compatibility and compound-matrix gate passes |
| eight-input frames with D16-D23 disabled | INPUT and OUTPUT independently pass every rate and lifecycle cell |
| 600 MHz production build profile | 450 MHz passes controlled same-board comparison, endurance, and required analog/power/thermal gates |

## Minimum compound test matrix

Claim boundary: INPUT and OUTPUT must each work with 450 MHz and RLE_AUTO on the same immutable build; they are mutually exclusive runtime modes and are never enabled simultaneously.

Immutable integration artifacts: **1**. Required configurations: **24**. Qualification tiers: ["local","rig_short","rig_endurance"].

Axes: {"auxiliary_bank_mode":["DISABLED","INPUT","OUTPUT"],"cpu_hz":[450000000],"rate_profiles":[{"adc_pair_rate_hz":1000000,"gpio_sample_rate_hz":4000000,"id":"ADC_1MHZ_GPIO_4MHZ"},{"adc_pair_rate_hz":500000,"gpio_sample_rate_hz":2000000,"id":"ADC_500KHZ_GPIO_2MHZ"},{"adc_pair_rate_hz":250000,"gpio_sample_rate_hz":1000000,"id":"ADC_250KHZ_GPIO_1MHZ"},{"adc_pair_rate_hz":125000,"gpio_sample_rate_hz":500000,"id":"ADC_125KHZ_GPIO_500KHZ"}],"stream_encoding":["RAW","RLE_AUTO"]}

| Configuration | Encoding | Bank mode / width | Rate profile (ADC / GPIO) | Output rate |
| --- | --- | --- | --- | ---: |
| 450-raw-disabled-adc_1mhz_gpio_4mhz | RAW | DISABLED / 8-bit | ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | — |
| 450-raw-disabled-adc_500khz_gpio_2mhz | RAW | DISABLED / 8-bit | ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | — |
| 450-raw-disabled-adc_250khz_gpio_1mhz | RAW | DISABLED / 8-bit | ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | — |
| 450-raw-disabled-adc_125khz_gpio_500khz | RAW | DISABLED / 8-bit | ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | — |
| 450-rle_auto-disabled-adc_1mhz_gpio_4mhz | RLE_AUTO | DISABLED / 8-bit | ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | — |
| 450-rle_auto-disabled-adc_500khz_gpio_2mhz | RLE_AUTO | DISABLED / 8-bit | ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | — |
| 450-rle_auto-disabled-adc_250khz_gpio_1mhz | RLE_AUTO | DISABLED / 8-bit | ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | — |
| 450-rle_auto-disabled-adc_125khz_gpio_500khz | RLE_AUTO | DISABLED / 8-bit | ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | — |
| 450-raw-input-adc_1mhz_gpio_4mhz | RAW | INPUT / 16-bit | ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | — |
| 450-raw-input-adc_500khz_gpio_2mhz | RAW | INPUT / 16-bit | ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | — |
| 450-raw-input-adc_250khz_gpio_1mhz | RAW | INPUT / 16-bit | ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | — |
| 450-raw-input-adc_125khz_gpio_500khz | RAW | INPUT / 16-bit | ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | — |
| 450-rle_auto-input-adc_1mhz_gpio_4mhz | RLE_AUTO | INPUT / 16-bit | ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | — |
| 450-rle_auto-input-adc_500khz_gpio_2mhz | RLE_AUTO | INPUT / 16-bit | ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | — |
| 450-rle_auto-input-adc_250khz_gpio_1mhz | RLE_AUTO | INPUT / 16-bit | ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | — |
| 450-rle_auto-input-adc_125khz_gpio_500khz | RLE_AUTO | INPUT / 16-bit | ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | — |
| 450-raw-output-adc_1mhz_gpio_4mhz | RAW | OUTPUT / 8-bit | ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | 1000000 |
| 450-raw-output-adc_500khz_gpio_2mhz | RAW | OUTPUT / 8-bit | ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | 1000000 |
| 450-raw-output-adc_250khz_gpio_1mhz | RAW | OUTPUT / 8-bit | ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | 1000000 |
| 450-raw-output-adc_125khz_gpio_500khz | RAW | OUTPUT / 8-bit | ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | 1000000 |
| 450-rle_auto-output-adc_1mhz_gpio_4mhz | RLE_AUTO | OUTPUT / 8-bit | ADC_1MHZ_GPIO_4MHZ (1000000 / 4000000) | 1000000 |
| 450-rle_auto-output-adc_500khz_gpio_2mhz | RLE_AUTO | OUTPUT / 8-bit | ADC_500KHZ_GPIO_2MHZ (500000 / 2000000) | 1000000 |
| 450-rle_auto-output-adc_250khz_gpio_1mhz | RLE_AUTO | OUTPUT / 8-bit | ADC_250KHZ_GPIO_1MHZ (250000 / 1000000) | 1000000 |
| 450-rle_auto-output-adc_125khz_gpio_500khz | RLE_AUTO | OUTPUT / 8-bit | ADC_125KHZ_GPIO_500KHZ (125000 / 500000) | 1000000 |

### Common gates

- one exact source/build/HEX identity across every cell
- unified protocol bytes and Python negotiation/parser round trip
- exact configured clock, rate, mode, layout, and resource readback
- START/STATUS/STOP/final-IDLE lifecycle
- zero unexplained ADC, GPIO, DMA, parser, transport, and USB loss/error counters
- exact frame, payload, sequence, and STOP-tail conservation
- bounded processing utilization, memory retention, queues, latency, and temperature
- 600 MHz, protocol-v1, RAW, eight-input, output-disabled rollback remains independently usable

### Mode-specific gates

- **RLE_AUTO**
  - RAW/RLE logical equality for ADC, GPIO, and combined streams
  - wire savings and fallback frequency by workload
  - encode/decode cost and v1 compatibility
- **INPUT**
  - externally stimulated D16-D23 bit mapping and transition fidelity
  - 16-input sustained rates, framed bandwidth, processing load, retention, and queue bounds
  - clean whole-bank direction rollback after STOP and every injected failure
- **OUTPUT**
  - authorized protected fixture and independent timing/signal-integrity capture
  - pattern correctness, loopback lag/stability, refill margin, and common-epoch alignment
  - finite completion, STOP/hold, CLEAR/high-impedance release, and injected fault behavior

## Human follow-up

Classification: human measurements and product decisions; not executable aggregation tasks or hidden approval gates.

### Manual measurements

- Run a longer same-board 600/450 MHz A/B campaign and 450 MHz endurance campaign.
- Apply traceable external analog stimulus to grade ADC accuracy and aperture at 450 MHz.
- Measure rail power and external temperature if power or comparative thermal benefit will be claimed.
- Stimulate D16-D23 externally to verify input mapping, voltage thresholds, transition fidelity, timing, jitter, and signal integrity on a replacement input candidate.
- Authorize a protected output fixture and capture output correctness, timing, lag stability, voltage levels, and signal integrity independently.

### User decisions

- Choose whether 450 MHz, RLE_AUTO, and auxiliary output justify continued integration investment.
- Choose whether to redesign the failed auxiliary-input implementation or remove INPUT from the unified contract.
- Choose supported rate profiles and whether optional modes must pass every profile before release.
- Choose fault policy and safety requirements for a combined acquisition/output product.

## Aggregate claim limitations

- Independent candidate results do not establish a combined clock, compression, and auxiliary-I/O binary.
- A host, analytic, or simulated result is not physical evidence.
- Different artifact identities remain separate even when metric definitions are comparable.
- Missing live or manual evidence remains FAIL, INCONCLUSIVE, or NOT_RUN exactly as reported.
