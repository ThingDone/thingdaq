#include <cassert>
#include "edma_priority_teensy.h"

int main() {
  // Reconfigure both ways to catch a stale experiment-only ECP setting.
  for (bool auxiliary : {false, true, false, true}) {
    thingdaq::edma_priority::configureReservedChannels(auxiliary);
    const unsigned adc0 = auxiliary ? 3U : 2U;
    const unsigned adc1 = auxiliary ? 2U : 1U;
    const unsigned gpio0 = auxiliary ? 1U : 0U;
    const unsigned gpio1 = auxiliary ? 0U : 3U;
    assert(DMA_DCHPRI0 == (0x80U | adc0));
    assert(DMA_DCHPRI1 == (0x80U | adc1));
    assert(DMA_DCHPRI2 == (0x80U | gpio0));
    assert(DMA_DCHPRI3 == (0x80U | gpio1));
  }
}
