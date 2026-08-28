#pragma once

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstdint>

#include "board_config.h"

namespace teensy_daq::gpio_dma_route {

inline constexpr std::uint32_t kPerclkMask =
    CCM_CSCMR1_PERCLK_CLK_SEL | CCM_CSCMR1_PERCLK_PODF(0x3FU);
inline constexpr std::uint32_t kPerclk24M = CCM_CSCMR1_PERCLK_CLK_SEL;
inline constexpr std::uint32_t kPitGateMask =
    CCM_CCGR1_PIT(CCM_CCGR_ON);
inline constexpr std::uint32_t kXbarGateMask =
    CCM_CCGR2_XBAR1(CCM_CCGR_ON);
inline constexpr std::uint32_t kDmaGateMask =
    CCM_CCGR5_DMA(CCM_CCGR_ON);
inline constexpr bool kXbarUsesHighByte =
    (board::kGpioXbarOutput & 1U) != 0U;
inline constexpr std::uint16_t kXbarSelectedStatus =
    kXbarUsesHighByte ? XBARA_CTRL_STS1 : XBARA_CTRL_STS0;
inline constexpr std::uint16_t kXbarSelectedEdge =
    kXbarUsesHighByte ? XBARA_CTRL_EDGE1(board::kGpioXbarActiveEdge)
                      : XBARA_CTRL_EDGE0(board::kGpioXbarActiveEdge);
inline constexpr std::uint16_t kXbarSelectedInterruptEnable =
    kXbarUsesHighByte ? XBARA_CTRL_IEN1 : XBARA_CTRL_IEN0;
inline constexpr std::uint16_t kXbarSelectedDmaEnable =
    kXbarUsesHighByte ? XBARA_CTRL_DEN1 : XBARA_CTRL_DEN0;
inline constexpr std::uint16_t kXbarPeerStatus =
    kXbarUsesHighByte ? XBARA_CTRL_STS0 : XBARA_CTRL_STS1;
inline constexpr std::uint16_t kXbarSelectedConfigurationMask =
    kXbarSelectedStatus | kXbarSelectedEdge |
    kXbarSelectedInterruptEnable | kXbarSelectedDmaEnable;
inline constexpr std::uint16_t kXbarSelectedConfiguration =
    kXbarSelectedStatus | kXbarSelectedEdge | kXbarSelectedDmaEnable;
inline constexpr std::uint16_t kXbarSelectionMask =
    kXbarUsesHighByte ? 0xFF00U : 0x00FFU;
inline constexpr std::uint8_t kXbarSelectionShift =
    kXbarUsesHighByte ? 8U : 0U;

inline void barrier() {
  __asm__ volatile("dsb\n\tisb" : : : "memory");
}

inline volatile std::uint16_t *xbarSelectRegister() {
  return &XBARA1_SEL0 + board::kGpioXbarOutput / 2U;
}

inline volatile std::uint16_t *xbarControlRegister() {
  return &XBARA1_CTRL0 + board::kGpioXbarOutput / 2U;
}

inline bool selectedOutputBusy() {
  return (*xbarControlRegister() &
          (kXbarSelectedEdge | kXbarSelectedInterruptEnable |
           kXbarSelectedDmaEnable)) != 0U;
}

inline void enableClockGates() {
  CCM_CCGR1 |= kPitGateMask;
  CCM_CCGR2 |= kXbarGateMask;
  CCM_CCGR5 |= kDmaGateMask;
}

inline void configureStoppedPit(std::uint32_t load_value) {
  CCM_CSCMR1 = (CCM_CSCMR1 & ~kPerclkMask) | kPerclk24M;
  PIT_MCR &= ~PIT_MCR_MDIS;
  IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  pit.TCTRL = 0U;
  pit.TFLG = PIT_TFLG_TIF;
  pit.LDVAL = load_value;
}

inline void configureXbarRequest() {
  volatile std::uint16_t *const select_register = xbarSelectRegister();
  std::uint16_t selection = *select_register;
  selection = static_cast<std::uint16_t>(
      (selection & static_cast<std::uint16_t>(~kXbarSelectionMask)) |
      (static_cast<std::uint16_t>(board::kGpioXbarInput)
       << kXbarSelectionShift));
  *select_register = selection;

  volatile std::uint16_t *const control_register = xbarControlRegister();
  std::uint16_t control = *control_register;
  control = static_cast<std::uint16_t>(
      control &
      static_cast<std::uint16_t>(~(kXbarSelectedConfigurationMask |
                                   kXbarPeerStatus)));
  *control_register = static_cast<std::uint16_t>(
      control | kXbarSelectedConfiguration);
}

inline void disableXbarRequest() {
  volatile std::uint16_t *const control_register = xbarControlRegister();
  std::uint16_t control = *control_register;
  control = static_cast<std::uint16_t>(
      control &
      static_cast<std::uint16_t>(~(kXbarSelectedConfigurationMask |
                                   kXbarPeerStatus)));
  *control_register =
      static_cast<std::uint16_t>(control | kXbarSelectedStatus);
}

}  // namespace teensy_daq::gpio_dma_route

#endif
