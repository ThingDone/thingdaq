/*
 * ThingDAQ Phase 07 synchronized GPIO and dual-ADC runtime.
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
#include "src/gpio_dual_bank_capture_teensy.h"
#include "src/gpio_dual_bank_packer.h"
#include "src/teensy_clock.h"
#include "src/teensy_usb.h"
#include "src/variable_rate_scheduler_teensy.h"
namespace {
// Packet banks stay CPU-owned; the CDC core copies into its own DMA TX ring.
thingdaq::usb::TeensyCdcByteStream cdc_stream{};
DMAMEM thingdaq::packet::PacketBufferReserveStorage packet_storage_reserve{};
thingdaq::packet::PacketBufferStorage packet_storage{
    thingdaq::benchmark::teensyPacketPrimaryStorage(),
    packet_storage_reserve};
thingdaq::gpio_packer::GpioBatchPacker gpio_packer{
    thingdaq::gpio_capture::teensyRawCapture(),
    thingdaq::gpio_packer::teensyPackedBufferStorage(),
    &thingdaq::gpio_packer::teensyCycleCounter()};
thingdaq::gpio_aux_packer::AuxiliaryBatchPacker aux_gpio_packer{
    thingdaq::gpio_join::teensyDualBankCapture(),
    &thingdaq::gpio_packer::teensyCycleCounter()};
thingdaq::adc_packer::AdcFramePacker adc_packer{
    thingdaq::adc_capture::teensyAdcDmaCapture()};
thingdaq::clock::TeensyTickClock tick_clock{};
thingdaq::runtime::FirmwareRuntime firmware_runtime{
    cdc_stream, packet_storage, tick_clock,
    thingdaq::synthetic::Mode::kRealtime,
    &thingdaq::benchmark::teensyRunner(),
    &thingdaq::gpio_clock::teensyRunner(),
    &thingdaq::gpio_capture::teensyRawCapture(), &gpio_packer,
    &thingdaq::gpio_diagnostic::teensyRunner(),
    &thingdaq::adc::teensyInitializer(),
    &thingdaq::adc_trigger::teensyScheduler(),
    &thingdaq::adc_capture::teensyAdcDmaCapture(), &adc_packer,
    &thingdaq::variable_rate::teensyRateScheduler(),
    &thingdaq::gpio_join::teensyDualBankCapture(), &aux_gpio_packer,
    &thingdaq::temperature::readTeensy};
}  // namespace

void setup() {
  // Do not initialize the Arduino serial facade, wait for DTR, or emit a
  // banner. Both ADC modules are explicitly reconfigured and independently
  // calibrated under a DWT deadline before the bounded BOOT completion.
  (void)firmware_runtime.begin(thingdaq::usb::hardwareSerialNumber());
}

void loop() {
  // Service one bounded cooperative control/data-path iteration. Teensy's
  // main() calls yield afterward.
  (void)firmware_runtime.service();
}
