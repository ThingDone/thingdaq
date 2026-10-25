---
type: report
title: Legacy STOP-tail accounting correction and streaming requalification
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

# Legacy STOP-tail recovery and streaming: FAIL

Fresh streaming campaign: **3/56 PASS, 1 FAIL, 52 NOT_RUN**. Isolated pre-upgrade SDK: **NOT_RUN**. Whole 63-cell release campaign: **FAIL**. Lifecycle, backpressure, endurance and promotion are separate unchecked tasks.

## Correction and independent regression

The previous candidate remains FAIL at combined v2 job `aee893a8-75e7-447f-bc8b-291b2e94224f`. Its full capture had zero frame drops/gaps or acquisition errors, but the frozen policy omitted explicit unframed STOP tails from legacy item conservation. See [[protocol-v3-legacy-recovery]] for retained failure counters.

The corrected policy reconciles complete-packet generated counts with bounded explicit STOP tails and raw-loss, captured/delivered and incomplete-buffer diagnostics. Frame drops, gaps and unexplained raw loss still fail. The isolated unchanged old-SDK probe bundles the same pure policy helper and is independently replayed. Regression accepts the retained measured tail and rejects altered loss/accounting/bounds. Firmware, SDK, schemas, capabilities and matrix are unchanged; frozen policy/test inputs change.

Two clean target builds reproduce the same firmware HEX as the failed candidate. RAM1 stack reserve remains 33,024 bytes and RAM2 heap reserve 4,096 bytes. No old passing cell is imported into this fresh qualification campaign.

## Exact candidate and local checks

- Candidate: `16f11b967bbf5c59a651adaa196a7f4ebd556b6347b099833588ce546bfcefd5`.
- HEX: `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`.
- Build: `thingdaq-e0c750868be7c5c2`; serial `20428100`.
- Source revision: `13ece93db8658342462becb6f3160fabf09a0274`; 500 protected files verified.
- Full suite: 2705 passed, 11 skipped, 17111 subtests passed in 292.00s (0:04:52).
- Focused runtime/qualification suite: 122 passed, 6 skipped in 23.33s.
- Legacy grader: 20 passed in 0.19s.
- Documentation/layout: 11 passed, 1492 subtests passed in 2.68s.

Historical candidate/freeze archived unchanged as `firmware/soak/history/protocol-v3-candidate*-20261025-legacy-tail-failed.json`. All historical campaign/report hashes listed in the machine-readable report and 316 earlier evidence hashes verified. Historical passing cells are not imported.

## Retained hardware evidence

| Cell | Grade | Job |
| --- | --- | --- |
| final-identity-validation | PASS | 1151bcbe-a450-4df9-a900-a7d114793511 |
| metadata-grade | PASS | 7886805e-b596-47c9-a5bb-9272818e27f6 |
| reset_defaults-grade | PASS | 793c3ed0-ba28-4a47-ac7d-04a80accd190 |
| `v2-0-1` | PASS | `a157c8f5-3264-4e81-8f48-9fa920a831da` |
| `v2-0-2` | PASS | `f85a9e79-1aa6-4e1e-b2ff-5f9d3eac6d8d` |
| `v2-0-3` | PASS | `3d530523-42eb-4f79-829b-1ca51b94e334` |
| `v2-1-1` | FAIL | `10d01714-118a-4f4b-bdf5-fe74b48e6b1f` |

## Invalid legacy matrix cell retained

After three fresh v2 passes, job `10d01714-118a-4f4b-bdf5-fe74b48e6b1f` failed before acquisition with `ValueError: auxiliary INPUT mode requires the GPIO stream`. The v2 specification explicitly requires GPIO for auxiliary INPUT and ADC-only with DISABLED; the legacy matrix incorrectly included v3's ADC-only/INPUT combination. This is a matrix construction defect, not an acquisition measurement. All advertised v3 combinations remain required. The controller exited; the isolated old SDK was not submitted. This original candidate remains FAIL; corrected matrix inputs require a new freeze and fresh evidence.

## Continuation and limits

Controller stage at report: `FAIL`. Controller/probes/logs/frozen artifacts are under `.maestro/playbooks/Working/phase06-legacy-tail-corrected-20261025/`; fresh campaign is `.maestro/playbooks/Working/protocol-v3-qualification-legacy-tail-fixed-20261025/`. Inspect live processes, lock and saved job state before resuming `continue_qualification.py --resume`. Follow accepted jobs through the current isolation runner; queue residence has no execution deadline. Never restart the historical failed campaign.

Legacy SDK reference is unchanged revision `3a52ead02791019fcdb0b27a8be869effc955aa2`, archive SHA-256 `6f086090943069ed228b529871a7fe03bbccb2e69c611464a31fa80f340e4e20`. Its physical probe follows the six fresh v2 cells, before the remaining streaming matrix. New-SDK/old-v1/v2 results are local fixture/simulator evidence; no old firmware image is claimed physically tested. Programming reset is not power removal. Unstimulated acquisition does not measure analog accuracy, external edge fidelity, power or multi-hour continuous reliability.

Exact counters, independent grades, job identities and hashed evidence references are in [the machine-readable report](protocol-v3-legacy-tail-recovery.json).
