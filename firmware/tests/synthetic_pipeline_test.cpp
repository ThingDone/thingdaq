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

#include "board_config.h"
#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "statistics.h"
#include "synthetic_source.h"
#include "usb_transport.h"

namespace teensy_daq::packet {

struct PacketBufferPipelineTestAccess {
  static void setNextSequence(PacketBufferPipeline &pipeline, Stream stream,
                              std::uint32_t sequence) {
    pipeline.source_counters_[streamIndex(stream)].next_sequence = sequence;
  }
};

}  // namespace teensy_daq::packet

namespace {

namespace board = teensy_daq::board;
namespace constants = teensy_daq::protocol_v1;
namespace packet = teensy_daq::packet;
namespace stats = teensy_daq::stats;
namespace synthetic = teensy_daq::synthetic;
namespace usb = teensy_daq::usb;
namespace wire = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

constexpr std::size_t stateIndex(packet::BufferState state) {
  return static_cast<std::size_t>(state);
}

wire::Configuration bothStreams() {
  wire::Configuration configuration{};
  configuration.stream_mask =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  configuration.source = constants::Source::kSynthetic;
  configuration.data_checksum_algorithm =
      constants::ChecksumAlgorithm::kAdler32;
  configuration.data_frame_bytes =
      static_cast<std::uint32_t>(constants::kDataFrameBytes);
  return configuration;
}

void fillSyntheticPayload(packet::Stream stream, wire::MutableByteView payload,
                          std::uint64_t first_item) {
  bool packed = payload.valid() &&
                payload.size == constants::kDataPayloadBytes;
  if (!packed) {
    expect(false, "a FILLING buffer exposes one complete fixed payload");
    return;
  }

  if (stream == packet::Stream::kAdc) {
    for (std::size_t pair = 0U; pair < constants::kAdcPairsPerFrame; ++pair) {
      const std::uint64_t index = first_item + pair;
      const std::size_t offset = pair * constants::kAdcBytesPerPair;
      packed = packed &&
               wire::storeU16(payload, offset,
                              synthetic::SyntheticSource::adc0Code(index)) &&
               wire::storeU16(payload, offset + 2U,
                              synthetic::SyntheticSource::adc1Code(index));
    }
  } else {
    for (std::size_t sample = 0U; sample < payload.size; ++sample) {
      payload.data[sample] =
          synthetic::SyntheticSource::gpioByte(first_item + sample);
    }
  }
  expect(packed, "synthetic payload packing stays within the fixed buffer");
}

packet::FillHandle fillCompleteFrame(packet::PacketBufferPipeline &pipeline,
                                     packet::Stream stream,
                                     std::uint64_t first_ticks,
                                     std::uint64_t first_item,
                                     std::uint16_t flags = 0U) {
  const packet::BeginFillResult begun = pipeline.beginFill(stream);
  expect(begun.ok(), "reserve a fixed buffer for a complete test frame");
  if (!begun.ok()) {
    return {};
  }
  wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  fillSyntheticPayload(stream, payload, first_item);
  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_ticks;
  completion.flags = static_cast<std::uint16_t>(
      flags | static_cast<std::uint16_t>(constants::FrameFlag::kSynthetic));
  if (first_ticks == 0U && first_item == 0U) {
    completion.flags = static_cast<std::uint16_t>(
        completion.flags |
        static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart));
  }
  completion.payload_bytes_written = payload.size;
  expect(pipeline.finishFill(begun.handle, completion).ok(),
         "complete framing and checksum before READY admission");
  return begun.handle;
}

wire::DecodedFrame decodeFront(packet::PacketBufferPipeline &pipeline,
                               const std::string &description) {
  wire::DecodedFrame decoded{};
  expect(wire::decodeFrame(pipeline.frontFrame(), decoded).ok(),
         description + " decodes with a valid checksum");
  return decoded;
}

