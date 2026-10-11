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
| Same larger-frame image, separate upload | `thingdaq-2e5796cfcae55c9f` | 600 s | PASS: 131 checks |

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

The initial larger-frame endurance run captured for 600.010 seconds, with
593,164 ADC frames and 296,582 GPIO frames including warmup/drain. Measured
timed rates were 999,999.15 ADC pairs/s and 999,997.46 GPIO samples/s. The last
temperature sample was 56.930 degrees C. No capture acceptance limit changed.

## Corrected implementation target benchmark

The original baseline and corrected final default image were flashed
separately and benchmarked through the public SDK's standard ID 1 command.
Each case uses the existing Phase-05 shape: 4,092-byte frame coverage, four
batches of 256 operations, on Teensy 4.0 at 450 MHz. Both jobs passed and
reported watchdog disabled, 28,664 stack bytes free, and no lookup table.

| Memory/cache | Original cycles/byte | Corrected dual-lane cycles/byte | Reduction in checksum time |
| --- | ---: | ---: | ---: |
| Hot DTCM | 4.023941 | 3.030792 | 24.68% |
| Cold-invalidated OCRAM | 4.812332 | 3.792480 | 21.19% |

These compare `thingdaq-b86c963eb8e1c895` with `thingdaq-fce489cabb418f9d`.
They measure checksum execution, not total MCU CPU, USB throughput, or a
higher physical sample rate. The cold metric includes the benchmark's cache
handling. The raw results retain complete returned timing fields.

## Final candidate endurance

The corrected larger-frame image `thingdaq-c32f1eb37ab5dcac` passed a separate
600-second combined 16-input run, job `94d2ff4f-1247-49a1-8db7-38cb1906ae98`,
with all 131 checks passing. The run measured 600.0049 seconds, 999,997.98 ADC
pairs/s and 999,999.67 GPIO samples/s. Including warmup and drain, the validator
accepted 593,158 ADC frames and 296,579 GPIO frames. No checksum, sequence,
DMA, conservation or loss acceptance check failed. Maximum observed host
receive gap was 24.54 ms; the transmit queue high-water mark was 28 frames.
Die temperature was 47.106 degrees C before and 58.158 after, with a sampled
maximum of 58.772 degrees C.

This final image includes the modular Adler correction and comment-only sketch
cleanup. Its firmware source fingerprint and that of the corrected default
image were checked against the committed inputs at `e57a3cd`. The frozen build
manifests honestly retain their earlier dirty-worktree provenance; the images
were not rebuilt or relabeled after testing. Both checksummed larger-frame
images passed ten minutes, but only this second image is the final candidate.
These two passes do not establish an MTBF or explain the failed baseline.

The same final larger-frame image then passed four 20-second combined cells
in the order 8 -> 16 -> 8 -> 16 inputs without reflashing between cells, job
`23887e0c-3055-43de-9d1c-984920e6199e`. The eight-input cells passed 128 checks
each and the sixteen-input cells passed 131 each (518 total). This exercises
the explicit auxiliary-bank DMA priority selection, STOP/reconfiguration,
frame shapes, checksums and stream conservation across width changes.

The rig was then restored to the normal-frame optimized-Adler build
`thingdaq-fce489cabb418f9d`. Public-SDK job
`a88b21ba-d0b1-4cf5-8446-5cda72b2def2` passed four 20-second combined cells
in the order 8 -> 16 -> 8 -> 16 inputs, with no observed stream gaps,
queue losses, or parser corruption. Only this job's container received a
two-core CPU quota (200,000 / 100,000 microseconds); the service default was
unchanged. This is short-duration SDK validation of the normal frame format,
not larger-frame SDK support or a long-duration SDK qualification. The final
rig-service health check reported healthy with an empty job queue.

The [machine-readable evidence](reliability-20261011.json) records every
completed job, including the failed baseline, identities, artifact/program
hashes, temperature samples, and acceptance results. Full local submissions
and service replies remain under `doc/results/raw/reliability-20261011/`.

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
original branch and clean tracked state after verification. The final build
configuration fixtures and documentation checks passed 23 tests and 751
subtests; fixture symbol addresses now account for the larger Adler function.

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

Acquisition tests use Teensy 4.0 serial 20428100, 450 MHz core, 37.5 MHz IPG-derived
ADC clock, 24 MHz crystal-derived PIT triggers and fixed 1 MS/s ADC/GPIO.
The watchdog remains disabled. No external electrical stimulus is connected;
streaming results do not qualify analog accuracy, aperture timing, or external
digital transitions. Passing runs do not establish a fix for the intermittent
ADC fault. See [[ADC-Clock-Options]] for why a 528 MHz CPU plus the internal
ADC oscillator was not enabled at 1 MS/s.
