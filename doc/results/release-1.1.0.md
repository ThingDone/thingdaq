---
type: result
title: ThingDAQ 1.1.0 Release Qualification
created: 2026-09-05
tags:
  - thingdaq
  - release
  - validation
related:
  - '[[Protocol-V2]]'
  - '[[Evidence-Index]]'
  - '[[Hardware-Safety]]'
---

# ThingDAQ 1.1.0 release qualification

Firmware/API **1.1.0 use wire protocol v2, not v3**. Release firmware fixes
the core at 450 MHz and each ADC and GPIO input at 1 MS/s. Eight GPIO inputs
are the default; sixteen are selectable. Profiles other than ID 4, v1
requests, output modes, and the 4 MHz GPIO diagnostic are rejected.

## Frozen artifact

| Item | Value |
| --- | --- |
| Firmware source commit | `e3e8417598de7494db3a93d7277ef8f0ec31bc8f` |
| Build ID | `thingdaq-636aebbecbf70691` |
| Build timestamp | `2026-09-05T05:10:13Z` |
| HEX size | 446,511 bytes |
| HEX SHA-256 | `23b0f2ef8023c52021b22b8c6642f801866dfe8b1aadc48affc6b1ac66c2157a` |
| Target | `teensy:avr:teensy40:usb=serial,speed=450,opt=o2std` |
| Toolchain | Arduino CLI 1.4.1, Teensy core 1.62.0, Arm GCC 15.2.1 |
| RAM1 | 456,992 variable bytes; 32,552 code bytes; 34,528 bytes for locals |
| RAM2 | 520,192 variable bytes; 4,096 bytes for heap |

Two clean builds produced byte-identical HEX files. The manifest records clean
firmware inputs, source identity, all linked-memory ownership checks and
artifact hashes. Later report-only commits do not change those inputs.

## Physical qualification

The final interlocked HEX passed the **600-second combined ADC + 16-GPIO soak**, job
`1fb826ca-90ec-440c-a747-be0c24a50fd3`, with **131 checks passed** and no
failed checks. The validator requires clean ADC/GPIO DMA, raw-ring and packet
loss counters, valid frame sequences/checksums, paired-bank conservation,
responsive control commands and a clean STOP.

The same frozen HEX passed four 20-second combined-input cells in the sequence
8 → 16 → 8 → 16 GPIO inputs without reflashing between cells, job
`5717e52e-47dc-4b07-b6e2-7877ba295451`. Every cell passed, including run-ID
continuity, STOP/reconfiguration, temperatures and loss checks.

Final public-SDK job `5ccf656b-ddb6-46dc-a01e-57a835f44e0f` passed ADC-only,
8-input GPIO-only, 8-input combined, and 16-input GPIO-only cells for five
seconds each. It also verified the 450 MHz / 1 MHz clock diagnostic and raw
rejection of unsupported rates and the disabled capture diagnostic. Its
16-input combined cell **failed**, with one checksum rejection (zero header
or payload rejections), 2,120 discarded bytes and one resynchronization.
Firmware ADC/GPIO raw-ring overruns and packet-pressure evictions were zero
at that failure snapshot. This does not establish whether corruption occurred
in firmware, transport or the host path; CPU throttling is not proven to be
the cause. Therefore the release is firmware-qualified by the independent
validator, **not fully SDK end-to-end qualified on this host**.

| Measurement | Result |
| --- | ---: |
| Timed capture | 600.009 s |
| ADC pairs/s (each ADC samples at this rate) | 1,000,001.612 |
| GPIO samples/s per input | 1,000,002.455 |
| Die temperature before / after | 39.737 / 54.474 °C |
| Peak sampled die temperature | 55.088 °C |
| Valid temperature observations | 61 |
| Packet transmit queue high-water mark | 150 of 200 frames |

Transient sensor NOT_READY replies were retried with bounded retries while
continuing to drain data. They were not interpreted as zero-temperature values.
Reported raw ADC/GPIO frame-count skew can reach three because one GPIO frame
spans four ADC frames; this is not missing data or paired-bank generation skew.

The board is Teensy 4.0 serial `20428100`. All physical tests use real capture
and Adler-32 data checksums, not synthetic streams. Input pins have no declared
external stimulus. Thus streaming, rates, DMA pairing, loss accounting and
temperature are tested; analog accuracy, bandwidth and external GPIO timing
are **not** established.

## Failure separation and changes

The first candidate (`thingdaq-3d8b291dbec0199e`, HEX `8d1cd5c777c965bf03878d80d212947fdec5461be1375c8186b05fa8d653db9d`)
passed a 600-second cold-start combined 16-input run, job
`76e26db1-a254-4ab4-bc97-a64ff64b78a3`. A subsequent 8-to-16-input transition,
job `a56b6176-2d0f-4426-bdb1-cf4b1e08e9c1`,
reported one ADC raw-ring overrun (506 pairs), while packet pressure evictions
and GPIO loss stayed zero. Four immediate repeated transitions passed, so the
failure was intermittent, not an unconditional mode-switch rejection.

