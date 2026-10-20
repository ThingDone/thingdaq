---
type: reference
title: Public protocol v3 contract
created: 2026-10-19
tags:
  - protocol-v3
  - wire-contract
  - offline
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-migration]]'
  - '[[protocol-v2]]'
  - '[[protocol-v3-foundation]]'
  - '[[deferred-codecs-20261018]]'
---

# Public protocol v3 contract

The [canonical schema](../../protocol/protocol-v3.json) defines public wire
version **3**. The current 1.2.0 development firmware/SDK implement negotiation,
metadata, atomic stopped configuration, acquisition and CLI support. Normal
builds use fixed **600 MHz**, **1 MHz** ADC pairs/GPIO, **12-bit ADC PACK12**,
**GPIO RLE_AUTO** and auxiliary **DISABLED**. Runtime CPU switching is unavailable.
Physical qualification remains **NOT_RUN**. [[Protocol-V2]] is the historical
compatibility contract; private `0x82`/`0x83` results are separate research.
See [[protocol-v3-migration]] for cross-version operation and reset/reconnect.

Generate with `.venv/bin/python tools/generate_protocol.py`; verify with
`--check`. `--protocol v3` selects only v3 outputs. Frozen v1/v2 artifacts remain
unchanged. The [generated vector manifest](../../protocol/fixtures-v3/manifest.json)
records the canonical SHA-256, frame/payload hashes and decoded examples;
[Python constants](../../daq_api/src/thingdone_daq/_generated/protocol_v3_constants.py)
are generated from the same source. The fixture catalogue includes all 60
canonical tuples; it is not an advertisement of the normal board's 48 tuples.

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
| GET_STATUS (STATUS) | `0x13 / 0x93` | 0 | 384 |
| STOP | `0x14 / 0x94` | 0 | 16 |
| GET_CAPABILITIES | `0x1C / 0x9C` | 0 | 1404 |
| GET_SETTINGS | `0x1D / 0x9D` | 0 | 48 |

Lengths are bytes excluding header/trailer. Normal error responses have a
four-byte prefix; generic ERROR_RESPONSE (`0x9F`) has eight bytes including
the rejected kind. IDs `0x15..0x1B` remain reserved for legacy commands and
are not reallocated. The maximum command/control frame sizes are 68/2048.
JSON defines every offset, enum, reserved byte, validation order and error.

### Envelope, checksum and correlation

All integers are unsigned little-endian. No implicit padding is allowed.

| Offset | Type | Field |
| --- | --- | --- |
| 0 | u32 | `magic` |
| 4 | u8 | `version` |
| 5 | u8 | `kind` |
| 6 | u16 | `flags` |
| 8 | u16 | `header_length` |
| 10 | u8 | `checksum_algorithm` |
| 11 | u8 | `reserved` |
| 12 | u32 | `total_length` |
| 16 | u32 | `payload_length` |
| 20 | u32 | `run_id` |
| 24 | u32 | `sequence` |
| 28 | u32 | `request_id` |
| 32 | u64 | `first_sample_ticks` |
| 40 | u32 | `item_count` |

Magic is `0xDEADBEEF` (`EF BE AD DE` on wire); version is 3, header_length is
44, checksum_algorithm is 1 (Adler-32), and every reserved field/bit is zero.
`total_length = 44 + payload_length + 4`. The trailer is a little-endian u32
Adler-32 of **all header bytes starting at magic plus transmitted payload**,
excluding the trailer. Adler starts with A=1/B=0, updates modulo 65521 per byte,
and stores `(B << 16) | A`. Compression is checked before expansion; never
checksum the decoded samples in place of transmitted bytes. CRC modes are not
v3 options. Minimum frame size is 48 bytes; request/control/data maxima are
68/2048/4108 bytes respectively. Advertised device bounds may be smaller.

Requests have nonzero `request_id`, zero run/sequence/timestamp/item fields,
and zero flags. Responses echo request ID and paired kind (or generic ERROR
with rejected kind); `run_id` is the current/most recent run, zero before START.
Other data-only response fields are zero. START returns the newly assigned run
ID. Hosts must not reuse request IDs within a connection or automatically replay
commands. Devices reject zero and duplicate IDs in their last-16 accepted-ID
window. Dispatched command errors occupy that window; zero/duplicate IDs do not.
Older IDs have no replay guarantee; reconnect clears the replay window.

