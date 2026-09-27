---
type: result
title: Current Watchdog Baseline and Separate SDK Reproduction
created: 2026-09-27
tags:
  - thingdaq
  - watchdog
  - validation
related:
  - '[[Firmware-Runtime-Hardening]]'
  - '[[Release-1.1.0]]'
---

# Current watchdog baseline and SDK CPU comparison

The watchdog preflight failure is fixed. The original initialization deadline
expired before hardware acknowledged a successfully written configuration;
refreshes were then withheld from an enabled watchdog. The repaired adapter
passed a deliberate main-loop stall/reset/reconnect test. The current firmware
passed a **600-second combined16 independent wire baseline with two cores
allocated**, plus the four previously healthy SDK modes. Combined16 SDK
captures also passed with adequate CPU allocation.

The separate SDK reproduction found firmware USB queue loss at the normal
0.5-core quota, both from a cold combined 16-input start and after the original
five-mode sequence. Allocating two cores passed a 60-second cold capture and seven
20-second cells, including 8 → 16 → 8 → 16 combined-input transitions. However,
a subsequent planned 600-second SDK capture **failed after 50.084 seconds with
zero CPU throttling**: a block timeout, two firmware ADC DMA error events and
an IDLE firmware state. Adequate CPU allocation does not eliminate every
combined16 failure. A subsequent standard-collector repeat passed 600 seconds,
so this adequate-CPU failure is intermittent; sustained SDK operation remains
unqualified.

Historical checksum/parser rejections were **not reproduced**; their cause
remains unresolved. The adequate-CPU failure below is a distinct observed
failure mode, not proof of the cause of those historical rejections.

## Frozen production image

| Item | Value |
| --- | --- |
| Firmware source commit | `cb833a5fcd80ae8f51d8bf524d3d5101bf92fb71` (firmware inputs clean) |
| Build ID | `thingdaq-b0fafcaf165da96b` |
| HEX SHA-256 | `9be428933c8d2cfb962e339c7d1f19272fff51b77c5de333ceab8320682cbbd6` |
| Target | Teensy 4.0, USB serial `20428100`, 450 MHz, fixed 1 MHz ADC/GPIO |
| Toolchain | Teensy core 1.62.0; Arm GNU 15.2.1; standard `-O2` |
| RAM1 locals/stack | 34,464 bytes; 34,432 monitored after MPU guard exclusion |
| RAM2 heap margin | 4,096 bytes |

The SDK comparisons and independent wire soak use this identical frozen HEX.
The earlier four-mode watchdog control run has the same firmware source/build
ID but an earlier build timestamp and a separately archived HEX hash. No SDK
library or checksum implementation was changed for this campaign. The sorted
SDK source-file hash inventory is identical in every SDK comparison:
`bb923fdf3fc0aa9fac92b2acfce91f3dbf2f8cb27e59dde57092fc184809dbf2`.
ZIP archive hashes differ because their entry timestamps differ; the
uncompressed Python source contents match exactly.

## Watchdog diagnosis and recovery

Current `main` at `e2cfbee` reproduced the preflight failure before acquisition,
job `f73d888a-1812-4bf8-800f-97a363d5dbee`. Original build
`thingdaq-6f2c6b332efc9280` reported watchdog disabled, timeout zero and reset
cause `0x1`. No acquisition cell ran.

A dedicated non-driving sketch using the actual adapter read CS `0x2520`
before initialization, `0x31a3` immediately after the failed call, and `0x35a3`
later. TOVAL was already 512. RCS, the configuration-success bit, arrived after
the original 100,000-poll deadline. Job
`23faba53-0f63-407a-a6e6-553172d33da3` retains that register evidence.

The bound is now 2,000,000 polls, still independent of DWT progress. The host
fake models delayed RCS and tests acknowledgment beyond the old bound.
Unlock/configuration failures, command width, interrupt masking and readback
checks remain enforced. Neither watchdog timeout nor acceptance was weakened.

The fixed adapter passed job `f8d87f59-512d-4f51-a5df-7f9a16ec0597`:

- Initialization acknowledged in 12,335,804 DWT cycles (27.413 ms).
- Healthy refreshes continued for more than the four-second timeout.
- Deliberately stalling main disconnected USB after 4.135 seconds.
- USB reconnected by 4.660 seconds, watchdog enabled, reset cause `0x80`.

The probe's printed `serial` is a raw OCOTP word; the fixed probe independently
checked public USB serial `20428100` on the host. This is dedicated
fault-injection evidence. On-device tests that stall DWT mid-diagnostic remain
outside this campaign.

## Production SDK results

