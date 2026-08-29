---
type: report
title: Phase 08 Combined Acquisition Acceptance
created: 2026-08-29
tags:
  - teensy-daq
  - phase-08
  - combined-acquisition
  - adc
  - gpio
  - dma
  - hardware-validation
related:
  - '[[Acquisition-Pipeline]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[Protocol-V1]]'
  - '[[Phase-06-GPIO-DMA]]'
  - '[[Phase-07-Dual-ADC]]'
---

# Phase 08 combined acquisition acceptance

## Outcome

The complete Phase 08 gate passed on 2026-08-29. Clean build
`tdaq-25b8d210adb6e4ac` first passed the full local correctness, memory, map,
packaging, and throughput gate. That exact HEX then ran a 5-second full-rate
synthetic regression followed strictly sequentially by 10-second and
60-second physical combined-acquisition jobs on Teensy 4.0 hardware serial
20512460. The synthetic job passed all 71 checks, and both physical jobs
passed all 352 checks.

The accepted 60-second epoch delivered 59,541 complete frames from each
source: 60,255,492 ADC pairs and 241,021,968 packed GPIO samples. Its measured
payload rates were 3,999,984.746 B/s ADC and 3,999,917.280 B/s GPIO, for
7,999,902.026 B/s combined. ADC/GPIO frame coverage, common-epoch event
ratios, and final timestamps matched exactly; maximum wire skew was one frame.
There were zero live or complete-frame losses, ADC_ETC/eDMA/ring/cache/
packet/parser/transport errors, checksum/sequence/timestamp failures, or host
drops.

STOP deliberately discarded and reconciled the one active, incomplete DMA
tail from each engine. Those 874 ADC pairs and 3,498 GPIO samples were never
complete frames and are reported separately from live loss below. No complete
unsent frame or transmitted payload byte was discarded.

| Acceptance requirement | Result |
| --- | --- |
| Complete local gate | PASS: 26 generated outputs, Ruff, MyPy, 287 tests/12,919 subtests, optional NumPy probe, package artifacts, map/memory tests, benchmarks, and clean target compile |
| Exact physical rates | PASS: both sources within 0.01% of 4 MB/s in the 10-second and 60-second epochs |
| Common epoch | PASS: equal frame counts and final timestamps, exactly four GPIO events per ADC pair, at most one frame of wire skew |
| Live loss and errors | PASS: zero live/complete-frame loss and zero target/host fault counters; one incomplete active tail explicitly discarded at STOP |
| Bounded resources | PASS: packet high water 69/200 and 79/200; raw/packed ready high water 1/4; host RSS growth below 0.5 MB |
| Control latency | PASS: physical STATUS p99 3.051 ms and 2.243 ms versus the 100 ms Phase 04 limit |
| Fixture claims | Correctly limited: no external analog or digital stimulus; analog quality/aperture and digital pad timing were not graded |

No task-associated images were present; zero images were analyzed.

## Repairs made during the gate

The gate was allowed to fail on measured target evidence before the accepted
sequence. The final design makes four related repairs:

1. `FirmwareRuntime` now services physical acquisition before USB work and
   again between two bounded transmit visits. Each visit is limited to 8,192
   bytes and eight calls; each individual core copy is limited to 1,024 bytes.
   This preserves two opportunities per cooperative loop to fill the pinned
   USB TX ring without hiding ADC/GPIO completion ownership behind one long
   copy interval.
2. Physical-fault recovery moved to a cold helper. The hot ITCM image remains
   below its bank boundary while both acquisition visits retain same-loop
   fail-safe recovery.
3. The independent rig uses synchronous 16 KiB reads and 500 ms STATUS
   spacing. A background-reader experiment was rejected because the remote
   runner's constrained CPU quota let its validation and reader threads starve
   each other. The accepted synchronous path had lower receive gaps and no
   target pressure.
4. The no-fixture validator still checks every frame checksum and every ADC
   code's safe range, but avoids computing full-run analog means and GPIO
   transitions when it is forbidden to make those electrical claims. A
   declared fixture retains exhaustive envelope/mean and transition grading.

An earlier single post-producer USB visit eventually exhausted raw-ring
margin during long captures. Moving a visit before producers instead delayed
ADC completion servicing and produced completion mismatches. Both rejected
placements were superseded by commit `4e81406`, which passed the complete
gate. Exploratory jobs are not acceptance evidence.

