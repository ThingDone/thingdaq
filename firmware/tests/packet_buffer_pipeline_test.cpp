#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "statistics.h"
#include "usb_transport.h"

namespace {

namespace board = thingdaq::board;
namespace constants = thingdaq::protocol_v1;
namespace packet = thingdaq::packet;
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

class FakeCdcStream final : public usb::CdcByteStream {
 public:
  bool sessionOpen() const override { return session_open; }

  usb::IoCount available() override { return 0; }

  usb::IoCount read(std::uint8_t *, std::size_t) override { return 0; }

  usb::IoCount availableForWrite() override {
    return std::numeric_limits<usb::IoCount>::max();
  }

  usb::IoCount write(const std::uint8_t *source, std::size_t size) override {
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

  std::deque<usb::IoCount> write_plan{};
  std::vector<std::uint8_t> output{};
  bool session_open = true;
};

packet::FinishFillResult fillAndFinish(packet::PacketBufferPipeline &pipeline,
                                       packet::Stream stream,
                                       std::uint64_t first_ticks,
                                       std::uint16_t flags,
                                       packet::FillHandle &handle,
                                       constants::ChecksumAlgorithm checksum =
                                           constants::kDefaultChecksumAlgorithm) {
  const packet::BeginFillResult begun = pipeline.beginFill(stream);
  expect(begun.ok(), "reserve one source frame for filling");
  handle = begun.handle;
  wire::MutableByteView payload = pipeline.writablePayload(handle);
  expect(payload.valid() && payload.size == constants::kDataPayloadBytes,
         "FILLING ownership exposes exactly one mutable payload");
  if (stream == packet::Stream::kAdc) {
    for (std::size_t offset = 0U; offset < payload.size; offset += 2U) {
      expect(wire::storeU16(payload, offset,
                            static_cast<std::uint16_t>((offset / 2U) & 0xFFFU)),
             "write valid ADC payload container");
    }
  } else {
    for (std::size_t index = 0U; index < payload.size; ++index) {
      payload.data[index] = static_cast<std::uint8_t>(index & 0xFFU);
    }
  }
  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_ticks;
  completion.flags = flags;
  completion.checksum_algorithm = checksum;
  completion.payload_bytes_written = payload.size;
  return pipeline.finishFill(handle, completion);
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
  wire::StatusResponse status = statistics.wireStatus(
      constants::DeviceState::kRunning, configuration);
  wire::ControlFrame frame{};
  expect(wire::encodeStatusResponse(request, run_id, status, frame).ok(),
         "encode a valid STATUS response during packet pressure");
  return frame;
}

wire::ControlFrame stopResponse(std::uint32_t request_id,
                                std::uint32_t run_id) {
  wire::Request request{};
  request.kind = constants::CommandKind::kStop;
  request.request_id = request_id;
  wire::ControlFrame frame{};
  expect(wire::encodeStopResponse(request, run_id, frame).ok(),
         "encode a valid STOP response during packet pressure");
  return frame;
}

void testRunChecksumIsImmutableUntilTheQueueIsQuiescent() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(
             30U, constants::ChecksumAlgorithm::kNoneReserved) ==
             packet::OperationStatus::kUnsupportedChecksum,
         "a run cannot select the reserved checksum ID");
  expect(pipeline.startRun(30U, constants::ChecksumAlgorithm::kCrc32c) ==
             packet::OperationStatus::kOk &&
             pipeline.snapshot().checksum_algorithm ==
                 constants::ChecksumAlgorithm::kCrc32c,
         "the packet epoch snapshots its negotiated checksum");

  packet::FillHandle mismatched{};
  const packet::FinishFillResult rejected = fillAndFinish(
      pipeline, packet::Stream::kAdc, 0U,
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart),
      mismatched, constants::ChecksumAlgorithm::kAdler32);
  expect(rejected.status == packet::OperationStatus::kChecksumMismatch &&
             rejected.encoding.error ==
                 constants::ErrorCode::kUnsupportedChecksum &&
             pipeline.readyFrames() == 0U &&
             pipeline.freeBuffers() == board::kPacketBufferCount,
         "a producer cannot label a frame with a different algorithm");

  pipeline.stopProduction();
  expect(pipeline.startRun(
             31U, constants::ChecksumAlgorithm::kCrc32IsoHdlc) ==
             packet::OperationStatus::kOk,
         "a new algorithm applies only after the prior epoch is quiescent");
  packet::FillHandle accepted{};
  expect(fillAndFinish(
             pipeline, packet::Stream::kGpio, 0U,
             static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart),
             accepted, constants::ChecksumAlgorithm::kCrc32IsoHdlc)
             .ok() &&
             pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "the new epoch emits its negotiated algorithm");
  wire::DecodedFrame decoded{};
  expect(wire::decodeFrame(pipeline.frontFrame(), decoded).ok() &&
             decoded.header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kCrc32IsoHdlc,
         "the immutable frame header and trailer use CRC-32/ISO-HDLC");
  pipeline.releaseFrontFrame();
  pipeline.stopProduction();
}

