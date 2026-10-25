---
type: reference
title: Public v3 release builds and legacy RAW compatibility
created: 2026-10-20
tags:
  - firmware
  - build
  - protocol-v3
related:
  - '[[protocol-v3-migration]]'
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[release-1.1.0]]'
---

# Public v3 release builds and legacy RAW compatibility

## Supported artifact and standard build

The supported artifact is the unchanged frozen HEX named in [[release-1.2.0]]
and `firmware/soak/protocol-v3-release.json`; use its recorded hash when flashing.
Promotion did not rebuild firmware. A new build is not automatically qualified.

For source reproduction from the repository root, with Arduino CLI, Teensy
core 1.62.0 and Arm GNU 15.2.1 installed:

```bash
.venv/bin/python firmware/tools/build_firmware.py
```

The builder uses `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`.
Artifacts and `build-manifest.json` are exported under
`firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/`.
The command builds without uploading. No private compression switches or
experiment environment variables are required.

Public settings come from `protocol/protocol-v3.json`, through generated
constants and `board_profile.h` / `v3_settings.h`: fixed 600 MHz, 1 MHz ADC
pairs and GPIO samples, auxiliary DISABLED (8 GPIO bits), RLE_AUTO and PACK12.
CONFIGURE selects exact advertised tuples while stopped; CPU switching is
unavailable. The SDK uses advertised defaults when v3 configuration options
are omitted:

```python
from thingdone_daq import ThingDAQ

with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
    applied = daq.configure()
    assert applied == daq.get_settings()
    print(applied)
```

The simulator default remains the historical persona for existing examples.
Select `protocol_version=3` explicitly for offline v3 work; physical opens
negotiate the firmware's supported protocol.

Manifest schema 12 records the canonical defaults, fixed-clock tuple filter,
firmware version, schema/generated-header/board-policy/recipe hashes and
public codec selection. The source identity covers all firmware sources,
v1/v2/v3 schemas, and both normal and experiment build recipes.
`SOURCE_DATE_EPOCH`, when supplied, controls the build timestamp; otherwise
the latest source-input commit supplies it. Existing ELF placement, memory
headroom and allocation ownership checks remain required.

`binary_inspection.legacy_v2_packet_retention` describes only legacy layouts.
It is not a public-v3 retention estimate: public frames include a prefix and
use different logical item counts. V3 STATUS exposes the selected layout's
retention. The exact frozen release passed all 62 required hardware cells and
supplemental checks; see [[protocol-v3-hardware]].

Firmware **1.2.0**, wire protocol **3**, and SDK **1.2.0** are independently
versioned. The supported release manifest binds their exact tested hashes;
remote package publication is separate.

## Explicit v2 RAW operation

New firmware retains v2 CONFIGURE/START and RAW data for older v2 clients.
Use an isolated environment with SDK 1.1.0, which does not negotiate v3:

```bash
python3 -m venv .maestro/playbooks/Working/v2-sdk
.maestro/playbooks/Working/v2-sdk/bin/python -m pip install 'thingdone-daq==1.1.0'
```

Run this with that environment's Python, substituting the connected device's
hardware serial:

```python
from thingdone_daq import AuxBankMode, RateProfile, Source, ThingDAQ

with ThingDAQ.open(hardware_serial=20512460, strict=True) as daq:
    daq.configure(
        adc=True,
        gpio=True,
        source=Source.HARDWARE,
        rate_profile=RateProfile.ADC_1MHZ_GPIO_1MHZ,
        aux_bank_mode=AuxBankMode.DISABLED,
    )
    daq.start()
    for block in daq.blocks(2):
        print(block)
    daq.stop()
```

This preserves v2 framing and RAW samples at the new build's fixed 600 MHz.
Selecting RAW policies in a v3 session still produces v3 frames; it does not
select v2. Close the active session before changing clients. Private research
versions `0x82`/`0x83` are not part of either compatibility workflow.

## Historical 450 MHz reproduction

The immutable 1.1.0 firmware source reference is
`e3e8417598de7494db3a93d7277ef8f0ec31bc8f`. In a separate checkout of that
revision, run its own `firmware/tools/build_firmware.py` with the pinned
toolchain. That recipe selects `speed=450` and its historical output directory.
Compare source identity, timestamp, and artifact hashes against
[the recorded release manifest and report](../results/release-1.1.0.md).

Current `build_input_experiment.py --cpu-mhz 450 --release-fixed-1mhz`
remains an explicit research selection. It compiles current sources and
does not reproduce the historical release. Never overwrite or relabel old
artifacts as public-v3 defaults. See [[protocol-v3-upgrade]] and
[[protocol-v3]] for the current contract.
