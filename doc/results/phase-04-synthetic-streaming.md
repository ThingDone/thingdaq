---
type: report
title: Phase 04 Synthetic Streaming Rig Acceptance
created: 2026-08-28
tags:
  - thingdaq
  - phase-04
  - firmware
  - synthetic-streaming
  - hardware-rig
  - verification
related:
  - '[[System-Overview]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[Phase-03-Control-Plane]]'
---

# Phase 04 synthetic streaming rig acceptance

## Result

The Phase 04 full-rate synthetic path passed a 10-second smoke followed by a
60-second soak on the physical Teensy 4.0 rig on 2026-08-28. The soak was not
submitted until the smoke had completed successfully and the service had
returned to a healthy, normal, empty-queue state. Both accepted jobs flashed
the same exported HEX, verified firmware 0.4.0, protocol 1, build and hardware
identity, and finished in `IDLE` with all 67 graded checks passing.

The timed window begins only after synchronization, identity verification,
CONFIGURE, and the successful START response. In both windows the independent
rig parser checked the checksum, run ID, per-source sequence, timestamp,
epoch/gap flags, item count, and every ADC/GPIO formula value in every data
frame. Each source remained within 1% of its advertised 4,000,000-byte/s
payload rate, combined payload stayed near 8,000,000 bytes/s, no firmware or
host loss/error counter changed, and final firmware counters exactly matched
the validated host totals. See [[Protocol-V1]] for the wire invariants and
[[System-Overview]] for the bounded data path.

| Acceptance requirement | Result |
| --- | --- |
| Live service preflight | PASS: healthy worker, Docker, and hub; normal coordinator; queue depth 0 |
| Sequential smoke then soak | PASS: accepted smoke completed at `10:54:28Z`; soak submission began at `10:54:41Z` after a fresh empty-queue health check |
| Firmware/build/hardware identity | PASS: firmware 0.4.0, protocol 1, `thingdaq-9fb124f80183ed61`, serial 20512460 in both jobs |
| ADC and GPIO payload rates | PASS: +0.1451% per source in the smoke and +0.0237% per source in the soak |
| Wire and synthetic correctness | PASS: every checksum, formula, sequence, timestamp, run ID, item count, and flag validated |
| Firmware and host loss | PASS: zero ADC/GPIO drops, gap/overrun flags, parser errors, transport errors, stale responses, or host queue drops |
| STATUS latency | PASS: worst p99 9.260 ms against 100 ms; worst maximum 9.260 ms against 250 ms |
| Parser and process memory | PASS: 69,631-byte parser high water against 69,635; worst RSS growth 585,728 bytes against 33,554,432 |
| Final reconciliation | PASS: final `IDLE`; firmware-emitted frames equal validated ADC/GPIO frame totals exactly |
| Program and test outcomes | PASS: `program_success=true`, exit code 0, and 67/67 checks in each accepted job |

## Live service preflight and postflight

The public preflight used only the unauthenticated `/health`, `/version`,
`/platforms`, and `/client/run_my_program.py` endpoints at
`http://192.168.150.14:5000`. The existing owner credential was read from its
mode-0600 local file into `FW_API_KEY` for each client process. It was never
printed, logged, placed on a command line, or copied into the repository.

| Endpoint | Evidence |
| --- | --- |
| `/health` | HTTP 200; `status=healthy`; worker alive; Docker and hub reachable; coordinator `normal`; queue depth 0 before each accepted submission |
| `/version` | `remote-firmware-testing` 1.0.0; API `v1`, matching client 1.0.0 |
| `/platforms` | Documented `teensy:avr:teensy40` target on hub port 15 with Teensy 4.0/i.MX RT1062 guidance |
| `/client/run_my_program.py` | 15,602 bytes; SHA-256 `23115388d9a62384cca074ac976c24986d77bd98538713901db3ec810e5c84ec`; byte-identical to the downloaded client used for both jobs |

