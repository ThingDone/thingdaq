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

The command refuses a manifest/artifact digest mismatch. It emits these
deterministic, executable programs under `firmware/tests/generated/`:

| Mode | Generated program | Measured contract |
| --- | --- | --- |
| Synthetic | `rig_soak_synthetic.py` | One 600-second combined synthetic epoch after warm-up |
| Physical combined | `rig_soak_physical_combined.py` | One 600-second combined hardware epoch after warm-up |
| Control stress | `rig_soak_control_stress.py` | A 600-second campaign of alternating bounded hardware/synthetic epochs and periodic CDC reopens |

Every program has a 780-second internal deadline and records the service's
900-second container limit, leaving 120 seconds for bounded STOP, final STATUS,
process teardown, and service cleanup.

## Validation and stdout contract

The validator consumes arbitrary serial chunks without retaining the capture.
It checks every frame checksum, protocol field, run ID, source flag, independent
sequence, common timestamp epoch, synthetic ADC/GPIO formula, scheduler skew,
and final firmware conservation equation. Physical mode grades the complete
conversion/capture/DMA/packing/transport path while explicitly recording that
undeclared external analog or digital stimulus cannot be quality-graded.

Evidence is bounded to first/last diagnostic samples, representative STATUS
snapshots, latency samples, queue maxima, counter endpoints, `tracemalloc`, RSS,
and available container/process memory. Progress lines begin with `SOAK_EVENT`.
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
