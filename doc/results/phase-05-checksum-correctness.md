---
type: report
title: Phase 05 Checksum Correctness and Corruption
created: 2026-08-28
tags:
  - teensy-daq
  - checksum
  - corruption-testing
  - cross-language
  - phase-05
related:
  - '[[Checksum-Candidates]]'
  - '[[Protocol-V1]]'
  - '[[ADR-002-Checksum-Selection]]'
---

# Phase 05 checksum correctness and corruption

## Outcome

Adler-32, CRC-32C Castagnoli, and CRC-32/ISO-HDLC pass independent C++ and
Python correctness references, byte-for-byte little-endian cross-language
comparison, the deterministic corruption samples below, negotiated simulator
runs, and bad-trailer parser recovery. The portable benchmark tests also pass
with a deliberately wrapping 32-bit cycle counter, checked aggregation
overflow, calibrated overhead subtraction, repeatability, and explicit
compiler-optimization guards.

These results characterize the exact deterministic cases exercised by the
tests. They do not prove detection of every possible corruption, establish a
minimum Hamming distance, or provide authentication or any other security
property. The checksums in [[Protocol-V1]] are only accidental-error detectors.

## Independent correctness method

`firmware/tests/checksum_correctness_test.cpp` is compiled separately from the
production checksum source. Its references use bytewise Adler arithmetic and
bit-at-a-time reflected CRC recurrences with hard-coded parameters rather than
the production lookup tables. It checks five fixed vectors, including empty
input and ASCII `123456789`, then checks 33 length/reduction edges at every
byte alignment from 0 through 31. That is 1,056 alignment/length inputs per
candidate.

`firmware/tests/test_checksum_correctness.py` implements its own bytewise and
bitwise references. It checks the same fixed values and a 97-buffer corpus:
33 declared edges plus 64 variable-length buffers from seed `0x0C5EED05`.
The optimized C++ harness reads those exact bytes and emits only the three
little-endian 32-bit results for each buffer. Python compares all 1,164 output
bytes, covering 291 C++/Python result pairs without parsing formatted numbers.

| Input | Adler-32 | CRC-32C | CRC-32/ISO-HDLC |
| --- | ---: | ---: | ---: |
| empty | `0x00000001` | `0x00000000` | `0x00000000` |
| `a` | `0x00620062` | `0xC1D04330` | `0xE8B7BE43` |
| `Wikipedia` | `0x11E60398` | `0x2D0E3663` | `0xADAAC02E` |
| `123456789` | `0x091E01DE` | `0xE3069283` | `0xCBF43926` |
| `The quick brown fox jumps over the lazy dog` | `0x5BDC0FDA` | `0x22620404` | `0x414FA339` |

## Deterministic corruption observations

Every mutation below starts from the same 64-byte sequence `00 01 ... 3F`
unless the row names a protocol frame. “Detected” means the recomputed 32-bit
value differed from the original value, or the frame decoder rejected the
unchanged trailer. Counts are per candidate.

| Corruption family | Construction | Adler-32 | CRC-32C | CRC-32/ISO-HDLC |
| --- | --- | ---: | ---: | ---: |
| Single bit | Each of all 512 bit positions flipped once | 512 / 512 | 512 / 512 | 512 / 512 |
| Short burst | Widths 2–16 bits at six declared bit offsets | 90 / 90 | 90 / 90 | 90 / 90 |
| Transposition | 63 adjacent and 4 separated distinct-byte swaps | 67 / 67 | 67 / 67 | 67 / 67 |
| Insert/delete | 15 one-byte insertions and 5 one-byte deletions | 20 / 20 | 20 / 20 | 20 / 20 |
| Header | One valid data-header field changed with trailer retained | 1 / 1 | 1 / 1 | 1 / 1 |
| Payload | One payload byte changed with trailer retained | 1 / 1 | 1 / 1 | 1 / 1 |
| Trailer | One serialized trailer bit changed | 1 / 1 | 1 / 1 | 1 / 1 |
| Parser recovery | Bad-trailer frame followed by a valid bootstrap command | 1 / 1 | 1 / 1 | 1 / 1 |

The parser recovery case is split across an awkward 47-byte input boundary.
For each candidate it records exactly one checksum error and one
resynchronization, discards the complete corrupt frame, accepts the following
INFO request, and retains no buffered bytes.

## Negotiation and queue isolation

The dedicated regression test verifies that control traffic remains bootstrap
Adler-32, other control IDs fail with an algorithm mismatch, reserved and
unknown IDs fail closed, and each advertised candidate completes an
INFO→CONFIGURE→START→data→STOP simulator run with the negotiated ID preserved.

The lower-level separately compiled tests retain the concurrency-sensitive
coverage that cannot be represented by the synchronous simulator:

- `control_state_test.cpp` verifies atomic configuration transitions and
  unsupported selection rejection.
- `packet_buffer_pipeline_test.cpp` verifies the checksum snapshot for a packet
  epoch and rejects a producer completion labeled with another algorithm.
- `firmware_runtime_test.cpp` leaves prior-run Adler frames partially queued,
  verifies that a CRC-32C CONFIGURE returns `BUSY`, drains the old epoch, and
  admits only CRC-32C data after the queue becomes quiescent.
- The C++ command parser and Python incremental frame parser both recover from
  a bad trailer and preserve the next valid frame.

## Benchmark arithmetic and optimization guards

The portable fake counter begins at `UINT32_MAX - 50`, wraps during calibration
and measurement, and relies on the same unsigned subtraction required by DWT.
The test checks exact raw cycles, per-operation overhead subtraction, batch
extrema, and restored critical-section state. A second case makes each 32-bit
interval nearly a full counter revolution and requires the runner to return
`MEASUREMENT_OVERFLOW` when the batch aggregate exceeds `u32`.

Two identical runs must produce identical raw/net cycles, extrema, and digest.
The test binary is compiled with `-O3 -flto`; source-boundary assertions retain
the compiler memory barriers, volatile digest publication, and target
`noinline`/`noipa` checksum bodies that make every measured operation
observable.

## Reproduction

Run the focused tests from the repository root:

```bash
.venv/bin/python -m pytest -q \
  firmware/tests/test_checksum_correctness.py \
  firmware/tests/test_checksum_benchmark.py
```

The complete local gate remains:

```bash
.venv/bin/python -m pytest -q
```
