#include "adc_dma_capture_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>

#include <core_pins.h>
#include <imxrt.h>

#include "board_config.h"
#include "gpio_dma_route_teensy.h"

#define TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace teensy_daq::adc_capture {

struct alignas(board::kCacheLineBytes) DescriptorBank {
  std::array<std::array<IMXRT_DMA_TCD_t, board::kAdcDmaDescriptorCount>,
             kConverterCount>
      descriptors{};
};

PairBufferStorage g_adc_dma_buffers
    __attribute__((section(".dmabuffers"), used));
PairOverflowSink g_adc_dma_overflow_sink
    __attribute__((section(".dmabuffers"), used));
DescriptorBank g_adc_dma_descriptors
    __attribute__((section(".dmabuffers"), used));

namespace {

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.allocations")
void *retainDmaAllocations() {
  __asm__ volatile(""
                   :
                   : "r"(&g_adc_dma_buffers),
                     "r"(&g_adc_dma_overflow_sink),
                     "r"(&g_adc_dma_descriptors)
                   : "memory");
  return &g_adc_dma_buffers;
}

void *volatile g_dma_allocation_link_anchor = retainDmaAllocations();

constexpr std::uint16_t kTcdAttributes =
    DMA_TCD_ATTR_SSIZE(1U) | DMA_TCD_ATTR_DSIZE(1U);
constexpr std::uint16_t kTcdControl =
    DMA_TCD_CSR_ESG | DMA_TCD_CSR_INTMAJOR;
constexpr std::uint32_t kStopBoundaryTimeoutCycles =
    protocol_v1::kAdcTriggerDwtClockHz / 100U;
constexpr std::uint32_t kStopBoundaryPollLimit =
    protocol_v1::kAdcTriggerDiagnosticPollLimit;
constexpr std::uint16_t kStopBoundaryArmMinimumPairs =
    static_cast<std::uint16_t>(
        (protocol_v1::kAdcPairsPerFrame * 3U) / 4U);
constexpr std::uint32_t kAdcDmaChannelMask =
    (std::uint32_t{1U} <<
     board::kAdcConverterConfigurations[0].edma_channel) |
    (std::uint32_t{1U} <<
     board::kAdcConverterConfigurations[1].edma_channel);
constexpr std::uint32_t kAdcTriggerEnableMask =
    (std::uint32_t{1U} <<
     board::kAdcConverterConfigurations[0].adc_etc_trigger) |
    (std::uint32_t{1U} <<
     board::kAdcConverterConfigurations[1].adc_etc_trigger);
constexpr std::array<std::uint32_t, kConverterCount> kAdcEtcErrorMasks{
    ADC_ETC_DONE2_ERR_IRQ_TRIG_ERR(
        board::kAdcConverterConfigurations[0].adc_etc_trigger),
    ADC_ETC_DONE2_ERR_IRQ_TRIG_ERR(
        board::kAdcConverterConfigurations[1].adc_etc_trigger)};
constexpr std::uint32_t kAdcEtcErrorMask =
    kAdcEtcErrorMasks[0] | kAdcEtcErrorMasks[1];

std::uint32_t readPrimask() {
  std::uint32_t value = 0U;
  __asm__ volatile("mrs %0, primask" : "=r"(value) : : "memory");
  return value;
}

void restorePrimask(std::uint32_t value) {
  if ((value & 1U) == 0U) {
    __enable_irq();
  }
}

void barrier() { gpio_dma_route::barrier(); }

template <typename Integer>
void saturatingIncrement(Integer &value) {
  if (value != std::numeric_limits<Integer>::max()) {
    ++value;
  }
}

class TeensyCacheMaintenance final : public CacheMaintenance {
 public:
  TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.cache_discard")
  void discardBeforeDmaWrite(void *address, std::size_t bytes) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(bytes));
  }

  TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.cache_invalidate")
  void invalidateBeforeCpuRead(void *address, std::size_t bytes) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(bytes));
  }
};

class TeensyCriticalSection final : public CriticalSection {
 public:
  TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.critical_enter")
  std::uint32_t enter() override {
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    return primask;
  }

  TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.critical_exit")
  void exit(std::uint32_t token) override { restorePrimask(token); }
};

