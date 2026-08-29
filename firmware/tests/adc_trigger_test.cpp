#include <array>
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>

#include "adc_trigger.h"

namespace adc_trigger = teensy_daq::adc_trigger;
namespace protocol_v1 = teensy_daq::protocol_v1;

namespace {

constexpr std::uint16_t kConfiguredFlags =
    adc_trigger::configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kConfiguredStopped) |
    adc_trigger::configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kClocksValid) |
    adc_trigger::configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kXbarRoutesValid) |
    adc_trigger::configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::kQueuesValid) |
    adc_trigger::configurationFlag(
        protocol_v1::AdcTriggerConfigurationFlag::
            kAdcHardwareTriggerValid);

class FakePlatform final : public adc_trigger::Platform {
 public:
  adc_trigger::ConfigureResult configure_result{};
  bool counter_available = true;
  std::uint32_t counter_hz = protocol_v1::kAdcTriggerDwtClockHz;
  std::uint32_t cycles = 0U;
  std::uint32_t cycle_step = 100U;
  bool arm_ok = true;
  bool stop_ok = true;
  std::uint32_t completion_after_poll = 2U;
  std::array<std::uint32_t, 2U> completed_counts{1U, 1U};
  std::array<std::uint32_t, 2U> first_cycles{0xFFFFFF00U, 0x0000002CU};
  std::uint32_t trigger_errors = 0U;
  std::uint32_t trigger_error_count = 0U;
  adc_trigger::HardwareEvidence terminal_evidence{};
  std::vector<std::string> operations{};
  std::vector<bool> diagnostic_arms{};
  std::uint32_t completion_polls = 0U;

  FakePlatform() {
    configure_result.configuration_flags = kConfiguredFlags;
    configure_result.evidence.adc_etc_ctrl_configured = 0xA0U;
    terminal_evidence = configure_result.evidence;
    terminal_evidence.done0_1_irq_final = 0xB0U;
  }

  adc_trigger::ConfigureResult configureStopped() override {
    operations.emplace_back("configure");
    return configure_result;
  }

  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    operations.emplace_back("counter");
    frequency_hz = counter_hz;
    return counter_available;
  }

  std::uint32_t readCycles() override {
    const std::uint32_t result = cycles;
    cycles += cycle_step;
    return result;
  }

  bool armFromStopped(bool completion_diagnostic) override {
    operations.emplace_back("arm");
    diagnostic_arms.push_back(completion_diagnostic);
    return arm_ok;
  }

  std::array<std::uint32_t, 2U> completionCounts() override {
    ++completion_polls;
    return completion_polls >= completion_after_poll
               ? completed_counts
               : std::array<std::uint32_t, 2U>{};
  }

  std::array<std::uint32_t, 2U> firstCompletionCycles() override {
    return first_cycles;
  }

  std::uint32_t triggerErrorFlags() override { return trigger_errors; }

  std::uint32_t triggerErrorCount() override {
    return trigger_error_count;
  }

  bool stop() override {
    operations.emplace_back("stop");
    return stop_ok;
  }

  adc_trigger::HardwareEvidence evidence() override {
    return terminal_evidence;
  }
};

void testExactScheduleAndSuccessfulDiagnostic() {
  FakePlatform platform{};
  adc_trigger::Scheduler scheduler{platform};
  const adc_trigger::Snapshot &snapshot = scheduler.initialize(true);

  assert(snapshot.ready());
  assert(snapshot.configuration_flags ==
         protocol_v1::kKnownAdcTriggerConfigurationFlagMask);
  assert(snapshot.error_flags == 0U);
  assert(snapshot.gpio_master_rate_hz == 4U * snapshot.pair_rate_hz);
  assert(snapshot.initial_delays ==
         (std::array<std::uint16_t, 2U>{0U, 75U}));
  assert(snapshot.effective_delays ==
         (std::array<std::uint16_t, 2U>{1U, 76U}));
  assert(snapshot.completion_delta_cycles == 300U);
  assert(snapshot.evidence.done0_1_irq_final == 0xB0U);
  assert((platform.operations ==
          std::vector<std::string>{"configure", "counter", "arm", "stop"}));
  assert((platform.diagnostic_arms == std::vector<bool>{true}));

  const teensy_daq::protocol::AdcTriggerMetadata metadata =
      adc_trigger::protocolMetadata(snapshot);
  assert(metadata.configuration_flags == snapshot.configuration_flags);
  assert(metadata.initial_delays == snapshot.initial_delays);
  assert(metadata.completion_delta_cycles == 300U);
  assert(metadata.evidence.done0_1_irq_final == 0xB0U);

  assert(scheduler.arm());
  assert((platform.diagnostic_arms == std::vector<bool>{true, false}));
  assert(scheduler.running());
  assert(!scheduler.arm());
  assert(scheduler.stop());
  assert(!scheduler.running());
}

void testConvertersMustBeReadyBeforeAnyPeripheralWrite() {
  FakePlatform platform{};
  adc_trigger::Scheduler scheduler{platform};
  const adc_trigger::Snapshot &snapshot = scheduler.initialize(false);
  assert(platform.operations.empty());
  assert(snapshot.error_flags == adc_trigger::triggerError(
                                     protocol_v1::AdcTriggerError::
                                         kConvertersNotReady));
}

