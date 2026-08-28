#include "protocol.h"

#include <limits>

namespace teensy_daq::protocol {
namespace {

constexpr std::size_t kNotFound = static_cast<std::size_t>(-1);
constexpr std::uint8_t kValidStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
constexpr std::uint16_t kResponseErrorFlag =
    static_cast<std::uint16_t>(protocol_v1::FrameFlag::kResponseError);

constexpr Result badMagic() {
  return Result::failure(protocol_v1::ErrorCode::kInvalidLength,
                         ValidationIssue::kBadMagic);
}

constexpr Result badVersion() {
  return Result::failure(protocol_v1::ErrorCode::kUnsupportedVersion,
                         ValidationIssue::kBadVersion);
}

constexpr Result badKind() {
  return Result::failure(protocol_v1::ErrorCode::kUnknownFrameKind,
                         ValidationIssue::kBadKind);
}

constexpr Result badFlags() {
  return Result::failure(protocol_v1::ErrorCode::kInvalidFlags,
                         ValidationIssue::kBadFlags);
}

constexpr Result badLength() {
  return Result::failure(protocol_v1::ErrorCode::kInvalidLength,
                         ValidationIssue::kBadLength);
}

constexpr Result badChecksum() {
  return Result::failure(protocol_v1::ErrorCode::kChecksumMismatch,
                         ValidationIssue::kBadChecksum);
}

constexpr Result badPayload() {
  return Result::failure(protocol_v1::ErrorCode::kInvalidPayload,
                         ValidationIssue::kBadPayload);
}

constexpr Result badRequestId() {
  return Result::failure(protocol_v1::ErrorCode::kInvalidRequestId,
                         ValidationIssue::kBadRequestId);
}

constexpr Result unsupportedChecksum() {
  return Result::failure(protocol_v1::ErrorCode::kUnsupportedChecksum,
                         ValidationIssue::kUnsupportedChecksum);
}

constexpr bool hasRange(std::size_t size, std::size_t offset,
                        std::size_t width) {
  return offset <= size && width <= size - offset;
}

constexpr std::uint8_t magicByte(std::size_t index) {
  return static_cast<std::uint8_t>((protocol_v1::kMagic >> (index * 8U)) &
                                   0xFFU);
}

constexpr bool isKnownKind(protocol_v1::FrameKind kind) {
  switch (kind) {
    case protocol_v1::FrameKind::kAdcData:
    case protocol_v1::FrameKind::kGpioData:
    case protocol_v1::FrameKind::kInfoRequest:
    case protocol_v1::FrameKind::kConfigureRequest:
    case protocol_v1::FrameKind::kStartRequest:
    case protocol_v1::FrameKind::kGetStatusRequest:
    case protocol_v1::FrameKind::kStopRequest:
    case protocol_v1::FrameKind::kResetStatsRequest:
    case protocol_v1::FrameKind::kPingRequest:
    case protocol_v1::FrameKind::kInfoResponse:
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
    case protocol_v1::FrameKind::kGetStatusResponse:
    case protocol_v1::FrameKind::kStopResponse:
    case protocol_v1::FrameKind::kResetStatsResponse:
    case protocol_v1::FrameKind::kPingResponse:
    case protocol_v1::FrameKind::kErrorResponse:
      return true;
  }
  return false;
}

constexpr bool isRequestKind(protocol_v1::FrameKind kind) {
  switch (kind) {
    case protocol_v1::FrameKind::kInfoRequest:
    case protocol_v1::FrameKind::kConfigureRequest:
    case protocol_v1::FrameKind::kStartRequest:
    case protocol_v1::FrameKind::kGetStatusRequest:
    case protocol_v1::FrameKind::kStopRequest:
    case protocol_v1::FrameKind::kResetStatsRequest:
    case protocol_v1::FrameKind::kPingRequest:
      return true;
    default:
      return false;
  }
}

constexpr bool isDataKind(protocol_v1::FrameKind kind) {
  return kind == protocol_v1::FrameKind::kAdcData ||
         kind == protocol_v1::FrameKind::kGpioData;
}

constexpr bool isTypedResponseKind(protocol_v1::FrameKind kind) {
  switch (kind) {
    case protocol_v1::FrameKind::kInfoResponse:
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
    case protocol_v1::FrameKind::kGetStatusResponse:
    case protocol_v1::FrameKind::kStopResponse:
    case protocol_v1::FrameKind::kResetStatsResponse:
    case protocol_v1::FrameKind::kPingResponse:
      return true;
    default:
      return false;
  }
}

constexpr bool isKnownError(protocol_v1::ErrorCode error) {
  return static_cast<std::uint16_t>(error) <=
         static_cast<std::uint16_t>(
             protocol_v1::ErrorCode::kChecksumMismatch);
}

constexpr bool isKnownState(std::uint8_t state) {
  return state <=
         static_cast<std::uint8_t>(protocol_v1::DeviceState::kRunning);
}

constexpr bool isKnownSource(std::uint8_t source) {
  return source <= static_cast<std::uint8_t>(protocol_v1::Source::kSynthetic);
}

constexpr bool isKnownBoard(std::uint16_t board) {
  return board <= static_cast<std::uint16_t>(protocol_v1::BoardId::kTeensy40);
}

constexpr bool isKnownMcu(std::uint16_t mcu) {
  return mcu <= static_cast<std::uint16_t>(protocol_v1::McuId::kImxrt1062);
}

bool decodeKind(std::uint8_t raw, protocol_v1::FrameKind &kind) {
  const auto candidate = static_cast<protocol_v1::FrameKind>(raw);
  if (!isKnownKind(candidate)) {
    return false;
  }
  kind = candidate;
  return true;
}

bool commandForKind(protocol_v1::FrameKind kind,
                    protocol_v1::CommandKind &command) {
  switch (kind) {
    case protocol_v1::FrameKind::kInfoRequest:
      command = protocol_v1::CommandKind::kInfo;
      return true;
    case protocol_v1::FrameKind::kConfigureRequest:
      command = protocol_v1::CommandKind::kConfigure;
      return true;
    case protocol_v1::FrameKind::kStartRequest:
      command = protocol_v1::CommandKind::kStart;
      return true;
    case protocol_v1::FrameKind::kGetStatusRequest:
      command = protocol_v1::CommandKind::kGetStatus;
      return true;
    case protocol_v1::FrameKind::kStopRequest:
      command = protocol_v1::CommandKind::kStop;
      return true;
    case protocol_v1::FrameKind::kResetStatsRequest:
      command = protocol_v1::CommandKind::kResetStats;
      return true;
    case protocol_v1::FrameKind::kPingRequest:
      command = protocol_v1::CommandKind::kPing;
      return true;
    default:
      return false;
  }
}

bool expectedPayloadSize(protocol_v1::FrameKind kind, bool response_error,
                         std::size_t &size) {
  if (response_error && isTypedResponseKind(kind)) {
    size = protocol_v1::kResponsePrefixPayloadSize;
    return true;
  }
  switch (kind) {
    case protocol_v1::FrameKind::kAdcData:
      size = protocol_v1::kAdcDataPayloadSize;
      return true;
    case protocol_v1::FrameKind::kGpioData:
      size = protocol_v1::kGpioDataPayloadSize;
      return true;
    case protocol_v1::FrameKind::kInfoRequest:
    case protocol_v1::FrameKind::kStartRequest:
    case protocol_v1::FrameKind::kGetStatusRequest:
    case protocol_v1::FrameKind::kStopRequest:
    case protocol_v1::FrameKind::kResetStatsRequest:
      size = protocol_v1::kEmptyPayloadSize;
      return true;
    case protocol_v1::FrameKind::kConfigureRequest:
      size = protocol_v1::kConfigureRequestPayloadSize;
      return true;
    case protocol_v1::FrameKind::kPingRequest:
      size = protocol_v1::kPingRequestPayloadSize;
      return true;
    case protocol_v1::FrameKind::kInfoResponse:
      size = protocol_v1::kInfoResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
      size = protocol_v1::kConfigureResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kGetStatusResponse:
      size = protocol_v1::kStatusResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kStopResponse:
      size = protocol_v1::kStopResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kResetStatsResponse:
      size = protocol_v1::kResetStatsResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kPingResponse:
      size = protocol_v1::kPingResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kErrorResponse:
      size = protocol_v1::kErrorResponsePayloadSize;
      return response_error;
  }
  return false;
}

Result validateHeader(const FrameHeader &header, bool commands_only) {
  if (header.version != protocol_v1::kProtocolVersion) {
    return badVersion();
  }
  if (!isKnownKind(header.kind) ||
      (commands_only && !isRequestKind(header.kind))) {
    return badKind();
  }
  if (header.header_length != protocol_v1::kHeaderSize) {
    return badLength();
  }
  if (header.checksum_algorithm !=
      protocol_v1::ChecksumAlgorithm::kAdler32) {
    return unsupportedChecksum();
  }
  const std::uint16_t allowed = protocol_v1::allowedFlags(header.kind);
  if ((header.flags & static_cast<std::uint16_t>(~allowed)) != 0U) {
    return badFlags();
  }
  const std::uint16_t overrun =
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kOverrunBefore);
  const std::uint16_t gap =
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kGapBefore);
  if ((header.flags & overrun) != 0U && (header.flags & gap) == 0U) {
    return badFlags();
  }

