#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "protocol.h"

namespace {

namespace wire = teensy_daq::protocol;
namespace constants = teensy_daq::protocol_v1;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

std::vector<std::uint8_t> readFixture(const std::string &directory,
                                      const std::string &name) {
  std::ifstream input(directory + "/" + name,
                      std::ios::binary | std::ios::ate);
  if (!input) {
    expect(false, "could not open fixture " + name);
    return {};
  }
  const std::streamsize length = input.tellg();
  input.seekg(0, std::ios::beg);
  std::vector<std::uint8_t> bytes(static_cast<std::size_t>(length));
  if (length > 0 &&
      !input.read(reinterpret_cast<char *>(bytes.data()), length)) {
    expect(false, "could not read fixture " + name);
    return {};
  }
  return bytes;
}

wire::ByteView view(const std::vector<std::uint8_t> &bytes) {
  return {bytes.data(), bytes.size()};
}

template <std::size_t Capacity>
void expectFrame(const wire::FixedFrame<Capacity> &actual,
                 const std::vector<std::uint8_t> &expected,
                 const std::string &name) {
  expect(actual.size() == expected.size(), name + " size");
  if (actual.size() != expected.size()) {
    return;
  }
  for (std::size_t index = 0U; index < expected.size(); ++index) {
    if (actual.data()[index] != expected[index]) {
      expect(false, name + " byte " + std::to_string(index));
      return;
    }
  }
}

void testEndianAndChecksum() {
  std::array<std::uint8_t, 16U> bytes{};
  wire::MutableByteView output{bytes.data(), bytes.size()};
  expect(wire::storeU16(output, 1U, 0xABCDU), "store u16");
  expect(wire::storeU32(output, 3U, 0x12345678U), "store u32");
  expect(wire::storeU64(output, 7U, 0x0123456789ABCDEFULL), "store u64");
  expect(bytes[1] == 0xCDU && bytes[2] == 0xABU, "u16 little endian");
  expect(bytes[3] == 0x78U && bytes[6] == 0x12U, "u32 little endian");
  expect(bytes[7] == 0xEFU && bytes[14] == 0x01U, "u64 little endian");

  const wire::ByteView input{bytes.data(), bytes.size()};
  std::uint16_t value16 = 0U;
  std::uint32_t value32 = 0U;
  std::uint64_t value64 = 0U;
  expect(wire::loadU16(input, 1U, value16) && value16 == 0xABCDU,
         "load u16");
  expect(wire::loadU32(input, 3U, value32) && value32 == 0x12345678U,
         "load u32");
  expect(wire::loadU64(input, 7U, value64) &&
             value64 == 0x0123456789ABCDEFULL,
         "load u64");
  expect(!wire::loadU32(input, bytes.size() - 3U, value32),
         "bounded u32 load");
  expect(!wire::storeU64(output, bytes.size() - 7U, value64),
         "bounded u64 store");

  expect(wire::adler32({nullptr, 0U}) == 0x00000001U,
         "empty Adler-32 vector");
  const std::array<std::uint8_t, 9U> digits{
      '1', '2', '3', '4', '5', '6', '7', '8', '9'};
  expect(wire::adler32({digits.data(), digits.size()}) == 0x091E01DEU,
         "RFC Adler-32 vector");
  std::uint32_t checksum = 0U;
  const wire::Result unsupported = wire::computeChecksum(
      constants::ChecksumAlgorithm::kCrc32c, {digits.data(), digits.size()},
      checksum);
  expect(unsupported.error == constants::ErrorCode::kUnsupportedChecksum,
         "checksum dispatch rejects disabled CRC32C");
}

void testGoldenDecode(const std::string &fixture_directory) {
  const std::array<const char *, 17U> fixtures{
      "adc-data.bin",
      "gpio-data.bin",
      "info-request.bin",
      "configure-request.bin",
      "start-request.bin",
      "get-status-request.bin",
      "stop-request.bin",
      "reset-stats-request.bin",
      "ping-request.bin",
      "info-response.bin",
      "configure-response.bin",
      "start-response.bin",
      "get-status-response.bin",
      "stop-response.bin",
      "reset-stats-response.bin",
      "ping-response.bin",
      "error-response.bin",
  };
  for (const char *name : fixtures) {
    const std::vector<std::uint8_t> bytes =
        readFixture(fixture_directory, name);
    wire::DecodedFrame frame{};
    const wire::Result result = wire::decodeFrame(view(bytes), frame);
    expect(result.ok(), std::string("decode golden ") + name);
    if (result.ok()) {
      expect(frame.header.total_length == bytes.size(),
             std::string("owned length ") + name);
      expect(frame.payload.size == frame.header.payload_length,
             std::string("payload length ") + name);
    }
  }

  const std::array<const char *, 7U> requests{
      "info-request.bin",       "configure-request.bin",
      "start-request.bin",      "get-status-request.bin",
      "stop-request.bin",       "reset-stats-request.bin",
      "ping-request.bin",
  };
  for (std::size_t index = 0U; index < requests.size(); ++index) {
    const std::vector<std::uint8_t> bytes =
        readFixture(fixture_directory, requests[index]);
    wire::Request request{};
    const wire::Result result = wire::decodeRequest(view(bytes), request);
    expect(result.ok(), std::string("typed decode ") + requests[index]);
    expect(request.request_id == index + 1U,
           std::string("request ID ") + requests[index]);
  }

  wire::Request configure{};
  const std::vector<std::uint8_t> configure_bytes =
      readFixture(fixture_directory, "configure-request.bin");
  expect(wire::decodeRequest(view(configure_bytes), configure).ok(),
         "decode CONFIGURE values");
  expect(configure.kind == constants::CommandKind::kConfigure &&
             configure.configuration.stream_mask == 3U &&
             configure.configuration.source == constants::Source::kSynthetic &&
             configure.configuration.data_checksum_algorithm ==
                 constants::ChecksumAlgorithm::kAdler32 &&
             configure.configuration.data_frame_bytes == 4096U,
         "typed CONFIGURE values");

  wire::Request ping{};
  const std::vector<std::uint8_t> ping_bytes =
      readFixture(fixture_directory, "ping-request.bin");
  expect(wire::decodeRequest(view(ping_bytes), ping).ok(),
         "decode PING values");
  expect(ping.nonce == 0x0123456789ABCDEFULL, "typed PING nonce");
}

wire::Request request(constants::CommandKind kind, std::uint32_t request_id) {
  wire::Request value{};
  value.kind = kind;
  value.request_id = request_id;
  return value;
}

wire::Configuration goldenConfiguration() {
  wire::Configuration configuration{};
  configuration.stream_mask = 3U;
  configuration.source = constants::Source::kSynthetic;
  configuration.data_checksum_algorithm = constants::ChecksumAlgorithm::kAdler32;
  configuration.data_frame_bytes = 4096U;
  return configuration;
}

void testGoldenEncode(const std::string &fixture_directory) {
  wire::CommandFrame command{};
  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kInfoRequest;
  fields.request_id = 1U;
  expect(wire::encodeFrame(fields, {nullptr, 0U}, command).ok(),
         "encode INFO request");
  expectFrame(command, readFixture(fixture_directory, "info-request.bin"),
              "INFO request golden");

  std::array<std::uint8_t, constants::kConfigureRequestPayloadSize>
      configure_payload{};
  configure_payload[constants::kConfigureRequestStreamMaskOffset] = 3U;
  configure_payload[constants::kConfigureRequestSourceOffset] = 1U;
  configure_payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      1U;
  wire::storeU32({configure_payload.data(), configure_payload.size()},
                 constants::kConfigureRequestDataFrameBytesOffset, 4096U);
  fields.kind = constants::FrameKind::kConfigureRequest;
  fields.request_id = 2U;
  expect(wire::encodeFrame(
             fields, {configure_payload.data(), configure_payload.size()},
             command)
             .ok(),
         "encode CONFIGURE request");
  expectFrame(command,
              readFixture(fixture_directory, "configure-request.bin"),
              "CONFIGURE request golden");

  wire::ControlFrame response{};
  wire::InfoResponse info{};
  info.device_state = constants::DeviceState::kIdle;
  info.supported_stream_mask = 3U;
  info.supported_source_mask = 3U;
  info.capability_bits = 63U;
  info.gpio_pin_map = {6U, 7U, 8U, 9U, 10U, 11U, 12U, 13U};
  info.hardware_serial = 0x12345678U;
  const std::string build_id = "synthetic-golden-v1";
  for (std::size_t index = 0U; index < build_id.size(); ++index) {
    info.build_id[index] = static_cast<std::uint8_t>(build_id[index]);
  }
  expect(wire::encodeInfoResponse(
             request(constants::CommandKind::kInfo, 1U), 0U, info, response)
             .ok(),
         "encode INFO response");
  expectFrame(response, readFixture(fixture_directory, "info-response.bin"),
              "INFO response golden");

  const wire::Configuration configuration = goldenConfiguration();
  expect(wire::encodeConfigureResponse(
             request(constants::CommandKind::kConfigure, 2U), 0U,
             configuration, response)
             .ok(),
         "encode CONFIGURE response");
  expectFrame(response,
              readFixture(fixture_directory, "configure-response.bin"),
              "CONFIGURE response golden");
  expect(wire::encodeStartResponse(
             request(constants::CommandKind::kStart, 3U), 7U, configuration,
             response)
             .ok(),
         "encode START response");
  expectFrame(response, readFixture(fixture_directory, "start-response.bin"),
              "START response golden");

  wire::StatusResponse status{};
  status.device_state = constants::DeviceState::kRunning;
  status.configuration = configuration;
  status.adc_frames_emitted = 1U;
  status.gpio_frames_emitted = 1U;
  status.stats_generation = 2U;
  expect(wire::encodeStatusResponse(
             request(constants::CommandKind::kGetStatus, 4U), 7U, status,
             response)
             .ok(),
         "encode STATUS response");
  expectFrame(response,
              readFixture(fixture_directory, "get-status-response.bin"),
              "STATUS response golden");
  expect(wire::encodeStopResponse(
             request(constants::CommandKind::kStop, 5U), 7U, response)
             .ok(),
         "encode STOP response");
  expectFrame(response, readFixture(fixture_directory, "stop-response.bin"),
              "STOP response golden");
  expect(wire::encodeResetStatsResponse(
             request(constants::CommandKind::kResetStats, 6U), 7U, 3U,
             response)
             .ok(),
         "encode RESET_STATS response");
  expectFrame(response,
              readFixture(fixture_directory, "reset-stats-response.bin"),
              "RESET_STATS response golden");
  wire::Request ping = request(constants::CommandKind::kPing, 7U);
  ping.nonce = 0x0123456789ABCDEFULL;
  expect(wire::encodePingResponse(ping, 7U, response).ok(),
         "encode PING response");
  expectFrame(response, readFixture(fixture_directory, "ping-response.bin"),
              "PING response golden");
  expect(wire::encodeRejectedFrameResponse(
             8U, 0xFEU, 1U, constants::ErrorCode::kUnknownFrameKind, response)
             .ok(),
         "encode generic error response");
  expectFrame(response, readFixture(fixture_directory, "error-response.bin"),
              "ERROR response golden");

  expect(wire::encodeTypedErrorResponse(
             request(constants::CommandKind::kStart, 42U), 7U,
             constants::ErrorCode::kInvalidState, response)
             .ok(),
         "encode typed error response");
  wire::DecodedFrame typed_error{};
  expect(wire::decodeFrame(response.view(), typed_error).ok(),
         "decode typed error response");
  expect(typed_error.header.kind == constants::FrameKind::kStartResponse &&
             typed_error.header.request_id == 42U &&
             (typed_error.header.flags & 0x8000U) != 0U,
         "typed error echoes request identity");

  wire::FixedFrame<47U> too_small{};
  fields.kind = constants::FrameKind::kInfoRequest;
  fields.request_id = 1U;
  const wire::Result bounded =
      wire::encodeFrame(fields, {nullptr, 0U}, too_small);
  expect(bounded.error == constants::ErrorCode::kInvalidLength &&
             too_small.size() == 0U,
         "frame construction refuses insufficient capacity");
}

std::vector<std::uint8_t> mutated(const std::vector<std::uint8_t> &source,
                                  std::size_t offset, std::uint8_t value) {
  std::vector<std::uint8_t> result = source;
  result[offset] = value;
  return result;
}

void expectDecodeError(const std::vector<std::uint8_t> &bytes,
                       constants::ErrorCode error, const std::string &name) {
  wire::DecodedFrame frame{};
  expect(wire::decodeFrame(view(bytes), frame).error == error, name);
}

void testValidation(const std::string &fixture_directory) {
  const std::vector<std::uint8_t> info =
      readFixture(fixture_directory, "info-request.bin");
  expectDecodeError(mutated(info, constants::kHeaderVersionOffset, 2U),
                    constants::ErrorCode::kUnsupportedVersion,
                    "reject bad version");
  expectDecodeError(mutated(info, constants::kHeaderKindOffset, 0xFEU),
                    constants::ErrorCode::kUnknownFrameKind,
                    "reject bad kind");
  expectDecodeError(mutated(info, constants::kHeaderFlagsOffset, 1U),
                    constants::ErrorCode::kInvalidFlags,
                    "reject bad flags");
  expectDecodeError(mutated(info, constants::kHeaderHeaderLengthOffset, 43U),
                    constants::ErrorCode::kInvalidLength,
                    "reject bad header length");
  expectDecodeError(mutated(info, constants::kHeaderRequestIdOffset, 0U),
                    constants::ErrorCode::kInvalidRequestId,
                    "reject zero request ID");
  std::vector<std::uint8_t> checksum = info;
  checksum.back() ^= 0x80U;
  expectDecodeError(checksum, constants::ErrorCode::kChecksumMismatch,
                    "reject bad checksum");
  std::vector<std::uint8_t> trailing = info;
  trailing.push_back(0U);
  expectDecodeError(trailing, constants::ErrorCode::kInvalidLength,
                    "reject trailing bytes");
}

void feedAll(wire::IncrementalCommandParser &parser,
             const std::vector<std::uint8_t> &bytes,
             std::vector<std::uint32_t> &request_ids) {
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    wire::ParsedCommand command{};
    const wire::FeedResult result =
        parser.feed({bytes.data() + offset, bytes.size() - offset}, command);
    expect(result.consumed > 0U, "parser makes forward progress");
    if (result.consumed == 0U) {
      return;
    }
    offset += result.consumed;
    if (result.command_ready) {
      request_ids.push_back(command.request.request_id);
      wire::DecodedFrame owned{};
      expect(wire::decodeFrame(command.frame.view(), owned).ok(),
             "parser output owns a complete frame");
    }
  }
}

