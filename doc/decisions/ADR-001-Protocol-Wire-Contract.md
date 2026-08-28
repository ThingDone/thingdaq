---
type: analysis
title: 'ADR 001: Protocol V1 Wire Contract'
created: 2026-08-27
tags:
  - teensy-daq
  - decision
  - protocol
  - framing
related:
  - '[[Protocol-V1]]'
  - '[[System-Overview]]'
---

# ADR 001: Protocol V1 wire contract

## Status

Accepted for the synthetic prototype and initial firmware implementation.
Production checksum selection remains deliberately open behind an allocated
algorithm identifier.

## Context

Teensy DAQ carries two continuous data streams and bidirectional control over
USB CDC, which is a byte stream rather than a message transport. The host must
recover from arbitrary read boundaries, leading garbage, corruption, and
reconnects. Firmware and Python also need identical numeric constants without
maintaining two hand-written copies.

The 32-byte candidate header in the early design notes did not have distinct
space for all of these concerns:

- acquisition-run identity;
- per-stream sequence;
- request/response correlation;
- an explicit checksum algorithm;
- an extensible, validated header length.

See [[System-Overview]] for the firmware/host boundary and [[Protocol-V1]] for
the normative byte-level specification.

## Decision

Protocol v1 uses one explicitly little-endian envelope for data, requests, and
typed responses:

- a fixed 44-byte header;
- a payload whose length is stated independently;
- a fixed 4-byte checksum trailer;
- `0xDEADBEEF` magic, serialized as `EF BE AD DE`;
- separate 32-bit run, sequence, and request identifiers;
- unsigned 64-bit first-sample time at 8 MHz;
- a header checksum-algorithm identifier.

ADC and GPIO data frames are exactly 4,096 bytes. Their 4,048-byte payloads
hold either 1,012 ADC pairs or 4,048 packed GPIO samples, so each frame covers
exactly 8,096 ticks (1,012 µs). Control frames use the same validation and
resynchronization machinery but range from 48 through 1,024 bytes.

Checksum algorithm zero is permanently invalid. Algorithm 1 is Adler-32 and
is the only v1 bootstrap algorithm. Algorithm 2 is allocated to CRC-32C but is
not accepted until benchmarking and capability negotiation explicitly enable
it. The stable field and ID let that later decision change the configured data
checksum without redesigning the frame.

The authoritative contract is `protocol/protocol-v1.json`. The deterministic
`tools/generate_protocol.py` generator produces Python constants, C++
constants, and checked-in golden frames. `--check` compares expected bytes to
the repository without writing.

## Consequences

- Firmware must serialize fields explicitly; it must not cast a native C++
  struct onto the wire.
- Host parsing can reject implausible headers before waiting for an attacker-
  or corruption-controlled length.
- Commands carry some data-only fields as zero, but one parser and checksum
  path can validate every frame class.
- The 44-byte header is larger than the early 32-byte candidate. The resulting
  framing overhead is still about 1.17% per data stream.
- Timestamp and sequence reset rules are scoped by run ID, making reconnects,
  restarts, and acquisition gaps distinguishable.
- Changing a contract description or value requires regeneration because the
  source hash is embedded in every textual generated artifact and fixture
  manifest.

## Alternatives considered

### Keep separate compact command framing

Rejected because it would duplicate incremental parsing, length validation,
checksum dispatch, and resynchronization logic on both Teensy and host.

### Keep the 32-byte data header

Rejected because overloading sequence or flags with run and request identity
would make loss detection and response correlation ambiguous.

### Make Adler-32 implicit

Rejected because a production checksum change would then require a framing
version or out-of-band inference. The explicit algorithm byte preserves wire
shape and makes capabilities observable.

### Use 512-byte application frames

Rejected as the default because framing, checksum, parser, and dispatch work
would be much higher. A 4,096-byte application frame still maps cleanly onto
512-byte high-speed USB packets without treating USB packet boundaries as
application boundaries.
