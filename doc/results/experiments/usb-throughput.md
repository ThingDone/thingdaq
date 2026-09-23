---
type: result
title: Synthetic GPIO USB Throughput Experiment
created: 2026-09-23
tags:
  - performance
  - usb
  - experiment
related:
  - '[[frame-performance]]'
---

# Synthetic GPIO USB throughput

Branch: `experiment/usb-throughput`, based on `experiment/larger-adc-frames`
at `763ba369b112ca9ca4f5eefc95d1f1d89d312c99`. The larger ADC frame flag is
not enabled for this experiment.

**The synthetic transport sustained about 24.5 MB/s of verified payload,
roughly four times the current 6 MB/s acquisition payload. Larger GPIO frames,
coalesced writes, and combined ADC/GPIO records gave no repeatable throughput
gain in these short runs.** This demonstrates transport headroom without
establishing a faster physical acquisition rate.

## Results

Both matrices passed all 18 measured cells and 15 warm-up cells. The host
verified 2,647,994,368 framed bytes across both matrices, with no payload or
sequence errors and no device short writes. The second build only shortened
sketch comments to satisfy the existing 65-line sketch gate; diagnostic behavior
was unchanged. Results below are host payload MB/s medians, three saturation
repetitions per layout per matrix.

| Layout | Initial matrix | Final matrix |
| --- | ---: | ---: |
| 4 KB GPIO | 24.45 | 24.46 |
| 8 KB GPIO | 24.35 | 24.43 |
| Separate 4 KB ADC/GPIO records | 24.50 | 24.47 |
| Two 4 KB records per 8 KB write | 24.22 | 24.38 |
| Combined 8 KB ADC/GPIO record | 24.56 | 24.29 |

Individual saturation cells ranged from 23.94 to 24.59 MB/s in the initial
matrix and 24.01 to 24.57 MB/s in the final matrix. The combined layout moved
from slightly faster to slightly slower than separate records. These runs
support no consistent advantage from doubling application writes or joining
the frames. They are short comparisons, not long-duration reliability soaks.

The final 6/12/24 MB/s offered-wire-rate sweep measured 5.991/11.983/23.975
MB/s on the host. Device wire accounting measured 6.001/12.001/24.001 MB/s;
host elapsed time also includes final delivery and read timeout overhead.
Final saturation medians used about 35.6–38.8% of one host core for verification.

Initial job: `76ec4e00-b280-4fe0-ac99-bee7722750ca`, build
`thingdaq-ac387fc4a9a26103`. Final job:
`273ea9b6-ea1b-435e-aafc-1a77c100d005`, build
`thingdaq-98ccdf9eda4b3aba`, HEX SHA-256
`388803271e5c04603b6e049f4c50ebfc994ff06139a0602827f220fdd11b11a9`.
Machine-readable measurements, warm-ups, identities, and restoration results
are retained in [usb-throughput.json](usb-throughput.json). Untracked full rig
responses, programs, manifests, and HEX files remain in the main workspace's
`doc/results/raw/usb-throughput/2026-09-23-*` directories.

The published release `thingdaq-636aebbecbf70691` was restored after each
matrix. The final restoration job `32eb717f-31de-44b4-9201-e8f86444f44a`
passed all 131 checks in a ten-second combined ADC/GPIO capture at 1 MHz.
This was an electrically unstimulated capture; external transition checks
were not run. The fixture is left on the published release.

## Implementation validation

The diagnostic and ordinary checksum-none target builds passed the existing
toolchain, linker-symbol, and memory gates. Final diagnostic RAM1 use was
457152 bytes of variables, 32616 bytes of code, and 152 bytes of padding,
leaving 34368 bytes for locals. RAM2 variables remained 520192 bytes with
4096 bytes of heap headroom; the packet pool was not enlarged.

Native tests compile the actual C++ diagnostic with platform fakes and feed
its output into the independent Python checker. Coverage includes all five
layouts, byte corruption, sequence gaps, partial writes, rate pacing, command
validation, deadline completion, and disconnect handling. The diagnostic,
input-isolation helper, transport, and firmware runtime suites passed
17 tests and 25 subtests. Documentation integrity and repository layout passed
8 tests and 777 subtests; Python lint and Git whitespace checks also passed.

## Method

The opt-in `--usb-throughput` build serves a command-driven synthetic stream
from idle firmware. Payloads are prebuilt repeating byte ramps; every payload
byte and frame sequence is checked on the host. There is no data checksum.
The fake GPIO data can exceed the rate at which physical pins produce useful
samples. No acquisition is started and no fixture output pins are driven.

