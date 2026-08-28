#include "packet_buffer_pipeline.h"

#include <limits>

namespace teensy_daq::packet {
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

}  // namespace

OperationStatus PacketBufferPipeline::startRun(std::uint32_t run_id) {
  if (run_id == 0U || run_id == run_id_) {
    saturatingIncrement(run_start_rejections_);
    return OperationStatus::kInvalidRunId;
  }
  if (!quiescent()) {
    saturatingIncrement(run_start_rejections_);
    return OperationStatus::kTransmissionPending;
  }
  if (accepting_frames_) {
    saturatingIncrement(run_start_rejections_);
    return OperationStatus::kRunActive;
  }

  for (ReadyQueue &queue : ready_queues_) {
    queue.clear();
  }
  for (BufferRecord &record : records_) {
    record = {};
  }
  transmit_queue_.clear();
  source_counters_ = {};
  transmit_depth_by_source_ = {};
  run_id_ = run_id;
  next_free_search_ = 0U;
  next_ready_source_ = 0U;
  ready_queue_high_water_ = 0U;
  transmit_queue_high_water_ = 0U;
  buffers_owned_high_water_ = 0U;
  pool_exhaustions_ = 0U;
  invalid_operations_ = 0U;
  encoding_rejections_ = 0U;
  ready_queue_rejections_ = 0U;
  transmit_queue_rejections_ = 0U;
  frames_promoted_ = 0U;
  accepting_frames_ = true;
  saturatingIncrement(run_starts_);
  return OperationStatus::kOk;
}

StopReport PacketBufferPipeline::stopProduction() {
  StopReport report{};
  accepting_frames_ = false;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferRecord &record = records_[index];
    if (record.state != BufferState::kFilling) {
      continue;
    }
    recordDrop(record.stream, record.item_count);
    recycle(static_cast<BufferIndex>(index));
    ++report.filling_frames_canceled;
  }
  report.ready_frames_to_drain = readyFrames();
  report.transmitting_frames_to_drain = transmit_queue_.size();
  return report;
}

BeginFillResult PacketBufferPipeline::beginFill(Stream stream) {
  BeginFillResult result{};
  result.handle.stream = stream;
  if (!accepting_frames_ || run_id_ == 0U || !validStream(stream)) {
    saturatingIncrement(invalid_operations_);
    result.status = OperationStatus::kNotRunning;
    return result;
  }

  SourceCounters &source = source_counters_[streamIndex(stream)];
  result.handle.sequence = source.next_sequence;
  ++source.next_sequence;  // Protocol sequence arithmetic wraps modulo 2^32.
  saturatingIncrement(source.frames_produced);
  saturatingAdd(source.items_produced,
                static_cast<std::uint64_t>(itemsPerFrame(stream)));

  const BufferIndex buffer_index = takeFreeBuffer();
  if (buffer_index == kInvalidBufferIndex) {
    saturatingIncrement(pool_exhaustions_);
    recordDrop(stream, itemsPerFrame(stream));
    result.status = OperationStatus::kPoolExhausted;
    return result;
  }

  std::uint32_t lease = next_lease_++;
  if (lease == 0U) {
    lease = next_lease_++;
  }
  if (next_lease_ == 0U) {
    next_lease_ = 1U;
  }

  BufferRecord &record = records_[buffer_index];
  record.state = BufferState::kFilling;
  record.stream = stream;
  record.run_id = run_id_;
  record.sequence = result.handle.sequence;
  record.item_count = itemsPerFrame(stream);
  record.lease = lease;
  record.frame_size = 0U;
  result.handle.buffer_index = buffer_index;
  result.handle.lease = lease;
  result.status = OperationStatus::kOk;
  updateOwnedHighWater();
  return result;
}

protocol::MutableByteView PacketBufferPipeline::writablePayload(
    const FillHandle &handle) {
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    return {};
  }
  return {storage_.frames[handle.buffer_index].data() +
              protocol_v1::kHeaderSize,
          protocol_v1::kDataPayloadBytes};
}

