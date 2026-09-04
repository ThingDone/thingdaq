# Independent sampling-rate and input-width experiments

Follow-up: [equal-rate inputs and 450 MHz CPU tests](input-rate-clock.md) now
test 1 MHz on each ADC and all sixteen GPIO inputs independently of the original
4:1 profiles below. Do not read this older matrix as a test of equal rates.

## Current answer

Several independent software defects were hidden behind the original mandatory
paired-bank diagnostic. They are now fixed on `experiment/aux-input-bank`;
the experiment runner and this report are on `main`. The experimental firmware
has **not** been merged into production main.

After the user recovered the board, the **eight-input rate experiment passed
all four profiles**, including a 0→1→2→3→0 cycle without reflashing (ten seconds
per cell), then **60 seconds per cell on the final clean candidate**, with every
STOP passing. The sixteen-input comparisons exposed additional, independent
metadata, transport and validator defects described below. With those fixed,
**sixteen inputs plus ADCs pass for 60 seconds at GPIO 1 MHz / ADC 250 kHz and
GPIO 500 kHz / ADC 125 kHz**. GPIO 2 MHz / ADC 500 kHz passed ten seconds.
Full-speed sixteen-input combined acquisition
still stalls the ADC path; its queued GPIO evictions are a downstream symptom.
The 60-second profile-1 follow-up streamed without active loss but returned an
ADC error on STOP; it remains an overall **FAIL**. Short capture passes do not
establish reliable shutdown or production readiness.

No new wires or loopbacks are required for these tests.

## Controlled experiment design

All cells use the same candidate, 600 MHz CPU, raw/uncompressed data, Adler-32,
unstimulated inputs and no output engine. The paired-bank diagnostic is opt-in,
not a prerequisite. These are runtime-feature controls in the experimental
firmware, not separate builds with the unused feature compiled out.

| ADC / GPIO rate | Eight inputs + ADC | Sixteen inputs + ADC | Eight inputs, GPIO only | Sixteen inputs, GPIO only |
| --- | --- | --- | --- | --- |
| 1 MHz / 4 MHz | **PASS**, 60 s twice | **FAIL**, ADC stalls; GPIO queue fills | **PASS**, 10 s twice | **FAIL** at STOP after 10 s; four/five-sample bank skew |
| 500 kHz / 2 MHz | **PASS**, 60 s | **PASS**, 10 s; **FAIL** at STOP after 60 s | **PASS**, 10 s | **PASS**, 10 s |
| 250 kHz / 1 MHz | **PASS**, 60 s | **PASS**, 60 s | **PASS**, 10 s | **PASS**, 10 s |
| 125 kHz / 500 kHz | **PASS**, 60 s | **PASS**, 60 s | **PASS**, 10 s | **PASS**, 10 s |

The rate experiment changes only the profile with eight inputs selected.
The width experiment compares eight versus sixteen inputs at the same profile.
GPIO-only counterparts remove ADC interaction. The separate diagnostic tests
both GPIO DMA banks without grading stream bandwidth. A final 0→1→2→3→0 profile
cycle passed with eight inputs. The sixteen-input cycle currently stops at
the first full-rate failure, so lower rates are submitted independently.

## Defects and fixes

