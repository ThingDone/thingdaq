---
type: result
title: SDK Capture with Watchdog Initialization Disabled
created: 2026-09-27
tags:
  - thingdaq
  - watchdog
  - validation
related:
  - '[[Watchdog-SDK-20260927]]'
---

# SDK capture with watchdog initialization disabled

This diagnostic tests whether the combined 16-input SDK capture reproduces
the previously observed ADC acquisition fault when watchdog initialization is
omitted. See the [preceding campaign](watchdog-sdk-20260927.md) for the
50.084-second failure and the subsequent 600-second pass with the watchdog
enabled. This comparison does not change the production watchdog policy.

## Controlled change

The temporary firmware change removes only the call to
`thingdaq::watchdog::begin()` in `firmware/firmware.ino::setup()`. The main loop
still calls `refresh()`, but `g_enabled` remains false, so no refresh register
write occurs. ADC/GPIO acquisition, checksums, interrupt guards, and SDK source
are unchanged. Disassembly confirms setup has no watchdog initialization call
and the guarded refresh call remains. The build passes the pinned toolchain
and memory checks. Removing initialization also changes linked code layout;
this experiment does not isolate register-write cost from other effects.

The variant reports `watchdog_enabled=false` and `watchdog_timeout_ms=0`.
Its reported `reset_cause=0` is an uninitialized software value because
watchdog initialization normally captures that register. It must not be used
as evidence that no reset occurred.

The standard strict SDK collector is used with one acceptance change: runtime
health must report a disabled watchdog with zero timeout. Stack checks, loss
checks, parser checks, and strict exception behavior remain enabled. Both
enabled and disabled health expectations were checked locally to accept only
their matching watchdog state. The exact firmware patch, variant sketch,
controller source, artifact hashes, and captured evidence are retained in the
companion machine-readable record.

## Test conditions

- Teensy 4.0 USB serial `20428100`, 450 MHz, fixed 1 MS/s ADC and GPIO.
- Combined ADC plus 16 GPIO inputs, cold start, 600-second target.
- Same SDK source as the preceding campaign; no rejected-frame hook.
- Rig `192.168.150.14`; individual job container quota verified as
  `cpu.max = 200000 100000` before serial access. This permits two CPU cores
  of processing time but does not reserve cores. The service default remains
  half a core.
- Runtime health, temperature, and STATUS sampled at the capture midpoint;
  preflight and cleanup remain unchanged except for watchdog-state acceptance.
- No external electrical stimulus; streaming correctness is the measured scope.

## Results

The disabled-watchdog capture **passed 600 seconds**, job
`1f3ce683-d83d-43f1-8661-b4d2869d3aef`. It received 600,002,656 ADC pairs and
600,002,656 GPIO samples, decoding 1,482,276 frames from 3,671,235,460 bytes.
There were no observed stream gaps, host queue losses, parser rejections,
checksum errors, discarded bytes, or firmware loss-counter failures. Midpoint
and end-of-capture STATUS reported zero ADC DMA errors and completion
mismatches. All four health samples reported the watchdog disabled and at
least 27,856 bytes free stack.

Process CPU time was 400.625 seconds over 600.164 seconds including cleanup,
about 0.668 CPU cores. Both `nr_throttled` and `throttled_usec` remained
unchanged across the capture (one period / 15,222 us already existed before
acquisition). Die temperature was 39.737 °C initially, 56.930 °C at midpoint,
and 58.772 °C after capture. Thermal starting conditions were not matched to
the earlier failed run or its passing repeat.

| Artifact | Identity |
| --- | --- |
| Diagnostic base commit | `ce11ade267ba7f0c774a72b859c4c96cbdc6b6e4` |
| Diagnostic firmware build ID | `thingdaq-b30b05ff35597872` |
| Diagnostic HEX SHA-256 | `82b809b480c8761ca2267311de29b7ac795db1ff901211260b8bdbbbffbffa41` |
| Original firmware build ID | `thingdaq-b0fafcaf165da96b` |
| Original HEX SHA-256 | `9be428933c8d2cfb962e339c7d1f19272fff51b77c5de333ceab8320682cbbd6` |

The temporary source edit was reverted immediately after building the variant.
A rebuild of production source reproduced the original HEX byte for byte.
The diagnostic manifest explicitly records the modified sketch; it is not a
clean production build or a permanent watchdog removal.

The original firmware was then programmed back onto the rig. Its 60-second
combined16 restoration capture **passed**, job
`fb2f623c-80e6-47cf-b883-8b9a20050685`, receiving 60,002,492 ADC pairs and
60,003,504 GPIO samples with zero observed loss, parser corruption, or ADC DMA
errors. All health observations reported watchdog enabled, timeout 4000 ms,
reset cause `0x1`, and at least 27,856 bytes free stack. CPU throttling deltas
were zero. This is a restoration check, not a matched-duration endurance run.
The rig finished healthy and idle with no running job containers.

The [machine-readable evidence](watchdog-disabled-20260927-evidence.json)
contains both complete SDK evidence records, CPU deltas, source inventories,
firmware manifests' source identities, raw-result hashes, and postflight state.
Raw service replies and submitted programs remain under
`doc/results/raw/watchdog-sdk-20260927/` in
`sdk-watchdog-disabled-two-600/` and `sdk-watchdog-restored-two-60/`.
The SDK file inventory matches both current jobs and the earlier 600-second
enabled repeat. The two current validators differ only in their expected
watchdog state. Artifact and comparison assertions passed before publication.
Documentation validation passed four tests and 740 subtests; report front
matter, postflight state, and patch whitespace checks also passed.

## Interpretation

The ADC fault did not reproduce in this watchdog-disabled trial. The earlier
watchdog-enabled firmware also passed a 600-second capture after its failure,
so one passing disabled run does not establish that the watchdog caused the
fault or that disabling it fixes the intermittent failure. Host SDK CPU use
was approximately the same as the preceding enabled pass (0.669 cores);
these runs do not measure the Teensy's watchdog-refresh cycle cost.
