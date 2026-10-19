---
type: analysis
title: Public protocol v3 offline upgrade architecture
created: 2026-10-19
tags:
  - protocol-v3
  - architecture
  - offline
related:
  - '[[protocol-v3-prototype]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-foundation]]'
  - '[[python-api]]'
---

# Public protocol v3 offline upgrade architecture

Phase 01 implements a hardware-free vertical slice: discover an explicitly
simulated Teensy 4.0, select an advertised configuration, capture compressed
ADC/GPIO frames through the public Python transport/parser stack, and read back
the applied settings. [[protocol-v3-prototype]] records commands and measured
offline results. [[protocol-v3]] describes the complete wire contract.

## Component ownership

| Component | Responsibility |
| --- | --- |
| `protocol/protocol-v3.json` | Canonical layouts, enums, limits, exact configuration tuples, state/error rules and golden fixtures. |
| `tools/generate_protocol.py` | Validates contracts and generates separate v3 Python/C++ constants and source-hashed fixtures without changing v1/v2 artifacts. |
| `daq_api/src/thingdone_daq/models_v3.py` | Typed capabilities, settings, identity, clocks, commands and correlated responses; exact tuple and echo validation. |
| `daq_api/src/thingdone_daq/protocol_v3.py` | Bounded v3 framing, mandatory checksums, RAW/RLE/PACK12 codecs and ordinary decoded block views. Reuses the incremental scanner/checksum backend. |
| `daq_api/src/thingdone_daq/simulator_v3.py` | Encoded command handling, deterministic source samples, atomic configuration, replay/state handling and drain-aware simulated device. |
| `daq_api/src/thingdone_daq/session_v3.py` | Public v3 command lifecycle, capability selection, applied echo/readback, run identity, status and bounded STOP. |
| Existing `client.py`, `transport.py`, `reader.py`, `protocol_v2.py`, `models.py` | ThingDAQ facade, in-memory byte transport, shared background reader, opt-in compatible parser, ADCBlock/GPIOBlock access and loss accounting. |
| `daq_api/examples/protocol_upgrade.py` | Executable discovery/configuration/capture/readback demonstration with exact source comparisons and deterministic cleanup. |

The data path is public facade → session → shared reader/transport → simulated
device, then encoded bytes → compatible parser → validated decoded blocks.
Opening `ThingDAQ.simulated(protocol_version=3, strict=True)` performs two
stable-identity INFO queries, GET_CAPABILITIES, GET_SETTINGS and GET_STATUS over
the wire. Public API capture does not bypass framing with direct device calls.

## Configuration and lifecycle

Board defaults are both streams, HARDWARE source (emulated), CPU 600 MHz,
1 MHz ADC-pair and GPIO rates, 12-bit ADC, auxiliary bank DISABLED (8 GPIO bits),
GPIO RLE_AUTO and ADC PACK12. Both HARDWARE and SYNTHETIC selections produce
deterministic simulated input; identity explicitly reports simulation.

Capabilities advertise 60 complete settings tuples: 48 at 600 MHz across
RAW/compressed policies and 12 RAW-only tuples at 450 MHz. Each combines one of
ADC/GPIO/both, hardware/synthetic source and 8/16-bit GPIO. Even disabled-stream
fields must match an advertised record. Known CPU/rate definitions do not
authorize arbitrary combinations. Auxiliary OUTPUT, 528 MHz, other boards and
historical higher sampling rates are excluded.

CONFIGURE is atomic and allowed only when STOPPED with drain complete.
The host checks exact tuple membership, the applied settings/clock echo and
GET_SETTINGS readback. RUNNING rejects configuration with INVALID_STATE;
DRAINING rejects it with BUSY. Neither failure mutates settings. START returns
the applied settings and new nonzero run ID before data. STOP drains a partial
frame and preserves settings; reboot restores board defaults. Wire mode cannot
change during a run or drain. Clock selection changes simulator metadata only.

## Wire and decoding decisions

- Public version **3** retains the 44-byte little-endian header, four-byte
  trailer, response correlation, per-stream sequence numbers, run IDs and
  START-relative 8 MHz timestamp domain. Adler-32 covers transmitted header and
  payload bytes. Reserved fields are zero; command/control limits are 68/2048
  bytes. GET_CAPABILITIES/GET_SETTINGS use unused command IDs `0x1C/0x1D`.
- Every data payload has a 12-byte prefix: encoding discriminator, decoded item
  width, reserved zero, decoded sample-byte count and RLE record count. RAW,
  GPIO_RLE and ADC_PACK12 are explicit encodings within version 3. Illegal
  kind/encoding combinations and contradictory stream settings are rejected.
- Decoded sample storage is at most 4048 bytes and complete wire frames at most
  4108 bytes. Validate counts, lengths, checksum and bounds before expansion.
  ADC frames contain at most 1012 pairs; GPIO8/GPIO16 contain at most 4048/2024
  samples. Capabilities bound tables to two CPU, one rate and 64 settings records,
  with zero-filled unused slots.
