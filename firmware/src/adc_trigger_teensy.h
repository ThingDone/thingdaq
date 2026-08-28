#pragma once

#include "adc_trigger.h"

namespace teensy_daq::adc_trigger {

// Singleton scheduler backed by PIT0/PIT1, XBARA1, ADC_ETC queues 0/4, and
// the calibrated ADC1/ADC2 modules on Teensy 4.0.
Scheduler &teensyScheduler();

}  // namespace teensy_daq::adc_trigger
