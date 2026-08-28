#include "adc_dma_capture.h"

#include <limits>

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_ADC_DMA_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_ADC_DMA_COLD_CODE(section_name)
#endif

namespace teensy_daq::adc_capture {
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
  return destination < board::kAdcDmaRingDepth;
}

constexpr bool isDmaDestination(std::uint8_t destination) {
  return isBufferDestination(destination) ||
         destination == kOverflowDestination;
}

std::uint64_t absoluteDifference(std::uint64_t left,
                                 std::uint64_t right) {
  return left >= right ? left - right : right - left;
}

}  // namespace

TEENSY_DAQ_ADC_DMA_COLD_CODE(".flashmem.adc_dma.prime")
PrimeResult PairCaptureRing::prime(std::uint32_t epoch,
                                   std::uint32_t initial_generation,
                                   std::uint64_t first_pair) {
  PrimeResult result{};
  result.epoch = epoch;
  result.active_generation = initial_generation;
  result.queued_generation = initial_generation + 1U;
  if (epoch == 0U) {
    result.status = OperationStatus::kInvalidEpoch;
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
  next_first_pair_ = first_pair;
  next_schedule_generation_ = initial_generation;
  next_free_search_ = 0U;
  epoch_ = epoch;
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
    generations_ = {};
    for (BufferRecord &record : records_) {
      record = {};
    }
    critical_.exit(token);
    result.status = OperationStatus::kNotQuiescent;
    return result;
  }
  result.active_destination = active->destination;
  result.queued_destination = queued->destination;
  result.status = OperationStatus::kOk;
  critical_.exit(token);

  // No eDMA request may be enabled until prime() returns. Preparing every
  // cache line here therefore precedes the first possible DMA write.
  for (PairBuffer &buffer : storage_.buffers) {
    cache_.discardBeforeDmaWrite(buffer.pairs.data(), sizeof(buffer));
  }
  cache_.discardBeforeDmaWrite(overflow_sink_.halfwords.data(),
                               sizeof(overflow_sink_));
  return result;
}

CompletionResult PairCaptureRing::onMajorLoopComplete(
    std::uint8_t converter, std::uint32_t epoch,
    std::uint32_t generation, std::uint8_t destination) {
  CompletionResult result{};
  result.converter = converter;
  result.epoch = epoch;
  result.completed_generation = generation;
  result.completed_destination = destination;
  result.future_generation = generation + 2U;

  if (!running_) {
    saturatingIncrement(progress_.stale_completions);
    result.status = OperationStatus::kNotRunning;
    return result;
  }
  if (epoch == 0U || epoch != epoch_) {
    saturatingIncrement(progress_.stale_completions);
    result.status = OperationStatus::kInvalidEpoch;
    return result;
  }
  if (converter >= kConverterCount) {
    noteInvariantError();
    result.status = OperationStatus::kInvalidConverter;
    return result;
  }
  if (generation != next_completion_generations_[converter]) {
    saturatingIncrement(progress_.stale_completions);
    saturatingIncrement(progress_.completion_mismatches);
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }

  GenerationSlot *const completed = findGeneration(generation);
  if (completed == nullptr) {
    saturatingIncrement(progress_.schedule_exhaustions);
    saturatingIncrement(progress_.completion_mismatches);
    noteInvariantError();
    next_completion_generations_[converter] = generation + 1U;
    result.consumed = true;
    result.pair_lost = true;
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }

  const std::uint8_t converter_bit =
      static_cast<std::uint8_t>(1U << converter);
  if ((completed->completion_mask & converter_bit) != 0U) {
    saturatingIncrement(progress_.stale_completions);
    saturatingIncrement(progress_.completion_mismatches);
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }

  bool completion_valid = true;
  if (destination != completed->destination ||
      !isDmaDestination(destination)) {
    completed->invalid_data = true;
    completion_valid = false;
    saturatingIncrement(progress_.destination_mismatches);
    saturatingIncrement(progress_.completion_mismatches);
  }

  completed->completion_mask = static_cast<std::uint8_t>(
      completed->completion_mask | converter_bit);
  result.completion_mask = completed->completion_mask;
  result.consumed = true;
  next_completion_generations_[converter] = generation + 1U;
  saturatingIncrement(progress_.channel_major_loops[converter]);
  saturatingAdd(
      progress_.channel_results[converter],
      static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame));

  if (absoluteDifference(progress_.channel_major_loops[0],
                         progress_.channel_major_loops[1]) > 1U) {
    saturatingIncrement(progress_.completion_mismatches);
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

  if (completed->completion_mask == kAllConvertersMask) {
    finalizeGeneration(*completed, result);
  }
  result.status = completion_valid ? OperationStatus::kOk
                                   : OperationStatus::kInvalidCompletion;
  return result;
}

