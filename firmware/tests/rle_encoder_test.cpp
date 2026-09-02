#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
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

  static bool fillReadyQueue(PacketBufferPipeline &pipeline,
                             Stream stream) {
    PacketBufferPipeline::ReadyQueue &queue =
        pipeline.ready_queues_[streamIndex(stream)];
    while (!queue.full()) {
      if (!queue.push(0U)) {
        return false;
      }
    }
    return queue.size() == queue.capacity();
  }

  static void clearReadyQueue(PacketBufferPipeline &pipeline,
                              Stream stream) {
    pipeline.ready_queues_[streamIndex(stream)].clear();
  }

  static void primeSuccessfulSaturation(PacketBufferPipeline &pipeline,
                                        Stream stream) {
    const std::size_t index = streamIndex(stream);
    const std::uint64_t near64 =
        std::numeric_limits<std::uint64_t>::max() - 1U;
    SourceCounters &source = pipeline.source_counters_[index];
    source.frames_produced = near64;
    source.items_produced = near64;
    source.frames_framed = near64;
    source.items_framed = near64;
    source.frames_emitted = near64;
    source.items_emitted = near64;
    source.frames_transmitted = near64;
    source.items_transmitted = near64;
    SelectedByteCounters &selected =
        pipeline.selected_byte_counters_[index];
    selected.framed_bytes_framed = near64;
    selected.framed_bytes_emitted = near64;
    selected.framed_bytes_transmitted = near64;
    selected.encoded_payload_bytes_framed = near64;
    selected.encoded_payload_bytes_emitted = near64;
    selected.encoded_payload_bytes_transmitted = near64;
    EncodingCounters &encoding = pipeline.encoding_counters_[index];
    encoding.rle_frames = near64;
    encoding.rle_runs = near64;
    encoding.encode_cycles = near64;
  }

  static void primeFailureSaturation(PacketBufferPipeline &pipeline,
                                     Stream stream) {
    const std::size_t index = streamIndex(stream);
    const std::uint64_t near64 =
        std::numeric_limits<std::uint64_t>::max() - 1U;
    const std::uint32_t near32 =
        std::numeric_limits<std::uint32_t>::max() - 1U;
    EncodingCounters &encoding = pipeline.encoding_counters_[index];
    encoding.fallback_frames = near64;
    encoding.fallback_encoder_failure = near64;
    encoding.encode_failures = near32;
    pipeline.encode_failures_ = near32;
  }

  static void primeTemporaryExhaustionSaturation(
      PacketBufferPipeline &pipeline, Stream stream) {
    const std::size_t index = streamIndex(stream);
    const std::uint64_t near64 =
        std::numeric_limits<std::uint64_t>::max() - 1U;
    const std::uint32_t near32 =
        std::numeric_limits<std::uint32_t>::max() - 1U;
    EncodingCounters &encoding = pipeline.encoding_counters_[index];
    encoding.fallback_frames = near64;
    encoding.fallback_temporary_page_unavailable = near64;
    pipeline.temporary_page_exhaustions_ = near32;
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

class FakeCycleCounter final : public thingdaq::timing::CycleCounter {
 public:
  bool begin() override {
    begun = true;
    return true;
  }
  std::uint32_t read() override {
    value += 100U;
    return value;
  }

  std::uint32_t value = 0U;
  bool begun = false;
};

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

bool readOracleU32(const std::vector<std::uint8_t> &bytes,
                   std::size_t &offset, std::uint32_t &value) {
  if (offset > bytes.size() || sizeof(value) > bytes.size() - offset) {
    return false;
  }
  value = static_cast<std::uint32_t>(bytes[offset]) |
          (static_cast<std::uint32_t>(bytes[offset + 1U]) << 8U) |
          (static_cast<std::uint32_t>(bytes[offset + 2U]) << 16U) |
          (static_cast<std::uint32_t>(bytes[offset + 3U]) << 24U);
  offset += sizeof(value);
  return true;
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

void testPythonOracleCorpus(const std::string &oracle_path) {
  const std::vector<std::uint8_t> oracle = fixture("", oracle_path);
  expect(oracle.size() >= 8U && oracle[0U] == 'R' && oracle[1U] == 'L' &&
             oracle[2U] == 'E' && oracle[3U] == 'O',
         "Python oracle begins with the fixed RLEO envelope");
  if (oracle.size() < 8U) {
    return;
  }
  std::size_t offset = 4U;
  std::uint32_t case_count = 0U;
  if (!readOracleU32(oracle, offset, case_count)) {
    expect(false, "Python oracle exposes a bounded case count");
    return;
  }
  expect(case_count == 76U,
         "Python oracle covers both widths, boundaries, and seeded cases");
  for (std::uint32_t case_index = 0U; case_index < case_count;
       ++case_index) {
    std::uint32_t item_bytes = 0U;
    std::uint32_t max_items = 0U;
    std::uint32_t decoded_bytes = 0U;
    std::uint32_t encoded_bytes = 0U;
    const bool header_ok = readOracleU32(oracle, offset, item_bytes) &&
                           readOracleU32(oracle, offset, max_items) &&
                           readOracleU32(oracle, offset, decoded_bytes) &&
                           readOracleU32(oracle, offset, encoded_bytes);
    expect(header_ok && offset <= oracle.size() &&
               static_cast<std::size_t>(decoded_bytes) <=
                   oracle.size() - offset,
           "each Python oracle case has a bounded logical payload");
    if (!header_ok || offset > oracle.size() ||
        static_cast<std::size_t>(decoded_bytes) > oracle.size() - offset) {
      return;
    }
    const wire::ByteView decoded{oracle.data() + offset, decoded_bytes};
    offset += decoded_bytes;
    expect(offset <= oracle.size() &&
               static_cast<std::size_t>(encoded_bytes) <=
                   oracle.size() - offset,
           "each Python oracle case has a bounded encoded payload");
    if (offset > oracle.size() ||
        static_cast<std::size_t>(encoded_bytes) > oracle.size() - offset) {
      return;
    }
    const wire::ByteView expected{oracle.data() + offset, encoded_bytes};
    offset += encoded_bytes;
    const rle::SizingPlan plan = rle::size(
        decoded, {static_cast<std::size_t>(item_bytes),
                  static_cast<std::size_t>(max_items)});
    std::vector<std::uint8_t> actual(encoded_bytes, 0xA5U);
    const rle::EncodeResult encoded = rle::encode(
        decoded, plan, {actual.data(), actual.size()});
    expect(plan.ok() && encoded.ok() &&
               plan.encoded_payload_bytes == encoded_bytes &&
               encoded.bytes_written == encoded_bytes &&
               std::equal(actual.begin(), actual.end(), expected.data),
           "portable encoder exactly matches one Python oracle case");
  }
  expect(offset == oracle.size(),
         "Python oracle is consumed exactly without ignored trailing bytes");
}

void testEveryFrameLocalSingleRunLengthAndPlanGuards() {
  std::array<std::uint8_t, constants_v2::kDataPayloadBytes> decoded{};
  std::fill(decoded.begin(), decoded.end(), 0x5AU);
  std::array<std::uint8_t, constants_v2::kAdcRleRecordBytes> encoded{};
  for (const auto &shape : std::array<rle::CodecShape, 2U>{
           rle::CodecShape{1U, constants_v2::kGpioSamplesPerFrame},
           rle::CodecShape{constants_v2::kAdcBytesPerPair,
                           constants_v2::kAdcPairsPerFrame}}) {
    for (std::size_t item_count = 1U; item_count <= shape.max_items;
         ++item_count) {
      const std::size_t byte_count = item_count * shape.item_bytes;
      const rle::SizingPlan plan =
          rle::size({decoded.data(), byte_count}, shape);
      std::fill(encoded.begin(), encoded.end(), 0xA5U);
      const rle::EncodeResult result = rle::encode(
          {decoded.data(), byte_count}, plan,
          {encoded.data(), shape.item_bytes + sizeof(std::uint16_t)});
      const std::uint16_t observed = static_cast<std::uint16_t>(
          static_cast<std::uint16_t>(encoded[0U]) |
          static_cast<std::uint16_t>(
              static_cast<std::uint16_t>(encoded[1U]) << 8U));
      if (!plan.ok() || plan.run_count != 1U || !result.ok() ||
          result.run_count != 1U || observed != item_count) {
        expect(false,
               "every firmware-frame-local single run encodes exactly");
        break;
      }
    }
  }

  const std::uint8_t sentinel = 0x11U;
  expect(rle::size({&sentinel, 65536U}, {1U, 65536U}).status ==
             rle::Status::kItemCountOverflow,
         "a logical count beyond the u16 wire bound fails before reading it");
  const std::array<std::uint8_t, 4U> logical{1U, 1U, 2U, 2U};
  rle::SizingPlan plan =
      rle::size({logical.data(), logical.size()}, {1U, logical.size()});
  std::array<std::uint8_t, 6U> output{};
  ++plan.run_count;
  expect(rle::encode({logical.data(), logical.size()}, plan,
                     {output.data(), output.size()})
                 .status == rle::Status::kPlanMismatch &&
             std::all_of(output.begin(), output.end(),
                         [](std::uint8_t value) { return value == 0U; }),
         "tampered sizing metadata is rejected before output mutation");
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

packet::RunFrameFormat v2Raw() {
  packet::RunFrameFormat format{};
  format.protocol_version = constants_v2::kProtocolVersion;
  format.encoding = constants_v2::ConfigurationEncoding::kRaw;
  return format;
}

packet::FinishFillResult finishConstantAdc(
    packet::PacketBufferPipeline &pipeline, std::uint16_t adc0,
    std::uint16_t adc1, std::uint64_t first_ticks = 0U,
    std::uint16_t flags = static_cast<std::uint16_t>(
        constants_v2::FrameFlag::kEpochStart)) {
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kAdc);
  expect(begun.ok(), "reserve one ADC source page");
  const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  for (std::size_t pair = 0U; pair < constants_v2::kAdcPairsPerFrame;
       ++pair) {
    setAdcPair(payload, pair, adc0, adc1);
  }
  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_ticks;
  completion.flags = flags;
  completion.payload_bytes_written = payload.size;
  return pipeline.finishFill(begun.handle, completion);
}

packet::FinishFillResult finishConstantGpio(
    packet::PacketBufferPipeline &pipeline, std::uint8_t value,
    std::uint64_t first_ticks = 0U,
    std::uint16_t flags = static_cast<std::uint16_t>(
        constants_v2::FrameFlag::kEpochStart)) {
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  expect(begun.ok(), "reserve one GPIO source page");
  const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  expect(payload.valid() && payload.size == constants_v2::kDataPayloadBytes,
         "RLE runs retain the common fixed RAW payload view");
  std::fill_n(payload.data, payload.size, value);
  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_ticks;
  completion.flags = flags;
  completion.payload_bytes_written = payload.size;
  return pipeline.finishFill(begun.handle, completion);
}

packet::FinishFillResult finishAlternatingGpio(
    packet::PacketBufferPipeline &pipeline, std::uint64_t first_ticks = 0U,
    std::uint16_t flags = static_cast<std::uint16_t>(
        constants_v2::FrameFlag::kEpochStart)) {
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  expect(begun.ok(), "reserve one alternating GPIO source page");
  const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  for (std::size_t item = 0U; item < payload.size; ++item) {
    payload.data[item] = (item & 1U) == 0U ? 0x55U : 0xAAU;
  }
  packet::FrameCompletion completion{};
  completion.first_sample_ticks = first_ticks;
  completion.flags = flags;
  completion.payload_bytes_written = payload.size;
  return pipeline.finishFill(begun.handle, completion);
}

void testAdaptivePipelineSuccessAndFallbacks() {
  {
    packet::OwnedPacketBufferStorage storage{};
    FakeCycleCounter cycles{};
    packet::PacketBufferPipeline pipeline{storage, &cycles};
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
    const packet::BeginFillResult raw_begun =
        pipeline.beginFill(packet::Stream::kGpio);
    const wire::MutableByteView raw_payload =
        pipeline.writablePayload(raw_begun.handle);
    for (std::size_t index = 0U; index < raw_payload.size; ++index) {
      raw_payload.data[index] = static_cast<std::uint8_t>(index & 0xFFU);
    }
    packet::FrameCompletion raw_completion{};
    raw_completion.first_sample_ticks = constants_v2::kFrameCoverageTicks;
    raw_completion.payload_bytes_written = raw_payload.size;
    const packet::FinishFillResult raw_finished =
        pipeline.finishFill(raw_begun.handle, raw_completion);
    expect(raw_finished.ok() &&
               raw_finished.frame_encoding ==
                   constants_v2::FrameEncoding::kRaw &&
               raw_finished.raw_fallback_reason ==
                   packet::RawFallbackReason::kRleNotSmaller &&
               pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
           "one negotiated run may select RLE and RAW on adjacent frames");
    pipeline.releaseFrontFrame();
    const packet::PipelineSnapshot mixed = pipeline.snapshot();
    const packet::SourceByteCounters &bytes =
        mixed.source_bytes[packet::streamIndex(packet::Stream::kGpio)];
    const packet::EncodingCounters &encoding =
        mixed.encoding[packet::streamIndex(packet::Stream::kGpio)];
    expect(cycles.begun && encoding.raw_frames == 1U &&
               encoding.rle_frames == 1U && encoding.rle_runs == 1U &&
               encoding.fallback_frames == 1U &&
               encoding.fallback_not_smaller == 1U &&
               encoding.encode_cycles == 200U &&
               bytes.payload_bytes_framed == 8096U &&
               bytes.payload_bytes_transmitted == 8096U &&
               bytes.encoded_payload_bytes_framed == 4051U &&
               bytes.encoded_payload_bytes_transmitted == 4051U &&
               bytes.framed_bytes_framed == 4147U &&
               bytes.framed_bytes_transmitted == 4147U &&
               bytes.encoded_payload_bytes_queued == 0U &&
               bytes.encoded_wire_bytes_queued == 0U,
           "logical, selected-payload, selected-wire, run, fallback, and cycle totals reconcile");
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

void testV1RawCompatibility(const std::string &fixture_directory) {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(7U) == packet::OperationStatus::kOk,
         "default packet start retains protocol v1 RAW");
  const std::uint16_t flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kSynthetic) |
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart));

  const packet::BeginFillResult adc_begun =
      pipeline.beginFill(packet::Stream::kAdc);
  wire::MutableByteView adc_payload =
      pipeline.writablePayload(adc_begun.handle);
  for (std::size_t pair = 0U; pair < constants::kAdcPairsPerFrame; ++pair) {
    setAdcPair(adc_payload, pair,
               static_cast<std::uint16_t>(2U * pair),
               static_cast<std::uint16_t>(2U * pair + 1U));
  }
  packet::FrameCompletion completion{};
  completion.flags = flags;
  completion.payload_bytes_written = adc_payload.size;
  const packet::FinishFillResult adc_finished =
      pipeline.finishFill(adc_begun.handle, completion);

  const packet::BeginFillResult gpio_begun =
      pipeline.beginFill(packet::Stream::kGpio);
  wire::MutableByteView gpio_payload =
      pipeline.writablePayload(gpio_begun.handle);
  for (std::size_t item = 0U; item < gpio_payload.size; ++item) {
    gpio_payload.data[item] = static_cast<std::uint8_t>(item & 0xFFU);
  }
  completion.payload_bytes_written = gpio_payload.size;
  const packet::FinishFillResult gpio_finished =
      pipeline.finishFill(gpio_begun.handle, completion);
  expect(adc_finished.ok() && gpio_finished.ok() &&
             adc_finished.protocol_version == constants::kProtocolVersion &&
             gpio_finished.protocol_version == constants::kProtocolVersion &&
             adc_finished.raw_fallback_reason ==
                 packet::RawFallbackReason::kNotRequested &&
             pipeline.snapshot().temporary_page_high_water == 0U &&
             pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "default finalization performs no RLE sizing or temporary ownership");

  for (const std::string &name : {std::string("adc-data.bin"),
                                  std::string("gpio-data.bin")}) {
    const std::vector<std::uint8_t> expected =
        fixture(fixture_directory + "/../fixtures", name);
    const wire::ByteView actual = pipeline.frontFrame();
    expect(actual.size == expected.size() &&
               std::equal(expected.begin(), expected.end(), actual.data),
           "default v1 packet bytes remain equal to the frozen golden fixture");
    pipeline.releaseFrontFrame();
  }
  const packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(snapshot.encoding[0U].raw_frames == 1U &&
             snapshot.encoding[1U].raw_frames == 1U &&
             snapshot.encoding[0U].rle_frames == 0U &&
             snapshot.encoding[1U].rle_frames == 0U &&
             snapshot.source_bytes[0U].framed_bytes_transmitted ==
                 constants::kDataFrameBytes &&
             snapshot.source_bytes[1U].framed_bytes_transmitted ==
                 constants::kDataFrameBytes,
         "v1 RAW resource and byte accounting remains unchanged");
  pipeline.stopProduction();
}