  const bool response_error = (header.flags & kResponseErrorFlag) != 0U;
  std::size_t expected_payload = 0U;
  if (!expectedPayloadSize(header.kind, response_error, expected_payload) ||
      header.payload_length != expected_payload) {
    return badLength();
  }
  if (header.payload_length > protocol_v1::kMaxDataFrameBytes) {
    return badLength();
  }
  const std::uint32_t framing_bytes = static_cast<std::uint32_t>(
      protocol_v1::kHeaderSize + protocol_v1::kTrailerSize);
  if (header.payload_length >
          std::numeric_limits<std::uint32_t>::max() - framing_bytes ||
      header.total_length != framing_bytes + header.payload_length) {
    return badLength();
  }

  if (isDataKind(header.kind)) {
    const std::uint32_t expected_items =
        header.kind == protocol_v1::FrameKind::kAdcData
            ? static_cast<std::uint32_t>(protocol_v1::kAdcPairsPerFrame)
            : static_cast<std::uint32_t>(protocol_v1::kGpioSamplesPerFrame);
    const std::uint32_t period =
        header.kind == protocol_v1::FrameKind::kAdcData
            ? protocol_v1::kAdcPairPeriodTicks
            : protocol_v1::kGpioSamplePeriodTicks;
    if (header.total_length != protocol_v1::kDataFrameBytes ||
        header.payload_length != protocol_v1::kDataPayloadBytes ||
        header.item_count != expected_items) {
      return badLength();
    }
    if (header.run_id == 0U || header.request_id != 0U ||
        header.first_sample_ticks % period != 0U) {
      return badPayload();
    }
    const bool epoch_start =
        (header.flags & static_cast<std::uint16_t>(
                            protocol_v1::FrameFlag::kEpochStart)) != 0U;
    const bool first_item =
        header.sequence == 0U && header.first_sample_ticks == 0U;
    return epoch_start == first_item ? Result::success() : badPayload();
  }

  if (header.total_length < protocol_v1::kMinFrameBytes ||
      header.total_length > protocol_v1::kMaxControlFrameBytes) {
    return badLength();
  }
  if (header.request_id == 0U) {
    return badRequestId();
  }
  if (header.sequence != 0U || header.first_sample_ticks != 0U ||
      header.item_count != 0U) {
    return badPayload();
  }
  if (isRequestKind(header.kind)) {
    if (header.run_id != 0U) {
      return badPayload();
    }
    if (header.total_length > protocol_v1::kMaxCommandFrameBytes) {
      return badLength();
    }
  }
  if (header.kind == protocol_v1::FrameKind::kStartResponse &&
      !response_error && header.run_id == 0U) {
    return badPayload();
  }
  return Result::success();
}

Result decodeHeader(ByteView input, FrameHeader &header, bool commands_only) {
  if (!input.valid() || input.size < protocol_v1::kHeaderSize) {
    return badLength();
  }
  std::uint32_t magic = 0U;
  if (!loadU32(input, protocol_v1::kHeaderMagicOffset, magic) ||
      magic != protocol_v1::kMagic) {
    return badMagic();
  }
  const std::uint8_t version = input.data[protocol_v1::kHeaderVersionOffset];
  if (version != protocol_v1::kProtocolVersion) {
    return badVersion();
  }
  protocol_v1::FrameKind kind{};
  if (!decodeKind(input.data[protocol_v1::kHeaderKindOffset], kind) ||
      (commands_only && !isRequestKind(kind))) {
    return badKind();
  }
  const std::uint8_t raw_checksum =
      input.data[protocol_v1::kHeaderChecksumAlgorithmOffset];
  if (raw_checksum != static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kAdler32)) {
    return unsupportedChecksum();
  }
  if (input.data[protocol_v1::kHeaderReservedOffset] != 0U) {
    return badPayload();
  }

  FrameHeader candidate{};
  candidate.kind = kind;
  candidate.version = version;
  candidate.checksum_algorithm = protocol_v1::ChecksumAlgorithm::kAdler32;
  if (!loadU16(input, protocol_v1::kHeaderFlagsOffset, candidate.flags) ||
      !loadU16(input, protocol_v1::kHeaderHeaderLengthOffset,
               candidate.header_length) ||
      !loadU32(input, protocol_v1::kHeaderTotalLengthOffset,
               candidate.total_length) ||
      !loadU32(input, protocol_v1::kHeaderPayloadLengthOffset,
               candidate.payload_length) ||
      !loadU32(input, protocol_v1::kHeaderRunIdOffset, candidate.run_id) ||
      !loadU32(input, protocol_v1::kHeaderSequenceOffset,
               candidate.sequence) ||
      !loadU32(input, protocol_v1::kHeaderRequestIdOffset,
               candidate.request_id) ||
      !loadU64(input, protocol_v1::kHeaderFirstSampleTicksOffset,
               candidate.first_sample_ticks) ||
      !loadU32(input, protocol_v1::kHeaderItemCountOffset,
               candidate.item_count)) {
    return badLength();
  }
  const Result result = validateHeader(candidate, commands_only);
  if (result.ok()) {
    header = candidate;
  }
  return result;
}

