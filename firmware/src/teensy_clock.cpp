#include "teensy_clock.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <Arduino.h>

#include "firmware_identity.h"

namespace thingdaq::clock {

__attribute__((section(".flashmem.identity.runtime_clock"), noinline, noipa,
               used)) bool runtimeProfileClocksValid() {
  return identity::runtimeClocksMatchProfile(F_CPU_ACTUAL, F_BUS_ACTUAL);
}

std::uint64_t TeensyTickClock::nowTicks() {
  const std::uint32_t current = static_cast<std::uint32_t>(micros());
  if (!initialized_) {
    previous_microseconds_ = current;
    initialized_ = true;
    return 0U;
  }
  const std::uint32_t elapsed = current - previous_microseconds_;
  previous_microseconds_ = current;
  elapsed_microseconds_ += elapsed;
  return elapsed_microseconds_ * 8U;
}

}  // namespace thingdaq::clock
#endif
