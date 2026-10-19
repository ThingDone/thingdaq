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

// PIT divisors are exact. DWT windows round up rational cycle/event ratios
// (450 MHz / 4 MHz is 112.5); request validation bounds the eDMA count.
Plan makePlan(const protocol::GpioClockDiagnosticRequest &request);
Plan makePlan(const protocol::GpioClockDiagnosticRequest &request,
              protocol_v3::CpuProfile profile);

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