void testAlignedFixedPoolAndFailureAccounting() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  for (std::size_t index = 0U; index < board::kPacketBufferCount; ++index) {
    const packet::PacketFrame &frame = storage.frame(index);
    const auto address = reinterpret_cast<std::uintptr_t>(frame.data());
    expect(address % board::kCacheLineBytes == 0U,
           "every packet buffer begins at a 32-byte boundary");
  }

  expect(pipeline.startRun(7U) == packet::OperationStatus::kOk,
         "a nonzero run starts from a quiescent pool");
  expect(pipeline.startRun(0U) == packet::OperationStatus::kInvalidRunId &&
             pipeline.startRun(7U) ==
                 packet::OperationStatus::kInvalidRunId,
         "zero and repeated run IDs cannot recycle current ownership");
  const packet::BeginFillResult first =
      pipeline.beginFill(packet::Stream::kAdc);
  expect(first.ok() && first.handle.sequence == 0U,
         "ADC production reserves sequence zero before queue admission");
  const wire::MutableByteView payload =
      pipeline.writablePayload(first.handle);
  std::fill_n(payload.data, payload.size, std::uint8_t{0U});
  packet::FrameCompletion incomplete{};
  incomplete.flags = static_cast<std::uint16_t>(
      constants::FrameFlag::kEpochStart);
  incomplete.payload_bytes_written = payload.size - 1U;
  expect(pipeline.finishFill(first.handle, incomplete).status ==
             packet::OperationStatus::kIncompletePayload,
         "an incomplete payload is recycled before ready-queue admission");
  const packet::PipelineSnapshot rejected = pipeline.snapshot();
  expect(rejected.buffers_by_state[static_cast<std::size_t>(
             packet::BufferState::kFree)] == board::kPacketBufferCount &&
             rejected.sources[packet::streamIndex(packet::Stream::kAdc)]
                     .frames_produced == 1U &&
             rejected.sources[packet::streamIndex(packet::Stream::kAdc)]
                     .frames_framed == 0U &&
             rejected.sources[packet::streamIndex(packet::Stream::kAdc)]
                     .frames_dropped == 1U &&
             rejected.sources[packet::streamIndex(packet::Stream::kAdc)]
                     .next_sequence == 1U,
         "failed construction preserves production, drop, and sequence facts");

  expect(!pipeline.readyForStart() &&
             pipeline.startRun(8U) == packet::OperationStatus::kRunActive,
         "a quiescent active run still requires an explicit STOP");
  const packet::StopReport stopped = pipeline.stopProduction();
  expect(stopped.filling_frames_canceled == 0U && pipeline.readyForStart(),
         "STOP makes an ownership-free run eligible for deterministic reset");
  expect(pipeline.startRun(8U) == packet::OperationStatus::kOk,
         "a new run resets source sequences after complete recycling");
  packet::FillHandle adc{};
  packet::FillHandle gpio{};
  const std::uint16_t epoch =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  expect(fillAndFinish(pipeline, packet::Stream::kAdc, 0U, epoch, adc).ok() &&
             fillAndFinish(pipeline, packet::Stream::kGpio, 0U, epoch, gpio)
                 .ok(),
         "both sources construct complete fixed data frames in place");
  const packet::PipelineSnapshot ready = pipeline.snapshot();
  expect(ready.ready_queue_depth == 2U &&
             ready.ready_depth_by_source[0] == 1U &&
             ready.ready_depth_by_source[1] == 1U &&
             ready.ready_queue_high_water == 2U &&
             ready.sources[0].next_sequence == 1U &&
             ready.sources[1].next_sequence == 1U,
         "independent source sequences and ready-queue telemetry are exact");
  const packet::StopReport ready_stop = pipeline.stopProduction();
  expect(ready_stop.ready_frames_to_drain == 2U &&
             ready_stop.transmitting_frames_to_drain == 0U &&
             pipeline.startRun(9U) ==
                 packet::OperationStatus::kTransmissionPending,
         "a new epoch cannot silently recycle complete READY frames");
  expect(pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "STOP preserves complete READY work for normal transport drain");
  pipeline.releaseFrontFrame();
  pipeline.releaseFrontFrame();
  expect(pipeline.readyForStart(),
         "the next START becomes eligible only after the READY drain");
}

