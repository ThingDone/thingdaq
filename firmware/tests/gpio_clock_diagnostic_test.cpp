#include <cstdint>
#include <iostream>
#include <string>

#include "gpio_clock_diagnostic.h"

namespace {

namespace clock_diagnostic = thingdaq::gpio_clock;
namespace constants = thingdaq::protocol_v1;
namespace wire = thingdaq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

constexpr std::uint32_t errorBit(constants::GpioClockError error) {
  return static_cast<std::uint32_t>(error);
}

class FakePlatform final : public clock_diagnostic::Platform {
 public:
  bool available = true;
  bool resource_busy = false;
  bool dwt_available = true;
  std::int32_t sample_adjustment = 0;
  std::int32_t elapsed_event_adjustment = 0;
  std::uint32_t injected_errors = 0U;
  std::uint32_t calls = 0U;
  clock_diagnostic::Plan observed{};

  bool execute(const clock_diagnostic::Plan &plan,
               wire::GpioClockDiagnosticResponse &snapshot) override {
    ++calls;
    observed = plan;
    if (!available) {
      return false;
    }
    snapshot.hardware_error_flags = injected_errors;
    if (resource_busy) {
      snapshot.hardware_error_flags |=
          errorBit(constants::GpioClockError::kResourceBusy);
      return true;
    }
    if (!dwt_available) {
      return true;
    }
    snapshot.dwt_counter_hz = constants::kGpioClockDwtHz;
    snapshot.dwt_elapsed_cycles = static_cast<std::uint32_t>(
        static_cast<std::int32_t>(plan.measurement_cycles) +
        elapsed_event_adjustment *
            static_cast<std::int32_t>(plan.cycles_per_event));
    snapshot.tcd_biter = plan.tcd_major_count;
    const std::int32_t adjusted =
        static_cast<std::int32_t>(plan.requested_event_count) +
        sample_adjustment;
    snapshot.dma_sample_count =
        adjusted > 0 ? static_cast<std::uint32_t>(adjusted) : 0U;
    snapshot.tcd_citer_final = static_cast<std::uint16_t>(
        plan.tcd_major_count - snapshot.dma_sample_count);
    return true;
  }
};

void testExactPlansAndBounds() {
  const wire::GpioClockDiagnosticRequest production{};
  expect(wire::validGpioClockDiagnosticRequest(production),
         "default production request is valid");
  const clock_diagnostic::Plan production_plan =
      clock_diagnostic::makePlan(production);
  expect(production_plan.rate_hz == 4000000U &&
             production_plan.pit_divisor == 6U &&
             production_plan.pit_load_value == 5U &&
             production_plan.cycles_per_event == 150U &&
             production_plan.measurement_cycles == 1228800U &&
             production_plan.tcd_major_count == 16400U,
         "4 MHz plan uses exact PIT/DWT arithmetic and a duplicate guard");

  wire::GpioClockDiagnosticRequest low_rate{};
  low_rate.rate_hz = 1000U;
  low_rate.event_count = 32U;
  const clock_diagnostic::Plan low_plan =
      clock_diagnostic::makePlan(low_rate);
  expect(wire::validGpioClockDiagnosticRequest(low_rate) &&
             low_plan.pit_load_value == 23999U &&
             low_plan.cycles_per_event == 600000U &&
             low_plan.measurement_cycles == 19200000U,
         "bounded 1 kHz bring-up plan remains exact");

  low_rate.rate_hz = 3999999U;
  expect(!wire::validGpioClockDiagnosticRequest(low_rate),
         "non-divisor diagnostic rates are rejected");
  low_rate.rate_hz = 1000U;
  low_rate.event_count = constants::kGpioClockMaxEventCount;
  expect(!wire::validGpioClockDiagnosticRequest(low_rate),
         "low-rate windows cannot exceed the DWT duration bound");
}

void testHealthyAndFaultEvidence() {
  FakePlatform platform{};
  clock_diagnostic::Runner runner{platform};
  const wire::GpioClockDiagnosticRequest request{};

  clock_diagnostic::RunResult result = runner.run(request);
  expect(result.ok() && platform.calls == 1U &&
             result.response.production_rate_hz == 4000000U &&
             result.response.pit_clock_hz == 24000000U &&
             result.response.pit_load_value == 5U &&
             result.response.requested_event_count == request.event_count &&
             result.response.scheduled_event_count == request.event_count &&
             result.response.dma_sample_count == request.event_count &&
             result.response.hardware_error_flags == 0U,
         "healthy run preserves exact requested, scheduled, and DMA counts");

  platform.sample_adjustment = -static_cast<std::int32_t>(request.event_count);
  result = runner.run(request);
  expect((result.response.hardware_error_flags &
          errorBit(constants::GpioClockError::kDeadTrigger)) != 0U &&
             (result.response.hardware_error_flags &
              errorBit(constants::GpioClockError::kCountOutOfTolerance)) !=
                 0U,
         "zero DMA requests are classified as a dead trigger and count fault");

  platform.sample_adjustment = 2;
  result = runner.run(request);
  expect((result.response.hardware_error_flags &
          errorBit(constants::GpioClockError::kDuplicateTrigger)) != 0U &&
             (result.response.hardware_error_flags &
              errorBit(constants::GpioClockError::kCountOutOfTolerance)) !=
                 0U,
         "excess DMA requests are classified as duplicate triggers");

  platform.sample_adjustment = 0;
  platform.elapsed_event_adjustment = -2;
  result = runner.run(request);
  expect((result.response.hardware_error_flags &
          errorBit(constants::GpioClockError::kCountOutOfTolerance)) != 0U,
         "a prematurely short DWT window is classified as a count fault");

  platform.elapsed_event_adjustment = 0;
  platform.injected_errors =
      errorBit(constants::GpioClockError::kXbarConfigMismatch);
  result = runner.run(request);
  expect((result.response.hardware_error_flags &
          errorBit(constants::GpioClockError::kXbarConfigMismatch)) != 0U,
         "platform register-validation flags remain visible to the host");
}

void testUnavailableAndUnarmedPaths() {
  FakePlatform platform{};
  clock_diagnostic::Runner runner{platform};
  const wire::GpioClockDiagnosticRequest request{};

  platform.available = false;
  clock_diagnostic::RunResult result = runner.run(request);
  expect(result.status == clock_diagnostic::RunStatus::kPlatformUnavailable,
         "an unavailable target adapter is reported without fabricated evidence");

  platform.available = true;
  platform.resource_busy = true;
  result = runner.run(request);
  expect(result.ok() &&
             result.response.hardware_error_flags ==
                 errorBit(constants::GpioClockError::kResourceBusy),
         "a reserved-resource conflict does not produce derivative count noise");

  platform.resource_busy = false;
  platform.dwt_available = false;
  result = runner.run(request);
  expect(result.ok() &&
             result.response.hardware_error_flags ==
                 errorBit(constants::GpioClockError::kDwtUnavailable),
         "a stopped DWT counter is reported before timing-derived checks");

  wire::GpioClockDiagnosticRequest invalid{};
  invalid.event_count = 0U;
  const std::uint32_t calls_before = platform.calls;
  result = runner.run(invalid);
  expect(result.status == clock_diagnostic::RunStatus::kInvalidRequest &&
             platform.calls == calls_before,
         "invalid requests never touch the hardware adapter");
}

}  // namespace

int main() {
  testExactPlansAndBounds();
  testHealthyAndFaultEvidence();
  testUnavailableAndUnarmedPaths();
  if (failures != 0) {
    std::cerr << failures << " GPIO clock diagnostic assertion(s) failed\n";
    return 1;
  }
  std::cout << "GPIO clock diagnostic tests passed\n";
  return 0;
}
