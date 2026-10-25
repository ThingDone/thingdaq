# ThingDAQ

The **supported 1.2.0 release** uses [public protocol v3](doc/protocol/protocol-v3.md):
**fixed 600 MHz**, **1 MHz ADC pairs/GPIO**, **12-bit ADC PACK12**, **GPIO RLE_AUTO**,
and **auxiliary DISABLED** (8 inputs; INPUT selects 16). Query capabilities and
configure an exact advertised tuple while STOPPED. Runtime CPU switching is
unavailable. Exact-artifact physical qualification is **PASS (62/62 cells)**,
plus identity, metadata/reset, old-SDK and mixed-version checks. See the
[release notes and artifact hashes](doc/results/release-1.2.0.md),
[hardware evidence](doc/results/protocol-v3-hardware.md), and
[migration guide](doc/guides/protocol-v3-migration.md). Remote package publication
is separate; no 1.2.0 package was published by this qualification.

Install the SDK from the checkout with `python -m pip install ./daq_api`.
The installed package provides these hardware-free checks:

```bash
python -m thingdone_daq.protocol_upgrade
thingdone-daq probe --simulate --simulator-version 3 --json
thingdone-daq configure --simulate --simulator-version 3 --json
thingdone-daq capture --simulate --simulator-version 3 --duration 0.1 --strict-loss --json
```

`probe` includes identity, capabilities, defaults and active settings/clocks.
`configure` verifies the echo and GET_SETTINGS readback. Each simulated CLI
invocation creates a fresh device; the upgrade demo retains one session across
compressed/RAW/default changes and checks v1/v2 compatibility too.

## Historical releases and physical evidence

Release **1.1.0** uses **protocol v2**, a **450 MHz** core and fixed **1 MHz**
rates on both ADCs and GPIO. Select 8 or 16 GPIO inputs; other acquisition
rates are rejected. See the
[historical v2 compatibility contract](doc/protocol/protocol-v2.md).
Build identity, validation and limits are in the
[v1.1.0 release report](doc/results/release-1.1.0.md).
The optional equal-frame `TimestampAligner` is not supported for this new
profile; acquisition blocks provide exact per-sample timestamps.

Historical SDK combined ADC + 16-GPIO captures were unqualified for sustained
lossless capture. Their queue-loss failure reproduced under a 0.5-core host quota.
Two allocated cores passed short captures, width transitions and a 600-second
SDK repeat, but another SDK attempt timed out after 50.08 seconds with firmware
ADC DMA error counters and zero host throttling. The independent wire validator
also passed a 600-second watchdog-enabled firmware baseline with two cores. See the
[historical watchdog baseline and SDK CPU comparison](doc/results/watchdog-sdk-20260927.md).
Those failures remain historical evidence. The supported v3 artifact passes its
separate complete matrix with two host cores and strict loss detection enabled.

Watchdog initialization remains disabled in the supported firmware. The
public-v3 STOP-boundary DMA fault was corrected and requalified; see the
[DMA recovery evidence](doc/results/protocol-v3-dma-recovery.md). A historical
disabled-watchdog build passed a 600-second SDK capture, but watchdog causation
is unproven. The legacy
runtime-health command reports watchdog disabled and timeout zero; v3 does not
expose that command. Reset cause is not captured while initialization is skipped. See the [decision and test evidence](doc/results/watchdog-disabled-20260927.md).

Current source uses an optimized, wire-compatible Adler-32 implementation.
Checksummed larger ADC frames are available as an opt-in research build, using
the independent wire validator rather than the public SDK. See the
[integration and reliability evidence](doc/results/experiments/reliability-20261011.md),
[ADC clock feasibility analysis](doc/research/adc-clock-options.md),
[528 MHz acquisition test results](doc/results/experiments/clock528-20261013.md),
and [600 MHz thermal repeats](doc/results/experiments/clock600-thermal-20261016.md).
The 600 MHz research image peaked at 68.6 °C over three ten-minute combined
16-input captures; two passed and one failed a parser-error check.

