#include "input_experiment_profile.h"

#include "adc_trigger.h"

#include <cstdint>

#if defined(__IMXRT1062__)
#define THINGDAQ_ADC_TRIGGER_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_ADC_TRIGGER_COLD_CODE(section_name)
#endif

namespace thingdaq::adc_trigger {
namespace {

void addError(Snapshot &snapshot, protocol_v1::AdcTriggerError error) {
  snapshot.error_flags |= triggerError(error);
}

std::uint32_t absoluteDifference(std::uint32_t left, std::uint32_t right) {
  return left >= right ? left - right : right - left;
}

THINGDAQ_ADC_TRIGGER_COLD_CODE(
    ".flashmem.adc_trigger.capture_terminal_evidence")
void captureTerminalEvidence(Platform &platform, Snapshot &snapshot) {
  snapshot.evidence = platform.evidence();
  snapshot.completion_counts = platform.completionCounts();
  snapshot.trigger_error_count = platform.triggerErrorCount();
  if (platform.triggerErrorFlags() != 0U ||
      snapshot.trigger_error_count != 0U) {
    addError(snapshot,
             protocol_v1::AdcTriggerError::kAdcEtcTriggerError);
  }
}

}  // namespace

THINGDAQ_ADC_TRIGGER_COLD_CODE(".flashmem.adc_trigger.metadata")
protocol::AdcTriggerMetadata protocolMetadata(const Snapshot &snapshot) {
  protocol::AdcTriggerMetadata metadata{};
  metadata.configuration_flags = snapshot.configuration_flags;
  metadata.error_flags = snapshot.error_flags;
  metadata.pit_clock_hz = snapshot.pit_clock_hz;
  metadata.dwt_clock_hz = snapshot.dwt_clock_hz;
  metadata.gpio_master_rate_hz = snapshot.gpio_master_rate_hz;
  metadata.pair_rate_hz = snapshot.pair_rate_hz;
  metadata.ipg_clock_hz = snapshot.ipg_clock_hz;
  metadata.gpio_master_pit_channel = snapshot.gpio_master_pit_channel;
  metadata.pair_pit_channel = snapshot.pair_pit_channel;
  metadata.gpio_master_pit_load = snapshot.gpio_master_pit_load;
  metadata.pair_pit_load = snapshot.pair_pit_load;
  metadata.predivider = snapshot.predivider;
  metadata.chain_length = snapshot.chain_length;
  metadata.xbar_inputs = snapshot.xbar_inputs;
  metadata.xbar_outputs = snapshot.xbar_outputs;
  metadata.trigger_queues = snapshot.trigger_queues;
  metadata.initial_delays = snapshot.initial_delays;
  metadata.effective_delays = snapshot.effective_delays;
  metadata.phase_ipg_cycles = snapshot.phase_ipg_cycles;
  metadata.evidence = snapshot.evidence;
  metadata.completion_counts = snapshot.completion_counts;
  metadata.completion_delta_cycles = snapshot.completion_delta_cycles;
  metadata.completion_expected_delta_cycles =
      snapshot.completion_expected_delta_cycles;
  metadata.completion_tolerance_cycles =
      snapshot.completion_tolerance_cycles;
  metadata.diagnostic_elapsed_cycles = snapshot.diagnostic_elapsed_cycles;
  metadata.trigger_error_count = snapshot.trigger_error_count;
  return metadata;
}

THINGDAQ_ADC_TRIGGER_COLD_CODE(".flashmem.adc_trigger.initialize")
const Snapshot &Scheduler::initialize(bool converters_ready) {
  snapshot_ = Snapshot{};
  running_ = false;
  if (!converters_ready) {
    addError(snapshot_,
             protocol_v1::AdcTriggerError::kConvertersNotReady);
    return snapshot_;
  }

  const ConfigureResult configured = platform_.configureStopped();
  snapshot_.configuration_flags = configured.configuration_flags;
  snapshot_.error_flags |= configured.error_flags;
  snapshot_.evidence = configured.evidence;
  if (snapshot_.configuration_flags != kStoppedConfigurationFlags &&
      snapshot_.error_flags == 0U) {
    addError(snapshot_,
             protocol_v1::AdcTriggerError::kAdcEtcConfigMismatch);
  }
  if (snapshot_.error_flags != 0U) {
    return snapshot_;
  }

  std::uint32_t counter_hz = 0U;
  if (!platform_.beginCycleCounter(counter_hz) ||
      counter_hz != input_experiment::kCpuHz) {
    addError(snapshot_, protocol_v1::AdcTriggerError::kDwtUnavailable);
    return snapshot_;
  }

  const std::uint32_t started = platform_.readCycles();
  if (!platform_.armFromStopped(true)) {
    addError(snapshot_, protocol_v1::AdcTriggerError::kArmFailed);
    if (!platform_.stop()) {
      addError(snapshot_, protocol_v1::AdcTriggerError::kCleanupFailed);
    } else {
      snapshot_.configuration_flags |= configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::
              kStoppedAfterDiagnostic);
    }
    captureTerminalEvidence(platform_, snapshot_);
    return snapshot_;
  }
  snapshot_.configuration_flags |= configurationFlag(
      protocol_v1::AdcTriggerConfigurationFlag::kArmSequenceExercised);
  running_ = true;

