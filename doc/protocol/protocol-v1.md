---
type: reference
title: Protocol V1
created: 2026-08-27
updated: 2026-08-28
tags:
  - teensy-daq
  - protocol
  - wire-format
  - usb-cdc
related:
  - '[[System-Overview]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
---

# Protocol v1

This document is the normative human-readable Teensy DAQ v1 wire contract.
The authoritative machine-readable values live in
`protocol/protocol-v1.json`; generated Python and C++ files must never be
edited directly. The framing rationale is recorded in
[[ADR-001-Wire-Protocol]], the production checksum decision in
[[ADR-002-Checksum-Selection]], and the component boundary in
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
| `0x17` | `CHECKSUM_BENCHMARK_REQUEST` | 8-byte bounded benchmark selection |
| `0x18` | `GPIO_CLOCK_DIAGNOSTIC_REQUEST` | 8-byte exact-rate diagnostic selection |
| `0x90` | `INFO_RESPONSE` | Typed identity and capabilities |
| `0x91` | `CONFIGURE_RESPONSE` | Typed applied configuration |
| `0x92` | `START_RESPONSE` | Typed applied configuration; new run ID in header |
| `0x93` | `GET_STATUS_RESPONSE` | Typed state and counters |
| `0x94` | `STOP_RESPONSE` | Typed final state |
| `0x95` | `RESET_STATS_RESPONSE` | New statistics generation |
| `0x96` | `PING_RESPONSE` | Echoed nonce |
| `0x97` | `CHECKSUM_BENCHMARK_RESPONSE` | 96-byte cycle/resource result |
| `0x98` | `GPIO_CLOCK_DIAGNOSTIC_RESPONSE` | 140-byte register/count snapshot |
| `0x9F` | `ERROR_RESPONSE` | Error for a structurally valid but unknown kind |

The numeric command kind is the request frame-kind byte: INFO is `0x10`,
CONFIGURE is `0x11`, START is `0x12`, GET_STATUS is `0x13`, STOP is `0x14`,
RESET_STATS is `0x15`, PING is `0x16`, CHECKSUM_BENCHMARK is `0x17`, and
GPIO_CLOCK_DIAGNOSTIC is `0x18`. A successful or typed-error response kind is
the command kind ORed with `0x80`;
generated mappings enforce this relationship. A device copies the request ID
into its response, allowing
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
| 1 | `ADLER32` | Enabled; fixed bootstrap and production data default selected by [[ADR-002-Checksum-Selection]] |
| 2 | `CRC32C` | Enabled for negotiated data frames |
| 3 | `CRC32_ISO_HDLC` | Enabled for negotiated data frames |

Adler-32 is the RFC 1950 algorithm with initial value 1 and modulus 65,521.
It covers every byte from the first magic byte through the final payload byte,
including the checksum-algorithm field itself. The four trailer bytes are not
included or treated as zeros. The unsigned 32-bit result is serialized little
endian. Standard checks include Adler-32 of an empty byte string =
`0x00000001` and of ASCII `123456789` = `0x091E01DE`.

The checksum detects accidental corruption and framing mistakes; it provides
no authenticity or security. All request and response frames use bootstrap
Adler-32, including INFO and CONFIGURE traffic before a data algorithm has
been selected. INFO advertises checksum-mask bits 1, 2, and 3; CONFIGURE and
STATUS carry the selected data algorithm, and each ADC/GPIO header repeats it.
A receiver rejects an unknown ID, a disabled ID, or a control frame labeled
with a non-bootstrap ID before waiting for its body. CRC-32C uses reflected
polynomial `0x82F63B78`; CRC-32/ISO-HDLC uses reflected polynomial
`0xEDB88320`; both initialize and finally XOR with `0xFFFFFFFF`. Their standard
ASCII `123456789` results are respectively `0xE3069283` and `0xCBF43926`.
Checked-in bootstrap-Adler examples are listed in
`protocol/fixtures/manifest.json`.

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

Firmware may continue draining complete frames from a stopped run before a new
epoch is armed. CONFIGURE received during that bounded drain returns `BUSY`
and makes no state or algorithm change; START remains invalid until a
post-drain CONFIGURE succeeds. After configuration, START can also return
`BUSY` if runtime resources are not ready, without allocating a run ID or
resetting statistics. A successful START response is emitted only after the
prior drain is quiescent and the new packet/source epoch has been armed; no
old-run data may follow it.

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
| CHECKSUM_BENCHMARK | No response | Valid if advertised | `INVALID_STATE` | `INVALID_STATE` |
| GPIO_CLOCK_DIAGNOSTIC | No response | Valid if advertised | `INVALID_STATE` | `INVALID_STATE` |

