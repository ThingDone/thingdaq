---
type: guide
title: Port Seed Common
created: 2026-10-18
tags:
  - thingdaq
  - port
  - seed
  - protocol
  - harness
related:
  - '[[Protocol-V2]]'
  - '[[Hardware-Safety]]'
  - '[[soak-harness]]'
  - '[[Quickstart]]'
  - '[[port-seed-pico]]'
  - '[[port-seed-feather-m4]]'
  - '[[port-seed-esp32]]'
---

# Port seed: shared contract and test harness

This document seeds a **new, separate repository** that builds ThingDAQ
firmware for a non-Teensy board as a clean-room implementation. It states
what must be byte-identical to the Teensy firmware, what may differ, and how
to use the test assets in this repository to prove the new firmware works.
Read the platform seed for your board after this one:
[[port-seed-pico]], [[port-seed-feather-m4]], [[port-seed-esp32]].

Nothing in this document requires reading the Teensy C++ sources. The
contract is the JSON file and the golden fixtures, not the code.

## 1. Non-negotiable: the wire contract

Copy these files from this repository into the new repository under
`contract/` and record the upstream commit hash in `contract/UPSTREAM`:

| File | Role |
| --- | --- |
| `protocol/protocol-v2.json` | Normative machine-readable contract: header, limits, enums, payload schemas, rate profiles, golden fixture plan |
| `protocol/fixtures-v2/*.bin` | Byte-exact golden request/response/data frames generated from the JSON |
| `tools/generate_protocol.py` | Generates C++ and Python constants and regenerates the fixtures; run it in the new repo so constants are never hand-typed |
| `doc/protocol/protocol-v2.md` | Human-readable version of the same contract |

Everything below is a summary. Where this summary and the JSON disagree, the
JSON wins.

**Envelope.** Little-endian. 44-byte header plus a 4-byte checksum trailer.
Magic `EF BE AD DE`. Header: version at 4 (`2`), kind at 5, flags at 6,
header length at 8 (`44`), checksum ID at 10, total bytes at 12, payload
bytes at 16, run ID at 20, per-stream sequence at 24, request ID at 28,
first-sample ticks at 32 (u64), item count at 40. Control frames use
Adler-32; data frames use Adler-32 by default and may offer CRC32C and
CRC32. The checksum covers header plus payload. Control request IDs are
nonzero and echoed; data frames carry request ID zero. USB packet
boundaries never mean anything; the parser resynchronises on the magic.

**Commands.** INFO `0x10`, CONFIGURE `0x11`, START `0x12`, GET_STATUS
`0x13`, STOP `0x14`, RESET_STATS `0x15`, PING `0x16`, GET_TEMPERATURE
`0x1A`, GET_RUNTIME_HEALTH `0x1B`. Responses are request kind plus `0x80`.
Every successful response starts with `u8 status=0, u8 reserved, u16
error=0`. Typed errors return only that 4-byte prefix with the error flag
set. Unknown kinds return the generic `0x9F` ERROR_RESPONSE. Maximum command
frame is 64 bytes; maximum control frame is 1536 bytes. Malformed input
fails closed and increments a counter; it never resets the device.

**CONFIGURE** payload is 16 bytes: stream mask (ADC=1, GPIO=2), source
(hardware=0, synthetic=1), data checksum ID, auxiliary bank mode (0 = 8
inputs, 1 = 16 inputs), maximum data frame bytes (`4096`), ADC pair rate
Hz, GPIO sample rate Hz. CONFIGURE and START reply with the applied 16-byte
configuration after the prefix. Rates not in the advertised profile mask
are rejected with UNSUPPORTED_CONFIGURATION before any state changes.

**Data frames.** ADC kind `0x01`, items are `u16 ADC0, u16 ADC1` raw 12-bit
codes in 16-bit containers. GPIO kind `0x02`, items are one byte (8 inputs,
bit 0 is the lowest-numbered input) or one little-endian u16 (16 inputs).
Frame size is 4096 bytes including header and trailer except the 16-input
combined ADC frame, which is 2072 bytes. Sequence numbers are per stream and
per run; a gap is loss. `first_sample_ticks` is in an unsigned 64-bit
**8 MHz** tick domain that restarts at zero on every START. Sample *n* in
a frame is at `first_sample_ticks + n * period_ticks`; ADC1 adds
`adc1_phase_ticks`. Every supported period must therefore be an integer
number of 8 MHz ticks (1 MHz = 8, 500 kHz = 16, 200 kHz = 40, 100 kHz =
80).

