---
type: result
title: 600 MHz GPIO RLE ADC Request Fix Qualification
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# 600 MHz GPIO-only RLE ADC request fix qualification

**For Bill:** corrected ADC request campaign **PASS**: five jobs / 64 cells, 9,536 checks, 8,883,491,344 received bytes; peak sampled die temperature **64.913 °C**. Zero parser errors, discarded bytes or rejection windows (NONE). Smoke, three ten-minute captures and sixty five-second START/STOP cells without reflash all passed. The ADC1 request-source defect is corrected: the old route lost samples under GPIO DMA load; the new route clears on DMA acknowledgement. No hardware change is required.

The earlier stages retain their completed gates and reports: [endurance](clock600-ready-endurance-20261018.md) passed 18/18 ten-minute captures (2,358 checks, 69.211 °C peak; all eighteen after-STOP/peak readings are tabulated there), [STOP/restart](stop-recovery600-20261018.md) passed 42 cells (6,132 checks; maximum host-observed STOP response 21.528 ms, drain 123.380 ms, final IDLE 247.440 ms), and [larger ADC](large-adc600-20261018.md) passed five jobs/eight cells (1,168 checks, 69.825 °C peak). Those reports were committed as `46fb05a`, `d8162b3` and `57ea067`. Injected stalls/disconnects and fault-state recovery remain ungraded. This follow-up qualifies the causal firmware correction after reproduced negative controls; it does not establish production reliability or resolve unrelated historical parser evidence.

Immutable RLE image: `thingdaq-24c275c126c4e0d8`, clean firmware source `441d5bc`, HEX SHA-256 `7b82a6c5a5f0e758e3e34e212ae601b800ab2e647de0f8a000923f9e0d222071`. Larger-ADC comparison image: `thingdaq-358337de6b642106`, HEX SHA-256 `b850159dcd294fa0f66f0bf647d15c2875703d3d8a627a9f455e133059cf10a1`. Both use 600 MHz CPU, two 12-bit ADCs at 1 MS/s each and sixteen GPIO inputs at 1 MHz. ADC stays RAW with 1,012 pairs per 4,096-byte frame; Adler-32 and all acceptance limits remain in force. The private GPIO format is opt-in and rejected by the ordinary SDK. No GPIO outputs were driven.

Every saved job was independently reclassified and reconciled against exact summaries, firmware, manifest, program, provenance and artifact hashes. Frozen orchestration/runner/validator hashes match. All five remote statuses are success; the local runner exited. Every cell passed STOP/drain/final-IDLE and idempotent STOP. Postflight service health was healthy with an empty queue; read-only Docker inspection found no active containers. Raw evidence remains in `doc/results/raw/gpio-rle600-etc-fixed-20261018`; [full machine-readable evidence](gpio-rle600-etc-fixed-20261018.json) retains all counters, identities and hashes.

| Job | Remote ID | Cells | Checks |
| --- | --- | ---: | ---: |
| smoke-60 | d3bb181a-e86e-450c-8a28-12c851071110 | 1 | 149 |
| restart-60x5 | 8faf1280-6893-4e06-b117-5980d9484268 | 60 | 8,940 |
| sustained-1 | c12fc03e-17f3-4481-adbf-3e1c5b020b76 | 1 | 149 |
| sustained-2 | b71d15db-746f-44cf-b56d-21a859c6af3d | 1 | 149 |
| sustained-3 | 81533b36-fffd-4620-bfbd-9890fb574558 | 1 | 149 |

The comparison below uses three 600-second captures on each image. Baseline wire bytes are derived from validated frame counts × 4,096; RLE bytes are independently summed selected lengths, reconciled with firmware wire counters. GPIO savings compare the same logical frames with their RAW equivalent. Combined savings use ADC actual bytes plus GPIO RAW-equivalent bytes as denominator, excluding control traffic and unframed STOP tails.

