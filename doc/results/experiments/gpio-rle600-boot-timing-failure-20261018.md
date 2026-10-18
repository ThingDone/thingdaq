---
type: result
title: GPIO RLE Boot Completion Timing Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE boot completion timing failure

**FAIL — CONFIGURE was rejected before acquisition.** The first cell completed
76 checks; there were no passing captures. The firmware's boot diagnostic
recorded both ADC first completions at the same timestamp: zero-cycle spacing,
versus the unchanged 300 ± 120-cycle requirement at 600 MHz. Trigger error
flag 8,192 (`CompletionTimingOutOfTolerance`) therefore prevented readiness;
CONFIGURE returned BUSY (10). Parser errors/discards/rejections, DMA errors and
the private first-fault record were all zero. Cleanup STOP observed IDLE.
Sampled temperature was 40.351 °C. This failure does not test the new common
DMA completion handling under acquisition.

Job `0a692454-1f15-479f-8d89-e568639b1cd3` ran image
`thingdaq-f50173f756842811`, clean source commit `4651a0d`, HEX SHA-256
`f2f37629c358e938ba89f3b62422ffebd8cdd55848ac715f1eac3d1f827338e2`.
The service's first upload failed in HalfKay; the second succeeded. Both
attempts remain in the stdout record. The
[complete campaign record](gpio-rle600-boot-timing-failure-20261018.json)
reconciles summary, provenance and artifact hashes with the saved results.
Raw evidence remains under `doc/results/raw/gpio-rle600-progressfix-20261018`;
the stopped runner submitted no more work. The
[previous diagnostic failure](gpio-rle600-alignment-failure-20261018.md) links
all earlier failed physical campaigns and both failed target builds.

The DONE polling routine already resides in instruction tightly coupled
memory (ITCM), but its caller enabled the timers and performed readback in
flash before entering that routine. A cold instruction fetch in this interval
can delay the first observation until both completion bits are set. That is
a plausible observation artifact for the zero-spacing result; the saved
record cannot prove flash latency or exclude a physical timing issue.

Timer enable, armed readback and entry into DONE polling now share one ITCM
helper, entered before the timers run. Interrupt masking, register setup,
phase tolerance, diagnostic deadlines and readiness rejection remain intact.
Target-register tests retain first-transition timestamps and masked-caller
behavior; a placement regression requires timer enable and polling entry in
the same hot helper. Target ELF placement is checked separately. Fresh boot,
restart regression and full physical qualification are still required.

Validation passed 73 tests plus 106 subtests, documentation/repository eight
tests plus 901 subtests, and Python lint/format. The target build passed with
34,400 bytes of RAM1 local/stack headroom and 4,096 bytes RAM2 heap headroom.
ELF symbols place the new helper at `0x1288` and DONE polling at `0x11ec`, both
in `.text.itcm`; disassembly shows only ITCM instructions/literals and a direct
ITCM call between timer enable and observation. That proves code placement,
not the historical cause of the failed physical measurement.
