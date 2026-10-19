---
type: report
title: Transactional firmware configuration and legacy v2 sessions
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - transactions
  - compatibility
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-firmware-control]]'
---

# Transactional firmware configuration and legacy v2 sessions

Completes the third Phase 03 task. No hardware was accessed or flashed; no task
images were supplied or analyzed. Public-v3 acquisition remains gated until the
following codec/layout work. This checkpoint implements configuration transactions
and mode isolation, not public-v3 data emission or physical qualification.

## Changes

- Full candidate validation and quiescence precede application. Responses are
  serialized before application; settings and mode are committed only after exact
  settings/clock readback. Failure or mismatch reapplies the previous complete
  record and verifies restoration. Failed restoration prevents START and settings/
  clock reporting until a successful configuration repairs it.
- Legacy v2 CONFIGURE selects RAW, historical ADC/GPIO frame counts, the compiled
  clock baseline, and the historical ADC2 request route. The private large-ADC,
  GPIO RLE and ADC PACK12 paths cannot leak into a publicly configured v2 run.
  The qualified ADC_ETC route remains available to explicit experimental layouts;
  the target adapter selects the legacy route only before preparing a stopped run.
- V2 INFO uses historical counts and profile coverage while preserving actual
  build-clock scaling of cycle metadata. Its capability bits are restricted to
  the v2 mask. Public v2 STATUS omits private appended diagnostic words.
- Synthetic data generation now uses the selected per-stream sample counts,
  payload lengths and coverage, including 16-bit GPIO samples. It no longer
  assumes the v1 layout for all sessions.
- Queries never negotiate a mode. Pending lifecycle events and runtime resource
  ownership prevent mode changes before drain. Cross-version lifecycle commands
  cannot operate a configured run in another mode; STOP cancels an unconsumed
  START. Replay handling preserves the contract's last-16-ID window, including
  errors, with explicit reset on a new host connection. Older IDs outside that
  window have no replay guarantee, as specified in [[protocol-v3]].
- Historical non-release v2 rate profiles retain their scheduler. Their rates
  cannot be represented as public-v3 GET_SETTINGS records and receive
  UNSUPPORTED_CONFIGURATION there. A 528 MHz research build remains v2-only.

The fixed-build application still changes software selections only. Future
hardware adapters must implement synchronous application/readback through the
same interface. Rollback tests use a stateful fake and establish no physical
clock-switching evidence.

## Validation

`test_v3_control_contract.py` exercises successful application, partial failure,
mismatched readback, restoration failure/recovery, busy drain, running rejection,
mode probes, duplicate START/CONFIGURE and stale IDs across mode changes. Existing
release/health harnesses now consume STOP events or provide matching request and
configuration versions, matching the actual parser/runtime contract.

`test_legacy_v2_session.py` reuses the complete runtime harness and portable source
list. It runs both GPIO widths on the 450 MHz release build and a 600 MHz build
with larger ADC frames, deferred GPIO RLE and ADC PACK12 enabled. Three-byte reads
and seven-byte writes exercise the real parser, runtime, synthetic producer,
packet pipeline and USB queues. Public Python parsers and typed readers decode
all emitted INFO/STATUS/control replies and RAW frames in five-byte chunks. Tests
check exact independent sample expectations, sequence/timestamps, two run IDs,
legacy USB-tail BUSY rejection, successful post-drain reconfiguration and the
unchanged UNSUPPORTED_VERSION response to a release v1 request.

All seven changed target translation units were also cross-compiled with the
installed Arm GNU 15.2.1 toolchain and Teensy 1.62.0 headers for 450 MHz release
and 600 MHz private-codec variants. This is object compilation, not a new linked
image, linker-map memory measurement or hardware test. Packet pool sizes and
USB/DMA ownership mechanisms were not changed.

Final validation:

- Full firmware/Python regression: **1,757 passed, 3 expected skips, 16,759
  subtests passed in 214.10 seconds**. Skips remain the unsupported fixed-rate /
  equal-rate override combinations.
- Final focused control/runtime/session tests: **100 passed, 24 subtests**.
- Documentation integrity: **4 passed, 1,031 subtests**.
- Ruff format/check passed across **193 files**; mypy passed across **33 source
  files**; all **142 generated outputs** are current; whitespace checks passed.

```bash
TMPDIR="$PWD/.maestro/playbooks/Working/phase03-transaction-tmp" .venv/bin/python -m pytest firmware/tests daq_api/tests -q -ra
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python tools/generate_protocol.py --check
git diff --check
```
Logs and target objects are ignored operator artifacts under
`.maestro/playbooks/Working/phase03-*`.