FinishFillResult PacketBufferPipeline::finishFill(
    const FillHandle &handle, const FrameCompletion &completion) {
  FinishFillResult result{};
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    result.status = OperationStatus::kInvalidHandle;
    return result;
  }

  BufferRecord &record = records_[handle.buffer_index];
  if (!accepting_frames_ || record.run_id != run_id_) {
    recordDrop(record.stream, record.item_count);
    recycle(handle.buffer_index);
    result.status = OperationStatus::kNotRunning;
    return result;
  }
  if (completion.payload_bytes_written != protocol_v1::kDataPayloadBytes) {
    recordDrop(record.stream, record.item_count);
    recycle(handle.buffer_index);
    result.status = OperationStatus::kIncompletePayload;
    return result;
  }

  protocol::FrameFields fields{};
  fields.kind = frameKind(record.stream);
  fields.flags = completion.flags;
  fields.checksum_algorithm = completion.checksum_algorithm;
  fields.run_id = record.run_id;
  fields.sequence = record.sequence;
  fields.first_sample_ticks = completion.first_sample_ticks;
  fields.item_count = record.item_count;
  result.encoding = protocol::encodeDataFrameInPlace(
      fields,
      {storage_.frames[handle.buffer_index].data(),
       storage_.frames[handle.buffer_index].size()},
      completion.payload_bytes_written);
  if (!result.encoding.ok()) {
    saturatingIncrement(encoding_rejections_);
    recordDrop(record.stream, record.item_count);
    recycle(handle.buffer_index);
    result.status = OperationStatus::kEncodingRejected;
    return result;
  }

  ReadyQueue &ready = ready_queues_[streamIndex(record.stream)];
  if (!ready.push(handle.buffer_index)) {
    saturatingIncrement(ready_queue_rejections_);
    recordDrop(record.stream, record.item_count);
    recycle(handle.buffer_index);
    result.status = OperationStatus::kQueueFull;
    return result;
  }

  record.state = BufferState::kReady;
  record.frame_size = protocol_v1::kDataFrameBytes;
  SourceCounters &source = source_counters_[streamIndex(record.stream)];
  saturatingIncrement(source.frames_framed);
  saturatingAdd(source.items_framed,
                static_cast<std::uint64_t>(record.item_count));
  if (ready.size() > source.ready_queue_high_water) {
    source.ready_queue_high_water = ready.size();
  }
  const std::size_t total_ready = readyFrames();
  if (total_ready > ready_queue_high_water_) {
    ready_queue_high_water_ = total_ready;
  }
  result.status = OperationStatus::kOk;
  return result;
}

bool PacketBufferPipeline::cancelFill(const FillHandle &handle) {
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    return false;
  }
  const BufferRecord record = records_[handle.buffer_index];
  recordDrop(record.stream, record.item_count);
  recycle(handle.buffer_index);
  return true;
}

PromotionReport PacketBufferPipeline::serviceReadyFrames(std::size_t limit) {
  PromotionReport report{};
  while (report.frames_promoted < limit) {
    if (transmit_queue_.full()) {
      report.transmit_queue_full = true;
      break;
    }

    std::size_t selected_source = kStreamCount;
    for (std::size_t attempt = 0U; attempt < kStreamCount; ++attempt) {
      const std::size_t candidate =
          (next_ready_source_ + attempt) % kStreamCount;
      if (!ready_queues_[candidate].empty()) {
        selected_source = candidate;
        break;
      }
    }
    if (selected_source == kStreamCount) {
      break;
    }

    BufferIndex buffer_index = kInvalidBufferIndex;
    if (!ready_queues_[selected_source].pop(buffer_index) ||
        buffer_index >= records_.size()) {
      saturatingIncrement(invalid_operations_);
      report.invariant_error = true;
      continue;
    }
    BufferRecord &record = records_[buffer_index];
    if (record.state != BufferState::kReady ||
        streamIndex(record.stream) != selected_source ||
        record.frame_size != protocol_v1::kDataFrameBytes) {
      saturatingIncrement(invalid_operations_);
      recordDrop(record.stream, record.item_count);
      recycle(buffer_index);
      report.invariant_error = true;
      continue;
    }
    if (!transmit_queue_.push(buffer_index)) {
      saturatingIncrement(transmit_queue_rejections_);
      recordDrop(record.stream, record.item_count);
      recycle(buffer_index);
      report.transmit_queue_full = true;
      break;
    }

    record.state = BufferState::kTransmitting;
    ++transmit_depth_by_source_[selected_source];
    SourceCounters &source = source_counters_[selected_source];
    saturatingIncrement(source.frames_emitted);
    saturatingAdd(source.items_emitted,
                  static_cast<std::uint64_t>(record.item_count));
    if (transmit_depth_by_source_[selected_source] >
        source.transmit_queue_high_water) {
      source.transmit_queue_high_water =
          transmit_depth_by_source_[selected_source];
    }
    if (transmit_queue_.size() > transmit_queue_high_water_) {
      transmit_queue_high_water_ = transmit_queue_.size();
    }
    next_ready_source_ = (selected_source + 1U) % kStreamCount;
    saturatingIncrement(frames_promoted_);
    ++report.frames_promoted;
  }
  return report;
}

protocol::ByteView PacketBufferPipeline::frontFrame() const {
  const BufferIndex *buffer_index = transmit_queue_.front();
  if (buffer_index == nullptr || *buffer_index >= records_.size()) {
    return {};
  }
  const BufferRecord &record = records_[*buffer_index];
  if (record.state != BufferState::kTransmitting ||
      record.frame_size != protocol_v1::kDataFrameBytes) {
    return {};
  }
  return {storage_.frames[*buffer_index].data(), record.frame_size};
}

