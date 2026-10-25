---
type: report
title: Corrected-candidate streaming and compatibility qualification
created: 2026-10-25
tags:
  - protocol-v3
  - qualification
  - hardware
  - compatibility
related:
  - '[[protocol-v3-gpio-requalification]]'
  - '[[protocol-v3-gpio-overrun-regression]]'
  - '[[protocol-v3-streaming-hardware]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-migration]]'
---

# Streaming and compatibility: INCONCLUSIVE

The exact corrected candidate has **10/56 streaming cells PASS**,
**0 FAIL**, and **46 NOT_RUN**. Isolated pre-upgrade
SDK physical compatibility: **NOT_RUN**. The unsupported-request cell
is separate. Full release qualification remains **INCONCLUSIVE**;
remaining lifecycle, backpressure, endurance, grading and promotion tasks have
not been credited here.

## Frozen identity

- Candidate: `bdb695e98e472a26d575f0a617d2deb6f1a5a500ce5771789c29dac431918d51`.
- Firmware HEX: `f29d05970b5b49381f4efcd80e2b948e72a41b89a32edbfce6ca00c5fab8fdbf`.
- Build: `thingdaq-92950ec5f7156586`; Teensy 4.0 serial `20428100`.
- Freeze verification: PASS; all 316 historical evidence files unchanged.
- Firmware, SDK, policy, durations, matrix and acceptance gates unchanged.
- Independent terminal-evidence replay uses the Phase 05 validator. Earlier
  candidates' failures and passing cells remain historical and are not imported.

## Validation and compatibility scope

Local checks: **1284 passed, 284 subtests passed in 47.64s**. Independent legacy evidence grader: **13 passed in 0.08s** (valid control plus 12 injected faults). These cover new-SDK/old-v1/old-v2 fixtures and
simulator peers, codecs/public APIs, legacy firmware session unit tests and
rig/qualification/resource/freeze checks. They do not constitute physical old
firmware testing. The original pre-upgrade SDK archive is revision
`3a52ead02791019fcdb0b27a8be869effc955aa2`, SHA-256
`6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`.
Its separate physical probe is serialized after the streaming matrix and runs
five 60-second v2 RAW cases with same-boot restart, without upgrading that SDK.

The frozen matrix covers advertised RAW/default-codec combinations, GPIO8 and
GPIO16, ADC/GPIO/combined, hardware and deterministic synthetic sources, and
compressible/high-transition GPIO fallback. Completed cells retain independent
wire checks, production SDK decode/accounting, timing, run IDs, sample
conservation, health, temperatures and encoding counters. Every job requires
verified two-core quota/affinity before opening serial. The machine-readable
report preserves counters and per-cell grades; raw frames remain in the
hash-linked original result files.

## Completed streaming cells

| Cell | Grade | Job | Capture seconds | ADC pairs | GPIO samples |
| --- | --- | --- | ---: | ---: | ---: |
| `smoke-010001030104000800000c0040420f0040420f00` | PASS | `eb1cbc1f-6dea-4cdf-a84a-241c1f46ad86` | 60.00171210616827 | 60027408 | 0 |
| `smoke-010001030104000800010c0040420f0040420f00` | PASS | `ca4aae0c-d0fa-4aa9-9afa-dfedac8fe2a8` | 60.00181107688695 | 60031440 | 0 |
| `smoke-010001030104000801000c0040420f0040420f00` | PASS | `6ed0a5ba-b183-471d-ad58-757af2310e34` | 60.00972013361752 | 60030432 | 0 |
| `smoke-010001030104000801010c0040420f0040420f00` | PASS | `b5ebfde7-fb76-4962-8497-7946226834c8` | 60.01581954583526 | 60051600 | 0 |
| `smoke-010001030104011000000c0040420f0040420f00` | PASS | `0e8f556c-63b9-407d-9b72-6a300329f849` | 60.00139211118221 | 60027408 | 0 |
| `smoke-010001030104011000010c0040420f0040420f00` | PASS | `4bb79d7f-ef44-4fb0-9012-aa0e8d185875` | 60.01135392207652 | 60047568 | 0 |
| `smoke-010001030104011001000c0040420f0040420f00` | PASS | `f2ad7544-dd7c-4134-920a-124f811acf51` | 60.0030430033803 | 60030432 | 0 |
| `smoke-010001030104011001010c0040420f0040420f00` | PASS | `e029fa9f-8f1e-4e19-9212-54c6ddc8dfe6` | 60.01783865503967 | 60051600 | 0 |
| `smoke-010101030104000800000c0040420f0040420f00` | PASS | `8676f37b-0482-400a-9a4b-99862c728e8a` | 60.00373372063041 | 60028416 | 0 |
| `smoke-030001030104011000000c0040420f0040420f00` | PASS | `b5b41941-6b73-419b-92af-88be8f08613d` | 60.00000737980008 | 60017328 | 60016320 |

## Retention and continuation

[Machine-readable evidence](protocol-v3-gpio-streaming.json) contains terminal
job IDs, raw-result references, immutable evidence hashes and replay results.
Campaign: `.maestro/playbooks/Working/protocol-v3-qualification-gpio-fixed-20261025/`.
Controller/probe/logs: `.maestro/playbooks/Working/phase06-gpio-streaming-20261025/`.
Inspect the controller lock/process and retained job before using `--resume`.
All rig HTTP requests use `run_input_isolation.py`, including saved-tag
reconciliation, queue waits and 30-second 5xx retries. Queue residence has no
execution deadline. Do not run historical raw-evidence clients.

No calibrated external stimulus was connected. No analog accuracy, external
waveform fidelity, external power or multi-hour continuous reliability claim is
made. Programming resets are not physical power-removal tests.
