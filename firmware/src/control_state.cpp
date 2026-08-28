#include "control_state.h"

#include <cstddef>

namespace teensy_daq::control {
namespace {

constexpr std::uint8_t kKnownStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);

constexpr bool knownSource(protocol_v1::Source source) {
  return source == protocol_v1::Source::kHardware ||
         source == protocol_v1::Source::kSynthetic;
}

constexpr bool knownDataChecksum(protocol_v1::ChecksumAlgorithm checksum) {
  return checksum == protocol_v1::ChecksumAlgorithm::kNoneReserved ||
         checksum == protocol_v1::ChecksumAlgorithm::kAdler32 ||
         checksum == protocol_v1::ChecksumAlgorithm::kCrc32c;
}

constexpr bool capabilityEnabled(protocol_v1::Capability capability) {
  return (capabilities::kCapabilityBits &
          capabilities::capabilityBit(capability)) != 0U;
}

}  // namespace

bool ControlState::completeBoot(std::uint32_t hardware_serial) {
  if (state_ != protocol_v1::DeviceState::kBoot) {
    return false;
  }
  hardware_serial_ = hardware_serial;
  return transitionTo(protocol_v1::DeviceState::kIdle);
}

DispatchResult ControlState::dispatch(const protocol::Request &request,
                                      protocol::ControlFrame &response) {
  response.clear();
  if (state_ == protocol_v1::DeviceState::kBoot) {
    return {DispatchStatus::kNoResponse,
            protocol_v1::ErrorCode::kInvalidState,
            protocol::Result::success()};
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
      const protocol::StatusResponse status =
          statistics_.wireStatus(state_, appliedConfiguration());
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
      configuration_ = kControlOnlyConfiguration;
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
  }

  statistics_.recordCommandRejected(
      protocol_v1::ErrorCode::kUnknownFrameKind);
  return {DispatchStatus::kEncodingFailure,
          protocol_v1::ErrorCode::kUnknownFrameKind,
          protocol::Result::failure(
              protocol_v1::ErrorCode::kUnknownFrameKind,
              protocol::ValidationIssue::kBadKind)};
}

PendingEvents ControlState::takePendingEvents() {
  PendingEvents events{};
  events.mask = pending_event_mask_;
  events.run_id = run_id_;
  events.stats_generation = statistics_.generation();
  pending_event_mask_ = 0U;
  return events;
}

protocol_v1::ErrorCode ControlState::validateConfiguration(
    const protocol::Configuration &configuration) {
  if ((configuration.stream_mask &
       static_cast<std::uint8_t>(~kKnownStreamMask)) != 0U ||
      !knownSource(configuration.source) ||
      !knownDataChecksum(configuration.data_checksum_algorithm) ||
      configuration.data_checksum_algorithm ==
          protocol_v1::ChecksumAlgorithm::kNoneReserved ||
      configuration.data_frame_bytes != protocol_v1::kDataFrameBytes) {
    return protocol_v1::ErrorCode::kInvalidPayload;
  }

  const std::uint8_t checksum_id = static_cast<std::uint8_t>(
      configuration.data_checksum_algorithm);
  if ((capabilities::kMetadata.supported_checksum_mask &
       (1UL << checksum_id)) == 0U) {
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

  return configuration.stream_mask == kControlOnlyConfiguration.stream_mask &&
                 configuration.source == kControlOnlyConfiguration.source &&
                 configuration.data_checksum_algorithm ==
                     kControlOnlyConfiguration.data_checksum_algorithm &&
                 configuration.data_frame_bytes ==
                     kControlOnlyConfiguration.data_frame_bytes
             ? protocol_v1::ErrorCode::kOk
             : protocol_v1::ErrorCode::kUnsupportedConfiguration;
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

protocol::InfoResponse ControlState::infoResponse() const {
  protocol::InfoResponse response{};
  response.device_state = state_;
  response.supported_stream_mask =
      capabilities::kMetadata.supported_stream_mask;
  response.supported_source_mask =
      capabilities::kMetadata.supported_source_mask;
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
  response.adc_resolution_bits = capabilities::kMetadata.adc_resolution_bits;
  response.adc_container_bytes = capabilities::kMetadata.adc_container_bytes;
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
  return response;
}

}  // namespace teensy_daq::control
