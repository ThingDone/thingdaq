#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "dma_buffer_ownership.h"
#include "generated/protocol_v2_constants.h"
#include "statistics.h"

namespace thingdaq::gpio_join {

inline constexpr std::size_t kBankCount = 2U;
inline constexpr std::size_t kSamplesPerBlock =
    protocol_v2::kInputGpioSamplesPerFrame;
inline constexpr std::size_t kRingDepth =
    protocol_v2::kAuxGpioRawRingDepth;
inline constexpr std::size_t kGenerationSlotCount = kRingDepth + 4U;
inline constexpr std::uint8_t kAllBanksMask = 0x03U;
inline constexpr std::uint8_t kOverflowDestination =
    static_cast<std::uint8_t>(kRingDepth);
inline constexpr std::uint8_t kInvalidDestination = 0xFFU;

enum class Bank : std::uint8_t {
  kPrimary = 0U,
  kAuxiliary = 1U,
};

constexpr std::size_t bankIndex(Bank bank) {
  return static_cast<std::size_t>(bank);
}

constexpr bool validBank(Bank bank) { return bankIndex(bank) < kBankCount; }

struct alignas(32U) RawBlock {
  std::array<std::uint32_t, kSamplesPerBlock> words{};
};

struct alignas(32U) PairedRawStorage {
  std::array<RawBlock, kRingDepth> primary{};
  std::array<RawBlock, kRingDepth> auxiliary{};

  RawBlock &block(Bank bank, std::size_t index) {
    return bank == Bank::kPrimary ? primary[index] : auxiliary[index];
  }
  const RawBlock &block(Bank bank, std::size_t index) const {
    return bank == Bank::kPrimary ? primary[index] : auxiliary[index];
  }
};

struct alignas(32U) PairedOverflowSink {
  std::array<std::array<std::uint32_t, 8U>, kBankCount> words{};
};

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
  kInvalidPeriod,
  kTimestampOverflow,
  kInvalidBank,
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
  kUnsupportedProfile,
  kResourceBusy,
  kHardwareError,
};

enum class StopReason : std::uint8_t {
  kStop,
  kRollback,
  kFault,
};

struct Progress {
  std::array<std::uint64_t, kBankCount> bank_major_loops{};
  std::array<std::uint64_t, kBankCount> bank_samples_completed{};
  std::array<std::uint32_t, kBankCount> bank_ring_overruns{};
  std::array<std::uint32_t, kBankCount> bank_stale_completions{};
  std::uint64_t paired_major_loops = 0U;
  std::uint64_t buffers_completed = 0U;
  std::uint64_t buffers_acquired = 0U;
  std::uint64_t buffers_released = 0U;
  std::uint64_t sample_instants_captured = 0U;
  std::uint64_t sample_instants_joined = 0U;
  std::uint64_t sample_instants_delivered = 0U;
  std::uint64_t sample_instants_lost = 0U;
  std::uint64_t raw_ring_overruns = 0U;
  std::uint64_t generation_skew_events = 0U;
  std::uint64_t generation_skew_samples = 0U;
  std::uint64_t canceled_generations = 0U;
  std::uint64_t cancellation_samples = 0U;
  std::uint64_t stop_tail_samples = 0U;
  std::uint32_t timestamp_mismatches = 0U;
  std::uint32_t count_mismatches = 0U;
  std::uint32_t destination_mismatches = 0U;
  std::uint32_t schedule_exhaustions = 0U;
  std::uint32_t stale_completions = 0U;
  std::uint32_t cache_dma_discards = 0U;
  std::uint32_t cache_cpu_invalidations = 0U;
  std::uint32_t hardware_errors = 0U;
  std::uint32_t invariant_errors = 0U;
  std::size_t ready_high_water = 0U;

