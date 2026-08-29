#include "adc_trigger_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <array>
#include <cstdint>
#include <limits>

#include <core_pins.h>
#include <imxrt.h>

#include "board_config.h"
#include "gpio_dma_route_teensy.h"

#define TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace teensy_daq::adc_trigger {
namespace {

constexpr std::uint32_t kTriggerEnableMask =
    (std::uint32_t{1U} << protocol_v1::kAdcTriggerQueues[0]) |
    (std::uint32_t{1U} << protocol_v1::kAdcTriggerQueues[1]);
constexpr std::uint32_t kAdcEtcControlConfiguration =
    ADC_ETC_CTRL_PRE_DIVIDER(protocol_v1::kAdcTriggerPredivider);
constexpr std::uint32_t kAdcHardwareTriggerChannel = ADC_HC_ADCH(16U);
constexpr std::uint32_t kDone0Mask =
    ADC_ETC_DONE0_1_IRQ_TRIG_DONE0(protocol_v1::kAdcTriggerQueues[0]);
constexpr std::uint32_t kDone1Mask =
    ADC_ETC_DONE0_1_IRQ_TRIG_DONE1(protocol_v1::kAdcTriggerQueues[1]);
constexpr std::uint32_t kTriggerErrorMask =
    ADC_ETC_DONE2_ERR_IRQ_TRIG_ERR(protocol_v1::kAdcTriggerQueues[0]) |
    ADC_ETC_DONE2_ERR_IRQ_TRIG_ERR(protocol_v1::kAdcTriggerQueues[1]);
constexpr std::uint32_t kAdcClockGateMask =
    CCM_CCGR1_ADC1(CCM_CCGR_ON) | CCM_CCGR1_ADC2(CCM_CCGR_ON);

volatile std::uint32_t g_completion_counts[kConverterCount]{};
volatile std::uint32_t g_first_completion_cycles[kConverterCount]{};
volatile std::uint32_t g_trigger_error_flags = 0U;
volatile std::uint32_t g_trigger_error_count = 0U;
std::uint32_t g_done0_1_irq_final = 0U;
std::uint32_t g_done2_err_irq_final = 0U;

std::uint32_t readPrimask() {
#if defined(TEENSY_DAQ_HOST_REGISTER_TEST)
  return 0U;
#else
  std::uint32_t value = 0U;
  __asm__ volatile("mrs %0, primask" : "=r"(value));
  return value;
#endif
}

void restorePrimask(std::uint32_t value) {
  if ((value & 1U) == 0U) {
    __enable_irq();
  }
}

void barrier() { gpio_dma_route::barrier(); }

void saturatingIncrement(volatile std::uint32_t &value) {
  if (value != std::numeric_limits<std::uint32_t>::max()) {
    ++value;
  }
}

volatile std::uint16_t *xbarSelectRegister(std::uint8_t output) {
  return &XBARA1_SEL0 + output / 2U;
}

std::uint16_t xbarSelectionMask(std::uint8_t output) {
  return (output & 1U) != 0U ? 0xFF00U : 0x00FFU;
}

std::uint8_t xbarSelectionShift(std::uint8_t output) {
  return (output & 1U) != 0U ? 8U : 0U;
}

void connectXbar(std::uint8_t input, std::uint8_t output) {
  volatile std::uint16_t *const selection = xbarSelectRegister(output);
  const std::uint16_t mask = xbarSelectionMask(output);
  const std::uint8_t shift = xbarSelectionShift(output);
  *selection = static_cast<std::uint16_t>(
      (*selection & static_cast<std::uint16_t>(~mask)) |
      (static_cast<std::uint16_t>(input) << shift));
}

std::uint8_t selectedXbarInput(std::uint8_t output) {
  return static_cast<std::uint8_t>(
      (*xbarSelectRegister(output) & xbarSelectionMask(output)) >>
      xbarSelectionShift(output));
}

IMXRT_PIT_CHANNEL_t &masterPit() {
  return IMXRT_PIT_CHANNELS[protocol_v1::kAdcTriggerGpioMasterPitChannel];
}

IMXRT_PIT_CHANNEL_t &pairPit() {
  return IMXRT_PIT_CHANNELS[protocol_v1::kAdcTriggerPairPitChannel];
}

auto &triggerQueue(std::size_t converter) {
  return IMXRT_ADC_ETC.TRIG[protocol_v1::kAdcTriggerQueues[converter]];
}

std::uint32_t chainConfiguration(std::size_t converter) {
  const std::uint32_t interrupt =
      converter == 0U ? ADC_ETC_TRIG_CHAIN_IE0(1U)
                      : ADC_ETC_TRIG_CHAIN_IE0(2U);
  return interrupt | ADC_ETC_TRIG_CHAIN_HWTS0(1U) |
         ADC_ETC_TRIG_CHAIN_CSEL0(protocol_v1::kAdcChannels[converter]);
}

TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
    ".flashmem.adc_trigger.target_capture_evidence")
