---
type: reference
title: Autonomous Soak Harness
created: 2026-08-29
tags:
  - thingdaq
  - firmware
  - endurance
  - remote-testing
related:
  - '[[Protocol-V1]]'
  - '[[Phase-09-Loss-Recovery]]'
  - '[[Phase-10-Package-Workflows]]'
  - '[[Phase-11-Soak-Evidence]]'
---

# Autonomous soak harness

> [!NOTE]
> Historical contract/evidence: clocks, profiles, sizes and identities below
> describe the named earlier firmware or experiment, not release 1.1.0.
> The current release specification is [[Protocol-V2]] (450 MHz core, fixed
> 1 MHz ADC and GPIO, optional 16 inputs). Old v1 soak harnesses are not v2
> release validators; use the release input/SDK runners.

Phase 11 and both Windows entry paths use one canonical validator and generated
implementations. Edit `firmware/soak/validator.py` or
`firmware/soak/windows_driver.inc`, never a generated program directly. The
generated files contain the complete protocol implementation because neither
the remote container nor the standalone Windows handoff requires a repository
checkout or installed package; both need only the standard library and
PySerial. The installed command executes its generated implementation inside
the `thingdaq` package rather than importing the standalone script. Remote
programs obtain their sole device endpoint from `SERIAL_PORT`, while both
Windows paths perform metadata-first, identity-pinned COM discovery.

## Candidate and generation

`firmware/soak/candidate.json` pins the expected firmware, protocol, board,
artifact, duration, and deadline identity. The generator verifies it against
the accepted two-build `firmware/soak/candidate-freeze.json`, derives the
complete release contract from `protocol/protocol-v1.json` and the canonical
validator, and writes `firmware/soak/validation-manifest.json`. The manifest is
path- and credential-free, links to [[Phase-11-Soak-Evidence]], and records the
exact firmware/HEX identity, checksum parameters, INFO capabilities,
rates/phases/pins, frame layout, resolution, and required zero counters.

Regenerate that manifest, all three Phase 11 rig programs,
`daq_api/scripts/windows_soak.py`, and `daq_api/src/thingdaq/soak.py` with:

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
path-aware hash of all protocol, firmware, harness, test, example, and package
inputs. The generated installed entry point is excluded from that tree because
it embeds the freeze digest; `generate_soak_programs.py --check` independently
enforces its exact bytes and avoids a circular hash dependency. The accepted
artifacts live under the ignored staged path recorded by the freeze. Every
service submission must use that staged HEX and run both freeze and generator
checks immediately before preflight. The freeze check fails closed on a
changed, added, or removed protected file, candidate-identity drift, or staged
artifact drift; any intentional edit therefore requires a new two-build freeze
and restarts the consecutive-pass series. The soak generator emits three
deterministic rig programs under `firmware/tests/generated/` and the Windows
handoff at the path shown below:

| Mode | Generated program | Measured contract |
| --- | --- | --- |
| Synthetic | `rig_soak_synthetic.py` | One 600-second combined synthetic epoch after warm-up |
| Physical combined | `rig_soak_physical_combined.py` | One 600-second combined hardware epoch after warm-up |
| Control stress | `rig_soak_control_stress.py` | A 600-second campaign of alternating bounded hardware/synthetic epochs and periodic CDC reopens |
| Release validation manifest | `firmware/soak/validation-manifest.json` | Deterministic Phase 11 candidate, protocol, INFO, acquisition, frame, and zero-counter contract embedded into both Windows paths |
| Windows handoff | `daq_api/scripts/windows_soak.py` | One identity-pinned 3600-second physical-combined epoch by default, with shorter diagnostic and synthetic options |
| Installed Windows handoff | `thingdaq-soak` → `thingdaq.soak:main` | The same options and report schema, executed from the installed package implementation |

The two Windows paths differ only in role-specific generated metadata. Prove
their shared command bytes against protocol fixtures and exercise identical
fragmented success/corruption/pattern/gap transcripts through both parsers,
validators, metric calculations, and graders with:

```bash
.venv/bin/python firmware/tools/check_soak_conformance.py --pretty
py daq_api\scripts\windows_soak.py --conformance-check
thingdaq-soak --conformance-check
```

