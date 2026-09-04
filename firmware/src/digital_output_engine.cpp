#include "digital_output_engine.h"

#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_OUTPUT_ENGINE_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_OUTPUT_ENGINE_COLD_CODE(section_name)
#endif

namespace thingdaq::digital_output {
namespace {

template <typename Value>
void saturatingIncrement(Value &value) {
  if (value != std::numeric_limits<Value>::max()) {
    ++value;
  }
}

template <typename Value>
void saturatingAdd(Value &value, Value increment) {
  const Value maximum = std::numeric_limits<Value>::max();
  value = increment > maximum - value ? maximum : value + increment;
}

std::uint64_t tickAfterStates(std::uint64_t start_tick,
                              std::uint64_t states) {
  constexpr std::uint64_t period = protocol_v2::kOutputPeriodTicks;
  const std::uint64_t maximum = std::numeric_limits<std::uint64_t>::max();
  return states > (maximum - start_tick) / period
             ? maximum
             : start_tick + states * period;
}

}  // namespace

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.cache_destructor")
CacheMaintenance::~CacheMaintenance() = default;

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.destructor")
Engine::~Engine() = default;

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.begin")
ProgramStatus Engine::begin(std::uint32_t generation,
                            std::uint32_t repeat_count,
                            std::uint32_t idle_state_mask) {
  if (state_ != protocol_v2::OutputState::kEmpty &&
      state_ != protocol_v2::OutputState::kLoading) {
    saturatingIncrement(telemetry_.invalid_operations);
    return ProgramStatus::kInvalidLifecycle;
  }
  const ProgramStatus status =
      program_.begin(generation, repeat_count, idle_state_mask);
  if (status == ProgramStatus::kOk) {
    state_ = protocol_v2::OutputState::kLoading;
  } else {
    saturatingIncrement(telemetry_.invalid_operations);
  }
  return status;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.append")
ProgramStatus Engine::append(std::uint32_t generation,
                             const Segment &segment_value) {
  const ProgramStatus status = program_.append(generation, segment_value);
  if (status != ProgramStatus::kOk) {
    saturatingIncrement(telemetry_.invalid_operations);
  }
  return status;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.commit")
ProgramStatus Engine::commit(std::uint32_t generation,
                             std::size_t expected_segment_count,
                             std::uint32_t expected_checksum) {
  const ProgramStatus status = program_.commit(
      generation, expected_segment_count, expected_checksum);
  if (status == ProgramStatus::kOk) {
    state_ = protocol_v2::OutputState::kCommitted;
  } else {
    saturatingIncrement(telemetry_.invalid_operations);
  }
  return status;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.arm")
OperationStatus Engine::arm(std::uint32_t generation) {
  const ProgramSnapshot committed = program_.snapshot();
  if (generation == 0U || generation != committed.generation) {
    saturatingIncrement(telemetry_.invalid_operations);
    return OperationStatus::kInvalidGeneration;
  }
  if (state_ != protocol_v2::OutputState::kCommitted ||
      !committed.immutable) {
    saturatingIncrement(telemetry_.invalid_operations);
    return OperationStatus::kInvalidLifecycle;
  }

  resetPlayback();
  bank_mode_ = protocol_v2::OutputBankMode::kOutput;
  state_ = protocol_v2::OutputState::kArmed;
  expanded_logical_state_ = committed.idle_state_mask;
  last_emitted_state_ = committed.idle_state_mask;
  expand_segment_remaining_ = program_.segment(0U).duration_samples;
  ServiceReport prefill = service(board::kAuxOutputDmaBlockCount);
  if (prefill.blocks_filled == 0U) {
    if (state_ != protocol_v2::OutputState::kFaulted) {
      latchFault(protocol_v2::OutputError::kUnderrun, 0U);
    }
    return OperationStatus::kNotReady;
  }
  return OperationStatus::kOk;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.rollback_arm")
void Engine::rollbackArm() {
  const bool predrive_fault =
      state_ == protocol_v2::OutputState::kFaulted && run_id_ == 0U &&
      telemetry_.dma_states_emitted == 0U;
  if ((state_ != protocol_v2::OutputState::kArmed && !predrive_fault) ||
      prepared_) {
    return;
  }
  releaseAllBlocks();
  resetPlayback();
  state_ = protocol_v2::OutputState::kCommitted;
  bank_mode_ = protocol_v2::OutputBankMode::kDisabled;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.clear")
OperationStatus Engine::clear(bool release_succeeded) {
  if (state_ == protocol_v2::OutputState::kRunning || prepared_) {
    saturatingIncrement(telemetry_.invalid_operations);
    return OperationStatus::kAlreadyActive;
  }
  releaseAllBlocks();
  if (!release_succeeded) {
    state_ = protocol_v2::OutputState::kFaulted;
    error_ = protocol_v2::OutputError::kReleaseFailed;
    bank_mode_ = protocol_v2::OutputBankMode::kOutput;
    saturatingIncrement(telemetry_.invalid_operations);
    return OperationStatus::kReleaseFailed;
  }
  program_.clear();
  telemetry_ = {};
  state_ = protocol_v2::OutputState::kEmpty;
  bank_mode_ = protocol_v2::OutputBankMode::kDisabled;
  error_ = protocol_v2::OutputError::kNone;
  resetPlayback();
  return OperationStatus::kOk;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.participates")
bool Engine::participatesInNextStart() const {
  return state_ == protocol_v2::OutputState::kArmed;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.inspect")
StartStatus Engine::inspectStart(std::uint32_t run_id) const {
  if (run_id == 0U) {
    return StartStatus::kInvalidRunId;
  }
  if (prepared_ || state_ == protocol_v2::OutputState::kRunning) {
    return StartStatus::kAlreadyActive;
  }
  if (state_ != protocol_v2::OutputState::kArmed) {
    return StartStatus::kNotArmed;
  }
  return readyDepth() == 0U ? StartStatus::kNotReady : StartStatus::kOk;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.prepare")
StartStatus Engine::prepareStart(std::uint32_t run_id,
                                 std::uint64_t epoch_ticks) {
  const StartStatus status = inspectStart(run_id);
  if (status != StartStatus::kOk) {
    saturatingIncrement(telemetry_.start_errors);
    return status;
  }
  run_id_ = run_id;
  start_tick_ = epoch_ticks;
  completion_tick_ = 0U;
  hold_tick_ = 0U;
  const std::uint32_t token = critical_.enter();
  const bool promoted = promoteReadyBlock();
  critical_.exit(token);
  if (!promoted) {
    run_id_ = 0U;
    start_tick_ = 0U;
    saturatingIncrement(telemetry_.start_errors);
    return StartStatus::kNotReady;
  }
  prepared_ = true;
  return StartStatus::kOk;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.start")
void Engine::commitCommonStart() {
  if (prepared_ && state_ == protocol_v2::OutputState::kArmed) {
    prepared_ = false;
    state_ = protocol_v2::OutputState::kRunning;
    saturatingIncrement(telemetry_.start_operations);
  }
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.rollback")
void Engine::rollbackPreparedStart() {
  const bool committed_without_clock =
      state_ == protocol_v2::OutputState::kRunning &&
      telemetry_.dma_states_emitted == 0U;
  if (!prepared_ && !committed_without_clock) {
    return;
  }
  const std::uint32_t token = critical_.enter();
  const std::uint8_t reading = readingBlock();
  if (reading != kInvalidBlockIndex) {
    blocks_[reading].state = BlockState::kDmaReady;
  }
  critical_.exit(token);
  prepared_ = false;
  state_ = protocol_v2::OutputState::kArmed;
  run_id_ = 0U;
  start_tick_ = 0U;
  completion_tick_ = 0U;
  hold_tick_ = 0U;
  refreshDepthHighWater();
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.stop")
StopReport Engine::stopAfterTriggers() {
  return stopAfterTriggersAtProgress(0U);
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.stop_progress")
StopReport Engine::stopAfterTriggersAtProgress(
    std::size_t active_states_emitted,
    std::uint32_t observed_logical_state) {
  StopReport report{};
  const std::uint32_t token = critical_.enter();
  const std::uint8_t reading = readingBlock();
  if (reading != kInvalidBlockIndex) {
    if (active_states_emitted > blocks_[reading].valid_states) {
      saturatingIncrement(telemetry_.stop_errors);
      saturatingIncrement(telemetry_.conservation_errors);
      latchFault(protocol_v2::OutputError::kDmaFault, 0U);
      report.status = OperationStatus::kInvalidCompletion;
      report.held_state_mask = last_emitted_state_;
      report.dma_quiesced = true;
      critical_.exit(token);
      return report;
    }
    applyEmittedPrefix(reading, active_states_emitted);
  } else if (active_states_emitted != 0U) {
    saturatingIncrement(telemetry_.stop_errors);
    saturatingIncrement(telemetry_.conservation_errors);
    report.status = OperationStatus::kInvalidCompletion;
    report.held_state_mask = last_emitted_state_;
    critical_.exit(token);
    return report;
  }

  accountAndReleasePending(active_states_emitted);
  if (observed_logical_state != kUnknownLogicalState) {
    last_emitted_state_ = observed_logical_state & kLegalStateMask;
  }
  prepared_ = false;
  if (state_ != protocol_v2::OutputState::kFaulted) {
    state_ = protocol_v2::OutputState::kHeld;
    error_ = protocol_v2::OutputError::kNone;
  }
  hold_tick_ = tickAfterStates(start_tick_, telemetry_.dma_states_emitted);
  report.status = OperationStatus::kOk;
  report.active_states_emitted = active_states_emitted;
  report.held_state_mask = last_emitted_state_;
  report.dma_quiesced = true;
  saturatingIncrement(telemetry_.stop_operations);
  critical_.exit(token);
  return report;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.service")
ServiceReport Engine::service(std::size_t block_limit) {
  ServiceReport report{};
  if ((state_ != protocol_v2::OutputState::kArmed &&
       state_ != protocol_v2::OutputState::kRunning) ||
      expansion_finished_) {
    report.expansion_finished = expansion_finished_;
    return report;
  }
  const std::size_t bounded_limit =
      block_limit < board::kAuxOutputDmaBlockCount
          ? block_limit
          : board::kAuxOutputDmaBlockCount;
  while (report.blocks_filled < bounded_limit && fillOneBlock(report)) {
  }
  report.expansion_finished = expansion_finished_;
  refreshDepthHighWater();
  return report;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.snapshot")
Snapshot Engine::snapshot() const {
  return snapshotAtDmaProgress(0U);
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.snapshot_progress")
Snapshot Engine::snapshotAtDmaProgress(
    std::size_t active_states_emitted,
    std::uint32_t observed_logical_state) const {
  Snapshot result{};
  const std::uint32_t token = critical_.enter();
  result.program = program_.snapshot();
  result.telemetry = telemetry_;
  result.blocks = blocks_;
  result.state = state_;
  result.bank_mode = bank_mode_;
  result.error = error_;
  result.run_id = run_id_;
  result.current_state_mask = last_emitted_state_;
  result.last_emitted_state_mask = last_emitted_state_;
  result.start_tick = start_tick_;
  result.completion_tick = completion_tick_;
  result.hold_tick = hold_tick_;
  result.ready_depth = readyDepth();
  result.reading_block = readingBlock();
  result.reading_depth =
      result.reading_block == kInvalidBlockIndex ? 0U : 1U;
  result.refill_lead = refillLead();
  if (result.reading_block != kInvalidBlockIndex) {
    const BlockRecord &reading = blocks_[result.reading_block];
    if (active_states_emitted > reading.valid_states) {
      result.conservation_exact = false;
      active_states_emitted = reading.valid_states;
    }
    for (std::size_t index = 0U; index < active_states_emitted; ++index) {
      if (storage_.blocks[result.reading_block][index] != 0U) {
        saturatingIncrement(result.telemetry.transitions_emitted);
      }
    }
    saturatingAdd(result.telemetry.dma_states_emitted,
                  static_cast<std::uint64_t>(active_states_emitted));
    result.refill_lead -= active_states_emitted;
  } else if (active_states_emitted != 0U) {
    result.conservation_exact = false;
  }
  if (observed_logical_state != kUnknownLogicalState) {
    result.current_state_mask = observed_logical_state & kLegalStateMask;
    result.last_emitted_state_mask = result.current_state_mask;
  }
  result.dma_states_queued = result.telemetry.states_expanded;
  if (result.program.repeat_count != protocol_v2::kOutputRepeatForever &&
      result.program.duration_samples != 0U) {
    const std::uint64_t repeats = result.program.repeat_count;
    const std::uint64_t duration = result.program.duration_samples;
    result.requested_duration_states =
        repeats > std::numeric_limits<std::uint64_t>::max() / duration
            ? std::numeric_limits<std::uint64_t>::max()
            : repeats * duration;
  }
  result.conservation_exact =
      result.conservation_exact &&
      result.telemetry.conservation_errors == 0U &&
      result.telemetry.states_expanded ==
          result.telemetry.dma_states_emitted + result.refill_lead +
              result.telemetry.held_remainder_states;
  result.prepared = prepared_;
  result.expansion_finished = expansion_finished_;
  result.fault_latched = error_ != protocol_v2::OutputError::kNone;
  critical_.exit(token);

  const ProgramSnapshot program = result.program;
  const bool finite_complete =
      result.state == protocol_v2::OutputState::kHeld &&
      result.completion_tick != 0U && program.repeat_count != 0U &&
      result.telemetry.completed_repeats >= program.repeat_count;
  if (finite_complete && program.segment_count != 0U) {
    result.current_segment_index =
        static_cast<std::uint32_t>(program.segment_count - 1U);
    result.current_segment_remaining = 0U;
  } else if (program.duration_samples != 0U) {
    std::uint64_t offset =
        result.telemetry.dma_states_emitted % program.duration_samples;
    for (std::size_t index = 0U; index < program.segment_count; ++index) {
      const std::uint32_t duration = program_.segment(index).duration_samples;
      if (offset < duration) {
        result.current_segment_index = static_cast<std::uint32_t>(index);
        result.current_segment_remaining =
            duration - static_cast<std::uint32_t>(offset);
        break;
      }
      offset -= duration;
    }
  }
  return result;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.faulted")
bool Engine::faulted() const {
  const std::uint32_t token = critical_.enter();
  const bool result = state_ == protocol_v2::OutputState::kFaulted;
  critical_.exit(token);
  return result;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.completion")
OperationStatus Engine::onDmaBlockComplete(std::uint8_t block_index,
                                           std::uint32_t upload_generation,
                                           std::uint32_t lease) {
  const std::uint32_t token = critical_.enter();
  if (state_ != protocol_v2::OutputState::kRunning ||
      block_index >= blocks_.size() ||
      blocks_[block_index].state != BlockState::kDmaReading ||
      blocks_[block_index].upload_generation != upload_generation ||
      blocks_[block_index].lease != lease) {
    saturatingIncrement(telemetry_.invalid_operations);
    saturatingIncrement(telemetry_.stale_completions);
    critical_.exit(token);
    return OperationStatus::kInvalidCompletion;
  }
  // The completion path is intentionally constant work: the cooperative
  // expander recorded the final state and transition count while CPU-owned.
  // A target ISR can publish this ownership transition without interpreting
  // up to 1,016 toggle words.
  applyCompletedBlock(block_index);
  blocks_[block_index] = {};
  saturatingIncrement(telemetry_.blocks_completed);

  if (promoteReadyBlock()) {
    critical_.exit(token);
    return OperationStatus::kOk;
  }
  if (expansion_finished_) {
    state_ = protocol_v2::OutputState::kHeld;
    completion_tick_ =
        tickAfterStates(start_tick_, telemetry_.dma_states_emitted);
    hold_tick_ = completion_tick_;
    critical_.exit(token);
    return OperationStatus::kOk;
  }
  latchFault(protocol_v2::OutputError::kUnderrun, 0U);
  critical_.exit(token);
  return OperationStatus::kNotReady;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.dma_fault")
OperationStatus Engine::recordDmaFault(
    std::size_t active_states_emitted,
    std::uint32_t observed_logical_state) {
  const std::uint32_t token = critical_.enter();
  if (state_ != protocol_v2::OutputState::kRunning) {
    saturatingIncrement(telemetry_.invalid_operations);
    critical_.exit(token);
    return OperationStatus::kInvalidLifecycle;
  }
  latchFault(protocol_v2::OutputError::kDmaFault, active_states_emitted,
             observed_logical_state);
  critical_.exit(token);
  return OperationStatus::kOk;
}

#if defined(THINGDAQ_TESTING)
THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.test_injection")
OperationStatus Engine::injectFaultForTest(
    InjectedFault fault, std::uint32_t observed_logical_state) {
  const std::uint32_t token = critical_.enter();
  if (fault == InjectedFault::kResourceConflict) {
    saturatingIncrement(telemetry_.resource_conflicts);
    critical_.exit(token);
    return OperationStatus::kNotReady;
  }
  if (state_ != protocol_v2::OutputState::kRunning) {
    saturatingIncrement(telemetry_.invalid_operations);
    critical_.exit(token);
    return OperationStatus::kInvalidLifecycle;
  }
  latchFault(fault == InjectedFault::kUnderrun
                 ? protocol_v2::OutputError::kUnderrun
                 : protocol_v2::OutputError::kDmaFault,
             0U, observed_logical_state);
  critical_.exit(token);
  return OperationStatus::kOk;
}
#endif

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.fill")
bool Engine::fillOneBlock(ServiceReport &report) {
  std::uint8_t selected = kInvalidBlockIndex;
  const std::uint32_t claim_token = critical_.enter();
  for (std::size_t index = 0U; index < blocks_.size(); ++index) {
    if (blocks_[index].state == BlockState::kFree) {
      selected = static_cast<std::uint8_t>(index);
      break;
    }
  }
  if (selected == kInvalidBlockIndex || expansion_finished_) {
    critical_.exit(claim_token);
    return false;
  }

  BlockRecord &record = blocks_[selected];
  record.state = BlockState::kCpuFilling;
  record.upload_generation = program_.snapshot().generation;
  ++next_lease_;
  if (next_lease_ == 0U) {
    ++next_lease_;
  }
  record.lease = next_lease_;
  record.sequence = next_block_sequence_;
  saturatingIncrement(next_block_sequence_);
  record.valid_states = 0U;
  record.transition_count = 0U;
  critical_.exit(claim_token);

  while (record.valid_states < board::kAuxOutputStatesPerBlock &&
         !expansion_finished_) {
    const std::uint32_t toggle = expandOneState();
    storage_.blocks[selected][record.valid_states] = toggle;
    if (toggle != 0U) {
      ++record.transition_count;
    }
    ++record.valid_states;
  }
  if (record.valid_states == 0U) {
    const std::uint32_t empty_token = critical_.enter();
    record = {};
    critical_.exit(empty_token);
    return false;
  }
  record.final_logical_state = expanded_logical_state_;
  if (!cache_.prepareBeforeDmaRead(
          selected, storage_.blocks[selected].data(),
          record.valid_states * sizeof(std::uint32_t),
          record.valid_states)) {
    const std::uint32_t failed_token = critical_.enter();
    latchFault(protocol_v2::OutputError::kDmaFault, 0U);
    critical_.exit(failed_token);
    return false;
  }
  saturatingIncrement(telemetry_.cache_flushes);
  saturatingIncrement(telemetry_.blocks_filled);
  const std::uint32_t publish_token = critical_.enter();
  if (record.state != BlockState::kCpuFilling ||
      (state_ != protocol_v2::OutputState::kArmed &&
       state_ != protocol_v2::OutputState::kRunning)) {
    record = {};
    critical_.exit(publish_token);
    return false;
  }
  record.state = BlockState::kDmaReady;
  critical_.exit(publish_token);
  ++report.blocks_filled;
  report.states_expanded += record.valid_states;
  return true;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.promote")
bool Engine::promoteReadyBlock() {
  const std::uint8_t selected = findReadyBlock();
  if (selected == kInvalidBlockIndex) {
    return false;
  }
  blocks_[selected].state = BlockState::kDmaReading;
  return true;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.expand")
std::uint32_t Engine::expandOneState() {
  const Segment &segment_value = program_.segment(expand_segment_index_);
  const std::uint32_t next_state = segment_value.logical_state_mask;
  const std::uint32_t toggle = physicalMaskForLogicalState(
      expanded_logical_state_ ^ next_state);
  expanded_logical_state_ = next_state;
  saturatingIncrement(telemetry_.states_expanded);

  --expand_segment_remaining_;
  if (expand_segment_remaining_ != 0U) {
    return toggle;
  }
  ++expand_segment_index_;
  if (expand_segment_index_ < program_.snapshot().segment_count) {
    expand_segment_remaining_ =
        program_.segment(expand_segment_index_).duration_samples;
    return toggle;
  }

  saturatingIncrement(expanded_repeats_);
  const std::uint32_t repeat_count = program_.snapshot().repeat_count;
  if (repeat_count != protocol_v2::kOutputRepeatForever &&
      expanded_repeats_ >= repeat_count) {
    expansion_finished_ = true;
    return toggle;
  }
  expand_segment_index_ = 0U;
  expand_segment_remaining_ = program_.segment(0U).duration_samples;
  return toggle;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.apply_complete")
void Engine::applyCompletedBlock(std::uint8_t block_index) {
  const BlockRecord &record = blocks_[block_index];
  last_emitted_state_ = record.final_logical_state;
  saturatingAdd(telemetry_.dma_states_emitted,
                static_cast<std::uint64_t>(record.valid_states));
  saturatingAdd(telemetry_.transitions_emitted,
                static_cast<std::uint64_t>(record.transition_count));
  updateCompletedRepeats();
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.apply_prefix")
void Engine::applyEmittedPrefix(std::uint8_t block_index, std::size_t count) {
  for (std::size_t index = 0U; index < count; ++index) {
    const std::uint32_t toggle = storage_.blocks[block_index][index];
    last_emitted_state_ ^= logicalStateFromPhysicalMask(toggle);
    if (toggle != 0U) {
      saturatingIncrement(telemetry_.transitions_emitted);
    }
  }
  saturatingAdd(telemetry_.dma_states_emitted,
                static_cast<std::uint64_t>(count));
  updateCompletedRepeats();
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.repeats")
void Engine::updateCompletedRepeats() {
  const std::uint64_t duration = program_.snapshot().duration_samples;
  if (duration != 0U) {
    const std::uint64_t repeats = telemetry_.dma_states_emitted / duration;
    telemetry_.completed_repeats =
        repeats > std::numeric_limits<std::uint32_t>::max()
            ? std::numeric_limits<std::uint32_t>::max()
            : static_cast<std::uint32_t>(repeats);
  }
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.release")
void Engine::releaseAllBlocks() {
  for (BlockRecord &record : blocks_) {
    record = {};
  }
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.account_release")
void Engine::accountAndReleasePending(std::size_t emitted_reading_prefix) {
  const std::size_t pending = pendingStates();
  const std::uint64_t remainder =
      emitted_reading_prefix > pending
          ? 0U
          : static_cast<std::uint64_t>(pending - emitted_reading_prefix);
  if (emitted_reading_prefix > pending) {
    saturatingIncrement(telemetry_.conservation_errors);
  }
  saturatingAdd(telemetry_.held_remainder_states, remainder);
  releaseAllBlocks();
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.latch_fault")
void Engine::latchFault(protocol_v2::OutputError error,
                        std::size_t active_states_emitted,
                        std::uint32_t observed_logical_state) {
  const std::uint8_t reading = readingBlock();
  std::size_t accounted_emitted = 0U;
  if (reading != kInvalidBlockIndex &&
      active_states_emitted <= blocks_[reading].valid_states) {
    applyEmittedPrefix(reading, active_states_emitted);
    accounted_emitted = active_states_emitted;
  } else if (active_states_emitted != 0U) {
    saturatingIncrement(telemetry_.conservation_errors);
  }
  if (observed_logical_state != kUnknownLogicalState) {
    last_emitted_state_ = observed_logical_state & kLegalStateMask;
  }
  if (error == protocol_v2::OutputError::kUnderrun) {
    saturatingIncrement(telemetry_.underruns);
  } else if (error == protocol_v2::OutputError::kDmaFault) {
    saturatingIncrement(telemetry_.dma_errors);
  }
  accountAndReleasePending(accounted_emitted);
  prepared_ = false;
  state_ = protocol_v2::OutputState::kFaulted;
  error_ = error;
  hold_tick_ = tickAfterStates(start_tick_, telemetry_.dma_states_emitted);
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.reset")
void Engine::resetPlayback() {
  releaseAllBlocks();
  telemetry_ = {};
  error_ = protocol_v2::OutputError::kNone;
  expand_segment_index_ = 0U;
  expand_segment_remaining_ = 0U;
  expanded_repeats_ = 0U;
  expanded_logical_state_ = 0U;
  last_emitted_state_ = 0U;
  run_id_ = 0U;
  next_block_sequence_ = 0U;
  start_tick_ = 0U;
  completion_tick_ = 0U;
  hold_tick_ = 0U;
  prepared_ = false;
  expansion_finished_ = false;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.depth")
void Engine::refreshDepthHighWater() {
  const std::uint32_t token = critical_.enter();
  const std::size_t ready = readyDepth();
  const std::size_t lead = refillLead();
  if (ready > telemetry_.ready_high_water) {
    telemetry_.ready_high_water = ready;
  }
  if (lead > telemetry_.refill_lead_high_water) {
    telemetry_.refill_lead_high_water = lead;
  }
  critical_.exit(token);
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.ready_depth")
std::size_t Engine::readyDepth() const {
  std::size_t depth = 0U;
  for (const BlockRecord &record : blocks_) {
    if (record.state == BlockState::kDmaReady) {
      ++depth;
    }
  }
  return depth;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.refill_lead")
std::size_t Engine::refillLead() const {
  std::size_t states = 0U;
  for (const BlockRecord &record : blocks_) {
    if (record.state == BlockState::kDmaReady ||
        record.state == BlockState::kDmaReading) {
      states += record.valid_states;
    }
  }
  return states;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.pending_states")
std::size_t Engine::pendingStates() const {
  std::size_t states = 0U;
  for (const BlockRecord &record : blocks_) {
    if (record.state != BlockState::kFree) {
      states += record.valid_states;
    }
  }
  return states;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.find_ready")
std::uint8_t Engine::findReadyBlock() const {
  std::uint8_t selected = kInvalidBlockIndex;
  std::uint64_t sequence = std::numeric_limits<std::uint64_t>::max();
  for (std::size_t index = 0U; index < blocks_.size(); ++index) {
    if (blocks_[index].state == BlockState::kDmaReady &&
        blocks_[index].sequence < sequence) {
      selected = static_cast<std::uint8_t>(index);
      sequence = blocks_[index].sequence;
    }
  }
  return selected;
}

THINGDAQ_OUTPUT_ENGINE_COLD_CODE(".flashmem.output.engine.reading")
std::uint8_t Engine::readingBlock() const {
  for (std::size_t index = 0U; index < blocks_.size(); ++index) {
    if (blocks_[index].state == BlockState::kDmaReading) {
      return static_cast<std::uint8_t>(index);
    }
  }
  return kInvalidBlockIndex;
}

}  // namespace thingdaq::digital_output

#undef THINGDAQ_OUTPUT_ENGINE_COLD_CODE
