#include "gpio_raw_capture_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>

#include <core_pins.h>
#include <imxrt.h>

#include "board_config.h"
#include "gpio_dma_route_teensy.h"

#define TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace teensy_daq::gpio_capture {

struct alignas(board::kCacheLineBytes) DescriptorBank {
  std::array<IMXRT_DMA_TCD_t, board::kGpioRawDmaDescriptorCount>
      descriptors{};
};

RawBufferStorage g_gpio_raw_dma_buffers
    __attribute__((section(".dmabuffers"), used));
RawOverflowSink g_gpio_raw_dma_overflow_sink
    __attribute__((section(".dmabuffers"), used));
DescriptorBank g_gpio_raw_dma_descriptors
    __attribute__((section(".dmabuffers"), used));

namespace {

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.allocations")
void *retainDmaAllocations() {
  __asm__ volatile(""
                   :
                   : "r"(&g_gpio_raw_dma_buffers),
                     "r"(&g_gpio_raw_dma_overflow_sink),
                     "r"(&g_gpio_raw_dma_descriptors)
                   : "memory");
  return &g_gpio_raw_dma_buffers;
}

void *volatile g_dma_allocation_link_anchor = retainDmaAllocations();

constexpr std::uint16_t kTcdAttributes =
    DMA_TCD_ATTR_SSIZE(2U) | DMA_TCD_ATTR_DSIZE(2U);
constexpr std::uint16_t kTcdControl =
    DMA_TCD_CSR_ESG | DMA_TCD_CSR_INTMAJOR;
constexpr std::uint32_t kProductionPitLoad =
    protocol_v1::kGpioClockPitHz /
        protocol_v1::kGpioClockProductionRateHz -
    1U;
constexpr std::uint32_t kStopBoundaryTimeoutCycles =
    protocol_v1::kGpioClockDwtHz / 100U;

std::uint32_t readPrimask() {
  std::uint32_t value = 0U;
  __asm__ volatile("mrs %0, primask" : "=r"(value) : : "memory");
  return value;
}

class TeensyCacheMaintenance final : public CacheMaintenance {
 public:
  TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.cache_discard")
  void discardBeforeDmaWrite(void *address, std::size_t bytes) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(bytes));
  }

  TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.cache_invalidate")
  void invalidateBeforeCpuRead(void *address, std::size_t bytes) override {
    arm_dcache_delete(address, static_cast<std::uint32_t>(bytes));
  }
};

class TeensyCriticalSection final : public CriticalSection {
 public:
  TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.critical_enter")
  std::uint32_t enter() override {
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    return primask;
  }

  TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.critical_exit")
  void exit(std::uint32_t token) override {
    if ((token & 1U) == 0U) {
      __enable_irq();
    }
  }
};

TeensyCacheMaintenance g_cache{};
TeensyCriticalSection g_critical{};
RawCaptureRing g_ring{g_gpio_raw_dma_buffers, g_gpio_raw_dma_overflow_sink,
                      g_cache, g_critical};
TeensyRawCapture g_facade{};
bool g_hardware_running = false;
bool g_hardware_prepared = false;
bool g_faulted = false;
std::uint32_t g_resource_conflicts = 0U;
std::uint32_t g_start_errors = 0U;
std::uint32_t g_stop_errors = 0U;
std::uint32_t g_stale_dma_completions = 0U;

void saturatingIncrement(std::uint32_t &value) {
  if (value != std::numeric_limits<std::uint32_t>::max()) {
    ++value;
  }
}

std::uint32_t address32(const volatile void *address) {
  return static_cast<std::uint32_t>(
      reinterpret_cast<std::uintptr_t>(address));
}

std::int32_t descriptorAddress(std::uint8_t destination) {
  if (destination > kOverflowDestination) {
    return 0;
  }
  return static_cast<std::int32_t>(address32(
      &g_gpio_raw_dma_descriptors.descriptors[destination]));
}

void forceSafeInputs() {
  selectStandardGpioInputs(IOMUXC_GPR_GPR27, GPIO2_GDIR);
  gpio_dma_route::barrier();
}

