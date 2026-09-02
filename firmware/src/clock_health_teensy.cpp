#include "clock_health_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstdint>

#include <imxrt.h>

#include "firmware_identity.h"
#include "gpio_dma_route_teensy.h"

#define THINGDAQ_CLOCK_HEALTH_TEENSY_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::clock_health {
namespace {

constexpr std::uint32_t error(protocol_v1::ClockHealthError value) {
  return static_cast<std::uint32_t>(value);
}

constexpr std::uint32_t kAdcClockConfigurationMask =
    ADC_CFG_ADIV(3U) | ADC_CFG_ADICLK(3U);
constexpr std::uint32_t kAdcClockConfiguration =
    ADC_CFG_ADIV(1U) | ADC_CFG_ADICLK(1U);
constexpr std::uint32_t kAdcClockGateMask =
    CCM_CCGR1_ADC1(CCM_CCGR_ON) | CCM_CCGR1_ADC2(CCM_CCGR_ON);

class TeensyHardware final : public Hardware {
 public:
  THINGDAQ_CLOCK_HEALTH_TEENSY_COLD_CODE(
      ".flashmem.clock_health.begin_cycle_counter")
  bool beginCycleCounter() override {
    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    const std::uint32_t before = ARM_DWT_CYCCNT;
    for (std::uint32_t index = 0U; index < 32U; ++index) {
      __asm__ volatile("nop");
    }
    cycle_counter_available_ = ARM_DWT_CYCCNT != before;
    return cycle_counter_available_;
  }

  std::uint32_t cycleCount() const override { return ARM_DWT_CYCCNT; }

  THINGDAQ_CLOCK_HEALTH_TEENSY_COLD_CODE(
      ".flashmem.clock_health.sample_hardware")
  HardwareReadback sampleHardware() override {
    HardwareReadback result{};
    result.cpu_clock_hz = F_CPU_ACTUAL;
    result.ipg_clock_hz = F_BUS_ACTUAL;
    if (result.cpu_clock_hz != identity::kExpectedCpuHz) {
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kCpuClockMismatch);
    }
    if (result.ipg_clock_hz != identity::kExpectedIpgHz) {
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kIpgClockMismatch);
    }

    if ((CCM_CSCMR1 & gpio_dma_route::kPerclkMask) ==
        gpio_dma_route::kPerclk24M) {
      result.pit_clock_hz = identity::kExpectedPitHz;
    } else {
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kPitClockMismatch);
    }

    const bool adc_clock_valid =
        (CCM_CCGR1 & kAdcClockGateMask) == kAdcClockGateMask &&
        (IMXRT_ADC1.CFG & kAdcClockConfigurationMask) ==
            kAdcClockConfiguration &&
        (IMXRT_ADC2.CFG & kAdcClockConfigurationMask) ==
            kAdcClockConfiguration &&
        F_BUS_ACTUAL == identity::kExpectedIpgHz;
    if (adc_clock_valid) {
      result.adc_clock_hz = F_BUS_ACTUAL / identity::kExpectedAdcClockDivider;
    } else {
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kAdcClockMismatch);
    }

    if (cycle_counter_available_ &&
        F_CPU_ACTUAL == identity::kExpectedDwtHz) {
      result.dwt_clock_hz = identity::kExpectedDwtHz;
    } else {
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kDwtUnavailable);
    }
    sampleTemperature(result);
    return result;
  }

 private:
  void sampleTemperature(HardwareReadback &result) const {
    const std::uint32_t control = TEMPMON_TEMPSENSE0;
    if ((control & TEMPMON_CTRL0_POWER_DOWN) != 0U ||
        (control & TEMPMON_CTRL0_MEASURE_TEMP) == 0U) {
      result.temperature_status =
          protocol_v1::TemperatureStatus::kUnavailable;
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kTemperatureUnavailable);
      return;
    }

    const std::uint32_t calibration = HW_OCOTP_ANA1;
    const std::int32_t hot_temperature =
        static_cast<std::int32_t>(calibration & 0xFFU);
    const std::int32_t hot_count =
        static_cast<std::int32_t>((calibration >> 8U) & 0xFFFU);
    const std::int32_t room_count =
        static_cast<std::int32_t>((calibration >> 20U) & 0xFFFU);
    if (hot_temperature <= 25 || hot_temperature > 150 || hot_count == 0 ||
        room_count == 0 || room_count == hot_count) {
      result.temperature_status =
          protocol_v1::TemperatureStatus::kInvalidCalibration;
      result.error_flags |= error(
          protocol_v1::ClockHealthError::kTemperatureCalibrationInvalid);
      return;
    }

    const std::uint32_t started = ARM_DWT_CYCCNT;
    const std::uint32_t deadline_cycles =
        identity::dwtCyclesForMicroseconds(
            protocol_v1::kTemperatureDeadlineUs);
    bool ready = false;
    for (std::uint32_t poll = 0U;
         poll < protocol_v1::kTemperaturePollLimit; ++poll) {
      if ((TEMPMON_TEMPSENSE0 & TEMPMON_CTRL0_FINISHED) != 0U) {
        ready = true;
        break;
      }
      if (cycle_counter_available_ &&
          ARM_DWT_CYCCNT - started >= deadline_cycles) {
        break;
      }
    }
    if (!ready) {
      result.temperature_status = protocol_v1::TemperatureStatus::kNotReady;
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kTemperatureNotReady);
      return;
    }

    const std::int32_t measured_count = static_cast<std::int32_t>(
        (TEMPMON_TEMPSENSE0 >> 8U) & 0xFFFU);
    const std::int32_t numerator =
        (measured_count - hot_count) * (hot_temperature - 25) * 1000;
    const std::int32_t temperature = hot_temperature * 1000 -
        numerator / (room_count - hot_count);
    if (temperature < protocol_v1::kTemperatureMinMillidegreesCelsius ||
        temperature > protocol_v1::kTemperatureMaxMillidegreesCelsius) {
      result.temperature_status =
          protocol_v1::TemperatureStatus::kOutOfRange;
      result.error_flags |=
          error(protocol_v1::ClockHealthError::kTemperatureOutOfRange);
      return;
    }
    result.temperature_status = protocol_v1::TemperatureStatus::kValid;
    result.temperature_millidegrees_celsius =
        static_cast<std::int32_t>(temperature);
  }

  bool cycle_counter_available_ = false;
};

TeensyHardware g_hardware{};

}  // namespace

THINGDAQ_CLOCK_HEALTH_TEENSY_COLD_CODE(
    ".flashmem.clock_health.hardware_instance")
Hardware &teensyHardware() {
  return g_hardware;
}

}  // namespace thingdaq::clock_health

#endif
