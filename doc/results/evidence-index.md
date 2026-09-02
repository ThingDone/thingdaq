---
type: reference
title: ThingDAQ Evidence Index
created: 2026-08-29
updated: 2026-09-02
tags:
  - thingdaq
  - evidence
  - validation
  - release-candidate
related:
  - '[[Phase-11-Soak-Evidence]]'
  - '[[Phase-12-Windows-Handoff]]'
  - '[[Phase-01-Prototype]]'
  - '[[Phase-02-Protocol-Python]]'
  - '[[Phase-03-Firmware-Local-Gate]]'
  - '[[Phase-03-Control-Plane]]'
  - '[[Phase-04-Synthetic-Streaming]]'
  - '[[Phase-05-Checksum-Correctness]]'
  - '[[Phase-05-Checksum-Local-Gate]]'
  - '[[Phase-05-Checksum-Physical-Campaign]]'
  - '[[Phase-05-Checksum-Benchmark]]'
  - '[[Phase-06-GPIO-DMA]]'
  - '[[Phase-07-Dual-ADC]]'
  - '[[Phase-08-Combined-Acquisition]]'
  - '[[Phase-09-Loss-Recovery]]'
  - '[[Phase-10-Package-Local-Gate]]'
  - '[[Phase-10-Package-Workflows]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[rle-prototype]]'
---

# ThingDAQ evidence index

## Current ThingDAQ 1.0 candidate

The rename is a breaking identity boundary. The current candidate has fresh
ThingDAQ namespaces, commands, USB product text, generated validators, and a
byte-identical two-build firmware freeze. Local software, protocol, packaging,
and firmware-build gates pass. No physical or Windows acquisition campaign has
run against this renamed binary, so the historical Phase 11 PASS does not
serve as release acceptance for ThingDAQ 1.0.

| Authority | Exact value |
| --- | --- |
| Freeze base commit | `503b58e9674d56723c0499ec5514334d728eee99` |
| Protected source tree | 242 files; SHA-256 `1d17a981f27438c8092996a70dcdadaec84c7cdd587e7dffc29b658d3059e6f9` |
| Source / build | `e27556de5b898f281dfbae8a9a1fefb486a4fa38a885516e2fac5ce6974ba673` / `thingdaq-e27556de5b898f28` |
| Firmware / protocol / checksum | 1.0.0 / v1 / Adler-32 |
| Frozen HEX | 357,227 bytes; SHA-256 `da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3` |
| Reproducible build manifests | Two byte-identical manifests; SHA-256 `d24bca9eba23ccffa11470f1cdd60f37fcc34fdde3522a2080b6953275e0d9cd` |
| Candidate freeze | SHA-256 `c67706d4b52dab9f8c4c77bcde31956b616fb9df3fbb04165f0d7e8e3f57388e` |
| Validation manifest | SHA-256 `0ea256df7166479883ea1bbe81d308c5bda333139b36bac5d3276a704fdf3c9a` |
| Local validation | 416 passed, 7 dependency skips, 14,081 subtests; Ruff, MyPy, protocol/soak generation, freeze verification, and pinned firmware build PASS |
| Physical/Windows acceptance | Pending for the renamed 1.0.0 identity |

Use [[soak-harness]] to generate and run new evidence against this identity.
Do not compare a current report to the hashes in the historical sections
below.

## Experimental negotiated RLE prototype

[[rle-prototype]] records the isolated `experiment/rle-streaming` host and
simulator gate. Two no-hardware demonstrations were byte-identical, both
72-frame corpus benchmarks passed exact round-trip, adaptive no-expansion,
bounded-memory, long-hold savings, incompressible fallback, and 1.25x decode
headroom requirements, and the pinned default 600 MHz firmware still compiled
without upload. All 27 protocol-v1 source/generated/fixture paths remained
byte-identical to the immutable baseline.

This is not target-side RLE, USB, analog, external-GPIO, or physical timing
evidence. Compression savings are workload-dependent, ADC savings have no
minimum acceptance threshold, and no cross-experiment branch combination was
tested.

