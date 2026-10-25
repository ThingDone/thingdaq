---
type: report
title: ThingDAQ 1.2.0 publication audit
created: 2026-10-25
tags:
  - release
  - qualification
  - publication
related:
  - '[[release-1.2.0]]'
  - '[[protocol-v3-hardware]]'
  - '[[protocol-v3-migration]]'
---

# Publication audit: PASS

The completed qualification reports, supported-release manifest and current
guides are published on `origin/main` in commit
[`2edf6771325b27e32efba60a53a4ed13e2dd17cd`](https://github.com/ThingDone/thingdaq/commit/2edf6771325b27e32efba60a53a4ed13e2dd17cd).
A fresh fetch and remote branch query agree with the local commit. All 70 audited
published files match the fetched Git tree byte-for-byte. Candidate, pre-upgrade
SDK and rollback source revisions resolve and are ancestors of that remote tip.
This checks Git publication, not GitHub web-page availability.

[Machine-readable audit](release-1.2.0-publication.json) records immutable source
URLs, hashes, sizes and validation scope. [[release-1.2.0]] remains the final
supported-release report; [[protocol-v3-hardware]] preserves the earlier grading
checkpoint without changing its evidence binding.

## Supported artifact and behavior

- Candidate: `14c14a82912a95482bb9146abb06e310b3d7f8c24bec37ef2274d13d4b9d4682`.
- Firmware HEX: `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`;
  build `thingdaq-e0c750868be7c5c2`, Teensy 4.0 serial `20428100`.
- SDK ZIP: `c22e520af516077d4b92527699c6c602dd857d0ef4627c453f5a20be32090f1f`.
- Defaults: fixed 600 MHz CPU, 1 MHz ADC/GPIO, ADC PACK12, GPIO RLE_AUTO,
  auxiliary DISABLED. Stopped RAW/compressed changes retain the same firmware.
- Five valid v2 RAW configurations and the unchanged pre-upgrade SDK passed
  physical checks. New-SDK/old-firmware compatibility uses fixtures/simulation;
  see [[protocol-v3-migration]] for the compatibility and rollback workflows.

## Verification and retention

Fresh offline independent validation passes all **62/62 cells**. The reused
release checker verifies all five supplemental outcomes, rejects six invalid
promotion controls, and verifies **500 protected inputs**, **633 master-report
references** and **1,558 historical evidence hashes**. All **19 retained promotion
evidence files** and the promotion report's release-manifest binding also match.
Documentation links, examples and repository-layout checks pass. Full source,
generator, lint, typing and package gates were already recorded in
[[release-1.2.0]]; this final task changes documentation only.

Frozen firmware, SDK archives/distributions and raw rig results remain in the
existing ignored local Working paths, verified by size/hash and explicitly not
published to Git. Raw results contain bounded frame samples and complete-run
counters, not full-duration USB dumps. No credentials, raw jobs, binaries or
unrelated files are added by this audit. No new rig jobs, rebuild or remote
package publication occurred.

The scope remains unstimulated transport/control qualification. Analog accuracy,
external waveform fidelity, calibrated pin mapping, external power, ambient/case
temperature and multi-hour continuous reliability are unmeasured. Three separately
reflashed ten-minute runs do not establish continuous thirty-minute endurance.
Peak die temperature was 68.597 °C; static RAM1/RAM2 reserves were 33,024/4,096
bytes. These are not runtime memory high-water measurements.
