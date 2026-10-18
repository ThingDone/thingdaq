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
   After endurance, qualify STOP/restart timing on the same image before
   performance changes: command response, drain, final IDLE, idempotent STOP,
   and repeated reconfiguration/START without reflashing. Preserve exact
   conservation and the existing command deadlines. This priority was added
   by the overnight instruction on 2026-10-18.
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

Current status: all eighteen ten-minute endurance captures passed, with
2,358 checks, 66,143,843,828 received bytes, zero parser errors or discarded
bytes, and a maximum sampled die temperature of 69.211 °C. The
[final endurance report](../results/experiments/clock600-ready-endurance-20261018.md)
includes all eighteen before/after/peak temperatures and earlier failure
classifications; committed and pushed as `46fb05a`. Earlier failures remain
preserved. The 80 °C campaign abort and firmware thermal protection remain
in force.

[STOP/restart qualification](../results/experiments/stop-recovery600-20261018.md)
also passed: 42 capture cells, 6,132 checks, and forty cycles without reflash
in the sustained restart job, committed and pushed as `d8162b3`. Maximum
host-observed STOP response was 21.528 ms, drain completion 123.380 ms,
and final-IDLE observation 247.440 ms. These include host/harness overhead;
injected stalls, disconnects, and fault-state recovery remain ungraded.

The larger-frame candidate `thingdaq-358337de6b642106` is built at 600 MHz;
normal resource gates and 22 focused local tests pass. Its immutable image is
archived under `doc/results/raw/large-adc600-20261018/image/`. Hardware
qualification can now proceed through a 60-second smoke, three 600-second
captures, and four START/STOP cycles without reflash. Evidence is retained
under the same raw directory; RLE remains gated on all these checks passing.

Same-agent Maestro Cue continuation `teensy-600mhz-qualification` checks every
11 minutes, diagnoses failures, and advances these gates. It is removed when
this finite plan completes. The detailed local continuation record is
`.maestro/600mhz-continuation.md`.
