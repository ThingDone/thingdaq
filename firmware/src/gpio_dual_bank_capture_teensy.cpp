#include "gpio_dual_bank_capture_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <new>

#include <core_pins.h>
#include <imxrt.h>

#include "board_config.h"
#include "checksum_benchmark_teensy.h"
#include "gpio_dma_route_teensy.h"
#include "gpio_raw_capture.h"
#include "gpio_raw_storage_teensy.h"
#include "variable_rate_scheduler.h"

#define THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::gpio_join {
namespace {

struct alignas(board::kCacheLineBytes) AuxDescriptorBank {
  std::array<IMXRT_DMA_TCD_t, board::kAuxGpioRawDmaDescriptorCount>
      descriptors{};
};

inline constexpr std::uint16_t kTcdAttributes =
    DMA_TCD_ATTR_SSIZE(2U) | DMA_TCD_ATTR_DSIZE(2U);
inline constexpr std::uint16_t kTcdControl =
    DMA_TCD_CSR_ESG | DMA_TCD_CSR_INTMAJOR;
inline constexpr std::uint32_t kInputMuxConfiguration = 5U | 0x10U;
inline constexpr std::uint32_t kInputPadConfiguration =
    IOMUXC_PAD_DSE(7U);
inline constexpr std::uint32_t kAdcTriggerEnableMask =
    (std::uint32_t{1U} <<
     board::kAdcConverterConfigurations[0].adc_etc_trigger) |
    (std::uint32_t{1U} <<
     board::kAdcConverterConfigurations[1].adc_etc_trigger);

class TeensyCacheMaintenance final : public dma::CacheMaintenance {
 public:
  THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
      ".flashmem.gpio_dual.cache_discard")
  void discardBeforeDmaWrite(void *address, std::size_t bytes) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(bytes));
  }

  THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
      ".flashmem.gpio_dual.cache_invalidate")
  void invalidateBeforeCpuRead(void *address, std::size_t bytes) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(bytes));
  }
};

std::uint32_t readPrimask() {
#if defined(THINGDAQ_HOST_REGISTER_TEST)
  return fake_imxrt::interrupts_enabled ? 0U : 1U;
#else
  std::uint32_t value = 0U;
  __asm__ volatile("mrs %0, primask" : "=r"(value) : : "memory");
  return value;
#endif
}

void restorePrimask(std::uint32_t value) {
  if ((value & 1U) == 0U) {
    __enable_irq();
  }
}

class TeensyCriticalSection final : public dma::CriticalSection {
 public:
  THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
      ".flashmem.gpio_dual.critical_enter")
  std::uint32_t enter() override {
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    return primask;
  }

  THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
      ".flashmem.gpio_dual.critical_exit")
  void exit(std::uint32_t token) override { restorePrimask(token); }
};

TeensyCacheMaintenance g_cache{};
TeensyCriticalSection g_critical{};
TeensyDualBankCapture g_facade{};
DualBankCaptureRing *g_ring = nullptr;
AuxDescriptorBank *g_aux_descriptors = nullptr;
PairedOverflowSink *g_overflow_sink = nullptr;
Snapshot g_cached_snapshot{};
std::array<std::uint32_t, kBankCount> g_current_generations{};
std::array<std::uint32_t, kBankCount> g_queued_generations{};
std::array<std::uint8_t, kBankCount> g_current_destinations{
    kInvalidDestination, kInvalidDestination};
std::array<std::uint8_t, kBankCount> g_queued_destinations{
    kInvalidDestination, kInvalidDestination};
std::array<std::uint64_t, kBankCount> g_current_first_ticks{};
std::array<std::uint64_t, kBankCount> g_queued_first_ticks{};
std::array<std::uint32_t, kBankCount> g_last_incomplete_samples{};
std::uint32_t g_epoch = 0U;
std::uint32_t g_sample_period_ticks = 0U;
std::uint32_t g_resource_conflicts = 0U;
std::uint32_t g_start_errors = 0U;
std::uint32_t g_stop_errors = 0U;
std::uint32_t g_stale_dma_completions = 0U;
std::uint32_t g_gpio1_gdir_unrelated = 0U;
std::uint32_t g_gpr26_unrelated = 0U;
std::uint32_t g_gpio2_gdir_unrelated = 0U;
std::uint32_t g_gpr27_unrelated = 0U;
protocol_v2::RateProfile g_profile = protocol_v2::kDefaultRateProfile;
bool g_workspace_claimed = false;
bool g_hardware_prepared = false;
bool g_hardware_running = false;
bool g_faulted = false;
bool g_pins_verified = false;
bool g_route_verified = false;

template <typename Integer>
void saturatingIncrement(Integer &value) {
  if (value != std::numeric_limits<Integer>::max()) {
    ++value;
  }
}

std::uint32_t address32(const volatile void *address) {
  return static_cast<std::uint32_t>(
      reinterpret_cast<std::uintptr_t>(address));
}

