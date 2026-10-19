---
type: report
title: Deferred GPIO RLE and ADC12 qualification
created: 2026-10-18
tags:
  - compression
  - firmware
  - qualification
related:
  - '[[deferred-codecs]]'
---

# Deferred GPIO RLE and ADC12 qualification — 2026-10-18

**For Bill:** 28/28 clean-source captures passed (4,396 checks), including 30 minutes with both codecs, 10 minutes with default GPIO RLE, and twenty same-boot START/STOP cells. No codec deadline/resource drops or parser discards; peak die temperature 65.527 °C. GPIO hybrid `-Os` RLE defaults on; ADC12 packing is optional and defaults off. No hardware changes were needed.

These are private experiment build selections, not yet SDK runtime options. The worker runs cooperatively after acquisition/USB work, with a 10 ms deadline; it is not a separate CPU/thread. Complete late blocks are dropped with counters and sequence-gap flags.

## Sixty-second comparisons

| Mode | Actual wire MB/s | GPIO acquisition CPU % | Codec elapsed % | ADC mean/max µs | GPIO mean/max µs |
|---|---:|---:|---:|---:|---:|
| raw | 6.071 | 15.73 | 0.00 | — | — |
| rle | 4.073 | 15.44 | 1.18 | — | 23.92 / 81.00 |
| adc | 5.071 | 15.19 | 5.47 | 55.34 / 90.00 | — |
| both | 3.073 | 14.92 | 6.76 | 55.31 / 80.00 | 26.16 / 79.00 |

Both codecs reduced measured wire bytes per capture second by 49.4% relative to raw. ADC frames shrink from 4,096 to 3,084 bytes (1,012 pairs unchanged). GPIO retains 2,024 samples per frame and uses RLE only when smaller; application frame count is unchanged. USB packet/transaction counts were not measured.

Codec time includes sizing, encoding/packing, checksum/copy and interrupt preemption, sampled at 1 µs clock resolution. The GPIO acquisition counter excludes deferred work. Neither measure is total CPU utilization or idle percentage. Wire rates are normalized by captured logical time, including bounded startup/drain data. Electrically unstimulated GPIO was highly compressible; these results do not establish fidelity for an externally driven waveform.

## Temperature and sustained runs

| Capture | Duration s | Before °C | After °C | Peak °C | Result |
|---|---:|---:|---:|---:|---|
| raw-comparison 1 | 60 | 39.123 | 49.562 | 49.562 | PASS |
| rle-comparison 1 | 60 | 47.720 | 54.474 | 54.474 | PASS |
| adc-comparison 1 | 60 | 49.562 | 56.316 | 56.316 | PASS |
| both-comparison 1 | 60 | 52.632 | 57.544 | 57.544 | PASS |
| both-endurance-01 1 | 600 | 44.650 | 64.299 | 64.299 | PASS |
| both-endurance-02 1 | 600 | 56.316 | 65.527 | 65.527 | PASS |
| both-endurance-03 1 | 600 | 45.878 | 64.913 | 64.913 | PASS |
| both-restarts 1 | 5 | 56.930 | 58.158 | 58.158 | PASS |
| both-restarts 2 | 5 | 58.772 | 58.772 | 58.772 | PASS |
| both-restarts 3 | 5 | 58.772 | 59.386 | 59.386 | PASS |
| both-restarts 4 | 5 | 60.000 | 60.615 | 60.615 | PASS |
| both-restarts 5 | 5 | 60.000 | 60.000 | 60.000 | PASS |
| both-restarts 6 | 5 | 60.615 | 61.229 | 61.229 | PASS |
| both-restarts 7 | 5 | 60.615 | 61.229 | 61.229 | PASS |
| both-restarts 8 | 5 | 61.229 | 61.229 | 61.229 | PASS |
| both-restarts 9 | 5 | 61.229 | 61.843 | 61.843 | PASS |
| both-restarts 10 | 5 | 61.843 | 61.843 | 61.843 | PASS |
| both-restarts 11 | 5 | 61.843 | 61.843 | 61.843 | PASS |
| both-restarts 12 | 5 | 61.843 | 61.843 | 61.843 | PASS |
| both-restarts 13 | 5 | 62.457 | 62.457 | 62.457 | PASS |
| both-restarts 14 | 5 | 62.457 | 62.457 | 62.457 | PASS |
| both-restarts 15 | 5 | 62.457 | 62.457 | 62.457 | PASS |
| both-restarts 16 | 5 | 63.071 | 63.071 | 63.071 | PASS |
| both-restarts 17 | 5 | 63.071 | 63.071 | 63.071 | PASS |
| both-restarts 18 | 5 | 63.685 | 63.071 | 63.685 | PASS |
| both-restarts 19 | 5 | 63.071 | 63.685 | 63.685 | PASS |
| both-restarts 20 | 5 | 63.685 | 63.685 | 63.685 | PASS |
| rle-endurance 1 | 600 | 57.544 | 65.527 | 65.527 | PASS |

