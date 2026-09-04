---
type: reference
title: ThingDAQ Documentation Index
created: 2026-08-27
updated: 2026-08-31
tags:
  - thingdaq
  - documentation
related:
  - '[[Evidence-Index]]'
  - '[[Phase-11-Soak-Evidence]]'
  - '[[Phase-12-Windows-Handoff]]'
  - '[[Quickstart]]'
  - '[[soak-harness]]'
  - '[[Python-API]]'
  - '[[API-Reference]]'
  - '[[Hardware-Safety]]'
  - '[[System-Overview]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Acquisition-Pipeline]]'
  - '[[Calibration]]'
  - '[[NumPy-Integration]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Checksum-Candidates]]'
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
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[ADR-008-Experimental-Aux-Output-Bank]]'
  - '[[Phase-01-Prototype]]'
  - '[[Phase-02-Protocol-Python]]'
  - '[[Phase-03-Firmware-Local-Gate]]'
  - '[[Phase-03-Control-Plane]]'
  - '[[Phase-04-Synthetic-Streaming]]'
---

# ThingDAQ documentation

Every Markdown artifact below `doc/` begins with YAML front matter containing
`type`, `title`, `created`, `tags`, and `related`. Related artifacts use
double-bracket document links so the project can be explored as a graph.

## Project identity and evidence provenance

ThingDAQ (Thing Done DAQ) is the project and product name. It supports the
Teensy® 4.0 hardware platform but is independent of and not endorsed by
PJRC.COM, LLC or SparkFun Electronics; Teensy is a registered trademark of
PJRC.COM, LLC. Hardware references are descriptive and do not form part of the
ThingDAQ name.

Result reports predate the rename unless they explicitly identify the current
1.0.0 candidate. Their `tdaq-*` build IDs are immutable values emitted by the
tested firmware and are retained verbatim for evidence integrity. Reusable
commands, source paths, Python names, and prose use current ThingDAQ naming;
consult the recorded commit when reproducing a historical artifact byte for
byte. [[Evidence-Index]] separates current local validation from historical
physical acceptance.

## Organization

- `guides/` contains executable user workflows, beginning with [[Quickstart]]
  and the generated remote endurance workflow in [[soak-harness]].
- `architecture/` describes system boundaries and component relationships,
  beginning with [[System-Overview]] and [[Firmware-Resource-Map]], with the
  centralized physical lifecycle and Phase 08 composition audit in
  [[Acquisition-Pipeline]], the synchronized public host boundary in
  [[Python-API]], the immutable opt-in host correction model in [[Calibration]],
  and the allocation, ownership, and pure-Python parity contract for optional
  arrays in [[NumPy-Integration]].
- `protocol/` contains versioned wire-contract specifications, beginning with
  [[Protocol-V1]].
- `decisions/` contains architecture decision records, including
  [[ADR-001-Wire-Protocol]], [[ADR-002-Checksum-Selection]], and
  [[ADR-003-GPIO-Clock-DMA]], followed by the permanent converter, trigger,
  and DMA resource contract in [[ADR-004-ADC-Trigger-DMA]]. The isolated
  preloaded D16-D23 output contract is
  [[ADR-008-Experimental-Aux-Output-Bank]].
- `reference/` records durable user and implementation references: begin with
  [[Hardware-Safety]] before connecting signals, use [[API-Reference]] for the
  stable Python surface, and consult [[Foundation-Reuse-Inventory]] for the
  original implementation audit.
- `research/` records evidence gathered before implementation or selection,
  beginning with [[Checksum-Candidates]].
- `results/` records reproducible test, build, benchmark, and hardware evidence,
  including [[Phase-01-Prototype]] and [[Phase-02-Protocol-Python]], followed
  by the compile-only
  [[Phase-03-Firmware-Local-Gate]] and physical
  [[Phase-03-Control-Plane]] control acceptance and
  [[Phase-04-Synthetic-Streaming]] full-rate synthetic-stream acceptance,
  followed by the independent [[Phase-05-Checksum-Correctness]] vector,
  corruption, negotiation, parser-recovery, and benchmark-arithmetic evidence
  and the pre-rig [[Phase-05-Checksum-Local-Gate]] correctness, build-resource,
  and repeated host-timing result. The candidate-isolated target evidence is
  in [[Phase-05-Checksum-Physical-Campaign]], the fixed production choice is
  recorded in [[ADR-002-Checksum-Selection]], and the clean selected-image
  rebuild plus three-run acceptance is consolidated in
  [[Phase-05-Checksum-Benchmark]]. The exact-rate physical GPIO gate, target
  CPU/queue evidence, and sequential diagnostic/smoke/soak results are recorded
  in [[Phase-06-GPIO-DMA]]. The paired converter, calibration, trigger/
  completion timing, eDMA, full-rate stream, and explicit unstimulated-input
  scope are recorded in [[Phase-07-Dual-ADC]]. The common-epoch physical
  composition acceptance is in [[Phase-08-Combined-Acquisition]], followed by
  the exact loss, malformed-control, CDC reopen, reset/re-enumeration, and
  normal-regression campaign in [[Phase-09-Loss-Recovery]]. The reproducible
  package contents, clean-install CPython 3.10-3.14 matrix, optional-NumPy
  parity, installed typing, consoles, simulator, and examples are recorded in
  [[Phase-10-Package-Local-Gate]]. Its byte-matched firmware rebuild and final
  sequential identity/capability, physical combined-stream, live STATUS, raw
  interpretation, clean STOP, and counter-reconciliation gate are recorded in
  [[Phase-10-Package-Workflows]].
  The historical autonomous release-candidate decision, complete accepted/excluded
  job lineage, cross-run trends, conservation equations, and reproducible
  post-campaign gate are consolidated in [[Phase-11-Soak-Evidence]]. The
  superseded identity-pinned Windows artifacts, hashes, packaging evidence,
  and report interpretation are in [[Phase-12-Windows-Handoff]]. Use
  [[Evidence-Index]] for the current-candidate boundary and cross-phase map.

Generated captures and scratch results remain outside version control. Small,
deterministic implementation fixtures belong under `firmware/tests/fixtures/`
or `daq_api/tests/fixtures/`; cross-language golden wire frames belong under
`protocol/fixtures/`. All remain tracked.
