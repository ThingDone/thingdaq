#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "firmware_capabilities.h"
#include "firmware_identity.h"

namespace {

using teensy_daq::board::EdmaAllocation;
using teensy_daq::board::PinAllocation;
using teensy_daq::board::ResourceOwner;

constexpr PinAllocation kConflictingPins[] = {
    {6U, ResourceOwner::kGpioCapture},
    {6U, ResourceOwner::kAdc0Capture},
};
constexpr EdmaAllocation kInvalidEdma[] = {
    {0U, 24U, ResourceOwner::kAdc0Capture},
    {0U, 88U, ResourceOwner::kAdc1Capture},
};

static_assert(!teensy_daq::board::validPins(kConflictingPins));
static_assert(!teensy_daq::board::validEdmaAllocations(kInvalidEdma));
static_assert(teensy_daq::identity::kFirmwareVersion.major == 0U);
static_assert(teensy_daq::identity::kFirmwareVersion.minor == 3U);
static_assert(teensy_daq::identity::kFirmwareVersion.patch == 0U);
static_assert(teensy_daq::board::kAdc0Pin == 14U);
static_assert(teensy_daq::board::kAdc1Pin == 15U);
static_assert(teensy_daq::board::kReservedRam2Bytes == 113664U);
static_assert(teensy_daq::capabilities::kMetadata.supported_stream_mask == 0U);
static_assert(teensy_daq::capabilities::kMetadata.gpio_pin_count == 8U);

}  // namespace

int main() {
  return teensy_daq::identity::kBuildId.front() == 't' ? 0 : 1;
}
