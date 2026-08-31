#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "adc_initializer.h"

namespace {

namespace adc = thingdaq::adc;
namespace board = thingdaq::board;
namespace wire = thingdaq::protocol;
namespace v1 = thingdaq::protocol_v1;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

constexpr std::size_t routeIndex(
    const board::AdcConverterConfiguration &route) {
  return route.logical_converter;
}

class FakePlatform final : public adc::Platform {
 public:
  std::array<adc::PrepareStatus, 2U> prepare_status{
      adc::PrepareStatus::kOk,
      adc::PrepareStatus::kOk,
  };
  std::array<bool, 2U> start_ok{true, true};
  std::array<bool, 2U> calibration_failed{false, false};
  std::array<bool, 2U> readback_valid{true, true};
  std::array<std::uint32_t, 2U> active_polls{1U, 2U};
  std::array<std::uint32_t, 2U> active_calls{};
  std::array<std::uint32_t, 2U> prepare_calls{};
  std::array<std::uint32_t, 2U> start_calls{};
  std::array<std::uint32_t, 2U> abort_calls{};
  std::array<board::AdcConverterConfiguration, 2U> observed_routes{};
  std::array<adc::Settings, 2U> observed_settings{};
  bool cycle_counter_available = true;
  std::uint32_t reported_counter_hz =
      v1::kAdcCalibrationCycleCounterHz;
  std::uint32_t cycles = 0U;
  std::uint32_t cycle_step = 100U;

  adc::PrepareStatus prepareConverter(
      const board::AdcConverterConfiguration &route,
      const adc::Settings &settings) override {
    const std::size_t index = routeIndex(route);
    ++prepare_calls[index];
    observed_routes[index] = route;
    observed_settings[index] = settings;
    return prepare_status[index];
  }

  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    frequency_hz = reported_counter_hz;
    return cycle_counter_available;
  }

  std::uint32_t readCycles() override {
    const std::uint32_t result = cycles;
    cycles += cycle_step;
    return result;
  }

  bool startCalibration(
      const board::AdcConverterConfiguration &route) override {
    const std::size_t index = routeIndex(route);
    ++start_calls[index];
    return start_ok[index];
  }

  bool calibrationActive(
      const board::AdcConverterConfiguration &route) override {
    const std::size_t index = routeIndex(route);
    return active_calls[index]++ < active_polls[index];
  }

  bool calibrationFailed(
      const board::AdcConverterConfiguration &route) override {
    return calibration_failed[routeIndex(route)];
  }

  bool verifyConverter(const board::AdcConverterConfiguration &route,
                       const adc::Settings &) override {
    return readback_valid[routeIndex(route)];
  }

  void abortCalibration(
      const board::AdcConverterConfiguration &route) override {
    ++abort_calls[routeIndex(route)];
  }
};

constexpr std::uint16_t flag(v1::AdcConfigurationFlag value) {
  return static_cast<std::uint16_t>(value);
}

constexpr std::uint32_t error(v1::AdcInitializationError value) {
  return static_cast<std::uint32_t>(value);
}

void testPrimaryInitializationAndRoutes() {
  FakePlatform platform{};
  adc::Initializer initializer{platform};
  const adc::Snapshot &snapshot = initializer.initialize();

  expect(snapshot.ready(), "both successful calibrations make ADC ready");
  expect(snapshot.settings.resolution_bits == 12U &&
             snapshot.settings.container_bytes == sizeof(std::uint16_t) &&
             snapshot.settings.code_min == 0U &&
             snapshot.settings.code_max == 4095U,
         "primary acquisition is explicit 12-bit data in uint16 containers");
  expect(snapshot.settings.hardware_average_count == 0U &&
             snapshot.settings.adc_clock_hz == 37500000U &&
             snapshot.settings.sample_time_adck == 3U,
         "initializer uses no averaging and the exact high-speed short sample");
  expect(platform.prepare_calls == std::array<std::uint32_t, 2U>{1U, 1U} &&
             platform.start_calls == std::array<std::uint32_t, 2U>{1U, 1U},
         "both converters are prepared and started independently");
  expect(platform.observed_routes[0].teensy_pin == 14U &&
             platform.observed_routes[0].adc_peripheral == 1U &&
             platform.observed_routes[0].input_channel == 7U &&
             platform.observed_routes[1].teensy_pin == 15U &&
             platform.observed_routes[1].adc_peripheral == 2U &&
             platform.observed_routes[1].input_channel == 8U,
         "logical routes remain ADC0=A0/ADC1/ch7 and ADC1=A1/ADC2/ch8");
  const std::uint16_t ready_flags =
      flag(v1::AdcConfigurationFlag::kInitialized) |
      flag(v1::AdcConfigurationFlag::kRoutesValidated) |
      flag(v1::AdcConfigurationFlag::kConfigurationReadbackValid) |
      flag(v1::AdcConfigurationFlag::kCalibrationComplete);
  expect((snapshot.configuration_flags & ready_flags) == ready_flags &&
             snapshot.initialization_error_flags == 0U,
         "successful initialization reports every verified readiness flag");

  const wire::AdcInitializationMetadata metadata =
      adc::protocolMetadata(snapshot);
  expect(metadata.resolution_bits == 12U && metadata.code_max == 4095U &&
             metadata.calibration_states[0] ==
                 v1::AdcCalibrationState::kSucceeded &&
             metadata.calibration_states[1] ==
                 v1::AdcCalibrationState::kSucceeded &&
             metadata.pins == std::array<std::uint8_t, 2U>{14U, 15U} &&
             metadata.peripherals ==
                 std::array<std::uint8_t, 2U>{1U, 2U} &&
             metadata.channels == std::array<std::uint8_t, 2U>{7U, 8U},
         "wire metadata preserves actual settings, calibration, and routes");
}

