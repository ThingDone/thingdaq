---
type: report
title: Phase 09 Loss and Recovery Acceptance
created: 2026-08-29
tags:
  - thingdaq
  - phase-09
  - loss-accounting
  - backpressure
  - recovery
  - hardware-validation
related:
  - '[[Acquisition-Pipeline]]'
  - '[[Protocol-V1]]'
  - '[[Phase-08-Combined-Acquisition]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
---

# Phase 09 loss and recovery acceptance

## Outcome

The Phase 09 hardware campaign passed on 2026-08-29. Exact firmware pressure
loss was induced by 0.25 s, 1 s, and 3 s host read stalls and reconciled for
both sources at frame, item, payload-byte, sequence, timestamp, successor-flag,
and packet-eviction levels. Valid combined framing resumed after every stall,
all command deadlines held, unexpected target and host error snapshots were
empty, and every run ended in IDLE.

A separate job rejected malformed traffic, completed 100 exact
CONFIGURE/START/STATUS/STOP cycles, and recovered the same RUNNING session
after a live CDC close/reopen in 267.616 ms. The final independent 60-second
normal regression then delivered 59,546 complete ADC frames and 59,546
complete GPIO frames with zero complete-frame or payload loss, exact common
epoch accounting, zero unaccounted acquisition/transport/host faults, and
final IDLE.

Six accepted service jobs each independently flashed, soft-reset, found the
HalfKay bootloader, programmed, booted, and re-enumerated the Teensy without a
manual USB unplug. All used the exact same HEX image. No task-associated
images were present; zero images were analyzed.

| Acceptance requirement | Result |
| --- | --- |
| Several bounded host stalls | PASS at 0.25 s, 1 s, and 3 s |
| Exact expected loss | PASS for frame, item, byte, sequence, timestamp, flag, and eviction evidence |
| Resumed acquisition and valid framing | PASS; live ADC/GPIO coverage advanced beyond post-stall STATUS snapshots |
| Partial-frame integrity | PASS; no checksum/parser/stale-response corruption and one correctly flagged successor per source |
| Control/lifecycle recovery | PASS; 903 checks across malformed traffic, 100 cycles, and CDC close/reopen |
| Flash/reset/re-enumeration | PASS in six independent accepted jobs, without an unplug |
| Normal 60-second regression | PASS; 352 checks, zero complete-frame/payload loss, exact STOP-tail accounting |
| Final state | PASS; IDLE with stream mask zero after every acceptance program |

## Gate-discovered BOOT diagnostic repair

The campaign was allowed to fail before acceptance. The first stall submission
could not CONFIGURE hardware ADC because the BOOT ADC-trigger snapshot reported
`COMPLETION_TIMING_OUT_OF_TOLERANCE`. Focused jobs proved that GPIO-only and
synthetic combined profiles remained healthy, all raw/packet ownership depths
were zero, and the ADC registers, queues, clocks, calibration, and resource
conflict counters were valid. The failing DWT delta was 60 cycles although the
programmed phase was 300 cycles.

Map and disassembly comparison showed that both completion IRQs could already
be pending before NVIC serviced either one. Their timestamps then measured
roughly 60 cycles of tail-chaining and handler work rather than the 75-IPG-cycle
hardware phase. Minor code-placement changes could therefore change BOOT
readiness even when the ADC schedule was identical.

The repaired target leaves the ADC_ETC completion/error IRQs disabled during
the BOOT cross-check, briefly masks global interrupts, and records the first
Done0 and Done1 status transitions in a bounded ITCM loop. Both the target loop
and portable scheduler retain the 2,000 us and 2,000,000-poll ceilings. Trigger
errors are still captured, the original interrupt mask is restored, and the
production ADC_ETC error/DMA ownership path is unchanged. The target-register
test now proves exact 300-cycle status capture, no completion-vector install,
and restoration of both initially enabled and initially masked interrupt state.

The repaired physical diagnostic reported configuration flags 255, trigger
errors zero, completion counts `[1, 1]`, and a 292-cycle delta against the
accepted `300 ± 120` bound. This is digital conversion-completion status
evidence only; it does not measure analog aperture.

