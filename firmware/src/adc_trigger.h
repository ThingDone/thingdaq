#pragma once

#include "input_experiment_profile.h"

#include <array>
#include <cstddef>
#include <cstdint>

#include "generated/protocol_constants.h"
#include "protocol.h"

namespace thingdaq::adc_trigger {

inline constexpr std::size_t kConverterCount = 2U;
inline constexpr std::uint16_t kRequiredConfigurationFlags =
    protocol_v1::kKnownAdcTriggerConfigurationFlagMask;
inline constexpr std::uint32_t kDiagnosticDeadlineCycles =
    (input_experiment::kCpuHz / 1000000U) *
    protocol_v1::kAdcTriggerDiagnosticDeadlineUs;

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

struct ConfigureResult {
  std::uint16_t configuration_flags = 0U;
  std::uint32_t error_flags = 0U;
  HardwareEvidence evidence{};
};

// This diagnostic timestamps the first ADC_ETC conversion-completion status
// transitions. It is an implementation cross-check of the programmed relative
// trigger delay; it is deliberately not evidence of the analog sample-and-hold
// aperture.
struct Snapshot {
  std::uint16_t configuration_flags = 0U;
  std::uint32_t error_flags = 0U;
  std::uint32_t pit_clock_hz = protocol_v1::kAdcTriggerPitClockHz;
  std::uint32_t dwt_clock_hz = input_experiment::kCpuHz;
  std::uint32_t gpio_master_rate_hz =
      protocol_v1::kAdcTriggerGpioMasterRateHz;
  std::uint32_t pair_rate_hz = protocol_v1::kAdcTriggerPairRateHz;
  std::uint32_t ipg_clock_hz = protocol_v1::kAdcTriggerIpgClockHz;
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
      protocol_v1::kAdcTriggerInitialDelays[0],
      protocol_v1::kAdcTriggerInitialDelays[1]};
  std::array<std::uint16_t, kConverterCount> effective_delays{
      protocol_v1::kAdcTriggerEffectiveDelays[0],
      protocol_v1::kAdcTriggerEffectiveDelays[1]};
  std::uint16_t phase_ipg_cycles = protocol_v1::kAdcTriggerPhaseIpgCycles;
  HardwareEvidence evidence{};
  std::array<std::uint32_t, kConverterCount> completion_counts{};
  std::uint32_t completion_delta_cycles = 0U;
  std::uint32_t completion_expected_delta_cycles =
      input_experiment::scaleDwt(protocol_v1::kAdcCompletionExpectedDwtCycles);
  std::uint32_t completion_tolerance_cycles =
      input_experiment::scaleDwt(protocol_v1::kAdcCompletionToleranceDwtCycles);
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
  virtual std::array<std::uint32_t, kConverterCount>
  firstCompletionCycles() = 0;
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
static_assert(protocol_v1::kAdcTriggerEffectiveDelays[1] -
                      protocol_v1::kAdcTriggerEffectiveDelays[0] ==
                  75U);
static_assert(protocol_v1::kAdcTriggerPhaseIpgCycles *
                      protocol_v1::kTimestampHz /
                      protocol_v1::kAdcTriggerIpgClockHz ==
                  protocol_v1::kAdc1PhaseTicks);
static_assert(static_cast<std::uint64_t>(
                  protocol_v1::kAdcTriggerPhaseIpgCycles) *
                      input_experiment::kCpuHz /
                      protocol_v1::kAdcTriggerIpgClockHz ==
                  input_experiment::scaleDwt(protocol_v1::kAdcCompletionExpectedDwtCycles));
static_assert(protocol_v1::kAdcTriggerQueues[0] !=
              protocol_v1::kAdcTriggerQueues[1]);
static_assert(kDiagnosticDeadlineCycles == input_experiment::scaleDwt(1200000U));

}  // namespace thingdaq::adc_trigger
