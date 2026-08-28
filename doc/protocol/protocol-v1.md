---
type: reference
title: Protocol V1
created: 2026-08-27
tags:
  - teensy-daq
  - protocol
  - wire-format
  - usb-cdc
related:
  - '[[System-Overview]]'
  - '[[ADR-001-Wire-Protocol]]'
---

# Protocol v1

This document is the normative human-readable Teensy DAQ v1 wire contract.
The authoritative machine-readable values live in
`protocol/protocol-v1.json`; generated Python and C++ files must never be
edited directly. The rationale is recorded in
[[ADR-001-Wire-Protocol]], and the component boundary is described in
[[System-Overview]].

Generate or verify all derived artifacts from the repository root:

```bash
python3 tools/generate_protocol.py
python3 tools/generate_protocol.py --check
```

## Scalar encoding and envelope

Every integer is unsigned and explicitly little endian. `u8`, `u16`, `u32`,
and `u64` are respectively 1, 2, 4, and 8 bytes wide and are never signed.
Firmware must write fields bytewise or with little-endian helpers rather than
transmitting a native struct. The magic integer is `0xDEADBEEF`; its wire
bytes are `EF BE AD DE`.

| Offset | Width | Type | Signed | Field | Rule |
| ---: | ---: | --- | --- | --- | --- |
| 0 | 4 | `u32` | No | magic | Exactly `0xDEADBEEF` |
| 4 | 1 | `u8` | No | version | Exactly `1` |
| 5 | 1 | `u8` | No | kind | A known frame-kind ID |
| 6 | 2 | `u16` | No | flags | Only bits allowed for that kind |
| 8 | 2 | `u16` | No | header length | Exactly `44` in v1 |
| 10 | 1 | `u8` | No | checksum algorithm | An enabled algorithm ID |
| 11 | 1 | `u8` | No | reserved | Zero |
| 12 | 4 | `u32` | No | total length | Header + payload + 4-byte trailer |
| 16 | 4 | `u32` | No | payload length | Exactly `total length - 48` |
| 20 | 4 | `u32` | No | run ID | Acquisition epoch identity; zero before the first run |
| 24 | 4 | `u32` | No | sequence | Per-stream data-frame sequence; zero for control |
| 28 | 4 | `u32` | No | request ID | Nonzero for control; zero for data |
| 32 | 8 | `u64` | No | first-sample ticks | 8 MHz time for data; zero for control |
| 40 | 4 | `u32` | No | item count | Logical data items; zero for control |
| 44 | variable | bytes | N/A | payload | Kind-specific layout |
| final 4 | 4 | `u32` | No | checksum | Algorithm result, little endian |

The minimum frame is therefore 48 bytes. The independent total and payload
length fields are intentionally redundant: a receiver accepts a frame only
when `total_length == 44 + payload_length + 4` and both lengths meet the rules
for its kind.

## Frame classes and bounds

| Class | Total bytes | Payload bytes | Header data fields |
| --- | ---: | ---: | --- |
| ADC data | exactly 4,096 | exactly 4,048 | run, sequence, time, and item count are meaningful |
| GPIO data | exactly 4,096 | exactly 4,048 | run, sequence, time, and item count are meaningful |
| Request | 48 through 56 | 0 through 8 | nonzero request ID; run/sequence/time/items are zero |
| Response | 52 through 1,024 | 4 through 976 | request ID is copied; sequence/time/items are zero |

The largest data frame is 4,096 bytes, the largest v1 command is 56 bytes,
and the defensive bound for any control response is 1,024 bytes. In addition
to those class bounds, every control kind has the exact
payload shape given below. A v1 receiver rejects trailing fields, shortened
fields, nonzero reserved bytes, and unknown flag bits instead of partially
applying a request.

## Frame kinds