| Exploratory job | UTC interval | Evidence | Disposition |
| --- | --- | --- | --- |
| `4494cf36-2b68-47a1-ab4e-68fca12d78ee` | `12:07:34Z`-`12:07:45Z` | Initial 0.25 s program reached BOOT but CONFIGURE returned BUSY; cleanup ended IDLE | Rejected |
| `bb52938e-8883-4720-be6f-6adfeb554518` | `12:10:09Z`-`12:10:21Z` | Confirmed no stale queue/resource ownership | Diagnostic only |
| `a1f8aee4-4db0-4497-aa83-3a2705ef3467` | `12:11:47Z`-`12:11:59Z` | Hardware ADC/combined failed while hardware GPIO and synthetic combined configured | Diagnostic only |
| `a795d5e7-a224-4c64-9e5a-d2ca4111d791` | `12:12:55Z`-`12:13:06Z` | Isolated valid registers and `[1, 1]` counts but a 60-cycle completion delta | Diagnostic only |

These jobs are retained as failure and root-cause evidence, not counted as
acceptance results.

## Service preflight, artifact, and reset scope

The service and client were both version 1.0.0 on API v1. Before each accepted
submission, `/health` reported coordinator mode `normal`, reachable Docker and
USB hub, a live worker, and queue depth zero. The catalog identified the Teensy
4.0 target on hub port 15. Each loader transcript selected the staged HEX,
reported a soft reboot, found HalfKay, programmed 124,928 decoded bytes (6.1%
usage), booted, and exposed `/dev/ttyACM0` to the rig program.

The hardware jobs ran the image whose HEX SHA-256 is
`6bb2c355ed59e3dc59109de9fc954daeb8440329996a3b5efbaf65f15781e769`.
After committing the repair, a clean rebuild with the pinned source timestamp
reproduced the accepted HEX, ELF, and map byte for byte and attached clean
commit identity `041a0f5cb66d23205be1d799dab801bb0b2bc75e` to the retained manifest.

| Property | Value |
| --- | --- |
| Build ID | `thingdaq-ea010335c9b63bb7` |
| Source ID | `ea010335c9b63bb7008e7c18fc911ac87df69ebdeacfdde27f5bb54a12f4fa85` |
| Clean source commit | `041a0f5cb66d23205be1d799dab801bb0b2bc75e` |
| Reproducible timestamp | `2026-08-29T12:02:24Z` |
| Hardware | Teensy 4.0 / i.MX RT1062, serial 20512460 |
| Protocol / firmware | protocol 1 / firmware 0.7.0 |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Toolchain | Teensy core 1.62.0; Arduino CLI 1.4.1; Arm GNU 15.2.1; 600 MHz; USB Serial; `-O2`; warnings `all` |
| Flash | 92,812 code + 23,496 data + 8,616 headers bytes |
| RAM1 | 456,960 variables + 32,744 code + 24 padding bytes; 34,560 bytes free for locals/stack |
| RAM2 | 503,488 variables; 20,800 bytes free for heap |

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 1,791,648 | `9337ac3ddbeb0461e48bc8050422c446bb0f4f216058b0d2e32f148370e1c292` |
| `firmware.ino.hex` | 351,467 | `6bb2c355ed59e3dc59109de9fc954daeb8440329996a3b5efbaf65f15781e769` |
| `firmware.ino.map` | 828,851 | `92ea75bcfcbedcb4c331f40670b43760e2c2fbe2ff89050e027b56c116b0e1a8` |
| `build-manifest.json` | 12,788 | `ac2a161c2a75660b15295bfae6b2ce52f97d7187c5dc2514da883f4ed6925149` |

## Sequential accepted jobs

No accepted jobs overlapped. Each row is an independent service submission
and therefore an independent flash/reset/re-enumeration exercise.

