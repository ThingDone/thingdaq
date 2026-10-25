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

Fresh streaming campaign: **30/56 PASS, 0 FAIL, 26 NOT_RUN**. Isolated pre-upgrade SDK: **NOT_RUN**. Whole 63-cell release campaign: **INCONCLUSIVE**. Lifecycle, backpressure, endurance and promotion are separate unchecked tasks.

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
| final-identity-validation | PASS | aea0a3af-125c-4f51-8fad-792723a6f8c2 |
| metadata-grade | PASS | 65c4288b-453f-4183-9c5e-2a077c475e6b |
| reset_defaults-grade | PASS | 73bc3727-a3fb-4caf-b536-f002872b5c81 |
| `fallback-0` | PASS | `f6353b13-b675-488a-8c70-a0f1a10a004e` |
| `fallback-1` | PASS | `cc0b36bb-befc-415c-8cea-d50057f9d063` |
| `smoke-010001030104000800000c0040420f0040420f00` | PASS | `57c03826-3408-4a5f-93d2-67b47a2989df` |
| `smoke-010001030104000800010c0040420f0040420f00` | PASS | `76f292f0-b0a0-4a84-9056-3560123120ab` |
| `smoke-010001030104000801000c0040420f0040420f00` | PASS | `90f6fe90-5f5d-49d9-88b5-7b9c9a6d6e61` |
| `smoke-010001030104000801010c0040420f0040420f00` | PASS | `35612a17-5bff-4eda-9498-862221d75a9a` |
| `smoke-010001030104011000000c0040420f0040420f00` | PASS | `8802773e-3398-4793-b611-710326214d51` |
| `smoke-010001030104011000010c0040420f0040420f00` | PASS | `1cafbfb4-4421-45a8-8362-35e4a9f495bd` |
| `smoke-010001030104011001000c0040420f0040420f00` | PASS | `0bb8b4e7-c8b0-4677-9815-a6702851e62a` |
| `smoke-010001030104011001010c0040420f0040420f00` | PASS | `d9ce3e36-128b-417c-bc9e-d150286e8bbc` |
| `smoke-010101030104000800000c0040420f0040420f00` | PASS | `223adebb-76c4-4e29-a96b-3627b36334bf` |
| `smoke-010101030104000800010c0040420f0040420f00` | PASS | `25a03598-ae6e-49df-95b9-95c80e4e393c` |
| `smoke-010101030104000801000c0040420f0040420f00` | PASS | `de1eab37-ab72-4694-ad09-8c3352be6b1f` |
| `smoke-010101030104000801010c0040420f0040420f00` | PASS | `1cfb0fed-2c12-47b1-afc5-d9fd97d7b8a3` |
| `smoke-010101030104011000000c0040420f0040420f00` | PASS | `a5511394-43ea-486c-929e-d8df2b48cd85` |
| `smoke-010101030104011000010c0040420f0040420f00` | PASS | `cba3bbee-4a68-487f-8c51-35ab99b66354` |
| `smoke-010101030104011001000c0040420f0040420f00` | PASS | `942f8dec-cd9b-4f26-91b3-df9282187698` |
| `smoke-010101030104011001010c0040420f0040420f00` | PASS | `f19f9182-670a-4399-9607-c843a698c40e` |
| `smoke-020001030104000800000c0040420f0040420f00` | PASS | `3953fd45-baff-4fe7-b5ed-13a35a58838a` |
| `smoke-020001030104000800010c0040420f0040420f00` | PASS | `3a48199c-53c4-4ad5-b398-ba04205132d8` |
| `smoke-020001030104000801000c0040420f0040420f00` | PASS | `5ec7ddc4-e2e9-4944-872a-1b0f83669a1b` |
| `smoke-020001030104000801010c0040420f0040420f00` | PASS | `d10c8201-4b15-480a-9b90-8ef24c56603a` |
| `smoke-020001030104011000000c0040420f0040420f00` | PASS | `7b338f8b-c257-498b-9ef0-5dfe1c13b0ef` |
| `smoke-020001030104011000010c0040420f0040420f00` | PASS | `ee9de570-dfd8-48da-b76f-7a7d7f03fb50` |
| `smoke-020001030104011001000c0040420f0040420f00` | PASS | `ccafb759-a24f-4110-958a-fda37152a9b0` |
| `smoke-020001030104011001010c0040420f0040420f00` | PASS | `759ca45c-58a4-4f28-a0d6-c3c0fa26484c` |
| `smoke-020101030104000800000c0040420f0040420f00` | PASS | `7972de50-4d37-4e51-8cf9-11093eb13896` |
| `smoke-020101030104000800010c0040420f0040420f00` | PASS | `efd9c276-ef56-49a2-991d-e75beb9b048b` |
| `smoke-020101030104000801000c0040420f0040420f00` | PASS | `7eb5af9b-161f-4430-bce6-da8e6a47a17f` |
| `smoke-030001030104011000000c0040420f0040420f00` | PASS | `c06338d5-4c0e-4e07-94b9-8f7f958fa796` |

## Continuation and limits

Controller stage at report: `STREAMING_MATRIX`. Controller/probes/logs/frozen artifacts are under `.maestro/playbooks/Working/phase06-synthetic-corrected-20261025/`; fresh campaign is `.maestro/playbooks/Working/protocol-v3-qualification-synthetic-fixed-20261025/`. Inspect live processes, lock and saved job state before resuming `continue_qualification.py --resume`. Follow accepted jobs through the current isolation runner; queue residence has no execution deadline. Never restart the historical failed campaign.

Legacy SDK reference is unchanged revision `3a52ead02791019fcdb0b27a8be869effc955aa2`, archive SHA-256 `6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`. Its physical probe follows the complete streaming matrix. New-SDK/old-v1/v2 results are local fixture/simulator evidence; no old firmware image is claimed physically tested. Programming reset is not power removal. Unstimulated acquisition does not measure analog accuracy, external edge fidelity, power or multi-hour continuous reliability.

Exact counters, independent grades, job identities and hashed evidence references are in [the machine-readable report](protocol-v3-synthetic-recovery.json).
