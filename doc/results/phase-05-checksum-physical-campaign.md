---
type: report
title: Phase 05 Checksum Physical Campaign
created: 2026-08-28
tags:
  - teensy-daq
  - checksum
  - benchmark
  - hardware-validation
  - phase-05
related:
  - '[[Checksum-Candidates]]'
  - '[[Phase-05-Checksum-Correctness]]'
  - '[[Phase-05-Checksum-Local-Gate]]'
  - '[[Phase-04-Synthetic-Streaming]]'
  - '[[Firmware-Resource-Map]]'
  - '[[ADR-002-Checksum-Selection]]'
---

# Phase 05 checksum physical campaign

## Outcome

The candidate-isolated physical checksum campaign passed on 2026-08-28 for
Adler-32, CRC-32C, and CRC-32/ISO-HDLC. The three accepted jobs ran strictly
sequentially on Teensy 4.0 serial 20512460 and flashed the same clean artifact,
`tdaq-b2d06f37e6cef9a7`. Each job first ran the complete on-device candidate
microbenchmark and then sustained a 60-second full-rate ADC/GPIO synthetic
stream using that candidate.

All three jobs validated the 15 independent fixed vectors, completed all 14
target benchmark profiles with four batches of 256 operations, held the
required stream rate, checked every received frame and trailer, reconciled
final firmware counters, observed no loss or corruption, ended with empty
bounded host queues, and met the [[Phase-04-Synthetic-Streaming]] command
latency limits.

| Campaign gate | Result |
| --- | --- |
| Service preflight before each accepted job | PASS: HTTP 200, healthy worker, Docker and hub reachable, coordinator `normal`, queue depth 0 |
| Sequential execution | PASS: no accepted or diagnostic submission overlapped another |
| Artifact and board identity | PASS: one clean build and Teensy serial 20512460 in all three accepted jobs |
| Independent vectors | PASS: 15/15 before serial campaign work in every job |
| Target microbenchmarks | PASS: 14/14 profiles per candidate, four batches × 256 operations, stable digest and tight batch spans |
| Full-rate capture | PASS: one 60-second candidate-isolated stream per algorithm |
| Stream correctness | PASS: every data/control trailer and every synthetic field validated |
| Loss and corruption | PASS: all seven reported firmware/host error fields were zero in every accepted job |
| Memory and queues | PASS: fixed 200-frame firmware pool, bounded 512 KiB host reader, bounded parser, all host queues empty at exit |
| Phase 04 latency | PASS: worst STATUS p99 8.188 ms against 100 ms; worst maximum 42.357 ms against 250 ms; every other command below 500 ms |
| Production checksum selection | NOT PERFORMED: reserved for the next fixed-policy playbook task |

No images were associated with this task; zero images were analyzed.

## Service preflight and strict sequencing

The campaign used the established remote firmware service at
`http://192.168.150.14:5000`. The existing owner credential was read from its
local mode-restricted file into the client environment. It was never printed,
placed on the command line, logged, or copied into the repository. A fresh
`/health` check immediately before every accepted submission required a live
worker, reachable Docker and hub, coordinator mode `normal`, and queue depth
zero.

Client timestamps include packaging, queue submission, target programming,
benchmarking, capture, terminal result retrieval, and exit. The next job was
not submitted until the prior client had exited and the service again reported
an empty queue.

| Order | Candidate | Job ID | Client UTC interval | Stream elapsed | Outcome |
| ---: | --- | --- | --- | ---: | --- |
| 1 | CRC-32C | `8b25b33c-175a-4add-a530-2bc7b6615d40` | `15:41:12Z`–`15:42:27Z` | 60.000335 s | PASS |
| 2 | Adler-32 | `d8fb7503-afe6-493b-9b12-c242ba77fac2` | `15:42:55Z`–`15:44:08Z` | 60.000249 s | PASS |
| 3 | CRC-32/ISO-HDLC | `f35e7b00-7a66-45c6-838a-7de6f5b19de7` | `15:44:26Z`–`15:45:39Z` | 60.000868 s | PASS |

## Accepted firmware artifact

