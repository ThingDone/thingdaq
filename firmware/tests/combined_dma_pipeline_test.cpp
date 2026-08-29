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

#include "adc_dma_capture.h"
#include "adc_frame_packer.h"
#include "gpio_batch_packer.h"
#include "gpio_raw_capture.h"
#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "statistics.h"
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

namespace adc_capture = teensy_daq::adc_capture;
namespace adc_packer = teensy_daq::adc_packer;
namespace board = teensy_daq::board;
namespace constants = teensy_daq::protocol_v1;
namespace gpio_capture = teensy_daq::gpio_capture;
namespace gpio_packer = teensy_daq::gpio_packer;
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

class TrackingCache final : public teensy_daq::dma::CacheMaintenance {
 public:
  void discardBeforeDmaWrite(void *address, std::size_t bytes) override {
    Record &record = findOrCreate(address, bytes);
    if (record.bytes != bytes) {
      ownership_violation_ = true;
    }
    record.cpu_owned = false;
    ++discard_calls;
  }

  void invalidateBeforeCpuRead(void *address, std::size_t bytes) override {
    Record &record = findOrCreate(address, bytes);
    if (record.bytes != bytes || record.cpu_owned) {
      ownership_violation_ = true;
    }
    record.cpu_owned = true;
    ++invalidate_calls;
  }

  void observeDmaWrite(void *address) {
    const std::uintptr_t target = reinterpret_cast<std::uintptr_t>(address);
    for (const Record &record : records_) {
      const std::uintptr_t start =
          reinterpret_cast<std::uintptr_t>(record.address);
      if (target >= start && target < start + record.bytes) {
        if (record.cpu_owned) {
          ownership_violation_ = true;
        }
        ++dma_write_checks;
        return;
      }
    }
    ownership_violation_ = true;
  }

  bool allReleasedToDma() const {
    return std::all_of(records_.begin(), records_.end(),
                       [](const Record &record) {
                         return !record.cpu_owned;
                       });
  }

  bool ownershipViolation() const { return ownership_violation_; }

  std::size_t discard_calls = 0U;
  std::size_t invalidate_calls = 0U;
  std::size_t dma_write_checks = 0U;

 private:
  struct Record {
    void *address = nullptr;
    std::size_t bytes = 0U;
    bool cpu_owned = false;
  };

  Record &findOrCreate(void *address, std::size_t bytes) {
    for (Record &record : records_) {
      if (record.address == address) {
        return record;
      }
    }
    records_.push_back({address, bytes, false});
    return records_.back();
  }

  std::vector<Record> records_{};
  bool ownership_violation_ = false;
};

class TrackingCriticalSection final
    : public teensy_daq::dma::CriticalSection {
 public:
  std::uint32_t enter() override {
    ++depth_;
    max_depth = std::max(max_depth, depth_);
    if (depth_ != 1U) {
      serialization_violation = true;
    }
    return depth_;
  }

  void exit(std::uint32_t) override {
    if (depth_ != 1U) {
      serialization_violation = true;
    }
    if (depth_ != 0U) {
      --depth_;
    }
  }

  std::uint32_t max_depth = 0U;
  bool serialization_violation = false;

 private:
  std::uint32_t depth_ = 0U;
};

std::uint32_t rawGpioWord(std::uint8_t value) {
  std::uint32_t result = 0U;
  for (std::size_t bit = 0U;
       bit < board::countOf(board::kGpioMappingsByPackedBit); ++bit) {
    if ((value & static_cast<std::uint8_t>(1U << bit)) != 0U) {
      result |= std::uint32_t{1U}
                << board::kGpioMappingsByPackedBit[bit].gpio2_bit;
    }
  }
  return result;
}

class AdcDmaDriver {
 public:
  AdcDmaDriver(adc_capture::PairCaptureRing &ring, TrackingCache &cache)
      : ring_(ring), cache_(cache) {}

  adc_capture::PrimeResult prime(std::uint32_t epoch) {
    const adc_capture::PrimeResult result = ring_.prime(epoch);
    if (result.ok()) {
      const adc_capture::ReservationResult third =
          ring_.reserveGeneration(epoch, result.active_generation + 2U);
      const adc_capture::ReservationResult fourth =
          ring_.reserveGeneration(epoch, result.active_generation + 3U);
      if (!third.ok() || !fourth.ok()) {
        return {};
      }
      epoch_ = epoch;
      generations_ = {result.active_generation, result.active_generation};
      destinations_ = {result.active_destination,
                       result.active_destination};
      next_destinations_ = {result.queued_destination,
                            result.queued_destination};
    }
    return result;
  }

