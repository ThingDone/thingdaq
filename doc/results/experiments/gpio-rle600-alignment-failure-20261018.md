---
type: result
title: GPIO RLE ADC Alignment Timeout Diagnosis
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE ADC alignment timeout diagnosis

**FAIL — the diagnostic reproduction stopped in cell three of eight.** Two
cells passed (292 checks); the third completed 106 checks before unexpected
IDLE. Maximum sampled temperature was 46.492 °C. The saved summary matches
independent reclassification, and firmware/program/artifact hashes reconcile.
The [complete evidence record](gpio-rle600-alignment-failure-20261018.json)
preserves this failure separately from the
[previous full campaign](gpio-rle600-dma-recurrence-20261018.md).

Job `f0c3e857-bfa3-45a8-be5a-9cb7cd582b21` ran clean commit `3e213e4`, image
`thingdaq-62cfbfaa7fa99ac4`, HEX SHA-256
`4b34121458b8f162cd01f90459e467e7fa812bfdb7c30a5f299d9abed49114a2`.
Raw evidence: `doc/results/raw/gpio-rle600-trace-20261018/restart-8x10`.
Parser errors/discarded bytes/rejection windows were zero; cleanup STOP
observed IDLE. No further cells were submitted after the fault. Read-only
inspection confirmed the runner exited and the rig had no active container.

The private first-fault record identifies the failure:

| Field | Value |
| --- | ---: |
| Reason | 1: software alignment timeout |
| ADC0 active pipeline index | 2 |
| ADC1 active pipeline index | 1 |
| Polls | 12 |
| Elapsed CPU cycles | 6,208 (10.347 µs at 600 MHz) |
| DMA error-status register | 0 |

Both converters had already completed the buffer at pipeline index zero, but
the handler insisted that their **active** descriptor indices match. Waiting
for that unrelated equality expired and faulted a completed common buffer.
The trace establishes this software timeout; it does not establish why the
hardware progress remained staggered during those samples, nor prove the
exact causes of the earlier uninstrumented failures.

The fix accounts only the common completed prefix (the smaller active index).
Both indices must remain inside the safe pipeline window, leaving a descriptor
of headroom, and may differ by at most one generation. Unmatched completion
is deferred until both converters finish it; a later dispatch accounts it
exactly once. Zero common progress can return without consuming a buffer.
Larger skew, invalid destinations, exhausted pipeline headroom, DMA error bits
and ring rejection still fail through the existing bounded path. No command
deadlines, checksums, continuity, loss or conservation checks are weakened.
The private first-fault record remains enabled for subsequent qualification.

Regression tests execute the production progress/service functions with both
converter orderings, with and without an already-completed common buffer,
and a later dispatch of the deferred pair. All eight new cases fail before
the fix across four- and six-descriptor pipelines; all pass afterward. The
combined DMA, framing, protocol, RLE, input-isolation and acquisition suite
passes 70 tests plus 106 subtests. A fresh restart reproduction followed by
smoke, three sustained captures and the final restart gate remains required.
The earlier failures, including both RAM1 build failures, remain preserved
through the linked report chain. GPIO outputs remain excluded.

Documentation/repository validation passed eight tests plus 896 subtests;
Python lint/format passed. The candidate target build passed unchanged resource
gates with 34,400 bytes of RAM1 local/stack headroom and 4,096 bytes of RAM2
heap headroom. These gates do not substitute for physical requalification.