| Sustained metric | Larger ADC, GPIO RAW | Larger ADC, GPIO RLE |
| --- | ---: | ---: |
| ADC frames | 1,779,476 | 1,779,489 |
| GPIO RAW frames | 889,737 | 0 |
| GPIO RLE frames | 0 | 889,743 |
| ADC wire bytes | 7,288,733,696 | 7,288,786,944 |
| GPIO actual wire bytes | 3,644,362,752 | 46,266,944 |
| GPIO RAW-equivalent wire bytes | 3,644,362,752 | 3,644,387,328 |
| All received bytes, including control | 10,938,620,960 | 7,340,843,048 |
| GPIO-service CPU median (%) | 15.72 | 17.31 |
| READY queue high-water | 2 | 2 |
| Transmit queue high-water | 49 | 16 |
| Peak sampled die temperature (°C) | 69.825 | 64.913 |

Sustained GPIO wire savings were **98.7305%**, or **32.9101%** of combined data wire bytes relative to RAW GPIO at the same frame counts. GPIO-service CPU increased from 15.72% to 17.31% (+1.59 percentage points). This counter includes synchronous RLE finalization in GPIO service, not total CPU or ADC processing. Different firmware instrumentation and initial thermal conditions prevent attributing queue or temperature differences solely to compression.

Across all 64 cells: 1,076,119 GPIO RLE frames, 0 GPIO RAW frames; 55,959,832 actual GPIO wire bytes versus 4,407,783,424 RAW-equivalent bytes (98.7304% saved). No physical RAW fallback was observed. Electrically unstimulated inputs favor compression and do not establish fidelity to an external waveform. Local known-pattern tests cover static, bursty, alternating and pseudorandom data, exact decode, malformed runs, pressure/RAW fallback, partial writes and ownership; see [implementation and validation](../../architecture/gpio-rle-experiment.md). Codec fidelity and physical unstimulated measurements are distinct evidence.

Current target resource gates retain 33,760 bytes RAM1 stack/local headroom, 4,096 bytes RAM2 heap headroom and the 819,200-byte packet pool. No extra full-size scratch page is allocated. The architecture record preserves the two earlier failed RAM1 builds; neither was flashed.

| RLE host-observed timing, all cells | Median (ms) | Maximum (ms) |
| --- | ---: | ---: |
| start_response_seconds | 19.056 | 19.644 |
| stop_response_seconds | 21.429 | 21.637 |
| stop_to_drained_seconds | 123.137 | 123.521 |
| stop_to_final_idle_status_seconds | 164.980 | 309.697 |
| idempotent_stop_response_seconds | 20.772 | 20.866 |

These timings include host and harness overhead, including the 100 ms drain quiet requirement. They grade normal STOP/restart and idempotent STOP, not injected-fault recovery.