void testConfigurationAndCounterFailuresAreObservable() {
  FakePlatform bad_configuration{};
  bad_configuration.configure_result.error_flags = adc_trigger::triggerError(
      protocol_v1::AdcTriggerError::kXbarConfigMismatch);
  adc_trigger::Scheduler scheduler{bad_configuration};
  const adc_trigger::Snapshot &configured = scheduler.initialize(true);
  assert(configured.error_flags == adc_trigger::triggerError(
                                       protocol_v1::AdcTriggerError::
                                           kXbarConfigMismatch));
  assert((bad_configuration.operations ==
          std::vector<std::string>{"configure"}));

  FakePlatform incomplete_configuration{};
  incomplete_configuration.configure_result.configuration_flags =
      adc_trigger::configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::kConfiguredStopped);
  adc_trigger::Scheduler incomplete_scheduler{incomplete_configuration};
  const adc_trigger::Snapshot &incomplete =
      incomplete_scheduler.initialize(true);
  assert(incomplete.error_flags ==
         adc_trigger::triggerError(
             protocol_v1::AdcTriggerError::kAdcEtcConfigMismatch));
  assert((incomplete_configuration.operations ==
          std::vector<std::string>{"configure"}));

  FakePlatform bad_counter{};
  bad_counter.counter_hz = 1U;
  adc_trigger::Scheduler counter_scheduler{bad_counter};
  const adc_trigger::Snapshot &counter = counter_scheduler.initialize(true);
  assert((counter.error_flags &
          adc_trigger::triggerError(
              protocol_v1::AdcTriggerError::kDwtUnavailable)) != 0U);
}

void testDiagnosticTimeoutIsBoundedAndLeavesStopped() {
  FakePlatform platform{};
  platform.completion_after_poll = 0xFFFFFFFFU;
  platform.cycle_step = adc_trigger::kDiagnosticDeadlineCycles / 2U;
  adc_trigger::Scheduler scheduler{platform};
  const adc_trigger::Snapshot &snapshot = scheduler.initialize(true);
  assert(!snapshot.ready());
  assert((snapshot.error_flags &
          adc_trigger::triggerError(
              protocol_v1::AdcTriggerError::kDiagnosticTimeout)) != 0U);
  assert((snapshot.error_flags &
          adc_trigger::triggerError(
              protocol_v1::AdcTriggerError::kCompletionCountMismatch)) != 0U);
  assert((snapshot.configuration_flags &
          adc_trigger::configurationFlag(
              protocol_v1::AdcTriggerConfigurationFlag::
                  kStoppedAfterDiagnostic)) != 0U);
  assert(platform.completion_polls < 10U);
}

void testCompletionTimingAndTriggerErrorsStayDistinct() {
  FakePlatform platform{};
  platform.first_cycles = {100U, 600U};
  platform.trigger_errors = 1U;
  platform.trigger_error_count = 1U;
  adc_trigger::Scheduler scheduler{platform};
  const adc_trigger::Snapshot &snapshot = scheduler.initialize(true);
  assert(snapshot.completion_delta_cycles == 500U);
  assert((snapshot.error_flags &
          adc_trigger::triggerError(
              protocol_v1::AdcTriggerError::
                  kCompletionTimingOutOfTolerance)) != 0U);
  assert((snapshot.error_flags &
          adc_trigger::triggerError(
              protocol_v1::AdcTriggerError::kAdcEtcTriggerError)) != 0U);
  assert(snapshot.trigger_error_count == 1U);

  FakePlatform valid_delta_with_error{};
  valid_delta_with_error.trigger_errors = 1U;
  valid_delta_with_error.trigger_error_count = 1U;
  adc_trigger::Scheduler error_scheduler{valid_delta_with_error};
  const adc_trigger::Snapshot &error_snapshot =
      error_scheduler.initialize(true);
  assert(error_snapshot.completion_delta_cycles == 300U);
  assert((error_snapshot.configuration_flags &
          adc_trigger::configurationFlag(
              protocol_v1::AdcTriggerConfigurationFlag::
                  kCompletionTimingValid)) == 0U);
  assert(!error_snapshot.ready());
}

void testFailedProductionArmForcesStoppedCleanup() {
  FakePlatform platform{};
  adc_trigger::Scheduler scheduler{platform};
  assert(scheduler.initialize(true).ready());
  platform.operations.clear();
  platform.arm_ok = false;

  assert(!scheduler.arm());
  assert(!scheduler.running());
  assert((platform.operations ==
          std::vector<std::string>{"arm", "stop"}));
}

}  // namespace

int main() {
  testExactScheduleAndSuccessfulDiagnostic();
  testConvertersMustBeReadyBeforeAnyPeripheralWrite();
  testConfigurationAndCounterFailuresAreObservable();
  testDiagnosticTimeoutIsBoundedAndLeavesStopped();
  testCompletionTimingAndTriggerErrorsStayDistinct();
  testFailedProductionArmForcesStoppedCleanup();
  return 0;
}
