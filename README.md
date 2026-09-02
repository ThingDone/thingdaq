# ThingDAQ

ThingDAQ (Thing Done DAQ) is firmware and a typed Python API for synchronized,
loss-visible acquisition on the Teensy 4.0 platform. It captures two
phase-shifted ADC channels and eight packed digital inputs. The same public API
runs against a deterministic in-memory simulator, so discovery, configuration,
parsing, timestamps, calibration, alignment, loss handling, and cleanup can be
developed without hardware.

> [!WARNING]
> Read the [hardware-safety guide](doc/reference/hardware-safety.md) before
> connecting a signal. A0/A1 and D6-D13 are 3.3 V inputs and are not 5 V
> tolerant. Host calibration does not add electrical protection.

## Supported acquisition

| Input | Physical schedule | Python representation |
| --- | --- | --- |
| ADC0 on A0/D14 | 1 MS/s, nominal ticks `0, 8, 16, ...` | unchanged 12-bit raw codes |
| ADC1 on A1/D15 | 1 MS/s, nominally 500 ns after ADC0 | unchanged 12-bit raw codes |
| GPIO D6-D13 | 4 MS/s simultaneous packed snapshots | one byte per sample, D6 in bit 0 through D13 in bit 7 |

The timestamp domain is an unsigned, START-relative 8 MHz clock. Explicit ADC
interleaving yields the nominal order `ADC0[0], ADC1[0], ADC0[1], ADC1[1], ...`.
That 2 MS/s view does **not** increase the analog bandwidth of the converters,
pins, source, or front end.

## Start without hardware

Create an environment and install the private local package:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable './daq_api[dev,numpy]'
```

Run the complete deterministic demo or a bounded CLI capture:

```bash
.venv/bin/thingdaq-demo --frames 2
.venv/bin/thingdaq capture --simulate --duration 1 --strict-loss \
  --gpio-channel D6 --gpio-channel D13
```

Run the isolated RAW-versus-adaptive-RLE simulator demonstration. It exercises
constant, long-hold, sparse-transition, slowly changing, alternating, and
deterministic high-entropy ADC/GPIO workloads, requires byte-identical decoded
samples, and prints exact payload/wire ratios and fallback counts:

```bash
.venv/bin/python daq_api/examples/rle_compression.py
```

Add `--output .maestro/rle-demo` to write temporary JSON and structured
Markdown through the shared experiment reporter. Those artifacts are labeled
`simulated` and make no firmware, USB, electrical, or physical-performance
claim.

Run the deterministic host corpus benchmark against the production v2 codec:

```bash
.venv/bin/python -m thingdaq.rle_benchmark --pretty
```

It covers five GPIO and four ADC workloads, compares exact RAW and selected
`RLE_AUTO` payload/wire bytes, measures all four encode/decode paths and their
bounded peak allocations, and exits nonzero unless round trips, adaptive
no-expansion, incompressible fallback, long-hold savings, and 1.25x per-stream
decode headroom all pass. ADC ratios are reported without a savings threshold.

Run the autonomous experiment baseline from a clean checkout. This exercises
the maximum-rate simulator profile, compiles the exact pinned 600 MHz firmware
without uploading it, and writes validated JSON and structured Markdown:

```bash
.venv/bin/python firmware/tools/baseline_prototype.py \
  --output-dir doc/results/experiments
```

The baseline's simulator command-latency fields use a deterministic logical
clock so normalized reports are reproducible. They are simulator bookkeeping,
not host, live-USB, or target timing evidence.

All examples default to the simulator. A script touches hardware only when
`--real` is present:

```bash
.venv/bin/python daq_api/examples/raw_adc_channels.py
.venv/bin/python daq_api/examples/combined_alignment.py
.venv/bin/python daq_api/examples/status_and_loss.py
```

See the [quickstart](doc/guides/quickstart.md) for the complete example roster,
physical discovery by hardware serial, and lifecycle guidance.

## Minimal API

```python
from thingdaq import ADCBlock, GPIOBlock, Source, ThingDAQ

with ThingDAQ.simulated(strict=True) as daq:
    applied = daq.configure(
        adc=True,
        gpio=True,
        source=Source.SYNTHETIC,
        adc_pair_rate_hz=1_000_000,
        gpio_sample_rate_hz=4_000_000,
        adc_resolution_bits=12,
    )
    run_id = daq.start()

    for item in daq.blocks(2):
        if isinstance(item, ADCBlock):
            print(run_id, item.adc0[0], item.adc1[0])
        elif isinstance(item, GPIOBlock):
            print(item.sample(0), item.channel(6)[0])

    daq.validate_stream_health()
    daq.stop()
```

`configure()` checks the exact stream/source profile, checksum, and optional
rate/resolution requirements against synchronized INFO capabilities before it
sends CONFIGURE. The returned `DAQConfiguration` is the device's exact applied
echo; a changed CONFIGURE or START echo is rejected.

## Hardware use

Metadata-only enumeration never opens candidate ports:

```bash
.venv/bin/thingdaq list
.venv/bin/thingdaq info --hardware-serial 20512460
.venv/bin/thingdaq monitor --hardware-serial 20512460 \
  --streams both --source hardware --duration 10 --strict-loss
