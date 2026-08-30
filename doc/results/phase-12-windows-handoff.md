---
type: report
title: Phase 12 Windows Validation Handoff
created: 2026-08-29
tags:
  - teensy-daq
  - phase-12
  - windows
  - packaging
  - validation-handoff
  - release-candidate
related:
  - '[[Phase-11-Soak-Evidence]]'
  - '[[Evidence-Index]]'
  - '[[Quickstart]]'
  - '[[soak-harness]]'
  - '[[Hardware-Safety]]'
  - '[[Protocol-V1]]'
---

# Phase 12 Windows validation handoff

## Outcome and status

The unpublished Windows handoff is ready for the user's later Windows run. The
standalone `daq_api/scripts/windows_soak.py`, installed `teensy-daq-soak`
command, and deterministic validation manifest encode the same accepted Phase
11 identity and validation contract. Generation, conformance, packaging,
clean-install, failure-fixture, and accelerated one-hour gates passed.

The final pre-handoff check also passed a 10-second, full-rate synthetic stream
through the exact standalone validator core using a virtual serial device and
clock. That diagnostic ran on Linux, not Windows, and its report correctly says
`profile: diagnostic` and `release_eligible: false`.

> [!IMPORTANT]
> Phase 12 does not replace or reopen the autonomous acceptance in
> [[Phase-11-Soak-Evidence]]. The future Windows run is additive evidence and
> is not a gate on that PASS. No Windows-host result, new physical-hardware
> result, analog accuracy/aperture result, or externally stimulated D6-D13
> result is claimed here.

| Evidence layer | Status | Meaning |
| --- | --- | --- |
| Phase 11 autonomous campaign | PASS, release-candidate authority | Accepted two synthetic, three physical-combined, and one control-stress 600-second job on one immutable firmware identity. |
| Phase 12 implementation/build | PASS, unpublished | The standalone/package validators, manifest, distributions, and local gates are ready for handoff. |
| Final Phase 12 fixture smoke | PASS, diagnostic only | Exact standalone validation logic passed a 10-second full-rate synthetic virtual-device stream on Linux. |
| Windows 3,600-second physical-combined run | Pending user evidence | Run later on Windows with the accepted Teensy attached; retain both generated reports. |
| Externally stimulated analog/digital validation | Not performed | Requires separately documented safe signal-generator/logic-analyzer work if those claims are desired. |

## Accepted immutable identity recheck

The final recheck compared the checked build output with the Phase 11 frozen
artifact at
`.maestro/playbooks/Working/phase-11-soak-candidate-00018/frozen/firmware.ino.hex`.
Both files are 357,214 bytes, both hash to the accepted digest below, and a
byte-for-byte comparison returned equal. The Phase 11 report, candidate freeze,
accepted-soak aggregate, Phase 12 validation manifest, and embedded standalone
expectation all name the same source, build, protocol, and HEX identities.

| Identity property | Accepted value |
| --- | --- |
| Firmware version | 0.7.0 |
| Protocol / checksum | v1 / Adler-32 algorithm 1 |
| Source ID | `a0dc150fd48a6e9b62c614fe487d533f6c7c90bee6c7d5cd3c9f8e985e0b49ba` |
| Build ID | `tdaq-a0dc150fd48a6e9b` |
| Exported HEX | `firmware.ino.hex`, 357,214 bytes |
| HEX SHA-256 | `0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a` |
| Target | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Stable hardware identity | INFO hardware serial `20512460`, board ID 1, MCU ID 1 |
| Candidate semantic SHA-256 | `32dcf73bc99f5abc53935901baa4f14103df339e1aafbe71ef3330f3b79d8656` |
| Candidate freeze SHA-256 | `b285449f1a7af391d5210189f87a0c01f7d28acc7c4f608a7ba3ade70c3b77a9` |
| Frozen build-manifest SHA-256 | `6741c3fe10c44b8d7ff5666ddfd9a6eba2147c584e687e34794a1165e9af384b` |
| Accepted-soak aggregate SHA-256 | `3a9d0064b143e49073776a1270c0b6dab2b1a3ad960533d635db2d7f08321696` |

The hardware serial is the stable device selector across COM renumbering. A
mutable name such as `COM10` is discovery evidence only and is never accepted
as release identity.

## Handoff artifacts and hashes

