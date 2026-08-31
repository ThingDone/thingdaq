#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <iostream>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#include "protocol.h"
#include "statistics.h"
#include "teensy_usb.h"
#include "usb_transport.h"

namespace {

namespace constants = thingdaq::protocol_v1;
namespace stats = thingdaq::stats;
namespace usb = thingdaq::usb;
namespace wire = thingdaq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

template <std::size_t Capacity>
std::vector<std::uint8_t> bytes(const wire::FixedFrame<Capacity> &frame) {
  return {frame.data(), frame.data() + frame.size()};
}

void append(std::vector<std::uint8_t> &destination,
            const std::vector<std::uint8_t> &source) {
  destination.insert(destination.end(), source.begin(), source.end());
}

wire::CommandFrame pingRequest(std::uint32_t request_id,
                               std::uint64_t nonce) {
  std::array<std::uint8_t, constants::kPingRequestPayloadSize> payload{};
  expect(wire::storeU64({payload.data(), payload.size()},
                        constants::kPingRequestNonceOffset, nonce),
         "encode PING request nonce");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kPingRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode PING request frame");
  return frame;
}

wire::ControlFrame pingResponse(std::uint32_t request_id,
                                std::uint64_t nonce) {
  wire::Request request{};
  request.kind = constants::CommandKind::kPing;
  request.request_id = request_id;
  request.nonce = nonce;
  wire::ControlFrame frame{};
  expect(wire::encodePingResponse(request, 7U, frame).ok(),
         "encode PING response frame");
  return frame;
}

std::vector<std::uint8_t> dataFrame(constants::FrameKind kind,
                                    std::uint32_t run_id,
                                    std::uint32_t sequence,
                                    std::uint64_t first_ticks) {
  std::array<std::uint8_t, constants::kDataPayloadBytes> payload{};
  if (kind == constants::FrameKind::kGpioData) {
    for (std::size_t index = 0U; index < payload.size(); ++index) {
      payload[index] = static_cast<std::uint8_t>(index & 0xFFU);
    }
  }
  wire::FrameFields fields{};
  fields.kind = kind;
  fields.run_id = run_id;
  fields.sequence = sequence;
  fields.first_sample_ticks = first_ticks;
  fields.item_count =
      kind == constants::FrameKind::kAdcData
          ? static_cast<std::uint32_t>(constants::kAdcPairsPerFrame)
          : static_cast<std::uint32_t>(constants::kGpioSamplesPerFrame);
  if (sequence == 0U && first_ticks == 0U) {
    fields.flags =
        static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  }
  wire::DataFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame).ok(),
         "encode complete lower-priority data frame");
  return bytes(frame);
}

class FakeCdcStream final : public usb::CdcByteStream {
 public:
  explicit FakeCdcStream(std::vector<std::uint8_t> input = {})
      : input_(std::move(input)) {}

  bool sessionOpen() const override { return session_open; }

  usb::IoCount available() override {
    if (!available_plan.empty()) {
      const usb::IoCount result = available_plan.front();
      available_plan.pop_front();
      return result;
    }
    const std::size_t remaining = input_.size() - input_offset_;
    return static_cast<usb::IoCount>(remaining);
  }

  usb::IoCount read(std::uint8_t *destination,
                    std::size_t capacity) override {
    if (!read_plan.empty()) {
      const usb::IoCount planned = read_plan.front();
      read_plan.pop_front();
      if (planned <= 0) {
        return planned;
      }
      capacity = std::min(capacity, static_cast<std::size_t>(planned));
    }
    const std::size_t remaining = input_.size() - input_offset_;
    const std::size_t count =
        std::min(std::min(capacity, max_read_size), remaining);
    std::copy_n(input_.data() + input_offset_, count, destination);
    input_offset_ += count;
    return static_cast<usb::IoCount>(count);
  }

  usb::IoCount availableForWrite() override {
    if (!writable_plan.empty()) {
      const usb::IoCount result = writable_plan.front();
      writable_plan.pop_front();
      return result;
    }
    return writable_limit;
  }

  usb::IoCount write(const std::uint8_t *source, std::size_t size) override {
    write_requests.push_back(size);
    if (!write_plan.empty()) {
      const usb::IoCount planned = write_plan.front();
      write_plan.pop_front();
      if (planned <= 0) {
        return planned;
      }
      size = std::min(size, static_cast<std::size_t>(planned));
    }
    output.insert(output.end(), source, source + size);
    return static_cast<usb::IoCount>(size);
  }

