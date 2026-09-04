#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "digital_output_program.h"
#include "dma_buffer_ownership.h"

namespace thingdaq::digital_output {

inline constexpr std::uint8_t kInvalidBlockIndex = 0xFFU;
inline constexpr std::size_t kBlocksPerServiceVisit = 1U;

enum class BlockState : std::uint8_t {
  kFree = 0U,
  kCpuFilling = 1U,
  kDmaReady = 2U,
  kDmaReading = 3U,
};

enum class OperationStatus : std::uint8_t {
  kOk,
  kInvalidGeneration,
  kInvalidLifecycle,
  kNotReady,
  kAlreadyActive,
  kInvalidRunId,
  kInvalidCompletion,
  kReleaseFailed,
};

enum class StartStatus : std::uint8_t {
  kOk,
  kNotArmed,
  kNotReady,
  kAlreadyActive,
  kInvalidRunId,
};

struct alignas(board::kCacheLineBytes) DmaBlockStorage {
  std::array<std::array<std::uint32_t, board::kAuxOutputStatesPerBlock>,
             board::kAuxOutputDmaBlockCount>
      blocks{};
};

// Four fixed 32-byte hardware TCD images are reserved separately from the
// source words so the linker manifest can prove both ranges independently.
struct alignas(board::kCacheLineBytes) DmaDescriptorStorage {
  std::array<std::array<std::uint32_t,
                        board::kEdmaTcdBytes / sizeof(std::uint32_t)>,
             board::kAuxOutputDmaBlockCount>
      descriptors{};
};

struct BlockRecord {
  BlockState state = BlockState::kFree;
  std::uint32_t upload_generation = 0U;
  std::uint32_t lease = 0U;
  std::uint32_t final_logical_state = 0U;
  std::uint64_t sequence = 0U;
  std::size_t valid_states = 0U;
  std::size_t transition_count = 0U;
};

struct Telemetry {
  std::uint64_t states_expanded = 0U;
  std::uint64_t dma_states_emitted = 0U;
  std::uint64_t transitions_emitted = 0U;
  std::uint64_t blocks_filled = 0U;
  std::uint64_t blocks_completed = 0U;
  std::uint32_t completed_repeats = 0U;
  std::uint32_t cache_flushes = 0U;
  std::uint32_t underruns = 0U;
  std::uint32_t dma_errors = 0U;
  std::uint32_t invalid_operations = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::size_t ready_high_water = 0U;
  std::size_t refill_lead_high_water = 0U;
};

struct Snapshot {
  ProgramSnapshot program{};
  Telemetry telemetry{};
  std::array<BlockRecord, board::kAuxOutputDmaBlockCount> blocks{};
  protocol_v2::OutputState state = protocol_v2::OutputState::kEmpty;
  protocol_v2::OutputBankMode bank_mode =
      protocol_v2::OutputBankMode::kDisabled;
  protocol_v2::OutputError error = protocol_v2::OutputError::kNone;
  std::uint32_t run_id = 0U;
  std::uint32_t current_state_mask = 0U;
  std::uint32_t last_emitted_state_mask = 0U;
  std::uint32_t current_segment_index = 0U;
  std::uint32_t current_segment_remaining = 0U;
  std::uint64_t start_tick = 0U;
  std::uint64_t completion_tick = 0U;
  std::uint64_t hold_tick = 0U;
  std::size_t ready_depth = 0U;
  std::size_t reading_depth = 0U;
  std::size_t refill_lead = 0U;
  std::uint8_t reading_block = kInvalidBlockIndex;
  bool prepared = false;
  bool expansion_finished = false;
  bool fault_latched = false;
};

struct ServiceReport {
  std::size_t blocks_filled = 0U;
  std::size_t states_expanded = 0U;
  bool expansion_finished = false;
};

struct StopReport {
  OperationStatus status = OperationStatus::kInvalidLifecycle;
  std::size_t active_states_emitted = 0U;
  std::uint32_t held_state_mask = 0U;
  bool dma_quiesced = false;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

// Output DMA is a memory reader, unlike the acquisition rings. The target
// adapter supplies the cache operation; the portable engine never includes a
// Teensy header or touches a register.
class CacheMaintenance {
 public:
  virtual ~CacheMaintenance() = default;
  virtual void flushBeforeDmaRead(const void *address,
                                  std::size_t bytes) = 0;
};

using CriticalSection = dma::CriticalSection;

// Optional participant boundary used by the existing common acquisition
// controller. A target adapter may implement the same boundary later; this
// phase wires only the portable implementation and does not instantiate it in
// the Teensy sketch.
class Participant {
 public:
  virtual ~Participant() = default;
  virtual bool participatesInNextStart() const = 0;
  virtual StartStatus inspectStart(std::uint32_t run_id) const = 0;
  virtual StartStatus prepareStart(std::uint32_t run_id,
                                   std::uint64_t epoch_ticks) = 0;
  virtual void commitCommonStart() = 0;
  virtual void rollbackPreparedStart() = 0;
  // Called only after the common trigger is disabled. A future target adapter
  // reads its own stopped transfer count; the portable engine has no implicit
  // in-flight states and exposes an explicit-progress helper for tests.
  virtual StopReport stopAfterTriggers() = 0;
  virtual ServiceReport service(std::size_t block_limit) = 0;
  virtual Snapshot snapshot() const = 0;
  virtual bool faulted() const = 0;
};

class Engine final : public Participant {
 public:
  constexpr Engine(ProgramStore &program, DmaBlockStorage &storage,
                   CacheMaintenance &cache, CriticalSection &critical)
      : program_(program),
        storage_(storage),
        cache_(cache),
        critical_(critical) {}

