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
  - '[[protocol-v3-python]]'
  - '[[protocol-v3-firmware-portable]]'
---

# Public protocol v3 offline upgrade architecture

## Current scope: fixed 600 MHz (2026-10-19)

The user explicitly requires a fixed 600 MHz CPU; runtime frequency switching
was not requested. The normal build now selects 600 MHz in its FQBN, timing
definitions and output directory. `FixedBuildApplication` continues to advertise
only the build's CPU profile and rejects requests for another speed. Stopped
acquisition/codec configuration remains supported; no PLL transition adapter,
core patch or watchdog-policy change is needed.

The Phase 04 transition blocker is superseded, and remaining Phase 04–06 work
covers fixed-clock configuration, documentation and qualification. Earlier
two-clock simulator coverage and 450 MHz build results below are historical
checkpoints, not requirements to switch CPU speed. The ordinary v3 simulator
and examples now follow the single-profile board policy.
Generic wire IDs and legacy build records remain compatible. Physical public-v3
qualification is still pending; this change does not program a device.

Validation of this scope/build correction: 136 focused tests passed with five
expected skips (build configuration, input timing, public control, runtime
layouts and documentation). Generator, Ruff format/lint and SDK mypy passed.
The normal pinned 600 MHz target build passed unchanged memory/placement gates:
33,024 bytes free for RAM1 locals/stack and 4,096 bytes for RAM2 heap.
The control regression rejects another otherwise-valid CPU profile and verifies
unchanged settings; no runtime clock switch is performed. Full release
qualification remains in the revised playbook.

Phase 03 now integrates public v3 control, per-run codecs, acquisition layouts
and USB framing in firmware. Portable C++ execution and the public Python SDK
agree on emitted bytes, repeated v2/v3 sessions and loss accounting. Production
clock selection remains fixed at build time; physical public-v3 capture
remains unqualified. [[protocol-v3-firmware-portable]]
records the consolidated gate and [[protocol-v3-python]] the earlier host gate.

Phase 01 established the hardware-free vertical slice: discover an explicitly
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
| Firmware `protocol.cpp`, `control_state.cpp`, `v3_settings.h` | Bounded generated controls, capability-derived tuples, transactional application/readback, replay protection and negotiated mode. |
| Firmware `firmware_runtime.cpp`, `acquisition_controller.cpp`, `stream_layout.h` | Run lifecycle, selected logical counts, acquisition routing and public status snapshots. |
| Firmware `packet_buffer_pipeline.cpp`, `deferred_codec.h`, `rle_encoder.cpp`, ADC/GPIO packers | Existing page ownership, cooperative RAW/RLE/PACK12 publication, loss and STOP-tail accounting. |
| Firmware `usb_transport.cpp` | Shared frame-shape validation, immutable partial-write ownership, logical-coverage fairness and actual wire-byte totals. |
| `firmware/tests/test_v3_cross_language.py` and its C++ harness | Python command bytes through the real C++ control/runtime/USB path, decoded by public Python parser and block APIs. |

The data path is public facade → session → shared reader/transport → simulated
device, then encoded bytes → compatible parser → validated decoded blocks.
Opening `ThingDAQ.simulated(protocol_version=3, strict=True)` performs two
stable-identity INFO queries, GET_CAPABILITIES, GET_SETTINGS and GET_STATUS over
the wire. Public API capture does not bypass framing with direct device calls.

## Simulator configuration and lifecycle

Simulator board defaults are both streams, HARDWARE source (emulated), CPU 600 MHz,
1 MHz ADC-pair and GPIO rates, 12-bit ADC, auxiliary bank DISABLED (8 GPIO bits),
GPIO RLE_AUTO and ADC PACK12. Both HARDWARE and SYNTHETIC selections produce
deterministic simulated input; identity explicitly reports simulation.

Simulator capabilities advertise 48 complete settings tuples at fixed 600 MHz
across RAW/compressed policies. The generic canonical table retains twelve
450 MHz RAW tuples for compatibility; the ordinary simulator rejects them.
Each supported tuple combines one of
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
change during a run or drain. CPU speed remains 600 MHz throughout. Known
nonadvertised CPU profiles return UNSUPPORTED_CONFIGURATION when stopped,
INVALID_STATE when running and BUSY during drain, without mutating settings.
The public example exercises compressed/RAW/default changes, host rejection of
a 450 MHz RAW selection and unchanged historical v1/v2 personas.

