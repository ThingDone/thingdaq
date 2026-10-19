---
type: report
title: Public protocol v3 offline prototype validation
created: 2026-10-19
tags:
  - protocol-v3
  - offline
  - validation
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-foundation]]'
---

# Public protocol v3 offline prototype validation

The public-v3 prototype completed three deterministic captures at simulated
600/450/600 MHz with exact ADC/GPIO sample equality, correct timestamps, rejected
running configuration changes, no reported loss and complete STOP/close cleanup.
[[protocol-v3-upgrade]] records component ownership and wire decisions;
[[protocol-v3]] is the detailed contract reference.

## Provenance and environment

Validated implementation revision: `c049c32639f6bc84d98ccd090aba8fcff6038c09`.
This checkpoint adds documentation only. The tracked worktree was clean on entry.
Date: 2026-10-19; Linux x86_64, kernel `6.17.0-35-generic`; reused editable `.venv`
with Python 3.12.3, pytest 9.1.1, Ruff 0.16.5 and mypy 2.3.1.
No dependency installation or upgrade was required.

| Artifact | SHA-256 |
| --- | --- |
| `protocol/protocol-v3.json` | `39b43beb44cfa0a704ec94a30301562fecbd04d815813b53722200dc0f4a1b7f` |
| `daq_api/examples/protocol_upgrade.py` | `bdfd9656bb515161b33757c970179944a9d0b2a7550fdccb2b299edbc6776161` |
| Complete demo stdout | `baf6c9c8fb2d6061035aa905fe3cecb59bcc3aa88e3b2d4e8795422c94e759a0` |

## Reproduction

Run from the repository root with the existing development environment:

```bash
mkdir -p .maestro/playbooks/Working/phase01-final-tmp
export TMPDIR="$PWD/.maestro/playbooks/Working/phase01-final-tmp"
.venv/bin/python daq_api/examples/protocol_upgrade.py
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m pytest daq_api/tests firmware/tests -q -ra
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python -m pytest daq_api/tests/test_documentation_integrity.py daq_api/tests/test_repository_layout.py -q -ra
git diff --check
```

The explicit tracked test directories avoid ignored historical scratch copies
that break bare pytest collection, as recorded in [[protocol-v3-foundation]].
The regression suite includes host-compiled portable C++ tests; it requires no
Teensy/Arduino firmware toolchain, target build, upload, attached device or remote
service. The firmware builder listed among README gates was not invoked.

Local ignored logs are retained under `.maestro/playbooks/Working/` with prefix
`phase01-v3-final-`: `demo.log`, `tests.log`, `generator.log`, `format.log`,
`lint.log`, `mypy.log`, `docs.log` and `demo-repeat.log`. The tables and hashes
here retain portable evidence; the local scratch logs are not distributed artifacts.

## Deterministic capture results

Two fresh demo executions produced byte-identical stdout (`cmp` exit 0) with
the hash above. The repeatability check used:

```bash
.venv/bin/python daq_api/examples/protocol_upgrade.py > .maestro/playbooks/Working/phase01-v3-final-demo.log
.venv/bin/python daq_api/examples/protocol_upgrade.py > .maestro/playbooks/Working/phase01-v3-final-demo-repeat.log
cmp .maestro/playbooks/Working/phase01-v3-final-demo.log .maestro/playbooks/Working/phase01-v3-final-demo-repeat.log
sha256sum .maestro/playbooks/Working/phase01-v3-final-demo.log
```

Identity: `TEENSY_40`, `IMXRT1062`, serial `SIM-TEENSY40-V3`, firmware
`0.3.0-sim`, build `thingdaq-simulator-v3`, wire version 3. The demo prints all
60 advertised tuples and defaults: both streams, HARDWARE source (emulated),
ADLER32, CPU 600 MHz, ADC-pair/GPIO 1 MHz, auxiliary DISABLED, 8 GPIO bits,
RLE_AUTO/PACK12 and 12-bit ADC.

Applied CPU clocks were 600000000, 450000000 and 600000000 Hz. All runs reported
IPG 150000000, ADC 37500000, PIT 24000000 and timestamp 8000000 Hz with exact
readback. Clock values are simulated metadata.

| Run | Stream / encoding policy | Frames | Logical items | Decoded sample bytes | Transmitted sample bytes | Complete frame bytes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (600 MHz) | ADC PACK12 | 2 | 2024 pairs | 8096 | 6072 | 6192 |
| 1 (600 MHz) | GPIO RLE_AUTO | 2 | 8096 samples | 8096 | 4051 | 4171 |
| 2 (450 MHz) | ADC RAW | 2 | 2024 pairs | 8096 | 8096 | 8216 |
| 2 (450 MHz) | GPIO RAW | 2 | 8096 samples | 8096 | 8096 | 8216 |
| 3 (600 MHz) | ADC PACK12 | 2 | 2024 pairs | 8096 | 6072 | 6192 |
| 3 (600 MHz) | GPIO RLE_AUTO | 2 | 8096 samples | 8096 | 4051 | 4171 |

Runs 1 and 3 each saved 2024 ADC sample bytes (25%) and produced one GPIO RLE
frame plus one RAW fallback. Their GPIO total is a three-byte all-zero run plus
4048 high-transition RAW bytes. Run 2 produced two RAW GPIO frames with no
adaptive fallback and zero ADC packing savings. Frame totals include 60 bytes
overhead per frame and exclude command traffic; these are byte counts, not
measurements of hardware throughput or elapsed-time performance.

Every run checked payload/channel equality, run ID, per-stream sequence,
per-item timestamps and absence of gap/loss evidence. Running CONFIGURE returned
INVALID_STATE with settings unchanged. Each STOP completed with STOPPED,
`pending_frames=0` and unchanged readback. The final line was:

```text
PASS runs=3 equality=exact final_state=STOPPED transport_closed=true reader_stopped=true
```

## Gates and compatibility

| Gate | Result |
| --- | --- |
| Demo and repeat | PASS; identical stdout, three captures per execution. |
| Generator `--check` | PASS; 142 outputs current (111 legacy + 31 v3). |
| Full tracked regression | 1226 passed, 3 skipped, 16666 subtests passed in 161.53 seconds. |
| Ruff format | PASS; 184 files already formatted. |
| Ruff lint | PASS; all checks passed. |
| Package mypy | PASS; no issues in 32 source files. |
| Documentation/layout after adding these reports | PASS; 8 tests, including front matter, links and existing executable snippets. |
| Diff whitespace | PASS. |

The three skips are existing `firmware/tests/test_input_rate_clock.py` cases:
the fixed-rate policy does not support the equal-rate override. No test failed.
No production code or additional tests were needed for this documentation-only
checkpoint; existing contract, example and documentation tests cover its surface.

The suite covers the v3 generator/contract, independent literal PACK12 and RLE
vectors, all golden-frame split positions, malformed/corrupt/truncated frames,
metadata bounds, all 60 exact tuples, atomic configuration/readback, both GPIO
widths, replay, drain/restart/reboot, public-session loss handling and executable
example assertions. Existing example tests prohibit serial access/network
connection creation and inject a sample mismatch to verify failure cleanup.

Legacy hash checks preserve both v1/v2 canonical sources and all 111 generated
artifacts against the foundation digests. V3 is opt-in through the simulator;
production firmware, serial negotiation and CLI remain v1/v2. Private `0x82/0x83`
research encodings are outside the public-v3 boundary.

No target firmware was built or flashed and no hardware was accessed. These
results do not qualify physical sampling, clocks, USB throughput, host sustained
capture, thermal behavior or analog performance.