void testTransportOwnershipSurvivesPartialWrites() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(11U) == packet::OperationStatus::kOk,
         "start transport-ownership run");
  packet::FillHandle adc{};
  packet::FillHandle gpio{};
  const std::uint16_t epoch =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  expect(fillAndFinish(pipeline, packet::Stream::kAdc, 0U, epoch, adc).ok() &&
             fillAndFinish(pipeline, packet::Stream::kGpio, 0U, epoch, gpio)
                 .ok(),
         "prepare ADC and GPIO transport frames");
  const packet::PromotionReport promoted = pipeline.serviceReadyFrames();
  expect(promoted.frames_promoted == 2U &&
             pipeline.snapshot().transmit_queue_high_water == 2U,
         "bounded fair promotion transfers both frames to transport ownership");

  const wire::ByteView first = pipeline.frontFrame();
  wire::DecodedFrame decoded{};
  expect(first.size == constants::kDataFrameBytes &&
             wire::decodeFrame(first, decoded).ok() &&
             decoded.header.kind == constants::FrameKind::kAdcData,
         "transport sees only a complete checksummed ADC frame first");

  FakeCdcStream stream{};
  stream.write_plan = {37, 0};
  stats::Statistics statistics{};
  usb::CdcTransport transport{stream, statistics, &pipeline};
  const usb::ServiceReport partial = transport.serviceTransmit();
  const usb::TransportSnapshot stalled = transport.snapshot();
  expect(partial.stalled && partial.bytes_written == 37U &&
             pipeline.queuedFrames() == 2U &&
             pipeline.snapshot().sources[0].frames_transmitted == 0U &&
             stalled.partial_write_events == 1U &&
             stalled.tx_stall_events == 1U &&
             stalled.max_consecutive_tx_stalls == 1U &&
             stalled.lower_priority_queue_depth == 2U &&
             statistics.snapshot().partial_usb_writes == 1U,
         "partial then zero USB writes retain ownership and expose shared stall telemetry");
  const packet::StopReport stopping = pipeline.stopProduction();
  expect(stopping.ready_frames_to_drain == 0U &&
             stopping.transmitting_frames_to_drain == 2U &&
             pipeline.snapshot().drain_pending,
         "STOP explicitly drains complete transport-owned frames");
  expect(pipeline.startRun(12U) ==
             packet::OperationStatus::kTransmissionPending,
         "a new run cannot recycle any transport-owned frame");

  for (std::size_t attempt = 0U;
       attempt < 8U && transport.hasPendingTransmission(); ++attempt) {
    transport.serviceTransmit();
  }
  const packet::PipelineSnapshot drained = pipeline.snapshot();
  const usb::TransportSnapshot transmitted = transport.snapshot();
  expect(!transport.hasPendingTransmission() && pipeline.quiescent() &&
             pipeline.readyForStart() &&
             stream.output.size() == 2U * constants::kDataFrameBytes &&
             drained.sources[0].frames_transmitted == 1U &&
             drained.sources[1].frames_transmitted == 1U &&
             drained.transmit_queue_high_water == 2U &&
             transmitted.lower_priority_frames_completed == 2U &&
             transmitted.lower_priority_queue_depth == 0U &&
             drained.buffers_by_state[static_cast<std::size_t>(
                 packet::BufferState::kFree)] == board::kPacketBufferCount,
         "final bytes release each frame once with exact queue high-water telemetry");

  std::size_t offset = 0U;
  for (constants::FrameKind expected : {constants::FrameKind::kAdcData,
                                        constants::FrameKind::kGpioData}) {
    wire::DecodedFrame output_frame{};
    expect(wire::decodeFrame(
               {stream.output.data() + offset, constants::kDataFrameBytes},
               output_frame)
                   .ok() &&
               output_frame.header.kind == expected,
           "partial writes preserve complete ordered wire frames");
    offset += constants::kDataFrameBytes;
  }
}

