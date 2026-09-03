#include "gpio_clock_diagnostic_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <array>
#include <cstddef>
#include <cstdint>

#include <core_pins.h>
#include <imxrt.h>

#include "firmware_identity.h"

#include "board_config.h"
#include "gpio_dma_route_teensy.h"

#define THINGDAQ_GPIO_CLOCK_TARGET_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::gpio_clock {

struct alignas(board::kCacheLineBytes) DiagnosticBuffer {
  std::array<std::uint32_t,
             board::kGpioClockDiagnosticSinkBytes / sizeof(std::uint32_t)>
      words{};
};

DiagnosticBuffer g_gpio_clock_diagnostic_buffer
    __attribute__((section(".dmabuffers"), used));

namespace {

constexpr std::uint32_t kSourceWord = 0xA5C35A7EU;
constexpr std::uint32_t kDestinationPoison = 0x5A3CA581U;
constexpr std::uint16_t kTcdAttributes =
    DMA_TCD_ATTR_SSIZE(2U) | DMA_TCD_ATTR_DSIZE(2U);
constexpr std::uint16_t kTcdCsr = DMA_TCD_CSR_DREQ;

std::uint32_t address32(const volatile void *address) {
  return static_cast<std::uint32_t>(
      reinterpret_cast<std::uintptr_t>(address));
}

void addError(protocol::GpioClockDiagnosticResponse &snapshot,
              protocol_v1::GpioClockError error) {
  snapshot.hardware_error_flags |= errorBit(error);
}

class TeensyPlatform final : public Platform {
 public:
  THINGDAQ_GPIO_CLOCK_TARGET_CODE(".flashmem.gpio_clock.target")
  bool execute(const Plan &plan,
               protocol::GpioClockDiagnosticResponse &snapshot) override {
    IMXRT_PIT_CHANNEL_t &pit = IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
    snapshot.pit_channel = board::kGpioPitChannel;
    snapshot.xbar_input = board::kGpioXbarInput;
    snapshot.xbar_output = board::kGpioXbarOutput;
    snapshot.edma_channel = board::kGpioEdmaChannel;
    snapshot.dmamux_source = board::kGpioDmamuxSource;

    // Clock gates are shared enable-only resources. Turn them on before the
    // first peripheral read; the later snapshot verifies each relevant gate.
    gpio_dma_route::enableClockGates();

    volatile std::uint32_t *const dmamux =
        gpio_dma_route::dmamuxChannelRegister();
    IMXRT_DMA_TCD_t &tcd = gpio_dma_route::edmaTcd();
    if (pit.TCTRL != 0U || gpio_dma_route::edmaRequestBusy() ||
        gpio_dma_route::selectedOutputBusy()) {
      addError(snapshot, protocol_v1::GpioClockError::kResourceBusy);
      captureUnarmed(snapshot, *dmamux, tcd);
      return true;
    }

    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    gpio_dma_route::barrier();
    const std::uint32_t counter_begin = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    if (ARM_DWT_CYCCNT == counter_begin ||
        F_CPU_ACTUAL != identity::kExpectedDwtHz) {
      addError(snapshot, protocol_v1::GpioClockError::kDwtUnavailable);
      captureUnarmed(snapshot, *dmamux, tcd);
      return true;
    }
    snapshot.dwt_counter_hz = F_CPU_ACTUAL;

    gpio_dma_route::configureStoppedPit(plan.pit_load_value);
    gpio_dma_route::configureXbarRequest();
    volatile std::uint16_t *const xbar_select =
        gpio_dma_route::xbarSelectRegister();
    volatile std::uint16_t *const xbar_control_register =
        gpio_dma_route::xbarControlRegister();

    gpio_dma_route::clearEdmaChannelState();

    g_gpio_clock_diagnostic_buffer.words[0] = kSourceWord;
    g_gpio_clock_diagnostic_buffer.words[1] = kDestinationPoison;
    arm_dcache_flush_delete(&g_gpio_clock_diagnostic_buffer,
                            sizeof(g_gpio_clock_diagnostic_buffer));
    tcd.SADDR = &g_gpio_clock_diagnostic_buffer.words[0];
    tcd.SOFF = 0;
    tcd.ATTR = kTcdAttributes;
    tcd.NBYTES_MLNO = sizeof(std::uint32_t);
    tcd.SLAST = 0;
    tcd.DADDR = &g_gpio_clock_diagnostic_buffer.words[1];
    tcd.DOFF = 0;
    tcd.CITER_ELINKNO = plan.tcd_major_count;
    tcd.DLASTSGA = 0;
    tcd.BITER_ELINKNO = plan.tcd_major_count;
    tcd.CSR = kTcdCsr;
    gpio_dma_route::configureOwnedEdmaPriorities();
    gpio_dma_route::enableEdmaRequest();

