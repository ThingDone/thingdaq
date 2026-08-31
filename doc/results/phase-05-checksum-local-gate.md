---
type: report
title: Phase 05 Checksum Local Gate
created: 2026-08-28
tags:
  - thingdaq
  - checksum
  - benchmark
  - firmware-build
  - phase-05
related:
  - '[[Checksum-Candidates]]'
  - '[[Phase-05-Checksum-Correctness]]'
  - '[[Protocol-V1]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Phase-04-Synthetic-Streaming]]'
  - '[[ADR-002-Checksum-Selection]]'
---

# Phase 05 checksum local gate

## Outcome

The complete pre-rig checksum gate passed on 2026-08-28 at implementation
revision `334a67b6c5f098e6f95b9e5ae205ea6a7050bd06`. Adler-32, CRC-32C, and
CRC-32/ISO-HDLC agree across the independent C++ references, Python references,
optimized implementations, generated protocol tables, fixtures, and the
self-contained rig codec. All three candidates therefore remain eligible for
the physical campaign. No implementation repair or local candidate rejection
was required, and the production default remains Adler-32 until the later
fixed-policy selection task.

This gate did not enumerate a serial port, contact the rig, upload firmware, or
use target timing as a substitute for the forthcoming on-device evidence. See
[[Checksum-Candidates]] for the implementation survey and
[[Phase-05-Checksum-Correctness]] for the finite corruption-test methodology
and its non-security limitations.

| Gate | Result |
| --- | --- |
| Generated protocol drift | PASS: all 22 tracked outputs current |
| Ruff format and lint | PASS: 57 files; no findings |
| MyPy | PASS: no issues in 57 source files |
| Python and host-C++ suites | PASS: 195 tests and 10,546 subtests |
| Wheel and source distribution | PASS |
| Exact Teensy 4.0 compile | PASS: core 1.62.0, USB Serial, 600 MHz, standard `-O2`, all warnings |
| Enabled implementation inspection | PASS: all three bodies, both CRC tables, shared dispatch, and both benchmark buffers present |
| Phase 04 map/resource comparison | PASS: all new large allocations accounted for |
| Repeated host checksum benchmark | PASS: three runs with warm-up, seven timed batches per path, and stable digests |
| Hardware access or upload | NOT RUN: deliberately excluded from the local gate |

## Correctness and protocol agreement

The complete suite includes separately compiled production C++ modules rather
than Python-only mirrors. The checksum correctness executable is built with
`-O3 -flto` and checks hard-coded empty/nonempty vectors, independent bytewise
Adler arithmetic, independent bit-at-a-time CRC recurrences, 32 alignments, and
33 length/reduction edges. A deterministic 97-buffer corpus then compares 291
C++/Python result pairs as 1,164 exact little-endian bytes.

The corruption suite retains all sampled single-bit, burst, transposition,
insert/delete, header, payload, and trailer cases plus parser recovery after a
bad trailer. Negotiation tests cover each advertised algorithm, bootstrap
Adler control traffic, unsupported-ID rejection, configuration transitions,
and prior-run queue isolation. The benchmark fake covers timer wrap,
calibrated-overhead subtraction, checked aggregate overflow, repeatability,
interrupt-state restoration, compiler barriers, and observable digest
publication.

`tools/generate_protocol.py --check` reported all 22 outputs current. The
source and representative generated identities at the gate revision are:

| Artifact | SHA-256 |
| --- | --- |
| `protocol/protocol-v1.json` | `72da74093b5bd775381bb63b1a501da2fc1242ae9d2ec2cbbb6ef01aea771ac4` |
| Python generated constants | `fe15b8cf25f749cadeb45329e46445cfea455c38060f75e3fccc1cdae4415b8a` |
| C++ generated constants | `4d30161c5f0c5026e68f4ace1d46301a8bf87af21d526dff26f10f3bc6806c18` |
| Golden-fixture manifest | `a7fd942197e47b18fb4dbdfd783841d446e6cac38f18e7d676d460943b0c01d5` |

Any mismatch in those tables, fixed values, independent references, or
cross-language bytes would have failed the suite before a candidate could be
sent to the rig. None occurred.

## Pinned firmware build

The clean build helper compiled every enabled implementation through the exact
[[Firmware-Resource-Map]] configuration:

| Property | Value |
| --- | --- |
| Build ID | `thingdaq-7749b6add37edd5b` |
| Source fingerprint | `7749b6add37edd5b49cfb15a40140b050ab71235e32651473a2005aa5ef6a24e` |
| Firmware inputs | Clean; no generated drift |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Teensy core | `teensy:avr` 1.62.0 |
| Compiler | Arm GNU 15.2.1, 15.2.Rel1 build arm-15.86 |
| CPU / USB / optimization | 600 MHz / USB Serial / standard `-O2` |
| Warning mode | Arduino CLI `all` |

