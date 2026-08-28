---
type: reference
title: Teensy DAQ Python Package
created: 2026-08-27
tags:
  - teensy-daq
  - python
  - package
  - local-development
related:
  - '[[System-Overview]]'
  - '[[Foundation-Reuse-Inventory]]'
---

# Teensy DAQ Python package

This directory contains the private, local-development Python distribution for
the Teensy DAQ host API. Its installable distribution name is
`teensy-daq-local`, while its stable import package is `teensy_daq`.

The base installation includes PySerial for the eventual hardware transport.
NumPy remains optional, and test, lint, type-check, and package-build tools are
available through development extras:

```bash
python3 -m pip install --editable '.[dev,numpy]'
```

The local distribution is intentionally marked `Private :: Do Not Upload`.
Choose and review public distribution metadata before publishing anything.
See [[System-Overview]] for the package boundary and
[[Foundation-Reuse-Inventory]] for the implementation-pattern audit.
