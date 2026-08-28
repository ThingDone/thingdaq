/*
 * Teensy DAQ Phase 06 GPIO-clock diagnostic foundation.
 *
 * Native USB and its chip-derived serial descriptor are initialized by the
 * pinned Teensy core before global C++ construction and setup(). The portable
 * runtime owns all bounded parser, state, statistics, and transport work.
 */
#include "src/firmware_runtime.h"
#include "src/checksum_benchmark_teensy.h"
#include "src/gpio_clock_diagnostic_teensy.h"
#include "src/teensy_clock.h"
#include "src/teensy_usb.h"

namespace {

// Packet banks stay CPU-owned; the CDC core copies into its own DMA TX ring.
teensy_daq::usb::TeensyCdcByteStream cdc_stream{};
teensy_daq::packet::PacketBufferPrimaryStorage packet_storage_primary{};
DMAMEM teensy_daq::packet::PacketBufferReserveStorage packet_storage_reserve{};
teensy_daq::packet::PacketBufferStorage packet_storage{packet_storage_primary, packet_storage_reserve};
teensy_daq::clock::TeensyTickClock tick_clock{};
teensy_daq::runtime::FirmwareRuntime firmware_runtime{cdc_stream,
                                                       packet_storage,
                                                       tick_clock,
                                                       teensy_daq::synthetic::Mode::kRealtime,
                                                       &teensy_daq::benchmark::teensyRunner(),
                                                       &teensy_daq::gpio_clock::teensyRunner()};

}  // namespace

void setup() {
  // Do not initialize the Arduino serial facade, wait for DTR, or emit a
  // banner. BOOT completion is bounded and independent of host presence.
  (void)firmware_runtime.begin(teensy_daq::usb::hardwareSerialNumber());
}

void loop() {
  // One call performs bounded RX, at most one command dispatch, event
  // acknowledgement, packet promotion, and bounded TX. Teensy's main() calls
  // yield afterward.
  (void)firmware_runtime.service();
}
