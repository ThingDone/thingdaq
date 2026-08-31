#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "generated/protocol_constants.h"

namespace thingdaq::adc {

inline constexpr std::size_t kConverterCount = board::kLogicalAdcCount;
inline constexpr std::uint32_t kCalibrationDeadlineCycles =
    (protocol_v1::kAdcCalibrationCycleCounterHz / 1000000U) *
    protocol_v1::kAdcCalibrationDeadlineUs;

constexpr std::uint16_t configurationFlag(
    protocol_v1::AdcConfigurationFlag flag) {
  return static_cast<std::uint16_t>(flag);
}

constexpr std::uint32_t initializationError(
    protocol_v1::AdcInitializationError error) {
  return static_cast<std::uint32_t>(error);
}

// A fallback is authorized only by a completed target timing/error gate after
// the exact clock, route, and calibration preconditions have been corrected
// and verified. An incomplete gate, a routing fault, or a calibration fault
// keeps 12-bit selected and leaves physical acquisition unavailable.
struct ResolutionGate {
  bool completed = false;
  bool configuration_corrected = false;
  bool exact_rate_verified = false;
  bool calibration_verified = false;
  bool timing_within_budget = false;
  bool error_free = false;
};

constexpr std::uint8_t selectResolution(const ResolutionGate &gate) {
  const bool fallback_authorized =
      gate.completed && gate.configuration_corrected &&
      gate.exact_rate_verified && gate.calibration_verified &&
      (!gate.timing_within_budget || !gate.error_free);
  return fallback_authorized ? protocol_v1::kAdcFallbackResolutionBits
                             : protocol_v1::kAdcPrimaryResolutionBits;
}

constexpr std::uint16_t codeMaximum(std::uint8_t resolution_bits) {
  return resolution_bits == protocol_v1::kAdcFallbackResolutionBits
             ? static_cast<std::uint16_t>(
                   (1U << protocol_v1::kAdcFallbackResolutionBits) - 1U)
             : static_cast<std::uint16_t>(
                   (1U << protocol_v1::kAdcPrimaryResolutionBits) - 1U);
}

constexpr std::uint8_t conversionMode(std::uint8_t resolution_bits) {
  // i.MX RT1062 CFG.MODE: 1 is 10-bit and 2 is 12-bit single-ended.
  return resolution_bits == protocol_v1::kAdcFallbackResolutionBits ? 1U
                                                                    : 2U;
}

struct Settings {
  std::uint8_t resolution_bits = protocol_v1::kAdcPrimaryResolutionBits;
  std::uint8_t container_bytes = protocol_v1::kAdcContainerBits / 8U;
  std::uint16_t code_min = protocol_v1::kAdcCodeMin;
  std::uint16_t code_max = codeMaximum(protocol_v1::kAdcPrimaryResolutionBits);
  protocol_v1::AdcReference reference =
      protocol_v1::AdcReference::kVrefhVreflNominal3v3;
  protocol_v1::AdcClockSource clock_source =
      protocol_v1::AdcClockSource::kSynchronousIpg;
  std::uint8_t clock_divider = protocol_v1::kAdcClockDivider;
  std::uint8_t hardware_average_count =
      protocol_v1::kAdcHardwareAverageCount;
  std::uint16_t reference_mv_nominal =
      protocol_v1::kAdcReferenceMvNominal;
  std::uint16_t input_min_mv_nominal =
      protocol_v1::kAdcInputMinMvNominal;
  std::uint16_t input_max_mv_nominal =
      protocol_v1::kAdcInputMaxMvNominal;
  std::uint8_t sample_time_adck = protocol_v1::kAdcSampleTimeAdck;
  std::uint8_t conversion_mode = conversionMode(
      protocol_v1::kAdcPrimaryResolutionBits);
  std::uint32_t ipg_clock_hz = protocol_v1::kAdcIpgClockHz;
  std::uint32_t adc_clock_hz = protocol_v1::kAdcClockHz;
  std::uint32_t calibration_deadline_us =
      protocol_v1::kAdcCalibrationDeadlineUs;
};

constexpr Settings settingsFor(const ResolutionGate &gate) {
  Settings settings{};
  settings.resolution_bits = selectResolution(gate);
  settings.code_max = codeMaximum(settings.resolution_bits);
  settings.conversion_mode = conversionMode(settings.resolution_bits);
  return settings;
}

struct ConverterSnapshot {
  protocol_v1::AdcCalibrationState calibration_state =
      protocol_v1::AdcCalibrationState::kNotRun;
  std::uint32_t calibration_cycles = 0U;
};

struct Snapshot {
  Settings settings{};
  std::array<ConverterSnapshot, kConverterCount> converters{};
  std::uint16_t configuration_flags =
      configurationFlag(
          protocol_v1::AdcConfigurationFlag::kNoHardwareAveraging) |
      configurationFlag(protocol_v1::AdcConfigurationFlag::kHighSpeed) |
      configurationFlag(
          protocol_v1::AdcConfigurationFlag::kShortestSample) |
      configurationFlag(protocol_v1::AdcConfigurationFlag::kPrimary12Bit);
  std::uint32_t initialization_error_flags = 0U;

