---
type: analysis
title: RLE Firmware Integration Target
created: 2026-09-02
tags:
  - thingdaq
  - architecture
  - firmware
  - compression
  - rle
  - ownership
related:
  - '[[ADR-006-Experimental-RLE-Streaming]]'
  - '[[Protocol-V1]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Firmware-Resource-Map]]'
  - '[[System-Overview]]'
  - '[[rle-prototype]]'
---

# RLE firmware integration target

## Verified starting point

The target implementation starts from Phase 03 checkpoint
`cfc265769f5ed19eb166213c14efaf11fe2ab409` on
`experiment/rle-streaming`. The fetched remote branch is identical, its merge
base with `origin/experiment/baseline-2026-09-01` is the frozen baseline
`b23004defeca465da0ae2d2884c4fef71979e5d4`, and the clock experiment is not an
ancestor. The worktree was clean before this analysis.

`tools/generate_protocol.py --check` reported all 70 v1/v2 outputs current.
The dedicated v1 generation, frozen-v1 hash, v2 contract, and v2 vector tests
passed 27 tests and 1,031 subtests. The canonical v1 source and its 26 outputs
remain the compatibility oracle; target RLE work must use only the isolated v2
contract and generated constants from [[ADR-006-Experimental-RLE-Streaming]].

## Current target path

| Surface | Current invariant | RLE consequence |
| --- | --- | --- |
| ADC packer | A complete 1,012-pair DMA lease is copied once into the payload of a packet `FILLING` lease, finalized, and then the DMA lease is released. The packer consumes at most two buffers per service call. | Keep raw bytes in their owned packet page until adaptive selection has completed; no encoder work may enter the paired-DMA completion path. |
| GPIO packer | Raw DMA leases are packed into four fixed CPU-owned OCRAM buffers. At most two raw buffers and two packed frames are processed per service call before a packed buffer is recycled. | The common packet finalizer should consume the same canonical 4,048-byte payload; do not add another GPIO ring or change raw-DMA cache ownership. |
| Synthetic source | One visit creates at most two frames and uses `ADC0(n) = 2n & 0x0fff`, `ADC1(n) = (2n + 1) & 0x0fff`, and `GPIO(m) = m & 0xff`. ADC and GPIO frames both cover 8,096 ticks. | Experimental patterns may change the logical formula only through an explicit v2 capability. Default v1 formulas, timestamps, and real-time pacing remain exact. |
| Packet ownership | Only `FILLING` exposes mutable payload bytes. A complete frame moves through per-stream `READY` queues to immutable `TRANSMITTING` ownership and returns to `FREE` only after complete USB release or classified loss. | Adaptive finalization belongs at the `FILLING -> READY` boundary, while the source page is exclusively owned and before any queue publication. |
| Fairness and pressure | Promotion is round-robin and prevents either equal-duration stream from advancing more than one accounted frame while production is active. Pool pressure may evict only a complete frame whose first byte has not been sent. | Selection must not change logical frame counts or fairness. A temporary-page request must never evict retained data; failure to obtain it falls back to RAW. |
| USB writes | Responses win at a frame boundary. A data frame is pinned after byte zero, arbitrary short writes resume from the retained offset, and reconnect aborts a partial data frame as classified loss. | The write loop already follows the selected view size. Its two fixed-4,096-byte validity guards must become negotiated bounded-data-frame guards without changing response priority or pinning. |
| Checksum timing | The complete raw header and payload are checksummed before `READY`. A later unsent gap annotation rewrites flags and recomputes the checksum immediately before transmission. | Checksum only the selected v2 header and transmitted payload. Gap repair must use the record's actual frame length and preserve its encoding selector. |
| Runtime order | Receive and one-command dispatch precede source work. Synthetic/physical ownership, promotion, and transmit run cooperatively; physical ownership, promotion, and transmit are serviced a second time each loop. | Synchronous per-frame finalization remains bounded by existing source limits and preserves command/response priority. No new unbounded drain loop is needed. |
| Statistics | Saturating counters conserve logical production through framing, emission, transmission, and classified drops. Payload and wire bytes are currently derived as fixed raw bytes per item/frame. | Keep logical equations unchanged, but accumulate selected payload and complete-wire bytes from each record instead of deriving every wire frame as 4,096 bytes. Publish new fields only in v2 STATUS. |
| Cache and linker gates | DMA receive rings use explicit cooperative discard/invalidate operations. Packet pages are CPU-owned: 105 pages in DTCM and 95 in OCRAM. The build verifies exact symbols, regions, sizes, alignment, and at least 32 KiB of RAM1 local/stack headroom. | Compression stays CPU-only and performs no cache maintenance. Reuse packet pages instead of adding unaccounted frame storage, then retain the exact linker/map checks. |

The retained Phase 03 build has only 34,528 RAM1 bytes free for locals against
the 32,768-byte gate and 4,096 RAM2 bytes free for heap. A new 4,096-byte RAM1
page would fail the local/stack gate, and a new RAM2 page would consume all
reported headroom. The existing 200-page, 819,200-byte packet pool is therefore
the selected complete-frame workspace; adding another page is unacceptable
unless a later change explicitly rebalances and revalidates retention.

## Reusable implementation patterns

- `protocol::ByteView` and `MutableByteView` provide allocation-free bounded
  inputs and outputs. Generated v2 item, record, and selected-frame limits
  should remain the single numerical authority.
- `PacketBufferPipeline` already supplies nonzero leases, stale-handle
  rejection, fixed index queues, explicit ownership states, saturating
  counters, classified cancellation, and publish-after-completion semantics.
