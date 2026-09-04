#pragma once

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstdint>

#include "board_config.h"

namespace thingdaq::gpio_dma_route {

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
    board::kGpioXbarSelectionMask;
inline constexpr std::uint8_t kXbarSelectionShift =
    kXbarUsesHighByte ? 8U : 0U;
inline constexpr std::uint32_t kEdmaChannelMask =
    std::uint32_t{1U} << board::kGpioEdmaChannel;
inline constexpr std::uint32_t kDmamuxConfiguration =
    DMAMUX_CHCFG_ENBL | board::kGpioDmamuxSource;
inline constexpr std::uint32_t kAuxEdmaChannelMask =
    std::uint32_t{1U} << board::kAuxGpioEdmaChannel;
inline constexpr std::uint32_t kPairedEdmaChannelMask =
    kEdmaChannelMask | kAuxEdmaChannelMask;
inline constexpr std::uint32_t kAuxDmamuxConfiguration =
    DMAMUX_CHCFG_ENBL | board::kAuxGpioDmamuxSource;
inline constexpr std::uint16_t kPairedXbarEdgeMask =
    XBARA_CTRL_EDGE0(3U) | XBARA_CTRL_EDGE1(3U);
inline constexpr std::uint16_t kPairedXbarInterruptMask =
    XBARA_CTRL_IEN0 | XBARA_CTRL_IEN1;
inline constexpr std::uint16_t kPairedXbarDmaMask =
    XBARA_CTRL_DEN0 | XBARA_CTRL_DEN1;
inline constexpr std::uint16_t kPairedXbarStatusMask =
    XBARA_CTRL_STS0 | XBARA_CTRL_STS1;
inline constexpr std::uint16_t kPairedXbarConfigurationMask =
    kPairedXbarEdgeMask | kPairedXbarInterruptMask |
    kPairedXbarDmaMask | kPairedXbarStatusMask;
inline constexpr std::uint16_t kPairedXbarConfiguration =
    kPairedXbarStatusMask |
    XBARA_CTRL_EDGE0(board::kGpioXbarActiveEdge) |
    XBARA_CTRL_EDGE1(board::kGpioXbarActiveEdge) |
    kPairedXbarDmaMask;

inline void barrier() {
#if defined(THINGDAQ_HOST_REGISTER_TEST)
  __asm__ volatile("" : : : "memory");
#else
  __asm__ volatile("dsb\n\tisb" : : : "memory");
#endif
}

inline volatile std::uint16_t *xbarSelectRegister() {
  return &XBARA1_SEL0 + board::kGpioXbarOutput / 2U;
}

inline volatile std::uint16_t *xbarControlRegister() {
  return &XBARA1_CTRL0 + board::kGpioXbarOutput / 2U;
}

inline volatile std::uint32_t *dmamuxChannelRegister() {
  return &DMAMUX_CHCFG0 + board::kGpioEdmaChannel;
}

inline IMXRT_DMA_TCD_t &edmaTcd() {
  return IMXRT_DMA_TCD[board::kGpioEdmaChannel];
}

inline volatile std::uint32_t *auxDmamuxChannelRegister() {
  return &DMAMUX_CHCFG0 + board::kAuxGpioEdmaChannel;
}

inline IMXRT_DMA_TCD_t &auxEdmaTcd() {
  return IMXRT_DMA_TCD[board::kAuxGpioEdmaChannel];
}

inline bool selectedOutputBusy() {
  return (*xbarControlRegister() &
          (kXbarSelectedEdge | kXbarSelectedInterruptEnable |
           kXbarSelectedDmaEnable)) != 0U;
}

inline bool edmaRequestBusy() {
  return (DMA_ERQ & kEdmaChannelMask) != 0U ||
         (*dmamuxChannelRegister() & DMAMUX_CHCFG_ENBL) != 0U;
}

inline bool pairedEdmaRequestBusy() {
  return edmaRequestBusy() ||
         (DMA_ERQ & kAuxEdmaChannelMask) != 0U ||
         (*auxDmamuxChannelRegister() & DMAMUX_CHCFG_ENBL) != 0U;
}

inline bool pairedOutputsBusy() {
  return (*xbarControlRegister() &
          (kPairedXbarEdgeMask | kPairedXbarInterruptMask |
           kPairedXbarDmaMask)) != 0U;
}

inline void enableClockGates() {
  CCM_CCGR1 |= kPitGateMask;
  CCM_CCGR2 |= kXbarGateMask;
  CCM_CCGR5 |= kDmaGateMask;
}

inline void configureStoppedPit(std::uint32_t load_value,
                                bool clear_pending_flag = true) {
  CCM_CSCMR1 = (CCM_CSCMR1 & ~kPerclkMask) | kPerclk24M;
  PIT_MCR &= ~PIT_MCR_MDIS;
  IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  pit.TCTRL = 0U;
  if (clear_pending_flag) {
    pit.TFLG = PIT_TFLG_TIF;
  }
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

inline void configurePairedXbarRequests() {
  volatile std::uint16_t *const selection = xbarSelectRegister();
  *selection = static_cast<std::uint16_t>(
      (*selection &
       static_cast<std::uint16_t>(~board::kPairedGpioXbarSelectionMask)) |
      static_cast<std::uint16_t>(board::kGpioXbarInput) |
      static_cast<std::uint16_t>(
          static_cast<std::uint16_t>(board::kAuxGpioXbarInput) << 8U));
  volatile std::uint16_t *const control = xbarControlRegister();
  *control = static_cast<std::uint16_t>(
      (*control & static_cast<std::uint16_t>(
                       ~kPairedXbarConfigurationMask)) |
      kPairedXbarConfiguration);
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

inline void disablePairedXbarRequests() {
  volatile std::uint16_t *const control = xbarControlRegister();
  *control = static_cast<std::uint16_t>(
      (*control & static_cast<std::uint16_t>(
                       ~kPairedXbarConfigurationMask)) |
      kPairedXbarStatusMask);
}

// The eDMA command registers take a channel number, not a bit mask. Keeping
// these writes beside the fixed route prevents target users from accidentally
// mixing channel 2 with a neighboring DMAMUX, priority, or TCD register.
inline void clearEdmaChannelState() {
  *dmamuxChannelRegister() = 0U;
  DMA_CERQ = board::kGpioEdmaChannel;
  DMA_CERR = board::kGpioEdmaChannel;
  DMA_CEEI = board::kGpioEdmaChannel;
  DMA_CINT = board::kGpioEdmaChannel;
  DMA_CDNE = board::kGpioEdmaChannel;
}

inline void clearAuxEdmaChannelState() {
  *auxDmamuxChannelRegister() = 0U;
  DMA_CERQ = board::kAuxGpioEdmaChannel;
  DMA_CERR = board::kAuxGpioEdmaChannel;
  DMA_CEEI = board::kAuxGpioEdmaChannel;
  DMA_CINT = board::kAuxGpioEdmaChannel;
  DMA_CDNE = board::kAuxGpioEdmaChannel;
}

inline void configureEdmaPriority() {
  static_assert(board::kGpioEdmaChannel == 2U);
  DMA_DCHPRI2 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP | DMA_DCHPRI_CHPRI(board::kGpioEdmaPriority));
}

inline void configurePairedEdmaPriorities() {
  static_assert(board::kGpioEdmaChannel == 2U);
  static_assert(board::kAuxGpioEdmaChannel == 3U);
  DMA_DCHPRI2 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kPrimaryGpioInputEdmaPriority));
  DMA_DCHPRI3 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kAuxGpioEdmaPriority));
}