TeensyCacheMaintenance g_cache{};
TeensyCriticalSection g_critical{};
PairCaptureRing g_ring{g_adc_dma_buffers, g_adc_dma_overflow_sink,
                       g_cache, g_critical};
TeensyAdcDmaCapture g_facade{};

std::array<std::uint32_t, kConverterCount> g_current_generations{};
std::array<std::uint8_t, kConverterCount> g_current_destinations{
    kInvalidDestination, kInvalidDestination};
std::array<std::uint8_t, kConverterCount> g_next_destinations{
    kInvalidDestination, kInvalidDestination};
std::uint32_t g_epoch = 0U;
std::uint32_t g_adc_etc_error_flags = 0U;
std::uint32_t g_adc_etc_error_interrupts = 0U;
std::uint32_t g_resource_conflicts = 0U;
std::uint32_t g_start_errors = 0U;
std::uint32_t g_stop_errors = 0U;
std::uint32_t g_stale_interrupts = 0U;
bool g_hardware_prepared = false;
bool g_faulted = false;

std::uint32_t address32(const volatile void *address) {
  return static_cast<std::uint32_t>(
      reinterpret_cast<std::uintptr_t>(address));
}

constexpr std::uint32_t channelMask(std::size_t converter) {
  return std::uint32_t{1U}
         << board::kAdcConverterConfigurations[converter].edma_channel;
}

volatile std::uint32_t *dmamuxRegister(std::size_t converter) {
  return &DMAMUX_CHCFG0 +
         board::kAdcConverterConfigurations[converter].edma_channel;
}

constexpr std::uint32_t dmamuxConfiguration(std::size_t converter) {
  return DMAMUX_CHCFG_ENBL |
         board::kAdcConverterConfigurations[converter].dmamux_source;
}

IMXRT_DMA_TCD_t &hardwareTcd(std::size_t converter) {
  return IMXRT_DMA_TCD[
      board::kAdcConverterConfigurations[converter].edma_channel];
}

volatile std::uint32_t &adcGc(std::size_t converter) {
  return converter == 0U ? ADC1_GC : ADC2_GC;
}

volatile const void *adcResultAddress(std::size_t converter) {
  return converter == 0U
             ? static_cast<volatile const void *>(&ADC1_R0)
             : static_cast<volatile const void *>(&ADC2_R0);
}

volatile std::uint8_t &priorityRegister(std::size_t converter) {
  return converter == 0U ? DMA_DCHPRI0 : DMA_DCHPRI1;
}

std::int32_t descriptorAddress(std::size_t converter,
                               std::uint8_t destination) {
  if (converter >= kConverterCount || destination > kOverflowDestination) {
    return 0;
  }
  return static_cast<std::int32_t>(address32(
      &g_adc_dma_descriptors.descriptors[converter][destination]));
}

bool triggersStopped() {
  const IMXRT_PIT_CHANNEL_t &master = IMXRT_PIT_CHANNELS[
      protocol_v1::kAdcTriggerGpioMasterPitChannel];
  const IMXRT_PIT_CHANNEL_t &pair =
      IMXRT_PIT_CHANNELS[protocol_v1::kAdcTriggerPairPitChannel];
  return (ADC_ETC_CTRL & ADC_ETC_CTRL_TRIG_ENABLE(kAdcTriggerEnableMask)) ==
             0U &&
         (master.TCTRL & PIT_TCTRL_TEN) == 0U &&
         (pair.TCTRL & PIT_TCTRL_TEN) == 0U &&
         ((IMXRT_ADC1.GS | IMXRT_ADC2.GS) & ADC_GS_ADACT) == 0U;
}

bool resourcesBusy() {
  if ((DMA_ERQ & kAdcDmaChannelMask) != 0U ||
      (ADC1_GC & ADC_GC_DMAEN) != 0U ||
      (ADC2_GC & ADC_GC_DMAEN) != 0U) {
    return true;
  }
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    if ((*dmamuxRegister(converter) & DMAMUX_CHCFG_ENBL) != 0U) {
      return true;
    }
  }
  return false;
}

void clearChannelState(std::size_t converter) {
  const std::uint8_t channel =
      board::kAdcConverterConfigurations[converter].edma_channel;
  *dmamuxRegister(converter) = 0U;
  DMA_CERQ = channel;
  DMA_CERR = channel;
  DMA_CEEI = channel;
  DMA_CINT = channel;
  DMA_CDNE = channel;
}

