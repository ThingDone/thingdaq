#include "gpio_dual_bank_packer.h"

#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(section_name)
#endif

namespace thingdaq::gpio_aux_packer {
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

}  // namespace

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.pack")
std::size_t packDualBankBatch(const std::uint32_t *primary_words,
                              const std::uint32_t *auxiliary_words,
                              std::size_t sample_count,
                              std::uint8_t *destination,
                              std::size_t destination_capacity) {
  if ((sample_count != 0U &&
       (primary_words == nullptr || auxiliary_words == nullptr ||
        destination == nullptr)) ||
      sample_count > destination_capacity / kPackedWireBytesPerSample) {
    return 0U;
  }
  for (std::size_t index = 0U; index < sample_count; ++index) {
    const std::uint16_t packed =
        packDualBankWord(primary_words[index], auxiliary_words[index]);
    destination[2U * index] = static_cast<std::uint8_t>(packed & 0xFFU);
    destination[2U * index + 1U] =
        static_cast<std::uint8_t>(packed >> 8U);
  }
  return sample_count;
}

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.start")
OperationStatus AuxiliaryBatchPacker::startRun(
    std::uint32_t run_id,
    protocol_v1::ChecksumAlgorithm checksum_algorithm,
    protocol_v2::RateProfile profile,
    const packet::PacketBufferPipeline &pipeline,
    std::uint64_t start_epoch_ticks) {
  if (run_id == 0U || run_id == run_id_) {
    return OperationStatus::kInvalidRunId;
  }
  if (!quiescent()) {
    return OperationStatus::kNotQuiescent;
  }
  const stream_layout::Result selected = stream_layout::experimental(
      protocol_v2::AuxBankMode::kInput, profile);
  if (!selected.ok()) {
    return OperationStatus::kUnsupportedProfile;
  }
  if (!pipeline.accepts(packet::Stream::kGpio, run_id,
                        checksum_algorithm) ||
      !protocol::isSupportedChecksum(checksum_algorithm) ||
      pipeline.layout() != selected.layout) {
    return OperationStatus::kPipelineNotReady;
  }
  layout_ = selected.layout;
  progress_ = {};
  // Wire timestamps are relative to the run and begin at zero. The physical
  // epoch marker is retained only for lifecycle diagnostics, matching the
  // established ADC and one-bank GPIO packers.
  next_sample_ticks_ = 0U;
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

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.stop")
void AuxiliaryBatchPacker::stopProduction() { running_ = false; }

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.service")
ServiceReport AuxiliaryBatchPacker::service(
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
    const gpio_join::AcquireResult acquired = source_.acquireReady();
    if (acquired.status == gpio_join::OperationStatus::kNoReadyBuffer) {
      report.waiting_for_buffer = true;
      break;
    }
    if (!acquired.ok() || !acquired.handle.valid()) {
      saturatingIncrement(source_errors_);
      report.source_error = true;
      break;
    }

    const bool consumed = consume(acquired.handle, pipeline, report);
    const gpio_join::OperationStatus released =
        source_.release(acquired.handle);
    if (released != gpio_join::OperationStatus::kOk) {
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

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.snapshot")
Snapshot AuxiliaryBatchPacker::snapshot(
    const packet::PacketBufferPipeline &pipeline) const {
  Snapshot result{};
  result.progress = progress(pipeline);
  result.layout = layout_;
  result.next_sample_ticks = next_sample_ticks_;
  result.start_epoch_ticks = start_epoch_ticks_;
  result.service_calls = service_calls_;
  result.run_id = run_id_;
  result.checksum_algorithm = checksum_algorithm_;
  result.source_errors = source_errors_;
  result.pipeline_errors = pipeline_errors_;
  result.chronology_errors = chronology_errors_;
  result.packet_gap_pending = packet_gap_pending_;
  result.running = running_;
  result.quiescent = quiescent();
  return result;
}

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.matches")
bool AuxiliaryBatchPacker::pipelineMatches(
    const packet::PacketBufferPipeline &pipeline) const {
  return pipeline.accepts(packet::Stream::kGpio, run_id_,
                          checksum_algorithm_) &&
         pipeline.layout() == layout_;
}

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.consume")
bool AuxiliaryBatchPacker::consume(
    const gpio_join::BufferHandle &handle,
    packet::PacketBufferPipeline &pipeline, ServiceReport &report) {
  const stream_layout::FrameLayout &gpio =
      layout_.forStream(stream_layout::Stream::kGpio);
  if (!handle.valid() || handle.epoch != run_id_ ||
      handle.sample_count != gpio.item_count ||
      handle.sample_period_ticks != gpio.item_period_ticks ||
      handle.first_sample_ticks % gpio.item_period_ticks != 0U ||
      handle.first_sample_ticks >
          std::numeric_limits<std::uint64_t>::max() -
              gpio.coverage_ticks) {
    saturatingIncrement(source_errors_);
    report.source_error = true;
    return false;
  }
  if (handle.first_sample_ticks < next_sample_ticks_) {
    saturatingIncrement(chronology_errors_);
    saturatingIncrement(source_errors_);
    report.source_error = true;
    return false;
  }
  if (handle.first_sample_ticks > next_sample_ticks_) {
    const std::uint64_t missing_ticks =
        handle.first_sample_ticks - next_sample_ticks_;
    if (missing_ticks % gpio.coverage_ticks != 0U) {
      saturatingIncrement(chronology_errors_);
      saturatingIncrement(source_errors_);
      report.source_error = true;
      return false;
    }
    const std::uint64_t missing_frames =
        missing_ticks / gpio.coverage_ticks;
    if (!projectRawGap(missing_frames, pipeline)) {
      saturatingIncrement(pipeline_errors_);
      report.pipeline_error = true;
      return false;
    }
    packet_gap_pending_ = true;
  }

  saturatingIncrement(progress_.frames_produced);
  saturatingAdd(progress_.samples_produced,
                static_cast<std::uint64_t>(handle.sample_count));
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  const bool expected_pressure_drop =
      begun.status == packet::OperationStatus::kPoolExhausted;
  bool framed = begun.ok();
  if (framed) {
    protocol::MutableByteView payload = pipeline.writablePayload(begun.handle);
    framed = payload.valid() && payload.size == gpio.payload_bytes;
    if (framed) {
      const std::size_t packed = packDualBankBatch(
          handle.primary_words, handle.auxiliary_words,
          handle.sample_count, payload.data, payload.size);
      framed = packed == handle.sample_count;
      if (framed) {
        saturatingIncrement(progress_.frames_packed);
        saturatingAdd(progress_.samples_packed,
                      static_cast<std::uint64_t>(packed));
        ++report.frames_packed;
        packet::FrameCompletion completion{};
        completion.first_sample_ticks = handle.first_sample_ticks;
        if (begun.handle.sequence == 0U &&
            handle.first_sample_ticks == 0U) {
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
    } else {
      (void)pipeline.cancelFill(begun.handle);
    }
  }

  next_sample_ticks_ = handle.first_sample_ticks + gpio.coverage_ticks;
  report.samples_consumed += handle.sample_count;
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

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.raw_gap")
bool AuxiliaryBatchPacker::projectRawGap(
    std::uint64_t missing_frames,
    packet::PacketBufferPipeline &pipeline) {
  if (missing_frames == 0U) {
    return true;
  }
  const stream_layout::FrameLayout &gpio =
      layout_.forStream(stream_layout::Stream::kGpio);
  if (pipeline.recordSourceFrameDrops(packet::Stream::kGpio,
                                      missing_frames) !=
      packet::OperationStatus::kOk) {
    return false;
  }
  const std::uint64_t missing_samples =
      missing_frames >
              std::numeric_limits<std::uint64_t>::max() / gpio.item_count
          ? std::numeric_limits<std::uint64_t>::max()
          : missing_frames * gpio.item_count;
  saturatingAdd(progress_.frames_produced, missing_frames);
  saturatingAdd(progress_.samples_produced, missing_samples);
  saturatingAdd(progress_.raw_gap_samples, missing_samples);
  saturatingAdd(progress_.raw_drop_samples_projected, missing_samples);
  return true;
}

THINGDAQ_GPIO_AUX_PACKER_COLD_CODE(".flashmem.gpio_aux_packer.progress")
stats::GpioPackerProgress AuxiliaryBatchPacker::progress(
    const packet::PacketBufferPipeline &pipeline) const {
  stats::GpioPackerProgress result = progress_;
  const packet::SourceCounters source =
      pipeline.sourceCounters(packet::Stream::kGpio);
  result.frames_framed = source.frames_framed;
  result.samples_framed = source.items_framed;
  result.frames_transmitted = source.frames_transmitted;
  result.samples_transmitted = source.items_transmitted;
  result.frames_dropped = source.frames_dropped;
  const std::uint64_t unprojected_raw = subtractFloor(
      result.raw_gap_samples, result.raw_drop_samples_projected);
  result.samples_dropped =
      saturatingSum(source.items_dropped, unprojected_raw);
  result.source_errors = source_errors_;
  result.pipeline_errors = pipeline_errors_;
  result.chronology_errors = chronology_errors_;
  return result;
}

}  // namespace thingdaq::gpio_aux_packer

#undef THINGDAQ_GPIO_AUX_PACKER_COLD_CODE
