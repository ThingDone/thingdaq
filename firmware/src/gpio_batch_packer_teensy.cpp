#include "input_experiment_profile.h"

#include "gpio_batch_packer_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <core_pins.h>
#include <imxrt.h>

namespace thingdaq::gpio_packer {

PackedBufferStorage g_gpio_packed_buffers
    __attribute__((section(".dmabuffers"), used));

namespace {

class TeensyCycleCounter final : public CycleCounter {
 public:
  bool begin() override {
    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    const std::uint32_t before = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    return F_CPU_ACTUAL == input_experiment::kCpuHz &&
           ARM_DWT_CYCCNT != before;
  }

  std::uint32_t read() override { return ARM_DWT_CYCCNT; }
};

__attribute__((noinline, noipa, used)) void *retainPackedAllocation() {
  __asm__ volatile("" : : "r"(&g_gpio_packed_buffers) : "memory");
  return &g_gpio_packed_buffers;
}

void *volatile g_packed_allocation_link_anchor = retainPackedAllocation();
TeensyCycleCounter g_cycle_counter{};

}  // namespace

PackedBufferStorage &teensyPackedBufferStorage() {
  return g_gpio_packed_buffers;
}

CycleCounter &teensyCycleCounter() { return g_cycle_counter; }

static_assert(sizeof(g_gpio_packed_buffers) ==
              board::kGpioPackedRingDepth *
                  board::kGpioPackedBufferStrideBytes);
static_assert(alignof(PackedBufferStorage) == board::kCacheLineBytes);
static_assert(F_CPU == input_experiment::kCpuHz,
              "GPIO processing profiling requires the pinned 600 MHz target");

}  // namespace thingdaq::gpio_packer

#endif
