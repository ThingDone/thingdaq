#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#define ARDUINO_TEENSY40 1
#define __IMXRT1062__ 1

#include "gpio_dma_route_teensy.h"
#include "gpio_raw_capture.h"

namespace {

namespace board = thingdaq::board;
namespace capture = thingdaq::gpio_capture;
namespace route = thingdaq::gpio_dma_route;

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
  fake_imxrt::dma_erq = 0U;
  fake_imxrt::dma_cerq = 0xFFU;
  fake_imxrt::dma_cerr = 0xFFU;
  fake_imxrt::dma_ceei = 0xFFU;
  fake_imxrt::dma_cint = 0xFFU;
  fake_imxrt::dma_cdne = 0xFFU;
  fake_imxrt::dma_serq = 0xFFU;
  for (std::size_t index = 0U; index < 4U; ++index) {
    fake_imxrt::pit_channels[index].LDVAL =
        static_cast<std::uint32_t>(0x1000U + index);
    fake_imxrt::pit_channels[index].CVAL =
        static_cast<std::uint32_t>(0x2000U + index);
    fake_imxrt::pit_channels[index].TCTRL =
        static_cast<std::uint32_t>(0x3000U + index);
    fake_imxrt::pit_channels[index].TFLG =
        static_cast<std::uint32_t>(0x4000U + index);
  }
  for (std::size_t index = 0U; index < 66U; ++index) {
    fake_imxrt::xbara1_sel[index] =
        static_cast<std::uint16_t>(0x5000U + index);
    fake_imxrt::xbara1_ctrl[index] =
        static_cast<std::uint16_t>(0x6000U + index);
  }
  for (std::size_t index = 0U; index < 32U; ++index) {
    fake_imxrt::dmamux_chcfg[index] =
        static_cast<std::uint32_t>(0x7000U + index);
    fake_imxrt::dma_tcd[index].marker =
        static_cast<std::uint32_t>(0x8000U + index);
    fake_imxrt::dma_dchpri[index] =
        static_cast<std::uint8_t>(0x40U + index);
  }
}

void testGpioAliasAndDirectionIsolation() {
  volatile std::uint32_t gpr27 = 0xF5A55A5FU;
  volatile std::uint32_t gdir = 0xA55AA55AU;
  const std::uint32_t gpr27_before = gpr27;
  const std::uint32_t gdir_before = gdir;

  capture::selectStandardGpioInputs(gpr27, gdir);

  expect(gpr27 ==
                 (gpr27_before & ~board::kGpio7ToGpio2Gpr27ClearMask) &&
             gdir == (gdir_before & ~board::kGpio2PsrCaptureMask),
         "GPR27 and GDIR clear exactly the eight D6-D13 GPIO2 bits");
  expect(((gpr27 ^ gpr27_before) &
          ~board::kGpio7ToGpio2Gpr27ClearMask) == 0U &&
             ((gdir ^ gdir_before) & ~board::kGpio2PsrCaptureMask) == 0U,
         "GPR27 and GDIR preserve every unrelated bit");
}

