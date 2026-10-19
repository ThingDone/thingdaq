#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "generated/protocol_v3_constants.h"
#include "input_experiment_profile.h"

namespace thingdaq::settings {

// Wire-sized values avoid padding, heap storage and a second metadata table.
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
    input_experiment::kCpuHz == 600000000U   ? 1U
    : input_experiment::kCpuHz == 450000000U ? 2U
                                             : 0U;

constexpr Record buildDefaults() {
  auto value = kBoardDefaults;
  value[protocol_v3::kSettingsCpuProfileOffset] = kBuildCpuProfile;
  // Compression is the public 600 MHz default. The board table excludes
  // codecs at 450 MHz; build-fixed clocks remain enforced by the adapter.
  value[protocol_v3::kSettingsGpioPolicyOffset] = kBuildCpuProfile == 1U ? 1U : 0U;
  value[protocol_v3::kSettingsAdcPolicyOffset] = kBuildCpuProfile == 1U ? 1U : 0U;
  return value;
}
inline constexpr auto kBuildDefaults = buildDefaults();

inline Clocks clocksFor(std::uint8_t profile) {
  for (const auto& bytes : protocol_v3::kCpuProfiles) {
    if (bytes[0] == profile) return record(bytes);
  }
  return {};
}

inline bool boardSupports(const Record& value) {
  for (const auto& bytes : protocol_v3::kSelectableConfigurations) {
    if (record(bytes) == value) return true;
  }
  return false;
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
