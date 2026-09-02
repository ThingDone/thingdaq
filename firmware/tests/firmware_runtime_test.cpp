#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#include "firmware_identity.h"
#include "firmware_runtime.h"

namespace {

namespace app = thingdaq::runtime;
namespace acquisition = thingdaq::acquisition;
namespace adc = thingdaq::adc;
namespace adc_capture = thingdaq::adc_capture;
namespace adc_packer = thingdaq::adc_packer;
namespace adc_trigger = thingdaq::adc_trigger;
namespace benchmark = thingdaq::benchmark;
namespace board = thingdaq::board;
namespace constants = thingdaq::protocol_v1;
namespace constants_v2 = thingdaq::protocol_v2;
namespace control = thingdaq::control;
namespace gpio_clock = thingdaq::gpio_clock;
namespace gpio_capture = thingdaq::gpio_capture;
namespace gpio_packer = thingdaq::gpio_packer;
namespace identity = thingdaq::identity;
namespace packet = thingdaq::packet;
namespace synthetic = thingdaq::synthetic;
namespace usb = thingdaq::usb;
namespace wire = thingdaq::protocol;

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
         "encode empty request");
  return frame;
}

wire::CommandFrame v2EmptyRequest(constants::FrameKind kind,
                                  std::uint32_t request_id) {
  wire::FrameFields fields{};
  fields.kind = kind;
  fields.version = constants_v2::kProtocolVersion;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {}, frame).ok(),
         "encode empty v2 request");
  return frame;
}

wire::CommandFrame v2RleConfigureRequest(std::uint32_t request_id) {
  std::array<std::uint8_t, constants_v2::kConfigureRequestPayloadSize>
      payload{};
  payload[constants_v2::kConfigureRequestStreamMaskOffset] = 3U;
  payload[constants_v2::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants_v2::Source::kSynthetic);
  payload[constants_v2::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(constants_v2::ChecksumAlgorithm::kAdler32);
  payload[constants_v2::kConfigureRequestEncodingOffset] =
      static_cast<std::uint8_t>(
          constants_v2::ConfigurationEncoding::kRleAuto);
  expect(wire::storeU32(
             {payload.data(), payload.size()},
             constants_v2::kConfigureRequestDataFrameBytesOffset,
             constants_v2::kDataFrameBytes),
         "encode v2 RLE configuration");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kConfigureRequest;
  fields.version = constants_v2::kProtocolVersion;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame).ok(),
         "encode v2 RLE_AUTO CONFIGURE request");
  return frame;
}

wire::CommandFrame configureRequest(
    std::uint32_t request_id,
    constants::ChecksumAlgorithm checksum_algorithm =
        constants::ChecksumAlgorithm::kAdler32) {
  std::array<std::uint8_t, constants::kConfigureRequestPayloadSize> payload{};
  payload[constants::kConfigureRequestStreamMaskOffset] =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  payload[constants::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants::Source::kSynthetic);
  payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(checksum_algorithm);
  expect(wire::storeU32(
             {payload.data(), payload.size()},
             constants::kConfigureRequestDataFrameBytesOffset,
             static_cast<std::uint32_t>(constants::kDataFrameBytes)),
         "encode dual-stream synthetic configuration");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kConfigureRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode CONFIGURE request");
  return frame;
}

wire::CommandFrame physicalAdcConfigureRequest(
    std::uint32_t request_id,
    constants::ChecksumAlgorithm checksum_algorithm =
        constants::ChecksumAlgorithm::kAdler32) {
  std::array<std::uint8_t, constants::kConfigureRequestPayloadSize> payload{};
  payload[constants::kConfigureRequestStreamMaskOffset] =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc);
  payload[constants::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants::Source::kHardware);
  payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(checksum_algorithm);
  expect(wire::storeU32(
             {payload.data(), payload.size()},
             constants::kConfigureRequestDataFrameBytesOffset,
             static_cast<std::uint32_t>(constants::kDataFrameBytes)),
         "encode physical ADC configuration");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kConfigureRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode physical ADC CONFIGURE request");
  return frame;
}

wire::CommandFrame pingRequest(std::uint32_t request_id,
                               std::uint64_t nonce) {
  std::array<std::uint8_t, constants::kPingRequestPayloadSize> payload{};
  expect(wire::storeU64({payload.data(), payload.size()},
                        constants::kPingRequestNonceOffset, nonce),
         "encode PING nonce");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kPingRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode PING request");
  return frame;
}

wire::CommandFrame checksumBenchmarkRequest(std::uint32_t request_id) {
  std::array<std::uint8_t,
             constants::kChecksumBenchmarkRequestPayloadSize>
      payload{};
  payload[constants::kChecksumBenchmarkRequestChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(constants::ChecksumAlgorithm::kAdler32);
  payload[constants::kChecksumBenchmarkRequestVectorOffset] =
      static_cast<std::uint8_t>(constants::BenchmarkVector::kBuffer64);
  payload[constants::kChecksumBenchmarkRequestMemoryRegionOffset] =
      static_cast<std::uint8_t>(
          constants::BenchmarkMemoryRegion::kDtcmPacket);
  payload[constants::kChecksumBenchmarkRequestCacheStateOffset] =
      static_cast<std::uint8_t>(
          constants::BenchmarkCacheState::kHotOrNative);
  expect(wire::storeU16(
             {payload.data(), payload.size()},
             constants::kChecksumBenchmarkRequestBatchCountOffset, 1U) &&
             wire::storeU16(
                 {payload.data(), payload.size()},
                 constants::kChecksumBenchmarkRequestIterationsPerBatchOffset,
                 1U),
         "encode benchmark repetition counts");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kChecksumBenchmarkRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode CHECKSUM_BENCHMARK request");
  return frame;
}

wire::CommandFrame gpioClockDiagnosticRequest(std::uint32_t request_id,
                                              std::uint32_t rate_hz,
                                              std::uint16_t event_count) {
  std::array<std::uint8_t,
             constants::kGpioClockDiagnosticRequestPayloadSize>
      payload{};
  expect(wire::storeU32(
             {payload.data(), payload.size()},
             constants::kGpioClockDiagnosticRequestRateHzOffset, rate_hz) &&
             wire::storeU16(
                 {payload.data(), payload.size()},
                 constants::kGpioClockDiagnosticRequestEventCountOffset,
                 event_count),
         "encode GPIO clock diagnostic window");
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kGpioClockDiagnosticRequest;
  fields.request_id = request_id;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "encode GPIO_CLOCK_DIAGNOSTIC request");
  return frame;
}

class FakeCdcStream final : public usb::CdcByteStream {
 public:
  usb::IoCount available() override {
    const std::size_t remaining = input_.size() - input_offset_;
    const std::size_t bounded =
        std::min(remaining,
                 static_cast<std::size_t>(
                     std::numeric_limits<usb::IoCount>::max()));
    return static_cast<usb::IoCount>(bounded);
  }

  usb::IoCount read(std::uint8_t *destination,
                    std::size_t capacity) override {
    const std::size_t remaining = input_.size() - input_offset_;
    const std::size_t count = std::min({remaining, capacity, max_read_size});
    std::copy_n(input_.data() + input_offset_, count, destination);
    input_offset_ += count;
    return static_cast<usb::IoCount>(count);
  }

  usb::IoCount availableForWrite() override {
    return static_cast<usb::IoCount>(available_write_size);
  }

  usb::IoCount write(const std::uint8_t *source, std::size_t size) override {
    const std::size_t count = std::min(size, max_write_size);
    output.insert(output.end(), source, source + count);
    return static_cast<usb::IoCount>(count);
  }

  void appendInput(const wire::CommandFrame &frame) {
    append(input_, bytes(frame));
  }

  bool inputEmpty() const { return input_offset_ == input_.size(); }

  std::size_t max_read_size = 13U;
  std::size_t available_write_size =
      static_cast<std::size_t>(std::numeric_limits<usb::IoCount>::max());
  std::size_t max_write_size = 11U;
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

class FakeBenchmarkPlatform final : public benchmark::Platform {
 public:
  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    frequency_hz = constants::kChecksumBenchmarkCycleCounterHz;
    pair_count_ = 0U;
    pair_open_ = false;
    return true;
  }

  std::uint32_t readCycles() override {
    if (!pair_open_) {
      pair_open_ = true;
      return cycles_;
    }
    cycles_ += pair_count_ <
                       constants::kChecksumBenchmarkTimerCalibrationSamples
                   ? 4U
                   : 104U;
    ++pair_count_;
    pair_open_ = false;
    return cycles_;
  }

  std::uint32_t enterCritical() override {
    ++critical_entries;
    return 0U;
  }
  void exitCritical(std::uint32_t) override { ++critical_exits; }
  void flushDelete(void *, std::size_t) override {}
  void invalidate(void *, std::size_t) override {}

  std::uint32_t critical_entries = 0U;
  std::uint32_t critical_exits = 0U;

 private:
  std::uint32_t cycles_ = 0U;
  std::uint32_t pair_count_ = 0U;
  bool pair_open_ = false;
};

class FakeGpioClockPlatform final : public gpio_clock::Platform {
 public:
  bool execute(const gpio_clock::Plan &plan,
               wire::GpioClockDiagnosticResponse &snapshot) override {
    ++calls;
    observed = plan;
    snapshot.dwt_counter_hz = constants::kGpioClockDwtHz;
    snapshot.dwt_elapsed_cycles = plan.measurement_cycles;
    snapshot.tcd_biter = plan.tcd_major_count;
    snapshot.tcd_citer_final = static_cast<std::uint16_t>(
        plan.tcd_major_count - plan.requested_event_count);
    snapshot.dma_sample_count = plan.requested_event_count;
    snapshot.pit_channel = board::kGpioPitChannel;
    snapshot.xbar_input = board::kGpioXbarInput;
    snapshot.xbar_output = board::kGpioXbarOutput;
    snapshot.edma_channel = board::kGpioEdmaChannel;
    snapshot.dmamux_source = board::kGpioDmamuxSource;
    snapshot.edma_priority = board::kGpioEdmaPriority;
    snapshot.tcd_nbytes = sizeof(std::uint32_t);
    return true;
  }

  std::uint32_t calls = 0U;
  gpio_clock::Plan observed{};
};

class ReadyAdcPlatform final : public adc::Platform {
 public:
  adc::PrepareStatus prepareConverter(
      const board::AdcConverterConfiguration &,
      const adc::Settings &) override {
    return adc::PrepareStatus::kOk;
  }
  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    frequency_hz = constants::kAdcCalibrationCycleCounterHz;
    return true;
  }
  std::uint32_t readCycles() override {
    const std::uint32_t value = cycles;
    cycles += 100U;
    return value;
  }
  bool startCalibration(
      const board::AdcConverterConfiguration &) override {
    return true;
  }
  bool calibrationActive(
      const board::AdcConverterConfiguration &) override {
    return false;
  }
  bool calibrationFailed(
      const board::AdcConverterConfiguration &) override {
    return false;
  }
  bool verifyConverter(const board::AdcConverterConfiguration &,
                       const adc::Settings &) override {
    return true;
  }
  void abortCalibration(
      const board::AdcConverterConfiguration &) override {}

 private:
  std::uint32_t cycles = 0U;
};

class LifecycleTriggerPlatform final : public adc_trigger::Platform {
 public:
  explicit LifecycleTriggerPlatform(std::vector<std::string> &operations)
      : operations_(operations) {}

  adc_trigger::ConfigureResult configureStopped() override {
    adc_trigger::ConfigureResult result{};
    result.configuration_flags = adc_trigger::kStoppedConfigurationFlags;
    return result;
  }
  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    frequency_hz = constants::kAdcTriggerDwtClockHz;
    return true;
  }
  std::uint32_t readCycles() override {
    const std::uint32_t value = cycles_;
    cycles_ += 100U;
    return value;
  }
  bool armFromStopped(bool completion_diagnostic) override {
    operations_.push_back(completion_diagnostic ? "diagnostic_arm"
                                                : "trigger_arm");
    return arm_ok;
  }
  std::array<std::uint32_t, 2U> completionCounts() override {
    return {1U, 1U};
  }
  std::array<std::uint32_t, 2U> firstCompletionCycles() override {
    return {100U, 400U};
  }
  std::uint32_t triggerErrorFlags() override { return 0U; }
  std::uint32_t triggerErrorCount() override { return 0U; }
  bool stop() override {
    operations_.push_back("trigger_stop");
    return stop_ok;
  }
  adc_trigger::HardwareEvidence evidence() override { return {}; }

  bool arm_ok = true;
  bool stop_ok = true;

 private:
  std::vector<std::string> &operations_;
  std::uint32_t cycles_ = 0U;
};

