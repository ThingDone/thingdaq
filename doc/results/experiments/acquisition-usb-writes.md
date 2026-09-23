---
type: result
title: Acquisition USB Write and Batch Experiment
created: 2026-09-23
tags:
  - performance
  - acquisition
  - usb
related:
  - '[[usb-throughput]]'
  - '[[frame-performance]]'
---

# Acquisition USB writes and processing batches

Branch: `experiment/acquisition-usb-writes`, based on `1a01d88`.

**Larger USB writes did not demonstrate a clear benefit at the current 1 MHz
acquisition rates. Doubling acquisition batches with 4 KB writes failed in
two independent cold-boot runs, each after about 2.05 seconds. Keep the
ordinary scheduling defaults.** The raw USB experiment's approximately
24.5 MB/s capacity remains a separate transport-only result.

## Measured results

The ordinary-batch variants completed twelve ten-second captures in total,
each passing all 131 acceptance checks. Both repeated baseline groups passed.
All successful captures sustained approximately 6.000 MB/s of sample payload,
with no reported loss, gaps, partial USB writes, or paired GPIO generation
skew. ADC and GPIO raw queues reached only one ready block, so the existing
two-buffer acquisition limit was not saturated in these captures.

| Group, in test order | Completed captures | Median host CPU seconds | Median GPIO processing % | Maximum TX queue depth |
| --- | ---: | ---: | ---: | ---: |
| 1 KB, baseline before | 3 / 3 | 2.970 | 15.57 | 9 |
| 2 KB | 3 / 3 | 2.912 | 15.60 | 2 |
| 4 KB | 3 / 3 | 2.878 | 15.61 | 17 |
| 4 KB, doubled batch | 0 / 3 planned | — | — | — |
| 1 KB, baseline after | 3 / 3 | 2.734 | 15.58 | 2 |
| 4 KB, doubled batch repeat | 0 / 3 planned | — | — | — |

The host CPU change between identical baseline groups (about 8%) exceeds the
apparent differences between write sizes. GPIO processing stayed around
15.6%; this is not a total MCU CPU measurement. The 2 KB queue peak was low,
but the final baseline matched it. These short tests do not establish a
repeatable performance improvement or higher maximum acquisition rate.

Both doubled-batch jobs stopped during their first planned capture, so the
remaining cells were not run. The host observed a STATUS response in IDLE
with cleared stream configuration, rather than the expected RUNNING state.
Each retained device snapshot had two `adc_dma_error_events`, one
`adc_completion_mismatches`, and one `adc_incomplete_conversions`. ADC captured
2,045,291 and 2,045,287 pairs respectively before stopping. Neither snapshot
showed USB I/O errors, packet-pool exhaustion, or raw-ring overruns. The
runtime's `recoverPhysicalFault()` returns the device to IDLE on a capture
fault; the counters are consistent with that recovery path. This establishes
a reproducible failure of the tested configuration, not the exact underlying
DMA fault. In particular, the completion mismatch may be part of partial-pair
shutdown accounting rather than the initiating event.

| Group | Rig job | Build ID suffix |
| --- | --- | --- |
| 1 KB before | `8ef6f1de-7f5b-490e-befe-8e86cff05d64` | `911ac8dac6c2ad84` |
| 2 KB | `f26c3809-ea94-4764-bbd7-d79bbb060041` | `5bc448fad0c24e02` |
| 4 KB | `ca7b3e5d-816a-4b07-bea3-10b04b87ca00` | `67d8ded7f8219b9b` |
| Doubled batch | `703d53e1-89e4-48e7-81e0-eaaec9f3ecc0` | `1b9e8dad63d1cf4f` |
| 1 KB after | `0befcab8-3bd5-443b-8915-528a0c0cdef4` | `911ac8dac6c2ad84` |
| Doubled batch repeat | `03600932-feaa-4a9c-9816-b1a565dc166e` | `1b9e8dad63d1cf4f` |

Full build IDs begin with `thingdaq-`. [Machine-readable evidence](acquisition-usb-writes.json)
retains summaries, metrics, failure snapshots, build identities, HEX hashes,
memory use, and restoration evidence. Complete rig responses and flashed
images remain in the main workspace's untracked
`doc/results/raw/acquisition-usb/2026-09-23-*` directories.

The published release `thingdaq-636aebbecbf70691` was restored and passed
all 131 checks in a ten-second combined capture, job
`39319a90-50b9-4cb2-aa55-48dfd0089271`. The fixture is left on that release.

## Local validation

All four target variants passed the existing compiler, linker-symbol, and
memory gates. Each used 456992 bytes of RAM1 variables, 32600 bytes of RAM1
code, 168 bytes of padding, and retained 34528 bytes for locals. RAM2 variables
remained 520192 bytes with 4096 bytes free for heap. No memory gate was relaxed.

Transport tests compile and run the same ownership, partial-write, backpressure,
priority, and bounded-work checks for all four settings. These plus the helper,
combined-acquisition, and packet-pipeline suites passed 20 tests and 72 subtests.
The rig's fake-device suite passed 9 tests and 29 subtests using this worktree's
SDK on `PYTHONPATH`. An initial invocation picked up the installed SDK from a
different revision and failed on its incompatible INFO payload size; selecting
the matching SDK resolved that environment mismatch. The live batch failures
above remain failures and disqualify that experimental setting.

## Design

