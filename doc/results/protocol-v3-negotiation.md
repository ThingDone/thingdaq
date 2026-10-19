---
type: report
title: Bounded Python wire negotiation and session continuity
created: 2026-10-19
tags:
  - protocol-v3
  - python
  - compatibility
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-python-inspection]]'
  - '[[api-reference]]'
---

# Bounded Python wire negotiation and session continuity

This report covers only Phase 02's negotiation task. Public metadata expansion,
codec optimization, CLI integration and performance coverage remain separate
playbook tasks. No physical hardware validation or image analysis was performed.

## Policy

`negotiation.InfoNegotiation` is shared by physical discovery and `ThingDAQ`
synchronization, including fresh sessions after reconnect. It probes public v3
first. Only an explicit `UNSUPPORTED_VERSION` permits another version: v1 next
to preserve historical defaults, then v2 for release firmware rejecting v1.
Private versions 0x82/0x83 are never attempted.

Each rejection must match the pending request ID. A typed rejection must use
the requested wire version and INFO response kind. A generic legacy rejection
must echo both INFO's command kind and the rejected version. This matches
`firmware/src/protocol.cpp`'s `encodeRejectedFrameResponse` and
`IncrementalCommandParser::describeRejection`. The policy has no historical
exception for INVALID_LENGTH, silence, checksum damage or invalid metadata.

The normal reader still rejects response wire-version changes. Only an INFO
probe explicitly marked as negotiating can consume a cross-version rejection.
Successful unrelated or stale frames cannot select a version. Session and
discovery readers randomize the initial nonzero request ID; subsequent IDs remain
monotonic, avoiding deterministic collisions with buffered replies after reopen.
This is correlation, not authentication.

Discovery checks physical board/MCU and USB serial continuity, then closes its
reader and transport. It sends INFO only, without changing configuration, clocks,
run state or encoding. Opening a discovered endpoint verifies its pinned identity
again and requires two stable INFO responses before session recovery. V3 keeps
its ASCII identity fields and explicit simulated marker; legacy physical identity
checks remain unchanged.

## Bounds and lifetime

- A negotiation exchange shares one command/discovery deadline across at most
  three version probes. Retries retain the currently selected version.
- Open defaults to four synchronization attempts with 50 ms retry delays. At
  most six INFO writes occur across those attempts, because each fallback edge
  can be taken only once. The INFO time budget is at most
  `attempts * command_timeout + (attempts - 1) * retry_delay`.
- After stable v3 identity, capabilities, settings and status each have the
  command timeout. Existing STOP/drain and transport-close deadlines apply to
  recovery and cleanup separately. No retry closes/reopens the port.
- The existing compatible parser bounds retained bytes to the largest supported
  frame plus the three-byte magic suffix. Reader chunks, decoded queues and
  pending requests retain their explicit limits. Discovery permits one pending
  request and one queued block/event. Nonfinite deadlines are rejected.
- CONFIGURE latches the wire version. INFO and STOP no longer reset it; subsequent
  configuration/restart keeps the selected version. Stopped v2 status preserves
  counter layout and rate metadata without claiming an active configuration.
- Reconnect uses a new `open()` session, fresh IDs and fresh metadata/settings.
  The existing `adopt` and `stop` recovery policies work for running v3 peers.
  Data arriving before fresh settings are available is discarded.

## Coverage

`daq_api/tests/test_version_negotiation.py` exercises:

| Peer or condition | Expected result |
| --- | --- |
| Historical legacy simulator | v3 rejection, v1 selection, 1 MHz ADC / 4 MHz GPIO |
| V2-only test peer | v3/v1 rejection, v2 selection, configured 1 MHz / 1 MHz |
| Public v3 simulator | v3 selected without a legacy probe |
| Physical-identity v3 test peer | Read-only discovery, serial selection and identity pins |
| Wrong request ID, kind or rejected version | No fallback |
| Timeout, corrupt checksum, malformed metadata, INVALID_LENGTH | No fallback |
| Exhausted versions | Three probes, close, no reopen loop |
| Large noise input | Bounded read/parser storage, no downgrade |
| STOP, diagnostics, configuration and restart | Stable selected version |
| Reset/reopen, stale buffered success, pre-existing run | Fresh metadata/settings; adopt or bounded STOP |

The v2-only test peer uses simulated timing, not physical clock evidence. Frozen
release-1.1.0 expectations remain in `test_release_v110_contract.py`. Existing
legacy test transports now understand the initial v3 rejection exchange;
byte-for-byte transport parity uses a fixed mocked request-ID seed.

## Validation

Commands run from the repository root with the existing environment:

```bash
.venv/bin/python -m pytest daq_api/tests -q --tb=short
.venv/bin/python -m pytest daq_api/tests/test_version_negotiation.py -q
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/ruff check daq_api/src/thingdone_daq daq_api/tests
.venv/bin/ruff format --check daq_api/src/thingdone_daq daq_api/tests
.venv/bin/mypy daq_api/src/thingdone_daq --ignore-missing-imports
.venv/bin/python daq_api/examples/protocol_upgrade.py
git diff --check
```

The full Python suite passed **845 tests and 15,861 subtests in 45.13 s**,
including offline examples, frozen legacy/release vectors and the optional NumPy
path. After the final constructor-cleanup and draining-state guards, the affected
negotiation/discovery/public API/control suites passed **129 tests and 11 subtests
in 9.05 s**, including all **27 negotiation tests**. Ruff lint and formatting
passed (84 Python files); mypy passed (33 source files); all 142 generated outputs
were current. The v3 demo passed three exact captures with STOPPED final state,
closed transport and stopped reader. Final documentation/layout checks passed
8 tests and 1,095 subtests; whitespace checks passed.

The final affected suites were rerun with the repository-local temporary directory:

```bash
TMPDIR="$PWD/.maestro/playbooks/Working/phase02-negotiation-tmp" .venv/bin/python -m pytest daq_api/tests/test_version_negotiation.py daq_api/tests/test_control_cli.py daq_api/tests/test_discovery.py daq_api/tests/test_public_api.py daq_api/tests/test_public_api_v3.py -q --tb=short
```

Local ignored logs are in `.maestro/playbooks/Working/phase02-negotiation-*.log`.
No hardware acceptance or decoding-performance claims are made.
