---
type: analysis
title: 'ADR 006: Experimental RLE Streaming'
created: 2026-09-02
tags:
  - thingdaq
  - decision
  - protocol
  - compression
  - rle
  - experiment
related:
  - '[[ADR-001-Wire-Protocol]]'
  - '[[Protocol-V1]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Experiment-Baseline]]'
---

# ADR 006: Experimental RLE streaming

## Status

Accepted for the isolated `experiment/rle-streaming` prototype. This decision
defines an opt-in protocol-v2 experiment; it does not change the production
protocol-v1 contract, its default raw configuration, or any v1 generated file
or golden fixture.

## Context

[[Protocol-V1]] deliberately uses fixed 4,096-byte data frames. Each ADC frame
contains 1,012 complete `(adc0, adc1)` pairs and each GPIO frame contains 4,048
packed eight-pin samples. Both cover exactly 8,096 ticks of the common 8 MHz
timestamp domain. That layout is simple, bounded, and already validated across
the host, simulator, firmware, and [[Acquisition-Pipeline]].

Constant and slowly changing inputs repeat many complete logical items. A
lossless run-length encoding can reduce their USB traffic, but noise and
alternating values can make RLE larger than raw data. Compression therefore
must be negotiated explicitly, selected independently for each frame, and
unable to expand the wire stream. The experiment begins at the immutable
[[Experiment-Baseline]] and preserves the compatibility boundary established
by [[ADR-001-Wire-Protocol]].

## Decision

The canonical experimental source is `protocol/protocol-v2.json`. It is a
complete versioned contract pinned to the SHA-256 of
`protocol/protocol-v1.json`; its generated constants and fixtures use separate
paths. Protocol v1 remains authoritative for existing clients.

### Version and capability negotiation

- Existing clients and new clients using the default `RAW` configuration keep
  speaking protocol v1. Compression is never inferred from payload contents,
  firmware identity, or observed repetition.
- Only an explicit `RLE_AUTO` request enters protocol-v2 negotiation. The host
  first obtains a v2 INFO response and requires the generated
  `RLE_STREAMING` capability bit (`0x00000200`). If version 2 or that capability
  is unavailable, the host raises a typed capability error without sending a
  compression CONFIGURE request and without silently falling back to a
  different user intent.
- A protocol-v1 INFO response never advertises the new bit. This keeps strict
  v1 clients from encountering a capability bit that v1 defines as reserved.
- CONFIGURE request byte 3, reserved and required to be zero in v1, is the v2
  requested encoding. CONFIGURE and START response byte 7 is the exact applied
  encoding. `RAW` is `0`; `RLE_AUTO` is `1`; every other value is invalid.

### Frame selector and unchanged envelope

Protocol v2 retains the 44-byte header and four-byte trailer. Header byte 11,
reserved and zero in v1, becomes the actual data-frame encoding selector:

| Value | Selector | Meaning |
| ---: | --- | --- |
| `0` | `RAW` | Payload is the unchanged sequence of complete logical items. |
| `1` | `RLE` | Payload is a canonical sequence of RLE records. |

Every request, response, and error response retains zero at byte 11. A run
configured `RAW` permits only `RAW` data frames. A run configured `RLE_AUTO`
permits `RAW` and `RLE` data frames to be mixed in any order. Selectors 2
through 255 are illegal and are rejected before payload interpretation.

### Canonical RLE records

Every record starts with a positive little-endian `u16 run_length`, followed
immediately by exactly one complete logical item:

| Stream | Logical item | Raw item bytes | RLE record bytes |
| --- | --- | ---: | ---: |
| ADC | little-endian `u16 adc0`, then little-endian `u16 adc1` | 4 | 6 |
| GPIO | one packed D6-through-D13 byte | 1 | 3 |

The item is repeated `run_length` times. Zero-length runs are invalid.
Adjacent records with identical items are noncanonical and invalid; an encoder
coalesces them into one record. Because one frame has at most 4,048 logical
items, every valid coalesced run fits in `u16` and never needs continuation.
A run and all of its record bytes are confined to one frame; neither may cross
a frame boundary.

For both selectors, `item_count` is the decoded count. An RLE decoder accepts a
payload only when every record is complete and the exact sum of all run lengths
equals the kind-specific count in the header. ADC still requires 1,012 pairs,
GPIO still requires 4,048 samples, and both still cover 8,096 ticks. Sequence,
`first_sample_ticks`, `GAP_BEFORE`, `OVERRUN_BEFORE`, and `EPOCH_START` retain
their existing meaning over decoded logical frames and items.

### Per-frame selection and bounds

The full raw payload remains 4,048 bytes, so a raw data frame remains exactly
4,096 bytes. Under `RLE_AUTO`, firmware builds the canonical encoding for one
complete logical frame and emits it as `RLE` only when

\[
44 + \text{encoded payload bytes} + 4
<
44 + 4{,}048 + 4.
\]

A tie or larger RLE result emits the original payload as `RAW`. Thus adaptive
encoding never expands a frame. This produces the following exact bounds:

| Stream | Logical items | Largest selected run count | RLE payload bytes | RLE total bytes |
| --- | ---: | ---: | ---: | ---: |
| ADC | 1,012 | 674 | 6 through 4,044 | 54 through 4,092 |
| GPIO | 4,048 | 1,349 | 3 through 4,047 | 51 through 4,095 |

Data frames are consequently variable-length up to the existing 4,096-byte
maximum without changing the logical item budget or timestamp coverage.
Records that cannot satisfy the strict inequality are not transmitted; the
frame uses `RAW` instead.

### Integrity and validation order

The selected checksum algorithm covers the transmitted 44-byte header,
including the selector, followed by the encoded payload. It excludes only the
four-byte trailer, exactly as in v1. A receiver first validates bounded header
and transmitted-length invariants, then validates the checksum, and only then
decodes and validates RLE records. It never exposes a partially decoded block.

Decoded expansion is bounded by the generated item count for the frame kind,
not by allocation sized from an untrusted run sum. An incomplete record, zero
run, count overflow or mismatch, adjacent equal record, illegal selector,
invalid length, or bad checksum rejects the whole frame. Stream parsing then
resynchronizes using the existing bounded framing policy.

## Consequences

- A negotiated acquisition can contain mixed raw and compressed frames while
  retaining the existing `ADCBlock` and `GPIOBlock` logical representation.
- Compression benefit is explicitly workload-dependent. Long digital holds
  should save strongly; noisy ADC data may consistently select raw frames.
- The host and firmware need isolated v2 constants, vectors, codecs, and
  parser paths. The v1 generator outputs and fixtures remain byte-for-byte
  frozen and continue to serve as the compatibility oracle.
- RLE is lossless but is not an integrity or confidentiality feature. Checksum
  validation remains mandatory and retains its existing accidental-corruption
  scope.

## Alternatives considered

### Always emit RLE after negotiation

Rejected because alternating and high-entropy inputs expand by the two-byte
run prefix per record. Per-frame raw fallback makes the no-expansion property
structural rather than workload-dependent.

### Use a frame flag as the selector

Rejected because byte 11 already exists in the fixed envelope and is available
only after a version change. Keeping encoding out of the loss/source flags also
preserves their independent semantics.

### Allow runs to continue across frames

Rejected because it would couple frame decoding and recovery state. Frame-local
records keep random access, corruption containment, sequence gaps, and parser
resynchronization deterministic.

### Change protocol v1 in place

Rejected because v1 requires reserved header and configuration bytes to be
zero and rejects unknown capability bits. Reinterpretation would turn a
strictly validated compatibility rule into ambiguous behavior for deployed
clients.