void testSessionBoundaryAbortsPartialDataFrame() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(13U, constants::kDefaultChecksumAlgorithm,
                           packet::kAdcStreamMask) ==
             packet::OperationStatus::kOk,
         "start a single-stream session-boundary run");
  const std::uint16_t epoch =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  for (std::uint32_t sequence = 0U; sequence < 2U; ++sequence) {
    packet::FillHandle handle{};
    expect(fillAndFinish(
               pipeline, packet::Stream::kAdc,
               static_cast<std::uint64_t>(sequence) *
                   constants::kFrameCoverageTicks,
               sequence == 0U ? epoch : 0U, handle)
               .ok(),
           "prepare consecutive ADC frames across a CDC boundary");
  }
  expect(pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "promote both CDC-boundary frames");

  FakeCdcStream stream{};
  stream.write_plan = {37, 0};
  stats::Statistics statistics{};
  usb::CdcTransport transport{stream, statistics, &pipeline};
  const usb::ServiceReport partial = transport.serviceTransmit();
  expect(partial.stalled && partial.bytes_written == 37U &&
             transport.snapshot().active_frame_bytes_sent == 37U,
         "establish one pinned partial data frame in the old host session");

  stream.session_open = false;
  const usb::ServiceReport closed = transport.serviceTransmit();
  packet::PipelineSnapshot after_close = pipeline.snapshot();
  expect(closed.bytes_written == 0U &&
             transport.snapshot().active_frame_size == 0U &&
             pipeline.queuedFrames() == 1U &&
             after_close.sources[0].frames_transmitted == 0U &&
             after_close.sources[0].frames_dropped == 1U &&
             after_close.sources[0].frames_dropped_after_framing == 1U &&
             after_close.sources[0].frames_dropped_after_promotion == 1U &&
             after_close.accounted_frame_skew == 2U,
         "DTR close aborts and exactly loss-accounts the pinned old-session frame");

  stream.output.clear();
  stream.session_open = true;
  const usb::ServiceReport reopened = transport.serviceTransmit();
  wire::DecodedFrame successor{};
  const std::uint16_t required_gap = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore));
  expect(reopened.frames_completed == 1U &&
             stream.output.size() == constants::kDataFrameBytes &&
             wire::decodeFrame({stream.output.data(), stream.output.size()},
                               successor)
                 .ok() &&
             successor.header.kind == constants::FrameKind::kAdcData &&
             successor.header.sequence == 1U &&
             (successor.header.flags & required_gap) == required_gap,
         "the new host session starts at a complete checksummed gap-marked frame");
  after_close = pipeline.snapshot();
  expect(after_close.sources[0].frames_transmitted == 1U &&
             after_close.sources[0].frames_dropped == 1U &&
             pipeline.quiescent(),
         "session abort and successor transmission conserve packet ownership");
}

void testFairPromotionKeepsNominalCoverageAligned() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(17U) == packet::OperationStatus::kOk,
         "start fair-promotion run");
  constexpr std::uint64_t coverage_ticks =
      static_cast<std::uint64_t>(constants::kAdcPairsPerFrame) *
      constants::kAdcPairPeriodTicks;
  constexpr std::uint16_t epoch =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);

  for (packet::Stream stream : {packet::Stream::kAdc,
                                packet::Stream::kGpio}) {
    for (std::uint32_t sequence = 0U; sequence < 3U; ++sequence) {
      packet::FillHandle handle{};
      expect(fillAndFinish(pipeline, stream,
                           static_cast<std::uint64_t>(sequence) * coverage_ticks,
                           sequence == 0U ? epoch : 0U, handle)
                 .ok(),
             "queue an unequal-arrival fair-scheduling frame");
    }
  }

  const packet::PromotionReport promoted = pipeline.serviceReadyFrames(6U);
  expect(promoted.frames_promoted == 6U && !promoted.invariant_error,
         "bounded promotion admits the complete dual-stream backlog");
  for (std::uint32_t sequence = 0U; sequence < 3U; ++sequence) {
    for (packet::Stream stream : {packet::Stream::kAdc,
                                  packet::Stream::kGpio}) {
      wire::DecodedFrame frame{};
      const wire::ByteView bytes = pipeline.frontFrame();
      expect(bytes.size == constants::kDataFrameBytes &&
                 wire::decodeFrame(bytes, frame).ok() &&
                 frame.header.kind == packet::frameKind(stream) &&
                 frame.header.sequence == sequence &&
                 frame.header.first_sample_ticks ==
                     static_cast<std::uint64_t>(sequence) * coverage_ticks &&
                 frame.header.checksum_algorithm ==
                     constants::kDefaultChecksumAlgorithm &&
                 frame.header.item_count == packet::itemsPerFrame(stream),
             "alternating transport order preserves aligned coverage and invariants");
      pipeline.releaseFrontFrame();
    }
  }
  expect(pipeline.quiescent() &&
             pipeline.snapshot().sources[0].frames_transmitted == 3U &&
             pipeline.snapshot().sources[1].frames_transmitted == 3U,
         "neither source starves under an unequal ready-arrival backlog");
}

