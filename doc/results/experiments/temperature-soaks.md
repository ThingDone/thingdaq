---
type: experiment
title: Temperature-instrumented input soak tests
created: 2026-09-04
tags: [thingdaq, firmware, temperature, input-isolation]
related: [input-rate-clock.md]
---

# Temperature-instrumented input soak tests

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

Follow-up to the [equal-rate input experiments](input-rate-clock.md). This
campaign holds the CPU at 450 MHz while independently varying input width
(8/16 GPIO pins) and the equal sampling rate (1 MHz/500 kHz on **each ADC channel
and the GPIO bank**). Inputs remain electrically unstimulated; no outputs are
enabled and no loopback wiring is required.

## Results

**All four ten-minute captures passed at 450 MHz**, including final STOP and
counter reconciliation. **All twenty restart/transition captures also passed.**

| GPIO width | Rate on each ADC and GPIO | Capture | Temperature before → after | Peak | Result |
| --- | --- | --- | --- | --- | --- |
| 8 pins | 1 MHz | 600 s | 36.7 → 50.8 °C | 51.4 °C | PASS |
| 8 pins | 500 kHz | 600 s | 42.8 → 51.4 °C | 51.4 °C | PASS |
| 16 pins | 1 MHz | 600 s | 44.7 → 55.1 °C | 55.1 °C | PASS |
| 16 pins | 500 kHz | 600 s | 47.1 → 55.1 °C | 55.7 °C | PASS |

All existing rate, timestamp, checksum, DMA, buffer-loss, paired-bank and final
STOP-reconciliation checks remained in force. Partial samples discarded at STOP
were distinguished from active loss. The 16-input/1 MHz run measured
999,999.29 ADC pairs/s and 999,997.60 GPIO samples/s; both GPIO banks captured
600,277,920 samples, with zero paired-generation skew events.

Starting temperatures vary because of prior test history and power cycles.
Both 16-input runs ended at 55.1 °C: reducing sampling to 500 kHz did not
demonstrate a cooling benefit in these runs. No matched 600 MHz thermal capture
or ambient-temperature measurement was performed.

The transition check used twenty ten-second START/STOP captures, five
repetitions of **8 inputs/1 MHz → 16 inputs/1 MHz → 16 inputs/500 kHz →
8 inputs/500 kHz**, without reflashing. Exactly one of width/rate changes at
each step. START run IDs advanced continuously from 1 through 20, ruling out a
hidden reboot between cells. Its maximum observed temperature was 53.9 °C.

The campaign retained eight jobs: 26 passing cell results (including two smoke
checks), two early development failures, and a service-interrupted cell without
a final grade. Unstarted follow-up smoke cells are not counted as results.
The service finished healthy with an empty queue; the board was left in IDLE
on the 450 MHz equal-rate firmware.

## Recommended next step

These results support **450 MHz core, selectable 8/16 GPIO inputs, and a 1 MHz
maximum on each ADC channel and the GPIO bank** as the proposed input-acquisition
configuration. A 500 kHz option is also supported by this matrix and reduces
data bandwidth; these measurements do not establish a thermal advantage for it.

The production rate cap and public API/profile integration have **not** been
implemented by this experiment. The old ADC 1 MHz/GPIO 4 MHz configuration at
450 MHz remains unqualified; passing the equal-rate tests does not rehabilitate
that earlier failure.

A subsequent [GPIO-only 4 MHz experiment](gpio-only-4mhz.md) disabled both ADC
streams at 450 MHz. Its 30-second and ten-minute captures both reached STOP
but failed the final bank-count comparison. This isolates a GPIO-side issue
that remains even without ADC acquisition; it does not change the passing
combined-input results above.

## Temperature feature

Firmware/API codec work is on `experiment/input-rate-clock`, commit
`673e855eb91d61ad0ae82ce2d0aceb277c907ff2`. The new optional v2 command is
`GET_TEMPERATURE` (`0x1a` request, `0x9a` response). It reports calibrated die
temperature and explicit sensor validity; it does not change sampling state,
drive pins, or alter the core's thermal protection. Frozen v1 bytes are unchanged.

The sensor read never waits for a conversion. The host retries transient
NOT_READY responses at most five times, continuing to drain incoming data.
Every attempt is saved. Persistent sensor failure or a reading at/above 80 °C
stops the campaign through its existing best-effort cleanup.

With that experimental worktree and exclusive access to the serial port:

```bash
python firmware/tools/read_temperature.py --port /dev/ttyACM0
```

The acquisition runner instead uses `--temperature` to sample before, every ten
seconds during, and after each run, through the same serial owner. Do not open a
second serial client during capture. The high-level `ThingDAQ` acquisition API
still does not support these experimental equal-rate tables; this is not a
production 450 MHz/1 MHz firmware release or an enforced rate cap.

Full wire details and implementation notes:
[temperature command](https://github.com/ThingDone/thingdaq/blob/experiment/input-rate-clock/doc/results/experiments/temperature-command.md).

## Issues found while adding the feature

- The first build exceeded the RAM1 stack-reserve gate because temperature
  conversion introduced a 64-bit division helper. Bounded 32-bit arithmetic and
  flash placement for command-only code restored the required memory headroom.
  The low-stack build was rejected before flashing.
- The first physical request was dropped by USB response admission, which still
  recognized only older IDs. The new ID is admitted and an end-to-end fragmented
  USB/runtime regression now covers both valid and unavailable sensor replies.
- An immediate NOT_READY response was initially treated as fatal. A subsequent
  short run exposed this normal conversion interval; bounded host-side retries
  now handle it without blocking firmware or hiding persistent failure.
- A two-cell, twenty-minute submission exceeded the documented 900-second
  container limit (exit `-110`). The 1 MHz cell passed; the following 500 kHz
  cell was interrupted without a final grade or STOP reconciliation. This is
  **infrastructure timeout**, not a measured firmware failure or a passing
  500 kHz soak. The runner now rejects oversized sequences before submission,
  distinguishes negative container exits, and requires all planned cell results.

All early failures and the passing smoke run are retained under
`.maestro/playbooks/Working/input-isolation/temp-*`; each directory contains the
submitted program, exact binary/manifest, service responses and graded evidence.
The [machine-readable run index](temperature-soak-runs.json) retains original
grades alongside reviewed outcomes, file hashes, temperature samples and planned
versus completed cell counts. All sixteen indexed result/summary file hashes
were rechecked against the retained artifacts when closing the campaign.

## Offline validation

The clean source passed **531 tests and 16,032 subtests**, with no skips. Main's
submission runner passed ten tests, including width/profile sequences, runtime
budget checks and partial/timeout result classification.
Equal-rate 450/600 MHz and the normal 600 MHz/4:1 firmware builds passed their
unchanged build gates. Each retains 34,528 bytes of RAM1 local/stack headroom and
4,096 bytes of RAM2 heap headroom.

Temperature is a die-sensor observation, not ambient temperature or a calibrated
external measurement. These tests cannot establish analog accuracy, GPIO pin
mapping/edge fidelity, worst-case ambient reliability, or component lifetime.
