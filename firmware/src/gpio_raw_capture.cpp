#include "gpio_raw_capture.h"

#include <limits>

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_GPIO_RAW_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_GPIO_RAW_COLD_CODE(section_name)
#endif

namespace teensy_daq::gpio_capture {
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
  return destination < board::kGpioRawDmaRingDepth;
}

}  // namespace

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.diagnostic_acquire")
RawWordDiagnosticAcquireResult BoundedRawWordDiagnostic::acquire(
    std::uint32_t sample_limit) {
  RawWordDiagnosticAcquireResult result{};
  if (sample_limit == 0U || sample_limit > kRawWordDiagnosticMaxSamples) {
    result.status = OperationStatus::kInvalidDiagnosticLimit;
    return result;
  }

  const AcquireResult acquired = source_.acquireReady();
  result.status = acquired.status;
  if (!acquired.ok()) {
    return result;
  }
  if (!acquired.handle.valid()) {
    (void)source_.release(acquired.handle);
    result.status = OperationStatus::kInvalidHandle;
    return result;
  }

  result.lease.owner = acquired.handle;
  result.lease.words = acquired.handle.words;
  result.lease.sample_count =
      sample_limit < acquired.handle.sample_count
          ? sample_limit
          : acquired.handle.sample_count;
  result.status = OperationStatus::kOk;
  return result;
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.diagnostic_release")
OperationStatus BoundedRawWordDiagnostic::release(
    const RawWordDiagnosticLease &lease) {
  if (!lease.valid()) {
    return OperationStatus::kInvalidHandle;
  }
  return source_.release(lease.owner);
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.prime")
PrimeResult RawCaptureRing::prime() {
  PrimeResult result{};
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
  invariant_errors_ = 0U;
  next_free_search_ = 0U;
  active_first_sample_ = 0U;
  queued_first_sample_ = protocol_v1::kGpioSamplesPerFrame;
  next_first_sample_ =
      2U * static_cast<std::uint64_t>(protocol_v1::kGpioSamplesPerFrame);
  active_destination_ = takeFreeBuffer(BufferState::kDmaActive,
                                        active_first_sample_);
  queued_destination_ = takeFreeBuffer(BufferState::kDmaQueued,
                                        queued_first_sample_);
  if (!isBufferDestination(active_destination_) ||
      !isBufferDestination(queued_destination_)) {
    noteInvariantError();
    active_destination_ = kInvalidDestination;
    queued_destination_ = kInvalidDestination;
    critical_.exit(token);
    result.status = OperationStatus::kNotQuiescent;
    return result;
  }
  running_ = true;
  result.status = OperationStatus::kOk;
  result.active_destination = active_destination_;
  result.queued_destination = queued_destination_;
  critical_.exit(token);

  for (RawBuffer &buffer : storage_.buffers) {
    cache_.discardBeforeDmaWrite(buffer.words.data(), sizeof(buffer));
    saturatingIncrement(progress_.cache_dma_discards);
  }
  cache_.discardBeforeDmaWrite(overflow_sink_.words.data(),
                               sizeof(overflow_sink_));
  saturatingIncrement(progress_.cache_dma_discards);
  return result;
}

MajorLoopResult RawCaptureRing::onMajorLoopComplete() {
  MajorLoopResult result{};
  result.completed_destination = active_destination_;
  result.completed_first_sample = active_first_sample_;
  if (!running_) {
    result.status = OperationStatus::kNotRunning;
    return result;
  }

  if (isBufferDestination(active_destination_)) {
    BufferRecord &completed = records_[active_destination_];
    if (completed.state != BufferState::kDmaActive) {
      noteInvariantError();
      result.status = OperationStatus::kInvalidCompletion;
      return result;
    }
    completed.state = BufferState::kReady;
    saturatingIncrement(progress_.buffers_completed);
    const std::size_t ready = countState(BufferState::kReady);
    if (ready > progress_.ready_high_water) {
      progress_.ready_high_water = ready;
    }
  } else if (active_destination_ == kOverflowDestination) {
    saturatingIncrement(progress_.raw_ring_overruns);
    saturatingAdd(
        progress_.samples_lost,
        static_cast<std::uint64_t>(protocol_v1::kGpioSamplesPerFrame));
  } else {
    noteInvariantError();
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }

  saturatingIncrement(progress_.major_loops_completed);
  saturatingAdd(
      progress_.samples_captured,
      static_cast<std::uint64_t>(protocol_v1::kGpioSamplesPerFrame));

  active_destination_ = queued_destination_;
  active_first_sample_ = queued_first_sample_;
  if (isBufferDestination(active_destination_)) {
    BufferRecord &active = records_[active_destination_];
    if (active.state != BufferState::kDmaQueued) {
      noteInvariantError();
      result.status = OperationStatus::kInvalidCompletion;
      return result;
    }
    active.state = BufferState::kDmaActive;
  } else if (active_destination_ != kOverflowDestination) {
    noteInvariantError();
    result.status = OperationStatus::kInvalidCompletion;
    return result;
  }

  queued_first_sample_ = next_first_sample_;
  queued_destination_ = scheduleFutureDestination();
  saturatingAdd(
      next_first_sample_,
      static_cast<std::uint64_t>(protocol_v1::kGpioSamplesPerFrame));
  result.active_destination = active_destination_;
  result.queued_destination = queued_destination_;
  result.status = OperationStatus::kOk;
  return result;
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.acquire")
AcquireResult RawCaptureRing::acquireReady() {
  AcquireResult result{};
  const std::uint32_t token = critical_.enter();
  std::uint8_t selected = kInvalidDestination;
  std::uint64_t oldest = std::numeric_limits<std::uint64_t>::max();
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferRecord &record = records_[index];
    if (record.state == BufferState::kReady &&
        record.first_sample < oldest) {
      selected = static_cast<std::uint8_t>(index);
      oldest = record.first_sample;
    }
  }
  if (!isBufferDestination(selected)) {
    critical_.exit(token);
    result.status = OperationStatus::kNoReadyBuffer;
    return result;
  }

  BufferRecord &record = records_[selected];
  record.state = BufferState::kPacking;
  record.lease = allocateLease();
  result.handle.words = storage_.buffers[selected].words.data();
  result.handle.first_sample = record.first_sample;
  result.handle.sample_count = static_cast<std::uint32_t>(
      protocol_v1::kGpioSamplesPerFrame);
  result.handle.lease = record.lease;
  result.handle.buffer_index = selected;
  saturatingIncrement(progress_.buffers_acquired);
  saturatingAdd(
      progress_.samples_delivered,
      static_cast<std::uint64_t>(protocol_v1::kGpioSamplesPerFrame));
  critical_.exit(token);

  cache_.invalidateBeforeCpuRead(storage_.buffers[selected].words.data(),
                                 sizeof(RawBuffer));
  saturatingIncrement(progress_.cache_cpu_invalidations);
  result.status = OperationStatus::kOk;
  return result;
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.release")
OperationStatus RawCaptureRing::release(const BufferHandle &handle) {
  std::uint32_t token = critical_.enter();
  if (!handleMatches(handle, BufferState::kPacking)) {
    critical_.exit(token);
    return OperationStatus::kInvalidHandle;
  }
  records_[handle.buffer_index].state = BufferState::kReleasing;
  critical_.exit(token);

  cache_.discardBeforeDmaWrite(
      storage_.buffers[handle.buffer_index].words.data(), sizeof(RawBuffer));
  saturatingIncrement(progress_.cache_dma_discards);

  token = critical_.enter();
  if (!handleMatches(handle, BufferState::kReleasing)) {
    noteInvariantError();
    critical_.exit(token);
    return OperationStatus::kInvalidHandle;
  }
  BufferRecord &record = records_[handle.buffer_index];
  record.state = BufferState::kFree;
  record.lease = 0U;
  saturatingIncrement(progress_.buffers_released);
  critical_.exit(token);
  return OperationStatus::kOk;
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.stop")
StopReport RawCaptureRing::stop(std::uint32_t active_samples) {
  StopReport report{};
  if (active_samples > protocol_v1::kGpioSamplesPerFrame) {
    active_samples = static_cast<std::uint32_t>(
        protocol_v1::kGpioSamplesPerFrame);
    noteInvariantError();
  }

  std::uint8_t active_to_discard = kInvalidDestination;
  const std::uint32_t token = critical_.enter();
  if (!running_) {
    critical_.exit(token);
    return report;
  }

  if (active_samples != 0U) {
    saturatingAdd(progress_.samples_captured,
                  static_cast<std::uint64_t>(active_samples));
    saturatingAdd(progress_.samples_lost,
                  static_cast<std::uint64_t>(active_samples));
    report.active_samples_discarded = active_samples;
    if (active_destination_ == kOverflowDestination) {
      saturatingIncrement(progress_.raw_ring_overruns);
    } else {
      saturatingAdd(progress_.stop_discarded_samples,
                    static_cast<std::uint64_t>(active_samples));
    }
  }

  if (isBufferDestination(active_destination_)) {
    BufferRecord &active = records_[active_destination_];
    if (active.state != BufferState::kDmaActive) {
      noteInvariantError();
    }
    active.state = BufferState::kReleasing;
    active_to_discard = active_destination_;
  }
  if (isBufferDestination(queued_destination_)) {
    BufferRecord &queued = records_[queued_destination_];
    if (queued.state != BufferState::kDmaQueued) {
      noteInvariantError();
    }
    queued.state = BufferState::kFree;
  }
  running_ = false;
  active_destination_ = kInvalidDestination;
  queued_destination_ = kInvalidDestination;
  report.ready_buffers_to_drain = countState(BufferState::kReady);
  report.packing_buffers_to_release = countState(BufferState::kPacking);
  critical_.exit(token);

  if (isBufferDestination(active_to_discard)) {
    cache_.discardBeforeDmaWrite(
        storage_.buffers[active_to_discard].words.data(), sizeof(RawBuffer));
    saturatingIncrement(progress_.cache_dma_discards);
    const std::uint32_t release_token = critical_.enter();
    records_[active_to_discard].state = BufferState::kFree;
    records_[active_to_discard].lease = 0U;
    critical_.exit(release_token);
  } else {
    cache_.discardBeforeDmaWrite(overflow_sink_.words.data(),
                                 sizeof(overflow_sink_));
    saturatingIncrement(progress_.cache_dma_discards);
  }
  report.status = OperationStatus::kOk;
  return report;
}

void RawCaptureRing::recordHardwareError() {
  const std::uint32_t token = critical_.enter();
  saturatingIncrement(progress_.hardware_errors);
  critical_.exit(token);
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.snapshot")
Snapshot RawCaptureRing::snapshot() {
  Snapshot value{};
  const std::uint32_t token = critical_.enter();
  value.progress = progress_;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    value.buffer_states[index] = records_[index].state;
  }
  value.active_destination = active_destination_;
  value.queued_destination = queued_destination_;
  value.ready_depth = countState(BufferState::kReady);
  value.packing_depth = countState(BufferState::kPacking) +
                        countState(BufferState::kReleasing);
  value.invariant_errors = invariant_errors_;
  value.running = running_;
  value.quiescent = !running_ && allBuffersFree();
  critical_.exit(token);
  return value;
}

TEENSY_DAQ_GPIO_RAW_COLD_CODE(".flashmem.gpio_raw.quiescent")
bool RawCaptureRing::quiescent() {
  const std::uint32_t token = critical_.enter();
  const bool value = !running_ && allBuffersFree();
  critical_.exit(token);
  return value;
}

std::uint32_t *RawCaptureRing::destinationWords(std::uint8_t destination) {
  if (isBufferDestination(destination)) {
    return storage_.buffers[destination].words.data();
  }
  return destination == kOverflowDestination
             ? overflow_sink_.words.data()
             : nullptr;
}

const std::uint32_t *RawCaptureRing::destinationWords(
    std::uint8_t destination) const {
  if (isBufferDestination(destination)) {
    return storage_.buffers[destination].words.data();
  }
  return destination == kOverflowDestination
             ? overflow_sink_.words.data()
             : nullptr;
}

std::uint8_t RawCaptureRing::takeFreeBuffer(BufferState state,
                                            std::uint64_t first_sample) {
  for (std::size_t attempt = 0U; attempt < records_.size(); ++attempt) {
    const std::size_t candidate =
        (next_free_search_ + attempt) % records_.size();
    BufferRecord &record = records_[candidate];
    if (record.state != BufferState::kFree) {
      continue;
    }
    record.state = state;
    record.first_sample = first_sample;
    record.lease = 0U;
    next_free_search_ = (candidate + 1U) % records_.size();
    return static_cast<std::uint8_t>(candidate);
  }
  return kOverflowDestination;
}

std::uint8_t RawCaptureRing::scheduleFutureDestination() {
  return takeFreeBuffer(BufferState::kDmaQueued, queued_first_sample_);
}

std::size_t RawCaptureRing::countState(BufferState state) const {
  std::size_t count = 0U;
  for (const BufferRecord &record : records_) {
    if (record.state == state) {
      ++count;
    }
  }
  return count;
}

bool RawCaptureRing::allBuffersFree() const {
  for (const BufferRecord &record : records_) {
    if (record.state != BufferState::kFree) {
      return false;
    }
  }
  return true;
}

bool RawCaptureRing::handleMatches(const BufferHandle &handle,
                                   BufferState state) const {
  if (!handle.valid()) {
    return false;
  }
  const BufferRecord &record = records_[handle.buffer_index];
  return record.state == state && record.lease == handle.lease &&
         record.first_sample == handle.first_sample &&
         handle.words == storage_.buffers[handle.buffer_index].words.data();
}

std::uint32_t RawCaptureRing::allocateLease() {
  std::uint32_t lease = next_lease_++;
  if (lease == 0U) {
    lease = next_lease_++;
  }
  if (next_lease_ == 0U) {
    next_lease_ = 1U;
  }
  return lease;
}

void RawCaptureRing::noteInvariantError() {
  saturatingIncrement(invariant_errors_);
}

}  // namespace teensy_daq::gpio_capture

#undef TEENSY_DAQ_GPIO_RAW_COLD_CODE
