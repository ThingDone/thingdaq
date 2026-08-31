---
type: report
title: Phase 06 GPIO DMA Acceptance
created: 2026-08-28
tags:
  - thingdaq
  - phase-06
  - gpio
  - dma
  - hardware-validation
related:
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[Protocol-V1]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Phase-05-Checksum-Benchmark]]'
  - '[[Phase-04-Synthetic-Streaming]]'
---

# Phase 06 GPIO DMA acceptance

## Outcome

The complete Phase 06 gate passed on 2026-08-28. A clean Teensy 4.0 build,
`tdaq-e8096e0fd6ce3963`, completed a bounded diagnostic job, a 10-second
4 MHz smoke, and a 60-second 4 MHz GPIO-only stream, strictly sequentially on
hardware serial 20512460. Each accepted job ran the 1 kHz and 4 MHz clock/DMA
diagnostics, the fail-closed capture/mapping diagnostic, and a physical GPIO
stream before returning to `IDLE` with all 238 checks passing.

The final 60-second job validated 59,326 frames and 240,151,648 packed GPIO
samples at 4,002,131.180 payload bytes/s. Captured, packed, framed, transmitted,
and host-validated sample totals were identical. Every DMA, raw-ring, cache-
ownership, packer, packet, transport, parser, lifecycle, stale-completion, and
host-loss field was zero. The measured pack/copy/checksum/framing service used
29.60% of one 600 MHz core, queue high waters remained inside fixed capacity,
and process RSS grew by only 282,624 bytes.

| Acceptance requirement | Result |
| --- | --- |
| Complete local gate | PASS: protocol drift, Ruff, MyPy, 229 tests/11,485 subtests, package build, strict host C++, and target build |
| Packing throughput | PASS: five-run host minimum 1,854.535 MB/s, 463.634 times the 4 MB/s payload requirement |
| Integrated target processing budget | PASS: 29.60-29.64% for pack/copy/Adler-32/framing at full rate, below the 50% limit |
| Exact internal rate evidence | PASS: exact 1 kHz count and 8,192 DMA samples for 8,193 DWT boundaries at 4 MHz, within the explicit one-event tolerance |
| Sequential hardware jobs | PASS: diagnostic, 10-second smoke, then 60-second soak, each after healthy empty-queue preflight |
| Physical stream | PASS: 4 MB/s payload within 1%, continuous frame structure/sequence/timestamps/checksums, zero loss or error |
| Commands | PASS: worst STATUS p99 40.559 ms, maximum 80.988 ms, and every individual control command below 500 ms |
| Memory and queues | PASS: bounded target queues, empty final queues, bounded parser, and at most 282,624 bytes RSS growth |
| Fixture mapping/electrical scope | PASS within declared authority: non-driving internal capture; no output drive or external transition claim |

No task-related images were present; zero images were analyzed.

## Repairs made during the gate

The gate was allowed to fail on measured evidence and was repaired before the
accepted sequence:

1. STATUS had no target measure for the combined packer/checksum/packetizer
   budget. A wrap-safe DWT profile now measures cumulative cycles spent in the
   cooperative pack/copy/checksum/framing service and reports basis points in
   the existing fixed-size STATUS frame. The percentage calculation was moved
   to cold Flash after an intermediate build crossed an ITCM allocation
   boundary; the final image restores 35,168 bytes of RAM1 locals/stack space.
2. The independent rig required diagnostic `CITER == BITER`, but the snapshot
   is intentionally sampled while eDMA remains active after the first complete
   buffer. Silicon returned a valid live count of 4,040/4,048. The grader and
   [[Protocol-V1]] now require the live inclusive range `0..BITER`, with a
   regression that accepts in-flight progress and rejects overflow.
3. Immediate STOP necessarily discarded a partial DMA tail and surfaced it as
   loss, making the zero-drop acceptance condition impossible. Production STOP
   now sets `DREQ` only on the active TCD, waits at most 10 ms for the next
   complete 4,048-sample major-loop boundary, then performs the existing
   reverse-order shutdown and drains the complete buffer. Timeout or unexpected
   partial progress retains the prior fail-safe shutdown, exact loss accounting,
   and a nonzero STOP error. All accepted jobs observed zero stopped partial,
   loss, and STOP errors.
4. The rig already validated queue bounds internally but did not print their
   high-water values. The standalone program now emits raw, packed, and packet
   ownership high waters as machine-readable graded metrics.

These changes preserve the fixed frame and wire sizes in [[Protocol-V1]] and
the ownership/resource policy in [[ADR-003-GPIO-Clock-DMA]].

