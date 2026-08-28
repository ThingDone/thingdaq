#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "gpio_batch_packer.h"
#include "gpio_raw_capture.h"
#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "statistics.h"

namespace {

namespace capture = teensy_daq::gpio_capture;
namespace constants = teensy_daq::protocol_v1;
namespace packet = teensy_daq::packet;
namespace packer = teensy_daq::gpio_packer;
namespace stats = teensy_daq::stats;
namespace wire = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

constexpr std::uint32_t rawWord(std::uint8_t packed,
                                std::uint32_t unrelated = 0U) {
  std::uint32_t word = unrelated & ~teensy_daq::board::kGpio2PsrCaptureMask;
  for (std::size_t bit = 0U; bit < 8U; ++bit) {
    if ((packed & (std::uint8_t{1U} << bit)) != 0U) {
      word |= std::uint32_t{1U}
              << teensy_daq::board::kGpioMappingsByPackedBit[bit].gpio2_bit;
    }
  }
  return word;
}

class FakeRawSource final : public capture::RawWordSource {
 public:
  struct Batch {
    std::array<std::uint32_t, constants::kGpioSamplesPerFrame> words{};
    std::uint64_t first_sample = 0U;
    std::uint32_t sample_count = 0U;
  };

  bool add(std::uint64_t first_sample, std::uint32_t sample_count) {
    if (batch_count_ >= batches_.size() || sample_count == 0U ||
        sample_count > constants::kGpioSamplesPerFrame) {
      return false;
    }
    Batch &batch = batches_[batch_count_++];
    batch.first_sample = first_sample;
    batch.sample_count = sample_count;
    for (std::size_t index = 0U; index < sample_count; ++index) {
      const std::uint64_t sample = first_sample + index;
      batch.words[index] = rawWord(
          static_cast<std::uint8_t>(sample & 0xFFU),
          static_cast<std::uint32_t>(0xA5A00000U ^ sample));
    }
    return true;
  }

  capture::AcquireResult acquireReady() override {
    capture::AcquireResult result{};
    if (outstanding_ || next_batch_ >= batch_count_) {
      result.status = capture::OperationStatus::kNoReadyBuffer;
      return result;
    }
    Batch &batch = batches_[next_batch_];
    outstanding_ = true;
    result.handle.words = batch.words.data();
    result.handle.first_sample = batch.first_sample;
    result.handle.sample_count = batch.sample_count;
    result.handle.lease = static_cast<std::uint32_t>(next_batch_ + 1U);
    result.handle.buffer_index =
        static_cast<std::uint8_t>(next_batch_ %
                                  teensy_daq::board::kGpioRawDmaRingDepth);
    result.status = capture::OperationStatus::kOk;
    return result;
  }

  capture::OperationStatus release(
      const capture::BufferHandle &handle) override {
    if (!outstanding_ || next_batch_ >= batch_count_) {
      return capture::OperationStatus::kInvalidHandle;
    }
    const Batch &batch = batches_[next_batch_];
    if (handle.words != batch.words.data() ||
        handle.lease != static_cast<std::uint32_t>(next_batch_ + 1U)) {
      return capture::OperationStatus::kInvalidHandle;
    }
    outstanding_ = false;
    ++next_batch_;
    return capture::OperationStatus::kOk;
  }

  std::size_t remaining() const { return batch_count_ - next_batch_; }

