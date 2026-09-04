#include "checksum_benchmark_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <core_pins.h>
#include <imxrt.h>

#include "packet_buffer_pipeline.h"

// Packet page zero is the target benchmark's DTCM view. Keep a sized linker
// alias for build-manifest validation, but pass an ordinary byte view to C++ so
// no second object lifetime is implied at this address.
extern "C" {
thingdaq::packet::PacketBufferPrimaryStorage
    thingdaq_packet_storage_primary{};
}
asm(".global _ZN8thingdaq9benchmark32g_checksum_benchmark_dtcm_bufferE\n"
    ".set _ZN8thingdaq9benchmark32g_checksum_benchmark_dtcm_bufferE, "
    "thingdaq_packet_storage_primary\n"
    ".size _ZN8thingdaq9benchmark32g_checksum_benchmark_dtcm_bufferE, "
    "4096");

namespace thingdaq::benchmark {

Buffer g_checksum_benchmark_ocram_buffer
    __attribute__((section(".dmabuffers"), used));

namespace {

class TeensyPlatform final : public Platform {
 public:
  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    if (F_CPU_ACTUAL != protocol_v1::kChecksumBenchmarkCycleCounterHz) {
      frequency_hz = 0U;
      return false;
    }
    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    __asm__ volatile("dsb\n\tisb" : : : "memory");
    const std::uint32_t begin = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    const std::uint32_t end = ARM_DWT_CYCCNT;
    frequency_hz = F_CPU_ACTUAL;
    return end != begin;
  }

  std::uint32_t readCycles() override {
    __asm__ volatile("" : : : "memory");
    return ARM_DWT_CYCCNT;
  }

  std::uint32_t enterCritical() override {
    std::uint32_t token = 0U;
    __asm__ volatile("mrs %0, primask\n\tcpsid i"
                     : "=r"(token)
                     :
                     : "memory");
    __asm__ volatile("dsb\n\tisb" : : : "memory");
    return token;
  }

  void exitCritical(std::uint32_t token) override {
    __asm__ volatile("dsb\n\tisb" : : : "memory");
    __asm__ volatile("msr primask, %0" : : "r"(token) : "memory");
  }

  void flushDelete(void *address, std::size_t size) override {
    arm_dcache_flush_delete(address, static_cast<std::uint32_t>(size));
  }

  void invalidate(void *address, std::size_t size) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(size));
  }
};

TeensyPlatform g_platform{};
Runner g_runner{
    g_platform,
    BufferView{thingdaq_packet_storage_primary.frames[0].data(),
               thingdaq_packet_storage_primary.frames[0].size()},
    bufferView(g_checksum_benchmark_ocram_buffer)};

}  // namespace

Runner &teensyRunner() { return g_runner; }

packet::PacketBufferPrimaryStorage &teensyPacketPrimaryStorage() {
  return thingdaq_packet_storage_primary;
}

Buffer &teensyOcramBuffer() { return g_checksum_benchmark_ocram_buffer; }

static_assert(F_CPU == protocol_v1::kChecksumBenchmarkCycleCounterHz,
              "checksum benchmark requires the pinned 600 MHz target");
static_assert(sizeof(packet::PacketFrame) == sizeof(Buffer));

}  // namespace thingdaq::benchmark

#endif
