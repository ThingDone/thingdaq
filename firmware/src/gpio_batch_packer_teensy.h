#pragma once

#include "gpio_batch_packer.h"

namespace thingdaq::gpio_packer {

// Fixed OCRAM allocation used by the integrated physical GPIO owner. The
// storage is CPU-owned and remains cached;
// it is separated from both DMA raw buffers and packet/USB ownership.
PackedBufferStorage &teensyPackedBufferStorage();
CycleCounter &teensyCycleCounter();

}  // namespace thingdaq::gpio_packer
