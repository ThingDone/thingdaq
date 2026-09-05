---
type: report
title: Phase 12 Windows Validation Handoff
created: 2026-08-29
updated: 2026-08-31
tags:
  - thingdaq
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

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

> [!IMPORTANT]
> This handoff is a historical record for the pre-rename 0.7.0 candidate. Its
> hashes do not match the current ThingDAQ files, and its planned Windows run
> was never performed. Generate a new handoff from the current 1.0.0 freeze by
> following [[soak-harness]].

## Outcome and status

The corrected unpublished Windows handoff was ready for a later Windows run
against the historical Phase 11 identity. Its pre-rename standalone and
installed validators plus deterministic validation manifest encoded that same
accepted identity and fail-closed validation contract. Generation,
conformance, packaging, clean-install, failure-fixture, and accelerated
one-hour gates passed. The dated release-grading hardening addendum below
superseded the original Phase 12 artifacts at the time; both sets are now
historical after the ThingDAQ rename.

The final pre-handoff check also passed a 10-second, full-rate synthetic stream
through the exact standalone validator core using a virtual serial device and
clock. That diagnostic ran on Linux, not Windows, and its report correctly says
`profile: diagnostic` and `release_eligible: false`.

> [!IMPORTANT]
> Phase 12 did not replace or reopen the historical autonomous acceptance in
> [[Phase-11-Soak-Evidence]]. No Windows-host result, new physical-hardware
> result, analog accuracy/aperture result, or externally stimulated D6-D13
> result was produced from this handoff.

| Evidence layer | Status | Meaning |
| --- | --- | --- |
| Phase 11 autonomous campaign | PASS, historical authority | Accepted two synthetic, three physical-combined, and one control-stress 600-second job on one immutable pre-rename firmware identity. |
| Phase 12 implementation/build | PASS, historical and unpublished | The standalone/package validators, manifest, distributions, and local gates were ready for handoff. |
| Final Phase 12 fixture smoke | PASS, diagnostic only | Exact standalone validation logic passed a 10-second full-rate synthetic virtual-device stream on Linux. |
| Windows 3,600-second physical-combined run | Not performed | The handoff was superseded by the ThingDAQ rename. |
| Externally stimulated analog/digital validation | Not performed | Requires separately documented safe signal-generator/logic-analyzer work if those claims are desired. |

## Accepted immutable identity recheck

The final historical recheck compared the checked build output with the Phase 11 frozen
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

The `tdaq-*` build ID above is retained exactly as emitted by the tested
firmware; it is not the current project namespace. The hardware serial is the
stable device selector across COM renumbering. A
mutable name such as `COM10` is discovery evidence only and is never accepted
as release identity.

## Original handoff artifacts and hashes (historical)

The original distributions were built from checkout
`00957d02c2e72161b752b2bd562962b48f3c595f` with
`SOURCE_DATE_EPOCH=1788051352`. Nothing was uploaded, tagged, released, or
reserved on a package index. These hashes preserve the initial Phase 12 record
but are superseded for future testing by the corrected artifacts in the
hardening addendum immediately below.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Pre-rename standalone validator | 230,948 | `6604d1ec4900fdfbeec74b5b98413b9e7a28879261b1774e20aad6584ef1757d` |
| Pre-rename installed validator | 230,947 | `33ae0942c2f75cc55c523afddd152b5fc9f5bdac4a6108a40f278a8fd60d9712` |
| Pre-rename validation manifest | 9,751 | `3da1727a886876848a405aca4a538fccdc6f1c39c4086c17a5c0e7ebc78ee7d5` |
| Validation-manifest canonical semantics | n/a | `d6da65261b17b91409da59a5a0f8f47182a26d2d2a5637ac68b4cf902413b260` |
| Pre-rename wheel, version 0.10.0 | 226,018 | `d9141177503a588338ea1e5d7eb50ba78d1f38f0e482babda4eebf4da3e8da88` |
| Pre-rename source distribution, version 0.10.0 | 245,003 | `244d0837a6144d797af0c85a88d25b7164d0745cd788e69eb1417f32c4c43660` |
| Shared conformance vector | n/a | `5cb3ae36964d5ddce3a197ced3f93380fe8366c8dd0f880ef343f48465ecfa30` |

The wheel has 30 members and the universal `py3-none-any` tag. The source
distribution has 46 files. Two independent generation passes reproduced all
six generated outputs byte for byte and matched the checked repository files.
The standalone imports only the Python standard library and PySerial; it does
not import the package, NumPy, repository code, a network client, or a rig
service at runtime.

## 2026-08-29 release-grading hardening addendum

> [!IMPORTANT]
> These corrected artifacts superseded the original historical handoff by
> adding native Windows RSS sampling and fail-closed release eligibility. They
> are themselves superseded by ThingDAQ 1.0 and must not be used for a current
> run.

