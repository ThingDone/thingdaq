#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "control_state.h"
#include "firmware_capabilities.h"
#include "firmware_identity.h"

namespace {

using teensy_daq::board::AdcConverterConfiguration;
using teensy_daq::board::AdcEtcAllocation;
using teensy_daq::board::AdcInputPad;
using teensy_daq::board::EdmaAllocation;
using teensy_daq::board::GpioPinMapping;
using teensy_daq::board::InterruptAllocation;
using teensy_daq::board::InterruptUse;
using teensy_daq::board::MemoryAllocation;
using teensy_daq::board::MemoryRegion;
using teensy_daq::board::MemoryUse;
using teensy_daq::board::PinAllocation;
using teensy_daq::board::PitAllocation;
using teensy_daq::board::ResourceOwner;
using teensy_daq::board::XbarRoute;

constexpr PinAllocation kConflictingPins[] = {
    {6U, ResourceOwner::kGpioCapture},
    {6U, ResourceOwner::kAdc0Capture},
};
constexpr PinAllocation kOutOfRangePin[] = {
    {teensy_daq::board::kTeensy40DigitalPinCount,
     ResourceOwner::kGpioCapture},
};
constexpr GpioPinMapping kDuplicateGpioBit[] = {
    {6U, 10U},
    {7U, 10U},
};
constexpr GpioPinMapping kOutOfRangeGpioBit[] = {
    {6U, teensy_daq::board::kGpioPortBitCount},
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
    {teensy_daq::board::kPitChannelCount,
     ResourceOwner::kAcquisitionClock},
};
constexpr XbarRoute kConflictingXbar[] = {
    {56U, 103U, ResourceOwner::kAdc0Capture},
    {57U, 103U, ResourceOwner::kAdc1Capture},
};
constexpr XbarRoute kOutOfRangeXbar[] = {
    {teensy_daq::board::kXbarInputCount, 0U,
     ResourceOwner::kAcquisitionClock},
};
constexpr AdcEtcAllocation kConflictingAdcEtc[] = {
    {0U, 1U, ResourceOwner::kAdc0Capture},
    {0U, 2U, ResourceOwner::kAdc1Capture},
};
constexpr AdcEtcAllocation kOutOfRangeAdcEtc[] = {
    {teensy_daq::board::kAdcEtcTriggerCount, 1U,
     ResourceOwner::kAdc0Capture},
};
constexpr EdmaAllocation kInvalidEdma[] = {
    {0U, 24U, ResourceOwner::kAdc0Capture},
    {0U, 88U, ResourceOwner::kAdc1Capture},
};
constexpr EdmaAllocation kOutOfRangeEdma[] = {
    {teensy_daq::board::kEdmaChannelCount, 24U,
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
    {InterruptUse::kAdc0DmaCompletion, 48U,
     ResourceOwner::kAdc0Capture},
    {InterruptUse::kAdc0DmaCompletion, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 48U, ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 64U,
     ResourceOwner::kGpioCapture},
};
constexpr InterruptAllocation kUnsafeInterruptPriority[] = {
    {InterruptUse::kAdc0DmaCompletion, 48U,
     ResourceOwner::kAdc0Capture},
    {InterruptUse::kAdc1DmaCompletion, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 48U, ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 40U,
     ResourceOwner::kGpioCapture},
};
constexpr InterruptAllocation kWrongInterruptOwner[] = {
    {InterruptUse::kAdc0DmaCompletion, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdc1DmaCompletion, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdcEtcError, 48U, ResourceOwner::kAdcCapture},
    {InterruptUse::kGpioDmaCompletion, 64U,
     ResourceOwner::kGpioCapture},
};
constexpr InterruptAllocation kReorderedInterrupts[] = {
    {InterruptUse::kGpioDmaCompletion, 64U,
     ResourceOwner::kGpioCapture},
    {InterruptUse::kAdcEtcError, 48U, ResourceOwner::kAdcCapture},
    {InterruptUse::kAdc1DmaCompletion, 48U,
     ResourceOwner::kAdc1Capture},
    {InterruptUse::kAdc0DmaCompletion, 48U,
     ResourceOwner::kAdc0Capture},
};

static_assert(teensy_daq::board::validPins(
    teensy_daq::board::kPinAllocations));
static_assert(teensy_daq::board::validGpioPinMappings(
    teensy_daq::board::kGpioMappingsByPackedBit));
static_assert(teensy_daq::board::gpioPinOrderMatches(
    teensy_daq::board::kGpioMappingsByPackedBit,
    teensy_daq::board::kGpioPinsByBit));
static_assert(teensy_daq::board::validAdcConverterConfigurations(
    teensy_daq::board::kAdcConverterConfigurations));
static_assert(teensy_daq::board::validPitAllocations(
    teensy_daq::board::kPitAllocations));
static_assert(teensy_daq::board::validXbarRoutes(
    teensy_daq::board::kXbarRoutes));
static_assert(teensy_daq::board::validAdcEtcAllocations(
    teensy_daq::board::kAdcEtcAllocations));
static_assert(teensy_daq::board::validEdmaAllocations(
    teensy_daq::board::kEdmaAllocations));
static_assert(teensy_daq::board::validEdmaPriorities(
    teensy_daq::board::kAdcEdmaPriorities,
    teensy_daq::board::kGpioEdmaPriority));
static_assert(teensy_daq::board::validMemoryAllocations(
    teensy_daq::board::kMemoryAllocations));
static_assert(teensy_daq::board::validInterruptAllocations(
    teensy_daq::board::kInterruptAllocations));
static_assert(teensy_daq::board::validAcquisitionMemoryRegions(
    teensy_daq::board::kMemoryAllocations));
static_assert(teensy_daq::board::kAcquisitionResourceContract.valid());
static_assert(!teensy_daq::board::validPins(kConflictingPins));
static_assert(!teensy_daq::board::validPins(kOutOfRangePin));
static_assert(!teensy_daq::board::validGpioPinMappings(
    kDuplicateGpioBit));
static_assert(!teensy_daq::board::validGpioPinMappings(
    kOutOfRangeGpioBit));
static_assert(!teensy_daq::board::gpioPinOrderMatches(
    kWrongGpioPinOrder, teensy_daq::board::kGpioPinsByBit));
static_assert(!teensy_daq::board::validAdcConverterConfigurations(
    kIncompleteAdcConfiguration));
static_assert(!teensy_daq::board::validAdcConverterConfigurations(
    kWrongAdcQueue));
static_assert(!teensy_daq::board::validAdcConverterConfigurations(
    kConflictingAdcDma));
static_assert(!teensy_daq::board::validPitAllocations(kConflictingPit));
static_assert(!teensy_daq::board::validPitAllocations(kOutOfRangePit));
static_assert(!teensy_daq::board::validXbarRoutes(kConflictingXbar));
static_assert(!teensy_daq::board::validXbarRoutes(kOutOfRangeXbar));
static_assert(
    !teensy_daq::board::validAdcEtcAllocations(kConflictingAdcEtc));
static_assert(
    !teensy_daq::board::validAdcEtcAllocations(kOutOfRangeAdcEtc));
static_assert(!teensy_daq::board::validEdmaAllocations(kInvalidEdma));
static_assert(!teensy_daq::board::validEdmaAllocations(kOutOfRangeEdma));
static_assert(!teensy_daq::board::validEdmaPriorities(
    kConflictingEdmaPriorities, 2U));
static_assert(
    !teensy_daq::board::validMemoryAllocations(kConflictingMemory));
static_assert(!teensy_daq::board::validMemoryAllocations(kMisalignedMemory));
static_assert(!teensy_daq::board::validMemoryAllocations(kInvalidAlignment));
static_assert(teensy_daq::board::validMemoryAllocations(kDmaRingInDtcm));
static_assert(!teensy_daq::board::validAcquisitionMemoryRegions(
    kDmaRingInDtcm));
static_assert(teensy_daq::board::validMemoryAllocations(
    kCacheUnsafePackedRing));
static_assert(!teensy_daq::board::validAcquisitionMemoryRegions(
    kCacheUnsafePackedRing));
static_assert(!teensy_daq::board::validInterruptAllocations(
    kDuplicateInterruptUse));
static_assert(!teensy_daq::board::validInterruptAllocations(
    kUnsafeInterruptPriority));
static_assert(!teensy_daq::board::validInterruptAllocations(
    kWrongInterruptOwner));
static_assert(teensy_daq::board::validInterruptAllocations(
    kReorderedInterrupts));
static_assert(teensy_daq::board::alignUp(4048U, 32U) == 4064U);
static_assert(teensy_daq::board::kCommandParserCapacityBytes >=
              teensy_daq::protocol::kCommandParserStorageBytes);
static_assert(teensy_daq::board::kUsbRxScratchBytes >=
              teensy_daq::protocol_v1::kMaxCommandFrameBytes);
static_assert(teensy_daq::board::kCommandQueueDepth == 4U);
static_assert(teensy_daq::board::kResponseQueueDepth == 4U);
static_assert(teensy_daq::board::kPacketBufferPrimaryCount == 105U);
static_assert(teensy_daq::board::kPacketBufferReserveCount == 95U);
static_assert(teensy_daq::board::kPacketBufferCount == 200U);
static_assert(teensy_daq::board::kPacketBufferPrimaryStorageBytes == 430080U);
static_assert(teensy_daq::board::kPacketBufferReserveStorageBytes == 389120U);
static_assert(teensy_daq::board::kPacketBufferStorageBytes == 819200U);
static_assert(teensy_daq::board::kPacketReadyQueueDepth ==
              teensy_daq::board::kPacketBufferCount);
static_assert(teensy_daq::board::kPacketTransmitQueueDepth ==
              teensy_daq::board::kPacketBufferCount);
static_assert(teensy_daq::board::kPacketReadyIndexStorageBytes == 400U);
static_assert(teensy_daq::board::kPacketTransmitIndexStorageBytes == 200U);
static_assert(teensy_daq::board::kPacketIndexStorageBytes == 600U);
static_assert(teensy_daq::board::kCombinedAcquisitionRam1BufferBytes ==
              440832U);
static_assert(teensy_daq::board::kCombinedAcquisitionRam2BufferBytes ==
              495264U);
static_assert(
    teensy_daq::board::kCombinedAcquisitionAndUsbRam2BufferBytes ==
    503456U);
static_assert(teensy_daq::board::kReservedRam1Bytes <=
              teensy_daq::board::kRam1BudgetBytes);
static_assert(teensy_daq::board::kReservedRam2Bytes <=
              teensy_daq::board::kRam2BudgetBytes);
static_assert(teensy_daq::control::kIdleConfiguration.stream_mask ==
              0U);
static_assert(teensy_daq::control::kIdleConfiguration.source ==
              teensy_daq::protocol_v1::Source::kHardware);
static_assert(
    teensy_daq::control::kIdleConfiguration.data_frame_bytes ==
    teensy_daq::protocol_v1::kDataFrameBytes);
static_assert(teensy_daq::control::kSyntheticConfiguration.stream_mask ==
              3U);
static_assert(teensy_daq::control::kSyntheticConfiguration.source ==
              teensy_daq::protocol_v1::Source::kSynthetic);
static_assert(teensy_daq::identity::kFirmwareVersion.major == 0U);
static_assert(teensy_daq::identity::kFirmwareVersion.minor == 7U);
static_assert(teensy_daq::identity::kFirmwareVersion.patch == 0U);
static_assert(teensy_daq::board::kAdc0Pin == 14U);
static_assert(teensy_daq::board::kAdc1Pin == 15U);
static_assert(teensy_daq::board::countOf(
                  teensy_daq::board::kAdcConverterConfigurations) == 2U);
static_assert(
    teensy_daq::board::kAdcConverterConfigurations[0].logical_converter ==
        0U &&
    teensy_daq::board::kAdcConverterConfigurations[0]
            .teensy_adc_library_module == 0U &&
    teensy_daq::board::kAdcConverterConfigurations[0].teensy_pin == 14U &&
    teensy_daq::board::kAdcConverterConfigurations[0].input_pad ==
        AdcInputPad::kGpioAdB1_02 &&
    teensy_daq::board::kAdcConverterConfigurations[0].adc_peripheral == 1U &&
    teensy_daq::board::kAdcConverterConfigurations[0].input_channel == 7U &&
    teensy_daq::board::kAdcConverterConfigurations[0].adc_etc_trigger == 0U &&
    teensy_daq::board::kAdcConverterConfigurations[0].xbar_input == 57U &&
    teensy_daq::board::kAdcConverterConfigurations[0].xbar_output == 103U &&
    teensy_daq::board::kAdcConverterConfigurations[0].edma_channel == 0U &&
    teensy_daq::board::kAdcConverterConfigurations[0].dmamux_source == 24U &&
    teensy_daq::board::kAdcConverterConfigurations[0].owner ==
        ResourceOwner::kAdc0Capture);
static_assert(
    teensy_daq::board::kAdcConverterConfigurations[1].logical_converter ==
        1U &&
    teensy_daq::board::kAdcConverterConfigurations[1]
            .teensy_adc_library_module == 1U &&
    teensy_daq::board::kAdcConverterConfigurations[1].teensy_pin == 15U &&
    teensy_daq::board::kAdcConverterConfigurations[1].input_pad ==
        AdcInputPad::kGpioAdB1_03 &&
    teensy_daq::board::kAdcConverterConfigurations[1].adc_peripheral == 2U &&
    teensy_daq::board::kAdcConverterConfigurations[1].input_channel == 8U &&
    teensy_daq::board::kAdcConverterConfigurations[1].adc_etc_trigger == 4U &&
    teensy_daq::board::kAdcConverterConfigurations[1].xbar_input == 57U &&
    teensy_daq::board::kAdcConverterConfigurations[1].xbar_output == 107U &&
    teensy_daq::board::kAdcConverterConfigurations[1].edma_channel == 1U &&
    teensy_daq::board::kAdcConverterConfigurations[1].dmamux_source == 88U &&
    teensy_daq::board::kAdcConverterConfigurations[1].owner ==
        ResourceOwner::kAdc1Capture);
static_assert(teensy_daq::board::countOf(
                  teensy_daq::board::kGpioMappingsByPackedBit) == 8U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[0].teensy_pin ==
                  6U &&
              teensy_daq::board::kGpioMappingsByPackedBit[0].gpio2_bit ==
                  10U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[1].teensy_pin ==
                  7U &&
              teensy_daq::board::kGpioMappingsByPackedBit[1].gpio2_bit ==
                  17U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[2].teensy_pin ==
                  8U &&
              teensy_daq::board::kGpioMappingsByPackedBit[2].gpio2_bit ==
                  16U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[3].teensy_pin ==
                  9U &&
              teensy_daq::board::kGpioMappingsByPackedBit[3].gpio2_bit ==
                  11U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[4].teensy_pin ==
                  10U &&
              teensy_daq::board::kGpioMappingsByPackedBit[4].gpio2_bit ==
                  0U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[5].teensy_pin ==
                  11U &&
              teensy_daq::board::kGpioMappingsByPackedBit[5].gpio2_bit ==
                  2U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[6].teensy_pin ==
                  12U &&
              teensy_daq::board::kGpioMappingsByPackedBit[6].gpio2_bit ==
                  1U);
static_assert(teensy_daq::board::kGpioMappingsByPackedBit[7].teensy_pin ==
                  13U &&
              teensy_daq::board::kGpioMappingsByPackedBit[7].gpio2_bit ==
                  3U);
static_assert(teensy_daq::board::kGpio2PsrCaptureMask == 0x00030C0FU);
static_assert(teensy_daq::board::kGpio7ToGpio2Gpr27ClearMask ==
              teensy_daq::board::kGpio2PsrCaptureMask);
static_assert(teensy_daq::board::kReservedRam1Bytes == 450464U);
static_assert(teensy_daq::board::kGpioRawDmaBufferBytes == 16192U);
static_assert(teensy_daq::board::kGpioRawDmaRingBytes == 64768U);
static_assert(teensy_daq::board::kAdcDmaBufferStrideBytes == 4064U);
static_assert(teensy_daq::board::kAdcDmaRingBytes == 24384U);
static_assert(teensy_daq::board::kAdcDmaOverflowSinkBytes == 32U);
static_assert(teensy_daq::board::kAdcDmaDescriptorCount == 8U);
static_assert(teensy_daq::board::kAdcDmaDescriptorBytes == 512U);
static_assert(teensy_daq::board::kAdcEdmaPriorities[0] == 2U);
static_assert(teensy_daq::board::kAdcEdmaPriorities[1] == 1U);
static_assert(teensy_daq::board::kAdcEdmaIrqPriority == 48U);
static_assert(teensy_daq::board::kGpioRawDmaOverflowSinkBytes == 32U);
static_assert(teensy_daq::board::kGpioRawDmaDescriptorCount == 5U);
static_assert(teensy_daq::board::kGpioRawDmaDescriptorBytes == 160U);
static_assert(teensy_daq::board::kGpioPackedRingDepth == 4U);
static_assert(teensy_daq::board::kGpioPackedBufferStrideBytes == 4064U);
static_assert(teensy_daq::board::kGpioPackerStateBudgetBytes == 2048U);
static_assert(teensy_daq::board::kAdcPackerStateBudgetBytes == 512U);
static_assert(teensy_daq::board::kReservedRam2Bytes == 499392U);
static_assert(teensy_daq::board::kChecksumBenchmarkBufferBytes == 4096U);
static_assert(teensy_daq::board::kGpioClockDiagnosticSinkBytes == 32U);
static_assert(teensy_daq::board::kGpioPitChannel == 0U);
static_assert(teensy_daq::board::kXbarPitTrigger0Input == 56U);
static_assert(teensy_daq::board::kXbarPitTrigger1Input == 57U);
static_assert(teensy_daq::board::kXbarPitTrigger2Input == 58U);
static_assert(teensy_daq::board::kXbarPitTrigger3Input == 59U);
static_assert(teensy_daq::board::kXbarDmaRequest30Output == 0U);
static_assert(teensy_daq::board::kXbarDmaRequest31Output == 1U);
static_assert(teensy_daq::board::kXbarDmaRequest94Output == 2U);
static_assert(teensy_daq::board::kXbarDmaRequest95Output == 3U);
static_assert(teensy_daq::board::kGpioXbarInput == 56U);
static_assert(teensy_daq::board::kGpioXbarOutput == 0U);
static_assert(teensy_daq::board::kGpioXbarActiveEdge == 1U);
static_assert(teensy_daq::board::kGpioEdmaChannel == 2U);
static_assert(teensy_daq::board::kDmamuxXbar1Request0Source == 30U);
static_assert(teensy_daq::board::kDmamuxXbar1Request1Source == 31U);
static_assert(teensy_daq::board::kDmamuxXbar1Request2Source == 94U);
static_assert(teensy_daq::board::kDmamuxXbar1Request3Source == 95U);
static_assert(teensy_daq::board::kGpioDmamuxSource == 30U);
static_assert(teensy_daq::board::kGpioEdmaPriority == 0U);
static_assert(teensy_daq::board::kGpioEdmaIrqPriority == 64U);
static_assert(teensy_daq::capabilities::kMetadata.supported_stream_mask == 3U);
static_assert((teensy_daq::capabilities::kMetadata.capability_bits &
               teensy_daq::capabilities::kDataCapabilityMask) ==
              teensy_daq::capabilities::kDataCapabilityMask);
static_assert((teensy_daq::capabilities::kMetadata.capability_bits &
               static_cast<std::uint32_t>(
                   teensy_daq::protocol_v1::Capability::
                       kGpioClockDiagnostic)) != 0U);
static_assert(teensy_daq::capabilities::kMetadata.gpio_pin_count == 8U);
static_assert(teensy_daq::identity::usbProductNameMatchesIdentity());

}  // namespace

int main() {
  return teensy_daq::identity::kBuildId.front() == 't' ? 0 : 1;
}
