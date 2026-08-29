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

#include "control_state.h"
#include "firmware_runtime.h"
#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "statistics.h"
#include "usb_transport.h"

namespace teensy_daq::packet {

// The production pool remains fixed at its target capacity. These sentinels
// make only the first `capacity` records available so the same production
// selection/eviction code can be driven through short deterministic wraps.
// No queue or packet implementation is replaced by a test model.
struct PacketBufferPipelineTestAccess {
  static bool installLogicalCapacity(PacketBufferPipeline &pipeline,
                                     std::size_t capacity) {
    if (capacity == 0U || capacity >= pipeline.records_.size() ||
        pipeline.freeBuffers() != pipeline.records_.size()) {
      return false;
    }
    for (std::size_t index = capacity; index < pipeline.records_.size();
         ++index) {
      PacketBufferPipeline::BufferRecord &record = pipeline.records_[index];
      record = {};
      record.state = BufferState::kFilling;
      record.stream = static_cast<Stream>(0xFFU);
      record.sequence = 0x80000000UL;
      record.run_id = pipeline.run_id_;
    }
    return pipeline.freeBuffers() == capacity;
  }

  static bool logicalCapacitySentinelsIntact(
      const PacketBufferPipeline &pipeline, std::size_t capacity) {
    if (capacity == 0U || capacity >= pipeline.records_.size()) {
      return false;
    }
    for (std::size_t index = capacity; index < pipeline.records_.size();
         ++index) {
      const PacketBufferPipeline::BufferRecord &record =
          pipeline.records_[index];
      if (record.state != BufferState::kFilling ||
          validStream(record.stream) || record.sequence != 0x80000000UL ||
          record.run_id != pipeline.run_id_ || record.frame_size != 0U) {
        return false;
      }
    }
    return true;
  }

  static bool releaseLogicalCapacity(PacketBufferPipeline &pipeline,
                                     std::size_t capacity) {
    if (!logicalCapacitySentinelsIntact(pipeline, capacity)) {
      return false;
    }
    for (std::size_t index = capacity; index < pipeline.records_.size();
         ++index) {
      pipeline.records_[index] = {};
    }
    return true;
  }
};

}  // namespace teensy_daq::packet

namespace {

namespace app = teensy_daq::runtime;
namespace board = teensy_daq::board;
namespace constants = teensy_daq::protocol_v1;
namespace control = teensy_daq::control;
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

template <std::size_t Capacity>
std::vector<std::uint8_t> bytes(const wire::FixedFrame<Capacity> &frame) {
  return {frame.data(), frame.data() + frame.size()};
}

void append(std::vector<std::uint8_t> &destination,
            const std::vector<std::uint8_t> &source) {
  destination.insert(destination.end(), source.begin(), source.end());
}

wire::CommandFrame emptyRequest(constants::FrameKind kind,
                                std::uint32_t request_id) {
  wire::FrameFields fields{};
  fields.kind = kind;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {}, frame).ok(),
         "encode an empty control request");
  return frame;
}

wire::CommandFrame configureRequest(std::uint32_t request_id) {
  std::array<std::uint8_t, constants::kConfigureRequestPayloadSize> payload{};
  payload[constants::kConfigureRequestStreamMaskOffset] =
      packet::kAllStreamMask;
  payload[constants::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants::Source::kSynthetic);
  payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(constants::kDefaultChecksumAlgorithm);
  expect(wire::storeU32(
             {payload.data(), payload.size()},
             constants::kConfigureRequestDataFrameBytesOffset,
             static_cast<std::uint32_t>(constants::kDataFrameBytes)),
         "encode the synthetic combined frame size");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kConfigureRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode a synthetic combined CONFIGURE request");
  return frame;
}

wire::Request controlRequest(constants::CommandKind kind,
                             std::uint32_t request_id) {
  wire::Request request{};
  request.kind = kind;
  request.request_id = request_id;
  return request;
}

wire::Request controlConfigureRequest(std::uint32_t request_id) {
  wire::Request request =
      controlRequest(constants::CommandKind::kConfigure, request_id);
  request.configuration = control::kSyntheticConfiguration;
  return request;
}

wire::ControlFrame pingResponse(std::uint32_t request_id,
                                std::uint32_t run_id) {
  wire::Request request{};
  request.kind = constants::CommandKind::kPing;
  request.request_id = request_id;
  request.nonce = (static_cast<std::uint64_t>(request_id) << 32U) | run_id;
  wire::ControlFrame frame{};
  expect(wire::encodePingResponse(request, run_id, frame).ok(),
         "encode a boundary-priority PING response");
  return frame;
}

wire::ControlFrame statusResponse(std::uint32_t request_id,
                                  std::uint32_t run_id) {
  wire::Request request{};
  request.kind = constants::CommandKind::kGetStatus;
  request.request_id = request_id;
  wire::Configuration configuration{};
  configuration.stream_mask = packet::kAllStreamMask;
  configuration.source = constants::Source::kHardware;
  stats::Statistics statistics{};
  const wire::StatusResponse status = statistics.wireStatus(
      constants::DeviceState::kRunning, configuration);
  wire::ControlFrame frame{};
  expect(wire::encodeStatusResponse(request, run_id, status, frame).ok(),
         "encode STATUS under packet pressure");
  return frame;
}

wire::ControlFrame stopResponse(std::uint32_t request_id,
                                std::uint32_t run_id) {
  wire::Request request{};
  request.kind = constants::CommandKind::kStop;
  request.request_id = request_id;
  wire::ControlFrame frame{};
  expect(wire::encodeStopResponse(request, run_id, frame).ok(),
         "encode STOP under packet pressure");
  return frame;
}

packet::FinishFillResult fillAndFinish(
    packet::PacketBufferPipeline &pipeline, packet::Stream stream,
    std::uint64_t first_ticks, packet::FillHandle &handle) {
  const packet::BeginFillResult begun = pipeline.beginFill(stream);
  if (!begun.ok()) {
    expect(false, "reserve a packet buffer for a complete source block");
    return {};
  }
  handle = begun.handle;
  const wire::MutableByteView payload = pipeline.writablePayload(handle);
  expect(payload.valid() && payload.size == constants::kDataPayloadBytes,
         "FILLING exposes exactly one canonical payload");
  if (payload.valid()) {
    std::fill_n(payload.data, payload.size, std::uint8_t{0U});
  }
  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_ticks;
  completion.flags = handle.sequence == 0U
                         ? static_cast<std::uint16_t>(
                               constants::FrameFlag::kEpochStart)
                         : 0U;
  completion.payload_bytes_written = payload.size;
  return pipeline.finishFill(handle, completion);
}

class FakeCdcStream final : public usb::CdcByteStream {
 public:
  bool sessionOpen() const override { return session_open; }