| Job | Workload | CPU quota | Result |
| --- | --- | ---: | --- |
| `1760c794-e831-4817-ae9b-03bfdf23570a` | ADC, GPIO8, combined8, GPIO16; 15 s each | 0.5 | PASS; all watchdog/stack samples healthy |
| `6ccde963-02b7-4c11-92c4-db8aadfe9840` | Cold combined16, planned 60 s | 0.5 | FAIL at 0.885 s; firmware-origin ADC gap |
| `dc179cd7-833d-46c0-9ba0-25d55cb845fb` | Cold combined16, 60 s | 2.0 | PASS |
| `82209c47-6492-48c8-8ab7-2436cd967fba` | Original five cells, 5 s each | 0.5 | First four PASS; combined16 FAIL at 1.483 s |
| `dc300634-1597-4e8c-9c69-851f262c2e1d` | ADC, GPIO8, combined8, GPIO16, combined16, combined8, combined16; 20 s each | 2.0 | All seven PASS |
| `775fe2fc-d3db-45cc-8790-9775715ddff6` | Cold combined16, planned 600 s | 2.0 | FAIL at 50.084 s; block timeout and firmware ADC DMA errors |
| `5e5f2e3a-023e-4b75-a2e7-314bf43da1d0` | Cold combined16, standard collector, 600 s | 2.0 | PASS; intermittent failure did not recur |

The first failed snapshot had 28 packet-pressure evictions (21 ADC, 7 GPIO);
the transition failure snapshot had 253 (201 ADC, 52 GPIO). Both had zero raw
ring overruns, parser corruption and host block-queue drops. These snapshots
can include losses after the first gap that triggered strict failure. The
first gap itself was 19 ADC frames; the sequence failure first reported 74.
CPU throttling increased in both half-core failures.

Both short adequate-CPU jobs observed **zero throttled periods and microseconds**,
with affinity to all four host CPUs. Combined16 consumed about 0.66 CPU cores
on average, versus about 0.46 for combined8. The seven-cell run recorded
CPython 3.13.15 on Linux x86-64. Its 22 runtime-health samples and the cold
run's four samples all reported watchdog enabled, 4,000 ms timeout and reset
cause `0x1`; minimum free monitored stack was 27,856 bytes.

### Failure with adequate CPU

Job `775fe2fc-d3db-45cc-8790-9775715ddff6` retained `cpu.max = 200000 100000`,
affinity to all four CPUs, and zero throttled periods/microseconds both before
and after its failure. It used 33.107 process CPU seconds in 50.084 wall
seconds. `read_block(timeout=1)` raised `BlockTimeoutError` after the stream
ceased; the reader had an empty queue, no disconnect, no parser error and no
host queue loss. STATUS remained responsive and reported IDLE with
`adc_dma_error_events = 2`, no packet-pressure evictions, and bounded stop
tails of 45 ADC pairs and 543 GPIO samples.

The SDK does not issue STOP for a block-wait timeout; this STATUS sample was
taken before context-manager cleanup. The firmware runtime independently
recovers physical faults to IDLE. The ADC adapter's DMA error counter also
covers paired-pipeline alignment/service-budget failures, so the two events do
not identify a physical DMA bus error or the exact triggering branch. Raw
DMA/pipeline register state was not captured. This is firmware-side fault
evidence encountered through the SDK workload, not a proven SDK parser bug.

This run had a bounded on-error hook to retain up to four rejected frame byte
sequences while calling the original parser error handler. It changes no
successful-frame path or acceptance rule; an offline corruption/recovery test
verified its behavior. The hook never fired (`rejected_frames = []`).

The repeat using the unmodified standard collector, job
`5e5f2e3a-023e-4b75-a2e7-314bf43da1d0`, passed 600 seconds and received
600,002,656 ADC pairs and 600,002,656 GPIO samples. It decoded 1,482,276 frames
from 3,671,235,460 bytes with zero corruption, discarded bytes or observed loss.
Process CPU was 401.420 seconds (about 0.669 cores). CPU throttling deltas were
zero; the pre-existing 4,861 us counter value did not change. All four health
samples showed watchdog enabled, reset cause `0x1`, and at least 27,856 bytes
of free stack. The failed run began at 51.404 °C; the repeat began at 44.036 °C
and ended at 55.088 °C. No temperature causality is established.

The passing repeat demonstrates that the failure is intermittent, not resolved.
The next fault investigation needs ADC pairing/service-failure branch and
register snapshots; these runs do not isolate that trigger.

One additional diagnostic attempted to continue reading after strict gap
exceptions at half a core. It observed three gap exceptions before the SDK's
strict cleanup left the device IDLE, ending after 1.067 s. It is retained as a
failed diagnostic, not a 20-second capture or a relaxed acceptance pass. Its
parser also recorded zero corruption.

The service default remains 0.5 cores. A campaign controller matched only its
own job's `/storage` mount to the returned test ID, recorded Docker quota
before/after, and temporarily set that container's quota to 200,000 us per
100,000 us period for the adequate-CPU runs. Submitted programs waited before
opening serial and asserted exact `cpu.max`. CPU counters were recorded before
and after acquisition. The service configuration and unrelated containers
were not changed; job containers are removed by normal service cleanup.

## Independent wire baseline

