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

## Offline simulator API

The synchronous `TeensyDAQ` facade operates on a small `ByteTransport`
interface. `InMemoryTransport` connects that facade to `SimulatedDevice`
through encoded protocol-v1 bytes, including arbitrary partial read/write
boundaries. A future serial transport can implement the same interface without
changing command or streaming calls:

```python
from teensy_daq import AdcBlock, TeensyDAQ

with TeensyDAQ.simulated(read_chunk_size=47) as daq:
    info = daq.info()
    applied = daq.configure(adc=True, gpio=True)
    run_id = daq.start()

    for block in daq.blocks(4):
        if isinstance(block, AdcBlock):
            print(run_id, block.sequence, block.pair(0))

    final = daq.status()
    daq.stop()
```

The simulator advertises only the deterministic synthetic source. Each
successful START allocates a new run ID, resets both stream epochs and
counters, and produces ADC then GPIO frames in a repeatable round-robin order
when both streams are enabled. INFO and STOP are idempotent; closing the facade
stops an active run before closing its transport.
