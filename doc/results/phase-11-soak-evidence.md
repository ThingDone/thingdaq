---
type: report
title: Phase 11 Autonomous Soak Evidence
created: 2026-08-29
tags:
  - thingdaq
  - phase-11
  - endurance
  - hardware-validation
  - release-candidate
  - reproducibility
related:
  - '[[Evidence-Index]]'
  - '[[soak-harness]]'
  - '[[Hardware-Safety]]'
  - '[[Protocol-V1]]'
  - '[[Phase-04-Synthetic-Streaming]]'
  - '[[Phase-08-Combined-Acquisition]]'
  - '[[Phase-09-Loss-Recovery]]'
  - '[[Phase-10-Package-Local-Gate]]'
  - '[[Phase-10-Package-Workflows]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[ADR-003-GPIO-Clock-DMA]]'
  - '[[ADR-004-ADC-Trigger-DMA]]'
---

# Phase 11 autonomous soak evidence

## Outcome

The Phase 11 autonomous release-candidate gate passed on 2026-08-29. The
fail-closed release aggregator accepted exactly two 600-second synthetic jobs,
three 600-second physical-combined jobs, and one 600-second control-stress job.
All six jobs were sequential, shared one firmware/source/protocol/HEX identity,
contained every required evidence field, and passed the independent records,
identity, duration, rate, latency, resource, conservation, and campaign-lineage
checks.

The accepted jobs accumulated 3,605.008125 measured seconds, 3,574.547822
streaming seconds, 28,595,177,248 payload bytes, and 28,934,250,496 framed
bytes. Normal streaming intervals had zero complete-frame loss, parser damage,
checksum/formula/order/timestamp errors, host-queue loss, and required
hardware/transport error counters. The sole deliberate loss case was named,
bounded, and reconciled exactly.

This is the autonomous acceptance decision. No release was tagged, no package
was uploaded or published, and the later Windows run is additive evidence rather
than a prerequisite. See [[Evidence-Index]] for the complete cross-phase map.
No task-associated images were present; zero images were analyzed.

## Post-campaign local gate

The complete gate ran from Git revision
`8517befc450d17e5684b4884c0ff69cd984046ad`. The documentation added by this
report is outside the 240-file candidate freeze; repeated freeze checks before
and after the executable gates proved that no package, protocol, firmware,
harness, generated program, test, or example input changed.

| Gate | Result |
| --- | --- |
| Candidate freeze | PASS before, during, and after the gate; 240 protected files, tree SHA-256 `84636113d34bdadef466d94c6c44180d2e591f3dc99ed346b32a8bd3b4a15dbc` |
| Generated protocol | PASS; all 26 outputs current |
| Generated soak programs | PASS; all three deterministic outputs current |
| Ruff format / lint | PASS; 120 files formatted, no lint findings |
| MyPy | PASS; no issues in 26 package/generator/freezer/aggregator sources |
| Full suite without NumPy | PASS; 386 tests, 7 expected skips, 13,899 subtests |
| Full suite with NumPy 2.5.2 | PASS; 393 tests, no skips, 13,899 subtests |
| Parser throughput | PASS; 16,596,992 wire bytes, minimum 2.042051x and median 3.176368x headroom over 8,094,861.660 B/s |
| GPIO packing throughput | PASS; 2,207.399 MB/s against the 40 MB/s guard and 4 MB/s payload target |
| Distribution builds | PASS; two independent PEP 517 builds, identical wheel bytes and identical normalized wheel/sdist contents |
| Clean installed-package workflows | PASS; CPython 3.10.19, 3.11.14, 3.12.3, 3.13.12, and 3.14.3 wheel installs plus a CPython 3.12.3 NumPy sdist install |
| Pinned Teensy build | PASS; EEP, ELF, HEX, and map reproduced their frozen byte hashes |
| Release aggregation | PASS; 6 accepted, 20 explicitly excluded, 0 infrastructure incidents, all 8 release checks true |

Each base-only wheel environment contained only the package and PySerial 3.5,
had no NumPy, passed `pip check`, isolated import/version/`py.typed` checks,
simulator INFO and strict-loss capture, the complete demo, and all nine examples.
The clean sdist environment added NumPy 2.5.2 and the declared development
dependencies; it passed the complete suite and the same installed workflows.
Strict installed-package MyPy consumers passed for both wheel and sdist.

