#pragma once

#include "variable_rate_scheduler.h"

namespace thingdaq::variable_rate {

// Transactional target adapter for the stopped PIT0/PIT1, ADC_ETC, XBARA1,
// and ADC hardware-trigger schedule. The adapter never enables a trigger;
// acquisition owners prepare DMA first and enable the common clock last.
Scheduler &teensyRateScheduler();
const Schedule &teensySelectedSchedule();

}  // namespace thingdaq::variable_rate