 private:
  std::array<Batch, 12U> batches_{};
  std::size_t batch_count_ = 0U;
  std::size_t next_batch_ = 0U;
  bool outstanding_ = false;
};

struct PipelineFixture {
  packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline pipeline{packet_storage};
  packer::PackedBufferStorage packed_storage{};
};

wire::DecodedFrame decodeAndRelease(packet::PacketBufferPipeline &pipeline,
                                    const std::string &message) {
  wire::DecodedFrame frame{};
  expect(wire::decodeFrame(pipeline.frontFrame(), frame).ok(), message);
  pipeline.releaseFrontFrame();
  return frame;
}

void expectPayloadRamp(const wire::DecodedFrame &frame,
                       std::uint64_t first_sample,
                       const std::string &message) {
  bool valid = frame.payload.valid() &&
               frame.payload.size == constants::kDataPayloadBytes;
  for (std::size_t index = 0U; valid && index < frame.payload.size; ++index) {
    valid = frame.payload.data[index] ==
            static_cast<std::uint8_t>((first_sample + index) & 0xFFU);
  }
  expect(valid, message);
}

void testExactMappingAndBatchPrimitive() {
  std::array<std::uint32_t, 256U> source{};
  std::array<std::uint8_t, 256U> destination{};
  for (std::size_t value = 0U; value < source.size(); ++value) {
    source[value] = rawWord(static_cast<std::uint8_t>(value),
                            static_cast<std::uint32_t>(value * 0x01010101U));
    expect(packer::packGpio2Word(source[value]) == value,
           "scalar mapping preserves D6-D13 user order");
  }
  expect(packer::packGpio2Batch(source.data(), source.size(),
                                destination.data(), destination.size()) ==
             source.size(),
         "batch mapping writes one byte for every raw word");
  for (std::size_t value = 0U; value < destination.size(); ++value) {
    expect(destination[value] == value,
           "batch output matches every possible packed GPIO byte");
  }
  expect(packer::packGpio2Batch(source.data(), source.size(),
                                destination.data(), destination.size() - 1U) ==
             0U,
         "batch mapping rejects a short destination");
}

void testRawBoundariesBecomeExactChecksummedFrames() {
  FakeRawSource source{};
  expect(source.add(0U, 17U) && source.add(17U, 2000U) &&
             source.add(2017U, 2031U) && source.add(4048U, 1U) &&
             source.add(4049U, 4047U),
         "prepare continuous batches that cross two frame boundaries");
  PipelineFixture fixture{};
  expect(fixture.pipeline.startRun(
             42U, constants::ChecksumAlgorithm::kAdler32) ==
             packet::OperationStatus::kOk,
         "start packet epoch for physical GPIO");
  packer::GpioBatchPacker gpio{source, fixture.packed_storage};
  expect(gpio.startRun(42U, constants::ChecksumAlgorithm::kAdler32,
                       fixture.pipeline) == packer::OperationStatus::kOk,
         "start packer against the matching packet/checksum epoch");

  const packer::ServiceReport serviced =
      gpio.service(fixture.pipeline, 8U, 8U);
  expect(serviced.raw_buffers_consumed == 5U &&
             serviced.samples_consumed == 8096U &&
             serviced.frames_packed == 2U && serviced.frames_framed == 2U &&
             !serviced.source_error && !serviced.pipeline_error &&
             source.remaining() == 0U,
         "one cooperative visit packs arbitrary raw boundaries exactly");
  expect(fixture.pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "common fixed ready/transmit queues accept both GPIO frames");

  const wire::DecodedFrame first =
      decodeAndRelease(fixture.pipeline, "decode first checksummed GPIO frame");
  const wire::DecodedFrame second =
      decodeAndRelease(fixture.pipeline, "decode second checksummed GPIO frame");
  const std::uint16_t epoch =
      static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart);
  const std::uint16_t gaps = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore));
  expect(first.header.kind == constants::FrameKind::kGpioData &&
             first.header.run_id == 42U && first.header.sequence == 0U &&
             first.header.first_sample_ticks == 0U &&
             first.header.item_count == constants::kGpioSamplesPerFrame &&
             first.header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kAdler32 &&
             (first.header.flags & epoch) != 0U &&
             (first.header.flags & gaps) == 0U,
         "first frame carries exact run/sequence/timestamp/checksum metadata");
  expect(second.header.run_id == 42U && second.header.sequence == 1U &&
             second.header.first_sample_ticks == 8096U &&
             second.header.flags == 0U,
         "second frame starts at its first packed sample two ticks apart");
  expectPayloadRamp(first, 0U, "first frame preserves every packed sample");
  expectPayloadRamp(second, 4048U,
                    "second frame preserves every packed sample");

  const packer::Snapshot snapshot = gpio.snapshot(fixture.pipeline);
  expect(snapshot.progress.frames_produced == 2U &&
             snapshot.progress.samples_produced == 8096U &&
             snapshot.progress.frames_packed == 2U &&
             snapshot.progress.samples_packed == 8096U &&
             snapshot.progress.frames_framed == 2U &&
             snapshot.progress.samples_framed == 8096U &&
             snapshot.progress.frames_transmitted == 2U &&
             snapshot.progress.samples_transmitted == 8096U &&
             snapshot.progress.samples_dropped == 0U &&
             snapshot.raw_buffers_acquired == 5U &&
             snapshot.raw_buffers_released == 5U,
         "produced/packed/framed/transmitted counters reconcile exactly");

  const packer::StopReport stopped = gpio.stopProduction();
  expect(stopped.partial_samples_discarded == 0U &&
             stopped.packed_frames_to_drain == 0U && gpio.quiescent(),
         "STOP leaves a fully drained packer quiescent");
  fixture.pipeline.stopProduction();
}

