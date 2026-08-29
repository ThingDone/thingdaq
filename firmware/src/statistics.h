#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "protocol.h"

namespace teensy_daq::stats {

struct StreamProgress {
  std::uint64_t frames_generated = 0U;
  std::uint64_t items_generated = 0U;
  std::uint64_t frames_framed = 0U;
  std::uint64_t items_framed = 0U;
  std::uint64_t frames_emitted = 0U;
  std::uint64_t items_emitted = 0U;
  std::uint64_t frames_transmitted = 0U;
  std::uint64_t items_transmitted = 0U;
  std::uint64_t frames_dropped = 0U;
  std::uint64_t items_dropped = 0U;
  std::uint64_t frames_evicted = 0U;
  std::uint64_t frames_evicted_after_promotion = 0U;
  std::uint64_t frames_dropped_after_framing = 0U;
  std::uint64_t frames_dropped_after_promotion = 0U;
  std::uint64_t payload_bytes_produced = 0U;
  std::uint64_t payload_bytes_framed = 0U;
  std::uint64_t payload_bytes_emitted = 0U;
  std::uint64_t payload_bytes_transmitted = 0U;
  std::uint64_t payload_bytes_dropped = 0U;
  std::uint64_t framed_bytes_framed = 0U;
  std::uint64_t framed_bytes_emitted = 0U;
  std::uint64_t framed_bytes_transmitted = 0U;
};

struct DataPathProgress {
  StreamProgress adc{};
  StreamProgress gpio{};
};

// The paired ADC DMA owner produces complete wire-sized generations directly.
// These counters preserve the raw dual-channel barrier and exact STOP/overrun
// losses independently from packet ownership.
struct AdcCaptureProgress {
  std::uint64_t adc0_major_loops = 0U;
  std::uint64_t adc1_major_loops = 0U;
  std::uint64_t adc0_results = 0U;
  std::uint64_t adc1_results = 0U;
  std::uint64_t paired_major_loops = 0U;
  std::uint64_t buffers_completed = 0U;
  std::uint64_t buffers_acquired = 0U;
  std::uint64_t buffers_released = 0U;
  std::uint64_t pairs_captured = 0U;
  std::uint64_t pairs_delivered = 0U;
  std::uint64_t pairs_lost = 0U;
  std::uint64_t stop_discarded_pairs = 0U;
  std::uint64_t incomplete_conversions = 0U;
  std::uint64_t overwritten_conversions = 0U;
  std::uint64_t ring_overruns = 0U;
  std::uint64_t incomplete_buffers = 0U;
  std::uint32_t cache_dma_discards = 0U;
  std::uint32_t cache_cpu_invalidations = 0U;
  std::size_t ready_depth = 0U;
  std::size_t ready_high_water = 0U;
  std::uint32_t adc_etc_error_events = 0U;
  std::uint32_t adc_etc_error_flags = 0U;
  std::uint32_t dma_error_events = 0U;
  std::uint32_t completion_mismatches = 0U;
  std::uint32_t destination_mismatches = 0U;
  std::uint32_t schedule_exhaustions = 0U;
  std::uint32_t invariant_errors = 0U;
  std::uint32_t stale_completions = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::uint32_t stale_interrupts = 0U;
};

// Whole raw generations are projected into packet sequence/drop slots before
// the next retained frame. The projection field prevents those same pairs
// from being counted a second time in the aggregate STATUS loss counter.
struct AdcPackerProgress {
  std::uint64_t frames_consumed = 0U;
  std::uint64_t pairs_consumed = 0U;
  std::uint64_t raw_gap_pairs = 0U;
  std::uint64_t raw_drop_pairs_projected = 0U;
  std::uint32_t source_errors = 0U;
  std::uint32_t pipeline_errors = 0U;
  std::uint32_t chronology_errors = 0U;
};

// Raw acquisition precedes packing and packet ownership. Keeping this stage
// in the common model makes a DMA-ring loss visible even when no packet was
// ever available to carry the affected samples.
struct GpioRawCaptureProgress {
  std::uint64_t major_loops_completed = 0U;
  std::uint64_t buffers_completed = 0U;
  std::uint64_t buffers_acquired = 0U;
  std::uint64_t buffers_released = 0U;
  std::uint64_t samples_captured = 0U;
  std::uint64_t samples_delivered = 0U;
  std::uint64_t raw_ring_overruns = 0U;
  std::uint64_t samples_lost = 0U;
  std::uint64_t stop_discarded_samples = 0U;
  std::uint32_t cache_dma_discards = 0U;
  std::uint32_t cache_cpu_invalidations = 0U;
  std::size_t ready_high_water = 0U;
  std::size_t ready_depth = 0U;
  std::uint32_t hardware_errors = 0U;
  std::uint32_t invariant_errors = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t start_errors = 0U;
  std::uint32_t stop_errors = 0U;
  std::uint32_t stale_dma_completions = 0U;
};

// GPIO packing bridges raw acquisition and the common packet pipeline. The
// projection fields identify pre-packet losses that have already consumed a
// packet sequence/drop slot, preventing STATUS from counting the same samples
// once as raw loss and again as a framed-source drop.
struct GpioPackerProgress {
  std::uint64_t frames_produced = 0U;
  std::uint64_t samples_produced = 0U;
  std::uint64_t frames_packed = 0U;
  std::uint64_t samples_packed = 0U;
  std::uint64_t frames_framed = 0U;
  std::uint64_t samples_framed = 0U;
  std::uint64_t frames_transmitted = 0U;
  std::uint64_t samples_transmitted = 0U;
  std::uint64_t frames_dropped = 0U;
  std::uint64_t samples_dropped = 0U;
  std::uint64_t raw_gap_samples = 0U;
  std::uint64_t packer_drop_samples = 0U;
  std::uint64_t raw_drop_samples_projected = 0U;
  std::uint64_t packer_drop_samples_projected = 0U;
  std::uint64_t duplicate_samples_ignored = 0U;
  std::size_t ready_depth = 0U;
  std::size_t ready_high_water = 0U;
  std::uint16_t processing_cpu_basis_points = 0U;
  std::uint32_t source_errors = 0U;
  std::uint32_t pipeline_errors = 0U;
  std::uint32_t chronology_errors = 0U;
};

struct PacketQueueProgress {
  std::array<std::size_t, 2U> filling_depth_by_source{};
  std::array<std::size_t, 2U> ready_depth_by_source{};
  std::array<std::size_t, 2U> transmit_depth_by_source{};
  std::array<std::size_t, 2U> ready_high_water_by_source{};
  std::array<std::size_t, 2U> transmit_high_water_by_source{};
  std::size_t ready_depth = 0U;
  std::size_t transmit_depth = 0U;
  std::size_t owned_depth = 0U;
  std::size_t ready_high_water = 0U;
  std::size_t transmit_high_water = 0U;
  std::size_t owned_high_water = 0U;
  std::uint64_t frames_promoted = 0U;
  std::uint64_t fairness_deferrals = 0U;
  std::uint64_t pressure_evictions = 0U;
  std::uint64_t capacity_drops_without_evictable_frame = 0U;
  std::uint64_t accounted_frame_skew = 0U;
  std::uint64_t data_payload_bytes_transmitted = 0U;
  std::uint64_t data_framed_bytes_transmitted = 0U;
  std::uint32_t pool_exhaustions = 0U;
  std::uint32_t invalid_operations = 0U;
  std::uint32_t encoding_rejections = 0U;
  std::uint32_t ready_queue_rejections = 0U;
  std::uint32_t transmit_queue_rejections = 0U;
};

struct UsbProgress {
  std::uint32_t short_capacity_deferrals = 0U;
  std::uint32_t rx_stall_events = 0U;
  std::uint32_t tx_stall_events = 0U;
  std::uint32_t io_errors = 0U;
  std::uint32_t responses_queued = 0U;
  std::uint32_t responses_completed = 0U;
  std::uint32_t response_queue_rejections = 0U;
  std::uint32_t response_reservations_abandoned = 0U;
  std::size_t command_queue_depth = 0U;
  std::size_t response_queue_depth = 0U;
  std::size_t lower_priority_queue_depth = 0U;
  std::size_t command_queue_high_water = 0U;
  std::size_t response_queue_high_water = 0U;
  std::size_t active_frame_bytes_sent = 0U;
  std::size_t active_frame_size = 0U;
};

// Detailed firmware diagnostics remain available to firmware tests and are
// projected into the fixed protocol-v1 STATUS layout where defined.
struct Snapshot {
  std::uint64_t adc_frames_emitted = 0U;
  std::uint64_t gpio_frames_emitted = 0U;
  std::uint64_t adc_items_dropped = 0U;
  std::uint64_t gpio_items_dropped = 0U;
  std::uint32_t commands_accepted = 0U;
  std::uint32_t commands_rejected = 0U;
  std::uint32_t bad_checksums = 0U;
  std::uint32_t bad_lengths = 0U;
  std::uint32_t bad_types = 0U;
  std::uint32_t bad_versions = 0U;
  std::uint32_t bad_flags = 0U;
  std::uint32_t bad_payloads = 0U;
  std::uint32_t bad_request_ids = 0U;
  std::uint32_t timeouts = 0U;
  std::uint32_t partial_usb_writes = 0U;
  std::uint32_t state_errors = 0U;
  std::uint32_t parser_errors = 0U;
  std::uint32_t transport_errors = 0U;
  std::uint32_t generation = 1U;
  DataPathProgress data_path{};
  AdcCaptureProgress adc_capture{};
  AdcPackerProgress adc_packer{};
  GpioRawCaptureProgress gpio_raw_capture{};
  GpioPackerProgress gpio_packer{};
  PacketQueueProgress packet_queue{};
  UsbProgress usb{};
};

class Statistics {
 public:
  constexpr Snapshot snapshot() const { return counters_; }
  constexpr std::uint32_t generation() const {
    return counters_.generation;
  }
  constexpr std::uint32_t generationAfterReset() const {
    return nextGeneration(counters_.generation);
  }