  adc_capture::CompletionResult complete(std::size_t converter) {
    if (converter >= adc_capture::kConverterCount) {
      return {};
    }
    writeDestination(converter, destinations_[converter],
                     generations_[converter]);
    const adc_capture::CompletionResult result = ring_.onMajorLoopComplete(
        static_cast<std::uint8_t>(converter), epoch_,
        generations_[converter], destinations_[converter]);
    const std::uint32_t completed_generation = generations_[converter];
    if (result.consumed) {
      ++generations_[converter];
      destinations_[converter] = next_destinations_[converter];
      next_destinations_[converter] = result.future_destination;
    }
    if (result.pair_ready || result.pair_lost) {
      const adc_capture::ReservationResult future = ring_.reserveGeneration(
          epoch_, completed_generation + 4U);
      if (!future.ok()) {
        return {};
      }
    }
    return result;
  }

  std::array<adc_capture::ChannelStopState, adc_capture::kConverterCount>
  stopStates() const {
    std::array<adc_capture::ChannelStopState,
               adc_capture::kConverterCount>
        states{};
    for (std::size_t converter = 0U;
         converter < adc_capture::kConverterCount; ++converter) {
      states[converter].generation = generations_[converter];
      states[converter].destination = destinations_[converter];
    }
    return states;
  }

  std::uint8_t destination(std::size_t converter) const {
    return destinations_[converter];
  }

 private:
  void writeDestination(std::size_t converter, std::uint8_t destination,
                        std::uint32_t generation) {
    std::uint16_t *const output = ring_.destinationHalfword(
        destination, static_cast<std::uint8_t>(converter));
    if (output == nullptr) {
      return;
    }
    cache_.observeDmaWrite(output);
    if (destination == adc_capture::kOverflowDestination) {
      output[0] = static_cast<std::uint16_t>(generation & 0x0FFFU);
      return;
    }
    for (std::size_t pair = 0U; pair < constants::kAdcPairsPerFrame;
         ++pair) {
      output[pair * adc_capture::kConverterCount] =
          static_cast<std::uint16_t>(
              (generation + pair + converter) & 0x0FFFU);
    }
  }

  adc_capture::PairCaptureRing &ring_;
  TrackingCache &cache_;
  std::array<std::uint32_t, adc_capture::kConverterCount> generations_{};
  std::array<std::uint8_t, adc_capture::kConverterCount> destinations_{};
  std::array<std::uint8_t, adc_capture::kConverterCount>
      next_destinations_{};
  std::uint32_t epoch_ = 0U;
};

class GpioDmaDriver {
 public:
  GpioDmaDriver(gpio_capture::RawCaptureRing &ring, TrackingCache &cache)
      : ring_(ring), cache_(cache) {}

  gpio_capture::PrimeResult prime() {
    const gpio_capture::PrimeResult result = ring_.prime();
    if (result.ok()) {
      active_destination_ = result.active_destination;
      queued_destination_ = result.queued_destination;
      generation_ = 0U;
    }
    return result;
  }

  gpio_capture::MajorLoopResult complete() {
    writeDestination(active_destination_, generation_);
    const gpio_capture::MajorLoopResult result = ring_.onMajorLoopComplete();
    if (result.ok()) {
      active_destination_ = result.active_destination;
      queued_destination_ = result.queued_destination;
      ++generation_;
    }
    return result;
  }

  std::uint8_t activeDestination() const { return active_destination_; }
  std::uint8_t queuedDestination() const { return queued_destination_; }

 private:
  void writeDestination(std::uint8_t destination,
                        std::uint64_t generation) {
    std::uint32_t *const output = ring_.destinationWords(destination);
    if (output == nullptr) {
      return;
    }
    cache_.observeDmaWrite(output);
    if (destination == gpio_capture::kOverflowDestination) {
      output[0] = rawGpioWord(static_cast<std::uint8_t>(generation));
      return;
    }
    for (std::size_t sample = 0U;
         sample < constants::kGpioSamplesPerFrame; ++sample) {
      output[sample] = rawGpioWord(static_cast<std::uint8_t>(
          generation + static_cast<std::uint64_t>(sample)));
    }
  }