## Local correctness and throughput gate

The final complete local suite ran after the repairs and before the clean final
build:

| Gate | Result |
| --- | --- |
| Generated protocol | PASS: all 26 outputs current |
| Ruff format/lint | PASS: 67 Python files; no findings |
| MyPy | PASS: no issues in 65 source files |
| Python and strict host-C++ suite | PASS: 229 tests and 11,485 subtests |
| Python distribution | PASS: wheel and source distribution built |
| Exact target compile | PASS: clean build, all warnings, manifest and ELF/map resource inspection |

The optimized `shift-mask-unrolled-4` benchmark compiled the production packer
with GCC 13.3.0 using `-O3 -flto`, strict warnings, no exceptions, and no RTTI.
Five executions processed 16,580,608 samples apiece with a stable digest:

| Run | Packed payload MB/s | Multiple of 4 MB/s |
| ---: | ---: | ---: |
| 1 | 2,136.830 | 534.208x |
| 2 | 1,854.535 | 463.634x |
| 3 | 2,117.598 | 529.400x |
| 4 | 2,017.882 | 504.471x |
| 5 | 2,450.109 | 612.527x |

The host timing isolates only mapping and is not target evidence. The selected
Adler-32 implementation was previously measured at 121.484 MB/s from cold
OCRAM in [[Phase-05-Checksum-Benchmark]]. The current-image DWT result closes
the integration gap: the actual target pack/copy/checksum/framing path used
29.60-29.64% of one core at 4 MB/s, leaving 70.36-70.40 percentage points of
full-core headroom and 20.36-20.40 points below the declared 50% ceiling.

## Accepted firmware artifact

The build helper compiled clean firmware inputs at commit
`751f19e7c828806a31bff2ff99a68071930e4387`.

| Property | Value |
| --- | --- |
| Build ID / source ID | `tdaq-e8096e0fd6ce3963` / `e8096e0fd6ce39634243ab71b47c6af4347dfbf342e97bb131d98275e3be67d3` |
| Reproducible timestamp | `2026-08-28T21:09:09Z` |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Target/toolchain | Teensy core 1.62.0; Arduino CLI 1.4.1; Arm GNU 15.2.1; 600 MHz; USB Serial; standard `-O2`; warnings `all` |
| Manifest | schema 9; 11,021 bytes; SHA-256 `bcc7a0d3d4a44d61d016def3e15b7dc9448caa5ac38ed3bb186d2a56a5b1c259` |
| Flash | 56,904 code + 21,448 initialized data + 8,684 headers bytes; 1,944,580 bytes free for files |
| RAM1 | 456,352 variables + 32,648 code + 120 padding bytes; 35,168 bytes free for locals/stack |
| RAM2 | 482,784 variables; 41,504 bytes free for heap |

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 1,198,540 | `a8abb48c4dcd34000f6d5a675f67c54478253c838eb286e85726ad20ebdead44` |
| `firmware.ino.hex` | 244,907 | `af78d10f4335b017a39dd64a1458d2b9ea5812c663a56379e744d68f126e8bf8` |
| `firmware.ino.map` | 731,947 | `7a63091ceb5d38446ed0fbb8485f53d58a90becce688a3c36736cb61de9640ce` |

The loader decoded 87,040 programmed bytes and reported 4.3% usage in every
accepted job. The upload tree was checked to contain exactly one HEX before
each accepted submission.

### Link-verified fixed allocations

| Allocation | Placement | Capacity |
| --- | --- | ---: |
| Primary packet bank | DTCM `0x200022c0` | 106 frames / 434,176 bytes |
| Reserve packet bank | OCRAM `0x20200000` | 94 frames / 385,024 bytes |
| Checksum benchmark buffers | DTCM `0x200012c0` + OCRAM `0x2025e000` | 8,192 bytes total |
| Packed GPIO ring | OCRAM `0x2025f000` | 4 buffers / 16,256 bytes |
| Clock diagnostic line | OCRAM `0x20262f80` | 32 bytes |
| Raw DMA TCD bank | OCRAM `0x20262fa0` | 5 descriptors / 160 bytes |
| Raw DMA overflow sink | OCRAM `0x20263040` | 32 bytes |
| Raw DMA ring | OCRAM `0x20263060` | 4 buffers / 64,768 bytes |

Every DMA-visible allocation is 32-byte aligned. The fixed packet pool totals
200 frames/819,200 bytes; raw and packed ring depths are four apiece.

## Sequential accepted jobs

