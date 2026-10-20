---
type: report
title: Protocol v3 fixed 600 MHz configuration evidence
created: 2026-10-20
tags:
  - protocol-v3
  - firmware
  - fixed-clock
  - local-validation
related:
  - '[[protocol-v3-upgrade]]'
  - '[[runtime-clock-dependency-audit]]'
  - '[[protocol-v3-firmware-portable]]'
  - '[[protocol-v3]]'
---

# Protocol v3 fixed 600 MHz configuration evidence

## Scope and outcome

Phase 04 establishes local fixed-clock configuration correctness and a compiled
public-v3 candidate. CPU speed is fixed at 600 MHz from startup; runtime
frequency switching is out of scope. The retained `clock-control` filename
identifies this evidence record, not a frequency-switching feature.
No PLL adapter, Teensy core patch, watchdog-policy change or USB-policy change
was introduced. Physical capture and independent clock measurements remain
pending Phase 06.

The production `FixedBuildApplication` in `firmware/src/v3_settings.h` and the
ordinary v3 simulator advertise only the normal build's 600 MHz profile.
Known generic 450 MHz IDs and historical v1/v2 records remain compatibility
data; they do not authorize that profile on the normal device.
[[protocol-v3-upgrade]] records integration and portable regression details;
[[runtime-clock-dependency-audit]] records timing consumers and build evidence.

## Supported settings and timing

The canonical source is `protocol/protocol-v3.json`; the application filters
its complete records to CPU profile 1 (600 MHz). There are **48 supported
tuples**, with these policy combinations:

| GPIO policy | ADC policy | Normal-build tuples |
| --- | --- | ---: |
| RAW | RAW | 12 |
| RAW | PACK12 | 12 |
| RLE_AUTO | RAW | 12 |
| RLE_AUTO | PACK12 | 12 |

Each row covers three stream masks (ADC, GPIO, both), two sources (HARDWARE,
SYNTHETIC), and two width/bank selections (8-bit GPIO with auxiliary bank
DISABLED, 16-bit GPIO with auxiliary bank INPUT). Every field participates in
exact tuple matching, including settings for disabled streams. All records
use wire version 3, Adler-32, 12-bit ADC resolution and rate profile 4:
1 MHz ADC pairs and 1 MHz GPIO samples. Auxiliary OUTPUT, 528 MHz and other
sample rates are not selectable. The twelve canonical 450 MHz RAW-only records
are not advertised by the normal build.

Boot defaults select both streams, HARDWARE source, 8-bit GPIO, auxiliary
DISABLED, RLE_AUTO GPIO and PACK12 ADC at 600 MHz and 1 MHz sampling.
RAW and compressed selections have identical sample timing:

| Quantity | Fixed-build value |
| --- | --- |
| CPU / IPG / ADC clock | 600 / 150 / 37.5 MHz |
| PIT / timestamp domain | 24 / 8 MHz |
| PIT0 / chained PIT1 load | 23 / 0 |
| ADC0 and GPIO sample period | 8 timestamp ticks (1 us) |
| ADC1 phase after ADC0 | 4 timestamp ticks (500 ns) |
| ADC_ETC initial delays | 0 / 75 IPG cycles |
| Calibration and ADC/GPIO stop budgets | 6,000,000 CPU cycles (10 ms) |
| Trigger diagnostic / ADC DMA alignment budgets | 1,200,000 cycles (2 ms) / 6,000 cycles (10 us) |

Clock echoes are compiled profile metadata. Core `F_CPU_ACTUAL`/`F_BUS_ACTUAL`
bookkeeping and fake-register tests do not constitute independent PLL/IPG
measurements. Peripheral register checks and the shared timing projection
verify local consistency, not physical aperture or external pin timing.

## Settings, errors and lifecycle

