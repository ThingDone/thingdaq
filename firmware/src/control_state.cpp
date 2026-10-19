#include "control_state.h"

#include <cstddef>

#include "stream_layout.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_CONTROL_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_CONTROL_COLD_CODE(section_name)
#endif

namespace thingdaq::control {
namespace {

constexpr std::uint8_t kKnownStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);

constexpr bool knownSource(protocol_v1::Source source) {
  return source == protocol_v1::Source::kHardware ||
         source == protocol_v1::Source::kSynthetic;
}

constexpr bool capabilityEnabled(protocol_v1::Capability capability) {
  return (capabilities::kCapabilityBits &
          capabilities::capabilityBit(capability)) != 0U;
}

}  // namespace

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.boot")
bool ControlState::completeBoot(
    std::uint32_t hardware_serial,
    const protocol::AdcInitializationMetadata &adc_metadata) {
  if (state_ != protocol_v1::DeviceState::kBoot) {
    return false;
  }
  hardware_serial_ = hardware_serial;
  adc_metadata_ = adc_metadata;
  return transitionTo(protocol_v1::DeviceState::kIdle);
}

bool ControlState::recoverToIdle() {
  if (state_ == protocol_v1::DeviceState::kBoot) {
    return false;
  }

  const bool needs_stop_signal =
      state_ != protocol_v1::DeviceState::kIdle ||
      (pending_event_mask_ & eventBit(Event::kStartEpoch)) != 0U;
  if (!transitionTo(protocol_v1::DeviceState::kIdle)) {
    return false;
  }

  configuration_ = kIdleConfiguration;
  has_configuration_ = false;
  pending_event_mask_ = static_cast<std::uint8_t>(
      pending_event_mask_ &
      static_cast<std::uint8_t>(~eventBit(Event::kStartEpoch)));
  if (needs_stop_signal) {
    pending_event_mask_ = static_cast<std::uint8_t>(
        pending_event_mask_ | eventBit(Event::kStop));
  }
  return true;
}

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.host_session")
void ControlState::beginHostSession() {
  recent_request_ids_ = {};
  recent_request_count_ = 0U;
  next_request_slot_ = 0U;
}

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.dispatch")
DispatchResult ControlState::dispatch(const protocol::Request &request,
                                      protocol::ControlFrame &response,
                                      DispatchReadiness readiness) {
  response.clear();
  if (state_ == protocol_v1::DeviceState::kBoot) {
    return {DispatchStatus::kNoResponse,
            protocol_v1::ErrorCode::kInvalidState,
            protocol::Result::success()};
  }
  if (!rememberRequestId(request.request_id)) {
    return reject(request, protocol_v1::ErrorCode::kInvalidRequestId,
                  response);
  }

  if (request.protocol_version == protocol_v3::kProtocolVersion)
    return dispatchV3(request, response, readiness);

  // Legacy telemetry cannot describe public encoding/layouts. A probe must
  // not produce an invalid legacy reply or trigger response-path recovery.
  if (state_ == protocol_v1::DeviceState::kRunning &&
      negotiated_version_ == protocol_v3::kProtocolVersion &&
      (request.kind == protocol_v1::CommandKind::kInfo ||
       request.kind == protocol_v1::CommandKind::kGetStatus))
    return reject(request, protocol_v1::ErrorCode::kUnsupportedConfiguration, response);

  if (request.kind == protocol::kGetRuntimeHealth) {
    return encoded(request, protocol_v1::ErrorCode::kOk,
                   protocol::encodeRuntimeHealthResponse(request, run_id_, readiness.runtime_health, response),
                   response);
  }
  if (request.kind == protocol::kGetTemperature) {
    return encoded(request, protocol_v1::ErrorCode::kOk,
                   protocol::encodeTemperatureResponse(request, run_id_, readiness.temperature, response),
                   response);
  }
  if (!settings_known_ &&
      (request.kind == protocol_v1::CommandKind::kInfo ||
       request.kind == protocol_v1::CommandKind::kGetStatus))
    return reject(request, protocol_v1::ErrorCode::kInternalError, response);
  switch (request.kind) {
    case protocol_v1::CommandKind::kInfo:
      return encoded(request, protocol_v1::ErrorCode::kOk,
                     protocol::encodeInfoResponse(request, run_id_,
                                                  infoResponse(), response),
                     response);

    case protocol_v1::CommandKind::kConfigure: {
      if (state_ != protocol_v1::DeviceState::kIdle &&
          state_ != protocol_v1::DeviceState::kConfigured) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (!readiness.configuration_ready || readiness.pending_frames != 0U ||
          pending_event_mask_ != 0U) {
        return reject(request, protocol_v1::ErrorCode::kBusy, response);
      }
      auto candidate = request.configuration;
      candidate.legacy_v2 = request.protocol_version == protocol_v2::kProtocolVersion;
      if (request.protocol_version != candidate.protocol_version)
        return reject(request, protocol_v1::ErrorCode::kInvalidPayload, response);
      const protocol_v1::ErrorCode validation = validateConfiguration(candidate);
      if (validation != protocol_v1::ErrorCode::kOk) {
        return reject(request, validation, response);
      }
      const protocol::Result encoding = protocol::encodeConfigureResponse(
          request, run_id_, request.configuration, response);
      if (!encoding.ok()) {
        return encoded(request, protocol_v1::ErrorCode::kInternalError,
                       encoding, response);
      }
      // Returning from v3 restores the compiled legacy clock and RAW policies.
      // Non-release historical rate profiles continue to use their v2 scheduler.
      if (candidate.legacy_v2 && settings::kBuildCpuProfile != 0U) {
        auto legacy_settings = settings::kBuildDefaults;
        legacy_settings[protocol_v3::kSettingsGpioPolicyOffset] = 0U;
        legacy_settings[protocol_v3::kSettingsAdcPolicyOffset] = 0U;
        legacy_settings[protocol_v3::kSettingsStreamMaskOffset] = candidate.stream_mask;
        legacy_settings[protocol_v3::kSettingsSourceOffset] = static_cast<std::uint8_t>(candidate.source);
        legacy_settings[protocol_v3::kSettingsAuxBankModeOffset] = static_cast<std::uint8_t>(candidate.aux_bank_mode);
        legacy_settings[protocol_v3::kSettingsGpioWidthBitsOffset] =
            candidate.aux_bank_mode == protocol_v2::AuxBankMode::kInput ? 16U : 8U;
        legacy_settings[protocol_v3::kSettingsChecksumAlgorithmOffset] =
            static_cast<std::uint8_t>(candidate.data_checksum_algorithm);
        if (!settings_application_.supports(legacy_settings))
          return reject(request, protocol_v1::ErrorCode::kUnsupportedConfiguration, response);
        if (!applySettings(legacy_settings))
          return reject(request, protocol_v1::ErrorCode::kInternalError, response);
      }
      if (!transitionTo(protocol_v1::DeviceState::kConfigured)) {
        response.clear();
        return encoded(
            request, protocol_v1::ErrorCode::kInternalError,
            protocol::Result::failure(protocol_v1::ErrorCode::kInternalError,
                                      protocol::ValidationIssue::kBadPayload),
            response);
      }
      configuration_ = candidate;
      negotiated_version_ = request.protocol_version;
      has_configuration_ = true;
      statistics_.recordCommandAccepted();
      return {DispatchStatus::kResponseReady, protocol_v1::ErrorCode::kOk,
              encoding};
    }

    case protocol_v1::CommandKind::kStart: {
      if (!settings_known_)
        return reject(request, protocol_v1::ErrorCode::kInternalError, response);
      if (negotiated_version_ != 0U && negotiated_version_ != request.protocol_version)
        return reject(request,
                      protocol_v1::ErrorCode::kUnsupportedConfiguration,
                      response);
      if (state_ != protocol_v1::DeviceState::kConfigured ||
          !has_configuration_) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (!readiness.start_ready || readiness.pending_frames != 0U ||
          pending_event_mask_ != 0U) {
        return reject(request, protocol_v1::ErrorCode::kBusy, response);
      }
      const std::uint32_t next_run = nextRunId(run_id_);
      const protocol::Result encoding = protocol::encodeStartResponse(
          request, next_run, configuration_, response);
      if (!encoding.ok()) {
        return encoded(request, protocol_v1::ErrorCode::kInternalError,
                       encoding, response);
      }
      if (!transitionTo(protocol_v1::DeviceState::kRunning)) {
        response.clear();
        return encoded(
            request, protocol_v1::ErrorCode::kInternalError,
            protocol::Result::failure(protocol_v1::ErrorCode::kInternalError,
                                      protocol::ValidationIssue::kBadPayload),
            response);
      }
      run_id_ = next_run;
      statistics_.resetForNewGeneration();
      statistics_.recordCommandAccepted();
      pending_event_mask_ = static_cast<std::uint8_t>(
          pending_event_mask_ | eventBit(Event::kStartEpoch));
      return {DispatchStatus::kResponseReady, protocol_v1::ErrorCode::kOk,
              encoding};
    }

    case protocol_v1::CommandKind::kGetStatus: {
      protocol::StatusResponse status =
          statistics_.wireStatus(state_, appliedConfiguration());
      status.adc = adc_metadata_;
      return encoded(request, protocol_v1::ErrorCode::kOk,
                     protocol::encodeStatusResponse(request, run_id_, status,
                                                    response),
                     response);
    }

    case protocol_v1::CommandKind::kStop: {
      if (negotiated_version_ != 0U && negotiated_version_ != request.protocol_version)
        return reject(request, protocol_v1::ErrorCode::kInvalidState, response);
      const protocol::Result encoding =
          protocol::encodeStopResponse(request, run_id_, response);
      if (!encoding.ok()) {
        return encoded(request, protocol_v1::ErrorCode::kInternalError,
                       encoding, response);
      }
      const bool needs_stop_signal =
          state_ != protocol_v1::DeviceState::kIdle;
      if (!transitionTo(protocol_v1::DeviceState::kIdle)) {
        response.clear();
        return encoded(
            request, protocol_v1::ErrorCode::kInternalError,
            protocol::Result::failure(protocol_v1::ErrorCode::kInternalError,
                                      protocol::ValidationIssue::kBadPayload),
            response);
      }
      configuration_ = kIdleConfiguration;
      has_configuration_ = false;
      pending_event_mask_ &= static_cast<std::uint8_t>(~eventBit(Event::kStartEpoch));
      if (needs_stop_signal) {
        pending_event_mask_ = static_cast<std::uint8_t>(
            pending_event_mask_ | eventBit(Event::kStop));
      }
      statistics_.recordCommandAccepted();
      return {DispatchStatus::kResponseReady, protocol_v1::ErrorCode::kOk,
              encoding};
    }

    case protocol_v1::CommandKind::kResetStats: {
      if (state_ != protocol_v1::DeviceState::kIdle &&
          state_ != protocol_v1::DeviceState::kConfigured) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (!readiness.statistics_reset_ready) {
        return reject(request, protocol_v1::ErrorCode::kBusy, response);
      }
      const std::uint32_t next_generation =
          statistics_.generationAfterReset();
      const protocol::Result encoding = protocol::encodeResetStatsResponse(
          request, run_id_, next_generation, response);
      if (!encoding.ok()) {
        return encoded(request, protocol_v1::ErrorCode::kInternalError,
                       encoding, response);
      }
      statistics_.resetForNewGeneration();
      statistics_.recordCommandAccepted();
      return {DispatchStatus::kResponseReady, protocol_v1::ErrorCode::kOk,
              encoding};
    }

    case protocol_v1::CommandKind::kPing:
      if (!capabilityEnabled(protocol_v1::Capability::kPing)) {
        return reject(request,
                      protocol_v1::ErrorCode::kUnsupportedConfiguration,
                      response);
      }
      return encoded(request, protocol_v1::ErrorCode::kOk,
                     protocol::encodePingResponse(request, run_id_, response),
                     response);

    case protocol_v1::CommandKind::kChecksumBenchmark:
      if (!capabilityEnabled(
              protocol_v1::Capability::kChecksumBenchmark)) {
        return reject(request,
                      protocol_v1::ErrorCode::kUnsupportedConfiguration,
                      response);
      }
      if (state_ != protocol_v1::DeviceState::kIdle) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (readiness.checksum_benchmark_response == nullptr) {
        return reject(request, readiness.checksum_benchmark_error, response);
      }
      return encoded(
          request, protocol_v1::ErrorCode::kOk,
          protocol::encodeChecksumBenchmarkResponse(
              request, run_id_, *readiness.checksum_benchmark_response,
              response),
          response);

    case protocol_v1::CommandKind::kGpioClockDiagnostic:
      if (!capabilityEnabled(
              protocol_v1::Capability::kGpioClockDiagnostic)) {
        return reject(request,
                      protocol_v1::ErrorCode::kUnsupportedConfiguration,
                      response);
      }
      if (state_ != protocol_v1::DeviceState::kIdle) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (readiness.gpio_clock_response == nullptr) {
        return reject(request, readiness.gpio_clock_error, response);
      }
      return encoded(
          request, protocol_v1::ErrorCode::kOk,
          protocol::encodeGpioClockDiagnosticResponse(
              request, run_id_, *readiness.gpio_clock_response, response),
          response);

    case protocol_v1::CommandKind::kGpioCaptureDiagnostic:
      if (!capabilityEnabled(
              protocol_v1::Capability::kGpioCaptureDiagnostic)) {
        return reject(request,
                      protocol_v1::ErrorCode::kUnsupportedConfiguration,
                      response);
      }
      if (state_ != protocol_v1::DeviceState::kIdle) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (readiness.gpio_capture_response == nullptr) {
        return reject(request, readiness.gpio_capture_error, response);
      }
      return encoded(
          request, protocol_v1::ErrorCode::kOk,
          protocol::encodeGpioCaptureDiagnosticResponse(
              request, run_id_, *readiness.gpio_capture_response, response),
          response);
  }

  statistics_.recordCommandRejected(
      protocol_v1::ErrorCode::kUnknownFrameKind);
  return {DispatchStatus::kEncodingFailure,
          protocol_v1::ErrorCode::kUnknownFrameKind,
          protocol::Result::failure(
              protocol_v1::ErrorCode::kUnknownFrameKind,
              protocol::ValidationIssue::kBadKind)};
}

