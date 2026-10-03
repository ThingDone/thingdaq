---
type: result
title: Combined ADC and GPIO Frame Without Checksum
created: 2026-10-02
tags:
  - protocol
  - adc
  - gpio
  - checksum
  - experiment
related:
  - '[[ADR-001-Wire-Protocol]]'
  - '[[Protocol-V2]]'
  - '[[Hardware-Safety]]'
---

# Combined ADC and GPIO frame without checksum

Branch: `experiment/combined-adc-gpio-no-checksum`, based on `302249a`.

**The combined unchecksummed format saves only 16 bytes per 1,012-instant
interval with eight GPIO inputs, or 28 bytes with sixteen inputs.** That changes
the required framed rate by just 0.31–0.46%. It is not worth losing bit-error
detection or adding a special variable-trailer rule.

## Proposed protocol change

`protocol/protocol-v2.json` now contains an experiment-only proposal; it does
not alter the enabled release enums or generated production parser.

- Frame kind 3, `ADC_GPIO_DATA`, contains 1,012 aligned instants.
- Checksum algorithm ID 4, `NONE_DATA`, is legal only on that frame kind.
- Checksum algorithm zero remains permanently invalid.
- `NONE_DATA` has a zero-byte trailer. Existing data and every control frame
  retain their fixed four-byte checksum trailer and normal algorithms.
- Each item is `adc0_u16_le`, `adc1_u16_le`, then `gpio_u8` or `gpio_u16_le`.
  The GPIO snapshot is the instant at the ADC0 pair time; ADC1 retains its
  documented half-period phase within the pair.
- One run-scoped sequence counts complete combined intervals. Header
  `item_count`, time, run, sequence, flags, lengths, and reserved fields retain
  their existing meanings.

The resulting frame is 5,104 bytes for eight GPIO inputs and 6,116 bytes for
sixteen. A future real protocol would also need capability negotiation, a
larger maximum-frame declaration, parser buffering changes, CONFIGURE format
selection, and tail/loss accounting. This prototype deliberately does not
smuggle the new meaning into release v2.

## Prototype and correctness

The firmware codec writes the normal 44-byte little-endian header and
interleaves the exact 12-bit ADC containers with each GPIO snapshot. It rejects
zero run IDs, reserved flag bits, invalid GPIO width/values, non-1,012 counts,
wrong destination sizes, and ADC codes above 4,095. It writes no trailer.

The host decoder independently validates structure and decodes both GPIO
widths. A cross-language test compiles the firmware encoder, produces 5,104-
and 6,116-byte frames, and checks exact ADC/GPIO values in Python. The test also
demonstrates the intended loss semantics:

- changing a payload bit produces a different ADC value and still decodes;
- changing sequence 11 to 13 reports one dropped combined interval.

Thus sequence counters still detect complete missing frames. They cannot
detect bit flips, byte changes that remain structurally plausible, corruption
within a received interval, or malicious modification. This format provides no
authentication, just like the existing checksums.

## Header/trailer savings and required USB rate

Rates use the fixed 1,000,000 ADC-pair/GPIO-instant rate and decimal MB/s.
Separate framing is normalized to the same 1,012-instant interval: one ADC
frame plus one quarter of an 8-bit GPIO frame, or one half of a 16-bit GPIO
frame.

| GPIO width | Separate checksummed bytes/interval | Combined no-checksum bytes/interval | Saved bytes | Separate MB/s | Combined MB/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 inputs | 5,120 | 5,104 | 16 | 5.05929 | 5.04348 |
| 16 inputs | 6,144 | 6,116 | 28 | 6.07115 | 6.04348 |

The payload bytes are identical. Separate per-interval framing overhead is 60
bytes for eight GPIO (48 ADC plus a quarter of 48 GPIO) and 72 bytes for
sixteen GPIO. Combined overhead is one 44-byte header and no trailer, yielding
the exact 16/28-byte savings above: 15.81/27.67 kB/s, or 0.3125/0.4557%.

Against the repository's measured 24.46 MB/s median USB saturation result,
combined headroom is 79.38% for eight GPIO and 75.29% for sixteen, only
0.06/0.11 percentage points above separate framing. More importantly, the
existing physical USB layout experiment measured separate records at 24.47
MB/s and a combined record at 24.29 MB/s; joining records did not improve
saturation throughput. Those measurements used synthetic prebuilt data and are
not a qualification of this new wire format, but they reinforce that header
savings do not translate into higher USB capacity.

## Hardware scope

No acquisition or pin-driving test ran. The codec operates on supplied buffers,
so the hardware-safety input limits remain unchanged. The watchdog remains
disabled, and no attempt was made to investigate or work around the known ADC
DMA fault.

## Recommendation

Reject this format for production. Preserve checksummed separate streams: the
measured/projected bandwidth gain is below half a percent, while every
otherwise-plausible payload bit error becomes silent. If aligned ADC/GPIO
delivery is valuable for API ergonomics, join blocks on the host using their
shared run/timestamp metadata without weakening the wire integrity contract.
