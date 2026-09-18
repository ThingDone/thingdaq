#include "gpio_pack_c.h"

/* Opt-in only: the release linker sees no additional kernel. The same source
 * can be compiled as C++ by the experiment to isolate language from algorithm. */
#if defined(THINGDAQ_EXPERIMENT_C_PACKER)
#if defined(__IMXRT1062__)
#if defined(THINGDAQ_EXPERIMENT_PACKER_ITCM)
#define PACK_CODE __attribute__((section(".fastrun"), noinline, noipa))
#else
#define PACK_CODE __attribute__((section(".flashmem.gpio_pack_c"), noinline, noipa))
#endif
#else
#define PACK_CODE __attribute__((noinline))
#endif

PACK_CODE
size_t thingdaq_pack_dual_c(const uint32_t *primary, const uint32_t *auxiliary,
                          size_t count, uint8_t *destination, size_t capacity) {
  if ((count != 0U && (primary == NULL || auxiliary == NULL ||
                      destination == NULL)) || count > capacity / 2U) {
    return 0U;
  }
  for (size_t index = 0U; index < count; ++index) {
    const uint32_t low = primary[index];
    const uint32_t high = auxiliary[index];
    destination[2U * index] = (uint8_t)(
        ((low >> 10U) & 0x01U) | ((low >> 16U) & 0x02U) |
        ((low >> 14U) & 0x04U) | ((low >> 8U) & 0x08U) |
        ((low << 4U) & 0x10U) | ((low << 3U) & 0x20U) |
        ((low << 5U) & 0x40U) | ((low << 4U) & 0x80U));
    destination[2U * index + 1U] = (uint8_t)(
        ((high >> 23U) & 0x01U) | ((high >> 21U) & 0x02U) |
        ((high >> 15U) & 0x04U) | ((high >> 13U) & 0x08U) |
        ((high >> 22U) & 0x10U) | ((high >> 22U) & 0x20U) |
        ((high >> 18U) & 0x40U) | ((high >> 18U) & 0x80U));
  }
  return count;
}
#undef PACK_CODE
#endif
