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

# Lifecycle hardware qualification: PASS

Exact candidate `14c14a82912a95482bb9146abb06e310b3d7f8c24bec37ef2274d13d4b9d4682`, firmware `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`, build `thingdaq-e0c750868be7c5c2`, serial `20428100`. Six selected cells: **6 PASS / 0 FAIL / 0 INCONCLUSIVE / 0 NOT_RUN**. Release promotion remains a separate task.

| Cell | Grade | Job | Captures | Peak °C |
| --- | --- | --- | --- | --- |
| same-boot-20 | PASS | `409c3d90-eb5f-4f2a-a1fe-ae76f7a330dc` | 20 | 50.790 |
| stall-0 | PASS | `77c1e293-8433-47a9-8496-1b8f652c1b26` | 1 | 53.246 |
| stall-1 | PASS | `463bf29a-d500-429c-a911-cd8be13d5452` | 1 | 56.316 |
| soak-1 | PASS | `494d9c0c-0b16-49b4-bc4b-c0a55705ad82` | 1 | 66.755 |
| soak-2 | PASS | `fe3aab1a-d798-4e37-b9ca-428c5acf0ae2` | 1 | 67.983 |
| soak-3 | PASS | `6e578843-79af-4256-bc93-2febec50f412` | 1 | 68.597 |

## Endurance measurements

| Cell | Seconds | ADC pairs | GPIO samples | Data MB/s | Host cores | Codec work ADC / GPIO (s) |
| --- | --- | --- | --- | --- | --- | --- |
| soak-1 | 600.020 | 600,054,336 | 600,050,304 | 3.075 | 0.478 | 33.017 / 7.483 |
| soak-2 | 600.020 | 600,054,336 | 600,050,304 | 3.075 | 0.478 | 33.019 / 7.483 |
| soak-3 | 600.000 | 600,033,168 | 600,030,144 | 3.075 | 0.479 | 33.016 / 7.483 |

Data MB/s uses decimal bytes and includes data-frame wire overhead. Host cores is process CPU seconds / wall seconds over capture/control boundaries. Codec work is measured wall time inside the codec, including preemption. All raw-encoding counts, deadline margins, loss counters and thermal samples are retained in JSON.

## Coverage and measurement limits

The same-boot cell alternates default compression and RAW for twenty START/STOP cycles. Each capture independently checks epochs, clocks, source/codec/sample conservation and STOP/drain. Host-stall cases pause reads for 250 ms at each GPIO width; all deliberate drops must reconcile with firmware counters and wire gaps. Endurance comprises three independently flashed 600-second combined default-codec jobs, each retaining the 80 °C cutoff and bounded NOT_READY retries.

The machine-readable report retains every status counter, ownership snapshot, temperature sample, CPU interval and per-stream derived metric with its units. Codec ticks use the 8 MHz clock; codec work includes preemption and is not total MCU utilization. Retention is advertised capacity; deadline-age margin is an observed bound, not a guaranteed tolerable host stall. USB data ownership is checked empty; a STATUS response may itself occupy the response queue. Incomplete raw STOP tails are recorded separately from public-v3 wire-item conservation.

Fragmented/zero/partial USB writes are exercised in the existing production transport and SDK harnesses. Physical acquisition uses unstimulated inputs and does not establish analog accuracy, external edge fidelity, power, ambient temperature or multi-hour uninterrupted reliability.

## Mixed-version physical probe

Supplemental probe: **PASS**, job `c66497ed-35e6-41ae-ac04-e5f7a646622b`. Six same-boot captures exercise v3 → v2 GPIO8 → v3 → v2 GPIO16 → v3, then serial close/reopen and another v3 capture. Run IDs must remain 1–6; every capture reuses the frozen sample/clock/health oracle. This probe is separate from the six canonical cells.

## Local verification

- `pytest.log`: 187 passed, 6 skipped, 86 subtests passed in 35.02s.
- `control-pytest.log`: 258 passed, 13 subtests passed in 21.34s.
- `grader-pytest.log`: 12 passed in 0.22s.

Freeze: 500 protected files PASS; 1558 historical hashes unchanged. Original failed campaigns remain preserved. Frozen build reserves 33,024 bytes RAM1 for locals and 4,096 bytes RAM2 heap. These are linker/build margins, not measured stack/heap high-water marks. Source, SDK, firmware, frozen runner and qualification policy are unchanged.

Full evidence and measurements: [protocol-v3-lifecycle-hardware.json](protocol-v3-lifecycle-hardware.json).
