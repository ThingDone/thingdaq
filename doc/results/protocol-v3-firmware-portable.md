---
type: report
title: Public v3 firmware portable validation checkpoint
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - portable-validation
  - cross-language-tests
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3-python]]'
  - '[[protocol-v3-firmware-adversarial]]'
  - '[[protocol-v3-firmware-cross-language]]'
  - '[[protocol-v3-firmware-layouts]]'
---

# Public v3 firmware portable validation checkpoint

This report records the eighth Phase 03 task against implementation/test commit
`6e2eed2`. It consolidates the existing portable firmware, cross-language and
Python compatibility gates. Production code and test assertions are unchanged.
No hardware was opened or flashed; no task images were supplied or analyzed.

## Contract and coverage

[[protocol-v3]] defines the public contract; [[protocol-v3-python]] records the
preceding host compatibility gate. The current firmware adds explicit v2 RAW
sessions alongside v3, as exercised by [[protocol-v3-firmware-cross-language]].
The earlier Python-only report's unimplemented v2-on-v3-firmware boundary is
superseded by this portable firmware coverage, not by physical qualification.

| Surface | Existing coverage rerun by this gate |
| --- | --- |
| Control | Generated commands, lengths, enums/reserved fields, bounded parsing, exact settings/readback, atomic failure/rollback, unsupported tuples, busy drain, duplicate/stale requests and non-mutating discovery |
| Lifecycle and compatibility | Repeated START/STOP and v2/v3 sessions; fixed build-clock capabilities; exact historical v2 RAW layouts and supported checksum modes; legacy Python compatibility and frozen generated vectors |
| Public codecs | ADC 12-bit edges and invalid input; GPIO8/GPIO16 profitable, unprofitable and tied RLE; RAW/PACK12; logical counts, timestamp coverage, checksums and malformed frame/payload rejection |
| Ownership and pressure | USB partial writes, held-buffer immutability, checked invalid indices, eviction, resource/deadline drops, sequence gaps and STOP tails |
| Cross-language execution | Python command bytes through actual C++ parser/control/runtime/USB; public Python frame/block decoding in single-byte and irregular chunks, exact samples, wire lengths, settings and loss counters |
| Structural bounds | Portable source boundaries, compile-time state/page assertions, packet storage, linked managed-memory overlap and placement checks, fixed stack/heap thresholds |

Public v3 requires Adler-32; legacy checksum coverage does not imply additional
public-v3 checksum choices. Cross-language coverage spans the advertised
synthetic encoding/width/stream combinations at both 450 and 600 MHz. Controlled
producer tests also exercise both source flags, but a HARDWARE flag on fabricated
samples is not evidence of physical acquisition.

## Reproduction

Run from the repository root using the existing `.venv` (CPython 3.12.3) and
host g++ 13.3.0. Scratch files and logs are ignored operator state under
`.maestro/playbooks/Working/phase03-portable/`.

```bash
mkdir -p .maestro/playbooks/Working/phase03-portable/tmp
export TMPDIR="$PWD/.maestro/playbooks/Working/phase03-portable/tmp"
.venv/bin/python -m pytest firmware/tests daq_api/tests -q -ra --tb=short
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python -m pytest daq_api/tests/test_documentation_integrity.py -q --tb=short
git diff --check
```

The cross-language and v3 regression harnesses compile production C++ with
`-std=c++17 -O2 -Wall -Wextra -Werror -Wconversion -Wsign-conversion -pedantic
-fno-exceptions -fno-rtti`. Existing portable harness flags, source boundaries,
state-size assertions and ownership tests remain intact.

## Gate results

