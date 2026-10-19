---
type: report
title: Python v3 compatibility and streaming validation
created: 2026-10-19
tags:
  - protocol-v3
  - python
  - compatibility
  - validation
related:
  - '[[protocol-v3-upgrade]]'
  - '[[api-reference]]'
  - '[[protocol-v3-negotiation]]'
  - '[[protocol-v3-python-performance]]'
  - '[[protocol-v3-python-inspection]]'
---

# Python v3 compatibility and streaming validation

Phase 02 integrates bounded version negotiation, advertised configuration,
decoded streaming, diagnostics and CLI support into the public Python API.
This gate validates simulated peers and host behavior only. Production firmware
remains v2; no device was opened, flashed or physically qualified by this gate.
No images were associated with this task.

## Compatibility matrix

| Peer / request | Verified behavior | Boundary |
| --- | --- | --- |
| Historical v1 persona, automatic selection | v3 rejection then v1; 1 MHz ADC / 4 MHz GPIO; existing checksums and defaults; STOP to IDLE | Historical simulator behavior, not new physical acceptance |
| Release v2-only persona, automatic selection | v3/v1 rejection then v2; 1 MHz ADC / 1 MHz GPIO; STOP to IDLE | Frozen release-1.1.0 vectors and expectations remain unchanged |
| V3 persona, automatic selection | Direct v3; advertised default 600 MHz, 1 MHz ADC/GPIO, RLE_AUTO/PACK12; all 60 exact tuples exercised | Clocks are simulated metadata; 450 MHz tuples require RAW policies |
| Explicit v2 INFO/CONFIGURE sent to current v3 persona | Bounded non-mutating timeout while stopped/running | Successful v2 operation on v3 firmware is **not implemented or qualified**; remains Phase 03/06 work |
| Corrupt/truncated metadata, checksums, stale IDs, arbitrary timeout | Bounded rejection without silent downgrade | Only correlated explicit UNSUPPORTED_VERSION permits fallback |
| Private versions 0x82/0x83 | Bounded rejection; never implicit negotiation candidates | Research variants are outside the public compatibility policy |
| Reconnect, STOP/restart, existing running session | Fresh identity/settings on reopen; adopt/stop recovery; configured wire version retained | V3 STOP drains to STOPPED and retains settings; legacy STOP returns IDLE |

Discovery is read-only INFO probing with identity correlation. CONFIGURE applies
an advertised exact tuple atomically while stopped; echo, GET_SETTINGS and INFO
clocks must agree. Unsupported selectors fail without silent substitutions.
The detailed negotiation deadlines, parser bounds and request-ID rules are in
[[protocol-v3-negotiation]].

## Reproduction

Run from the repository root. Temporary files and logs stay under the ignored
playbook Working directory. The primary environment has CPython 3.12.3,
NumPy 2.5.2, pytest 9.1.1, Ruff 0.16.5 and mypy 2.3.1 on Linux x86-64.

```bash
mkdir -p .maestro/playbooks/Working/phase02-validation-tmp
export TMPDIR="$PWD/.maestro/playbooks/Working/phase02-validation-tmp"
.venv/bin/python -m pytest daq_api/tests -q --tb=short
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python -m pytest daq_api/tests/test_examples.py daq_api/tests/test_documentation_integrity.py daq_api/tests/test_repository_layout.py -q --tb=short
.venv/bin/python daq_api/examples/protocol_upgrade.py
git diff --check
```

`test_examples.py` runs all 11 public examples in fresh subprocesses with serial
opening, enumeration and network connection attempts forbidden. Documentation
integrity compiles every Python fence and executes all eight simulator snippets
with serial/network access forbidden, including the API reference's advertised
tuple selection and default compressed capture/restart examples.

Create a genuinely separate environment without the optional NumPy extra:

```bash
.venv/bin/python -m venv --without-pip .maestro/playbooks/Working/phase02-no-numpy
.venv/bin/python -m pip --python .maestro/playbooks/Working/phase02-no-numpy/bin/python install --no-cache-dir --editable './daq_api[dev]'
.maestro/playbooks/Working/phase02-no-numpy/bin/python -c 'import importlib.util; assert importlib.util.find_spec("numpy") is None; print("NumPy absent")'
.maestro/playbooks/Working/phase02-no-numpy/bin/python -m pytest daq_api/tests -q --tb=short
```

This installs the base package and development tools, not NumPy, and uses the
same CPython interpreter version. The dependency installation requires package
index access; subsequent simulator validation is offline. The package's existing
optional-NumPy tests skip only NumPy consumers in this environment; pure Python
decoding, CLI, discovery, transport reader, adversarial/loss, packaging and all
offline examples still execute. No global environment was modified.

