#include "adc_initializer.h"

#include <array>

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_ADC_INIT_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_ADC_INIT_COLD_CODE(section_name)
#endif

namespace teensy_daq::adc {
namespace {

constexpr protocol_v1::AdcInitializationError routeError(std::size_t index) {
  return index == 0U
             ? protocol_v1::AdcInitializationError::kAdc0RouteInvalid
             : protocol_v1::AdcInitializationError::kAdc1RouteInvalid;
}

constexpr protocol_v1::AdcInitializationError configurationError(
    std::size_t index) {
  return index == 0U
             ? protocol_v1::AdcInitializationError::kAdc0ConfigurationInvalid
             : protocol_v1::AdcInitializationError::kAdc1ConfigurationInvalid;
}

constexpr protocol_v1::AdcInitializationError calibrationError(
    std::size_t index) {
  return index == 0U
             ? protocol_v1::AdcInitializationError::kAdc0CalibrationFailed
             : protocol_v1::AdcInitializationError::kAdc1CalibrationFailed;
}

constexpr protocol_v1::AdcInitializationError timeoutError(
    std::size_t index) {
  return index == 0U
             ? protocol_v1::AdcInitializationError::kAdc0CalibrationTimeout
             : protocol_v1::AdcInitializationError::kAdc1CalibrationTimeout;
}

constexpr protocol_v1::AdcInitializationError readbackError(
    std::size_t index) {
  return index == 0U
             ? protocol_v1::AdcInitializationError::kAdc0ReadbackInvalid
             : protocol_v1::AdcInitializationError::kAdc1ReadbackInvalid;
}

void addError(Snapshot &snapshot,
              protocol_v1::AdcInitializationError error) {
  snapshot.initialization_error_flags |= initializationError(error);
}

}  // namespace

TEENSY_DAQ_ADC_INIT_COLD_CODE(".flashmem.adc_init.metadata")
protocol::AdcInitializationMetadata protocolMetadata(
    const Snapshot &snapshot) {
  protocol::AdcInitializationMetadata metadata{};
  metadata.resolution_bits = snapshot.settings.resolution_bits;
  metadata.container_bytes = snapshot.settings.container_bytes;
  metadata.code_min = snapshot.settings.code_min;
  metadata.code_max = snapshot.settings.code_max;
  metadata.reference = snapshot.settings.reference;
  metadata.clock_source = snapshot.settings.clock_source;
  metadata.clock_divider = snapshot.settings.clock_divider;
  metadata.hardware_average_count =
      snapshot.settings.hardware_average_count;
  metadata.reference_mv_nominal = snapshot.settings.reference_mv_nominal;
  metadata.input_min_mv_nominal = snapshot.settings.input_min_mv_nominal;
  metadata.input_max_mv_nominal = snapshot.settings.input_max_mv_nominal;
  metadata.sample_time_adck = snapshot.settings.sample_time_adck;
  metadata.conversion_mode = snapshot.settings.conversion_mode;
  metadata.configuration_flags = snapshot.configuration_flags;
  metadata.ipg_clock_hz = snapshot.settings.ipg_clock_hz;
  metadata.adc_clock_hz = snapshot.settings.adc_clock_hz;
  metadata.calibration_deadline_us =
      snapshot.settings.calibration_deadline_us;
  metadata.initialization_error_flags =
      snapshot.initialization_error_flags;
  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    metadata.calibration_states[index] =
        snapshot.converters[index].calibration_state;
    metadata.pins[index] =
        board::kAdcConverterConfigurations[index].teensy_pin;
    metadata.peripherals[index] =
        board::kAdcConverterConfigurations[index].adc_peripheral;
    metadata.channels[index] =
        board::kAdcConverterConfigurations[index].input_channel;
    metadata.calibration_cycles[index] =
        snapshot.converters[index].calibration_cycles;
  }
  return metadata;
}

