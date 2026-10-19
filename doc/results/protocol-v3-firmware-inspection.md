---
type: analysis
title: Phase 03 firmware contract and codec reuse inspection
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - compression
  - regression
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-python]]'
  - '[[deferred-codecs-20261018]]'
  - '[[usb600-autoflush-20261018]]'
  - '[[gpio-rle600-etc-fixed-20261018]]'
---

# Phase 03 firmware contract and codec reuse inspection

Inspected revision: `12bdc1a`. This completes only the first Phase 03 task:
trace the existing implementation, record reuse boundaries and preserve its
regression baseline. The worktree was clean on entry. `AGENTS.md` requires
validated commits and normal pushes to `origin/main`; no `CLAUDE.md` or nested
agent instructions were present. No task images were supplied or analyzed.
Production code, generated contracts and build selections are unchanged.

## Implementation to extend

Paths below are relative to `firmware/src/`.

| Surface | Existing implementation and reuse boundary |
| --- | --- |
| Wire contract | `protocol.cpp`: reuse checked little-endian loads/stores, header/payload validation, checksums, typed errors, response serializers and `IncrementalCommandParser`. `decodeRequest` rejects v1 in fixed-1-MHz release builds. The parser and public serializers currently accept v1/v2 only; generated v3 constants exist separately. |
| Control | `control_state.cpp`: `dispatch` validates configuration and readiness before committing, encodes responses before transitions, rejects recent duplicate IDs, and emits START/STOP events. INFO is a query. Existing STOP clears configuration and returns IDLE; v3 settings retention and drain-visible state still need implementation. |
| Runtime | `firmware_runtime.cpp`: reserves response capacity, computes quiescence/readiness, dispatches commands, applies acquisition events before admitting successful START, and recovers response failures. Services physical acquisition twice around bounded packet/USB work, then services deferred codecs. Extend this integration point rather than creating another loop. |
| Acquisition | `acquisition_controller.cpp`: `runLayout`, `inspect`, `readyForStart`, START reservation, rollback, common trigger ownership, STOP and drain compose the existing ADC/GPIO adapters. START reserves one run/epoch before mutations; combined GPIO DMA prepares before the ADC scheduler arms the common clock. Configuration-time hardware application/readback is not yet a separate transactional adapter. |
| Packet ownership | `packet_buffer_pipeline.cpp`: reuse fill handles, producer-lease invalidation, per-stream FIFOs, fair promotion, protected transmitting buffers, eviction, gap propagation and drain. `finishFill` retains complete deferred pages as FILLING in FIFO order; `publishReady` releases them only after encoding. |
| USB | `usb_transport.cpp`: bounded receive/transmit budgets, command/response reservation, partial-frame offsets, immutable active views and session cleanup already exist. `validDataView` includes explicit private RLE/PACK12 shapes; `queueResponse` independently decodes and checks control responses. Both guards need deliberate v3 support. |
| ADC acquisition packing | `adc_frame_packer.cpp`: copies acquired DMA pairs into a packet lease, derives timestamps from pair position and selected period, projects raw gaps, releases DMA handles even on expected pool pressure, and keeps logical item accounting. Compression belongs after this acquisition service. |
| GPIO acquisition packing | `gpio_batch_packer.cpp`: reuses `packGpio2Batch`, bounded raw-buffer service, chronology/gap checks, packed-buffer ownership and STOP-tail accounting for 8 inputs. `gpio_dual_bank_packer.cpp` is the existing 16-input counterpart selected by the controller. |
| Layout and metadata | `stream_layout.h` separates logical count/width/period/coverage, but computes frame bytes as RAW plus the legacy envelope and validates only v1/v2. `firmware_capabilities.h` builds static legacy metadata; `input_experiment_profile.h` and `rate_profile_table.h` still couple build selections to layouts and metadata. |
| GPIO codec | `rle_encoder.h/.cpp`: reuse checked sizing, adaptive early RAW selection, canonical maximal runs, disjoint-output validation and the measured `encodeHybrid16` implementation. Generic `encode` already supports caller-described widths; the packet integration currently selects only GPIO16. Sizing currently includes a 48-byte legacy envelope. |
| ADC codec | `PacketBufferPipeline::packAdc12` validates every code's upper bits before in-place packing, preserving pair count and rebuilding the checksum. It currently writes private version `0x83`; GPIO compression writes `0x82`. Retain the packing algorithm, replace public framing explicitly. |
| Deferred work | `serviceDeferred` alternates sources, searches past blocked READY predecessors, expires deadlines even with zero work budget, and encodes at most one block per opportunity. `deferred_codec.h` owns per-stream counters and private request-ID diagnostic pages. Public v3 diagnostics must reuse these counters through the generated contract. |

