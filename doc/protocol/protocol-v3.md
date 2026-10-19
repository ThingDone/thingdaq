---
type: reference
title: Public protocol v3 contract
created: 2026-10-19
tags:
  - protocol-v3
  - wire-contract
  - offline
related:
  - '[[protocol-v2]]'
  - '[[protocol-v3-foundation]]'
  - '[[deferred-codecs-20261018]]'
---

# Public protocol v3 contract

`protocol/protocol-v3.json` is the canonical v3 wire contract. This checkpoint
provides validated schemas, separate Python/C++ constants, golden frames and
opt-in Python codecs, a simulated v3 device and public ThingDAQ simulator
sessions. Production firmware and serial negotiation are not enabled.
The current product still uses [[protocol-v2]]. Physical results in
[[deferred-codecs-20261018]] concern private research versions, not v3.

Generate with `.venv/bin/python tools/generate_protocol.py`; verify with
`--check`. `--protocol v3` selects only the new outputs. V1/v2 sources and all
111 existing generated artifacts retain their original bytes. V3 constants
and `protocol/fixtures-v3/manifest.json` contain the canonical source SHA-256;
the manifest also records each frame/payload hash and decoded sample examples.

## Framing and commands

The 44-byte little-endian header, four-byte trailer, request correlation,
run IDs and 8 MHz START-relative timestamp domain retain their existing
positions. Every v3 frame uses version **3** and mandatory Adler-32 over the
transmitted header and payload. Header byte 11 remains reserved zero.
Private versions `0x82/0x83` are not v3 encodings.

| Command | Request / response kind | Request payload | Success payload |
| --- | --- | --- | --- |
| INFO | `0x10 / 0x90` | 0 | 132 |
| CONFIGURE | `0x11 / 0x91` | 20 | 48 |
| START | `0x12 / 0x92` | 0 | 48 |
| GET_STATUS (STATUS) | `0x13 / 0x93` | 0 | 80 |
| STOP | `0x14 / 0x94` | 0 | 16 |
| GET_CAPABILITIES | `0x1C / 0x9C` | 0 | 1404 |
| GET_SETTINGS | `0x1D / 0x9D` | 0 | 48 |

Lengths are bytes excluding header/trailer. Normal error responses have a
four-byte prefix; generic ERROR_RESPONSE (`0x9F`) has eight bytes including
the rejected kind. IDs `0x15..0x1B` remain reserved for legacy commands and
are not reallocated. The maximum command/control frame sizes are 68/2048.
JSON defines every offset, enum, reserved byte, validation order and error.

## Capabilities and settings

INFO supplies board/MCU identity, serial, firmware version, build ID,
simulation flag and active CPU/IPG/ADC/PIT/timestamp clocks in Hz. The board
is Teensy 4.0, including when emulated; `simulated=1` and a `SIM-` serial make
simulation explicit. Known clock profiles are:

| Profile ID | CPU Hz | IPG Hz | ADC Hz | PIT Hz | Timestamp Hz |
| --- | --- | --- | --- | --- | --- |
| 1 | 600000000 | 150000000 | 37500000 | 24000000 | 8000000 |
| 2 | 450000000 | 150000000 | 37500000 | 24000000 | 8000000 |

Only rate profile 4 (ADC-pair and GPIO rates both 1000000 Hz) is defined.
Capabilities use fixed capacities of two CPU records, one rate record and
64 complete settings records; counts bound the valid leading entries and
unused slots are entirely zero. Known profiles alone do not authorize any
configuration. A requested 20-byte settings record must exactly match an
advertised tuple, including settings for disabled streams.

The canonical table contains 60 tuples: ADC/GPIO/both, hardware/synthetic,
8/16 GPIO bits, four RAW/compressed policy combinations at 600 MHz, and RAW
only at 450 MHz. Devices may advertise a subset containing board defaults.
Widths follow auxiliary mode DISABLED/INPUT; OUTPUT, 528 MHz and historical
higher-rate profiles are absent. Defaults are both streams, hardware source,
600 MHz, 1 MHz/1 MHz, 12-bit ADC, auxiliary DISABLED, GPIO RLE_AUTO, ADC PACK12.

CONFIGURE validates and applies all settings atomically while STOPPED with
drain complete. It returns the exact settings plus active clocks; GET_SETTINGS
reads the same record. Unsupported or contradictory tuples cause no partial
mutation. RUNNING returns INVALID_STATE; DRAINING returns BUSY. STOP preserves
settings and drains already queued frames before STOPPED. START returns the
applied settings and new run ID before data. Reboot restores defaults; settings
are not persistent. Wire mode cannot change during acquisition or drain.