class LifecycleAdcCapture final : public adc_capture::HardwareCapture {
 public:
  using InspectHook = void (*)(void *context);

  explicit LifecycleAdcCapture(std::vector<std::string> &operations)
      : operations_(operations) {}

  adc_capture::StartStatus inspectStart(std::uint32_t epoch) override {
    ++inspect_calls;
    if (inspect_hook != nullptr) {
      InspectHook hook = inspect_hook;
      inspect_hook = nullptr;
      hook(inspect_hook_context);
    }
    if (inspect_status != adc_capture::StartStatus::kOk) {
      return inspect_status;
    }
    return epoch != 0U && snapshot_.quiescent
               ? adc_capture::StartStatus::kOk
               : adc_capture::StartStatus::kNotQuiescent;
  }

  adc_capture::StartStatus prepare(std::uint32_t epoch) override {
    if (inspectStart(epoch) != adc_capture::StartStatus::kOk) {
      return adc_capture::StartStatus::kNotQuiescent;
    }
    operations_.push_back("dma_prepare");
    if (prepare_status != adc_capture::StartStatus::kOk) {
      return prepare_status;
    }
    epoch_ = epoch;
    snapshot_.progress = {};
    snapshot_.epoch = epoch;
    snapshot_.running = true;
    snapshot_.quiescent = false;
    snapshot_.hardware_prepared = true;
    snapshot_.faulted = false;
    return adc_capture::StartStatus::kOk;
  }

  adc_capture::StopReport stopAfterTriggers() override {
    operations_.push_back("dma_stop");
    adc_capture::StopReport report{};
    if (!snapshot_.running) {
      return report;
    }
    snapshot_.running = false;
    snapshot_.hardware_prepared = false;
    snapshot_.quiescent = !ready_ && !leased_;
    report.status = adc_capture::OperationStatus::kOk;
    report.ready_buffers_to_drain = ready_ ? 1U : 0U;
    return report;
  }

  bool stopAtBoundaryBeforeTriggers() override {
    operations_.push_back("dma_boundary_stop");
    return !snapshot_.faulted;
  }

  std::size_t serviceOwnership() override { return 0U; }

  adc_capture::AcquireResult acquireReady() override {
    if (!ready_ || leased_) {
      return {};
    }
    leased_ = true;
    snapshot_.ready_depth = 0U;
    snapshot_.reading_depth = 1U;
    ++snapshot_.progress.buffers_acquired;
    snapshot_.progress.pairs_delivered += constants::kAdcPairsPerFrame;
    adc_capture::BufferHandle handle{};
    handle.pairs = buffer_.pairs.data();
    handle.first_pair = first_pair_;
    handle.pair_count = constants::kAdcPairsPerFrame;
    handle.epoch = epoch_;
    handle.lease = lease_;
    handle.buffer_index = 0U;
    return {adc_capture::OperationStatus::kOk, handle};
  }

  adc_capture::OperationStatus release(
      const adc_capture::BufferHandle &handle) override {
    if (!leased_ || handle.pairs != buffer_.pairs.data() ||
        handle.epoch != epoch_ || handle.lease != lease_) {
      return adc_capture::OperationStatus::kInvalidHandle;
    }
    leased_ = false;
    ready_ = false;
    snapshot_.reading_depth = 0U;
    ++snapshot_.progress.buffers_released;
    snapshot_.quiescent = !snapshot_.running;
    return adc_capture::OperationStatus::kOk;
  }

  adc_capture::Snapshot rawSnapshot() override { return snapshot_; }

  void publish(std::uint64_t first_pair) {
    first_pair_ = first_pair;
    ++lease_;
    if (lease_ == 0U) {
      ++lease_;
    }
    for (std::size_t pair = 0U; pair < buffer_.pairs.size(); ++pair) {
      buffer_.pairs[pair].adc0 =
          static_cast<std::uint16_t>(pair & 0x0FFFU);
      buffer_.pairs[pair].adc1 =
          static_cast<std::uint16_t>((pair + 1U) & 0x0FFFU);
    }
    ready_ = true;
    snapshot_.quiescent = false;
    snapshot_.ready_depth = 1U;
    snapshot_.progress.ready_high_water = 1U;
    ++snapshot_.progress.channel_major_loops[0];
    ++snapshot_.progress.channel_major_loops[1];
    snapshot_.progress.channel_results[0] += constants::kAdcPairsPerFrame;
    snapshot_.progress.channel_results[1] += constants::kAdcPairsPerFrame;
    ++snapshot_.progress.paired_major_loops;
    ++snapshot_.progress.buffers_completed;
    snapshot_.progress.pairs_captured += constants::kAdcPairsPerFrame;
  }

  void fault() { snapshot_.faulted = true; }

  adc_capture::StartStatus inspect_status =
      adc_capture::StartStatus::kOk;
  adc_capture::StartStatus prepare_status =
      adc_capture::StartStatus::kOk;
  InspectHook inspect_hook = nullptr;
  void *inspect_hook_context = nullptr;
  std::uint32_t inspect_calls = 0U;

 private:
  std::vector<std::string> &operations_;
  adc_capture::PairBuffer buffer_{};
  adc_capture::Snapshot snapshot_{};
  std::uint64_t first_pair_ = 0U;
  std::uint32_t epoch_ = 0U;
  std::uint32_t lease_ = 0U;
  bool ready_ = false;
  bool leased_ = false;
};

class LifecycleGpioCapture final : public gpio_capture::HardwareCapture {
 public:
  using InspectHook = void (*)(void *context);

  explicit LifecycleGpioCapture(std::vector<std::string> &operations)
      : operations_(operations) {}

  gpio_capture::StartStatus inspectStart() override {
    ++inspect_calls;
    if (inspect_hook != nullptr) {
      InspectHook hook = inspect_hook;
      inspect_hook = nullptr;
      hook(inspect_hook_context);
    }
    if (inspect_status != gpio_capture::StartStatus::kOk) {
      return inspect_status;
    }
    return snapshot_.quiescent ? gpio_capture::StartStatus::kOk
                               : gpio_capture::StartStatus::kNotQuiescent;
  }

  gpio_capture::StartStatus prepare() override {
    operations_.push_back("gpio_dma_prepare");
    if (prepare_status != gpio_capture::StartStatus::kOk) {
      return prepare_status;
    }
    if (!snapshot_.quiescent) {
      return gpio_capture::StartStatus::kNotQuiescent;
    }
    snapshot_.progress = {};
    snapshot_.running = true;
    snapshot_.quiescent = false;
    snapshot_.hardware_prepared = true;
    snapshot_.faulted = false;
    return gpio_capture::StartStatus::kOk;
  }

  gpio_capture::StartStatus start() override {
    const gpio_capture::StartStatus prepared = prepare();
    if (prepared == gpio_capture::StartStatus::kOk) {
      operations_.push_back("gpio_trigger_start");
    }
    return prepared;
  }

  gpio_capture::StopReport stopAfterTriggers() override {
    operations_.push_back("gpio_dma_stop");
    return finishStop();
  }

  gpio_capture::StopReport stop() override {
    operations_.push_back("gpio_boundary_stop");
    return finishStop();
  }

  gpio_capture::AcquireResult acquireReady() override {
    if (!ready_ || leased_) {
      return {};
    }
    leased_ = true;
    snapshot_.ready_depth = 0U;
    snapshot_.packing_depth = 1U;
    ++snapshot_.progress.buffers_acquired;
    snapshot_.progress.samples_delivered += constants::kGpioSamplesPerFrame;
    gpio_capture::BufferHandle handle{};
    handle.words = buffer_.words.data();
    handle.first_sample = first_sample_;
    handle.sample_count = constants::kGpioSamplesPerFrame;
    handle.lease = lease_;
    handle.buffer_index = 0U;
    return {gpio_capture::OperationStatus::kOk, handle};
  }

  gpio_capture::OperationStatus release(
      const gpio_capture::BufferHandle &handle) override {
    if (!leased_ || handle.words != buffer_.words.data() ||
        handle.lease != lease_) {
      return gpio_capture::OperationStatus::kInvalidHandle;
    }
    leased_ = false;
    ready_ = false;
    snapshot_.packing_depth = 0U;
    ++snapshot_.progress.buffers_released;
    snapshot_.quiescent = !snapshot_.running;
    return gpio_capture::OperationStatus::kOk;
  }

  gpio_capture::Snapshot rawSnapshot() override { return snapshot_; }

  void publish(std::uint64_t first_sample) {
    first_sample_ = first_sample;
    ++lease_;
    if (lease_ == 0U) {
      ++lease_;
    }
    for (std::size_t sample = 0U; sample < buffer_.words.size(); ++sample) {
      const std::uint8_t logical = static_cast<std::uint8_t>(sample);
      std::uint32_t raw = 0U;
      for (std::size_t bit = 0U;
           bit < board::countOf(board::kGpioMappingsByPackedBit); ++bit) {
        if ((logical & static_cast<std::uint8_t>(1U << bit)) != 0U) {
          raw |= std::uint32_t{1U}
                 << board::kGpioMappingsByPackedBit[bit].gpio2_bit;
        }
      }
      buffer_.words[sample] = raw;
    }
    ready_ = true;
    snapshot_.quiescent = false;
    snapshot_.ready_depth = 1U;
    snapshot_.progress.ready_high_water = 1U;
    ++snapshot_.progress.major_loops_completed;
    ++snapshot_.progress.buffers_completed;
    snapshot_.progress.samples_captured += constants::kGpioSamplesPerFrame;
  }

  void fault() { snapshot_.faulted = true; }

  gpio_capture::StartStatus prepare_status =
      gpio_capture::StartStatus::kOk;
  gpio_capture::StartStatus inspect_status =
      gpio_capture::StartStatus::kOk;
  InspectHook inspect_hook = nullptr;
  void *inspect_hook_context = nullptr;
  std::uint32_t inspect_calls = 0U;

 private:
  gpio_capture::StopReport finishStop() {
    gpio_capture::StopReport report{};
    if (!snapshot_.running && !snapshot_.hardware_prepared) {
      return report;
    }
    snapshot_.running = false;
    snapshot_.hardware_prepared = false;
    snapshot_.quiescent = !ready_ && !leased_;
    report.status = gpio_capture::OperationStatus::kOk;
    report.ready_buffers_to_drain = ready_ ? 1U : 0U;
    report.packing_buffers_to_release = leased_ ? 1U : 0U;
    return report;
  }

  std::vector<std::string> &operations_;
  gpio_capture::RawBuffer buffer_{};
  gpio_capture::Snapshot snapshot_{};
  std::uint64_t first_sample_ = 0U;
  std::uint32_t lease_ = 0U;
  bool ready_ = false;
  bool leased_ = false;
};

class AuditGpioCapture final : public thingdaq::gpio_capture::HardwareCapture {
 public:
  thingdaq::gpio_capture::StartStatus inspectStart() override {
    ++inspect_calls;
    return inspect_status;
  }
  thingdaq::gpio_capture::StartStatus prepare() override {
    return inspect_status;
  }
  thingdaq::gpio_capture::StartStatus start() override {
    return inspect_status;
  }
  thingdaq::gpio_capture::StopReport stopAfterTriggers() override {
    return {};
  }
  thingdaq::gpio_capture::StopReport stop() override { return {}; }
  thingdaq::gpio_capture::AcquireResult acquireReady() override {
    return {};
  }
  thingdaq::gpio_capture::OperationStatus release(
      const thingdaq::gpio_capture::BufferHandle &) override {
    return thingdaq::gpio_capture::OperationStatus::kInvalidHandle;
  }
  thingdaq::gpio_capture::Snapshot rawSnapshot() override {
    return snapshot;
  }

