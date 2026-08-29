#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "adc_frame_packer.h"

namespace {

namespace capture = teensy_daq::adc_capture;
namespace packer = teensy_daq::adc_packer;
namespace packet = teensy_daq::packet;
namespace v1 = teensy_daq::protocol_v1;
namespace wire = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class FakePairSource final : public capture::PairSource {
 public:
  void push(std::uint64_t first_pair, std::uint32_t epoch,
            std::uint16_t base,
            std::uint32_t pair_count = v1::kAdcPairsPerFrame) {
    const std::size_t slot = queued_;
    if (slot >= buffers_.size()) {
      return;
    }
    for (std::size_t pair = 0U; pair < v1::kAdcPairsPerFrame; ++pair) {
      buffers_[slot].pairs[pair].adc0 =
          static_cast<std::uint16_t>(base + pair);
      buffers_[slot].pairs[pair].adc1 =
          static_cast<std::uint16_t>(0x0800U + base + pair);
    }
    handles_[slot].pairs = buffers_[slot].pairs.data();
    handles_[slot].first_pair = first_pair;
    handles_[slot].pair_count = pair_count;
    handles_[slot].epoch = epoch;
    handles_[slot].lease = static_cast<std::uint32_t>(slot + 1U);
    handles_[slot].buffer_index = static_cast<std::uint8_t>(slot);
    ++queued_;
  }

  capture::AcquireResult acquireReady() override {
    if (next_ >= queued_ || leased_) {
      return {};
    }
    leased_ = true;
    return {capture::OperationStatus::kOk, handles_[next_]};
  }

  capture::OperationStatus release(
      const capture::BufferHandle &handle) override {
    if (!leased_ || next_ >= queued_ ||
        handle.lease != handles_[next_].lease ||
        handle.pairs != handles_[next_].pairs) {
      return capture::OperationStatus::kInvalidHandle;
    }
    leased_ = false;
    ++next_;
    ++releases;
    return capture::OperationStatus::kOk;
  }

  std::size_t releases = 0U;

