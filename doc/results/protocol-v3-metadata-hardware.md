---
type: report
title: Public v3 physical metadata and fixed-clock configuration checks
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - fixed-clock
  - qualification
related:
  - '[[protocol-v3-identity-recovery]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-clock-control]]'
  - '[[protocol-v3-qualification]]'
---

# Metadata and configuration hardware checks

**PASS for this task. Full release qualification remains INCONCLUSIVE.**
The frozen matrix's `unsupported` cell passed; its other 62 cells remain unrun.
The supplemental short captures below do not substitute for the later streaming,
compatibility, lifecycle, backpressure or endurance tasks.

Candidate SHA-256:
`13b4060f6a90d7aecc4f8f93de319f389ed65a74c665f2bd72b6597e28054872`.
HEX SHA-256:
`33ff95d8f37b6ebd51457eae66c323ca99b82efe692b1b4994d2d05700398b2a`.
Physical Teensy 4.0 serial `20428100`, build `thingdaq-5c7c7201f63665fd`,
firmware/SDK 1.2.0 and public protocol 3 match [[protocol-v3-identity-recovery]].
No firmware, SDK, schema, frozen worker, policy or HTTP-helper input changed.

[Machine-readable evidence](protocol-v3-metadata-hardware.json) contains
measurements, counters, identities, all three outcomes, independent grading,
and hashes/paths for the retained local programs, results and logs.

## Physical observations

| Check | Result |
| --- | --- |
| Boot defaults | Both hardware streams, CPU 600 MHz, ADC/GPIO 1 MHz, auxiliary DISABLED, GPIO8 RLE_AUTO, ADC PACK12, Adler-32; STOPPED, run ID 0, no pending frames |
| Metadata | Public INFO, all 48 advertised capability tuples, GET_SETTINGS and configure echoes agree with the exact candidate |
| Clock metadata | CPU/IPG/ADC/PIT/timestamp = 600/150/37.5/24/8 MHz |
| Clock diagnostics | Seven stopped DWT/PIT/eDMA measurements in the corrected job; 8,192 requested events at 1 MHz, PIT load 23, CCM PERCLK oscillator/divider bits checked, no hardware errors |
| ADC initialization/phase | Configuration flags 255, no initialization/trigger errors; ADC_ETC counter readbacks 0/75 IPG cycles; measured completion separation within 300 ± 120 CPU cycles |
| Stopped configuration | RAW, RAW, compressed, compressed accepted with identical clocks and matching readbacks |
| Acquisition after changes | Three two-second combined hardware captures, compressed/RAW/compressed, same-boot run IDs 1/2/3; independent wire/SDK conservation and final STOPPED checks passed |
| Normal short-capture health | Zero firmware drops, codec deadline/resource drops, parser errors, host queue drops and required hardware/ownership errors |
| Unsupported requests | All 18 cases returned their required errors: twelve canonical unsupported CPU tuples, four malformed settings and two unsupported sample rates; valid settings and 600 MHz unchanged |
| Configure during RUNNING | INVALID_STATE (7), unchanged RAW settings, still RUNNING |
| Configure during drain | STOP explicitly reported DRAINING with five pending frames; paired CONFIGURE returned BUSY (10), unchanged RAW settings |
| Serial reconnect | Close/reopen retained RAW settings and run ID 5; final STOPPED with zero pending frames and zero transport/parser/hardware errors |
| Reset restoration | Original probe's last CONFIGURE response confirms RAW; the next job reprogrammed the identical image and observed default compression with run ID 0 |
| Command latency | 111 measured commands in the corrected session; maximum 90.068 ms against the existing one-second deadline |
| Temperature | Corrected job 40.351–44.036 °C; valid readings before/during/after capture, existing 80 °C cutoff retained |

The drain probe used a bounded 50 ms host-read pause and sent separately
correlated STOP/CONFIGURE requests in one serial write. It tests the draining
state; it is not the later required backpressure qualification cell.

