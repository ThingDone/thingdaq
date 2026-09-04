#include "src/firmware_runtime.h"
#include "src/adc_dma_capture_teensy.h"
#include "src/adc_initializer_teensy.h"
#include "src/adc_trigger_teensy.h"
#include "src/checksum_benchmark_teensy.h"
#include "src/digital_output_teensy.h"
#include "src/gpio_clock_diagnostic_teensy.h"
#include "src/gpio_capture_diagnostic_teensy.h"
#include "src/gpio_raw_capture_teensy.h"
#include "src/gpio_batch_packer_teensy.h"
#include "src/teensy_clock.h"
#include "src/teensy_usb.h"
namespace {
// Packet banks stay CPU-owned; the CDC core copies into its own DMA TX ring.
thingdaq::usb::TeensyCdcByteStream cdc_stream{};
thingdaq::packet::PacketBufferPrimaryStorage packet_storage_primary{};
DMAMEM thingdaq::packet::PacketBufferReserveStorage packet_storage_reserve{};
thingdaq::packet::PacketBufferStorage packet_storage{packet_storage_primary, packet_storage_reserve};
thingdaq::digital_output::ProgramStorage aux_output_program_storage{};
DMAMEM thingdaq::digital_output::DmaBlockStorage aux_output_dma_ring{};
DMAMEM thingdaq::digital_output::DmaDescriptorStorage aux_output_dma_descriptors{};
thingdaq::digital_output::TeensyOutput &aux_output =
    thingdaq::digital_output::teensyOutput(
        aux_output_program_storage, aux_output_dma_ring,
        aux_output_dma_descriptors);
thingdaq::gpio_packer::GpioBatchPacker gpio_packer{
    thingdaq::gpio_capture::teensyRawCapture(),
    thingdaq::gpio_packer::teensyPackedBufferStorage(),
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
    &aux_output};
}  // namespace

void setup() {
  // Binding output storage is register-free; BOOT leaves D16-D23 as inputs.
  (void)firmware_runtime.begin(thingdaq::usb::hardwareSerialNumber());
}

void loop() {
  // Service one bounded cooperative control/data-path iteration. Teensy's
  // main() calls yield afterward.
  (void)firmware_runtime.service();
}