  gpio_capture::RawCaptureRing &ring_;
  TrackingCache &cache_;
  std::uint8_t active_destination_ = gpio_capture::kInvalidDestination;
  std::uint8_t queued_destination_ = gpio_capture::kInvalidDestination;
  std::uint64_t generation_ = 0U;
};

struct CombinedPipelineFixture {
  TrackingCache adc_cache{};
  TrackingCache gpio_cache{};
  TrackingCriticalSection adc_critical{};
  TrackingCriticalSection gpio_critical{};
  adc_capture::PairBufferStorage adc_storage{};
  adc_capture::PairOverflowSink adc_sink{};
  adc_capture::PairCaptureRing adc_ring{adc_storage, adc_sink, adc_cache,
                                        adc_critical};
  AdcDmaDriver adc_driver{adc_ring, adc_cache};
  gpio_capture::RawBufferStorage gpio_raw_storage{};
  gpio_capture::RawOverflowSink gpio_sink{};
  gpio_capture::RawCaptureRing gpio_ring{
      gpio_raw_storage, gpio_sink, gpio_cache, gpio_critical};
  GpioDmaDriver gpio_driver{gpio_ring, gpio_cache};
  packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline pipeline{packet_storage};
  adc_packer::AdcFramePacker adc_frame_packer{adc_ring};
  gpio_packer::PackedBufferStorage gpio_packed_storage{};
  gpio_packer::GpioBatchPacker gpio_frame_packer{gpio_ring,
                                                 gpio_packed_storage};
  stats::Statistics statistics{};
};

template <std::size_t Capacity>
std::vector<std::uint8_t> bytes(const wire::FixedFrame<Capacity> &frame) {
  return {frame.data(), frame.data() + frame.size()};
}

wire::CommandFrame pingRequest(std::uint32_t request_id,
                               std::uint64_t nonce) {
  std::array<std::uint8_t, constants::kPingRequestPayloadSize> payload{};
  expect(wire::storeU64({payload.data(), payload.size()},
                        constants::kPingRequestNonceOffset, nonce),
         "encode concurrent PING request nonce");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kPingRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode concurrent PING request");
  return frame;
}

wire::ControlFrame pingResponse(const wire::ParsedCommand &command,
                                std::uint32_t run_id) {
  wire::ControlFrame frame{};
  expect(wire::encodePingResponse(command.request, run_id, frame).ok(),
         "encode bounded PING response during combined traffic");
  return frame;
}

class FakeCdcStream final : public usb::CdcByteStream {
 public:
  usb::IoCount available() override {
    return static_cast<usb::IoCount>(input_.size() - input_offset_);
  }

  usb::IoCount read(std::uint8_t *destination,
                    std::size_t capacity) override {
    const std::size_t count =
        std::min(capacity, input_.size() - input_offset_);
    std::copy_n(input_.data() + input_offset_, count, destination);
    input_offset_ += count;
    return static_cast<usb::IoCount>(count);
  }

