---
type: report
title: Protocol v3 lifecycle, backpressure and endurance qualification
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - endurance
related:
  - '[[protocol-v3-legacy-matrix-recovery]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-clock-control]]'
---

# Lifecycle hardware qualification: INCONCLUSIVE

Exact candidate `14c14a82912a95482bb9146abb06e310b3d7f8c24bec37ef2274d13d4b9d4682`, firmware `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`, build `thingdaq-e0c750868be7c5c2`, serial `20428100`. Six selected cells: **3 PASS / 0 FAIL / 1 INCONCLUSIVE / 2 NOT_RUN**. Release promotion remains a separate task.

| Cell | Grade | Job | Captures | Peak °C |
| --- | --- | --- | --- | --- |
| same-boot-20 | PASS | `409c3d90-eb5f-4f2a-a1fe-ae76f7a330dc` | 20 | 50.790 |
| stall-0 | PASS | `77c1e293-8433-47a9-8496-1b8f652c1b26` | 1 | 53.246 |
| stall-1 | PASS | `463bf29a-d500-429c-a911-cd8be13d5452` | 1 | 56.316 |

## Coverage and measurement limits

The same-boot cell alternates default compression and RAW for twenty START/STOP cycles. Each capture independently checks epochs, clocks, source/codec/sample conservation and STOP/drain. Host-stall cases pause reads for 250 ms at each GPIO width; all deliberate drops must reconcile with firmware counters and wire gaps. Endurance comprises three independently flashed 600-second combined default-codec jobs, each retaining the 80 °C cutoff and bounded NOT_READY retries.

The machine-readable report retains every status counter, ownership snapshot, temperature sample, CPU interval and per-stream derived metric with its units. Codec ticks use the 8 MHz clock; codec work includes preemption and is not total MCU utilization. Retention is advertised capacity; deadline-age margin is an observed bound, not a guaranteed tolerable host stall. USB data ownership is checked empty; a STATUS response may itself occupy the response queue. Incomplete raw STOP tails are recorded separately from public-v3 wire-item conservation.

Fragmented/zero/partial USB writes are exercised in the existing production transport and SDK harnesses. Physical acquisition uses unstimulated inputs and does not establish analog accuracy, external edge fidelity, power, ambient temperature or multi-hour uninterrupted reliability.

## Local verification

- `pytest.log`: 187 passed, 6 skipped, 86 subtests passed in 35.02s.
- `control-pytest.log`: 258 passed, 13 subtests passed in 21.34s.

Freeze: 500 protected files PASS; 1558 historical hashes unchanged. Original failed campaigns remain preserved. Source, SDK, firmware, runner and qualification policy are unchanged.

Full evidence and measurements: [protocol-v3-lifecycle-hardware.json](protocol-v3-lifecycle-hardware.json).
