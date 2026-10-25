---
type: report
title: Qualification runner CPU provisioning corrects GPIO backpressure
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - qualification
  - host-backpressure
related:
  - '[[protocol-v3-gpio-overrun-diagnosis]]'
  - '[[protocol-v3-dma-recovery]]'
---

# Runner correction validated; requalification remains pending

The corrected qualification runner provisions two CPU cores for its accepted
job and verifies the allocation before opening serial. A fresh 60-second
capture of the original failing configuration passed with zero loss, packet
evictions, raw-ring overruns, DMA faults, parser errors, or host queue drops.
The correction follows [[protocol-v3-gpio-overrun-diagnosis]] and preserves the
DONE-before-DREQ firmware correction in [[protocol-v3-dma-recovery]].

## Scoped change

`firmware/tools/qualify_protocol_v3.py` matches the accepted UUID against the
container's `/storage` mount, updates only that container to quota/period
`200000 100000`, and saves Docker readback in `cpu-allocation.json`. It uses the
existing `FW_RIG_SSH` override or `bill@<service hostname>` and the rig's existing
Docker Python environment. Service defaults and other jobs are unchanged.
SSH operations have a ten-second deadline. Ambiguous containers or allocation
errors fail explicitly; a resume verifies live allocation again rather than
trusting an old receipt.

`firmware/tools/run_input_isolation.py` adds an optional active-job callback.
Admission/journal reconciliation, saved-job following, unlimited queue wait,
30-second 5xx retries, ten-minute continuous-5xx budget, and existing execution
limits remain intact. No callback executes for queued or terminal results.

`firmware/tests/rig_protocol_v3_qualification.py` waits at most 30 seconds for
quota readback and at least two available CPU IDs before serial open. Failed
setup emits a FAIL record with zero captures. Capture-boundary telemetry reuses
`host_cpu()` from `rig_release_sdk.py` and `CpuTracker` from the soak validator;
the bundle selects their original definitions and freezes both source hashes.
Post-STOP legacy STATUS retains packet ownership even when a stream gap raises.
No acquisition-time command was added. Missing ownership evidence fails the
normal path. The independent reader also rejects missing/insufficient worker
CPU setup evidence.

Firmware, SDK, public settings, capture durations, sample-loss acceptance,
thermal limits, and the qualification policy are unchanged. Existing tests
received only callback-signature, host-setup, and legacy-STATUS fixture updates. Independent
permanent regression coverage remains the next playbook task.

## Fresh diagnostic evidence

- Job: `2abfcf14-7dd0-4a1d-8317-91e324118eb5`; independently graded PASS.
- Original failed candidate: `5d6df850bd97add629502c9126c42eb1483ee2bd05efb1c0b466c55e5a92c1c7`.
- Firmware HEX: `f29d05970b5b49381f4efcd80e2b948e72a41b89a32edbfce6ca00c5fab8fdbf`.
- Build: `thingdaq-92950ec5f7156586`; serial `20428100`; fixed 600 MHz.
- Tuple: `030001030104011000000c0040420f0040420f00` (physical combined ADC/GPIO16 RAW).
- Capture: 60.007234 seconds; 60,027,408 ADC pairs and 60,026,400 GPIO samples.
- Packet transmit high-water: 8/200; final ownership and pending frames: zero.
- CPU: 30.583873 process seconds over 60.183134 boundary wall seconds;
  zero capture-period throttling. Both boundary quota reads were `200000 100000`.
- Temperature: 39.123–50.176 °C; bounded NOT_READY retries retained.

Earlier bootstrap throttling remains visible in the CPU baseline; it is not
capture-period throttling. All four earlier jobs were reconciled terminal
before submission. The old controller was absent and its lock was free.
Normal service cleanup removed the diagnostic container.
Original failure `322b4ac0-309d-4d61-a625-d4ce41cbf104` remains FAIL; all 63 prior
diagnostic evidence hashes and all five frozen artifact hashes were verified.

## Validation and handoff

Before editing, the existing production packet-pipeline reproduction again
produced exactly one 2,016-sample / 4,032-byte GPIO eviction under blocked USB,
with immutable pinned data, exact conservation, independently checked wire
payload/checksum, and a lossless draining control.

A temporary resource-precondition test fails against `cbbf330`: the half-core
worker opens serial. Its adequate-resource control passes. With the correction,
all four temporary checks pass: inadequate-resource rejection, adequate-resource
admission, exact-job Docker selection with resume revalidation, and isolated
execution of the bundled telemetry definitions. The affected existing suites
passed 853 tests; resource-owner/freeze suites passed 28 tests and 27 subtests.
The final runner, temporary reproduction and documentation checks passed 91 tests
and 1,448 subtests (overlapping the earlier runner set). A final runner check
initially failed because the v3 simulator has no legacy ownership STATUS; the
existing orchestration fixture now reuses the v2 simulator for that readback.
The failing log is retained; the production ownership gate remains enforced.
The unchanged target manifest passes memory headroom validation: RAM1 locals
33,024 bytes and RAM2 heap 4,096 bytes. No firmware/build input changed, so no
new target image was built for this host-only correction.

Retained driver, tests, logs, raw results, provenance and allocation readback:
`.maestro/playbooks/Working/phase06-gpio-correction-20261025/`. Resume its accepted
job only with `run_correction.py --resume`; do not submit another diagnostic or
restart the old campaign. Exact hashes and measurements are recorded in
[the machine-readable report](protocol-v3-gpio-overrun-correction.json).

**This diagnostic earns no canonical qualification credit.** Streaming remains
36 PASS / 1 FAIL / 19 NOT_RUN. The changed runner inputs invalidate the active
freeze; keep its candidate and historical evidence unchanged. Commit independent
regression coverage next, then freeze and requalify the corrected candidate in a
separate campaign. No release promotion, analog accuracy, external timing, or
continuous endurance claim follows from this capture.
