# Independent sampling-rate and input-width experiments

## Current answer

Several independent software defects were hidden behind the original mandatory
paired-bank diagnostic. They are now fixed on `experiment/aux-input-bank`;
the experiment runner and this report are on `main`. The experimental firmware
has **not** been merged into production main.

**One physical control passes:** eight digital inputs plus both ADCs, five seconds
at ADC 1 MHz / GPIO 4 MHz. All active loss/error, chronology, checksum, rate,
conservation and cleanup checks passed. The next upload failed; subsequent
normal power-cycle submissions could not enumerate the Teensy. Therefore the
remaining rate/width comparisons are **blocked, not feature failures**.

No new wires or loopbacks are required for these tests.

## Controlled experiment design

All cells use the same candidate, 600 MHz CPU, raw/uncompressed data, Adler-32,
unstimulated inputs and no output engine. The paired-bank diagnostic is opt-in,
not a prerequisite. These are runtime-feature controls in the experimental
firmware, not separate builds with the unused feature compiled out.

| ADC / GPIO rate | Eight inputs + ADC | Sixteen inputs + ADC | GPIO-only controls |
| --- | --- | --- | --- |
| 1 MHz / 4 MHz | **PASS**, 5 seconds | Not run: upload/board detection failed | Not run on repaired candidate |
| 500 kHz / 2 MHz | Not run: rig unavailable | Not run | Not run |
| 250 kHz / 1 MHz | Not run: rig unavailable | Not run | Not run |
| 125 kHz / 500 kHz | Not run: board detection failed | Not run | Not run on repaired candidate |

The rate experiment changes only the profile with eight inputs selected.
The width experiment compares eight versus sixteen inputs at the same profile.
GPIO-only counterparts remove ADC interaction. The separate diagnostic tests
both GPIO DMA banks without grading stream bandwidth. A final 0→1→2→3→0 profile
cycle is implemented to check reselection without reflashing, but has not run
on hardware yet.

## Defects and fixes

| Defect | What actually happened | Fix and evidence |
| --- | --- | --- |
| Command-size mismatch | v2 CONFIGURE is 64 bytes, but firmware retained v1's 56-byte limit and 59-byte parser buffer. Every valid v2 configuration was rejected before rate/pin testing. | Version-aware limit, 67-byte parser storage and 68-byte reservation. New C++ test first reproduced all eight width/rate failures, then passed every fragmentation boundary. Physical CONFIGURE now passes. |
| Status bits mistaken for enables | Rate setup required the entire ADC_ETC DMA_CTRL register to be zero. Boot completion flags left `0x00110000` latched even though requests were disabled. START rolled back with platform-apply failure. | Check only enable bits; preserve W1C status during rollback. Temporary hardware trace identified the register value; the real target adapter is now exercised with a W1C-aware fake. Physical START and capture now pass. |
| Truncated slow-rate ADC delay | Teensy core 1.62's INIT_DELAY macro masks to eight bits. Required delays of 300 and 600 IPG cycles would become 44 and 88. The old readback check used the same defective macro. | Encode the actual 16-bit register field in both scheduler and trigger adapter. Real-adapter tests verify register values 75, 150, 300 and 600. Slow-rate physical timing remains untested. |
| Colliding DMA priorities | Paired GPIO setup assigned channels 2/3 priorities 1/0 without updating inactive ADC channels 0/1, whose reset priorities are 0/1. Standalone GPIO and switching back from INPUT could also leave duplicates. | Configure all four reserved priorities as a unique permutation: legacy 2/1/0/3, INPUT 3/2/1/0. Host tests cover inactive channels and repeated mode changes. This is a confirmed static defect matching the original diagnostic failure; physical paired-bank reproduction is still pending. |
| Misleading runner grading | The runner discarded v1 generic rejections, required both banks in the eight-input control, graded the paired diagnostic against v1 primary BITER/priority, and expected active metadata after STOP. | Accept only the legitimate legacy rejection shape, make diagnostic optional, expect primary BITER 2024/priority 1, and distinguish IDLE metadata from completed-run counters. Active-loss and STOP-tail checks remain enabled. |

Hardware register semantics were checked against
[NXP's ADC_ETC driver documentation](https://mcuxpresso.nxp.com/api_doc/dev/4784/a00009.html)
and [NXP's RT1062 register definitions](https://github.com/nxp-mcuxpresso/legacy-mcux-sdk/blob/main/devices/MIMXRT1062/MIMXRT1062.h).
The priority rule is documented in
[NXP's eDMA reference material](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/186373/1/IMXRT1050RM.pdf).

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

The [machine-readable run index](input-isolation-runs.json) preserves all eleven
jobs, identities, results and raw-result hashes. Complete HEX images, manifests,
submitted programs and service responses remain under
`.maestro/playbooks/Working/input-isolation/`.

## Validation and source checkpoints

- `b38bcdd`: command parser fix and independent diagnostic selection.
- `c96bdbd`: DMA-priority, ADC register and STOP-grading fixes.
- A clean rebuild of `c96bdbd` with `SOURCE_DATE_EPOCH=1788552674` produced
  exactly the successful physical test's HEX, SHA-256
  `7824c6b9620074da7da6eb31fc2ec4f1294af0d1f6829cb55bd77afeeaf65681`.
- Full branch regression: **508 tests and 16,020 subtests passed**, no skips.
- Main experiment-wrapper tests: **5 passed**. Focused Python lint passed.
- Pinned Teensy build passed: RAM1 stack/local headroom 34,528 bytes; RAM2 free
  4,096 bytes. No memory-capacity gate was weakened.
- The first full-suite attempt exposed a four-byte reservation expectation needing
  update and a system Python missing the packaging `build` dependency. The final
  gate used the existing complete root virtual environment; both issues were
  resolved, not excluded.

## Resume after rig recovery

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

After short cells pass, repeat each matched eight/sixteen pair for 60 seconds.
The tool refuses stale HEX/manifest combinations, pins board/build identity,
keeps credentials out of evidence, and distinguishes infrastructure failures
from firmware-test failures.

The remaining prerequisite is **recovering the undetected Teensy**, not attaching
signal wires. Unstimulated capture cannot establish external pin order, edge
fidelity, analog performance or electrical timing.