| Job / cell | Before (°C) | After STOP (°C) | Peak (°C) |
| --- | ---: | ---: | ---: |
| smoke-60 / 1 | 40.965 | 49.562 | 49.562 |
| restart-60x5 / 1 | 48.334 | 49.562 | 49.562 |
| restart-60x5 / 2 | 49.562 | 50.176 | 50.176 |
| restart-60x5 / 3 | 50.790 | 51.404 | 51.404 |
| restart-60x5 / 4 | 51.404 | 51.404 | 51.404 |
| restart-60x5 / 5 | 52.018 | 52.632 | 52.632 |
| restart-60x5 / 6 | 53.246 | 52.632 | 53.246 |
| restart-60x5 / 7 | 53.246 | 53.246 | 53.246 |
| restart-60x5 / 8 | 53.860 | 54.474 | 54.474 |
| restart-60x5 / 9 | 54.474 | 54.474 | 54.474 |
| restart-60x5 / 10 | 55.088 | 55.088 | 55.088 |
| restart-60x5 / 11 | 55.088 | 55.088 | 55.088 |
| restart-60x5 / 12 | 55.702 | 55.702 | 55.702 |
| restart-60x5 / 13 | 56.316 | 55.702 | 56.316 |
| restart-60x5 / 14 | 56.930 | 56.316 | 56.930 |
| restart-60x5 / 15 | 56.930 | 56.316 | 56.930 |
| restart-60x5 / 16 | 56.930 | 56.930 | 56.930 |
| restart-60x5 / 17 | 57.544 | 57.544 | 57.544 |
| restart-60x5 / 18 | 57.544 | 57.544 | 57.544 |
| restart-60x5 / 19 | 57.544 | 57.544 | 57.544 |
| restart-60x5 / 20 | 58.158 | 58.158 | 58.158 |
| restart-60x5 / 21 | 58.772 | 58.158 | 58.772 |
| restart-60x5 / 22 | 58.772 | 58.772 | 58.772 |
| restart-60x5 / 23 | 58.772 | 58.772 | 58.772 |
| restart-60x5 / 24 | 59.386 | 58.772 | 59.386 |
| restart-60x5 / 25 | 58.772 | 59.386 | 59.386 |
| restart-60x5 / 26 | 59.386 | 59.386 | 59.386 |
| restart-60x5 / 27 | 60.000 | 59.386 | 60.000 |
| restart-60x5 / 28 | 60.000 | 59.386 | 60.000 |
| restart-60x5 / 29 | 60.000 | 59.386 | 60.000 |
| restart-60x5 / 30 | 60.615 | 60.000 | 60.615 |
| restart-60x5 / 31 | 60.000 | 60.000 | 60.000 |
| restart-60x5 / 32 | 60.615 | 60.615 | 60.615 |
| restart-60x5 / 33 | 60.000 | 60.000 | 60.000 |
| restart-60x5 / 34 | 60.615 | 60.000 | 60.615 |
| restart-60x5 / 35 | 60.615 | 60.615 | 60.615 |
| restart-60x5 / 36 | 60.615 | 60.615 | 60.615 |
| restart-60x5 / 37 | 61.229 | 60.615 | 61.229 |
| restart-60x5 / 38 | 61.229 | 60.615 | 61.229 |
| restart-60x5 / 39 | 61.229 | 61.229 | 61.229 |
| restart-60x5 / 40 | 61.229 | 60.615 | 61.229 |
| restart-60x5 / 41 | 61.229 | 60.615 | 61.229 |
| restart-60x5 / 42 | 61.843 | 61.229 | 61.843 |
| restart-60x5 / 43 | 61.229 | 61.229 | 61.229 |
| restart-60x5 / 44 | 61.843 | 61.229 | 61.843 |
| restart-60x5 / 45 | 61.843 | 61.843 | 61.843 |
| restart-60x5 / 46 | 61.843 | 61.843 | 61.843 |
| restart-60x5 / 47 | 61.843 | 61.843 | 61.843 |
| restart-60x5 / 48 | 62.457 | 61.843 | 62.457 |
| restart-60x5 / 49 | 61.843 | 61.843 | 61.843 |
| restart-60x5 / 50 | 61.843 | 61.843 | 61.843 |
| restart-60x5 / 51 | 62.457 | 61.229 | 62.457 |
| restart-60x5 / 52 | 62.457 | 61.843 | 62.457 |
| restart-60x5 / 53 | 61.843 | 61.843 | 61.843 |
| restart-60x5 / 54 | 62.457 | 61.843 | 62.457 |
| restart-60x5 / 55 | 62.457 | 61.843 | 62.457 |
| restart-60x5 / 56 | 62.457 | 61.843 | 62.457 |
| restart-60x5 / 57 | 62.457 | 62.457 | 62.457 |
| restart-60x5 / 58 | 62.457 | 62.457 | 62.457 |
| restart-60x5 / 59 | 62.457 | 61.843 | 62.457 |
| restart-60x5 / 60 | 62.457 | 62.457 | 62.457 |
| sustained-1 / 1 | 57.544 | 64.299 | 64.299 |
| sustained-2 / 1 | 59.386 | 64.299 | 64.913 |
| sustained-3 / 1 | 59.386 | 64.299 | 64.913 |

