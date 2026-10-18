---
type: result
title: GPIO RLE Descriptor Divergence Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE descriptor divergence failure

**FAIL — two restart cells passed; the third failed after approximately four
seconds.** The planned forty-cell restart test stopped immediately, and its
following ten-minute job was never submitted. The passing cells completed
292 checks; peak sampled temperature was 47.720 °C. Parser checksum, header,
payload errors and discarded bytes were zero, including the failing cell.
Cleanup STOP observed IDLE. Saved summary, provenance and artifact hashes
reconcile exactly; frozen scripts were verified before diagnostic changes.
The [complete evidence record](gpio-rle600-descriptor-failure-20261018.json)
preserves the failed campaign, and raw artifacts remain in
`doc/results/raw/gpio-rle600-detail-repeat-20261018`.

Remote job `a3ba2fff-f93c-4eb0-bb6f-ddf5cc99e8b9` used clean source `2edfa63`,
image `thingdaq-0f462a06fef8cf6f`, HEX SHA-256
`24dd53a2a2e2f3c54daa5ef130ecccf0061b9d55636aafc2c352a6ba2ac64549`.
The runner exited; postflight service health was healthy with an empty queue.
Subsequent read-only Docker inspection found no active container.

The first fault is alignment timeout: indices 3/1, ten polls, 6,308 cycles
(10.513 µs at 600 MHz), DMA_ES and DMA_ERR zero. The software pipeline base
was generation 4,044, with destinations 4/5/6/7. Retained hardware registers:

| Converter | DADDR | DLASTSGA | Next descriptor slot | CITER | CSR |
| --- | --- | --- | ---: | ---: | --- |
| ADC0 | `0x20266280` | `0x2025f080` | 4 | 996 | `0x12` |
| ADC1 | `0x202642c6` | `0x2025f1c0` | 2 | 995 | `0x12` |

Both address/link pairs agree with the divergent indices. All eight retained
CPU-visible RAM descriptor destination/link pairs match their expected values.
These sequential reads are not an atomic snapshot and do not establish the
cause of the divergence, DMA-visible descriptor contents at load time, or
sample fidelity. The safe-window and skew guards correctly reject this state;
neither limit is relaxed. Two ADC DMA error events and a completion mismatch
remain recorded as failure, despite zero wire parser errors.

The preceding [bounded diagnostic PASS](gpio-rle600-detail-diagnostic-20261018.md)
did not establish a fix. This seventh physical failure retains the chain to
the [six earlier failed campaigns](gpio-rle600-window-failure-20261018.md)
and both failed RAM1 builds. The separately qualified endurance, STOP/restart
and larger-ADC images remain complete; GPIO RLE remains unqualified.

The next diagnostic adds the last two accepted DMA progress observations:
software base generation, packed converter indices, DWT timestamp and pending
DMA interrupts. They occupy detail words 36–43, oldest first, and reset at
prepare. The first fault freezes them before publishing its reason. These
observations precede completion accounting; hardware may advance during the
reads. They add bounded RLE-only recording work on the successful service path,
so this is a new diagnostic image, not a timing-neutral replay or a fix.
Explicit private STATUS pages now extend through `0xFADC0016`; each response
still has the same twelve-byte suffix and 1,536-byte control-frame limit.
The independent validator retrieves all 22 pages after cleanup and retains
the original FAIL if retrieval fails. Fresh bounded restart reproduction and
full qualification remain necessary; GPIO outputs remain disabled.

Validation passed 70 local tests plus 137 subtests, covering history rollover,
freeze/reset, all private STATUS pages, ordinary-host rejection, interrupt
ordering, protocol and acquisition integration. Documentation/repository checks
passed eight tests plus 916 subtests; Python lint/format and diff checks passed.
The target build passed unchanged resource gates with 34,208 bytes RAM1
stack/local headroom and 4,096 bytes RAM2 heap headroom. The precommit image
and build log are retained separately from the clean qualification image.
