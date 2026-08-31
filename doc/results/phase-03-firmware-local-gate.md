---
type: report
title: Phase 03 Firmware Local Gate
created: 2026-08-28
tags:
  - thingdaq
  - phase-03
  - firmware
  - control-plane
  - verification
related:
  - '[[System-Overview]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[Phase-02-Protocol-Python]]'
---

# Phase 03 firmware local gate

## Result

The complete offline Phase 03 gate passed on 2026-08-28 in
`/home/bill/agents/thingdaq`. The implementation revision at the start of the
gate was `59e9f9630685681b23b3aa2f9bfc5a3d92720c15`; this report and the build
gate repair are recorded by the following `MAESTRO` commit. The exact firmware
input fingerprint is
`39300273210c1c89964c5c5cc56ae76ca7b6e800471d94acaa24f6b30de0ff5a`,
which produces build ID `thingdaq-39300273210c1c89`.

The gate used generated protocol assets, the Python simulator/fake serial
peers, host-compiled portable C++ executables, and a compile-only Teensy build.
It did not enumerate or open a serial port, contact the live rig, use
credentials, or upload firmware. Live acceptance remains a separate step after
this frozen local candidate. See [[System-Overview]], [[Firmware-Resource-Map]],
and [[Protocol-V1]] for the boundaries under test.

| Gate | Result |
| --- | --- |
| Protocol regeneration and drift check | PASS: all 20 outputs current |
| Ruff format and lint | PASS: 40 files formatted; no findings |
| MyPy | PASS: no issues in 40 source files |
| Python and host-C++ tests | PASS: 140 tests and 9,830 subtests |
| Exact Teensy build | PASS: clean compile with all warnings enabled |
| HEX identity inspection | PASS: ELF and HEX decode identically; expected build/product identity present |
| Linker-map/resource inspection | PASS: no change from the integrated Phase 03 baseline and no acquisition allocation |
| Upload | NOT RUN: deliberately excluded from this gate |

## Quality-gate repair

The first compile passed, but review found that the existing helper inherited
Arduino CLI's `--warnings none` default and did not retain a linker map. That
made two requirements of this gate unverifiable. `firmware/tools/build_firmware.py`
now:

- requests a clean compile with `--warnings all` while retaining the exact
  pinned FQBN;
- adds only `-Wl,-Map=<path>,--cref` to the core's resolved linker flags and
  requires the fresh map alongside the HEX;
- hashes the map in the gitignored build manifest; and
- records resolved board/CPU/USB/optimization properties, parsed Flash/RAM
  usage, the Git revision, and dirtiness of the exact firmware input set in
  manifest schema 3.

Focused tests cover the immutable command and exact memory-summary parser. No
firmware runtime behavior or firmware input changed during this repair.

## Host gate

| Component | Identity |
| --- | --- |
| Host | Linux 6.17.0-35-generic, x86-64 |
| Python | CPython 3.12.3 |
| Host C++ compiler | Ubuntu GCC 13.3.0 |
| Ruff | 0.16.5 |
| MyPy | 2.3.1 |
| pytest | 9.1.1 |

The following commands were run from the repository root:

```bash
.venv/bin/python tools/generate_protocol.py
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/ruff format --check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/ruff check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/mypy daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/python -m pytest -q daq_api/tests firmware/tests
```

Generation reported all 20 outputs current before and after the gate. The
tracked source and representative generated identities are:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `protocol/protocol-v1.json` | 25,246 | `216b389103267b1d51e65c29ffc06405dbd7ac5e1fd069eb82af9e95a57fde16` |
| Python protocol constants | 13,233 | `bc9bb46ef5865243f8486561163ba0d4b76cbb75b59751d653818720206af534` |
| C++ protocol constants | 15,064 | `b0c6293a308f5cf92dcee34d88750b226329f92b972b95e657ef0c6ba849a9f7` |
| Golden-fixture manifest | 11,388 | `16933ebe1a710b8b870c12c87f2d21ecf9f7484b5575ed72fd4fea6cfc7d0466` |

The host-C++ wrappers compile the production protocol, state, statistics,
transport, and runtime sources as C++17 with `-Wall`, `-Wextra`, `-Werror`,
conversion warnings, pedantic checks, exceptions disabled, and RTTI disabled.
The complete test result also includes every Python API, fake-serial,
cross-language golden-frame, independent rig-script, resource-registry, and
source-boundary test.

## Pinned firmware candidate

The only firmware command invoked was the compile-only helper:

```bash
.venv/bin/python firmware/tools/build_firmware.py
```

The complete expanded command is retained in
`firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json`.
No command contained `--upload`.

