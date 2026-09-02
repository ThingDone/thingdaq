#include "synthetic_source.h"

#include <limits>

#include "board_config.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_SYNTHETIC_PATTERN_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_SYNTHETIC_PATTERN_CODE(section_name)
#endif

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

constexpr std::uint16_t kAdcCodeMask = static_cast<std::uint16_t>(
    (1U << protocol_v1::kAdcResolutionBits) - 1U);

constexpr std::uint32_t mixU32(std::uint32_t value) {
  value += 0x9E3779B9U;
  value = (value ^ (value >> 16U)) * 0x85EBCA6BU;
  value = (value ^ (value >> 13U)) * 0xC2B2AE35U;
  return value ^ (value >> 16U);
}

constexpr void patternAdcCodes(Pattern pattern, std::uint64_t pair_index,
                               std::uint16_t &adc0,
                               std::uint16_t &adc1) {
  switch (pattern) {
    case Pattern::kDefaultRamp:
      adc0 = static_cast<std::uint16_t>((pair_index * 2U) & kAdcCodeMask);
      adc1 = static_cast<std::uint16_t>(
          (pair_index * 2U + 1U) & kAdcCodeMask);
      return;
    case Pattern::kConstant:
      adc0 = 0x155U;
      adc1 = 0xAAAU;
      return;
    case Pattern::kSparseHold:
      adc0 = static_cast<std::uint16_t>(
          0x456U ^ (((pair_index / 997U) & 1U) << 3U));
      adc1 = 0x789U;
      return;
    case Pattern::kSlowAdc:
      adc0 = static_cast<std::uint16_t>(
          (0x100U + pair_index / 8U) & kAdcCodeMask);
      adc1 = static_cast<std::uint16_t>(
          (0x900U + pair_index / 11U) & kAdcCodeMask);
      return;
    case Pattern::kAlternating:
      adc0 = pair_index % 2U == 0U ? 0x123U : 0xFEDU;
      adc1 = pair_index % 2U == 0U ? 0xABCU : 0x456U;
      return;
    case Pattern::kIncompressible:
      adc0 = static_cast<std::uint16_t>(
          mixU32(static_cast<std::uint32_t>(pair_index)) & kAdcCodeMask);
      adc1 = static_cast<std::uint16_t>(
          (mixU32(static_cast<std::uint32_t>(
               pair_index ^ 0xA5A55A5AULL)) >>
           12U) &
          kAdcCodeMask);
      return;
  }
  adc0 = 0U;
  adc1 = 0U;
}

constexpr std::uint8_t patternGpioByte(Pattern pattern,
                                       std::uint64_t sample_index) {
  switch (pattern) {
    case Pattern::kDefaultRamp:
      return static_cast<std::uint8_t>(sample_index & 0xFFU);
    case Pattern::kConstant:
      return 0x5AU;
    case Pattern::kSparseHold: {
      const std::uint64_t epoch = sample_index / 4001U;
      const std::uint64_t gray = epoch ^ (epoch >> 1U);
      return static_cast<std::uint8_t>(0x33U ^ (gray & 0xFFU));
    }
    case Pattern::kSlowAdc:
      return static_cast<std::uint8_t>(
          (0x40U + sample_index / 16U) & 0xFFU);
    case Pattern::kAlternating:
      return sample_index % 2U == 0U ? 0x55U : 0xAAU;
    case Pattern::kIncompressible:
      return static_cast<std::uint8_t>(
          mixU32(static_cast<std::uint32_t>(
              sample_index ^ 0xC001D00DULL)) &
          0xFFU);
  }
  return 0U;
}

}  // namespace

THINGDAQ_SYNTHETIC_PATTERN_CODE(".flashmem.synthetic.formula_adc0")
std::uint16_t SyntheticSource::adc0Code(Pattern pattern,
                                        std::uint64_t pair_index) {
  std::uint16_t adc0 = 0U;
  std::uint16_t adc1 = 0U;
  patternAdcCodes(pattern, pair_index, adc0, adc1);
  return adc0;
}

THINGDAQ_SYNTHETIC_PATTERN_CODE(".flashmem.synthetic.formula_adc1")
std::uint16_t SyntheticSource::adc1Code(Pattern pattern,
                                        std::uint64_t pair_index) {
  std::uint16_t adc0 = 0U;
  std::uint16_t adc1 = 0U;
  patternAdcCodes(pattern, pair_index, adc0, adc1);
  return adc1;
}

THINGDAQ_SYNTHETIC_PATTERN_CODE(".flashmem.synthetic.formula_gpio")
std::uint8_t SyntheticSource::gpioByte(Pattern pattern,
                                       std::uint64_t sample_index) {
  return patternGpioByte(pattern, sample_index);
}

THINGDAQ_SYNTHETIC_PATTERN_CODE(".flashmem.synthetic.start")
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
      !supportsSource(configuration.source, configuration.protocol_version) ||
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
  pattern_ = patternForSource(configuration.source);
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
  pattern_ = Pattern::kDefaultRamp;
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
  result.pattern = pattern_;
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
  if (pattern_ != Pattern::kDefaultRamp) {
    fillExperimentalAdc(payload, first_pair_index);
    return;
  }
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
  if (pattern_ != Pattern::kDefaultRamp) {
    fillExperimentalGpio(payload, first_sample_index);
    return;
  }
  for (std::size_t sample = 0U;
       sample < protocol_v1::kGpioSamplesPerFrame; ++sample) {
    payload.data[sample] = gpioByte(first_sample_index + sample);
  }
}

THINGDAQ_SYNTHETIC_PATTERN_CODE(".flashmem.synthetic.fill_adc")
void SyntheticSource::fillExperimentalAdc(
    protocol::MutableByteView payload, std::uint64_t first_pair_index) {
  for (std::size_t pair = 0U; pair < protocol_v1::kAdcPairsPerFrame;
       ++pair) {
    const std::uint64_t index = first_pair_index + pair;
    std::uint16_t adc0 = 0U;
    std::uint16_t adc1 = 0U;
    patternAdcCodes(pattern_, index, adc0, adc1);
    const std::size_t offset = pair * 4U;
    payload.data[offset] = static_cast<std::uint8_t>(adc0 & 0xFFU);
    payload.data[offset + 1U] =
        static_cast<std::uint8_t>((adc0 >> 8U) & 0xFFU);
    payload.data[offset + 2U] = static_cast<std::uint8_t>(adc1 & 0xFFU);
    payload.data[offset + 3U] =
        static_cast<std::uint8_t>((adc1 >> 8U) & 0xFFU);
  }
}

THINGDAQ_SYNTHETIC_PATTERN_CODE(".flashmem.synthetic.fill_gpio")
void SyntheticSource::fillExperimentalGpio(
    protocol::MutableByteView payload, std::uint64_t first_sample_index) {
  for (std::size_t sample = 0U;
       sample < protocol_v1::kGpioSamplesPerFrame; ++sample) {
    payload.data[sample] =
        patternGpioByte(pattern_, first_sample_index + sample);
  }
}

}  // namespace thingdaq::synthetic
