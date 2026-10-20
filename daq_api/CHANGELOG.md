# Python SDK changelog

## 1.2.0 — development candidate (not published)

- Add public protocol-v3 negotiation, metadata, configuration, streaming and
  decoding, with advertised 600 MHz / 1 MHz / RLE_AUTO / PACK12 defaults.
- Extend pre-release v3 STATUS with logical/encoded byte totals and selected
  health counters. Diagnostic availability decodes to `None`/JSON `null`;
  strict health checks reject reported codec, DMA, parser and transport faults.
  The 384-byte STATUS schema requires matching firmware and SDK candidates.
- Retain v1/v2 decoding and explicit legacy simulator personas. Older v2 SDKs
  can use the new firmware's v2 RAW compatibility path.
- Firmware 1.2.0, wire protocol 3 and SDK 1.2.0 are independent version axes.
  Physical qualification remains pending; no package publication is implied.

## 1.1.0 — first public package

- Publish the Python SDK as `thingdone-daq`, imported as `thingdone_daq`.
- Rename console commands to `thingdone-daq`, `thingdone-daq-demo`, and
  `thingdone-daq-soak`.
- Retain the `ThingDAQ` facade, typed models, optional NumPy integration,
  simulator, calibration formats, and firmware identity conventions.
- Support firmware 1.1.0 and protocol v2 with fixed 1 MHz ADC/GPIO acquisition;
  historical simulator profiles remain available for offline regression.

Migration from the private `thingdaq-local` distribution requires updating
imports from `thingdaq` to `thingdone_daq` and command names as above. The
private package name and import alias are not shipped in this distribution.
See the package README for known throughput and alignment limitations.
