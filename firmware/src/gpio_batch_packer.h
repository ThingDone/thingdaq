#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "gpio_raw_capture.h"
#include "packet_buffer_pipeline.h"
#include "statistics.h"

namespace teensy_daq::gpio_packer {

inline constexpr const char kBatchAlgorithmName[] =
    "shift-mask-unrolled-4";
inline constexpr std::size_t kPackedWireBytesPerSample = 1U;

// Hot scalar primitive selected for the batch loop. The source identities are
// compile-time bound to board::kGpioMappingsByPackedBit; unrelated GPIO2 bits
// are discarded.
constexpr std::uint8_t packGpio2Word(std::uint32_t word) {
  return static_cast<std::uint8_t>(
      ((word >> 10U) & 0x01U) | ((word >> 16U) & 0x02U) |
      ((word >> 14U) & 0x04U) | ((word >> 8U) & 0x08U) |
      ((word << 4U) & 0x10U) | ((word << 3U) & 0x20U) |
      ((word << 5U) & 0x40U) | ((word << 4U) & 0x80U));
}

// Convert a contiguous raw-word batch without allocation or virtual dispatch.
// Returns zero on an invalid view; otherwise exactly sample_count bytes.
std::size_t packGpio2Batch(const std::uint32_t *source,
                           std::size_t sample_count,
                           std::uint8_t *destination,
                           std::size_t destination_capacity);

enum class BufferState : std::uint8_t {
  kFree = 0U,
  kFilling = 1U,
  kReady = 2U,
  kFraming = 3U,
};

struct alignas(board::kCacheLineBytes) PackedBuffer {
  std::array<std::uint8_t, protocol_v1::kDataPayloadBytes> bytes{};
};

struct alignas(board::kCacheLineBytes) PackedBufferStorage {
  std::array<PackedBuffer, board::kGpioPackedRingDepth> buffers{};
};

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
  std::size_t raw_buffers_consumed = 0U;
  std::size_t samples_consumed = 0U;
  std::size_t frames_packed = 0U;
  std::size_t frames_framed = 0U;
  std::size_t frames_dropped = 0U;
  bool waiting_for_raw_buffer = false;
  bool waiting_for_packet_buffer = false;
  bool raw_work_limit_reached = false;
  bool frame_work_limit_reached = false;
  bool source_error = false;
  bool pipeline_error = false;
};

struct StopReport {
  std::uint32_t partial_samples_discarded = 0U;
  std::size_t packed_frames_to_drain = 0U;
  std::uint64_t dropped_frames_to_publish = 0U;
};

struct Snapshot {
  stats::GpioPackerProgress progress{};
  std::array<BufferState, board::kGpioPackedRingDepth> buffer_states{};
  std::uint32_t run_id = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint64_t next_source_sample = 0U;
  std::uint64_t pending_dropped_frames = 0U;
  std::uint32_t current_frame_samples = 0U;
  std::size_t ready_depth = 0U;
  std::size_t ready_high_water = 0U;
  std::uint64_t service_calls = 0U;
  std::uint64_t raw_buffers_acquired = 0U;
  std::uint64_t raw_buffers_released = 0U;
  std::uint64_t duplicate_samples_ignored = 0U;
  std::uint32_t source_errors = 0U;
  std::uint32_t pipeline_errors = 0U;
  std::uint32_t chronology_errors = 0U;
  bool running = false;
  bool input_gap_pending = false;
  bool packet_gap_pending = false;
  bool quiescent = true;
};

// Cooperative raw-to-wire bridge. DMA ownership is acquired and released once
// per batch; all bit gathering, packed-ring ownership, frame construction,
// checksum work, and queue mutation happen outside interrupts.
class GpioBatchPacker final {
 public:
  GpioBatchPacker(gpio_capture::RawWordSource &source,
                  PackedBufferStorage &storage)
      : source_(source), storage_(storage) {}
  GpioBatchPacker(const GpioBatchPacker &) = delete;
  GpioBatchPacker &operator=(const GpioBatchPacker &) = delete;

  OperationStatus startRun(
      std::uint32_t run_id,
      protocol_v1::ChecksumAlgorithm checksum_algorithm,
      const packet::PacketBufferPipeline &pipeline);
  StopReport stopProduction();

  ServiceReport service(
      packet::PacketBufferPipeline &pipeline,
      std::size_t raw_buffer_limit = board::kGpioRawBuffersPerLoop,
      std::size_t frame_limit = board::kGpioPackedFramesPerLoop);

  Snapshot snapshot(const packet::PacketBufferPipeline &pipeline) const;
  bool quiescent() const;
  bool readyForStart() const;

 private:
  static constexpr std::uint8_t kInvalidBuffer = 0xFFU;

