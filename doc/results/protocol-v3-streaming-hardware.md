---
type: report
title: Public v3 streaming matrix first-cell hardware failure
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - qualification
  - adc-dma
related:
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-identity-recovery]]'
  - '[[protocol-v3-metadata-hardware]]'
  - '[[protocol-v3-qualification]]'
  - '[[protocol-v3-migration]]'
---

# Streaming and compatibility matrix attempt

**FAIL; task incomplete.** The first 60-second ADC-only hardware RAW cell
reported two ADC DMA error events. The frozen runner stopped subsequent
submissions under its existing failure gate. None of the 56 cells selected for
this task passed: one failed and 55 remain NOT_RUN. Across the full 63-cell
campaign, the previous unsupported-request cell remains PASS, this cell is FAIL,
and 61 cells remain missing. No release promotion is justified.

[Machine-readable evidence](protocol-v3-streaming-hardware.json) retains the
failed worker record, representative raw/control frames, independent grading,
legacy SDK manifest, local test command, and hashes of local evidence files.

## Exact artifact and physical result

Candidate SHA-256:
`13b4060f6a90d7aecc4f8f93de319f389ed65a74c665f2bd72b6597e28054872`.
HEX SHA-256:
`33ff95d8f37b6ebd51457eae66c323ca99b82efe692b1b4994d2d05700398b2a`.
Physical serial `20428100`, build `thingdaq-5c7c7201f63665fd`, firmware
1.2.0, public protocol 3, and capabilities matched the unchanged candidate.

Job: `972d70fb-d407-40e9-9633-7bd197aed2c6`.
Cell: `smoke-010001030104000800000c0040420f0040420f00`.
Configuration: ADC only, hardware source, 1 MHz, RAW ADC/GPIO policies,
auxiliary DISABLED/GPIO8, CPU fixed at 600 MHz.

| Observation | Recorded value |
| --- | --- |
| Acquisition loop duration | 60.000336 seconds |
| ADC frames received on wire | 59,551, all RAW |
| ADC pairs produced and received on wire | 60,027,408 |
| ADC pairs consumed by application loop | 60,004,224 |
| SDK STOP-boundary / stale discards | 22 / 1 blocks, totaling the remaining 23,184 pairs |
| Logical/encoded ADC bytes | 240,109,632 / 240,109,632 |
| ADC wire bytes | 243,682,692 |
| DMA error events | **2 — required health gate failed** |
| ADC ETC / raw invariant errors | 0 / 0 |
| Firmware dropped frames/pairs | 0 / 0 |
| Wire gaps / wire oracle errors | 0 / 0 |
| Parser errors / host queue drops | 0 / 0 |
| Final state / pending frames | STOPPED / 0 |
| Run ID | 1 |
| Observed temperature | 39.737–49.562 °C; no 80 °C abort |

The application-loop count excludes blocks discarded by the SDK at STOP.
The independent wire count equals the firmware production count; this does
not excuse the nonzero DMA health counter. The retained worker error is:
`UnexpectedStreamValidationError: strict stream validation failed (adc_dma_error_events): observed 2 events`.

The SDK rejected final STATUS after STOP/drain. The worker therefore never
recorded its following settings readback, second clock diagnostic or final
temperature. The independent validator additionally reports missing
`readback_hex`; that is an incomplete-evidence consequence, not the initiating
failure. The pre-capture clock diagnostic passed with DWT 600 MHz, PIT 24 MHz,
load 23, 8,192 events and zero diagnostic hardware errors.

The service's built-in upload retry recovered its first failed programming
attempt. The accepted job then ran to completion with worker exit code 1.
This is a measurement failure, not a queue timeout or HTTP 5xx failure.
Final service health remained healthy. The same accepted job was followed to
its saved terminal result; no duplicate or replacement job was submitted.

## Limits and remaining work

The error's timing and cause are unproven. Source inspection identifies both
paired DMA service failures and stop-time TCD checks as paths that increment
this counter. The frozen worker did not collect a detailed DMA fault trace or
register snapshot; a later diagnosis must establish the cause without
relabeling this result or relaxing the gate. No production, SDK, schema,
runner or acceptance-policy inputs changed in this task.

The frozen runner's stop-on-failure behavior was preserved. The remaining
47 streaming tuples, two fallback cells and six canonical v2 RAW cells were
not submitted. The task checkbox stays unchecked. No playbook-wide halt
marker was added for this ordinary qualification failure; the later failure
resolution task remains applicable. Resuming retained results cannot turn
this failure into PASS or qualify the missing cells.

The unchanged pre-upgrade SDK was archived from revision
`3a52ead02791019fcdb0b27a8be869effc955aa2`, before the public-v3 foundation
commits. Its deterministic source ZIP SHA-256 is
`6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`.
The manifest records every source file hash and contains no v3 modules.
**Its isolated physical discovery/configuration/capture/diagnostics/restart
check remains NOT_RUN.** The canonical v2 cells use the new SDK and would
not, by themselves, satisfy this additional legacy-SDK requirement.

New-SDK/old-v1/old-v2 compatibility was exercised using local fixtures and
simulator personas, including discovery/version selection, capture, STOP,
restart and reconnect. No physical old firmware was exercised. The hardware
input was unstimulated; no analog accuracy or external waveform fidelity was
measured. Synthetic decoding, compressible GPIO, high-transition fallback,
lifecycle, backpressure and endurance remain unqualified by this attempt.

## Validation and evidence retention

- Freeze: PASS, 498 protected files; all 15 retained artifact hashes/sizes match.
- Compatibility, negotiation, qualification and HTTP retry regressions:
  **861 passed** in 28.66 seconds.
- Documentation and repository integrity: **11 passed, 1,409 subtests passed**.
- Independent canonical validator: expected **FAIL**, exit 1; original outcome
  and incomplete follow-on measurements preserved.

Local evidence roots:

- `.maestro/playbooks/Working/protocol-v3-qualification/smoke-010001030104000800000c0040420f0040420f00/attempt-001/`
  contains the immutable request program, firmware, saved submission/job,
  provenance, status and service results.
- `.maestro/playbooks/Working/phase06-streaming-20261024/` contains orchestration,
  regression logs, independent grading and the frozen legacy SDK archive.

As in the previous metadata task, the frozen worker hashes all received serial
bytes and retains representative frames plus bounded control samples; it does
not retain a continuous raw-byte capture. The committed JSON includes those
samples; the full returned service log remains in local `results.json`.

Regrade the accepted job without another submission:

```bash
.venv/bin/python firmware/tools/qualify_protocol_v3.py validate \
  --candidate firmware/soak/protocol-v3-candidate.json \
  --output .maestro/playbooks/Working/protocol-v3-qualification
```

Exit 1 is required for this failed, incomplete campaign.
