---
type: report
title: Protocol v3 execution foundation
created: 2026-10-19
tags:
  - protocol-v3
  - offline
  - baseline
related:
  - '[[protocol-v2]]'
  - '[[python-api]]'
  - '[[deferred-codecs-20261018]]'
---

# Protocol v3 execution foundation

This records only the first Phase 01 task: repository orientation, reuse
boundaries, and the pre-change baseline. No v3 contract or implementation is
introduced. Baseline revision: `3a52ead02791019fcdb0b27a8be869effc955aa2`.
The tracked worktree was clean on entry; `AGENTS.md` requires validated commits
and normal pushes to `origin/main`. No `CLAUDE.md` was present.

## Environment

Reused `.venv` with Python 3.12.3 and the existing editable
`thingdone-daq==1.1.0` installation pointing at this checkout's `daq_api`.
An import check resolved `thingdone_daq` to `daq_api/src/thingdone_daq/__init__.py`.
No dependencies were installed, removed, or upgraded.

| Tool/dependency | Installed version |
| --- | --- |
| pytest | 9.1.1 |
| Ruff | 0.16.5 |
| mypy | 2.3.1 |
| build | 1.6.0 |
| twine | 7.0.0 |
| pyserial | 3.5 |
| types-pyserial | 3.5.0.20260712 |
| NumPy | 2.5.2 |

`python -m pip check` passed. Historical editable distributions
`teensy-daq-local` and `thingdaq-local` also exist in this environment and were
preserved. The latter points to an old ignored working copy; it does not own
the current `thingdone_daq` import.

## Baseline validation

Commands run from the repository root:

```bash
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m pytest
.venv/bin/python -m pytest daq_api/tests firmware/tests
```

- Generator check: PASS, all 111 generated outputs current.
- Bare pytest: collection failed with 829 errors after traversing historical
  copies in ignored `benchmark-scratch/`. Duplicate test module names caused
  import mismatches; an old copy also imported the historical SDK namespace.
  This is retained as a baseline failure, not relabeled as a passing gate.
- Explicit tracked test directories: 790 passed, 3 skipped, 2 failed in
  158.59 seconds. Both failures were missing YAML front matter in
  `doc/research/deferred-codecs.md` and
  `doc/results/experiments/deferred-codecs-20261018.md`.

Added only the required front matter to those two inspected reference documents,
preserving their content and original creation date. The affected gate is
`.venv/bin/python -m pytest daq_api/tests/test_repository_layout.py`:
4 passed in 0.04 seconds after the fix. Its log is
`.maestro/playbooks/Working/phase01-layout-validation.log`.
No new test was needed for metadata already covered by this regression test.

Use the explicit test directories for subsequent runs in this workspace;
`git ls-files '*test*.py'` identifies only `daq_api/tests` and `firmware/tests`
as tracked test locations. This preserves the scratch work and exercises both
current test suites. Logs are local, ignored artifacts under
`.maestro/playbooks/Working/phase01-{generator,pytest,tracked-pytest}-baseline.log`.
No target firmware build, device access, or physical qualification was performed.

Canonical source SHA-256 values before changes:

| Source | SHA-256 |
| --- | --- |
| `protocol/protocol-v1.json` | `014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222` |
| `protocol/protocol-v2.json` | `1596bab522a711aa7980b0187d157b550d9ec8f69049d9961c579b1ef2cc9c48` |

All 111 actual generated files also matched the generator's expected bytes.
A sorted manifest (`sha256`, two spaces, repository-relative path, newline)
is retained locally at
`.maestro/playbooks/Working/phase01-generated-sha256.txt`; its SHA-256 is
`130f84398661a726583665f2a73017f41401ef8ad7b985e6f2bcf30bca1a1a12`.

## Reuse map

Paths below refer to existing implementations, not proposed replacements.