  Engine(const Engine &) = delete;
  Engine &operator=(const Engine &) = delete;

  ProgramStatus begin(std::uint32_t generation, std::uint32_t repeat_count,
                      std::uint32_t idle_state_mask);
  ProgramStatus append(std::uint32_t generation, const Segment &segment);
  ProgramStatus commit(std::uint32_t generation,
                       std::size_t expected_segment_count,
                       std::uint32_t expected_checksum);
  OperationStatus arm(std::uint32_t generation);
  OperationStatus clear(bool release_succeeded = true);

  bool participatesInNextStart() const override;
  StartStatus inspectStart(std::uint32_t run_id) const override;
  StartStatus prepareStart(std::uint32_t run_id,
                           std::uint64_t epoch_ticks) override;
  void commitCommonStart() override;
  void rollbackPreparedStart() override;
  StopReport stopAfterTriggers() override;
  StopReport stopAfterTriggersAtProgress(
      std::size_t active_states_emitted);
  ServiceReport service(std::size_t block_limit) override;
  Snapshot snapshot() const override;
  bool faulted() const override;

  OperationStatus onDmaBlockComplete(std::uint8_t block_index,
                                     std::uint32_t upload_generation,
                                     std::uint32_t lease);
  OperationStatus recordDmaFault(std::size_t active_states_emitted);

  constexpr const std::uint32_t *blockWords(std::size_t index) const {
    return storage_.blocks[index].data();
  }
  constexpr const BlockRecord &blockRecord(std::size_t index) const {
    return blocks_[index];
  }

 private:
  bool fillOneBlock(ServiceReport &report);
  bool promoteReadyBlock();
  std::uint32_t expandOneState();
  void applyCompletedBlock(std::uint8_t block_index);
  void applyEmittedPrefix(std::uint8_t block_index, std::size_t count);
  void updateCompletedRepeats();
  void releaseAllBlocks();
  void latchFault(protocol_v2::OutputError error,
                  std::size_t active_states_emitted);
  void resetPlayback();
  void refreshDepthHighWater();
  std::size_t readyDepth() const;
  std::size_t refillLead() const;
  std::uint8_t findReadyBlock() const;
  std::uint8_t readingBlock() const;
  static std::uint32_t physicalToggleMask(std::uint32_t logical_delta);
  static std::uint32_t logicalDeltaMask(std::uint32_t physical_toggle);

  ProgramStore &program_;
  DmaBlockStorage &storage_;
  CacheMaintenance &cache_;
  CriticalSection &critical_;
  std::array<BlockRecord, board::kAuxOutputDmaBlockCount> blocks_{};
  Telemetry telemetry_{};
  protocol_v2::OutputState state_ = protocol_v2::OutputState::kEmpty;
  protocol_v2::OutputBankMode bank_mode_ =
      protocol_v2::OutputBankMode::kDisabled;
  protocol_v2::OutputError error_ = protocol_v2::OutputError::kNone;
  std::size_t expand_segment_index_ = 0U;
  std::uint32_t expand_segment_remaining_ = 0U;
  std::uint32_t expanded_repeats_ = 0U;
  std::uint32_t expanded_logical_state_ = 0U;
  std::uint32_t last_emitted_state_ = 0U;
  std::uint32_t run_id_ = 0U;
  std::uint32_t next_lease_ = 0U;
  std::uint64_t next_block_sequence_ = 0U;
  std::uint64_t start_tick_ = 0U;
  std::uint64_t completion_tick_ = 0U;
  std::uint64_t hold_tick_ = 0U;
  bool prepared_ = false;
  bool expansion_finished_ = false;
};

static_assert(sizeof(DmaBlockStorage) ==
              board::kAuxOutputDmaStateStorageBytes);
static_assert(alignof(DmaBlockStorage) == board::kCacheLineBytes);
static_assert(sizeof(DmaDescriptorStorage) ==
              board::kAuxOutputDmaDescriptorBytes);
static_assert(alignof(DmaDescriptorStorage) == board::kCacheLineBytes);

}  // namespace thingdaq::digital_output
