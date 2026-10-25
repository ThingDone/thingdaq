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

Fresh streaming campaign: **0/55 PASS, 0 FAIL, 55 NOT_RUN**. Isolated pre-upgrade SDK: **NOT_RUN**. Whole 62-cell release campaign: **NOT_RUN**. Lifecycle, backpressure, endurance and promotion are separate unchecked tasks.

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
- Legacy grader: 20 passed in 0.19s.
- Documentation/layout: 11 passed, 1499 subtests passed in 2.63s.

Historical candidate/freeze archived unchanged as `firmware/soak/history/protocol-v3-candidate*-20261025-legacy-matrix-failed.json`. All historical campaign/report hashes listed in the machine-readable report and 316 earlier evidence hashes verified. Historical passing cells are not imported.

## Retained hardware evidence

| Cell | Grade | Job |
| --- | --- | --- |
| final-identity-validation | NOT_RUN |  |
| metadata-grade | NOT_RUN |  |
| reset_defaults-grade | NOT_RUN |  |

## Continuation and limits

Controller stage at report: `IDENTITY`. Controller/probes/logs/frozen artifacts are under `.maestro/playbooks/Working/phase06-legacy-matrix-corrected-20261025/`; fresh campaign is `.maestro/playbooks/Working/protocol-v3-qualification-legacy-matrix-fixed-20261025/`. Inspect live processes, lock and saved job state before resuming `continue_qualification.py --resume`. Follow accepted jobs through the current isolation runner; queue residence has no execution deadline. Never restart the historical failed campaign.

Legacy SDK reference is unchanged revision `3a52ead02791019fcdb0b27a8be869effc955aa2`, archive SHA-256 `6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`. Its physical probe follows the five fresh v2 cells, before the remaining streaming matrix. New-SDK/old-v1/v2 results are local fixture/simulator evidence; no old firmware image is claimed physically tested. Programming reset is not power removal. Unstimulated acquisition does not measure analog accuracy, external edge fidelity, power or multi-hour continuous reliability.

Exact counters, independent grades, job identities and hashed evidence references are in [the machine-readable report](protocol-v3-legacy-matrix-recovery.json).
