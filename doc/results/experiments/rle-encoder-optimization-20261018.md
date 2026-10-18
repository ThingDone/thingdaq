---
type: result
title: Isolated RLE Encoder Optimization at 600 MHz
created: 2026-10-18
tags: [firmware, compression, performance]
related: []
---

# Isolated RLE encoder optimization at 600 MHz

**For Bill:** all four physical benchmark jobs passed: two 14-variant pilots and a final matched-source pair with 19 variants. This validates 5,280 timing rows and 163,680 timed invocations, each checked for exact output, unchanged input and output bounds. The final pair compares per-function optimization and algorithm variants with/without LTO. Acquisition firmware is unchanged and the qualified image was restored with a passing combined-input capture.

## Findings

The no-LTO DTCM hybrid Os candidate takes 4.112 cycles/sample for constant input versus 8.305 for the baseline (2.02× faster), 9.751 versus 50.047 for 32-sample runs (5.13×), and 15.802 versus 76.613 for three-sample runs (4.85×). Alternating/random RAW fallback stays near 3.09 cycles/sample. It avoids rechecking a constant block after sizing has already proven equality, and avoids the generic per-item comparison/record path for other selected blocks.

The span Os one-pass candidate is faster on changing compressible data: 5.429 cycles/sample for 32-sample runs and 9.353 for three-sample runs, versus 50.047 and 76.613 in the baseline. Its tradeoff is RAW fallback: approximately 6.02 cycles/sample for alternating/random input versus 3.09 for the sizing-first baseline. This is not a universal replacement; the hybrid is the conservative next integration candidate.

Function-only O3 is much less effective: 76.613 → 71.673 cycles/sample on three-sample runs, while constant input slightly regresses (8.305 → 8.384). Higher optimization levels are not monotonically faster; Os wins for these small specialized loops. LTO produces no broad improvement: baseline three-sample runs increase from 76.613 to 78.270 cycles/sample in the final DTCM pair, while the hybrid changes from 15.802 to 15.479. Link layout also changes. The pilots and final images do not support enabling whole-firmware LTO as an assumed performance win.

Across both RAM regions and all five no-LTO sweeps, the hybrid Os maximum observed block time was 53.447 µs (worst sweep median 53.332 µs), versus a 2,024 µs arrival interval. The span Os maximum was 38.903 µs and baseline maximum 258.492 µs. These are measured isolated maxima, not worst-case execution guarantees under acquisition/cache pressure. The hybrid’s worst median corresponds to about 2.64% of a 600 MHz core at 1 MS/s for selection/encoding alone.

## Method and scope

Teensy 4.0 serial 20428100; 600 MHz core; GCC 15.2.1; pinned Teensy core 1.62.0. The final images use clean source `1992d83d51774d1beb7c44f495993e3d4c3b4aa1`. Their compiled source hashes match except the image-name banner. The no-LTO snapshot also retains seven unused .inc files from the first failed harness build; Arduino did not copy them into the compilation directory. Their names/hashes are retained and explicitly excluded from the active-source comparison. Default compilation is O2; the second image enables LTO. Each function variant retains its stated optimization attribute or translation-unit pragma. The original encoder and its protocol helper are copied from production source; no hand-written substitute is used for the baseline. The separate sketch does not link acquisition DMA.

Each image runs five sweeps with rotated variant order, eight deterministic patterns, DTCM/OCRAM input and output, and 31 measurements per case after warming caches. IRQs remain enabled. DWT timestamps include call/barrier overhead and any interrupt preemption. Correctness, temperature cutoff, pattern generation and serial reporting occur outside timing. The host independently reconstructs canonical RLE output. Every per-trial board comparison is byte-for-byte; the host also checks output/input digests and complete case coverage. The 80 °C cutoff remains active, but this is not a thermal qualification.