  bool inputEmpty() const { return input_offset_ == input_.size(); }

  bool session_open = true;
  std::size_t max_read_size = std::numeric_limits<std::size_t>::max();
  usb::IoCount writable_limit = std::numeric_limits<usb::IoCount>::max();
  std::deque<usb::IoCount> available_plan{};
  std::deque<usb::IoCount> read_plan{};
  std::deque<usb::IoCount> writable_plan{};
  std::deque<usb::IoCount> write_plan{};
  std::vector<std::size_t> write_requests{};
  std::vector<std::uint8_t> output{};

 private:
  std::vector<std::uint8_t> input_{};
  std::size_t input_offset_ = 0U;
};

class FakeLowerPrioritySource final : public usb::LowerPriorityFrameSource {
 public:
  wire::ByteView frontFrame() const override {
    if (frames.empty()) {
      return {};
    }
    return {frames.front().data(), frames.front().size()};
  }

  void releaseFrontFrame() override {
    if (!frames.empty()) {
      frames.pop_front();
    }
  }

  bool abortFrontFrame() override {
    if (frames.empty()) {
      return false;
    }
    frames.pop_front();
    return true;
  }

  std::size_t queuedFrames() const override { return frames.size(); }

  std::deque<std::vector<std::uint8_t>> frames{};
};

void drainTransmit(usb::CdcTransport &transport,
                   std::size_t maximum_visits = 32U) {
  for (std::size_t visit = 0U;
       visit < maximum_visits && transport.hasPendingTransmission(); ++visit) {
    (void)transport.serviceTransmit();
  }
  expect(!transport.hasPendingTransmission(),
         "bounded transmit visits drain every queued frame");
}

void testFixedQueueBoundaries() {
  usb::detail::FixedQueue<std::uint32_t, 3U> queue{};
  static_assert(decltype(queue)::capacity() == 3U);

  std::uint32_t item = 99U;
  expect(queue.empty() && !queue.full() && queue.size() == 0U &&
             queue.front() == nullptr && !queue.pop(item) && item == 99U,
         "fixed queue refuses underflow without mutating output");
  expect(queue.push(1U) && queue.push(2U) && queue.push(3U) && queue.full() &&
             queue.size() == queue.capacity(),
         "fixed queue accepts exactly its declared capacity");
  expect(!queue.push(4U) && queue.front() != nullptr && *queue.front() == 1U,
         "fixed queue refuses overflow without replacing its front");
  expect(queue.pop(item) && item == 1U && queue.push(4U),
         "fixed queue reuses one slot after wraparound");
  expect(queue.eraseFirst(3U) && !queue.eraseFirst(99U) &&
             queue.size() == 2U,
         "fixed queue erases one interior value without fabricating a match");
  expect(queue.pop(item) && item == 2U,
         "erased fixed-queue values do not disturb the front");
  expect(queue.pop(item) && item == 4U && queue.empty(),
         "fixed queue preserves survivor order across erase and wraparound");
  expect(!queue.popFront() && queue.front() == nullptr,
         "fixed queue refuses an empty front removal");
}

void testUsbIdentity() {
  static_assert(usb::kTeensyUsbSerialVendorId == 0x16C0U);
  static_assert(usb::kTeensyUsbSerialProductId == 0x0483U);
  static_assert(thingdaq::identity::usbProductNameMatchesIdentity());

  const std::array<std::uint16_t, 8U> serial{
      '1', '6', '7', '7', '7', '2', '1', '5',
  };
  std::uint32_t decoded = 99U;
  expect(usb::parseDecimalHardwareSerial(serial.data(), serial.size(),
                                         decoded) &&
             decoded == 16777215U,
         "decode the core-style chip-derived USB serial");

  const std::array<std::uint16_t, 3U> invalid{'1', 'x', '2'};
  decoded = 77U;
  expect(!usb::parseDecimalHardwareSerial(invalid.data(), invalid.size(),
                                          decoded) &&
             decoded == 77U,
         "reject a non-decimal USB serial without mutating output");

  const std::array<std::uint16_t, 10U> overflow{
      '4', '2', '9', '4', '9', '6', '7', '2', '9', '6',
  };
  expect(!usb::parseDecimalHardwareSerial(overflow.data(), overflow.size(),
                                          decoded),
         "reject a USB serial that does not fit INFO u32");
  expect(!usb::parseDecimalHardwareSerial(nullptr, 1U, decoded) &&
             !usb::parseDecimalHardwareSerial(serial.data(), 0U, decoded),
         "reject absent USB serial code units");
}

