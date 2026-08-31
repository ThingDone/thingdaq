---
type: report
title: Phase 07 Dual ADC Acceptance
created: 2026-08-28
tags:
  - thingdaq
  - phase-07
  - adc
  - adc-etc
  - dma
  - hardware-validation
related:
  - '[[ADR-004-ADC-Trigger-DMA]]'
  - '[[Protocol-V1]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Phase-06-GPIO-DMA]]'
---

# Phase 07 dual ADC acceptance

## Outcome

The complete Phase 07 gate passed on 2026-08-28. Clean build
`thingdaq-5eb59f8fd8b9d65f` ran a bounded trigger/DMA diagnostic, a 10-second
full-rate smoke, and a 60-second ADC-only soak strictly sequentially on Teensy
4.0 hardware serial 20512460. Each accepted job independently verified the
firmware and board identity, both calibrations, the PIT/XBAR/ADC_ETC register
route, conversion-completion timing, paired eDMA storage, every frame and
checksum, STATUS responsiveness, final queue drainage, and zero loss/error
telemetry. All 174 checks passed in each job.

The final soak delivered 60,041,960 ADC pairs in 59,330 frames over
60.011482 seconds. Its timed rate was 1,000,069.415 pairs/s per converter,
0.0069% above the exact 1 MHz target. ADC0/ADC1 DMA major-loop, buffer,
framing, transmission, and host totals matched. Every ADC_ETC, eDMA, cache/
ownership, ring, packet, parser, transport, lifecycle, and host drop/error
counter was zero.

| Acceptance requirement | Result |
| --- | --- |
| Complete local gate | PASS: 26 generated outputs current, Ruff, MyPy, 260 tests/12,337 subtests, target build, ELF/map inspection |
| Frame handling | PASS: parser/formula minimum 16.647 MB/s versus 8.095 MB/s combined target; optimized ADC validator 7.399 Mpair/s versus 1 Mpair/s |
| Exact ADC settings | PASS: 12-bit, `uint16_t`, 0-4095, 37.5 MHz ADCK, no averaging, three-ADCK sample setting |
| Rate and phase arithmetic | PASS: exact 1 MHz trigger, eight ticks/pair, raw delays 0/75 and effective delays 1/76, nominal four ticks/500 ns |
| Completion diagnostic | PASS: 296, 296, and 312 DWT cycles versus `300 +/- 120`; matched nonzero completion counts |
| Sequential hardware jobs | PASS: diagnostic, 10-second smoke, then 60-second soak, each after a healthy empty-queue preflight |
| Stream correctness | PASS: every pair layout, range, sequence, timestamp, run, source flag, item count, and Adler-32 trailer validated |
| Errors and loss | PASS: zero ADC_ETC/eDMA/ring/cache/frame/packet/host drops or errors and zero STOP-discarded pairs |
| Commands and memory | PASS: 58.851 ms worst STATUS latency, bounded target queues, 172,032-byte worst RSS growth |
| Analog claims | Correctly limited: A0/A1 were unstimulated, so analog quality, accuracy, bandwidth, and aperture were not graded |

No task-associated images were present; zero images were analyzed.

## Repairs made during the gate

The gate was allowed to fail on measured target evidence. Four repairs were
completed and retested before the accepted sequence:

1. The i.MX RT1062 ADC_ETC `CTRL` reset value retained `TSC_BYPASS` after the
   first zero write. The target adapter now performs the two writes required
   to leave reset and then clear bypass, matching the silicon behavior and the
   pinned PJRC setup pattern. This changed BOOT evidence from configuration
   flags 23/error `0x80` with zero completions to all flags set and no error.
2. The continuing 1 MHz queue-0 completion interrupt could starve the
   equal-priority queue-4 first-completion timestamp. Each diagnostic ISR now
   latches exactly its first completion and disables only its own NVIC line;
   the ADC_ETC error IRQ stays live. The observed cross-converter completion
   delta then became 296-312 cycles around the 300-cycle expectation.