void expectSyntheticFrame(const wire::DecodedFrame &frame,
                          packet::Stream stream, std::uint32_t run_id,
                          std::uint32_t sequence,
                          std::uint64_t logical_frame,
                          const std::string &description) {
  const constants::FrameKind expected_kind = packet::frameKind(stream);
  const std::uint64_t expected_ticks =
      logical_frame * synthetic::kFrameCoverageTicks;
  const std::uint16_t synthetic_flag =
      static_cast<std::uint16_t>(constants::FrameFlag::kSynthetic);
  const std::uint16_t epoch_flag =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  const std::uint16_t gap_flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore));
  expect(frame.header.kind == expected_kind &&
             frame.header.run_id == run_id &&
             frame.header.sequence == sequence &&
             frame.header.first_sample_ticks == expected_ticks &&
             frame.header.item_count == packet::itemsPerFrame(stream) &&
             frame.header.total_length == constants::kDataFrameBytes &&
             frame.header.payload_length == constants::kDataPayloadBytes &&
             frame.header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kAdler32 &&
             (frame.header.flags & synthetic_flag) != 0U &&
             ((frame.header.flags & epoch_flag) != 0U) ==
                 (logical_frame == 0U) &&
             (frame.header.flags & gap_flags) == 0U,
         description + " has exact framing, identity, sequence, and time");

  bool pattern_valid = frame.payload.valid() &&
                       frame.payload.size == constants::kDataPayloadBytes;
  const std::uint64_t first_item =
      logical_frame * packet::itemsPerFrame(stream);
  if (pattern_valid && stream == packet::Stream::kAdc) {
    for (std::size_t pair = 0U; pair < constants::kAdcPairsPerFrame; ++pair) {
      std::uint16_t adc0 = 0U;
      std::uint16_t adc1 = 0U;
      const std::size_t offset = pair * constants::kAdcBytesPerPair;
      const std::uint64_t item = first_item + pair;
      pattern_valid =
          pattern_valid && wire::loadU16(frame.payload, offset, adc0) &&
          wire::loadU16(frame.payload, offset + 2U, adc1) &&
          adc0 == synthetic::SyntheticSource::adc0Code(item) &&
          adc1 == synthetic::SyntheticSource::adc1Code(item);
    }
  } else if (pattern_valid) {
    for (std::size_t sample = 0U;
         sample < constants::kGpioSamplesPerFrame; ++sample) {
      pattern_valid =
          pattern_valid &&
          frame.payload.data[sample] ==
              synthetic::SyntheticSource::gpioByte(first_item + sample);
    }
  }
  expect(pattern_valid,
         description + " preserves every synthetic item across boundaries");
}

template <std::size_t Capacity>
std::vector<std::uint8_t> frameBytes(
    const wire::FixedFrame<Capacity> &frame) {
  return {frame.data(), frame.data() + frame.size()};
}

wire::CommandFrame pingRequest(std::uint32_t request_id,
                               std::uint64_t nonce) {
  std::array<std::uint8_t, constants::kPingRequestPayloadSize> payload{};
  expect(wire::storeU64({payload.data(), payload.size()},
                        constants::kPingRequestNonceOffset, nonce),
         "pack a fake-USB PING request");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kPingRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode a fake-USB PING request");
  return frame;
}

wire::ControlFrame pingResponse(const wire::Request &request,
                                std::uint32_t run_id) {
  wire::ControlFrame response{};
  expect(wire::encodePingResponse(request, run_id, response).ok(),
         "encode the response for an interleaved PING");
  return response;
}

class AlternatingFakeUsb final : public usb::CdcByteStream {
 public:
  enum class WriteOutcome : std::uint8_t {
    kNone,
    kFull,
    kPartial,
    kZero,
    kRecovered,
  };

  void appendInput(const wire::CommandFrame &frame) {
    input_.insert(input_.end(), frame.data(), frame.data() + frame.size());
  }

  usb::IoCount available() override {
    const std::size_t remaining = input_.size() - input_offset_;
    return static_cast<usb::IoCount>(remaining);
  }

  usb::IoCount read(std::uint8_t *destination,
                    std::size_t capacity) override {
    static constexpr std::array<std::size_t, 9U> kReadChunks{
        1U, 17U, 3U, 61U, 7U, 29U, 2U, 47U, 11U,
    };
    const std::size_t remaining = input_.size() - input_offset_;
    const std::size_t planned = kReadChunks[read_index_ % kReadChunks.size()];
    ++read_index_;
    const std::size_t count = std::min(std::min(capacity, planned), remaining);
    std::copy_n(input_.data() + input_offset_, count, destination);
    input_offset_ += count;
    read_chunks.push_back(count);
    return static_cast<usb::IoCount>(count);
  }

  usb::IoCount availableForWrite() override {
    return static_cast<usb::IoCount>(board::kUsbTxMaxWriteBytes);
  }

  usb::IoCount write(const std::uint8_t *source, std::size_t size) override {
    write_requests.push_back(size);
    const std::size_t phase = write_index_ % 4U;
    ++write_index_;
    if (phase == 2U) {
      last_write_outcome = WriteOutcome::kZero;
      ++zero_writes;
      return 0;
    }

    std::size_t accepted = size;
    if (phase == 1U) {
      accepted = std::min<std::size_t>(size, 37U);
      if (accepted < size) {
        last_write_outcome = WriteOutcome::kPartial;
        ++partial_writes;
      } else {
        last_write_outcome = WriteOutcome::kFull;
        ++full_writes;
      }
    } else if (phase == 3U) {
      last_write_outcome = WriteOutcome::kRecovered;
      ++recovered_writes;
    } else {
      last_write_outcome = WriteOutcome::kFull;
      ++full_writes;
    }
    output.insert(output.end(), source, source + accepted);
    accepted_chunks.push_back(accepted);
    return static_cast<usb::IoCount>(accepted);
  }

  bool inputEmpty() const { return input_offset_ == input_.size(); }

  WriteOutcome last_write_outcome = WriteOutcome::kNone;
  std::size_t full_writes = 0U;
  std::size_t partial_writes = 0U;
  std::size_t zero_writes = 0U;
  std::size_t recovered_writes = 0U;
  std::vector<std::size_t> read_chunks{};
  std::vector<std::size_t> write_requests{};
  std::vector<std::size_t> accepted_chunks{};
  std::vector<std::uint8_t> output{};

