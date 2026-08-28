#include "gpio_batch_packer_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

namespace teensy_daq::gpio_packer {

PackedBufferStorage g_gpio_packed_buffers
    __attribute__((section(".dmabuffers"), used));

namespace {

__attribute__((noinline, noipa, used)) void *retainPackedAllocation() {
  __asm__ volatile("" : : "r"(&g_gpio_packed_buffers) : "memory");
  return &g_gpio_packed_buffers;
}

void *volatile g_packed_allocation_link_anchor = retainPackedAllocation();

}  // namespace

PackedBufferStorage &teensyPackedBufferStorage() {
  return g_gpio_packed_buffers;
}

static_assert(sizeof(g_gpio_packed_buffers) ==
              board::kGpioPackedRingDepth *
                  board::kGpioPackedBufferStrideBytes);
static_assert(alignof(PackedBufferStorage) == board::kCacheLineBytes);

}  // namespace teensy_daq::gpio_packer

#endif
