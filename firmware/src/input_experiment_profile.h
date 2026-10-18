#pragma once

#if defined(THINGDAQ_EXPERIMENT_GPIO_PREEMPT_PROBE) && \
    !defined(THINGDAQ_EXPERIMENT_GPIO_RLE)
#error "The GPIO preemption probe requires the private GPIO RLE experiment"
#endif

#include <cstdint>

// Closed, build-time research variants, not additions to the public v2 contract.
// The experiment builder salts firmware identity with both selections.
#ifndef THINGDAQ_RELEASE_FIXED_1MHZ
#define THINGDAQ_RELEASE_FIXED_1MHZ 0
#endif
#ifndef THINGDAQ_EXPERIMENT_CPU_HZ
#if THINGDAQ_RELEASE_FIXED_1MHZ
#define THINGDAQ_EXPERIMENT_CPU_HZ 450000000U
#else
#define THINGDAQ_EXPERIMENT_CPU_HZ 600000000U
#endif
#endif
#ifndef THINGDAQ_EXPERIMENT_EQUAL_RATES
#define THINGDAQ_EXPERIMENT_EQUAL_RATES 0
#endif
#if THINGDAQ_EXPERIMENT_CPU_HZ != 600000000U && \
    THINGDAQ_EXPERIMENT_CPU_HZ != 450000000U && \
    THINGDAQ_EXPERIMENT_CPU_HZ != 528000000U
#error "input experiment supports only 600/150, 450/150 and 528/132 MHz clocks"
#endif
#if THINGDAQ_EXPERIMENT_EQUAL_RATES != 0 && THINGDAQ_EXPERIMENT_EQUAL_RATES != 1
#error "invalid equal-rate experiment selection"
#endif

namespace thingdaq::input_experiment {
#if defined(THINGDAQ_EXPERIMENT_GPIO_RLE)
inline constexpr bool kGpioRle = true;
static_assert(THINGDAQ_RELEASE_FIXED_1MHZ && THINGDAQ_EXPERIMENT_CPU_HZ == 600000000U,
              "GPIO RLE requires the qualified 600 MHz fixed-rate baseline");
#if !defined(THINGDAQ_EXPERIMENT_LARGE_ADC_FRAME)
#error "GPIO RLE requires the qualified larger ADC layout"
#endif
#else
inline constexpr bool kGpioRle = false;
#endif
// Private GPIO-RLE16 wire version; ordinary v2 decoders reject it. RAW fallback
// and all ADC/control frames retain v2. No reserved header byte is repurposed.
inline constexpr std::uint8_t kGpioRleVersion = 0x82U;

#if defined(THINGDAQ_EXPERIMENT_LARGE_ADC_FRAME)
inline constexpr std::uint32_t kAdcFrameMultiplier = 2U;
#else
inline constexpr std::uint32_t kAdcFrameMultiplier = 1U;
#endif
inline constexpr bool kReleaseFixed1MHz = THINGDAQ_RELEASE_FIXED_1MHZ != 0;
inline constexpr std::uint32_t kCpuHz = THINGDAQ_EXPERIMENT_CPU_HZ;
static_assert(!kReleaseFixed1MHz || kCpuHz == 450000000U ||
                  kCpuHz == 528000000U || kCpuHz == 600000000U,
              "unsupported fixed-rate core clock");
inline constexpr std::uint32_t kIpgHz = kCpuHz == 528000000U ? 132000000U : 150000000U;
inline constexpr std::uint32_t kAdcHz = kIpgHz / 4U;
constexpr std::uint16_t scaleIpg(std::uint16_t cycles_at_150mhz) {
  return static_cast<std::uint16_t>(
      static_cast<std::uint64_t>(cycles_at_150mhz) * kIpgHz / 150000000U);
}
inline constexpr bool kEqualRates = THINGDAQ_EXPERIMENT_EQUAL_RATES != 0;
inline constexpr std::uint32_t kGpioRateMultiplier = kEqualRates ? 1U : 4U;
constexpr std::uint32_t scaleDwt(std::uint32_t cycles_at_600mhz) {
  return static_cast<std::uint32_t>(
      static_cast<std::uint64_t>(cycles_at_600mhz) * kCpuHz / 600000000U);
}
}  // namespace thingdaq::input_experiment
