---
type: result
title: Larger ADC Frame Experiment
created: 2026-09-18
updated: 2026-09-23
tags:
  - performance
  - frames
  - experiment
related:
  - '[[Protocol-V2]]'
---

# Larger ADC frame experiment

Branch: `experiment/larger-adc-frames`, based on the qualified v1.1.0
checksum experiment at `8dd4929`. This excludes the unqualified runtime
hardening changes on newer main.

**Larger ADC frames reduced measured processing cost while sustaining the same
1 MHz acquisition rates.** After fixture recovery on 2026-09-23, all nine
comparison captures passed. Median host acceptance CPU time fell by 20.2%,
and the GPIO processing counter fell from 15.59% to 14.37%. This establishes
additional processing headroom; maximum sustainable acquisition throughput
was not tested. The earlier programming failure is retained below.

## Change and expected effect

The opt-in `--large-adc-frame` build doubles the ADC payload in sixteen-input
mode. It uses the existing 4096-byte packet slots and the existing ADC raw
buffer capacity. GPIO frames, eight-input mode, acquisition rates, packet
count, and pool allocation are unchanged.

| Quantity | Smaller ADC frames | Larger ADC frames |
| --- | ---: | ---: |
| ADC frame bytes, including header and trailer | 2072 | 4096 |
| ADC payload bytes | 2024 | 4048 |
| ADC pairs per frame | 506 | 1012 |
| GPIO frame bytes | 4096 | 4096 |
| GPIO samples per frame | 2024 | 2024 |
| ADC frame coverage at 1 MHz | 506 microseconds | 1012 microseconds |
| Combined data frames per second, calculated | 2470.36 | 1482.21 |
| Combined sample payload bytes per second | 6000000 | 6000000 |
| Combined framed bytes per second, calculated | 6118577.08 | 6071146.25 |
| Packet pool bytes | 819200 | 819200 |

This reduces ADC frame frequency by 50%, combined frame frequency by 40%, and
framed USB bytes by approximately 0.775%. The calculation counts the 44-byte
header and retained 4-byte trailer; it excludes USB transaction overhead and
control traffic. It predicts 47,430.83 fewer framed bytes per second, not a
measured increase in acquisition rate. The cost is an extra 506 microseconds
of ADC frame-fill time. The live comparison below measures processing cost.

Both comparison variants disable data checksum calculation and retain
zero trailers. Controls remain checksummed. Neither is a production protocol
change. The ordinary SDK is not adapted to this research wire format.

## Implementation and validation

`input_experiment_profile.h` and `rate_profile_table.h` derive the larger ADC
count and coverage only for the explicit build flag. `stream_layout.h`,
`protocol.cpp`, and `acquisition_controller.cpp` use that count for framing,
reported metadata, and DMA capture length. Since ADC length no longer
distinguishes eight- and sixteen-input operation, the experimental capture
interface conveys auxiliary-bank mode explicitly to select DMA priorities.
The packet pipeline and independent host validator also account for the new
two-ADC-to-one-GPIO frame ratio, retaining time-based fairness and skew checks.

`build_checksum_experiment.py` salts the build identity with frame selection
and records the incompatible frame layout in the manifest.
`run_input_isolation.py` requires a matching `--frame-experiment` flag and
uses the standalone validator. Its isolated adapter supplies independent
larger-frame expectations while retaining strict continuity, loss, counter,
control-checksum, and ADC-range checks. The adapter also records host process
CPU and wall time around each complete acceptance cell, including setup and
drain; these are separate from capture-only throughput and firmware counters.

The target build passed the pinned compiler and linked-memory gates.
RAM1 free for locals remains 34,528 bytes; RAM2 free for heap remains 4096 bytes.
The larger-frame image is identified in [frame-performance.json](frame-performance.json).

Local validation passed 47 tests and 549 subtests across the new frame
experiment, input isolation, protocol/checksum primitives, ADC DMA/packer,
combined acquisition, packet pipeline, fake-device rig, and repository checks. The new
native test encodes and decodes both ADC and GPIO layouts at every profile
with the frame flag both enabled and disabled, and verifies unchanged packet
storage and equal-time packet accounting. The host test accepts the new
two-to-one interleaving and rejects an incorrect ADC timestamp progression.

## Initial live attempt, 2026-09-18

Job `284894cb-2586-4a29-a5c2-261148308280` requested three ten-second
INPUT_COMBINED captures at profile 4 using the previously successful
checksum-disabled 2072-byte ADC image, build `thingdaq-e31051d44e59d73c`.
The service health check was healthy and idle.

The loader could not soft-reboot the Teensy: USB control transfer returned
“Protocol error.” It then waited for the device and timed out after 75 seconds.
The runner classified this as `INFRASTRUCTURE_FAIL`; there are no capture
measurements. No further flash was attempted that day, and the running image
was not re-identified. The last previously verified image was the published
checksummed v1.1.0 baseline.

Complete local raw evidence is in
`/home/bill/agents/teensy_daq/doc/results/raw/frame-performance/adc2072-none/`.
The compact tracked JSON preserves the firmware identities and loader output.