## Encoded data

Every data payload starts with this prefix, then sample bytes:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u8 | Encoding: RAW=0, GPIO_RLE=1, ADC_PACK12=2 |
| 1 | u8 | Decoded item width: ADC=4, GPIO=1 or 2 |
| 2 | u16 | Reserved zero |
| 4 | u32 | Decoded sample bytes = item_count × item width |
| 8 | u32 | RLE record count; zero for RAW/PACK12 |

`item_count` always counts logical ADC pairs/GPIO samples. Maximum decoded
and encoded sample storage is 4048 bytes, excluding the prefix; maximum wire
frame is 4108 bytes. Frames may contain 1..1012 ADC pairs, 1..4048 GPIO8 samples
or 1..2024 GPIO16 samples. Check all bounds and exact lengths before expansion.

RAW ADC is ADC0 u16 LE followed by ADC1 u16 LE, with both codes at most 4095.
For ADC0=`a` and ADC1=`b`, PACK12 bytes are `a & 255`,
`(a >> 8) | ((b & 15) << 4)`, `b >> 4`. For example `(0xABC, 0x123)` becomes
`BC 3A 12`. Out-of-range inputs are rejected before packing. PACK12 policy
always uses PACK12; RAW ADC policy always uses RAW.

GPIO RLE records are a nonzero u16 LE run length followed by an 8-bit or u16 LE
sample. Runs are maximal, adjacent values differ, record count is explicit,
and their lengths sum exactly to `item_count`. RLE_AUTO selects RLE only when
its sample bytes are strictly fewer than RAW; ties and expansion use RAW.
GPIO bit positions retain primary D6..D13, then auxiliary D16..D23.

Timestamps do not depend on encoding: ADC0/GPIO advance eight ticks per item;
ADC1 follows ADC0 by four ticks. Sequence counters are per stream and include
dropped frames; timestamps advance across missing logical samples. JSON defines
loss flags, epoch rules, status counters and STOP/drain ordering. Frames across
streams need not cover equal durations.

## Verification scope

`daq_api/tests/test_protocol_v3_generation.py` independently checks framing,
checksums, hand-derived packed/RLE bytes, exact capability records, rejected
contract mutations, all version-selecting generator paths, and the frozen
legacy artifact digest recorded in [[protocol-v3-foundation]].
`daq_api/tests/test_protocol_v3_codecs.py` exercises runtime controls and samples,
exact golden-byte round trips, malformed metadata, count/expansion bounds,
RLE tie fallback, PACK12 bit positions and bounded parser recovery.
`daq_api/tests/test_simulator_v3.py` covers all 60 advertised tuples, encoded
commands, atomic configuration, replay, chunking, corruption and transport drain.
`daq_api/tests/test_public_api_v3.py` covers the completed public-session path;
`daq_api/tests/test_examples.py` asserts the executable demo's results and cleanup.
See [[protocol-v3-upgrade]] for architecture and [[protocol-v3-prototype]] for
reproducible offline validation results.

## Opt-in Python codecs

`thingdone_daq.protocol_v3` supplies `encode_v3_frame`, `decode_v3_frame`,
`V3FrameParser`, `encode_adc_payload`, `encode_gpio_payload` and
`decode_data_payload`. The parser reuses the existing bounded scanner and
checksum backend; it accepts only explicitly selected public-v3 frames.
A truncated stream stays buffered within its fixed bound until completed or
reset; the single-frame decoder rejects truncation and trailing bytes.

`thingdone_daq.models_v3` supplies typed settings, clocks, rates, identity,
capabilities, applied settings, status, STOP state and command/response records.
Use `V3Capabilities.require_supported(settings)` to check a device's exact
advertised subset and `V3Response.validate_for(command)` to check correlation
and the CONFIGURE echo. State transitions, replay tracking and atomic application
belong to the device/session integration; these codecs do not mutate state.

`decode_v3_block(frame, settings)` validates selected stream/source/width/policy
and returns the existing `ADCBlock` or `GPIOBlock`. Channel views and timestamps
use decoded samples. `encoded_payload` retains the transmitted prefix and sample
bytes; `encoded_sample_bytes`, `decoded_bytes` and `wire_bytes` distinguish sample
compression from complete frame overhead. Variable logical counts apply only to
v3 blocks; v1/v2 retain their fixed layouts and existing behavior.

## Opt-in simulated device

