---
type: reference
title: Autonomous Soak Harness
created: 2026-08-29
tags:
  - teensy-daq
  - firmware
  - endurance
  - remote-testing
related:
  - '[[Protocol-V1]]'
  - '[[Phase-09-Loss-Recovery]]'
  - '[[Phase-10-Package-Workflows]]'
---

# Autonomous soak harness

Phase 11 uses one canonical validator and generated standalone programs. Edit
`firmware/soak/validator.py`, never one of the generated programs directly.
The generated files contain the complete protocol implementation because the
remote container has no repository checkout, no network, and only Python 3.13,
the standard library, and PySerial. They obtain their sole device endpoint from
`SERIAL_PORT`.

## Candidate and generation

`firmware/soak/candidate.json` pins the expected firmware, protocol, board,
artifact, duration, and deadline identity. Regenerate all three programs with:

```bash
.venv/bin/python firmware/tools/generate_soak_programs.py
.venv/bin/python firmware/tools/generate_soak_programs.py --check
```

When a newly built candidate is intentionally selected, bind the manifest to
the actual artifact bytes and update the candidate before generating:

```bash
.venv/bin/python firmware/tools/generate_soak_programs.py \
  --build-manifest firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/build-manifest.json \
  --artifact firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/firmware.ino.hex \
  --update-candidate
```

The candidate-update command refuses a manifest/artifact digest mismatch.

After two clean builds reproduce every manifest-declared artifact, freeze the
second build into the campaign's dedicated working directory:

```bash
.venv/bin/python firmware/tools/freeze_soak_candidate.py --create \
  --first-build-directory .maestro/playbooks/Working/phase-11-soak-candidate-00001/first-build
.venv/bin/python firmware/tools/freeze_soak_candidate.py --check
```

`firmware/soak/candidate-freeze.json` records both manifest hashes, every
exported artifact hash, the inspected memory/resource sections, and a
path-aware hash of all package, protocol, firmware, harness, generated, test,
and example inputs. The accepted artifacts live under the ignored staged path
recorded by that file. Every service submission must use that staged HEX and
run `--check` immediately before preflight. The check fails closed on a
changed, added, or removed protected file, candidate-identity drift, or staged
artifact drift; any intentional edit therefore requires a new two-build freeze
and restarts the consecutive-pass series. The soak generator emits these
deterministic, executable programs under `firmware/tests/generated/`:

| Mode | Generated program | Measured contract |
| --- | --- | --- |
| Synthetic | `rig_soak_synthetic.py` | One 600-second combined synthetic epoch after warm-up |
| Physical combined | `rig_soak_physical_combined.py` | One 600-second combined hardware epoch after warm-up |
| Control stress | `rig_soak_control_stress.py` | A 600-second campaign of alternating bounded hardware/synthetic epochs and periodic CDC reopens |

Every program has a 780-second internal deadline and records the service's
900-second container limit, leaving 120 seconds for bounded STOP, final STATUS,
process teardown, and service cleanup.

The control-stress program includes exactly one named
`cdc_close_reopen_pressure` negative subcase in its first physical epoch. It
closes CDC only at a complete-frame boundary while acquisition remains
`RUNNING`, pauses for 250 ms, reopens and re-synchronizes to the same device and
run ID, then validates each retained frame. The permitted sequence/timestamp
gaps must carry both `GAP_BEFORE` and `OVERRUN_BEFORE`; their exact ADC/GPIO
frame, item, and payload-byte counts must equal the firmware's pressure
eviction, packet-exhaustion, and stage-conservation counters. All other epochs
remain strictly zero-loss, and later periodic CDC reopens occur from `IDLE`.

The serial loop keeps the previously accepted mode-specific synchronous read
cadence: synthetic runs use 64 KiB batches, while physical-combined and
control-stress runs use 16 KiB batches. The smaller hardware batch bounds each
non-yielding range/structure-validation visit on the service's constrained CPU
runner, so physical DMA keeps the proven host-drain cadence. The selected byte
count is included in both `SOAK_EVENT program_start` and the terminal result.
Physical ADC range validation uses one C-level integer mask over every 12-bit
sample instead of a Python byte-lane loop, keeping the same exhaustive check
while reducing work inside the service's 0.5-core quota.

## Validation and stdout contract

The validator consumes arbitrary serial chunks without retaining the capture.
It checks every frame checksum, protocol field, run ID, source flag, independent
sequence, common timestamp epoch, synthetic ADC/GPIO formula, scheduler skew,
and final firmware conservation equation. It decodes the complete STATUS
pressure/ownership extension through the raw and packer loss projections so a
named negative subcase cannot hide a missing or mismatched counter. Physical
mode grades the complete conversion/capture/DMA/packing/transport path while
explicitly recording that undeclared external analog or digital stimulus
cannot be quality-graded.

Evidence is bounded to first/last diagnostic samples, representative STATUS
snapshots, latency samples, queue maxima, counter endpoints, `tracemalloc`, RSS,
available container/process memory, and boundary-only cgroup CPU/throttling
counters. A failed active epoch also retains its receive-gap maximum, parser
counters, last STATUS errors/queues, and bounded samples so a host scheduling
stall can be separated from device-originated loss. Progress lines begin with `SOAK_EVENT`.
Exactly one terminal line begins with `SOAK_RESULT ` followed by compact JSON;
the process exits zero only when that result is `PASS`.

## Saved job evidence

Keep the service's exact `/results` response together with client-side metadata
that the device cannot observe. The aggregator accepts a bundle shaped like:

```json
{
  "job_id": "service-test-uuid",
  "service_result": {
    "test_id": "service-test-uuid",
    "completed": true,
    "program_success": true,
    "exit_code": 0,
    "stdout": "SOAK_EVENT ...\nSOAK_RESULT {...}"
  },
  "job_metadata": {
    "artifact_sha256": "actual-uploaded-hex-sha256",
    "program_sha256": "actual-generated-program-sha256",
    "source_id": "firmware-source-id",
    "build_id": "tdaq-source-prefix",
    "client_started_utc": "2026-08-29T12:00:00+00:00",
    "client_completed_utc": "2026-08-29T12:11:00+00:00",
    "client_version": "1.0.0",
    "service_version": "1.0.0"
  }
}
```

Aggregate one or more saved bundles and fail unless every record is accepted:

```bash
.venv/bin/python firmware/tools/aggregate_soak_results.py \
  --pretty --strict saved-job-*.json
```

The output preserves the test process exit status separately from its
classification and normalizes rates, latency milliseconds, queue high-water
marks, and memory bytes for cross-run comparison.

| Classification | Meaning | Disposition |
| --- | --- | --- |
| `accepted` | Programming and test succeeded; result and uploaded identities are complete and equal | Count the run |
| `test_failure` | A complete soak result failed, or its test exited nonzero | Fail the release candidate |
| `program_failure` | Programming succeeded but the harness emitted no complete result | Diagnose the harness |
| `upload_failure` | Programming failed, including service exit `-130` | Retry infrastructure once |
| `service_failure` | The service did not complete normally or returned another negative exit | Retry infrastructure once |
| `evidence_failure` | The test passed but required identity or timestamp evidence is absent or inconsistent | Diagnose evidence capture; do not count |

The current service contract marks programming independently with
`program_success`, uses `completed` for terminal worker state, returns the
container's exit as `exit_code`, and reserves negative exit codes for service
or upload failures. See [[Phase-10-Package-Workflows]] for the accepted client
and deployed-service provenance that this harness extends.