void testIncrementalReceiveAndBackpressure() {
  std::vector<std::uint8_t> input{};
  wire::CommandFrame corrupt = pingRequest(90U, 90U);
  corrupt.mutableData()[corrupt.size() - 1U] ^= 0x40U;
  append(input, bytes(corrupt));
  for (std::uint32_t request_id = 1U; request_id <= 6U; ++request_id) {
    append(input, bytes(pingRequest(request_id, request_id * 11U)));
  }

  FakeCdcStream stream(std::move(input));
  stream.max_read_size = 128U;
  stats::Statistics statistics{};
  usb::CdcTransport transport(stream, statistics);
  std::vector<std::uint32_t> request_ids{};
  std::vector<std::uint32_t> rejected_ids{};
  bool observed_full_queue = false;

  for (std::size_t iteration = 0U;
       iteration < 16U && request_ids.size() < 6U; ++iteration) {
    const usb::ServiceReport report = transport.serviceReceive();
    expect(report.bytes_processed <=
               thingdaq::board::kUsbRxBudgetBytesPerLoop,
           "receive work respects its byte budget");
    expect(report.io_calls <= thingdaq::board::kUsbRxCallsPerLoop,
           "receive work respects its call budget");
    observed_full_queue =
        observed_full_queue ||
        transport.commandQueueDepth() ==
            thingdaq::board::kCommandQueueDepth;

    wire::ParsedCommand command{};
    while (transport.takeCommand(command)) {
      if (command.rejected()) {
        rejected_ids.push_back(command.rejected_request_id);
        wire::ControlFrame rejection{};
        expect(wire::encodeRejectedFrameResponse(
                   command.rejected_request_id, command.rejected_kind,
                   command.rejected_version, command.rejection_error,
                   rejection)
                       .ok() &&
                   transport.queueResponse(rejection),
               "reserve one explicit response for a rejected command");
      } else {
        request_ids.push_back(command.request.request_id);
        expect(transport.queueResponse(
                   pingResponse(command.request.request_id,
                                command.request.nonce)),
               "reserve exactly one response for each dequeued command");
      }
      transport.serviceTransmit();
    }
  }

  expect(stream.inputEmpty(), "bounded receiver eventually drains USB input");
  expect(request_ids ==
             std::vector<std::uint32_t>({1U, 2U, 3U, 4U, 5U, 6U}),
         "complete commands retain FIFO order across queue backpressure");
  expect(rejected_ids == std::vector<std::uint32_t>({90U}),
         "an identifiable malformed command receives one queued rejection");
  expect(observed_full_queue,
         "command input applies backpressure at the fixed queue depth");
  const usb::TransportSnapshot snapshot = transport.snapshot();
  expect(snapshot.command_queue_high_water ==
             thingdaq::board::kCommandQueueDepth,
         "command queue high-water is exposed");
  expect(snapshot.parser.bad_checksums == 1U &&
             statistics.snapshot().bad_checksums == 1U &&
             statistics.snapshot().parser_errors == 1U,
         "parser rejection deltas reach firmware statistics exactly once");
  expect(snapshot.commands_queued == 7U &&
             snapshot.commands_dequeued == 7U &&
             snapshot.rejected_commands_queued == 1U,
         "transport command and rejection counters are exact");
}

