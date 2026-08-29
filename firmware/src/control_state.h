#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "firmware_capabilities.h"
#include "firmware_identity.h"
#include "protocol.h"
#include "statistics.h"

namespace teensy_daq::control {

inline constexpr std::size_t kRecentRequestIdWindow = 16U;

// IDLE has no applied acquisition profile. Protocol v1 represents that state
// with the original zero-stream hardware-shaped placeholder; CONFIGURE no
// longer accepts this placeholder after synthetic stream support is enabled.
inline constexpr protocol::Configuration kIdleConfiguration{
    0U,
    protocol_v1::Source::kHardware,
    protocol_v1::kDefaultChecksumAlgorithm,
    static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes),
};

inline constexpr protocol::Configuration kSyntheticConfiguration{
    capabilities::kSupportedStreamMask,
    protocol_v1::Source::kSynthetic,
    protocol_v1::kDefaultChecksumAlgorithm,
    static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes),
};

inline constexpr protocol::Configuration kPhysicalGpioConfiguration{
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio),
    protocol_v1::Source::kHardware,
    protocol_v1::kDefaultChecksumAlgorithm,
    static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes),
};

inline constexpr protocol::Configuration kPhysicalAdcConfiguration{
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc),
    protocol_v1::Source::kHardware,
    protocol_v1::kDefaultChecksumAlgorithm,
    static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes),
};

inline constexpr protocol::Configuration kPhysicalCombinedConfiguration{
    capabilities::kSupportedStreamMask,
    protocol_v1::Source::kHardware,
    protocol_v1::kDefaultChecksumAlgorithm,
    static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes),
};

enum class Event : std::uint8_t {
  kNone = 0U,
  kStartEpoch = 1U,
  kStop = 2U,
};

constexpr std::uint8_t eventBit(Event event) {
  return static_cast<std::uint8_t>(event);
}

struct PendingEvents {
  std::uint8_t mask = 0U;
  std::uint32_t run_id = 0U;
  std::uint32_t stats_generation = 1U;

  constexpr bool has(Event event) const {
    return (mask & eventBit(event)) != 0U;
  }
};

enum class DispatchStatus : std::uint8_t {
  kNoResponse,
  kResponseReady,
  kEncodingFailure,
};

struct DispatchResult {
  DispatchStatus status = DispatchStatus::kNoResponse;
  protocol_v1::ErrorCode command_error =
      protocol_v1::ErrorCode::kInvalidState;
  protocol::Result encoding = protocol::Result::success();

  constexpr bool responseReady() const {
    return status == DispatchStatus::kResponseReady;
  }
  constexpr bool commandAccepted() const {
    return responseReady() && command_error == protocol_v1::ErrorCode::kOk;
  }
};

// Runtime-owned resources may need a bounded drain after STOP even though the
// protocol state is already IDLE. Keeping these readiness inputs explicit lets
// CONFIGURE and START return BUSY without changing algorithms, allocating a
// run ID, or mutating control state until every prior-run frame is gone.
struct DispatchReadiness {
  bool start_ready = true;
  bool configuration_ready = true;
  bool statistics_reset_ready = true;
  const protocol::ChecksumBenchmarkResponse *checksum_benchmark_response =
      nullptr;
  protocol_v1::ErrorCode checksum_benchmark_error =
      protocol_v1::ErrorCode::kUnsupportedConfiguration;
  const protocol::GpioClockDiagnosticResponse *gpio_clock_response = nullptr;
  protocol_v1::ErrorCode gpio_clock_error =
      protocol_v1::ErrorCode::kUnsupportedConfiguration;
  const protocol::GpioCaptureDiagnosticResponse *gpio_capture_response =
      nullptr;
  protocol_v1::ErrorCode gpio_capture_error =
      protocol_v1::ErrorCode::kUnsupportedConfiguration;
};

class ControlState {
 public:
  constexpr ControlState() = default;

  // Constant-time, idempotent BOOT completion. The future sketch supplies the
  // chip-derived USB serial before command polling begins.
  bool completeBoot(
      std::uint32_t hardware_serial,
      const protocol::AdcInitializationMetadata &adc_metadata = {});

  // Fail safe after an internal main-loop or response-path fault. Expected
  // typed command rejections do not use this path and remain state-atomic.
  // Recovery preserves the current run ID/statistics, clears configuration,
  // cancels an unconsumed START event, and signals STOP when work may exist.
  bool recoverToIdle();

  // Request identifiers are unique only within one CDC host session. DTR
  // reopen clears this bounded replay window without changing acquisition
  // state, run identity, configuration, or counters.
  void beginHostSession();