| Order | Program | Job ID | Client UTC interval | Timed action / checks | Result |
| ---: | --- | --- | --- | ---: | --- |
| 1 | Repaired combined diagnostic | `1da6f364-4b03-4ba4-90a5-73c0dd0690f0` | `12:26:33Z`-`12:26:46Z` | 1.001585 s / 352 | PASS |
| 2 | Host-stall recovery | `c386d6b1-d81f-4156-9c81-0e2a4e77e988` | `12:27:16Z`-`12:27:29Z` | 0.250065 s / 61 | PASS |
| 3 | Host-stall recovery | `154f1dbc-6518-4bc1-a77e-cf3934445766` | `12:27:49Z`-`12:28:02Z` | 1.000270 s / 61 | PASS |
| 4 | Host-stall recovery | `29fefa2f-7e71-492c-9e13-ec0b8a2ca39d` | `12:28:14Z`-`12:28:29Z` | 3.000271 s / 61 | PASS |
| 5 | Control/lifecycle recovery | `81cf9197-8438-4ce6-af0e-f85672a86bd9` | `12:28:47Z`-`12:29:06Z` | 100 cycles / 903 | PASS |
| 6 | Normal combined regression | `81a184e1-41d5-4b19-b3ca-bf4ede46b674` | `12:29:22Z`-`12:30:35Z` | 60.000637 s / 352 | PASS |

## Stall loss and gap reconciliation

Both sources cover 8,096 ticks per complete frame. An ADC frame contains 1,012
four-byte pairs; a GPIO frame contains 4,048 one-byte samples. For each source,
the rig independently required:

```text
missing_frames = successor_sequence - predecessor_sequence - 1
next_ticks - previous_ticks = (missing_frames + 1) * 8,096
ADC dropped_items = ADC dropped_frames * 1,012
ADC dropped_bytes = ADC dropped_items * 4
GPIO dropped_items = GPIO dropped_frames * 4,048
GPIO dropped_bytes = GPIO dropped_items
packet_pressure_evictions = ADC dropped_frames + GPIO dropped_frames
```

All modular sequence/timestamp arithmetic also handled wrap. Each gap had
exactly one chronological successor carrying both GAP_BEFORE and
OVERRUN_BEFORE. The firmware frame/item/byte counters, inferred sequence and
timestamp gaps, source eviction counters, and global pressure-eviction counter
agreed exactly:

| Requested / actual stall | ADC frames / items / bytes | GPIO frames / items / bytes | Pressure evictions | Resumed STATUS | Final STOP |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.25 s / 0.250065 s | 146 / 147,752 / 591,008 | 146 / 591,008 / 591,008 | 292 | 1.560 ms | 1.147 ms |
| 1 s / 1.000270 s | 889 / 899,668 / 3,598,672 | 888 / 3,594,624 / 3,594,624 | 1,777 | 3.832 ms | 21.297 ms |
| 3 s / 3.000271 s | 2,865 / 2,899,380 / 11,597,520 | 2,864 / 11,593,472 / 11,593,472 | 5,729 | 3.943 ms | 20.934 ms |

The apparent one-frame ADC/GPIO difference in the longer stalls is legal
source-fair oldest-complete eviction; each source still reconciles exactly.
For every stall, `packet_capacity_drops_without_evictable_frame` was zero and
the frame conservation equations in [[Acquisition-Pipeline]] held:

```text
generated = transmitted + pressure_dropped + filling + ready + transmitting
framed = transmitted + ready + transmitting + dropped_after_framing
emitted = transmitted + transmitting + dropped_after_promotion
```

After reads resumed, both trackers advanced beyond a fresh live STATUS target,
the loss counters stabilized, acquisition remained RUNNING with the same run
and statistics generation, and the parser continued accepting checksummed
frames. Unexpected firmware/hardware counter dictionaries were empty; host
parser errors and stale responses were zero. Initial STOP, START, resumed
STATUS, and final STOP all stayed below their 1-second command deadlines and
the 10-second recovery deadline.

## Malformed-command, lifecycle, and CDC recovery

The control job rejected bad checksum, oversized, unknown-kind,
unknown-version, reserved-field, truncated-plus-garbage, duplicate-request-ID,
and illegal-state cases without partially applying state. Its expected
classification snapshot was two bad checksums and one each of bad length,
payload, request ID, kind, version, and state transition; eight commands were
rejected. Valid identity/state probes succeeded after every negative case and
unexpected inbound corruption remained zero.

All 100 lifecycle cycles executed four exact transitions, with monotonically
advancing run IDs through 101 and IDLE after every STOP. Across the 400 normal
transition events, maximum latency was 22.286 ms. The six malformed-command
responses took at most 21.008 ms, and the four explicitly illegal transitions
took at most 20.607 ms, all against a 1-second deadline.