  usb::IoCount availableForWrite() override {
    if (!writable_plan.empty()) {
      const usb::IoCount value = writable_plan.front();
      writable_plan.pop_front();
      return value;
    }
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

  void appendInput(const wire::CommandFrame &frame) {
    const std::vector<std::uint8_t> encoded = bytes(frame);
    input_.insert(input_.end(), encoded.begin(), encoded.end());
  }

  std::deque<usb::IoCount> writable_plan{};
  std::deque<usb::IoCount> write_plan{};
  std::vector<std::uint8_t> output{};

 private:
  std::vector<std::uint8_t> input_{};
  std::size_t input_offset_ = 0U;
};

std::vector<wire::FrameHeader> decodeOutput(
    const std::vector<std::uint8_t> &output) {
  std::vector<wire::FrameHeader> headers{};
  std::size_t offset = 0U;
  while (offset < output.size()) {
    std::uint32_t length = 0U;
    const wire::ByteView remaining{output.data() + offset,
                                   output.size() - offset};
    if (!wire::loadU32(remaining, constants::kHeaderTotalLengthOffset,
                       length) ||
        length == 0U || length > remaining.size) {
      expect(false, "USB output contains only bounded complete frames");
      break;
    }
    wire::DecodedFrame decoded{};
    if (!wire::decodeFrame({remaining.data, length}, decoded).ok()) {
      expect(false, "every combined USB output frame validates");
      break;
    }
    headers.push_back(decoded.header);
    offset += length;
  }
  expect(offset == output.size(),
         "combined USB output has no partial trailing bytes");
  return headers;
}

void completeInterval(CombinedPipelineFixture &fixture,
                      std::size_t interval) {
  adc_capture::CompletionResult first{};
  adc_capture::CompletionResult second{};
  gpio_capture::MajorLoopResult gpio{};
  if ((interval & 1U) == 0U) {
    first = fixture.adc_driver.complete(1U);
    gpio = fixture.gpio_driver.complete();
    second = fixture.adc_driver.complete(0U);
  } else {
    first = fixture.adc_driver.complete(0U);
    second = fixture.adc_driver.complete(1U);
    gpio = fixture.gpio_driver.complete();
  }
  expect(first.consumed && second.consumed && gpio.ok(),
         "adversarial ADC/GPIO completion ordering remains consumable");
}

void testConcurrentPressureWrapUsbAndCounterReconciliation() {
  CombinedPipelineFixture fixture{};
  constexpr std::uint32_t kRunId = 91U;
  constexpr std::uint64_t kEpochTicks = 0x123456789ABCULL;
  constexpr std::uint32_t kFirstSequence =
      std::numeric_limits<std::uint32_t>::max() - 2U;
  constexpr std::size_t kInitialCompletions = 6U;
  constexpr std::size_t kTotalCompletions = 11U;
  constexpr std::size_t kRetainedFrames = 7U;
  constexpr std::size_t kDroppedFrames = 4U;

  expect(fixture.pipeline.startRun(kRunId) ==
                 packet::OperationStatus::kOk,
         "start one combined pressure epoch");
  packet::PacketBufferPipelineTestAccess::setNextSequence(
      fixture.pipeline, packet::Stream::kAdc, kFirstSequence);
  packet::PacketBufferPipelineTestAccess::setNextSequence(
      fixture.pipeline, packet::Stream::kGpio, kFirstSequence);
  expect(fixture.adc_frame_packer.startRun(
             kRunId, constants::kDefaultChecksumAlgorithm,
             fixture.pipeline, kEpochTicks) ==
                 adc_packer::OperationStatus::kOk &&
             fixture.gpio_frame_packer.startRun(
                 kRunId, constants::kDefaultChecksumAlgorithm,
                 fixture.pipeline, kEpochTicks) ==
                 gpio_packer::OperationStatus::kOk &&
             fixture.adc_driver.prime(kRunId).ok() &&
             fixture.gpio_driver.prime().ok(),
         "both DMA rings and packers snapshot the same run and epoch");

  for (std::size_t interval = 0U; interval < kInitialCompletions;
       ++interval) {
    completeInterval(fixture, interval);
  }
  const adc_capture::Snapshot adc_pressured = fixture.adc_ring.snapshot();
  const gpio_capture::Snapshot gpio_pressured = fixture.gpio_ring.snapshot();
  expect(adc_pressured.ready_depth == board::kAdcDmaRingDepth &&
             adc_pressured.progress.ready_high_water ==
                 board::kAdcDmaRingDepth &&
             adc_pressured.progress.ring_overruns == 0U &&
             gpio_pressured.ready_depth == board::kGpioRawDmaRingDepth &&
             gpio_pressured.progress.ready_high_water ==
                 board::kGpioRawDmaRingDepth &&
             gpio_pressured.progress.raw_ring_overruns == 2U,
         "different-depth source rings expose only their expected initial pressure losses");

  const adc_packer::ServiceReport adc_initial =
      fixture.adc_frame_packer.service(fixture.pipeline,
                                       board::kAdcDmaRingDepth);
  const gpio_packer::ServiceReport gpio_pack_only =
      fixture.gpio_frame_packer.service(
          fixture.pipeline, board::kGpioRawDmaRingDepth, 0U);
  const gpio_packer::Snapshot packed_pressure =
      fixture.gpio_frame_packer.snapshot(fixture.pipeline);
  expect(adc_initial.frames_framed == board::kAdcDmaRingDepth &&
             gpio_pack_only.frames_packed ==
                 board::kGpioPackedRingDepth &&
             gpio_pack_only.frames_framed == 0U &&
             packed_pressure.ready_depth == board::kGpioPackedRingDepth &&
             packed_pressure.ready_high_water ==
                 board::kGpioPackedRingDepth,
         "bounded service independently pressures the full packed GPIO ring");
  expect(fixture.gpio_frame_packer
                 .service(fixture.pipeline, 0U,
                          board::kGpioPackedRingDepth)
                 .frames_framed == board::kGpioPackedRingDepth,
         "a later scheduler visit drains packed GPIO ownership into packets");

  for (std::size_t interval = kInitialCompletions;
       interval < kTotalCompletions; ++interval) {
    completeInterval(fixture, interval);
  }
  expect(fixture.adc_frame_packer.service(fixture.pipeline, 1U)
                     .frames_framed == 1U &&
             fixture.gpio_frame_packer.service(fixture.pipeline, 3U, 3U)
                     .frames_framed == 3U,
         "the next retained interval projects every intervening raw loss");

  const adc_capture::StopReport adc_stop =
      fixture.adc_ring.stop(fixture.adc_driver.stopStates());
  const gpio_capture::StopReport gpio_stop = fixture.gpio_ring.stop(0U);
  (void)fixture.adc_frame_packer.stopProduction();
  (void)fixture.gpio_frame_packer.stopProduction();
  expect(adc_stop.ok() && gpio_stop.status ==
                              gpio_capture::OperationStatus::kOk &&
             fixture.adc_ring.quiescent() && fixture.gpio_ring.quiescent(),
         "source STOP releases only the still-DMA-owned future generations");

  const packet::PromotionReport promoted =
      fixture.pipeline.serviceReadyFrames(2U * kRetainedFrames);
  const packet::StopReport packet_stop = fixture.pipeline.stopProduction();
  expect(promoted.frames_promoted == 2U * kRetainedFrames &&
             !promoted.invariant_error &&
             packet_stop.ready_frames_to_drain == 0U &&
             packet_stop.transmitting_frames_to_drain ==
                 2U * kRetainedFrames,
         "fair scheduling promotes the retained equal-coverage backlog without ownership loss");

  FakeCdcStream stream{};
  stream.writable_plan = {
      std::numeric_limits<usb::IoCount>::max(), 0};
  stream.write_plan = {700};
  usb::CdcTransport transport{stream, fixture.statistics,
                              &fixture.pipeline};
  const usb::ServiceReport partial = transport.serviceTransmit();
  expect(partial.stalled && partial.bytes_written == 700U &&
             fixture.pipeline.queuedFrames() ==
                 2U * kRetainedFrames,
         "a partial USB prefix and zero-capacity stall retain the active data frame");

  stream.appendInput(pingRequest(501U, 0x1111222233334444ULL));
  stream.appendInput(pingRequest(502U, 0x5555666677778888ULL));
  (void)transport.serviceReceive();
  expect(transport.commandQueueDepth() == 2U,
         "two commands arrive while one combined data frame is partial");
  for (std::size_t response = 0U; response < 2U; ++response) {
    wire::ParsedCommand command{};
    expect(transport.takeCommand(command) &&
               transport.queueResponse(pingResponse(command, kRunId)),
           "each concurrent command reserves one bounded response");
  }

  for (std::size_t visit = 0U;
       visit < 64U && transport.hasPendingTransmission(); ++visit) {
    (void)transport.serviceTransmit();
  }
  expect(!transport.hasPendingTransmission(),
         "bounded USB visits drain responses and all retained data");

  const std::vector<wire::FrameHeader> headers = decodeOutput(stream.output);
  expect(headers.size() == 2U * kRetainedFrames + 2U &&
             (headers[0].kind == constants::FrameKind::kAdcData ||
              headers[0].kind == constants::FrameKind::kGpioData) &&
             headers[1].kind == constants::FrameKind::kPingResponse &&
             headers[2].kind == constants::FrameKind::kPingResponse &&
             headers[1].request_id == 501U &&
             headers[2].request_id == 502U,
         "responses wait for the active data tail, then precede the next data frame");

  const std::array<std::array<std::uint32_t, kRetainedFrames>,
                   packet::kStreamCount>
      expected_sequences{{
          {kFirstSequence, kFirstSequence + 1U, kFirstSequence + 2U,
           0U, 1U, 2U, 7U},
          {kFirstSequence, kFirstSequence + 1U, kFirstSequence + 2U,
           0U, 5U, 6U, 7U},
      }};
  std::array<std::vector<std::uint32_t>, packet::kStreamCount>
      observed_sequences{};
  std::array<bool, packet::kStreamCount> gap_observed{};
  for (const wire::FrameHeader &header : headers) {
    if (header.kind != constants::FrameKind::kAdcData &&
        header.kind != constants::FrameKind::kGpioData) {
      continue;
    }
    const std::size_t source =
        header.kind == constants::FrameKind::kAdcData ? 0U : 1U;
    observed_sequences[source].push_back(header.sequence);
    gap_observed[source] =
        gap_observed[source] ||
        (header.flags & static_cast<std::uint16_t>(
                            constants::FrameFlag::kGapBefore)) != 0U;
    expect(header.run_id == kRunId,
           "all drained data remains in the pressured run");
  }
  for (std::size_t source = 0U; source < packet::kStreamCount; ++source) {
    expect(std::equal(observed_sequences[source].begin(),
                      observed_sequences[source].end(),
                      expected_sequences[source].begin(),
                      expected_sequences[source].end()) &&
               gap_observed[source],
           "each source wraps modulo 2^32 and exposes its four-frame pressure gap");
  }

  const adc_capture::Snapshot adc = fixture.adc_ring.snapshot();
  const gpio_capture::Snapshot gpio = fixture.gpio_ring.snapshot();
  const adc_packer::Snapshot adc_packed =
      fixture.adc_frame_packer.snapshot(fixture.pipeline);
  const gpio_packer::Snapshot gpio_packed =
      fixture.gpio_frame_packer.snapshot(fixture.pipeline);
  const packet::PipelineSnapshot packets = fixture.pipeline.snapshot();
  const usb::TransportSnapshot usb_counters = transport.snapshot();
  const std::uint64_t adc_pairs =
      kTotalCompletions * constants::kAdcPairsPerFrame;
  const std::uint64_t gpio_samples =
      kTotalCompletions * constants::kGpioSamplesPerFrame;
  const std::uint64_t adc_loss =
      kDroppedFrames * constants::kAdcPairsPerFrame;
  const std::uint64_t gpio_loss =
      kDroppedFrames * constants::kGpioSamplesPerFrame;
  expect(adc.progress.channel_major_loops ==
                 std::array<std::uint64_t, 2U>{kTotalCompletions,
                                               kTotalCompletions} &&
             adc.progress.channel_results ==
                 std::array<std::uint64_t, 2U>{adc_pairs, adc_pairs} &&
             adc.progress.paired_major_loops == kTotalCompletions &&
             adc.progress.buffers_completed == kRetainedFrames &&
             adc.progress.buffers_acquired == kRetainedFrames &&
             adc.progress.buffers_released == kRetainedFrames &&
             adc.progress.pairs_captured == adc_pairs &&
             adc.progress.pairs_delivered ==
                 kRetainedFrames * constants::kAdcPairsPerFrame &&
             adc.progress.pairs_lost == adc_loss,
         "ADC channel, pair, lease, and raw-loss counters reconcile exactly");
  expect(gpio.progress.major_loops_completed == kTotalCompletions &&
             gpio.progress.buffers_completed == kRetainedFrames &&
             gpio.progress.buffers_acquired == kRetainedFrames &&
             gpio.progress.buffers_released == kRetainedFrames &&
             gpio.progress.samples_captured == gpio_samples &&
             gpio.progress.samples_delivered ==
                 kRetainedFrames * constants::kGpioSamplesPerFrame &&
             gpio.progress.samples_lost == gpio_loss,
         "GPIO raw completion, lease, sample, and loss counters reconcile exactly");
  expect(adc_packed.progress.frames_consumed == kRetainedFrames &&
             adc_packed.progress.pairs_consumed ==
                 kRetainedFrames * constants::kAdcPairsPerFrame &&
             adc_packed.progress.raw_gap_pairs == adc_loss &&
             adc_packed.progress.raw_drop_pairs_projected == adc_loss &&
             gpio_packed.progress.frames_produced == kTotalCompletions &&
             gpio_packed.progress.samples_produced == gpio_samples &&
             gpio_packed.progress.frames_packed == kRetainedFrames &&
             gpio_packed.progress.samples_packed ==
                 kRetainedFrames * constants::kGpioSamplesPerFrame &&
             gpio_packed.progress.raw_gap_samples == gpio_loss &&
             gpio_packed.progress.raw_drop_samples_projected == gpio_loss &&
             gpio_packed.ready_high_water == board::kGpioPackedRingDepth,
         "ADC and GPIO packer counters reconcile raw gaps with projected drops");

  for (packet::Stream stream_kind : {packet::Stream::kAdc,
                                     packet::Stream::kGpio}) {
    const std::size_t source = packet::streamIndex(stream_kind);
    const packet::SourceCounters &counter = packets.sources[source];
    const packet::SourceByteCounters &byte_counter =
        packets.source_bytes[source];
    expect(counter.frames_produced == kTotalCompletions &&
               counter.frames_framed == kRetainedFrames &&
               counter.frames_emitted == kRetainedFrames &&
               counter.frames_transmitted == kRetainedFrames &&
               counter.frames_dropped == kDroppedFrames &&
               counter.ready_queue_high_water == kRetainedFrames &&
               counter.transmit_queue_high_water == kRetainedFrames &&
               byte_counter.payload_bytes_produced ==
                   kTotalCompletions * constants::kDataPayloadBytes &&
               byte_counter.payload_bytes_framed ==
                   kRetainedFrames * constants::kDataPayloadBytes &&
               byte_counter.payload_bytes_dropped ==
                   kDroppedFrames * constants::kDataPayloadBytes &&
               byte_counter.framed_bytes_transmitted ==
                   kRetainedFrames * constants::kDataFrameBytes,
           "per-source frame, item, byte, drop, and queue counters reconcile");
  }
  expect(packets.ready_queue_high_water == 2U * kRetainedFrames &&
             packets.transmit_queue_high_water ==
                 2U * kRetainedFrames &&
             packets.buffers_owned_high_water ==
                 2U * kRetainedFrames &&
             packets.data_payload_bytes_transmitted ==
                 2U * kRetainedFrames * constants::kDataPayloadBytes &&
             packets.data_framed_bytes_transmitted ==
                 2U * kRetainedFrames * constants::kDataFrameBytes &&
             usb_counters.lower_priority_frames_completed ==
                 2U * kRetainedFrames &&
             usb_counters.partial_write_events >= 1U &&
             usb_counters.tx_stall_events >= 1U &&
             usb_counters.command_queue_high_water == 2U &&
             usb_counters.response_queue_high_water == 2U,
         "shared queue, byte, USB-stall, and command high-water counters reconcile");
  expect(!fixture.adc_cache.ownershipViolation() &&
             !fixture.gpio_cache.ownershipViolation() &&
             fixture.adc_cache.allReleasedToDma() &&
             fixture.gpio_cache.allReleasedToDma() &&
             fixture.adc_cache.dma_write_checks ==
                 2U * kTotalCompletions &&
             fixture.gpio_cache.dma_write_checks ==
                 kTotalCompletions &&
             !fixture.adc_critical.serialization_violation &&
             !fixture.gpio_critical.serialization_violation,
         "cache and critical-section traces never expose one ring to two owners");
}

void testBothRingsRejectStaleLeasesAcrossRunBoundaries() {
  TrackingCache adc_cache{};
  TrackingCache gpio_cache{};
  TrackingCriticalSection adc_critical{};
  TrackingCriticalSection gpio_critical{};
  adc_capture::PairBufferStorage adc_storage{};
  adc_capture::PairOverflowSink adc_sink{};
  adc_capture::PairCaptureRing adc_ring{adc_storage, adc_sink, adc_cache,
                                        adc_critical};
  AdcDmaDriver adc_driver{adc_ring, adc_cache};
  gpio_capture::RawBufferStorage gpio_storage{};
  gpio_capture::RawOverflowSink gpio_sink{};
  gpio_capture::RawCaptureRing gpio_ring{gpio_storage, gpio_sink,
                                         gpio_cache, gpio_critical};
  GpioDmaDriver gpio_driver{gpio_ring, gpio_cache};

  constexpr std::uint32_t kFirstRun = 100U;
  expect(adc_driver.prime(kFirstRun).ok() && gpio_driver.prime().ok(),
         "prime both ownership rings for the first run");
  expect(adc_driver.complete(1U).consumed &&
             adc_driver.complete(0U).pair_ready &&
             gpio_driver.complete().ok(),
         "publish one complete buffer in each ring");
  const adc_capture::AcquireResult old_adc = adc_ring.acquireReady();
  const gpio_capture::AcquireResult old_gpio = gpio_ring.acquireReady();
  expect(old_adc.ok() && old_gpio.ok() &&
             adc_ring.acquireReady().status ==
                 adc_capture::OperationStatus::kNoReadyBuffer &&
             gpio_ring.acquireReady().status ==
                 gpio_capture::OperationStatus::kNoReadyBuffer,
         "a ready buffer grants exactly one CPU lease");

  const adc_capture::CompletionResult adc_ahead = adc_driver.complete(0U);
  const adc_capture::CompletionResult adc_caught_up =
      adc_driver.complete(1U);
  const gpio_capture::MajorLoopResult gpio_ahead = gpio_driver.complete();
  expect(adc_ahead.future_destination != old_adc.handle.buffer_index &&
             adc_caught_up.future_destination !=
                 old_adc.handle.buffer_index &&
             gpio_ahead.queued_destination != old_gpio.handle.buffer_index,
         "DMA scheduling never reuses a CPU-leased ADC or GPIO buffer");

  const adc_capture::StopReport first_adc_stop =
      adc_ring.stop(adc_driver.stopStates());
  const gpio_capture::StopReport first_gpio_stop = gpio_ring.stop(0U);
  expect(first_adc_stop.reading_buffers_to_release == 1U &&
             first_gpio_stop.packing_buffers_to_release == 1U &&
             adc_ring.release(old_adc.handle) ==
                 adc_capture::OperationStatus::kOk &&
             gpio_ring.release(old_gpio.handle) ==
                 gpio_capture::OperationStatus::kOk,
         "STOP preserves and then releases each outstanding CPU lease");
  const adc_capture::AcquireResult remaining_adc = adc_ring.acquireReady();
  const gpio_capture::AcquireResult remaining_gpio = gpio_ring.acquireReady();
  expect(remaining_adc.ok() && remaining_gpio.ok() &&
             adc_ring.release(remaining_adc.handle) ==
                 adc_capture::OperationStatus::kOk &&
             gpio_ring.release(remaining_gpio.handle) ==
                 gpio_capture::OperationStatus::kOk &&
             adc_ring.quiescent() && gpio_ring.quiescent(),
         "complete first-run buffers drain without crossing the epoch");

  constexpr std::uint32_t kSecondRun = 101U;
  expect(adc_driver.prime(kSecondRun).ok() && gpio_driver.prime().ok(),
         "both rings can begin a fresh run only after quiescence");
  const adc_capture::CompletionResult stale_completion =
      adc_ring.onMajorLoopComplete(0U, kFirstRun, 0U,
                                   old_adc.handle.buffer_index);
  expect(stale_completion.status ==
                 adc_capture::OperationStatus::kInvalidEpoch &&
             adc_ring.snapshot().next_completion_generations ==
                 std::array<std::uint32_t, 2U>{0U, 0U},
         "an old ADC interrupt cannot advance the new paired generation");

  expect(adc_driver.complete(0U).consumed &&
             adc_driver.complete(1U).pair_ready &&
             gpio_driver.complete().ok(),
         "publish fresh second-run buffers after the stale interrupt");
  const adc_capture::AcquireResult new_adc = adc_ring.acquireReady();
  const gpio_capture::AcquireResult new_gpio = gpio_ring.acquireReady();
  expect(new_adc.ok() && new_gpio.ok() &&
             new_adc.handle.epoch == kSecondRun &&
             new_adc.handle.lease != old_adc.handle.lease &&
             new_gpio.handle.lease != old_gpio.handle.lease &&
             adc_ring.release(old_adc.handle) ==
                 adc_capture::OperationStatus::kInvalidHandle &&
             gpio_ring.release(old_gpio.handle) ==
                 gpio_capture::OperationStatus::kInvalidHandle &&
             adc_ring.release(new_adc.handle) ==
                 adc_capture::OperationStatus::kOk &&
             gpio_ring.release(new_gpio.handle) ==
                 gpio_capture::OperationStatus::kOk,
         "stale leases cannot release or alias newly reused storage");
  expect(adc_ring.stop(adc_driver.stopStates()).ok() &&
             gpio_ring.stop(0U).status ==
                 gpio_capture::OperationStatus::kOk &&
             adc_ring.quiescent() && gpio_ring.quiescent() &&
             adc_cache.allReleasedToDma() && gpio_cache.allReleasedToDma() &&
             !adc_cache.ownershipViolation() &&
             !gpio_cache.ownershipViolation(),
         "the second run returns both cache-owned rings to reusable IDLE");
}

}  // namespace

int main() {
  testConcurrentPressureWrapUsbAndCounterReconciliation();
  testBothRingsRejectStaleLeasesAcrossRunBoundaries();
  if (failures != 0) {
    std::cerr << failures << " combined DMA/pipeline assertion(s) failed\n";
    return 1;
  }
  std::cout << "combined DMA/pipeline tests passed\n";
  return 0;
}