Simulator alignment validated 2026-10-20: all 1,237 SDK tests passed across the
focused simulator/API/CLI/example/documentation suite and remaining SDK suite.
The documentation gate executes nine simulator snippets; its expected count
was updated for the new SDK README example. Regression coverage retains all
60 generic tuples: 48 stream at 600 MHz and twelve 450 MHz tuples are rejected
without mutation. Wire tests preserve stopped/running/draining error precedence.
Generator drift (142 outputs), changed-Python Ruff format/lint and SDK mypy
(33 source files) passed. No firmware build, hardware access or task images
were needed for this simulator/documentation task. Historical results remain
unchanged; subsequent Phase 04 tasks own firmware validation.

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
Default simulator selection remains historical v1/v2; the Python serial facade
and CLI now negotiate public v3 with bounded explicit fallback to legacy peers.
Current firmware accepts v3 and explicit v2 RAW configuration; it preserves the
release rejection of v1 acquisition. Private `0x82/0x83` research frames are not
public v3 and are not accepted as v3 encoding discriminators.

Facade annotations include v3 model variants, so callers accepting either
session type must narrow returned metadata/settings types. V3 status provides
its own contract counters, not legacy hardware-health telemetry. Strict loss
checks remain enabled; optional equal-frame alignment is not established here.

Phases 01–03 establish byte correctness, bounded parsing, API behavior and
firmware integration through portable runtime execution and linked target
images. They do not establish physical clock switching, sustained USB/host
throughput, analog accuracy, external pin timing or thermal reliability.
Those require subsequent implementation and qualification; private-codec
hardware evidence does not qualify public v3.

The following checkpoints retain the implementation sequence. START gating and
unfinished integration described in the control/codec checkpoints were resolved
by the layout/transport checkpoint below.

## Firmware control contract checkpoint (2026-10-19)

The existing C++ incremental parser, dispatcher and USB response queue now
understand all seven v3 control IDs and their request/response schemas. This
checkpoint initially implemented discovery, capability/settings selection and
serializers with public-v3 acquisition gated. START returned
UNSUPPORTED_CONFIGURATION until the later layout/transport integration.
A successful fake application is portable
control evidence only. [[protocol-v3-firmware-control]] records validation.

`firmware/src/v3_settings.h` separates canonical board definitions, build defaults,
active settings/readback and an injectable application interface. Production
exposes 48 RAW/compressed tuples at its build-fixed 600 MHz clock, or twelve
RAW-only tuples at 450 MHz. It
performs no clock register writes; 528 MHz research builds cannot describe a
public-v3 settings tuple. The portable fake exposes all sixty board tuples to
exercise the same capability serializer and membership checks. The 600 MHz
build defaults now select RLE_AUTO and PACK12; 450 MHz defaults remain RAW.
Queries leave acquisition, negotiated mode, run identity and statistics generation
unchanged. CONFIGURE publishes settings only after successful exact adapter
readback. ControlState now reapplies and verifies the previous complete settings
on application failure or mismatched readback. A failed rollback inhibits START
and settings/clock reports until a successful CONFIGURE. The fixed-build adapter
still applies software selections only; public-v3 START was gated at this
checkpoint pending public data-path integration.

[[protocol-v3-firmware-transactions]] records the transactional/legacy checkpoint.
Successful v2 CONFIGURE explicitly selects historical RAW layouts, compiled-clock
settings and the ADC2 request route. The qualified ADC_ETC route remains intact
for the experimental path. V2 INFO/STATUS use historical counts, timing tables,
known capability bits and standard payload sizes, including in a private-codec
build. The synthetic source follows selected per-stream counts and coverage.
Only CONFIGURE changes mode: INFO probes never switch it, pending STOP/DMA/packet/
USB work blocks reconfiguration, and duplicate IDs retain the contract's bounded
16-entry replay protection. The later layout task completed public-v3 START/STOP
acquisition.

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
or 2,018 GPIO16 samples. These storage ceilings exceed the selected aligned run
counts documented below. The command buffer is 68 bytes and parser retention is
71 bytes, accounted as 72 aligned bytes. The resource registry also corrects its
old v1-sized accounting for existing v2 response buffers; no pool was enlarged.

