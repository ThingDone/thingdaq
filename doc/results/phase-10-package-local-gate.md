---
type: report
title: Phase 10 Package Local Gate
created: 2026-08-29
tags:
  - thingdaq
  - phase-10
  - python-package
  - clean-install
  - reproducibility
related:
  - '[[Python-API]]'
  - '[[API-Reference]]'
  - '[[Quickstart]]'
  - '[[Calibration]]'
  - '[[NumPy-Integration]]'
  - '[[Hardware-Safety]]'
  - '[[Phase-09-Loss-Recovery]]'
---

# Phase 10 package local gate

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

## Outcome

The complete offline package gate passed on 2026-08-29 against source revision
`f34ba96651a417bd1b26ab30ac0f8940f96684b9`. No implementation or packaging
repair was required. The generated protocol, format, lint, typing, pure-Python,
optional-NumPy, host-compiled C++, distribution, clean-install, console,
simulator, and example checks all passed.

The gate did not enumerate or open a serial port, compile or upload firmware,
contact the remote rig, load a personal calibration record, or claim new
physical evidence. The public lifecycle and raw/calibrated boundaries under
test are documented in [[Python-API]], [[API-Reference]], [[Calibration]], and
[[NumPy-Integration]]. Electrical limits remain in [[Hardware-Safety]].

| Gate | Result |
| --- | --- |
| Generated protocol drift | PASS: all 26 tracked outputs current |
| Ruff format and lint | PASS: 111 Python files; no findings |
| MyPy package check | PASS: no issues in 23 package modules |
| Full suite without NumPy | PASS: 363 tests, 7 expected skips, 13,815 subtests |
| Full suite with NumPy 2.5.2 | PASS: 370 tests and 13,815 subtests; no skips |
| Independent distribution builds | PASS: two isolated PEP 517 builds from the same Git revision and source epoch |
| Normalized artifact comparison | PASS: 29 wheel files and 45 sdist files/modes/bytes matched exactly |
| Clean wheel installs | PASS: CPython 3.10 through 3.14 on Linux x86-64 |
| Clean sdist install | PASS: CPython 3.12.3 with development and NumPy extras |
| Installed PEP 561 consumer checks | PASS: wheel and sdist installs |
| Installed console and simulator checks | PASS: INFO, bounded strict-loss monitor, and complete two-stream demo |
| Installed-package example checks | PASS: all nine examples for every wheel environment and the sdist environment |
| Physical hardware or publication | NOT RUN: outside this local gate |

## Reproducible distribution contents

Two clean snapshots were produced with `git archive` from the exact revision
above. They were built concurrently in separate source, build, cache, and
output directories with CPython 3.12.3, `build` 1.6.0, isolated Setuptools
84.0.0, `PYTHONHASHSEED=0`, and `SOURCE_DATE_EPOCH=1788013865`. Each build made
the sdist first and then built the wheel from that sdist.

| Build | Artifact | Bytes | Archive SHA-256 |
| --- | --- | ---: | --- |
| A | pre-rename wheel, version 0.10.0 | 178,111 | `47759ba1a74d7465f8c06ffb40e2656778701245a6285b193ced04deb818f7d3` |
| B | pre-rename wheel, version 0.10.0 | 178,111 | `47759ba1a74d7465f8c06ffb40e2656778701245a6285b193ced04deb818f7d3` |
| A | pre-rename source distribution, version 0.10.0 | 195,939 | `67285e6a10cd1d384e01e438f0b54ee12404e61924c646aa25ce538913e52f22` |
| B | pre-rename source distribution, version 0.10.0 | 195,928 | `831be5170b8ed2f498724eaa1c4bc241d39ad0722861347eab6f80f498c5a420` |

The two wheel containers are byte-for-byte identical. The gzip-wrapped sdist
containers are not byte-identical, so their distinct sizes and hashes are
reported rather than hidden. After removing the single generated top-level
directory and archive metadata, every sdist regular-file path, permission
mode, and byte sequence matches. The canonical comparison hashes each sorted
`path`, octal `mode`, and file body separated by NUL bytes:

