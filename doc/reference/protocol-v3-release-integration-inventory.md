---
type: reference
title: Protocol v3 release integration reuse inventory
created: 2026-10-20
tags:
  - protocol-v3
  - release
  - build
  - reuse-audit
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-clock-control]]'
  - '[[release-1.1.0]]'
  - '[[soak-harness]]'
---

# Protocol v3 release integration reuse inventory

Phase 05 task 1 inspection at source revision
`1c6afa7ce2d4d89d26bd6c680862704f20f6d4ca`. The initial `main` worktree was
clean. `AGENTS.md` requires validated checkpoints pushed to `origin/main`
and all rig HTTP traffic routed through `run_input_isolation.py`.
No `CLAUDE.md` was present. No task images were supplied.

This inventory records the integration seams for subsequent tasks. It does
not change defaults, build a release candidate, or establish physical acceptance.
The current fixed-clock implementation is described in
[[protocol-v3-clock-control]] and [[protocol-v3-upgrade]].

## Build and identity

| Existing implementation | Reuse and remaining integration |
| --- | --- |
| `firmware/tools/build_firmware.py` | Keep the pinned Teensy core 1.62.0, Arm GNU 15.2.1, FQBN `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`, resolved-property checks, and `firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std/` output. The builder already sets the internal CPU macro to 600 MHz. |
| `collect_source_files`, `source_fingerprint`, `resolve_build_epoch`, `build_identity`, `git_source_state` | Reuse stable path/content hashing, `thingdaq-<source hash prefix>`, source-derived epoch or `SOURCE_DATE_EPOCH`, and scoped Git dirtiness. Inputs currently include the sketch, all `firmware/src`, and v1/v2 schemas. Generated v3 C++ constants and board policy are covered through `src`; the canonical v3 schema and builder selections need explicit provenance coverage. |
| Build manifest schema 11 and binary inspection | Preserve artifact sizes/SHA-256, compile command, linker map, checksum placement, DMA alignment/ownership, packet capacity/retention, and RAM headroom checks. `release_policy.protocol_version` is still hard-coded to 2; resource/retention projections still read v2. Audit those projections against actual v3 layouts. |
| `firmware/src/board_profile.h`, `v3_settings.h`, generated constants | Reuse exact tuple membership and `FixedBuildApplication`; derive metadata/defaults from the canonical contract and build policy. Normal firmware selects fixed 600 MHz; compiled clock metadata is not an independent physical measurement. |
| `firmware/tools/build_input_experiment.py` | Retain the wrapper around normal build gates, distinct output directories, selection-derived identities, and `input_experiment` manifest. Private RLE/PACK12/deferred flags remain historical research controls, not a prerequisite for public-v3 defaults. |

The target public defaults are 600 MHz, 1 MHz ADC/GPIO, auxiliary DISABLED,
RLE_AUTO and PACK12. Preserve explicit v2 RAW compatibility and use the recorded
release source revision `e3e8417598de7494db3a93d7277ef8f0ec31bc8f` when reproducing
the historical 450 MHz release. An experiment wrapper on current source is
not a reproduction of those historical bytes.

## Freeze, validation, and rig execution

