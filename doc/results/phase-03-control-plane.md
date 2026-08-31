---
type: report
title: Phase 03 Control Plane Rig Acceptance
created: 2026-08-28
tags:
  - thingdaq
  - phase-03
  - firmware
  - control-plane
  - hardware-rig
  - verification
related:
  - '[[System-Overview]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[Phase-03-Firmware-Local-Gate]]'
---

# Phase 03 control plane rig acceptance

## Result

The Phase 03 control-plane firmware passed two consecutive physical Teensy 4.0
rig jobs on 2026-08-28. Both jobs flashed the same exported HEX, returned the
same hardware, firmware, protocol, and source-derived build identity, passed
all 107 graded checks, kept every command within its one-second deadline, and
finished in `IDLE` with zero parser and transport errors after statistics
reset. No job retry was needed, and the two submissions never overlapped.

The accepted candidate is build `tdaq-39300273210c1c89`, generated from
firmware source fingerprint
`39300273210c1c89964c5c5cc56ae76ca7b6e800471d94acaa24f6b30de0ff5a`
at Git revision `a5bd30c243a012680a93a77d22770db56cb00b58`. This is the
same candidate frozen by [[Phase-03-Firmware-Local-Gate]]. See
[[System-Overview]] for its control-only boundary and [[Protocol-V1]] for the
wire contract exercised here.

| Acceptance requirement | Result |
| --- | --- |
| Live service preflight | PASS: healthy worker, Docker, hub, normal coordinator, empty queue |
| Current service-owned client | PASS: downloaded client/service version 1.0.0, exact source SHA-256 recorded below |
| Sequential execution | PASS: job 2 was submitted only after job 1 completed and health returned to an empty queue |
| Consecutive physical runs | PASS: 2 of 2, with no excluded or retried job between them |
| Firmware/protocol/build identity | PASS: ThingDAQ 0.3.0, protocol 1, `tdaq-39300273210c1c89` in both runs |
| Hardware identity | PASS: board ID 1, MCU ID 1, hardware serial 20512460 in both runs |
| Command latency | PASS: all exchanges had a 1.000 s deadline; worst reported latency was 0.051104 s |
| State and error cleanup | PASS: final `IDLE`, parser errors 0, transport errors 0, stale/interleaved responses 0 |
| Program and test outcomes | PASS: `program_success=true`, test exit code 0 for both jobs |

## Live service preflight

The public preflight completed at `2026-08-28T07:45:42Z` against
`http://192.168.150.14:5000`. It used only the unauthenticated `/health`,
`/version`, `/platforms`, and `/client/run_my_program.py` endpoints before any
hardware request.

| Endpoint | Evidence |
| --- | --- |
| `/health` | HTTP 200; `status=healthy`; worker alive; Docker and hub reachable; coordinator `normal`; queue depth 0 |
| `/version` | Service `remote-firmware-testing` 1.0.0; API `v1` |
| `/platforms` | Documented `teensy:avr:teensy40` target on hub port 15 with Teensy 4.0/i.MX RT1062 guidance |
| `/client/run_my_program.py` | 15,602 bytes; SHA-256 `23115388d9a62384cca074ac976c24986d77bd98538713901db3ec810e5c84ec` |

The catalog reported `connected=false` while the hub was idle and all target
ports were unpowered. That did not claim the target was absent: each submitted
job powered port 15, found the Teensy, soft-rebooted it into HalfKay, flashed
it, and opened its re-enumerated CDC device at `/dev/ttyACM0`.

The downloaded client was byte-identical to the service checkout. A temporary,
gitignored wrapper left those bytes unchanged and only surfaced the `test_id`
already returned by `/start`; the downloaded client itself performed the
version handshake, packaging, submission, polling, and results retrieval. The
existing owner API key was resolved from its mode-0600 reference file, placed
in `FW_API_KEY` for each client process, and never printed, logged, passed as a
command argument, or copied into the repository.

## Submitted artifact and resource identity