  bool completed = false;
  for (std::uint32_t poll = 0U;
       poll < protocol_v1::kAdcTriggerDiagnosticPollLimit; ++poll) {
    const auto counts = platform_.completionCounts();
    if (counts[0] != 0U && counts[1] != 0U) {
      completed = true;
      break;
    }
    if (platform_.triggerErrorFlags() != 0U ||
        platform_.readCycles() - started >= kDiagnosticDeadlineCycles) {
      break;
    }
  }

  const std::uint32_t ended = platform_.readCycles();
  snapshot_.diagnostic_elapsed_cycles = ended - started;
  if (!platform_.stop()) {
    addError(snapshot_, protocol_v1::AdcTriggerError::kCleanupFailed);
  } else {
    snapshot_.configuration_flags |= configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kStoppedAfterDiagnostic);
  }
  running_ = false;
  captureTerminalEvidence(platform_, snapshot_);

  if (!completed) {
    addError(snapshot_, protocol_v1::AdcTriggerError::kDiagnosticTimeout);
  }
  if (snapshot_.completion_counts[0] == 0U ||
      snapshot_.completion_counts[1] == 0U) {
    addError(snapshot_,
             protocol_v1::AdcTriggerError::kCompletionCountMismatch);
    return snapshot_;
  }

  const auto first = platform_.firstCompletionCycles();
  snapshot_.completion_delta_cycles = first[1] - first[0];
  if (absoluteDifference(snapshot_.completion_delta_cycles,
                         snapshot_.completion_expected_delta_cycles) >
      snapshot_.completion_tolerance_cycles) {
    addError(snapshot_,
             protocol_v1::AdcTriggerError::
                 kCompletionTimingOutOfTolerance);
    return snapshot_;
  }
  if (snapshot_.error_flags != 0U ||
      (snapshot_.configuration_flags &
       configurationFlag(protocol_v1::AdcTriggerConfigurationFlag::
                             kStoppedAfterDiagnostic)) == 0U) {
    return snapshot_;
  }
  snapshot_.configuration_flags |= configurationFlag(
      protocol_v1::AdcTriggerConfigurationFlag::kCompletionTimingValid);
  return snapshot_;
}

THINGDAQ_ADC_TRIGGER_COLD_CODE(".flashmem.adc_trigger.arm")
bool Scheduler::arm() {
  if (running_ || !snapshot_.ready()) {
    return false;
  }
  if (!platform_.armFromStopped(false)) {
    // A target can reject the final readback after it has already written
    // one or more enable registers. Always drive the platform back through
    // its bounded stopped-state cleanup before the caller tears down DMA.
    (void)platform_.stop();
    return false;
  }
  running_ = true;
  return true;
}

THINGDAQ_ADC_TRIGGER_COLD_CODE(".flashmem.adc_trigger.stop")
bool Scheduler::stop() {
  if (!running_) {
    return true;
  }
  const bool stopped = platform_.stop();
  if (stopped) {
    running_ = false;
  }
  return stopped;
}

}  // namespace thingdaq::adc_trigger

#undef THINGDAQ_ADC_TRIGGER_COLD_CODE