  thingdaq::gpio_capture::StartStatus inspect_status =
      thingdaq::gpio_capture::StartStatus::kOk;
  thingdaq::gpio_capture::Snapshot snapshot{};
  std::uint32_t inspect_calls = 0U;
};

struct CombinedControllerFixture {
  packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline packet_pipeline{packet_storage};
  thingdaq::stats::Statistics statistics{};
  std::vector<std::string> operations{};
  ReadyAdcPlatform adc_platform{};
  adc::Initializer adc_initializer{adc_platform};
  LifecycleTriggerPlatform trigger_platform{operations};
  adc_trigger::Scheduler trigger_scheduler{trigger_platform};
  LifecycleAdcCapture adc_capture{operations};
  adc_packer::AdcFramePacker adc_frame_packer{adc_capture};
  LifecycleGpioCapture gpio_capture{operations};
  gpio_packer::PackedBufferStorage gpio_storage{};
  gpio_packer::GpioBatchPacker gpio_frame_packer{gpio_capture,
                                                 gpio_storage};
  acquisition::Controller controller{
      statistics,       packet_pipeline,   &gpio_capture,
      &gpio_frame_packer, &adc_initializer, &trigger_scheduler,
      &adc_capture,     &adc_frame_packer};
};

wire::Configuration combinedPhysicalConfiguration() {
  wire::Configuration configuration = control::kPhysicalAdcConfiguration;
  configuration.stream_mask =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  return configuration;
}

struct AdcPackerHookContext {
  adc_packer::AdcFramePacker *packer = nullptr;
  packet::PacketBufferPipeline *pipeline = nullptr;
  adc_packer::OperationStatus status =
      adc_packer::OperationStatus::kNotRunning;
  std::uint32_t run_id = 0U;
};

void startAdcPackerDuringInspection(void *opaque) {
  auto &context = *static_cast<AdcPackerHookContext *>(opaque);
  context.status = context.packer->startRun(
      context.run_id, constants::kDefaultChecksumAlgorithm,
      *context.pipeline, 111U);
}

struct GpioPackerHookContext {
  gpio_packer::GpioBatchPacker *packer = nullptr;
  packet::PacketBufferPipeline *pipeline = nullptr;
  gpio_packer::OperationStatus status =
      gpio_packer::OperationStatus::kNotRunning;
  std::uint32_t run_id = 0U;
};

void startGpioPackerDuringInspection(void *opaque) {
  auto &context = *static_cast<GpioPackerHookContext *>(opaque);
  context.status = context.packer->startRun(
      context.run_id, constants::kDefaultChecksumAlgorithm,
      *context.pipeline, 111U);
}

struct DrainResult {
  bool quiescent = false;
  bool saw_start = false;
  bool saw_stop = false;
  bool packet_started = false;
  bool packet_stopped = false;
  std::size_t stop_ready_frames = 0U;
  std::size_t stop_transmitting_frames = 0U;
};

DrainResult drain(app::FirmwareRuntime &firmware, FakeCdcStream &stream) {
  DrainResult result{};
  for (std::size_t iteration = 0U; iteration < 512U; ++iteration) {
    const usb::TransportSnapshot before = firmware.transportSnapshot();
    const app::LoopReport report = firmware.service();
    const usb::TransportSnapshot after = firmware.transportSnapshot();

    expect(report.receive.bytes_processed <= board::kUsbRxBudgetBytesPerLoop &&
               report.receive.io_calls <= board::kUsbRxCallsPerLoop &&
               report.transmit_before_second_acquisition.bytes_written <=
                   board::kUsbTxBudgetBytesPerVisit &&
               report.transmit_before_second_acquisition.io_calls <=
                   board::kUsbTxCallsPerVisit &&
               report.transmit.bytes_written <=
                   board::kUsbTxBudgetBytesPerVisit &&
               report.transmit.io_calls <= board::kUsbTxCallsPerVisit &&
               report.transmit_before_second_acquisition.bytes_written +
                       report.transmit.bytes_written <=
                   board::kUsbTxBudgetBytesPerLoop &&
               report.transmit_before_second_acquisition.io_calls +
                       report.transmit.io_calls <=
                   board::kUsbTxCallsPerLoop,
           "each cooperative loop respects every USB work budget");
    expect(after.commands_dequeued - before.commands_dequeued <= 1U,
           "each cooperative loop dispatches at most one command");
    expect(!report.internal_error && !report.recovered_to_idle &&
               !report.response_reservation_abandoned,
           "valid requests do not enter internal recovery");
    result.saw_start =
        result.saw_start || report.events.has(control::Event::kStartEpoch);
    result.saw_stop =
        result.saw_stop || report.events.has(control::Event::kStop);
    result.packet_started =
        result.packet_started || report.packet_run_started;
    result.packet_stopped =
        result.packet_stopped || report.packet_production_stopped;
    result.stop_ready_frames =
        std::max(result.stop_ready_frames,
                 report.packet_stop.ready_frames_to_drain);
    result.stop_transmitting_frames =
        std::max(result.stop_transmitting_frames,
                 report.packet_stop.transmitting_frames_to_drain);

    if (stream.inputEmpty() && after.pending_rx_bytes == 0U &&
        after.command_queue_depth == 0U &&
        after.response_queue_depth == 0U &&
        !after.command_awaiting_response &&
        !firmware.hasPendingTransmission()) {
      result.quiescent = true;
      break;
    }
  }
  return result;
}

std::vector<wire::DecodedFrame> decodeOutput(
    const std::vector<std::uint8_t> &output) {
  std::vector<wire::DecodedFrame> frames{};
  std::size_t offset = 0U;
  while (offset < output.size()) {
    const wire::ByteView remaining{output.data() + offset,
                                   output.size() - offset};
    std::uint32_t total_length = 0U;
    if (!wire::loadU32(remaining, constants::kHeaderTotalLengthOffset,
                       total_length) ||
        total_length > remaining.size ||
        total_length < constants::kMinFrameBytes) {
      expect(false, "response stream contains a complete bounded frame");
      break;
    }
    wire::DecodedFrame decoded{};
    expect(wire::decodeFrame(
               {remaining.data, static_cast<std::size_t>(total_length)},
               decoded)
               .ok(),
           "response frame decodes and validates");
    frames.push_back(decoded);
    offset += static_cast<std::size_t>(total_length);
  }
  expect(offset == output.size(), "response stream has no trailing bytes");
  return frames;
}

constants::ErrorCode responseError(const wire::DecodedFrame &frame) {
  std::uint16_t raw = static_cast<std::uint16_t>(
      constants::ErrorCode::kInternalError);
  expect(wire::loadU16(frame.payload,
                       constants::kResponsePrefixErrorCodeOffset, raw),
         "typed response exposes its error code");
  return static_cast<constants::ErrorCode>(raw);
}

std::string buildId(const wire::DecodedFrame &info) {
  const std::uint8_t *field =
      info.payload.data + constants::kInfoResponseBuildIdOffset;
  std::size_t length = 0U;
  while (length < constants::kInfoResponseBuildIdCount &&
         field[length] != 0U) {
    ++length;
  }
  return {reinterpret_cast<const char *>(field), length};
}

void testCompleteControlPlane() {
  FakeCdcStream stream{};
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  constexpr std::uint32_t hardware_serial = 167772150U;
  constexpr std::uint64_t nonce = 0x0123456789ABCDEFULL;

  expect(firmware.state() == constants::DeviceState::kBoot,
         "runtime begins in BOOT before setup");
  expect(firmware.begin(hardware_serial) &&
             firmware.state() == constants::DeviceState::kIdle &&
             firmware.hardwareSerial() == hardware_serial,
         "setup atomically binds the core serial and enters IDLE");
  expect(!firmware.begin(99U) &&
             firmware.hardwareSerial() == hardware_serial,
         "repeated initialization cannot replace hardware identity");

  stream.appendInput(emptyRequest(constants::FrameKind::kInfoRequest, 1U));
  stream.appendInput(configureRequest(2U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 3U));
  const DrainResult started = drain(firmware, stream);
  expect(started.quiescent && started.saw_start && !started.saw_stop &&
             started.packet_started && !started.packet_stopped &&
             firmware.state() == constants::DeviceState::kRunning &&
             firmware.runId() == 1U &&
             firmware.packetSnapshot().run_id == 1U &&
             firmware.packetSnapshot().accepting_frames &&
             firmware.syntheticSnapshot().running &&
             firmware.syntheticSnapshot().mode == synthetic::Mode::kRealtime,
         "INFO-CONFIGURE-START arms the paced synthetic run cooperatively");

  wire::CommandFrame corrupt = pingRequest(90U, 90U);
  corrupt.mutableData()[corrupt.size() - 1U] ^= 0x80U;
  stream.appendInput(corrupt);
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 4U));
  stream.appendInput(pingRequest(5U, nonce));
  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 6U));
  const DrainResult stopped = drain(firmware, stream);
  expect(stopped.quiescent && !stopped.saw_start && stopped.saw_stop &&
             !stopped.packet_started && stopped.packet_stopped &&
             firmware.state() == constants::DeviceState::kIdle &&
             firmware.runId() == 1U &&
             !firmware.packetSnapshot().accepting_frames &&
             !firmware.syntheticSnapshot().running,
         "STATUS-PING-STOP stops synthetic production in clean IDLE");

  stream.appendInput(
      emptyRequest(constants::FrameKind::kResetStatsRequest, 7U));
  stream.appendInput(emptyRequest(constants::FrameKind::kInfoRequest, 8U));
  expect(drain(firmware, stream).quiescent,
         "RESET and INFO run after every prior response is complete");

  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 9U,
         "every valid or identifiable malformed request receives one response");
  if (frames.size() != 9U) {
    return;
  }

  const std::array<constants::FrameKind, 9U> expected_kinds{
      constants::FrameKind::kInfoResponse,
      constants::FrameKind::kConfigureResponse,
      constants::FrameKind::kStartResponse,
      constants::FrameKind::kErrorResponse,
      constants::FrameKind::kGetStatusResponse,
      constants::FrameKind::kPingResponse,
      constants::FrameKind::kStopResponse,
      constants::FrameKind::kResetStatsResponse,
      constants::FrameKind::kInfoResponse,
  };
  const std::array<std::uint32_t, 9U> expected_request_ids{
      1U, 2U, 3U, 90U, 4U, 5U, 6U, 7U, 8U,
  };
  for (std::size_t index = 0U; index < frames.size(); ++index) {
    expect(frames[index].header.kind == expected_kinds[index] &&
               frames[index].header.request_id == expected_request_ids[index],
           "response order, type, and echoed request ID are deterministic");
  }

  const wire::DecodedFrame &info = frames[0];
  std::uint32_t value32 = 0U;
  std::uint16_t value16 = 0U;
  expect(info.payload.data[constants::kInfoResponseProtocolVersionOffset] ==
                 identity::kProtocolVersion &&
             info.payload
                     .data[constants::kInfoResponseFirmwareVersionMajorOffset] ==
                 identity::kFirmwareVersion.major &&
             info.payload
                     .data[constants::kInfoResponseFirmwareVersionMinorOffset] ==
                 identity::kFirmwareVersion.minor &&
             info.payload
                     .data[constants::kInfoResponseFirmwareVersionPatchOffset] ==
                 identity::kFirmwareVersion.patch,
         "INFO exposes protocol and semantic firmware compatibility");
  expect(wire::loadU32(info.payload,
                       constants::kInfoResponseHardwareSerialOffset, value32) &&
             value32 == hardware_serial,
         "INFO exposes the USB chip-derived hardware identity");
  expect(wire::loadU16(info.payload, constants::kInfoResponseBoardIdOffset,
                       value16) &&
             value16 == static_cast<std::uint16_t>(identity::kBoardId) &&
             wire::loadU16(info.payload, constants::kInfoResponseMcuIdOffset,
                           value16) &&
             value16 == static_cast<std::uint16_t>(identity::kMcuId),
         "INFO exposes exact board and MCU identities");
  expect(buildId(info) == std::string(identity::kBuildId.data()),
         "INFO exposes the source-derived stale-image build key");
  expect(info.payload
                 .data[constants::kInfoResponseSupportedStreamMaskOffset] ==
             3U &&
             wire::loadU32(info.payload,
                           constants::kInfoResponseCapabilityBitsOffset,
                           value32) &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kAdcStream)) != 0U &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kGpioStream)) != 0U &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kSyntheticSource)) != 0U &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kHardwareSource)) != 0U &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kGpioCaptureDiagnostic)) !=
                 0U &&
             info.payload.data[constants::kInfoResponseSupportedSourceMaskOffset] ==
                 3U,
         "INFO advertises physical GPIO, diagnostics, and synthetic mode");

  const wire::DecodedFrame &rejection = frames[3];
  expect(responseError(rejection) ==
                 constants::ErrorCode::kChecksumMismatch &&
             rejection.payload
                     .data[constants::kErrorResponseRejectedKindOffset] ==
                 static_cast<std::uint8_t>(
                     constants::FrameKind::kPingRequest) &&
             rejection.payload
                     .data[constants::kErrorResponseRejectedVersionOffset] ==
                 identity::kProtocolVersion,
         "bad-checksum requests are rejected explicitly without dispatch");

  const wire::DecodedFrame &status = frames[4];
  expect(status.header.run_id == 1U &&
             status.payload.data[constants::kStatusResponseDeviceStateOffset] ==
                 static_cast<std::uint8_t>(constants::DeviceState::kRunning) &&
             status.payload.data[constants::kStatusResponseStreamMaskOffset] ==
                 3U &&
             status.payload.data[constants::kStatusResponseSourceOffset] ==
                 static_cast<std::uint8_t>(constants::Source::kSynthetic) &&
             wire::loadU32(status.payload,
                           constants::kStatusResponseParserErrorsOffset,
                           value32) &&
             value32 == 1U,
         "RUNNING STATUS projects the synthetic profile and parser recovery");
  std::uint64_t echoed_nonce = 0U;
  expect(wire::loadU64(frames[5].payload,
                       constants::kPingResponseNonceOffset, echoed_nonce) &&
             echoed_nonce == nonce,
         "PING survives the complete receive-dispatch-transmit path");
  expect(frames[8].header.run_id == 1U &&
             frames[8]
                     .payload.data[constants::kInfoResponseDeviceStateOffset] ==
                 static_cast<std::uint8_t>(constants::DeviceState::kIdle),
         "final INFO proves retained run provenance and clean IDLE");

  const thingdaq::stats::Snapshot statistics = firmware.statistics().snapshot();
  const usb::TransportSnapshot transport = firmware.transportSnapshot();
  expect(statistics.generation == 3U &&
             statistics.commands_accepted == 2U &&
             statistics.parser_errors == 0U &&
             statistics.transport_errors == 0U,
         "RESET_STATS clears shared runtime diagnostics then counts itself");
  expect(transport.parser.bad_checksums == 1U &&
             transport.commands_dequeued == 9U &&
             transport.rejected_commands_queued == 1U &&
             transport.responses_completed == 9U &&
             transport.response_reservations_abandoned == 0U,
         "transport lifetime diagnostics account for parser recovery and I/O");
}

