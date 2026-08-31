#pragma once

#include "gpio_clock_diagnostic.h"

namespace thingdaq::gpio_clock {

// Singleton runner backed by the fixed PIT0/XBARA1 request 0/eDMA channel 2
// route and one link-verified, cache-line-isolated OCRAM diagnostic word pair.
Runner &teensyRunner();

}  // namespace thingdaq::gpio_clock
