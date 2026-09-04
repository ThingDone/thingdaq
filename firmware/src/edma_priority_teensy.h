#pragma once

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstdint>

#include "board_config.h"

namespace thingdaq::edma_priority {

// The i.MX RT1062 requires every channel priority in a group to be unique,
// including channels whose requests are currently disabled. Configure the
// complete reserved acquisition group before any ADC, GPIO, or output request
// is enabled so no-output profiles cannot inherit a conflicting reset value.
inline void configureReservedChannels() {
  DMA_DCHPRI0 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kAdcEdmaPriorities[0]));
  DMA_DCHPRI1 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kAdcEdmaPriorities[1]));
  DMA_DCHPRI2 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kGpioEdmaPriority));
  DMA_DCHPRI3 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kAuxOutputEdmaPriority));
}

inline bool reservedChannelsConfigured() {
  return (DMA_DCHPRI0 & 0x0FU) == board::kAdcEdmaPriorities[0] &&
         (DMA_DCHPRI1 & 0x0FU) == board::kAdcEdmaPriorities[1] &&
         (DMA_DCHPRI2 & 0x0FU) == board::kGpioEdmaPriority &&
         (DMA_DCHPRI3 & 0x0FU) == board::kAuxOutputEdmaPriority;
}

}  // namespace thingdaq::edma_priority

#endif