- ADC and GPIO capture rings prove the required lease rule: invalidate only
  after DMA completion, retain exclusive CPU ownership while reading, and
  release on every cooperative exit. Compression must not be included by any
  target ISR or adapter.
- The Python v2 decoder validates an entire record stream before its second
  expansion pass. The target encoder should apply the analogous discipline:
  a read-only sizing pass first, followed by output only after selection and
  capacity are known.
- `encodeDataFrameInPlace()` and `prepareFrontFrame()` demonstrate the two
  publication barriers to preserve: complete header/payload/checksum before
  `READY`, and complete late gap/checksum repair before USB accepts byte zero.
- The GPIO packed ring and common packet pool demonstrate bounded staged
  ownership. No existing C++ RLE encoder or general two-pass transform exists
  to reuse.

## Selected implementation

Add an isolated portable v2 RLE module with two operations:

1. A sizing pass validates the raw logical shape, counts canonical runs, and
   computes the complete encoded wire length with overflow-safe generated
   bounds. It does not write output. RAW is selected unless that complete wire
   length is strictly less than 4,096 bytes.
2. An encoding pass writes little-endian `u16` run lengths and complete items
   into a caller-owned fixed-capacity view. It succeeds only at the exact size
   from the sizing pass and reports the run count and bytes written.

`PacketBufferPipeline::finishFill()` remains the single publication boundary.
For v1 or negotiated v2 RAW it keeps the existing raw in-place finalizer. For
v2 `RLE_AUTO`, it retains the source page, runs the sizing pass, and follows
one of these paths:

```text
not strictly smaller
  raw source page -> v2 RAW header/checksum -> READY

strictly smaller and one FREE page is available without eviction
  raw source page (read-only) -> temporary packet page (RLE + checksum)
  temporary page -> READY; raw source page -> FREE

strictly smaller but no temporary page, or injected encoder failure
  temporary page, if acquired -> FREE
  intact raw source page -> v2 RAW header/checksum -> READY
  fallback/exhaustion/failure counters identify the reason
```

The temporary page needs an internal lease and explicit transform ownership
state. It is acquired with a new non-evicting free-page operation; the normal
producer acquisition policy may still perform its existing classified
eviction. At most one temporary page exists during a synchronous finalizer
call, and no temporary ownership survives the call. Consequently every
published logical frame still retains exactly one pool page, so the validated
200-frame retention budget is unchanged.

The raw page remains readable until the encoded header, payload, and checksum
are complete. The selected page is queued only after all record metadata is
committed. Queue rejection, STOP/rollback recovery, pressure handling, and
fault injection recycle every temporary page and classify any actual logical
drop. If raw fallback itself cannot be finalized, the operation must surface
an internal error and a classified drop rather than silently losing data.

## Required integration adjustments

- Store the selected frame and payload sizes per packet record. Replace the
  packet and USB fixed-size guards with version/negotiation-aware bounds while
  leaving v1 checks exact. Use the selected length for pressure eligibility,
  gap checksum repair, partial-write pinning, transmitted byte counters, and
  final release.
- Preserve logical fairness and sequence/timestamp/drop arithmetic. Add actual
  raw logical bytes, selected payload bytes, complete-wire bytes, RAW/RLE
  counts, run counts, fallback reasons, temporary-page high water/exhaustion,
  encode cycles, and encode failures as saturating v2 telemetry.
- Keep the v1 parser, `encodeDataFrameInPlace()`, configuration defaults,
  generated files, fixtures, and fixed-size STATUS byte-for-byte unchanged.
  The v2 control path must route explicitly on version and reject unsupported
  selectors/states before mutating configuration.
- A RAW frame during `RLE_AUTO` does not prove that RLE was merely too large:
  page pressure or a counted encoder failure may also force safe fallback.
  Host per-frame diagnostics must use a reason that does not infer more than
  the selector reveals; v2 STATUS supplies aggregate reason counts.
- Extend the existing source-service, packet-pressure, USB partial-write,
  reconnect, STOP/rollback, cache-boundary, `sizeof`, resource-registry, map,
  and exact-v1 tests. The target build must still report both packet banks as
  exactly 105/95 aligned pages and must retain the RAM1 local/stack gate.

This choice keeps RLE interpretation, sizing, record construction, checksum,
queue mutation, and cleanup in bounded cooperative context. It also keeps the
raw compatibility path structurally independent: v1 never requests a
temporary page and continues through its existing fixed-frame finalizer.

## Alternatives considered

### Reuse a checksum-benchmark buffer

The target already links one 4,096-byte checksum-benchmark buffer in DTCM and
one in OCRAM. Benchmark commands are IDLE-only, so either allocation could be
given a mutually exclusive scratch lease without increasing linked memory.
It was not selected because the encoded frame cannot remain in this single
benchmark page while later frames queue for USB. The finalizer would have to
copy every selected encoded frame back over its now-fully-read raw packet page,
adding another near-frame-sized pass and coupling packet recovery to a
diagnostic owner. The existing packet pool gives the selected frame its normal
long-lived owner directly; pressure simply selects safe RAW fallback.

### Encode over the source page

Forward encoding can overtake unread input because an RLE record adds a
two-byte prefix, even when the complete result will eventually be smaller.
Backward or compacting schemes make overlap proofs and injected-failure
recovery depend on record distribution. They are rejected by the explicit
read-only-input rule.

### Encode directly from ADC and GPIO source rings

ADC DMA and packed GPIO buffers could serve as raw inputs while one packet page
receives the selected result. That would avoid a temporary packet page for
physical sources, but it would extend DMA/packer lease lifetimes through
compression, require a different synthetic path, and duplicate finalization
ownership. Keeping the common packet page as the raw compatibility boundary
preserves the accepted packers and one source-independent failure model.