The repository gate fails if implementation bytes outside the generated
metadata differ, either path disagrees with the golden request/data frames, or
their deterministic metrics and PASS/FAIL categories differ. A normal installed
run accepts the same `--mode`, `--duration`/`--smoke`, `--hardware-serial`,
`--port`, `--output`, `--discovery-timeout`, and `--open-timeout` options as the
standalone path and writes the same JSON/structured-Markdown report schema.
Both programs validate the embedded manifest digest before opening a COM port.
The default path rejects any INFO field that differs from the manifest, and a
COM number is recorded only as mutable discovery evidence rather than device
identity.

The authoritative JSON records every release predicate under
`windows.release_requirements`. A report is labeled `profile: release` only
when `physical_combined_mode`, `exact_3600_second_duration`, `non_smoke`,
`diagnostic_identity_override_disabled`, and `native_windows_host` are all
`true`; native host identity requires both `system: Windows` and
`sys_platform: win32` from one captured host snapshot. `release_eligible` is
the conjunction of the complete mapping, which additionally requires an
overall PASS, exact manifest/device identity, and finite nonnegative
`baseline_bytes`, `peak_bytes`, and `growth_bytes` process-RSS evidence with
growth no greater than 32 MiB. Missing, malformed, negative, non-finite, or
over-limit RSS evidence fails closed as non-release without changing a useful
diagnostic PASS into a runtime FAIL.

On native Windows, the bounded `MemoryTracker` checkpoints obtain current and
peak process working-set bytes through a dependency-free `ctypes` wrapper over
`GetCurrentProcess` and `GetProcessMemoryInfo`. The wrapper validates the
`PROCESS_MEMORY_COUNTERS` structure and returns unavailable evidence rather
than zero when the native API cannot be loaded or called. The report's
`windows.validation_reasons` then identifies a non-native host, unavailable or
invalid RSS fields, or RSS growth above 32 MiB explicitly; these are
release-evidence failures, not automatic runtime failures for an otherwise
useful diagnostic run.

`--diagnostic-identity-override` is the sole escape hatch for deliberately
testing a different parseable device or firmware identity. It must be supplied
explicitly; without it, even one build, hardware-serial, version, capability,
rate, phase, pin-map, frame-size, or resolution mismatch is rejected before
stream grading. With it, the mismatches are retained in JSON and Markdown,
stdout prints a warning, the report profile becomes
`diagnostic-identity-override`, and `release_eligible` is always `false` even
when every stream check passes. It cannot convert diagnostic evidence into a
release result.

Each Phase 11 rig program has a 780-second internal deadline and records the
service's 900-second container limit, leaving 120 seconds for bounded STOP,
final STATUS, process teardown, and service cleanup. The Windows profile derives
finite run and total deadlines from its selected duration and reserves bounded
cleanup time separately.

The control-stress program includes exactly one named
`serial_read_stall_pressure` negative subcase in its first physical epoch. It
keeps the same CDC and parser session open but performs no host serial reads for
250 ms while acquisition remains `RUNNING`. After reads resume, every complete
frame is validated and each sequence/timestamp gap must carry both `GAP_BEFORE`
and `OVERRUN_BEFORE`; the exact ADC/GPIO frame, item, and payload-byte counts
must equal the firmware's pressure-eviction, packet-exhaustion, and
stage-conservation counters. All other epochs remain strictly zero-loss.
Periodic CDC close/reopen operations occur only from `IDLE`, then re-synchronize
and revalidate the immutable device identity before the next run.

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
    "build_id": "thingdaq-source-prefix",
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

For the final Phase 11 decision, also supply the accepted/excluded campaign
index for each mode and enable the release policy:

```bash
.venv/bin/python firmware/tools/aggregate_soak_results.py \
  --pretty --strict --phase-11-release \
  --campaign-index synthetic-campaign-index.json \
  --campaign-index physical-campaign-index.json \
  --campaign-index control-campaign-index.json \
  --output phase-11-accepted-soaks.json \
  accepted-synthetic-1.json accepted-synthetic-2.json \
  accepted-physical-1.json accepted-physical-2.json accepted-physical-3.json \
  accepted-control.json
```

That gate requires one uniform source, build, firmware, protocol, and artifact
identity; two synthetic, three physical-combined, and one control-stress job
whose configured and observed durations are at least 600 seconds; complete
per-epoch parser, formula, counter, queue, latency, and memory evidence; exact
produced/framed/emitted/transmitted/dropped conservation; stable one-percent
rates; the Phase 04 100/250/500 ms latency limits; and an exact match between
the aggregate inputs and campaign-index accepted IDs. Every campaign index
must explicitly contain `excluded` and `infrastructure_incidents` lists, even
when either list is empty. Any missing field makes `release_gate.result` fail
and the command exit nonzero.

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
