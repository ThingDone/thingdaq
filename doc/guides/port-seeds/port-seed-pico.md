---
type: guide
title: Port Seed Pico
created: 2026-10-18
tags:
  - thingdaq
  - port
  - seed
  - rp2040
  - rp2350
related:
  - '[[port-seed-common]]'
  - '[[Protocol-V2]]'
  - '[[Hardware-Safety]]'
---

# Port seed: Raspberry Pi Pico and Pico 2

Read [[port-seed-common]] first. This document adds the RP2040 and RP2350
specifics: toolchain, pin map, capture design, rate profiles and the
expected pitfalls. One repository and one code base cover both chips; the
pico-sdk board selection switches between them.

## 1. Targets and toolchain

| Item | Pico (RP2040) | Pico 2 (RP2350) |
| --- | --- | --- |
| Cores | 2 × Cortex-M0+ 125 MHz | 2 × Cortex-M33 150 MHz |
| SRAM | 264 KB | 520 KB |
| USB | Full speed, ~0.9 MB/s sustained CDC | Same |
| ADC | One 12-bit SAR, 500 kS/s total, round-robin mux | Same |
| PIO | 2 blocks × 4 state machines | 3 blocks × 4 state machines |
| DMA | 12 channels | 16 channels |

Use **pico-sdk 2.x with CMake**, not Arduino. Reasons: direct TinyUSB
descriptor and buffer control, explicit core assignment, PIO assembly
through `pioasm`, and a host unit-test target in the same CMake tree.
Build with `-DPICO_BOARD=pico` or `pico2`; flash as UF2 or with `picotool
load -f`. Add `pico_enable_stdio_usb` **off**; the CDC interface belongs to
the protocol, not to `printf`.

## 2. Pin map

| Function | Pins | Notes |
| --- | --- | --- |
| Digital inputs bits 0–7 | GP0–GP7 | 8-input mode |
| Digital inputs bits 8–15 | GP8–GP15 | 16-input mode |
| ADC0 | GP26 (ADC channel 0) | |
| ADC1 | GP27 (ADC channel 1) | |
| Reserved | GP23–GP25, GP29 | On-board regulator control, LED, VSYS sense |

GP0–GP15 are contiguous, so a single PIO `in pins, 16` instruction captures
the whole word with bit *i* equal to GP*i*. Publish this map in INFO
`gpio_pin_map` and `aux_gpio_pin_map`.

RP2350 only: erratum E9 makes an input pad latch when the internal
pull-down is enabled and the pin floats between about 1 V and 2.2 V. Do
not enable internal pull-downs on capture pins; document that unused
inputs need an external pull of 8.2 kΩ or lower, or must be driven.

## 3. GPIO capture design

- One PIO state machine runs a two-instruction loop: `in pins, 16` (or 8)
  with autopush at 16 (or 8) bits, paced by the state-machine clock
  divider. 125 MHz / 1 MHz = 125 and 150 MHz / 1 MHz = 150, both exact
  integers, so the sample period is exact and jitter-free.
- Two DMA channels in ping-pong, each reading the PIO RX FIFO with DREQ
  pacing into one half of a ring in SRAM, chained to each other, with the
  completion interrupt marking a buffer ready. Ring of at least 64 KB.
- The packer on core 1 drains ready buffers into 4096-byte frames (4048
  one-byte items or 2024 two-byte items), writes the header and checksum,
  and queues the frame. Core 0 runs TinyUSB and the control plane.
- Timestamps: START enables the state machine; sample 0 is tick 0 and
  sample *n* is `n × period_ticks`. No clock reading is needed after START
  because the PIO clock and the ADC clock derive from the same system PLL.

## 4. ADC design and its limits

The RP2040/RP2350 ADC is one converter with a 48 MHz clock and 96 cycles
per conversion. In round-robin over channels 0 and 1 each channel gets at
most 250 kS/s and the two samples are 2 µs apart, not simultaneous. Use
the ADC FIFO with the error bit enabled and `DREQ_ADC` to a DMA ring, with
the channel-select bit in the FIFO so the packer can verify the ADC0/ADC1
pairing never slips. The on-chip temperature sensor is ADC channel 4, so
GET_TEMPERATURE returns `UNAVAILABLE` while a capture runs.

Quality is about 8.7 effective bits with known DNL spikes at codes 512,
1536, 2560 and 3584. Report raw codes; do not correct in firmware.

## 5. Proposed rate profiles (protocol v3, option B)

Measure sustained CDC throughput in milestone M2 first. Expect ~0.9 MB/s
and plan for 0.55 MB/s. Starting proposal:

| ID | ADC pairs/s | ADC1 phase | GPIO samples/s | Combined wire rate (16 in) | Purpose |
| ---: | ---: | --- | ---: | --- | --- |
| 5 | 100 000 | 40 ticks (5 µs) | 100 000 | 0.6 MB/s | Default combined |
| 6 | off | | 500 000 | 0.5 MB/s at 8 inputs | Logic capture; 16 inputs at 250 kHz |
| 7 | 200 000 | 20 ticks | off | 0.8 MB/s | ADC only |

Profile 4 (1 MHz) stays defined and rejected, like profiles 0–3 on the
Teensy. Advertise only the mask of profiles the board sustained in M2.

## 6. USB transport

TinyUSB CDC, one interface. Raise `CFG_TUD_CDC_TX_BUFSIZE` to at least 4096
and write whole frames with `tud_cdc_write` followed by
`tud_cdc_write_flush`. Call `tud_task` from the core 0 loop at least every
200 µs or run it from the USB interrupt. Serial number string from the
flash unique ID; product string `ThingDAQ`; VID 0x2E8A with a PID from the
Raspberry Pi open-source allocation or your own.

Bounded buffering: hold at most the packet ring (for example 16 frames)
and count every discarded frame in STATUS, exactly as the Teensy does when
the host stalls.

## 7. Identity, temperature, health

- `hardware_serial`: XOR-fold the 64-bit flash unique ID to 32 bits; if
  zero, use 1.
- `build_id`: hash of the source tree computed by the CMake configure
  step, formatted `thingdaq-<16 hex>`.
- GET_RUNTIME_HEALTH: report free stack of both cores and the watchdog
  state; enable the hardware watchdog once the pipeline is stable.

## 8. Harness mapping

| Milestone | Command |
| --- | --- |
| M0 | `SERIAL_PORT=/dev/ttyACM0 python rig_control_smoke.py` (after v2 edits) |
| M2 | `SERIAL_PORT=/dev/ttyACM0 python rig_synthetic_stream.py` for each profile |
| M3–M4 | `SERIAL_PORT=... EXPECTED_HARDWARE_SERIAL=... EXPECTED_BUILD_ID=... AUX_INPUT_CAPTURE_SECONDS=60 python rig_release_sdk.py` |
| M5 | Adapted soak physical program, 600 s |

A second Pico running a PIO pattern generator is a cheap bit-exact source
for M3; drive it from a known LFSR so the host can check every sample.

## 9. Effort and risk

| Item | Estimate | Risk |
| --- | --- | --- |
| Core: codec, state machine, packet ring, statistics, synthetic source, host tests | 2 weeks | Low |
| PIO + DMA GPIO capture, both widths | 3 days | Low |
| ADC FIFO + DMA, pairing check | 3 days | Medium: FIFO error bit and mux order |
| TinyUSB CDC and throughput tuning | 3 days | Medium: full-speed ceiling |
| Pico 2 bring-up on the same tree | 2 days | Low, except E9 |
| Validation M0–M6 | 1 week | |
| **Total** | **~5 weeks** | |
