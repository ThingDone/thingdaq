---
type: reference
title: Public v3 SDK and firmware migration
created: 2026-10-20
tags:
  - protocol-v3
  - migration
  - compatibility
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-migration]]'
  - '[[Protocol-V1]]'
  - '[[Protocol-V2]]'
  - '[[Quickstart]]'
  - '[[API-Reference]]'
  - '[[firmware-builds]]'
---

# Public v3 SDK and firmware migration

The supported 1.2.0 release defaults to fixed 600 MHz CPU, both streams at
1 MHz, 12-bit ADC PACK12, GPIO RLE_AUTO and auxiliary DISABLED (8 GPIO inputs).
INPUT selects 16 bits. Firmware version 1.2.0, SDK version 1.2.0 and wire version
3 are independent identities. Exact-artifact physical qualification is
**PASS (62/62 cells)** plus supplemental identity, metadata/reset, isolated
pre-upgrade SDK and mixed-version checks. See [[release-1.2.0]] for supported
artifact hashes and [[protocol-v3-hardware]] for evidence and measurement limits.
Install from the checkout or retained local wheel; remote publication is separate.

## Compatibility matrix

| Python client | Firmware | Behavior |
| --- | --- | --- |
| New v3-aware SDK | Supported public v3 | Negotiates v3; advertised compressed defaults, exact tuple selection and active settings/clocks readback |
| New v3-aware SDK | Historical v1 | Explicit version rejection permits fallback to v1; existing layouts, models, rate checks and commands retained |
| New v3-aware SDK | Historical v2 / release 1.1.0 | Negotiates v2 after explicit rejections; legacy RAW layouts and 1 MHz policy retained |
| Older v2 SDK (1.1.0) | Supported public v3 | Explicit v2 CONFIGURE/START yields legacy RAW frames at the new firmware's actual fixed 600 MHz clock |
| v1-only SDK | Supported public v3 | No guarantee of acquisition; the new firmware need not acquire in v1 mode |
| Any ordinary public SDK | Private `0x82` / `0x83` experiment | No automatic support or decoding as public v3; use matching archived tooling only for offline evidence inspection |

The new SDK probes INFO in order **3 → 1 → 2**. It advances only after an
explicit correlated UNSUPPORTED_VERSION response. Timeouts, malformed metadata,
checksum failures, wrong identity or unsupported private frames do not permit
silent downgrade. Opening requires two stable INFO identities. The normal v3
frame parser discards non-v3 versions; the device's negotiation dispatcher is a
separate compatibility boundary. A v1 INFO compatibility path does not promise
v1 acquisition. `--simulator-version` chooses a peer, not a forced physical wire
version. Use an older v2 client for explicit v2 acquisition on new firmware.

## Installed offline demonstration

From the repository root:

```bash
python -m pip install ./daq_api
python -m thingdone_daq.protocol_upgrade
thingdone-daq probe --simulate --simulator-version 3 --json
thingdone-daq configure --simulate --simulator-version 3 --json
thingdone-daq capture --simulate --simulator-version 3 --duration 0.1 --strict-loss --json
```

The installed demo reuses the checkout `daq_api/examples/protocol_upgrade.py`
implementation. It verifies exact ADC/GPIO samples and timestamps through
compressed → RAW → compressed runs, adaptive RLE fallback, stopped readback,
rejection of nonadvertised CPU selection and running CONFIGURE, and legacy
v1/v2 captures. The clocks are simulated metadata, not measured throughput.
Separate simulated CLI commands each create a fresh peer. The default simulator
and `thingdone-daq-demo` remain historical v1 for existing regression users.

## Configure and capture public v3

Use `probe` first to inspect `info`, `capabilities`, `defaults`, `active_settings`
and `state`. Only complete `capabilities.configurations` tuples are selectable;
known profile IDs alone authorize nothing. Both rates remain 1 MHz even when
one stream is disabled. Omitted configure options use advertised defaults,
not the previous settings. CPU switching, auxiliary OUTPUT, 528 MHz and higher
sample rates are unsupported.

