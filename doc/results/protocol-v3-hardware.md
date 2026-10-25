---
type: report
title: Protocol v3 complete hardware qualification
created: 2026-10-25
tags:
  - protocol-v3
  - hardware
  - qualification
related:
  - '[[protocol-v3-release-candidate]]'
  - '[[protocol-v3-clock-control]]'
  - '[[protocol-v3-migration]]'
  - '[[protocol-v3-legacy-matrix-recovery]]'
  - '[[protocol-v3-lifecycle-hardware]]'
---

# Complete hardware qualification: PASS

Independent exact-candidate validation: **62/62 PASS**, zero FAIL, INCONCLUSIVE or NOT_RUN. All five supplemental identity/metadata/reset/old-SDK/mixed-version checks independently pass. Release promotion remains **PENDING**; this report does not change supported-release metadata.

## Tested artifact

- Candidate SHA-256: `14c14a82912a95482bb9146abb06e310b3d7f8c24bec37ef2274d13d4b9d4682`.
- Firmware HEX SHA-256: `827f8304497fcabcbc7b749eca03158b552d5dced674f93562e7642e5504341d`.
- SDK archive SHA-256: `c22e520af516077d4b92527699c6c602dd857d0ef4627c453f5a20be32090f1f`.
- Build `thingdaq-e0c750868be7c5c2`, firmware/SDK 1.2.0, Teensy 4.0 serial `20428100`.
- Candidate source revision: `94144fd32b35968c3f650d2c5927cfefd4e88343`; all 500 protected files and all retained artifacts verified.
- Defaults: fixed 600 MHz CPU, 1 MHz ADC/GPIO, GPIO RLE_AUTO, ADC PACK12, auxiliary bank DISABLED. INFO, capabilities, settings, configure echoes, STATUS and physical DWT/PIT/eDMA checks agree.

The original Phase 05 artifact in [[protocol-v3-release-candidate]] is historical. This report grades the corrected candidate above, frozen under `.maestro/playbooks/Working/phase06-legacy-matrix-corrected-20261025/frozen/`. Firmware was not rebuilt for this grading task. The immutable candidate snapshot still says NOT_RUN; the independently graded outcome is recorded here pending the separate promotion task.

## Matrix coverage

| Class | Cells | Result |
| --- | ---: | --- |
| Advertised v3 configurations | 48 | PASS |
| Complete synthetic RLE/RAW fallback captures | 2 | PASS |
| Documented v2 RAW configurations | 5 | PASS |
| Unsupported requests (18 rejections) | 1 | PASS |
| Twenty same-boot START/STOP cycles | 1 | PASS |
| Bounded 250 ms host stalls, both GPIO widths | 2 | PASS |
| Separately reflashed ten-minute endurance captures | 3 | PASS |

Normal captures pass sample/frame conservation, identity, clock, codec/source, parser, ownership, host-resource and thermal checks. Deliberate stall losses reconcile with wire gaps and firmware counters. Legacy incomplete STOP tails are explicitly bounded and reconciled separately from complete packets. No previous campaign passes are imported; all 1,558 historical evidence hashes remain unchanged.

## Supplemental physical checks

| Check | Result | Job |
| --- | --- | --- |
| identity | PASS | `4f199238-40ce-4ed3-b437-711b08360496` |
| metadata | PASS | `de0a4887-caa0-47e9-be1f-44790ce063d5` |
| reset_defaults | PASS | `ba4acb88-058d-4298-b335-ca02c672a8b0` |
| isolated_pre_upgrade_sdk | PASS | `9e8d1bd6-a044-492d-9e33-010500fe5bf6` |
| mixed_version_reconnect | PASS | `c66497ed-35e6-41ae-ac04-e5f7a646622b` |

The unchanged pre-upgrade SDK exercised five 60-second RAW configurations in one boot. Metadata covers repeated configuration, rejected RUNNING/DRAINING changes, actual acquisition, reset defaults and serial reconnect. The mixed-version probe exercises six same-boot captures with v3/v2 transitions and reconnect. See [[protocol-v3-migration]] for compatibility usage.

