---
type: report
title: Same-candidate ADC RAW STOP diagnostic did not reproduce DMA failure
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - qualification
  - adc-dma
related:
  - '[[protocol-v3-streaming-hardware]]'
  - '[[protocol-v3-identity-recovery]]'
  - '[[protocol-v3-qualification]]'
---

# Streaming failure follow-up

**INCONCLUSIVE diagnosis; streaming matrix remains FAIL and incomplete.**
A separate 60-second ADC-only RAW capture on the unchanged candidate passed,
including eleven added STATUS observations. It did not reproduce the two DMA
errors in [[protocol-v3-streaming-hardware]], so neither fault timing nor root
cause is established. No failed result was replaced and no matrix cell was
credited for this supplemental program.

[Machine-readable evidence](protocol-v3-streaming-stop-diagnostic.json) includes
the full diagnostic worker record, STATUS observations, immutable input hashes,
retained-file hashes, and the unchanged canonical campaign grading.

## Identity and execution

- Candidate SHA-256: `13b4060f6a90d7aecc4f8f93de319f389ed65a74c665f2bd72b6597e28054872`.
- HEX SHA-256: `33ff95d8f37b6ebd51457eae66c323ca99b82efe692b1b4994d2d05700398b2a`.
- Physical serial: `20428100`; build: `thingdaq-5c7c7201f63665fd`.
- Original failed job: `972d70fb-d407-40e9-9633-7bd197aed2c6`.
- Supplemental job: `90ac5e11-7959-423f-911e-fc7bfcbd312f`.

The original saved result was terminal before submission. Live `/status`
reconciliation returned `status=success`, `message=Test completed`; this means
service completion, not measurement acceptance. Its worker exit code remains
1 and its qualification result remains FAIL. Availability passed before the
new diagnostic submission. All HTTP used `run_input_isolation.py` and the
accepted diagnostic job was followed to completion.

The diagnostic reused the frozen qualification worker, SDK bundle, policy,
identity/capability checks, thermal cutoff, capture checks and execution budget.
A local wrapper added read-only STATUS queries after thermal measurements and
immediately around SDK STOP, plus settings readback after STOP. It did not
suppress any health check. The supplemental program has a separate ID and
hash; the candidate's firmware/SDK/schema/runner inputs remain unchanged.

## Observations

| Measurement | Result |
| --- | --- |
| Capture duration | 60.004212 seconds |
| ADC pairs produced / received on wire | 60,046,560 / 60,046,560 |
| RAW ADC frames | 59,570 |
| ADC DMA / ETC / invariant errors | 0 / 0 / 0 |
| Wire gaps / oracle errors | 0 / 0 |
| Parser errors / host queue drops | 0 / 0 |
| Final state / pending frames | STOPPED / 0 |
| Run ID | 1 |
| Temperature | 40.965–51.404 °C |
| Physical clock diagnostics | Both passed, 600 MHz CPU |
| Settings echo and stopped readback | Match |

All eleven STATUS samples had `adc_dma_error_events=0`: before START, five
during acquisition, immediately before/after the acquisition STOP, after the
final thermal measurement, and before/after the SDK context manager's redundant
STOP while already stopped. Only one acquisition ran; the closing STOP is not
a restart or lifecycle qualification cycle. The pre-STOP observation reported
RUNNING, and the post-STOP observation reported STOPPED.

Additional requests alter command timing. This passing diagnostic therefore
cannot determine whether the original failure was timing-sensitive, whether
it occurred during acquisition or STOP, or which source path incremented the
counter. The firmware's paired-DMA service and `activeMinorPairs()` stop-time
TCD validation remain possible increment sites. Detailed DMA fault traces are
conditional on `THINGDAQ_EXPERIMENT_GPIO_RLE`; the public candidate does not
expose that private trace. No speculative firmware correction was made.

## Validation and task disposition

- Active v3 freeze: PASS, all 498 protected files.
- All 15 retained artifact hashes and sizes: PASS.
- Compatibility, negotiation, qualification and HTTP retry tests: 861 passed.
- Documentation/repository integrity: 11 tests and 1,416 subtests passed.
- Independent capture policy: no problems for the supplemental capture.
- Canonical campaign validator: expected FAIL, exit 1, 61 missing cells.

The first streaming task stays unchecked: its 56 selected cells still contain
one FAIL and 55 NOT_RUN. The full campaign additionally retains the earlier
unsupported-request PASS. The pre-upgrade SDK archive and local old-v1/v2
fixture/simulator results remain as recorded in [[protocol-v3-streaming-hardware]];
isolated physical legacy compatibility is NOT_RUN. No physical old firmware
was tested. No later lifecycle, endurance, correction or promotion task ran.
No playbook-wide halt marker was added for this ordinary qualification failure.

The next diagnosis must reproduce the error or obtain fault-site evidence
before changing the candidate or resuming the remaining matrix. Re-running
`--resume` on retained jobs follows their saved identity; it cannot clear an
existing failure. A passing supplemental capture is not a release gate waiver.

Local evidence and the resumable diagnostic driver are retained under
`.maestro/playbooks/Working/phase06-streaming-stop-diagnostic-20261024/`.
The driver requires `--resume` once its program exists. As with the original
worker, serial bytes are hashed in full but only representative frames and
bounded control samples are retained; this is not a continuous raw-byte archive.
Unstimulated input establishes no analog-accuracy or external-waveform claim.
