#include "adc_frame_packer.h"

#include <cstring>
#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_ADC_PACKER_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_ADC_PACKER_COLD_CODE(section_name)
#endif

namespace thingdaq::adc_packer {
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

THINGDAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.start")
OperationStatus AdcFramePacker::startRun(
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
  if (!pipeline.accepts(packet::Stream::kAdc, run_id,
                        checksum_algorithm) ||
      !protocol::isSupportedChecksum(checksum_algorithm)) {
    return OperationStatus::kPipelineNotReady;
  }
  const stream_layout::RunLayout &selected_layout = pipeline.layout();
  const stream_layout::FrameLayout &adc_layout =
      selected_layout.forStream(stream_layout::Stream::kAdc);
  if (!selected_layout.valid() ||
      adc_layout.item_count > protocol_v1::kAdcPairsPerFrame ||
      adc_layout.item_bytes != sizeof(adc_capture::SamplePair) ||
      adc_layout.payload_bytes !=
          adc_layout.item_count * adc_layout.item_bytes) {
    return OperationStatus::kPipelineNotReady;
  }

  progress_ = {};
  next_source_pair_ = 0U;
  start_epoch_ticks_ = start_epoch_ticks;
  service_calls_ = 0U;
  run_id_ = run_id;
  source_errors_ = 0U;
  pipeline_errors_ = 0U;
  chronology_errors_ = 0U;
  checksum_algorithm_ = checksum_algorithm;
  layout_ = selected_layout;
  packet_gap_pending_ = false;
  running_ = true;
  return OperationStatus::kOk;
}

THINGDAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.stop")
StopReport AdcFramePacker::stopProduction() {
  StopReport report{};
  running_ = false;
  report.packet_gap_unreported = packet_gap_pending_;
  return report;
}

THINGDAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.service")
ServiceReport AdcFramePacker::service(
    packet::PacketBufferPipeline &pipeline, std::size_t buffer_limit) {
  ServiceReport report{};
  saturatingIncrement(service_calls_);
  if (!pipelineMatches(pipeline)) {
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
    return report;
  }
  if (!running_) {
    return report;
  }

  while (report.buffers_consumed < buffer_limit) {
    const adc_capture::AcquireResult acquired = source_.acquireReady();
    if (acquired.status == adc_capture::OperationStatus::kNoReadyBuffer) {
      report.waiting_for_buffer = true;
      break;
    }
    const std::uint32_t expected_pair_count =
        layout_.forStream(stream_layout::Stream::kAdc).item_count;
    if (!acquired.ok() ||
        !acquired.handle.validForPairCount(expected_pair_count)) {
      saturatingIncrement(source_errors_);
      report.source_error = true;
      break;
    }

    const bool consumed = consume(acquired.handle, pipeline, report);
    const adc_capture::OperationStatus released =
        source_.release(acquired.handle);
    if (released != adc_capture::OperationStatus::kOk) {
      saturatingIncrement(source_errors_);
      report.source_error = true;
    }
    ++report.buffers_consumed;
    if (!consumed || report.source_error || report.pipeline_error) {
      break;
    }
  }
  report.work_limit_reached =
      buffer_limit != 0U && report.buffers_consumed == buffer_limit;
  return report;
}

THINGDAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.snapshot")
Snapshot AdcFramePacker::snapshot(
    const packet::PacketBufferPipeline &pipeline) const {
  Snapshot result{};
  result.progress = progress(pipeline);
  result.run_id = run_id_;
  result.checksum_algorithm = checksum_algorithm_;
  result.layout = layout_;
  result.next_source_pair = next_source_pair_;
  result.start_epoch_ticks = start_epoch_ticks_;
  result.service_calls = service_calls_;
  result.running = running_;
  result.packet_gap_pending = packet_gap_pending_;
  result.quiescent = quiescent();
  return result;
}

bool AdcFramePacker::pipelineMatches(
    const packet::PacketBufferPipeline &pipeline) const {
  return pipeline.accepts(packet::Stream::kAdc, run_id_,
                          checksum_algorithm_);
}

THINGDAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.consume")
bool AdcFramePacker::consume(
    const adc_capture::BufferHandle &handle,
    packet::PacketBufferPipeline &pipeline, ServiceReport &report) {
  const stream_layout::FrameLayout &adc_layout =
      layout_.forStream(stream_layout::Stream::kAdc);
  if (!handle.validForPairCount(adc_layout.item_count) ||
      handle.epoch != run_id_ ||
      handle.first_pair >
          std::numeric_limits<std::uint64_t>::max() - handle.pair_count) {
    saturatingIncrement(source_errors_);
    report.source_error = true;
    return false;
  }
  if (handle.first_pair < next_source_pair_) {
    saturatingIncrement(chronology_errors_);
    saturatingIncrement(source_errors_);
    report.source_error = true;
    return false;
  }

  const std::uint64_t raw_gap = handle.first_pair - next_source_pair_;
  if (raw_gap != 0U) {
    saturatingAdd(progress_.raw_gap_pairs, raw_gap);
    packet_gap_pending_ = true;
    if (!projectRawGap(raw_gap, pipeline)) {
      saturatingIncrement(pipeline_errors_);
      report.pipeline_error = true;
      return false;
    }
  }

  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kAdc);
  const bool expected_pressure_drop =
      begun.status == packet::OperationStatus::kPoolExhausted;
  bool framed = begun.ok();
  if (framed) {
    protocol::MutableByteView payload = pipeline.writablePayload(begun.handle);
    const bool timestamp_valid =
        handle.first_pair <=
        std::numeric_limits<std::uint64_t>::max() /
            adc_layout.item_period_ticks;
    framed = payload.valid() && payload.size == adc_layout.payload_bytes &&
             timestamp_valid;
    if (framed) {
      std::memcpy(payload.data, handle.pairs, payload.size);
      packet::FrameCompletion completion{};
      completion.first_sample_ticks =
          layout_.protocol_version == protocol_v1::kProtocolVersion
              ? handle.first_pair * protocol_v1::kAdcPairPeriodTicks
              : handle.first_pair * adc_layout.item_period_ticks;
      if (begun.handle.sequence == 0U && handle.first_pair == 0U) {
        completion.flags = flag(protocol_v1::FrameFlag::kEpochStart);
      }
      if (packet_gap_pending_) {
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

  next_source_pair_ = handle.first_pair + handle.pair_count;
  saturatingIncrement(progress_.frames_consumed);
  saturatingAdd(progress_.pairs_consumed,
                static_cast<std::uint64_t>(handle.pair_count));
  report.pairs_consumed += handle.pair_count;
  if (framed) {
    packet_gap_pending_ = false;
    ++report.frames_framed;
  } else {
    packet_gap_pending_ = true;
    // A pool with no complete unsent eviction candidate is loss, not a
    // hardware/pipeline fault. Release the DMA lease and keep draining future
    // completions; the shared packet layer already consumed sequence and exact
    // drop counters for this frame.
    if (!expected_pressure_drop) {
      saturatingIncrement(pipeline_errors_);
      report.pipeline_error = true;
    }
    ++report.frames_dropped;
  }
  return true;
}

THINGDAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.raw_gap")
bool AdcFramePacker::projectRawGap(
    std::uint64_t pair_count,
    packet::PacketBufferPipeline &pipeline) {
  const std::uint64_t pairs_per_frame =
      layout_.forStream(stream_layout::Stream::kAdc).item_count;
  const std::uint64_t complete_frames = pair_count / pairs_per_frame;
  const std::uint64_t projected_pairs = complete_frames * pairs_per_frame;
  if (pair_count != projected_pairs) {
    // A retained DMA generation always begins on a frame boundary. Keep the
    // exact pair loss in raw telemetry, mark the next frame, and make the
    // impossible partial chronology visible without fabricating a sequence.
    saturatingIncrement(chronology_errors_);
  }
  if (complete_frames == 0U) {
    return true;
  }
  if (pipeline.recordSourceFrameDrops(packet::Stream::kAdc,
                                      complete_frames) !=
      packet::OperationStatus::kOk) {
    return false;
  }
  saturatingAdd(progress_.raw_drop_pairs_projected, projected_pairs);
  return true;
}

stats::AdcPackerProgress AdcFramePacker::progress(
    const packet::PacketBufferPipeline &) const {
  stats::AdcPackerProgress result = progress_;
  result.source_errors = source_errors_;
  result.pipeline_errors = pipeline_errors_;
  result.chronology_errors = chronology_errors_;
  return result;
}

}  // namespace thingdaq::adc_packer

#undef THINGDAQ_ADC_PACKER_COLD_CODE