 private:
  std::vector<std::uint8_t> input_{};
  std::size_t input_offset_ = 0U;
  std::size_t read_index_ = 0U;
  std::size_t write_index_ = 0U;
};

struct ExpectedPing {
  std::uint32_t request_id = 0U;
  std::uint64_t nonce = 0U;
};

bool settled(const packet::PacketBufferPipeline &pipeline,
             const usb::CdcTransport &transport,
             const AlternatingFakeUsb &stream) {
  const usb::TransportSnapshot snapshot = transport.snapshot();
  return pipeline.readyFrames() == 0U && pipeline.queuedFrames() == 0U &&
         !transport.hasPendingTransmission() && stream.inputEmpty() &&
         snapshot.pending_rx_bytes == 0U &&
         snapshot.command_queue_depth == 0U &&
         snapshot.response_queue_depth == 0U &&
         !snapshot.command_awaiting_response;
}

void serviceIoOnce(packet::PacketBufferPipeline &pipeline,
                   usb::CdcTransport &transport,
                   AlternatingFakeUsb &stream, std::uint32_t run_id,
                   bool &saw_zero_continuation) {
  const packet::PromotionReport promoted = pipeline.serviceReadyFrames();
  expect(!promoted.invariant_error,
         "cooperative promotion preserves packet ownership invariants");
  (void)transport.serviceReceive();
  wire::ParsedCommand command{};
  if (transport.takeCommand(command)) {
    expect(command.request.kind == constants::CommandKind::kPing,
           "only deterministic PING commands enter the stress transport");
    expect(transport.queueResponse(pingResponse(command.request, run_id)),
           "each accepted command reserves and queues one response");
  }
  const usb::ServiceReport transmitted = transport.serviceTransmit();
  if (transmitted.stalled &&
      stream.last_write_outcome ==
          AlternatingFakeUsb::WriteOutcome::kZero) {
    const usb::TransportSnapshot snapshot = transport.snapshot();
    saw_zero_continuation =
        saw_zero_continuation ||
        (snapshot.active_frame_size > snapshot.active_frame_bytes_sent &&
         snapshot.active_frame_bytes_sent > 0U);
  }
}

void drainIo(packet::PacketBufferPipeline &pipeline,
             usb::CdcTransport &transport, AlternatingFakeUsb &stream,
             std::uint32_t run_id, bool &saw_zero_continuation) {
  constexpr std::size_t kMaximumVisits = 20000U;
  for (std::size_t visit = 0U; visit < kMaximumVisits; ++visit) {
    if (settled(pipeline, transport, stream)) {
      return;
    }
    serviceIoOnce(pipeline, transport, stream, run_id,
                  saw_zero_continuation);
  }
  expect(false, "bounded cooperative visits drain fake USB and packet queues");
}

void startOneDataFrame(packet::PacketBufferPipeline &pipeline,
                       usb::CdcTransport &transport,
                       AlternatingFakeUsb &stream,
                       std::uint32_t run_id,
                       bool &saw_zero_continuation) {
  (void)pipeline.serviceReadyFrames();
  for (std::size_t visit = 0U; visit < 4U; ++visit) {
    const usb::TransportSnapshot before = transport.snapshot();
    if (before.active_frame_size > before.active_frame_bytes_sent &&
        before.active_frame_bytes_sent > 0U) {
      return;
    }
    serviceIoOnce(pipeline, transport, stream, run_id,
                  saw_zero_continuation);
  }
  const usb::TransportSnapshot after = transport.snapshot();
  expect(after.active_frame_size > after.active_frame_bytes_sent &&
             after.active_frame_bytes_sent > 0U &&
             !after.active_frame_is_response,
         "data owns the wire before a concurrent command arrives");
}

void appendDuePings(AlternatingFakeUsb &stream,
                    std::vector<ExpectedPing> &expected,
                    std::uint64_t completed_frames) {
  constexpr std::size_t kPingCount = 6U;
  const std::size_t due = std::min<std::size_t>(
      kPingCount, static_cast<std::size_t>(completed_frames / 4U));
  while (expected.size() < due) {
    const std::uint32_t ordinal =
        static_cast<std::uint32_t>(expected.size());
    const ExpectedPing ping{
        static_cast<std::uint32_t>(700U + ordinal),
        0xA5A5000000000000ULL + static_cast<std::uint64_t>(ordinal),
    };
    stream.appendInput(pingRequest(ping.request_id, ping.nonce));
    expected.push_back(ping);
  }
}

