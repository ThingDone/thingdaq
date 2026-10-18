---
type: research
title: GPIO RLE ADC DMA Divergence Investigation
created: 2026-10-18
tags: [firmware, reliability, dma]
related: []
---

# GPIO RLE ADC DMA divergence

**For Bill:** the 600 MHz endurance PASS stands. Two controlled comparisons
identify the original ADC1 DMA request route as the cause of the progressive
sample deficit. The ACK-cleared ADC_ETC route passed 7/7 short captures while
the original route failed twice. The RLE default is corrected in `441d5bc`; sustained qualification is running. No hardware change is required.

The [preemption probe reproduced the fault](../results/experiments/gpio-rle600-preempt-ab-failure-20261018.md)
in its third capture, with GPIO preemption restricted. Early history now
establishes progressive ADC1 transfer deficit: about one sample per 2,024
GPIO samples, reaching 1,025 at generation 2,048. GPIO DPA alone is
insufficient. The [request-source comparisons](../results/experiments/gpio-rle600-adc-request-ab-20261018.md)
then reproduced the fault only on the original ADC2 route. Detailed sections
below retain the sequence of hypotheses and checks; they are not all current
open questions.

## Retained evidence and new analysis

The counter, preemption and history failures all stopped at software base
generation 4,042; the descriptor failure stopped at 4,044. Hardware DADDR and
DLASTSGA agree with ADC indices 3/1. CPU-visible descriptor links agree with
the intended chain. DMA_ES/DMA_ERR and host parser errors are zero. This is
a rejected acquisition state, not evidence of a host framing defect.

The [counter](../results/experiments/gpio-rle600-counter-failure-20261018.md)
and [preemption](../results/experiments/gpio-rle600-preemption-failure-20261018.md)
records independently retain apparent ADC0 leads of 2,021 and 2,022 samples
at generations 4,040 and 4,041. Each sequential observation spans less than
one microsecond. These values are consistent with approximately one missing
ADC1 transfer per 2,024-sample GPIO block. That relationship is a hypothesis,
not a measured loss count: the onset and progression were not recorded in
those images, and DMA registers are sampled sequentially.

The pre-fix immutable image `thingdaq-45d59c363f7aa067` was inspected at the
machine-code level. `hardwarePipelineIndex()` loads DLASTSGA at ITCM address
`0x1044` after each successful destination match and inside the loop. Although
the pinned core's TCD type does not mark that field volatile, the inspected
binary does not reuse a stale link across progress checks. No causal compiler
fix is claimed.

The NXP RT1060 reference manual, revision 3, sections 66.5.4.2 and 66.8.3,
states that ADC DMA requests follow COCO and that ADC_ETC hardware triggering
automatically clears COCO when a phase completes. Section 67.3.1 describes
ADC_ETC storing the conversion result and generating its own DMA request.
At the start of this investigation, the adapter enabled ADC_GC_DMAEN, routed
DMAMUX_SOURCE_ADC1/ADC2, read ADC1_R0/ADC2_R0, and left ADC_ETC_DMA_CTRL zero. Loss of a short ADC
request during DMA arbitration or scatter/gather fetch is therefore a
specific mechanism to test. The later controlled comparison below isolates
the request route; the exact bus-arbitration cycle remains uninstrumented.
Reference: [NXP RT1060 manual hosted by PJRC](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf).