The clock observations have distinct scopes. Public clock records are compiled
metadata. DWT/PIT/eDMA diagnostics provide register readbacks and observed
counts at the requested rate. Legacy INFO retains its **boot** ADC-trigger
snapshot: a 4 MHz master and chained 1 MHz ADC schedule. Those cached fields
are not current public-v3 PIT-load readbacks. Physical v3 START applies the
1 MHz schedule through the frozen scheduler's `registerReadbackMatches` gate,
including PIT loads 23/0 and ADC_ETC phase 0/75; successful acquisition follows
that gate. No external reference measured absolute PLL frequency or aperture.

Reset here means the rig's programming/system reset with the same artifact.
Reconnect means reopening the serial device. Neither is a physical USB unplug
or power-removal test. Unstimulated acquisition does not establish analog
accuracy or external waveform fidelity.

## Attempts and retained diagnostic failure

| Job | Scope | Outcome |
| --- | --- | --- |
| `8beddb76-fa14-4c1b-be7e-638987e98d47` | Unchanged frozen `unsupported` matrix cell | PASS |
| `c21a3d65-43d3-4ab0-b77d-c7650545567b` | Initial supplemental metadata probe | FAIL, retained |
| `4713759c-86bc-4760-8430-1946e588b5a8` | Corrected supplemental probe, including drain/reconnect | PASS |

The initial supplemental probe passed boot/configuration checks and all three
short captures, then timed out at its fourth START. Its local wrapper had
omitted `WireTap.reset()` before that additional run. The observer consequently
compared the new run's reset timestamp against the preceding run's final
cursor and raised a timestamp-regression error in the reader thread.
The retained result includes that oracle error and the subsequent timeout.

A local regression using the retained physical frame reproduces the original
failure and passes when the wrapper resets the observer before START. A second
test verifies that pairing STOP/CONFIGURE preserves both frames and request IDs
through partial transport writes. The corrected probe used a separate saved
submission and reran its measurements. No firmware or frozen qualification
implementation was corrected; the first diagnostic FAIL was not relabeled.

The existing matrix validator independently reports the unsupported cell PASS
and the full campaign INCONCLUSIVE with 62 missing cells. The supplemental
probe's independent grader recomputes its metadata, captures, register checks,
state rejections, reconnect and latency results. Altering CPU clock evidence,
drain acceptance, reconnect epoch or loss accounting makes that grader fail.
These probes are separately identified evidence, not extra canonical matrix cells.

## Validation and resumption

- Freeze and protected inputs: PASS, all 498 files; exact staged HEX unchanged.
- Qualification and HTTP retry suites: 800 passed.
- Portable v3 lifecycle/regression suites: 30 passed.
- Supplemental observer, paired-write and evidence-mutation checks: seven passed.
- Documentation integrity: seven passed, 1,268 subtests passed.
- Service health after all jobs: PASS. Queue residence was excluded from execution
  deadlines; no accepted submission was duplicated.

The initial test command named nonexistent `test_rig_queue.py` and collected
no tests. The corrected existing suites produced the passing counts above.

Local evidence roots:

- `.maestro/playbooks/Working/phase06-metadata-20261024/` — supplemental programs,
  original/corrected jobs, independent grader, tests and logs.
- `.maestro/playbooks/Working/protocol-v3-qualification/unsupported/attempt-001/`
  — canonical frozen-cell program, submission, status and raw result.

The frozen worker retains hashes of all serial bytes, representative data
frames and bounded control-frame samples, rather than continuous raw captures.
Full returned logs and those raw samples remain in the local results files;
the committed JSON omits duplicate frame samples and records their file hashes.

To regrade these completed observations without another submission:

```bash
.venv/bin/python .maestro/playbooks/Working/phase06-metadata-20261024/grade_metadata.py
.venv/bin/python firmware/tools/qualify_protocol_v3.py validate \
  --candidate firmware/soak/protocol-v3-candidate.json \
  --output .maestro/playbooks/Working/protocol-v3-qualification
```

The second command deliberately exits nonzero while required matrix cells are
missing. Future matrix execution must use that campaign directory with
`--resume` and the active artifact paths in [[protocol-v3-identity-recovery]].
Do not submit new jobs merely to recover these completed results.
