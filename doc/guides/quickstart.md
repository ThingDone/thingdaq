---
type: reference
title: Quickstart
created: 2026-08-29
tags:
  - thingdaq
  - quickstart
  - python
  - simulator
  - hardware
related:
  - '[[Python-API]]'
  - '[[API-Reference]]'
  - '[[Hardware-Safety]]'
  - '[[Calibration]]'
  - '[[NumPy-Integration]]'
  - '[[Protocol-V1]]'
---

# ThingDAQ quickstart

Start with the simulator. It uses the real protocol encoder, parser,
background reader, immutable block models, checksums, timestamps, loss policy,
and public lifecycle without opening a serial port. Move to `--real` only after
reading [[Hardware-Safety]] and checking the attached signals.

ThingDAQ is the software/product name. Teensy 4.0 references below identify
the supported hardware platform, not a ThingDAQ model or affiliation.

## Install for repository development

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable './daq_api[dev]'
```

NumPy is optional. Add the `numpy` extra only when array views are wanted:

```bash
.venv/bin/python -m pip install --editable './daq_api[dev,numpy]'
```

The supported host range is CPython 3.10 through 3.14. PySerial is the only
base runtime dependency. See [[NumPy-Integration]] for allocation, ownership,
and pure-Python parity.

## Verify the simulator first

Run the complete offline flight and a short strict-loss CLI capture:

```bash
.venv/bin/thingdaq-demo --frames 2
.venv/bin/thingdaq capture --simulate --duration 1 --strict-loss \
  --gpio-channel D6 --gpio-channel D13
```

`--simulate` never enumerates or opens USB hardware. INFO advertises synthetic
ADC/GPIO profiles, and CONFIGURE, START, STATUS, stream decoding, STOP, and
shutdown travel through ordinary protocol-v1 frames.

## Executable examples

Every script below runs with no arguments against the simulator. The `--real`
path is opt-in and clearly represents a physical-device operation.

| Example | Simulator command | Physical requirement with `--real` |
| --- | --- | --- |
| Discovery and stable serial selection | `.venv/bin/python daq_api/examples/discovery_and_selection.py` | Attached Teensy 4.0; pass `--hardware-serial N` when more than one is present |
| Raw ADC0/A0 and ADC1/A1 | `.venv/bin/python daq_api/examples/raw_adc_channels.py` | Safe signals on A0/A1 |
| Explicit ADC interleaving | `.venv/bin/python daq_api/examples/interleaved_adc.py` | Safe signals on A0/A1; one shared signal is required for meaningful waveform interleaving |
| Optional host calibration | `.venv/bin/python daq_api/examples/calibrated_adc.py` | Safe A0/A1 signals plus `--calibration PATH` and the exact optional profile |
| Packed GPIO and selected channels | `.venv/bin/python daq_api/examples/gpio_channels.py` | Safe 3.3 V logic on D6-D13 |
| Combined timestamp alignment | `.venv/bin/python daq_api/examples/combined_alignment.py` | Safe A0/A1 and D6-D13 inputs |
| Live STATUS and loss handling | `.venv/bin/python daq_api/examples/status_and_loss.py` | Safe inputs; performs a short physical combined capture |
| Standalone simulator lifecycle | `.venv/bin/python daq_api/examples/simulator.py` | None; this example intentionally has no `--real` path |
| Auxiliary-input workload matrix | `.venv/bin/python daq_api/examples/aux_input_matrix.py` | None; this example intentionally has no `--real` path |
| Explicit clean shutdown | `.venv/bin/python daq_api/examples/clean_shutdown.py` | Safe A0/A1 input; demonstrates STOP in `finally` |

For example:

```bash
.venv/bin/python daq_api/examples/raw_adc_channels.py \
  --real --hardware-serial 20512460
```

The calibration example's simulator coefficients are illustrative and exist
only in memory. They are not a personal calibration, do not touch a default
path, and must not be reused for a physical device. See [[Calibration]].

## Validate the auxiliary-input workload matrix

The experimental auxiliary-input example runs the 8-bit and 16-bit layouts at
all four exact rate profiles, plus the one-bank and 16-input GPIO-only 4 MHz
cases. Its no-argument path validates all four independent primary/auxiliary
GPIO formulas, every ADC pair and half-period timestamp, frame chronology,
STATUS byte conservation, STOP, and closed cleanup:

```bash
.venv/bin/python daq_api/examples/aux_input_matrix.py
```

It prints exact analytic payload/framed rates, logical packed-item and channel
sample rates, frame coverage, projected load increases, and decoded examples.
Generate a temporary shared-schema JSON/structured-Markdown pair only when
needed:

```bash
.venv/bin/python daq_api/examples/aux_input_matrix.py \
  --output .maestro/aux-input-demo
```

The reported 12 MB/s full-combined payload is explicitly a protocol-load
hypothesis. Simulator execution does not establish host throughput, physical
USB acceptance, target timing, pad behavior, or electrical performance.

## Minimal Python lifecycle

```python
from thingdaq import ADCBlock, GPIOBlock, Source, ThingDAQ

with ThingDAQ.simulated(strict=True) as daq:
    info = daq.info()
    applied = daq.configure(
        adc=True,
        gpio=True,
        source=Source.SYNTHETIC,
        adc_pair_rate_hz=1_000_000,
        gpio_sample_rate_hz=4_000_000,
        adc_resolution_bits=12,
    )
    print(applied)

    run_id = daq.start()
    for item in daq.blocks(2):  # counts data blocks, not loss reports
        if isinstance(item, ADCBlock):
            print(run_id, item.adc0[0], item.adc1[0])
        elif isinstance(item, GPIOBlock):
            print(item.sample(0), item.channel(6)[0])

    daq.validate_stream_health()
    daq.stop()
