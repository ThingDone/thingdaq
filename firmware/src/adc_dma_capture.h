#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "board_config.h"
#include "dma_buffer_ownership.h"

namespace teensy_daq::adc_capture {

inline constexpr std::size_t kConverterCount = board::kLogicalAdcCount;
inline constexpr std::uint8_t kAllConvertersMask =
    static_cast<std::uint8_t>((1U << kConverterCount) - 1U);
inline constexpr std::uint8_t kOverflowDestination =
    static_cast<std::uint8_t>(board::kAdcDmaRingDepth);
inline constexpr std::uint8_t kInvalidDestination = 0xFFU;
// Two seeded generations plus every consumer buffer leave enough bounded
// bookkeeping for ordinary IRQ skew and two additional pressure generations.
inline constexpr std::size_t kGenerationSlotCount =
    board::kAdcDmaRingDepth + 4U;

struct SamplePair {
  std::uint16_t adc0 = 0U;
  std::uint16_t adc1 = 0U;
};

struct alignas(board::kCacheLineBytes) PairBuffer {
  std::array<SamplePair, protocol_v1::kAdcPairsPerFrame> pairs{};
};

struct alignas(board::kCacheLineBytes) PairBufferStorage {
  std::array<PairBuffer, board::kAdcDmaRingDepth> buffers{};
};

// When no consumer buffer is free, both channels continue into their own
// halfword of this isolated line with DOFF=0. No CPU consumer sees sink data.
struct alignas(board::kCacheLineBytes) PairOverflowSink {
  std::array<std::uint16_t,
             board::kAdcDmaOverflowSinkBytes / sizeof(std::uint16_t)>
      halfwords{};
};

using CacheMaintenance = dma::CacheMaintenance;
using CriticalSection = dma::CriticalSection;

enum class BufferState : std::uint8_t {
  kFree = 0U,
  kDmaOwned = 1U,
  kReady = 2U,
  kReading = 3U,
  kDiscardPending = 4U,
  kReleasing = 5U,
};

enum class OperationStatus : std::uint8_t {
  kOk,
  kAlreadyRunning,
  kNotRunning,
  kNotQuiescent,
  kInvalidEpoch,
  kInvalidConverter,
  kInvalidCompletion,
  kNoReadyBuffer,
  kInvalidHandle,
  kInvalidStopProgress,
};

enum class StartStatus : std::uint8_t {
  kOk,
  kAlreadyRunning,
  kNotQuiescent,
  kInvalidEpoch,
  kResourceBusy,
  kHardwareError,
};

struct Progress {
  std::array<std::uint64_t, kConverterCount> channel_major_loops{};
  std::array<std::uint64_t, kConverterCount> channel_results{};
  std::uint64_t paired_major_loops = 0U;
  std::uint64_t buffers_completed = 0U;
  std::uint64_t buffers_acquired = 0U;
  std::uint64_t buffers_released = 0U;
  std::uint64_t pairs_captured = 0U;
  std::uint64_t pairs_delivered = 0U;
  std::uint64_t pairs_lost = 0U;
  std::uint64_t stop_discarded_pairs = 0U;
  std::uint64_t incomplete_conversions = 0U;
  std::uint64_t overwritten_conversions = 0U;
  std::uint64_t ring_overruns = 0U;
  std::uint64_t incomplete_buffers = 0U;
  std::size_t ready_high_water = 0U;
  std::uint32_t adc_etc_error_events = 0U;
  std::uint32_t adc_etc_error_flags = 0U;
  std::uint32_t dma_error_events = 0U;
  std::uint32_t completion_mismatches = 0U;
  std::uint32_t destination_mismatches = 0U;
  std::uint32_t schedule_exhaustions = 0U;
  std::uint32_t invariant_errors = 0U;
  std::uint32_t stale_completions = 0U;
};

struct PrimeResult {
  OperationStatus status = OperationStatus::kNotQuiescent;
  std::uint32_t epoch = 0U;
  std::uint32_t active_generation = 0U;
  std::uint32_t queued_generation = 1U;
  std::uint8_t active_destination = kInvalidDestination;
  std::uint8_t queued_destination = kInvalidDestination;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct CompletionResult {
  OperationStatus status = OperationStatus::kInvalidCompletion;
  std::uint32_t epoch = 0U;
  std::uint32_t completed_generation = 0U;
  std::uint32_t future_generation = 0U;
  std::uint8_t converter = 0U;
  std::uint8_t completed_destination = kInvalidDestination;
  std::uint8_t future_destination = kOverflowDestination;
  std::uint8_t completion_mask = 0U;
  bool consumed = false;
  bool pair_ready = false;
  bool pair_lost = false;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct BufferHandle {
  const SamplePair *pairs = nullptr;
  std::uint64_t first_pair = 0U;
  std::uint32_t pair_count = 0U;
  std::uint32_t epoch = 0U;
  std::uint32_t lease = 0U;
  std::uint8_t buffer_index = kInvalidDestination;

  constexpr bool valid() const {
    return pairs != nullptr && buffer_index < board::kAdcDmaRingDepth &&
           pair_count == protocol_v1::kAdcPairsPerFrame && epoch != 0U &&
           lease != 0U;
  }
};

struct AcquireResult {
  OperationStatus status = OperationStatus::kNoReadyBuffer;
  BufferHandle handle{};

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct ChannelStopState {
  std::uint32_t generation = 0U;
  std::uint32_t minor_pairs = 0U;
  std::uint8_t destination = kInvalidDestination;
};

struct StopReport {
  OperationStatus status = OperationStatus::kNotRunning;
  std::uint64_t pairs_discarded = 0U;
  std::size_t buffers_discarded = 0U;
  std::size_t ready_buffers_to_drain = 0U;
  std::size_t reading_buffers_to_release = 0U;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct Snapshot {
  Progress progress{};
  std::array<BufferState, board::kAdcDmaRingDepth> buffer_states{};
  std::array<std::uint32_t, board::kAdcDmaRingDepth>
      buffer_generations{};
  std::array<std::uint32_t, kConverterCount>
      next_completion_generations{};
  std::uint32_t epoch = 0U;
  std::size_t ready_depth = 0U;
  std::size_t reading_depth = 0U;
  std::size_t discard_depth = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::uint32_t stale_interrupts = 0U;
  bool running = false;
  bool quiescent = true;
  bool hardware_prepared = false;
  bool faulted = false;
};

class PairSource {
 public:
  virtual ~PairSource() = default;
  virtual AcquireResult acquireReady() = 0;
  virtual OperationStatus release(const BufferHandle &handle) = 0;
};

// Portable paired-generation ownership core. A channel completion cannot make
// a buffer CPU-visible: the matching generation must be complete on both
// channels and free of ADC_ETC/eDMA evidence first. DMA-owned corrupt blocks
// are reclaimed cooperatively so cache calls never execute in an ISR.
class PairCaptureRing final : public PairSource {
 public:
  constexpr PairCaptureRing(PairBufferStorage &storage,
                            PairOverflowSink &overflow_sink,
                            CacheMaintenance &cache,
                            CriticalSection &critical)
      : storage_(storage),
        overflow_sink_(overflow_sink),
        cache_(cache),
        critical_(critical) {}

  PairCaptureRing(const PairCaptureRing &) = delete;
  PairCaptureRing &operator=(const PairCaptureRing &) = delete;

  PrimeResult prime(std::uint32_t epoch,
                    std::uint32_t initial_generation = 0U,
                    std::uint64_t first_pair = 0U);
  CompletionResult onMajorLoopComplete(std::uint8_t converter,
                                       std::uint32_t epoch,
                                       std::uint32_t generation,
                                       std::uint8_t destination);
  void recordAdcEtcError(std::uint32_t epoch,
                         std::uint8_t converter_mask,
                         std::uint32_t raw_flags);
  void recordDmaError(std::uint32_t epoch, std::uint8_t converter);
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;
  std::size_t serviceDiscarded(
      std::size_t limit = board::kAdcDmaRingDepth);
  StopReport stop(
      const std::array<ChannelStopState, kConverterCount> &channels);
  Snapshot snapshot();
  bool quiescent();

  std::uint16_t *destinationHalfword(std::uint8_t destination,
                                     std::uint8_t converter);
  const std::uint16_t *destinationHalfword(
      std::uint8_t destination, std::uint8_t converter) const;

 private:
  struct BufferRecord {
    BufferState state = BufferState::kFree;
    std::uint32_t epoch = 0U;
    std::uint32_t generation = 0U;
    std::uint64_t first_pair = 0U;
    std::uint32_t lease = 0U;
  };

  struct GenerationSlot {
    std::uint64_t first_pair = 0U;
    std::uint32_t generation = 0U;
    std::uint8_t destination = kInvalidDestination;
    std::uint8_t completion_mask = 0U;
    std::uint32_t minimum_lost_pairs = 0U;
    bool valid = false;
    bool invalid_data = false;
  };

  GenerationSlot *findGeneration(std::uint32_t generation);
  const GenerationSlot *findGeneration(std::uint32_t generation) const;
  GenerationSlot *scheduleGeneration(std::uint32_t generation);
  std::uint8_t takeFreeBuffer(std::uint32_t generation,
                              std::uint64_t first_pair);
  void markOutstandingInvalid();
  void markGenerationInvalid(std::uint32_t generation,
                             std::uint32_t minimum_lost_pairs = 0U);
  void finalizeGeneration(GenerationSlot &slot, CompletionResult &result);
  std::size_t countState(BufferState state) const;
  bool allBuffersFree() const;
  bool handleMatches(const BufferHandle &handle,
                     BufferState state) const;
  std::uint32_t allocateLease();
  void noteInvariantError();

  PairBufferStorage &storage_;
  PairOverflowSink &overflow_sink_;
  CacheMaintenance &cache_;
  CriticalSection &critical_;
  std::array<BufferRecord, board::kAdcDmaRingDepth> records_{};
  std::array<GenerationSlot, kGenerationSlotCount> generations_{};
  Progress progress_{};
  std::array<std::uint32_t, kConverterCount>
      next_completion_generations_{};
  std::uint64_t next_first_pair_ = 0U;
  std::uint32_t next_schedule_generation_ = 0U;
  std::uint32_t next_lease_ = 1U;
  std::uint32_t epoch_ = 0U;
  std::size_t next_free_search_ = 0U;
  bool running_ = false;
};

class HardwareCapture : public PairSource {
 public:
  virtual StartStatus inspectStart(std::uint32_t epoch) = 0;
  virtual StartStatus prepare(std::uint32_t epoch) = 0;
  // The caller invokes this while ADC triggers are still active. The target
  // adapter must request a complete paired-DMA boundary and wait boundedly;
  // it must not tear down DMA resources here.
  virtual bool stopAtBoundaryBeforeTriggers() = 0;
  // The caller must disable ADC triggers first. Complete buffers remain
  // drainable, while every partial generation is accounted and discarded.
  virtual StopReport stopAfterTriggers() = 0;
  virtual std::size_t serviceOwnership() = 0;
  virtual Snapshot rawSnapshot() = 0;
};

static_assert(kConverterCount == 2U);
static_assert(kAllConvertersMask == 0x03U);
static_assert(board::kAdcDmaRingDepth < kInvalidDestination);
static_assert(std::is_standard_layout_v<SamplePair>);
static_assert(sizeof(SamplePair) == protocol_v1::kAdcBytesPerPair);
static_assert(offsetof(SamplePair, adc0) == 0U);
static_assert(offsetof(SamplePair, adc1) == sizeof(std::uint16_t));
static_assert(sizeof(PairBuffer) == board::kAdcDmaBufferStrideBytes);
static_assert(alignof(PairBuffer) == board::kCacheLineBytes);
static_assert(sizeof(PairBufferStorage) == board::kAdcDmaRingBytes);
static_assert(alignof(PairBufferStorage) == board::kCacheLineBytes);
static_assert(sizeof(PairOverflowSink) == board::kAdcDmaOverflowSinkBytes);
static_assert(alignof(PairOverflowSink) == board::kCacheLineBytes);

}  // namespace teensy_daq::adc_capture
