#include "clock_health.h"

#include <limits>

#include "firmware_identity.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_CLOCK_HEALTH_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_CLOCK_HEALTH_COLD_CODE(section_name)
#endif

namespace thingdaq::clock_health {
namespace {

constexpr std::uint16_t flag(protocol_v1::ClockHealthFlag value) {
  return static_cast<std::uint16_t>(value);
}

constexpr std::uint32_t error(protocol_v1::ClockHealthError value) {
  return static_cast<std::uint32_t>(value);
}

constexpr std::uint32_t kClockErrorMask =
    error(protocol_v1::ClockHealthError::kCpuClockMismatch) |
    error(protocol_v1::ClockHealthError::kIpgClockMismatch) |
    error(protocol_v1::ClockHealthError::kAdcClockMismatch) |
    error(protocol_v1::ClockHealthError::kPitClockMismatch) |
    error(protocol_v1::ClockHealthError::kDwtUnavailable) |
    error(protocol_v1::ClockHealthError::kPhaseMismatch);

}  // namespace

THINGDAQ_CLOCK_HEALTH_COLD_CODE(".flashmem.clock_health.begin")
bool Monitor::begin(std::uint64_t now_ticks) {
  if (initialized_) {
    return cycle_counter_available_;
  }
  cycle_counter_available_ = hardware_.beginCycleCounter();
  last_sample_ticks_ = now_ticks;
  initialized_ = true;
  if (!cycle_counter_available_) {
    saturatingIncrement(service_counter_error_count_);
  }
  return cycle_counter_available_;
}

void Monitor::beginAcquisitionService() {
  beginService(Service::kAcquisition);
}

void Monitor::endAcquisitionService() { endService(Service::kAcquisition); }

void Monitor::beginUsbService() { beginService(Service::kUsb); }

void Monitor::endUsbService() { endService(Service::kUsb); }

void Monitor::beginService(Service service) {
  if (!initialized_ || !cycle_counter_available_) {
    return;
  }
  bool &active = service == Service::kAcquisition ? acquisition_active_
                                                  : usb_active_;
  std::uint32_t &start = service == Service::kAcquisition
                             ? acquisition_start_
                             : usb_start_;
  if (active) {
    saturatingIncrement(service_counter_error_count_);
    return;
  }
  start = hardware_.cycleCount();
  active = true;
}

void Monitor::endService(Service service) {
  if (!initialized_ || !cycle_counter_available_) {
    return;
  }
  bool &active = service == Service::kAcquisition ? acquisition_active_
                                                  : usb_active_;
  const std::uint32_t start = service == Service::kAcquisition
                                  ? acquisition_start_
                                  : usb_start_;
  if (!active) {
    saturatingIncrement(service_counter_error_count_);
    return;
  }
  const std::uint32_t elapsed = hardware_.cycleCount() - start;
  if (service == Service::kAcquisition) {
    saturatingAdd(acquisition_cycles_, elapsed);
  } else {
    saturatingAdd(usb_cycles_, elapsed);
  }
  active = false;
}

THINGDAQ_CLOCK_HEALTH_COLD_CODE(".flashmem.clock_health.sample")
protocol::ClockHealthSample Monitor::sample(std::uint64_t now_ticks) {
  protocol::ClockHealthSample result{};
  if (!initialized_) {
    (void)begin(now_ticks);
  }
  if (acquisition_active_ || usb_active_) {
    saturatingIncrement(service_counter_error_count_);
    acquisition_active_ = false;
    usb_active_ = false;
  }

  ++sample_sequence_;
  if (sample_sequence_ == 0U) {
    sample_sequence_ = 1U;
  }
  result.sample_sequence = sample_sequence_;
  result.sample_ticks = now_ticks;

  const HardwareReadback readback = hardware_.sampleHardware();
  result.runtime_cpu_clock_hz = readback.cpu_clock_hz;
  result.runtime_ipg_clock_hz = readback.ipg_clock_hz;
  result.runtime_adc_clock_hz = readback.adc_clock_hz;
  result.runtime_pit_clock_hz = readback.pit_clock_hz;
  result.runtime_dwt_clock_hz = readback.dwt_clock_hz;
  result.temperature_status = readback.temperature_status;
  result.temperature_millidegrees_celsius =
      readback.temperature_millidegrees_celsius;
  result.error_flags = readback.error_flags;

