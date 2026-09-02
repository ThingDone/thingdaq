#include <cstdint>
#include <iostream>

#include "clock_health.h"
#include "firmware_identity.h"

namespace {

using thingdaq::clock_health::HardwareReadback;
using thingdaq::protocol_v1::ClockHealthError;
using thingdaq::protocol_v1::ClockHealthFlag;
using thingdaq::protocol_v1::TemperatureStatus;

int failures = 0;

constexpr std::uint16_t flag(ClockHealthFlag value) {
  return static_cast<std::uint16_t>(value);
}

constexpr std::uint32_t error(ClockHealthError value) {
  return static_cast<std::uint32_t>(value);
}

void expect(bool condition, const char *message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class FakeHardware final : public thingdaq::clock_health::Hardware {
 public:
  bool beginCycleCounter() override { return cycle_counter_available; }
  std::uint32_t cycleCount() const override { return cycle_count; }
  HardwareReadback sampleHardware() override { return readback; }

  bool cycle_counter_available = true;
  std::uint32_t cycle_count = 0U;
  HardwareReadback readback{
      thingdaq::identity::kExpectedCpuHz,
      thingdaq::identity::kExpectedIpgHz,
      thingdaq::identity::kExpectedAdcClockHz,
      thingdaq::identity::kExpectedPitHz,
      thingdaq::identity::kExpectedDwtHz,
      TemperatureStatus::kValid,
      42125,
      0U,
  };
};

void testFiniteValidSample() {
  FakeHardware hardware{};
  thingdaq::clock_health::Monitor monitor{hardware};
  expect(monitor.begin(0U), "cycle counter starts");

  hardware.cycle_count = 100U;
  monitor.beginAcquisitionService();
  hardware.cycle_count = 150100U;
  monitor.endAcquisitionService();
  hardware.cycle_count = 200000U;
  monitor.beginUsbService();
  hardware.cycle_count = 260000U;
  monitor.endUsbService();

  const auto sample = monitor.sample(8000U);
  expect(sample.sample_sequence == 1U, "sample sequence starts nonzero");
  expect(sample.sample_ticks == 8000U, "sample carries protocol ticks");
  expect((sample.flags & flag(ClockHealthFlag::kClocksValid)) != 0U,
         "matching runtime clocks are valid");
  expect((sample.flags & flag(ClockHealthFlag::kTemperatureValid)) != 0U,
         "bounded integer temperature is valid");
  expect((sample.flags & flag(ClockHealthFlag::kUtilizationValid)) != 0U,
         "bounded service-cycle utilization is valid");
  expect(sample.temperature_millidegrees_celsius == 42125,
         "temperature preserves integer milli-degrees");
  const std::uint32_t interval_cycles =
      thingdaq::identity::kExpectedDwtHz / 1000U;
  expect(sample.acquisition_service_utilization_basis_points ==
             150000U * 10000U / interval_cycles,
         "acquisition cycles become basis points");
  expect(sample.usb_service_utilization_basis_points ==
             60000U * 10000U / interval_cycles,
         "USB cycles become basis points");
  expect(sample.error_flags == 0U, "valid sample has no health error");
}

void testExplicitUnavailableAndMismatchState() {
  FakeHardware hardware{};
  hardware.cycle_counter_available = false;
  hardware.readback.cpu_clock_hz =
      thingdaq::identity::kExpectedCpuHz - 1U;
  hardware.readback.dwt_clock_hz = 0U;
  hardware.readback.temperature_status = TemperatureStatus::kNotReady;
  hardware.readback.temperature_millidegrees_celsius = 999999;
  hardware.readback.error_flags =
      error(ClockHealthError::kCpuClockMismatch) |
      error(ClockHealthError::kDwtUnavailable) |
      error(ClockHealthError::kTemperatureNotReady);

  thingdaq::clock_health::Monitor monitor{hardware};
  expect(!monitor.begin(0U), "unavailable DWT is reported without retrying");
  const auto sample = monitor.sample(8000U);
  expect((sample.flags & flag(ClockHealthFlag::kClocksValid)) == 0U,
         "contradictory clocks are invalid");
  expect((sample.flags & flag(ClockHealthFlag::kTemperatureValid)) == 0U,
         "not-ready temperature is invalid");
  expect((sample.flags & flag(ClockHealthFlag::kUtilizationValid)) == 0U,
         "unavailable DWT makes utilization unavailable");
  expect(sample.temperature_millidegrees_celsius == 0,
         "invalid sensor value is not published");
  expect((sample.error_flags & error(ClockHealthError::kTemperatureNotReady)) !=
             0U,
         "temperature status has an explicit error");
  expect((sample.error_flags &
          error(ClockHealthError::kUtilizationUnavailable)) != 0U,
         "utilization has an explicit unavailable error");
  expect(sample.temperature_error_count == 1U,
         "temperature failures are counted");
  expect(sample.clock_mismatch_count == 1U, "clock mismatches are counted");
  expect(sample.service_counter_error_count >= 2U,
         "cycle-counter failures are counted monotonically");
}

}  // namespace

int main() {
  testFiniteValidSample();
  testExplicitUnavailableAndMismatchState();
  if (failures != 0) {
    std::cerr << failures << " clock health assertion(s) failed\n";
    return 1;
  }
  return 0;
}