Result validateConfiguration(ByteView payload, std::size_t offset,
                             bool applied) {
  if (!hasRange(payload.size, offset, protocol_v1::kConfigureRequestPayloadSize)) {
    return badLength();
  }
  const std::uint8_t streams = payload.data[offset];
  const std::uint8_t source = payload.data[offset + 1U];
  const std::uint8_t checksum = payload.data[offset + 2U];
  if ((streams & static_cast<std::uint8_t>(~kValidStreamMask)) != 0U ||
      !isKnownSource(source) || payload.data[offset + 3U] != 0U) {
    return badPayload();
  }
  if (checksum == static_cast<std::uint8_t>(
                      protocol_v1::ChecksumAlgorithm::kNoneReserved) ||
      checksum >
          static_cast<std::uint8_t>(protocol_v1::ChecksumAlgorithm::kCrc32c)) {
    return badPayload();
  }
  if (applied && checksum != static_cast<std::uint8_t>(
                                protocol_v1::ChecksumAlgorithm::kAdler32)) {
    return unsupportedChecksum();
  }
  std::uint32_t frame_bytes = 0U;
  if (!loadU32(payload, offset + 4U, frame_bytes) ||
      frame_bytes != protocol_v1::kDataFrameBytes) {
    return badPayload();
  }
  return Result::success();
}

Result validateResponsePrefix(const FrameHeader &header, ByteView payload) {
  if (payload.size < protocol_v1::kResponsePrefixPayloadSize) {
    return badLength();
  }
  const std::uint8_t raw_status =
      payload.data[protocol_v1::kResponsePrefixResponseStatusOffset];
  if (payload.data[protocol_v1::kResponsePrefixReservedOffset] != 0U ||
      raw_status >
          static_cast<std::uint8_t>(protocol_v1::ResponseStatus::kError)) {
    return badPayload();
  }
  std::uint16_t raw_error = 0U;
  if (!loadU16(payload, protocol_v1::kResponsePrefixErrorCodeOffset,
               raw_error)) {
    return badLength();
  }
  const auto error = static_cast<protocol_v1::ErrorCode>(raw_error);
  if (!isKnownError(error)) {
    return badPayload();
  }
  const bool response_error = (header.flags & kResponseErrorFlag) != 0U;
  const bool error_status =
      raw_status == static_cast<std::uint8_t>(protocol_v1::ResponseStatus::kError);
  const bool ok_error = error == protocol_v1::ErrorCode::kOk;
  if (response_error != error_status || ok_error == error_status) {
    return badPayload();
  }
  return Result::success();
}

Result validateInfo(ByteView payload) {
  if (payload.data[protocol_v1::kInfoResponseReserved0Offset] != 0U ||
      payload.data[protocol_v1::kInfoResponseReserved1Offset] != 0U ||
      payload.data[protocol_v1::kInfoResponseReserved2Offset] != 0U ||
      !isKnownState(payload.data[protocol_v1::kInfoResponseDeviceStateOffset]) ||
      payload.data[protocol_v1::kInfoResponseDeviceStateOffset] ==
          static_cast<std::uint8_t>(protocol_v1::DeviceState::kBoot) ||
      payload.data[protocol_v1::kInfoResponseProtocolVersionOffset] !=
          protocol_v1::kProtocolVersion ||
      payload.data[protocol_v1::kInfoResponseSupportedStreamMaskOffset] &
          static_cast<std::uint8_t>(~kValidStreamMask) ||
      payload.data[protocol_v1::kInfoResponseSupportedSourceMaskOffset] == 0U ||
      payload.data[protocol_v1::kInfoResponseSupportedSourceMaskOffset] & 0xFCU ||
      payload.data[protocol_v1::kInfoResponseAdcResolutionBitsOffset] !=
          protocol_v1::kAdcResolutionBits ||
      payload.data[protocol_v1::kInfoResponseAdcContainerBytesOffset] !=
          protocol_v1::kAdcContainerBits / 8U ||
      payload.data[protocol_v1::kInfoResponseGpioPinCountOffset] !=
          protocol_v1::kInfoResponseGpioPinMapCount) {
    return badPayload();
  }

  std::uint32_t value32 = 0U;
  const std::size_t offsets[] = {
      protocol_v1::kInfoResponseSupportedChecksumMaskOffset,
      protocol_v1::kInfoResponseTimestampHzOffset,
      protocol_v1::kInfoResponseDataFrameBytesOffset,
      protocol_v1::kInfoResponseMaxControlFrameBytesOffset,
      protocol_v1::kInfoResponseAdcPairRateHzOffset,
      protocol_v1::kInfoResponseGpioSampleRateHzOffset,
  };
  const std::uint32_t expected[] = {
      protocol_v1::kSupportedChecksumMask,
      protocol_v1::kTimestampHz,
      static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes),
      static_cast<std::uint32_t>(protocol_v1::kMaxControlFrameBytes),
      protocol_v1::kAdcPairRateHz,
      protocol_v1::kGpioSampleRateHz,
  };
  for (std::size_t index = 0U; index < sizeof(offsets) / sizeof(offsets[0]);
       ++index) {
    if (!loadU32(payload, offsets[index], value32) ||
        value32 != expected[index]) {
      return badPayload();
    }
  }
  if (!loadU32(payload, protocol_v1::kInfoResponseCapabilityBitsOffset,
               value32) ||
      (value32 & ~protocol_v1::kKnownCapabilityMask) != 0U) {
    return badPayload();
  }

  std::uint16_t value16 = 0U;
  if (!loadU16(payload, protocol_v1::kInfoResponseAdcPairPeriodTicksOffset,
               value16) ||
      value16 != protocol_v1::kAdcPairPeriodTicks ||
      !loadU16(payload, protocol_v1::kInfoResponseAdc1PhaseTicksOffset,
               value16) ||
      value16 != protocol_v1::kAdc1PhaseTicks ||
      !loadU16(payload, protocol_v1::kInfoResponseGpioSamplePeriodTicksOffset,
               value16) ||
      value16 != protocol_v1::kGpioSamplePeriodTicks) {
    return badPayload();
  }
  for (std::size_t index = 0U;
       index < protocol_v1::kInfoResponseGpioPinMapCount; ++index) {
    if (payload.data[protocol_v1::kInfoResponseGpioPinMapOffset + index] !=
        protocol_v1::kGpioPinsByBit[index]) {
      return badPayload();
    }
  }
  if (!loadU16(payload, protocol_v1::kInfoResponseBoardIdOffset, value16) ||
      !isKnownBoard(value16) ||
      !loadU16(payload, protocol_v1::kInfoResponseMcuIdOffset, value16) ||
      !isKnownMcu(value16)) {
    return badPayload();
  }

  bool terminated = false;
  for (std::size_t index = 0U; index < protocol_v1::kInfoResponseBuildIdCount;
       ++index) {
    const std::uint8_t value =
        payload.data[protocol_v1::kInfoResponseBuildIdOffset + index];
    if (terminated && value != 0U) {
      return badPayload();
    }
    if (!terminated && value == 0U) {
      terminated = true;
    } else if (!terminated && value > 0x7FU) {
      return badPayload();
    }
  }
  return terminated ? Result::success() : badPayload();
}

