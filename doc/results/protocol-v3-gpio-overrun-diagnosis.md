---
type: report
title: Public v3 GPIO overrun traced to host backpressure and packet eviction
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - qualification
  - host-backpressure
related:
  - '[[protocol-v3-dma-recovery]]'
  - '[[protocol-v3-dma-fault-site]]'
  - '[[watchdog-sdk-20260927]]'
---

# Responsible path established; runner resource correction required

**The same frozen candidate reproduced complete-packet eviction under a
half-core host quota. Its acquisition rings stayed healthy.** Allocating two
host CPU cores to one diagnostic job removed throttling, reduced transmit
high-water from 200 to seven frames, and passed the unchanged 60-second capture.
The evidence supports correcting qualification host-resource provisioning;
it does not justify changing acquisition, packet loss accounting, or gates.

The DONE-before-DREQ correction and its passing evidence in
[[protocol-v3-dma-recovery]] remain unchanged. This diagnosis completes only the
GPIO-overrun investigation. Canonical streaming remains **36/56 PASS, one FAIL,
19 NOT_RUN**; diagnostic jobs earn no replacement qualification credit.

## Identity and reconciliation

- Candidate SHA-256: `5d6df850bd97add629502c9126c42eb1483ee2bd05efb1c0b466c55e5a92c1c7`.
- HEX SHA-256: `f29d05970b5b49381f4efcd80e2b948e72a41b89a32edbfce6ca00c5fab8fdbf`.
- Build: `thingdaq-92950ec5f7156586`; Teensy 4.0 serial `20428100`; CPU fixed at 600 MHz.
- Tuple: `030001030104011000000c0040420f0040420f00`: combined physical ADC/GPIO16, RAW, 1 MHz each.
- Original job: `322b4ac0-309d-4d61-a625-d4ce41cbf104`, retained as FAIL.

The old controller was absent, its exclusive lock was available, and its
progress/log recorded the terminal failure. Saved inputs/results and remote
terminal status were reconciled before new submissions. Each new job has a
distinct saved submission tag and ID. All rig HTTP used current
`run_input_isolation.py`; no archived raw-evidence client was executed.
The three diagnostic controllers have exited. The adequate-CPU job's container
was removed by normal service cleanup; no service default or unrelated
container was changed.

## Retained failure and reproduction

The original gap was GPIO sequence 19,423, covering 2,016 samples / 4,032 bytes
at tick 313,254,144 (39.156768 seconds). The first retained STATUS, still
RUNNING, reported 194 pending frames and a transmit high-water of 200. Its final
STATUS reconciled one GPIO frame lost, zero ADC loss, and zero DMA, ETC, GPIO
hardware, raw-invariant, parser or transport errors. The host queue dropped
zero blocks. Original detailed raw-ring/eviction and CPU counters were not
captured; these facts alone did not establish the root cause.

All new probes retained the exact firmware, SDK, settings, capture duration,
thermal cutoff and acceptance checks. Host-only hooks measured read timing and
queried detailed legacy STATUS **after STOP**, adding no acquisition-time
commands. The second and third probes also sampled host resources at boundaries.

| Diagnostic job | Host quota | Outcome | TX high-water | Packet evictions | CPU throttling delta |
| --- | --- | --- | ---: | ---: | ---: |
| `9bd2bd3d-a7b6-46e4-bf64-8d985fce9179` | Service default; quota not sampled | PASS | 189 | 0 | Not measured |
| `d32cf7d4-3756-4834-8458-b9c5efccb1a2` | `50000 100000` (0.5 core) | FAIL | 200 | 7 | 441 periods / 9.959196 s |
| `4e475671-5925-4e12-908b-c93d8711053a` | `200000 100000` (2 cores) | PASS | 7 | 0 | 0 periods / 0 s |

The second probe failed on an ADC gap after about 49.7 seconds of source time.
Detailed STATUS attributed **four ADC frames and three GPIO frames** to eviction
after promotion: seven pool exhaustions, seven pressure evictions, and zero
capacity drops without an evictable frame. Both raw rings had zero overruns and
ready high-water one. DMA faults, parser errors and host queue drops were zero.
Thus the reproduced loss occurred after successful acquisition and framing,
while completed packets waited for USB consumption.

