---
type: report
title: Public v3 rig verification failed at live INFO
created: 2026-10-20
tags:
  - protocol-v3
  - qualification
  - hardware
  - failure
related:
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-qualification]]'
  - '[[protocol-v3-local-gates]]'
---

# Phase 06 rig and candidate verification

Historical attempt; its **FAIL remains unchanged**. The 2026-10-24 diagnosis,
corrections, and replacement identity PASS are in [[protocol-v3-identity-recovery]].
The unchecked-task statement below describes the original attempt.

**FAIL: live firmware identity could not be read after programming.**
The first Phase 06 agent task remains unchecked. Measurements are **NOT_RUN**;
the release remains an unqualified candidate.

## Verified inputs and availability

The candidate from [[protocol-v3-release-candidate]] passed its freeze check:
498 protected files, all 15 retained artifacts, source revision, firmware,
SDK, schema and runner hashes matched. The 63-job matrix matched the policy.
The installed Arduino CLI 1.4.1, Teensy core 1.62.0 and Arm GNU 15.2.1 matched
the frozen build manifest; the target remained
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`.
No firmware, SDK, schema, runner or frozen manifest was changed or rebuilt.

| Identity | Value |
| --- | --- |
| Frozen source revision | `eb8a890da5646ff18074a9103678b8e6acc0c900` |
| Checkpoint worktree revision | `020f2049a63b1f5773c3d00db9a5920af5850d5d` |
| Canonical candidate SHA-256 | `4781d273db15091039b841b51680a31143b02a6eec4d94ac23ec2898634540b4` |
| Firmware HEX SHA-256 | `2a64e61f071b4ff9d981c3ea0217049dd40b64fad2ae448267a70c5b47fd25e7` |
| Expected build ID | `thingdaq-67539aafb5b130a5` |
| Expected board serial | `20428100` |
| Rig job | `20005b76-64a0-43c3-88a8-347d7676d2c9` |

The shell lacked `FW_RIG_SERVICE` and `FW_RIG_AUTH`. The existing historical
rig URL and the runner's private default credential file were available.
The credential was read directly, never embedded in a program or evidence.
Non-mutating health, version and platform requests used
`firmware/tools/run_input_isolation.py`. Health passed before and after the
job; service version was 1.2.0. Read-only SSH journal access also worked.

The platform catalog listed Teensy 4.0 on hub port 15 as disconnected.
The rig's local HOWTO explains that configured offline boards stay listed
and every job powers and reflashes its board. The job journal subsequently
confirmed power-on, successful loading, container execution and power-off.

## Failed live check

The unchanged qualification worker was bundled by the existing runner with
a separate `preflight-identity-only` descriptor and **zero capture cycles**.
This executes its normal physical INFO and exact capability comparison before
the capture loop. It is deliberately outside the 63-cell qualification ledger
and cannot satisfy any acquisition, timing, thermal or compatibility cell.
The standard planner reserved 36 seconds plus the existing 90-second client
margin; the rig's 900-second limit and retry/reconciliation rules were retained.

The first upload attempt reported `error writing to Teensy`. The rig's built-in
retry then programmed from HalfKay and reported `Booting`. The worker failed:

```text
CommandTimeoutError: INFO_REQUEST request 2535947824 exceeded 0.999997 seconds
```

The wire observer received **zero bytes**, no control frames and no data
frames. There is no live INFO identity or capabilities payload to compare.
Neither an identity match nor a mismatch was established. The underlying cause
of the missing response remains undiagnosed.

The service marked container execution successful, but returned exit code 1
and the worker reported FAIL. Those latter results determine this checkpoint.
There were no HTTP 5xx responses, ambiguous submissions or replacement jobs.
The single accepted job's result and admission journal were recovered and
retained. No measurement campaign was started.

## Evidence and validation

Machine-readable details, the worker failure record, upload log, artifact
identities and retained-file hashes are in
[protocol-v3-rig-verification.json](protocol-v3-rig-verification.json).
The 17 retained local evidence files live under
`.maestro/playbooks/Working/phase06-rig-verification/`; raw files follow the
repository's existing local-retention convention. The JSON is sufficient to
inspect the failure without needing the ignored raw service response.

The freeze, qualification, HTTP-recovery and input-isolation suites passed
**822 tests in 24.47 seconds**. These are host tests, not physical acceptance.
An initial auxiliary toolchain inspection used the wrong Arduino JSON key
(`installed`); the corrected `installed_version` check passed.
Documentation integrity also passed (7 tests, 1,254 subtests). A separate
evidence check verified all retained-file hashes, candidate/job bindings,
failed outcome and credential exclusion.

The local `verify_identity.py --resume` command reuses the saved job and
completed result; it cannot replace this failure with another submission.
Do not execute the archived `identity-job/rig-program.py` as a client.

Phase 06 stops at its unmet live-identity prerequisite. Diagnose the
post-flash INFO timeout before resuming measurements, retaining this failure.
Any correction to frozen firmware, SDK or runner inputs requires a new
candidate and the corresponding requalification under
[[protocol-v3-qualification]]. No supported-release claim is made.