The hardening build was produced from checkout
`1b5d96dd263b3ba791545d56fd1687fde820dbad` with fixed
`SOURCE_DATE_EPOCH=1788057661`. The artifacts and complete machine-readable
evidence are retained under
`.maestro/playbooks/Working/phase-12-windows-release-grading-00001/`; see its
`windows-release-grading-evidence.md` and
`windows-release-grading-evidence.json`. Nothing was uploaded, tagged,
released, pushed, or reserved on a package index.

| Corrected artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Pre-rename standalone validator | 240,272 | `3553336f6f2a26b86de45c0100dd06e104e3fcca17ec80f82a5bef28a4445730` |
| Pre-rename installed validator | 240,271 | `6762390e5d779c705acbff9e9e7acce48da7870a91cb324b50958cf798a3bbe0` |
| Pre-rename validation manifest | 9,751 | `3da1727a886876848a405aca4a538fccdc6f1c39c4086c17a5c0e7ebc78ee7d5` |
| Pre-rename wheel, version 0.10.0 | 228,020 | `4a80428ddab575718bba0eb50fc976451c0b216f32f6c9d5b3331930214f12ff` |
| Pre-rename source distribution, version 0.10.0 | 246,984 | `5b6723897e3f0f3059a6aa2be5ef11b3a38e0524410994aaab958a33b65d3c69` |
| Shared normalized implementation | n/a | `329528555c452a8e17569971702245e6af5d5a964f504bf16b9ee953e440b816` |
| Shared conformance vector | n/a | `5cb3ae36964d5ddce3a197ced3f93380fe8366c8dd0f880ef343f48465ecfa30` |

Two independent builds produced byte-identical wheels. Their extracted source
distribution paths and bytes also matched exactly. Fresh standalone, wheel,
and source-distribution environments contained only PySerial 3.5 plus the
package where applicable; isolated imports, `pip check`, conformance,
simulator INFO, and one-frame-per-stream demos passed with NumPy and
development dependencies absent.

The corrected Windows-native sampler uses standard-library `ctypes` with
`GetCurrentProcess` and `GetProcessMemoryInfo` to record current and peak
working-set bytes at bounded memory checkpoints. A report is release eligible
only when every boolean in `windows.release_requirements` is true: the exact
3,600-second non-smoke physical-combined profile, identity override disabled,
native Windows host identity, overall PASS, exact manifest/device identity,
valid numeric baseline/peak/growth RSS evidence, and growth no greater than 32
MiB. Non-Windows hosts and unavailable, malformed, negative, non-finite, or
over-limit memory evidence produce explicit non-release reasons.

Automated gates passed 413 tests with 7 expected skips and 14,078 subtests,
including 22 focused Windows tests and 74 subtests. The rebuilt firmware kept
build ID `tdaq-a0dc150fd48a6e9b`; its 357,214-byte HEX remained byte-identical
to the accepted frozen Phase 11 artifact with SHA-256
`0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a`.
These Linux-hosted automated tests and Windows mocks validate grading logic;
they are not a Windows-host, USB-controller, attached-device, analog-quality,
aperture, or externally stimulated GPIO result. The planned Windows smoke and
3,600-second physical-combined run were not performed before this handoff was
superseded.

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

The last pre-handoff smoke exercised the checked pre-rename standalone
validator, including its runtime settings,
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

## Replacement procedure for the current ThingDAQ candidate

Do not use the historical artifact hashes above for a new run. First verify the
current candidate freeze and generated soak programs as described in
[[soak-harness]], program the staged current HEX, and build the current 1.0.0
wheel if the installed entry path is needed. Read [[Quickstart]] and
[[Hardware-Safety]] before attaching the supported board. The standalone path
needs only Python and PySerial at runtime.

```powershell
py -m pip install pyserial==3.5
py daq_api\scripts\windows_soak.py --conformance-check
py daq_api\scripts\windows_soak.py --duration 3600 --mode combined --output thingdaq-windows-soak
```

Or install the retained universal wheel and run the equivalent package entry
point:

```powershell
py -m pip install thingdaq_local-1.0.0-py3-none-any.whl
thingdaq-soak --conformance-check
thingdaq-soak --duration 3600 --mode combined --output thingdaq-windows-soak
```

Use `--hardware-serial 20512460` when more than one matching Teensy is present.
Retain both `thingdaq-windows-soak.json` and
`thingdaq-windows-soak.md`; do not summarize the Windows run as passed until
those reports exist and have been reviewed under the interpretation rules
above. Record it as new ThingDAQ 1.0 evidence rather than amending the
historical Phase 11 decision. See [[soak-harness]] for all options and
bounded-deadline behavior.

No task-associated images were present; zero images were analyzed.
