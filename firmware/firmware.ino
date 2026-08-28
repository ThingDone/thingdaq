/*
 * Teensy DAQ Phase 03 control-plane firmware.
 *
 * Native USB and its chip-derived serial descriptor are initialized by the
 * pinned Teensy core before global C++ construction and setup(). The portable
 * runtime owns all bounded parser, state, statistics, and transport work.
 */

#include "src/firmware_runtime.h"
#include "src/teensy_usb.h"

namespace {

// Same-translation-unit declaration order is intentional: the concrete USB
// adapter exists before the runtime stores its byte-stream reference, while
// FirmwareRuntime constructs ControlState/Statistics before CdcTransport.
teensy_daq::usb::TeensyCdcByteStream cdc_stream{};
teensy_daq::runtime::FirmwareRuntime firmware_runtime{cdc_stream};

}  // namespace

void setup() {
  // Do not initialize the Arduino serial facade, wait for DTR, or emit a
  // banner. BOOT completion is bounded and independent of host presence.
  (void)firmware_runtime.begin(teensy_daq::usb::hardwareSerialNumber());
}

void loop() {
  // One call performs bounded RX, at most one command dispatch, event
  // acknowledgement, and bounded TX. Teensy's main() calls yield afterward.
  (void)firmware_runtime.service();
}
