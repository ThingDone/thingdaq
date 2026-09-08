---
type: reference
title: NumPy Integration
created: 2026-08-29
tags:
  - thingdaq
  - numpy
  - python
  - adc
  - gpio
related:
  - '[[Quickstart]]'
  - '[[API-Reference]]'
  - '[[Python-API]]'
  - '[[Calibration]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Protocol-V1]]'
---

# Optional NumPy integration

> [!IMPORTANT]
> Release 1.1.0 uses [[Protocol-V2]]: 450 MHz core, both ADCs and GPIO at
> 1 MHz, with 8 or 16 GPIO inputs. Phase-numbered results and legacy v1
> examples below are historical; their 600 MHz / 4 MHz claims are not current
> release settings. Use live INFO metadata. `TimestampAligner` does not support
> the new unequal-duration ADC/GPIO frames; use block sample timestamps.

The core `thingdone_daq` package does not import or require NumPy. Its immutable
`ADCBlock`, `GPIOBlock`, lazy channel views, explicit interleaving, calibration,
and timestamp helpers remain the complete behavior used by the network-disabled
remote rig. Installing the `numpy` extra adds a vectorized representation of
the same raw blocks and metadata:

```bash
python -m pip install 'thingdone-daq[numpy]'
```

`ADCBlock.as_numpy()` and `GPIOBlock.as_numpy()` import the optional
`thingdone_daq.numpy` module only when called. Importing `thingdone_daq`, reading and
aligning blocks, validating synthetic streams, or applying the pure-Python
calibration API never probes for or imports NumPy. If an array view is requested
without the extra, the operation raises an actionable `ImportError`; the block
and its pure-Python views remain usable.

## Raw layout, ownership, and endianness

| View | Shape | dtype | allocation | meaning |
| --- | ---: | --- | --- | --- |
| `ADCArrayView.pairs` | `(1012, 2)` | explicit wire `<u2` | zero-copy, read-only | columns are ADC0/A0 then ADC1/A1 |
| `ADCArrayView.adc0` / `.adc1` | `(1012,)` | `<u2` with 4-byte stride | zero-copy, read-only | one converter without deinterleaving copy |
| `GPIOArrayView.packed` | `(4048,)` | `uint8` | zero-copy, read-only | one simultaneous D6-D13 snapshot per byte |

Both raw views use `numpy.frombuffer()` over the immutable bytes already owned
by the validated block. NumPy's base chain retains a `memoryview` of that bytes
object, so an array remains valid if the `ADCBlock` or `GPIOBlock` name goes out
of scope. `raw_block` and `payload_owner` make the ownership relationship
visible. The arrays cannot be made writable; callers that need mutable storage
must explicitly copy it.

ADC halfwords are always interpreted with the wire's little-endian `<u2` dtype,
independent of host byte order. NumPy may display the byte-order field as native
on a little-endian host, but `dtype.str` remains `<u2` and values have the same
meaning on a big-endian host. GPIO samples are single bytes, so byte order does
not apply to them; D6 is bit 0 and D13 is bit 7 as defined by [[Protocol-V1]].

The fixed payloads start at buffer offset zero and normally satisfy `uint16`
alignment. The array exposes NumPy's `flags.aligned` rather than making a hidden
copy. NumPy still interprets a valid unaligned buffer correctly on platforms
that report it, although a caller with an aligned-SIMD requirement can request
an explicit aligned copy with `numpy.require()`.

## Explicit allocation boundary

Creating either block view allocates only the small Python wrapper and NumPy
array headers. Further storage appears only for an operation that mathematically
requires output:

| Explicit operation | Output allocation |
| --- | --- |
| `adc_view.interleaved()` | raw codes stay zero-copy; one `uint64` timestamp vector is generated |
| `adc_view.timestamp_pairs()` | one `(1012, 2)` `uint64` tick matrix |
| `adc_view.calibrate(...)` | one `(1012, 2)` native `float64` voltage matrix; raw codes stay zero-copy |
| `calibrated.interleaved()` | voltage flattening is a view; one `uint64` timestamp vector is generated |
| `gpio_view.timestamps()` | one `(4048,)` `uint64` tick vector |
| `gpio_view.channels(pins)` | one Boolean column per requested pin only |