void testFormatRollbackAndMixedStreamConservation() {
  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    packet::RunFrameFormat invalid{};
    invalid.protocol_version = constants::kProtocolVersion;
    invalid.encoding = constants_v2::ConfigurationEncoding::kRleAuto;
    expect(pipeline.startRun(60U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, invalid) ==
                   packet::OperationStatus::kUnsupportedFrameFormat &&
               pipeline.snapshot().run_id == 0U &&
               !pipeline.snapshot().accepting_frames &&
               pipeline.freeBuffers() == thingdaq::board::kPacketBufferCount,
           "an illegal negotiated format rolls back before mutating ownership");
    expect(pipeline.startRun(60U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Raw()) ==
               packet::OperationStatus::kOk,
           "the rejected run ID remains available for a valid v2 RAW start");
    const packet::FinishFillResult raw = finishConstantGpio(pipeline, 0x33U);
    const packet::PipelineSnapshot ready = pipeline.snapshot();
    expect(raw.ok() &&
               raw.frame_encoding == constants_v2::FrameEncoding::kRaw &&
               raw.raw_fallback_reason ==
                   packet::RawFallbackReason::kNotRequested &&
               ready.temporary_page_high_water == 0U &&
               ready.encoding[1U].encode_cycles == 0U &&
               ready.encoding[1U].fallback_frames == 0U,
           "explicit v2 RAW performs no adaptive work or fallback accounting");
    pipeline.serviceReadyFrames(1U);
    pipeline.releaseFrontFrame();
    pipeline.stopProduction();
  }

  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(61U, constants::kDefaultChecksumAlgorithm,
                             packet::kAllStreamMask, v2Auto()) ==
               packet::OperationStatus::kOk,
           "start a mixed-selection dual-stream run");
    const packet::FinishFillResult adc =
        finishConstantAdc(pipeline, 0x155U, 0xAAAU);
    const packet::FinishFillResult gpio = finishAlternatingGpio(pipeline);
    expect(adc.ok() &&
               adc.frame_encoding == constants_v2::FrameEncoding::kRle &&
               adc.rle_run_count == 1U && adc.frame_bytes == 54U &&
               gpio.ok() &&
               gpio.frame_encoding == constants_v2::FrameEncoding::kRaw &&
               gpio.raw_fallback_reason ==
                   packet::RawFallbackReason::kRleNotSmaller &&
               pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
           "one run independently selects compressed ADC and RAW GPIO");

    for (const auto &expected :
         std::array<std::pair<constants_v2::FrameKind,
                              constants_v2::FrameEncoding>,
                    2U>{{
             {constants_v2::FrameKind::kAdcData,
              constants_v2::FrameEncoding::kRle},
             {constants_v2::FrameKind::kGpioData,
              constants_v2::FrameEncoding::kRaw},
         }}) {
      wire::DecodedFrame decoded{};
      const wire::ByteView frame = pipeline.frontFrame();
      expect(wire::decodeFrame(frame, decoded).ok() &&
                 decoded.header.version == constants_v2::kProtocolVersion &&
                 static_cast<std::uint8_t>(decoded.header.kind) ==
                     static_cast<std::uint8_t>(expected.first) &&
                 decoded.header.encoding == expected.second &&
                 decoded.header.sequence == 0U &&
                 decoded.header.first_sample_ticks == 0U &&
                 checksumValid(frame),
             "mixed stream preserves kind, selector, epoch, and checksum");
      pipeline.releaseFrontFrame();
    }
    const packet::PipelineSnapshot mixed = pipeline.snapshot();
    expect(mixed.sources[0U].frames_transmitted == 1U &&
               mixed.sources[1U].frames_transmitted == 1U &&
               mixed.source_bytes[0U].payload_bytes_transmitted == 4048U &&
               mixed.source_bytes[1U].payload_bytes_transmitted == 4048U &&
               mixed.source_bytes[0U].encoded_payload_bytes_transmitted == 6U &&
               mixed.source_bytes[1U].encoded_payload_bytes_transmitted ==
                   4048U &&
               mixed.source_bytes[0U].framed_bytes_transmitted == 54U &&
               mixed.source_bytes[1U].framed_bytes_transmitted == 4096U &&
               mixed.data_payload_bytes_transmitted == 8096U &&
               mixed.data_framed_bytes_transmitted == 4150U &&
               mixed.encoding[0U].rle_frames == 1U &&
               mixed.encoding[1U].raw_frames == 1U &&
               mixed.encoding[1U].fallback_not_smaller == 1U &&
               mixed.temporary_pages_owned == 0U,
           "mixed logical, selected-payload, and wire totals conserve exactly");
    pipeline.stopProduction();
  }
}

