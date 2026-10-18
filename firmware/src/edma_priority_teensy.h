#pragma once

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <cstdint>
#include "board_config.h"

namespace thingdaq::edma_priority {

#if defined(THINGDAQ_EXPERIMENT_GPIO_PREEMPT_PROBE)
// Same-binary A/B diagnosis only: odd acquisition epochs reserve the preempt
// slot for ADC channels, even epochs retain the existing GPIO policy. eDMA
// cannot preempt a preempting channel (RT1060 RM 6.3.4).
inline bool g_protect_adc_preempt_slot = false;
inline void selectCaptureEpoch(std::uint32_t epoch) {
  g_protect_adc_preempt_slot = (epoch & 1U) != 0U;
}
#else
inline void selectCaptureEpoch(std::uint32_t) {}
#endif

// All priorities in an eDMA arbitration group must be unique, even for
// disabled channels. Reuse the output experiment's complete-reservation
// approach, with the two input-mode permutations. Owners call this only
// during stopped setup, before enabling any acquisition requests.
__attribute__((section(".flashmem.edma.priorities"), noinline, noipa))
inline void configureReservedChannels(bool auxiliary) {
  std::uint8_t gpio_control = DMA_DCHPRI_ECP;
#if defined(THINGDAQ_EXPERIMENT_GPIO_PREEMPT_PROBE)
  if (auxiliary && g_protect_adc_preempt_slot)
    gpio_control |= DMA_DCHPRI_DPA;
#endif
  DMA_DCHPRI0 = static_cast<std::uint8_t>(DMA_DCHPRI_ECP | DMA_DCHPRI_CHPRI(
      auxiliary ? board::kInputModeEdmaPriorities[0] : board::kAdcEdmaPriorities[0]));
  DMA_DCHPRI1 = static_cast<std::uint8_t>(DMA_DCHPRI_ECP | DMA_DCHPRI_CHPRI(
      auxiliary ? board::kInputModeEdmaPriorities[1] : board::kAdcEdmaPriorities[1]));
  DMA_DCHPRI2 = static_cast<std::uint8_t>(gpio_control | DMA_DCHPRI_CHPRI(
      auxiliary ? board::kPrimaryGpioInputEdmaPriority : board::kGpioEdmaPriority));
  DMA_DCHPRI3 = static_cast<std::uint8_t>(gpio_control | DMA_DCHPRI_CHPRI(
      auxiliary ? board::kAuxGpioEdmaPriority : 3U));
}

}  // namespace thingdaq::edma_priority
#endif