void validateWireOutput(const std::vector<std::uint8_t> &output,
                        std::uint32_t run_id,
                        std::uint64_t frames_per_stream,
                        const std::vector<ExpectedPing> &expected_pings,
                        const std::string &mode_name) {
  std::array<std::uint64_t, packet::kStreamCount> data_frames{};
  std::size_t response_index = 0U;
  std::size_t offset = 0U;
  while (offset < output.size()) {
    const wire::ByteView remaining{output.data() + offset,
                                   output.size() - offset};
    std::uint32_t frame_size = 0U;
    if (!wire::loadU32(remaining, constants::kHeaderTotalLengthOffset,
                       frame_size) ||
        frame_size < constants::kMinFrameBytes || frame_size > remaining.size) {
      expect(false, mode_name + " output has a complete next frame");
      break;
    }
    wire::DecodedFrame decoded{};
    expect(wire::decodeFrame(
               {remaining.data, static_cast<std::size_t>(frame_size)}, decoded)
               .ok(),
           mode_name + " output validates checksum after unequal USB chunks");
    if (decoded.header.kind == constants::FrameKind::kAdcData ||
        decoded.header.kind == constants::FrameKind::kGpioData) {
      const packet::Stream stream =
          decoded.header.kind == constants::FrameKind::kAdcData
              ? packet::Stream::kAdc
              : packet::Stream::kGpio;
      const std::size_t stream_index = packet::streamIndex(stream);
      const std::uint64_t logical_frame = data_frames[stream_index]++;
      expectSyntheticFrame(decoded, stream, run_id,
                           static_cast<std::uint32_t>(logical_frame),
                           logical_frame, mode_name + " data frame");
    } else if (decoded.header.kind ==
               constants::FrameKind::kPingResponse) {
      expect(response_index < expected_pings.size(),
             mode_name + " emits no unexpected command response");
      if (response_index < expected_pings.size()) {
        std::uint64_t nonce = 0U;
        const ExpectedPing expected = expected_pings[response_index];
        expect(decoded.header.request_id == expected.request_id &&
                   decoded.header.run_id == run_id &&
                   wire::loadU64(decoded.payload,
                                 constants::kPingResponseNonceOffset, nonce) &&
                   nonce == expected.nonce,
               mode_name + " preserves concurrent command response order");
      }
      ++response_index;
    } else {
      expect(false, mode_name + " output contains only data and PING frames");
    }
    offset += static_cast<std::size_t>(frame_size);
  }

  expect(offset == output.size(), mode_name + " output has no trailing bytes");
  expect(data_frames[packet::streamIndex(packet::Stream::kAdc)] ==
             frames_per_stream &&
             data_frames[packet::streamIndex(packet::Stream::kGpio)] ==
                 frames_per_stream,
         mode_name + " transmits every expected ADC and GPIO frame");
  expect(response_index == expected_pings.size(),
         mode_name + " transmits every interleaved command response");
}