void testV2RleRuntimeTelemetryAndConservation() {
  FakeCdcStream stream{};
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(0xAABBCCDDU), "v2 runtime completes BOOT");
  stream.appendInput(v2EmptyRequest(constants::FrameKind::kInfoRequest, 401U));
  stream.appendInput(v2RleConfigureRequest(402U));
  stream.appendInput(v2EmptyRequest(constants::FrameKind::kStartRequest, 403U));
  const DrainResult started = drain(firmware, stream);
  const packet::PipelineSnapshot negotiated = firmware.packetSnapshot();
  expect(started.saw_start && started.packet_started &&
             firmware.state() == constants::DeviceState::kRunning &&
             negotiated.frame_format.protocol_version ==
                 constants_v2::kProtocolVersion &&
             negotiated.frame_format.encoding ==
                 constants_v2::ConfigurationEncoding::kRleAuto,
         "runtime maps the accepted v2 encoding into one immutable packet run");

  clock.ticks = 2U * constants_v2::kFrameCoverageTicks;
  for (std::size_t iteration = 0U; iteration < 32U; ++iteration) {
    const app::LoopReport report = firmware.service();
    expect(!report.internal_error,
           "v2 synthetic production remains cooperative and error-free");
  }
  stream.appendInput(
      v2EmptyRequest(constants::FrameKind::kGetStatusRequest, 404U));
  stream.appendInput(v2EmptyRequest(constants::FrameKind::kStopRequest, 405U));
  expect(drain(firmware, stream).quiescent &&
             firmware.state() == constants::DeviceState::kIdle,
         "v2 STATUS and STOP drain without starving control");

  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  const wire::DecodedFrame *info = nullptr;
  const wire::DecodedFrame *configure = nullptr;
  const wire::DecodedFrame *start = nullptr;
  const wire::DecodedFrame *status = nullptr;
  const wire::DecodedFrame *stop = nullptr;
  std::size_t data_frames = 0U;
  for (const wire::DecodedFrame &frame : frames) {
    if (frame.header.kind == constants::FrameKind::kAdcData ||
        frame.header.kind == constants::FrameKind::kGpioData) {
      ++data_frames;
      expect(frame.header.version == constants_v2::kProtocolVersion &&
                 (frame.header.encoding == constants_v2::FrameEncoding::kRaw ||
                  frame.header.encoding == constants_v2::FrameEncoding::kRle),
             "one negotiated run emits only legal mixed RAW/RLE selectors");
    } else if (frame.header.request_id == 401U) {
      info = &frame;
    } else if (frame.header.request_id == 402U) {
      configure = &frame;
    } else if (frame.header.request_id == 403U) {
      start = &frame;
    } else if (frame.header.request_id == 404U) {
      status = &frame;
    } else if (frame.header.request_id == 405U) {
      stop = &frame;
    }
  }
  expect(info != nullptr && configure != nullptr && start != nullptr &&
             status != nullptr && stop != nullptr && data_frames != 0U,
         "v2 lifecycle returns every typed response and at least one data frame");
  if (info == nullptr || configure == nullptr || start == nullptr ||
      status == nullptr || stop == nullptr) {
    return;
  }
  std::uint32_t max_control = 0U;
  std::uint32_t capability_bits = 0U;
  expect(info->header.version == constants_v2::kProtocolVersion &&
             wire::loadU32(
                 info->payload,
                 constants_v2::kInfoResponseMaxControlFrameBytesOffset,
                 max_control) &&
             max_control == constants_v2::kMaxControlFrameBytes &&
             wire::loadU32(info->payload,
                           constants_v2::kInfoResponseCapabilityBitsOffset,
                           capability_bits) &&
             (capability_bits & static_cast<std::uint32_t>(
                                    constants_v2::Capability::kRleStreaming)) !=
                 0U &&
             configure->payload.data[
                 constants_v2::kConfigureResponseEncodingOffset] == 1U &&
             start->payload.data[
                 constants_v2::kConfigureResponseEncodingOffset] == 1U,
         "v2 INFO advertises the bound/capability and CONFIGURE/START echo RLE_AUTO");

  std::uint64_t logical_framed = 0U;
  std::uint64_t encoded_framed = 0U;
  std::uint64_t encoded_transmitted = 0U;
  std::uint64_t encoded_dropped = 0U;
  std::uint64_t encoded_queued = 0U;
  std::uint64_t wire_framed = 0U;
  std::uint64_t wire_transmitted = 0U;
  std::uint64_t wire_dropped = 0U;
  std::uint64_t wire_queued = 0U;
  std::uint64_t framed_frames = 0U;
  std::uint64_t raw_frames = 0U;
  std::uint64_t rle_frames = 0U;
  expect(status->header.version == constants_v2::kProtocolVersion &&
             status->payload.size == constants_v2::kStatusResponsePayloadSize &&
             status->payload.data[
                 constants_v2::kStatusResponseConfigurationEncodingOffset] ==
                 1U &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioPayloadBytesFramedOffset,
                 logical_framed) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioEncodedPayloadBytesFramedOffset,
                 encoded_framed) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioEncodedPayloadBytesTransmittedOffset,
                 encoded_transmitted) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioEncodedPayloadBytesDroppedOffset,
                 encoded_dropped) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioEncodedPayloadBytesQueuedOffset,
                 encoded_queued) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioFramedBytesFramedOffset,
                 wire_framed) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioFramedBytesTransmittedOffset,
                 wire_transmitted) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioEncodedWireBytesDroppedOffset,
                 wire_dropped) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioEncodedWireBytesQueuedOffset,
                 wire_queued) &&
             wire::loadU64(
                 status->payload,
                 constants_v2::kStatusResponseGpioFramesFramedPipelineOffset,
                 framed_frames) &&
             wire::loadU64(status->payload,
                           constants_v2::kStatusResponseGpioRawFramesOffset,
                           raw_frames) &&
             wire::loadU64(status->payload,
                           constants_v2::kStatusResponseGpioRleFramesOffset,
                           rle_frames),
         "v2 STATUS exposes every GPIO conservation term");
  expect(framed_frames != 0U && raw_frames + rle_frames == framed_frames &&
             encoded_framed <= logical_framed &&
             encoded_framed ==
                 encoded_transmitted + encoded_dropped + encoded_queued &&
             wire_framed == encoded_framed + 48U * framed_frames &&
             wire_framed == wire_transmitted + wire_dropped + wire_queued,
         "logical production, selection, queue ownership, transmission, and drops reconcile");
  const usb::TransportSnapshot transport = firmware.transportSnapshot();
  expect(transport.tx_bytes == transport.response_bytes_written +
                                   transport.lower_priority_bytes_written &&
             transport.lower_priority_bytes_written ==
                 transport.lower_priority_frame_bytes_completed +
                     transport.lower_priority_bytes_aborted +
                     transport.active_frame_bytes_sent,
         "runtime USB response/data byte ownership conserves exactly");
}

void testResetStatsWaitsForOlderControlResponses() {
  FakeCdcStream stream{};
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(167772151U),
         "RESET ordering runtime completes BOOT");

  stream.max_write_size = 1U;
  stream.appendInput(pingRequest(1U, 0x1122334455667788ULL));
  stream.appendInput(
      emptyRequest(constants::FrameKind::kResetStatsRequest, 2U));
  (void)firmware.service();
  (void)firmware.service();
  expect(firmware.transportSnapshot().response_queue_depth == 2U &&
             firmware.statistics().generation() == 1U,
         "RESET returns BUSY while an older response remains in flight");

  stream.max_write_size = 2048U;
  expect(drain(firmware, stream).quiescent,
         "older response and BUSY RESET response drain in order");
  std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 2U &&
             frames[0].header.kind == constants::FrameKind::kPingResponse &&
             frames[1].header.kind ==
                 constants::FrameKind::kResetStatsResponse &&
             responseError(frames[1]) == constants::ErrorCode::kBusy &&
             firmware.statistics().generation() == 1U,
         "rejected RESET preserves generation behind an older response");

  stream.appendInput(
      emptyRequest(constants::FrameKind::kResetStatsRequest, 3U));
  expect(drain(firmware, stream).quiescent,
         "quiescent RESET response drains");
  frames = decodeOutput(stream.output);
  expect(frames.size() == 3U &&
             frames[2].header.kind ==
                 constants::FrameKind::kResetStatsResponse &&
             responseError(frames[2]) == constants::ErrorCode::kOk &&
             firmware.statistics().generation() == 2U,
         "quiescent RESET starts one unambiguous response-counter epoch");
}

