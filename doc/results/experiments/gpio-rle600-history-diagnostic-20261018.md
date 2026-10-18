---
type: result
title: GPIO RLE Progress History Diagnostic Results
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE progress history diagnostic results

**Bounded diagnostic PASS; full GPIO RLE qualification remains pending.**
Forty ten-second START/STOP cells without reflash and one ten-minute capture
passed all 5,986 checks. Peak sampled die temperature was 67.983 °C; parser
checksum/header/payload errors and discarded bytes were zero. Both jobs
completed STOP/drain/IDLE and idempotent STOP checks. The
[complete evidence record](gpio-rle600-history-diagnostic-20261018.json)
preserves summaries, provenance and artifact hashes, reconciled exactly
against saved results. Frozen orchestration, runner and validator hashes match.

| Job | Remote ID | Cells | Checks | Peak °C |
| --- | --- | ---: | ---: | ---: |
| regression-40x10 | d37b8663-691e-45c7-af26-bc4a3d1b09e2 | 40 | 5,840 | 64.913 |
| diagnostic-600 | cdae0b80-ed90-47f7-9e87-9202294d56b6 | 1 | 146 | 67.983 |

Both used immutable `thingdaq-09ca2870316328a3`, clean source `811cba3`, HEX
SHA-256 `beb28a7347d1b8cb518971319aff957d02a2f430813b1ed5e085136913bdce13`.
Raw evidence is retained in `doc/results/raw/gpio-rle600-history-20261018`.
Postflight service health was healthy with an empty queue; subsequent read-only
Docker inspection found no active container.

The [preceding descriptor divergence](gpio-rle600-descriptor-failure-20261018.md)
remains unresolved. This image adds the last two accepted DMA observations to
failure detail; that instrumentation is not a demonstrated correction. This
campaign did not reproduce the failure and supplied no failure-only history.
All seven earlier failed physical campaigns and two failed builds remain
preserved through the preceding report's evidence chain. Acceptance limits
are unchanged. Inputs remain electrically unstimulated; no GPIO outputs are
driven and no external-pattern fidelity is claimed.

The next bounded repeat uses the same image for forty ten-second START/STOP
cells, followed by one ten-minute capture, stopping on the first failure.
Fresh evidence storage preserves this completed campaign. Any failure must
be reconciled and its 44-word history decoded before a correction. A further
PASS does not establish the historical cause or complete full qualification.
The final RLE comparison report remains pending.
