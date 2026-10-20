---
type: report
title: Public protocol v3 local gates and distributable builds
created: 2026-10-20
tags:
  - protocol-v3
  - validation
  - distribution
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-migration]]'
  - '[[protocol-v3-qualification]]'
---

# Public protocol v3 local gates and distributable builds

This checkpoint validates local builds for firmware and SDK 1.2.0 at source
revision `735fb8d098bfa7579c73e995300ebea107b4b25f`, with the accompanying
pytest discovery configuration and documentation changes. Firmware, SDK,
qualification-runner inputs and historical evidence are unchanged.
Physical qualification remains **NOT_RUN**. Candidate freezing and Phase 06
inputs are the next playbook task; these development builds are not a frozen
release candidate.

The contract and migration paths are documented in [[protocol-v3]] and
[[protocol-v3-migration]]. [[protocol-v3-upgrade]] records the architecture;
[[protocol-v3-qualification]] defines the later physical evidence requirements.

## Test discovery

The initial bare `python -m pytest` failed collection with 833 errors because it
also searched ignored historical checkouts in `benchmark-scratch/` and archived
rig clients under `doc/results/raw/`. Root `pytest.ini` now selects the existing
`firmware/tests` and `daq_api/tests` suites, matching the previously documented
explicit command. No test assertions, thresholds or test files were removed.
Default and explicit collection produced the same 2,653 ordered test IDs.

## Local gates

All required local gates passed:

| Gate | Result |
| --- | --- |
| Protocol generation | 142 generated files current |
| Ruff formatting and lint | 203 files formatted; lint passed |
| SDK mypy | 34 source files passed |
| Bare `python -m pytest` | 2,648 passed, five expected unsupported-combination skips, 324.62 seconds |
| Historical soak generation | Current; no artifacts rewritten |
| Standalone/installed soak conformance | PASS |
| Standard target build | PASS, including unchanged binary gates |
| Wheel/sdist and strict Twine | PASS for both artifacts |
| Isolated installed-wheel offline demo | PASS |
| Whitespace validation | `git diff --check` passed |

The complete full-suite run passed on its first execution after the discovery
fix, including throughput thresholds; no failing test was retried or weakened.
Full-suite log SHA-256:
`d4127e98c6489788069a55b028de8fd18a19b8b3cf8260fe4f022c9c8102aa09`.

```bash
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
TMPDIR="$PWD/.maestro/playbooks/Working" .venv/bin/python -m pytest
.venv/bin/python firmware/tools/generate_soak_programs.py --check
.venv/bin/python firmware/tools/check_soak_conformance.py
git diff --check
```

## Standard firmware build

The default builder ran without inherited experiment settings or caller flags:

```bash
env -i PATH="$PATH" HOME="$HOME" TMPDIR="$PWD/.maestro/playbooks/Working" \
  .venv/bin/python firmware/tools/build_firmware.py
```

The unchanged placement, memory-headroom and allocation-ownership gates passed.
Arduino CLI 1.4.1, Teensy core 1.62.0 and Arm GNU 15.2.1 compiled
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`. RAM1 has 33,024 bytes
free for locals; RAM2 has 4,096 bytes free for heap. The build manifest records
clean firmware inputs and build ID `thingdaq-67539aafb5b130a5`.
Defaults remain fixed CPU 600 MHz, ADC/GPIO 1 MHz, auxiliary DISABLED,
GPIO RLE_AUTO and ADC PACK12. The builder supplies its internal timing macros;
no private codec flags are required.

Build output directory:
`firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/`.
The toolchain emitted its existing missing-udev-rule warning; compilation and
binary checks succeeded. This task did not upload firmware or contact the rig.

| Artifact in build output | SHA-256 |
| --- | --- |
| `firmware.ino.hex` | `2a64e61f071b4ff9d981c3ea0217049dd40b64fad2ae448267a70c5b47fd25e7` |
| `firmware.ino.elf` | `8588c3e54a092b78c2afc9f175fe9f2002210ebc22f5d95540de0f0c6708c0c5` |
| `build-manifest.json` | `db670798642394eea9bd4c8dda1862b8f695fce883dcd825a5cec2fdb2f15824` |

## Python distributions and installed demo

Built with the existing isolated setuptools backend and package source epoch:

```bash
package_source_epoch="$(git log -1 --format=%ct -- daq_api)"
SOURCE_DATE_EPOCH="$package_source_epoch" TMPDIR="$PWD/.maestro/playbooks/Working" \
  .venv/bin/python -m build \
  --outdir .maestro/playbooks/Working/phase05-gates-dist daq_api
.venv/bin/python -m twine check --strict \
  .maestro/playbooks/Working/phase05-gates-dist/*
.venv/bin/python -m venv .maestro/playbooks/Working/phase05-gates-installed
TMPDIR="$PWD/.maestro/playbooks/Working" \
  .maestro/playbooks/Working/phase05-gates-installed/bin/python \
  -m pip --no-cache-dir install \
  .maestro/playbooks/Working/phase05-gates-dist/thingdone_daq-1.2.0-py3-none-any.whl
.maestro/playbooks/Working/phase05-gates-installed/bin/python \
  -I -m thingdone_daq.protocol_upgrade
```

Wheel and sdist both passed strict Twine checks. The fresh virtual environment
has no editable package install or system site packages; isolated Python ran
the wheel's module. The demo passed three exact v3 captures, RLE/RAW fallback,
stopped readback, reset and v1/v2 compatibility checks, with complete cleanup.
Its clock changes are simulator coverage, not physical CPU-switching support.
No package was published remotely.

| Artifact under `.maestro/playbooks/Working/` | SHA-256 |
| --- | --- |
| `phase05-gates-dist/thingdone_daq-1.2.0-py3-none-any.whl` | `8ba2f35029405407582ef699e4cad3b2d3a210c93d11ffc0b64cff3eb36ee51c` |
| `phase05-gates-dist/thingdone_daq-1.2.0.tar.gz` | `83a863fd59d07701e95eb068f124f66b9f8442bc43331dd37a2ed23a3edaf04d` |
| `phase05-gates-offline-demo.log` | `53f9de65c963d6093c0f52f548250dfd2ea7211345c67fb2a43cef5f348b83b0` |

Ignored local logs and package artifacts use prefix
`.maestro/playbooks/Working/phase05-gates-`. The tables retain artifact identities
in version control; the next task must freeze and bind its exact clean-source
firmware, SDK and runner inputs.