## Local correctness and throughput gate

The final local gate ran against the accepted source before the exact clean
compile:

| Gate | Result |
| --- | --- |
| Generated protocol | PASS: all 26 generated files current |
| Ruff format/lint | PASS: 106 files formatted; no findings |
| MyPy | PASS: no issues in 81 source files |
| Full Python and host-C++ suite | PASS: 287 tests, 1 optional skip, and 12,919 subtests |
| Optional NumPy zero-copy probe | PASS under the system Python with NumPy installed |
| Package build | PASS: isolated sdist and pure-Python wheel |
| Combined memory/pipeline suite | PASS: 3 tests and 10 subtests, including the pinned map fixture |
| Whitespace | PASS: `git diff --check` |
| Exact target compile | PASS: clean firmware inputs, warnings `all`, manifest schema 10, ELF/map allocation inspection |

The deterministic parser plus complete synthetic-formula benchmark processed
16,596,992 wire bytes in each profile. Minimum headroom was 2.082 times the
8,094,861.660 B/s combined framed target, versus a required 1.25 times; median
headroom was 3.170 times and maximum was 3.275 times. The selected
`shift-mask-unrolled-4` GPIO packer processed 16,580,608 samples at
2,390.611 MB/s versus its 4.000 MB/s payload target.

The package artifacts were:

| Artifact | SHA-256 |
| --- | --- |
| `teensy_daq_local-0.0.0-py3-none-any.whl` | `9607ec39be83e239a9d660d3059cf18bd4757b72fa26f7e632f3c0fa780d8cc9` |
| `teensy_daq_local-0.0.0.tar.gz` | `874f05ba9575c0ebdc74ca3b8b5b7f575126f9406307622f727d6a9f486a81f3` |

## Accepted firmware artifact and map

The image was compiled from clean firmware inputs at commit
`4e81406053d0470d90b034520833fd2655fae62e`.

| Property | Value |
| --- | --- |
| Build ID / source ID | `tdaq-25b8d210adb6e4ac` / `25b8d210adb6e4acb0caf9f0ad7b399a22a8e7904d49d5f9ba0d546bd8765ffa` |
| Reproducible timestamp | `2026-08-29T08:23:17Z` |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Target/toolchain | Teensy core 1.62.0; Arduino CLI 1.4.1; Arm GNU 15.2.1; 600 MHz; USB Serial; standard `-O2`; warnings `all` |
| Manifest | schema 10; 12,788 bytes; SHA-256 `20bd0f5bf197808d1f4e43befc32a237bab7387b73656415f012b8c108a518b9` |
| Flash | 86,796 code + 23,496 initialized data + 8,488 headers bytes; 1,912,836 bytes free for files |
| RAM1 | 455,488 variables + 32,728 code + 40 padding bytes; 36,032 bytes free for locals/stack |
| RAM2 | 503,488 variables; 20,800 bytes free for heap |

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 1,724,504 | `85031cf94ffc112d7c53a14960d952b8a9d979f3215f6ff4911ee37bcf1710bc` |
| `firmware.ino.hex` | 334,187 | `f5f3e53ae3ccebb5986b2fee06cfe82d9c3a49321bd883cb3d8cbfbaef48e227` |
| `firmware.ino.map` | 817,878 | `a90610b24954d4d22d4bbac480f6a2a878dd196f77457d6ea8c7ad1986b0c20b` |

Every accepted loader run decoded 118,784 programmed bytes and reported 5.8%
usage. The staged upload tree contained exactly this one HEX.

### Combined RAM and peripheral allocation

The linker inspection proved every allocation aligned, in range, and
non-overlapping:

| Allocation | Region / address | Size |
| --- | --- | ---: |
| Primary packet bank | DTCM `0x20002ac0`, 105 frames | 430,080 bytes |
| Reserve packet bank | OCRAM `0x20200000`, 95 frames | 389,120 bytes |
| ADC descriptors + sink + four-buffer ring | OCRAM `0x2025f000` through `0x2025f160` allocations | 16,608 bytes |
| GPIO packed four-buffer ring | OCRAM `0x202640e0` | 16,256 bytes |
| GPIO diagnostic buffer | OCRAM `0x20268060` | 32 bytes |
| GPIO descriptors + sink + four-buffer raw ring | OCRAM `0x20268080` through `0x20268140` allocations | 64,960 bytes |

