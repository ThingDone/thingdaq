---
type: report
title: Public v3 deferred codec policies on bounded packet storage
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - codecs
  - portable-validation
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-firmware-transactions]]'
---

# Public v3 deferred codec policies

Completes the fourth Phase 03 task: public codec settings and packet encoding.
No hardware was accessed or flashed. No task images were supplied or analyzed.
Public-v3 START remains gated until the next acquisition-layout/transport task.

## Implementation

- The fixed-clock adapter advertises all 48 generated 600 MHz tuples, with
  RLE_AUTO/PACK12 build defaults, and the 12 RAW-only 450 MHz tuples. Unsupported
  clock/policy/rate combinations still fail table membership. Legacy CONFIGURE
  explicitly clears both policies rather than inheriting compressed defaults.
- `stream_layout::publicV3` captures validated settings and caller-supplied
  logical counts. Packet producer views contain decoded samples after the
  generated 12-byte prefix. Packet pages remain 4096 bytes: at most 1009 ADC pairs,
  4036 GPIO8 samples or 2018 GPIO16 samples. This is a storage constraint, not the
  selection of production DMA block sizes.
- Deferred selection uses immutable per-run policies. Public frames always use
  version 3, explicit RAW/GPIO_RLE/ADC_PACK12 encoding, item width, decoded bytes
  and RLE record count. Logical item counts, timestamps and coverage survive
  compression. Public checksum selection is Adler-32 only, per the contract.
- GPIO8 reuses the existing generic encoder; GPIO16 reuses the qualified hybrid
  implementation. The sizing pass selects RLE only when the complete frame is
  strictly smaller than RAW. Both candidates include the same public prefix, so
  the existing sizing ceiling comparison is preserved. Ties and incompressible
  samples publish RAW. RLE borrows one FREE pool page; it never allocates storage
  or evicts a page to acquire scratch space.
- ADC reuses the existing lossless in-place packing. Both RAW publication and
  PACK12 reject input outside 12 bits; PACK12 validates before overwriting input.
- The existing complete-but-FILLING FIFO, invalidated producer leases, immutable
  READY/TRANSMITTING pages, deadline/resource drops, sequence-gap flags and
  STOP-tail drain remain. Runtime codec service now runs without experiment
  defines, after acquisition and USB, at most one block per idle opportunity.
  The 80,000-tick deadline still expires with zero work budget.
- Public-v3 hardware mode can select the qualified ACK-cleared ADC_ETC request
  independently of private codec flags. Legacy v2 retains ADC2. Request ownership,
  pulse mode and stop/drain cleanup no longer depend on GPIO-RLE experiment
  compilation. Private A/B probes and private wire adapters remain available.

## Portable evidence

`test_v3_codec_pipeline.py` compiles the production packet path both without
experiment flags and with all private codec flags enabled. Each executable emits
128 public packets spanning both widths, four policy combinations, constant,
incompressible, tied and profitable patterns, and small/maximal page capacities.
The public Python parser reads seven-byte chunks and validates independent exact
sample expectations, prefix encoding, item count, timestamp, checksum and total
wire length. This exercises packet output directly, not the runtime USB guard.

The C++ harness additionally checks zero-budget deferral, invalidated producer
leases, complete STOP tails, deadline boundary and uint32 wrap, late completion,
resource exhaustion, gap propagation, transmitting-byte immutability, bad ADC
input, oversized layouts, unsupported 450 MHz policies and v3 CRC rejection.
Control tests apply every advertised fixed-build tuple and verify defaults and
settings echoes. Existing private-codec and legacy-v2 tests remain in the suite.

All eight relevant target translation units compile with Arm GNU 15.2.1, Teensy
1.62.0 headers, the repository identity definitions and standard O2 at both
450 MHz and 600 MHz, without private codec defines (16 objects). This is object
compilation, not a linked-image memory measurement or physical qualification.
Existing packet/state/memory static assertions remain enabled.

## Remaining integration

The next task owns actual acquisition block sizes, larger ADC layout selection,
encoded USB shape guards, coverage/retention metadata and public codec counters.
Public-v3 START must remain gated until those agree. Runtime clock switching and
physical throughput/loss qualification are also outstanding. Historical results
in [[protocol-v3-firmware-transactions]] remain the legacy compatibility baseline.

## Validation results

- Full firmware/Python regression: **1759 passed, 3 expected skips, 16,765
  subtests** in 224.71 seconds. Skips are the existing fixed-rate/equal-rate
  override exclusions.
- Focused public control/codec checks: **94 passed**. Final RAW-fast-path,
  private-codec, public-codec, runtime, packet and legacy-session checks:
  **16 passed, 29 subtests**.
- Documentation integrity: **4 passed, 1036 subtests**.
- Ruff format/check passed across 194 files; mypy passed across 33 source files;
  all 142 generated outputs are current; whitespace checks passed.
- Final target object compilation: **16 passed** at 450/600 MHz.

```bash
TMPDIR="$PWD/.maestro/playbooks/Working/phase03-codecs-tmp" .venv/bin/python -m pytest firmware/tests daq_api/tests -q -ra
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python tools/generate_protocol.py --check
git diff --check
```

Logs, temporary executables and target objects are ignored operator artifacts
under `.maestro/playbooks/Working/codecs-*` and `phase03-codecs-*`.