void testOnlyReservedPitAndClockGatesChange() {
  resetFakeRegisters();
  fake_imxrt::ccm_cscmr1 = 0xA5A5F0F0U;
  fake_imxrt::ccm_ccgr1 = 0x01010101U;
  fake_imxrt::ccm_ccgr2 = 0x02020202U;
  fake_imxrt::ccm_ccgr5 = 0x04040404U;
  fake_imxrt::pit_mcr = 0xFFFFFFFFU;
  const std::uint32_t cscmr1_before = fake_imxrt::ccm_cscmr1;
  const std::uint32_t ccgr1_before = fake_imxrt::ccm_ccgr1;
  const std::uint32_t ccgr2_before = fake_imxrt::ccm_ccgr2;
  const std::uint32_t ccgr5_before = fake_imxrt::ccm_ccgr5;
  const std::uint32_t pit_mcr_before = fake_imxrt::pit_mcr;
  std::array<std::array<std::uint32_t, 4U>, 4U> pit_before{};
  for (std::size_t channel = 0U; channel < pit_before.size(); ++channel) {
    pit_before[channel] = {
        fake_imxrt::pit_channels[channel].LDVAL,
        fake_imxrt::pit_channels[channel].CVAL,
        fake_imxrt::pit_channels[channel].TCTRL,
        fake_imxrt::pit_channels[channel].TFLG,
    };
  }

  route::enableClockGates();
  route::configureStoppedPit(5U);

  expect(fake_imxrt::ccm_ccgr1 == (ccgr1_before | route::kPitGateMask) &&
             fake_imxrt::ccm_ccgr2 ==
                 (ccgr2_before | route::kXbarGateMask) &&
             fake_imxrt::ccm_ccgr5 ==
                 (ccgr5_before | route::kDmaGateMask),
         "clock setup is enable-only for the reserved PIT, XBAR, and DMA gates");
  expect((fake_imxrt::ccm_cscmr1 & ~route::kPerclkMask) ==
                 (cscmr1_before & ~route::kPerclkMask) &&
             (fake_imxrt::ccm_cscmr1 & route::kPerclkMask) ==
                 route::kPerclk24M &&
             fake_imxrt::pit_mcr ==
                 (pit_mcr_before & ~PIT_MCR_MDIS),
         "PIT setup preserves unrelated clock and module-control bits");

  const IMXRT_PIT_CHANNEL_t &selected =
      fake_imxrt::pit_channels[board::kGpioPitChannel];
  expect(selected.LDVAL == 5U && selected.TCTRL == 0U &&
             selected.TFLG == PIT_TFLG_TIF &&
             selected.CVAL == pit_before[board::kGpioPitChannel][1],
         "PIT setup changes only the stopped configuration of reserved PIT0");
  for (std::size_t channel = 1U; channel < pit_before.size(); ++channel) {
    const IMXRT_PIT_CHANNEL_t &pit = fake_imxrt::pit_channels[channel];
    expect(pit.LDVAL == pit_before[channel][0] &&
               pit.CVAL == pit_before[channel][1] &&
               pit.TCTRL == pit_before[channel][2] &&
               pit.TFLG == pit_before[channel][3],
           "PIT setup leaves every unreserved channel untouched");
  }
}

void testOnlyReservedXbarOutputChanges() {
  resetFakeRegisters();
  const std::size_t selected_index = board::kGpioXbarOutput / 2U;
  fake_imxrt::xbara1_sel[selected_index] = 0xA5D3U;
  fake_imxrt::xbara1_ctrl[selected_index] = 0xFFFFU;
  std::array<std::uint16_t, 66U> select_before{};
  std::array<std::uint16_t, 66U> control_before{};
  for (std::size_t index = 0U; index < select_before.size(); ++index) {
    select_before[index] = fake_imxrt::xbara1_sel[index];
    control_before[index] = fake_imxrt::xbara1_ctrl[index];
  }

  route::configureXbarRequest();

  const std::uint16_t selected_route = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(board::kGpioXbarInput)
      << route::kXbarSelectionShift);
  expect((fake_imxrt::xbara1_sel[selected_index] &
          route::kXbarSelectionMask) == selected_route &&
             ((fake_imxrt::xbara1_sel[selected_index] ^
               select_before[selected_index]) &
              static_cast<std::uint16_t>(~route::kXbarSelectionMask)) == 0U,
         "XBAR setup selects the reserved PIT input without changing its peer byte");
  expect((fake_imxrt::xbara1_ctrl[selected_index] &
          route::kXbarSelectedConfigurationMask) ==
                 route::kXbarSelectedConfiguration &&
             route::selectedOutputBusy(),
         "XBAR setup enables exactly the reserved DMA output edge request");
  for (std::size_t index = 0U; index < select_before.size(); ++index) {
    if (index == selected_index) {
      continue;
    }
    expect(fake_imxrt::xbara1_sel[index] == select_before[index] &&
               fake_imxrt::xbara1_ctrl[index] == control_before[index],
           "XBAR setup leaves all other route registers untouched");
  }

  const std::uint16_t selection_configured =
      fake_imxrt::xbara1_sel[selected_index];
  route::disableXbarRequest();
  expect(fake_imxrt::xbara1_sel[selected_index] == selection_configured &&
             (fake_imxrt::xbara1_ctrl[selected_index] &
              route::kXbarSelectedConfigurationMask) ==
                 route::kXbarSelectedStatus &&
             !route::selectedOutputBusy(),
         "XBAR shutdown disables only the reserved output request");
}