void testSyntheticDataCountersReachStatus() {
  FakeCdcStream stream{};
  stream.max_write_size = constants::kDataFrameBytes;
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(1234U), "counter test completes BOOT");

  stream.appendInput(configureRequest(101U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 102U));
  expect(drain(firmware, stream).quiescent,
         "counter test reaches a paced RUNNING epoch");
  stream.output.clear();

  clock.ticks = synthetic::kFrameCoverageTicks;
  expect(drain(firmware, stream).quiescent,
         "one elapsed interval transmits both complete data frames");
  const packet::PipelineSnapshot packet_counters = firmware.packetSnapshot();
  expect(packet_counters.sources[0].frames_transmitted == 1U &&
             packet_counters.sources[1].frames_transmitted == 1U,
         "packet ownership records both transmitted source frames");

  stream.output.clear();
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 103U));
  expect(drain(firmware, stream).quiescent,
         "STATUS is serviced while the paced source waits for its deadline");
  const thingdaq::stats::Snapshot native_counters =
      firmware.statistics().snapshot();
  expect(native_counters.data_path.adc.items_generated ==
                 constants::kAdcPairsPerFrame &&
             native_counters.data_path.adc.items_framed ==
                 constants::kAdcPairsPerFrame &&
             native_counters.data_path.adc.items_emitted ==
                 constants::kAdcPairsPerFrame &&
             native_counters.data_path.adc.items_transmitted ==
                 constants::kAdcPairsPerFrame &&
             native_counters.data_path.gpio.items_generated ==
                 constants::kGpioSamplesPerFrame &&
             native_counters.data_path.gpio.items_emitted ==
                 constants::kGpioSamplesPerFrame &&
             native_counters.data_path.gpio.items_transmitted ==
                 constants::kGpioSamplesPerFrame,
         "on-demand STATUS publication retains every data ownership stage");
  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 1U &&
             frames[0].header.kind ==
                 constants::FrameKind::kGetStatusResponse,
         "counter query emits one typed STATUS response");
  if (frames.size() == 1U) {
    std::uint64_t adc_emitted = 0U;
    std::uint64_t gpio_emitted = 0U;
    std::uint64_t adc_dropped = 1U;
    std::uint64_t gpio_dropped = 1U;
    std::uint64_t adc_generated = 0U;
    std::uint64_t gpio_generated = 0U;
    std::uint64_t adc_payload_transmitted = 0U;
    std::uint64_t gpio_payload_transmitted = 0U;
    std::uint64_t frames_promoted = 0U;
    std::uint64_t payload_transmitted = 0U;
    std::uint16_t command_queue_high_water = 0U;
    std::uint16_t response_queue_high_water = 0U;
    expect(wire::loadU64(
               frames[0].payload,
               constants::kStatusResponseAdcFramesEmittedOffset,
               adc_emitted) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseGpioFramesEmittedOffset,
                   gpio_emitted) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcItemsDroppedOffset,
                   adc_dropped) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseGpioItemsDroppedOffset,
                   gpio_dropped) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcFramesGeneratedOffset,
                   adc_generated) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseGpioFramesGeneratedOffset,
                   gpio_generated) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcPayloadBytesTransmittedOffset,
                   adc_payload_transmitted) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseGpioPayloadBytesTransmittedOffset,
                   gpio_payload_transmitted) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponsePacketFramesPromotedOffset,
                   frames_promoted) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseDataPayloadBytesTransmittedOffset,
                   payload_transmitted) &&
               wire::loadU16(
                   frames[0].payload,
                   constants::kStatusResponseUsbCommandQueueHighWaterOffset,
                   command_queue_high_water) &&
               wire::loadU16(
                   frames[0].payload,
                   constants::kStatusResponseUsbResponseQueueHighWaterOffset,
                   response_queue_high_water) &&
               adc_emitted == 1U && gpio_emitted == 1U &&
               adc_dropped == 0U && gpio_dropped == 0U &&
               adc_generated == 1U && gpio_generated == 1U &&
               adc_payload_transmitted == constants::kDataPayloadBytes &&
               gpio_payload_transmitted == constants::kDataPayloadBytes &&
               frames_promoted == 2U &&
               payload_transmitted == 2U * constants::kDataPayloadBytes &&
               command_queue_high_water == 1U &&
               response_queue_high_water == 1U &&
               frames[0]
                       .payload.data[constants::kStatusResponseSourceOffset] ==
                   static_cast<std::uint8_t>(
                       constants::Source::kSynthetic),
           "wire STATUS reports source/shared byte, queue, and frame telemetry");
  }
}

void testStartupSchedulingJitterFitsPacketPool() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  stream.max_write_size = constants::kDataFrameBytes;
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(6060U), "jitter test completes BOOT");

  stream.appendInput(configureRequest(151U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 152U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 1U,
         "jitter test reaches a paced RUNNING epoch");
  stream.output.clear();

  // One 64 KiB host read contains sixteen data frames. Retain the five batches
  // measured during a 39.8 ms rig scheduling pause while an interleaved STATUS
  // response waits at a frame boundary, leaving one further batch of margin.
  constexpr std::uint64_t kJitterIntervals = 40U;
  stream.available_write_size = 0U;
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 153U));
  for (std::uint64_t interval = 1U; interval <= kJitterIntervals;
       ++interval) {
    clock.ticks = interval * synthetic::kFrameCoverageTicks;
    const app::LoopReport report = firmware.service();
    expect(report.synthetic.frames_framed == 2U &&
               report.synthetic.frames_dropped == 0U &&
               !report.synthetic.invariant_error,
           "bounded startup USB jitter retains both due source frames");
  }

  const packet::PipelineSnapshot buffered = firmware.packetSnapshot();
  expect(buffered.sources[0].frames_framed == kJitterIntervals &&
             buffered.sources[1].frames_framed == kJitterIntervals &&
             buffered.sources[0].frames_dropped == 0U &&
             buffered.sources[1].frames_dropped == 0U &&
             buffered.pool_exhaustions == 0U &&
             buffered.buffers_owned_high_water == 2U * kJitterIntervals,
         "packet pool absorbs an 80-frame host scheduling excursion");

  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  expect(drain(firmware, stream).quiescent,
         "recovered USB drains the complete jitter backlog");
  const packet::PipelineSnapshot drained = firmware.packetSnapshot();
  expect(drained.sources[0].frames_transmitted == kJitterIntervals &&
             drained.sources[1].frames_transmitted == kJitterIntervals &&
             drained.sources[0].frames_dropped == 0U &&
             drained.sources[1].frames_dropped == 0U,
         "jitter recovery transmits every buffered frame without loss");

  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  std::array<std::size_t, packet::kStreamCount> data_frames{};
  std::size_t status_responses = 0U;
  for (const wire::DecodedFrame &frame : frames) {
    if (frame.header.kind == constants::FrameKind::kAdcData) {
      ++data_frames[packet::streamIndex(packet::Stream::kAdc)];
    } else if (frame.header.kind == constants::FrameKind::kGpioData) {
      ++data_frames[packet::streamIndex(packet::Stream::kGpio)];
    } else if (frame.header.kind ==
               constants::FrameKind::kGetStatusResponse) {
      ++status_responses;
    }
  }
  expect(data_frames[0] == kJitterIntervals &&
             data_frames[1] == kJitterIntervals && status_responses == 1U,
         "jitter recovery preserves both streams and interleaved STATUS");
}

void testTransmitVisitsInterleaveAcquisitionWork() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  stream.max_write_size = constants::kDataFrameBytes;
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(7070U), "interleaved TX test completes BOOT");

  stream.appendInput(configureRequest(181U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 182U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 1U,
         "interleaved TX test reaches a paced RUNNING epoch");
  stream.output.clear();
  stream.max_write_size = board::kUsbTxMinimumWriteBytes;

  clock.ticks = synthetic::kFrameCoverageTicks;
  const app::LoopReport report = firmware.service();
  expect(report.synthetic.frames_framed == 2U &&
             report.packet_promotion_before_second_acquisition.frames_promoted ==
                 2U &&
             report.transmit_before_second_acquisition.bytes_written ==
                 constants::kDataFrameBytes &&
             report.transmit_before_second_acquisition.io_calls ==
                 board::kUsbTxCallsPerVisit &&
             report.transmit_before_second_acquisition.call_budget_exhausted &&
             report.packet_promotion.frames_promoted == 0U &&
             report.transmit.bytes_written == constants::kDataFrameBytes &&
             report.transmit.io_calls == board::kUsbTxCallsPerVisit &&
             report.transmit.call_budget_exhausted &&
             report.transmit_before_second_acquisition.bytes_written +
                     report.transmit.bytes_written <=
                 board::kUsbTxBudgetBytesPerLoop,
         "two bounded post-producer visits transmit both source frames");
  const packet::PipelineSnapshot snapshot = firmware.packetSnapshot();
  expect(snapshot.sources[0].frames_transmitted == 1U &&
             snapshot.sources[1].frames_transmitted == 1U &&
             snapshot.sources[0].frames_dropped == 0U &&
             snapshot.sources[1].frames_dropped == 0U &&
             snapshot.pool_exhaustions == 0U,
         "interleaved visits preserve both streams without packet pressure");
}

void testStopDrainGatesNextStartAndPreventsStaleRunData() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  stream.max_write_size = 37U;
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(8080U), "drain-gate test completes BOOT");

  stream.appendInput(configureRequest(201U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 202U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 1U,
         "first synthetic run starts before the drain race");
  stream.output.clear();

  clock.ticks = synthetic::kFrameCoverageTicks;
  const app::LoopReport partial = firmware.service();
  expect(partial.synthetic.frames_framed == 2U &&
             partial.transmit.bytes_written > 0U &&
             firmware.transportSnapshot().active_frame_bytes_sent > 0U,
         "full-size run-one data is partially active before STOP");

  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 203U));
  stream.appendInput(
      configureRequest(204U, constants::ChecksumAlgorithm::kCrc32c));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 205U));
  const DrainResult stopped = drain(firmware, stream);
  expect(stopped.quiescent && stopped.saw_stop && stopped.packet_stopped &&
             stopped.stop_transmitting_frames == 2U &&
             firmware.state() == constants::DeviceState::kIdle &&
             firmware.runId() == 1U &&
             firmware.packetSnapshot().ready_for_start,
         "STOP drains old frames while rapid reconfiguration remains unapplied");

  const std::vector<wire::DecodedFrame> first_run =
      decodeOutput(stream.output);
  std::size_t old_data_frames = 0U;
  bool saw_busy_configure = false;
  bool saw_unconfigured_start = false;
  for (const wire::DecodedFrame &frame : first_run) {
    if (frame.header.kind == constants::FrameKind::kAdcData ||
        frame.header.kind == constants::FrameKind::kGpioData) {
      ++old_data_frames;
      expect(frame.header.run_id == 1U,
             "every drained data frame retains the stopped run ID");
    }
    if (frame.header.kind == constants::FrameKind::kConfigureResponse &&
        frame.header.request_id == 204U) {
      saw_busy_configure =
          responseError(frame) == constants::ErrorCode::kBusy;
    }
    if (frame.header.kind == constants::FrameKind::kStartResponse &&
        frame.header.request_id == 205U) {
      saw_unconfigured_start =
          responseError(frame) == constants::ErrorCode::kInvalidState;
    }
  }
  expect(old_data_frames == 2U && saw_busy_configure &&
             saw_unconfigured_start,
         "queued Adler-32 frames block a CRC-32C switch and its START");

  const std::size_t next_run_offset = stream.output.size();
  stream.appendInput(
      configureRequest(206U, constants::ChecksumAlgorithm::kCrc32c));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 207U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 2U &&
             firmware.state() == constants::DeviceState::kRunning,
         "retry CONFIGURE and START arm CRC-32C after the drain completes");
  clock.ticks += synthetic::kFrameCoverageTicks;
  expect(drain(firmware, stream).quiescent,
         "run two transmits one aligned frame from each source");
  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 208U));
  expect(drain(firmware, stream).quiescent,
         "run two STOP drains cleanly");

  const std::vector<std::uint8_t> next_run_bytes(
      stream.output.begin() + static_cast<std::ptrdiff_t>(next_run_offset),
      stream.output.end());
  const std::vector<wire::DecodedFrame> next_run =
      decodeOutput(next_run_bytes);
  expect(next_run.size() == 5U &&
             next_run[0].header.kind ==
                 constants::FrameKind::kConfigureResponse &&
             next_run[0].header.request_id == 206U &&
             next_run[0].header.checksum_algorithm ==
                 constants::kBootstrapChecksumAlgorithm &&
             responseError(next_run[0]) == constants::ErrorCode::kOk &&
             next_run[1].header.kind ==
                 constants::FrameKind::kStartResponse &&
             next_run[1].header.request_id == 207U &&
             responseError(next_run[1]) == constants::ErrorCode::kOk &&
             next_run[1].header.run_id == 2U &&
             next_run[2].header.kind == constants::FrameKind::kAdcData &&
             next_run[3].header.kind == constants::FrameKind::kGpioData &&
             next_run[2].header.run_id == 2U &&
             next_run[3].header.run_id == 2U &&
             next_run[2].header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kCrc32c &&
             next_run[3].header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kCrc32c &&
             next_run[4].header.kind ==
                 constants::FrameKind::kStopResponse,
         "bootstrap control frames surround only CRC-32C run-two data");
  const usb::TransportSnapshot transport = firmware.transportSnapshot();
  expect(transport.partial_write_events > 0U &&
             transport.zero_length_write_events == 0U &&
             transport.max_write_request_bytes ==
                 board::kUsbTxMaxWriteBytes,
         "interleaved lifecycle retained large-request and partial-write accounting");
}

