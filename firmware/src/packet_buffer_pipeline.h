#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "cycle_counter.h"
#include "protocol.h"
#include "rle_encoder.h"
#include "usb_transport.h"

namespace thingdaq::packet {

#if defined(THINGDAQ_TESTING)
struct PacketBufferPipelineTestAccess;
#endif

// These values describe ownership, not merely progress. Only FILLING exposes
// mutable payload bytes. READY is owned by a bounded per-source ready queue,
// and TRANSMITTING is immutable until CdcTransport releases the complete
// frame after its final byte. Recycling always returns through FREE.
enum class BufferState : std::uint8_t {
  kFree = 0U,
  kFilling = 1U,
  kReady = 2U,
  kTransmitting = 3U,
  // A TRANSFORMING page is a synchronous, non-evicting RLE destination. It
  // never survives finishFill(): success promotes it to READY, while every
  // fallback/failure path recycles it before returning.
  kTransforming = 4U,
};

inline constexpr std::size_t kBufferStateCount = 5U;

enum class Stream : std::uint8_t {
  kAdc = 0U,
  kGpio = 1U,
};

inline constexpr std::size_t kStreamCount = 2U;
inline constexpr std::uint8_t kInvalidBufferIndex = 0xFFU;
inline constexpr std::uint8_t kAdcStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc);
inline constexpr std::uint8_t kGpioStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
inline constexpr std::uint8_t kAllStreamMask =
    static_cast<std::uint8_t>(kAdcStreamMask | kGpioStreamMask);

constexpr std::size_t streamIndex(Stream stream) {
  return static_cast<std::size_t>(stream);
}

constexpr bool validStream(Stream stream) {
  return streamIndex(stream) < kStreamCount;
}

constexpr std::uint8_t streamBit(Stream stream) {
  return stream == Stream::kAdc ? kAdcStreamMask : kGpioStreamMask;
}

constexpr bool validStreamMask(std::uint8_t mask) {
  return mask != 0U && (mask & static_cast<std::uint8_t>(~kAllStreamMask)) == 0U;
}

constexpr bool streamEnabled(std::uint8_t mask, Stream stream) {
  return validStream(stream) && (mask & streamBit(stream)) != 0U;
}

constexpr protocol_v1::FrameKind frameKind(Stream stream) {
  return stream == Stream::kAdc ? protocol_v1::FrameKind::kAdcData
                                : protocol_v1::FrameKind::kGpioData;
}

constexpr protocol_v2::FrameKind v2FrameKind(Stream stream) {
  return stream == Stream::kAdc ? protocol_v2::FrameKind::kAdcData
                                : protocol_v2::FrameKind::kGpioData;
}

// Control integration maps an accepted configuration to this immutable
// per-run format. Existing callers receive the exact v1/RAW default.
struct RunFrameFormat {
  std::uint8_t protocol_version = protocol_v1::kProtocolVersion;
  protocol_v2::ConfigurationEncoding encoding =
      protocol_v2::ConfigurationEncoding::kRaw;

  constexpr bool valid() const {
    const bool raw =
        encoding == protocol_v2::ConfigurationEncoding::kRaw;
    const bool rle_auto =
        encoding == protocol_v2::ConfigurationEncoding::kRleAuto;
    return (protocol_version == protocol_v1::kProtocolVersion && raw) ||
           (protocol_version == protocol_v2::kProtocolVersion &&
            (raw || rle_auto));
  }

  constexpr bool rleAuto() const {
    return protocol_version == protocol_v2::kProtocolVersion &&
           encoding == protocol_v2::ConfigurationEncoding::kRleAuto;
  }
};

enum class RawFallbackReason : std::uint8_t {
  kNone = 0U,
  kNotRequested,
  kRleNotSmaller,
  kTemporaryPageUnavailable,
  kEncoderFailure,
};

constexpr std::uint32_t itemsPerFrame(Stream stream) {
  return stream == Stream::kAdc
             ? static_cast<std::uint32_t>(protocol_v1::kAdcPairsPerFrame)
             : static_cast<std::uint32_t>(
                   protocol_v1::kGpioSamplesPerFrame);
}

constexpr std::uint32_t payloadBytesPerItem(Stream stream) {
  return stream == Stream::kAdc
             ? static_cast<std::uint32_t>(protocol_v1::kAdcBytesPerPair)
             : 1U;
}

