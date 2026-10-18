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
short reproduction, which [identified an equal-index wait timeout](../results/experiments/gpio-rle600-alignment-failure-20261018.md)
with a completed common buffer and no DMA hardware error. The handler now
processes only the common completed prefix within bounded skew/headroom.
Fresh reproduction and full qualification remain required; RLE is pending.
The next attempt [failed boot completion timing before acquisition](../results/experiments/gpio-rle600-boot-timing-failure-20261018.md).
Timer enable through first-DONE observation now executes in ITCM, avoiding
a flash-code interval before timestamp polling; timing tolerances remain
unchanged. That candidate passed eight restart cells and smoke, then
[failed the pipeline window guard](../results/experiments/gpio-rle600-window-failure-20261018.md)
with observed indices 3/1 and DMA_ES zero. The cause remains unresolved.
Failure-only TCD/descriptor detail is now retained and retrieved after STOP
through explicit private STATUS pages; acceptance limits remain unchanged.
Fresh diagnostic reproduction and qualification are required.

The first [descriptor diagnostic campaign](../results/experiments/gpio-rle600-detail-diagnostic-20261018.md)
passed eight restart cells and one ten-minute capture (1,314 checks,
64.299 °C peak, zero parser errors/discards). It did not reproduce the failure
and does not establish a fix. A bounded repeat increases restart coverage to
forty cells, followed by another ten-minute capture on the same image. It
[failed in the third restart cell](../results/experiments/gpio-rle600-descriptor-failure-20261018.md)
after two PASS cells (292 checks, 47.720 °C peak). Retained hardware addresses
confirm indices 3/1, while CPU-visible descriptor links/destinations match
expectations. The cause remains unresolved. The next diagnostic retains the
last two accepted progress observations to narrow when divergence begins;
full qualification and the final RLE report remain pending.
The [progress-history diagnostic](../results/experiments/gpio-rle600-history-diagnostic-20261018.md)
passed forty restart cells and one ten-minute capture: 5,986 checks,
67.983 °C peak, zero parser errors/discards. No fault history was triggered;
the instrumentation does not establish a correction. A bounded repeat on the
same immutable image will attempt to reproduce the unresolved divergence,
preserving all seven previous failed physical campaigns and two failed builds.

The [bounded history repeat](../results/experiments/gpio-rle600-history-repeat-20261018.md)
also passed forty restart cells and one ten-minute capture (5,986 checks,
67.983 °C peak, zero parser errors/discards). The intermittent divergence
remains unresolved; the diagnostic instrumentation is not a demonstrated fix.
The next bounded campaign uses the same image for three ten-minute captures
followed by forty restart cells, stopping on first failure. This expands
sustained coverage before restart stress without changing acceptance gates.
Full RLE qualification and the final comparison report remain pending.
The expanded [sustained diagnostic failed in its first capture](../results/experiments/gpio-rle600-history-failure-20261018.md)
after approximately four seconds; no later job was submitted. This eighth
physical failure retained indices 3/1 and two preceding accepted 2/1
observations, 607,280 cycles apart. RAM descriptor links match expectations;
the cause remains unresolved. The next diagnostic adds per-observation CITER
and start/end DWT plus fault-entry DWT and hardware counters, with unchanged
acceptance limits. A fresh forty-cycle restart test followed by one ten-minute
capture will collect this expanded record; no automatic full qualification or
finalizer follows. All failed evidence remains preserved.
The [counter diagnostic failed in its second restart cell](../results/experiments/gpio-rle600-counter-failure-20261018.md)
after one PASS (146 checks, 44.036 °C peak). The two preceding observations
imply an ADC0 lead of 2,021/2,022 samples despite read spans under one
microsecond. This narrows the investigation beyond long sequential-read
latency; the cause remains unproven. A controlled candidate disables DMA
channel preemption for ADC1 only in the private combined-input RLE image,
retaining all priorities, sample rates, deadlines and acceptance limits.
Fresh bounded restart and ten-minute tests will assess this hypothesis before
any full qualification. The ninth failed campaign remains preserved.
The [ADC1-preemption candidate failed in its third restart cell](../results/experiments/gpio-rle600-preemption-failure-20261018.md)
after two PASS cells (292 checks, 45.264 °C peak), with the same indices 3/1
and apparent sample lead. This tenth failure is preserved and the ineffective
ECP change is removed. The next diagnostic records eight earlier phase
checkpoints, alongside the last-two observations, to distinguish initial
offset, gradual drift and a later step. It uses a fresh bounded forty-cycle
restart and ten-minute campaign, with unchanged capture gates. Full RLE
qualification and its final report remain pending.

The [early-phase diagnostic passed](../results/experiments/gpio-rle600-phase-diagnostic-20261018.md)
forty restart cells and one ten-minute capture: 5,986 checks, 67.369 °C peak,
zero parser errors/discards. No failure record was triggered; the added
instrumentation does not establish a correction. The next bounded campaign
uses the same immutable image for three ten-minute captures followed by forty
restart cells, stopping on first failure. Decode the 96-word phase history if
triggered. All ten failed physical campaigns and both failed builds remain
preserved; full RLE qualification and its comparison report are pending.

Same-agent Maestro Cue continuation `teensy-600mhz-qualification` checks every
11 minutes, diagnoses failures, and advances these gates. It is removed when
this finite plan completes. The detailed local continuation record is
`.maestro/600mhz-continuation.md`.
