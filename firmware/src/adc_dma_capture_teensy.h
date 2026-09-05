#pragma once

#include <array>
#include <cstdint>

#include "adc_dma_capture.h"

namespace thingdaq::adc_capture {

struct HardwareChannelSnapshot {
  std::uint32_t dmamux_chcfg = 0U;
  std::uint32_t tcd_saddr = 0U;
  std::uint32_t tcd_daddr = 0U;
  std::uint32_t tcd_nbytes = 0U;
  std::int32_t tcd_dlastsga = 0;
  std::int16_t tcd_doff = 0;
  std::uint16_t tcd_attr = 0U;
  std::uint16_t tcd_citer = 0U;
  std::uint16_t tcd_biter = 0U;
  std::uint16_t tcd_csr = 0U;
  std::uint8_t priority = 0U;
  std::uint8_t current_destination = kInvalidDestination;
  std::uint8_t next_destination = kInvalidDestination;
  std::uint32_t current_generation = 0U;
};

struct HardwareSnapshot {
  Snapshot ring{};
  std::array<HardwareChannelSnapshot, kConverterCount> channels{};
  std::array<std::uint32_t, kConverterCount> adc_gc{};
  std::uint32_t dma_erq = 0U;
  std::uint32_t dma_int = 0U;
  std::uint32_t dma_err = 0U;
  std::uint32_t dma_hrs = 0U;
  std::uint32_t adc_etc_done2_err_irq = 0U;
  std::uint32_t adc_etc_error_flags = 0U;
  std::uint32_t adc_etc_error_interrupts = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::uint32_t stale_interrupts = 0U;
  bool hardware_prepared = false;
  bool faulted = false;
};

class TeensyAdcDmaCapture final : public HardwareCapture {
 public:
  StartStatus inspectStart(std::uint32_t epoch) override;
  StartStatus inspectStart(std::uint32_t epoch,
                           std::uint32_t pairs_per_buffer) override;
  StartStatus prepare(std::uint32_t epoch) override;
  StartStatus prepare(std::uint32_t epoch,
                      std::uint32_t pairs_per_buffer) override;
  bool stopAtBoundaryBeforeTriggers() override;
  StopReport stopAfterTriggers() override;
  std::size_t serviceOwnership() override;
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;
  Snapshot rawSnapshot() override;
  HardwareSnapshot snapshot();
};

// Singleton backed by fixed eDMA channels 0/1 and cache-line-aligned OCRAM.
TeensyAdcDmaCapture &teensyAdcDmaCapture();

}  // namespace thingdaq::adc_capture
