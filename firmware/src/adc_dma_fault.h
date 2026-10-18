#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace thingdaq::adc_capture::fault_trace {
// Private GPIO-RLE STATUS suffix; never part of the public protocol.
#if defined(THINGDAQ_EXPERIMENT_GPIO_RLE)
inline constexpr std::size_t kWords = 3;
inline volatile std::uint32_t words[kWords]{};
// Opt-in requests 0xFADC0001..0018 read two immutable diagnostic words.
// Normal STATUS retains its original 12-byte summary and frame-size limit.
inline constexpr std::size_t kDetailWords = 48;
inline constexpr std::uint32_t kDetailRequestBase = 0xFADC0000U;
inline volatile std::uint32_t detail[kDetailWords]{};
// Two most recent accepted progress observations, oldest first. Each holds
// software base generation, packed indices, end DWT cycles, pending DMA IRQs,
// packed 16-bit CITER values (ADC0 low), and observation-start DWT cycles.
// Sequential reads are NOT an atomic hardware snapshot. The timestamps bound
// their sampling interval, so phase comparisons can account for read latency.
// Only the serialized DMA service writes this; prepare resets it while stopped.
inline constexpr std::size_t kProgressWords = 6;
inline std::array<std::uint32_t, 2 * kProgressWords> progress_history{};
inline void rememberProgress(std::uint32_t generation, std::uint32_t indices,
                             std::uint32_t cycles, std::uint32_t pending,
                             std::uint32_t remaining, std::uint32_t started) {
  if (words[0] != 0U) return;
  for (std::size_t i = 0; i < kProgressWords; ++i)
    progress_history[i] = progress_history[i + kProgressWords];
  progress_history[6] = generation;
  progress_history[7] = indices;
  progress_history[8] = cycles;
  progress_history[9] = pending;
  progress_history[10] = remaining;
  progress_history[11] = started;
}
inline void retainProgress() {
  for (std::size_t i = 0; i < progress_history.size(); ++i)
    detail[36 + i] = progress_history[i];
}
inline void reset() {
  for (std::size_t i = 0; i < kWords; ++i) words[i] = 0;
  for (std::size_t i = 0; i < kDetailWords; ++i) detail[i] = 0;
  progress_history.fill(0U);
}
inline std::array<std::uint32_t, kWords> snapshot(std::uint32_t request_id = 0) {
  std::array<std::uint32_t, kWords> result{};
  // The ISR publishes reason last. Once nonzero, the record stays immutable
  // until the next stopped prepare. Main cannot race that prepare operation.
  if (words[0] != 0) {
    const std::uint32_t page = request_id - kDetailRequestBase;
    if (page >= 1U && page <= kDetailWords / 2U) {
      result[0] = (words[0] & 0x7FU) | 0x80U | (page << 8U);
      result[1] = detail[(page - 1U) * 2U];
      result[2] = detail[(page - 1U) * 2U + 1U];
    } else {
      for (std::size_t i = 0; i < kWords; ++i) result[i] = words[i];
    }
  }
  return result;
}
#else
inline constexpr std::size_t kWords = 0;
inline void reset() {}
inline std::array<std::uint32_t, 0> snapshot(std::uint32_t = 0) { return {}; }
#endif
inline constexpr std::size_t kBytes = kWords * sizeof(std::uint32_t);
}  // namespace thingdaq::adc_capture::fault_trace