## Thermal, memory and measurement scope

Peak canonical on-chip temperature: **68.597 °C**, below the 80 °C abort gate. The three endurance runs lasted 600.020, 600.020 and 600.000 seconds; their peaks were 66.755, 67.983 and 68.597 °C. Each had zero wire gaps, firmware frame/item drops, parser/host errors or capture CPU throttling.

Frozen linker margins: **33,024 bytes RAM1** for locals/stack against a 32,768-byte minimum; **4,096 bytes RAM2** heap against a 4,096-byte minimum. These are static build gates, not measured runtime stack/heap high-water marks.

Per-cell counters, ownership, CPU intervals, thermal samples, wire throughput, encoding frequencies and codec timing are retained in the JSON. Codec ticks use 8 MHz and measure elapsed time including preemption; they are not total MCU utilization. Throughput is wire bytes/second; host core fraction is process CPU seconds/wall seconds. Retention is advertised capacity and codec deadline margin is observed, not a guaranteed stall tolerance. [[protocol-v3-clock-control]] describes fixed-clock behavior.

## Evidence classes and limits

- **Real acquisition:** physical Teensy with unstimulated inputs; hardware-source data, control continuity, clocks, STOP/drain and restart are exercised.
- **Physical synthetic source:** deterministic firmware-generated data verifies codecs and RAW fallback on the board; it does not measure external signals.
- **Host/simulated:** production-function and SDK harnesses cover fragmented/zero/partial writes, correlation and old-firmware fixtures. Prior full suite: 2,716 tests plus 17,118 subtests PASS, 11 expected skips; lifecycle suites: 457 tests plus 99 subtests PASS, six expected skips.
- **Externally stimulated:** NOT_RUN. No analog accuracy, calibrated pin mapping or external edge/waveform fidelity claim.
- **Analytic:** linker reserves, advertised retention and derived codec margins; no dynamic memory high-water or arbitrary-stall guarantee.
- **Unmeasured:** external power, ambient/case temperature, comparative power, power-removal reset and multi-hour uninterrupted reliability. Three reflashed ten-minute jobs are not uninterrupted 30-minute endurance.

## Reproduce the grading

Run from the repository root with the retained local raw evidence present:

```bash
.venv/bin/python firmware/tools/qualify_protocol_v3.py validate --candidate firmware/soak/protocol-v3-candidate.json --output .maestro/playbooks/Working/protocol-v3-qualification-legacy-matrix-fixed-20261025
```

Exit status was 0. The validator reconstructs each expected worker program, verifies submission/firmware/candidate/job identity and independently applies the frozen acceptance policy to authoritative saved results. It does not trust campaign summary PASS labels. No new rig submissions are needed.

All per-cell job IDs, hashes, exact worker program/provenance/submission paths, counters, supplemental grades and raw-evidence references are in [protocol-v3-hardware.json](protocol-v3-hardware.json). The report retains the complete candidate snapshot and tested distribution hashes. Large rig results, firmware and programs remain in ignored local Working storage under the existing retention convention; they are required for full replay and are not published by this commit. Raw results contain bounded wire samples plus complete-run oracle counters, not full-duration USB dumps.


Current report checks: pytest.log: 180 passed, 6 skipped, 1505 subtests passed in 26.10s; docs-pytest.log: 11 passed, 1514 subtests passed in 2.64s.
## Per-cell results