```

The context manager attempts bounded STOP if the body exits while CONFIGURED
or RUNNING, then closes the background reader and transport deterministically.
Calling `stop()` explicitly still makes the lifecycle visible at the normal
success boundary.

## Capability-driven configuration

INFO is authoritative. Before writing CONFIGURE, the client rejects:

- stream bits absent from `supported_stream_mask`;
- a source absent from `supported_source_mask`;
- a source/stream pair absent from `supported_configuration_mask`;
- a checksum absent from the device mask or host implementation set;
- an exact ADC/GPIO rate requirement that differs from INFO; and
- an exact ADC resolution requirement that differs from INFO.

Protocol v1 carries stream, source, checksum, and 4,096-byte frame size in the
eight-byte CONFIGURE body. Rates and resolution are fixed INFO capabilities,
so `adc_pair_rate_hz`, `gpio_sample_rate_hz`, and `adc_resolution_bits` are
host-side preconditions and are never smuggled into reserved wire bytes.
CONFIGURE returns the device's exact applied body. The facade rejects a changed
CONFIGURE echo, and START must echo that same applied configuration again.

The CLI exposes the same preflight and then prints the applied body plus active
fixed-rate metadata:

```bash
.venv/bin/thingdaq configure --simulate --streams both \
  --source synthetic --checksum adler32 \
  --adc-pair-rate-hz 1000000 --gpio-sample-rate-hz 4000000 \
  --adc-resolution-bits 12
```

## Discover and select physical hardware

Metadata-only enumeration lists plausible PJRC USB Serial endpoints without
opening them:

```bash
.venv/bin/thingdaq list
```

`discover()` then opens only matching candidates for a short read-only INFO
probe. A `DiscoveredDevice.port` is a current endpoint, not identity. Select by
the stable nonzero fuse-derived INFO `hardware_serial`:

```python
from thingdaq import ThingDAQ, discover, select_device

devices = discover(timeout=0.2)
selected = select_device(devices, hardware_serial=20512460)
with ThingDAQ.open(selected) as daq:
    print(daq.device_info.build_id)
```

`ThingDAQ.open(hardware_serial=20512460)` performs a fresh scan, chooses the
current endpoint, reopens it, and requires stable repeated INFO identity before
any mutating command. Multiple devices without an explicit serial fail with an
actionable selection error. See [[Python-API]] for adopt-versus-stop behavior
when a prior process left the device CONFIGURED or RUNNING.

## Interpret ADC data

Each `ADCBlock` contains 1,012 immutable little-endian pairs. `adc0` is A0/D14
through logical ADC0; `adc1` is A1/D15 through logical ADC1. Each converter is
nominally 1 MS/s. In the 8 MHz tick domain:

- pair `n` ADC0 is at `first_sample_ticks + 8n`;
- pair `n` ADC1 is at `first_sample_ticks + 8n + 4`;
- four ticks are 500 ns.

`block.interleaved()` explicitly yields ADC0 then ADC1 with converter, pin,
raw code, pair index, and nominal timestamp attached. The resulting 2 MS/s
nominal grid does not increase analog bandwidth, and combining a waveform is
meaningful only when the external circuit drives both inputs appropriately.

Raw values never become calibrated implicitly. `calibrated_channels()` and
`calibrated_interleaved()` return visibly calibrated voltage views while the
source block and raw codes remain accessible. Calibration estimates pin
voltage; it is not electrical protection or proof of analog bandwidth.

## Interpret GPIO data

Each `GPIOBlock` contains 4,048 packed bytes at 4 MS/s. One byte is one nominal
simultaneous input snapshot:

| Bit | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pin | D6 | D7 | D8 | D9 | D10 | D11 | D12 | D13 |

`block.samples` keeps the one-byte form. `block.channel(6)` returns a lazy
Boolean view of only D6; no eightfold expansion occurs unless requested.
Sample `n` is at `first_sample_ticks + 2n`.

## Align combined blocks

ADC and GPIO frames each cover exactly 8,096 ticks. `TimestampAligner` pairs
equal `(run_id, first_sample_ticks)` intervals without copying either payload.
Missing sides and stream gaps remain explicit `AlignmentLoss`/`StreamGap`
objects. The common epoch is firmware START-relative nominal time; it does not
measure external GPIO-pad propagation or analog aperture latency.

## Loss policy and STATUS

With `strict=False`, live iteration emits `StreamGap`, `HostQueueLoss`, and
`StreamAnomaly` objects alongside data. Firmware cumulative loss/error counters
and host reader/parser/queue counters remain independent evidence. With
`strict=True`, the same unexpected conditions raise typed exceptions.

Call `status()` during a run for live firmware counters, then
`loss_counters()` to combine—not conflate—the firmware and host domains.
`validate_stream_health()` rejects gaps, anomalies, host drops, parser damage,
firmware drops/errors, or inconsistent telemetry. Do not infer zero loss from
an iterator that simply did not show a gap; reconcile the counters too.

## Physical scope and claims

This project targets Teensy 4.0 / i.MX RT1062 only. A0/A1 and D6-D13 are
0-3.3 V inputs and are not 5 V tolerant. Source impedance, buffering,
protection, and anti-alias filtering belong to the external front end; consult
[[Hardware-Safety]] before connecting anything.

The accepted campaigns demonstrated full-rate digital acquisition, framing,
checksums, timestamps, command responsiveness, exact loss accounting,
recovery, and clean STOP on one recorded Teensy 4.0. Inputs were not externally
stimulated for analog-quality or GPIO-edge grading. Analog accuracy, analog
bandwidth, true aperture timing, customer front ends, and external digital pad
timing remain untested claims. Evidence is linked from [[Hardware-Safety]].