| Flag | Value | Scope |
| --- | --- | --- |
| SYNTHETIC | `0x0001` | Data source is SYNTHETIC |
| GAP_BEFORE | `0x0002` | Logical items/frames missing before this data frame |
| EPOCH_START | `0x0004` | First transmitted frame of this stream/run |
| OVERRUN_BEFORE | `0x0008` | Firmware loss; also requires GAP_BEFORE |
| RESPONSE_ERROR | `0x8000` | Error response only |

Data kinds are ADC_DATA (`0x01`) and GPIO_DATA (`0x02`); their request ID is
zero, run ID matches START and is nonzero. Per-stream u32 sequences start at
zero and advance modulo 2^32 for every produced frame, including dropped frames.
Timestamps count logical items, never encoded bytes or RLE records.

### Errors and validation order

Every response begins `response_status:u8, reserved:u8=0, error_code:u16`.
Success has status 0/code 0, RESPONSE_ERROR clear and the full success payload.
Failure has status 1/nonzero code, RESPONSE_ERROR set and exactly four payload
bytes. Generic ERROR_RESPONSE adds `rejected_kind:u8` at offset 4 and three
zero reserved bytes. A zero-ID request's INVALID_REQUEST_ID reply is the sole
allowed response with request ID zero. Errors do not mutate settings, run ID
or acquisition state.

| Error | Code | Meaning |
| --- | --- | --- |
| OK | 0 | Success only; never set RESPONSE_ERROR. |
| UNSUPPORTED_VERSION | 1 | Reserved legacy meaning; mismatched version is discarded before v3 command dispatch. |
| UNKNOWN_FRAME_KIND | 2 | Checksummed request with unsupported kind, including reserved legacy commands; generic ERROR_RESPONSE carries rejected_kind. |
| INVALID_FLAGS | 3 | Checksummed request has nonzero flags. |
| INVALID_LENGTH | 4 | Bounded checksummed request has wrong schema payload length. Unbounded/untrusted framing is discarded. |
| INVALID_PAYLOAD | 5 | Nonzero reserved fields, unknown enum values, zero stream mask, out-of-domain scalar or nonzero data-only request header fields. |
| UNSUPPORTED_CHECKSUM | 6 | Reserved legacy meaning; only Adler-32 frames are admitted in v3, so unknown algorithms are discarded. |
| INVALID_STATE | 7 | CONFIGURE or START while RUNNING. |
| UNSUPPORTED_CONFIGURATION | 8 | Well-formed settings absent from advertised exact tuples, including contradictory width/auxiliary mode or 450 MHz compression. |
| INVALID_REQUEST_ID | 9 | Request ID is zero or duplicated in the last-16 accepted-request window. A zero ID response echoes zero as the sole correlation exception. |
| BUSY | 10 | CONFIGURE or START during DRAINING or incomplete transport drain. |
| INTERNAL_ERROR | 11 | Device cannot execute an otherwise valid command; any attempted CONFIGURE application is fully rolled back. |
| CHECKSUM_MISMATCH | 12 | Reserved legacy meaning; corrupt checksums are discarded without response. |

Validation order is bounded framing/checksum → known request kind → request
ID/replay → flags/fixed payload length → reserved/data-only fields and scalar/
enum validity → command state → exact tuple/cross-field consistency → atomic
application. Untrusted lengths, bad magic/version/checksum and oversize frames
are discarded with bounded resynchronization, not answered from untrusted data.
A checksummed bounded request can receive a correlated error. V3 parser rules
do not define legacy INFO negotiation; see [[protocol-v3-migration]].

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
only at 450 MHz. The normal firmware and ordinary v3 simulator advertise only
the 48 fixed-600 MHz tuples and one CPU record. The 450 MHz wire ID remains
known for compatibility, but does not imply device support. Devices advertise
a subset with build defaults drawn from that subset.
Advertised device limits may be smaller than the canonical maxima; they must
remain positive, fit the capability response and respect framing and logical
item capacity relationships.
Widths follow auxiliary mode DISABLED/INPUT; OUTPUT, 528 MHz and historical
higher-rate profiles are absent. Reference defaults are both streams, hardware source,
600 MHz, 1 MHz/1 MHz, 12-bit ADC, auxiliary DISABLED, GPIO RLE_AUTO, ADC PACK12.

CONFIGURE validates and applies all settings atomically while STOPPED with
drain complete. It returns the exact settings plus active clocks; GET_SETTINGS
reads the same record. Unsupported or contradictory tuples cause no partial
mutation. RUNNING returns INVALID_STATE; DRAINING returns BUSY. STOP preserves
settings and drains already queued frames before STOPPED. START returns the
applied settings and new run ID before data. Reboot restores defaults; settings
are not persistent. Wire mode cannot change during acquisition or drain.

