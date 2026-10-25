---
type: report
title: Public v3 ADC DMA STOP fault-site evidence
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - qualification
  - dma
related:
  - '[[protocol-v3-streaming-baseline-replay]]'
  - '[[protocol-v3-streaming-stop-diagnostic]]'
  - '[[protocol-v3-release-candidate]]'
---

# ADC DMA failure localized to STOP

The diagnostic reproduced two DMA errors **inside STOP boundary arming**.
The ADC1 CSR update that sets DREQ can clear ESG when DONE is still set.
A deterministic harness executing the production boundary function reproduces
this hardware coherency rule: DONE on ADC0, ADC1, or both fails; the ordinary
case and three refusal/headroom controls pass. The historical candidate remains
failed, and no diagnostic capture earns matrix credit.

Job `982f84e0-18d4-46e0-a224-41f49098f6e7` used diagnostic build
`thingdaq-f90d046020134e18` from pushed source `963b84a`, with the original
60-second ADC-only RAW configuration. The original three jobs were reconciled
terminal first. The new job waited in the shared queue and completed through
`run_input_isolation.py`; no duplicate submission was made.

Instrumentation adds no acquisition-time STATUS requests, uses failure-only
register recording and STOP phase markers, and reads the trace after STOP.
The image borrows the idle OCRAM checksum benchmark buffer; no checksum
benchmark ran between prepare and retrieval. It passes unchanged memory gates:
32,768 bytes RAM1 stack reserve and 4,096 bytes RAM2 heap reserve. The original
frozen candidate remains unchanged. Initial diagnostic build failures and logs
are retained, including RAM1 and RAM2 reserve failures.

## Captured fault

| Observation | Value |
| --- | --- |
| First fault reason | 1: `waitForSafePipelineProgress()` timeout |
| STOP phase | 2: DREQ armed, awaiting completion |
| Observed pipeline indices | ADC0 = 1, ADC1 = 4 (invalid) |
| Alignment polls / elapsed cycles | 12 / 6,261 |
| ADC0 CSR / CITER / BITER | `0x92` / 1,008 / 1,008 |
| ADC1 CSR / CITER / BITER | `0x8a` / 1,008 / 1,008 |
| DMA_ERR / DMA_ES | 0 / 0 |
| ADC1 buffer end | `0x20267202` |
| ADC1 DLASTSGA | `0x2025f200` |
| ADC1 observed DADDR | `0x404c6402` = buffer end + DLASTSGA |
| Ordinary stopped STATUS DMA errors | 2 |

ADC1 CSR has DONE, DREQ and INTMAJOR set, with ESG cleared. Its destination
therefore contains the exact addition that occurs when a descriptor pointer
is interpreted as the final destination offset instead of a scatter/gather
address. This is a software progress-validation failure, not a DMA engine
bus-error flag. The ISR records one error for each converter when it cannot
reconcile the pair.

The [NXP RT1060 reference manual, section 5.5.7.3](https://lv.mouser.com/pdfdocs/NXP_iMX_RT1060_Reference.pdf)
documents that writing TCD word 7 while DONE is set clears ESG and major-loop
linking. DONE must be cleared before updating those fields. The production
STOP function currently reads CSR and writes it back with DREQ without first
clearing DONE; its CITER headroom check also admits a freshly reloaded TCD.
This register evidence plus the production-function reproduction supports that
specific path. Stop-time `activeMinorPairs()` validation is not the first fault.

## Evidence limits and next gate

The diagnostic worker itself remains **FAIL**. Its private response mapping
put arbitrary trace words into produced/dropped counters; page 50 was rejected
by the normal `dropped <= produced` response check. Checksummed retained control
frames recover summary and pages 1–49, including the fault registers and STOP
phase. Remaining boundary timestamps are unavailable; they are not invented.
This retrieval defect does not alter the already captured fault and must be
corrected separately from acquisition behavior.

Full firmware regression: 1,393 passed, five expected skips, 838 subtests.
Focused validation: 116 passed and 55 subtests. The independent STOP regression
fails three DONE cases against the faulty production implementation and passes
four controls. Its fake registers model the documented coherency rule, not
analog or bus-level timing.

Machine-readable observations, exact hashes and retained paths are in
[protocol-v3-dma-fault-site.json](protocol-v3-dma-fault-site.json).
The next correction is to clear channel DONE before the STOP CSR/DREQ update,
then run the regression, target gates, and new-candidate qualification.
The original failure, byte-identical replay failure, and timing-altered probe
PASS remain separate historical outcomes. Matrix continuation requires a new
frozen candidate and fresh prerequisite evidence.