HardwareEvidence captureEvidence() {
  HardwareEvidence evidence{};
  evidence.ccm_cscmr1_configured = CCM_CSCMR1;
  evidence.ccm_ccgr1_configured = CCM_CCGR1;
  evidence.ccm_ccgr2_configured = CCM_CCGR2;
  evidence.pit_mcr_configured = PIT_MCR;
  evidence.gpio_master_tctrl_configured = masterPit().TCTRL;
  evidence.pair_tctrl_configured = pairPit().TCTRL;
  evidence.adc_etc_ctrl_configured = ADC_ETC_CTRL;
  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    evidence.trigger_ctrl_configured[index] = triggerQueue(index).CTRL;
    evidence.trigger_counter_configured[index] = triggerQueue(index).COUNTER;
    evidence.chain_configured[index] = triggerQueue(index).CHAIN_1_0;
    evidence.xbar_sel_configured[index] =
        *xbarSelectRegister(protocol_v1::kAdcTriggerXbarOutputs[index]);
  }
  evidence.done0_1_irq_final = g_done0_1_irq_final;
  evidence.done2_err_irq_final = g_done2_err_irq_final;
  return evidence;
}

bool resourcesBusy() {
  return (masterPit().TCTRL & PIT_TCTRL_TEN) != 0U ||
         (pairPit().TCTRL & PIT_TCTRL_TEN) != 0U ||
         (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(0xFFU)) != 0U ||
         (IMXRT_ADC1.GS & ADC_GS_ADACT) != 0U ||
         (IMXRT_ADC2.GS & ADC_GS_ADACT) != 0U;
}

bool clocksValid() {
  return F_BUS_ACTUAL == protocol_v1::kAdcTriggerIpgClockHz &&
         (CCM_CSCMR1 & gpio_dma_route::kPerclkMask) ==
             gpio_dma_route::kPerclk24M &&
         (CCM_CCGR1 & (gpio_dma_route::kPitGateMask |
                       kAdcClockGateMask)) ==
             (gpio_dma_route::kPitGateMask | kAdcClockGateMask) &&
         (CCM_CCGR2 & gpio_dma_route::kXbarGateMask) ==
             gpio_dma_route::kXbarGateMask;
}

bool xbarValid() {
  return selectedXbarInput(protocol_v1::kAdcTriggerXbarOutputs[0]) ==
             protocol_v1::kAdcTriggerXbarInputs[0] &&
         selectedXbarInput(protocol_v1::kAdcTriggerXbarOutputs[1]) ==
             protocol_v1::kAdcTriggerXbarInputs[1];
}

TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
    ".flashmem.adc_trigger.target_queues_valid")
bool queuesValid() {
  if (ADC_ETC_CTRL != kAdcEtcControlConfiguration ||
      masterPit().LDVAL != protocol_v1::kAdcTriggerGpioMasterPitLoad ||
      pairPit().LDVAL != protocol_v1::kAdcTriggerPairPitLoad ||
      masterPit().TCTRL != 0U || pairPit().TCTRL != PIT_TCTRL_CHN) {
    return false;
  }
  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    if (triggerQueue(index).CTRL != ADC_ETC_TRIG_CTRL_TRIG_CHAIN(0U) ||
        triggerQueue(index).COUNTER != ADC_ETC_TRIG_COUNTER_INIT_DELAY(
                                           protocol_v1::
                                               kAdcTriggerInitialDelays[index]) ||
        triggerQueue(index).CHAIN_1_0 != chainConfiguration(index)) {
      return false;
    }
  }
  return true;
}

bool convertersHardwareTriggered() {
  return (IMXRT_ADC1.CFG & ADC_CFG_ADTRG) != 0U &&
         (IMXRT_ADC2.CFG & ADC_CFG_ADTRG) != 0U &&
         IMXRT_ADC1.HC0 == kAdcHardwareTriggerChannel &&
         IMXRT_ADC2.HC0 == kAdcHardwareTriggerChannel;
}

