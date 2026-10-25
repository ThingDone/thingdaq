---
type: report
title: Independent regression coverage for qualification host CPU admission
created: 2026-10-25
tags:
  - protocol-v3
  - qualification
  - regression
  - host-backpressure
related:
  - '[[protocol-v3-gpio-overrun-diagnosis]]'
  - '[[protocol-v3-gpio-overrun-correction]]'
  - '[[protocol-v3-dma-recovery]]'
---

# Regression milestone passed

Permanent tests reproduce the missing CPU precondition identified after GPIO
loss in job `322b4ac0-309d-4d61-a625-d4ce41cbf104`. They extend the existing
qualification and rig retry harnesses. Production firmware, SDK, runner and
acceptance policy are unchanged in this regression commit.

The responsible path and hardware evidence remain in
[[protocol-v3-gpio-overrun-diagnosis]] and
[[protocol-v3-gpio-overrun-correction]]. These tests verify the correction;
they do not replace hardware qualification or erase the original FAIL.

## Before/after evidence

The same permanent assertions were executed against source extracted with
`git show cbbf330:<path>` and against corrected production commit `082228f`.
The retained pytest plugin loads only the historical worker and runner modules;
it neither checks out another tree nor executes a rig client.

| Regression | Before correction | After correction |
| --- | --- | --- |
| Half-core, insufficient affinity, missing setup: reject before serial opens | 3 FAIL | 3 PASS |
| Delayed allocation: wait before opening serial | FAIL | PASS |
| Adequate two-core allocation: admit immediately | PASS | PASS |
| Saved PASS with missing/half-core/insufficient-affinity readback: reject | 3 FAIL | 3 PASS |

Thus the before run has **7 failed / 1 passed**, and all eight corresponding
checks pass after correction. Four additional new tests pass: exact accepted-job
container selection with retry and resume revalidation, ambiguous-container
rejection, failed quota readback, and standalone bundled telemetry execution.
The emitted SSH program executes against fake Docker objects; no SSH is sent.

The existing queue/5xx regression now checks the active callback too. All four
queue representations survive over 2,300 seconds of simulated queue/retry time
under a two-second execution budget. Provisioning runs only for the active job,
never during queue residence or after completion.

## Validation and retained evidence

- Affected qualification, rig HTTP, isolation, packet ownership, USB transport,
  codec, freeze, SDK compatibility, stream consumer and reader suites:
  **943 passed + 28 subtests passed**.
- Final focused run: **16 passed**, including four extended queue cases.
- Existing independent sample conservation, checksum, gap rejection and
  production packet eviction tests remain intact and passed in the affected set.
- Ruff lint/format and Git whitespace checks pass.
- Documentation/layout checks: **11 passed + 1,455 subtests passed**.
- All 23 locally referenced evidence files in the correction report retain
  their recorded SHA-256 hashes.

Logs, extracted baseline sources, and the baseline-loader plugin are retained
under `.maestro/playbooks/Working/phase06-gpio-regression-20261025/`.
[Machine-readable results](protocol-v3-gpio-overrun-regression.json) record
commands, outcomes, source identities and file hashes. Run the focused tests
from the repository root with:

```bash
PYTHONPATH=.:daq_api/src .venv/bin/python -m pytest -q \
  firmware/tests/test_protocol_v3_qualification.py \
  firmware/tests/test_rig_http_retry.py \
  -k 'cpu_admission or cpu_allocation_targets or bundled_resource or worker_cpu_readback or queue_and_separate'
```

No new rig job was submitted. Canonical streaming remains **36 PASS / 1 FAIL /
19 NOT_RUN** on the historical candidate. The changed runner inputs from the
production correction still require a new freeze and candidate requalification;
that next playbook task remains unchecked. This report makes no new hardware,
analog accuracy, external waveform timing, or endurance claim.
