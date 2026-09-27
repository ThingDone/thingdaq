---
type: result
title: Current Watchdog Baseline and Separate SDK Reproduction
created: 2026-09-27
tags:
  - thingdaq
  - watchdog
  - validation
---

# Watchdog initialization and current baseline

Current `main` at `e2cfbee` reproduced the watchdog preflight failure before
acquisition, job `f73d888a-1812-4bf8-800f-97a363d5dbee`. The original firmware
build `thingdaq-6f2c6b332efc9280` reported watchdog disabled, timeout zero and
reset cause `0x1`. No acquisition cell ran.

A dedicated non-driving sketch using the actual watchdog adapter read CS
`0x2520` before initialization, `0x31a3` immediately after the failed call, and
`0x35a3` later. TOVAL was already 512. The missing RCS acknowledgment bit
arrived after the original 100,000-poll deadline. This was a false negative
that prevented refreshes of an already enabled watchdog. Job
`23faba53-0f63-407a-a6e6-553172d33da3` retains the register evidence.

The bound is now 2,000,000 polls, still independent of DWT progress. The host
fake models delayed RCS and tests an acknowledgment beyond the old bound;
unlock/configuration failures, command width, interrupt masking and readback
checks remain enforced. Neither watchdog timeout nor acceptance was weakened.

The fixed adapter passed the physical watchdog test on Teensy serial
`20428100`, 450 MHz, job `f8d87f59-512d-4f51-a5df-7f9a16ec0597`:

- Initialization acknowledged in 12,335,804 DWT cycles (27.413 ms).
- Healthy refreshes continued for more than the four-second timeout.
- A deliberately stalled main loop disconnected USB after 4.135 seconds.
- USB reconnected by 4.660 seconds, watchdog enabled, reset cause `0x80`.

This is a dedicated fault-injection sketch, not an acquisition soak. The
production build passes the pinned target build and memory gates. Subsequent
production acquisition and SDK CPU comparisons are recorded separately below
when complete.

[Machine-readable evidence](watchdog-sdk-20260927-evidence.json) preserves the
observations. Complete programs, HEX files, manifests, responses and logs are
under ignored `doc/results/raw/watchdog-sdk-20260927/` and `firmware/build/`.
The probe's printed `serial` field is the raw OCOTP word, not the public USB
serial; the fixed probe's host independently checked USB serial `20428100`.

The rig had upload timeouts before the original probe and two production
attempts. These were terminal programming failures, not acquisition results.
No simultaneous board jobs or automatic retries of ambiguous submissions were
used. The later successful small fixed probe restored a refreshing image.

## Local validation boundaries

The watchdog regression and focused SDK/runner tests pass. A broad local run
passed 610 tests and 16,360 subtests but was not wholly green: existing SDK
throughput/paced-simulator checks failed on local CPython 3.12.3, the unrelated
untracked `doc/results/firmware-analysis-2026-09-12.md` lacks required YAML, and
an in-progress report link was not yet present. The link is now resolved.
No performance threshold was lowered and no unrelated file was changed.

## Hardware reference

The [NXP RT1060 reference manual, rev. 3](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf),
sections 58.3.5 and 58.5.1.2, describes clock-transition delay and the RCS
acknowledgment. The physical observations above establish this target's
initialization timing; the previous immediate-acknowledgment fake did not.
