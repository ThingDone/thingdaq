---
type: experiment
title: Sixteen GPIO inputs at 4 MHz with ADC acquisition disabled
created: 2026-09-04
tags: [thingdaq, firmware, temperature, input-isolation]
related: [temperature-soaks.md, input-rate-clock.md]
---

# Sixteen GPIO inputs at 4 MHz

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

This follow-up isolates digital capture: **16 GPIO inputs at 4 MHz, both ADC
acquisition streams disabled, and a 450 MHz core**. It follows the successful
[1 MHz/500 kHz combined-input soaks](temperature-soaks.md). Pins 6–13 and 16–23
remain inputs without an external test signal.

## Results

**4 MHz is not qualified at 450 MHz with 16 inputs, even with ADC acquisition
disabled.** Both captures reached their requested duration and failed final
bank-count reconciliation. A 1 MHz control passed with the same firmware.

| GPIO rate | Capture duration | Final bank difference | Temperature before → after | Result |
| --- | --- | --- | --- | --- |
| 4 MHz | 30 s | 9 samples | 36.1 → 41.6 °C | FAIL |
| 4 MHz | 600 s | 101 samples | 37.9 → 53.2 °C | FAIL |
| 1 MHz | 30 s | 0 samples | 48.9 → 51.4 °C | PASS |

The initial 30-second capture reached STOP and then failed the final bank-count
check: one count mismatch, one generation-skew event, and nine skew samples.
Both banks completed 59,820 buffers (121,075,680 samples per bank), and all
59,820 GPIO frames were transmitted. ADC DMA loops, captured pairs, and
transmitted frames were zero. Temperature rose from 36.053 to 41.579 °C.

The ten-minute follow-up also reached STOP and failed the same check, this time
with **101 skew samples**. Both banks completed 1,186,308 buffers, and the host
received 1,186,308 GPIO frames containing 2,401,087,392 sample instants. ADC
acquisition counters remained zero. Temperature rose from 37.895 to 53.246 °C,
also the peak observed temperature. There were no reported GPIO frame drops,
raw ring overruns, hardware errors, or parser/checksum errors. The partial STOP
tail was 394 samples, separately accounted from the 101-sample bank difference.

Both 4 MHz runs remain **FAIL**, including final reconciliation; successful
streaming alone does not qualify this mode for production. The short 1 MHz
comparison used profile 2 of the same firmware, with both ADC streams disabled.
It passed all 126 checks, measured 1,000,040.55 GPIO samples/s, transmitted
14,966 frames, and reported zero generation-skew events. Both banks contributed
30,291,184 complete-buffer samples. Its 1,645-sample STOP tail was accounted
without a bank mismatch.

## Interpretation

`DualBankCaptureRing::stop` compares each bank's contribution to the unfinished
generation and increments the count/skew counters when those contributions
differ. The short run passed its active status checks and failed after STOP.
Its 1,594 discarded samples were accounted as the partial STOP tail; the
nine-sample bank difference was an additional validation failure.

Detection at STOP does not establish when the difference arose. Completed
buffers have a fixed sample count, so agreement between completed-buffer counts
does not prove that both banks observed every trigger at the same instant.
The larger difference in the longer run is consistent with accumulated drift,
but two observations do not isolate its cause. The evidence does not yet
distinguish capture drift from shutdown behavior. No validator checks were
relaxed, and neither failed run is counted as a passing soak.

The passing 1 MHz control started warmer than either failing 4 MHz run. These
observations do not suggest that reaching a high die temperature is necessary
for the failure. They also do not establish that a 600 MHz core would fix it;
that core speed was not tested in this follow-up.

Because final STATUS validation throws before the runner exports its normal
rate/latency metrics, those metrics are unavailable for the failed runs. The
configured 4 MHz rate and transmitted sample counts must not be presented as
a completed host-rate acceptance check.

The existing 1 MHz recommendation remains supported. A reliable 4 MHz digital
mode needs investigation of trigger delivery and bank progress, with additional
instrumentation before STOP to separate accumulated drift from teardown.

The profile advertises nominal ADC 1 MHz/GPIO 4 MHz rates, but `INPUT_GPIO`
selects only the GPIO stream. ADC startup initialization/calibration is distinct
from acquisition: the validator requires zero ADC DMA loops, captured pairs,
and emitted/transmitted frames throughout GPIO-only capture.

With unstimulated pins, these tests assess acquisition, transport, counters,
and temperature; they do not establish electrical timing fidelity or correct
capture of a known external waveform.

## Reproduction

Firmware is from `experiment/input-rate-clock`, commit
`673e855eb91d61ad0ae82ce2d0aceb277c907ff2`, build
`thingdaq-9f43cb3f4d396417`. The ratio-four 450 MHz variant passed the normal
build and memory gates. There are no firmware changes for this experiment.

Build in that experimental worktree:

```bash
SOURCE_DATE_EPOCH=1788552674 python firmware/tools/build_input_experiment.py --cpu-mhz 450
```

Run from the main worktree, choosing a new evidence directory for each job:

```bash
python firmware/tools/run_input_isolation.py \
  --worktree .maestro/playbooks/Working/input-rate-clock \
  --build-dir .maestro/playbooks/Working/input-rate-clock/firmware/build/input-experiment-ratio4-450 \
  --evidence-dir .maestro/playbooks/Working/input-isolation/NEW-UNUSED-DIRECTORY \
  --case INPUT_GPIO --profile 0 --seconds 600 --temperature
```

Temperature is queried before, every ten seconds during, and after capture.
The existing 80 °C ceiling and data-integrity checks remain enabled. The initial
submission in the preceding session was blocked by a manual service override;
after the user released it, the service reported healthy/normal with queue zero
and accepted the tests.

## Evidence

[Machine-readable results](gpio-only-4mhz-runs.json) retain each job's summary,
temperature samples, selected final counters, build identity, and SHA-256
hashes of the raw evidence. Firmware, submitted programs, complete stdout, and
service responses remain in the immutable local evidence directories:

| Capture | Service job | Directory under `.maestro/playbooks/Working/input-isolation/` |
| --- | --- | --- |
| 4 MHz / 30 s | `5d319873-9b22-45d0-8d02-8767752c60d2` | `temp-450-gpio16-4mhz-smoke-30s` |
| 4 MHz / 600 s | `da5e0813-7773-4e07-a30f-699c77c5b569` | `temp-450-gpio16-4mhz-soak-600s` |
| 1 MHz / 30 s | `e02e5f50-afaa-476b-bb13-a760cb58930d` | `temp-450-gpio16-1mhz-control-30s` |

After the control capture, the board was IDLE on the 450 MHz ratio-four research
firmware, last configured for GPIO-only 1 MHz. The service reported healthy,
coordinator mode normal, and an empty queue. No firmware or validator code was
changed during this follow-up.
