#include "digital_output_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstddef>
#include <cstdint>
#include <limits>

#include <core_pins.h>
#include <imxrt.h>

#include "board_config.h"
#include "gpio_dma_route_teensy.h"

#define THINGDAQ_OUTPUT_TARGET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::digital_output {
namespace {

constexpr std::uint16_t kTcdAttributes =
    DMA_TCD_ATTR_SSIZE(2U) | DMA_TCD_ATTR_DSIZE(2U);
constexpr std::uint16_t kTcdTerminalControl =
    DMA_TCD_CSR_DREQ | DMA_TCD_CSR_INTMAJOR;
constexpr std::uint16_t kTcdLinkedControl =
    DMA_TCD_CSR_ESG | DMA_TCD_CSR_INTMAJOR;
constexpr std::uint32_t kEdmaChannelMask =
    std::uint32_t{1U} << board::kAuxOutputEdmaChannel;
constexpr std::uint32_t kDmamuxConfiguration =
    DMAMUX_CHCFG_ENBL | board::kAuxOutputDmamuxSource;
constexpr bool kXbarUsesHighByte =
    (board::kAuxOutputXbarOutput & 1U) != 0U;
constexpr std::uint16_t kXbarStatus =
    kXbarUsesHighByte ? XBARA_CTRL_STS1 : XBARA_CTRL_STS0;
constexpr std::uint16_t kXbarEdge =
    kXbarUsesHighByte
        ? XBARA_CTRL_EDGE1(board::kAuxOutputXbarActiveEdge)
        : XBARA_CTRL_EDGE0(board::kAuxOutputXbarActiveEdge);
constexpr std::uint16_t kXbarInterruptEnable =
    kXbarUsesHighByte ? XBARA_CTRL_IEN1 : XBARA_CTRL_IEN0;
constexpr std::uint16_t kXbarDmaEnable =
    kXbarUsesHighByte ? XBARA_CTRL_DEN1 : XBARA_CTRL_DEN0;
constexpr std::uint16_t kXbarPeerStatus =
    kXbarUsesHighByte ? XBARA_CTRL_STS0 : XBARA_CTRL_STS1;
constexpr std::uint16_t kXbarConfigurationMask =
    kXbarStatus | kXbarEdge | kXbarInterruptEnable | kXbarDmaEnable;
constexpr std::uint16_t kXbarConfiguration =
    kXbarStatus | kXbarEdge | kXbarDmaEnable;
constexpr std::uint16_t kXbarSelectionMask =
    kXbarUsesHighByte ? 0xFF00U : 0x00FFU;
constexpr std::uint8_t kXbarSelectionShift =
    kXbarUsesHighByte ? 8U : 0U;

Engine *g_engine = nullptr;
DmaBlockStorage *g_dma_storage = nullptr;
DmaDescriptorStorage *g_descriptor_storage = nullptr;
std::uint8_t g_active_block = kInvalidBlockIndex;
std::uint32_t g_active_generation = 0U;
std::uint32_t g_active_lease = 0U;
std::uint32_t g_resource_conflicts = 0U;
std::uint32_t g_target_start_errors = 0U;
std::uint32_t g_target_stop_errors = 0U;
std::uint32_t g_stale_dma_completions = 0U;
bool g_pins_claimed = false;
bool g_hardware_prepared = false;
bool g_hardware_running = false;

template <typename Value>
void saturatingIncrement(Value &value) {
  if (value != std::numeric_limits<Value>::max()) {
    ++value;
  }
}

template <typename Value>
void saturatingAdd(Value &value, Value increment) {
  const Value maximum = std::numeric_limits<Value>::max();
  value = increment > maximum - value ? maximum : value + increment;
}

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

volatile std::uint16_t *xbarSelectRegister() {
  return &XBARA1_SEL0 + board::kAuxOutputXbarOutput / 2U;
}

volatile std::uint16_t *xbarControlRegister() {
  return &XBARA1_CTRL0 + board::kAuxOutputXbarOutput / 2U;
}

volatile std::uint32_t *dmamuxChannelRegister() {
  return &DMAMUX_CHCFG0 + board::kAuxOutputEdmaChannel;
}

IMXRT_DMA_TCD_t &hardwareTcd() {
  return IMXRT_DMA_TCD[board::kAuxOutputEdmaChannel];
}

IMXRT_DMA_TCD_t &descriptor(std::uint8_t block_index) {
  return *reinterpret_cast<IMXRT_DMA_TCD_t *>(
      g_descriptor_storage->descriptors[block_index].data());
}

std::uint32_t address32(const volatile void *address) {
  return static_cast<std::uint32_t>(
      reinterpret_cast<std::uintptr_t>(address));
}

std::int32_t descriptorAddress(std::uint8_t block_index) {
  if (block_index >= board::kAuxOutputDmaBlockCount) {
    return 0;
  }
  return static_cast<std::int32_t>(address32(&descriptor(block_index)));
}

bool pinMuxesAreGpio() {
  return CORE_PIN16_CONFIG == 5U && CORE_PIN17_CONFIG == 5U &&
         CORE_PIN18_CONFIG == 5U && CORE_PIN19_CONFIG == 5U &&
         CORE_PIN20_CONFIG == 5U && CORE_PIN21_CONFIG == 5U &&
         CORE_PIN22_CONFIG == 5U && CORE_PIN23_CONFIG == 5U;
}

bool pinsAreSafeInputs() {
  const std::uint32_t mask = board::kAuxOutputGpio1Mask;
  return pinMuxesAreGpio() && (GPIO1_GDIR & mask) == 0U &&
         (GPIO6_GDIR & mask) == 0U &&
         (IOMUXC_GPR_GPR26 & mask) == mask;
}

bool pinsHoldPhysicalState(std::uint32_t physical_state) {
  const std::uint32_t mask = board::kAuxOutputGpio1Mask;
  return pinMuxesAreGpio() && (GPIO1_GDIR & mask) == mask &&
         (IOMUXC_GPR_GPR26 & mask) == 0U &&
         (GPIO1_DR & mask) == (physical_state & mask);
}

bool selectedOutputBusy() {
  return (*xbarControlRegister() &
          (kXbarEdge | kXbarInterruptEnable | kXbarDmaEnable)) != 0U;
}

bool dmaRequestBusy() {
  return (DMA_ERQ & kEdmaChannelMask) != 0U ||
         (*dmamuxChannelRegister() & DMAMUX_CHCFG_ENBL) != 0U;
}

StartStatus inspectTargetArm() {
  if (g_pins_claimed || g_hardware_prepared || g_hardware_running) {
    return StartStatus::kAlreadyActive;
  }
  if (!pinsAreSafeInputs() || selectedOutputBusy() || dmaRequestBusy()) {
    return StartStatus::kNotReady;
  }
  return StartStatus::kOk;
}

void clearEdmaChannelState() {
  *dmamuxChannelRegister() = 0U;
  DMA_CERQ = board::kAuxOutputEdmaChannel;
  DMA_CERR = board::kAuxOutputEdmaChannel;
  DMA_CEEI = board::kAuxOutputEdmaChannel;
  DMA_CINT = board::kAuxOutputEdmaChannel;
  DMA_CDNE = board::kAuxOutputEdmaChannel;
}

void disableOutputRequests() {
  DMA_CERQ = board::kAuxOutputEdmaChannel;
  *dmamuxChannelRegister() = 0U;
  volatile std::uint16_t *const control = xbarControlRegister();
  const std::uint16_t preserved = static_cast<std::uint16_t>(
      *control & static_cast<std::uint16_t>(
                     ~(kXbarConfigurationMask | kXbarPeerStatus)));
  *control = static_cast<std::uint16_t>(preserved | kXbarStatus);
  barrier();
}

void stopSharedTriggerFirst() {
  IMXRT_PIT_CHANNELS[board::kGpioPitChannel].TCTRL = 0U;
  IMXRT_PIT_CHANNELS[protocol_v1::kAdcTriggerPairPitChannel].TCTRL =
      PIT_TCTRL_CHN;
  ADC_ETC_CTRL &= ~ADC_ETC_CTRL_TRIG_ENABLE(0xFFU);
  barrier();
}

bool claimPins(std::uint32_t logical_idle_state) {
  const std::uint32_t physical_idle =
      physicalMaskForLogicalState(logical_idle_state);
  const std::uint32_t mask = board::kAuxOutputGpio1Mask;
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  if (!pinsAreSafeInputs()) {
    restorePrimask(primask);
    return false;
  }
  GPIO1_DR_CLEAR = mask;
  GPIO1_DR_SET = physical_idle;
  IOMUXC_GPR_GPR26 &= ~mask;
  GPIO1_GDIR |= mask;
  barrier();
  const bool claimed = pinsHoldPhysicalState(physical_idle);
  if (!claimed) {
    GPIO1_GDIR &= ~mask;
    GPIO6_GDIR &= ~mask;
    IOMUXC_GPR_GPR26 |= mask;
    barrier();
  }
  restorePrimask(primask);
  g_pins_claimed = claimed;
  return claimed;
}

bool releasePins() {
  const std::uint32_t mask = board::kAuxOutputGpio1Mask;
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  GPIO1_GDIR &= ~mask;
  GPIO6_GDIR &= ~mask;
  IOMUXC_GPR_GPR26 |= mask;
  barrier();
  const bool released = pinsAreSafeInputs();
  restorePrimask(primask);
  g_pins_claimed = !released;
  return released;
}

void configureDescriptor(IMXRT_DMA_TCD_t &tcd,
                         const std::uint32_t *source,
                         std::size_t state_count) {
  tcd.SADDR = source;
  tcd.SOFF = static_cast<std::int16_t>(sizeof(std::uint32_t));
  tcd.ATTR = kTcdAttributes;
  tcd.NBYTES_MLNO = sizeof(std::uint32_t);
  tcd.SLAST = 0;
  tcd.DADDR = &GPIO1_DR_TOGGLE;
  tcd.DOFF = 0;
  tcd.CITER_ELINKNO = static_cast<std::uint16_t>(state_count);
  tcd.DLASTSGA = 0;
  tcd.CSR = kTcdTerminalControl;
  tcd.BITER_ELINKNO = static_cast<std::uint16_t>(state_count);
}

void copyDescriptorToHardware(const IMXRT_DMA_TCD_t &source) {
  IMXRT_DMA_TCD_t &destination = hardwareTcd();
  destination.SADDR = source.SADDR;
  destination.SOFF = source.SOFF;
  destination.ATTR = source.ATTR;
  destination.NBYTES_MLNO = source.NBYTES_MLNO;
  destination.SLAST = source.SLAST;
  destination.DADDR = source.DADDR;
  destination.DOFF = source.DOFF;
  destination.CITER_ELINKNO = source.CITER_ELINKNO;
  destination.DLASTSGA = source.DLASTSGA;
  destination.CSR = source.CSR;
  destination.BITER_ELINKNO = source.BITER_ELINKNO;
}

std::uint8_t earliestReadyBlock(const Snapshot &snapshot) {
  std::uint8_t selected = kInvalidBlockIndex;
  std::uint64_t sequence = std::numeric_limits<std::uint64_t>::max();
  for (std::size_t index = 0U; index < snapshot.blocks.size(); ++index) {
    if (snapshot.blocks[index].state == BlockState::kDmaReady &&
        snapshot.blocks[index].sequence < sequence) {
      selected = static_cast<std::uint8_t>(index);
      sequence = snapshot.blocks[index].sequence;
    }
  }
  return selected;
}

bool liveTcdMatchesBlock(std::uint8_t block_index) {
  if (block_index >= board::kAuxOutputDmaBlockCount) {
    return false;
  }
  const std::uint32_t *const begin =
      g_dma_storage->blocks[block_index].data();
  const std::uintptr_t current =
      reinterpret_cast<std::uintptr_t>(hardwareTcd().SADDR);
  const std::uintptr_t first = reinterpret_cast<std::uintptr_t>(begin);
  const std::uintptr_t end =
      first + board::kAuxOutputDmaBlockBytes;
  return current >= first && current <= end &&
         hardwareTcd().DADDR == &GPIO1_DR_TOGGLE;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.link_tcd")
bool linkLiveTcdToNext(const Snapshot &snapshot) {
  const std::uint8_t next = earliestReadyBlock(snapshot);
  IMXRT_DMA_TCD_t &tcd = hardwareTcd();
  if (next == kInvalidBlockIndex) {
    tcd.DLASTSGA = 0;
    tcd.CSR = kTcdTerminalControl;
  } else {
    tcd.DLASTSGA = descriptorAddress(next);
    tcd.CSR = kTcdLinkedControl;
  }
  barrier();
  return (next == kInvalidBlockIndex && tcd.DLASTSGA == 0 &&
          tcd.CSR == kTcdTerminalControl) ||
         (next != kInvalidBlockIndex &&
          tcd.DLASTSGA == descriptorAddress(next) &&
          tcd.CSR == kTcdLinkedControl);
}

void publishActiveBlock(const Snapshot &snapshot) {
  g_active_block = snapshot.reading_block;
  if (g_active_block == kInvalidBlockIndex) {
    g_active_generation = 0U;
    g_active_lease = 0U;
    return;
  }
  g_active_generation =
      snapshot.blocks[g_active_block].upload_generation;
  g_active_lease = snapshot.blocks[g_active_block].lease;
}

std::size_t activeStatesEmitted() {
  const IMXRT_DMA_TCD_t &tcd = hardwareTcd();
  const std::uint16_t biter = tcd.BITER_ELINKNO;
  const std::uint16_t citer = tcd.CITER_ELINKNO;
  if (biter == 0U || citer > biter ||
      biter > board::kAuxOutputStatesPerBlock) {
    return 0U;
  }
  return static_cast<std::size_t>(biter - citer);
}

std::uint32_t observedLogicalLatch() {
  return logicalStateFromPhysicalMask(GPIO1_DR &
                                      board::kAuxOutputGpio1Mask);
}

bool targetResourcesFree() {
  return !selectedOutputBusy() && !dmaRequestBusy();
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.dma_isr")
void dmaMajorLoopIsr() {
  DMA_CINT = board::kAuxOutputEdmaChannel;
  if (!g_hardware_running || g_engine == nullptr) {
    saturatingIncrement(g_stale_dma_completions);
    return;
  }
  if ((DMA_ERR & kEdmaChannelMask) != 0U) {
    stopSharedTriggerFirst();
    disableOutputRequests();
    const std::size_t progress = activeStatesEmitted();
    (void)g_engine->recordDmaFault(progress, observedLogicalLatch());
    g_hardware_running = false;
    g_hardware_prepared = false;
    return;
  }

  // One linked successor can be the short final finite block. If it finishes
  // before this lower-priority ISR runs, consume its already-DONE TCD here so
  // clearing channel 3's interrupt never loses that terminal completion.
  for (std::size_t completion_count = 0U; completion_count < 2U;
       ++completion_count) {
    const OperationStatus completed = g_engine->onDmaBlockComplete(
        g_active_block, g_active_generation, g_active_lease);
    const Snapshot after = g_engine->snapshot();
    if (completed != OperationStatus::kOk || after.fault_latched) {
      stopSharedTriggerFirst();
      disableOutputRequests();
      g_hardware_running = false;
      g_hardware_prepared = false;
      return;
    }
    if (after.state == protocol_v2::OutputState::kHeld) {
      disableOutputRequests();
      NVIC_DISABLE_IRQ(IRQ_DMA_CH3);
      g_hardware_running = false;
      g_hardware_prepared = false;
      publishActiveBlock(after);
      return;
    }
    publishActiveBlock(after);
    if (!liveTcdMatchesBlock(g_active_block)) {
      break;
    }
    if (hardwareTcd().CITER_ELINKNO == 0U &&
        (hardwareTcd().CSR & DMA_TCD_CSR_DONE) != 0U) {
      DMA_CINT = board::kAuxOutputEdmaChannel;
      continue;
    }
    if (linkLiveTcdToNext(after)) {
      return;
    }
    break;
  }
  stopSharedTriggerFirst();
  disableOutputRequests();
  (void)g_engine->recordDmaFault(activeStatesEmitted(),
                                 observedLogicalLatch());
  g_hardware_running = false;
  g_hardware_prepared = false;
}

bool configurePreparedHardware(const Snapshot &snapshot) {
  if (snapshot.reading_block == kInvalidBlockIndex ||
      !g_pins_claimed || !targetResourcesFree()) {
    return false;
  }
  gpio_dma_route::enableClockGates();
  clearEdmaChannelState();
  copyDescriptorToHardware(descriptor(snapshot.reading_block));
  if (!liveTcdMatchesBlock(snapshot.reading_block) ||
      !linkLiveTcdToNext(snapshot)) {
    return false;
  }

  DMA_DCHPRI3 = static_cast<std::uint8_t>(
      DMA_DCHPRI_ECP |
      DMA_DCHPRI_CHPRI(board::kAuxOutputEdmaPriority));
  volatile std::uint16_t *const selection = xbarSelectRegister();
  *selection = static_cast<std::uint16_t>(
      (*selection & static_cast<std::uint16_t>(~kXbarSelectionMask)) |
      (static_cast<std::uint16_t>(board::kAuxOutputXbarInput)
       << kXbarSelectionShift));
  volatile std::uint16_t *const control = xbarControlRegister();
  const std::uint16_t preserved = static_cast<std::uint16_t>(
      *control & static_cast<std::uint16_t>(
                     ~(kXbarConfigurationMask | kXbarPeerStatus)));
  *control = static_cast<std::uint16_t>(preserved | kXbarConfiguration);

  attachInterruptVector(IRQ_DMA_CH3, dmaMajorLoopIsr);
  NVIC_SET_PRIORITY(IRQ_DMA_CH3, board::kAuxOutputEdmaIrqPriority);
  NVIC_CLEAR_PENDING(IRQ_DMA_CH3);
  NVIC_ENABLE_IRQ(IRQ_DMA_CH3);
  *dmamuxChannelRegister() = kDmamuxConfiguration;
  DMA_SERQ = board::kAuxOutputEdmaChannel;
  publishActiveBlock(snapshot);
  barrier();
  return (*dmamuxChannelRegister() == kDmamuxConfiguration) &&
         (DMA_ERQ & kEdmaChannelMask) != 0U &&
         ((*xbarSelectRegister() & kXbarSelectionMask) >>
              kXbarSelectionShift) == board::kAuxOutputXbarInput &&
         (*xbarControlRegister() & (kXbarEdge | kXbarDmaEnable)) ==
             (kXbarEdge | kXbarDmaEnable) &&
         (DMA_DCHPRI3 & 0x0FU) == board::kAuxOutputEdmaPriority;
}

class TeensyCacheMaintenance final : public CacheMaintenance {
 public:
  explicit constexpr TeensyCacheMaintenance(
      DmaDescriptorStorage &descriptor_storage)
      : descriptor_storage_(descriptor_storage) {}
  THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.cache_destructor")
  ~TeensyCacheMaintenance() override = default;

  THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.cache_flush")
  void flushBeforeDmaRead(const void *address, std::size_t bytes) override {
    arm_dcache_flush_delete(const_cast<void *>(address),
                            static_cast<std::uint32_t>(bytes));
  }

  THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.block_prepare")
  bool prepareBeforeDmaRead(std::uint8_t block_index,
                            const void *address, std::size_t bytes,
                            std::size_t state_count) override {
    if (block_index >= board::kAuxOutputDmaBlockCount ||
        state_count == 0U ||
        state_count > board::kAuxOutputStatesPerBlock) {
      return false;
    }
    g_descriptor_storage = &descriptor_storage_;
    flushBeforeDmaRead(address, bytes);
    IMXRT_DMA_TCD_t &tcd = descriptor(block_index);
    configureDescriptor(tcd, static_cast<const std::uint32_t *>(address),
                        state_count);
    arm_dcache_flush_delete(&tcd, sizeof(tcd));
    barrier();
    return true;
  }

 private:
  DmaDescriptorStorage &descriptor_storage_;
};

class TeensyCriticalSection final : public CriticalSection {
 public:
  THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.critical_destructor")
  ~TeensyCriticalSection() override = default;
  THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.critical_enter")
  std::uint32_t enter() override {
    const std::uint32_t primask = readPrimask();
    __disable_irq();
    return primask;
  }

  THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.critical_exit")
  void exit(std::uint32_t token) override { restorePrimask(token); }
};

}  // namespace

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.destructor")
TeensyOutput::~TeensyOutput() = default;

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.begin")
ProgramStatus TeensyOutput::begin(std::uint32_t generation,
                                  std::uint32_t repeat_count,
                                  std::uint32_t idle_state_mask) {
  return engine_.begin(generation, repeat_count, idle_state_mask);
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.append")
ProgramStatus TeensyOutput::append(std::uint32_t generation,
                                   const Segment &segment) {
  return engine_.append(generation, segment);
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.commit")
ProgramStatus TeensyOutput::commit(std::uint32_t generation,
                                   std::size_t expected_segment_count,
                                   std::uint32_t expected_checksum) {
  return engine_.commit(generation, expected_segment_count,
                        expected_checksum);
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.arm")
OperationStatus TeensyOutput::arm(std::uint32_t generation) {
  const StartStatus target = inspectTargetArm();
  if (target != StartStatus::kOk) {
    saturatingIncrement(g_resource_conflicts);
    return OperationStatus::kNotReady;
  }
  const OperationStatus armed = engine_.arm(generation);
  if (armed != OperationStatus::kOk) {
    engine_.rollbackArm();
    return armed;
  }
  const std::uint32_t idle = engine_.snapshot().program.idle_state_mask;
  if (!claimPins(idle)) {
    engine_.rollbackArm();
    saturatingIncrement(g_target_start_errors);
    return OperationStatus::kNotReady;
  }
  return OperationStatus::kOk;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.clear")
OperationStatus TeensyOutput::clear() {
  const Snapshot before = engine_.snapshot();
  if (before.state == protocol_v2::OutputState::kRunning ||
      before.prepared) {
    return engine_.clear(false);
  }
  disableOutputRequests();
  NVIC_DISABLE_IRQ(IRQ_DMA_CH3);
  clearEdmaChannelState();
  g_hardware_running = false;
  g_hardware_prepared = false;
  publishActiveBlock({});
  const OperationStatus cleared = engine_.clear(releasePins());
  if (cleared == OperationStatus::kOk) {
    g_resource_conflicts = 0U;
    g_target_start_errors = 0U;
    g_target_stop_errors = 0U;
    g_stale_dma_completions = 0U;
  }
  return cleared;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.participates")
bool TeensyOutput::participatesInNextStart() const {
  return engine_.participatesInNextStart();
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.inspect")
StartStatus TeensyOutput::inspectStart(std::uint32_t run_id) const {
  const StartStatus engine_status = engine_.inspectStart(run_id);
  if (engine_status != StartStatus::kOk) {
    return engine_status;
  }
  if (!g_pins_claimed || g_hardware_prepared || g_hardware_running ||
      !pinsHoldPhysicalState(physicalMaskForLogicalState(
          engine_.snapshot().program.idle_state_mask)) ||
      !targetResourcesFree()) {
    return StartStatus::kNotReady;
  }
  return StartStatus::kOk;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.prepare_start")
StartStatus TeensyOutput::prepareStart(std::uint32_t run_id,
                                       std::uint64_t epoch_ticks) {
  const StartStatus readiness = inspectStart(run_id);
  if (readiness != StartStatus::kOk) {
    saturatingIncrement(g_target_start_errors);
    return readiness;
  }
  const StartStatus prepared = engine_.prepareStart(run_id, epoch_ticks);
  if (prepared != StartStatus::kOk) {
    saturatingIncrement(g_target_start_errors);
    return prepared;
  }
  const Snapshot snapshot_value = engine_.snapshot();
  if (!configurePreparedHardware(snapshot_value)) {
    disableOutputRequests();
    NVIC_DISABLE_IRQ(IRQ_DMA_CH3);
    clearEdmaChannelState();
    engine_.rollbackPreparedStart();
    publishActiveBlock({});
    saturatingIncrement(g_target_start_errors);
    return StartStatus::kNotReady;
  }
  g_hardware_prepared = true;
  return StartStatus::kOk;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.start")
void TeensyOutput::commitCommonStart() {
  if (!g_hardware_prepared) {
    return;
  }
  engine_.commitCommonStart();
  if (engine_.snapshot().state == protocol_v2::OutputState::kRunning) {
    g_hardware_running = true;
  }
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.rollback")
void TeensyOutput::rollbackPreparedStart() {
  disableOutputRequests();
  NVIC_DISABLE_IRQ(IRQ_DMA_CH3);
  clearEdmaChannelState();
  g_hardware_running = false;
  g_hardware_prepared = false;
  publishActiveBlock({});
  engine_.rollbackPreparedStart();
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.stop")
StopReport TeensyOutput::stopAfterTriggers() {
  // The acquisition controller normally reaches this method after stopping
  // PIT0/PIT1/ADC_ETC. Reassert that ordering locally for fault containment.
  stopSharedTriggerFirst();
  const std::uint32_t primask = readPrimask();
  __disable_irq();
  disableOutputRequests();
  NVIC_DISABLE_IRQ(IRQ_DMA_CH3);
  if ((DMA_INT & kEdmaChannelMask) != 0U && g_hardware_running &&
      g_active_block != kInvalidBlockIndex) {
    DMA_CINT = board::kAuxOutputEdmaChannel;
    (void)engine_.onDmaBlockComplete(
        g_active_block, g_active_generation, g_active_lease);
    publishActiveBlock(engine_.snapshot());
  }
  const Snapshot stopped_snapshot = engine_.snapshot();
  const std::size_t progress =
      stopped_snapshot.reading_block == kInvalidBlockIndex
          ? 0U
          : activeStatesEmitted();
  const std::uint32_t latch = observedLogicalLatch();
  clearEdmaChannelState();
  g_hardware_running = false;
  g_hardware_prepared = false;
  publishActiveBlock({});
  restorePrimask(primask);
  StopReport report = engine_.stopAfterTriggersAtProgress(progress, latch);
  if (!report.ok()) {
    saturatingIncrement(g_target_stop_errors);
  }
  report.held_state_mask = latch;
  report.dma_quiesced = (DMA_ERQ & kEdmaChannelMask) == 0U &&
                        (*dmamuxChannelRegister() & DMAMUX_CHCFG_ENBL) == 0U;
  return report;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.service")
ServiceReport TeensyOutput::service(std::size_t block_limit) {
  return engine_.service(block_limit);
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.snapshot")
Snapshot TeensyOutput::snapshot() const {
  const bool progressing = g_hardware_running &&
                           g_active_block != kInvalidBlockIndex &&
                           liveTcdMatchesBlock(g_active_block);
  Snapshot value = progressing
                       ? engine_.snapshotAtDmaProgress(
                             activeStatesEmitted(), observedLogicalLatch())
                       : engine_.snapshot();
  saturatingAdd(value.telemetry.resource_conflicts, g_resource_conflicts);
  saturatingAdd(value.telemetry.start_errors, g_target_start_errors);
  saturatingAdd(value.telemetry.stop_errors, g_target_stop_errors);
  saturatingAdd(value.telemetry.stale_completions,
                g_stale_dma_completions);
  return value;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.faulted")
bool TeensyOutput::faulted() const { return engine_.faulted(); }

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.hardware_snapshot")
HardwareSnapshot TeensyOutput::hardwareSnapshot() const {
  HardwareSnapshot value{};
  value.engine = snapshot();
  value.gpr26 = IOMUXC_GPR_GPR26;
  value.gpio1_dr = GPIO1_DR;
  value.gpio1_gdir = GPIO1_GDIR;
  value.gpio6_gdir = GPIO6_GDIR;
  value.dmamux_chcfg = *dmamuxChannelRegister();
  value.dma_erq = DMA_ERQ;
  value.dma_err = DMA_ERR;
  value.xbar_selection = *xbarSelectRegister();
  value.xbar_control = *xbarControlRegister();
  value.tcd_citer = hardwareTcd().CITER_ELINKNO;
  value.tcd_biter = hardwareTcd().BITER_ELINKNO;
  value.tcd_csr = hardwareTcd().CSR;
  value.edma_priority = static_cast<std::uint8_t>(DMA_DCHPRI3 & 0x0FU);
  value.resource_conflicts = g_resource_conflicts;
  value.target_start_errors = g_target_start_errors;
  value.target_stop_errors = g_target_stop_errors;
  value.stale_dma_completions = g_stale_dma_completions;
  value.pins_claimed = g_pins_claimed;
  value.hardware_prepared = g_hardware_prepared;
  value.hardware_running = g_hardware_running;
  return value;
}

THINGDAQ_OUTPUT_TARGET_COLD_CODE(".flashmem.output.factory")
TeensyOutput &teensyOutput(ProgramStorage &program_storage,
                           DmaBlockStorage &dma_storage,
                           DmaDescriptorStorage &descriptor_storage) {
  static ProgramStore program{program_storage};
  static TeensyCacheMaintenance cache{descriptor_storage};
  static TeensyCriticalSection critical{};
  static Engine engine{program, dma_storage, cache, critical};
  static TeensyOutput output{engine};
  g_engine = &engine;
  g_dma_storage = &dma_storage;
  g_descriptor_storage = &descriptor_storage;
  return output;
}

static_assert(sizeof(IMXRT_DMA_TCD_t) == board::kEdmaTcdBytes);
static_assert(alignof(DmaDescriptorStorage) == board::kCacheLineBytes);
static_assert(board::kAuxOutputEdmaChannel == 3U);
static_assert(board::kAuxOutputEdmaPriority == 1U);
static_assert(board::kAuxOutputXbarOutput == 1U);
static_assert(kXbarUsesHighByte);
static_assert(board::kAuxOutputGpio1Mask == 0x0FC30000U);
static_assert(physicalMaskForLogicalState(0xFFU) ==
              board::kAuxOutputGpio1Mask);
static_assert(board::kAuxOutputStatesPerBlock <=
              std::numeric_limits<std::uint16_t>::max());

}  // namespace thingdaq::digital_output

#endif

#undef THINGDAQ_OUTPUT_TARGET_COLD_CODE
