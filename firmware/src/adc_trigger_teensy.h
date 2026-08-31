#pragma once

#include "adc_trigger.h"

namespace thingdaq::adc_trigger {

// Singleton scheduler backed by PIT0/PIT1, XBARA1, ADC_ETC queues 0/4, and
// the calibrated ADC1/ADC2 modules on Teensy 4.0.
Scheduler &teensyScheduler();

}  // namespace thingdaq::adc_trigger
