---
type: research
title: GPIO RLE ADC DMA Divergence Investigation
created: 2026-10-18
tags: [firmware, reliability, dma]
related: []
---

# GPIO RLE ADC DMA divergence

**For Bill:** the 600 MHz endurance PASS stands. The intermittent ADC DMA
divergence under GPIO RLE is still unresolved; the latest RLE PASS is not a
causal fix. Investigation resumed at Bill's request. No hardware change is
currently required.

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

The current immutable image `thingdaq-45d59c363f7aa067` was inspected at the
machine-code level. `hardwarePipelineIndex()` loads DLASTSGA at ITCM address
`0x1044` after each successful destination match and inside the loop. Although
the pinned core's TCD type does not mark that field volatile, the inspected
binary does not reuse a stale link across progress checks. No causal compiler
fix is claimed.

The NXP RT1060 reference manual, revision 3, sections 66.5.4.2 and 66.8.3,
states that ADC DMA requests follow COCO and that ADC_ETC hardware triggering
automatically clears COCO when a phase completes. Section 67.3.1 describes
ADC_ETC storing the conversion result and generating its own DMA request.
Our adapter instead enables ADC_GC_DMAEN, routes DMAMUX_SOURCE_ADC1/ADC2,
reads ADC1_R0/ADC2_R0, and leaves ADC_ETC_DMA_CTRL zero. Loss of a short ADC
request during DMA arbitration or scatter/gather fetch is therefore a
specific mechanism to test. It is not established as this board's cause.
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
62.457 degrees C. The following ten-minute capture is running. Frozen
orchestration, runner, validator and image hashes reconcile. No failure has
yet supplied the current image's early-phase checkpoints.

## Diagnostic change

`adc_dma_fault.h` now exposes the existing phase history after a successful
STOP as well as after a fault. `stopHardwareAfterTriggers()` seals it after
disabling requests/IRQs and servicing the last pending completion. Normal
STATUS still reports zero fault; explicit private pages have reason zero.
On healthy captures only words 36–95 contain progress history; words 0–35
remain zero and are not a hardware fault snapshot. Failed records retain
priority, idempotent STOP does not overwrite them, and prepare clears the
record. Acquisition ISR recording is unchanged. This is instrumentation,
not a fix or a relaxed acceptance gate.

Validation: 64 tests and 1,024 subtests passed, covering the production DMA
wait/service code, protocol round-trip, healthy/fault publication, reset,
ordinary-host rejection and documentation. The 600 MHz large-ADC/RLE target
build passes unchanged resource gates: 33,760 bytes RAM1 stack/local headroom
and 4,096 bytes RAM2 heap headroom. Host retrieval and physical comparison
follow after the frozen running campaign completes.
