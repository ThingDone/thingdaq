---
type: report
title: Phase 10 Package Workflows
created: 2026-08-29
tags:
  - thingdaq
  - phase-10
  - python-package
  - hardware-validation
  - user-workflows
related:
  - '[[Phase-10-Package-Local-Gate]]'
  - '[[Phase-09-Loss-Recovery]]'
  - '[[Python-API]]'
  - '[[API-Reference]]'
  - '[[Calibration]]'
  - '[[Hardware-Safety]]'
  - '[[Protocol-V1]]'
---

# Phase 10 package and physical workflows

## Outcome

The Phase 10 package workflow gate passed on 2026-08-29. A clean pinned-target
firmware recompile reproduced the intended production HEX, ELF, and map byte
for byte. One sequential remote-rig job then flashed that image and passed all
352 identity, capability, physical combined-stream, live STATUS, raw-layout,
loss, STOP, and final-reconciliation checks. The accepted capture ran for
60.001437 seconds, delivered 59,546 complete ADC frames and 59,546 complete
GPIO frames, and ended IDLE with zero complete-frame or payload-byte loss.

This physical result closes the hardware boundary left explicit by
[[Phase-10-Package-Local-Gate]]. It does not replace that report's package,
clean-install, typing, console, simulator, or example evidence. No package was
published, no personal calibration was loaded, and no task-associated images
were present; zero images were analyzed.

| Gate | Result |
| --- | --- |
| Production firmware rebuild | PASS; pinned Teensy 4.0 toolchain and clean firmware inputs |
| Intended acquisition/checksum artifact | PASS; HEX/ELF/map byte-identical to the accepted Phase 09 image |
| Rig identity and capabilities | PASS; exact serial, build ID, firmware, protocol, masks, rates, resolution, pins, and resources |
| Physical combined capture | PASS; 60.001437 s, 1 MHz ADC pairs plus 4 MHz packed GPIO |
| Live STATUS | PASS; 121 samples, no counter regression or inconsistent configuration |
| Raw interpretation | PASS; independent little-endian ADC-pair and packed D6-D13 checks |
| Loss and STOP | PASS; zero complete-frame/payload loss and exact bounded partial-tail accounting |
| Final reconciliation | PASS; 123 host/firmware commands, all queues empty, stream mask zero, IDLE |
| Package matrix carried forward | PASS; retained artifacts rehashed and `daq_api` unchanged since the local gate |

## Rebuilt production image

`firmware/tools/build_firmware.py` compiled the current clean firmware inputs
with Arduino CLI 1.4.1, Teensy core 1.62.0, Arm GNU 15.2.1, 600 MHz, USB
Serial, `-O2`, and all warnings enabled. The target was
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`. The resulting source
fingerprint and build ID remained
`ea010335c9b63bb7008e7c18fc911ac87df69ebdeacfdde27f5bb54a12f4fa85`
and `thingdaq-ea010335c9b63bb7`.

The new manifest binds the build to repository revision
`f36f606b0691a289365d1d90f35b058a4da2e53e` and reports no changed firmware
inputs. Its invocation timestamp/provenance differs from the retained Phase 09
manifest, but every program artifact is byte-identical. The artifact equality,
not a remembered filename, was required before submission.

| Artifact | Bytes | SHA-256 | Intended-image comparison |
| --- | ---: | --- | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` | unchanged build output |
| `firmware.ino.elf` | 1,791,648 | `9337ac3ddbeb0461e48bc8050422c446bb0f4f216058b0d2e32f148370e1c292` | byte-identical |
| `firmware.ino.hex` | 351,467 | `6bb2c355ed59e3dc59109de9fc954daeb8440329996a3b5efbaf65f15781e769` | byte-identical; submitted image |
| `firmware.ino.map` | 828,851 | `92ea75bcfcbedcb4c331f40670b43760e2c2fbe2ff89050e027b56c116b0e1a8` | byte-identical |
| `build-manifest.json` | 12,789 | `8850d9a12f7acbfd4ccffa55498f49ca05afede91a6779e1ea23e51f4564d0e9` | new provenance manifest |

