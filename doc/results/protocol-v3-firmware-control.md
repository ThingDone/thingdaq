---
type: report
title: Firmware v3 control contract and settings checkpoint
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - portable-tests
  - settings
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-firmware-inspection]]'
  - '[[protocol-v3-python]]'
---

# Firmware v3 control contract and settings checkpoint

This completes the second task in Phase 03, building on
[[protocol-v3-firmware-inspection]]. No task images were supplied or analyzed.
No hardware was accessed or flashed. Runtime clock switching, complete v2/v3
transactional acquisition, and public compressed data emission remain later
playbook tasks. V3 START intentionally rejects acquisition until that integration
exists; its successful settings serializer is checked against the golden frame.

## Implemented surface

- `firmware/src/protocol.cpp` and `protocol.h`: all v3 control IDs, bounded
  framing, reserved fields, enums, exact payload lengths, scalar/tuple error
  distinction, serializers and correlated errors. Untrusted v3 checksums and
  lengths are discarded before any reflected response. Legacy validation and
  private data encodings remain intact.
- `firmware/src/v3_settings.h` and `control_state.*`: generated board records,
  separate build defaults, active settings and negotiated mode; injectable
  application/readback interface. Production advertises only twelve RAW tuples
  at the compiled clock. The fake adapter exercises all sixty canonical tuples
  and both clocks without claiming hardware evidence. Queries never apply
  settings, reset counters, allocate runs or signal acquisition events.
- `firmware_runtime.cpp`, `usb_transport.*`, `packet_buffer_pipeline.*`:
  admission of new response IDs, current run IDs on malformed-command errors,
  and pending counts that include complete deferred pages and USB tails.
- `board_config.h`: 68-byte commands, 71-byte parser retention accounted as
  72 aligned bytes; existing 1,536-byte control buffers and 4,096-byte packet
  pages retained. Corrected old v1 accounting for command/response buffer slots
  brings the static RAM1 reservation from 446,372 to 447,448 bytes. Packet-pool
  counts and acquisition/USB ownership are unchanged.
- Contract/SDK correction: permit bounded device limits and build defaults in
  the advertised tuple subset. All existing golden frame bytes remain unchanged;
  only generated contract source hashes change. The Python capability model
  preserves the received limits and rejects inconsistent capacities.

The current storage ceilings are 4,036 sample bytes after public prefix overhead,
1,009 ADC pairs, 4,036 GPIO8 samples and 2,018 GPIO16 samples. Actual per-run public
layouts are deferred to the layout task, as described in [[protocol-v3-upgrade]].

## Validation

`firmware/tests/test_v3_control_contract.py` compiles the production parser,
control state, statistics and checksum units with strict warnings, no exceptions
and no RTTI, for both 450 and 600 MHz builds. It feeds requests one byte at a
time, then parses emitted responses in seven-byte chunks with the public Python
SDK. Coverage includes every advertised tuple, typed/generic errors, scalar and
reserved-field mutations, unknown commands, framing recovery, exact settings
readback, fake application failures/mismatches, query availability while legacy
acquisition is running/draining, non-mutating discovery and the START golden
serializer. The existing deferred-codec harness checks pending-frame counts
before encoding and after STOP drain.

Commands from the repository root:

```bash
TMPDIR="$PWD/.maestro/playbooks/Working/phase03-contract-tmp" .venv/bin/python -m pytest firmware/tests daq_api/tests -q -ra
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python tools/generate_protocol.py --check
git diff --check
```

- Full firmware/Python regression: **1,751 passed, 3 expected skips, 16,757
  subtests passed in 206.85 s**. Skips are the existing unsupported fixed-rate /
  equal-rate override combinations.
- Runtime/USB integration also passed separately: **2 passed, 13 subtests**.
  All seven controls traverse the runtime and response queue with seven-byte
  writes; only START returns the intentional acquisition gate.
- Ruff format/check passed across 192 files; mypy passed across 33 source files.
- Generator: all **142 outputs current**. Whitespace check passed.

The first complete run exposed two obsolete assertions: version 3 was used as
an unknown-version negative control, and the resource test pinned the old
under-accounted buffer total. Negative controls now use unsupported version 4;
the resource assertion pins the corrected total and retains the RAM budget
limit. Both gates passed in the final full run.

Logs remain ignored operator state under `.maestro/playbooks/Working/`, including
`phase03-contract-final.log` and `phase03-runtime-v3.log`. RAM figures above are
static resource-registry reservations, not a new target linker-map or physical
measurement. Physical clock, acquisition and codec qualification are unchanged.
