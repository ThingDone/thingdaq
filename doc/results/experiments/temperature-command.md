---
type: experiment
title: Temperature command and instrumented input soaks
created: 2026-09-04
tags: [thingdaq, firmware, temperature, input-isolation]
related: [input-rate-clock-design.md]
---

# Temperature command and instrumented input soaks

`GET_TEMPERATURE` is an append-only **experimental v2** command: request kind
`0x1a`, empty payload; response `0x9a`, 12-byte success payload. It uses the
existing request-ID/run-ID correlation, Adler-32 control checksum, response
reservation, replay protection and four-byte typed-error response. V1 rejects
these IDs and all frozen v1 bytes remain unchanged. Older v2 firmware can reject
the optional command as unknown; do not infer support solely from version 2.

| Payload offset | Field |
| --- | --- |
| 0–3 | Existing response prefix: status, reserved, error code |
| 4 | Sensor status: 0 VALID, 1 UNAVAILABLE, 2 NOT_READY, 3 INVALID_CALIBRATION, 4 OUT_OF_RANGE |
| 5–7 | Reserved, zero |
| 8–11 | Signed two's-complement 32-bit millidegrees Celsius, little endian |

The value is meaningful only for VALID; all other statuses require zero on the
wire and become `None` in the Python decoder. Accepted reporting range is
−40 to +150 °C, not a claim that operation across that range is safe.

The Teensy adapter snapshots the core's already-running TEMPMON registers and
uses the OTP hot/room calibration formula from the earlier clock-health adapter.
It does not wait, force a conversion, change alarms, disable interrupts or touch
acquisition pins. This reports the **latest die-temperature conversion**, not
ambient temperature or a guaranteed newly triggered measurement. Replies work
in IDLE, CONFIGURED and RUNNING without changing acquisition state.

## Reading and testing

With exclusive ownership of the serial port and this firmware installed:

```bash
python firmware/tools/read_temperature.py --port /dev/ttyACM0
```

This reuses the existing bounded rig parser and prints a JSON reading. It does
not start or stop acquisition. Do not run a second serial client alongside a
capture. In a host application, the v2 wire codec provides
`encode_v2_frame(FrameKind.GET_TEMPERATURE_REQUEST, request_id=...)` and
`decode_temperature_payload(...)`; the high-level `ThingDAQ` API has not yet
gained a temperature method or support for the research equal-rate profile table.

Main's `firmware/tools/run_input_isolation.py --temperature` uses the sole
acquisition serial owner to record before/after readings and an in-band reading
every ten seconds. It retains statuses, host monotonic timestamps and response
latencies in each cell's evidence, including failed cells. Transient NOT_READY
gets at most five host-side attempts while continuing to drain data; all attempts
are retained. An unavailable reading after these attempts
or temperature at/above 80 °C aborts this campaign and executes its existing
best-effort STOP cleanup; the core's thermal protection is unchanged.

The controlled matrix is 450 MHz core, 8/16 GPIO inputs, both ADC channels
enabled, equal 1 MHz/500 kHz sampling, followed by repeated START/STOP and profile
switches. No loopback or external stimulus is assumed. All existing transport,
rate, DMA, timestamp, bank-join, queue and STOP-reconciliation checks remain.
Temperature comparisons are descriptive, not controlled ambient/power/lifetime
measurements. Evidence and final results are published on main separately.
