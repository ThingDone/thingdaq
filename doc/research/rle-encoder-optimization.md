---
type: research
title: Isolated GPIO RLE Encoder Optimization
created: 2026-10-18
tags: [firmware, compression, performance]
related: []
---

# Isolated GPIO RLE encoder optimization

Bill requested on-board encoder experiments, including function-only `-O3`
and multiple optimization levels. This experiment does not change the qualified
acquisition firmware or implement accumulated output framing.

`firmware/tools/rle_performance.py` builds a separate 600 MHz sketch from the
actual production encoder plus an experimental fixed-shape single-pass encoder.
Fourteen variants cover the O2 baseline; encode-function-only O0/O1/O3/Os;
the whole encoder at O3; O3 with interprocedural restrictions removed;
single-pass O0/O1/O2/O3/Os in flash; and single-pass O2/O3 in ITCM. Two images
compare the default O2 toolchain with O2 plus LTO. Generated sources, compiler,
ELF, disassembly, symbol sizes and placements are retained in the manifest/build.

Each image runs five rotated-order sweeps over eight patterns and DTCM/OCRAM
input/output pairs. Every case has 31 timed invocations after warming caches.
The timed scope includes selection and encoding into scratch; it excludes
pattern generation, correctness checks, checksumming, frame copy and USB output.
Interrupts stay enabled; acquisition DMA is not running. The 80 degrees C
cutoff remains active outside timed regions. Per-case min/median/max DWT cycles
include call and timing overhead. These are isolated costs, not total CPU or
acquisition deadline guarantees.

Input contains 2,024 16-bit items. Patterns cover constant input, runs of
32/3/2 samples, alternating values, seeded random data, sparse pulses and a
change at the final sample. The output limit is 4,044 bytes: with the 48-byte
frame envelope this is strictly smaller than the 4,096-byte RAW frame. A zero
length means RAW fallback; an incomplete scratch prefix is discarded and the
input remains intact. The candidate requires valid, disjoint caller-owned
buffers; it is not a replacement for the generic codec API's validation.

Every timed output is compared byte-for-byte with a separately implemented
board oracle; input hashes and output canaries are checked outside timing.
The host independently reconstructs canonical output and verifies the digest,
RAW decision, complete case matrix, clock, cycle ordering and completion marker.
The existing M7 serial collector and upload/provenance client are reused.
Local validation passed 54 tests, including 240 seeded run distributions,
unaligned buffers, output guards and malformed/incomplete evidence rejection.

Physical measurements are pending. Two initial harness build failures (Arduino
not copying an `.inc` file, then missing the production `storeU16` dependency)
are retained under `doc/results/raw/rle-encoder-20261018`; no image from either
failed build was flashed. The corrected standalone target build passes.

## Deferred encoding

The current runtime services acquisition, then USB, then acquisition and USB
again. Compression runs synchronously during GPIO frame completion; there is
no measured CPU-idle signal. A future deferred stage can run after urgent
acquisition/control/USB work, with a cycle budget and bounded pending queue.
At 1 MHz, a 2,024-sample GPIO block arrives every 2.024 ms and retains 4,048
raw bytes. Deferring for 10 ms requires roughly five block slots (20,480 bytes
at 4,096 bytes per pool page), plus ownership for active/output work. Those
pages must come from the existing pool; the qualified image has only 4,096
bytes of free RAM2, already its required headroom floor. Average encoder
throughput must exceed arrival rate, and backlog deadlines must prevent
indefinite starvation. Measurements will inform the cycle budget; integrated
stress testing is still needed before changing scheduling.
