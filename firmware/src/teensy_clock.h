#pragma once

#include <cstdint>

#include "synthetic_source.h"

namespace thingdaq::clock {

// Thin hardware boundary for cooperative synthetic pacing. micros() is read
// only from main-loop context; unsigned deltas extend its 32-bit wrap into a
// 64-bit 8 MHz clock without installing an interrupt.
class TeensyTickClock final : public synthetic::TickClock {
 public:
  std::uint64_t nowTicks() override;

 private:
  std::uint64_t elapsed_microseconds_ = 0U;
  std::uint32_t previous_microseconds_ = 0U;
  bool initialized_ = false;
};

}  // namespace thingdaq::clock