The retained final-gate workspace is
`.maestro/playbooks/Working/phase-11-final-gate-00001`. It contains the two
source snapshots, both distribution pairs, clean environments, and the compiled
packer benchmark. It contains no credential and no bulk acquisition capture.

## Immutable candidate and toolchain identity

| Property | Accepted value |
| --- | --- |
| Gate checkout | `8517befc450d17e5684b4884c0ff69cd984046ad` |
| Freeze base commit | `399d8a7c222584edef0df074e021136f388808ad` |
| Frozen build-manifest provenance commit | `26d1035c6723fae5872f9207121e4d5eed99d20f` |
| Protected tree | 240 files; SHA-256 `84636113d34bdadef466d94c6c44180d2e591f3dc99ed346b32a8bd3b4a15dbc` |
| Candidate semantic SHA-256 | `32dcf73bc99f5abc53935901baa4f14103df339e1aafbe71ef3330f3b79d8656` |
| Firmware source ID | `a0dc150fd48a6e9b62c614fe487d533f6c7c90bee6c7d5cd3c9f8e985e0b49ba` |
| Firmware build ID | `thingdaq-a0dc150fd48a6e9b` |
| Firmware / protocol / checksum | 0.7.0 / v1 / Adler-32 algorithm 1 |
| Target | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Board identity | Teensy 4.0 / i.MX RT1062, board ID 1, MCU ID 1, hardware serial `20512460` |
| Package source tree | Git tree `36181ae8291d759e53f185dc7940e124656eab22` at the gate checkout |
| Package version | private local distribution `thingdaq-local` 0.10.0 |
| Soak service | `remote-firmware-testing` 1.0.0, API v1 |
| Service-owned client | 1.0.0; SHA-256 `23115388d9a62384cca074ac976c24986d77bd98538713901db3ec810e5c84ec` |

The accepted job programs were self-contained Python 3.13.13 scripts using
only the standard library and PySerial. Their exact executed identities were:

| Mode | Program SHA-256 | Validator SHA-256 |
| --- | --- | --- |
| Synthetic | `09cbc4d860c44a4ced0e3bdb257295b677a3b8d30e29afe5cf349ba6bb34c350` | `acfe54307aea6d92d087997dc63d2c93cbdf63e9fe1bd25fc8db2a5eb91fc7cd` |
| Physical combined | `9d537c53b5ec09c4e06a2eb195f69e27955ef1bf314205055d2f1538cddfd940` | `4075c735fae366887f6c4417e4c524e544a5ace7cf24d11156acf91444043fb5` |
| Control stress | `ccb4c92864ac0a189d185da38e3f374882077eb1421c87c80edf1fa6bbdb7400` | `acfe54307aea6d92d087997dc63d2c93cbdf63e9fe1bd25fc8db2a5eb91fc7cd` |

The physical job retains its executed pre-control-extension validator snapshot.
Later control-only loss/reopen evidence extended the canonical validator, so
the final generated physical file has a newer validator digest; the executed
program above remains the authority for the physical bundles and is preserved
with them rather than retroactively rewritten.

| Build tool | Exact identity |
| --- | --- |
| Arduino CLI | 1.4.1, commit `e39419312` |
| Teensy core | `teensy:avr` 1.62.0 |
| Target compiler | `arm-none-eabi-g++ (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203` |
| Host compiler | Ubuntu `g++` 13.3.0 |
| Local Python | CPython 3.12.3 |
| Package tools | Setuptools 84.0.0, build 1.6.0, pytest 9.1.1, Ruff 0.16.5, MyPy 2.3.1, PySerial 3.5 |
| Host | Linux 6.17.0-35-generic x86-64, glibc 2.39 |

The linked image retained 34,528 RAM1 bytes for locals/stack and 4,096 RAM2
bytes for heap. It used 94,356 flash code bytes, 23,496 initialized-data bytes,
9,120 header bytes, a 200-frame/819,200-byte packet pool, 33,312 bytes of ADC
DMA storage, 64,960 bytes of raw GPIO DMA storage, and 16,256 bytes of packed
GPIO storage.

### Firmware reproduction

