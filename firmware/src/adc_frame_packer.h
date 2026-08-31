#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "adc_dma_capture.h"
#include "packet_buffer_pipeline.h"
#include "statistics.h"

namespace thingdaq::adc_packer {

enum class OperationStatus : std::uint8_t {
  kOk,
  kInvalidRunId,
  kPipelineNotReady,
  kNotQuiescent,
  kNotRunning,
  kSourceError,
  kPipelineError,
};

struct ServiceReport {
  std::size_t buffers_consumed = 0U;
  std::size_t pairs_consumed = 0U;
  std::size_t frames_framed = 0U;
  std::size_t frames_dropped = 0U;
  bool waiting_for_buffer = false;
  bool waiting_for_packet_buffer = false;
  bool work_limit_reached = false;
  bool source_error = false;
  bool pipeline_error = false;
};

struct StopReport {
  bool packet_gap_unreported = false;
};

struct Snapshot {
  stats::AdcPackerProgress progress{};
  std::uint32_t run_id = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint64_t next_source_pair = 0U;
  std::uint64_t start_epoch_ticks = 0U;
  std::uint64_t service_calls = 0U;
  bool running = false;
  bool packet_gap_pending = false;
  bool quiescent = true;
};

// Main-loop bridge from complete dual-DMA generations to immutable packet
// buffers. Each source buffer is already one canonical ADC payload, so this
// owner preserves its adc0/adc1 halfword order with one bounded copy and
// releases the DMA lease before USB can retain the resulting frame.
class AdcFramePacker final {
 public:
  explicit constexpr AdcFramePacker(adc_capture::PairSource &source)
      : source_(source) {}
  AdcFramePacker(const AdcFramePacker &) = delete;
  AdcFramePacker &operator=(const AdcFramePacker &) = delete;

  OperationStatus startRun(
      std::uint32_t run_id,
      protocol_v1::ChecksumAlgorithm checksum_algorithm,
      const packet::PacketBufferPipeline &pipeline,
      std::uint64_t start_epoch_ticks = 0U);
  StopReport stopProduction();
  ServiceReport service(
      packet::PacketBufferPipeline &pipeline,
      std::size_t buffer_limit = board::kAdcFramesPerLoop);

  Snapshot snapshot(const packet::PacketBufferPipeline &pipeline) const;
  constexpr bool quiescent() const { return !running_; }
  constexpr bool readyForStart() const { return quiescent(); }

 private:
  bool pipelineMatches(const packet::PacketBufferPipeline &pipeline) const;
  bool consume(const adc_capture::BufferHandle &handle,
               packet::PacketBufferPipeline &pipeline,
               ServiceReport &report);
  bool projectRawGap(std::uint64_t pair_count,
                     packet::PacketBufferPipeline &pipeline);
  stats::AdcPackerProgress progress(
      const packet::PacketBufferPipeline &pipeline) const;

  adc_capture::PairSource &source_;
  stats::AdcPackerProgress progress_{};
  std::uint64_t next_source_pair_ = 0U;
  std::uint64_t start_epoch_ticks_ = 0U;
  std::uint64_t service_calls_ = 0U;
  std::uint32_t run_id_ = 0U;
  std::uint32_t source_errors_ = 0U;
  std::uint32_t pipeline_errors_ = 0U;
  std::uint32_t chronology_errors_ = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm_ =
      protocol_v1::kDefaultChecksumAlgorithm;
  bool packet_gap_pending_ = false;
  bool running_ = false;
};

static_assert(sizeof(adc_capture::SamplePair) ==
              protocol_v1::kAdcBytesPerPair);
static_assert(std::is_trivially_copyable_v<adc_capture::SamplePair>);
#if defined(__BYTE_ORDER__) && defined(__ORDER_LITTLE_ENDIAN__)
static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__,
              "direct ADC pair packetization requires little-endian storage");
#endif
static_assert(protocol_v1::kAdcPairPeriodTicks == 8U);
static_assert(protocol_v1::kAdc1PhaseTicks == 4U);
static_assert(sizeof(AdcFramePacker) <= board::kAdcPackerStateBudgetBytes);

}  // namespace thingdaq::adc_packer
