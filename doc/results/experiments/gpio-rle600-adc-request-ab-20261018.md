---
type: result
title: GPIO RLE ADC Request Source Root Cause Comparison
created: 2026-10-18
tags: [firmware, reliability, dma]
related: []
---

# ADC1 request-source comparison

**For Bill:** the comparisons identify the ADC1 DMA request route as the
defect causing the recurring sample deficit. ADC_ETC's acknowledgement-cleared
request passed all seven captures; the original ADC2 request reproduced the
failure twice. The correction is being made the RLE default and needs sustained
qualification. No hardware change is required.

Both campaigns used the identical image `thingdaq-b845812541fe0e65`, clean
source `b71785e`. Odd run IDs select ADC_ETC trigger 4 (DMAMUX 23, ACK-cleared
mode); even IDs select ADC2 COCO (DMAMUX 88). ADC2_R0, halfword transfer size,
descriptors, priorities, 600 MHz core, 1 MS/s ADCs, 1 MHz GPIO and RLE codec
are identical within each comparison. Actual source/enable/mode registers
were checked after every successful STOP.

| Campaign | ADC_ETC route | Original ADC2 route | Failure run ID | Peak degrees C |
| --- | --- | --- | ---: | ---: |
| First comparison | 5 PASS | 4 PASS, 1 FAIL | 10 | 51.404 |
| Repeat | 2 PASS | 1 PASS, 1 FAIL | 4 | 50.790 |

Passing captures ran five seconds each and completed 1,788 checks in total.
Their retained early and final sample-offset observations were within -1 to
+1 sample, consistent with sequential register-read timing. Both failures
used the original route and reproduced progressive deficits near one ADC1
sample per GPIO block: approximately 128 at generation 256, 512 at 1,024 and
1,024–1,025 at 2,048. Both then tripped alignment timeout, indices 3/1, near
four seconds. DMA_ES/DMA_ERR and parser errors/discarded bytes were zero.
Cleanup STOP observed IDLE, and no subsequent cell was submitted after failure.
The negative controls remain FAIL, not qualification successes.

This isolates the request path, rather than a GPIO RLE coding or host parser
error. NXP documents that ADC_ETC clears ADC COCO after a phase completes;
the ADC DMA request follows COCO, so it can disappear without a DMA transfer.
The observed deficit is consistent with that request being missed under GPIO
DMA load. ADC_ETC's separate request in DMA_MODE_SEL=1 clears on DMA ACK.
The same-result-register intervention and repeated original-route failures
support a firmware request-source defect causing genuine ADC1 sample loss.
The exact bus-arbitration cycle that misses a request was not instrumented;
no undocumented silicon erratum is asserted. See RT1060 RM sections 66.5.4.2,
66.8.3 and 67.6.1.2 in the [reference manual](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf).

Jobs were `c993b27b-3a41-4588-a4a5-d2d7521d251d` and
`a16a32d1-09bb-4341-a9b2-ce6dcdfde707`. The [complete evidence](gpio-rle600-adc-request-ab-20261018.json)
retains both campaigns and artifact hashes. Raw evidence lives in
`doc/results/raw/gpio-rle600-etc-ab-20261018` and
`doc/results/raw/gpio-rle600-etc-ab-repeat-20261018`; both reconciled before
subsequent host changes. Electrical inputs were unstimulated. Seven short
corrected-route passes establish useful causal evidence, not an endurance
claim or a qualification of arbitrary analog/GPIO stimuli.