  const bool clocks_valid =
      result.runtime_cpu_clock_hz == identity::kExpectedCpuHz &&
      result.runtime_ipg_clock_hz == identity::kExpectedIpgHz &&
      result.runtime_adc_clock_hz == identity::kExpectedAdcClockHz &&
      result.runtime_pit_clock_hz == identity::kExpectedPitHz &&
      result.runtime_dwt_clock_hz == identity::kExpectedDwtHz &&
      (result.error_flags & kClockErrorMask) == 0U;
  if (clocks_valid) {
    result.flags |= flag(protocol_v1::ClockHealthFlag::kClocksValid);
  } else {
    result.flags = static_cast<std::uint16_t>(
        result.flags & ~flag(protocol_v1::ClockHealthFlag::kClocksValid));
    saturatingIncrement(clock_mismatch_count_);
  }

  const bool temperature_valid =
      result.temperature_status == protocol_v1::TemperatureStatus::kValid &&
      result.temperature_millidegrees_celsius >=
          protocol_v1::kTemperatureMinMillidegreesCelsius &&
      result.temperature_millidegrees_celsius <=
          protocol_v1::kTemperatureMaxMillidegreesCelsius;
  if (temperature_valid) {
    result.flags |= flag(protocol_v1::ClockHealthFlag::kTemperatureValid);
  } else {
    switch (result.temperature_status) {
      case protocol_v1::TemperatureStatus::kUnavailable:
        result.error_flags |=
            error(protocol_v1::ClockHealthError::kTemperatureUnavailable);
        break;
      case protocol_v1::TemperatureStatus::kNotReady:
        result.error_flags |=
            error(protocol_v1::ClockHealthError::kTemperatureNotReady);
        break;
      case protocol_v1::TemperatureStatus::kInvalidCalibration:
        result.error_flags |= error(
            protocol_v1::ClockHealthError::kTemperatureCalibrationInvalid);
        break;
      case protocol_v1::TemperatureStatus::kOutOfRange:
      case protocol_v1::TemperatureStatus::kValid:
        result.temperature_status =
            protocol_v1::TemperatureStatus::kOutOfRange;
        result.error_flags |=
            error(protocol_v1::ClockHealthError::kTemperatureOutOfRange);
        break;
    }
    result.temperature_millidegrees_celsius = 0;
    saturatingIncrement(temperature_error_count_);
  }

  const std::uint64_t interval_ticks = now_ticks - last_sample_ticks_;
  const std::uint64_t interval_cycles =
      (interval_ticks / protocol_v1::kTimestampHz) *
          identity::kExpectedDwtHz +
      (interval_ticks % protocol_v1::kTimestampHz) *
          identity::kExpectedDwtHz / protocol_v1::kTimestampHz;
  if (cycle_counter_available_ && interval_ticks != 0U &&
      interval_cycles != 0U) {
    result.acquisition_service_utilization_basis_points =
        utilizationBasisPoints(acquisition_cycles_, interval_cycles);
    result.usb_service_utilization_basis_points =
        utilizationBasisPoints(usb_cycles_, interval_cycles);
    result.flags |= flag(protocol_v1::ClockHealthFlag::kUtilizationValid);
    result.error_flags &=
        ~error(protocol_v1::ClockHealthError::kUtilizationUnavailable);
  } else {
    result.error_flags |=
        error(protocol_v1::ClockHealthError::kUtilizationUnavailable);
    saturatingIncrement(service_counter_error_count_);
  }

  result.temperature_error_count = temperature_error_count_;
  result.clock_mismatch_count = clock_mismatch_count_;
  result.service_counter_error_count = service_counter_error_count_;
  last_sample_ticks_ = now_ticks;
  acquisition_cycles_ = 0U;
  usb_cycles_ = 0U;
  return result;
}

void Monitor::saturatingIncrement(std::uint32_t &value) {
  if (value != std::numeric_limits<std::uint32_t>::max()) {
    ++value;
  }
}

void Monitor::saturatingAdd(std::uint64_t &value, std::uint32_t increment) {
  if (value > std::numeric_limits<std::uint64_t>::max() - increment) {
    value = std::numeric_limits<std::uint64_t>::max();
  } else {
    value += increment;
  }
}

std::uint16_t Monitor::utilizationBasisPoints(
    std::uint64_t service_cycles, std::uint64_t interval_cycles) {
  if (service_cycles >= interval_cycles) {
    return 10000U;
  }
  return static_cast<std::uint16_t>(
      service_cycles * 10000U / interval_cycles);
}

}  // namespace thingdaq::clock_health