## Regression invariants to preserve

- **USB autoflush:** `teensy_usb.cpp` masks only `IRQ_USB1` around capacity
  checks/writes, uses barriers, restores prior enable state and preserves pending
  IRQs. Capacity is rechecked under the mask; `kWriteWouldBlock` retains the
  transport offset without reporting an attempted-write failure. DMA remains
  enabled. [[usb600-autoflush-20261018]] retains the actual corrupt-byte fixture
  and deterministic race diagnosis; keep the adapter and 24-byte-tail tests.
- **Checked indices:** `validFrameSize(BufferIndex)` checks bounds and reads
  live storage by that index. `evictCompleteBuffer` may copy the record, but
  passes the explicit index. Never derive an index by subtracting a copied
  record's address from the live record array. [[deferred-codecs-20261018]]
  ties that former defect to a captured memory fault and a deterministic
  compressed-page eviction regression.
- **ADC request route:** `input_experiment::kAdcEtcRequest` currently depends
  on the private RLE build flag. `adc_dma_capture_teensy.cpp` selects ADC_ETC
  source 23 for ADC1, enables trigger 4 and selects ACK-cleared DMA mode while
  retaining ADC2_R0. Removing experiment flags must retain this qualified route
  and truthful metadata. [[gpio-rle600-etc-fixed-20261018]] records 64 passing
  cells and negative controls with progressive loss on the old route.
- **Acquisition timing:** retain the ITCM helper in `adc_trigger_teensy.cpp`
  that enables timers, reads back and enters DONE polling without a cold-flash
  boundary. Preserve common-epoch arming, interrupt ownership, stop-at-boundary,
  rollback and tail drain. [[gpio-rle600-boot-timing-failure-20261018]] records
  why timer-enable placement matters; its failed capture remains a failure.
- **Deferred deadlines and memory:** retain the 80,000-tick (10 ms) deadline,
  unsigned-wrap handling, late-completion rejection, deadline/resource counters,
  sequence gaps and complete-page STOP drain. RLE borrows a disjoint FREE pool
  page without producer admission/eviction; PACK12 packs in place. Never mutate
  a page after USB begins transmitting or allocate another full frame buffer.
- **Evidence limits:** [[clock600-ready-endurance-20261018]] records 18 passing
  ten-minute sessions; [[stop-recovery600-20261018]] records 42 ordinary
  lifecycle cells; [[large-adc600-20261018]] records eight larger-frame cells.
  [[deferred-codecs-20261018]] records 28 private-codec captures including
  thirty minutes with both codecs. These are historical, identity-pinned,
  unstimulated-input results, not public-v3 or runtime-clock qualification.
  Failed earlier campaigns and disabled-watchdog status remain unchanged.

## Boundaries for subsequent tasks

1. Extend the generated v3 contract through the existing parser/control/runtime
   path. Separate board support, build defaults, active settings and negotiated
   mode; advertise only configurations the production adapter can actually
   apply. A portable fake's clock readback is not hardware evidence.
2. Preserve explicit v2 RAW layouts independently of the private larger-frame
   multiplier: 8-input ADC has 1,012 pairs; 16-input release ADC has 506 pairs.
   The qualified private layout doubles the latter to 1,012. Read-only INFO
   must not switch mode; configuration must await all old data/codec/USB drain.