void testCombinedFairnessBoundsLeadAndCountsMissingCoverage() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(18U, constants::kDefaultChecksumAlgorithm,
                           packet::kAllStreamMask) ==
             packet::OperationStatus::kOk,
         "start an explicit equal-coverage combined packet epoch");
  constexpr std::uint64_t coverage_ticks = constants::kFrameCoverageTicks;

  for (std::uint32_t sequence = 0U; sequence < 4U; ++sequence) {
    packet::FillHandle handle{};
    expect(fillAndFinish(
               pipeline, packet::Stream::kAdc,
               static_cast<std::uint64_t>(sequence) * coverage_ticks,
               sequence == 0U
                   ? static_cast<std::uint16_t>(
                         constants::FrameFlag::kEpochStart)
                   : 0U,
               handle)
               .ok(),
           "queue an early ADC frame before matching GPIO coverage");
  }

  const packet::PromotionReport first = pipeline.serviceReadyFrames(4U);
  packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(first.frames_promoted == 1U && first.fairness_deferred &&
             snapshot.ready_depth_by_source[0] == 3U &&
             snapshot.transmit_depth_by_source[0] == 1U &&
             snapshot.accounted_frame_skew == 1U &&
             snapshot.enabled_stream_mask == packet::kAllStreamMask,
         "one source may lead by one equal-duration frame but cannot monopolize USB");

  expect(pipeline.recordSourceFrameDrops(packet::Stream::kGpio, 2U) ==
             packet::OperationStatus::kOk,
         "two missing GPIO intervals consume independent sequence and fairness slots");
  const packet::PromotionReport after_drops =
      pipeline.serviceReadyFrames(4U);
  expect(after_drops.frames_promoted == 2U &&
             after_drops.fairness_deferred &&
             pipeline.snapshot().ready_depth_by_source[0] == 1U,
         "retained ADC coverage advances only across explicitly counted GPIO loss");

  packet::FillHandle gpio{};
  expect(fillAndFinish(pipeline, packet::Stream::kGpio,
                       2U * coverage_ticks, 0U, gpio)
             .ok() &&
             gpio.sequence == 2U,
         "the next retained GPIO frame preserves its independent gap sequence");
  expect(pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "matching GPIO coverage releases itself and the final held ADC frame");

  for (std::size_t frame = 0U; frame < 5U; ++frame) {
    expect(pipeline.frontFrame().size == constants::kDataFrameBytes,
           "transport owns only complete fair-scheduled frames");
    pipeline.releaseFrontFrame();
  }
  snapshot = pipeline.snapshot();
  const std::uint64_t transmitted_payload =
      5U * constants::kDataPayloadBytes;
  const std::uint64_t transmitted_framed =
      5U * constants::kDataFrameBytes;
  expect(snapshot.sources[0].frames_transmitted == 4U &&
             snapshot.sources[1].frames_transmitted == 1U &&
             snapshot.sources[1].frames_dropped == 2U &&
             snapshot.source_bytes[0].payload_bytes_transmitted ==
                 4U * constants::kDataPayloadBytes &&
             snapshot.source_bytes[1].payload_bytes_dropped ==
                 2U * constants::kDataPayloadBytes &&
             snapshot.data_payload_bytes_transmitted ==
                 transmitted_payload &&
             snapshot.data_framed_bytes_transmitted == transmitted_framed &&
             snapshot.fairness_deferrals >= 2U,
         "per-source loss and payload bytes remain separate from framed wire bytes");
  expect(packet::kNominalPayloadBytesPerSecondPerStream == 4000000U &&
             packet::kNominalCombinedPayloadBytesPerSecond == 8000000U &&
             packet::kNominalFramedBytesPerSecondPerStream == 4047431U &&
             packet::kNominalCombinedFramedBytesPerSecond == 8094862U,
         "the nominal 4+4 MB/s payload model reports framing overhead separately");

  (void)pipeline.stopProduction();
  expect(pipeline.startRun(19U, constants::kDefaultChecksumAlgorithm,
                           packet::kAdcStreamMask) ==
             packet::OperationStatus::kOk &&
             pipeline.beginFill(packet::Stream::kGpio).status ==
                 packet::OperationStatus::kStreamDisabled &&
             pipeline.beginFill(packet::Stream::kAdc).ok(),
         "a single-source epoch rejects production from an unconfigured stream");
  (void)pipeline.stopProduction();
  expect(pipeline.startRun(20U, constants::kDefaultChecksumAlgorithm, 0U) ==
                 packet::OperationStatus::kInvalidStreamMask &&
             pipeline.startRun(20U, constants::kDefaultChecksumAlgorithm,
                               0x80U) ==
                 packet::OperationStatus::kInvalidStreamMask,
         "empty and unknown stream masks fail before packet ownership changes");
}

