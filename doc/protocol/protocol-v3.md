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
provides validated schemas, separate Python/C++ constants and golden frames;
it does not enable production firmware, serial negotiation, runtime codecs or
the simulator. The current product still uses [[protocol-v2]]. Physical results
in [[deferred-codecs-20261018]] concern private research versions, not v3.

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
legacy artifact digest recorded in [[protocol-v3-foundation]]. Runtime parser,
codec and simulator behavior will be exercised in subsequent Phase 01 tasks.
