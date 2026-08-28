#pragma once

#include <cstdint>

struct IMXRT_PIT_CHANNEL_t {
  volatile std::uint32_t LDVAL = 0U;
  volatile std::uint32_t CVAL = 0U;
  volatile std::uint32_t TCTRL = 0U;
  volatile std::uint32_t TFLG = 0U;
};

struct IMXRT_DMA_TCD_t {
  volatile std::uint32_t marker = 0U;
};

namespace fake_imxrt {

inline volatile std::uint32_t ccm_cscmr1 = 0U;
inline volatile std::uint32_t ccm_ccgr1 = 0U;
inline volatile std::uint32_t ccm_ccgr2 = 0U;
inline volatile std::uint32_t ccm_ccgr5 = 0U;
inline volatile std::uint32_t pit_mcr = 0U;
inline IMXRT_PIT_CHANNEL_t pit_channels[4]{};
inline volatile std::uint16_t xbara1_sel[66]{};
inline volatile std::uint16_t xbara1_ctrl[66]{};
inline volatile std::uint32_t dmamux_chcfg[32]{};
inline IMXRT_DMA_TCD_t dma_tcd[32]{};
inline volatile std::uint8_t dma_dchpri[32]{};
inline volatile std::uint32_t dma_erq = 0U;
inline volatile std::uint8_t dma_cerq = 0U;
inline volatile std::uint8_t dma_cerr = 0U;
inline volatile std::uint8_t dma_ceei = 0U;
inline volatile std::uint8_t dma_cint = 0U;
inline volatile std::uint8_t dma_cdne = 0U;
inline volatile std::uint8_t dma_serq = 0U;

}  // namespace fake_imxrt

#define CCM_CSCMR1 fake_imxrt::ccm_cscmr1
#define CCM_CCGR1 fake_imxrt::ccm_ccgr1
#define CCM_CCGR2 fake_imxrt::ccm_ccgr2
#define CCM_CCGR5 fake_imxrt::ccm_ccgr5
#define PIT_MCR fake_imxrt::pit_mcr
#define IMXRT_PIT_CHANNELS fake_imxrt::pit_channels
#define XBARA1_SEL0 fake_imxrt::xbara1_sel[0]
#define XBARA1_CTRL0 fake_imxrt::xbara1_ctrl[0]
#define DMAMUX_CHCFG0 fake_imxrt::dmamux_chcfg[0]
#define IMXRT_DMA_TCD fake_imxrt::dma_tcd
#define DMA_DCHPRI2 fake_imxrt::dma_dchpri[2]
#define DMA_ERQ fake_imxrt::dma_erq
#define DMA_CERQ fake_imxrt::dma_cerq
#define DMA_CERR fake_imxrt::dma_cerr
#define DMA_CEEI fake_imxrt::dma_ceei
#define DMA_CINT fake_imxrt::dma_cint
#define DMA_CDNE fake_imxrt::dma_cdne
#define DMA_SERQ fake_imxrt::dma_serq

#define CCM_CSCMR1_PERCLK_CLK_SEL (std::uint32_t{1U} << 6U)
#define CCM_CSCMR1_PERCLK_PODF(value) \
  (static_cast<std::uint32_t>(value) & 0x3FU)
#define CCM_CCGR_ON 3U
#define CCM_CCGR1_PIT(value) \
  (static_cast<std::uint32_t>(value) << 0U)
#define CCM_CCGR2_XBAR1(value) \
  (static_cast<std::uint32_t>(value) << 4U)
#define CCM_CCGR5_DMA(value) \
  (static_cast<std::uint32_t>(value) << 8U)

#define PIT_MCR_MDIS (std::uint32_t{1U} << 1U)
#define PIT_TFLG_TIF (std::uint32_t{1U} << 0U)

#define XBARA_CTRL_STS0 (std::uint16_t{1U} << 0U)
#define XBARA_CTRL_EDGE0(value) \
  (static_cast<std::uint16_t>(value) << 1U)
#define XBARA_CTRL_IEN0 (std::uint16_t{1U} << 3U)
#define XBARA_CTRL_DEN0 (std::uint16_t{1U} << 4U)
#define XBARA_CTRL_STS1 (std::uint16_t{1U} << 8U)
#define XBARA_CTRL_EDGE1(value) \
  (static_cast<std::uint16_t>(value) << 9U)
#define XBARA_CTRL_IEN1 (std::uint16_t{1U} << 11U)
#define XBARA_CTRL_DEN1 (std::uint16_t{1U} << 12U)

#define DMAMUX_CHCFG_ENBL (std::uint32_t{1U} << 7U)
#define DMA_DCHPRI_ECP (std::uint8_t{1U} << 7U)
#define DMA_DCHPRI_CHPRI(value) \
  (static_cast<std::uint8_t>(value) & std::uint8_t{0x0FU})

#define XBARA1_IN_PIT_TRIGGER0 56U
#define XBARA1_IN_PIT_TRIGGER1 57U
#define XBARA1_IN_PIT_TRIGGER2 58U
#define XBARA1_IN_PIT_TRIGGER3 59U
#define XBARA1_OUT_DMA_CH_MUX_REQ30 0U
#define XBARA1_OUT_DMA_CH_MUX_REQ31 1U
#define XBARA1_OUT_DMA_CH_MUX_REQ94 2U
#define XBARA1_OUT_DMA_CH_MUX_REQ95 3U
#define XBARA1_OUT_ADC_ETC_TRIG00 103U
#define XBARA1_OUT_ADC_ETC_TRIG10 107U

#define DMAMUX_SOURCE_ADC1 24U
#define DMAMUX_SOURCE_ADC2 88U
#define DMAMUX_SOURCE_XBAR1_0 30U
#define DMAMUX_SOURCE_XBAR1_1 31U
#define DMAMUX_SOURCE_XBAR1_2 94U
#define DMAMUX_SOURCE_XBAR1_3 95U
