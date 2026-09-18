#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Experimental C ABI for the existing dual-bank wire mapping. CPU-owned,
 * non-overlapping input/output buffers only; no DMA ownership is transferred. */
size_t thingdaq_pack_dual_c(const uint32_t *primary, const uint32_t *auxiliary,
                          size_t count, uint8_t *destination, size_t capacity);

#ifdef __cplusplus
}
#endif