## Historical autonomous acceptance (superseded identity)

[[Phase-11-Soak-Evidence]] records the autonomous decision for the pre-rename
0.7.0 candidate. It preserves the exact identity, complete 26-job lineage,
metrics and trends, acceptance equations, retry policy, fixture limits, final
local gate, firmware/distribution reproduction, and retained-evidence hashes.

| Authority | Exact value |
| --- | --- |
| Gate checkout | `8517befc450d17e5684b4884c0ff69cd984046ad` |
| Protected source tree | 240 files; SHA-256 `84636113d34bdadef466d94c6c44180d2e591f3dc99ed346b32a8bd3b4a15dbc` |
| Source / build | `a0dc150fd48a6e9b62c614fe487d533f6c7c90bee6c7d5cd3c9f8e985e0b49ba` / `tdaq-a0dc150fd48a6e9b` |
| Firmware / protocol / checksum | 0.7.0 / v1 / Adler-32 |
| Accepted HEX | `0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a` |
| Target / toolchain | Teensy 4.0 FQBN `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`; Arduino CLI 1.4.1; Teensy core 1.62.0; Arm GNU 15.2.1 |
| Accepted jobs | 2 synthetic + 3 physical-combined + 1 control-stress, each nominally 600 seconds |
| Release aggregate | 6 accepted, 20 excluded, 0 infrastructure incidents; SHA-256 `3a9d0064b143e49073776a1270c0b6dab2b1a3ad960533d635db2d7f08321696` |
| Worst accepted latency | STATUS p99 9.116 ms; STATUS/any-command maximum 59.672 ms |
| Accepted data | 3,605.008125 measured seconds; 28,595,177,248 payload bytes |
| Historical wheel record | 178,120 bytes; SHA-256 `a086facfc564ae5d2a4c143556aa6a8487ff65f19eb2879b99a8d0d846153c31` |
| Historical normalized distributions | wheel `d496b9a0c8e11181cea1c356ee8c278fe69db381424d25c9015bf868167dbdaa`; sdist `297fa155bfb905a5984764edcf954ab7536c99b42c77f70b7fa8cbadf48807d0` |

The detailed equations and limits are in [[Phase-11-Soak-Evidence]]. In short,
every stage conserved produced/framed/emitted/transmitted/dropped frames,
ADC/GPIO items and bytes matched frame geometry, all synthetic items matched
their formulas, normal loss/error counters were zero, and the one named
control pressure case reconciled 148 ADC plus 148 GPIO frame evictions exactly.
The unstimulated fixture does not grade analog accuracy, aperture, external
GPIO transitions, or Windows-host behavior. A service incident could be
retried once; no such incident occurred. Product/test failures were excluded,
fixed, rebuilt when needed, and restarted from run one.

## Historical Phase 12 handoff and release-grading hardening (superseded)

[[Phase-12-Windows-Handoff]] records the corrected unpublished handoff prepared
for the same pre-rename identity. Its standalone validator, installed command,
deterministic manifest, universal wheel, and source distribution passed their
generation, conformance, packaging, clean-install, fault-fixture, and
accelerated one-hour gates. The retained
`.maestro/playbooks/Working/phase-12-windows-release-grading-00001/windows-release-grading-evidence.md`
records the native Windows RSS and fail-closed eligibility hardening. A
10-second full-rate synthetic virtual-device smoke passed on Linux and was
correctly marked diagnostic and non-release. Those files and hashes do not
describe the current ThingDAQ sources.