The exact FQBN was
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`, using Teensy core 1.62.0
and Arm GNU 15.2.1 at 600 MHz. Target CRC functions alone carry an `-O3`
attribute; the rest of the image retains the pinned standard `-O2` contract.

| Property | Value |
| --- | --- |
| Build ID | `tdaq-b2d06f37e6cef9a7` |
| Firmware-input commit | `06930e2e5815d80365f43a5ac5e276c8af1bae70` |
| Firmware inputs | Clean; no generated drift |
| HEX SHA-256 | `d6ed1b5a69082b023e90951541a3d3b876f67118e8b2d2fc751f46724813e89e` |
| Build-manifest SHA-256 | `45f12ec04dbc0896077783982e4a318434736b6482e3dd4680a442957cf7384a` |
| Manifest schema | 6 |
| Flash code / initialized data / headers | 35,172 / 21,448 / 8,912 bytes |
| RAM1 variables / code / padding / free | 455,488 / 32,712 / 56 / 36,032 bytes |
| RAM2 variables / free | 401,536 / 122,752 bytes |
| DTCM packet bank | 106 frames / 434,176 bytes at `0x200022c0` |
| OCRAM packet reserve | 94 frames / 385,024 bytes at `0x20200000` |
| Total packet pool | 200 frames / 819,200 bytes; fixed and allocation-free |
| Application/core retention | 101.200 ms plus 1.012 ms at nominal framed rate |
| Checksum benchmark buffers | 4,096-byte DTCM plus 4,096-byte OCRAM; 8,192 bytes total |
| CRC lookup tables | 8,192 Flash bytes per polynomial; zero table RAM |

The manifest verifies both split packet-bank placements, both aligned benchmark
buffers, all checksum bodies, both memory-mapped Flash tables, and the shared
dispatch. This closes the earlier ambiguity where protocol v1 exposed fixed
capacity but not linked storage placement.

## Repeatable target microbenchmarks

Each accepted program independently checked empty, `123456789`, deterministic
64-byte and 512-byte buffers, and the exact 4,092-byte frame coverage for all
three algorithms before touching the serial device. On target, the isolated
candidate then ran 14 meaningful combinations: empty DTCM/OCRAM; nonempty
DTCM and hot OCRAM; and cold-invalidated OCRAM for every nonempty vector. Each
profile used four batches of 256 operations with DWT overhead subtraction,
interrupt exclusion, compiler barriers, a published digest, and exact
raw/minimum/maximum cycle counts in the retained JSON.

The representative result is the complete 4,092-byte covered frame. MB/s is
decimal and projected CPU is against the declared 8,100,000 framed bytes/s on
one 600 MHz core.

| Candidate | Hot DTCM cycles/B | Hot MB/s | Hot CPU | Hot batch cycles min–max | Cold OCRAM cycles/B | Cold MB/s | Cold CPU | Cold batch cycles min–max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Adler-32 | 4.024445 | 149.088531 | 5.432999% | 4,215,808–4,215,850 | 4.938919 | 121.483871 | 6.667526% | 4,871,288–4,871,349 |
| CRC-32C | 2.647598 | 226.619705 | 3.574249% | 2,773,504–2,773,510 | 3.560394 | 168.520416 | 4.806519% | 3,427,854–3,427,904 |
| CRC-32/ISO-HDLC | 2.648102 | 226.576538 | 3.574936% | 2,774,016–2,774,060 | 3.561356 | 168.475037 | 4.807816% | 3,428,848–3,428,923 |

| Candidate | Representative digest | Body code | Table Flash | Table RAM | Working RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| Adler-32 | 3,039,746,001 | 120 bytes | 0 | 0 | 8,192 bytes |
| CRC-32C | 4,268,808,542 | 308 bytes | 8,192 bytes | 0 | 8,192 bytes |
| CRC-32/ISO-HDLC | 2,120,471,814 | 308 bytes | 8,192 bytes | 0 | 8,192 bytes |

The minimum/maximum batch spans are only 6–75 cycles across roughly 2.8–4.9
million cycles per batch. All batches and regions published the expected
deterministic digest. Those internal repeats, rather than host timing, establish
the repeatability of each accepted target measurement.

## Sixty-second stream results

ADC frames contain 4,048 payload bytes as 1,012 four-byte pairs; GPIO frames
contain 4,048 one-byte samples. The two sources each target 4,000,000 payload
bytes/s. Including the fixed 48-byte frame overhead, the combined target is
8,094,861.660 framed bytes/s.

| Candidate | ADC / GPIO frames | Payload B/s | Framed B/s | Trailers checked incl. control | Max receive gap | STATUS p99 / max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Adler-32 | 59,292 / 59,292 | 8,000,433.949 | 8,095,300.755 | 118,830 | 53.557 ms | 2.765 / 34.342 ms |
| CRC-32C | 59,291 / 59,291 | 8,000,287.546 | 8,095,152.616 | 118,828 | 55.564 ms | 8.188 / 8.382 ms |
| CRC-32/ISO-HDLC | 59,292 / 59,292 | 8,000,351.491 | 8,095,217.319 | 118,830 | 78.394 ms | 2.960 / 42.357 ms |

Every ADC/GPIO frame matched the selected checksum ID, fixed shape, run ID,
sequence, timestamp cadence, flags, item count, and complete deterministic
payload formula. Final firmware emitted counts exactly equaled host-validated
counts. The following seven fields were zero for every candidate:

- firmware ADC items dropped;
- firmware GPIO items dropped;
- firmware parser errors;
- firmware transport errors;
- host parser errors;
- host stale responses; and
- host stream bytes discarded.

CRC-32C used a bounded precomputed oracle so the service host could validate
the exact trailer without becoming part of the device performance result. It
prepared 118,994 four-byte entries in 2.053414 seconds, consuming 475,976 bytes,
and validated all 118,582 CRC-32C data trailers through the oracle plus the
independent semantic payload checker. No data frame fell back to a full
byte-at-a-time CRC. Adler-32 and CRC-32/ISO-HDLC used their exact standard
library matches after the same semantic validation.

## Queue, memory, and latency evidence

The fixed firmware packet capacity was 200 frames in every accepted run and no
run observed an exhaustion counter, gap/overrun flag, sequence discontinuity,
or final drop. Protocol v1 still does not expose internal firmware queue depth,
so this report does not invent an internal high-water value. The linked
capacity, continuous wire checks, and exact final counters are the available
external exhaustion evidence.

The host reader was bounded to 32 × 16,384-byte chunks, or 524,288 bytes. Every
run reached only 81,920 bytes/five chunks, returned to zero bytes/zero chunks,
and left the frame parser at zero bytes. Parser high water was 20,479 bytes.
The maximum successful read-call durations were 53.509 ms for Adler-32,
58.689 ms for CRC-32C, and 78.341 ms for CRC-32/ISO-HDLC; all were absorbed by
the fixed target retention without loss.

Each stream sampled STATUS 240 times. The Phase 04 bounds are 100 ms p99 and
250 ms maximum for STATUS and 500 ms for individual control commands. The
worst accepted values were 8.188 ms p99, 42.357 ms maximum, 38.832 ms for a
long on-device benchmark response, and 20.731 ms among CONFIGURE, INFO, START,
STOP, and final STATUS. All passed with substantial margin.

## Repairs and diagnostic exclusions

The initial bytewise CRC-32C target result missed both throughput and CPU
bounds. Slicing by four repaired target speed but exposed host validator
backpressure. Later isolated jobs exposed bounded host scheduling pauses and
then genuine target drops when firmware production could outrun cooperative
USB service during those pauses. The repair sequence therefore addressed both
sides independently:

- upgraded target CRCs to alignment-safe slicing by eight with `-O3` bodies;
- replaced full-frame CRC-32C host work with an exact bounded oracle;
- drained serial data through a bounded reader while validation continued;
- limited each producer visit to one ADC/GPIO pair while retaining same-visit
  promotion and USB service; and
- added the verified 94-frame OCRAM reserve behind the 106-frame DTCM bank.

Every failed job below remains excluded. A diagnostic PASS on the superseded
96-frame Adler artifact was also rerun on the final artifact before acceptance.
The terminal observation is a locator, not a replacement for each log's raw
`EVENT`, `CANDIDATE`, and `SUMMARY` numbers.

| Job ID | Raw log | Terminal observation |
| --- | --- | --- |
| `05694247-0dc3-4a8e-9f19-e1efc24aba72` | `campaign-60s.log` | Bytewise CRC-32C missed speed/CPU gates; ADC gap at sequence 110 |
| `073dfc2d-0857-42fc-b36f-708c0ea91679` | `campaign-60s-slicing-firmware-bytewise-host.log` | Slicing-by-four benchmark passed; ADC gap at sequence 131 |
| `788db141-a558-48a7-989b-29aa61ca064d` | `campaign-60s-slicing-host.log` | ADC gap at sequence 4,099 |
| `716961fb-89e8-41f5-bf2f-0e7f52d0256c` | `candidate-crc32c-60s-submit1.log` | ADC gap at sequence 129 |
| `1dfc5c68-8216-4079-b4bc-d1a7191ff592` | `candidate-crc32c-60s-submit2.log` | Running STATUS reported a loss/error counter |
| `86d0d98b-d24f-4fa7-88c3-b1aa095dd4a0` | `candidate-crc32c-60s-submit3.log` | GPIO gap at sequence 3,602 |
| `2d34b9cb-83fc-4c1e-a111-4b2c05ecddbe` | `candidate-adler32-60s-submit2.log` | Programming ended without device campaign output; excluded |
| `adeb7da8-0091-4937-9091-7830e2dbfbd1` | `candidate-adler32-60s-submit3.log` | Diagnostic PASS on superseded 96-frame artifact; rerun on final artifact |
| `d5513e97-f23b-4a14-abbe-74f11410de33` | `accepted-crc32c-60s.log` | ADC gap at sequence 6,603 |
| `c61d8b0e-78f3-4881-b975-b0b4ecb82481` | `bounded-crc32c-60s-submit1.log` | ADC gap at sequence 28,632 |
| `3f0450fb-1827-4ef6-a1be-bf41c72af305` | `bounded-crc32c-60s-submit2.log` | GPIO gap at sequence 3,624 |
| `f47003b0-1011-41d4-b6f2-346b3076f3a0` | `bounded-crc32c-60s-submit3-diagnostic.log` | ADC gap at sequence 3,572 |
| `337fc628-a626-4990-b40b-a18509d602ad` | `tx4096-crc32c-60s.log` | ADC gap at sequence 3,672 |
| `b9654aec-cd7b-41bc-99b9-76749786a42a` | `o3-adler32-60s.log` | GPIO gap at sequence 48,801 |
| `9ea3915e-1de4-4aa1-b377-d2e154bc45ff` | `o3-crc32c-60s.log` | GPIO gap at sequence 3,655 |
| `fc0c7336-518a-48ef-96b7-765872a5b623` | `ingest-crc32c-60s.log` | STATUS reported 2,024 ADC and 12,144 GPIO items dropped |
| `04a89206-c921-45c2-ac8f-a9938c33b6bd` | `final-a4eb-crc32c-60s.log` | STATUS reported 17,204 ADC and 72,864 GPIO items dropped |
| `2c784a64-2725-4a06-ad7b-4bd85d0494f6` | `final-3633-crc32c-60s.log` | STATUS reported 3,036 ADC and 12,144 GPIO items dropped |
| `58c6b3b7-3ac6-4426-b521-59c6a805d0e3` | `final-0709-crc32c-60s.log` | GPIO gap at sequence 1,565 |
| `c69f231e-0940-4a43-806e-e62fdc1224b3` | `final-crc32c-60s.log` | ADC gap at sequence 3,646 |

## Retained raw evidence

The accepted logs are under the ignored, workspace-local directory
`.maestro/playbooks/Working/phase-05-checksum-rig-00001/`. They contain the
complete numeric benchmark profiles, all latency sample arrays, stream totals,
queue high waters, error fields, service job IDs, and final machine-readable
summaries. They do not contain bulk serial payload captures: each frame was
validated online and discarded.

| Candidate | Job ID | Raw log | Log SHA-256 | Submitted program SHA-256 |
| --- | --- | --- | --- | --- |
| Adler-32 | `d8fb7503-afe6-493b-9b12-c242ba77fac2` | `final-b2d0-adler32-60s.log` | `9be38926a56f8e296cb8bc721d576db8ca4a1db26cfdcd0318a31e981c802d65` | `b3b183dd087e1fc48261fe3c58a9669349a0889ead4c3028f30d42369b54904d` |
| CRC-32C | `8b25b33c-175a-4add-a530-2bc7b6615d40` | `final-b2d0-crc32c-60s.log` | `efa9b31d33f2b9fc36d01acf52f93f559707290cce8eaf81d390b6294cbdf471` | `c942bca6b1464f1466bbf6327a326ecda4821142c9430bd0cef61b6960185375` |
| CRC-32/ISO-HDLC | `f35e7b00-7a66-45c6-838a-7de6f5b19de7` | `final-b2d0-crc32-iso-hdlc-60s.log` | `799bb27d9e4966fc26be8ce72a1e5f947bada95da7e612d6fe21844b3a74877d` | `5210f839f9ddbbcfbc40eaac9f3f16b168adfc88e9ebca671acbf926f523ae81` |

All diagnostic logs named in the exclusion table are retained in the same
directory. Their SHA-256 values can be regenerated with:

```bash
sha256sum .maestro/playbooks/Working/phase-05-checksum-rig-00001/*.log
```

## Local regression gate and limitation

After the final packet-placement repair, all 22 generated protocol outputs were
current; Ruff format and lint passed across 57 Python files; MyPy passed across
57 source files; and the complete suite passed with 199 tests and 10,554
subtests. The clean pinned firmware build produced the accepted manifest and
artifact above.

This campaign supplies one accepted 60-second stream per candidate, with
repeatability inside every four-batch target profile. It does not make the
fixed-policy production choice and is not the later requirement for three
consecutive selected-checksum validation runs. Those are deliberately separate
playbook tasks. The finite corruption evidence remains bounded as documented
in [[Phase-05-Checksum-Correctness]] and makes no security claim.