  DispatchResult dispatch(
      const protocol::Request &request, protocol::ControlFrame &response,
      DispatchReadiness readiness = DispatchReadiness{});

  constexpr protocol_v1::DeviceState state() const { return state_; }
  constexpr std::uint32_t runId() const { return run_id_; }
  constexpr std::uint32_t hardwareSerial() const { return hardware_serial_; }
  constexpr bool hasConfiguration() const { return has_configuration_; }
  constexpr protocol::Configuration appliedConfiguration() const {
    return has_configuration_ ? configuration_ : kIdleConfiguration;
  }

  constexpr const stats::Statistics &statistics() const { return statistics_; }
  constexpr stats::Statistics &statistics() { return statistics_; }

  PendingEvents takePendingEvents();

  static constexpr std::uint32_t nextRunId(std::uint32_t current) {
    const std::uint32_t next = current + 1U;
    return next == 0U ? 1U : next;
  }

  static constexpr bool isLegalTransition(protocol_v1::DeviceState from,
                                          protocol_v1::DeviceState to) {
    switch (from) {
      case protocol_v1::DeviceState::kBoot:
        return to == protocol_v1::DeviceState::kIdle;
      case protocol_v1::DeviceState::kIdle:
        return to == protocol_v1::DeviceState::kIdle ||
               to == protocol_v1::DeviceState::kConfigured;
      case protocol_v1::DeviceState::kConfigured:
        return to == protocol_v1::DeviceState::kIdle ||
               to == protocol_v1::DeviceState::kConfigured ||
               to == protocol_v1::DeviceState::kRunning;
      case protocol_v1::DeviceState::kRunning:
        return to == protocol_v1::DeviceState::kIdle;
    }
    return false;
  }

  static protocol_v1::ErrorCode validateConfiguration(
      const protocol::Configuration &configuration);

 private:
  bool transitionTo(protocol_v1::DeviceState next);
  DispatchResult reject(const protocol::Request &request,
                        protocol_v1::ErrorCode error,
                        protocol::ControlFrame &response);
  DispatchResult encoded(const protocol::Request &request,
                         protocol_v1::ErrorCode command_error,
                         protocol::Result encoding,
                         protocol::ControlFrame &response);
  protocol::InfoResponse infoResponse() const;
  bool rememberRequestId(std::uint32_t request_id);

  protocol_v1::DeviceState state_ = protocol_v1::DeviceState::kBoot;
  protocol::Configuration configuration_ = kIdleConfiguration;
  bool has_configuration_ = false;
  std::uint32_t run_id_ = 0U;
  std::uint32_t hardware_serial_ = 0U;
  protocol::AdcInitializationMetadata adc_metadata_{};
  std::uint8_t pending_event_mask_ = 0U;
  std::array<std::uint32_t, kRecentRequestIdWindow> recent_request_ids_{};
  std::size_t recent_request_count_ = 0U;
  std::size_t next_request_slot_ = 0U;
  stats::Statistics statistics_{};
};

static_assert(kIdleConfiguration.stream_mask == 0U);
static_assert(kIdleConfiguration.source ==
              protocol_v1::Source::kHardware);
static_assert(kSyntheticConfiguration.stream_mask == 3U);
static_assert(kSyntheticConfiguration.source ==
              protocol_v1::Source::kSynthetic);
static_assert(kPhysicalGpioConfiguration.stream_mask == 2U);
static_assert(kPhysicalGpioConfiguration.source ==
              protocol_v1::Source::kHardware);
static_assert(kPhysicalAdcConfiguration.stream_mask == 1U);
static_assert(kPhysicalAdcConfiguration.source ==
              protocol_v1::Source::kHardware);
static_assert(kPhysicalCombinedConfiguration.stream_mask == 3U);
static_assert(kPhysicalCombinedConfiguration.source ==
              protocol_v1::Source::kHardware);
static_assert(capabilities::kSupportedStreamMask == 3U);
static_assert(kRecentRequestIdWindow >= 2U);
static_assert(ControlState::nextRunId(0U) == 1U);
static_assert(ControlState::nextRunId(0xFFFFFFFFU) == 1U);
static_assert(ControlState::isLegalTransition(
    protocol_v1::DeviceState::kBoot, protocol_v1::DeviceState::kIdle));
static_assert(!ControlState::isLegalTransition(
    protocol_v1::DeviceState::kIdle, protocol_v1::DeviceState::kRunning));

}  // namespace teensy_daq::control