The six-generation ADC DMA look-ahead reserved six of eight buffers, leaving
only two for foreground processing. At 506 us per ADC frame this made buffer
availability sensitive to foreground scheduling latency. Release firmware now
uses four active look-ahead generations, retaining four processing buffers;
allocated storage and descriptor slots are unchanged. The new portable
regression models three paired completions during delayed processing and
demonstrates that the former reservation exhausts available buffers whereas
the release reservation does not. This addresses the demonstrated headroom
deficit; the precise interrupt/foreground timing of the original hardware
event was not instrumented. No loss counter or acceptance limit was relaxed.
Four short transitions passed on the revised source in job
`9119297c-f365-4ba9-ba86-d38d5ee79152` before the final reproducibility freeze.

The Python SDK has a separate host-throughput limit. On the first candidate,
job `7907730d-90c7-4e5a-a2b8-8fe07f75ba9f` passed ADC-only, GPIO-only with 8
and 16 inputs, and combined 8-input capture for five seconds each. Combined
16-input capture failed with a firmware-origin stream gap after about 1.35 s.
ADC/GPIO raw-ring overruns were both zero, but firmware USB packet pressure
evicted 83 frames. Host block-queue drops and protocol errors were zero.
The live cgroup limit was `cpu.max = 50000 100000` (half a CPU core), and CPU
throttling increased. This is consistent with insufficient SDK USB-drain
capacity under that quota, not the raw ADC-buffer failure above. Lossless SDK
operation in this mode on a faster host remains unverified.

Interlock-candidate SDK job `43bd53fb-5055-4c54-8d3d-51734840269c` confirmed
that the legacy diagnostic is rejected before capture and again passed the
first four mode cells. The combined 16-input cell instead reported two parser
rejections after 0.957 s, with no raw-ring loss or packet evictions at the
failure snapshot. That error's cause is unconfirmed; the CPU quota alone does
not establish why these frames were rejected. This is an additional SDK-path
qualification failure, not a passing capture.

SDK fixes made during release preparation include correct v1-to-v2 discovery,
live supported-profile enforcement, 450 MHz diagnostic decoding, preserving
negotiated layout for late STOP-tail frames, bounded immutable metadata caches,
and C-backed exhaustive ADC-range validation. The simulator's temperature
command now obeys BOOT and duplicate-request protections. Strict loss checks
remain enabled.

The final command audit also found that the legacy GPIO capture diagnostic
could bypass CONFIGURE and start a fixed 4 MHz acquisition. The release now
clears its INFO capability bit and rejects command `0x19` before execution.
The GPIO clock diagnostic remains available only at 1 MHz. Historical schema
and fixtures still describe the legacy diagnostic response; this release
does not advertise or execute that path.

## Local validation and protocol documentation

The full suite passed **562 tests and 16,324 subtests**. Ruff checking and
formatting, MyPy, all 109 generated protocol outputs, portable firmware tests,
and pinned linked-memory gates passed. The new buffer-headroom regression is
included. The 1.1.0 wheel was built, installed into a fresh environment, and
its deterministic demo passed with two ADC and two GPIO frames and no loss.
That simulator demo is packaging evidence, not physical throughput evidence.

[[Protocol-V2]] is the current human-readable contract, backed by
`protocol/protocol-v2.json`. Automated contract tests compare all command IDs,
successful payload sizes and the generic error ID in its table with the
schema. INFO is 680 bytes (five timing entries); STATUS is 1476 bytes;
GET_TEMPERATURE is `0x1A`/`0x9A` with a 12-byte successful response. The sole
supported rate profile is ID 4/mask `0x10`. Core clock, timestamp periods,
GPIO mapping, frame sizes, errors and temperature status semantics were audited.
Frozen v1 schema/constants/golden frames remain unchanged. Historical reports
retain their original measurements and are explicitly marked as historical;
their experimental rates and 632-byte INFO are not release instructions.
Documentation links and executable simulator snippets pass automated checks.

The optional `TimestampAligner` rejects the new unequal-duration frame layout:
one GPIO frame spans four ADC frames. Use `read_block()` / `blocks()` and the
per-sample timestamps instead. Temperature is calibrated die temperature, not
ambient temperature; transient NOT_READY responses require bounded retries.

## Reproduction

Build the release with `python firmware/tools/build_firmware.py`. The research
builder intentionally permits different clocks/profiles and must not be used
to produce this release. Run the independent physical validator through
`firmware/tools/run_input_isolation.py` with profile `4`, `INPUT_COMBINED`,
600 seconds and `--temperature`, pinning the supplied build directory.
The runner verifies the HEX against its manifest before submitting it.

GitHub release assets include the compiled HEX, build manifest, validation
summary, checksums and selected raw evidence. Test failures remain in the
evidence lineage; they are not converted into passing results.

The [machine-readable validation record](release-1.1.0-validation.json)
separates the final firmware PASS results, SDK TEST_FAIL result and superseded
candidate evidence, with exact job IDs and artifact hashes.