void PairCaptureRing::recordAdcEtcError(std::uint32_t epoch,
                                        std::uint8_t converter_mask,
                                        std::uint32_t raw_flags) {
  if (!running_ || epoch == 0U || epoch != epoch_) {
    return;
  }
  const std::uint8_t known_mask =
      static_cast<std::uint8_t>(converter_mask & kAllConvertersMask);
  if (known_mask == 0U || known_mask != converter_mask) {
    noteInvariantError();
  }
  saturatingIncrement(progress_.adc_etc_error_events);
  progress_.adc_etc_error_flags |= raw_flags;
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    if ((known_mask & (1U << converter)) == 0U) {
      continue;
    }
    saturatingIncrement(progress_.overwritten_conversions);
    markGenerationInvalid(next_completion_generations_[converter], 1U);
  }
}

void PairCaptureRing::recordDmaError(std::uint32_t epoch,
                                     std::uint8_t converter) {
  if (!running_ || epoch == 0U || epoch != epoch_) {
    return;
  }
  if (converter >= kConverterCount) {
    noteInvariantError();
    return;
  }
  saturatingIncrement(progress_.dma_error_events);
  markGenerationInvalid(next_completion_generations_[converter]);
}

TEENSY_DAQ_ADC_DMA_COLD_CODE(".flashmem.adc_dma.acquire")
AcquireResult PairCaptureRing::acquireReady() {
  (void)serviceDiscarded();
  AcquireResult result{};
  const std::uint32_t token = critical_.enter();
  std::uint8_t selected = kInvalidDestination;
  std::uint64_t oldest = std::numeric_limits<std::uint64_t>::max();
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferRecord &record = records_[index];
    if (record.state == BufferState::kReady && record.first_pair < oldest) {
      selected = static_cast<std::uint8_t>(index);
      oldest = record.first_pair;
    }
  }
  if (!isBufferDestination(selected)) {
    critical_.exit(token);
    return result;
  }

  BufferRecord &record = records_[selected];
  record.state = BufferState::kReading;
  record.lease = allocateLease();
  result.handle.pairs = storage_.buffers[selected].pairs.data();
  result.handle.first_pair = record.first_pair;
  result.handle.pair_count = static_cast<std::uint32_t>(
      protocol_v1::kAdcPairsPerFrame);
  result.handle.epoch = record.epoch;
  result.handle.lease = record.lease;
  result.handle.buffer_index = selected;
  saturatingIncrement(progress_.buffers_acquired);
  saturatingAdd(progress_.pairs_delivered,
                static_cast<std::uint64_t>(
                    protocol_v1::kAdcPairsPerFrame));
  critical_.exit(token);

  cache_.invalidateBeforeCpuRead(
      storage_.buffers[selected].pairs.data(), sizeof(PairBuffer));
  result.status = OperationStatus::kOk;
  return result;
}

