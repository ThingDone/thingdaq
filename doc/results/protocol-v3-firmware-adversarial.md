---
type: report
title: Public v3 portable contract and adversarial firmware regressions
created: 2026-10-19
tags:
  - protocol-v3
  - firmware
  - portable-validation
  - regression-tests
related:
  - '[[protocol-v3]]'
  - '[[protocol-v3-firmware-transactions]]'
  - '[[protocol-v3-firmware-codecs]]'
  - '[[protocol-v3-firmware-layouts]]'
---

# Portable contract and adversarial regressions

Completes the sixth Phase 03 task. Production firmware is unchanged. These
are portable behavioral checks; they do not qualify physical capture, clock
switching, sustained USB throughput, or hardware loss rates. No hardware was
accessed and no task images were supplied or analyzed.

## Independent expectations and reused infrastructure

`firmware/tests/v3_portable_regressions_test.cpp` reuses the existing pressure
harness's CDC fake, exact-prefix write scheduler and constrained packet-pool
seam. It links the actual packet, deferred codec, transport and runtime sources.
Expected data bytes use literal public offsets, literal ADC edge vectors and
a simple independent Adler-32 calculation, rather than firmware serializers,
codecs, decoders or generated golden fixtures. Existing endian stores only
write individual integer fields. The Python driver compiles under the existing
strict warning flags without private codec defines.

`v3_control_contract_test.cpp` extends the existing fake hardware application
and real control state. It now tests mismatched settings readback as well as
failed application and mismatched clock readback. Literal rejected clock/rate
and reserved/enum cases assert no adapter call, setting change, run change,
generation reset or pending event. Replaying failed or successful mutations
cannot apply twice. Failed rollback prohibits START until recovery.

Eight alternating v3/v2 sessions at each compiled clock exercise both GPIO
widths, idle discovery in both wire versions, busy START conditions, CONFIGURE
while running, duplicate START/STOP and idempotent STOP. Run IDs and statistics
generations advance exactly once per accepted START; discovery preserves mode.
Existing transaction tests continue to cover pending STOP events and queued
old-format frames preventing configuration.

## Data, ownership and scheduling coverage

| Surface | Assertions |
| --- | --- |
| Complete wire bytes | RAW, RLE and PACK12, GPIO8/16, ADC values 0/4095/0x123/0xABC/0x800/0x7FF; checksum covers header, prefix and encoded bytes |
| Adaptive selection | Profitable runs compress; ties and alternating values stay RAW at both widths |
| Short writes | Every prefix offset of the small frame matrix, including zero and checksum splits; control replies cannot interleave with a started data frame |
| Maximum counts | 1009 ADC pairs, 4036 GPIO8 samples, 2018 GPIO16 samples; next larger count rejected; exact emitted bytes within 4096-byte packet storage |
| Malformed input | All truncated shape views, inconsistent header/prefix fields, invalid flags/timestamps/counts, tied/oversized RLE envelopes, incorrect producer lengths/checksum policy, out-of-range ADC values at both ends/channels |
| Pressure | Four-page pool, mixed compressed/RAW GPIO arrivals, eviction, pinned USB bytes, chronological sequence/timestamp gaps and exact produced/transmitted/dropped totals |
| STOP | Cancels incomplete producer ownership once; drains complete deferred tails; forbids restart while old bytes remain |
| Invalid handles | Every buffer index from the pool limit through 255, retired leases, repeated completion/cancel attempts |
| Deadlines | Exact 80,000-tick cutoff across u32 wrap, expiry with zero budget, and completion that finishes at the deadline for both codecs |
| Resources | Full-pool RLE resource drop versus successful in-place PACK12; neither consumes an incomplete owner |
| Cooperative work | Zero-budget service completes nothing; even a large work budget completes at most one frame; successive calls service both streams |

The transport shape guard intentionally does not recheck checksum bytes or
parse RLE records on each short write. Payload correctness is checked against
the independent emitted-byte oracle. Existing public Python malformed-codec
checks and portable RLE primitive tests remain complementary coverage.
Public v3 advertises Adler-32 only; existing tests reject other v3 selections
and retain the legacy supported-checksum matrix. The qualified run layout
still uses 1008 ADC pairs and 4032/2016 GPIO samples; the larger counts above
exercise the packet envelope boundary, not advertised acquisition defaults.

## Validation

- Complete firmware/Python regression: **1773 passed, 5 expected skips,
  16,778 subtests**, in 238.77 seconds. Skips retain the three equal-rate
  override exclusions and two unadvertised 450 MHz compression cases.
- Strict C++ compilation retains `-Wall -Wextra -Werror -Wconversion
  -Wsign-conversion -pedantic -fno-exceptions -fno-rtti`.
- All five new scenarios pass GCC address and bounds sanitizers, including every
  out-of-range pool index and the four-page pressure cases.
- Generator: all 142 outputs current. Ruff formatting/checks: 196 files pass.
  Mypy: 33 source files pass. Whitespace checks pass.

The optional full `-fsanitize=undefined` build could not compile existing
constexpr layout assertions with this GCC. No assertion was disabled; the
address/bounds sanitizer build and required ordinary strict builds pass.

Logs and temporary binaries are ignored under `.maestro/playbooks/Working/portable-*`.
