---
type: result
title: GPIO RLE Sustained Phase Diagnostic Results
created: 2026-10-18
tags: [firmware, compression, reliability]
related: []
---

# GPIO RLE sustained phase diagnostic results

**Bounded diagnostic PASS; full GPIO RLE qualification remains pending.**
Three ten-minute captures and forty ten-second START/STOP cells without
reflash passed all 6,278 checks. Peak sampled die temperature was 67.983 °C;
parser checksum/header/payload errors and discarded bytes were zero.
All 43 cells completed STOP/drain/IDLE and idempotent STOP checks. The
[complete evidence record](gpio-rle600-phase-sustained-20261018.json)
retains summaries, provenance and artifact hashes, reconciled exactly against
saved results. Frozen orchestration, runner and validator hashes match.

| Job | Remote ID | Cells | Checks | Peak °C |
| --- | --- | ---: | ---: | ---: |
| diagnostic-600-01 | 1439e959-b0ff-4c8f-bc79-eff4a9d4236c | 1 | 146 | 66.141 |
| diagnostic-600-02 | fa0a8792-7b3d-47f3-83fe-43697dbe31fa | 1 | 146 | 67.983 |
| diagnostic-600-03 | 8a376461-060f-421c-8e65-d9aa8607873d | 1 | 146 | 67.983 |
| restart-40x10 | 47180a16-0ec1-4475-8812-85835f43b221 | 40 | 5,840 | 67.983 |

All jobs used immutable `thingdaq-45d59c363f7aa067`, clean source `30e7bfc`, HEX
SHA-256 `bd8a89038d0f5387185b59d4b95499e6fc137cb5bf7f39bc9a4b2009824c768f`.
Raw evidence is retained in `doc/results/raw/gpio-rle600-phase-sustained-20261018`.
Each job reflashes/resets; cells within the restart job do not. All four remote
statuses are success, the local runner has exited, and postflight service
health was healthy with an empty queue. Read-only Docker inspection after
completion found no active containers.

This extends the [early-phase diagnostic](gpio-rle600-phase-diagnostic-20261018.md).
No failure triggered the 96-word phase record. Instrumentation changes service
timing and is not a demonstrated correction; intermittent ADC DMA divergence
remains unresolved. All ten failed physical campaigns and both failed RAM1
builds remain preserved through the
[preceding failure report](gpio-rle600-preemption-failure-20261018.md).
Acceptance limits remain unchanged. Inputs are electrically unstimulated;
no GPIO output or external-pattern fidelity is claimed.

The next campaign runs the full physical gate sequence on the same image:
60-second smoke, three consecutive ten-minute captures, then forty ten-second
START/STOP cells without reflash. Fresh evidence goes to
`doc/results/raw/gpio-rle600-phase-qualification-20261018`. It stops on the first
failure or ambiguity, with no automatic finalizer. This advances from diagnostic
coverage to the planned qualification sequence; it does not establish a causal
fix. If it fails, preserve the eleventh physical failure and decode the early
phase history before further changes. If it passes, report the measured GPIO
wire savings, RAW/RLE counts, GPIO-service CPU, queues and temperature against
the larger-ADC baseline, retaining the unresolved historical failure explicitly.
