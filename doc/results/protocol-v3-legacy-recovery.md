---
type: report
title: Legacy cleanup correction and streaming requalification
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - qualification
  - legacy-compatibility
related:
  - '[[protocol-v3-synthetic-recovery]]'
  - '[[protocol-v3-gpio-requalification]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-migration]]'
---

# Legacy cleanup recovery and streaming: FAIL

Fresh streaming campaign: **2/56 PASS, 1 FAIL, 53 NOT_RUN**. Isolated pre-upgrade SDK: **NOT_RUN**. Whole 63-cell release campaign: **FAIL**. Lifecycle, backpressure, endurance and promotion are separate unchecked tasks.

## Correction and independent regression

The previous candidate remains FAIL at v2 ADC-only job `e942cc96-e44f-43e7-9111-501b25d2fd6e`. Its full capture passed every measurement gate, but worker context cleanup sent an extra v3 STOP after validated v2 STOP/drain. Production firmware correctly rejected the wrong dialect. See [[protocol-v3-synthetic-recovery]] for the complete retained failure and transcript.

Runner correction `ab115d1` uses the SDK's explicit `close(stop=False)` only after successful validated legacy captures. This prevents an extra STOP in the wrong protocol while preserving capture, STOP/drain, reader-close and thermal failures. Independent regression `6db6342` reproduces firmware dialect rejection and exercises actual SDK cleanup, normal v3 teardown and injected drain/close failures. Firmware, SDK, schemas, capabilities, acceptance thresholds and matrix are unchanged; only frozen worker/test inputs change.

Two clean target builds reproduce the same firmware HEX as the failed candidate. RAM1 stack reserve remains 33,024 bytes and RAM2 heap reserve 4,096 bytes. No old passing cell is imported into this fresh qualification campaign.

## Exact candidate and local checks

- Candidate: `3f075ccc6438b1e09d56663954700bd4ac39563ab023b7543713897916e00ef8`.
- HEX: `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`.
- Build: `thingdaq-e0c750868be7c5c2`; serial `20428100`.
- Source revision: `6db63422359ccc470977bf1b71a59214b667de5b`; 499 protected files verified.
- Full suite: 2687 passed, 11 skipped, 17104 subtests passed in 293.11s (0:04:53).
- Focused runtime/qualification suite: 104 passed, 6 skipped in 23.53s.
- Legacy grader: 13 passed in 0.09s.
- Documentation/layout: 11 passed, 1485 subtests passed in 2.66s.

Historical candidate/freeze archived unchanged as `firmware/soak/history/protocol-v3-candidate*-20261025-legacy-cleanup-failed.json`. All historical campaign/report hashes listed in the machine-readable report and 316 earlier evidence hashes verified. Historical passing cells are not imported.

## Retained hardware evidence

| Cell | Grade | Job |
| --- | --- | --- |
| final-identity-validation | PASS | a6bdd7b3-767d-4dee-ad41-754b5c096da8 |
| metadata-grade | PASS | 6263bfee-3b0a-4dad-bf16-ab83d9432645 |
| reset_defaults-grade | PASS | 9f567ec4-adda-49f2-a4c7-34bb5e5feeea |
| `v2-0-1` | PASS | `d54e5cb9-2efe-40b8-9ce9-1de2d3a1b87c` |
| `v2-0-2` | PASS | `cbc4e874-0f03-430b-b17d-68896d94c85b` |
| `v2-0-3` | FAIL | `aee893a8-75e7-447f-bc8b-291b2e94224f` |

## Retained combined-stream failure

Job `aee893a8-75e7-447f-bc8b-291b2e94224f` captured both streams for 60.000003 seconds, with zero frame drops, wire gaps, DMA/parser/host errors or CPU throttling, and final IDLE/zero ownership. The frozen policy rejected legacy item conservation: ADC reported 78 explicitly discarded STOP pairs; GPIO reported 3,114 explicitly discarded STOP samples. ADC captured 60,018,762 pairs and transmitted 60,018,684; GPIO transmitted 60,015,648 samples. Raw loss equals the explicit STOP tail in each stream.

Legacy `items_generated` counts complete packets, while `items_dropped` also includes unframed physical STOP tails (`statistics.cpp::refreshDataProjection`). The existing soak validator reconciles bounded tails; the v3 qualification policy omitted that legacy distinction. This original result remains FAIL. A corrected policy requires independent regression, a new freeze and fresh captures; no historical passes are imported. The controller exited and released its lock. The isolated old SDK was never submitted.

## Continuation and limits

Controller stage at report: `FAIL`. Controller/probes/logs/frozen artifacts are under `.maestro/playbooks/Working/phase06-legacy-corrected-20261025/`; fresh campaign is `.maestro/playbooks/Working/protocol-v3-qualification-legacy-fixed-20261025/`. Inspect live processes, lock and saved job state before resuming `continue_qualification.py --resume`. Follow accepted jobs through the current isolation runner; queue residence has no execution deadline. Never restart the historical failed campaign.

Legacy SDK reference is unchanged revision `3a52ead02791019fcdb0b27a8be869effc955aa2`, archive SHA-256 `6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`. Its physical probe follows the complete streaming matrix. New-SDK/old-v1/v2 results are local fixture/simulator evidence; no old firmware image is claimed physically tested. Programming reset is not power removal. Unstimulated acquisition does not measure analog accuracy, external edge fidelity, power or multi-hour continuous reliability.

Exact counters, independent grades, job identities and hashed evidence references are in [the machine-readable report](protocol-v3-legacy-recovery.json).