### INFO

INFO is idempotent and valid in IDLE, CONFIGURED, and RUNNING. Its request is
empty. Its 98-byte success payload reports:

- state and protocol version;
- supported stream and source masks;
- a checksum mask whose bit number equals the checksum algorithm ID and a
  separate capability-bit mask, plus the currently selected data checksum;
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
| 45 | 1 / `u8` | selected data checksum algorithm |
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
The selected checksum is the generated production default in IDLE and the
applied configuration in CONFIGURED or RUNNING. It must be present in the
supported checksum mask. STATUS and each ADC/GPIO frame repeat the same
selection so a host never infers a polynomial from context.

The fixed Phase 05 qualification policy selected standard Adler-32 as the
production data default. CRC-32C and CRC-32/ISO-HDLC remain enabled in the
supported mask for explicit negotiation, validation of retained evidence, and
compatibility with captured frames. Selection did not change the fixed frame
boundary, trailer width, bootstrap rule, or per-frame algorithm identifier.

Capability bits are independent, one-bit values:

| Bit value | Name | Meaning |
| ---: | --- | --- |
| `0x00000001` | `ADC_STREAM` | ADC data is supported |
| `0x00000002` | `GPIO_STREAM` | GPIO data is supported |
| `0x00000004` | `HARDWARE_SOURCE` | Source mode 0 is supported |
| `0x00000008` | `SYNTHETIC_SOURCE` | Source mode 1 is supported |
| `0x00000010` | `RESET_STATS` | RESET_STATS is implemented |
| `0x00000020` | `PING` | Optional PING is implemented |
| `0x00000040` | `CHECKSUM_BENCHMARK` | Optional on-device checksum benchmark is implemented |
| `0x00000080` | `GPIO_CLOCK_DIAGNOSTIC` | Optional exact-rate PIT/XBARA/eDMA diagnostic is implemented |

The first four capability bits must agree with the stream/source masks. Bits
outside `0x000000FF` are reserved and rejected in protocol v1. PING,
CHECKSUM_BENCHMARK, and GPIO_CLOCK_DIAGNOSTIC callers must check their
capability bits; all other commands in the initial set are mandatory. Device
states are BOOT = 0, IDLE = 1,
CONFIGURED = 2, and RUNNING = 3. BOOT does not answer commands.

### CONFIGURE

CONFIGURE is valid in IDLE or CONFIGURED and never starts acquisition. Its
eight-byte request is:

| Offset | Type | Field | v1 constraint |
| ---: | --- | --- | --- |
| 0 | `u8` | stream mask | Subset of ADC/GPIO; zero only for the control-only profile below |
| 1 | `u8` | source | Hardware (0) or synthetic (1) |
| 2 | `u8` | data checksum | An advertised enabled algorithm ID (1, 2, or 3) |
| 3 | `u8` | reserved | Zero |
| 4 | `u32` | data frame bytes | Exactly 4,096 |

Success moves the device to CONFIGURED and returns the common prefix followed
by the exact eight-byte applied configuration. Unsupported values are rejected
atomically; no partial configuration is applied. If prior-run frames are still
queued, CONFIGURE returns `BUSY` and preserves the prior configuration.

Phase 03 physical firmware defines one deliberately narrow control-only
profile: stream mask zero, hardware source, Adler-32, and `data_frame_bytes =
4096`. It is available only when INFO reports a zero supported-stream mask.
The checksum and frame-size fields remain populated and are echoed so the
control schema does not change when acquisition arrives. CONFIGURE and START
succeed for this profile, RUNNING emits no ADC/GPIO frames, GET_STATUS reports
RUNNING with stream mask zero, and STOP returns to IDLE. A zero stream mask on
a device that advertises acquisition streams is not an implicit request to
disable data; it must be rejected unless that firmware explicitly documents
support for the control-only profile.

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
| 5 | 1 / `u8` | active stream mask; zero in IDLE and in the Phase 03 control-only profile |
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

Disabling acquisition prevents new frame production immediately. Incomplete
producer-owned work is canceled; already complete ready or transport-owned
frames drain without interleaving or abandoning a partial frame. A caller may
CONFIGURE while this finite drain completes, but START is subject to the BUSY
rule above. STOP_RESPONSE retains normal response priority at the next frame
boundary, so drained old-run data may follow STOP_RESPONSE; it must precede any
later successful START_RESPONSE on the CDC byte stream.

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

### CHECKSUM_BENCHMARK

