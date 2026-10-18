---
type: result
title: GPIO RLE Renewed DMA Diagnostic Baseline
created: 2026-10-18
tags: [firmware, reliability, dma]
related: []
---

# GPIO RLE renewed DMA diagnostic baseline

**For Bill:** all 61 captures passed, with 8,906 checks and a peak of
66.141 degrees C. This unchanged-image repeat did not reproduce the DMA
fault and does not establish a fix. The investigation continues; no hardware
change is currently required.

| Job | Captures | Checks | Peak degrees C | Result |
| --- | ---: | ---: | ---: | --- |
| Sixty five-second START/STOP cycles, without reflash | 60 | 8,760 | 62.457 | PASS |
| Sustained ten-minute capture | 1 | 146 | 66.141 | PASS |

The image was `thingdaq-45d59c363f7aa067`, clean firmware source `30e7bfc`,
HEX SHA-256 `bd8a89038d0f5387185b59d4b95499e6fc137cb5bf7f39bc9a4b2009824c768f`.
It retains both 12-bit ADCs at 1 MS/s, all sixteen GPIO inputs at 1 MHz,
larger raw ADC frames and private GPIO-only RLE at 600 MHz. All cells
completed STOP, drain, final IDLE and idempotent STOP checks. Parser header,
checksum and payload errors, discarded bytes and rejected frames were zero.
Inputs were electrically unstimulated; this is not analog waveform or GPIO
transition fidelity qualification.

Jobs `f4f75b34-6e05-4be5-aab3-ef9e441d3ee3` and
`2c84f962-c7fe-4a55-8bcc-ee8c5a04d849` completed. Saved results, summaries,
provenance and artifact hashes reconciled, and the frozen runner/validator
hashes matched before subsequent host changes. Postflight service health was
healthy with an empty queue. The [evidence record](gpio-rle600-renewed-diagnosis-20261018.json)
retains the campaign and all per-cell measurements. Raw artifacts, the final
verification log and frozen host sources remain in
`doc/results/raw/gpio-rle600-renewed-diagnosis-20261018`.

The [active investigation](../../research/gpio-rle-dma-investigation.md)
documents the repeated generation-4,042 failures, ADC request-clear mechanism,
machine-code inspection and controlled GPIO preemption probe. No historical
failure is reclassified by this PASS.
