#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#define ARDUINO_TEENSY40 1
#define __IMXRT1062__ 1
#define THINGDAQ_HOST_REGISTER_TEST 1

// Supply the target adapter's selected variable-rate schedule through the
// portable derivation path used by production.
#include "../src/variable_rate_scheduler.cpp"
#include "../src/variable_rate_scheduler_teensy.cpp"

// White-box inclusion is deliberate: this host executable exercises the
// production register adapters themselves against the narrow fake i.MX RT1062
// register surface, including helpers kept in their anonymous namespaces.
#include "../src/adc_initializer_teensy.cpp"
#include "../src/adc_trigger_teensy.cpp"

namespace {

namespace adc = thingdaq::adc;
namespace board = thingdaq::board;
namespace gpio_route = thingdaq::gpio_dma_route;
namespace trigger = thingdaq::adc_trigger;
namespace v1 = thingdaq::protocol_v1;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

void testInterruptGuardPreservesCallerAndEarlyReturns() {
  using thingdaq::interrupts::Guard;
  fake_imxrt::interrupts_enabled = true;
  {
    const Guard outer;
    expect(!fake_imxrt::interrupts_enabled, "guard masks interrupts");
    {
      const Guard inner;
      expect(!fake_imxrt::interrupts_enabled, "nested guard stays masked");
    }
    expect(!fake_imxrt::interrupts_enabled,
           "nested destruction preserves outer mask");
  }
  expect(fake_imxrt::interrupts_enabled, "outer guard restores enabled caller");
  const auto early_return = []() {
    const Guard guard;
    return fake_imxrt::interrupts_enabled;
  };
  expect(!early_return() && fake_imxrt::interrupts_enabled,
         "early return restores the interrupt mask");
  fake_imxrt::interrupts_enabled = false;
  {
    const Guard guard;
  }
  expect(!fake_imxrt::interrupts_enabled,
         "guard preserves a caller that already disabled interrupts");
  fake_imxrt::interrupts_enabled = true;
  {
    const Guard inactive(false);
    expect(fake_imxrt::interrupts_enabled,
           "conditional inactive guard leaves caller alone");
    Guard shortened;
    shortened.release();
    expect(fake_imxrt::interrupts_enabled,
           "explicit release ends the hardware window");
    fake_imxrt::interrupts_enabled = false;
  }
  expect(!fake_imxrt::interrupts_enabled,
         "released and inactive destructors never unmask a later window");
  fake_imxrt::interrupts_enabled = true;
}

void resetFakeRegisters() {
  fake_imxrt::ccm_cscmr1 = 0U;
  fake_imxrt::ccm_ccgr1 = 0U;
  fake_imxrt::ccm_ccgr2 = 0U;
  fake_imxrt::ccm_ccgr5 = 0U;
  fake_imxrt::pit_mcr = 0U;
  fake_imxrt::gpio6_gdir = std::numeric_limits<std::uint32_t>::max();
  fake_imxrt::pin14_config = 0U;
  fake_imxrt::pin15_config = 0U;
  fake_imxrt::pin14_padconfig = 0U;
  fake_imxrt::pin15_padconfig = 0U;
  fake_imxrt::f_bus_actual = v1::kAdcIpgClockHz;
  fake_imxrt::f_cpu_actual = v1::kAdcCalibrationCycleCounterHz;
  fake_imxrt::interrupts_enabled = true;
  fake_imxrt::arm_demcr = 0U;
  fake_imxrt::arm_dwt_ctrl = 0U;
  fake_imxrt::arm_dwt_cyccnt = 0U;
  fake_imxrt::adc1 = {};
  fake_imxrt::adc2 = {};
  fake_imxrt::adc_etc = {};
  fake_imxrt::dma_erq = 0U;
  fake_imxrt::dma_cerq = 0U;
  fake_imxrt::dma_cerr = 0U;
  fake_imxrt::dma_ceei = 0U;
  fake_imxrt::dma_cint = 0U;
  fake_imxrt::dma_cdne = 0U;
  fake_imxrt::dma_serq = 0U;
  for (std::size_t channel = 0U; channel < 32U; ++channel) {
    fake_imxrt::dmamux_chcfg[channel] = 0U;
    fake_imxrt::dma_dchpri[channel] = 0U;
  }
  fake_imxrt::adc_etc.CTRL.reset(ADC_ETC_CTRL_SOFTRST |
                                 ADC_ETC_CTRL_TSC_BYPASS);
  for (IMXRT_PIT_CHANNEL_t &pit : fake_imxrt::pit_channels) {
    pit = {};
  }
  for (std::size_t index = 0U; index < 66U; ++index) {
    fake_imxrt::xbara1_sel[index] =
        static_cast<std::uint16_t>(0xA500U + index);
    fake_imxrt::xbara1_ctrl[index] =
        static_cast<std::uint16_t>(0x5A00U + index);
  }
  fake_imxrt::interrupt_vectors.fill(nullptr);
  fake_imxrt::interrupt_priorities.fill(0U);
  fake_imxrt::interrupt_enabled.fill(false);
  fake_imxrt::interrupt_pending.fill(false);
  fake_imxrt::adc_trigger_diagnostic_poll_hook = nullptr;
  fake_imxrt::clearRegisterWrites();
}

std::size_t writeIndex(const fake_imxrt::Register32 &target,
                       std::uint32_t value) {
  const std::size_t count =
      fake_imxrt::register_write_count < fake_imxrt::register_writes.size()
          ? fake_imxrt::register_write_count
          : fake_imxrt::register_writes.size();
  for (std::size_t index = 0U; index < count; ++index) {
    const fake_imxrt::RegisterWrite &write =
        fake_imxrt::register_writes[index];
    if (write.address == &target && write.value == value) {
      return index;
    }
  }
  return std::numeric_limits<std::size_t>::max();
}

std::size_t writeCount(const fake_imxrt::Register32 &target,
                       std::uint32_t value) {
  const std::size_t count =
      fake_imxrt::register_write_count < fake_imxrt::register_writes.size()
          ? fake_imxrt::register_write_count
          : fake_imxrt::register_writes.size();
  std::size_t matches = 0U;
  for (std::size_t index = 0U; index < count; ++index) {
    const fake_imxrt::RegisterWrite &write =
        fake_imxrt::register_writes[index];
    if (write.address == &target && write.value == value) {
      ++matches;
    }
  }
  return matches;
}

void testFixedPinModuleRoutesAndLegalResolutionModes() {
  resetFakeRegisters();
  adc::TeensyPlatform platform{};
  const adc::Settings primary = adc::settingsFor({});

  const adc::PrepareStatus adc0 = platform.prepareConverter(
      board::kAdcConverterConfigurations[0], primary);
  const std::uint32_t primary_cfg = IMXRT_ADC1.CFG;
  const std::uint32_t adc2_cfg_before = IMXRT_ADC2.CFG;
  expect(adc0 == adc::PrepareStatus::kOk &&
             (fake_imxrt::gpio6_gdir & CORE_PIN14_BITMASK) == 0U &&
             fake_imxrt::pin14_config == (5U | 0x10U) &&
             fake_imxrt::pin14_padconfig ==
                 (IOMUXC_PAD_DSE(7U) | IOMUXC_PAD_HYS),
         "logical ADC0 prepares only Teensy A0/GPIO_AD_B1_02 as analog input");
  expect((primary_cfg & ADC_CFG_MODE(3U)) == ADC_CFG_MODE(2U) &&
             (primary_cfg & (ADC_CFG_OVWREN | ADC_CFG_ADHSC)) ==
                 (ADC_CFG_OVWREN | ADC_CFG_ADHSC) &&
             (primary_cfg & ADC_CFG_ADTRG) == 0U && IMXRT_ADC1.GC == 0U &&
             adc2_cfg_before == 0U,
         "primary 12-bit setup selects legal MODE=2 without touching ADC2");

  const adc::ResolutionGate fallback_gate{true, true, true,
                                           true, false, true};
  const adc::Settings fallback = adc::settingsFor(fallback_gate);
  const adc::PrepareStatus adc1 = platform.prepareConverter(
      board::kAdcConverterConfigurations[1], fallback);
  const std::uint32_t fallback_cfg = IMXRT_ADC2.CFG;
  expect(adc1 == adc::PrepareStatus::kOk &&
             (fake_imxrt::gpio6_gdir & CORE_PIN15_BITMASK) == 0U &&
             fake_imxrt::pin15_config == (5U | 0x10U) &&
             fake_imxrt::pin15_padconfig ==
                 (IOMUXC_PAD_DSE(7U) | IOMUXC_PAD_HYS),
         "logical ADC1 prepares only Teensy A1/GPIO_AD_B1_03 as analog input");
  expect(fallback.resolution_bits == 10U && fallback.code_max == 1023U &&
             (fallback_cfg & ADC_CFG_MODE(3U)) == ADC_CFG_MODE(1U) &&
             IMXRT_ADC1.CFG == primary_cfg,
         "authorized 10-bit fallback selects legal MODE=1 without changing ADC1");

  board::AdcConverterConfiguration swapped =
      board::kAdcConverterConfigurations[0];
  swapped.adc_peripheral = 2U;
  const std::uint32_t adc1_before_invalid = IMXRT_ADC1.CFG;
  const std::uint32_t adc2_before_invalid = IMXRT_ADC2.CFG;
  expect(platform.prepareConverter(swapped, primary) ==
                 adc::PrepareStatus::kRouteInvalid &&
             IMXRT_ADC1.CFG == adc1_before_invalid &&
             IMXRT_ADC2.CFG == adc2_before_invalid,
         "a swapped A0-to-ADC2 route fails before either module is modified");
}

void testExactStoppedTriggerScheduleAndResourceIsolation() {
  resetFakeRegisters();
  // Unreserved activity and queue state must not be mistaken for ownership of
  // PIT0/PIT1, ADC_ETC queues 0/4, or XBAR outputs 103/107.
  fake_imxrt::pit_channels[2].TCTRL.reset(PIT_TCTRL_TEN);
  fake_imxrt::adc_etc.TRIG[3].CTRL.reset(0x00ABC000U);
  std::array<std::uint16_t, 66U> xbar_before{};
  for (std::size_t index = 0U; index < xbar_before.size(); ++index) {
    xbar_before[index] = fake_imxrt::xbara1_sel[index];
  }

  trigger::TeensyPlatform platform{};
  const trigger::ConfigureResult configured = platform.configureStopped();
  expect(configured.error_flags == 0U &&
             configured.configuration_flags ==
                 trigger::kStoppedConfigurationFlags,
         "the fixed trigger adapter configures successfully from stopped state");
  expect(writeCount(fake_imxrt::adc_etc.CTRL,
                    ADC_ETC_CTRL_PRE_DIVIDER(
                        v1::kAdcTriggerPredivider)) == 2U,
         "ADC_ETC reset state receives separate SOFTRST and TSC_BYPASS clears");
  expect(fake_imxrt::pit_channels[0].LDVAL ==
                 v1::kAdcTriggerGpioMasterPitLoad &&
             fake_imxrt::pit_channels[0].TCTRL == 0U &&
             fake_imxrt::pit_channels[1].LDVAL ==
                 v1::kAdcTriggerPairPitLoad &&
             fake_imxrt::pit_channels[1].TCTRL == PIT_TCTRL_CHN &&
             fake_imxrt::pit_channels[2].TCTRL == PIT_TCTRL_TEN,
         "PIT0/PIT1 form the exact 4 MHz to 1 MHz chain without touching PIT2");

  const std::array<std::uint8_t, 2U> queues{v1::kAdcTriggerQueues[0],
                                            v1::kAdcTriggerQueues[1]};
  const std::array<std::uint16_t, 2U> raw_delays{
      static_cast<std::uint16_t>(fake_imxrt::adc_etc.TRIG[queues[0]].COUNTER),
      static_cast<std::uint16_t>(fake_imxrt::adc_etc.TRIG[queues[1]].COUNTER)};
  const std::array<std::uint16_t, 2U> effective_delays{
      static_cast<std::uint16_t>(raw_delays[0] + 1U),
      static_cast<std::uint16_t>(raw_delays[1] + 1U)};
  expect(raw_delays == std::array<std::uint16_t, 2U>{0U, 75U} &&
             effective_delays ==
                 std::array<std::uint16_t, 2U>{1U, 76U} &&
             effective_delays[1] - effective_delays[0] ==
                 v1::kAdcTriggerPhaseIpgCycles &&
             static_cast<std::uint32_t>(v1::kAdcTriggerPhaseIpgCycles) *
                     v1::kTimestampHz /
                     v1::kAdcTriggerIpgClockHz ==
                 v1::kAdc1PhaseTicks,
         "raw delays 0/75 implement effective 1/76 and exactly four ticks");
  expect(fake_imxrt::adc_etc.TRIG[queues[0]].CHAIN_1_0 ==
                 (ADC_ETC_TRIG_CHAIN_IE0(1U) |
                  ADC_ETC_TRIG_CHAIN_HWTS0(1U) |
                  ADC_ETC_TRIG_CHAIN_CSEL0(7U)) &&
             fake_imxrt::adc_etc.TRIG[queues[1]].CHAIN_1_0 ==
                 (ADC_ETC_TRIG_CHAIN_IE0(2U) |
                  ADC_ETC_TRIG_CHAIN_HWTS0(1U) |
                  ADC_ETC_TRIG_CHAIN_CSEL0(8U)) &&
             fake_imxrt::adc_etc.TRIG[3].CTRL == 0x00ABC000U,
         "queues 0/4 retain converter channels 7/8 and leave queue 3 intact");

  for (std::size_t index = 0U; index < xbar_before.size(); ++index) {
    const bool selected = index == v1::kAdcTriggerXbarOutputs[0] / 2U ||
                          index == v1::kAdcTriggerXbarOutputs[1] / 2U;
    if (!selected) {
      expect(fake_imxrt::xbara1_sel[index] == xbar_before[index],
             "ADC trigger setup leaves every unrelated XBAR select untouched");
    }
  }
  for (std::size_t converter = 0U; converter < 2U; ++converter) {
    const std::uint8_t output = v1::kAdcTriggerXbarOutputs[converter];
    const std::size_t index = output / 2U;
    expect((fake_imxrt::xbara1_sel[index] & 0xFF00U) ==
                   static_cast<std::uint16_t>(
                       static_cast<std::uint16_t>(
                           v1::kAdcTriggerXbarInputs[converter])
                       << 8U) &&
               (fake_imxrt::xbara1_sel[index] & 0x00FFU) ==
                   (xbar_before[index] & 0x00FFU),
           "each odd ADC_ETC XBAR output changes only its selected high byte");
  }
  expect((IMXRT_ADC1.CFG & ADC_CFG_ADTRG) != 0U &&
             (IMXRT_ADC2.CFG & ADC_CFG_ADTRG) != 0U &&
             IMXRT_ADC1.HC0 == ADC_HC_ADCH(16U) &&
             IMXRT_ADC2.HC0 == ADC_HC_ADCH(16U),
         "both fixed modules are bound to their ADC_ETC hardware trigger slot");
}

void testDeterministicArmStopOrderAndOwnedConflict() {
  resetFakeRegisters();
  trigger::TeensyPlatform platform{};
  expect(platform.configureStopped().error_flags == 0U,
         "arm-order fixture configures");

  fake_imxrt::clearRegisterWrites();
  expect(platform.armFromStopped(false),
         "production trigger arm succeeds from verified stopped state");
  const std::uint32_t enable_mask =
      (std::uint32_t{1U} << v1::kAdcTriggerQueues[0]) |
      (std::uint32_t{1U} << v1::kAdcTriggerQueues[1]);
  const std::uint32_t enabled_control =
      ADC_ETC_CTRL_PRE_DIVIDER(v1::kAdcTriggerPredivider) |
      ADC_ETC_CTRL_TRIG_ENABLE(enable_mask);
  const std::size_t etc_arm =
      writeIndex(fake_imxrt::adc_etc.CTRL, enabled_control);
  const std::size_t master_flag_reset = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel].TFLG,
      PIT_TFLG_TIF);
  const std::size_t pair_flag_reset = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel].TFLG,
      PIT_TFLG_TIF);
  const std::size_t master_reload = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel].LDVAL,
      v1::kAdcTriggerGpioMasterPitLoad);
  const std::size_t pair_reload = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel].LDVAL,
      v1::kAdcTriggerPairPitLoad);
  const std::size_t pair_arm = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel].TCTRL,
      PIT_TCTRL_CHN | PIT_TCTRL_TEN);
  const std::size_t master_arm = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel].TCTRL,
      PIT_TCTRL_TEN);
  expect(master_flag_reset < etc_arm && pair_flag_reset < etc_arm &&
             master_reload < etc_arm && pair_reload < etc_arm &&
             etc_arm < pair_arm && pair_arm < master_arm &&
             (static_cast<std::uint32_t>(ADC_ETC_CTRL) & 0xFFU) ==
                 enable_mask,
         "arm reloads the epoch, enables queues 0/4, then chained PIT1 and master PIT0");

  fake_imxrt::clearRegisterWrites();
  expect(platform.stop(), "trigger stop reaches verified stopped state");
  const std::size_t master_stop = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel].TCTRL, 0U);
  const std::size_t pair_stop = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel].TCTRL,
      PIT_TCTRL_CHN);
  const std::size_t etc_stop = writeIndex(
      fake_imxrt::adc_etc.CTRL,
      ADC_ETC_CTRL_PRE_DIVIDER(v1::kAdcTriggerPredivider));
  expect(master_stop < pair_stop && pair_stop < etc_stop &&
             (static_cast<std::uint32_t>(ADC_ETC_CTRL) & 0xFFU) == 0U,
         "stop disables master PIT0, chained PIT1, then both ADC_ETC queues");

  resetFakeRegisters();
  fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel].TCTRL.reset(
      PIT_TCTRL_CHN | PIT_TCTRL_TEN);
  fake_imxrt::clearRegisterWrites();
  trigger::TeensyPlatform conflicting{};
  const trigger::ConfigureResult rejected = conflicting.configureStopped();
  expect(rejected.error_flags == trigger::triggerError(
                                      v1::AdcTriggerError::kResourceBusy) &&
             rejected.configuration_flags == 0U &&
             fake_imxrt::register_write_count == 0U,
         "an active owned PIT1 rejects configuration before any register write");
}