void resetDiagnosticState() {
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  for (std::size_t index = 0U; index < kConverterCount; ++index) {
    g_completion_counts[index] = 0U;
    g_first_completion_cycles[index] = 0U;
  }
  g_trigger_error_flags = 0U;
  g_trigger_error_count = 0U;
  g_done0_1_irq_final = 0U;
  g_done2_err_irq_final = 0U;
  restorePrimask(primask);
}

void adcEtcDone0Isr() {
  const std::uint32_t pending = ADC_ETC_DONE0_1_IRQ & kDone0Mask;
  if (pending != 0U) {
    if (g_completion_counts[0] == 0U) {
      g_first_completion_cycles[0] = ARM_DWT_CYCCNT;
    }
    saturatingIncrement(g_completion_counts[0]);
    ADC_ETC_DONE0_1_IRQ = pending;
  }
}

void adcEtcDone1Isr() {
  const std::uint32_t pending = ADC_ETC_DONE0_1_IRQ & kDone1Mask;
  if (pending != 0U) {
    if (g_completion_counts[1] == 0U) {
      g_first_completion_cycles[1] = ARM_DWT_CYCCNT;
    }
    saturatingIncrement(g_completion_counts[1]);
    ADC_ETC_DONE0_1_IRQ = pending;
  }
}

TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
    ".flashmem.adc_trigger.target_error_isr")
void adcEtcErrorIsr() {
  const std::uint32_t pending = ADC_ETC_DONE2_ERR_IRQ & kTriggerErrorMask;
  if (pending != 0U) {
    g_trigger_error_flags |= pending;
    saturatingIncrement(g_trigger_error_count);
    ADC_ETC_DONE2_ERR_IRQ = pending;
  }
}