3. Command arrival can occur mid-generation. Immediate trigger shutdown
   therefore produced a truthful partial-buffer loss on STOP. Production STOP
   now waits until both DMA channels are in the first quarter of the same
   generation, atomically adds `DREQ` to both active TCDs, waits at most 10 ms
   and 2,000,000 polls for the matching complete boundary, then stops triggers
   before DMA teardown. Timeout retains fail-safe shutdown and exact loss/error
   accounting. Every accepted job observed zero stopped partial pairs and zero
   STOP errors.
4. The original independent rig validator made two Python method calls per
   received pair and could backpressure the worker despite the MCU remaining
   error-free. Frame-local accumulation preserves the check of every ADC0 and
   ADC1 code, fixture envelope, sum, count, minimum, and maximum while raising
   local throughput from 1.555 to 7.399 Mpair/s. Detailed failure STATUS output
   was added so future backpressure and target faults remain distinguishable.

The firmware repairs are commits `733e2e8`, `79e2af1`, and `fd00c39`; the rig
hot-loop repair is commit `e0762cd`. Failed exploratory jobs are not counted as
acceptance evidence: `e22e1a01-0674-425e-98c3-934211a6cddf` exposed ADC_ETC
reset state, `d1ca8859-2626-454f-b694-a5cdf0a1d5c2` exposed diagnostic IRQ
starvation, `be567852-96c7-4e3a-b6bf-ecd2a5a4f22e` exposed partial STOP loss,
and `5f1ac453-4ff1-4aa9-9b79-e2c61926385d` exposed host-validator
backpressure. A rejected empty-artifact routing attempt never programmed the
board and is likewise excluded.

## Local correctness and throughput gate

The final local gate ran after all tracked repairs:

| Gate | Result |
| --- | --- |
| Generated protocol | PASS: all 26 outputs current |
| Ruff format/lint | PASS: 76 files formatted; no findings |
| MyPy | PASS: no issues in 75 source files |
| Python and strict host-C++ suite | PASS: 260 tests and 12,337 subtests |
| Whitespace | PASS: `git diff --check` |
| Exact target compile | PASS: clean firmware inputs, all warnings, manifest schema 10, ELF/map resource validation |

The existing incremental parser plus full synthetic-formula benchmark
processed 16,596,992 wire bytes in three deterministic chunk profiles. Its
minimum was 16.647 MB/s, 2.057 times the approximately 8.095 MB/s combined
ADC/GPIO framed target; the median headroom was 3.211 times. The independent
full-frame checksum benchmark selected Adler-32 and measured median ADC-frame
encode/validation rates of 43.681/44.884 MB/s versus its 8.1 MB/s target.

The final physical ADC validator benchmark processed 5,060,000 pairs in
0.683882 seconds without retaining frames: 7,398,933 pairs/s and 29.947 MB/s
of framed data, 7.399 times the production pair rate. This host measurement is
not target timing evidence; the sequential rig streams below close that gate.

## Accepted firmware artifact and map

The exact image was compiled from clean firmware inputs at commit
`fd00c398b5d33813d42868bad15ff72e7f58ae4c`.

