#pragma once

#include <cstddef>
#include <cstdint>

namespace thingdaq::health {

inline constexpr std::uint32_t kStackAvailable = 1U;
inline constexpr std::uint32_t kWatchdogEnabled = 2U;
inline constexpr std::uint32_t kStackCanary = 0xA55A3CC3U;

struct Reading {
  std::uint32_t flags = 0;
  std::uint32_t stack_total_bytes = 0;
  std::uint32_t stack_min_free_bytes = 0;
  std::uint32_t stack_max_used_bytes = 0;
  std::uint32_t reset_cause = 0;
  std::uint32_t watchdog_timeout_ms = 0;
};
using Reader = Reading (*)();

// Scan only the previously untouched prefix: history can never improve, even
// if a later stack write happens to recreate the canary. No reset/repaint API.
inline std::size_t untouchedWords(const volatile std::uint32_t *bottom,
                                  std::size_t previous_free_words) {
  std::size_t free_words = 0;
  while (free_words < previous_free_words &&
         bottom[free_words] == kStackCanary) {
    ++free_words;
  }
  return free_words;
}

Reading readTeensy();

}  // namespace thingdaq::health
