#pragma once

#include "checksum_benchmark.h"

namespace teensy_daq::benchmark {

// Singleton runner whose backing buffers are link-placed in real DTCM and
// DMA-visible OCRAM. The pinned-build inspector verifies both symbols.
Runner &teensyRunner();

}  // namespace teensy_daq::benchmark