| Property | Value |
| --- | --- |
| Build ID / source ID | `thingdaq-5eb59f8fd8b9d65f` / `5eb59f8fd8b9d65f55513aa0c26625c6afeec1c9b78837206a655ff05d165b38` |
| Reproducible timestamp | `2026-08-29T02:03:54Z` |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Target/toolchain | Teensy core 1.62.0; Arduino CLI 1.4.1; Arm GNU 15.2.1; 600 MHz; USB Serial; standard `-O2`; warnings `all` |
| Manifest | schema 10; 12,692 bytes; SHA-256 `482bbd938216c7f005ce69dd441ffdfc1cd506ecc8eceed6a576809500fc2188` |
| Flash | 78,524 code + 23,496 initialized data + 8,568 headers bytes; 1,921,028 bytes free for files |
| RAM1 | 454,912 variables + 32,472 code + 296 padding bytes; 36,608 bytes free for locals/stack |
| RAM2 | 503,488 variables; 20,800 bytes free for heap |

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 1,592,060 | `91e56ef0f6dbeb5474836152b93fd8ef1bf0ce35a083d688916f6158e51e7c2a` |
| `firmware.ino.hex` | 311,147 | `ea7ff1fb668bdcf6233fea2f6cf34db64c5a971b11e9051eccf6d6223158cf52` |
| `firmware.ino.map` | 802,819 | `8cc317cc9ddaf697341d93d44245cb7b7d776be980417bc0df24cf61728e15ed` |

The loader decoded 110,592 programmed bytes and reported 5.4% usage in all
accepted jobs. The staged upload tree contained exactly one HEX.

### Phase 06 resource delta

The comparison baseline is rebuilt Phase 06 commit
`9166bab527af4f43f6b7de5dfca0cc073b7cdeb5`, build
`thingdaq-e8096e0fd6ce3963`.

| Resource | Phase 06 | Accepted Phase 07 | Delta |
| --- | ---: | ---: | ---: |
| Flash code | 56,904 | 78,524 | +21,620 bytes |
| Flash initialized data | 21,448 | 23,496 | +2,048 bytes |
| Flash headers | 8,684 | 8,568 | -116 bytes |
| RAM1 variables | 456,352 | 454,912 | -1,440 bytes |
| RAM1 code | 32,648 | 32,472 | -176 bytes |
| RAM1 locals/stack free | 35,168 | 36,608 | +1,440 bytes |
| RAM2 variables | 482,784 | 503,488 | +20,704 bytes |
| RAM2 heap free | 41,504 | 20,800 | -20,704 bytes |

The added ADC DMA allocation is 16,608 bytes of 32-byte-aligned OCRAM:
320 bytes of descriptors at `0x2025f000`, a 32-byte two-halfword sink at
`0x2025f140`, and a 16,256-byte four-buffer ring at `0x2025f160`. One
4,096-byte packet frame moved from DTCM to OCRAM, explaining the remaining
RAM2 delta while preserving the 200-frame/819,200-byte pool as 105 DTCM plus
95 OCRAM frames. The two DMA completion ISRs remain in ITCM at `0x00000f90`
and `0x00000fa0`; the STOP-boundary and teardown paths are cold Flash at
`0x60001f94` and `0x60002710`, preserving stack headroom.

## Sequential accepted jobs

The service reported coordinator mode `normal`, reachable Docker and USB hub,
a live worker, and queue depth zero before every accepted submission and after
the soak. Service API version was 1.0.0. No accepted jobs overlapped.

| Order | Stage | Job ID | Client UTC interval | Timed stream / checks | Outcome |
| ---: | --- | --- | --- | ---: | --- |
| 1 | Bounded trigger/DMA diagnostic plus 5-second stream | `6405ca3b-d111-470b-a7ea-c5a7bfdcf668` | `02:13:13Z`-`02:13:30Z` | 5.044163 s / 174 | PASS |
| 2 | 10-second full-rate ADC smoke | `1772044a-6ac9-4641-a1d6-e9392aabf4bf` | `02:13:44Z`-`02:14:06Z` | 10.024361 s / 174 | PASS |
| 3 | 60-second 1 MS/s-per-converter soak | `464b9c80-f04e-4408-8a80-fc97a6cc0ac6` | `02:14:20Z`-`02:15:31Z` | 60.011482 s / 174 | PASS |

Every program pinned protocol 1, firmware 0.7.0, build
`thingdaq-5eb59f8fd8b9d65f`, Teensy 4.0/i.MX RT1062, and hardware serial 20512460.
Before its timed epoch, each job also ran a bounded production-schedule capture
and stopped cleanly: 40, 40, and 39 complete frames with matched DMA loops and
zero loss.

