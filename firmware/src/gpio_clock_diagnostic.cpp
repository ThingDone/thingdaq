#include "input_experiment_profile.h"

#include "gpio_clock_diagnostic.h"

#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_GPIO_CLOCK_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_GPIO_CLOCK_COLD_CODE(section_name)
#endif

namespace thingdaq::gpio_clock {
namespace {

constexpr std::uint32_t absoluteDifference(std::uint32_t left,
                                           std::uint32_t right) {
  return left >= right ? left - right : right - left;
}

}  // namespace

THINGDAQ_GPIO_CLOCK_COLD_CODE(".flashmem.gpio_clock.plan")
Plan makePlan(const protocol::GpioClockDiagnosticRequest &request) {
  Plan plan{};
  if (!protocol::validGpioClockDiagnosticRequest(request)) {
    return plan;
  }
  plan.rate_hz = request.rate_hz;
  plan.pit_divisor = protocol_v1::kGpioClockPitHz / request.rate_hz;
  plan.pit_load_value = plan.pit_divisor - 1U;
  // Reuse the rational event/cycle conversion from experiment/clock-450mhz:
  // 450 MHz / 4 MHz is 112.5 cycles, not an integer cycles-per-event.
  plan.cycles_per_event = (input_experiment::kCpuHz + request.rate_hz - 1U) /
      request.rate_hz;
  plan.measurement_cycles =
      static_cast<std::uint32_t>((static_cast<std::uint64_t>(request.event_count) *
          input_experiment::kCpuHz + request.rate_hz - 1U) / request.rate_hz);
  plan.requested_event_count = request.event_count;
  plan.tcd_major_count = static_cast<std::uint16_t>(
      2U * static_cast<std::uint32_t>(request.event_count) +
      protocol_v1::kGpioClockDuplicateGuardEvents);
  return plan;
}

THINGDAQ_GPIO_CLOCK_COLD_CODE(".flashmem.gpio_clock.runner")
RunResult Runner::run(
    const protocol::GpioClockDiagnosticRequest &request) {
  RunResult result{};
  if (!protocol::validGpioClockDiagnosticRequest(request)) {
    result.status = RunStatus::kInvalidRequest;
    return result;
  }

  const Plan plan = makePlan(request);
  protocol::GpioClockDiagnosticResponse &response = result.response;
  response.configured_rate_hz = plan.rate_hz;
  response.production_rate_hz = protocol_v1::kGpioClockProductionRateHz;
  response.pit_clock_hz = protocol_v1::kGpioClockPitHz;
  response.pit_load_value = plan.pit_load_value;
  response.requested_event_count = plan.requested_event_count;
  if (!platform_.execute(plan, response)) {
    result.status = RunStatus::kPlatformUnavailable;
    return result;
  }

  if ((response.hardware_error_flags &
       errorBit(protocol_v1::GpioClockError::kResourceBusy)) != 0U) {
    result.status = RunStatus::kOk;
    return result;
  }
  if (response.dwt_counter_hz != input_experiment::kCpuHz ||
      response.dwt_elapsed_cycles == 0U) {
    response.hardware_error_flags |=
        errorBit(protocol_v1::GpioClockError::kDwtUnavailable);
    result.status = RunStatus::kOk;
    return result;
  } else {
    response.scheduled_event_count =
        static_cast<std::uint32_t>(
            static_cast<std::uint64_t>(response.dwt_elapsed_cycles) * plan.rate_hz /
            input_experiment::kCpuHz);
  }

  const std::uint32_t sample_count = response.dma_sample_count;
  const std::uint32_t scheduled_count = response.scheduled_event_count;
  if (sample_count == 0U && scheduled_count != 0U) {
    response.hardware_error_flags |=
        errorBit(protocol_v1::GpioClockError::kDeadTrigger);
  }
  if (sample_count >
      scheduled_count + protocol_v1::kGpioClockCountTolerance) {
    response.hardware_error_flags |=
        errorBit(protocol_v1::GpioClockError::kDuplicateTrigger);
  }
  if (absoluteDifference(sample_count, scheduled_count) >
          protocol_v1::kGpioClockCountTolerance ||
      absoluteDifference(scheduled_count, plan.requested_event_count) >
          protocol_v1::kGpioClockCountTolerance) {
    response.hardware_error_flags |=
        errorBit(protocol_v1::GpioClockError::kCountOutOfTolerance);
  }
  if (response.tcd_biter != plan.tcd_major_count ||
      response.tcd_citer_final > response.tcd_biter ||
      sample_count > response.tcd_biter) {
    response.hardware_error_flags |=
        errorBit(protocol_v1::GpioClockError::kMeasurementOverflow);
  }

  result.status = RunStatus::kOk;
  return result;
}

static_assert(protocol_v1::kGpioClockPitHz /
                      protocol_v1::kGpioClockProductionRateHz ==
                  6U,
              "4 MHz production clock requires six 24 MHz PIT ticks");
static_assert(protocol_v1::kGpioClockPitHz %
                      protocol_v1::kGpioClockProductionRateHz ==
                  0U);
static_assert(2U * protocol_v1::kGpioClockMaxEventCount +
                      protocol_v1::kGpioClockDuplicateGuardEvents <=
                  std::numeric_limits<std::int16_t>::max());

}  // namespace thingdaq::gpio_clock

#undef THINGDAQ_GPIO_CLOCK_COLD_CODE