`GPIOArrayView` contains only the packed `uint8` vector. It has no eager Boolean
fields and no default “all channels” operation. `channel(pin)` or
`channels(pins)` requires an explicit selection; requesting `range(6, 14)` is
the deliberate opt-in that permits an eightfold expansion. This keeps the
normal 4 million packed samples per second as four million bytes rather than
silently producing 32 million Boolean values per second.

## Vectorized workflow

```python
from thingdone_daq.numpy import adc_view, gpio_view

adc_arrays = adc_view(adc_block)  # same as adc_block.as_numpy()
raw_pairs = adc_arrays.pairs  # read-only, zero-copy, shape (1012, 2)
raw_adc0 = adc_arrays.adc0  # read-only strided view
samples = adc_arrays.interleaved()  # ADC0, ADC1, ADC0, ADC1, ...

assert samples.converter_order[0].name == "ADC0"
assert samples.raw_codes[0] == raw_pairs[0, 0]
assert samples.timestamp_ticks[1] == adc_block.pair_ticks(0)[1]

volts = adc_arrays.calibrate(
    calibration_record,
    analog_front_end_profile="buffer-rev-a",
)
assert volts.calibrated and volts.units == "V"
assert volts.raw_pairs is raw_pairs
calibrated_samples = volts.interleaved()

gpio_arrays = gpio_view(gpio_block)  # same as gpio_block.as_numpy()
packed = gpio_arrays.packed  # still one byte per sample instant
d6_and_d13 = gpio_arrays.channels((6, 13))
assert d6_and_d13.values.shape == (gpio_block.item_count, 2)
```

`ADCInterleavedArray` retains `raw_codes`, `values`, `timestamp_ticks`,
`converter_order=(ADC0, ADC1)`, `pins=("A0", "A1")`, and the source block.
Even positions are ADC0 and odd positions are ADC1; `converter_indices()` and
`pair_indices()` produce explicit vector columns when a table-oriented caller
needs them. A calibrated result retains the exact `CalibrationRecord`, reports
`calibrated=True`, `units="V"`, and `timing_skew_applied=False`, matching
[[Calibration]].

Timestamp generation uses `uint64` modular arithmetic, so wrap behavior is
identical to `ADCBlock.pair_ticks()` and `GPIOBlock.sample_ticks()`. Integer
ticks remain the authoritative 8 MHz START-relative domain. Converting them to
`float64` seconds is explicit and can lose sub-tick precision for very large
run-relative values.

## Pure-Python equivalence

| NumPy operation | Baseline operation without NumPy | preserved metadata |
| --- | --- | --- |
| `adc_view.pairs` | `block.pairs()` / `block.pair(i)` | pair order, resolution, code range, raw codes |
| `adc_view.adc0`, `.adc1` | `block.adc0`, `block.adc1` | converter and A0/A1 identity |
| `adc_view.interleaved()` | `block.interleaved()` | pair index, converter, raw code, nominal tick |
| `adc_view.calibrate(...)` | `block.calibrated_channels(...)` | raw block/codes, record, marker, units |
| `calibrated.interleaved()` | `block.calibrated_interleaved(...)` | raw code, voltage, converter, nominal tick |
| `gpio_view.packed` | `block.payload_view` / `block.sample(i)` | packed pin order and simultaneous snapshot |
| `gpio_view.channels(pins)` | `block.channel(pin)` for each selected pin | requested pin and bit identity |
| vectorized timestamps | `pair_ticks(i)` / `sample_ticks(i)` | run ID, sequence, t0, period, phase, wrap |

The vectorized calibration path calls the same compatibility boundary as the
pure-Python API before allocating output. Device serial, front-end profile,
resolution, complete code range, and nominal voltage range therefore fail in
the same way. It applies the same independent affine coefficients and does not
clamp results, mutate raw bytes, or apply the schema-v1 residual timing skew.

Explicit ADC interleaving remains a representation choice. It produces a
nominal 2 MS/s two-converter time grid but does not increase the analog
bandwidth of A0 or A1 and does not turn independent inputs into one waveform.
The acquisition and timestamp claims remain those in [[Acquisition-Pipeline]].
