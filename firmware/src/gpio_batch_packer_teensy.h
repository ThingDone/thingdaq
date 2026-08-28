#pragma once

#include "gpio_batch_packer.h"

namespace teensy_daq::gpio_packer {

// Fixed OCRAM allocation used by the physical GPIO owner once control-plane
// integration arms the packer. The storage is CPU-owned and remains cached;
// it is separated from both DMA raw buffers and packet/USB ownership.
PackedBufferStorage &teensyPackedBufferStorage();

}  // namespace teensy_daq::gpio_packer
