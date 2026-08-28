---
type: reference
title: System Overview
created: 2026-08-27
tags:
  - teensy-daq
  - architecture
  - foundation
related:
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
---

# System overview

Teensy DAQ is split into three independently testable areas:

- `firmware/` owns the Teensy 4.0 Arduino sketch, portable C++ modules,
  repository-local build tooling, and host-side firmware tests.
- `daq_api/` owns an installable Python src-layout package and its tests.
- `doc/` owns structured architecture, protocol, decision, reference, and
  result artifacts.

The intended runtime boundary is a versioned binary protocol carried over the
Teensy 4.0 native USB CDC byte stream. The host API must also support an
in-memory simulator so protocol and public-API behavior can be validated
without hardware. Wire constants will be generated from one machine-readable
source rather than maintained independently in C++ and Python.

This foundation does not yet claim acquisition, command, or streaming support.
Those capabilities are added behind the boundaries above in later tasks. See
[[Foundation-Reuse-Inventory]] for the source and pattern audit that informed
the scaffold.
