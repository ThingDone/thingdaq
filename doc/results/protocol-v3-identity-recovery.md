---
type: report
title: Public v3 startup fault diagnosis and replacement candidate
created: 2026-10-24
tags:
  - protocol-v3
  - hardware
  - qualification
  - startup
related:
  - '[[protocol-v3-rig-verification]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-qualification]]'
---

# Startup fault and replacement candidate

The original frozen candidate faults during global runtime construction because
its clock-table reference resolves to address zero. The generator correction is
pushed in `b5869d5`; independent regression coverage is in `e1a4988`.
**Replacement live identity: pending. Physical measurements: NOT_RUN.**

## Diagnosis and retained failures

The saved job `20005b76-64a0-43c3-88a8-347d7676d2c9` was reconciled through the
rig's `/status`: terminal, completed. Its original FAIL is unchanged in
[[protocol-v3-rig-verification]]. A fresh zero-capture identity job
`e0789e19-da36-4883-9698-9222ec3a1d9e` reproduced INFO timeout with zero bytes
after a successful first-attempt flash. This establishes that the old upload
retry alone did not explain the failure.

Raw INFO-only job `ff615b5a-70e6-4767-88cf-2de7bbb56983` enumerated serial
`20428100`, asserted DTR, and sent complete 48-byte v3 and v2 INFO requests.
It received no bytes and then disconnected. A diagnostic-only image in job
`5cb4237d-8af4-4724-a965-45ce48efb190` observed disconnects at 7.74, 16.44,
and 25.40 seconds, consistent with the pinned core's eight-second fault reboot.
CDC fault reporting itself produced no bytes.

Diagnostic job `a995b69f-7742-470b-9558-be6e6cfb85d4` exposed the retained
fault PC through the USB product descriptor, without depending on CDC. Repeated
readbacks were `60008abc`. The diagnostic ELF maps that PC to
`settings::record<24>()` in `v3_settings.h`, in the runtime constructor:
`ldr.w r0, [ip]`, with the literal source pointer **0x00000000**.
The same instruction and zero literal occur in the original frozen ELF.
These instrumented images are diagnosis only and cannot qualify a release.

All generated inline record tables shared `.progmem.protocol_v3.tables`.
Translation units emit different subsets of these objects. Link-time COMDAT
selection retained the tuple-only section and discarded the clock/rate tables;
the original ELF contains the configuration table but no `kCpuProfiles` or
`kRateProfiles` symbols. Giving each table its own section preserves independent
selection. No clock values, protocol bytes, SDK behavior, or retry policy changed.

The regression links a translation unit using only tuples ahead of one using
all four tables, with target section attributes and garbage collection enabled.
The old header fails linking with missing default/CPU/rate tables; the corrected
header links and emits every table byte exactly. All 66 generator tests pass.
The corrected target ELF also places both CPU and rate tables in program flash.

## Replacement freeze

The active manifests remain `firmware/soak/protocol-v3-candidate.json` and
`firmware/soak/protocol-v3-candidate-freeze.json`. Exact original manifests are
archived under `firmware/soak/history/*-20261020.json`; original artifact bytes
remain under `.maestro/playbooks/Working/phase05-freeze/`. Historical results
remain bound to their original candidate and are not replacement acceptance.

| Field | Replacement |
| --- | --- |
| Source revision | `e1a4988` (full revision in candidate) |
| Build ID | `thingdaq-5c7c7201f63665fd` |
| HEX SHA-256 | `33ff95d8f37b6ebd51457eae66c323ca99b82efe692b1b4994d2d05700398b2a` |
| Artifact root | `.maestro/playbooks/Working/phase06-candidate-20261024/` |
| Expected hardware serial | `20428100` |
| Target | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |

Two clean builds reproduced HEX/ELF/MAP/EEP and the manifest exactly. Both passed
existing placement, allocation-ownership, RAM1 (33,024-byte locals headroom) and
RAM2 (4,096-byte heap headroom) gates. The freeze protects 498 files and retains
15 artifacts, with the unchanged 63-job matrix. SDK, schema, and runner hashes
remain unchanged; the exact validated wheel/sdist bytes are reused because no
package input changed. Toolchain remains Arduino CLI 1.4.1, Teensy core 1.62.0,
and Arm GNU 15.2.1. Defaults remain fixed 600 MHz, 1 MHz ADC/GPIO, auxiliary
DISABLED, GPIO RLE_AUTO, ADC PACK12.

Recovery evidence is retained under
`.maestro/playbooks/Working/phase06-identity-recovery-20261024/`. Each accepted
job has its own saved submission/job ID and result; HTTP uses the established
runner with queue-aware timeouts and 30-second/ten-minute 5xx recovery.
No acquisition or compatibility measurement has run.

Use the active candidate's artifact paths, not the superseded Phase 05 paths:

```bash
.venv/bin/python firmware/tools/freeze_soak_candidate.py --check \
  --lock firmware/soak/protocol-v3-candidate-freeze.json
.venv/bin/python firmware/tools/qualify_protocol_v3.py plan \
  --candidate firmware/soak/protocol-v3-candidate.json
```