bool ControlState::rememberRequestId(std::uint32_t request_id) {
  if (request_id == 0U) {
    return false;
  }
  for (std::size_t index = 0U; index < recent_request_count_; ++index) {
    if (recent_request_ids_[index] == request_id) {
      return false;
    }
  }
  recent_request_ids_[next_request_slot_] = request_id;
  next_request_slot_ = (next_request_slot_ + 1U) % recent_request_ids_.size();
  if (recent_request_count_ < recent_request_ids_.size()) {
    ++recent_request_count_;
  }
  return true;
}

PendingEvents ControlState::takePendingEvents() {
  PendingEvents events{};
  events.mask = pending_event_mask_;
  events.run_id = run_id_;
  events.stats_generation = statistics_.generation();
  pending_event_mask_ = 0U;
  return events;
}

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.dispatch_v3")
DispatchResult ControlState::dispatchV3(const protocol::Request& request,
                                        protocol::ControlFrame& response,
                                        const DispatchReadiness& readiness) {
  using protocol_v1::ErrorCode;
  using protocol_v3::CommandKind;
  if (!protocol::isV3Command(static_cast<std::uint8_t>(request.kind)))
    return reject(request, ErrorCode::kUnknownFrameKind, response);
  if (!settings_known_ &&
      request.kind != protocol_v1::CommandKind::kConfigure &&
      request.kind != static_cast<protocol_v1::CommandKind>(CommandKind::kGetCapabilities))
    return reject(request, ErrorCode::kInternalError, response);
  if (!settings::boardSupports(active_settings_.settings))
    return reject(request, ErrorCode::kUnsupportedConfiguration, response);
  const auto kind = static_cast<CommandKind>(request.kind);
  protocol::Result result{};
  switch (kind) {
    case CommandKind::kInfo:
      result =
          protocol::encodeV3InfoResponse(request, run_id_, hardware_serial_,
                                         active_settings_.clocks, response);
      break;
    case CommandKind::kGetCapabilities:
      result = protocol::encodeV3CapabilitiesResponse(
          request, run_id_, settings_application_, response);
      break;
    case CommandKind::kGetSettings:
      // Historical non-release v2 rates have no public-v3 settings record.
      if (negotiated_version_ == protocol_v2::kProtocolVersion && has_configuration_ &&
          configuration_.rate_profile != protocol_v2::RateProfile::kAdc1mhzGpio1mhz)
        return reject(request, ErrorCode::kUnsupportedConfiguration, response);
      result = protocol::encodeV3SettingsResponse(request, run_id_,
                                                  active_settings_, response);
      break;
    case CommandKind::kConfigure: {
      const auto valid = protocol::validateV3Settings(
          {request.settings.data(), request.settings.size()});
      if (!valid.ok()) return reject(request, valid.error, response);
      if (state_ == protocol_v1::DeviceState::kRunning)
        return reject(request, ErrorCode::kInvalidState, response);
      if (!readiness.configuration_ready || readiness.pending_frames != 0U ||
          pending_event_mask_ != 0U)
        return reject(request, ErrorCode::kBusy, response);
      if (!settings::boardSupports(request.settings) ||
          !settings_application_.supports(request.settings))
        return reject(request, ErrorCode::kUnsupportedConfiguration, response);
      // Serialize the expected echo before touching hardware. Commit only after
      // exact readback; failed application/readback restores the previous state.
      const settings::Applied expected{request.settings, settings::clocksFor(
          request.settings[protocol_v3::kSettingsCpuProfileOffset])};
      result = protocol::encodeV3SettingsResponse(request, run_id_, expected, response);
      if (result.ok()) {
        if (!applySettings(request.settings))
          return reject(request, ErrorCode::kInternalError, response);
        configuration_ = kIdleConfiguration;
        has_configuration_ = false;
        transitionTo(protocol_v1::DeviceState::kIdle);
        negotiated_version_ = protocol_v3::kProtocolVersion;
      }
      break;
    }
    case CommandKind::kStart: {
      if (state_ == protocol_v1::DeviceState::kRunning)
        return reject(request, ErrorCode::kInvalidState, response);
      if (negotiated_version_ != 0U && negotiated_version_ != protocol_v3::kProtocolVersion)
        return reject(request, ErrorCode::kUnsupportedConfiguration, response);
      if (!readiness.start_ready || readiness.pending_frames != 0U || pending_event_mask_ != 0U)
        return reject(request, ErrorCode::kBusy, response);
      const auto candidate = protocol::publicConfiguration(active_settings_.settings);
      if (!stream_layout::publicV3(candidate.public_settings).ok())
        return reject(request, ErrorCode::kUnsupportedConfiguration, response);
      const auto next_run = nextRunId(run_id_);
      result = protocol::encodeV3SettingsResponse(request, next_run, active_settings_, response);
      if (!result.ok()) break;
      configuration_ = candidate;
      has_configuration_ = true;
      transitionTo(protocol_v1::DeviceState::kConfigured);
      transitionTo(protocol_v1::DeviceState::kRunning);
      negotiated_version_ = protocol_v3::kProtocolVersion;
      run_id_ = next_run;
      statistics_.resetForNewGeneration();
      pending_event_mask_ |= eventBit(Event::kStartEpoch);
      break;
    }
    case CommandKind::kStop:
    case CommandKind::kGetStatus: {
      if (kind == CommandKind::kStop) {
        if (negotiated_version_ != 0U && negotiated_version_ != protocol_v3::kProtocolVersion)
          return reject(request, ErrorCode::kInvalidState, response);
        if (state_ == protocol_v1::DeviceState::kRunning) {
          transitionTo(protocol_v1::DeviceState::kIdle);
          configuration_ = kIdleConfiguration;
          has_configuration_ = false;
          pending_event_mask_ &= static_cast<std::uint8_t>(~eventBit(Event::kStartEpoch));
          pending_event_mask_ |= eventBit(Event::kStop);
        }
      }
      protocol::V3Status status{};
      status.pending_frames = readiness.pending_frames;
      status.diagnostics = readiness.v3_diagnostics;
      status.state = state_ == protocol_v1::DeviceState::kRunning
                         ? protocol_v3::DeviceState::kRunning
                     : readiness.pending_frames != 0U
                         ? protocol_v3::DeviceState::kDraining
                         : protocol_v3::DeviceState::kStopped;
      if (kind == CommandKind::kStop &&
          negotiated_version_ != 0U && negotiated_version_ != protocol_v3::kProtocolVersion)
        return reject(request, ErrorCode::kInvalidState, response);
      const auto snapshot = statistics_.snapshot();
      const auto& adc = snapshot.data_path.adc;
      const auto& gpio = snapshot.data_path.gpio;
      status.counters = {adc.frames_generated,  adc.frames_dropped,
                         adc.items_generated,   adc.items_dropped,
                         gpio.frames_generated, gpio.frames_dropped,
                         gpio.items_generated,  gpio.items_dropped};
      result =
          protocol::encodeV3StatusResponse(request, run_id_, status, response);
      break;
    }
  }
  return encoded(request, ErrorCode::kOk, result, response);
}

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.apply_settings")
bool ControlState::applySettings(const settings::Record& candidate) {
  settings::Applied readback{};
  if (settings_application_.apply(candidate, readback) &&
      readback.settings == candidate &&
      readback.clocks == settings::clocksFor(candidate[protocol_v3::kSettingsCpuProfileOffset])) {
    active_settings_ = readback;
    settings_known_ = true;
    return true;
  }
  settings::Applied restored{};
  settings_known_ = settings_application_.apply(active_settings_.settings, restored) &&
      restored.settings == active_settings_.settings && restored.clocks == active_settings_.clocks;
  // An unverified rollback inhibits START and settings/clock reports until a
  // later successful CONFIGURE. Never report the candidate as applied.
  return false;
}

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.configuration_validation")
protocol_v1::ErrorCode ControlState::validateConfiguration(
    const protocol::Configuration &configuration) {
  if (input_experiment::kReleaseFixed1MHz &&
      (configuration.protocol_version != protocol_v2::kProtocolVersion ||
       configuration.rate_profile != protocol_v2::RateProfile::kAdc1mhzGpio1mhz)) {
    return protocol_v1::ErrorCode::kUnsupportedConfiguration;
  }
  if ((configuration.stream_mask &
       static_cast<std::uint8_t>(~kKnownStreamMask)) != 0U ||
      !knownSource(configuration.source) ||
      configuration.data_checksum_algorithm ==
          protocol_v1::ChecksumAlgorithm::kNoneReserved ||
      configuration.data_frame_bytes != protocol_v1::kDataFrameBytes ||
      (configuration.protocol_version != protocol_v1::kProtocolVersion &&
       configuration.protocol_version != protocol_v2::kProtocolVersion) ||
      (configuration.protocol_version == protocol_v1::kProtocolVersion &&
       (configuration.aux_bank_mode != protocol_v2::kDefaultAuxBankMode ||
        configuration.rate_profile != protocol_v2::kDefaultRateProfile))) {
    return protocol_v1::ErrorCode::kInvalidPayload;
  }

  if (configuration.protocol_version == protocol_v2::kProtocolVersion) {
    const stream_layout::Result layout = stream_layout::experimental(
        configuration.aux_bank_mode, configuration.rate_profile,
        configuration.legacy_v2);
    const auto* actual = rate_profile::timingFor(configuration.rate_profile);
    const auto* legacy = rate_profile::legacyTimingFor(configuration.rate_profile);
    if (!layout.ok() || (configuration.legacy_v2 && actual != nullptr && legacy != nullptr &&
        (actual->adc_pair_period_ticks != legacy->adc_pair_period_ticks ||
         actual->gpio_sample_period_ticks != legacy->gpio_sample_period_ticks))) {
      return protocol_v1::ErrorCode::kUnsupportedConfiguration;
    }
  }

  if (!protocol::isSupportedChecksum(
          configuration.data_checksum_algorithm)) {
    return protocol_v1::ErrorCode::kUnsupportedChecksum;
  }

  const std::uint8_t source_id =
      static_cast<std::uint8_t>(configuration.source);
  if ((configuration.stream_mask &
       static_cast<std::uint8_t>(~capabilities::kSupportedStreamMask)) != 0U ||
      (capabilities::kSupportedSourceMask &
       static_cast<std::uint8_t>(1U << source_id)) == 0U) {
    return protocol_v1::ErrorCode::kUnsupportedConfiguration;
  }

  if (!capabilities::supportsConfiguration(configuration.source,
                                           configuration.stream_mask)) {
    return protocol_v1::ErrorCode::kUnsupportedConfiguration;
  }
  return protocol_v1::ErrorCode::kOk;
}