| Existing implementation | Reuse and boundary |
| --- | --- |
| `firmware/tools/freeze_soak_candidate.py` | Reuse clean protected-input enforcement, two byte-identical builds/manifests, candidate/build identity checks, immutable staging, protected-tree hash, and verification. Select a new lock/candidate/stage explicitly. Its protected-input list still names the historical candidate and excludes generated `soak.py` to avoid a transitive hash cycle; adapt coverage for new SDK/runner inputs. |
| `firmware/soak/` | `candidate.json`, `candidate-freeze.json`, and `validation-manifest.json` describe firmware 1.0.0/protocol v1 at 600 MHz with historical 4 MHz GPIO. Preserve them as a campaign, not a template to overwrite with public v3. `validator.py` supplies the canonical independent validator; `windows_driver.inc` supplies the generated CLI driver. |
| `firmware/tools/generate_soak_programs.py`, `check_soak_conformance.py` | Reuse deterministic generation, identity-bound validation metadata, normalized standalone/installed implementation comparison, fixed command fixtures, fragmented transcripts, and grading equivalence. Passing these checks verifies the historical harness, not v3 qualification. |
| `firmware/tools/aggregate_soak_results.py`, `firmware/tests/test_soak_endurance_tools.py` | Reuse retained attempt lineage, identity/conservation checks, accelerated devices, and service transcript fixtures. Extend qualification around advertised v3 tuples and explicit missing-evidence outcomes. |
| `firmware/tools/run_input_isolation.py` | Reuse `request_json`, `submit_program`, `wait_for_result`, and `resume_saved_program`. Persist submission identity before network activity; reconcile journal acceptance before retrying START; follow saved job IDs. Every 5xx retries every 30 seconds for up to 600 continuous seconds. Queue residence and HTTP retry waits do not consume execution deadlines. |
| `firmware/tests/rig_release_sdk.py` and existing isolation validators | Reuse SDK bundling, capture evidence and bounded temperature retries; adapt the v2-specific SDK runner to public v3. Keep the required 80 °C abort threshold and existing service budget: captures up to 600 seconds, planned program at most 780 seconds, container limit 900 seconds. |

The future v3 manifest belongs at `firmware/soak/protocol-v3-candidate.json`.
Never replay archived raw-evidence clients or replace historical experiment
binaries/manifests, release-1.1.0 evidence, or frozen v1/v2 fixtures.

## Distribution and guides

`daq_api/pyproject.toml` uses setuptools 84.0.0 and reads SDK version `1.1.0`
from `thingdone_daq._version`. Firmware identity lives separately in
`firmware/src/firmware_identity.h`; wire versions belong to the protocol
contracts. Keep these version axes independent and add a new changelog entry
without rewriting `daq_api/CHANGELOG.md`'s first-public-package record.

Reuse `daq_api/MANIFEST.in` and package-data exclusions: installed code imports
generated Python constants; canonical JSON, fixtures, captures, credentials,
and firmware artifacts do not ship. Existing distribution tests build and
inspect wheel/sdist contents and isolated imports/entry points.
`daq_api/README.md` documents `python -m build --outdir daq_api/dist daq_api`
with a package-source-derived `SOURCE_DATE_EPOCH`. Retain local Twine checks
and isolated-wheel demo validation; remote package publication is outside scope.

Reviewed `README.md`, `doc/guides/quickstart.md`, and
`doc/reference/api-reference.md`. Reuse their executable simulator examples,
stable hardware-serial selection, explicit physical commands, exact CONFIGURE
echo/readback checks, and qualification limits. The API reference already has
v3 negotiation/settings/CLI sections; extend these instead of creating another
API guide. Remaining guide work includes:

- Lead with public-v3 defaults; label historical 450 MHz/v2 and 4 MHz/v1
  examples consistently. The README still labels v2 the current wire contract.
- Make commands usable from the installed package, while retaining repository
  development instructions and historical evidence.
- Add the planned migration guide and link it once it exists; reconcile stale
  negotiation wording in the v3 schema with the implemented SDK behavior.
- Keep unsupported diagnostics unavailable and physical qualification explicit.

## Validation for this inspection

Reused existing tests; no runtime code or new test helper was needed.
The following focused suite passed: **83 tests and 1,137 subtests**.

```bash
.venv/bin/python -m pytest -q \
  firmware/tests/test_build_configuration.py \
  firmware/tests/test_soak_candidate_freeze.py \
  firmware/tests/test_soak_endurance_tools.py \
  firmware/tests/test_input_isolation.py \
  daq_api/tests/test_package_configuration.py \
  daq_api/tests/test_release_v110_contract.py \
  daq_api/tests/test_documentation_integrity.py
```

Additional checks passed:

```bash
.venv/bin/python tools/generate_protocol.py --check
.venv/bin/python firmware/tools/generate_soak_programs.py --check
.venv/bin/python firmware/tools/check_soak_conformance.py
```

Protocol generation checked 142 outputs. Soak generation changed no files;
standalone/installed conformance returned PASS. Firmware compilation, new
distribution builds, a new freeze, and physical qualification were not run
for this inspection task. Their gates remain assigned to later tasks.