ThingDAQ (Thing Done DAQ) is firmware and a typed Python API for synchronized,
loss-visible acquisition on the Teensy 4.0 platform. It captures two
phase-shifted ADC channels and either eight or sixteen packed digital inputs. The same public API
runs against a deterministic in-memory simulator, so discovery, configuration,
parsing, timestamps, calibration, alignment, loss handling, and cleanup can be
developed without hardware.

> [!WARNING]
> Read the [hardware-safety guide](doc/reference/hardware-safety.md) before
> connecting a signal. A0/A1, D6-D13 and D16-D23 are 3.3 V inputs and are not 5 V
> tolerant. Host calibration does not add electrical protection.

## Supported acquisition

| Input | Physical schedule | Python representation |
| --- | --- | --- |
| ADC0 on A0/D14 | 1 MS/s, nominal ticks `0, 8, 16, ...` | unchanged 12-bit raw codes |
| ADC1 on A1/D15 | 1 MS/s, nominally 500 ns after ADC0 | unchanged 12-bit raw codes |
| GPIO D6-D13, optionally D16-D23 | 1 MS/s packed snapshots | 8-bit or little-endian 16-bit samples |

The timestamp domain is an unsigned, START-relative 8 MHz clock. Explicit ADC
interleaving yields the nominal order `ADC0[0], ADC1[0], ADC0[1], ADC1[1], ...`.
That 2 MS/s view does **not** increase the analog bandwidth of the converters,
pins, source, or front end.

## Start without hardware

Published packages remain separately versioned. The following installs the
published package, which need not contain the locally qualified 1.2.0 release:

```bash
python -m pip install thingdone-daq
```

For development from this checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable './daq_api[dev,numpy]'
```

Run the complete deterministic demo or a bounded CLI capture:

```bash
.venv/bin/python -m thingdone_daq.protocol_upgrade
.venv/bin/thingdone-daq capture --simulate --simulator-version 3 --duration 1 --strict-loss \
  --gpio-channel D6 --gpio-channel D13
```

Run the autonomous experiment baseline from a clean checkout. This exercises
the historical simulator profile and invokes the firmware builder
without uploading it, and writes validated JSON and structured Markdown:

```bash
.venv/bin/python firmware/tools/baseline_prototype.py \
  --output-dir doc/results/experiments
```

The baseline's simulator command-latency fields use a deterministic logical
clock so normalized reports are reproducible. They are simulator bookkeeping,
not host, live-USB, or target timing evidence.

Run the isolated auxiliary-input workload matrix entirely offline:

```bash
.venv/bin/python daq_api/examples/aux_input_matrix.py
.venv/bin/python daq_api/examples/aux_input_matrix.py \
  --output .maestro/aux-input-demo
```

The optional output prefix writes temporary shared-schema JSON and structured
Markdown. The printed 12 MB/s full-combined payload and protocol-framed byte
rates are analytic load hypotheses, not physical USB acceptance.
The validated two-run simulator/host result is retained in the
[auxiliary-input prototype evidence](doc/results/experiments/aux-input-prototype.md).
The subsequent target campaign and its reproducible pre-START DMA failure are
recorded in the
[final auxiliary-input report](doc/results/experiments/aux-input-bank.md).

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
from thingdone_daq import ADCBlock, GPIOBlock, ThingDAQ

with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
    print(daq.info(), daq.get_capabilities())
    applied = daq.configure()
    assert applied == daq.get_settings()
    run_id = daq.start()

    for item in daq.blocks(2):
        if isinstance(item, ADCBlock):
            print(run_id, item.adc0[0], item.adc1[0])
        elif isinstance(item, GPIOBlock):
            print(item.sample(0), item.channel(6)[0])

    daq.validate_stream_health()
    daq.stop()
```

