#pragma once

#include <cstdint>

#include "gpio_dual_bank_capture.h"
#include "gpio_raw_capture.h"

namespace thingdaq::gpio_capture {

// INPUT mode overlays the existing 64,768-byte legacy GPIO ring with two
// equal generation rings. Exactly one facade may own the active union member.
union alignas(board::kCacheLineBytes) SharedRawBufferStorage {
  RawBufferStorage legacy;
  gpio_join::PairedRawStorage paired;

  constexpr SharedRawBufferStorage() : legacy{} {}
  ~SharedRawBufferStorage() {}
};

enum class RawStorageOwner : std::uint8_t {
  kNone,
  kLegacy,
  kPaired,
};

extern SharedRawBufferStorage g_gpio_raw_dma_buffers;

bool rawStorageAvailable(RawStorageOwner owner);
bool rawStorageActive(RawStorageOwner owner);
bool claimRawStorage(RawStorageOwner owner);
void releaseRawStorage(RawStorageOwner owner);
RawBufferStorage &legacyRawStorage();
gpio_join::PairedRawStorage &pairedRawStorage();
void *primaryRawDescriptorStorage();

static_assert(sizeof(SharedRawBufferStorage) ==
              board::kGpioRawDmaRingBytes);
static_assert(alignof(SharedRawBufferStorage) ==
              board::kCacheLineBytes);

}  // namespace thingdaq::gpio_capture
