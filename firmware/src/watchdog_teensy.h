#pragma once

#include <cstdint>

namespace thingdaq::watchdog {

// Initialize once before the runtime boots. Returns false if the peripheral
// refuses its bounded unlock/configuration handshake.
bool begin();
// Feed only after a complete cooperative main-loop iteration, never from an
// interrupt, diagnostic wait, or transport retry.
void refresh();
bool enabled();
std::uint32_t resetCause();
// Nominal timeout: the 32.768 kHz crystal can fall back to the on-chip RC clock.
std::uint32_t timeoutMs();

}  // namespace thingdaq::watchdog