void PacketBufferPipeline::releaseFrontFrame() {
  BufferIndex buffer_index = kInvalidBufferIndex;
  if (!transmit_queue_.pop(buffer_index) ||
      buffer_index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return;
  }

  BufferRecord &record = records_[buffer_index];
  if (record.state != BufferState::kTransmitting ||
      !validStream(record.stream)) {
    saturatingIncrement(invalid_operations_);
    recycle(buffer_index);
    return;
  }
  const std::size_t source_index = streamIndex(record.stream);
  SourceCounters &source = source_counters_[source_index];
  saturatingIncrement(source.frames_transmitted);
  saturatingAdd(source.items_transmitted,
                static_cast<std::uint64_t>(record.item_count));
  if (transmit_depth_by_source_[source_index] == 0U) {
    saturatingIncrement(invalid_operations_);
  } else {
    --transmit_depth_by_source_[source_index];
  }
  recycle(buffer_index);
}

std::size_t PacketBufferPipeline::queuedFrames() const {
  return transmit_queue_.size();
}

std::size_t PacketBufferPipeline::readyFrames() const {
  std::size_t total = 0U;
  for (const ReadyQueue &queue : ready_queues_) {
    total += queue.size();
  }
  return total;
}

std::size_t PacketBufferPipeline::freeBuffers() const {
  std::size_t total = 0U;
  for (const BufferRecord &record : records_) {
    if (record.state == BufferState::kFree) {
      ++total;
    }
  }
  return total;
}

bool PacketBufferPipeline::quiescent() const {
  return ownedBuffers() == 0U && readyFrames() == 0U &&
         transmit_queue_.empty();
}

bool PacketBufferPipeline::readyForStart() const {
  return !accepting_frames_ && quiescent();
}

PipelineSnapshot PacketBufferPipeline::snapshot() const {
  PipelineSnapshot result{};
  result.sources = source_counters_;
  for (const BufferRecord &record : records_) {
    const std::size_t state = static_cast<std::size_t>(record.state);
    if (state < result.buffers_by_state.size()) {
      ++result.buffers_by_state[state];
    }
  }
  for (std::size_t source = 0U; source < kStreamCount; ++source) {
    result.ready_depth_by_source[source] = ready_queues_[source].size();
    result.transmit_depth_by_source[source] =
        transmit_depth_by_source_[source];
  }
  result.run_id = run_id_;
  result.run_starts = run_starts_;
  result.run_start_rejections = run_start_rejections_;
  result.pool_exhaustions = pool_exhaustions_;
  result.invalid_operations = invalid_operations_;
  result.encoding_rejections = encoding_rejections_;
  result.ready_queue_rejections = ready_queue_rejections_;
  result.transmit_queue_rejections = transmit_queue_rejections_;
  result.frames_promoted = frames_promoted_;
  result.ready_queue_depth = readyFrames();
  result.transmit_queue_depth = transmit_queue_.size();
  result.ready_queue_high_water = ready_queue_high_water_;
  result.transmit_queue_high_water = transmit_queue_high_water_;
  result.buffers_owned_high_water = buffers_owned_high_water_;
  result.accepting_frames = accepting_frames_;
  result.drain_pending = !quiescent();
  result.ready_for_start = readyForStart();
  return result;
}

bool PacketBufferPipeline::handleMatches(const FillHandle &handle) const {
  if (!handle.valid() || handle.buffer_index >= records_.size()) {
    return false;
  }
  const BufferRecord &record = records_[handle.buffer_index];
  return record.state == BufferState::kFilling &&
         record.stream == handle.stream &&
         record.sequence == handle.sequence && record.lease == handle.lease;
}

PacketBufferPipeline::BufferIndex PacketBufferPipeline::takeFreeBuffer() {
  for (std::size_t offset = 0U; offset < records_.size(); ++offset) {
    const std::size_t index = (next_free_search_ + offset) % records_.size();
    if (records_[index].state == BufferState::kFree) {
      next_free_search_ = (index + 1U) % records_.size();
      return static_cast<BufferIndex>(index);
    }
  }
  return kInvalidBufferIndex;
}

void PacketBufferPipeline::recycle(BufferIndex index) {
  if (index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  records_[index] = {};
}

void PacketBufferPipeline::recordDrop(Stream stream,
                                      std::uint32_t item_count) {
  if (!validStream(stream)) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  SourceCounters &source = source_counters_[streamIndex(stream)];
  saturatingIncrement(source.frames_dropped);
  saturatingAdd(source.items_dropped,
                static_cast<std::uint64_t>(item_count));
}

void PacketBufferPipeline::updateOwnedHighWater() {
  const std::size_t owned = ownedBuffers();
  if (owned > buffers_owned_high_water_) {
    buffers_owned_high_water_ = owned;
  }
}

std::size_t PacketBufferPipeline::ownedBuffers() const {
  std::size_t owned = 0U;
  for (const BufferRecord &record : records_) {
    if (record.state != BufferState::kFree) {
      ++owned;
    }
  }
  return owned;
}

}  // namespace teensy_daq::packet
