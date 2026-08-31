---
type: report
title: Phase 05 Checksum Benchmark
created: 2026-08-28
tags:
  - thingdaq
  - checksum
  - benchmark
  - hardware-validation
  - phase-05
related:
  - '[[ADR-002-Checksum-Selection]]'
  - '[[Phase-04-Synthetic-Streaming]]'
  - '[[Phase-05-Checksum-Physical-Campaign]]'
  - '[[Phase-05-Checksum-Local-Gate]]'
  - '[[Phase-05-Checksum-Correctness]]'
  - '[[Checksum-Candidates]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Protocol-V1]]'
---

# Phase 05 checksum benchmark

## Outcome

The selected Adler-32 configuration passed its final acceptance gate on
2026-08-28. A clean pinned build passed every local regression and the same
HEX image then completed three consecutive, strictly sequential 60-second
full-rate synthetic runs on Teensy 4.0 serial 20512460. Each job independently
validated all 15 fixed checksum vectors, ran all 14 selected-algorithm target
benchmark profiles, checked every received trailer and synthetic field, and
reconciled final firmware counters.

Across 180.001843 seconds of graded streaming, the rig accepted 355,754 data
frames and 356,492 trailers including control traffic. All checksum, pattern,
sequence, timestamp, firmware-drop, transport, parser, stale-response, and
discarded-byte fields were zero. Every host queue drained to zero, no target
queue exhaustion was observed, and every command remained inside the
[[Phase-04-Synthetic-Streaming]] latency bounds.

| Final gate | Result |
| --- | --- |
| Selected algorithm | PASS: standard Adler-32, checksum ID 1 |
| Local regressions | PASS: generated contract, format/lint, typing, complete Python/host-C++ suite, package build, and pinned target build |
| Artifact identity | PASS: one `thingdaq-c98936587626449d` image and one HEX SHA-256 in all three jobs |
| Consecutive physical runs | PASS: 3/3, strictly sequential after healthy empty-queue preflights |
| Target benchmark stability | PASS: one Q16.16-unit hot/cold cycles-per-byte range, fixed digest and cold-cache setup count |
| Stream correctness | PASS: every frame/trailer/pattern/sequence/timestamp checked; all error fields zero |
| Queue stability | PASS: fixed target capacity, no exhaustion, identical parser high water, bounded reader peaks, all queues empty at exit |
| Command latency | PASS: worst STATUS p99 8.474 ms, maximum 73.865 ms; worst other command 20.682 ms |

No images were associated with this task; zero images were analyzed.

## Selection result

[[ADR-002-Checksum-Selection]] applies a predeclared conjunctive policy: a
candidate must be cross-language correct, safe with reserved resources, exceed
81 MB/s on representative target memory, consume no more than 10% of one
600 MHz core at 8.1 MB/s, finish its isolated 60-second stream without loss or
corruption, and keep every established command-latency and queue measure within
10% of the Adler-32 baseline. Stronger accidental-error detection is preferred
only among candidates that pass every gate.

| Candidate | Cold OCRAM cycles/B | Cold MB/s | Projected CPU | Isolated 60 s stream | Relative command/queue gate | Decision |
| --- | ---: | ---: | ---: | --- | --- | --- |
| Adler-32 | 4.938919 | 121.483871 | 6.667526% | PASS, zero loss/corruption | Baseline; PASS | **Selected** |
| CRC-32C | 3.560394 | 168.520416 | 4.806519% | PASS, zero loss/corruption | STATUS p99 +196.139%; FAIL | Rejected as default |
| CRC-32/ISO-HDLC | 3.561356 | 168.475037 | 4.807816% | PASS, zero loss/corruption | STATUS maximum +23.340%; FAIL | Rejected as default |

