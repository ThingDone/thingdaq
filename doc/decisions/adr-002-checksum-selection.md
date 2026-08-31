---
type: analysis
title: 'ADR 002: Checksum Selection'
created: 2026-08-28
tags:
  - thingdaq
  - decision
  - checksum
  - crc32c
  - phase-05
related:
  - '[[Checksum-Candidates]]'
  - '[[Protocol-V1]]'
  - '[[Phase-05-Checksum-Correctness]]'
  - '[[Phase-05-Checksum-Physical-Campaign]]'
  - '[[Phase-05-Checksum-Benchmark]]'
  - '[[Firmware-Resource-Map]]'
---

# ADR 002: Checksum selection

## Status

Accepted. Standard Adler-32 remains the protocol-v1 production data checksum
and the fixed control bootstrap. CRC-32C and CRC-32/ISO-HDLC remain enabled,
advertised, negotiable, and decodable so retained benchmark evidence and
explicit non-default configurations do not become unreadable.

## Context

Protocol v1 reserved stable identifiers before the production checksum was
selected. [[Checksum-Candidates]] defines the three exact wire algorithms and
records why no i.MX RT1062 peripheral is a safe matching implementation. The
independent correctness gate and candidate-isolated target campaign then
measured the same firmware dispatch and packet path for every candidate. This
decision applies the playbook policy to that evidence without using host
benchmark speed as a compatibility criterion.

The checksum covers the complete 44-byte header and payload and excludes the
four-byte trailer. It detects accidental corruption and framing errors; it is
not authentication and makes no security claim.

## Fixed selection policy

A candidate qualifies only when all of these conditions hold:

1. independently checked C++ and Python results agree;
2. the implementation is safe with all reserved hardware resources;
3. representative frame data is processed at least ten times faster than the
   required 8.1 MB/s framed rate, or at least 81 MB/s;
4. projected checksum cost is no more than 10% of one 600 MHz core at the
   target rate;
5. a candidate-isolated 60-second stream completes with zero loss or
   corruption; and
6. established command-latency and queue measures do not regress by more than
   10% from the Adler-32 campaign baseline.

Among qualifiers, the policy prefers the strongest documented accidental-error
detection in this order: CRC-32C, CRC-32/ISO-HDLC, then Adler-32. If no CRC
qualifies, it retains standard Adler-32.

The command gate is conjunctive. It compares the established Phase 04 STATUS
p99 and maximum separately, plus the worst one-shot lifecycle-command response.
An improvement in one statistic cannot conceal a greater-than-10% regression
in another. Queue comparison uses every observable high-water/capacity measure:
the target exhaustion indicator, host reader bytes, parser bytes, and deferred
START-boundary frames. Protocol v1 does not expose an internal firmware queue
high water, so this decision does not invent one.

## Complete qualification results

The conservative throughput and CPU columns use the slower cold-invalidated
OCRAM representative-frame result. All jobs used the pre-rename artifact
`tdaq-b2d06f37e6cef9a7` on Teensy serial 20512460.

| Candidate | Job ID | Cross-language / hardware safe | Cold MB/s ≥ 81 | Cold CPU ≤ 10% | 60 s zero-loss stream | Result before latency gate |
| --- | --- | --- | ---: | ---: | --- | --- |
| Adler-32 | `d8fb7503-afe6-493b-9b12-c242ba77fac2` | PASS / PASS | 121.483871 | 6.667526% | PASS, 60.000249 s | PASS |
| CRC-32C | `8b25b33c-175a-4add-a530-2bc7b6615d40` | PASS / PASS | 168.520416 | 4.806519% | PASS, 60.000335 s | PASS |
| CRC-32/ISO-HDLC | `f35e7b00-7a66-45c6-838a-7de6f5b19de7` | PASS / PASS | 168.475037 | 4.807816% | PASS, 60.000868 s | PASS |