| Artifact | Bytes | Frozen and rebuilt SHA-256 | Result |
| --- | ---: | --- | --- |
| `firmware.ino.eep` | 34 | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` | byte-identical |
| `firmware.ino.elf` | 1,808,808 | `d656c0f93212d2f2c33bf8391c59fbf1843a567b94d55d2601cab2d4bcd0eb89` | byte-identical |
| `firmware.ino.hex` | 357,214 | `0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a` | byte-identical |
| `firmware.ino.map` | 830,863 | `b023e30fe587ca7855e632487f859fa441f3b60c8c831a0ad7d5b624909530c7` | byte-identical |

The frozen manifest SHA-256 was
`6741c3fe10c44b8d7ff5666ddfd9a6eba2147c584e687e34794a1165e9af384b`;
the post-campaign manifest SHA-256 was
`5ade1ab272f941d2bf34a5f5dd47f4e0557fded771f744eaa1aab931ac99c354`.
Their sole byte-level difference is the provenance `git_commit` field
(`26d1035…` versus `8517bef…`). Source ID, build ID, timestamp epoch
`1788036685`, target, compiler, memory/resource inspection, and all four
artifact records are identical. The manifest provenance change is therefore
not a firmware-reproduction failure.

### Distribution reproduction

Two independent `git archive` snapshots of the exact gate checkout were built
with CPython 3.12.3, isolated Setuptools 84.0.0, `PYTHONHASHSEED=0`, and
`SOURCE_DATE_EPOCH=1788036685`. Build A established the current protected-tree
record and build B independently reproduced it.

| Build | Artifact | Bytes | Archive SHA-256 |
| --- | --- | ---: | --- |
| A | `thingdaq_local-0.10.0-py3-none-any.whl` | 178,120 | `a086facfc564ae5d2a4c143556aa6a8487ff65f19eb2879b99a8d0d846153c31` |
| B | `thingdaq_local-0.10.0-py3-none-any.whl` | 178,120 | `a086facfc564ae5d2a4c143556aa6a8487ff65f19eb2879b99a8d0d846153c31` |
| A | `thingdaq_local-0.10.0.tar.gz` | 195,949 | `d537004ddd3af9e7ac1199d263c392082f25c946b66638a813acb26d718f7136` |
| B | `thingdaq_local-0.10.0.tar.gz` | 195,953 | `1f51a3eab60d627ab7751da50a7f20da6ba506894033b73b90fc710248e56f90` |

| Normalized set | Members | Build A SHA-256 | Build B SHA-256 |
| --- | ---: | --- | --- |
| Wheel paths, modes, and bytes | 29 | `d496b9a0c8e11181cea1c356ee8c278fe69db381424d25c9015bf868167dbdaa` | `d496b9a0c8e11181cea1c356ee8c278fe69db381424d25c9015bf868167dbdaa` |
| Sdist paths, modes, and bytes | 45 | `297fa155bfb905a5984764edcf954ab7536c99b42c77f70b7fa8cbadf48807d0` | `297fa155bfb905a5984764edcf954ab7536c99b42c77f70b7fa8cbadf48807d0` |

The gzip containers retain nondeterministic wrapper metadata, so their raw
hashes are reported rather than claimed equal. Their complete normalized
contents reproduce exactly. The earlier Phase 10 archives in
[[Phase-10-Package-Local-Gate]] remain valid historical artifacts for their
source revision; Phase 11 intentionally changed generated protocol constants,
so the current protected-tree distribution record is the table above.

## Accepted jobs

Every interval below is a client-observed UTC interval. Jobs did not overlap.
The accepted control job has 600 nominal measured seconds and 604.998386
campaign seconds because its 49 epochs include bounded control/reopen work;
its throughput denominator is the 574.538083 streaming seconds.

| Mode / sequence | Job ID | UTC start | UTC completion | Measured s | Streaming s |
| --- | --- | --- | --- | ---: | ---: |
| Physical 1 | `bed9b04d-f1e4-4b31-820b-e51075c8e1aa` | 2026-08-29 20:55:01Z | 2026-08-29 21:05:14Z | 600.000474 | 600.000474 |
| Physical 2 | `8e83ad24-469f-46a3-8bf7-8d8149eea6f8` | 2026-08-29 21:06:42Z | 2026-08-29 21:16:56Z | 600.001406 | 600.001406 |
| Physical 3 | `f7c5aebb-5591-4656-8f29-dfb0ae2db2ad` | 2026-08-29 21:17:36Z | 2026-08-29 21:27:49Z | 600.000473 | 600.000473 |
| Control 1 | `ad2ea61c-e17d-4b2f-bc72-47eb3e3d6f1a` | 2026-08-29 22:17:52Z | 2026-08-29 22:28:09Z | 604.998386 | 574.538083 |
| Synthetic 1 | `3d20bf96-044b-436f-bcc2-5df5b55fa026` | 2026-08-29 22:53:31Z | 2026-08-29 23:03:44Z | 600.001444 | 600.001444 |
| Synthetic 2 | `98efca60-aad2-4a93-a857-182408ed0dde` | 2026-08-29 23:04:31Z | 2026-08-29 23:14:44Z | 600.005942 | 600.005942 |

### Throughput and logical rates

| Mode / sequence | Payload bytes | Payload B/s | Framed B/s | ADC pairs/s | GPIO samples/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Physical 1 | 4,799,972,672 | 7,999,948.128 | 8,094,809.173 | 999,993.516 | 3,999,974.064 |
| Physical 2 | 4,799,968,624 | 7,999,928.967 | 8,094,789.785 | 999,991.964 | 3,999,961.110 |
| Physical 3 | 4,799,956,480 | 7,999,921.166 | 8,094,781.892 | 999,990.146 | 3,999,960.583 |
| Control 1 | 4,595,305,792 | 7,998,261.429 | 8,093,102.473 | 999,773.872 | 3,999,165.943 |
| Synthetic 1 | 4,799,968,624 | 7,999,928.458 | 8,094,789.270 | 999,990.214 | 3,999,967.602 |
| Synthetic 2 | 4,800,005,056 | 7,999,929.199 | 8,094,790.020 | 999,991.150 | 3,999,964.600 |

### Latency and bounded resources

| Mode / sequence | STATUS p99 / max ms | Any-command max ms | Packet owned HWM / 200 | RSS growth B | Traced growth B | Minimum available B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Physical 1 | 2.199 / 3.092 | 21.591 | 101 | 319,488 | 39,507 | 251,469,824 |
| Physical 2 | 2.309 / 3.113 | 21.792 | 121 | 348,160 | 39,555 | 251,817,984 |
| Physical 3 | 2.165 / 3.150 | 21.574 | 94 | 307,200 | 39,501 | 251,568,128 |
| Control 1 | 2.906 / 3.147 | 22.185 | 200 | 1,683,456 | 43,432 | 249,090,048 |
| Synthetic 1 | 8.518 / 59.672 | 59.672 | 134 | 790,528 | 43,334 | 250,437,632 |
| Synthetic 2 | 9.116 / 53.776 | 53.776 | 138 | 761,856 | 43,326 | 250,433,536 |

The worst accepted STATUS p99, STATUS maximum, and any-command maximum were
9.116, 59.672, and 59.672 ms against the 100, 250, and 500 ms limits. Maximum
RSS and traced growth were 1,683,456 and 43,432 bytes against 32 MiB and 16 MiB
limits. The control pressure case intentionally reached all 200 packet owners;
it remained within the advertised fixed pool and reconciled every eviction.

## Cross-run trends

| Mode | Payload B/s min–max | Framed B/s min–max | ADC pairs/s min–max | GPIO samples/s min–max | Resource sequence |
| --- | --- | --- | --- | --- | --- |
| Synthetic (2) | 7,999,928.458–7,999,929.199 | 8,094,789.270–8,094,790.020 | 999,990.214–999,991.150 | 3,999,964.600–3,999,967.602 | owned 134,138; RSS 790,528,761,856; traced 43,334,43,326 |
| Physical (3) | 7,999,921.166–7,999,948.128 | 8,094,781.892–8,094,809.173 | 999,990.146–999,993.516 | 3,999,960.583–3,999,974.064 | owned 101,121,94; RSS 319,488,348,160,307,200; traced 39,507,39,555,39,501 |
| Control (1) | 7,998,261.429 | 8,093,102.473 | 999,773.872 | 3,999,165.943 | owned 200; RSS 1,683,456; traced 43,432 |

Synthetic payload/framed relative spread was below `9.2641e-8`; physical
payload/framed relative spread was below `3.3703e-6`. Both are far inside the
one-percent limit. The physical rates decreased by only 0.000337% from their
maximum to minimum, while queue and memory series were not monotonically
increasing. The two-run synthetic resource series was bounded and its memory
measurements decreased. A single control run supports bounds, not a cross-run
trend claim. No mode showed a worsening hardware or transport error counter.

## Acceptance rules and equations

The `phase-11-release-v1` policy failed closed on a missing field. It required:

- exactly 2 synthetic, 3 physical-combined, and 1 control-stress accepted job;
- nominal and observed duration of at least 600 seconds for every job;
- one exact source ID, build ID, firmware version, protocol version, and HEX
  digest across the accepted set, plus one executed-program digest per mode;
- globally sequential client timestamps and exact agreement with all three
  accepted/excluded campaign indexes;
- payload, framed, ADC, and GPIO rates within 1% per mode;
- STATUS p99 at most 100 ms, STATUS maximum at most 250 ms, and any command at
  most 500 ms;
- RSS growth at most 32 MiB, traced growth at most 16 MiB, every queue within
  its advertised capacity, and no three-run monotonic resource growth;
- clean parsers, complete formula/fixture evidence, final IDLE, and zero
  required hardware/transport error counters; and
- exact stage, item, byte, loss, and campaign-lineage conservation.

For every source `s` (`adc` or `gpio`) and every epoch, the final counter
snapshot satisfied these frame-stage equations:

```text
generated_s = transmitted_s + dropped_s
generated_s = transmitted_s + dropped_s + filling_s + ready_s + transmitting_s
framed_s = transmitted_s + ready_s + transmitting_s + dropped_after_framing_s
emitted_s = transmitted_s + transmitting_s + dropped_after_promotion_s
```

Final IDLE made all three queue-depth terms zero. At each stage, ADC item counts
equaled frames times 1,012 pairs and GPIO item counts equaled frames times 4,048
samples. ADC payload bytes equaled pair counts times four; GPIO payload bytes
equaled sample counts; every framed byte count equaled frames times 4,096.
Timed evidence independently satisfied:

```text
adc_pairs = adc_frames * 1,012
gpio_samples = gpio_frames * 4,048
payload_bytes = adc_pairs * 4 + gpio_samples
framed_bytes = (adc_frames + gpio_frames) * 4,096
total_payload = adc_payload + gpio_payload
total_framed = adc_framed + gpio_framed
```

For synthetic pair index `i`, every ADC pair was
`((2*i) & 0x0fff, (2*i + 1) & 0x0fff)` and its timestamp advanced eight ticks.
For synthetic GPIO sample index `j`, every byte was `j & 0xff` and its
timestamp advanced two ticks. All 26 synthetic epochs validated every payload
item, not only samples.

Physical STOP tails were bounded outside normal streaming and reconciled as
410/1,644, 412/1,652, and 395/1,587 ADC-pair/GPIO-sample items. Physical run 2
also observed one completion mismatch and one incomplete conversion at that
STOP boundary; active-stream mismatches remained zero and the final equations
were exact.

The named `serial_read_stall_pressure` case deliberately stopped host reads
for 0.250274 seconds while control run 1 remained RUNNING. Its loss equations
were:

```text
ADC:  148 frames * 1,012 pairs = 149,776 pairs = 599,104 payload bytes
GPIO: 148 frames * 4,048 samples = 599,104 samples = 599,104 payload bytes
packet_pressure_evictions = 148 + 148 = 296
packet_pool_exhaustions = packet_pressure_evictions = 296
packet_capacity_drops_without_evictable_frame = 0
```

Exactly three chronological successor records carried both `GAP_BEFORE` and
`OVERRUN_BEFORE`; their split still represented 148 missing frames per source.
Every other normal epoch had zero complete-frame loss. All 54 epochs conserved,
including this one named negative case.

## Excluded job lineage

The release gate retained every submitted non-counting job. There were 15
test/product/harness failures and five clean-but-superseded passes. There were
no upload, service, worker, or container incidents and therefore no
infrastructure retry. All intervals are UTC client timestamps.

### Synthetic exclusions

| Job ID | UTC interval | Classification | Reason |
| --- | --- | --- | --- |
| `f57b475d-dbd7-4091-bcd5-09a313a76f84` | 16:16:19Z–16:16:30Z | `test_failure` | Synthetic GPIO legacy STATUS used inactive physical-packer counters. |
| `ea6e220f-7e6d-49ca-9b64-ddd60b42b657` | 16:23:24Z–16:23:37Z | `test_failure` | Continuous allocation/filesystem memory tracing backpressured the full-rate stream. |
| `d1266d62-dfc7-4d19-a4cc-3944c6a1da70` | 16:31:24Z–16:41:36Z | `test_failure` | The harness expected the run source instead of the protocol-defined IDLE placeholder after STOP. |
| `a90bceab-fde8-4a0c-9e79-1c567be38df5` | 16:45:07Z–16:55:19Z | `accepted_superseded_identity` | Clean pass superseded after physical product fixes changed the phase-wide artifact identity. |
| `22f66838-ecd5-4eed-91ad-d92f70b7ee17` | 16:55:59Z–17:06:12Z | `accepted_superseded_identity` | Clean pass superseded after physical product fixes changed the phase-wide artifact identity. |

### Physical-combined exclusions

| Job ID | UTC interval | Classification | Reason |
| --- | --- | --- | --- |
| `a8da2773-94f6-4e91-ab84-300f78d57971` | 17:12:16Z–17:14:50Z | `test_failure` | Unbounded validation/read pressure exposed packet-pool exhaustion; physical read batches and range validation were optimized. |
| `4892b46e-bb04-4d4c-9c99-d29868fc9b9a` | 17:23:50Z–17:34:02Z | `accepted_superseded` | Clean pass invalidated when the next sequential run failed on the same candidate. |
| `7c21f29c-36d8-4f0a-822e-990717ad01a2` | 17:34:44Z–17:38:11Z | `test_failure` | Packet-pool exhaustion and paired ADC completion mismatches recurred. |
| `9f87d9ab-bdc4-4b61-a70e-a171fb3e2a9c` | 17:51:28Z–17:53:17Z | `test_failure` | The optimized harness isolated an independent ADC completion race; paired completion handling was added. |
| `a286cc08-4b5a-4562-853a-2dc383eda6ad` | 18:09:09Z–18:19:21Z | `accepted_superseded` | Clean pass invalidated when the next sequential run faulted on the same candidate. |
| `a67bd98a-197a-4076-b98c-5b5338c12377` | 18:20:06Z–18:23:56Z | `test_failure` | Paired DMA completion ordering diverged; completion reconciliation was strengthened. |
| `81775ca9-e771-4977-bbd4-d602938f08ce` | 18:32:07Z–18:34:00Z | `test_failure` | ADC channel arbitration skew ended the active state; fixed channel ordering was enforced. |
| `fd7cded1-1257-40c4-bd54-37ba411516fd` | 18:41:27Z–18:47:24Z | `test_failure` | Independent completion IRQ interleaving ended the active state; paired dispatch was serialized. |
| `b2b7bb11-1716-47b0-81f4-6618c1734d45` | 18:56:13Z–18:57:21Z | `test_failure` | Fair-scheduler skew reached two after DMA service starvation; paired ADC DMA was prioritized above GPIO. |
| `30c12dd2-c71c-4813-aa5f-49a269d47d00` | 19:23:23Z–19:33:36Z | `accepted_superseded` | Clean pass invalidated when the next sequential run faulted on the same candidate. |
| `c3417fa1-5854-4cea-b824-07f702d3d3c3` | 19:34:37Z–19:43:30Z | `test_failure` | A delayed completion raced a live-TCD rewrite; generation-indexed descriptors were prelinked. |
| `2f298f18-111e-4e7d-b856-c6fcd37b9815` | 20:11:50Z–20:20:53Z | `test_failure` | A newer ADC0 completion latch was cleared after attribution; both latches are now acknowledged before inference. |
| `1bcc662b-0e5a-478e-a01e-50359ece23db` | 20:28:39Z–20:36:01Z | `test_failure` | Three coalesced paired generations exceeded the four-entry inference window; look-ahead and descriptor depth were extended. |

### Control-stress exclusions

| Job ID | UTC interval | Classification | Reason |
| --- | --- | --- | --- |
| `f8b70430-7228-4e3e-a041-4ae871f49921` | 22:00:57Z–22:01:10Z | `test_failure` (harness) | A pre-timed live-CDC assertion rejected a retained partial parser frame after 2.713 seconds. |
| `c72d1e01-8c83-4fa8-aefd-7597a7898232` | 22:09:48Z–22:10:02Z | `test_failure` (harness) | Live reconnect began mid-wire-frame after 2.923 seconds, preventing exact fragment attribution; loss testing moved to a continuous-session read stall and CDC reopens moved to IDLE. |

## Retry and restart policy

- A proven upload/service/worker/container incident may be excluded as
  infrastructure evidence and retried once with the same immutable artifact.
- A product or test failure is never relabeled as infrastructure. It is
  excluded, diagnosed, repaired, rebuilt under a new artifact identity when
  source changed, and the required consecutive series restarts from run one.
- A clean run followed by a same-candidate failure is explicitly superseded;
  it cannot be combined with a later restart to manufacture a consecutive
  series. A clean run on an older identity is likewise non-counting.
- A local client environment failure before `/start` creates no job and is not
  a retry. The project virtual environment lacked `requests` before one
  physical and one replacement-synthetic submission; system Python was used,
  and both no-job events remain recorded in their campaign indexes.

The actual release lineage contains zero infrastructure incidents and zero
infrastructure retries. Every submitted job ID appears either in the accepted
set or the exclusion tables above.

## Fixture and claim limitations

The physical fixture declared no external analog stimulus and no external
digital transition stimulus. The campaign fully graded the configured trigger,
ADC conversion, paired completion, eDMA ownership, cache handling, GPIO DMA,
packing, framing, Adler-32, USB transport, STATUS/control, STOP, and counter
paths that unstimulated inputs can exercise. It does not establish:

- ADC DC accuracy, offset, gain, noise, ENOB, linearity, or distortion;
- analog bandwidth, source-impedance tolerance, anti-alias performance, or a
  customer-ready front end;
- true aperture time or externally measured cross-channel analog phase;
- GPIO voltage thresholds, externally stimulated pin mapping, or transition
  timing; or
- sustained behavior on a Windows host/controller.

Raw unstimulated values are transport/layout observations, not calibration or
signal-quality evidence. Electrical limits and safe connection requirements
remain in [[Hardware-Safety]]. The autonomous rig acceptance does not depend on
the later Windows handoff, and this report makes no Windows compatibility
claim.

## Evidence retention and hashes

| Evidence | Location | SHA-256 where applicable |
| --- | --- | --- |
| Final candidate stage | `.maestro/playbooks/Working/phase-11-soak-candidate-00018/frozen` | HEX `0716cffb11c551bf77dd8a9bca062c6155bb2e40036ad8d82eaf1be4588d743a` |
| Final synthetic campaign | `.maestro/playbooks/Working/phase-11-synthetic-soaks-00005` | campaign index `19d17a78cc4141552c49f5bcf41f70f186bd69c19bb9b095cf39094cbbe321dc` |
| Final physical campaign | `.maestro/playbooks/Working/phase-11-physical-soaks-00011` | campaign index `0f1a95948593f036d157bc1713b154f4c561a245c37cc7d0b2a96a3cf0a0ec3a` |
| Final control campaign | `.maestro/playbooks/Working/phase-11-control-soak-00001` | campaign index `28c7f05f5bcf1bfd18799ded789e2486cebe4836020505817945969d32235222` |
| Initial cross-run failure | `.maestro/playbooks/Working/phase-11-cross-run-00001` | older-identity mismatch retained |
| Final cross-run PASS | `.maestro/playbooks/Working/phase-11-cross-run-00002` | aggregate `3a9d0064b143e49073776a1270c0b6dab2b1a3ad960533d635db2d7f08321696` |
| Final release campaign index | `.maestro/playbooks/Working/phase-11-cross-run-00002/campaign-index.json` | `d5a7937ec3eb591ae5845ab50c20579991dcda4c3a0925b3dc19bae7bef4354b` |
| Post-aggregation freeze output | `.maestro/playbooks/Working/phase-11-cross-run-00002/post-aggregation-freeze.json` | `2926bb5e115b12869343e18c1eb2f02c7f7f037dab73d2945b` |
| Post-campaign local gate | `.maestro/playbooks/Working/phase-11-final-gate-00001` | distribution hashes recorded above |

The ignored working directories retain compact JSON, bounded diagnostic
samples, logs, exact programs, health responses, and firmware artifacts. They
do not retain the API credential or multi-gigabyte payload captures.