### Settings record and metadata units

CONFIGURE contains one 20-byte settings record. Settings responses contain the
four-byte response prefix, settings at offset 4 and a 24-byte clock record at
24. All byte offsets below are relative to the settings record.

| Offset | Type | Field |
| --- | --- | --- |
| 0 | u8 | `stream_mask` |
| 1 | u8 | `source` |
| 2 | u8 | `checksum_algorithm` |
| 3 | u8 | `wire_version` |
| 4 | u8 | `cpu_profile` |
| 5 | u8 | `rate_profile` |
| 6 | u8 | `aux_bank_mode` |
| 7 | u8 | `gpio_width_bits` |
| 8 | u8 | `gpio_policy` |
| 9 | u8 | `adc_policy` |
| 10 | u8 | `adc_resolution_bits` |
| 11 | u8 | `reserved` |
| 12 | u32 | `adc_pair_rate_hz` |
| 16 | u32 | `gpio_sample_rate_hz` |

Stream mask ADC=1, GPIO=2, both=3; zero is invalid. Source HARDWARE=0,
SYNTHETIC=1. Auxiliary DISABLED=0/INPUT=1 implies width 8/16; GPIO policy
RAW=0/RLE_AUTO=1 and ADC policy RAW=0/PACK12=1 are distinct from per-frame
encoding IDs. Checksum=1, wire version=3, ADC resolution=12, reserved=0.
Rates count **ADC pairs/s** and **GPIO samples/s**. One ADC pair contains one
code from each converter, staggered by four ticks (500 ns), not simultaneous.

Clock records carry profile ID at offset 0, three reserved bytes, then u32
CPU/IPG/ADC/PIT/timestamp frequencies at offsets 4/8/12/16/20, all in **Hz**.
Rate records carry profile ID and reserved bytes at 0..3, u32 ADC/GPIO rates at
4/8, u16 ADC-pair/GPIO periods and ADC1 phase at 12/14/16, and reserved u16 at
18. Period/phase values use **8 MHz ticks** (125 ns), not CPU cycles.

INFO contains board/MCU u16 IDs at 4/6, simulated/version/resolution bytes at
8/9/10, reserved byte 11, NUL-terminated zero-padded ASCII serial/version/build
fields of 32/16/48 bytes at 12/44/60, then clocks at 108. Firmware version is
an identity string, independent of the wire version. Simulator identities are
explicit; do not treat their clocks as measured hardware performance.

GET_CAPABILITIES counts at 4/5/6 select leading CPU/rate/tuple entries; byte 7
is reserved. Seven u32 limits at 8..32 describe max data/control frame bytes,
logical/encoded sample bytes and ADC/GPIO8/GPIO16 item counts. Defaults are at
36, two clock slots at 56, one rate slot at 104, and 64 settings slots at 124.
Unused slots are zero. Defaults must belong to the advertised table. Never
construct a Cartesian product from independent profiles: match one complete
tuple, including disabled-stream settings. Canonical maxima are ceilings,
not required device capacities or qualification claims.

### Lifecycle and counter epochs

| State/event | Result |
| --- | --- |
| Boot/reboot | STOPPED (1), defaults applied, run ID 0, empty queues/counters/replay history |
| STOPPED + CONFIGURE | Atomically replace settings after complete drain; remain STOPPED |
| STOPPED + START | RUNNING (3); increment u32 run ID, skip zero, reset run counters/sequences/timestamps; respond before data |
| RUNNING + CONFIGURE or START | INVALID_STATE; preserve active run/settings |
| RUNNING + STOP | Stop production; DRAINING (4) if complete frames or a partial transport tail remain, otherwise STOPPED |
| DRAINING + CONFIGURE or START | BUSY; no mutation |
| DRAINING + final transmitted byte | Automatically STOPPED, pending_frames=0 |
| STOPPED/DRAINING + STOP | Idempotent; preserve settings and final counters |
| Any state + INFO/CAPABILITIES/SETTINGS/STATUS | Read-only snapshot |

STOP's response may still report DRAINING. Consume queued old-run data and an
ordered GET_STATUS reporting STOPPED/pending_frames=0 before restarting or
changing settings/wire mode. No queued frame is truncated. A reconnect preserves
device state/settings; reboot clears them. There is no v3 RESET_STATS command.

