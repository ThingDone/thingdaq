#pragma once

#include <cstddef>
#include <cstdint>

#include "generated/protocol_v3_constants.h"

namespace thingdaq::board_profile {

// Typed views of the generated Flash tables, not a second clock/rate policy.
// Compile-time bounds are sufficient here; untrusted wire bytes still pass
// through protocol's length/reserved-field validators.
template <std::size_t Offset, std::size_t Width, std::size_t N>
constexpr std::uint32_t field(const std::uint8_t (&bytes)[N]) {
  static_assert(Width <= 4U && Offset + Width <= N);
  std::uint32_t value = 0U;
  for (std::size_t i = 0U; i < Width; ++i)
    value |= static_cast<std::uint32_t>(bytes[Offset + i]) << (8U * i);
  return value;
}

struct Cpu {
  protocol_v3::CpuProfile id{};
  std::uint32_t cpu_hz = 0U;
  std::uint32_t ipg_hz = 0U;
  std::uint32_t adc_hz = 0U;
  std::uint32_t pit_hz = 0U;
  std::uint32_t timestamp_hz = 0U;

  constexpr bool valid() const { return cpu_hz != 0U; }
};

constexpr Cpu cpuFor(protocol_v3::CpuProfile id) {
  using namespace protocol_v3;
  for (const auto& bytes : kCpuProfiles) {
    if (bytes[kCpuProfileInfoCpuProfileOffset] == static_cast<std::uint8_t>(id)) {
      return {id, field<kCpuProfileInfoCpuClockHzOffset, 4U>(bytes),
              field<kCpuProfileInfoIpgClockHzOffset, 4U>(bytes),
              field<kCpuProfileInfoAdcClockHzOffset, 4U>(bytes),
              field<kCpuProfileInfoPitClockHzOffset, 4U>(bytes),
              field<kCpuProfileInfoTimestampHzOffset, 4U>(bytes)};
    }
  }
  return {};
}

constexpr std::uint8_t cpuIdForHz(std::uint32_t hz) {
  for (const auto& bytes : protocol_v3::kCpuProfiles) {
    const auto id = static_cast<protocol_v3::CpuProfile>(bytes[0]);
    if (cpuFor(id).cpu_hz == hz) return bytes[0];
  }
  return 0U;
}

struct Rate {
  protocol_v3::RateProfile id{};
  std::uint32_t adc_pair_hz = 0U;
  std::uint32_t gpio_hz = 0U;
  std::uint16_t adc_period_ticks = 0U;
  std::uint16_t gpio_period_ticks = 0U;
  std::uint16_t adc1_phase_ticks = 0U;

  constexpr bool valid() const { return adc_pair_hz != 0U; }
};

constexpr Rate rateFor(protocol_v3::RateProfile id) {
  using namespace protocol_v3;
  for (const auto& bytes : kRateProfiles) {
    if (bytes[kRateProfileInfoRateProfileOffset] == static_cast<std::uint8_t>(id)) {
      return {id, field<kRateProfileInfoAdcPairRateHzOffset, 4U>(bytes),
              field<kRateProfileInfoGpioSampleRateHzOffset, 4U>(bytes),
              static_cast<std::uint16_t>(field<kRateProfileInfoAdcPairPeriodTicksOffset, 2U>(bytes)),
              static_cast<std::uint16_t>(field<kRateProfileInfoGpioSamplePeriodTicksOffset, 2U>(bytes)),
              static_cast<std::uint16_t>(field<kRateProfileInfoAdc1PhaseTicksOffset, 2U>(bytes))};
    }
  }
  return {};
}

// Keep experimental clocks and historical v2 rates out of public selection.
static_assert(cpuIdForHz(528000000U) == 0U);
static_assert(cpuFor(protocol_v3::CpuProfile::kCpu600mhz).timestamp_hz == 8000000U);
static_assert(cpuFor(protocol_v3::CpuProfile::kCpu450mhz).timestamp_hz == 8000000U);
static_assert(rateFor(protocol_v3::RateProfile::kAdc1mhzGpio1mhz).adc_pair_hz == 1000000U);

}  // namespace thingdaq::board_profile
