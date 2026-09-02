#include "control_state.h"

#include <cstddef>

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

constexpr bool knownSource(protocol_v1::Source source,
                           std::uint8_t protocol_version) {
  return source == protocol_v1::Source::kHardware ||
         source == protocol_v1::Source::kSynthetic ||
         (protocol_version == protocol_v2::kProtocolVersion &&
          capabilities::isExperimentalSyntheticSource(source));
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
  if (has_configuration_ &&
      configuration_.protocol_version == protocol_v2::kProtocolVersion) {
    (void)recoverToIdle();
  }
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
      if (!readiness.configuration_ready) {
        return reject(request, protocol_v1::ErrorCode::kBusy, response);
      }
      const protocol_v1::ErrorCode validation =
          validateConfiguration(request.configuration);
      if (validation != protocol_v1::ErrorCode::kOk) {
        return reject(request, validation, response);
      }
      const protocol::Result encoding = protocol::encodeConfigureResponse(
          request, run_id_, request.configuration, response);
      if (!encoding.ok()) {
        return encoded(request, protocol_v1::ErrorCode::kInternalError,
                       encoding, response);
      }
      if (!transitionTo(protocol_v1::DeviceState::kConfigured)) {
        response.clear();
        return encoded(
            request, protocol_v1::ErrorCode::kInternalError,
            protocol::Result::failure(protocol_v1::ErrorCode::kInternalError,
                                      protocol::ValidationIssue::kBadPayload),
            response);
      }
      configuration_ = request.configuration;
      has_configuration_ = true;
      statistics_.recordCommandAccepted();
      return {DispatchStatus::kResponseReady, protocol_v1::ErrorCode::kOk,
              encoding};
    }

    case protocol_v1::CommandKind::kStart: {
      if (state_ != protocol_v1::DeviceState::kConfigured ||
          !has_configuration_) {
        return reject(request, protocol_v1::ErrorCode::kInvalidState,
                      response);
      }
      if (!readiness.start_ready) {
        return reject(request, protocol_v1::ErrorCode::kBusy, response);
      }
      if (request.protocol_version != configuration_.protocol_version) {
        return reject(request,
                      protocol_v1::ErrorCode::kUnsupportedConfiguration,
                      response);
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

THINGDAQ_CONTROL_COLD_CODE(".flashmem.control.configuration_validation")
protocol_v1::ErrorCode ControlState::validateConfiguration(
    const protocol::Configuration &configuration) {
  const bool raw = configuration.encoding ==
                   protocol_v2::ConfigurationEncoding::kRaw;
  const bool rle_auto = configuration.encoding ==
                        protocol_v2::ConfigurationEncoding::kRleAuto;
  if ((configuration.stream_mask &
       static_cast<std::uint8_t>(~kKnownStreamMask)) != 0U ||
      !knownSource(configuration.source, configuration.protocol_version) ||
      configuration.data_checksum_algorithm ==
          protocol_v1::ChecksumAlgorithm::kNoneReserved ||
      configuration.data_frame_bytes != protocol_v1::kDataFrameBytes ||
      (configuration.protocol_version != protocol_v1::kProtocolVersion &&
       configuration.protocol_version != protocol_v2::kProtocolVersion) ||
      (!raw && !rle_auto) ||
      (configuration.protocol_version == protocol_v1::kProtocolVersion &&
       !raw)) {
    return protocol_v1::ErrorCode::kInvalidPayload;
  }

  if (!protocol::isSupportedChecksum(
          configuration.data_checksum_algorithm)) {
    return protocol_v1::ErrorCode::kUnsupportedChecksum;
  }

  const std::uint8_t source_id =
      static_cast<std::uint8_t>(configuration.source);
  if ((configuration.stream_mask &
       static_cast<std::uint8_t>(~capabilities::kSupportedStreamMask)) != 0U ||
      ((configuration.protocol_version == protocol_v2::kProtocolVersion
            ? capabilities::kV2SupportedSourceMask
            : capabilities::kSupportedSourceMask) &
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