CHECKSUM_BENCHMARK is an optional, bounded, on-device measurement command. It
is valid only in IDLE and never allocates a run ID, changes configuration,
starts a source, emits data, advances the statistics generation, or changes
acquisition counters. Command-path diagnostics may account for the accepted
request normally. CONFIGURED and RUNNING requests return `INVALID_STATE`; an
implementation that does not advertise capability bit `0x00000040` returns
`UNSUPPORTED_CONFIGURATION`.

The eight-byte request is:

| Offset | Type | Field | Constraint |
| ---: | --- | --- | --- |
| 0 | `u8` | checksum algorithm | Enabled ID 1, 2, or 3 |
| 1 | `u8` | vector | One ID from the vector table below |
| 2 | `u8` | memory region | DTCM packet storage (0) or OCRAM DMA storage (1) |
| 3 | `u8` | cache state | Hot/native (0) or cold-invalidated (1) |
| 4 | `u16` | batch count | 1 through 8 |
| 6 | `u16` | iterations per batch | 1 through 4,096 |

| Vector ID | Name | Checksum input bytes | Meaning |
| ---: | --- | ---: | --- |
| 0 | `EMPTY` | 0 | Canonical empty input |
| 1 | `CANONICAL_123456789` | 9 | ASCII `123456789` |
| 2 | `BUFFER_64` | 64 | Aligned deterministic representative buffer |
| 3 | `BUFFER_512` | 512 | Aligned deterministic representative buffer |
| 4 | `FRAME_COVERAGE` | 4,092 | Actual production-encoded GPIO header plus payload, excluding its four-byte trailer |

The operation count is `batch_count * iterations_per_batch`, at most 32,768.
Processed input is additionally capped at 8,388,608 bytes, so not every pair
of individually legal repetition counts is legal for every vector. Cold cache
is meaningful only for a nonempty OCRAM buffer and is rejected for DTCM or the
empty vector. Both backing allocations are 32-byte aligned, isolated 4,096-byte
buffers. DTCM represents the packetizer's cacheless CPU storage. OCRAM is in
the target's DMA-visible `.dmabuffers` region; hot mode reads it through cache,
while cold mode flushes initial contents and invalidates the complete aligned
coverage before every measured checksum.

The 96-byte successful result is:

| Offset | Width/type | Field |
| ---: | --- | --- |
| 0 | 4 / response prefix | status, reserved zero, error code |
| 4 | 4 / four `u8` | algorithm, vector, memory region, cache state |
| 8 | 2 / `u16` | batch count |
| 10 | 2 / `u16` | iterations per batch |
| 12 | 4 / `u32` | checksum input bytes per operation |
| 16 | 4 / `u32` | verified cycle-counter frequency, exactly 600,000,000 Hz |
| 20 | 4 / `u32` | calibrated timer/read overhead cycles per checksum interval |
| 24 | 4 / `u32` | selected checksum-body code bytes in the pinned build |
| 28 | 4 / `u32` | selected lookup-table Flash bytes |
| 32 | 4 / `u32` | benchmark working RAM bytes, exactly 8,192 |
| 36 | 4 / `u32` | deterministic digest mixed from every measured checksum result |
| 40 | 8 / `u64` | processed input bytes across all measured operations |
| 48 | 8 / `u64` | raw checksum interval cycles |
| 56 | 8 / `u64` | net checksum cycles after per-operation timer subtraction |
| 64 | 8 / `u64` | recurring cold-cache setup cycles after timer subtraction |
| 72 | 4 / `u32` | minimum net checksum cycles in one batch |
| 76 | 4 / `u32` | maximum net checksum cycles in one batch |
| 80 | 4 / Q16.16 `u32` | cycles per processed byte, including recurring cache setup |
| 84 | 4 / Q16.16 `u32` | effective decimal MB/s, including recurring cache setup |
| 88 | 4 / Q16.16 `u32` | projected CPU percent at the target framed byte rate |
| 92 | 4 / `u32` | target framed rate, exactly 8,100,000 bytes/s |

The i.MX RT1062 DWT cycle counter is enabled without resetting the shared
counter and is accepted only when the runtime CPU frequency is exactly 600
MHz and the counter is observed advancing. The minimum of 32 empty timed
intervals calibrates read/barrier overhead. Four checksum warm-ups are
excluded. Interrupts are disabled only from the start counter read through the
end read for each checksum, and separately for each measured invalidation, so
USB servicing cannot inflate a sample. The prior interrupt mask is restored
after every interval. Each interval is shorter than one 32-bit wrap; unsigned
subtraction handles a single wrap, while all aggregates use `u64`. Out-of-line
non-IPA checksum bodies, compiler memory barriers, a deterministic mixer, and
a volatile published digest prevent dead-code elimination or loop hoisting.