## Gate results

| Gate | Result |
| --- | --- |
| Full Python suite with NumPy | 1,255 tests and 15,878 subtests passed in 74.07 s |
| Full Python suite without NumPy | 1,240 tests and 15,884 subtests passed in 77.27 s; 15 optional NumPy cases skipped; NumPy absence asserted in the isolated environment |
| Compatibility/adversarial and NumPy/decoded consumer suites | 200 tests passed in 8.25 s |
| Offline examples plus documentation/layout | 10 tests and 1,129 subtests passed; 11 example scripts and eight simulator documentation snippets |
| Protocol generator drift | All 142 generated files current |
| Ruff format/lint over daq_api, firmware and tools | 191 Python files formatted; lint clean |
| Mypy | 33 package source files clean |
| Standalone protocol_upgrade.py | Three exact v3 captures plus automatic v1/v2 legacy captures; clean STOP and reader/transport cleanup |
| API reference CLI examples | All five commands passed, including JSON parsing, v3 defaults, 450 MHz RAW, GPIO16 capture and v2 configuration |

The CLI commands are reproduced verbatim in [[api-reference]] under CLI and
examples. Local full logs use
`.maestro/playbooks/Working/phase02-validation-*.log` (ignored operator state,
not shipped artifacts). The first no-NumPy pass overlapped documentation editing
and caught three unresolved new-report links; the completed report resolves
them, and the full no-NumPy suite passed against the completed files. No production
code or historical fixtures were changed for this gate.

## Measured limitations

The retained measurements in [[protocol-v3-python-performance]] use ten bounded
RAW/PACK12/GPIO8/GPIO16 RLE_AUTO profiles, maximum-size frames and short tails,
matched logical samples, three timing batches and separate memory passes.
At maximum chunks of 16,384 bytes, that recorded run measured ADC RAW at
15.84 million pairs/s and PACK12 at 11.37 million pairs/s (1.39 times RAW wall
cost). Compressible GPIO8 RLE measured 36.16 million samples/s (2.18 times RAW
cost); GPIO16 RLE measured 22.42 million samples/s (1.76 times RAW cost).
Alternating GPIO fell back to byte-identical RAW. These are prior retained
measurements, not new hardware or end-to-end throughput results from this gate.

Across those profiles, retained encoded plus decoded deque payload storage was
at most 64,864 bytes for eight blocks; traced peaks were 79,266–115,052 bytes.
Normal tests enforce exact 520-frame accounting, bounded parser storage,
eight-block retention, traced peak below 2 MiB and post-return traced retention
below 128 KiB. Tracemalloc is not RSS. The existing legacy 1.25-times headroom
gate remains enforced; new v3 timings are informational and load-sensitive.

PACK12 saves one wire sample byte per ADC pair; RLE_AUTO may interleave RAW and
RLE frames. Decoded logical item counts, GPIO mapping, START-relative timestamps,
ADC1 phase and loss evidence are independent of encoded size. Full wire-byte
counters remain separate from decoded-byte totals. Optional NumPy views retain
immutable decoded storage; NumPy is not required for standard-library decoding.

The current TimestampAligner rejects the equal-rate v2/v3 frame layout. ADC and
GPIO frames cover different time intervals; sequence numbers do not establish
alignment. Consume block timestamps directly. V3 status lacks firmware
emitted-frame, DMA, parser, transport and queue-high-water telemetry exposed by
some legacy diagnostics; unavailable metrics stay None/null, not inferred zero.
Reconciliation cannot prove conservation for unadvertised counters.

Simulator acceptance does not measure USB scheduling, target encoding cost,
real clock transitions, electrical timing, analog accuracy, or sustained
combined physical capture. Existing hardware/watchdog/SDK qualification limits
in [[watchdog-sdk-20260927]] and [[watchdog-disabled-20260927]] remain in effect.

## Phase 02 closeout review

Reviewed the eight Phase 02 checkpoints from `3319f84` through `4c463e2`,
their changed-file scope, negotiation/identity/settings integration, and the
retained validation logs. A fresh fetch confirmed all eight commits were already
on `origin/main`, with no divergence or uncommitted work. Changes are confined to
the Python package, its tests/examples, README and protocol documentation;
firmware and frozen legacy vectors are unchanged.

This closeout adds only this review record. No remote integration or production
code changes required repeating the full Python suites. Documentation, offline
examples and repository layout passed 10 tests and 1,130 subtests on closeout.
Generator drift (142 outputs), Ruff format/lint (191 files), mypy (33 source
files) and whitespace checks also passed. The Phase 02 playbook completion is
recorded in ignored local operator state.
