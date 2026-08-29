#include "statistics.h"

#include <limits>

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_STATISTICS_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_STATISTICS_COLD_CODE(section_name)
#endif

namespace teensy_daq::stats {
namespace {

template <typename Integer>
void saturatingAdd(Integer &value, Integer amount) {
  const Integer maximum = std::numeric_limits<Integer>::max();
  value = amount > maximum - value ? maximum : value + amount;
}

template <typename Integer>
Integer saturatingSum(Integer left, Integer right) {
  const Integer maximum = std::numeric_limits<Integer>::max();
  return right > maximum - left ? maximum : left + right;
}

template <typename Integer>
Integer subtractFloor(Integer value, Integer amount) {
  return amount >= value ? Integer{0U} : value - amount;
}

template <typename Integer>
Integer maximum(Integer left, Integer right) {
  return left > right ? left : right;
}

std::uint16_t narrowDepth(std::size_t value) {
  return value > std::numeric_limits<std::uint16_t>::max()
             ? std::numeric_limits<std::uint16_t>::max()
             : static_cast<std::uint16_t>(value);
}

}  // namespace

std::uint32_t Statistics::resetForNewGeneration() {
  const std::uint32_t next = generationAfterReset();
  counters_ = {};
  counters_.generation = next;
  return next;
}

void Statistics::recordCommandAccepted() {
  saturatingAdd(counters_.commands_accepted, std::uint32_t{1U});
}

void Statistics::recordCommandRejected(protocol_v1::ErrorCode error) {
  saturatingAdd(counters_.commands_rejected, std::uint32_t{1U});
  if (error == protocol_v1::ErrorCode::kInvalidState) {
    saturatingAdd(counters_.state_errors, std::uint32_t{1U});
  }
}

void Statistics::recordParserDelta(const protocol::ParserCounters &delta) {
  saturatingAdd(counters_.commands_rejected, delta.candidates_rejected);
  saturatingAdd(counters_.parser_errors, delta.candidates_rejected);
  saturatingAdd(counters_.bad_checksums, delta.bad_checksums);
  saturatingAdd(counters_.bad_lengths, delta.bad_lengths);
  saturatingAdd(counters_.bad_types, delta.bad_kinds);
  saturatingAdd(counters_.bad_versions, delta.bad_versions);
}

void Statistics::recordTimeout() {
  saturatingAdd(counters_.timeouts, std::uint32_t{1U});
  saturatingAdd(counters_.transport_errors, std::uint32_t{1U});
}

void Statistics::recordPartialUsbWrite() {
  saturatingAdd(counters_.partial_usb_writes, std::uint32_t{1U});
}

void Statistics::recordTransportError() {
  saturatingAdd(counters_.transport_errors, std::uint32_t{1U});
}

void Statistics::recordGpioResourceConflict() {
  saturatingAdd(counters_.gpio_raw_capture.resource_conflicts,
                std::uint32_t{1U});
}

void Statistics::recordGpioStartError() {
  saturatingAdd(counters_.gpio_raw_capture.start_errors,
                std::uint32_t{1U});
}

void Statistics::recordGpioStopError() {
  saturatingAdd(counters_.gpio_raw_capture.stop_errors,
                std::uint32_t{1U});
}

void Statistics::recordAdcResourceConflict() {
  saturatingAdd(counters_.adc_capture.resource_conflicts,
                std::uint32_t{1U});
}

void Statistics::recordAdcStartError() {
  saturatingAdd(counters_.adc_capture.start_errors, std::uint32_t{1U});
}

void Statistics::recordAdcStopError() {
  saturatingAdd(counters_.adc_capture.stop_errors, std::uint32_t{1U});
}

TEENSY_DAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_adc_emitted")
void Statistics::recordAdcFrameEmitted(std::uint64_t count) {
  saturatingAdd(counters_.adc_frames_emitted, count);
}

TEENSY_DAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_gpio_emitted")
void Statistics::recordGpioFrameEmitted(std::uint64_t count) {
  saturatingAdd(counters_.gpio_frames_emitted, count);
}

TEENSY_DAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_adc_dropped")
void Statistics::recordAdcItemsDropped(std::uint64_t count) {
  saturatingAdd(counters_.adc_items_dropped, count);
}

TEENSY_DAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_gpio_dropped")
void Statistics::recordGpioItemsDropped(std::uint64_t count) {
  saturatingAdd(counters_.gpio_items_dropped, count);
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_data")
void Statistics::publishDataPath(const DataPathProgress &progress) {
  counters_.data_path = progress;
  counters_.adc_frames_emitted = progress.adc.frames_emitted;
  counters_.gpio_frames_emitted = progress.gpio.frames_emitted;
  counters_.adc_items_dropped = progress.adc.items_dropped;
  refreshDataProjection();
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_adc_capture")
void Statistics::publishAdcCapture(const AdcCaptureProgress &progress) {
  const AdcCaptureProgress previous = counters_.adc_capture;
  counters_.adc_capture = progress;
  counters_.adc_capture.adc_etc_error_events = maximum(
      previous.adc_etc_error_events, progress.adc_etc_error_events);
  counters_.adc_capture.adc_etc_error_flags |=
      previous.adc_etc_error_flags;
  counters_.adc_capture.dma_error_events = maximum(
      previous.dma_error_events, progress.dma_error_events);
  counters_.adc_capture.completion_mismatches = maximum(
      previous.completion_mismatches, progress.completion_mismatches);
  counters_.adc_capture.destination_mismatches = maximum(
      previous.destination_mismatches, progress.destination_mismatches);
  counters_.adc_capture.schedule_exhaustions = maximum(
      previous.schedule_exhaustions, progress.schedule_exhaustions);
  counters_.adc_capture.invariant_errors = maximum(
      previous.invariant_errors, progress.invariant_errors);
  counters_.adc_capture.stale_completions = maximum(
      previous.stale_completions, progress.stale_completions);
  counters_.adc_capture.resource_conflicts = maximum(
      previous.resource_conflicts, progress.resource_conflicts);
  counters_.adc_capture.start_errors = maximum(
      previous.start_errors, progress.start_errors);
  counters_.adc_capture.stop_errors = maximum(
      previous.stop_errors, progress.stop_errors);
  counters_.adc_capture.stale_interrupts = maximum(
      previous.stale_interrupts, progress.stale_interrupts);
  refreshDataProjection();
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_adc_packer")
void Statistics::publishAdcPacker(const AdcPackerProgress &progress) {
  counters_.adc_packer = progress;
  refreshDataProjection();
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_gpio_capture")
void Statistics::publishGpioRawCapture(
    const GpioRawCaptureProgress &progress) {
  const GpioRawCaptureProgress previous = counters_.gpio_raw_capture;
  counters_.gpio_raw_capture = progress;
  counters_.gpio_raw_capture.hardware_errors = maximum(
      previous.hardware_errors, progress.hardware_errors);
  counters_.gpio_raw_capture.invariant_errors = maximum(
      previous.invariant_errors, progress.invariant_errors);
  counters_.gpio_raw_capture.resource_conflicts = maximum(
      previous.resource_conflicts, progress.resource_conflicts);
  counters_.gpio_raw_capture.start_errors = maximum(
      previous.start_errors, progress.start_errors);
  counters_.gpio_raw_capture.stop_errors = maximum(
      previous.stop_errors, progress.stop_errors);
  counters_.gpio_raw_capture.stale_dma_completions = maximum(
      previous.stale_dma_completions, progress.stale_dma_completions);
  refreshDataProjection();
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_gpio_packer")
void Statistics::publishGpioPacker(const GpioPackerProgress &progress) {
  counters_.gpio_packer = progress;
  refreshDataProjection();
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_packet_queues")
void Statistics::publishPacketQueues(const PacketQueueProgress &progress) {
  counters_.packet_queue = progress;
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.refresh_projection")
void Statistics::refreshDataProjection() {
  const std::uint64_t unprojected_adc_loss = subtractFloor(
      counters_.adc_capture.pairs_lost,
      counters_.adc_packer.raw_drop_pairs_projected);
  counters_.adc_items_dropped = saturatingSum(
      counters_.data_path.adc.items_dropped, unprojected_adc_loss);
  const std::uint64_t unprojected_raw_loss = subtractFloor(
      counters_.gpio_raw_capture.samples_lost,
      counters_.gpio_packer.raw_drop_samples_projected);
  const std::uint64_t unprojected_packer_loss = subtractFloor(
      counters_.gpio_packer.packer_drop_samples,
      counters_.gpio_packer.packer_drop_samples_projected);
  counters_.gpio_items_dropped = saturatingSum(
      saturatingSum(counters_.data_path.gpio.items_dropped,
                    unprojected_raw_loss),
      unprojected_packer_loss);
}

TEENSY_DAQ_STATISTICS_COLD_CODE(".flashmem.statistics.wire_status")
protocol::StatusResponse Statistics::wireStatus(
    protocol_v1::DeviceState state,
    const protocol::Configuration &configuration) const {
  protocol::StatusResponse response{};
  response.device_state = state;
  response.configuration = configuration;
  response.adc_frames_emitted = counters_.adc_frames_emitted;
  response.gpio_frames_emitted = counters_.gpio_frames_emitted;
  response.adc_items_dropped = counters_.adc_items_dropped;
  response.gpio_items_dropped = counters_.gpio_items_dropped;
  response.parser_errors = counters_.parser_errors;
  response.transport_errors = counters_.transport_errors;
  response.stats_generation = counters_.generation;
  response.gpio_samples_captured =
      counters_.gpio_raw_capture.samples_captured;
  response.gpio_samples_packed = counters_.gpio_packer.samples_packed;
  response.gpio_samples_framed = counters_.gpio_packer.samples_framed;
  response.gpio_samples_transmitted =
      counters_.gpio_packer.samples_transmitted;
  response.gpio_raw_samples_lost = counters_.gpio_raw_capture.samples_lost;
  response.gpio_packer_samples_dropped =
      counters_.gpio_packer.packer_drop_samples;
  response.gpio_raw_ring_overruns =
      counters_.gpio_raw_capture.raw_ring_overruns;
  response.gpio_dma_major_loops =
      counters_.gpio_raw_capture.major_loops_completed;
  response.gpio_raw_ready_depth =
      narrowDepth(counters_.gpio_raw_capture.ready_depth);
  response.gpio_raw_ready_high_water =
      narrowDepth(counters_.gpio_raw_capture.ready_high_water);
  response.gpio_packed_ready_depth =
      narrowDepth(counters_.gpio_packer.ready_depth);
  response.gpio_packed_ready_high_water =
      narrowDepth(counters_.gpio_packer.ready_high_water);
  response.packet_ready_depth =
      narrowDepth(counters_.packet_queue.ready_depth);
  response.packet_transmit_depth =
      narrowDepth(counters_.packet_queue.transmit_depth);
  response.packet_owned_high_water =
      narrowDepth(counters_.packet_queue.owned_high_water);
  response.gpio_processing_cpu_basis_points =
      counters_.gpio_packer.processing_cpu_basis_points;
  response.gpio_hardware_errors =
      counters_.gpio_raw_capture.hardware_errors;
  response.gpio_raw_invariant_errors =
      counters_.gpio_raw_capture.invariant_errors;
  response.gpio_packer_source_errors = counters_.gpio_packer.source_errors;
  response.gpio_packer_pipeline_errors =
      counters_.gpio_packer.pipeline_errors;
  response.gpio_packer_chronology_errors =
      counters_.gpio_packer.chronology_errors;
  response.gpio_resource_conflicts =
      counters_.gpio_raw_capture.resource_conflicts;
  response.gpio_start_errors = counters_.gpio_raw_capture.start_errors;
  response.gpio_stop_errors = counters_.gpio_raw_capture.stop_errors;
  response.gpio_stale_dma_completions =
      counters_.gpio_raw_capture.stale_dma_completions;
  response.adc0_dma_major_loops = counters_.adc_capture.adc0_major_loops;
  response.adc1_dma_major_loops = counters_.adc_capture.adc1_major_loops;
  response.adc0_dma_results = counters_.adc_capture.adc0_results;
  response.adc1_dma_results = counters_.adc_capture.adc1_results;
  response.adc_paired_major_loops =
      counters_.adc_capture.paired_major_loops;
  response.adc_buffers_completed = counters_.adc_capture.buffers_completed;
  response.adc_buffers_acquired = counters_.adc_capture.buffers_acquired;
  response.adc_buffers_released = counters_.adc_capture.buffers_released;
  response.adc_pairs_captured = counters_.adc_capture.pairs_captured;
  response.adc_pairs_delivered = counters_.adc_capture.pairs_delivered;
  response.adc_pairs_framed = counters_.data_path.adc.items_framed;
  response.adc_pairs_transmitted = counters_.data_path.adc.items_transmitted;
  response.adc_raw_pairs_lost = counters_.adc_capture.pairs_lost;
  response.adc_stop_pairs_discarded =
      counters_.adc_capture.stop_discarded_pairs;
  response.adc_incomplete_conversions =
      counters_.adc_capture.incomplete_conversions;
  response.adc_overwritten_conversions =
      counters_.adc_capture.overwritten_conversions;
  response.adc_raw_ring_overruns = counters_.adc_capture.ring_overruns;
  response.adc_incomplete_buffers = counters_.adc_capture.incomplete_buffers;
  response.adc_raw_ready_depth =
      narrowDepth(counters_.adc_capture.ready_depth);
  response.adc_raw_ready_high_water =
      narrowDepth(counters_.adc_capture.ready_high_water);
  response.adc_etc_error_events =
      counters_.adc_capture.adc_etc_error_events;
  response.adc_etc_error_flags = counters_.adc_capture.adc_etc_error_flags;
  response.adc_dma_error_events = counters_.adc_capture.dma_error_events;
  response.adc_completion_mismatches =
      counters_.adc_capture.completion_mismatches;
  response.adc_destination_mismatches =
      counters_.adc_capture.destination_mismatches;
  response.adc_schedule_exhaustions =
      counters_.adc_capture.schedule_exhaustions;
  response.adc_raw_invariant_errors =
      counters_.adc_capture.invariant_errors;
  response.adc_stale_completions = counters_.adc_capture.stale_completions;
  response.adc_resource_conflicts = counters_.adc_capture.resource_conflicts;
  response.adc_start_errors = counters_.adc_capture.start_errors;
  response.adc_stop_errors = counters_.adc_capture.stop_errors;
  response.adc_stale_interrupts = counters_.adc_capture.stale_interrupts;
  response.adc_packer_source_errors = counters_.adc_packer.source_errors;
  response.adc_packer_pipeline_errors = counters_.adc_packer.pipeline_errors;
  response.adc_packer_chronology_errors =
      counters_.adc_packer.chronology_errors;
  return response;
}

}  // namespace teensy_daq::stats

#undef TEENSY_DAQ_STATISTICS_COLD_CODE
