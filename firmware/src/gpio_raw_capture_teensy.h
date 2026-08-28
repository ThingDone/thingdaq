#pragma once

#include "gpio_raw_capture.h"

namespace teensy_daq::gpio_capture {

enum class StartStatus : std::uint8_t {
  kOk,
  kAlreadyRunning,
  kNotQuiescent,
  kResourceBusy,
  kHardwareError,
};

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
  bool hardware_running = false;
  bool faulted = false;
};

// Thin singleton facade over the fixed Teensy 4.0 register adapter. It is
// deliberately not connected to CONFIGURE/START until the later physical-mode
// integration task can coordinate the packer and packet epoch atomically.
class TeensyRawCapture final : public RawWordSource {
 public:
  StartStatus start();
  StopReport stop();
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;
  HardwareSnapshot snapshot();
};

TeensyRawCapture &teensyRawCapture();

}  // namespace teensy_daq::gpio_capture
