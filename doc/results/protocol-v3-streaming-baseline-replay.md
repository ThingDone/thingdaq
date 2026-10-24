---
type: report
title: Exact-worker ADC RAW replay reproduces two DMA errors
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - qualification
  - adc-dma
related:
  - '[[protocol-v3-streaming-hardware]]'
  - '[[protocol-v3-streaming-stop-diagnostic]]'
  - '[[protocol-v3-identity-recovery]]'
  - '[[protocol-v3-qualification]]'
---

# Original-worker failure reproduction

**FAIL reproduced; streaming qualification remains incomplete.** A fresh
60-second ADC-only hardware RAW capture using the exact original worker and
unchanged candidate again reported two ADC DMA errors at final STATUS. This
reproduces the symptom in [[protocol-v3-streaming-hardware]] without the added
STATUS requests in [[protocol-v3-streaming-stop-diagnostic]]. It does not
establish the fault site, timing, or root cause.

[Machine-readable evidence](protocol-v3-streaming-baseline-replay.json) retains
the complete worker record, representative frames, immutable input identities,
job reconciliation, independent grading, and local evidence hashes.

## Identity and execution

- Candidate SHA-256: `13b4060f6a90d7aecc4f8f93de319f389ed65a74c665f2bd72b6597e28054872`.
- HEX SHA-256: `33ff95d8f37b6ebd51457eae66c323ca99b82efe692b1b4994d2d05700398b2a`.
- Worker program SHA-256: `a3cef2d57d7c653b351003d4e7dfd06c74f970cb40d5b543ff591891b211cd68`.
- Physical serial: `20428100`; build: `thingdaq-5c7c7201f63665fd`.
- Original failed job: `972d70fb-d407-40e9-9633-7bd197aed2c6`.
- Prior STATUS-probe job: `90ac5e11-7959-423f-911e-fc7bfcbd312f`.
- New reproduction job: `1a3535d7-2646-4a69-88ae-d832c758ee7f`.

The two prior jobs were confirmed terminal using saved results and live
`/status` before the new diagnostic was submitted. Availability passed. All
HTTP used `run_input_isolation.py`, retaining submission identity and following
the accepted job. The new program was compared byte-for-byte with both the
original saved program and the current candidate's generated worker. Firmware,
SDK, schemas, policy, thermal cutoff and execution budget were unchanged.

A bounded plan allowed at most three separately flashed replays, stopping at
the first nonpassing result. Replay 1 reproduced the failure, so replays 2 and
3 were never submitted. The service reported completion and
`program_success=true`, but worker exit code **1** and the worker FAIL record
control measurement acceptance. Service completion is not qualification PASS.

## Measurements

Configuration: ADC only, hardware source, 1 MHz, RAW policies, auxiliary
DISABLED/GPIO8, fixed 600 MHz CPU; run ID 1.

| Measurement | Original failure | Exact-worker replay |
| --- | ---: | ---: |
| Acquisition loop duration, seconds | 60.000336 | 60.000021 |
| ADC pairs produced and received on wire | 60,027,408 | 60,025,392 |
| RAW ADC frames | 59,551 | 59,549 |
| ADC DMA error events | **2** | **2** |
| ADC ETC / raw invariant errors | 0 / 0 | 0 / 0 |
| Wire gaps / parser errors / host drops | 0 / 0 / 0 | 0 / 0 / 0 |
| Final state / pending frames | STOPPED / 0 | STOPPED / 0 |
| Observed temperature range, °C | 39.737–49.562 | 42.193–51.404 |

The replay carried 240,101,568 logical/encoded ADC bytes and 243,674,508 ADC
wire bytes. The application loop consumed 60,017,328 pairs; seven STOP-boundary
blocks plus one stale block account for the remaining 8,064 pairs. Firmware
production and independent wire accounting agree. These observations do not
excuse the nonzero health counter.

The pre-capture physical clock diagnostic passed at 600 MHz CPU and 24 MHz
PIT. Two temperature requests returned NOT_READY; their existing bounded
retries returned VALID. No thermal cutoff occurred. The SDK rejected final
STATUS after STOP with the same exception as the original job:
`UnexpectedStreamValidationError: strict stream validation failed (adc_dma_error_events): observed 2 events`.
Subsequent settings readback, final clock measurement and final temperature
were consequently not collected. Independent grading additionally reports
missing `readback_hex`; no value was synthesized to complete that evidence.

## Interpretation and disposition

The original worker has now failed twice with this symptom, while the prior
worker with eleven additional STATUS observations passed once. Those are three
separate flashed jobs, not a statistical reliability estimate or a controlled
proof of a STOP race. Identical worker bytes preserve the algorithm, not OS,
USB, thermal-retry, or firmware interrupt timing. No new serial probes were
injected into this replay.

Source inspection still identifies several counter increment paths:
`servicePendingDmaPair()` can record a pair of errors on invalid pipeline
progress, DMA hardware error or exhausted service attempts;
`processInferredPairCompletion()` can record a hardware error per converter;
and stop-time `activeMinorPairs()` can record invalid TCD iteration counts.
Final public STATUS cannot distinguish those paths. The existing detailed
fault trace is conditional on `THINGDAQ_EXPERIMENT_GPIO_RLE` and is not exposed
by this candidate. The next diagnostic needs fault-site or boundary evidence;
another passing capture alone cannot resolve this reproduced failure.

The canonical campaign remains untouched: the streaming selection has **one
FAIL and 55 NOT_RUN**, and the full campaign has the earlier unsupported-request
PASS plus **61 missing cells**. This separate replay earns no matrix credit and
replaces no result. The first streaming task stays unchecked. No halt marker,
production correction, refreeze, later-task execution or promotion was made.

## Validation and retention

- Active freeze: PASS, all 498 protected files.
- All 15 retained artifacts: hashes and sizes verified.
- Local compatibility, negotiation, qualification and HTTP retry tests: 861 passed.
- Existing production-function DMA interrupt-order tests: 39 passed.
- Documentation/repository integrity: 11 tests and 1,424 subtests passed.
- Canonical independent validator: expected FAIL, original result preserved.

The unchanged pre-upgrade SDK archive remains pinned to
`3a52ead02791019fcdb0b27a8be869effc955aa2`; its physical compatibility check remains
NOT_RUN. New-SDK/old-v1/v2 evidence is from local fixtures and simulators only.
No physical old firmware, analog accuracy or external waveform fidelity was
tested. The worker hashes all serial bytes and retains representative frames
and bounded control samples, not a continuous raw-byte archive.

Local retained inputs, service results, replay driver and validation logs:
`.maestro/playbooks/Working/phase06-streaming-baseline-replay-20261024/`.
The driver requires `--resume` on existing evidence and preserves the failed
result without submitting a replacement. It imports the current established
runner; archived raw-evidence programs must not be executed directly.