The timed path is selection plus encoding into scratch, excluding checksum, frame construction, copy-back, queueing and USB. All costs are normalized per **incoming** sample; early RAW rejection may inspect only part of the 2,024-sample input. Scratch output is limited to 4,044 bytes, preserving the strict smaller-than-RAW rule. Single-pass candidates require valid disjoint fixed-shape buffers; they do not implement the generic API’s complete argument checks. Partial scratch from a RAW decision is discarded.

## Final timing matrix

Entries are cycles per incoming sample: median of the five sweep medians. Lower is better. The full JSON retains every sweep’s minimum/median/maximum and all provenance. Code layout changes with compilation; these are measured images, not guarantees that another placement will preserve small differences.

### O2, DTCM

| Variant | constant | runs32 | runs3 | runs2 | alternating | random | pulses | last_change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_O2 | 8.30 | 50.05 | 76.61 | 8.08 | 3.09 | 3.09 | 48.90 | 47.35 |
| encode_O0 | 8.43 | 69.44 | 98.72 | 8.08 | 3.09 | 3.09 | 68.16 | 66.46 |
| encode_O1 | 8.38 | 53.14 | 80.00 | 7.58 | 3.09 | 3.09 | 51.95 | 50.41 |
| encode_O3 | 8.38 | 45.11 | 71.67 | 7.58 | 3.09 | 3.09 | 43.94 | 42.42 |
| encode_Os | 8.34 | 48.07 | 74.64 | 7.58 | 3.09 | 3.09 | 47.92 | 45.38 |
| hybrid_O3 | 4.11 | 13.57 | 17.81 | 7.59 | 3.09 | 3.09 | 13.47 | 13.13 |
| hybrid_Os | 4.11 | 9.75 | 15.80 | 7.59 | 3.09 | 3.09 | 9.62 | 9.14 |
| relaxed_O3 | 8.26 | 50.26 | 79.23 | 7.56 | 3.07 | 3.07 | 48.96 | 47.32 |
| single_O0 | 32.04 | 33.04 | 42.70 | 48.01 | 29.51 | 29.51 | 32.61 | 32.06 |
| single_O1 | 7.03 | 7.37 | 10.69 | 12.52 | 6.52 | 6.52 | 7.27 | 7.03 |
| single_O2 | 10.03 | 10.34 | 13.36 | 15.02 | 7.02 | 7.02 | 10.26 | 10.03 |
| single_O3 | 10.03 | 10.31 | 13.02 | 14.52 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_Os | 8.02 | 8.34 | 11.36 | 13.02 | 6.52 | 6.52 | 8.25 | 8.03 |
| single_itcm_O2 | 10.02 | 10.30 | 13.02 | 14.51 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_itcm_O3 | 10.02 | 10.33 | 13.35 | 15.01 | 7.02 | 7.02 | 10.25 | 10.03 |
| span_O2 | 9.03 | 9.24 | 11.36 | 12.52 | 6.52 | 6.52 | 9.18 | 9.03 |
| span_O3 | 9.03 | 9.24 | 11.36 | 12.52 | 6.52 | 6.52 | 9.18 | 9.03 |
| span_Os | 5.02 | 5.43 | 9.35 | 11.52 | 6.02 | 6.02 | 5.33 | 5.03 |
| unit_O3 | 8.30 | 50.05 | 76.61 | 8.08 | 3.09 | 3.09 | 48.90 | 47.35 |

### O2, OCRAM

