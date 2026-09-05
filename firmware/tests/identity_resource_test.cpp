#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "control_state.h"
#include "firmware_capabilities.h"
#include "firmware_identity.h"

namespace {

using thingdaq::board::AdcConverterConfiguration;
using thingdaq::board::AdcEtcAllocation;
using thingdaq::board::AdcInputPad;
using thingdaq::board::EdmaAllocation;
using thingdaq::board::GpioPinMapping;
using thingdaq::board::GpioBitAllocation;
using thingdaq::board::InterruptAllocation;
using thingdaq::board::InterruptUse;
using thingdaq::board::MemoryAllocation;
using thingdaq::board::MemoryRegion;
using thingdaq::board::MemoryUse;
using thingdaq::board::MemoryViewAllocation;
using thingdaq::board::PinAllocation;
using thingdaq::board::PitAllocation;
using thingdaq::board::ResourceOwner;
using thingdaq::board::XbarRoute;

constexpr PinAllocation kConflictingPins[] = {
    {6U, ResourceOwner::kGpioCapture},
    {6U, ResourceOwner::kAdc0Capture},
};
constexpr PinAllocation kOutOfRangePin[] = {
    {thingdaq::board::kTeensy40DigitalPinCount,
     ResourceOwner::kGpioCapture},
};
constexpr std::uint8_t kAuxOwnerPins[] = {16U, 17U};
constexpr PinAllocation kSplitAuxPinOwners[] = {
    {16U, ResourceOwner::kAuxGpioCapture},
    {17U, ResourceOwner::kGpioCapture},
};
constexpr GpioPinMapping kDuplicateGpioBit[] = {
    {6U, 10U},
    {7U, 10U},
};
constexpr GpioPinMapping kOutOfRangeGpioBit[] = {
    {6U, thingdaq::board::kGpioPortBitCount},
};
constexpr GpioPinMapping kWrongGpioPinOrder[] = {
    {7U, 17U},
    {6U, 10U},
    {8U, 16U},
    {9U, 11U},
    {10U, 0U},
    {11U, 2U},
    {12U, 1U},
    {13U, 3U},
};
constexpr GpioBitAllocation kDuplicatePortBit[] = {
    {2U, 17U, ResourceOwner::kGpioCapture},
    {2U, 17U, ResourceOwner::kAuxGpioCapture},
};
constexpr GpioBitAllocation kSameBitDifferentPorts[] = {
    {2U, 17U, ResourceOwner::kGpioCapture},
    {1U, 17U, ResourceOwner::kAuxGpioCapture},
};
constexpr AdcConverterConfiguration kIncompleteAdcConfiguration[] = {
    {0U, 0U, 14U, AdcInputPad::kGpioAdB1_02, 1U, 7U, 0U, 57U,
     103U, 0U, 24U, ResourceOwner::kAdc0Capture},
};
constexpr AdcConverterConfiguration kWrongAdcQueue[] = {
    {0U, 0U, 14U, AdcInputPad::kGpioAdB1_02, 1U, 7U, 4U, 57U,
     103U, 0U, 24U, ResourceOwner::kAdc0Capture},
    {1U, 1U, 15U, AdcInputPad::kGpioAdB1_03, 2U, 8U, 0U, 57U,
     107U, 1U, 88U, ResourceOwner::kAdc1Capture},
};
constexpr AdcConverterConfiguration kConflictingAdcDma[] = {
    {0U, 0U, 14U, AdcInputPad::kGpioAdB1_02, 1U, 7U, 0U, 57U,
     103U, 0U, 24U, ResourceOwner::kAdc0Capture},
    {1U, 1U, 15U, AdcInputPad::kGpioAdB1_03, 2U, 8U, 4U, 57U,
     107U, 0U, 88U, ResourceOwner::kAdc1Capture},
};
constexpr PitAllocation kConflictingPit[] = {
    {1U, ResourceOwner::kAcquisitionClock},
    {1U, ResourceOwner::kGpioCapture},
};
constexpr PitAllocation kOutOfRangePit[] = {
    {thingdaq::board::kPitChannelCount,
     ResourceOwner::kAcquisitionClock},
};
constexpr XbarRoute kConflictingXbar[] = {
    {56U, 103U, ResourceOwner::kAdc0Capture},
    {57U, 103U, ResourceOwner::kAdc1Capture},
};
constexpr XbarRoute kOutOfRangeXbar[] = {
    {thingdaq::board::kXbarInputCount, 0U,
     ResourceOwner::kAcquisitionClock},
};
constexpr AdcEtcAllocation kConflictingAdcEtc[] = {
    {0U, 1U, ResourceOwner::kAdc0Capture},
    {0U, 2U, ResourceOwner::kAdc1Capture},
};
constexpr AdcEtcAllocation kOutOfRangeAdcEtc[] = {
    {thingdaq::board::kAdcEtcTriggerCount, 1U,
     ResourceOwner::kAdc0Capture},
};
constexpr EdmaAllocation kInvalidEdma[] = {
    {0U, 24U, ResourceOwner::kAdc0Capture},
    {0U, 88U, ResourceOwner::kAdc1Capture},
};
constexpr EdmaAllocation kOutOfRangeEdma[] = {
    {thingdaq::board::kEdmaChannelCount, 24U,
     ResourceOwner::kAdc0Capture},
};
constexpr std::uint8_t kConflictingEdmaPriorities[] = {0U, 2U};
constexpr MemoryAllocation kConflictingMemory[] = {
    {MemoryUse::kCommandParser, MemoryRegion::kDtcmRam1, 64U, 4U,
     ResourceOwner::kControlPlane},
    {MemoryUse::kCommandParser, MemoryRegion::kDtcmRam1, 128U, 4U,
     ResourceOwner::kControlPlane},
};
constexpr MemoryAllocation kMisalignedMemory[] = {
    {MemoryUse::kAdcDmaRing, MemoryRegion::kOcramRam2Dma, 33U, 32U,
     ResourceOwner::kAdcCapture},
};
constexpr MemoryAllocation kInvalidAlignment[] = {
    {MemoryUse::kGpioRawDmaRing, MemoryRegion::kOcramRam2Dma, 96U, 3U,
     ResourceOwner::kGpioCapture},
};
constexpr MemoryAllocation kDmaRingInDtcm[] = {
    {MemoryUse::kAdcDmaRing, MemoryRegion::kDtcmRam1, 64U, 32U,
     ResourceOwner::kAdcCapture},
};
constexpr MemoryAllocation kCacheUnsafePackedRing[] = {
    {MemoryUse::kGpioPackedRing, MemoryRegion::kOcramRam2Dma, 64U, 16U,
     ResourceOwner::kGpioPacker},
};
constexpr InterruptAllocation kDuplicateInterruptUse[] = {
    {InterruptUse::kAdc0DmaCompletion, 0U, 16U, 48U,
     ResourceOwner::kAdc0Capture},
    {InterruptUse::kAdc0DmaCompletion, 1U, 17U, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 121U, 137U, 48U,
     ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 2U, 18U, 64U,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAuxGpioDmaCompletion, 3U, 19U, 64U,
     ResourceOwner::kAuxGpioCapture},
};
constexpr InterruptAllocation kUnsafeInterruptPriority[] = {
    {InterruptUse::kAdc0DmaCompletion, 0U, 16U, 48U,
     ResourceOwner::kAdc0Capture},
    {InterruptUse::kAdc1DmaCompletion, 1U, 17U, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 121U, 137U, 48U,
     ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 2U, 18U, 40U,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAuxGpioDmaCompletion, 3U, 19U, 64U,
     ResourceOwner::kAuxGpioCapture},
};
constexpr InterruptAllocation kWrongInterruptOwner[] = {
    {InterruptUse::kAdc0DmaCompletion, 0U, 16U, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdc1DmaCompletion, 1U, 17U, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 121U, 137U, 48U,
     ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 2U, 18U, 64U,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAuxGpioDmaCompletion, 3U, 19U, 64U,
     ResourceOwner::kAuxGpioCapture},
};
constexpr InterruptAllocation kReorderedInterrupts[] = {
    {InterruptUse::kAuxGpioDmaCompletion, 3U, 19U, 64U,
     ResourceOwner::kAuxGpioCapture},
    {InterruptUse::kGpioDmaCompletion, 2U, 18U, 64U,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAdcEtcError, 121U, 137U, 48U,
     ResourceOwner::kAdcCapture},
    {InterruptUse::kAdc1DmaCompletion, 1U, 17U, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdc0DmaCompletion, 0U, 16U, 48U,
     ResourceOwner::kAdc0Capture},
};
constexpr InterruptAllocation kDuplicateInterruptVector[] = {
    {InterruptUse::kAdc0DmaCompletion, 0U, 16U, 48U,
     ResourceOwner::kAdc0Capture},
    {InterruptUse::kAdc1DmaCompletion, 1U, 16U, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 121U, 137U, 48U,
     ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 2U, 18U, 64U,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAuxGpioDmaCompletion, 3U, 19U, 64U,
     ResourceOwner::kAuxGpioCapture},
};
constexpr std::uint8_t kWrongInputPriorityOrder[] = {3U, 1U, 2U, 0U};
constexpr MemoryViewAllocation kOverlappingMemoryViews[] = {
    {MemoryUse::kPrimaryInputGpioRawDmaRing,
     MemoryUse::kGpioRawDmaRing, 0U, 32768U,
     ResourceOwner::kGpioCapture},
    {MemoryUse::kAuxGpioRawDmaRing, MemoryUse::kGpioRawDmaRing,
     32000U, 32768U, ResourceOwner::kAuxGpioCapture},
};

static_assert(thingdaq::board::validPins(
    thingdaq::board::kPinAllocations));
static_assert(thingdaq::board::validGpioPinMappings(
    thingdaq::board::kGpioMappingsByPackedBit));
static_assert(thingdaq::board::validGpioPinMappings(
    thingdaq::board::kAuxGpioMappingsByPackedBit));
static_assert(thingdaq::board::validGpioBitAllocations(
    thingdaq::board::kGpioBitAllocations));
static_assert(thingdaq::board::gpioPinOrderMatches(
    thingdaq::board::kGpioMappingsByPackedBit,
    thingdaq::board::kGpioPinsByBit));
static_assert(thingdaq::board::validAdcConverterConfigurations(
    thingdaq::board::kAdcConverterConfigurations));
static_assert(thingdaq::board::validPitAllocations(
    thingdaq::board::kPitAllocations));
static_assert(thingdaq::board::validXbarRoutes(
    thingdaq::board::kXbarRoutes));
static_assert(thingdaq::board::validAdcEtcAllocations(
    thingdaq::board::kAdcEtcAllocations));
static_assert(thingdaq::board::validEdmaAllocations(
    thingdaq::board::kEdmaAllocations));
static_assert(thingdaq::board::validEdmaPriorities(
    thingdaq::board::kAdcEdmaPriorities,
    thingdaq::board::kGpioEdmaPriority));
static_assert(thingdaq::board::validMemoryAllocations(
    thingdaq::board::kMemoryAllocations));
static_assert(thingdaq::board::validMemoryViews(
    thingdaq::board::kInputModeMemoryViews,
    thingdaq::board::kMemoryAllocations));
static_assert(thingdaq::board::validMemoryViews(
    thingdaq::board::kIdleModeMemoryViews,
    thingdaq::board::kMemoryAllocations));
static_assert(thingdaq::board::validAcquisitionMemoryViews(
    thingdaq::board::kInputModeMemoryViews,
    thingdaq::board::kMemoryAllocations));
static_assert(thingdaq::board::validInterruptAllocations(
    thingdaq::board::kInterruptAllocations));
static_assert(thingdaq::board::validAcquisitionMemoryRegions(
    thingdaq::board::kMemoryAllocations));
static_assert(thingdaq::board::kAcquisitionResourceContract.valid());
static_assert(!thingdaq::board::validPins(kConflictingPins));
static_assert(!thingdaq::board::validPins(kOutOfRangePin));
static_assert(!thingdaq::board::pinAllocationsMatch(
    kAuxOwnerPins, kSplitAuxPinOwners, 0U,
    ResourceOwner::kAuxGpioCapture));
static_assert(!thingdaq::board::validGpioPinMappings(
    kDuplicateGpioBit));
static_assert(!thingdaq::board::validGpioPinMappings(
    kOutOfRangeGpioBit));
static_assert(!thingdaq::board::validGpioBitAllocations(
    kDuplicatePortBit));
static_assert(thingdaq::board::validGpioBitAllocations(
    kSameBitDifferentPorts));
static_assert(!thingdaq::board::gpioPinOrderMatches(
    kWrongGpioPinOrder, thingdaq::board::kGpioPinsByBit));
static_assert(!thingdaq::board::validAdcConverterConfigurations(
    kIncompleteAdcConfiguration));
static_assert(!thingdaq::board::validAdcConverterConfigurations(
    kWrongAdcQueue));
static_assert(!thingdaq::board::validAdcConverterConfigurations(
    kConflictingAdcDma));
static_assert(!thingdaq::board::validPitAllocations(kConflictingPit));
static_assert(!thingdaq::board::validPitAllocations(kOutOfRangePit));
static_assert(!thingdaq::board::validXbarRoutes(kConflictingXbar));
static_assert(!thingdaq::board::validXbarRoutes(kOutOfRangeXbar));
static_assert(
    !thingdaq::board::validAdcEtcAllocations(kConflictingAdcEtc));
static_assert(
    !thingdaq::board::validAdcEtcAllocations(kOutOfRangeAdcEtc));
static_assert(!thingdaq::board::validEdmaAllocations(kInvalidEdma));
static_assert(!thingdaq::board::validEdmaAllocations(kOutOfRangeEdma));
static_assert(!thingdaq::board::validEdmaPriorities(
    kConflictingEdmaPriorities, 2U));
static_assert(!thingdaq::board::strictlyDescendingEdmaPriorities(
    kWrongInputPriorityOrder));
static_assert(
    !thingdaq::board::validMemoryAllocations(kConflictingMemory));
static_assert(!thingdaq::board::validMemoryAllocations(kMisalignedMemory));
static_assert(!thingdaq::board::validMemoryAllocations(kInvalidAlignment));
static_assert(thingdaq::board::validMemoryAllocations(kDmaRingInDtcm));
static_assert(!thingdaq::board::validAcquisitionMemoryRegions(
    kDmaRingInDtcm));
static_assert(thingdaq::board::validMemoryAllocations(
    kCacheUnsafePackedRing));
static_assert(!thingdaq::board::validAcquisitionMemoryRegions(
    kCacheUnsafePackedRing));
static_assert(!thingdaq::board::validInterruptAllocations(
    kDuplicateInterruptUse));
static_assert(!thingdaq::board::validInterruptAllocations(
    kUnsafeInterruptPriority));
static_assert(!thingdaq::board::validInterruptAllocations(
    kWrongInterruptOwner));
static_assert(!thingdaq::board::validInterruptAllocations(
    kDuplicateInterruptVector));
static_assert(thingdaq::board::validInterruptAllocations(
    kReorderedInterrupts));
static_assert(!thingdaq::board::validMemoryViews(
    kOverlappingMemoryViews, thingdaq::board::kMemoryAllocations));
static_assert(thingdaq::board::alignUp(4048U, 32U) == 4064U);
static_assert(thingdaq::board::kCommandParserCapacityBytes >=
              thingdaq::protocol::kCommandParserStorageBytes);
static_assert(thingdaq::board::kUsbRxScratchBytes >=
              thingdaq::protocol_v1::kMaxCommandFrameBytes);
static_assert(thingdaq::board::kCommandQueueDepth == 4U);
static_assert(thingdaq::board::kResponseQueueDepth == 4U);
static_assert(thingdaq::board::kPacketBufferPrimaryCount == 105U);
static_assert(thingdaq::board::kPacketBufferReserveCount == 95U);
static_assert(thingdaq::board::kPacketBufferCount == 200U);
static_assert(thingdaq::board::kPacketBufferPrimaryStorageBytes == 430080U);
static_assert(thingdaq::board::kPacketBufferReserveStorageBytes == 389120U);
static_assert(thingdaq::board::kPacketBufferStorageBytes == 819200U);
static_assert(thingdaq::board::kPacketReadyQueueDepth ==
              thingdaq::board::kPacketBufferCount);
static_assert(thingdaq::board::kPacketTransmitQueueDepth ==
              thingdaq::board::kPacketBufferCount);
static_assert(thingdaq::board::kPacketReadyIndexStorageBytes == 400U);
static_assert(thingdaq::board::kPacketTransmitIndexStorageBytes == 200U);
static_assert(thingdaq::board::kPacketIndexStorageBytes == 600U);
static_assert(thingdaq::board::kCombinedAcquisitionRam1BufferBytes ==
              440832U);
static_assert(thingdaq::board::kCombinedAcquisitionRam2BufferBytes ==
              504640U);
static_assert(
    thingdaq::board::kCombinedAcquisitionAndUsbRam2BufferBytes ==
    512832U);
static_assert(thingdaq::board::kReservedRam1Bytes <=
              thingdaq::board::kRam1BudgetBytes);
static_assert(thingdaq::board::kReservedRam2Bytes <=
              thingdaq::board::kRam2BudgetBytes);
static_assert(thingdaq::control::kIdleConfiguration.stream_mask ==
              0U);
static_assert(thingdaq::control::kIdleConfiguration.source ==
              thingdaq::protocol_v1::Source::kHardware);
static_assert(
    thingdaq::control::kIdleConfiguration.data_frame_bytes ==
    thingdaq::protocol_v1::kDataFrameBytes);
static_assert(thingdaq::control::kSyntheticConfiguration.stream_mask ==
              3U);
static_assert(thingdaq::control::kSyntheticConfiguration.source ==
              thingdaq::protocol_v1::Source::kSynthetic);
static_assert(thingdaq::identity::kFirmwareVersion.major == 1U);
static_assert(thingdaq::identity::kFirmwareVersion.minor == 1U);
static_assert(thingdaq::identity::kFirmwareVersion.patch == 0U);
static_assert(thingdaq::board::kAdc0Pin == 14U);
static_assert(thingdaq::board::kAdc1Pin == 15U);
static_assert(thingdaq::board::countOf(
                  thingdaq::board::kAdcConverterConfigurations) == 2U);
static_assert(
    thingdaq::board::kAdcConverterConfigurations[0].logical_converter ==
        0U &&
    thingdaq::board::kAdcConverterConfigurations[0]
            .teensy_adc_library_module == 0U &&
    thingdaq::board::kAdcConverterConfigurations[0].teensy_pin == 14U &&
    thingdaq::board::kAdcConverterConfigurations[0].input_pad ==
        AdcInputPad::kGpioAdB1_02 &&
    thingdaq::board::kAdcConverterConfigurations[0].adc_peripheral == 1U &&
    thingdaq::board::kAdcConverterConfigurations[0].input_channel == 7U &&
    thingdaq::board::kAdcConverterConfigurations[0].adc_etc_trigger == 0U &&
    thingdaq::board::kAdcConverterConfigurations[0].xbar_input == 57U &&
    thingdaq::board::kAdcConverterConfigurations[0].xbar_output == 103U &&
    thingdaq::board::kAdcConverterConfigurations[0].edma_channel == 0U &&
    thingdaq::board::kAdcConverterConfigurations[0].dmamux_source == 24U &&
    thingdaq::board::kAdcConverterConfigurations[0].owner ==
        ResourceOwner::kAdc0Capture);
static_assert(
    thingdaq::board::kAdcConverterConfigurations[1].logical_converter ==
        1U &&
    thingdaq::board::kAdcConverterConfigurations[1]
            .teensy_adc_library_module == 1U &&
    thingdaq::board::kAdcConverterConfigurations[1].teensy_pin == 15U &&
    thingdaq::board::kAdcConverterConfigurations[1].input_pad ==
        AdcInputPad::kGpioAdB1_03 &&
    thingdaq::board::kAdcConverterConfigurations[1].adc_peripheral == 2U &&
    thingdaq::board::kAdcConverterConfigurations[1].input_channel == 8U &&
    thingdaq::board::kAdcConverterConfigurations[1].adc_etc_trigger == 4U &&
    thingdaq::board::kAdcConverterConfigurations[1].xbar_input == 57U &&
    thingdaq::board::kAdcConverterConfigurations[1].xbar_output == 107U &&
    thingdaq::board::kAdcConverterConfigurations[1].edma_channel == 1U &&
    thingdaq::board::kAdcConverterConfigurations[1].dmamux_source == 88U &&
    thingdaq::board::kAdcConverterConfigurations[1].owner ==
        ResourceOwner::kAdc1Capture);
static_assert(thingdaq::board::countOf(
                  thingdaq::board::kGpioMappingsByPackedBit) == 8U);
static_assert(thingdaq::board::countOf(
                  thingdaq::board::kAuxGpioMappingsByPackedBit) == 8U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[0].teensy_pin ==
                  6U &&
              thingdaq::board::kGpioMappingsByPackedBit[0].gpio2_bit ==
                  10U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[1].teensy_pin ==
                  7U &&
              thingdaq::board::kGpioMappingsByPackedBit[1].gpio2_bit ==
                  17U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[2].teensy_pin ==
                  8U &&
              thingdaq::board::kGpioMappingsByPackedBit[2].gpio2_bit ==
                  16U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[3].teensy_pin ==
                  9U &&
              thingdaq::board::kGpioMappingsByPackedBit[3].gpio2_bit ==
                  11U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[4].teensy_pin ==
                  10U &&
              thingdaq::board::kGpioMappingsByPackedBit[4].gpio2_bit ==
                  0U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[5].teensy_pin ==
                  11U &&
              thingdaq::board::kGpioMappingsByPackedBit[5].gpio2_bit ==
                  2U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[6].teensy_pin ==
                  12U &&
              thingdaq::board::kGpioMappingsByPackedBit[6].gpio2_bit ==
                  1U);
static_assert(thingdaq::board::kGpioMappingsByPackedBit[7].teensy_pin ==
                  13U &&
              thingdaq::board::kGpioMappingsByPackedBit[7].gpio2_bit ==
                  3U);
static_assert(thingdaq::board::kGpio2PsrCaptureMask == 0x00030C0FU);
static_assert(thingdaq::board::kGpio7ToGpio2Gpr27ClearMask ==
              thingdaq::board::kGpio2PsrCaptureMask);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[0].teensy_pin ==
                  16U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[0].gpio2_bit ==
                  23U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[1].teensy_pin ==
                  17U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[1].gpio2_bit ==
                  22U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[2].teensy_pin ==
                  18U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[2].gpio2_bit ==
                  17U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[3].teensy_pin ==
                  19U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[3].gpio2_bit ==
                  16U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[4].teensy_pin ==
                  20U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[4].gpio2_bit ==
                  26U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[5].teensy_pin ==
                  21U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[5].gpio2_bit ==
                  27U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[6].teensy_pin ==
                  22U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[6].gpio2_bit ==
                  24U);