void testAcquisitionControllerAuditsBothPhysicalEnginesAtomically() {
  packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline packet_pipeline{packet_storage};
  thingdaq::stats::Statistics statistics{};
  std::vector<std::string> operations{};
  ReadyAdcPlatform adc_platform{};
  adc::Initializer adc_initializer{adc_platform};
  LifecycleTriggerPlatform trigger_platform{operations};
  adc_trigger::Scheduler trigger_scheduler{trigger_platform};
  LifecycleAdcCapture adc_capture{operations};
  adc_packer::AdcFramePacker adc_frame_packer{adc_capture};
  AuditGpioCapture gpio_capture{};
  gpio_packer::PackedBufferStorage gpio_storage{};
  gpio_packer::GpioBatchPacker gpio_frame_packer{gpio_capture, gpio_storage};
  acquisition::Controller controller{
      statistics, packet_pipeline, &gpio_capture, &gpio_frame_packer,
      &adc_initializer, &trigger_scheduler, &adc_capture, &adc_frame_packer};

  const wire::AdcInitializationMetadata metadata = controller.initialize();
  expect(metadata.calibration_states[0] ==
                 constants::AdcCalibrationState::kSucceeded &&
             metadata.calibration_states[1] ==
                 constants::AdcCalibrationState::kSucceeded &&
             trigger_scheduler.snapshot().ready(),
         "controller owns one bounded ADC initialization/trigger boundary");
  operations.clear();

  wire::Configuration combined = control::kPhysicalAdcConfiguration;
  combined.stream_mask =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  expect(acquisition::Controller::isHardwareConfiguration(combined) &&
             acquisition::Controller::isExecutableConfiguration(combined),
         "combined hardware is auditable and executable behind the protocol gate");
  const acquisition::Audit ready = controller.inspect(combined, 1U);
  expect(ready.ready() && ready.contract.valid() &&
             ready.profile == acquisition::Profile::kCombined &&
             ready.adc_inspected && ready.gpio_inspected &&
             ready.adc_capture_status == adc_capture::StartStatus::kOk &&
             ready.gpio_capture_status ==
                 thingdaq::gpio_capture::StartStatus::kOk &&
             adc_capture.inspect_calls == 1U &&
             gpio_capture.inspect_calls == 1U && operations.empty(),
         "combined preflight audits both engines without arming hardware");

  const std::uint32_t adc_inspections_before_invalid =
      adc_capture.inspect_calls;
  const std::uint32_t gpio_inspections_before_invalid =
      gpio_capture.inspect_calls;
  wire::Configuration invalid = combined;
  invalid.data_frame_bytes = constants::kDataFrameBytes - 1U;
  const acquisition::Audit invalid_configuration =
      controller.inspect(invalid, 2U);
  const acquisition::Audit invalid_run = controller.inspect(combined, 0U);
  expect(invalid_configuration.has(
             acquisition::Conflict::kInvalidConfiguration) &&
             invalid_run.has(acquisition::Conflict::kInvalidRunId) &&
             adc_capture.inspect_calls == adc_inspections_before_invalid &&
             gpio_capture.inspect_calls == gpio_inspections_before_invalid &&
             operations.empty(),
         "combined preflight rejects the full configuration and run identity before target inspection");

  gpio_capture.inspect_status =
      thingdaq::gpio_capture::StartStatus::kResourceBusy;
  const acquisition::Audit conflict = controller.inspect(combined, 2U);
  expect(!conflict.ready() &&
             conflict.has(acquisition::Conflict::kGpioCaptureUnavailable) &&
             !conflict.has(acquisition::Conflict::kAdcCaptureUnavailable) &&
             conflict.adc_inspected && conflict.gpio_inspected &&
             operations.empty(),
         "one GPIO resource collision rejects the whole combined audit");
  expect(!controller.readyForStart(combined, 2U) &&
             statistics.snapshot().gpio_raw_capture.resource_conflicts == 1U,
         "runtime preflight projects a typed GPIO resource conflict once");

  acquisition::Controller missing{statistics, packet_pipeline};
  const acquisition::Audit absent = missing.inspect(combined, 3U);
  expect(absent.has(acquisition::Conflict::kAdcComponentsMissing) &&
             absent.has(acquisition::Conflict::kGpioComponentsMissing) &&
             !absent.ready(),
         "combined preflight fails closed when either engine is absent");
}

void testCombinedControllerUsesOneEpochAndDeterministicLifecycle() {
  packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline packet_pipeline{packet_storage};
  thingdaq::stats::Statistics statistics{};
  std::vector<std::string> operations{};
  ReadyAdcPlatform adc_platform{};
  adc::Initializer adc_initializer{adc_platform};
  LifecycleTriggerPlatform trigger_platform{operations};
  adc_trigger::Scheduler trigger_scheduler{trigger_platform};
  LifecycleAdcCapture adc_capture{operations};
  adc_packer::AdcFramePacker adc_frame_packer{adc_capture};
  LifecycleGpioCapture gpio_capture{operations};
  gpio_packer::PackedBufferStorage gpio_storage{};
  gpio_packer::GpioBatchPacker gpio_frame_packer{gpio_capture, gpio_storage};
  acquisition::Controller controller{
      statistics, packet_pipeline, &gpio_capture, &gpio_frame_packer,
      &adc_initializer, &trigger_scheduler, &adc_capture, &adc_frame_packer};

  wire::Configuration combined = control::kPhysicalAdcConfiguration;
  combined.stream_mask =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  combined.data_checksum_algorithm = constants::ChecksumAlgorithm::kCrc32c;
  expect(controller.initialize().trigger.error_flags == 0U,
         "combined lifecycle completes the bounded trigger BOOT gate");
  operations.clear();

  constexpr std::uint32_t kRunOne = 41U;
  constexpr std::uint64_t kEpochOne = 0x123456789ABCULL;
  expect(packet_pipeline.startRun(kRunOne,
                                  combined.data_checksum_algorithm,
                                  combined.stream_mask) ==
                 packet::OperationStatus::kOk,
         "combined lifecycle reserves one packet epoch");
  acquisition::Report started{};
  expect(controller.start(combined, kRunOne, kEpochOne, started) &&
             started.adc_packer_started && started.gpio_packer_started &&
             started.adc_capture_prepared &&
             started.gpio_capture_prepared &&
             started.gpio_capture_started && started.adc_trigger_armed &&
             controller.active() && controller.activeRunId() == kRunOne &&
             controller.epochTicks() == kEpochOne &&
             controller.activeStreamMask() == combined.stream_mask &&
             operations ==
                 std::vector<std::string>{"dma_prepare", "gpio_dma_prepare",
                                          "trigger_arm"},
         "combined START prepares ADC then GPIO DMA before one common trigger arm");
  const adc_packer::Snapshot adc_started =
      adc_frame_packer.snapshot(packet_pipeline);
  const gpio_packer::Snapshot gpio_started =
      gpio_frame_packer.snapshot(packet_pipeline);
  expect(adc_started.run_id == kRunOne && gpio_started.run_id == kRunOne &&
             adc_started.start_epoch_ticks == kEpochOne &&
             gpio_started.start_epoch_ticks == kEpochOne &&
             adc_started.next_source_pair == 0U &&
             gpio_started.next_source_sample == 0U,
         "both physical packers snapshot the same run ID and 8 MHz epoch");

  adc_capture.publish(0U);
  gpio_capture.publish(0U);
  acquisition::Report serviced{};
  controller.service(serviced);
  expect(serviced.adc_packer.frames_framed == 1U &&
             serviced.gpio_packer.frames_framed == 1U,
         "one equal-coverage ADC/GPIO interval is framed from hardware counters");
  const packet::PipelineSnapshot first_interval = packet_pipeline.snapshot();
  expect(first_interval.sources[packet::streamIndex(packet::Stream::kAdc)]
                     .frames_framed == 1U &&
             first_interval.sources[packet::streamIndex(packet::Stream::kGpio)]
                     .frames_framed == 1U,
         "combined sources retain independent frame sequences");
  expect(packet_pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "the common packet owner promotes both first-interval frames");
  for (std::size_t frame = 0U; frame < 2U; ++frame) {
    wire::DecodedFrame decoded{};
    expect(wire::decodeFrame(packet_pipeline.frontFrame(), decoded).ok() &&
               decoded.header.run_id == kRunOne &&
               decoded.header.sequence == 0U &&
               decoded.header.first_sample_ticks == 0U &&
               (decoded.header.flags & static_cast<std::uint16_t>(
                                           constants::FrameFlag::kEpochStart)) !=
                   0U,
           "each source begins at relative tick zero without ISR timestamping");
    packet_pipeline.releaseFrontFrame();
  }

  adc_capture.publish(constants::kAdcPairsPerFrame);
  gpio_capture.publish(constants::kGpioSamplesPerFrame);
  acquisition::Report stopped{};
  expect(controller.stop(stopped) && stopped.physical_drain_pending &&
             stopped.adc_trigger_stopped && stopped.gpio_capture_stopped &&
             stopped.adc_capture_stopped &&
             operations ==
                 std::vector<std::string>{
                     "dma_prepare", "gpio_dma_prepare", "trigger_arm",
                     "trigger_stop", "gpio_dma_stop", "dma_stop"},
         "combined STOP disables the common source before GPIO and ADC DMA");
  acquisition::Report drained{};
  controller.service(drained);
  expect(!controller.active() && !controller.drainPending() &&
             drained.packet_production_stopped &&
             drained.packet_stop.ready_frames_to_drain == 2U &&
             adc_frame_packer.readyForStart() &&
             gpio_frame_packer.readyForStart(),
         "combined STOP retains only complete unsent frames and drains both packers");
  expect(packet_pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "both complete STOP-boundary frames remain transportable");
  for (std::size_t frame = 0U; frame < 2U; ++frame) {
    wire::DecodedFrame decoded{};
    const bool valid =
        wire::decodeFrame(packet_pipeline.frontFrame(), decoded).ok();
    const std::uint64_t expected_ticks =
        decoded.header.kind == constants::FrameKind::kAdcData
            ? constants::kAdcPairsPerFrame *
                  constants::kAdcPairPeriodTicks
            : constants::kGpioSamplesPerFrame *
                  constants::kGpioSamplePeriodTicks;
    expect(valid && decoded.header.run_id == kRunOne &&
               decoded.header.sequence == 1U &&
               decoded.header.first_sample_ticks == expected_ticks,
           "complete STOP frames preserve equal run-relative coverage");
    packet_pipeline.releaseFrontFrame();
  }
  expect(packet_pipeline.readyForStart() && controller.quiescent() &&
             controller.activeRunId() == 0U && controller.epochTicks() == 0U,
         "the complete combined run returns every owner to reusable IDLE");

  constexpr std::uint32_t kFaultRun = 42U;
  expect(packet_pipeline.startRun(kFaultRun,
                                  combined.data_checksum_algorithm,
                                  combined.stream_mask) ==
                 packet::OperationStatus::kOk,
         "a fresh packet epoch starts after the combined drain");
  acquisition::Report restarted{};
  expect(controller.start(combined, kFaultRun, kEpochOne + 1U, restarted),
         "a second combined run starts without stale ownership");
  const adc_packer::Snapshot adc_restarted =
      adc_frame_packer.snapshot(packet_pipeline);
  const gpio_packer::Snapshot gpio_restarted =
      gpio_frame_packer.snapshot(packet_pipeline);
  const packet::PipelineSnapshot packet_restarted =
      packet_pipeline.snapshot();
  expect(adc_restarted.run_id == kFaultRun &&
             gpio_restarted.run_id == kFaultRun &&
             adc_restarted.start_epoch_ticks == kEpochOne + 1U &&
             gpio_restarted.start_epoch_ticks == kEpochOne + 1U &&
             adc_restarted.next_source_pair == 0U &&
             gpio_restarted.next_source_sample == 0U &&
             adc_restarted.service_calls == 0U &&
             gpio_restarted.service_calls == 0U &&
             packet_restarted.run_id == kFaultRun &&
             packet_restarted.ready_queue_depth == 0U &&
             packet_restarted.transmit_queue_depth == 0U &&
             packet_restarted.sources[packet::streamIndex(packet::Stream::kAdc)]
                     .next_sequence == 0U &&
             packet_restarted.sources[packet::streamIndex(packet::Stream::kGpio)]
                     .next_sequence == 0U &&
             adc_capture.rawSnapshot().progress.buffers_completed == 0U &&
             gpio_capture.rawSnapshot().progress.buffers_completed == 0U,
         "a new run resets source counters, sequences, queues, and packer generations");
  operations.clear();
  gpio_capture.fault();
  acquisition::Report faulted{};
  controller.service(faulted);
  expect(faulted.physical_fault_detected && faulted.internal_error &&
             faulted.packet_production_stopped && !controller.active() &&
             !controller.drainPending() && controller.quiescent() &&
             packet_pipeline.readyForStart() &&
             operations ==
                 std::vector<std::string>{"trigger_stop", "gpio_dma_stop",
                                          "dma_stop"},
         "a combined source fault stops the common schedule first and returns reusable IDLE");
}