| Variant | constant | runs32 | runs3 | runs2 | alternating | random | pulses | last_change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_O2 | 8.30 | 50.05 | 76.61 | 8.08 | 3.09 | 3.09 | 48.90 | 47.35 |
| encode_O0 | 8.44 | 69.44 | 98.72 | 8.08 | 3.09 | 3.09 | 68.16 | 66.46 |
| encode_O1 | 8.38 | 53.14 | 80.00 | 7.58 | 3.09 | 3.09 | 51.95 | 50.41 |
| encode_O3 | 8.38 | 45.11 | 71.67 | 7.58 | 3.09 | 3.09 | 43.94 | 42.42 |
| encode_Os | 8.34 | 48.07 | 74.64 | 7.58 | 3.09 | 3.09 | 47.92 | 45.38 |
| hybrid_O3 | 4.11 | 13.57 | 17.80 | 7.59 | 3.09 | 3.09 | 13.47 | 13.13 |
| hybrid_Os | 4.11 | 9.76 | 15.80 | 7.59 | 3.09 | 3.09 | 9.60 | 9.14 |
| relaxed_O3 | 8.25 | 50.26 | 79.23 | 7.56 | 3.07 | 3.07 | 48.96 | 47.32 |
| single_O0 | 32.04 | 33.04 | 42.70 | 48.01 | 29.52 | 29.52 | 32.61 | 32.06 |
| single_O1 | 7.03 | 7.37 | 10.69 | 12.52 | 6.52 | 6.52 | 7.27 | 7.03 |
| single_O2 | 10.03 | 10.34 | 13.36 | 15.02 | 7.03 | 7.03 | 10.26 | 10.03 |
| single_O3 | 10.03 | 10.31 | 13.03 | 14.52 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_Os | 8.02 | 8.34 | 11.36 | 13.02 | 6.52 | 6.52 | 8.25 | 8.03 |
| single_itcm_O2 | 10.02 | 10.30 | 13.02 | 14.51 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_itcm_O3 | 10.02 | 10.33 | 13.35 | 15.01 | 7.02 | 7.02 | 10.25 | 10.03 |
| span_O2 | 9.03 | 9.24 | 11.36 | 12.52 | 6.52 | 6.52 | 9.18 | 9.03 |
| span_O3 | 9.03 | 9.24 | 11.36 | 12.52 | 6.52 | 6.52 | 9.18 | 9.03 |
| span_Os | 5.02 | 5.43 | 9.35 | 11.52 | 6.02 | 6.02 | 5.33 | 5.03 |
| unit_O3 | 8.30 | 50.05 | 76.61 | 8.08 | 3.09 | 3.09 | 48.90 | 47.35 |

### O2-lto, DTCM

| Variant | constant | runs32 | runs3 | runs2 | alternating | random | pulses | last_change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_O2 | 8.31 | 56.54 | 78.27 | 7.59 | 3.09 | 3.09 | 55.62 | 54.33 |
| encode_O0 | 8.44 | 78.95 | 103.70 | 7.59 | 3.09 | 3.09 | 77.88 | 76.44 |
| encode_O1 | 8.37 | 60.64 | 82.98 | 7.59 | 3.09 | 3.09 | 59.69 | 58.37 |
| encode_O3 | 8.37 | 54.61 | 76.64 | 7.59 | 3.09 | 3.09 | 53.67 | 52.37 |
| encode_Os | 8.34 | 54.56 | 76.29 | 7.59 | 3.09 | 3.09 | 53.66 | 52.35 |
| hybrid_O3 | 4.13 | 12.66 | 17.50 | 7.60 | 3.10 | 3.11 | 12.56 | 12.17 |
| hybrid_Os | 4.11 | 9.72 | 15.48 | 7.59 | 3.09 | 3.09 | 9.58 | 9.14 |
| relaxed_O3 | 8.23 | 49.52 | 71.55 | 7.56 | 3.06 | 3.06 | 48.58 | 47.28 |
| single_O0 | 32.04 | 33.04 | 42.70 | 48.01 | 29.51 | 29.51 | 32.60 | 32.06 |
| single_O1 | 7.02 | 7.37 | 10.69 | 12.52 | 6.52 | 6.52 | 7.28 | 7.03 |
| single_O2 | 10.03 | 10.31 | 13.02 | 14.52 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_O3 | 10.03 | 10.34 | 13.36 | 15.02 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_Os | 7.02 | 7.37 | 10.69 | 12.52 | 6.52 | 6.52 | 7.28 | 7.03 |
| single_itcm_O2 | 10.02 | 10.31 | 13.02 | 14.52 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_itcm_O3 | 10.02 | 10.34 | 13.36 | 15.02 | 7.02 | 7.02 | 10.25 | 10.03 |
| span_O2 | 9.03 | 9.31 | 12.02 | 13.52 | 6.02 | 6.02 | 9.24 | 9.03 |
| span_O3 | 8.03 | 8.31 | 11.02 | 12.52 | 6.02 | 6.02 | 8.24 | 8.03 |
| span_Os | 5.02 | 5.40 | 9.02 | 11.02 | 6.02 | 6.02 | 5.28 | 5.03 |
| unit_O3 | 8.30 | 49.42 | 69.94 | 7.58 | 3.09 | 3.09 | 48.56 | 47.33 |