- RAW ADC stores ADC0 then ADC1 as little-endian u16 values in `0..4095`.
  PACK12 stores `(a & 255, (a >> 8) | ((b & 15) << 4), b >> 4)`;
  `(0xABC, 0x123)` becomes `BC 3A 12`. Out-of-range codes fail rather than mask.
  Two channels take three bytes instead of four, saving 25% of sample storage.
- GPIO RLE stores a nonzero little-endian u16 run length followed by a one- or
  two-byte sample. Runs are maximal with distinct adjacent values; their sum
  must equal the logical item count. RLE_AUTO uses RLE only when strictly smaller
  than RAW; ties/expansion fall back to RAW. Both encodings have equal framing
  overhead, so sample-byte profitability is also complete-frame profitability.

ADCBlock/GPIOBlock retain ordinary logical samples and channel views.
`decoded_bytes`, `encoded_sample_bytes` and `wire_bytes` separate decoded
storage, encoded samples and complete frames. Each data frame adds 60 bytes
(44 header + 12 prefix + 4 checksum); payload savings are not a throughput claim.

ADC0 and GPIO timestamps advance eight ticks per logical item; ADC1 follows by
four ticks. Different streams need not span equal durations per frame.
Variable-count v3 loss accounting uses sequence deltas for missing frames and
timestamp deltas for missing items. Queue eviction sums actual item counts.
Fixed-count v1/v2 behavior remains intact.

## Compatibility and qualification boundary

V1/v2 canonical sources and all 111 generated legacy artifacts are frozen by
independent hash tests. V3 adds 31 generated outputs, including 28 golden frames.
Default simulator selection, production serial negotiation, CLI and firmware
remain on their existing v1/v2 paths. Private `0x82/0x83` research frames are
not public v3 and are not accepted as v3 encoding discriminators.

Facade annotations include v3 model variants, so callers accepting either
session type must narrow returned metadata/settings types. V3 status provides
its own contract counters, not legacy hardware-health telemetry. Strict loss
checks remain enabled; optional equal-frame alignment is not established here.

This phase establishes byte correctness, bounded parsing, API behavior and
simulated lifecycle only. It does not establish firmware integration, physical
clock switching, sustained USB/host throughput, analog accuracy, external pin
timing or thermal reliability. Those require subsequent implementation and
qualification; private-codec hardware evidence does not qualify public v3.

## Firmware control contract checkpoint (2026-10-19)

The existing C++ incremental parser, dispatcher and USB response queue now
understand all seven v3 control IDs and their request/response schemas. This
checkpoint implements discovery, capability/settings selection and serializers;
it does **not** enable public-v3 acquisition. START returns
UNSUPPORTED_CONFIGURATION until the following lifecycle/data-path tasks wire
public framing into acquisition. A successful fake application is portable
control evidence only. [[protocol-v3-firmware-control]] records validation.

`firmware/src/v3_settings.h` separates canonical board definitions, build defaults,
active settings/readback and an injectable application interface. Production
exposes twelve RAW tuples at its single build-fixed 450 or 600 MHz clock. It
performs no clock register writes; 528 MHz research builds cannot describe a
public-v3 settings tuple. The portable fake exposes all sixty board tuples to
exercise the same capability serializer and membership checks. Codec promotion
will replace the temporary RAW build defaults with compressed 600 MHz defaults.
Queries leave acquisition, negotiated mode, run identity and statistics generation
unchanged. CONFIGURE publishes settings only after successful exact adapter
readback. Application implementations own hardware atomicity; the subsequent
transactional task owns rollback orchestration and complete v2/v3 lifecycle
integration. The fixed-build adapter applies software selections only.

The capability contract now permits positive device limits bounded by canonical
maxima and build defaults belonging to the advertised subset. Previously the
schema and Python reader required reference limits/defaults, which would force
this fixed-clock checkpoint to misreport its capabilities. Generated schemas,
wire layouts and golden frame bytes remain unchanged; source hashes were
regenerated. The public Python reader preserves and validates these device
limits, checks capacity relationships and still rejects duplicate/unknown
records or defaults absent from the tuple set.

The control response buffer remains 1,536 bytes (the capability frame is 1,452),
and packet pages remain 4,096 bytes. The advertised sample capacity reserves the
12-byte v3 encoding prefix: 4,036 bytes, up to 1,009 ADC pairs, 4,036 GPIO8 samples
or 2,018 GPIO16 samples. These are storage ceilings, not a claim that v3 frames
are already emitted. The command buffer is 68 bytes and parser retention is
71 bytes, accounted as 72 aligned bytes. The resource registry also corrects its
old v1-sized accounting for existing v2 response buffers; no pool was enlarged.

The parser verifies bounded framing/checksum before reflecting malformed v3
requests, emits typed or generic errors with the current run ID, and retains
legacy malformed-frame handling. Pending-frame metadata includes complete
pages awaiting deferred codecs and partial USB frames, excluding unfinished
producer leases. Existing DMA/USB/deferred codec algorithms remain unchanged.