| Property | Resolved value |
| --- | --- |
| Arduino CLI | 1.4.1, commit `e39419312` |
| Teensy core | `teensy:avr` 1.62.0 |
| Compiler | Arm GNU `arm-none-eabi-g++` 15.2.1, 15.2.Rel1 build arm-15.86 |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Board | `TEENSY40` / i.MX RT1062 |
| CPU menu | 600 MHz (`build.fcpu=600000000`) |
| USB menu | Serial (`build.usbtype=USB_SERIAL`) |
| Optimization menu | Faster (`opt=o2std`, standard libc, `build.flags.optimize=-O2`) |
| Language mode | GNU C++17 |
| Warning mode | Arduino CLI `all` |
| Build timestamp | `2026-08-28T06:29:36Z`, latest firmware-input commit policy |
| Firmware inputs | Clean at baseline revision; no generated drift |

The all-warnings build emitted no compiler or linker diagnostic. Arduino CLI
reported only the missing host file `/etc/udev/rules.d/00-teensy.rules`. That
rule is needed for later local physical-device access, not for compilation or
the service-owned rig path, and no upload was attempted here.

## Flash and RAM review

| Region | Current candidate | Integrated Phase 03 baseline | Delta |
| --- | ---: | ---: | ---: |
| Flash code | 22,368 bytes | 22,368 bytes | 0 |
| Flash initialized data | 4,040 bytes | 4,040 bytes | 0 |
| Flash headers | 8,404 bytes | 8,404 bytes | 0 |
| Flash free for files | 1,996,804 bytes | 1,996,804 bytes | 0 |
| RAM1 variables | 10,080 bytes | 10,080 bytes | 0 |
| RAM1 code | 20,648 bytes | 20,648 bytes | 0 |
| RAM1 alignment padding | 12,120 bytes | 12,120 bytes | 0 |
| RAM1 free for local variables | 481,440 bytes | 481,440 bytes | 0 |
| RAM2 variables | 12,416 bytes | 12,416 bytes | 0 |
| RAM2 free for heap | 511,872 bytes | 511,872 bytes | 0 |

Total Flash occupancy is 34,812 of 2,031,616 bytes (1.71%). RAM1 reserves
42,848 of 524,288 bytes including ITCM code and alignment (8.17%); RAM2 uses
12,416 of 524,288 bytes (2.37%). Compared with the tracked Phase 01 prototype,
the completed control plane adds 13,312 total Flash bytes and 6,592 RAM1
variable bytes while RAM2 remains unchanged. This growth is accounted for by
the protocol parser, typed control dispatcher, fixed queues, statistics, and
runtime coordinator.

The exported map provides the more specific ownership check:

| Map item | Size | Finding |
| --- | ---: | --- |
| `.bss` | 6,304 bytes | Bounded ordinary zero-initialized state |
| `firmware_runtime` | 5,232 bytes | Expected fixed command/response queues and control state |
| `.bss.dma` | 12,416 bytes | Entirely the Teensy USB core descriptor and 4 KiB RX / 8 KiB TX buffers |
| `thingdaq::identity::kBuildId` | 22 bytes | Expected `thingdaq-` identity storage |
| `usb_string_product_name` | 22 bytes | Strong sketch-owned UTF-16 `ThingDAQ` descriptor |
| `usb_string_serial_number` | 22 bytes | Core-owned chip-derived serial descriptor alias |

There is no ADC/GPIO acquisition ring, PIT/XBAR/ADC_ETC/eDMA allocation, or
other unexplained large project symbol in this control-only image. This agrees
with [[Firmware-Resource-Map]] and the Phase 03 capability mask.

## Exported artifact and identity inspection

| Exported artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 542,412 | `301d40ea4f2f549e9da2226c2cc16287dba0f10a83bd28d0f143984ac250effd` |
| `firmware.ino.hex` | 98,010 | `7cd252bb37badf9e82de5c625b0e2caa8eadfd731a4c99003dec6509243a01b4` |
| `firmware.ino.map` | 586,789 | `1d72c625a2010628c20aa11ce5c860f2706b35207fdf52501c37f89d7a4fcbe4` |

Arm `objcopy` decoded the exported ELF and Intel HEX independently. The two raw
images compared byte for byte and both had SHA-256
`ec93d7ea00be3b7a5ea09335bb5b52fefaa9e148af7d4f7eeac42690477ebef8`.
Inspection of the HEX-derived bytes found ASCII build ID
`thingdaq-39300273210c1c89` and UTF-16LE product name `ThingDAQ`. The map places
the build ID in the production control object, the strong product descriptor
in `teensy_usb.cpp`, and the serial descriptor in the untouched Teensy core.
Together, the manifest, HEX inspection, and map inspection bind the candidate
to the clean source fingerprint before any upload or rig submission.
