# Standalone ADC timing probe

This characterization sketch reuses the production ADC initializer and trigger
adapter. It is **not production firmware or a protocol acceptance test**: there
is no GPIO capture, USB sample stream, checksum, watchdog, or production memory
layout. It changes ADC, ADC_ETC, PIT, XBAR and DMA state. Restore the normal
firmware after use. Results and limitations are in
[the recovery report](../adc528-recovery-20261013.md).

From the repository root, using the pinned Teensy 1.62.0 platform:

```bash
arduino-cli compile \
  --fqbn teensy:avr:teensy40:usb=serial,speed=528,opt=o2std \
  --warnings all \
  --build-property "build.flags.defs=-D__IMXRT1062__ -DTEENSYDUINO=160 -I$PWD/firmware/src" \
  --output-dir doc/results/raw/adc528-probe-build \
  doc/results/experiments/adc528_probe
```

The definitions preserve this pinned platform's `teensy40.build.flags.defs`
(its `TEENSYDUINO` value is 160). The include path lets the standalone sketch
compile the existing adapters directly. Use `speed=450` for the positive control.
Both variants have been compiled. They are not run through production firmware
memory-layout gates and must not be represented as passing those gates.

After programming an authorized test board, open its USB serial port and send
one ASCII command. Each run emits `PROBE ` followed by JSON, ending in
`PROBE_DONE`. Allow at least 90 seconds for a command. Prefer a fresh boot per
command; the recorded campaign reflashed before each submission.

| Command | Characterization | Expected JSON rows |
| --- | --- | ---: |
| `r` | Software polling, then 72 ADC_ETC cells: two divider paths, B2B on/off, either/both ADCs, six PIT rates | 89 |
| `d` | PIT/XBAR-triggered DMA writes to HC0, separate result DMA, each ADC and divider path | 17 |
| `c` | Single-converter continuous DMA, four sample-time settings, each ADC and divider path | 17 |
| `s` | Both ADCs continuously converting for 60 seconds, separate circular DMA buffers | 2 |

The first row records actual CPU/IPG clocks and calibration readiness. `direct=0`
uses IPG/2 then /2; `direct=1` uses IPG then /4. Both yield 33 MHz at 528 MHz
or 37.5 MHz at 450 MHz. Twelve-bit resolution and high-speed mode stay enabled.
PIT rate is 24 MHz divided by `ticks`. Timing windows include startup and endpoint
effects; observed DONE events are not aperture measurements. Error counts are
polled status observations, not an exact count of every lost trigger.

The continuous soak counts modulo-16,384 DMA transfers while extending DWT
cycles to 64 bits. Check that the maximum polling interval is shorter than a
buffer wrap and compare totals with `elapsed_seconds * ADCK / 28`. This is
aggregate transfer accounting, not validation of every analog value or exact
channel phase. Only the final buffers are checked for codes outside 0–4095.
The two converters start through separate software writes; the normal 500 ns
channel offset is not established. The buffer is overwritten intentionally;
there is no host delivery or full sample archive.
