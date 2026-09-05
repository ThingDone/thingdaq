---
type: reference
title: Hardware Safety
created: 2026-08-29
tags:
  - thingdaq
  - hardware-safety
  - teensy-4-0
  - adc
  - gpio
related:
  - '[[Quickstart]]'
  - '[[Python-API]]'
  - '[[Calibration]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[Phase-07-Dual-ADC]]'
  - '[[Phase-08-Combined-Acquisition]]'
  - '[[Phase-09-Loss-Recovery]]'
---

# ThingDAQ hardware safety for Teensy 4.0

> [!IMPORTANT]
> Release 1.1.0 uses [[Protocol-V2]]: 450 MHz core, both ADCs and GPIO at
> 1 MHz, with 8 or 16 GPIO inputs. Phase-numbered results and legacy v1
> examples below are historical; their 600 MHz / 4 MHz claims are not current
> release settings. Use live INFO metadata. `TimestampAligner` does not support
> the new unequal-duration ADC/GPIO frames; use block sample timestamps.

> [!CAUTION]
> This project targets Teensy 4.0 / i.MX RT1062 only. Treat A0/A1 and D6-D13
> as 0-3.3 V inputs. They are not 5 V tolerant. Software validation,
> calibration, clipping, or simulator success cannot protect a physical pin.

This guide defines the safe interpretation boundary for current firmware. It
is not a substitute for reviewing the Teensy 4.0 schematic/datasheet and the
external circuit before connection.

## Fixed input map

| Logical input | Teensy pin | Internal path | Current use |
| --- | --- | --- | --- |
| ADC0 | A0 / D14 | NXP ADC1 channel 7 | 12-bit raw code, nominal 1 MS/s |
| ADC1 | A1 / D15 | NXP ADC2 channel 8 | 12-bit raw code, nominal 1 MS/s, 500 ns after ADC0 |
| GPIO bit 0 | D6 | packed digital input | nominal 4 MS/s |
| GPIO bit 1 | D7 | packed digital input | nominal 4 MS/s |
| GPIO bit 2 | D8 | packed digital input | nominal 4 MS/s |
| GPIO bit 3 | D9 | packed digital input | nominal 4 MS/s |
| GPIO bit 4 | D10 | packed digital input | nominal 4 MS/s |
| GPIO bit 5 | D11 | packed digital input | nominal 4 MS/s |
| GPIO bit 6 | D12 | packed digital input | nominal 4 MS/s |
| GPIO bit 7 | D13 | packed digital input | nominal 4 MS/s |

Physical START and STOP keep D6-D13 in input mode. The fail-closed GPIO capture
diagnostic is non-driving. That behavior does not make an externally unsafe
voltage, contention path, or ground offset safe.

## Voltage and connection rules

- Keep every A0/A1 and D6-D13 voltage between board ground and 3.3 V unless an
  independently reviewed protection/front-end circuit establishes a stricter
  safe interface.
- Never connect a 5 V logic output or 5 V analog source directly to these pins.
- Establish a valid common reference/ground before presenting a signal, and
  consider ground-offset and transient current rather than only nominal voltage.
- Power down or isolate the external system while changing wiring when
  practical. Verify pin identity and voltage with appropriate instruments
  before START.
- Do not assume a series resistor alone covers overvoltage, negative voltage,
  ESD, surge, or powered/unpowered backfeed cases. Protection must be designed
  for the actual system.
- D13 may also be associated with board hardware in common Teensy workflows;
  review the board schematic and attached circuitry rather than assuming it is
  an unencumbered header node.

The firmware's nominal ADC range metadata is 0-3.3 V and codes 0-4095 for the
accepted 12-bit build. It is metadata, not a precision reference guarantee or
permission to approach absolute maximum ratings.

## ADC source impedance and front end

At the shortest high-speed sample setting, each ADC presents a switched
sample-and-hold load. A source that is acceptable for slow static measurement
may not settle adequately at 1 MS/s. The current project has not qualified a
maximum source impedance or a customer-ready analog front end.

Use an external front end appropriate to the signal and measurement claim. It
may need:

- low source impedance or a stable buffer that can drive the ADC input load;
- current limiting and over/undervoltage protection;
- level shifting or attenuation that cannot exceed 0-3.3 V under faults;
- anti-alias filtering appropriate to the actual converter/front-end bandwidth;
- a defined return path, grounding, shielding, and noise plan; and
- separate characterization for offset, gain, linearity, noise, settling,
  channel mismatch, bandwidth, and temperature.

