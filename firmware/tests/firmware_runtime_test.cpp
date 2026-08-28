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

namespace app = teensy_daq::runtime;
namespace board = teensy_daq::board;
namespace constants = teensy_daq::protocol_v1;
namespace control = teensy_daq::control;
namespace identity = teensy_daq::identity;
namespace packet = teensy_daq::packet;
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
         "encode empty request");
  return frame;
}

wire::CommandFrame configureRequest(std::uint32_t request_id) {
  std::array<std::uint8_t, constants::kConfigureRequestPayloadSize> payload{};
  payload[constants::kConfigureRequestStreamMaskOffset] =
      static_cast<std::uint8_t>(constants::StreamMask::kAdc) |
      static_cast<std::uint8_t>(constants::StreamMask::kGpio);
  payload[constants::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants::Source::kSynthetic);
  payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(constants::ChecksumAlgorithm::kAdler32);
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
               report.transmit.bytes_written <= board::kUsbTxBudgetBytesPerLoop &&
               report.transmit.io_calls <= board::kUsbTxCallsPerLoop,
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
  packet::PacketBufferStorage packet_storage{};
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
  stream.appendInput(
      emptyRequest(constants::FrameKind::kResetStatsRequest, 7U));
  stream.appendInput(emptyRequest(constants::FrameKind::kInfoRequest, 8U));
  const DrainResult stopped = drain(firmware, stream);
  expect(stopped.quiescent && !stopped.saw_start && stopped.saw_stop &&
             !stopped.packet_started && stopped.packet_stopped &&
             firmware.state() == constants::DeviceState::kIdle &&
             firmware.runId() == 1U &&
             !firmware.packetSnapshot().accepting_frames &&
             !firmware.syntheticSnapshot().running,
         "STATUS-PING-STOP-RESET-INFO stops synthetic production in clean IDLE");

  const std::vector<wire::DecodedFrame> frames = decodeOutput(stream.output);
  expect(frames.size() == 8U,
         "one complete response is emitted for every valid request");
  if (frames.size() != 8U) {
    return;
  }

  const std::array<constants::FrameKind, 8U> expected_kinds{
      constants::FrameKind::kInfoResponse,
      constants::FrameKind::kConfigureResponse,
      constants::FrameKind::kStartResponse,
      constants::FrameKind::kGetStatusResponse,
      constants::FrameKind::kPingResponse,
      constants::FrameKind::kStopResponse,
      constants::FrameKind::kResetStatsResponse,
      constants::FrameKind::kInfoResponse,
  };
  for (std::size_t index = 0U; index < frames.size(); ++index) {
    expect(frames[index].header.kind == expected_kinds[index] &&
               frames[index].header.request_id == index + 1U,
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
             info.payload.data[constants::kInfoResponseSupportedSourceMaskOffset] ==
                 2U,
         "INFO advertises both layouts and only the implemented synthetic source");

  const wire::DecodedFrame &status = frames[3];
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
  expect(wire::loadU64(frames[4].payload,
                       constants::kPingResponseNonceOffset, echoed_nonce) &&
             echoed_nonce == nonce,
         "PING survives the complete receive-dispatch-transmit path");
  expect(frames[7].header.run_id == 1U &&
             frames[7]
                     .payload.data[constants::kInfoResponseDeviceStateOffset] ==
                 static_cast<std::uint8_t>(constants::DeviceState::kIdle),
         "final INFO proves retained run provenance and clean IDLE");

  const teensy_daq::stats::Snapshot statistics = firmware.statistics().snapshot();
  const usb::TransportSnapshot transport = firmware.transportSnapshot();
  expect(statistics.generation == 3U &&
             statistics.commands_accepted == 2U &&
             statistics.parser_errors == 0U &&
             statistics.transport_errors == 0U,
         "RESET_STATS clears shared runtime diagnostics then counts itself");
  expect(transport.parser.bad_checksums == 1U &&
             transport.commands_dequeued == 8U &&
             transport.responses_completed == 8U &&
             transport.response_reservations_abandoned == 0U,
         "transport lifetime diagnostics account for parser recovery and I/O");
}

void testSyntheticDataCountersReachStatus() {
  FakeCdcStream stream{};
  stream.max_write_size = constants::kDataFrameBytes;
  packet::PacketBufferStorage packet_storage{};
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
  const teensy_daq::stats::Snapshot native_counters =
      firmware.statistics().snapshot();
  expect(packet_counters.sources[0].frames_transmitted == 1U &&
             packet_counters.sources[1].frames_transmitted == 1U &&
             native_counters.data_path.adc.items_generated ==
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
         "native STATUS diagnostics retain every exact data ownership stage");

  stream.output.clear();
  stream.appendInput(
      emptyRequest(constants::FrameKind::kGetStatusRequest, 103U));
  expect(drain(firmware, stream).quiescent,
         "STATUS is serviced while the paced source waits for its deadline");
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
               adc_emitted == 1U && gpio_emitted == 1U &&
               adc_dropped == 0U && gpio_dropped == 0U &&
               frames[0]
                       .payload.data[constants::kStatusResponseSourceOffset] ==
                   static_cast<std::uint8_t>(
                       constants::Source::kSynthetic),
           "wire STATUS reports emitted frames, drops, and synthetic source");
  }
}