  usb::IoCount available() override {
    const std::size_t remaining = input_.size() - input_offset_;
    const std::size_t bounded = std::min(
        remaining,
        static_cast<std::size_t>(std::numeric_limits<usb::IoCount>::max()));
    return static_cast<usb::IoCount>(bounded);
  }

  usb::IoCount read(std::uint8_t *destination,
                    std::size_t capacity) override {
    const std::size_t remaining = input_.size() - input_offset_;
    const std::size_t count =
        std::min({remaining, capacity, max_read_size});
    std::copy_n(input_.data() + input_offset_, count, destination);
    input_offset_ += count;
    return static_cast<usb::IoCount>(count);
  }

  usb::IoCount availableForWrite() override { return writable_limit; }

  usb::IoCount write(const std::uint8_t *source, std::size_t size) override {
    size = std::min(size, max_write_size);
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

  template <std::size_t Capacity>
  void appendInput(const wire::FixedFrame<Capacity> &frame) {
    input_.insert(input_.end(), frame.data(), frame.data() + frame.size());
  }

  template <std::size_t Capacity>
  void appendInputPrefix(const wire::FixedFrame<Capacity> &frame,
                         std::size_t prefix) {
    const std::size_t count = std::min(prefix, frame.size());
    input_.insert(input_.end(), frame.data(), frame.data() + count);
  }

  void appendInputBytes(const std::vector<std::uint8_t> &data) {
    append(input_, data);
  }

  bool inputEmpty() const { return input_offset_ == input_.size(); }

  bool session_open = true;
  std::size_t max_read_size =
      std::numeric_limits<std::size_t>::max();
  std::size_t max_write_size =
      std::numeric_limits<std::size_t>::max();
  usb::IoCount writable_limit =
      std::numeric_limits<usb::IoCount>::max();
  std::deque<usb::IoCount> write_plan{};
  std::vector<std::uint8_t> output{};

 private:
  std::vector<std::uint8_t> input_{};
  std::size_t input_offset_ = 0U;
};

class FakeTickClock final : public synthetic::TickClock {
 public:
  std::uint64_t nowTicks() override { return ticks; }

  std::uint64_t ticks = 0U;
};

void scheduleExactPrefix(FakeCdcStream &stream, std::size_t prefix) {
  std::size_t remaining = prefix;
  while (remaining != 0U) {
    const std::size_t chunk =
        std::min(remaining, board::kUsbTxMaxWriteBytes);
    stream.write_plan.push_back(static_cast<usb::IoCount>(chunk));
    remaining -= chunk;
  }
  stream.write_plan.push_back(0);
}

bool drainTransport(usb::CdcTransport &transport,
                    std::size_t maximum_visits = 32U) {
  for (std::size_t visit = 0U;
       visit < maximum_visits && transport.hasPendingTransmission();
       ++visit) {
    (void)transport.serviceTransmit();
  }
  return !transport.hasPendingTransmission();
}

std::vector<wire::DecodedFrame> decodeFrames(
    const std::vector<std::uint8_t> &data, const std::string &context) {
  std::vector<wire::DecodedFrame> decoded{};
  std::size_t offset = 0U;
  while (offset < data.size()) {
    std::uint32_t total_length = 0U;
    const bool length_ok =
        data.size() - offset >= constants::kHeaderSize &&
        wire::loadU32({data.data() + offset, data.size() - offset},
                      constants::kHeaderTotalLengthOffset, total_length) &&
        total_length >= constants::kMinFrameBytes &&
        total_length <= data.size() - offset;
    expect(length_ok, context + " has a bounded declared frame length");
    if (!length_ok) {
      break;
    }
    wire::DecodedFrame frame{};
    expect(wire::decodeFrame({data.data() + offset, total_length}, frame).ok(),
           context + " contains only valid checksummed frames");
    decoded.push_back(frame);
    offset += total_length;
  }
  expect(offset == data.size(), context + " ends on a frame boundary");
  return decoded;
}

constants::ErrorCode responseError(const wire::DecodedFrame &response) {
  std::uint16_t raw = static_cast<std::uint16_t>(
      constants::ErrorCode::kInternalError);
  expect(wire::loadU16(response.payload,
                       constants::kResponsePrefixErrorCodeOffset, raw),
         "decode the typed response error code");
  return static_cast<constants::ErrorCode>(raw);
}

constants::ErrorCode responseError(const wire::ControlFrame &response) {
  wire::DecodedFrame decoded{};
  expect(wire::decodeFrame(response.view(), decoded).ok(),
         "decode a control-state response");
  return responseError(decoded);
}

void testEveryPartialFrameOffsetPreservesBoundaries() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  constexpr std::uint32_t run_id = 301U;
  expect(pipeline.startRun(run_id, constants::kDefaultChecksumAlgorithm,
                           packet::kAdcStreamMask) ==
             packet::OperationStatus::kOk,
         "start exhaustive partial-offset run");

  for (std::size_t offset = 0U; offset < constants::kDataFrameBytes;
       ++offset) {
    packet::FillHandle handle{};
    expect(fillAndFinish(
               pipeline, packet::Stream::kAdc,
               static_cast<std::uint64_t>(offset) *
                   constants::kFrameCoverageTicks,
               handle)
               .ok(),
           "frame every exhaustive-offset ADC block");
    expect(pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
           "promote the exhaustive-offset ADC block");
    const wire::ByteView front = pipeline.frontFrame();
    const std::vector<std::uint8_t> expected_data(front.data,
                                                   front.data + front.size);

    FakeCdcStream stream{};
    scheduleExactPrefix(stream, offset);
    stats::Statistics statistics{};
    usb::CdcTransport transport{stream, statistics, &pipeline};
    const usb::ServiceReport stalled = transport.serviceTransmit();
    const usb::TransportSnapshot snapshot = transport.snapshot();
    expect(stalled.stalled && stalled.bytes_written == offset &&
               stream.output.size() == offset &&
               snapshot.active_frame_bytes_sent == offset &&
               pipeline.queuedFrames() == 1U,
           "fake USB stops at the requested data-frame byte offset");
    expect((offset == 0U && snapshot.active_frame_size == 0U) ||
               (offset != 0U &&
                snapshot.active_frame_size == constants::kDataFrameBytes),
           "byte zero alone determines whether the data frame is pinned");

    const wire::ControlFrame response = pingResponse(
        static_cast<std::uint32_t>(offset) + 1U, run_id);
    expect(transport.queueResponse(response),
           "queue control work behind the stalled data candidate");
    expect(drainTransport(transport),
           "bounded recovered USB service drains data and control");

    std::vector<std::uint8_t> expected{};
    if (offset == 0U) {
      expected = bytes(response);
      append(expected, expected_data);
    } else {
      expected = expected_data;
      append(expected, bytes(response));
    }
    expect(stream.output == expected,
           "no partial offset permits response/data interleaving");
    const std::vector<wire::DecodedFrame> frames =
        decodeFrames(stream.output, "exhaustive partial-offset output");
    expect(frames.size() == 2U,
           "each exhaustive offset emits exactly data plus one response");
    if (frames.size() == 2U) {
      const std::size_t data_index = offset == 0U ? 1U : 0U;
      const std::size_t response_index = offset == 0U ? 0U : 1U;
      expect(frames[data_index].header.kind ==
                     constants::FrameKind::kAdcData &&
                 frames[data_index].header.sequence ==
                     static_cast<std::uint32_t>(offset) &&
                 frames[response_index].header.kind ==
                     constants::FrameKind::kPingResponse,
             "zero-byte stalls allow priority; partial frames finish first");
    }
  }

