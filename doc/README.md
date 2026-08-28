---
type: reference
title: Teensy DAQ Documentation Index
created: 2026-08-27
tags:
  - teensy-daq
  - documentation
related:
  - '[[System-Overview]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Protocol-Wire-Contract]]'
  - '[[Phase-01-Synthetic-Prototype-Gate]]'
---

# Teensy DAQ documentation

Every Markdown artifact below `doc/` begins with YAML front matter containing
`type`, `title`, `created`, `tags`, and `related`. Related artifacts use
`[[Wiki-Links]]` so the project can be explored as a documentation graph.

## Organization

- `architecture/` describes system boundaries and component relationships,
  beginning with [[System-Overview]].
- `protocol/` contains versioned wire-contract specifications, beginning with
  [[Protocol-V1]].
- `decisions/` contains architecture decision records, beginning with
  [[ADR-001-Protocol-Wire-Contract]].
- `reference/` records durable inventories and implementation references,
  beginning with [[Foundation-Reuse-Inventory]].
- `results/` records reproducible test, build, benchmark, and hardware evidence,
  beginning with [[Phase-01-Synthetic-Prototype-Gate]].

Generated captures and scratch results remain outside version control. Small,
deterministic implementation fixtures belong under `firmware/tests/fixtures/`
or `daq_api/tests/fixtures/`; cross-language golden wire frames belong under
`protocol/fixtures/`. All remain tracked.