  struct BufferRecord {
    BufferState state = BufferState::kFree;
    std::uint64_t first_sample = 0U;
    std::uint64_t dropped_frames_before = 0U;
    std::uint64_t raw_drop_samples_before = 0U;
    std::uint64_t packer_drop_samples_before = 0U;
    bool gap_before = false;
  };

  using ReadyQueue = usb::detail::FixedQueue<
      std::uint8_t, board::kGpioPackedRingDepth>;

  bool pipelineMatches(const packet::PacketBufferPipeline &pipeline) const;
  bool consume(const gpio_capture::BufferHandle &handle,
               ServiceReport &report);
  void accountRawGap(std::uint64_t sample_count, ServiceReport &report);
  void consumeAvailable(const std::uint32_t *source,
                        std::size_t sample_count,
                        ServiceReport &report);
  bool ensureFillingBuffer();
  void invalidateCurrentFrame();
  void finishInvalidFrame(ServiceReport &report);
  void finishPackedFrame(ServiceReport &report);
  void resetCurrentFrame();
  bool packetizeOne(packet::PacketBufferPipeline &pipeline,
                    ServiceReport &report);
  bool applyDroppedFrames(packet::PacketBufferPipeline &pipeline,
                          std::uint64_t frames,
                          std::uint64_t raw_samples,
                          std::uint64_t packer_samples);
  bool flushTrailingDrops(packet::PacketBufferPipeline &pipeline);
  std::uint8_t takeFreeBuffer();
  void recycle(std::uint8_t index);
  std::size_t countState(BufferState state) const;
  stats::GpioPackerProgress progress(
      const packet::PacketBufferPipeline &pipeline) const;

  gpio_capture::RawWordSource &source_;
  PackedBufferStorage &storage_;
  std::array<BufferRecord, board::kGpioPackedRingDepth> records_{};
  ReadyQueue ready_queue_{};
  stats::GpioPackerProgress progress_{};
  std::uint64_t pending_dropped_frames_ = 0U;
  std::uint64_t pending_raw_drop_samples_ = 0U;
  std::uint64_t pending_packer_drop_samples_ = 0U;
  std::uint64_t prepacket_frames_dropped_ = 0U;
  std::uint64_t prepacket_frames_projected_ = 0U;
  std::uint64_t next_source_sample_ = 0U;
  std::uint64_t service_calls_ = 0U;
  std::uint64_t raw_buffers_acquired_ = 0U;
  std::uint64_t raw_buffers_released_ = 0U;
  std::uint64_t duplicate_samples_ignored_ = 0U;
  std::uint64_t current_raw_drop_samples_ = 0U;
  std::uint64_t current_packer_drop_samples_ = 0U;
  std::uint32_t run_id_ = 0U;
  std::uint32_t current_frame_samples_ = 0U;
  std::uint32_t source_errors_ = 0U;
  std::uint32_t pipeline_errors_ = 0U;
  std::uint32_t chronology_errors_ = 0U;
  std::size_t next_free_search_ = 0U;
  std::size_t ready_high_water_ = 0U;
  std::uint8_t filling_buffer_ = kInvalidBuffer;
  protocol_v1::ChecksumAlgorithm checksum_algorithm_ =
      protocol_v1::kDefaultChecksumAlgorithm;
  bool current_frame_invalid_ = false;
  bool input_gap_pending_ = false;
  bool packet_gap_pending_ = false;
  bool running_ = false;
};

static_assert(kPackedWireBytesPerSample == 1U);
static_assert(sizeof(PackedBuffer) == board::kGpioPackedBufferStrideBytes);
static_assert(alignof(PackedBuffer) == board::kCacheLineBytes);
static_assert(sizeof(PackedBufferStorage) ==
              board::kGpioPackedRingDepth *
                  board::kGpioPackedBufferStrideBytes);
static_assert(alignof(PackedBufferStorage) == board::kCacheLineBytes);
static_assert(sizeof(GpioBatchPacker) <= board::kGpioPackerStateBudgetBytes);
static_assert(protocol_v1::kGpioSamplePeriodTicks == 2U);
static_assert(protocol_v1::kGpioSamplesPerFrame ==
              protocol_v1::kDataPayloadBytes);
static_assert(board::kGpioMappingsByPackedBit[0].gpio2_bit == 10U);
static_assert(board::kGpioMappingsByPackedBit[1].gpio2_bit == 17U);
static_assert(board::kGpioMappingsByPackedBit[2].gpio2_bit == 16U);
static_assert(board::kGpioMappingsByPackedBit[3].gpio2_bit == 11U);
static_assert(board::kGpioMappingsByPackedBit[4].gpio2_bit == 0U);
static_assert(board::kGpioMappingsByPackedBit[5].gpio2_bit == 2U);
static_assert(board::kGpioMappingsByPackedBit[6].gpio2_bit == 1U);
static_assert(board::kGpioMappingsByPackedBit[7].gpio2_bit == 3U);

}  // namespace teensy_daq::gpio_packer