The three combined endurance cells used identical firmware in separate ten-minute jobs because the runner enforces a 780-second job budget; each job reflashes. Twenty five-second cells separately exercise START/STOP without reflashing. Comparisons also reflash between modes and begin at different temperatures; their thermal differences are not a controlled power comparison. All runs capture both 12-bit ADCs and sixteen digital inputs at 1 MHz, 600 MHz core, Adler-32, unchanged 80 °C cutoff and disabled watchdog. GPIO outputs remain deferred.

## Same-boot START/STOP timing

| Host-observed interval | Minimum ms | Maximum ms |
|---|---:|---:|
| START reply | 20.809 | 23.180 |
| START to first validated ADC frame | 20.828 | 23.255 |
| START to first validated GPIO frame | 20.869 | 23.400 |
| STOP reply | 20.646 | 22.295 |
| STOP to drained | 121.015 | 123.983 |
| STOP to final IDLE status | 161.488 | 165.931 |
| Repeated STOP reply | 20.156 | 20.877 |

These twenty cycles share one boot. Drain timing includes the required 100 ms quiet interval; final IDLE adds a STATUS round trip. Measurements include host scheduling/USB latency and do not isolate firmware execution time. All cycles passed drain, IDLE and restart checks; this is not a forced-stall recovery test.

## Retained failures and corrections

The initial packed-ADC pilot exposed a missing USB transport shape guard. The transport dropped packed ADC views, causing the host time-coverage-skew rejection. An explicit packed shape guard and a test through actual CdcTransport short writes correct it.

Two subsequent pilots timed out. A separate diagnostic reproduction retained a CRC-valid ARM memory fault (IPSR 4, CFSR 0x82, PC 0x6000f67a, address 0x75e6f004). The exact ELF maps the fault to `validFrameSize`: `evictCompleteBuffer` passed a copied record, and validation derived a storage index by subtracting that copy’s address from the live array. Validation now takes an explicit checked index. The deterministic pressure test fails before and passes after the fix. The two earlier timeouts are consistent with this defect but lack their own fault records.

The original host ADC unpack loop cost 0.332 s per 1.012 million pairs on the rig host. Independent bounded byte-lane decoding costs 0.00948 s (about 35× faster), reducing host backpressure. The firmware eviction fix remains necessary regardless of host speed. All four rejected captures remain FAIL in the accompanying JSON; none is relabeled after a retry.

The local orchestration process disappeared during the second endurance job. Its terminal remote result was recovered and graded PASS with the unchanged classifier; that capture was not resubmitted. Remaining jobs resumed from the completed ledger. One early build failed on a wrong report-field name and was never flashed. The first endurance orchestration exceeded the existing service-duration guard and was rejected before submission; it was split into bounded jobs without relaxing that guard. One HTTP 503 preflight occurred before submission; the retained log confirms no job was started. Subsequent upload retries were handled by the existing rig uploader and every accepted capture independently checked firmware identity.

## Reproduction and limits

Build: `.venv/bin/python firmware/tools/build_input_experiment.py --cpu-mhz 600 --release-fixed-1mhz --large-adc-frame --deferred-codecs`. Add `--no-rle` and/or `--adc-pack12` for the four combinations. Use the existing `run_input_isolation.py` with `--gpio-rle --frame-experiment --temperature --lifecycle-checks --adc-phase`; manifests determine actual codec selections.

All accepted images were built from clean `fc0c889c11d16d502b6416b619e313b340c8b9d8`. Raw evidence, manifests, frozen runner programs, failure fault ELF/disassembly, orchestration and logs are retained under `doc/results/raw/deferred-codecs-20261018/`. The accompanying JSON records job IDs, image hashes, exact counters, thermal samples and failure classifications.

Host validation: 83 tests, 1,010 subtests, three intentionally unsupported selection skips; lint/format checks passed. All four target builds passed unchanged memory/ownership gates. Combined image free RAM1 local/stack space is 33,696 bytes (32,768 minimum); RAM2 heap headroom is 4,096 bytes (unchanged minimum). No pool repartitioning or extra full-size buffer allocation.

Deadline/late-completion, wraparound, blocked predecessor, scratch exhaustion and eviction behavior are deliberately exercised in portable tests. Physical acceptance requires zero drops; forced hardware starvation is not part of this campaign. Cross-block RLE output aggregation, public SDK integration, external stimulus and GPIO output remain outside this change. The board is left on the qualified RLE-only default image after the final run.

Implementation details: [deferred codecs](../../research/deferred-codecs.md).