  const packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(snapshot.sources[0].frames_produced ==
                 constants::kDataFrameBytes &&
             snapshot.sources[0].frames_transmitted ==
                 constants::kDataFrameBytes &&
             snapshot.sources[0].frames_dropped == 0U,
         "all exhaustive offsets retain exact no-loss source accounting");
  (void)pipeline.stopProduction();
  expect(pipeline.quiescent(),
         "exhaustive partial-offset run stops quiescently");
}

std::vector<std::uint32_t> expectedSurvivors(std::size_t capacity,
                                             packet::Stream stream,
                                             bool frame_pinned) {
  const std::uint32_t half = static_cast<std::uint32_t>(capacity / 2U);
  std::vector<std::uint32_t> result{};
  if (frame_pinned && stream == packet::Stream::kAdc) {
    result.push_back(0U);
  }
  const std::uint32_t first =
      frame_pinned && stream == packet::Stream::kAdc ? half + 1U : half;
  for (std::uint32_t sequence = first; sequence < 2U * half; ++sequence) {
    result.push_back(sequence);
  }
  return result;
}

void runPressureScenario(std::size_t capacity, std::size_t partial_offset,
                         std::uint32_t run_id) {
  const std::string context = "capacity=" + std::to_string(capacity) +
                              " offset=" +
                              std::to_string(partial_offset);
  expect(capacity >= 4U && capacity % 2U == 0U &&
             partial_offset < constants::kDataFrameBytes,
         context + " uses a supported deterministic scenario");
  const std::uint32_t half = static_cast<std::uint32_t>(capacity / 2U);

  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(run_id) == packet::OperationStatus::kOk,
         context + " starts a combined pressure epoch");
  expect(packet::PacketBufferPipelineTestAccess::installLogicalCapacity(
             pipeline, capacity),
         context + " installs the small test-only logical capacity");

  // Complete GPIO first at each timestamp even though fair USB service starts
  // with ADC. Incoming replacements reverse that order below.
  for (std::uint32_t sequence = 0U; sequence < half; ++sequence) {
    for (packet::Stream stream : {packet::Stream::kGpio,
                                  packet::Stream::kAdc}) {
      packet::FillHandle handle{};
      expect(fillAndFinish(
                 pipeline, stream,
                 static_cast<std::uint64_t>(sequence) *
                     constants::kFrameCoverageTicks,
                 handle)
                 .ok(),
             context + " fills the adversarial initial source pair");
    }
  }
  expect(pipeline.freeBuffers() == 0U &&
             pipeline.serviceReadyFrames(capacity).frames_promoted ==
                 capacity,
         context + " moves the complete logical pool to USB ownership");

  FakeCdcStream stream{};
  scheduleExactPrefix(stream, partial_offset);
  stats::Statistics transport_statistics{};
  usb::CdcTransport transport{stream, transport_statistics, &pipeline};
  const usb::ServiceReport stalled = transport.serviceTransmit();
  expect(stalled.stalled && stalled.bytes_written == partial_offset,
         context + " establishes the deterministic USB stall");

  const wire::ControlFrame status = statusResponse(7001U, run_id);
  const wire::ControlFrame stop = stopResponse(7002U, run_id);
  expect(transport.queueResponse(status) && transport.queueResponse(stop),
         context + " keeps STATUS and STOP admissible during pressure");

  for (std::uint32_t sequence = half; sequence < 2U * half; ++sequence) {
    for (packet::Stream source : {packet::Stream::kAdc,
                                  packet::Stream::kGpio}) {
      packet::FillHandle handle{};
      expect(fillAndFinish(
                 pipeline, source,
                 static_cast<std::uint64_t>(sequence) *
                     constants::kFrameCoverageTicks,
                 handle)
                 .ok(),
             context + " admits a newer adversarial live block");
    }
  }

  packet::PipelineSnapshot pressured = pipeline.snapshot();
  expect(pressured.pool_exhaustions == capacity &&
             pressured.pressure_evictions == capacity &&
             pressured.capacity_drops_without_evictable_frame == 0U,
         context + " evicts once per newer complete block");
  for (std::size_t source = 0U; source < packet::kStreamCount; ++source) {
    const packet::Stream stream_kind = static_cast<packet::Stream>(source);
    const packet::SourceCounters &counters = pressured.sources[source];
    expect(counters.frames_produced == 2U * half &&
               counters.frames_framed == 2U * half &&
               counters.frames_dropped == half &&
               counters.frames_evicted == half &&
               counters.frames_dropped_after_framing == half &&
               counters.items_dropped ==
                   static_cast<std::uint64_t>(half) *
                       packet::itemsPerFrame(stream_kind) &&
               pressured.source_bytes[source].payload_bytes_dropped ==
                   static_cast<std::uint64_t>(half) *
                       constants::kDataPayloadBytes &&
               pressured.source_bytes[source].framed_bytes_evicted ==
                   static_cast<std::uint64_t>(half) *
                       constants::kDataFrameBytes,
           context + " reconciles exact source blocks, items, and bytes");
  }
  const bool frame_pinned = partial_offset != 0U;
  expect(pressured.sources[0].frames_evicted_after_promotion ==
                 (frame_pinned ? half - 1U : half) &&
             pressured.sources[1].frames_evicted_after_promotion == half,
         context + " forces both READY and unsent TRANSMITTING eviction");
  expect(packet::PacketBufferPipelineTestAccess::
             logicalCapacitySentinelsIntact(pipeline, capacity),
         context + " never evicts an incomplete producer-owned sentinel");
  expect(transport.snapshot().active_frame_bytes_sent == partial_offset,
         context + " never abandons the accepted USB prefix");

  expect(packet::PacketBufferPipelineTestAccess::releaseLogicalCapacity(
             pipeline, capacity),
         context + " removes only the test capacity sentinels");
  (void)pipeline.stopProduction();
  for (std::size_t visit = 0U;
       visit < capacity + 16U &&
       (pipeline.readyFrames() != 0U || transport.hasPendingTransmission());
       ++visit) {
    (void)pipeline.serviceReadyFrames(capacity);
    (void)transport.serviceTransmit();
  }
  expect(pipeline.quiescent() && !transport.hasPendingTransmission(),
         context + " drains to a bounded quiescent STOP");

  const std::vector<wire::DecodedFrame> frames =
      decodeFrames(stream.output, context + " recovered output");
  expect(frames.size() == capacity + 2U,
         context + " emits every survivor and both control responses");
  if (frames.size() >= 3U) {
    if (frame_pinned) {
      expect(frames[0].header.kind == constants::FrameKind::kAdcData &&
                 frames[0].header.sequence == 0U &&
                 frames[1].header.kind ==
                     constants::FrameKind::kGetStatusResponse &&
                 frames[2].header.kind ==
                     constants::FrameKind::kStopResponse,
             context + " finishes the partial frame before STATUS and STOP");
    } else {
      expect(frames[0].header.kind ==
                     constants::FrameKind::kGetStatusResponse &&
                 frames[1].header.kind ==
                     constants::FrameKind::kStopResponse,
             context + " lets STATUS and STOP overtake an unsent data frame");
    }
  }

  std::array<std::vector<std::uint32_t>, packet::kStreamCount> sequences{};
  std::array<std::uint32_t, packet::kStreamCount> expected_sequence{};
  std::array<std::uint64_t, packet::kStreamCount> expected_ticks{};
  std::array<std::uint32_t, packet::kStreamCount> sequence_loss{};
  std::array<std::uint32_t, packet::kStreamCount> timestamp_loss{};
  std::array<std::size_t, packet::kStreamCount> gap_markers{};
  const std::uint16_t required_gap = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore));

  for (const wire::DecodedFrame &frame : frames) {
    if (frame.header.kind != constants::FrameKind::kAdcData &&
        frame.header.kind != constants::FrameKind::kGpioData) {
      continue;
    }
    const std::size_t source =
        frame.header.kind == constants::FrameKind::kAdcData ? 0U : 1U;
    const std::uint32_t missing =
        frame.header.sequence - expected_sequence[source];
    expect(frame.header.first_sample_ticks >= expected_ticks[source],
           context + " retains monotonic source timestamps");
    const std::uint64_t tick_delta =
        frame.header.first_sample_ticks - expected_ticks[source];
    expect(tick_delta % constants::kFrameCoverageTicks == 0U,
           context + " gaps cover whole canonical source frames");
    const std::uint64_t tick_frames =
        tick_delta / constants::kFrameCoverageTicks;
    expect(tick_frames == missing,
           context + " sequence and timestamp infer identical loss");
    sequence_loss[source] += missing;
    timestamp_loss[source] += static_cast<std::uint32_t>(tick_frames);
    const bool marked = (frame.header.flags & required_gap) == required_gap;
    expect(marked == (missing != 0U),
           context + " marks exactly the chronological gap successor");
    if (marked) {
      ++gap_markers[source];
    }
    expected_sequence[source] = frame.header.sequence + 1U;
    expected_ticks[source] =
        frame.header.first_sample_ticks + constants::kFrameCoverageTicks;
    sequences[source].push_back(frame.header.sequence);
  }

  expect(sequences[0] == expectedSurvivors(capacity, packet::Stream::kAdc,
                                           frame_pinned) &&
             sequences[1] ==
                 expectedSurvivors(capacity, packet::Stream::kGpio,
                                   frame_pinned),
         context + " retains only the pinned frame and newest live coverage");
  expect(sequence_loss[0] == half && sequence_loss[1] == half &&
             timestamp_loss == sequence_loss && gap_markers[0] == 1U &&
             gap_markers[1] == 1U,
         context + " reconciles flags, sequence gaps, and timestamp gaps");

  pressured = pipeline.snapshot();
  for (std::size_t source = 0U; source < packet::kStreamCount; ++source) {
    const packet::Stream stream_kind = static_cast<packet::Stream>(source);
    const packet::SourceCounters &counters = pressured.sources[source];
    expect(counters.frames_produced ==
                   counters.frames_transmitted + counters.frames_dropped &&
               counters.frames_transmitted == half &&
               counters.frames_dropped == half &&
               counters.items_transmitted ==
                   static_cast<std::uint64_t>(half) *
                       packet::itemsPerFrame(stream_kind),
           context + " closes the final per-source conservation equation");
  }
}

