#include "teensy_clock.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <Arduino.h>

namespace teensy_daq::clock {

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

}  // namespace teensy_daq::clock
#endif
