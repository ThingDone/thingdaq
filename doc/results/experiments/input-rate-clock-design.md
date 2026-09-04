---
type: experiment
title: Equal-rate input and 450 MHz CPU research builds
created: 2026-09-04
tags: [thingdaq, firmware, input-isolation]
related: []
---

# Equal-rate input and 450 MHz CPU research builds

This branch extends `experiment/aux-input-bank` at `086d44d`. It is an isolated
research vehicle, not a new public v2 contract or a production firmware limit.
The normal builder still selects the existing 600 MHz, 4:1 rate contract.

## Controlled selections

```bash
SOURCE_DATE_EPOCH=1788552674 python firmware/tools/build_input_experiment.py \
  --cpu-mhz 600 --equal-rates
SOURCE_DATE_EPOCH=1788552674 python firmware/tools/build_input_experiment.py \
  --cpu-mhz 450 --equal-rates
SOURCE_DATE_EPOCH=1788552674 python firmware/tools/build_input_experiment.py \
  --cpu-mhz 450
```

The last command retains the original 4:1 profiles as a clock-only control.
The helper reuses the pinned core/compiler, target-property checks, linker and
memory gates in `build_firmware.py`. It does not relax a capacity gate. Build
identities include the CPU and rate-ratio selection; each output has a separate
directory, HEX hash, complete compile command and `input_experiment` manifest.
Use main's `run_input_isolation.py --build-dir ...`; its validator settings are
selected from that manifest, not inferred from a filename.

In equal-rate builds, experiment-local profiles 0/1 select 1 MHz/500 kHz on
**each ADC channel and all sixteen GPIO inputs**. Profiles 2/3 select 250/125
kHz. Both ADC channels retain their existing half-period phase separation;
equal sampling frequency does not mean simultaneous ADC apertures.

The existing packet shapes are unchanged: 506 ADC pairs per 2072-byte ADC
packet and 2024 sixteen-bit samples per 4096-byte GPIO packet. At equal rates,
four ADC packets cover the same time as one GPIO packet. Scheduling and host
continuity checks explicitly use that ratio. The packet skew field is expressed
in GPIO-packet time units for these research builds. Existing retention metadata
is a conservative inherited bound, not a newly qualified unequal-packet capacity
guarantee. No overflow, gap, bank-skew, checksum or shutdown failures are waived.

**Do not use an ordinary protocol-v2 client with these equal-rate binaries.**
They advertise a different table using experiment-local profile IDs; an ordinary
client should reject it. Before release, introduce an explicit public contract
for the chosen modes and corresponding API support. Rate/layout contract tables
have not been rewritten to disguise the experimental rate change. The subsequent
[temperature command](temperature-command.md) adds v2-only IDs; frozen v1 remains
unchanged.

## Clock isolation

The reviewed 450 MHz approach follows `experiment/clock-450mhz`: select the
Teensy 450 MHz CPU menu while retaining a 150 MHz IPG bus, 37.5 MHz ADC clock,
24 MHz PIT and 8 MHz timestamp domain. The installed 1.62 core's `clockspeed.c`
selects IPG divisor three at 450 MHz (four at 600 MHz).

DWT frequency, deadlines, phase expectations and utilization denominators follow
the selected CPU clock. Hardware adapters check actual CPU/bus frequencies, and
the capture validator checks the reported DWT/IPG/ADC/PIT clocks. The rational
event/cycle arithmetic from the earlier clock experiment is reused: 450 MHz /
4 MHz is 112.5 cycles, so per-event integer truncation would be incorrect.

All physical captures are electrically unstimulated, input-only, raw/uncompressed
and Adler-32 checked. No loopback declaration or wiring is needed. They test
capture/transport continuity and shutdown, not analog accuracy, pin mapping,
external edge fidelity, temperature reduction or lifetime improvement.

The completed physical run report and immutable result index live on main under
`doc/results/experiments/input-rate-clock.md` and `input-rate-clock-runs.json`.