The linker/build gates reported 92,812 code bytes, 23,496 initialized-data
bytes, 8,616 header bytes, 34,560 RAM1 bytes free for locals/stack, and 20,800
RAM2 bytes free for heap. The local host's missing optional Teensy udev rule
produced a build-time warning only; the image was uploaded by the remote
headless loader, which found HalfKay, programmed 124,928 decoded bytes, booted,
and re-enumerated the target without a manual reset or unplug.

## Distribution artifacts and clean-install evidence

The package artifacts remain those independently built from revision
`f34ba96651a417bd1b26ab30ac0f8940f96684b9` in
[[Phase-10-Package-Local-Gate]]. Only reports changed between that package
revision and this hardware run: `daq_api/`, `firmware/`, and `protocol/` have
no diff. The retained archives were rehashed before this report was written.

| Build | Artifact | Bytes | Archive SHA-256 |
| --- | --- | ---: | --- |
| A | `thingdaq_local-0.10.0-py3-none-any.whl` | 178,111 | `47759ba1a74d7465f8c06ffb40e2656778701245a6285b193ced04deb818f7d3` |
| B | `thingdaq_local-0.10.0-py3-none-any.whl` | 178,111 | `47759ba1a74d7465f8c06ffb40e2656778701245a6285b193ced04deb818f7d3` |
| A | `thingdaq_local-0.10.0.tar.gz` | 195,939 | `67285e6a10cd1d384e01e438f0b54ee12404e61924c646aa25ce538913e52f22` |
| B | `thingdaq_local-0.10.0.tar.gz` | 195,928 | `831be5170b8ed2f498724eaa1c4bc241d39ad0722861347eab6f80f498c5a420` |

The wheels are byte-identical and their 29 normalized members share digest
`35c6ba0082be054b54ed851b5f2ed2b2707c1f0087964f1cf2437aaba5f76af3`.
The gzip-wrapped source archives differ at the container level, as reported,
while all 45 normalized paths, modes, and file bodies share digest
`eb7a949827a01e428aa365d66194987132a5429a3b7e4cecdfd58fd46327d3d7`.

| Local package result | Accepted result |
| --- | --- |
| Full suite without NumPy | 363 passed, 7 expected skips, 13,815 subtests |
| Full suite with NumPy 2.5.2 | 370 passed, no skips, 13,815 subtests |
| Base-only wheel installs | CPython 3.10.19, 3.11.14, 3.12.3, 3.13.12, and 3.14.3 on Linux x86-64 |
| Source install | CPython 3.12.3 with development and NumPy extras |
| Dependency/import/type gates | `pip check`, isolated import/version/`py.typed`, wheel and sdist MyPy consumers passed |
| Installed console/simulator gates | INFO, bounded strict-loss monitor, and the complete two-stream demo passed |
| Installed examples | All nine examples passed in every wheel environment and the source environment |

Those installed examples used their bounded simulator defaults. The physical
job below independently grades the firmware/wire behavior they rely on; it is
not presented as a second clean-install matrix.

## Rig job identity and preflight

The service and downloaded client were version 1.0.0 on API v1. Secret-free
preflight and postflight health responses both reported coordinator mode
`normal`, a live worker, reachable Docker and hub, and queue depth zero. The
deployed client hash matched the retained client before submission. The API
key was supplied transiently through `FW_API_KEY`; it was not printed, logged,
copied into the working directory, or committed.