The rig then started run 102, closed CDC while firmware remained RUNNING,
paused 250 ms, reopened by the same hardware identity, and re-synchronized in
267.616 ms against a 4-second deadline. INFO and STATUS retained build, serial,
state, and run identity; the first post-reopen STATUS took 1.864 ms. The
expected unread interval reconciled to 156 ADC frames (157,872 pairs and
631,488 bytes) and 156 GPIO frames (631,488 samples/bytes), with no unexpected
hardware errors or old/new-session inbound corruption. STOP completed in
1.420 ms, the bounded source-first tail accounted for 782 ADC pairs and 3,128
GPIO samples, and final STATUS reported IDLE, stream mask zero, and run 102.

## Final 60-second normal regression

The final job ran for 60.000637 s and validated every received frame's Adler-32
checksum, source, run, sequence, timestamp, flags, item count, payload layout,
and safe no-fixture value range.

| Metric | Result |
| --- | ---: |
| Complete ADC / GPIO frames | 59,546 / 59,546 |
| ADC pairs delivered | 60,260,552 |
| GPIO samples delivered | 241,042,208 |
| ADC0 / ADC1 delivered results | 60,260,552 / 60,260,552 |
| ADC pair rate | 999,997.183 pairs/s |
| GPIO sample/payload rate | 3,999,988.733 samples/s / B/s |
| Combined payload rate | 7,999,977.465 B/s |
| Equal final ADC / GPIO timestamp | 482,084,416 / 482,084,416 ticks |
| Maximum wire skew | 1 frame |
| Checksummed host frames | 119,224 |

Complete-frame and payload-byte drops were zero for both sources. Packet pool
exhaustions, packet encoding/queue failures, ADC/GPIO raw-ring overruns,
ADC_ETC/eDMA errors, overwritten conversions, destination/stale/schedule/cache
ownership invariants, source/pipeline/chronology errors, command/parser/state,
transport/USB I/O, host parser, stale-response, and host in-run discarded-frame
counters were all zero. The packet-owned high water was 99 of 200.

STOP separately and exactly reconciled the active partial tail:

```text
60,260,916 ADC pairs captured - 60,260,552 delivered = 364 discarded
241,043,665 GPIO samples captured - 241,042,208 delivered = 1,457 discarded
```

The one incomplete ADC buffer, one incomplete conversion, and one completion
mismatch were bounded terminal STOP observations and accompanied those exact
tail counters; they did not discard a complete frame or payload byte. The
602,932 USB TX stall observations were cooperative polls of a temporarily full
core ring, with zero partial writes, capacity drops, or USB errors.

STATUS p99 was 2.138 ms, STATUS maximum was 2.726 ms, all-command maximum was
21.232 ms, and maximum receive gap was 53.485 ms. Host peak RSS growth was
372,736 bytes. The final firmware counter snapshot reported IDLE and zero
stream mask.

## Local verification and retained evidence

The repaired source passed the target-register ADC diagnostic tests and the
complete local suite: 319 tests passed, one optional test skipped, and 13,239
subtests passed. The all-warnings Teensy target build passed schema-10
manifest, ELF/map allocation, 32 KiB ITCM-bank, RAM1 stack-headroom, and RAM2
heap gates. `git diff --check` also passed.

The complete service health responses, downloaded client, standalone rig
variants, clean and acceptance artifact hashes, manifest/ELF/HEX/map, and full
stdout for every exploratory and accepted job are retained under
`.maestro/playbooks/Working/phase-09-loss-recovery-00001/`. The maintained
programs remain `firmware/tests/rig_host_stall_recovery.py`,
`firmware/tests/rig_control_recovery.py`, and
`firmware/tests/rig_combined_capture.py`. Counter units and the complete-frame
drop state machine are defined in [[Acquisition-Pipeline]]; wire fields,
states, flags, and error semantics are defined in [[Protocol-V1]].

## Fixture limitations

No external analog fixture declaration or digital stimulus was supplied.
These jobs therefore grade digital scheduling metadata, full-rate capture,
framing, loss/recovery behavior, checksums, and safe code ranges, but do not
grade analog accuracy, noise, bandwidth, sample-and-hold aperture, or external
GPIO transition timing.