For \(N\) processed bytes and
\(C = \text{net_checksum_cycles} + \text{cache_setup_cycles}\), nonempty
fixed-point fields are integer floors of:

$$
\begin{aligned}
\text{cycles_per_byte_q16} &= \frac{C \cdot 65536}{N}, \\
\text{bytes_per_second} &= \frac{600000000 \cdot N}{C}, \\
\text{mb_per_second_q16} &= \frac{\text{bytes_per_second} \cdot 65536}{1000000}, \\
\text{projected_cpu_percent_q16} &=
  \frac{\text{cycles_per_byte_q16} \cdot 8100000 \cdot 100}{600000000}.
\end{aligned}
$$

For the empty vector these three byte-derived fields are zero, while raw/net
cycles and the deterministic digest remain meaningful. The wire validator
also requires
`raw_checksum_cycles - operations * timer_overhead_cycles == net_checksum_cycles`
and verifies processed bytes, batch bounds, code/table/RAM claims, and every
derived field before exposing the result. Code bytes describe the selected
algorithm body; the shared narrow dispatch is recorded separately in build
provenance. CRC table bytes are 8,192 and Adler table bytes are zero.

### GPIO_CLOCK_DIAGNOSTIC

GPIO_CLOCK_DIAGNOSTIC is an optional, bounded, IDLE-only measurement of the
fixed PIT0 → XBARA1 input 56 → rising-edge output 0 → DMAMUX source 30 → eDMA
channel 2 path selected by [[ADR-003-GPIO-Clock-DMA]]. It never changes a pad
mux, reads a user pin, allocates a run ID, changes acquisition configuration,
emits data, or resets statistics. The DMA source and destination are isolated
words in one aligned 32-byte OCRAM allocation. CONFIGURED and RUNNING requests
return `INVALID_STATE`; firmware without capability bit `0x00000080` returns
`UNSUPPORTED_CONFIGURATION`. The route and edge mode passed the hardware rig
at 1 kHz, 1 MHz, and three consecutive 4 MHz windows in final-image job
`db75db1e-45c0-4f66-a09a-bb4adee26b77`.

The immutable production rate remains 4,000,000 samples/s in INFO regardless
of the selected diagnostic rate. A diagnostic rate is accepted only when it
is from 1,000 through 4,000,000 Hz, divides both the 24 MHz PIT clock and the
600 MHz DWT clock exactly, and keeps the measurement at or below 60,000,000
DWT cycles (100 ms). Event count is 32 through 8,192. The guarded eDMA major
count is `2 * event_count + 16` and must fit the 15-bit ELINKNO count.

The eight-byte request is:

| Offset | Type | Field | Constraint |
| ---: | --- | --- | --- |
| 0 | `u32` | rate Hz | Exact permitted divisor; production is 4,000,000 |
| 4 | `u16` | event count | 32 through 8,192 and within the duration bound |
| 6 | `u16` | reserved | Zero |

The 140-byte success response is a read-only evidence snapshot. Configured
fields are captured after the channel is armed and before PIT starts;
terminal fields are captured after PIT, eDMA request, DMAMUX, and XBAR DMA
output are disabled in that order.