Driving both A0 and A1 adds two converter input loads. Do not simply bridge an
unknown high-impedance source to both pins and infer that the waveform is
unchanged. Buffering and per-channel isolation may be required.

## ADC phase and bandwidth semantics

The digital trigger plan schedules ADC0 first and ADC1 nominally four 8 MHz
ticks later:

```text
time:   0.0 us   0.5 us   1.0 us   1.5 us
        ADC0     ADC1     ADC0     ADC1
```

Each converter remains a 1 MS/s channel. `interleaved()` exposes a nominal
2 MS/s grid only when the user explicitly requests it. It does not:

- increase either converter's analog bandwidth;
- remove input/front-end bandwidth or settling limits;
- prove that A0 and A1 carry the same signal;
- measure the true analog aperture time of either converter; or
- correct offset, gain, frequency response, or timing mismatch.

The recorded completion diagnostic checks digital conversion-completion status
against the programmed schedule. It is not analog aperture evidence. A
meaningful combined waveform requires the external circuit to drive the same
signal to both inputs under a characterized front end and to account for
converter mismatch.

## Raw and calibrated values

`ADCBlock.adc0` and `.adc1` are the received raw codes and remain available.
Host calibration is opt-in, visibly marked, keyed to the exact hardware serial
and optional analog-front-end profile, and retains provenance. It estimates
voltage at the Teensy input pin using affine coefficients. It does not:

- widen the safe input range or protect hardware;
- turn an overstressed/clipped input into valid data;
- establish source settling, linearity, noise, or bandwidth;
- apply the recorded residual timing-skew field; or
- replace an electrical or metrology review.

See [[Calibration]] before creating or applying a record.

## GPIO semantics

Each GPIO byte is a nominal simultaneous snapshot of D6-D13, with D6 in bit 0
and D13 in bit 7. Sample `n` is timestamped at `first_sample_ticks + 2n` in the
8 MHz START-relative domain. The timestamp describes the internal acquisition
schedule. Current evidence does not quantify external pad threshold,
propagation delay, setup/hold margin, edge rate, ringing, or cable behavior.

Use 3.3 V-compatible logic only. Review output drive strength of the external
source, possible contention with other devices, pulls, power sequencing, and
signal integrity at the intended edge rate. The DAQ is an input in the current
physical capture path; it is not a level translator or protection device.

## Tested versus untested claims

Accepted physical tests on hardware serial 20512460 demonstrated:

- exact fixed INFO identity/capability metadata and Teensy 4.0 resource map;
- bounded CONFIGURE/START/STATUS/STOP and repeated lifecycle recovery;
- 12-bit pair layout and code-range validation at nominal 1 MS/s/converter;
- packed D6-D13 framing at nominal 4 MS/s;
- a common START-relative ADC/GPIO epoch and exact frame coverage;
- checksums, sequence/timestamp continuity, host parsing, and loss counters;
- a 60-second combined run with zero complete-frame/payload loss;
- exact loss accounting and valid resumption after deliberate host stalls; and
- CDC close/reopen, malformed-control recovery, and final IDLE cleanup.

The accepted ADC inputs were unstimulated and the GPIO fixture supplied no
declared external transition stimulus. The evidence therefore does **not**
establish:

- analog DC accuracy, calibration accuracy, ENOB, noise, distortion, or
  linearity;
- analog bandwidth, anti-alias performance, source-impedance tolerance, or a
  customer-ready front end;
- true ADC aperture time or cross-channel analog phase accuracy;
- externally stimulated GPIO mapping/threshold/edge timing; or
- safe operation with a particular third-party circuit, cable, fixture, or
  Windows host.

Exact results and limitations are in [[Phase-07-Dual-ADC]],
[[Phase-08-Combined-Acquisition]], and [[Phase-09-Loss-Recovery]]. Do not turn a
digital transport pass into an unstated analog or electrical claim.

## Pre-START checklist

- [ ] Confirm the board is Teensy 4.0 and the selected INFO hardware serial is
  the intended physical unit.
- [ ] Confirm A0/A1 and D6-D13 wiring against the fixed map above.
- [ ] Measure or otherwise establish that every input remains within 0-3.3 V,
  including startup, shutdown, transients, and fault cases; no 5 V inputs.
- [ ] Confirm a valid common ground/reference and no unintended contention or
  backfeed path.
- [ ] Review source impedance, buffering, protection, and filtering for the
  intended sample rate and measurement claim.
- [ ] Use raw data first; apply only an exact serial/profile calibration with
  recorded provenance.
- [ ] Run bounded capture with visible STATUS and strict loss checking before a
  longer unattended acquisition.
- [ ] STOP and reconcile firmware and host counters at the end.
