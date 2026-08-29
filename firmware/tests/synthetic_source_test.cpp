#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "board_config.h"
#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "synthetic_source.h"

namespace {

namespace board = teensy_daq::board;
namespace constants = teensy_daq::protocol_v1;
namespace packet = teensy_daq::packet;
namespace synthetic = teensy_daq::synthetic;
namespace wire = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
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

wire::DecodedFrame decodeFront(packet::PacketBufferPipeline &pipeline,
                               const std::string &name) {
  wire::DecodedFrame frame{};
  expect(wire::decodeFrame(pipeline.frontFrame(), frame).ok(),
         name + " is a complete valid data frame");
  return frame;
}

std::uint16_t sampleCode(wire::ByteView payload, std::size_t offset) {
  std::uint16_t result = 0U;
  expect(wire::loadU16(payload, offset, result),
         "ADC sample container is readable");
  return result;
}

void testRealtimePacingAndExactLayouts() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  synthetic::SyntheticSource source{};
  constexpr std::uint32_t run_id = 17U;
  constexpr std::uint64_t clock_epoch = 9000000000ULL;

  expect(source.mode() == synthetic::Mode::kRealtime &&
             std::string(synthetic::modeName(source.mode())) == "realtime",
         "normal synthetic source is explicitly real-time paced");
  expect(pipeline.startRun(run_id) == packet::OperationStatus::kOk,
         "packet ownership starts before the source epoch");
  expect(source.startRun(run_id, bothStreams(), clock_epoch, pipeline) ==
             synthetic::OperationStatus::kOk,
         "both deterministic streams share one nonzero START epoch");

  expect(source.service(clock_epoch, pipeline).frames_generated == 0U &&
             source.service(clock_epoch + synthetic::kFrameCoverageTicks - 1U,
                            pipeline)
                     .frames_generated == 0U &&
             pipeline.readyFrames() == 0U,
         "normal mode cannot generate a frame before its samples are due");

  const synthetic::ServiceReport first = source.service(
      clock_epoch + synthetic::kFrameCoverageTicks, pipeline);
  expect(first.frames_generated == 2U && first.frames_framed == 2U &&
             first.frames_dropped == 0U && pipeline.readyFrames() == 2U,
         "one elapsed coverage interval produces one frame per stream");
  expect(pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "complete source frames enter the existing bounded transport path");

  const wire::DecodedFrame adc = decodeFront(pipeline, "first ADC frame");
  expect(adc.header.kind == constants::FrameKind::kAdcData &&
             adc.header.run_id == run_id && adc.header.sequence == 0U &&
             adc.header.first_sample_ticks == 0U &&
             adc.header.item_count == constants::kAdcPairsPerFrame &&
             (adc.header.flags & static_cast<std::uint16_t>(
                                     constants::FrameFlag::kSynthetic)) != 0U &&
             (adc.header.flags & static_cast<std::uint16_t>(
                                     constants::FrameFlag::kEpochStart)) != 0U,
         "ADC header identifies the source, run, sequence, and shared epoch");
  expect(sampleCode(adc.payload, 0U) == 0U &&
             sampleCode(adc.payload, 2U) == 1U &&
             sampleCode(adc.payload, 4U) == 2U &&
             sampleCode(adc.payload, 6U) == 3U,
         "ADC0/ADC1 pair identity follows 2n and 2n+1 interleaving");
  const std::size_t last_adc =
      (constants::kAdcPairsPerFrame - 1U) * constants::kAdcBytesPerPair;
  expect(sampleCode(adc.payload, last_adc) ==
                 synthetic::SyntheticSource::adc0Code(
                     constants::kAdcPairsPerFrame - 1U) &&
             sampleCode(adc.payload, last_adc + 2U) ==
                 synthetic::SyntheticSource::adc1Code(
                     constants::kAdcPairsPerFrame - 1U) &&
             constants::kAdc1PhaseTicks == 4U,
         "the complete ADC frame preserves formulas and four-tick ADC1 phase");
  pipeline.releaseFrontFrame();

  const wire::DecodedFrame gpio = decodeFront(pipeline, "first GPIO frame");
  expect(gpio.header.kind == constants::FrameKind::kGpioData &&
             gpio.header.run_id == run_id && gpio.header.sequence == 0U &&
             gpio.header.first_sample_ticks == 0U &&
             gpio.header.item_count == constants::kGpioSamplesPerFrame,
         "GPIO has an independent sequence on the shared epoch");
  expect(gpio.payload.data[0] == 0U && gpio.payload.data[1] == 1U &&
             gpio.payload.data[255] == 255U &&
             gpio.payload.data[256] == 0U &&
             constants::kGpioPinsByBit[0] == 6U &&
             constants::kGpioPinsByBit[7] == 13U,
         "GPIO bytes are m modulo 256 with D6-D13 mapped to bits 0-7");
  pipeline.releaseFrontFrame();