The service was healthy, in coordinator mode `normal`, with a live worker,
reachable Docker and USB hub, and queue depth zero immediately before every
accepted submission and after the final job. The client was version 1.0.0,
SHA-256 `23115388d9a62384cca074ac976c24986d77bd98538713901db3ec810e5c84ec`.
No accepted submissions overlapped.

| Order | Stage | Job ID | Client UTC interval | Timed stream / checks | Outcome |
| ---: | --- | --- | --- | ---: | --- |
| 1 | Reduced 1 kHz + production diagnostic gate | `4270f855-fdef-4a02-adba-ed91691eef85` | `21:09:54Z`-`21:10:10Z` | 5.039865 s / 238 | PASS |
| 2 | 10-second 4 MHz smoke | `df081800-42a3-4ef8-9f9a-4634468b5e56` | `21:10:26Z`-`21:10:48Z` | 10.024555 s / 238 | PASS |
| 3 | 60-second 4 MHz GPIO-only soak | `fce7911f-7a8a-4a18-ae5f-06f6be20fbd2` | `21:11:03Z`-`21:12:16Z` | 60.005941 s / 238 | PASS |

Each job independently pinned build ID `tdaq-e8096e0fd6ce3963`, protocol 1,
firmware 0.7.0, Teensy 4.0/i.MX RT1062, and hardware serial 20512460.

## Clock, route, and safe mapping evidence

The low-rate window configured PIT0 from the 24 MHz peripheral clock with
`LDVAL=23999`. It requested, independently scheduled, and DMA-captured exactly
64 events at 1 kHz in every accepted job. The production window used
`LDVAL=5`, requested 8,192 events, measured 8,193 DWT boundaries, and captured
8,192 DMA samples. Its event/request ratio was 1.0001220703125 and its
sample/event ratio was 0.9998779445868424, both inside the explicit one-event
tolerance. PIT0, XBARA1 input 56/output 0 rising-edge mode, DMAMUX source 30,
eDMA channel 2/priority 2, TCD width/count/link flags, clock gates, request
state, and zero eDMA error registers all matched [[ADR-003-GPIO-Clock-DMA]].

The registered fixture provides documentation-only metadata, not permission to
drive D6-D13 and not a loopback or external stimulus declaration. The rig
therefore selected `NON_DRIVING_CAPTURE`, retained one complete 4,048-word raw
buffer, analyzed 256 words with the production mapper, preserved unrelated
GPR27/GDIR bits, and restored all eight pins as GPIO2 inputs. The live TCD
remaining-count snapshots were 4,040, 4,041, and 4,039 out of 4,048; all were
valid active progress. Boundary-aligned diagnostic STOP captured 8,096 complete
samples with zero stopped partial in every job.

The observed fixture input was static (`packed AND = packed OR = 0x20`, zero
transitions). Consequently the hardware jobs do **not** claim external voltage,
pad transition, signal-integrity, skew, all-256-value electrical mapping, or
loopback correctness. Exact D6-D13 bit order and all 256 mapper outputs are
covered by the strict host-C++ tests; they are not misreported as pad-level
electrical evidence.

## Stream rate and reconciliation

The target is 4,000,000 one-byte samples/payload bytes per second. A fixed
4,096-byte frame carries 4,048 samples, so the corresponding framed target is
4,047,430.830 bytes/s.

| Metric | Diagnostic | 10 s smoke | 60 s soak |
| --- | ---: | ---: | ---: |
| GPIO frames | 5,012 | 9,937 | 59,326 |
| Samples/payload bytes | 20,288,576 | 40,224,976 | 240,151,648 |
| Payload rate | 4,025,619.121 B/s | 4,012,644.478 B/s | 4,002,131.180 B/s |
| Payload deviation | +0.6405% | +0.3161% | +0.0533% |
| Framed rate | 4,073,353.735 B/s | 4,060,225.243 B/s | 4,049,587.281 B/s |
| Captured = packed = framed = transmitted | 20,288,576 | 40,224,976 | 240,151,648 |
| Firmware GPIO items dropped | 0 | 0 | 0 |
| Raw samples lost / overruns | 0 / 0 | 0 / 0 | 0 / 0 |
| Packer samples dropped | 0 | 0 | 0 |

Every accepted data frame had the expected 4,096-byte shape, Adler-32 trailer,
physical-source flag, run ID, sequence, two-tick timestamp cadence, and 4,048
item count. No synthetic, gap, or overrun flag was accepted. The host parser
checksummed 5,077, 9,992, and 59,581 total data/control frames respectively and
ended with zero buffered bytes.

## CPU, queues, command latency, and memory