void testDtrSessionBoundariesAreBounded() {
  const wire::CommandFrame abandoned = pingRequest(70U, 700U);
  const wire::CommandFrame valid = pingRequest(71U, 710U);
  constexpr std::size_t prefix_size = constants::kHeaderSize + 3U;
  std::vector<std::uint8_t> input(abandoned.data(),
                                  abandoned.data() + prefix_size);
  append(input, bytes(valid));

  FakeCdcStream stream(std::move(input));
  stream.read_plan = {static_cast<usb::IoCount>(prefix_size), 0};
  stats::Statistics statistics{};
  usb::CdcTransport transport(stream, statistics);

  const usb::ServiceReport partial = transport.serviceReceive();
  expect(partial.stalled && transport.takeSessionStarted() &&
             !transport.takeSessionStarted() &&
             transport.snapshot().parser.buffered_bytes == prefix_size,
         "the initial DTR-open session retains one bounded truncated prefix");

  stream.session_open = false;
  const usb::ServiceReport closed = transport.serviceReceive();
  expect(closed.bytes_read == 0U && closed.bytes_processed == 0U &&
             transport.snapshot().parser.buffered_bytes == 0U &&
             !transport.takeSessionStarted(),
         "DTR close abandons pending receive bytes without waiting");

  stream.session_open = true;
  const usb::ServiceReport reopened = transport.serviceReceive();
  wire::ParsedCommand command{};
  expect(reopened.commands_queued == 1U && transport.takeSessionStarted() &&
             !transport.takeSessionStarted() &&
             transport.takeCommand(command) && !command.rejected() &&
             command.request.request_id == 71U &&
             command.request.nonce == 710U,
         "DTR reopen starts a new session and cannot splice the old prefix");

  expect(transport.queueResponse(pingResponse(71U, 710U)),
         "the reopened command reserves a response");
  stream.write_plan = {7, 0};
  const usb::ServiceReport stalled = transport.serviceTransmit();
  expect(stalled.stalled && stalled.bytes_written == 7U &&
             transport.snapshot().active_frame_is_response,
         "a response can stall partway through an open session");

  stream.session_open = false;
  const usb::ServiceReport shutdown = transport.serviceTransmit();
  const usb::TransportSnapshot snapshot = transport.snapshot();
  expect(shutdown.bytes_written == 0U &&
             snapshot.response_queue_depth == 0U &&
             snapshot.active_frame_size == 0U &&
             snapshot.session_open_events == 2U &&
             snapshot.session_close_events == 2U &&
             snapshot.session_responses_abandoned == 1U &&
             !snapshot.session_open,
         "DTR close bounds shutdown and records an abandoned partial response");
}

void testZeroReadAndResponseReservation() {
  const wire::CommandFrame request = pingRequest(41U, 41U);
  FakeCdcStream stream(bytes(request));
  stream.read_plan.push_back(0);
  stats::Statistics statistics{};
  usb::CdcTransport transport(stream, statistics);

  const usb::ServiceReport stalled = transport.serviceReceive();
  expect(stalled.stalled && stalled.io_calls == 1U &&
             transport.commandQueueDepth() == 0U,
         "a zero-length read yields without spinning or consuming input");
  transport.serviceReceive();
  expect(transport.commandQueueDepth() == 1U,
         "receive retries make progress on a later loop");

  for (std::uint32_t request_id = 1U;
       request_id <= thingdaq::board::kResponseQueueDepth; ++request_id) {
    expect(transport.queueResponse(pingResponse(request_id, request_id)),
           "fill the complete response queue");
  }
  expect(transport.responseQueueFree() == 0U,
         "response queue reports no free slots");
  wire::ParsedCommand parsed{};
  expect(!transport.takeCommand(parsed),
         "a command stays queued until one response slot is guaranteed");
  expect(!transport.queueResponse(pingResponse(99U, 99U)),
         "a full response queue rejects rather than overwrites a frame");

  transport.serviceTransmit();
  expect(transport.responseQueueDepth() == 0U &&
             transport.takeCommand(parsed) && parsed.request.request_id == 41U,
         "draining responses releases the queued command for dispatch");
  expect(transport.snapshot().command_awaiting_response,
         "one dequeued command reserves the next response enqueue");

  wire::ControlFrame invalid{};
  expect(!transport.queueResponse(invalid),
         "only a complete checksummed response can enter the queue");
  expect(transport.abandonResponseReservation() &&
             !transport.snapshot().command_awaiting_response &&
             !transport.abandonResponseReservation(),
         "an unrecoverable response failure releases exactly one reservation");
  const usb::TransportSnapshot snapshot = transport.snapshot();
  expect(snapshot.zero_length_read_events == 1U &&
             snapshot.rx_stall_events == 1U &&
             snapshot.response_queue_high_water ==
                 thingdaq::board::kResponseQueueDepth &&
             snapshot.response_queue_rejections == 2U &&
             snapshot.response_reservations_abandoned == 1U,
         "queue depth and receive-stall diagnostics are exposed");
}

