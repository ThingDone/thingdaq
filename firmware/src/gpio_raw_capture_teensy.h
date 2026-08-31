#pragma once

#include "gpio_raw_capture.h"

namespace thingdaq::gpio_capture {

struct HardwareSnapshot {
  Snapshot ring{};
  std::uint32_t gpr27 = 0U;
  std::uint32_t gpio2_gdir = 0U;
  std::uint32_t gpio2_psr = 0U;
  std::uint32_t pit_ldval = 0U;
  std::uint32_t pit_tctrl = 0U;
  std::uint32_t dmamux_chcfg = 0U;
  std::uint32_t dma_erq = 0U;
  std::uint32_t dma_err = 0U;
  std::uint16_t tcd_citer = 0U;
  std::uint16_t tcd_biter = 0U;
  std::uint16_t tcd_csr = 0U;
  std::uint8_t edma_priority = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::uint32_t stale_dma_completions = 0U;
  bool hardware_running = false;
  bool faulted = false;
};

// Thin singleton facade over the fixed Teensy 4.0 register adapter. Runtime
// preflights it before START, then arms the packet/packer epoch before this
// adapter enables the hardware trigger.
class TeensyRawCapture final : public HardwareCapture {
 public:
  StartStatus inspectStart() override;
  StartStatus prepare() override;
  StartStatus start() override;
  StopReport stopAfterTriggers() override;
  StopReport stop() override;
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;
  Snapshot rawSnapshot() override;
  HardwareSnapshot snapshot();
};

TeensyRawCapture &teensyRawCapture();

}  // namespace thingdaq::gpio_capture