bool ControlState::transitionTo(protocol_v1::DeviceState next) {
  if (!isLegalTransition(state_, next)) {
    return false;
  }
  state_ = next;
  return true;
}

DispatchResult ControlState::reject(const protocol::Request &request,
                                    protocol_v1::ErrorCode error,
                                    protocol::ControlFrame &response) {
  const protocol::Result encoding =
      protocol::encodeTypedErrorResponse(request, run_id_, error, response);
  if (encoding.ok()) {
    statistics_.recordCommandRejected(error);
    return {DispatchStatus::kResponseReady, error, encoding};
  }
  return encoded(request, protocol_v1::ErrorCode::kInternalError, encoding,
                 response);
}

DispatchResult ControlState::encoded(const protocol::Request &request,
                                     protocol_v1::ErrorCode command_error,
                                     protocol::Result encoding,
                                     protocol::ControlFrame &response) {
  (void)request;
  if (!encoding.ok()) {
    response.clear();
    statistics_.recordCommandRejected(
        protocol_v1::ErrorCode::kInternalError);
    return {DispatchStatus::kEncodingFailure,
            protocol_v1::ErrorCode::kInternalError, encoding};
  }
  if (command_error == protocol_v1::ErrorCode::kOk) {
    statistics_.recordCommandAccepted();
  } else {
    statistics_.recordCommandRejected(command_error);
  }
  return {DispatchStatus::kResponseReady, command_error, encoding};
}

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.info_response")
protocol::InfoResponse ControlState::infoResponse() const {
  protocol::InfoResponse response{};
  response.device_state = state_;
  response.supported_stream_mask =
      capabilities::kMetadata.supported_stream_mask;
  response.supported_source_mask =
      capabilities::kMetadata.supported_source_mask;
  response.supported_configuration_mask =
      capabilities::kMetadata.supported_configuration_mask;
  response.supported_checksum_mask =
      capabilities::kMetadata.supported_checksum_mask;
  response.capability_bits = capabilities::kMetadata.capability_bits;
  response.timestamp_hz = capabilities::kMetadata.timestamp_hz;
  response.data_frame_bytes = static_cast<std::uint32_t>(
      capabilities::kMetadata.data_frame_bytes);
  response.max_control_frame_bytes = static_cast<std::uint32_t>(
      capabilities::kMetadata.max_control_frame_bytes);
  response.adc_pair_rate_hz = capabilities::kMetadata.adc_pair_rate_hz;
  response.gpio_sample_rate_hz = capabilities::kMetadata.gpio_sample_rate_hz;
  response.adc_pair_period_ticks = static_cast<std::uint16_t>(
      capabilities::kMetadata.adc_pair_period_ticks);
  response.adc1_phase_ticks = static_cast<std::uint16_t>(
      capabilities::kMetadata.adc1_phase_ticks);
  response.gpio_sample_period_ticks = static_cast<std::uint16_t>(
      capabilities::kMetadata.gpio_sample_period_ticks);
  response.adc = adc_metadata_;
  response.data_checksum_algorithm =
      appliedConfiguration().data_checksum_algorithm;
  response.applied_configuration = appliedConfiguration();
  // V2 selects the historical ADC2 request route at acquisition preparation.
  response.adc_dmamux_sources[1] = protocol_v1::kAdcDmamuxSources[1];
  for (std::size_t index = 0U; index < response.gpio_pin_map.size(); ++index) {
    response.gpio_pin_map[index] =
        capabilities::kMetadata.gpio_pins_by_bit[index];
  }
  response.hardware_serial = hardware_serial_;
  response.firmware_version_major = identity::kFirmwareVersion.major;
  response.firmware_version_minor = identity::kFirmwareVersion.minor;
  response.firmware_version_patch = identity::kFirmwareVersion.patch;
  response.board_id = identity::kBoardId;
  response.mcu_id = identity::kMcuId;
  for (std::size_t index = 0U;
       index < identity::kBuildId.size() && index < response.build_id.size();
       ++index) {
    response.build_id[index] =
        static_cast<std::uint8_t>(identity::kBuildId[index]);
  }
  response.gpio_packed_width_bits = protocol_v1::kGpioPackedWidthBits;
  response.gpio_raw_ring_depth = protocol_v1::kGpioRawRingDepth;
  response.gpio_packed_ring_depth = protocol_v1::kGpioPackedRingDepth;
  response.gpio_capture_diagnostic_mode =
      protocol_v1::GpioCaptureDiagnosticMode::kNonDrivingCapture;
  response.gpio_capture_diagnostic_flags =
      capabilities::kGpioCaptureDiagnosticInfoFlags;
  response.gpio_raw_samples_per_buffer =
      protocol_v1::kGpioRawSamplesPerBuffer;
  response.gpio_raw_ring_bytes = protocol_v1::kGpioRawRingBytes;
  response.gpio_packed_ring_bytes = protocol_v1::kGpioPackedRingBytes;
  response.gpio_packet_buffer_count = protocol_v1::kGpioPacketBufferCount;
  response.gpio_pit_channel = protocol_v1::kGpioPitChannel;
  response.gpio_xbar_input = protocol_v1::kGpioXbarInput;
  response.gpio_xbar_output = protocol_v1::kGpioXbarOutput;
  response.gpio_edma_channel = protocol_v1::kGpioEdmaChannel;
  response.gpio_dmamux_source = protocol_v1::kGpioDmamuxSource;
  response.gpio_edma_priority = protocol_v1::kGpioEdmaPriority;
  response.gpio_xbar_active_edge = protocol_v1::kGpioXbarActiveEdge;
  return response;
}

#undef THINGDAQ_CONTROL_COLD_CODE

}  // namespace thingdaq::control
