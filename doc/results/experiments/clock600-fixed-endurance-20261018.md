---
type: result
title: 600 MHz Three-Hour Repeated Capture After USB Fix
created: 2026-10-18
tags: [firmware, reliability, temperature]
related: ['[[Clock600-Thermal-20261016]]', '[[Parser600-Investigation-20261017]]']
---

# 600 MHz three-hour repeated capture after USB fix

Status: **STOPPED**. Attempted 9 of 18 requested ten-minute captures; 8 passed.

This campaign restarts the eighteen-run request after the USB autoflush fix in `9e7fb90`. The original failed campaign remains separate. The exact archived `thingdaq-75ac69ba3e2bb588` image captures both 12-bit ADCs and all sixteen GPIO inputs at 1 MS/s, with normal ADC frames, standard Adler-32, 600 MHz CPU / 150 MHz IPG / 37.5 MHz ADC / 24 MHz PIT. Watchdog remains disabled.

Each job verifies START, active acquisition, STOP to IDLE, drain, final counters, parser integrity, and sample conservation using the unchanged independent validator. Die temperature is sampled before, approximately every ten seconds during capture, and after STOP. The existing 80 °C abort is retained. The campaign stops on the first failed or ambiguous job; no automatic submission retry.

The rig reflashes/resets between jobs. There is no intentional cooldown, but programming gaps mean this is three hours of requested acquisition across eighteen sessions, not an uninterrupted three-hour stream or proof of restart without reset. Earlier pre-fix forty-session testing covers repeated START/STOP without reflashing.

| Run | Before (°C) | After STOP (°C) | Peak sampled (°C) | Result |
| ---: | ---: | ---: | ---: | --- |
| 1 | 52.632 | 67.369 | 67.369 | PASS |
| 2 | 61.229 | 67.983 | 68.597 | PASS |
| 3 | 61.843 | 67.983 | 68.597 | PASS |
| 4 | 62.457 | 68.597 | 68.597 | PASS |
| 5 | 61.843 | 68.597 | 69.211 | PASS |
| 6 | 62.457 | 69.211 | 69.211 | PASS |
| 7 | 62.457 | 69.211 | 69.211 | PASS |
| 8 | 63.071 | 69.211 | 69.211 | PASS |
| 9 | 62.457 | unavailable | 68.597 | TEST_FAIL |

Campaign stopped: Run 9 failed; evidence preserved; no further runs submitted

## Scope and next work

Ambient temperature and heatsink configuration are not independently measured. These captures do not grade externally stimulated analog accuracy or GPIO edge fidelity, establish a worst-case temperature, or resolve the historical parser rejection. Final and peak readings are distinct.

Agreed order: establish reliability with this campaign; next evaluate and qualify larger ADC frames at 600 MHz; only then evaluate RLE with the successful larger-frame configuration. GPIO output is deferred. No frame-layout, compression, output, or SDK-default change is part of this campaign.

Full graded metrics, temperatures, provenance, job IDs, and artifact hashes are in [the machine-readable report](clock600-fixed-endurance-20261018.json). Raw jobs and the campaign script are retained under `doc/results/raw/clock600-fixed-endurance-20261018/`.