std::uint32_t diagnostic_poll_count = 0U;

void publishDiagnosticCompletions() {
  ++diagnostic_poll_count;
  fake_imxrt::adc_etc.DONE2_ERR_IRQ.reset(0U);
  if (diagnostic_poll_count == 1U) {
    fake_imxrt::arm_dwt_cyccnt = 1'000U;
    fake_imxrt::adc_etc.DONE0_1_IRQ.reset(
        ADC_ETC_DONE0_1_IRQ_TRIG_DONE0(v1::kAdcTriggerQueues[0]));
  } else if (diagnostic_poll_count == 2U) {
    fake_imxrt::arm_dwt_cyccnt = 1'300U;
    fake_imxrt::adc_etc.DONE0_1_IRQ.reset(
        ADC_ETC_DONE0_1_IRQ_TRIG_DONE1(v1::kAdcTriggerQueues[1]));
  }
}

void testCompletionDiagnosticPollsHardwareStatusWithInterruptsMasked() {
  resetFakeRegisters();
  diagnostic_poll_count = 0U;
  fake_imxrt::adc_trigger_diagnostic_poll_hook =
      publishDiagnosticCompletions;
  trigger::TeensyPlatform platform{};
  expect(platform.configureStopped().error_flags == 0U &&
             platform.armFromStopped(true),
         "completion diagnostic arms from verified stopped state");

  const auto completion_counts = platform.completionCounts();
  const auto completion_cycles = platform.firstCompletionCycles();
  expect(completion_counts == std::array<std::uint32_t, 2U>{1U, 1U} &&
             completion_cycles ==
                 std::array<std::uint32_t, 2U>{1'000U, 1'300U},
         "diagnostic retains exactly the first 300-cycle-spaced DONE transitions (counts " +
             std::to_string(completion_counts[0]) + "/" +
             std::to_string(completion_counts[1]) + ", cycles " +
             std::to_string(completion_cycles[0]) + "/" +
             std::to_string(completion_cycles[1]) + ")");
  expect(!fake_imxrt::interrupt_enabled[IRQ_ADC_ETC0] &&
             !fake_imxrt::interrupt_enabled[IRQ_ADC_ETC1] &&
             !fake_imxrt::interrupt_enabled[IRQ_ADC_ETC_ERR] &&
             fake_imxrt::interrupt_vectors[IRQ_ADC_ETC0] == nullptr &&
             fake_imxrt::interrupt_vectors[IRQ_ADC_ETC1] == nullptr &&
             fake_imxrt::interrupts_enabled,
         "BOOT polling neither installs completion vectors nor leaks its interrupt mask");
  expect(platform.stop(), "latched completion diagnostic stops cleanly");

  resetFakeRegisters();
  diagnostic_poll_count = 0U;
  fake_imxrt::adc_trigger_diagnostic_poll_hook =
      publishDiagnosticCompletions;
  fake_imxrt::interrupts_enabled = false;
  trigger::TeensyPlatform masked_platform{};
  expect(masked_platform.configureStopped().error_flags == 0U &&
             masked_platform.armFromStopped(true) &&
             !fake_imxrt::interrupts_enabled,
         "BOOT polling preserves a caller's pre-existing global interrupt mask");
  __enable_irq();
  expect(masked_platform.stop(),
         "pre-masked completion diagnostic stops cleanly");
}