void disableRequests() {
  ADC1_GC &= ~ADC_GC_DMAEN;
  ADC2_GC &= ~ADC_GC_DMAEN;
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    DMA_CERQ = board::kAdcConverterConfigurations[converter].edma_channel;
    *dmamuxRegister(converter) = 0U;
  }
  barrier();
}

void configureDescriptor(IMXRT_DMA_TCD_t &descriptor,
                         std::size_t converter,
                         std::uint8_t destination) {
  descriptor.SADDR = adcResultAddress(converter);
  descriptor.SOFF = 0;
  descriptor.ATTR = kTcdAttributes;
  descriptor.NBYTES_MLNO = sizeof(std::uint16_t);
  descriptor.SLAST = 0;
  descriptor.DADDR = g_ring.destinationHalfword(destination,
                                                 static_cast<std::uint8_t>(
                                                     converter));
  descriptor.DOFF = destination == kOverflowDestination
                        ? 0
                        : static_cast<std::int16_t>(sizeof(SamplePair));
  descriptor.CITER_ELINKNO = static_cast<std::uint16_t>(
      protocol_v1::kAdcPairsPerFrame);
  descriptor.DLASTSGA = descriptorAddress(converter, kOverflowDestination);
  descriptor.CSR = kTcdControl;
  descriptor.BITER_ELINKNO = static_cast<std::uint16_t>(
      protocol_v1::kAdcPairsPerFrame);
}

void copyDescriptorToHardware(std::size_t converter,
                              const IMXRT_DMA_TCD_t &source,
                              std::int32_t next_descriptor) {
  IMXRT_DMA_TCD_t &destination = hardwareTcd(converter);
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
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    for (std::uint8_t destination = 0U;
         destination <= kOverflowDestination; ++destination) {
      configureDescriptor(
          g_adc_dma_descriptors.descriptors[converter][destination],
          converter, destination);
    }
  }
  arm_dcache_flush_delete(&g_adc_dma_descriptors,
                          sizeof(g_adc_dma_descriptors));
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    copyDescriptorToHardware(
        converter,
        g_adc_dma_descriptors
            .descriptors[converter][prime.active_destination],
        descriptorAddress(converter, prime.queued_destination));
  }
}

void configurePriorities() {
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    priorityRegister(converter) = static_cast<std::uint8_t>(
        DMA_DCHPRI_ECP |
        DMA_DCHPRI_CHPRI(board::kAdcEdmaPriorities[converter]));
  }
}

bool hardwareDestinationMatches(std::size_t converter,
                                std::uint8_t destination) {
  const std::uint16_t *const begin = g_ring.destinationHalfword(
      destination, static_cast<std::uint8_t>(converter));
  if (begin == nullptr) {
    return false;
  }
  const std::uintptr_t current =
      reinterpret_cast<std::uintptr_t>(hardwareTcd(converter).DADDR);
  const std::uintptr_t first = reinterpret_cast<std::uintptr_t>(begin);
  const std::uintptr_t end =
      first + (destination == kOverflowDestination
                   ? sizeof(std::uint16_t)
                   : protocol_v1::kDataPayloadBytes);
  return current >= first && current <= end;
}

bool configuredHardwareValid() {
  if ((DMA_ERQ & kAdcDmaChannelMask) != kAdcDmaChannelMask ||
      (ADC1_GC & ADC_GC_DMAEN) == 0U ||
      (ADC2_GC & ADC_GC_DMAEN) == 0U ||
      (DMA_ERR & kAdcDmaChannelMask) != 0U) {
    return false;
  }
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    const IMXRT_DMA_TCD_t &tcd = hardwareTcd(converter);
    if (*dmamuxRegister(converter) != dmamuxConfiguration(converter) ||
        tcd.SADDR != adcResultAddress(converter) ||
        tcd.ATTR != kTcdAttributes ||
        tcd.NBYTES_MLNO != sizeof(std::uint16_t) ||
        tcd.DOFF != static_cast<std::int16_t>(sizeof(SamplePair)) ||
        tcd.CITER_ELINKNO != protocol_v1::kAdcPairsPerFrame ||
        tcd.BITER_ELINKNO != protocol_v1::kAdcPairsPerFrame ||
        tcd.CSR != kTcdControl ||
        (priorityRegister(converter) & 0x0FU) !=
            board::kAdcEdmaPriorities[converter] ||
        !hardwareDestinationMatches(converter,
                                    g_current_destinations[converter])) {
      return false;
    }
  }
  return true;
}

