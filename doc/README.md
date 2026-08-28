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
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
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
- `decisions/` contains architecture decision records, beginning with
  [[ADR-001-Wire-Protocol]].
- `reference/` records durable inventories and implementation references,
  beginning with [[Foundation-Reuse-Inventory]].
- `research/` records evidence gathered before implementation or selection,
  beginning with [[Checksum-Candidates]].
- `results/` records reproducible test, build, benchmark, and hardware evidence,
  including [[Phase-01-Synthetic-Prototype-Gate]] and
  [[Phase-02-Protocol-Python-Gate]], followed by the compile-only
  [[Phase-03-Firmware-Local-Gate]] and physical
  [[Phase-03-Control-Plane]] control acceptance and
  [[Phase-04-Synthetic-Streaming]] full-rate synthetic-stream acceptance.

Generated captures and scratch results remain outside version control. Small,
deterministic implementation fixtures belong under `firmware/tests/fixtures/`
or `daq_api/tests/fixtures/`; cross-language golden wire frames belong under
`protocol/fixtures/`. All remain tracked.