std::uint8_t selectedXbarInput(std::uint8_t output) {
  const std::uint16_t selected = fake_imxrt::xbara1_sel[output / 2U];
  return static_cast<std::uint8_t>(
      (output & 1U) == 0U ? selected & 0x00FFU
                          : (selected >> 8U) & 0x00FFU);
}

void testCombinedRegisterResourcesCoexistWithPriorityIsolation() {
  resetFakeRegisters();
  trigger::TeensyPlatform platform{};
  expect(platform.configureStopped().error_flags == 0U,
         "combined register fixture configures the ADC schedule stopped");

  gpio_route::configureXbarRequest();
  gpio_route::clearEdmaChannelState();
  gpio_route::configureEdmaPriority();
  gpio_route::enableEdmaRequest();
  expect(platform.armFromStopped(false),
         "combined register fixture arms the one common schedule");

  const std::uint32_t trigger_enable_mask =
      (std::uint32_t{1U} << v1::kAdcTriggerQueues[0]) |
      (std::uint32_t{1U} << v1::kAdcTriggerQueues[1]);
  expect(board::countOf(board::kPinAllocations) == 18U &&
             board::countOf(board::kPitAllocations) == 2U &&
             board::countOf(board::kXbarRoutes) == 4U &&
             board::countOf(board::kAdcEtcAllocations) == 2U &&
             board::countOf(board::kEdmaAllocations) == 4U &&
             board::countOf(board::kInterruptAllocations) == 5U &&
             board::kAcquisitionResourceContract.valid(),
         "the target registry allocates the complete combined resource set");
  expect(selectedXbarInput(board::kGpioXbarOutput) ==
                 board::kGpioXbarInput &&
             selectedXbarInput(v1::kAdcTriggerXbarOutputs[0]) ==
                 v1::kAdcTriggerXbarInputs[0] &&
             selectedXbarInput(v1::kAdcTriggerXbarOutputs[1]) ==
                 v1::kAdcTriggerXbarInputs[1] &&
             fake_imxrt::dmamux_chcfg[board::kGpioEdmaChannel] ==
                 gpio_route::kDmamuxConfiguration &&
             gpio_route::edmaPriority() == board::kGpioEdmaPriority,
         "GPIO XBAR/eDMA channel 2 coexists with both ADC_ETC XBAR routes");
  expect(fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel]
                     .LDVAL == v1::kAdcTriggerGpioMasterPitLoad &&
             fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel]
                     .TCTRL == PIT_TCTRL_TEN &&
             fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel]
                     .LDVAL == v1::kAdcTriggerPairPitLoad &&
             fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel]
                     .TCTRL == (PIT_TCTRL_CHN | PIT_TCTRL_TEN) &&
             (static_cast<std::uint32_t>(ADC_ETC_CTRL) &
              trigger_enable_mask) == trigger_enable_mask &&
             v1::kAdcTriggerGpioMasterRateHz /
                     v1::kAdcTriggerPairRateHz ==
                 4U &&
             v1::kGpioSamplesPerFrame * v1::kGpioSamplePeriodTicks ==
                 v1::kAdcPairsPerFrame * v1::kAdcPairPeriodTicks,
         "PIT0 produces four GPIO events per ADC pair with equal frame coverage");
  expect(board::kAdcEdmaPriorities[0] == 2U &&
             board::kAdcEdmaPriorities[1] == 1U &&
             board::kGpioEdmaPriority == 0U &&
             board::kAdcEdmaIrqPriority < board::kGpioEdmaIrqPriority,
         "fixed eDMA and IRQ tiers prioritize paired ADC completion over continuous GPIO traffic");

  expect(platform.stop(),
         "combined stop first disables PIT0/PIT1 and ADC_ETC");
  expect(gpio_route::edmaRequestBusy() &&
             gpio_route::selectedOutputBusy(),
         "common-source stop leaves GPIO DMA ownership intact until its explicit teardown");
  gpio_route::disableEdmaRequest();
  gpio_route::disableXbarRequest();
  expect(!gpio_route::edmaRequestBusy() &&
             !gpio_route::selectedOutputBusy() &&
             fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel]
                     .TCTRL == 0U &&
             fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel]
                     .TCTRL == PIT_TCTRL_CHN &&
             (static_cast<std::uint32_t>(ADC_ETC_CTRL) &
              trigger_enable_mask) == 0U,
         "GPIO request teardown follows the stopped common source and leaves every trigger disabled");
}

}  // namespace

