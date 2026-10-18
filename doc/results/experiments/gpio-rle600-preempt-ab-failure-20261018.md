---
type: result
title: GPIO RLE Progressive ADC1 Deficit and Preemption Probe Failure
created: 2026-10-18
tags: [firmware, reliability, dma]
related: []
---

# Progressive ADC1 deficit in the GPIO preemption probe

**For Bill:** the fault reproduced in capture 3. ADC1 progressively falls
behind ADC0 by approximately one sample per 2,024-sample GPIO block.
Restricting GPIO DMA preemption did not prevent it. This is an acquisition
failure, not a host parser fault. No hardware change is currently required.

Job `0f3d8088-39e1-495e-8e1e-e222c3fca4c4` used clean source `715a812`, image
`thingdaq-902ea02caf2afa6f`. Odd run IDs set DPA on both GPIO channels; even
IDs retain the prior policy. Capture 1 (protected) and capture 2 (original)
passed five-second captures and 294 checks. Early and final observations
showed zero apparent ADC lead; priority readbacks were `0xC0C18283` and
`0x80818283`. Capture 3 (protected) failed after approximately four seconds.
The runner stopped; peak temperature was 52.632 degrees C. Parser errors,
discarded bytes and rejected frames were zero. Cleanup STOP observed IDLE.

The first fault is alignment timeout, indices 3/1 at generation 4,040,
ten polls, 6,609 cycles. DMA_ES/DMA_ERR were zero. Hardware destination/link
pairs and all eight CPU-visible RAM descriptor pairs match their expected
positions. The complete 96-word fault record was retrieved.

| Software generation | Apparent ADC0 lead, samples | Read span, cycles |
| ---: | ---: | ---: |
| 0 | 1 | 637 |
| 1 | 1 | 645 |
| 2 | 1 | 510 |
| 4 | 2 | 621 |
| 16 | 8 | 528 |
| 256 | 128 | 621 |
| 1,024 | 512 | 609 |
| 2,048 | 1,025 | 709 |
| 4,038 | 2,020 | 685 |
| 4,039 | 2,021 | 701 |

Between the first and generation-2,048 observations, DWT advanced
1,244,160,740 cycles (2.073601233 seconds at 600 MHz). Unwrapped ADC0
progress advanced 2,073,601 samples (999,999.887 samples/s); ADC1 advanced
2,072,577 (999,506.061 samples/s). Sequential reads limit individual-sample
precision, but cannot explain a 1,024-sample growing discrepancy. This
supports real ADC1 transfer deficit, rather than a late ISR or a one-time
descriptor-index observation. Analog conversion loss versus dropped DMA
requests still requires the request-source comparison.

The failed protected condition rules out GPIO DPA alone as a sufficient fix.
NXP RT1060 RM sections 66.5.4.2 and 66.8.3 document automatic COCO clearing;
section 67.6.1.2 documents the ETC request's acknowledgement-cleared mode.
The next same-binary probe changes ADC1's request route between ADC2 COCO
and ADC_ETC trigger 4, keeping ADC2_R0, transfer size, clocks, trigger timing
and rejection thresholds. [RT1060 reference manual](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf).

The [evidence record](gpio-rle600-preempt-ab-failure-20261018.json) preserves
all artifact hashes and decoded early progress. Raw evidence and completion
verification remain in `doc/results/raw/gpio-rle600-preempt-ab-20261018`.
Saved jobs reconciled before subsequent diagnostic edits. The separate
600 MHz endurance and larger-ADC qualification records remain unchanged.
