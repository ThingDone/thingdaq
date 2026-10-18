---
type: result
title: 600 MHz GPIO RLE Final Qualification
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# 600 MHz GPIO-only RLE final qualification

**For Bill:** planned campaign **PASS**: five jobs / 44 cells, 6,424 checks, 9,262,631,284 received bytes; peak sampled die temperature **67.983 °C**. Zero parser errors, discarded bytes or rejection windows (NONE). Smoke, three ten-minute captures and forty ten-second START/STOP cells without reflash all passed. Historical intermittent ADC DMA divergence remains unresolved; this PASS does not demonstrate a causal correction.

All authorized stages have completed their planned gates and reports: [endurance](clock600-ready-endurance-20261018.md) passed 18/18 ten-minute captures (2,358 checks, 69.211 °C peak; all eighteen after-STOP/peak readings are tabulated there), [STOP/restart](stop-recovery600-20261018.md) passed 42 cells (6,132 checks; maximum host-observed STOP response 21.528 ms, drain 123.380 ms, final IDLE 247.440 ms), and [larger ADC](large-adc600-20261018.md) passed five jobs/eight cells (1,168 checks, 69.825 °C peak). Those reports were committed as `46fb05a`, `d8162b3` and `57ea067`. Injected stalls/disconnects and fault-state recovery remain ungraded. This final stage completes the finite experiment; it does not establish production reliability or resolve every historical fault.

Immutable RLE image: `thingdaq-45d59c363f7aa067`, clean firmware source `30e7bfc227a889aa95f57ad45291e59a3cacd911`, HEX SHA-256 `bd8a89038d0f5387185b59d4b95499e6fc137cb5bf7f39bc9a4b2009824c768f`. Larger-ADC comparison image: `thingdaq-358337de6b642106`, HEX SHA-256 `b850159dcd294fa0f66f0bf647d15c2875703d3d8a627a9f455e133059cf10a1`. Both use 600 MHz CPU, two 12-bit ADCs at 1 MS/s each and sixteen GPIO inputs at 1 MHz. ADC stays RAW with 1,012 pairs per 4,096-byte frame; Adler-32 and all acceptance limits remain in force. The private GPIO format is opt-in and rejected by the ordinary SDK. No GPIO outputs were driven.

Every saved job was independently reclassified and reconciled against exact summaries, firmware, manifest, program, provenance and artifact hashes. Frozen orchestration/runner/validator hashes match. All five remote statuses are success; the local runner exited. Every cell passed STOP/drain/final-IDLE and idempotent STOP. Postflight service health was healthy with an empty queue; read-only Docker inspection found no active containers. Raw evidence remains in `doc/results/raw/gpio-rle600-phase-qualification-20261018`; [full machine-readable evidence](gpio-rle600-phase-qualification-20261018.json) retains all counters, identities and hashes.

| Job | Remote ID | Cells | Checks |
| --- | --- | ---: | ---: |
| smoke-60 | 7fb2fdba-37ca-4b5b-871d-dc84511cb5e9 | 1 | 146 |
| sustained-01 | 55dd4814-09e4-43ed-9b42-f0fa5a519d5f | 1 | 146 |
| sustained-02 | cb01aab0-b0fd-4330-8814-e518a785ab36 | 1 | 146 |
| sustained-03 | 6ec6a1a1-3839-46b7-bb8c-fffe2d9f4d33 | 1 | 146 |
| restart-40x10 | e5624554-ddcc-416b-abc4-790d19a86748 | 40 | 5,840 |

The comparison below uses three 600-second captures on each image. Baseline wire bytes are derived from validated frame counts × 4,096; RLE bytes are independently summed selected lengths, reconciled with firmware wire counters. GPIO savings compare the same logical frames with their RAW equivalent. Combined savings use ADC actual bytes plus GPIO RAW-equivalent bytes as denominator, excluding control traffic and unframed STOP tails.

| Sustained metric | Larger ADC, GPIO RAW | Larger ADC, GPIO RLE |
| --- | ---: | ---: |
| ADC frames | 1,779,476 | 1,779,489 |
| GPIO RAW frames | 889,737 | 0 |
| GPIO RLE frames | 0 | 889,743 |
| ADC wire bytes | 7,288,733,696 | 7,288,786,944 |
| GPIO actual wire bytes | 3,644,362,752 | 46,267,192 |
| GPIO RAW-equivalent wire bytes | 3,644,362,752 | 3,644,387,328 |
| All received bytes, including control | 10,938,620,960 | 7,340,621,932 |
| GPIO-service CPU median (%) | 15.72 | 16.86 |
| READY queue high-water | 2 | 2 |
| Transmit queue high-water | 49 | 24 |
| Peak sampled die temperature (°C) | 69.825 | 67.983 |

Sustained GPIO wire savings were **98.7305%**, or **32.9101%** of combined data wire bytes relative to RAW GPIO at the same frame counts. GPIO-service CPU increased from 15.72% to 16.86% (+1.14 percentage points). This counter includes synchronous RLE finalization in GPIO service, not total CPU or ADC processing. Different firmware instrumentation and initial thermal conditions prevent attributing queue or temperature differences solely to compression.

