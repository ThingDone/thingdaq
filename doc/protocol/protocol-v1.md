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
  - '[[ADR-001-Protocol-Wire-Contract]]'
---

# Protocol v1

This document is the normative human-readable Teensy DAQ v1 wire contract.
The authoritative machine-readable values live in
`protocol/protocol-v1.json`; generated Python and C++ files must never be
edited directly. The rationale is recorded in
[[ADR-001-Protocol-Wire-Contract]], and the component boundary is described in
[[System-Overview]].

Generate or verify all derived artifacts from the repository root:

```bash
python3 tools/generate_protocol.py
python3 tools/generate_protocol.py --check
```

## Scalar encoding and envelope

Every integer is unsigned and explicitly little endian. Firmware must write
fields bytewise or with little-endian helpers rather than transmitting a
native struct. The magic integer is `0xDEADBEEF`; its wire bytes are
`EF BE AD DE`.

| Offset | Bytes | Type | Field | Rule |
| ---: | ---: | --- | --- | --- |
| 0 | 4 | `u32` | magic | Exactly `0xDEADBEEF` |
| 4 | 1 | `u8` | version | Exactly `1` |
| 5 | 1 | `u8` | kind | A known frame-kind ID |
| 6 | 2 | `u16` | flags | Only bits allowed for that kind |
| 8 | 2 | `u16` | header length | Exactly `44` in v1 |
| 10 | 1 | `u8` | checksum algorithm | An enabled algorithm ID |
| 11 | 1 | `u8` | reserved | Zero |
| 12 | 4 | `u32` | total length | Header + payload + 4-byte trailer |
| 16 | 4 | `u32` | payload length | Exactly `total length - 48` |
| 20 | 4 | `u32` | run ID | Acquisition epoch identity; zero before the first run |
| 24 | 4 | `u32` | sequence | Per-stream data-frame sequence; zero for control |
| 28 | 4 | `u32` | request ID | Nonzero for control; zero for data |
| 32 | 8 | `u64` | first-sample ticks | 8 MHz time for data; zero for control |
| 40 | 4 | `u32` | item count | Logical data items; zero for control |
| 44 | variable | bytes | payload | Kind-specific layout |
| final 4 | 4 | `u32` | checksum | Algorithm result, little endian |

The minimum frame is therefore 48 bytes. The independent total and payload
length fields are intentionally redundant: a receiver accepts a frame only
when `total_length == 44 + payload_length + 4` and both lengths meet the rules
for its kind.

## Frame classes and bounds

| Class | Total bytes | Payload bytes | Header data fields |
| --- | ---: | ---: | --- |
| ADC data | exactly 4,096 | exactly 4,048 | run, sequence, time, and item count are meaningful |
| GPIO data | exactly 4,096 | exactly 4,048 | run, sequence, time, and item count are meaningful |
| Request | 48 through 1,024 | 0 through 976 | nonzero request ID; run/sequence/time/items are zero |
| Response | 52 through 1,024 | 4 through 976 | request ID is copied; sequence/time/items are zero |

In addition to the general bound, every initial control kind has the exact
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
| `0x13` | `STATUS_REQUEST` | Empty |
| `0x14` | `STOP_REQUEST` | Empty |
| `0x90` | `INFO_RESPONSE` | Typed identity and capabilities |
| `0x91` | `CONFIGURE_RESPONSE` | Typed applied configuration |
| `0x92` | `START_RESPONSE` | Typed applied configuration; new run ID in header |
| `0x93` | `STATUS_RESPONSE` | Typed state and counters |
| `0x94` | `STOP_RESPONSE` | Typed final state |
| `0x9F` | `ERROR_RESPONSE` | Error for a structurally valid but unknown kind |

Each request maps to the same low nibble in the `0x90` response range. A
device copies the request ID into its response, allowing control traffic to be
matched while ADC and GPIO frames are interspersed. Request ID zero is
reserved for non-control frames; clients increment IDs modulo (2^{32}) and
skip zero. A client must not reuse an ID while that request is outstanding.

## Flags

