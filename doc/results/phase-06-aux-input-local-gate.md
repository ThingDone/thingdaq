---
type: report
title: Phase 06 Auxiliary Input Local Gate
created: 2026-09-04
tags:
  - thingdaq
  - phase-06
  - auxiliary-input
  - firmware
  - verification
related:
  - '[[Aux-Input-Prototype]]'
  - '[[ADR-007-Experimental-Aux-Input-Bank]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Hardware-Safety]]'
---

# Phase 06 auxiliary input local gate

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

## Result

The complete offline gate passed on 2026-09-04 for source commit
`3a703ffd030ff2b5c7fdb46ea7e738ea962fff77` on
`experiment/aux-input-bank`. Protocol drift, focused target and portable tests,
both GPIO-width throughput gates, static analysis, documentation/layout tests,
the full regression suite, and two exact Teensy builds all passed. The branch
was clean and matched `origin/experiment/aux-input-bank` before the report-only
checkpoint commit.

This gate used no serial port, upload, live target, or external stimulus. It
qualifies the local implementation and the 12 MB/s host-processing hypothesis;
it does not establish sustainable USB/target throughput or physical D16-D23
transition fidelity. Those claims remain reserved for the sequential rig
campaign described by [[ADR-007-Experimental-Aux-Input-Bank]] and bounded by
[[Hardware-Safety]].

| Gate | Result |
| --- | --- |
| Protocol generation/drift | PASS: all 99 outputs current |
| Focused target/portable/Python/fake-rig tests | PASS: 94 tests, 2 dependency skips, 2,685 subtests |
| 8-bit and 16-bit packer/parser throughput | PASS: 10 tests and 22 subtests |
| Ruff format/lint | PASS: 130 files formatted; no findings |
| MyPy production package | PASS: no issues in 27 source files |
| Documentation/layout tests | PASS: 22 tests and 751 subtests |
| Full regression suite | PASS: 506 tests and 15,989 subtests |
| Exact Teensy builds | PASS: two byte-identical builds |
| Upload/live rig | NOT RUN: deliberately excluded from the local gate |

## Throughput headroom

The one-bank 8-bit packer exceeded its 40 MB/s local threshold against the
4 MB/s GPIO payload target. The dual-bank 16-bit packer processed
1,594.798 MB/s, or 199.350 times the 8 MB/s GPIO payload target, exceeding its
required tenfold headroom. The legacy 8-bit parser's slowest randomized chunk
profile retained 2.638 times its 8.094862 MB/s framed target.

The 16-input combined parser, typed decoder, and synthetic-formula validator
processed the complete 12 MB/s payload hypothesis. Its slowest randomized
chunk profile sustained 23.865 MB/s framed throughput, or 1.958 times the
12.189723 MB/s framed target, above the required 1.25 ratio. These are local
x86-64 host measurements and are not target-runtime or physical-USB
acceptance.

## Deterministic target build and memory

Both clean builds used Arduino CLI 1.4.1, Teensy core 1.62.0, Arm GNU 15.2.1,
and exact FQBN
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`. They produced build ID
`thingdaq-c1f05b3a2ebfc8b3` and identical hashes:

| Artifact | SHA-256 |
| --- | --- |
| Build manifest | `682c66df9d4d45b3441d576bc63bad106970c14293ee71186fbf42087fec1fc5` |
| ELF | `a10f0b19a2cc2a07f46b6d0b20c84b67e8f9862ddaaea9f027389db665ed7741` |
| HEX | `6ade9731134a87475672607d746cb2b338fb923ccc72a7aeb04a075a88c9cb95` |
| Linker map | `1b9e1cb295ea9975e4e92089dce25c545566713b2e8c10a3bf9c48edd63600ff` |
| EEPROM image | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |

The linked image uses 125,120 flash code bytes and preserves 34,528 bytes of
RAM1 local/stack space and the required 4,096-byte RAM2 heap floor. The
manifest validates 13 managed allocations with no overlap, retains the exact
105-DTCM plus 95-OCRAM packet split and 200 total frames, and records no packet
capacity change.

Complete combined packet retention remains exact for every profile:

| ADC/GPIO profile | 8-input retention | 16-input retention |
| --- | ---: | ---: |
| 1 MHz / 4 MHz | 101.200 ms | 50.600 ms |
| 500 kHz / 2 MHz | 202.400 ms | 101.200 ms |
| 250 kHz / 1 MHz | 404.800 ms | 202.400 ms |
| 125 kHz / 500 kHz | 809.600 ms | 404.800 ms |

The v1/default compatibility tests preserve the D6-D13 map, one-byte GPIO
layout, public v1 offsets and semantics, fixed primary resource assignments,
and frozen protocol-v1 hash. See [[Acquisition-Pipeline]] for lifecycle and
ownership details and [[Aux-Input-Prototype]] for the earlier protocol and
simulator evidence.

## Reproduction

Commands were run from the isolated auxiliary-input worktree. `PYTHONPATH` was
set explicitly for pytest because the shared virtual environment also contains
an older editable checkout; this prevents that unrelated path from shadowing
the branch under test.

```bash
.venv/bin/python tools/generate_protocol.py --check
PYTHONPATH=daq_api/src .venv/bin/python -m pytest -q \
  firmware/tests/test_gpio_register_configuration.py \
  firmware/tests/test_gpio_raw_capture.py \
  firmware/tests/test_combined_acquisition.py \
  firmware/tests/test_build_configuration.py \
  firmware/tests/test_aux_input_portable.py \
  firmware/tests/test_aux_input_stress.py \
  firmware/tests/test_rig_aux_input_capture.py \
  daq_api/tests/test_aux_input_contract_properties.py \
  daq_api/tests/test_aux_input_cross_language.py \
  daq_api/tests/test_aux_input_end_to_end.py \
  daq_api/tests/test_aux_input_protocol_v2_vectors.py \
  daq_api/tests/test_aux_input_python_surface.py \
  daq_api/tests/test_aux_input_v2_contract.py \
  daq_api/tests/test_protocol_generation_drift.py
PYTHONPATH=daq_api/src .venv/bin/python -m pytest -q -s \
  firmware/tests/test_gpio_batch_packer.py \
  firmware/tests/test_aux_input_packer_throughput.py \
  daq_api/tests/test_streaming_correctness_performance.py \
  daq_api/tests/test_aux_input_throughput.py
.venv/bin/ruff format --check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/ruff check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/python -m mypy daq_api/src/thingdaq
PYTHONPATH=daq_api/src .venv/bin/python -m pytest -q \
  daq_api/tests/test_documentation_integrity.py \
  daq_api/tests/test_repository_layout.py \
  daq_api/tests/test_distribution_artifacts.py \
  firmware/tests/test_portable_source_boundaries.py \
  firmware/tests/test_firmware_identity_resources.py
PYTHONPATH=daq_api/src .venv/bin/python -m pytest -q
.venv/bin/python firmware/tools/build_firmware.py
.venv/bin/python firmware/tools/build_firmware.py
```
