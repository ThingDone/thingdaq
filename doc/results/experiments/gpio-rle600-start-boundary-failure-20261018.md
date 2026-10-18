---
type: result
title: GPIO RLE START Boundary Host Failure
created: 2026-10-18
tags: [firmware, compression, validation]
related: []
---

# GPIO RLE START boundary failure

**FAIL — host START deferral assumed fixed-size frames.** The first 60-second
GPIO-RLE smoke stopped at START, before sustained acquisition. Remote job
`61cf02f7-5fd7-4faa-ae7f-d52a6ce2461c` used the clean committed image
`thingdaq-87c25c1a8732105e` (HEX SHA-256
`8436511c60ce30e5a8a83bf6471bb0426c5443b7ad9b2a0b16420004d60c3d00`).
It is not a passing smoke and cannot count toward qualification.

The independent validator reported `START boundary data exceeds bounded
deferral`. Its START response handling deferred data decoded from the same
64 KiB serial read until the response supplied the run ID. The old larger-ADC
limit was seventeen frames, derived from 4,096-byte minimum wire size. GPIO
RLE permits 52-byte frames; a valid mixed batch exceeded seventeen frames.
This was a host buffering error, not evidence of wire corruption: parser
checksum/header/payload errors, discarded bytes and rejection windows were
all zero. The failure snapshot showed eighteen ADC frames (73,728 wire bytes)
and nine GPIO frames (468 wire bytes), with zero firmware drop/error counters.
The best-effort cleanup logged STOP and IDLE. This short failed run does not
establish sustained reliability, final conservation or thermal performance.

The host fix derives a finite frame-count bound from the smallest selected
wire frame, and separately caps deferred wire bytes at one serial read plus
one maximum frame. At the RLE limit, decoded payload retention is below 5 MiB.
All frames still undergo checksum, run, sequence, tick, logical-count and final
wire-conservation validation. Command deadlines are unchanged. Regression
coverage includes a valid compressed START burst exceeding seventeen frames,
frame-count overflow, RAW-byte overflow and the unchanged ordinary frame-count
limit. The firmware image is reused unchanged for a fresh qualification.

The two earlier RAM1 build failures are also preserved as failures; neither
was flashed. The unchanged 32,768-byte stack/local gate rejected the builds,
and flash placement restored 34,400 bytes of headroom before this smoke.
Full failure summary, provenance, artifact hashes and build-failure hashes are
in [the evidence](gpio-rle600-start-boundary-failure-20261018.json). Raw job data
remains under `doc/results/raw/gpio-rle600-20261018/smoke-60`. Follow-up captures
must use a new directory; this result must never be overwritten or relabeled.
