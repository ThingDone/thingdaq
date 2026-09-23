---
type: result
title: ADC12 Word Packing Experiment
created: 2026-09-23
tags:
  - performance
  - acquisition
  - packing
related:
  - '[[acquisition-usb-writes]]'
---

# Lossless 16-byte to 12-byte ADC packing

Branch: `experiment/adc12-word-packing`, based on `8c73ec0`.

The requested 32-bit-word loop is implemented and passes exhaustive native
codec tests. It saves 25% of ADC payload, preserving all twelve bits of every
sample. Live tests confirmed the smaller frames, but did **not** establish a
performance improvement: two packed captures passed and two attempts faulted.
All six unpacked comparison captures passed. Keep this as an opt-in experiment;
the packed acquisition configuration is not qualified for release.

## Implementation

`firmware/src/adc_frame_packer.cpp::pack12BitPairs` processes four ADC pairs
(eight unsigned 12-bit values) per iteration. It replaces the outgoing payload
copy with packing; DMA still writes the original two 16-bit containers per pair.
For values `v0` through `v7` in acquisition order, the three output words are:

```cpp
word0 = v0        | (v1 << 12) | (v2 << 24);
word1 = (v2 >> 8) | (v3 << 4)  | (v4 << 16) | (v5 << 28);
word2 = (v5 >> 4) | (v6 << 8)  | (v7 << 20);
```

Each value is a `uint32_t`; input codes above `0xFFF` are rejected rather than
truncated. The payload is a little-endian contiguous 12-bit bitstream, retaining
adc0 then adc1 order. For example, pair `0xABC, 0x123` becomes `BC 3A 12`.
The destination must be four-byte aligned and exactly three bytes per pair;
pair count must be a nonzero multiple of four. Invalid acquisition data cancels
the frame and releases its DMA lease. There are 253 iterations per ADC frame.

A constant-size `memcpy` writes the local three-word result without violating
byte-array aliasing rules. Inspection of the Teensy GCC 15.2.1 output confirms
eight halfword loads and word output stores (`strd` plus `str`), with no function
call inside the packing loop. The source advances 16 bytes and the destination
12 bytes per iteration. This is **32-bit word-oriented**, not a requirement for
32-byte output alignment.

The experimental layout, protocol validation, and both USB admission checks
accept 3,084-byte ADC frames. Legacy v1 frames and ordinary builds keep their
existing format. The standalone rig adapter provides an independent byte-based
decoder and separates wire pair width (three bytes) from DMA pair width (four).
The regular SDK is not changed to accept this research format. INFO's container
and pair byte fields retain their raw representation; the manifest and explicit
`--adc12-packed` runner option identify the packed wire format.

## Size and timing

| Quantity | Unpacked | Packed |
| --- | ---: | ---: |
| ADC pairs per frame | 1,012 | 1,012 |
| ADC sample payload per frame | 4,048 bytes | 3,036 bytes |
| ADC frame including header/trailer | 4,096 bytes | 3,084 bytes |
| GPIO frame | 4,096 bytes | 4,096 bytes |
| ADC payload at 1 MHz pair rate | 4 MB/s | 3 MB/s |
| Combined ADC/GPIO sample payload | 6 MB/s | 5 MB/s |
| Combined framed rate, calculated | 6.071146 MB/s | 5.071146 MB/s |

Rates use decimal MB/s and exclude USB transaction overhead. ADC frames cover
1.012 ms; GPIO frames cover 2.024 ms. Sample counts, rate, timestamps, phase,
DMA allocations, and fixed packet-slot allocations are unchanged. The saving is
16.7% of combined sample payload; fewer transmitted bytes do not automatically
increase the configured acquisition rate. No higher sample-rate test was run.

## Live comparison

Teensy 4.0 serial `20428100`, 450 MHz, Teensy core 1.62.0. Both ADC pair and
sixteen-input GPIO sample rates were fixed at 1 MHz. Both experimental variants
used 1 KB maximum USB writes and the ordinary acquisition batch limits. Data
checksums were disabled in both, with control checksums retained.

Each group planned three ten-second captures, stopping at the first failure.
Values below are medians of completed passing captures; queue depth is the
largest observed high-water mark within those captures.

| Group | Passed / attempted | Host CPU seconds | GPIO processing % | Maximum TX queue |
| --- | ---: | ---: | ---: | ---: |
| Unpacked before | 3 / 3 | 2.921 | 15.94 | 3 |
| Packed | 2 / 3 | 4.756 | 18.36 | 159 |
| Unpacked after | 3 / 3 | 2.842 | 15.94 | 2 |
| Packed, fresh boot repeat | 0 / 1 | — | — | — |