void testSmallCapacityPressureMatrix() {
  constexpr std::array<std::size_t, 3U> capacities{4U, 6U, 8U};
  constexpr std::array<std::size_t, 4U> offsets{0U, 1U, 2047U, 4095U};
  std::uint32_t run_id = 400U;
  for (const std::size_t capacity : capacities) {
    for (const std::size_t offset : offsets) {
      runPressureScenario(capacity, offset, ++run_id);
    }
  }
}

void testPoolWithOnlyFillingOwnersCannotEvict() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(501U) == packet::OperationStatus::kOk &&
             packet::PacketBufferPipelineTestAccess::installLogicalCapacity(
                 pipeline, 3U),
         "start a three-buffer no-complete-owner scenario");
  std::array<packet::FillHandle, 3U> handles{};
  for (std::size_t index = 0U; index < handles.size(); ++index) {
    const packet::BeginFillResult begun = pipeline.beginFill(
        index % 2U == 0U ? packet::Stream::kAdc : packet::Stream::kGpio);
    expect(begun.ok(), "reserve each logical buffer without finishing it");
    handles[index] = begun.handle;
  }
  const packet::BeginFillResult rejected =
      pipeline.beginFill(packet::Stream::kGpio);
  const packet::PipelineSnapshot full = pipeline.snapshot();
  expect(rejected.status == packet::OperationStatus::kPoolExhausted &&
             full.pool_exhaustions == 1U &&
             full.pressure_evictions == 0U &&
             full.capacity_drops_without_evictable_frame == 1U,
         "a pool of only incomplete owners reports loss without eviction");
  for (const packet::FillHandle &handle : handles) {
    expect(pipeline.writablePayload(handle).valid() &&
               pipeline.cancelFill(handle),
           "every producer-owned partial buffer survives pool pressure");
  }
  expect(packet::PacketBufferPipelineTestAccess::releaseLogicalCapacity(
             pipeline, 3U),
         "release no-complete-owner capacity sentinels");
  (void)pipeline.stopProduction();
  expect(pipeline.quiescent(),
         "no-complete-owner scenario stops without stranded ownership");
}

