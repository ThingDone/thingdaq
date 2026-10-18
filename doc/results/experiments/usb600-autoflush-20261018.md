---
type: result
title: 600 MHz USB Autoflush Race Diagnosis and Fix
created: 2026-10-18
tags: [firmware, usb, reliability]
related:
  - '[[Clock600-Endurance-20261017]]'
  - '[[Parser600-Investigation-20261017]]'
---

# 600 MHz USB autoflush race diagnosis and fix

The aborted endurance capture exposed a **firmware USB transmit race** in the
pinned Teensy 1.62.0 core as compiled by Arm GNU 15.2.1 at `-O2`. It can report
a successful write while losing new bytes and transmitting stale ring-buffer
contents. The host parser correctly rejected the corrupted stream. This was
real corruption on the host receive path, not an ADC DMA overrun or an
established temperature limit.

## Captured evidence

Job `91ba765b-d70a-4523-b8dd-258f1e6888d3` failed about 70 seconds into the first
requested 600-second capture. It recorded two checksum rejections, 2,120
discarded bytes, and an ADC continuity failure (expected sequence 138621,
received 138622). Peak sampled temperature was 48.948 °C. The failure STATUS
snapshot reported zero ADC DMA errors, raw-ring overruns, USB I/O errors, and
partial USB writes. Cleanup STOP returned IDLE.

The two saved rejection windows overlap by 24 bytes. Their union reconstructs
4,120 observed bytes without inventing missing data:

| Offset | Length | Contents |
| ---: | ---: | --- |
| 0 | 2,048 | Header and initial payload of ADC frame 138621 |
| 2,048 | 72 | Stale fragment beginning with ADC frame 138619's header |
| 2,120 | 2,000 | Beginning of ADC frame 138622 |

ADC frames are 2,072 bytes here. The expected final 24 bytes (five ADC pairs
and the checksum) of frame 138621 were replaced by 72 stale bytes. The host
therefore rejected a whole 506-pair frame. This is a net insertion of 48 bytes,
not merely a damaged checksum word. Removing 48 bytes does not recover the
lost tail or a valid frame.

The first checksum candidate ends in `0x00000001`, the stale header's run ID.
Independent Adler-32 calculation agrees with both parser rejection reasons.
The captured union is retained as
`firmware/tests/fixtures/usb-autoflush-corruption.bin`. Regression coverage
replays every possible two-chunk split, preserving the two rejections, exactly
2,120 discarded bytes, and the incomplete 2,000-byte following-frame prefix.
No synthetic completion is substituted for the missing wire bytes.

## Root cause and deterministic reproduction

The archived ELF's HEX matches the failed image byte for byte. In its
`usb_serial_write.part.0`, the relevant instructions are:

| Address | Operation |
| --- | --- |
| `0x6d36` | Load `tx_head` into a register |
| `0x6d38` | Load `tx_available` into a register |
| `0x6d3e` | Store 1 to volatile `tx_noautoflush` |

The source places the guard assignment first, but a volatile flag does not
itself prevent this reordering of ordinary shared-state loads. The timer
callback can interrupt between the loads and the guard store, transmit the
partially filled buffer, advance `tx_head`, and clear `tx_available`.
The interrupted writer then uses stale register values. On the partial-write
branch it copies into the old buffer, yet updates the available count for the
new head. A later autoflush sends stale bytes from that new head.

`firmware/tools/replay_usb_autoflush.py` executes the archived Thumb machine
code in Unicorn and injects the real compiled flush callback at that window.
It models `memcpy`, completed USB transfers, and NVIC enable/disable registers;
it is not a complete USB controller/cache simulation. With 48 bytes already
in the current buffer and a 24-byte write:

| Case | Write return | Emitted transfers | Result |
| --- | ---: | --- | --- |
| Original, no interrupt | 24 | 72 bytes | Original 48 + new 24, correct |
| Original, timer in vulnerable window | 24 | 48 then 72 bytes | Original 48 + stale 72; new 24 lost |
| Fixed adapter, same timer request | 24 | 72 bytes | Interrupt deferred; original 48 + new 24, correct |