The distributions were built from checkout
`00957d02c2e72161b752b2bd562962b48f3c595f` with
`SOURCE_DATE_EPOCH=1788051352`. Nothing was uploaded, tagged, released, or
reserved on a package index.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `daq_api/scripts/windows_soak.py` | 230,948 | `6604d1ec4900fdfbeec74b5b98413b9e7a28879261b1774e20aad6584ef1757d` |
| `daq_api/src/teensy_daq/soak.py` | 230,947 | `33ae0942c2f75cc55c523afddd152b5fc9f5bdac4a6108a40f278a8fd60d9712` |
| `firmware/soak/validation-manifest.json` | 9,751 | `3da1727a886876848a405aca4a538fccdc6f1c39c4086c17a5c0e7ebc78ee7d5` |
| Validation-manifest canonical semantics | n/a | `d6da65261b17b91409da59a5a0f8f47182a26d2d2a5637ac68b4cf902413b260` |
| `teensy_daq_local-0.10.0-py3-none-any.whl` | 226,018 | `d9141177503a588338ea1e5d7eb50ba78d1f38f0e482babda4eebf4da3e8da88` |
| `teensy_daq_local-0.10.0.tar.gz` | 245,003 | `244d0837a6144d797af0c85a88d25b7164d0745cd788e69eb1417f32c4c43660` |
| Shared conformance vector | n/a | `5cb3ae36964d5ddce3a197ced3f93380fe8366c8dd0f880ef343f48465ecfa30` |

The wheel has 30 members and the universal `py3-none-any` tag. The source
distribution has 46 files. Two independent generation passes reproduced all
six generated outputs byte for byte and matched the checked repository files.
The standalone imports only the Python standard library and PySerial; it does
not import the package, NumPy, repository code, a network client, or a rig
service at runtime.

## Expected validation manifest

The checked manifest is the fail-closed authority embedded in both entry
paths. Each program validates the embedded semantic digest before opening a
serial port and compares two stable INFO responses with the complete expected
contract.

| Contract area | Expected value |
| --- | --- |
| Firmware identity | Version 0.7.0, build `tdaq-a0dc150fd48a6e9b`, accepted source/HEX digests above |
| Device identity | Hardware serial `20512460`, board ID 1, MCU ID 1 |
| Protocol | Version 1, little-endian, 44-byte header, 4,048-byte payload, 4-byte trailer, 4,096-byte data frame |
| Checksum | Adler-32 algorithm 1, initial value 1, modulus 65,521, 32-bit little-endian trailer over header and payload |
| ADC | A0/A1 (pins 14/15), 1,000,000 pairs/s, 12-bit samples in 16-bit containers, 1,012 pairs/frame |
| ADC phase | ADC1 scheduled 4 ticks / 500 ns after ADC0 from the shared 8 MHz timestamp domain |
| GPIO | D6-D13 mapped to payload bits 0-7, 4,000,000 samples/s, 4,048 samples/frame |
| Capabilities | Bits 511; stream/source/configuration/checksum masks `3` / `3` / `63` / `14` |
| Bounds | 200 packet buffers and 200-entry ready/transmit queues; four command and four response entries |
| Loss/error policy | All named host parser/stream and firmware loss/error counters must be zero during normal streaming and at final reconciliation |
| Physical STOP tail | Only the explicitly bounded acquisition tail counters may be nonzero, and they must reconcile exactly |
| Identity override | `--diagnostic-identity-override` records every mismatch and is unconditionally non-release |

See [[Protocol-V1]] for the wire contract and [[Hardware-Safety]] before
connecting the accepted board or any external source.

## Test and packaging evidence

| Gate | Result |
| --- | --- |
| Protocol / soak generation drift | PASS; 26 protocol and 6 soak outputs current |
| Ruff formatting / lint | PASS; 124 files, no lint findings |
| MyPy implementation gate | PASS; 28 sources |
| Phase 12 build Python and host-C++ suite | PASS; 401 tests, 7 expected dependency skips, 14,015 subtests |
| Dedicated Windows handoff suite | PASS; 10 tests, 32 subtests |
| Package/configuration/example gate | PASS; 14 tests, 109 subtests |
| Accelerated exact 3,600-second profile | PASS; 3,501 STATUS latency samples, bounded queues/memory |
| Standalone/package conformance | PASS; identical commands, frames, metrics, and success/failure grades |
| Pinned Teensy build | PASS; expected build ID and byte-identical accepted HEX |
| Clean standalone environment | PASS with PySerial 3.5 only |
| Clean wheel and sdist environments | PASS with package 0.10.0 and PySerial 3.5 only; `pip check` clean and NumPy absent |
| Final handoff-document regression | PASS; 401 tests, 7 expected dependency skips, 14,036 subtests |

The conformance fixtures accepted the valid transcript and rejected checksum
corruption, a synthetic pattern error, and a sequence gap with the intended
failure categories. The broader suite covered COM metadata/order/renumbering,
busy and access-denied ports, hardware-serial selection, arbitrary read
fragmentation, partial writes, delayed STATUS, wrong identities, counter
disagreement, disconnect, Ctrl+C, STOP/close failures, and report creation on
every exit path.

## Final simulated full-rate smoke

The last pre-handoff smoke exercised the checked
`daq_api/scripts/windows_soak.py` module, including its runtime settings,
serial parser, INFO synchronization, CONFIGURE/START/STATUS/STOP sequence,
stream validator, counter reconciliation, grading, JSON writer, and Markdown
writer. A virtual PySerial-shaped peer supplied the accepted INFO identity and
full-rate synthetic ADC/GPIO frames; a virtual clock advanced 506 microseconds
per alternating data frame. Deliberate 14-byte startup noise exercised
synchronization before the measured interval.

