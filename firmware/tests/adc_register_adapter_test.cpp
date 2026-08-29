#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#define ARDUINO_TEENSY40 1
#define __IMXRT1062__ 1
#define TEENSY_DAQ_HOST_REGISTER_TEST 1

// White-box inclusion is deliberate: this host executable exercises the
// production register adapters themselves against the narrow fake i.MX RT1062
// register surface, including helpers kept in their anonymous namespaces.
#include "../src/adc_initializer_teensy.cpp"
#include "../src/adc_trigger_teensy.cpp"

namespace {

namespace adc = teensy_daq::adc;
namespace board = teensy_daq::board;
namespace trigger = teensy_daq::adc_trigger;
namespace v1 = teensy_daq::protocol_v1;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
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
  const std::size_t pair_arm = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerPairPitChannel].TCTRL,
      PIT_TCTRL_CHN | PIT_TCTRL_TEN);
  const std::size_t master_arm = writeIndex(
      fake_imxrt::pit_channels[v1::kAdcTriggerGpioMasterPitChannel].TCTRL,
      PIT_TCTRL_TEN);
  expect(etc_arm < pair_arm && pair_arm < master_arm &&
             (static_cast<std::uint32_t>(ADC_ETC_CTRL) & 0xFFU) ==
                 enable_mask,
         "arm enables only queues 0/4 before chained PIT1 and master PIT0");

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

}  // namespace

int main() {
  testFixedPinModuleRoutesAndLegalResolutionModes();
  testExactStoppedTriggerScheduleAndResourceIsolation();
  testDeterministicArmStopOrderAndOwnedConflict();
  if (failures != 0) {
    std::cerr << failures << " ADC register-adapter assertion(s) failed\n";
    return 1;
  }
  std::cout << "ADC register-adapter tests passed\n";
  return 0;
}