void testRawGapAdvancesSequenceWithoutDoubleCountingStatus() {
  FakeRawSource source{};
  expect(source.add(0U, constants::kGpioSamplesPerFrame) &&
             source.add(2U * constants::kGpioSamplesPerFrame,
                        constants::kGpioSamplesPerFrame),
         "prepare one exact missing raw frame");
  PipelineFixture fixture{};
  expect(fixture.pipeline.startRun(51U) == packet::OperationStatus::kOk,
         "start raw-gap packet epoch");
  packer::GpioBatchPacker gpio{source, fixture.packed_storage};
  expect(gpio.startRun(51U, constants::kDefaultChecksumAlgorithm,
                       fixture.pipeline) == packer::OperationStatus::kOk,
         "start raw-gap packer epoch");
  const packer::ServiceReport report = gpio.service(fixture.pipeline, 2U, 2U);
  expect(report.frames_packed == 2U && report.frames_framed == 2U &&
             report.frames_dropped == 1U,
         "raw gap produces two retained frames and one exact source drop");
  expect(fixture.pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "promote retained frames around the raw gap");
  const wire::DecodedFrame first =
      decodeAndRelease(fixture.pipeline, "decode pre-gap GPIO frame");
  const wire::DecodedFrame after =
      decodeAndRelease(fixture.pipeline, "decode post-gap GPIO frame");
  const std::uint16_t gap_flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
      static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore));
  expect(first.header.sequence == 0U && after.header.sequence == 2U &&
             after.header.first_sample_ticks == 16192U &&
             (after.header.flags & gap_flags) == gap_flags,
         "raw loss advances sequence, timestamp, and firmware gap metadata");

  const packer::Snapshot packed = gpio.snapshot(fixture.pipeline);
  expect(packed.progress.frames_produced == 3U &&
             packed.progress.samples_produced == 12144U &&
             packed.progress.raw_gap_samples == 4048U &&
             packed.progress.raw_drop_samples_projected == 4048U &&
             packed.progress.samples_dropped == 4048U,
         "packer reports the exact missing source sample count once");

  stats::Statistics statistics{};
  stats::DataPathProgress data_path{};
  const packet::PipelineSnapshot packet_snapshot = fixture.pipeline.snapshot();
  const packet::SourceCounters &packet_gpio =
      packet_snapshot.sources[packet::streamIndex(packet::Stream::kGpio)];
  data_path.gpio.frames_generated = packet_gpio.frames_produced;
  data_path.gpio.items_generated = packet_gpio.items_produced;
  data_path.gpio.frames_framed = packet_gpio.frames_framed;
  data_path.gpio.items_framed = packet_gpio.items_framed;
  data_path.gpio.frames_transmitted = packet_gpio.frames_transmitted;
  data_path.gpio.items_transmitted = packet_gpio.items_transmitted;
  data_path.gpio.frames_dropped = packet_gpio.frames_dropped;
  data_path.gpio.items_dropped = packet_gpio.items_dropped;
  stats::GpioRawCaptureProgress raw{};
  raw.samples_lost = 4048U;
  statistics.publishDataPath(data_path);
  statistics.publishGpioRawCapture(raw);
  statistics.publishGpioPacker(packed.progress);
  expect(statistics.snapshot().gpio_items_dropped == 4048U,
         "common STATUS projection does not count one raw gap twice");

  gpio.stopProduction();
  fixture.pipeline.stopProduction();
}