  const synthetic::ServiceReport second = source.service(
      clock_epoch + 2U * synthetic::kFrameCoverageTicks, pipeline);
  expect(second.frames_framed == 2U &&
             pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "the next elapsed interval produces both next frames");
  const wire::DecodedFrame second_adc = decodeFront(pipeline, "second ADC frame");
  expect(second_adc.header.sequence == 1U &&
             second_adc.header.first_sample_ticks ==
                 synthetic::kFrameCoverageTicks &&
             sampleCode(second_adc.payload, 0U) ==
                 synthetic::SyntheticSource::adc0Code(
                     constants::kAdcPairsPerFrame) &&
             sampleCode(second_adc.payload, 2U) ==
                 synthetic::SyntheticSource::adc1Code(
                     constants::kAdcPairsPerFrame),
         "ADC formula and timestamp continue exactly across frame boundaries");
  pipeline.releaseFrontFrame();
  const wire::DecodedFrame second_gpio =
      decodeFront(pipeline, "second GPIO frame");
  expect(second_gpio.header.sequence == 1U &&
             second_gpio.header.first_sample_ticks ==
                 synthetic::kFrameCoverageTicks &&
             second_gpio.payload.data[0] ==
                 synthetic::SyntheticSource::gpioByte(
                     constants::kGpioSamplesPerFrame),
         "GPIO formula and timestamp continue exactly across frame boundaries");
  pipeline.releaseFrontFrame();

  const packet::PipelineSnapshot counters = pipeline.snapshot();
  expect(counters.sources[0].items_produced ==
                 2U * constants::kAdcPairsPerFrame &&
             counters.sources[0].items_framed ==
                 2U * constants::kAdcPairsPerFrame &&
             counters.sources[0].items_transmitted ==
                 2U * constants::kAdcPairsPerFrame &&
             counters.sources[0].items_dropped == 0U &&
             counters.sources[1].items_produced ==
                 2U * constants::kGpioSamplesPerFrame &&
             counters.sources[1].items_transmitted ==
                 2U * constants::kGpioSamplesPerFrame,
         "generated, framed, transmitted, and dropped item counts are exact");
}

void testUnpacedDiagnosticIsExplicitAndBounded() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  synthetic::SyntheticSource source{
      synthetic::Mode::kUnpacedDiagnostic};
  expect(std::string(synthetic::modeName(source.mode())) ==
             "unpaced-diagnostic",
         "headroom mode has a distinct diagnostic name");
  expect(pipeline.startRun(31U) == packet::OperationStatus::kOk &&
             source.startRun(31U, bothStreams(), 500U, pipeline) ==
                 synthetic::OperationStatus::kOk,
         "unpaced diagnostic starts through the same packet pipeline");

  const synthetic::ServiceReport first = source.service(500U, pipeline);
  expect(first.frames_generated == board::kSyntheticFramesPerLoop &&
             first.frames_framed == board::kSyntheticFramesPerLoop &&
             pipeline.readyFrames() == board::kSyntheticFramesPerLoop,
         "unpaced mode ignores deadlines but retains a per-loop work bound");
  for (std::size_t call = 1U;
       call < (board::kPacketBufferCount + board::kSyntheticFramesPerLoop - 1U) /
                  board::kSyntheticFramesPerLoop;
       ++call) {
    (void)source.service(500U, pipeline);
  }
  const packet::PipelineSnapshot full = pipeline.snapshot();
  expect(pipeline.freeBuffers() == 0U &&
             full.sources[0].frames_produced ==
                 board::kPacketBufferCount / 2U &&
             full.sources[1].frames_produced ==
                 board::kPacketBufferCount / 2U,
         "unpaced alternation fills the fixed pool fairly");
  const synthetic::ServiceReport blocked = source.service(500U, pipeline);
  const packet::PipelineSnapshot unchanged = pipeline.snapshot();
  expect(blocked.waiting_for_buffer && blocked.frames_generated == 0U &&
             unchanged.sources[0].frames_dropped == 0U &&
             unchanged.sources[1].frames_dropped == 0U,
         "unpaced backpressure waits instead of fabricating clockless drops");
}