void testCombinedStartRollsBackEveryPreparedOwner() {
  packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline packet_pipeline{packet_storage};
  thingdaq::stats::Statistics statistics{};
  std::vector<std::string> operations{};
  ReadyAdcPlatform adc_platform{};
  adc::Initializer adc_initializer{adc_platform};
  LifecycleTriggerPlatform trigger_platform{operations};
  adc_trigger::Scheduler trigger_scheduler{trigger_platform};
  LifecycleAdcCapture adc_capture{operations};
  adc_packer::AdcFramePacker adc_frame_packer{adc_capture};
  LifecycleGpioCapture gpio_capture{operations};
  gpio_packer::PackedBufferStorage gpio_storage{};
  gpio_packer::GpioBatchPacker gpio_frame_packer{gpio_capture, gpio_storage};
  acquisition::Controller controller{
      statistics, packet_pipeline, &gpio_capture, &gpio_frame_packer,
      &adc_initializer, &trigger_scheduler, &adc_capture, &adc_frame_packer};
  wire::Configuration combined = control::kPhysicalAdcConfiguration;
  combined.stream_mask =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  expect(controller.initialize().trigger.error_flags == 0U,
         "rollback fixture completes the trigger BOOT gate");
  operations.clear();

  expect(packet_pipeline.startRun(50U,
                                  combined.data_checksum_algorithm,
                                  packet::kAdcStreamMask) ==
                 packet::OperationStatus::kOk,
         "mismatch fixture reserves an ADC-only packet epoch");
  acquisition::Report mismatched{};
  expect(!controller.start(combined, 50U, 8999U, mismatched) &&
             mismatched.internal_error &&
             mismatched.packet_production_stopped && operations.empty() &&
             controller.quiescent() && packet_pipeline.readyForStart(),
         "combined acquisition rejects a different packet stream mask before arming any owner");

  gpio_capture.prepare_status = gpio_capture::StartStatus::kHardwareError;
  expect(packet_pipeline.startRun(51U,
                                  combined.data_checksum_algorithm,
                                  combined.stream_mask) ==
                 packet::OperationStatus::kOk,
         "rollback fixture reserves the packet epoch");

  acquisition::Report failed{};
  expect(!controller.start(combined, 51U, 9000U, failed) &&
             failed.internal_error && failed.adc_packer_started &&
             failed.gpio_packer_started && failed.adc_capture_prepared &&
             !failed.gpio_capture_prepared && failed.adc_capture_stopped &&
             failed.adc_packer_stopped && failed.gpio_packer_stopped &&
             failed.packet_production_stopped && !controller.active() &&
             !controller.drainPending() && controller.quiescent() &&
             packet_pipeline.readyForStart() &&
             operations ==
                 std::vector<std::string>{"dma_prepare", "gpio_dma_prepare",
                                          "dma_stop"},
         "a GPIO prepare failure rolls ADC, both packers, and packet ownership back atomically");
}

enum class CombinedStartFailurePoint : std::uint8_t {
  kPreflight,
  kPacketReservation,
  kAdcPacker,
  kGpioPacker,
  kAdcPrepare,
  kGpioPrepare,
  kTriggerArm,
};

void exerciseCombinedStartRollback(CombinedStartFailurePoint point) {
  CombinedControllerFixture fixture{};
  const wire::Configuration combined = combinedPhysicalConfiguration();
  constexpr std::uint32_t kRunId = 73U;
  expect(fixture.controller.initialize().trigger.error_flags == 0U,
         "rollback matrix initializes the common trigger boundary");
  fixture.operations.clear();

  const std::uint8_t packet_mask =
      point == CombinedStartFailurePoint::kPacketReservation
          ? packet::kAdcStreamMask
          : packet::kAllStreamMask;
  expect(fixture.packet_pipeline.startRun(
             kRunId, combined.data_checksum_algorithm, packet_mask) ==
             packet::OperationStatus::kOk,
         "rollback matrix reserves a packet epoch");

  AdcPackerHookContext adc_hook{
      &fixture.adc_frame_packer, &fixture.packet_pipeline,
      adc_packer::OperationStatus::kNotRunning, kRunId};
  GpioPackerHookContext gpio_hook{
      &fixture.gpio_frame_packer, &fixture.packet_pipeline,
      gpio_packer::OperationStatus::kNotRunning, kRunId};
  switch (point) {
    case CombinedStartFailurePoint::kPreflight:
      fixture.adc_capture.inspect_status =
          adc_capture::StartStatus::kResourceBusy;
      break;
    case CombinedStartFailurePoint::kPacketReservation:
      break;
    case CombinedStartFailurePoint::kAdcPacker:
      fixture.adc_capture.inspect_hook = startAdcPackerDuringInspection;
      fixture.adc_capture.inspect_hook_context = &adc_hook;
      break;
    case CombinedStartFailurePoint::kGpioPacker:
      fixture.gpio_capture.inspect_hook = startGpioPackerDuringInspection;
      fixture.gpio_capture.inspect_hook_context = &gpio_hook;
      break;
    case CombinedStartFailurePoint::kAdcPrepare:
      fixture.adc_capture.prepare_status =
          adc_capture::StartStatus::kHardwareError;
      break;
    case CombinedStartFailurePoint::kGpioPrepare:
      fixture.gpio_capture.prepare_status =
          gpio_capture::StartStatus::kHardwareError;
      break;
    case CombinedStartFailurePoint::kTriggerArm:
      fixture.trigger_platform.arm_ok = false;
      break;
  }

  acquisition::Report report{};
  expect(!fixture.controller.start(combined, kRunId, 987654321U, report) &&
             report.internal_error && report.packet_production_stopped &&
             !fixture.controller.active() &&
             !fixture.controller.drainPending() &&
             !fixture.packet_pipeline.acceptingFrames(),
         "each combined partial START failure closes packet production and controller state");

  switch (point) {
    case CombinedStartFailurePoint::kPreflight:
    case CombinedStartFailurePoint::kPacketReservation:
    case CombinedStartFailurePoint::kAdcPacker:
      expect(fixture.operations.empty() && !report.adc_packer_started &&
                 !report.gpio_packer_started &&
                 !report.adc_capture_prepared &&
                 !report.gpio_capture_prepared &&
                 !report.adc_trigger_armed,
             "failures through ADC packer admission leave every hardware owner untouched");
      break;
    case CombinedStartFailurePoint::kGpioPacker:
      expect(fixture.operations.empty() && report.adc_packer_started &&
                 report.adc_packer_stopped &&
                 !report.gpio_packer_started &&
                 !report.adc_capture_prepared &&
                 !report.gpio_capture_prepared,
             "GPIO packer admission failure releases the earlier ADC packer only");
      break;
    case CombinedStartFailurePoint::kAdcPrepare:
      expect(fixture.operations ==
                     std::vector<std::string>{"dma_prepare"} &&
                 report.adc_packer_started && report.gpio_packer_started &&
                 report.adc_packer_stopped && report.gpio_packer_stopped &&
                 !report.adc_capture_prepared &&
                 !report.gpio_capture_prepared,
             "ADC prepare failure releases both packers without stopping an unowned DMA path");
      break;
    case CombinedStartFailurePoint::kGpioPrepare:
      expect(fixture.operations ==
                     std::vector<std::string>{"dma_prepare",
                                              "gpio_dma_prepare",
                                              "dma_stop"} &&
                 report.adc_capture_prepared &&
                 !report.gpio_capture_prepared &&
                 report.adc_capture_stopped &&
                 report.adc_packer_stopped && report.gpio_packer_stopped,
             "GPIO prepare failure unwinds the earlier ADC DMA owner in reverse order");
      break;
    case CombinedStartFailurePoint::kTriggerArm:
      expect(fixture.operations ==
                     std::vector<std::string>{
                         "dma_prepare", "gpio_dma_prepare", "trigger_arm",
                         "trigger_stop", "gpio_dma_stop", "dma_stop"} &&
                 report.adc_capture_prepared &&
                 report.gpio_capture_prepared &&
                 !report.adc_trigger_armed && report.gpio_capture_stopped &&
                 report.adc_capture_stopped &&
                 report.adc_packer_stopped && report.gpio_packer_stopped,
             "failed common-clock arm cleans the source before both prepared DMA paths");
      break;
  }

  if (adc_hook.status == adc_packer::OperationStatus::kOk) {
    (void)fixture.adc_frame_packer.stopProduction();
  }
  if (gpio_hook.status == gpio_packer::OperationStatus::kOk) {
    (void)fixture.gpio_frame_packer.stopProduction();
  }
  expect(fixture.packet_pipeline.readyForStart() &&
             fixture.controller.quiescent(),
         "every rollback matrix case is reusable after externally injected races release ownership");
}

void testCombinedStartRollbackMatrixCoversEveryAdmissionPoint() {
  for (CombinedStartFailurePoint point : {
           CombinedStartFailurePoint::kPreflight,
           CombinedStartFailurePoint::kPacketReservation,
           CombinedStartFailurePoint::kAdcPacker,
           CombinedStartFailurePoint::kGpioPacker,
           CombinedStartFailurePoint::kAdcPrepare,
           CombinedStartFailurePoint::kGpioPrepare,
           CombinedStartFailurePoint::kTriggerArm,
       }) {
    exerciseCombinedStartRollback(point);
  }
}