ERR011164 found in discussions of other RT parts must not be assumed to
apply here. Neither the inspected [RT1060_A errata](https://www.nxp.com/docs/en/errata/IMXRT1060CE_A.pdf)
nor [RT1060_B errata](https://www.nxp.com/docs/en/errata/IMXRT1060CE_B.pdf)
lists it. Any alternate ADC_ETC DMA route needs its own request/acknowledge
qualification on this board.

## Bounded unchanged-image reproduction

Raw evidence: `doc/results/raw/gpio-rle600-renewed-diagnosis-20261018`.
The first job, `f4f75b34-6e05-4be5-aab3-ef9e441d3ee3`, passed sixty five-second
captures and STOP/restart cycles without reflashing: 8,760 checks, peak
62.457 degrees C. The following ten-minute capture also passed: 146 checks,
66.141 degrees C peak. The [completed baseline](../results/experiments/gpio-rle600-renewed-diagnosis-20261018.md)
contains all 61 captures and 8,906 checks. Frozen orchestration, runner,
validator and image hashes reconciled before host changes. No failure
supplied the current image's early-phase checkpoints.

## Diagnostic change

`adc_dma_fault.h` now exposes the existing phase history after a successful
STOP as well as after a fault. `stopHardwareAfterTriggers()` seals it after
disabling requests/IRQs and servicing the last pending completion. Normal
STATUS still reports zero fault; explicit private pages have reason zero.
On healthy captures words 36–95 contain progress history; the follow-up
preemption probe records DCHPRI0–3 in word 0, low byte first. The request-source
probe additionally retains ADC1 DMAMUX, ETC DMA control and ETC control before
DMA teardown in words 1–3. Words 4–35
remain zero and are not a hardware fault snapshot. Failed records retain
priority, idempotent STOP does not overwrite them, and prepare clears the
record. Acquisition ISR recording is unchanged. This is instrumentation,
not a fix or a relaxed acceptance gate.

Validation: 64 tests and 1,024 subtests passed, covering the production DMA
wait/service code, protocol round-trip, healthy/fault publication, reset,
ordinary-host rejection and documentation. The 600 MHz large-ADC/RLE target
build passes unchanged resource gates: 33,760 bytes RAM1 stack/local headroom
and 4,096 bytes RAM2 heap headroom. Host retrieval and physical comparison
are now supported by `run_input_isolation.py --adc-phase`. The host retains
all 96 words, checks page/reason/run/IDLE consistency, restores ordinary
request IDs on errors, and preserves partial evidence. The preemption probe
requires this opt-in and grades actual priority-register readback against
the acquisition epoch. Fault retrieval reuses the same reader and preserves
the original acquisition failure if retrieval fails.

## Controlled preemption probe

RT1060 RM section 6.3.4 explicitly disallows nested DMA preemption and
describes DPA as a way to keep low-priority channels from occupying the
preempt slot. Our GPIO channels currently permit preemption of each other.
A GPIO major-loop descriptor fetch occurs every 2,024 samples. A GPIO
transfer occupying the preempt slot while ADC1's request pulses is a second,
more specific hypothesis; the previous experiment cleared ADC1 ECP, which
does not prevent a GPIO channel from occupying that slot.

The opt-in `--gpio-preempt-probe` build alternates policies within one binary:
odd acquisition epochs set DPA on both GPIO channels, even epochs retain the
existing policy. Numeric priorities and ADC ECP remain unchanged; both GPIO
channels remain preemptible by an ADC channel. Selection occurs in stopped
ADC prepare before either capture engine starts; GPIO setup reuses it. Other
builds retain the original policy. The build identity and manifest explicitly
mark the probe. Healthy STOP captures the four priority registers for host
verification. This is a controlled diagnostic, not a production fix, and a
PASS without a reproduced control failure cannot establish causality.

## ADC1 request-source probe

The opt-in `--adc-etc-probe` build uses ADC_ETC trigger 4's DMA request
(DMAMUX source 23) on odd run IDs and the original ADC2 request (source 88)
on even IDs. It excludes the preemption probe, so priority policy is constant.
The DMA source address remains ADC2_R0 with identical halfword transfers,
descriptors and sample rate. DMA_MODE_SEL is enabled only for the ETC route:
its request clears on DMA ACK instead of following automatically cleared
ADC COCO. Trigger STOP preserves the handshake until the final conversion
drains; ADC DMA teardown disables ETC requests and clears mode. Setup rejects
a busy ETC DMA source, clears stale trigger-4 requests and verifies enables
and mux before triggers start. The host grades source, enable and mode
readback against run ID after each successful STOP.

The request-source probe passes the target build with unchanged 33,760-byte
RAM1 and 4,096-byte RAM2 free-space floors. Adapter, DMA service, codec and
host tests passed 89 tests plus 55 subtests; subsequent manifest-identity,
probe opt-in and documentation checks passed 28 tests plus 980 subtests.
The register test executes the production arm/STOP adapter and verifies that
the ETC handshake survives trigger shutdown until DMA teardown.

## RLE correction

Normal GPIO RLE builds now select the ACK-cleared ADC_ETC trigger-4 request
for ADC1 on every epoch. Explicit diagnostic probes retain their original
comparison policies. The board resource table and private INFO metadata now
advertise source 23 for the corrected build; the matching host validator gets
this selection from the immutable build manifest. Public non-RLE builds and
their source-88 contract are unchanged. Both converters still read the same
ADC result registers with the same descriptors and phase schedule. GPIO RLE
encoding is unchanged. Source/enable/mode readback, original error checks and
the 80 degrees C campaign abort remain mandatory in the next qualification.

## Corrected-image qualification checkpoint

Clean source `441d5bc`, image `thingdaq-24c275c126c4e0d8`, passed the
60-second smoke capture and sixty five-second START/STOP cells without reflash:
61 cells, 9,089 checks, peak 62.457 degrees C. All actual source/enable/mode
readbacks and bounded early/final ADC phase observations passed. Three
600-second captures are now running sequentially; their outcome is pending.
Raw evidence: `doc/results/raw/gpio-rle600-etc-fixed-20261018`.

The complete firmware suite passed 324 tests and 838 subtests, with three
unsupported build combinations skipped. The initial bare pytest invocation
failed collection because of its import path; the passing invocation used
`python -m pytest` from the repository root. Corrected RLE and ordinary
non-RLE 600 MHz larger-ADC target builds both pass the normal gates. RLE
headroom remains 33,760/4,096 bytes (RAM1/RAM2); non-RLE has 34,464/4,096.