static_assert(thingdaq::board::kAuxGpioMappingsByPackedBit[7].teensy_pin ==
                  23U &&
              thingdaq::board::kAuxGpioMappingsByPackedBit[7].gpio2_bit ==
                  25U);
static_assert(thingdaq::board::kGpio1PsrCaptureMask == 0x0FC30000U);
static_assert(thingdaq::board::kGpio6ToGpio1Gpr26ClearMask ==
              thingdaq::board::kGpio1PsrCaptureMask);
static_assert(thingdaq::board::kReservedRam1Bytes == 446372U);
static_assert(thingdaq::board::countOf(
                  thingdaq::board::kIdleModeMemoryViews) == 1U);
static_assert(thingdaq::board::kIdleModeMemoryViews[0].storage ==
              MemoryUse::kPacketBufferStorage);
static_assert(thingdaq::board::kIdleModeMemoryViews[0].offset == 0U);
static_assert(thingdaq::board::kIdleModeMemoryViews[0].bytes == 4096U);
static_assert(thingdaq::board::kGpioRawDmaBufferBytes == 16192U);
static_assert(thingdaq::board::kGpioRawDmaRingBytes == 64768U);
static_assert(thingdaq::board::kInputGpioRawDmaBufferBytes == 8096U);
static_assert(thingdaq::board::kPrimaryInputGpioRawDmaRingBytes == 32384U);
static_assert(thingdaq::board::kAuxGpioRawDmaRingBytes == 32384U);
static_assert(thingdaq::board::kAdcDmaBufferStrideBytes == 4064U);
static_assert(thingdaq::board::kAdcDmaRingBytes == 32512U);
static_assert(thingdaq::board::kAdcDmaOverflowSinkBytes == 32U);
static_assert(thingdaq::board::kAdcDmaPipelineDepth == 6U);
static_assert(thingdaq::board::kAdcDmaDescriptorCount == 12U);
static_assert(thingdaq::board::kAdcDmaDescriptorBytes == 768U);
static_assert(thingdaq::board::kAdcEdmaPriorities[0] == 2U);
static_assert(thingdaq::board::kAdcEdmaPriorities[1] == 1U);
static_assert(thingdaq::board::kAdcEdmaIrqPriority == 48U);
static_assert(thingdaq::board::kGpioRawDmaOverflowSinkBytes == 32U);
static_assert(thingdaq::board::kGpioRawDmaDescriptorCount == 5U);
static_assert(thingdaq::board::kGpioRawDmaDescriptorBytes == 160U);
static_assert(thingdaq::board::kAuxGpioRawDmaDescriptorBytes == 160U);
static_assert(thingdaq::board::kAuxGpioRawDmaOverflowSinkBytes == 32U);
static_assert(thingdaq::board::kGpioPairedJoinStateBudgetBytes == 768U);
static_assert(thingdaq::board::kGpioPairedJoinStateOffsetBytes == 0U);
static_assert(thingdaq::board::kAuxGpioRawDmaDescriptorOffsetBytes == 768U);
static_assert(
    thingdaq::board::kPrimaryInputGpioRawDmaOverflowSinkOffsetBytes == 928U);
