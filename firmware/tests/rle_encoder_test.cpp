#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <utility>
#include <vector>

#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "rle_encoder.h"

namespace thingdaq::packet {

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
      record.run_id = pipeline.run_id_;
    }
    return pipeline.freeBuffers() == capacity;
  }

  static void releaseLogicalCapacity(PacketBufferPipeline &pipeline,
                                     std::size_t capacity) {
    for (std::size_t index = capacity; index < pipeline.records_.size();
         ++index) {
      pipeline.records_[index] = {};
    }
  }

  static void injectNextEncodeFailure(PacketBufferPipeline &pipeline) {
    pipeline.inject_rle_encode_failure_ = true;
  }

  static bool acquireTemporaryFor(PacketBufferPipeline &pipeline,
                                  const FillHandle &handle) {
    if (!pipeline.handleMatches(handle)) {
      return false;
    }
    return pipeline.takeTransformBuffer(
               pipeline.records_[handle.buffer_index]) !=
           kInvalidBufferIndex;
  }
};

}  // namespace thingdaq::packet

namespace {

namespace constants = thingdaq::protocol_v1;
namespace constants_v2 = thingdaq::protocol_v2;
namespace packet = thingdaq::packet;
namespace rle = thingdaq::rle;
namespace wire = thingdaq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

std::vector<std::uint8_t> fixture(const std::string &directory,
                                  const std::string &name) {
  std::ifstream input(directory + "/" + name,
                      std::ios::in | std::ios::binary);
  return {std::istreambuf_iterator<char>(input),
          std::istreambuf_iterator<char>()};
}

bool checksumValid(wire::ByteView frame) {
  if (!frame.valid() || frame.size < constants_v2::kTrailerSize) {
    return false;
  }
  const std::size_t checksum_offset =
      frame.size - constants_v2::kTrailerSize;
  std::uint32_t expected = 0U;
  std::uint32_t observed = 0U;
  return wire::computeChecksum(constants::ChecksumAlgorithm::kAdler32,
                               {frame.data, checksum_offset}, expected)
             .ok() &&
         wire::loadU32(frame, checksum_offset, observed) &&
         observed == expected;
}

void setAdcPair(wire::MutableByteView payload, std::size_t pair,
                std::uint16_t adc0, std::uint16_t adc1) {
  const std::size_t offset = pair * constants_v2::kAdcBytesPerPair;
  expect(wire::storeU16(payload, offset, adc0) &&
             wire::storeU16(payload, offset + sizeof(adc0), adc1),
         "write one bounded ADC pair");
}

void fillAdcVector(wire::MutableByteView payload) {
  std::size_t pair = 0U;
  for (; pair < 400U; ++pair) {
    setAdcPair(payload, pair, 291U, 1110U);
  }
  setAdcPair(payload, pair++, 16U, 32U);
  for (; pair < constants_v2::kAdcPairsPerFrame; ++pair) {
    setAdcPair(payload, pair, 2748U, 3567U);
  }
}

void fillGpioVector(wire::MutableByteView payload) {
  std::fill_n(payload.data, 2048U, std::uint8_t{0U});
  std::fill_n(payload.data + 2048U, 1000U, std::uint8_t{0xFFU});
  std::fill_n(payload.data + 3048U, 1000U, std::uint8_t{0x55U});
}

void fillExactRuns(constants_v2::FrameKind kind,
                   wire::MutableByteView payload, std::size_t run_count) {
  const rle::CodecShape shape = rle::dataShape(kind);
  expect(run_count != 0U && run_count <= shape.max_items,
         "requested exact run count fits the generated item bound");
  std::size_t item = 0U;
  for (std::size_t run = 0U; run < run_count; ++run) {
    const std::size_t length =
        run + 1U == run_count ? shape.max_items - item : 1U;
    for (std::size_t offset = 0U; offset < length; ++offset, ++item) {
      if (kind == constants_v2::FrameKind::kGpioData) {
        payload.data[item] =
            static_cast<std::uint8_t>((run & 1U) == 0U ? 0x11U : 0x22U);
      } else {
        const bool even = (run & 1U) == 0U;
        setAdcPair(payload, item, even ? 1U : 3U, even ? 2U : 4U);
      }
    }
  }
  expect(item == shape.max_items, "exact runs fill the complete raw frame");
}

rle::DataFrameFields vectorFields(constants_v2::FrameKind kind) {
  rle::DataFrameFields fields{};
  fields.kind = kind;
  fields.flags =
      static_cast<std::uint16_t>(constants_v2::FrameFlag::kSynthetic);
  fields.checksum_algorithm = constants::ChecksumAlgorithm::kAdler32;
  fields.run_id = 7U;
  fields.sequence = 1U;
  fields.first_sample_ticks = constants_v2::kFrameCoverageTicks;
  return fields;
}

void testExactGoldenVectors(const std::string &fixture_directory) {
  std::array<std::uint8_t, constants_v2::kDataPayloadBytes> adc{};
  fillAdcVector({adc.data(), adc.size()});
  const rle::SizingPlan adc_plan =
      rle::size({adc.data(), adc.size()},
                rle::dataShape(constants_v2::FrameKind::kAdcData));
  expect(adc_plan.ok() && adc_plan.run_count == 3U &&
             adc_plan.encoded_payload_bytes == 18U &&
             adc_plan.encoded_frame_bytes == 66U,
         "ADC sizing matches the canonical three-record vector");
  std::array<std::uint8_t, constants_v2::kDataFrameBytes> adc_frame{};
  const rle::FinalizeResult adc_finalized = rle::finalizeRleDataFrame(
      vectorFields(constants_v2::FrameKind::kAdcData),
      {adc.data(), adc.size()}, adc_plan,
      {adc_frame.data(), adc_frame.size()});
  const std::vector<std::uint8_t> expected_adc =
      fixture(fixture_directory, "adc-rle-data.bin");
  expect(adc_finalized.ok() && expected_adc.size() == adc_finalized.frame_bytes &&
             std::equal(expected_adc.begin(), expected_adc.end(),
                        adc_frame.begin()) &&
             checksumValid({adc_frame.data(), adc_finalized.frame_bytes}),
         "portable ADC finalizer exactly matches the generated golden frame");

  std::array<std::uint8_t, constants_v2::kDataPayloadBytes> gpio{};
  fillGpioVector({gpio.data(), gpio.size()});
  const rle::SizingPlan gpio_plan =
      rle::size({gpio.data(), gpio.size()},
                rle::dataShape(constants_v2::FrameKind::kGpioData));
  expect(gpio_plan.ok() && gpio_plan.run_count == 3U &&
             gpio_plan.encoded_payload_bytes == 9U &&
             gpio_plan.encoded_frame_bytes == 57U,
         "GPIO sizing matches the canonical three-record vector");
  std::array<std::uint8_t, constants_v2::kDataFrameBytes> gpio_frame{};
  const rle::FinalizeResult gpio_finalized = rle::finalizeRleDataFrame(
      vectorFields(constants_v2::FrameKind::kGpioData),
      {gpio.data(), gpio.size()}, gpio_plan,
      {gpio_frame.data(), gpio_frame.size()});
  const std::vector<std::uint8_t> expected_gpio =
      fixture(fixture_directory, "gpio-rle-data.bin");
  expect(gpio_finalized.ok() &&
             expected_gpio.size() == gpio_finalized.frame_bytes &&
             std::equal(expected_gpio.begin(), expected_gpio.end(),
                        gpio_frame.begin()) &&
             checksumValid({gpio_frame.data(), gpio_finalized.frame_bytes}),
         "portable GPIO finalizer exactly matches the generated golden frame");
}

void testSizingBoundariesAndCapacityGuards() {
  std::array<std::uint8_t, constants_v2::kDataPayloadBytes> payload{};
  for (const auto &test :
       std::array<std::pair<constants_v2::FrameKind, std::size_t>, 4U>{
           std::pair{constants_v2::FrameKind::kAdcData, 674U},
           std::pair{constants_v2::FrameKind::kAdcData, 675U},
           std::pair{constants_v2::FrameKind::kGpioData, 1349U},
           std::pair{constants_v2::FrameKind::kGpioData, 1350U}}) {
    fillExactRuns(test.first, {payload.data(), payload.size()}, test.second);
    const rle::SizingPlan plan =
        rle::size({payload.data(), payload.size()}, rle::dataShape(test.first));
    const std::size_t maximum =
        test.first == constants_v2::FrameKind::kAdcData ? 674U : 1349U;
    expect(plan.ok() && plan.run_count == test.second &&
               (plan.encoded_frame_bytes < constants_v2::kDataFrameBytes) ==
                   (test.second <= maximum),
           "strict complete-wire boundary selects only a smaller RLE frame");
  }

  std::array<std::uint8_t, 8U> decoded{1U, 1U, 1U, 2U,
                                       2U, 3U, 3U, 3U};
  const rle::SizingPlan plan =
      rle::size({decoded.data(), decoded.size()}, {1U, decoded.size()});
  std::array<std::uint8_t, 9U> encoded{};
  expect(plan.ok() && plan.run_count == 3U &&
             plan.encoded_payload_bytes == encoded.size(),
         "generic sizing counts maximal adjacent runs");
  const rle::EncodeResult exact =
      rle::encode({decoded.data(), decoded.size()}, plan,
                  {encoded.data(), encoded.size()});
  const std::array<std::uint8_t, 9U> expected{
      3U, 0U, 1U, 2U, 0U, 2U, 3U, 0U, 3U};
  expect(exact.ok() && encoded == expected,
         "generic encoding writes canonical little-endian records");
  expect(rle::encode({decoded.data(), decoded.size()}, plan,
                     {encoded.data(), encoded.size() - 1U})
                 .status == rle::Status::kOutputTooSmall,
         "capacity is checked before the first encoded byte is written");
  std::array<std::uint8_t, 9U> overlapping{};
  std::copy(decoded.begin(), decoded.end(), overlapping.begin());
  expect(rle::encode({overlapping.data(), decoded.size()}, plan,
                     {overlapping.data(), overlapping.size()})
                 .status == rle::Status::kOverlappingBuffers,
         "overlapping output is rejected before unread input can be changed");
  expect(rle::size({decoded.data(), decoded.size() - 1U}, {2U, 4U}).status ==
             rle::Status::kInvalidLength,
         "a sizing pass rejects input truncated inside a logical item");
}

packet::RunFrameFormat v2Auto() {
  packet::RunFrameFormat format{};
  format.protocol_version = constants_v2::kProtocolVersion;
  format.encoding = constants_v2::ConfigurationEncoding::kRleAuto;
  return format;
}

packet::FinishFillResult finishConstantGpio(
    packet::PacketBufferPipeline &pipeline, std::uint8_t value) {
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  expect(begun.ok(), "reserve one GPIO source page");
  const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  expect(payload.valid() && payload.size == constants_v2::kDataPayloadBytes,
         "RLE runs retain the common fixed RAW payload view");
  std::fill_n(payload.data, payload.size, value);
  packet::FrameCompletion completion{};
  completion.flags =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  completion.payload_bytes_written = payload.size;
  return pipeline.finishFill(begun.handle, completion);
}

void testAdaptivePipelineSuccessAndFallbacks() {
  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(41U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Auto()) ==
               packet::OperationStatus::kOk,
           "start an explicit v2 RLE_AUTO packet run");
    const packet::FinishFillResult finished =
        finishConstantGpio(pipeline, 0x5AU);
    const packet::PipelineSnapshot ready = pipeline.snapshot();
    expect(finished.ok() &&
               finished.frame_encoding == constants_v2::FrameEncoding::kRle &&
               finished.raw_fallback_reason ==
                   packet::RawFallbackReason::kNone &&
               finished.rle_run_count == 1U && finished.payload_bytes == 3U &&
               finished.frame_bytes == 51U && ready.ready_queue_depth == 1U &&
               ready.temporary_pages_owned == 0U &&
               ready.temporary_page_high_water == 1U &&
               pipeline.freeBuffers() ==
                   thingdaq::board::kPacketBufferCount - 1U,
           "strictly smaller RLE publishes one complete destination and recycles RAW");
    expect(pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
           "a selected variable-size frame enters transport ownership");
    const wire::ByteView frame = pipeline.frontFrame();
    expect(frame.size == 51U && frame.data[constants_v2::kHeaderVersionOffset] ==
                                    constants_v2::kProtocolVersion &&
               frame.data[constants_v2::kHeaderEncodingOffset] ==
                   static_cast<std::uint8_t>(
                       constants_v2::FrameEncoding::kRle) &&
               checksumValid(frame),
           "published RLE metadata and checksum cover the transmitted view");
    pipeline.releaseFrontFrame();
    pipeline.stopProduction();
    expect(pipeline.readyForStart(),
           "RLE success leaves no hidden temporary ownership");
  }

  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(42U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Auto()) ==
               packet::OperationStatus::kOk,
           "start an incompressible v2 run");
    const packet::BeginFillResult begun =
        pipeline.beginFill(packet::Stream::kGpio);
    const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
    for (std::size_t index = 0U; index < payload.size; ++index) {
      payload.data[index] = static_cast<std::uint8_t>(index & 0xFFU);
    }
    packet::FrameCompletion completion{};
    completion.flags =
        static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
    completion.payload_bytes_written = payload.size;
    const packet::FinishFillResult finished =
        pipeline.finishFill(begun.handle, completion);
    expect(finished.ok() &&
               finished.frame_encoding == constants_v2::FrameEncoding::kRaw &&
               finished.raw_fallback_reason ==
                   packet::RawFallbackReason::kRleNotSmaller &&
               finished.frame_bytes == constants_v2::kDataFrameBytes &&
               pipeline.snapshot().temporary_page_high_water == 0U,
           "non-smaller input stays RAW without requesting workspace");
    pipeline.stopProduction();
    pipeline.serviceReadyFrames(1U);
    pipeline.releaseFrontFrame();
  }

  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(43U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Auto()) ==
                   packet::OperationStatus::kOk &&
               packet::PacketBufferPipelineTestAccess::installLogicalCapacity(
                   pipeline, 1U),
           "constrain the real pool to one logical page without replacing it");
    const packet::FinishFillResult finished =
        finishConstantGpio(pipeline, 0x33U);
    expect(finished.ok() &&
               finished.frame_encoding == constants_v2::FrameEncoding::kRaw &&
               finished.raw_fallback_reason ==
                   packet::RawFallbackReason::kTemporaryPageUnavailable &&
               pipeline.snapshot().temporary_page_exhaustions == 1U &&
               pipeline.snapshot().temporary_pages_owned == 0U,
           "page pressure falls back to intact RAW without evicting data");
    pipeline.serviceReadyFrames(1U);
    expect(pipeline.frontFrame().size == constants_v2::kDataFrameBytes &&
               checksumValid(pipeline.frontFrame()),
           "page-pressure RAW fallback is a complete checksummed v2 frame");
    pipeline.releaseFrontFrame();
    packet::PacketBufferPipelineTestAccess::releaseLogicalCapacity(pipeline,
                                                                    1U);
    pipeline.stopProduction();
  }

  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(44U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Auto()) ==
               packet::OperationStatus::kOk,
           "start the injected encoder-failure run");
    packet::PacketBufferPipelineTestAccess::injectNextEncodeFailure(pipeline);
    const packet::FinishFillResult finished =
        finishConstantGpio(pipeline, 0x7BU);
    expect(finished.ok() &&
               finished.frame_encoding == constants_v2::FrameEncoding::kRaw &&
               finished.raw_fallback_reason ==
                   packet::RawFallbackReason::kEncoderFailure &&
               pipeline.snapshot().encode_failures == 1U &&
               pipeline.snapshot().temporary_pages_owned == 0U &&
               pipeline.freeBuffers() ==
                   thingdaq::board::kPacketBufferCount - 1U,
           "injected encoder failure recycles its page and safely publishes RAW");
    pipeline.serviceReadyFrames(1U);
    const wire::ByteView raw = pipeline.frontFrame();
    expect(raw.size == constants_v2::kDataFrameBytes && checksumValid(raw) &&
               std::all_of(raw.data + constants_v2::kHeaderSize,
                           raw.data + constants_v2::kHeaderSize +
                               constants_v2::kDataPayloadBytes,
                           [](std::uint8_t value) { return value == 0x7BU; }),
           "encoder failure never modifies the retained RAW logical payload");
    pipeline.releaseFrontFrame();
    pipeline.stopProduction();
  }
}

