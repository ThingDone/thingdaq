---
type: reference
title: Protocol V2
created: 2026-09-05
tags:
  - thingdaq
  - protocol
  - release
related:
  - '[[Protocol-V1]]'
  - '[[API-Reference]]'
  - '[[Hardware-Safety]]'
---

# Protocol v2 — firmware 1.1.0

Firmware and Python API **1.1.0 use wire protocol 2**, not 3. This is the first
stable v2 release. Firmware 1.0.0 used v1. Experimental v2 snapshots were not a
stable release; their 632-byte INFO payload is superseded by the 680-byte
payload below. Upgrade firmware and the Python package together.

The normative machine-readable source is
[`protocol/protocol-v2.json`](../../protocol/protocol-v2.json), including its
`release_policy`. Generated constants and golden frames are checked against
that source. [[Protocol-V1]] is frozen historical documentation: its common
envelope, checksums, counter units and unchanged payload fields are inherited,
but its version, acquisition rates, CONFIGURE/START/INFO/STATUS sizes and
600 MHz target assumptions do **not** describe this release.

## Fixed release policy

| Setting | Firmware 1.1.0 |
| --- | --- |
| Core / peripheral bus / ADC clock | 450 / 150 / 37.5 MHz |
| ADC0 A0/D14 and ADC1 A1/D15 | Each 1 MS/s, 12-bit raw codes in 16-bit containers |
| GPIO sampling | 1 MS/s, with ADC enabled or disabled |
| Timestamp frequency | 8 MHz, unsigned 64-bit START-relative ticks |
| ADC pair period / ADC1 phase / GPIO period | 8 / 4 / 8 ticks |
| Default bank mode | `DISABLED` (8 inputs D6–D13) |
| Optional bank mode | `INPUT` (16 inputs D6–D13 and D16–D23) |
| Supported profile mask / selected profile | `0x10` / ID `4` |
| Outputs | Unsupported; acquisition pins remain inputs |

The paired ADC stream contains two samples per pair. The channels are staggered
by a nominal 500 ns; they are not simultaneous ADC samples. Core speed is a
compile-time release setting, not a host command. There is no selectable
500 kHz, 2 MHz or 4 MHz acquisition mode in this release.

The five known profile IDs are retained without reassigning experimental IDs:

| ID | ADC pairs/s | GPIO samples/s | Release support |
| ---: | ---: | ---: | --- |
| 0 | 1,000,000 | 4,000,000 | Rejected |
| 1 | 500,000 | 2,000,000 | Rejected |
| 2 | 250,000 | 1,000,000 | Rejected |
| 3 | 125,000 | 500,000 | Rejected |
| 4 | 1,000,000 | 1,000,000 | Default and only supported rate pair |

An entry in the INFO timing table means that an ID is defined, not that it is
enabled. Always check `supported_rate_profile_mask`. Release firmware rejects
other rates before configuration changes. The GPIO clock diagnostic is also
restricted to 1 MHz. The research-only builder is not a release builder.

The legacy `GPIO_CAPTURE_DIAGNOSTIC` path (`0x19`) is disabled because it
uses a fixed 4 MHz schedule. Its capability bit `0x100` is clear in live INFO
(release capability mask `0x6FF`), and requests are rejected with
UNSUPPORTED_CONFIGURATION before any capture starts. Its successful-response
schema below remains defined for historical clients, not supported by this
release. Use normal 1 MHz acquisition for non-driving input checks.

Host processing capacity remains a separate constraint. The Python SDK's
combined 16-GPIO capture is not lossless under the test server's 0.5-core CPU
quota, although the independent wire validator sustains the same firmware
configuration. No wire-rate or capability bit promises a host throughput
budget. One SDK run also reported parser rejections without raw-ring loss;
their cause remains unconfirmed. Strict gap/overrun/parser checks are not
disabled to accommodate these failures.

## Envelope and commands

All multibyte integers are little-endian. The envelope remains 44 bytes plus a
4-byte checksum trailer; minimum frame size is 48 bytes. The magic is
`EF BE AD DE`. Header offsets remain: version 4 (`2`), kind 5, flags 6,
header length 8 (`44`), checksum ID 10, reserved 11 (`0`), total bytes 12,
payload bytes 16, run ID 20, per-stream sequence 24, request ID 28,
first-sample ticks 32, item count 40. Control sequence, timestamp and item count
are zero. Control request IDs are nonzero; data request IDs are zero.
Checksums cover header and payload, excluding the trailer. Control uses
Adler-32; data supports Adler-32 (default), CRC32C and CRC32/ISO-HDLC.

| Command | Request / response kind | Request / successful response payload bytes |
| --- | --- | --- |
| INFO | `0x10` / `0x90` | 0 / 680 |
| CONFIGURE | `0x11` / `0x91` | 16 / 20 |
| START | `0x12` / `0x92` | 0 / 20 |
| GET_STATUS | `0x13` / `0x93` | 0 / 1476 |
| STOP | `0x14` / `0x94` | 0 / 8 |
| RESET_STATS | `0x15` / `0x95` | 0 / 8 |
| PING | `0x16` / `0x96` | 8 / 12 |
| CHECKSUM_BENCHMARK | `0x17` / `0x97` | 8 / 96 |
| GPIO_CLOCK_DIAGNOSTIC | `0x18` / `0x98` | 8 / 140 |
| GPIO_CAPTURE_DIAGNOSTIC | `0x19` / `0x99` | 0 / 272 |
| GET_TEMPERATURE | `0x1A` / `0x9A` | 0 / 12 |

