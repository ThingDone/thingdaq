#include "synthetic_source.h"

#include <limits>

#include "board_config.h"

namespace thingdaq::synthetic {
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

constexpr std::uint16_t flag(protocol_v1::FrameFlag value) {
  return static_cast<std::uint16_t>(value);
}

}  // namespace

OperationStatus SyntheticSource::startRun(
    std::uint32_t run_id, const protocol::Configuration &configuration,
    std::uint64_t start_clock_ticks,
    const packet::PacketBufferPipeline &pipeline) {
  if (run_id == 0U || run_id == run_id_) {
    return OperationStatus::kInvalidRunId;
  }
  const std::uint8_t known_streams =
      static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
      static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
  if (configuration.stream_mask == 0U ||
      (configuration.stream_mask &
       static_cast<std::uint8_t>(~known_streams)) != 0U ||
      configuration.source != protocol_v1::Source::kSynthetic ||
      !protocol::isSupportedChecksum(
          configuration.data_checksum_algorithm) ||
      configuration.data_frame_bytes != protocol_v1::kDataFrameBytes) {
    return OperationStatus::kInvalidConfiguration;
  }
  if (!pipeline.acceptingFrames() || pipeline.runId() != run_id ||
      pipeline.enabledStreamMask() != configuration.stream_mask ||
      pipeline.checksumAlgorithm() !=
          configuration.data_checksum_algorithm) {
    return OperationStatus::kPipelineNotReady;
  }

  streams_ = {};
  for (StreamState &stream : streams_) {
    stream.epoch_frame_pending = true;
  }
  configuration_ = configuration;
  run_id_ = run_id;
  start_clock_ticks_ = start_clock_ticks;
  last_elapsed_ticks_ = 0U;
  service_calls_ = 0U;
  frames_framed_ = 0U;
  frames_dropped_ = 0U;
  next_stream_ = 0U;
  running_ = true;
  return OperationStatus::kOk;
}

void SyntheticSource::stop() {
  running_ = false;
}

ServiceReport SyntheticSource::service(
    std::uint64_t now_ticks, packet::PacketBufferPipeline &pipeline) {
  ServiceReport report{};
  if (!running_) {
    return report;
  }

  saturatingIncrement(service_calls_);
  last_elapsed_ticks_ = now_ticks - start_clock_ticks_;
  while (report.frames_generated < board::kSyntheticFramesPerLoop) {
    bool selected = false;
    const packet::Stream stream =
        selectDueStream(last_elapsed_ticks_, selected);
    if (!selected) {
      report.waiting_for_deadline = mode_ == Mode::kRealtime;
      break;
    }

    // Unpaced mode is demand-limited rather than clock-limited. It waits for
    // ownership instead of inventing drops at CPU-loop speed. Real-time mode
    // must account for every elapsed frame even when the pool is exhausted.
    if (mode_ == Mode::kUnpacedDiagnostic &&
        pipeline.freeBuffers() == 0U) {
      report.waiting_for_buffer = true;
      break;
    }

    (void)generateFrame(stream, pipeline, report);
    next_stream_ = (packet::streamIndex(stream) + 1U) % packet::kStreamCount;
  }

  if (report.frames_generated == board::kSyntheticFramesPerLoop) {
    bool selected = false;
    (void)selectDueStream(last_elapsed_ticks_, selected);
    report.work_limit_reached = selected;
  }
  return report;
}

Snapshot SyntheticSource::snapshot() const {
  Snapshot result{};
  for (std::size_t index = 0U; index < streams_.size(); ++index) {
    const StreamState &source = streams_[index];
    StreamSnapshot &destination = result.streams[index];
    const packet::Stream stream = static_cast<packet::Stream>(index);
    destination.frames_generated = source.frames_generated;
    destination.items_generated = source.items_generated;
    destination.next_item_index =
        source.logical_frames * packet::itemsPerFrame(stream);
    destination.next_frame_first_ticks =
        source.logical_frames * kFrameCoverageTicks;
    destination.epoch_frame_pending = source.epoch_frame_pending;
    destination.gap_before_pending = source.gap_before_pending;
  }
  result.configuration = configuration_;
  result.mode = mode_;
  result.run_id = run_id_;
  result.start_clock_ticks = start_clock_ticks_;
  result.last_elapsed_ticks = last_elapsed_ticks_;
  result.service_calls = service_calls_;
  result.frames_framed = frames_framed_;
  result.frames_dropped = frames_dropped_;
  result.next_stream = next_stream_;
  result.running = running_;
  return result;
}

bool SyntheticSource::streamEnabled(packet::Stream stream) const {
  return packet::streamEnabled(configuration_.stream_mask, stream);
}

