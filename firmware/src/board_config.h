#pragma once

#include <cstddef>
#include <cstdint>

#if defined(ARDUINO) &&                                                   \
    (!defined(ARDUINO_TEENSY40) || !defined(__IMXRT1062__))
#error "Teensy DAQ board resources require Teensy 4.0 / i.MX RT1062"
#endif

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
#include <core_pins.h>
#include <imxrt.h>
#endif

#include "generated/protocol_constants.h"
#include "protocol.h"

namespace teensy_daq::board {

enum class ResourceOwner : std::uint8_t {
  kControlPlane,
  kAcquisitionClock,
  kAdcCapture,
  kAdc0Capture,
  kAdc1Capture,
  kGpioCapture,
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
  kGpioRawDmaRing,
  kGpioPackedRing,
  kGpioClockDiagnosticSink,
  kChecksumBenchmarkDtcmBuffer,
  kChecksumBenchmarkOcramBuffer,
};

struct PinAllocation {
  std::uint8_t pin;
  ResourceOwner owner;
};

struct GpioPinMapping {
  std::uint8_t teensy_pin;
  std::uint8_t gpio2_bit;
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

inline constexpr std::uint8_t kTeensy40DigitalPinCount = 40U;
inline constexpr std::uint8_t kPitChannelCount = 4U;
inline constexpr std::uint8_t kXbarInputCount = 132U;
inline constexpr std::uint8_t kXbarOutputCount = 132U;
inline constexpr std::uint8_t kAdcEtcTriggerCount = 8U;
inline constexpr std::uint8_t kAdcPeripheralCount = 2U;
inline constexpr std::uint8_t kEdmaChannelCount = 32U;
inline constexpr std::uint8_t kDmamuxSourceCount = 128U;
inline constexpr std::uint8_t kGpioPortBitCount = 32U;
inline constexpr std::size_t kCacheLineBytes = 32U;
inline constexpr std::size_t kRam1BudgetBytes = 512U * 1024U;
inline constexpr std::size_t kRam2BudgetBytes = 512U * 1024U;

// Teensy 4.0 A0/A1 are digital pins 14/15. Logical ADC0 is NXP ADC1 and
// logical ADC1 is NXP ADC2; keeping both names here avoids future off-by-one
// mistakes at the register boundary.
inline constexpr std::uint8_t kAdc0Pin = 14U;
inline constexpr std::uint8_t kAdc1Pin = 15U;
inline constexpr std::uint8_t kAdc0Peripheral = 1U;
inline constexpr std::uint8_t kAdc1Peripheral = 2U;
inline constexpr std::uint8_t kGpioPinsByBit[] = {6U, 7U, 8U, 9U,
                                                  10U, 11U, 12U, 13U};
// Array order is the packed wire bit. Teensy startup selects the GPIO7 fast
// aliases for these pads; clearing the same-numbered GPR27 bits selects the
// DMA-visible GPIO2 aliases without changing any unrelated pin.
inline constexpr GpioPinMapping kGpioMappingsByPackedBit[] = {
    {6U, 10U}, {7U, 17U}, {8U, 16U}, {9U, 11U},
    {10U, 0U}, {11U, 2U}, {12U, 1U}, {13U, 3U},
};
inline constexpr std::uint32_t kGpio2PsrCaptureMask =
    (std::uint32_t{1U} << 10U) | (std::uint32_t{1U} << 17U) |
    (std::uint32_t{1U} << 16U) | (std::uint32_t{1U} << 11U) |
    (std::uint32_t{1U} << 0U) | (std::uint32_t{1U} << 2U) |
    (std::uint32_t{1U} << 1U) | (std::uint32_t{1U} << 3U);
inline constexpr std::uint32_t kGpio7ToGpio2Gpr27ClearMask =
    kGpio2PsrCaptureMask;
inline constexpr std::uint8_t kGpioPitChannel = 0U;
inline constexpr std::uint8_t kGpioEdmaChannel = 2U;
inline constexpr std::uint8_t kGpioEdmaPriority = 2U;

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
};

// PIT0 is the exact 4 MHz GPIO master. PIT1 is chained down to the proposed
// 1 MHz ADC-pair event. These are reservations, not a claim that the Phase 04
// CPU-generated synthetic source enables either timer.
inline constexpr PitAllocation kPitAllocations[] = {
    {kGpioPitChannel, ResourceOwner::kGpioCapture},
    {1U, ResourceOwner::kAcquisitionClock},
};

// Numeric identities come from the pinned core's imxrt.h. PIT1 fans out to two
// ADC_ETC outputs by design; XBAR outputs, rather than inputs, must be unique.
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
// The PIT trigger is a periodic transition source. Detect one rising edge per
// period; the inherited dual-edge setting over-counted at 4 MHz on silicon.
inline constexpr std::uint8_t kGpioXbarInput = kXbarPitTrigger0Input;
inline constexpr std::uint8_t kGpioXbarOutput = kXbarDmaRequest30Output;
inline constexpr std::uint8_t kGpioXbarActiveEdge = 1U;
inline constexpr XbarRoute kXbarRoutes[] = {
    {kGpioXbarInput, kGpioXbarOutput, ResourceOwner::kGpioCapture},
    {kXbarPitTrigger1Input, kXbarAdcEtcTrigger0Output,
     ResourceOwner::kAdc0Capture},
    {kXbarPitTrigger1Input, kXbarAdcEtcTrigger4Output,
     ResourceOwner::kAdc1Capture},
};

inline constexpr AdcEtcAllocation kAdcEtcAllocations[] = {
    {0U, kAdc0Peripheral, ResourceOwner::kAdc0Capture},
    {4U, kAdc1Peripheral, ResourceOwner::kAdc1Capture},
};

inline constexpr std::uint8_t kDmamuxAdc1Source = 24U;
inline constexpr std::uint8_t kDmamuxXbar1Request0Source = 30U;
inline constexpr std::uint8_t kDmamuxXbar1Request1Source = 31U;
inline constexpr std::uint8_t kDmamuxXbar1Request2Source = 94U;
inline constexpr std::uint8_t kDmamuxXbar1Request3Source = 95U;
inline constexpr std::uint8_t kDmamuxAdc2Source = 88U;
inline constexpr std::uint8_t kGpioDmamuxSource =
    kDmamuxXbar1Request0Source;
inline constexpr EdmaAllocation kEdmaAllocations[] = {
    {0U, kDmamuxAdc1Source, ResourceOwner::kAdc0Capture},
    {1U, kDmamuxAdc2Source, ResourceOwner::kAdc1Capture},
    {kGpioEdmaChannel, kGpioDmamuxSource, ResourceOwner::kGpioCapture},
};

inline constexpr std::size_t kCommandParserCapacityBytes = 64U;
inline constexpr std::size_t kUsbRxScratchBytes = 128U;
inline constexpr std::size_t kCommandQueueDepth = 4U;
inline constexpr std::size_t kResponseQueueDepth = 4U;
inline constexpr std::size_t kAdcDmaRingDepth = 4U;
inline constexpr std::size_t kGpioRawDmaRingDepth = 4U;
inline constexpr std::size_t kGpioPackedRingDepth = 4U;
// At the nominal combined framed rate, each 4096-byte buffer represents 0.506
// ms. Keep the proven 106-frame primary bank in cacheless DTCM, then add a
// fixed 94-frame CPU-owned OCRAM reserve. The complete 200-frame pool retains
// 101.200 ms and the pinned core contributes another 1.012 ms in four 2048-byte
// TX buffers. This covers the 60.715 ms Phase 05 service gap while retaining at
// least 32 KiB of target RAM1 for locals/stack and every future DMA-ring budget.
inline constexpr std::size_t kPacketBufferPrimaryCount = 106U;
inline constexpr std::size_t kPacketBufferReserveCount = 94U;
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
inline constexpr std::size_t kUsbTxBudgetBytesPerLoop = 2048U;
// Data is offered to the pinned core in one core-buffer-sized block whenever
// possible. A visit waits for at least one high-speed USB packet of capacity
// instead of deliberately degrading into byte-at-a-time calls. Unexpected
// backend prefixes are still retained and resumed exactly.
inline constexpr std::size_t kUsbTxMaxWriteBytes =
    kPinnedUsbCdcTxBufferBytes;
inline constexpr std::size_t kUsbTxMinimumWriteBytes = 512U;
inline constexpr std::size_t kUsbRxCallsPerLoop = 8U;
inline constexpr std::size_t kUsbTxCallsPerLoop = 8U;

constexpr std::size_t alignUp(std::size_t value, std::size_t alignment) {
  return ((value + alignment - 1U) / alignment) * alignment;
}

inline constexpr std::size_t kAdcDmaBufferStrideBytes =
    alignUp(protocol_v1::kDataPayloadBytes, kCacheLineBytes);
inline constexpr std::size_t kGpioRawDmaBufferBytes =
    protocol_v1::kGpioSamplesPerFrame * sizeof(std::uint32_t);
inline constexpr std::size_t kGpioPackedBufferStrideBytes =
    alignUp(protocol_v1::kDataPayloadBytes, kCacheLineBytes);
inline constexpr std::size_t kPacketBufferStorageBytes =
    kPacketBufferCount * protocol_v1::kDataFrameBytes;
inline constexpr std::size_t kPacketBufferPrimaryStorageBytes =
    kPacketBufferPrimaryCount * protocol_v1::kDataFrameBytes;
inline constexpr std::size_t kPacketBufferReserveStorageBytes =
    kPacketBufferReserveCount * protocol_v1::kDataFrameBytes;

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
    {MemoryUse::kChecksumBenchmarkDtcmBuffer, MemoryRegion::kDtcmRam1,
     kChecksumBenchmarkBufferBytes, kCacheLineBytes,
     ResourceOwner::kChecksumBenchmark},
    {MemoryUse::kAdcDmaRing, MemoryRegion::kOcramRam2Dma,
     kAdcDmaRingDepth * kAdcDmaBufferStrideBytes, kCacheLineBytes,
     ResourceOwner::kAdcCapture},
    {MemoryUse::kGpioRawDmaRing, MemoryRegion::kOcramRam2Dma,
     kGpioRawDmaRingDepth * kGpioRawDmaBufferBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kGpioPackedRing, MemoryRegion::kOcramRam2Dma,
     kGpioPackedRingDepth * kGpioPackedBufferStrideBytes, kCacheLineBytes,
     ResourceOwner::kGpioPacker},
    {MemoryUse::kGpioClockDiagnosticSink, MemoryRegion::kOcramRam2Dma,
     kGpioClockDiagnosticSinkBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kChecksumBenchmarkOcramBuffer,
     MemoryRegion::kOcramRam2Dma, kChecksumBenchmarkBufferBytes,
     kCacheLineBytes, ResourceOwner::kChecksumBenchmark},
};