Successful response payloads begin with `u8 status=0`, `u8 reserved=0`,
`u16 error=0`. Typed errors contain only this 4-byte prefix, with ERROR status,
nonzero error code and the response-error header flag. Generic ERROR_RESPONSE
(`0x9F`) additionally identifies the rejected kind and version; its exact
8-byte schema is inherited from v1. Maximum command size is 64 bytes; maximum
control frame size is 1536 bytes. Unknown versions, reserved fields, illegal
combinations and malformed lengths fail closed.

CONFIGURE's `<BBBBIII>` payload contains stream mask (ADC=1, GPIO=2), source
(hardware=0, synthetic=1), data checksum ID, auxiliary mode (0 or 1), maximum
data frame bytes (`4096`), ADC pair rate (`1000000`), GPIO rate (`1000000`).
Auxiliary INPUT requires GPIO enabled. ADC-only uses DISABLED. CONFIGURE and
START successful replies echo the exact 16-byte applied configuration after
the response prefix. CONFIGURE does not start sampling.

INFO has a 440-byte prefix followed by **five 48-byte timing entries**. The
source schema gives every offset. Live trigger metadata reports 450 MHz DWT;
the ADC half-period reference is 225 DWT cycles at that core clock. Historical
600 MHz template/golden metadata in the JSON is a codec reference, not a live
release claim. Convert DWT measurements using the reported clock, not 600 MHz.
Legacy shared nominal-throughput fields cannot describe unequal stream byte
rates; derive active throughput from the rates and item sizes below. Likewise,
GPIO clock diagnostic `production_rate_hz` retains the historical 4 MHz
reference value; it is not permission to select 4 MHz. The release interlock
accepts only 1 MHz and the diagnostic echoes `configured_rate_hz=1000000`.

## Data frames, timestamps and loss

| GPIO mode | ADC pairs / total frame bytes | GPIO samples / item bytes / total frame bytes |
| --- | --- | --- |
| 8 inputs | 1012 / 4096 | 4048 / 1 / 4096 |
| 16 inputs | 506 / 2072 | 2024 / 2 / 4096 |

ADC kind is `0x01`; GPIO kind is `0x02`. ADC payload items are ordered
`u16 ADC0, u16 ADC1`. GPIO bits 0–7 map to D6–D13 in order, and bits 8–15 map
to D16–D23 in order; 16-bit GPIO words are little-endian.

At equal sample rates, **one GPIO frame spans four ADC frames**. Compare time
coverage, not frame counts or same-numbered ADC/GPIO sequences. Eight-input
ADC/GPIO frame durations are 1012/4048 microseconds; sixteen-input durations
are 506/2024 microseconds. Raw combined payload is 5 MB/s with 8 GPIO or
6 MB/s with 16 GPIO, excluding framing. Sample timestamps are calculated from
the stream's first tick and 8-tick period; ADC1 adds 4 ticks.

STATUS preserves the existing loss, generation, queue and STOP-tail fields and
adds the auxiliary-bank counters. `frame_coverage_ticks` denotes ADC-frame
coverage. Its packet-retention fields are conservative lower bounds: 100 ADC
frame durations combined and 200 single-stream. They are not exact maximum
retention for equal-rate GPIO frames. Lost items, discarded STOP tails,
frame-count skew and unequal-bank generation skew are distinct quantities.
STOP acknowledges IDLE; bounded draining can still return BUSY to an immediate
restart. A new START creates a new nonzero run ID and timestamp epoch.

## Temperature

GET_TEMPERATURE is valid while IDLE, CONFIGURED or RUNNING and does not start,
stop or reconfigure capture. Its 12-byte reply uses `<BBHBBHi>`: response prefix
(bytes 0–3), sensor status (4), zero reserved bytes (5–7), signed milli-Celsius
(8–11). Status 0 is VALID; 1 UNAVAILABLE; 2 NOT_READY; 3 INVALID_CALIBRATION;
4 OUT_OF_RANGE. A non-valid status carries zero on wire and maps to `None`,
**not 0°C**. Valid range is −40,000 through 150,000 milli-Celsius. The firmware
reads the calibrated die sensor; it does not force a conversion or measure
ambient/case temperature. Hosts may use bounded retries for transient status.

## Python migration

`ThingDAQ.open()` and discovery try INFO v1 and retry v2 on explicit
UNSUPPORTED_VERSION. All subsequent release commands use v2, including after
STOP. Default `daq.configure()` selects the live profile 4 and 8 GPIO inputs;
pass `aux_bank_mode=AuxBankMode.INPUT` for 16. Use `daq.get_temperature()` and
check `reading.status` or `reading.celsius is not None`.

The simulator deliberately retains historical defaults/profiles for regression
coverage and is not a wall-clock scheduling model. Explicitly select
`RateProfile.ADC_1MHZ_GPIO_1MHZ` to exercise release sample layouts offline.
The optional `TimestampAligner` currently requires equal-duration ADC/GPIO
frames and rejects profile 4 explicitly. Use `read_block()` / `blocks()` and
each block's sample timestamps for this release; do not pair by sequence.

Historical reports and ADRs retain the firmware, protocol, clocks and fixtures
actually tested. They are not release specifications. Unconnected-pin tests
validate acquisition/transport/control continuity, not external pin order,
analog accuracy, bandwidth or electrical timing. See [[Hardware-Safety]].
