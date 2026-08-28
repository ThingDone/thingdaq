---
type: reference
title: Teensy DAQ Documentation Index
created: 2026-08-27
tags:
  - teensy-daq
  - documentation
related:
  - '[[System-Overview]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Checksum-Candidates]]'
  - '[[Phase-05-Checksum-Correctness]]'
  - '[[Phase-05-Checksum-Local-Gate]]'
  - '[[Phase-05-Checksum-Physical-Campaign]]'
  - '[[Phase-05-Checksum-Benchmark]]'
  - '[[Phase-06-GPIO-DMA]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[Phase-01-Synthetic-Prototype-Gate]]'
  - '[[Phase-02-Protocol-Python-Gate]]'
  - '[[Phase-03-Firmware-Local-Gate]]'
  - '[[Phase-03-Control-Plane]]'
  - '[[Phase-04-Synthetic-Streaming]]'
---

# Teensy DAQ documentation

Every Markdown artifact below `doc/` begins with YAML front matter containing
`type`, `title`, `created`, `tags`, and `related`. Related artifacts use
`[[Wiki-Links]]` so the project can be explored as a documentation graph.

## Organization

- `architecture/` describes system boundaries and component relationships,
  beginning with [[System-Overview]] and [[Firmware-Resource-Map]].
- `protocol/` contains versioned wire-contract specifications, beginning with
  [[Protocol-V1]].
- `decisions/` contains architecture decision records, including
  [[ADR-001-Wire-Protocol]], [[ADR-002-Checksum-Selection]], and
  [[ADR-003-GPIO-Clock-DMA]].
- `reference/` records durable inventories and implementation references,
  beginning with [[Foundation-Reuse-Inventory]].
- `research/` records evidence gathered before implementation or selection,
  beginning with [[Checksum-Candidates]].
- `results/` records reproducible test, build, benchmark, and hardware evidence,
  including [[Phase-01-Synthetic-Prototype-Gate]] and
  [[Phase-02-Protocol-Python-Gate]], followed by the compile-only
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
  in [[Phase-06-GPIO-DMA]].

Generated captures and scratch results remain outside version control. Small,
deterministic implementation fixtures belong under `firmware/tests/fixtures/`
or `daq_api/tests/fixtures/`; cross-language golden wire frames belong under
`protocol/fixtures/`. All remain tracked.
