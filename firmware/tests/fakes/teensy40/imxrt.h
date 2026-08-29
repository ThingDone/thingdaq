#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace fake_imxrt {

struct RegisterWrite {
  const void *address = nullptr;
  std::uint32_t value = 0U;
};

inline std::array<RegisterWrite, 512U> register_writes{};
inline std::size_t register_write_count = 0U;

inline void recordRegisterWrite(const void *address, std::uint32_t value) {
  if (register_write_count < register_writes.size()) {
    register_writes[register_write_count] = {address, value};
  }
  ++register_write_count;
}

inline void clearRegisterWrites() {
  register_writes = {};
  register_write_count = 0U;
}

class Register32 {
 public:
  Register32() = default;

  Register32 &operator=(std::uint32_t value) {
    value_ = value;
    recordRegisterWrite(this, value_);
    return *this;
  }

  Register32 &operator|=(std::uint32_t value) {
    return *this = value_ | value;
  }

  Register32 &operator&=(std::uint32_t value) {
    return *this = value_ & value;
  }

  operator std::uint32_t() const { return value_; }

  void reset(std::uint32_t value = 0U) { value_ = value; }

 private:
  std::uint32_t value_ = 0U;
};

}  // namespace fake_imxrt

struct IMXRT_PIT_CHANNEL_t {
  fake_imxrt::Register32 LDVAL{};
  fake_imxrt::Register32 CVAL{};
  fake_imxrt::Register32 TCTRL{};
  fake_imxrt::Register32 TFLG{};
};

struct IMXRT_DMA_TCD_t {
  volatile std::uint32_t marker = 0U;
};

struct IMXRT_ADCS_t {
  fake_imxrt::Register32 HC0{};
  fake_imxrt::Register32 HC1{};
  fake_imxrt::Register32 HC2{};
  fake_imxrt::Register32 HC3{};
  fake_imxrt::Register32 HC4{};
  fake_imxrt::Register32 HC5{};
  fake_imxrt::Register32 HC6{};
  fake_imxrt::Register32 HC7{};
  fake_imxrt::Register32 HS{};
  fake_imxrt::Register32 R0{};
  fake_imxrt::Register32 R1{};
  fake_imxrt::Register32 R2{};
  fake_imxrt::Register32 R3{};
  fake_imxrt::Register32 R4{};
  fake_imxrt::Register32 R5{};
  fake_imxrt::Register32 R6{};
  fake_imxrt::Register32 R7{};
  fake_imxrt::Register32 CFG{};
  fake_imxrt::Register32 GC{};
  fake_imxrt::Register32 GS{};
};

struct IMXRT_ADC_ETC_TRIGGER_t {
  fake_imxrt::Register32 CTRL{};
  fake_imxrt::Register32 COUNTER{};
  fake_imxrt::Register32 CHAIN_1_0{};
  fake_imxrt::Register32 CHAIN_3_2{};
  fake_imxrt::Register32 CHAIN_5_4{};
  fake_imxrt::Register32 CHAIN_7_6{};
  fake_imxrt::Register32 RESULT_1_0{};
  fake_imxrt::Register32 RESULT_3_2{};
  fake_imxrt::Register32 RESULT_5_4{};
  fake_imxrt::Register32 RESULT_7_6{};
};