volatile std::uint32_t *muxRegister(std::size_t index) {
  switch (index) {
    case 0U: return &CORE_PIN6_CONFIG;
    case 1U: return &CORE_PIN7_CONFIG;
    case 2U: return &CORE_PIN8_CONFIG;
    case 3U: return &CORE_PIN9_CONFIG;
    case 4U: return &CORE_PIN10_CONFIG;
    case 5U: return &CORE_PIN11_CONFIG;
    case 6U: return &CORE_PIN12_CONFIG;
    case 7U: return &CORE_PIN13_CONFIG;
    case 8U: return &CORE_PIN16_CONFIG;
    case 9U: return &CORE_PIN17_CONFIG;
    case 10U: return &CORE_PIN18_CONFIG;
    case 11U: return &CORE_PIN19_CONFIG;
    case 12U: return &CORE_PIN20_CONFIG;
    case 13U: return &CORE_PIN21_CONFIG;
    case 14U: return &CORE_PIN22_CONFIG;
    case 15U: return &CORE_PIN23_CONFIG;
    default: return nullptr;
  }
}

volatile std::uint32_t *padRegister(std::size_t index) {
  switch (index) {
    case 0U: return &CORE_PIN6_PADCONFIG;
    case 1U: return &CORE_PIN7_PADCONFIG;
    case 2U: return &CORE_PIN8_PADCONFIG;
    case 3U: return &CORE_PIN9_PADCONFIG;
    case 4U: return &CORE_PIN10_PADCONFIG;
    case 5U: return &CORE_PIN11_PADCONFIG;
    case 6U: return &CORE_PIN12_PADCONFIG;
    case 7U: return &CORE_PIN13_PADCONFIG;
    case 8U: return &CORE_PIN16_PADCONFIG;
    case 9U: return &CORE_PIN17_PADCONFIG;
    case 10U: return &CORE_PIN18_PADCONFIG;
    case 11U: return &CORE_PIN19_PADCONFIG;
    case 12U: return &CORE_PIN20_PADCONFIG;
    case 13U: return &CORE_PIN21_PADCONFIG;
    case 14U: return &CORE_PIN22_PADCONFIG;
    case 15U: return &CORE_PIN23_PADCONFIG;
    default: return nullptr;
  }
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.safe_inputs")
void forceSafeInputs() {
  // Clear both fast aliases before changing mux/select state, then clear the
  // DMA-visible directions before selecting GPIO2/GPIO1. These pads are on
  // the Teensy 4.0 3.3 V digital domain; DSE(7), ALT5, and SION match the
  // pinned core's INPUT configuration without enabling pulls.
  GPIO7_GDIR &= ~board::kGpio2PsrCaptureMask;
  GPIO6_GDIR &= ~board::kGpio1PsrCaptureMask;
  GPIO2_GDIR &= ~board::kGpio2PsrCaptureMask;
  GPIO1_GDIR &= ~board::kGpio1PsrCaptureMask;
  for (std::size_t index = 0U; index < 16U; ++index) {
    *padRegister(index) = kInputPadConfiguration;
    *muxRegister(index) = kInputMuxConfiguration;
  }
  gpio_capture::selectStandardGpioInputs(IOMUXC_GPR_GPR27,
                                         GPIO2_GDIR);
  selectAuxiliaryStandardInputs(IOMUXC_GPR_GPR26, GPIO1_GDIR);
  gpio_dma_route::barrier();
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.pins_valid")
bool pinsValid() {
  if ((GPIO7_GDIR & board::kGpio2PsrCaptureMask) != 0U ||
      (GPIO6_GDIR & board::kGpio1PsrCaptureMask) != 0U ||
      (GPIO2_GDIR & board::kGpio2PsrCaptureMask) != 0U ||
      (GPIO1_GDIR & board::kGpio1PsrCaptureMask) != 0U ||
      (IOMUXC_GPR_GPR27 &
       board::kGpio7ToGpio2Gpr27ClearMask) != 0U ||
      (IOMUXC_GPR_GPR26 &
       board::kGpio6ToGpio1Gpr26ClearMask) != 0U ||
      (GPIO1_GDIR & ~board::kGpio1PsrCaptureMask) !=
          g_gpio1_gdir_unrelated ||
      (IOMUXC_GPR_GPR26 &
       ~board::kGpio6ToGpio1Gpr26ClearMask) != g_gpr26_unrelated ||
      (GPIO2_GDIR & ~board::kGpio2PsrCaptureMask) !=
          g_gpio2_gdir_unrelated ||
      (IOMUXC_GPR_GPR27 &
       ~board::kGpio7ToGpio2Gpr27ClearMask) != g_gpr27_unrelated) {
    return false;
  }
  for (std::size_t index = 0U; index < 16U; ++index) {
    if (*muxRegister(index) != kInputMuxConfiguration ||
        *padRegister(index) != kInputPadConfiguration) {
      return false;
    }
  }
  // Volatile reads verify both selected input aliases are readable before
  // either DMA request can observe PIT0.
  const std::uint32_t primary = GPIO2_PSR;
  const std::uint32_t auxiliary = GPIO1_PSR;
  (void)primary;
  (void)auxiliary;
  return true;
}

constexpr std::uint8_t channel(Bank bank) {
  return bank == Bank::kPrimary ? board::kGpioEdmaChannel
                                : board::kAuxGpioEdmaChannel;
}

constexpr std::uint32_t channelMask(Bank bank) {
  return std::uint32_t{1U} << channel(bank);
}

volatile std::uint32_t *dmamuxRegister(Bank bank) {
  return bank == Bank::kPrimary
             ? gpio_dma_route::dmamuxChannelRegister()
             : gpio_dma_route::auxDmamuxChannelRegister();
}

constexpr std::uint32_t dmamuxConfiguration(Bank bank) {
  return bank == Bank::kPrimary
             ? gpio_dma_route::kDmamuxConfiguration
             : gpio_dma_route::kAuxDmamuxConfiguration;
}

IMXRT_DMA_TCD_t &hardwareTcd(Bank bank) {
  return bank == Bank::kPrimary ? gpio_dma_route::edmaTcd()
                                : gpio_dma_route::auxEdmaTcd();
}

volatile std::uint8_t &priorityRegister(Bank bank) {
  return bank == Bank::kPrimary ? DMA_DCHPRI2 : DMA_DCHPRI3;
}

IMXRT_DMA_TCD_t *descriptorBank(Bank bank) {
  if (bank == Bank::kPrimary) {
    return static_cast<IMXRT_DMA_TCD_t *>(
        gpio_capture::primaryRawDescriptorStorage());
  }
  return g_aux_descriptors == nullptr
             ? nullptr
             : g_aux_descriptors->descriptors.data();
}

std::int32_t descriptorAddress(Bank bank, std::uint8_t destination) {
  IMXRT_DMA_TCD_t *const descriptors = descriptorBank(bank);
  if (descriptors == nullptr || destination > kOverflowDestination) {
    return 0;
  }
  return static_cast<std::int32_t>(address32(
      &descriptors[destination]));
}

volatile const void *psrAddress(Bank bank) {
  return bank == Bank::kPrimary
             ? static_cast<volatile const void *>(&GPIO2_PSR)
             : static_cast<volatile const void *>(&GPIO1_PSR);
}

void configureDescriptor(IMXRT_DMA_TCD_t &descriptor, Bank bank,
                         std::uint8_t destination) {
  descriptor.SADDR = psrAddress(bank);
  descriptor.SOFF = 0;
  descriptor.ATTR = kTcdAttributes;
  descriptor.NBYTES_MLNO = sizeof(std::uint32_t);
  descriptor.SLAST = 0;
  descriptor.DADDR = g_ring->destinationWords(destination, bank);
  descriptor.DOFF = destination == kOverflowDestination
                        ? 0
                        : static_cast<std::int16_t>(sizeof(std::uint32_t));
  descriptor.CITER_ELINKNO = static_cast<std::uint16_t>(kSamplesPerBlock);
  descriptor.DLASTSGA = descriptorAddress(bank, kOverflowDestination);
  descriptor.CSR = kTcdControl;
  descriptor.BITER_ELINKNO = static_cast<std::uint16_t>(kSamplesPerBlock);
}

void copyDescriptorToHardware(Bank bank,
                              const IMXRT_DMA_TCD_t &source,
                              std::int32_t next_descriptor) {
  IMXRT_DMA_TCD_t &destination = hardwareTcd(bank);
  destination.SADDR = source.SADDR;
  destination.SOFF = source.SOFF;
  destination.ATTR = source.ATTR;
  destination.NBYTES_MLNO = source.NBYTES_MLNO;
  destination.SLAST = source.SLAST;
  destination.DADDR = source.DADDR;
  destination.DOFF = source.DOFF;
  destination.CITER_ELINKNO = source.CITER_ELINKNO;
  destination.DLASTSGA = next_descriptor;
  destination.CSR = source.CSR;
  destination.BITER_ELINKNO = source.BITER_ELINKNO;
}

void configureDescriptors(const PrimeResult &prime) {
  for (Bank bank : {Bank::kPrimary, Bank::kAuxiliary}) {
    IMXRT_DMA_TCD_t *const descriptors = descriptorBank(bank);
    for (std::uint8_t destination = 0U;
         destination <= kOverflowDestination; ++destination) {
      configureDescriptor(descriptors[destination], bank, destination);
    }
    copyDescriptorToHardware(
        bank, descriptors[prime.active_destination],
        descriptorAddress(bank, prime.queued_destination));
  }
  arm_dcache_flush_delete(descriptorBank(Bank::kPrimary),
                          board::kGpioRawDmaDescriptorBytes);
  arm_dcache_flush_delete(g_aux_descriptors, sizeof(*g_aux_descriptors));
}

bool hardwareDestinationMatches(Bank bank, std::uint8_t destination) {
  const std::uint32_t *const begin =
      g_ring->destinationWords(destination, bank);
  if (begin == nullptr) {
    return false;
  }
  const std::uintptr_t current =
      reinterpret_cast<std::uintptr_t>(hardwareTcd(bank).DADDR);
  const std::uintptr_t first = reinterpret_cast<std::uintptr_t>(begin);
  const std::uintptr_t end =
      first + (destination == kOverflowDestination
                   ? board::kCacheLineBytes
                   : sizeof(RawBlock));
  return current >= first && current <= end;
}

bool routeValid(const variable_rate::Schedule &schedule) {
  const std::uint16_t selected = *gpio_dma_route::xbarSelectRegister();
  const std::uint16_t control = *gpio_dma_route::xbarControlRegister();
  // STS0/STS1 are write-one-to-clear, so only the persistent EDGE/IEN/DEN
  // fields can participate in readback. The configuration write includes the
  // status bits precisely to clear any event left by an earlier run.
  constexpr std::uint16_t kPersistentControlMask =
      static_cast<std::uint16_t>(
          gpio_dma_route::kPairedXbarConfigurationMask &
          static_cast<std::uint16_t>(
              ~gpio_dma_route::kPairedXbarStatusMask));
  constexpr std::uint16_t kPersistentControlConfiguration =
      static_cast<std::uint16_t>(
          gpio_dma_route::kPairedXbarConfiguration &
          kPersistentControlMask);
  if ((selected & board::kPairedGpioXbarSelectionMask) !=
          (static_cast<std::uint16_t>(board::kGpioXbarInput) |
           static_cast<std::uint16_t>(
               static_cast<std::uint16_t>(board::kAuxGpioXbarInput)
               << 8U)) ||
      (control & kPersistentControlMask) !=
          kPersistentControlConfiguration ||
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel].LDVAL !=
          schedule.gpio_master_pit_load ||
      (DMA_ERQ & gpio_dma_route::kPairedEdmaChannelMask) !=
          gpio_dma_route::kPairedEdmaChannelMask) {
    return false;
  }
  for (Bank bank : {Bank::kPrimary, Bank::kAuxiliary}) {
    const IMXRT_DMA_TCD_t &tcd = hardwareTcd(bank);
    const std::uint8_t expected_priority =
        bank == Bank::kPrimary ? board::kPrimaryGpioInputEdmaPriority
                               : board::kAuxGpioEdmaPriority;
    if (*dmamuxRegister(bank) != dmamuxConfiguration(bank) ||
        tcd.SADDR != psrAddress(bank) || tcd.ATTR != kTcdAttributes ||
        tcd.NBYTES_MLNO != sizeof(std::uint32_t) ||
        tcd.DOFF != static_cast<std::int16_t>(sizeof(std::uint32_t)) ||
        tcd.CITER_ELINKNO != kSamplesPerBlock ||
        tcd.BITER_ELINKNO != kSamplesPerBlock ||
        tcd.CSR != kTcdControl ||
        (priorityRegister(bank) & 0x0FU) != expected_priority ||
        !hardwareDestinationMatches(
            bank, g_current_destinations[bankIndex(bank)])) {
      return false;
    }
  }
  return true;
}

void clearChannel(Bank bank) {
  *dmamuxRegister(bank) = 0U;
  DMA_CERQ = channel(bank);
  DMA_CERR = channel(bank);
  DMA_CEEI = channel(bank);
  DMA_CINT = channel(bank);
  DMA_CDNE = channel(bank);
}

void disableCommonTriggers() {
  IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL = 0U;
  IMXRT_PIT_CHANNELS[protocol_v1::kAdcTriggerPairPitChannel].TCTRL =
      PIT_TCTRL_CHN;
  ADC_ETC_CTRL &= ~ADC_ETC_CTRL_TRIG_ENABLE(kAdcTriggerEnableMask);
  gpio_dma_route::barrier();
}

bool commonTriggersStopped() {
  return (IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL &
          PIT_TCTRL_TEN) == 0U &&
         (IMXRT_PIT_CHANNELS[protocol_v1::kAdcTriggerPairPitChannel]
              .TCTRL & PIT_TCTRL_TEN) == 0U &&
         (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(kAdcTriggerEnableMask)) ==
             0U;
}

void disableDmaAndRoute() {
  gpio_dma_route::disablePairedEdmaRequests();
  gpio_dma_route::disablePairedXbarRequests();
  gpio_dma_route::barrier();
}

void disableInterrupts() {
  NVIC_DISABLE_IRQ(IRQ_DMA_CH2);
  NVIC_DISABLE_IRQ(IRQ_DMA_CH3);
}

void clearInterrupts() {
  DMA_CINT = board::kGpioEdmaChannel;
  DMA_CINT = board::kAuxGpioEdmaChannel;
  NVIC_CLEAR_PENDING(IRQ_DMA_CH2);
  NVIC_CLEAR_PENDING(IRQ_DMA_CH3);
}

std::uint64_t blockCoverageTicks() {
  return static_cast<std::uint64_t>(kSamplesPerBlock) *
         g_sample_period_ticks;
}

bool publishCompletion(Bank bank) {
  const std::size_t index = bankIndex(bank);
  // Acknowledge first. Everything below is fixed-size ownership publication;
  // cache maintenance and packing stay in cooperative context.
  DMA_CINT = channel(bank);
  if (!g_hardware_prepared || g_ring == nullptr) {
    saturatingIncrement(g_stale_dma_completions);
    return false;
  }
  if ((DMA_ERR & channelMask(bank)) != 0U) {
    DMA_CERR = channel(bank);
    return false;
  }
  const std::uint8_t active_after_completion =
      g_queued_destinations[index];
  if (!hardwareDestinationMatches(bank, active_after_completion)) {
    return false;
  }

  const CompletionResult completed = g_ring->onMajorLoopComplete(
      bank, g_epoch, g_current_generations[index],
      g_current_destinations[index], g_current_first_ticks[index],
      static_cast<std::uint32_t>(kSamplesPerBlock));
  if (!completed.consumed || !completed.ok() ||
      completed.future_generation != g_current_generations[index] + 2U) {
    if (!completed.consumed) {
      saturatingIncrement(g_stale_dma_completions);
    }
    return false;
  }
  const std::int32_t future =
      descriptorAddress(bank, completed.future_destination);
  if (future == 0) {
    return false;
  }
  hardwareTcd(bank).DLASTSGA = future;
  gpio_dma_route::barrier();

  g_current_generations[index] = g_queued_generations[index];
  g_current_destinations[index] = g_queued_destinations[index];
  g_current_first_ticks[index] = g_queued_first_ticks[index];
  g_queued_generations[index] = completed.future_generation;
  g_queued_destinations[index] = completed.future_destination;
  g_queued_first_ticks[index] =
      g_current_first_ticks[index] + blockCoverageTicks();
  return true;
}

void faultFromIsr() {
  disableCommonTriggers();
  disableDmaAndRoute();
  disableInterrupts();
  if (g_ring != nullptr) {
    g_ring->recordHardwareError(g_epoch);
  }
  forceSafeInputs();
  g_faulted = true;
  g_hardware_running = false;
}

void primaryDmaIsr() {
  if (!publishCompletion(Bank::kPrimary)) {
    faultFromIsr();
  }
  NVIC_CLEAR_PENDING(IRQ_DMA_CH2);
  __asm__ volatile("dsb" : : : "memory");
}

void auxiliaryDmaIsr() {
  if (!publishCompletion(Bank::kAuxiliary)) {
    faultFromIsr();
  }
  NVIC_CLEAR_PENDING(IRQ_DMA_CH3);
  __asm__ volatile("dsb" : : : "memory");
}

std::uint32_t activeSamples(Bank bank) {
  const IMXRT_DMA_TCD_t &tcd = hardwareTcd(bank);
  if (tcd.BITER_ELINKNO != kSamplesPerBlock ||
      tcd.CITER_ELINKNO > tcd.BITER_ELINKNO) {
    if (g_ring != nullptr) {
      g_ring->recordHardwareError(g_epoch);
    }
    return 0U;
  }
  return static_cast<std::uint32_t>(tcd.BITER_ELINKNO -
                                    tcd.CITER_ELINKNO);
}

bool resourcesBusy() {
  return (IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL &
          PIT_TCTRL_TEN) != 0U ||
         gpio_dma_route::pairedEdmaRequestBusy() ||
         gpio_dma_route::pairedOutputsBusy();
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.capture_resources_quiescent")
bool captureResourcesQuiescent() {
  return commonTriggersStopped() &&
         !gpio_dma_route::pairedEdmaRequestBusy() &&
         !gpio_dma_route::pairedOutputsBusy();
}

std::uint8_t *workspaceBase() {
  return benchmark::teensyOcramBuffer().bytes.data();
}

bool constructWorkspace() {
  if (g_workspace_claimed) {
    return false;
  }
  std::uint8_t *const base = workspaceBase();
  g_ring = ::new (static_cast<void *>(
      base + board::kGpioPairedJoinStateOffsetBytes))
      DualBankCaptureRing{gpio_capture::pairedRawStorage(),
                          *(::new (static_cast<void *>(
                              base + board::
                                  kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes))
                                PairedOverflowSink{}),
                          g_cache, g_critical};
  g_overflow_sink = reinterpret_cast<PairedOverflowSink *>(
      base + board::kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes);
  g_aux_descriptors = ::new (static_cast<void *>(
      base + board::kAuxGpioRawDmaDescriptorOffsetBytes))
      AuxDescriptorBank{};
  g_workspace_claimed = true;
  return true;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.release_workspace")
void releaseWorkspaceIfQuiescent() {
  if (g_ring == nullptr || !g_ring->quiescent()) {
    return;
  }
  g_cached_snapshot = g_ring->snapshot();
  g_ring->~DualBankCaptureRing();
  g_ring = nullptr;
  g_aux_descriptors = nullptr;
  g_overflow_sink = nullptr;
  g_workspace_claimed = false;
  gpio_capture::releaseRawStorage(
      gpio_capture::RawStorageOwner::kPaired);
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.cache_hardware_fields")
void cacheHardwareFields(Snapshot &snapshot) {
  snapshot.resource_conflicts = g_resource_conflicts;
  snapshot.start_errors = g_start_errors;
  snapshot.stop_errors = g_stop_errors;
  snapshot.stale_dma_completions = g_stale_dma_completions;
  snapshot.hardware_prepared = g_hardware_prepared;
  snapshot.faulted = g_faulted;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.current_snapshot")
Snapshot currentSnapshot() {
  Snapshot value = g_ring == nullptr ? g_cached_snapshot
                                     : g_ring->snapshot();
  cacheHardwareFields(value);
  return value;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.rollback_preparation")
void rollbackPreparation() {
  disableCommonTriggers();
  disableDmaAndRoute();
  disableInterrupts();
  clearInterrupts();
  for (Bank bank : {Bank::kPrimary, Bank::kAuxiliary}) {
    clearChannel(bank);
  }
  forceSafeInputs();
  g_pins_verified = pinsValid();
  g_hardware_prepared = false;
  g_hardware_running = false;
  if (g_ring != nullptr && g_ring->snapshot().running) {
    (void)g_ring->cancel(g_epoch, StopReason::kRollback);
    (void)g_ring->serviceDiscarded();
  }
  releaseWorkspaceIfQuiescent();
  g_epoch = 0U;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.inspect")
StartStatus inspectHardwareStart(std::uint32_t epoch,
                                 protocol_v2::RateProfile profile) {
  if (epoch == 0U) {
    return StartStatus::kInvalidEpoch;
  }
  if (!variable_rate::derive(profile).ok()) {
    return StartStatus::kUnsupportedProfile;
  }
  if (g_hardware_prepared || g_hardware_running) {
    return StartStatus::kAlreadyRunning;
  }
  if (g_ring != nullptr && !g_ring->quiescent()) {
    return StartStatus::kNotQuiescent;
  }
  if (!gpio_capture::rawStorageAvailable(
          gpio_capture::RawStorageOwner::kPaired) ||
      resourcesBusy() || g_workspace_claimed) {
    return StartStatus::kResourceBusy;
  }
  return StartStatus::kOk;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.prepare")
StartStatus prepareHardware(std::uint32_t epoch,
                            protocol_v2::RateProfile profile) {
  const StartStatus readiness = inspectHardwareStart(epoch, profile);
  if (readiness != StartStatus::kOk) {
    if (readiness == StartStatus::kResourceBusy) {
      saturatingIncrement(g_resource_conflicts);
    } else {
      saturatingIncrement(g_start_errors);
    }
    return readiness;
  }
  const variable_rate::DeriveResult derived =
      variable_rate::derive(profile);
  if (!derived.ok() ||
      !gpio_capture::claimRawStorage(
          gpio_capture::RawStorageOwner::kPaired) ||
      !constructWorkspace()) {
    gpio_capture::releaseRawStorage(
        gpio_capture::RawStorageOwner::kPaired);
    saturatingIncrement(g_start_errors);
    return StartStatus::kResourceBusy;
  }

  g_epoch = epoch;
  g_sample_period_ticks = derived.schedule.gpio_sample_period_ticks;
  g_profile = profile;
  g_gpio1_gdir_unrelated = GPIO1_GDIR & ~board::kGpio1PsrCaptureMask;
  g_gpr26_unrelated = IOMUXC_GPR_GPR26 &
                      ~board::kGpio6ToGpio1Gpr26ClearMask;
  g_gpio2_gdir_unrelated = GPIO2_GDIR & ~board::kGpio2PsrCaptureMask;
  g_gpr27_unrelated = IOMUXC_GPR_GPR27 &
                      ~board::kGpio7ToGpio2Gpr27ClearMask;
  g_faulted = false;
  g_pins_verified = false;
  g_route_verified = false;
  g_cached_snapshot = {};
  g_last_incomplete_samples = {};
  g_stale_dma_completions = 0U;

  const PrimeResult prime =
      g_ring->prime(epoch, g_sample_period_ticks);
  if (!prime.ok()) {
    saturatingIncrement(g_start_errors);
    rollbackPreparation();
    return prime.status == OperationStatus::kInvalidEpoch
               ? StartStatus::kInvalidEpoch
               : StartStatus::kNotQuiescent;
  }
  const std::uint64_t coverage = blockCoverageTicks();
  for (std::size_t index = 0U; index < kBankCount; ++index) {
    g_current_generations[index] = prime.active_generation;
    g_queued_generations[index] = prime.queued_generation;
    g_current_destinations[index] = prime.active_destination;
    g_queued_destinations[index] = prime.queued_destination;
    g_current_first_ticks[index] = 0U;
    g_queued_first_ticks[index] = coverage;
  }

  gpio_dma_route::enableClockGates();
  gpio_dma_route::configureStoppedPit(
      derived.schedule.gpio_master_pit_load, false);
  disableInterrupts();
  gpio_dma_route::clearEdmaChannelState();
  gpio_dma_route::clearAuxEdmaChannelState();
  configureDescriptors(prime);
  gpio_dma_route::configurePairedEdmaPriorities();
  gpio_dma_route::configurePairedXbarRequests();
  forceSafeInputs();

  attachInterruptVector(IRQ_DMA_CH2, primaryDmaIsr);
  attachInterruptVector(IRQ_DMA_CH3, auxiliaryDmaIsr);
  NVIC_SET_PRIORITY(IRQ_DMA_CH2, board::kGpioEdmaIrqPriority);
  NVIC_SET_PRIORITY(IRQ_DMA_CH3, board::kAuxGpioEdmaIrqPriority);
  clearInterrupts();
  g_hardware_prepared = true;
  g_hardware_running = true;
  NVIC_ENABLE_IRQ(IRQ_DMA_CH2);
  NVIC_ENABLE_IRQ(IRQ_DMA_CH3);
  gpio_dma_route::enablePairedEdmaRequests();
  gpio_dma_route::barrier();

  g_pins_verified = pinsValid();
  g_route_verified = routeValid(derived.schedule);
  if (!g_pins_verified || !g_route_verified ||
      (IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL &
       PIT_TCTRL_TEN) != 0U) {
    g_faulted = true;
    saturatingIncrement(g_start_errors);
    rollbackPreparation();
    return StartStatus::kHardwareError;
  }
  g_resource_conflicts = 0U;
  g_start_errors = 0U;
  g_stop_errors = 0U;
  return StartStatus::kOk;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.start")
StartStatus startHardware(std::uint32_t epoch,
                          protocol_v2::RateProfile profile) {
  const StartStatus prepared = prepareHardware(epoch, profile);
  if (prepared != StartStatus::kOk) {
    return prepared;
  }
  IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  pit.TFLG = PIT_TFLG_TIF;
  pit.TCTRL = PIT_TCTRL_TEN;
  gpio_dma_route::barrier();
  if ((pit.TCTRL & PIT_TCTRL_TEN) == 0U) {
    g_faulted = true;
    saturatingIncrement(g_start_errors);
    rollbackPreparation();
    return StartStatus::kHardwareError;
  }
  return StartStatus::kOk;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.stop")
StopReport stopHardwareAfterTriggers(StopReason reason) {
  StopReport report{};
  report.reason = reason;
  if (g_ring == nullptr || !g_ring->snapshot().running) {
    const Snapshot before = currentSnapshot();
    report.ready_buffers_to_drain = before.ready_depth;
    report.reading_buffers_to_release = before.reading_depth;
    return report;
  }
  if (!commonTriggersStopped()) {
    saturatingIncrement(g_stop_errors);
    report.status = OperationStatus::kInvalidStopProgress;
    return report;
  }

  disableDmaAndRoute();
  disableInterrupts();
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  for (Bank bank : {Bank::kPrimary, Bank::kAuxiliary}) {
    if ((DMA_INT & channelMask(bank)) != 0U && !publishCompletion(bank)) {
      g_ring->recordHardwareError(g_epoch);
      g_faulted = true;
    }
  }

  std::array<BankStopState, kBankCount> states{};
  for (Bank bank : {Bank::kPrimary, Bank::kAuxiliary}) {
    const std::size_t index = bankIndex(bank);
    states[index].generation = g_current_generations[index];
    states[index].destination = g_current_destinations[index];
    states[index].first_sample_ticks = g_current_first_ticks[index];
    states[index].sample_count = activeSamples(bank);
    g_last_incomplete_samples[index] = states[index].sample_count;
    clearChannel(bank);
  }
  clearInterrupts();
  gpio_dma_route::barrier();
  g_hardware_prepared = false;
  g_hardware_running = false;
  forceSafeInputs();
  g_pins_verified = pinsValid();
  const bool teardown_verified =
      captureResourcesQuiescent() && g_pins_verified;
  if (!teardown_verified) {
    g_ring->recordHardwareError(g_epoch);
    g_faulted = true;
  }
  restorePrimask(primask);

  const StopReason effective_reason =
      g_faulted ? StopReason::kFault : reason;
  report = g_ring->stop(states, effective_reason);
  if (!teardown_verified && report.status == OperationStatus::kOk) {
    report.status = OperationStatus::kInvalidStopProgress;
  }
  (void)g_ring->serviceDiscarded();
  if (report.status != OperationStatus::kOk &&
      report.status != OperationStatus::kNotRunning) {
    saturatingIncrement(g_stop_errors);
  }
  g_cached_snapshot = g_ring->snapshot();
  cacheHardwareFields(g_cached_snapshot);
  g_epoch = 0U;
  releaseWorkspaceIfQuiescent();
  return report;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.hardware_snapshot")
HardwareSnapshot hardwareSnapshot() {
  HardwareSnapshot value{};
  value.ring = currentSnapshot();
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  for (Bank bank : {Bank::kPrimary, Bank::kAuxiliary}) {
    const std::size_t index = bankIndex(bank);
    HardwareBankSnapshot &target = value.banks[index];
    const IMXRT_DMA_TCD_t &tcd = hardwareTcd(bank);
    target.gdir = bank == Bank::kPrimary ? GPIO2_GDIR : GPIO1_GDIR;
    target.psr = bank == Bank::kPrimary ? GPIO2_PSR : GPIO1_PSR;
    target.dmamux_chcfg = *dmamuxRegister(bank);
    target.tcd_saddr = address32(tcd.SADDR);
    target.tcd_daddr = address32(tcd.DADDR);
    target.tcd_citer = tcd.CITER_ELINKNO;
    target.tcd_biter = tcd.BITER_ELINKNO;
    target.tcd_csr = tcd.CSR;
    target.edma_priority =
        static_cast<std::uint8_t>(priorityRegister(bank) & 0x0FU);
    target.current_destination = g_current_destinations[index];
    target.queued_destination = g_queued_destinations[index];
    target.current_generation = g_current_generations[index];
    target.last_incomplete_samples = g_last_incomplete_samples[index];
  }
  for (std::size_t index = 0U; index < 16U; ++index) {
    value.mux[index] = *muxRegister(index);
    value.pad[index] = *padRegister(index);
  }
  value.gpr26 = IOMUXC_GPR_GPR26;
  value.gpr27 = IOMUXC_GPR_GPR27;
  value.pit_ldval =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel].LDVAL;
  value.pit_tctrl =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL;
  value.xbar_select = *gpio_dma_route::xbarSelectRegister();
  value.xbar_control = *gpio_dma_route::xbarControlRegister();
  value.dma_erq = DMA_ERQ;
  value.dma_err = DMA_ERR;
  value.profile = g_profile;
  value.pins_verified = g_pins_verified;
  value.route_verified = g_route_verified;
  value.hardware_running = g_hardware_running;
  restorePrimask(primask);
  return value;
}

}  // namespace

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_inspect")
StartStatus TeensyDualBankCapture::inspectStart(
    std::uint32_t epoch, protocol_v2::RateProfile profile) {
  return inspectHardwareStart(epoch, profile);
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_prepare")
StartStatus TeensyDualBankCapture::prepare(
    std::uint32_t epoch, protocol_v2::RateProfile profile) {
  return prepareHardware(epoch, profile);
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_start")
StartStatus TeensyDualBankCapture::start(
    std::uint32_t epoch, protocol_v2::RateProfile profile) {
  return startHardware(epoch, profile);
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_stop_after_triggers")
StopReport TeensyDualBankCapture::stopAfterTriggers(StopReason reason) {
  return stopHardwareAfterTriggers(reason);
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.facade_stop")
StopReport TeensyDualBankCapture::stop(StopReason reason) {
  disableCommonTriggers();
  return stopHardwareAfterTriggers(reason);
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_service_ownership")
std::size_t TeensyDualBankCapture::serviceOwnership() {
  if (g_ring == nullptr) {
    return 0U;
  }
  const std::size_t serviced = g_ring->serviceDiscarded();
  g_cached_snapshot = g_ring->snapshot();
  releaseWorkspaceIfQuiescent();
  return serviced;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_acquire_ready")
AcquireResult TeensyDualBankCapture::acquireReady() {
  return g_ring == nullptr ? AcquireResult{} : g_ring->acquireReady();
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_release")
OperationStatus TeensyDualBankCapture::release(
    const BufferHandle &handle) {
  if (g_ring == nullptr) {
    return OperationStatus::kInvalidHandle;
  }
  const OperationStatus status = g_ring->release(handle);
  g_cached_snapshot = g_ring->snapshot();
  releaseWorkspaceIfQuiescent();
  return status;
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_raw_snapshot")
Snapshot TeensyDualBankCapture::rawSnapshot() {
  return currentSnapshot();
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(
    ".flashmem.gpio_dual.facade_hardware_snapshot")
HardwareSnapshot TeensyDualBankCapture::snapshot() {
  return hardwareSnapshot();
}

THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE(".flashmem.gpio_dual.singleton")
TeensyDualBankCapture &teensyDualBankCapture() { return g_facade; }

static_assert(sizeof(AuxDescriptorBank) ==
              board::kAuxGpioRawDmaDescriptorBytes);
static_assert(alignof(AuxDescriptorBank) == board::kCacheLineBytes);
static_assert(board::kGpioPairedJoinStateOffsetBytes %
                      alignof(DualBankCaptureRing) ==
                  0U);
static_assert(board::kAuxGpioRawDmaDescriptorOffsetBytes %
                      alignof(AuxDescriptorBank) ==
                  0U);
static_assert(board::kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes %
                      alignof(PairedOverflowSink) ==
                  0U);
static_assert(board::kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes +
                      sizeof(PairedOverflowSink) ==
                  board::kAuxInputWorkspaceBytes);
static_assert(kSamplesPerBlock <=
              static_cast<std::size_t>(
                  std::numeric_limits<std::int16_t>::max()));

}  // namespace thingdaq::gpio_join

#endif

#undef THINGDAQ_DUAL_GPIO_TARGET_COLD_CODE