V3 `configure()` selects an exact advertised tuple and returns
`V3AppliedSettings(settings, clocks)`. The SDK verifies CONFIGURE/START echoes,
GET_SETTINGS and INFO clocks. Omitted options use board defaults, not the prior
configuration. `stop()` drains and preserves settings; reboot restores defaults.

## Hardware use

Metadata-only enumeration never opens candidate ports:

```bash
.venv/bin/thingdone-daq list
.venv/bin/thingdone-daq probe --hardware-serial 20512460 --json
.venv/bin/thingdone-daq configure --hardware-serial 20512460 --json
.venv/bin/thingdone-daq monitor --hardware-serial 20512460 \
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

The historical ThingDAQ firmware 1.0.0 candidate had a byte-identical two-build freeze,
generated validators, and passing local software/build gates. Because the USB
identity, firmware build ID, host namespace, and packaging identity changed,
the earlier physical results are engineering history rather than release
acceptance for the renamed binary. Physical acceptance was pending at that
historical freeze; the v1.1.0 report qualifies only its recorded artifact.
The identity-pinned standalone and installed `thingdone-daq-soak` entry paths are
documented in the [soak harness guide](doc/guides/soak-harness.md). Both embed
the deterministic `firmware/soak/validation-manifest.json` contract; a
different INFO identity is rejected unless the explicit diagnostic override is
used, and override reports are always non-release.
The superseded artifacts, exact hashes, local packaging results, diagnostic
fixture smoke, and report interpretation for the earlier candidate remain in
the [Phase 12 Windows handoff](doc/results/phase-12-windows-handoff.md). Use
the soak harness guide only for its named legacy campaigns. Public-v3 physical
qualification requires its own candidate-bound runner and evidence.

Those runs used unstimulated A0/A1 and no declared external digital stimulus.
They do not establish analog accuracy, analog bandwidth, true aperture timing,
external GPIO transition timing, or compatibility with a particular customer
front end. The distinction between tested and untested claims is maintained in
the [hardware-safety guide](doc/reference/hardware-safety.md).

## Documentation map

- [Documentation index](doc/README.md)
- [Evidence index](doc/results/evidence-index.md)
- [M7 C, atomics, optimization and ITCM experiments](doc/results/m7-performance-experiments.md)
- [Phase 11 autonomous soak evidence](doc/results/phase-11-soak-evidence.md)
- [Phase 12 Windows validation handoff](doc/results/phase-12-windows-handoff.md)
- [Quickstart](doc/guides/quickstart.md)
- [Autonomous soak harness](doc/guides/soak-harness.md)
- [Python API architecture](doc/architecture/python-api.md)
- [Python API reference](doc/reference/api-reference.md)
- [Hardware safety](doc/reference/hardware-safety.md)
- [Calibration](doc/architecture/calibration.md)
- [Optional NumPy integration](doc/architecture/numpy-integration.md)
- [Current protocol v3](doc/protocol/protocol-v3.md)
- [Legacy protocol v2](doc/protocol/protocol-v2.md)
- [Historical protocol v1](doc/protocol/protocol-v1.md)
- [System overview](doc/architecture/system-overview.md)
- [Phase 10 package workflow evidence](doc/results/phase-10-package-workflows.md)

The additive [public v3 contract](doc/protocol/protocol-v3.md) defines bounded
capability/settings queries and explicit RAW/RLE/PACK12 framing. Its generated
constants, codecs and opt-in Python simulator sessions are available offline.
The Python API, serial negotiation and CLI support v3 plus historical v1 and
release v2 peers. Supported firmware runs v3 at fixed 600 MHz; see the
[exact-artifact hardware qualification](doc/results/protocol-v3-hardware.md) and
[host compatibility gate](doc/results/protocol-v3-python.md).

```python
from thingdone_daq import ThingDAQ

