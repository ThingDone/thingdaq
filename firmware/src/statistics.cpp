#include "statistics.h"

#include <limits>

namespace teensy_daq::stats {
namespace {

template <typename Integer>
void saturatingAdd(Integer &value, Integer amount) {
  const Integer maximum = std::numeric_limits<Integer>::max();
  value = amount > maximum - value ? maximum : value + amount;
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

void Statistics::recordAdcFrameEmitted(std::uint64_t count) {
  saturatingAdd(counters_.adc_frames_emitted, count);
}

void Statistics::recordGpioFrameEmitted(std::uint64_t count) {
  saturatingAdd(counters_.gpio_frames_emitted, count);
}

void Statistics::recordAdcItemsDropped(std::uint64_t count) {
  saturatingAdd(counters_.adc_items_dropped, count);
}

void Statistics::recordGpioItemsDropped(std::uint64_t count) {
  saturatingAdd(counters_.gpio_items_dropped, count);
}

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
  return response;
}

}  // namespace teensy_daq::stats
