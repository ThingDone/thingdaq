#include "statistics.h"

#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_STATISTICS_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_STATISTICS_COLD_CODE(section_name)
#endif

namespace thingdaq::stats {
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
  } else if (error == protocol_v1::ErrorCode::kInvalidRequestId) {
    saturatingAdd(counters_.bad_request_ids, std::uint32_t{1U});
  } else if (error == protocol_v1::ErrorCode::kInvalidPayload) {
    saturatingAdd(counters_.bad_payloads, std::uint32_t{1U});
  }
}

void Statistics::recordParserDelta(const protocol::ParserCounters &delta) {
  saturatingAdd(counters_.commands_rejected, delta.candidates_rejected);
  saturatingAdd(counters_.parser_errors, delta.candidates_rejected);
  saturatingAdd(counters_.bad_checksums, delta.bad_checksums);
  saturatingAdd(counters_.bad_lengths, delta.bad_lengths);
  saturatingAdd(counters_.bad_types, delta.bad_kinds);
  saturatingAdd(counters_.bad_versions, delta.bad_versions);
  saturatingAdd(counters_.bad_flags, delta.bad_flags);
  saturatingAdd(counters_.bad_payloads, delta.bad_payloads);
  saturatingAdd(counters_.bad_request_ids, delta.bad_request_ids);
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

THINGDAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_adc_emitted")
void Statistics::recordAdcFrameEmitted(std::uint64_t count) {
  saturatingAdd(counters_.adc_frames_emitted, count);
}

THINGDAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_gpio_emitted")
void Statistics::recordGpioFrameEmitted(std::uint64_t count) {
  saturatingAdd(counters_.gpio_frames_emitted, count);
}

THINGDAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_adc_dropped")
void Statistics::recordAdcItemsDropped(std::uint64_t count) {
  saturatingAdd(counters_.adc_items_dropped, count);
}

THINGDAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.legacy_gpio_dropped")
void Statistics::recordGpioItemsDropped(std::uint64_t count) {
  saturatingAdd(counters_.gpio_items_dropped, count);
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_data")
void Statistics::publishDataPath(const DataPathProgress &progress) {
  counters_.data_path = progress;
  counters_.adc_frames_emitted = progress.adc.frames_emitted;
  counters_.gpio_frames_emitted = progress.gpio.frames_emitted;
  counters_.adc_items_dropped = progress.adc.items_dropped;
  refreshDataProjection();
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_adc_capture")
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

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_adc_packer")
void Statistics::publishAdcPacker(const AdcPackerProgress &progress) {
  counters_.adc_packer = progress;
  refreshDataProjection();
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_gpio_capture")
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

THINGDAQ_STATISTICS_COLD_CODE(
    ".flashmem.statistics.publish_aux_gpio_capture")
void Statistics::publishAuxiliaryGpioCapture(
    const AuxiliaryGpioCaptureProgress &progress) {
  const AuxiliaryGpioCaptureProgress previous =
      counters_.auxiliary_gpio_capture;
  counters_.auxiliary_gpio_capture = progress;
  counters_.auxiliary_gpio_capture.hardware_errors = maximum(
      previous.hardware_errors, progress.hardware_errors);
  counters_.auxiliary_gpio_capture.invariant_errors = maximum(
      previous.invariant_errors, progress.invariant_errors);
  counters_.auxiliary_gpio_capture.resource_conflicts = maximum(
      previous.resource_conflicts, progress.resource_conflicts);
  counters_.auxiliary_gpio_capture.start_errors = maximum(
      previous.start_errors, progress.start_errors);
  counters_.auxiliary_gpio_capture.stop_errors = maximum(
      previous.stop_errors, progress.stop_errors);
  counters_.auxiliary_gpio_capture.stale_dma_completions = maximum(
      previous.stale_dma_completions, progress.stale_dma_completions);
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_gpio_packer")
void Statistics::publishGpioPacker(const GpioPackerProgress &progress) {
  counters_.gpio_packer = progress;
  refreshDataProjection();
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_packet_queues")
void Statistics::publishPacketQueues(const PacketQueueProgress &progress) {
  counters_.packet_queue = progress;
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.publish_usb")
void Statistics::publishUsb(const UsbProgress &progress) {
  counters_.usb = progress;
}

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.refresh_projection")
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

THINGDAQ_STATISTICS_COLD_CODE(".flashmem.statistics.wire_status")
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
  response.gpio_samples_framed = counters_.data_path.gpio.items_framed;
  response.gpio_samples_transmitted =
      counters_.data_path.gpio.items_transmitted;
  response.gpio_raw_samples_lost = counters_.gpio_raw_capture.samples_lost;
  response.gpio_packer_samples_dropped =
      counters_.gpio_packer.packer_drop_samples;
  response.gpio_raw_ring_overruns =
      counters_.gpio_raw_capture.raw_ring_overruns;
  response.gpio_dma_major_loops =
      counters_.gpio_raw_capture.major_loops_completed;
  response.gpio_buffers_completed =
      counters_.gpio_raw_capture.buffers_completed;
  response.gpio_buffers_acquired =
      counters_.gpio_raw_capture.buffers_acquired;
  response.gpio_buffers_released =
      counters_.gpio_raw_capture.buffers_released;
  response.gpio_samples_delivered =
      counters_.gpio_raw_capture.samples_delivered;
  response.gpio_stop_samples_discarded =
      counters_.gpio_raw_capture.stop_discarded_samples;
  response.gpio_frames_produced = counters_.gpio_packer.frames_produced;
  response.gpio_samples_produced = counters_.gpio_packer.samples_produced;
  response.gpio_frames_packed = counters_.gpio_packer.frames_packed;
  response.gpio_duplicate_samples_ignored =
      counters_.gpio_packer.duplicate_samples_ignored;
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
  response.gpio_cache_dma_discards =
      counters_.gpio_raw_capture.cache_dma_discards;
  response.gpio_cache_cpu_invalidations =
      counters_.gpio_raw_capture.cache_cpu_invalidations;
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
  response.adc_cache_dma_discards =
      counters_.adc_capture.cache_dma_discards;
  response.adc_cache_cpu_invalidations =
      counters_.adc_capture.cache_cpu_invalidations;
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
  response.adc_frames_consumed = counters_.adc_packer.frames_consumed;
  response.adc_pairs_consumed = counters_.adc_packer.pairs_consumed;
  response.adc_raw_gap_pairs = counters_.adc_packer.raw_gap_pairs;
  response.adc_raw_drop_pairs_projected =
      counters_.adc_packer.raw_drop_pairs_projected;
  response.gpio_raw_drop_samples_projected =
      counters_.gpio_packer.raw_drop_samples_projected;
  response.gpio_packer_drop_samples_projected =
      counters_.gpio_packer.packer_drop_samples_projected;
  const auto project_stream = [](const StreamProgress &source,
                                 protocol::StreamTelemetry &destination) {
    destination.frames_generated = source.frames_generated;
    destination.items_generated = source.items_generated;
    destination.frames_framed = source.frames_framed;
    destination.items_framed = source.items_framed;
    destination.items_emitted = source.items_emitted;
    destination.frames_transmitted = source.frames_transmitted;
    destination.items_transmitted = source.items_transmitted;
    destination.frames_dropped = source.frames_dropped;
    destination.frames_evicted = source.frames_evicted;
    destination.frames_evicted_after_promotion =
        source.frames_evicted_after_promotion;
    destination.frames_dropped_after_framing =
        source.frames_dropped_after_framing;
    destination.frames_dropped_after_promotion =
        source.frames_dropped_after_promotion;
    destination.payload_bytes_produced = source.payload_bytes_produced;
    destination.payload_bytes_framed = source.payload_bytes_framed;
    destination.payload_bytes_emitted = source.payload_bytes_emitted;
    destination.payload_bytes_transmitted =
        source.payload_bytes_transmitted;
    destination.payload_bytes_dropped = source.payload_bytes_dropped;
    destination.framed_bytes_framed = source.framed_bytes_framed;
    destination.framed_bytes_emitted = source.framed_bytes_emitted;
    destination.framed_bytes_transmitted =
        source.framed_bytes_transmitted;
  };
  project_stream(counters_.data_path.adc, response.streams[0U]);
  project_stream(counters_.data_path.gpio, response.streams[1U]);
  for (std::size_t index = 0U; index < response.streams.size(); ++index) {
    response.streams[index].packet_ready_depth = narrowDepth(
        counters_.packet_queue.ready_depth_by_source[index]);
    response.streams[index].packet_transmit_depth = narrowDepth(
        counters_.packet_queue.transmit_depth_by_source[index]);
    response.streams[index].packet_filling_depth = narrowDepth(
        counters_.packet_queue.filling_depth_by_source[index]);
    response.streams[index].packet_ready_high_water = narrowDepth(
        counters_.packet_queue.ready_high_water_by_source[index]);
    response.streams[index].packet_transmit_high_water = narrowDepth(
        counters_.packet_queue.transmit_high_water_by_source[index]);
  }
  response.packet.ready_high_water =
      narrowDepth(counters_.packet_queue.ready_high_water);
  response.packet.owned_depth =
      narrowDepth(counters_.packet_queue.owned_depth);
  response.packet.transmit_high_water =
      narrowDepth(counters_.packet_queue.transmit_high_water);
  response.packet.frames_promoted = counters_.packet_queue.frames_promoted;
  response.packet.fairness_deferrals =
      counters_.packet_queue.fairness_deferrals;
  response.packet.pressure_evictions =
      counters_.packet_queue.pressure_evictions;
  response.packet.capacity_drops_without_evictable_frame =
      counters_.packet_queue.capacity_drops_without_evictable_frame;
  response.packet.accounted_frame_skew =
      counters_.packet_queue.accounted_frame_skew;
  response.packet.data_payload_bytes_transmitted =
      counters_.packet_queue.data_payload_bytes_transmitted;
  response.packet.data_framed_bytes_transmitted =
      counters_.packet_queue.data_framed_bytes_transmitted;
  response.packet.pool_exhaustions =
      counters_.packet_queue.pool_exhaustions;
  response.packet.invalid_operations =
      counters_.packet_queue.invalid_operations;
  response.packet.encoding_rejections =
      counters_.packet_queue.encoding_rejections;
  response.packet.ready_queue_rejections =
      counters_.packet_queue.ready_queue_rejections;
  response.packet.transmit_queue_rejections =
      counters_.packet_queue.transmit_queue_rejections;
  response.diagnostics.commands_accepted = counters_.commands_accepted;
  response.diagnostics.commands_rejected = counters_.commands_rejected;
  response.diagnostics.bad_checksums = counters_.bad_checksums;
  response.diagnostics.bad_lengths = counters_.bad_lengths;
  response.diagnostics.bad_types = counters_.bad_types;
  response.diagnostics.bad_versions = counters_.bad_versions;
  response.diagnostics.bad_flags = counters_.bad_flags;
  response.diagnostics.bad_payloads = counters_.bad_payloads;
  response.diagnostics.bad_request_ids = counters_.bad_request_ids;
  response.diagnostics.timeouts = counters_.timeouts;
  response.diagnostics.partial_usb_writes = counters_.partial_usb_writes;
  response.diagnostics.state_errors = counters_.state_errors;
  response.usb.short_capacity_deferrals =
      counters_.usb.short_capacity_deferrals;
  response.usb.rx_stall_events = counters_.usb.rx_stall_events;
  response.usb.tx_stall_events = counters_.usb.tx_stall_events;
  response.usb.io_errors = counters_.usb.io_errors;
  response.usb.responses_queued = counters_.usb.responses_queued;
  response.usb.responses_completed = counters_.usb.responses_completed;
  response.usb.response_queue_rejections =
      counters_.usb.response_queue_rejections;
  response.usb.response_reservations_abandoned =
      counters_.usb.response_reservations_abandoned;
  response.usb.command_queue_depth =
      narrowDepth(counters_.usb.command_queue_depth);
  response.usb.response_queue_depth =
      narrowDepth(counters_.usb.response_queue_depth);
  response.usb.lower_priority_queue_depth =
      narrowDepth(counters_.usb.lower_priority_queue_depth);
  response.usb.command_queue_high_water =
      narrowDepth(counters_.usb.command_queue_high_water);
  response.usb.response_queue_high_water =
      narrowDepth(counters_.usb.response_queue_high_water);
  response.usb.active_frame_bytes_sent =
      narrowDepth(counters_.usb.active_frame_bytes_sent);
  response.usb.active_frame_size =
      narrowDepth(counters_.usb.active_frame_size);
  const AuxiliaryGpioCaptureProgress &aux =
      counters_.auxiliary_gpio_capture;
  response.auxiliary_gpio.bank_major_loops = aux.bank_major_loops;
  response.auxiliary_gpio.bank_samples_captured =
      aux.bank_samples_captured;
  response.auxiliary_gpio.bank_ring_overruns = aux.bank_ring_overruns;
  response.auxiliary_gpio.bank_stale_completions =
      aux.bank_stale_completions;
  response.auxiliary_gpio.paired_major_loops = aux.paired_major_loops;
  response.auxiliary_gpio.buffers_completed = aux.buffers_completed;
  response.auxiliary_gpio.buffers_acquired = aux.buffers_acquired;
  response.auxiliary_gpio.buffers_released = aux.buffers_released;
  response.auxiliary_gpio.samples_captured = aux.samples_captured;
  response.auxiliary_gpio.samples_joined = aux.samples_joined;
  response.auxiliary_gpio.samples_delivered = aux.samples_delivered;
  response.auxiliary_gpio.samples_lost = aux.samples_lost;
  response.auxiliary_gpio.raw_ring_overruns = aux.raw_ring_overruns;
  response.auxiliary_gpio.generation_skew_events =
      aux.generation_skew_events;
  response.auxiliary_gpio.generation_skew_samples =
      aux.generation_skew_samples;
  response.auxiliary_gpio.canceled_generations = aux.canceled_generations;
  response.auxiliary_gpio.cancellation_samples = aux.cancellation_samples;
  response.auxiliary_gpio.stop_tail_samples = aux.stop_tail_samples;
  response.auxiliary_gpio.timestamp_mismatches = aux.timestamp_mismatches;
  response.auxiliary_gpio.count_mismatches = aux.count_mismatches;
  response.auxiliary_gpio.destination_mismatches =
      aux.destination_mismatches;
  response.auxiliary_gpio.schedule_exhaustions = aux.schedule_exhaustions;
  response.auxiliary_gpio.stale_completions = aux.stale_completions;
  response.auxiliary_gpio.cache_dma_discards = aux.cache_dma_discards;
  response.auxiliary_gpio.cache_cpu_invalidations =
      aux.cache_cpu_invalidations;
  response.auxiliary_gpio.hardware_errors = aux.hardware_errors;
  response.auxiliary_gpio.invariant_errors = aux.invariant_errors;
  response.auxiliary_gpio.resource_conflicts = aux.resource_conflicts;
  response.auxiliary_gpio.start_errors = aux.start_errors;
  response.auxiliary_gpio.stop_errors = aux.stop_errors;
  response.auxiliary_gpio.stale_dma_completions =
      aux.stale_dma_completions;
  response.auxiliary_gpio.ready_depth = {
      narrowDepth(aux.ready_depth), narrowDepth(aux.ready_depth)};
  response.auxiliary_gpio.ready_high_water = {
      narrowDepth(aux.ready_high_water), narrowDepth(aux.ready_high_water)};
  return response;
}

}  // namespace thingdaq::stats

#undef THINGDAQ_STATISTICS_COLD_CODE
