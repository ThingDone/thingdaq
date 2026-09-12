#pragma once

#include <cstdint>

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <core_pins.h>

namespace thingdaq::interrupts {

// Also used by the portable DMA rings' token-based CriticalSection adapter.
// The compiler barriers cover ordinary shared records, not only volatile flags.
inline std::uint32_t saveAndDisable() {
#if defined(THINGDAQ_HOST_REGISTER_TEST)
  const std::uint32_t previous = fake_imxrt::interrupts_enabled ? 0U : 1U;
  __disable_irq();
  __asm__ volatile("" : : : "memory");
#else
  std::uint32_t previous;
  __asm__ volatile("mrs %0, primask\n\tcpsid i"
                   : "=r"(previous) : : "memory");
#endif
  return previous;
}

inline void restore(std::uint32_t previous) {
#if defined(THINGDAQ_HOST_REGISTER_TEST)
  __asm__ volatile("" : : : "memory");
  if ((previous & 1U) == 0U) {
    __enable_irq();
  } else {
    __disable_irq();
  }
#else
  __asm__ volatile("msr primask, %0" : : "r"(previous) : "memory");
#endif
}

// Single-core main/ISR serialization. Nested guards preserve an already masked
// caller; NMI/HardFault handlers must not access the protected records.
class Guard final {
 public:
  explicit Guard(bool enabled = true)
      : previous_(enabled ? saveAndDisable() : 0U), active_(enabled) {}
  ~Guard() { release(); }
  Guard(const Guard &) = delete;
  Guard &operator=(const Guard &) = delete;
  Guard(Guard &&) = delete;
  Guard &operator=(Guard &&) = delete;

  // End a hardware window before cache maintenance or cooperative processing.
  void release() {
    if (active_) {
      active_ = false;
      restore(previous_);
    }
  }

 private:
  const std::uint32_t previous_;
  bool active_;
};

}  // namespace thingdaq::interrupts

#endif