template <typename T, std::size_t N>
constexpr std::size_t countOf(const T (&)[N]) {
  return N;
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
      if (routes[left].output == routes[right].output) {
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

static_assert(validPins(kPinAllocations),
              "pin allocation is unsupported or conflicts");
static_assert(validGpioPinMappings(kGpioMappingsByPackedBit),
              "GPIO map is unsupported or contains duplicate pins/bits");
static_assert(gpioPinOrderMatches(kGpioMappingsByPackedBit, kGpioPinsByBit),
              "GPIO resource map and packed pin order disagree");
static_assert(kGpio2PsrCaptureMask == 0x00030C0FU,
              "GPIO2 capture and GPR27 masks must cover only D6-D13");
static_assert(kGpio7ToGpio2Gpr27ClearMask == kGpio2PsrCaptureMask,
              "GPIO2 direction/read and GPR27 selection masks disagree");
static_assert(validPitAllocations(kPitAllocations),
              "PIT channel allocation is unsupported or conflicts");
static_assert(validXbarRoutes(kXbarRoutes),
              "XBAR output allocation is unsupported or conflicts");
static_assert(validAdcEtcAllocations(kAdcEtcAllocations),
              "ADC_ETC allocation is unsupported or conflicts");
static_assert(validEdmaAllocations(kEdmaAllocations),
              "eDMA allocation is unsupported or conflicts");
static_assert(validMemoryAllocations(kMemoryAllocations),
              "memory allocations must be nonzero and alignment-safe");
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
static_assert(kUsbTxCallsPerLoop > 0U && kUsbRxCallsPerLoop > 0U,
              "USB per-loop call budgets must be nonzero");
static_assert(kUsbTxBudgetBytesPerLoop <= kPinnedUsbCdcTxBufferBytes,
              "one cooperative TX visit must not outrun a core TX buffer");
static_assert(kPacketBufferStorageBytes % kCacheLineBytes == 0U,
              "packet storage must occupy complete alignment units");
static_assert(kPacketBufferPrimaryStorageBytes +
                      kPacketBufferReserveStorageBytes ==
                  kPacketBufferStorageBytes,
              "packet storage banks must cover the complete pool");
static_assert(kChecksumBenchmarkBufferBytes % kCacheLineBytes == 0U,
              "benchmark buffers must occupy complete cache lines");
static_assert(kPacketReadyQueueDepth >= kPacketBufferCount &&
                  kPacketTransmitQueueDepth >= kPacketBufferCount,
              "packet index queues must be able to represent the whole pool");
static_assert(kPacketPromotionsPerLoop > 0U &&
                  kPacketPromotionsPerLoop <= kPacketBufferCount,
              "packet promotion work must be nonzero and pool-bounded");
static_assert(sameBytes(kGpioPinsByBit, protocol_v1::kGpioPinsByBit),
              "resource registry and protocol GPIO maps disagree");

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
static_assert(kGpio2PsrCaptureMask ==
              static_cast<std::uint32_t>(
                  CORE_PIN6_BITMASK | CORE_PIN7_BITMASK |
                  CORE_PIN8_BITMASK | CORE_PIN9_BITMASK |
                  CORE_PIN10_BITMASK | CORE_PIN11_BITMASK |
                  CORE_PIN12_BITMASK | CORE_PIN13_BITMASK));
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
#endif

}  // namespace teensy_daq::board