The accepted metadata retained the shared resource contract in
[[Acquisition-Pipeline]]: D6-D13 map to the packed GPIO byte; PIT0/XBAR input
56/DMAMUX 30/eDMA 2 drive the 4 MHz GPIO path; chained PIT1/XBAR input 57 feeds
ADC_ETC queues 0/4 through XBAR outputs 103/107 and eDMA 0/1. ADC eDMA
priorities 0/1 remain above GPIO priority 2, with ADC/GPIO IRQ priorities
48/64. Each stream covers the same 8,096 ticks per 4,096-byte frame.

## Sequential accepted jobs

The service reported coordinator mode `normal`, reachable Docker and USB hub,
a live worker, and queue depth zero before the physical submissions and after
the soak. No accepted jobs overlapped.

| Order | Stage | Job ID | Client UTC interval | Timed capture / checks | Result |
| ---: | --- | --- | --- | ---: | --- |
| 1 | Full-rate synthetic regression | `fbfb3178-fd5f-47f3-a1ac-dcd3ea0c13df` | `08:24:42Z`-`08:24:58Z` | 5.000106 s / 71 | PASS |
| 2 | Physical combined smoke | `b9eac21d-4cac-47d5-b137-3bcc63faa047` | `08:25:07Z`-`08:25:28Z` | 10.001459 s / 352 | PASS |
| 3 | Physical combined soak | `be3e20b9-2958-4730-a88a-fbc900ca461a` | `08:25:38Z`-`08:26:49Z` | 60.000697 s / 352 | PASS |

Every job pinned protocol 1, firmware 0.7.0, build
`tdaq-25b8d210adb6e4ac`, Teensy 4.0/i.MX RT1062, hardware serial 20512460,
4,096-byte frames, and Adler-32.

## Rates, layout, and common epoch

| Metric | Synthetic 5 s | Physical 10 s | Physical 60 s |
| --- | ---: | ---: | ---: |
| ADC complete frames | 4,951 | 10,140 | 59,541 |
| GPIO complete frames | 4,951 | 10,140 | 59,541 |
| ADC pairs | 5,010,412 | 10,261,680 | 60,255,492 |
| GPIO samples | 20,041,648 | 41,046,720 | 241,021,968 |
| ADC payload rate | 4,008,244.406 B/s | 4,000,054.766 B/s | 3,999,984.746 B/s |
| GPIO payload rate | 4,008,244.406 B/s | 3,999,650.025 B/s | 3,999,917.280 B/s |
| Combined payload rate | 8,016,488.811 B/s | 7,999,704.791 B/s | 7,999,902.026 B/s |
| ADC framed rate | included below | 4,047,486.245 B/s | 4,047,415.395 B/s |
| GPIO framed rate | included below | 4,047,076.705 B/s | 4,047,347.129 B/s |
| Combined framed rate | 8,111,545.991 B/s | 8,094,562.951 B/s | 8,094,762.525 B/s |

The 10-second ADC rate was 1,000,013.692 pairs/s (+0.00137%) and the GPIO
rate was 3,999,650.025 samples/s (-0.00875%). The 60-second rates were
999,996.187 pairs/s (-0.00038%) and 3,999,917.280 samples/s (-0.00207%).

| Epoch/layout evidence | Physical 10 s | Physical 60 s |
| --- | ---: | ---: |
| Complete ADC/GPIO frames | 10,140 / 10,140 | 59,541 / 59,541 |
| Four GPIO events per ADC pair | 41,046,720 / 41,046,720 | 241,021,968 / 241,021,968 |
| Final ADC/GPIO timestamp | 82,093,440 / 82,093,440 | 482,043,936 / 482,043,936 |
| Maximum wire-frame skew | 1 | 1 |
| ADC0 / ADC1 item counts | 10,261,680 / 10,261,680 | 60,255,492 / 60,255,492 |
| ADC0 observed code range | 857-1,668 | 819-1,667 |
| ADC1 observed code range | 907-1,723 | 870-1,725 |
| GPIO observed byte range | `0x20`-`0x20` | `0x20`-`0x20` |

Every received data frame matched its source, run ID, independent sequence,
first-sample timestamp, item count, equal coverage, fixed ADC0/ADC1 halfword or
packed-GPIO layout, safe value range, and Adler-32 trailer. The physical parser
checksummed 20,312 and 119,214 data/control frames and ended with zero buffered
bytes.

## Errors, STOP accounting, queues, latency, and memory

