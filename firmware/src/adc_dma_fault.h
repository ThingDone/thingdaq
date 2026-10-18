#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace thingdaq::adc_capture::fault_trace {
// Private GPIO-RLE STATUS suffix; never part of the public protocol.
#if defined(THINGDAQ_EXPERIMENT_GPIO_RLE)
inline constexpr std::size_t kWords = 3;
inline volatile std::uint32_t words[kWords]{};
inline void reset() {
  for (std::size_t i = 0; i < kWords; ++i) words[i] = 0;
}
inline std::array<std::uint32_t, kWords> snapshot() {
  std::array<std::uint32_t, kWords> result{};
  // The ISR publishes reason last. Once nonzero, the record stays immutable
  // until the next stopped prepare. Main cannot race that prepare operation.
  if (words[0] != 0) {
    for (std::size_t i = 0; i < kWords; ++i) result[i] = words[i];
  }
  return result;
}
#else
inline constexpr std::size_t kWords = 0;
inline void reset() {}
inline std::array<std::uint32_t, 0> snapshot() { return {}; }
#endif
inline constexpr std::size_t kBytes = kWords * sizeof(std::uint32_t);
}  // namespace thingdaq::adc_capture::fault_trace
