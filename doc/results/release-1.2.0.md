---
type: report
title: Supported ThingDAQ 1.2.0 release
created: 2026-10-25
tags:
  - release
  - protocol-v3
  - hardware
related:
  - '[[protocol-v3-hardware]]'
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-migration]]'
  - '[[protocol-v3-clock-control]]'
  - '[[firmware-builds]]'
  - '[[release-1.1.0]]'
---

# Supported ThingDAQ 1.2.0

The exact frozen firmware and SDK below are **SUPPORTED**, with **62/62 physical
qualification cells PASS** and all five supplemental checks PASS. Promotion is
metadata only: firmware, SDK, schemas, runner inputs and acceptance gates retain
their tested bytes. No remote package publication or new rig job was performed.
The machine-readable authority is
[protocol-v3-release.json](../../firmware/soak/protocol-v3-release.json).

## Exact supported artifacts

| Identity | Value |
| --- | --- |
| Candidate semantic SHA-256 | `14c14a82912a95482bb9146abb06e310b3d7f8c24bec37ef2274d13d4b9d4682` |
| Candidate source revision | `94144fd32b35968c3f650d2c5927cfefd4e88343` |
| Firmware / SDK / wire versions | 1.2.0 / 1.2.0 / 3 |
| Firmware build ID | `thingdaq-e0c750868be7c5c2` |
| Firmware HEX SHA-256 | `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d` |
| Tested SDK ZIP SHA-256 | `c22e520af516077d4b92527699c6c602dd857d0ef4627c453f5a20be32090f1f` |
| Retained wheel SHA-256 | `8ba2f35029405407582ef699e4cad3b2d3a210c93d11ffc0b64cff3eb36ee51c` |
| Retained sdist SHA-256 | `701d4559e426591683eae72773c78d88de80d38e24c30516d860767dbbd0f22f` |
| Tested board | Teensy 4.0, serial `20428100` |

The manifest records exact local paths, sizes and hashes. Firmware remains under
`.maestro/playbooks/Working/phase06-legacy-matrix-corrected-20261025/frozen/`;
SDK distributions remain under `.maestro/playbooks/Working/phase05-freeze/distributions/`.
These large artifacts and raw rig evidence are retained locally in ignored
Working storage, not hosted by the Git repository. Install the retained wheel
or unchanged checkout SDK; published package availability is a separate process.

The frozen candidate's `physical_qualification: NOT_RUN`, master hardware
report's `release_promotion: PENDING`, and packaged README/changelog describe
their original freeze/grading checkpoints. They remain byte-identical for
provenance and reproducibility. This release manifest and current guides
supersede those historical status statements; neither the original Phase 05
firmware nor any failed intermediate candidate is promoted.

## Defaults and compatibility

Defaults are fixed **600 MHz CPU**, **1 MHz ADC pairs and GPIO samples**,
**12-bit ADC PACK12**, **GPIO RLE_AUTO**, and **auxiliary DISABLED** (8 GPIO
inputs). INPUT selects 16 inputs. RAW and compressed policies share the same
binary and change only while stopped. CPU switching remains unsupported.
Use exact advertised tuples and per-sample timestamps; the equal-frame
`TimestampAligner` does not support these layouts.

All 48 advertised v3 configurations, both deterministic RLE/RAW fallback cells,
and all five valid v2 RAW configurations passed. Unchanged pre-upgrade SDK
revision `3a52ead02791019fcdb0b27a8be869effc955aa2` separately passed five
60-second physical captures, discovery, configuration, diagnostics, STOP and
same-boot restart. Auxiliary INPUT requires GPIO in v2; ADC-only uses DISABLED.
Legacy incomplete STOP tails are bounded and reconciled explicitly. See
[[protocol-v3-migration]] for the isolated v2 workflow and mixed-version use.
New-SDK/old-v1/v2 checks use local fixtures/simulators, not physical old firmware.

Rollback firmware 1.1.0 remains tied to source revision
`e3e8417598de7494db3a93d7277ef8f0ec31bc8f`, its 450 MHz build recipe, and
[[release-1.1.0]]. Follow [[firmware-builds]] to reproduce that separate artifact;
current sources built at 450 MHz are not the historical release.

## Evidence and limits

[[protocol-v3-hardware]] and its JSON retain all jobs, measurements and raw
references. Independent replay verifies identity, exact matrix membership,
sample conservation, codec recovery, clocks, normal-capture health and counted
deliberate loss. Supplemental checks cover live identity, metadata, programming
reset/default restoration, unchanged old SDK, and mixed-version reconnect.

Twenty same-boot START/STOP cycles and both 250 ms host stalls passed. Three
separately reflashed ten-minute default-codec captures passed with zero
unexpected loss or DMA/parser/host errors. Peak canonical die temperature was
**68.597 °C**, below the 80 °C cutoff. Qualification verified two allocated host
cores; an underprovisioned host is not covered by a lossless guarantee.
RAM1/RAM2 static reserves are **33,024 / 4,096 bytes**, not runtime high-water
measurements. Watchdog initialization remains disabled.

Unstimulated physical acquisition proves transport/control continuity;
deterministic firmware sources exercise sample recovery and fallback. Neither
establishes analog accuracy, calibrated pin mapping or external waveform
fidelity. External power, ambient/case temperature, power-removal reset and
multi-hour uninterrupted reliability were not measured. Three reflashed
ten-minute captures are not continuous thirty-minute endurance. Full-duration
USB payloads are not retained; raw evidence includes bounded frame samples and
complete-run counters/hashes. Historical failures remain unchanged.

## Promotion validation

Validation results and commands are retained in
[release-1.2.0-validation.json](release-1.2.0-validation.json).

- Independent canonical replay: 62/62 PASS; all 500 protected inputs unchanged.
- Full firmware/SDK regression: 2,716 tests and 17,159 subtests PASS; 11 expected skips.
- Generated protocol drift: all 142 outputs current. Ruff lint and SDK MyPy pass.
- Release references: 633 master-report and 1,558 historical hashes verified;
  six invalid promotion mutations rejected.
- Package contents: all 34 Python runtime files match the tested SDK ZIP;
  the typed marker also matches the frozen wheel, sdist and checkout. Reproduced
  wheel is byte-identical; sdist file paths, modes and bytes are identical,
  while archive metadata differs. Strict Twine checks, isolated wheel install,
  dependency check, upgrade demo and strict simulated v3 capture pass.

An additional repository-wide format audit reports one pre-existing formatting
finding in `firmware/tests/test_adc_dma_interrupt_order.py` (202 other files
pass). Its bytes match the qualified source revision. This metadata/documentation
promotion changes no Python or protected inputs; the optional audit finding is
retained separately from the passing applicable gates.
