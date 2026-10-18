---
type: guide
title: Port Seed ESP32
created: 2026-10-18
tags:
  - thingdaq
  - port
  - seed
  - esp32
  - wifi
related:
  - '[[port-seed-common]]'
  - '[[Protocol-V2]]'
  - '[[Hardware-Safety]]'
---

# Port seed: ESP32-S3 and ESP32-C6

Read [[port-seed-common]] first. This document adds the ESP32 specifics.
The product shape differs from the other ports: the device joins the
user's WiFi as a station and streams to the browser over the network,
with USB used for provisioning and as a slow fallback. The first release
is a **1 MHz digital capture device with no ADC stream**.

## 1. Targets and toolchain

| Item | ESP32-S3 (primary) | ESP32-C6 (secondary) | Classic ESP32 |
| --- | --- | --- | --- |
| Cores | 2 × Xtensa LX7 240 MHz | 1 × RISC-V 160 MHz | 2 × LX6 240 MHz |
| RAM | 512 KB + 8 MB PSRAM on most modules | 512 KB, no PSRAM | 320 KB |
| USB | Native full-speed OTG | USB-Serial-JTAG only | None |
| WiFi | 802.11n 2.4 GHz | WiFi 6 2.4 GHz | 802.11n |
| Parallel capture | LCD_CAM camera mode, 8/16-bit | PARLIO RX, up to 16-bit, internal clock | I2S camera mode |
| Verdict | Build here first | Second target | Excluded: no USB, no PSRAM, ADC2 conflicts |

Use **ESP-IDF 5.3 or newer** with CMake. Arduino-ESP32 is not suitable:
its prebuilt `sdkconfig` fixes the WiFi and lwIP buffer sizes, and the
capture peripherals have no Arduino wrappers. Set `CONFIG_FREERTOS_HZ=1000`,
pin the WiFi task to core 0 and the capture and packer tasks to core 1 on
the S3, and enable PSRAM with the octal or quad mode matching the module.

## 2. Capture design

**ESP32-C6 (PARLIO RX).** Configure a `parlio_rx_unit` with
`data_width = 16` (or 8), `clk_in_gpio_num = -1` so the unit generates its
own sample clock, and an exact 1 MHz `exp_clk_freq_hz`. Use the
level-delimiter or soft-delimiter mode with infinite receive and
`on_partial_receive` callbacks delivering GDMA-filled buffers of 4048 or
2024 items. This is the cleanest capture path of the three families.

**ESP32-S3 (LCD_CAM camera mode).** Camera mode needs a pixel clock input
and valid signals. Generate 1 MHz with LEDC on one GPIO and route it back
into the camera PCLK input through the GPIO matrix; tie VSYNC and HREF to
the constant-high matrix signal. Configure 16 data lines on any GPIOs and
let GDMA fill descriptors in a ring. Use the `esp_cam_ctlr` DVP driver
where IDF 5.4 or newer supports it; otherwise program LCD_CAM registers
directly. This is the riskiest module in the S3 port, so build it first.

Timestamps: both units clock from the 80 MHz APB or PLL. 1 MHz is an
exact divisor, so sample *n* is `n × 8` ticks from START. Record nothing
else.

**ADC.** Leave the `ADC_STREAM` capability bit clear and
`supported_stream_mask = 2`. The on-chip SAR peaks at 83.3 kS/s aggregate
through `adc_continuous` on S3 and C6 and is well below 12 effective bits.
If analog is wanted later, add a low-rate profile (2 × 40 kS/s) in
protocol v3 rather than pretending to match the other boards.

## 3. Pins

| Function | ESP32-S3 | ESP32-C6 |
| --- | --- | --- |
| Inputs bits 0–15 | Any 16 GPIOs not used by flash, PSRAM or USB; avoid GPIO19/20 (USB) and GPIO26–37 (PSRAM/flash) | Any 16 of GPIO0–GPIO23 excluding GPIO12/13 (USB-JTAG) and GPIO24–30 (flash) |
| Sample clock loopback | One spare GPIO | Not needed |
| Strapping pins | Keep GPIO0, 3, 45, 46 out of the capture set | Keep GPIO4, 5, 8, 9, 15 out |

Publish the chosen map in INFO. Keep the map identical between 8-input and
16-input modes so bit 0 is the same pin in both.

## 4. Transports

One frame codec, three byte streams:

| Transport | Role | Implementation |
| --- | --- | --- |
| USB CDC (S3) or USB-Serial-JTAG (C6) | Provisioning, identity, slow capture fallback | `tinyusb` component on S3, `usb_serial_jtag` driver on C6 |
| Raw TCP, port 5555, one client | Python SDK and every rig script unchanged via `SERIAL_PORT=socket://host:5555` | lwIP socket, 64 KB send buffer |
| WebSocket, binary frames, `/stream` | Browser | `esp_http_server` with `httpd_ws_send_frame_async`; batch 8 to 16 wire frames per message |

The control protocol is identical on all three. Only one data consumer at
a time: a START on one transport while another is RUNNING returns BUSY.

**Provisioning commands.** Add three vendor commands in protocol v3 and
document their schemas in the JSON: `SET_WIFI_CREDENTIALS` (`0x30`, SSID
and passphrase, stored in NVS), `GET_NETWORK_STATUS` (`0x31`, state,
RSSI, IPv4, hostname), `SCAN_WIFI` (`0x32`, bounded list). Advertise
`thingdaq-<serial>.local` over mDNS so the website never needs the IP.

**Browser mixed-content constraint.** A page served over https cannot open
`ws://` to a LAN device, and self-signed `wss://` fails without certificate
installation. Decide early: serve the web app from the device over http
(LittleFS partition, same build), or host the site over plain http. The
USB provisioning page can hand the user a link to the device-served app.

## 5. Buffering and WiFi settings

- Disable power save: `esp_wifi_set_ps(WIFI_PS_NONE)`. Default modem sleep
  halves throughput and adds 100 ms gaps.
- Station mode only; 802.11n, 40 MHz bandwidth allowed, AMPDU TX on.
- `sdkconfig`: `ESP_WIFI_STATIC_RX_BUFFER_NUM=16`,
  `ESP_WIFI_DYNAMIC_TX_BUFFER_NUM=32`, `LWIP_TCP_SND_BUF_DEFAULT=65535`,
  `LWIP_TCP_WND_DEFAULT=65535`, `LWIP_TCP_RECVMBOX_SIZE=64`.
- Packet ring in PSRAM on the S3: 1 MB (256 frames) absorbs a 500 ms AP
  stall at 2 MB/s. On the C6 the ring is ~300 KB of internal RAM, so
  advertise 8-input 1 MHz only, or 16-input with the expectation that
  loss counters will show stalls on weak networks.
- Planning numbers for a station on a typical home AP: 1.5 to 2.5 MB/s
  sustained, 100 to 500 ms stalls. 8 inputs at 1 MHz (1 MB/s) is
  reliable; 16 inputs (2 MB/s) works on a good network and fails
  honestly on a bad one.

## 6. Identity, temperature, health

- `hardware_serial`: fold the 48-bit base MAC to a nonzero u32.
- USB VID 0x303A (Espressif) with a PID from their open allocation;
  product string `ThingDAQ`.
- GET_TEMPERATURE: `temperature_sensor` driver, valid at all times.
- GET_RUNTIME_HEALTH: minimum free stack of the capture, packer and
  network tasks, task watchdog state, and additionally free PSRAM.

## 7. Harness mapping

| Milestone | Command |
| --- | --- |
| M0 | `SERIAL_PORT=/dev/ttyACM0 python rig_control_smoke.py` (v2 edits), then the same over `SERIAL_PORT=socket://thingdaq-1234.local:5555` |
| M2 | `rig_synthetic_stream.py` over TCP for 10 minutes on the real network; record loss and stall counters |
| M3 | `rig_release_sdk.py` with `AUX_INPUT_SDK_CASES=gpio8,gpio16` over TCP |
| M5 | Adapted soak program over TCP, 600 s, plus a USB run for the fallback path |
| M6 | `rig_host_stall_recovery.py` over TCP; also pull the AP's power for 2 s and confirm reconnection and honest loss |

Add one ESP32-specific rig: a browser test page that opens the WebSocket,
counts bytes and sequence gaps for 60 s and prints a JSON report, because
the browser's WebSocket path is not exercised by the Python rigs.

## 8. Effort and risk

| Item | Estimate | Risk |
| --- | --- | --- |
| Core and host tests | 2 weeks | Low |
| PARLIO capture (C6) | 3 days | Low |
| LCD_CAM capture (S3) | 1 week | High: clock loopback, valid-signal tie-off, descriptor ring |
| USB CDC / Serial-JTAG transport | 2 days | Low |
| WiFi station, NVS provisioning, mDNS, TCP server | 1 week | Medium |
| WebSocket server, batching, PSRAM ring | 4 days | Medium |
| Website: provisioning page, WebSocket transport, mixed-content decision | 1 week | Medium, decision-bound |
| Validation M0–M6 on two networks | 1.5 weeks | |
| **Total, S3 first then C6** | **~8 weeks** | |
