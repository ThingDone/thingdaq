#pragma once

#include <cstdint>

// Closed, build-time research variants, not additions to the public v2 contract.
// The experiment builder salts firmware identity with both selections.
#ifndef THINGDAQ_EXPERIMENT_CPU_HZ
#define THINGDAQ_EXPERIMENT_CPU_HZ 600000000U
#endif
#ifndef THINGDAQ_EXPERIMENT_EQUAL_RATES
#define THINGDAQ_EXPERIMENT_EQUAL_RATES 0
#endif
#if THINGDAQ_EXPERIMENT_CPU_HZ != 600000000U && THINGDAQ_EXPERIMENT_CPU_HZ != 450000000U
#error "input experiment supports only the reviewed 600/150 and 450/150 MHz clocks"
#endif
#if THINGDAQ_EXPERIMENT_EQUAL_RATES != 0 && THINGDAQ_EXPERIMENT_EQUAL_RATES != 1
#error "invalid equal-rate experiment selection"
#endif

namespace thingdaq::input_experiment {
inline constexpr std::uint32_t kCpuHz = THINGDAQ_EXPERIMENT_CPU_HZ;
inline constexpr bool kEqualRates = THINGDAQ_EXPERIMENT_EQUAL_RATES != 0;
inline constexpr std::uint32_t kGpioRateMultiplier = kEqualRates ? 1U : 4U;
constexpr std::uint32_t scaleDwt(std::uint32_t cycles_at_600mhz) {
  return static_cast<std::uint32_t>(
      static_cast<std::uint64_t>(cycles_at_600mhz) * kCpuHz / 600000000U);
}
}  // namespace thingdaq::input_experiment