TEENSY_DAQ_ADC_DMA_COLD_CODE(".flashmem.adc_dma.release")
OperationStatus PairCaptureRing::release(const BufferHandle &handle) {
  std::uint32_t token = critical_.enter();
  if (!handleMatches(handle, BufferState::kReading)) {
    critical_.exit(token);
    return OperationStatus::kInvalidHandle;
  }
  records_[handle.buffer_index].state = BufferState::kReleasing;
  critical_.exit(token);

  cache_.discardBeforeDmaWrite(
      storage_.buffers[handle.buffer_index].pairs.data(),
      sizeof(PairBuffer));

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

TEENSY_DAQ_ADC_DMA_COLD_CODE(".flashmem.adc_dma.service_discarded")
std::size_t PairCaptureRing::serviceDiscarded(std::size_t limit) {
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

    cache_.discardBeforeDmaWrite(
        storage_.buffers[selected].pairs.data(), sizeof(PairBuffer));
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

TEENSY_DAQ_ADC_DMA_COLD_CODE(".flashmem.adc_dma.stop")
StopReport PairCaptureRing::stop(
    const std::array<ChannelStopState, kConverterCount> &channels) {
  StopReport report{};
  bool valid_progress = true;
  for (std::size_t converter = 0U; converter < kConverterCount;
       ++converter) {
    if (channels[converter].minor_pairs >
            protocol_v1::kAdcPairsPerFrame ||
        !isDmaDestination(channels[converter].destination) ||
        channels[converter].generation !=
            next_completion_generations_[converter]) {
      valid_progress = false;
    }
  }

  const std::uint32_t token = critical_.enter();
  if (!running_) {
    critical_.exit(token);
    return report;
  }
  running_ = false;

  for (GenerationSlot &slot : generations_) {
    if (!slot.valid) {
      continue;
    }
    std::array<std::uint32_t, kConverterCount> contributed{};
    for (std::size_t converter = 0U; converter < kConverterCount;
         ++converter) {
      const std::uint8_t bit = static_cast<std::uint8_t>(1U << converter);
      if ((slot.completion_mask & bit) != 0U) {
        contributed[converter] = static_cast<std::uint32_t>(
            protocol_v1::kAdcPairsPerFrame);
      } else if (channels[converter].generation == slot.generation) {
        contributed[converter] =
            channels[converter].minor_pairs >
                    protocol_v1::kAdcPairsPerFrame
                ? static_cast<std::uint32_t>(
                      protocol_v1::kAdcPairsPerFrame)
                : channels[converter].minor_pairs;
        if (channels[converter].destination != slot.destination) {
          slot.invalid_data = true;
          saturatingIncrement(progress_.destination_mismatches);
          valid_progress = false;
        }
      }
    }

    std::uint32_t lost = contributed[0] > contributed[1]
                             ? contributed[0]
                             : contributed[1];
    if (lost < slot.minimum_lost_pairs) {
      // An ADC_ETC overwrite flag proves at least one pair instant was
      // affected even if STOP observed the TCD before its first result write.
      lost = slot.minimum_lost_pairs;
    }
    if (lost != 0U) {
      saturatingAdd(progress_.pairs_captured,
                    static_cast<std::uint64_t>(lost));
      saturatingAdd(progress_.pairs_lost,
                    static_cast<std::uint64_t>(lost));
      saturatingAdd(progress_.stop_discarded_pairs,
                    static_cast<std::uint64_t>(lost));
      saturatingAdd(report.pairs_discarded,
                    static_cast<std::uint64_t>(lost));
      if (slot.destination == kOverflowDestination) {
        saturatingIncrement(progress_.ring_overruns);
      } else {
        saturatingIncrement(progress_.incomplete_buffers);
      }
    }

    const std::uint64_t difference = absoluteDifference(
        contributed[0], contributed[1]);
    if (difference != 0U) {
      saturatingAdd(progress_.incomplete_conversions, difference);
      saturatingIncrement(progress_.completion_mismatches);
    }

    if (isBufferDestination(slot.destination)) {
      BufferRecord &record = records_[slot.destination];
      if (record.state != BufferState::kDmaOwned ||
          record.epoch != epoch_ || record.generation != slot.generation) {
        noteInvariantError();
        valid_progress = false;
      } else {
        record.state = BufferState::kDiscardPending;
        ++report.buffers_discarded;
      }
    }
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

TEENSY_DAQ_ADC_DMA_COLD_CODE(".flashmem.adc_dma.snapshot")
Snapshot PairCaptureRing::snapshot() {
  Snapshot value{};
  const std::uint32_t token = critical_.enter();
  value.progress = progress_;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    value.buffer_states[index] = records_[index].state;
    value.buffer_generations[index] = records_[index].generation;
  }
  value.next_completion_generations = next_completion_generations_;
  value.epoch = epoch_;
  value.ready_depth = countState(BufferState::kReady);
  value.reading_depth = countState(BufferState::kReading);
  value.discard_depth = countState(BufferState::kDiscardPending) +
                        countState(BufferState::kReleasing);
  value.running = running_;
  value.quiescent = !running_ && allBuffersFree();
  critical_.exit(token);
  return value;
}

bool PairCaptureRing::quiescent() {
  const std::uint32_t token = critical_.enter();
  const bool value = !running_ && allBuffersFree();
  critical_.exit(token);
  return value;
}

std::uint16_t *PairCaptureRing::destinationHalfword(
    std::uint8_t destination, std::uint8_t converter) {
  if (converter >= kConverterCount) {
    return nullptr;
  }
  if (isBufferDestination(destination)) {
    return reinterpret_cast<std::uint16_t *>(
               storage_.buffers[destination].pairs.data()) +
           converter;
  }
  return destination == kOverflowDestination
             ? overflow_sink_.halfwords.data() + converter
             : nullptr;
}

const std::uint16_t *PairCaptureRing::destinationHalfword(
    std::uint8_t destination, std::uint8_t converter) const {
  if (converter >= kConverterCount) {
    return nullptr;
  }
  if (isBufferDestination(destination)) {
    return reinterpret_cast<const std::uint16_t *>(
               storage_.buffers[destination].pairs.data()) +
           converter;
  }
  return destination == kOverflowDestination
             ? overflow_sink_.halfwords.data() + converter
             : nullptr;
}

PairCaptureRing::GenerationSlot *PairCaptureRing::findGeneration(
    std::uint32_t generation) {
  for (GenerationSlot &slot : generations_) {
    if (slot.valid && slot.generation == generation) {
      return &slot;
    }
  }
  return nullptr;
}

const PairCaptureRing::GenerationSlot *PairCaptureRing::findGeneration(
    std::uint32_t generation) const {
  for (const GenerationSlot &slot : generations_) {
    if (slot.valid && slot.generation == generation) {
      return &slot;
    }
  }
  return nullptr;
}

PairCaptureRing::GenerationSlot *PairCaptureRing::scheduleGeneration(
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

  available->generation = generation;
  available->first_pair = next_first_pair_;
  available->destination = takeFreeBuffer(generation, next_first_pair_);
  available->completion_mask = 0U;
  available->minimum_lost_pairs = 0U;
  available->valid = true;
  available->invalid_data = false;
  next_schedule_generation_ = generation + 1U;
  saturatingAdd(
      next_first_pair_,
      static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame));
  return available;
}

std::uint8_t PairCaptureRing::takeFreeBuffer(
    std::uint32_t generation, std::uint64_t first_pair) {
  for (std::size_t attempt = 0U; attempt < records_.size(); ++attempt) {
    const std::size_t candidate =
        (next_free_search_ + attempt) % records_.size();
    BufferRecord &record = records_[candidate];
    if (record.state != BufferState::kFree) {
      continue;
    }
    record.state = BufferState::kDmaOwned;
    record.epoch = epoch_;
    record.generation = generation;
    record.first_pair = first_pair;
    record.lease = 0U;
    next_free_search_ = (candidate + 1U) % records_.size();
    return static_cast<std::uint8_t>(candidate);
  }
  return kOverflowDestination;
}

void PairCaptureRing::markOutstandingInvalid() {
  for (GenerationSlot &slot : generations_) {
    if (slot.valid) {
      slot.invalid_data = true;
    }
  }
}

void PairCaptureRing::markGenerationInvalid(
    std::uint32_t generation, std::uint32_t minimum_lost_pairs) {
  GenerationSlot *const slot = findGeneration(generation);
  if (slot == nullptr) {
    saturatingIncrement(progress_.schedule_exhaustions);
    noteInvariantError();
    return;
  }
  slot->invalid_data = true;
  if (slot->minimum_lost_pairs < minimum_lost_pairs) {
    slot->minimum_lost_pairs = minimum_lost_pairs;
  }
}

void PairCaptureRing::finalizeGeneration(GenerationSlot &slot,
                                         CompletionResult &result) {
  result.completion_mask = slot.completion_mask;
  result.pair_ready = false;
  result.pair_lost = slot.invalid_data ||
                     slot.destination == kOverflowDestination;
  saturatingIncrement(progress_.paired_major_loops);
  saturatingAdd(
      progress_.pairs_captured,
      static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame));

  if (slot.destination == kOverflowDestination) {
    saturatingIncrement(progress_.ring_overruns);
    saturatingAdd(
        progress_.pairs_lost,
        static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame));
  } else if (!isBufferDestination(slot.destination)) {
    noteInvariantError();
    saturatingIncrement(progress_.incomplete_buffers);
    saturatingAdd(
        progress_.pairs_lost,
        static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame));
    result.pair_lost = true;
  } else {
    BufferRecord &record = records_[slot.destination];
    const bool ownership_matches =
        record.state == BufferState::kDmaOwned &&
        record.epoch == epoch_ &&
        record.generation == slot.generation;
    if (!ownership_matches) {
      noteInvariantError();
      slot.invalid_data = true;
    }
    if (slot.invalid_data) {
      // Never steal a CPU lease or a differently scheduled DMA buffer when
      // an impossible ownership mismatch is detected. The samples are still
      // counted as lost and hardware can continue into its next descriptor.
      if (ownership_matches) {
        record.state = BufferState::kDiscardPending;
      }
      saturatingIncrement(progress_.incomplete_buffers);
      saturatingAdd(
          progress_.pairs_lost,
          static_cast<std::uint64_t>(protocol_v1::kAdcPairsPerFrame));
      result.pair_lost = true;
    } else if (ownership_matches) {
      record.state = BufferState::kReady;
      saturatingIncrement(progress_.buffers_completed);
      const std::size_t ready = countState(BufferState::kReady);
      if (ready > progress_.ready_high_water) {
        progress_.ready_high_water = ready;
      }
      result.pair_ready = true;
    }
  }
  slot = {};
}