void processDmaCompletion(std::size_t converter) {
  const std::uint8_t channel =
      board::kAdcConverterConfigurations[converter].edma_channel;
  const std::uint32_t mask = channelMask(converter);
  const bool pending = (DMA_INT & mask) != 0U;
  DMA_CINT = channel;
  if (!pending || !g_hardware_prepared) {
    saturatingIncrement(g_stale_interrupts);
    return;
  }
  if ((DMA_ERR & mask) != 0U) {
    DMA_CERR = channel;
    g_ring.recordDmaError(g_epoch, static_cast<std::uint8_t>(converter));
  }

  const std::uint32_t completed_generation =
      g_current_generations[converter];
  const std::uint8_t completed_destination =
      g_current_destinations[converter];
  const CompletionResult completed = g_ring.onMajorLoopComplete(
      static_cast<std::uint8_t>(converter), g_epoch,
      completed_generation, completed_destination);
  if (!completed.consumed) {
    saturatingIncrement(g_stale_interrupts);
    return;
  }

  g_current_generations[converter] = completed_generation + 1U;
  g_current_destinations[converter] = g_next_destinations[converter];
  g_next_destinations[converter] = completed.future_destination;
  if (!hardwareDestinationMatches(converter,
                                  g_current_destinations[converter])) {
    g_ring.recordDmaError(g_epoch, static_cast<std::uint8_t>(converter));
    g_faulted = true;
    g_next_destinations[converter] = kOverflowDestination;
  }
  const std::int32_t next = descriptorAddress(
      converter, g_next_destinations[converter]);
  if (next == 0) {
    g_ring.recordDmaError(g_epoch, static_cast<std::uint8_t>(converter));
    g_faulted = true;
    hardwareTcd(converter).DLASTSGA =
        descriptorAddress(converter, kOverflowDestination);
  } else {
    hardwareTcd(converter).DLASTSGA = next;
  }
  barrier();
}

void adc0DmaIsr() {
  processDmaCompletion(0U);
  __asm__ volatile("dsb" : : : "memory");
}

void adc1DmaIsr() {
  processDmaCompletion(1U);
  __asm__ volatile("dsb" : : : "memory");
}

void adcEtcErrorIsr() {
  const std::uint32_t pending = ADC_ETC_DONE2_ERR_IRQ & kAdcEtcErrorMask;
  if (pending == 0U) {
    saturatingIncrement(g_stale_interrupts);
    return;
  }
  std::uint8_t converter_mask = 0U;
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    if ((pending & kAdcEtcErrorMasks[converter]) != 0U) {
      converter_mask = static_cast<std::uint8_t>(
          converter_mask | (1U << converter));
    }
  }
  g_adc_etc_error_flags |= pending;
  saturatingIncrement(g_adc_etc_error_interrupts);
  g_ring.recordAdcEtcError(g_epoch, converter_mask, pending);
  ADC_ETC_DONE2_ERR_IRQ = pending;
  __asm__ volatile("dsb" : : : "memory");
}

void disableInterrupts() {
  NVIC_DISABLE_IRQ(IRQ_DMA_CH0);
  NVIC_DISABLE_IRQ(IRQ_DMA_CH1);
  NVIC_DISABLE_IRQ(IRQ_ADC_ETC_ERR);
}

void clearInterruptState() {
  DMA_CINT = board::kAdcConverterConfigurations[0].edma_channel;
  DMA_CINT = board::kAdcConverterConfigurations[1].edma_channel;
  ADC_ETC_DONE2_ERR_IRQ = kAdcEtcErrorMask;
  NVIC_CLEAR_PENDING(IRQ_DMA_CH0);
  NVIC_CLEAR_PENDING(IRQ_DMA_CH1);
  NVIC_CLEAR_PENDING(IRQ_ADC_ETC_ERR);
}

