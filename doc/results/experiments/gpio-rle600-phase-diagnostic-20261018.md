---
type: result
title: GPIO RLE Early Phase Diagnostic Results
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE early phase diagnostic results

**Bounded diagnostic PASS; full GPIO RLE qualification remains pending.**
Forty ten-second START/STOP cells without reflash and one ten-minute capture
passed all 5,986 checks. Peak sampled die temperature was 67.369 °C; parser
checksum/header/payload errors and discarded bytes were zero. Both jobs
completed STOP/drain/IDLE and idempotent STOP checks. The
[complete evidence record](gpio-rle600-phase-diagnostic-20261018.json)
preserves summaries, provenance and artifact hashes, reconciled exactly
against saved results. Frozen orchestration, runner and validator hashes match.

| Job | Remote ID | Cells | Checks | Peak °C |
| --- | --- | ---: | ---: | ---: |
| regression-40x10 | 3c17e66e-4313-460d-9a2f-e4ff1a691b5a | 40 | 5,840 | 64.299 |
| diagnostic-600 | 0355bde2-a2a4-49b0-a96f-767abce9507b | 1 | 146 | 67.369 |

Both used immutable `thingdaq-45d59c363f7aa067`, clean source `30e7bfc`, HEX
SHA-256 `bd8a89038d0f5387185b59d4b95499e6fc137cb5bf7f39bc9a4b2009824c768f`.
Raw evidence is retained in `doc/results/raw/gpio-rle600-phase-20261018`.
Postflight service health was healthy with an empty queue; subsequent read-only
Docker inspection found no active container, and the local runner had exited.

This campaign follows the
[failed ADC1-preemption candidate](gpio-rle600-preemption-failure-20261018.md).
That ineffective change was withdrawn. The current image adds eight early
phase checkpoints to the retained last-two observations and fault counters,
forming a 96-word failure record. No failure triggered that record in this
campaign. Instrumentation changes service timing and is not a demonstrated
correction; intermittent ADC DMA divergence remains unresolved. All ten
failed physical campaigns and both failed RAM1 builds remain preserved through
the preceding failure report's evidence chain. Acceptance limits are unchanged.
Inputs remain electrically unstimulated; no GPIO output or external-pattern
fidelity is claimed.

The next bounded diagnostic uses this same immutable image for three ten-minute
captures followed by forty ten-second restart cells. Each job reflashes/resets;
cells within the restart job do not. It stops on the first failure, retains
fresh evidence, and has no automatic finalizer or follow-on campaign. If the
failure recurs, decode the 96-word record to distinguish initial offset,
gradual drift and a later step. Another PASS is diagnostic evidence only;
full qualification and the final RLE comparison report remain pending.
