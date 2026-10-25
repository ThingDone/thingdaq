---
type: report
title: Legacy compatibility matrix correction and streaming requalification
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - qualification
  - legacy-compatibility
related:
  - '[[protocol-v3-legacy-recovery]]'
  - '[[protocol-v3-gpio-requalification]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-migration]]'
---

# Legacy matrix recovery and streaming: INCONCLUSIVE

Fresh streaming campaign: **30/55 PASS, 0 FAIL, 25 NOT_RUN**. Isolated pre-upgrade SDK: **PASS**. Whole 62-cell release campaign: **INCONCLUSIVE**. Lifecycle, backpressure, endurance and promotion are separate unchecked tasks.

## Correction and independent regression

The previous candidate remains FAIL at v2 ADC-only/INPUT job `10d01714-118a-4f4b-bdf5-fe74b48e6b1f`. It failed SDK configuration validation before acquisition. See [[protocol-v3-legacy-tail-recovery]] for the original failure; the preceding three legacy cases passed, including explicit bounded physical STOP-tail reconciliation.

The v2 specification and both old/current SDKs require GPIO when auxiliary mode is INPUT. The matrix incorrectly inherited all six v3 stream/width tuples. It now contains the five documented v2 configurations; all 48 advertised v3 tuples remain. Independent regression constructs every legacy configuration through the real SDK and exercises all five on the production C++ runtime. The isolated unchanged SDK also checks those five cases. Firmware, SDK, schemas and capabilities are unchanged. Streaming has 55 valid cells; the complete release campaign has 62.

Two clean target builds reproduce the same firmware HEX as the failed candidate. RAM1 stack reserve remains 33,024 bytes and RAM2 heap reserve 4,096 bytes. No old passing cell is imported into this fresh qualification campaign.

## Exact candidate and local checks

- Candidate: `14c14a82912a95482bb9146abb06e310b3d7f8c24bec37ef2274d13d4b9d4682`.
- HEX: `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`.
- Build: `thingdaq-e0c750868be7c5c2`; serial `20428100`.
- Source revision: `94144fd32b35968c3f650d2c5927cfefd4e88343`; 500 protected files verified.
- Full suite: 2716 passed, 11 skipped, 17118 subtests passed in 289.45s (0:04:49).
- Focused runtime/qualification suite: 133 passed, 6 skipped in 23.27s.
- Legacy grader: 21 passed in 0.19s.
- Documentation/layout: 11 passed, 1499 subtests passed in 2.63s.

Historical candidate/freeze archived unchanged as `firmware/soak/history/protocol-v3-candidate*-20261025-legacy-matrix-failed.json`. All historical campaign/report hashes listed in the machine-readable report and 316 earlier evidence hashes verified. Historical passing cells are not imported.

## Retained hardware evidence

