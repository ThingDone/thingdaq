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
  payload[constants::kConfigureRequestStreamMaskOffset] = 0U;
  payload[constants::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants::Source::kHardware);
  payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(constants::ChecksumAlgorithm::kAdler32);
  expect(wire::storeU32(
             {payload.data(), payload.size()},
             constants::kConfigureRequestDataFrameBytesOffset,
             static_cast<std::uint32_t>(constants::kDataFrameBytes)),
         "encode control-only configuration");
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
    return static_cast<usb::IoCount>(max_write_size);
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
  std::size_t max_write_size = 11U;
  std::vector<std::uint8_t> output{};

 private:
  std::vector<std::uint8_t> input_{};
  std::size_t input_offset_ = 0U;
};

struct DrainResult {
  bool quiescent = false;
  bool saw_start = false;
  bool saw_stop = false;
  bool packet_started = false;
  bool packet_stopped = false;
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
  app::FirmwareRuntime firmware{stream, packet_storage};
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
             firmware.packetSnapshot().accepting_frames,
         "INFO-CONFIGURE-START arms the packet run in cooperative context");

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
             !firmware.packetSnapshot().accepting_frames,
         "STATUS-PING-STOP-RESET-INFO stops packet production in clean IDLE");

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
             0U &&
             wire::loadU32(info.payload,
                           constants::kInfoResponseCapabilityBitsOffset,
                           value32) &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kAdcStream)) == 0U &&
             (value32 & static_cast<std::uint32_t>(
                            constants::Capability::kGpioStream)) == 0U,
         "INFO capability metadata cannot claim unimplemented streams");

  const wire::DecodedFrame &status = frames[3];
  expect(status.header.run_id == 1U &&
             status.payload.data[constants::kStatusResponseDeviceStateOffset] ==
                 static_cast<std::uint8_t>(constants::DeviceState::kRunning) &&
             status.payload.data[constants::kStatusResponseStreamMaskOffset] ==
                 0U &&
             wire::loadU32(status.payload,
                           constants::kStatusResponseParserErrorsOffset,
                           value32) &&
             value32 == 1U,
         "RUNNING STATUS projects the applied profile and parser recovery");
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

}  // namespace

int main() {
  testCompleteControlPlane();
  if (failures != 0) {
    std::cerr << failures << " firmware runtime assertion(s) failed\n";
    return 1;
  }
  std::cout << "firmware runtime integration tests passed\n";
  return 0;
}