| Defect | What actually happened | Fix and evidence |
| --- | --- | --- |
| Command-size mismatch | v2 CONFIGURE is 64 bytes, but firmware retained v1's 56-byte limit and 59-byte parser buffer. Every valid v2 configuration was rejected before rate/pin testing. | Version-aware limit, 67-byte parser storage and 68-byte reservation. New C++ test first reproduced all eight width/rate failures, then passed every fragmentation boundary. Physical CONFIGURE now passes. |
| Status bits mistaken for enables | Rate setup required the entire ADC_ETC DMA_CTRL register to be zero. Boot completion flags left `0x00110000` latched even though requests were disabled. START rolled back with platform-apply failure. | Check only enable bits; preserve W1C status during rollback. Temporary hardware trace identified the register value; the real target adapter is now exercised with a W1C-aware fake. Physical START and capture now pass. |
| Truncated slow-rate ADC delay | Teensy core 1.62's INIT_DELAY macro masks to eight bits. Required delays of 300 and 600 IPG cycles would become 44 and 88. The old readback check used the same defective macro. | Encode the actual 16-bit register field in both scheduler and trigger adapter. Real-adapter tests verify register values 75, 150, 300 and 600. Slow-rate hardware throughput now passes; external aperture/phase measurements remain untested. |
| Colliding DMA priorities | Paired GPIO setup assigned channels 2/3 priorities 1/0 without updating inactive ADC channels 0/1, whose reset priorities are 0/1. Standalone GPIO and switching back from INPUT could also leave duplicates. | Configure all four reserved priorities as a unique permutation: legacy 2/1/0/3, INPUT 3/2/1/0. Host tests cover inactive channels and repeated mode changes. Physical paired capture now completes both banks; separate diagnostic grading mismatches remain below. |
| Misleading runner grading | The runner discarded v1 generic rejections, required both banks in the eight-input control, graded the paired diagnostic against v1 primary BITER/priority, and expected active metadata after STOP. | Accept only the legitimate legacy rejection shape, make diagnostic optional, expect primary BITER 2024/priority 1, and distinguish IDLE metadata from completed-run counters. Active-loss and STOP-tail checks remain enabled. |
| Incomplete sixteen-input INFO encoding | After board recovery, the eight-input rate cycle passed, but sixteen-input CONFIGURE advertised ADC payload 4048 instead of 2024 bytes and legacy ADC/GPIO priorities. Acquisition was never started. | The encoder now selects these three fields from the active mode, matching the API and existing validator. The new C++ regression reproduced all twelve mismatches across four rates before the fix. |
| Fixed-size USB admission | Sixteen-input mode produces 2072-byte ADC frames, but USB admission still required 4096 bytes. The transport discarded valid ADC frames, recorded I/O errors and misleadingly released them as transmitted. | Both admission checks now accept the two supported lengths. A real-encoder/USB regression first failed, then passed with mixed ADC/GPIO frames and zero/partial writes. Physical combined capture passes at profiles 1–3, with the profile-1 sustained STOP failure retained. |
| Invalid single-stream/STOP assertions | GPIO-only accounted frame skew legitimately grows when ADC is disabled. Normal paired STOP cancels its two outstanding reservations. The fake device omitted both behaviors, hiding the runner mistakes. | Bound cross-stream skew only in combined mode; permit at most two canceled generations only in final paired STOP status. Active cancellation, bank skew, count mismatches and all loss/conservation checks remain strict. Fakes now reproduce these real firmware behaviors. |

