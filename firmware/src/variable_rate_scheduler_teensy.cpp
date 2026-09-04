#include "variable_rate_scheduler_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <array>
#include <cstddef>
#include <cstdint>

#include <core_pins.h>
#include <imxrt.h>

#include "board_config.h"
#include "gpio_dma_route_teensy.h"

#define THINGDAQ_RATE_TARGET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::variable_rate {
namespace {

inline constexpr std::size_t kConverterCount = 2U;
inline constexpr std::uint32_t kAdcClockGateMask =
    CCM_CCGR1_ADC1(CCM_CCGR_ON) | CCM_CCGR1_ADC2(CCM_CCGR_ON);
inline constexpr std::uint32_t kAdcHardwareTriggerChannel =
    ADC_HC_ADCH(16U);

struct RegisterSnapshot {
  std::uint32_t ccm_cscmr1 = 0U;
  std::uint32_t ccm_ccgr1 = 0U;
  std::uint32_t ccm_ccgr2 = 0U;
  std::uint32_t pit_mcr = 0U;
  std::array<std::uint32_t, 2U> pit_ldval{};
  std::array<std::uint32_t, 2U> pit_tctrl{};
  std::array<std::uint16_t, kConverterCount> xbar_select{};
  std::uint32_t adc_etc_ctrl = 0U;
  std::uint32_t adc_etc_dma_ctrl = 0U;
  std::array<std::uint32_t, kConverterCount> trigger_ctrl{};
  std::array<std::uint32_t, kConverterCount> trigger_counter{};
  std::array<std::uint32_t, kConverterCount> trigger_chain{};
  std::array<std::uint32_t, kConverterCount> adc_cfg{};
  std::array<std::uint32_t, kConverterCount> adc_hc0{};
  Schedule selected{};
};

Schedule initialSchedule() {
  const DeriveResult derived = derive(protocol_v2::kDefaultRateProfile);
  return derived.schedule;
}

Schedule g_selected_schedule = initialSchedule();
Schedule g_pending_schedule = g_selected_schedule;

volatile std::uint16_t *xbarSelectRegister(std::uint8_t output) {
  return &XBARA1_SEL0 + output / 2U;
}

constexpr std::uint16_t xbarSelectionMask(std::uint8_t output) {
  return (output & 1U) != 0U ? 0xFF00U : 0x00FFU;
}

constexpr std::uint8_t xbarSelectionShift(std::uint8_t output) {
  return (output & 1U) != 0U ? 8U : 0U;
}

void connectXbar(std::uint8_t input, std::uint8_t output) {
  volatile std::uint16_t *const selection = xbarSelectRegister(output);
  const std::uint16_t mask = xbarSelectionMask(output);
  *selection = static_cast<std::uint16_t>(
      (*selection & static_cast<std::uint16_t>(~mask)) |
      (static_cast<std::uint16_t>(input)
       << xbarSelectionShift(output)));
}

std::uint8_t selectedXbarInput(std::uint8_t output) {
  return static_cast<std::uint8_t>(
      (*xbarSelectRegister(output) & xbarSelectionMask(output)) >>
      xbarSelectionShift(output));
}

IMXRT_PIT_CHANNEL_t &masterPit() {
  return IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
}

IMXRT_PIT_CHANNEL_t &pairPit() { return IMXRT_PIT_CHANNELS[1U]; }

auto &triggerQueue(std::size_t converter) {
  return IMXRT_ADC_ETC.TRIG[
      board::kAdcConverterConfigurations[converter].adc_etc_trigger];
}

volatile std::uint32_t &adcCfg(std::size_t converter) {
  return converter == 0U ? IMXRT_ADC1.CFG : IMXRT_ADC2.CFG;
}

volatile std::uint32_t &adcHc0(std::size_t converter) {
  return converter == 0U ? IMXRT_ADC1.HC0 : IMXRT_ADC2.HC0;
}

std::uint32_t chainConfiguration(std::size_t converter) {
  const std::uint32_t interrupt =
      converter == 0U ? ADC_ETC_TRIG_CHAIN_IE0(1U)
                      : ADC_ETC_TRIG_CHAIN_IE0(2U);
  return interrupt | ADC_ETC_TRIG_CHAIN_HWTS0(1U) |
         ADC_ETC_TRIG_CHAIN_CSEL0(
             board::kAdcConverterConfigurations[converter].input_channel);
}

THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.resources_stopped")
bool resourcesStopped() {
  return (masterPit().TCTRL & PIT_TCTRL_TEN) == 0U &&
         (pairPit().TCTRL & PIT_TCTRL_TEN) == 0U &&
         (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(0xFFU)) == 0U &&
         ((IMXRT_ADC1.GS | IMXRT_ADC2.GS) & ADC_GS_ADACT) == 0U;
}

THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.clocks_valid")
bool clocksValid(const Schedule &schedule) {
  return schedule.clocks == kContractClocks &&
         F_BUS_ACTUAL == schedule.clocks.ipg_hz &&
         F_CPU_ACTUAL == schedule.clocks.dwt_hz &&
         (CCM_CSCMR1 & gpio_dma_route::kPerclkMask) ==
             gpio_dma_route::kPerclk24M &&
         (CCM_CCGR1 & (gpio_dma_route::kPitGateMask |
                       kAdcClockGateMask)) ==
             (gpio_dma_route::kPitGateMask | kAdcClockGateMask) &&
         (CCM_CCGR2 & gpio_dma_route::kXbarGateMask) ==
             gpio_dma_route::kXbarGateMask;
}

THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.register_readback")
bool registerReadbackMatches(const Schedule &schedule) {
  if (!resourcesStopped() || !clocksValid(schedule) ||
      PIT_MCR & PIT_MCR_MDIS ||
      masterPit().LDVAL != schedule.gpio_master_pit_load ||
      masterPit().TCTRL != 0U ||
      pairPit().LDVAL != schedule.adc_pair_pit_load ||
      pairPit().TCTRL != PIT_TCTRL_CHN ||
      ADC_ETC_CTRL != ADC_ETC_CTRL_PRE_DIVIDER(
                          schedule.adc_etc_predivider) ||
      ADC_ETC_DMA_CTRL != 0U) {
    return false;
  }
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    const auto &configuration =
        board::kAdcConverterConfigurations[converter];
    if (selectedXbarInput(configuration.xbar_output) !=
            configuration.xbar_input ||
        triggerQueue(converter).CTRL !=
            ADC_ETC_TRIG_CTRL_TRIG_CHAIN(0U) ||
        triggerQueue(converter).COUNTER !=
            ADC_ETC_TRIG_COUNTER_INIT_DELAY(
                converter == 0U ? schedule.adc0_initial_delay
                                : schedule.adc1_initial_delay) ||
        triggerQueue(converter).CHAIN_1_0 !=
            chainConfiguration(converter) ||
        (adcCfg(converter) & ADC_CFG_ADTRG) == 0U ||
        adcHc0(converter) != kAdcHardwareTriggerChannel) {
      return false;
    }
  }
  return true;
}

