#include "adc_initializer_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstdint>

#include <core_pins.h>
#include <imxrt.h>

#define THINGDAQ_ADC_TARGET_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

// Teensy startup calls analog_init() before C++ global construction. The core
// implementation calibrates both modules with unbounded busy loops, so resolve
// that archive hook here without touching any unconstructed project object.
// setup() then performs the sole ADC configuration and calibration through the
// independently bounded, reportable initializer below. Linking analogRead()
// later will intentionally expose a duplicate hook instead of bypassing this
// ownership boundary silently.
extern "C" THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.defer_core")
void analog_init(void) {}

namespace thingdaq::adc {
namespace {

constexpr std::uint32_t kAdcClockGateMask =
    CCM_CCGR1_ADC1(CCM_CCGR_ON) | CCM_CCGR1_ADC2(CCM_CCGR_ON);
constexpr std::uint32_t kAnalogMuxConfiguration = 5U | 0x10U;
constexpr std::uint32_t kAnalogPadConfiguration =
    IOMUXC_PAD_DSE(7U) | IOMUXC_PAD_HYS;
constexpr std::uint32_t kDisabledChannel = ADC_HC_ADCH(31U);

IMXRT_ADCS_t *moduleFor(const board::AdcConverterConfiguration &route) {
  if (route.adc_peripheral == 1U) {
    return &IMXRT_ADC1;
  }
  if (route.adc_peripheral == 2U) {
    return &IMXRT_ADC2;
  }
  return nullptr;
}

bool routeMatchesContract(const board::AdcConverterConfiguration &route) {
  if (route.logical_converter == 0U) {
    return route.teensy_adc_library_module == 0U &&
           route.teensy_pin == A0 &&
           route.input_pad == board::AdcInputPad::kGpioAdB1_02 &&
           route.adc_peripheral == 1U && route.input_channel == 7U;
  }
  if (route.logical_converter == 1U) {
    return route.teensy_adc_library_module == 1U &&
           route.teensy_pin == A1 &&
           route.input_pad == board::AdcInputPad::kGpioAdB1_03 &&
           route.adc_peripheral == 2U && route.input_channel == 8U;
  }
  return false;
}

void disableCommandSlots(IMXRT_ADCS_t &module) {
  module.HC0 = kDisabledChannel;
  module.HC1 = kDisabledChannel;
  module.HC2 = kDisabledChannel;
  module.HC3 = kDisabledChannel;
  module.HC4 = kDisabledChannel;
  module.HC5 = kDisabledChannel;
  module.HC6 = kDisabledChannel;
  module.HC7 = kDisabledChannel;
}

THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_slots")
bool commandSlotsDisabled(const IMXRT_ADCS_t &module) {
  return module.HC0 == kDisabledChannel && module.HC1 == kDisabledChannel &&
         module.HC2 == kDisabledChannel && module.HC3 == kDisabledChannel &&
         module.HC4 == kDisabledChannel && module.HC5 == kDisabledChannel &&
         module.HC6 == kDisabledChannel && module.HC7 == kDisabledChannel;
}

bool preparePin(const board::AdcConverterConfiguration &route) {
  if (route.teensy_pin == A0 &&
      route.input_pad == board::AdcInputPad::kGpioAdB1_02) {
    GPIO6_GDIR &= ~static_cast<std::uint32_t>(CORE_PIN14_BITMASK);
    CORE_PIN14_CONFIG = kAnalogMuxConfiguration;
    CORE_PIN14_PADCONFIG = kAnalogPadConfiguration;
    return (GPIO6_GDIR & CORE_PIN14_BITMASK) == 0U &&
           CORE_PIN14_CONFIG == kAnalogMuxConfiguration &&
           CORE_PIN14_PADCONFIG == kAnalogPadConfiguration;
  }
  if (route.teensy_pin == A1 &&
      route.input_pad == board::AdcInputPad::kGpioAdB1_03) {
    GPIO6_GDIR &= ~static_cast<std::uint32_t>(CORE_PIN15_BITMASK);
    CORE_PIN15_CONFIG = kAnalogMuxConfiguration;
    CORE_PIN15_PADCONFIG = kAnalogPadConfiguration;
    return (GPIO6_GDIR & CORE_PIN15_BITMASK) == 0U &&
           CORE_PIN15_CONFIG == kAnalogMuxConfiguration &&
           CORE_PIN15_PADCONFIG == kAnalogPadConfiguration;
  }
  return false;
}

bool pinPrepared(const board::AdcConverterConfiguration &route) {
  if (route.teensy_pin == A0) {
    return (GPIO6_GDIR & CORE_PIN14_BITMASK) == 0U &&
           CORE_PIN14_CONFIG == kAnalogMuxConfiguration &&
           CORE_PIN14_PADCONFIG == kAnalogPadConfiguration;
  }
  if (route.teensy_pin == A1) {
    return (GPIO6_GDIR & CORE_PIN15_BITMASK) == 0U &&
           CORE_PIN15_CONFIG == kAnalogMuxConfiguration &&
           CORE_PIN15_PADCONFIG == kAnalogPadConfiguration;
  }
  return false;
}

std::uint32_t configurationFor(const Settings &settings) {
  // ADICLK=1 selects IPG/2 and ADIV=1 divides by another two: the resulting
  // 37.5 MHz ADCK completes a 12-bit, three-ADCK sample conversion in
  // (25 + 3 + 4.5) / 37.5 MHz = 866.667 ns, inside the 1 us pair period.
  return ADC_CFG_OVWREN | ADC_CFG_ADHSC | ADC_CFG_ADIV(1U) |
         ADC_CFG_ADICLK(1U) | ADC_CFG_MODE(settings.conversion_mode);
}

class TeensyPlatform final : public Platform {
 public:
  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_prepare")
  PrepareStatus prepareConverter(
      const board::AdcConverterConfiguration &route,
      const Settings &settings) override {
    if (!routeMatchesContract(route)) {
      return PrepareStatus::kRouteInvalid;
    }
    if (F_BUS_ACTUAL != settings.ipg_clock_hz ||
        settings.adc_clock_hz * settings.clock_divider !=
            settings.ipg_clock_hz) {
      return PrepareStatus::kConfigurationInvalid;
    }
    IMXRT_ADCS_t *const module = moduleFor(route);
    if (module == nullptr) {
      return PrepareStatus::kRouteInvalid;
    }

    CCM_CCGR1 |= kAdcClockGateMask;
    if (!preparePin(route)) {
      return PrepareStatus::kRouteInvalid;
    }
    disableCommandSlots(*module);
    module->GC = 0U;
    module->GS = ADC_GS_CALF;
    module->CFG = configurationFor(settings);
    if ((CCM_CCGR1 & kAdcClockGateMask) != kAdcClockGateMask ||
        module->CFG != configurationFor(settings) || module->GC != 0U ||
        !commandSlotsDisabled(*module)) {
      return PrepareStatus::kConfigurationInvalid;
    }
    return PrepareStatus::kOk;
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_counter_begin")
  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    if (F_CPU_ACTUAL != protocol_v1::kAdcCalibrationCycleCounterHz) {
      frequency_hz = 0U;
      return false;
    }
    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
#if defined(THINGDAQ_HOST_REGISTER_TEST)
    __asm__ volatile("" : : : "memory");
#else
    __asm__ volatile("dsb\n\tisb" : : : "memory");
#endif
    const std::uint32_t begin = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    frequency_hz = F_CPU_ACTUAL;
    return ARM_DWT_CYCCNT != begin;
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_counter_read")
  std::uint32_t readCycles() override {
    __asm__ volatile("" : : : "memory");
    return ARM_DWT_CYCCNT;
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_cal_start")
  bool startCalibration(
      const board::AdcConverterConfiguration &route) override {
    IMXRT_ADCS_t *const module = moduleFor(route);
    if (module == nullptr || !routeMatchesContract(route) ||
        (module->GC & ADC_GC_CAL) != 0U) {
      return false;
    }
    module->GS = ADC_GS_CALF;
    module->GC = ADC_GC_CAL;
    // A very fast completion between the write and a readback is success, not
    // a failed start. The bounded poll examines CAL/CALF and full readback.
    return true;
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_cal_active")
  bool calibrationActive(
      const board::AdcConverterConfiguration &route) override {
    const IMXRT_ADCS_t *const module = moduleFor(route);
    return module != nullptr && (module->GC & ADC_GC_CAL) != 0U;
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_cal_failed")
  bool calibrationFailed(
      const board::AdcConverterConfiguration &route) override {
    const IMXRT_ADCS_t *const module = moduleFor(route);
    return module == nullptr || (module->GS & ADC_GS_CALF) != 0U;
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_verify")
  bool verifyConverter(const board::AdcConverterConfiguration &route,
                       const Settings &settings) override {
    const IMXRT_ADCS_t *const module = moduleFor(route);
    return module != nullptr && routeMatchesContract(route) &&
           F_BUS_ACTUAL == settings.ipg_clock_hz &&
           settings.adc_clock_hz * settings.clock_divider ==
               settings.ipg_clock_hz &&
           (CCM_CCGR1 & kAdcClockGateMask) == kAdcClockGateMask &&
           pinPrepared(route) && module->CFG == configurationFor(settings) &&
           module->GC == 0U && (module->GS & ADC_GS_CALF) == 0U &&
           commandSlotsDisabled(*module);
  }

  THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_abort")
  void abortCalibration(
      const board::AdcConverterConfiguration &route) override {
    IMXRT_ADCS_t *const module = moduleFor(route);
    if (module != nullptr) {
      module->GC = 0U;
      disableCommandSlots(*module);
    }
  }
};

TeensyPlatform g_platform{};
Initializer g_initializer{g_platform};

}  // namespace

THINGDAQ_ADC_TARGET_CODE(".flashmem.adc_init.target_singleton")
Initializer &teensyInitializer() { return g_initializer; }

static_assert(F_CPU == protocol_v1::kAdcCalibrationCycleCounterHz,
              "ADC initialization requires the pinned 600 MHz target");
static_assert(A0 == board::kAdc0Pin);
static_assert(A1 == board::kAdc1Pin);
static_assert(board::kAdc0Peripheral == 1U);
static_assert(board::kAdc1Peripheral == 2U);
static_assert(board::kAdc0InputChannel == 7U);
static_assert(board::kAdc1InputChannel == 8U);
static_assert(protocol_v1::kAdcClockHz * protocol_v1::kAdcClockDivider ==
              protocol_v1::kAdcIpgClockHz);

}  // namespace thingdaq::adc

#endif

#undef THINGDAQ_ADC_TARGET_CODE