void testRateAdapterIgnoresLatchedStatusAndPreservesFullDelay() {
  namespace rate = thingdaq::variable_rate;
  resetFakeRegisters();
  rate::TeensyRatePlatform platform;
  rate::Scheduler scheduler(platform);
  constexpr std::array<std::uint32_t, 4U> delays{75U, 150U, 300U, 600U};
  for (std::uint8_t index = 0U; index < 4U; ++index) {
    IMXRT_ADC_ETC.DMA_CTRL.reset(0x00110000U);
    const auto result = scheduler.configure(static_cast<thingdaq::protocol_v2::RateProfile>(index));
    expect(result.ok(), "latched boot completion flags do not reject rate setup");
    expect(IMXRT_ADC_ETC.DMA_CTRL == 0x00110000U,
           "rate setup leaves W1C completion evidence intact and DMA disabled");
    expect(IMXRT_ADC_ETC.TRIG[4].COUNTER == delays[index],
           "actual register delay retains all sixteen bits at every rate");
    IMXRT_ADC_ETC.DMA_CTRL.reset(0x00110001U);
    expect(!rate::registerReadbackMatches(scheduler.selected()),
           "enabled requests are not ignored as status");
  }
}

int main() {
  testInterruptGuardPreservesCallerAndEarlyReturns();
  testFixedPinModuleRoutesAndLegalResolutionModes();
  testExactStoppedTriggerScheduleAndResourceIsolation();
  testDeterministicArmStopOrderAndOwnedConflict();
  testCompletionDiagnosticPollsHardwareStatusWithInterruptsMasked();
  testCombinedRegisterResourcesCoexistWithPriorityIsolation();
  testRateAdapterIgnoresLatchedStatusAndPreservesFullDelay();
  if (failures != 0) {
    std::cerr << failures << " ADC register-adapter assertion(s) failed\n";
    return 1;
  }
  std::cout << "ADC register-adapter tests passed\n";
  return 0;
}
