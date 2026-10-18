---
type: result
title: Bound Temperature Readiness Retries by Elapsed Time
created: 2026-10-18
tags: [firmware, reliability, temperature]
related: []
---

# Temperature readiness during sustained capture

The USB-fixed endurance campaign passed eight 600-second captures, with a
69.211 °C maximum sampled die temperature. Run nine failed at approximately
260 seconds because GET_TEMPERATURE returned NOT_READY five consecutive times.
The responses span 86.058 ms; the preceding valid reading was 68.597 °C ten
seconds earlier. Firmware reports this state when TEMPMON FINISHED is clear;
the pinned Teensy core continuously runs that monitor. This was a temperature
availability failure, not a checksum or acquisition-loss failure: zero parser
errors/discards, no rejected frames, and no reported ADC/GPIO/USB errors.
The aborted capture remains FAIL; it did not complete final conservation checks.

The host previously exhausted a five-request budget, waiting only 7 ms between
requests. `rig_aux_input_capture.py` now retries only NOT_READY for up to one
second, with a 64-attempt backstop and varied 7/13/23/37 ms spacing. Every wait
continues parsing and validating acquisition data. Each command remains bounded
by the existing exchange timeout. The varied spacing avoids repeatedly sampling
the same monitor phase; phase locking is a plausible mechanism, not proven by
these register-free logs. Persistent NOT_READY, other sensor failures, corrupt
responses and readings at or above 80 °C still abort. No firmware or thermal
alarm setting changed, and no cached temperature is substituted for a reading.

Regression tests cover recovery after five NOT_READY responses, the one-second
persistent-failure bound, immediate unavailable/hot failures, and preservation
of every failed sample. Fifteen rig tests and 31 subtests pass.

A 60-second physical capture with the corrected host and unchanged image
`thingdaq-75ac69ba3e2bb588` passed all 131 checks over 369,014,796 received bytes;
zero parser errors or discarded bytes. Peak/after STOP was 50.790 °C. This smoke
run did not encounter NOT_READY; the transient policy is exercised locally and
will be exercised further in a fresh eighteen-run campaign.

Evidence: [summaries, provenance and hashes](temperature-retry-20261018.json).
The original failed campaign remains in
[its separate report](clock600-fixed-endurance-20261018.md).
The current work order is in [the stability plan](../../research/600mhz-stability-plan.md).
