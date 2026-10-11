---
type: research
title: ADC Clock Options for Reliability and Higher Rates
created: 2026-10-11
tags:
  - adc
  - clocks
  - reliability
related:
  - '[[Protocol-V2]]'
  - '[[Reliability-20261011]]'
---

# ADC clock options

The user priorities are reliability first, then higher sample rates; delivery
latency is secondary. Keep standard Adler-32 and evaluate larger ADC frames.
The proposed independent ADC oscillator exists, but its documented speed does
not support the current 12-bit, 1 MS/s-per-converter schedule.

## Independent trigger and conversion clocks

The existing PIT sample-trigger clock already comes from the 24 MHz crystal
through PERCLK. The ADC conversion clock currently comes from IPG/4. Raising
the core frequency need not change the PIT trigger rate, but with the pinned
Teensy clock configuration it also changes IPG, ADC conversion time, ADC_ETC
phase-delay cycles, and DWT-based deadlines. A core-frequency edit alone is
not a valid experiment.

NXP's [RT1060 reference manual, revision 3](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf),
section 66.5.1, lists IPG, IPG/2, and internal asynchronous ADACK as ADC clock
sources. ADICLK=2 is reserved; it does not select the external crystal.
ADICLK=3 selects ADACK. ADACKEN keeps that oscillator running between
conversions; otherwise the first/single-conversion timing includes a 1.5 us
oscillator startup term (section 66.5.4.5, table 66-4).

The [RT1060 consumer datasheet, revision 4](https://www.nxp.com/docs/en/nxp/data-sheets/IMXRT1060CEC.pdf),
table 55, specifies ADACK at 10 MHz typical with ADHSC=0 or 20 MHz typical
with ADHSC=1. These are typical values, not guaranteed bounds. Table 54
permits externally derived ADCK up to 40 MHz in high-speed 12-bit mode;
that is not the internal oscillator's frequency.

## Timing calculation

With no averaging, the reference manual's 12-bit base conversion is 25 ADCK
cycles. The shortest sample setting adds 3; single hardware-triggered
conversions add another 4 ADCK cycles plus 2 IPG cycles. For an always-running
ADACK the same single-conversion adders apply. These are design calculations,
not measurements of actual aperture timing or oscillator frequency.

| Core / ADC source | IPG | ADCK | Calculated single conversion | Margin in a 1 us period |
| --- | ---: | ---: | ---: | ---: |
| 450 MHz / IPG divided by 4 | 150 MHz | 37.5 MHz | 866.7 ns | 133.3 ns |
| 528 MHz / IPG divided by 4 | 132 MHz | 33 MHz | 984.8 ns | 15.2 ns |
| 528 MHz / ADACK, no divider | 132 MHz | 20 MHz typical | 1615.2 ns typical | negative 615.2 ns |

Even the 25-cycle base alone takes 1.25 us at typical 20 MHz. Therefore ADACK
is not a supported way to maintain 1 MS/s at 12 bits. Keeping crystal-derived
triggers cannot make a busy converter complete sooner. Crossing into an
asynchronous ADC clock also means nominal trigger timing is not proof of
identical sample-aperture phase.

The pinned Teensy 1.62.0 `boards.txt` provides 528 MHz, not 524 MHz.
`cores/teensy4/clockspeed.c` derives the above IPG values with integer dividers.
Earlier `experiment/clock-528mhz` evidence already records 12-bit full-rate
ADC_ETC errors at IPG/4 and a subsequent explicitly advertised 10-bit fallback.
That historical run is a reason to investigate, not proof that the current
firmware will behave identically.

## Decision and possible follow-up

Integrate the measured exact-Adler implementation at the existing wire ID,
and test checksummed larger frames at the existing 450 MHz clock first.
Do not silently select 10-bit conversion or program a 1 MS/s ADACK candidate
as if its conversion budget were valid. Preserve the current disabled-watchdog
policy during the comparison; it is not an established fix for the ADC fault.

If independent-clock characterization is desired, a separate 528 MHz ADACK
experiment should start at 500 kS/s, keep ADACK running, calibrate each ADC,
verify every selected clock/register value, and measure missed triggers,
completion timing and temperature. Its lower rate does not satisfy the higher
sample-rate objective. A 528 MHz / 33 MHz IPG-derived ADC experiment instead
tests a faster CPU with substantially less ADC timing margin. Neither is
currently qualified or enabled by the build tools.