Result validateStatus(ByteView payload) {
  if (payload.data[protocol_v1::kStatusResponseReservedOffset] != 0U) {
    return badPayload();
  }
  const std::uint8_t state =
      payload.data[protocol_v1::kStatusResponseDeviceStateOffset];
  const std::uint8_t streams =
      payload.data[protocol_v1::kStatusResponseStreamMaskOffset];
  const std::uint8_t source =
      payload.data[protocol_v1::kStatusResponseSourceOffset];
  const std::uint8_t checksum =
      payload.data[protocol_v1::kStatusResponseDataChecksumAlgorithmOffset];
  if (!isKnownState(state) ||
      state == static_cast<std::uint8_t>(protocol_v1::DeviceState::kBoot) ||
      (streams & static_cast<std::uint8_t>(~kValidStreamMask)) != 0U ||
      (state == static_cast<std::uint8_t>(protocol_v1::DeviceState::kIdle) &&
       streams != 0U) ||
      !isKnownSource(source) ||
      checksum != static_cast<std::uint8_t>(
                      protocol_v1::ChecksumAlgorithm::kAdler32)) {
    return badPayload();
  }
  std::uint32_t value = 0U;
  if (!loadU32(payload, protocol_v1::kStatusResponseDataFrameBytesOffset,
               value) ||
      value != protocol_v1::kDataFrameBytes ||
      !loadU32(payload, protocol_v1::kStatusResponseStatsGenerationOffset,
               value) ||
      value == 0U) {
    return badPayload();
  }
  return Result::success();
}

Result validatePayload(const FrameHeader &header, ByteView payload) {
  if (!payload.valid() || payload.size != header.payload_length) {
    return badLength();
  }
  if (header.kind == protocol_v1::FrameKind::kAdcData) {
    for (std::size_t offset = 0U; offset < payload.size; offset += 2U) {
      std::uint16_t sample = 0U;
      if (!loadU16(payload, offset, sample) ||
          sample >= (1U << protocol_v1::kAdcResolutionBits)) {
        return badPayload();
      }
    }
    return Result::success();
  }
  if (header.kind == protocol_v1::FrameKind::kGpioData) {
    return Result::success();
  }
  if (header.kind == protocol_v1::FrameKind::kConfigureRequest) {
    return validateConfiguration(payload, 0U, false);
  }
  if (isRequestKind(header.kind)) {
    return Result::success();
  }

  const Result prefix = validateResponsePrefix(header, payload);
  if (!prefix.ok()) {
    return prefix;
  }
  if ((header.flags & kResponseErrorFlag) != 0U) {
    if (header.kind == protocol_v1::FrameKind::kErrorResponse) {
      std::uint16_t reserved = 1U;
      if (!loadU16(payload, protocol_v1::kErrorResponseReserved1Offset,
                   reserved) ||
          reserved != 0U) {
        return badPayload();
      }
    }
    return Result::success();
  }

  switch (header.kind) {
    case protocol_v1::FrameKind::kInfoResponse:
      return validateInfo(payload);
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
      return validateConfiguration(payload, 4U, true);
    case protocol_v1::FrameKind::kGetStatusResponse:
      return validateStatus(payload);
    case protocol_v1::FrameKind::kStopResponse: {
      std::uint16_t reserved = 1U;
      return payload.data[protocol_v1::kStopResponseDeviceStateOffset] ==
                     static_cast<std::uint8_t>(
                         protocol_v1::DeviceState::kIdle) &&
                 payload.data[protocol_v1::kStopResponseReserved1Offset] == 0U &&
                 loadU16(payload, protocol_v1::kStopResponseReserved2Offset,
                         reserved) &&
                 reserved == 0U
             ? Result::success()
             : badPayload();
    }
    case protocol_v1::FrameKind::kResetStatsResponse: {
      std::uint32_t generation = 0U;
      return payload.data[protocol_v1::kResetStatsResponseReservedOffset] ==
                         0U &&
                     loadU32(
                         payload,
                         protocol_v1::kResetStatsResponseStatsGenerationOffset,
                         generation) &&
                     generation != 0U
                 ? Result::success()
                 : badPayload();
    }
    case protocol_v1::FrameKind::kPingResponse:
      return payload.data[protocol_v1::kPingResponseReservedOffset] == 0U
                 ? Result::success()
                 : badPayload();
    default:
      return badPayload();
  }
}

Result verifyRequestKind(const Request &request,
                         protocol_v1::CommandKind expected) {
  if (request.kind != expected) {
    return badPayload();
  }
  return request.request_id == 0U ? badRequestId() : Result::success();
}

FrameFields responseFields(protocol_v1::FrameKind kind, const Request &request,
                           std::uint32_t run_id, std::uint16_t flags = 0U) {
  FrameFields fields{};
  fields.kind = kind;
  fields.flags = flags;
  fields.run_id = run_id;
  fields.request_id = request.request_id;
  return fields;
}