This reproduces the precise lost-write/stale-fragment lengths seen in the
capture, including a successful return and no backend error. The actual
historical interrupt PC was not recorded; attribution rests on the captured
signature, exact-binary disassembly, and deterministic execution of that race.
The older October 16 parser incident remains unclassified because its rejected
bytes were not retained; it is not retroactively regraded.

## Fix and validation

`TeensyCdcByteStream` masks only `IRQ_USB1` around core transmit capacity checks
and writes, with DSB/ISB before entering the core. It restores the prior IRQ
enable state and leaves pending interrupts intact. DMA and global interrupts
remain enabled. Each call is bounded to the existing 1,024-byte write limit;
capacity is rechecked under the mask before calling the core, avoiding its
cooperative timeout wait. The externally installed core is unchanged.

If capacity changed since the earlier query, the adapter returns the explicit
`kWriteWouldBlock` result without calling `usb_serial_write`. `CdcTransport`
counts a capacity deferral and retains the frame/offset for retry. Actual core
zero-byte returns and other backend errors retain their existing failure
accounting; parser and capture acceptance rules are unchanged.

The fix is committed as `9e7fb90`. Both the default 450 MHz build and the
600 MHz research build pass the unchanged resource gates. The complete firmware
suite passed 249 tests and 836 subtests, with three existing evidence-dependent
skips. The fixed 600 MHz image is `thingdaq-75ac69ba3e2bb588`.

Target-adapter register tests check USB masking, preserved DMA enable state,
pending IRQ retention, prior-disabled IRQ restoration, bounds, capacity
changes, and backend return values. A transport regression exercises deferral
at the 24-byte ADC tail and verifies exact output on retry. The first hardware
candidate exposed that an unattempted capacity deferral was being reported as
a timeout; that failed smoke is retained separately and was not regraded.

The corrected 60-second hardware smoke and 600-second combined-input soak each
passed all 131 checks with zero parser errors or discarded bytes. They received
368,979,716 and 3,674,701,180 bytes respectively. The soak completed
600.010728 seconds with both ADCs and all sixteen GPIO inputs at 1 MS/s.
Its final and maximum sampled temperature were both 65.527 °C.
Two additional ten-second captures in one job passed all 262 checks without
reflashing between them. START replies carried consecutive run IDs 1 and 2;
both STOP/drain/final-IDLE checks passed. Across these four captures, all 524
checks passed with zero parser errors or discarded bytes.

| Job | Duration | Result |
| --- | --- | --- |
| `cc6d6423-c123-4296-a0ad-0e44d9dce8ba` | First candidate, aborted | FAIL: unattempted capacity deferrals counted as timeouts; preserved |
| `8b4240b2-6721-4b5f-87a5-de72e8b950ac` | 60 s | PASS, 131 checks |
| `89cadb75-5904-460a-b8ae-a730a8864abf` | 600 s | PASS, 131 checks |

The [machine-readable evidence](usb600-autoflush-20261018.json) includes the
two-cycle job, all full metrics and temperature samples, artifact hashes,
original rejection samples, machine-code replay, and healthy idle postflight.
The separate eighteen-run endurance campaign is restarted only after these
fix validations; it does not replace or regrade the failed original campaign.
Its live results are recorded in the
[fixed-image endurance report](clock600-fixed-endurance-20261018.md).

## Reproduction and evidence

The replay requires optional `unicorn==2.1.4` and `pyelftools==0.33` in the local
Python environment. It asserts the pinned vulnerable instruction sequence and
refuses a different code layout rather than injecting at an unverified address.

```bash
.venv/bin/python firmware/tools/replay_usb_autoflush.py \
  --original-elf doc/results/raw/usb600-investigation-20261018/original.elf \
  --fixed-elf doc/results/raw/usb600-investigation-20261018/fixed.elf
```

Raw disassembly, replay output, build/test logs, immutable hardware job
artifacts, and service replies are retained under
`doc/results/raw/usb600-investigation-20261018/`.