| Bit | Name | Meaning |
| ---: | --- | --- |
| `0x0001` | `SYNTHETIC` | Data came from the deterministic test source |
| `0x0002` | `GAP_BEFORE` | At least one item or complete frame was dropped before this frame |
| `0x0004` | `EPOCH_START` | First produced frame for this stream in a new run |
| `0x8000` | `RESPONSE_ERROR` | Response prefix contains a nonzero error |

Only the first three bits are valid on ADC/GPIO frames. Requests require zero
flags. Typed responses permit only `RESPONSE_ERROR`; successful responses use
zero. `ERROR_RESPONSE` requires `RESPONSE_ERROR`. All other bits are reserved
and must be rejected in v1.

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
4. resets per-run production/drop/error counters;
5. marks the first produced frame of each enabled stream with `EPOCH_START`.

Run IDs increment modulo (2^{32}), skip zero, and are not persisted across a
device reboot. A disconnect, reset, or newly observed INFO identity begins a
new host session; frames from different host sessions must not be joined using
run ID alone. STOP retains the most recently allocated run ID in its response
and status but returns the control state to IDLE.

ADC and GPIO have independent unsigned 32-bit frame sequences. A sequence is
assigned when a source frame is produced, before it can be dropped by the
transmit queue. The receiver computes the next value modulo (2^{32}), so
`0xFFFFFFFF -> 0` within one run is normal rather than a gap. A skip, duplicate,
or reversal that is not this wrap is reported. `GAP_BEFORE`, timestamps, and
cumulative counters provide independent corroboration.

First-sample time is an unsigned 64-bit count of 8 MHz ticks (125 ns) since the
current START epoch. Arithmetic is formally modulo (2^{64}), although wrap
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
zero. If the header time is (T), pair (n) has these nominal times:

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

If the header time is (T), byte (m) is sampled at (T + 2m) ticks. The
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

### INFO

INFO is idempotent and valid in IDLE, CONFIGURED, and RUNNING. Its request is
empty. Its 94-byte success payload reports:

- state and protocol version;
- supported stream and source masks;
- a checksum mask whose bit number equals the checksum algorithm ID;
- timestamp frequency and data/control frame limits;
- ADC/GPIO rates, periods, ADC phase, resolution, and container width;
- GPIO count and the eight-byte D6-through-D13 pin map;
- 32-bit hardware serial, three-byte firmware semantic version, board/MCU IDs;
- a 32-byte NUL-terminated, NUL-padded ASCII build ID (31 characters maximum).

Stream-mask bits are ADC = 1 and GPIO = 2. Source IDs are hardware = 0 and
synthetic = 1; the INFO supported-source mask uses `1 << source_id`. Board IDs
are simulator = 0 and Teensy 4.0 = 1. MCU IDs are simulated = 0 and
i.MX RT1062 = 1. Exact offsets live in the machine-readable payload schema.

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

### STATUS

STATUS is idempotent in every post-boot state and has an empty request. Its
52-byte success payload contains the common prefix followed by state, active
stream mask, source, data checksum, data-frame size, 64-bit emitted-frame
counters for ADC and GPIO, 64-bit dropped-item counters for ADC and GPIO, and
32-bit parser and transport error counters. The header carries the current or
most recent run ID.

### STOP

STOP is idempotent in IDLE, CONFIGURED, and RUNNING and has an empty request.
It disables acquisition if necessary, discards pending configuration, and
returns to IDLE. Its eight-byte success payload is the common prefix followed
by state `IDLE` and three reserved zero bytes. The response header retains the
stopped/most recent run ID (or zero if no run has started).

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
therefore normally reported through STATUS rather than sent in response to the
corrupt frame. Selecting an unsupported data algorithm inside an otherwise
valid Adler-32 CONFIGURE request can safely return error code 6.

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

`protocol/fixtures/` contains one complete Adler-32 frame for every initial
kind plus a deterministic `manifest.json` with decoded header values, payload
and frame SHA-256 hashes, checksums, and inline hex for small control frames.
The ADC vector is the little-endian pair ramp `(0, 1), (2, 3), ...`; the GPIO
vector is the byte ramp `0, 1, ... 255, 0, ...`.

The generated Python and C++ files and fixture manifest embed the SHA-256 of
`protocol/protocol-v1.json`. Tests independently unpack every header, verify
all length relationships, recompute Adler-32 and SHA-256, validate stream
ordering, and run generator check mode. Any mismatch is contract drift.