bool SyntheticSource::frameDue(packet::Stream stream,
                               std::uint64_t elapsed_ticks) const {
  if (!streamEnabled(stream)) {
    return false;
  }
  if (mode_ == Mode::kUnpacedDiagnostic) {
    return true;
  }
  const StreamState &source = streams_[packet::streamIndex(stream)];
  const std::uint64_t completed_frames = elapsed_ticks / kFrameCoverageTicks;
  return source.logical_frames < completed_frames;
}

packet::Stream SyntheticSource::selectDueStream(
    std::uint64_t elapsed_ticks, bool &selected) const {
  for (std::size_t attempt = 0U; attempt < packet::kStreamCount; ++attempt) {
    const std::size_t index = (next_stream_ + attempt) % packet::kStreamCount;
    const packet::Stream stream = static_cast<packet::Stream>(index);
    if (frameDue(stream, elapsed_ticks)) {
      selected = true;
      return stream;
    }
  }
  selected = false;
  return packet::Stream::kAdc;
}

bool SyntheticSource::generateFrame(
    packet::Stream stream, packet::PacketBufferPipeline &pipeline,
    ServiceReport &report) {
  StreamState &source = streams_[packet::streamIndex(stream)];
  const std::uint64_t first_item_index =
      source.logical_frames * packet::itemsPerFrame(stream);
  const std::uint64_t first_sample_ticks =
      source.logical_frames * kFrameCoverageTicks;
  ++source.logical_frames;
  saturatingIncrement(source.frames_generated);
  saturatingAdd(source.items_generated,
                static_cast<std::uint64_t>(packet::itemsPerFrame(stream)));
  ++report.frames_generated;

  const packet::BeginFillResult begun = pipeline.beginFill(stream);
  if (!begun.ok()) {
    source.gap_before_pending = true;
    saturatingIncrement(frames_dropped_);
    ++report.frames_dropped;
    report.invariant_error =
        begun.status != packet::OperationStatus::kPoolExhausted;
    return false;
  }

  protocol::MutableByteView payload = pipeline.writablePayload(begun.handle);
  if (!payload.valid() || payload.size != protocol_v1::kDataPayloadBytes) {
    (void)pipeline.cancelFill(begun.handle);
    source.gap_before_pending = true;
    saturatingIncrement(frames_dropped_);
    ++report.frames_dropped;
    report.invariant_error = true;
    return false;
  }
  if (stream == packet::Stream::kAdc) {
    fillAdc(payload, first_item_index);
  } else {
    fillGpio(payload, first_item_index);
  }

  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_sample_ticks;
  completion.flags = flag(protocol_v1::FrameFlag::kSynthetic);
  if (source.epoch_frame_pending) {
    completion.flags = static_cast<std::uint16_t>(
        completion.flags | flag(protocol_v1::FrameFlag::kEpochStart));
  }
  if (source.gap_before_pending) {
    completion.flags = static_cast<std::uint16_t>(
        completion.flags | flag(protocol_v1::FrameFlag::kGapBefore) |
        flag(protocol_v1::FrameFlag::kOverrunBefore));
  }
  completion.checksum_algorithm = configuration_.data_checksum_algorithm;
  completion.payload_bytes_written = payload.size;
  const packet::FinishFillResult finished =
      pipeline.finishFill(begun.handle, completion);
  if (!finished.ok()) {
    source.gap_before_pending = true;
    saturatingIncrement(frames_dropped_);
    ++report.frames_dropped;
    report.invariant_error = true;
    return false;
  }

  source.epoch_frame_pending = false;
  source.gap_before_pending = false;
  saturatingIncrement(frames_framed_);
  ++report.frames_framed;
  return true;
}

void SyntheticSource::fillAdc(protocol::MutableByteView payload,
                              std::uint64_t first_pair_index) {
  for (std::size_t pair = 0U; pair < protocol_v1::kAdcPairsPerFrame;
       ++pair) {
    const std::uint64_t index = first_pair_index + pair;
    const std::uint16_t adc0 = adc0Code(index);
    const std::uint16_t adc1 = adc1Code(index);
    const std::size_t offset = pair * 4U;
    payload.data[offset] = static_cast<std::uint8_t>(adc0 & 0xFFU);
    payload.data[offset + 1U] =
        static_cast<std::uint8_t>((adc0 >> 8U) & 0xFFU);
    payload.data[offset + 2U] = static_cast<std::uint8_t>(adc1 & 0xFFU);
    payload.data[offset + 3U] =
        static_cast<std::uint8_t>((adc1 >> 8U) & 0xFFU);
  }
}

void SyntheticSource::fillGpio(protocol::MutableByteView payload,
                               std::uint64_t first_sample_index) {
  for (std::size_t sample = 0U;
       sample < protocol_v1::kGpioSamplesPerFrame; ++sample) {
    payload.data[sample] = gpioByte(first_sample_index + sample);
  }
}

}  // namespace thingdaq::synthetic