void testNewRunResetsIndependentEpochState() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  synthetic::SyntheticSource source{};
  const wire::Configuration configuration = bothStreams();
  expect(pipeline.startRun(41U) == packet::OperationStatus::kOk &&
             source.startRun(41U, configuration, 100U, pipeline) ==
                 synthetic::OperationStatus::kOk,
         "first run starts");
  (void)source.service(100U + synthetic::kFrameCoverageTicks, pipeline);
  expect(pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "first run frames are transport-owned");
  pipeline.releaseFrontFrame();
  pipeline.releaseFrontFrame();
  source.stop();
  pipeline.stopProduction();

  expect(source.startRun(41U, configuration, 200U, pipeline) ==
             synthetic::OperationStatus::kInvalidRunId,
         "a repeated run ID cannot masquerade as a new epoch");
  expect(pipeline.startRun(42U) == packet::OperationStatus::kOk &&
             source.startRun(42U, configuration, 200U, pipeline) ==
                 synthetic::OperationStatus::kOk,
         "a distinct nonzero run resets both streams");
  (void)source.service(200U + synthetic::kFrameCoverageTicks, pipeline);
  (void)pipeline.serviceReadyFrames(2U);
  const wire::DecodedFrame adc = decodeFront(pipeline, "new-run ADC frame");
  expect(adc.header.run_id == 42U && adc.header.sequence == 0U &&
             adc.header.first_sample_ticks == 0U &&
             sampleCode(adc.payload, 0U) == 0U &&
             sampleCode(adc.payload, 2U) == 1U,
         "new run resets run ID, sequence, timestamp, and formula epoch");
}