void testParser(const std::string &fixture_directory) {
  const std::vector<std::uint8_t> configure =
      readFixture(fixture_directory, "configure-request.bin");
  for (std::size_t split = 0U; split <= configure.size(); ++split) {
    wire::IncrementalCommandParser parser{};
    wire::ParsedCommand command{};
    const wire::FeedResult first =
        parser.feed({configure.data(), split}, command);
    expect(first.consumed == split, "parser consumes arbitrary first split");
    expect(first.command_ready == (split == configure.size()),
           "parser waits for a complete split frame");
    if (!first.command_ready) {
      const wire::FeedResult second = parser.feed(
          {configure.data() + split, configure.size() - split}, command);
      expect(second.command_ready, "parser completes every split point");
    }
    expect(command.request.kind == constants::CommandKind::kConfigure &&
               command.request.request_id == 2U,
           "parser returns typed CONFIGURE command");
  }

  const std::vector<std::uint8_t> info =
      readFixture(fixture_directory, "info-request.bin");
  const std::vector<std::uint8_t> ping =
      readFixture(fixture_directory, "ping-request.bin");
  const std::vector<std::uint8_t> response =
      readFixture(fixture_directory, "stop-response.bin");
  std::vector<std::vector<std::uint8_t>> corruptions{
      mutated(info, constants::kHeaderVersionOffset, 2U),
      mutated(info, constants::kHeaderKindOffset, 0xFEU),
      mutated(info, constants::kHeaderFlagsOffset, 1U),
      mutated(info, constants::kHeaderHeaderLengthOffset, 43U),
      mutated(info, constants::kHeaderChecksumAlgorithmOffset, 2U),
      mutated(info, constants::kHeaderRequestIdOffset, 0U),
      response,
  };
  std::vector<std::uint8_t> bad_checksum = info;
  bad_checksum.back() ^= 1U;
  corruptions.push_back(bad_checksum);

  std::vector<std::uint8_t> stream{0x00U, 0xEFU, 0x00U, 0xBEU, 0xADU};
  for (const auto &candidate : corruptions) {
    stream.insert(stream.end(), candidate.begin(), candidate.end());
    stream.push_back(0x55U);
  }
  stream.insert(stream.end(), info.begin(), info.end());
  stream.insert(stream.end(), ping.begin(), ping.end());

  wire::IncrementalCommandParser parser{};
  std::vector<std::uint32_t> request_ids;
  feedAll(parser, stream, request_ids);
  expect(request_ids == std::vector<std::uint32_t>({1U, 7U}),
         "parser recovers to both valid commands");
  const wire::ParserCounters counters = parser.counters();
  expect(counters.commands_accepted == 2U, "parser accepted count");
  expect(counters.candidates_rejected >= corruptions.size(),
         "parser rejected candidates");
  expect(counters.bad_versions >= 1U && counters.bad_kinds >= 2U &&
             counters.bad_flags >= 1U && counters.bad_lengths >= 1U &&
             counters.bad_checksums >= 1U &&
             counters.bad_request_ids >= 1U &&
             counters.unsupported_checksums >= 1U,
         "parser classifies structural failures");
  expect(counters.buffered_bytes == 0U &&
             counters.high_water_mark <= wire::kCommandParserStorageBytes,
         "parser storage remains bounded");

  wire::IncrementalCommandParser partial_parser{};
  wire::ParsedCommand command{};
  const std::array<std::uint8_t, 4U> prefix_noise{0x12U, 0x34U, 0xEFU, 0xBEU};
  partial_parser.feed({prefix_noise.data(), prefix_noise.size()}, command);
  expect(partial_parser.counters().buffered_bytes == 2U,
         "parser retains only partial magic");
  const wire::FeedResult recovered = partial_parser.feed(
      {info.data() + 2U, info.size() - 2U}, command);
  expect(recovered.command_ready && command.request.request_id == 1U,
         "partial magic completes across USB reads");
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: protocol-primitives-test FIXTURE_DIRECTORY\n";
    return 2;
  }
  testEndianAndChecksum();
  testGoldenDecode(argv[1]);
  testGoldenEncode(argv[1]);
  testValidation(argv[1]);
  testParser(argv[1]);
  if (failures != 0) {
    std::cerr << failures << " protocol primitive assertion(s) failed\n";
    return 1;
  }
  return 0;
}