constexpr std::uint64_t roundedRate(std::uint64_t bytes_per_frame) {
  return (bytes_per_frame * protocol_v1::kTimestampHz +
          protocol_v1::kFrameCoverageTicks / 2U) /
         protocol_v1::kFrameCoverageTicks;
}

inline constexpr std::uint64_t kNominalPayloadBytesPerSecondPerStream =
    roundedRate(protocol_v1::kDataPayloadBytes);
inline constexpr std::uint64_t kNominalFramedBytesPerSecondPerStream =
    roundedRate(protocol_v1::kDataFrameBytes);
inline constexpr std::uint64_t kNominalCombinedPayloadBytesPerSecond =
    kStreamCount * kNominalPayloadBytesPerSecondPerStream;
inline constexpr std::uint64_t kNominalCombinedFramedBytesPerSecond =
    kStreamCount * kNominalFramedBytesPerSecondPerStream;

using PacketFrame =
    std::array<std::uint8_t, protocol_v1::kDataFrameBytes>;

// Packet bytes stay CPU-owned: the pinned Teensy 1.62 USB Serial core memcpy()s
// each write into its own aligned DMAMEM TX ring and flushes that destination.
// The primary bank remains cacheless DTCM; the aligned reserve bank is cached
// OCRAM but is likewise never handed to USB DMA directly.
struct alignas(board::kCacheLineBytes) PacketBufferPrimaryStorage {
  std::array<PacketFrame, board::kPacketBufferPrimaryCount> frames{};
};

struct alignas(board::kCacheLineBytes) PacketBufferReserveStorage {
  std::array<PacketFrame, board::kPacketBufferReserveCount> frames{};
};

class PacketBufferStorage final {
 public:
  PacketBufferStorage(PacketBufferPrimaryStorage &primary,
                      PacketBufferReserveStorage &reserve)
      : primary_(primary), reserve_(reserve) {}
  PacketBufferStorage(const PacketBufferStorage &) = delete;
  PacketBufferStorage &operator=(const PacketBufferStorage &) = delete;

  PacketFrame &frame(std::size_t index) {
    return index < board::kPacketBufferPrimaryCount
               ? primary_.frames[index]
               : reserve_.frames[index - board::kPacketBufferPrimaryCount];
  }

  const PacketFrame &frame(std::size_t index) const {
    return index < board::kPacketBufferPrimaryCount
               ? primary_.frames[index]
               : reserve_.frames[index - board::kPacketBufferPrimaryCount];
  }

 private:
  PacketBufferPrimaryStorage &primary_;
  PacketBufferReserveStorage &reserve_;
};

#if !defined(ARDUINO_TEENSY40) || !defined(__IMXRT1062__)
// Portable tests own both banks contiguously on the host while exercising the
// same indexed view used by the split target placement.
class OwnedPacketBufferStorage final {
 public:
  OwnedPacketBufferStorage() : storage_(primary_, reserve_) {}

  operator PacketBufferStorage &() { return storage_; }
  PacketFrame &frame(std::size_t index) { return storage_.frame(index); }
  const PacketFrame &frame(std::size_t index) const {
    return storage_.frame(index);
  }

 private:
  PacketBufferPrimaryStorage primary_{};
  PacketBufferReserveStorage reserve_{};
  PacketBufferStorage storage_;
};
#endif

struct FillHandle {
  std::uint8_t buffer_index = kInvalidBufferIndex;
  Stream stream = Stream::kAdc;
  std::uint32_t sequence = 0U;
  std::uint32_t lease = 0U;

  constexpr bool valid() const {
    return buffer_index != kInvalidBufferIndex && validStream(stream) &&
           lease != 0U;
  }
};

struct FrameCompletion {
  std::uint64_t first_sample_ticks = 0U;
  std::uint16_t flags = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::size_t payload_bytes_written = 0U;
};

enum class OperationStatus : std::uint8_t {
  kOk,
  kInvalidRunId,
  kRunActive,
  kNotRunning,
  kPoolExhausted,
  kInvalidHandle,
  kIncompletePayload,
  kEncodingRejected,
  kQueueFull,
  kTransmissionPending,
  kUnsupportedChecksum,
  kChecksumMismatch,
  kInvalidStreamMask,
  kStreamDisabled,
  kUnsupportedFrameFormat,
};

