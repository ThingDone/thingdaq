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
The [subsequent DMA investigation](../research/gpio-rle-dma-investigation.md)
isolates progressive ADC1 sample loss to the original ADC2 COCO DMA request.
Two same-image comparisons passed 7/7 ACK-cleared ADC_ETC captures and reproduced
two original-route failures. Fix `441d5bc` selects ADC_ETC trigger 4 (DMAMUX 23)
for ADC1 in default private RLE builds; ADC2_R0, descriptors, rates, priorities
and codec remain unchanged. Private INFO advertises the selected source.
The trigger adapter preserves ACK-cleared mode through final-conversion drain;
ADC teardown disables the source and clears mode. Public non-RLE builds retain
the original route. The [corrected-image qualification](../results/experiments/gpio-rle600-etc-fixed-20261018.md)
passed 64 cells / 9,536 checks, including sixty START/STOP cycles and three
ten-minute captures. Peak was 64.913 °C, with zero parser errors/discards or
rejections and all 640 phase observations within ±1 sample. On unstimulated
GPIO, sustained wire savings were 98.7305% (32.9101% combined data); GPIO-service
CPU median was 17.31% versus 15.72% for larger ADC/RAW GPIO, not total CPU.
The report preserves the failed controls and per-cell results. No hardware
change was required.

The [earlier planned physical qualification](../results/experiments/gpio-rle600-phase-qualification-20261018.md)
passed 44 cells and 6,424 checks with a 67.983 °C peak, but did not establish
a correction. It remains historical evidence. Current RLE target resource gates
retain 33,760 bytes RAM1 stack/local and 4,096 bytes RAM2 heap headroom.
No GPIO outputs or public SDK promotion are included.

Subsequent [isolated encoder experiments](../results/experiments/rle-encoder-optimization-20261018.md)
compare nineteen variants with and without LTO. A hybrid specialized Os
candidate improves constant and mixed-run costs while retaining fast RAW
rejection. These are standalone measurements; the acquisition encoder and
synchronous scheduling described here remain unchanged.

The following preserves the implementation and diagnostic history; pending/next
statements describe their respective historical checkpoints. The [first smoke failure](../results/experiments/gpio-rle600-start-boundary-failure-20261018.md)
identified a host START buffering assumption and remains classified FAIL.
After that host fix, smoke and three ten-minute captures passed, but the
[restart job failed with ADC DMA pipeline counters](../results/experiments/gpio-rle600-dma-failure-20261018.md).
A deterministic test reproduces an already-accounted interrupt race in the
ADC service; a firmware fix now accepts aligned index zero without weakening
hardware-error, skew, window or ring checks. The historical fault's exact
ordering remains unproven. The [next campaign reproduced the ADC fault](../results/experiments/gpio-rle600-dma-recurrence-20261018.md)
in its fourth restart cell after seven passing cells. A private 12-byte STATUS
suffix now preserves first-fault DMA error status and alignment state through
cleanup; ordinary STATUS framing is unchanged. The [instrumented reproduction](../results/experiments/gpio-rle600-alignment-failure-20261018.md)
identified an equal-active-index wait timeout even though both converters had
a completed common buffer. The handler now consumes only that common prefix
within the existing safe window and at most one generation of skew. Fresh
reproduction and full qualification remain required.
The next attempt [failed boot completion timing before acquisition](../results/experiments/gpio-rle600-boot-timing-failure-20261018.md).
Timer enable through first-DONE observation now executes in ITCM, avoiding
a flash-code interval before timestamp polling; timing tolerances remain
unchanged. That candidate passed eight restart cells and smoke, then
[failed the pipeline window guard](../results/experiments/gpio-rle600-window-failure-20261018.md)
with observed indices 3/1 and DMA_ES zero. The cause remains unresolved.
Failure-only TCD/descriptor detail is now retained and retrieved after STOP
through explicit private STATUS pages; acceptance limits remain unchanged.
Fresh diagnostic reproduction and qualification are required.

The [descriptor repeat failed](../results/experiments/gpio-rle600-descriptor-failure-20261018.md)
in its third restart cell. Hardware destination/link pairs confirm indices
3/1; CPU-visible RAM descriptors match expectations. The cause remains
unresolved. RLE-only diagnostics now retain the last two accepted progress
observations before completion accounting, frozen at first fault and cleared
on prepare. The [history failure](../results/experiments/gpio-rle600-history-failure-20261018.md)
showed indices 2/1 twice before 3/1, but lacked the sample counters and final
timestamp needed to distinguish service latency from DMA progress discrepancy.
Each observation now stores base generation, indices, end DWT, pending IRQs,
packed CITER values (ADC0 low 16 bits), and start DWT. Detail words 36–47
contain the two six-word records; words 28–35 hold fault-entry DWT, DMA_HRS,
ADC0 NBYTES/BITER, ADC1 NBYTES/BITER, and ADC1/ADC2 GS. Sequential reads are
not atomic; the observation timestamps bound their read interval. NBYTES is
a live hardware value, not a saved initial transfer size. Retrieval now uses
48 private pages without enlarging any response (including the sparse phase
checkpoints below).
This adds bounded service-path work and is diagnostic instrumentation, not
a demonstrated fix. Acceptance limits and ordinary builds are unchanged.

The [counter diagnostic failure](../results/experiments/gpio-rle600-counter-failure-20261018.md)
shows apparent sample-progress divergence despite sub-microsecond register
read spans. A controlled ADC1 channel ECP change also
[failed with the same discrepancy](../results/experiments/gpio-rle600-preemption-failure-20261018.md)
and was removed. All channel preemption settings retain their prior values.
The next diagnostic records the first observation at or after base generations
0, 1, 2, 4, 16, 256, 1024 and 2048 in detail words 48–95. Each uses the same
six-word format as the last-two history. Unreached records remain zero;
reached records are immutable until prepare. These bounded checkpoints narrow
whether the discrepancy begins at startup, grows gradually or appears later.
Cause and correction remain unresolved; no acceptance gate is relaxed.

The [sustained phase diagnostic](../results/experiments/gpio-rle600-phase-sustained-20261018.md)
passed three ten-minute captures and forty restart cells (6,278 checks,
67.983 °C peak, zero parser errors/discards). The fault record was not triggered;
instrumentation is still not a demonstrated correction. Full qualification on
the same image follows in fresh evidence, including smoke, sustained repeats
and forty restart cells. Historical failures remain part of the final assessment.

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


The [deferred codec candidate](../research/deferred-codecs.md) adds an opt-in
cooperative worker with default-on GPIO RLE, optional ADC12 packing, and explicit
deadline drops. Its pressure qualification also fixes the compressed-frame
validator to accept a checked buffer index instead of deriving one from a
possibly copied record. See that candidate's evidence before treating it as
qualified; historical captures above used their recorded immutable images.