STATUS and STOP share state at offset 4, three reserved bytes, run ID at 8 and
pending_frames at 12. STATUS adds u64 ADC produced/dropped frames/items at
16/24/32/40 and GPIO at 48/56/64/72. Produced includes queued and dropped data;
dropped cannot exceed produced. Counters saturate at u64 and reset on successful
START/reboot; STOP retains them. Pending includes complete or partially sent
frames; STOPPED requires zero and DRAINING requires a positive count. Appended
diagnostics and their availability/units are specified below.

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

For hand-checkable byte vectors (spaces separate bytes):

| Encoding | Logical input | Sample bytes after the 12-byte prefix |
| --- | --- | --- |
| ADC RAW | `(0xABC, 0x123)` | `BC 0A 23 01` |
| ADC PACK12 | `(0xABC, 0x123)` | `BC 3A 12` |
| ADC PACK12 | `(0,0), (4095,4095)` | `00 00 00 FF FF FF` |
| GPIO8 RLE | six `0xAA`, then four `0x55` | `06 00 AA 04 00 55` |
| GPIO16 RLE | three `0x1234` | `03 00 34 12` |
| GPIO8 RAW fallback | three `0xAA` (RLE ties RAW at 3 bytes) | `AA AA AA` |

The GPIO8 RLE example has item_count=10, decoded_bytes=10, run_count=2;
its prefix is `01 01 00 00 0A 00 00 00 02 00 00 00`, payload length 18,
and total frame length 66. The single PACK12 pair has item_count=1,
decoded_bytes=4, run_count=0, prefix `02 04 00 00 04 00 00 00 00 00 00 00`,
payload length 15 and total length 63. PACK12 middle byte `3A` stores ADC1's
low nibble `3` above ADC0's high nibble `A`; unpack with
`a=b0|((b1&15)<<8)` and `b=(b1>>4)|(b2<<4)`.

Reject unknown encodings, wrong kind/policy/width combinations, zero items,
nonzero reserved prefix bytes, excess/truncated records, nonmaximal RLE,
zero-length runs, count/sum overflow and mismatched decoded length before
allocation/expansion. RAW payload length is `12 + item_count*item_bytes`,
PACK12 is `12 + 3*item_count`, RLE is `12 + run_count*(2+item_bytes)`.
Encoding is chosen from the **prefix**, never inferred from payload size.

Timestamps do not depend on encoding: first_sample_ticks is aligned to eight
ticks and must not wrap during a run. ADC0/GPIO advance eight ticks per item;
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
`daq_api/tests/test_simulator_v3.py` covers the canonical 60-tuple catalogue,
board-specific advertised subsets, encoded commands, atomic configuration, replay, chunking, corruption and transport drain.
`daq_api/tests/test_public_api_v3.py` covers the completed public-session path;
`daq_api/tests/test_examples.py` asserts the executable demo's results and cleanup.
See [[protocol-v3-upgrade]] for architecture and [[protocol-v3-prototype]] for
reproducible offline validation results.

## Low-level Python codecs

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

## Explicit simulated device

Construct `SimulatedV3Device` from `thingdone_daq.simulator_v3` and pass it to
`InMemoryTransport`. Send `V3Command.to_bytes()` through transport writes and
parse reads with `V3FrameParser`; partial writes/reads follow the same transport
contract as v1/v2. The public session below wires these through the shared
background reader and compatible parser.
The historical `SimulatedDevice` and default transport persona remain unchanged.

The v3 peer starts STOPPED with the advertised board defaults already applied.
INFO always sets `simulated=True`, uses a `SIM-` serial and identifies its build
as `thingdaq-simulator-v3`. HARDWARE source represents emulated board input;
SYNTHETIC source sets the wire flag. Both use deterministic samples. CPU speed
is fixed at 600 MHz; even an otherwise-valid 450 MHz RAW request receives
UNSUPPORTED_CONFIGURATION while stopped and preserves settings. No simulator
rate measures hardware throughput.

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
(the historical v1/v2 simulator). Production serial discovery/negotiation and
CLI support public v3; legacy capture paths retain their own layouts. The installed offline demo is
`python -m thingdone_daq.protocol_upgrade`. Facade return annotations now
include the v3 model variants; default v1/v2 sessions still return their original
models. Consumers accepting either session type should narrow the returned type.

