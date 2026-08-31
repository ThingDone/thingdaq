---
type: analysis
title: 'ADR 001: Wire Protocol'
created: 2026-08-27
updated: 2026-08-29
tags:
  - thingdaq
  - decision
  - protocol
  - framing
related:
  - '[[Protocol-V1]]'
  - '[[System-Overview]]'
  - '[[ADR-002-Checksum-Selection]]'
---

# ADR 001: Wire protocol

## Status

Accepted for protocol v1. Stable checksum identifiers and capabilities remain
negotiable; [[ADR-002-Checksum-Selection]] subsequently retained Adler-32 as
the production data default under the fixed Phase 05 qualification policy.

## Context

ThingDAQ carries two continuous data streams and bidirectional control over
USB CDC, which is a byte stream rather than a message transport. The host must
recover from arbitrary read boundaries, leading garbage, corruption, stale
bytes from a previous acquisition run, and reconnects. Firmware and Python
also need identical numeric constants without maintaining hand-written copies.

The 32-byte candidate header in the early design notes could not independently
represent all required identities and invariants:

- acquisition run identity;
- per-stream sequence identity;
- concurrent request/response correlation;
- an explicit checksum algorithm;
- an extensible but strictly validated header length.

The prototype established a 44-byte common envelope. Phase 02 retained that
working shape and closed its remaining contract gaps: generated command IDs,
GET_STATUS naming, RESET_STATS and PING schemas, capability bits, explicit
overrun signaling, statistics generations, command-size bounds, and fail-
closed compatibility rules. See [[Protocol-V1]] for the normative byte-level
specification and [[System-Overview]] for the firmware/host boundary.

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
exactly 8,096 ticks (1,012 µs). Commands are at most 56 bytes and control
responses are defensively bounded at 1,280 bytes.

Request frame-kind IDs are also command-kind IDs. INFO through PING occupy
`0x10` through `0x16`; each typed response is its request ID ORed with `0x80`.
Every request carries a nonzero request ID, and every response copies it.
INFO advertises independent stream, source, checksum, and capability masks and
reports the selected data checksum (the generated default in IDLE or applied
configuration otherwise). PING remains optional and must be advertised.

Each successful START allocates a new nonzero run ID and resets sequence,
timestamp, and counter epochs. The host accepts data only for the run ID
returned by that START. RESET_STATS is restricted to IDLE or CONFIGURED and
advances a statistics generation, so a reset cannot be mistaken for loss or
counter wrap while acquisition is active.

`GAP_BEFORE` says continuity was lost. `OVERRUN_BEFORE` is narrower: it says
firmware caused that gap and therefore requires `GAP_BEFORE`. Host queue loss
is accounted separately and never changes firmware flags or counters.

Checksum algorithm zero is permanently invalid. Algorithm 1 is Adler-32 and
is the only bootstrap algorithm for commands and responses. Algorithms 2 and
3 are CRC-32C and CRC-32/ISO-HDLC; INFO advertises all three and CONFIGURE
selects the algorithm used by data frames. The packet epoch snapshots that
selection, and reconfiguration is rejected as `BUSY` until prior frames drain.
INFO, STATUS, and decoded block metadata expose the exact selection. This
stable field lets the later evidence-based checksum decision change the data
default without redesigning the envelope or bootstrapping control traffic.

The authoritative contract is `protocol/protocol-v1.json`. The deterministic
`tools/generate_protocol.py` generator validates cross-field invariants and
produces Python constants, C++ constants, and one checked-in golden frame for
every frame kind. `--check` compares exact expected bytes and rejects orphaned
binary fixtures without writing.

## Consequences

- Firmware serializes fields explicitly; it never casts a native C++ struct
  onto the wire.
- Host parsing rejects implausible headers before waiting for an attacker- or
  corruption-controlled length.
- Commands carry data-only header fields as zero, but one parser and checksum
  path validates every frame class.
- The 44-byte header is larger than the early 32-byte candidate. Framing
  overhead remains about 1.17% per data stream.
- Run identity and statistics generation make restarts, counter resets, and
  stream gaps distinguishable.
- Unknown versions, kinds, reserved bits, and payload extensions fail closed;
  they never partially mutate device state.
- Changing any source value requires regeneration because the source hash is
  embedded in both generated languages and the fixture manifest.

## Alternatives considered

### Keep separate compact command framing

Rejected because it duplicates incremental parsing, length validation,
checksum dispatch, and resynchronization logic on both Teensy and host.

### Add a second command byte inside every payload

Rejected because the request frame-kind byte already identifies the command.
A second serialized identifier could disagree and would add a validation path
without adding information. The generator instead emits a `CommandKind` enum
and request/response mappings from the same entries.

### Keep the 32-byte data header

Rejected because overloading sequence or flags with run and request identity
would make loss detection and response correlation ambiguous.

### Make Adler-32 implicit

Rejected because a production checksum change would require a framing version
or out-of-band inference. An explicit algorithm byte preserves wire shape and
makes capabilities observable.

### Use 512-byte application frames

Rejected as the default because framing, checksum, parser, and dispatch work
would be much higher. A 4,096-byte application frame maps efficiently onto
512-byte high-speed USB packets without treating packet boundaries as message
boundaries.
