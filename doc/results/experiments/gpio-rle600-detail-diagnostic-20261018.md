---
type: result
title: GPIO RLE Descriptor Diagnostic Results
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE descriptor diagnostic results

**Bounded diagnostic PASS; full GPIO RLE qualification remains pending.**
Eight ten-second START/STOP cells without reflash and one ten-minute capture
passed all 1,314 checks. Peak sampled die temperature was 64.299 °C; parser
checksum/header/payload errors and discarded bytes were zero. Both jobs
completed the STOP/drain/IDLE and idempotent STOP checks. The
[complete evidence record](gpio-rle600-detail-diagnostic-20261018.json)
preserves summaries, provenance and artifact hashes, reconciled exactly
against saved results. Frozen orchestration, runner and validator hashes match.

| Job | Remote ID | Cells | Checks | Peak °C |
| --- | --- | ---: | ---: | ---: |
| regression-8x10 | 177e8189-da1c-45c5-ab0f-468953229d2f | 8 | 1,168 | 52.632 |
| diagnostic-600 | edbedc02-734c-4520-a404-7e59b7080358 | 1 | 146 | 64.299 |

Both used immutable `thingdaq-0f462a06fef8cf6f`, clean source `2edfa63`, HEX
SHA-256 `24dd53a2a2e2f3c54daa5ef130ecccf0061b9d55636aafc2c352a6ba2ac64549`.
Raw evidence is retained in `doc/results/raw/gpio-rle600-detail-20261018`.
Postflight service health was healthy with an empty queue; subsequent read-only
Docker inspection found no active container.

The [preceding pipeline-window failure](gpio-rle600-window-failure-20261018.md)
remains unresolved. This run did not reproduce it and therefore supplies no
failure-only descriptor snapshot. It neither proves a fix nor replaces the
full qualification gate. All six earlier failed physical campaigns and two
failed builds remain preserved through that report's evidence chain.
Acceptance limits are unchanged. Inputs remain electrically unstimulated;
no GPIO outputs are driven and no external-pattern fidelity is claimed.

The next bounded diagnostic uses this exact image for forty ten-second
START/STOP cells without reflash, then one ten-minute capture, stopping on
the first failure. A fresh evidence directory prevents overwriting this run.
Failure detail must be reconciled and decoded before any correction; a further
PASS still leaves the historical cause unresolved. Final RLE qualification
and its comparison report remain pending.
