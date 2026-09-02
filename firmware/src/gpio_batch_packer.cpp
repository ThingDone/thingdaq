#include "gpio_batch_packer.h"

#include <cstring>
#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_GPIO_PACKER_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_GPIO_PACKER_COLD_CODE(section_name)
#endif

namespace thingdaq::gpio_packer {
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

template <typename Integer>
Integer subtractFloor(Integer value, Integer amount) {
  return amount >= value ? Integer{0U} : value - amount;
}

template <typename Integer>
Integer saturatingSum(Integer left, Integer right) {
  saturatingAdd(left, right);
  return left;
}

constexpr std::uint16_t flag(protocol_v1::FrameFlag value) {
  return static_cast<std::uint16_t>(value);
}

constexpr std::uint64_t kFrameSamples = protocol_v1::kGpioSamplesPerFrame;

}  // namespace

std::size_t packGpio2Batch(const std::uint32_t *source,
                           std::size_t sample_count,
                           std::uint8_t *destination,
                           std::size_t destination_capacity) {
  if ((sample_count != 0U && (source == nullptr || destination == nullptr)) ||
      sample_count > destination_capacity) {
    return 0U;
  }

  std::size_t index = 0U;
  for (; index + 4U <= sample_count; index += 4U) {
    destination[index] = packGpio2Word(source[index]);
    destination[index + 1U] = packGpio2Word(source[index + 1U]);
    destination[index + 2U] = packGpio2Word(source[index + 2U]);
    destination[index + 3U] = packGpio2Word(source[index + 3U]);
  }
  for (; index < sample_count; ++index) {
    destination[index] = packGpio2Word(source[index]);
  }
  return sample_count;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.start")
OperationStatus GpioBatchPacker::startRun(
    std::uint32_t run_id,
    protocol_v1::ChecksumAlgorithm checksum_algorithm,
    const packet::PacketBufferPipeline &pipeline,
    std::uint64_t start_epoch_ticks) {
  if (run_id == 0U || run_id == run_id_) {
    return OperationStatus::kInvalidRunId;
  }
  if (!quiescent()) {
    return OperationStatus::kNotQuiescent;
  }
  if (!pipeline.accepts(packet::Stream::kGpio, run_id,
                        checksum_algorithm) ||
      !protocol::isSupportedChecksum(checksum_algorithm)) {
    return OperationStatus::kPipelineNotReady;
  }
  const stream_layout::RunLayout &selected_layout = pipeline.layout();
  const stream_layout::FrameLayout &gpio_layout =
      selected_layout.forStream(stream_layout::Stream::kGpio);
  if (!selected_layout.valid() ||
      selected_layout.aux_bank_mode !=
          protocol_v2::AuxBankMode::kDisabled ||
      gpio_layout.item_count != kFrameSamples ||
      gpio_layout.item_bytes != kPackedWireBytesPerSample ||
      gpio_layout.payload_bytes != storage_.buffers[0].bytes.size()) {
    return OperationStatus::kPipelineNotReady;
  }

  records_ = {};
  ready_queue_.clear();
  progress_ = {};
  pending_dropped_frames_ = 0U;
  pending_raw_drop_samples_ = 0U;
  pending_packer_drop_samples_ = 0U;
  prepacket_frames_dropped_ = 0U;
  prepacket_frames_projected_ = 0U;
  next_source_sample_ = 0U;
  start_epoch_ticks_ = start_epoch_ticks;
  service_calls_ = 0U;
  raw_buffers_acquired_ = 0U;
  raw_buffers_released_ = 0U;
  duplicate_samples_ignored_ = 0U;
  processing_elapsed_cycles_ = 0U;
  processing_active_cycles_ = 0U;
  current_raw_drop_samples_ = 0U;
  current_packer_drop_samples_ = 0U;
  current_frame_samples_ = 0U;
  source_errors_ = 0U;
  pipeline_errors_ = 0U;
  chronology_errors_ = 0U;
  next_free_search_ = 0U;
  ready_high_water_ = 0U;
  filling_buffer_ = kInvalidBuffer;
  run_id_ = run_id;
  checksum_algorithm_ = checksum_algorithm;
  layout_ = selected_layout;
  current_frame_invalid_ = false;
  input_gap_pending_ = false;
  packet_gap_pending_ = false;
  processing_profile_active_ =
      cycle_counter_ != nullptr && cycle_counter_->begin();
  if (processing_profile_active_) {
    profile_last_cycle_ = cycle_counter_->read();
  }
  running_ = true;
  return OperationStatus::kOk;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.stop")
StopReport GpioBatchPacker::stopProduction() {
  StopReport report{};
  running_ = false;
  if (current_frame_samples_ != 0U) {
    invalidateCurrentFrame();
    report.partial_samples_discarded = current_frame_samples_;
    // A stopped partial frame has no later frame in this run and therefore no
    // complete sequence slot. Its exact produced samples remain visible in the
    // packer counters without inflating loss to a whole wire frame.
    resetCurrentFrame();
  }
  report.packed_frames_to_drain = ready_queue_.size();
  report.dropped_frames_to_publish = pending_dropped_frames_;
  return report;
}

ServiceReport GpioBatchPacker::service(
    packet::PacketBufferPipeline &pipeline, std::size_t raw_buffer_limit,
    std::size_t frame_limit) {
  const std::uint32_t profile_started_at = beginProfile();
  ServiceReport report{};
  saturatingIncrement(service_calls_);
  if (!pipelineMatches(pipeline)) {
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
    finishProfile(profile_started_at);
    return report;
  }

  while (report.frames_framed < frame_limit && !ready_queue_.empty()) {
    if (!packetizeOne(pipeline, report)) {
      break;
    }
  }

  if (running_) {
    while (report.raw_buffers_consumed < raw_buffer_limit) {
      const gpio_capture::AcquireResult acquired = source_.acquireReady();
      if (acquired.status == gpio_capture::OperationStatus::kNoReadyBuffer) {
        report.waiting_for_raw_buffer = true;
        break;
      }
      if (!acquired.ok() || !acquired.handle.valid()) {
        saturatingIncrement(source_errors_);
        report.source_error = true;
        break;
      }

      saturatingIncrement(raw_buffers_acquired_);
      const bool consumed = consume(acquired.handle, report);
      const gpio_capture::OperationStatus released =
          source_.release(acquired.handle);
      if (released != gpio_capture::OperationStatus::kOk) {
        saturatingIncrement(source_errors_);
        report.source_error = true;
      } else {
        saturatingIncrement(raw_buffers_released_);
      }
      ++report.raw_buffers_consumed;
      if (!consumed || report.source_error) {
        break;
      }

      while (report.frames_framed < frame_limit && !ready_queue_.empty()) {
        if (!packetizeOne(pipeline, report)) {
          break;
        }
      }
    }
    report.raw_work_limit_reached =
        raw_buffer_limit != 0U &&
        report.raw_buffers_consumed == raw_buffer_limit;
  }

  while (report.frames_framed < frame_limit && !ready_queue_.empty()) {
    if (!packetizeOne(pipeline, report)) {
      break;
    }
  }
  report.frame_work_limit_reached =
      frame_limit != 0U && report.frames_framed == frame_limit &&
      !ready_queue_.empty();

  if (!running_ && ready_queue_.empty() && pending_dropped_frames_ != 0U &&
      !flushTrailingDrops(pipeline)) {
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
  }
  finishProfile(profile_started_at);
  return report;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.snapshot")
Snapshot GpioBatchPacker::snapshot(
    const packet::PacketBufferPipeline &pipeline) const {
  Snapshot result{};
  result.progress = progress(pipeline);
  result.progress.duplicate_samples_ignored = duplicate_samples_ignored_;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    result.buffer_states[index] = records_[index].state;
  }
  result.run_id = run_id_;
  result.checksum_algorithm = checksum_algorithm_;
  result.layout = layout_;
  result.next_source_sample = next_source_sample_;
  result.start_epoch_ticks = start_epoch_ticks_;
  result.pending_dropped_frames = pending_dropped_frames_;
  result.current_frame_samples = current_frame_samples_;
  result.ready_depth = ready_queue_.size();
  result.ready_high_water = ready_high_water_;
  result.service_calls = service_calls_;
  result.raw_buffers_acquired = raw_buffers_acquired_;
  result.raw_buffers_released = raw_buffers_released_;
  result.duplicate_samples_ignored = duplicate_samples_ignored_;
  result.processing_elapsed_cycles = processing_elapsed_cycles_;
  result.processing_active_cycles = processing_active_cycles_;
  result.processing_cpu_basis_points = processingCpuBasisPoints();
  result.source_errors = source_errors_;
  result.pipeline_errors = pipeline_errors_;
  result.chronology_errors = chronology_errors_;
  result.running = running_;
  result.input_gap_pending = input_gap_pending_;
  result.packet_gap_pending = packet_gap_pending_;
  result.quiescent = quiescent();
  return result;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.quiescent")
bool GpioBatchPacker::quiescent() const {
  return !running_ && filling_buffer_ == kInvalidBuffer &&
         ready_queue_.empty() && countState(BufferState::kFilling) == 0U &&
         countState(BufferState::kReady) == 0U &&
         countState(BufferState::kFraming) == 0U &&
         pending_dropped_frames_ == 0U;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.ready")
bool GpioBatchPacker::readyForStart() const { return quiescent(); }

std::uint32_t GpioBatchPacker::beginProfile() {
  if (!processing_profile_active_) {
    return 0U;
  }
  const std::uint32_t started_at = cycle_counter_->read();
  saturatingAdd(
      processing_elapsed_cycles_,
      static_cast<std::uint64_t>(started_at - profile_last_cycle_));
  profile_last_cycle_ = started_at;
  return started_at;
}

void GpioBatchPacker::finishProfile(std::uint32_t started_at) {
  if (!processing_profile_active_) {
    return;
  }
  const std::uint32_t finished_at = cycle_counter_->read();
  const std::uint64_t active =
      static_cast<std::uint64_t>(finished_at - started_at);
  saturatingAdd(processing_active_cycles_, active);
  saturatingAdd(processing_elapsed_cycles_, active);
  profile_last_cycle_ = finished_at;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.profile")
std::uint16_t GpioBatchPacker::processingCpuBasisPoints() const {
  if (!processing_profile_active_ || processing_elapsed_cycles_ == 0U) {
    return 0U;
  }
  if (processing_active_cycles_ >= processing_elapsed_cycles_) {
    return kCpuBasisPointsFullScale;
  }
  constexpr std::uint64_t scale = kCpuBasisPointsFullScale;
  std::uint64_t scaled = 0U;
  if (processing_active_cycles_ <=
      std::numeric_limits<std::uint64_t>::max() / scale) {
    scaled = (processing_active_cycles_ * scale +
              processing_elapsed_cycles_ / 2U) /
             processing_elapsed_cycles_;
  } else {
    const std::uint64_t divisor =
        processing_elapsed_cycles_ / scale + 1U;
    scaled = processing_active_cycles_ / divisor;
  }
  return static_cast<std::uint16_t>(
      scaled > scale ? scale : scaled);
}

bool GpioBatchPacker::pipelineMatches(
    const packet::PacketBufferPipeline &pipeline) const {
  return pipeline.accepts(packet::Stream::kGpio, run_id_,
                          checksum_algorithm_);
}

bool GpioBatchPacker::consume(const gpio_capture::BufferHandle &handle,
                              ServiceReport &report) {
  if (!handle.valid() ||
      handle.first_sample >
          std::numeric_limits<std::uint64_t>::max() - handle.sample_count) {
    saturatingIncrement(source_errors_);
    report.source_error = true;
    return false;
  }

  std::size_t source_offset = 0U;
  std::uint64_t first_sample = handle.first_sample;
  std::size_t remaining = handle.sample_count;
  if (first_sample < next_source_sample_) {
    saturatingIncrement(chronology_errors_);
    const std::uint64_t overlap = next_source_sample_ - first_sample;
    if (overlap >= remaining) {
      saturatingAdd(duplicate_samples_ignored_,
                    static_cast<std::uint64_t>(remaining));
      return true;
    }
    source_offset = static_cast<std::size_t>(overlap);
    remaining -= source_offset;
    first_sample = next_source_sample_;
    saturatingAdd(duplicate_samples_ignored_, overlap);
  }
  if (first_sample > next_source_sample_) {
    accountRawGap(first_sample - next_source_sample_, report);
  }
  consumeAvailable(handle.words + source_offset, remaining, report);
  report.samples_consumed += remaining;
  return true;
}

// Raw-gap recovery is an exceptional path. Keep it in program Flash so the
// dual-ADC completion ISRs retain deterministic ITCM residency without
// crossing the linker allocator's next 32 KiB RAM1 code block.
THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.raw_gap")
void GpioBatchPacker::accountRawGap(std::uint64_t sample_count,
                                    ServiceReport &report) {
  if (sample_count == 0U) {
    return;
  }
  saturatingAdd(progress_.raw_gap_samples, sample_count);
  saturatingAdd(progress_.samples_produced, sample_count);
  input_gap_pending_ = true;

  while (sample_count != 0U) {
    if (current_frame_samples_ == 0U && sample_count >= kFrameSamples) {
      const std::uint64_t full_frames = sample_count / kFrameSamples;
      const std::uint64_t full_samples = full_frames * kFrameSamples;
      saturatingAdd(progress_.frames_produced, full_frames);
      saturatingAdd(prepacket_frames_dropped_, full_frames);
      saturatingAdd(pending_dropped_frames_, full_frames);
      saturatingAdd(pending_raw_drop_samples_, full_samples);
      saturatingAdd(next_source_sample_, full_samples);
      sample_count -= full_samples;
      report.frames_dropped += static_cast<std::size_t>(
          full_frames > std::numeric_limits<std::size_t>::max()
              ? std::numeric_limits<std::size_t>::max()
              : full_frames);
      continue;
    }

    invalidateCurrentFrame();
    const std::uint64_t remaining_in_frame =
        kFrameSamples - current_frame_samples_;
    const std::uint64_t chunk =
        sample_count < remaining_in_frame ? sample_count : remaining_in_frame;
    saturatingAdd(current_raw_drop_samples_, chunk);
    current_frame_samples_ += static_cast<std::uint32_t>(chunk);
    saturatingAdd(next_source_sample_, chunk);
    sample_count -= chunk;
    if (current_frame_samples_ == kFrameSamples) {
      finishInvalidFrame(report);
    }
  }
}

void GpioBatchPacker::consumeAvailable(const std::uint32_t *source,
                                       std::size_t sample_count,
                                       ServiceReport &report) {
  std::size_t offset = 0U;
  while (offset < sample_count) {
    const std::size_t remaining_in_frame =
        static_cast<std::size_t>(kFrameSamples - current_frame_samples_);
    const std::size_t remaining = sample_count - offset;
    const std::size_t chunk =
        remaining < remaining_in_frame ? remaining : remaining_in_frame;
    saturatingAdd(progress_.samples_produced,
                  static_cast<std::uint64_t>(chunk));

    if (!current_frame_invalid_ && !ensureFillingBuffer()) {
      invalidateCurrentFrame();
    }
    if (current_frame_invalid_) {
      saturatingAdd(progress_.packer_drop_samples,
                    static_cast<std::uint64_t>(chunk));
      saturatingAdd(current_packer_drop_samples_,
                    static_cast<std::uint64_t>(chunk));
    } else {
      PackedBuffer &destination = storage_.buffers[filling_buffer_];
      const std::size_t written = packGpio2Batch(
          source + offset, chunk,
          destination.bytes.data() + current_frame_samples_,
          destination.bytes.size() - current_frame_samples_);
      if (written != chunk) {
        saturatingIncrement(source_errors_);
        report.source_error = true;
        invalidateCurrentFrame();
        saturatingAdd(progress_.packer_drop_samples,
                      static_cast<std::uint64_t>(chunk));
        saturatingAdd(current_packer_drop_samples_,
                      static_cast<std::uint64_t>(chunk));
      } else {
        saturatingAdd(progress_.samples_packed,
                      static_cast<std::uint64_t>(written));
      }
    }

    offset += chunk;
    current_frame_samples_ += static_cast<std::uint32_t>(chunk);
    saturatingAdd(next_source_sample_, static_cast<std::uint64_t>(chunk));
    if (current_frame_samples_ == kFrameSamples) {
      if (current_frame_invalid_) {
        finishInvalidFrame(report);
      } else {
        finishPackedFrame(report);
      }
    }
  }
}

bool GpioBatchPacker::ensureFillingBuffer() {
  if (filling_buffer_ != kInvalidBuffer) {
    return filling_buffer_ < records_.size() &&
           records_[filling_buffer_].state == BufferState::kFilling;
  }
  filling_buffer_ = takeFreeBuffer();
  if (filling_buffer_ == kInvalidBuffer) {
    return false;
  }
  records_[filling_buffer_].state = BufferState::kFilling;
  return true;
}

void GpioBatchPacker::invalidateCurrentFrame() {
  input_gap_pending_ = true;
  if (current_frame_invalid_) {
    return;
  }
  current_frame_invalid_ = true;
  if (filling_buffer_ != kInvalidBuffer) {
    // Bytes already packed into an incomplete frame cannot cross a source gap.
    saturatingAdd(progress_.packer_drop_samples,
                  static_cast<std::uint64_t>(current_frame_samples_));
    saturatingAdd(current_packer_drop_samples_,
                  static_cast<std::uint64_t>(current_frame_samples_));
    recycle(filling_buffer_);
    filling_buffer_ = kInvalidBuffer;
  }
}

void GpioBatchPacker::finishInvalidFrame(ServiceReport &report) {
  saturatingIncrement(progress_.frames_produced);
  saturatingIncrement(prepacket_frames_dropped_);
  saturatingIncrement(pending_dropped_frames_);
  saturatingAdd(pending_raw_drop_samples_, current_raw_drop_samples_);
  saturatingAdd(pending_packer_drop_samples_, current_packer_drop_samples_);
  ++report.frames_dropped;
  resetCurrentFrame();
}

void GpioBatchPacker::finishPackedFrame(ServiceReport &report) {
  if (filling_buffer_ == kInvalidBuffer ||
      filling_buffer_ >= records_.size()) {
    saturatingIncrement(source_errors_);
    report.source_error = true;
    invalidateCurrentFrame();
    finishInvalidFrame(report);
    return;
  }

  BufferRecord &record = records_[filling_buffer_];
  record.state = BufferState::kReady;
  record.first_sample = next_source_sample_ - kFrameSamples;
  record.dropped_frames_before = pending_dropped_frames_;
  record.raw_drop_samples_before = pending_raw_drop_samples_;
  record.packer_drop_samples_before = pending_packer_drop_samples_;
  record.gap_before = input_gap_pending_ || pending_dropped_frames_ != 0U;
  if (!ready_queue_.push(filling_buffer_)) {
    // Queue depth equals storage depth, so this is an invariant failure rather
    // than normal pressure. Preserve chronology and loss accounting anyway.
    saturatingIncrement(source_errors_);
    report.source_error = true;
    recycle(filling_buffer_);
    saturatingAdd(progress_.packer_drop_samples, kFrameSamples);
    saturatingIncrement(progress_.frames_produced);
    saturatingIncrement(prepacket_frames_dropped_);
    saturatingIncrement(pending_dropped_frames_);
    saturatingAdd(pending_packer_drop_samples_, kFrameSamples);
    ++report.frames_dropped;
  } else {
    pending_dropped_frames_ = 0U;
    pending_raw_drop_samples_ = 0U;
    pending_packer_drop_samples_ = 0U;
    input_gap_pending_ = false;
    saturatingIncrement(progress_.frames_produced);
    saturatingIncrement(progress_.frames_packed);
    ++report.frames_packed;
    if (ready_queue_.size() > ready_high_water_) {
      ready_high_water_ = ready_queue_.size();
    }
  }
  filling_buffer_ = kInvalidBuffer;
  resetCurrentFrame();
}

void GpioBatchPacker::resetCurrentFrame() {
  current_frame_samples_ = 0U;
  current_raw_drop_samples_ = 0U;
  current_packer_drop_samples_ = 0U;
  current_frame_invalid_ = false;
  filling_buffer_ = kInvalidBuffer;
}

bool GpioBatchPacker::packetizeOne(
    packet::PacketBufferPipeline &pipeline, ServiceReport &report) {
  const std::uint8_t *front = ready_queue_.front();
  if (front == nullptr || *front >= records_.size()) {
    return false;
  }

  const std::uint8_t index = *front;
  BufferRecord &record = records_[index];
  if (record.state != BufferState::kReady) {
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
    return false;
  }
  if (!applyDroppedFrames(pipeline, record.dropped_frames_before,
                          record.raw_drop_samples_before,
                          record.packer_drop_samples_before)) {
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
    return false;
  }
  record.dropped_frames_before = 0U;
  record.raw_drop_samples_before = 0U;
  record.packer_drop_samples_before = 0U;
  record.state = BufferState::kFraming;

  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  const bool expected_pressure_drop =
      begun.status == packet::OperationStatus::kPoolExhausted;
  bool framed = begun.ok();
  if (framed) {
    protocol::MutableByteView payload = pipeline.writablePayload(begun.handle);
    const stream_layout::FrameLayout &gpio_layout =
        layout_.forStream(stream_layout::Stream::kGpio);
    const bool timestamp_valid =
        record.first_sample <=
        std::numeric_limits<std::uint64_t>::max() /
            gpio_layout.item_period_ticks;
    framed = payload.valid() && payload.size == gpio_layout.payload_bytes &&
             timestamp_valid;
    if (framed) {
      std::memcpy(payload.data, storage_.buffers[index].bytes.data(),
                  payload.size);
      packet::FrameCompletion completion{};
      completion.first_sample_ticks =
          record.first_sample * gpio_layout.item_period_ticks;
      if (begun.handle.sequence == 0U && record.first_sample == 0U) {
        completion.flags = flag(protocol_v1::FrameFlag::kEpochStart);
      }
      if (record.gap_before || packet_gap_pending_) {
        completion.flags = static_cast<std::uint16_t>(
            completion.flags | flag(protocol_v1::FrameFlag::kGapBefore) |
            flag(protocol_v1::FrameFlag::kOverrunBefore));
      }
      completion.checksum_algorithm = checksum_algorithm_;
      completion.payload_bytes_written = payload.size;
      framed = pipeline.finishFill(begun.handle, completion).ok();
    } else {
      (void)pipeline.cancelFill(begun.handle);
      if (!timestamp_valid) {
        saturatingIncrement(chronology_errors_);
        saturatingIncrement(source_errors_);
        report.source_error = true;
      }
    }
  }

  std::uint8_t popped = kInvalidBuffer;
  if (!ready_queue_.pop(popped) || popped != index) {
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
  }
  recycle(index);
  if (framed) {
    packet_gap_pending_ = false;
    ++report.frames_framed;
  } else {
    packet_gap_pending_ = true;
    if (!expected_pressure_drop) {
      saturatingIncrement(pipeline_errors_);
      report.pipeline_error = true;
    }
    ++report.frames_dropped;
  }
  return true;
}

bool GpioBatchPacker::applyDroppedFrames(
    packet::PacketBufferPipeline &pipeline, std::uint64_t frames,
    std::uint64_t raw_samples, std::uint64_t packer_samples) {
  if (frames == 0U) {
    return raw_samples == 0U && packer_samples == 0U;
  }
  if (pipeline.recordSourceFrameDrops(packet::Stream::kGpio, frames) !=
      packet::OperationStatus::kOk) {
    return false;
  }
  saturatingAdd(prepacket_frames_projected_, frames);
  saturatingAdd(progress_.raw_drop_samples_projected, raw_samples);
  saturatingAdd(progress_.packer_drop_samples_projected, packer_samples);
  return true;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.trailing_drops")
bool GpioBatchPacker::flushTrailingDrops(
    packet::PacketBufferPipeline &pipeline) {
  if (!applyDroppedFrames(pipeline, pending_dropped_frames_,
                          pending_raw_drop_samples_,
                          pending_packer_drop_samples_)) {
    return false;
  }
  pending_dropped_frames_ = 0U;
  pending_raw_drop_samples_ = 0U;
  pending_packer_drop_samples_ = 0U;
  input_gap_pending_ = false;
  return true;
}

std::uint8_t GpioBatchPacker::takeFreeBuffer() {
  for (std::size_t attempt = 0U; attempt < records_.size(); ++attempt) {
    const std::size_t index =
        (next_free_search_ + attempt) % records_.size();
    if (records_[index].state == BufferState::kFree) {
      records_[index] = {};
      next_free_search_ = (index + 1U) % records_.size();
      return static_cast<std::uint8_t>(index);
    }
  }
  return kInvalidBuffer;
}

void GpioBatchPacker::recycle(std::uint8_t index) {
  if (index >= records_.size()) {
    saturatingIncrement(source_errors_);
    return;
  }
  records_[index] = {};
}

std::size_t GpioBatchPacker::countState(BufferState state) const {
  std::size_t count = 0U;
  for (const BufferRecord &record : records_) {
    if (record.state == state) {
      ++count;
    }
  }
  return count;
}

THINGDAQ_GPIO_PACKER_COLD_CODE(".flashmem.gpio_packer.progress")
stats::GpioPackerProgress GpioBatchPacker::progress(
    const packet::PacketBufferPipeline &pipeline) const {
  stats::GpioPackerProgress result = progress_;
  const packet::SourceCounters gpio =
      pipeline.sourceCounters(packet::Stream::kGpio);
  result.frames_framed = gpio.frames_framed;
  result.samples_framed = gpio.items_framed;
  result.frames_transmitted = gpio.frames_transmitted;
  result.samples_transmitted = gpio.items_transmitted;
  const std::uint64_t unprojected_frames = subtractFloor(
      prepacket_frames_dropped_, prepacket_frames_projected_);
  result.frames_dropped =
      saturatingSum(gpio.frames_dropped, unprojected_frames);
  const std::uint64_t unprojected_raw = subtractFloor(
      result.raw_gap_samples, result.raw_drop_samples_projected);
  const std::uint64_t unprojected_packer = subtractFloor(
      result.packer_drop_samples, result.packer_drop_samples_projected);
  result.samples_dropped = saturatingSum(
      saturatingSum(gpio.items_dropped, unprojected_raw),
      unprojected_packer);
  result.ready_depth = ready_queue_.size();
  result.ready_high_water = ready_high_water_;
  result.processing_cpu_basis_points = processingCpuBasisPoints();
  result.source_errors = source_errors_;
  result.pipeline_errors = pipeline_errors_;
  result.chronology_errors = chronology_errors_;
  return result;
}

}  // namespace thingdaq::gpio_packer

#undef THINGDAQ_GPIO_PACKER_COLD_CODE
