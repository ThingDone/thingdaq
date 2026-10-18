---
type: result
title: GPIO RLE Qualification ADC DMA Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE qualification ADC DMA failure

**FAIL — the first cell of the restart job stopped on an ADC DMA pipeline
fault.** The preceding smoke and all three ten-minute captures passed, with
584 checks and a maximum sampled temperature of 66.755 °C. They do not replace
the failed restart gate. All five summaries, provenance and artifact hashes
were reconciled against the saved results. Full evidence is in
[the campaign record](gpio-rle600-dma-failure-20261018.json).

| Job | Outcome | Checks | Peak °C |
| --- | --- | ---: | ---: |
| smoke-60 | PASS | 146 | 49.562 |
| sustained-01 | PASS | 146 | 64.913 |
| sustained-02 | PASS | 146 | 66.141 |
| sustained-03 | PASS | 146 | 66.755 |
| restart-4x10 | FAIL in first cell | 106 before failure | 60.615 |

Failed remote job `c7d63a8b-1605-4e84-8e69-4b8ddd963e3f` used immutable
`thingdaq-87c25c1a8732105e`, HEX SHA-256
`8436511c60ce30e5a8a83bf6471bb0426c5443b7ad9b2a0b16420004d60c3d00`.
Raw evidence remains under `doc/results/raw/gpio-rle600-startfix-20261018`.
The upload initially failed in HalfKay and the service's second programming
attempt succeeded; both attempts remain in the captured stdout. The validator
synchronized and passed START and warmup before the acquisition fault.

The failing STATUS reported IDLE with cleared configuration during an active
capture. It contained two ADC DMA error events, one completion mismatch and
eleven incomplete conversions, after 2,000 ADC and 1,001 GPIO frames. The
reported partial STOP tails were 276 ADC pairs and 265 GPIO samples. Parser
checksum/header/payload errors and discarded bytes were zero, with no rejection
windows. Cleanup STOP also observed IDLE. These are failed-run snapshots, not
proof of successful final conservation. The runner stopped and submitted no
further work; subsequent read-only inspection found no running rig container.

## Reproduced defect and fix

The DMA error counter also covers software alignment faults; it does not
establish a silicon DMA error. Inspection found a reproducible interrupt race:
the handler clears a latched interrupt, then infers completed generations from
current DMA descriptor progress. A further completion between those operations
can be included in that inference while its new interrupt remains latched.
After accounting those generations, the next visit sees both channels at
active pipeline index zero. The previous code required a positive index and
incorrectly timed out waiting for a generation it had already counted.

A deterministic host test executes the production alignment and service
functions with simulated register ordering. The original code fails both the
completion-after-acknowledgement case and an already-accounted wakeup. The fix
accepts aligned index zero as no new work. It still checks DMA hardware error
bits, rejects unmatched or out-of-window progress, preserves the bounded wait,
and propagates ring completion failures. Tests also exercise an ordinary
completion and a new completion during ring processing. No checksum,
continuity, loss, conservation, temperature or command deadline gate changes.

The historical failure is **consistent with this race, but its exact cause
remains unproven**: the original snapshot lacks the TCD/IRQ ordering at the
fault. New physical qualification is required on a separately identified image;
another failure must be preserved and investigated. The prior host START
failure and both RAM1 build failures remain recorded in the
[earlier failure report](gpio-rle600-start-boundary-failure-20261018.md).

The candidate target build passes the unchanged resource gates: 34,400 bytes
of RAM1 local/stack headroom and 4,096 bytes of RAM2 heap headroom. The packet
pool remains unchanged. Hardware inputs remain electrically unstimulated and
GPIO outputs remain excluded. This report does not claim final RLE qualification.

Local validation passed 46 focused tests plus 86 subtests, then 18 interrupt
ordering cases across four- and six-descriptor pipelines. Integration tests
passed 20 tests plus 41 subtests (three unsupported configurations skipped);
documentation/repository checks passed eight tests plus 885 subtests. Python
lint and formatting checks passed. These local gates do not replace the fresh
physical qualification.