class TeensyPlatform final : public Platform {
 public:
  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_configure")
  ConfigureResult configureStopped() override {
    ConfigureResult result{};
    if (resourcesBusy()) {
      result.error_flags |=
          triggerError(protocol_v1::AdcTriggerError::kResourceBusy);
      result.evidence = captureEvidence();
      return result;
    }

    gpio_dma_route::enableClockGates();
    CCM_CCGR1 |= kAdcClockGateMask;
    gpio_dma_route::configureStoppedPit(
        protocol_v1::kAdcTriggerGpioMasterPitLoad);
    pairPit().TCTRL = 0U;
    pairPit().TFLG = PIT_TFLG_TIF;
    pairPit().LDVAL = protocol_v1::kAdcTriggerPairPitLoad;
    pairPit().TCTRL = PIT_TCTRL_CHN;

    for (std::size_t index = 0U; index < kConverterCount; ++index) {
      connectXbar(protocol_v1::kAdcTriggerXbarInputs[index],
                  protocol_v1::kAdcTriggerXbarOutputs[index]);
    }

    ADC_ETC_CTRL = kAdcEtcControlConfiguration;
    ADC_ETC_DMA_CTRL = 0U;
    for (std::size_t index = 0U; index < kConverterCount; ++index) {
      triggerQueue(index).CTRL = ADC_ETC_TRIG_CTRL_TRIG_CHAIN(0U);
      triggerQueue(index).COUNTER = ADC_ETC_TRIG_COUNTER_INIT_DELAY(
          protocol_v1::kAdcTriggerInitialDelays[index]);
      triggerQueue(index).CHAIN_1_0 = chainConfiguration(index);
    }
    IMXRT_ADC1.CFG |= ADC_CFG_ADTRG;
    IMXRT_ADC2.CFG |= ADC_CFG_ADTRG;
    IMXRT_ADC1.HC0 = kAdcHardwareTriggerChannel;
    IMXRT_ADC2.HC0 = kAdcHardwareTriggerChannel;
    barrier();

    if (masterPit().TCTRL == 0U && pairPit().TCTRL == PIT_TCTRL_CHN &&
        (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(0xFFU)) == 0U) {
      result.configuration_flags |= configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::kConfiguredStopped);
    }
    if (clocksValid()) {
      result.configuration_flags |= configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::kClocksValid);
    } else {
      if ((CCM_CSCMR1 & gpio_dma_route::kPerclkMask) !=
          gpio_dma_route::kPerclk24M) {
        result.error_flags |=
            triggerError(protocol_v1::AdcTriggerError::kPerclkMismatch);
      }
      if (F_BUS_ACTUAL != protocol_v1::kAdcTriggerIpgClockHz) {
        result.error_flags |=
            triggerError(protocol_v1::AdcTriggerError::kIpgClockMismatch);
      }
      if ((CCM_CCGR1 & gpio_dma_route::kPitGateMask) !=
          gpio_dma_route::kPitGateMask) {
        result.error_flags |=
            triggerError(protocol_v1::AdcTriggerError::kPitConfigMismatch);
      }
      if ((CCM_CCGR2 & gpio_dma_route::kXbarGateMask) !=
          gpio_dma_route::kXbarGateMask) {
        result.error_flags |=
            triggerError(protocol_v1::AdcTriggerError::kXbarConfigMismatch);
      }
      if ((CCM_CCGR1 & kAdcClockGateMask) != kAdcClockGateMask) {
        result.error_flags |= triggerError(
            protocol_v1::AdcTriggerError::kAdcHardwareTriggerMismatch);
      }
    }
    if (xbarValid()) {
      result.configuration_flags |= configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::kXbarRoutesValid);
    } else {
      result.error_flags |=
          triggerError(protocol_v1::AdcTriggerError::kXbarConfigMismatch);
    }
    if (queuesValid()) {
      result.configuration_flags |= configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::kQueuesValid);
    } else {
      result.error_flags |= triggerError(
          protocol_v1::AdcTriggerError::kAdcEtcConfigMismatch);
      if (masterPit().LDVAL !=
              protocol_v1::kAdcTriggerGpioMasterPitLoad ||
          pairPit().LDVAL != protocol_v1::kAdcTriggerPairPitLoad) {
        result.error_flags |=
            triggerError(protocol_v1::AdcTriggerError::kPitConfigMismatch);
      }
    }
    if (convertersHardwareTriggered()) {
      result.configuration_flags |= configurationFlag(
          protocol_v1::AdcTriggerConfigurationFlag::
              kAdcHardwareTriggerValid);
    } else {
      result.error_flags |= triggerError(
          protocol_v1::AdcTriggerError::kAdcHardwareTriggerMismatch);
    }
    result.evidence = captureEvidence();
    return result;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_counter_begin")
  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    if (F_CPU_ACTUAL != protocol_v1::kAdcTriggerDwtClockHz) {
      frequency_hz = 0U;
      return false;
    }
    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    barrier();
    const std::uint32_t begin = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    frequency_hz = F_CPU_ACTUAL;
    return ARM_DWT_CYCCNT != begin;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_counter_read")
  std::uint32_t readCycles() override { return ARM_DWT_CYCCNT; }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_arm")
  bool armFromStopped(bool completion_diagnostic) override {
    if (!queuesValid() || !xbarValid() || !convertersHardwareTriggered() ||
        (IMXRT_ADC1.GS & ADC_GS_ADACT) != 0U ||
        (IMXRT_ADC2.GS & ADC_GS_ADACT) != 0U) {
      return false;
    }
    ADC_ETC_DONE0_1_IRQ = kDone0Mask | kDone1Mask;
    ADC_ETC_DONE2_ERR_IRQ = kTriggerErrorMask;
    if (completion_diagnostic) {
      resetDiagnosticState();
      attachInterruptVector(IRQ_ADC_ETC0, adcEtcDone0Isr);
      attachInterruptVector(IRQ_ADC_ETC1, adcEtcDone1Isr);
      attachInterruptVector(IRQ_ADC_ETC_ERR, adcEtcErrorIsr);
      NVIC_SET_PRIORITY(IRQ_ADC_ETC0,
                        protocol_v1::kAdcTriggerIrqPriority);
      NVIC_SET_PRIORITY(IRQ_ADC_ETC1,
                        protocol_v1::kAdcTriggerIrqPriority);
      NVIC_SET_PRIORITY(IRQ_ADC_ETC_ERR,
                        protocol_v1::kAdcTriggerIrqPriority);
      NVIC_CLEAR_PENDING(IRQ_ADC_ETC0);
      NVIC_CLEAR_PENDING(IRQ_ADC_ETC1);
      NVIC_CLEAR_PENDING(IRQ_ADC_ETC_ERR);
      NVIC_ENABLE_IRQ(IRQ_ADC_ETC0);
      NVIC_ENABLE_IRQ(IRQ_ADC_ETC1);
      NVIC_ENABLE_IRQ(IRQ_ADC_ETC_ERR);
    } else {
      // The production ADC DMA adapter already owns IRQ_ADC_ETC_ERR. The
      // completion vectors are diagnostic-only and must not race DMA buffer
      // generations or overwrite the production error observer.
      NVIC_DISABLE_IRQ(IRQ_ADC_ETC0);
      NVIC_DISABLE_IRQ(IRQ_ADC_ETC1);
      NVIC_CLEAR_PENDING(IRQ_ADC_ETC0);
      NVIC_CLEAR_PENDING(IRQ_ADC_ETC1);
    }
    ADC_ETC_CTRL = kAdcEtcControlConfiguration |
                   ADC_ETC_CTRL_TRIG_ENABLE(kTriggerEnableMask);
    barrier();
    pairPit().TCTRL = PIT_TCTRL_CHN | PIT_TCTRL_TEN;
    masterPit().TCTRL = PIT_TCTRL_TEN;
    barrier();
    return (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(kTriggerEnableMask)) ==
               ADC_ETC_CTRL_TRIG_ENABLE(kTriggerEnableMask) &&
           (pairPit().TCTRL & PIT_TCTRL_TEN) != 0U &&
           (masterPit().TCTRL & PIT_TCTRL_TEN) != 0U;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_completion_counts")
  std::array<std::uint32_t, kConverterCount> completionCounts() override {
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    const std::array<std::uint32_t, kConverterCount> result{
        g_completion_counts[0], g_completion_counts[1]};
    restorePrimask(primask);
    return result;
  }

  std::array<std::uint32_t, kConverterCount>
  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_completion_cycles")
  firstCompletionCycles() override {
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    const std::array<std::uint32_t, kConverterCount> result{
        g_first_completion_cycles[0], g_first_completion_cycles[1]};
    restorePrimask(primask);
    return result;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_error_flags")
  std::uint32_t triggerErrorFlags() override {
    return g_trigger_error_flags;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_error_count")
  std::uint32_t triggerErrorCount() override {
    return g_trigger_error_count;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_stop")
  bool stop() override {
    masterPit().TCTRL = 0U;
    pairPit().TCTRL = PIT_TCTRL_CHN;
    ADC_ETC_CTRL = kAdcEtcControlConfiguration;
    barrier();
    const std::uint32_t started = ARM_DWT_CYCCNT;
    std::uint32_t polls = 0U;
    while (((IMXRT_ADC1.GS | IMXRT_ADC2.GS) & ADC_GS_ADACT) != 0U &&
           ARM_DWT_CYCCNT - started < kDiagnosticDeadlineCycles &&
           polls < protocol_v1::kAdcTriggerDiagnosticPollLimit) {
      ++polls;
    }
    NVIC_DISABLE_IRQ(IRQ_ADC_ETC0);
    NVIC_DISABLE_IRQ(IRQ_ADC_ETC1);
    NVIC_DISABLE_IRQ(IRQ_ADC_ETC_ERR);
    barrier();
    g_done0_1_irq_final = ADC_ETC_DONE0_1_IRQ;
    g_done2_err_irq_final = ADC_ETC_DONE2_ERR_IRQ;
    ADC_ETC_DONE0_1_IRQ = kDone0Mask | kDone1Mask;
    ADC_ETC_DONE2_ERR_IRQ = kTriggerErrorMask;
    NVIC_CLEAR_PENDING(IRQ_ADC_ETC0);
    NVIC_CLEAR_PENDING(IRQ_ADC_ETC1);
    NVIC_CLEAR_PENDING(IRQ_ADC_ETC_ERR);
    return masterPit().TCTRL == 0U && pairPit().TCTRL == PIT_TCTRL_CHN &&
           (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(0xFFU)) == 0U &&
           ((IMXRT_ADC1.GS | IMXRT_ADC2.GS) & ADC_GS_ADACT) == 0U;
  }

  TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
      ".flashmem.adc_trigger.target_evidence")
  HardwareEvidence evidence() override { return captureEvidence(); }
};

TeensyPlatform g_platform{};
Scheduler g_scheduler{g_platform};

}  // namespace

TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE(
    ".flashmem.adc_trigger.target_singleton")
Scheduler &teensyScheduler() { return g_scheduler; }

static_assert(F_CPU == protocol_v1::kAdcTriggerDwtClockHz,
              "ADC trigger diagnostic requires the pinned 600 MHz target");
static_assert(XBARA1_IN_PIT_TRIGGER1 ==
              protocol_v1::kAdcTriggerXbarInputs[0]);
static_assert(XBARA1_OUT_ADC_ETC_TRIG00 ==
              protocol_v1::kAdcTriggerXbarOutputs[0]);
static_assert(XBARA1_OUT_ADC_ETC_TRIG10 ==
              protocol_v1::kAdcTriggerXbarOutputs[1]);

}  // namespace teensy_daq::adc_trigger

#endif

#undef TEENSY_DAQ_ADC_TRIGGER_TARGET_COLD_CODE
