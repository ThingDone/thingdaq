#include "runtime_health.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <Arduino.h>
#include "interrupt_guard_teensy.h"
#include "watchdog_teensy.h"

extern "C" {
extern std::uint32_t _ebss;
extern std::uint32_t _estack;
}

namespace {
// POD state is initialized by the core before startup_late_hook. The hook runs
// before global constructors and setup, after memory/MPU/USB initialization.
std::uintptr_t stack_bottom;
std::uint32_t stack_total;
std::size_t free_words;
}

extern "C" FLASHMEM void startup_late_hook() {
  const thingdaq::interrupts::Guard guard{};
  std::uintptr_t sp;
  __asm__ volatile("mrs %0, msp" : "=r"(sp) : : "memory");
  // The pinned core installs a 32-byte NOACCESS MPU region AT _ebss.
  // Leave that region alone, plus 128 bytes below our current live frame.
  stack_bottom = reinterpret_cast<std::uintptr_t>(&_ebss) + 32U;
  const auto top = reinterpret_cast<std::uintptr_t>(&_estack);
  if (sp < stack_bottom + 128U || sp > top) return;
  stack_total = static_cast<std::uint32_t>(top - stack_bottom);
  free_words = (sp - 128U - stack_bottom) / sizeof(std::uint32_t);
  auto *const bottom = reinterpret_cast<volatile std::uint32_t *>(stack_bottom);
  for (std::size_t i = 0; i < free_words; ++i) {
    bottom[i] = thingdaq::health::kStackCanary;
  }
}

namespace thingdaq::health {
FLASHMEM Reading readTeensy() {
  Reading reading{};
  if (stack_total != 0U) {
    // Interrupts stay enabled during this bounded read-only scan. An interrupt
    // after a word is scanned is reflected on the next query, as with any
    // sampled diagnostic. Never call this from an ISR or repaint while running.
    free_words = untouchedWords(
        reinterpret_cast<const volatile std::uint32_t *>(stack_bottom), free_words);
    reading.flags = kStackAvailable;
    reading.stack_total_bytes = stack_total;
    reading.stack_min_free_bytes = static_cast<std::uint32_t>(free_words * 4U);
    reading.stack_max_used_bytes = stack_total - reading.stack_min_free_bytes;
  }
  if (watchdog::enabled()) {
    reading.flags |= kWatchdogEnabled;
    reading.watchdog_timeout_ms = watchdog::timeoutMs();
  }
  reading.reset_cause = watchdog::resetCause();
  return reading;
}
}  // namespace thingdaq::health
#endif
