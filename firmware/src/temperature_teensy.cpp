#include "temperature.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <Arduino.h>

namespace thingdaq::temperature {

__attribute__((section(".flashmem.temperature.read"), noinline, noipa, used))
Reading readTeensy() {
  const std::uint32_t control = TEMPMON_TEMPSENSE0;
  return decode(control, HW_OCOTP_ANA1);
}

}  // namespace thingdaq::temperature
#endif
