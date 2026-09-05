#pragma once

#include <array>
#include <cstdint>

#include "gpio_dual_bank_capture.h"

namespace thingdaq::gpio_join {

struct HardwareBankSnapshot {
  std::uint32_t gdir = 0U;
  std::uint32_t psr = 0U;
  std::uint32_t dmamux_chcfg = 0U;
  std::uint32_t tcd_saddr = 0U;
  std::uint32_t tcd_daddr = 0U;
  std::uint16_t tcd_citer = 0U;
  std::uint16_t tcd_biter = 0U;
  std::uint16_t tcd_csr = 0U;
  std::uint8_t edma_priority = 0U;
  std::uint8_t current_destination = kInvalidDestination;
  std::uint8_t queued_destination = kInvalidDestination;
  std::uint32_t current_generation = 0U;
  std::uint32_t last_incomplete_samples = 0U;
};

struct HardwareSnapshot {
  Snapshot ring{};
  std::array<HardwareBankSnapshot, kBankCount> banks{};
  std::array<std::uint32_t, 16U> mux{};
  std::array<std::uint32_t, 16U> pad{};
  std::uint32_t gpr26 = 0U;
  std::uint32_t gpr27 = 0U;
  std::uint32_t pit_ldval = 0U;
  std::uint32_t pit_tctrl = 0U;
  std::uint16_t xbar_select = 0U;
  std::uint16_t xbar_control = 0U;
  std::uint32_t dma_erq = 0U;
  std::uint32_t dma_err = 0U;
  protocol_v2::RateProfile profile =
      protocol_v2::kDefaultRateProfile;
  bool pins_verified = false;
  bool route_verified = false;
  bool hardware_running = false;
};

class TeensyDualBankCapture final : public HardwareCapture {
 public:
  StartStatus inspectStart(std::uint32_t epoch,
                           protocol_v2::RateProfile profile) override;
  StartStatus prepare(std::uint32_t epoch,
                      protocol_v2::RateProfile profile) override;
  StartStatus start(std::uint32_t epoch,
                    protocol_v2::RateProfile profile) override;
  StopReport stopAfterTriggers(
      StopReason reason = StopReason::kStop) override;
  StopReport stop(StopReason reason = StopReason::kStop) override;
  std::size_t serviceOwnership() override;
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;
  Snapshot rawSnapshot() override;
  HardwareSnapshot snapshot();
};

TeensyDualBankCapture &teensyDualBankCapture();

}  // namespace thingdaq::gpio_join
