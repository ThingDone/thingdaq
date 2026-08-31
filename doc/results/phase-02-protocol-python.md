---
type: report
title: Phase 02 Protocol and Python Quality Gate
created: 2026-08-28
tags:
  - thingdaq
  - phase-02
  - protocol
  - python
  - verification
related:
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[Phase-01-Prototype]]'
  - '[[System-Overview]]'
---

# Phase 02 protocol and Python quality gate

## Result

The complete offline Phase 02 gate passed on 2026-08-28 in
the repository root. The implementation baseline at the start of the
gate was `a9f1856dd3107404de7d0a8ca060b8a39e3a124d`; this report and the two
test-only quality-gate repairs are recorded by the following commit.

The gate used generated fixtures, fake serial peers, the in-memory simulator,
and clean local Python environments. It did not enumerate or open a physical
serial port, access a Teensy, use credentials, upload firmware, or require a
human decision. See [[Protocol-V1]] for the normative contract and
[[ADR-001-Wire-Protocol]] for its rationale.

| Gate | Result |
| --- | --- |
| Two protocol generations plus drift check | PASS: all 20 outputs unchanged |
| Ruff format and lint | PASS on Python 3.11 and 3.12: 29 files formatted; no findings |
| MyPy | PASS on Python 3.11 and 3.12: no issues in 29 source files |
| Complete tests | PASS on each runtime: 110 tests and 9,749 subtests |
| Deterministic parser fuzz focus | PASS: 3 tests and 42 seeded subtests |
| Valid-frame throughput probe | PASS: 256 MiB, 65,536 frames, 40.797 MiB/s |
| Dense false-magic stress probe | PASS: 64 MiB, 16,777,216 rejected candidates, bounded at 4,099 bytes, then recovered |
| Clean wheel build and non-editable install | PASS on Python 3.12 build to Python 3.11 install |
| Hardened-reader synthetic demo | PASS at 1-, 17-, and 4,096-byte chunk limits |

## Quality-gate repairs

The first static-analysis pass found the deferred findings documented by the
preceding test task. No production package behavior needed repair:

- `daq_api/tests/test_serial_stack_adversarial.py` now uses Ruff's canonical
  import grouping.
- `daq_api/tests/test_simulator_api.py` explicitly narrows decoded data blocks
  before shared attribute assertions and narrows the restarted block after the
  runtime assertion. This removes five union-attribute errors without changing
  the assertions or exercised behavior.

The initial functional run already passed all 110 tests and 9,748 subtests.
The final matrix below passed after these test-only repairs and includes one
additional documentation-layout subtest for this report.

## Environment and runtime matrix

| Component | Identity |
| --- | --- |
| Host | Linux 6.17.0-35-generic, x86-64 |
| CPU | AMD Ryzen 5 5600X, 6 cores / 12 threads |
| Supported local runtime 1 | CPython 3.11.14, uv-managed |
| Supported local runtime 2 | CPython 3.12.3, system |
| Package requirement | Python 3.10 or newer |
| uv | 0.10.2 |
| Ruff | 0.16.5 |
| MyPy | 2.3.1 |
| pytest | 9.1.1 |
| build | 1.6.0 |
| Isolated-build setuptools | 84.0.0 |
| PySerial | 3.5 |

`uv python list --only-installed` found only Python 3.11.14 and 3.12.3 among
the package's supported versions, so both were tested. Each environment was
new, separate, and installed from `./daq_api[dev]` before running the same gate:

```bash
ruff format --check daq_api/src daq_api/tests firmware/tools firmware/tests tools
ruff check daq_api/src daq_api/tests firmware/tools firmware/tests tools
mypy daq_api/src daq_api/tests firmware/tools firmware/tests tools
python -m pytest -q daq_api/tests firmware/tests
```

| Runtime | Format | Lint | MyPy | Complete tests |
| --- | --- | --- | --- | --- |
| CPython 3.11.14 | 29 files already formatted | All checks passed | No issues in 29 files | 110 passed, 9,749 subtests passed in 2.51 s |
| CPython 3.12.3 | 29 files already formatted | All checks passed | No issues in 29 files | 110 passed, 9,749 subtests passed in 2.64 s |

## Protocol generation and identity

The generator was run twice, explicit check mode passed, and Git diff checks
were empty after both generations:

```bash
.venv/bin/python tools/generate_protocol.py
git diff --exit-code -- daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h protocol/fixtures
.venv/bin/python tools/generate_protocol.py
.venv/bin/python tools/generate_protocol.py --check
git diff --exit-code -- daq_api/src/thingdaq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h protocol/fixtures
```

