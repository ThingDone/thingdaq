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

[Larger ADC frame qualification](../results/experiments/large-adc600-20261018.md)
passed on immutable `thingdaq-358337de6b642106`: five jobs / eight cells,
including three ten-minute captures and four START/STOP cycles without reflash.
All 1,168 checks passed, with zero parser errors/discards and a 69.825 °C peak.
The report compares wire overhead, GPIO-processing CPU and queue high-water
against baseline without claiming total CPU improvement. GPIO-only RLE is now
the next authorized stage, using this larger-frame configuration as baseline.
The [opt-in implementation](../architecture/gpio-rle-experiment.md) passes local
codec/ownership/validator tests and target resource gates. Two failed RAM1
builds and the host START failure are preserved. After the host fix, smoke
and three ten-minute RLE captures passed (584 checks, 66.755 °C peak), but the
[restart gate failed](../results/experiments/gpio-rle600-dma-failure-20261018.md)
with ADC DMA pipeline errors. A reproduced interrupt-accounting race is fixed;
the original fault's exact ordering remains unproven. Fresh qualification of
the new firmware failed again in the fourth restart cell after seven passing
cells (1,022 checks). The [recurrence report](../results/experiments/gpio-rle600-dma-recurrence-20261018.md)
preserves all five jobs. A private first-fault diagnostic suffix now supports
short reproduction before further qualification; physical RLE remains pending.

Same-agent Maestro Cue continuation `teensy-600mhz-qualification` checks every
11 minutes, diagnoses failures, and advances these gates. It is removed when
this finite plan completes. The detailed local continuation record is
`.maestro/600mhz-continuation.md`.