## Converter, trigger, and completion evidence

The accepted INFO and STATUS metadata retained the primary setting; the
documented 10-bit fallback was neither authorized nor used.

| Setting | Accepted value |
| --- | --- |
| Logical ADC0 | A0/D14, NXP ADC1 channel 7, ADC_ETC queue 0, eDMA 0 / DMAMUX 24 |
| Logical ADC1 | A1/D15, NXP ADC2 channel 8, ADC_ETC queue 4, eDMA 1 / DMAMUX 88 |
| Result format | 12-bit codes 0-4095 in one little-endian `uint16_t` per converter |
| Reference/range metadata | nominal 3.3 V reference and nominal 0-3.3 V input range |
| Conversion clock | synchronous 150 MHz IPG divided by four = 37.5 MHz ADCK |
| Sampling | high-speed, no hardware averaging, shortest three-ADCK sample setting, conversion mode 2 |
| Pair layout | `adc0[0], adc1[0], adc0[1], adc1[1], ...`; 1,012 pairs / 4,048 payload bytes |
| Timestamp schedule | 8 MHz epoch; pair `n` at `t0 + 8n`, ADC1 metadata at `t0 + 8n + 4` |

| Evidence | Diagnostic | 10 s smoke | 60 s soak | Bound |
| --- | ---: | ---: | ---: | ---: |
| ADC0 calibration | 4,718 cycles | 4,710 cycles | 4,722 cycles | 1-6,000,000 |
| ADC1 calibration | 22,140 cycles | 22,140 cycles | 22,148 cycles | 1-6,000,000 |
| Completion delta | 296 cycles | 296 cycles | 312 cycles | 180-420 |
| Completion diagnostic elapsed | 14,181 cycles | 14,189 cycles | 14,189 cycles | 1-2,400,000 |
| Completion counts | 1 / 1 | 1 / 1 | 1 / 1 | equal, nonzero |

The 24 MHz PIT root with PIT0 `LDVAL=5` produces the existing 4 MHz master;
chained PIT1 `LDVAL=3` produces exactly 1 MHz. PIT1 fans XBAR input 57 to
outputs 103/107 and independent ADC_ETC queues 0/4. Raw initial delays 0/75
become effective delays 1/76 at 150 MHz, so their difference is exactly
75 cycles or nominally 500 ns. All clock gates, stopped PIT state, XBAR
selectors, queue controls, chain words, error bits, and trigger flags matched
[[ADR-004-ADC-Trigger-DMA]].

The measured DWT values are conversion-completion IRQ timing. They corroborate
the programmed digital phase but are not analog sample-and-hold aperture
measurements.

## Stream rate and reconciliation

| Metric | Diagnostic | 10 s smoke | 60 s soak |
| --- | ---: | ---: | ---: |
| ADC frames | 5,015 | 9,936 | 59,330 |
| ADC pairs | 5,075,180 | 10,055,232 | 60,041,960 |
| Pair rate / converter | 992,506.468/s | 994,700.443/s | 1,000,069.415/s |
| Rate deviation | -0.7494% | -0.5300% | +0.0069% |
| Payload rate | 3,970,025.873 B/s | 3,978,801.770 B/s | 4,000,277.662 B/s |
| Framed rate | 4,017,101.279 B/s | 4,025,981.238 B/s | 4,047,711.784 B/s |
| ADC0 observed codes | 971-1,670 | 932-1,671 | 901-1,671 |
| ADC1 observed codes | 1,010-1,726 | 967-1,724 | 939-1,723 |
| Firmware frames/pairs = host | yes | yes | yes |

Every received ADC data frame was exactly 4,096 bytes, carried 1,012 pairs in
the fixed halfword order, used the hardware-source flag and selected Adler-32,
and matched its run ID, independent sequence, sample-derived timestamp, item
count, code range, and checksum. No synthetic, gap, or overrun flag was
accepted. The parser checksummed 5,119, 10,030, and 59,623 total data/control
frames and ended with zero buffered bytes.