| Handoff authority | Exact value |
| --- | --- |
| Standalone validator | 240,272 bytes; SHA-256 `3553336f6f2a26b86de45c0100dd06e104e3fcca17ec80f82a5bef28a4445730` |
| Validation manifest | File SHA-256 `3da1727a886876848a405aca4a538fccdc6f1c39c4086c17a5c0e7ebc78ee7d5`; semantic SHA-256 `d6da65261b17b91409da59a5a0f8f47182a26d2d2a5637ac68b4cf902413b260` |
| Universal wheel | 228,020 bytes; SHA-256 `4a80428ddab575718bba0eb50fc976451c0b216f32f6c9d5b3331930214f12ff` |
| Source distribution | 246,984 bytes; SHA-256 `5b6723897e3f0f3059a6aa2be5ef11b3a38e0524410994aaab958a33b65d3c69` |
| Release grading | Native Windows host plus complete numeric bounded RSS evidence required; conformance SHA-256 `5cb3ae36964d5ddce3a197ced3f93380fe8366c8dd0f880ef343f48465ecfa30` |
| Final simulated smoke | PASS; 10.000958 seconds, 79,919,664 payload bytes, `release_eligible: false` |
| Windows physical-combined result | Never run for this superseded handoff |

No Windows-host behavior or externally stimulated analog/digital behavior is
accepted by the Phase 12 preparation evidence. Those claim limits and the
exact report interpretation rules are explicit in
[[Phase-12-Windows-Handoff]].

## Accepted Phase 11 job register

| Mode | Job ID | UTC interval | Measured seconds |
| --- | --- | --- | ---: |
| Physical combined | `bed9b04d-f1e4-4b31-820b-e51075c8e1aa` | 2026-08-29 20:55:01Z–21:05:14Z | 600.000474 |
| Physical combined | `8e83ad24-469f-46a3-8bf7-8d8149eea6f8` | 2026-08-29 21:06:42Z–21:16:56Z | 600.001406 |
| Physical combined | `f7c5aebb-5591-4656-8f29-dfb0ae2db2ad` | 2026-08-29 21:17:36Z–21:27:49Z | 600.000473 |
| Control stress | `ad2ea61c-e17d-4b2f-bc72-47eb3e3d6f1a` | 2026-08-29 22:17:52Z–22:28:09Z | 604.998386 |
| Synthetic | `3d20bf96-044b-436f-bcc2-5df5b55fa026` | 2026-08-29 22:53:31Z–23:03:44Z | 600.001444 |
| Synthetic | `98efca60-aad2-4a93-a857-182408ed0dde` | 2026-08-29 23:04:31Z–23:14:44Z | 600.005942 |

## Excluded Phase 11 job register

Every submitted non-counting job is listed here; the reason and resulting
repair are in [[Phase-11-Soak-Evidence]].

