#include "packet_buffer_pipeline.h"

#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_PACKET_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_PACKET_COLD_CODE(section_name)
#endif

namespace thingdaq::packet {
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
Integer saturatingMultiply(Integer left, Integer right) {
  if (left == 0U || right == 0U) {
    return 0U;
  }
  const Integer maximum = std::numeric_limits<Integer>::max();
  return left > maximum / right ? maximum : left * right;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.byte_counters")
SourceByteCounters byteCounters(Stream stream,
                                const SourceCounters &source) {
  SourceByteCounters result{};
  const std::uint64_t payload_bytes_per_item = payloadBytesPerItem(stream);
  const std::uint64_t frame_bytes = protocol_v1::kDataFrameBytes;
  result.payload_bytes_produced = saturatingMultiply(
      source.items_produced, payload_bytes_per_item);
  result.payload_bytes_framed = saturatingMultiply(
      source.items_framed, payload_bytes_per_item);
  result.payload_bytes_emitted = saturatingMultiply(
      source.items_emitted, payload_bytes_per_item);
  result.payload_bytes_transmitted = saturatingMultiply(
      source.items_transmitted, payload_bytes_per_item);
  result.payload_bytes_dropped = saturatingMultiply(
      source.items_dropped, payload_bytes_per_item);
  result.payload_bytes_evicted = saturatingMultiply(
      source.items_evicted, payload_bytes_per_item);
  result.framed_bytes_framed =
      saturatingMultiply(source.frames_framed, frame_bytes);
  result.framed_bytes_emitted =
      saturatingMultiply(source.frames_emitted, frame_bytes);
  result.framed_bytes_transmitted =
      saturatingMultiply(source.frames_transmitted, frame_bytes);
  result.framed_bytes_evicted =
      saturatingMultiply(source.frames_evicted, frame_bytes);
  return result;
}

protocol::Result rleFailure(rle::Status status) {
  if (status == rle::Status::kUnsupportedChecksum) {
    return protocol::Result::failure(
        protocol_v1::ErrorCode::kUnsupportedChecksum,
        protocol::ValidationIssue::kUnsupportedChecksum);
  }
  const bool bad_length =
      status == rle::Status::kInvalidView ||
      status == rle::Status::kInvalidShape ||
      status == rle::Status::kInvalidLength ||
      status == rle::Status::kItemCountOverflow ||
      status == rle::Status::kSizeOverflow ||
      status == rle::Status::kOutputTooSmall ||
      status == rle::Status::kPlanMismatch;
  return protocol::Result::failure(
      bad_length ? protocol_v1::ErrorCode::kInvalidLength
                 : protocol_v1::ErrorCode::kInvalidPayload,
      bad_length ? protocol::ValidationIssue::kBadLength
                 : protocol::ValidationIssue::kBadPayload);
}

void applyFinalizedResult(const rle::FinalizeResult &finalized,
                          FinishFillResult &result) {
  result.frame_encoding = finalized.encoding;
  result.payload_bytes = finalized.payload_bytes;
  result.frame_bytes = finalized.frame_bytes;
  result.rle_run_count = finalized.run_count;
  result.encoding = finalized.ok() ? protocol::Result::success()
                                   : rleFailure(finalized.status);
}

}  // namespace

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.start")
OperationStatus PacketBufferPipeline::startRun(
    std::uint32_t run_id,
    protocol_v1::ChecksumAlgorithm checksum_algorithm,
    std::uint8_t enabled_stream_mask,
    RunFrameFormat frame_format) {
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
  if (!protocol::isSupportedChecksum(checksum_algorithm)) {
    saturatingIncrement(run_start_rejections_);
    return OperationStatus::kUnsupportedChecksum;
  }
  if (!validStreamMask(enabled_stream_mask)) {
    saturatingIncrement(run_start_rejections_);
    return OperationStatus::kInvalidStreamMask;
  }
  if (!frame_format.valid()) {
    saturatingIncrement(run_start_rejections_);
    return OperationStatus::kUnsupportedFrameFormat;
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
  enabled_stream_mask_ = enabled_stream_mask;
  checksum_algorithm_ = checksum_algorithm;
  frame_format_ = frame_format;
  next_free_search_ = 0U;
  next_ready_source_ = 0U;
  ready_queue_high_water_ = 0U;
  transmit_queue_high_water_ = 0U;
  buffers_owned_high_water_ = 0U;
  temporary_pages_owned_ = 0U;
  temporary_page_high_water_ = 0U;
  pool_exhaustions_ = 0U;
  invalid_operations_ = 0U;
  encoding_rejections_ = 0U;
  ready_queue_rejections_ = 0U;
  transmit_queue_rejections_ = 0U;
  temporary_page_exhaustions_ = 0U;
  encode_failures_ = 0U;
  frames_promoted_ = 0U;
  fairness_deferrals_ = 0U;
  pressure_evictions_ = 0U;
  capacity_drops_without_evictable_frame_ = 0U;
  next_eviction_source_ = 0U;
  gap_before_next_frame_ = {};
  accepting_frames_ = true;
  saturatingIncrement(run_starts_);
  return OperationStatus::kOk;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.stop")
StopReport PacketBufferPipeline::stopProduction() {
  StopReport report{};
  accepting_frames_ = false;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferState state = records_[index].state;
    if (state == BufferState::kTransforming) {
      recycleTransform(static_cast<BufferIndex>(index));
      ++report.temporary_pages_recycled;
    } else if (state == BufferState::kFilling) {
      dropBuffer(static_cast<BufferIndex>(index), false);
      ++report.filling_frames_canceled;
    }
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
  if (!streamEnabled(enabled_stream_mask_, stream)) {
    saturatingIncrement(invalid_operations_);
    result.status = OperationStatus::kStreamDisabled;
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
    recordDrop(stream, itemsPerFrame(stream));
    gap_before_next_frame_[streamIndex(stream)] = true;
    saturatingIncrement(capacity_drops_without_evictable_frame_);
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
  record.gap_before_required =
      gap_before_next_frame_[streamIndex(stream)];
  gap_before_next_frame_[streamIndex(stream)] = false;
  record.run_id = run_id_;
  record.sequence = result.handle.sequence;
  record.item_count = itemsPerFrame(stream);
  record.lease_or_representation = lease;
  record.frame_size = 0U;
  result.handle.buffer_index = buffer_index;
  result.handle.lease = lease;
  result.status = OperationStatus::kOk;
  updateOwnedHighWater();
  return result;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.source_drops")
OperationStatus PacketBufferPipeline::recordSourceFrameDrops(
    Stream stream, std::uint64_t frame_count) {
  if (!accepting_frames_ || run_id_ == 0U || !validStream(stream)) {
    saturatingIncrement(invalid_operations_);
    return OperationStatus::kNotRunning;
  }
  if (!streamEnabled(enabled_stream_mask_, stream)) {
    saturatingIncrement(invalid_operations_);
    return OperationStatus::kStreamDisabled;
  }
  if (frame_count == 0U) {
    return OperationStatus::kOk;
  }

  SourceCounters &source = source_counters_[streamIndex(stream)];
  const std::uint64_t items = saturatingMultiply(
      frame_count, static_cast<std::uint64_t>(itemsPerFrame(stream)));
  saturatingAdd(source.frames_produced, frame_count);
  saturatingAdd(source.items_produced, items);
  saturatingAdd(source.frames_dropped, frame_count);
  saturatingAdd(source.items_dropped, items);
  source.next_sequence += static_cast<std::uint32_t>(frame_count);
  gap_before_next_frame_[streamIndex(stream)] = true;
  return OperationStatus::kOk;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.writable_payload")
protocol::MutableByteView PacketBufferPipeline::writablePayload(
    const FillHandle &handle) {
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    return {};
  }
  return {storage_.frame(handle.buffer_index).data() +
              protocol_v1::kHeaderSize,
          protocol_v1::kDataPayloadBytes};
}

FinishFillResult PacketBufferPipeline::finishFill(
    const FillHandle &handle, const FrameCompletion &completion) {
  if (frame_format_.protocol_version == protocol_v2::kProtocolVersion) {
    return finishV2Fill(handle, completion);
  }
  FinishFillResult result{};
  result.protocol_version = protocol_v1::kProtocolVersion;
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    result.status = OperationStatus::kInvalidHandle;
    return result;
  }

  BufferRecord &record = records_[handle.buffer_index];
  if (!accepting_frames_ || record.run_id != run_id_) {
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kNotRunning;
    return result;
  }
  if (completion.payload_bytes_written != protocol_v1::kDataPayloadBytes) {
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kIncompletePayload;
    return result;
  }
  if (completion.checksum_algorithm != checksum_algorithm_) {
    saturatingIncrement(encoding_rejections_);
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kChecksumMismatch;
    result.encoding = protocol::Result::failure(
        protocol_v1::ErrorCode::kUnsupportedChecksum,
        protocol::ValidationIssue::kUnsupportedChecksum);
    return result;
  }

  protocol::FrameFields fields{};
  fields.kind = frameKind(record.stream);
  fields.flags = completion.flags;
  if (record.gap_before_required) {
    fields.flags = static_cast<std::uint16_t>(
        fields.flags |
        static_cast<std::uint16_t>(protocol_v1::FrameFlag::kGapBefore) |
        static_cast<std::uint16_t>(protocol_v1::FrameFlag::kOverrunBefore));
  }
  fields.checksum_algorithm = completion.checksum_algorithm;
  fields.run_id = record.run_id;
  fields.sequence = record.sequence;
  fields.first_sample_ticks = completion.first_sample_ticks;
  fields.item_count = record.item_count;
  result.encoding = protocol::encodeDataFrameInPlace(
      fields,
      {storage_.frame(handle.buffer_index).data(),
       storage_.frame(handle.buffer_index).size()},
      completion.payload_bytes_written);
  result.frame_encoding = protocol_v2::FrameEncoding::kRaw;
  result.raw_fallback_reason = RawFallbackReason::kNotRequested;
  result.payload_bytes = protocol_v1::kDataPayloadBytes;
  result.frame_bytes = protocol_v1::kDataFrameBytes;
  if (!result.encoding.ok()) {
    saturatingIncrement(encoding_rejections_);
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kEncodingRejected;
    return result;
  }
  record.gap_before_required = false;

  ReadyQueue &ready = ready_queues_[streamIndex(record.stream)];
  if (!ready.push(handle.buffer_index)) {
    saturatingIncrement(ready_queue_rejections_);
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kQueueFull;
    return result;
  }

  record.state = BufferState::kReady;
  record.frame_size = protocol_v1::kDataFrameBytes;
  record.lease_or_representation =
      static_cast<std::uint32_t>(LeaseOrRepresentation::kV1Raw);
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

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.finish_v2")
FinishFillResult PacketBufferPipeline::finishV2Fill(
    const FillHandle &handle, const FrameCompletion &completion) {
  FinishFillResult result{};
  result.protocol_version = protocol_v2::kProtocolVersion;
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    result.status = OperationStatus::kInvalidHandle;
    return result;
  }

  BufferRecord &record = records_[handle.buffer_index];
  if (!accepting_frames_ || record.run_id != run_id_) {
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kNotRunning;
    return result;
  }
  if (completion.payload_bytes_written != protocol_v2::kDataPayloadBytes) {
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kIncompletePayload;
    return result;
  }
  if (completion.checksum_algorithm != checksum_algorithm_) {
    saturatingIncrement(encoding_rejections_);
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kChecksumMismatch;
    result.encoding = protocol::Result::failure(
        protocol_v1::ErrorCode::kUnsupportedChecksum,
        protocol::ValidationIssue::kUnsupportedChecksum);
    return result;
  }

  const Stream stream = record.stream;
  const std::uint32_t item_count = record.item_count;
  std::uint16_t selected_flags = completion.flags;
  if (record.gap_before_required) {
    selected_flags = static_cast<std::uint16_t>(
        selected_flags |
        static_cast<std::uint16_t>(protocol_v2::FrameFlag::kGapBefore) |
        static_cast<std::uint16_t>(protocol_v2::FrameFlag::kOverrunBefore));
  }

  rle::DataFrameFields fields{};
  fields.kind = v2FrameKind(stream);
  fields.flags = selected_flags;
  fields.checksum_algorithm = completion.checksum_algorithm;
  fields.run_id = record.run_id;
  fields.sequence = record.sequence;
  fields.first_sample_ticks = completion.first_sample_ticks;
  const protocol::ByteView decoded{
      storage_.frame(handle.buffer_index).data() +
          protocol_v2::kHeaderSize,
      protocol_v2::kDataPayloadBytes};
  const rle::Status input_status =
      rle::validateDataFrameInput(fields, decoded);
  BufferIndex selected_index = handle.buffer_index;
  if (input_status != rle::Status::kOk) {
    result.encoding = rleFailure(input_status);
  } else if (frame_format_.rleAuto()) {
    const rle::SizingPlan plan =
        rle::size(decoded, rle::dataShape(fields.kind));
    if (!plan.ok()) {
      result.encoding = rleFailure(plan.status);
    } else if (plan.encoded_frame_bytes < protocol_v2::kDataFrameBytes) {
      const BufferIndex temporary = takeTransformBuffer(record);
      if (temporary == kInvalidBufferIndex) {
        result.raw_fallback_reason =
            RawFallbackReason::kTemporaryPageUnavailable;
      } else {
        rle::FinalizeResult finalized{};
        bool inject_failure = false;
#if defined(THINGDAQ_TESTING)
        inject_failure = inject_rle_encode_failure_;
        inject_rle_encode_failure_ = false;
#endif
        if (inject_failure) {
          finalized.status = rle::Status::kPlanMismatch;
        } else {
          finalized = rle::finalizeRleDataFrame(
              fields, decoded, plan,
              {storage_.frame(temporary).data(),
               storage_.frame(temporary).size()});
        }
        if (finalized.ok()) {
          selected_index = temporary;
          applyFinalizedResult(finalized, result);
          result.raw_fallback_reason = RawFallbackReason::kNone;
          BufferRecord &selected = records_[selected_index];
          selected.frame_size = finalized.frame_bytes;
          selected.lease_or_representation =
              static_cast<std::uint32_t>(LeaseOrRepresentation::kV2Rle);
          selected.gap_before_required = false;
        } else {
          saturatingIncrement(encode_failures_);
          recycleTransform(temporary);
          result.raw_fallback_reason = RawFallbackReason::kEncoderFailure;
        }
      }
    } else {
      result.raw_fallback_reason = RawFallbackReason::kRleNotSmaller;
    }
  } else {
    result.raw_fallback_reason = RawFallbackReason::kNotRequested;
  }

  if (result.encoding.ok() && selected_index == handle.buffer_index) {
    const rle::FinalizeResult finalized = rle::finalizeRawDataFrame(
        fields,
        {storage_.frame(handle.buffer_index).data(),
         storage_.frame(handle.buffer_index).size()});
    applyFinalizedResult(finalized, result);
  }
  if (!result.encoding.ok()) {
    if (selected_index != handle.buffer_index) {
      recycleTransform(selected_index);
    }
    saturatingIncrement(encoding_rejections_);
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kEncodingRejected;
    return result;
  }

  ReadyQueue &ready = ready_queues_[streamIndex(stream)];
  if (!ready.push(selected_index)) {
    saturatingIncrement(ready_queue_rejections_);
    if (selected_index != handle.buffer_index) {
      recycleTransform(selected_index);
    }
    dropBuffer(handle.buffer_index, false);
    result.status = OperationStatus::kQueueFull;
    return result;
  }

  if (selected_index != handle.buffer_index) {
    if (!releaseTransformOwnership(selected_index)) {
      ready.eraseFirst(selected_index);
      recycleTransform(selected_index);
      saturatingIncrement(invalid_operations_);
      dropBuffer(handle.buffer_index, false);
      result.status = OperationStatus::kEncodingRejected;
      result.encoding = rleFailure(rle::Status::kPlanMismatch);
      return result;
    }
    records_[selected_index].state = BufferState::kReady;
    recycle(handle.buffer_index);
  } else {
    record.state = BufferState::kReady;
    record.frame_size = result.frame_bytes;
    record.lease_or_representation = static_cast<std::uint32_t>(
        LeaseOrRepresentation::kV2Raw);
    record.gap_before_required = false;
  }

  SourceCounters &source = source_counters_[streamIndex(stream)];
  saturatingIncrement(source.frames_framed);
  saturatingAdd(source.items_framed,
                static_cast<std::uint64_t>(item_count));
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

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.cancel")
bool PacketBufferPipeline::cancelFill(const FillHandle &handle) {
  if (!handleMatches(handle)) {
    saturatingIncrement(invalid_operations_);
    return false;
  }
  dropBuffer(handle.buffer_index, false);
  return true;
}

PromotionReport PacketBufferPipeline::serviceReadyFrames(std::size_t limit) {
  PromotionReport report{};
  while (report.frames_promoted < limit) {
    if (transmit_queue_.full()) {
      report.transmit_queue_full = true;
      break;
    }

    bool fairness_deferred = false;
    const std::size_t selected_source =
        selectReadySource(fairness_deferred);
    if (selected_source == kStreamCount) {
      if (fairness_deferred) {
        saturatingIncrement(fairness_deferrals_);
        report.fairness_deferred = true;
      }
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
        !completeRecordValid(record)) {
      saturatingIncrement(invalid_operations_);
      dropBuffer(buffer_index, false);
      report.invariant_error = true;
      continue;
    }
    if (!finalizeGapBefore(buffer_index)) {
      saturatingIncrement(encoding_rejections_);
      dropBuffer(buffer_index, false);
      report.invariant_error = true;
      continue;
    }
    if (!transmit_queue_.push(buffer_index)) {
      saturatingIncrement(transmit_queue_rejections_);
      dropBuffer(buffer_index, false);
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
      !completeRecordValid(record)) {
    return {};
  }
  return {storage_.frame(*buffer_index).data(), record.frame_size};
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.prepare_front")
bool PacketBufferPipeline::prepareFrontFrame() {
  const BufferIndex *buffer_index = transmit_queue_.front();
  if (buffer_index == nullptr || *buffer_index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return false;
  }
  const BufferRecord &record = records_[*buffer_index];
  if (record.state != BufferState::kTransmitting ||
      record.transmission_started ||
      !completeRecordValid(record)) {
    saturatingIncrement(invalid_operations_);
    return false;
  }
  return finalizeGapBefore(*buffer_index);
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.mark_front_started")
void PacketBufferPipeline::markFrontFrameStarted() {
  const BufferIndex *buffer_index = transmit_queue_.front();
  if (buffer_index == nullptr || *buffer_index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  BufferRecord &record = records_[*buffer_index];
  if (record.state != BufferState::kTransmitting ||
      !completeRecordValid(record)) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  record.transmission_started = true;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.abort_front")
bool PacketBufferPipeline::abortFrontFrame() {
  BufferIndex buffer_index = kInvalidBufferIndex;
  if (!transmit_queue_.pop(buffer_index) ||
      buffer_index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return false;
  }

  BufferRecord &record = records_[buffer_index];
  if (record.state != BufferState::kTransmitting ||
      !record.transmission_started || !validStream(record.stream)) {
    saturatingIncrement(invalid_operations_);
    recycle(buffer_index);
    return false;
  }
  const std::size_t source_index = streamIndex(record.stream);
  if (transmit_depth_by_source_[source_index] == 0U) {
    saturatingIncrement(invalid_operations_);
  } else {
    --transmit_depth_by_source_[source_index];
  }
  dropBuffer(buffer_index, false);
  return true;
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
  // Direct portable tests may model an all-at-once transport completion. The
  // real CdcTransport calls markFrontFrameStarted() after accepting byte zero.
  record.transmission_started = true;
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

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.quiescent")
bool PacketBufferPipeline::quiescent() const {
  return ownedBuffers() == 0U && readyFrames() == 0U &&
         transmit_queue_.empty();
}

bool PacketBufferPipeline::readyForStart() const {
  return !accepting_frames_ && quiescent();
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.snapshot")
PipelineSnapshot PacketBufferPipeline::snapshot() const {
  PipelineSnapshot result{};
  result.sources = source_counters_;
  for (std::size_t source = 0U; source < kStreamCount; ++source) {
    result.source_bytes[source] = byteCounters(
        static_cast<Stream>(source), source_counters_[source]);
    saturatingAdd(result.data_payload_bytes_transmitted,
                  result.source_bytes[source].payload_bytes_transmitted);
    saturatingAdd(result.data_framed_bytes_transmitted,
                  result.source_bytes[source].framed_bytes_transmitted);
  }
  for (const BufferRecord &record : records_) {
    const std::size_t state = static_cast<std::size_t>(record.state);
    if (state < result.buffers_by_state.size()) {
      ++result.buffers_by_state[state];
    }
    if (record.state == BufferState::kFilling &&
        validStream(record.stream)) {
      ++result.filling_depth_by_source[streamIndex(record.stream)];
    }
  }
  for (std::size_t source = 0U; source < kStreamCount; ++source) {
    result.ready_depth_by_source[source] = ready_queues_[source].size();
    result.transmit_depth_by_source[source] =
        transmit_depth_by_source_[source];
  }
  result.run_id = run_id_;
  result.enabled_stream_mask = enabled_stream_mask_;
  result.checksum_algorithm = checksum_algorithm_;
  result.frame_format = frame_format_;
  result.run_starts = run_starts_;
  result.run_start_rejections = run_start_rejections_;
  result.pool_exhaustions = pool_exhaustions_;
  result.invalid_operations = invalid_operations_;
  result.encoding_rejections = encoding_rejections_;
  result.ready_queue_rejections = ready_queue_rejections_;
  result.transmit_queue_rejections = transmit_queue_rejections_;
  result.temporary_page_exhaustions = temporary_page_exhaustions_;
  result.encode_failures = encode_failures_;
  result.frames_promoted = frames_promoted_;
  result.fairness_deferrals = fairness_deferrals_;
  result.pressure_evictions = pressure_evictions_;
  result.capacity_drops_without_evictable_frame =
      capacity_drops_without_evictable_frame_;
  result.accounted_frame_skew =
      accountedFrames(0U) > accountedFrames(1U)
          ? accountedFrames(0U) - accountedFrames(1U)
          : accountedFrames(1U) - accountedFrames(0U);
  result.ready_queue_depth = readyFrames();
  result.transmit_queue_depth = transmit_queue_.size();
  result.buffers_owned = ownedBuffers();
  result.ready_queue_high_water = ready_queue_high_water_;
  result.transmit_queue_high_water = transmit_queue_high_water_;
  result.buffers_owned_high_water = buffers_owned_high_water_;
  result.temporary_pages_owned = temporary_pages_owned_;
  result.temporary_page_high_water = temporary_page_high_water_;
  result.accepting_frames = accepting_frames_;
  result.drain_pending = !quiescent();
  result.ready_for_start = readyForStart();
  return result;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.handle_matches")
bool PacketBufferPipeline::handleMatches(const FillHandle &handle) const {
  if (!handle.valid() || handle.buffer_index >= records_.size()) {
    return false;
  }
  const BufferRecord &record = records_[handle.buffer_index];
  return record.state == BufferState::kFilling &&
         record.stream == handle.stream &&
         record.sequence == handle.sequence &&
         record.lease_or_representation == handle.lease;
}

std::size_t PacketBufferPipeline::selectReadySource(
    bool &fairness_deferred) const {
  fairness_deferred = false;
  const bool equal_coverage_fairness =
      accepting_frames_ && enabled_stream_mask_ == kAllStreamMask;
  for (std::size_t attempt = 0U; attempt < kStreamCount; ++attempt) {
    const std::size_t candidate =
        (next_ready_source_ + attempt) % kStreamCount;
    if (!streamEnabled(enabled_stream_mask_,
                       static_cast<Stream>(candidate)) ||
        ready_queues_[candidate].empty()) {
      continue;
    }
    if (!equal_coverage_fairness) {
      return candidate;
    }
    const std::size_t peer = (candidate + 1U) % kStreamCount;
    if (accountedFrames(candidate) <= accountedFrames(peer)) {
      return candidate;
    }
    fairness_deferred = true;
  }
  return kStreamCount;
}

std::uint64_t PacketBufferPipeline::accountedFrames(
    std::size_t source_index) const {
  if (source_index >= source_counters_.size()) {
    return 0U;
  }
  std::uint64_t result = source_counters_[source_index].frames_emitted;
  saturatingAdd(result, source_counters_[source_index].frames_dropped);
  // A promoted frame already contributes to frames_emitted. If it is later
  // dropped for any reason (pressure eviction, session abort, or invariant
  // recovery), subtract that classified drop so its coverage is counted once.
  const std::uint64_t dropped_after_promotion =
      source_counters_[source_index].frames_dropped_after_promotion;
  result = dropped_after_promotion >= result
               ? 0U
               : result - dropped_after_promotion;
  return result;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.take_free")
PacketBufferPipeline::BufferIndex PacketBufferPipeline::takeFreeBuffer() {
  for (std::size_t offset = 0U; offset < records_.size(); ++offset) {
    const std::size_t index = (next_free_search_ + offset) % records_.size();
    if (records_[index].state == BufferState::kFree) {
      next_free_search_ = (index + 1U) % records_.size();
      return static_cast<BufferIndex>(index);
    }
  }

  // Capacity pressure is normal in continue-and-report mode. Only complete
  // immutable frames that USB has not started are eligible; producer-owned
  // construction and a partially emitted frame remain pinned.
  saturatingIncrement(pool_exhaustions_);
  const BufferIndex evicted = oldestEvictableCompleteBuffer();
  if (evicted != kInvalidBufferIndex && evictCompleteBuffer(evicted)) {
    next_free_search_ = (static_cast<std::size_t>(evicted) + 1U) %
                        records_.size();
    return evicted;
  }
  return kInvalidBufferIndex;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.take_transform")
PacketBufferPipeline::BufferIndex
PacketBufferPipeline::takeTransformBuffer(const BufferRecord &source) {
  for (std::size_t offset = 0U; offset < records_.size(); ++offset) {
    const std::size_t index = (next_free_search_ + offset) % records_.size();
    if (records_[index].state != BufferState::kFree) {
      continue;
    }
    next_free_search_ = (index + 1U) % records_.size();
    BufferRecord &temporary = records_[index];
    temporary = source;
    temporary.state = BufferState::kTransforming;
    temporary.transmission_started = false;
    temporary.frame_size = 0U;
    temporary.lease_or_representation =
        static_cast<std::uint32_t>(LeaseOrRepresentation::kV2Rle);
    ++temporary_pages_owned_;
    if (temporary_pages_owned_ > temporary_page_high_water_) {
      temporary_page_high_water_ = temporary_pages_owned_;
    }
    updateOwnedHighWater();
    return static_cast<BufferIndex>(index);
  }

  // Compression workspace acquisition never evicts retained logical data.
  // The still-owned RAW source page is therefore always available for the
  // adaptive fallback path.
  saturatingIncrement(temporary_page_exhaustions_);
  return kInvalidBufferIndex;
}

bool PacketBufferPipeline::releaseTransformOwnership(BufferIndex index) {
  if (index >= records_.size() ||
      records_[index].state != BufferState::kTransforming ||
      temporary_pages_owned_ == 0U) {
    return false;
  }
  --temporary_pages_owned_;
  return true;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.complete_record")
bool PacketBufferPipeline::completeRecordValid(
    const BufferRecord &record) const {
  if (!validStream(record.stream)) {
    return false;
  }
  const LeaseOrRepresentation representation =
      static_cast<LeaseOrRepresentation>(record.lease_or_representation);
  if (representation == LeaseOrRepresentation::kV1Raw) {
    return record.frame_size == protocol_v1::kDataFrameBytes;
  }
  if (representation == LeaseOrRepresentation::kV2Raw) {
    return record.frame_size == protocol_v2::kDataFrameBytes;
  }
  if (representation != LeaseOrRepresentation::kV2Rle) {
    return false;
  }
  const protocol_v2::FrameKind kind = v2FrameKind(record.stream);
  const std::size_t minimum =
      protocol_v2::kHeaderSize +
      (record.stream == Stream::kAdc
           ? protocol_v2::kAdcRleRecordBytes
           : protocol_v2::kGpioRleRecordBytes) +
      protocol_v2::kTrailerSize;
  return record.frame_size >= minimum &&
         record.frame_size <= rle::maximumSelectedFrameBytes(kind) &&
         record.frame_size < protocol_v2::kDataFrameBytes;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.select_eviction")
PacketBufferPipeline::BufferIndex
PacketBufferPipeline::oldestEvictableCompleteBuffer() const {
  BufferIndex oldest = kInvalidBufferIndex;
  std::uint64_t oldest_ticks = 0U;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferRecord &record = records_[index];
    const bool complete_unsent =
        record.state == BufferState::kReady ||
        (record.state == BufferState::kTransmitting &&
         !record.transmission_started);
    if (!complete_unsent ||
        !completeRecordValid(record)) {
      continue;
    }

    std::uint64_t first_ticks = 0U;
    const PacketFrame &frame = storage_.frame(index);
    if (!protocol::loadU64({frame.data(), frame.size()},
                           protocol_v1::kHeaderFirstSampleTicksOffset,
                           first_ticks)) {
      continue;
    }
    if (oldest == kInvalidBufferIndex || first_ticks < oldest_ticks) {
      oldest = static_cast<BufferIndex>(index);
      oldest_ticks = first_ticks;
      continue;
    }
    if (first_ticks != oldest_ticks) {
      continue;
    }

    // ADC and GPIO share one timestamp epoch. Equal-age blocks are selected by
    // a rotating source preference so a sustained combined stall cannot make
    // one source absorb every eviction merely because its producer runs first.
    const std::size_t candidate_source = streamIndex(record.stream);
    const std::size_t oldest_source =
        streamIndex(records_[oldest].stream);
    if (candidate_source == next_eviction_source_ &&
        oldest_source != next_eviction_source_) {
      oldest = static_cast<BufferIndex>(index);
    } else if (candidate_source == oldest_source) {
      const std::uint32_t candidate_distance =
          record.sequence - records_[oldest].sequence;
      if (candidate_distance >= 0x80000000UL) {
        oldest = static_cast<BufferIndex>(index);
      }
    }
  }
  return oldest;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.evict_complete")
bool PacketBufferPipeline::evictCompleteBuffer(BufferIndex index) {
  if (index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return false;
  }
  const BufferRecord record = records_[index];
  if ((record.state != BufferState::kReady &&
       record.state != BufferState::kTransmitting) ||
      record.transmission_started ||
      !completeRecordValid(record) ||
      !validStream(record.stream)) {
    saturatingIncrement(invalid_operations_);
    return false;
  }

  const std::size_t source_index = streamIndex(record.stream);
  if (record.state == BufferState::kReady) {
    if (!ready_queues_[source_index].eraseFirst(index)) {
      saturatingIncrement(invalid_operations_);
      return false;
    }
  } else {
    if (transmit_depth_by_source_[source_index] == 0U ||
        !transmit_queue_.eraseFirst(index)) {
      saturatingIncrement(invalid_operations_);
      return false;
    }
    --transmit_depth_by_source_[source_index];
    saturatingIncrement(
        source_counters_[source_index].frames_evicted_after_promotion);
  }

  dropBuffer(index, true);
  next_eviction_source_ = (source_index + 1U) % kStreamCount;
  saturatingIncrement(pressure_evictions_);
  return true;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.drop_buffer")
void PacketBufferPipeline::dropBuffer(BufferIndex index,
                                      bool pressure_eviction) {
  if (index >= records_.size() ||
      records_[index].state == BufferState::kFree ||
      !validStream(records_[index].stream)) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  const BufferRecord dropped = records_[index];
  SourceCounters &source = source_counters_[streamIndex(dropped.stream)];
  if (dropped.state == BufferState::kReady ||
      dropped.state == BufferState::kTransmitting) {
    saturatingIncrement(source.frames_dropped_after_framing);
  }
  if (dropped.state == BufferState::kTransmitting) {
    saturatingIncrement(source.frames_dropped_after_promotion);
  }
  if (pressure_eviction) {
    saturatingIncrement(source.frames_evicted);
    saturatingAdd(source.items_evicted,
                  static_cast<std::uint64_t>(dropped.item_count));
  }
  propagateGapAfter(dropped);
  recordDrop(dropped.stream, dropped.item_count);
  recycle(index);
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.propagate_gap")
void PacketBufferPipeline::propagateGapAfter(
    const BufferRecord &dropped) {
  if (!validStream(dropped.stream)) {
    saturatingIncrement(invalid_operations_);
    return;
  }

  BufferIndex successor = kInvalidBufferIndex;
  std::uint32_t successor_distance = 0U;
  for (std::size_t index = 0U; index < records_.size(); ++index) {
    const BufferRecord &candidate = records_[index];
    if (candidate.state == BufferState::kFree ||
        candidate.stream != dropped.stream ||
        candidate.transmission_started) {
      continue;
    }
    const std::uint32_t distance = candidate.sequence - dropped.sequence;
    if (distance == 0U || distance >= 0x80000000UL) {
      continue;
    }
    if (successor == kInvalidBufferIndex ||
        distance < successor_distance) {
      successor = static_cast<BufferIndex>(index);
      successor_distance = distance;
    }
  }

  if (successor != kInvalidBufferIndex) {
    markGapBefore(successor);
    return;
  }
  gap_before_next_frame_[streamIndex(dropped.stream)] = true;
}

void PacketBufferPipeline::markGapBefore(BufferIndex index) {
  if (index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  BufferRecord &record = records_[index];
  if (record.state == BufferState::kFree || record.transmission_started) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  record.gap_before_required = true;
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.finalize_gap")
bool PacketBufferPipeline::finalizeGapBefore(BufferIndex index) {
  if (index >= records_.size()) {
    return false;
  }
  BufferRecord &record = records_[index];
  if (!record.gap_before_required) {
    return true;
  }
  if ((record.state != BufferState::kReady &&
       record.state != BufferState::kTransmitting) ||
      !completeRecordValid(record)) {
    return false;
  }

  PacketFrame &frame = storage_.frame(index);
  protocol::MutableByteView bytes{frame.data(), frame.size()};
  std::uint16_t flags = 0U;
  if (!protocol::loadU16({frame.data(), frame.size()},
                         protocol_v1::kHeaderFlagsOffset, flags)) {
    return false;
  }
  flags = static_cast<std::uint16_t>(
      flags |
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kOverrunBefore));
  std::uint32_t checksum = 0U;
  if (!protocol::storeU16(bytes, protocol_v1::kHeaderFlagsOffset, flags) ||
      !protocol::computeChecksum(
           checksum_algorithm_,
           {frame.data(), record.frame_size - protocol_v1::kTrailerSize},
           checksum)
           .ok() ||
      !protocol::storeU32(bytes,
                          record.frame_size - protocol_v1::kTrailerSize,
                          checksum)) {
    saturatingIncrement(encoding_rejections_);
    return false;
  }
  record.gap_before_required = false;
  return true;
}

void PacketBufferPipeline::recycle(BufferIndex index) {
  if (index >= records_.size()) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  records_[index] = {};
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.recycle_transform")
void PacketBufferPipeline::recycleTransform(BufferIndex index) {
  if (index >= records_.size() ||
      records_[index].state != BufferState::kTransforming) {
    saturatingIncrement(invalid_operations_);
    return;
  }
  if (temporary_pages_owned_ == 0U) {
    saturatingIncrement(invalid_operations_);
  } else {
    --temporary_pages_owned_;
  }
  records_[index] = {};
}

THINGDAQ_PACKET_COLD_CODE(".flashmem.packet.record_drop")
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

#undef THINGDAQ_PACKET_COLD_CODE

}  // namespace thingdaq::packet