| Cell | Grade | Job |
| --- | --- | --- |
| final-identity-validation | PASS | 4f199238-40ce-4ed3-b437-711b08360496 |
| metadata-grade | PASS | de0a4887-caa0-47e9-be1f-44790ce063d5 |
| reset_defaults-grade | PASS | ba4acb88-058d-4298-b335-ca02c672a8b0 |
| `fallback-0` | PASS | `9d37baf6-4740-4494-8be2-170ef9a5bca3` |
| `fallback-1` | PASS | `c2b79b4f-41f5-4cbf-9b85-f0f29cd69627` |
| `smoke-010001030104000800000c0040420f0040420f00` | PASS | `0c3f3c69-a751-4c43-9228-88e7ea08d1fc` |
| `smoke-010001030104000800010c0040420f0040420f00` | PASS | `3d91f4e1-c6f6-42e7-98a4-bd4da4c575ed` |
| `smoke-010001030104000801000c0040420f0040420f00` | PASS | `11bb30be-0471-4fc9-8d1a-cb0ea5b362ea` |
| `smoke-010001030104000801010c0040420f0040420f00` | PASS | `c7ccd36f-3f09-4c22-9657-fe42e72d7466` |
| `smoke-010001030104011000000c0040420f0040420f00` | PASS | `df334a57-9339-4270-9f2c-e71f2f9a61b5` |
| `smoke-010001030104011000010c0040420f0040420f00` | PASS | `da804445-1c64-4609-a44f-36e7c9370fef` |
| `smoke-010001030104011001000c0040420f0040420f00` | PASS | `4b5da522-35f3-4599-928b-395552b002e0` |
| `smoke-010001030104011001010c0040420f0040420f00` | PASS | `016bcd46-f390-41c4-9f6d-aceadf286b8b` |
| `smoke-010101030104000800000c0040420f0040420f00` | PASS | `f78635c8-5e3e-4925-9506-76cc404533a2` |
| `smoke-010101030104000800010c0040420f0040420f00` | PASS | `a25a516d-9894-4a70-b383-f8740627c3a5` |
| `smoke-010101030104000801000c0040420f0040420f00` | PASS | `425625fc-6f9c-433f-8672-9aa28b96b5c8` |
| `smoke-010101030104000801010c0040420f0040420f00` | PASS | `23594d26-b662-4db2-a7f5-82494140cc3c` |
| `smoke-010101030104011000000c0040420f0040420f00` | PASS | `9e7329bc-0460-4e5b-9b44-3f7b1d50ebd3` |
| `smoke-010101030104011000010c0040420f0040420f00` | PASS | `9dc5bcd8-b595-44c1-8ed8-120783115f0c` |
| `smoke-010101030104011001000c0040420f0040420f00` | PASS | `5e1acaac-fad9-4db2-94e5-b4ac320df400` |
| `smoke-010101030104011001010c0040420f0040420f00` | PASS | `ec8fccfe-817b-4359-a49b-d0ac3c18986b` |
| `smoke-020001030104000800000c0040420f0040420f00` | PASS | `189c967d-4702-4000-b4e0-9c50416da449` |
| `smoke-020001030104000800010c0040420f0040420f00` | PASS | `ce487728-24ec-4012-be8e-cee84b40adf8` |
| `smoke-020001030104000801000c0040420f0040420f00` | PASS | `aa710d55-250e-4c92-9ecc-9adb38b3d46d` |
| `smoke-020001030104000801010c0040420f0040420f00` | PASS | `4a23a364-b53e-47e7-ae55-7f6895a001ed` |
| `smoke-020001030104011000000c0040420f0040420f00` | PASS | `de302c94-cafa-4625-9202-d6ff25ea51d8` |
| `smoke-020001030104011000010c0040420f0040420f00` | PASS | `de1619b7-beb1-444f-9ec2-c5f7bfac160a` |
| `smoke-030001030104011000000c0040420f0040420f00` | PASS | `d1093f61-3b29-48ea-a8f9-eafa3af55892` |
| `v2-0-1` | PASS | `a70e9f3c-88da-40d4-abc3-7572fc7cd66d` |
| `v2-0-2` | PASS | `338c2782-998e-4b63-a64a-f5e53007bc48` |
| `v2-0-3` | PASS | `7966be1b-dae9-4941-8cef-2df5a4e9acdf` |
| `v2-1-2` | PASS | `3166abbe-e063-4fe9-9dbd-eb78055044b5` |
| `v2-1-3` | PASS | `f74bb5ac-6bfd-4ac2-9045-3fa3662024f8` |

## Continuation and limits

Controller stage at report: `STREAMING_MATRIX`. Controller/probes/logs/frozen artifacts are under `.maestro/playbooks/Working/phase06-legacy-matrix-corrected-20261025/`; fresh campaign is `.maestro/playbooks/Working/protocol-v3-qualification-legacy-matrix-fixed-20261025/`. Inspect live processes, lock and saved job state before resuming `continue_qualification.py --resume`. Follow accepted jobs through the current isolation runner; queue residence has no execution deadline. Never restart the historical failed campaign.

Legacy SDK reference is unchanged revision `3a52ead02791019fcdb0b27a8be869effc955aa2`, archive SHA-256 `6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`. Its physical probe follows the five fresh v2 cells, before the remaining streaming matrix. New-SDK/old-v1/v2 results are local fixture/simulator evidence; no old firmware image is claimed physically tested. Programming reset is not power removal. Unstimulated acquisition does not measure analog accuracy, external edge fidelity, power or multi-hour continuous reliability.

Exact counters, independent grades, job identities and hashed evidence references are in [the machine-readable report](protocol-v3-legacy-matrix-recovery.json).