void testIndependentFailureAndReadback() {
  FakePlatform platform{};
  platform.calibration_failed[0] = true;
  platform.readback_valid[1] = false;
  platform.active_polls = {0U, 0U};
  adc::Initializer initializer{platform};
  const adc::Snapshot &snapshot = initializer.initialize();

  expect(snapshot.converters[0].calibration_state ==
                 v1::AdcCalibrationState::kFailed &&
             snapshot.converters[1].calibration_state ==
                 v1::AdcCalibrationState::kConfigurationInvalid,
         "each converter retains its own terminal failure state");
  expect((snapshot.initialization_error_flags &
          error(v1::AdcInitializationError::kAdc0CalibrationFailed)) != 0U &&
             (snapshot.initialization_error_flags &
              error(v1::AdcInitializationError::kAdc1ReadbackInvalid)) != 0U &&
             !snapshot.ready(),
         "independent calibration and readback errors are both exposed");
}

void testRouteConfigurationAndClockFailures() {
  FakePlatform platform{};
  platform.prepare_status = {adc::PrepareStatus::kRouteInvalid,
                             adc::PrepareStatus::kConfigurationInvalid};
  adc::Initializer initializer{platform};
  const adc::Snapshot &snapshot = initializer.initialize();
  expect(snapshot.converters[0].calibration_state ==
                 v1::AdcCalibrationState::kRouteInvalid &&
             snapshot.converters[1].calibration_state ==
                 v1::AdcCalibrationState::kConfigurationInvalid &&
             platform.start_calls ==
                 std::array<std::uint32_t, 2U>{0U, 0U},
         "invalid route/configuration never starts calibration");

  FakePlatform no_counter{};
  no_counter.cycle_counter_available = false;
  adc::Initializer no_counter_initializer{no_counter};
  const adc::Snapshot &no_counter_snapshot =
      no_counter_initializer.initialize();
  expect(no_counter_snapshot.converters[0].calibration_state ==
                 v1::AdcCalibrationState::kClockUnavailable &&
             no_counter_snapshot.converters[1].calibration_state ==
                 v1::AdcCalibrationState::kClockUnavailable &&
             no_counter.start_calls ==
                 std::array<std::uint32_t, 2U>{0U, 0U} &&
             (no_counter_snapshot.initialization_error_flags &
             error(v1::AdcInitializationError::kDwtUnavailable)) != 0U,
         "unavailable deadline clock fails closed without starting either ADC");

  FakePlatform wrong_frequency{};
  wrong_frequency.reported_counter_hz = 599999999U;
  adc::Initializer wrong_frequency_initializer{wrong_frequency};
  const adc::Snapshot &wrong_frequency_snapshot =
      wrong_frequency_initializer.initialize();
  expect(wrong_frequency_snapshot.converters[0].calibration_state ==
                 v1::AdcCalibrationState::kClockUnavailable &&
             wrong_frequency_snapshot.converters[1].calibration_state ==
                 v1::AdcCalibrationState::kClockUnavailable &&
             wrong_frequency.start_calls ==
                 std::array<std::uint32_t, 2U>{0U, 0U},
         "an unexpected deadline-counter frequency fails closed");
}

void testIndependentTimeoutAndCycleWrap() {
  FakePlatform platform{};
  platform.active_polls = {100U, 0U};
  platform.cycle_step = 3000000U;
  adc::Initializer initializer{platform};
  const adc::Snapshot &snapshot = initializer.initialize();
  expect(snapshot.converters[0].calibration_state ==
                 v1::AdcCalibrationState::kTimedOut &&
             snapshot.converters[1].calibration_state ==
                 v1::AdcCalibrationState::kSucceeded &&
             platform.abort_calls ==
                 std::array<std::uint32_t, 2U>{1U, 0U},
         "one timed-out converter is aborted without hiding peer success");

  FakePlatform wrapped{};
  wrapped.cycles = std::numeric_limits<std::uint32_t>::max() - 50U;
  wrapped.cycle_step = 100U;
  wrapped.active_polls = {0U, 0U};
  adc::Initializer wrapped_initializer{wrapped};
  const adc::Snapshot &wrapped_snapshot = wrapped_initializer.initialize();
  expect(wrapped_snapshot.ready() &&
             wrapped_snapshot.converters[0].calibration_cycles < 1000U &&
             wrapped_snapshot.converters[1].calibration_cycles < 1000U,
         "unsigned DWT subtraction remains bounded across counter wrap");
}