void testPackedRingPressureStaysBoundedAndVisible() {
  FakeRawSource source{};
  for (std::uint64_t frame = 0U; frame < 6U; ++frame) {
    expect(source.add(frame * constants::kGpioSamplesPerFrame,
                      constants::kGpioSamplesPerFrame),
           "prepare packed-ring pressure frame");
  }
  PipelineFixture fixture{};
  expect(fixture.pipeline.startRun(61U) == packet::OperationStatus::kOk,
         "start packed-pressure packet epoch");
  packer::GpioBatchPacker gpio{source, fixture.packed_storage};
  expect(gpio.startRun(61U, constants::kDefaultChecksumAlgorithm,
                       fixture.pipeline) == packer::OperationStatus::kOk,
         "start packed-pressure packer epoch");

  const packer::ServiceReport filled = gpio.service(fixture.pipeline, 5U, 0U);
  expect(filled.frames_packed == teensy_daq::board::kGpioPackedRingDepth &&
             filled.frames_dropped == 1U &&
             gpio.snapshot(fixture.pipeline).ready_depth ==
                 teensy_daq::board::kGpioPackedRingDepth,
         "fixed packed ring drops a complete fifth frame without allocation");
  const packer::ServiceReport drained = gpio.service(fixture.pipeline, 0U, 4U);
  expect(drained.frames_framed == 4U,
         "bounded framing drains the four retained packed buffers");
  const packer::ServiceReport resumed = gpio.service(fixture.pipeline, 1U, 1U);
  expect(resumed.frames_packed == 1U && resumed.frames_framed == 1U &&
             source.remaining() == 0U,
         "capture resumes after packed pressure without stale ownership");

  expect(fixture.pipeline.serviceReadyFrames(5U).frames_promoted == 5U,
         "common queues retain all non-dropped pressure frames");
  for (std::uint32_t expected_sequence : {0U, 1U, 2U, 3U, 5U}) {
    const wire::DecodedFrame frame =
        decodeAndRelease(fixture.pipeline, "decode pressure-sequence frame");
    expect(frame.header.sequence == expected_sequence,
           "packed-ring drop remains visible as one sequence skip");
    if (expected_sequence == 5U) {
      const std::uint16_t gaps = static_cast<std::uint16_t>(
          static_cast<std::uint16_t>(constants::FrameFlag::kGapBefore) |
          static_cast<std::uint16_t>(constants::FrameFlag::kOverrunBefore));
      expect(frame.header.first_sample_ticks == 40480U &&
                 (frame.header.flags & gaps) == gaps,
             "first post-pressure frame carries exact gap timestamp/flags");
    }
  }
  const packer::Snapshot snapshot = gpio.snapshot(fixture.pipeline);
  expect(snapshot.progress.packer_drop_samples == 4048U &&
             snapshot.progress.packer_drop_samples_projected == 4048U &&
             snapshot.progress.samples_dropped == 4048U &&
             snapshot.ready_high_water ==
                 teensy_daq::board::kGpioPackedRingDepth,
         "pressure counters and high-water mark are exact");
  gpio.stopProduction();
  fixture.pipeline.stopProduction();
}