void testStartupSchedulingJitterFitsPacketPool() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  stream.max_write_size = constants::kDataFrameBytes;
  packet::PacketBufferStorage packet_storage{};
  FakeTickClock clock{};
  app::FirmwareRuntime firmware{stream, packet_storage, clock};
  expect(firmware.begin(6060U), "jitter test completes BOOT");

  stream.appendInput(configureRequest(151U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 152U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 1U,
         "jitter test reaches a paced RUNNING epoch");
  stream.output.clear();

  // One 64 KiB host read contains sixteen data frames. Retain another half
  // batch of scheduling margin while the host validates the prior batch and
  // an interleaved STATUS response waits at a frame boundary.
  constexpr std::uint64_t kJitterIntervals = 12U;
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
         "packet pool absorbs a 24-frame startup scheduling excursion");

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

void testStopDrainGatesNextStartAndPreventsStaleRunData() {
  FakeCdcStream stream{};
  stream.max_read_size = 128U;
  stream.available_write_size = board::kUsbTxMaxWriteBytes;
  stream.max_write_size = 37U;
  packet::PacketBufferStorage packet_storage{};
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
  stream.appendInput(configureRequest(204U));
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 205U));
  const DrainResult stopped = drain(firmware, stream);
  expect(stopped.quiescent && stopped.saw_stop && stopped.packet_stopped &&
             stopped.stop_transmitting_frames == 2U &&
             firmware.state() == constants::DeviceState::kConfigured &&
             firmware.runId() == 1U &&
             firmware.packetSnapshot().ready_for_start,
         "STOP drains both transport-owned frames while rapid START stays gated");

  const std::vector<wire::DecodedFrame> first_run =
      decodeOutput(stream.output);
  std::size_t old_data_frames = 0U;
  bool saw_busy_start = false;
  for (const wire::DecodedFrame &frame : first_run) {
    if (frame.header.kind == constants::FrameKind::kAdcData ||
        frame.header.kind == constants::FrameKind::kGpioData) {
      ++old_data_frames;
      expect(frame.header.run_id == 1U,
             "every drained data frame retains the stopped run ID");
    }
    if (frame.header.kind == constants::FrameKind::kStartResponse &&
        frame.header.request_id == 205U) {
      saw_busy_start = responseError(frame) == constants::ErrorCode::kBusy;
    }
  }
  expect(old_data_frames == 2U && saw_busy_start,
         "rapid START returns BUSY without allocating run two");

  const std::size_t next_run_offset = stream.output.size();
  stream.appendInput(emptyRequest(constants::FrameKind::kStartRequest, 206U));
  expect(drain(firmware, stream).quiescent && firmware.runId() == 2U &&
             firmware.state() == constants::DeviceState::kRunning,
         "retry START arms run two after the prior drain completes");
  clock.ticks += synthetic::kFrameCoverageTicks;
  expect(drain(firmware, stream).quiescent,
         "run two transmits one aligned frame from each source");
  stream.appendInput(emptyRequest(constants::FrameKind::kStopRequest, 207U));
  expect(drain(firmware, stream).quiescent,
         "run two STOP drains cleanly");

  const std::vector<std::uint8_t> next_run_bytes(
      stream.output.begin() + static_cast<std::ptrdiff_t>(next_run_offset),
      stream.output.end());
  const std::vector<wire::DecodedFrame> next_run =
      decodeOutput(next_run_bytes);
  expect(next_run.size() == 4U &&
             next_run[0].header.kind ==
                 constants::FrameKind::kStartResponse &&
             next_run[0].header.request_id == 206U &&
             responseError(next_run[0]) == constants::ErrorCode::kOk &&
             next_run[0].header.run_id == 2U &&
             next_run[1].header.kind == constants::FrameKind::kAdcData &&
             next_run[2].header.kind == constants::FrameKind::kGpioData &&
             next_run[1].header.run_id == 2U &&
             next_run[2].header.run_id == 2U &&
             next_run[3].header.kind ==
                 constants::FrameKind::kStopResponse,
         "successful run-two START is followed only by run-two data");
  const usb::TransportSnapshot transport = firmware.transportSnapshot();
  expect(transport.partial_write_events > 0U &&
             transport.zero_length_write_events == 0U &&
             transport.max_write_request_bytes ==
                 board::kUsbTxMaxWriteBytes,
         "interleaved lifecycle retained large-request and partial-write accounting");
}

}  // namespace

int main() {
  testCompleteControlPlane();
  testSyntheticDataCountersReachStatus();
  testStartupSchedulingJitterFitsPacketPool();
  testStopDrainGatesNextStartAndPreventsStaleRunData();
  if (failures != 0) {
    std::cerr << failures << " firmware runtime assertion(s) failed\n";
    return 1;
  }
  std::cout << "firmware runtime integration tests passed\n";
  return 0;
}
