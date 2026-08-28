#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "control_state.h"
#include "firmware_capabilities.h"
#include "firmware_identity.h"

namespace {

using teensy_daq::board::AdcEtcAllocation;
using teensy_daq::board::EdmaAllocation;
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

static_assert(teensy_daq::board::validPins(
    teensy_daq::board::kPinAllocations));
static_assert(teensy_daq::board::validPitAllocations(
    teensy_daq::board::kPitAllocations));
static_assert(teensy_daq::board::validXbarRoutes(
    teensy_daq::board::kXbarRoutes));
static_assert(teensy_daq::board::validAdcEtcAllocations(
    teensy_daq::board::kAdcEtcAllocations));
static_assert(teensy_daq::board::validEdmaAllocations(
    teensy_daq::board::kEdmaAllocations));
static_assert(teensy_daq::board::validMemoryAllocations(
    teensy_daq::board::kMemoryAllocations));
static_assert(!teensy_daq::board::validPins(kConflictingPins));
static_assert(!teensy_daq::board::validPins(kOutOfRangePin));
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
static_assert(
    !teensy_daq::board::validMemoryAllocations(kConflictingMemory));
static_assert(!teensy_daq::board::validMemoryAllocations(kMisalignedMemory));
static_assert(!teensy_daq::board::validMemoryAllocations(kInvalidAlignment));
static_assert(teensy_daq::board::alignUp(4048U, 32U) == 4064U);
static_assert(teensy_daq::board::kCommandParserCapacityBytes >=
              teensy_daq::protocol::kCommandParserStorageBytes);
static_assert(teensy_daq::board::kUsbRxScratchBytes >=
              teensy_daq::protocol_v1::kMaxCommandFrameBytes);
static_assert(teensy_daq::board::kCommandQueueDepth == 4U);
static_assert(teensy_daq::board::kResponseQueueDepth == 4U);
static_assert(teensy_daq::board::kReservedRam1Bytes <=
              teensy_daq::board::kRam1BudgetBytes);
static_assert(teensy_daq::board::kReservedRam2Bytes <=
              teensy_daq::board::kRam2BudgetBytes);
static_assert(teensy_daq::control::kControlOnlyConfiguration.stream_mask ==
              0U);
static_assert(teensy_daq::control::kControlOnlyConfiguration.source ==
              teensy_daq::protocol_v1::Source::kHardware);
static_assert(
    teensy_daq::control::kControlOnlyConfiguration.data_frame_bytes ==
    teensy_daq::protocol_v1::kDataFrameBytes);
static_assert(teensy_daq::identity::kFirmwareVersion.major == 0U);
static_assert(teensy_daq::identity::kFirmwareVersion.minor == 3U);
static_assert(teensy_daq::identity::kFirmwareVersion.patch == 0U);
static_assert(teensy_daq::board::kAdc0Pin == 14U);
static_assert(teensy_daq::board::kAdc1Pin == 15U);
static_assert(teensy_daq::board::kReservedRam1Bytes == 4512U);
static_assert(teensy_daq::board::kReservedRam2Bytes == 113664U);
static_assert(teensy_daq::capabilities::kMetadata.supported_stream_mask == 0U);
static_assert((teensy_daq::capabilities::kMetadata.capability_bits &
               teensy_daq::capabilities::kDataCapabilityMask) == 0U);
static_assert(teensy_daq::capabilities::kMetadata.gpio_pin_count == 8U);
static_assert(teensy_daq::identity::usbProductNameMatchesIdentity());

}  // namespace

int main() {
  return teensy_daq::identity::kBuildId.front() == 't' ? 0 : 1;
}
