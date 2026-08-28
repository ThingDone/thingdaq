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

constexpr std::array<const char *, 10U> kRequestFixtures{
    "info-request.bin",       "configure-request.bin",
    "start-request.bin",      "get-status-request.bin",
    "stop-request.bin",       "reset-stats-request.bin",
    "ping-request.bin",       "checksum-benchmark-request.bin",
    "gpio-clock-diagnostic-request.bin",
    "gpio-capture-diagnostic-request.bin",
};

constexpr std::array<constants::CommandKind, 10U> kRequestKinds{
    constants::CommandKind::kInfo,
    constants::CommandKind::kConfigure,
    constants::CommandKind::kStart,
    constants::CommandKind::kGetStatus,
    constants::CommandKind::kStop,
    constants::CommandKind::kResetStats,
    constants::CommandKind::kPing,
    constants::CommandKind::kChecksumBenchmark,
    constants::CommandKind::kGpioClockDiagnostic,
    constants::CommandKind::kGpioCaptureDiagnostic,
};

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

std::uint32_t referenceAdler32(wire::ByteView input) {
  constexpr std::uint32_t modulus = 65521U;
  std::uint32_t first = 1U;
  std::uint32_t second = 0U;
  for (std::size_t index = 0U; index < input.size; ++index) {
    first = (first + input.data[index]) % modulus;
    second = (second + first) % modulus;
  }
  return (second << 16U) | first;
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

template <std::size_t Capacity>
void writeFrame(const std::string &directory, const std::string &name,
                const wire::FixedFrame<Capacity> &frame) {
  if (directory.empty()) {
    return;
  }
  std::ofstream output(directory + "/" + name,
                       std::ios::binary | std::ios::trunc);
  expect(static_cast<bool>(output), "could not create interop frame " + name);
  if (!output) {
    return;
  }
  output.write(reinterpret_cast<const char *>(frame.data()),
               static_cast<std::streamsize>(frame.size()));
  expect(static_cast<bool>(output), "could not write interop frame " + name);
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
  const std::array<std::uint8_t, 1U> letter_a{'a'};
  expect(wire::adler32({letter_a.data(), letter_a.size()}) == 0x00620062U,
         "single-byte Adler-32 vector");
  const std::array<std::uint8_t, 9U> wikipedia{
      'W', 'i', 'k', 'i', 'p', 'e', 'd', 'i', 'a'};
  expect(wire::adler32({wikipedia.data(), wikipedia.size()}) == 0x11E60398U,
         "Wikipedia Adler-32 vector");
  const std::array<std::uint8_t, 9U> digits{
      '1', '2', '3', '4', '5', '6', '7', '8', '9'};
  expect(wire::adler32({digits.data(), digits.size()}) == 0x091E01DEU,
         "RFC Adler-32 vector");
  std::array<std::uint8_t, 12000U> long_input{};
  for (std::size_t index = 0U; index < long_input.size(); ++index) {
    long_input[index] =
        static_cast<std::uint8_t>((index * 37U + 11U) & 0xFFU);
  }
  const std::array<std::size_t, 4U> reduction_lengths{
      5551U, 5552U, 5553U, long_input.size()};
  for (std::size_t length : reduction_lengths) {
    const wire::ByteView long_view{long_input.data(), length};
    expect(wire::adler32(long_view) == referenceAdler32(long_view),
           "block-reduced Adler-32 matches the bytewise reference");
  }
  std::uint32_t checksum = 0U;
  expect(wire::computeChecksum(
      constants::ChecksumAlgorithm::kCrc32c, {digits.data(), digits.size()},
      checksum).ok() && checksum == 0xE3069283U,
         "CRC-32C dispatch uses the canonical Castagnoli vector");
  expect(wire::computeChecksum(
      constants::ChecksumAlgorithm::kCrc32IsoHdlc,
      {digits.data(), digits.size()}, checksum).ok() &&
             checksum == 0xCBF43926U,
         "CRC-32/ISO-HDLC dispatch uses the canonical vector");
  const wire::Result unsupported = wire::computeChecksum(
      static_cast<constants::ChecksumAlgorithm>(0xFFU),
      {digits.data(), digits.size()}, checksum);
  expect(unsupported.error == constants::ErrorCode::kUnsupportedChecksum,
         "checksum dispatch rejects unknown IDs");
}

void testGoldenDecode(const std::string &fixture_directory) {
  const std::array<const char *, 23U> fixtures{
      "adc-data.bin",
      "gpio-data.bin",
      "info-request.bin",
      "configure-request.bin",
      "start-request.bin",
      "get-status-request.bin",
      "stop-request.bin",
      "reset-stats-request.bin",
      "ping-request.bin",
      "checksum-benchmark-request.bin",
      "gpio-clock-diagnostic-request.bin",
      "gpio-capture-diagnostic-request.bin",
      "info-response.bin",
      "configure-response.bin",
      "start-response.bin",
      "get-status-response.bin",
      "stop-response.bin",
      "reset-stats-response.bin",
      "ping-response.bin",
      "checksum-benchmark-response.bin",
      "gpio-clock-diagnostic-response.bin",
      "gpio-capture-diagnostic-response.bin",
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

  for (std::size_t index = 0U; index < kRequestFixtures.size(); ++index) {
    const std::vector<std::uint8_t> bytes =
        readFixture(fixture_directory, kRequestFixtures[index]);
    wire::Request request{};
    const wire::Result result = wire::decodeRequest(view(bytes), request);
    expect(result.ok(),
           std::string("typed decode ") + kRequestFixtures[index]);
    expect(request.request_id == index + 1U,
           std::string("request ID ") + kRequestFixtures[index]);
    expect(request.kind == kRequestKinds[index],
           std::string("request kind ") + kRequestFixtures[index]);
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

  wire::Request benchmark{};
  const std::vector<std::uint8_t> benchmark_bytes =
      readFixture(fixture_directory, "checksum-benchmark-request.bin");
  expect(wire::decodeRequest(view(benchmark_bytes), benchmark).ok(),
         "decode CHECKSUM_BENCHMARK values");
  expect(benchmark.checksum_benchmark.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kAdler32 &&
             benchmark.checksum_benchmark.vector ==
                 constants::BenchmarkVector::kCanonical123456789 &&
             benchmark.checksum_benchmark.memory_region ==
                 constants::BenchmarkMemoryRegion::kDtcmPacket &&
             benchmark.checksum_benchmark.cache_state ==
                 constants::BenchmarkCacheState::kHotOrNative &&
             benchmark.checksum_benchmark.batch_count == 4U &&
             benchmark.checksum_benchmark.iterations_per_batch == 64U,
         "typed CHECKSUM_BENCHMARK values");

  wire::Request gpio_clock{};
  const std::vector<std::uint8_t> gpio_clock_bytes =
      readFixture(fixture_directory, "gpio-clock-diagnostic-request.bin");
  expect(wire::decodeRequest(view(gpio_clock_bytes), gpio_clock).ok(),
         "decode GPIO_CLOCK_DIAGNOSTIC values");
  expect(gpio_clock.gpio_clock_diagnostic.rate_hz == 1000000U &&
             gpio_clock.gpio_clock_diagnostic.event_count == 4096U,
         "typed GPIO_CLOCK_DIAGNOSTIC values");
}

void testPythonGeneratedCommands(const std::string &fixture_directory,
                                 const std::string &python_directory) {
  for (std::size_t index = 0U; index < kRequestFixtures.size(); ++index) {
    const std::string name = kRequestFixtures[index];
    const std::vector<std::uint8_t> python_bytes =
        readFixture(python_directory, name);
    const std::vector<std::uint8_t> golden_bytes =
        readFixture(fixture_directory, name);
    expect(python_bytes == golden_bytes,
           "Python request is byte-identical to golden " + name);

    wire::Request decoded{};
    const wire::Result result = wire::decodeRequest(view(python_bytes), decoded);
    expect(result.ok(), "C++ decodes Python request " + name);
    if (result.ok()) {
      expect(decoded.kind == kRequestKinds[index],
             "C++ preserves Python command kind " + name);
      expect(decoded.request_id == index + 1U,
             "C++ preserves Python request ID " + name);
    }
  }
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

void testGoldenEncode(const std::string &fixture_directory,
                      const std::string &response_directory) {
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
  info.capability_bits = constants::kKnownCapabilityMask;
  info.gpio_capture_diagnostic_flags = 3U;
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
  writeFrame(response_directory, "info-response.bin", response);

  const wire::Configuration configuration = goldenConfiguration();
  expect(wire::encodeConfigureResponse(
             request(constants::CommandKind::kConfigure, 2U), 0U,
             configuration, response)
             .ok(),
         "encode CONFIGURE response");
  expectFrame(response,
              readFixture(fixture_directory, "configure-response.bin"),
              "CONFIGURE response golden");
  writeFrame(response_directory, "configure-response.bin", response);
  expect(wire::encodeStartResponse(
             request(constants::CommandKind::kStart, 3U), 7U, configuration,
             response)
             .ok(),
         "encode START response");
  expectFrame(response, readFixture(fixture_directory, "start-response.bin"),
              "START response golden");
  writeFrame(response_directory, "start-response.bin", response);

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
  writeFrame(response_directory, "get-status-response.bin", response);
  expect(wire::encodeStopResponse(
             request(constants::CommandKind::kStop, 5U), 7U, response)
             .ok(),
         "encode STOP response");
  expectFrame(response, readFixture(fixture_directory, "stop-response.bin"),
              "STOP response golden");
  writeFrame(response_directory, "stop-response.bin", response);
  expect(wire::encodeResetStatsResponse(
             request(constants::CommandKind::kResetStats, 6U), 7U, 3U,
             response)
             .ok(),
         "encode RESET_STATS response");
  expectFrame(response,
              readFixture(fixture_directory, "reset-stats-response.bin"),
              "RESET_STATS response golden");
  writeFrame(response_directory, "reset-stats-response.bin", response);
  wire::Request ping = request(constants::CommandKind::kPing, 7U);
  ping.nonce = 0x0123456789ABCDEFULL;
  expect(wire::encodePingResponse(ping, 7U, response).ok(),
         "encode PING response");
  expectFrame(response, readFixture(fixture_directory, "ping-response.bin"),
              "PING response golden");
  writeFrame(response_directory, "ping-response.bin", response);

  wire::Request benchmark =
      request(constants::CommandKind::kChecksumBenchmark, 8U);
  benchmark.checksum_benchmark.checksum_algorithm =
      constants::ChecksumAlgorithm::kAdler32;
  benchmark.checksum_benchmark.vector =
      constants::BenchmarkVector::kCanonical123456789;
  benchmark.checksum_benchmark.memory_region =
      constants::BenchmarkMemoryRegion::kDtcmPacket;
  benchmark.checksum_benchmark.cache_state =
      constants::BenchmarkCacheState::kHotOrNative;
  benchmark.checksum_benchmark.batch_count = 4U;
  benchmark.checksum_benchmark.iterations_per_batch = 64U;
  wire::ChecksumBenchmarkResponse benchmark_response{};
  benchmark_response.request = benchmark.checksum_benchmark;
  benchmark_response.cycle_counter_hz = 600000000U;
  benchmark_response.timer_overhead_cycles = 4U;
  benchmark_response.implementation_code_bytes = 120U;
  benchmark_response.table_bytes = 0U;
  benchmark_response.working_ram_bytes = 8192U;
  benchmark_response.deterministic_digest = 0x12345678U;
  benchmark_response.raw_checksum_cycles = 10240U;
  benchmark_response.net_checksum_cycles = 9216U;
  benchmark_response.cache_setup_cycles = 0U;
  benchmark_response.min_batch_cycles = 2304U;
  benchmark_response.max_batch_cycles = 2304U;
  expect(wire::populateChecksumBenchmarkMetrics(benchmark_response),
         "derive CHECKSUM_BENCHMARK metrics");
  expect(wire::encodeChecksumBenchmarkResponse(
             benchmark, 0U, benchmark_response, response)
             .ok(),
         "encode CHECKSUM_BENCHMARK response");
  expectFrame(response,
              readFixture(fixture_directory,
                          "checksum-benchmark-response.bin"),
              "CHECKSUM_BENCHMARK response golden");
  writeFrame(response_directory, "checksum-benchmark-response.bin", response);

  wire::Request gpio_clock =
      request(constants::CommandKind::kGpioClockDiagnostic, 9U);
  gpio_clock.gpio_clock_diagnostic.rate_hz = 1000000U;
  gpio_clock.gpio_clock_diagnostic.event_count = 4096U;
  wire::GpioClockDiagnosticResponse gpio_clock_response{};
  gpio_clock_response.configured_rate_hz = 1000000U;
  gpio_clock_response.production_rate_hz = 4000000U;
  gpio_clock_response.pit_clock_hz = 24000000U;
  gpio_clock_response.pit_load_value = 23U;
  gpio_clock_response.requested_event_count = 4096U;
  gpio_clock_response.scheduled_event_count = 4096U;
  gpio_clock_response.dma_sample_count = 4096U;
  gpio_clock_response.dwt_counter_hz = 600000000U;
  gpio_clock_response.dwt_elapsed_cycles = 2457600U;
  gpio_clock_response.ccm_cscmr1_configured = 64U;
  gpio_clock_response.ccm_ccgr1_configured = 12288U;
  gpio_clock_response.ccm_ccgr2_configured = 12582912U;
  gpio_clock_response.ccm_ccgr5_configured = 192U;
  gpio_clock_response.pit_ldval_configured = 23U;
  gpio_clock_response.pit_cval_final = 22U;
  gpio_clock_response.pit_tctrl_configured = 1U;
  gpio_clock_response.pit_tflg_final = 1U;
  gpio_clock_response.xbar_sel_configured = 56U;
  gpio_clock_response.xbar_ctrl_configured = 5U;
  gpio_clock_response.dmamux_chcfg_configured = 0x8000001EU;
  gpio_clock_response.dma_cr_configured = 2U;
  gpio_clock_response.dma_erq_configured = 4U;
  gpio_clock_response.tcd_saddr = 0x401BC008U;
  gpio_clock_response.tcd_daddr = 0x20200000U;
  gpio_clock_response.tcd_nbytes = 4U;
  gpio_clock_response.last_sample_word = 0x00030C0FU;
  gpio_clock_response.tcd_citer_final = 4112U;
  gpio_clock_response.tcd_biter = 8208U;
  gpio_clock_response.tcd_csr_final = 8U;
  gpio_clock_response.tcd_attr = 0x0202U;
  gpio_clock_response.pit_channel = 0U;
  gpio_clock_response.xbar_input = 56U;
  gpio_clock_response.xbar_output = 0U;
  gpio_clock_response.edma_channel = 2U;
  gpio_clock_response.dmamux_source = 30U;
  gpio_clock_response.edma_priority = 2U;
  expect(wire::encodeGpioClockDiagnosticResponse(
             gpio_clock, 0U, gpio_clock_response, response)
             .ok(),
         "encode GPIO_CLOCK_DIAGNOSTIC response");
  expectFrame(response,
              readFixture(fixture_directory,
                          "gpio-clock-diagnostic-response.bin"),
              "GPIO_CLOCK_DIAGNOSTIC response golden");
  writeFrame(response_directory, "gpio-clock-diagnostic-response.bin",
             response);

  wire::Request gpio_capture =
      request(constants::CommandKind::kGpioCaptureDiagnostic, 10U);
  wire::GpioCaptureDiagnosticResponse gpio_capture_response{};
  gpio_capture_response.metadata_kind = 1U;
  gpio_capture_response.diagnostic_flags = 307U;
  gpio_capture_response.dwt_counter_hz = 600000000U;
  gpio_capture_response.dwt_elapsed_cycles = 607200U;
  gpio_capture_response.dma_samples_captured = 4055U;
  gpio_capture_response.complete_samples_retained = 4048U;
  gpio_capture_response.samples_analyzed = 256U;
  gpio_capture_response.stopped_partial_samples = 7U;
  gpio_capture_response.raw_word_or = 0x00030C0FU;
  gpio_capture_response.packed_value_or = 0xFFU;
  gpio_capture_response.first_packed_value = 0x5AU;
  gpio_capture_response.last_packed_value = 0x5AU;
  gpio_capture_response.gpr27_before = 0x00030C0FU;
  gpio_capture_response.gpio2_gdir_before = 0x00030C0FU;
  gpio_capture_response.gpio2_psr_before = 0x00020403U;
  gpio_capture_response.gpio2_psr_configured = 0x00020403U;
  gpio_capture_response.gpio2_psr_after = 0x00020403U;
  gpio_capture_response.pit_ldval_configured = 5U;
  gpio_capture_response.pit_tctrl_configured = 1U;
  gpio_capture_response.dmamux_chcfg_configured = 0x8000001EU;
  gpio_capture_response.dma_erq_configured = 4U;
  gpio_capture_response.tcd_citer_configured = 4048U;
  gpio_capture_response.tcd_biter_configured = 4048U;
  gpio_capture_response.tcd_csr_configured = 18U;
  gpio_capture_response.edma_priority_configured = 2U;
  expect(wire::encodeGpioCaptureDiagnosticResponse(
             gpio_capture, 0U, gpio_capture_response, response)
             .ok(),
         "encode GPIO_CAPTURE_DIAGNOSTIC response");
  expectFrame(response,
              readFixture(fixture_directory,
                          "gpio-capture-diagnostic-response.bin"),
              "GPIO_CAPTURE_DIAGNOSTIC response golden");
  writeFrame(response_directory, "gpio-capture-diagnostic-response.bin",
             response);

  expect(wire::encodeRejectedFrameResponse(
             11U, 0xFEU, 1U, constants::ErrorCode::kUnknownFrameKind, response)
             .ok(),
         "encode generic error response");
  expectFrame(response, readFixture(fixture_directory, "error-response.bin"),
              "ERROR response golden");
  writeFrame(response_directory, "error-response.bin", response);

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
}

void testFixedCapacityBoundaries() {
  static_assert(wire::CommandFrame::capacity() ==
                constants::kMaxCommandFrameBytes);
  static_assert(wire::ControlFrame::capacity() ==
                constants::kMaxControlFrameBytes);
  static_assert(wire::DataFrame::capacity() == constants::kMaxDataFrameBytes);

  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kInfoRequest;
  fields.request_id = 1U;

  wire::FixedFrame<constants::kMinFrameBytes> exact_minimum{};
  expect(wire::encodeFrame(fields, {nullptr, 0U}, exact_minimum).ok() &&
             exact_minimum.size() == constants::kMinFrameBytes,
         "minimum command exactly fits its fixed frame");

  wire::FixedFrame<constants::kMinFrameBytes - 1U> below_minimum{};
  const wire::Result minimum_failure =
      wire::encodeFrame(fields, {nullptr, 0U}, below_minimum);
  expect(minimum_failure.error == constants::ErrorCode::kInvalidLength &&
             below_minimum.size() == 0U,
         "minimum command refuses one-byte-short capacity");

  std::array<std::uint8_t, constants::kPingRequestPayloadSize> ping_payload{};
  expect(wire::storeU64({ping_payload.data(), ping_payload.size()},
                        constants::kPingRequestNonceOffset,
                        0x0123456789ABCDEFULL),
         "construct maximum-size PING request payload");
  fields.kind = constants::FrameKind::kPingRequest;
  fields.request_id = 7U;

  wire::FixedFrame<constants::kMaxCommandFrameBytes> exact_maximum{};
  expect(wire::encodeFrame(
             fields, {ping_payload.data(), ping_payload.size()}, exact_maximum)
             .ok() &&
             exact_maximum.size() == constants::kMaxCommandFrameBytes,
         "maximum command exactly fits its fixed frame");

  wire::FixedFrame<constants::kMaxCommandFrameBytes - 1U> below_maximum{};
  const wire::Result maximum_failure = wire::encodeFrame(
      fields, {ping_payload.data(), ping_payload.size()}, below_maximum);
  expect(maximum_failure.error == constants::ErrorCode::kInvalidLength &&
             below_maximum.size() == 0U,
         "maximum command refuses one-byte-short capacity");

  wire::FixedFrame<8U> size_guard{};
  expect(size_guard.setSize(size_guard.capacity()) && size_guard.size() == 8U,
         "fixed frame accepts its exact capacity");
  expect(!size_guard.setSize(size_guard.capacity() + 1U) &&
             size_guard.size() == 0U,
         "fixed frame clears itself after an oversized length");
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
  for (std::size_t fixture_index = 0U;
       fixture_index < kRequestFixtures.size(); ++fixture_index) {
    const std::string fixture_name = kRequestFixtures[fixture_index];
    const std::vector<std::uint8_t> command_bytes =
        readFixture(fixture_directory, fixture_name);
    for (std::size_t split = 0U; split <= command_bytes.size(); ++split) {
      wire::IncrementalCommandParser parser{};
      wire::ParsedCommand command{};
      const wire::FeedResult first =
          parser.feed({command_bytes.data(), split}, command);
      expect(first.consumed == split,
             fixture_name + " consumes split " + std::to_string(split));
      expect(first.command_ready == (split == command_bytes.size()),
             fixture_name + " waits at split " + std::to_string(split));
      if (!first.command_ready) {
        const wire::FeedResult second = parser.feed(
            {command_bytes.data() + split, command_bytes.size() - split},
            command);
        expect(second.command_ready,
               fixture_name + " completes split " + std::to_string(split));
      }
      expect(command.request.kind == kRequestKinds[fixture_index] &&
                 command.request.request_id == fixture_index + 1U,
             fixture_name + " returns its typed request");
      expectFrame(command.frame, command_bytes,
                  fixture_name + " owns exact split bytes");
    }

    wire::IncrementalCommandParser byte_parser{};
    wire::ParsedCommand byte_command{};
    for (std::size_t offset = 0U; offset < command_bytes.size(); ++offset) {
      const wire::FeedResult byte_result = byte_parser.feed(
          {command_bytes.data() + offset, 1U}, byte_command);
      expect(byte_result.consumed == 1U,
             fixture_name + " consumes one-byte chunk");
      expect(byte_result.command_ready ==
                 (offset + 1U == command_bytes.size()),
             fixture_name + " completes only on its final byte");
    }
    expect(byte_command.request.kind == kRequestKinds[fixture_index],
           fixture_name + " survives all one-byte boundaries");
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

  for (const char *fixture_name : kRequestFixtures) {
    const std::vector<std::uint8_t> candidate =
        readFixture(fixture_directory, fixture_name);
    for (std::size_t truncated = 0U; truncated < candidate.size();
         ++truncated) {
      wire::IncrementalCommandParser truncated_parser{};
      wire::ParsedCommand truncated_command{};
      const wire::FeedResult prefix = truncated_parser.feed(
          {candidate.data(), truncated}, truncated_command);
      expect(!prefix.command_ready,
             std::string(fixture_name) + " rejects truncated prefix " +
                 std::to_string(truncated));
      expect(truncated_parser.counters().buffered_bytes <=
                 wire::kCommandParserStorageBytes,
             std::string(fixture_name) + " truncated prefix stays bounded");

      std::vector<std::uint32_t> recovered_ids{};
      feedAll(truncated_parser, info, recovered_ids);
      expect(recovered_ids == std::vector<std::uint32_t>({1U}),
             std::string(fixture_name) +
                 " truncated prefix resynchronizes to the next command");
      expect(truncated_parser.counters().buffered_bytes == 0U,
             std::string(fixture_name) +
                 " leaves no bytes after truncated recovery");
    }
  }
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 2 && argc != 4) {
    std::cerr << "usage: protocol-primitives-test FIXTURE_DIRECTORY "
                 "[PYTHON_COMMAND_DIRECTORY CPP_RESPONSE_DIRECTORY]\n";
    return 2;
  }
  const std::string response_directory = argc == 4 ? argv[3] : "";
  testEndianAndChecksum();
  testGoldenDecode(argv[1]);
  if (argc == 4) {
    testPythonGeneratedCommands(argv[1], argv[2]);
  }
  testGoldenEncode(argv[1], response_directory);
  testFixedCapacityBoundaries();
  testValidation(argv[1]);
  testParser(argv[1]);
  if (failures != 0) {
    std::cerr << failures << " protocol primitive assertion(s) failed\n";
    return 1;
  }
  return 0;
}