void testFallbackGatePolicy() {
  adc::ResolutionGate incomplete{};
  expect(adc::selectResolution(incomplete) == 12U,
         "incomplete validation never authorizes fallback");

  adc::ResolutionGate passing{true, true, true, true, true, true};
  expect(adc::selectResolution(passing) == 12U,
         "a passing corrected full-rate gate retains primary 12-bit mode");

  adc::ResolutionGate timing_failure = passing;
  timing_failure.timing_within_budget = false;
  expect(adc::selectResolution(timing_failure) == 10U,
         "a completed corrected timing failure authorizes 10-bit fallback");

  adc::ResolutionGate error_failure = passing;
  error_failure.error_free = false;
  expect(adc::selectResolution(error_failure) == 10U,
         "a completed corrected error gate authorizes 10-bit fallback");

  timing_failure.calibration_verified = false;
  expect(adc::selectResolution(timing_failure) == 12U,
         "missing calibration evidence cannot silently downgrade resolution");

  FakePlatform fallback_platform{};
  adc::Initializer fallback_initializer{fallback_platform, error_failure};
  const adc::Snapshot &fallback = fallback_initializer.initialize();
  expect(fallback.settings.resolution_bits == 10U &&
             fallback.settings.code_max == 1023U &&
             fallback.settings.conversion_mode == 1U &&
             (fallback.configuration_flags &
              flag(v1::AdcConfigurationFlag::kFallback10Bit)) != 0U &&
             (fallback.configuration_flags &
              flag(v1::AdcConfigurationFlag::kPrimary12Bit)) == 0U,
         "authorized fallback is fully and unambiguously advertised");
}

void testEveryFallbackGateCombination() {
  constexpr std::uint16_t primary_flag =
      flag(v1::AdcConfigurationFlag::kPrimary12Bit);
  constexpr std::uint16_t fallback_flag =
      flag(v1::AdcConfigurationFlag::kFallback10Bit);
  for (std::uint32_t mask = 0U; mask < 64U; ++mask) {
    const adc::ResolutionGate gate{
        (mask & (1U << 0U)) != 0U,
        (mask & (1U << 1U)) != 0U,
        (mask & (1U << 2U)) != 0U,
        (mask & (1U << 3U)) != 0U,
        (mask & (1U << 4U)) != 0U,
        (mask & (1U << 5U)) != 0U,
    };
    const bool fallback_authorized =
        gate.completed && gate.configuration_corrected &&
        gate.exact_rate_verified && gate.calibration_verified &&
        (!gate.timing_within_budget || !gate.error_free);
    const std::uint8_t expected_resolution =
        fallback_authorized ? v1::kAdcFallbackResolutionBits
                            : v1::kAdcPrimaryResolutionBits;
    const adc::Settings settings = adc::settingsFor(gate);
    const adc::Snapshot snapshot = adc::defaultSnapshot(gate);
    const bool primary_advertised =
        (snapshot.configuration_flags & primary_flag) != 0U;
    const bool fallback_advertised =
        (snapshot.configuration_flags & fallback_flag) != 0U;

    expect(adc::selectResolution(gate) == expected_resolution &&
               settings.resolution_bits == expected_resolution &&
               settings.code_max == adc::codeMaximum(expected_resolution) &&
               settings.conversion_mode ==
                   adc::conversionMode(expected_resolution),
           "all 64 fallback evidence combinations select one deterministic format");
    expect(primary_advertised != fallback_advertised &&
               fallback_advertised == fallback_authorized,
           "every fallback combination advertises exactly the selected resolution");
  }
}

void testFrozenCounterPollLimit() {
  FakePlatform platform{};
  platform.active_polls = {std::numeric_limits<std::uint32_t>::max(), 0U};
  platform.cycle_step = 0U;
  adc::Initializer initializer{platform};
  const adc::Snapshot &snapshot = initializer.initialize();

  expect(snapshot.converters[0].calibration_state ==
                 v1::AdcCalibrationState::kTimedOut &&
             snapshot.converters[1].calibration_state ==
                 v1::AdcCalibrationState::kSucceeded &&
             platform.active_calls[0] == v1::kAdcCalibrationPollLimit &&
             platform.abort_calls ==
                 std::array<std::uint32_t, 2U>{1U, 0U},
         "the finite poll ceiling terminates one frozen calibration independently");
}

}  // namespace

int main() {
  testPrimaryInitializationAndRoutes();
  testIndependentFailureAndReadback();
  testRouteConfigurationAndClockFailures();
  testIndependentTimeoutAndCycleWrap();
  testFallbackGatePolicy();
  testEveryFallbackGateCombination();
  testFrozenCounterPollLimit();
  if (failures != 0) {
    std::cerr << failures << " ADC initializer assertion(s) failed\n";
    return 1;
  }
  std::cout << "ADC initializer tests passed\n";
  return 0;
}