void testQueueFailureReturnsBothPages() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  expect(pipeline.startRun(62U, constants::kDefaultChecksumAlgorithm,
                           packet::kGpioStreamMask, v2Auto()) ==
             packet::OperationStatus::kOk,
         "start a queue-failure cleanup run");
  const packet::BeginFillResult begun =
      pipeline.beginFill(packet::Stream::kGpio);
  const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
  std::fill_n(payload.data, payload.size, std::uint8_t{0x42U});
  expect(begun.ok() &&
             packet::PacketBufferPipelineTestAccess::fillReadyQueue(
                 pipeline, packet::Stream::kGpio),
         "fill the fixed ready queue through the test-only fault seam");
  packet::FrameCompletion completion{};
  completion.flags = static_cast<std::uint16_t>(
      constants_v2::FrameFlag::kEpochStart);
  completion.payload_bytes_written = payload.size;
  const packet::FinishFillResult rejected =
      pipeline.finishFill(begun.handle, completion);
  packet::PacketBufferPipelineTestAccess::clearReadyQueue(
      pipeline, packet::Stream::kGpio);
  const packet::PipelineSnapshot snapshot = pipeline.snapshot();
  expect(rejected.status == packet::OperationStatus::kQueueFull &&
             snapshot.ready_queue_rejections == 1U &&
             snapshot.sources[1U].frames_dropped == 1U &&
             snapshot.sources[1U].frames_framed == 0U &&
             snapshot.temporary_pages_owned == 0U &&
             pipeline.freeBuffers() == thingdaq::board::kPacketBufferCount,
         "queue rejection returns the RLE destination and retained RAW page");
  pipeline.stopProduction();
  expect(pipeline.readyForStart(),
         "queue fault cleanup leaves no hidden ownership for the next run");
}