bool writeHeader(const FrameHeader &header, MutableByteView output) {
  if (!output.valid() || output.size < protocol_v1::kHeaderSize) {
    return false;
  }
  for (std::size_t index = 0U; index < protocol_v1::kHeaderSize; ++index) {
    output.data[index] = 0U;
  }
  output.data[protocol_v1::kHeaderVersionOffset] = header.version;
  output.data[protocol_v1::kHeaderKindOffset] =
      static_cast<std::uint8_t>(header.kind);
  output.data[protocol_v1::kHeaderChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(header.checksum_algorithm);
  return storeU32(output, protocol_v1::kHeaderMagicOffset,
                  protocol_v1::kMagic) &&
         storeU16(output, protocol_v1::kHeaderFlagsOffset, header.flags) &&
         storeU16(output, protocol_v1::kHeaderHeaderLengthOffset,
                  header.header_length) &&
         storeU32(output, protocol_v1::kHeaderTotalLengthOffset,
                  header.total_length) &&
         storeU32(output, protocol_v1::kHeaderPayloadLengthOffset,
                  header.payload_length) &&
         storeU32(output, protocol_v1::kHeaderRunIdOffset, header.run_id) &&
         storeU32(output, protocol_v1::kHeaderSequenceOffset,
                  header.sequence) &&
         storeU32(output, protocol_v1::kHeaderRequestIdOffset,
                  header.request_id) &&
         storeU64(output, protocol_v1::kHeaderFirstSampleTicksOffset,
                  header.first_sample_ticks) &&
         storeU32(output, protocol_v1::kHeaderItemCountOffset,
                  header.item_count);
}

void writeSuccessPrefix(MutableByteView payload) {
  payload.data[protocol_v1::kResponsePrefixResponseStatusOffset] =
      static_cast<std::uint8_t>(protocol_v1::ResponseStatus::kOk);
  storeU16(payload, protocol_v1::kResponsePrefixErrorCodeOffset,
           static_cast<std::uint16_t>(protocol_v1::ErrorCode::kOk));
}

void writeErrorPrefix(MutableByteView payload, protocol_v1::ErrorCode error) {
  payload.data[protocol_v1::kResponsePrefixResponseStatusOffset] =
      static_cast<std::uint8_t>(protocol_v1::ResponseStatus::kError);
  storeU16(payload, protocol_v1::kResponsePrefixErrorCodeOffset,
           static_cast<std::uint16_t>(error));
}

void writeConfiguration(MutableByteView payload, std::size_t offset,
                        const Configuration &configuration) {
  payload.data[offset] = configuration.stream_mask;
  payload.data[offset + 1U] =
      static_cast<std::uint8_t>(configuration.source);
  payload.data[offset + 2U] =
      static_cast<std::uint8_t>(configuration.data_checksum_algorithm);
  storeU32(payload, offset + 4U, configuration.data_frame_bytes);
}

template <std::size_t Size>
ByteView view(const std::array<std::uint8_t, Size> &value) {
  return {value.data(), value.size()};
}

template <std::size_t Size>
MutableByteView mutableView(std::array<std::uint8_t, Size> &value) {
  return {value.data(), value.size()};
}

void saturatingIncrement(std::uint32_t &value) {
  if (value != std::numeric_limits<std::uint32_t>::max()) {
    ++value;
  }
}

void saturatingIncrement(std::uint64_t &value) {
  if (value != std::numeric_limits<std::uint64_t>::max()) {
    ++value;
  }
}

}  // namespace

bool loadU16(ByteView input, std::size_t offset, std::uint16_t &value) {
  if (!input.valid() || !hasRange(input.size, offset, sizeof(value))) {
    return false;
  }
  value = static_cast<std::uint16_t>(input.data[offset]) |
          static_cast<std::uint16_t>(
              static_cast<std::uint16_t>(input.data[offset + 1U]) << 8U);
  return true;
}

bool loadU32(ByteView input, std::size_t offset, std::uint32_t &value) {
  if (!input.valid() || !hasRange(input.size, offset, sizeof(value))) {
    return false;
  }
  value = 0U;
  for (std::size_t index = 0U; index < sizeof(value); ++index) {
    value |= static_cast<std::uint32_t>(input.data[offset + index])
             << (index * 8U);
  }
  return true;
}

bool loadU64(ByteView input, std::size_t offset, std::uint64_t &value) {
  if (!input.valid() || !hasRange(input.size, offset, sizeof(value))) {
    return false;
  }
  value = 0U;
  for (std::size_t index = 0U; index < sizeof(value); ++index) {
    value |= static_cast<std::uint64_t>(input.data[offset + index])
             << (index * 8U);
  }
  return true;
}

bool storeU16(MutableByteView output, std::size_t offset,
              std::uint16_t value) {
  if (!output.valid() || !hasRange(output.size, offset, sizeof(value))) {
    return false;
  }
  for (std::size_t index = 0U; index < sizeof(value); ++index) {
    output.data[offset + index] =
        static_cast<std::uint8_t>((value >> (index * 8U)) & 0xFFU);
  }
  return true;
}

bool storeU32(MutableByteView output, std::size_t offset,
              std::uint32_t value) {
  if (!output.valid() || !hasRange(output.size, offset, sizeof(value))) {
    return false;
  }
  for (std::size_t index = 0U; index < sizeof(value); ++index) {
    output.data[offset + index] =
        static_cast<std::uint8_t>((value >> (index * 8U)) & 0xFFU);
  }
  return true;
}

bool storeU64(MutableByteView output, std::size_t offset,
              std::uint64_t value) {
  if (!output.valid() || !hasRange(output.size, offset, sizeof(value))) {
    return false;
  }
  for (std::size_t index = 0U; index < sizeof(value); ++index) {
    output.data[offset + index] =
        static_cast<std::uint8_t>((value >> (index * 8U)) & 0xFFU);
  }
  return true;
}

std::uint32_t adler32(ByteView input) {
  if (!input.valid()) {
    return 0U;
  }
  constexpr std::uint32_t modulus = 65521U;
  std::uint32_t first = 1U;
  std::uint32_t second = 0U;
  for (std::size_t index = 0U; index < input.size; ++index) {
    first = (first + input.data[index]) % modulus;
    second = (second + first) % modulus;
  }
  return (second << 16U) | first;
}

Result computeChecksum(protocol_v1::ChecksumAlgorithm algorithm, ByteView input,
                       std::uint32_t &checksum) {
  if (!input.valid()) {
    return badLength();
  }
  switch (algorithm) {
    case protocol_v1::ChecksumAlgorithm::kAdler32:
      checksum = adler32(input);
      return Result::success();
    case protocol_v1::ChecksumAlgorithm::kNoneReserved:
    case protocol_v1::ChecksumAlgorithm::kCrc32c:
      return unsupportedChecksum();
  }
  return unsupportedChecksum();
}

Result decodeFrame(ByteView input, DecodedFrame &frame) {
  FrameHeader header{};
  Result result = decodeHeader(input, header, false);
  if (!result.ok()) {
    return result;
  }
  if (input.size != header.total_length) {
    return badLength();
  }
  const std::size_t payload_end =
      protocol_v1::kHeaderSize + header.payload_length;
  std::uint32_t observed = 0U;
  if (!loadU32(input, payload_end, observed)) {
    return badLength();
  }
  std::uint32_t expected = 0U;
  result = computeChecksum(header.checksum_algorithm,
                           {input.data, payload_end}, expected);
  if (!result.ok()) {
    return result;
  }
  if (observed != expected) {
    return badChecksum();
  }
  const ByteView payload{input.data + protocol_v1::kHeaderSize,
                         header.payload_length};
  result = validatePayload(header, payload);
  if (!result.ok()) {
    return result;
  }
  frame = {header, payload, observed};
  return Result::success();
}