| Cell | Result | Job |
| --- | --- | --- |
| `smoke-010001030104000800000c0040420f0040420f00` | PASS | `0c3f3c69-a751-4c43-9228-88e7ea08d1fc` |
| `smoke-010001030104000800010c0040420f0040420f00` | PASS | `3d91f4e1-c6f6-42e7-98a4-bd4da4c575ed` |
| `smoke-010001030104000801000c0040420f0040420f00` | PASS | `11bb30be-0471-4fc9-8d1a-cb0ea5b362ea` |
| `smoke-010001030104000801010c0040420f0040420f00` | PASS | `c7ccd36f-3f09-4c22-9657-fe42e72d7466` |
| `smoke-010001030104011000000c0040420f0040420f00` | PASS | `df334a57-9339-4270-9f2c-e71f2f9a61b5` |
| `smoke-010001030104011000010c0040420f0040420f00` | PASS | `da804445-1c64-4609-a44f-36e7c9370fef` |
| `smoke-010001030104011001000c0040420f0040420f00` | PASS | `4b5da522-35f3-4599-928b-395552b002e0` |
| `smoke-010001030104011001010c0040420f0040420f00` | PASS | `016bcd46-f390-41c4-9f6d-aceadf286b8b` |
| `smoke-010101030104000800000c0040420f0040420f00` | PASS | `f78635c8-5e3e-4925-9506-76cc404533a2` |
| `smoke-010101030104000800010c0040420f0040420f00` | PASS | `a25a516d-9894-4a70-b383-f8740627c3a5` |
| `smoke-010101030104000801000c0040420f0040420f00` | PASS | `425625fc-6f9c-433f-8672-9aa28b96b5c8` |
| `smoke-010101030104000801010c0040420f0040420f00` | PASS | `23594d26-b662-4db2-a7f5-82494140cc3c` |
| `smoke-010101030104011000000c0040420f0040420f00` | PASS | `9e7329bc-0460-4e5b-9b44-3f7b1d50ebd3` |
| `smoke-010101030104011000010c0040420f0040420f00` | PASS | `9dc5bcd8-b595-44c1-8ed8-120783115f0c` |
| `smoke-010101030104011001000c0040420f0040420f00` | PASS | `5e1acaac-fad9-4db2-94e5-b4ac320df400` |
| `smoke-010101030104011001010c0040420f0040420f00` | PASS | `ec8fccfe-817b-4359-a49b-d0ac3c18986b` |
| `smoke-020001030104000800000c0040420f0040420f00` | PASS | `189c967d-4702-4000-b4e0-9c50416da449` |
| `smoke-020001030104000800010c0040420f0040420f00` | PASS | `ce487728-24ec-4012-be8e-cee84b40adf8` |
| `smoke-020001030104000801000c0040420f0040420f00` | PASS | `aa710d55-250e-4c92-9ecc-9adb38b3d46d` |
| `smoke-020001030104000801010c0040420f0040420f00` | PASS | `4a23a364-b53e-47e7-ae55-7f6895a001ed` |
| `smoke-020001030104011000000c0040420f0040420f00` | PASS | `de302c94-cafa-4625-9202-d6ff25ea51d8` |
| `smoke-020001030104011000010c0040420f0040420f00` | PASS | `de1619b7-beb1-444f-9ec2-c5f7bfac160a` |
| `smoke-020001030104011001000c0040420f0040420f00` | PASS | `5100d1a0-74d0-4601-8d30-9c79719bf540` |
| `smoke-020001030104011001010c0040420f0040420f00` | PASS | `7522aa8d-672d-471a-800a-fa2181b8591a` |
| `smoke-020101030104000800000c0040420f0040420f00` | PASS | `ba81cd2c-9f9e-4d24-b1cf-835a4ad5477f` |
| `smoke-020101030104000800010c0040420f0040420f00` | PASS | `799d6a49-88bf-4a89-8380-ac1f4afad48c` |
| `smoke-020101030104000801000c0040420f0040420f00` | PASS | `6543d826-c25d-4f6e-ae4a-5ed6a9a79bb8` |
| `smoke-020101030104000801010c0040420f0040420f00` | PASS | `64e1cf37-88ca-4dca-8c8f-3661ab57122d` |
| `smoke-020101030104011000000c0040420f0040420f00` | PASS | `d511f2ab-9ac8-4b12-83a5-a4962466e4f3` |
| `smoke-020101030104011000010c0040420f0040420f00` | PASS | `bb8f1b8f-c562-4ab3-a586-7737e3be11e5` |
| `smoke-020101030104011001000c0040420f0040420f00` | PASS | `0e73f441-839e-4253-8a96-22a39a5f85f8` |
| `smoke-020101030104011001010c0040420f0040420f00` | PASS | `a967ab4b-86a0-43dd-abd3-0adca5ba830d` |
| `smoke-030001030104000800000c0040420f0040420f00` | PASS | `e5c65bb9-2ed5-4f76-aef8-6b665c084bdd` |
| `smoke-030001030104000800010c0040420f0040420f00` | PASS | `b30fd26e-8c6b-4e6a-9716-77c11cd398f2` |
| `smoke-030001030104000801000c0040420f0040420f00` | PASS | `bd4955eb-9b4c-4cdc-965b-91b38042c080` |
| `smoke-030001030104000801010c0040420f0040420f00` | PASS | `89390bdb-9071-48c2-b142-7a7d72c4f137` |
| `smoke-030001030104011000000c0040420f0040420f00` | PASS | `d1093f61-3b29-48ea-a8f9-eafa3af55892` |
| `smoke-030001030104011000010c0040420f0040420f00` | PASS | `9a59d83e-d774-45d2-84b5-12a90346ae9f` |
| `smoke-030001030104011001000c0040420f0040420f00` | PASS | `f2492682-89cd-4df3-aa4f-5b0df8dcf6f0` |
| `smoke-030001030104011001010c0040420f0040420f00` | PASS | `6e17107d-ad8e-4cfe-b64e-04303d3a674b` |
| `smoke-030101030104000800000c0040420f0040420f00` | PASS | `b42d46d3-cfe5-4271-b173-d9b59fbfc403` |
| `smoke-030101030104000800010c0040420f0040420f00` | PASS | `9f9997ce-a2bf-4ec3-abed-7691c78c095a` |
| `smoke-030101030104000801000c0040420f0040420f00` | PASS | `42bc5ff9-d507-4afe-baf2-0cf6b4f8b854` |
| `smoke-030101030104000801010c0040420f0040420f00` | PASS | `4a3f385a-b759-4a2e-ba6b-0f36b0f8ffdb` |
| `smoke-030101030104011000000c0040420f0040420f00` | PASS | `ccffafbf-4fc8-4160-8abf-de8e392d6307` |
| `smoke-030101030104011000010c0040420f0040420f00` | PASS | `28a08531-a20c-41bf-8955-51d91beec411` |
| `smoke-030101030104011001000c0040420f0040420f00` | PASS | `eb1d17fe-0766-44c6-919e-e0605fbd2265` |
| `smoke-030101030104011001010c0040420f0040420f00` | PASS | `90394d4e-3d5a-4224-818a-aa8196b75c29` |
| `same-boot-20` | PASS | `409c3d90-eb5f-4f2a-a1fe-ae76f7a330dc` |
| `soak-1` | PASS | `494d9c0c-0b16-49b4-bc4b-c0a55705ad82` |
| `soak-2` | PASS | `fe3aab1a-d798-4e37-b9ca-428c5acf0ae2` |
| `soak-3` | PASS | `6e578843-79af-4256-bc93-2febec50f412` |
| `stall-0` | PASS | `77c1e293-8433-47a9-8496-1b8f652c1b26` |
| `fallback-0` | PASS | `9d37baf6-4740-4494-8be2-170ef9a5bca3` |
| `v2-0-1` | PASS | `a70e9f3c-88da-40d4-abc3-7572fc7cd66d` |
| `v2-0-2` | PASS | `338c2782-998e-4b63-a64a-f5e53007bc48` |
| `v2-0-3` | PASS | `7966be1b-dae9-4941-8cef-2df5a4e9acdf` |
| `stall-1` | PASS | `463bf29a-d500-429c-a911-cd8be13d5452` |
| `fallback-1` | PASS | `c2b79b4f-41f5-4cbf-9b85-f0f29cd69627` |
| `v2-1-2` | PASS | `3166abbe-e063-4fe9-9dbd-eb78055044b5` |
| `v2-1-3` | PASS | `f74bb5ac-6bfd-4ac2-9045-3fa3662024f8` |
| `unsupported` | PASS | `dbb826d2-81d8-4817-b57c-ed71b62e28e5` |