All live error/loss fields were zero in both physical jobs: source payload and
complete-frame drops; raw-ring overruns; ADC_ETC and eDMA errors; overwritten,
stale, destination, completion, schedule, cache/ownership, source, pipeline,
and chronology faults; packet pool/encoding/queue failures; checksum, frame,
firmware-parser, state, command, transport, and USB I/O errors; and host parser,
stale-response, discarded-frame, sequence, timestamp, and queue loss.

| Final STOP accounting | Physical 10 s | Physical 60 s |
| --- | ---: | ---: |
| ADC captured / complete transmitted pairs | 10,261,711 / 10,261,680 | 60,256,366 / 60,255,492 |
| ADC incomplete active tail discarded | 31 | 874 |
| GPIO captured / complete transmitted samples | 41,046,845 / 41,046,720 | 241,025,466 / 241,021,968 |
| GPIO incomplete active tail discarded | 125 | 3,498 |
| Incomplete ADC buffers / conversions | 1 / 0 | 1 / 0 |
| Complete/payload frame drops | 0 | 0 |

The firmware's aggregate item-drop fields equal only these explicit STOP-tail
counts. This is the designed source-first STOP policy, not a silent live gap:
all complete acquired buffers, packed frames, packet frames, and host frames
reconcile exactly.

| Bound/evidence | Physical 10 s | Physical 60 s | Limit |
| --- | ---: | ---: | ---: |
| Packet-owned high water | 69 / 200 | 79 / 200 | 200 |
| ADC/GPIO transmit high water | 35 / 34 | 40 / 39 | 200 each |
| Shared ready high water | 2 | 2 | 200 |
| ADC raw / GPIO raw / GPIO packed ready high water | 1 / 1 / 1 | 1 / 1 / 1 | 4 each |
| GPIO processing CPU | 22.10% | 22.10% | 100% |
| STATUS samples | 21 | 121 | at least 20 / 120 |
| STATUS p99 | 3.050 ms | 2.243 ms | 100 ms |
| STATUS maximum | 3.050 ms | 4.186 ms | 250 ms |
| Maximum all-command latency | 21.379 ms | 20.916 ms | 250 ms |
| Maximum receive gap | 37.276 ms | 42.898 ms | 250 ms |
| Host parser high water | 20,479 bytes | 20,479 bytes | 20,483 bytes |
| Host maximum read | 16,384 bytes | 16,384 bytes | 16,384 bytes |
| Host peak RSS growth | 245,760 bytes | 200,704 bytes | 33,554,432 bytes |

The 84,399 and 515,346 USB TX stall observations are cooperative polls that
found the bounded PJRC TX ring temporarily full; they are expected flow-control
telemetry. Both runs had zero partial writes, zero short-capacity deferrals,
zero USB I/O errors, zero packet exhaustion, and exact final byte/frame
reconciliation.

## Fixture limitations

No `ADC_FIXTURE_STIMULUS_JSON` declaration was provided. The rig therefore
proved safe 12-bit code range, layout, rates, timing metadata, checksums, and
transport integrity, but did not grade analog accuracy, gain, offset, noise,
linearity, bandwidth, or sample-and-hold aperture. The reported ADC minima and
maxima are observations, not analog-quality claims.

The registered fixture also declared no safe digital driver or transition
source. GPIO remained in `NON_DRIVING_CAPTURE` and observed a constant `0x20`.
That proves the input-only DMA/packing path and complete data reconciliation,
but not external transitions, pad propagation, voltage thresholds, or channel
bandwidth. These limits preserve the distinctions in [[ADR-003-GPIO-Clock-DMA]]
and [[ADR-004-ADC-Trigger-DMA]].

## Reproduction and retained evidence

The local gate commands were:

```bash
python3 tools/generate_protocol.py --check
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy daq_api/src daq_api/tests firmware/tools firmware/tests tools
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q firmware/tests/test_combined_acquisition.py
.venv/bin/python -m pytest -q -s daq_api/tests/test_streaming_correctness_performance.py
.venv/bin/python firmware/tools/build_firmware.py
```

The playbook working directory retains the exact manifest/ELF/HEX/map, package
artifacts, generated 5/10/60-second standalone rig programs, service health
responses, and complete stdout for every accepted job under
`.maestro/playbooks/Working/phase-08-combined-final-00001/`. The committed
acceptance program remains `firmware/tests/rig_combined_capture.py`.