static_assert(thingdaq::board::kAuxGpioRawDmaOverflowSinkOffsetBytes == 960U);
static_assert(thingdaq::board::kAuxInputWorkspaceBytes == 992U);
static_assert(thingdaq::board::kGpioPackedRingDepth == 4U);
static_assert(thingdaq::board::kGpioPackedBufferStrideBytes == 4064U);
static_assert(thingdaq::board::kGpioPackerStateBudgetBytes == 2048U);
static_assert(thingdaq::board::kAdcPackerStateBudgetBytes == 512U);
static_assert(thingdaq::board::kReservedRam2Bytes == 507776U);
static_assert(thingdaq::board::kChecksumBenchmarkBufferBytes == 4096U);
static_assert(thingdaq::board::kGpioClockDiagnosticSinkBytes == 32U);
static_assert(thingdaq::board::kGpioPitChannel == 0U);
static_assert(thingdaq::board::kXbarPitTrigger0Input == 56U);
static_assert(thingdaq::board::kXbarPitTrigger1Input == 57U);
static_assert(thingdaq::board::kXbarPitTrigger2Input == 58U);
static_assert(thingdaq::board::kXbarPitTrigger3Input == 59U);
static_assert(thingdaq::board::kXbarDmaRequest30Output == 0U);
static_assert(thingdaq::board::kXbarDmaRequest31Output == 1U);
static_assert(thingdaq::board::kXbarDmaRequest94Output == 2U);
static_assert(thingdaq::board::kXbarDmaRequest95Output == 3U);
static_assert(thingdaq::board::kGpioXbarInput == 56U);
static_assert(thingdaq::board::kGpioXbarOutput == 0U);
static_assert(thingdaq::board::kAuxGpioXbarInput == 56U);
static_assert(thingdaq::board::kAuxGpioXbarOutput == 1U);
static_assert(thingdaq::board::kGpioXbarSelectionRegister == 0U);
static_assert(thingdaq::board::kAuxGpioXbarSelectionRegister == 0U);
static_assert(thingdaq::board::kGpioXbarSelectionMask == 0x00FFU);
static_assert(thingdaq::board::kAuxGpioXbarSelectionMask == 0xFF00U);
static_assert(thingdaq::board::replaceXbarSelection(
                  0xAB00U, thingdaq::board::kGpioXbarOutput,
                  thingdaq::board::kGpioXbarInput) == 0xAB38U);
