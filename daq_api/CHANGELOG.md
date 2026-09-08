# Python SDK changelog

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
