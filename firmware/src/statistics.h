#pragma once

#include <cstdint>

#include "protocol.h"

namespace teensy_daq::stats {

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

  void recordAdcFrameEmitted(std::uint64_t count = 1U);
  void recordGpioFrameEmitted(std::uint64_t count = 1U);
  void recordAdcItemsDropped(std::uint64_t count);
  void recordGpioItemsDropped(std::uint64_t count);

  protocol::StatusResponse wireStatus(
      protocol_v1::DeviceState state,
      const protocol::Configuration &configuration) const;

  static constexpr std::uint32_t nextGeneration(std::uint32_t current) {
    const std::uint32_t next = current + 1U;
    return next == 0U ? 1U : next;
  }

 private:
  Snapshot counters_{};
};

static_assert(Statistics::nextGeneration(0U) == 1U);
static_assert(Statistics::nextGeneration(1U) == 2U);
static_assert(Statistics::nextGeneration(0xFFFFFFFFU) == 1U);

}  // namespace teensy_daq::stats
