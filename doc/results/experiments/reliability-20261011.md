---
type: result
title: Checksummed Acquisition Reliability Integration
created: 2026-10-11
tags:
  - reliability
  - checksum
  - adc
related:
  - '[[ADC-Clock-Options]]'
  - '[[Watchdog-Disabled-20260927]]'
---

# Checksummed acquisition integration

The standard Adler-32 implementation now uses the previously measured dual-lane
algorithm without changing algorithm ID 1, checksum values, trailers, or the
public SDK. The linked implementation is 260 bytes instead of 120, with no
lookup table. Independent per-byte reference tests include odd/even and
unaligned data, zero/all-255/patterned inputs, and multiple 5,552-byte reduction
blocks. The target build enforces the new exact implementation size and the
existing memory floors.

An additional constructed vector makes the first Adler accumulator zero at a
reduction boundary. It exposed unsigned subtraction in the imported experiment's
multi-block concatenation. The corrected implementation subtracts modulo 65521
and passes that vector too. Production frames are shorter than one reduction
block, but the public checksum function must also handle longer inputs exactly.

The larger-frame candidate reuses the earlier frame experiment, now with
checksums enabled and the current release's four-generation ADC lookahead.
Sixteen-input mode carries 1,012 ADC pairs in a 4,096-byte frame instead of
506 pairs in 2,072 bytes. Eight-input ADC framing and both GPIO layouts remain
unchanged. Packet storage remains 819,200 bytes in 200 slots. Auxiliary DMA
priority selection is explicit because ADC frame length no longer identifies
GPIO bank width. Scheduling compares equivalent time coverage.

Larger frames remain opt-in research firmware: INFO advertises the changed
layout, ordinary SDK validation rejects it, and the runner requires explicit
`--frame-experiment` agreement with the manifest. The independent wire
validator retains checksum, chronology, conservation, and loss checks. There
is no checksum-disabled adapter. Local tests corrupt encoded data to verify
that the real decoder still rejects it.

## Initial hardware comparison

| Variant | Immutable build ID | Requested capture | Result |
| --- | --- | ---: | --- |
| Unchanged September 27 main | `thingdaq-b86c963eb8e1c895` | 60 s | FAIL: ADC DMA fault after 1,016,601 captured pairs |
| Dual-lane Adler, original frames | `thingdaq-b70388a72be23267` | 60 s | PASS: 131 checks |
| Dual-lane Adler, larger ADC frames | `thingdaq-2e5796cfcae55c9f` | 60 s | PASS: 131 checks |

The baseline snapshot has two ADC DMA error events, one completion mismatch,
zero parser checksum errors, zero packet-pool exhaustions and zero ADC raw-ring
overruns. STOP recovery clears the configuration, which the next STATUS query
correctly rejects as inconsistent with an active capture. This does not identify
the initiating DMA fault; mismatch/incomplete-conversion counters can include
shutdown accounting.

Both successful captures sustain approximately 1 million ADC pairs and GPIO
samples per second with no acceptance failures. They are sequential runs with
different thermal starts, not a randomized performance comparison. The GPIO
processing counter is not total firmware CPU, and neither CPU savings nor an
increased maximum sample rate is established by these runs. These first images
precede the later multi-block Adler edge-case correction and comment-only
sketch cleanup; subsequent final-image tests are recorded separately.

## Local checks

The initial firmware/checksum/build suites passed 30 tests and 351 subtests.
The frame/layout/rig suites passed 30 tests and 29 subtests. Both default and
larger-frame target builds retain 34,464 bytes for RAM1 locals/stack and 4,096
bytes for RAM2 heap; no memory gate was relaxed. Protocol generation remains
byte-current across all 111 generated outputs.

The broad run initially exposed two pre-existing repository issues: the sketch
had 67 lines against its 65-line limit, and the unrelated untracked September
analysis lacks required front matter. Compacting comments restores the sketch
gate without changing runtime behavior. The untracked file was left untouched.
The same candidate files in an existing clean worktree passed 252 tests and
1,726 subtests, with one skip. The checksum edge-case fix and documentation
then passed 13 tests and 1,101 subtests there. That worktree was restored to its
original branch and clean tracked state after verification.

## Reproduction

Build the normal optimized-Adler firmware with `firmware/tools/build_firmware.py`.
Build the larger-frame candidate with:

```bash
.venv/bin/python firmware/tools/build_input_experiment.py \
  --cpu-mhz 450 --release-fixed-1mhz --large-adc-frame
```

Its output directory is `firmware/build/input-experiment-release-large-adc-450`.
Pass that directory to the existing `run_input_isolation.py` runner with
`--case INPUT_COMBINED --profile 4 --temperature --frame-experiment`, a fresh
evidence directory and the rig service URL. `--seconds 600` requests one
ten-minute capture. The ordinary SDK path is deliberately rejected for this
unnegotiated layout.

## Qualification boundary

All tests use Teensy 4.0 serial 20428100, 450 MHz core, 37.5 MHz IPG-derived
ADC clock, 24 MHz crystal-derived PIT triggers and fixed 1 MS/s ADC/GPIO.
The watchdog remains disabled. No external electrical stimulus is connected;
streaming results do not qualify analog accuracy, aperture timing, or external
digital transitions. Passing runs do not establish a fix for the intermittent
ADC fault. See [[ADC-Clock-Options]] for why a 528 MHz CPU plus the internal
ADC oscillator was not enabled at 1 MS/s.