3. Account for the v3 12-byte encoding prefix before selecting frame sizes.
   Its maximum frame is 4,108 bytes, while current packet pages are 4,096 bytes
   in a fixed 200-page pool. Existing `CommandFrame`, `ControlFrame` and parser
   storage use v2 bounds; v3 limits are 68-byte commands and 2,048-byte control
   frames. Reconcile storage, layout and state/resource assertions explicitly;
   do not silently increase the pool or copy reference capability limits.
4. Keep logical item counts/coverage distinct from selected wire length across
   shape guards, queue accounting, retention and STATUS. RLE's current 48-byte
   sizing envelope must account for the v3 prefix; ties remain RAW. Extend
   packet integration to both GPIO widths using the existing generic codec.
5. Preserve legacy diagnostics while exposing public codec counters. Extend
   duplicate/state tests and add actual C++ control-to-public-Python decoding;
   the current private experiment decoder alone cannot establish v3 correctness.

## Existing tests to reuse

All paths are under `firmware/tests/` unless otherwise stated.

| Concern | Existing coverage |
| --- | --- |
| Deferred ownership and encoding | `test_deferred_codec.py` compiles four RLE/PACK12 combinations, sends actual CdcTransport output through seven-byte writes, independently decodes samples and checks private lengths. Its C++ harness covers deadlines, wraparound, blocked predecessors, scratch exhaustion, eviction, STOP drain and invalid ADC upper bits. |
| GPIO codec | `test_gpio_rle.py`, `gpio_rle_test.cpp`, `test_rle_performance.py`: exact static/bursty/noisy patterns, RAW fallback, malformed runs, corruption, checksum/ownership checks, request-route metadata and bounded START buffering. |
| Control | `test_control_state.py`: legal transitions, atomic rejection/busy readiness, duplicates, session-scoped IDs, recovery and statistics. `test_firmware_runtime.py` covers event/response ordering and failure recovery. |
| USB and pressure | `test_usb_transport.py`: target IRQ guard and bounded transport ownership. `test_pressure_recovery.py`: every partial-frame offset, small capacities, pool pressure, parser recovery, illegal states, duplicate IDs and START/STOP/reopen races. |
| Acquisition and resources | `test_adc_frame_packer.py`, `test_gpio_batch_packer.py`, `test_combined_acquisition.py`, `test_adc_dma_interrupt_order.py`, `test_adc_register_adapter.py`, `test_packet_buffer_pipeline.py`, `test_firmware_identity_resources.py`, `test_portable_source_boundaries.py` and build-configuration tests. |

Use the existing host-compiled harnesses and their strict compiler flags;
several enforce `-Wconversion`, `-Wsign-conversion`, `-pedantic`, no exceptions
and no RTTI. This inspection introduces no production behavior requiring a new
test. Later implementation tasks own new behavioral cases.

## Validation

Commands run from the repository root:

```bash
mkdir -p .maestro/playbooks/Working/phase03-inspection-tmp
TMPDIR="$PWD/.maestro/playbooks/Working/phase03-inspection-tmp" .venv/bin/python -m pytest firmware/tests -q -ra
TMPDIR="$PWD/.maestro/playbooks/Working/phase03-inspection-tmp" .venv/bin/python -m pytest daq_api/tests/test_repository_layout.py daq_api/tests/test_documentation_integrity.py -q
.venv/bin/python tools/generate_protocol.py --check
git diff --check
```

- Firmware suite: **406 passed, 3 skipped, 838 subtests passed in 121.55 s**.
  All three skips are fixed-rate-policy/equal-rate override combinations in
  `test_input_rate_clock.py`; no firmware test failed.
- Documentation/layout: **8 passed, 1,134 subtests passed in 1.81 s**.
- Generator: all **142 outputs current**. Whitespace check passed.

Logs are local ignored operator state under `.maestro/playbooks/Working/`:
`phase03-inspection-tests.log` and `phase03-inspection-docs.log`. The Phase 03
playbook checkbox and completion note are also ignored operator state; this
tracked report preserves the findings and validation in Git.

No hardware was accessed or firmware flashed for this inspection. These results
establish the existing portable baseline, not public-v3 firmware support.
