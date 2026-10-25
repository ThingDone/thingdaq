---
type: report
title: Synthetic source correction and streaming requalification
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - qualification
  - synthetic-source
related:
  - '[[protocol-v3-gpio-streaming]]'
  - '[[protocol-v3-gpio-requalification]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-migration]]'
---

# Synthetic recovery and streaming: INCONCLUSIVE

Fresh streaming campaign: **0/56 PASS, 0 FAIL, 56 NOT_RUN**. Isolated pre-upgrade SDK: **NOT_RUN**. Whole 63-cell release campaign: **NOT_RUN**. Lifecycle, backpressure, endurance and promotion are separate unchecked tasks.

## Correction and independent regression

The previous candidate remains FAIL at fallback job `56729135-cdc1-4883-9be7-616f9dde45b1`: its incrementing synthetic GPIO source could not produce RLE. Firmware v3 now implements the existing SDK validator/simulator patterns: alternating zero/high-transition GPIO frames, and four ADC edge pairs per 2,048-pair ramp cycle. Legacy v1/v2 generation and physical acquisition are unchanged. Production correction `70689d9` and separate regressions `75ca24c` / `6eda739` are retained.

The regression drives the production runtime, generator, codecs and USB, checks every emitted block using the SDK validator, and derives fallback coverage from those real frames. The previous generator fails for both widths. The rig now independently checks source bytes on one full frame per encoding per stream, retaining those frames. Framing/checksum/sequence/conservation checks cover every frame; source-pattern proof is bounded sampling, not an all-payload replay of the full capture. Acceptance still requires both RLE and RAW.

The initial target build failed the unchanged 32 KiB stack gate after crossing an ITCM bank boundary (only 256 bytes remained). Commit `1a1fc95` places the synthetic fill routines in flash using the existing section pattern. The failed build log is retained. Two subsequent clean builds are byte-identical and pass: RAM1 stack reserve 33,024 bytes; RAM2 heap reserve 4,096 bytes.

## Exact candidate and local checks

- Candidate: `7bb97a0aa37b9d2c3d00b38ed322accfacc97143af063ad9160ecb28865265b8`.
- HEX: `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`.
- Build: `thingdaq-e0c750868be7c5c2`; serial `20428100`.
- Source revision: `6eda739ba1061807d579d016c1f0467963ab1a44`; 499 protected files verified.
- Full suite: 2681 passed, 11 skipped, 17098 subtests passed in 291.50s (0:04:51).
- Focused runtime/qualification suite: 126 passed, 6 skipped, 27 subtests passed in 40.80s.
- Legacy grader: 13 passed in 0.08s.
- Documentation/layout: 11 passed, 1478 subtests passed in 2.69s.

Historical candidate/freeze archived unchanged as `firmware/soak/history/protocol-v3-candidate*-20261025-synthetic-failed.json`. All 462 failed-campaign/report hashes and 316 earlier evidence hashes verified. Historical passing cells are not imported.

## Retained hardware evidence

| Cell | Grade | Job |
| --- | --- | --- |
| final-identity-validation | NOT_RUN |  |
| metadata-grade | NOT_RUN |  |
| reset_defaults-grade | NOT_RUN |  |

## Continuation and limits

Controller stage at report: `FROZEN`. Controller/probes/logs/frozen artifacts are under `.maestro/playbooks/Working/phase06-synthetic-corrected-20261025/`; fresh campaign is `.maestro/playbooks/Working/protocol-v3-qualification-synthetic-fixed-20261025/`. Inspect live processes, lock and saved job state before resuming `continue_qualification.py --resume`. Follow accepted jobs through the current isolation runner; queue residence has no execution deadline. Never restart the historical failed campaign.

Legacy SDK reference is unchanged revision `3a52ead02791019fcdb0b27a8be869effc955aa2`, archive SHA-256 `6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`. Its physical probe follows the complete streaming matrix. New-SDK/old-v1/v2 results are local fixture/simulator evidence; no old firmware image is claimed physically tested. Programming reset is not power removal. Unstimulated acquisition does not measure analog accuracy, external edge fidelity, power or multi-hour continuous reliability.

Exact counters, independent grades, job identities and hashed evidence references are in [the machine-readable report](protocol-v3-synthetic-recovery.json).
