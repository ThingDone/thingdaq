---
type: result
title: GPIO RLE ADC Pipeline Window Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE ADC pipeline window failure

**FAIL — eight restart cells and smoke passed, then sustained-01 failed.**
The nine passing cells completed 1,314 checks, with a maximum sampled die
temperature of 57.544 °C. The first ten-minute job stopped after about four
seconds of acquisition. No subsequent jobs were submitted. All three saved
summaries, provenance and artifact hashes reconcile exactly; frozen scripts
were checked before diagnostic changes. The
[complete evidence record](gpio-rle600-window-failure-20261018.json) retains
all three jobs. Parser errors/discards/rejection windows were zero, and cleanup
STOP observed IDLE. Read-only inspection confirmed no active rig container.

Failed job `c6af19e2-1f9d-4786-80c4-6438affe5e13` used clean source `1f36a4a`,
image `thingdaq-0404021e755aa291`, HEX SHA-256
`c83818c0d4876758ecfdf6aac5f7f6c1a01330080fd07b85ed09111206313afa`.
Raw files remain under `doc/results/raw/gpio-rle600-bootfix-20261018`.

The first-fault record reports alignment timeout (reason 1), ADC0 pipeline
index 3, ADC1 index 1, 11 polls, 6,543 CPU cycles (10.905 µs), and DMA_ES zero.
Index 3 exhausts the required spare descriptor in the active four-entry
pipeline, and the two-generation difference exceeds the skew allowance.
The earlier common-prefix correction therefore does not make this safe to
consume. The cause of the divergent observed indices is unresolved; neither
skew nor headroom limits have been relaxed. Existing trace data lacks the
raw TCD addresses and descriptor contents needed to distinguish hardware
progress from incorrect software inference.

Diagnostic instrumentation now captures both hardware TCD destination/link,
remaining iterations and control; the software base generation and destination
mapping; DMA interrupt/error flags; and each active RAM descriptor destination
and link. Reads occur only after a first fault, before automatic cleanup,
with reason published last. They are sequential bus reads while DMA runs,
not an atomic snapshot; RAM descriptor reads show the CPU's view, not proof
of DMA-visible memory. Normal acquisition processing is unchanged.

The private RLE STATUS suffix remains 12 bytes within the unchanged 1,536-byte
control frame. Normal requests return the original summary. Explicit request
IDs `0xFADC0001` through `0xFADC0012` return eighteen two-word detail pages.
The validator fetches these only after failed capture cleanup, retaining the
original FAIL even if detail retrieval fails. The record survives STOP and
resets at prepare. Ordinary builds have no detail storage or private suffix.

The [preceding boot-timing failure](gpio-rle600-boot-timing-failure-20261018.md)
links all five earlier failed physical campaigns and both failed RAM1 builds.
All remain failures. This sixth failure does not invalidate the separately
qualified endurance, STOP/restart or larger-ADC images. GPIO RLE qualification
remains pending; no GPIO outputs are driven.

Validation passed 70 tests plus 95 subtests, including private-page wire
roundtrips, unpublished/reset records, invalid page requests and ordinary-host
rejection. Documentation/repository checks passed eight tests plus 906
subtests; Python lint/format passed. The diagnostic target build passed the
unchanged resource gates: 34,272 bytes RAM1 local/stack headroom and 4,096
bytes RAM2 heap headroom. These checks do not qualify the physical RLE stage.