The 80 °C cutoff remains unchanged. Ambient/heatsink conditions were not independently measured; sampled peaks are not worst-case temperatures. Each job reflashes/resets, while the sixty restart cells share one flash. This is repeated capture evidence, not an uninterrupted multi-hour stream.

All thirteen failed physical campaigns remain FAIL: the ten earlier campaigns listed below, the newer GPIO-DPA comparison failure, and two ADC request-source negative-control failures. Their report hashes are retained. The host START buffering and boot timing failures are separate defects. Progressive ADC1 loss was reproduced with the original ADC2 COCO route and removed by selecting the ACK-cleared ADC_ETC trigger-4 request while retaining ADC2_R0, transfer size, descriptors, priorities, rates and codec. The exact bus-arbitration cycle was not instrumented; no undocumented silicon erratum is asserted.

- [start-boundary-failure](gpio-rle600-start-boundary-failure-20261018.md)
- [dma-failure](gpio-rle600-dma-failure-20261018.md)
- [dma-recurrence](gpio-rle600-dma-recurrence-20261018.md)
- [alignment-failure](gpio-rle600-alignment-failure-20261018.md)
- [boot-timing-failure](gpio-rle600-boot-timing-failure-20261018.md)
- [window-failure](gpio-rle600-window-failure-20261018.md)
- [descriptor-failure](gpio-rle600-descriptor-failure-20261018.md)
- [history-failure](gpio-rle600-history-failure-20261018.md)
- [counter-failure](gpio-rle600-counter-failure-20261018.md)
- [preemption-failure](gpio-rle600-preemption-failure-20261018.md)

Earlier baseline USB corruption, temperature-readiness failure and the unclassified October 16 parser event retain their classifications in the endurance report. No failed run was relabeled PASS or included as a passing qualification cell. The requested GPIO RLE DMA diagnosis and corrected-image qualification are complete with these limits; GPIO output and public SDK promotion remain outside scope.

## Root cause and qualification evidence

The [same-image request-source comparisons](gpio-rle600-adc-request-ab-20261018.md) passed 7/7 ADC_ETC captures and reproduced two original-route failures (five other original-route captures passed). Both failures showed a growing ADC1 deficit, approximately one lost transfer per 2,024 GPIO samples. The [GPIO preemption comparison](gpio-rle600-preempt-ab-failure-20261018.md) also failed and ruled out GPIO DPA alone as the correction. Those negative controls remain failures and are excluded from this campaign’s pass count.

All 64 corrected captures verified the actual ADC1 mux (23), trigger-4 enable and ACK-cleared mode after STOP. The 640 retained early/final phase observations range from -1 to 1 apparent ADC0 lead samples; maximum sequential read span 1401 core cycles. Each was checked against its timed sequential-read allowance. No progressive ADC1 deficit recurred.

The correction is confined to private RLE builds. ADC0 and public non-RLE ADC request routes remain unchanged; the shared ETC source is assigned only to trigger 4. Normal INFO metadata continues to describe the ordinary route, while corrected private INFO advertises source 23. The result does not qualify arbitrary electrical inputs or the original route under different workloads.

Local validation: the complete firmware suite passed 324 tests and 838 subtests, with three skipped build combinations. Corrected RLE and ordinary non-RLE 600 MHz larger-ADC target builds passed their normal resource gates. Test/build logs and hashes accompany the machine-readable report. The first bare pytest invocation had an import-path collection failure; the recorded passing run used python -m pytest from the repository root.

See the [investigation log](../../research/gpio-rle-dma-investigation.md) for register interpretation, rejected hypotheses and reference-manual sections. Physical inputs were unstimulated, ambient temperature was not recorded, and no hardware modification was required.