```

Use the stable fuse-derived INFO serial instead of assuming a COM or `/dev`
path remains attached to the same unit. The client re-probes identity when it
opens the selected endpoint, and context-manager exit attempts bounded STOP
before deterministic reader/transport shutdown.

## Validation scope

The recorded pre-rename Teensy 4.0 campaigns include a 60-second combined
physical run at the nominal ADC/GPIO rates with zero complete-frame or payload
loss, deliberate host-stall loss/recovery checks, malformed-control recovery,
repeated lifecycle cycles, and CDC close/reopen recovery. Exact historical
evidence is in
[Phase 08](doc/results/phase-08-combined-acquisition.md) and
[Phase 09](doc/results/phase-09-loss-recovery.md). The reproducible package
matrix and final byte-matched real-device workflow are recorded in the
[Phase 10 local gate](doc/results/phase-10-package-local-gate.md) and
[Phase 10 physical workflow](doc/results/phase-10-package-workflows.md).

The historical autonomous release-candidate gate added two 10-minute synthetic
runs, three 10-minute physical-combined runs, and one 10-minute alternating
control-stress run on one immutable pre-rename artifact. The six-job decision,
complete exclusion lineage, conservation equations, fixture limits, and
post-campaign reproducibility gate are in the
[Phase 11 soak evidence](doc/results/phase-11-soak-evidence.md) and the
[cross-phase evidence index](doc/results/evidence-index.md). The prepared
Phase 12 Windows handoff for that artifact is now historical and superseded.

ThingDAQ firmware 1.0.0 has a fresh byte-identical two-build freeze, current
generated validators, and passing local software/build gates. Because the USB
identity, firmware build ID, host namespace, and packaging identity changed,
the earlier physical results are engineering history rather than release
acceptance for the renamed binary. A fresh physical campaign remains pending.
The identity-pinned standalone and installed `thingdaq-soak` entry paths are
documented in the [soak harness guide](doc/guides/soak-harness.md). Both embed
the deterministic `firmware/soak/validation-manifest.json` contract; a
different INFO identity is rejected unless the explicit diagnostic override is
used, and override reports are always non-release.
The superseded artifacts, exact hashes, local packaging results, diagnostic
fixture smoke, and report interpretation for the earlier candidate remain in
the [Phase 12 Windows handoff](doc/results/phase-12-windows-handoff.md). Use
the current soak harness guide—not those historical hashes—for a new run.

Those runs used unstimulated A0/A1 and no declared external digital stimulus.
They do not establish analog accuracy, analog bandwidth, true aperture timing,
external GPIO transition timing, or compatibility with a particular customer
front end. The distinction between tested and untested claims is maintained in
the [hardware-safety guide](doc/reference/hardware-safety.md).

## Documentation map

- [Documentation index](doc/README.md)
- [Evidence index](doc/results/evidence-index.md)
- [Phase 11 autonomous soak evidence](doc/results/phase-11-soak-evidence.md)
- [Phase 12 Windows validation handoff](doc/results/phase-12-windows-handoff.md)
- [Quickstart](doc/guides/quickstart.md)
- [Autonomous soak harness](doc/guides/soak-harness.md)
- [Python API architecture](doc/architecture/python-api.md)
- [Python API reference](doc/reference/api-reference.md)
- [Hardware safety](doc/reference/hardware-safety.md)
- [Calibration](doc/architecture/calibration.md)
- [Optional NumPy integration](doc/architecture/numpy-integration.md)
- [Protocol v1](doc/protocol/protocol-v1.md)
- [System overview](doc/architecture/system-overview.md)
- [Phase 10 package workflow evidence](doc/results/phase-10-package-workflows.md)

## Repository layout and checks

- `firmware/`: Teensy 4.0 sketch, portable C++ components, build tooling, and
  host-compiled firmware tests.
- `daq_api/`: installable `thingdaq` package, CLI, simulator, examples, and
  Python tests.
- `protocol/`: canonical machine-readable contract and cross-language golden
  frames.
- `doc/`: structured architecture, guide, reference, decision, and evidence
  artifacts.

Common local gates:

```bash
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdaq
.venv/bin/python -m pytest
python3 firmware/tools/build_firmware.py
```

## Distribution and trademark boundary

The distribution remains marked `Private :: Do Not Upload` until package-index
availability and publication readiness are reviewed. Repository workflows must
not reserve, upload, or publish it.

ThingDAQ is an independent project and is not affiliated with or endorsed by
PJRC.COM, LLC or SparkFun Electronics. Teensy® is a registered trademark of
PJRC.COM, LLC. References to Teensy identify the supported hardware platform;
they are not part of the ThingDAQ product name.

## License

This project is available under the [MIT License](LICENSE).
Copyright (c) 2026 THING DONE LLC.
