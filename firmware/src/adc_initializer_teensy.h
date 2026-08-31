#pragma once

#include "adc_initializer.h"

namespace thingdaq::adc {

// Singleton initializer backed by the fixed Teensy 4.0 ADC1/ADC2 registers.
// The sketch invokes it exactly once at the bounded BOOT-to-IDLE boundary.
Initializer &teensyInitializer();

}  // namespace thingdaq::adc
