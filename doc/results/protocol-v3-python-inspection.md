---
type: analysis
title: Phase 02 Python integration reuse inspection
created: 2026-10-19
tags:
  - protocol-v3
  - python
  - compatibility
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-prototype]]'
  - '[[protocol-v3-foundation]]'
  - '[[deferred-codecs-20261018]]'
  - '[[api-reference]]'
---

# Phase 02 Python integration reuse inspection

This completes only the first Phase 02 inspection task, before extending the
supported physical-device API. Inspected revision: `da71dab`. The worktree was
clean on entry, `AGENTS.md` requires validated commits and normal pushes to
`origin/main`, and no `CLAUDE.md` was present. No associated task images were
present. Production code, fixtures, defaults, and public imports are unchanged.

## Existing implementation to extend

Paths in this table are relative to `daq_api/src/thingdone_daq/`.

| Surface | Existing implementation and reuse boundary |
| --- | --- |
| Session | `client.py`: `ThingDAQ.open`, `synchronize`, `_read_info`, `configure`, START/STOP, strict loss handling and recovery evidence. `session_v3.py`: `V3Session` owns v3 control state while using the same reader; configuration already checks exact CONFIGURE echo and GET_SETTINGS equality. Extend these instead of introducing another facade. |
| Discovery and identity | `discovery.py`: metadata filtering, `probe_candidate`, fresh enumeration, serial selection, bounded reader cleanup. `identity.py`: stable snapshots, expected-identity pins, board/MCU/build validation. Preserve validation before mutation and serial continuity across port renames. |
| Reader | `reader.py`: one parser/thread, correlated pending requests, bounded queues, deadlines, active-run checks, loss events and STOP-tail handling. V3 response/block dispatch and START settings already exist. |
| Transport | `transport.py`: `ByteTransport`, bounded `SerialTransport`, and chunked `InMemoryTransport`. The latter already supports `SimulatedV3Device`, sizes buffers for v3 metadata, and reports pending data tails for drain. No separate serial or simulator transport is needed. |
| Contract and parser | `protocol/protocol-v3.json`, `tools/generate_protocol.py`, `_generated/protocol_v3_constants.py`, and `protocol/fixtures-v3/` are the authority. `protocol_v3.py` reuses `_incremental.py` bounds and supplies RAW/PACK12/RLE codecs. `protocol_v2.py` has an opt-in `include_v3` compatible parser. Preserve generated v1/v2 outputs and private-version rejection. |
| Metadata | `models_v3.py`: reuse `V3Info`, `V3Capabilities`, `V3Settings`, `V3AppliedSettings`, `V3Clocks`, `V3Rate`, and `V3Status`. Capabilities already carry defaults, clock/rate tables and exact supported configuration tuples. No parallel metadata model is needed. |
| Blocks and loss | `models.py`: shared `ADCBlock`/`GPIOBlock` already accept v3 decoded payloads plus encoded payloads, expose decoded/encoded/wire byte counts, preserve channel views and timestamps, and handle variable-count gaps. Reuse `analyze_stream_continuity`, `StreamGap` and `HostQueueLoss`. |
| Streaming consumers | `streaming.py`: bounded latency, queue, memory and conservation metrics; strict synthetic validation. `numpy.py` provides optional array views over existing blocks; `alignment.py` owns timestamp alignment. Extend consumer assumptions deliberately. |
| CLI and exports | `cli.py`: existing connection/acquisition argument builders, `_configuration_from_arguments`, `_json_value`, human formatters and lifecycle cleanup. Keep `__init__.py` exports and expert `low_level.py` imports compatible. Root v3 exports exist; low-level exports currently describe v1/v2. |
| Simulator and demo | Preserve `simulator.py`'s historical behavior; reuse the explicit `simulator_v3.py` persona and `synthetic.py` patterns. `daq_api/examples/protocol_upgrade.py` already verifies three 600/450/600 MHz simulated captures, configuration readback, RAW fallback, timestamps, loss and cleanup. Extend that example instead of adding a second upgrade demo. |

## Integration gaps for later tasks

- `ThingDAQ.open()` and `probe_candidate()` independently probe v1, retrying
  v2 only on explicit UNSUPPORTED_VERSION. V3 setup is enabled only through
  `ThingDAQ.simulated(protocol_version=3)` and its private constructor flag.
  The common negotiation policy must reach physical open, discovery and fresh
  sessions after reconnect; no public `reconnect()` method currently exists.
- `BackgroundReader._dispatch_response()` rejects a legacy response to a
  pending v3 request. Negotiation must explicitly recognize permitted legacy
  rejections without weakening normal request-ID, kind or version checks.
  Ordinary timeout, corruption and malformed metadata must remain failures.
- `DiscoveredDevice.info` and identity validation assume legacy `DeviceInfo`;
  the shared validator admits only versions 1/2. `V3Session.info()` checks
  identity stability, but is not yet integrated with physical discovery or
  caller-supplied identity pins.
