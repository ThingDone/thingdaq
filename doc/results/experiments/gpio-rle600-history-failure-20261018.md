---
type: result
title: GPIO RLE Progress History Divergence Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE progress history divergence failure

**FAIL — the first sustained capture failed after approximately four seconds.**
The runner stopped before submitting either remaining sustained capture or
the restart job. No complete capture cell passed. Peak sampled temperature
was 45.264 °C; parser checksum/header/payload errors and discarded bytes were
zero. Cleanup STOP observed IDLE. The first programming attempt failed in
HalfKay; the service's second attempt succeeded before acquisition. Both
events remain in the raw evidence, without reclassifying the acquisition FAIL.

Remote job `1c094a34-c4a3-4e93-b81f-c6b7ba1d50f7` used clean source `811cba3`,
image `thingdaq-09ca2870316328a3`, HEX SHA-256
`beb28a7347d1b8cb518971319aff957d02a2f430813b1ed5e085136913bdce13`.
The [complete evidence record](gpio-rle600-history-failure-20261018.json)
preserves summary, provenance and artifact hashes. These reconciled exactly
with saved results, and frozen scripts matched before the next diagnostic
edit. Raw evidence and decoded history remain in
`doc/results/raw/gpio-rle600-history-sustained-20261018`.
The runner exited and postflight service health was healthy with an empty queue.

The first fault is alignment timeout: indices 3/1, eleven polls, 6,581 cycles
(10.968 µs at 600 MHz), DMA_ES and DMA_ERR zero. The pipeline base was
generation 4,042, with destinations 2/3/4/5. Hardware address/link pairs agree
with those divergent indices. All eight CPU-visible RAM descriptor
destination/link pairs match their expected values.

| Converter | DADDR | DLASTSGA | Next descriptor slot | CITER | CSR |
| --- | --- | --- | ---: | ---: | --- |
| ADC0 | `0x202642c4` | `0x2025f040` | 2 | 994 | `0x12` |
| ADC1 | `0x2026230e` | `0x2025f180` | 0 | 993 | `0x12` |

The two preceding accepted observations were retained before accounting:

| Observation | Base generation | ADC0 index | ADC1 index | DWT cycles | Pending DMA IRQs |
| --- | ---: | ---: | ---: | ---: | --- |
| Older | 4,040 | 2 | 1 | 3,440,496,398 | `0x0` |
| Newer | 4,041 | 2 | 1 | 3,441,103,678 | `0xc` |

Those observations are 607,280 cycles (1,012.133 µs) apart. They establish
that unequal indices preceded the failure; they do not establish sample loss,
the onset of divergence, or its cause. The earlier record lacks per-channel
CITER values, observation read intervals, and an absolute fault timestamp.
Sequential register reads are not atomic. Two ADC DMA errors and a completion
mismatch remain recorded, and no skew, headroom or timeout gate is relaxed.

This eighth failed physical campaign follows two
[bounded diagnostic PASS campaigns](gpio-rle600-history-repeat-20261018.md).
They did not establish a correction. The
[preceding failure](gpio-rle600-descriptor-failure-20261018.md) retains the
chain to all seven earlier physical failures and both failed RAM1 builds.
The separately qualified endurance, STOP/restart and larger-ADC images remain
complete; GPIO RLE is still unqualified.

The next diagnostic retains start/end DWT and both CITER values for each of
the two observations, plus fault-entry DWT, DMA_HRS, hardware NBYTES/BITER
and ADC GS registers. This can distinguish a long observation/service interval
from a discrepancy in apparent sample progress, subject to sequential-read
uncertainty. Live NBYTES is interpreted as a changing hardware counter, as
documented in the [NXP eDMA API](https://docs.mcuxpresso.nxp.com/mcuxsdk/latest/api/devices/MIMXRT1062/index.html).
These measurements are diagnostic instrumentation, not a demonstrated fix.
The record has 48 words, retrieved through 24 private STATUS pages after STOP;
each response retains the twelve-byte suffix and 1,536-byte frame limit.
No GPIO outputs are driven, and inputs remain electrically unstimulated.

Validation passed 80 local tests plus 137 subtests, including the production
DMA wait/service functions with diagnostic instrumentation enabled, history
rollover/freeze/reset, all private STATUS pages, ordinary-host rejection,
protocol and acquisition integration. Python lint/format and diff checks pass.
The target build passes unchanged resource gates with 34,176 bytes RAM1
stack/local headroom and 4,096 bytes RAM2 heap headroom. Its precommit image
and build log are retained separately from the committed-source image used
for the next bounded forty-cycle restart and ten-minute diagnostic campaign.