void enableInterrupts() {
  attachInterruptVector(IRQ_DMA_CH0, adc0DmaIsr);
  attachInterruptVector(IRQ_DMA_CH1, adc1DmaIsr);
  attachInterruptVector(IRQ_ADC_ETC_ERR, adcEtcErrorIsr);
  NVIC_SET_PRIORITY(IRQ_DMA_CH0, board::kAdcEdmaIrqPriority);
  NVIC_SET_PRIORITY(IRQ_DMA_CH1, board::kAdcEdmaIrqPriority);
  // All acquisition-state writers use one preemption priority. Main context
  // uses the shared critical section, while equal-priority IRQs serialize the
  // two completion paths and ADC_ETC error attribution.
  NVIC_SET_PRIORITY(IRQ_ADC_ETC_ERR, board::kAdcEdmaIrqPriority);
  clearInterruptState();
  NVIC_ENABLE_IRQ(IRQ_DMA_CH0);
  NVIC_ENABLE_IRQ(IRQ_DMA_CH1);
  NVIC_ENABLE_IRQ(IRQ_ADC_ETC_ERR);
}

std::uint32_t activeMinorPairs(std::size_t converter) {
  const IMXRT_DMA_TCD_t &tcd = hardwareTcd(converter);
  const std::uint16_t biter = tcd.BITER_ELINKNO;
  const std::uint16_t citer = tcd.CITER_ELINKNO;
  if (biter != protocol_v1::kAdcPairsPerFrame || citer > biter) {
    g_ring.recordDmaError(g_epoch, static_cast<std::uint8_t>(converter));
    return 0U;
  }
  return static_cast<std::uint32_t>(biter - citer);
}

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(
    ".flashmem.adc_dma.target_stop_boundary")