| Metric | Diagnostic | 10 s smoke | 60 s soak | Bound |
| --- | ---: | ---: | ---: | ---: |
| GPIO processing CPU | 29.61% | 29.64% | 29.60% | 50% |
| Raw-ready high water | 1 / 4 | 1 / 4 | 2 / 4 | 4 |
| Packed-ready high water | 1 / 4 | 1 / 4 | 1 / 4 | 4 |
| Packet-owned high water | 100 / 200 | 177 / 200 | 117 / 200 | 200 |
| STATUS samples | 50 | 40 | 240 | at least 50 / 40 / 240 |
| STATUS p99 | 31.865 ms | 25.074 ms | 40.559 ms | 100 ms |
| STATUS maximum | 31.865 ms | 25.074 ms | 80.988 ms | 250 ms |
| STOP latency | 11.151 ms | 11.606 ms | 22.983 ms | 500 ms |
| Parser high water | 69,631 bytes | 69,623 bytes | 69,631 bytes | 69,635 bytes |
| Peak RSS growth | 184,320 bytes | 188,416 bytes | 282,624 bytes | 33,554,432 bytes |

Final raw-ready, packed-ready, packet-ready, and packet-transmit depths were
zero in all jobs. Parser errors, stale responses, buffered parser bytes,
firmware parser/transport errors, hardware/invariant/source/pipeline/chronology
errors, resource conflicts, START/STOP errors, and stale DMA completions were
also all zero. The longest observed receive gap was 81.672 ms in the smoke and
remained within the fixed packet retention without loss.

## Retained evidence

Machine-readable logs and preflight/postflight JSON are retained in the
ignored workspace directory
`.maestro/playbooks/Working/phase-06-gpio-final-00001/`. Bulk GPIO captures were
not retained; frames were validated online and released.

| Stage | Raw log | Log SHA-256 | Submitted program SHA-256 |
| --- | --- | --- | --- |
| Diagnostic | `final-diagnostics.log` | `e545ff080a054b5aa8f67793eee60a7ff7777bf999058f43a896a85cc5072caf` | `e03c15e790a2c37e6007c809649e4c8897ab575968e3651687fc71be08dc0c76` |
| 10-second smoke | `final-smoke-10s.log` | `4469db1ebf60eee64f3e5e008c76d2b318d245b0a033ed071405e85173f48ae0` | `d4f00209ff37832385f1c25dfab4c9ad9a0ddde3c7d30cdd1500670ffaa049ea` |
| 60-second soak | `final-soak-60s.log` | `7e221bc000a6cb822a0fded0dde5a5951aac8cc611232e7e2f8859e6e0aa7e6a` | `d4e1207046af76887d4df7274372731ca47c3aa30c2aff1c87f3f1c19cff6c6e` |

The local packer evidence is `final-packer-benchmark.log`, SHA-256
`6a1f07f11edb56a7159f3c7453a56e888f49925320f3fa177277da9a9040dbe8`.
The final wheel and source archive were also built successfully and retained in
`final-dist/`.

### Excluded diagnostic attempts

| Job | Reason excluded |
| --- | --- |
| `7fa57825-3228-487e-8a6e-e834dd92ef6e` | Scratch upload contained a duplicated nested HEX; service rejected it before programming |
| `b17f6eeb-6fa1-46a6-a882-ad97497a4b23` | Valid silicon exposed the over-strict live-`CITER` host assertion |
| `ce64e2fd-014c-4d9c-88cf-b2b410519c41` | Superseded image exposed immediate-STOP partial-tail loss; short 1-second host rate window was also biased by START/STOP boundary traffic |

None contributes to acceptance. The complete final sequence used only the
clean `tdaq-e8096e0fd6ce3963` artifact and passed without retries.

## Limitations

- This is one Teensy 4.0, one service/USB path, and a longest duration of
  60 seconds; it is not a multi-board, environmental, or long-duration study.
- The fixture did not authorize output or declare external stimulus. External
  transitions, voltages, timing skew, and pad electrical behavior remain
  untested, explicitly rather than implicitly assumed.
- The DWT CPU field covers cooperative pack/copy/checksum/framing service. It
  does not claim whole-device energy use or every cycle in USB, control parsing,
  and the low-frequency major-loop ISR.
- Host packer throughput characterizes the implementation host only. Target
  acceptance rests on exact hardware clock evidence, full-chain DWT use,
  continuous frame validation, bounded queues, and zero final loss/errors.

Within those declared limits, the exact-rate GPIO DMA acquisition and packed
physical GPIO-only stream satisfy the Phase 06 acceptance gate.
