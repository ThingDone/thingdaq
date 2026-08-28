#pragma once

#include <cstddef>
#include <cstdint>

namespace teensy_daq::dma {

// Shared cache and interrupt-serialization boundaries for DMA receive rings.
// Target adapters provide the implementation; portable ownership cores never
// include Teensy headers or perform cache maintenance from a completion ISR.
class CacheMaintenance {
 public:
  virtual ~CacheMaintenance() = default;

  // DMA receive ownership discards CPU cache lines without writing stale data
  // back. CPU ownership invalidates again after every contributing channel has
  // completed its major loop.
  virtual void discardBeforeDmaWrite(void *address, std::size_t bytes) = 0;
  virtual void invalidateBeforeCpuRead(void *address,
                                       std::size_t bytes) = 0;
};

class CriticalSection {
 public:
  virtual ~CriticalSection() = default;
  virtual std::uint32_t enter() = 0;
  virtual void exit(std::uint32_t token) = 0;
};

}  // namespace teensy_daq::dma