bool waitForCompleteStopBoundary() {
  if (!g_hardware_prepared || g_faulted) {
    return false;
  }
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
  const std::uint32_t started = ARM_DWT_CYCCNT;
  std::uint32_t polls = 0U;
  bool armed = false;
  while (ARM_DWT_CYCCNT - started < kStopBoundaryTimeoutCycles &&
         polls < kStopBoundaryPollLimit && !armed) {
    ++polls;
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    bool safe_to_arm =
        (DMA_ERQ & kAdcDmaChannelMask) == kAdcDmaChannelMask &&
        g_current_generations[0] == g_current_generations[1] &&
        g_current_destinations[0] == g_current_destinations[1];
    for (std::size_t converter = 0U;
         converter < kConverterCount && safe_to_arm; ++converter) {
      const IMXRT_DMA_TCD_t &tcd = hardwareTcd(converter);
      safe_to_arm =
          tcd.BITER_ELINKNO == protocol_v1::kAdcPairsPerFrame &&
          tcd.CITER_ELINKNO > kStopBoundaryArmMinimumPairs &&
          tcd.CITER_ELINKNO <= tcd.BITER_ELINKNO;
    }
    if (safe_to_arm) {
      for (std::size_t converter = 0U; converter < kConverterCount;
           ++converter) {
        IMXRT_DMA_TCD_t &tcd = hardwareTcd(converter);
        tcd.CSR =
            static_cast<std::uint16_t>(tcd.CSR | DMA_TCD_CSR_DREQ);
      }
      barrier();
      armed = true;
    }
    restorePrimask(primask);
  }

  while ((DMA_ERQ & kAdcDmaChannelMask) != 0U &&
         ARM_DWT_CYCCNT - started < kStopBoundaryTimeoutCycles &&
         polls < kStopBoundaryPollLimit) {
    ++polls;
  }
  const bool completed = armed &&
      (DMA_ERQ & kAdcDmaChannelMask) == 0U;
  if (!completed) {
    saturatingIncrement(g_stop_errors);
  }
  return completed;
}

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.target_inspect")
StartStatus inspectHardwareStart(std::uint32_t epoch) {
  if (epoch == 0U) {
    return StartStatus::kInvalidEpoch;
  }
  if (g_hardware_prepared) {
    return StartStatus::kAlreadyRunning;
  }
  if (!triggersStopped() || resourcesBusy()) {
    return StartStatus::kResourceBusy;
  }
  return g_ring.snapshot().quiescent ? StartStatus::kOk
                                     : StartStatus::kNotQuiescent;
}

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.target_prepare")
StartStatus prepareHardware(std::uint32_t epoch) {
  const StartStatus readiness = inspectHardwareStart(epoch);
  if (readiness != StartStatus::kOk) {
    if (readiness == StartStatus::kResourceBusy) {
      saturatingIncrement(g_resource_conflicts);
    } else {
      saturatingIncrement(g_start_errors);
    }
    return readiness;
  }

  CCM_CCGR5 |= gpio_dma_route::kDmaGateMask;
  const PrimeResult prime = g_ring.prime(epoch);
  if (!prime.ok()) {
    saturatingIncrement(g_start_errors);
    return prime.status == OperationStatus::kInvalidEpoch
               ? StartStatus::kInvalidEpoch
               : StartStatus::kNotQuiescent;
  }

  disableInterrupts();
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    clearChannelState(converter);
  }
  configureDescriptors(prime);
  configurePriorities();

  g_epoch = epoch;
  g_current_generations = {prime.active_generation,
                           prime.active_generation};
  g_current_destinations = {prime.active_destination,
                            prime.active_destination};
  g_next_destinations = {prime.queued_destination,
                         prime.queued_destination};
  g_adc_etc_error_flags = 0U;
  g_adc_etc_error_interrupts = 0U;
  g_stale_interrupts = 0U;
  g_faulted = false;
  g_hardware_prepared = true;
  enableInterrupts();

  ADC1_GC |= ADC_GC_DMAEN;
  ADC2_GC |= ADC_GC_DMAEN;
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    *dmamuxRegister(converter) = dmamuxConfiguration(converter);
    DMA_SERQ = board::kAdcConverterConfigurations[converter].edma_channel;
  }
  barrier();

  if (!configuredHardwareValid()) {
    disableRequests();
    disableInterrupts();
    clearInterruptState();
    std::array<ChannelStopState, kConverterCount> stopped{};
    for (std::size_t converter = 0U; converter < kConverterCount;
         ++converter) {
      stopped[converter].generation = g_current_generations[converter];
      stopped[converter].destination =
          g_current_destinations[converter];
    }
    g_hardware_prepared = false;
    (void)g_ring.stop(stopped);
    g_epoch = 0U;
    g_faulted = true;
    saturatingIncrement(g_start_errors);
    return StartStatus::kHardwareError;
  }

  g_resource_conflicts = 0U;
  g_start_errors = 0U;
  g_stop_errors = 0U;
  return StartStatus::kOk;
}

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.target_stop")
StopReport stopHardwareAfterTriggers() {
  StopReport report{};
  if (!g_hardware_prepared) {
    return report;
  }
  if (!triggersStopped()) {
    saturatingIncrement(g_stop_errors);
    report.status = OperationStatus::kInvalidStopProgress;
    return report;
  }

  disableRequests();
  disableInterrupts();
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    if ((DMA_INT & channelMask(converter)) != 0U) {
      processDmaCompletion(converter);
    }
  }

  std::array<ChannelStopState, kConverterCount> stopped{};
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    stopped[converter].generation = g_current_generations[converter];
    stopped[converter].destination = g_current_destinations[converter];
    stopped[converter].minor_pairs = activeMinorPairs(converter);
    clearChannelState(converter);
  }
  clearInterruptState();
  g_hardware_prepared = false;
  restorePrimask(primask);

  report = g_ring.stop(stopped);
  (void)g_ring.serviceDiscarded();
  if (!report.ok()) {
    saturatingIncrement(g_stop_errors);
  }
  g_epoch = 0U;
  g_current_destinations = {kInvalidDestination, kInvalidDestination};
  g_next_destinations = {kInvalidDestination, kInvalidDestination};
  return report;
}

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.target_snapshot")
HardwareSnapshot hardwareSnapshot() {
  HardwareSnapshot value{};
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  value.ring = g_ring.snapshot();
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    HardwareChannelSnapshot &channel = value.channels[converter];
    const IMXRT_DMA_TCD_t &tcd = hardwareTcd(converter);
    channel.dmamux_chcfg = *dmamuxRegister(converter);
    channel.tcd_saddr = address32(tcd.SADDR);
    channel.tcd_daddr = address32(tcd.DADDR);
    channel.tcd_nbytes = tcd.NBYTES_MLNO;
    channel.tcd_dlastsga = tcd.DLASTSGA;
    channel.tcd_doff = tcd.DOFF;
    channel.tcd_attr = tcd.ATTR;
    channel.tcd_citer = tcd.CITER_ELINKNO;
    channel.tcd_biter = tcd.BITER_ELINKNO;
    channel.tcd_csr = tcd.CSR;
    channel.priority =
        static_cast<std::uint8_t>(priorityRegister(converter) & 0x0FU);
    channel.current_destination = g_current_destinations[converter];
    channel.next_destination = g_next_destinations[converter];
    channel.current_generation = g_current_generations[converter];
    value.adc_gc[converter] = adcGc(converter);
  }
  value.dma_erq = DMA_ERQ;
  value.dma_int = DMA_INT;
  value.dma_err = DMA_ERR;
  value.dma_hrs = DMA_HRS;
  value.adc_etc_done2_err_irq = ADC_ETC_DONE2_ERR_IRQ;
  value.adc_etc_error_flags = g_adc_etc_error_flags;
  value.adc_etc_error_interrupts = g_adc_etc_error_interrupts;
  value.resource_conflicts = g_resource_conflicts;
  value.start_errors = g_start_errors;
  value.stop_errors = g_stop_errors;
  value.stale_interrupts = g_stale_interrupts;
  value.hardware_prepared = g_hardware_prepared;
  value.faulted = g_faulted;
  restorePrimask(primask);
  return value;
}

}  // namespace