## Errors, queues, command latency, and host memory

All final error fields were zero in every accepted job: ADC item drops, raw
pair loss, STOP discards, incomplete/overwritten conversions, raw-ring
overruns, incomplete buffers, ADC_ETC events/flags, eDMA faults, completion/
destination mismatches, schedule exhaustion, invariant/stale events, resource
conflicts, START/STOP errors, packer source/pipeline/chronology faults, parser
and transport errors, GPIO leakage, and host parser/stale-response errors.

| Metric | Diagnostic | 10 s smoke | 60 s soak | Bound |
| --- | ---: | ---: | ---: | ---: |
| Raw-ready high water | 1 / 4 | 2 / 4 | 2 / 4 | 4 |
| Packet-owned high water | 103 / 200 | 95 / 200 | 110 / 200 | 200 |
| STATUS samples | 50 | 40 | 240 | at least 50 / 40 / 240 |
| STATUS p99 | 41.633 ms | 26.172 ms | 56.088 ms | 100 ms |
| STATUS maximum | 41.633 ms | 26.172 ms | 58.851 ms | 250 ms |
| STOP latency | 11.966 ms | 11.804 ms | 23.822 ms | 500 ms |
| Parser high water | 69,572 bytes | 69,631 bytes | 69,631 bytes | 69,635 bytes |
| Peak RSS growth | 151,552 bytes | 172,032 bytes | 167,936 bytes | 33,554,432 bytes |

Final raw-ready, packet-ready, and packet-transmit depths were zero in all
jobs. Commands remained responsive under load, and the postflight service
health check again reported queue depth zero.

## Analog stimulus limitation

No registered machine-readable `thingdaq-adc-stimulus-v1` declaration was
available. A0 and A1 were therefore treated as unstimulated inputs. The rig
correctly graded converter identity, payload order, code range, digital
trigger arithmetic, conversion completion, sustained transport, and loss/
error behavior, but it did **not** grade DC accuracy, gain/offset, noise, ENOB,
input bandwidth, source-impedance settling, crosstalk, analog aperture, or
physical 500 ns skew. The varying in-range codes above are observations, not
an accuracy result. A later analog characterization must provide a declared
low-impedance fixture and separate aperture instrumentation.

## Retained evidence

Machine-readable logs, manifests, maps, hashes, and health records are retained
outside version control in
`.maestro/playbooks/Working/phase-07-adc-final-00001/`. Frames were validated
online and released; bulk ADC captures were not retained.

| Stage | Raw log | Log SHA-256 | Submitted program SHA-256 |
| --- | --- | --- | --- |
| Diagnostic | `diagnostics-optimized.log` | `beb7403e46a907c9ef1ff1f691905924db71fd6fe0c7cfa87b0a509dc754db7c` | `f1b7fe3a7a203ef71716e29972dc31324e638c45fc4605a4a4d5357b48dff89d` |
| 10-second smoke | `smoke-10s.log` | `6a8a9e23c91a096578b172eebf6a382c37b14b0d9770894848503f1ff5759be8` | `0b5c438214865e45de0516aa658f1f18d2e432ae30c6ba49cde1e5d199ea69ab` |
| 60-second soak | `soak-60s.log` | `31cad59d360784d6d682a2eb57829d340ce7e820e85df8544efa3a2afdd97ffd` | `bd5f2b1bc88f2d669eea4ec72658b229b5303b2b0bb071ce0308f7c6ea06259b` |

The tracked standalone rig source is SHA-256
`c879f357a8c2b86d302675ddcc8c4010363a7883961a61eee462862adbc6799c`;
the client wrapper is
`799268c6942a48206d8b408fa530cd6c89019130ce4900e83f0ba05c5619362e`.
