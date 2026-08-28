#pragma once

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
};

struct DataPathProgress {
  StreamProgress adc{};
  StreamProgress gpio{};
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
  std::size_t ready_depth = 0U;
  std::size_t ready_high_water = 0U;
  std::uint16_t processing_cpu_basis_points = 0U;
  std::uint32_t source_errors = 0U;
  std::uint32_t pipeline_errors = 0U;
  std::uint32_t chronology_errors = 0U;
};

struct PacketQueueProgress {
  std::size_t ready_depth = 0U;
  std::size_t transmit_depth = 0U;
  std::size_t owned_high_water = 0U;
};

// Detailed firmware diagnostics remain available to firmware tests and future
// transport/status extensions. Protocol v1 currently projects only the data,
// parser, transport, and generation fields into GET_STATUS.
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
  std::uint32_t timeouts = 0U;
  std::uint32_t partial_usb_writes = 0U;
  std::uint32_t state_errors = 0U;
  std::uint32_t parser_errors = 0U;
  std::uint32_t transport_errors = 0U;
  std::uint32_t generation = 1U;
  DataPathProgress data_path{};
  GpioRawCaptureProgress gpio_raw_capture{};
  GpioPackerProgress gpio_packer{};
  PacketQueueProgress packet_queue{};
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

  void recordAdcFrameEmitted(std::uint64_t count = 1U);
  void recordGpioFrameEmitted(std::uint64_t count = 1U);
  void recordAdcItemsDropped(std::uint64_t count);
  void recordGpioItemsDropped(std::uint64_t count);

  // Replace the current generation's cooperative pipeline projection. The
  // native snapshot retains every ownership stage exactly; protocol v1 STATUS
  // projects completed frames and dropped logical items into its fixed fields.
  void publishDataPath(const DataPathProgress &progress);
  void publishGpioRawCapture(const GpioRawCaptureProgress &progress);
  void publishGpioPacker(const GpioPackerProgress &progress);
  void publishPacketQueues(const PacketQueueProgress &progress);

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
