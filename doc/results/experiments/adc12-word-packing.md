---
type: result
title: 10-bit and 12-bit ADC Sample Packing
created: 2026-10-02
tags:
  - adc
  - packing
  - experiment
related:
  - '[[Hardware-Safety]]'
  - '[[Protocol-V2]]'
---

# 10-bit and 12-bit ADC sample packing

Branch: `experiment/adc12-word-packing`; current work is based on `302249a`
and retains the existing branch tip `adf43e8` as an ancestor.

**Lossless 12-bit packing is the best tradeoff.** It removes 25% of ADC wire
bytes without changing the converter result. Ten-bit packing removes another
506 bytes per frame, but permanently discards two LSBs for only 6.14 percentage
points more empirical USB headroom than today's container format in ADC-only
operation.

## Relationship to the existing experiment

The earlier branch implemented a four-pair, three-word 12-bit kernel and ran
live packed captures. This update ports that exact word layout onto current
main, adds the independent unpacker, adds 10-bit truncating pack/unpack, and
measures all three host kernels under the same workload. Unrelated old
checksum-disabled and USB experiment changes were not carried into current
firmware.

The earlier live evidence remains relevant: the lossless codec passed, two of
three packed captures completed, and the other packed attempts hit the known
ADC DMA/completion fault. This update does not reinterpret or chase that fault,
and does not claim a new physical qualification.

## Wire sizes and USB headroom

All rows retain 1,012 ADC pairs per frame and the existing 44-byte header plus
4-byte trailer. Rates are decimal MB/s at 1,000,000 pairs/s. Headroom is
relative to the measured 24.46 MB/s median saturation rate from the repository's
USB transport experiment; that diagnostic is a practical comparison point,
not a guaranteed production ceiling.

| ADC representation | Payload bytes/frame | Total bytes/frame | ADC framed MB/s | USB headroom |
| --- | ---: | ---: | ---: | ---: |
| Two 16-bit containers | 4,048 | 4,096 | 4.04743 | 83.45% |
| Two packed 12-bit codes | 3,036 | 3,084 | 3.04743 | 87.54% |
| Two packed 10-bit codes | 2,530 | 2,578 | 2.54743 | 89.59% |

For context, combined equal-rate acquisition adds 1.01186 MB/s for eight GPIO
inputs or 2.02372 MB/s for sixteen. Total framed rates and headroom are:

| Representation | ADC + 8 GPIO MB/s / headroom | ADC + 16 GPIO MB/s / headroom |
| --- | ---: | ---: |
| 16-bit containers | 5.05929 / 79.32% | 6.07115 / 75.18% |
| packed 12-bit | 4.05929 / 83.40% | 5.07115 / 79.27% |
| packed 10-bit | 3.55929 / 85.45% | 4.57115 / 81.31% |

## Codec and precision

Twelve-bit output is the existing contiguous little-endian stream. Four pairs
(eight codes) become three 32-bit words and all values `0..4095` round-trip
exactly. Ten-bit output shifts every raw 12-bit code right by two and packs two
pairs into five bytes. The decoder returns the transmitted `0..1023` code.

Reconstructing a 12-bit-scale value with `code10 << 2` has an error of 0–3 raw
counts, mean truncation bias of -1.5 counts, and uniform-code RMS error of
√3.5 = 1.871 counts. It loses two bits of resolution, reduces 4,096 possible
codes to 1,024, and has a worst-case nominal 3.3 V error of about 2.42 mV before
analog error, noise, calibration, or front-end effects. Twelve-bit packing has
no precision loss.

## Host packer CPU cost

GCC 13.3.0 compiled separate translation units with `-O3`. Seven sequential
repetitions processed 200,000 frames after 2,048 warmups. The table reports
median pack time for one 1,012-pair frame and its projected share of one host
core at 1,000,000 pairs/s.

| Representation | Median ns/frame | Million pairs/s | Core at target rate |
| --- | ---: | ---: | ---: |
| 16-bit `memcpy` | 495.950 | 2,040.53 | 0.049% |
| packed 12-bit | 1,661.094 | 609.24 | 0.164% |
| packed 10-bit | 1,458.236 | 693.99 | 0.144% |

The packed kernels cost about 3.35× and 2.94× the host time of the container
copy, but each remains more than 600 times faster than the required pair rate.
These are native-host figures, not Cortex-M7 cycles; the earlier branch's live
work did not expose ADC packer CPU separately.

## Correctness and safety

The host test exhaustively places every input code `0..4095` in every one of
eight sample positions, compares both packed byte streams with an independent
bit-at-a-time writer, then unpacks them. It checks the documented
`0xABC,0x123 -> BC 3A 12` vector, exact sizes, and rejection of wrong lengths or
out-of-range ADC codes. Twelve-bit output must equal the source; ten-bit output
must equal `source >> 2`.

No hardware capture ran in this update. The prototype changes encoding only;
it does not alter A0/A1 electrical limits, source-impedance requirements,
sample timing, or the hardware-safety rules. The watchdog remains disabled.

## Recommendation

Advance packed 12-bit framing only if a protocol revision can advertise the
sample representation explicitly and a fresh live qualification avoids the
known DMA fault. Do not adopt 10-bit truncation for the normal data path: its
incremental 0.5 MB/s saving is not worth the irreversible two-bit precision
loss at the current measured USB margin.
