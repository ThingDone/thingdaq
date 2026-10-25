---
type: report
title: Corrected qualification candidate passes hardware prerequisites
created: 2026-10-25
tags:
  - protocol-v3
  - qualification
  - hardware
  - host-backpressure
related:
  - '[[protocol-v3-gpio-overrun-diagnosis]]'
  - '[[protocol-v3-gpio-overrun-correction]]'
  - '[[protocol-v3-gpio-overrun-regression]]'
  - '[[protocol-v3-dma-recovery]]'
  - '[[protocol-v3-release-candidate]]'
---

# Requalification prerequisite passed

The corrected runner candidate passed live identity, metadata/configuration,
fixed-clock checks, reset/default restoration, all 18 unsupported requests,
and fresh full 60-second captures of both original failure configurations.
This completes the prerequisite milestone. Full release qualification remains
**INCONCLUSIVE**: the new campaign has **2/56 streaming cells PASS**, zero FAIL,
and 54 NOT_RUN; unsupported requests add one separate PASS. No old passing
cell was imported. Lifecycle, endurance, isolated pre-upgrade SDK testing and
promotion remain pending.

## Frozen identity and local gates

- Candidate SHA-256: `bdb695e98e472a26d575f0a617d2deb6f1a5a500ce5771789c29dac431918d51`.
- Firmware HEX SHA-256: `f29d05970b5b49381f4efcd80e2b948e72a41b89a32edbfce6ca00c5fab8fdbf`.
- Build: `thingdaq-92950ec5f7156586`; Teensy 4.0 serial `20428100`.
- Source revision: `62caff6a88133b93abba8d2edf2382e1ede1bee0`; freeze commit `d1a905d`.
- Two clean builds reproduced all exported artifacts and manifests byte-for-byte.
- All 499 protected files, retained artifacts and frozen runner inputs verified.
- Firmware, SDK, schemas, policy, matrix, capture durations and acceptance
  thresholds are unchanged. The new identity freezes the CPU provisioning and
  telemetry correction described in [[protocol-v3-gpio-overrun-correction]].
- Target gates PASS: RAM1 stack reserve 33,024 bytes; RAM2 heap reserve 4,096 bytes.
- Full local suite: **2671 passed, 5 skipped, 17081 subtests passed in 303.55s (0:05:03)**.
- Documentation/layout checks: **11 passed, 1465 subtests passed in 2.72s**.

The failed candidate/freeze were archived byte-for-byte as
`firmware/soak/history/protocol-v3-candidate*-20261025-gpio-failed.json`.
All 316 retained historical campaign/report files kept their hashes.
Historical streaming remains 36 PASS / 1 FAIL / 19 NOT_RUN, retaining the
original GPIO loss in [[protocol-v3-gpio-overrun-diagnosis]]. The earlier ADC
failure remains separately preserved in [[protocol-v3-dma-recovery]].

## Fresh physical evidence

| Gate | Job | Result |
| --- | --- | --- |
| Identity and complete capabilities | `61e9cc1c-d89e-4ab9-91cb-31a207d0a632` | PASS |
| Eighteen unsupported-request rejections | `0b9dddd3-b3dc-4ad7-a5b8-64c4e74a80ef` | PASS |
| Metadata/configuration/fixed clocks/reconnect | `dbc42664-806c-446c-93e2-6591b1ce5378` | PASS |
| Programming reset/default restoration and repeated metadata checks | `faae90fa-f4c8-4706-9c08-5658528e3f76` | PASS |

Each metadata job verified boot defaults (600 MHz, 1 MHz ADC/GPIO, auxiliary
bank disabled, GPIO RLE_AUTO, ADC PACK12), repeated stopped RAW/compressed
configuration, three two-second acquisitions with same-boot epochs 1/2/3,
RUNNING/INVALID_STATE and DRAINING/BUSY rejection, and serial reconnect.
Each retained seven clock diagnostics and three ADC phase readbacks;
maximum measured command latency across both jobs was 90.679 ms.
The first metadata job ended with RAW settings; programming the identical image
for the second restored compressed defaults and epoch zero. This is a
programming/system reset, not a power-removal test. Legacy INFO timing values
remain boot snapshots.

| Full capture | Seconds | ADC pairs | GPIO samples | TX buffers high-water / 200 | Peak °C | Job |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| ADC-only RAW | 60.001712 | 60,027,408 | 0 | 2 | 53.860 | `eb1cbc1f-6dea-4cdf-a84a-241c1f46ad86` |
| Combined ADC/GPIO16 RAW | 60.000007 | 60,017,328 | 60,016,320 | 6 | 56.316 | `b5b41941-6b73-419b-92af-88be8f08613d` |

Both captures independently passed the unchanged sample-conservation, timing,
checksum, sequence, health and 80 °C thermal gates. They had zero unexpected
wire loss, packet evictions, raw-ring overruns, DMA faults, parser errors or
host queue drops, and ended STOPPED with zero pending frames. Legacy ownership
readbacks retain incomplete STOP-tail discard counts separately; those are not
unreported full-frame losses. Both jobs verified quota/period `200000 100000`
and at least two available CPU IDs before serial opened. Capture-boundary CPU
telemetry showed zero throttled microseconds; bootstrap counters remain visible
in the baseline. No extra acquisition-time STATUS probes were introduced into
the two canonical captures.

## Retention and continuation

Raw rig responses, programs, job IDs, submission tags, CPU allocation receipts,
independent grades, build logs and source snapshots are retained in
`.maestro/playbooks/Working/phase06-gpio-requalified-20261025/` and the separate
campaign `.maestro/playbooks/Working/protocol-v3-qualification-gpio-fixed-20261025/`.
The [machine-readable report](protocol-v3-gpio-requalification.json) contains
exact hashes, counters, commands, per-job evidence and the independent campaign
grade. Retained jobs must be resumed with `--resume`; the prerequisite controller
is `requalify.py` and stops at `REQUALIFICATION_COMPLETE`. It does not launch the
remaining streaming matrix. Old controller/PID notes in the playbook are historical.

The next task must continue the new campaign against this exact candidate.
Do not restart the historical failed campaign. Shared-rig queue waits and all
5xx retries/reconciliation remain delegated to `run_input_isolation.py`.

These are unstimulated physical captures. They establish the measured
transport/control and acquisition behavior, not analog accuracy, external
waveform fidelity, power consumption or multi-hour continuous reliability.
