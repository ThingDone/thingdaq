#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "firmware_identity.h"
#include "generated/protocol_constants.h"
#include "protocol.h"

namespace thingdaq::adc_trigger {

inline constexpr std::size_t kConverterCount = 2U;
inline constexpr std::size_t kDiagnosticWarmupPairCount =
    protocol_v1::kAdcTriggerDiagnosticWarmupPairCount;
inline constexpr std::size_t kDiagnosticMeasuredPairCount =
    protocol_v1::kAdcTriggerDiagnosticMeasuredPairCount;
inline constexpr std::size_t kDiagnosticCompletionTarget =
    protocol_v1::kAdcTriggerDiagnosticCompletionTarget;
inline constexpr std::uint16_t kRequiredConfigurationFlags =
    protocol_v1::kKnownAdcTriggerConfigurationFlagMask;
inline constexpr std::uint32_t kDiagnosticDeadlineCycles =
    identity::dwtCyclesForMicroseconds(
        protocol_v1::kAdcTriggerDiagnosticDeadlineUs);

constexpr std::uint16_t configurationFlag(
    protocol_v1::AdcTriggerConfigurationFlag flag) {
  return static_cast<std::uint16_t>(flag);
}

constexpr std::uint32_t triggerError(protocol_v1::AdcTriggerError error) {
  return static_cast<std::uint32_t>(error);
}

inline constexpr std::uint16_t kStoppedConfigurationFlags =
    configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kConfiguredStopped) |
    configurationFlag(protocol_v1::AdcTriggerConfigurationFlag::kClocksValid) |
    configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kXbarRoutesValid) |
    configurationFlag(protocol_v1::AdcTriggerConfigurationFlag::kQueuesValid) |
    configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kAdcHardwareTriggerValid);

using HardwareEvidence = protocol::AdcTriggerHardwareEvidence;
using CompletionDeltaSamples =
    std::array<std::uint32_t, kDiagnosticMeasuredPairCount>;

struct ConfigureResult {
  std::uint16_t configuration_flags = 0U;
  std::uint32_t error_flags = 0U;
  HardwareEvidence evidence{};
};

// This diagnostic timestamps consecutive ADC_ETC conversion-completion status
// transitions, discards one startup pair, and grades the median of seven paired
// deltas. It is an implementation cross-check of the programmed relative
// trigger delay; it is deliberately not evidence of the analog sample-and-hold
// aperture.
struct Snapshot {
  std::uint16_t configuration_flags = 0U;
  std::uint32_t error_flags = 0U;
  std::uint32_t pit_clock_hz = protocol_v1::kAdcTriggerPitClockHz;
  std::uint32_t dwt_clock_hz = identity::kExpectedDwtHz;
  std::uint32_t gpio_master_rate_hz =
      protocol_v1::kAdcTriggerGpioMasterRateHz;
  std::uint32_t pair_rate_hz = protocol_v1::kAdcTriggerPairRateHz;
  std::uint32_t ipg_clock_hz = identity::kExpectedIpgHz;
  std::uint8_t gpio_master_pit_channel =
      protocol_v1::kAdcTriggerGpioMasterPitChannel;
  std::uint8_t pair_pit_channel =
      protocol_v1::kAdcTriggerPairPitChannel;
  std::uint8_t gpio_master_pit_load =
      protocol_v1::kAdcTriggerGpioMasterPitLoad;
  std::uint8_t pair_pit_load = protocol_v1::kAdcTriggerPairPitLoad;
  std::uint8_t predivider = protocol_v1::kAdcTriggerPredivider;
  std::uint8_t chain_length = protocol_v1::kAdcTriggerChainLength;
  std::array<std::uint8_t, kConverterCount> xbar_inputs{
      protocol_v1::kAdcTriggerXbarInputs[0],
      protocol_v1::kAdcTriggerXbarInputs[1]};
  std::array<std::uint8_t, kConverterCount> xbar_outputs{
      protocol_v1::kAdcTriggerXbarOutputs[0],
      protocol_v1::kAdcTriggerXbarOutputs[1]};
  std::array<std::uint8_t, kConverterCount> trigger_queues{
      protocol_v1::kAdcTriggerQueues[0],
      protocol_v1::kAdcTriggerQueues[1]};
  std::array<std::uint16_t, kConverterCount> initial_delays{
      identity::kAdcTriggerInitialDelays[0],
      identity::kAdcTriggerInitialDelays[1]};
  std::array<std::uint16_t, kConverterCount> effective_delays{
      identity::kAdcTriggerEffectiveDelays[0],
      identity::kAdcTriggerEffectiveDelays[1]};
  std::uint16_t phase_ipg_cycles = identity::kAdcNominalPhaseIpgCycles;
  HardwareEvidence evidence{};
  std::array<std::uint32_t, kConverterCount> completion_counts{};
  std::uint32_t completion_delta_cycles = 0U;
  std::uint32_t completion_expected_delta_cycles =
      identity::kAdcCompletionExpectedDwtCycles;
  std::uint32_t completion_tolerance_cycles =
      identity::kAdcCompletionToleranceDwtCycles;
  std::uint32_t diagnostic_elapsed_cycles = 0U;
  std::uint32_t trigger_error_count = 0U;