  constexpr bool conserved() const {
    return sample_instants_captured ==
           sample_instants_joined + sample_instants_lost;
  }
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

struct ReservationResult {
  OperationStatus status = OperationStatus::kNotRunning;
  std::uint32_t generation = 0U;
  std::uint8_t destination = kInvalidDestination;
  std::uint64_t first_sample_ticks = 0U;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct CompletionResult {
  OperationStatus status = OperationStatus::kInvalidCompletion;
  Bank bank = Bank::kPrimary;
  std::uint32_t generation = 0U;
  std::uint32_t future_generation = 0U;
  std::uint8_t completed_destination = kInvalidDestination;
  std::uint8_t future_destination = kInvalidDestination;
  std::uint8_t completion_mask = 0U;
  bool consumed = false;
  bool pair_ready = false;
  bool pair_lost = false;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct BufferHandle {
  const std::uint32_t *primary_words = nullptr;
  const std::uint32_t *auxiliary_words = nullptr;
  std::uint64_t first_sample_ticks = 0U;
  std::uint32_t sample_period_ticks = 0U;
  std::uint32_t sample_count = 0U;
  std::uint32_t epoch = 0U;
  std::uint32_t generation = 0U;
  std::uint32_t lease = 0U;
  std::uint8_t buffer_index = kInvalidDestination;

  constexpr bool valid() const {
    return primary_words != nullptr && auxiliary_words != nullptr &&
           buffer_index < kRingDepth && sample_count == kSamplesPerBlock &&
           sample_period_ticks != 0U && epoch != 0U && lease != 0U;
  }
};

struct AcquireResult {
  OperationStatus status = OperationStatus::kNoReadyBuffer;
  BufferHandle handle{};

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct BankStopState {
  std::uint32_t generation = 0U;
  std::uint8_t destination = kInvalidDestination;
  std::uint64_t first_sample_ticks = 0U;
  std::uint32_t sample_count = 0U;
};

struct StopReport {
  OperationStatus status = OperationStatus::kNotRunning;
  StopReason reason = StopReason::kStop;
  std::uint64_t samples_discarded = 0U;
  std::size_t generations_canceled = 0U;
  std::size_t buffers_discarded = 0U;
  std::size_t ready_buffers_to_drain = 0U;
  std::size_t reading_buffers_to_release = 0U;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct Snapshot {
  Progress progress{};
  std::array<BufferState, kRingDepth> buffer_states{};
  std::array<std::uint32_t, kRingDepth> buffer_generations{};
  std::array<std::uint32_t, kBankCount> next_completion_generations{};
  std::uint32_t epoch = 0U;
  std::uint32_t sample_period_ticks = 0U;
  std::size_t ready_depth = 0U;
  std::size_t reading_depth = 0U;
  std::size_t discard_depth = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::uint32_t stale_dma_completions = 0U;
  bool running = false;
  bool quiescent = true;
  bool hardware_prepared = false;
  bool faulted = false;
};

class PairedRawSource {
 public:
  virtual ~PairedRawSource() = default;
  virtual AcquireResult acquireReady() = 0;
  virtual OperationStatus release(const BufferHandle &handle) = 0;
};

class HardwareCapture : public PairedRawSource {
 public:
  virtual StartStatus inspectStart(
      std::uint32_t epoch, protocol_v2::RateProfile profile) = 0;
  // Prepare both GPIO DMA paths against one epoch while PIT0 remains stopped.
  virtual StartStatus prepare(
      std::uint32_t epoch, protocol_v2::RateProfile profile) = 0;
  // Standalone GPIO convenience path: prepare both banks, then enable PIT0.
  virtual StartStatus start(
      std::uint32_t epoch, protocol_v2::RateProfile profile) = 0;
  // Combined-mode callers stop the common trigger before invoking this path.
  virtual StopReport stopAfterTriggers(
      StopReason reason = StopReason::kStop) = 0;
  virtual StopReport stop(StopReason reason = StopReason::kStop) = 0;
  virtual std::size_t serviceOwnership() = 0;
  virtual Snapshot rawSnapshot() = 0;
};

// Direction is made safe on the DMA-visible alias before only the selected
// fast-alias bits are cleared. Unrelated GPIO1 direction and select bits are
// preserved exactly.
inline void selectAuxiliaryStandardInputs(
    volatile std::uint32_t &gpr26,
    volatile std::uint32_t &gpio1_gdir) {
  gpio1_gdir = gpio1_gdir & ~board::kGpio1PsrCaptureMask;
  gpr26 = gpr26 & ~board::kGpio6ToGpio1Gpr26ClearMask;
}

// Fixed-capacity, generation-indexed join barrier for the two GPIO PSR DMA
// streams. Only a complete pair with identical generation, timestamp, count,
// destination, and scheduled interval can transition to CPU ownership.
class DualBankCaptureRing final : public PairedRawSource {
 public:
  constexpr DualBankCaptureRing(PairedRawStorage &storage,
                                PairedOverflowSink &overflow_sink,
                                dma::CacheMaintenance &cache,
                                dma::CriticalSection &critical)
      : storage_(storage),
        overflow_sink_(overflow_sink),
        cache_(cache),
        critical_(critical) {}

  DualBankCaptureRing(const DualBankCaptureRing &) = delete;
  DualBankCaptureRing &operator=(const DualBankCaptureRing &) = delete;

  PrimeResult prime(std::uint32_t epoch, std::uint32_t sample_period_ticks,
                    std::uint32_t initial_generation = 0U,
                    std::uint64_t first_sample_ticks = 0U);
  ReservationResult reserveGeneration(std::uint32_t epoch,
                                      std::uint32_t generation);
  CompletionResult onMajorLoopComplete(
      Bank bank, std::uint32_t epoch, std::uint32_t generation,
      std::uint8_t destination, std::uint64_t first_sample_ticks,
      std::uint32_t sample_count =
          static_cast<std::uint32_t>(kSamplesPerBlock));
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;
  std::size_t serviceDiscarded(std::size_t limit = kRingDepth);
  StopReport stop(const std::array<BankStopState, kBankCount> &banks,
                  StopReason reason = StopReason::kStop);
  StopReport cancel(std::uint32_t epoch,
                    StopReason reason = StopReason::kRollback);
  void recordHardwareError(std::uint32_t epoch);
  Snapshot snapshot();
  bool quiescent();

  std::uint32_t *destinationWords(std::uint8_t destination, Bank bank);
  const std::uint32_t *destinationWords(std::uint8_t destination,
                                        Bank bank) const;

 private:
  struct BufferRecord {
    BufferState state = BufferState::kFree;
    std::uint32_t epoch = 0U;
    std::uint32_t generation = 0U;
    std::uint64_t first_sample_ticks = 0U;
    std::uint32_t lease = 0U;
  };

  struct GenerationSlot {
    std::array<std::uint64_t, kBankCount> observed_first_ticks{};
    std::array<std::uint32_t, kBankCount> observed_counts{};
    std::uint64_t expected_first_ticks = 0U;
    std::uint32_t generation = 0U;
    std::uint8_t destination = kInvalidDestination;
    std::uint8_t completion_mask = 0U;
    bool valid = false;
    bool invalid_data = false;
  };

  GenerationSlot *findGeneration(std::uint32_t generation);
  GenerationSlot *scheduleGeneration(std::uint32_t generation);
  std::uint8_t takeFreeBuffer(std::uint32_t generation,
                              std::uint64_t first_sample_ticks);
  void finalizeGeneration(GenerationSlot &slot, CompletionResult &result);
  void markOutstandingInvalid();
  void markDiscardPending(const GenerationSlot &slot,
                          StopReport *report = nullptr);
  std::size_t countState(BufferState state) const;
  bool allBuffersFree() const;
  bool handleMatches(const BufferHandle &handle, BufferState state) const;
  std::uint32_t allocateLease();
  void noteInvariantError();

  PairedRawStorage &storage_;
  PairedOverflowSink &overflow_sink_;
  dma::CacheMaintenance &cache_;
  dma::CriticalSection &critical_;
  std::array<BufferRecord, kRingDepth> records_{};
  std::array<GenerationSlot, kGenerationSlotCount> generations_{};
  Progress progress_{};
  std::array<std::uint32_t, kBankCount> next_completion_generations_{};
  std::uint64_t next_first_sample_ticks_ = 0U;
  std::uint32_t next_schedule_generation_ = 0U;
  std::uint32_t sample_period_ticks_ = 0U;
  std::uint32_t epoch_ = 0U;
  std::uint32_t next_lease_ = 1U;
  std::size_t next_free_search_ = 0U;
  bool running_ = false;
};

stats::GpioRawCaptureProgress statisticsProgress(const Snapshot &snapshot);

static_assert(kBankCount == 2U);
static_assert(kAllBanksMask == 0x03U);
static_assert(kRingDepth == 4U);
static_assert(kSamplesPerBlock == 2024U);
static_assert(kRingDepth < kInvalidDestination);
static_assert(sizeof(RawBlock) == kSamplesPerBlock * sizeof(std::uint32_t));
static_assert(alignof(RawBlock) == 32U);
static_assert(sizeof(PairedRawStorage) ==
              kBankCount * kRingDepth * sizeof(RawBlock));
static_assert(sizeof(PairedRawStorage) == board::kGpioRawDmaRingBytes,
              "paired and legacy GPIO layouts must share one physical ring");
static_assert(alignof(PairedRawStorage) == 32U);
static_assert(sizeof(PairedOverflowSink) == 64U);
static_assert(alignof(PairedOverflowSink) == 32U);
static_assert(sizeof(DualBankCaptureRing) <=
              board::kGpioPairedJoinStateBudgetBytes,
              "paired join state exceeds its fixed OCRAM reservation");

}  // namespace thingdaq::gpio_join