| ID | Name | Payload |
| ---: | --- | --- |
| `0x01` | `ADC_DATA` | 1,012 ADC sample pairs |
| `0x02` | `GPIO_DATA` | 4,048 packed GPIO samples |
| `0x10` | `INFO_REQUEST` | Empty |
| `0x11` | `CONFIGURE_REQUEST` | 8-byte requested configuration |
| `0x12` | `START_REQUEST` | Empty |
| `0x13` | `GET_STATUS_REQUEST` | Empty |
| `0x14` | `STOP_REQUEST` | Empty |
| `0x15` | `RESET_STATS_REQUEST` | Empty |
| `0x16` | `PING_REQUEST` | 8-byte nonce |
| `0x90` | `INFO_RESPONSE` | Typed identity and capabilities |
| `0x91` | `CONFIGURE_RESPONSE` | Typed applied configuration |
| `0x92` | `START_RESPONSE` | Typed applied configuration; new run ID in header |
| `0x93` | `GET_STATUS_RESPONSE` | Typed state and counters |
| `0x94` | `STOP_RESPONSE` | Typed final state |
| `0x95` | `RESET_STATS_RESPONSE` | New statistics generation |
| `0x96` | `PING_RESPONSE` | Echoed nonce |
| `0x9F` | `ERROR_RESPONSE` | Error for a structurally valid but unknown kind |

The numeric command kind is the request frame-kind byte: INFO is `0x10`,
CONFIGURE is `0x11`, START is `0x12`, GET_STATUS is `0x13`, STOP is `0x14`,
RESET_STATS is `0x15`, and PING is `0x16`. A successful or typed-error response
kind is the command kind ORed with `0x80`; generated mappings enforce this
relationship. A device copies the request ID into its response, allowing
control traffic to be matched while ADC and GPIO frames are interspersed.
Request ID zero is
reserved for non-control frames; clients increment IDs modulo \(2^{32}\) and
skip zero. A client must not reuse an ID while that request is outstanding.

## Flags

| Bit | Name | Meaning |
| ---: | --- | --- |
| `0x0001` | `SYNTHETIC` | Data came from the deterministic test source |
| `0x0002` | `GAP_BEFORE` | At least one item or complete frame was dropped before this frame |
| `0x0004` | `EPOCH_START` | First produced frame for this stream in a new run |
| `0x0008` | `OVERRUN_BEFORE` | Firmware-side acquisition, queue, or transport overrun caused the gap |
| `0x8000` | `RESPONSE_ERROR` | Response prefix contains a nonzero error |

Only the first four low bits are valid on ADC/GPIO frames, and
`OVERRUN_BEFORE` requires `GAP_BEFORE`. A host-observed sequence or timestamp
gap without `OVERRUN_BEFORE` is still a gap; it must not be relabeled as a
firmware overrun. Requests require zero flags. Typed responses permit only
`RESPONSE_ERROR`; successful responses use zero. `ERROR_RESPONSE` requires
`RESPONSE_ERROR`. All other bits are reserved and must be rejected in v1.

## Checksum trailer

The `checksum_algorithm` byte selects the interpretation of the fixed 32-bit
trailer:

| ID | Name | v1 state |
| ---: | --- | --- |
| 0 | `NONE_RESERVED` | Invalid; unchecksummed frames are never accepted |
| 1 | `ADLER32` | Enabled and the bootstrap/default algorithm |
| 2 | `CRC32C` | ID reserved; not accepted or advertised as supported yet |

Adler-32 is the RFC 1950 algorithm with initial value 1 and modulus 65,521.
It covers every byte from the first magic byte through the final payload byte,
including the checksum-algorithm field itself. The four trailer bytes are not
included or treated as zeros. The unsigned 32-bit result is serialized little
endian. Standard checks include Adler-32 of an empty byte string =
`0x00000001` and of ASCII `123456789` = `0x091E01DE`.

The checksum detects accidental corruption and framing mistakes; it provides
no authenticity or security. CRC-32C ID 2 is allocated so benchmarking can
enable it later through INFO capabilities and CONFIGURE without changing the
header. Until that happens, a receiver treats ID 2 as unsupported. Checked-in
Adler-32 examples are listed in `protocol/fixtures/manifest.json`.

## Run epoch, timestamps, and sequence

The device enters IDLE after bounded boot. Before a successful START, run ID is
zero. Each successful START:

