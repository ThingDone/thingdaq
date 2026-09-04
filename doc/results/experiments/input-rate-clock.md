---
type: experiment
title: Equal-rate sixteen-input and CPU-clock experiments
created: 2026-09-04
tags: [thingdaq, firmware, input-isolation]
related: []
---

# Equal-rate sixteen-input and CPU-clock experiments

Follow-up to [input isolation](input-isolation.md). The question is whether
**each of the two ADC channels and all sixteen GPIO inputs** can sample at
1 MHz, or at 500 kHz, with a 600 or 450 MHz CPU.

## Results

Both CPU speeds passed **1 MHz → 500 kHz → 1 MHz**, 60 seconds per cell,
including every STOP. The clean committed **450 MHz build also passed five
minutes at 1 MHz everywhere**, with successful shutdown and no active loss.

| Per-channel ADC rate / sixteen-input GPIO rate | 600 MHz CPU | 450 MHz CPU |
| --- | --- | --- |
| 1 MHz / 1 MHz | PASS, three 60-second cells | PASS, 300 seconds plus two 60-second cells |
| 500 kHz / 500 kHz | PASS, two 60-second cells | PASS, two 60-second cells |

The five-minute job measured **1,000,002.93 ADC pairs/s** (that rate on each
channel) and **1,000,001.24 GPIO samples/s** (all sixteen bits per sample).
It delivered 593,437 ADC frames and 148,359 GPIO frames, with zero paired-bank
skew events. STATUS p99 was 11.18 ms. STOP's 155 ADC-pair and 661 GPIO-sample
partial tails were separately accounted, not active-stream loss. Job:
`1fb36ef7-de27-4515-853d-3bd4bc18adf9`; clean build `thingdaq-e4e367ea1b8a876a`.

Clean-source confirmation at 600 MHz passed both rates for 60 seconds each:
job `1205dd3b-8e3f-4402-b030-963fe1110332`, build `thingdaq-03891c9370ac0cbd`.
The initial matched sequences used a pre-commit candidate; the final source
also corrects the separate clock-diagnostic response's fractional-cycle
calculation. Both versions, their exact binaries and their provenance are
distinguished in the run index.

The clean 450 MHz build additionally passed 500 kHz everywhere for 60 seconds,
including STOP: job `ee1e7dc5-f8b7-4dd5-b863-e8c4bdb67b09`. Thus both requested
equal-rate modes have physical acceptance on the final committed source at
both CPU speeds. The campaign retained **15 passing cells and two failures
across ten jobs**, including the early encoder defect and the separate fast
eight-input/450 MHz fault. The last job completed in IDLE; no capture is left
running.

### The fast eight-input mode is not qualified at 450 MHz

The clock-only control kept the old ADC 1 MHz / GPIO 4 MHz profile and selected
eight inputs. It passed configuration/clock checks and streamed about **45.015
seconds**, then stopped automatically before completing the requested 60 seconds.
The failure snapshot reports two ADC DMA error events and one ADC completion
mismatch, after 44,481 ADC and 44,482 GPIO frames were transmitted. The precise
trigger is unresolved; this is not a configuration rejection or a successful
60-second run with an inconvenient STOP result.
The DMA-event counters also cover software pipeline-alignment failures in
`servicePendingDmaPair`; they do not by themselves prove a silicon DMA error.

Job `d2903962-b92e-4618-9e63-df926606fcf7` remains **FAIL**. The prior 600 MHz
eight-input/full-rate passes do not establish 450 MHz reliability. Conversely,
this separate high-GPIO-rate failure does not invalidate the sixteen-input
equal-rate passes. Do not infer an absolute hardware limit from one failure.

Two lower-rate clock-only controls with sixteen GPIO inputs also passed at
450 MHz: ADC 250 kHz / GPIO 1 MHz and ADC 125 kHz / GPIO 500 kHz, ten seconds
each with successful STOP. These retain the original 4:1 table; job
`73ca5240-7b6a-4565-8db7-f33084971027`.

These are unstimulated input captures. They validate reported sample throughput,
frame/timestamp continuity, checksums, bank accounting, control responsiveness
and shutdown. They do not validate external signal fidelity, analog accuracy,
temperature or lifetime. The ADC channels retain their half-period phase offset;
equal rates do not imply simultaneous apertures.

## What changed to make this a valid experiment

The previous candidate enforced GPIO = 4 × ADC, including one ADC packet for
each GPIO packet. Simply lowering the GPIO timer would therefore have caused
configuration, scheduling and packet-validation failures unrelated to hardware
capacity.

The isolated `experiment/input-rate-clock` branch extends auxiliary-input
commit `086d44d` with two explicit build selections:

- CPU 600 or 450 MHz, with the same 150 MHz IPG, 37.5 MHz ADC, 24 MHz PIT and
  8 MHz timestamp clocks. DWT-based deadlines, utilization denominators and
  timing expectations follow the CPU clock. Hardware adapters check actual
  CPU/bus frequencies; the host also checks reported acquisition clocks.
- Original 4:1 rates, or equal rates. The equal-rate table adjusts PIT loads
  and frame periods without changing DMA bank widths or packet sizes.

One sixteen-input GPIO packet contains 2024 samples; one ADC packet contains
506 pairs. Equal rates require **four ADC packets per GPIO packet**. Firmware
scheduling and host continuity checks use that time relationship. All active
loss, checksum, timestamp, bank-skew and STOP checks remain enabled. Inherited
retention metadata remains a conservative bound, not a newly qualified storage
capacity guarantee for unequal-duration packets.

The first equal-rate hardware attempt failed after about 2.4 ms because the
packet encoder still required equal ADC/GPIO packet durations. It emitted four
ADC frames, rejected the first GPIO frame, and stopped acquisition. The host
regression reproduced that rejection; fixing the encoder's coverage rule enabled
the subsequent captures. That failed job is retained, not relabeled PASS.

450 MHz also requires rational diagnostic timing: a 4 MHz event period is 112.5
CPU cycles. The implementation reuses the approach in `experiment/clock-450mhz`
instead of truncating the period to 112 cycles. CPU-only controls retain the old
rate table to separate this adaptation from equal-rate acquisition.

## Compatibility and proposed limits

These are **research builds, not production firmware**. They advertise an
experiment-local table using existing profile slots; ordinary protocol-v2 clients
should reject it. Frozen protocol JSON/generated files are unchanged. A release
needs explicit public rate profiles, API support and firmware configuration
limits rather than silently changing the meaning of existing profile IDs.

The evidence supports **capping sixteen-input GPIO at 1 MHz while retaining
1 MHz on each ADC**, with 500 kHz everywhere as a lower-bandwidth option.
450 MHz is a viable experimental CPU selection for those rates. If retaining
the eight-input/GPIO-4-MHz mode, keep its previously tested 600 MHz clock until
the separate 450 MHz fault is understood.

No production limit has been imposed yet. A successful bounded capture does not
establish unlimited endurance or repair the separate high-GPIO-rate failures.

## Validation

- Experimental source checkpoint: `db5d775`, pushed to
  `experiment/input-rate-clock`. Main's manifest-selecting runner is `4a86412`.
- Full clean regression: **514 tests and 16,022 subtests passed**, no skips.
  Added real C++ coverage for all four CPU/ratio combinations, scheduler
  dividers, ADC phase, packet admission/fairness and rational clock-diagnostic
  encoding. Added host weighted-continuity and build-identity tests.
- Main runner: **8 tests passed**; focused lint and whitespace checks passed.
- Pinned Teensy 4.0/core 1.62.0/Arm GNU 15.2.1 builds passed for equal-rate
  600/450 MHz, original-ratio 450 MHz, and the normal default 600 MHz builder.
  Equal-rate variants use 32,712 ITCM bytes; normal/old-ratio variants use
  32,760. All preserve 34,528 bytes RAM1 stack/local headroom and 4,096 bytes
  RAM2 free. No linker or capacity gate was weakened.
- Earlier validation failures were corrected: the source-token check now
  references the selected CPU frequency, documentation has required front
  matter, and fractional-cycle diagnostic calculations are consistent in both
  producer and response validator. These gates were rerun, not skipped.

## Reproduction and evidence

Build from `experiment/input-rate-clock`:

```bash
SOURCE_DATE_EPOCH=1788552674 python firmware/tools/build_input_experiment.py \
  --cpu-mhz 450 --equal-rates
```

From main, submit a single cold-boot job:

```bash
python firmware/tools/run_input_isolation.py \
  --worktree .maestro/playbooks/Working/input-rate-clock \
  --build-dir .maestro/playbooks/Working/input-rate-clock/firmware/build/input-experiment-equal-450 \
  --evidence-dir .maestro/playbooks/Working/input-isolation/new-equal-rate-run \
  --case INPUT_COMBINED --profile 0 --profiles 0 1 0 --seconds 60
```

Equal-rate profile 0 is 1 MHz everywhere; profile 1 is 500 kHz everywhere.
Omit `--equal-rates` at build time for the original 4:1 clock-only controls.
The runner derives CPU/rate selections from the hash-checked build manifest and
checks that its CPU selection agrees with the compiled target. Each variant has
a distinct build identity salted with its clock and rate selections.

The [machine-readable run index](input-rate-clock-runs.json) accompanies this report. Complete submitted HEX
files, manifests, rig programs, provenance and service results remain in the
indexed directories under `.maestro/playbooks/Working/input-isolation/`.