Result encodeFrameTo(FrameFields fields, ByteView payload,
                     MutableByteView output, std::size_t &written) {
  written = 0U;
  if (!payload.valid() || !output.valid() ||
      payload.size > std::numeric_limits<std::uint32_t>::max() ||
      payload.size > protocol_v1::kMaxDataFrameBytes) {
    return badLength();
  }
  const std::size_t framing_bytes =
      protocol_v1::kHeaderSize + protocol_v1::kTrailerSize;
  if (payload.size > std::numeric_limits<std::size_t>::max() - framing_bytes) {
    return badLength();
  }
  const std::size_t total = framing_bytes + payload.size;
  if (total > output.size || total > std::numeric_limits<std::uint32_t>::max()) {
    return badLength();
  }

  FrameHeader header{};
  header.kind = fields.kind;
  header.flags = fields.flags;
  header.checksum_algorithm = fields.checksum_algorithm;
  header.total_length = static_cast<std::uint32_t>(total);
  header.payload_length = static_cast<std::uint32_t>(payload.size);
  header.run_id = fields.run_id;
  header.sequence = fields.sequence;
  header.request_id = fields.request_id;
  header.first_sample_ticks = fields.first_sample_ticks;
  header.item_count = fields.item_count;
  Result result = validateHeader(header, false);
  if (!result.ok()) {
    return result;
  }
  result = validatePayload(header, payload);
  if (!result.ok()) {
    return result;
  }

  for (std::size_t index = 0U; index < total; ++index) {
    output.data[index] = 0U;
  }
  if (!writeHeader(header, output)) {
    return badLength();
  }
  for (std::size_t index = 0U; index < payload.size; ++index) {
    output.data[protocol_v1::kHeaderSize + index] = payload.data[index];
  }
  std::uint32_t checksum = 0U;
  result = computeChecksum(header.checksum_algorithm,
                           {output.data, protocol_v1::kHeaderSize + payload.size},
                           checksum);
  if (!result.ok() ||
      !storeU32(output, protocol_v1::kHeaderSize + payload.size, checksum)) {
    return result.ok() ? badLength() : result;
  }
  written = total;
  return Result::success();
}

Result encodeDataFrameInPlace(FrameFields fields, MutableByteView frame,
                              std::size_t payload_bytes_written) {
  if (!frame.valid() || frame.size != protocol_v1::kDataFrameBytes ||
      payload_bytes_written != protocol_v1::kDataPayloadBytes ||
      !isDataKind(fields.kind)) {
    return badLength();
  }

  FrameHeader header{};
  header.kind = fields.kind;
  header.flags = fields.flags;
  header.checksum_algorithm = fields.checksum_algorithm;
  header.total_length =
      static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes);
  header.payload_length =
      static_cast<std::uint32_t>(protocol_v1::kDataPayloadBytes);
  header.run_id = fields.run_id;
  header.sequence = fields.sequence;
  header.request_id = fields.request_id;
  header.first_sample_ticks = fields.first_sample_ticks;
  header.item_count = fields.item_count;
  Result result = validateHeader(header, false);
  if (!result.ok()) {
    return result;
  }

  const ByteView payload{frame.data + protocol_v1::kHeaderSize,
                         protocol_v1::kDataPayloadBytes};
  result = validatePayload(header, payload);
  if (!result.ok()) {
    return result;
  }
  if (!writeHeader(header, frame)) {
    return badLength();
  }

  std::uint32_t checksum = 0U;
  result = computeChecksum(
      header.checksum_algorithm,
      {frame.data, protocol_v1::kHeaderSize + protocol_v1::kDataPayloadBytes},
      checksum);
  if (!result.ok() ||
      !storeU32(frame,
                protocol_v1::kHeaderSize + protocol_v1::kDataPayloadBytes,
                checksum)) {
    return result.ok() ? badLength() : result;
  }
  return Result::success();
}

Result decodeRequest(ByteView input, Request &request) {
  DecodedFrame frame{};
  Result result = decodeFrame(input, frame);
  if (!result.ok()) {
    return result;
  }
  protocol_v1::CommandKind command{};
  if (!commandForKind(frame.header.kind, command)) {
    return badKind();
  }
  Request decoded{};
  decoded.kind = command;
  decoded.request_id = frame.header.request_id;
  if (command == protocol_v1::CommandKind::kConfigure) {
    decoded.configuration.stream_mask =
        frame.payload.data[protocol_v1::kConfigureRequestStreamMaskOffset];
    decoded.configuration.source = static_cast<protocol_v1::Source>(
        frame.payload.data[protocol_v1::kConfigureRequestSourceOffset]);
    decoded.configuration.data_checksum_algorithm =
        static_cast<protocol_v1::ChecksumAlgorithm>(frame.payload.data[
            protocol_v1::kConfigureRequestDataChecksumAlgorithmOffset]);
    if (!loadU32(frame.payload,
                 protocol_v1::kConfigureRequestDataFrameBytesOffset,
                 decoded.configuration.data_frame_bytes)) {
      return badPayload();
    }
  } else if (command == protocol_v1::CommandKind::kPing &&
             !loadU64(frame.payload, protocol_v1::kPingRequestNonceOffset,
                      decoded.nonce)) {
    return badPayload();
  }
  request = decoded;
  return Result::success();
}