The first 600-second combined16 wire attempt at the ordinary 0.5-core quota
failed at approximately 350.57 seconds of stream time, job
`5c5e293d-5829-40cb-a020-d6600b51a305`. It expected ADC sequence 692820 at tick
2804535360, but received sequence 692821 at tick 2804539408 without a loss
flag. The failure STATUS reported no firmware loss/error counters, and STOP
returned IDLE. This is a failed long baseline, not a watchdog reset or a
passing soak. The original collector did not snapshot host parser counters
before cleanup, so the evidence cannot distinguish a rejected/corrupt frame
from a complete frame lost in transport.

The collector now retains parser counters and stream totals at the first
failure, plus the already available failure STATUS, before cleanup changes
those observations. The repeat with two cores allocated **passed 600.008 s**,
job `b11e3c2f-d98f-4c87-a65c-dceafa67ed4f`, using the same frozen production HEX
and unchanged acceptance gates: 131 checks, no failures, no parser/stream loss,
matched paired-bank conservation and clean STOP.

| Wire baseline measurement | Result |
| --- | ---: |
| ADC pair rate | 999,999.755 pairs/s |
| GPIO rate | 1,000,000.598 samples/s |
| Accepted ADC / GPIO frames | 1,186,321 / 296,580 |
| Paired samples captured, joined and transmitted | 600,277,920 each |
| STATUS observations / p99 latency | 1,201 / 11.02 ms |
| Maximum host receive gap | 20.80 ms |
| Packet ready / transmit high water | 3 / 7 |
| GPIO processing CPU | 17.06% |
| Host peak RSS growth | 0 bytes |
| Bounded STOP tails, ADC pairs / GPIO samples | 422 / 1,023 |
| Die temperature range | 44.036–55.088 °C |

The wire repeat's CPU receipt records the two-core quota. A mid-run snapshot
had one throttled period totaling 22,246 us, unchanged in a later observation;
its timing relative to initial quota adjustment was not captured. The SDK
comparisons independently retain before/after CPU deltas. This passing baseline
does **not** turn the failed half-core soak into a pass.

## Local validation

The initial broad run exposed allocation tracing leaking out of the accelerated
soak tests, slowing later SDK performance checks. A direct reproduction showed
`tracemalloc` false before those tests and true after them. Test cleanup now
restores the caller's tracing state. Running those tests followed immediately
by the performance tests passes: nine tests and five subtests, tracing false
before and after. Isolated performance tests also pass on both untouched
`e2cfbee` and current code; no performance threshold was lowered.

A complete validation uses an isolated worktree containing only tracked files
and these changes. This keeps the user's pre-existing untracked
`doc/results/firmware-analysis-2026-09-12.md` out of the documentation scan;
that file lacks required YAML and was left untouched. The suites pass in
separate processes: **227 firmware tests / 836 subtests**, and **384 SDK tests /
15,535 subtests**. One historical clock-evidence check skips in the clean
checkout because its ignored campaign artifacts are absent; it passed in the
original workspace run. A joint run after the tracing fix still narrowly
missed a wall-time paced-stream threshold under workstation load (two Blender
jobs plus a busy Python process); the unchanged check passes in the standalone
SDK suite. These failed joint-run logs are retained. Target build/memory gates,
focused watchdog/runner tests, Ruff and whitespace checks pass.

## Reproduction and retained evidence

Build current firmware with `python3 firmware/tools/build_firmware.py`. At the
rig's default quota, isolate the SDK workload using:

```bash
python3 firmware/tools/run_input_isolation.py \
  --worktree . \
  --build-dir firmware/build/teensy.avr.teensy40.usb_serial.speed_450.opt_o2std \
  --evidence-dir doc/results/raw/watchdog-sdk-next \
  --case INPUT_COMBINED --profile 4 --seconds 60 \
  --host-api --runtime-health --sdk-cases combined16 \
  --service http://192.168.150.14:5000
```

For the wire baseline, omit the three SDK options, select `--seconds 600`,
and add `--temperature`. Each submission needs a new evidence directory.
The CPU controller and exact submitted programs are retained in the raw
campaign directory, including the pre-acquisition quota assertion and
job-specific Docker allocation receipt. Credentials are read from the private
key file and are never included in evidence.

[Machine-readable evidence](watchdog-sdk-20260927-evidence.json) retains job IDs,
source/image/program hashes, CPU deltas, runtime health and failure counters.
Full replies, programs, HEX/ELF files and manifests are under ignored
`doc/results/raw/watchdog-sdk-20260927/`; local validation logs are under
`firmware/build/`. Three early programming timeouts are retained as
infrastructure failures, separate from acquisition results. No simultaneous
board jobs or retries of ambiguous submissions were used. Final service
postflight was healthy, normal mode, queue depth zero, with no running job
containers. The last programmed image is the fixed production HEX above;
temporary CPU allocations ended with their containers.

There was no external electrical stimulus. This campaign does not measure
analog accuracy, external GPIO transition fidelity or pad-level simultaneity.

The [NXP RT1060 reference manual, rev. 3](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf),
sections 58.3.5 and 58.5.1.2, describes clock-transition delay and the RCS
acknowledgment. The register probe establishes this target's observed timing.