 private:
  std::array<capture::PairBuffer, 4U> buffers_{};
  std::array<capture::BufferHandle, 4U> handles_{};
  std::size_t queued_ = 0U;
  std::size_t next_ = 0U;
  bool leased_ = false;
};

wire::DecodedFrame promoteAndDecode(packet::PacketBufferPipeline &pipeline) {
  expect(pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "one completed ADC frame enters transport ownership");
  const wire::ByteView bytes = pipeline.frontFrame();
  wire::DecodedFrame decoded{};
  expect(bytes.size == v1::kDataFrameBytes &&
             wire::decodeFrame(bytes, decoded).ok(),
         "the physical ADC frame validates with its selected checksum");
  return decoded;
}

void testPhysicalPairFramingTimestampsAndGapProjection() {
  FakePairSource source{};
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  packer::AdcFramePacker adc{source};
  constexpr std::uint32_t run_id = 17U;
  constexpr v1::ChecksumAlgorithm checksum =
      v1::ChecksumAlgorithm::kCrc32c;

  expect(pipeline.startRun(run_id, checksum) == packet::OperationStatus::kOk &&
             adc.startRun(run_id, checksum, pipeline, 123456U) ==
                 packer::OperationStatus::kOk,
         "packet and ADC owners accept one common nonzero run epoch");
  source.push(0U, run_id, 0x0100U);
  source.push(2U * v1::kAdcPairsPerFrame, run_id, 0x0200U);

  const packer::ServiceReport first_service = adc.service(pipeline, 1U);
  expect(first_service.buffers_consumed == 1U &&
             first_service.pairs_consumed == v1::kAdcPairsPerFrame &&
             first_service.frames_framed == 1U && source.releases == 1U,
         "one DMA lease becomes one pair-counted frame and is released");
  wire::DecodedFrame first = promoteAndDecode(pipeline);
  const std::uint16_t first_flags =
      static_cast<std::uint16_t>(v1::FrameFlag::kEpochStart);
  expect(first.header.kind == v1::FrameKind::kAdcData &&
             first.header.flags == first_flags &&
             first.header.checksum_algorithm == checksum &&
             first.header.run_id == run_id && first.header.sequence == 0U &&
             first.header.first_sample_ticks == 0U &&
             first.header.item_count == v1::kAdcPairsPerFrame,
         "first physical frame has independent run/sequence and epoch timing");
  std::uint16_t adc0 = 0U;
  std::uint16_t adc1 = 0U;
  expect(wire::loadU16(first.payload, 12U * sizeof(capture::SamplePair), adc0) &&
             wire::loadU16(first.payload,
                           12U * sizeof(capture::SamplePair) +
                               sizeof(std::uint16_t),
                           adc1) &&
             adc0 == 0x010CU && adc1 == 0x090CU,
         "native DMA payload preserves adc0 then adc1 identity for every pair");
  pipeline.releaseFrontFrame();

  const packer::ServiceReport second_service = adc.service(pipeline, 1U);
  expect(second_service.buffers_consumed == 1U &&
             second_service.frames_framed == 1U && source.releases == 2U,
         "the next retained DMA generation is framed after its raw gap");
  wire::DecodedFrame second = promoteAndDecode(pipeline);
  const std::uint16_t gap_flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(v1::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(v1::FrameFlag::kOverrunBefore));
  expect(second.header.flags == gap_flags && second.header.sequence == 2U &&
             second.header.first_sample_ticks ==
                 2U * v1::kAdcPairsPerFrame *
                     v1::kAdcPairPeriodTicks &&
             (second.header.flags &
              static_cast<std::uint16_t>(v1::FrameFlag::kSynthetic)) == 0U,
         "raw loss consumes one sequence and timestamp interval without a synthetic flag");
  pipeline.releaseFrontFrame();

  const packet::SourceCounters counters =
      pipeline.snapshot().sources[packet::streamIndex(packet::Stream::kAdc)];
  const packer::Snapshot snapshot = adc.snapshot(pipeline);
  expect(counters.frames_produced == 3U && counters.frames_framed == 2U &&
             counters.frames_dropped == 1U &&
             counters.items_dropped == v1::kAdcPairsPerFrame &&
             snapshot.progress.frames_consumed == 2U &&
             snapshot.progress.pairs_consumed ==
                 2U * v1::kAdcPairsPerFrame &&
             snapshot.progress.raw_gap_pairs == v1::kAdcPairsPerFrame &&
             snapshot.progress.raw_drop_pairs_projected ==
                 v1::kAdcPairsPerFrame &&
             snapshot.start_epoch_ticks == 123456U,
         "frame, pair, raw-gap, and projected packet counters reconcile exactly");

  expect(!adc.stopProduction().packet_gap_unreported && adc.quiescent(),
         "clean STOP leaves no unreported packet gap");
  expect(pipeline.stopProduction().ready_frames_to_drain == 0U &&
             pipeline.quiescent(),
         "complete transport release leaves the packet owner reusable");
}

void testStaleEpochCannotCrossRuns() {
  FakePairSource source{};
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  packer::AdcFramePacker adc{source};
  expect(pipeline.startRun(21U, v1::ChecksumAlgorithm::kAdler32) ==
                 packet::OperationStatus::kOk &&
             adc.startRun(21U, v1::ChecksumAlgorithm::kAdler32, pipeline) ==
                 packer::OperationStatus::kOk,
         "second fixture starts a fresh physical epoch");
  source.push(0U, 20U, 0U);
  const packer::ServiceReport service = adc.service(pipeline, 1U);
  expect(service.source_error && service.frames_framed == 0U &&
             source.releases == 1U && pipeline.readyFrames() == 0U &&
             adc.snapshot(pipeline).next_source_pair == 0U,
         "a stale DMA lease is released but never timestamped or framed");
  (void)adc.stopProduction();
  (void)pipeline.stopProduction();
}

void testAlignedFrameBoundaryAtLargestSafeTimestamp() {
  FakePairSource source{};
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  packer::AdcFramePacker adc{source};
  constexpr std::uint64_t maximum_pair_for_timestamp =
      std::numeric_limits<std::uint64_t>::max() /
      v1::kAdcPairPeriodTicks;
  constexpr std::uint64_t first_pair =
      maximum_pair_for_timestamp -
      maximum_pair_for_timestamp % v1::kAdcPairsPerFrame;
  constexpr std::uint64_t dropped_frames =
      first_pair / v1::kAdcPairsPerFrame;
  static_assert(first_pair * v1::kAdcPairPeriodTicks <=
                std::numeric_limits<std::uint64_t>::max());
  static_assert(first_pair <=
                std::numeric_limits<std::uint64_t>::max() -
                    v1::kAdcPairsPerFrame);

  expect(pipeline.startRun(27U, v1::ChecksumAlgorithm::kCrc32IsoHdlc) ==
                 packet::OperationStatus::kOk &&
             adc.startRun(27U, v1::ChecksumAlgorithm::kCrc32IsoHdlc,
                          pipeline) == packer::OperationStatus::kOk,
         "maximum-timestamp fixture starts");
  source.push(first_pair, 27U, 0x0200U);
  const packer::ServiceReport service = adc.service(pipeline, 1U);
  wire::DecodedFrame decoded = promoteAndDecode(pipeline);
  const std::uint16_t gap_flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(v1::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(v1::FrameFlag::kOverrunBefore));
  expect(service.frames_framed == 1U &&
             decoded.header.sequence ==
                 static_cast<std::uint32_t>(dropped_frames) &&
             decoded.header.first_sample_ticks ==
                 first_pair * v1::kAdcPairPeriodTicks &&
             decoded.header.item_count == v1::kAdcPairsPerFrame &&
             decoded.header.flags == gap_flags,
         "an aligned high pair index keeps exact 64-bit timestamp and frame sequence arithmetic");

  std::uint16_t first_adc0 = 0U;
  std::uint16_t first_adc1 = 0U;
  std::uint16_t last_adc0 = 0U;
  std::uint16_t last_adc1 = 0U;
  const std::size_t last_offset =
      (v1::kAdcPairsPerFrame - 1U) * sizeof(capture::SamplePair);
  expect(wire::loadU16(decoded.payload, 0U, first_adc0) &&
             wire::loadU16(decoded.payload, sizeof(std::uint16_t),
                           first_adc1) &&
             wire::loadU16(decoded.payload, last_offset, last_adc0) &&
             wire::loadU16(decoded.payload,
                           last_offset + sizeof(std::uint16_t), last_adc1) &&
             first_adc0 == 0x0200U && first_adc1 == 0x0A00U &&
             last_adc0 == 0x05F3U && last_adc1 == 0x0DF3U,
         "first and last payload boundaries preserve adc0,adc1 halfword order");

  const packer::Snapshot snapshot = adc.snapshot(pipeline);
  expect(snapshot.progress.raw_gap_pairs == first_pair &&
             snapshot.progress.raw_drop_pairs_projected == first_pair &&
             snapshot.progress.chronology_errors == 0U &&
             snapshot.next_source_pair ==
                 first_pair + v1::kAdcPairsPerFrame,
         "aligned frame loss projects exact pair counts without a partial-boundary error");
  pipeline.releaseFrontFrame();
  (void)adc.stopProduction();
  (void)pipeline.stopProduction();
}

void testPairCountAndCounterBoundariesFailClosed() {
  {
    FakePairSource source{};
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    packer::AdcFramePacker adc{source};
    expect(pipeline.startRun(31U, v1::ChecksumAlgorithm::kAdler32) ==
                   packet::OperationStatus::kOk &&
               adc.startRun(31U, v1::ChecksumAlgorithm::kAdler32,
                            pipeline) == packer::OperationStatus::kOk,
           "invalid-count fixture starts");
    source.push(0U, 31U, 0U,
                static_cast<std::uint32_t>(v1::kAdcPairsPerFrame - 1U));
    const packer::ServiceReport rejected = adc.service(pipeline, 1U);
    expect(rejected.source_error && rejected.frames_framed == 0U &&
               pipeline.readyFrames() == 0U,
           "a source handle with less than one fixed ADC frame is rejected");
    (void)adc.stopProduction();
    (void)pipeline.stopProduction();
  }

  {
    FakePairSource source{};
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    packer::AdcFramePacker adc{source};
    expect(pipeline.startRun(33U, v1::ChecksumAlgorithm::kAdler32) ==
                   packet::OperationStatus::kOk &&
               adc.startRun(33U, v1::ChecksumAlgorithm::kAdler32,
                            pipeline) == packer::OperationStatus::kOk,
           "overflowing-counter fixture starts");
    source.push(std::numeric_limits<std::uint64_t>::max() -
                    v1::kAdcPairsPerFrame + 2U,
                33U, 0U);
    const packer::ServiceReport rejected = adc.service(pipeline, 1U);
    expect(rejected.source_error && rejected.frames_framed == 0U &&
               source.releases == 1U && pipeline.readyFrames() == 0U,
           "a pair counter whose fixed frame would wrap is released and never timestamped");
    (void)adc.stopProduction();
    (void)pipeline.stopProduction();
  }
}

}  // namespace

int main() {
  testPhysicalPairFramingTimestampsAndGapProjection();
  testStaleEpochCannotCrossRuns();
  testAlignedFrameBoundaryAtLargestSafeTimestamp();
  testPairCountAndCounterBoundariesFailClosed();
  if (failures != 0) {
    std::cerr << failures << " ADC frame packer assertion(s) failed\n";
    return 1;
  }
  std::cout << "ADC frame packer tests passed\n";
  return 0;
}
