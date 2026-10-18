---
type: architecture
title: Opt-in 600 MHz GPIO RLE Experiment
created: 2026-10-18
tags: [firmware, compression, protocol]
related: []
---

# GPIO-only RLE experiment

This implements the final authorized stage of the
[600 MHz qualification plan](../research/600mhz-stability-plan.md), after the
[larger ADC qualification](../results/experiments/large-adc600-20261018.md).
Hardware qualification is pending; the [first smoke failure](../results/experiments/gpio-rle600-start-boundary-failure-20261018.md)
identified a host START buffering assumption and remains classified FAIL.
After that host fix, smoke and three ten-minute captures passed, but the
[restart job failed with ADC DMA pipeline counters](../results/experiments/gpio-rle600-dma-failure-20261018.md).
A deterministic test reproduces an already-accounted interrupt race in the
ADC service; a firmware fix now accepts aligned index zero without weakening
hardware-error, skew, window or ring checks. The historical fault's exact
ordering remains unproven, and the new image requires fresh qualification.
ADC remains uncompressed at 1,012 pairs
per frame; GPIO remains sixteen inputs at 1 MHz. No GPIO outputs are driven.

The experiment builder requires `--cpu-mhz 600 --release-fixed-1mhz
--large-adc-frame --gpio-rle`. The GPIO-RLE selection salts the build identity
and appears in the manifest. The runner independently requires `--gpio-rle`
plus `--frame-experiment`; the public SDK path cannot opt in. Normal builds
retain their fixed framing and counters. This is a private experiment, not a
public protocol revision.

Compressed GPIO frames use header version `0x82`, kind GPIO, and the existing
44-byte header and four-byte Adler-32 trailer. ADC, control and RAW fallback
frames retain version 2. Reserved fields stay zero. Each compressed record is
a little-endian `u16` positive run length followed by one `u16` GPIO value.
Runs are maximal and sum to exactly 2,024 samples. The header retains logical
item count and timestamps; payload and total length describe transmitted
bytes. The complete selected frame must be smaller than the 4,096-byte RAW
frame: 52 through 4,092 bytes. Checksums cover the transmitted header/payload.
The independent validator checks every record before bounded expansion,
rejects zero, overflowing, short, noncanonical and malformed runs, and then
applies the same logical shape, sequence, tick and conservation checks.
Ordinary validators reject the private version.

The portable sizing/encoding core is adapted from `experiment/rle-streaming`;
its old frame contract and ADC compression integration are not imported.
Sizing is read-only and encoding uses disjoint caller-owned storage. During
`finishFill`, the source remains exclusively FILLING. A FREE packet page is
borrowed without invoking eviction; after a complete checksummed result is
copied back, that scratch page is recycled before READY publication. If the
encoded frame is not smaller or no FREE page exists, the intact RAW frame is
published. Encoder failures retain RAW but increment the existing rejection
counter, so qualification cannot silently pass them. No extra full-size page
or persistent scratch allocation is introduced. READY, promotion, transport,
late gap repair, eviction and release validate/use the selected length.
Partial USB frames retain the existing immutable ownership and pinning rules.

Logical payload counters still measure uncompressed samples. Experimental
wire counters accumulate each selected frame at framing, emission,
transmission and pressure eviction. STATUS wire stages must satisfy bounded
queued-byte differences, becoming exact at drain. The host independently sums
all selected lengths and reconciles them against final firmware counters.
Reports include RAW/RLE counts, actual GPIO bytes and RAW-equivalent bytes;
a RAW frame alone does not identify whether incompressibility or scratch
pressure caused fallback.

Local tests cover item widths 1/2/4, static/bursty/alternating/pseudorandom data,
exact cross-language decode, short writes, malformed/corrupt frames, no-scratch
fallback, late gap repair, disconnect cleanup, ADC and 8-bit GPIO RAW behavior,
and mismatched selected lengths. The final combined regression/documentation gate passed 81 tests and
897 subtests (three unsupported build-selection combinations skipped).
Protocol generation and Python lint/format checks also passed.

Two target builds failed the unchanged 32,768-byte RAM1 local/stack gate:
32,920 and 32,776 bytes of instruction code crossed a 32 KiB bank boundary,
leaving only 1,632 bytes for locals. Their HEX/ELF/map, source patch and logs
remain under `doc/results/raw/gpio-rle600-20261018/build-failure-01` and
`build-failure-02`, with failure classifications and hashes. Neither was flashed.
Placing the data-view helper and experimental finalizer in flash restored
34,400 bytes of local/stack headroom; all target build/resource gates passed.
The 819,200-byte packet pool and 4,096 bytes of RAM2 heap headroom are unchanged.

Physical gates are a 60-second combined smoke, three consecutive 600-second
combined captures, and repeated START/STOP without reflash. Each checks both
ADCs, all GPIO, checksums, no loss, wire conservation, temperatures below 80 °C,
STOP/drain/final IDLE and idempotent STOP. Inputs are electrically unstimulated:
local known-data tests establish codec fidelity; hardware captures establish
transport and compression on the observed inputs, not external-waveform fidelity.
GPIO processing CPU includes synchronous RLE finalization within the GPIO
packer service, but is not total CPU usage. Queue maxima and thermal readings
must be compared with their differing capture durations and initial conditions.