```python
from thingdone_daq import ThingDAQ, V3AdcPolicy, V3GpioPolicy

with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
    print(daq.info(), daq.get_capabilities())
    raw = daq.configure(gpio_policy=V3GpioPolicy.RAW, adc_policy=V3AdcPolicy.RAW)
    assert daq.get_settings() == raw
    assert raw.clocks.cpu_clock_hz == 600_000_000
    daq.start()
    for block in daq.blocks(2):
        print(block.encoding.name, block.item_count, block.decoded_bytes)
    daq.validate_stream_health()
    daq.stop()
    assert daq.get_settings() == raw
    assert daq.configure().settings == daq.get_capabilities().defaults
```

The SDK checks the CONFIGURE echo, GET_SETTINGS and INFO clocks. START echoes
active settings again. GPIO RLE_AUTO can emit either RLE or RAW per frame;
PACK12 always emits packed ADC pairs. Logical `item_count` counts samples/pairs,
not bytes or runs. `payload` and channel views contain decoded values;
`encoded_payload` retains wire prefix/sample bytes. Use `encoding`,
`encoded_sample_bytes`, `decoded_bytes` and `wire_bytes` to distinguish them.
Variable frame lengths require timestamp-based logical loss accounting, not
sequence difference times a fixed count. Equal-duration `TimestampAligner` is
unsupported; use per-sample timestamps.

After checking [[Hardware-Safety]], replace the example serial with the attached
unit. These commands work from an installed package:

```bash
thingdone-daq probe --hardware-serial 20512460 --json
thingdone-daq configure --hardware-serial 20512460 --gpio-policy raw --adc-policy raw --json
thingdone-daq probe --hardware-serial 20512460 --json
thingdone-daq capture --hardware-serial 20512460 --duration 10 --strict-loss --json
```

`configure` leaves settings applied. `capture` configures its own selection;
omitting codec flags restores advertised compressed defaults. Add `--gpio-policy
raw --adc-policy raw` to capture RAW with **v3** framing, or `--aux-bank-mode
input` for 16 GPIO bits. Capture owns START/STOP and closes the port on exit.

## Older v2 Python with new firmware

Close and drain the v3 session before connecting the older client. Use an
isolated SDK 1.1.0 environment (or its archived wheel), as detailed in
[[firmware-builds]]. With that environment's Python:

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
        assert block.protocol_version == 2
        print(block)
    daq.validate_stream_health()
    daq.stop()
```

The v2 request selects the legacy wire path; private compression flags are not
needed. All five documented v2 stream/width configurations passed using unchanged
pre-upgrade SDK revision `3a52ead02791019fcdb0b27a8be869effc955aa2`. ADC-only
with auxiliary INPUT is invalid in v2; use DISABLED for ADC-only. Incomplete
STOP tails are explicitly bounded and reconciled separately from complete packets.
Read live INFO for the actual 600 MHz clock. The historical 1.1.0 450 MHz
artifact remains separately reproducible; do not relabel its hashes or assume
its qualification transfers. New Python's v3 RAW policies do not emulate v2.

## Reset, reconnect and diagnostics

- STOP ends production and drains all queued complete frames/partial transport
  tails. The SDK waits until STOPPED with `pending_frames=0`; repeated STOP is
  idempotent. Settings and final counters remain available.
- Reconnect is not reboot. It preserves device settings/state and rereads INFO,
  capabilities, settings and status. Use `session_policy="stop"` to drain an
  abandoned run before configuring. The default `"adopt"` preserves its epoch;
  it cannot recover samples missed before attachment. Never reuse cached settings
  or a cached COM path after reset; select the stable hardware serial.
- Reboot restores defaults, STOPPED, run ID zero, empty queues/counters and replay
  history. Close the old session and open a new one after re-enumeration; START
  supplies a fresh nonzero run ID. CONFIGURE is optional after reboot.
- V3 has no RESET_STATS, temperature, runtime-health, or legacy full-conservation
  wire command. SDK/CLI reconciliation can still check advertised counters,
  without proving complete DMA conservation. Successful START resets run counters. STATUS validity bits mark
  measured diagnostics; unavailable values are `None`/JSON `null`, never an
  invented zero. Host/parser continuity and available firmware counters still
  participate in strict stream-health checking.

See [[protocol-v3-upgrade]] for architecture, [[protocol-v3]] for byte layouts,
and [[protocol-v3-migration]] for this compatibility boundary.