void testRealtimePoolLossPreservesFormulaTimeAndFlags() {
  packet::OwnedPacketBufferStorage storage{};
  packet::PacketBufferPipeline pipeline{storage};
  synthetic::SyntheticSource source{};
  constexpr std::uint64_t epoch = 700U;
  expect(pipeline.startRun(51U) == packet::OperationStatus::kOk &&
             source.startRun(51U, bothStreams(), epoch, pipeline) ==
                 synthetic::OperationStatus::kOk,
         "loss test starts a real-time dual-stream epoch");

  constexpr std::uint64_t dropped_frames_per_stream = 12U;
  constexpr std::uint64_t retained_frames_per_stream =
      board::kPacketBufferCount / packet::kStreamCount;
  constexpr std::uint64_t elapsed_frames =
      retained_frames_per_stream + dropped_frames_per_stream;
  constexpr std::size_t service_calls = static_cast<std::size_t>(
      (packet::kStreamCount * elapsed_frames +
       board::kSyntheticFramesPerLoop - 1U) /
      board::kSyntheticFramesPerLoop);
  for (std::size_t call = 0U; call < service_calls; ++call) {
    const synthetic::ServiceReport report = source.service(
        epoch + elapsed_frames * synthetic::kFrameCoverageTicks, pipeline);
    expect(!report.invariant_error,
           "expected real-time pool pressure is not an invariant failure");
  }
  const packet::PipelineSnapshot pressure = pipeline.snapshot();
  expect(pressure.sources[0].frames_produced == elapsed_frames &&
             pressure.sources[1].frames_produced == elapsed_frames &&
             pressure.sources[0].frames_framed == elapsed_frames &&
             pressure.sources[1].frames_framed == elapsed_frames &&
             pressure.sources[0].frames_dropped ==
                 dropped_frames_per_stream &&
             pressure.sources[1].frames_dropped ==
                 dropped_frames_per_stream &&
             pressure.sources[0].frames_evicted ==
                 dropped_frames_per_stream &&
             pressure.sources[1].frames_evicted ==
                 dropped_frames_per_stream &&
             pressure.pressure_evictions ==
                 packet::kStreamCount * dropped_frames_per_stream,
         "elapsed real-time frames stay framed while the oldest complete coverage is evicted exactly");

  expect(pipeline.serviceReadyFrames(board::kPacketBufferCount)
                 .frames_promoted == board::kPacketBufferCount,
         "all current retained frames move to transport ownership");
  const std::uint16_t gap_flags =
      static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore);
  const wire::DecodedFrame first_adc =
      decodeFront(pipeline, "first retained pressure ADC frame");
  const std::uint64_t first_adc_index =
      dropped_frames_per_stream * constants::kAdcPairsPerFrame;
  expect(first_adc.header.kind == constants::FrameKind::kAdcData &&
             first_adc.header.sequence == dropped_frames_per_stream &&
             first_adc.header.first_sample_ticks ==
                 dropped_frames_per_stream *
                     synthetic::kFrameCoverageTicks &&
             (first_adc.header.flags & gap_flags) == gap_flags &&
             sampleCode(first_adc.payload, 0U) ==
                 synthetic::SyntheticSource::adc0Code(first_adc_index) &&
             sampleCode(first_adc.payload, 2U) ==
                 synthetic::SyntheticSource::adc1Code(first_adc_index),
         "oldest-drop ADC successor exposes matching sequence, time, flags, and formula");
  pipeline.releaseFrontFrame();
  const wire::DecodedFrame first_gpio =
      decodeFront(pipeline, "first retained pressure GPIO frame");
  const std::uint64_t first_gpio_index =
      dropped_frames_per_stream * constants::kGpioSamplesPerFrame;
  expect(first_gpio.header.kind == constants::FrameKind::kGpioData &&
             first_gpio.header.sequence == dropped_frames_per_stream &&
             first_gpio.header.first_sample_ticks ==
                 dropped_frames_per_stream *
                     synthetic::kFrameCoverageTicks &&
             (first_gpio.header.flags & gap_flags) == gap_flags &&
             first_gpio.payload.data[0] ==
                 synthetic::SyntheticSource::gpioByte(first_gpio_index),
         "oldest-drop GPIO successor exposes matching sequence, time, flags, and formula");
  pipeline.releaseFrontFrame();
  for (std::size_t old_frame = 2U;
       old_frame < board::kPacketBufferCount; ++old_frame) {
    pipeline.releaseFrontFrame();
  }

  const synthetic::ServiceReport recovered = source.service(
      epoch + (elapsed_frames + 1U) * synthetic::kFrameCoverageTicks,
      pipeline);
  expect(recovered.frames_generated == 2U && recovered.frames_framed == 2U &&
             recovered.frames_dropped == 0U &&
             pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "new due frames recover when two fixed buffers become free");

  const wire::DecodedFrame adc = decodeFront(pipeline, "post-gap ADC frame");
  const std::uint64_t adc_index =
      elapsed_frames * constants::kAdcPairsPerFrame;
  expect(adc.header.kind == constants::FrameKind::kAdcData &&
             adc.header.sequence == elapsed_frames &&
             adc.header.first_sample_ticks ==
                 elapsed_frames * synthetic::kFrameCoverageTicks &&
             (adc.header.flags & gap_flags) == 0U &&
             sampleCode(adc.payload, 0U) ==
                 synthetic::SyntheticSource::adc0Code(adc_index) &&
             sampleCode(adc.payload, 2U) ==
                 synthetic::SyntheticSource::adc1Code(adc_index),
         "post-gap ADC continues without repeating already reported loss");
  pipeline.releaseFrontFrame();
  const wire::DecodedFrame gpio = decodeFront(pipeline, "post-gap GPIO frame");
  const std::uint64_t gpio_index =
      elapsed_frames * constants::kGpioSamplesPerFrame;
  expect(gpio.header.kind == constants::FrameKind::kGpioData &&
             gpio.header.sequence == elapsed_frames &&
             gpio.header.first_sample_ticks ==
                 elapsed_frames * synthetic::kFrameCoverageTicks &&
             (gpio.header.flags & gap_flags) == 0U &&
             gpio.payload.data[0] ==
                 synthetic::SyntheticSource::gpioByte(gpio_index),
         "post-gap GPIO continues without repeating already reported loss");
  pipeline.releaseFrontFrame();

  const packet::PipelineSnapshot final = pipeline.snapshot();
  expect(final.sources[0].items_produced ==
                 (elapsed_frames + 1U) * constants::kAdcPairsPerFrame &&
             final.sources[0].items_framed ==
                 (elapsed_frames + 1U) * constants::kAdcPairsPerFrame &&
             final.sources[0].items_transmitted ==
                 (retained_frames_per_stream + 1U) *
                     constants::kAdcPairsPerFrame &&
             final.sources[0].items_dropped ==
                 dropped_frames_per_stream *
                     constants::kAdcPairsPerFrame &&
             final.sources[1].items_produced ==
                 (elapsed_frames + 1U) * constants::kGpioSamplesPerFrame &&
             final.sources[1].items_framed ==
                 (elapsed_frames + 1U) * constants::kGpioSamplesPerFrame &&
             final.sources[1].items_transmitted ==
                 (retained_frames_per_stream + 1U) *
                     constants::kGpioSamplesPerFrame &&
             final.sources[1].items_dropped ==
                 dropped_frames_per_stream *
                     constants::kGpioSamplesPerFrame,
         "post-recovery item-stage conservation remains exact per stream");
}

}  // namespace

int main() {
  testRealtimePacingAndExactLayouts();
  testUnpacedDiagnosticIsExplicitAndBounded();
  testNewRunResetsIndependentEpochState();
  testRealtimePoolLossPreservesFormulaTimeAndFlags();
  if (failures != 0) {
    std::cerr << failures << " synthetic source assertion(s) failed\n";
    return 1;
  }
  std::cout << "synthetic source tests passed\n";
  return 0;
}
