#pragma once

#include <array>
#include <cstddef>

#include "generated/protocol_v2_constants.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_RATE_PROFILE_STORAGE \
  __attribute__((section(".progmem.thingdaq.rate_profiles"), used))
#else
#define THINGDAQ_RATE_PROFILE_STORAGE
#endif

namespace thingdaq::rate_profile {

inline constexpr std::size_t kCount = 4U;

// The generated table is the sole value source. This constexpr projection is
// placed in memory-mapped Flash on Teensy so opting into portable v2
// validation does not consume a second 1 KiB-aligned DTCM data block.
inline constexpr std::array<protocol_v2::RateProfileTiming, kCount> kTimings
    THINGDAQ_RATE_PROFILE_STORAGE{{
        protocol_v2::kRateProfiles[0],
        protocol_v2::kRateProfiles[1],
        protocol_v2::kRateProfiles[2],
        protocol_v2::kRateProfiles[3],
    }};

constexpr const protocol_v2::RateProfileTiming *timingFor(
    protocol_v2::RateProfile profile) {
  for (const protocol_v2::RateProfileTiming &timing : kTimings) {
    if (timing.profile == profile) {
      return &timing;
    }
  }
  return nullptr;
}

static_assert(sizeof(protocol_v2::kRateProfiles) /
                      sizeof(protocol_v2::kRateProfiles[0]) ==
                  kCount);
static_assert(kTimings[0].profile ==
              protocol_v2::RateProfile::kAdc1mhzGpio4mhz);
static_assert(kTimings[kCount - 1U].profile ==
              protocol_v2::RateProfile::kAdc125khzGpio500khz);

}  // namespace thingdaq::rate_profile

#undef THINGDAQ_RATE_PROFILE_STORAGE
