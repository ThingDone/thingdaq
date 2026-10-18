---
type: result
title: 600 MHz Three-Hour Repeated Capture Campaign
created: 2026-10-17
tags: [firmware, reliability, temperature]
related: ['[[Clock600-Thermal-20261016]]', '[[Parser600-Investigation-20261017]]']
---

# 600 MHz three-hour repeated capture campaign

[Follow-up investigation](usb600-autoflush-20261018.md) identifies and reproduces a firmware USB autoflush race matching the retained corruption. The failed capture below remains failed.

Status: **STOPPED**. Attempted 1 of 18 requested ten-minute captures; **zero full ten-minute captures completed**. Run 1 failed after approximately 70 seconds, and runs 2–18 were not started.

The host recorded two checksum rejections and discarded 2,120 bytes before detecting an ADC sequence gap: expected frame 138621 at tick 561137808, received frame 138622 at tick 561141856. Both rejected byte samples are retained in the JSON evidence. The capture alone did not establish the initiating defect; the follow-up above identifies and reproduces the firmware USB transmit race. The firmware failure snapshot reports zero ADC DMA errors and zero ADC raw-ring overruns. Cleanup STOP returned IDLE; no post-STOP temperature was collected on the failure path. The highest sampled temperature was 48.948 °C, below the 80 °C abort threshold.

The exact archived `thingdaq-6c8a85596662e413` image captures both 12-bit ADCs and all sixteen GPIO inputs at 1 MS/s, with normal ADC frames, standard Adler-32, 600 MHz CPU / 150 MHz IPG / 37.5 MHz ADC / 24 MHz PIT. Watchdog remains disabled.

Each job verifies START, active acquisition, STOP to IDLE, drain, final counters, parser integrity, and sample conservation using the unchanged independent validator. Die temperature is sampled before, approximately every ten seconds during capture, and after STOP. The existing 80 °C abort is retained. The campaign stops on the first failed or ambiguous job; no automatic submission retry.

The rig reflashes/resets between jobs. There is no intentional cooldown, but programming gaps mean this is three hours of requested acquisition across eighteen sessions, not an uninterrupted three-hour stream or proof of restart without reset. Earlier forty-session testing covers repeated START/STOP without reflashing.

| Run | Before (°C) | After STOP (°C) | Peak sampled (°C) | Result |
| ---: | ---: | ---: | ---: | --- |
| 1 | 36.667 | unavailable | 48.948 | TEST_FAIL |

Campaign stopped: Run 1 failed; evidence preserved; no further runs submitted

## Scope and next work

Ambient temperature and heatsink configuration are not independently measured. These captures do not grade externally stimulated analog accuracy or GPIO edge fidelity, establish a worst-case temperature, or resolve the historical parser rejection. Final and peak readings are distinct.

Agreed order: establish reliability with this campaign; next evaluate and qualify larger ADC frames at 600 MHz; only then evaluate RLE with the successful larger-frame configuration. GPIO output is deferred. No frame-layout, compression, output, or SDK-default change is part of this campaign.

Full graded metrics, temperatures, provenance, job IDs, and artifact hashes are in [the machine-readable report](clock600-endurance-20261017.json). Raw jobs and the campaign script are retained under `doc/results/raw/clock600-endurance-20261017/`.
