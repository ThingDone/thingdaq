// Execute the production STOP boundary function with the RT1060 CSR coherency
// rule: a word-7 write while DONE is set clears ESG (RM section 5.5.7.3).
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string>
constexpr std::uint16_t DMA_TCD_CSR_DREQ = 8;
constexpr std::uint16_t DMA_TCD_CSR_ESG = 16;
constexpr std::uint16_t DMA_TCD_CSR_DONE = 128;
constexpr std::size_t kConverterCount = 2;
constexpr std::uint32_t kAdcDmaChannelMask = 3;
constexpr std::uint32_t kStopBoundaryTimeoutCycles = 1000;
constexpr std::uint32_t kStopBoundaryPollLimit = 1000;
constexpr std::uint32_t ARM_DEMCR_TRCENA = 1, ARM_DWT_CTRL_CYCCNTENA = 1;
std::uint32_t ARM_DEMCR = 0, ARM_DWT_CTRL = 0;
bool g_hardware_prepared = true, g_faulted = false;
std::uint16_t g_pairs_per_buffer = 1008;
std::array<unsigned, 2> g_current_generations{59559, 59559};
std::array<unsigned, 2> g_current_destinations{7, 7};
unsigned g_stop_errors = 0;
namespace board {
struct Converter { unsigned edma_channel; };
constexpr std::array<Converter, 2> kAdcConverterConfigurations{{{0}, {1}}};
}
namespace interrupts { struct Guard { Guard() {} ~Guard() {} }; }
void barrier() {}
void saturatingIncrement(unsigned &v) { ++v; }
unsigned csr_writes = 0;
struct Csr {
  std::uint16_t value = DMA_TCD_CSR_ESG | 2;
  operator std::uint16_t() const { return value; }
  void operator=(std::uint16_t next) {
    ++csr_writes;
    // Hardware checks the prior DONE, not just the value being written.
    if (value & DMA_TCD_CSR_DONE)
      next = static_cast<std::uint16_t>(next & ~DMA_TCD_CSR_ESG);
    value = next;
  }
};
struct IMXRT_DMA_TCD_t {
  std::uint16_t BITER_ELINKNO = 1008, CITER_ELINKNO = 1008;
  Csr CSR;
  std::uint32_t DADDR = 0x20266242, DLASTSGA = 0x2025f200;
};
std::array<IMXRT_DMA_TCD_t, 2> tcds{};
IMXRT_DMA_TCD_t &hardwareTcd(std::size_t converter) { return tcds[converter]; }
struct ClearDone {
  void operator=(unsigned channel) {
    tcds[channel].CSR.value &= static_cast<std::uint16_t>(~DMA_TCD_CSR_DONE);
  }
} DMA_CDNE;
struct Requests {
  unsigned bits = 3;
  operator unsigned() {
    // Let the next major loop finish after both DREQ writes. Model the exact
    // observed DADDR addition if software accidentally disabled scatter/gather.
    if (bits && (tcds[0].CSR.value & DMA_TCD_CSR_DREQ) &&
                (tcds[1].CSR.value & DMA_TCD_CSR_DREQ)) {
      for (auto &tcd : tcds) {
        tcd.DADDR += g_pairs_per_buffer * 4U;
        if (!(tcd.CSR.value & DMA_TCD_CSR_ESG)) tcd.DADDR += tcd.DLASTSGA;
        tcd.CSR.value |= DMA_TCD_CSR_DONE;
      }
      bits = 0;
    }
    return bits;
  }
} DMA_ERQ;
struct Clock {
  unsigned ticks = 0;
  operator unsigned() { return ticks++; }
} ARM_DWT_CYCCNT;
#include "adc_dma_stop_under_test.h"
int main(int argc, char **argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  const bool no_start = scenario == "unprepared" || scenario == "faulted";
  if (scenario == "unprepared") g_hardware_prepared = false;
  if (scenario == "faulted") g_faulted = true;
  if (scenario == "adc0-done" || scenario == "both-done")
    tcds[0].CSR.value |= DMA_TCD_CSR_DONE;
  if (scenario == "adc1-done" || scenario == "both-done")
    tcds[1].CSR.value |= DMA_TCD_CSR_DONE;
  if (scenario == "insufficient-headroom")
    for (auto &tcd : tcds) tcd.CITER_ELINKNO = 756;
  const bool expect_ok = !no_start && scenario != "insufficient-headroom";
  assert(waitForCompleteStopBoundary() == expect_ok);
  if (!expect_ok) { assert(csr_writes == 0); return 0; }
  for (const auto &tcd : tcds) {
    assert(tcd.CSR.value & DMA_TCD_CSR_ESG);
    assert(tcd.DADDR == 0x20267202); // Never add the descriptor pointer.
  }
  assert(g_stop_errors == 0 && csr_writes == 2);
}