void testOnlyReservedEdmaChannelChanges() {
  resetFakeRegisters();
  std::array<std::uint32_t, 32U> dmamux_before{};
  std::array<std::uint32_t, 32U> tcd_before{};
  std::array<std::uint8_t, 32U> priority_before{};
  for (std::size_t channel = 0U; channel < dmamux_before.size(); ++channel) {
    dmamux_before[channel] = fake_imxrt::dmamux_chcfg[channel];
    tcd_before[channel] = fake_imxrt::dma_tcd[channel].marker;
    priority_before[channel] = fake_imxrt::dma_dchpri[channel];
  }

  fake_imxrt::dma_erq = std::uint32_t{1U} << 7U;
  expect(!route::edmaRequestBusy(),
         "an unrelated active eDMA channel is not a GPIO resource conflict");
  fake_imxrt::dma_erq |= route::kEdmaChannelMask;
  expect(route::edmaRequestBusy(),
         "the reserved eDMA channel is detected as busy");
  fake_imxrt::dma_erq = 0U;

  route::clearEdmaChannelState();
  route::configureEdmaPriority();
  route::edmaTcd().marker = 0xDEADBEEFU;
  route::enableEdmaRequest();

  expect(fake_imxrt::dma_cerq == board::kGpioEdmaChannel &&
             fake_imxrt::dma_cerr == board::kGpioEdmaChannel &&
             fake_imxrt::dma_ceei == board::kGpioEdmaChannel &&
             fake_imxrt::dma_cint == board::kGpioEdmaChannel &&
             fake_imxrt::dma_cdne == board::kGpioEdmaChannel &&
             fake_imxrt::dma_serq == board::kGpioEdmaChannel,
         "all eDMA command writes name only reserved channel 2");
  expect(fake_imxrt::dmamux_chcfg[board::kGpioEdmaChannel] ==
                 route::kDmamuxConfiguration &&
             route::edmaPriority() == board::kGpioEdmaPriority &&
             fake_imxrt::dma_tcd[board::kGpioEdmaChannel].marker ==
                 0xDEADBEEFU,
         "DMAMUX, priority, and TCD access resolve to reserved channel 2");
  for (std::size_t channel = 0U; channel < dmamux_before.size(); ++channel) {
    if (channel == board::kGpioEdmaChannel) {
      continue;
    }
    expect(fake_imxrt::dmamux_chcfg[channel] == dmamux_before[channel] &&
               fake_imxrt::dma_tcd[channel].marker == tcd_before[channel] &&
               fake_imxrt::dma_dchpri[channel] == priority_before[channel],
           "eDMA setup leaves every unreserved channel register untouched");
  }

  route::disableEdmaRequest();
  expect(fake_imxrt::dma_cerq == board::kGpioEdmaChannel &&
             fake_imxrt::dmamux_chcfg[board::kGpioEdmaChannel] == 0U,
         "eDMA shutdown clears only the reserved channel request");
}

}  // namespace

int main() {
  testGpioAliasAndDirectionIsolation();
  testOnlyReservedPitAndClockGatesChange();
  testOnlyReservedXbarOutputChanges();
  testOnlyReservedEdmaChannelChanges();
  if (failures != 0) {
    std::cerr << failures << " GPIO register assertion(s) failed\n";
    return 1;
  }
  std::cout << "GPIO register configuration tests passed\n";
  return 0;
}
