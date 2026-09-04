#pragma once

#include "checksum_benchmark.h"

namespace thingdaq::packet {
struct PacketBufferPrimaryStorage;
}

namespace thingdaq::benchmark {

// The target aliases this IDLE-only view onto the first packet page. The
// runtime admits a benchmark only after the packet/acquisition path is fully
// quiescent, so the public 200-page packet capacity is unchanged.
packet::PacketBufferPrimaryStorage &teensyPacketPrimaryStorage();

// Singleton runner whose backing buffers are link-placed in real DTCM and
// DMA-visible OCRAM. The pinned-build inspector verifies both symbols.
Runner &teensyRunner();
// INPUT capture leases the beginning of this IDLE-only aligned workspace.
// The runtime already excludes checksum benchmarks while acquisition runs.
Buffer &teensyOcramBuffer();

}  // namespace thingdaq::benchmark
