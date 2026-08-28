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

The base installation includes PySerial for the bounded hardware transport.
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
boundaries. `SerialTransport` implements the same interface over PySerial, so
command and streaming code does not depend on the concrete byte source:

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

## Production transport and background reader

`SerialTransport` configures finite PySerial read and write timeouts and adds
bounded open, flush, and close behavior. A write may report partial progress;
`BackgroundReader` serializes concurrent command writes and retries each
unwritten suffix within the command's overall deadline. Its default 64 KiB
reads are deliberately larger than USB packets because USB CDC is one byte
stream, not a packet-preserving message API.

`BackgroundReader` owns exactly one `IncrementalFrameParser`. One non-daemon
thread continuously feeds arbitrary read chunks into it, matches concurrent
responses by echoed request ID, and separates decoded ADC/GPIO blocks from
other non-response frames. Pending requests, block queues, and event queues are
all bounded. Request timeout removes the pending entry; an eventual unmatched
reply increments `late_responses`. STOP, close, parser failure, and disconnect
wake blocked callers and cancel outstanding requests with typed exceptions.

Both decoded queues use a **drop-oldest complete item** policy when full. The
newest data therefore remains visible during consumer stalls. The
`host_block_queue_drops` and `host_event_queue_drops` reader counters describe
only those local Python queue evictions: they never include firmware sequence
gaps, `GAP_BEFORE`/`OVERRUN_BEFORE` flags, or the firmware counters returned by
GET_STATUS. `stale_blocks_discarded` separately records blocks rejected because
their run ID is not the active START epoch.

## Executable offline demo

Both entry points below run the same bounded synthetic acquisition. They print
the discovered capabilities, ADC and GPIO ramps (including frame joins), final
counters, and the clean IDLE landing. Every sample is checked and a mismatch
returns a nonzero exit status:

```bash
python -m teensy_daq.demo --frame-count 2 --parser-chunk-size 17
teensy-daq-demo --frame-count 2 --parser-chunk-size 17
```
