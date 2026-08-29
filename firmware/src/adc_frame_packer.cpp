#include "adc_frame_packer.h"

#include <cstring>
#include <limits>

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_ADC_PACKER_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_ADC_PACKER_COLD_CODE(section_name)
#endif

namespace teensy_daq::adc_packer {
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

TEENSY_DAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.start")
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
  const packet::PipelineSnapshot packet_snapshot = pipeline.snapshot();
  if (!packet_snapshot.accepting_frames || packet_snapshot.run_id != run_id ||
      packet_snapshot.checksum_algorithm != checksum_algorithm ||
      !protocol::isSupportedChecksum(checksum_algorithm)) {
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
  packet_gap_pending_ = false;
  running_ = true;
  return OperationStatus::kOk;
}

TEENSY_DAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.stop")
StopReport AdcFramePacker::stopProduction() {
  StopReport report{};
  running_ = false;
  report.packet_gap_unreported = packet_gap_pending_;
  return report;
}

TEENSY_DAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.service")
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
    if (pipeline.freeBuffers() == 0U) {
      report.waiting_for_packet_buffer = true;
      break;
    }
    const adc_capture::AcquireResult acquired = source_.acquireReady();
    if (acquired.status == adc_capture::OperationStatus::kNoReadyBuffer) {
      report.waiting_for_buffer = true;
      break;
    }
    if (!acquired.ok() || !acquired.handle.valid()) {
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

TEENSY_DAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.snapshot")
Snapshot AdcFramePacker::snapshot(
    const packet::PacketBufferPipeline &pipeline) const {
  Snapshot result{};
  result.progress = progress(pipeline);
  result.run_id = run_id_;
  result.checksum_algorithm = checksum_algorithm_;
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
  const packet::PipelineSnapshot value = pipeline.snapshot();
  return value.accepting_frames && value.run_id == run_id_ &&
         value.checksum_algorithm == checksum_algorithm_;
}

TEENSY_DAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.consume")
bool AdcFramePacker::consume(
    const adc_capture::BufferHandle &handle,
    packet::PacketBufferPipeline &pipeline, ServiceReport &report) {
  if (!handle.valid() || handle.epoch != run_id_ ||
      handle.pair_count != protocol_v1::kAdcPairsPerFrame ||
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
  bool framed = begun.ok();
  if (framed) {
    protocol::MutableByteView payload = pipeline.writablePayload(begun.handle);
    framed = payload.valid() &&
             payload.size == protocol_v1::kDataPayloadBytes;
    if (framed) {
      std::memcpy(payload.data, handle.pairs, payload.size);
      packet::FrameCompletion completion{};
      completion.first_sample_ticks =
          handle.first_pair * protocol_v1::kAdcPairPeriodTicks;
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
    saturatingIncrement(pipeline_errors_);
    report.pipeline_error = true;
    ++report.frames_dropped;
  }
  return true;
}

TEENSY_DAQ_ADC_PACKER_COLD_CODE(".flashmem.adc_packer.raw_gap")
bool AdcFramePacker::projectRawGap(
    std::uint64_t pair_count,
    packet::PacketBufferPipeline &pipeline) {
  constexpr std::uint64_t pairs_per_frame =
      protocol_v1::kAdcPairsPerFrame;
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

}  // namespace teensy_daq::adc_packer

#undef TEENSY_DAQ_ADC_PACKER_COLD_CODE
