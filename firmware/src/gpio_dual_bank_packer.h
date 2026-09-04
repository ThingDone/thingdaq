#pragma once

#include <cstddef>
#include <cstdint>

#include "gpio_batch_packer.h"
#include "gpio_dual_bank_capture.h"
#include "packet_buffer_pipeline.h"
#include "statistics.h"
#include "stream_layout.h"

namespace thingdaq::gpio_aux_packer {

inline constexpr std::size_t kPackedWireBytesPerSample = 2U;

// GPIO2 is the established low byte. GPIO1 is gathered into the high byte in
// D16-D23 order. These are raw PSR word operations, never per-pin APIs.
constexpr std::uint8_t packGpio1Word(std::uint32_t word) {
  return static_cast<std::uint8_t>(
      ((word >> 23U) & 0x01U) | ((word >> 21U) & 0x02U) |
      ((word >> 15U) & 0x04U) | ((word >> 13U) & 0x08U) |
      ((word >> 22U) & 0x10U) | ((word >> 22U) & 0x20U) |
      ((word >> 18U) & 0x40U) | ((word >> 18U) & 0x80U));
}

constexpr std::uint16_t packDualBankWord(std::uint32_t gpio2_word,
                                         std::uint32_t gpio1_word) {
  return static_cast<std::uint16_t>(
      gpio_packer::packGpio2Word(gpio2_word) |
      (static_cast<std::uint16_t>(packGpio1Word(gpio1_word)) << 8U));
}

// Serializes exact little-endian uint16 samples into destination. Returns the
// number of logical samples written, or zero for an invalid view.
std::size_t packDualBankBatch(const std::uint32_t *primary_words,
                              const std::uint32_t *auxiliary_words,
                              std::size_t sample_count,
                              std::uint8_t *destination,
                              std::size_t destination_capacity);

enum class OperationStatus : std::uint8_t {
  kOk,
  kInvalidRunId,
  kUnsupportedProfile,
  kPipelineNotReady,
  kNotQuiescent,
  kNotRunning,
  kSourceError,
  kPipelineError,
};

struct ServiceReport {
  std::size_t buffers_consumed = 0U;
  std::size_t samples_consumed = 0U;
  std::size_t frames_packed = 0U;
  std::size_t frames_framed = 0U;
  std::size_t frames_dropped = 0U;
  bool waiting_for_buffer = false;
  bool work_limit_reached = false;
  bool source_error = false;
  bool pipeline_error = false;
};

struct Snapshot {
  stats::GpioPackerProgress progress{};
  stream_layout::RunLayout layout{};
  std::uint64_t next_sample_ticks = 0U;
  std::uint64_t start_epoch_ticks = 0U;
  std::uint64_t service_calls = 0U;
  std::uint32_t run_id = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t source_errors = 0U;
  std::uint32_t pipeline_errors = 0U;
  std::uint32_t chronology_errors = 0U;
  bool packet_gap_pending = false;
  bool running = false;
  bool quiescent = true;
};

// Cooperative bridge from a matched dual-bank raw lease into the existing
// packet pool. The established one-bank GpioBatchPacker remains the disabled
// mode implementation; this class can start only with a generated INPUT
// layout and a packet pipeline already bound to that exact layout.
class AuxiliaryBatchPacker final {
 public:
  explicit constexpr AuxiliaryBatchPacker(
      gpio_join::PairedRawSource &source,
      gpio_packer::CycleCounter *cycle_counter = nullptr)
      : source_(source), cycle_counter_(cycle_counter) {}

  AuxiliaryBatchPacker(const AuxiliaryBatchPacker &) = delete;
  AuxiliaryBatchPacker &operator=(const AuxiliaryBatchPacker &) = delete;

  OperationStatus startRun(
      std::uint32_t run_id,
      protocol_v1::ChecksumAlgorithm checksum_algorithm,
      protocol_v2::RateProfile profile,
      const packet::PacketBufferPipeline &pipeline,
      std::uint64_t start_epoch_ticks = 0U);
  void stopProduction();
  ServiceReport service(packet::PacketBufferPipeline &pipeline,
                        std::size_t buffer_limit = 2U);
  Snapshot snapshot(const packet::PacketBufferPipeline &pipeline) const;

  constexpr bool quiescent() const { return !running_; }
  constexpr bool readyForStart() const { return quiescent(); }

 private:
  bool pipelineMatches(const packet::PacketBufferPipeline &pipeline) const;
  bool consume(const gpio_join::BufferHandle &handle,
               packet::PacketBufferPipeline &pipeline,
               ServiceReport &report);
  bool projectRawGap(std::uint64_t missing_frames,
                     packet::PacketBufferPipeline &pipeline);
  stats::GpioPackerProgress progress(
      const packet::PacketBufferPipeline &pipeline) const;
  std::uint32_t beginProfile();
  void finishProfile(std::uint32_t started_at);
  std::uint16_t processingCpuBasisPoints() const;

  gpio_join::PairedRawSource &source_;
  gpio_packer::CycleCounter *cycle_counter_ = nullptr;
  stream_layout::RunLayout layout_{};
  stats::GpioPackerProgress progress_{};
  std::uint64_t next_sample_ticks_ = 0U;
  std::uint64_t start_epoch_ticks_ = 0U;
  std::uint64_t service_calls_ = 0U;
  std::uint64_t processing_elapsed_cycles_ = 0U;
  std::uint64_t processing_active_cycles_ = 0U;
  std::uint32_t profile_last_cycle_ = 0U;
  std::uint32_t run_id_ = 0U;
  std::uint32_t source_errors_ = 0U;
  std::uint32_t pipeline_errors_ = 0U;
  std::uint32_t chronology_errors_ = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm_ =
      protocol_v1::kDefaultChecksumAlgorithm;
  bool packet_gap_pending_ = false;
  bool processing_profile_active_ = false;
  bool running_ = false;
};

static_assert(kPackedWireBytesPerSample == 2U);
static_assert(packGpio1Word(std::uint32_t{1U} << 23U) == 0x01U);
static_assert(packGpio1Word(std::uint32_t{1U} << 22U) == 0x02U);
static_assert(packGpio1Word(std::uint32_t{1U} << 17U) == 0x04U);
static_assert(packGpio1Word(std::uint32_t{1U} << 16U) == 0x08U);
static_assert(packGpio1Word(std::uint32_t{1U} << 26U) == 0x10U);
static_assert(packGpio1Word(std::uint32_t{1U} << 27U) == 0x20U);
static_assert(packGpio1Word(std::uint32_t{1U} << 24U) == 0x40U);
static_assert(packGpio1Word(std::uint32_t{1U} << 25U) == 0x80U);
static_assert(packDualBankWord(std::uint32_t{1U} << 10U,
                              std::uint32_t{1U} << 25U) == 0x8001U);

}  // namespace thingdaq::gpio_aux_packer