The adequate-CPU probe used the prior job-specific allocation procedure from
[[watchdog-sdk-20260927]], adapted to the current retained-job runner. It matched
only the accepted job's `/storage` mount, verified the resulting quota, and
asserted `cpu.max` before opening serial. A ten-second pre-serial allocation
window was added; acquisition itself remained 60 seconds. It captured
60,027,408 ADC pairs and 60,026,400 GPIO samples with zero complete-frame loss.
Boundary process CPU was 30.972 seconds over 61.327 wall seconds, exceeding a
half-core average allocation. Maximum time between host reads fell from the
first probe's 81.926 ms to 6.676 ms. Independent unchanged capture grading passed.

## Production-code reproduction

The diagnostic C++ harness reuses the fill/drain helpers from
`firmware/tests/v3_codec_pipeline_test.cpp` and links unchanged production
`packet_buffer_pipeline.cpp`, transport, protocol and checksum code. With the
candidate's 1,008-pair ADC and 2,016-sample GPIO frame sizes, it fills all 200
packet buffers at the 2:1 frame-production ratio and pins the oldest ADC frame
as partially transmitted. The next producer admission evicts exactly one
complete GPIO frame: 2,016 samples / 4,032 bytes. Its successor carries the
correct gap/overrun flags, sequence and timestamp. The pinned frame stays
byte-identical. Independent SDK decoding verifies the successor checksum and
payload; final sample conservation holds. A draining-consumer control loses
nothing.

The responsible production path is `PacketBufferPipeline::beginFill()` →
`takeFreeBuffer()` → `oldestEvictableCompleteBuffer()` → `evictCompleteBuffer()`
→ `dropBuffer()` / `propagateGapAfter()`. The observed eviction behavior is the
existing continue-and-report policy functioning as designed.

Reproduce locally from the repository root:

```bash
PYTHONPATH=daq_api/src python .maestro/playbooks/Working/phase06-gpio-overrun-20261025/run_repro.py
```

Retained diagnostic drivers are `run_diagnostic.py`, `run_resources.py`, and
`run_adequate_cpu.py` in that same directory. For accepted jobs, use the owning
driver with `--resume --job job-01`, `job-02`, or `job-03` respectively. All are
terminal; resuming saved results is not a fresh measurement. Do not resubmit
these jobs or restart the failed qualification controller.

## Scoped next correction and limits

The current qualification runner submits into the service's default half-core
container without establishing the adequate host allocation used by earlier
SDK campaigns. Correct that runner precondition: establish and verify the
job-specific host CPU allocation before capture, retain quota/throttling and
post-STOP ownership evidence, and preserve accepted-job reconciliation and
queue-aware timeouts. Reuse `host_cpu()` from `rig_release_sdk.py` and
`CpuTracker` from `firmware/soak/validator.py` when integrating telemetry.
Keep resource setup bounded once the job starts, preserve the normal service
cleanup, and fail explicitly if the requested allocation is not established.
Do not classify loss as PASS because it came from host pressure.

The original job's exact scheduling history remains unavailable. Same-artifact
reproduction establishes this responsible path; the quota comparison supports
the scoped remedy. One adequate-CPU pass does not establish full qualification
or exclude unrelated future failures. Runner changes require their own
correction/regression commits and refreshed protected-input identity before
canonical requalification. No firmware/SDK/runner production input changed in
this diagnosis.

Legacy STATUS includes separately accounted partial STOP tails and historical
boot-layout fields. Those are not additional complete-frame overruns, and its
boot-layout fields do not override the negotiated public-v3 layout. Entire
wire input was hashed; only bounded sample/control frames were retained, not
a full raw-byte stream file.

Validation: deterministic pressure reproduction and independent wire decode
PASS; 31 affected existing tests and 16 subtests PASS; candidate artifact,
SDK/schema/runner identities and all 499 protected files verify unchanged.
Documentation/layout validation passed 11 tests and 1,442 subtests.
Exact statuses, host-resource deltas and retained-file hashes are in
[the machine-readable evidence](protocol-v3-gpio-overrun-diagnosis.json).