bool resourcesBusy() {
  const IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  return pit.TCTRL != 0U || gpio_dma_route::edmaRequestBusy() ||
         gpio_dma_route::selectedOutputBusy();
}

void configureDescriptor(IMXRT_DMA_TCD_t &descriptor,
                         std::uint8_t destination) {
  descriptor.SADDR = &GPIO2_PSR;
  descriptor.SOFF = 0;
  descriptor.ATTR = kTcdAttributes;
  descriptor.NBYTES_MLNO = sizeof(std::uint32_t);
  descriptor.SLAST = 0;
  descriptor.DADDR = g_ring.destinationWords(destination);
  descriptor.DOFF =
      destination == kOverflowDestination
          ? 0
          : static_cast<std::int16_t>(sizeof(std::uint32_t));
  descriptor.CITER_ELINKNO = static_cast<std::uint16_t>(
      protocol_v1::kGpioSamplesPerFrame);
  descriptor.DLASTSGA = descriptorAddress(kOverflowDestination);
  descriptor.CSR = kTcdControl;
  descriptor.BITER_ELINKNO = static_cast<std::uint16_t>(
      protocol_v1::kGpioSamplesPerFrame);
}

void copyDescriptorToHardware(const IMXRT_DMA_TCD_t &source,
                              std::int32_t next_descriptor) {
  IMXRT_DMA_TCD_t &destination = gpio_dma_route::edmaTcd();
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
  for (std::uint8_t destination = 0U;
       destination <= kOverflowDestination; ++destination) {
    configureDescriptor(
        g_gpio_raw_dma_descriptors.descriptors[destination], destination);
  }
  copyDescriptorToHardware(
      g_gpio_raw_dma_descriptors.descriptors[prime.active_destination],
      descriptorAddress(prime.queued_destination));
  arm_dcache_flush_delete(&g_gpio_raw_dma_descriptors,
                          sizeof(g_gpio_raw_dma_descriptors));
}

bool hardwareDestinationMatches(std::uint8_t destination) {
  const std::uint32_t *const begin = g_ring.destinationWords(destination);
  if (begin == nullptr) {
    return false;
  }
  const std::uintptr_t current =
      reinterpret_cast<std::uintptr_t>(gpio_dma_route::edmaTcd().DADDR);
  const std::uintptr_t first = reinterpret_cast<std::uintptr_t>(begin);
  const std::uintptr_t end =
      first + (destination == kOverflowDestination
                   ? board::kGpioRawDmaOverflowSinkBytes
                   : board::kGpioRawDmaBufferBytes);
  return current >= first && current <= end;
}

void disableHardware() {
  IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  pit.TCTRL = 0U;
  gpio_dma_route::disableEdmaRequest();
  gpio_dma_route::disableXbarRequest();
  gpio_dma_route::barrier();
}

void faultFromIsr() {
  g_ring.recordHardwareError();
  disableHardware();
  forceSafeInputs();
  g_faulted = true;
  g_hardware_running = false;
}

void dmaMajorLoopIsr() {
  DMA_CINT = board::kGpioEdmaChannel;
  if (!g_hardware_running) {
    saturatingIncrement(g_stale_dma_completions);
    return;
  }
  if ((DMA_ERR & gpio_dma_route::kEdmaChannelMask) != 0U) {
    faultFromIsr();
    return;
  }

  const MajorLoopResult completed = g_ring.onMajorLoopComplete();
  if (!completed.ok() ||
      !hardwareDestinationMatches(completed.active_destination)) {
    faultFromIsr();
    return;
  }
  const std::int32_t next =
      descriptorAddress(completed.queued_destination);
  if (next == 0) {
    faultFromIsr();
    return;
  }
  gpio_dma_route::edmaTcd().DLASTSGA = next;
  gpio_dma_route::barrier();
}