Across all 44 cells: 1,122,648 GPIO RLE frames, 0 GPIO RAW frames; 58,379,272 actual GPIO wire bytes versus 4,598,366,208 RAW-equivalent bytes (98.7304% saved). No physical RAW fallback was observed. Electrically unstimulated inputs favor compression and do not establish fidelity to an external waveform. Local known-pattern tests cover static, bursty, alternating and pseudorandom data, exact decode, malformed runs, pressure/RAW fallback, partial writes and ownership; see [implementation and validation](../../architecture/gpio-rle-experiment.md). Codec fidelity and physical unstimulated measurements are distinct evidence.

Current target resource gates retain 33,760 bytes RAM1 stack/local headroom, 4,096 bytes RAM2 heap headroom and the 819,200-byte packet pool. No extra full-size scratch page is allocated. The architecture record preserves the two earlier failed RAM1 builds; neither was flashed.

| RLE host-observed timing, all cells | Median (ms) | Maximum (ms) |
| --- | ---: | ---: |
| start_response_seconds | 19.078 | 19.464 |
| stop_response_seconds | 21.382 | 21.635 |
| stop_to_drained_seconds | 123.096 | 123.478 |
| stop_to_final_idle_status_seconds | 164.936 | 206.593 |
| idempotent_stop_response_seconds | 20.759 | 21.047 |

These timings include host and harness overhead, including the 100 ms drain quiet requirement. They grade normal STOP/restart and idempotent STOP, not injected-fault recovery.

| Job / cell | Before (°C) | After STOP (°C) | Peak (°C) |
| --- | ---: | ---: | ---: |
| smoke-60 / 1 | 44.650 | 55.702 | 55.702 |
| sustained-01 / 1 | 52.018 | 67.369 | 67.369 |
| sustained-02 / 1 | 61.229 | 67.983 | 67.983 |
| sustained-03 / 1 | 61.843 | 67.369 | 67.983 |
| restart-40x10 / 1 | 61.843 | 63.071 | 63.685 |
| restart-40x10 / 2 | 63.071 | 63.685 | 63.685 |
| restart-40x10 / 3 | 63.685 | 64.299 | 64.299 |
| restart-40x10 / 4 | 64.299 | 64.913 | 64.913 |
| restart-40x10 / 5 | 64.913 | 64.913 | 64.913 |
| restart-40x10 / 6 | 64.913 | 65.527 | 65.527 |
| restart-40x10 / 7 | 65.527 | 66.141 | 66.141 |
| restart-40x10 / 8 | 65.527 | 66.141 | 66.141 |
| restart-40x10 / 9 | 66.141 | 66.141 | 66.141 |
| restart-40x10 / 10 | 66.141 | 66.141 | 66.141 |
| restart-40x10 / 11 | 66.141 | 66.141 | 66.755 |
| restart-40x10 / 12 | 66.141 | 66.755 | 66.755 |
| restart-40x10 / 13 | 66.755 | 66.755 | 66.755 |
| restart-40x10 / 14 | 66.755 | 66.141 | 66.755 |
| restart-40x10 / 15 | 66.755 | 66.755 | 66.755 |
| restart-40x10 / 16 | 66.755 | 66.755 | 66.755 |
| restart-40x10 / 17 | 66.755 | 67.369 | 67.369 |
| restart-40x10 / 18 | 67.369 | 66.755 | 67.369 |
| restart-40x10 / 19 | 67.369 | 66.755 | 67.369 |
| restart-40x10 / 20 | 66.755 | 66.755 | 66.755 |
| restart-40x10 / 21 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 22 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 23 | 66.755 | 67.369 | 67.369 |
| restart-40x10 / 24 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 25 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 26 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 27 | 67.369 | 67.983 | 67.983 |
| restart-40x10 / 28 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 29 | 67.983 | 67.369 | 67.983 |
| restart-40x10 / 30 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 31 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 32 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 33 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 34 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 35 | 67.369 | 67.983 | 67.983 |
| restart-40x10 / 36 | 67.983 | 67.369 | 67.983 |
| restart-40x10 / 37 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 38 | 67.983 | 67.369 | 67.983 |
| restart-40x10 / 39 | 67.369 | 67.369 | 67.369 |
| restart-40x10 / 40 | 67.983 | 67.983 | 67.983 |

The 80 °C cutoff remains unchanged. Ambient/heatsink conditions were not independently measured; sampled peaks are not worst-case temperatures. Each job reflashes/resets, while the forty restart cells share one flash. This is repeated capture evidence, not an uninterrupted multi-hour stream.

All ten failed physical RLE campaigns remain FAIL and are retained below, with their JSON hashes in this report. The first host START buffering failure and boot timing failure are separate from the intermittent ADC DMA divergence. Deterministically reproduced accounting/common-prefix defects were addressed, but later indices 3/1 with apparent ADC0 lead persisted; the ineffective ADC1 preemption candidate was withdrawn. Early-phase instrumentation did not trigger a fault in the two preceding bounded diagnostics or this final campaign, and its added service work could affect timing. No claim is made that it corrected the divergence.

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

Earlier baseline USB corruption, temperature-readiness failure and the unclassified October 16 parser event retain their classifications in the endurance report. No failed run was relabeled PASS or included as a passing qualification cell. The finite authorized campaign is complete with these explicit limits; GPIO output and public SDK promotion remain outside scope.
