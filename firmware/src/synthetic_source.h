#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "packet_buffer_pipeline.h"
#include "protocol.h"

namespace teensy_daq::synthetic {

// REALTIME is the production default: a frame is eligible only after all of
// its logical samples have occurred at the advertised 8 MHz timeline.
// UNPACED_DIAGNOSTIC is deliberately named and must be selected explicitly;
// it exercises the identical generator, packetizer, checksum, queues, and USB
// path without waiting for wall-clock deadlines.
enum class Mode : std::uint8_t {
  kRealtime = 0U,
  kUnpacedDiagnostic = 1U,
};

constexpr const char *modeName(Mode mode) {
  return mode == Mode::kRealtime ? "realtime" : "unpaced-diagnostic";
}

// Platform adapters expose monotonically sampled unsigned 8 MHz ticks. The
// synthetic source stores one START reading and publishes sample timestamps
// relative to that shared epoch, so both streams begin at tick zero.
class TickClock {
 public:
  virtual ~TickClock() = default;
  virtual std::uint64_t nowTicks() = 0;
};

enum class OperationStatus : std::uint8_t {
  kOk,
  kInvalidRunId,
  kInvalidConfiguration,
  kPipelineNotReady,
  kNotRunning,
};

struct StreamSnapshot {
  std::uint64_t frames_generated = 0U;
  std::uint64_t items_generated = 0U;
  std::uint64_t next_item_index = 0U;
  std::uint64_t next_frame_first_ticks = 0U;
  bool epoch_frame_pending = false;
  bool gap_before_pending = false;
};

struct Snapshot {
  std::array<StreamSnapshot, packet::kStreamCount> streams{};
  protocol::Configuration configuration{};
  Mode mode = Mode::kRealtime;
  std::uint32_t run_id = 0U;
  std::uint64_t start_clock_ticks = 0U;
  std::uint64_t last_elapsed_ticks = 0U;
  std::uint64_t service_calls = 0U;
  std::uint64_t frames_framed = 0U;
  std::uint64_t frames_dropped = 0U;
  std::size_t next_stream = 0U;
  bool running = false;
};

struct ServiceReport {
  std::size_t frames_generated = 0U;
  std::size_t frames_framed = 0U;
  std::size_t frames_dropped = 0U;
  bool work_limit_reached = false;
  bool waiting_for_deadline = false;
  bool waiting_for_buffer = false;
  bool invariant_error = false;
};

class SyntheticSource {
 public:
  explicit constexpr SyntheticSource(Mode mode = Mode::kRealtime)
      : mode_(mode) {}

  OperationStatus startRun(std::uint32_t run_id,
                           const protocol::Configuration &configuration,
                           std::uint64_t start_clock_ticks,
                           const packet::PacketBufferPipeline &pipeline);
  void stop();

  ServiceReport service(std::uint64_t now_ticks,
                        packet::PacketBufferPipeline &pipeline);

  Snapshot snapshot() const;
  constexpr Mode mode() const { return mode_; }
  constexpr bool running() const { return running_; }

  static constexpr std::uint16_t adc0Code(std::uint64_t pair_index) {
    return static_cast<std::uint16_t>(
        (pair_index * 2U) & kAdcCodeMask);
  }
  static constexpr std::uint16_t adc1Code(std::uint64_t pair_index) {
    return static_cast<std::uint16_t>(
        (pair_index * 2U + 1U) & kAdcCodeMask);
  }
  static constexpr std::uint8_t gpioByte(std::uint64_t sample_index) {
    return static_cast<std::uint8_t>(sample_index & 0xFFU);
  }

 private:
  static constexpr std::uint16_t kAdcCodeMask =
      static_cast<std::uint16_t>(
          (1U << protocol_v1::kAdcResolutionBits) - 1U);

  struct StreamState {
    std::uint64_t logical_frames = 0U;
    std::uint64_t frames_generated = 0U;
    std::uint64_t items_generated = 0U;
    bool epoch_frame_pending = true;
    bool gap_before_pending = false;
  };

  bool streamEnabled(packet::Stream stream) const;
  bool frameDue(packet::Stream stream, std::uint64_t elapsed_ticks) const;
  packet::Stream selectDueStream(std::uint64_t elapsed_ticks,
                                 bool &selected) const;
  bool generateFrame(packet::Stream stream,
                     packet::PacketBufferPipeline &pipeline,
                     ServiceReport &report);
  static void fillAdc(protocol::MutableByteView payload,
                      std::uint64_t first_pair_index);
  static void fillGpio(protocol::MutableByteView payload,
                       std::uint64_t first_sample_index);

  std::array<StreamState, packet::kStreamCount> streams_{};
  protocol::Configuration configuration_{};
  Mode mode_ = Mode::kRealtime;
  std::uint32_t run_id_ = 0U;
  std::uint64_t start_clock_ticks_ = 0U;
  std::uint64_t last_elapsed_ticks_ = 0U;
  std::uint64_t service_calls_ = 0U;
  std::uint64_t frames_framed_ = 0U;
  std::uint64_t frames_dropped_ = 0U;
  std::size_t next_stream_ = 0U;
  bool running_ = false;
};

inline constexpr std::uint64_t kFrameCoverageTicks =
    static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame) *
    protocol_v1::kAdcPairPeriodTicks;

static_assert(kFrameCoverageTicks ==
              static_cast<std::uint64_t>(
                  protocol_v1::kGpioSamplesPerFrame) *
                  protocol_v1::kGpioSamplePeriodTicks);
static_assert(protocol_v1::kTimestampHz == 8000000U);
static_assert(protocol_v1::kAdcPairRateHz == 1000000U);
static_assert(protocol_v1::kGpioSampleRateHz == 4000000U);
static_assert(protocol_v1::kAdcPairPeriodTicks == 8U);
static_assert(protocol_v1::kAdc1PhaseTicks == 4U);
static_assert(protocol_v1::kGpioSamplePeriodTicks == 2U);
static_assert(protocol_v1::kAdcContainerBits == 16U);
static_assert(protocol_v1::kAdcResolutionBits == 12U);
static_assert(SyntheticSource::adc0Code(0U) == 0U);
static_assert(SyntheticSource::adc1Code(0U) == 1U);
static_assert(SyntheticSource::adc0Code(2048U) == 0U);
static_assert(SyntheticSource::adc1Code(2048U) == 1U);
static_assert(SyntheticSource::gpioByte(256U) == 0U);

}  // namespace teensy_daq::synthetic