| Normalized set | Members | Build A SHA-256 | Build B SHA-256 |
| --- | ---: | --- | --- |
| Wheel files | 29 | `35c6ba0082be054b54ed851b5f2ed2b2707c1f0087964f1cf2437aaba5f76af3` | `35c6ba0082be054b54ed851b5f2ed2b2707c1f0087964f1cf2437aaba5f76af3` |
| Sdist files and modes | 45 | `eb7a949827a01e428aa365d66194987132a5429a3b7e4cecdfd58fd46327d3d7` | `eb7a949827a01e428aa365d66194987132a5429a3b7e4cecdfd58fd46327d3d7` |

This establishes reproducible package *contents*. It deliberately does not
claim byte-reproducible gzip containers. Archive acceptance tests also rebuilt
the package from a private-data-baited temporary tree and confirmed that
tests, credentials, calibration JSON, captures, firmware binaries, build
trees, and publication commands are absent.

## Supported interpreter matrix

Each interpreter below received a new virtual environment and a non-editable
install of the built wheel plus only its required PySerial 3.5 dependency.
NumPy was absent. Every row passed `pip check`, an isolated import resolving
inside that environment's `site-packages`, version `0.10.0`, `py.typed` and
low-level-namespace checks, JSON INFO, a bounded strict-loss monitor, the
complete two-ADC/two-GPIO-frame simulator demo, and all nine public examples.

| Interpreter | Provider | Wheel install | `pip check` | Consoles/demo | Examples |
| --- | --- | --- | --- | --- | --- |
| CPython 3.10.19 | uv standalone | PASS | PASS | PASS | 9/9 PASS |
| CPython 3.11.14 | uv standalone | PASS | PASS | PASS | 9/9 PASS |
| CPython 3.12.3 | Ubuntu system | PASS | PASS | PASS | 9/9 PASS |
| CPython 3.13.12 | uv standalone | PASS | PASS | PASS | 9/9 PASS |
| CPython 3.14.3 | uv standalone | PASS | PASS | PASS | 9/9 PASS |

A separate fresh CPython 3.12.3 environment installed the source distribution
with `[dev,numpy]`. It resolved PySerial 3.5, NumPy 2.5.2, pytest 9.1.1, Ruff
0.16.5, MyPy 2.3.1, `build` 1.6.0, and the declared type stubs; `pip check`,
isolated import, both console workflows, the full demo, and all nine examples
passed. Strict MyPy consumer snippets imported `ThingDAQ` and the optional
`ADCArrayView` from both the wheel and sdist installs, proving the installed
PEP 561 marker and annotations are usable without an editable source tree.

These are exact Linux x86-64 results, not a claim of tests on Windows, macOS,
another architecture, PyPy, or a different patch release. They exercise every
CPython minor in the declared `>=3.10,<3.15` range on this host.

## Source and regression gates

The no-NumPy suite ran from the existing CPython 3.12.3 development environment
after confirming that `importlib.util.find_spec("numpy")` returned `None`. The
NumPy suite ran through the clean sdist environment and imported version 2.5.2
from that environment. Both invocations covered all repository Python tests
and every host-compiled C++ test. The C++ wrappers used Ubuntu `g++` 13.3.0;
the host was Linux 6.17.0-35-generic x86-64.

```bash
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdaq
.venv/bin/python -m pytest -q

<clean-numpy-sdist-python> -m ruff format --check daq_api firmware tools
<clean-numpy-sdist-python> -m ruff check daq_api firmware tools
<clean-numpy-sdist-python> -m mypy daq_api/src/thingdaq
<clean-numpy-sdist-python> -m pytest -q
```

The nine examples cover discovery/serial selection, raw ADC channels, explicit
interleaving, opt-in calibration, GPIO bytes and selected channels, combined
timestamp alignment, live loss handling, simulator use, and clean shutdown.
They all used their default bounded simulator path; no `--real` option was
passed. See [[Quickstart]] for the runnable commands and tested-versus-physical
boundary.

## Retained local evidence

Build snapshots, both artifact pairs, workspace-contained CPython installs,
and clean virtual environments are retained outside version control under
`.maestro/playbooks/Working/phase-10-package-gate-00001/`. They contain no
credentials or personal calibration. The following Phase 10 hardware task will
produce separate physical workflow evidence; it must not reinterpret this
offline gate as a device result.