This comparison uses real ADC/GPIO acquisition on Teensy 4.0 serial
`20428100`, at 450 MHz with the pinned Teensy 1.62.0 core. Both streams remain
at 1 MHz, with two ADC channels and sixteen GPIO inputs. All variants enable
the previously tested larger ADC frames: 1012 ADC pairs in a 4096-byte frame,
and 2024 GPIO samples in a 4096-byte frame. The sample payload is 6 MB/s;
including 48 bytes of framing per record, the calculated data rate is
6.071146 MB/s. Rates use decimal MB/s and exclude USB transaction overhead.

| Variant | Maximum USB write | ADC/GPIO buffers per acquisition visit | Packet promotions per visit |
| --- | ---: | ---: | ---: |
| Baseline | 1024 bytes | 2 / 2 | 4 |
| Larger write | 2048 bytes | 2 / 2 | 4 |
| Full frame write | 4096 bytes | 2 / 2 | 4 |
| Full frame and larger batch | 4096 bytes | 4 / 4 | 8 |

Every variant retains the 8192-byte USB visit budget, eight-call limit, two
interleaved acquisition/TX visits per runtime loop, 512-byte minimum available
capacity, and existing packet/DMA allocations. The experimental batch scale
increases the amount of ready work processed per visit, not memory allocation
or sampling frequency. Writes remain bounded by reported available capacity
and the remainder of the current frame. Frames are not coalesced, so a limit
above 4096 bytes would not enlarge a write in this path.

All variants disable data checksums and retain zero trailers; controls remain
checksummed. This isolates scheduling changes within the existing research
format. The validator checks sequences, timing, ADC ranges, loss accounting,
and control responses, but does not prove bit-for-bit integrity of arbitrary
physical samples. Captures are electrically unstimulated and do not verify
external transitions.

Each variant schedules three ten-second captures; a second baseline group checks
for drift after the changed variants. Sampling rates are held constant, so
this experiment tests processing and queue behavior, not maximum sustainable
sampling frequency. Host CPU time measures the acceptance program, including
setup and drain. The existing `firmware_processing_cpu_basis_points` field
measures GPIO packing time only, not total MCU or USB CPU utilization. USB
stall counters count unsuccessful service visits and are not elapsed stall
time. No write-call timing instrumentation is added to the firmware.

## ADC packing

The configured ADC resolution is 12 bits, but `adc_frame_packer.cpp` currently
copies each pair as two 16-bit containers. All 24 useful bits can be retained
in three bytes. For unsigned 12-bit codes `a` and `b`, one possible byte layout
is:

```cpp
out[0] = static_cast<uint8_t>(a);
out[1] = static_cast<uint8_t>((a >> 8) | ((b & 0x0F) << 4));
out[2] = static_cast<uint8_t>(b >> 4);
```

The inverse is `a = out[0] | ((out[1] & 0x0F) << 8)` and
`b = (out[1] >> 4) | (out[2] << 4)`. For example, `0xABC, 0x123` encodes as
`BC 3A 12`. Preconditions are unsigned codes in `0..4095`; packing preserves
both values and their existing phase relationship. It does not reduce ADC
resolution or imply simultaneous sample apertures.

| Sample payload at the present rates | Current | Packed ADC |
| --- | ---: | ---: |
| ADC pair | 4 bytes | 3 bytes |
| ADC stream | 4 MB/s | 3 MB/s |
| Sixteen-input GPIO stream | 2 MB/s | 2 MB/s |
| Combined | 6 MB/s | 5 MB/s |

That saves 25% of ADC payload and 16.7% of combined sample payload. Keeping
1012 pairs per ADC frame would reduce its payload from 4048 to 3036 bytes and
its total frame from 4096 to 3084 bytes while preserving frame timing. The
combined framed rate would then be 5.071146 MB/s with the current headers.
More pairs per frame could reduce header cost further but would also change
block duration and buffering.

A first implementation could retain the existing DMA capture layout and pack
while copying into the outgoing packet, replacing the current `memcpy`.
It would save USB bytes. Raw DMA-ring memory and the fixed packet-slot
allocation would stay unchanged unless separately resized.
The protocol would need an explicit packed format plus host decoding and
validation; current fixed frame sizes and four-byte pair assumptions reject
this layout. Packing/unpacking cost has not been benchmarked here. Fewer than
24 bits per arbitrary pair requires data-dependent compression or reduced
precision. No packed ADC codec is enabled by this experiment.

## Reproduction

Build one variant with the normal memory and toolchain gates:

```bash
python firmware/tools/build_checksum_experiment.py --mode none \
  --large-adc-frame --usb-write-bytes 4096 --pipeline-batch-scale 2
```

The output directory is `firmware/build/checksum-none-adc4096-usb4096-batch2`.
Use `--usb-write-bytes 1024`, `2048`, or `4096`, and batch scale `1` or `2`.
Ordinary builds retain 1024-byte writes and scale 1. The builder salts each
variant's identity and records all limits in `acquisition_usb_experiment`.
The synthetic raw-USB mode cannot be combined with these acquisition options.

```bash
python firmware/tools/run_input_isolation.py --worktree "$PWD" \
  --build-dir "$PWD/firmware/build/checksum-none-adc4096-usb4096-batch2" \
  --evidence-dir "$PWD/doc/results/raw/acquisition-usb/new-run" \
  --case INPUT_COMBINED --profile 4 --profiles 4 4 4 --seconds 10 \
  --checksum-experiment --frame-experiment --service http://192.168.150.14:5000
```