template <std::size_t Capacity>
bool stressFixedQueue(std::uint32_t seed) {
  usb::detail::FixedQueue<std::uint32_t, Capacity> queue{};
  std::deque<std::uint32_t> oracle{};
  std::uint32_t next_value = 1U;
  bool ok = true;
  for (std::size_t step = 0U; step < 50000U; ++step) {
    seed = seed * std::uint32_t{1664525U} + std::uint32_t{1013904223U};
    switch ((seed >> 29U) & 3U) {
      case 0U: {
        const bool expected_push = oracle.size() < Capacity;
        const bool pushed = queue.push(next_value);
        ok = ok && pushed == expected_push;
        if (expected_push) {
          oracle.push_back(next_value);
          ++next_value;
        }
        break;
      }
      case 1U: {
        std::uint32_t actual = 0U;
        const bool popped = queue.pop(actual);
        const bool expected_pop = !oracle.empty();
        ok = ok && popped == expected_pop;
        if (expected_pop) {
          ok = ok && actual == oracle.front();
          oracle.pop_front();
        }
        break;
      }
      case 2U: {
        const bool choose_present = !oracle.empty() && (seed & 1U) != 0U;
        std::uint32_t target = std::numeric_limits<std::uint32_t>::max();
        std::size_t index = 0U;
        if (choose_present) {
          index = static_cast<std::size_t>(seed) % oracle.size();
          target = oracle[index];
        }
        const bool erased = queue.eraseFirst(target);
        ok = ok && erased == choose_present;
        if (choose_present) {
          oracle.erase(oracle.begin() + static_cast<std::ptrdiff_t>(index));
        }
        break;
      }
      default:
        ok = ok && queue.size() == oracle.size() &&
             queue.empty() == oracle.empty() &&
             queue.full() == (oracle.size() == Capacity);
        if (!oracle.empty()) {
          ok = ok && queue.front() != nullptr &&
               *queue.front() == oracle.front();
        }
        break;
    }
    ok = ok && queue.size() == oracle.size();
  }
  while (!oracle.empty()) {
    std::uint32_t actual = 0U;
    ok = ok && queue.pop(actual) && actual == oracle.front();
    oracle.pop_front();
  }
  return ok && queue.empty() && queue.front() == nullptr;
}

void testFixedQueueLongWrapStress() {
  expect(stressFixedQueue<2U>(0x12345678UL) &&
             stressFixedQueue<3U>(0x23456789UL) &&
             stressFixedQueue<5U>(0x3456789AUL) &&
             stressFixedQueue<7U>(0x456789ABUL),
         "50,000-step small-capacity queues match the wrap/erase oracle");
}

void storeU32(std::vector<std::uint8_t> &frame, std::size_t offset,
              std::uint32_t value) {
  expect(wire::storeU32({frame.data(), frame.size()}, offset, value),
         "mutate a test command u32 field");
}

void refreshBootstrapChecksum(std::vector<std::uint8_t> &frame) {
  std::uint32_t checksum = 0U;
  expect(frame.size() >= constants::kTrailerSize &&
             wire::computeChecksum(
                 constants::kBootstrapChecksumAlgorithm,
                 {frame.data(), frame.size() - constants::kTrailerSize},
                 checksum)
                 .ok() &&
             wire::storeU32({frame.data(), frame.size()},
                            frame.size() - constants::kTrailerSize,
                            checksum),
         "refresh a deliberately mutated command checksum");
}

std::vector<wire::ParsedCommand> feedParser(
    wire::IncrementalCommandParser &parser,
    const std::vector<std::uint8_t> &input) {
  std::vector<wire::ParsedCommand> results{};
  std::size_t offset = 0U;
  while (offset < input.size()) {
    const std::size_t chunk =
        std::min<std::size_t>(1U + ((offset * 17U) % 23U),
                              input.size() - offset);
    wire::ParsedCommand command{};
    const wire::FeedResult fed =
        parser.feed({input.data() + offset, chunk}, command);
    expect(fed.consumed != 0U && fed.consumed <= chunk,
           "incremental parser makes bounded forward progress");
    if (fed.consumed == 0U || fed.consumed > chunk) {
      break;
    }
    offset += fed.consumed;
    if (fed.command_ready || fed.rejection_ready) {
      results.push_back(command);
    }
  }
  return results;
}

void testGarbageAndCorruptParserRecovery() {
  const wire::CommandFrame info =
      emptyRequest(constants::FrameKind::kInfoRequest, 9001U);
  const wire::CommandFrame status =
      emptyRequest(constants::FrameKind::kGetStatusRequest, 9002U);
  const wire::CommandFrame truncated_info =
      emptyRequest(constants::FrameKind::kInfoRequest, 9003U);

  std::vector<std::uint8_t> bad_checksum = bytes(info);
  bad_checksum.back() ^= 0x80U;
  std::vector<std::uint8_t> oversized = bytes(info);
  storeU32(oversized, constants::kHeaderTotalLengthOffset,
           static_cast<std::uint32_t>(constants::kMaxCommandFrameBytes + 1U));
  std::vector<std::uint8_t> bad_version = bytes(info);
  bad_version[constants::kHeaderVersionOffset] =
      static_cast<std::uint8_t>(constants::kProtocolVersion + 1U);
  std::vector<std::uint8_t> bad_kind = bytes(info);
  bad_kind[constants::kHeaderKindOffset] = 0x7FU;
  std::vector<std::uint8_t> bad_flags = bytes(info);
  bad_flags[constants::kHeaderFlagsOffset] = 1U;
  std::vector<std::uint8_t> bad_reserved = bytes(info);
  bad_reserved[constants::kHeaderReservedOffset] = 1U;
  std::vector<std::uint8_t> zero_request_id = bytes(info);
  storeU32(zero_request_id, constants::kHeaderRequestIdOffset, 0U);
  refreshBootstrapChecksum(zero_request_id);

  std::vector<std::uint8_t> stream(257U, 0xA5U);
  for (const std::vector<std::uint8_t> *corrupt :
       {&bad_checksum, &oversized, &bad_version, &bad_kind, &bad_flags,
        &bad_reserved, &zero_request_id}) {
    append(stream, *corrupt);
    stream.insert(stream.end(), 19U, 0x6DU);
  }
  const std::vector<std::uint8_t> truncated_info_bytes =
      bytes(truncated_info);
  stream.insert(
      stream.end(), truncated_info_bytes.begin(),
      truncated_info_bytes.begin() +
          static_cast<std::ptrdiff_t>(truncated_info_bytes.size() - 9U));
  stream.insert(stream.end(), 23U, 0xD2U);
  append(stream, bytes(info));
  append(stream, bytes(status));

  wire::IncrementalCommandParser parser{};
  const std::vector<wire::ParsedCommand> results = feedParser(parser, stream);
  std::size_t accepted = 0U;
  std::size_t rejected = 0U;
  std::vector<constants::CommandKind> accepted_kinds{};
  for (const wire::ParsedCommand &result : results) {
    if (result.rejected()) {
      ++rejected;
    } else {
      ++accepted;
      accepted_kinds.push_back(result.request.kind);
    }
  }
  const wire::ParserCounters counters = parser.counters();
  expect(accepted == 2U && rejected >= 7U &&
             accepted_kinds ==
                 std::vector<constants::CommandKind>{
                     constants::CommandKind::kInfo,
                     constants::CommandKind::kGetStatus},
         "corrupt/truncated traffic recovers to valid INFO then STATUS");
  expect(counters.bad_checksums >= 1U && counters.bad_lengths >= 1U &&
             counters.bad_versions >= 1U && counters.bad_kinds >= 1U &&
             counters.bad_flags >= 1U && counters.bad_payloads >= 1U &&
             counters.bad_request_ids >= 1U &&
             counters.buffered_bytes == 0U &&
             counters.high_water_mark <= wire::kCommandParserStorageBytes,
         "parser classifies each corruption while keeping storage bounded: "
         "checksum=" +
             std::to_string(counters.bad_checksums) +
             " length=" + std::to_string(counters.bad_lengths) +
             " version=" + std::to_string(counters.bad_versions) +
             " kind=" + std::to_string(counters.bad_kinds) +
             " flags=" + std::to_string(counters.bad_flags) +
             " payload=" + std::to_string(counters.bad_payloads) +
             " request=" + std::to_string(counters.bad_request_ids) +
             " buffered=" + std::to_string(counters.buffered_bytes) +
             " high_water=" + std::to_string(counters.high_water_mark));

  constexpr std::size_t stress_cycles = 2048U;
  wire::IncrementalCommandParser stress_parser{};
  std::vector<std::uint8_t> stress{};
  stress.reserve(stress_cycles * 127U);
  for (std::size_t cycle = 0U; cycle < stress_cycles; ++cycle) {
    stress.insert(stress.end(), 31U, 0x5AU);
    wire::CommandFrame corrupt = emptyRequest(
        constants::FrameKind::kInfoRequest,
        static_cast<std::uint32_t>(10000U + cycle));
    std::vector<std::uint8_t> corrupt_bytes = bytes(corrupt);
    corrupt_bytes.back() ^= 0x01U;
    append(stress, corrupt_bytes);
    const constants::FrameKind valid_kind =
        cycle % 2U == 0U ? constants::FrameKind::kInfoRequest
                         : constants::FrameKind::kGetStatusRequest;
    append(stress,
           bytes(emptyRequest(valid_kind,
                              static_cast<std::uint32_t>(20000U + cycle))));
  }
  const std::vector<wire::ParsedCommand> stress_results =
      feedParser(stress_parser, stress);
  std::size_t stress_accepted = 0U;
  std::size_t stress_rejected = 0U;
  for (const wire::ParsedCommand &result : stress_results) {
    result.rejected() ? ++stress_rejected : ++stress_accepted;
  }
  const wire::ParserCounters stress_counters = stress_parser.counters();
  expect(stress_accepted == stress_cycles &&
             stress_rejected == stress_cycles &&
             stress_counters.commands_accepted == stress_cycles &&
             stress_counters.candidates_rejected == stress_cycles &&
             stress_counters.bad_checksums == stress_cycles &&
             stress_counters.bytes_received == stress.size() &&
             stress_counters.buffered_bytes == 0U &&
             stress_counters.high_water_mark <=
                 wire::kCommandParserStorageBytes,
         "long garbage/corruption stress remains exact and allocation-bounded");
}

