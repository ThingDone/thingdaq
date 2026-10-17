---
type: result
title: 600 MHz Repeated Combined-Capture Thermal Test
created: 2026-10-16
tags:
  - reliability
  - temperature
  - clocks
related:
  - '[[Clock528-20261013]]'
  - '[[Reliability-20261011]]'
---

# 600 MHz repeated combined-capture thermal test

**Maximum sampled die temperature: 68.597 °C (68.6 °C).** Three successive
600-second captures completed with both 12-bit ADC channels and all sixteen
GPIO inputs at 1 MS/s each. Runs 2 and 3 passed all 131 checks. Run 1 failed
one parser-error check, so this is not a three-pass reliability qualification.

[Follow-up parser investigation](parser600-investigation-20261017.md): three
additional ten-minute captures and forty short session/START/STOP repeats passed.
The original rejection did not recur; its missing bytes prevent root-cause
classification, and run 1 remains failed.

| Run | Capture | Die temperature before → after | Sampled maximum | Acceptance |
| --- | ---: | --- | ---: | --- |
| Smoke | 60 s | 37.3 → 49.6 °C | 49.6 °C | PASS, 131 checks |
| 1 | 600 s | 46.5 → 66.1 °C | 66.1 °C | FAIL: one parser error; 130/131 checks passed |
| 2 | 600 s | 57.5 → 67.4 °C | 68.0 °C | PASS, 131 checks |
| 3 | 600 s | 61.2 → 68.0 °C | 68.6 °C | PASS, 131 checks |

The maxima increased on each repeat, with a smaller increase on the third.
During the last two minutes of run 3, samples ranged from 67.983 to 68.597 °C.
The rig uploads/resets between jobs: the intervals between the previous final
and next initial temperature readings were 42.85 and 31.85 seconds. No deliberate
cooldown was inserted, but these are three captures rather than one uninterrupted
30-minute stream. The first failure was reviewed before the second submission.

## Configuration and streaming result

Teensy 4.0 serial **20428100**, immutable image `thingdaq-6c8a85596662e413`:
600 MHz CPU, 150 MHz IPG, 37.5 MHz ADC clock, and 24 MHz PIT. The image uses
fixed 1 MHz acquisition scheduling, normal ADC frames (506 pairs per frame
in sixteen-input mode), standard Adler-32, and the current four-generation ADC
DMA lookahead. Only the core clock differs from the normal fixed-rate clock
selection. Watchdog initialization remains disabled.

All three long runs measured approximately 999,997–999,999 ADC pairs and GPIO
samples per second. Their DMA, sequence/loss, paired-bank, rate, and final
conservation checks passed. Both GPIO banks captured exactly 600,269,824 samples
in each of runs 1 and 2, and 600,277,920 in run 3, including warmup and drain.
All paired-generation skew counters were zero. Partial samples discarded at
STOP remain distinct from active capture loss.

The only failed acceptance predicate was run 1's
`host.parser_errors: expected 0, got 1`. Its original harness retained neither
the rejection category nor offending bytes for a final-check failure. Its type,
time, and cause are therefore unresolved; it must not be called a checksum
failure, attributed to temperature, or dismissed as startup noise.
The initial upload also needed a service-managed programming retry before the
capture began. The saved service output preserves that incident separately.

After reviewing run 1, two more measurements used the same firmware and strict
acceptance rules. Run 3 additionally retained bounded parser diagnostics:
at most four rejected frames with reason, bytes, and timestamp, plus final
parser counters even when acceptance fails without an exception. Its final
counters show **zero header, checksum, or payload errors and zero discarded
bytes** across 3,674,690,928 received bytes. No rejection was recorded. This
improves future diagnosis; it does not explain or regrade run 1.

## Temperature interpretation and decision

The existing firmware die sensor was polled before capture, approximately every
ten seconds while running, and after STOP. Transient NOT_READY replies were
retained and retried through the same serial owner. The existing 80 °C campaign
abort remained active and was never reached.

**600 MHz with a heatsink is a reasonable provisional engineering direction**
for thermal margin. These measurements do not establish that a heatsink is
strictly required, how effective one would be, or a worst-case operating limit.
Ambient temperature and cooling configuration were not independently measured;
68.6 °C is the maximum sampled in this campaign, not a guaranteed upper bound.
No external stimulus, analog accuracy, or GPIO edge fidelity was graded.
The unresolved parser rejection still prevents a clean reliability claim.

The 600 MHz research image is left flashed, with the final capture stopped.
The published 450 MHz release default and SDK clock contract remain unchanged.
Use the independent validator for this explicit 600 MHz selection; the public
SDK is not qualified for it. Postflight service health was healthy with an
empty queue.

## Provenance and validation

The clock-selection implementation is commit `dad0eeb`; bounded parser evidence
is commit `874a912`. The tested image's base firmware source fingerprint is
`c3214f143592dbc858cf5fc4ae7d20417e789c3564f177915ed96f04a5ec45bc`, verified
against committed inputs. Its frozen manifest retains its actual pre-commit
dirty-state provenance and source-derived build timestamp; it was not relabeled
or rebuilt between runs. The parser diagnostics did not change firmware bytes.

All target binary-layout and memory gates passed: 34,464 bytes remain for RAM1
locals/stack and 4,096 for RAM2 heap. Firmware regression validation passed
243 tests and 836 subtests, with three intentionally unsupported equal-rate /
fixed-rate combinations skipped. The subsequent parser-diagnostic suite passed
12 tests and 29 subtests, including bounded corrupt-frame retention,
resynchronization, and evidence preservation on final acceptance failure.
All 111 generated protocol outputs remain current; changed Python files pass
Ruff and whitespace checks.

The [machine-readable evidence](clock600-thermal-20261016.json) preserves all
four results, failures, temperature samples, metrics, source identities, and
artifact/program/result hashes. Frozen HEX files, manifests, submitted programs,
and complete service replies are retained locally under
`doc/results/raw/clock600-20261016/`.

## Reproduction

```bash
.venv/bin/python firmware/tools/build_input_experiment.py \
  --cpu-mhz 600 --release-fixed-1mhz
.venv/bin/python firmware/tools/run_input_isolation.py \
  --worktree "$PWD" \
  --build-dir firmware/build/input-experiment-release-600 \
  --evidence-dir doc/results/raw/clock600-new-run \
  --case INPUT_COMBINED --profile 4 --seconds 600 --temperature \
  --service http://192.168.150.14:5000
```

Use a fresh evidence directory per repeat. Review any failure and preserve its
original grade; never overwrite or count it as a passing run.