| Surface | Reuse point and boundary |
| --- | --- |
| Contract generation | `tools/generate_protocol.py`: `load_contract`, duplicate-key rejection, enum/field validators, version-specific rendering and fixture generation, source hashes, and `check_outputs`. Extend version dispatch while preserving the existing v1/v2 output union. |
| Existing wire contract | `protocol/protocol-v1.json` and `protocol/protocol-v2.json`: little-endian 44-byte header, 4-byte checksum trailer, correlated requests, run IDs, and 8 MHz timestamps. Control frames use Adler-32. V2 has historical profile definitions distinct from the release's selectable 1 MHz/1 MHz profile. |
| Client lifecycle | `daq_api/src/thingdone_daq/client.py`: `ThingDAQ.simulated` constructs `SimulatedDevice` and `InMemoryTransport`, then uses ordinary `open`/synchronization. Reuse exact CONFIGURE/START echo checks, capability validation, reader queues, STOP/drain, and cleanup. |
| Simulator | `daq_api/src/thingdone_daq/simulator.py`: bounded encoded requests/responses, replay detection, state handlers, round-robin streams, sequence numbers, and timestamps. Current STOP clears configuration; persistent v3 settings need an explicit persona boundary. |
| Transport/parser | `transport.py` provides chunked, bounded `InMemoryTransport`; `protocol_v2.py` provides compatible version dispatch. Reuse `_incremental.py`'s `BoundedIncrementalParser` and `checksum.py` rather than creating another serial/parser stack. |
| Models | `models.py`: `DAQConfiguration`, capability/timing models, `decode_response`, `decode_message`, `ADCBlock`, and `GPIOBlock`. Current blocks explicitly accept only versions 1/2 and validate fixed decoded shapes; extend deliberately while retaining sample access and loss semantics. |
| Synthetic inputs | `synthetic.py`: deterministic ADC formulas, per-bank GPIO patterns including all-zero and high-transition inputs, cached payload generation, and exact validators. |
| Examples/tests | `daq_api/examples/simulator.py`, `_common.py`, `aux_input_matrix.py`; `test_simulator_api.py`, `test_transport_reader.py`, `test_examples.py`, `test_protocol_contract.py`, `test_protocol_generation_drift.py`, and `test_protocol_vectors_exhaustive.py`. |

Existing request IDs occupy `0x10..0x1B`, responses `0x90..0x9B`, and generic
ERROR is `0x9F`; data kinds are `0x01/0x02`. The next contract task must check
all definitions before allocating new IDs; this foundation allocates none.

## Tested codec behavior and private boundary

Read `firmware/src/input_experiment_profile.h`, `rle_encoder.h`,
`deferred_codec.h`, the codec paths in `packet_buffer_pipeline.cpp`, and
[[deferred-codecs-20261018]]. Also inspected `rle_encoder.cpp` and existing
portable/independent decoder tests for reusable byte-level behavior.

- Private GPIO RLE frames use version `0x82`; packed ADC uses `0x83`.
  RAW fallback and control frames retain v2. Public compatible parsers reject
  these private versions. A public v3 discriminator must be specified separately.
- RLE records contain a little-endian unsigned 16-bit run length followed by
  one logical item's bytes. The portable codec accepts a bounded item shape;
  the measured pipeline uses the 16-bit hybrid encoder. Sizing precedes encoding,
  and RLE is selected only when the complete frame is strictly smaller than RAW;
  ties fall back to RAW. New 8-bit support should reuse these semantics.
- ADC packing validates all values fit 12 bits before modifying input. For
  logical pair `(a, b)` in ADC0/ADC1 order, bytes are `a & 0xff`,
  `(a >> 8) | ((b & 0x0f) << 4)`, and `b >> 4`. Logical count and timestamps
  remain unchanged; the checksum is recomputed over the transmitted header
  and payload.
- The cooperative deferred worker handles at most one block per idle
  opportunity. Its 80,000-tick deadline is 10 ms in the 8 MHz domain;
  deadline/resource failures drop whole blocks with counters and gap semantics.
  Private diagnostic pages do not change ordinary STATUS.
- `firmware/tests/test_deferred_codec.py` exercises all four RAW/RLE/PACK12
  combinations through compiled portable components and an independent decoder.
  `firmware/tests/rig_aux_input_capture.py` already supplies bounded byte-lane
  `decode_adc12` and `decode_gpio_rle`; use their vectors and checks as reference,
  without importing a rig runner into the public SDK.

The existing experiment report records 600 MHz, 1 MHz/1 MHz qualification of
private builds. It is historical algorithm evidence, not qualification of the
future public v3 API or a reason to advertise 528 MHz or other rate pairs.