  constexpr bool ready() const {
    return (configuration_flags &
            configurationFlag(
                protocol_v1::AdcConfigurationFlag::kInitialized)) != 0U &&
           initialization_error_flags == 0U &&
           converters[0].calibration_state ==
               protocol_v1::AdcCalibrationState::kSucceeded &&
           converters[1].calibration_state ==
               protocol_v1::AdcCalibrationState::kSucceeded;
  }
};

constexpr Snapshot defaultSnapshot(const ResolutionGate &gate = {}) {
  Snapshot snapshot{};
  snapshot.settings = settingsFor(gate);
  snapshot.configuration_flags =
      configurationFlag(
          protocol_v1::AdcConfigurationFlag::kNoHardwareAveraging) |
      configurationFlag(protocol_v1::AdcConfigurationFlag::kHighSpeed) |
      configurationFlag(
          protocol_v1::AdcConfigurationFlag::kShortestSample) |
      configurationFlag(
          snapshot.settings.resolution_bits ==
                  protocol_v1::kAdcFallbackResolutionBits
              ? protocol_v1::AdcConfigurationFlag::kFallback10Bit
              : protocol_v1::AdcConfigurationFlag::kPrimary12Bit);
  return snapshot;
}

protocol::AdcInitializationMetadata protocolMetadata(
    const Snapshot &snapshot);

enum class PrepareStatus : std::uint8_t {
  kOk,
  kRouteInvalid,
  kConfigurationInvalid,
};

class Platform {
 public:
  virtual ~Platform() = default;

  virtual PrepareStatus prepareConverter(
      const board::AdcConverterConfiguration &route,
      const Settings &settings) = 0;
  virtual bool beginCycleCounter(std::uint32_t &frequency_hz) = 0;
  virtual std::uint32_t readCycles() = 0;
  virtual bool startCalibration(
      const board::AdcConverterConfiguration &route) = 0;
  virtual bool calibrationActive(
      const board::AdcConverterConfiguration &route) = 0;
  virtual bool calibrationFailed(
      const board::AdcConverterConfiguration &route) = 0;
  virtual bool verifyConverter(
      const board::AdcConverterConfiguration &route,
      const Settings &settings) = 0;
  virtual void abortCalibration(
      const board::AdcConverterConfiguration &route) = 0;
};

class Initializer {
 public:
  constexpr explicit Initializer(Platform &platform, ResolutionGate gate = {})
      : platform_(platform), gate_(gate), snapshot_(defaultSnapshot(gate)) {}

  const Snapshot &initialize();
  constexpr const Snapshot &snapshot() const { return snapshot_; }

 private:
  Platform &platform_;
  ResolutionGate gate_{};
  Snapshot snapshot_{};
};

static_assert(kConverterCount == 2U);
static_assert(kCalibrationDeadlineCycles == 6000000U);
static_assert(selectResolution({}) == protocol_v1::kAdcPrimaryResolutionBits);
static_assert(codeMaximum(protocol_v1::kAdcPrimaryResolutionBits) == 4095U);
static_assert(codeMaximum(protocol_v1::kAdcFallbackResolutionBits) == 1023U);
static_assert(conversionMode(protocol_v1::kAdcPrimaryResolutionBits) == 2U);
static_assert(conversionMode(protocol_v1::kAdcFallbackResolutionBits) == 1U);
static_assert(defaultSnapshot().settings.container_bytes == 2U);
static_assert(!defaultSnapshot().ready());

}  // namespace thingdaq::adc