1. allocates the next nonzero 32-bit run ID;
2. resets both stream sequences to zero;
3. resets the acquisition timestamp epoch to tick zero;
4. resets production/drop/error counters and advances the nonzero statistics
   generation;
5. marks the first produced frame of each enabled stream with `EPOCH_START`.

Run IDs increment modulo \(2^{32}\), skip zero, and are not persisted across a
device reboot. A disconnect, reset, or newly observed INFO identity begins a
new host session; frames from different host sessions must not be joined using
run ID alone. STOP retains the most recently allocated run ID in its response
and status but returns the control state to IDLE.

The host records the run ID from the successful START response before exposing
data. It rejects or visibly discards every ADC/GPIO frame whose run ID differs
from that active value, including buffered frames left by a prior START. A new
START is an epoch boundary: sequence zero from an older run is never accepted
as sequence zero of the new run. The current Python facade enforces this rule
when queuing active-run blocks; the background reader must preserve it.

ADC and GPIO have independent unsigned 32-bit frame sequences. A sequence is
assigned when a source frame is produced, before it can be dropped by the
transmit queue. The receiver computes the next value modulo \(2^{32}\), so
`0xFFFFFFFF -> 0` within one run is normal rather than a gap. A skip, duplicate,
or reversal that is not this wrap is reported. `GAP_BEFORE`, timestamps, and
counters within the current statistics generation provide independent
corroboration.

First-sample time is an unsigned 64-bit count of 8 MHz ticks (125 ns) since the
current START epoch. Arithmetic is formally modulo \(2^{64}\), although wrap
is outside any practical run. Timestamps come from acquisition sample
counters, never from DMA-interrupt or USB-write time.

## ADC data payload

An ADC data frame contains exactly 1,012 pairs and has `item_count = 1012`.
Each four-byte pair is:

| Byte within pair | Type | Value |
| ---: | --- | --- |
| 0 | `u16` little endian | ADC0 / A0 raw code |
| 2 | `u16` little endian | ADC1 / A1 raw code |

ADC values are 12-bit raw codes in 16-bit containers; unused high bits are
zero. If the header time is \(T\), pair \(n\) has these nominal times:

$$
t_{ADC0,n} = T + 8n, \qquad t_{ADC1,n} = T + 8n + 4
$$

Thus each pair covers eight ticks and the frame covers 8,096 ticks, or
1,012 µs. Converter identity is never discarded. Interleaving is an explicit
host operation and does not imply greater analog input bandwidth.

## GPIO data payload

A GPIO data frame contains exactly 4,048 bytes and has `item_count = 4048`.
Each byte samples all pins at one instant, with a user-facing bit order:

| Bit | Teensy pin |
| ---: | --- |
| 0 | D6 |
| 1 | D7 |
| 2 | D8 |
| 3 | D9 |
| 4 | D10 |
| 5 | D11 |
| 6 | D12 |
| 7 | D13 |

If the header time is \(T\), byte \(m\) is sampled at \(T + 2m\) ticks. The
4,048 samples therefore cover the same 8,096 ticks / 1,012 µs as one ADC
frame.

## Control payload conventions

All successful response payloads start with this four-byte prefix:

| Offset | Type | Field | Success rule |
| ---: | --- | --- | --- |
| 0 | `u8` | response status | `OK` (0) |
| 1 | `u8` | reserved | Zero |
| 2 | `u16` | error code | `OK` (0) |

An unsuccessful typed response consists of only this four-byte prefix, has
status `ERROR` (1), a nonzero error code, and the `RESPONSE_ERROR` flag. The
header keeps the typed response kind and copied request ID. The generic
8-byte `ERROR_RESPONSE` extends the prefix with rejected kind, rejected
version, and two reserved zero bytes.