| Operation or condition | Verified behavior |
| --- | --- |
| INFO, capabilities, GET_SETTINGS | Agree on the fixed CPU profile, supported records and current compiled clocks. |
| CONFIGURE while stopped and fully drained | Accepts exact advertised records atomically; echoes settings/clocks. RAW/compressed/RAW changes and same-settings idempotence are covered. |
| Well-formed unsupported CPU/tuple while stopped | Correlated `UNSUPPORTED_CONFIGURATION`; prior valid settings and clocks remain unchanged. |
| Well-formed CONFIGURE while RUNNING | `INVALID_STATE`, including otherwise-valid historical 450 MHz requests; no mutation. |
| Well-formed CONFIGURE while draining | `BUSY`; no mutation until queued frames/events drain. |
| Malformed settings | Wire/field validation precedes state and support checks; state precedence above applies to well-formed requests. |
| START | Returns applied settings and a new nonzero run ID before DATA; each successful START creates a new epoch. |
| STOP/drain/reconfigure/START | Preserves stopped settings, permits reconfiguration after drain, and starts a fresh run. |
| Fresh runtime construction | Restores board defaults and run ID zero; this is portable boot coverage, not a physical reboot test. |
| V2 query / explicit V2 configuration | Query is read-only; explicit configuration retains legacy RAW layouts and compatibility metadata. Neither changes CPU speed. |

The production C++ runtime/parser/control/USB harness exchanges real wire
requests and responses with the Python SDK. The portable regression harness
accepts all 48 normal settings, then rejects all twelve historical CPU records
after each selection (576 rejections), preserving control/acquisition state,
clocks, counters and pending events. Existing generic fake-application
apply/readback/rollback failure coverage remains; it imposes no PLL failure
or runtime transition requirement. V1/v2 validators and wire contracts remain
separate from public-v3 projection.

## Candidate identity and target gates

The normal builder ran without private experiment codec flags. These are the
retained artifacts from the preceding local-validation task, not a rebuild
performed for this documentation task.

| Identity | Value |
| --- | --- |
| Build ID | `thingdaq-4c250bedb4d1bbc0` |
| Firmware input commit | `f16d463cb2b187dac4155c0301262dde16389b45` |
| Validation/documentation commit | `d1ad76a` |
| Source SHA-256 | `4c250bedb4d1bbc01bd5b302470501f6a5e53825b607bb2d9c4048983babbbb0` |
| Source-derived timestamp | `2026-10-20T05:10:58Z` |
| Toolchain | Arduino CLI 1.4.1; Teensy core 1.62.0; Arm GNU 15.2.1; `-O2` |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Output directory | `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/` |
| Manifest SHA-256 | `fc18a31ac15da45ca74643483be9a8c5a4f4dbff9d9bcc1dc85f609c82e88213` |

All 125 compile entries contain `F_CPU=600000000`,
`THINGDAQ_EXPERIMENT_CPU_HZ=600000000U` and
`THINGDAQ_RELEASE_FIXED_1MHZ=1`. The resolved `build.fcpu`, internal timing,
FQBN, output directory and manifest agree on 600 MHz. The manifest's historical
`release_policy.protocol_version=2` describes legacy fixed-rate policy, not a
restriction of the v3 control path.