**STATUS** reports saturating counters: frames sent, items lost, DMA
overruns, parser errors, queue high-water marks, and a statistics
generation that increments on RESET_STATS. The host treats any nonzero
loss counter during a strict capture as failure, so the firmware must count
honestly rather than hide drops.

**Synthetic source.** Source 1 replaces the hardware front end with a
deterministic ramp defined in the JSON (`synthetic_source` formulas). It
lets the host harness verify transport throughput, sequencing and
timestamps on a bare board with no signals attached. Implement it first.

## 2. What may differ, and the decision you must make first

The Teensy firmware fixes one rate profile (ID 4: ADC 1 MS/s per channel,
GPIO 1 MHz) and its INFO payload is 680 bytes, of which roughly 300 bytes
describe i.MX RT registers (PIT, XBAR, eDMA, ADC_ETC). Two options:

| Option | When to use | What changes |
| --- | --- | --- |
| **A. Protocol v2, exact** | The board can honour profile 4 for the streams it advertises. Realistic only for GPIO-only at 1 MHz (ESP32 over WiFi, 8 inputs) | Nothing on the host. Clear the `ADC_STREAM` capability bit, set `supported_stream_mask=2`, fill every Teensy-specific INFO field with zero. |
| **B. Protocol v3, additive** | The board needs lower rates (every full-speed USB board) | Append new rate profile IDs (5 and up) to `rate_profiles` in a `protocol-v3.json` copied from v2, make `rate_profile_count` authoritative for the INFO length, add new `board_id`/`mcu_id` values, bump the version byte to 3. Keep every other offset identical so the host parser change is small. |

Recommendation: B for Pico and Feather M4, A first and B later for ESP32.
Either way the host SDK and website must gain the new board identities
(section 4), so coordinate that change in this repository before the first
hardware milestone.

Propose these identities and keep them in the JSON `enums`:

| Board | `board_id` | `mcu_id` | USB VID:PID | Serial source |
| --- | ---: | ---: | --- | --- |
| Teensy 4.0 (existing) | 1 | 1 IMXRT1062 | 16C0:0483 | chip serial |
| Pico / Pico W | 2 | 2 RP2040 | 2E8A:000A or own PID | `pico_get_unique_board_id` folded to nonzero u32 |
| Pico 2 | 3 | 3 RP2350 | 2E8A:000F or own PID | same |
| Feather M4 Express | 4 | 4 SAMD51J19 | 239A:own PID | 128-bit serial folded |
| ESP32-S3 | 5 | 5 ESP32S3 | 303A:own PID | base MAC folded |
| ESP32-C6 | 6 | 6 ESP32C6 | 303A:own PID | base MAC folded |

USB product string must be `ThingDAQ`. `build_id` must match
`thingdaq-<16 lowercase hex>` derived from a hash of the source tree; the
SDK rejects any other format for a physical board. `hardware_serial` must be
nonzero.

## 3. The harness, piece by piece

All commands below run from a checkout of **this** repository with a venv:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable './daq_api[dev,numpy]'
```

### 3.1 Golden-fixture conformance (first thing to pass)

Pattern: `firmware/tests/protocol_primitives_test.cpp` is a host-compiled
C++ program that encodes every request, decodes every response and data
frame, and compares bytes against `protocol/fixtures-v2/`. The Python
wrapper `firmware/tests/test_protocol_primitives.py` compiles it with:

```bash
g++ -std=c++17 -Wall -Wextra -Werror -Wconversion -Wsign-conversion -pedantic \
    -fno-exceptions -fno-rtti -I<src> <test>.cpp <codec>.cpp <checksum>.cpp -o t
