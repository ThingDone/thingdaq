---
type: result
title: GPIO RLE DMA Preemption Candidate Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE DMA preemption candidate failure

**FAIL — clearing ADC1 DMA preemption did not prevent the divergence.**
Two ten-second restart cells passed (292 checks), then the third failed after
about four seconds. The runner stopped and did not submit the ten-minute
diagnostic. Peak sampled die temperature was 45.264 °C; parser checksum,
header and payload errors and discarded bytes were zero. Cleanup STOP
observed IDLE. Postflight service health was healthy with an empty queue.
All summary, provenance and artifact hashes reconciled exactly; frozen script
hashes matched before the next diagnostic edit.

Remote job `90322240-88bc-4a5b-b1e6-7d919194c3ea` used clean source `a95f59f`,
image `thingdaq-104086be1e3b3b9d`, HEX SHA-256
`4dd4967edd82a324d50cd88b15deaa7f9e95304c03963bb1dc3d1942547a5f0b`.
The [complete evidence record](gpio-rle600-preemption-failure-20261018.json)
preserves all three cells. Raw evidence and decoded detail are retained in
`doc/results/raw/gpio-rle600-preemption-20261018`. The runner exited.

The first fault was again alignment timeout: indices 3/1 at base generation
4,042, ten polls, 6,455 cycles (10.758 µs), DMA_ES and DMA_ERR zero. Hardware
destination/link pairs confirmed the indices and all eight CPU-visible RAM
descriptor destination/link pairs matched expectations. CITER values were
993/991, BITER 1,012/1,012, live NBYTES 2/2, DMA_HRS zero and ADC GS 0/1.

| Base | Indices ADC0/ADC1 | CITER ADC0/ADC1 | End DWT | Read span cycles | Apparent ADC0 lead, samples |
| ---: | --- | --- | ---: | ---: | ---: |
| 4,040 | 2/1 | 1/1,010 | 3,684,372,699 | 577 | 2,021 |
| 4,041 | 2/1 | 1/1,011 | 3,684,979,899 | 577 | 2,022 |

Observation ends were 607,200 cycles apart. Fault-entry DWT was 3,685,598,347,
618,448 cycles after the last observation. Sequential reads remain non-atomic.
The same sample-progress discrepancy occurred despite disabling ADC1 channel
preemption. This does not exclude every possible arbitration effect, but this
candidate is not an effective correction and its ECP change is removed.
All priorities and preemption settings return to their prior values; a local
register-write test now checks that both ordinary and RLE setup restore them.

This tenth failed physical campaign preserves the chain through the
[counter diagnostic failure](gpio-rle600-counter-failure-20261018.md) to all
nine preceding failures and both failed RAM1 builds. The cause remains
unresolved. Earlier endurance, STOP/restart and larger-ADC stages remain
complete on their separately qualified images. GPIO RLE remains unqualified.

The next diagnostic adds eight sparse progress checkpoints: the first accepted
observation at or after base generations 0, 1, 2, 4, 16, 256, 1,024 and 2,048.
Each records base, indices, end DWT, pending DMA IRQs, packed CITER and start
DWT, using the same six-word format as the last-two history. These distinguish
initial offset, gradual drift and a later step. They freeze at the first fault
and reset on prepare. Bounded storage adds 48 detail words at offsets 48–95;
48 private STATUS pages retrieve the entire 96-word record after STOP, keeping
the twelve-byte suffix and 1,536-byte response limit. These measurements alter
service timing and are not a demonstrated fix. No capture gate is relaxed.

A fresh bounded forty-cycle restart and ten-minute diagnostic will collect
this record, stopping on first failure. No full qualification or finalizer
follows automatically. GPIO outputs remain disabled; inputs are electrically
unstimulated and no external-pattern fidelity is claimed.

Validation passed 82 local tests plus 137 subtests, covering threshold crossing,
immutable checkpoint retention, DWT wrap, reset, all 48 STATUS pages, ordinary
host rejection, restored priority registers, DMA service, protocol and
acquisition integration. Python lint/format and diff checks pass. The target
build passes unchanged memory gates with 33,760 bytes RAM1 stack/local and
4,096 bytes RAM2 heap headroom. The precommit image/build log remain separate
from the clean committed-source diagnostic image.