TEENSY_DAQ_ADC_INIT_COLD_CODE(".flashmem.adc_init.initialize")
const Snapshot &Initializer::initialize() {
  snapshot_ = defaultSnapshot(gate_);
  std::array<bool, kConverterCount> route_valid{};
  std::array<bool, kConverterCount> prepared{};
  std::array<bool, kConverterCount> active{};
  std::array<bool, kConverterCount> readback_valid{};
  std::array<std::uint32_t, kConverterCount> started_cycles{};

  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    const PrepareStatus status = platform_.prepareConverter(
        board::kAdcConverterConfigurations[index], snapshot_.settings);
    route_valid[index] = status != PrepareStatus::kRouteInvalid;
    prepared[index] = status == PrepareStatus::kOk;
    if (status == PrepareStatus::kRouteInvalid) {
      snapshot_.converters[index].calibration_state =
          protocol_v1::AdcCalibrationState::kRouteInvalid;
      addError(snapshot_, routeError(index));
    } else if (status == PrepareStatus::kConfigurationInvalid) {
      snapshot_.converters[index].calibration_state =
          protocol_v1::AdcCalibrationState::kConfigurationInvalid;
      addError(snapshot_, configurationError(index));
    }
  }
  if (route_valid[0] && route_valid[1]) {
    snapshot_.configuration_flags |= configurationFlag(
        protocol_v1::AdcConfigurationFlag::kRoutesValidated);
  }

  std::uint32_t counter_hz = 0U;
  if (!platform_.beginCycleCounter(counter_hz) ||
      counter_hz != protocol_v1::kAdcCalibrationCycleCounterHz) {
    addError(snapshot_, protocol_v1::AdcInitializationError::kDwtUnavailable);
    for (std::size_t index = 0U; index < kConverterCount; ++index) {
      if (prepared[index]) {
        snapshot_.converters[index].calibration_state =
            protocol_v1::AdcCalibrationState::kClockUnavailable;
      }
    }
    return snapshot_;
  }

  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    if (!prepared[index]) {
      continue;
    }
    started_cycles[index] = platform_.readCycles();
    if (!platform_.startCalibration(
            board::kAdcConverterConfigurations[index])) {
      snapshot_.converters[index].calibration_state =
          protocol_v1::AdcCalibrationState::kFailed;
      addError(snapshot_, calibrationError(index));
      continue;
    }
    active[index] = true;
  }

  for (std::uint32_t poll = 0U;
       poll < protocol_v1::kAdcCalibrationPollLimit &&
       (active[0] || active[1]);
       ++poll) {
    for (std::size_t index = 0U; index < kConverterCount; ++index) {
      if (!active[index]) {
        continue;
      }
      const auto &route = board::kAdcConverterConfigurations[index];
      const std::uint32_t now = platform_.readCycles();
      const std::uint32_t elapsed = now - started_cycles[index];
      if (!platform_.calibrationActive(route)) {
        snapshot_.converters[index].calibration_cycles = elapsed;
        active[index] = false;
        if (platform_.calibrationFailed(route)) {
          snapshot_.converters[index].calibration_state =
              protocol_v1::AdcCalibrationState::kFailed;
          addError(snapshot_, calibrationError(index));
          continue;
        }
        readback_valid[index] =
            platform_.verifyConverter(route, snapshot_.settings);
        if (!readback_valid[index]) {
          snapshot_.converters[index].calibration_state =
              protocol_v1::AdcCalibrationState::kConfigurationInvalid;
          addError(snapshot_, readbackError(index));
          continue;
        }
        snapshot_.converters[index].calibration_state =
            protocol_v1::AdcCalibrationState::kSucceeded;
        continue;
      }
      if (elapsed >= kCalibrationDeadlineCycles) {
        platform_.abortCalibration(route);
        snapshot_.converters[index].calibration_cycles = elapsed;
        snapshot_.converters[index].calibration_state =
            protocol_v1::AdcCalibrationState::kTimedOut;
        active[index] = false;
        addError(snapshot_, timeoutError(index));
      }
    }
  }

  // The independent poll limit remains a hard bound even if a broken cycle
  // counter stops advancing after its initial availability probe.
  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    if (!active[index]) {
      continue;
    }
    const auto &route = board::kAdcConverterConfigurations[index];
    const std::uint32_t elapsed = platform_.readCycles() - started_cycles[index];
    platform_.abortCalibration(route);
    snapshot_.converters[index].calibration_cycles = elapsed;
    snapshot_.converters[index].calibration_state =
        protocol_v1::AdcCalibrationState::kTimedOut;
    addError(snapshot_, timeoutError(index));
  }

  if (readback_valid[0] && readback_valid[1]) {
    snapshot_.configuration_flags |= configurationFlag(
        protocol_v1::AdcConfigurationFlag::kConfigurationReadbackValid);
  }
  const bool calibration_complete =
      snapshot_.converters[0].calibration_state ==
          protocol_v1::AdcCalibrationState::kSucceeded &&
      snapshot_.converters[1].calibration_state ==
          protocol_v1::AdcCalibrationState::kSucceeded;
  if (calibration_complete) {
    snapshot_.configuration_flags = static_cast<std::uint16_t>(
        snapshot_.configuration_flags |
        configurationFlag(
            protocol_v1::AdcConfigurationFlag::kCalibrationComplete) |
        configurationFlag(protocol_v1::AdcConfigurationFlag::kInitialized));
  }
  return snapshot_;
}

}  // namespace teensy_daq::adc

#undef TEENSY_DAQ_ADC_INIT_COLD_CODE