### O2-lto, OCRAM

| Variant | constant | runs32 | runs3 | runs2 | alternating | random | pulses | last_change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_O2 | 8.31 | 56.54 | 78.27 | 7.59 | 3.09 | 3.09 | 55.62 | 54.33 |
| encode_O0 | 8.44 | 78.95 | 103.70 | 7.59 | 3.09 | 3.09 | 77.88 | 76.44 |
| encode_O1 | 8.37 | 60.64 | 82.97 | 7.59 | 3.09 | 3.09 | 59.69 | 58.37 |
| encode_O3 | 8.37 | 54.61 | 76.64 | 7.59 | 3.09 | 3.09 | 53.67 | 52.37 |
| encode_Os | 8.34 | 54.56 | 76.29 | 7.59 | 3.09 | 3.09 | 53.66 | 52.35 |
| hybrid_O3 | 4.13 | 12.66 | 17.50 | 7.60 | 3.11 | 3.10 | 12.56 | 12.17 |
| hybrid_Os | 4.11 | 9.73 | 15.48 | 7.59 | 3.09 | 3.09 | 9.58 | 9.14 |
| relaxed_O3 | 8.22 | 49.52 | 71.55 | 7.56 | 3.06 | 3.06 | 48.58 | 47.28 |
| single_O0 | 32.04 | 33.04 | 42.70 | 48.01 | 29.51 | 29.51 | 32.60 | 32.06 |
| single_O1 | 7.02 | 7.37 | 10.69 | 12.52 | 6.52 | 6.52 | 7.28 | 7.03 |
| single_O2 | 10.03 | 10.31 | 13.02 | 14.52 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_O3 | 10.03 | 10.34 | 13.36 | 15.02 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_Os | 7.02 | 7.37 | 10.69 | 12.52 | 6.52 | 6.52 | 7.28 | 7.03 |
| single_itcm_O2 | 10.03 | 10.31 | 13.02 | 14.52 | 7.02 | 7.02 | 10.25 | 10.03 |
| single_itcm_O3 | 10.03 | 10.34 | 13.36 | 15.02 | 7.02 | 7.02 | 10.25 | 10.03 |
| span_O2 | 9.03 | 9.31 | 12.02 | 13.52 | 6.02 | 6.02 | 9.24 | 9.03 |
| span_O3 | 8.03 | 8.31 | 11.02 | 12.52 | 6.02 | 6.02 | 8.24 | 8.03 |
| span_Os | 5.02 | 5.40 | 9.02 | 11.02 | 6.02 | 6.02 | 5.28 | 5.03 |
| unit_O3 | 8.30 | 49.42 | 69.94 | 7.58 | 3.09 | 3.09 | 48.56 | 47.33 |

`encode_O*` changes only the generic encode function; sizing/helpers retain O2. `unit_O3` applies O3 across the encoder translation unit. `relaxed_O3` also removes the tagged functions’ noinline/noipa restrictions. `single_O*` is the first counter-based one-pass loop. `span_O*` computes lengths from transition indices and handles the terminal record outside the loop. `hybrid_O*` retains production sizing/early RAW rejection, emits constant blocks directly from the verified sizing result, and otherwise calls the corresponding span kernel. `_itcm_` places the original single-pass candidate in ITCM; other kernels are in flash.

## Code footprint