All passing captures completed 131 acceptance checks with no reported gaps,
loss, paired-generation skew, or partial USB writes. The packed host decoder
unpacked every received pair. Its Python loop increased validation work, so the
host CPU and queue results include that cost. These measurements do not isolate
the firmware packing cost. The existing firmware CPU field measures GPIO
processing only, not ADC packing or total MCU utilization. USB stall counters
count service visits, not elapsed stalled time.

The two failed attempts stopped with the device in IDLE after 2,045,297 and
2,045,288 ADC pairs (about 2.045 seconds). Each retained failure snapshot reported
two `adc_dma_error_events`, one `adc_completion_mismatches`, and one
`adc_incomplete_conversions`. Both had zero ADC raw-ring overruns and USB I/O
errors, and a TX queue high-water mark of 15. This resembles the earlier batch
experiment's failure signature but does not identify the initiating DMA fault;
completion mismatch can also arise during partial-pair shutdown. The failed
configuration remains disqualified even though its codec round trips correctly.

| Group | Rig job | Build ID suffix |
| --- | --- | --- |
| Unpacked before | `4ca5af86-850f-4209-a488-c1d8e778dcf0` | `d57b172cfd2b2f8e` |
| Packed | `e8e14b28-12de-42cc-9a2d-51376f6b85ec` | `b8f8209c7962cba3` |
| Unpacked after | `cc9e1e5e-6e23-49b6-8c46-a59607f58db0` | `ef3a0a0c55aba6e0` |
| Packed repeat | `fddd34a5-f24c-474d-8881-d96ad284c4a6` | `b8f8209c7962cba3` |

The first baseline preceded consolidation of the USB frame-size checks and a
comment update. Those edits change admission only for the packed format;
the final-source unpacked baseline also passed all three captures. Both packed
jobs used the identical HEX, SHA-256
`6d78ef83990d73021d3debe1f15537f2a57d724b387296ffbce7e586b8c772e7`.

The fixture was electrically unstimulated: external transitions and analog
accuracy were not tested. No data checksum means the live runs do not establish
bit-for-bit integrity of physical samples. Native reference tests establish the
codec transformation independently of the fixture.

## Validation and reproduction

The native kernel test exercises all 4,096 codes in every sample position against
a bit-by-bit reference, output guards, invalid input range, alignment and length
rejection. It also exercises an actual CRC-protected packed frame through the
packet pipeline and decodes all 1,012 pairs with the independent Python decoder.
Timestamp/gap accounting, invalid-frame cancellation, old v1 behavior, and USB
zero/partial writes are covered. The rig adapter test checks packed wire width,
raw DMA width, and ADC/GPIO chronology. The combined local suites passed 38 tests
and 870 subtests before this report was added.

Both final target builds pass the normal memory/toolchain gates. Packed RAM1
code is 32,616 bytes versus 32,600 unpacked; both retain 34,528 bytes for local
variables and 4,096 bytes of RAM2 heap. No memory limit was relaxed.

```bash
python firmware/tools/build_checksum_experiment.py --mode none \
  --large-adc-frame --adc12-packed

python firmware/tools/run_input_isolation.py --worktree "$PWD" \
  --build-dir "$PWD/firmware/build/checksum-none-adc4096-adc12" \
  --evidence-dir "$PWD/doc/results/raw/adc12-word/new-packed-run" \
  --case INPUT_COMBINED --profile 4 --profiles 4 4 4 --seconds 10 \
  --checksum-experiment --frame-experiment --adc12-packed \
  --service http://192.168.150.14:5000
```

Omit `--adc12-packed` from both commands for the unpacked comparison, using build
directory `checksum-none-adc4096` and a new evidence directory. The packed option
requires the larger 1,012-pair frame so every frame contains complete four-pair
groups. Ordinary builds do not enable this option.

Raw manifests, HEX images, submitted programs, snapshots, and rig output are
retained locally under `doc/results/raw/adc12-word/2026-09-23-*`.
The committed [machine-readable results](adc12-word-packing.json) preserve all
capture summaries, failure snapshots, job IDs, and firmware/program hashes.

After the experiment, the published 1.1.0 firmware was restored and passed a
ten-second INPUT_COMBINED capture with all 131 checks. Restoration job:
`b931c834-cfbb-411f-9ef7-0e4b65e2230c`; build ID:
`thingdaq-636aebbecbf70691`; HEX SHA-256:
`23b0f2ef8023c52021b22b8c6642f801866dfe8b1aadc48affc6b1ac66c2157a`.
