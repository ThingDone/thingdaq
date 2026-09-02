#pragma once

#include <cstdint>

namespace thingdaq::timing {

// Optional wrapping cycle source shared by bounded cooperative profilers.
class CycleCounter {
 public:
  virtual ~CycleCounter() = default;
  virtual bool begin() = 0;
  virtual std::uint32_t read() = 0;
};

}  // namespace thingdaq::timing
