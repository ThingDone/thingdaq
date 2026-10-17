---
type: result
title: Firmware Static-Analysis Review
created: 2026-09-12
tags:
  - firmware
  - static-analysis
related: []
---

# Firmware static-analysis review — 2026-09-12

## Scope and environment

This review covers the production firmware at revision `8c63274`: the tracked
`firmware/firmware.ino` entry point and `firmware/src/`. Host tests, soak tools,
generated runtime caches, and compiled build output were intentionally excluded.

The deployed C Analyzer was current with `origin/master` at `92cc000a` and ran
the pinned image built from `4a4b63b2`. The persistent review project is:

- `teensy-daq-firmware-analysis-8c63274-0c29b15d`
- `http://pcbg:7000/?project=teensy-daq-firmware-analysis-8c63274-0c29b15d`

The deployment does not contain the `teensy:avr` Arduino core, so it cannot run
the sketch-build ingest path for the real FQBN
`teensy:avr:teensy40:usb=serial,speed=450,opt=o2std`. For static inspection only,
the uploaded archive contains an unchanged copy of `firmware.ino` named
`firmware.cpp`. This preserves `setup()`, `loop()`, and their call-graph edges
without pretending that the generic host compiler is a Teensy compiler.

The srcML pipeline completed without an analysis error. It produced 977
function nodes and 2,136 call edges from 85 files.

## Inspection results

The full deployed batch ran regeneration, RTOS detection, preprocessor
detection, all firmware checks, cppcheck, Semgrep, CodeChecker, AI Auditor, and
AI Data-Fault. Detailed findings remain in the persistent project above.

The firmware checks emitted 18 candidates: 13 IRQ lock-pair findings, four
state-machine findings, and one blocking-context finding. Manual review reached
these conclusions:

- All 13 IRQ findings are false positives. The direct critical sections restore
  the captured `PRIMASK` before returning. The three `enter()` findings are the
  acquire half of an intentional `enter()`/`exit(token)` interface and return
  the saved mask as the token; returning is not an unpaired exit.
- The four state-machine findings are false positives in
  `validChecksumBenchmarkRequest()`. Its switches validate values received from
  the wire. They do not implement a state machine or assign transitions.
- The spin in `gpio_raw_capture_teensy.cpp::waitForCompleteStopBoundary()` is
  real but bounded by the DWT counter to 10 ms. It intentionally waits for an
  eDMA major-loop boundary before teardown. It is not an infinite-wait defect,
  but it is a possible cooperative-loop latency risk and is the one firmware
  item retained for follow-up.

The non-AI static analyzers did not establish another correctness defect:

- Semgrep emitted no findings.
- cppcheck emitted 224 records. Most are analysis-quality or style records:
  106 unavailable system headers, 42 unused-function reports caused by analyzing
  translation units without the Arduino core, 27 branch-limit notices, and 28
  suggestions to use STL algorithms. The purported 56-bit shift is in the
  four-iteration `loadU32()` loop and cannot shift farther than 24 bits. The
  unsigned wrap checks are intentional and pinned by compile-time assertions.
  The reported output-buffer writes are externally observable writes, not dead
  stores.
- Eight of CodeChecker's nine records are cascading compile errors in the
  analysis-only sketch wrapper because Teensy macros and core headers are absent.
  The remaining `misc-redundant-expression` record is the defensive two-bound
  copy loop for the build identifier, not a functional fault.
- AI Auditor completed its 46-file review with no findings.

The complete host firmware suite independently passed: 200 tests and 821
subtests. That includes strict `-Wall -Wextra -Werror -Wconversion
-Wsign-conversion -pedantic` compilation and protocol cross-language fixtures.

## Firmware risk-reduction plan

No confirmed correctness defect should be patched from these findings alone.
Use the following ordered plan to resolve the retained stop-latency risk and to
make later analyzer runs more authoritative.

1. Measure the stop path before changing it. Add a target diagnostic that
   records the maximum DWT cycles spent in both GPIO and ADC stop-boundary waits,
   the number of timeouts, and the largest control/USB service gap during STOP.
   Exercise normal stop, host stall, DMA fault, and rate/profile transitions at
   the release clock and stream profile.
2. Establish an acceptance limit from the protocol control-response deadline
   and USB buffering budget. Keep the existing bounded implementation if its
   measured worst case stays inside that limit; document the bound beside the
   constants and add a regression assertion.
3. If the bound is exceeded, replace the synchronous GPIO spin with a two-phase
   stop state. The request phase should set `DREQ`, save a DWT deadline, and
   return `pending`; later `FirmwareRuntime::service()` calls should poll once,
   then finalize the ring at the major-loop boundary or take the existing
   timeout/fault path. Preserve `StopReport`, partial-sample accounting, safe-pin
   teardown, and storage-release ordering.
4. Add host-register tests for immediate completion, delayed completion,
   timeout, DWT wraparound, a pending DMA interrupt, and repeated STOP while a
   stop is pending. Then run the complete firmware suite, build the exact release
   FQBN, and repeat the combined physical/host-stall soak gates before accepting
   the state-machine change.
5. Separately improve inspection fidelity: make `build_firmware.py` emit or
   retain a relocatable compilation database (including the exact Teensy core
   macros and include paths), and teach the deployed analyzer to consume a
   provisioned Teensy core. Re-run cppcheck and CodeChecker only after that
   boundary is reproducible; do not change production code merely to silence
   missing-core diagnostics.
6. For the custom lock-pair check, prefer an analyzer model or scoped annotation
   for `readPrimask()`/`restorePrimask()` and the `CriticalSection::enter/exit`
   token protocol. An inline target-only guard can be considered for direct
   critical sections, but accept it only if generated assembly and timing are
   unchanged. This is maintainability work, not a response to an observed lock
   leak.