| Candidate | Hot cycles/B / MB/s / CPU | Framed B/s | STATUS p99 vs baseline | STATUS max vs baseline | Worst one-shot command vs baseline | Reader / parser high water | Final qualification |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Adler-32 | 4.024445 / 149.088531 / 5.432999% | 8,095,300.755 | 2.765 ms / baseline | 34.342 ms / baseline | 20.436 ms / baseline | 81,920 / 20,479 B | **QUALIFIES** |
| CRC-32C | 2.647598 / 226.619705 / 3.574249% | 8,095,152.616 | 8.188 ms / **+196.139%** | 8.382 ms / -75.591% | 20.731 ms / +1.445% | 81,920 / 20,479 B | **REJECT: p99 latency** |
| CRC-32/ISO-HDLC | 2.648102 / 226.576538 / 3.574936% | 8,095,217.319 | 2.960 ms / +7.064% | 42.357 ms / **+23.340%** | 20.634 ms / +0.971% | 81,920 / 20,479 B | **REJECT: max latency** |

Every stream validated 118,828–118,830 trailers including control traffic.
Firmware item drops, firmware parser/transport errors, host parser errors,
stale responses, and discarded stream bytes were zero for all candidates. The
host reader and parser ended empty. Reader and parser high waters were identical
for all three candidates; target queue exhaustion was never observed. Deferred
START-boundary frames were 3, 2, and 3 for Adler-32, CRC-32C, and
CRC-32/ISO-HDLC respectively, so neither CRC had a queue regression.

The complete vector/corruption evidence is in
[[Phase-05-Checksum-Correctness]], and raw microbenchmark batches, stream
counts, latency samples, queue data, artifact hashes, and excluded diagnostics
are inventoried in [[Phase-05-Checksum-Physical-Campaign]].

## Decision

Adler-32 is the only candidate that passes every fixed qualification condition,
so it remains `default_checksum_algorithm` and checksum ID 1 is used for data
frames when no explicit configuration overrides it. CRC-32C has the preferred
error-detection polynomial and the best measured target performance, but the
policy does not permit its 196.139% STATUS-p99 regression. CRC-32/ISO-HDLC also
has stronger accidental-error detection than Adler-32, but its 23.340% STATUS
maximum regression disqualifies it.

INFO in IDLE reports Adler-32 as the selected data checksum while its supported
checksum mask remains `0b1110`. CONFIGURE may still explicitly select IDs 1,
2, or 3; INFO in CONFIGURED/RUNNING, STATUS, and each data-frame header report
that applied selection. Every request and response remains bootstrap Adler-32,
independent of the data selection. [[Protocol-V1]] remains the normative wire
definition.

## Resource impact

The selected Adler-32 body occupies 120 bytes and requires no lookup table. It
uses 4.024445 cycles/byte from hot DTCM and a conservative 4.938919 cycles/byte
from cold OCRAM. Selecting it changes no frame, packet-buffer, RAM, USB,
acquisition, timer, DMA, or cache ownership.

Decode and explicit negotiation support for both CRCs is retained. Therefore
the image still carries each 308-byte CRC body and each 8,192-byte flash-resident
slicing-by-eight table, with zero table RAM. The selection itself does not
reclaim those bytes because doing so would invalidate captured evidence and
the advertised IDs. The accepted artifact retains a fixed 200-frame/819,200-byte
packet pool, 8,192 benchmark working bytes, 36,032 free RAM1 bytes, and 122,752
free RAM2 bytes as detailed in [[Firmware-Resource-Map]].

## Consequences and rejected alternatives

- CRC-32C is rejected as the default only because it fails the fixed relative
  p99 latency gate. Its implementation and wire ID remain supported.
- CRC-32/ISO-HDLC is rejected as the default because it fails the fixed
  relative maximum-latency gate. Its implementation and wire ID remain
  supported.
- Removing either CRC implementation is rejected because the task requires
  decode support for benchmarked identifiers and preserved evidence.
- Reinterpreting the relative gate using only the most favorable aggregate is
  rejected because the policy says a candidate qualifies only if no command
  regression exceeds 10%.
- Hardware assistance remains rejected for the reasons in
  [[Checksum-Candidates]]: available peripheral CRC paths either implement the
  wrong polynomial or own unrelated resources.

Golden fixtures continue to use Adler-32 for both production-default data and
bootstrap control frames. Their source provenance was regenerated after this
decision; their wire bytes remain stable because the selected default is the
same algorithm used before selection.

The subsequent clean selected-image rebuild and three consecutive 60-second
full-rate acceptance runs passed without loss, corruption, queue exhaustion,
or Phase 04 latency violations. Their raw summaries and retained job identities
are recorded in [[Phase-05-Checksum-Benchmark]].