Construct `SimulatedV3Device` from `thingdone_daq.simulator_v3` and pass it to
`InMemoryTransport`. Send `V3Command.to_bytes()` through transport writes and
parse reads with `V3FrameParser`; partial writes/reads follow the same transport
contract as v1/v2. The public session below wires these through the shared
background reader and compatible parser.
The historical `SimulatedDevice` and default transport persona remain unchanged.

The v3 peer starts STOPPED with the advertised board defaults already applied.
INFO always sets `simulated=True`, uses a `SIM-` serial and identifies its build
as `thingdaq-simulator-v3`. HARDWARE source represents emulated board input;
SYNTHETIC source sets the wire flag. Both use deterministic samples. Selecting
450 MHz changes metadata only; no simulator rate measures hardware throughput.

GPIO frames alternate all-zero input and high-transition input using existing
synthetic formulas: primary bytes alternate AA/55, auxiliary bytes 0F/F0.
RLE_AUTO therefore emits RLE followed by RAW at either GPIO width. ADC uses
`synthetic_v3_adc_payload`: the existing 12-bit ramp, with each 2048-pair cycle's
first four pairs replaced by `(0,0)`, `(4095,4095)`, `(0xABC,0x123)` and
`(0x555,0xAAA)`. This exercises edge values and every packed bit position.

START resets per-stream sequences, timestamps and logical counters; its response
precedes data. The transport produces one frame per requested credit. STOP
preserves settings and enters DRAINING while a partially read data frame remains;
START/CONFIGURE return BUSY until that tail is consumed. Already queued responses
retain their original state snapshots: query GET_STATUS again after draining to
observe STOPPED. Closing a transport discards any pending tail and records its
frame/items as dropped; reconnect preserves settings/run and clears request replay
history. `device.reboot()` while detached restores defaults and all initial state.

## Public simulator session

`ThingDAQ.simulated(protocol_version=3)` explicitly selects the v3 persona.
Opening performs two stable-identity INFO queries, GET_CAPABILITIES,
GET_SETTINGS and GET_STATUS over the wire. The default selector remains `1`
(the historical v1/v2 simulator). Production serial discovery/negotiation,
CLI and legacy capture tooling remain unchanged. Facade return annotations now
include the v3 model variants; default v1/v2 sessions still return their original
models. Consumers accepting either session type should narrow the returned type.

- `info()` / `device_info`: `V3Info`, including simulated identity and clocks.
- `get_capabilities()` / `capabilities`: `V3Capabilities` with exact selectable tuples.
- `get_settings()`: `V3AppliedSettings` containing settings and applied clocks.
- `configure(V3Settings)` checks the advertised subset, verifies the exact echo,
  and performs GET_SETTINGS readback before accepting it. `configure()` starts
  from advertised defaults; existing stream/source/rate/auxiliary keyword options
  select a matching tuple. Do not combine a settings object with those options.
- `configuration` is the current `V3Settings`. Choose 450 MHz with both encoding
  policies RAW, then call `configure()` while stopped to restore compressed
  600 MHz defaults. Running changes receive a correlated INVALID_STATE error.
- `start()` may use board defaults without a preceding CONFIGURE; it checks
  settings readback and the START echo and returns a new nonzero run ID.
- `blocks()` / `read_block()` retain ordinary ADCBlock/GPIOBlock channel views,
  8 MHz timestamps, per-stream sequences and bounded queue-loss reports.
- `stop()` waits through DRAINING to `V3DeviceState.STOPPED` within the command
  deadline. It preserves settings. Context-manager exit stops and closes the
  shared reader/transport deterministically.

V3 `status()` returns the contract's `V3Status`, not legacy hardware-health
telemetry. `validate_stream_health()` checks available v3 drop counters and
shared host/parser/continuity evidence. `loss_counters()` maps run-relative
frame/item drops and derived decoded byte losses into the common loss view;
legacy-only firmware telemetry is unavailable. It does not measure hardware
throughput or analog accuracy.

Variable-length v3 frames use sequence deltas for missing **frames** and timestamp
deltas for missing logical **items**. Their StreamGap has
`variable_frame_items=True` and `sequence_inferred_items=None`; sequence alone
cannot determine missing item counts. HostQueueLoss sums the actual evicted
counts and retains exact timestamp intervals. For variable frames,
`frame_item_count` describes the reference frame, not a fixed count for every
lost frame; use `missing_items` / `dropped_items` for loss accounting. Fixed
v1/v2 count validation remains intact.