| Variant | O2 linked variant bytes | O2+LTO linked variant bytes |
| --- | ---: | ---: |
| baseline_O2 | 1514 | 1544 |
| encode_O0 | 1974 | 1992 |
| encode_O1 | 1604 | 1628 |
| encode_O3 | 1562 | 1586 |
| encode_Os | 1550 | 1574 |
| hybrid_O3 | 842 | 1694 |
| hybrid_Os | 784 | 1638 |
| relaxed_O3 | 1648 | 1672 |
| single_O0 | 214 | 214 |
| single_O1 | 132 | 130 |
| single_O2 | 154 | 154 |
| single_O3 | 154 | 154 |
| single_Os | 100 | 94 |
| single_itcm_O2 | 154 | 154 |
| single_itcm_O3 | 154 | 154 |
| span_O2 | 160 | 156 |
| span_O3 | 160 | 156 |
| span_Os | 102 | 100 |
| unit_O3 | 1572 | 1588 |

Sizes sum the variant wrapper and linked namespace functions; hybrid totals also include their span helper. Shared protocol/library support and whole-image storage are excluded. These are not projected production ELF savings. Warm-cache ITCM comparisons do not measure cache-miss behavior during acquisition. Production has only 952 bytes before the next ITCM allocation boundary and 992 bytes above its RAM1 headroom floor; moving whole generic routines to ITCM requires a real production resource-gate build.

## Deferred encoding implications

At 1 MHz GPIO, a 2,024-sample block arrives every 2.024 ms. Convert a block’s cycle count to microseconds by dividing by 600; divide cycles/sample by 6 for the encoder-only percentage of a 600 MHz core at 1 MS/s. These exclude the other acquisition/transport work and do not establish available idle time. Current GPIO-service utilization is not total CPU utilization.

A deferred stage should service urgent acquisition/control work first, then encode with a bounded cycle or block budget. It must reserve input ownership until encoding finishes, enforce a backlog deadline/high-water policy, and flush/drain on STOP. Ten milliseconds of retained GPIO input needs about five 4,096-byte pool pages (20 KiB), plus active/output ownership. Reuse the existing pool; do not spend the qualified image’s 4 KiB RAM2 headroom. Idle-only scheduling without a deadline can starve under load. No scheduling or output-aggregation change was made in this experiment.

## Validation and retained evidence

Local gates: 87 host tests passed, including both single-pass loops over known and seeded patterns, unaligned buffers, guard regions, evidence rejection and frozen collector composition. Both final target builds pass the benchmark’s address/alignment/clock checks. These standalone builds have a different memory footprint from production and do not replace its resource gates. Three harness link/input setup failures are retained; none was flashed. No physical benchmark job failed. The first firmware-restoration attempt was rejected by a transient HTTP 503 health response before submission; a fresh healthy/idle check preceded the successful restore, and the failed preflight log is retained.

| Job | Remote ID | Variants | Sweeps | Timed invocations |
| --- | --- | ---: | ---: | ---: |
| O2-run1 | 1c648c2b-9bf9-4aa9-9d2c-65a5172da560 | 14 | 5 | 34,720 |
| O2-lto-run1 | 524730e1-5faa-4b83-85d2-c92a6534cd55 | 14 | 5 | 34,720 |
| O2-run2 | 6a91fbd1-fdb7-45c0-9dc1-b1ef72d73941 | 19 | 5 | 47,120 |
| O2-lto-run2 | 54e6fc09-4185-4c7e-8d3a-223714680bcd | 19 | 5 | 47,120 |

Restored qualified image `thingdaq-24c275c126c4e0d8` and verified a five-second combined capture, both ADCs and all sixteen GPIO inputs, including STOP/drain/IDLE, ADC request-route readback and retained phase history: 149 checks passed. Restore job `4f11eef8-c9fe-4da0-8bba-4dd4fe75d9a5`. No hardware change was needed.

Raw evidence, source snapshots, ELF/disassembly, transcripts and failed build logs: `doc/results/raw/rle-encoder-20261018`. [Machine-readable results](rle-encoder-optimization-20261018.json) include hashes and all measured rows; [experiment design](../../research/rle-encoder-optimization.md) describes the candidate contracts.