Hardware register semantics were checked against
[NXP's ADC_ETC driver documentation](https://mcuxpresso.nxp.com/api_doc/dev/4784/a00009.html)
and [NXP's RT1062 register definitions](https://github.com/nxp-mcuxpresso/legacy-mcux-sdk/blob/main/devices/MIMXRT1062/MIMXRT1062.h).
The priority rule is documented in
[NXP's eDMA reference material](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/186373/1/IMXRT1050RM.pdf).

## Remaining failures are separate

### Full-rate GPIO DMA interferes with ADC acquisition

On the repaired full-rate sixteen-input build, both ADCs remain active but
produce almost no DMA results. Their DMA requests and triggers are enabled,
with no DMA error. GPIO keeps producing frames; combined-stream fairness waits
for the missing ADC stream, and the GPIO packet queue eventually overflows.
Increasing the USB buffer or relaxing fairness would not repair acquisition.

Diagnostic job `94accc35-1af3-437c-b1e8-1e5703552345` measured the same ADC
remaining-transfer counters before and after a controlled intervention:

| Observation in one run | ADC0 CITER | ADC1 CITER |
| --- | --- | --- |
| With both GPIO DMA streams running | 505 | 506 |
| After another 20 µs, GPIO DMA unchanged | 505 | 506 |
| After disabling only GPIO DMA requests and waiting 20 µs | 484 | 485 |

The ADC timing, trigger routing and DMA configuration were not reset or changed.
Both ADCs resumed immediately when GPIO DMA traffic was removed. This proves
the load dependency, but **does not yet distinguish peripheral-bus contention,
DMA arbitration or ADC_ETC handshake behavior**. It is not proof that 4 MHz
sixteen-input capture is an absolute hardware limit. The diagnostic intentionally
breaks normal combined capture and is not graded as an acceptance pass.
Its exact source patch is retained alongside the submitted binary and program.

### STOP has independent problems

- GPIO-only sixteen-input capture at 4 MHz completed ten seconds, then STOP
  reported a four-sample bank-tail mismatch; a clean-candidate repeat reported
  five samples. The strict bank-skew checks remain
  enabled; this has not been relabeled as harmless loss.
- Combined sixteen-input profile 1 completed 60 seconds and transmitted 59,559
  frames from each stream without active loss. STOP returned INTERNAL_ERROR
  with one ADC stop error; cleanup ultimately reached IDLE. Job
  `b677587f-a453-407e-88d7-98c75143ee55` remains failed. The precise shutdown race
  has not yet been established.

### The optional paired diagnostic still has contract/grading mismatches

Job `ff0513fb-2617-4e29-af5d-1ef2fee7bae4` exercised the diagnostic at its fixed
4 MHz rate, independently of the selected streaming profile. Both banks retained
and analyzed a complete 2024-sample block, and the hardware-error checks passed.
The overall diagnostic nevertheless failed four assertions:

- The runner requires auxiliary CITER to remain exactly 2024 even though it is
  read while DMA is running; the actual value was 1861.
- Its paired-count check still expects 4048 primary samples from the old layout,
  although sixteen-input mode uses 2024 samples in each bank.
- Both captured-count checks expect partial tails to be included, but the target
  currently publishes completed-bank counts (2024), separately from its reported
  partial tail (200). The firmware and validator need a consistent definition.

These remaining diagnostic issues were **identified, not fixed or waived** in
this capture-focused follow-up. No streaming START was issued for that job.
The independent matrix does not depend on this diagnostic passing.

## Physical evidence

Target: Teensy serial **20428100**, remote rig hub port **15**.

- Original rejection: `9924586f-17cc-41a6-8f03-85ad8a46aaa4`.
  Raw response was INVALID_LENGTH, not a silent CONFIGURE hang.
- Parser-only fix: `838876ad-4537-42fe-a2d9-b0fb2ecfee46`.
  CONFIGURE/metadata passed; START exposed the separate scheduler defect.
- Register trace: `3ca6850f-804b-4357-9900-959e2e9e6f42`.
  ADC_ETC DMA_CTRL was `0x00110000`; PIT and ADC trigger controls were stopped.
  Temporary trace instrumentation was removed from the final candidate.
- Successful isolated control: `dad59acd-67eb-4c51-90ae-44d1f5dd1b99`.
  Build `thingdaq-92254306334bb69f`; **128 checks passed**.
  Measured ADC **1,000,000.08 pairs/s**, GPIO **4,000,000.30 samples/s**.
  Received 5,208 frames per stream; maximum frame skew 1; STATUS p99 8.16 ms.
  STOP discarded 82 ADC pairs and 331 GPIO samples, fully reconciled as bounded
  partial tails—not active-stream loss.
- Upload failure: `87b7c89e-1b7d-4e76-9d3d-6dd7a85f9684`.
  All three loader attempts failed, before the sixteen-input test program ran.
- Board-detection failures: `9122f006-adef-4652-8569-9a335aa73efe` and
  `73d6d833-aada-4efe-9bc1-af28e1091244`.
  Neither serial nor HalfKay appeared within 20 seconds of powering port 15.
  Public service health remained healthy/idle. Broader USB resets or service
  deployment changes were not performed.

The [machine-readable run index](input-isolation-runs.json) preserves the original
eleven jobs and recovery follow-ups, identities, results and raw-result hashes.
Temporary trace builds are diagnostic evidence, not acceptance candidates.
Complete HEX images, manifests,
submitted programs and service responses remain under
`.maestro/playbooks/Working/input-isolation/`.

## Validation and source checkpoints

- `b38bcdd`: command parser fix and independent diagnostic selection.
- `c96bdbd`: DMA-priority, ADC register and STOP-grading fixes.
- `d2ad07c`: active-mode INFO metadata fix, with real encoder regression.
- `086d44d`: short ADC frame USB admission and isolated GPIO/STOP grading.
  Build `thingdaq-81e5fa1be59b4aae` passed combined sixteen-input captures:
  profile 3 job `089ab77b-a6e6-4c17-a424-c1d4d540b970` and profile 1 job
  `e14177fd-bb5d-4672-adc4-f8bda41c34fd`, 131 checks each.
- Recovery rate-cycle job `61dda5f7-0115-45b2-b828-e5a2e14ca93b` passed all five
  eight-input cells, 128 checks each, on the preceding candidate.
- Final clean-candidate eight-input rate cycle
  `7b642559-e98b-471f-ab0b-f10cc15ba6ac` passed profiles 0→1→2→3→0 for 60
  seconds each, 128 checks each, including every STOP. This is the matched
  baseline for the sixteen-input sustained tests.
- Eight-input GPIO-only cycle `db1b1348-c10e-438e-8925-3164d61f4da3` passed
  profiles 0→1→2→3→0 for ten seconds each, 123 checks each.
- Clean candidate job `552f77f2-28a5-4e5f-b55c-ef44f107dc62` passed profiles 2
  and 3 for 60 seconds each, 131 checks each. It used a clean rebuild of
  `086d44d`, HEX SHA-256
  `dd37617356911ded1583c73c8981ea2a4d737c34062f8f20a991a194902e3a0b`.
- A clean rebuild of `c96bdbd` with `SOURCE_DATE_EPOCH=1788552674` produced
  exactly the successful physical test's HEX, SHA-256
  `7824c6b9620074da7da6eb31fc2ec4f1294af0d1f6829cb55bd77afeeaf65681`.
- GPIO-only job `110f8ca6-41e4-4ffa-ad94-3efd01161eb9` passed sixteen-input
  profiles 1, 2 and 3 for ten seconds each, 126 checks each, then failed the
  full-rate STOP bank-skew check. The partial sequence's overall result is FAIL;
  the three preceding per-profile PASS records remain independently useful.
- Full branch regression: **508 tests and 16,020 subtests passed**, no skips.
- USB fix full regression: **508 tests and 16,020 subtests passed**; subsequent
  paired-STOP runner regression: **7 tests and 22 subtests passed**. Focused
  Python lint and the pinned build passed. USB fix uses 32,760 ITCM bytes,
  preserving 34,528 bytes RAM1 stack/local headroom and 4,096 bytes RAM2 free.
- Final clean-source regression: **508 tests and 16,021 subtests passed**, no
  skips. The thin-sketch guard correctly failed while temporary Serial tracing
  was present; removing that diagnostic restored the full gate. No guard was
  disabled or excluded. Final main wrapper regression: **7 tests passed**.
- Main experiment-wrapper tests: **5 passed**. Focused Python lint passed.
- Pinned Teensy build passed: RAM1 stack/local headroom 34,528 bytes; RAM2 free
  4,096 bytes. No memory-capacity gate was weakened.
- The first full-suite attempt exposed a four-byte reservation expectation needing
  update and a system Python missing the packaging `build` dependency. The final
  gate used the existing complete root virtual environment; both issues were
  resolved, not excluded.

## Reproduce individual experiments

Build the auxiliary-input branch with its `firmware/tools/build_firmware.py`.
From main, run one cold-boot cell:

```bash
python firmware/tools/run_input_isolation.py \
  --worktree .maestro/playbooks/Working/aux-input-bank \
  --evidence-dir .maestro/playbooks/Working/input-isolation/new-run \
  --case CONTROL_COMBINED --profile 0 --seconds 10
```

Use `INPUT_COMBINED` for sixteen inputs, `CONTROL_GPIO`/`INPUT_GPIO` to remove
ADC, and profiles 0–3 for the table above. Use a fresh evidence directory each
time. Add `--cycle` for 0→1→2→3→0 without reflashing; add `--diagnostic` only
for the separate paired-bank diagnostic.
Use `--profiles 1 2 3` to test lower rates independently of the known full-rate
failure. Sequences stop on their first failure and retain every completed cell.

After short cells pass, repeat each matched eight/sixteen pair for 60 seconds.
The tool refuses stale HEX/manifest combinations, pins board/build identity,
keeps credentials out of evidence, and distinguishes infrastructure failures
from firmware-test failures.

The board has been recovered; no additional signal wires are needed for this
matrix. Unstimulated capture cannot establish external pin order, edge fidelity,
analog performance or electrical timing.