inline std::uint8_t auxEdmaPriority() {
  static_assert(board::kAuxGpioEdmaChannel == 3U);
  return static_cast<std::uint8_t>(DMA_DCHPRI3 & 0x0FU);
}

inline std::uint8_t edmaPriority() {
  static_assert(board::kGpioEdmaChannel == 2U);
  return static_cast<std::uint8_t>(DMA_DCHPRI2 & 0x0FU);
}

inline void enableEdmaRequest() {
  *dmamuxChannelRegister() = kDmamuxConfiguration;
  DMA_SERQ = board::kGpioEdmaChannel;
}

inline void enablePairedEdmaRequests() {
  *dmamuxChannelRegister() = kDmamuxConfiguration;
  *auxDmamuxChannelRegister() = kAuxDmamuxConfiguration;
  DMA_SERQ = board::kGpioEdmaChannel;
  DMA_SERQ = board::kAuxGpioEdmaChannel;
}

inline void disableEdmaRequest() {
  DMA_CERQ = board::kGpioEdmaChannel;
  *dmamuxChannelRegister() = 0U;
}

inline void disablePairedEdmaRequests() {
  DMA_CERQ = board::kGpioEdmaChannel;
  DMA_CERQ = board::kAuxGpioEdmaChannel;
  *dmamuxChannelRegister() = 0U;
  *auxDmamuxChannelRegister() = 0U;
}

}  // namespace thingdaq::gpio_dma_route

#endif
