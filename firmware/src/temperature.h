#pragma once

#include <cstdint>
#include "generated/protocol_v2_constants.h"

namespace thingdaq::temperature {

using Status = protocol_v2::TemperatureStatus;

struct Reading {
  Status status = Status::kUnavailable;
  std::int32_t millidegrees_c = 0;
};

using Reader = Reading (*)();

// Snapshot the core's already-running monitor; never trigger a conversion,
// spin waiting for FINISHED, or change the core's thermal alarm configuration.
// Conversion follows the fuse-calibrated formula used by clock_health_teensy.
inline Reading decode(std::uint32_t control, std::uint32_t calibration) {
  if ((control & 1U) != 0U || (control & 2U) == 0U) return {};
  if ((control & 4U) == 0U) return {Status::kNotReady, 0};
  const auto hot = static_cast<std::int32_t>(calibration & 0xffU);
  const auto hot_count = static_cast<std::int32_t>((calibration >> 8U) & 0xfffU);
  const auto room_count = static_cast<std::int32_t>((calibration >> 20U) & 0xfffU);
  if (hot <= 25 || hot > 150 || hot_count == 0 || room_count <= hot_count)
    return {Status::kInvalidCalibration, 0};
  const auto measured = static_cast<std::int32_t>((control >> 8U) & 0xfffU);
  // Maximum magnitude is 4095 * 125 * 1000 = 511875000, within int32.
  const std::int32_t numerator = (measured - hot_count) * (hot - 25) * 1000;
  const std::int32_t value = hot * 1000 - numerator / (room_count - hot_count);
  if (value < -40000 || value > 150000) return {Status::kOutOfRange, 0};
  return {Status::kValid, static_cast<std::int32_t>(value)};
}

Reading readTeensy();

}  // namespace thingdaq::temperature