void testPartialAndZeroWritesPreserveFrames() {
  FakeCdcStream stream{};
  stream.write_plan = {7, 0};
  stats::Statistics statistics{};
  usb::CdcTransport transport(stream, statistics);
  const wire::ControlFrame first = pingResponse(1U, 101U);
  const wire::ControlFrame second = pingResponse(2U, 202U);
  expect(transport.queueResponse(first) && transport.queueResponse(second),
         "queue two responses");

  const usb::ServiceReport stalled = transport.serviceTransmit();
  expect(stalled.stalled && stalled.bytes_written == 7U &&
             stalled.io_calls == 2U,
         "partial then zero write returns control to the main loop");
  usb::TransportSnapshot snapshot = transport.snapshot();
  expect(snapshot.active_frame_is_response &&
             snapshot.active_frame_bytes_sent == 7U &&
             snapshot.response_queue_depth == 2U,
         "partially emitted response remains owned at the queue front");

  transport.serviceTransmit();
  std::vector<std::uint8_t> expected = bytes(first);
  append(expected, bytes(second));
  expect(stream.output == expected,
         "partial writes preserve complete FIFO response boundaries");
  snapshot = transport.snapshot();
  expect(snapshot.response_queue_depth == 0U &&
             snapshot.responses_completed == 2U &&
             snapshot.partial_write_events == 1U &&
             snapshot.zero_length_write_events == 1U &&
             statistics.snapshot().partial_usb_writes == 1U,
         "partial/zero write counters and completion depths are exact");
}

void testResponsePriorityAndActiveFrameOwnership() {
  const std::vector<std::uint8_t> low_one =
      dataFrame(constants::FrameKind::kAdcData, 7U, 0U, 0U);
  const std::vector<std::uint8_t> low_two =
      dataFrame(constants::FrameKind::kGpioData, 7U, 0U, 0U);
  const wire::ControlFrame high = pingResponse(1U, 1U);

  FakeLowerPrioritySource lower{};
  lower.frames = {low_one, low_two};
  FakeCdcStream stream{};
  stats::Statistics statistics{};
  usb::CdcTransport transport(stream, statistics, &lower);
  expect(transport.queueResponse(high), "queue high-priority response");
  drainTransmit(transport);
  std::vector<std::uint8_t> expected = bytes(high);
  append(expected, low_one);
  append(expected, low_two);
  expect(stream.output == expected,
         "responses win over every lower-priority frame at a boundary");

  FakeLowerPrioritySource active_lower{};
  active_lower.frames = {low_one};
  FakeCdcStream active_stream{};
  active_stream.write_plan = {5, 0};
  stats::Statistics active_statistics{};
  usb::CdcTransport active_transport(active_stream, active_statistics,
                                     &active_lower);
  active_transport.serviceTransmit();
  expect(active_transport.snapshot().active_frame_bytes_sent == 5U,
         "lower-priority frame becomes active only after bytes are accepted");
  expect(active_transport.queueResponse(high),
         "response can queue behind an active frame");
  drainTransmit(active_transport);
  expected = low_one;
  append(expected, bytes(high));
  expect(active_stream.output == expected,
         "an active frame finishes before the new response begins");

  FakeLowerPrioritySource unsent_lower{};
  unsent_lower.frames = {low_one};
  FakeCdcStream unsent_stream{};
  unsent_stream.write_plan = {0};
  stats::Statistics unsent_statistics{};
  usb::CdcTransport unsent_transport(unsent_stream, unsent_statistics,
                                     &unsent_lower);
  unsent_transport.serviceTransmit();
  expect(unsent_transport.snapshot().active_frame_size == 0U,
         "a zero write does not lock an unsent lower-priority frame");
  expect(unsent_transport.queueResponse(high),
         "queue response after lower-priority zero write");
  drainTransmit(unsent_transport);
  expected = bytes(high);
  append(expected, low_one);
  expect(unsent_stream.output == expected,
         "new response overtakes a lower-priority frame with zero bytes sent");
}

