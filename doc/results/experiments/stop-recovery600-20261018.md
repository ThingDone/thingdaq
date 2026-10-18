---
type: result
title: 600 MHz STOP and Restart Timing
created: 2026-10-18
tags: [firmware, reliability, timing]
related: []
---

# 600 MHz STOP and restart timing

**For Bill:** **PASS**, 42 capture cells and 6,132 checks on the same USB-guarded 600 MHz firmware. The forty-cycle job restarted both ADCs and all sixteen GPIO inputs without reflashing, checked idempotent STOP, and reconciled all captured data.

| Host-observed measurement | Count | Median (ms) | Maximum (ms) |
| --- | ---: | ---: | ---: |
| configure_response_seconds | 42 | 20.761 | 20.862 |
| start_response_seconds | 42 | 13.426 | 13.806 |
| stop_response_seconds | 42 | 21.341 | 21.528 |
| stop_to_drained_seconds | 42 | 123.028 | 123.380 |
| stop_to_final_idle_status_seconds | 42 | 164.828 | 247.440 |
| idempotent_stop_response_seconds | 42 | 20.754 | 21.217 |
| start_to_first_validated_adc_seconds | 42 | 13.657 | 14.170 |
| start_to_first_validated_gpio_seconds | 42 | 13.899 | 14.524 |
| stop_to_next_both_streams_including_harness | 40 | 638.045 | 720.409 |

All ordinary command responses retain the existing 250 ms acceptance limit. The drain measurement includes the required 100 ms quiet interval. Final-IDLE timing also includes the post-STOP temperature query. First-data timings are host validation times, not hardware trigger latency. Cross-cycle recovery includes serial reopen, startup synchronization, temperature queries and configuration; it is not an intrinsic firmware re-arm time.

This qualifies ordinary STOP/IDLE/reconfigure/START and idempotent STOP. Injected host stalls, cable disconnects and fault-state recovery are not graded by this report.

Each job independently flashes the same image; no reset/reflash occurs between cells. No output pins are driven. Inputs are electrically unstimulated. Full counters, failures, per-cell timings, identities and hashes are in [the evidence](stop-recovery600-20261018.json).
