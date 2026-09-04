#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#define ARDUINO_TEENSY40 1
#define __IMXRT1062__ 1
#define THINGDAQ_HOST_REGISTER_TEST 1

// White-box inclusion is intentional: this executable runs the production
// target adapter, including its ISR and anonymous-namespace register helpers,
// against the narrow fake i.MX RT1062 register surface.
#include "../src/digital_output_teensy.cpp"

namespace {

namespace board = thingdaq::board;
namespace output = thingdaq::digital_output;
namespace v2 = thingdaq::protocol_v2;

int failures = 0;
alignas(32U) output::ProgramStorage g_program{};
alignas(32U) output::DmaBlockStorage g_blocks{};
alignas(32U) output::DmaDescriptorStorage g_descriptors{};

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

void resetFakeHardware() {
  fake_imxrt::ccm_cscmr1 = 0U;
  fake_imxrt::ccm_ccgr1 = 0U;
  fake_imxrt::ccm_ccgr2 = 0U;
  fake_imxrt::ccm_ccgr5 = 0U;
  fake_imxrt::pit_mcr = 0U;
  for (IMXRT_PIT_CHANNEL_t &pit : fake_imxrt::pit_channels) {
    pit = {};
  }
  fake_imxrt::xbara1_sel[0] = 0x00A5U;
  fake_imxrt::xbara1_ctrl[0] = 0x0013U;
  for (std::size_t index = 1U; index < 66U; ++index) {
    fake_imxrt::xbara1_sel[index] =
        static_cast<std::uint16_t>(0x4000U + index);
    fake_imxrt::xbara1_ctrl[index] =
        static_cast<std::uint16_t>(0x2000U + index);
  }
  for (std::size_t channel = 0U; channel < 32U; ++channel) {
    fake_imxrt::dmamux_chcfg[channel] = 0U;
    fake_imxrt::dma_tcd[channel] = {};
    fake_imxrt::dma_dchpri[channel] =
        static_cast<std::uint8_t>(0x40U + channel);
  }
  fake_imxrt::dma_erq = 0U;
  fake_imxrt::dma_err = 0U;
  fake_imxrt::dma_int = 0U;
  fake_imxrt::dma_cerq.reset();
  fake_imxrt::dma_cerr.reset();
  fake_imxrt::dma_ceei.reset();
  fake_imxrt::dma_cint.reset();
  fake_imxrt::dma_cdne.reset();
  fake_imxrt::dma_serq.reset();
  fake_imxrt::iomuxc_gpr_gpr26.reset(0xA0000000U |
                                     board::kAuxOutputGpio1Mask);
  fake_imxrt::gpio1_dr.reset(0x50001000U);
  fake_imxrt::gpio1_gdir.reset(0x30000C00U &
                               ~board::kAuxOutputGpio1Mask);
  fake_imxrt::gpio6_gdir = 0xC0000C00U &
                           ~board::kAuxOutputGpio1Mask;
  fake_imxrt::gpio1_dr_set.reset();
  fake_imxrt::gpio1_dr_clear.reset();
  fake_imxrt::gpio1_dr_toggle.reset();
  fake_imxrt::GpioAliasRegister::gpio_alias_writes_update_target = true;
  fake_imxrt::cache_flushes = {};
  fake_imxrt::cache_flush_count = 0U;
  fake_imxrt::interrupt_vectors.fill(nullptr);
  fake_imxrt::interrupt_priorities.fill(0U);
  fake_imxrt::interrupt_enabled.fill(false);
  fake_imxrt::interrupt_pending.fill(false);
  fake_imxrt::interrupts_enabled = true;
  fake_imxrt::clearRegisterWrites();
}

void commitProgram(output::TeensyOutput &target, std::uint32_t generation,
                   std::uint32_t repeats, std::uint32_t idle,
                   output::ProgramStorage &storage,
                   const output::Segment *segments, std::size_t count) {
  expect(target.begin(generation, repeats, idle) == output::ProgramStatus::kOk,
         "BEGIN accepts the isolated target fixture");
  for (std::size_t index = 0U; index < count; ++index) {
    expect(target.append(generation, segments[index]) ==
               output::ProgramStatus::kOk,
           "APPEND accepts each canonical target segment");
  }
  // Reproduce the canonical Adler-32 directly from the now-populated fixed
  // storage without sharing mutable lifecycle metadata with the target.
  std::uint32_t a = 1U;
  std::uint32_t b = 0U;
  for (std::size_t segment = 0U; segment < count; ++segment) {
    const std::uint32_t words[] = {storage.segments[segment].duration_samples,
                                   storage.segments[segment].logical_state_mask};
    for (std::uint32_t word : words) {
      for (std::size_t byte = 0U; byte < 4U; ++byte) {
        a = (a + ((word >> (8U * byte)) & 0xFFU)) % 65521U;
        b = (b + a) % 65521U;
      }
    }
  }
  expect(target.commit(generation, count, (b << 16U) | a) ==
             output::ProgramStatus::kOk,
         "COMMIT validates the independent canonical checksum");
}

void testExactArmPrepareCompletionClearAndRepeatedStop() {
  resetFakeHardware();
  output::TeensyOutput &target =
      output::teensyOutput(g_program, g_blocks, g_descriptors);
  const std::uint32_t initial_gpr = fake_imxrt::iomuxc_gpr_gpr26;
  const std::uint32_t initial_dr = fake_imxrt::gpio1_dr;
  const std::uint32_t initial_gdir = fake_imxrt::gpio1_gdir;
  const std::uint32_t initial_gpio6_gdir = fake_imxrt::gpio6_gdir;
  expect(fake_imxrt::register_write_count == 0U &&
             (initial_gpr & board::kAuxOutputGpio1Mask) ==
                 board::kAuxOutputGpio1Mask &&
             (initial_gdir & board::kAuxOutputGpio1Mask) == 0U,
         "factory construction leaves all eight pins as GPIO6 inputs");

  const output::Segment finite[] = {{4U, 0xA5U}, {3U, 0x3CU}};
  commitProgram(target, 71U, 1U, 0x12U, g_program, finite, 2U);
  expect((fake_imxrt::gpio1_gdir & board::kAuxOutputGpio1Mask) == 0U &&
             fake_imxrt::cache_flush_count == 0U,
         "upload and validation neither claim pins nor expose DMA memory");
  expect(target.arm(71U) == output::OperationStatus::kOk,
         "ARM claims the complete protected bank");
  const std::uint32_t physical_idle =
      output::physicalMaskForLogicalState(0x12U);
  const output::HardwareSnapshot armed = target.hardwareSnapshot();
  expect((armed.gpr26 & board::kAuxOutputGpio1Mask) == 0U &&
             (armed.gpr26 & ~board::kAuxOutputGpio1Mask) ==
                 (initial_gpr & ~board::kAuxOutputGpio1Mask) &&
             (armed.gpio1_gdir & board::kAuxOutputGpio1Mask) ==
                 board::kAuxOutputGpio1Mask &&
             (armed.gpio1_gdir & ~board::kAuxOutputGpio1Mask) ==
                 (initial_gdir & ~board::kAuxOutputGpio1Mask) &&
             (armed.gpio1_dr & board::kAuxOutputGpio1Mask) == physical_idle &&
             (armed.gpio1_dr & ~board::kAuxOutputGpio1Mask) ==
                 (initial_dr & ~board::kAuxOutputGpio1Mask) &&
             fake_imxrt::gpio6_gdir == initial_gpio6_gdir,
         "ARM changes only the exact mux, latch, and all-eight direction mask");
  expect(fake_imxrt::cache_flush_count == 2U &&
             fake_imxrt::cache_flushes[0].first == g_blocks.blocks[0].data() &&
             fake_imxrt::cache_flushes[0].second == 7U * sizeof(std::uint32_t) &&
             fake_imxrt::cache_flushes[1].first ==
                 g_descriptors.descriptors[0].data() &&
             fake_imxrt::cache_flushes[1].second == sizeof(IMXRT_DMA_TCD_t),
         "ARM flushes the complete source block and descriptor before publication");

  const std::uint16_t xbar_select_before = fake_imxrt::xbara1_sel[0];
  const std::uint16_t xbar_control_before = fake_imxrt::xbara1_ctrl[0];
  expect(target.prepareStart(501U, 1000U) == output::StartStatus::kOk,
         "target prepares the fixed channel without clocking PIT");
  const output::HardwareSnapshot prepared = target.hardwareSnapshot();
  const IMXRT_DMA_TCD_t &tcd = fake_imxrt::dma_tcd[3];
  expect(prepared.hardware_prepared && !prepared.hardware_running &&
             fake_imxrt::pit_channels[0].TCTRL == 0U &&
             fake_imxrt::pit_channels[1].TCTRL == 0U &&
             tcd.SADDR == g_blocks.blocks[prepared.engine.reading_block].data() &&
             tcd.SOFF == 4 && tcd.ATTR ==
                 (DMA_TCD_ATTR_SSIZE(2U) | DMA_TCD_ATTR_DSIZE(2U)) &&
             tcd.NBYTES_MLNO == 4U && tcd.DADDR == &GPIO1_DR_TOGGLE &&
             tcd.DOFF == 0 && tcd.CITER_ELINKNO == 7U &&
             tcd.BITER_ELINKNO == 7U &&
             (tcd.CSR & (DMA_TCD_CSR_DREQ | DMA_TCD_CSR_INTMAJOR)) ==
                 (DMA_TCD_CSR_DREQ | DMA_TCD_CSR_INTMAJOR),
         "prepared channel 3 has the exact GPIO1 toggle TCD and no output edge");
  expect((fake_imxrt::xbara1_sel[0] & 0x00FFU) ==
                 (xbar_select_before & 0x00FFU) &&
             ((fake_imxrt::xbara1_sel[0] >> 8U) & 0xFFU) ==
                 board::kAuxOutputXbarInput &&
             (fake_imxrt::xbara1_ctrl[0] & 0x00FEU) ==
                 (xbar_control_before & 0x00FEU) &&
             prepared.dmamux_chcfg ==
                 (DMAMUX_CHCFG_ENBL | board::kAuxOutputDmamuxSource) &&
             (prepared.dma_erq & (std::uint32_t{1U} << 3U)) != 0U &&
             prepared.edma_priority == board::kAuxOutputEdmaPriority &&
             fake_imxrt::interrupt_priorities[IRQ_DMA_CH3] ==
                 board::kAuxOutputEdmaIrqPriority &&
             fake_imxrt::interrupt_enabled[IRQ_DMA_CH3],
         "XBAR peer lanes, DMAMUX source, channel priority, and IRQ are exact");

  target.rollbackPreparedStart();
  expect(target.snapshot().state == v2::OutputState::kArmed &&
             target.snapshot().telemetry.dma_states_emitted == 0U &&
             (fake_imxrt::dma_erq & (std::uint32_t{1U} << 3U)) == 0U &&
             (fake_imxrt::xbara1_ctrl[0] & 0x1F00U) == 0x0100U,
         "pre-clock rollback emits no state and disables every output request");

  expect(target.prepareStart(501U, 1000U) == output::StartStatus::kOk,
         "rolled-back output can be prepared again");
  target.commitCommonStart();
  expect(target.snapshot().state == v2::OutputState::kRunning,
         "common commit publishes RUNNING only after target preparation");
  fake_imxrt::gpio1_dr.reset(
      (initial_dr & ~board::kAuxOutputGpio1Mask) |
      output::physicalMaskForLogicalState(0x3CU));
  fake_imxrt::dma_tcd[3].CITER_ELINKNO = 0U;
  fake_imxrt::dma_tcd[3].CSR |= DMA_TCD_CSR_DONE;
  expect(fake_imxrt::interrupt_vectors[IRQ_DMA_CH3] != nullptr,
         "channel 3 completion vector is installed");
  fake_imxrt::interrupt_vectors[IRQ_DMA_CH3]();
  const output::HardwareSnapshot held = target.hardwareSnapshot();
  expect(held.engine.state == v2::OutputState::kHeld &&
             held.engine.last_emitted_state_mask == 0x3CU &&
             held.engine.telemetry.dma_states_emitted == 7U &&
             held.engine.conservation_exact && !held.hardware_running &&
             (held.dma_erq & (std::uint32_t{1U} << 3U)) == 0U &&
             (held.gpio1_gdir & board::kAuxOutputGpio1Mask) ==
                 board::kAuxOutputGpio1Mask,
         "ISR completion holds the final physical latch and conserves the run");
  expect(target.clear() == output::OperationStatus::kOk,
         "CLEAR releases a completed target run");
  const output::HardwareSnapshot cleared = target.hardwareSnapshot();
  expect(cleared.engine.state == v2::OutputState::kEmpty &&
             cleared.engine.bank_mode == v2::OutputBankMode::kDisabled &&
             (cleared.gpio1_gdir & board::kAuxOutputGpio1Mask) == 0U &&
             (cleared.gpio6_gdir & board::kAuxOutputGpio1Mask) == 0U &&
             (cleared.gpr26 & board::kAuxOutputGpio1Mask) ==
                 board::kAuxOutputGpio1Mask,
         "CLEAR erases state and returns all D16-D23 aliases to inputs");

  const output::Segment infinite[] = {{1U, 0x01U}, {1U, 0x80U}};
  commitProgram(target, 72U, 0U, 0U, g_program, infinite, 2U);
  expect(target.arm(72U) == output::OperationStatus::kOk &&
             target.prepareStart(502U, 2000U) == output::StartStatus::kOk,
         "a second lifecycle reuses the fully released resources");
  target.commitCommonStart();
  fake_imxrt::dma_tcd[3].CITER_ELINKNO =
      static_cast<std::uint16_t>(fake_imxrt::dma_tcd[3].BITER_ELINKNO - 3U);
  fake_imxrt::gpio1_dr.reset(
      (initial_dr & ~board::kAuxOutputGpio1Mask) |
      output::physicalMaskForLogicalState(0x01U));
  fake_imxrt::pit_channels[0].TCTRL = PIT_TCTRL_TEN;
  fake_imxrt::pit_channels[1].TCTRL = PIT_TCTRL_CHN | PIT_TCTRL_TEN;
  fake_imxrt::adc_etc.CTRL.reset(ADC_ETC_CTRL_TRIG_ENABLE(0x11U));
  const output::StopReport stopped = target.stopAfterTriggers();
  expect(stopped.ok() && stopped.active_states_emitted == 3U &&
             stopped.held_state_mask == 0x01U && stopped.dma_quiesced &&
             fake_imxrt::pit_channels[0].TCTRL == 0U &&
             fake_imxrt::pit_channels[1].TCTRL == PIT_TCTRL_CHN &&
             (static_cast<std::uint32_t>(fake_imxrt::adc_etc.CTRL) & 0xFFU) == 0U,
         "STOP disables the shared trigger first, quiesces DMA, and holds latch");
  expect(target.clear() == output::OperationStatus::kOk,
         "repeated STOP lifecycle clears successfully");
}

void testFailClosedResourceReadbackAndDmaFaults() {
  resetFakeHardware();
  output::TeensyOutput &target =
      output::teensyOutput(g_program, g_blocks, g_descriptors);
  // The singleton was cleared by the preceding lifecycle; bind calls are
  // otherwise deliberately side-effect free.
  const output::Segment finite[] = {{8U, 0x55U}};
  commitProgram(target, 73U, 1U, 0x01U, g_program, finite, 1U);
  fake_imxrt::dmamux_chcfg[3] = DMAMUX_CHCFG_ENBL | 7U;
  expect(target.arm(73U) == output::OperationStatus::kNotReady &&
             (fake_imxrt::gpio1_gdir & board::kAuxOutputGpio1Mask) == 0U &&
             target.hardwareSnapshot().resource_conflicts == 1U,
         "resource conflict rejects ARM without changing a pin to output");
  fake_imxrt::dmamux_chcfg[3] = 0U;
  fake_imxrt::GpioAliasRegister::gpio_alias_writes_update_target = false;
  expect(target.arm(73U) == output::OperationStatus::kNotReady &&
             (fake_imxrt::gpio1_gdir & board::kAuxOutputGpio1Mask) == 0U &&
             (fake_imxrt::iomuxc_gpr_gpr26 & board::kAuxOutputGpio1Mask) ==
                 board::kAuxOutputGpio1Mask,
         "latch readback failure rolls mux and directions back to safe inputs");
  fake_imxrt::GpioAliasRegister::gpio_alias_writes_update_target = true;
  expect(target.arm(73U) == output::OperationStatus::kOk &&
             target.prepareStart(503U, 3000U) == output::StartStatus::kOk,
         "readback-failure fixture remains reusable after rollback");
  target.commitCommonStart();
  fake_imxrt::gpio1_dr.reset(
      output::physicalMaskForLogicalState(0x55U));
  fake_imxrt::dma_tcd[3].CITER_ELINKNO =
      static_cast<std::uint16_t>(fake_imxrt::dma_tcd[3].BITER_ELINKNO - 2U);
  fake_imxrt::dma_err = std::uint32_t{1U} << 3U;
  fake_imxrt::pit_channels[0].TCTRL = PIT_TCTRL_TEN;
  fake_imxrt::pit_channels[1].TCTRL = PIT_TCTRL_CHN | PIT_TCTRL_TEN;
  expect(fake_imxrt::interrupt_vectors[IRQ_DMA_CH3] != nullptr,
         "fault lifecycle installs the channel 3 vector");
  if (fake_imxrt::interrupt_vectors[IRQ_DMA_CH3] != nullptr) {
    fake_imxrt::interrupt_vectors[IRQ_DMA_CH3]();
  }
  const output::HardwareSnapshot faulted = target.hardwareSnapshot();
  expect(faulted.engine.state == v2::OutputState::kFaulted &&
             faulted.engine.error == v2::OutputError::kDmaFault &&
             faulted.engine.last_emitted_state_mask == 0x55U &&
             faulted.engine.telemetry.dma_errors == 1U &&
             faulted.engine.conservation_exact &&
             fake_imxrt::pit_channels[0].TCTRL == 0U &&
             fake_imxrt::pit_channels[1].TCTRL == PIT_TCTRL_CHN &&
             (faulted.gpio1_gdir & board::kAuxOutputGpio1Mask) ==
                 board::kAuxOutputGpio1Mask,
         "DMA error stops the common trigger and preserves a driven fault hold");
  fake_imxrt::dma_err = 0U;
  expect(target.clear() == output::OperationStatus::kOk,
         "fault-held lifecycle can be explicitly released to inputs");
}

}  // namespace

int main() {
  testExactArmPrepareCompletionClearAndRepeatedStop();
  testFailClosedResourceReadbackAndDmaFaults();
  if (failures != 0) {
    std::cerr << failures << " Teensy output target assertion(s) failed\n";
    return 1;
  }
  std::cout << "Teensy output target tests passed\n";
  return 0;
}
