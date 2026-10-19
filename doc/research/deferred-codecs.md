# Deferred input codecs

This private 600 MHz candidate adds cooperative low-priority processing for
sixteen-bit digital inputs and optional lossless 12-bit ADC packing. It builds
on the qualified large-ADC-frame/ADC_ETC request baseline. GPIO outputs remain
deferred. Public SDK/protocol promotion is outside this experiment.

Build with `firmware/tools/build_input_experiment.py --cpu-mhz 600
--release-fixed-1mhz --large-adc-frame --deferred-codecs`. GPIO RLE defaults on;
`--no-rle` disables it. ADC packing defaults off; `--adc-pack12` enables it.
These are explicit build selections, salted into identity and frozen in the
manifest; they are not yet SDK configuration fields. All four combinations
retain the same ADC request routing, rates, pool size and diagnostic contract.

## Ownership and scheduling

`finishFill` constructs the raw frame and invalidates the producer lease.
A complete deferred page stays FILLING in its source FIFO; acquisition owns
no DMA lease on its behalf. Promotion cannot publish it until the worker
finishes. Selected-byte/framed counters advance only on publication, so live
wire accounting never rewrites earlier cumulative counters. No new full-size
allocation or ring is added to the existing 200-page pool.

`FirmwareRuntime::service` invokes one codec block after the two bounded
acquisition/USB visits, only if no acquisition work limit, command or physical
fault is pending. Interrupts stay enabled. This is a cooperative slack
opportunity, not a separate thread or a promise that the entire CPU is idle.
A busy next iteration immediately returns to acquisition and control work.

The deadline is 10 ms from cooperative admission, measured on the existing
8 MHz timestamp clock (1 us hardware resolution). It is checked before and
after encoding, including when no encoding budget is granted. Pending pages
behind READY predecessors remain visible to expiry even when USB is blocked.
Expired pages are dropped, counted, and represented by the next sequence gap
and GAP_BEFORE/OVERRUN_BEFORE flags. An incompressible GPIO block selects RAW;
a compressible block without a scratch page is a separately counted resource
drop. STOP retains complete deferred pages for bounded drain/expiry, cancels
only partial construction, and START waits for full quiescence.

## Codecs and wire formats

GPIO uses the hybrid `-Os` strategy from the isolated benchmark: the existing
early RAW sizing pass, direct constant-run emission, and a transition-span
encoder for multiple runs. Source remains immutable while a FREE packet page
holds scratch output. Only a complete checksummed smaller result replaces it.
Private version 0x82, logical sample count and original timestamps are unchanged.
This integration retains generic bounds checks; integrated timing is measured
separately rather than assuming the isolated benchmark timings transfer.

ADC packing validates all 12-bit values before changing any bytes, then packs
in-place: two little-endian u16 values A/B become `A[7:0]`,
`B[3:0]:A[11:8]`, `B[11:4]`. The fixed 1,012-pair payload shrinks from 4,048
to 3,036 bytes; complete frames shrink from 4,096 to 3,084 bytes. Private version
0x83 distinguishes packed frames. Logical counts, timestamps and checksums
remain exact. Ordinary v2 validators reject the private version; the explicit
experiment validator independently expands it before normal acquisition checks.

## Measurement and gates

Private STATUS requests 0xFDEC0001–0006 reuse the existing twelve-byte
experiment diagnostic suffix, without increasing response length. ADC then
GPIO each expose completed/RAW counts, deadline/resource drops, total worker
elapsed ticks, maximum worker ticks, maximum observed queue age, and deadline.
Work timing includes codec/checksum/copy and any interrupt preemption; it is
not total CPU utilization. Ordinary STATUS and the ADC fault pages retain their
existing meaning. The runner reads diagnostics only after STOP and checks zero
drops and completion counts against final pipeline counts.

Portable gates cover all four selections through seven-byte USB short writes
and an independent Python decoder, STOP/drain/restart, exact deadline boundary,
32-bit timestamp wrap, late completion rejection, USB-blocked predecessors,
scratch exhaustion, invalid ADC high bits, and producer lease invalidation.
Physical gates require both ADCs and all sixteen GPIO inputs at 1 MHz, strict
continuity/checksum/conservation, temperature, STOP/IDLE and retained failures.
The inputs are electrically unstimulated; known-data portable tests establish
codec fidelity, while physical captures establish acquisition/transport behavior.

Clean-source qualification passed 28 captures and 4,396 checks: all four
60-second mode comparisons, three ten-minute combined-codec captures, twenty
same-boot START/STOP cells, and a ten-minute default RLE-only capture. No codec
deadline/resource drops or parser discards were observed; peak die temperature
was 65.527 degrees C. Both codecs reduced wire traffic from 6.071 to 3.073 MB/s
on these unstimulated inputs. The ten-minute jobs reflash separately; only the
twenty restart cells share one boot. Full counters, per-capture temperatures,
retained failures and provenance are in the
[qualification report](../results/experiments/deferred-codecs-20261018.md).

The initial pilot exposed a missing USB view guard for packed ADC frames; that
guard and a real-transport regression test were added. Two later pilots timed
out with no parser corruption. A diagnostic reproduction retained a CRC-valid
Cortex-M7 fault record: IPSR=4, CFSR=0x82, PC=0x6000f67a, fault address
0x75e6f004. The exact ELF maps that PC to `validFrameSize` reading a frame header.
`evictCompleteBuffer` passed a copied buffer record, while `validFrameSize`
subtracted its address from the live record array to locate storage. That is
undefined pointer arithmetic and an invalid access during compressed-frame
pressure eviction. The validator now takes an explicit checked buffer index.
A deterministic portable pressure test fails before the change and passes after.
The historical timeouts are consistent with this defect, but only the diagnostic
reproduction retained a fault record and establishes the exact mechanism.

The first Python ADC decoder used a per-pair loop (0.332 seconds per 1.012 million
pairs on the rig host). Bounded byte-lane operations reduce that to 0.00948
seconds, independently checked against boundary and random known values.
This reduces host backpressure; it is not a substitute for the firmware eviction
fix. Wire checksum, continuity and conservation gates remain unchanged.

Requests 0xFDEC0007–000A read the pinned core's reserved eleven-word persistent
ARM fault record without clearing it. On a failed deferred-codec run, the host
allows the core's eight-second reboot, reconnects only to the expected hardware
serial, issues STOP and retains this diagnostic readback. The original run stays
FAIL. No automatic retry is converted into acceptance.
