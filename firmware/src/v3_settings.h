#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_profile.h"
#include "input_experiment_profile.h"

namespace thingdaq::settings {

// Wire-sized values avoid padding, heap storage and a second metadata table.
// Public decoded payload is cache-line aligned and leaves room for the prefix
// in every existing 4096-byte packet page. Shared by metadata and acquisition.
inline constexpr std::uint32_t kDecodedPayloadBytes = 4032U;
inline constexpr std::uint32_t kRawFrameBytes = kDecodedPayloadBytes +
    protocol_v3::kHeaderSize + protocol_v3::kDataPrefixBytes + protocol_v3::kTrailerSize;

using Record = std::array<std::uint8_t, protocol_v3::kSettingsPayloadSize>;
using Clocks =
    std::array<std::uint8_t, protocol_v3::kCpuProfileInfoPayloadSize>;

template <std::size_t N>
constexpr std::array<std::uint8_t, N> record(const std::uint8_t (&bytes)[N]) {
  std::array<std::uint8_t, N> result{};
  for (std::size_t i = 0U; i < N; ++i) result[i] = bytes[i];
  return result;
}

inline constexpr auto kBoardDefaults = record(protocol_v3::kDefaultSettings[0]);
inline constexpr std::uint8_t kBuildCpuProfile =
    board_profile::cpuIdForHz(input_experiment::kCpuHz);

constexpr bool boardSupports(const Record& value) {
  for (const auto& bytes : protocol_v3::kSelectableConfigurations) {
    bool equal = true;
    for (std::size_t i = 0U; i < value.size(); ++i)
      if (bytes[i] != value[i]) equal = false;
    if (equal) return true;
  }
  return false;
}

constexpr Record defaultsFor(protocol_v3::CpuProfile profile) {
  auto value = kBoardDefaults;
  value[protocol_v3::kSettingsCpuProfileOffset] =
      static_cast<std::uint8_t>(profile);
  if (boardSupports(value)) return value;
  // Preserve the board's default stream/source/width/rates when this CPU
  // supports only RAW. Exact membership still decides whether it is usable.
  value[protocol_v3::kSettingsGpioPolicyOffset] =
      static_cast<std::uint8_t>(protocol_v3::GpioPolicy::kRaw);
  value[protocol_v3::kSettingsAdcPolicyOffset] =
      static_cast<std::uint8_t>(protocol_v3::AdcPolicy::kRaw);
  return boardSupports(value) ? value : Record{};
}

constexpr Record buildDefaults() {
  return defaultsFor(static_cast<protocol_v3::CpuProfile>(kBuildCpuProfile));
}
inline constexpr auto kBuildDefaults = buildDefaults();

constexpr Clocks clocksFor(std::uint8_t profile) {
  for (const auto& bytes : protocol_v3::kCpuProfiles) {
    if (bytes[protocol_v3::kCpuProfileInfoCpuProfileOffset] == profile)
      return record(bytes);
  }
  return {};
}

struct Applied {
  Record settings = kBuildDefaults;
  Clocks clocks = clocksFor(kBuildCpuProfile);
};

// Apply synchronously while acquisition is quiescent and return actual readback.
// On failure or mismatch, ControlState reapplies the previous complete record
// and verifies restoration before allowing START or settings/clock reports.
// This seam does not establish physical qualification.
class Application {
 public:
  virtual ~Application() = default;
  virtual Record defaults() const = 0;
  virtual bool supports(const Record& candidate) const = 0;
  virtual bool apply(const Record& candidate, Applied& readback) = 0;
};

// Current production adapter changes software acquisition selections only.
// Clocks are build-fixed; no runtime clock selection or hardware writes occur.
// Phase 04 replaces this with verified register application/readback.
class FixedBuildApplication final : public Application {
 public:
  Record defaults() const override { return kBuildDefaults; }
  bool supports(const Record& candidate) const override {
    return kBuildCpuProfile != 0U && boardSupports(candidate) &&
           candidate[protocol_v3::kSettingsCpuProfileOffset] ==
               kBuildCpuProfile;
  }
  bool apply(const Record& candidate, Applied& readback) override {
    if (!supports(candidate)) return false;
    readback = {candidate, clocksFor(kBuildCpuProfile)};
    return true;
  }
};
inline FixedBuildApplication kFixedBuildApplication{};

static_assert(sizeof(Record) == 20U && sizeof(Clocks) == 24U);
static_assert(sizeof(Applied) == 44U);
static_assert(sizeof(protocol_v3::kSelectableConfigurations) / sizeof(Record) <=
              protocol_v3::kMaxConfigurationTuples);

}  // namespace thingdaq::settings