struct BeginFillResult {
  OperationStatus status = OperationStatus::kNotRunning;
  FillHandle handle{};

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct FinishFillResult {
  OperationStatus status = OperationStatus::kInvalidHandle;
  protocol::Result encoding = protocol::Result::success();
  std::uint8_t protocol_version = protocol_v1::kProtocolVersion;
  protocol_v2::FrameEncoding frame_encoding =
      protocol_v2::FrameEncoding::kRaw;
  RawFallbackReason raw_fallback_reason = RawFallbackReason::kNotRequested;
  std::size_t payload_bytes = 0U;
  std::size_t frame_bytes = 0U;
  std::size_t rle_run_count = 0U;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct SourceCounters {
  std::uint64_t frames_produced = 0U;
  std::uint64_t items_produced = 0U;
  std::uint64_t frames_framed = 0U;
  std::uint64_t items_framed = 0U;
  std::uint64_t frames_emitted = 0U;
  std::uint64_t items_emitted = 0U;
  std::uint64_t frames_transmitted = 0U;
  std::uint64_t items_transmitted = 0U;
  std::uint64_t frames_dropped = 0U;
  std::uint64_t items_dropped = 0U;
  // Pressure evictions are the subset of drops where a complete, immutable,
  // not-yet-started frame was removed to admit newer live data.
  std::uint64_t frames_evicted = 0U;
  std::uint64_t items_evicted = 0U;
  std::uint64_t frames_evicted_after_promotion = 0U;
  // Every drop is classified by the latest ownership stage it reached. These
  // totals include pressure evictions and exceptional invariant/encoding
  // failures, so live conservation never has to infer a missing stage.
  std::uint64_t frames_dropped_after_framing = 0U;
  std::uint64_t frames_dropped_after_promotion = 0U;
  std::uint32_t next_sequence = 0U;
  std::size_t ready_queue_high_water = 0U;
  std::size_t transmit_queue_high_water = 0U;
};

// Byte totals are a derived view of the item/frame counters. Payload bytes
// exclude protocol overhead; framed bytes include the complete 4,096-byte
// wire frame. Keeping both prevents a nominal 8 MB/s payload target from
// being confused with the slightly larger CDC data-frame rate.
struct SourceByteCounters {
  std::uint64_t payload_bytes_produced = 0U;
  std::uint64_t payload_bytes_framed = 0U;
  std::uint64_t payload_bytes_emitted = 0U;
  std::uint64_t payload_bytes_transmitted = 0U;
  std::uint64_t payload_bytes_dropped = 0U;
  std::uint64_t payload_bytes_evicted = 0U;
  std::uint64_t framed_bytes_framed = 0U;
  std::uint64_t framed_bytes_emitted = 0U;
  std::uint64_t framed_bytes_transmitted = 0U;
  std::uint64_t framed_bytes_evicted = 0U;
  std::uint64_t encoded_payload_bytes_framed = 0U;
  std::uint64_t encoded_payload_bytes_emitted = 0U;
  std::uint64_t encoded_payload_bytes_transmitted = 0U;
  std::uint64_t encoded_payload_bytes_dropped = 0U;
  std::uint64_t encoded_payload_bytes_evicted = 0U;
  std::uint64_t encoded_payload_bytes_queued = 0U;
  std::uint64_t framed_bytes_dropped = 0U;
  std::uint64_t encoded_wire_bytes_queued = 0U;
};

// Mutable accounting keeps only cumulative selected-wire totals. Logical
// payload totals come from SourceCounters, while queued gauges are derived by
// inspecting owned records in snapshot(); excluding both from this long-lived
// state avoids duplicating 128 bytes of target RAM.
struct SelectedByteCounters {
  std::uint64_t framed_bytes_framed = 0U;
  std::uint64_t framed_bytes_emitted = 0U;
  std::uint64_t framed_bytes_transmitted = 0U;
  std::uint64_t framed_bytes_evicted = 0U;
  std::uint64_t encoded_payload_bytes_framed = 0U;
  std::uint64_t encoded_payload_bytes_emitted = 0U;
  std::uint64_t encoded_payload_bytes_transmitted = 0U;
  std::uint64_t encoded_payload_bytes_dropped = 0U;
  std::uint64_t encoded_payload_bytes_evicted = 0U;
  std::uint64_t framed_bytes_dropped = 0U;
};

struct EncodingCounters {
  std::uint64_t raw_frames = 0U;
  std::uint64_t rle_frames = 0U;
  std::uint64_t rle_runs = 0U;
  std::uint64_t fallback_frames = 0U;
  std::uint64_t fallback_not_smaller = 0U;
  std::uint64_t fallback_temporary_page_unavailable = 0U;
  std::uint64_t fallback_encoder_failure = 0U;
  std::uint64_t encode_cycles = 0U;
  std::uint32_t encode_failures = 0U;
};

struct PipelineSnapshot {
  std::array<SourceCounters, kStreamCount> sources{};
  std::array<SourceByteCounters, kStreamCount> source_bytes{};
  std::array<EncodingCounters, kStreamCount> encoding{};
  std::array<std::size_t, kBufferStateCount> buffers_by_state{};
  std::array<std::size_t, kStreamCount> ready_depth_by_source{};
  std::array<std::size_t, kStreamCount> transmit_depth_by_source{};
  std::array<std::size_t, kStreamCount> filling_depth_by_source{};
  std::uint32_t run_id = 0U;
  std::uint8_t enabled_stream_mask = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  RunFrameFormat frame_format{};
  std::uint32_t run_starts = 0U;
  std::uint32_t run_start_rejections = 0U;
  std::uint32_t pool_exhaustions = 0U;
  std::uint32_t invalid_operations = 0U;
  std::uint32_t encoding_rejections = 0U;
  std::uint32_t ready_queue_rejections = 0U;
  std::uint32_t transmit_queue_rejections = 0U;
  std::uint32_t temporary_page_exhaustions = 0U;
  std::uint32_t encode_failures = 0U;
  std::uint64_t frames_promoted = 0U;
  std::uint64_t fairness_deferrals = 0U;
  std::uint64_t pressure_evictions = 0U;
  std::uint64_t capacity_drops_without_evictable_frame = 0U;
  std::uint64_t accounted_frame_skew = 0U;
  std::uint64_t data_payload_bytes_transmitted = 0U;
  std::uint64_t data_framed_bytes_transmitted = 0U;
  std::size_t ready_queue_depth = 0U;
  std::size_t transmit_queue_depth = 0U;
  std::size_t buffers_owned = 0U;
  std::size_t ready_queue_high_water = 0U;
  std::size_t transmit_queue_high_water = 0U;
  std::size_t buffers_owned_high_water = 0U;
  std::size_t temporary_pages_owned = 0U;
  std::size_t temporary_page_high_water = 0U;
  bool accepting_frames = false;
  bool drain_pending = false;
  bool ready_for_start = true;
};

struct PromotionReport {
  std::size_t frames_promoted = 0U;
  bool transmit_queue_full = false;
  bool fairness_deferred = false;
  bool invariant_error = false;
};

struct StopReport {
  std::size_t filling_frames_canceled = 0U;
  std::size_t temporary_pages_recycled = 0U;
  std::size_t ready_frames_to_drain = 0U;
  std::size_t transmitting_frames_to_drain = 0U;
};

// Main-loop-only packet ownership pipeline. A future pacing ISR may publish a
// compact event/tick count, but it must never call this class: frame filling,
// validation, checksum construction, queue mutation, and USB service all stay
// in cooperative context.
class PacketBufferPipeline final : public usb::LowerPriorityFrameSource {
 public:
  explicit PacketBufferPipeline(PacketBufferStorage &storage,
                                timing::CycleCounter *cycle_counter = nullptr)
      : storage_(storage), cycle_counter_(cycle_counter) {}
  PacketBufferPipeline(const PacketBufferPipeline &) = delete;
  PacketBufferPipeline &operator=(const PacketBufferPipeline &) = delete;
  PacketBufferPipeline(PacketBufferPipeline &&) = delete;
  PacketBufferPipeline &operator=(PacketBufferPipeline &&) = delete;

  // START is admitted only after STOP has made the prior run quiescent. This
  // prevents resetting READY work or abandoning a partially written frame.
  OperationStatus startRun(
      std::uint32_t run_id,
      protocol_v1::ChecksumAlgorithm checksum_algorithm =
          protocol_v1::kDefaultChecksumAlgorithm,
      std::uint8_t enabled_stream_mask = kAllStreamMask,
      RunFrameFormat frame_format = {});
  // STOP cancels any producer-owned partial construction, then drains every
  // already complete READY/TRANSMITTING frame through normal USB ownership.
  StopReport stopProduction();

  // Calling beginFill represents production of one complete source frame.
  // Sequence and production counts advance before pool admission so a pool
  // drop remains visible as a sequence gap, as required by protocol v1.
  BeginFillResult beginFill(Stream stream);
  // Acquisition owners can lose complete canonical frames before packet
  // storage exists (for example, a GPIO raw-ring or packer overrun). Record
  // those frames in chronological cooperative context before beginning the
  // next retained frame so sequence and source counters preserve the gap.
  OperationStatus recordSourceFrameDrops(Stream stream,
                                         std::uint64_t frame_count);
  protocol::MutableByteView writablePayload(const FillHandle &handle);
  FinishFillResult finishFill(const FillHandle &handle,
                              const FrameCompletion &completion);
  bool cancelFill(const FillHandle &handle);

  // Move a bounded number of complete READY frames into immutable transport
  // ownership. A combined active run admits at most one equal-duration frame
  // beyond the other source's emitted-or-dropped coverage; STOP relaxes that
  // wait so every remaining complete frame drains.
  PromotionReport serviceReadyFrames(
      std::size_t limit = board::kPacketPromotionsPerLoop);

  protocol::ByteView frontFrame() const override;
  bool prepareFrontFrame() override;
  void markFrontFrameStarted() override;
  bool abortFrontFrame() override;
  void releaseFrontFrame() override;
  std::size_t queuedFrames() const override;

  std::size_t readyFrames() const;
  std::size_t freeBuffers() const;
  bool quiescent() const;
  bool readyForStart() const;
  constexpr bool acceptingFrames() const { return accepting_frames_; }
  constexpr std::uint32_t runId() const { return run_id_; }
  constexpr std::uint8_t enabledStreamMask() const {
    return enabled_stream_mask_;
  }
  constexpr protocol_v1::ChecksumAlgorithm checksumAlgorithm() const {
    return checksum_algorithm_;
  }
  constexpr RunFrameFormat frameFormat() const { return frame_format_; }
  constexpr bool accepts(
      Stream stream, std::uint32_t run_id,
      protocol_v1::ChecksumAlgorithm checksum_algorithm) const {
    return accepting_frames_ && run_id_ == run_id &&
           checksum_algorithm_ == checksum_algorithm &&
           streamEnabled(enabled_stream_mask_, stream);
  }
  SourceCounters sourceCounters(Stream stream) const {
    return validStream(stream) ? source_counters_[streamIndex(stream)]
                               : SourceCounters{};
  }
  PipelineSnapshot snapshot() const;

 private:
#if defined(THINGDAQ_TESTING)
  friend struct PacketBufferPipelineTestAccess;
#endif

  // FILLING records use this word as the nonzero producer lease. Complete
  // records no longer need that lease, so the same accounted word records the
  // immutable wire representation without growing all 200 pool records.
  enum class LeaseOrRepresentation : std::uint32_t {
    kUnowned = 0U,
    kV1Raw = 1U,
    kV2Raw = 2U,
    kV2Rle = 3U,
  };

  struct BufferRecord {
    BufferState state = BufferState::kFree;
    Stream stream = Stream::kAdc;
    bool transmission_started = false;
    bool gap_before_required = false;
    std::uint32_t run_id = 0U;
    std::uint32_t sequence = 0U;
    std::uint32_t item_count = 0U;
    std::uint32_t lease_or_representation = 0U;
    std::size_t frame_size = 0U;
  };

  using BufferIndex = std::uint8_t;
  using ReadyQueue =
      usb::detail::FixedQueue<BufferIndex, board::kPacketReadyQueueDepth>;
  using TransmitQueue = usb::detail::FixedQueue<
      BufferIndex, board::kPacketTransmitQueueDepth>;

  FinishFillResult finishV2Fill(const FillHandle &handle,
                                const FrameCompletion &completion);
  bool handleMatches(const FillHandle &handle) const;
  std::size_t selectReadySource(bool &fairness_deferred) const;
  std::uint64_t accountedFrames(std::size_t source_index) const;
  BufferIndex takeFreeBuffer();
  BufferIndex takeTransformBuffer(const BufferRecord &source);
  bool releaseTransformOwnership(BufferIndex index);
  bool completeRecordValid(const BufferRecord &record) const;
  BufferIndex oldestEvictableCompleteBuffer() const;
  bool evictCompleteBuffer(BufferIndex index);
  void dropBuffer(BufferIndex index, bool pressure_eviction);
  void propagateGapAfter(const BufferRecord &dropped);
  void markGapBefore(BufferIndex index);
  bool finalizeGapBefore(BufferIndex index);
  void recycle(BufferIndex index);
  void recycleTransform(BufferIndex index);
  void recordDrop(Stream stream, std::uint32_t item_count);
  void updateOwnedHighWater();
  std::size_t ownedBuffers() const;

  PacketBufferStorage &storage_;
  std::array<BufferRecord, board::kPacketBufferCount> records_{};
  std::array<ReadyQueue, kStreamCount> ready_queues_{};
  TransmitQueue transmit_queue_{};
  std::array<SourceCounters, kStreamCount> source_counters_{};
  std::array<SelectedByteCounters, kStreamCount> selected_byte_counters_{};
  std::array<EncodingCounters, kStreamCount> encoding_counters_{};
  std::array<std::size_t, kStreamCount> transmit_depth_by_source_{};
  std::uint32_t run_id_ = 0U;
  std::uint8_t enabled_stream_mask_ = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm_ =
      protocol_v1::kDefaultChecksumAlgorithm;
  RunFrameFormat frame_format_{};
  std::uint32_t next_lease_ = 1U;
  std::uint32_t run_starts_ = 0U;
  std::uint32_t run_start_rejections_ = 0U;
  std::uint32_t pool_exhaustions_ = 0U;
  std::uint32_t invalid_operations_ = 0U;
  std::uint32_t encoding_rejections_ = 0U;
  std::uint32_t ready_queue_rejections_ = 0U;
  std::uint32_t transmit_queue_rejections_ = 0U;
  std::uint32_t temporary_page_exhaustions_ = 0U;
  std::uint32_t encode_failures_ = 0U;
  std::uint64_t frames_promoted_ = 0U;
  std::uint64_t fairness_deferrals_ = 0U;
  std::uint64_t pressure_evictions_ = 0U;
  std::uint64_t capacity_drops_without_evictable_frame_ = 0U;
  std::size_t next_free_search_ = 0U;
  std::size_t next_ready_source_ = 0U;
  std::size_t next_eviction_source_ = 0U;
  std::size_t ready_queue_high_water_ = 0U;
  std::size_t transmit_queue_high_water_ = 0U;
  std::size_t buffers_owned_high_water_ = 0U;
  std::size_t temporary_pages_owned_ = 0U;
  std::size_t temporary_page_high_water_ = 0U;
  std::array<bool, kStreamCount> gap_before_next_frame_{};
  bool accepting_frames_ = false;
  timing::CycleCounter *cycle_counter_ = nullptr;
  bool cycle_counter_ready_ = false;
#if defined(THINGDAQ_TESTING)
  bool inject_rle_encode_failure_ = false;
#endif
};

static_assert(kStreamCount == 2U);
static_assert(kBufferStateCount ==
              static_cast<std::size_t>(BufferState::kTransforming) + 1U);
static_assert(kAllStreamMask == 3U);
static_assert(protocol_v1::kAdcPairsPerFrame *
                      protocol_v1::kAdcBytesPerPair ==
                  protocol_v1::kDataPayloadBytes);
static_assert(protocol_v1::kGpioSamplesPerFrame ==
              protocol_v1::kDataPayloadBytes);
static_assert(protocol_v1::kHeaderSize == protocol_v2::kHeaderSize);
static_assert(protocol_v1::kHeaderFlagsOffset ==
              protocol_v2::kHeaderFlagsOffset);
static_assert(protocol_v1::kHeaderFirstSampleTicksOffset ==
              protocol_v2::kHeaderFirstSampleTicksOffset);
static_assert(kNominalPayloadBytesPerSecondPerStream == 4000000U);
static_assert(kNominalCombinedPayloadBytesPerSecond == 8000000U);
static_assert(board::kPacketBufferCount < kInvalidBufferIndex);
static_assert(alignof(PacketBufferPrimaryStorage) == board::kCacheLineBytes);
static_assert(alignof(PacketBufferReserveStorage) == board::kCacheLineBytes);
static_assert(sizeof(PacketBufferPrimaryStorage) ==
              board::kPacketBufferPrimaryStorageBytes);
static_assert(sizeof(PacketBufferReserveStorage) ==
              board::kPacketBufferReserveStorageBytes);
static_assert(sizeof(PacketBufferPrimaryStorage) +
                      sizeof(PacketBufferReserveStorage) ==
                  board::kPacketBufferStorageBytes);
static_assert(protocol_v1::kDataFrameBytes % board::kCacheLineBytes == 0U);
static_assert(sizeof(PacketBufferPipeline) <=
              board::kPacketPipelineStateBudgetBytes);

}  // namespace thingdaq::packet