std::size_t PairCaptureRing::countState(BufferState state) const {
  std::size_t count = 0U;
  for (const BufferRecord &record : records_) {
    if (record.state == state) {
      ++count;
    }
  }
  return count;
}

bool PairCaptureRing::allBuffersFree() const {
  for (const BufferRecord &record : records_) {
    if (record.state != BufferState::kFree) {
      return false;
    }
  }
  return true;
}

bool PairCaptureRing::handleMatches(const BufferHandle &handle,
                                    BufferState state) const {
  if (!handle.valid()) {
    return false;
  }
  const BufferRecord &record = records_[handle.buffer_index];
  return record.state == state && record.epoch == handle.epoch &&
         record.lease == handle.lease &&
         record.first_pair == handle.first_pair &&
         handle.pairs ==
             storage_.buffers[handle.buffer_index].pairs.data();
}

std::uint32_t PairCaptureRing::allocateLease() {
  std::uint32_t lease = next_lease_++;
  if (lease == 0U) {
    lease = next_lease_++;
  }
  if (next_lease_ == 0U) {
    next_lease_ = 1U;
  }
  return lease;
}

void PairCaptureRing::noteInvariantError() {
  saturatingIncrement(progress_.invariant_errors);
}

}  // namespace teensy_daq::adc_capture

#undef TEENSY_DAQ_ADC_DMA_COLD_CODE