| Target gate | Result |
| --- | --- |
| RAM1 locals/stack | 33,024 bytes free; minimum 32,768; margin 256 bytes |
| RAM2 heap | 4,096 bytes free; minimum 4,096; margin zero |
| Placement | Checksum flash tables, packet pages, DMA alignment/ranges, shared workspace, managed-memory overlap and linker sections passed |
| Packet storage | 200 retained pages: 105 DTCM + 95 OCRAM |
| Public codec linkage | RLE encoder and deferred-codec counters present; portable suites exercise RAW/PACK12/RLE_AUTO |

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.elf` | 2843348 | `7a4f5349b897ef7a1f220fb573963da42417bbd42a78c6dfbd1e787ae24064f8` |
| `firmware.ino.hex` | 521404 | `0017f377307e315cffe800d67fcbd2c031f46ea02ef4c94252831fba3e460261` |
| `firmware.ino.map` | 1392786 | `ac0fa82cb3dced3c13daa991dc0b565ea4578776ec473b6256298183c80ce045` |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |

Artifacts, manifest and raw logs remain ignored local outputs. The hashes and
source identity above provide the committed handoff; the binaries themselves
are not published by this evidence task.

## Exact local validation

The preceding task used these commands from the repository root:

```bash
mkdir -p .maestro/playbooks/Working/phase04-fixed600/tmp
mkdir -p .maestro/playbooks/Working/phase04-fixed600/cache
export TMPDIR="$PWD/.maestro/playbooks/Working/phase04-fixed600/tmp"
export XDG_CACHE_HOME="$PWD/.maestro/playbooks/Working/phase04-fixed600/cache"
export ARDUINO_BUILD_CACHE_PATH="$PWD/.maestro/playbooks/Working/phase04-fixed600/cache/arduino"
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python -m ruff format --check daq_api firmware tools
.venv/bin/python -m ruff check daq_api firmware tools
.venv/bin/python -m mypy daq_api/src/thingdone_daq
.venv/bin/python -m pytest firmware/tests daq_api/tests -q -ra --tb=short
python3 firmware/tools/build_firmware.py
.venv/bin/python -m pytest firmware/tests/test_rig_checksum_benchmark.py firmware/tests/test_rig_gpio_capture.py -q -ra --tb=short
.venv/bin/python -m pytest daq_api/tests/test_documentation_integrity.py -q
git diff --check
```

| Gate | Recorded result |
| --- | --- |
| Generator drift | 142 outputs passed |
| Ruff 0.16.5 | Formatting passed for 198 files; lint passed |
| mypy 2.3.1 | 33 SDK sources passed |
| Full maintained suite, pytest 9.1.1 | 2,497 passed, 2 failed, 5 skipped; 16,820 subtests passed in 266.31 s |
| Both affected modules rerun unchanged in isolation | 13 passed; 29 subtests passed in 1.28 s |
| Documentation after prior edits | 4 passed; 1,082 subtests passed |
| Normal target build | Toolchain, memory and placement gates passed |
| Source/artifact inspection | Source fingerprint, four artifact sizes/hashes and 125 compile entries verified |
| Diff whitespace | Passed |

All **2,499 unique tests** passed across the full invocation and focused
recheck; the full invocation itself was not uniformly green. Its failures
were fake-serial wall-clock throughput checks:
`test_selected_campaign_benchmarks_and_streams_only_one_candidate` measured
1,347,008 ADC payload bytes/s against a 2,000,000 lower bound, and
`test_full_program_runs_diagnostics_streams_status_and_stops` measured
2,664,815 GPIO samples/s against a 3,200,000 lower bound.
Both modules passed without code changes, threshold relaxation or disabled
tests. The five skips explicitly cover three historical fixed-rate/equal-rate
combinations and two historical 450 MHz RAW-only compressed layouts.

The initial unscoped pytest invocation collected ignored archived scratch
copies and produced 832 collection/import errors. The maintained-directory
command above avoids those copies. The prior task also corrected README
snippet formatting before rerunning its gates. Neither correction changed
firmware or required limits. Raw logs and `artifact-verification.json` are
retained under `.maestro/playbooks/Working/phase04-fixed600/`.

For this documentation handoff, reran:

```bash
TMPDIR="$PWD/.maestro/playbooks/Working" .venv/bin/python -m pytest daq_api/tests/test_documentation_integrity.py -q
git diff --check
```

Result: **4 passed, 1,090 subtests passed**. An additional local inspection
checked front matter fields/dates, all 48 schema tuples and policy counts,
the current firmware source fingerprint, manifest hash, four artifact
sizes/hashes, RAM values and all 125 compile entries against this report.
All checks passed. The firmware suites and target build above were retained
from the preceding task, not rerun for these documentation-only changes.

## Qualification boundary

NOT_RUN in Phase 04: flashing, rig access, physical public-v3 capture,
independent clock/aperture measurements, on-device reboot testing, sustained
USB/host throughput and thermal/on-device qualification. These remain Phase 06
work. Historical private-codec/450 MHz hardware results are not public-v3
qualification. Missing local Teensy udev rules did not prevent compilation;
no system configuration was changed.

This evidence task changes documentation only. No task images were supplied
or analyzed.