void testPoolExhaustionIsBoundedAndSequenceVisible() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(21U) == packet::OperationStatus::kOk,
         "start pool-bound run");
  std::array<packet::FillHandle, board::kPacketBufferCount> handles{};
  for (std::size_t index = 0U; index < handles.size(); ++index) {
    const packet::BeginFillResult begun =
        pipeline.beginFill(packet::Stream::kGpio);
    expect(begun.ok() && begun.handle.sequence == index,
           "fixed pool reserves each buffer and source sequence in order");
    handles[index] = begun.handle;
  }
  const packet::BeginFillResult overflow =
      pipeline.beginFill(packet::Stream::kGpio);
  expect(overflow.status == packet::OperationStatus::kPoolExhausted,
         "a pool containing only incomplete producer blocks cannot evict one");
  const packet::PipelineSnapshot full = pipeline.snapshot();
  const packet::SourceCounters &gpio = full.sources[1];
  expect(full.buffers_owned_high_water == board::kPacketBufferCount &&
             full.pool_exhaustions == 1U &&
             full.pressure_evictions == 0U &&
             full.capacity_drops_without_evictable_frame == 1U &&
             full.filling_depth_by_source[0] == 0U &&
             full.filling_depth_by_source[1] == board::kPacketBufferCount &&
             full.buffers_owned == board::kPacketBufferCount &&
             gpio.frames_produced == board::kPacketBufferCount + 1U &&
             gpio.frames_dropped == 1U &&
             gpio.next_sequence == board::kPacketBufferCount + 1U,
         "pool pressure exposes exact high-water, drop, and sequence telemetry");
  for (std::size_t index = 0U; index + 1U < handles.size(); ++index) {
    expect(pipeline.cancelFill(handles[index]),
           "producer-owned buffers can be explicitly recycled");
  }
  const packet::StopReport stopped = pipeline.stopProduction();
  expect(pipeline.quiescent() &&
             stopped.filling_frames_canceled == 1U &&
             pipeline.readyForStart() &&
             !pipeline.beginFill(packet::Stream::kGpio).ok(),
         "STOP cancels the final partial fill and prevents new production");
}