  // A successful START or RESET_STATS begins a new nonzero generation and
  // clears every diagnostic. The successful command is subsequently the
  // first accepted-command event in that generation.
  std::uint32_t resetForNewGeneration();

  void recordCommandAccepted();
  void recordCommandRejected(protocol_v1::ErrorCode error);

  // The argument is a delta since the caller's prior parser snapshot, never a
  // cumulative parser lifetime total. Successfully parsed commands are
  // counted by recordCommandAccepted/Rejected after semantic dispatch.
  void recordParserDelta(const protocol::ParserCounters &delta);

  void recordTimeout();
  void recordPartialUsbWrite();
  void recordTransportError();
  void recordGpioResourceConflict();
  void recordGpioStartError();
  void recordGpioStopError();
  void recordAdcResourceConflict();
  void recordAdcStartError();
  void recordAdcStopError();

  void recordAdcFrameEmitted(std::uint64_t count = 1U);
  void recordGpioFrameEmitted(std::uint64_t count = 1U);
  void recordAdcItemsDropped(std::uint64_t count);
  void recordGpioItemsDropped(std::uint64_t count);

  // Replace the current generation's cooperative pipeline projection. The
  // native snapshot retains every ownership stage exactly; protocol v1 STATUS
  // projects completed frames and dropped logical items into its fixed fields.
  void publishDataPath(const DataPathProgress &progress);
  void publishAdcCapture(const AdcCaptureProgress &progress);
  void publishAdcPacker(const AdcPackerProgress &progress);
  void publishGpioRawCapture(const GpioRawCaptureProgress &progress);
  void publishGpioPacker(const GpioPackerProgress &progress);
  void publishPacketQueues(const PacketQueueProgress &progress);
  void publishUsb(const UsbProgress &progress);

  protocol::StatusResponse wireStatus(
      protocol_v1::DeviceState state,
      const protocol::Configuration &configuration) const;

  static constexpr std::uint32_t nextGeneration(std::uint32_t current) {
    const std::uint32_t next = current + 1U;
    return next == 0U ? 1U : next;
  }

 private:
  void refreshDataProjection();

  Snapshot counters_{};
};

static_assert(Statistics::nextGeneration(0U) == 1U);
static_assert(Statistics::nextGeneration(1U) == 2U);
static_assert(Statistics::nextGeneration(0xFFFFFFFFU) == 1U);

}  // namespace teensy_daq::stats