void testOwnershipTransitionsStopAndStaleHandles() {
  static_assert(sizeof(packet::PacketBufferStorage) ==
                board::kPacketBufferStorageBytes);
  static_assert(alignof(packet::PacketBufferStorage) ==
                board::kCacheLineBytes);
  static_assert(sizeof(packet::PacketBufferPipeline) <=
                board::kPacketPipelineStateBudgetBytes);

  packet::PacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(snapshot.buffers_by_state[stateIndex(packet::BufferState::kFree)] ==
             board::kPacketBufferCount &&
             snapshot.ready_for_start,
         "the fixed pool begins entirely FREE");
  expect(pipeline.startRun(1U) == packet::OperationStatus::kOk,
         "start the ownership-transition run");

  const packet::BeginFillResult begun = pipeline.beginFill(packet::Stream::kAdc);
  expect(begun.ok(), "FREE transitions to FILLING");
  snapshot = pipeline.snapshot();
  expect(snapshot.buffers_by_state[stateIndex(packet::BufferState::kFilling)] ==
             1U &&
             snapshot.buffers_by_state[stateIndex(packet::BufferState::kFree)] ==
                 board::kPacketBufferCount - 1U,
         "FILLING has exclusive mutable ownership");
  wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  fillSyntheticPayload(packet::Stream::kAdc, payload, 0U);
  packet::FrameCompletion completion{};
  completion.flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kSynthetic) |
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart));
  completion.payload_bytes_written = payload.size;
  expect(pipeline.finishFill(begun.handle, completion).ok(),
         "FILLING transitions to checksummed READY");
  snapshot = pipeline.snapshot();
  expect(snapshot.buffers_by_state[stateIndex(packet::BufferState::kReady)] ==
             1U &&
             snapshot.ready_queue_depth == 1U,
         "READY ownership is represented by one bounded queue entry");
  expect(pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "READY transitions to TRANSMITTING");
  snapshot = pipeline.snapshot();
  expect(snapshot.buffers_by_state[
             stateIndex(packet::BufferState::kTransmitting)] == 1U &&
             snapshot.transmit_queue_depth == 1U,
         "TRANSMITTING keeps a complete immutable frame");
  pipeline.releaseFrontFrame();
  snapshot = pipeline.snapshot();
  expect(snapshot.buffers_by_state[stateIndex(packet::BufferState::kFree)] ==
             board::kPacketBufferCount &&
             pipeline.quiescent(),
         "final-byte completion transitions TRANSMITTING back to FREE");
  (void)pipeline.stopProduction();

  expect(pipeline.startRun(2U) == packet::OperationStatus::kOk,
         "start a STOP cleanup run");
  const packet::BeginFillResult canceled =
      pipeline.beginFill(packet::Stream::kAdc);
  expect(canceled.ok(), "hold one producer-owned FILLING frame");
  (void)fillCompleteFrame(pipeline, packet::Stream::kGpio, 0U, 0U);
  (void)fillCompleteFrame(pipeline, packet::Stream::kAdc,
                          synthetic::kFrameCoverageTicks,
                          constants::kAdcPairsPerFrame);
  expect(pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "create simultaneous FILLING, READY, and TRANSMITTING ownership");
  snapshot = pipeline.snapshot();
  expect(snapshot.buffers_by_state[stateIndex(packet::BufferState::kFilling)] ==
             1U &&
             snapshot.buffers_by_state[stateIndex(packet::BufferState::kReady)] ==
                 1U &&
             snapshot.buffers_by_state[
                 stateIndex(packet::BufferState::kTransmitting)] == 1U,
         "all non-free ownership states coexist without aliasing");
  const packet::StopReport stopped = pipeline.stopProduction();
  expect(stopped.filling_frames_canceled == 1U &&
             stopped.ready_frames_to_drain == 1U &&
             stopped.transmitting_frames_to_drain == 1U &&
             pipeline.startRun(3U) ==
                 packet::OperationStatus::kTransmissionPending,
         "STOP cancels only FILLING and gates reset behind complete frames");
  expect(!pipeline.cancelFill(canceled.handle),
         "a STOP-canceled lease is immediately stale");
  expect(pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "STOP-preserved READY work enters the normal drain");
  pipeline.releaseFrontFrame();
  pipeline.releaseFrontFrame();
  expect(pipeline.readyForStart() &&
             pipeline.startRun(3U) == packet::OperationStatus::kOk,
         "a new run resets queues only after the old drain is quiescent");

  const packet::BeginFillResult fresh =
      pipeline.beginFill(packet::Stream::kGpio);
  expect(fresh.ok(), "new-run FILLING receives a fresh lease");
  const packet::FinishFillResult stale =
      pipeline.finishFill(canceled.handle, completion);
  snapshot = pipeline.snapshot();
  expect(stale.status == packet::OperationStatus::kInvalidHandle &&
             snapshot.buffers_by_state[stateIndex(packet::BufferState::kFilling)] ==
                 1U &&
             snapshot.run_id == 3U,
         "a stale prior-run handle cannot mutate new-run ownership");
  payload = pipeline.writablePayload(fresh.handle);
  fillSyntheticPayload(packet::Stream::kGpio, payload, 0U);
  completion.flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kSynthetic) |
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart));
  completion.payload_bytes_written = payload.size;
  expect(pipeline.finishFill(fresh.handle, completion).ok() &&
             pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "fresh new-run work completes after stale-run rejection");
  const wire::DecodedFrame new_run =
      decodeFront(pipeline, "new-run frame after stale-handle rejection");
  expect(new_run.header.run_id == 3U,
         "no stopped-run identity can leak after a successful reset");
  pipeline.releaseFrontFrame();
  (void)pipeline.stopProduction();
}