with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
    capabilities = daq.get_capabilities()
    applied = daq.configure()  # Advertised 600 MHz, 1 MHz/1 MHz, RLE_AUTO/PACK12
    assert daq.get_settings() == applied
    daq.start()
    blocks = list(daq.blocks(4))  # Ordinary ADCBlock/GPIOBlock decoded samples
    daq.validate_stream_health()
    daq.stop()  # Waits for STOPPED; preserves settings
```

Pass an exact `V3Settings` tuple from `capabilities.configurations` to
`configure()` for other advertised settings, including RAW at fixed 600 MHz. The
ordinary v3 simulator advertises 48 tuples and only the 600 MHz CPU profile;
450 MHz requests are rejected without changing settings. Clock values are
simulated metadata. Omitting `protocol_version` retains the historical
simulator defaults. See the [v3 session API](doc/protocol/protocol-v3.md#public-simulator-session).

Run the deterministic public-v3 demonstration without hardware:

```bash
.venv/bin/python -m thingdone_daq.protocol_upgrade
```

It prints all advertised tuples, verifies exact ADC/GPIO samples and timestamps,
reports compression byte counts and RAW fallback, and exercises stopped
compressed/RAW/default configuration changes at fixed 600 MHz, rejection of a
nonadvertised 450 MHz profile, and rejected running reconfiguration. This does
not measure hardware throughput.
The CLI exposes v3 metadata and exact configuration tuples through `probe`:

```bash
.venv/bin/python -m thingdone_daq.cli probe --simulate --simulator-version 3 --json
.venv/bin/python -m thingdone_daq.cli configure --simulate --simulator-version 3 --cpu-profile cpu_600mhz --gpio-policy raw --adc-policy raw --json
```

Omitted v3 selectors use advertised defaults. The offline upgrade demo also
checks automatic negotiation and exact capture against historical v1 and
v2-only release personas. See the [CLI reference](doc/reference/api-reference.md#cli-and-examples)
for selectors, output fields and legacy behavior.

See the [v3 upgrade architecture](doc/architecture/protocol-v3-upgrade.md) and
[offline validation results](doc/results/protocol-v3-prototype.md) for the
component boundaries, reproducible gates and capture byte counts.

## Repository layout and checks

- `firmware/`: Teensy 4.0 sketch, portable C++ components, build tooling, and
  host-compiled firmware tests.
- `daq_api/`: installable `thingdone_daq` package, CLI, simulator, examples, and
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
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python -m pytest
python3 firmware/tools/build_firmware.py
```

`pytest.ini` selects both repository suites (`firmware/tests` and `daq_api/tests`)
by default, keeping ignored scratch checkouts and archived rig evidence out of
test discovery. Explicit test paths still work for focused checks.

The firmware builder targets `speed=600`, pins acquisition timing to the same
600 MHz clock, and exports to
`firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/`.
It does not flash the device. Public-v3 defaults use RLE_AUTO and PACK12 without
private codec flags. See the [build and compatibility guide](doc/guides/firmware-builds.md)
for manifest provenance, explicit v2 RAW operation, and reproduction of the
historical 450 MHz release from its recorded revision.

## Distribution and trademark boundary

The Python distribution is `thingdone-daq`; the import package is
`thingdone_daq`. See the [Python package README](daq_api/README.md) and
[Python changelog](daq_api/CHANGELOG.md). Firmware, protocol, and Python SDK
versions are independent. Other language SDKs can share `protocol/` and its
golden fixtures; the [SDK documentation plan](doc/architecture/sdk-layout.md)
describes language-specific documentation boundaries.

ThingDAQ is an independent project and is not affiliated with or endorsed by
PJRC.COM, LLC or SparkFun Electronics. Teensy® is a registered trademark of
PJRC.COM, LLC. References to Teensy identify the supported hardware platform;
they are not part of the ThingDAQ product name.

## License

This project is available under the [MIT License](LICENSE).
Copyright (c) 2026 THING DONE LLC.