- Legacy `ThingDAQ.stop()` resets the selected wire version to the verified
  identity version. Preserve historical tests while adding explicit coverage
  for a configuration-latched version through STOP and subsequent commands.
- The legacy simulator supports v1/v2 but is not a release-v2-only persona.
  `simulated(protocol_version=2)` currently rejects its argument; the v3 peer
  accepts v3 ingress only. Explicit compatibility personas and rejection
  behavior belong to the subsequent negotiation/compatibility work.
- Keep historical v1 ADC/GPIO defaults at 1 MHz/4 MHz and release-v2 defaults
  at 1 MHz/1 MHz (450 MHz CPU). The v3 defaults remain advertised separately:
  600 MHz CPU, 1 MHz/1 MHz, RLE_AUTO/PACK12. Do not rewrite frozen vectors or
  existing release assertions to make a new default pass.
- `configure()` accepts `V3Settings`, but has no clock/encoding keyword
  selectors. Its omitted checksum and stream selectors still come from host
  signature defaults. Metadata validation currently pins defaults, limits and
  clock/rate records to canonical generated values; any broadening must remain
  consistent with the contract and validate advertised tuple membership.
- `protocol_v3.decode_data_payload()` uses a per-pair unpack/pack loop for
  PACK12. Reuse the bounded byte-lane approach in
  `firmware/tests/rig_aux_input_capture.py:decode_adc12`, cited by
  [[deferred-codecs-20261018]], without importing the rig runner. Its fixed
  1012-pair guard must become the public codec's validated count bound.
  The current frame/block validation path also decodes payloads repeatedly;
  preserve validation guarantees when measuring or reducing that cost.
- `streaming.py` still computes byte totals from legacy fixed frame sizes.
  Use actual block wire metrics for compression bandwidth, retaining decoded
  sample counts separately. NumPy remains optional. `TimestampAligner`
  requires common frame time coverage; unequal ADC/GPIO coverage remains
  unsupported, and sequence-number pairing is not an alternative.
- CLI metadata and lifecycle formatters still assume legacy models. Extend
  their existing JSON/human conventions and configuration path; the current
  prototype demo alone does not establish physical-device compatibility.

## Existing verification to reuse

Inspected the corresponding test cases and fixtures, including:

| Concern | Existing tests under `daq_api/tests/` |
| --- | --- |
| Discovery, identity and reconnect | `test_discovery.py`, `test_capability_validation.py`, `test_serial_stack_adversarial.py`, `test_python_loss_recovery.py` (including renamed-port recovery). |
| Reader and transport bounds | `test_transport_reader.py`: partial reads/writes, reordered responses, pending limits, deadlines, disconnects and queue loss. |
| Public lifecycle and compatibility | `test_public_api.py`, `test_simulator_api.py`, `test_public_api_v3.py`, `test_simulator_v3.py`, `test_release_v110_contract.py`. |
| Protocol and malformed inputs | `test_protocol_v3_codecs.py`, `test_protocol_v3_generation.py`, `test_protocol_generation_drift.py`, `test_protocol_vectors_exhaustive.py`, `test_parser_adversarial.py`. |
| Consumers and exports | `test_data_models.py`, `test_loss_semantics.py`, `test_streaming.py`, `test_numpy_integration.py` (including NumPy import prohibition), `test_alignment.py`, `test_cli_lifecycle.py`, `test_control_cli.py`. |
| Demo and performance | `test_examples.py`, `test_streaming_correctness_performance.py`; retain the existing benchmark conventions and separate informational new timings from deterministic correctness bounds. |
| Documentation | `test_repository_layout.py` and `test_documentation_integrity.py` check front matter, links, public example coverage and executable snippets. |

This inspection adds no production behavior requiring a new test. Existing
regressions validate the unchanged baseline and the new documentation; future
implementation tasks own their corresponding new cases.

## Validation

Commands run from the repository root using the existing `.venv`:

```bash
mkdir -p .maestro/playbooks/Working/phase02-inspection-tmp
TMPDIR="$PWD/.maestro/playbooks/Working/phase02-inspection-tmp" .venv/bin/python -m pytest daq_api/tests -q -ra
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python daq_api/examples/protocol_upgrade.py
.venv/bin/python -m pytest daq_api/tests/test_repository_layout.py daq_api/tests/test_documentation_integrity.py -q
git diff --check
```

The explicit test directory avoids ignored historical scratch copies described
in [[protocol-v3-foundation]]. Generator validation passed with all 142 outputs
current. The offline demo passed all three captures with exact equality,
STOPPED final state, a closed transport and a stopped reader. The Python suite
passed: **820 tests and 15,846 subtests in 39.77 seconds**. No physical hardware
validation was attempted.

After adding this report, documentation/layout checks passed: **8 tests and
1,090 subtests in 1.33 seconds**. Whitespace validation also passed.

Local ignored logs: `.maestro/playbooks/Working/phase02-inspection-tests.log`
and `.maestro/playbooks/Working/phase02-inspection-demo.log`.
