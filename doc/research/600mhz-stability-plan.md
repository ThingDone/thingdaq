---
type: research
title: 600 MHz Stability and Input Throughput Plan
created: 2026-10-18
tags: [firmware, reliability, temperature]
related: []
---

# 600 MHz stability and input throughput

Bill authorized this sequence on 2026-10-18, including diagnosing and fixing
issues without stopping for renewed approval. This supersedes the older
clock/compression/output integration proposal for current work.

1. Complete eighteen consecutive ten-minute captures at 600 MHz, both 12-bit
   ADCs at 1 MS/s each and all sixteen GPIO inputs at 1 MHz. Record before,
   after STOP, and peak die temperatures for every run; verify parser integrity,
   loss/conservation, START/STOP, and final IDLE. Preserve failed campaigns.
   The rig resets between jobs; separately exercise START/STOP without reset.
2. Qualify the existing opt-in larger ADC layout at 600 MHz: 1,012 pairs in
   4,096-byte frames instead of 506 pairs in 2,072-byte frames. Compare measured
   overhead and retention, run sustained captures and repeated START/STOP.
   Keep sample rates, ADC resolution, GPIO layout, and Adler-32 unchanged.
3. Only after larger ADC frames pass, adapt the existing RLE implementation
   for GPIO only, with RAW fallback for incompressible input. Verify decoded
   logical equality, timestamps, conservation, actual wire savings, CPU cost,
   and sustained capture. ADC remains RAW. Keep experimental wire changes
   explicit; do not silently make incompatible public SDK claims.
4. GPIO output is deferred and excluded from this work. No output pin driving
   or auxiliary-output integration is planned.

Current blocker: the USB-fixed campaign passed eight ten-minute captures,
then run nine aborted on five temperature NOT_READY responses within 86 ms.
The parser reported zero errors or discarded bytes. The host's readiness
retry policy is being corrected and requalified before a fresh campaign.
The 80 °C campaign abort and firmware thermal protection remain in force.
