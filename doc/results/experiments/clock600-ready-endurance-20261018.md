---
type: result
title: 600 MHz Three-Hour Capture With Bounded Temperature Retries
created: 2026-10-18
tags: [firmware, reliability, temperature]
related: ['[[Clock600-Thermal-20261016]]', '[[Parser600-Investigation-20261017]]']
---

# 600 MHz three-hour repeated capture with bounded temperature retries

**For Bill:** 18/18 ten-minute captures passed; campaign **PASS**. Maximum sampled die temperature: **69.211 °C**. 0 parser errors, 0 discarded bytes, 0 retained rejection windows (NONE). 2,358 checks over 66,143,843,828 received bytes. Both ADCs and all 16 GPIO inputs ran at 1 MS/s with 600 MHz core.

Earlier failures remain separately classified: the original October 17 rejected bytes proved firmware USB corruption (24 new bytes lost, 72 stale bytes transmitted), fixed in `9e7fb90`. The subsequent campaign in `742249c` passed eight runs and stopped on temperature NOT_READY, with no parser rejections; host retry policy fixed in `8be8cce`. The October 16 isolated parser event remains unclassified because its rejected bytes were not retained.

Status: **PASS**. Attempted 18 of 18 requested ten-minute captures; 18 passed.

This campaign restarts the eighteen-run request after correcting the host temperature-readiness retry policy. Both previous failed campaigns remain separate. Firmware is unchanged from USB autoflush fix `9e7fb90`. The exact archived `thingdaq-75ac69ba3e2bb588` image captures both 12-bit ADCs and all sixteen GPIO inputs at 1 MS/s, with normal ADC frames, standard Adler-32, 600 MHz CPU / 150 MHz IPG / 37.5 MHz ADC / 24 MHz PIT. Watchdog remains disabled.

Each job verifies START, active acquisition, STOP to IDLE, drain, final counters, parser integrity, and sample conservation using the independent validator with a one-second readiness retry budget and varied retry spacing. Acquisition, checksum, loss, conservation, and thermal-limit checks are unchanged. Die temperature is sampled before, approximately every ten seconds during capture, and after STOP. The existing 80 °C abort is retained. The campaign stops on the first failed or ambiguous job; no automatic submission retry.

The rig reflashes/resets between jobs. There is no intentional cooldown, but programming gaps mean this is three hours of requested acquisition across eighteen sessions, not an uninterrupted three-hour stream or proof of restart without reset. The USB-fixed image separately passed two START/STOP cycles without reflashing; see usb600-autoflush-20261018.

| Run | Before (°C) | After STOP (°C) | Peak sampled (°C) | Result |
| ---: | ---: | ---: | ---: | --- |
| 1 | 43.422 | 66.755 | 66.755 | PASS |
| 2 | 60.615 | 67.983 | 68.597 | PASS |
| 3 | 62.457 | 68.597 | 68.597 | PASS |
| 4 | 61.843 | 68.597 | 69.211 | PASS |
| 5 | 62.457 | 68.597 | 69.211 | PASS |
| 6 | 63.071 | 68.597 | 69.211 | PASS |
| 7 | 62.457 | 68.597 | 69.211 | PASS |
| 8 | 62.457 | 68.597 | 69.211 | PASS |
| 9 | 62.457 | 69.211 | 69.211 | PASS |
| 10 | 63.071 | 69.211 | 69.211 | PASS |
| 11 | 63.071 | 68.597 | 69.211 | PASS |
| 12 | 62.457 | 68.597 | 69.211 | PASS |
| 13 | 62.457 | 68.597 | 69.211 | PASS |
| 14 | 62.457 | 68.597 | 69.211 | PASS |
| 15 | 62.457 | 69.211 | 69.211 | PASS |
| 16 | 62.457 | 68.597 | 69.211 | PASS |
| 17 | 62.457 | 69.211 | 69.211 | PASS |
| 18 | 63.071 | 68.597 | 69.211 | PASS |

## Scope and next work

Ambient temperature and heatsink configuration are not independently measured. These captures do not grade externally stimulated analog accuracy or GPIO edge fidelity, establish a worst-case temperature, or resolve the historical parser rejection. Final and peak readings are distinct.

Agreed order: establish reliability with this campaign; next evaluate and qualify larger ADC frames at 600 MHz; only then evaluate RLE with the successful larger-frame configuration. GPIO output is deferred. No frame-layout, compression, output, or SDK-default change is part of this campaign.

Full graded metrics, temperatures, provenance, job IDs, and artifact hashes are in [the machine-readable report](clock600-ready-endurance-20261018.json). Raw jobs and the campaign script are retained under `doc/results/raw/clock600-ready-endurance-20261018/`.