| Property | Value |
| --- | --- |
| Job ID | `292d0a5b-0344-41c9-b3aa-6a3e660fa51d` |
| Client UTC interval | `2026-08-29T14:49:00Z` to `2026-08-29T14:50:12Z` |
| Board / MCU | Teensy 4.0 / i.MX RT1062 |
| Hub port / rig serial port | 15 / transient `/dev/ttyACM0` |
| Stable hardware serial | `20512460` (required exactly by the acceptance program) |
| Protocol / firmware | protocol 1 / firmware 0.7.0 |
| Build ID | `thingdaq-ea010335c9b63bb7` (required exactly by the acceptance program) |
| Capability / configuration masks | `0x1ff` / `0x3f` |
| Supported stream / source / checksum masks | `0x3` / `0x3` / `0x0e` |
| Applied configuration | ADC + GPIO, physical hardware, Adler-32, 4,096-byte frames |
| Capture / warmup / STATUS interval | 60 s / 0.25 s / 0.5 s |
| Acceptance result | PASS; 352 checks, no failures |

An initial local client invocation used the package-test virtual environment,
which deliberately lacks `requests`, and stopped at import time before
contacting `/start`. It created no job ID and caused no hardware activity. The
table above identifies the sole submitted and accepted job.

## Sequential user-flow evidence

The self-contained program used only Python 3.13, the standard library, and
PySerial inside the rig's network-disabled container. It did not import the
project package or generated constants, so its checks remain independent of
the host implementation.

1. Two synchronized INFO responses matched exactly. The program pinned serial
   `20512460`, build ID `thingdaq-ea010335c9b63bb7`, protocol v1, firmware 0.7.0,
   both stream/source profiles, all three checksums, fixed rates, 12-bit ADC
   metadata, A0/A1 and D6-D13 routes, trigger phase, DMA resources, and packet
   geometry.
2. The non-driving GPIO diagnostic retained D6-D13 as inputs and independently
   checked DMA routing, raw-word-to-packed-byte mapping, and bounded capture
   accounting. No output was driven.
3. CONFIGURE applied and echoed `[streams=3, source=0, checksum=1,
   frame_bytes=4096]`. INFO and STATUS retained that exact configuration.
4. START echoed the same configuration and created run ID 1. During the
   capture, 121 live STATUS requests retained the same run/configuration,
   monotonically advanced all stage counters, and reported no loss or fault.
5. Every data frame was independently checksummed and decoded. ADC payloads
   were interpreted as 1,012 little-endian `(ADC0/A0, ADC1/A1)` 16-bit pairs;
   GPIO payloads remained 4,048 packed bytes with D6 at bit 0 through D13 at
   bit 7. This was explicitly raw, uncalibrated interpretation.
6. STOP returned IDLE for run 1. A final STATUS reconciled every complete
   acquisition, framing, packet, USB, host, and command counter and confirmed
   empty queues and stream mask zero.

## Capture, STATUS, and raw-data results

| Metric | Result |
| --- | ---: |
| Timed capture | 60.001436996 s |
| Complete ADC / GPIO frames | 59,546 / 59,546 |
| Delivered ADC pairs / ADC0 codes / ADC1 codes | 60,260,552 / 60,260,552 / 60,260,552 |
| Delivered GPIO packed samples | 241,042,208 |
| Total delivered payload | 482,084,416 bytes |
| ADC pair rate | 1,000,000.717 pairs/s |
| GPIO sample rate | 3,999,935.402 samples/s |
| Combined payload rate | 7,999,938.269 bytes/s |
| Final ADC / GPIO timestamp | 482,084,416 / 482,084,416 ticks |
| Maximum wire skew | 1 equal-coverage frame |
| Checksummed host data frames | 119,224 |
| Maximum receive gap | 44.674 ms |
| STATUS samples / p99 / maximum | 121 / 2.815 ms / 20.972 ms |
| Maximum all-command latency | 20.972 ms |
| Host peak RSS growth | 389,120 bytes |

The raw observed ADC0/A0 range was 904-1,671 and the ADC1/A1 range was
949-1,722, both within the advertised 0-4,095 code range. Every GPIO byte was
`0x20`, within the expected 0-255 packed range. These are transport/layout
observations only. No calibration record was supplied, so no result is a
calibrated voltage; the raw codes remain the authority described by
[[Calibration]].