void testFixedQueueAndPipelineWraparound() {
  usb::detail::FixedQueue<std::uint32_t, 3U> queue{};
  static_assert(decltype(queue)::capacity() == 3U);
  std::uint32_t item = 99U;
  expect(queue.empty() && queue.front() == nullptr && !queue.pop(item) &&
             item == 99U,
         "fixed queue rejects empty underflow without output mutation");
  expect(queue.push(1U) && queue.push(2U) && queue.push(3U) && queue.full() &&
             !queue.push(4U),
         "fixed queue accepts exactly its compile-time capacity");
  expect(queue.pop(item) && item == 1U && queue.push(4U) &&
             queue.pop(item) && item == 2U && queue.pop(item) && item == 3U &&
             queue.pop(item) && item == 4U && queue.empty() &&
             !queue.popFront(),
         "fixed queue preserves FIFO order through tail/head wraparound");

  packet::PacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.frontFrame().size == 0U && pipeline.readyFrames() == 0U &&
             pipeline.queuedFrames() == 0U &&
             pipeline.startRun(11U) == packet::OperationStatus::kOk,
         "pipeline queue fronts begin empty");
  for (std::uint32_t sequence = 0U;
       sequence < static_cast<std::uint32_t>(board::kPacketBufferCount);
       ++sequence) {
    (void)fillCompleteFrame(
        pipeline, packet::Stream::kAdc,
        static_cast<std::uint64_t>(sequence) * synthetic::kFrameCoverageTicks,
        static_cast<std::uint64_t>(sequence) * constants::kAdcPairsPerFrame);
  }
  packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(pipeline.freeBuffers() == 0U &&
             snapshot.ready_depth_by_source[0] ==
                 board::kPacketReadyQueueDepth &&
             snapshot.ready_queue_high_water == board::kPacketBufferCount,
         "the per-source READY ring reaches its exact fixed full edge");

  constexpr std::size_t kFirstDrain = board::kPacketBufferCount / 2U;
  expect(pipeline.serviceReadyFrames(kFirstDrain).frames_promoted ==
             kFirstDrain,
         "move half the full READY ring into transport ownership");
  for (std::uint32_t expected_sequence = 0U;
       expected_sequence < static_cast<std::uint32_t>(kFirstDrain);
       ++expected_sequence) {
    const wire::DecodedFrame frame = decodeFront(pipeline, "first ring lap");
    expect(frame.header.sequence == expected_sequence,
           "first ring lap preserves FIFO sequence");
    pipeline.releaseFrontFrame();
  }
  for (std::uint32_t sequence =
           static_cast<std::uint32_t>(board::kPacketBufferCount);
       sequence < static_cast<std::uint32_t>(board::kPacketBufferCount +
                                             kFirstDrain);
       ++sequence) {
    (void)fillCompleteFrame(
        pipeline, packet::Stream::kAdc,
        static_cast<std::uint64_t>(sequence) * synthetic::kFrameCoverageTicks,
        static_cast<std::uint64_t>(sequence) * constants::kAdcPairsPerFrame);
  }
  snapshot = pipeline.snapshot();
  expect(snapshot.ready_depth_by_source[0] ==
             board::kPacketReadyQueueDepth,
         "READY tail wraps and refills every released slot");
  expect(pipeline.serviceReadyFrames(board::kPacketTransmitQueueDepth)
                 .frames_promoted == board::kPacketTransmitQueueDepth &&
             pipeline.serviceReadyFrames(1U).transmit_queue_full,
         "TRANSMIT ring reaches and reports its exact full edge after wrap");
  for (std::uint32_t expected_sequence =
           static_cast<std::uint32_t>(kFirstDrain);
       expected_sequence <
       static_cast<std::uint32_t>(board::kPacketBufferCount + kFirstDrain);
       ++expected_sequence) {
    const wire::DecodedFrame frame = decodeFront(pipeline, "wrapped ring lap");
    expect(frame.header.sequence == expected_sequence,
           "wrapped READY and TRANSMIT rings retain FIFO sequence");
    pipeline.releaseFrontFrame();
  }
  snapshot = pipeline.snapshot();
  expect(pipeline.frontFrame().size == 0U && pipeline.queuedFrames() == 0U &&
             pipeline.readyFrames() == 0U &&
             snapshot.transmit_queue_high_water ==
                 board::kPacketTransmitQueueDepth &&
             snapshot.buffers_by_state[stateIndex(packet::BufferState::kFree)] ==
                 board::kPacketBufferCount,
         "wrapped queue drain returns the entire pool to FREE");
  (void)pipeline.stopProduction();
}

void testFairSchedulingWithUnequalArrivals() {
  packet::PacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(21U) == packet::OperationStatus::kOk,
         "start an unequal-arrival scheduling run");
  for (std::uint32_t sequence = 0U; sequence < 6U; ++sequence) {
    (void)fillCompleteFrame(
        pipeline, packet::Stream::kAdc,
        static_cast<std::uint64_t>(sequence) * synthetic::kFrameCoverageTicks,
        static_cast<std::uint64_t>(sequence) * constants::kAdcPairsPerFrame);
  }
  for (std::uint32_t sequence = 0U; sequence < 3U; ++sequence) {
    (void)fillCompleteFrame(
        pipeline, packet::Stream::kGpio,
        static_cast<std::uint64_t>(sequence) * synthetic::kFrameCoverageTicks,
        static_cast<std::uint64_t>(sequence) * constants::kGpioSamplesPerFrame);
  }
  expect(pipeline.serviceReadyFrames(9U).frames_promoted == 9U,
         "promote all unequal arrivals without starving either source");
  const std::array<constants::FrameKind, 9U> expected{
      constants::FrameKind::kAdcData,  constants::FrameKind::kGpioData,
      constants::FrameKind::kAdcData,  constants::FrameKind::kGpioData,
      constants::FrameKind::kAdcData,  constants::FrameKind::kGpioData,
      constants::FrameKind::kAdcData,  constants::FrameKind::kAdcData,
      constants::FrameKind::kAdcData,
  };
  std::array<std::uint32_t, packet::kStreamCount> sequences{};
  for (constants::FrameKind kind : expected) {
    const wire::DecodedFrame frame = decodeFront(pipeline, "fair queue frame");
    const packet::Stream stream =
        kind == constants::FrameKind::kAdcData ? packet::Stream::kAdc
                                               : packet::Stream::kGpio;
    const std::size_t index = packet::streamIndex(stream);
    expect(frame.header.kind == kind &&
               frame.header.sequence == sequences[index]++,
           "scheduler alternates while both sources are ready, then drains");
    pipeline.releaseFrontFrame();
  }
  expect(sequences[0] == 6U && sequences[1] == 3U,
         "unequal ready depths retain independent source sequences");
  (void)pipeline.stopProduction();
}