The build helper exports the option-qualified local directory for
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`. For the service's exact
base target `teensy:avr:teensy40`, its contents were copied without alteration
into a temporary `build/teensy.avr.teensy40/` staging tree. The current client
created a 410,171-byte ZIP containing the manifest, EEP, ELF, HEX, listing,
map, and symbol table. Independent ZIP inspection recovered the exact tracked
98,010-byte HEX and its expected SHA-256 before submission.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Build manifest | 4,337 | `b3bcb97a83d571ba6c3b0283ef46cec48d6c9814454500a79c4be69f1590bfdf` |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `firmware.ino.elf` | 542,412 | `301d40ea4f2f549e9da2226c2cc16287dba0f10a83bd28d0f143984ac250effd` |
| `firmware.ino.hex` | 98,010 | `7cd252bb37badf9e82de5c625b0e2caa8eadfd731a4c99003dec6509243a01b4` |
| `firmware.ino.map` | 586,789 | `1d72c625a2010628c20aa11ce5c860f2706b35207fdf52501c37f89d7a4fcbe4` |
| `rig_control_smoke.py` | 31,496 | `59b8b08de9765fabc62967ba0be6a6813858e3f5d866fc9f7e8d4e1661060159` |

| Build property | Accepted value |
| --- | --- |
| Teensy core | `teensy:avr` 1.62.0 |
| Compiler | Arm GNU 15.2.1, 15.2.Rel1 build arm-15.86 |
| CPU / USB / optimization | 600 MHz / USB Serial / `-O2` standard libc |
| Flash | 22,368 bytes code; 4,040 bytes initialized data; 8,404 bytes headers; 1,996,804 bytes free for files |
| RAM1 | 10,080 bytes variables; 20,648 bytes code; 12,120 bytes padding; 481,440 bytes free for locals |
| RAM2 | 12,416 bytes variables; 511,872 bytes free for heap |
| Fixed runtime ownership | 5,232-byte `firmware_runtime`; 12,416-byte core-owned USB DMA region; no acquisition buffers |

The rig's Teensy loader decoded 34,816 programmed image bytes and reported
1.7% usage in both jobs, consistent with the local linker and HEX inspection.
The capability response also stayed truthful for this milestone: no data
streams, hardware source plus reset-statistics and ping capabilities, Adler-32,
and the future timing/rate metadata documented by [[Firmware-Resource-Map]].

## Sequential rig jobs

The service records timestamps in host-local time without an offset. The table
labels those values as America/New_York and also records the client-observed
UTC interval around submission, polling, and results retrieval.

| Pass | Job ID | Service timestamp (America/New_York) | Client UTC interval | Program / test | Graded checks | Worst reported command latency |
| ---: | --- | --- | --- | --- | ---: | --- |
| 1 | `ee49d4e1-ace8-44f9-9355-a5d516190212` | `2026-08-28 03:47:37` | `07:47:36Z`–`07:47:48Z` | PASS / exit 0 | 107 PASS, 0 FAIL | START, 0.051009 s |
| 2 | `5f9e9be8-f72f-43a5-913a-c2bfecf1e436` | `2026-08-28 03:48:05` | `07:48:05Z`–`07:48:16Z` | PASS / exit 0 | 107 PASS, 0 FAIL | STOP, 0.051104 s |

The service was queried again between passes. It had returned to `healthy`,
coordinator `normal`, and queue depth 0 before pass 2 was submitted. The final
postflight at `2026-08-28T07:48:40Z` reported the same healthy, empty state.

### Stdout evidence summary

Both independent flash/reset runs produced the same acceptance sequence:

- the loader found HalfKay, programmed the image, and booted without a physical
  Program-button action;
- startup drain observed zero discarded bytes and zero stale frames, then INFO
  synchronization succeeded with a throwaway response on attempt 1 and stable
  matching identity on attempt 2;
- INFO reported protocol 1, firmware 0.3.0, build
  `tdaq-39300273210c1c89`, hardware serial 20512460, board/MCU IDs 1/1, and
  the exact control-only capability and rate metadata;
- PING echoed its 64-bit nonce, unsupported ADC configuration returned typed
  error 8 without leaving `IDLE`, and the zero-stream configuration moved
  through `CONFIGURED` and `RUNNING` with run ID 1;
- the deliberately checksum-corrupt INFO request produced silence and exactly
  one parser-error increment, proving bounded rejection and recovery; no
  transport error occurred;
- STOP returned to `IDLE`, a second STOP was idempotent, RESET_STATS advanced
  the generation to 3, and final STATUS reported parser errors 0, transport
  errors 0, all stream/drop counters 0, and no late/interleaved response; and
- the final line in each result was `PASS: Phase 03 identity, control
  lifecycle, recovery, and counters verified`.

Every exchange used a hard one-second command deadline even when its latency
was not printed as a separate graded line. The 11 explicitly reported latency
checks in each job ranged near 50–51 ms; the maximum across both runs was
0.051104 s, leaving more than 94% of the deadline unused.

## Retry policy

No retry was used in this acceptance sequence. A future rerun follows these
rules:

1. Require a fresh HTTP-200 health response with a live worker, reachable
   Docker and hub, non-fault coordinator, and an empty queue; require a
   compatible client/service major version and the documented Teensy target.
2. Give the client process a 1,200-second outer bound while retaining the
   rig script's four 0.75-second synchronization attempts, one-second command
   deadlines, 0.5-second serial-write timeout, and best-effort STOP cleanup.
3. Treat a failed, timed-out, identity-mismatched, or incomplete job as an
   excluded result that breaks the consecutive-pass sequence. Never submit a
   replacement while the original job could still be queued or running.
4. After the outstanding job is terminal, wait for healthy `normal` service
   state and queue depth 0 before one fresh sequential attempt. Firmware or
   protocol identity drift, a reproducible control failure, or any unexplained
   parser/transport error requires diagnosis and a new frozen candidate rather
   than blind resubmission.

## Post-run evidence checks

After writing this report, protocol drift check mode reported all 20 generated
outputs current. The complete local Python and host-C++ suite passed 140 tests
and 9,831 subtests. A separate evidence check reparsed both raw client logs and
asserted their job IDs, 107-to-0 PASS/FAIL counts, identities, latency maxima,
final state/error counters, manifest build ID, and HEX hash against this
report. The repository diff and Markdown front-matter checks also passed.

## Scope

This evidence accepts the physical Phase 03 USB identity and control plane. It
does not claim ADC acquisition, GPIO acquisition, streaming throughput,
externally stimulated signal correctness, or long-duration host behavior;
those remain later phases. Within the intended control-only scope, the two
consecutive flash/reset jobs satisfy the hardware acceptance gate.