| Command | BOOT | IDLE | CONFIGURED | RUNNING |
| --- | --- | --- | --- | --- |
| INFO | No response | Valid | Valid | Valid |
| CONFIGURE | No response | Valid | Valid | `INVALID_STATE` |
| START | No response | `INVALID_STATE` | Valid | `INVALID_STATE` |
| GET_STATUS | No response | Valid | Valid | Valid |
| STOP | No response | Valid | Valid | Valid |
| RESET_STATS | No response | Valid | Valid | `INVALID_STATE` |
| PING | No response | Valid if advertised | Valid if advertised | Valid if advertised |

### INFO

INFO is idempotent and valid in IDLE, CONFIGURED, and RUNNING. Its request is
empty. Its 98-byte success payload reports:

- state and protocol version;
- supported stream and source masks;
- a checksum mask whose bit number equals the checksum algorithm ID and a
  separate capability-bit mask;
- timestamp frequency and data/control frame limits;
- ADC/GPIO rates, periods, ADC phase, resolution, and container width;
- GPIO count and the eight-byte D6-through-D13 pin map;
- 32-bit hardware serial, three-byte firmware semantic version, board/MCU IDs;
- a 32-byte NUL-terminated, NUL-padded ASCII build ID (31 characters maximum).

| Offset | Width/type | Field |
| ---: | --- | --- |
| 0 | 4 / response prefix | status, reserved zero, error code |
| 4 | 1 / `u8` | device state |
| 5 | 1 / `u8` | protocol version |
| 6 | 1 / `u8` | supported stream mask |
| 7 | 1 / `u8` | supported source mask |
| 8 | 4 / `u32` | supported checksum mask |
| 12 | 4 / `u32` | capability bits |
| 16 | 4 / `u32` | timestamp frequency in Hz |
| 20 | 4 / `u32` | fixed data-frame bytes |
| 24 | 4 / `u32` | maximum control-frame bytes |
| 28 | 4 / `u32` | ADC pair rate in Hz |
| 32 | 4 / `u32` | GPIO sample rate in Hz |
| 36 | 2 / `u16` | ADC pair period in ticks |
| 38 | 2 / `u16` | ADC1 phase in ticks |
| 40 | 2 / `u16` | GPIO sample period in ticks |
| 42 | 1 / `u8` | ADC resolution bits |
| 43 | 1 / `u8` | ADC container bytes |
| 44 | 1 / `u8` | GPIO pin count |
| 45 | 1 / `u8` | reserved, zero |
| 46 | 8 / `u8[8]` | GPIO pin map in bit order |
| 54 | 4 / `u32` | hardware serial |
| 58 | 3 / `u8[3]` | firmware major, minor, patch |
| 61 | 1 / `u8` | reserved, zero |
| 62 | 2 / `u16` | board ID |
| 64 | 2 / `u16` | MCU ID |
| 66 | 32 / ASCII | NUL-terminated and NUL-padded build ID |

Stream-mask bits are ADC = 1 and GPIO = 2. Source IDs are hardware = 0 and
synthetic = 1; the INFO supported-source mask uses `1 << source_id`. Board IDs
are simulator = 0 and Teensy 4.0 = 1. MCU IDs are simulated = 0 and
i.MX RT1062 = 1. Exact offsets live in the machine-readable payload schema.

Capability bits are independent, one-bit values:

| Bit value | Name | Meaning |
| ---: | --- | --- |
| `0x00000001` | `ADC_STREAM` | ADC data is supported |
| `0x00000002` | `GPIO_STREAM` | GPIO data is supported |
| `0x00000004` | `HARDWARE_SOURCE` | Source mode 0 is supported |
| `0x00000008` | `SYNTHETIC_SOURCE` | Source mode 1 is supported |
| `0x00000010` | `RESET_STATS` | RESET_STATS is implemented |
| `0x00000020` | `PING` | Optional PING is implemented |

The first four capability bits must agree with the stream/source masks. Bits
outside `0x0000003F` are reserved and rejected in protocol v1. PING callers
must check its capability bit; all other commands in the initial set are
mandatory. Device states are BOOT = 0, IDLE = 1, CONFIGURED = 2, and RUNNING =
3. BOOT does not answer commands.

### CONFIGURE

CONFIGURE is valid in IDLE or CONFIGURED and never starts acquisition. Its
eight-byte request is:

| Offset | Type | Field | v1 constraint |
| ---: | --- | --- | --- |
| 0 | `u8` | stream mask | Nonempty subset of ADC/GPIO |
| 1 | `u8` | source | Hardware (0) or synthetic (1) |
| 2 | `u8` | data checksum | An advertised enabled algorithm; initially 1 |
| 3 | `u8` | reserved | Zero |
| 4 | `u32` | data frame bytes | Exactly 4,096 |

Success moves the device to CONFIGURED and returns the common prefix followed
by the exact eight-byte applied configuration. Unsupported values are rejected
atomically; no partial configuration is applied.

### START

START is valid only in CONFIGURED and has an empty request. Success allocates a
new run, applies the epoch/reset rules above, moves to RUNNING, places the new
run ID in the response header, and returns the same 12-byte success layout as
CONFIGURE. A repeated START while RUNNING returns `INVALID_STATE` and does not
create another run.

### GET_STATUS

GET_STATUS is idempotent in every post-boot state and has an empty request. Its
56-byte success payload contains the common prefix followed by state, active
stream mask, source, data checksum, data-frame size, 64-bit emitted-frame
counters for ADC and GPIO, 64-bit dropped-item counters for ADC and GPIO, and
32-bit parser and transport error counters, followed by a nonzero 32-bit
statistics generation. The header carries the current or most recent run ID.

| Offset | Width/type | Field |
| ---: | --- | --- |
| 0 | 4 / response prefix | status, reserved zero, error code |
| 4 | 1 / `u8` | device state |
| 5 | 1 / `u8` | active stream mask; zero exactly in IDLE |
| 6 | 1 / `u8` | source mode |
| 7 | 1 / `u8` | data checksum algorithm |
| 8 | 4 / `u32` | data-frame bytes, exactly 4,096 |
| 12 | 8 / `u64` | ADC frames emitted |
| 20 | 8 / `u64` | GPIO frames emitted |
| 28 | 8 / `u64` | ADC pairs dropped |
| 36 | 8 / `u64` | GPIO sample instants dropped |
| 44 | 4 / `u32` | parser errors |
| 48 | 4 / `u32` | transport errors |
| 52 | 4 / `u32` | nonzero statistics generation |

| Counter | Wire type | Unit |
| --- | --- | --- |
| `adc_frames_emitted` | `u64` | Complete ADC frames admitted to the USB transmit path |
| `gpio_frames_emitted` | `u64` | Complete GPIO frames admitted to the USB transmit path |
| `adc_items_dropped` | `u64` | ADC sample pairs not emitted |
| `gpio_items_dropped` | `u64` | Packed eight-pin GPIO sample instants not emitted |
| `parser_errors` | `u32` | Rejected inbound frame candidates |
| `transport_errors` | `u32` | Bounded USB read/write failure events |

These are firmware counters only. They saturate at their type maximum and
reset on successful START or RESET_STATS. Host parser corruption, decoded-
queue drops, and late responses live in separate host models and must never be
added to or described as these firmware counters.

### STOP

STOP is idempotent in IDLE, CONFIGURED, and RUNNING and has an empty request.
It disables acquisition if necessary, discards pending configuration, and
returns to IDLE. Its eight-byte success payload is the common prefix followed
by state `IDLE` and three reserved zero bytes. The response header retains the
stopped/most recent run ID (or zero if no run has started).

### RESET_STATS

RESET_STATS has an empty request and is valid only in IDLE or CONFIGURED, so a
counter reset cannot race with in-flight acquisition data. Success zeros every
reported firmware counter, advances the nonzero `stats_generation` modulo
\(2^{32}\) while skipping zero, and returns the new generation after the common
prefix in an eight-byte payload. It does not change configuration, run ID,
sequence values, or timestamp state. A request while RUNNING returns
`INVALID_STATE` without changing counters.

### PING

PING is optional and valid in every post-boot state when the `PING` capability
is set. Its request is one arbitrary little-endian `u64` nonce. Its 12-byte
success response is the common prefix followed by the exact nonce. PING changes
no state or counters. INFO remains the preferred discovery probe because it
also proves identity and compatibility.