control::ControlState stateAt(constants::DeviceState target) {
  control::ControlState state{};
  wire::ControlFrame response{};
  if (target == constants::DeviceState::kBoot) {
    return state;
  }
  expect(state.completeBoot(0x12345678UL), "complete test control BOOT");
  if (target == constants::DeviceState::kIdle) {
    return state;
  }
  expect(state.dispatch(controlConfigureRequest(1U), response)
             .commandAccepted(),
         "reach CONFIGURED for an illegal-state case");
  if (target == constants::DeviceState::kConfigured) {
    return state;
  }
  expect(state.dispatch(controlRequest(constants::CommandKind::kStart, 2U),
                        response)
             .commandAccepted(),
         "reach RUNNING for an illegal-state case");
  (void)state.takePendingEvents();
  return state;
}

void testIllegalStatesDuplicateIdsAndResetBoundaries() {
  constexpr std::array<constants::DeviceState, 4U> states{
      constants::DeviceState::kBoot, constants::DeviceState::kIdle,
      constants::DeviceState::kConfigured,
      constants::DeviceState::kRunning};
  constexpr std::array<std::array<bool, 4U>, 4U> legal{{
      {{false, true, false, false}},
      {{false, true, true, false}},
      {{false, true, true, true}},
      {{false, true, false, false}},
  }};
  for (std::size_t from = 0U; from < states.size(); ++from) {
    for (std::size_t to = 0U; to < states.size(); ++to) {
      expect(control::ControlState::isLegalTransition(states[from],
                                                       states[to]) ==
                 legal[from][to],
             "cover every legal and illegal state-transition edge");
    }
  }

  constexpr std::array<constants::CommandKind, 10U> commands{
      constants::CommandKind::kInfo,
      constants::CommandKind::kConfigure,
      constants::CommandKind::kStart,
      constants::CommandKind::kGetStatus,
      constants::CommandKind::kStop,
      constants::CommandKind::kResetStats,
      constants::CommandKind::kPing,
      constants::CommandKind::kChecksumBenchmark,
      constants::CommandKind::kGpioClockDiagnostic,
      constants::CommandKind::kGpioCaptureDiagnostic};
  for (std::size_t index = 0U; index < commands.size(); ++index) {
    control::ControlState state = stateAt(constants::DeviceState::kBoot);
    wire::ControlFrame response{};
    const control::DispatchResult result = state.dispatch(
        controlRequest(commands[index], static_cast<std::uint32_t>(index + 1U)),
        response);
    expect(result.status == control::DispatchStatus::kNoResponse &&
               response.size() == 0U &&
               state.state() == constants::DeviceState::kBoot,
           "BOOT rejects every command without a partial response or mutation");
  }

  struct IllegalCase {
    constants::DeviceState state;
    constants::CommandKind command;
  };
  constexpr std::array<IllegalCase, 10U> illegal{{
      {constants::DeviceState::kIdle, constants::CommandKind::kStart},
      {constants::DeviceState::kConfigured,
       constants::CommandKind::kChecksumBenchmark},
      {constants::DeviceState::kConfigured,
       constants::CommandKind::kGpioClockDiagnostic},
      {constants::DeviceState::kConfigured,
       constants::CommandKind::kGpioCaptureDiagnostic},
      {constants::DeviceState::kRunning, constants::CommandKind::kConfigure},
      {constants::DeviceState::kRunning, constants::CommandKind::kStart},
      {constants::DeviceState::kRunning, constants::CommandKind::kResetStats},
      {constants::DeviceState::kRunning,
       constants::CommandKind::kChecksumBenchmark},
      {constants::DeviceState::kRunning,
       constants::CommandKind::kGpioClockDiagnostic},
      {constants::DeviceState::kRunning,
       constants::CommandKind::kGpioCaptureDiagnostic},
  }};
  for (std::size_t index = 0U; index < illegal.size(); ++index) {
    control::ControlState state = stateAt(illegal[index].state);
    const std::uint32_t run_id = state.runId();
    const std::uint32_t generation = state.statistics().generation();
    wire::ControlFrame response{};
    const control::DispatchResult result = state.dispatch(
        controlRequest(illegal[index].command,
                       static_cast<std::uint32_t>(100U + index)),
        response);
    expect(result.responseReady() && !result.commandAccepted() &&
               responseError(response) == constants::ErrorCode::kInvalidState &&
               state.state() == illegal[index].state &&
               state.runId() == run_id &&
               state.statistics().generation() == generation,
           "each illegal command/state pair is atomic and typed");
  }

  control::ControlState duplicate_state = stateAt(constants::DeviceState::kIdle);
  wire::ControlFrame response{};
  expect(duplicate_state
             .dispatch(controlRequest(constants::CommandKind::kInfo, 77U),
                       response)
             .commandAccepted(),
         "accept the first session-scoped request ID");
  expect(!duplicate_state
              .dispatch(controlRequest(constants::CommandKind::kInfo, 77U),
                        response)
              .commandAccepted() &&
             responseError(response) ==
                 constants::ErrorCode::kInvalidRequestId,
         "reject a duplicate request ID without replaying its command");
  duplicate_state.beginHostSession();
  expect(duplicate_state
             .dispatch(controlRequest(constants::CommandKind::kInfo, 77U),
                       response)
             .commandAccepted(),
         "a new CDC session accepts the same request ID without resetting state");

  control::ControlState reset_state = stateAt(constants::DeviceState::kIdle);
  expect(reset_state.statistics().generation() == 1U &&
             reset_state
                 .dispatch(controlRequest(constants::CommandKind::kResetStats,
                                          1000U),
                           response)
                 .commandAccepted() &&
             reset_state.statistics().generation() == 2U,
         "IDLE RESET_STATS advances exactly one generation");
  expect(reset_state.dispatch(controlConfigureRequest(1001U), response)
             .commandAccepted(),
         "configure the reset-boundary state");
  control::DispatchReadiness busy{};
  busy.statistics_reset_ready = false;
  expect(!reset_state
              .dispatch(controlRequest(constants::CommandKind::kResetStats,
                                       1002U),
                        response, busy)
              .commandAccepted() &&
             responseError(response) == constants::ErrorCode::kBusy &&
             reset_state.statistics().generation() == 2U,
         "busy RESET_STATS preserves the complete prior generation");
  expect(reset_state
             .dispatch(controlRequest(constants::CommandKind::kResetStats,
                                      1003U),
                       response)
             .commandAccepted() &&
             reset_state.statistics().generation() == 3U,
         "CONFIGURED RESET_STATS advances only at a quiescent boundary");
  expect(reset_state
             .dispatch(controlRequest(constants::CommandKind::kStart, 1004U),
                       response)
             .commandAccepted(),
         "START opens a new run after the reset boundary");
  const std::uint32_t running_generation =
      reset_state.statistics().generation();
  const std::uint32_t running_run = reset_state.runId();
  (void)reset_state.takePendingEvents();
  expect(!reset_state
              .dispatch(controlRequest(constants::CommandKind::kStart, 1005U),
                        response)
              .commandAccepted() &&
             !reset_state
                  .dispatch(
                      controlRequest(constants::CommandKind::kResetStats,
                                     1006U),
                      response)
                  .commandAccepted() &&
             reset_state.runId() == running_run &&
             reset_state.statistics().generation() == running_generation,
         "repeated START and RUNNING reset cannot split an active epoch");
  expect(reset_state
             .dispatch(controlRequest(constants::CommandKind::kStop, 1007U),
                       response)
             .commandAccepted() &&
             reset_state.takePendingEvents().has(control::Event::kStop) &&
             reset_state
                 .dispatch(controlRequest(constants::CommandKind::kStop,
                                          1008U),
                           response)
                 .commandAccepted() &&
             reset_state.takePendingEvents().mask == 0U,
         "rapid and repeated STOP is event-idempotent");

  control::ControlState cycles = stateAt(constants::DeviceState::kIdle);
  std::uint32_t request_id = 2000U;
  for (std::uint32_t cycle = 0U; cycle < 256U; ++cycle) {
    expect(cycles.dispatch(controlConfigureRequest(request_id++), response)
                   .commandAccepted(),
           "long lifecycle stress CONFIGURE succeeds");
    expect(cycles
               .dispatch(controlRequest(constants::CommandKind::kStart,
                                        request_id++),
                         response)
               .commandAccepted(),
           "long lifecycle stress START succeeds");
    const control::PendingEvents started = cycles.takePendingEvents();
    expect(started.has(control::Event::kStartEpoch) &&
               started.run_id == cycle + 1U,
           "long lifecycle stress allocates one exact run event");
    expect(cycles
               .dispatch(controlRequest(constants::CommandKind::kGetStatus,
                                        request_id++),
                         response)
               .commandAccepted(),
           "long lifecycle stress STATUS remains serviceable");
    expect(cycles
               .dispatch(controlRequest(constants::CommandKind::kStop,
                                        request_id++),
                         response)
               .commandAccepted() &&
               cycles.takePendingEvents().has(control::Event::kStop),
           "long lifecycle stress STOP closes one exact run event");
  }
  expect(cycles.state() == constants::DeviceState::kIdle &&
             cycles.runId() == 256U,
         "256 rapid lifecycle cycles finish deterministically in IDLE");
}