Result encodeInfoResponse(const Request &request, std::uint32_t run_id,
                          const InfoResponse &response, ControlFrame &output) {
  Result result = verifyRequestKind(request, protocol_v1::CommandKind::kInfo);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kInfoResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  payload[protocol_v1::kInfoResponseDeviceStateOffset] =
      static_cast<std::uint8_t>(response.device_state);
  payload[protocol_v1::kInfoResponseProtocolVersionOffset] =
      protocol_v1::kProtocolVersion;
  payload[protocol_v1::kInfoResponseSupportedStreamMaskOffset] =
      response.supported_stream_mask;
  payload[protocol_v1::kInfoResponseSupportedSourceMaskOffset] =
      response.supported_source_mask;
  storeU32(bytes, protocol_v1::kInfoResponseSupportedChecksumMaskOffset,
           response.supported_checksum_mask);
  storeU32(bytes, protocol_v1::kInfoResponseCapabilityBitsOffset,
           response.capability_bits);
  storeU32(bytes, protocol_v1::kInfoResponseTimestampHzOffset,
           response.timestamp_hz);
  storeU32(bytes, protocol_v1::kInfoResponseDataFrameBytesOffset,
           response.data_frame_bytes);
  storeU32(bytes, protocol_v1::kInfoResponseMaxControlFrameBytesOffset,
           response.max_control_frame_bytes);
  storeU32(bytes, protocol_v1::kInfoResponseAdcPairRateHzOffset,
           response.adc_pair_rate_hz);
  storeU32(bytes, protocol_v1::kInfoResponseGpioSampleRateHzOffset,
           response.gpio_sample_rate_hz);
  storeU16(bytes, protocol_v1::kInfoResponseAdcPairPeriodTicksOffset,
           response.adc_pair_period_ticks);
  storeU16(bytes, protocol_v1::kInfoResponseAdc1PhaseTicksOffset,
           response.adc1_phase_ticks);
  storeU16(bytes, protocol_v1::kInfoResponseGpioSamplePeriodTicksOffset,
           response.gpio_sample_period_ticks);
  payload[protocol_v1::kInfoResponseAdcResolutionBitsOffset] =
      response.adc_resolution_bits;
  payload[protocol_v1::kInfoResponseAdcContainerBytesOffset] =
      response.adc_container_bytes;
  payload[protocol_v1::kInfoResponseGpioPinCountOffset] =
      static_cast<std::uint8_t>(response.gpio_pin_map.size());
  for (std::size_t index = 0U; index < response.gpio_pin_map.size(); ++index) {
    payload[protocol_v1::kInfoResponseGpioPinMapOffset + index] =
        response.gpio_pin_map[index];
  }
  storeU32(bytes, protocol_v1::kInfoResponseHardwareSerialOffset,
           response.hardware_serial);
  payload[protocol_v1::kInfoResponseFirmwareVersionMajorOffset] =
      response.firmware_version_major;
  payload[protocol_v1::kInfoResponseFirmwareVersionMinorOffset] =
      response.firmware_version_minor;
  payload[protocol_v1::kInfoResponseFirmwareVersionPatchOffset] =
      response.firmware_version_patch;
  storeU16(bytes, protocol_v1::kInfoResponseBoardIdOffset,
           static_cast<std::uint16_t>(response.board_id));
  storeU16(bytes, protocol_v1::kInfoResponseMcuIdOffset,
           static_cast<std::uint16_t>(response.mcu_id));
  for (std::size_t index = 0U; index < response.build_id.size(); ++index) {
    payload[protocol_v1::kInfoResponseBuildIdOffset + index] =
        response.build_id[index];
  }
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kInfoResponse, request, run_id),
      view(payload), output);
}

Result encodeConfigureResponse(const Request &request, std::uint32_t run_id,
                               const Configuration &configuration,
                               ControlFrame &output) {
  Result result =
      verifyRequestKind(request, protocol_v1::CommandKind::kConfigure);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kConfigureResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  writeConfiguration(bytes, 4U, configuration);
  return encodeFrame(responseFields(protocol_v1::FrameKind::kConfigureResponse,
                                    request, run_id),
                     view(payload), output);
}

Result encodeStartResponse(const Request &request, std::uint32_t run_id,
                           const Configuration &configuration,
                           ControlFrame &output) {
  Result result = verifyRequestKind(request, protocol_v1::CommandKind::kStart);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kConfigureResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  writeConfiguration(bytes, 4U, configuration);
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kStartResponse, request, run_id),
      view(payload), output);
}

Result encodeStatusResponse(const Request &request, std::uint32_t run_id,
                            const StatusResponse &response,
                            ControlFrame &output) {
  Result result =
      verifyRequestKind(request, protocol_v1::CommandKind::kGetStatus);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kStatusResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  payload[protocol_v1::kStatusResponseDeviceStateOffset] =
      static_cast<std::uint8_t>(response.device_state);
  payload[protocol_v1::kStatusResponseStreamMaskOffset] =
      response.configuration.stream_mask;
  payload[protocol_v1::kStatusResponseSourceOffset] =
      static_cast<std::uint8_t>(response.configuration.source);
  payload[protocol_v1::kStatusResponseDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(
          response.configuration.data_checksum_algorithm);
  storeU32(bytes, protocol_v1::kStatusResponseDataFrameBytesOffset,
           response.configuration.data_frame_bytes);
  storeU64(bytes, protocol_v1::kStatusResponseAdcFramesEmittedOffset,
           response.adc_frames_emitted);
  storeU64(bytes, protocol_v1::kStatusResponseGpioFramesEmittedOffset,
           response.gpio_frames_emitted);
  storeU64(bytes, protocol_v1::kStatusResponseAdcItemsDroppedOffset,
           response.adc_items_dropped);
  storeU64(bytes, protocol_v1::kStatusResponseGpioItemsDroppedOffset,
           response.gpio_items_dropped);
  storeU32(bytes, protocol_v1::kStatusResponseParserErrorsOffset,
           response.parser_errors);
  storeU32(bytes, protocol_v1::kStatusResponseTransportErrorsOffset,
           response.transport_errors);
  storeU32(bytes, protocol_v1::kStatusResponseStatsGenerationOffset,
           response.stats_generation);
  return encodeFrame(responseFields(protocol_v1::FrameKind::kGetStatusResponse,
                                    request, run_id),
                     view(payload), output);
}

Result encodeStopResponse(const Request &request, std::uint32_t run_id,
                          ControlFrame &output) {
  Result result = verifyRequestKind(request, protocol_v1::CommandKind::kStop);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kStopResponsePayloadSize> payload{};
  writeSuccessPrefix(mutableView(payload));
  payload[protocol_v1::kStopResponseDeviceStateOffset] =
      static_cast<std::uint8_t>(protocol_v1::DeviceState::kIdle);
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kStopResponse, request, run_id),
      view(payload), output);
}

Result encodeResetStatsResponse(const Request &request, std::uint32_t run_id,
                                std::uint32_t stats_generation,
                                ControlFrame &output) {
  Result result =
      verifyRequestKind(request, protocol_v1::CommandKind::kResetStats);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kResetStatsResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  storeU32(bytes, protocol_v1::kResetStatsResponseStatsGenerationOffset,
           stats_generation);
  return encodeFrame(responseFields(protocol_v1::FrameKind::kResetStatsResponse,
                                    request, run_id),
                     view(payload), output);
}

Result encodePingResponse(const Request &request, std::uint32_t run_id,
                          ControlFrame &output) {
  Result result = verifyRequestKind(request, protocol_v1::CommandKind::kPing);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v1::kPingResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  storeU64(bytes, protocol_v1::kPingResponseNonceOffset, request.nonce);
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kPingResponse, request, run_id),
      view(payload), output);
}

