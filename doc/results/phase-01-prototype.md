---
type: report
title: Phase 01 Synthetic Prototype Gate
created: 2026-08-27
tags:
  - teensy-daq
  - phase-01
  - verification
  - synthetic-prototype
related:
  - '[[Protocol-V1]]'
  - '[[System-Overview]]'
  - '[[ADR-001-Wire-Protocol]]'
---

# Phase 01 synthetic prototype gate

## Result

The complete autonomous Phase 01 gate passed on 2026-08-27 in
`/home/bill/agents/teensy_daq`. The implementation revision under test was
`5cd3e2d6d378b9e78ccb6b7b913acd086ac9faca`; this report and its documentation
index entry were added after that implementation run.

The gate used only the in-memory synthetic device. It did not open serial
hardware, contact a rig, use credentials, upload firmware, or require a human
decision. See [[System-Overview]] for the simulator boundary and [[Protocol-V1]]
for the generated wire contract.

| Gate | Result |
| --- | --- |
| Clean local environment and editable development install | PASS |
| Ruff format check | PASS: 20 files already formatted |
| Ruff lint | PASS: all checks passed |
| MyPy | PASS: no issues in 20 source files |
| Full Python and firmware-helper tests | PASS: 50 tests and 9,037 subtests |
| Wheel and source distribution | PASS |
| Two protocol generations plus drift check | PASS: 16 outputs unchanged |
| Synthetic demo at chunk sizes 1, 17, and 4,096 | PASS |
| Pinned Teensy 4.0 compile and HEX export | PASS; no upload attempted |

## Environment and tool identities

| Component | Identity |
| --- | --- |
| Host Python | Python 3.12.3 |
| pip | 24.0 |
| Installed distribution | `teensy-daq-local` 0.0.0, editable |
| PySerial | 3.5 |
| Ruff | 0.16.5 |
| MyPy | 2.3.1 |
| pytest | 9.1.1 |
| build | 1.6.0 |
| Isolated-build setuptools | 84.0.0 |
| Arduino CLI | 1.4.1, commit `e39419312` |
| Teensy Arduino core | `teensy:avr` 1.62.0 |
| C++ compiler | Arm GNU `arm-none-eabi-g++` 15.2.1 (15.2.Rel1, build arm-15.86) |
| Firmware target | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |

The clean environment and host gates were run with these exact commands from
the repository root:

```bash
python3 -m venv --clear .venv
.venv/bin/python -m pip install --editable './daq_api[dev]'
.venv/bin/ruff format --check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/ruff check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/mypy daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/python -m pytest -q daq_api/tests firmware/tests
.venv/bin/python -m build --outdir daq_api/dist daq_api
```

The package build created both requested formats in the gitignored
`daq_api/dist/` directory:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `teensy_daq_local-0.0.0-py3-none-any.whl` | 34,417 | `bde3b94c796fc4719875ba4dada3ccc418f92572678fcf72d9ab4e02bd866f93` |
| `teensy_daq_local-0.0.0.tar.gz` | 41,539 | `e7cecbf938f330e80c44ecd4a669e2e1046514959f6e534688eadaac804225bf` |

## Protocol regeneration and drift evidence

The generator was run twice. The first run found the 16 tracked outputs current;
the second run also changed nothing, and explicit check mode passed. Both Git
diff checks were empty.

```bash
.venv/bin/python tools/generate_protocol.py
git diff --exit-code -- daq_api/src/teensy_daq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h protocol/fixtures
.venv/bin/python tools/generate_protocol.py
.venv/bin/python tools/generate_protocol.py --check
git diff --exit-code -- daq_api/src/teensy_daq/_generated/protocol_constants.py firmware/src/generated/protocol_constants.h protocol/fixtures
```

Representative source and generated-output identities were:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `protocol/protocol-v1.json` | 17,487 | `08a7ac4ddb3b8d397b5f0ff87f4aac41c31c3b780fb3e25d2af4c68ba9b02ae6` |
| Python protocol constants | 8,491 | `b05576601bbc8d9cacf3176c1639a4c574b3570a8fcd2c798c5bfbb3a70ddb52` |
| C++ protocol constants | 11,672 | `e68b6aa32a3b188b200d87bf329e151ee3e7b3f527e1c8b54df38b7a13521f20` |
| Golden-fixture manifest | 8,723 | `b129906465e281cabd28bec1c0ac3aa86dc21eea97503965b8c9a2d280090fd2` |

These outputs implement the contract and decisions documented in
[[Protocol-V1]] and [[ADR-001-Wire-Protocol]].

## Synthetic demo evidence

Three parser boundaries were exercised with three ADC and three GPIO frames per
run:

```bash
.venv/bin/teensy-daq-demo --frame-count 3 --parser-chunk-size 1
.venv/bin/teensy-daq-demo --frame-count 3 --parser-chunk-size 17
.venv/bin/teensy-daq-demo --frame-count 3 --parser-chunk-size 4096
```

Every run reported `PASS` and the same validated acquisition facts:

- ADC and GPIO sequences were `0`, `1`, and `2`, with first-sample ticks `0`,
  `8096`, and `16192` for each stream.
- The ADC preview was the contiguous interleaved ramp `0..15`; the first frame
  ended `2020, 2021, 2022, 2023` and the next began
  `2024, 2025, 2026, 2027`.
- The GPIO preview was `0x00..0x0f`; the first frame ended
  `0xcc, 0xcd, 0xce, 0xcf` and the next began
  `0xd0, 0xd1, 0xd2, 0xd3`.
- Running and final counters were `adc=3 gpio=3 dropped=0 errors=0`.
- The final state was `IDLE`, the transport was closed, and the explicit result
  was `zero gaps, drops, or errors`.

## Firmware build evidence

The firmware helper validated the core and compiler identities, compiled the
exact FQBN, and exported binaries without invoking an upload:

```bash
.venv/bin/python firmware/tools/build_firmware.py
```

The helper recorded this underlying compile command in its gitignored build
manifest:

```bash
/usr/local/bin/arduino-cli compile --fqbn teensy:avr:teensy40:usb=serial,speed=600,opt=o2std --export-binaries --output-dir /home/bill/agents/teensy_daq/firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std /home/bill/agents/teensy_daq/firmware
```

| Exported artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 339,716 | `24d5e2db7108561919a13b37250503f874cb4f548248494a04e8b23f354613bd` |
| `firmware.ino.hex` | 60,557 | `f86cbdf262e635d26af05df4d7510401dcb991b5435eec84821c9815b6050041` |

The Teensy linker summary reported:

| Region | Used detail | Free |
| --- | --- | ---: |
| Flash | code 9,348 bytes; data 3,016 bytes; headers 9,136 bytes | 2,010,116 bytes for files |
| RAM1 | variables 3,488 bytes; code 7,632 bytes; padding 25,136 bytes | 488,032 bytes for local variables |
| RAM2 | variables 12,416 bytes | 511,872 bytes for allocation |

Arduino CLI warned that the host lacks `/etc/udev/rules.d/00-teensy.rules`.
That rule is relevant to later physical-device access, but it does not affect
this compile-only, no-upload gate.
