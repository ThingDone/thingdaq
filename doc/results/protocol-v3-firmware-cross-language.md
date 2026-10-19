---
type: report
title: Public v3 firmware and Python cross-language sessions
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - python-api
  - cross-language-tests
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-firmware-layouts]]'
  - '[[protocol-v3-firmware-adversarial]]'
  - '[[protocol-v3-python]]'
---

# Firmware and public SDK agreement

Completes the seventh Phase 03 task. Production firmware and SDK code are
unchanged. No hardware was accessed; no task images were supplied or analyzed.

## Reused execution paths

`firmware/tests/v3_cross_language_test.cpp` reuses the runtime test's CDC and
clock fakes and links the existing complete portable production source list.
Python supplies command bytes, including generated v3 fixtures, through a
small test-only line wrapper. Firmware does not serialize its own input.

The runtime mode executes the real incremental command parser, control state,
synthetic acquisition, deferred codecs, statistics publication and USB path.
CDC reads are limited to three bytes and writes to seven bytes. The second
mode feeds controlled samples at the packet boundary, using the real command
parser, ControlState, packet pipeline, codecs and USB transport. Applied
control settings select the layout; both streams are submitted before codec
service. Its 12-item frames make exact RLE ties independently checkable. This
mode does not implement acquisition or publish acquisition statistics; loss
and layout metadata assertions use the full runtime mode.

`firmware/tests/test_v3_cross_language.py` uses the public compatible parser,
`decode_v3_block`, legacy `decode_message`, `ADCBlock` and `GPIOBlock`. Entire
mixed control/data/version streams arrive as single bytes or irregular chunks,
including frame-boundary crossings. Checks require zero discarded bytes,
checksum errors and trailing buffered bytes. No private experiment decoder or
Python simulator supplies the expected data.

## Coverage

| Surface | Independently checked behavior |
| --- | --- |
| Compiled profiles | 450 MHz RAW-only and 600 MHz RAW/RLE_AUTO/PACK12, without private codec defines |
| Advertised configurations | Every synthetic stream-mask/width/policy tuple: six at 450 MHz, 24 at 600 MHz |
| Repeated sessions | 72 runtime runs across chunk schedules, including both legacy GPIO widths and a return to v3 in each process |
| Golden controls | All seven request kinds; exact CONFIGURE, GET_SETTINGS, START and STOP response bytes where fixture state/settings match; 450 MHz rejects the 600 MHz golden configuration |
| Controlled samples | 20 dual-stream runs across both profiles, GPIO widths, source flags and advertised policy pairs; ADC zero/full-scale and asymmetric bit patterns |
| Adaptive encoding | Constant, alternating, exact-tie and two-span GPIO frames within each run; RLE/RAW/RAW/RLE under RLE_AUTO, RAW throughout under RAW policy |
| Values and timing | Every ADC channel value and pair timestamp, every GPIO sample and timestamp, sequence/run identity, decoded count and end tick |
| Wire accounting | Exact per-frame sizes and encoding IDs; actual transmitted bytes agree with final STATUS; legacy layouts stay exact |
| Settings | CONFIGURE echoes, running GET_SETTINGS, clocks from advertised profiles, and legacy configuration readback |
| Loss | 220 acquisition steps with CDC blocked; exact produced/dropped frames and items from elapsed ticks and received frames, sequence-gap flags, final wire totals and public counter reconciliation |

Controlled source flags describe test data; they do not demonstrate physical
capture. Portable results do not qualify hardware clocks, DMA timing, sustained
USB throughput, electrical input behavior or physical loss rates. These checks
extend the boundaries documented in [[protocol-v3-firmware-adversarial]] and
[[protocol-v3-firmware-layouts]].

## Validation

- New cross-language suite: **10 passed**, in 16.40 seconds.
- Both C++ builds retain `-Wall -Wextra -Werror -Wconversion -Wsign-conversion
  -pedantic -fno-exceptions -fno-rtti`.
- Generator: all **142 outputs current**. Ruff formatting/checks: **197 files**
  pass. Mypy: **33 source files** pass.
- Full firmware/Python regression: **1,783 passed, 5 expected skips,
  16,783 subtests**, in 254.48 seconds. Skips retain the three equal-rate
  override exclusions and two unadvertised 450 MHz compression cases.
- Documentation integrity including this report: **4 passed, 1,053 subtests**.
  Staged whitespace checks pass.

Commands and logs use ignored scratch space under
`.maestro/playbooks/Working/cross-language/`, with `TMPDIR` inside the workspace.
