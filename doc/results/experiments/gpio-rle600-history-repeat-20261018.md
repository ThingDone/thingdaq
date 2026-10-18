---
type: result
title: GPIO RLE Progress History Repeat Results
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE progress history repeat results

**Bounded diagnostic PASS; full GPIO RLE qualification remains pending.**
Forty ten-second START/STOP cells without reflash and one ten-minute capture
passed all 5,986 checks. Peak sampled die temperature was 67.983 °C; parser
checksum/header/payload errors and discarded bytes were zero. Both jobs
completed STOP/drain/IDLE and idempotent STOP checks. The
[complete evidence record](gpio-rle600-history-repeat-20261018.json)
preserves summaries, provenance and artifact hashes, reconciled exactly
against saved results. Frozen orchestration, runner and validator hashes match.

| Job | Remote ID | Cells | Checks | Peak °C |
| --- | --- | ---: | ---: | ---: |
| regression-40x10 | 022461a8-8d7f-42d8-be44-46afe18c782e | 40 | 5,840 | 65.527 |
| diagnostic-600 | d4010b97-bedc-48de-8f90-6776d109c9fb | 1 | 146 | 67.983 |

Both used immutable `thingdaq-09ca2870316328a3`, clean source `811cba3`, HEX
SHA-256 `beb28a7347d1b8cb518971319aff957d02a2f430813b1ed5e085136913bdce13`.
Raw evidence is retained in `doc/results/raw/gpio-rle600-history-repeat-20261018`.
Postflight service health was healthy with an empty queue; subsequent read-only
Docker inspection found no active container, and the local runner had exited.

Like the [preceding diagnostic](gpio-rle600-history-diagnostic-20261018.md),
this campaign did not reproduce the
[descriptor divergence](gpio-rle600-descriptor-failure-20261018.md).
The added progress-history instrumentation changes service timing and is not
a demonstrated correction. Both diagnostic campaigns together cover eighty
restart cells and two ten-minute captures, but cannot establish the historical
cause or close the failure. All seven failed physical campaigns and two failed
builds remain preserved through the preceding failure report's evidence chain.
No acceptance limits changed. Inputs remain electrically unstimulated;
no GPIO output or external-pattern fidelity is claimed.

The next bounded diagnostic expands sustained coverage to three ten-minute
jobs followed by forty ten-second restart cells, with no intentional cooldown.
Each job reflashes/resets; restart cells within the final job do not. This tests
longer sustained operation before restart stress on the same immutable image,
without speculative firmware changes. It stops on the first failure, retains
fresh evidence, and has no automatic finalizer or follow-on campaign. Decode
the 44-word failure history if triggered. Another PASS is diagnostic evidence
only; full qualification and the final RLE comparison report remain pending.