void testSequenceWrapAndPacingBoundaries() {
  packet::PacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  synthetic::SyntheticSource source{};
  constexpr std::uint32_t run_id = 31U;
  constexpr std::uint64_t epoch = 0x123456789ABC0000ULL;
  constexpr std::uint32_t near_wrap =
      std::numeric_limits<std::uint32_t>::max() - 1U;
  expect(pipeline.startRun(run_id) == packet::OperationStatus::kOk,
         "start the sequence-wrap run");
  expect(source.startRun(run_id, bothStreams(), epoch, pipeline) ==
             synthetic::OperationStatus::kOk,
         "arm both paced sources beside the 32-bit sequence boundary");
  expect(source.service(epoch + synthetic::kFrameCoverageTicks, pipeline)
                 .frames_generated == 2U &&
             pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "emit each stream's required sequence-zero epoch frame");
  for (packet::Stream stream : {packet::Stream::kAdc,
                                packet::Stream::kGpio}) {
    const wire::DecodedFrame epoch_frame =
        decodeFront(pipeline, "sequence-wrap epoch frame");
    expectSyntheticFrame(epoch_frame, stream, run_id, 0U, 0U,
                         "sequence-wrap epoch frame");
    pipeline.releaseFrontFrame();
  }
  packet::PacketBufferPipelineTestAccess::setNextSequence(
      pipeline, packet::Stream::kAdc, near_wrap);
  packet::PacketBufferPipelineTestAccess::setNextSequence(
      pipeline, packet::Stream::kGpio, near_wrap);
  expect(source.service(epoch + 4U * synthetic::kFrameCoverageTicks, pipeline)
                 .frames_generated == board::kSyntheticFramesPerLoop &&
             source.service(epoch + 4U * synthetic::kFrameCoverageTicks,
                            pipeline)
                     .frames_generated == 2U,
         "real-time catch-up remains bounded across an unequal three-frame deadline");
  expect(pipeline.serviceReadyFrames(6U).frames_promoted == 6U,
         "promote all sequence-wrap frames fairly");
  const std::array<std::uint32_t, 3U> expected_sequences{
      near_wrap, std::numeric_limits<std::uint32_t>::max(), 0U,
  };
  std::array<std::size_t, packet::kStreamCount> seen{};
  for (std::size_t index = 0U; index < 6U; ++index) {
    const packet::Stream stream =
        index % 2U == 0U ? packet::Stream::kAdc : packet::Stream::kGpio;
    const std::size_t stream_index = packet::streamIndex(stream);
    const wire::DecodedFrame frame = decodeFront(pipeline, "sequence-wrap frame");
    expectSyntheticFrame(frame, stream, run_id,
                         expected_sequences[seen[stream_index]],
                         static_cast<std::uint64_t>(seen[stream_index] + 1U),
                         "sequence-wrap frame");
    ++seen[stream_index];
    pipeline.releaseFrontFrame();
  }
  const packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(snapshot.sources[0].next_sequence == 1U &&
             snapshot.sources[1].next_sequence == 1U,
         "independent packet sequences wrap modulo 2^32");
  source.stop();
  (void)pipeline.stopProduction();
}

