---
type: result
title: GPIO RLE Sample Counter Divergence Failure
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE sample counter divergence failure

**FAIL — one ten-second restart cell passed; the second failed after about
four seconds.** The runner stopped, and the ten-minute diagnostic was never
submitted. The passing cell completed 146 checks; peak sampled die temperature
was 44.036 °C. Parser checksum/header/payload errors and discarded bytes were
zero, including the failed cell. Cleanup STOP observed IDLE. Summary,
provenance and artifact hashes reconcile exactly, and frozen scripts match.

Remote job `76b2ac03-b8e3-4086-806d-472c1dc41b0f` used clean source `ebc2486`,
image `thingdaq-97f99da6e911833c`, HEX SHA-256
`2f9f46dcd2ff4b7f1af4822a9f2a9ab1a317cba2e37510a6a3db59f98e868138`.
The [complete evidence record](gpio-rle600-counter-failure-20261018.json)
preserves both cells. Raw evidence and decoded detail remain in
`doc/results/raw/gpio-rle600-counters-20261018`.
The runner exited; postflight service health was healthy with an empty queue.

The first fault was alignment timeout: indices 3/1 at base generation 4,042,
ten polls, 6,425 cycles (10.708 µs), DMA_ES and DMA_ERR zero. Hardware
DADDR/DLAST pairs confirm those indices, while all eight CPU-visible RAM
descriptor destination/link pairs match expectations. ADC0 CITER was 993 and
ADC1 CITER 991 when sampled during fault capture. Both BITER values were 1,012
and live NBYTES values 2; DMA_HRS was zero and both ADC GS registers were 1.

The new diagnostic preserves preceding observations:

| Base | Indices ADC0/ADC1 | CITER ADC0/ADC1 | End DWT | Read span cycles | Apparent ADC0 lead, samples |
| ---: | --- | --- | ---: | ---: | ---: |
| 4,040 | 2/1 | 1/1,010 | 2,041,251,145 | 587 | 2,021 |
| 4,041 | 2/1 | 1/1,011 | 2,041,858,413 | 583 | 2,022 |

The lead estimate is `(index0 - index1) * 1012 - CITER0 + CITER1`.
Register reads are sequential, so descriptor transitions and read latency can
affect this estimate. Both read spans are under one microsecond; the gap
between observation ends is 607,268 cycles. Fault-entry DWT was 2,042,477,029,
618,616 cycles after the last observation. These measurements narrow the
investigation toward differing DMA sample progress, beyond a long sequential
register-read delay. They do not prove peripheral request loss, descriptor
fetch corruption, or a specific arbitration cause.

This ninth failed physical campaign retains the chain through the
[preceding history failure](gpio-rle600-history-failure-20261018.md) to all
eight earlier failures and both failed RAM1 builds. Earlier bounded PASS
campaigns remain valid observations but did not establish a fix. The
endurance, STOP/restart and larger-ADC stages remain complete on their
separately qualified images. GPIO RLE is still unqualified.

The next controlled candidate clears ADC1's DMA ECP bit only in the private
combined-input RLE build. NXP documents that enabling channel preemption
allows higher-priority channels to suspend it; see the
[eDMA channel configuration](https://docs.mcuxpresso.nxp.com/mcuxsdk/latest/api/devices/MIMXRT1062/index.html).
Preventing suspension tests the hypothesis that ADC1 request service is
delayed during higher-priority work. It does not establish that hypothesis.
ADC0 and both GPIO channel settings, all numeric priorities, sample rates,
ADC resolution, checksums and capture acceptance limits are unchanged.
Stopped setup verifies the selected ECP bit. Ordinary builds and
non-auxiliary setup retain the prior configuration.

The candidate must pass a fresh forty-cycle restart diagnostic and ten-minute
capture before any further qualification decision. No follow-on campaign or
final report is automatic. A further failure must be preserved and analyzed;
no GPIO output or externally stimulated fidelity is claimed.

Candidate validation passed 51 local tests plus 106 subtests, including actual
priority-register writes in both ordinary and RLE configurations, repeated
auxiliary/non-auxiliary setup, DMA service ordering, protocol and acquisition
integration. Documentation/repository validation passed eight tests plus 936
subtests; Python lint/format and diff checks pass. An initial test invocation
omitted required RLE build-selection flags and was rejected by the existing
compile-time guard; the harness was corrected without changing that guard.
The target build passes unchanged memory gates (34,176 bytes RAM1 local/stack,
4,096 bytes RAM2 heap headroom). Precommit image and build log are retained
separately from the committed-source candidate used for physical testing.