void testPhysicalAdcLifecycleOrdersHardwareAndDrainsCompletePairs() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  stream.max_write_size = constants::kDataFrameBytes;
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  std::vector<std::string> operations{};
  ReadyAdcPlatform adc_platform{};
  adc::Initializer adc_initializer{adc_platform};
  LifecycleTriggerPlatform trigger_platform{operations};
  adc_trigger::Scheduler trigger_scheduler{trigger_platform};
  LifecycleAdcCapture adc_capture{operations};
  adc_packer::AdcFramePacker adc_frame_packer{adc_capture};
  app::FirmwareRuntime firmware{
      stream, packet_storage, clock, synthetic::Mode::kRealtime,
      nullptr, nullptr, nullptr, nullptr, nullptr, &adc_initializer,
      &trigger_scheduler, &adc_capture, &adc_frame_packer};

  expect(firmware.begin(9090U) && trigger_scheduler.snapshot().ready(),
         "physical ADC runtime completes converter and trigger BOOT gates");
  operations.clear();
  clock.ticks = 123456U;
  stream.appendInput(physicalAdcConfigureRequest(
      251U, constants::ChecksumAlgorithm::kCrc32c));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 252U));
  expect(drain(firmware, stream).quiescent &&
             firmware.state() == constants::DeviceState::kRunning &&
             firmware.runId() == 1U &&
             operations == std::vector<std::string>{"dma_prepare",
                                                    "trigger_arm"},
         "physical ADC START prepares packet/DMA ownership before arming triggers");
  stream.output.clear();

  adc_capture.publish(0U);
  expect(drain(firmware, stream).quiescent,
         "one complete dual-DMA generation reaches USB");
  std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 1U &&
             frames[0].header.kind == constants::FrameKind::kAdcData &&
             frames[0].header.run_id == 1U &&
             frames[0].header.sequence == 0U &&
             frames[0].header.first_sample_ticks == 0U &&
             frames[0].header.item_count == constants::kAdcPairsPerFrame &&
             frames[0].header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kCrc32c &&
             (frames[0].header.flags &
              static_cast<std::uint16_t>(constants::FrameFlag::kEpochStart)) !=
                 0U &&
             (frames[0].header.flags &
              static_cast<std::uint16_t>(constants::FrameFlag::kSynthetic)) ==
                 0U,
         "physical ADC frame retains run-relative pair timing, CRC-32C, and source metadata");
  if (frames.size() == 1U) {
    std::uint16_t adc0 = 1U;
    std::uint16_t adc1 = 0U;
    expect(wire::loadU16(frames[0].payload, 0U, adc0) &&
               wire::loadU16(frames[0].payload, sizeof(std::uint16_t), adc1) &&
               adc0 == 0U && adc1 == 1U,
           "physical payload keeps ADC0 then ADC1 identity in each counted pair");
  }

  stream.output.clear();
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 253U));
  expect(drain(firmware, stream).quiescent,
         "physical ADC STATUS remains responsive between DMA generations");
  frames = decodeOutput(stream.output);
  if (frames.size() == 1U) {
    std::uint64_t adc0_loops = 0U;
    std::uint64_t adc1_loops = 0U;
    std::uint64_t pairs_captured = 0U;
    std::uint64_t pairs_delivered = 0U;
    std::uint64_t pairs_framed = 0U;
    std::uint64_t pairs_transmitted = 0U;
    expect(frames[0].header.kind ==
                   constants::FrameKind::kGetStatusResponse &&
               frames[0].payload
                       .data[constants::kStatusResponseSourceOffset] ==
                   static_cast<std::uint8_t>(constants::Source::kHardware) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdc0DmaMajorLoopsOffset,
                   adc0_loops) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdc1DmaMajorLoopsOffset,
                   adc1_loops) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcPairsCapturedOffset,
                   pairs_captured) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcPairsDeliveredOffset,
                   pairs_delivered) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcPairsFramedOffset,
                   pairs_framed) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcPairsTransmittedOffset,
                   pairs_transmitted) &&
               adc0_loops == 1U && adc1_loops == 1U &&
               pairs_captured == constants::kAdcPairsPerFrame &&
               pairs_delivered == constants::kAdcPairsPerFrame &&
               pairs_framed == constants::kAdcPairsPerFrame &&
               pairs_transmitted == constants::kAdcPairsPerFrame,
           "STATUS reconciles both ADC DMA channels through transmitted pair counts");
  } else {
    expect(false, "physical ADC STATUS emits one typed response");
  }

  adc_capture.publish(constants::kAdcPairsPerFrame);
  stream.output.clear();
  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 254U));
  const DrainResult stopped = drain(firmware, stream);
  expect(stopped.quiescent && stopped.saw_stop && stopped.packet_stopped &&
             firmware.state() == constants::DeviceState::kIdle &&
             !firmware.physicalDrainPending() &&
             operations ==
                 std::vector<std::string>{"dma_prepare", "trigger_arm",
                                          "dma_boundary_stop", "trigger_stop",
                                          "dma_stop"},
         "physical ADC STOP finishes a paired boundary, disables triggers, then tears down DMA");
  frames = decodeOutput(stream.output);
  expect(frames.size() == 2U &&
             frames[0].header.kind == constants::FrameKind::kStopResponse &&
             frames[0].header.run_id == 1U &&
             frames[1].header.kind == constants::FrameKind::kAdcData &&
             frames[1].header.run_id == 1U &&
             frames[1].header.sequence == 1U &&
             frames[1].header.first_sample_ticks ==
                 constants::kAdcPairsPerFrame *
                     constants::kAdcPairPeriodTicks &&
             adc_frame_packer.readyForStart(),
         "STOP response precedes the final immutable old-run ADC frame");

  stream.output.clear();
  stream.appendInput(configureRequest(255U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 256U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 2U &&
             firmware.state() == constants::DeviceState::kRunning,
         "a synthetic epoch can start only after the physical ADC drain");
  stream.output.clear();
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 257U));
  expect(drain(firmware, stream).quiescent,
         "the new synthetic generation publishes a fresh STATUS snapshot");
  frames = decodeOutput(stream.output);
  if (frames.size() == 1U) {
    std::uint64_t stale_dma_loops = 1U;
    std::uint64_t stale_pairs = 1U;
    expect(wire::loadU64(
               frames[0].payload,
               constants::kStatusResponseAdc0DmaMajorLoopsOffset,
               stale_dma_loops) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kStatusResponseAdcPairsCapturedOffset,
                   stale_pairs) &&
               stale_dma_loops == 0U && stale_pairs == 0U,
           "old physical ADC counters cannot cross the new run/statistics epoch");
  } else {
    expect(false, "the fresh synthetic epoch emits one typed STATUS response");
  }
}

void testChecksumBenchmarkRoundTripPreservesIdleAcquisitionState() {
  FakeCdcStream stream{};
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  FakeBenchmarkPlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner checksum_benchmark{platform, dtcm, ocram};
  app::FirmwareRuntime firmware{
      stream, packet_storage, clock, synthetic::Mode::kRealtime,
      &checksum_benchmark};
  expect(firmware.begin(9876U), "benchmark runtime completes BOOT");
  const thingdaq::stats::Snapshot before =
      firmware.statistics().snapshot();

  stream.appendInput(checksumBenchmarkRequest(301U));
  const DrainResult drained = drain(firmware, stream);
  expect(drained.quiescent && firmware.state() == constants::DeviceState::kIdle,
         "benchmark round trip returns with runtime in IDLE");
  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 1U &&
             frames[0].header.kind ==
                 constants::FrameKind::kChecksumBenchmarkResponse &&
             responseError(frames[0]) == constants::ErrorCode::kOk,
         "runtime emits one typed benchmark response");
  if (frames.size() == 1U) {
    std::uint64_t raw_cycles = 0U;
    std::uint64_t net_cycles = 0U;
    expect(wire::loadU64(
               frames[0].payload,
               constants::kChecksumBenchmarkResponseRawChecksumCyclesOffset,
               raw_cycles) &&
               wire::loadU64(
                   frames[0].payload,
                   constants::kChecksumBenchmarkResponseNetChecksumCyclesOffset,
                   net_cycles) &&
               raw_cycles == 104U && net_cycles == 100U,
           "runtime transports calibrated on-device cycle fields unchanged");
  }
  const thingdaq::stats::Snapshot after =
      firmware.statistics().snapshot();
  expect(after.generation == before.generation &&
             after.adc_frames_emitted == before.adc_frames_emitted &&
             after.gpio_frames_emitted == before.gpio_frames_emitted &&
             after.adc_items_dropped == before.adc_items_dropped &&
             after.gpio_items_dropped == before.gpio_items_dropped &&
             firmware.packetSnapshot().run_id == 0U &&
             !firmware.syntheticSnapshot().running,
         "benchmark leaves acquisition epoch, source, and counters untouched");
  expect(platform.critical_entries == platform.critical_exits &&
             platform.critical_entries ==
                 constants::kChecksumBenchmarkTimerCalibrationSamples + 1U,
         "runtime benchmark excludes interrupts only during timed intervals");
}

void testGpioClockRoundTripPreservesIdleAcquisitionState() {
  FakeCdcStream stream{};
  packet::OwnedPacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  FakeGpioClockPlatform platform{};
  gpio_clock::Runner diagnostic{platform};
  app::FirmwareRuntime firmware{
      stream, packet_storage, clock, synthetic::Mode::kRealtime, nullptr,
      &diagnostic};
  expect(firmware.begin(9877U), "GPIO clock runtime completes BOOT");
  const thingdaq::stats::Snapshot before =
      firmware.statistics().snapshot();

  stream.appendInput(gpioClockDiagnosticRequest(302U, 1000000U, 4096U));
  const DrainResult drained = drain(firmware, stream);
  expect(drained.quiescent && firmware.state() == constants::DeviceState::kIdle,
         "GPIO clock round trip returns with runtime in IDLE");
  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 1U &&
             frames[0].header.kind ==
                 constants::FrameKind::kGpioClockDiagnosticResponse &&
             responseError(frames[0]) == constants::ErrorCode::kOk,
         "runtime emits one typed GPIO clock response");
  if (frames.size() == 1U) {
    std::uint32_t configured_rate = 0U;
    std::uint32_t scheduled_events = 0U;
    std::uint32_t dma_samples = 0U;
    std::uint32_t error_flags = 1U;
    expect(wire::loadU32(
               frames[0].payload,
               constants::kGpioClockDiagnosticResponseConfiguredRateHzOffset,
               configured_rate) &&
               wire::loadU32(
                   frames[0].payload,
                   constants::
                       kGpioClockDiagnosticResponseScheduledEventCountOffset,
                   scheduled_events) &&
               wire::loadU32(
                   frames[0].payload,
                   constants::kGpioClockDiagnosticResponseDmaSampleCountOffset,
                   dma_samples) &&
               wire::loadU32(
                   frames[0].payload,
                   constants::
                       kGpioClockDiagnosticResponseHardwareErrorFlagsOffset,
                   error_flags) &&
               configured_rate == 1000000U && scheduled_events == 4096U &&
               dma_samples == 4096U && error_flags == 0U,
           "runtime transports exact rate, counts, and hardware status");
  }
  const thingdaq::stats::Snapshot after =
      firmware.statistics().snapshot();
  expect(platform.calls == 1U && platform.observed.pit_load_value == 23U &&
             after.generation == before.generation &&
             after.adc_frames_emitted == before.adc_frames_emitted &&
             after.gpio_frames_emitted == before.gpio_frames_emitted &&
             firmware.packetSnapshot().run_id == 0U &&
             !firmware.syntheticSnapshot().running,
         "GPIO clock diagnostic is one isolated hardware call without an epoch");
}

}  // namespace

int main() {
  testCompleteControlPlane();
  testV2RleRuntimeTelemetryAndConservation();
  testResetStatsWaitsForOlderControlResponses();
  testSyntheticDataCountersReachStatus();
  testStartupSchedulingJitterFitsPacketPool();
  testTransmitVisitsInterleaveAcquisitionWork();
  testStopDrainGatesNextStartAndPreventsStaleRunData();
  testAcquisitionControllerAuditsBothPhysicalEnginesAtomically();
  testCombinedControllerUsesOneEpochAndDeterministicLifecycle();
  testCombinedStartRollsBackEveryPreparedOwner();
  testCombinedStartRollbackMatrixCoversEveryAdmissionPoint();
  testPhysicalAdcLifecycleOrdersHardwareAndDrainsCompletePairs();
  testChecksumBenchmarkRoundTripPreservesIdleAcquisitionState();
  testGpioClockRoundTripPreservesIdleAcquisitionState();
  if (failures != 0) {
    std::cerr << failures << " firmware runtime assertion(s) failed\n";
    return 1;
  }
  std::cout << "firmware runtime integration tests passed\n";
  return 0;
}