void testOldestCompletePressureEvictionKeepsLiveDataAndControlServiceable() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  constexpr std::uint32_t run_id = 41U;
  constexpr std::uint64_t coverage = constants::kFrameCoverageTicks;
  constexpr std::uint32_t initial_frames_per_source =
      static_cast<std::uint32_t>(board::kPacketBufferCount / 2U);
  expect(board::kPacketBufferCount % 2U == 0U &&
             pipeline.startRun(run_id) == packet::OperationStatus::kOk,
         "start an even-capacity combined pressure epoch");

  for (std::uint32_t sequence = 0U;
       sequence < initial_frames_per_source; ++sequence) {
    for (packet::Stream stream : {packet::Stream::kAdc,
                                  packet::Stream::kGpio}) {
      packet::FillHandle handle{};
      expect(fillAndFinish(
                 pipeline, stream,
                 static_cast<std::uint64_t>(sequence) * coverage,
                 sequence == 0U
                     ? static_cast<std::uint16_t>(
                           constants::FrameFlag::kEpochStart)
                     : 0U,
                 handle)
                 .ok(),
             "fill the complete shared packet pool in timestamp order");
    }
  }
  expect(pipeline.freeBuffers() == 0U &&
             pipeline.serviceReadyFrames(board::kPacketBufferCount)
                     .frames_promoted == board::kPacketBufferCount,
         "move the full complete backlog into unsent transport ownership");

  FakeCdcStream stream{};
  stream.write_plan = {37, 0};
  stats::Statistics transport_statistics{};
  usb::CdcTransport transport{stream, transport_statistics, &pipeline};
  const usb::ServiceReport partial = transport.serviceTransmit();
  expect(partial.stalled && partial.bytes_written == 37U &&
             transport.snapshot().active_frame_bytes_sent == 37U,
         "pin the oldest ADC frame only after USB accepts its first prefix");

  const wire::ControlFrame status = statusResponse(700U, run_id);
  const wire::ControlFrame stop = stopResponse(701U, run_id);
  expect(transport.queueResponse(status) && transport.queueResponse(stop),
         "STATUS and STOP responses remain admissible while data is stalled");

  packet::FillHandle adc_new{};
  packet::FillHandle gpio_new{};
  expect(fillAndFinish(
             pipeline, packet::Stream::kAdc,
             static_cast<std::uint64_t>(initial_frames_per_source) * coverage,
             0U, adc_new)
             .ok() &&
             fillAndFinish(
                 pipeline, packet::Stream::kGpio,
                 static_cast<std::uint64_t>(initial_frames_per_source) *
                     coverage,
                 0U, gpio_new)
                 .ok(),
         "new live ADC and GPIO blocks replace complete unsent old coverage");
  expect(adc_new.sequence == initial_frames_per_source &&
             gpio_new.sequence == initial_frames_per_source,
         "pressure admission preserves each source's produced sequence");

  packet::PipelineSnapshot pressured = pipeline.snapshot();
  const packet::SourceCounters &adc = pressured.sources[0];
  const packet::SourceCounters &gpio = pressured.sources[1];
  expect(pressured.pool_exhaustions == 2U &&
             pressured.pressure_evictions == 2U &&
             pressured.capacity_drops_without_evictable_frame == 0U &&
             adc.frames_produced == initial_frames_per_source + 1U &&
             gpio.frames_produced == initial_frames_per_source + 1U &&
             adc.frames_dropped == 1U && gpio.frames_dropped == 1U &&
             adc.frames_evicted == 1U && gpio.frames_evicted == 1U &&
             adc.frames_dropped_after_framing == 1U &&
             gpio.frames_dropped_after_framing == 1U &&
             adc.frames_dropped_after_promotion == 1U &&
             gpio.frames_dropped_after_promotion == 1U &&
             adc.frames_evicted_after_promotion == 1U &&
             gpio.frames_evicted_after_promotion == 1U &&
             pressured.filling_depth_by_source[0] == 0U &&
             pressured.filling_depth_by_source[1] == 0U &&
             adc.items_dropped == constants::kAdcPairsPerFrame &&
             gpio.items_dropped == constants::kGpioSamplesPerFrame &&
             pressured.source_bytes[0].payload_bytes_dropped ==
                 constants::kDataPayloadBytes &&
             pressured.source_bytes[1].payload_bytes_dropped ==
                 constants::kDataPayloadBytes &&
             pressured.source_bytes[0].framed_bytes_evicted ==
                 constants::kDataFrameBytes &&
             pressured.source_bytes[1].framed_bytes_evicted ==
                 constants::kDataFrameBytes &&
             transport.snapshot().active_frame_bytes_sent == 37U,
         "source-aware eviction accounts exact blocks, items, bytes, and the pinned prefix");

  const packet::StopReport stopping = pipeline.stopProduction();
  expect(stopping.transmitting_frames_to_drain ==
                 board::kPacketBufferCount - 2U &&
             stopping.ready_frames_to_drain == 2U,
         "STOP freezes production but retains every complete survivor");
  for (std::size_t visit = 0U;
       visit < board::kPacketBufferCount + 16U &&
       (pipeline.readyFrames() != 0U || transport.hasPendingTransmission());
       ++visit) {
    (void)pipeline.serviceReadyFrames(board::kPacketBufferCount);
    (void)transport.serviceTransmit();
  }
  expect(!transport.hasPendingTransmission() && pipeline.quiescent(),
         "bounded resumed service drains control and the current complete backlog");

  std::size_t offset = 0U;
  std::size_t frame_index = 0U;
  std::array<std::uint32_t, packet::kStreamCount> expected_sequence{};
  std::array<std::uint64_t, packet::kStreamCount> expected_ticks{};
  std::array<std::uint32_t, packet::kStreamCount> inferred_sequence_loss{};
  std::array<std::uint32_t, packet::kStreamCount> inferred_timestamp_loss{};
  std::array<bool, packet::kStreamCount> saw_gap_marker{};
  std::array<std::size_t, packet::kStreamCount> data_frames{};
  while (offset < stream.output.size()) {
    std::uint32_t total = 0U;
    expect(wire::loadU32({stream.output.data(), stream.output.size()},
                         offset + constants::kHeaderTotalLengthOffset,
                         total) &&
               total >= constants::kMinFrameBytes &&
               total <= stream.output.size() - offset,
           "walk each resumed frame by its validated declared length");
    if (total < constants::kMinFrameBytes ||
        total > stream.output.size() - offset) {
      break;
    }
    wire::DecodedFrame decoded{};
    expect(wire::decodeFrame({stream.output.data() + offset, total}, decoded)
               .ok(),
           "every partial/control/data survivor remains a valid frame");
    if (frame_index == 0U) {
      expect(decoded.header.kind == constants::FrameKind::kAdcData &&
                 decoded.header.sequence == 0U,
             "the started ADC frame is never abandoned under pressure");
    } else if (frame_index == 1U) {
      expect(decoded.header.kind ==
                 constants::FrameKind::kGetStatusResponse,
             "STATUS runs at the first boundary after the partial data frame");
    } else if (frame_index == 2U) {
      expect(decoded.header.kind == constants::FrameKind::kStopResponse,
             "STOP follows STATUS before another unsent data frame");
    }

    if (decoded.header.kind == constants::FrameKind::kAdcData ||
        decoded.header.kind == constants::FrameKind::kGpioData) {
      const std::size_t source =
          decoded.header.kind == constants::FrameKind::kAdcData ? 0U : 1U;
      const std::uint32_t sequence_gap =
          decoded.header.sequence - expected_sequence[source];
      const std::uint64_t tick_delta =
          decoded.header.first_sample_ticks - expected_ticks[source];
      expect(tick_delta % coverage == 0U,
             "retained source timestamps stay on complete-frame boundaries");
      const std::uint64_t timestamp_gap = tick_delta / coverage;
      expect(timestamp_gap <= std::numeric_limits<std::uint32_t>::max(),
             "test timestamp loss fits the exact source counter width");
      inferred_sequence_loss[source] += sequence_gap;
      inferred_timestamp_loss[source] +=
          static_cast<std::uint32_t>(timestamp_gap);
      if (sequence_gap != 0U || timestamp_gap != 0U) {
        const std::uint16_t required = static_cast<std::uint16_t>(
            static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
            static_cast<std::uint16_t>(
                constants::FrameFlag::kOverrunBefore));
        expect((decoded.header.flags & required) == required,
               "the exact chronological successor reports gap and overrun");
        saw_gap_marker[source] = true;
      }
      expected_sequence[source] = decoded.header.sequence + 1U;
      expected_ticks[source] = decoded.header.first_sample_ticks + coverage;
      ++data_frames[source];
    }
    offset += total;
    ++frame_index;
  }

  pressured = pipeline.snapshot();
  expect(offset == stream.output.size() && frame_index ==
                 board::kPacketBufferCount + 2U &&
             data_frames[0] == initial_frames_per_source &&
             data_frames[1] == initial_frames_per_source &&
             inferred_sequence_loss[0] == 1U &&
             inferred_sequence_loss[1] == 1U &&
             inferred_timestamp_loss == inferred_sequence_loss &&
             saw_gap_marker[0] && saw_gap_marker[1] &&
             pressured.sources[0].frames_transmitted ==
                 initial_frames_per_source &&
             pressured.sources[1].frames_transmitted ==
                 initial_frames_per_source,
         "sequence, timestamp, flags, counters, and transmitted survivors reconcile exactly");
}

}  // namespace

int main() {
  testAlignedFixedPoolAndFailureAccounting();
  testTransportOwnershipSurvivesPartialWrites();
  testSessionBoundaryAbortsPartialDataFrame();
  testFairPromotionKeepsNominalCoverageAligned();
  testCombinedFairnessBoundsLeadAndCountsMissingCoverage();
  testPoolExhaustionIsBoundedAndSequenceVisible();
  testOldestCompletePressureEvictionKeepsLiveDataAndControlServiceable();
  testRunChecksumIsImmutableUntilTheQueueIsQuiescent();
  if (failures != 0) {
    std::cerr << failures << " packet pipeline assertion(s) failed\n";
    return 1;
  }
  std::cout << "packet buffer pipeline tests passed\n";
  return 0;
}