    snapshot.ccm_cscmr1_configured = CCM_CSCMR1;
    snapshot.ccm_ccgr1_configured = CCM_CCGR1;
    snapshot.ccm_ccgr2_configured = CCM_CCGR2;
    snapshot.ccm_ccgr5_configured = CCM_CCGR5;
    snapshot.pit_mcr_configured = PIT_MCR;
    snapshot.pit_ldval_configured = pit.LDVAL;
    snapshot.xbar_sel_configured = *xbar_select;
    snapshot.xbar_ctrl_configured = *xbar_control_register;
    snapshot.dmamux_chcfg_configured = *dmamux;
    snapshot.dma_cr_configured = DMA_CR;
    snapshot.dma_erq_configured = DMA_ERQ;
    snapshot.tcd_saddr = address32(tcd.SADDR);
    snapshot.tcd_daddr = address32(tcd.DADDR);
    snapshot.tcd_nbytes = tcd.NBYTES_MLNO;
    snapshot.tcd_biter = tcd.BITER_ELINKNO;
    snapshot.tcd_attr = tcd.ATTR;
    snapshot.tcd_soff = static_cast<std::uint16_t>(tcd.SOFF);
    snapshot.edma_priority = gpio_dma_route::edmaPriority();
    validateArmed(plan, snapshot);

    gpio_dma_route::barrier();
    const std::uint32_t measurement_begin = ARM_DWT_CYCCNT;
    pit.TCTRL = PIT_TCTRL_TEN;
    snapshot.pit_tctrl_configured = pit.TCTRL;
    while (ARM_DWT_CYCCNT - measurement_begin < plan.measurement_cycles) {
      if ((tcd.CSR & DMA_TCD_CSR_DONE) != 0U) {
        addError(snapshot, protocol_v1::GpioClockError::kDuplicateTrigger);
        addError(snapshot, protocol_v1::GpioClockError::kMeasurementOverflow);
        break;
      }
    }
    pit.TCTRL = 0U;
    gpio_dma_route::barrier();
    const std::uint32_t measurement_end = ARM_DWT_CYCCNT;
    gpio_dma_route::disableEdmaRequest();
    gpio_dma_route::disableXbarRequest();
    gpio_dma_route::barrier();

    snapshot.dwt_elapsed_cycles = measurement_end - measurement_begin;
    snapshot.pit_cval_final = pit.CVAL;
    snapshot.pit_tflg_final = pit.TFLG;
    snapshot.dma_es_final = DMA_ES;
    snapshot.dma_err_final = DMA_ERR;
    snapshot.dma_hrs_final = DMA_HRS;
    snapshot.tcd_citer_final = tcd.CITER_ELINKNO;
    snapshot.tcd_csr_final = tcd.CSR;
    snapshot.dma_sample_count =
        snapshot.tcd_citer_final <= snapshot.tcd_biter
            ? static_cast<std::uint32_t>(snapshot.tcd_biter -
                                         snapshot.tcd_citer_final)
            : 0U;
    arm_dcache_delete(&g_gpio_clock_diagnostic_buffer,
                      sizeof(g_gpio_clock_diagnostic_buffer));
    snapshot.last_sample_word = g_gpio_clock_diagnostic_buffer.words[1];

    if ((snapshot.dma_err_final & gpio_dma_route::kEdmaChannelMask) != 0U ||
        snapshot.dma_es_final != 0U) {
      addError(snapshot, protocol_v1::GpioClockError::kEdmaChannelError);
    }
    if (snapshot.dma_sample_count != 0U &&
        snapshot.last_sample_word != kSourceWord) {
      addError(snapshot, protocol_v1::GpioClockError::kEdmaConfigMismatch);
    }

    pit.TFLG = PIT_TFLG_TIF;
    DMA_CERR = board::kGpioEdmaChannel;
    DMA_CINT = board::kGpioEdmaChannel;
    DMA_CDNE = board::kGpioEdmaChannel;
    return true;
  }

 private:
  static void captureUnarmed(protocol::GpioClockDiagnosticResponse &snapshot,
                             std::uint32_t dmamux,
                             const IMXRT_DMA_TCD_t &tcd) {
    const IMXRT_PIT_CHANNEL_t &pit =
        IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
    snapshot.ccm_cscmr1_configured = CCM_CSCMR1;
    snapshot.ccm_ccgr1_configured = CCM_CCGR1;
    snapshot.ccm_ccgr2_configured = CCM_CCGR2;
    snapshot.ccm_ccgr5_configured = CCM_CCGR5;
    snapshot.pit_mcr_configured = PIT_MCR;
    snapshot.pit_ldval_configured = pit.LDVAL;
    snapshot.pit_cval_final = pit.CVAL;
    snapshot.pit_tctrl_configured = pit.TCTRL;
    snapshot.pit_tflg_final = pit.TFLG;
    snapshot.xbar_sel_configured = *gpio_dma_route::xbarSelectRegister();
    snapshot.xbar_ctrl_configured = *gpio_dma_route::xbarControlRegister();
    snapshot.dmamux_chcfg_configured = dmamux;
    snapshot.dma_cr_configured = DMA_CR;
    snapshot.dma_es_final = DMA_ES;
    snapshot.dma_erq_configured = DMA_ERQ;
    snapshot.dma_err_final = DMA_ERR;
    snapshot.dma_hrs_final = DMA_HRS;
    snapshot.tcd_saddr = address32(tcd.SADDR);
    snapshot.tcd_daddr = address32(tcd.DADDR);
    snapshot.tcd_nbytes = tcd.NBYTES_MLNO;
    snapshot.tcd_citer_final = tcd.CITER_ELINKNO;
    snapshot.tcd_biter = tcd.BITER_ELINKNO;
    snapshot.tcd_csr_final = tcd.CSR;
    snapshot.tcd_attr = tcd.ATTR;
    snapshot.tcd_soff = static_cast<std::uint16_t>(tcd.SOFF);
    snapshot.edma_priority = gpio_dma_route::edmaPriority();
  }