bool drainRuntime(app::FirmwareRuntime &firmware, FakeCdcStream &stream,
                  std::size_t maximum_visits = 20000U) {
  for (std::size_t visit = 0U; visit < maximum_visits; ++visit) {
    (void)firmware.service();
    const packet::PipelineSnapshot packets = firmware.packetSnapshot();
    const usb::TransportSnapshot transport = firmware.transportSnapshot();
    if (stream.inputEmpty() && transport.command_queue_depth == 0U &&
        !transport.command_awaiting_response &&
        !firmware.hasPendingTransmission() &&
        packets.ready_queue_depth == 0U) {
      return true;
    }
  }
  return false;
}

void testRuntimeStartStopRaceAndSerialReopen() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.max_write_size = board::kUsbTxMaxWriteBytes;
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(0x00ABCDEFUL),
         "recovery runtime completes bounded BOOT");

  const wire::CommandFrame first_info =
      emptyRequest(constants::FrameKind::kInfoRequest, 90U);
  stream.appendInputPrefix(first_info, 20U);
  (void)firmware.service();
  expect(firmware.transportSnapshot().parser.buffered_bytes == 20U,
         "adapter retains one bounded partial command while DTR is open");
  stream.session_open = false;
  (void)firmware.service();
  expect(firmware.transportSnapshot().parser.buffered_bytes == 0U,
         "DTR close discards the old session's partial command");
  stream.session_open = true;
  stream.appendInput(first_info);
  expect(drainRuntime(firmware, stream),
         "DTR reopen resynchronizes to a complete INFO command");
  std::vector<wire::DecodedFrame> frames =
      decodeFrames(stream.output, "initial reopen INFO output");
  expect(frames.size() == 1U &&
             frames[0].header.kind == constants::FrameKind::kInfoResponse &&
             frames[0].header.request_id == 90U,
         "truncated prior-session bytes never splice into reopened INFO");

  stream.output.clear();
  stream.appendInput(configureRequest(100U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 101U));
  expect(drainRuntime(firmware, stream) &&
             firmware.state() == constants::DeviceState::kRunning &&
             firmware.runId() == 1U,
         "runtime starts the first combined synthetic epoch");
  stream.output.clear();

  clock.ticks = constants::kFrameCoverageTicks;
  stream.max_write_size = 37U;
  (void)firmware.service();
  expect(firmware.transportSnapshot().active_frame_bytes_sent > 0U &&
             firmware.transportSnapshot().active_frame_bytes_sent <
                 constants::kDataFrameBytes,
         "START/STOP race begins with a genuinely partial data frame");
  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 102U));
  stream.appendInput(configureRequest(103U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 104U));
  (void)firmware.service();
  (void)firmware.service();
  (void)firmware.service();
  expect(firmware.state() == constants::DeviceState::kIdle &&
             firmware.runId() == 1U &&
             firmware.hasPendingTransmission(),
         "rapid STOP/CONFIGURE/START freezes run one while its frame drains");
  stream.max_write_size = board::kUsbTxMaxWriteBytes;
  expect(drainRuntime(firmware, stream),
         "rapid lifecycle race drains within a finite service bound");
  frames = decodeFrames(stream.output, "START/STOP race output");
  bool saw_stop = false;
  bool saw_busy_configure = false;
  bool saw_rejected_start = false;
  std::size_t data_frames = 0U;
  for (const wire::DecodedFrame &frame : frames) {
    if (frame.header.kind == constants::FrameKind::kAdcData ||
        frame.header.kind == constants::FrameKind::kGpioData) {
      ++data_frames;
      expect(frame.header.run_id == 1U,
             "drained race data never crosses run identity");
    } else if (frame.header.request_id == 102U) {
      saw_stop = frame.header.kind == constants::FrameKind::kStopResponse &&
                 responseError(frame) == constants::ErrorCode::kOk;
    } else if (frame.header.request_id == 103U) {
      saw_busy_configure =
          frame.header.kind == constants::FrameKind::kConfigureResponse &&
          responseError(frame) == constants::ErrorCode::kBusy;
    } else if (frame.header.request_id == 104U) {
      saw_rejected_start =
          frame.header.kind == constants::FrameKind::kStartResponse &&
          responseError(frame) == constants::ErrorCode::kInvalidState;
    }
  }
  expect(data_frames == 2U && saw_stop && saw_busy_configure &&
             saw_rejected_start,
         "race output preserves both data frames and exact typed outcomes");

  stream.output.clear();
  stream.appendInput(configureRequest(105U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 106U));
  expect(drainRuntime(firmware, stream) && firmware.runId() == 2U &&
             firmware.state() == constants::DeviceState::kRunning,
         "a clean second run starts after the prior drain");
  stream.output.clear();

  stream.appendInput(emptyRequest(constants::FrameKind::kInfoRequest, 500U));
  expect(drainRuntime(firmware, stream),
         "record one request ID in the running CDC session");
  frames = decodeFrames(stream.output, "pre-close running INFO output");
  expect(frames.size() == 1U && frames[0].header.request_id == 500U &&
             responseError(frames[0]) == constants::ErrorCode::kOk,
         "pre-close INFO succeeds in run two");
  stream.output.clear();

  stream.session_open = false;
  (void)firmware.service();
  expect(firmware.state() == constants::DeviceState::kRunning &&
             firmware.runId() == 2U,
         "serial close never implicitly stops live acquisition");
  clock.ticks += 3U * constants::kFrameCoverageTicks;
  for (std::size_t visit = 0U; visit < 4U; ++visit) {
    (void)firmware.service();
  }
  expect(firmware.packetSnapshot().buffers_owned > 0U &&
             stream.output.empty(),
         "acquisition continues into bounded packet ownership while DTR is closed");

  stream.session_open = true;
  stream.appendInput(emptyRequest(constants::FrameKind::kInfoRequest, 500U));
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 501U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 502U));
  expect(drainRuntime(firmware, stream) &&
             firmware.state() == constants::DeviceState::kIdle,
         "reopened host probes the retained run and explicitly STOPs it");
  frames = decodeFrames(stream.output, "running close/reopen output");
  bool saw_reopened_info = false;
  bool saw_reopened_status = false;
  bool saw_reopened_stop = false;
  for (const wire::DecodedFrame &frame : frames) {
    if (frame.header.request_id == 500U) {
      saw_reopened_info =
          frame.header.kind == constants::FrameKind::kInfoResponse &&
          responseError(frame) == constants::ErrorCode::kOk;
    } else if (frame.header.request_id == 501U) {
      saw_reopened_status =
          frame.header.kind == constants::FrameKind::kGetStatusResponse &&
          responseError(frame) == constants::ErrorCode::kOk;
    } else if (frame.header.request_id == 502U) {
      saw_reopened_stop =
          frame.header.kind == constants::FrameKind::kStopResponse &&
          responseError(frame) == constants::ErrorCode::kOk;
    }
  }
  const usb::TransportSnapshot transport = firmware.transportSnapshot();
  expect(saw_reopened_info && saw_reopened_status && saw_reopened_stop &&
             transport.session_open_events >= 3U &&
             transport.session_close_events >= 2U,
         "reopen resets duplicate IDs, preserves state, and reports session edges");
  const packet::PipelineSnapshot packets = firmware.packetSnapshot();
  expect(packets.ready_for_start && packets.buffers_owned == 0U &&
             packets.sources[0].frames_dropped == 0U &&
             packets.sources[1].frames_dropped == 0U,
         "bounded close/reopen recovery finishes quiescently without hidden loss");
}

}  // namespace

int main() {
  testEveryPartialFrameOffsetPreservesBoundaries();
  testSmallCapacityPressureMatrix();
  testPoolWithOnlyFillingOwnersCannotEvict();
  testFixedQueueLongWrapStress();
  testGarbageAndCorruptParserRecovery();
  testIllegalStatesDuplicateIdsAndResetBoundaries();
  testRuntimeStartStopRaceAndSerialReopen();

  if (failures != 0) {
    std::cerr << failures << " pressure/recovery assertion(s) failed\n";
    return 1;
  }
  std::cout << "firmware pressure and recovery tests passed\n";
  return 0;
}
