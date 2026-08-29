---
type: reference
title: Calibration
created: 2026-08-29
tags:
  - teensy-daq
  - calibration
  - adc
  - python
related:
  - '[[Quickstart]]'
  - '[[API-Reference]]'
  - '[[Python-API]]'
  - '[[Hardware-Safety]]'
  - '[[Phase-07-Dual-ADC]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
---

# Host-side ADC calibration

Teensy DAQ preserves the received ADC0/A0 and ADC1/A1 codes exactly. Host
calibration is a separate, explicit view that converts each converter's raw
codes to estimated volts at its Teensy input pin. It never rewrites a frame,
replaces `ADCBlock.adc0` or `ADCBlock.adc1`, clamps an out-of-range result, or
changes firmware data and loss accounting. See [[Python-API]] for the public
model boundary and [[Hardware-Safety]] before attaching a source.

This is distinct from the firmware's bounded boot calibration. Firmware
calibration verifies that each i.MX RT1062 ADC initialized successfully; its
INFO/STATUS state and cycle count are not per-unit voltage coefficients. The
validated digital path and its deliberately limited analog claims are recorded
in [[Phase-07-Dual-ADC]] and [[ADR-004-ADC-Trigger-DMA]].

## Record identity and schema

`CalibrationRecord` is an immutable schema-v1 value. Its primary key is the
nonzero fuse-derived hardware serial plus an optional, exact, case-sensitive
`analog_front_end_profile`. A record contains:

- schema version, hardware serial, and optional front-end profile;
- ADC resolution, complete raw-code range, and ADC-pin voltage range;
- affine offset and gain for ADC0 and ADC1 independently;
- an optional measured residual timing-skew value;
- nonempty provenance, a timezone-aware creation time, and optional notes.

Applying a record checks its serial, profile, 10/12-bit resolution, complete
code range, and nominal input range before producing a value. A profiled record
requires the caller to name that profile at application time. A block delivered
by `TeensyDAQ` carries the INFO-reported hardware serial; a manually constructed
block has no trusted serial and requires an explicit one.

The JSON database repeats schema version 1 at the document and record levels.
Parsing rejects duplicate or unknown fields, non-finite numbers, invalid UTF-8,
unsupported versions, duplicate keys, symbolic-link paths, and documents over
1 MiB. `CalibrationStore`, `save_calibration()`, and `load_calibration()` have
no default location: the user must pass a path. Writes create a private
temporary sibling, flush it, and atomically replace the selected file. The
package does not create or track a personal calibration file in this
repository.

## Two-point formula

For one converter, let \(L\) and \(H\) be the arithmetic means of the supplied
stable low and high raw-code captures. Let \(V_L\) and \(V_H\) be the measured
reference voltages at that same Teensy input pin, with \(H > L\) and
\(V_H > V_L\). `estimate_offset_gain()` fits:

$$
g = \frac{V_H - V_L}{H - L}
$$

$$
o = V_L - gL
$$

The calibrated voltage for an unmodified raw code \(c\) is:

$$
V(c) = gc + o
$$

`apply_correction()` applies that formula to one code and
`apply_corrections()` returns a pure-Python tuple for an iterable. Results are
not clipped to 0-3.3 V: a value outside the nominal range remains visible as
possible saturation, extrapolation, wiring, reference, or calibration
evidence.

## Workflow

Use a high-impedance, traceable measurement at the actual A0/A1 pins and keep
each source level stable for both channel captures. Estimate each converter
independently, construct the immutable record, and save it to a user-selected
path outside the repository:

```python
from datetime import datetime, timezone
from pathlib import Path

from teensy_daq import (
    CalibrationRecord,
    TeensyDAQ,
    estimate_offset_gain,
    load_calibration,
    save_calibration,
)

serial = 20512460
profile = "buffer-rev-a"
record = CalibrationRecord(
    hardware_serial=serial,
    analog_front_end_profile=profile,
    adc_resolution_bits=12,
    adc_code_range=(0, 4095),
    adc_input_range_volts=(0.0, 3.3),
    adc0=estimate_offset_gain(adc0_low, adc0_high, low_volts, high_volts),
    adc1=estimate_offset_gain(adc1_low, adc1_high, low_volts, high_volts),
    provenance="fixture F-17; DMM asset D-42; firmware/build recorded in lab log",
    created_at=datetime.now(timezone.utc),
    notes="Both pins driven from the same buffered source",
)

path = Path.home() / ".config" / "teensy-daq" / "calibration.json"
save_calibration(path, record)  # the parent directory must already exist
selected = load_calibration(path, serial, profile)

with TeensyDAQ.open(hardware_serial=serial) as daq:
    daq.configure(adc=True, gpio=False)
    daq.start()
    block = daq.read_block()
    channels = block.calibrated_channels(
        selected,
        analog_front_end_profile=profile,
    )
    print(block.adc0[0], channels.adc0[0], channels.units)
```

`CalibratedAdcChannels` is visibly marked with `calibrated=True`, units `V`,
the source `raw_block`, `raw_adc0`, `raw_adc1`, and the exact record.
`calibrated_interleaved()` yields `CalibratedAdcSample` values containing both
`raw_code` and `voltage`. The equivalent block methods are available as
`block.calibrated_channels()` and `block.calibrated_interleaved()`.

## Provenance rules

A usable record's provenance should identify, in text or an external immutable
record referenced by text:

1. hardware serial and exact analog-front-end/wiring revision;
2. firmware build and host package/source revision;
3. raw capture identifiers and the number of samples retained at each level;
4. reference values, measurement location, instrument, and traceability state;
5. source impedance, buffering, temperature, supply/reference conditions, and
   any settling or filtering policy;
6. the estimator/method version, UTC creation time, and responsible operator or
   automated fixture.

Do not reuse a record after changing the board, ADC resolution, voltage range,
front end, attenuation/gain path, reference conditions, or measurement setup.
Create a new record and retain the old provenance instead of editing history.

## Limitations and timing skew

- Two-point mean fitting corrects only a linear gain/offset model. It does not
  characterize noise, nonlinearity, temperature drift, reference drift,
  settling, aliasing, source impedance, clipping, or analog bandwidth.
- The firmware's nominal 500 ns phase and measured conversion-completion delta
  are digital timing evidence, not analog sample-and-hold aperture evidence.
- Schema v1 can retain `residual_timing_skew_seconds` as provenance, but the
  Python API deliberately reports `timing_skew_applied=False` and leaves all
  nominal timestamps unchanged. No characterized shared sine/edge waveform is
  available in the repository to select and validate a deterministic
  fractional-delay algorithm.
- Explicit ADC0/ADC1 interleaving creates a 2 MS/s nominal time grid. It does
  not increase either input's analog bandwidth, and independent input signals
  are not one higher-rate waveform.
- A calibration is not permission to exceed the electrical limits in
  [[Hardware-Safety]]. Never use correction or extrapolation to reinterpret an
  unsafe voltage as acceptable.