void testTransmitBudgets() {
  FakeLowerPrioritySource lower{};
  lower.frames.push_back(
      dataFrame(constants::FrameKind::kAdcData, 9U, 0U, 0U));
  lower.frames.push_back(
      dataFrame(constants::FrameKind::kGpioData, 9U, 0U, 0U));
  lower.frames.push_back(dataFrame(constants::FrameKind::kAdcData, 9U, 1U,
                                   constants::kFrameCoverageTicks));
  FakeCdcStream stream{};
  stats::Statistics statistics{};
  usb::CdcTransport transport(stream, statistics, &lower);

  const usb::ServiceReport first = transport.serviceTransmit();
  expect(first.bytes_written == thingdaq::board::kUsbTxBudgetBytesPerVisit &&
             first.byte_budget_exhausted &&
             first.frames_completed == 2U && first.io_calls == 8U &&
             stream.write_requests.size() == 8U &&
             std::all_of(stream.write_requests.begin(),
                         stream.write_requests.end(), [](std::size_t request) {
                           return request ==
                                  thingdaq::board::kUsbTxMaxWriteBytes;
                         }),
         "one loop fills the core TX ring in bounded USB-packet calls");
  expect(transport.snapshot().active_frame_bytes_sent == 0U &&
             lower.frames.size() == 1U,
         "byte budget stops at a complete frame boundary");
  transport.serviceTransmit();
  expect(stream.output.size() == 3U * constants::kDataFrameBytes &&
             lower.frames.empty(),
         "the next bounded loop completes the remaining frame");
  const usb::TransportSnapshot large_snapshot = transport.snapshot();
  expect(large_snapshot.max_write_request_bytes ==
             thingdaq::board::kUsbTxMaxWriteBytes &&
             large_snapshot.tx_bytes_requested ==
                 3U * constants::kDataFrameBytes,
         "transport exposes exact large-write request telemetry");

  FakeLowerPrioritySource call_limited_lower{};
  call_limited_lower.frames.push_back(
      dataFrame(constants::FrameKind::kGpioData, 10U, 0U, 0U));
  call_limited_lower.frames.push_back(dataFrame(
      constants::FrameKind::kGpioData, 10U, 1U,
      constants::kFrameCoverageTicks));
  call_limited_lower.frames.push_back(dataFrame(
      constants::FrameKind::kGpioData, 10U, 2U,
      2U * constants::kFrameCoverageTicks));
  FakeCdcStream call_limited_stream{};
  call_limited_stream.writable_limit = 1;
  stats::Statistics call_limited_statistics{};
  usb::CdcTransport call_limited_transport(
      call_limited_stream, call_limited_statistics, &call_limited_lower);
  const usb::ServiceReport calls = call_limited_transport.serviceTransmit();
  expect(calls.stalled && calls.io_calls == 0U && calls.bytes_written == 0U &&
             call_limited_stream.write_requests.empty() &&
             call_limited_transport.snapshot().short_capacity_deferrals == 1U,
         "one-byte capacity is deferred instead of requested byte by byte");
  call_limited_stream.writable_limit = static_cast<usb::IoCount>(
      thingdaq::board::kUsbTxMinimumWriteBytes);
  const usb::ServiceReport recovered =
      call_limited_transport.serviceTransmit();
  expect(recovered.bytes_written ==
                 thingdaq::board::kUsbTxCallsPerVisit *
                     thingdaq::board::kUsbTxMinimumWriteBytes &&
             recovered.io_calls == thingdaq::board::kUsbTxCallsPerVisit &&
             recovered.call_budget_exhausted &&
             !call_limited_stream.write_requests.empty() &&
             call_limited_stream.write_requests.front() ==
                 thingdaq::board::kUsbTxMinimumWriteBytes,
         "recovered capacity remains bounded by USB-packet-sized call count");

  FakeLowerPrioritySource malformed_lower{};
  malformed_lower.frames.emplace_back(100U, 0x5AU);
  FakeCdcStream malformed_stream{};
  stats::Statistics malformed_statistics{};
  usb::CdcTransport malformed_transport(
      malformed_stream, malformed_statistics, &malformed_lower);
  (void)malformed_transport.serviceTransmit();
  expect(malformed_lower.frames.empty() && malformed_stream.output.empty() &&
             malformed_transport.snapshot().io_errors == 1U,
         "lower-priority admission rejects every non-4096-byte data frame");
}

}  // namespace

int main() {
  testFixedQueueBoundaries();
  testUsbIdentity();
  testIncrementalReceiveAndBackpressure();
  testDtrSessionBoundariesAreBounded();
  testZeroReadAndResponseReservation();
  testPartialAndZeroWritesPreserveFrames();
  testResponsePriorityAndActiveFrameOwnership();
  testTransmitBudgets();

  if (failures == 0) {
    std::cout << "usb transport tests passed\n";
  }
  return failures == 0 ? 0 : 1;
}