Adler-32 was the only complete qualifier and therefore remains the production
data default and fixed control bootstrap. CRC-32C and CRC-32/ISO-HDLC remain
advertised, negotiable, and decodable under [[Protocol-V1]] so benchmarked
identifiers and retained evidence remain usable. The checksum detects
accidental corruption; it is not authentication and makes no security claim.

## Selected build and local gate

The build helper compiled clean firmware inputs at commit
`08a2e7ebaca88544238601f2b9e750569899df6c` with exact FQBN
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`, Teensy core 1.62.0,
Arduino CLI 1.4.1, and Arm GNU 15.2.1. The image uses USB Serial, a 600 MHz
CPU, standard `-O2` globally, and the already-inspected target-only CRC
optimization attributes.

| Build property | Value |
| --- | --- |
| Build ID / source ID | `thingdaq-c98936587626449d` / `c98936587626449dc934385cfc98645d6902cea9fb8b573b29b633ec13795340` |
| Deterministic build timestamp | `2026-08-28T16:09:02Z` |
| HEX | 184,397 bytes; SHA-256 `5bc66a481495b8df342c7500ff2daa053acc63ccea322ddc7b337ff6e0beff96` |
| ELF | 825,012 bytes; SHA-256 `b2f65833c0e0b049cf1ed215fd0a3981779f41ef6b868d96cdbe6936bf41853b` |
| Linker map | 647,320 bytes; SHA-256 `ac493ae10fd9e0040e89156b15d171b0df70d4ab1e59d9222bc36c89c705e2dd` |
| Build manifest | schema 6; SHA-256 `f962667bea180e2e61dc0e9d5f9e73869d38880966bcc868a35b09d6959a9921` |
| Flash | 35,172 code + 21,448 initialized data + 8,912 headers bytes |
| RAM1 | 455,488 variables + 32,712 code + 56 padding; 36,032 bytes free for locals/stack |
| RAM2 | 401,536 variables; 122,752 bytes free for heap |
| Packet storage | 106 DTCM + 94 OCRAM frames; 200 frames / 819,200 bytes total |

The exact HEX SHA-256 was recomputed immediately before each submission. All
three jobs' INFO responses independently returned the expected build ID and
hardware serial. The staged image was not rebuilt or replaced between jobs.

| Local regression | Result |
| --- | --- |
| Generated protocol drift | PASS: all 22 outputs current |
| Ruff format and lint | PASS: 57 files, no findings |
| MyPy | PASS: no issues in 57 source files |
| Pre-rig complete test suite | PASS: 200 tests and 10,555 subtests |
| Post-report complete test suite | PASS: 200 tests and 10,556 subtests |
| Python distribution | PASS: wheel and source distribution built |
| Pinned Teensy build | PASS: clean, all warnings, manifest/resource/symbol inspection |

## Benchmark and stream methodology

The remote service was checked immediately before every accepted submission.
Each preflight required HTTP 200, healthy worker/Docker/hub checks,
coordinator mode `normal`, and queue depth zero. No new job was submitted until
the prior client exited and the service returned to an empty queue. The same
self-contained program, SHA-256
`1ab49667b8b33608cd4772c501a7d09e83311379a5d761340206b8977a7c5686`,
ran in the service's network-disabled Python 3.13 environment using only the
standard library and pyserial.

Before serial access, each job checked empty, `123456789`, deterministic
64-byte and 512-byte buffers, and exact 4,092-byte frame coverage for Adler-32,
CRC-32C, and CRC-32/ISO-HDLC through independent bitwise and streaming paths.
It then required INFO to identify the expected build, board, protocol,
capability mask, and selected Adler-32 campaign.

The target benchmark used the verified 600 MHz DWT counter with calibrated
timer overhead, interrupt exclusion only inside timed intervals, compiler
barriers, volatile digest publication, and four batches of 256 operations per
profile. Its 14 profiles covered empty DTCM/OCRAM plus each nonempty vector in
native/hot DTCM, hot OCRAM, and meaningful cold-invalidated OCRAM. The summary
below uses the exact 4,092-byte production-frame coverage; each memory-state
row processed 4,190,208 bytes.

The stream configured checksum ID 1 and both synthetic sources, started one
new epoch, and captured for at least 60 seconds at the normal 8 MHz pacing
clock. The validator checked every frame boundary, checksum ID and trailer,
run ID, source sequence, timestamp cadence, flags, item count, ADC pair formula,
and GPIO formula online, then discarded payload bytes. STATUS was sampled
every 250 ms. STOP drained complete frames before final STATUS/counter and
queue reconciliation.

## Raw target benchmark summary

The cycle totals are overhead-subtracted sums across four batches. Batch
minimum and maximum are the raw per-batch net-cycle extrema. MB/s is decimal,
and projected CPU uses the declared 8,100,000 framed bytes/s workload.

| Run / job | Hot net cycles; batch min–max | Hot cycles/B; MB/s; CPU | Cold net cycles; batch min–max | Cold cycles/B; MB/s; CPU | Cold cache setup cycles | Digest |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 / `7f79b63b-41f2-4615-a62c-2868d6a5579f` | 16,863,328; 4,215,808–4,215,862 | 4.024460; 149.088287; 5.433014% | 19,485,252; 4,871,283–4,871,347 | 4.938919; 121.483902; 6.667526% | 1,209,874 | 3,039,746,001 |
| 2 / `89d42949-4a03-415e-9077-f192d22b3f32` | 16,863,327; 4,215,808–4,215,861 | 4.024460; 149.088287; 5.433014% | 19,485,208; 4,871,288–4,871,328 | 4.938904; 121.484161; 6.667511% | 1,209,874 | 3,039,746,001 |
| 3 / `069eb5b6-552a-456a-99ca-bacb507e580f` | 16,863,285; 4,215,808–4,215,849 | 4.024445; 149.088669; 5.432999% | 19,485,259; 4,871,287–4,871,336 | 4.938919; 121.483856; 6.667526% | 1,209,874 | 3,039,746,001 |

Hot and cold cycles per byte each span exactly one Q16.16 unit
(1/65,536 cycle/byte). The deterministic digest and cold-cache setup count are
identical across jobs. Across all 24 representative hot/cold batches, the
largest min-to-max span is 64 cycles out of more than 4.2 million cycles.

## Raw 60-second stream summary

| Run / job | Capture (s) | ADC / GPIO frames | Payload B/s | Framed B/s | Trailers checked | Max receive gap (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 / `7f79b63b-41f2-4615-a62c-2868d6a5579f` | 60.000851 | 59,293 / 59,293 | 8,000,488.608 | 8,095,356.061 | 118,832 | 64.316 |
| 2 / `89d42949-4a03-415e-9077-f192d22b3f32` | 60.000648 | 59,292 / 59,292 | 8,000,380.740 | 8,095,246.915 | 118,830 | 78.080 |
| 3 / `069eb5b6-552a-456a-99ca-bacb507e580f` | 60.000343 | 59,292 / 59,292 | 8,000,421.473 | 8,095,288.131 | 118,830 | 60.673 |

| Error field | Run 1 | Run 2 | Run 3 |
| --- | ---: | ---: | ---: |
| Firmware ADC items dropped | 0 | 0 | 0 |
| Firmware GPIO items dropped | 0 | 0 | 0 |
| Firmware parser errors | 0 | 0 | 0 |
| Firmware transport errors | 0 | 0 | 0 |
| Host parser errors | 0 | 0 | 0 |
| Host stale responses | 0 | 0 | 0 |
| Host stream bytes discarded | 0 | 0 | 0 |

The payload target is 8,000,000 B/s and the fixed-frame target is
8,094,861.660 B/s. All runs remained within the rig's 1% rate tolerance while
validating rather than bulk-capturing the stream.

## Queue and latency stability

| Run | Target capacity / exhaustion | Reader high water / capacity | Parser high water | Reader / parser final | Deferred START-boundary frames |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | 200 frames / none | 49,152 / 524,288 bytes | 20,479 bytes | 0 / 0 bytes | 3 |
| 2 | 200 frames / none | 98,304 / 524,288 bytes | 20,479 bytes | 0 / 0 bytes | 3 |
| 3 | 200 frames / none | 114,688 / 524,288 bytes | 20,479 bytes | 0 / 0 bytes | 3 |

The transient host-reader peaks reflect service-host scheduling and range from
9.375% to 21.875% of fixed capacity. They do not accumulate across runs: the
reader and parser end empty every time. Parser high water, deferred boundary
frames, fixed target capacity, zero exhaustion indication, zero drops, and
continuous sequence checks are stable across all three runs.

| Run | STATUS samples | p50 / p95 / p99 (ms) | STATUS maximum (ms) | Worst other command (ms) | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 240 | 2.025 / 2.782 / 3.075 | 4.613 | STOP 20.682 | PASS |
| 2 | 240 | 2.020 / 2.131 / 8.474 | 73.865 | final STATUS 20.564 | PASS |
| 3 | 240 | 2.034 / 2.140 / 2.775 | 32.813 | configured STATUS 20.360 | PASS |

The inherited limits are 100 ms for STATUS p99, 250 ms for STATUS maximum,
and 500 ms for an individual command. Run 2's isolated 73.865 ms STATUS sample
is visible in the raw evidence and remains below the declared maximum; its p99
also remains below 10 ms.

## Retained evidence and job identities

Machine-readable service logs and preflight JSON are retained under the
ignored workspace directory
`.maestro/playbooks/Working/phase-05-checksum-final-00001/`. Bulk payload
captures were not retained; frames were graded online and discarded.

| Run | Job ID | Raw log | Log SHA-256 |
| --- | --- | --- | --- |
| 1 | `7f79b63b-41f2-4615-a62c-2868d6a5579f` | `selected-adler32-60s-run-1.log` | `e45a9fb6366abfbc06c8fd901e7a623c72d6029809b4439ae61d7f20f09db289` |
| 2 | `89d42949-4a03-415e-9077-f192d22b3f32` | `selected-adler32-60s-run-2.log` | `7ed5a691d038f5c681629f1f88c1ca2b0cad03d3604c8ba52957d829f398d8bc` |
| 3 | `069eb5b6-552a-456a-99ca-bacb507e580f` | `selected-adler32-60s-run-3.log` | `b48b111e8948c5f3c88f6fd061778a4d92ff8235a87e32ffa33ddf7b408e5c01` |

## Limitations

- The acceptance evidence covers one Teensy 4.0, one USB/service path, three
  consecutive 60-second runs, and the deterministic synthetic ADC/GPIO source.
  It is not a multi-board study, long-duration soak, or validation of the later
  physical acquisition peripherals.
- Protocol v1 exposes fixed firmware packet capacity, loss/error counters, and
  frame continuity, but not internal firmware queue current/high-water depth.
  This report therefore uses the linked 200-frame capacity, zero exhaustion,
  zero drops, continuous sequences, and bounded host queues rather than
  inventing an unavailable target high-water number.
- The remote service does not echo a cryptographic firmware hash over the wire.
  The same locally hashed staged HEX was submitted each time, while firmware
  INFO independently proved the same source-derived build ID on every run.
- Target cycles describe these exact implementations, memory states, compiler,
  clock, and image. Host queue and latency observations also include the
  service container, kernel scheduling, USB, and CDC path.
- The finite correctness/corruption campaign in
  [[Phase-05-Checksum-Correctness]] is not an exhaustive error-code proof, and
  none of the checksums provides authentication or adversarial integrity.

Within those limits, the final evidence accepts Adler-32 as the production
protocol-v1 checksum and closes the Phase 05 benchmark and selection gate.
