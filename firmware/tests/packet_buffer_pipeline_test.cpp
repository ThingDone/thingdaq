#include <algorithm>
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

namespace board = teensy_daq::board;
namespace constants = teensy_daq::protocol_v1;
namespace packet = teensy_daq::packet;
namespace stats = teensy_daq::stats;
namespace usb = teensy_daq::usb;
namespace wire = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class FakeCdcStream final : public usb::CdcByteStream {
 public:
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

void testRunChecksumIsImmutableUntilTheQueueIsQuiescent() {
  packet::PacketBufferStorage storage{};
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
  packet::PacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  for (const auto &frame : storage.frames) {
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
  packet::PacketBufferStorage storage{};
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
  expect(partial.stalled && partial.bytes_written == 37U &&
             pipeline.queuedFrames() == 2U &&
             pipeline.snapshot().sources[0].frames_transmitted == 0U,
         "partial then zero USB writes retain the immutable front frame");
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
  expect(!transport.hasPendingTransmission() && pipeline.quiescent() &&
             pipeline.readyForStart() &&
             stream.output.size() == 2U * constants::kDataFrameBytes &&
             drained.sources[0].frames_transmitted == 1U &&
             drained.sources[1].frames_transmitted == 1U &&
             drained.buffers_by_state[static_cast<std::size_t>(
                 packet::BufferState::kFree)] == board::kPacketBufferCount,
         "final bytes release each frame exactly once back to FREE");

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

void testFairPromotionKeepsNominalCoverageAligned() {
  packet::PacketBufferStorage storage{};
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
                     constants::ChecksumAlgorithm::kAdler32 &&
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

void testPoolExhaustionIsBoundedAndSequenceVisible() {
  packet::PacketBufferStorage storage{};
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
         "the seventeenth concurrent frame is dropped without allocation");
  const packet::PipelineSnapshot full = pipeline.snapshot();
  const packet::SourceCounters &gpio = full.sources[1];
  expect(full.buffers_owned_high_water == board::kPacketBufferCount &&
             full.pool_exhaustions == 1U &&
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

}  // namespace

int main() {
  testAlignedFixedPoolAndFailureAccounting();
  testTransportOwnershipSurvivesPartialWrites();
  testFairPromotionKeepsNominalCoverageAligned();
  testPoolExhaustionIsBoundedAndSequenceVisible();
  testRunChecksumIsImmutableUntilTheQueueIsQuiescent();
  if (failures != 0) {
    std::cerr << failures << " packet pipeline assertion(s) failed\n";
    return 1;
  }
  std::cout << "packet buffer pipeline tests passed\n";
  return 0;
}