The catalog reported `connected=false` while the powered hub port was idle.
Each job then powered port 15, found the board, soft-rebooted it into HalfKay,
programmed it, and opened the re-enumerated CDC device at `/dev/ttyACM0`.
Postflight at `2026-08-28T10:56:06Z` again returned HTTP 200, healthy/normal,
with a live worker, reachable Docker and hub, and queue depth 0.

## Accepted firmware candidate

The final buffer size is evidence-based. An excluded 60-second diagnostic on
the preceding 64-frame build observed a 39.8081 ms host receive pause, followed
by four dropped ADC frames and five dropped GPIO frames with zero parser and
transport errors. At the protocol's 8,094,861.660 framed bytes/s, one 64 KiB
host-read batch spans exactly 8.096 ms. The accepted 96-frame application pool
therefore holds six batches, or 48.576 ms, and the core-owned 8,192-byte ring
adds 1.012 ms. Five batches cover the measured pause and one complete batch
remains as bounded margin. The corresponding host-C++ regression stalls USB
with 80 buffers owned, confirms zero exhaustion/drop, then drains to zero.

| Build property | Accepted value |
| --- | --- |
| Build ID | `thingdaq-9fb124f80183ed61` |
| Firmware source fingerprint | `9fb124f80183ed6161dbcadc2758feaaf2a25a54b8e4678484a392086e5980b4` |
| Firmware-input Git revision | `e3f93de74c85e7441f2db20b559bd48f34e263b8` |
| Reproducible build timestamp | `2026-08-28T10:53:10Z` |
| Target | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`; Teensy core 1.62.0 |
| Tools | Arduino CLI 1.4.1; Arm GNU 15.2.1, 15.2.Rel1 build arm-15.86 |
| Flash | 29,552 bytes code; 5,064 bytes initialized data; 8,388 bytes headers; 1,988,612 bytes free for files |
| RAM1 | 407,552 bytes variables; 27,832 bytes code; 4,936 bytes padding; 83,968 bytes free for locals/stack |
| RAM2 | 12,416 bytes variables; 511,872 bytes free for heap |
| Packet storage | 96 × 4,096-byte aligned DTCM frames = 393,216 bytes; 48.576 ms at target framed rate |

The RAM1 registry reserves 401,824 bytes for project data, including the
393,216-byte packet storage and a 4,096-byte pipeline-state ceiling. The linked
image retains 83,968 bytes, or 16.016% of RAM1, for locals and stack. RAM2
remains available for the future DMA acquisition rings described in
[[Firmware-Resource-Map]] and [[Foundation-Reuse-Inventory]].

### Submitted artifacts

The build helper exported the option-qualified local directory. Its contents
were copied without alteration to the service client's required
`build/teensy.avr.teensy40/` staging path, and the staged manifest and HEX were
independently hash-matched before both accepted submissions.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Build manifest | 4,594 | `a9f674cbaf484994f5c4bb644655de4a0cff42ad7a6d45f099c07e2b2175aeb6` |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 700,956 | `3a57597bcd46b88dac80ad1a379861115b0e719167c569dfc3ab6268aa6bcb34` |
| `firmware.ino.hex` | 121,050 | `32305d681e38b173ca6c318d28036eb64fe64eabbea559cf7e57d3a1fbb8539d` |
| `firmware.ino.map` | 624,278 | `f0e2a82c01c181e13b10b2dd18dad1ebb83672c0a54b67fb211f17b212c7cea9` |
| 10-second pinned rig program | 58,908 | `ca1175f30ca94f1ea319499129df3dbe9f136e7c6077820fd9869f61ec0a5bc6` |
| 60-second pinned rig program | 58,908 | `d83645343695e485a983f1d92c29a44c4228031efc05d2c527818cadcaabcb04` |

The Teensy loader decoded 43,008 programmed image bytes and reported 2.1%
usage in both accepted jobs. The two rig files are exact copies of the tracked
independent program except for three bottom-of-file defaults pinning duration,
build ID, and hardware serial.

## Sequential accepted jobs

Service timestamps are host-local America/New_York time. Client UTC intervals
bound version handshake, packaging, submission, programming, capture, result
retrieval, and exit. The job records were fetched again after completion and
confirmed `program_success=true`, `completed=true`, and exit code 0.

| Stage | Job ID | Service timestamp (EDT) | Client UTC interval | Capture / checks | Outcome |
| --- | --- | --- | --- | --- | --- |
| 10-second smoke | `507161d9-9397-4365-a006-2da240bb6058` | `2026-08-28 06:54:07` | `10:54:07Z`–`10:54:28Z` | 10.005293 s / 67 | PASS |
| 60-second soak | `3129bb7f-ad33-4d97-9c26-cf552c2b5bb9` | `2026-08-28 06:54:42` | `10:54:41Z`–`10:55:54Z` | 60.001438 s / 67 | PASS |

No submissions overlapped. The soak started 13 seconds after smoke completion,
only after `/health` again reported an empty queue.

## Throughput, volume, and final counters

ADC payload consists of 1,012 four-byte pairs per frame; GPIO payload consists
of 4,048 one-byte samples per frame. Both therefore advertise exactly
4,000,000 payload bytes/s. The target combined framed rate, including the
48-byte header/trailer overhead of every 4,096-byte frame, is
8,094,861.660 bytes/s.

| Metric | 10-second smoke | 60-second soak | Requirement |
| --- | ---: | ---: | --- |
| ADC frames / pairs | 9,901 / 10,019,812 | 59,304 / 60,015,648 | Continuous and final-counter exact |
| GPIO frames / samples | 9,901 / 40,079,248 | 59,304 / 240,062,592 | Continuous and final-counter exact |
| ADC payload bytes | 40,079,248 | 240,062,592 | Exact from frames |
| GPIO payload bytes | 40,079,248 | 240,062,592 | Exact from frames |
| Combined payload bytes | 80,158,496 | 480,125,184 | Exact from frames |
| Combined framed bytes | 81,108,992 | 485,818,368 | Exact from frames |
| ADC payload rate | 4,005,804.558 B/s (+0.1451%) | 4,000,947.342 B/s (+0.0237%) | 4,000,000 B/s ±1% |
| GPIO payload rate | 4,005,804.558 B/s (+0.1451%) | 4,000,947.342 B/s (+0.0237%) | 4,000,000 B/s ±1% |
| Combined payload rate | 8,011,609.115 B/s (+0.1451%) | 8,001,894.684 B/s (+0.0237%) | 8,000,000 B/s ±1% |
| Combined framed rate | 8,106,608.433 B/s (+0.1451%) | 8,096,778.810 B/s (+0.0237%) | 8,094,861.660 B/s ±1% |
| Final emitted ADC / GPIO frames | 9,901 / 9,901 | 59,304 / 59,304 | Equal host totals; balance difference ≤1 |
| Final dropped ADC / GPIO items | 0 / 0 | 0 / 0 | 0 / 0 |
| Final firmware parser / transport errors | 0 / 0 | 0 / 0 | 0 / 0 |

The parser decoded and checksummed 19,850 frames in the smoke and 118,856 in
the soak. Those totals include the 19,802 and 118,608 data frames respectively,
plus bounded command responses. There were no bad checksums, formulas,
sequences, timestamps, flags, run IDs, frame shapes, or counter mismatches.

## Latency, queue, parser, and memory bounds

| Metric | 10-second smoke | 60-second soak | Bound |
| --- | ---: | ---: | ---: |
| INFO latency | 20.904 ms | 20.899 ms | 500 ms |
| CONFIGURE latency | 20.799 ms | 20.743 ms | 500 ms |
| START latency | 10.596 ms | 10.496 ms | 500 ms |
| STATUS samples | 40 | 240 | At least 40 / 240 |
| STATUS p99 | 9.260 ms | 8.541 ms | 100 ms |
| STATUS maximum | 9.260 ms | 8.708 ms | 250 ms |
| STOP latency | 20.728 ms | 20.730 ms | 500 ms |
| Final STATUS latency | 20.885 ms | 20.847 ms | 500 ms |
| Parser high water | 69,631 bytes | 69,631 bytes | 69,635 bytes |
| Maximum serial read | 65,536 bytes | 65,536 bytes | 65,536 bytes |
| Parser bytes retained at end | 0 | 0 | 0 |
| Host parser errors / stale responses | 0 / 0 | 0 / 0 | 0 / 0 |
| Peak RSS growth | 466,944 bytes | 585,728 bytes | 33,554,432 bytes |
| Peak process RSS | 16,617,472 bytes | 16,703,488 bytes | Finite and bounded |

The device-side queue capacities are fixed at 96 packet buffers, 96 indexes in
each per-source ready FIFO, and 96 indexes in the shared transmit FIFO; shared
buffer ownership limits aggregate occupancy to 96 frames. The protocol-v1
STATUS payload does not expose internal queue high-water values, so hardware
acceptance uses continuous sequence/gap checks plus exact final drop counters
as the externally observable exhaustion proof. The separate native regression
records an 80-buffer owned high water under the measured five-batch stall and
drains all ready/transmit depths back to zero without loss. On the host, the
self-contained rig processes each bounded serial read directly rather than
retaining a decoded queue; its parser ended empty in both jobs and stayed four
bytes below its explicit high-water ceiling.

## Diagnostic exclusions and retry policy

Failures were never relabeled as passes and the soak gate was restarted when
the firmware candidate changed. The retry policy required a terminal job,
healthy/normal service, and queue depth 0 before every subsequent submission.
Only the final smoke/soak pair above is accepted.

| Excluded job | Candidate | Diagnostic result and repair |
| --- | --- | --- |
| `9c64c033-3c95-45ca-abff-14f0a555dbbe` | 16-frame `thingdaq-5dcbdd7741f93361` | First live STATUS exposed one dropped GPIO frame; expanded the startup scheduling reserve and added a native stall regression. |
| `073c7860-dca0-4721-b25f-278c49c5966d` | 32-frame `thingdaq-ece399a4744dc360` | Rig false negative compared a STATUS snapshot with newer frames from the same 64 KiB read; validation now uses the pre-request receive floor. |
| `d6984e90-f28e-44e1-af0d-01ca8513d04b` | 32-frame `thingdaq-ece399a4744dc360` | Genuine GPIO gap flag at sequence 4,626 showed that one batch of scheduling margin was insufficient. |
| `cda77c5d-ea69-446f-874c-f829c054c8fc` | 64-frame `thingdaq-f0c60e4b4ae2deb7` | Genuine ADC gap flag at sequence 4,622; added post-failure timing and final STATUS diagnostics. |
| `0a1c4593-9ccd-46a2-9e5b-5249b51a0653` | 64-frame `thingdaq-f0c60e4b4ae2deb7` | Ten-second diagnostic passed, but it is not paired with the accepted candidate because the following soak failed. |
| `2e691c60-99d8-4ada-a4c9-6289a4559910` | 64-frame `thingdaq-f0c60e4b4ae2deb7` | Soak measured a 39.8081 ms receive pause and exact losses of four ADC plus five GPIO frames, with parser/transport errors zero; expanded to the final six-batch reserve. |

The repair sequence is preserved in commits `0eb59f0`, `eb7b504`, `7b6ffbf`,
`041fc9b`, and `e3f93de`. The final local gate reports all 20 generated
protocol outputs current, 48 Python sources formatted and lint-clean, MyPy
clean across the same 48 sources, and 164 tests with 9,887 native subtests
passing. The exact all-warnings target compile also passes; its only host note
is the absent local udev rule, which is irrelevant to the service-owned upload
and serial path.

## Scope

This result accepts the complete synthetic protocol/framing/queue/CDC/host
validation path at the Phase 04 rates. It does not claim that the later
physical ADC, GPIO trigger, ADC_ETC, XBAR, or eDMA acquisition implementation
exists or has been validated.