| Campaign | Job ID | UTC interval | Classification |
| --- | --- | --- | --- |
| Synthetic | `f57b475d-dbd7-4091-bcd5-09a313a76f84` | 2026-08-29 16:16:19Z–16:16:30Z | `test_failure` |
| Synthetic | `ea6e220f-7e6d-49ca-9b64-ddd60b42b657` | 2026-08-29 16:23:24Z–16:23:37Z | `test_failure` |
| Synthetic | `d1266d62-dfc7-4d19-a4cc-3944c6a1da70` | 2026-08-29 16:31:24Z–16:41:36Z | `test_failure` |
| Synthetic | `a90bceab-fde8-4a0c-9e79-1c567be38df5` | 2026-08-29 16:45:07Z–16:55:19Z | `accepted_superseded_identity` |
| Synthetic | `22f66838-ecd5-4eed-91ad-d92f70b7ee17` | 2026-08-29 16:55:59Z–17:06:12Z | `accepted_superseded_identity` |
| Physical | `a8da2773-94f6-4e91-ab84-300f78d57971` | 2026-08-29 17:12:16Z–17:14:50Z | `test_failure` |
| Physical | `4892b46e-bb04-4d4c-9c99-d29868fc9b9a` | 2026-08-29 17:23:50Z–17:34:02Z | `accepted_superseded` |
| Physical | `7c21f29c-36d8-4f0a-822e-990717ad01a2` | 2026-08-29 17:34:44Z–17:38:11Z | `test_failure` |
| Physical | `9f87d9ab-bdc4-4b61-a70e-a171fb3e2a9c` | 2026-08-29 17:51:28Z–17:53:17Z | `test_failure` |
| Physical | `a286cc08-4b5a-4562-853a-2dc383eda6ad` | 2026-08-29 18:09:09Z–18:19:21Z | `accepted_superseded` |
| Physical | `a67bd98a-197a-4076-b98c-5b5338c12377` | 2026-08-29 18:20:06Z–18:23:56Z | `test_failure` |
| Physical | `81775ca9-e771-4977-bbd4-d602938f08ce` | 2026-08-29 18:32:07Z–18:34:00Z | `test_failure` |
| Physical | `fd7cded1-1257-40c4-bd54-37ba411516fd` | 2026-08-29 18:41:27Z–18:47:24Z | `test_failure` |
| Physical | `b2b7bb11-1716-47b0-81f4-6618c1734d45` | 2026-08-29 18:56:13Z–18:57:21Z | `test_failure` |
| Physical | `30c12dd2-c71c-4813-aa5f-49a269d47d00` | 2026-08-29 19:23:23Z–19:33:36Z | `accepted_superseded` |
| Physical | `c3417fa1-5854-4cea-b824-07f702d3d3c3` | 2026-08-29 19:34:37Z–19:43:30Z | `test_failure` |
| Physical | `2f298f18-111e-4e7d-b856-c6fcd37b9815` | 2026-08-29 20:11:50Z–20:20:53Z | `test_failure` |
| Physical | `1bcc662b-0e5a-478e-a01e-50359ece23db` | 2026-08-29 20:28:39Z–20:36:01Z | `test_failure` |
| Control | `f8b70430-7228-4e3e-a041-4ae871f49921` | 2026-08-29 22:00:57Z–22:01:10Z | `test_failure` (harness) |
| Control | `c72d1e01-8c83-4fa8-aefd-7597a7898232` | 2026-08-29 22:09:48Z–22:10:02Z | `test_failure` (harness) |

## Prior result reports

| Phase | Evidence reports |
| --- | --- |
| 01 | [[Phase-01-Prototype]] |
| 02 | [[Phase-02-Protocol-Python]] |
| 03 | [[Phase-03-Firmware-Local-Gate]], [[Phase-03-Control-Plane]] |
| 04 | [[Phase-04-Synthetic-Streaming]] |
| 05 | [[Phase-05-Checksum-Correctness]], [[Phase-05-Checksum-Local-Gate]], [[Phase-05-Checksum-Physical-Campaign]], [[Phase-05-Checksum-Benchmark]] |
| 06 | [[Phase-06-GPIO-DMA]] |
| 07 | [[Phase-07-Dual-ADC]] |
| 08 | [[Phase-08-Combined-Acquisition]] |
| 09 | [[Phase-09-Loss-Recovery]] |
| 10 | [[Phase-10-Package-Local-Gate]], [[Phase-10-Package-Workflows]] |
| 11 | [[Phase-11-Soak-Evidence]] |
| 12 | [[Phase-12-Windows-Handoff]] |

## Architecture decisions

| Decision | Evidence relationship |
| --- | --- |
| [[ADR-001-Wire-Protocol]] | Versioned framing, identity, run/sequence/timestamp, and control semantics graded by every accepted job. |
| [[ADR-002-Checksum-Selection]] | Adler-32 selection continuously validated over all accepted payloads. |
| [[ADR-003-GPIO-Clock-DMA]] | Exact-rate GPIO trigger/DMA/packing path graded by physical and control epochs. |
| [[ADR-004-ADC-Trigger-DMA]] | Paired ADC trigger, completion, descriptor, and DMA resource contract graded by physical and control epochs. |

No public-release tag or package publication is part of this index. A new
ThingDAQ physical or Windows result may be linked here only after it uses the
current 1.0.0 candidate and its generated validation manifest; it cannot be
backfilled into the historical Phase 11 or Phase 12 records.