  constexpr bool ready() const {
    return configuration_flags == kRequiredConfigurationFlags &&
           error_flags == 0U;
  }
};

class Platform {
 public:
  virtual ~Platform() = default;

  virtual ConfigureResult configureStopped() = 0;
  virtual bool beginCycleCounter(std::uint32_t &frequency_hz) = 0;
  virtual std::uint32_t readCycles() = 0;
  // BOOT performs a bounded, target-owned completion-status diagnostic while
  // arming. Production leaves the ADC_ETC error vector to the dual-DMA owner
  // and enables only the stopped trigger schedule.
  virtual bool armFromStopped(bool completion_diagnostic) = 0;
  virtual std::array<std::uint32_t, kConverterCount> completionCounts() = 0;
  virtual CompletionDeltaSamples completionDeltaSamples() = 0;
  virtual std::uint32_t triggerErrorFlags() = 0;
  virtual std::uint32_t triggerErrorCount() = 0;
  virtual bool stop() = 0;
  virtual HardwareEvidence evidence() = 0;
};

class Scheduler {
 public:
  constexpr explicit Scheduler(Platform &platform) : platform_(platform) {}

  const Snapshot &initialize(bool converters_ready);
  bool arm();
  bool stop();
  constexpr const Snapshot &snapshot() const { return snapshot_; }
  constexpr bool running() const { return running_; }

 private:
  Platform &platform_;
  Snapshot snapshot_{};
  bool running_ = false;
};

protocol::AdcTriggerMetadata protocolMetadata(const Snapshot &snapshot);

static_assert(protocol_v1::kAdcTriggerGpioMasterRateHz /
                      protocol_v1::kAdcTriggerPairRateHz ==
                  4U,
              "four GPIO master periods must equal one ADC pair period");
static_assert(protocol_v1::kAdcTriggerPitClockHz /
                          protocol_v1::kAdcTriggerGpioMasterRateHz -
                      1U ==
                  protocol_v1::kAdcTriggerGpioMasterPitLoad);
static_assert(protocol_v1::kAdcTriggerGpioMasterRateHz /
                          protocol_v1::kAdcTriggerPairRateHz -
                      1U ==
                  protocol_v1::kAdcTriggerPairPitLoad);
static_assert(identity::kAdcTriggerEffectiveDelays[1] -
                      identity::kAdcTriggerEffectiveDelays[0] ==
                  identity::kAdcNominalPhaseIpgCycles);
static_assert(identity::kAdcNominalPhaseIpgCycles *
                      protocol_v1::kTimestampHz /
                      identity::kExpectedIpgHz ==
                  protocol_v1::kAdc1PhaseTicks);
static_assert(static_cast<std::uint64_t>(
                  identity::kAdcNominalPhaseIpgCycles) *
                      identity::kExpectedDwtHz /
                      identity::kExpectedIpgHz ==
                  identity::kAdcCompletionExpectedDwtCycles);
static_assert(protocol_v1::kAdcTriggerQueues[0] !=
              protocol_v1::kAdcTriggerQueues[1]);
static_assert(kDiagnosticDeadlineCycles ==
              identity::kExpectedDwtHz / 500U);
static_assert(kDiagnosticMeasuredPairCount % 2U == 1U,
              "the completion-delta median requires an odd sample count");
static_assert(kDiagnosticCompletionTarget ==
              kDiagnosticWarmupPairCount + kDiagnosticMeasuredPairCount);
static_assert(kDiagnosticCompletionTarget <
              protocol_v1::kAdcTriggerDiagnosticPollLimit);

}  // namespace thingdaq::adc_trigger