void testStopDrainsReadyFrameAndDiscardsOnlyPartialTail() {
  FakeRawSource source{};
  expect(source.add(0U, constants::kGpioSamplesPerFrame) &&
             source.add(constants::kGpioSamplesPerFrame, 37U),
         "prepare one complete frame followed by a partial STOP tail");
  PipelineFixture fixture{};
  expect(fixture.pipeline.startRun(71U) == packet::OperationStatus::kOk,
         "start STOP-race packet epoch");
  packer::GpioBatchPacker gpio{source, fixture.packed_storage};
  expect(gpio.startRun(71U, constants::kDefaultChecksumAlgorithm,
                       fixture.pipeline) == packer::OperationStatus::kOk,
         "start STOP-race packer epoch");

  const packer::ServiceReport filled =
      gpio.service(fixture.pipeline, 2U, 0U);
  const packer::Snapshot before_stop = gpio.snapshot(fixture.pipeline);
  expect(filled.raw_buffers_consumed == 2U &&
             filled.samples_consumed ==
                 constants::kGpioSamplesPerFrame + 37U &&
             filled.frames_packed == 1U &&
             before_stop.ready_depth == 1U &&
             before_stop.current_frame_samples == 37U &&
             before_stop.buffer_states[0] == packer::BufferState::kReady &&
             before_stop.buffer_states[1] == packer::BufferState::kFilling,
         "queue ownership separates a ready frame from its partial successor");

  const packer::StopReport stopped = gpio.stopProduction();
  const packer::Snapshot after_stop = gpio.snapshot(fixture.pipeline);
  expect(stopped.partial_samples_discarded == 37U &&
             stopped.packed_frames_to_drain == 1U &&
             after_stop.ready_depth == 1U &&
             after_stop.current_frame_samples == 0U &&
             after_stop.buffer_states[0] == packer::BufferState::kReady &&
             after_stop.buffer_states[1] == packer::BufferState::kFree &&
             !after_stop.running && !after_stop.quiescent,
         "STOP recycles only the partial tail while retaining the ready frame");
  expect(gpio.startRun(72U, constants::kDefaultChecksumAlgorithm,
                       fixture.pipeline) ==
             packer::OperationStatus::kNotQuiescent,
         "a new run cannot overtake the old run's ready frame");

  const packer::ServiceReport drained =
      gpio.service(fixture.pipeline, 8U, 1U);
  expect(drained.raw_buffers_consumed == 0U &&
             drained.frames_framed == 1U && gpio.quiescent(),
         "post-STOP service drains old ready ownership without acquiring input");
  expect(fixture.pipeline.serviceReadyFrames(1U).frames_promoted == 1U,
         "the retained STOP-race frame reaches the transmit queue");
  const wire::DecodedFrame frame =
      decodeAndRelease(fixture.pipeline, "decode retained STOP-race frame");
  expect(frame.header.run_id == 71U && frame.header.sequence == 0U &&
             frame.header.first_sample_ticks == 0U,
         "the drained frame retains its original run and timestamp epoch");

  const packer::Snapshot final = gpio.snapshot(fixture.pipeline);
  expect(final.raw_buffers_acquired == 2U &&
             final.raw_buffers_released == 2U &&
             final.progress.samples_produced ==
                 constants::kGpioSamplesPerFrame + 37U &&
             final.progress.packer_drop_samples == 37U,
         "STOP counters account the exact partial tail and balanced leases");
  fixture.pipeline.stopProduction();
}

void testRawWordDiagnosticIsExplicitAndBounded() {
  FakeRawSource source{};
  expect(source.add(0U, constants::kGpioSamplesPerFrame),
         "prepare one diagnostic raw buffer");
  capture::BoundedRawWordDiagnostic diagnostic{source};
  expect(diagnostic.acquire(0U).status ==
                 capture::OperationStatus::kInvalidDiagnosticLimit &&
             diagnostic.acquire(capture::kRawWordDiagnosticMaxSamples + 1U)
                     .status ==
                 capture::OperationStatus::kInvalidDiagnosticLimit &&
             source.remaining() == 1U,
         "raw-word troubleshooting rejects unbounded requests before ownership");
  const capture::RawWordDiagnosticAcquireResult acquired =
      diagnostic.acquire(64U);
  expect(acquired.ok() && acquired.lease.valid() &&
             acquired.lease.sample_count == 64U &&
             packer::packGpio2Word(acquired.lease.words[37U]) == 37U,
         "bounded diagnostic exposes only the requested raw-word prefix");
  expect(diagnostic.release(acquired.lease) ==
                 capture::OperationStatus::kOk &&
             source.remaining() == 0U,
         "bounded diagnostic releases the complete underlying DMA lease");
}

}  // namespace

int main() {
  testExactMappingAndBatchPrimitive();
  testRawBoundariesBecomeExactChecksummedFrames();
  testRawGapAdvancesSequenceWithoutDoubleCountingStatus();
  testPackedRingPressureStaysBoundedAndVisible();
  testStopDrainsReadyFrameAndDiscardsOnlyPartialTail();
  testRawWordDiagnosticIsExplicitAndBounded();
  if (failures != 0) {
    std::cerr << failures << " GPIO batch packer assertion(s) failed\n";
    return 1;
  }
  std::cout << "GPIO batch packer tests passed\n";
  return 0;
}