No analog fixture or external digital stimulus declaration was present. The
job therefore does not grade ADC accuracy, offset, gain, noise, bandwidth,
sample-and-hold aperture, GPIO thresholds, or external transition timing. The
safe electrical and tested-versus-untested boundaries remain those in
[[Hardware-Safety]].

## Zero-loss and final counter reconciliation

All complete-frame and payload-byte drop counters were zero. No sequence or
timestamp gap, checksum/parser damage, stale response, host queue eviction,
ADC/GPIO ring overrun, converter overwrite, ADC_ETC/eDMA fault, packet
exhaustion, command/state error, transport error, USB I/O error, partial USB
write, or source/pipeline/chronology invariant occurred.

| STOP accounting | Captured | Complete delivered | Explicit partial tail | Check |
| --- | ---: | ---: | ---: | --- |
| ADC pairs | 60,261,418 | 60,260,552 | 866 | exact |
| GPIO samples | 241,045,673 | 241,042,208 | 3,465 | exact |

The one incomplete ADC buffer, one incomplete conversion, and one completion
mismatch were bounded terminal STOP observations attached to that exact tail;
they did not remove a complete frame or payload byte. The 601,589 USB TX stall
observations were cooperative polls of a temporarily full core TX ring. They
coexisted with zero partial writes, zero short-capacity deferrals, zero USB
errors, and a packet-owned high water of 83 out of 200.

The host issued and firmware accepted 123 commands. Final firmware and host
counts agreed at 123, every source/packet/USB queue depth was zero, device
state was IDLE, and stream mask was zero. These facts distinguish clean STOP
tail accounting from live acquisition loss.

## Public API compatibility

The physical evidence matches the stable surface in [[Python-API]] and
[[API-Reference]]:

- INFO provided the exact `DeviceInfo` identity and `DeviceCapabilities`
  invariants used for serial selection, optional `ExpectedDeviceIdentity`
  pinning, and pre-CONFIGURE validation.
- The accepted stream/source/checksum/rate/resolution values are exactly the
  arguments supported by `ThingDAQ.configure()`, and both CONFIGURE and START
  echoed the immutable applied `DAQConfiguration` expected by the facade.
- The independent ADC/GPIO payload interpretation matches `ADCBlock.adc0`,
  `ADCBlock.adc1`, explicit ADC0-then-ADC1 interleaving, `GPIOBlock.samples`,
  and lazy D6-D13 bit extraction. Raw codes and bytes were never replaced by a
  calibrated view.
- Repeated live STATUS and the final equations match `status()`,
  `loss_counters()`, `validate_stream_health()`, and
  `reconcile_run_counters()` semantics. STOP reached the context manager's
  required IDLE boundary.
- The accepted protocol/package inputs did not change after the clean-install
  matrix, so no wire or public-model drift separates the built distributions
  from this target image.

The rig container intentionally used the independent acceptance program, not
an installed wheel. This result is therefore a physical firmware/wire and
model-compatibility regression, while the actual wheel/sdist imports, typing,
CLI, simulator, and examples remain the clean-environment evidence above. It
does not claim a second installed-wheel-on-hardware execution.

## Verification and retained evidence

The maintained acceptance program's focused host suite passed 5 tests and 11
subtests before submission. After this report and its index links were added,
all 26 generated protocol outputs remained current; Ruff format and lint
passed across 111 Python files; MyPy passed across 23 package modules; the
documentation gate passed 4 tests and 441 subtests; and the complete local
suite passed 363 tests, 7 expected skips, and 13,850 subtests.

The manifest, ELF, HEX, map, independent 60-second program, deployed client,
preflight/postflight health documents, hashes, initial no-job error, and full
accepted stdout are retained outside version control under
`.maestro/playbooks/Working/phase-10-package-workflows-00001/`. No API key,
personal calibration, or bulk capture payload is retained there.
