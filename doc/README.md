---
type: reference
title: Teensy DAQ Documentation Index
created: 2026-08-27
updated: 2026-08-29
tags:
  - teensy-daq
  - documentation
related:
  - '[[Quickstart]]'
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
  - '[[Phase-01-Prototype]]'
  - '[[Phase-02-Protocol-Python]]'
  - '[[Phase-03-Firmware-Local-Gate]]'
  - '[[Phase-03-Control-Plane]]'
  - '[[Phase-04-Synthetic-Streaming]]'
---

# Teensy DAQ documentation

Every Markdown artifact below `doc/` begins with YAML front matter containing
`type`, `title`, `created`, `tags`, and `related`. Related artifacts use
double-bracket document links so the project can be explored as a graph.

## Organization

- `guides/` contains executable user workflows, beginning with [[Quickstart]].
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
  and DMA resource contract in [[ADR-004-ADC-Trigger-DMA]].
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

Generated captures and scratch results remain outside version control. Small,
deterministic implementation fixtures belong under `firmware/tests/fixtures/`
or `daq_api/tests/fixtures/`; cross-language golden wire frames belong under
`protocol/fixtures/`. All remain tracked.
