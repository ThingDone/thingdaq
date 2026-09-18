---
type: result
title: M7 Hardware Test Attempt and Programming Failure
created: 2026-09-18
tags:
  - thingdaq
  - firmware
  - performance
related:
  - '[[m7-performance-experiments]]'
  - '[[firmware-runtime-hardening]]'
---

# M7 hardware test results

The baseline acquisition test failed with a USB disconnect. Two subsequent
programming attempts failed before their Python tests could run. No M7 timing
measurements or experimental acquisition comparisons were obtained. The rig
needs board recovery before this campaign can continue.

The user authorized hardware tests after the compiler-only experiment. The
established service at `http://192.168.150.14:5000` reported version 1.2.0/API v1,
healthy status, coordinator mode normal and an empty queue. Jobs ran serially.
The first job identified Teensy 4.0 serial `20428100`, firmware 1.1.0/protocol 2,
build `thingdaq-6f2c6b332efc9280`. This is the standard 450 MHz `-O2` firmware,
with the original C++ packer and production interrupt guards.

| Job | Test ID | Programming | Test outcome |
| --- | --- | --- | --- |
| Baseline public SDK, five acquisition modes planned | `a04db2cd-5598-489c-ad2a-11f1bfa6481c` | Success | Failed during first ADC-only capture |
| Baseline independent wire validator, combined ADC/GPIO | `a2258ae2-fef1-4c96-96e2-bfde877ffaa4` | Failed: loader `-110`, service exit `-130` | Not run |
| Standalone `-O2` microbenchmark, one programming retry | `6b985e48-d1b4-450d-9dbb-c03cb55d87cd` | Failed: loader `-110`, service exit `-130` | Not run |

## Observed baseline failure

INFO and the 1 MHz GPIO clock diagnostic succeeded. Initial die temperature was
37.281 degrees Celsius. The public SDK then started ADC-only capture with the
auxiliary bank disabled. The serial transport disconnected 1.038644 seconds
after the capture loop started. The host had received 3,983,300 bytes, decoded
994 frames, and delivered 969 ADC frames. Parser checksum/header/payload errors,
corruption events, resynchronizations and host block-queue drops were all zero.

The exception was `DeviceDisconnectedError`, caused by a serial read reporting
readiness but returning no data. The exception's cached device state was RUNNING,
run ID 1. This is not proof of the device's final state. No complete acquisition
cell passed. The container was limited to half a CPU and recorded throttling;
these observations do not establish whether the disconnect came from firmware,
USB/power, or another rig condition. No reset-cause or stack-watermark sample
was captured, so this report does not attribute the failure to a watchdog or
stack overflow.

The independent wire test was submitted to distinguish a public-SDK issue from
a more general failure, but its upload failed. The standalone timing image was
then submitted as the single infrastructure retry described in the
[soak harness procedure](../guides/soak-harness.md). It also failed to program.
Both jobs report `completed: true`, `program_success: false`, and exit `-130`;
the service's outer `status: success` only means result retrieval completed.
It is not a passing hardware test. Subsequent submissions were stopped.

Postflight health again reported normal mode, worker/Docker/hub reachable, and
queue depth zero. Baseline firmware was the last image successfully programmed,
but final firmware state and restoration could not be confirmed. The documented
public service API offers no separate board recovery operation. Reconnect the
Teensy on rig hub port 15 or use its PROGRAM button, then repeat the baseline
preflight before acquisition comparisons.

## Evidence and resumption tooling

[Tracked evidence](m7-hardware-evidence.json) retains job IDs, programming and
test results separately, firmware/program hashes, preflight state, and the full
service replies. Original artifacts remain under ignored
`doc/results/raw/m7-hardware-20260918/`, including submitted HEX files, build
manifests and exact Python programs. No credential was copied into evidence.

The prepared `firmware/tests/rig_m7_benchmark.py` collector requests five timing
passes and requires all ten cases per pass, the expected CPU/optimization
banner, ordered cycle counts, correct operation counts, and an independent
host digest of the packed GPIO output. Missing, duplicate, corrupt and partial
results fail validation. USB serial is checked when the container exposes it;
the preceding production preflight independently verifies the protocol's
hardware serial. The collector has not executed on the physical target yet.

`firmware/tools/run_m7_benchmark.py` verifies the benchmark ELF against its build
manifest and derives the uploaded HEX from that ELF. It reuses the extracted
`service_preflight` and `submit_program` functions in `run_input_isolation.py`.
These enforce idle/healthy preflight, retain the job ID and raw replies, and do
not automatically repeat an ambiguous submission. After board recovery, use a
new evidence directory for each resumed job:

```bash
python3 firmware/tools/run_m7_benchmark.py \
  --build-dir firmware/build/m7-performance/benchmark-O2 \
  --evidence-dir doc/results/raw/m7-hardware-resumed/benchmark-O2 \
  --service http://192.168.150.14:5000
```

The existing `run_input_isolation.py` supports the baseline and experimental
acquisition checks. Run only firmware variants that passed the normal memory
and build gates. Restore and verify the baseline after the timing campaign.

Local validation of the collector, shared submission behavior and documentation
passed 28 tests and 720 subtests. Formatting and lint checks passed. These are
tooling checks and do not change the failed/blocked hardware outcome above.
