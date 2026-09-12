---
type: research
title: Runtime Watchdog and Independent Poll Bounds
created: 2026-09-12
tags:
  - thingdaq
  - firmware
  - watchdog
  - imxrt1062
related:
  - '[[Firmware-Resource-Map]]'
---

# Runtime watchdog and independent poll bounds

The firmware audit confirmed that there was no application watchdog setup or
refresh. Five hardware waits depended only on DWT advancing: GPIO stop,
single-bank and dual-bank GPIO capture diagnostics, GPIO clock measurement,
and ADC DMA pipeline alignment. The ADC stop and ADC trigger diagnostic waits
already had independent poll limits. The initial DWT availability probes do
not guarantee that the counter keeps advancing after a peripheral is armed.

All five missing waits now have iteration bounds. GPIO stop and capture
diagnostic exhaustion use their existing unsuccessful stop/timeout paths.
ADC alignment returns its existing invalid-pipeline result. Clock measurement
reports `DwtUnavailable` and still disables PIT, DMA requests and XBAR requests.
No bounded wait refreshes the watchdog.

## RTWDOG configuration

`firmware/src/watchdog_teensy.cpp` configures WDOG3 with a nominal four-second
timeout. It uses clock selector 1, the 256 prescaler and 512 counter ticks.
On RT1060, selector 1 is the 32 kHz crystal source, with automatic RC fallback;
it is **not** the 1 kHz LPO used on some other watchdog implementations. At
32.768 kHz the nominal timeout is exactly 4,000 ms; fallback RC accuracy can
change elapsed wall time.

The module captures SRC_SRSR once, then clears its sticky flags so a subsequent
boot does not inherit a previous watchdog-reset indication. WDOG3 reset is bit
7; the temperature-reset flag in bit 8 has different clear semantics. The raw
boot value remains available throughout the boot. SRC explicitly unmasks WDOG3
reset using the documented 0xA encoding.

The unlock sequence honors the peripheral's initial 16-bit or 32-bit command
mode. Unlock and configuration occur under the shared interrupt guard and
within ITCM, preserving the documented 128 bus-clock configuration window.
Both handshake waits have independent poll limits. Successful initialization
verifies configuration and timeout readback before enabling refreshes. The
configured 32-bit command mode makes each refresh one peripheral write.

The main loop refreshes only after a cooperative runtime service iteration
returns. WAIT and STOP operation are enabled; debug-halt operation is disabled
to permit debugging. There is no ISR feed or timer feed that could hide a
blocked main loop. Setup enables the watchdog before runtime initialization;
earlier core startup and C++ constructors are outside this coverage.

## Verification and remaining hardware evidence

The host register test executes the actual watchdog adapter with simulated
registers. It covers both initial command widths, preservation of an already
masked caller, failure to unlock, failure to accept configuration, stable
reset-cause capture, idempotent initialization, and exactly one refresh write.
Both failed handshakes terminate without relying on a clock. GPIO diagnostic
and ADC portable tests continue to exercise their existing timeout/error
handling, but do not simulate a DWT that stops halfway through a real transfer.

The changes require these on-device checks before claiming hardware recovery
or long-soak qualification:

1. Run legal maximum-size checksum and clock diagnostic requests while idle,
   then repeated acquisition start/stop. Verify runtime health reports an
   enabled watchdog and that no healthy operation causes a reset.
2. In a dedicated fault-injection firmware build, stall main after one normal
   service iteration. Confirm reset near the nominal four-second interval,
   USB reconnect, and SRC_SRSR bit 7 in the next runtime-health response.
3. In a separate build, stop DWT after the initial availability probe during
   each diagnostic/stop/alignment wait. Confirm bounded failure, stopped
   peripheral requests and subsequent control responsiveness.
4. Run the sustained acquisition workload while periodically recording stack
   watermark and reset cause. A watchdog reset is a test failure to diagnose,
   not evidence that the workload is stable.

No watchdog reset or on-device stalled-counter test was performed by the host
test suite. Register fakes establish software branching and bounds, not real
clock selection, reset propagation or USB recovery.

## Sources

- [NXP i.MX RT1060 reference manual, revision 3](https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf):
  sections 20.8.1/20.8.3 (reset mask and cause), 58.1 (chip-specific clocks),
  58.3.2 (unlock timing), 58.3.3 (debug/low-power operation), and 58.5 (registers).
- [NXP RTWDOG driver](https://github.com/nxp-mcuxpresso/mcux-sdk/blob/master/drivers/rtwdog/fsl_rtwdog.c)
  and [driver header](https://github.com/nxp-mcuxpresso/mcux-sdk/blob/master/drivers/rtwdog/fsl_rtwdog.h):
  protected unlock/configuration order and width-sensitive unlock/refresh.
- The pinned Teensy 1.62.0 core's `imxrt.h` supplies the WDOG3, CCM and SRC
  register definitions; `CrashReport.cpp` independently identifies SRC bit 7
  as WDOG3 reset and clears temperature reset by writing zero.