Each generator invocation reported all 20 outputs current. Representative
source and generated-output identities were:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `protocol/protocol-v1.json` | 23,692 | `ca99dcf8e21d76bd20a2ccb41122773a2c9f4f8d902cb4bfdb5c472331f47f01` |
| Python protocol constants | 13,233 | `2c8d16b36368c186e871a490af6ee1dafcdc13c5cc237a8148276b8361e7f800` |
| C++ protocol constants | 15,064 | `be724ea85ce518d01a9b9f53cf62e8cec35be2f750a8acc86d96a58bacb4eedc` |
| Golden-fixture manifest | 11,388 | `0e7584176fce07c21f1d8401965997ed8a801a2ea6480eb0fa0f57d0f0817b61` |

## Deterministic fuzz and parser stress evidence

The focused parser run fixed `PYTHONHASHSEED=0` and selected the random
partition, fault-fuzz, and dense false-magic cases:

```bash
PYTHONHASHSEED=0 python -m pytest -q \
  daq_api/tests/test_parser_adversarial.py::AdversarialParserTests::test_seeded_random_partitions_preserve_all_frames \
  daq_api/tests/test_parser_adversarial.py::AdversarialParserTests::test_seeded_fault_fuzz_makes_bounded_forward_progress \
  daq_api/tests/test_protocol_core.py::ProtocolCoreTests::test_dense_false_magic_stream_stays_bounded_and_reports_counters
```

It passed 3 tests and 42 subtests in 0.10 seconds. The 10 partition seeds were
`0`, `1`, `2`, `7`, `19`, `41`, `101`, `257`, `1001`, and `65537`. The 32
fault seeds were `0xDA0000 + [0, 31]`; each applied 24 deterministic noise and
mutation rounds, for 768 fault rounds total. Every seed asserted forward
progress, exact sentinel recovery, and the 4,099-byte parser bound.

Separate CPython 3.12.3 probes measured `time.perf_counter()`, process CPU time,
Linux `ru_maxrss`, and parser counters. The valid probe fed the tracked
4,096-byte ADC frame 65,536 times. The hostile probe fed 1,024 64-KiB chunks
made entirely of repeated four-byte magic values, then verified recovery by
decoding the tracked INFO-request sentinel.

| Stream | Timed bytes | Wall / CPU | Throughput | Outcomes | Parser high-water / bound | Process max RSS |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Valid ADC frames | 268,435,456 (256 MiB) | 6.274925871 s / 6.256600922 s | 40.797294703 MiB/s | 65,536 decoded; 0 corruptions; 0 buffered bytes | 4,096 / 4,099 bytes | 55,040 KiB |
| Dense false magic | 67,108,864 (64 MiB) | 21.422540841 s / 21.386748860 s | 2.987507433 MiB/s | 16,777,216 header corruptions; all 67,108,864 bytes discarded; sentinel recovered; 0 buffered bytes | 4,099 / 4,099 bytes | 54,664 KiB |

`ru_maxrss` includes the interpreter and imported package. The parser-specific
high-water counter is the stronger storage-bound measurement: retained state
never exceeded 4,099 bytes even though the hostile input was more than 16,000
times larger.

## Clean wheel and installed demo

A new CPython 3.12 environment containing only `build` created the wheel via an
isolated PEP 517 builder. A separate new CPython 3.11 environment installed the
wheel and its runtime dependency without editable source access:

```bash
python -m build --wheel --outdir <wheelhouse> daq_api
uv pip install --python <clean-python-3.11> <wheelhouse>/<pre-rename-wheel>
python -I -c 'import pathlib, thingdaq; print(pathlib.Path(thingdaq.__file__).resolve())'
```

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Pre-rename wheel, version 0.0.0 | 59,879 | `06665a3566621fdbf9a4abbcfad2e0539fa7a760e112f47be1831ed7dd3471c8` |

The isolated import resolved inside the clean environment's
`lib/python3.11/site-packages/thingdaq/`, confirming a non-editable wheel
install. The installed console entry point then reran the [[Phase-01-Prototype]]
flow through the current `BackgroundReader` and synchronous public API:

```bash
thingdaq-demo --frame-count 3 --parser-chunk-size 1
thingdaq-demo --frame-count 3 --parser-chunk-size 17
thingdaq-demo --frame-count 3 --parser-chunk-size 4096
```

All three runs validated three ADC and three GPIO frames, independent sequence
and timestamp progression, cross-frame synthetic joins, final `IDLE` state,
closed transport, and zero gaps, drops, or errors.