std::uint32_t activeSamples() {
  const IMXRT_DMA_TCD_t &tcd = gpio_dma_route::edmaTcd();
  const std::uint16_t biter = tcd.BITER_ELINKNO;
  const std::uint16_t citer = tcd.CITER_ELINKNO;
  if (biter != protocol_v1::kGpioSamplesPerFrame || citer > biter) {
    g_ring.recordHardwareError();
    return 0U;
  }
  return static_cast<std::uint32_t>(biter - citer);
}

bool waitForCompleteStopBoundary() {
  if (!g_hardware_running || g_faulted) {
    return false;
  }
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
  IMXRT_DMA_TCD_t &tcd = gpio_dma_route::edmaTcd();
  tcd.CSR = static_cast<std::uint16_t>(tcd.CSR | DMA_TCD_CSR_DREQ);
  gpio_dma_route::barrier();

  const std::uint32_t started = ARM_DWT_CYCCNT;
  while ((DMA_ERQ & gpio_dma_route::kEdmaChannelMask) != 0U &&
         ARM_DWT_CYCCNT - started < kStopBoundaryTimeoutCycles) {
  }
  return (DMA_ERQ & gpio_dma_route::kEdmaChannelMask) == 0U;
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.target_start")
StartStatus inspectHardwareStart() {
  if (g_hardware_prepared || g_hardware_running) {
    return StartStatus::kAlreadyRunning;
  }
  if (resourcesBusy()) {
    return StartStatus::kResourceBusy;
  }
  return g_ring.snapshot().quiescent ? StartStatus::kOk
                                     : StartStatus::kNotQuiescent;
}

bool preparedHardwareValid() {
  const IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  const IMXRT_DMA_TCD_t &tcd = gpio_dma_route::edmaTcd();
  return pit.LDVAL == kProductionPitLoad && pit.TCTRL == 0U &&
         gpio_dma_route::selectedOutputBusy() &&
         gpio_dma_route::edmaRequestBusy() &&
         *gpio_dma_route::dmamuxChannelRegister() ==
             gpio_dma_route::kDmamuxConfiguration &&
         tcd.SADDR == &GPIO2_PSR && tcd.ATTR == kTcdAttributes &&
         tcd.NBYTES_MLNO == sizeof(std::uint32_t) &&
         tcd.CITER_ELINKNO == protocol_v1::kGpioSamplesPerFrame &&
         tcd.BITER_ELINKNO == protocol_v1::kGpioSamplesPerFrame &&
         tcd.CSR == kTcdControl &&
         hardwareDestinationMatches(g_ring.snapshot().active_destination) &&
         (GPIO2_GDIR & board::kGpio2PsrCaptureMask) == 0U &&
         (IOMUXC_GPR_GPR27 & board::kGpio7ToGpio2Gpr27ClearMask) == 0U;
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.target_prepare")
StartStatus prepareHardware() {
  const StartStatus readiness = inspectHardwareStart();
  if (readiness != StartStatus::kOk) {
    if (readiness == StartStatus::kResourceBusy) {
      saturatingIncrement(g_resource_conflicts);
    } else {
      saturatingIncrement(g_start_errors);
    }
    return readiness;
  }
  gpio_dma_route::enableClockGates();

  const PrimeResult prime = g_ring.prime();
  if (!prime.ok()) {
    forceSafeInputs();
    saturatingIncrement(g_start_errors);
    return prime.status == OperationStatus::kAlreadyRunning
               ? StartStatus::kAlreadyRunning
               : StartStatus::kNotQuiescent;
  }

  gpio_dma_route::clearEdmaChannelState();
  configureDescriptors(prime);
  gpio_dma_route::configureEdmaPriority();

  gpio_dma_route::configureStoppedPit(kProductionPitLoad);
  gpio_dma_route::configureXbarRequest();
  forceSafeInputs();

  attachInterruptVector(IRQ_DMA_CH2, dmaMajorLoopIsr);
  NVIC_SET_PRIORITY(IRQ_DMA_CH2, board::kGpioEdmaIrqPriority);
  NVIC_CLEAR_PENDING(IRQ_DMA_CH2);
  NVIC_ENABLE_IRQ(IRQ_DMA_CH2);
  gpio_dma_route::enableEdmaRequest();
  g_hardware_prepared = true;
  g_hardware_running = true;
  gpio_dma_route::barrier();

  if (!preparedHardwareValid()) {
    disableHardware();
    NVIC_DISABLE_IRQ(IRQ_DMA_CH2);
    DMA_CINT = board::kGpioEdmaChannel;
    DMA_CERR = board::kGpioEdmaChannel;
    DMA_CDNE = board::kGpioEdmaChannel;
    forceSafeInputs();
    g_hardware_running = false;
    g_hardware_prepared = false;
    (void)g_ring.stop(0U);
    g_faulted = true;
    saturatingIncrement(g_start_errors);
    return StartStatus::kHardwareError;
  }

  g_resource_conflicts = 0U;
  g_start_errors = 0U;
  g_stop_errors = 0U;
  g_stale_dma_completions = 0U;
  g_faulted = false;
  return StartStatus::kOk;
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.target_start")
StartStatus startHardware() {
  const StartStatus prepared = prepareHardware();
  if (prepared != StartStatus::kOk) {
    return prepared;
  }
  IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL = PIT_TCTRL_TEN;
  gpio_dma_route::barrier();
  if ((IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL & PIT_TCTRL_TEN) ==
      0U) {
    disableHardware();
    NVIC_DISABLE_IRQ(IRQ_DMA_CH2);
    g_hardware_running = false;
    g_hardware_prepared = false;
    (void)g_ring.stop(0U);
    forceSafeInputs();
    g_faulted = true;
    saturatingIncrement(g_start_errors);
    return StartStatus::kHardwareError;
  }
  return StartStatus::kOk;
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.target_stop")
StopReport stopHardwareImpl(bool preserve_complete_boundary) {
  IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  const bool source_was_stopped = (pit.TCTRL & PIT_TCTRL_TEN) == 0U;
  const bool boundary_stop_requested =
      preserve_complete_boundary && g_hardware_running && !g_faulted;
  const bool boundary_stop_completed =
      boundary_stop_requested && waitForCompleteStopBoundary();
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  disableHardware();
  NVIC_DISABLE_IRQ(IRQ_DMA_CH2);

  Snapshot before = g_ring.snapshot();
  if (before.running &&
      (DMA_INT & gpio_dma_route::kEdmaChannelMask) != 0U) {
    DMA_CINT = board::kGpioEdmaChannel;
    const MajorLoopResult pending = g_ring.onMajorLoopComplete();
    if (!pending.ok()) {
      g_ring.recordHardwareError();
    }
  }
  const std::uint32_t partial_samples =
      g_ring.snapshot().running ? activeSamples() : 0U;
  if (boundary_stop_requested &&
      (!boundary_stop_completed || partial_samples != 0U)) {
    saturatingIncrement(g_stop_errors);
  }
  DMA_CINT = board::kGpioEdmaChannel;
  DMA_CERR = board::kGpioEdmaChannel;
  DMA_CDNE = board::kGpioEdmaChannel;
  forceSafeInputs();
  g_hardware_running = false;
  g_hardware_prepared = false;
  if ((primask & 1U) == 0U) {
    __enable_irq();
  }

  StopReport report = g_ring.stop(partial_samples);
  if (report.status == OperationStatus::kNotRunning && !before.running) {
    report.ready_buffers_to_drain = before.ready_depth;
    report.packing_buffers_to_release = before.packing_depth;
  }
  if (report.status != OperationStatus::kOk &&
      report.status != OperationStatus::kNotRunning) {
    saturatingIncrement(g_stop_errors);
  }
  if (!preserve_complete_boundary && !source_was_stopped) {
    saturatingIncrement(g_stop_errors);
    if (report.status == OperationStatus::kOk) {
      report.status = OperationStatus::kInvalidCompletion;
    }
  }
  return report;
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.target_stop")
StopReport stopHardware() { return stopHardwareImpl(true); }

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(
    ".flashmem.gpio_raw.target_stop_after_triggers")
StopReport stopHardwareAfterTriggers() {
  return stopHardwareImpl(false);
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.target_snapshot")
HardwareSnapshot hardwareSnapshot() {
  HardwareSnapshot value{};
  value.ring = g_ring.snapshot();
  value.ring.resource_conflicts = g_resource_conflicts;
  value.ring.start_errors = g_start_errors;
  value.ring.stop_errors = g_stop_errors;
  value.ring.stale_dma_completions = g_stale_dma_completions;
  value.ring.hardware_prepared = g_hardware_prepared;
  value.ring.faulted = g_faulted;
  value.gpr27 = IOMUXC_GPR_GPR27;
  value.gpio2_gdir = GPIO2_GDIR;
  value.gpio2_psr = GPIO2_PSR;
  const IMXRT_PIT_CHANNEL_t &pit =
      IMXRT_PIT_CHANNELS[board::kGpioPitChannel];
  value.pit_ldval = pit.LDVAL;
  value.pit_tctrl = pit.TCTRL;
  value.dmamux_chcfg = *gpio_dma_route::dmamuxChannelRegister();
  value.dma_erq = DMA_ERQ;
  value.dma_err = DMA_ERR;
  const IMXRT_DMA_TCD_t &tcd = gpio_dma_route::edmaTcd();
  value.tcd_citer = tcd.CITER_ELINKNO;
  value.tcd_biter = tcd.BITER_ELINKNO;
  value.tcd_csr = tcd.CSR;
  value.edma_priority = gpio_dma_route::edmaPriority();
  value.resource_conflicts = g_resource_conflicts;
  value.start_errors = g_start_errors;
  value.stop_errors = g_stop_errors;
  value.stale_dma_completions = g_stale_dma_completions;
  value.hardware_running = g_hardware_running;
  value.faulted = g_faulted;
  return value;
}

}  // namespace

StartStatus TeensyRawCapture::inspectStart() { return inspectHardwareStart(); }

StartStatus TeensyRawCapture::prepare() { return prepareHardware(); }

StartStatus TeensyRawCapture::start() { return startHardware(); }

StopReport TeensyRawCapture::stopAfterTriggers() {
  return stopHardwareAfterTriggers();
}

StopReport TeensyRawCapture::stop() { return stopHardware(); }

AcquireResult TeensyRawCapture::acquireReady() {
  return g_ring.acquireReady();
}

OperationStatus TeensyRawCapture::release(const BufferHandle &handle) {
  return g_ring.release(handle);
}

Snapshot TeensyRawCapture::rawSnapshot() {
  Snapshot value = g_ring.snapshot();
  value.resource_conflicts = g_resource_conflicts;
  value.start_errors = g_start_errors;
  value.stop_errors = g_stop_errors;
  value.stale_dma_completions = g_stale_dma_completions;
  value.hardware_prepared = g_hardware_prepared;
  value.faulted = g_faulted;
  return value;
}

HardwareSnapshot TeensyRawCapture::snapshot() {
  return hardwareSnapshot();
}

TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE(".flashmem.gpio_raw.facade")
TeensyRawCapture &teensyRawCapture() {
  return g_facade;
}

static_assert(sizeof(IMXRT_DMA_TCD_t) == board::kEdmaTcdBytes);
static_assert(alignof(DescriptorBank) == board::kCacheLineBytes);
static_assert(sizeof(DescriptorBank) == board::kGpioRawDmaDescriptorBytes);
static_assert(sizeof(g_gpio_raw_dma_buffers) == board::kGpioRawDmaRingBytes);
static_assert(sizeof(g_gpio_raw_dma_overflow_sink) ==
              board::kGpioRawDmaOverflowSinkBytes);
static_assert(protocol_v1::kGpioSamplesPerFrame <=
              std::numeric_limits<std::int16_t>::max());
static_assert(kProductionPitLoad == 5U);
static_assert(kStopBoundaryTimeoutCycles == 6000000U);
static_assert(board::kGpioEdmaChannel == 2U);
static_assert(board::kGpioEdmaPriority == 0U);

}  // namespace teensy_daq::gpio_capture

#undef TEENSY_DAQ_GPIO_RAW_TARGET_COLD_CODE

#endif
