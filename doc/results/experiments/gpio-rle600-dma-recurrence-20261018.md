---
type: result
title: GPIO RLE ADC DMA Fault Recurrence
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE ADC DMA fault recurrence

**FAIL — GPIO RLE qualification remains pending.** The already-accounted
wakeup fix did not eliminate the physical fault. Smoke, three ten-minute
captures and the first three restart cells passed: seven cells, 1,022 checks,
and a 66.755 °C maximum sampled temperature. The fourth restart cell failed.
All five job summaries, provenance and artifact hashes were reconciled with
saved results and the frozen orchestration/runner/validator hashes verified
before changing code. See the [complete campaign record](gpio-rle600-dma-recurrence-20261018.json).

| Job | Outcome | Passing checks | Peak °C |
| --- | --- | ---: | ---: |
| smoke-60 | PASS | 146 | 53.246 |
| sustained-01 | PASS | 146 | 65.527 |
| sustained-02 | PASS | 146 | 66.141 |
| sustained-03 | PASS | 146 | 66.755 |
| restart-4x10 | Three cells PASS, fourth FAIL | 438 | 63.685 |

The failed cell completed 106 checks before reporting unexpected IDLE during
capture. Its failure snapshot has two ADC DMA error events, one completion
mismatch and three incomplete conversions; 2,017 ADC frames and 1,009 GPIO
frames were received. Partial STOP tails were 30 ADC pairs and 1,039 GPIO
samples. Parser checksum/header/payload errors and discarded bytes were zero;
no rejection windows were recorded. Cleanup STOP observed IDLE. These are
failure snapshots, not passing final conservation. The runner exited without
further submissions; read-only SSH inspection found no running rig containers.

Failed remote job: `57f622c7-e431-483b-a2b1-bf85e2d72270`. Immutable image:
`thingdaq-bb2d641b13d18633`, source commit `5ae2ee4`, HEX SHA-256
`a1570f8e0ddaf62301f6852cbdd837d58cb2d61e28cbd6786d00e6662d54e5ba`.
Raw evidence remains under `doc/results/raw/gpio-rle600-dmafix-20261018`.
The [earlier DMA failure](gpio-rle600-dma-failure-20261018.md),
[host START failure and two build failures](gpio-rle600-start-boundary-failure-20261018.md)
remain failed evidence.

The DMA error count includes software alignment faults and does not identify
the underlying cause. The next diagnostic image adds a private 12-byte
GPIO-RLE STATUS suffix retaining the first fault reason, last alignment
indices, elapsed cycles, polls and DMA error-status register before cleanup. It survives STOP until the next prepare. The ISR publishes reason
last, and readers suppress an unpublished record. Ordinary builds retain their
public STATUS layout; the independent validator requires the suffix only for
the selected private RLE image and rejects a nonzero fault reason. Acceptance
checks and command deadlines remain unchanged. Fresh short reproduction must
precede another full qualification; this record makes no root-cause claim.

Local validation passed 63 tests plus 946 subtests, including production DMA
service ordering, cross-language STATUS diagnostics, RLE and ordinary framing,
input isolation, and documentation/repository checks. Python lint/format passed.
The diagnostic target build passed unchanged resource gates: 34,400 bytes RAM1
local/stack headroom and 4,096 bytes RAM2 heap headroom.