## Error codes

| Value | Name | Meaning |
| ---: | --- | --- |
| 0 | `OK` | Successful response only |
| 1 | `UNSUPPORTED_VERSION` | Version cannot be processed |
| 2 | `UNKNOWN_FRAME_KIND` | Structurally valid envelope has unknown kind |
| 3 | `INVALID_FLAGS` | Unknown or kind-inappropriate flag bits |
| 4 | `INVALID_LENGTH` | Length relation, bound, or fixed size is wrong |
| 5 | `INVALID_PAYLOAD` | Typed fields or reserved bytes are invalid |
| 6 | `UNSUPPORTED_CHECKSUM` | Requested data checksum is not enabled |
| 7 | `INVALID_STATE` | Command is not valid in the current state |
| 8 | `UNSUPPORTED_CONFIGURATION` | Requested stream/source/frame combination is unavailable |
| 9 | `INVALID_REQUEST_ID` | Request ID is zero or conflicts with an outstanding request |
| 10 | `BUSY` | Bounded request capacity is temporarily exhausted |
| 11 | `INTERNAL_ERROR` | Device could not complete a valid command |
| 12 | `CHECKSUM_MISMATCH` | Local parser/counter classification for a bad trailer |

An envelope whose checksum cannot be verified is silently discarded and
counted because none of its request fields can be trusted. Error code 12 is
therefore normally reported through GET_STATUS rather than sent in response
to the corrupt frame. Selecting an unsupported data algorithm inside an
otherwise valid Adler-32 CONFIGURE request can safely return error code 6.

Unknown version, frame-kind/command-kind, checksum ID, reserved flag, or
impossible-length candidates are rejected before their declared bodies are
trusted; the device makes no control-state or configuration change. Because a
bad or unsupported envelope may not establish an authentic request ID, a
receiver may discard it without a response and expose the classification in
GET_STATUS. Unknown typed payload values inside a complete checksummed known
command receive that command's typed error response. No v1 receiver attempts
to interpret a newer-version payload or silently ignores a trailing field.

## Structural validation and resynchronization

USB CDC supplies arbitrary chunks. A read may contain a partial frame, one
frame, or many frames; a 4,096-byte application frame is not one USB transfer.
A receiver follows this bounded process:

1. Scan for the four magic bytes `EF BE AD DE`, retaining at most the final
   three bytes that could be a magic prefix when discarding garbage.
2. Wait for the complete 44-byte header.
3. Validate magic, version, header length, header reserved byte, known kind,
   allowed flags, enabled checksum ID, the total/payload length equation, and
   the applicable class bound.
4. Validate fixed data lengths/item counts or the exact control payload size.
   Never wait for a declared body whose header is already implausible.
5. Wait for the declared complete frame only after those checks pass.
6. Verify the trailer over header plus payload.
7. Validate kind-specific header semantics and typed payload/reserved fields.
8. Emit the frame. On any failure, advance one byte past the candidate magic
   start and scan again rather than trusting the corrupt declared length.

Magic may occur naturally in a payload. Header plausibility plus checksum is
what establishes framing. An incremental implementation must cap retained
storage to the largest accepted frame plus the three-byte partial-magic suffix
and discard leading garbage as it scans.

## Golden fixtures and drift

`protocol/fixtures/` contains one complete Adler-32 frame for all 17 v1 frame
kinds (two data, seven requests, seven typed responses, and one generic error)
plus a deterministic `manifest.json` with decoded header values, payload
and frame SHA-256 hashes, checksums, and inline hex for small control frames.
The ADC vector is the little-endian pair ramp `(0, 1), (2, 3), ...`; the GPIO
vector is the byte ramp `0, 1, ... 255, 0, ...`.

The generated Python and C++ files and fixture manifest embed the SHA-256 of
`protocol/protocol-v1.json`. Tests independently unpack every header, verify
all length relationships, recompute Adler-32 and SHA-256, validate stream
ordering, and run generator check mode. Any mismatch is contract drift.