void runLongModeTest(synthetic::Mode mode, std::uint32_t run_id,
                     const std::string &mode_name) {
  constexpr std::uint64_t kFramesPerStream = 24U;
  constexpr std::uint64_t epoch = 5000000000ULL;
  packet::PacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  synthetic::SyntheticSource source{mode};
  AlternatingFakeUsb stream{};
  stats::Statistics statistics{};
  usb::CdcTransport transport{stream, statistics, &pipeline};
  std::vector<ExpectedPing> expected_pings{};
  bool saw_zero_continuation = false;
  std::size_t commands_while_data_active = 0U;

  expect(pipeline.startRun(run_id) == packet::OperationStatus::kOk &&
             source.startRun(run_id, bothStreams(), epoch, pipeline) ==
                 synthetic::OperationStatus::kOk,
         mode_name + " starts through the real fixed packet pipeline");

  if (mode == synthetic::Mode::kRealtime) {
    static constexpr std::array<std::uint64_t, 8U> kDeadlineAdvances{
        1U, 3U, 2U, 5U, 1U, 4U, 3U, 2U,
    };
    std::uint64_t elapsed_frames = 0U;
    std::size_t advance_index = 0U;
    while (elapsed_frames < kFramesPerStream) {
      elapsed_frames = std::min<std::uint64_t>(
          kFramesPerStream,
          elapsed_frames +
              kDeadlineAdvances[advance_index % kDeadlineAdvances.size()]);
      ++advance_index;
      while (source.snapshot().streams[0].frames_generated < elapsed_frames) {
        const synthetic::ServiceReport report = source.service(
            epoch + elapsed_frames * synthetic::kFrameCoverageTicks, pipeline);
        expect(report.frames_generated > 0U &&
                   report.frames_generated <= board::kSyntheticFramesPerLoop &&
                   report.frames_dropped == 0U && !report.invariant_error,
               "real-time source catches up within its cooperative work bound");
        const std::uint64_t completed =
            source.snapshot().streams[0].frames_generated;
        const std::size_t ping_count_before = expected_pings.size();
        const std::size_t ping_count_due = std::min<std::size_t>(
            6U, static_cast<std::size_t>(completed / 4U));
        if (ping_count_due > ping_count_before) {
          startOneDataFrame(pipeline, transport, stream, run_id,
                            saw_zero_continuation);
          appendDuePings(stream, expected_pings, completed);
          ++commands_while_data_active;
        }
        drainIo(pipeline, transport, stream, run_id,
                saw_zero_continuation);
      }
    }
  } else {
    while (source.snapshot().streams[0].frames_generated <
           kFramesPerStream) {
      const std::uint64_t call = source.snapshot().service_calls;
      const synthetic::ServiceReport report = source.service(
          epoch + call * 137U, pipeline);
      expect(report.frames_generated == board::kSyntheticFramesPerLoop &&
                 report.frames_framed == board::kSyntheticFramesPerLoop &&
                 report.frames_dropped == 0U && !report.invariant_error,
             "unpaced mode keeps identical bounded source and framing work");
      const std::uint64_t completed =
          source.snapshot().streams[0].frames_generated;
      const std::size_t ping_count_before = expected_pings.size();
      const std::size_t ping_count_due = std::min<std::size_t>(
          6U, static_cast<std::size_t>(completed / 4U));
      if (ping_count_due > ping_count_before) {
        startOneDataFrame(pipeline, transport, stream, run_id,
                          saw_zero_continuation);
        appendDuePings(stream, expected_pings, completed);
        ++commands_while_data_active;
      }
      drainIo(pipeline, transport, stream, run_id, saw_zero_continuation);
    }
  }

  source.stop();
  const packet::StopReport stopped = pipeline.stopProduction();
  drainIo(pipeline, transport, stream, run_id, saw_zero_continuation);
  const packet::PipelineSnapshot packet_snapshot = pipeline.snapshot();
  const usb::TransportSnapshot transport_snapshot = transport.snapshot();
  expect(stopped.filling_frames_canceled == 0U &&
             stopped.ready_frames_to_drain == 0U &&
             stopped.transmitting_frames_to_drain == 0U &&
             pipeline.readyForStart(),
         mode_name + " STOP finds the fully reconciled long run quiescent");
  for (std::size_t source_index = 0U; source_index < packet::kStreamCount;
       ++source_index) {
    const packet::SourceCounters counters =
        packet_snapshot.sources[source_index];
    const packet::Stream source_stream =
        static_cast<packet::Stream>(source_index);
    const std::uint64_t expected_items =
        kFramesPerStream * packet::itemsPerFrame(source_stream);
    expect(counters.frames_produced == kFramesPerStream &&
               counters.frames_framed == kFramesPerStream &&
               counters.frames_emitted == kFramesPerStream &&
               counters.frames_transmitted == kFramesPerStream &&
               counters.frames_dropped == 0U &&
               counters.items_produced == expected_items &&
               counters.items_framed == expected_items &&
               counters.items_emitted == expected_items &&
               counters.items_transmitted == expected_items &&
               counters.items_dropped == 0U,
           mode_name + " reconciles every ownership-stage counter");
  }
  expect(expected_pings.size() == 6U && commands_while_data_active == 6U &&
             transport_snapshot.commands_queued == 6U &&
             transport_snapshot.commands_dequeued == 6U &&
             transport_snapshot.responses_completed == 6U,
         mode_name + " services commands while data frames own the wire");
  expect(stream.full_writes > 0U && stream.partial_writes > 0U &&
             stream.zero_writes > 0U && stream.recovered_writes > 0U &&
             saw_zero_continuation &&
             transport_snapshot.partial_write_events == stream.partial_writes &&
             transport_snapshot.zero_length_write_events == stream.zero_writes &&
             transport_snapshot.max_write_request_bytes ==
                 board::kUsbTxMaxWriteBytes,
         mode_name +
             " survives deterministic full/partial/zero/recovered USB writes");
  expect(stream.accepted_chunks.size() >
             static_cast<std::size_t>(2U * kFramesPerStream) &&
             std::find(stream.accepted_chunks.begin(),
                       stream.accepted_chunks.end(), 37U) !=
                 stream.accepted_chunks.end() &&
             *std::max_element(stream.read_chunks.begin(),
                               stream.read_chunks.end()) !=
                 *std::min_element(stream.read_chunks.begin(),
                                   stream.read_chunks.end()),
         mode_name + " exercises many unequal receive and transmit chunks");
  validateWireOutput(stream.output, run_id, kFramesPerStream, expected_pings,
                     mode_name);
}

void testRealtimeAndUnpacedThroughAlternatingUsb() {
  runLongModeTest(synthetic::Mode::kRealtime, 41U, "real-time");
  runLongModeTest(synthetic::Mode::kUnpacedDiagnostic, 42U,
                  "unpaced-diagnostic");
}

}  // namespace

int main() {
  testOwnershipTransitionsStopAndStaleHandles();
  testFixedQueueAndPipelineWraparound();
  testFairSchedulingWithUnequalArrivals();
  testSequenceWrapAndPacingBoundaries();
  testRealtimeAndUnpacedThroughAlternatingUsb();

  if (failures != 0) {
    std::cerr << failures << " synthetic pipeline assertion(s) failed\n";
    return 1;
  }
  std::cout << "synthetic pipeline stress tests passed\n";
  return 0;
}