./t protocol/fixtures-v2
```

Copy the pattern, not the code: keep the frame codec, checksum and state
machine free of vendor headers so they compile on the host, and run them
against the vendored fixtures in CI. The fixture manifest lists expected
SHA-256 per file.

### 3.2 Python SDK as the first host

Install the released package and use the CLI against the board:

```bash
python -m pip install thingdone-daq
thingdone-daq capture --duration 5 --strict-loss --gpio-channel D6
thingdone-daq capture --simulate --duration 1 --strict-loss
```

`--simulate` shows exactly what the host expects, offline. The SDK's
discovery filters on VID/PID and product string and then validates
identity; until the SDK accepts the new `board_id` it will refuse the
board, so run `rig_release_sdk.py` with `EXPECTED_*` overrides or patch
`daq_api/src/thingdone_daq/identity.py` and `discovery.py` in a branch.

### 3.3 Independent rig scripts (`firmware/tests/rig_*.py`)

These are single-file validators that import only the standard library and
PySerial, so they run anywhere, including a container with no checkout.
Configure them with environment variables, mainly `SERIAL_PORT`,
`EXPECTED_HARDWARE_SERIAL`, `EXPECTED_BUILD_ID`, `AUX_INPUT_CAPTURE_SECONDS`
and `AUX_INPUT_SDK_CASES` (`adc,gpio8,combined8,gpio16,combined16`).

| Rig | Protocol | Use for a port |
| --- | --- | --- |
| `rig_release_sdk.py` | v2 via SDK | Release acceptance: every stream case, strict loss, temperature, runtime health |
| `rig_aux_input_capture.py` | v2 | 16-input capture without the SDK |
| `rig_control_smoke.py`, `rig_control_recovery.py` | v1 | Control-plane and malformed-input recovery; change `PROTOCOL_VERSION`, INFO size and CONFIGURE payload to v2 before use |
| `rig_synthetic_stream.py` | v1 | Transport throughput with the synthetic source; same edit |
| `rig_host_stall_recovery.py` | v1 | Host stops reading, then resumes; proves bounded buffering and honest loss counts; same edit |

PySerial accepts `socket://host:port` as a port name, so a board that
exposes a raw TCP byte stream (ESP32) runs every rig unchanged.

### 3.4 Soak validator (`firmware/soak/validator.py`)

The canonical endurance validator: parser, link, deadline, metric and
PASS/FAIL logic in one file, with generated 600-second synthetic, physical
and control-stress programs. It is pinned to the Teensy candidate and
protocol v1 through `candidate.json` and the freeze mechanism described in
[[soak-harness]]. For a port, copy the `FrameParser`, `SerialLink`, metric
and report classes, drop the candidate-freeze machinery, and set the
expected INFO values for your board. Keep the report schema so results can
be compared across boards.

### 3.5 Host adversarial tests

`daq_api/tests/test_parser_adversarial.py` and
`test_serial_stack_adversarial.py` feed corrupted, fragmented and
interleaved frames to the host parser. Mirror them in the firmware: a host
test that feeds the same patterns to your command parser must show bounded
memory, an incremented error counter and continued service.

## 4. Host-side work that lives in this repository

- Add the new `board_id`/`mcu_id` enum values and, for option B, the v3
  JSON, generated constants and fixtures.
- Extend `identity.py` to accept the new board/MCU pairs and
  `discovery.py` to match the new VID/PID values.
- Website: same identity and VID/PID filter changes, profile picker driven
  by `supported_rate_profile_mask`, and for ESP32 a WebSocket transport.
- Optional: a `TcpTransport` implementing the SDK `ByteTransport` protocol
  for ESP32.

## 5. Milestones and gates

| Milestone | Gate | Harness used |
| --- | --- | --- |
| M0 Build and identity | Enumerates as `ThingDAQ`, INFO decodes, identity fields valid | SDK discovery, `rig_control_smoke.py` |
| M1 Control plane | All commands and every error path match fixtures; malformed input survives | Fixture test, `rig_control_recovery.py` |
| M2 Synthetic streaming | 10 minutes, every advertised profile, zero loss, timestamps exact | `rig_synthetic_stream.py`, soak synthetic |
| M3 GPIO hardware | Known pattern from a signal generator or a second board decodes bit-exact | `rig_release_sdk.py` gpio cases |
| M4 ADC hardware | DC and sine inputs produce expected codes; phase between channels as advertised | `rig_release_sdk.py` adc cases |
| M5 Soak | 600 s combined capture, zero loss counters, stable memory | Soak physical program |
| M6 Host stall | Host pauses 2 s, loss is counted exactly, capture continues | `rig_host_stall_recovery.py` |

Measure USB or network throughput in M2 before choosing rates, then set
every advertised profile to at most 60 % of the measured sustained rate.

## 6. Repository skeleton for the new project

```text
contract/            vendored JSON, fixtures, generator, UPSTREAM hash
firmware/
  core/              codec, checksum, control state, packet ring, statistics (host-compilable)
  platform/<board>/  DMA, timers, USB or network, identity, temperature
  app/               main, task or loop wiring
tests/host/          g++ unit tests plus fixture conformance
tests/rig/           copied and adapted rig scripts
doc/                 ADRs for the rate profiles, pin map, transport, buffering
```

Keep the core free of vendor headers from day one so the host tests stay
cheap. Record every reservation of a pin, timer, DMA channel and interrupt
in one file, the way `firmware/src/board_config.h` does here.

## 7. Safety

All three target families are 3.3 V, not 5 V tolerant, and have weaker
input protection than the Teensy. The guidance in [[Hardware-Safety]]
applies unchanged. Acquisition pins must stay inputs; the firmware never
drives a capture pin.
