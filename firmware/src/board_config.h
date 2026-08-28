#pragma once

#include <cstddef>
#include <cstdint>

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
  kAdcDmaRing,
  kGpioRawDmaRing,
  kGpioPackedRing,
  kDataTransmitQueue,
};

struct PinAllocation {
  std::uint8_t pin;
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

inline constexpr std::uint8_t kTeensy40DigitalPinCount = 40U;
inline constexpr std::uint8_t kPitChannelCount = 4U;
inline constexpr std::uint8_t kXbarInputCount = 132U;
inline constexpr std::uint8_t kXbarOutputCount = 132U;
inline constexpr std::uint8_t kAdcEtcTriggerCount = 8U;
inline constexpr std::uint8_t kAdcPeripheralCount = 2U;
inline constexpr std::uint8_t kEdmaChannelCount = 32U;
inline constexpr std::uint8_t kDmamuxSourceCount = 128U;
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

// PIT0 is the proposed exact 4 MHz GPIO master. PIT1 is chained down to the
// proposed 1 MHz ADC-pair event. These are reservations, not a claim that the
// Phase 03 control-only firmware enables either timer.
inline constexpr PitAllocation kPitAllocations[] = {
    {0U, ResourceOwner::kGpioCapture},
    {1U, ResourceOwner::kAcquisitionClock},
};

// Numeric identities come from the pinned core's imxrt.h. PIT1 fans out to two
// ADC_ETC outputs by design; XBAR outputs, rather than inputs, must be unique.
inline constexpr std::uint8_t kXbarPitTrigger0Input = 56U;
inline constexpr std::uint8_t kXbarPitTrigger1Input = 57U;
inline constexpr std::uint8_t kXbarDmaRequest30Output = 0U;
inline constexpr std::uint8_t kXbarAdcEtcTrigger0Output = 103U;
inline constexpr std::uint8_t kXbarAdcEtcTrigger4Output = 107U;
inline constexpr XbarRoute kXbarRoutes[] = {
    {kXbarPitTrigger0Input, kXbarDmaRequest30Output,
     ResourceOwner::kGpioCapture},
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
inline constexpr std::uint8_t kDmamuxAdc2Source = 88U;
inline constexpr EdmaAllocation kEdmaAllocations[] = {
    {0U, kDmamuxAdc1Source, ResourceOwner::kAdc0Capture},
    {1U, kDmamuxAdc2Source, ResourceOwner::kAdc1Capture},
    {2U, kDmamuxXbar1Request0Source, ResourceOwner::kGpioCapture},
};

inline constexpr std::size_t kCommandParserCapacityBytes = 64U;
inline constexpr std::size_t kUsbRxScratchBytes = 128U;
inline constexpr std::size_t kCommandQueueDepth = 4U;
inline constexpr std::size_t kResponseQueueDepth = 4U;
inline constexpr std::size_t kAdcDmaRingDepth = 4U;
inline constexpr std::size_t kGpioRawDmaRingDepth = 4U;
inline constexpr std::size_t kGpioPackedRingDepth = 4U;
inline constexpr std::size_t kDataTransmitQueueDepth = 4U;
inline constexpr std::size_t kUsbRxBudgetBytesPerLoop = 1024U;
inline constexpr std::size_t kUsbTxBudgetBytesPerLoop = 2048U;
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
    {MemoryUse::kAdcDmaRing, MemoryRegion::kOcramRam2Dma,
     kAdcDmaRingDepth * kAdcDmaBufferStrideBytes, kCacheLineBytes,
     ResourceOwner::kAdcCapture},
    {MemoryUse::kGpioRawDmaRing, MemoryRegion::kOcramRam2Dma,
     kGpioRawDmaRingDepth * kGpioRawDmaBufferBytes, kCacheLineBytes,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kGpioPackedRing, MemoryRegion::kOcramRam2Dma,
     kGpioPackedRingDepth * kGpioPackedBufferStrideBytes, kCacheLineBytes,
     ResourceOwner::kGpioPacker},
    {MemoryUse::kDataTransmitQueue, MemoryRegion::kOcramRam2Dma,
     kDataTransmitQueueDepth * protocol_v1::kDataFrameBytes, kCacheLineBytes,
     ResourceOwner::kPacketizer},
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
static_assert(sameBytes(kGpioPinsByBit, protocol_v1::kGpioPinsByBit),
              "resource registry and protocol GPIO maps disagree");

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)
static_assert(kTeensy40DigitalPinCount == CORE_NUM_DIGITAL);
static_assert(kAdc0Pin == A0);
static_assert(kAdc1Pin == A1);
static_assert(kXbarPitTrigger0Input == XBARA1_IN_PIT_TRIGGER0);
static_assert(kXbarPitTrigger1Input == XBARA1_IN_PIT_TRIGGER1);
static_assert(kXbarDmaRequest30Output == XBARA1_OUT_DMA_CH_MUX_REQ30);
static_assert(kXbarAdcEtcTrigger0Output == XBARA1_OUT_ADC_ETC_TRIG00);
static_assert(kXbarAdcEtcTrigger4Output == XBARA1_OUT_ADC_ETC_TRIG10);
static_assert(kDmamuxAdc1Source == DMAMUX_SOURCE_ADC1);
static_assert(kDmamuxAdc2Source == DMAMUX_SOURCE_ADC2);
static_assert(kDmamuxXbar1Request0Source == DMAMUX_SOURCE_XBAR1_0);
#endif

}  // namespace teensy_daq::board