void testRleCountersSaturateWithoutWrapping() {
  const std::uint64_t maximum64 =
      std::numeric_limits<std::uint64_t>::max();
  const std::uint32_t maximum32 =
      std::numeric_limits<std::uint32_t>::max();
  {
    packet::OwnedPacketBufferStorage storage{};
    FakeCycleCounter cycles{};
    packet::PacketBufferPipeline pipeline{storage, &cycles};
    expect(pipeline.startRun(63U, constants::kDefaultChecksumAlgorithm,
                             packet::kAdcStreamMask, v2Auto()) ==
               packet::OperationStatus::kOk,
           "start successful saturation run");
    packet::PacketBufferPipelineTestAccess::primeSuccessfulSaturation(
        pipeline, packet::Stream::kAdc);
    const packet::BeginFillResult begun =
        pipeline.beginFill(packet::Stream::kAdc);
    const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
    for (std::size_t pair = 0U; pair < constants_v2::kAdcPairsPerFrame;
         ++pair) {
      setAdcPair(payload, pair, 0x123U, 0x456U);
    }
    packet::FrameCompletion completion{};
    completion.flags = static_cast<std::uint16_t>(
        constants_v2::FrameFlag::kEpochStart);
    completion.payload_bytes_written = payload.size;
    expect(pipeline.finishFill(begun.handle, completion).ok() &&
               pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
           "saturation fixture still publishes one complete RLE frame");
    pipeline.releaseFrontFrame();
    const packet::PipelineSnapshot saturated = pipeline.snapshot();
    expect(saturated.sources[0U].frames_produced == maximum64 &&
               saturated.sources[0U].items_produced == maximum64 &&
               saturated.sources[0U].frames_framed == maximum64 &&
               saturated.sources[0U].frames_emitted == maximum64 &&
               saturated.sources[0U].frames_transmitted == maximum64 &&
               saturated.source_bytes[0U].payload_bytes_transmitted ==
                   maximum64 &&
               saturated.source_bytes[0U].encoded_payload_bytes_transmitted ==
                   maximum64 &&
               saturated.source_bytes[0U].framed_bytes_transmitted ==
                   maximum64 &&
               saturated.encoding[0U].rle_frames == maximum64 &&
               saturated.encoding[0U].rle_runs == maximum64 &&
               saturated.encoding[0U].encode_cycles == maximum64,
           "64-bit logical, encoded, wire, run, and cycle counters saturate");
    pipeline.stopProduction();
  }

  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(64U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Auto()) ==
               packet::OperationStatus::kOk,
           "start injected failure saturation run");
    const packet::BeginFillResult begun =
        pipeline.beginFill(packet::Stream::kGpio);
    const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
    std::fill_n(payload.data, payload.size, std::uint8_t{0x63U});
    packet::PacketBufferPipelineTestAccess::primeFailureSaturation(
        pipeline, packet::Stream::kGpio);
    packet::PacketBufferPipelineTestAccess::injectNextEncodeFailure(pipeline);
    packet::FrameCompletion completion{};
    completion.flags = static_cast<std::uint16_t>(
        constants_v2::FrameFlag::kEpochStart);
    completion.payload_bytes_written = payload.size;
    const packet::FinishFillResult result =
        pipeline.finishFill(begun.handle, completion);
    const packet::PipelineSnapshot saturated = pipeline.snapshot();
    expect(result.ok() && result.raw_fallback_reason ==
                              packet::RawFallbackReason::kEncoderFailure &&
               saturated.encode_failures == maximum32 &&
               saturated.encoding[1U].encode_failures == maximum32 &&
               saturated.encoding[1U].fallback_frames == maximum64 &&
               saturated.encoding[1U].fallback_encoder_failure == maximum64 &&
               saturated.temporary_pages_owned == 0U,
           "fault and fallback counters saturate while ownership is recycled");
    pipeline.serviceReadyFrames(1U);
    pipeline.releaseFrontFrame();
    pipeline.stopProduction();
  }

  {
    packet::OwnedPacketBufferStorage storage{};
    packet::PacketBufferPipeline pipeline{storage};
    expect(pipeline.startRun(65U, constants::kDefaultChecksumAlgorithm,
                             packet::kGpioStreamMask, v2Auto()) ==
                   packet::OperationStatus::kOk &&
               packet::PacketBufferPipelineTestAccess::installLogicalCapacity(
                   pipeline, 1U),
           "start temporary-page exhaustion saturation run");
    const packet::BeginFillResult begun =
        pipeline.beginFill(packet::Stream::kGpio);
    const wire::MutableByteView payload = pipeline.writablePayload(begun.handle);
    std::fill_n(payload.data, payload.size, std::uint8_t{0x65U});
    packet::PacketBufferPipelineTestAccess::primeTemporaryExhaustionSaturation(
        pipeline, packet::Stream::kGpio);
    packet::FrameCompletion completion{};
    completion.flags = static_cast<std::uint16_t>(
        constants_v2::FrameFlag::kEpochStart);
    completion.payload_bytes_written = payload.size;
    const packet::FinishFillResult result =
        pipeline.finishFill(begun.handle, completion);
    const packet::PipelineSnapshot saturated = pipeline.snapshot();
    expect(result.ok() && result.raw_fallback_reason ==
                              packet::RawFallbackReason::kTemporaryPageUnavailable &&
               saturated.temporary_page_exhaustions == maximum32 &&
               saturated.encoding[1U].fallback_frames == maximum64 &&
               saturated.encoding[1U]
                       .fallback_temporary_page_unavailable == maximum64 &&
               saturated.temporary_pages_owned == 0U,
           "temporary-page pressure counters saturate without wrapping");
    pipeline.serviceReadyFrames(1U);
    pipeline.releaseFrontFrame();
    packet::PacketBufferPipelineTestAccess::releaseLogicalCapacity(pipeline,
                                                                    1U);
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
  if (argc != 3) {
    std::cerr <<
        "usage: rle_encoder_test FIXTURE_DIRECTORY PYTHON_ORACLE\n";
    return 2;
  }
  testExactGoldenVectors(argv[1]);
  testPythonOracleCorpus(argv[2]);
  testEveryFrameLocalSingleRunLengthAndPlanGuards();
  testSizingBoundariesAndCapacityGuards();
  testAdaptivePipelineSuccessAndFallbacks();
  testV1RawCompatibility(argv[1]);
  testFormatRollbackAndMixedStreamConservation();
  testQueueFailureReturnsBothPages();
  testRleCountersSaturateWithoutWrapping();
  testStopRecyclesSynchronousWorkspaceDefensively();
  if (failures != 0) {
    std::cerr << failures << " RLE encoder assertion(s) failed\n";
    return 1;
  }
  std::cout << "portable RLE encoder and adaptive finalizer tests passed\n";
  return 0;
}
