#include "gpio_dual_bank_capture.h"

#include <limits>

#include "rate_profile_table.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_GPIO_DUAL_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_GPIO_DUAL_COLD_CODE(section_name)
#endif

namespace thingdaq::gpio_join {
namespace {

template <typename Integer>
void saturatingAdd(Integer &value, Integer amount) {
  const Integer maximum = std::numeric_limits<Integer>::max();
  value = amount > maximum - value ? maximum : value + amount;
}

template <typename Integer>
void saturatingIncrement(Integer &value) {
  saturatingAdd(value, Integer{1U});
}

constexpr bool isBufferDestination(std::uint8_t destination) {
  return destination < kRingDepth;
}

constexpr bool isDmaDestination(std::uint8_t destination) {
  return isBufferDestination(destination) ||
         destination == kOverflowDestination;
}

template <typename Integer>
Integer absoluteDifference(Integer left, Integer right) {
  return left >= right ? left - right : right - left;
}

bool validPeriod(std::uint32_t period) {
  for (const protocol_v2::RateProfileTiming &timing :
       rate_profile::kTimings) {
    if (period == timing.gpio_sample_period_ticks) {
      return true;
    }
  }
  return false;
}

}  // namespace

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.prime")
PrimeResult DualBankCaptureRing::prime(
    std::uint32_t epoch, std::uint32_t sample_period_ticks,
    std::uint32_t initial_generation, std::uint64_t first_sample_ticks) {
  PrimeResult result{};
  result.epoch = epoch;
  result.active_generation = initial_generation;
  result.queued_generation = initial_generation + 1U;
  if (epoch == 0U) {
    result.status = OperationStatus::kInvalidEpoch;
    return result;
  }
  if (!validPeriod(sample_period_ticks) ||
      first_sample_ticks % sample_period_ticks != 0U) {
    result.status = OperationStatus::kInvalidPeriod;
    return result;
  }
  const std::uint64_t coverage =
      static_cast<std::uint64_t>(kSamplesPerBlock) * sample_period_ticks;
  if (coverage > std::numeric_limits<std::uint64_t>::max() -
                     first_sample_ticks ||
      coverage > std::numeric_limits<std::uint64_t>::max() -
                     (first_sample_ticks + coverage)) {
    result.status = OperationStatus::kTimestampOverflow;
    return result;
  }

  const std::uint32_t token = critical_.enter();
  if (running_) {
    critical_.exit(token);
    result.status = OperationStatus::kAlreadyRunning;
    return result;
  }
  if (!allBuffersFree()) {
    critical_.exit(token);
    result.status = OperationStatus::kNotQuiescent;
    return result;
  }

  progress_ = {};
  generations_ = {};
  next_completion_generations_.fill(initial_generation);
  next_first_sample_ticks_ = first_sample_ticks;
  next_schedule_generation_ = initial_generation;
  sample_period_ticks_ = sample_period_ticks;
  epoch_ = epoch;
  next_free_search_ = 0U;
  running_ = true;

  GenerationSlot *const active = scheduleGeneration(initial_generation);
  GenerationSlot *const queued =
      scheduleGeneration(initial_generation + 1U);
  if (active == nullptr || queued == nullptr ||
      !isBufferDestination(active->destination) ||
      !isBufferDestination(queued->destination) ||
      active->destination == queued->destination) {
    noteInvariantError();
    running_ = false;
    epoch_ = 0U;
    sample_period_ticks_ = 0U;
    generations_ = {};
    records_ = {};
    critical_.exit(token);
    result.status = OperationStatus::kNotQuiescent;
    return result;
  }
  result.active_destination = active->destination;
  result.queued_destination = queued->destination;
  result.status = OperationStatus::kOk;
  critical_.exit(token);

  for (std::size_t index = 0U; index < kRingDepth; ++index) {
    for (std::size_t bank = 0U; bank < kBankCount; ++bank) {
      RawBlock &block = storage_.block(static_cast<Bank>(bank), index);
      cache_.discardBeforeDmaWrite(block.words.data(), sizeof(block));
      saturatingIncrement(progress_.cache_dma_discards);
    }
  }
  for (std::size_t bank = 0U; bank < kBankCount; ++bank) {
    cache_.discardBeforeDmaWrite(overflow_sink_.words[bank].data(),
                                 sizeof(overflow_sink_.words[bank]));
    saturatingIncrement(progress_.cache_dma_discards);
  }
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.reserve")
ReservationResult DualBankCaptureRing::reserveGeneration(
    std::uint32_t epoch, std::uint32_t generation) {
  ReservationResult result{};
  result.generation = generation;
  const std::uint32_t token = critical_.enter();
  if (!running_) {
    critical_.exit(token);
    return result;
  }
  if (epoch == 0U || epoch != epoch_) {
    critical_.exit(token);
    result.status = OperationStatus::kInvalidEpoch;
    return result;
  }
  GenerationSlot *const slot = scheduleGeneration(generation);
  if (slot == nullptr) {
    critical_.exit(token);
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }
  result.destination = slot->destination;
  result.first_sample_ticks = slot->expected_first_ticks;
  result.status = OperationStatus::kOk;
  critical_.exit(token);
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.complete")
CompletionResult DualBankCaptureRing::onMajorLoopComplete(
    Bank bank, std::uint32_t epoch, std::uint32_t generation,
    std::uint8_t destination, std::uint64_t first_sample_ticks,
    std::uint32_t sample_count) {
  CompletionResult result{};
  result.bank = bank;
  result.generation = generation;
  result.future_generation = generation + 2U;
  result.completed_destination = destination;

  const std::uint32_t token = critical_.enter();
  if (!running_) {
    saturatingIncrement(progress_.stale_completions);
    critical_.exit(token);
    result.status = OperationStatus::kNotRunning;
    return result;
  }
  if (epoch == 0U || epoch != epoch_) {
    saturatingIncrement(progress_.stale_completions);
    critical_.exit(token);
    result.status = OperationStatus::kInvalidEpoch;
    return result;
  }
  if (!validBank(bank)) {
    noteInvariantError();
    critical_.exit(token);
    result.status = OperationStatus::kInvalidBank;
    return result;
  }
  const std::size_t bank_index = bankIndex(bank);
  if (generation != next_completion_generations_[bank_index]) {
    saturatingIncrement(progress_.stale_completions);
    critical_.exit(token);
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }
  GenerationSlot *const completed = findGeneration(generation);
  if (completed == nullptr) {
    saturatingIncrement(progress_.schedule_exhaustions);
    noteInvariantError();
    next_completion_generations_[bank_index] = generation + 1U;
    result.consumed = true;
    result.pair_lost = true;
    critical_.exit(token);
    return result;
  }
  const std::uint8_t bank_bit =
      static_cast<std::uint8_t>(1U << bank_index);
  if ((completed->completion_mask & bank_bit) != 0U) {
    saturatingIncrement(progress_.stale_completions);
    critical_.exit(token);
    return result;
  }

  bool completion_valid = true;
  if (!isDmaDestination(destination) ||
      destination != completed->destination) {
    completed->invalid_data = true;
    // A contradictory destination means another scheduled buffer may have
    // received this bank's writes. Invalidate every unpublished generation;
    // no later completion may make potentially stale bank data visible.
    markOutstandingInvalid();
    completion_valid = false;
    saturatingIncrement(progress_.destination_mismatches);
  }
  if (sample_count != kSamplesPerBlock) {
    completed->invalid_data = true;
    completion_valid = false;
    saturatingIncrement(progress_.count_mismatches);
  }
  if (first_sample_ticks != completed->expected_first_ticks) {
    completed->invalid_data = true;
    completion_valid = false;
    saturatingIncrement(progress_.timestamp_mismatches);
  }

  completed->observed_first_ticks[bank_index] = first_sample_ticks;
  const std::uint32_t bounded_sample_count =
      sample_count > kSamplesPerBlock
          ? static_cast<std::uint32_t>(kSamplesPerBlock)
          : sample_count;
  completed->observed_counts[bank_index] = bounded_sample_count;
  completed->completion_mask = static_cast<std::uint8_t>(
      completed->completion_mask | bank_bit);
  result.completion_mask = completed->completion_mask;
  result.consumed = true;
  next_completion_generations_[bank_index] = generation + 1U;
  saturatingIncrement(progress_.bank_major_loops[bank_index]);
  saturatingAdd(progress_.bank_samples_completed[bank_index],
                static_cast<std::uint64_t>(bounded_sample_count));

  const std::uint64_t generation_skew = absoluteDifference(
      progress_.bank_major_loops[0], progress_.bank_major_loops[1]);
  if (generation_skew > 1U) {
    saturatingIncrement(progress_.generation_skew_events);
    markOutstandingInvalid();
    completion_valid = false;
  }

  GenerationSlot *const future = scheduleGeneration(result.future_generation);
  if (future == nullptr) {
    saturatingIncrement(progress_.schedule_exhaustions);
    markOutstandingInvalid();
    completion_valid = false;
    result.future_destination = kOverflowDestination;
  } else {
    result.future_destination = future->destination;
  }

  if (completed->completion_mask == kAllBanksMask) {
    finalizeGeneration(*completed, result);
  }
  result.status = completion_valid ? OperationStatus::kOk
                                   : OperationStatus::kInvalidCompletion;
  critical_.exit(token);
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.acquire")
AcquireResult DualBankCaptureRing::acquireReady() {
  (void)serviceDiscarded();
  AcquireResult result{};
  const std::uint32_t token = critical_.enter();
  std::uint8_t selected = kInvalidDestination;
  std::uint64_t oldest = std::numeric_limits<std::uint64_t>::max();
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferRecord &record = records_[index];
    if (record.state == BufferState::kReady &&
        record.first_sample_ticks < oldest) {
      selected = static_cast<std::uint8_t>(index);
      oldest = record.first_sample_ticks;
    }
  }
  if (!isBufferDestination(selected)) {
    critical_.exit(token);
    return result;
  }

  BufferRecord &record = records_[selected];
  record.state = BufferState::kReading;
  record.lease = allocateLease();
  result.handle.primary_words = storage_.primary[selected].words.data();
  result.handle.auxiliary_words =
      storage_.auxiliary[selected].words.data();
  result.handle.first_sample_ticks = record.first_sample_ticks;
  result.handle.sample_period_ticks = sample_period_ticks_;
  result.handle.sample_count = static_cast<std::uint32_t>(kSamplesPerBlock);
  result.handle.epoch = record.epoch;
  result.handle.generation = record.generation;
  result.handle.lease = record.lease;
  result.handle.buffer_index = selected;
  saturatingIncrement(progress_.buffers_acquired);
  saturatingAdd(progress_.sample_instants_delivered,
                static_cast<std::uint64_t>(kSamplesPerBlock));
  critical_.exit(token);

  cache_.invalidateBeforeCpuRead(storage_.primary[selected].words.data(),
                                 sizeof(RawBlock));
  cache_.invalidateBeforeCpuRead(storage_.auxiliary[selected].words.data(),
                                 sizeof(RawBlock));
  saturatingAdd(progress_.cache_cpu_invalidations, std::uint32_t{2U});
  result.status = OperationStatus::kOk;
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.release")
OperationStatus DualBankCaptureRing::release(const BufferHandle &handle) {
  std::uint32_t token = critical_.enter();
  if (!handleMatches(handle, BufferState::kReading)) {
    critical_.exit(token);
    return OperationStatus::kInvalidHandle;
  }
  records_[handle.buffer_index].state = BufferState::kReleasing;
  critical_.exit(token);

  cache_.discardBeforeDmaWrite(
      storage_.primary[handle.buffer_index].words.data(), sizeof(RawBlock));
  cache_.discardBeforeDmaWrite(
      storage_.auxiliary[handle.buffer_index].words.data(), sizeof(RawBlock));
  saturatingAdd(progress_.cache_dma_discards, std::uint32_t{2U});

  token = critical_.enter();
  if (!handleMatches(handle, BufferState::kReleasing)) {
    noteInvariantError();
    critical_.exit(token);
    return OperationStatus::kInvalidHandle;
  }
  records_[handle.buffer_index] = {};
  saturatingIncrement(progress_.buffers_released);
  critical_.exit(token);
  return OperationStatus::kOk;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.discard")
std::size_t DualBankCaptureRing::serviceDiscarded(std::size_t limit) {
  std::size_t serviced = 0U;
  while (serviced < limit) {
    std::uint8_t selected = kInvalidDestination;
    std::uint32_t token = critical_.enter();
    for (std::size_t index = 0U; index < records_.size(); ++index) {
      if (records_[index].state == BufferState::kDiscardPending) {
        selected = static_cast<std::uint8_t>(index);
        records_[index].state = BufferState::kReleasing;
        break;
      }
    }
    critical_.exit(token);
    if (!isBufferDestination(selected)) {
      break;
    }
    cache_.discardBeforeDmaWrite(storage_.primary[selected].words.data(),
                                 sizeof(RawBlock));
    cache_.discardBeforeDmaWrite(storage_.auxiliary[selected].words.data(),
                                 sizeof(RawBlock));
    saturatingAdd(progress_.cache_dma_discards, std::uint32_t{2U});
    token = critical_.enter();
    if (records_[selected].state != BufferState::kReleasing) {
      noteInvariantError();
      critical_.exit(token);
      break;
    }
    records_[selected] = {};
    critical_.exit(token);
    ++serviced;
  }
  return serviced;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.stop")
StopReport DualBankCaptureRing::stop(
    const std::array<BankStopState, kBankCount> &banks,
    StopReason reason) {
  StopReport report{};
  report.reason = reason;
  bool valid_progress = true;
  for (std::size_t bank = 0U; bank < kBankCount; ++bank) {
    if (banks[bank].generation != next_completion_generations_[bank] ||
        banks[bank].sample_count > kSamplesPerBlock ||
        (banks[bank].sample_count != 0U &&
         !isDmaDestination(banks[bank].destination))) {
      valid_progress = false;
    }
  }

  const std::uint32_t token = critical_.enter();
  if (!running_) {
    critical_.exit(token);
    return report;
  }
  running_ = false;

  for (const BankStopState &bank : banks) {
    if (bank.sample_count > kSamplesPerBlock) {
      saturatingIncrement(progress_.count_mismatches);
    }
  }

  for (GenerationSlot &slot : generations_) {
    if (!slot.valid) {
      continue;
    }
    std::array<std::uint32_t, kBankCount> contributed{};
    std::array<std::uint64_t, kBankCount> first_ticks{};
    for (std::size_t bank = 0U; bank < kBankCount; ++bank) {
      const std::uint8_t bit = static_cast<std::uint8_t>(1U << bank);
      if ((slot.completion_mask & bit) != 0U) {
        contributed[bank] = slot.observed_counts[bank];
        first_ticks[bank] = slot.observed_first_ticks[bank];
      } else if (banks[bank].generation == slot.generation) {
        contributed[bank] =
            banks[bank].sample_count > kSamplesPerBlock
                ? static_cast<std::uint32_t>(kSamplesPerBlock)
                : banks[bank].sample_count;
        first_ticks[bank] = banks[bank].first_sample_ticks;
        if (banks[bank].sample_count != 0U &&
            banks[bank].destination != slot.destination) {
          saturatingIncrement(progress_.destination_mismatches);
          valid_progress = false;
        }
      }
    }

    const std::uint32_t attempted =
        contributed[0] > contributed[1] ? contributed[0] : contributed[1];
    const std::uint32_t skew = absoluteDifference(
        contributed[0], contributed[1]);
    if (skew != 0U) {
      saturatingIncrement(progress_.generation_skew_events);
      saturatingAdd(progress_.generation_skew_samples,
                    static_cast<std::uint64_t>(skew));
      saturatingIncrement(progress_.count_mismatches);
    }
    if (contributed[0] != 0U && contributed[1] != 0U &&
        first_ticks[0] != first_ticks[1]) {
      saturatingIncrement(progress_.timestamp_mismatches);
    }
    if ((contributed[0] != 0U &&
         first_ticks[0] != slot.expected_first_ticks) ||
        (contributed[1] != 0U &&
         first_ticks[1] != slot.expected_first_ticks)) {
      saturatingIncrement(progress_.timestamp_mismatches);
      valid_progress = false;
    }

    saturatingIncrement(progress_.canceled_generations);
    ++report.generations_canceled;
    if (attempted != 0U) {
      saturatingAdd(progress_.sample_instants_captured,
                    static_cast<std::uint64_t>(attempted));
      saturatingAdd(progress_.sample_instants_lost,
                    static_cast<std::uint64_t>(attempted));
      saturatingAdd(report.samples_discarded,
                    static_cast<std::uint64_t>(attempted));
      if (reason == StopReason::kStop) {
        saturatingAdd(progress_.stop_tail_samples,
                      static_cast<std::uint64_t>(attempted));
      } else {
        saturatingAdd(progress_.cancellation_samples,
                      static_cast<std::uint64_t>(attempted));
      }
      if (slot.destination == kOverflowDestination) {
        saturatingIncrement(progress_.raw_ring_overruns);
      }
    }
    markDiscardPending(slot, &report);
    slot = {};
  }

  report.ready_buffers_to_drain = countState(BufferState::kReady);
  report.reading_buffers_to_release = countState(BufferState::kReading);
  report.status = valid_progress ? OperationStatus::kOk
                                 : OperationStatus::kInvalidStopProgress;
  critical_.exit(token);
  (void)serviceDiscarded();
  return report;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.cancel")
StopReport DualBankCaptureRing::cancel(std::uint32_t epoch,
                                       StopReason reason) {
  if (epoch == 0U || epoch != epoch_) {
    StopReport report{};
    report.reason = reason;
    report.status = OperationStatus::kInvalidEpoch;
    return report;
  }
  std::array<BankStopState, kBankCount> banks{};
  for (std::size_t bank = 0U; bank < kBankCount; ++bank) {
    banks[bank].generation = next_completion_generations_[bank];
  }
  return stop(banks, reason);
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.hardware_error")
void DualBankCaptureRing::recordHardwareError(std::uint32_t epoch) {
  const std::uint32_t token = critical_.enter();
  if (running_ && epoch != 0U && epoch == epoch_) {
    saturatingIncrement(progress_.hardware_errors);
    markOutstandingInvalid();
  }
  critical_.exit(token);
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.snapshot")
Snapshot DualBankCaptureRing::snapshot() {
  Snapshot result{};
  const std::uint32_t token = critical_.enter();
  result.progress = progress_;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    result.buffer_states[index] = records_[index].state;
    result.buffer_generations[index] = records_[index].generation;
  }
  result.next_completion_generations = next_completion_generations_;
  result.epoch = epoch_;
  result.sample_period_ticks = sample_period_ticks_;
  result.ready_depth = countState(BufferState::kReady);
  result.reading_depth = countState(BufferState::kReading);
  result.discard_depth = countState(BufferState::kDiscardPending) +
                         countState(BufferState::kReleasing);
  result.running = running_;
  result.quiescent = !running_ && allBuffersFree();
  critical_.exit(token);
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.quiescent")
bool DualBankCaptureRing::quiescent() {
  const std::uint32_t token = critical_.enter();
  const bool result = !running_ && allBuffersFree();
  critical_.exit(token);
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.destination")
std::uint32_t *DualBankCaptureRing::destinationWords(
    std::uint8_t destination, Bank bank) {
  if (!validBank(bank)) {
    return nullptr;
  }
  if (isBufferDestination(destination)) {
    return storage_.block(bank, destination).words.data();
  }
  return destination == kOverflowDestination
             ? overflow_sink_.words[bankIndex(bank)].data()
             : nullptr;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.destination_const")
const std::uint32_t *DualBankCaptureRing::destinationWords(
    std::uint8_t destination, Bank bank) const {
  if (!validBank(bank)) {
    return nullptr;
  }
  if (isBufferDestination(destination)) {
    return storage_.block(bank, destination).words.data();
  }
  return destination == kOverflowDestination
             ? overflow_sink_.words[bankIndex(bank)].data()
             : nullptr;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.find_generation")
DualBankCaptureRing::GenerationSlot *DualBankCaptureRing::findGeneration(
    std::uint32_t generation) {
  for (GenerationSlot &slot : generations_) {
    if (slot.valid && slot.generation == generation) {
      return &slot;
    }
  }
  return nullptr;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.schedule_generation")
DualBankCaptureRing::GenerationSlot *DualBankCaptureRing::scheduleGeneration(
    std::uint32_t generation) {
  GenerationSlot *const existing = findGeneration(generation);
  if (existing != nullptr) {
    return existing;
  }
  if (generation != next_schedule_generation_) {
    noteInvariantError();
    return nullptr;
  }
  GenerationSlot *available = nullptr;
  for (GenerationSlot &slot : generations_) {
    if (!slot.valid) {
      available = &slot;
      break;
    }
  }
  if (available == nullptr) {
    return nullptr;
  }
  const std::uint64_t coverage =
      static_cast<std::uint64_t>(kSamplesPerBlock) * sample_period_ticks_;
  if (coverage > std::numeric_limits<std::uint64_t>::max() -
                     next_first_sample_ticks_) {
    return nullptr;
  }

  available->generation = generation;
  available->expected_first_ticks = next_first_sample_ticks_;
  available->destination =
      takeFreeBuffer(generation, next_first_sample_ticks_);
  available->completion_mask = 0U;
  available->valid = true;
  available->invalid_data = false;
  next_schedule_generation_ = generation + 1U;
  next_first_sample_ticks_ += coverage;
  return available;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.take_free")
std::uint8_t DualBankCaptureRing::takeFreeBuffer(
    std::uint32_t generation, std::uint64_t first_sample_ticks) {
  for (std::size_t attempt = 0U; attempt < records_.size(); ++attempt) {
    const std::size_t index =
        (next_free_search_ + attempt) % records_.size();
    BufferRecord &record = records_[index];
    if (record.state != BufferState::kFree) {
      continue;
    }
    record.state = BufferState::kDmaOwned;
    record.epoch = epoch_;
    record.generation = generation;
    record.first_sample_ticks = first_sample_ticks;
    record.lease = 0U;
    next_free_search_ = (index + 1U) % records_.size();
    return static_cast<std::uint8_t>(index);
  }
  return kOverflowDestination;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.finalize")
void DualBankCaptureRing::finalizeGeneration(
    GenerationSlot &slot, CompletionResult &result) {
  result.completion_mask = slot.completion_mask;
  const std::uint32_t logical_samples =
      slot.observed_counts[0] > slot.observed_counts[1]
          ? slot.observed_counts[0]
          : slot.observed_counts[1];
  const std::uint32_t skew = absoluteDifference(
      slot.observed_counts[0], slot.observed_counts[1]);
  if (skew != 0U) {
    slot.invalid_data = true;
    saturatingIncrement(progress_.generation_skew_events);
    saturatingAdd(progress_.generation_skew_samples,
                  static_cast<std::uint64_t>(skew));
  }
  if (slot.observed_counts[0] != slot.observed_counts[1]) {
    slot.invalid_data = true;
  }
  if (slot.observed_first_ticks[0] != slot.observed_first_ticks[1]) {
    slot.invalid_data = true;
    saturatingIncrement(progress_.timestamp_mismatches);
  }

  saturatingIncrement(progress_.paired_major_loops);
  saturatingAdd(progress_.sample_instants_captured,
                static_cast<std::uint64_t>(logical_samples));
  const bool complete = logical_samples == kSamplesPerBlock &&
                        slot.observed_counts[0] == kSamplesPerBlock &&
                        slot.observed_counts[1] == kSamplesPerBlock;
  result.pair_lost = slot.invalid_data || !complete ||
                     slot.destination == kOverflowDestination;

  if (slot.destination == kOverflowDestination) {
    saturatingIncrement(progress_.raw_ring_overruns);
  } else if (!isBufferDestination(slot.destination)) {
    noteInvariantError();
    result.pair_lost = true;
  } else {
    BufferRecord &record = records_[slot.destination];
    const bool ownership_matches =
        record.state == BufferState::kDmaOwned && record.epoch == epoch_ &&
        record.generation == slot.generation &&
        record.first_sample_ticks == slot.expected_first_ticks;
    if (!ownership_matches) {
      noteInvariantError();
      result.pair_lost = true;
    }
    if (result.pair_lost) {
      if (ownership_matches) {
        record.state = BufferState::kDiscardPending;
      }
    } else {
      record.state = BufferState::kReady;
      saturatingIncrement(progress_.buffers_completed);
      saturatingAdd(progress_.sample_instants_joined,
                    static_cast<std::uint64_t>(kSamplesPerBlock));
      const std::size_t ready = countState(BufferState::kReady);
      if (ready > progress_.ready_high_water) {
        progress_.ready_high_water = ready;
      }
      result.pair_ready = true;
    }
  }
  if (result.pair_lost) {
    saturatingAdd(progress_.sample_instants_lost,
                  static_cast<std::uint64_t>(logical_samples));
  }
  slot = {};
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.invalidate")
void DualBankCaptureRing::markOutstandingInvalid() {
  for (GenerationSlot &slot : generations_) {
    if (slot.valid) {
      slot.invalid_data = true;
    }
  }
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.mark_discard")
void DualBankCaptureRing::markDiscardPending(const GenerationSlot &slot,
                                              StopReport *report) {
  if (!isBufferDestination(slot.destination)) {
    return;
  }
  BufferRecord &record = records_[slot.destination];
  if (record.state != BufferState::kDmaOwned || record.epoch != epoch_ ||
      record.generation != slot.generation) {
    noteInvariantError();
    return;
  }
  record.state = BufferState::kDiscardPending;
  if (report != nullptr) {
    ++report->buffers_discarded;
  }
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.count_state")
std::size_t DualBankCaptureRing::countState(BufferState state) const {
  std::size_t result = 0U;
  for (const BufferRecord &record : records_) {
    if (record.state == state) {
      ++result;
    }
  }
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.all_free")
bool DualBankCaptureRing::allBuffersFree() const {
  for (const BufferRecord &record : records_) {
    if (record.state != BufferState::kFree) {
      return false;
    }
  }
  return true;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.handle_matches")
bool DualBankCaptureRing::handleMatches(const BufferHandle &handle,
                                        BufferState state) const {
  if (!handle.valid()) {
    return false;
  }
  const BufferRecord &record = records_[handle.buffer_index];
  return record.state == state && record.epoch == handle.epoch &&
         record.generation == handle.generation &&
         record.first_sample_ticks == handle.first_sample_ticks &&
         record.lease == handle.lease &&
         handle.sample_period_ticks == sample_period_ticks_ &&
         handle.primary_words ==
             storage_.primary[handle.buffer_index].words.data() &&
         handle.auxiliary_words ==
             storage_.auxiliary[handle.buffer_index].words.data();
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.allocate_lease")
std::uint32_t DualBankCaptureRing::allocateLease() {
  std::uint32_t result = next_lease_++;
  if (result == 0U) {
    result = next_lease_++;
  }
  if (next_lease_ == 0U) {
    next_lease_ = 1U;
  }
  return result;
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.invariant")
void DualBankCaptureRing::noteInvariantError() {
  saturatingIncrement(progress_.invariant_errors);
}

THINGDAQ_GPIO_DUAL_COLD_CODE(".flashmem.gpio_dual.statistics")
stats::GpioRawCaptureProgress statisticsProgress(
    const Snapshot &snapshot) {
  stats::GpioRawCaptureProgress result{};
  result.major_loops_completed = snapshot.progress.paired_major_loops;
  result.buffers_completed = snapshot.progress.buffers_completed;
  result.buffers_acquired = snapshot.progress.buffers_acquired;
  result.buffers_released = snapshot.progress.buffers_released;
  result.samples_captured = snapshot.progress.sample_instants_captured;
  result.samples_delivered = snapshot.progress.sample_instants_delivered;
  result.raw_ring_overruns = snapshot.progress.raw_ring_overruns;
  result.samples_lost = snapshot.progress.sample_instants_lost;
  result.stop_discarded_samples = snapshot.progress.stop_tail_samples;
  result.cache_dma_discards = snapshot.progress.cache_dma_discards;
  result.cache_cpu_invalidations =
      snapshot.progress.cache_cpu_invalidations;
  result.ready_high_water = snapshot.progress.ready_high_water;
  result.ready_depth = snapshot.ready_depth;
  result.hardware_errors = snapshot.progress.hardware_errors;
  result.invariant_errors = snapshot.progress.invariant_errors;
  result.stale_dma_completions = snapshot.progress.stale_completions;
  return result;
}

}  // namespace thingdaq::gpio_join

#undef THINGDAQ_GPIO_DUAL_COLD_CODE