StartStatus TeensyAdcDmaCapture::inspectStart(std::uint32_t epoch) {
  return inspectHardwareStart(epoch);
}

StartStatus TeensyAdcDmaCapture::prepare(std::uint32_t epoch) {
  return prepareHardware(epoch);
}

bool TeensyAdcDmaCapture::stopAtBoundaryBeforeTriggers() {
  return waitForCompleteStopBoundary();
}

StopReport TeensyAdcDmaCapture::stopAfterTriggers() {
  return stopHardwareAfterTriggers();
}

std::size_t TeensyAdcDmaCapture::serviceOwnership() {
  return g_ring.serviceDiscarded();
}

AcquireResult TeensyAdcDmaCapture::acquireReady() {
  return g_ring.acquireReady();
}

OperationStatus TeensyAdcDmaCapture::release(
    const BufferHandle &handle) {
  return g_ring.release(handle);
}

Snapshot TeensyAdcDmaCapture::rawSnapshot() {
  Snapshot value = g_ring.snapshot();
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  value.resource_conflicts = g_resource_conflicts;
  value.start_errors = g_start_errors;
  value.stop_errors = g_stop_errors;
  value.stale_interrupts = g_stale_interrupts;
  value.hardware_prepared = g_hardware_prepared;
  value.faulted = g_faulted;
  restorePrimask(primask);
  return value;
}

HardwareSnapshot TeensyAdcDmaCapture::snapshot() {
  return hardwareSnapshot();
}

TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE(".flashmem.adc_dma.facade")
TeensyAdcDmaCapture &teensyAdcDmaCapture() { return g_facade; }

static_assert(sizeof(IMXRT_DMA_TCD_t) == board::kEdmaTcdBytes);
static_assert(alignof(DescriptorBank) == board::kCacheLineBytes);
static_assert(sizeof(DescriptorBank) == board::kAdcDmaDescriptorBytes);
static_assert(sizeof(g_adc_dma_buffers) == board::kAdcDmaRingBytes);
static_assert(sizeof(g_adc_dma_overflow_sink) ==
              board::kAdcDmaOverflowSinkBytes);
static_assert(protocol_v1::kAdcPairsPerFrame <=
              std::numeric_limits<std::int16_t>::max());
static_assert(kStopBoundaryTimeoutCycles == 6000000U);
static_assert(kStopBoundaryPollLimit == 2000000U);
static_assert(kStopBoundaryArmMinimumPairs == 759U);
static_assert(board::kAdcConverterConfigurations[0].edma_channel == 0U);
static_assert(board::kAdcConverterConfigurations[1].edma_channel == 1U);
static_assert(board::kAdcConverterConfigurations[0].dmamux_source ==
              DMAMUX_SOURCE_ADC1);
static_assert(board::kAdcConverterConfigurations[1].dmamux_source ==
              DMAMUX_SOURCE_ADC2);
static_assert(board::kAdcEdmaPriorities[0] == 0U);
static_assert(board::kAdcEdmaPriorities[1] == 1U);

}  // namespace teensy_daq::adc_capture

#undef TEENSY_DAQ_ADC_DMA_TARGET_COLD_CODE

#endif
