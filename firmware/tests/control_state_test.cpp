#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "control_state.h"

namespace {

namespace control = teensy_daq::control;
namespace constants = teensy_daq::protocol_v1;
namespace stats = teensy_daq::stats;
namespace wire = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

wire::Request request(constants::CommandKind kind, std::uint32_t request_id) {
  wire::Request value{};
  value.kind = kind;
  value.request_id = request_id;
  return value;
}

wire::Request configureRequest(std::uint32_t request_id,
                               wire::Configuration configuration =
                                   control::kControlOnlyConfiguration) {
  wire::Request value = request(constants::CommandKind::kConfigure, request_id);
  value.configuration = configuration;
  return value;
}

wire::DecodedFrame decodeResponse(const wire::ControlFrame &response,
                                  const std::string &name) {
  wire::DecodedFrame decoded{};
  const wire::Result result = wire::decodeFrame(response.view(), decoded);
  expect(result.ok(), name + " decodes");
  expect(response.size() <= constants::kMaxControlFrameBytes,
         name + " stays within the control-frame bound");
  return decoded;
}

constants::ErrorCode responseError(const wire::DecodedFrame &response) {
  std::uint16_t raw = static_cast<std::uint16_t>(
      constants::ErrorCode::kInternalError);
  expect(wire::loadU16(response.payload,
                       constants::kResponsePrefixErrorCodeOffset, raw),
         "response error code is present");
  return static_cast<constants::ErrorCode>(raw);
}

void expectTypedResponse(const wire::ControlFrame &response,
                         constants::FrameKind kind,
                         std::uint32_t request_id,
                         constants::ErrorCode error,
                         const std::string &name) {
  const wire::DecodedFrame decoded = decodeResponse(response, name);
  expect(decoded.header.kind == kind, name + " response kind");
  expect(decoded.header.request_id == request_id,
         name + " echoes request ID");
  expect(responseError(decoded) == error, name + " error code");
  const bool error_flag =
      (decoded.header.flags & static_cast<std::uint16_t>(
                                  constants::FrameFlag::kResponseError)) != 0U;
  expect(error_flag == (error != constants::ErrorCode::kOk),
         name + " error flag agrees with status");
}

void testLegalTransitionMatrix() {
  constexpr std::array<constants::DeviceState, 4U> states{
      constants::DeviceState::kBoot,
      constants::DeviceState::kIdle,
      constants::DeviceState::kConfigured,
      constants::DeviceState::kRunning,
  };
  constexpr std::array<std::array<bool, 4U>, 4U> expected{{
      {{false, true, false, false}},
      {{false, true, true, false}},
      {{false, true, true, true}},
      {{false, true, false, false}},
  }};

  for (std::size_t from = 0U; from < states.size(); ++from) {
    for (std::size_t to = 0U; to < states.size(); ++to) {
      expect(control::ControlState::isLegalTransition(states[from],
                                                       states[to]) ==
                 expected[from][to],
             "complete legal-transition matrix entry " +
                 std::to_string(from) + "->" + std::to_string(to));
    }
  }
  expect(control::ControlState::nextRunId(0U) == 1U &&
             control::ControlState::nextRunId(
                 std::numeric_limits<std::uint32_t>::max()) == 1U,
         "run IDs remain nonzero at both allocation boundaries");
}

void testBootAndInfo() {
  control::ControlState state{};
  wire::ControlFrame response{};
  const wire::Request info = request(constants::CommandKind::kInfo, 1U);

  const control::DispatchResult during_boot = state.dispatch(info, response);
  expect(during_boot.status == control::DispatchStatus::kNoResponse,
         "BOOT does not answer commands");
  expect(response.size() == 0U, "BOOT leaves no stale response");
  expect(state.state() == constants::DeviceState::kBoot,
         "device begins in BOOT");

  expect(state.completeBoot(0x89ABCDEFU), "BOOT completes once");
  expect(state.state() == constants::DeviceState::kIdle,
         "bounded boot enters IDLE");
  expect(!state.completeBoot(0x12345678U), "BOOT completion is idempotent");
  expect(state.hardwareSerial() == 0x89ABCDEFU,
         "repeated boot completion preserves hardware serial");

  const control::DispatchResult result = state.dispatch(info, response);
  expect(result.commandAccepted(), "INFO succeeds in IDLE");
  expectTypedResponse(response, constants::FrameKind::kInfoResponse, 1U,
                      constants::ErrorCode::kOk, "INFO");
  const wire::DecodedFrame decoded = decodeResponse(response, "INFO fields");
  expect(decoded.header.run_id == 0U, "INFO reports zero before first run");
  expect(decoded.payload.data[constants::kInfoResponseDeviceStateOffset] ==
             static_cast<std::uint8_t>(constants::DeviceState::kIdle),
         "INFO reports IDLE");
  expect(decoded.payload
             .data[constants::kInfoResponseSupportedStreamMaskOffset] == 0U,
         "INFO advertises no implemented streams");
  expect(decoded.payload
             .data[constants::kInfoResponseSupportedSourceMaskOffset] == 1U,
         "INFO advertises the hardware source identity");

  std::uint32_t value = 0U;
  expect(wire::loadU32(decoded.payload,
                       constants::kInfoResponseHardwareSerialOffset, value) &&
             value == 0x89ABCDEFU,
         "INFO reports the supplied hardware serial");
  expect(wire::loadU32(decoded.payload,
                       constants::kInfoResponseCapabilityBitsOffset, value) &&
             (value & static_cast<std::uint32_t>(
                          constants::Capability::kAdcStream)) == 0U &&
             (value & static_cast<std::uint32_t>(
                          constants::Capability::kGpioStream)) == 0U &&
             (value & static_cast<std::uint32_t>(
                          constants::Capability::kResetStats)) != 0U &&
             (value & static_cast<std::uint32_t>(
                          constants::Capability::kPing)) != 0U,
         "INFO capability bits are control-only and truthful");

  const std::size_t build_offset = constants::kInfoResponseBuildIdOffset;
  expect(decoded.payload.data[build_offset] == 't' &&
             decoded.payload.data[build_offset + 1U] == 'd' &&
             decoded.payload.data[build_offset + 2U] == 'a' &&
             decoded.payload.data[build_offset + 3U] == 'q' &&
             decoded.payload.data[build_offset + 4U] == '-',
         "INFO includes the centralized build identity");

  wire::Request repeated = info;
  repeated.request_id = 2U;
  expect(state.dispatch(repeated, response).commandAccepted(),
         "repeated INFO is successful");
  expect(state.state() == constants::DeviceState::kIdle &&
             state.runId() == 0U && !state.hasConfiguration(),
         "repeated INFO is state-idempotent");
}

void testControlOnlyLifecycle() {
  control::ControlState state{};
  wire::ControlFrame response{};
  expect(state.completeBoot(17U), "lifecycle boot completion");

  const wire::Request configure = configureRequest(10U);
  expect(state.dispatch(configure, response).commandAccepted(),
         "control-only CONFIGURE succeeds");
  expectTypedResponse(response, constants::FrameKind::kConfigureResponse, 10U,
                      constants::ErrorCode::kOk, "CONFIGURE");
  wire::DecodedFrame decoded = decodeResponse(response, "CONFIGURE echo");
  expect(decoded.payload.data[constants::kConfigureResponseStreamMaskOffset] ==
             0U,
         "CONFIGURE echoes zero streams");
  expect(state.state() == constants::DeviceState::kConfigured &&
             state.hasConfiguration(),
         "CONFIGURE enters CONFIGURED atomically");

  expect(state.dispatch(request(constants::CommandKind::kGetStatus, 11U),
                        response)
             .commandAccepted(),
         "STATUS succeeds while CONFIGURED");
  decoded = decodeResponse(response, "CONFIGURED STATUS");
  expect(decoded.payload.data[constants::kStatusResponseDeviceStateOffset] ==
             static_cast<std::uint8_t>(constants::DeviceState::kConfigured) &&
             decoded.payload.data[constants::kStatusResponseStreamMaskOffset] ==
                 0U,
         "STATUS represents CONFIGURED control-only mode");

  expect(state.dispatch(request(constants::CommandKind::kStart, 12U), response)
             .commandAccepted(),
         "START succeeds from CONFIGURED");
  expectTypedResponse(response, constants::FrameKind::kStartResponse, 12U,
                      constants::ErrorCode::kOk, "START");
  decoded = decodeResponse(response, "START epoch");
  expect(decoded.header.run_id == 1U && state.runId() == 1U,
         "START allocates the first nonzero run ID");
  expect(state.state() == constants::DeviceState::kRunning,
         "START enters RUNNING");
  expect(state.statistics().generation() == 2U,
         "START resets counters into a new generation");
  expect(state.statistics().snapshot().commands_accepted == 1U,
         "START is the first accepted command in its new generation");

  const control::PendingEvents start_events = state.takePendingEvents();
  expect(start_events.has(control::Event::kStartEpoch) &&
             !start_events.has(control::Event::kStop) &&
             start_events.run_id == 1U &&
             start_events.stats_generation == 2U,
         "START signals one explicit epoch reset event");
  expect(state.takePendingEvents().mask == 0U,
         "epoch events are consumed exactly once");

  expect(state.dispatch(request(constants::CommandKind::kGetStatus, 13U),
                        response)
             .commandAccepted(),
         "STATUS succeeds while RUNNING control-only");
  decoded = decodeResponse(response, "RUNNING STATUS");
  expect(decoded.header.run_id == 1U &&
             decoded.payload.data[constants::kStatusResponseDeviceStateOffset] ==
                 static_cast<std::uint8_t>(constants::DeviceState::kRunning) &&
             decoded.payload.data[constants::kStatusResponseStreamMaskOffset] ==
                 0U,
         "RUNNING STATUS keeps zero streams and the current run ID");

  const control::DispatchResult repeated_start =
      state.dispatch(request(constants::CommandKind::kStart, 14U), response);
  expect(!repeated_start.commandAccepted() && repeated_start.responseReady(),
         "repeated START returns a bounded typed error");
  expectTypedResponse(response, constants::FrameKind::kStartResponse, 14U,
                      constants::ErrorCode::kInvalidState,
                      "repeated START");
  expect(state.runId() == 1U &&
             state.state() == constants::DeviceState::kRunning,
         "rejected START cannot allocate or mutate a run");

  const std::uint32_t generation_before_rejected_reset =
      state.statistics().generation();
  state.dispatch(request(constants::CommandKind::kResetStats, 15U), response);
  expectTypedResponse(response, constants::FrameKind::kResetStatsResponse, 15U,
                      constants::ErrorCode::kInvalidState,
                      "RUNNING RESET_STATS");
  expect(state.statistics().generation() ==
             generation_before_rejected_reset,
         "rejected RESET_STATS preserves counters and generation");

  wire::Request ping = request(constants::CommandKind::kPing, 16U);
  ping.nonce = 0x0123456789ABCDEFULL;
  expect(state.dispatch(ping, response).commandAccepted(),
         "PING succeeds while RUNNING");
  decoded = decodeResponse(response, "PING");
  std::uint64_t nonce = 0U;
  expect(wire::loadU64(decoded.payload, constants::kPingResponseNonceOffset,
                       nonce) &&
             nonce == ping.nonce,
         "PING echoes its exact nonce");

  expect(state.dispatch(request(constants::CommandKind::kStop, 17U), response)
             .commandAccepted(),
         "STOP succeeds from RUNNING");
  expectTypedResponse(response, constants::FrameKind::kStopResponse, 17U,
                      constants::ErrorCode::kOk, "STOP");
  decoded = decodeResponse(response, "STOP run retention");
  expect(decoded.header.run_id == 1U && state.runId() == 1U,
         "STOP retains the most recent run ID");
  expect(state.state() == constants::DeviceState::kIdle &&
             !state.hasConfiguration(),
         "STOP clears configuration and returns to IDLE");
  expect(state.takePendingEvents().has(control::Event::kStop),
         "STOP signals acquisition shutdown");

  expect(state.dispatch(request(constants::CommandKind::kStop, 18U), response)
             .commandAccepted(),
         "repeated STOP succeeds");
  expect(state.state() == constants::DeviceState::kIdle &&
             state.takePendingEvents().mask == 0U,
         "repeated STOP is idempotent and emits no duplicate event");

  expect(state.dispatch(configureRequest(19U), response).commandAccepted(),
         "CONFIGURE succeeds after STOP");
  expect(state.dispatch(request(constants::CommandKind::kStart, 20U), response)
             .commandAccepted(),
         "second START succeeds");
  expect(state.runId() == 2U && state.statistics().generation() == 3U,
         "successful START advances run and statistics IDs monotonically");
  state.takePendingEvents();
  state.dispatch(request(constants::CommandKind::kStop, 21U), response);
  state.takePendingEvents();

  const std::uint32_t generation_before_reset =
      state.statistics().generation();
  expect(state.dispatch(request(constants::CommandKind::kResetStats, 22U),
                        response)
             .commandAccepted(),
         "RESET_STATS succeeds in IDLE");
  decoded = decodeResponse(response, "RESET_STATS generation");
  std::uint32_t reported_generation = 0U;
  expect(wire::loadU32(
             decoded.payload,
             constants::kResetStatsResponseStatsGenerationOffset,
             reported_generation) &&
             reported_generation ==
                 stats::Statistics::nextGeneration(generation_before_reset),
         "RESET_STATS returns its new nonzero generation");
  const stats::Snapshot reset = state.statistics().snapshot();
  expect(reset.commands_accepted == 1U && reset.commands_rejected == 0U &&
             reset.parser_errors == 0U && reset.transport_errors == 0U &&
             reset.adc_frames_emitted == 0U &&
             reset.gpio_frames_emitted == 0U,
         "RESET_STATS clears all diagnostics before counting itself");
}

void testIdempotencyRequestIdsAndCounters() {
  control::ControlState state{};
  wire::ControlFrame response{};
  expect(state.completeBoot(44U), "idempotency test boot completion");

  std::uint32_t request_id = std::numeric_limits<std::uint32_t>::max();
  expect(state.dispatch(request(constants::CommandKind::kInfo, request_id),
                        response)
             .commandAccepted(),
         "INFO accepts the maximum request ID");
  expectTypedResponse(response, constants::FrameKind::kInfoResponse,
                      request_id, constants::ErrorCode::kOk,
                      "maximum-ID INFO");

  --request_id;
  expect(state.dispatch(configureRequest(request_id), response)
             .commandAccepted(),
         "idempotency test enters CONFIGURED");
  --request_id;
  expect(state.dispatch(request(constants::CommandKind::kInfo, request_id),
                        response)
             .commandAccepted() &&
             state.state() == constants::DeviceState::kConfigured &&
             state.hasConfiguration(),
         "INFO is idempotent while CONFIGURED");
  expectTypedResponse(response, constants::FrameKind::kInfoResponse,
                      request_id, constants::ErrorCode::kOk,
                      "CONFIGURED INFO");

  --request_id;
  expect(state.dispatch(request(constants::CommandKind::kStop, request_id),
                        response)
             .commandAccepted() &&
             state.state() == constants::DeviceState::kIdle,
         "STOP reaches IDLE from CONFIGURED");
  expect(state.takePendingEvents().has(control::Event::kStop),
         "first STOP emits the single required stop event");
  --request_id;
  expect(state.dispatch(request(constants::CommandKind::kStop, request_id),
                        response)
             .commandAccepted() &&
             state.state() == constants::DeviceState::kIdle &&
             state.takePendingEvents().mask == 0U,
         "repeated STOP is state- and event-idempotent");
  expectTypedResponse(response, constants::FrameKind::kStopResponse,
                      request_id, constants::ErrorCode::kOk,
                      "idempotent STOP");

  --request_id;
  expect(!state.dispatch(request(constants::CommandKind::kStart, request_id),
                         response)
              .commandAccepted(),
         "START without configuration is rejected");
  expectTypedResponse(response, constants::FrameKind::kStartResponse,
                      request_id, constants::ErrorCode::kInvalidState,
                      "rejected START request ID");

  const stats::Snapshot snapshot = state.statistics().snapshot();
  expect(snapshot.commands_accepted == 5U &&
             snapshot.commands_rejected == 1U &&
             snapshot.state_errors == 1U,
         "accepted, rejected, and state-error counters remain exact");
}

void testConfigurationValidationAndAtomicity() {
  control::ControlState state{};
  wire::ControlFrame response{};
  state.completeBoot(1U);

  struct Case {
    wire::Configuration configuration;
    constants::ErrorCode error;
    const char *name;
  };

  wire::Configuration adc = control::kControlOnlyConfiguration;
  adc.stream_mask = static_cast<std::uint8_t>(constants::StreamMask::kAdc);
  wire::Configuration synthetic = control::kControlOnlyConfiguration;
  synthetic.source = constants::Source::kSynthetic;
  wire::Configuration crc = control::kControlOnlyConfiguration;
  crc.data_checksum_algorithm = constants::ChecksumAlgorithm::kCrc32c;
  wire::Configuration bad_size = control::kControlOnlyConfiguration;
  bad_size.data_frame_bytes = 2048U;
  wire::Configuration unknown_stream = control::kControlOnlyConfiguration;
  unknown_stream.stream_mask = 0x80U;
  wire::Configuration unknown_source = control::kControlOnlyConfiguration;
  unknown_source.source = static_cast<constants::Source>(0xFFU);
  wire::Configuration no_checksum = control::kControlOnlyConfiguration;
  no_checksum.data_checksum_algorithm =
      constants::ChecksumAlgorithm::kNoneReserved;

  const std::array<Case, 7U> cases{{
      {adc, constants::ErrorCode::kUnsupportedConfiguration, "ADC stream"},
      {synthetic, constants::ErrorCode::kUnsupportedConfiguration,
       "synthetic source"},
      {crc, constants::ErrorCode::kUnsupportedChecksum, "disabled checksum"},
      {bad_size, constants::ErrorCode::kInvalidPayload, "wrong frame size"},
      {unknown_stream, constants::ErrorCode::kInvalidPayload,
       "unknown stream field"},
      {unknown_source, constants::ErrorCode::kInvalidPayload,
       "unknown source field"},
      {no_checksum, constants::ErrorCode::kInvalidPayload,
       "reserved checksum field"},
  }};

  std::uint32_t request_id = 30U;
  for (const Case &test_case : cases) {
    const control::DispatchResult result = state.dispatch(
        configureRequest(request_id, test_case.configuration), response);
    expect(result.responseReady() && !result.commandAccepted(),
           std::string(test_case.name) + " returns a typed rejection");
    expectTypedResponse(response, constants::FrameKind::kConfigureResponse,
                        request_id, test_case.error, test_case.name);
    expect(state.state() == constants::DeviceState::kIdle &&
               !state.hasConfiguration(),
           std::string(test_case.name) + " makes no partial state change");
    ++request_id;
  }

  expect(state.dispatch(configureRequest(request_id++), response)
             .commandAccepted(),
         "valid configuration applies after rejections");
  expect(state.state() == constants::DeviceState::kConfigured &&
             state.appliedConfiguration().stream_mask == 0U,
         "valid control-only configuration is retained");
  state.dispatch(configureRequest(request_id, adc), response);
  expect(state.state() == constants::DeviceState::kConfigured &&
             state.appliedConfiguration().stream_mask == 0U,
         "invalid reconfiguration leaves the prior configuration intact");

  std::array<std::uint8_t, constants::kConfigureRequestPayloadSize> payload{};
  payload[constants::kConfigureRequestStreamMaskOffset] = 0U;
  payload[constants::kConfigureRequestSourceOffset] =
      static_cast<std::uint8_t>(constants::Source::kHardware);
  payload[constants::kConfigureRequestDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(constants::ChecksumAlgorithm::kAdler32);
  expect(wire::storeU32({payload.data(), payload.size()},
                        constants::kConfigureRequestDataFrameBytesOffset,
                        static_cast<std::uint32_t>(
                            constants::kDataFrameBytes)),
         "write control-only request payload");

  wire::FrameFields fields{};
  fields.kind = constants::FrameKind::kConfigureRequest;
  fields.request_id = 99U;
  wire::CommandFrame frame{};
  expect(wire::encodeFrame(
             fields, {payload.data(), payload.size()}, frame)
             .ok(),
         "wire codec accepts the documented zero-stream request");
  wire::Request decoded_request{};
  expect(wire::decodeRequest(frame.view(), decoded_request).ok() &&
             decoded_request.configuration.stream_mask == 0U,
         "wire codec decodes the control-only request");

  payload[constants::kConfigureRequestReservedOffset] = 1U;
  const wire::Result unknown_field = wire::encodeFrame(
      fields, {payload.data(), payload.size()}, frame);
  expect(unknown_field.error == constants::ErrorCode::kInvalidPayload &&
             frame.size() == 0U,
         "nonzero reserved configuration fields are rejected");
}

void testRecoverableFaultReturnsIdle() {
  control::ControlState state{};
  wire::ControlFrame response{};
  expect(!state.recoverToIdle() &&
             state.state() == constants::DeviceState::kBoot,
         "recovery cannot bypass BOOT identity initialization");
  expect(state.completeBoot(23U), "recovery test boot completion");
  expect(state.dispatch(configureRequest(70U), response).commandAccepted() &&
             state.dispatch(request(constants::CommandKind::kStart, 71U),
                            response)
                 .commandAccepted(),
         "recovery test reaches RUNNING");

  const std::uint32_t run_id = state.runId();
  const std::uint32_t generation = state.statistics().generation();
  expect(state.recoverToIdle(), "recoverable internal fault reaches IDLE");
  expect(state.state() == constants::DeviceState::kIdle &&
             !state.hasConfiguration() && state.runId() == run_id &&
             state.statistics().generation() == generation,
         "fault recovery clears configuration but preserves provenance");
  const control::PendingEvents events = state.takePendingEvents();
  expect(events.has(control::Event::kStop) &&
             !events.has(control::Event::kStartEpoch),
         "fault recovery cancels an unconsumed START and signals STOP");
  expect(state.recoverToIdle() && state.takePendingEvents().mask == 0U,
         "IDLE recovery is idempotent and emits no duplicate STOP");
  expect(state.dispatch(configureRequest(72U), response).commandAccepted(),
         "normal control resumes after recoverable fault handling");
}

void testStatisticsDetailAndSaturation() {
  stats::Statistics statistics{};
  const std::uint64_t maximum64 =
      std::numeric_limits<std::uint64_t>::max();
  const std::uint32_t maximum32 =
      std::numeric_limits<std::uint32_t>::max();

  statistics.recordAdcFrameEmitted(maximum64);
  statistics.recordAdcFrameEmitted();
  statistics.recordGpioFrameEmitted(7U);
  statistics.recordAdcItemsDropped(maximum64);
  statistics.recordAdcItemsDropped(1U);
  statistics.recordGpioItemsDropped(9U);

  wire::ParserCounters parser{};
  parser.candidates_rejected = 7U;
  parser.bad_checksums = 1U;
  parser.bad_lengths = 2U;
  parser.bad_kinds = 3U;
  parser.bad_versions = 1U;
  statistics.recordParserDelta(parser);
  statistics.recordCommandAccepted();
  statistics.recordCommandRejected(constants::ErrorCode::kInvalidState);
  statistics.recordTimeout();
  statistics.recordTimeout();
  statistics.recordPartialUsbWrite();
  statistics.recordPartialUsbWrite();
  statistics.recordPartialUsbWrite();
  statistics.recordTransportError();

  stats::Snapshot snapshot = statistics.snapshot();
  expect(snapshot.adc_frames_emitted == maximum64 &&
             snapshot.adc_items_dropped == maximum64,
         "64-bit data counters saturate");
  expect(snapshot.gpio_frames_emitted == 7U &&
             snapshot.gpio_items_dropped == 9U,
         "data counters retain exact units");
  expect(snapshot.commands_accepted == 1U &&
             snapshot.commands_rejected == 8U &&
             snapshot.parser_errors == 7U,
         "accepted, rejected, and aggregate parser counters are distinct");
  expect(snapshot.bad_checksums == 1U && snapshot.bad_lengths == 2U &&
             snapshot.bad_types == 3U && snapshot.bad_versions == 1U,
         "parser rejection classifications are retained");
  expect(snapshot.state_errors == 1U && snapshot.timeouts == 2U &&
             snapshot.partial_usb_writes == 3U &&
             snapshot.transport_errors == 3U,
         "state and USB transport diagnostics are retained");

  const wire::StatusResponse status = statistics.wireStatus(
      constants::DeviceState::kRunning,
      control::kControlOnlyConfiguration);
  expect(status.configuration.stream_mask == 0U &&
             status.adc_frames_emitted == maximum64 &&
             status.gpio_frames_emitted == 7U &&
             status.parser_errors == 7U && status.transport_errors == 3U &&
             status.stats_generation == 1U,
         "GET_STATUS projection uses the protocol-defined aggregates");

  wire::ParserCounters saturating_parser{};
  saturating_parser.candidates_rejected = maximum32;
  saturating_parser.bad_checksums = maximum32;
  saturating_parser.bad_lengths = maximum32;
  saturating_parser.bad_kinds = maximum32;
  saturating_parser.bad_versions = maximum32;
  statistics.recordParserDelta(saturating_parser);
  statistics.recordParserDelta(saturating_parser);
  snapshot = statistics.snapshot();
  expect(snapshot.commands_rejected == maximum32 &&
             snapshot.parser_errors == maximum32 &&
             snapshot.bad_checksums == maximum32 &&
             snapshot.bad_lengths == maximum32 &&
             snapshot.bad_types == maximum32 &&
             snapshot.bad_versions == maximum32,
         "32-bit diagnostic counters saturate");

  expect(statistics.resetForNewGeneration() == 2U,
         "statistics reset advances generation");
  snapshot = statistics.snapshot();
  expect(snapshot.generation == 2U && snapshot.commands_accepted == 0U &&
             snapshot.commands_rejected == 0U &&
             snapshot.adc_frames_emitted == 0U &&
             snapshot.transport_errors == 0U,
         "statistics reset clears all counters");
}

}  // namespace

int main() {
  testLegalTransitionMatrix();
  testBootAndInfo();
  testControlOnlyLifecycle();
  testIdempotencyRequestIdsAndCounters();
  testConfigurationValidationAndAtomicity();
  testRecoverableFaultReturnsIdle();
  testStatisticsDetailAndSaturation();

  if (failures != 0) {
    std::cerr << failures << " control/state assertion(s) failed\n";
    return 1;
  }
  std::cout << "control state and statistics tests passed\n";
  return 0;
}
