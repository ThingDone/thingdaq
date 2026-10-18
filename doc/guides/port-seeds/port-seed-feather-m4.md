---
type: guide
title: Port Seed Feather M4
created: 2026-10-18
tags:
  - thingdaq
  - port
  - seed
  - samd51
related:
  - '[[port-seed-common]]'
  - '[[Protocol-V2]]'
  - '[[Hardware-Safety]]'
---

# Port seed: Adafruit Feather M4 Express

Read [[port-seed-common]] first. This document adds the SAMD51J19A
specifics. The Feather M4 is the only board in this port set with two
independent ADCs, so it is the natural choice when analog matters more
than digital width.

## 1. Target and toolchain

| Item | Value |
| --- | --- |
| MCU | ATSAMD51J19A, Cortex-M4F 120 MHz, 192 KB SRAM, 512 KB flash |
| USB | Full speed device, ~0.9 MB/s sustained CDC |
| ADC | ADC0 and ADC1, 12-bit, up to 1 MS/s each, independent |
| DMA | DMAC with 32 channels, linked descriptors, event-triggered |
| Timers | TC0–TC5, TCC0–TCC4, EVSYS with 32 channels |
| Bootloader | UF2 (double-tap reset) |

Use **arm-none-eabi-gcc with CMake** and the Microchip CMSIS/DFP headers
(`samd51j19a.h`) directly. Do not generate code with Atmel START; use the
datasheet and register headers. Flash with `uf2conv.py` or `bossac` after
the 1200-baud touch. TinyUSB has a native SAMD51 driver.

## 2. Pin map

Verify every entry against Adafruit's `variant.cpp` for the Feather M4
before trusting it; the port-group assignments below are from the
schematic and are the basis of the design.

| Function | Feather label | Port pin | Notes |
| --- | --- | --- | --- |
| Inputs bits 0–7 | D5, SCK, D6, D9, D10, D11, D12, D13 | PA16–PA23 | Contiguous byte 2 of `PORT->Group[0].IN`, one DMA beat |
| Inputs bits 8–15 | D0, D1, MISO, MOSI, A2, A3, SDA, SCL | PB16, PB17, PB22, PB23, PB08, PB09, PA12, PA13 | Not contiguous; needs a second bank read and a software join |
| ADC0 | A0 | PA02, ADC0 AIN0 | |
| ADC1 | A2 or A3 | PB08 or PB09, ADC1 AIN0/AIN1 | A1 (PA05) is on ADC0 only, so it cannot be the second converter's input |

Consequence: 8 inputs are a single byte-wide DMA read at full rate. 16
inputs cost a second DMA channel reading a 32-bit word from PORTB (plus
two bits from PORTA), and a join step in the packer that masks and shifts
into the 16-bit item. Choosing ADC1 on A2 means the 16-input mode and ADC
cannot share A2; publish that in the capability mask or move bit 12 to
another pin.

## 3. Trigger and DMA design

- One TC (for example TC0, GCLK at 120 MHz) in match-frequency mode sets
  the sample rate. Its overflow event goes through EVSYS to both ADC START
  inputs, so ADC0 and ADC1 convert on the same edge: truly simultaneous,
  `adc1_phase_ticks = 0`.
- ADC RESRDY of each converter is the DMAC trigger for its own channel; each
  channel runs a linked two-descriptor ring (ping-pong) into SRAM with
  `BTCTRL.BLOCKACT=INT` on each half. Pack `u16 ADC0, u16 ADC1` from the
  two rings by index; a mismatch of the two ring counts is an overrun and
  is counted.
- GPIO: the same TC overflow is also a DMAC trigger source (`TCn_OVF`).
  A byte-wide channel copies `PORT->Group[0].IN` byte 2 into its ring each
  period. For 16 inputs a second channel on the same trigger copies the
  PORTB word.
- Set capture channels at DMAC priority 3 and leave USB to the CPU
  (TinyUSB does not use DMAC on SAMD51), so bus contention is limited.
- Timestamps: the TC starts on START; sample *n* is `n × period_ticks`. 120
  MHz / 8 MHz = 15, so every integer-microsecond period is an exact tick
  count.

ADC configuration: 12-bit, single-ended, `REFCTRL.REFSEL = INTVCC1`
(VDDANA/2 with gain 2 is the usual 3.3 V scale), ADC GCLK ≤ 16 MHz,
minimal sampling length, prescaler chosen so conversion time fits the
period. Run the ADC calibration load from NVM (`BIASCOMP`, `BIASREFBUF`,
`BIASR2R`) at boot and report it in INFO.

## 4. Proposed rate profiles (protocol v3, option B)

| ID | ADC pairs/s | ADC1 phase | GPIO samples/s | Combined wire rate (16 in) | Purpose |
| ---: | ---: | --- | ---: | --- | --- |
| 5 | 100 000 | 0 | 100 000 | 0.6 MB/s | Default combined |
| 6 | off | | 500 000 | 0.5 MB/s at 8 inputs | Logic capture |
| 7 | 200 000 | 0 | off | 0.8 MB/s | ADC only, simultaneous |

The converters can go to 1 MS/s each, but full-speed USB cannot carry it.
Profile 4 stays defined and rejected.

## 5. USB transport

TinyUSB CDC, Adafruit VID 0x239A with a PID requested from Adafruit or
your own. Serial string from the 128-bit device serial at the documented
word addresses; fold to a nonzero u32 for `hardware_serial`. Same buffer
and flush rules as the Pico seed: whole frames, bounded packet ring,
honest discard counters.

## 6. Identity, temperature, health

- The internal temperature channels (PTAT/CTAT) need ADC0, so
  GET_TEMPERATURE is `UNAVAILABLE` while running and valid when idle.
- GET_RUNTIME_HEALTH: stack watermark and WDT state. Enable the WDT with a
  2 s window once the pipeline is stable.

## 7. Harness mapping

Same as the Pico seed: adapted v1 rigs for M0–M2, `rig_release_sdk.py`
for M3–M4, the adapted soak program for M5. For M4 use a DC source on A0
and A2 and a 1 kHz sine shared by both to confirm the zero phase.

## 8. Effort and risk

| Item | Estimate | Risk |
| --- | --- | --- |
| Core and host tests | 2 weeks | Low |
| Clocks, TC, EVSYS, dual ADC + DMAC | 1 week | Medium-high: register-level, event routing is easy to get subtly wrong |
| GPIO DMAC capture, dual-bank join | 4 days | Medium |
| TinyUSB CDC | 2 days | Low |
| Validation M0–M6 | 1 week | |
| **Total** | **~6 weeks** | |