| Gate | Result |
| --- | --- |
| Full firmware and Python suites | **1,783 passed, 5 expected skips, 16,797 subtests**, in 256.73 seconds |
| Cross-language suites | Included in the passing full run: both 450/600 MHz builds, repeated v2/v3 sessions, public decoded sample/block expectations and loss reconciliation |
| Generator drift | All **142 outputs current**, including frozen legacy artifacts |
| Ruff format and lint | **197 Python files** formatted; lint clean (Ruff 0.16.5) |
| Mypy | **33 package source files** clean (mypy 2.3.1) |
| Final documentation integrity | **4 passed, 1,069 subtests**; links, Python fences and simulator snippets checked |
| Linked target gates | Both 450/600 MHz images pass unchanged memory and placement checks; details below |
| Whitespace | `git diff --check` passes |

The five skips are the three existing equal-rate-override exclusions in
`test_input_rate_clock.py` and two compression cases not advertised at 450 MHz
in `test_v3_layout_runtime.py`. There were no test failures or missing-tool skips;
no implementation fixes were needed. The full run used pytest 9.1.1. Documentation
was updated during that run and separately checked after completion of the text;
its new wiki-links account for the changed subtest total relative to the prior
cross-language report. No additional tests were needed for this documentation
and validation checkpoint.

The full regression log is `regression.log`; the separate documentation run is
`documentation.log`, both under the scratch directory above.

## Linked target images

Both fixed-clock variants build through `firmware/tools/build_firmware.py` with
Arduino CLI 1.4.1, Teensy core 1.62.0 and Arm GNU 15.2.1. The verification wrapper
changes only the selected clock and scratch output paths; all existing memory,
linker-map, packet/DMA storage, overlap and checksum-placement checks execute.
The default release target remains 450 MHz; neither scratch image was published
or flashed. Reproduce the two verification images with the `TMPDIR` above:

```bash
.venv/bin/python - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path('firmware/tools').resolve()))
import build_firmware as build

scratch = Path('.maestro/playbooks/Working/phase03-portable').resolve()
original_compile = build.compile_command
for mhz in (450, 600):
    build.FQBN = f'teensy:avr:teensy40:usb=serial,speed={mhz},opt=o2std'
    build.EXPECTED_BUILD_PROPERTIES = dict(
        build.EXPECTED_BUILD_PROPERTIES, **{'build.fcpu': str(mhz * 1_000_000)}
    )
    build.OUTPUT_DIRECTORY = scratch / f'build-{mhz}' / 'output'
    def compile_command(cli, identity, defs, ld):
        defs += f' -DTHINGDAQ_EXPERIMENT_CPU_HZ={mhz * 1_000_000}U'
        return original_compile(cli, identity, defs, ld) + [
            '--build-path', str(scratch / f'build-{mhz}' / 'arduino')
        ]
    build.compile_command = compile_command
    build.build('arduino-cli')
PY
```

| Linked memory gate | 450 MHz | 600 MHz | Required minimum |
| --- | ---: | ---: | ---: |
| RAM1 free for locals/stack | 33,024 bytes | 33,024 bytes | 32,768 bytes |
| RAM2 free for heap | 4,096 bytes | 4,096 bytes | 4,096 bytes |
| Existing packet pool | 200 × 4,096 bytes | 200 × 4,096 bytes | Unchanged |

The first 600 MHz invocation selected the CPU menu without its matching
`THINGDAQ_EXPERIMENT_CPU_HZ` define. The existing identity guard rejected it;
adding the required define produced the passing image. No source or assertion
was changed to pass. This build-clock define does not enable private codecs.
Both builds also reported the host's missing Teensy udev rules, which did not
prevent compilation/link validation; this run did not attempt device access.
Manifests are `build-{450,600}/output/build-manifest.json` under the scratch
directory; logs are `linked-builds.log` and `linked-build-600.log`.

## Qualification boundary

Passing portable tests establishes the exercised software behavior with fake
clocks, register/CDC seams, synthetic acquisition and controlled packet inputs.
Linked target images establish compilation, layout and memory gates. Neither
establishes physical ADC/GPIO timing, analog accuracy, real DMA contention,
end-to-end loss/USB throughput, thermal behavior or runtime clock switching.
The production application adapter still exposes only its compiled clock.
Private-codec hardware evidence from October 18 does not qualify public v3.
