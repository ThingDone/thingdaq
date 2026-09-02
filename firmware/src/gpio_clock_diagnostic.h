#pragma once

#include <cstdint>

#include "protocol.h"

namespace thingdaq::gpio_clock {

constexpr std::uint32_t errorBit(protocol_v1::GpioClockError error) {
  return static_cast<std::uint32_t>(error);
}

struct Plan {
  std::uint32_t rate_hz = 0U;
  std::uint32_t pit_divisor = 0U;
  std::uint32_t pit_load_value = 0U;
  std::uint32_t cycles_per_event = 0U;
  std::uint32_t measurement_cycles = 0U;
  std::uint16_t requested_event_count = 0U;
  std::uint16_t tcd_major_count = 0U;
};

// All integer arithmetic is exact because accepted rates divide both the
// fixed 24 MHz PIT clock and the selected, runtime-verified DWT clock. The
// request validator also proves every intermediate and the 15-bit eDMA
// ELINKNO count are bounded.
Plan makePlan(const protocol::GpioClockDiagnosticRequest &request);

class Platform {
 public:
  virtual ~Platform() = default;

  // Execute exactly one bounded hardware window. Register-level failures are
  // returned as snapshot flags so a host can inspect the evidence; false is
  // reserved for a platform on which the diagnostic cannot run at all.
  virtual bool execute(const Plan &plan,
                       protocol::GpioClockDiagnosticResponse &snapshot) = 0;
};

enum class RunStatus : std::uint8_t {
  kOk,
  kInvalidRequest,
  kPlatformUnavailable,
};

struct RunResult {
  RunStatus status = RunStatus::kInvalidRequest;
  protocol::GpioClockDiagnosticResponse response{};

  constexpr bool ok() const { return status == RunStatus::kOk; }
};

class Runner {
 public:
  explicit Runner(Platform &platform) : platform_(platform) {}

  RunResult run(const protocol::GpioClockDiagnosticRequest &request);

 private:
  Platform &platform_;
};

}  // namespace thingdaq::gpio_clock