void testStopRecyclesSynchronousWorkspaceDefensively() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(45U, constants::kDefaultChecksumAlgorithm,
                           packet::kGpioStreamMask, v2Auto()) ==
             packet::OperationStatus::kOk,
         "start temporary-page STOP cleanup run");
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  expect(begun.ok() &&
             packet::PacketBufferPipelineTestAccess::acquireTemporaryFor(
                 pipeline, begun.handle) &&
             pipeline.snapshot().temporary_pages_owned == 1U,
         "test seam exposes one real TRANSFORMING lease");
  const packet::StopReport stopped = pipeline.stopProduction();
  expect(stopped.filling_frames_canceled == 1U &&
             stopped.temporary_pages_recycled == 1U &&
             pipeline.snapshot().temporary_pages_owned == 0U &&
             pipeline.freeBuffers() == thingdaq::board::kPacketBufferCount &&
             pipeline.readyForStart(),
         "STOP returns both retained RAW and defensive temporary ownership");
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: rle_encoder_test FIXTURE_DIRECTORY\n";
    return 2;
  }
  testExactGoldenVectors(argv[1]);
  testSizingBoundariesAndCapacityGuards();
  testAdaptivePipelineSuccessAndFallbacks();
  testStopRecyclesSynchronousWorkspaceDefensively();
  if (failures != 0) {
    std::cerr << failures << " RLE encoder assertion(s) failed\n";
    return 1;
  }
  std::cout << "portable RLE encoder and adaptive finalizer tests passed\n";
  return 0;
}
