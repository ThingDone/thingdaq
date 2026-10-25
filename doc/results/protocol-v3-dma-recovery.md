---
type: report
title: Public v3 ADC DMA STOP correction and matrix continuation
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - qualification
  - dma
related:
  - '[[protocol-v3-dma-fault-site]]'
  - '[[protocol-v3-streaming-baseline-replay]]'
  - '[[protocol-v3-release-candidate]]'
---

# STOP correction passed; streaming matrix resumed

**The original 60-second ADC-only RAW failure case now passes with zero DMA
errors.** The corrected candidate passed identity, metadata/configuration,
fixed-clock measurements and unsupported-request checks. Its streaming matrix
is running; full qualification and release promotion remain incomplete.

The STOP path wrote CSR with DREQ while DONE could still be set. The eDMA
coherency rule then cleared ESG, causing the descriptor pointer to be added to
the destination address at major completion. Fault-site evidence and its
limits are retained in [[protocol-v3-dma-fault-site]]. Correction `448e54a`
clears DONE through DMA_CDNE and the existing barrier before the CSR update.
Independent regression commit `c67872b` executes the production boundary
function: three DONE cases fail before the correction and all seven cases pass
after it. Production and regression changes were committed separately.

## New artifact and prerequisite results

Two clean builds reproduced every artifact and manifest byte-for-byte. Freeze
commit `811ab97` protects 499 files. The old failed candidate and freeze are
archived under `firmware/soak/history/` with the `20261024-dma-failed` suffix;
its evidence is unchanged.

- Candidate SHA-256: `5d6df850bd97add629502c9126c42eb1483ee2bd05efb1c0b466c55e5a92c1c7`.
- Build: `thingdaq-92950ec5f7156586`; HEX SHA-256: `f29d05970b5b49381f4efcd80e2b948e72a41b89a32edbfce6ca00c5fab8fdbf`.
- RAM1 stack reserve: 33,024 bytes; RAM2 heap reserve: 4,096 bytes. All target gates passed.
- Full local suite: **2,657 passed, five expected skips, 17,055 subtests**.
- Focused correction validation: 55 tests and 79 subtests passed.

| Gate | Job | Result |
| --- | --- | --- |
| Physical identity and exact capabilities | `fad09eb5-7e64-48f5-8e4b-a95e247f4f48` | PASS |
| Eighteen unsupported-request rejections | `a488b1ad-dae4-4d8a-86d1-97a6a0bf442c` | PASS |
| Metadata, configuration, clocks, reconnect | `c58804d6-62d9-4f57-80d6-6cd454fd511c` | PASS |
| Original ADC-only RAW failure cell | `b72e07dd-0d94-4a18-b972-58e92788acc7` | PASS |

The metadata probe passed seven clock measurements, default/RAW/default
acquisitions with epochs 1/2/3, stopped configuration repeats, RUNNING and
DRAINING rejections, and serial reconnect. Identity reported Teensy 4.0 serial
`20428100`, firmware 1.2.0, and the exact new build at fixed 600 MHz.

The original failure cell captured **60,030,432 ADC pairs** over
60.003177 seconds, with no wire gaps, parser corruption, host queue drops,
DMA/ETC errors, or invariant errors. Final state was STOPPED with zero pending
frames. Temperature rose from 44.036 to 52.632 °C. Its unchanged independent
capture policy returned no problems.

## Continuing work

At this checkpoint the selected matrix has **1/56 PASS, 0 FAIL, 55 incomplete**;
its next job is already accepted. The negative-request cell is a separate PASS.
Later results live in the campaign ledger and do not retroactively change this
checkpoint's counts. An isolated `/health` HTTP 503 retried successfully before
the next submission. Queue residence and isolated 5xx responses do not halt the
controller or spend its capture execution budget.

The active controller is
`.maestro/playbooks/Working/phase06-dma-corrected-20261024/continue_qualification.py`.
Read its `progress.json`, `qualification.log`, process state and saved jobs
before taking action. It serializes accepted jobs through the current
`run_input_isolation.py` and stops new submissions on a measurement failure.
If the local controller exits, resume it with `--resume`; never start a second
copy while it is alive. The separate campaign is
`.maestro/playbooks/Working/protocol-v3-qualification-dma-fixed-20261024/`.

The complete matrix, isolated pre-upgrade SDK compatibility, later lifecycle and
endurance checks, and promotion remain uncredited. Real unstimulated acquisition
does not establish analog accuracy or external waveform fidelity. Machine-readable
results and exact retained evidence hashes are in
[protocol-v3-dma-recovery.json](protocol-v3-dma-recovery.json).

## Resume checkpoint

On 2026-10-24 the previous controller process had exited. Resuming with
`--resume` followed saved job `1dbf164b-b283-498c-a7aa-69f0198806ca` through
queue residence and execution to PASS, without submitting another copy.
Independent replay now gives **3/56 streaming PASS, zero FAIL, 53 incomplete**.
Job `558e5bbf-e5cd-4c74-bc3d-318ec7bdd767` is the next accepted cell; the
controller continues as PID 8538 at this checkpoint. Inspect the live ledger
and process before resuming; these counts are historical.

The candidate freeze and every earlier retained evidence hash rechecked PASS.
Documentation/layout validation passed 11 tests and 1,435 subtests. The JSON
`continuations` entry retains the resumed job's evidence hashes. Earlier
checkpoint counts and failures remain unchanged; complete streaming, later
qualification, and promotion remain uncredited.