The only host warning was the absent local Teensy udev rule. It is irrelevant
to compile-only verification and the service-owned upload/serial path; no
upload was attempted.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.elf` | 778,052 | `07fe974f37d7e98642db5632e6e102fb1189a60313fdd659c5fa92aefd70c59a` |
| `firmware.ino.hex` | 141,197 | `226b70582f05c73a98666841b98bc22bace034bd5f6861ad5f7aa4b10c449648` |
| `firmware.ino.map` | 647,140 | `e1ae722aeb2e23b3596489607b3447b016f0d6e2f83f4febbc44e12f31d91110` |

The manifest verifies all three checksum bodies as executable text: 120 bytes
for Adler-32 and 48 bytes each for CRC-32C and CRC-32/ISO-HDLC, plus an 84-byte
shared dispatch. Each CRC uses one 1,024-byte table in a distinct
`.progmem.checksum.*` Flash section and consumes zero table RAM.

## Map and resource comparison

For a like-for-like baseline, the same pinned helper rebuilt detached revision
`bd0638f` from the accepted [[Phase-04-Synthetic-Streaming]] result. That clean
baseline reproduced build ID `thingdaq-9fb124f80183ed61` and its recorded resource
summary. The temporary worktree was removed after its manifest and map were
copied into the ignored evidence directory.

| Region | Phase 04 baseline | Phase 05 local candidate | Delta |
| --- | ---: | ---: | ---: |
| Flash code | 29,552 | 34,324 | +4,772 |
| Flash initialized data | 5,064 | 7,112 | +2,048 |
| Flash headers | 8,388 | 8,736 | +348 |
| Total Flash occupancy | 43,004 | 50,172 | +7,168 |
| RAM1 variables | 407,552 | 411,712 | +4,160 |
| RAM1 free for locals/stack | 83,968 | 79,808 | -4,160 |
| RAM2 variables | 12,416 | 16,512 | +4,096 |
| RAM2 free for heap | 511,872 | 507,776 | -4,096 |

The 2,048-byte Flash-data increase is exactly the two memory-mapped CRC tables.
The RAM changes contain one 4,096-byte, 32-byte-aligned DTCM benchmark buffer,
one 4,096-byte, 32-byte-aligned DMA-visible OCRAM benchmark buffer, and 64 bytes
of bounded runner/runtime bookkeeping and alignment. The manifest locates the
buffers at `0x200012c0` and `0x20200000`, respectively. No checksum lookup table
is copied to RAM, and the map contains no unexpected large allocation or new
acquisition-peripheral owner.

## Repeated host benchmark

Three independent package-benchmark invocations covered every candidate and
both complete 4,096-byte production frame layouts. Each invocation performed
16 untimed warm-up operations followed by seven timed batches of 64 operations
for encode and validation separately. Corpus construction and warm-up were
excluded from timing. The table reports the median across the three per-run
batch medians, followed by the slowest individual batch across all runs, in
decimal MB/s.

| Algorithm / backend | Frame | Median encode / validate | Slowest encode / validate batch |
| --- | --- | ---: | ---: |
| Adler-32 / `zlib.adler32` | ADC | 44.45 / 45.52 | 40.84 / 44.01 |
| Adler-32 / `zlib.adler32` | GPIO | 499.91 / 497.33 | 474.06 / 447.32 |
| CRC-32C / Python 256-entry table | ADC | 9.82 / 9.72 | 9.57 / 9.27 |
| CRC-32C / Python 256-entry table | GPIO | 12.18 / 12.13 | 12.01 / 11.92 |
| CRC-32/ISO-HDLC / `zlib.crc32` | ADC | 44.48 / 45.10 | 43.39 / 44.23 |
| CRC-32/ISO-HDLC / `zlib.crc32` | GPIO | 508.14 / 505.27 | 479.87 / 461.00 |

Every encode and validation digest was identical across all three invocations.
These timings characterize this CPython 3.12.3 x86-64 host only. They are
deliberately non-grading and do not satisfy or replace the later selection
policy's on-device throughput and projected-CPU requirements.

## Reproduction and retained scratch evidence

The gate used Linux 6.17.0 x86-64, CPython 3.12.3, pytest 9.1.1, Ruff 0.16.5,
MyPy 2.3.1, and Ubuntu GCC 13.3.0. From the repository root:

```bash
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/ruff format --check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/ruff check daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/mypy daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/python -m pytest -q
.venv/bin/python firmware/tools/build_firmware.py
.venv/bin/python -m build daq_api
PYTHONPATH=daq_api/src .venv/bin/python -m thingdaq.checksum_benchmark \
  --algorithms all --batches 7 --iterations 64 --warmups 16
```

Raw JSON from the three host runs, both manifests, and both linker maps are
retained under
`.maestro/playbooks/Working/phase-05-checksum-local-gate-00001/`. The host JSON
SHA-256 values are, in run order,
`7bb71c3a4dfed17827b6c1679e197c668a57c70158047432dbf95128fa66b3c6`,
`93427d85a8e127069ea5ba218c227fb513acd7211e93d2a7e51d1500a604e9c9`,
and `c4da87e6c9394e65b4e27263adb70ab5aa9083c48cf228e8e0aa943687d466cf`.
