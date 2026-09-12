---
type: result
title: Firmware Runtime Hardening
created: 2026-09-12
tags:
  - thingdaq
  - firmware
  - reliability
related:
  - '[[Watchdog-and-Poll-Bounds]]'
  - '[[Protocol-V2]]'
  - '[[API-Reference]]'
---

# Firmware runtime hardening review

Three independent investigations reviewed watchdog/poll bounds, interrupt
synchronization, and vector/storage ownership. The integrating review added
stack instrumentation and the complete firmware-to-Python command path.

| Finding | Assessment and implemented response |
| --- | --- |
| Missing watchdog and DWT-only waits | Confirmed missing recovery coverage. Five waits, rather than four, lacked independent poll caps. Added caps and a nominal four-second RTWDOG refreshed once after each main-loop service. Capture and clear sticky reset cause once at boot and expose the retained value. ADC stop already had poll caps. |
| Plain ISR flags and multi-word publication | Confirmed five flags needed compiler-visible asynchronous access. Marked them volatile. Also fixed coherent snapshot boundaries in ADC and both GPIO adapters. Existing ring locks and generation counters already serialize multi-word records; encompassing masked snapshots fix the actual races without an additional seqlock/retry protocol. Volatile alone would not make a record coherent. |
| Hand-written PRIMASK sections | No proven unmatched restore: original findings included intentional token-based enter/exit pairs. Added one shared RAII guard with exact mask restoration, compiler barriers and explicit early release where cache work belongs outside the mask. Portable critical-section adapters reuse its primitives. |
| IRQ_DMA_CH2 shared ownership | Normal simultaneous starts were indirectly excluded by storage/resource checks, but handlers remained attached after teardown. Added explicit runtime vector leases keyed to the existing static IRQ table, including ADC vectors. STOP/rollback disable, clear, restore the previous handler and release ownership. An inactive legacy GPIO STOP now cannot disable paired GPIO hardware. |
| Stack margin | The 32,768-byte RAM1 build floor already existed and remains enforced. Added a boot-lifetime canary watermark and runtime query. The verified release build reports 34,464 bytes for locals/stack, of which 32 bytes are excluded by the MPU guard. |
| Nested placement construction | Confirmed nested paired-workspace construction obscured the storage lifetime precondition and broke cppcheck parsing. Named storage addresses and sequential construction make it explicit; paired storage ownership is checked before use. Target assertion failure uses a small trap instead of libc formatted assertions. |

The standard libc assertion pulled formatted I/O and allocator support into the
first integration image and failed the RAM1 floor. Replacing it with the target
trap removed that dependency. The small remaining ITCM overflow was resolved
by putting post-measurement checksum metrics in flash, using the existing cold
code convention. The checksum kernels, packet capacity (200 frames), and
required memory floors are unchanged. ITCM code occupies 32,520 bytes in the
verified build, below the 32 KiB bank boundary; RAM2 keeps its existing
4,096-byte heap margin.

## Runtime command and long tests

Use `daq.get_runtime_health()` on the same `ThingDAQ` object already owning the
acquisition. Firmware command `GET_RUNTIME_HEALTH` is v2 kind `0x1B`, with a
32-byte successful payload in response `0x9B`. It works while idle, configured,
or running; it neither stops capture nor clears the watermark. Earlier
firmware can reject this optional command. Install the matching SDK source.

For an existing long-test loop that already consumes data, periodically add:

```python
from dataclasses import asdict
import json
import time

# daq is the existing connected client; keep draining data in the test loop.
# Run this sampling block at a modest interval, for example once per minute.
health = daq.get_runtime_health()
print(json.dumps({"time": time.time(), **asdict(health)}), flush=True)
assert health.stack_available
assert health.watchdog_enabled
```

Record a baseline after connection, samples during the workload, and a final
sample after STOP/draining. Include the firmware build ID in the test record.
Exercise both bank modes, ADC/GPIO combinations, checksums, repeated START/STOP,
queue pressure and control queries. Judge the minimum free margin across the
whole run; RESET_STATS and host reconnect do not clear it. Reboot starts a new
watermark history, so never combine records across reconnects after reset as
one uninterrupted test. SRC_SRSR bit 7 indicates WDOG3 reset. A disabled watchdog
reports a zero timeout; initialization refusal is observable through these
fields but currently does not prevent acquisition.

The probe paints only unused DTCM memory in `startup_late_hook`, before global
constructors and setup, after core memory and USB initialization. It skips the
32-byte MPU no-access region at `_ebss` and leaves 128 bytes below its own live
MSP untouched. That margin and the active startup frame count as used. The
reported total is `_estack - (_ebss + 32)`. There is no heap overlap: the pinned
core allocates its heap from OCRAM.

Reading scans at most the prior free prefix (about 8,600 words in this build),
with interrupts enabled. The minimum can only decrease; painting never repeats
within a boot. A concurrent ISR after a word was scanned may be reflected by
the next query. Reading the diagnostic itself also contributes stack usage.

This is a canary high-water estimate of overwritten memory, not proof of the
maximum historical stack-pointer depth. Reserved but unwritten stack slots,
or writes equal to the canary, can understate usage. It does not measure core
startup before the hook, provide overflow protection beyond the core's MPU
trap, or establish that future workloads fit. Select a test acceptance margin
with those limits in mind.

## Validation and remaining work

Final validation: 203 firmware tests / 831 subtests and 384 SDK tests /
15,507 subtests passed. Ruff, mypy (27 modules), generated-output checks and
cppcheck parsing passed. SDK tests ran against a clean staged export so the
user's pre-existing, untracked analysis report was neither modified nor included
in the proposed commit's documentation checks.

The pinned release build succeeds at
`teensy:avr:teensy40:usb=serial,speed=450,opt=o2std` with Teensy core 1.62.0 and
ARM GCC 15.2.1. Its checked manifest retains memory, allocation, checksum and
capacity gates. Host coverage includes guard nesting/early returns, vector
contention/restoration, watchdog register handshakes and failures, canary
monotonicity, malformed/replayed health messages, acquisition-state preservation,
and the actual parser/runtime/USB response queue path. SDK tests cover the
public command, simulator, fragmented frames and device errors. V1 generated
bytes remain frozen; v2 adds two golden fixtures. Cppcheck 2.13.0 now parses both
placement-construction files with the real target defines.

These changes have not been flashed or qualified on hardware. The required
watchdog-reset injection, stalled-DWT injection, worst-case operation timing,
and sustained acquisition watermark measurements are listed in
[[Watchdog-and-Poll-Bounds]]. Host register fakes cannot establish actual clock
accuracy, reset propagation, ISR timing or USB reconnection behavior.

## Primary references

- [PJRC Teensy 4.0 memory documentation](https://www.pjrc.com/store/teensy40.html)
  describes the downward RAM1 stack and separate RAM2 allocation.
- [PJRC core startup](https://github.com/PaulStoffregen/cores/blob/master/teensy4/startup.c)
  and [linker layout](https://github.com/PaulStoffregen/cores/blob/master/teensy4/imxrt1062.ld)
  identify the hook order and stack/MPU boundaries. Implementation was checked
  against the locally installed, pinned 1.62.0 sources and compiled disassembly,
  not assumed from the moving upstream branch.
- Watchdog hardware sources and chip-specific clock details are linked in
  [[Watchdog-and-Poll-Bounds]].
