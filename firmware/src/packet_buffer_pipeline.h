#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "protocol.h"
#include "usb_transport.h"

namespace teensy_daq::packet {

#if defined(TEENSY_DAQ_TESTING)
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
};

enum class Stream : std::uint8_t {
  kAdc = 0U,
  kGpio = 1U,
};

inline constexpr std::size_t kStreamCount = 2U;
inline constexpr std::uint8_t kInvalidBufferIndex = 0xFFU;

constexpr std::size_t streamIndex(Stream stream) {
  return static_cast<std::size_t>(stream);
}

constexpr bool validStream(Stream stream) {
  return streamIndex(stream) < kStreamCount;
}

constexpr protocol_v1::FrameKind frameKind(Stream stream) {
  return stream == Stream::kAdc ? protocol_v1::FrameKind::kAdcData
                                : protocol_v1::FrameKind::kGpioData;
}

constexpr std::uint32_t itemsPerFrame(Stream stream) {
  return stream == Stream::kAdc
             ? static_cast<std::uint32_t>(protocol_v1::kAdcPairsPerFrame)
             : static_cast<std::uint32_t>(
                   protocol_v1::kGpioSamplesPerFrame);
}

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
};

struct BeginFillResult {
  OperationStatus status = OperationStatus::kNotRunning;
  FillHandle handle{};

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct FinishFillResult {
  OperationStatus status = OperationStatus::kInvalidHandle;
  protocol::Result encoding = protocol::Result::success();

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
  std::uint32_t next_sequence = 0U;
  std::size_t ready_queue_high_water = 0U;
  std::size_t transmit_queue_high_water = 0U;
};

struct PipelineSnapshot {
  std::array<SourceCounters, kStreamCount> sources{};
  std::array<std::size_t, 4U> buffers_by_state{};
  std::array<std::size_t, kStreamCount> ready_depth_by_source{};
  std::array<std::size_t, kStreamCount> transmit_depth_by_source{};
  std::uint32_t run_id = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t run_starts = 0U;
  std::uint32_t run_start_rejections = 0U;
  std::uint32_t pool_exhaustions = 0U;
  std::uint32_t invalid_operations = 0U;
  std::uint32_t encoding_rejections = 0U;
  std::uint32_t ready_queue_rejections = 0U;
  std::uint32_t transmit_queue_rejections = 0U;
  std::uint64_t frames_promoted = 0U;
  std::size_t ready_queue_depth = 0U;
  std::size_t transmit_queue_depth = 0U;
  std::size_t ready_queue_high_water = 0U;
  std::size_t transmit_queue_high_water = 0U;
  std::size_t buffers_owned_high_water = 0U;
  bool accepting_frames = false;
  bool drain_pending = false;
  bool ready_for_start = true;
};

struct PromotionReport {
  std::size_t frames_promoted = 0U;
  bool transmit_queue_full = false;
  bool invariant_error = false;
};

struct StopReport {
  std::size_t filling_frames_canceled = 0U;
  std::size_t ready_frames_to_drain = 0U;
  std::size_t transmitting_frames_to_drain = 0U;
};

// Main-loop-only packet ownership pipeline. A future pacing ISR may publish a
// compact event/tick count, but it must never call this class: frame filling,
// validation, checksum construction, queue mutation, and USB service all stay
// in cooperative context.
class PacketBufferPipeline final : public usb::LowerPriorityFrameSource {
 public:
  explicit PacketBufferPipeline(PacketBufferStorage &storage)
      : storage_(storage) {}
  PacketBufferPipeline(const PacketBufferPipeline &) = delete;
  PacketBufferPipeline &operator=(const PacketBufferPipeline &) = delete;
  PacketBufferPipeline(PacketBufferPipeline &&) = delete;
  PacketBufferPipeline &operator=(PacketBufferPipeline &&) = delete;

  // START is admitted only after STOP has made the prior run quiescent. This
  // prevents resetting READY work or abandoning a partially written frame.
  OperationStatus startRun(
      std::uint32_t run_id,
      protocol_v1::ChecksumAlgorithm checksum_algorithm =
          protocol_v1::kDefaultChecksumAlgorithm);
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
  // ownership. Sources alternate whenever both have work.
  PromotionReport serviceReadyFrames(
      std::size_t limit = board::kPacketPromotionsPerLoop);

  protocol::ByteView frontFrame() const override;
  void releaseFrontFrame() override;
  std::size_t queuedFrames() const override;

  std::size_t readyFrames() const;
  std::size_t freeBuffers() const;
  bool quiescent() const;
  bool readyForStart() const;
  PipelineSnapshot snapshot() const;

 private:
#if defined(TEENSY_DAQ_TESTING)
  friend struct PacketBufferPipelineTestAccess;
#endif

  struct BufferRecord {
    BufferState state = BufferState::kFree;
    Stream stream = Stream::kAdc;
    std::uint32_t run_id = 0U;
    std::uint32_t sequence = 0U;
    std::uint32_t item_count = 0U;
    std::uint32_t lease = 0U;
    std::size_t frame_size = 0U;
  };

  using BufferIndex = std::uint8_t;
  using ReadyQueue =
      usb::detail::FixedQueue<BufferIndex, board::kPacketReadyQueueDepth>;
  using TransmitQueue = usb::detail::FixedQueue<
      BufferIndex, board::kPacketTransmitQueueDepth>;

  bool handleMatches(const FillHandle &handle) const;
  BufferIndex takeFreeBuffer();
  void recycle(BufferIndex index);
  void recordDrop(Stream stream, std::uint32_t item_count);
  void updateOwnedHighWater();
  std::size_t ownedBuffers() const;

  PacketBufferStorage &storage_;
  std::array<BufferRecord, board::kPacketBufferCount> records_{};
  std::array<ReadyQueue, kStreamCount> ready_queues_{};
  TransmitQueue transmit_queue_{};
  std::array<SourceCounters, kStreamCount> source_counters_{};
  std::array<std::size_t, kStreamCount> transmit_depth_by_source_{};
  std::uint32_t run_id_ = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm_ =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t next_lease_ = 1U;
  std::uint32_t run_starts_ = 0U;
  std::uint32_t run_start_rejections_ = 0U;
  std::uint32_t pool_exhaustions_ = 0U;
  std::uint32_t invalid_operations_ = 0U;
  std::uint32_t encoding_rejections_ = 0U;
  std::uint32_t ready_queue_rejections_ = 0U;
  std::uint32_t transmit_queue_rejections_ = 0U;
  std::uint64_t frames_promoted_ = 0U;
  std::size_t next_free_search_ = 0U;
  std::size_t next_ready_source_ = 0U;
  std::size_t ready_queue_high_water_ = 0U;
  std::size_t transmit_queue_high_water_ = 0U;
  std::size_t buffers_owned_high_water_ = 0U;
  bool accepting_frames_ = false;
};

static_assert(kStreamCount == 2U);
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

}  // namespace teensy_daq::packet
