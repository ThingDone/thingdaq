---
type: experiment
title: Temperature-instrumented input soak tests
created: 2026-09-04
tags: [thingdaq, firmware, temperature, input-isolation]
related: [input-rate-clock.md]
---

# Temperature-instrumented input soak tests

Follow-up to the [equal-rate input experiments](input-rate-clock.md). This
campaign holds the CPU at 450 MHz while independently varying input width
(8/16 GPIO pins) and the equal sampling rate (1 MHz/500 kHz on **each ADC channel
and the GPIO bank**). Inputs remain electrically unstimulated; no outputs are
enabled and no loopback wiring is required.

## Current status

The temperature feature is implemented. Both clean 8-input captures passed
600 seconds, including STOP. At 1 MHz, die temperature was 36.7 °C before,
50.8 °C after and 51.4 °C maximum; at 500 kHz it was 42.8 °C before and 51.4 °C
after/maximum. Both 16-input smoke checks also passed for 15 seconds.
The 16-input long captures are in progress, not yet qualified.

| GPIO width | Rate on each ADC and GPIO | Planned continuous capture | Result |
| --- | --- | --- | --- |
| 8 pins | 1 MHz | 600 s | PASS |
| 8 pins | 500 kHz | 600 s | PASS, separate rerun after service timeout |
| 16 pins | 1 MHz | 600 s | In progress |
| 16 pins | 500 kHz | 600 s | Pending |

Repeated START/STOP, rate changes and 8↔16-input transitions without reflashing
will follow the continuous captures. All existing rate, timestamp, checksum,
DMA, buffer-loss, paired-bank and final STOP-reconciliation checks remain in
force. Partial samples discarded at STOP are distinguished from active loss.
The explicit width-transition sequence also requires START run IDs to advance
across cells, so a reboot cannot silently count as a successful transition.

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
versus completed cell counts. It is updated as this campaign progresses.

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
