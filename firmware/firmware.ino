/*
 * Teensy DAQ Phase 07 synchronized GPIO and dual-ADC runtime.
 *
 * Native USB and its chip-derived serial descriptor are initialized by the
 * pinned Teensy core before global C++ construction and setup(). The portable
 * runtime owns all bounded parser, state, statistics, and transport work.
 */
#include "src/firmware_runtime.h"
#include "src/adc_dma_capture_teensy.h"
#include "src/adc_initializer_teensy.h"
#include "src/adc_trigger_teensy.h"
#include "src/checksum_benchmark_teensy.h"
#include "src/gpio_clock_diagnostic_teensy.h"
#include "src/gpio_capture_diagnostic_teensy.h"
#include "src/gpio_raw_capture_teensy.h"
#include "src/gpio_batch_packer_teensy.h"
#include "src/teensy_clock.h"
#include "src/teensy_usb.h"
namespace {
// Packet banks stay CPU-owned; the CDC core copies into its own DMA TX ring.
teensy_daq::usb::TeensyCdcByteStream cdc_stream{};
teensy_daq::packet::PacketBufferPrimaryStorage packet_storage_primary{};
DMAMEM teensy_daq::packet::PacketBufferReserveStorage packet_storage_reserve{};
teensy_daq::packet::PacketBufferStorage packet_storage{packet_storage_primary, packet_storage_reserve};
teensy_daq::gpio_packer::GpioBatchPacker gpio_packer{
    teensy_daq::gpio_capture::teensyRawCapture(),
    teensy_daq::gpio_packer::teensyPackedBufferStorage(),
    &teensy_daq::gpio_packer::teensyCycleCounter()};
teensy_daq::adc_packer::AdcFramePacker adc_packer{
    teensy_daq::adc_capture::teensyAdcDmaCapture()};
teensy_daq::clock::TeensyTickClock tick_clock{};
teensy_daq::runtime::FirmwareRuntime firmware_runtime{
    cdc_stream, packet_storage, tick_clock,
    teensy_daq::synthetic::Mode::kRealtime,
    &teensy_daq::benchmark::teensyRunner(),
    &teensy_daq::gpio_clock::teensyRunner(),
    &teensy_daq::gpio_capture::teensyRawCapture(), &gpio_packer,
    &teensy_daq::gpio_diagnostic::teensyRunner(),
    &teensy_daq::adc::teensyInitializer(),
    &teensy_daq::adc_trigger::teensyScheduler(),
    &teensy_daq::adc_capture::teensyAdcDmaCapture(), &adc_packer};
}  // namespace

void setup() {
  // Do not initialize the Arduino serial facade, wait for DTR, or emit a
  // banner. Both ADC modules are explicitly reconfigured and independently
  // calibrated under a DWT deadline before the bounded BOOT completion.
  (void)firmware_runtime.begin(teensy_daq::usb::hardwareSerialNumber());
}

void loop() {
  // Service one bounded cooperative control/data-path iteration. Teensy's
  // main() calls yield afterward.
  (void)firmware_runtime.service();
}