Result encodeTypedErrorResponse(const Request &request, std::uint32_t run_id,
                                protocol_v1::ErrorCode error,
                                ControlFrame &output) {
  if (request.request_id == 0U) {
    return badRequestId();
  }
  if (!isKnownError(error) || error == protocol_v1::ErrorCode::kOk) {
    return badPayload();
  }
  const protocol_v1::FrameKind request_kind =
      protocol_v1::requestFrameKind(request.kind);
  protocol_v1::CommandKind checked{};
  if (!commandForKind(request_kind, checked) || checked != request.kind) {
    return badKind();
  }
  std::array<std::uint8_t, protocol_v1::kResponsePrefixPayloadSize> payload{};
  writeErrorPrefix(mutableView(payload), error);
  return encodeFrame(
      responseFields(protocol_v1::responseFrameKind(request.kind), request,
                     run_id, kResponseErrorFlag),
      view(payload), output);
}

Result encodeRejectedFrameResponse(std::uint32_t request_id,
                                   std::uint8_t rejected_kind,
                                   std::uint8_t rejected_version,
                                   protocol_v1::ErrorCode error,
                                   ControlFrame &output) {
  if (request_id == 0U) {
    return badRequestId();
  }
  if (!isKnownError(error) || error == protocol_v1::ErrorCode::kOk) {
    return badPayload();
  }
  std::array<std::uint8_t, protocol_v1::kErrorResponsePayloadSize> payload{};
  writeErrorPrefix(mutableView(payload), error);
  payload[protocol_v1::kErrorResponseRejectedKindOffset] = rejected_kind;
  payload[protocol_v1::kErrorResponseRejectedVersionOffset] = rejected_version;
  FrameFields fields{};
  fields.kind = protocol_v1::FrameKind::kErrorResponse;
  fields.flags = kResponseErrorFlag;
  fields.request_id = request_id;
  return encodeFrame(fields, view(payload), output);
}

FeedResult IncrementalCommandParser::feed(ByteView input,
                                          ParsedCommand &command) {
  FeedResult result{};
  if (!input.valid()) {
    return result;
  }
  while (result.consumed < input.size) {
    if (buffered_ == buffer_.size()) {
      recordFailure(badLength());
      discard(1U);
    }
    buffer_[buffered_++] = input.data[result.consumed++];
    saturatingIncrement(counters_.bytes_received);
    updateHighWater();
    if (drain(command)) {
      result.command_ready = true;
      return result;
    }
  }
  return result;
}

void IncrementalCommandParser::reset() {
  buffer_ = {};
  buffered_ = 0U;
  resynchronizing_ = false;
  counters_ = {};
}

ParserCounters IncrementalCommandParser::counters() const {
  ParserCounters result = counters_;
  result.buffered_bytes = buffered_;
  return result;
}

bool IncrementalCommandParser::drain(ParsedCommand &command) {
  while (true) {
    const std::size_t magic_at = findMagic();
    if (magic_at == kNotFound) {
      const std::size_t retained = partialMagicSuffix();
      discard(buffered_ - retained);
      return false;
    }
    if (magic_at != 0U) {
      discard(magic_at);
    }
    if (buffered_ < protocol_v1::kHeaderSize) {
      return false;
    }
    FrameHeader header{};
    Result result = decodeHeader({buffer_.data(), buffered_}, header, true);
    if (!result.ok()) {
      recordFailure(result);
      discard(1U);
      continue;
    }
    if (buffered_ < header.total_length) {
      return false;
    }
    Request request{};
    result = decodeRequest({buffer_.data(), header.total_length}, request);
    if (!result.ok()) {
      recordFailure(result);
      discard(1U);
      continue;
    }
    if (!command.frame.setSize(header.total_length)) {
      recordFailure(badLength());
      discard(1U);
      continue;
    }
    for (std::size_t index = 0U; index < header.total_length; ++index) {
      command.frame.mutableData()[index] = buffer_[index];
    }
    command.request = request;
    for (std::size_t index = header.total_length; index < buffered_; ++index) {
      buffer_[index - header.total_length] = buffer_[index];
    }
    buffered_ -= header.total_length;
    saturatingIncrement(counters_.commands_accepted);
    resynchronizing_ = false;
    return true;
  }
}

std::size_t IncrementalCommandParser::findMagic() const {
  if (buffered_ < kMagicBytes) {
    return kNotFound;
  }
  for (std::size_t start = 0U; start <= buffered_ - kMagicBytes; ++start) {
    bool matches = true;
    for (std::size_t index = 0U; index < kMagicBytes; ++index) {
      if (buffer_[start + index] != magicByte(index)) {
        matches = false;
        break;
      }
    }
    if (matches) {
      return start;
    }
  }
  return kNotFound;
}

std::size_t IncrementalCommandParser::partialMagicSuffix() const {
  const std::size_t maximum =
      buffered_ < kMagicBytes - 1U ? buffered_ : kMagicBytes - 1U;
  for (std::size_t length = maximum; length > 0U; --length) {
    bool matches = true;
    for (std::size_t index = 0U; index < length; ++index) {
      if (buffer_[buffered_ - length + index] != magicByte(index)) {
        matches = false;
        break;
      }
    }
    if (matches) {
      return length;
    }
  }
  return 0U;
}

void IncrementalCommandParser::discard(std::size_t count) {
  if (count == 0U) {
    return;
  }
  if (count > buffered_) {
    count = buffered_;
  }
  if (!resynchronizing_) {
    resynchronizing_ = true;
    saturatingIncrement(counters_.resynchronizations);
  }
  for (std::size_t index = count; index < buffered_; ++index) {
    buffer_[index - count] = buffer_[index];
  }
  buffered_ -= count;
  for (std::size_t index = 0U; index < count; ++index) {
    saturatingIncrement(counters_.bytes_discarded);
  }
}

void IncrementalCommandParser::recordFailure(const Result &failure) {
  saturatingIncrement(counters_.candidates_rejected);
  switch (failure.issue) {
    case ValidationIssue::kBadVersion:
      saturatingIncrement(counters_.bad_versions);
      break;
    case ValidationIssue::kBadKind:
      saturatingIncrement(counters_.bad_kinds);
      break;
    case ValidationIssue::kBadFlags:
      saturatingIncrement(counters_.bad_flags);
      break;
    case ValidationIssue::kBadLength:
    case ValidationIssue::kBadMagic:
      saturatingIncrement(counters_.bad_lengths);
      break;
    case ValidationIssue::kBadChecksum:
      saturatingIncrement(counters_.bad_checksums);
      break;
    case ValidationIssue::kBadPayload:
      saturatingIncrement(counters_.bad_payloads);
      break;
    case ValidationIssue::kBadRequestId:
      saturatingIncrement(counters_.bad_request_ids);
      break;
    case ValidationIssue::kUnsupportedChecksum:
      saturatingIncrement(counters_.unsupported_checksums);
      break;
    case ValidationIssue::kNone:
      break;
  }
}

void IncrementalCommandParser::updateHighWater() {
  if (buffered_ > counters_.high_water_mark) {
    counters_.high_water_mark = buffered_;
  }
}

}  // namespace teensy_daq::protocol