class TeensyRatePlatform final : public Platform {
 public:
  THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.begin")
  bool beginTransaction() override {
    if (transaction_active_ || !resourcesStopped()) {
      return false;
    }
    snapshot_.ccm_cscmr1 = CCM_CSCMR1;
    snapshot_.ccm_ccgr1 = CCM_CCGR1;
    snapshot_.ccm_ccgr2 = CCM_CCGR2;
    snapshot_.pit_mcr = PIT_MCR;
    snapshot_.pit_ldval = {masterPit().LDVAL, pairPit().LDVAL};
    snapshot_.pit_tctrl = {masterPit().TCTRL, pairPit().TCTRL};
    for (std::size_t converter = 0U; converter < kConverterCount;
         ++converter) {
      snapshot_.xbar_select[converter] = *xbarSelectRegister(
          board::kAdcConverterConfigurations[converter].xbar_output);
      snapshot_.trigger_ctrl[converter] = triggerQueue(converter).CTRL;
      snapshot_.trigger_counter[converter] =
          triggerQueue(converter).COUNTER;
      snapshot_.trigger_chain[converter] =
          triggerQueue(converter).CHAIN_1_0;
      snapshot_.adc_cfg[converter] = adcCfg(converter);
      snapshot_.adc_hc0[converter] = adcHc0(converter);
    }
    snapshot_.adc_etc_ctrl = ADC_ETC_CTRL;
    snapshot_.adc_etc_dma_ctrl = ADC_ETC_DMA_CTRL;
    snapshot_.selected = g_selected_schedule;
    transaction_active_ = true;
    return true;
  }

  THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.apply")
  bool applyStopped(const Schedule &schedule) override {
    if (!transaction_active_ || !resourcesStopped()) {
      return false;
    }
    const DeriveResult canonical = derive(schedule.profile);
    if (!canonical.ok() || canonical.schedule != schedule) {
      return false;
    }

    // This transaction owns only the stopped PIT/XBAR/ADC schedule. DMA
    // clock ownership remains with the capture adapters.
    CCM_CCGR1 |= gpio_dma_route::kPitGateMask | kAdcClockGateMask;
    CCM_CCGR2 |= gpio_dma_route::kXbarGateMask;
    CCM_CSCMR1 = (CCM_CSCMR1 & ~gpio_dma_route::kPerclkMask) |
                 gpio_dma_route::kPerclk24M;
    PIT_MCR &= ~PIT_MCR_MDIS;
    masterPit().TCTRL = 0U;
    masterPit().LDVAL = schedule.gpio_master_pit_load;
    pairPit().TCTRL = 0U;
    pairPit().LDVAL = schedule.adc_pair_pit_load;
    pairPit().TCTRL = PIT_TCTRL_CHN;
    for (std::size_t converter = 0U; converter < kConverterCount;
         ++converter) {
      const auto &configuration =
          board::kAdcConverterConfigurations[converter];
      connectXbar(configuration.xbar_input, configuration.xbar_output);
    }

    const std::uint32_t control =
        ADC_ETC_CTRL_PRE_DIVIDER(schedule.adc_etc_predivider);
    ADC_ETC_CTRL = control;
    ADC_ETC_CTRL = control;
    ADC_ETC_DMA_CTRL = 0U;
    for (std::size_t converter = 0U; converter < kConverterCount;
         ++converter) {
      triggerQueue(converter).CTRL = ADC_ETC_TRIG_CTRL_TRIG_CHAIN(0U);
      triggerQueue(converter).COUNTER =
          ADC_ETC_TRIG_COUNTER_INIT_DELAY(
              converter == 0U ? schedule.adc0_initial_delay
                              : schedule.adc1_initial_delay);
      triggerQueue(converter).CHAIN_1_0 =
          chainConfiguration(converter);
      adcCfg(converter) |= ADC_CFG_ADTRG;
      adcHc0(converter) = kAdcHardwareTriggerChannel;
    }
    gpio_dma_route::barrier();
    g_pending_schedule = schedule;
    return registerReadbackMatches(schedule);
  }

  THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.readback")
  bool readback(Schedule &observed) override {
    if (!transaction_active_ ||
        !registerReadbackMatches(g_pending_schedule)) {
      return false;
    }
    observed = g_pending_schedule;
    return true;
  }

  THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.commit")
  bool commitTransaction() override {
    if (!transaction_active_ ||
        !registerReadbackMatches(g_pending_schedule)) {
      return false;
    }
    g_selected_schedule = g_pending_schedule;
    transaction_active_ = false;
    return true;
  }

  THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.rollback")
  bool rollbackTransaction() override {
    if (!transaction_active_) {
      return false;
    }
    masterPit().TCTRL = 0U;
    pairPit().TCTRL = 0U;
    ADC_ETC_CTRL = 0U;
    gpio_dma_route::barrier();

    PIT_MCR = snapshot_.pit_mcr;
    masterPit().LDVAL = snapshot_.pit_ldval[0];
    pairPit().LDVAL = snapshot_.pit_ldval[1];
    masterPit().TCTRL = snapshot_.pit_tctrl[0];
    pairPit().TCTRL = snapshot_.pit_tctrl[1];
    for (std::size_t converter = 0U; converter < kConverterCount;
         ++converter) {
      *xbarSelectRegister(
          board::kAdcConverterConfigurations[converter].xbar_output) =
          snapshot_.xbar_select[converter];
      triggerQueue(converter).CTRL = snapshot_.trigger_ctrl[converter];
      triggerQueue(converter).COUNTER =
          snapshot_.trigger_counter[converter];
      triggerQueue(converter).CHAIN_1_0 =
          snapshot_.trigger_chain[converter];
      adcCfg(converter) = snapshot_.adc_cfg[converter];
      adcHc0(converter) = snapshot_.adc_hc0[converter];
    }
    ADC_ETC_CTRL = snapshot_.adc_etc_ctrl;
    ADC_ETC_CTRL = snapshot_.adc_etc_ctrl;
    ADC_ETC_DMA_CTRL = snapshot_.adc_etc_dma_ctrl;
    // Clock source and gates are restored only after every peripheral write
    // has completed, so rollback also works when the prior gates were off.
    CCM_CSCMR1 = snapshot_.ccm_cscmr1;
    CCM_CCGR1 = snapshot_.ccm_ccgr1;
    CCM_CCGR2 = snapshot_.ccm_ccgr2;
    g_selected_schedule = snapshot_.selected;
    g_pending_schedule = snapshot_.selected;
    gpio_dma_route::barrier();
    transaction_active_ = false;
    return true;
  }

 private:
  RegisterSnapshot snapshot_{};
  bool transaction_active_ = false;
};

TeensyRatePlatform g_platform{};
Scheduler g_scheduler{g_platform};

}  // namespace

THINGDAQ_RATE_TARGET_COLD_CODE(".flashmem.variable_rate.singleton")
Scheduler &teensyRateScheduler() { return g_scheduler; }

const Schedule &teensySelectedSchedule() { return g_selected_schedule; }

static_assert(board::kGpioPitChannel == 0U);
static_assert(protocol_v1::kAdcTriggerPairPitChannel == 1U);

}  // namespace thingdaq::variable_rate

#endif

#undef THINGDAQ_RATE_TARGET_COLD_CODE