- `info()` / `device_info`: `V3Info`, including simulated identity and clocks.
- `get_capabilities()` / `capabilities`: `V3Capabilities` with exact selectable tuples.
- `get_settings()`: `V3AppliedSettings` containing settings and applied clocks.
- `configure(V3Settings)` checks the advertised subset, verifies the exact echo,
  and performs GET_SETTINGS readback before accepting it. `configure()` starts
  from advertised defaults; existing stream/source/rate/auxiliary keyword options
  select a matching tuple. Do not combine a settings object with those options.
- `configuration` is the current `V3Settings`. Select both encoding policies RAW
  at 600 MHz, then call `configure()` while stopped to restore compressed
  defaults. Nonadvertised CPU selections fail host capability checks before
  CONFIGURE. Valid running changes receive a correlated INVALID_STATE error.
- `start()` may use board defaults without a preceding CONFIGURE; it checks
  settings readback and the START echo and returns a new nonzero run ID.
- `blocks()` / `read_block()` retain ordinary ADCBlock/GPIOBlock channel views,
  8 MHz timestamps, per-stream sequences and bounded queue-loss reports.
- `stop()` waits through DRAINING to `V3DeviceState.STOPPED` within the command
  deadline. It preserves settings. Context-manager exit stops and closes the
  shared reader/transport deterministically.

V3 `status()` returns the contract's `V3Status`, including available diagnostic
measurements. `validate_stream_health()` checks available v3 fault/drop counters
and shared host/parser/continuity evidence. `loss_counters()` maps run-relative
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


## Firmware layout and diagnostic status

[[protocol-v3-firmware-layouts]] records production v3 framing: 1008 ADC pairs,
4032 GPIO8 samples or 2016 GPIO16 samples per frame, with a 4092-byte RAW envelope
inside each existing 4096-byte packet page. PACK12 ADC frames contain 3084 wire
bytes. Device-specific limits can be smaller than the protocol maxima above.

GET_STATUS retains the original 80-byte state/logical-counter prefix and appends
37 little-endian u64 diagnostic fields and a u64 validity bitmap (384-byte payload
total). Offsets are generated from
`protocol/protocol-v3.json`:

| Payload offsets | Fields |
| --- | --- |
| 80–128 | ADC codec completed, RAW fallback, deadline drops, resource drops, work ticks, maximum work ticks, maximum age ticks |
| 136–184 | GPIO codec counters in the same order |
| 192–216 | ADC completed wire bytes, logical items/frame, maximum RAW wire bytes/frame, retention ticks |
| 224–248 | GPIO layout/transport fields in the same order |
| 256–280 | ADC logical/encoded bytes transmitted, then GPIO logical/encoded bytes transmitted |
| 288–312 | Parser errors, transport errors, packet READY high-water, packet transmit high-water |
| 320–368 | ADC DMA errors, ADC_ETC errors, GPIO hardware errors, ADC raw invariant errors, GPIO raw invariant errors, packet invalid operations, packet encoding rejections |
| 376 | Diagnostic validity bitmap; bit 0 corresponds to offset 80, bit 36 to offset 368 |

Codec times use the 8 MHz domain. Counts/maxima saturate at the firmware source's
u32 width and accumulated work at u64. RAW policies bypass codec work, so their
codec counters remain zero. Completed wire bytes include envelope, prefix and
checksum; an incomplete USB write does not count as a transmitted frame.
Logical bytes count decoded ADC pairs at four bytes each and GPIO samples at
one/two bytes each. Encoded bytes exclude header, data prefix and checksum;
wire bytes include all three. All three totals count only fully transmitted
frames, including during stalls and STOP drain. Codec completed counts include
RAW fallbacks; subtract RAW from completed for compressed completions. A RAW
policy bypasses the codec and contributes to neither count.

Validity bits distinguish unavailable measurements from measured zero and
saturation. An unset bit requires a zero wire value; the SDK exposes `None` and
the CLI exposes JSON `null` (human output `None`). Reserved validity bits must be
zero. The simulator and control-only harness do not claim runtime measurements.
Temperature, watchdog/reset details and complete DMA-stage conservation remain
unavailable through v3; these are not implied by the selected health counters.
GPIO hardware/invariant errors include both primary and auxiliary capture
owners. Health counters and queue high-water marks use the existing statistics
epoch, reset by successful START; strict SDK health checks reject available
nonzero faults, including codec deadline/resource drops.

Retention is a per-stream upper bound if every shared packet page holds that
stream, calculated from logical time coverage. Layout, codec and byte fields are
unavailable before the first v3 run and after a legacy run. Settings changes preserve the prior
run's diagnostics until START resets them. Legacy layouts and diagnostics do not
change. This pre-release v3 schema extension requires matching generated clients.