| Offset | Type | Field |
| ---: | --- | --- |
| 0 | response prefix | Successful status/error prefix |
| 4 | `u32` | configured rate Hz |
| 8 | `u32` | immutable production rate Hz, exactly 4,000,000 |
| 12 | `u32` | PIT clock Hz, exactly 24,000,000 |
| 16 | `u32` | PIT load value, `24000000 / rate_hz - 1` |
| 20 | `u32` | requested event count |
| 24 | `u32` | events scheduled from elapsed DWT cycles |
| 28 | `u32` | completed eDMA samples |
| 32 | `u32` | DWT counter Hz, normally 600,000,000 |
| 36 | `u32` | elapsed DWT cycles |
| 40 | `u32` | GPIO clock hardware-error flags |
| 44 | `u32` | configured `CCM_CSCMR1` |
| 48 | `u32` | configured `CCM_CCGR1` |
| 52 | `u32` | configured `CCM_CCGR2` |
| 56 | `u32` | configured `CCM_CCGR5` |
| 60 | `u32` | configured `PIT_MCR` |
| 64 | `u32` | configured PIT `LDVAL` |
| 68 | `u32` | final PIT `CVAL` |
| 72 | `u32` | configured PIT `TCTRL` |
| 76 | `u32` | final PIT `TFLG` |
| 80 | `u16` | configured XBARA selection register |
| 82 | `u16` | configured XBARA control register; the accepted output-0 rising-edge/DMA bits are `0x0005` |
| 84 | `u32` | configured DMAMUX channel register |
| 88 | `u32` | configured eDMA `CR` |
| 92 | `u32` | final eDMA `ES` |
| 96 | `u32` | configured eDMA `ERQ` |
| 100 | `u32` | final eDMA `ERR` |
| 104 | `u32` | final eDMA `HRS` |
| 108 | `u32` | TCD source address |
| 112 | `u32` | TCD destination address |
| 116 | `u32` | TCD bytes per minor loop |
| 120 | `u32` | cache-invalidated final destination word |
| 124 | `u16` | final TCD current iteration count |
| 126 | `u16` | configured TCD beginning iteration count |
| 128 | `u16` | final TCD control/status |
| 130 | `u16` | configured TCD attributes |
| 132 | `u8` | PIT channel ID |
| 133 | `u8` | XBARA input ID |
| 134 | `u8` | XBARA output ID |
| 135 | `u8` | eDMA channel ID |
| 136 | `u8` | DMAMUX source ID |
| 137 | `u8` | eDMA priority |
| 138 | `u16` | TCD source offset |

The host derives scheduled events with integer division of elapsed DWT cycles
by exact cycles per event. A healthy result requires zero hardware-error
flags, a scheduled count within one of the requested count, and a sampled
count within one of the scheduled count.
Known hardware-error bits are:

| Bit value | Name | Meaning |
| ---: | --- | --- |
| `0x00000001` | `DWT_UNAVAILABLE` | Cycle counter absent, stopped, or not 600 MHz |
| `0x00000002` | `RESOURCE_BUSY` | Reserved PIT/XBAR/eDMA owner was already active |
| `0x00000004` | `PERCLK_MISMATCH` | PIT peripheral clock is not exact 24 MHz |
| `0x00000008` | `PIT_GATE_DISABLED` | PIT clock gate snapshot is not enabled |
| `0x00000010` | `XBAR_GATE_DISABLED` | XBARA1 clock gate snapshot is not enabled |
| `0x00000020` | `DMA_GATE_DISABLED` | eDMA clock gate snapshot is not enabled |
| `0x00000040` | `PIT_CONFIG_MISMATCH` | PIT enable/load snapshot differs from the plan |
| `0x00000080` | `XBAR_CONFIG_MISMATCH` | XBAR input/edge/DMA-enable snapshot differs |
| `0x00000100` | `DMAMUX_CONFIG_MISMATCH` | DMAMUX source or enable differs |
| `0x00000200` | `EDMA_CONFIG_MISMATCH` | TCD, request, priority, or copied sentinel differs |
| `0x00000400` | `EDMA_CHANNEL_ERROR` | eDMA global/channel error was observed |
| `0x00000800` | `DEAD_TRIGGER` | Scheduled events produced no DMA sample |
| `0x00001000` | `DUPLICATE_TRIGGER` | DMA samples exceed scheduled events by more than one |
| `0x00002000` | `COUNT_OUT_OF_TOLERANCE` | Absolute scheduled/sample difference exceeds one |
| `0x00004000` | `MEASUREMENT_OVERFLOW` | Guard major loop completed or TCD counts are invalid |

An unarmed `DWT_UNAVAILABLE` or `RESOURCE_BUSY` snapshot may retain preexisting
TCD values; no sample-count claim is inferred from it. All other successful
responses must prove `dma_sample_count == BITER - CITER`, and a zero-error
response must include a nonzero 600 MHz DWT interval. Unknown flag bits and
inconsistent derived fields are rejected as `INVALID_PAYLOAD`.

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

`protocol/fixtures/` contains one complete Adler-32 frame for all 21 v1 frame
kinds (two data, nine requests, nine typed responses, and one generic error)
plus a deterministic `manifest.json` with decoded header values, payload
and frame SHA-256 hashes, checksums, and inline hex for small control frames.
The ADC vector is the little-endian pair ramp `(0, 1), (2, 3), ...`; the GPIO
vector is the byte ramp `0, 1, ... 255, 0, ...`.

The generated Python and C++ files and fixture manifest embed the SHA-256 of
`protocol/protocol-v1.json`. Tests independently unpack every header, verify
all length relationships, recompute Adler-32 and SHA-256, validate stream
ordering, and run generator check mode. Any mismatch is contract drift.