The experiment borrows 8192 bytes from existing idle DTCM packet storage.
Every variant has the same working allocation; 8 KB variants change frame
and/or write size, not total allocated memory. Diagnostic state adds 160 bytes
of RAM1 variables. The pinned Teensy core has four 2048-byte USB TX buffers
and copies application writes into those buffers. An 8192-byte application
write still passes through this ring and does not eliminate its copy.

| Mode | Record size | Write size | Synthetic payload layout |
| --- | ---: | ---: | --- |
| `gpio-4k` | 4096 | 4096 | 4064 GPIO bytes |
| `gpio-8k` | 8192 | 8192 | 8160 GPIO bytes |
| `separate-4k` | 4096 | 4096 | ADC, ADC, GPIO records, each with 4064 payload bytes |
| `coalesced-8k` | 4096 | 8192 | Same record sequence, two records per write |
| `combined-8k` | 8192 | 8192 | One record with 5440 ADC and 2720 GPIO bytes |

Each record has a 32-byte research header. Mixed streams model the 2:1
ADC-to-GPIO payload ratio of two 16-bit ADC channels and sixteen GPIO inputs
sampled at equal rates. Mode 4 isolates write coalescing; mode 5 also removes
one header by combining the streams. These are research records, not protocol
v2 frames or production SDK input.

The rig used Teensy 4.0 serial `20428100` at 450 MHz, Teensy core 1.62.0,
Arduino CLI 1.4.1, GCC 15.2.1, and USB serial. The running firmware reported
high-speed USB. Each matrix first offered 6, 12, and 24 million framed bytes
per second using mode 1, then ran three uncapped repetitions of every mode.
Each measured cell lasted three seconds; each saturation cell had a separate
250 ms warm-up. Mode order rotated between repetitions. MB/s means decimal
millions of bytes per second; wire counts include research headers but exclude
USB transaction overhead, command replies, and END records.

## Scope and interpretation

This isolates the prebuilt-data transport path. It bypasses acquisition,
DMA packing, the normal packet scheduler, and checksum computation. It does
not establish a higher sustainable physical sampling rate or identify a
universal USB bandwidth ceiling. The host verifies the complete stream, so
its parser and USB stack also contribute to the measured limit.

Production transport limits each write to 1024 bytes to preserve acquisition
responsiveness. This diagnostic instead offers complete 4096/8192-byte writes
to the core, which can block while waiting for USB space. Its device
`write_active_us` includes that waiting and is not a MCU CPU utilization
measurement. Host CPU figures represent the verifier process as a percentage
of one core, not the normal SDK's cost.

Combining production buffers requires more than concatenating data. One
current sixteen-input GPIO payload covers 2024 sample times (4048 bytes).
Matching ADC data occupy 8096 bytes, so their combined payload is 12144 bytes
before headers, already larger than 8 KB. An 8 KB common frame would require
reblocking partial capture blocks and preserving independent readiness, loss,
and tail handling. This benchmark tests transport batching without implementing
that producer join; it does not show that such a join would simplify firmware.

## Reproduction

Build from this branch with the existing pinned toolchain and memory gates:

```bash
python firmware/tools/build_checksum_experiment.py --mode none --usb-throughput
```

The diagnostic interface accepts newline-terminated ASCII commands. `INFO`
returns binary identity/configuration. `RUN <mode> <milliseconds> <wire_Bps>`
accepts modes 1 through 5, durations 100 through 30000 ms, and rates 0 through
60000000 B/s; zero means uncapped. For example, `RUN 2 3000 0` sends 8 KB fake
GPIO frames for three seconds. `STOP` ends at a transfer boundary. Idle
`PROTOCOL` switches to the ordinary runtime until reset. Responses and data
are binary; use `firmware/tests/rig_usb_throughput.py` to decode and verify them.

For a complete matrix through the existing rig service:

```bash
python firmware/tools/run_input_isolation.py \
  --worktree "$PWD" --build-dir "$PWD/firmware/build/usb-throughput" \
  --evidence-dir "$PWD/doc/results/raw/usb-throughput/new-matrix" \
  --case INPUT_COMBINED --profile 4 --seconds 3 \
  --checksum-experiment --usb-throughput --service http://192.168.150.14:5000
```

The helper's case/profile arguments are inherited interface requirements;
the USB validator runs its own synthetic matrix. This build is opt-in and
wire-incompatible with normal clients. Restore the qualified release after
testing. The benchmark is not enabled in normal builds.