| Smoke property | Result |
| --- | --- |
| Host / transport | CPython 3.12.3 on Linux; virtual COM metadata and virtual serial device |
| Requested profile | `--smoke --mode synthetic`, 10 measured seconds |
| Grade / eligibility | PASS / `profile: diagnostic` / `release_eligible: false` |
| Identity | Expected and observed build `tdaq-a0dc150fd48a6e9b`, hardware serial `20512460`, protocol v1 |
| Measured time | 10.000958 seconds |
| Timed ADC | 9,871 frames; 9,989,452 pairs; 998,849.510 pairs/s |
| Timed GPIO | 9,872 frames; 39,961,856 samples; 3,995,802.802 samples/s |
| Timed bytes | 79,919,664 payload; 80,867,328 framed; 7,991,200.843 payload B/s |
| Continuity | Zero ADC/GPIO missing frames and zero gap flags |
| Parser | 21,739 frames; zero errors; zero retained bytes; 14 startup-noise bytes discarded during synchronization |
| STATUS / latency | 13 snapshots; STATUS p99/max and any-command max all 1.000 ms |
| Memory | 62,566-byte traced growth and 131,072-byte RSS growth, inside the fixed limits |
| Final state | Required loss/error counters zero, state IDLE, virtual serial close completed |

The retained reports are
`.maestro/playbooks/Working/phase-12-windows-handoff-00001/final-simulated-full-rate-smoke.json`
(SHA-256
`ff7231d5d0bc19abbd3d369bfe0c4c8bbaa6fc6967a3fa56d3e93dabf4790aca`)
and the corresponding Markdown report (SHA-256
`91e12e5687c6066da48c4c76e5595eb5facbe09064f2a6b906026334c7bfb30a`).
They are diagnostic fixture evidence, not Windows or physical-device evidence.

## Reading a Windows report

The JSON record is authoritative; the Markdown report renders the same
complete JSON after its summary tables.

- `result: PASS` means the checks for the invoked profile passed. It does not
  by itself mean the report is release evidence.
- `windows.profile: release` requires an exact 3,600-second non-smoke combined
  run, no identity override, and one host snapshot identifying native Windows
  (`system: Windows` and `sys_platform: win32`).
- `windows.release_eligible: true` is computed from every boolean in
  `windows.release_requirements`. In addition to the release-profile
  predicates, it requires an overall PASS, exact manifest/device identity, and
  complete finite nonnegative process-RSS baseline, peak, and growth values;
  RSS growth must not exceed 32 MiB.
- `windows.profile: diagnostic`, a shorter duration, synthetic mode, or
  `release_eligible: false` is useful troubleshooting evidence only.
- `diagnostic-identity-override.requested: true` is always non-release even if
  the stream itself passes. Review the retained expected/actual mismatches.
- Confirm the host reports Windows, the selected endpoint is the intended
  hardware serial regardless of its current COM number, parser errors and
  retained bytes are zero after synchronization, rates are within tolerance,
  STATUS and memory limits pass, firmware/host counts conserve exactly, STOP
  reaches IDLE, and serial close completes.
- A FAIL report is still intentionally complete. Use `failure.category`,
  `failure.message`, discovery/probe records, lifecycle records, validation
  reasons, and the active epoch to distinguish identity, protocol, loss,
  counter, timeout, disconnect, memory, and cleanup failures.

The Windows physical-combined run can validate the selected host/controller,
COM discovery, serial transport, firmware acquisition/capture paths, and
end-to-end counters. With unstimulated A0/A1 and D6-D13, it still cannot prove
analog accuracy, noise, bandwidth, source-impedance performance, true aperture
separation, or externally changing digital inputs.

## Windows handoff procedure

Read [[Quickstart]] and [[Hardware-Safety]], attach the Teensy programmed with
the accepted HEX, and use either entry path. The standalone path needs only
Python and PySerial at runtime.

```powershell
py -m pip install pyserial==3.5
py daq_api\scripts\windows_soak.py --conformance-check
py daq_api\scripts\windows_soak.py --duration 3600 --mode combined --output teensy-daq-windows-soak
```

Or install the retained universal wheel and run the equivalent package entry
point:

```powershell
py -m pip install teensy_daq_local-0.10.0-py3-none-any.whl
teensy-daq-soak --conformance-check
teensy-daq-soak --duration 3600 --mode combined --output teensy-daq-windows-soak
```

Use `--hardware-serial 20512460` when more than one matching Teensy is present.
Retain both `teensy-daq-windows-soak.json` and
`teensy-daq-windows-soak.md`; do not summarize the Windows run as passed until
those reports exist and have been reviewed under the interpretation rules
above. See [[soak-harness]] for all options and bounded-deadline behavior.

No task-associated images were present; zero images were analyzed.
