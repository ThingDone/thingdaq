#include <cstdint>
#include <iostream>
#include <string>

#define ARDUINO_TEENSY40 1
#define __IMXRT1062__ 1
#define THINGDAQ_HOST_REGISTER_TEST 1

#include <core_pins.h>

// White-box inclusion exercises the production clock/TEMPMON adapter against
// the same narrow fake-register surface as the ADC and PIT adapter tests.
#include "../src/clock_health_teensy.cpp"

namespace {

namespace health = thingdaq::clock_health;
namespace identity = thingdaq::identity;
namespace route = thingdaq::gpio_dma_route;
namespace v1 = thingdaq::protocol_v1;

int failures = 0;

constexpr std::uint32_t error(v1::ClockHealthError value) {
  return static_cast<std::uint32_t>(value);
}

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

void resetClockRegisters() {
  fake_imxrt::f_cpu_actual = identity::kExpectedCpuHz;
  fake_imxrt::f_bus_actual = identity::kExpectedIpgHz;
  fake_imxrt::ccm_cscmr1 = route::kPerclk24M;
  fake_imxrt::ccm_ccgr1 =
      CCM_CCGR1_ADC1(CCM_CCGR_ON) | CCM_CCGR1_ADC2(CCM_CCGR_ON);
  fake_imxrt::adc1.CFG.reset(ADC_CFG_ADIV(1U) | ADC_CFG_ADICLK(1U));
  fake_imxrt::adc2.CFG.reset(ADC_CFG_ADIV(1U) | ADC_CFG_ADICLK(1U));
  fake_imxrt::arm_demcr = 0U;
  fake_imxrt::arm_dwt_ctrl = 0U;
  fake_imxrt::arm_dwt_cyccnt = 0U;
  fake_imxrt::tempmon_tempsense0 = TEMPMON_CTRL0_POWER_DOWN;
  fake_imxrt::hw_ocotp_ana1 = 0U;
}

std::uint32_t calibration(std::uint32_t hot_temperature,
                          std::uint32_t hot_count,
                          std::uint32_t room_count) {
  return (hot_temperature & 0xFFU) | ((hot_count & 0xFFFU) << 8U) |
         ((room_count & 0xFFFU) << 20U);
}

std::uint32_t temperatureControl(std::uint32_t measured_count,
                                 bool finished) {
  return TEMPMON_CTRL0_MEASURE_TEMP |
         (finished ? TEMPMON_CTRL0_FINISHED : 0U) |
         ((measured_count & 0xFFFU) << 8U);
}

void testExactProfileClockReadbacksAndMismatches() {
  resetClockRegisters();
  health::Hardware &hardware = health::teensyHardware();
  const health::HardwareReadback matching = hardware.sampleHardware();
  expect(matching.cpu_clock_hz == identity::kExpectedCpuHz &&
             matching.ipg_clock_hz == identity::kExpectedIpgHz &&
             matching.adc_clock_hz == identity::kExpectedAdcClockHz &&
             matching.pit_clock_hz == identity::kExpectedPitHz,
         "target adapter reports the exact selected CPU/IPG/ADC/PIT profile");
  expect((matching.error_flags &
          (error(v1::ClockHealthError::kCpuClockMismatch) |
           error(v1::ClockHealthError::kIpgClockMismatch) |
           error(v1::ClockHealthError::kAdcClockMismatch) |
           error(v1::ClockHealthError::kPitClockMismatch))) == 0U,
         "matching target clock-tree readbacks carry no mismatch error");

  fake_imxrt::f_cpu_actual = identity::kExpectedCpuHz - 1U;
  fake_imxrt::f_bus_actual = identity::kExpectedIpgHz - 1U;
  fake_imxrt::ccm_cscmr1 = 0U;
  fake_imxrt::ccm_ccgr1 = 0U;
  fake_imxrt::adc1.CFG.reset(0U);
  fake_imxrt::adc2.CFG.reset(0U);
  const health::HardwareReadback mismatched = hardware.sampleHardware();
  const std::uint32_t required =
      error(v1::ClockHealthError::kCpuClockMismatch) |
      error(v1::ClockHealthError::kIpgClockMismatch) |
      error(v1::ClockHealthError::kAdcClockMismatch) |
      error(v1::ClockHealthError::kPitClockMismatch) |
      error(v1::ClockHealthError::kDwtUnavailable);
  expect((mismatched.error_flags & required) == required &&
             mismatched.adc_clock_hz == 0U &&
             mismatched.pit_clock_hz == 0U,
         "every contradictory target clock readback fails explicitly");
}

void testTemperatureUnavailableInvalidTimeoutAndBounds() {
  resetClockRegisters();
  health::Hardware &hardware = health::teensyHardware();

  health::HardwareReadback sample = hardware.sampleHardware();
  expect(sample.temperature_status == v1::TemperatureStatus::kUnavailable &&
             (sample.error_flags &
              error(v1::ClockHealthError::kTemperatureUnavailable)) != 0U,
         "powered-down TEMPMON is explicitly unavailable");

  fake_imxrt::tempmon_tempsense0 = temperatureControl(1500U, true);
  fake_imxrt::hw_ocotp_ana1 = calibration(25U, 1000U, 2000U);
  sample = hardware.sampleHardware();
  expect(sample.temperature_status ==
                 v1::TemperatureStatus::kInvalidCalibration &&
             (sample.error_flags &
              error(v1::ClockHealthError::kTemperatureCalibrationInvalid)) !=
                 0U,
         "invalid fuse calibration is rejected before conversion");

  fake_imxrt::tempmon_tempsense0 = temperatureControl(1500U, false);
  fake_imxrt::hw_ocotp_ana1 = calibration(105U, 1000U, 2000U);
  sample = hardware.sampleHardware();
  expect(sample.temperature_status == v1::TemperatureStatus::kNotReady &&
             (sample.error_flags &
              error(v1::ClockHealthError::kTemperatureNotReady)) != 0U,
         "a sensor that never finishes exits through the finite poll bound");

  fake_imxrt::tempmon_tempsense0 = temperatureControl(1500U, true);
  sample = hardware.sampleHardware();
  expect(sample.temperature_status == v1::TemperatureStatus::kValid &&
             sample.temperature_millidegrees_celsius == 65000,
         "valid calibrated TEMPMON data preserves integer milli-degrees");

  fake_imxrt::tempmon_tempsense0 = temperatureControl(4095U, true);
  sample = hardware.sampleHardware();
  expect(sample.temperature_status == v1::TemperatureStatus::kOutOfRange &&
             sample.temperature_millidegrees_celsius == 0 &&
             (sample.error_flags &
              error(v1::ClockHealthError::kTemperatureOutOfRange)) != 0U,
         "a finite but implausible converted value is not published");
}

}  // namespace

int main() {
  testExactProfileClockReadbacksAndMismatches();
  testTemperatureUnavailableInvalidTimeoutAndBounds();
  if (failures != 0) {
    std::cerr << failures << " target clock-health assertion(s) failed\n";
    return 1;
  }
  return 0;
}
