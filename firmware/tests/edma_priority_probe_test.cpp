// Exercise the real stopped-setup policy against register stand-ins.
#include <cassert>
#include <cstdint>
#include "board_config.h"
// Board constants use their host form; only the policy below is target gated.
#define ARDUINO_TEENSY40
#define __IMXRT1062__
volatile std::uint8_t DMA_DCHPRI0, DMA_DCHPRI1, DMA_DCHPRI2, DMA_DCHPRI3;
#define DMA_DCHPRI_ECP 0x80U
#define DMA_DCHPRI_DPA 0x40U
#define DMA_DCHPRI_CHPRI(n) (n)
#include "edma_priority_teensy.h"

int main() {
  using namespace thingdaq::edma_priority;
  for (std::uint32_t epoch : {1U, 2U, 3U, 4U, 0xFFFFFFFFU, 0U}) {
    selectCaptureEpoch(epoch);
    for (bool auxiliary : {true, false, true}) {
      // Both ADC and GPIO owners call the same function in stopped setup.
      configureReservedChannels(auxiliary);
      configureReservedChannels(auxiliary);
      std::uint8_t protect = 0;
#if defined(THINGDAQ_EXPERIMENT_GPIO_PREEMPT_PROBE)
      if (auxiliary && (epoch & 1U)) protect = DMA_DCHPRI_DPA;
#endif
      assert(DMA_DCHPRI0 == (DMA_DCHPRI_ECP | (auxiliary ? 3U : 2U)));
      assert(DMA_DCHPRI1 == (DMA_DCHPRI_ECP | (auxiliary ? 2U : 1U)));
      assert(DMA_DCHPRI2 == (DMA_DCHPRI_ECP | protect | (auxiliary ? 1U : 0U)));
      assert(DMA_DCHPRI3 == (DMA_DCHPRI_ECP | protect | (auxiliary ? 0U : 3U)));
    }
  }
}