  static void validateArmed(
      const Plan &plan, protocol::GpioClockDiagnosticResponse &snapshot) {
    if ((snapshot.ccm_cscmr1_configured & gpio_dma_route::kPerclkMask) !=
        gpio_dma_route::kPerclk24M) {
      addError(snapshot, protocol_v1::GpioClockError::kPerclkMismatch);
    }
    if ((snapshot.ccm_ccgr1_configured & gpio_dma_route::kPitGateMask) !=
        gpio_dma_route::kPitGateMask) {
      addError(snapshot, protocol_v1::GpioClockError::kPitGateDisabled);
    }
    if ((snapshot.ccm_ccgr2_configured & gpio_dma_route::kXbarGateMask) !=
        gpio_dma_route::kXbarGateMask) {
      addError(snapshot, protocol_v1::GpioClockError::kXbarGateDisabled);
    }
    if ((snapshot.ccm_ccgr5_configured & gpio_dma_route::kDmaGateMask) !=
        gpio_dma_route::kDmaGateMask) {
      addError(snapshot, protocol_v1::GpioClockError::kDmaGateDisabled);
    }
    if ((snapshot.pit_mcr_configured & PIT_MCR_MDIS) != 0U ||
        snapshot.pit_ldval_configured != plan.pit_load_value) {
      addError(snapshot, protocol_v1::GpioClockError::kPitConfigMismatch);
    }
    if ((snapshot.xbar_sel_configured &
         gpio_dma_route::kXbarSelectionMask) !=
            (static_cast<std::uint16_t>(board::kGpioXbarInput)
             << gpio_dma_route::kXbarSelectionShift) ||
        (snapshot.xbar_ctrl_configured &
         (gpio_dma_route::kXbarSelectedEdge |
          gpio_dma_route::kXbarSelectedDmaEnable)) !=
            (gpio_dma_route::kXbarSelectedEdge |
             gpio_dma_route::kXbarSelectedDmaEnable)) {
      addError(snapshot, protocol_v1::GpioClockError::kXbarConfigMismatch);
    }
    if (snapshot.dmamux_chcfg_configured !=
        gpio_dma_route::kDmamuxConfiguration) {
      addError(snapshot, protocol_v1::GpioClockError::kDmamuxConfigMismatch);
    }
    if (snapshot.tcd_nbytes != sizeof(std::uint32_t) ||
        snapshot.tcd_biter != plan.tcd_major_count ||
        snapshot.tcd_attr != kTcdAttributes || snapshot.tcd_soff != 0U ||
        snapshot.edma_priority != board::kGpioEdmaPriority ||
        (snapshot.dma_erq_configured &
         (std::uint32_t{1U} << board::kGpioEdmaChannel)) == 0U) {
      addError(snapshot, protocol_v1::GpioClockError::kEdmaConfigMismatch);
    }
  }
};

TeensyPlatform g_platform{};
Runner g_runner{g_platform};

}  // namespace

Runner &teensyRunner() { return g_runner; }

static_assert(sizeof(DiagnosticBuffer) == board::kGpioClockDiagnosticSinkBytes);
static_assert(alignof(DiagnosticBuffer) == board::kCacheLineBytes);
static_assert(F_CPU == identity::kExpectedCpuHz,
              "GPIO clock diagnostic requires the selected CPU profile");
static_assert(board::kGpioPitChannel == 0U);
static_assert(board::kGpioEdmaChannel == 2U);
static_assert(board::kGpioXbarInput == board::kXbarPitTrigger0Input);
static_assert(board::kGpioXbarActiveEdge == 1U);
static_assert(board::kGpioXbarOutput <= board::kXbarDmaRequest95Output);
static_assert((board::kGpioXbarOutput == board::kXbarDmaRequest30Output &&
               board::kGpioDmamuxSource ==
                   board::kDmamuxXbar1Request0Source) ||
              (board::kGpioXbarOutput == board::kXbarDmaRequest31Output &&
               board::kGpioDmamuxSource ==
                   board::kDmamuxXbar1Request1Source) ||
              (board::kGpioXbarOutput == board::kXbarDmaRequest94Output &&
               board::kGpioDmamuxSource ==
                   board::kDmamuxXbar1Request2Source) ||
              (board::kGpioXbarOutput == board::kXbarDmaRequest95Output &&
               board::kGpioDmamuxSource ==
                   board::kDmamuxXbar1Request3Source));

}  // namespace thingdaq::gpio_clock

#undef THINGDAQ_GPIO_CLOCK_TARGET_CODE

#endif