struct IMXRT_ADC_ETC_t {
  fake_imxrt::Register32 CTRL{};
  fake_imxrt::Register32 DONE0_1_IRQ{};
  fake_imxrt::Register32 DONE2_ERR_IRQ{};
  fake_imxrt::Register32 DMA_CTRL{};
  std::array<IMXRT_ADC_ETC_TRIGGER_t, 8U> TRIG{};
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
inline IMXRT_ADCS_t adc1{};
inline IMXRT_ADCS_t adc2{};
inline IMXRT_ADC_ETC_t adc_etc{};
inline volatile std::uint32_t arm_demcr = 0U;
inline volatile std::uint32_t arm_dwt_ctrl = 0U;
inline volatile std::uint32_t arm_dwt_cyccnt = 0U;
inline std::array<void (*)(void), 160U> interrupt_vectors{};
inline std::array<std::uint8_t, 160U> interrupt_priorities{};
inline std::array<bool, 160U> interrupt_enabled{};
inline std::array<bool, 160U> interrupt_pending{};
inline void (*adc_trigger_diagnostic_poll_hook)() = nullptr;

inline void runAdcTriggerDiagnosticPollHook() {
  if (adc_trigger_diagnostic_poll_hook != nullptr) {
    adc_trigger_diagnostic_poll_hook();
  }
}

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
#define IMXRT_ADC1 fake_imxrt::adc1
#define IMXRT_ADC2 fake_imxrt::adc2
#define IMXRT_ADC_ETC fake_imxrt::adc_etc
#define ADC_ETC_CTRL (IMXRT_ADC_ETC.CTRL)
#define ADC_ETC_DONE0_1_IRQ (IMXRT_ADC_ETC.DONE0_1_IRQ)
#define ADC_ETC_DONE2_ERR_IRQ (IMXRT_ADC_ETC.DONE2_ERR_IRQ)
#define ADC_ETC_DMA_CTRL (IMXRT_ADC_ETC.DMA_CTRL)
#define ARM_DEMCR fake_imxrt::arm_demcr
#define ARM_DWT_CTRL fake_imxrt::arm_dwt_ctrl
#define ARM_DWT_CYCCNT fake_imxrt::arm_dwt_cyccnt
#define TEENSY_DAQ_ADC_TRIGGER_DIAGNOSTIC_POLL_HOOK() \
  fake_imxrt::runAdcTriggerDiagnosticPollHook()

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
#define CCM_CCGR1_ADC1(value) \
  (static_cast<std::uint32_t>(value) << 12U)
#define CCM_CCGR1_ADC2(value) \
  (static_cast<std::uint32_t>(value) << 14U)

#define PIT_MCR_MDIS (std::uint32_t{1U} << 1U)
#define PIT_TFLG_TIF (std::uint32_t{1U} << 0U)
#define PIT_TCTRL_TEN (std::uint32_t{1U} << 0U)
#define PIT_TCTRL_TIE (std::uint32_t{1U} << 1U)
#define PIT_TCTRL_CHN (std::uint32_t{1U} << 2U)

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

#define IOMUXC_PAD_DSE(value) \
  ((static_cast<std::uint32_t>(value) & 0x07U) << 3U)
#define IOMUXC_PAD_HYS (std::uint32_t{1U} << 16U)

#define ADC_HC_ADCH(value) \
  (static_cast<std::uint32_t>(value) & 0x1FU)
#define ADC_CFG_OVWREN (std::uint32_t{1U} << 16U)
#define ADC_CFG_ADTRG (std::uint32_t{1U} << 13U)
#define ADC_CFG_ADHSC (std::uint32_t{1U} << 10U)
#define ADC_CFG_ADIV(value) \
  ((static_cast<std::uint32_t>(value) & 0x03U) << 5U)
#define ADC_CFG_MODE(value) \
  ((static_cast<std::uint32_t>(value) & 0x03U) << 2U)
#define ADC_CFG_ADICLK(value) \
  (static_cast<std::uint32_t>(value) & 0x03U)
#define ADC_GC_CAL (std::uint32_t{1U} << 7U)
#define ADC_GC_DMAEN (std::uint32_t{1U} << 1U)
#define ADC_GS_CALF (std::uint32_t{1U} << 1U)
#define ADC_GS_ADACT (std::uint32_t{1U} << 0U)

#define ADC_ETC_CTRL_PRE_DIVIDER(value) \
  ((static_cast<std::uint32_t>(value) & 0xFFU) << 16U)
#define ADC_ETC_CTRL_SOFTRST (std::uint32_t{1U} << 31U)
#define ADC_ETC_CTRL_TSC_BYPASS (std::uint32_t{1U} << 30U)
#define ADC_ETC_CTRL_TRIG_ENABLE(value) \
  (static_cast<std::uint32_t>(value) & 0xFFU)
#define ADC_ETC_DONE0_1_IRQ_TRIG_DONE1(value) \
  (std::uint32_t{1U} << (16U + (static_cast<std::uint32_t>(value) & 0x07U)))
#define ADC_ETC_DONE0_1_IRQ_TRIG_DONE0(value) \
  (std::uint32_t{1U} << (static_cast<std::uint32_t>(value) & 0x07U))
#define ADC_ETC_DONE2_ERR_IRQ_TRIG_ERR(value) \
  (std::uint32_t{1U} << (16U + (static_cast<std::uint32_t>(value) & 0x07U)))
#define ADC_ETC_TRIG_CTRL_TRIG_CHAIN(value) \
  ((static_cast<std::uint32_t>(value) & 0x07U) << 8U)
#define ADC_ETC_TRIG_COUNTER_INIT_DELAY(value) \
  (static_cast<std::uint32_t>(value) & 0xFFU)
#define ADC_ETC_TRIG_CHAIN_IE0(value) \
  ((static_cast<std::uint32_t>(value) & 0x03U) << 13U)
#define ADC_ETC_TRIG_CHAIN_HWTS0(value) \
  ((static_cast<std::uint32_t>(value) & 0xFFU) << 4U)
#define ADC_ETC_TRIG_CHAIN_CSEL0(value) \
  (static_cast<std::uint32_t>(value) & 0x0FU)

#define ARM_DEMCR_TRCENA (std::uint32_t{1U} << 24U)
#define ARM_DWT_CTRL_CYCCNTENA (std::uint32_t{1U} << 0U)

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

using IRQ_NUMBER_t = std::uint8_t;
inline constexpr IRQ_NUMBER_t IRQ_ADC_ETC0 = 118U;
inline constexpr IRQ_NUMBER_t IRQ_ADC_ETC1 = 119U;
inline constexpr IRQ_NUMBER_t IRQ_ADC_ETC_ERR = 121U;

inline void attachInterruptVector(IRQ_NUMBER_t irq, void (*function)(void)) {
  fake_imxrt::interrupt_vectors[irq] = function;
}

inline void fakeNvicSetPriority(IRQ_NUMBER_t irq, std::uint8_t priority) {
  fake_imxrt::interrupt_priorities[irq] = priority;
}

inline void fakeNvicClearPending(IRQ_NUMBER_t irq) {
  fake_imxrt::interrupt_pending[irq] = false;
}

inline void fakeNvicEnable(IRQ_NUMBER_t irq) {
  fake_imxrt::interrupt_enabled[irq] = true;
}

inline void fakeNvicDisable(IRQ_NUMBER_t irq) {
  fake_imxrt::interrupt_enabled[irq] = false;
}

#define NVIC_SET_PRIORITY(irq, priority) \
  fakeNvicSetPriority((irq), static_cast<std::uint8_t>(priority))
#define NVIC_CLEAR_PENDING(irq) fakeNvicClearPending((irq))
#define NVIC_ENABLE_IRQ(irq) fakeNvicEnable((irq))
#define NVIC_DISABLE_IRQ(irq) fakeNvicDisable((irq))
