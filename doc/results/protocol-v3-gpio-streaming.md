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

The exact corrected candidate has **30/56 streaming cells PASS**,
**0 FAIL**, and **26 NOT_RUN**. Isolated pre-upgrade
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
| `smoke-010101030104000800010c0040420f0040420f00` | PASS | `54b2fbb9-a739-4d18-828c-0059f49df41f` | 60.01601212937385 | 60049584 | 0 |
| `smoke-010101030104000801000c0040420f0040420f00` | PASS | `6251239d-8c69-4b27-9a73-bd82846e3bce` | 60.00374897290021 | 60025392 | 0 |
| `smoke-010101030104000801010c0040420f0040420f00` | PASS | `09bb7f93-a512-449a-940d-f5779e388bc1` | 60.016408500261605 | 60049584 | 0 |
| `smoke-010101030104011000000c0040420f0040420f00` | PASS | `24cf996a-db25-4405-8bd7-dc01917330fd` | 60.00477451086044 | 60025392 | 0 |
| `smoke-010101030104011000010c0040420f0040420f00` | PASS | `519f37ad-1980-48f9-9613-2fd2624bdbad` | 60.015503691509366 | 60049584 | 0 |
| `smoke-010101030104011001000c0040420f0040420f00` | PASS | `33259981-5918-494b-8495-8fe31d5a29cf` | 60.00414601992816 | 60028416 | 0 |
| `smoke-010101030104011001010c0040420f0040420f00` | PASS | `3da1d107-53da-4c27-b1a9-9f81c52b289b` | 60.01611482538283 | 60049584 | 0 |
| `smoke-020001030104000800000c0040420f0040420f00` | PASS | `11ebb9c2-4980-4ddf-b812-b378ec2b3f68` | 60.01664655096829 | 0 | 60072768 |
| `smoke-020001030104000800010c0040420f0040420f00` | PASS | `f28e549c-4027-4242-94e8-99cd7afa8d47` | 60.023641287349164 | 0 | 60080832 |
| `smoke-020001030104000801000c0040420f0040420f00` | PASS | `732176c4-d25f-47ec-a781-e4a369670e90` | 60.02902282308787 | 0 | 60084864 |
| `smoke-020001030104000801010c0040420f0040420f00` | PASS | `074e325b-fa19-4c6c-8416-bd25b11d8d0d` | 60.01465371996164 | 0 | 60068736 |
| `smoke-020001030104011000000c0040420f0040420f00` | PASS | `7c314a0d-116f-4077-a25c-2fe502ffd384` | 60.021268176846206 | 0 | 60060672 |
| `smoke-020001030104011000010c0040420f0040420f00` | PASS | `5eaaa10e-3973-4fb4-b280-45c4b128936f` | 60.02093751449138 | 0 | 60056640 |
| `smoke-020001030104011001000c0040420f0040420f00` | PASS | `313d3eb0-ae01-45b0-b0ae-3d13c6e0d9d4` | 60.04091286379844 | 0 | 60098976 |
| `smoke-020001030104011001010c0040420f0040420f00` | PASS | `77189e31-6ffa-4c85-aa77-b42384cca133` | 60.027627564035356 | 0 | 60084864 |
| `smoke-020101030104000800000c0040420f0040420f00` | PASS | `6560eab6-edcd-4a81-9548-7f209558f90c` | 60.05461968481541 | 0 | 60109056 |
| `smoke-020101030104000800010c0040420f0040420f00` | PASS | `da0a757c-051d-413d-8d1c-a70431592170` | 60.00870071165264 | 0 | 60060672 |
| `smoke-020101030104000801000c0040420f0040420f00` | PASS | `18f79d8d-e2d6-4e9d-a15e-3dc9d191cb11` | 60.04000353626907 | 0 | 60092928 |
| `smoke-020101030104000801010c0040420f0040420f00` | PASS | `19b37905-5ac9-4f4e-8ca5-c381efdc2ccd` | 60.005961207672954 | 0 | 60060672 |
| `smoke-020101030104011000000c0040420f0040420f00` | PASS | `907a038e-edfb-4550-b2c5-7954517b4c9a` | 60.021753310225904 | 0 | 60058656 |
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