static_assert(thingdaq::board::replaceXbarSelection(
                  0x00CDU, thingdaq::board::kAuxGpioXbarOutput,
                  thingdaq::board::kAuxGpioXbarInput) == 0x38CDU);
static_assert(thingdaq::board::kGpioXbarActiveEdge == 1U);
static_assert(thingdaq::board::kGpioEdmaChannel == 2U);
static_assert(thingdaq::board::kAuxGpioEdmaChannel == 3U);
static_assert(thingdaq::board::kDmamuxXbar1Request0Source == 30U);
static_assert(thingdaq::board::kDmamuxXbar1Request1Source == 31U);
static_assert(thingdaq::board::kDmamuxXbar1Request2Source == 94U);
static_assert(thingdaq::board::kDmamuxXbar1Request3Source == 95U);
static_assert(thingdaq::board::kGpioDmamuxSource == 30U);
static_assert(thingdaq::board::kAuxGpioDmamuxSource == 31U);
static_assert(thingdaq::board::kGpioEdmaPriority == 0U);
static_assert(thingdaq::board::kInputModeEdmaPriorities[0] == 3U);
static_assert(thingdaq::board::kInputModeEdmaPriorities[1] == 2U);
static_assert(thingdaq::board::kInputModeEdmaPriorities[2] == 1U);
static_assert(thingdaq::board::kInputModeEdmaPriorities[3] == 0U);
static_assert(thingdaq::board::kGpioEdmaIrqPriority == 64U);
static_assert(thingdaq::board::kAuxGpioEdmaIrqPriority == 64U);
static_assert(thingdaq::board::kInterruptAllocations[4].irq == 3U);
static_assert(thingdaq::board::kInterruptAllocations[4].vector == 19U);
static_assert(thingdaq::capabilities::kMetadata.supported_stream_mask == 3U);
static_assert((thingdaq::capabilities::kMetadata.capability_bits &
               thingdaq::capabilities::kDataCapabilityMask) ==
              thingdaq::capabilities::kDataCapabilityMask);
static_assert((thingdaq::capabilities::kMetadata.capability_bits &
               static_cast<std::uint32_t>(
                   thingdaq::protocol_v1::Capability::
                       kGpioClockDiagnostic)) != 0U);
static_assert(thingdaq::capabilities::kMetadata.gpio_pin_count == 8U);
static_assert(thingdaq::identity::usbProductNameMatchesIdentity());

}  // namespace

int main() {
  return thingdaq::identity::kBuildId.front() == 't' ? 0 : 1;
}