## Live comparison after fixture recovery, 2026-09-23

The user reset the fixture. We ran three ten-second captures with smaller
frames, three with larger frames, and three more with smaller frames to
check drift. Each group used a fresh firmware upload; its three captures
shared one boot. All nine captures passed 131 checks each, including loss
accounting, frame sequences, timestamps, ADC ranges, and paired-bank counters.
No sequence gaps, reported sample loss, or disconnects occurred.

Both images were built from the same firmware source fingerprint on this
branch, with data checksums disabled, a 450 MHz core, sixteen GPIO inputs,
and profile 4: 1 million ADC pairs and 1 million GPIO samples per second.
The sole build selection difference was the larger-ADC-frame flag.

| Median metric | Small frames, before (3 runs) | Large frames (3 runs) | Small frames, after (3 runs) |
| --- | ---: | ---: | ---: |
| Host acceptance CPU seconds | 3.384 | 2.695 | 3.370 |
| Host CPU as percent of one core | 31.28% | 24.93% | 31.16% |
| GPIO processing counter | 15.59% | 14.37% | 15.59% |
| ADC pairs per second | 999988 | 1000002 | 999998 |
| GPIO samples per second | 999887 | 1000103 | 999897 |
| ADC frames per complete capture | 20316 | 10152 | 20316 |
| GPIO frames per complete capture | 5079 | 5076 | 5079 |
| STATUS p99 latency | 11.012 ms | 11.089 ms | 10.980 ms |
| Transmit queue peak, frames | 33 | 2 | 14 |

Pooling the six smaller-frame captures gives median host CPU time of 3.3773
seconds versus 2.6945 seconds for larger frames: **20.2% less host CPU time**.
Normalized by each cell's wall time, median CPU utilization falls from 31.22%
to 24.93% of one core, a 20.1% relative reduction. CPU time ranges are
3.0910–3.4673 seconds for smaller frames and 2.6928–2.9273 seconds for larger
frames. Host timing includes acceptance setup, warmup, capture, and drain
(about 10.81–10.82 seconds wall time), not only the timed ten-second window.

The GPIO processing counter drops by **1.22 percentage points**, or **7.8%
relative**. It measures the auxiliary GPIO packer's active-cycle accounting;
it is not total MCU utilization. No inference about total ADC/MCU CPU cost
or maximum USB throughput is justified by that counter alone.

The return to the original CPU levels in the final smaller-frame group
supports a frame-size effect rather than simple time drift. This remains a
short comparison on one board and one host, without randomized order or a
long-duration soak. STATUS latency did not materially improve. Queue peaks
are frame counts, whose byte sizes differ between variants. Frame counts
include warmup and drain; rates use the timed capture window. Data corruption
detection remains disabled in both experimental conditions, and no external
electrical stimulus was declared.

| Group | Rig job | Build ID |
| --- | --- | --- |
| Smaller, before | `5c9878b1-1186-4cce-a463-51029be22315` | `thingdaq-bf3cc7acb836dfe0` |
| Larger | `a1143cce-1112-411b-be2a-c96b77032e68` | `thingdaq-f0ec13cc42c5e848` |
| Smaller, after | `ece2bd06-9abf-4907-a1ac-e2c97342836f` | `thingdaq-bf3cc7acb836dfe0` |

All repetitions, identities, SHA-256 hashes, aggregate calculations, and
restoration evidence are retained in [frame-performance-live.json](frame-performance-live.json).
Full local artifacts remain under
`/home/bill/agents/teensy_daq/doc/results/raw/frame-performance/2026-09-23-*`.

The published checksummed v1.1.0 firmware, build
`thingdaq-636aebbecbf70691`, was restored afterward. Job
`54af157f-f01f-4969-8608-d357a7b2e6ee` passed a further ten-second capture
and all 131 checks. The board is therefore back on the published baseline.

## Reproduction

From this branch's checkout, build both variants with the pinned timestamp:

```bash
SOURCE_DATE_EPOCH=1788585013 python firmware/tools/build_checksum_experiment.py --mode none
SOURCE_DATE_EPOCH=1788585013 python firmware/tools/build_checksum_experiment.py --mode none --large-adc-frame
```

Use `run_input_isolation.py` with the corresponding explicit build directory,
`--case INPUT_COMBINED --profile 4 --profiles 4 4 4 --seconds 10`,
`--checksum-experiment`, and a fresh evidence directory for each job.
Add `--frame-experiment` only for `checksum-none-adc4096`. Run one job at a
time. Compare rates, frame counts, loss counters, host acceptance CPU/wall
time, status latency, and queue peaks. The existing
`firmware_processing_cpu_basis_points` metric measures GPIO packer work,
not total MCU utilization or ADC processing cost.

Repeat the smaller-frame condition after the larger-frame condition to
check drift, then restore and validate the published v1.1.0 baseline. No
electrical input stimulus was declared, so input transitions are outside this
experiment's evidence.