The parser verifies bounded framing/checksum before reflecting malformed v3
requests, emits typed or generic errors with the current run ID, and retains
legacy malformed-frame handling. Pending-frame metadata includes complete
pages awaiting deferred codecs and partial USB frames, excluding unfinished
producer leases. DMA/USB ownership and cooperative codec deadlines remain unchanged.


## Firmware codec checkpoint (2026-10-19)

[[protocol-v3-firmware-codecs]] records public policy-driven packet encoding.
`stream_layout::publicV3` snapshots validated settings and explicit logical block
counts into a run layout. Producers receive decoded sample storage after the
12-byte prefix. The packet pipeline emits version 3 with RAW, GPIO_RLE or
ADC_PACK12 identifiers, decoded byte counts, and RLE run counts. GPIO8 reuses the
generic encoder; GPIO16 retains the qualified hybrid encoder. Strict whole-frame
profitability selects RAW for ties and incompressible samples. ADC input is
validated as 12-bit before RAW publication or lossless in-place PACK12 packing.

The same deferred FIFO ownership, 80,000-tick deadline, one-block idle service,
resource drops, gap propagation and STOP-tail drain apply without experimental
build defines. RLE borrows a FREE page from the existing pool; no frame buffer was
added. Explicit v2 configurations still force historical RAW settings even when
the build defaults are compressed. Private experiment layouts retain their
explicit adapter and wire versions. ADC_ETC request routing can now be selected
by public run mode independently of private codec flags; legacy v2 retains ADC2.

This checkpoint tested packet bytes directly with the public Python decoder.
Public-v3 START, production ADC/GPIO block counts, the USB v3 data guard and public
codec diagnostics were completed in the following layout/transport checkpoint.
Physical qualification remains outstanding. The storage
ceilings above are enforced by the packet layout factory, and the public v3
checksum remains Adler-32 only.


## Firmware layout/transport checkpoint (2026-10-19)

[[protocol-v3-firmware-layouts]] completes acquisition/USB integration and enables
public v3 START/STOP. One shared decoded-payload size selects 1008 ADC pairs,
4032 GPIO8 samples or 2016 GPIO16 samples; each RAW frame occupies 4092 bytes in
an existing 4096-byte page. GPIO16 DMA count, pair-join leases and STOP accounting
now follow the run layout. ADC priority mode is independent of frame size.
Legacy v2 layouts and private experiment adapters remain explicit.

The packet and USB paths share a bounded v3 shape guard. Queue fairness compares
logical coverage, wire throughput accumulates actual transmitted frame lengths,
and STATUS retention is an explicitly shared-pool upper bound. The generated
256-byte public STATUS schema exposes layout, wire totals and codec counters;
Python models and golden vectors match it. The fixed control buffers and packet
storage are unchanged. A bounded raw-tail drain precedes the v3 STOP response.

Both 450/600 MHz linked images pass the original memory gates after moving
immutable discovery tables and initialization-only code to program flash.
Physical capture/throughput qualification remains
outstanding; portable adapters and synthetic streaming do not establish them.

## Firmware portable validation checkpoint (2026-10-19)

[[protocol-v3-firmware-portable]] consolidates the full firmware/Python regression,
generator, formatting, lint, typing and linked-image memory gates. No production
code, state-size bound, page count or required gate was changed for this check.
The default build remains 450 MHz RAW; the isolated 600 MHz verification build
selects RLE_AUTO/PACK12 and is not a published release image.

[[protocol-v3-firmware-adversarial]] supplies independent wire/checksum oracles
and pressure, ownership, resource/deadline and STOP-tail regressions.
[[protocol-v3-firmware-cross-language]] supplies command-driven C++ sessions
decoded through public Python frames and ADCBlock/GPIOBlock APIs, including
irregular chunks, both GPIO widths, mixed RAW/RLE frames and exact legacy v2
layouts. The current gate reruns those suites; their physical limitations remain.

## Runtime clock dependency audit (2026-10-19)

[[runtime-clock-dependency-audit]] pins the installed Teensy core 1.62.0 clock
sequence and maps active timing, cached schedules, legacy projections and fixed
storage. It identifies unbounded core handshake waits and mixed-frequency
`micros()` conversion as constraints for the runtime adapter. The current
watchdog remains disabled; runtime switching is out of scope and physical
qualification is still pending. The audit passed 41 baseline tests
(3 intentional skips) and 6 subtests without changing firmware.
