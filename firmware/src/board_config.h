#pragma once

#include <cstddef>
#include <cstdint>

#if defined(ARDUINO) &&                                                   \
    (!defined(ARDUINO_TEENSY40) || !defined(__IMXRT1062__))
#error "ThingDAQ board resources require Teensy 4.0 / i.MX RT1062"
#endif

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <core_pins.h>
#include <imxrt.h>
#endif

#include "generated/protocol_constants.h"
#include "generated/protocol_v2_constants.h"
#include "protocol.h"

namespace thingdaq::board {

enum class ResourceOwner : std::uint8_t {
  kControlPlane,
  kAcquisitionClock,
  kAdcCapture,
  kAdc0Capture,
  kAdc1Capture,
  kAdcPacker,
  kGpioCapture,
  kAuxGpioCapture,
  kGpioJoin,
  kGpioPacker,
  kPacketizer,
  kUsbTransport,
  kChecksumBenchmark,
};

enum class MemoryRegion : std::uint8_t {
  kDtcmRam1,
  kOcramRam2Dma,
};

enum class MemoryUse : std::uint8_t {
  kCommandParser,
  kUsbRxScratch,
  kCommandQueue,
  kResponseQueue,
  kPacketBufferStorage,
  kPacketBufferReserveStorage,
  kPacketPipelineState,
  kAdcDmaRing,
  kAdcDmaOverflowSink,
  kAdcDmaDescriptors,
  kAdcPackerState,
  kGpioRawDmaRing,
  kPrimaryInputGpioRawDmaRing,
  kAuxGpioRawDmaRing,
  kGpioRawDmaOverflowSink,
  kPrimaryInputGpioRawDmaOverflowSink,
  kAuxGpioRawDmaOverflowSink,
  kGpioRawDmaDescriptors,
  kAuxGpioRawDmaDescriptors,
  kGpioPairedJoinState,
  kGpioPackedRing,
  kGpioPackerState,
  kGpioClockDiagnosticSink,
  kChecksumBenchmarkDtcmBuffer,
  kChecksumBenchmarkOcramBuffer,
};

enum class InterruptUse : std::uint8_t {
  kAdc0DmaCompletion,
  kAdc1DmaCompletion,
  kAdcEtcError,
  kGpioDmaCompletion,
  kAuxGpioDmaCompletion,
};

struct PinAllocation {
  std::uint8_t pin;
  ResourceOwner owner;
};

struct GpioPinMapping {
  std::uint8_t teensy_pin;
  std::uint8_t gpio2_bit;
};

struct GpioBitAllocation {
  std::uint8_t gpio_port;
  std::uint8_t gpio_bit;
  ResourceOwner owner;
};

enum class AdcInputPad : std::uint8_t {
  kGpioAdB1_02 = 2U,
  kGpioAdB1_03 = 3U,
};

// The complete route for one logical converter. The Teensy ADC library calls
// NXP ADC1 "adc0" and NXP ADC2 "adc1"; keeping every identity in one tuple
// prevents a library call or first-free allocator from silently swapping them.
struct AdcConverterConfiguration {
  std::uint8_t logical_converter;
  std::uint8_t teensy_adc_library_module;
  std::uint8_t teensy_pin;
  AdcInputPad input_pad;
  std::uint8_t adc_peripheral;
  std::uint8_t input_channel;
  std::uint8_t adc_etc_trigger;
  std::uint8_t xbar_input;
  std::uint8_t xbar_output;
  std::uint8_t edma_channel;
  std::uint8_t dmamux_source;
  ResourceOwner owner;
};

struct PitAllocation {
  std::uint8_t channel;
  ResourceOwner owner;
};

struct XbarRoute {
  std::uint8_t input;
  std::uint8_t output;
  ResourceOwner owner;
};

struct AdcEtcAllocation {
  std::uint8_t trigger;
  std::uint8_t adc_peripheral;
  ResourceOwner owner;
};

struct EdmaAllocation {
  std::uint8_t channel;
  std::uint8_t dmamux_source;
  ResourceOwner owner;
};

struct MemoryAllocation {
  MemoryUse use;
  MemoryRegion region;
  std::size_t bytes;
  std::size_t alignment;
  ResourceOwner owner;
};

// A mode-specific logical view within one fixed physical allocation. Views
// let INPUT split the legacy raw ring and lease IDLE-only scratch without
// double-counting physical storage or hiding an overlap.
struct MemoryViewAllocation {
  MemoryUse use;
  MemoryUse storage;
  std::size_t offset;
  std::size_t bytes;
  ResourceOwner owner;
};

struct InterruptAllocation {
  InterruptUse use;
  std::uint8_t irq;
  std::uint8_t vector;
  std::uint8_t priority;
  ResourceOwner owner;
};

inline constexpr std::uint8_t kTeensy40DigitalPinCount = 40U;
inline constexpr std::uint8_t kPitChannelCount = 4U;
inline constexpr std::uint8_t kXbarInputCount = 132U;
inline constexpr std::uint8_t kXbarOutputCount = 132U;
inline constexpr std::uint8_t kAdcEtcTriggerCount = 8U;
inline constexpr std::uint8_t kAdcPeripheralCount = 2U;
inline constexpr std::uint8_t kLogicalAdcCount = 2U;
inline constexpr std::uint8_t kAdcInputChannelCount = 16U;
inline constexpr std::uint8_t kEdmaChannelCount = 32U;
inline constexpr std::uint8_t kDmamuxSourceCount = 128U;
inline constexpr std::uint8_t kGpioPortBitCount = 32U;
inline constexpr std::uint8_t kGpioPortCount = 5U;
inline constexpr std::uint8_t kArmExceptionVectorCount = 16U;
inline constexpr std::uint8_t kIrqDmaChannel0 = 0U;
inline constexpr std::uint8_t kIrqDmaChannel1 = 1U;
inline constexpr std::uint8_t kIrqDmaChannel2 = 2U;
inline constexpr std::uint8_t kIrqDmaChannel3 = 3U;
inline constexpr std::uint8_t kIrqAdcEtcError = 121U;
inline constexpr std::size_t kCacheLineBytes = 32U;
inline constexpr std::size_t kRam1BudgetBytes = 512U * 1024U;
inline constexpr std::size_t kRam2BudgetBytes = 512U * 1024U;

// Numeric identities come from the pinned core's imxrt.h. PIT1 fans out to
// both ADC_ETC outputs by design; XBAR outputs, rather than inputs, are unique.
inline constexpr std::uint8_t kXbarPitTrigger0Input = 56U;
inline constexpr std::uint8_t kXbarPitTrigger1Input = 57U;
inline constexpr std::uint8_t kXbarPitTrigger2Input = 58U;
inline constexpr std::uint8_t kXbarPitTrigger3Input = 59U;
inline constexpr std::uint8_t kXbarDmaRequest30Output = 0U;
inline constexpr std::uint8_t kXbarDmaRequest31Output = 1U;
inline constexpr std::uint8_t kXbarDmaRequest94Output = 2U;
inline constexpr std::uint8_t kXbarDmaRequest95Output = 3U;
inline constexpr std::uint8_t kXbarAdcEtcTrigger0Output = 103U;
inline constexpr std::uint8_t kXbarAdcEtcTrigger4Output = 107U;
inline constexpr std::uint8_t kDmamuxAdc1Source = 24U;
inline constexpr std::uint8_t kDmamuxXbar1Request0Source = 30U;
inline constexpr std::uint8_t kDmamuxXbar1Request1Source = 31U;
inline constexpr std::uint8_t kDmamuxXbar1Request2Source = 94U;
inline constexpr std::uint8_t kDmamuxXbar1Request3Source = 95U;
inline constexpr std::uint8_t kDmamuxAdc2Source = 88U;

// This is the sole authoritative ADC route table. Although both NXP ADC
// modules can sample both pads, logical ADC0 is permanently A0 through ADC1
// channel 7 and logical ADC1 is permanently A1 through ADC2 channel 8.
inline constexpr AdcConverterConfiguration kAdcConverterConfigurations[] = {
    {0U, 0U, 14U, AdcInputPad::kGpioAdB1_02, 1U, 7U, 0U,
     kXbarPitTrigger1Input, kXbarAdcEtcTrigger0Output, 0U,
     kDmamuxAdc1Source, ResourceOwner::kAdc0Capture},
    {1U, 1U, 15U, AdcInputPad::kGpioAdB1_03, 2U, 8U, 4U,
     kXbarPitTrigger1Input, kXbarAdcEtcTrigger4Output, 1U,
     kDmamuxAdc2Source, ResourceOwner::kAdc1Capture},
};

inline constexpr std::uint8_t kAdc0Pin =
    kAdcConverterConfigurations[0].teensy_pin;
inline constexpr std::uint8_t kAdc1Pin =
    kAdcConverterConfigurations[1].teensy_pin;
inline constexpr std::uint8_t kAdc0Peripheral =
    kAdcConverterConfigurations[0].adc_peripheral;
inline constexpr std::uint8_t kAdc1Peripheral =
    kAdcConverterConfigurations[1].adc_peripheral;
inline constexpr std::uint8_t kAdc0InputChannel =
    kAdcConverterConfigurations[0].input_channel;
inline constexpr std::uint8_t kAdc1InputChannel =
    kAdcConverterConfigurations[1].input_channel;
inline constexpr std::uint8_t kGpioPinsByBit[] = {6U, 7U, 8U, 9U,
                                                  10U, 11U, 12U, 13U};
// Array order is the packed wire bit. Teensy startup selects the GPIO7 fast
// aliases for these pads; clearing the same-numbered GPR27 bits selects the
// DMA-visible GPIO2 aliases without changing any unrelated pin.
inline constexpr GpioPinMapping kGpioMappingsByPackedBit[] = {
    {6U, 10U}, {7U, 17U}, {8U, 16U}, {9U, 11U},
    {10U, 0U}, {11U, 2U}, {12U, 1U}, {13U, 3U},
};
inline constexpr std::uint8_t kAuxGpioPinsByBit[] = {
    16U, 17U, 18U, 19U, 20U, 21U, 22U, 23U,
};
inline constexpr GpioPinMapping kAuxGpioMappingsByPackedBit[] = {
    {16U, 23U}, {17U, 22U}, {18U, 17U}, {19U, 16U},
    {20U, 26U}, {21U, 27U}, {22U, 24U}, {23U, 25U},
};
inline constexpr std::uint8_t kPrimaryGpioPort = 2U;
inline constexpr std::uint8_t kAuxGpioPort = 1U;
inline constexpr GpioBitAllocation kGpioBitAllocations[] = {
    {kPrimaryGpioPort, 10U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 17U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 16U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 11U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 0U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 2U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 1U, ResourceOwner::kGpioCapture},
    {kPrimaryGpioPort, 3U, ResourceOwner::kGpioCapture},
    {kAuxGpioPort, 23U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 22U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 17U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 16U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 26U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 27U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 24U, ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPort, 25U, ResourceOwner::kAuxGpioCapture},
};
inline constexpr std::uint32_t kGpio2PsrCaptureMask =
    (std::uint32_t{1U} << 10U) | (std::uint32_t{1U} << 17U) |
    (std::uint32_t{1U} << 16U) | (std::uint32_t{1U} << 11U) |
    (std::uint32_t{1U} << 0U) | (std::uint32_t{1U} << 2U) |
    (std::uint32_t{1U} << 1U) | (std::uint32_t{1U} << 3U);
inline constexpr std::uint32_t kGpio7ToGpio2Gpr27ClearMask =
    kGpio2PsrCaptureMask;
inline constexpr std::uint32_t kGpio1PsrCaptureMask =
    (std::uint32_t{1U} << 23U) | (std::uint32_t{1U} << 22U) |
    (std::uint32_t{1U} << 17U) | (std::uint32_t{1U} << 16U) |
    (std::uint32_t{1U} << 26U) | (std::uint32_t{1U} << 27U) |
    (std::uint32_t{1U} << 24U) | (std::uint32_t{1U} << 25U);
inline constexpr std::uint32_t kGpio6ToGpio1Gpr26ClearMask =
    kGpio1PsrCaptureMask;
inline constexpr std::uint8_t kGpioPitChannel = 0U;
inline constexpr std::uint8_t kGpioEdmaChannel = 2U;
inline constexpr std::uint8_t kGpioEdmaPriority = 0U;
inline constexpr std::uint8_t kAuxGpioEdmaChannel =
    protocol_v2::kAuxGpioEdmaChannel;
inline constexpr std::uint8_t kAuxGpioEdmaPriority =
    protocol_v2::kInputModeEdmaPriorities[3];
inline constexpr std::uint8_t kPrimaryGpioInputEdmaPriority =
    protocol_v2::kInputModeEdmaPriorities[2];
inline constexpr std::uint8_t kGpioEdmaIrqPriority = 64U;
inline constexpr std::uint8_t kAuxGpioEdmaIrqPriority =
    protocol_v2::kGpioDmaIrqPriority;
// Protect both 1 MHz result registers from the continuous 4 MHz GPIO request.
// ADC0 is triggered 500 ns first and has the highest fixed priority, ADC1 is
// next, and GPIO retains the remaining bus slots at the lowest priority.
inline constexpr std::uint8_t kAdcEdmaPriorities[] = {2U, 1U};
// INPUT mode uses fixed arbitration in this exact order: ADC0, ADC1, primary
// GPIO2, auxiliary GPIO1. This is a bus-read ordering policy, not a claim that
// the two pads have a simultaneous electrical aperture.
inline constexpr std::uint8_t kInputModeEdmaPriorities[] = {
    protocol_v2::kInputModeEdmaPriorities[0],
    protocol_v2::kInputModeEdmaPriorities[1],
    protocol_v2::kInputModeEdmaPriorities[2],
    protocol_v2::kInputModeEdmaPriorities[3],
};
inline constexpr std::uint8_t kAdcEdmaIrqPriority = 48U;

// The later ADC1 completion IRQ is the paired path's sole wakeup; progress is
// inferred from both live TCDs after immediately acknowledging the latches, so
// a clear cannot erase a newer ADC0 completion. ADC0's line stays reserved but
// masked. That handler and ADC_ETC errors share one priority because they mutate
// the same generation state. GPIO tolerates either preempting its lower-priority
// completion interrupt.
inline constexpr InterruptAllocation kInterruptAllocations[] = {
    {InterruptUse::kAdc0DmaCompletion, kIrqDmaChannel0,
     kArmExceptionVectorCount + kIrqDmaChannel0, kAdcEdmaIrqPriority,
     ResourceOwner::kAdc0Capture},
    {InterruptUse::kAdc1DmaCompletion, kIrqDmaChannel1,
     kArmExceptionVectorCount + kIrqDmaChannel1, kAdcEdmaIrqPriority,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, kIrqAdcEtcError,
     kArmExceptionVectorCount + kIrqAdcEtcError, kAdcEdmaIrqPriority,
     ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, kIrqDmaChannel2,
     kArmExceptionVectorCount + kIrqDmaChannel2, kGpioEdmaIrqPriority,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAuxGpioDmaCompletion, kIrqDmaChannel3,
     kArmExceptionVectorCount + kIrqDmaChannel3,
     kAuxGpioEdmaIrqPriority, ResourceOwner::kAuxGpioCapture},
};

inline constexpr PinAllocation kPinAllocations[] = {
    {kAdc0Pin, ResourceOwner::kAdc0Capture},
    {kAdc1Pin, ResourceOwner::kAdc1Capture},
    {kGpioPinsByBit[0], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[1], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[2], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[3], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[4], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[5], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[6], ResourceOwner::kGpioCapture},
    {kGpioPinsByBit[7], ResourceOwner::kGpioCapture},
    {kAuxGpioPinsByBit[0], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[1], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[2], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[3], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[4], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[5], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[6], ResourceOwner::kAuxGpioCapture},
    {kAuxGpioPinsByBit[7], ResourceOwner::kAuxGpioCapture},
};

// PIT0 is the exact 4 MHz GPIO master. PIT1 is chained down to the proposed
// 1 MHz ADC-pair event. These are reservations, not a claim that the Phase 04
// CPU-generated synthetic source enables either timer.
inline constexpr PitAllocation kPitAllocations[] = {
    {kGpioPitChannel, ResourceOwner::kGpioCapture},
    {1U, ResourceOwner::kAcquisitionClock},
};

// The PIT trigger is a periodic transition source. Detect one rising edge per
// period; the inherited dual-edge setting over-counted at 4 MHz on silicon.
inline constexpr std::uint8_t kGpioXbarInput = kXbarPitTrigger0Input;
inline constexpr std::uint8_t kGpioXbarOutput = kXbarDmaRequest30Output;
inline constexpr std::uint8_t kAuxGpioXbarInput = kXbarPitTrigger0Input;
inline constexpr std::uint8_t kAuxGpioXbarOutput =
    protocol_v2::kAuxGpioXbarOutput;
inline constexpr std::uint8_t kGpioXbarActiveEdge = 1U;
inline constexpr std::uint8_t kGpioXbarSelectionRegister =
    kGpioXbarOutput / 2U;
inline constexpr std::uint8_t kAuxGpioXbarSelectionRegister =
    kAuxGpioXbarOutput / 2U;
inline constexpr std::uint16_t kGpioXbarSelectionMask = 0x00FFU;
inline constexpr std::uint16_t kAuxGpioXbarSelectionMask = 0xFF00U;
inline constexpr std::uint16_t kPairedGpioXbarSelectionMask =
    kGpioXbarSelectionMask | kAuxGpioXbarSelectionMask;
inline constexpr XbarRoute kXbarRoutes[] = {
    {kGpioXbarInput, kGpioXbarOutput, ResourceOwner::kGpioCapture},
    {kAuxGpioXbarInput, kAuxGpioXbarOutput,
     ResourceOwner::kAuxGpioCapture},
    {kAdcConverterConfigurations[0].xbar_input,
     kAdcConverterConfigurations[0].xbar_output,
     kAdcConverterConfigurations[0].owner},
    {kAdcConverterConfigurations[1].xbar_input,
     kAdcConverterConfigurations[1].xbar_output,
     kAdcConverterConfigurations[1].owner},
};

inline constexpr AdcEtcAllocation kAdcEtcAllocations[] = {
    {kAdcConverterConfigurations[0].adc_etc_trigger,
     kAdcConverterConfigurations[0].adc_peripheral,
     kAdcConverterConfigurations[0].owner},
    {kAdcConverterConfigurations[1].adc_etc_trigger,
     kAdcConverterConfigurations[1].adc_peripheral,
     kAdcConverterConfigurations[1].owner},
};

inline constexpr std::uint8_t kGpioDmamuxSource =
    kDmamuxXbar1Request0Source;
inline constexpr std::uint8_t kAuxGpioDmamuxSource =
    protocol_v2::kAuxGpioDmamuxSource;
inline constexpr EdmaAllocation kEdmaAllocations[] = {
    {kAdcConverterConfigurations[0].edma_channel,
     kAdcConverterConfigurations[0].dmamux_source,
     kAdcConverterConfigurations[0].owner},
    {kAdcConverterConfigurations[1].edma_channel,
     kAdcConverterConfigurations[1].dmamux_source,
     kAdcConverterConfigurations[1].owner},
    {kGpioEdmaChannel, kGpioDmamuxSource, ResourceOwner::kGpioCapture},
    {kAuxGpioEdmaChannel, kAuxGpioDmamuxSource,
     ResourceOwner::kAuxGpioCapture},
};

inline constexpr std::size_t kCommandParserCapacityBytes = 68U;
inline constexpr std::size_t kUsbRxScratchBytes = 128U;
inline constexpr std::size_t kCommandQueueDepth = 4U;
inline constexpr std::size_t kResponseQueueDepth = 4U;
// Eight data buffers retain two complete generations beyond the six-entry
// hardware look-ahead pipeline. Twelve generation-indexed TCD slots keep
// descriptor links unique even when multiple pressure generations target the
// shared overflow sink.
inline constexpr std::size_t kAdcDmaRingDepth = 8U;
inline constexpr std::size_t kAdcDmaPipelineDepth = 6U;
// At 1 MHz in INPUT mode a generation is only 506 us. Reserving six of
// eight buffers ahead leaves just two for foreground framing. Use four
// look-ahead generations in the fixed-rate release, retaining four buffers
// for command/USB scheduling latency without changing allocated resources.
inline constexpr std::size_t kAdcDmaActivePipelineDepth =
    input_experiment::kReleaseFixed1MHz ? 4U : kAdcDmaPipelineDepth;
inline constexpr std::size_t kAdcDmaDescriptorCount =
    2U * kAdcDmaPipelineDepth;
inline constexpr std::size_t kAdcFramesPerLoop = 2U;
inline constexpr std::size_t kAdcPackerStateBudgetBytes = 512U;
inline constexpr std::size_t kGpioRawDmaRingDepth = 4U;
inline constexpr std::size_t kGpioRawDmaDescriptorCount =
    kGpioRawDmaRingDepth + 1U;
inline constexpr std::size_t kAuxGpioRawDmaRingDepth =
    protocol_v2::kAuxGpioRawRingDepth;
inline constexpr std::size_t kAuxGpioRawDmaDescriptorCount =
    kAuxGpioRawDmaRingDepth + 1U;
inline constexpr std::size_t kGpioPackedRingDepth = 4U;
inline constexpr std::size_t kGpioRawBuffersPerLoop = 2U;
inline constexpr std::size_t kGpioPackedFramesPerLoop = 2U;
inline constexpr std::size_t kGpioPackerStateBudgetBytes = 2048U;
// The generation table and ownership records are CPU state. INPUT mode leases
// the beginning of the IDLE-only checksum benchmark's aligned OCRAM buffer, so
// the paired path does not consume either explicit target-memory floor. The
// target type is compile-time bounded by this value.
inline constexpr std::size_t kGpioPairedJoinStateBudgetBytes = 768U;
// At the nominal combined framed rate, each 4096-byte buffer represents 0.506
// ms. Keep a 105-frame primary bank in cacheless DTCM, then add a fixed
// 95-frame CPU-owned OCRAM reserve. The complete 200-frame pool retains
// 101.200 ms and the pinned core contributes another 1.012 ms in four 2048-byte
// TX buffers. This covers the 60.715 ms Phase 05 service gap while retaining at
// least 32 KiB of target RAM1 for locals/stack and every future DMA-ring budget.
inline constexpr std::size_t kPacketBufferPrimaryCount = 105U;
inline constexpr std::size_t kPacketBufferReserveCount = 95U;
inline constexpr std::size_t kPacketBufferCount =
    kPacketBufferPrimaryCount + kPacketBufferReserveCount;
inline constexpr std::size_t kPacketReadyQueueDepth = kPacketBufferCount;
inline constexpr std::size_t kPacketTransmitQueueDepth = kPacketBufferCount;
inline constexpr std::size_t kPacketPromotionsPerLoop = 4U;
// One elapsed coverage interval makes one ADC/GPIO pair due. Limiting a visit
// to that pair halves the longest checksum burst while retaining same-visit
// promotion/transmission and fast bounded catch-up on the next loop.
inline constexpr std::size_t kSyntheticFramesPerLoop = 2U;
inline constexpr std::size_t kPacketPipelineStateBudgetBytes = 8192U;
inline constexpr std::size_t kChecksumBenchmarkBufferBytes =
    protocol_v1::kDataFrameBytes;
inline constexpr std::size_t kGpioClockDiagnosticSinkBytes = kCacheLineBytes;
// Pinned Teensy 1.62 cores/teensy4/usb_serial.c constants. The core owns this
// aligned DMAMEM ring; it is documented here but is not project allocation.
inline constexpr std::size_t kPinnedUsbCdcTxBufferCount = 4U;
inline constexpr std::size_t kPinnedUsbCdcTxBufferBytes = 2048U;
inline constexpr std::size_t kPinnedUsbCdcTxStorageBytes =
    kPinnedUsbCdcTxBufferCount * kPinnedUsbCdcTxBufferBytes;
inline constexpr std::size_t kUsbRxBudgetBytesPerLoop = 1024U;
// One physical acquisition visit may consume a meaningful fraction of the
// 1,012 us frame interval. Let the following TX visit fill the pinned core's
// existing four-buffer ring, but offer at most two 512-byte high-speed packets
// per call so the paired ADC completion IRQs cannot be hidden behind a 2 KiB
// core copy. The aggregate byte and call work remains fixed and bounded.
inline constexpr std::size_t kUsbTxBudgetBytesPerVisit =
    kPinnedUsbCdcTxStorageBytes;
inline constexpr std::size_t kUsbTxVisitsPerLoop = 2U;
inline constexpr std::size_t kUsbTxBudgetBytesPerLoop =
    kUsbTxVisitsPerLoop * kUsbTxBudgetBytesPerVisit;
// Data is offered to the pinned core in one core-buffer-sized block whenever
// possible. A visit waits for at least one high-speed USB packet of capacity
// instead of deliberately degrading into byte-at-a-time calls. Unexpected
// backend prefixes are still retained and resumed exactly.
inline constexpr std::size_t kUsbTxMaxWriteBytes = 1024U;
inline constexpr std::size_t kUsbTxMinimumWriteBytes = 512U;
inline constexpr std::size_t kUsbRxCallsPerLoop = 8U;
inline constexpr std::size_t kUsbTxCallsPerVisit = 8U;
inline constexpr std::size_t kUsbTxCallsPerLoop =
    kUsbTxVisitsPerLoop * kUsbTxCallsPerVisit;

constexpr std::size_t alignUp(std::size_t value, std::size_t alignment) {
  return ((value + alignment - 1U) / alignment) * alignment;
}

inline constexpr std::size_t kAdcDmaBufferStrideBytes =
    alignUp(protocol_v1::kDataPayloadBytes, kCacheLineBytes);
inline constexpr std::size_t kEdmaTcdBytes = 32U;
inline constexpr std::size_t kAdcDmaRingBytes =
    kAdcDmaRingDepth * kAdcDmaBufferStrideBytes;
inline constexpr std::size_t kAdcDmaOverflowSinkBytes = kCacheLineBytes;
inline constexpr std::size_t kAdcDmaDescriptorBytes =
    kLogicalAdcCount * kAdcDmaDescriptorCount * kEdmaTcdBytes;
inline constexpr std::size_t kGpioRawDmaBufferBytes =
    protocol_v1::kGpioSamplesPerFrame * sizeof(std::uint32_t);
inline constexpr std::size_t kGpioRawDmaRingBytes =
    kGpioRawDmaRingDepth * kGpioRawDmaBufferBytes;
inline constexpr std::size_t kInputGpioRawDmaBufferBytes =
    protocol_v2::kInputGpioSamplesPerFrame * sizeof(std::uint32_t);
inline constexpr std::size_t kPrimaryInputGpioRawDmaRingBytes =
    kAuxGpioRawDmaRingDepth * kInputGpioRawDmaBufferBytes;
inline constexpr std::size_t kAuxGpioRawDmaRingBytes =
    kAuxGpioRawDmaRingDepth * kInputGpioRawDmaBufferBytes;
inline constexpr std::size_t kGpioRawDmaOverflowSinkBytes =
    kCacheLineBytes;
inline constexpr std::size_t kPrimaryInputGpioRawDmaOverflowSinkBytes =
    kCacheLineBytes;
inline constexpr std::size_t kAuxGpioRawDmaOverflowSinkBytes =
    kCacheLineBytes;
inline constexpr std::size_t kGpioRawDmaDescriptorBytes =
    kGpioRawDmaDescriptorCount * kEdmaTcdBytes;
inline constexpr std::size_t kAuxGpioRawDmaDescriptorBytes =
    kAuxGpioRawDmaDescriptorCount * kEdmaTcdBytes;
inline constexpr std::size_t kGpioPairedJoinStateOffsetBytes = 0U;
inline constexpr std::size_t kAuxGpioRawDmaDescriptorOffsetBytes =
    kGpioPairedJoinStateOffsetBytes + kGpioPairedJoinStateBudgetBytes;
inline constexpr std::size_t kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes =
    kAuxGpioRawDmaDescriptorOffsetBytes + kAuxGpioRawDmaDescriptorBytes;
inline constexpr std::size_t kAuxGpioRawDmaOverflowSinkOffsetBytes =
    kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes +
    kPrimaryInputGpioRawDmaOverflowSinkBytes;
inline constexpr std::size_t kAuxInputWorkspaceBytes =
    kAuxGpioRawDmaOverflowSinkOffsetBytes +
    kAuxGpioRawDmaOverflowSinkBytes;
inline constexpr std::size_t kGpioPackedBufferStrideBytes =
    alignUp(protocol_v1::kDataPayloadBytes, kCacheLineBytes);
inline constexpr std::size_t kInputGpioPackedBufferStrideBytes =
    alignUp(protocol_v2::kInputGpioSamplesPerFrame * sizeof(std::uint16_t),
            kCacheLineBytes);
inline constexpr std::size_t kPacketBufferStorageBytes =
    kPacketBufferCount * protocol_v1::kDataFrameBytes;
inline constexpr std::size_t kPacketBufferPrimaryStorageBytes =
    kPacketBufferPrimaryCount * protocol_v1::kDataFrameBytes;
inline constexpr std::size_t kPacketBufferReserveStorageBytes =
    kPacketBufferReserveCount * protocol_v1::kDataFrameBytes;
// READY and TRANSMIT queues contain one-byte indexes into the shared packet
// pool; they never allocate another payload copy. Their backing arrays and all
// queue metadata/records are covered by kPacketPipelineStateBudgetBytes and
// the PacketBufferPipeline sizeof assertion.
inline constexpr std::size_t kPacketReadyIndexStorageBytes =
    2U * kPacketReadyQueueDepth * sizeof(std::uint8_t);
inline constexpr std::size_t kPacketTransmitIndexStorageBytes =
    kPacketTransmitQueueDepth * sizeof(std::uint8_t);
inline constexpr std::size_t kPacketIndexStorageBytes =
    kPacketReadyIndexStorageBytes + kPacketTransmitIndexStorageBytes;

// The combined physical path reuses these simultaneous, fixed reservations.
// Packet frames change ownership in place, so the READY and TRANSMIT stages do
// not appear here as duplicate 4,096-byte banks.
inline constexpr std::size_t kCombinedAcquisitionRam1BufferBytes =
    kPacketBufferPrimaryStorageBytes + kPacketPipelineStateBudgetBytes +
    kAdcPackerStateBudgetBytes + kGpioPackerStateBudgetBytes;
inline constexpr std::size_t kCombinedAcquisitionRam2BufferBytes =
    kPacketBufferReserveStorageBytes + kAdcDmaRingBytes +
    kAdcDmaOverflowSinkBytes + kAdcDmaDescriptorBytes +
    kGpioRawDmaRingBytes + kGpioRawDmaOverflowSinkBytes +
    kGpioRawDmaDescriptorBytes +
    kPrimaryInputGpioRawDmaOverflowSinkBytes +
    kAuxGpioRawDmaOverflowSinkBytes + kAuxGpioRawDmaDescriptorBytes +
    kGpioPairedJoinStateBudgetBytes +
    kGpioPackedRingDepth * kGpioPackedBufferStrideBytes;
inline constexpr std::size_t kCombinedAcquisitionAndUsbRam2BufferBytes =
    kCombinedAcquisitionRam2BufferBytes + kPinnedUsbCdcTxStorageBytes;

inline constexpr MemoryAllocation kMemoryAllocations[] = {
    {MemoryUse::kCommandParser, MemoryRegion::kDtcmRam1,
     kCommandParserCapacityBytes, 4U, ResourceOwner::kControlPlane},
    {MemoryUse::kUsbRxScratch, MemoryRegion::kDtcmRam1,
     kUsbRxScratchBytes, 4U, ResourceOwner::kUsbTransport},
    {MemoryUse::kCommandQueue, MemoryRegion::kDtcmRam1,
     kCommandQueueDepth * protocol_v1::kMaxCommandFrameBytes, 4U,
     ResourceOwner::kControlPlane},
    {MemoryUse::kResponseQueue, MemoryRegion::kDtcmRam1,
     kResponseQueueDepth * protocol_v1::kMaxControlFrameBytes, 4U,
     ResourceOwner::kUsbTransport},
    {MemoryUse::kPacketBufferStorage, MemoryRegion::kDtcmRam1,
     kPacketBufferPrimaryStorageBytes, kCacheLineBytes,
     ResourceOwner::kPacketizer},
    {MemoryUse::kPacketBufferReserveStorage,
     MemoryRegion::kOcramRam2Dma, kPacketBufferReserveStorageBytes,
     kCacheLineBytes, ResourceOwner::kPacketizer},
    {MemoryUse::kPacketPipelineState, MemoryRegion::kDtcmRam1,
     kPacketPipelineStateBudgetBytes, kCacheLineBytes,
     ResourceOwner::kPacketizer},
    {MemoryUse::kAdcDmaRing, MemoryRegion::kOcramRam2Dma,
     kAdcDmaRingBytes, kCacheLineBytes,
     ResourceOwner::kAdcCapture},
    {MemoryUse::kAdcDmaOverflowSink, MemoryRegion::kOcramRam2Dma,
     kAdcDmaOverflowSinkBytes, kCacheLineBytes,
     ResourceOwner::kAdcCapture},
    {MemoryUse::kAdcDmaDescriptors, MemoryRegion::kOcramRam2Dma,
     kAdcDmaDescriptorBytes, kCacheLineBytes,
     ResourceOwner::kAdcCapture},
    {MemoryUse::kAdcPackerState, MemoryRegion::kDtcmRam1,
     kAdcPackerStateBudgetBytes, alignof(std::uint64_t),
     ResourceOwner::kAdcPacker},
    {MemoryUse::kGpioRawDmaRing, MemoryRegion::kOcramRam2Dma,
     kGpioRawDmaRingBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kGpioRawDmaOverflowSink, MemoryRegion::kOcramRam2Dma,
     kGpioRawDmaOverflowSinkBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kGpioRawDmaDescriptors, MemoryRegion::kOcramRam2Dma,
     kGpioRawDmaDescriptorBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kGpioPackedRing, MemoryRegion::kOcramRam2Dma,
     kGpioPackedRingDepth * kGpioPackedBufferStrideBytes, kCacheLineBytes,
     ResourceOwner::kGpioPacker},
    {MemoryUse::kGpioPackerState, MemoryRegion::kDtcmRam1,
     kGpioPackerStateBudgetBytes, kCacheLineBytes,
     ResourceOwner::kGpioPacker},
    {MemoryUse::kGpioClockDiagnosticSink, MemoryRegion::kOcramRam2Dma,
     kGpioClockDiagnosticSinkBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kChecksumBenchmarkOcramBuffer,
     MemoryRegion::kOcramRam2Dma, kChecksumBenchmarkBufferBytes,
     kCacheLineBytes, ResourceOwner::kChecksumBenchmark},
};

// The checksum benchmark runs only after the data path is fully quiescent, so
// its cacheless working buffer is a bounded view of packet page zero rather
// than a second 4 KiB DTCM allocation. Benchmark writes are harmless to a FREE
// packet page; packetization replaces every byte in the selected frame layout
// before that byte can be published.
inline constexpr MemoryViewAllocation kIdleModeMemoryViews[] = {
    {MemoryUse::kChecksumBenchmarkDtcmBuffer,
     MemoryUse::kPacketBufferStorage, 0U,
     kChecksumBenchmarkBufferBytes, ResourceOwner::kChecksumBenchmark},
};

// INPUT mode overlays two non-overlapping half-sized raw rings on the exact
// legacy GPIO ring allocation. Its auxiliary TCDs, sink, and join state lease
// disjoint cache-line views of the OCRAM checksum scratch, whose benchmark is
// IDLE-only. Packet storage therefore remains 200 frames and neither target
// memory floor is traded away behind the auxiliary bank.
inline constexpr MemoryViewAllocation kInputModeMemoryViews[] = {
    {MemoryUse::kPrimaryInputGpioRawDmaRing,
     MemoryUse::kGpioRawDmaRing, 0U,
     kPrimaryInputGpioRawDmaRingBytes, ResourceOwner::kGpioCapture},
    {MemoryUse::kAuxGpioRawDmaRing, MemoryUse::kGpioRawDmaRing,
     kPrimaryInputGpioRawDmaRingBytes, kAuxGpioRawDmaRingBytes,
     ResourceOwner::kAuxGpioCapture},
    {MemoryUse::kGpioPairedJoinState,
     MemoryUse::kChecksumBenchmarkOcramBuffer,
     kGpioPairedJoinStateOffsetBytes, kGpioPairedJoinStateBudgetBytes,
     ResourceOwner::kGpioJoin},
    {MemoryUse::kAuxGpioRawDmaDescriptors,
     MemoryUse::kChecksumBenchmarkOcramBuffer,
     kAuxGpioRawDmaDescriptorOffsetBytes, kAuxGpioRawDmaDescriptorBytes,
     ResourceOwner::kAuxGpioCapture},
    {MemoryUse::kPrimaryInputGpioRawDmaOverflowSink,
     MemoryUse::kChecksumBenchmarkOcramBuffer,
     kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes,
     kPrimaryInputGpioRawDmaOverflowSinkBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kAuxGpioRawDmaOverflowSink,
     MemoryUse::kChecksumBenchmarkOcramBuffer,
     kAuxGpioRawDmaOverflowSinkOffsetBytes,
     kAuxGpioRawDmaOverflowSinkBytes, ResourceOwner::kAuxGpioCapture},
};

template <typename T, std::size_t N>
constexpr std::size_t countOf(const T (&)[N]) {
  return N;
}

constexpr std::uint8_t xbarSelectionRegister(std::uint8_t output) {
  return static_cast<std::uint8_t>(output / 2U);
}

constexpr std::uint8_t xbarSelectionShift(std::uint8_t output) {
  return (output & 1U) == 0U ? 0U : 8U;
}

constexpr std::uint16_t xbarSelectionMask(std::uint8_t output) {
  return static_cast<std::uint16_t>(0x00FFU << xbarSelectionShift(output));
}

constexpr std::uint16_t replaceXbarSelection(std::uint16_t current,
                                             std::uint8_t output,
                                             std::uint8_t input) {
  const std::uint16_t mask = xbarSelectionMask(output);
  return static_cast<std::uint16_t>(
      (current & static_cast<std::uint16_t>(~mask)) |
      (static_cast<std::uint16_t>(input) << xbarSelectionShift(output)));
}

template <std::size_t N>
constexpr bool validPins(const PinAllocation (&allocations)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (allocations[left].pin >= kTeensy40DigitalPinCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (allocations[left].pin == allocations[right].pin) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t PinN, std::size_t AllocationN>
constexpr bool pinAllocationsMatch(
    const std::uint8_t (&pins)[PinN],
    const PinAllocation (&allocations)[AllocationN],
    std::size_t allocation_offset, ResourceOwner owner) {
  if (allocation_offset + PinN > AllocationN) {
    return false;
  }
  for (std::size_t index = 0U; index < PinN; ++index) {
    const PinAllocation &allocation = allocations[allocation_offset + index];
    if (allocation.pin != pins[index] || allocation.owner != owner) {
      return false;
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validGpioPinMappings(
    const GpioPinMapping (&mappings)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (mappings[left].teensy_pin >= kTeensy40DigitalPinCount ||
        mappings[left].gpio2_bit >= kGpioPortBitCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (mappings[left].teensy_pin == mappings[right].teensy_pin ||
          mappings[left].gpio2_bit == mappings[right].gpio2_bit) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validGpioBitAllocations(
    const GpioBitAllocation (&allocations)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (allocations[left].gpio_port == 0U ||
        allocations[left].gpio_port > kGpioPortCount ||
        allocations[left].gpio_bit >= kGpioPortBitCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (allocations[left].gpio_port == allocations[right].gpio_port &&
          allocations[left].gpio_bit == allocations[right].gpio_bit) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t MappingN, std::size_t AllocationN>
constexpr bool gpioBitAllocationsMatch(
    const GpioPinMapping (&mappings)[MappingN],
    const GpioBitAllocation (&allocations)[AllocationN],
    std::size_t allocation_offset, std::uint8_t gpio_port,
    ResourceOwner owner) {
  if (allocation_offset + MappingN > AllocationN) {
    return false;
  }
  for (std::size_t index = 0; index < MappingN; ++index) {
    const GpioBitAllocation &allocation =
        allocations[allocation_offset + index];
    if (allocation.gpio_port != gpio_port ||
        allocation.gpio_bit != mappings[index].gpio2_bit ||
        allocation.owner != owner) {
      return false;
    }
  }
  return true;
}

template <std::size_t MappingN, std::size_t PinN>
constexpr bool gpioPinOrderMatches(
    const GpioPinMapping (&mappings)[MappingN],
    const std::uint8_t (&pins)[PinN]) {
  if (MappingN != PinN) {
    return false;
  }
  for (std::size_t index = 0; index < MappingN; ++index) {
    if (mappings[index].teensy_pin != pins[index]) {
      return false;
    }
  }
  return true;
}

constexpr bool validAdcInputPad(AdcInputPad pad) {
  return pad == AdcInputPad::kGpioAdB1_02 ||
         pad == AdcInputPad::kGpioAdB1_03;
}

template <std::size_t N>
constexpr bool validAdcConverterConfigurations(
    const AdcConverterConfiguration (&configurations)[N]) {
  if (N != kLogicalAdcCount) {
    return false;
  }
  for (std::size_t left = 0; left < N; ++left) {
    const AdcConverterConfiguration &configuration = configurations[left];
    const ResourceOwner expected_owner =
        configuration.logical_converter == 0U
            ? ResourceOwner::kAdc0Capture
            : ResourceOwner::kAdc1Capture;
    if (configuration.logical_converter >= kLogicalAdcCount ||
        configuration.teensy_adc_library_module >= kLogicalAdcCount ||
        configuration.teensy_pin >= kTeensy40DigitalPinCount ||
        !validAdcInputPad(configuration.input_pad) ||
        configuration.adc_peripheral == 0U ||
        configuration.adc_peripheral > kAdcPeripheralCount ||
        configuration.input_channel >= kAdcInputChannelCount ||
        configuration.adc_etc_trigger >= kAdcEtcTriggerCount ||
        configuration.xbar_input >= kXbarInputCount ||
        configuration.xbar_output >= kXbarOutputCount ||
        configuration.edma_channel >= kEdmaChannelCount ||
        configuration.dmamux_source >= kDmamuxSourceCount ||
        configuration.logical_converter + 1U !=
            configuration.adc_peripheral ||
        configuration.teensy_adc_library_module + 1U !=
            configuration.adc_peripheral ||
        configuration.adc_etc_trigger / 4U + 1U !=
            configuration.adc_peripheral ||
        configuration.owner != expected_owner) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      const AdcConverterConfiguration &later = configurations[right];
      if (configuration.logical_converter == later.logical_converter ||
          configuration.teensy_adc_library_module ==
              later.teensy_adc_library_module ||
          configuration.teensy_pin == later.teensy_pin ||
          configuration.input_pad == later.input_pad ||
          configuration.adc_peripheral == later.adc_peripheral ||
          configuration.adc_etc_trigger == later.adc_etc_trigger ||
          configuration.xbar_output == later.xbar_output ||
          configuration.edma_channel == later.edma_channel ||
          configuration.dmamux_source == later.dmamux_source ||
          configuration.owner == later.owner) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validPitAllocations(const PitAllocation (&allocations)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (allocations[left].channel >= kPitChannelCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (allocations[left].channel == allocations[right].channel) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validXbarRoutes(const XbarRoute (&routes)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (routes[left].input >= kXbarInputCount ||
        routes[left].output >= kXbarOutputCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (routes[left].output == routes[right].output ||
          (xbarSelectionRegister(routes[left].output) ==
               xbarSelectionRegister(routes[right].output) &&
           (xbarSelectionMask(routes[left].output) &
            xbarSelectionMask(routes[right].output)) != 0U)) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validAdcEtcAllocations(
    const AdcEtcAllocation (&allocations)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (allocations[left].trigger >= kAdcEtcTriggerCount ||
        allocations[left].adc_peripheral == 0U ||
        allocations[left].adc_peripheral > kAdcPeripheralCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (allocations[left].trigger == allocations[right].trigger ||
          allocations[left].adc_peripheral ==
              allocations[right].adc_peripheral) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validEdmaAllocations(const EdmaAllocation (&allocations)[N]) {
  for (std::size_t left = 0; left < N; ++left) {
    if (allocations[left].channel >= kEdmaChannelCount ||
        allocations[left].dmamux_source >= kDmamuxSourceCount) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (allocations[left].channel == allocations[right].channel ||
          allocations[left].dmamux_source ==
              allocations[right].dmamux_source) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validEdmaPriorities(
    const std::uint8_t (&adc_priorities)[N],
    std::uint8_t gpio_priority) {
  if (N != kLogicalAdcCount) {
    return false;
  }
  for (std::size_t left = 0U; left < N; ++left) {
    if (adc_priorities[left] == gpio_priority) {
      return false;
    }
    for (std::size_t right = left + 1U; right < N; ++right) {
      if (adc_priorities[left] == adc_priorities[right]) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool strictlyDescendingEdmaPriorities(
    const std::uint8_t (&priorities)[N]) {
  if (N == 0U) {
    return false;
  }
  for (std::size_t index = 0U; index < N; ++index) {
    if (priorities[index] >= kEdmaChannelCount) {
      return false;
    }
    if (index != 0U && priorities[index - 1U] <= priorities[index]) {
      return false;
    }
  }
  return true;
}

constexpr bool isPowerOfTwo(std::size_t value) {
  return value != 0U && (value & (value - 1U)) == 0U;
}

template <std::size_t N>
constexpr bool validMemoryAllocations(
    const MemoryAllocation (&allocations)[N]) {
  for (std::size_t index = 0; index < N; ++index) {
    const MemoryAllocation &allocation = allocations[index];
    if (allocation.bytes == 0U || !isPowerOfTwo(allocation.alignment) ||
        allocation.bytes % allocation.alignment != 0U) {
      return false;
    }
    for (std::size_t later = index + 1U; later < N; ++later) {
      if (allocation.use == allocations[later].use) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t AllocationN>
constexpr std::size_t allocationBytes(
    const MemoryAllocation (&allocations)[AllocationN], MemoryUse use) {
  for (const MemoryAllocation &allocation : allocations) {
    if (allocation.use == use) {
      return allocation.bytes;
    }
  }
  return 0U;
}

template <std::size_t ViewN, std::size_t AllocationN>
constexpr bool validMemoryViews(
    const MemoryViewAllocation (&views)[ViewN],
    const MemoryAllocation (&allocations)[AllocationN]) {
  for (std::size_t left = 0U; left < ViewN; ++left) {
    const MemoryViewAllocation &view = views[left];
    const std::size_t storage_bytes = allocationBytes(allocations, view.storage);
    if (view.bytes == 0U || storage_bytes == 0U ||
        view.offset > storage_bytes || view.bytes > storage_bytes - view.offset) {
      return false;
    }
    for (const MemoryAllocation &allocation : allocations) {
      if (view.use == allocation.use) {
        return false;
      }
    }
    for (std::size_t right = left + 1U; right < ViewN; ++right) {
      const MemoryViewAllocation &later = views[right];
      if (view.use == later.use) {
        return false;
      }
      if (view.storage == later.storage &&
          view.offset < later.offset + later.bytes &&
          later.offset < view.offset + view.bytes) {
        return false;
      }
    }
  }
  return true;
}

template <std::size_t N>
constexpr bool validInterruptAllocations(
    const InterruptAllocation (&allocations)[N]) {
  if (N != 5U) {
    return false;
  }
  bool adc0_seen = false;
  bool adc1_seen = false;
  bool adc_etc_seen = false;
  bool gpio_seen = false;
  bool aux_gpio_seen = false;
  std::uint8_t adc0_priority = 0U;
  std::uint8_t adc1_priority = 0U;
  std::uint8_t adc_etc_priority = 0U;
  std::uint8_t gpio_priority = 0U;
  std::uint8_t aux_gpio_priority = 0U;
  for (std::size_t index = 0U; index < N; ++index) {
    const InterruptAllocation &allocation = allocations[index];
    if (allocation.vector != kArmExceptionVectorCount + allocation.irq) {
      return false;
    }
    for (std::size_t later = index + 1U; later < N; ++later) {
      if (allocation.use == allocations[later].use ||
          allocation.irq == allocations[later].irq ||
          allocation.vector == allocations[later].vector) {
        return false;
      }
    }
    switch (allocation.use) {
      case InterruptUse::kAdc0DmaCompletion:
        if (adc0_seen || allocation.irq != kIrqDmaChannel0 ||
            allocation.owner != ResourceOwner::kAdc0Capture) {
          return false;
        }
        adc0_seen = true;
        adc0_priority = allocation.priority;
        break;
      case InterruptUse::kAdc1DmaCompletion:
        if (adc1_seen || allocation.irq != kIrqDmaChannel1 ||
            allocation.owner != ResourceOwner::kAdc1Capture) {
          return false;
        }
        adc1_seen = true;
        adc1_priority = allocation.priority;
        break;
      case InterruptUse::kAdcEtcError:
        if (adc_etc_seen || allocation.irq != kIrqAdcEtcError ||
            allocation.owner != ResourceOwner::kAdcCapture) {
          return false;
        }
        adc_etc_seen = true;
        adc_etc_priority = allocation.priority;
        break;
      case InterruptUse::kGpioDmaCompletion:
        if (gpio_seen || allocation.irq != kIrqDmaChannel2 ||
            allocation.owner != ResourceOwner::kGpioCapture) {
          return false;
        }
        gpio_seen = true;
        gpio_priority = allocation.priority;
        break;
      case InterruptUse::kAuxGpioDmaCompletion:
        if (aux_gpio_seen || allocation.irq != kIrqDmaChannel3 ||
            allocation.owner != ResourceOwner::kAuxGpioCapture) {
          return false;
        }
        aux_gpio_seen = true;
        aux_gpio_priority = allocation.priority;
        break;
      default:
        return false;
    }
  }
  return adc0_seen && adc1_seen && adc_etc_seen && gpio_seen &&
         aux_gpio_seen &&
         adc0_priority == adc1_priority &&
         adc0_priority == adc_etc_priority &&
         adc0_priority < gpio_priority &&
         gpio_priority == aux_gpio_priority;
}

constexpr bool dmaWritesMemory(MemoryUse use) {
  return use == MemoryUse::kAdcDmaRing ||
         use == MemoryUse::kAdcDmaOverflowSink ||
         use == MemoryUse::kAdcDmaDescriptors ||
         use == MemoryUse::kGpioRawDmaRing ||
         use == MemoryUse::kPrimaryInputGpioRawDmaRing ||
         use == MemoryUse::kAuxGpioRawDmaRing ||
         use == MemoryUse::kGpioRawDmaOverflowSink ||
         use == MemoryUse::kPrimaryInputGpioRawDmaOverflowSink ||
         use == MemoryUse::kGpioRawDmaDescriptors ||
         use == MemoryUse::kAuxGpioRawDmaOverflowSink ||
         use == MemoryUse::kAuxGpioRawDmaDescriptors;
}

constexpr bool cacheSensitiveMemory(MemoryUse use) {
  return dmaWritesMemory(use) || use == MemoryUse::kPacketBufferStorage ||
         use == MemoryUse::kPacketBufferReserveStorage ||
         use == MemoryUse::kGpioPackedRing ||
         use == MemoryUse::kGpioPairedJoinState ||
         use == MemoryUse::kGpioClockDiagnosticSink ||
         use == MemoryUse::kChecksumBenchmarkDtcmBuffer ||
         use == MemoryUse::kChecksumBenchmarkOcramBuffer;
}

template <std::size_t N>
constexpr bool validAcquisitionMemoryRegions(
    const MemoryAllocation (&allocations)[N]) {
  for (const MemoryAllocation &allocation : allocations) {
    if (dmaWritesMemory(allocation.use) &&
        allocation.region != MemoryRegion::kOcramRam2Dma) {
      return false;
    }
    if (cacheSensitiveMemory(allocation.use) &&
        (allocation.alignment != kCacheLineBytes ||
         allocation.bytes % kCacheLineBytes != 0U)) {
      return false;
    }
  }
  return true;
}

template <std::size_t ViewN, std::size_t AllocationN>
constexpr bool validAcquisitionMemoryViews(
    const MemoryViewAllocation (&views)[ViewN],
    const MemoryAllocation (&allocations)[AllocationN]) {
  for (const MemoryViewAllocation &view : views) {
    bool storage_is_dma_visible = false;
    for (const MemoryAllocation &allocation : allocations) {
      if (allocation.use == view.storage) {
        storage_is_dma_visible =
            allocation.region == MemoryRegion::kOcramRam2Dma;
      }
    }
    if (cacheSensitiveMemory(view.use) &&
        (!storage_is_dma_visible || view.offset % kCacheLineBytes != 0U ||
         view.bytes % kCacheLineBytes != 0U)) {
      return false;
    }
  }
  return true;
}

template <std::size_t N>
constexpr std::size_t memoryBytes(const MemoryAllocation (&allocations)[N],
                                  MemoryRegion region) {
  std::size_t total = 0U;
  for (const MemoryAllocation &allocation : allocations) {
    if (allocation.region == region) {
      total += allocation.bytes;
    }
  }
  return total;
}

template <std::size_t LeftN, std::size_t RightN>
constexpr bool sameBytes(const std::uint8_t (&left)[LeftN],
                         const std::uint8_t (&right)[RightN]) {
  if (LeftN != RightN) {
    return false;
  }
  for (std::size_t index = 0; index < LeftN; ++index) {
    if (left[index] != right[index]) {
      return false;
    }
  }
  return true;
}

inline constexpr std::size_t kReservedRam1Bytes =
    memoryBytes(kMemoryAllocations, MemoryRegion::kDtcmRam1);
inline constexpr std::size_t kReservedRam2Bytes =
    memoryBytes(kMemoryAllocations, MemoryRegion::kOcramRam2Dma);

// One aggregate projection is consumed by the acquisition controller at
// runtime and asserted here at compile time. Keeping the categories separate
// makes a future route edit fail with a useful resource-class diagnosis.
struct AcquisitionResourceContract {
  bool pins = false;
  bool gpio_bits = false;
  bool pit = false;
  bool xbar = false;
  bool adc_etc = false;
  bool edma = false;
  bool irq_priorities = false;
  bool dma_memory = false;
  bool memory_views = false;
  bool cache_regions = false;

  constexpr bool valid() const {
    return pins && gpio_bits && pit && xbar && adc_etc && edma &&
           irq_priorities && dma_memory && memory_views && cache_regions;
  }
};

inline constexpr AcquisitionResourceContract kAcquisitionResourceContract{
    validPins(kPinAllocations) &&
        pinAllocationsMatch(kGpioPinsByBit, kPinAllocations, 2U,
                            ResourceOwner::kGpioCapture) &&
        pinAllocationsMatch(kAuxGpioPinsByBit, kPinAllocations, 10U,
                            ResourceOwner::kAuxGpioCapture) &&
        validGpioPinMappings(kGpioMappingsByPackedBit) &&
        validGpioPinMappings(kAuxGpioMappingsByPackedBit) &&
        gpioPinOrderMatches(kGpioMappingsByPackedBit, kGpioPinsByBit) &&
        gpioPinOrderMatches(kAuxGpioMappingsByPackedBit,
                            kAuxGpioPinsByBit) &&
        validAdcConverterConfigurations(kAdcConverterConfigurations),
    validGpioBitAllocations(kGpioBitAllocations) &&
        gpioBitAllocationsMatch(kGpioMappingsByPackedBit,
                                kGpioBitAllocations, 0U,
                                kPrimaryGpioPort,
                                ResourceOwner::kGpioCapture) &&
        gpioBitAllocationsMatch(kAuxGpioMappingsByPackedBit,
                                kGpioBitAllocations, 8U,
                                kAuxGpioPort,
                                ResourceOwner::kAuxGpioCapture),
    validPitAllocations(kPitAllocations),
    validXbarRoutes(kXbarRoutes),
    validAdcEtcAllocations(kAdcEtcAllocations),
    validEdmaAllocations(kEdmaAllocations) &&
        validEdmaPriorities(kAdcEdmaPriorities, kGpioEdmaPriority) &&
        strictlyDescendingEdmaPriorities(kInputModeEdmaPriorities),
    validInterruptAllocations(kInterruptAllocations),
    validMemoryAllocations(kMemoryAllocations) &&
        kReservedRam1Bytes <= kRam1BudgetBytes &&
        kReservedRam2Bytes <= kRam2BudgetBytes,
    validMemoryViews(kInputModeMemoryViews, kMemoryAllocations) &&
        validAcquisitionMemoryViews(kInputModeMemoryViews,
                                    kMemoryAllocations),
    validAcquisitionMemoryRegions(kMemoryAllocations),
};

static_assert(validPins(kPinAllocations),
              "pin allocation is unsupported or conflicts");
static_assert(pinAllocationsMatch(kAuxGpioPinsByBit, kPinAllocations, 10U,
                                  ResourceOwner::kAuxGpioCapture),
              "all auxiliary pins must share one capture owner");
static_assert(validGpioPinMappings(kGpioMappingsByPackedBit),
              "GPIO map is unsupported or contains duplicate pins/bits");
static_assert(validGpioPinMappings(kAuxGpioMappingsByPackedBit),
              "auxiliary GPIO map is unsupported or contains duplicates");
static_assert(gpioPinOrderMatches(kGpioMappingsByPackedBit, kGpioPinsByBit),
              "GPIO resource map and packed pin order disagree");
static_assert(gpioPinOrderMatches(kAuxGpioMappingsByPackedBit,
                                  kAuxGpioPinsByBit),
              "auxiliary GPIO resource map and packed order disagree");
static_assert(validGpioBitAllocations(kGpioBitAllocations),
              "GPIO port-bit allocation is unsupported or conflicts");
static_assert(validMemoryViews(kInputModeMemoryViews, kMemoryAllocations),
              "mode-specific memory regions overlap or escape storage");
static_assert(validMemoryViews(kIdleModeMemoryViews, kMemoryAllocations),
              "IDLE memory views overlap or exceed physical storage");
static_assert(validAcquisitionMemoryViews(kInputModeMemoryViews,
                                          kMemoryAllocations),
              "mode-specific memory views require aligned DMA-visible OCRAM");
static_assert(validAdcConverterConfigurations(kAdcConverterConfigurations),
              "ADC converter route is unsupported or conflicts");
static_assert(countOf(kAdcConverterConfigurations) == kLogicalAdcCount);
static_assert(kAdcConverterConfigurations[0].logical_converter == 0U);
static_assert(
    kAdcConverterConfigurations[0].teensy_adc_library_module == 0U);
static_assert(kAdcConverterConfigurations[0].teensy_pin == 14U);
static_assert(kAdcConverterConfigurations[0].input_pad ==
              AdcInputPad::kGpioAdB1_02);
static_assert(kAdcConverterConfigurations[0].adc_peripheral == 1U);
static_assert(kAdcConverterConfigurations[0].input_channel == 7U);
static_assert(kAdcConverterConfigurations[0].adc_etc_trigger == 0U);
static_assert(kAdcConverterConfigurations[0].xbar_input ==
              kXbarPitTrigger1Input);
static_assert(kAdcConverterConfigurations[0].xbar_output ==
              kXbarAdcEtcTrigger0Output);
static_assert(kAdcConverterConfigurations[0].edma_channel == 0U);
static_assert(kAdcConverterConfigurations[0].dmamux_source ==
              kDmamuxAdc1Source);
static_assert(kAdcConverterConfigurations[1].logical_converter == 1U);
static_assert(
    kAdcConverterConfigurations[1].teensy_adc_library_module == 1U);
static_assert(kAdcConverterConfigurations[1].teensy_pin == 15U);
static_assert(kAdcConverterConfigurations[1].input_pad ==
              AdcInputPad::kGpioAdB1_03);
static_assert(kAdcConverterConfigurations[1].adc_peripheral == 2U);
static_assert(kAdcConverterConfigurations[1].input_channel == 8U);
static_assert(kAdcConverterConfigurations[1].adc_etc_trigger == 4U);
static_assert(kAdcConverterConfigurations[1].xbar_input ==
              kXbarPitTrigger1Input);
static_assert(kAdcConverterConfigurations[1].xbar_output ==
              kXbarAdcEtcTrigger4Output);
static_assert(kAdcConverterConfigurations[1].edma_channel == 1U);
static_assert(kAdcConverterConfigurations[1].dmamux_source ==
              kDmamuxAdc2Source);
static_assert(kGpio2PsrCaptureMask == 0x00030C0FU,
              "GPIO2 capture and GPR27 masks must cover only D6-D13");
static_assert(kGpio7ToGpio2Gpr27ClearMask == kGpio2PsrCaptureMask,
              "GPIO2 direction/read and GPR27 selection masks disagree");
static_assert(kGpio1PsrCaptureMask == 0x0FC30000U,
              "GPIO1 capture and GPR26 masks must cover only D16-D23");
static_assert(kGpio6ToGpio1Gpr26ClearMask == kGpio1PsrCaptureMask,
              "GPIO1 direction/read and GPR26 selection masks disagree");
static_assert(validPitAllocations(kPitAllocations),
              "PIT channel allocation is unsupported or conflicts");
static_assert(validXbarRoutes(kXbarRoutes),
              "XBAR output allocation is unsupported or conflicts");
static_assert(validAdcEtcAllocations(kAdcEtcAllocations),
              "ADC_ETC allocation is unsupported or conflicts");
static_assert(validEdmaAllocations(kEdmaAllocations),
              "eDMA allocation is unsupported or conflicts");
static_assert(validEdmaPriorities(kAdcEdmaPriorities, kGpioEdmaPriority),
              "eDMA arbitration priorities must be unique");
static_assert(strictlyDescendingEdmaPriorities(kInputModeEdmaPriorities),
              "INPUT arbitration must be ADC0, ADC1, primary, auxiliary");
static_assert(validInterruptAllocations(kInterruptAllocations),
              "acquisition IRQ priorities are incomplete or unsafe");
static_assert(validMemoryAllocations(kMemoryAllocations),
              "memory allocations must be nonzero and alignment-safe");
static_assert(validMemoryViews(kInputModeMemoryViews, kMemoryAllocations),
              "INPUT memory regions overlap or exceed physical storage");
static_assert(validMemoryViews(kIdleModeMemoryViews, kMemoryAllocations),
              "IDLE memory views overlap or exceed physical storage");
static_assert(validAcquisitionMemoryRegions(kMemoryAllocations),
              "DMA/cache allocations use an unsafe region or alignment");
static_assert(kAcquisitionResourceContract.valid(),
              "combined acquisition resource contract is invalid");
static_assert(kReservedRam1Bytes <= kRam1BudgetBytes,
              "control queues exceed the RAM1 budget");
static_assert(kReservedRam2Bytes <= kRam2BudgetBytes,
              "future DMA queues exceed the RAM2 budget");
static_assert(kCommandParserCapacityBytes >=
                  protocol::kCommandParserStorageBytes,
              "parser must retain a full command and partial next magic");
static_assert(kUsbRxScratchBytes >= protocol_v1::kMaxCommandFrameBytes,
              "USB scratch must hold at least one maximum command");
static_assert(kUsbRxCallsPerLoop * kUsbRxScratchBytes >=
                  kUsbRxBudgetBytesPerLoop,
              "USB read-call bound must be able to reach its byte budget");
static_assert(kUsbTxCallsPerVisit > 0U && kUsbRxCallsPerLoop > 0U,
              "USB per-loop call budgets must be nonzero");
static_assert(kUsbTxVisitsPerLoop == 2U,
              "runtime interleaves exactly two TX and acquisition visits");
static_assert(kUsbTxBudgetBytesPerVisit <= kPinnedUsbCdcTxStorageBytes,
              "one cooperative TX visit must not outrun core TX storage");
static_assert(kUsbTxCallsPerVisit * kUsbTxMaxWriteBytes >=
                  kUsbTxBudgetBytesPerVisit,
              "USB write-call bound must be able to reach its byte budget");
static_assert(kPacketBufferStorageBytes % kCacheLineBytes == 0U,
              "packet storage must occupy complete alignment units");
static_assert(kAdcDmaBufferStrideBytes % kCacheLineBytes == 0U,
              "each ADC DMA buffer must occupy complete cache lines");
static_assert(kAdcDmaRingDepth >= 2U,
              "continuous paired ADC DMA needs two destinations");
static_assert(kAdcDmaPipelineDepth >= 4U,
              "paired ADC DMA needs bounded interrupt-coalescing headroom");
static_assert(kAdcDmaActivePipelineDepth >= 4U &&
              kAdcDmaActivePipelineDepth <= kAdcDmaPipelineDepth);
static_assert(kAdcDmaRingDepth >= kAdcDmaPipelineDepth + 2U,
              "ADC ring must retain two buffers beyond hardware look-ahead");
static_assert(kAdcDmaDescriptorCount >= 2U * kAdcDmaPipelineDepth,
              "ADC descriptor slots must not alias the live look-ahead");
static_assert(kAdcDmaDescriptorBytes % kCacheLineBytes == 0U,
              "ADC DMA descriptors must occupy complete cache lines");
static_assert(countOf(kAdcEdmaPriorities) == kLogicalAdcCount);
static_assert(kAdcEdmaIrqPriority < kGpioEdmaIrqPriority,
              "ADC completion/error IRQs must preempt GPIO completion");
static_assert(kGpioRawDmaBufferBytes % kCacheLineBytes == 0U,
              "each raw GPIO DMA buffer must occupy complete cache lines");
static_assert(kGpioRawDmaRingDepth >= 2U,
              "continuous GPIO DMA needs active and queued destinations");
static_assert(kGpioRawDmaDescriptorBytes % kCacheLineBytes == 0U,
              "GPIO DMA descriptors must occupy complete cache lines");
static_assert(kAuxGpioRawDmaDescriptorBytes % kCacheLineBytes == 0U,
              "auxiliary GPIO descriptors must occupy complete cache lines");
static_assert(kAuxInputWorkspaceBytes == 992U);
static_assert(kAuxInputWorkspaceBytes <= kChecksumBenchmarkBufferBytes,
              "INPUT state exceeds the IDLE-only OCRAM workspace");
static_assert(kPrimaryInputGpioRawDmaRingBytes +
                      kAuxGpioRawDmaRingBytes ==
                  kGpioRawDmaRingBytes,
              "INPUT raw rings must exactly overlay legacy raw storage");
static_assert(kGpioPackedBufferStrideBytes % kCacheLineBytes == 0U,
              "packed GPIO buffers must occupy complete cache lines");
static_assert(kInputGpioPackedBufferStrideBytes ==
                  kGpioPackedBufferStrideBytes,
              "16-bit INPUT packing must reuse the fixed packed ring");
static_assert(kGpioRawBuffersPerLoop > 0U &&
                  kGpioRawBuffersPerLoop <= kGpioRawDmaRingDepth,
              "GPIO packer input work must be nonzero and ring-bounded");
static_assert(kGpioPackedFramesPerLoop > 0U &&
                  kGpioPackedFramesPerLoop <= kGpioPackedRingDepth,
              "GPIO framing work must be nonzero and ring-bounded");
static_assert(kPacketBufferPrimaryStorageBytes +
                      kPacketBufferReserveStorageBytes ==
                  kPacketBufferStorageBytes,
              "packet storage banks must cover the complete pool");
static_assert(kChecksumBenchmarkBufferBytes % kCacheLineBytes == 0U,
              "benchmark buffers must occupy complete cache lines");
static_assert(kPacketReadyQueueDepth >= kPacketBufferCount &&
                  kPacketTransmitQueueDepth >= kPacketBufferCount,
              "packet index queues must be able to represent the whole pool");
static_assert(kPacketPipelineStateBudgetBytes >= kPacketIndexStorageBytes,
              "packet state budget must include ready/transmit indexes");
static_assert(kCombinedAcquisitionRam1BufferBytes <= kRam1BudgetBytes,
              "combined packet/packer buffers exceed RAM1");
static_assert(kCombinedAcquisitionRam2BufferBytes <= kRam2BudgetBytes,
              "combined DMA/packet buffers exceed RAM2");
static_assert(kCombinedAcquisitionAndUsbRam2BufferBytes <= kRam2BudgetBytes,
              "combined buffers plus the pinned USB TX ring exceed RAM2");
static_assert(kPacketPromotionsPerLoop > 0U &&
                  kPacketPromotionsPerLoop <= kPacketBufferCount,
              "packet promotion work must be nonzero and pool-bounded");
static_assert(sameBytes(kGpioPinsByBit, protocol_v1::kGpioPinsByBit),
              "resource registry and protocol GPIO maps disagree");
static_assert(sameBytes(kGpioPinsByBit,
                        protocol_v2::kPrimaryGpioPinsByBit));
static_assert(sameBytes(kAuxGpioPinsByBit,
                        protocol_v2::kAuxGpioPinsByBit));
static_assert(kGpio1PsrCaptureMask == protocol_v2::kAuxGpioCaptureMask);
static_assert(kGpioRawDmaRingDepth == protocol_v1::kGpioRawRingDepth);
static_assert(kGpioPackedRingDepth == protocol_v1::kGpioPackedRingDepth);
static_assert(kGpioRawDmaRingBytes == protocol_v1::kGpioRawRingBytes);
static_assert(kGpioPackedRingDepth * kGpioPackedBufferStrideBytes ==
              protocol_v1::kGpioPackedRingBytes);
static_assert(kPacketBufferCount == protocol_v1::kGpioPacketBufferCount);
static_assert(kAdcDmaRingDepth == protocol_v1::kAdcDmaRingDepth);
static_assert(protocol_v1::kDataPayloadBytes / protocol_v1::kAdcPairBytes ==
              protocol_v1::kAdcPairsPerBuffer);
static_assert(kAdcDmaRingBytes == protocol_v1::kAdcDmaRingBytes);
static_assert(kAdcConverterConfigurations[0].edma_channel ==
              protocol_v1::kAdcEdmaChannels[0]);
static_assert(kAdcConverterConfigurations[1].edma_channel ==
              protocol_v1::kAdcEdmaChannels[1]);
static_assert(kAdcEdmaPriorities[0] ==
                  protocol_v1::kAdcEdmaPriorities[0] &&
              kAdcEdmaPriorities[1] ==
                  protocol_v1::kAdcEdmaPriorities[1]);
static_assert(kAdcConverterConfigurations[0].dmamux_source ==
              protocol_v1::kAdcDmamuxSources[0]);
static_assert(kAdcConverterConfigurations[1].dmamux_source ==
              protocol_v1::kAdcDmamuxSources[1]);
static_assert(kAdcEdmaIrqPriority == protocol_v1::kAdcDmaIrqPriority);
static_assert(kGpioEdmaIrqPriority == protocol_v1::kGpioDmaIrqPriority);
static_assert(kPacketBufferCount == protocol_v1::kPacketBufferCount);
static_assert(kPacketBufferPrimaryCount == protocol_v1::kPacketPrimaryCount);
static_assert(kPacketBufferReserveCount == protocol_v1::kPacketReserveCount);
static_assert(kPacketReadyQueueDepth ==
              protocol_v1::kPacketReadyQueueCapacity);
static_assert(kPacketTransmitQueueDepth ==
              protocol_v1::kPacketTransmitQueueCapacity);
static_assert(kCommandQueueDepth == protocol_v1::kCommandQueueCapacity);
static_assert(kResponseQueueDepth == protocol_v1::kResponseQueueCapacity);
static_assert(kGpioPitChannel == protocol_v1::kGpioPitChannel);
static_assert(kGpioXbarInput == protocol_v1::kGpioXbarInput);
static_assert(kGpioXbarOutput == protocol_v1::kGpioXbarOutput);
static_assert(kGpioXbarActiveEdge == protocol_v1::kGpioXbarActiveEdge);
static_assert(kGpioEdmaChannel == protocol_v1::kGpioEdmaChannel);
static_assert(kGpioDmamuxSource == protocol_v1::kGpioDmamuxSource);
static_assert(kGpioEdmaPriority == protocol_v1::kGpioEdmaPriority);
static_assert(kAuxGpioXbarInput == kGpioXbarInput);
static_assert(kAuxGpioXbarOutput == protocol_v2::kAuxGpioXbarOutput);
static_assert(kAuxGpioEdmaChannel == protocol_v2::kAuxGpioEdmaChannel);
static_assert(kAuxGpioDmamuxSource == protocol_v2::kAuxGpioDmamuxSource);
static_assert(kAuxGpioRawDmaRingDepth ==
              protocol_v2::kAuxGpioRawRingDepth);
static_assert(kInputModeEdmaPriorities[0] == 3U &&
              kInputModeEdmaPriorities[1] == 2U &&
              kInputModeEdmaPriorities[2] == 1U &&
              kInputModeEdmaPriorities[3] == 0U);
static_assert(kGpioXbarSelectionRegister ==
              kAuxGpioXbarSelectionRegister);
static_assert((kGpioXbarSelectionMask & kAuxGpioXbarSelectionMask) == 0U);
static_assert(kPairedGpioXbarSelectionMask == 0xFFFFU);
static_assert(xbarSelectionMask(kGpioXbarOutput) ==
              kGpioXbarSelectionMask);
static_assert(xbarSelectionMask(kAuxGpioXbarOutput) ==
              kAuxGpioXbarSelectionMask);
static_assert(replaceXbarSelection(0xA500U, kGpioXbarOutput,
                                  kGpioXbarInput) == 0xA538U);
static_assert(replaceXbarSelection(0x00A5U, kAuxGpioXbarOutput,
                                  kAuxGpioXbarInput) == 0x38A5U);
static_assert(kGpioPitChannel ==
              protocol_v1::kAdcTriggerGpioMasterPitChannel);
static_assert(kPitAllocations[1].channel ==
              protocol_v1::kAdcTriggerPairPitChannel);
static_assert(kAdcConverterConfigurations[0].input_channel ==
              protocol_v1::kAdcChannels[0]);
static_assert(kAdcConverterConfigurations[1].input_channel ==
              protocol_v1::kAdcChannels[1]);
static_assert(kAdcConverterConfigurations[0].adc_etc_trigger ==
              protocol_v1::kAdcTriggerQueues[0]);
static_assert(kAdcConverterConfigurations[1].adc_etc_trigger ==
              protocol_v1::kAdcTriggerQueues[1]);
static_assert(kAdcConverterConfigurations[0].xbar_input ==
              protocol_v1::kAdcTriggerXbarInputs[0]);
static_assert(kAdcConverterConfigurations[1].xbar_input ==
              protocol_v1::kAdcTriggerXbarInputs[1]);
static_assert(kAdcConverterConfigurations[0].xbar_output ==
              protocol_v1::kAdcTriggerXbarOutputs[0]);
static_assert(kAdcConverterConfigurations[1].xbar_output ==
              protocol_v1::kAdcTriggerXbarOutputs[1]);

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
static_assert(kTeensy40DigitalPinCount == CORE_NUM_DIGITAL);
static_assert(kAdc0Pin == A0);
static_assert(kAdc1Pin == A1);
static_assert(kGpioMappingsByPackedBit[0].gpio2_bit == CORE_PIN6_BIT);
static_assert(kGpioMappingsByPackedBit[1].gpio2_bit == CORE_PIN7_BIT);
static_assert(kGpioMappingsByPackedBit[2].gpio2_bit == CORE_PIN8_BIT);
static_assert(kGpioMappingsByPackedBit[3].gpio2_bit == CORE_PIN9_BIT);
static_assert(kGpioMappingsByPackedBit[4].gpio2_bit == CORE_PIN10_BIT);
static_assert(kGpioMappingsByPackedBit[5].gpio2_bit == CORE_PIN11_BIT);
static_assert(kGpioMappingsByPackedBit[6].gpio2_bit == CORE_PIN12_BIT);
static_assert(kGpioMappingsByPackedBit[7].gpio2_bit == CORE_PIN13_BIT);
static_assert(kAuxGpioMappingsByPackedBit[0].gpio2_bit == CORE_PIN16_BIT);
static_assert(kAuxGpioMappingsByPackedBit[1].gpio2_bit == CORE_PIN17_BIT);
static_assert(kAuxGpioMappingsByPackedBit[2].gpio2_bit == CORE_PIN18_BIT);
static_assert(kAuxGpioMappingsByPackedBit[3].gpio2_bit == CORE_PIN19_BIT);
static_assert(kAuxGpioMappingsByPackedBit[4].gpio2_bit == CORE_PIN20_BIT);
static_assert(kAuxGpioMappingsByPackedBit[5].gpio2_bit == CORE_PIN21_BIT);
static_assert(kAuxGpioMappingsByPackedBit[6].gpio2_bit == CORE_PIN22_BIT);
static_assert(kAuxGpioMappingsByPackedBit[7].gpio2_bit == CORE_PIN23_BIT);
static_assert(kGpio2PsrCaptureMask ==
              static_cast<std::uint32_t>(
                  CORE_PIN6_BITMASK | CORE_PIN7_BITMASK |
                  CORE_PIN8_BITMASK | CORE_PIN9_BITMASK |
                  CORE_PIN10_BITMASK | CORE_PIN11_BITMASK |
                  CORE_PIN12_BITMASK | CORE_PIN13_BITMASK));
static_assert(kGpio1PsrCaptureMask ==
              static_cast<std::uint32_t>(
                  CORE_PIN16_BITMASK | CORE_PIN17_BITMASK |
                  CORE_PIN18_BITMASK | CORE_PIN19_BITMASK |
                  CORE_PIN20_BITMASK | CORE_PIN21_BITMASK |
                  CORE_PIN22_BITMASK | CORE_PIN23_BITMASK));
static_assert(kXbarPitTrigger0Input == XBARA1_IN_PIT_TRIGGER0);
static_assert(kXbarPitTrigger1Input == XBARA1_IN_PIT_TRIGGER1);
static_assert(kXbarPitTrigger2Input == XBARA1_IN_PIT_TRIGGER2);
static_assert(kXbarPitTrigger3Input == XBARA1_IN_PIT_TRIGGER3);
static_assert(kXbarDmaRequest30Output == XBARA1_OUT_DMA_CH_MUX_REQ30);
static_assert(kXbarDmaRequest31Output == XBARA1_OUT_DMA_CH_MUX_REQ31);
static_assert(kXbarDmaRequest94Output == XBARA1_OUT_DMA_CH_MUX_REQ94);
static_assert(kXbarDmaRequest95Output == XBARA1_OUT_DMA_CH_MUX_REQ95);
static_assert(kXbarAdcEtcTrigger0Output == XBARA1_OUT_ADC_ETC_TRIG00);
static_assert(kXbarAdcEtcTrigger4Output == XBARA1_OUT_ADC_ETC_TRIG10);
static_assert(kDmamuxAdc1Source == DMAMUX_SOURCE_ADC1);
static_assert(kDmamuxAdc2Source == DMAMUX_SOURCE_ADC2);
static_assert(kDmamuxXbar1Request0Source == DMAMUX_SOURCE_XBAR1_0);
static_assert(kDmamuxXbar1Request1Source == DMAMUX_SOURCE_XBAR1_1);
static_assert(kDmamuxXbar1Request2Source == DMAMUX_SOURCE_XBAR1_2);
static_assert(kDmamuxXbar1Request3Source == DMAMUX_SOURCE_XBAR1_3);
static_assert(kIrqDmaChannel0 == IRQ_DMA_CH0);
static_assert(kIrqDmaChannel1 == IRQ_DMA_CH1);
static_assert(kIrqDmaChannel2 == IRQ_DMA_CH2);
static_assert(kIrqDmaChannel3 == IRQ_DMA_CH3);
static_assert(kIrqAdcEtcError == IRQ_ADC_ETC_ERR);
#endif

}  // namespace thingdaq::board
