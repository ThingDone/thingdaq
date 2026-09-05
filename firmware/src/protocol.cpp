#include "input_experiment_profile.h"

#include "protocol.h"

#include <limits>

#include "checksum.h"
#include "generated/protocol_v2_constants.h"
#include "rate_profile_table.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_PROTOCOL_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_PROTOCOL_COLD_CODE(section_name)
#endif

namespace thingdaq::protocol {
namespace {

constexpr std::size_t kNotFound = static_cast<std::size_t>(-1);
constexpr std::uint8_t kValidStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
constexpr std::uint16_t kResponseErrorFlag =
    static_cast<std::uint16_t>(protocol_v1::FrameFlag::kResponseError);

constexpr std::uint32_t absoluteDifference(std::uint32_t left,
                                           std::uint32_t right) {
  return left >= right ? left - right : right - left;
}

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
  if (kind == kTemperatureRequest || kind == kTemperatureResponse) return true;
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
    case protocol_v1::FrameKind::kChecksumBenchmarkRequest:
    case protocol_v1::FrameKind::kGpioClockDiagnosticRequest:
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticRequest:
    case protocol_v1::FrameKind::kInfoResponse:
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
    case protocol_v1::FrameKind::kGetStatusResponse:
    case protocol_v1::FrameKind::kStopResponse:
    case protocol_v1::FrameKind::kResetStatsResponse:
    case protocol_v1::FrameKind::kPingResponse:
    case protocol_v1::FrameKind::kChecksumBenchmarkResponse:
    case protocol_v1::FrameKind::kGpioClockDiagnosticResponse:
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticResponse:
    case protocol_v1::FrameKind::kErrorResponse:
      return true;
  }
  return false;
}

constexpr bool isRequestKind(protocol_v1::FrameKind kind) {
  if (kind == kTemperatureRequest) return true;
  switch (kind) {
    case protocol_v1::FrameKind::kInfoRequest:
    case protocol_v1::FrameKind::kConfigureRequest:
    case protocol_v1::FrameKind::kStartRequest:
    case protocol_v1::FrameKind::kGetStatusRequest:
    case protocol_v1::FrameKind::kStopRequest:
    case protocol_v1::FrameKind::kResetStatsRequest:
    case protocol_v1::FrameKind::kPingRequest:
    case protocol_v1::FrameKind::kChecksumBenchmarkRequest:
    case protocol_v1::FrameKind::kGpioClockDiagnosticRequest:
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticRequest:
      return true;
    default:
      return false;
  }
}

constexpr bool isDataKind(protocol_v1::FrameKind kind) {
  return kind == protocol_v1::FrameKind::kAdcData ||
         kind == protocol_v1::FrameKind::kGpioData;
}

constexpr bool isKnownChecksum(protocol_v1::ChecksumAlgorithm algorithm) {
  switch (algorithm) {
    case protocol_v1::ChecksumAlgorithm::kNoneReserved:
    case protocol_v1::ChecksumAlgorithm::kAdler32:
    case protocol_v1::ChecksumAlgorithm::kCrc32c:
    case protocol_v1::ChecksumAlgorithm::kCrc32IsoHdlc:
      return true;
  }
  return false;
}

constexpr bool checksumAllowedForKind(
    protocol_v1::FrameKind kind,
    protocol_v1::ChecksumAlgorithm algorithm) {
  return isSupportedChecksum(algorithm) &&
         (isDataKind(kind) ||
          algorithm == protocol_v1::kBootstrapChecksumAlgorithm);
}

constexpr bool isTypedResponseKind(protocol_v1::FrameKind kind) {
  if (kind == kTemperatureResponse) return true;
  switch (kind) {
    case protocol_v1::FrameKind::kInfoResponse:
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
    case protocol_v1::FrameKind::kGetStatusResponse:
    case protocol_v1::FrameKind::kStopResponse:
    case protocol_v1::FrameKind::kResetStatsResponse:
    case protocol_v1::FrameKind::kPingResponse:
    case protocol_v1::FrameKind::kChecksumBenchmarkResponse:
    case protocol_v1::FrameKind::kGpioClockDiagnosticResponse:
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticResponse:
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

constexpr std::uint16_t configurationProfileBit(std::uint8_t source,
                                                std::uint8_t streams) {
  const std::uint8_t adc =
      static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc);
  const std::uint8_t gpio =
      static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
  const bool combined = streams == static_cast<std::uint8_t>(adc | gpio);
  if (source == static_cast<std::uint8_t>(protocol_v1::Source::kHardware)) {
    return streams == adc
               ? static_cast<std::uint16_t>(
                     protocol_v1::ConfigurationProfile::kHardwareAdc)
           : streams == gpio
               ? static_cast<std::uint16_t>(
                     protocol_v1::ConfigurationProfile::kHardwareGpio)
           : combined
               ? static_cast<std::uint16_t>(
                     protocol_v1::ConfigurationProfile::kHardwareCombined)
               : 0U;
  }
  if (source == static_cast<std::uint8_t>(protocol_v1::Source::kSynthetic)) {
    return streams == adc
               ? static_cast<std::uint16_t>(
                     protocol_v1::ConfigurationProfile::kSyntheticAdc)
           : streams == gpio
               ? static_cast<std::uint16_t>(
                     protocol_v1::ConfigurationProfile::kSyntheticGpio)
           : combined
               ? static_cast<std::uint16_t>(
                     protocol_v1::ConfigurationProfile::kSyntheticCombined)
               : 0U;
  }
  return 0U;
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.command_kind")
bool commandForKind(protocol_v1::FrameKind kind,
                    protocol_v1::CommandKind &command) {
  if (kind == kTemperatureRequest) {
    command = kGetTemperature;
    return true;
  }
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
    case protocol_v1::FrameKind::kChecksumBenchmarkRequest:
      command = protocol_v1::CommandKind::kChecksumBenchmark;
      return true;
    case protocol_v1::FrameKind::kGpioClockDiagnosticRequest:
      command = protocol_v1::CommandKind::kGpioClockDiagnostic;
      return true;
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticRequest:
      command = protocol_v1::CommandKind::kGpioCaptureDiagnostic;
      return true;
    default:
      return false;
  }
}

bool expectedPayloadSize(protocol_v1::FrameKind kind, bool response_error,
                         std::uint8_t version, std::size_t &size) {
  if (response_error && isTypedResponseKind(kind)) {
    size = protocol_v1::kResponsePrefixPayloadSize;
    return true;
  }
  if (kind == kTemperatureRequest || kind == kTemperatureResponse) {
    size = kind == kTemperatureRequest ? 0U : protocol_v2::kTemperatureResponsePayloadSize;
    return version == protocol_v2::kProtocolVersion;
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
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticRequest:
      size = protocol_v1::kEmptyPayloadSize;
      return true;
    case protocol_v1::FrameKind::kConfigureRequest:
      size = version == protocol_v2::kProtocolVersion
                 ? protocol_v2::kConfigureRequestPayloadSize
                 : protocol_v1::kConfigureRequestPayloadSize;
      return true;
    case protocol_v1::FrameKind::kPingRequest:
      size = protocol_v1::kPingRequestPayloadSize;
      return true;
    case protocol_v1::FrameKind::kChecksumBenchmarkRequest:
      size = protocol_v1::kChecksumBenchmarkRequestPayloadSize;
      return true;
    case protocol_v1::FrameKind::kGpioClockDiagnosticRequest:
      size = protocol_v1::kGpioClockDiagnosticRequestPayloadSize;
      return true;
    case protocol_v1::FrameKind::kInfoResponse:
      size = version == protocol_v2::kProtocolVersion
                 ? protocol_v2::kInfoResponsePayloadSize
                 : protocol_v1::kInfoResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
      size = version == protocol_v2::kProtocolVersion
                 ? protocol_v2::kConfigureResponsePayloadSize
                 : protocol_v1::kConfigureResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kGetStatusResponse:
      size = version == protocol_v2::kProtocolVersion
                 ? protocol_v2::kStatusResponsePayloadSize
                 : protocol_v1::kStatusResponsePayloadSize;
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
    case protocol_v1::FrameKind::kChecksumBenchmarkResponse:
      size = protocol_v1::kChecksumBenchmarkResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kGpioClockDiagnosticResponse:
      size = protocol_v1::kGpioClockDiagnosticResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticResponse:
      size = version == protocol_v2::kProtocolVersion
                 ? protocol_v2::kGpioCaptureDiagnosticResponsePayloadSize
                 : protocol_v1::kGpioCaptureDiagnosticResponsePayloadSize;
      return true;
    case protocol_v1::FrameKind::kErrorResponse:
      size = protocol_v1::kErrorResponsePayloadSize;
      return response_error;
  }
  return false;
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.header_validation")
Result validateHeader(const FrameHeader &header, bool commands_only) {
  if (header.version != protocol_v1::kProtocolVersion &&
      header.version != protocol_v2::kProtocolVersion) {
    return badVersion();
  }
  if (!isKnownKind(header.kind) ||
      (commands_only && !isRequestKind(header.kind))) {
    return badKind();
  }
  if (header.version != protocol_v2::kProtocolVersion &&
      (header.kind == kTemperatureRequest || header.kind == kTemperatureResponse))
    return badKind();
  if (header.header_length != protocol_v1::kHeaderSize) {
    return badLength();
  }
  if (!checksumAllowedForKind(header.kind, header.checksum_algorithm)) {
    return unsupportedChecksum();
  }
  const std::uint16_t allowed = header.kind == kTemperatureResponse
      ? kResponseErrorFlag : protocol_v1::allowedFlags(header.kind);
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
  if (!isDataKind(header.kind)) {
    std::size_t expected_payload = 0U;
    if (!expectedPayloadSize(header.kind, response_error, header.version,
                             expected_payload) ||
        header.payload_length != expected_payload) {
      return badLength();
    }
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
    if (header.version == protocol_v2::kProtocolVersion) {
      const bool adc = header.kind == protocol_v1::FrameKind::kAdcData;
      const bool disabled =
          header.payload_length == protocol_v2::kDataPayloadBytes &&
          header.item_count ==
              (adc ? protocol_v2::kDisabledAdcPairsPerFrame
                   : protocol_v2::kDisabledGpioSamplesPerFrame);
      const bool input =
          header.payload_length ==
              (adc ? protocol_v2::kInputAdcPairsPerFrame *
                         protocol_v2::kAdcBytesPerPair
                   : protocol_v2::kInputGpioSamplesPerFrame * 2U) &&
          header.item_count ==
              (adc ? protocol_v2::kInputAdcPairsPerFrame
                   : protocol_v2::kInputGpioSamplesPerFrame);
      const std::uint32_t item_bytes = adc ? 4U : (input ? 2U : 1U);
      if ((!disabled && !input) ||
          header.total_length != protocol_v1::kHeaderSize +
                                     header.item_count * item_bytes +
                                     protocol_v1::kTrailerSize ||
          header.run_id == 0U || header.request_id != 0U) {
        return badLength();
      }
      bool aligned = false;
      for (const protocol_v2::RateProfileTiming &timing :
           rate_profile::kTimings) {
        const std::uint32_t period =
            adc ? timing.adc_pair_period_ticks
                : timing.gpio_sample_period_ticks;
        aligned = aligned || header.first_sample_ticks % period == 0U;
      }
      const bool epoch_start =
          (header.flags & static_cast<std::uint16_t>(
                              protocol_v1::FrameFlag::kEpochStart)) != 0U;
      const bool first_item =
          header.sequence == 0U && header.first_sample_ticks == 0U;
      return aligned && epoch_start == first_item ? Result::success()
                                                  : badPayload();
    }
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

  const std::uint32_t max_control =
      header.version == protocol_v2::kProtocolVersion
          ? protocol_v2::kMaxControlFrameBytes
          : protocol_v1::kMaxControlFrameBytes;
  if (header.total_length < protocol_v1::kMinFrameBytes ||
      header.total_length > max_control) {
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
    const std::size_t max_command =
        header.version == protocol_v2::kProtocolVersion
            ? protocol_v2::kMaxCommandFrameBytes
            : protocol_v1::kMaxCommandFrameBytes;
    if (header.total_length > max_command) {
      return badLength();
    }
  }
  if (header.kind == protocol_v1::FrameKind::kStartResponse &&
      !response_error && header.run_id == 0U) {
    return badPayload();
  }
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.header_decode")
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
  if (version != protocol_v1::kProtocolVersion &&
      version != protocol_v2::kProtocolVersion) {
    return badVersion();
  }
  protocol_v1::FrameKind kind{};
  if (!decodeKind(input.data[protocol_v1::kHeaderKindOffset], kind) ||
      (commands_only && !isRequestKind(kind))) {
    return badKind();
  }
  const std::uint8_t raw_checksum =
      input.data[protocol_v1::kHeaderChecksumAlgorithmOffset];
  const auto checksum_algorithm =
      static_cast<protocol_v1::ChecksumAlgorithm>(raw_checksum);
  if (!isKnownChecksum(checksum_algorithm) ||
      !checksumAllowedForKind(kind, checksum_algorithm)) {
    return unsupportedChecksum();
  }
  if (input.data[protocol_v1::kHeaderReservedOffset] != 0U) {
    return badPayload();
  }

  FrameHeader candidate{};
  candidate.kind = kind;
  candidate.version = version;
  candidate.checksum_algorithm = checksum_algorithm;
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.payload_validation")
Result validateConfiguration(ByteView payload, std::size_t offset,
                             bool applied, std::uint8_t version) {
  const std::size_t body_size =
      version == protocol_v2::kProtocolVersion
          ? protocol_v2::kConfigureRequestPayloadSize
          : protocol_v1::kConfigureRequestPayloadSize;
  if (!hasRange(payload.size, offset, body_size)) {
    return badLength();
  }
  const std::uint8_t streams = payload.data[offset];
  const std::uint8_t source = payload.data[offset + 1U];
  const std::uint8_t checksum = payload.data[offset + 2U];
  const std::uint8_t raw_mode = payload.data[offset + 3U];
  if ((streams & static_cast<std::uint8_t>(~kValidStreamMask)) != 0U ||
      !isKnownSource(source) ||
      (version == protocol_v1::kProtocolVersion && raw_mode != 0U) ||
      (version == protocol_v2::kProtocolVersion && raw_mode > 1U)) {
    return badPayload();
  }
  const auto checksum_algorithm =
      static_cast<protocol_v1::ChecksumAlgorithm>(checksum);
  if (!isKnownChecksum(checksum_algorithm) ||
      checksum_algorithm == protocol_v1::ChecksumAlgorithm::kNoneReserved) {
    return badPayload();
  }
  if (applied && !isSupportedChecksum(checksum_algorithm)) {
    return unsupportedChecksum();
  }
  std::uint32_t frame_bytes = 0U;
  if (!loadU32(payload, offset + 4U, frame_bytes) ||
      frame_bytes != protocol_v1::kDataFrameBytes) {
    return badPayload();
  }
  if (version == protocol_v2::kProtocolVersion) {
    std::uint32_t adc_rate = 0U;
    std::uint32_t gpio_rate = 0U;
    if (!loadU32(payload, offset + 8U, adc_rate) ||
        !loadU32(payload, offset + 12U, gpio_rate)) {
      return badLength();
    }
    bool matched = false;
    for (const protocol_v2::RateProfileTiming &timing :
         rate_profile::kTimings) {
      matched = matched ||
                (timing.adc_pair_rate_hz == adc_rate &&
                 timing.gpio_sample_rate_hz == gpio_rate);
    }
    if (!matched) {
      return badPayload();
    }
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

struct AdcMetadataOffsets {
  std::size_t resolution_bits;
  std::size_t container_bytes;
  std::size_t calibration_state_0;
  std::size_t calibration_state_1;
  std::size_t code_min;
  std::size_t code_max;
  std::size_t reference;
  std::size_t clock_source;
  std::size_t clock_divider;
  std::size_t hardware_average_count;
  std::size_t reference_mv_nominal;
  std::size_t input_min_mv_nominal;
  std::size_t input_max_mv_nominal;
  std::size_t sample_time_adck;
  std::size_t conversion_mode;
  std::size_t configuration_flags;
  std::size_t pin_0;
  std::size_t pin_1;
  std::size_t peripheral_0;
  std::size_t peripheral_1;
  std::size_t channel_0;
  std::size_t channel_1;
  std::size_t ipg_clock_hz;
  std::size_t adc_clock_hz;
  std::size_t calibration_deadline_us;
  std::size_t calibration_cycles_0;
  std::size_t calibration_cycles_1;
  std::size_t initialization_error_flags;
};

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.adc_metadata_validation")
Result validateAdcMetadata(ByteView payload,
                           const AdcMetadataOffsets &offsets) {
  const std::uint8_t resolution = payload.data[offsets.resolution_bits];
  const bool primary = resolution == protocol_v1::kAdcPrimaryResolutionBits;
  const bool fallback = resolution == protocol_v1::kAdcFallbackResolutionBits;
  const std::uint8_t calibration_state_0 =
      payload.data[offsets.calibration_state_0];
  const std::uint8_t calibration_state_1 =
      payload.data[offsets.calibration_state_1];
  if ((!primary && !fallback) ||
      payload.data[offsets.container_bytes] !=
          protocol_v1::kAdcContainerBits / 8U ||
      payload.data[offsets.reference] != static_cast<std::uint8_t>(
          protocol_v1::AdcReference::kVrefhVreflNominal3v3) ||
      payload.data[offsets.clock_source] != static_cast<std::uint8_t>(
          protocol_v1::AdcClockSource::kSynchronousIpg) ||
      payload.data[offsets.clock_divider] != protocol_v1::kAdcClockDivider ||
      payload.data[offsets.hardware_average_count] !=
          protocol_v1::kAdcHardwareAverageCount ||
      payload.data[offsets.sample_time_adck] !=
          protocol_v1::kAdcSampleTimeAdck ||
      payload.data[offsets.conversion_mode] != (primary ? 2U : 1U) ||
      calibration_state_0 > static_cast<std::uint8_t>(
          protocol_v1::AdcCalibrationState::kClockUnavailable) ||
      calibration_state_1 > static_cast<std::uint8_t>(
          protocol_v1::AdcCalibrationState::kClockUnavailable) ||
      payload.data[offsets.pin_0] != protocol_v1::kAdcPins[0] ||
      payload.data[offsets.pin_1] != protocol_v1::kAdcPins[1] ||
      payload.data[offsets.peripheral_0] != protocol_v1::kAdcPeripherals[0] ||
      payload.data[offsets.peripheral_1] != protocol_v1::kAdcPeripherals[1] ||
      payload.data[offsets.channel_0] != protocol_v1::kAdcChannels[0] ||
      payload.data[offsets.channel_1] != protocol_v1::kAdcChannels[1]) {
    return badPayload();
  }

  std::uint16_t value16 = 0U;
  std::uint16_t flags = 0U;
  if (!loadU16(payload, offsets.code_min, value16) ||
      value16 != protocol_v1::kAdcCodeMin ||
      !loadU16(payload, offsets.code_max, value16) ||
      value16 != (primary ? 4095U : 1023U) ||
      !loadU16(payload, offsets.reference_mv_nominal, value16) ||
      value16 != protocol_v1::kAdcReferenceMvNominal ||
      !loadU16(payload, offsets.input_min_mv_nominal, value16) ||
      value16 != protocol_v1::kAdcInputMinMvNominal ||
      !loadU16(payload, offsets.input_max_mv_nominal, value16) ||
      value16 != protocol_v1::kAdcInputMaxMvNominal ||
      !loadU16(payload, offsets.configuration_flags, flags) ||
      (flags & ~protocol_v1::kKnownAdcConfigurationFlagMask) != 0U) {
    return badPayload();
  }
  constexpr std::uint16_t kRequiredSettingFlags =
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kNoHardwareAveraging) |
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kHighSpeed) |
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kShortestSample);
  const std::uint16_t resolution_flag = static_cast<std::uint16_t>(
      primary ? protocol_v1::AdcConfigurationFlag::kPrimary12Bit
              : protocol_v1::AdcConfigurationFlag::kFallback10Bit);
  const std::uint16_t other_resolution_flag = static_cast<std::uint16_t>(
      primary ? protocol_v1::AdcConfigurationFlag::kFallback10Bit
              : protocol_v1::AdcConfigurationFlag::kPrimary12Bit);
  if ((flags & kRequiredSettingFlags) != kRequiredSettingFlags ||
      (flags & resolution_flag) == 0U ||
      (flags & other_resolution_flag) != 0U) {
    return badPayload();
  }

  std::uint32_t value32 = 0U;
  std::uint32_t errors = 0U;
  const std::size_t clock_offsets[] = {
      offsets.ipg_clock_hz,
      offsets.adc_clock_hz,
      offsets.calibration_deadline_us,
  };
  const std::uint32_t clock_expected[] = {
      protocol_v1::kAdcIpgClockHz,
      protocol_v1::kAdcClockHz,
      protocol_v1::kAdcCalibrationDeadlineUs,
  };
  for (std::size_t index = 0U;
       index < sizeof(clock_offsets) / sizeof(clock_offsets[0]); ++index) {
    if (!loadU32(payload, clock_offsets[index], value32) ||
        value32 != clock_expected[index]) {
      return badPayload();
    }
  }
  if (!loadU32(payload, offsets.calibration_cycles_0, value32) ||
      !loadU32(payload, offsets.calibration_cycles_1, value32) ||
      !loadU32(payload, offsets.initialization_error_flags, errors) ||
      (errors & ~protocol_v1::kKnownAdcInitializationErrorMask) != 0U) {
    return badPayload();
  }

  const std::uint16_t initialized = static_cast<std::uint16_t>(
      protocol_v1::AdcConfigurationFlag::kInitialized);
  const std::uint16_t routes_validated = static_cast<std::uint16_t>(
      protocol_v1::AdcConfigurationFlag::kRoutesValidated);
  const std::uint16_t readback_valid = static_cast<std::uint16_t>(
      protocol_v1::AdcConfigurationFlag::kConfigurationReadbackValid);
  const std::uint16_t calibration_complete = static_cast<std::uint16_t>(
      protocol_v1::AdcConfigurationFlag::kCalibrationComplete);
  if ((flags & initialized) != 0U &&
      (errors != 0U || (flags & routes_validated) == 0U ||
       (flags & readback_valid) == 0U ||
       (flags & calibration_complete) == 0U ||
       calibration_state_0 != static_cast<std::uint8_t>(
           protocol_v1::AdcCalibrationState::kSucceeded) ||
       calibration_state_1 != static_cast<std::uint8_t>(
           protocol_v1::AdcCalibrationState::kSucceeded))) {
    return badPayload();
  }
  return Result::success();
}

namespace adc_trigger_wire {
inline constexpr std::size_t kBytes = 144U;
inline constexpr std::size_t kConfigurationFlags = 0U;
inline constexpr std::size_t kReserved0 = 2U;
inline constexpr std::size_t kErrorFlags = 4U;
inline constexpr std::size_t kPitClockHz = 8U;
inline constexpr std::size_t kDwtClockHz = 12U;
inline constexpr std::size_t kGpioMasterRateHz = 16U;
inline constexpr std::size_t kPairRateHz = 20U;
inline constexpr std::size_t kIpgClockHz = 24U;
inline constexpr std::size_t kGpioMasterPitChannel = 28U;
inline constexpr std::size_t kPairPitChannel = 29U;
inline constexpr std::size_t kGpioMasterPitLoad = 30U;
inline constexpr std::size_t kPairPitLoad = 31U;
inline constexpr std::size_t kPredivider = 32U;
inline constexpr std::size_t kChainLength = 33U;
inline constexpr std::size_t kXbarInputs = 34U;
inline constexpr std::size_t kXbarOutputs = 36U;
inline constexpr std::size_t kTriggerQueues = 38U;
inline constexpr std::size_t kInitialDelays = 40U;
inline constexpr std::size_t kEffectiveDelays = 44U;
inline constexpr std::size_t kPhaseIpgCycles = 48U;
inline constexpr std::size_t kReserved1 = 50U;
inline constexpr std::size_t kCcmCscmr1 = 52U;
inline constexpr std::size_t kCcmCcgr1 = 56U;
inline constexpr std::size_t kCcmCcgr2 = 60U;
inline constexpr std::size_t kPitMcr = 64U;
inline constexpr std::size_t kMasterTctrl = 68U;
inline constexpr std::size_t kPairTctrl = 72U;
inline constexpr std::size_t kAdcEtcCtrl = 76U;
inline constexpr std::size_t kTriggerCtrl = 80U;
inline constexpr std::size_t kTriggerCounter = 88U;
inline constexpr std::size_t kChain = 96U;
inline constexpr std::size_t kDone0_1Irq = 104U;
inline constexpr std::size_t kDone2ErrIrq = 108U;
inline constexpr std::size_t kCompletionCounts = 112U;
inline constexpr std::size_t kCompletionDelta = 120U;
inline constexpr std::size_t kCompletionExpected = 124U;
inline constexpr std::size_t kCompletionTolerance = 128U;
inline constexpr std::size_t kDiagnosticElapsed = 132U;
inline constexpr std::size_t kTriggerErrorCount = 136U;
inline constexpr std::size_t kXbarSelections = 140U;
}  // namespace adc_trigger_wire

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.adc_trigger_metadata_validation")
Result validateAdcTriggerMetadata(ByteView payload, std::size_t base) {
  using namespace adc_trigger_wire;
  if (!hasRange(payload.size, base, kBytes)) {
    return badLength();
  }

  std::uint16_t flags = 0U;
  std::uint16_t value16 = 0U;
  std::uint32_t errors = 0U;
  if (!loadU16(payload, base + kConfigurationFlags, flags) ||
      (flags & ~protocol_v1::kKnownAdcTriggerConfigurationFlagMask) != 0U ||
      !loadU16(payload, base + kReserved0, value16) || value16 != 0U ||
      !loadU32(payload, base + kErrorFlags, errors) ||
      (errors & ~protocol_v1::kKnownAdcTriggerErrorMask) != 0U ||
      !loadU16(payload, base + kReserved1, value16) || value16 != 0U) {
    return badPayload();
  }

  const std::size_t fixed32_offsets[] = {
      kPitClockHz, kDwtClockHz, kGpioMasterRateHz, kPairRateHz,
      kIpgClockHz, kCompletionExpected, kCompletionTolerance};
  const std::uint32_t fixed32_expected[] = {
      protocol_v1::kAdcTriggerPitClockHz,
      input_experiment::kCpuHz,
      protocol_v1::kAdcTriggerGpioMasterRateHz,
      protocol_v1::kAdcTriggerPairRateHz,
      protocol_v1::kAdcTriggerIpgClockHz,
      input_experiment::scaleDwt(protocol_v1::kAdcCompletionExpectedDwtCycles),
      input_experiment::scaleDwt(protocol_v1::kAdcCompletionToleranceDwtCycles)};
  std::uint32_t value32 = 0U;
  for (std::size_t index = 0U;
       index < sizeof(fixed32_offsets) / sizeof(fixed32_offsets[0]); ++index) {
    if (!loadU32(payload, base + fixed32_offsets[index], value32) ||
        value32 != fixed32_expected[index]) {
      return badPayload();
    }
  }

  const std::uint8_t fixed8_expected[] = {
      protocol_v1::kAdcTriggerGpioMasterPitChannel,
      protocol_v1::kAdcTriggerPairPitChannel,
      protocol_v1::kAdcTriggerGpioMasterPitLoad,
      protocol_v1::kAdcTriggerPairPitLoad,
      protocol_v1::kAdcTriggerPredivider,
      protocol_v1::kAdcTriggerChainLength,
      protocol_v1::kAdcTriggerXbarInputs[0],
      protocol_v1::kAdcTriggerXbarInputs[1],
      protocol_v1::kAdcTriggerXbarOutputs[0],
      protocol_v1::kAdcTriggerXbarOutputs[1],
      protocol_v1::kAdcTriggerQueues[0],
      protocol_v1::kAdcTriggerQueues[1]};
  for (std::size_t index = 0U;
       index < sizeof(fixed8_expected) / sizeof(fixed8_expected[0]); ++index) {
    if (payload.data[base + kGpioMasterPitChannel + index] !=
        fixed8_expected[index]) {
      return badPayload();
    }
  }

  const std::size_t fixed16_offsets[] = {
      kInitialDelays, kInitialDelays + 2U, kEffectiveDelays,
      kEffectiveDelays + 2U, kPhaseIpgCycles};
  const std::uint16_t fixed16_expected[] = {
      protocol_v1::kAdcTriggerInitialDelays[0],
      protocol_v1::kAdcTriggerInitialDelays[1],
      protocol_v1::kAdcTriggerEffectiveDelays[0],
      protocol_v1::kAdcTriggerEffectiveDelays[1],
      protocol_v1::kAdcTriggerPhaseIpgCycles};
  for (std::size_t index = 0U;
       index < sizeof(fixed16_offsets) / sizeof(fixed16_offsets[0]); ++index) {
    if (!loadU16(payload, base + fixed16_offsets[index], value16) ||
        value16 != fixed16_expected[index]) {
      return badPayload();
    }
  }

  std::uint32_t completion0 = 0U;
  std::uint32_t completion1 = 0U;
  std::uint32_t completion_delta = 0U;
  std::uint32_t diagnostic_elapsed = 0U;
  // The wait loop itself has independent cycle and poll ceilings. Preserve a
  // small observed deadline overshoot here so failure telemetry remains
  // encodable after interrupt/preemption or the terminal DWT read.
  if (!loadU32(payload, base + kCompletionCounts, completion0) ||
      !loadU32(payload, base + kCompletionCounts + 4U, completion1) ||
      !loadU32(payload, base + kCompletionDelta, completion_delta) ||
      !loadU32(payload, base + kDiagnosticElapsed, diagnostic_elapsed)) {
    return badPayload();
  }
  (void)diagnostic_elapsed;
  const std::uint16_t timing_valid = static_cast<std::uint16_t>(
      protocol_v1::AdcTriggerConfigurationFlag::kCompletionTimingValid);
  const std::uint16_t arm_exercised = static_cast<std::uint16_t>(
      protocol_v1::AdcTriggerConfigurationFlag::kArmSequenceExercised);
  const std::uint16_t stopped = static_cast<std::uint16_t>(
      protocol_v1::AdcTriggerConfigurationFlag::kStoppedAfterDiagnostic);
  if ((flags & timing_valid) != 0U &&
      (errors != 0U || completion0 == 0U || completion1 == 0U ||
       (flags & arm_exercised) == 0U || (flags & stopped) == 0U ||
       absoluteDifference(completion_delta,
                          input_experiment::scaleDwt(protocol_v1::kAdcCompletionExpectedDwtCycles)) >
           input_experiment::scaleDwt(protocol_v1::kAdcCompletionToleranceDwtCycles))) {
    return badPayload();
  }
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.adc_trigger_metadata_encoding")
void encodeAdcTriggerMetadata(MutableByteView payload, std::size_t base,
                              const AdcTriggerMetadata &trigger) {
  using namespace adc_trigger_wire;
  storeU16(payload, base + kConfigurationFlags,
           trigger.configuration_flags);
  storeU32(payload, base + kErrorFlags, trigger.error_flags);
  storeU32(payload, base + kPitClockHz, trigger.pit_clock_hz);
  storeU32(payload, base + kDwtClockHz, trigger.dwt_clock_hz);
  storeU32(payload, base + kGpioMasterRateHz,
           trigger.gpio_master_rate_hz);
  storeU32(payload, base + kPairRateHz, trigger.pair_rate_hz);
  storeU32(payload, base + kIpgClockHz, trigger.ipg_clock_hz);
  payload.data[base + kGpioMasterPitChannel] =
      trigger.gpio_master_pit_channel;
  payload.data[base + kPairPitChannel] = trigger.pair_pit_channel;
  payload.data[base + kGpioMasterPitLoad] = trigger.gpio_master_pit_load;
  payload.data[base + kPairPitLoad] = trigger.pair_pit_load;
  payload.data[base + kPredivider] = trigger.predivider;
  payload.data[base + kChainLength] = trigger.chain_length;
  for (std::size_t index = 0U; index < 2U; ++index) {
    payload.data[base + kXbarInputs + index] = trigger.xbar_inputs[index];
    payload.data[base + kXbarOutputs + index] = trigger.xbar_outputs[index];
    payload.data[base + kTriggerQueues + index] =
        trigger.trigger_queues[index];
    storeU16(payload, base + kInitialDelays + index * 2U,
             trigger.initial_delays[index]);
    storeU16(payload, base + kEffectiveDelays + index * 2U,
             trigger.effective_delays[index]);
    storeU32(payload, base + kTriggerCtrl + index * 4U,
             trigger.evidence.trigger_ctrl_configured[index]);
    storeU32(payload, base + kTriggerCounter + index * 4U,
             trigger.evidence.trigger_counter_configured[index]);
    storeU32(payload, base + kChain + index * 4U,
             trigger.evidence.chain_configured[index]);
    storeU32(payload, base + kCompletionCounts + index * 4U,
             trigger.completion_counts[index]);
    storeU16(payload, base + kXbarSelections + index * 2U,
             trigger.evidence.xbar_sel_configured[index]);
  }
  storeU16(payload, base + kPhaseIpgCycles, trigger.phase_ipg_cycles);
  storeU32(payload, base + kCcmCscmr1,
           trigger.evidence.ccm_cscmr1_configured);
  storeU32(payload, base + kCcmCcgr1,
           trigger.evidence.ccm_ccgr1_configured);
  storeU32(payload, base + kCcmCcgr2,
           trigger.evidence.ccm_ccgr2_configured);
  storeU32(payload, base + kPitMcr,
           trigger.evidence.pit_mcr_configured);
  storeU32(payload, base + kMasterTctrl,
           trigger.evidence.gpio_master_tctrl_configured);
  storeU32(payload, base + kPairTctrl,
           trigger.evidence.pair_tctrl_configured);
  storeU32(payload, base + kAdcEtcCtrl,
           trigger.evidence.adc_etc_ctrl_configured);
  storeU32(payload, base + kDone0_1Irq,
           trigger.evidence.done0_1_irq_final);
  storeU32(payload, base + kDone2ErrIrq,
           trigger.evidence.done2_err_irq_final);
  storeU32(payload, base + kCompletionDelta,
           trigger.completion_delta_cycles);
  storeU32(payload, base + kCompletionExpected,
           trigger.completion_expected_delta_cycles);
  storeU32(payload, base + kCompletionTolerance,
           trigger.completion_tolerance_cycles);
  storeU32(payload, base + kDiagnosticElapsed,
           trigger.diagnostic_elapsed_cycles);
  storeU32(payload, base + kTriggerErrorCount,
           trigger.trigger_error_count);
}

Result validateInfo(ByteView payload) {
  if (payload.data[protocol_v1::kInfoResponseReserved0Offset] != 0U ||
      payload.data[protocol_v1::kInfoResponseReserved2Offset] != 0U ||
      payload.data[protocol_v1::kInfoResponseReserved4Offset] != 0U ||
      !isKnownState(payload.data[protocol_v1::kInfoResponseDeviceStateOffset]) ||
      payload.data[protocol_v1::kInfoResponseDeviceStateOffset] ==
          static_cast<std::uint8_t>(protocol_v1::DeviceState::kBoot) ||
      payload.data[protocol_v1::kInfoResponseProtocolVersionOffset] !=
          protocol_v1::kProtocolVersion ||
      payload.data[protocol_v1::kInfoResponseSupportedStreamMaskOffset] &
          static_cast<std::uint8_t>(~kValidStreamMask) ||
      payload.data[protocol_v1::kInfoResponseSupportedSourceMaskOffset] == 0U ||
      payload.data[protocol_v1::kInfoResponseSupportedSourceMaskOffset] & 0xFCU ||
      payload.data[protocol_v1::kInfoResponseGpioPinCountOffset] !=
          protocol_v1::kInfoResponseGpioPinMapCount ||
      payload.data[protocol_v1::kInfoResponseGpioPackedWidthBitsOffset] !=
          protocol_v1::kGpioPackedWidthBits ||
      payload.data[protocol_v1::kInfoResponseGpioRawRingDepthOffset] !=
          protocol_v1::kGpioRawRingDepth ||
      payload.data[protocol_v1::kInfoResponseGpioPackedRingDepthOffset] !=
          protocol_v1::kGpioPackedRingDepth ||
      payload.data[
          protocol_v1::kInfoResponseGpioCaptureDiagnosticModeOffset] >
          static_cast<std::uint8_t>(
              protocol_v1::GpioCaptureDiagnosticMode::kFixtureStimulus) ||
      payload.data[protocol_v1::kInfoResponseGpioPitChannelOffset] !=
          protocol_v1::kGpioPitChannel ||
      payload.data[protocol_v1::kInfoResponseGpioXbarInputOffset] !=
          protocol_v1::kGpioXbarInput ||
      payload.data[protocol_v1::kInfoResponseGpioXbarOutputOffset] !=
          protocol_v1::kGpioXbarOutput ||
      payload.data[protocol_v1::kInfoResponseGpioEdmaChannelOffset] !=
          protocol_v1::kGpioEdmaChannel ||
      payload.data[protocol_v1::kInfoResponseGpioDmamuxSourceOffset] !=
          protocol_v1::kGpioDmamuxSource ||
      payload.data[protocol_v1::kInfoResponseGpioEdmaPriorityOffset] !=
          protocol_v1::kGpioEdmaPriority ||
      payload.data[protocol_v1::kInfoResponseGpioXbarActiveEdgeOffset] !=
          protocol_v1::kGpioXbarActiveEdge) {
    return badPayload();
  }
  const auto data_checksum = static_cast<protocol_v1::ChecksumAlgorithm>(
      payload.data[protocol_v1::kInfoResponseDataChecksumAlgorithmOffset]);
  if (!isSupportedChecksum(data_checksum)) {
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
  const std::size_t gpio_offsets[] = {
      protocol_v1::kInfoResponseGpioRawSamplesPerBufferOffset,
      protocol_v1::kInfoResponseGpioRawRingBytesOffset,
      protocol_v1::kInfoResponseGpioPackedRingBytesOffset,
  };
  const std::uint32_t gpio_expected[] = {
      protocol_v1::kGpioRawSamplesPerBuffer,
      protocol_v1::kGpioRawRingBytes,
      protocol_v1::kGpioPackedRingBytes,
  };
  for (std::size_t index = 0U;
       index < sizeof(gpio_offsets) / sizeof(gpio_offsets[0]); ++index) {
    if (!loadU32(payload, gpio_offsets[index], value32) ||
        value32 != gpio_expected[index]) {
      return badPayload();
    }
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
  if (!loadU16(
          payload,
          protocol_v1::kInfoResponseGpioCaptureDiagnosticFlagsOffset,
          value16) ||
      (value16 & ~protocol_v1::kKnownGpioCaptureDiagnosticFlagMask) != 0U ||
      !loadU16(payload, protocol_v1::kInfoResponseGpioPacketBufferCountOffset,
               value16) ||
      value16 != protocol_v1::kGpioPacketBufferCount ||
      !loadU16(payload, protocol_v1::kInfoResponseReserved3Offset, value16) ||
      value16 != 0U) {
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
  if (!terminated) {
    return badPayload();
  }
  if (!loadU16(payload, protocol_v1::kInfoResponseReserved5Offset, value16) ||
      value16 != 0U) {
    return badPayload();
  }
  const Result adc_result = validateAdcMetadata(
      payload,
      {protocol_v1::kInfoResponseAdcResolutionBitsOffset,
       protocol_v1::kInfoResponseAdcContainerBytesOffset,
       protocol_v1::kInfoResponseAdc0CalibrationStateOffset,
       protocol_v1::kInfoResponseAdc1CalibrationStateOffset,
       protocol_v1::kInfoResponseAdcCodeMinOffset,
       protocol_v1::kInfoResponseAdcCodeMaxOffset,
       protocol_v1::kInfoResponseAdcReferenceOffset,
       protocol_v1::kInfoResponseAdcClockSourceOffset,
       protocol_v1::kInfoResponseAdcClockDividerOffset,
       protocol_v1::kInfoResponseAdcHardwareAverageCountOffset,
       protocol_v1::kInfoResponseAdcReferenceMvNominalOffset,
       protocol_v1::kInfoResponseAdcInputMinMvNominalOffset,
       protocol_v1::kInfoResponseAdcInputMaxMvNominalOffset,
       protocol_v1::kInfoResponseAdcSampleTimeAdckOffset,
       protocol_v1::kInfoResponseAdcConversionModeOffset,
       protocol_v1::kInfoResponseAdcConfigurationFlagsOffset,
       protocol_v1::kInfoResponseAdc0PinOffset,
       protocol_v1::kInfoResponseAdc1PinOffset,
       protocol_v1::kInfoResponseAdc0PeripheralOffset,
       protocol_v1::kInfoResponseAdc1PeripheralOffset,
       protocol_v1::kInfoResponseAdc0ChannelOffset,
       protocol_v1::kInfoResponseAdc1ChannelOffset,
       protocol_v1::kInfoResponseAdcIpgClockHzOffset,
       protocol_v1::kInfoResponseAdcClockHzOffset,
       protocol_v1::kInfoResponseAdcCalibrationDeadlineUsOffset,
       protocol_v1::kInfoResponseAdc0CalibrationCyclesOffset,
       protocol_v1::kInfoResponseAdc1CalibrationCyclesOffset,
       protocol_v1::kInfoResponseAdcInitializationErrorFlagsOffset});
  if (!adc_result.ok()) {
    return adc_result;
  }
  const Result trigger_result = validateAdcTriggerMetadata(
      payload, protocol_v1::kInfoResponseAdcTriggerConfigurationFlagsOffset);
  if (!trigger_result.ok()) {
    return trigger_result;
  }

  const std::uint8_t state =
      payload.data[protocol_v1::kInfoResponseDeviceStateOffset];
  const std::uint8_t applied_streams =
      payload.data[protocol_v1::kInfoResponseAppliedStreamMaskOffset];
  const std::uint8_t applied_source =
      payload.data[protocol_v1::kInfoResponseAppliedSourceOffset];
  if ((applied_streams & static_cast<std::uint8_t>(~kValidStreamMask)) != 0U ||
      !isKnownSource(applied_source) ||
      (state == static_cast<std::uint8_t>(protocol_v1::DeviceState::kIdle) &&
       applied_streams != 0U)) {
    return badPayload();
  }

  std::uint16_t profile_mask = 0U;
  const std::uint8_t supported_streams =
      payload.data[protocol_v1::kInfoResponseSupportedStreamMaskOffset];
  if (!loadU16(payload,
               protocol_v1::kInfoResponseSupportedConfigurationMaskOffset,
               profile_mask) ||
      (profile_mask & ~protocol_v1::kKnownConfigurationProfileMask) != 0U ||
      ((supported_streams == 0U) != (profile_mask == 0U))) {
    return badPayload();
  }
  const std::uint8_t supported_sources =
      payload.data[protocol_v1::kInfoResponseSupportedSourceMaskOffset];
  const std::uint8_t applied_source_bit =
      static_cast<std::uint8_t>(1U << applied_source);
  const std::uint16_t applied_profile =
      configurationProfileBit(applied_source, applied_streams);
  if ((supported_sources & applied_source_bit) == 0U ||
      (state != static_cast<std::uint8_t>(protocol_v1::DeviceState::kIdle) &&
       ((supported_streams == 0U &&
         (applied_streams != 0U ||
          applied_source != static_cast<std::uint8_t>(
                                protocol_v1::Source::kHardware))) ||
        (supported_streams != 0U &&
         (applied_profile == 0U ||
          (profile_mask & applied_profile) == 0U))))) {
    return badPayload();
  }

  const std::size_t combined_u16_offsets[] = {
      protocol_v1::kInfoResponseDataPayloadBytesOffset,
      protocol_v1::kInfoResponseAdcPairsPerFrameOffset,
      protocol_v1::kInfoResponseGpioSamplesPerFrameOffset,
      protocol_v1::kInfoResponseAdcPairsPerBufferOffset,
      protocol_v1::kInfoResponsePacketBufferCountOffset,
      protocol_v1::kInfoResponsePacketPrimaryCountOffset,
      protocol_v1::kInfoResponsePacketReserveCountOffset,
      protocol_v1::kInfoResponsePacketReadyQueueCapacityOffset,
      protocol_v1::kInfoResponsePacketTransmitQueueCapacityOffset,
  };
  const std::uint16_t combined_u16_expected[] = {
      static_cast<std::uint16_t>(protocol_v1::kDataPayloadBytes),
      protocol_v1::kAdcPairsPerFrame,
      protocol_v1::kGpioSamplesPerFrame,
      protocol_v1::kAdcPairsPerBuffer,
      protocol_v1::kPacketBufferCount,
      protocol_v1::kPacketPrimaryCount,
      protocol_v1::kPacketReserveCount,
      protocol_v1::kPacketReadyQueueCapacity,
      protocol_v1::kPacketTransmitQueueCapacity,
  };
  for (std::size_t index = 0U;
       index < sizeof(combined_u16_offsets) / sizeof(combined_u16_offsets[0]);
       ++index) {
    if (!loadU16(payload, combined_u16_offsets[index], value16) ||
        value16 != combined_u16_expected[index]) {
      return badPayload();
    }
  }
  if (!loadU16(payload, protocol_v1::kInfoResponseReserved8Offset, value16) ||
      value16 != 0U) {
    return badPayload();
  }

  const std::size_t combined_u32_offsets[] = {
      protocol_v1::kInfoResponseFrameCoverageTicksOffset,
      protocol_v1::kInfoResponseAdcDmaRingBytesOffset,
      protocol_v1::kInfoResponseNominalPayloadBytesPerSecondPerStreamOffset,
      protocol_v1::kInfoResponseNominalFramedBytesPerSecondPerStreamOffset,
  };
  const std::uint32_t combined_u32_expected[] = {
      protocol_v1::kFrameCoverageTicks,
      protocol_v1::kAdcDmaRingBytes,
      protocol_v1::kNominalPayloadBytesPerSecondPerStream,
      protocol_v1::kNominalFramedBytesPerSecondPerStream,
  };
  for (std::size_t index = 0U;
       index < sizeof(combined_u32_offsets) / sizeof(combined_u32_offsets[0]);
       ++index) {
    if (!loadU32(payload, combined_u32_offsets[index], value32) ||
        value32 != combined_u32_expected[index]) {
      return badPayload();
    }
  }

  if (payload.data[protocol_v1::kInfoResponseAdcDmaRingDepthOffset] !=
          protocol_v1::kAdcDmaRingDepth ||
      payload.data[protocol_v1::kInfoResponseAdcPairBytesOffset] !=
          protocol_v1::kAdcPairBytes ||
      payload.data[protocol_v1::kInfoResponseAdcDmaIrqPriorityOffset] !=
          protocol_v1::kAdcDmaIrqPriority ||
      payload.data[protocol_v1::kInfoResponseGpioDmaIrqPriorityOffset] !=
          protocol_v1::kGpioDmaIrqPriority ||
      payload.data[protocol_v1::kInfoResponseCommandQueueCapacityOffset] !=
          protocol_v1::kCommandQueueCapacity ||
      payload.data[protocol_v1::kInfoResponseResponseQueueCapacityOffset] !=
          protocol_v1::kResponseQueueCapacity) {
    return badPayload();
  }
  for (std::size_t index = 0U; index < 2U; ++index) {
    if (payload.data[protocol_v1::kInfoResponseAdcEdmaChannelsOffset + index] !=
            protocol_v1::kAdcEdmaChannels[index] ||
        payload.data[protocol_v1::kInfoResponseAdcEdmaPrioritiesOffset + index] !=
            protocol_v1::kAdcEdmaPriorities[index] ||
        payload.data[protocol_v1::kInfoResponseAdcDmamuxSourcesOffset + index] !=
            protocol_v1::kAdcDmamuxSources[index]) {
      return badPayload();
    }
  }
  return Result::success();
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
      !isSupportedChecksum(
          static_cast<protocol_v1::ChecksumAlgorithm>(checksum))) {
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
  std::uint16_t depth = 0U;
  if (!loadU16(
          payload,
          protocol_v1::kStatusResponseGpioProcessingCpuBasisPointsOffset,
          depth) ||
      depth > 10000U ||
      !loadU16(payload, protocol_v1::kStatusResponseGpioRawReadyDepthOffset,
               depth) ||
      depth > protocol_v1::kGpioRawRingDepth ||
      !loadU16(
          payload,
          protocol_v1::kStatusResponseGpioRawReadyHighWaterOffset, depth) ||
      depth > protocol_v1::kGpioRawRingDepth ||
      !loadU16(payload,
               protocol_v1::kStatusResponseGpioPackedReadyDepthOffset,
               depth) ||
      depth > protocol_v1::kGpioPackedRingDepth ||
      !loadU16(
          payload,
          protocol_v1::kStatusResponseGpioPackedReadyHighWaterOffset,
          depth) ||
      depth > protocol_v1::kGpioPackedRingDepth ||
      !loadU16(payload, protocol_v1::kStatusResponsePacketReadyDepthOffset,
               depth) ||
      depth > protocol_v1::kGpioPacketBufferCount ||
      !loadU16(payload,
               protocol_v1::kStatusResponsePacketTransmitDepthOffset,
               depth) ||
      depth > protocol_v1::kGpioPacketBufferCount ||
      !loadU16(payload,
               protocol_v1::kStatusResponsePacketOwnedHighWaterOffset,
               depth) ||
      depth > protocol_v1::kGpioPacketBufferCount) {
    return badPayload();
  }
  const std::size_t packet_depth_offsets[] = {
      protocol_v1::kStatusResponseAdcPacketReadyDepthOffset,
      protocol_v1::kStatusResponseGpioPacketReadyDepthOffset,
      protocol_v1::kStatusResponseAdcPacketTransmitDepthOffset,
      protocol_v1::kStatusResponseGpioPacketTransmitDepthOffset,
      protocol_v1::kStatusResponseAdcPacketReadyHighWaterOffset,
      protocol_v1::kStatusResponseGpioPacketReadyHighWaterOffset,
      protocol_v1::kStatusResponseAdcPacketTransmitHighWaterOffset,
      protocol_v1::kStatusResponseGpioPacketTransmitHighWaterOffset,
      protocol_v1::kStatusResponsePacketReadyHighWaterOffset,
      protocol_v1::kStatusResponsePacketTransmitHighWaterOffset,
      protocol_v1::kStatusResponseUsbLowerPriorityQueueDepthOffset,
      protocol_v1::kStatusResponsePacketOwnedDepthOffset,
      protocol_v1::kStatusResponseAdcPacketFillingDepthOffset,
      protocol_v1::kStatusResponseGpioPacketFillingDepthOffset,
  };
  for (std::size_t index = 0U;
       index < sizeof(packet_depth_offsets) / sizeof(packet_depth_offsets[0]);
       ++index) {
    if (!loadU16(payload, packet_depth_offsets[index], depth) ||
        depth > protocol_v1::kPacketBufferCount) {
      return badPayload();
    }
  }
  if (!loadU16(payload,
               protocol_v1::kStatusResponseUsbCommandQueueDepthOffset,
               depth) ||
      depth > protocol_v1::kCommandQueueCapacity ||
      !loadU16(payload,
               protocol_v1::kStatusResponseUsbCommandQueueHighWaterOffset,
               depth) ||
      depth > protocol_v1::kCommandQueueCapacity ||
      !loadU16(payload,
               protocol_v1::kStatusResponseUsbResponseQueueDepthOffset,
               depth) ||
      depth > protocol_v1::kResponseQueueCapacity ||
      !loadU16(payload,
               protocol_v1::kStatusResponseUsbResponseQueueHighWaterOffset,
               depth) ||
      depth > protocol_v1::kResponseQueueCapacity ||
      !loadU16(payload,
               protocol_v1::kStatusResponseUsbActiveFrameBytesSentOffset,
               depth) ||
      depth > protocol_v1::kDataFrameBytes) {
    return badPayload();
  }
  std::uint16_t active_bytes_sent = 0U;
  std::uint16_t active_frame_size = 0U;
  if (!loadU16(payload,
               protocol_v1::kStatusResponseUsbActiveFrameBytesSentOffset,
               active_bytes_sent) ||
      !loadU16(payload,
               protocol_v1::kStatusResponseUsbActiveFrameSizeOffset,
               active_frame_size) ||
      active_frame_size > protocol_v1::kDataFrameBytes ||
      active_bytes_sent > active_frame_size) {
    return badPayload();
  }
  const Result adc_result = validateAdcMetadata(
      payload,
      {protocol_v1::kStatusResponseAdcResolutionBitsOffset,
       protocol_v1::kStatusResponseAdcContainerBytesOffset,
       protocol_v1::kStatusResponseAdc0CalibrationStateOffset,
       protocol_v1::kStatusResponseAdc1CalibrationStateOffset,
       protocol_v1::kStatusResponseAdcCodeMinOffset,
       protocol_v1::kStatusResponseAdcCodeMaxOffset,
       protocol_v1::kStatusResponseAdcReferenceOffset,
       protocol_v1::kStatusResponseAdcClockSourceOffset,
       protocol_v1::kStatusResponseAdcClockDividerOffset,
       protocol_v1::kStatusResponseAdcHardwareAverageCountOffset,
       protocol_v1::kStatusResponseAdcReferenceMvNominalOffset,
       protocol_v1::kStatusResponseAdcInputMinMvNominalOffset,
       protocol_v1::kStatusResponseAdcInputMaxMvNominalOffset,
       protocol_v1::kStatusResponseAdcSampleTimeAdckOffset,
       protocol_v1::kStatusResponseAdcConversionModeOffset,
       protocol_v1::kStatusResponseAdcConfigurationFlagsOffset,
       protocol_v1::kStatusResponseAdc0PinOffset,
       protocol_v1::kStatusResponseAdc1PinOffset,
       protocol_v1::kStatusResponseAdc0PeripheralOffset,
       protocol_v1::kStatusResponseAdc1PeripheralOffset,
       protocol_v1::kStatusResponseAdc0ChannelOffset,
       protocol_v1::kStatusResponseAdc1ChannelOffset,
       protocol_v1::kStatusResponseAdcIpgClockHzOffset,
       protocol_v1::kStatusResponseAdcClockHzOffset,
       protocol_v1::kStatusResponseAdcCalibrationDeadlineUsOffset,
       protocol_v1::kStatusResponseAdc0CalibrationCyclesOffset,
       protocol_v1::kStatusResponseAdc1CalibrationCyclesOffset,
       protocol_v1::kStatusResponseAdcInitializationErrorFlagsOffset});
  if (!adc_result.ok()) {
    return adc_result;
  }
  return validateAdcTriggerMetadata(
      payload,
      protocol_v1::kStatusResponseAdcTriggerConfigurationFlagsOffset);
}

Result decodeChecksumBenchmarkRequest(ByteView payload,
                                      ChecksumBenchmarkRequest &request) {
  if (payload.size != protocol_v1::kChecksumBenchmarkRequestPayloadSize) {
    return badLength();
  }
  ChecksumBenchmarkRequest decoded{};
  decoded.checksum_algorithm =
      static_cast<protocol_v1::ChecksumAlgorithm>(payload.data[
          protocol_v1::kChecksumBenchmarkRequestChecksumAlgorithmOffset]);
  decoded.vector = static_cast<protocol_v1::BenchmarkVector>(
      payload.data[protocol_v1::kChecksumBenchmarkRequestVectorOffset]);
  decoded.memory_region = static_cast<protocol_v1::BenchmarkMemoryRegion>(
      payload.data[protocol_v1::kChecksumBenchmarkRequestMemoryRegionOffset]);
  decoded.cache_state = static_cast<protocol_v1::BenchmarkCacheState>(
      payload.data[protocol_v1::kChecksumBenchmarkRequestCacheStateOffset]);
  if (!loadU16(payload, protocol_v1::kChecksumBenchmarkRequestBatchCountOffset,
               decoded.batch_count) ||
      !loadU16(
          payload,
          protocol_v1::kChecksumBenchmarkRequestIterationsPerBatchOffset,
          decoded.iterations_per_batch)) {
    return badLength();
  }
  if (!isKnownChecksum(decoded.checksum_algorithm) ||
      !isSupportedChecksum(decoded.checksum_algorithm)) {
    return unsupportedChecksum();
  }
  if (!validChecksumBenchmarkRequest(decoded)) {
    return badPayload();
  }
  request = decoded;
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.gpio_clock_diagnostic_request")
Result decodeGpioClockDiagnosticRequest(
    ByteView payload, GpioClockDiagnosticRequest &request) {
  if (payload.size != protocol_v1::kGpioClockDiagnosticRequestPayloadSize) {
    return badLength();
  }
  GpioClockDiagnosticRequest decoded{};
  std::uint16_t reserved = 1U;
  if (!loadU32(payload,
               protocol_v1::kGpioClockDiagnosticRequestRateHzOffset,
               decoded.rate_hz) ||
      !loadU16(payload,
               protocol_v1::kGpioClockDiagnosticRequestEventCountOffset,
               decoded.event_count) ||
      !loadU16(payload,
               protocol_v1::kGpioClockDiagnosticRequestReservedOffset,
               reserved)) {
    return badLength();
  }
  if (reserved != 0U || !validGpioClockDiagnosticRequest(decoded)) {
    return badPayload();
  }
  request = decoded;
  return Result::success();
}

Result validateChecksumBenchmarkResponse(ByteView payload) {
  ChecksumBenchmarkResponse decoded{};
  decoded.request.checksum_algorithm =
      static_cast<protocol_v1::ChecksumAlgorithm>(payload.data[
          protocol_v1::kChecksumBenchmarkResponseChecksumAlgorithmOffset]);
  decoded.request.vector = static_cast<protocol_v1::BenchmarkVector>(
      payload.data[protocol_v1::kChecksumBenchmarkResponseVectorOffset]);
  decoded.request.memory_region =
      static_cast<protocol_v1::BenchmarkMemoryRegion>(payload.data[
          protocol_v1::kChecksumBenchmarkResponseMemoryRegionOffset]);
  decoded.request.cache_state =
      static_cast<protocol_v1::BenchmarkCacheState>(payload.data[
          protocol_v1::kChecksumBenchmarkResponseCacheStateOffset]);
  if (payload.data[protocol_v1::kChecksumBenchmarkResponseReservedOffset] != 0U ||
      !loadU16(payload,
               protocol_v1::kChecksumBenchmarkResponseBatchCountOffset,
               decoded.request.batch_count) ||
      !loadU16(
          payload,
          protocol_v1::kChecksumBenchmarkResponseIterationsPerBatchOffset,
          decoded.request.iterations_per_batch) ||
      !loadU32(payload, protocol_v1::kChecksumBenchmarkResponseBufferBytesOffset,
               decoded.buffer_bytes) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseCycleCounterHzOffset,
          decoded.cycle_counter_hz) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseTimerOverheadCyclesOffset,
          decoded.timer_overhead_cycles) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseImplementationCodeBytesOffset,
          decoded.implementation_code_bytes) ||
      !loadU32(payload, protocol_v1::kChecksumBenchmarkResponseTableBytesOffset,
               decoded.table_bytes) ||
      !loadU32(
          payload, protocol_v1::kChecksumBenchmarkResponseWorkingRamBytesOffset,
          decoded.working_ram_bytes) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseDeterministicDigestOffset,
          decoded.deterministic_digest) ||
      !loadU64(
          payload,
          protocol_v1::kChecksumBenchmarkResponseProcessedBytesOffset,
          decoded.processed_bytes) ||
      !loadU64(
          payload,
          protocol_v1::kChecksumBenchmarkResponseRawChecksumCyclesOffset,
          decoded.raw_checksum_cycles) ||
      !loadU64(
          payload,
          protocol_v1::kChecksumBenchmarkResponseNetChecksumCyclesOffset,
          decoded.net_checksum_cycles) ||
      !loadU64(
          payload,
          protocol_v1::kChecksumBenchmarkResponseCacheSetupCyclesOffset,
          decoded.cache_setup_cycles) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseMinBatchCyclesOffset,
          decoded.min_batch_cycles) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseMaxBatchCyclesOffset,
          decoded.max_batch_cycles) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseCyclesPerByteQ16Offset,
          decoded.cycles_per_byte_q16) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseMbPerSecondQ16Offset,
          decoded.mb_per_second_q16) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseProjectedCpuPercentQ16Offset,
          decoded.projected_cpu_percent_q16) ||
      !loadU32(
          payload,
          protocol_v1::kChecksumBenchmarkResponseTargetFramedBytesPerSecondOffset,
          decoded.target_framed_bytes_per_second)) {
    return badLength();
  }

  const std::uint32_t observed_buffer_bytes = decoded.buffer_bytes;
  const std::uint32_t observed_cycles_per_byte = decoded.cycles_per_byte_q16;
  const std::uint32_t observed_mb_per_second = decoded.mb_per_second_q16;
  const std::uint32_t observed_projected_cpu =
      decoded.projected_cpu_percent_q16;
  const std::uint64_t observed_processed = decoded.processed_bytes;
  const std::uint32_t observed_target_rate =
      decoded.target_framed_bytes_per_second;
  std::uint32_t expected_table_bytes = 0U;
  switch (decoded.request.checksum_algorithm) {
    case protocol_v1::ChecksumAlgorithm::kAdler32:
      expected_table_bytes = 0U;
      break;
    case protocol_v1::ChecksumAlgorithm::kCrc32c:
    case protocol_v1::ChecksumAlgorithm::kCrc32IsoHdlc:
      expected_table_bytes =
          static_cast<std::uint32_t>(checksum::kCrcTableBytes);
      break;
    case protocol_v1::ChecksumAlgorithm::kNoneReserved:
      return badPayload();
  }
  const std::uint64_t operations =
      static_cast<std::uint64_t>(decoded.request.batch_count) *
      decoded.request.iterations_per_batch;
  const std::uint64_t calibrated_overhead =
      operations * decoded.timer_overhead_cycles;
  const std::uint64_t minimum_total =
      static_cast<std::uint64_t>(decoded.min_batch_cycles) *
      decoded.request.batch_count;
  const std::uint64_t maximum_total =
      static_cast<std::uint64_t>(decoded.max_batch_cycles) *
      decoded.request.batch_count;
  if (!isKnownChecksum(decoded.request.checksum_algorithm) ||
      !isSupportedChecksum(decoded.request.checksum_algorithm) ||
      decoded.cycle_counter_hz !=
          input_experiment::kCpuHz ||
      decoded.target_framed_bytes_per_second !=
          protocol_v1::kChecksumBenchmarkTargetFramedBytesPerSecond ||
      decoded.implementation_code_bytes == 0U ||
      decoded.table_bytes != expected_table_bytes ||
      decoded.working_ram_bytes != 2U * protocol_v1::kDataFrameBytes ||
      decoded.raw_checksum_cycles < calibrated_overhead ||
      decoded.raw_checksum_cycles - calibrated_overhead !=
          decoded.net_checksum_cycles ||
      decoded.net_checksum_cycles > decoded.raw_checksum_cycles ||
      decoded.min_batch_cycles > decoded.max_batch_cycles ||
      decoded.net_checksum_cycles < minimum_total ||
      decoded.net_checksum_cycles > maximum_total ||
      (decoded.request.cache_state !=
           protocol_v1::BenchmarkCacheState::kColdInvalidated &&
       decoded.cache_setup_cycles != 0U)) {
    return badPayload();
  }
  if (!populateChecksumBenchmarkMetrics(decoded) ||
      decoded.buffer_bytes != observed_buffer_bytes ||
      decoded.processed_bytes != observed_processed ||
      decoded.cycles_per_byte_q16 != observed_cycles_per_byte ||
      decoded.mb_per_second_q16 != observed_mb_per_second ||
      decoded.projected_cpu_percent_q16 != observed_projected_cpu ||
      decoded.target_framed_bytes_per_second != observed_target_rate) {
    return badPayload();
  }
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.gpio_clock_diagnostic_validation")
Result validateGpioClockDiagnosticResponse(ByteView payload) {
  GpioClockDiagnosticRequest request{};
  std::uint32_t production_rate = 0U;
  std::uint32_t pit_clock = 0U;
  std::uint32_t pit_load = 0U;
  std::uint32_t requested_events = 0U;
  std::uint32_t scheduled_events = 0U;
  std::uint32_t samples = 0U;
  std::uint32_t dwt_hz = 0U;
  std::uint32_t elapsed_cycles = 0U;
  std::uint32_t error_flags = 0U;
  std::uint16_t citer = 0U;
  std::uint16_t biter = 0U;
  if (!loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponseConfiguredRateHzOffset,
               request.rate_hz) ||
      !loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponseProductionRateHzOffset,
               production_rate) ||
      !loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponsePitClockHzOffset,
               pit_clock) ||
      !loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponsePitLoadValueOffset,
               pit_load) ||
      !loadU32(
          payload,
          protocol_v1::kGpioClockDiagnosticResponseRequestedEventCountOffset,
          requested_events) ||
      !loadU32(
          payload,
          protocol_v1::kGpioClockDiagnosticResponseScheduledEventCountOffset,
          scheduled_events) ||
      !loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponseDmaSampleCountOffset,
               samples) ||
      !loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponseDwtCounterHzOffset,
               dwt_hz) ||
      !loadU32(payload,
               protocol_v1::kGpioClockDiagnosticResponseDwtElapsedCyclesOffset,
               elapsed_cycles) ||
      !loadU32(
          payload,
          protocol_v1::kGpioClockDiagnosticResponseHardwareErrorFlagsOffset,
          error_flags) ||
      !loadU16(payload,
               protocol_v1::kGpioClockDiagnosticResponseTcdCiterFinalOffset,
               citer) ||
      !loadU16(payload,
               protocol_v1::kGpioClockDiagnosticResponseTcdBiterOffset,
               biter)) {
    return badLength();
  }
  if (requested_events > std::numeric_limits<std::uint16_t>::max()) {
    return badPayload();
  }
  request.event_count = static_cast<std::uint16_t>(requested_events);
  const std::uint32_t expected_major_count =
      2U * requested_events + protocol_v1::kGpioClockDuplicateGuardEvents;
  const std::uint32_t unarmed_error_mask =
      static_cast<std::uint32_t>(
          protocol_v1::GpioClockError::kDwtUnavailable) |
      static_cast<std::uint32_t>(
          protocol_v1::GpioClockError::kResourceBusy);
  const bool configuration_was_armed =
      (error_flags & unarmed_error_mask) == 0U;
  const std::uint32_t expected_scheduled =
      dwt_hz == input_experiment::kCpuHz && request.rate_hz != 0U
          ? static_cast<std::uint32_t>(
                static_cast<std::uint64_t>(elapsed_cycles) * request.rate_hz /
                input_experiment::kCpuHz)
          : 0U;
  if (!validGpioClockDiagnosticRequest(request) ||
      production_rate != protocol_v1::kGpioClockProductionRateHz ||
      pit_clock != protocol_v1::kGpioClockPitHz ||
      pit_load != protocol_v1::kGpioClockPitHz / request.rate_hz - 1U ||
      (error_flags & ~protocol_v1::kKnownGpioClockErrorMask) != 0U ||
      (configuration_was_armed &&
       (biter != expected_major_count || citer > biter ||
        samples != static_cast<std::uint32_t>(biter - citer))) ||
      (dwt_hz == input_experiment::kCpuHz &&
       scheduled_events != expected_scheduled) ||
      (error_flags == 0U &&
       (dwt_hz != input_experiment::kCpuHz || elapsed_cycles == 0U ||
        absoluteDifference(scheduled_events, requested_events) >
            protocol_v1::kGpioClockCountTolerance ||
        absoluteDifference(samples, scheduled_events) >
            protocol_v1::kGpioClockCountTolerance))) {
    return badPayload();
  }
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.gpio_capture_diagnostic_validation")
Result validateGpioCaptureDiagnosticResponse(ByteView payload) {
  std::uint16_t reserved = 1U;
  std::uint32_t errors = 0U;
  std::uint32_t flags = 0U;
  std::uint64_t captured = 0U;
  std::uint32_t retained = 0U;
  std::uint32_t analyzed = 0U;
  std::uint32_t limit = 0U;
  if (payload.data[
          protocol_v1::kGpioCaptureDiagnosticResponseModeOffset] >
          static_cast<std::uint8_t>(
              protocol_v1::GpioCaptureDiagnosticMode::kFixtureStimulus) ||
      payload.data[
          protocol_v1::kGpioCaptureDiagnosticResponseMetadataKindOffset] >
          2U ||
      payload.data[
          protocol_v1::kGpioCaptureDiagnosticResponseDriveSafetyOffset] >
          2U ||
      payload.data[
          protocol_v1::kGpioCaptureDiagnosticResponseStimulusKindOffset] >
          2U ||
      payload.data[
          protocol_v1::kGpioCaptureDiagnosticResponseReserved2Offset] != 0U ||
      !loadU16(payload,
               protocol_v1::kGpioCaptureDiagnosticResponseReserved1Offset,
               reserved) ||
      reserved != 0U ||
      !loadU32(
          payload,
          protocol_v1::kGpioCaptureDiagnosticResponseHardwareErrorFlagsOffset,
          errors) ||
      (errors & ~protocol_v1::kKnownGpioCaptureErrorMask) != 0U ||
      !loadU32(
          payload,
          protocol_v1::kGpioCaptureDiagnosticResponseDiagnosticFlagsOffset,
          flags) ||
      (flags & ~protocol_v1::kKnownGpioCaptureDiagnosticFlagMask) != 0U ||
      (flags & static_cast<std::uint32_t>(
                   protocol_v1::GpioCaptureDiagnosticFlag::kAvailable)) ==
          0U ||
      !loadU64(
          payload,
          protocol_v1::kGpioCaptureDiagnosticResponseDmaSamplesCapturedOffset,
          captured) ||
      !loadU32(
          payload,
          protocol_v1::kGpioCaptureDiagnosticResponseCompleteSamplesRetainedOffset,
          retained) ||
      !loadU32(
          payload,
          protocol_v1::kGpioCaptureDiagnosticResponseSamplesAnalyzedOffset,
          analyzed) ||
      !loadU32(
          payload,
          protocol_v1::kGpioCaptureDiagnosticResponseAnalysisSampleLimitOffset,
          limit) ||
      retained > captured || analyzed > retained || analyzed > limit ||
      limit == 0U || limit > protocol_v1::kGpioSamplesPerFrame) {
    return badPayload();
  }
  const std::uint32_t output_permitted = static_cast<std::uint32_t>(
      protocol_v1::GpioCaptureDiagnosticFlag::kOutputDrivePermitted);
  const std::uint32_t output_exercised = static_cast<std::uint32_t>(
      protocol_v1::GpioCaptureDiagnosticFlag::kOutputDriveExercised);
  return (flags & output_exercised) != 0U &&
                 (flags & output_permitted) == 0U
             ? badPayload()
             : Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.payload_validation")
Result validateInfoV2(ByteView payload) {
  std::uint32_t value32 = 0U;
  if (payload.size != protocol_v2::kInfoResponsePayloadSize ||
      payload.data[protocol_v2::kInfoResponseProtocolVersionOffset] !=
          protocol_v2::kProtocolVersion ||
      payload.data[protocol_v2::kInfoResponseSupportedRateProfileMaskOffset] !=
          (input_experiment::kReleaseFixed1MHz ? 16U : protocol_v2::kSupportedRateProfileMask) ||
      payload.data[
          protocol_v2::kInfoResponseSupportedAuxBankModeMaskOffset] !=
          protocol_v2::kSupportedAuxBankModeMask ||
      payload.data[protocol_v2::kInfoResponseSelectedRateProfileOffset] >=
          rate_profile::kCount ||
      payload.data[protocol_v2::kInfoResponseAppliedAuxBankModeOffset] > 1U ||
      payload.data[protocol_v2::kInfoResponseGpioItemBytesOffset] !=
          (payload.data[protocol_v2::kInfoResponseAppliedAuxBankModeOffset] ==
                   static_cast<std::uint8_t>(protocol_v2::AuxBankMode::kInput)
               ? 2U
               : 1U) ||
      payload.data[protocol_v2::kInfoResponseAuxGpioPinCountOffset] != 8U ||
      payload.data[protocol_v2::kInfoResponseRateProfileCountOffset] !=
          rate_profile::kCount ||
      payload.data[protocol_v2::kInfoResponseReserved9Offset] != 0U ||
      payload.data[protocol_v2::kInfoResponseReserved10Offset] != 0U ||
      payload.data[protocol_v2::kInfoResponseReserved11Offset] != 0U ||
      !loadU32(payload,
               protocol_v2::kInfoResponseMaxControlFrameBytesOffset,
               value32) ||
      value32 != protocol_v2::kMaxControlFrameBytes) {
    return badPayload();
  }
  for (std::size_t index = 0U; index < 8U; ++index) {
    if (payload.data[protocol_v2::kInfoResponseAuxGpioPinMapOffset + index] !=
            protocol_v2::kAuxGpioPinsByBit[index] ||
        payload.data[protocol_v2::kInfoResponseAuxGpioPortBitsOffset + index] !=
            protocol_v2::kAuxGpioPortBitsByWireBit[index]) {
      return badPayload();
    }
  }
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.payload_validation")
Result validateStatusV2(ByteView payload) {
  if (payload.size != protocol_v2::kStatusResponsePayloadSize ||
      payload.data[protocol_v2::kStatusResponseProtocolVersionOffset] !=
          protocol_v2::kProtocolVersion ||
      payload.data[protocol_v2::kStatusResponseAuxBankModeOffset] > 1U ||
      payload.data[protocol_v2::kStatusResponseRateProfileOffset] >=
          rate_profile::kCount ||
      payload.data[protocol_v2::kStatusResponseGpioItemBytesOffset] !=
          (payload.data[protocol_v2::kStatusResponseAuxBankModeOffset] == 1U
               ? 2U
               : 1U)) {
    return badPayload();
  }
  std::uint32_t reserved = 1U;
  return loadU32(payload, protocol_v2::kStatusResponseReserved4Offset,
                 reserved) && reserved == 0U
             ? Result::success()
             : badPayload();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.payload_validation")
Result validateGpioCaptureDiagnosticResponseV2(ByteView payload) {
  if (payload.size !=
          protocol_v2::kGpioCaptureDiagnosticResponsePayloadSize ||
      payload.data[
          protocol_v2::kGpioCaptureDiagnosticResponseBankCountOffset] > 2U ||
      payload.data[
          protocol_v2::kGpioCaptureDiagnosticResponseAuxBankModeOffset] > 1U ||
      payload.data[protocol_v2::
                       kGpioCaptureDiagnosticResponseSelectedRateProfileOffset] >=
          rate_profile::kCount ||
      payload.data[protocol_v2::
                       kGpioCaptureDiagnosticResponseAuxElectricallyUnstimulatedOffset] >
          1U ||
      payload.data[protocol_v2::
                       kGpioCaptureDiagnosticResponseAuxExternalTransitionChecksRunOffset] >
          1U ||
      payload.data[protocol_v2::kGpioCaptureDiagnosticResponseReserved3Offset] !=
          0U ||
      payload.data[protocol_v2::kGpioCaptureDiagnosticResponseReserved5Offset] !=
          0U) {
    return badPayload();
  }
  std::uint16_t reserved = 1U;
  return loadU16(payload,
                 protocol_v2::kGpioCaptureDiagnosticResponseReserved4Offset,
                 reserved) && reserved == 0U
             ? Result::success()
             : badPayload();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.payload_validation")
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
    return validateConfiguration(payload, 0U, false, header.version);
  }
  if (header.kind == protocol_v1::FrameKind::kChecksumBenchmarkRequest) {
    ChecksumBenchmarkRequest request{};
    return decodeChecksumBenchmarkRequest(payload, request);
  }
  if (header.kind ==
      protocol_v1::FrameKind::kGpioClockDiagnosticRequest) {
    GpioClockDiagnosticRequest request{};
    return decodeGpioClockDiagnosticRequest(payload, request);
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

  if (header.kind == kTemperatureResponse) {
    const auto status = payload.data[4];
    std::uint32_t bits = 0;
    if (status > 4 || payload.data[5] || payload.data[6] || payload.data[7] ||
        !loadU32(payload, 8, bits)) return badPayload();
    const std::int64_t value = bits <= 0x7fffffffU ? bits
        : static_cast<std::int64_t>(bits) - 0x100000000LL;
    if ((status == 0 && (value < -40000 || value > 150000)) ||
        (status != 0 && bits != 0)) return badPayload();
    return Result::success();
  }
  switch (header.kind) {
    case protocol_v1::FrameKind::kInfoResponse:
      return header.version == protocol_v2::kProtocolVersion
                 ? validateInfoV2(payload)
                 : validateInfo(payload);
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
      return validateConfiguration(payload, 4U, true, header.version);
    case protocol_v1::FrameKind::kGetStatusResponse:
      return header.version == protocol_v2::kProtocolVersion
                 ? validateStatusV2(payload)
                 : validateStatus(payload);
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
    case protocol_v1::FrameKind::kChecksumBenchmarkResponse:
      return validateChecksumBenchmarkResponse(payload);
    case protocol_v1::FrameKind::kGpioClockDiagnosticResponse:
      return validateGpioClockDiagnosticResponse(payload);
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticResponse:
      return header.version == protocol_v2::kProtocolVersion
                 ? validateGpioCaptureDiagnosticResponseV2(payload)
                 : validateGpioCaptureDiagnosticResponse(payload);
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
  fields.version = request.protocol_version;
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.response_configuration")
void writeConfiguration(MutableByteView payload, std::size_t offset,
                        const Configuration &configuration,
                        std::uint8_t version) {
  payload.data[offset] = configuration.stream_mask;
  payload.data[offset + 1U] =
      static_cast<std::uint8_t>(configuration.source);
  payload.data[offset + 2U] =
      static_cast<std::uint8_t>(configuration.data_checksum_algorithm);
  payload.data[offset + 3U] =
      version == protocol_v2::kProtocolVersion
          ? static_cast<std::uint8_t>(configuration.aux_bank_mode)
          : 0U;
  storeU32(payload, offset + 4U, configuration.data_frame_bytes);
  if (version == protocol_v2::kProtocolVersion) {
    const protocol_v2::RateProfileTiming &timing =
        rate_profile::kTimings[
            static_cast<std::size_t>(configuration.rate_profile)];
    storeU32(payload, offset + 8U, timing.adc_pair_rate_hz);
    storeU32(payload, offset + 12U, timing.gpio_sample_rate_hz);
  }
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

bool dataFrameShapeMatchesContract(protocol_v1::FrameKind kind,
                                   const DataFrameShape &shape) {
  if (!isDataKind(kind) || shape.item_count == 0U ||
      shape.item_bytes == 0U || shape.item_period_ticks == 0U ||
      shape.payload_bytes > std::numeric_limits<std::uint32_t>::max() ||
      shape.frame_bytes > protocol_v2::kMaxDataFrameBytes) {
    return false;
  }
  const std::uint64_t payload =
      static_cast<std::uint64_t>(shape.item_count) * shape.item_bytes;
  const std::uint64_t total =
      payload + protocol_v1::kHeaderSize + protocol_v1::kTrailerSize;
  if (payload != shape.payload_bytes || total != shape.frame_bytes) {
    return false;
  }

  if (shape.protocol_version == protocol_v1::kProtocolVersion) {
    const bool adc = kind == protocol_v1::FrameKind::kAdcData;
    return shape.item_count ==
               (adc ? protocol_v1::kAdcPairsPerFrame
                    : protocol_v1::kGpioSamplesPerFrame) &&
           shape.item_bytes ==
               (adc ? protocol_v1::kAdcBytesPerPair : 1U) &&
           shape.item_period_ticks ==
               (adc ? protocol_v1::kAdcPairPeriodTicks
                    : protocol_v1::kGpioSamplePeriodTicks) &&
           shape.payload_bytes == protocol_v1::kDataPayloadBytes &&
           shape.frame_bytes == protocol_v1::kDataFrameBytes;
  }
  if (shape.protocol_version != protocol_v2::kProtocolVersion) {
    return false;
  }

  for (const protocol_v2::RateProfileTiming &timing :
       rate_profile::kTimings) {
    const bool adc = kind == protocol_v1::FrameKind::kAdcData;
    const std::uint32_t expected_period =
        adc ? timing.adc_pair_period_ticks
            : timing.gpio_sample_period_ticks;
    if (shape.item_period_ticks != expected_period) {
      continue;
    }
    const std::uint64_t coverage =
        static_cast<std::uint64_t>(shape.item_count) *
        shape.item_period_ticks;
    const std::uint32_t coverage_multiplier =
        input_experiment::kEqualRates && !adc ? 4U : 1U;
    const bool disabled =
        coverage == timing.disabled_frame_coverage_ticks * coverage_multiplier &&
        shape.item_count ==
            (adc ? protocol_v2::kDisabledAdcPairsPerFrame
                 : protocol_v2::kDisabledGpioSamplesPerFrame) &&
        shape.item_bytes ==
            (adc ? protocol_v2::kAdcBytesPerPair : 1U);
    const bool input =
        coverage == timing.input_frame_coverage_ticks * coverage_multiplier &&
        shape.item_count ==
            (adc ? protocol_v2::kInputAdcPairsPerFrame
                 : protocol_v2::kInputGpioSamplesPerFrame) &&
        shape.item_bytes ==
            (adc ? protocol_v2::kAdcBytesPerPair : 2U);
    if (disabled || input) {
      return true;
    }
  }
  return false;
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
        static_cast<std::uint8_t>(
            (static_cast<std::uint32_t>(value) >> (index * 8U)) & 0xFFU);
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
  return checksum::adler32(input.data, input.size);
}

bool validChecksumBenchmarkRequest(const ChecksumBenchmarkRequest &request) {
  if (!isSupportedChecksum(request.checksum_algorithm) ||
      request.batch_count == 0U ||
      request.batch_count > protocol_v1::kChecksumBenchmarkMaxBatchCount ||
      request.iterations_per_batch == 0U ||
      request.iterations_per_batch >
          protocol_v1::kChecksumBenchmarkMaxIterationsPerBatch) {
    return false;
  }
  switch (request.vector) {
    case protocol_v1::BenchmarkVector::kEmpty:
    case protocol_v1::BenchmarkVector::kCanonical123456789:
    case protocol_v1::BenchmarkVector::kBuffer64:
    case protocol_v1::BenchmarkVector::kBuffer512:
    case protocol_v1::BenchmarkVector::kFrameCoverage:
      break;
    default:
      return false;
  }
  switch (request.memory_region) {
    case protocol_v1::BenchmarkMemoryRegion::kDtcmPacket:
    case protocol_v1::BenchmarkMemoryRegion::kOcramDma:
      break;
    default:
      return false;
  }
  switch (request.cache_state) {
    case protocol_v1::BenchmarkCacheState::kHotOrNative:
      break;
    case protocol_v1::BenchmarkCacheState::kColdInvalidated:
      if (request.memory_region !=
              protocol_v1::BenchmarkMemoryRegion::kOcramDma ||
          request.vector == protocol_v1::BenchmarkVector::kEmpty) {
        return false;
      }
      break;
    default:
      return false;
  }

  const std::uint64_t operations =
      static_cast<std::uint64_t>(request.batch_count) *
      request.iterations_per_batch;
  const std::uint64_t processed =
      operations * static_cast<std::uint64_t>(benchmarkVectorBytes(request.vector));
  return operations <= protocol_v1::kChecksumBenchmarkMaxOperations &&
         processed <= protocol_v1::kChecksumBenchmarkMaxProcessedBytes;
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.gpio_clock_diagnostic_bounds")
bool validGpioClockDiagnosticRequest(
    const GpioClockDiagnosticRequest &request) {
  if (request.rate_hz < protocol_v1::kGpioClockMinRateHz ||
      request.rate_hz > protocol_v1::kGpioClockProductionRateHz ||
      protocol_v1::kGpioClockPitHz % request.rate_hz != 0U ||
      request.event_count < protocol_v1::kGpioClockMinEventCount ||
      request.event_count > protocol_v1::kGpioClockMaxEventCount) {
    return false;
  }
  const std::uint64_t elapsed_cycles =
      (static_cast<std::uint64_t>(request.event_count) *
       input_experiment::kCpuHz + request.rate_hz - 1U) / request.rate_hz;
  const std::uint32_t major_count =
      2U * static_cast<std::uint32_t>(request.event_count) +
      protocol_v1::kGpioClockDuplicateGuardEvents;
  return elapsed_cycles <= input_experiment::scaleDwt(protocol_v1::kGpioClockMaxElapsedCycles) &&
         major_count <= std::numeric_limits<std::int16_t>::max();
}

bool populateChecksumBenchmarkMetrics(ChecksumBenchmarkResponse &response) {
  if (!validChecksumBenchmarkRequest(response.request) ||
      response.net_checksum_cycles > response.raw_checksum_cycles ||
      response.net_checksum_cycles >
          std::numeric_limits<std::uint64_t>::max() -
              response.cache_setup_cycles) {
    return false;
  }
  const std::uint64_t operations =
      static_cast<std::uint64_t>(response.request.batch_count) *
      response.request.iterations_per_batch;
  response.buffer_bytes = benchmarkVectorBytes(response.request.vector);
  response.processed_bytes = operations * response.buffer_bytes;
  response.target_framed_bytes_per_second =
      protocol_v1::kChecksumBenchmarkTargetFramedBytesPerSecond;
  const std::uint64_t total_cycles =
      response.net_checksum_cycles + response.cache_setup_cycles;
  if (response.processed_bytes == 0U) {
    response.cycles_per_byte_q16 = 0U;
    response.mb_per_second_q16 = 0U;
    response.projected_cpu_percent_q16 = 0U;
    return true;
  }
  if (total_cycles == 0U || response.cycle_counter_hz == 0U ||
      total_cycles >
          std::numeric_limits<std::uint64_t>::max() / 65536ULL) {
    return false;
  }
  const std::uint64_t cycles_per_byte_q16 =
      (total_cycles * 65536ULL) / response.processed_bytes;
  if (cycles_per_byte_q16 > std::numeric_limits<std::uint32_t>::max() ||
      response.processed_bytes >
          std::numeric_limits<std::uint64_t>::max() /
              response.cycle_counter_hz) {
    return false;
  }
  const std::uint64_t bytes_per_second =
      (static_cast<std::uint64_t>(response.cycle_counter_hz) *
       response.processed_bytes) /
      total_cycles;
  // Split the decimal-MB scaling around its divisor. This is exactly
  // floor(bytes_per_second * 65536 / 1,000,000) without permitting the
  // intermediate multiplication to wrap for an untrusted response.
  const std::uint64_t mb_per_second_q16 =
      (bytes_per_second / 1000000ULL) * 65536ULL +
      ((bytes_per_second % 1000000ULL) * 65536ULL) / 1000000ULL;
  const std::uint64_t projected_cpu_percent_q16 =
      (cycles_per_byte_q16 * response.target_framed_bytes_per_second * 100ULL) /
      response.cycle_counter_hz;
  if (mb_per_second_q16 > std::numeric_limits<std::uint32_t>::max() ||
      projected_cpu_percent_q16 >
          std::numeric_limits<std::uint32_t>::max()) {
    return false;
  }
  response.cycles_per_byte_q16 =
      static_cast<std::uint32_t>(cycles_per_byte_q16);
  response.mb_per_second_q16 =
      static_cast<std::uint32_t>(mb_per_second_q16);
  response.projected_cpu_percent_q16 =
      static_cast<std::uint32_t>(projected_cpu_percent_q16);
  return true;
}

Result computeChecksum(protocol_v1::ChecksumAlgorithm algorithm, ByteView input,
                       std::uint32_t &result_checksum) {
  if (!input.valid()) {
    return badLength();
  }
  checksum::Algorithm implementation{};
  switch (algorithm) {
    case protocol_v1::ChecksumAlgorithm::kAdler32:
      implementation = checksum::Algorithm::kAdler32;
      break;
    case protocol_v1::ChecksumAlgorithm::kCrc32c:
      implementation = checksum::Algorithm::kCrc32c;
      break;
    case protocol_v1::ChecksumAlgorithm::kCrc32IsoHdlc:
      implementation = checksum::Algorithm::kCrc32IsoHdlc;
      break;
    case protocol_v1::ChecksumAlgorithm::kNoneReserved:
      return unsupportedChecksum();
    default:
      return unsupportedChecksum();
  }
  return checksum::compute(implementation, input.data, input.size,
                           result_checksum)
             ? Result::success()
             : unsupportedChecksum();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.frame_decode")
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.frame_encode")
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
  header.version = fields.version;
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.data_frame_v2")
Result encodeDataFrameInPlace(FrameFields fields, MutableByteView frame,
                              std::size_t payload_bytes_written,
                              const DataFrameShape &shape) {
  if (shape.protocol_version != protocol_v1::kProtocolVersion &&
      shape.protocol_version != protocol_v2::kProtocolVersion) {
    return badVersion();
  }
  if (!frame.valid() || frame.size != shape.frame_bytes ||
      payload_bytes_written != shape.payload_bytes ||
      !isDataKind(fields.kind) ||
      !dataFrameShapeMatchesContract(fields.kind, shape)) {
    return badLength();
  }
  if (!isSupportedChecksum(fields.checksum_algorithm)) {
    return unsupportedChecksum();
  }
  const std::uint16_t allowed = protocol_v1::allowedFlags(fields.kind);
  if ((fields.flags & static_cast<std::uint16_t>(~allowed)) != 0U) {
    return badFlags();
  }
  const std::uint16_t overrun = static_cast<std::uint16_t>(
      protocol_v1::FrameFlag::kOverrunBefore);
  const std::uint16_t gap =
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kGapBefore);
  if ((fields.flags & overrun) != 0U && (fields.flags & gap) == 0U) {
    return badFlags();
  }
  const bool epoch_start =
      (fields.flags & static_cast<std::uint16_t>(
                          protocol_v1::FrameFlag::kEpochStart)) != 0U;
  const bool first_item =
      fields.sequence == 0U && fields.first_sample_ticks == 0U;
  if (fields.run_id == 0U || fields.request_id != 0U ||
      fields.item_count != shape.item_count ||
      fields.first_sample_ticks % shape.item_period_ticks != 0U ||
      epoch_start != first_item) {
    return badPayload();
  }

  FrameHeader header{};
  header.kind = fields.kind;
  header.version = shape.protocol_version;
  header.flags = fields.flags;
  header.checksum_algorithm = fields.checksum_algorithm;
  header.total_length = static_cast<std::uint32_t>(shape.frame_bytes);
  header.payload_length = static_cast<std::uint32_t>(shape.payload_bytes);
  header.run_id = fields.run_id;
  header.sequence = fields.sequence;
  header.request_id = fields.request_id;
  header.first_sample_ticks = fields.first_sample_ticks;
  header.item_count = fields.item_count;
  Result result = validatePayload(
      header,
      {frame.data + protocol_v1::kHeaderSize, shape.payload_bytes});
  if (!result.ok()) {
    return result;
  }
  if (!writeHeader(header, frame)) {
    return badLength();
  }

  std::uint32_t checksum = 0U;
  result = computeChecksum(
      header.checksum_algorithm,
      {frame.data, protocol_v1::kHeaderSize + shape.payload_bytes},
      checksum);
  if (!result.ok() ||
      !storeU32(frame, protocol_v1::kHeaderSize + shape.payload_bytes,
                checksum)) {
    return result.ok() ? badLength() : result;
  }
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.request_decode")
Result decodeRequest(ByteView input, Request &request) {
  DecodedFrame frame{};
  Result result = decodeFrame(input, frame);
  if (!result.ok()) {
    return result;
  }
  if (input_experiment::kReleaseFixed1MHz &&
      frame.header.version != protocol_v2::kProtocolVersion) {
    return badVersion();
  }
  protocol_v1::CommandKind command{};
  if (!commandForKind(frame.header.kind, command)) {
    return badKind();
  }
  Request decoded{};
  decoded.kind = command;
  decoded.request_id = frame.header.request_id;
  decoded.protocol_version = frame.header.version;
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
    decoded.configuration.protocol_version = frame.header.version;
    if (frame.header.version == protocol_v2::kProtocolVersion) {
      decoded.configuration.aux_bank_mode =
          static_cast<protocol_v2::AuxBankMode>(frame.payload.data[
              protocol_v2::kConfigureRequestAuxBankModeOffset]);
      std::uint32_t adc_rate = 0U;
      std::uint32_t gpio_rate = 0U;
      if (!loadU32(frame.payload,
                   protocol_v2::kConfigureRequestAdcPairRateHzOffset,
                   adc_rate) ||
          !loadU32(frame.payload,
                   protocol_v2::kConfigureRequestGpioSampleRateHzOffset,
                   gpio_rate)) {
        return badPayload();
      }
      bool matched = false;
      for (const protocol_v2::RateProfileTiming &timing :
           rate_profile::kTimings) {
        if (timing.adc_pair_rate_hz == adc_rate &&
            timing.gpio_sample_rate_hz == gpio_rate) {
          decoded.configuration.rate_profile = timing.profile;
          matched = true;
          break;
        }
      }
      if (!matched) {
        return badPayload();
      }
    }
  } else if (command == protocol_v1::CommandKind::kPing &&
             !loadU64(frame.payload, protocol_v1::kPingRequestNonceOffset,
                      decoded.nonce)) {
    return badPayload();
  } else if (command == protocol_v1::CommandKind::kChecksumBenchmark) {
    result = decodeChecksumBenchmarkRequest(frame.payload,
                                            decoded.checksum_benchmark);
    if (!result.ok()) {
      return result;
    }
  } else if (command ==
             protocol_v1::CommandKind::kGpioClockDiagnostic) {
    result = decodeGpioClockDiagnosticRequest(
        frame.payload, decoded.gpio_clock_diagnostic);
    if (!result.ok()) {
      return result;
    }
  }
  if (input_experiment::kReleaseFixed1MHz &&
      (command == protocol_v1::CommandKind::kGpioCaptureDiagnostic ||
       (command == protocol_v1::CommandKind::kConfigure &&
        decoded.configuration.rate_profile != protocol_v2::RateProfile::kAdc1mhzGpio1mhz) ||
       (command == protocol_v1::CommandKind::kGpioClockDiagnostic &&
        decoded.gpio_clock_diagnostic.rate_hz != 1000000U))) {
    return Result::failure(protocol_v1::ErrorCode::kUnsupportedConfiguration,
                           ValidationIssue::kBadPayload);
  }
  request = decoded;
  return Result::success();
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.info_response")
Result encodeInfoResponse(const Request &request, std::uint32_t run_id,
                          const InfoResponse &response, ControlFrame &output) {
  Result result = verifyRequestKind(request, protocol_v1::CommandKind::kInfo);
  if (!result.ok()) {
    return result;
  }
  const bool version2 =
      request.protocol_version == protocol_v2::kProtocolVersion;
  const bool auxiliary_input =
      version2 && response.applied_configuration.aux_bank_mode ==
                      protocol_v2::AuxBankMode::kInput;
  const protocol_v2::RateProfileTiming *timing =
      rate_profile::timingFor(response.applied_configuration.rate_profile);
  if (version2 && timing == nullptr) {
    return badPayload();
  }
  std::array<std::uint8_t, protocol_v2::kInfoResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  payload[protocol_v1::kInfoResponseDeviceStateOffset] =
      static_cast<std::uint8_t>(response.device_state);
  payload[protocol_v1::kInfoResponseProtocolVersionOffset] =
      request.protocol_version;
  payload[protocol_v1::kInfoResponseSupportedStreamMaskOffset] =
      response.supported_stream_mask;
  payload[protocol_v1::kInfoResponseSupportedSourceMaskOffset] =
      response.supported_source_mask;
  storeU32(bytes, protocol_v1::kInfoResponseSupportedChecksumMaskOffset,
           response.supported_checksum_mask);
  storeU32(bytes, protocol_v1::kInfoResponseCapabilityBitsOffset,
           version2 ? response.capability_bits |
                          static_cast<std::uint32_t>(
                              protocol_v2::Capability::kAuxiliaryInputBank) |
                          static_cast<std::uint32_t>(
                              protocol_v2::Capability::kExactRateProfiles)
                    : response.capability_bits);
  storeU32(bytes, protocol_v1::kInfoResponseTimestampHzOffset,
           response.timestamp_hz);
  storeU32(bytes, protocol_v1::kInfoResponseDataFrameBytesOffset,
           response.data_frame_bytes);
  storeU32(bytes, protocol_v1::kInfoResponseMaxControlFrameBytesOffset,
           version2 ? protocol_v2::kMaxControlFrameBytes
                    : protocol_v1::kMaxControlFrameBytes);
  storeU32(bytes, protocol_v1::kInfoResponseAdcPairRateHzOffset,
           version2 ? timing->adc_pair_rate_hz : response.adc_pair_rate_hz);
  storeU32(bytes, protocol_v1::kInfoResponseGpioSampleRateHzOffset,
           version2 ? timing->gpio_sample_rate_hz
                    : response.gpio_sample_rate_hz);
  storeU16(bytes, protocol_v1::kInfoResponseAdcPairPeriodTicksOffset,
           version2 ? timing->adc_pair_period_ticks
                    : response.adc_pair_period_ticks);
  storeU16(bytes, protocol_v1::kInfoResponseAdc1PhaseTicksOffset,
           version2 ? timing->adc1_phase_ticks : response.adc1_phase_ticks);
  storeU16(bytes, protocol_v1::kInfoResponseGpioSamplePeriodTicksOffset,
           version2 ? timing->gpio_sample_period_ticks
                    : response.gpio_sample_period_ticks);
  payload[protocol_v1::kInfoResponseAdcResolutionBitsOffset] =
      response.adc.resolution_bits;
  payload[protocol_v1::kInfoResponseAdcContainerBytesOffset] =
      response.adc.container_bytes;
  payload[protocol_v1::kInfoResponseGpioPinCountOffset] =
      static_cast<std::uint8_t>(response.gpio_pin_map.size());
  payload[protocol_v1::kInfoResponseDataChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(response.data_checksum_algorithm);
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
  payload[protocol_v1::kInfoResponseGpioPackedWidthBitsOffset] =
      version2 && response.applied_configuration.aux_bank_mode ==
                      protocol_v2::AuxBankMode::kInput
          ? 16U
          : response.gpio_packed_width_bits;
  payload[protocol_v1::kInfoResponseGpioRawRingDepthOffset] =
      response.gpio_raw_ring_depth;
  payload[protocol_v1::kInfoResponseGpioPackedRingDepthOffset] =
      response.gpio_packed_ring_depth;
  payload[protocol_v1::kInfoResponseGpioCaptureDiagnosticModeOffset] =
      static_cast<std::uint8_t>(response.gpio_capture_diagnostic_mode);
  storeU16(bytes,
           protocol_v1::kInfoResponseGpioCaptureDiagnosticFlagsOffset,
           response.gpio_capture_diagnostic_flags);
  storeU32(bytes, protocol_v1::kInfoResponseGpioRawSamplesPerBufferOffset,
           version2
               ? static_cast<std::uint32_t>(
                     response.applied_configuration.aux_bank_mode ==
                             protocol_v2::AuxBankMode::kInput
                         ? protocol_v2::kInputGpioSamplesPerFrame
                         : protocol_v2::kDisabledGpioSamplesPerFrame)
               : response.gpio_raw_samples_per_buffer);
  storeU32(bytes, protocol_v1::kInfoResponseGpioRawRingBytesOffset,
           version2
               ? static_cast<std::uint32_t>(
                     (response.applied_configuration.aux_bank_mode ==
                              protocol_v2::AuxBankMode::kInput
                          ? protocol_v2::kInputGpioSamplesPerFrame
                          : protocol_v2::kDisabledGpioSamplesPerFrame) *
                     sizeof(std::uint32_t) *
                     protocol_v1::kGpioRawRingDepth)
               : response.gpio_raw_ring_bytes);
  storeU32(bytes, protocol_v1::kInfoResponseGpioPackedRingBytesOffset,
           response.gpio_packed_ring_bytes);
  storeU16(bytes, protocol_v1::kInfoResponseGpioPacketBufferCountOffset,
           response.gpio_packet_buffer_count);
  payload[protocol_v1::kInfoResponseGpioPitChannelOffset] =
      response.gpio_pit_channel;
  payload[protocol_v1::kInfoResponseGpioXbarInputOffset] =
      response.gpio_xbar_input;
  payload[protocol_v1::kInfoResponseGpioXbarOutputOffset] =
      response.gpio_xbar_output;
  payload[protocol_v1::kInfoResponseGpioEdmaChannelOffset] =
      response.gpio_edma_channel;
  payload[protocol_v1::kInfoResponseGpioDmamuxSourceOffset] =
      response.gpio_dmamux_source;
  payload[protocol_v1::kInfoResponseGpioEdmaPriorityOffset] =
      auxiliary_input ? protocol_v2::kInputModeEdmaPriorities[2]
                      : response.gpio_edma_priority;
  payload[protocol_v1::kInfoResponseGpioXbarActiveEdgeOffset] =
      response.gpio_xbar_active_edge;
  storeU16(bytes, protocol_v1::kInfoResponseAdcCodeMinOffset,
           response.adc.code_min);
  storeU16(bytes, protocol_v1::kInfoResponseAdcCodeMaxOffset,
           response.adc.code_max);
  payload[protocol_v1::kInfoResponseAdcReferenceOffset] =
      static_cast<std::uint8_t>(response.adc.reference);
  payload[protocol_v1::kInfoResponseAdcClockSourceOffset] =
      static_cast<std::uint8_t>(response.adc.clock_source);
  payload[protocol_v1::kInfoResponseAdcClockDividerOffset] =
      response.adc.clock_divider;
  payload[protocol_v1::kInfoResponseAdcHardwareAverageCountOffset] =
      response.adc.hardware_average_count;
  storeU16(bytes, protocol_v1::kInfoResponseAdcReferenceMvNominalOffset,
           response.adc.reference_mv_nominal);
  storeU16(bytes, protocol_v1::kInfoResponseAdcInputMinMvNominalOffset,
           response.adc.input_min_mv_nominal);
  storeU16(bytes, protocol_v1::kInfoResponseAdcInputMaxMvNominalOffset,
           response.adc.input_max_mv_nominal);
  payload[protocol_v1::kInfoResponseAdcSampleTimeAdckOffset] =
      response.adc.sample_time_adck;
  payload[protocol_v1::kInfoResponseAdcConversionModeOffset] =
      response.adc.conversion_mode;
  storeU16(bytes, protocol_v1::kInfoResponseAdcConfigurationFlagsOffset,
           response.adc.configuration_flags);
  payload[protocol_v1::kInfoResponseAdc0CalibrationStateOffset] =
      static_cast<std::uint8_t>(response.adc.calibration_states[0]);
  payload[protocol_v1::kInfoResponseAdc1CalibrationStateOffset] =
      static_cast<std::uint8_t>(response.adc.calibration_states[1]);
  payload[protocol_v1::kInfoResponseAdc0PinOffset] = response.adc.pins[0];
  payload[protocol_v1::kInfoResponseAdc1PinOffset] = response.adc.pins[1];
  payload[protocol_v1::kInfoResponseAdc0PeripheralOffset] =
      response.adc.peripherals[0];
  payload[protocol_v1::kInfoResponseAdc1PeripheralOffset] =
      response.adc.peripherals[1];
  payload[protocol_v1::kInfoResponseAdc0ChannelOffset] =
      response.adc.channels[0];
  payload[protocol_v1::kInfoResponseAdc1ChannelOffset] =
      response.adc.channels[1];
  storeU32(bytes, protocol_v1::kInfoResponseAdcIpgClockHzOffset,
           response.adc.ipg_clock_hz);
  storeU32(bytes, protocol_v1::kInfoResponseAdcClockHzOffset,
           response.adc.adc_clock_hz);
  storeU32(bytes, protocol_v1::kInfoResponseAdcCalibrationDeadlineUsOffset,
           response.adc.calibration_deadline_us);
  storeU32(bytes, protocol_v1::kInfoResponseAdc0CalibrationCyclesOffset,
           response.adc.calibration_cycles[0]);
  storeU32(bytes, protocol_v1::kInfoResponseAdc1CalibrationCyclesOffset,
           response.adc.calibration_cycles[1]);
  storeU32(bytes,
           protocol_v1::kInfoResponseAdcInitializationErrorFlagsOffset,
           response.adc.initialization_error_flags);
  encodeAdcTriggerMetadata(
      bytes, protocol_v1::kInfoResponseAdcTriggerConfigurationFlagsOffset,
      response.adc.trigger);
  payload[protocol_v1::kInfoResponseAppliedStreamMaskOffset] =
      response.applied_configuration.stream_mask;
  payload[protocol_v1::kInfoResponseAppliedSourceOffset] =
      static_cast<std::uint8_t>(response.applied_configuration.source);
  storeU16(bytes, protocol_v1::kInfoResponseSupportedConfigurationMaskOffset,
           response.supported_configuration_mask);
  storeU16(bytes, protocol_v1::kInfoResponseDataPayloadBytesOffset,
           auxiliary_input
               ? static_cast<std::uint16_t>(protocol_v2::kInputAdcPairsPerFrame *
                                            protocol_v1::kAdcPairBytes)
               : response.data_payload_bytes);
  storeU16(bytes, protocol_v1::kInfoResponseAdcPairsPerFrameOffset,
           version2
               ? static_cast<std::uint16_t>(
                     response.applied_configuration.aux_bank_mode ==
                             protocol_v2::AuxBankMode::kInput
                         ? protocol_v2::kInputAdcPairsPerFrame
                         : protocol_v2::kDisabledAdcPairsPerFrame)
               : response.adc_pairs_per_frame);
  storeU16(bytes, protocol_v1::kInfoResponseGpioSamplesPerFrameOffset,
           version2
               ? static_cast<std::uint16_t>(
                     response.applied_configuration.aux_bank_mode ==
                             protocol_v2::AuxBankMode::kInput
                         ? protocol_v2::kInputGpioSamplesPerFrame
                         : protocol_v2::kDisabledGpioSamplesPerFrame)
               : response.gpio_samples_per_frame);
  storeU32(bytes, protocol_v1::kInfoResponseFrameCoverageTicksOffset,
           version2
               ? (response.applied_configuration.aux_bank_mode ==
                          protocol_v2::AuxBankMode::kInput
                      ? timing->input_frame_coverage_ticks
                      : timing->disabled_frame_coverage_ticks)
               : response.frame_coverage_ticks);
  payload[protocol_v1::kInfoResponseAdcDmaRingDepthOffset] =
      response.adc_dma_ring_depth;
  payload[protocol_v1::kInfoResponseAdcPairBytesOffset] =
      response.adc_pair_bytes;
  for (std::size_t index = 0U; index < 2U; ++index) {
    payload[protocol_v1::kInfoResponseAdcEdmaChannelsOffset + index] =
        response.adc_edma_channels[index];
    payload[protocol_v1::kInfoResponseAdcEdmaPrioritiesOffset + index] =
        auxiliary_input ? protocol_v2::kInputModeEdmaPriorities[index]
                        : response.adc_edma_priorities[index];
    payload[protocol_v1::kInfoResponseAdcDmamuxSourcesOffset + index] =
        response.adc_dmamux_sources[index];
  }
  payload[protocol_v1::kInfoResponseAdcDmaIrqPriorityOffset] =
      response.adc_dma_irq_priority;
  payload[protocol_v1::kInfoResponseGpioDmaIrqPriorityOffset] =
      response.gpio_dma_irq_priority;
  storeU16(bytes, protocol_v1::kInfoResponseAdcPairsPerBufferOffset,
           version2
               ? static_cast<std::uint16_t>(
                     response.applied_configuration.aux_bank_mode ==
                             protocol_v2::AuxBankMode::kInput
                         ? protocol_v2::kInputAdcPairsPerFrame
                         : protocol_v2::kDisabledAdcPairsPerFrame)
               : response.adc_pairs_per_buffer);
  storeU32(bytes, protocol_v1::kInfoResponseAdcDmaRingBytesOffset,
           version2
               ? static_cast<std::uint32_t>(
                     ((response.applied_configuration.aux_bank_mode ==
                               protocol_v2::AuxBankMode::kInput
                           ? protocol_v2::kInputAdcPairsPerFrame
                           : protocol_v2::kDisabledAdcPairsPerFrame) *
                              protocol_v1::kAdcPairBytes +
                          31U) /
                         32U * 32U * protocol_v1::kAdcDmaRingDepth)
               : response.adc_dma_ring_bytes);
  storeU16(bytes, protocol_v1::kInfoResponsePacketBufferCountOffset,
           response.packet_buffer_count);
  storeU16(bytes, protocol_v1::kInfoResponsePacketPrimaryCountOffset,
           response.packet_primary_count);
  storeU16(bytes, protocol_v1::kInfoResponsePacketReserveCountOffset,
           response.packet_reserve_count);
  storeU16(bytes, protocol_v1::kInfoResponsePacketReadyQueueCapacityOffset,
           response.packet_ready_queue_capacity);
  storeU16(bytes,
           protocol_v1::kInfoResponsePacketTransmitQueueCapacityOffset,
           response.packet_transmit_queue_capacity);
  payload[protocol_v1::kInfoResponseCommandQueueCapacityOffset] =
      response.command_queue_capacity;
  payload[protocol_v1::kInfoResponseResponseQueueCapacityOffset] =
      response.response_queue_capacity;
  storeU32(
      bytes,
      protocol_v1::kInfoResponseNominalPayloadBytesPerSecondPerStreamOffset,
      response.nominal_payload_bytes_per_second_per_stream);
  storeU32(
      bytes,
      protocol_v1::kInfoResponseNominalFramedBytesPerSecondPerStreamOffset,
      response.nominal_framed_bytes_per_second_per_stream);
  if (version2) {
    payload[protocol_v2::kInfoResponseSupportedRateProfileMaskOffset] =
        input_experiment::kReleaseFixed1MHz ? 16U
                                          : protocol_v2::kSupportedRateProfileMask;
    payload[protocol_v2::kInfoResponseSelectedRateProfileOffset] =
        static_cast<std::uint8_t>(response.applied_configuration.rate_profile);
    payload[protocol_v2::kInfoResponseSupportedAuxBankModeMaskOffset] =
        protocol_v2::kSupportedAuxBankModeMask;
    payload[protocol_v2::kInfoResponseAppliedAuxBankModeOffset] =
        static_cast<std::uint8_t>(response.applied_configuration.aux_bank_mode);
    payload[protocol_v2::kInfoResponseGpioItemBytesOffset] =
        response.applied_configuration.aux_bank_mode ==
                protocol_v2::AuxBankMode::kInput
            ? 2U
            : 1U;
    payload[protocol_v2::kInfoResponseAuxGpioPinCountOffset] = 8U;
    payload[protocol_v2::kInfoResponseRateProfileCountOffset] =
        static_cast<std::uint8_t>(rate_profile::kCount);
    for (std::size_t index = 0U; index < 8U; ++index) {
      payload[protocol_v2::kInfoResponseAuxGpioPinMapOffset + index] =
          response.auxiliary.pins[index];
      payload[protocol_v2::kInfoResponseAuxGpioPortBitsOffset + index] =
          response.auxiliary.port_bits[index];
    }
    payload[protocol_v2::kInfoResponseAuxGpioStandardPortOffset] = 1U;
    payload[protocol_v2::kInfoResponseAuxGpioFastPortOffset] = 6U;
    payload[protocol_v2::kInfoResponseAuxGpioFastSelectGprOffset] = 26U;
    payload[protocol_v2::kInfoResponseGpioRawWordBytesOffset] =
        protocol_v2::kGpioRawWordBytesPerBank;
    storeU32(bytes, protocol_v2::kInfoResponseAuxGpioCaptureMaskOffset,
             protocol_v2::kAuxGpioCaptureMask);
    payload[protocol_v2::kInfoResponsePrimaryGpioStandardPortOffset] = 2U;
    payload[protocol_v2::kInfoResponsePrimaryGpioFastPortOffset] = 7U;
    payload[protocol_v2::kInfoResponsePrimaryGpioFastSelectGprOffset] = 27U;
    storeU32(bytes, protocol_v2::kInfoResponsePrimaryGpioCaptureMaskOffset,
             protocol_v2::kPrimaryGpioCaptureMask);
    payload[protocol_v2::kInfoResponsePrimaryGpioEdmaChannelOffset] = 2U;
    payload[protocol_v2::kInfoResponseAuxGpioEdmaChannelOffset] =
        protocol_v2::kAuxGpioEdmaChannel;
    payload[protocol_v2::kInfoResponsePrimaryGpioDmamuxSourceOffset] = 30U;
    payload[protocol_v2::kInfoResponseAuxGpioDmamuxSourceOffset] =
        protocol_v2::kAuxGpioDmamuxSource;
    payload[protocol_v2::kInfoResponsePrimaryGpioXbarOutputOffset] = 0U;
    payload[protocol_v2::kInfoResponseAuxGpioXbarOutputOffset] =
        protocol_v2::kAuxGpioXbarOutput;
    payload[protocol_v2::kInfoResponsePairedGpioXbarInputOffset] = 56U;
    payload[protocol_v2::kInfoResponseAuxGpioEdmaPriorityOffset] =
        protocol_v2::kInputModeEdmaPriorities[3];
    payload[protocol_v2::kInfoResponsePrimaryGpioEdmaPriorityOffset] =
        protocol_v2::kInputModeEdmaPriorities[2];
    payload[protocol_v2::kInfoResponseAdc0EdmaPriorityOffset] =
        protocol_v2::kInputModeEdmaPriorities[0];
    payload[protocol_v2::kInfoResponseAdc1EdmaPriorityOffset] =
        protocol_v2::kInputModeEdmaPriorities[1];
    payload[protocol_v2::kInfoResponseAuxGpioDmaIrqPriorityOffset] = 64U;
    payload[protocol_v2::kInfoResponsePrimaryGpioRawRingDepthOffset] =
        protocol_v1::kGpioRawRingDepth;
    payload[protocol_v2::kInfoResponseAuxGpioRawRingDepthOffset] =
        protocol_v2::kAuxGpioRawRingDepth;
    payload[protocol_v2::kInfoResponsePairedGpioJoinRequiredOffset] = 1U;
    storeU16(bytes, protocol_v2::kInfoResponseDisabledAdcPairsPerFrameOffset,
             protocol_v2::kDisabledAdcPairsPerFrame);
    storeU16(bytes,
             protocol_v2::kInfoResponseDisabledGpioSamplesPerFrameOffset,
             protocol_v2::kDisabledGpioSamplesPerFrame);
    storeU16(bytes, protocol_v2::kInfoResponseInputAdcPairsPerFrameOffset,
             protocol_v2::kInputAdcPairsPerFrame);
    storeU16(bytes, protocol_v2::kInfoResponseInputGpioSamplesPerFrameOffset,
             protocol_v2::kInputGpioSamplesPerFrame);
    for (std::size_t index = 0U; index < rate_profile::kCount; ++index) {
      const protocol_v2::RateProfileTiming &entry =
          rate_profile::kTimings[index];
      const std::size_t base = protocol_v2::kInfoResponseRateProfilesOffset +
                               index * protocol_v2::kRateProfileInfoPayloadSize;
      payload[base + protocol_v2::kRateProfileInfoRateProfileOffset] =
          static_cast<std::uint8_t>(entry.profile);
      payload[base + protocol_v2::kRateProfileInfoAdcEtcChainLengthOffset] = 1U;
      storeU32(bytes, base + protocol_v2::kRateProfileInfoAdcPairRateHzOffset,
               entry.adc_pair_rate_hz);
      storeU32(bytes,
               base + protocol_v2::kRateProfileInfoGpioSampleRateHzOffset,
               entry.gpio_sample_rate_hz);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoAdcPairPeriodTicksOffset,
               entry.adc_pair_period_ticks);
      storeU16(bytes, base + protocol_v2::kRateProfileInfoAdc1PhaseTicksOffset,
               entry.adc1_phase_ticks);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoGpioSamplePeriodTicksOffset,
               entry.gpio_sample_period_ticks);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoGpioMasterPitDividerOffset,
               entry.gpio_master_pit_divider);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoGpioMasterPitLoadOffset,
               entry.gpio_master_pit_load);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoAdcPairPitDividerOffset,
               entry.adc_pair_pit_divider);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoAdcPairPitLoadOffset,
               entry.adc_pair_pit_load);
      storeU16(bytes, base + protocol_v2::kRateProfileInfoAdc1InitialDelayOffset,
               entry.adc1_phase_ipg_cycles);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoAdc0EffectiveDelayOffset,
               1U);
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoAdc1EffectiveDelayOffset,
               static_cast<std::uint16_t>(entry.adc1_phase_ipg_cycles + 1U));
      storeU16(bytes,
               base + protocol_v2::kRateProfileInfoAdc1PhaseIpgCyclesOffset,
               entry.adc1_phase_ipg_cycles);
      storeU32(bytes,
               base +
                   protocol_v2::kRateProfileInfoCompletionExpectedDwtCyclesOffset,
               entry.completion_expected_dwt_cycles);
      storeU32(bytes,
               base +
                   protocol_v2::kRateProfileInfoDisabledFrameCoverageTicksOffset,
               entry.disabled_frame_coverage_ticks);
      storeU32(bytes,
               base +
                   protocol_v2::kRateProfileInfoInputFrameCoverageTicksOffset,
               entry.input_frame_coverage_ticks);
    }
  }
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kInfoResponse, request, run_id),
      {payload.data(), version2 ? protocol_v2::kInfoResponsePayloadSize
                                : protocol_v1::kInfoResponsePayloadSize},
      output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.configure_response")
Result encodeConfigureResponse(const Request &request, std::uint32_t run_id,
                               const Configuration &configuration,
                               ControlFrame &output) {
  Result result =
      verifyRequestKind(request, protocol_v1::CommandKind::kConfigure);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v2::kConfigureResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  writeConfiguration(bytes, 4U, configuration, request.protocol_version);
  return encodeFrame(responseFields(protocol_v1::FrameKind::kConfigureResponse,
                                    request, run_id),
                     {payload.data(), request.protocol_version ==
                                          protocol_v2::kProtocolVersion
                                      ? protocol_v2::kConfigureResponsePayloadSize
                                      : protocol_v1::kConfigureResponsePayloadSize},
                     output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.start_response")
Result encodeStartResponse(const Request &request, std::uint32_t run_id,
                           const Configuration &configuration,
                           ControlFrame &output) {
  Result result = verifyRequestKind(request, protocol_v1::CommandKind::kStart);
  if (!result.ok()) {
    return result;
  }
  std::array<std::uint8_t, protocol_v2::kConfigureResponsePayloadSize> payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  writeConfiguration(bytes, 4U, configuration, request.protocol_version);
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kStartResponse, request, run_id),
      {payload.data(), request.protocol_version == protocol_v2::kProtocolVersion
                           ? protocol_v2::kConfigureResponsePayloadSize
                           : protocol_v1::kConfigureResponsePayloadSize},
      output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.status_response")
Result encodeStatusResponse(const Request &request, std::uint32_t run_id,
                            const StatusResponse &response,
                            ControlFrame &output) {
  Result result =
      verifyRequestKind(request, protocol_v1::CommandKind::kGetStatus);
  if (!result.ok()) {
    return result;
  }
  const bool version2 =
      request.protocol_version == protocol_v2::kProtocolVersion;
  const protocol_v2::RateProfileTiming *timing =
      rate_profile::timingFor(response.configuration.rate_profile);
  if (version2 && timing == nullptr) {
    return badPayload();
  }
  std::array<std::uint8_t, protocol_v2::kStatusResponsePayloadSize> payload{};
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
#define STORE_STATUS_U64(field, member)                                    \
  storeU64(bytes, protocol_v1::kStatusResponse##field##Offset,             \
           response.member)
#define STORE_STATUS_U32(field, member)                                    \
  storeU32(bytes, protocol_v1::kStatusResponse##field##Offset,             \
           response.member)
#define STORE_STATUS_U16(field, member)                                    \
  storeU16(bytes, protocol_v1::kStatusResponse##field##Offset,             \
           response.member)
  STORE_STATUS_U64(GpioSamplesCaptured, gpio_samples_captured);
  STORE_STATUS_U64(GpioSamplesPacked, gpio_samples_packed);
  STORE_STATUS_U64(GpioSamplesFramed, gpio_samples_framed);
  STORE_STATUS_U64(GpioSamplesTransmitted, gpio_samples_transmitted);
  STORE_STATUS_U64(GpioRawSamplesLost, gpio_raw_samples_lost);
  STORE_STATUS_U64(GpioPackerSamplesDropped, gpio_packer_samples_dropped);
  STORE_STATUS_U64(GpioRawRingOverruns, gpio_raw_ring_overruns);
  STORE_STATUS_U64(GpioDmaMajorLoops, gpio_dma_major_loops);
  STORE_STATUS_U16(GpioRawReadyDepth, gpio_raw_ready_depth);
  STORE_STATUS_U16(GpioRawReadyHighWater, gpio_raw_ready_high_water);
  STORE_STATUS_U16(GpioPackedReadyDepth, gpio_packed_ready_depth);
  STORE_STATUS_U16(GpioPackedReadyHighWater, gpio_packed_ready_high_water);
  STORE_STATUS_U16(PacketReadyDepth, packet_ready_depth);
  STORE_STATUS_U16(PacketTransmitDepth, packet_transmit_depth);
  STORE_STATUS_U16(PacketOwnedHighWater, packet_owned_high_water);
  STORE_STATUS_U16(GpioProcessingCpuBasisPoints,
                   gpio_processing_cpu_basis_points);
  STORE_STATUS_U32(GpioHardwareErrors, gpio_hardware_errors);
  STORE_STATUS_U32(GpioRawInvariantErrors, gpio_raw_invariant_errors);
  STORE_STATUS_U32(GpioPackerSourceErrors, gpio_packer_source_errors);
  STORE_STATUS_U32(GpioPackerPipelineErrors, gpio_packer_pipeline_errors);
  STORE_STATUS_U32(GpioPackerChronologyErrors,
                   gpio_packer_chronology_errors);
  STORE_STATUS_U32(GpioResourceConflicts, gpio_resource_conflicts);
  STORE_STATUS_U32(GpioStartErrors, gpio_start_errors);
  STORE_STATUS_U32(GpioStopErrors, gpio_stop_errors);
  STORE_STATUS_U32(GpioStaleDmaCompletions, gpio_stale_dma_completions);
  STORE_STATUS_U64(Adc0DmaMajorLoops, adc0_dma_major_loops);
  STORE_STATUS_U64(Adc1DmaMajorLoops, adc1_dma_major_loops);
  STORE_STATUS_U64(Adc0DmaResults, adc0_dma_results);
  STORE_STATUS_U64(Adc1DmaResults, adc1_dma_results);
  STORE_STATUS_U64(AdcPairedMajorLoops, adc_paired_major_loops);
  STORE_STATUS_U64(AdcBuffersCompleted, adc_buffers_completed);
  STORE_STATUS_U64(AdcBuffersAcquired, adc_buffers_acquired);
  STORE_STATUS_U64(AdcBuffersReleased, adc_buffers_released);
  STORE_STATUS_U64(AdcPairsCaptured, adc_pairs_captured);
  STORE_STATUS_U64(AdcPairsDelivered, adc_pairs_delivered);
  STORE_STATUS_U64(AdcPairsFramed, adc_pairs_framed);
  STORE_STATUS_U64(AdcPairsTransmitted, adc_pairs_transmitted);
  STORE_STATUS_U64(AdcRawPairsLost, adc_raw_pairs_lost);
  STORE_STATUS_U64(AdcStopPairsDiscarded, adc_stop_pairs_discarded);
  STORE_STATUS_U64(AdcIncompleteConversions, adc_incomplete_conversions);
  STORE_STATUS_U64(AdcOverwrittenConversions, adc_overwritten_conversions);
  STORE_STATUS_U64(AdcRawRingOverruns, adc_raw_ring_overruns);
  STORE_STATUS_U64(AdcIncompleteBuffers, adc_incomplete_buffers);
  STORE_STATUS_U16(AdcRawReadyDepth, adc_raw_ready_depth);
  STORE_STATUS_U16(AdcRawReadyHighWater, adc_raw_ready_high_water);
  STORE_STATUS_U32(AdcEtcErrorEvents, adc_etc_error_events);
  STORE_STATUS_U32(AdcEtcErrorFlags, adc_etc_error_flags);
  STORE_STATUS_U32(AdcDmaErrorEvents, adc_dma_error_events);
  STORE_STATUS_U32(AdcCompletionMismatches, adc_completion_mismatches);
  STORE_STATUS_U32(AdcDestinationMismatches, adc_destination_mismatches);
  STORE_STATUS_U32(AdcScheduleExhaustions, adc_schedule_exhaustions);
  STORE_STATUS_U32(AdcRawInvariantErrors, adc_raw_invariant_errors);
  STORE_STATUS_U32(AdcStaleCompletions, adc_stale_completions);
  STORE_STATUS_U32(AdcResourceConflicts, adc_resource_conflicts);
  STORE_STATUS_U32(AdcStartErrors, adc_start_errors);
  STORE_STATUS_U32(AdcStopErrors, adc_stop_errors);
  STORE_STATUS_U32(AdcStaleInterrupts, adc_stale_interrupts);
  STORE_STATUS_U32(AdcPackerSourceErrors, adc_packer_source_errors);
  STORE_STATUS_U32(AdcPackerPipelineErrors, adc_packer_pipeline_errors);
  STORE_STATUS_U32(AdcPackerChronologyErrors,
                   adc_packer_chronology_errors);
#define STORE_STREAM_TELEMETRY(prefix, index)                              \
  storeU64(bytes, protocol_v1::kStatusResponse##prefix##FramesGeneratedOffset, \
           response.streams[index].frames_generated);                     \
  storeU64(bytes, protocol_v1::kStatusResponse##prefix##ItemsGeneratedOffset, \
           response.streams[index].items_generated);                      \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##FramesFramedPipelineOffset, \
           response.streams[index].frames_framed);                        \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##ItemsFramedPipelineOffset, \
           response.streams[index].items_framed);                         \
  storeU64(bytes, protocol_v1::kStatusResponse##prefix##ItemsEmittedOffset, \
           response.streams[index].items_emitted);                        \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##FramesTransmittedOffset, \
           response.streams[index].frames_transmitted);                   \
  storeU64(                                                               \
      bytes,                                                              \
      protocol_v1::kStatusResponse##prefix##ItemsTransmittedPipelineOffset, \
      response.streams[index].items_transmitted);                         \
  storeU64(bytes, protocol_v1::kStatusResponse##prefix##FramesDroppedOffset, \
           response.streams[index].frames_dropped);                       \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##PayloadBytesProducedOffset, \
           response.streams[index].payload_bytes_produced);               \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##PayloadBytesFramedOffset, \
           response.streams[index].payload_bytes_framed);                 \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##PayloadBytesEmittedOffset, \
           response.streams[index].payload_bytes_emitted);                \
  storeU64(                                                               \
      bytes,                                                              \
      protocol_v1::kStatusResponse##prefix##PayloadBytesTransmittedOffset, \
      response.streams[index].payload_bytes_transmitted);                 \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##PayloadBytesDroppedOffset, \
           response.streams[index].payload_bytes_dropped);                \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##FramedBytesFramedOffset, \
           response.streams[index].framed_bytes_framed);                  \
  storeU64(bytes,                                                         \
           protocol_v1::kStatusResponse##prefix##FramedBytesEmittedOffset, \
           response.streams[index].framed_bytes_emitted);                 \
  storeU64(                                                               \
      bytes,                                                              \
      protocol_v1::kStatusResponse##prefix##FramedBytesTransmittedOffset, \
      response.streams[index].framed_bytes_transmitted)
  STORE_STREAM_TELEMETRY(Adc, 0U);
  STORE_STREAM_TELEMETRY(Gpio, 1U);
#undef STORE_STREAM_TELEMETRY
  STORE_STATUS_U16(AdcPacketReadyDepth, streams[0U].packet_ready_depth);
  STORE_STATUS_U16(GpioPacketReadyDepth, streams[1U].packet_ready_depth);
  STORE_STATUS_U16(AdcPacketTransmitDepth,
                   streams[0U].packet_transmit_depth);
  STORE_STATUS_U16(GpioPacketTransmitDepth,
                   streams[1U].packet_transmit_depth);
  STORE_STATUS_U16(AdcPacketReadyHighWater,
                   streams[0U].packet_ready_high_water);
  STORE_STATUS_U16(GpioPacketReadyHighWater,
                   streams[1U].packet_ready_high_water);
  STORE_STATUS_U16(AdcPacketTransmitHighWater,
                   streams[0U].packet_transmit_high_water);
  STORE_STATUS_U16(GpioPacketTransmitHighWater,
                   streams[1U].packet_transmit_high_water);
  STORE_STATUS_U16(PacketReadyHighWater, packet.ready_high_water);
  STORE_STATUS_U16(PacketTransmitHighWater, packet.transmit_high_water);
  STORE_STATUS_U64(PacketFramesPromoted, packet.frames_promoted);
  STORE_STATUS_U64(PacketFairnessDeferrals, packet.fairness_deferrals);
  STORE_STATUS_U64(PacketAccountedFrameSkew, packet.accounted_frame_skew);
  STORE_STATUS_U64(DataPayloadBytesTransmitted,
                   packet.data_payload_bytes_transmitted);
  STORE_STATUS_U64(DataFramedBytesTransmitted,
                   packet.data_framed_bytes_transmitted);
  STORE_STATUS_U32(PacketPoolExhaustions, packet.pool_exhaustions);
  STORE_STATUS_U32(PacketInvalidOperations, packet.invalid_operations);
  STORE_STATUS_U32(PacketEncodingRejections, packet.encoding_rejections);
  STORE_STATUS_U32(PacketReadyQueueRejections,
                   packet.ready_queue_rejections);
  STORE_STATUS_U32(PacketTransmitQueueRejections,
                   packet.transmit_queue_rejections);
  STORE_STATUS_U32(CommandsAccepted, diagnostics.commands_accepted);
  STORE_STATUS_U32(CommandsRejected, diagnostics.commands_rejected);
  STORE_STATUS_U32(BadChecksums, diagnostics.bad_checksums);
  STORE_STATUS_U32(BadLengths, diagnostics.bad_lengths);
  STORE_STATUS_U32(BadTypes, diagnostics.bad_types);
  STORE_STATUS_U32(BadVersions, diagnostics.bad_versions);
  STORE_STATUS_U32(Timeouts, diagnostics.timeouts);
  STORE_STATUS_U32(PartialUsbWrites, diagnostics.partial_usb_writes);
  STORE_STATUS_U32(StateErrors, diagnostics.state_errors);
  STORE_STATUS_U32(UsbShortCapacityDeferrals,
                   usb.short_capacity_deferrals);
  STORE_STATUS_U32(UsbRxStallEvents, usb.rx_stall_events);
  STORE_STATUS_U32(UsbTxStallEvents, usb.tx_stall_events);
  STORE_STATUS_U32(UsbIoErrors, usb.io_errors);
  STORE_STATUS_U16(UsbCommandQueueDepth, usb.command_queue_depth);
  STORE_STATUS_U16(UsbResponseQueueDepth, usb.response_queue_depth);
  STORE_STATUS_U16(UsbLowerPriorityQueueDepth,
                   usb.lower_priority_queue_depth);
  STORE_STATUS_U16(UsbCommandQueueHighWater,
                   usb.command_queue_high_water);
  STORE_STATUS_U16(UsbResponseQueueHighWater,
                   usb.response_queue_high_water);
  STORE_STATUS_U16(UsbActiveFrameBytesSent,
                   usb.active_frame_bytes_sent);
  STORE_STATUS_U16(PacketOwnedDepth, packet.owned_depth);
  STORE_STATUS_U16(UsbActiveFrameSize, usb.active_frame_size);
  STORE_STATUS_U32(AdcCacheDmaDiscards, adc_cache_dma_discards);
  STORE_STATUS_U32(AdcCacheCpuInvalidations,
                   adc_cache_cpu_invalidations);
  STORE_STATUS_U32(GpioCacheDmaDiscards, gpio_cache_dma_discards);
  STORE_STATUS_U32(GpioCacheCpuInvalidations,
                   gpio_cache_cpu_invalidations);
  STORE_STATUS_U32(BadFlags, diagnostics.bad_flags);
  STORE_STATUS_U32(BadPayloads, diagnostics.bad_payloads);
  STORE_STATUS_U32(BadRequestIds, diagnostics.bad_request_ids);
  STORE_STATUS_U32(ResponsesQueued, usb.responses_queued);
  STORE_STATUS_U32(ResponsesCompleted, usb.responses_completed);
  STORE_STATUS_U32(ResponseQueueRejections,
                   usb.response_queue_rejections);
  STORE_STATUS_U32(ResponseReservationsAbandoned,
                   usb.response_reservations_abandoned);
  STORE_STATUS_U64(PacketPressureEvictions,
                   packet.pressure_evictions);
  STORE_STATUS_U64(PacketCapacityDropsWithoutEvictableFrame,
                   packet.capacity_drops_without_evictable_frame);
  STORE_STATUS_U64(AdcFramesEvicted, streams[0U].frames_evicted);
  STORE_STATUS_U64(AdcFramesEvictedAfterPromotion,
                   streams[0U].frames_evicted_after_promotion);
  STORE_STATUS_U64(GpioFramesEvicted, streams[1U].frames_evicted);
  STORE_STATUS_U64(GpioFramesEvictedAfterPromotion,
                   streams[1U].frames_evicted_after_promotion);
  STORE_STATUS_U16(AdcPacketFillingDepth,
                   streams[0U].packet_filling_depth);
  STORE_STATUS_U16(GpioPacketFillingDepth,
                   streams[1U].packet_filling_depth);
  STORE_STATUS_U64(AdcFramesDroppedAfterFraming,
                   streams[0U].frames_dropped_after_framing);
  STORE_STATUS_U64(AdcFramesDroppedAfterPromotion,
                   streams[0U].frames_dropped_after_promotion);
  STORE_STATUS_U64(GpioFramesDroppedAfterFraming,
                   streams[1U].frames_dropped_after_framing);
  STORE_STATUS_U64(GpioFramesDroppedAfterPromotion,
                   streams[1U].frames_dropped_after_promotion);
  STORE_STATUS_U64(GpioBuffersCompleted, gpio_buffers_completed);
  STORE_STATUS_U64(GpioBuffersAcquired, gpio_buffers_acquired);
  STORE_STATUS_U64(GpioBuffersReleased, gpio_buffers_released);
  STORE_STATUS_U64(GpioSamplesDelivered, gpio_samples_delivered);
  STORE_STATUS_U64(GpioStopSamplesDiscarded,
                   gpio_stop_samples_discarded);
  STORE_STATUS_U64(GpioFramesProduced, gpio_frames_produced);
  STORE_STATUS_U64(GpioSamplesProduced, gpio_samples_produced);
  STORE_STATUS_U64(GpioFramesPacked, gpio_frames_packed);
  STORE_STATUS_U64(GpioDuplicateSamplesIgnored,
                   gpio_duplicate_samples_ignored);
  STORE_STATUS_U64(AdcFramesConsumed, adc_frames_consumed);
  STORE_STATUS_U64(AdcPairsConsumed, adc_pairs_consumed);
  STORE_STATUS_U64(AdcRawGapPairs, adc_raw_gap_pairs);
  STORE_STATUS_U64(AdcRawDropPairsProjected,
                   adc_raw_drop_pairs_projected);
  STORE_STATUS_U64(GpioRawDropSamplesProjected,
                   gpio_raw_drop_samples_projected);
  STORE_STATUS_U64(GpioPackerDropSamplesProjected,
                   gpio_packer_drop_samples_projected);
#undef STORE_STATUS_U16
#undef STORE_STATUS_U32
#undef STORE_STATUS_U64
  payload[protocol_v1::kStatusResponseAdcResolutionBitsOffset] =
      response.adc.resolution_bits;
  payload[protocol_v1::kStatusResponseAdcContainerBytesOffset] =
      response.adc.container_bytes;
  payload[protocol_v1::kStatusResponseAdc0CalibrationStateOffset] =
      static_cast<std::uint8_t>(response.adc.calibration_states[0]);
  payload[protocol_v1::kStatusResponseAdc1CalibrationStateOffset] =
      static_cast<std::uint8_t>(response.adc.calibration_states[1]);
  storeU16(bytes, protocol_v1::kStatusResponseAdcCodeMinOffset,
           response.adc.code_min);
  storeU16(bytes, protocol_v1::kStatusResponseAdcCodeMaxOffset,
           response.adc.code_max);
  payload[protocol_v1::kStatusResponseAdcReferenceOffset] =
      static_cast<std::uint8_t>(response.adc.reference);
  payload[protocol_v1::kStatusResponseAdcClockSourceOffset] =
      static_cast<std::uint8_t>(response.adc.clock_source);
  payload[protocol_v1::kStatusResponseAdcClockDividerOffset] =
      response.adc.clock_divider;
  payload[protocol_v1::kStatusResponseAdcHardwareAverageCountOffset] =
      response.adc.hardware_average_count;
  storeU16(bytes, protocol_v1::kStatusResponseAdcReferenceMvNominalOffset,
           response.adc.reference_mv_nominal);
  storeU16(bytes, protocol_v1::kStatusResponseAdcInputMinMvNominalOffset,
           response.adc.input_min_mv_nominal);
  storeU16(bytes, protocol_v1::kStatusResponseAdcInputMaxMvNominalOffset,
           response.adc.input_max_mv_nominal);
  payload[protocol_v1::kStatusResponseAdcSampleTimeAdckOffset] =
      response.adc.sample_time_adck;
  payload[protocol_v1::kStatusResponseAdcConversionModeOffset] =
      response.adc.conversion_mode;
  storeU16(bytes, protocol_v1::kStatusResponseAdcConfigurationFlagsOffset,
           response.adc.configuration_flags);
  payload[protocol_v1::kStatusResponseAdc0PinOffset] = response.adc.pins[0];
  payload[protocol_v1::kStatusResponseAdc1PinOffset] = response.adc.pins[1];
  payload[protocol_v1::kStatusResponseAdc0PeripheralOffset] =
      response.adc.peripherals[0];
  payload[protocol_v1::kStatusResponseAdc1PeripheralOffset] =
      response.adc.peripherals[1];
  payload[protocol_v1::kStatusResponseAdc0ChannelOffset] =
      response.adc.channels[0];
  payload[protocol_v1::kStatusResponseAdc1ChannelOffset] =
      response.adc.channels[1];
  storeU32(bytes, protocol_v1::kStatusResponseAdcIpgClockHzOffset,
           response.adc.ipg_clock_hz);
  storeU32(bytes, protocol_v1::kStatusResponseAdcClockHzOffset,
           response.adc.adc_clock_hz);
  storeU32(bytes, protocol_v1::kStatusResponseAdcCalibrationDeadlineUsOffset,
           response.adc.calibration_deadline_us);
  storeU32(bytes, protocol_v1::kStatusResponseAdc0CalibrationCyclesOffset,
           response.adc.calibration_cycles[0]);
  storeU32(bytes, protocol_v1::kStatusResponseAdc1CalibrationCyclesOffset,
           response.adc.calibration_cycles[1]);
  storeU32(bytes,
           protocol_v1::kStatusResponseAdcInitializationErrorFlagsOffset,
           response.adc.initialization_error_flags);
  encodeAdcTriggerMetadata(
      bytes, protocol_v1::kStatusResponseAdcTriggerConfigurationFlagsOffset,
      response.adc.trigger);
  if (version2) {
    const bool input = response.configuration.aux_bank_mode ==
                       protocol_v2::AuxBankMode::kInput;
    const std::uint32_t coverage =
        input ? timing->input_frame_coverage_ticks
              : timing->disabled_frame_coverage_ticks;
    const std::uint32_t frame_us = static_cast<std::uint32_t>(
        static_cast<std::uint64_t>(coverage) * 1000000U /
        protocol_v2::kTimestampHz);
    payload[protocol_v2::kStatusResponseProtocolVersionOffset] =
        protocol_v2::kProtocolVersion;
    payload[protocol_v2::kStatusResponseAuxBankModeOffset] =
        static_cast<std::uint8_t>(response.configuration.aux_bank_mode);
    payload[protocol_v2::kStatusResponseRateProfileOffset] =
        static_cast<std::uint8_t>(response.configuration.rate_profile);
    payload[protocol_v2::kStatusResponseGpioItemBytesOffset] = input ? 2U : 1U;
    storeU32(bytes, protocol_v2::kStatusResponseAdcPairRateHzOffset,
             timing->adc_pair_rate_hz);
    storeU32(bytes, protocol_v2::kStatusResponseGpioSampleRateHzOffset,
             timing->gpio_sample_rate_hz);
    storeU32(bytes, protocol_v2::kStatusResponseFrameCoverageTicksOffset,
             coverage);
    storeU32(bytes,
             protocol_v2::kStatusResponsePacketRetentionUsCombinedOffset,
             frame_us * (protocol_v1::kPacketBufferCount / 2U));
    storeU32(bytes,
             protocol_v2::kStatusResponsePacketRetentionUsSingleStreamOffset,
             frame_us * protocol_v1::kPacketBufferCount);
    storeU16(bytes, protocol_v2::kStatusResponsePrimaryGpioRawReadyDepthOffset,
             response.auxiliary_gpio.ready_depth[0]);
    storeU16(bytes, protocol_v2::kStatusResponseAuxGpioRawReadyDepthOffset,
             response.auxiliary_gpio.ready_depth[1]);
    storeU16(
        bytes,
        protocol_v2::kStatusResponsePrimaryGpioRawReadyHighWaterOffset,
        response.auxiliary_gpio.ready_high_water[0]);
    storeU16(bytes,
             protocol_v2::kStatusResponseAuxGpioRawReadyHighWaterOffset,
             response.auxiliary_gpio.ready_high_water[1]);
#define STORE_AUX_STATUS_U64(field, member)                                \
  storeU64(bytes, protocol_v2::kStatusResponse##field##Offset,             \
           response.auxiliary_gpio.member)
#define STORE_AUX_STATUS_U32(field, member)                                \
  storeU32(bytes, protocol_v2::kStatusResponse##field##Offset,             \
           response.auxiliary_gpio.member)
    storeU64(bytes, protocol_v2::kStatusResponsePrimaryGpioDmaMajorLoopsOffset,
             response.auxiliary_gpio.bank_major_loops[0]);
    storeU64(bytes, protocol_v2::kStatusResponseAuxGpioDmaMajorLoopsOffset,
             response.auxiliary_gpio.bank_major_loops[1]);
    storeU64(bytes,
             protocol_v2::kStatusResponsePrimaryGpioSamplesCapturedOffset,
             response.auxiliary_gpio.bank_samples_captured[0]);
    storeU64(bytes, protocol_v2::kStatusResponseAuxGpioSamplesCapturedOffset,
             response.auxiliary_gpio.bank_samples_captured[1]);
    STORE_AUX_STATUS_U64(PairedGpioDmaMajorLoops, paired_major_loops);
    STORE_AUX_STATUS_U64(PairedGpioBuffersCompleted, buffers_completed);
    STORE_AUX_STATUS_U64(PairedGpioBuffersAcquired, buffers_acquired);
    STORE_AUX_STATUS_U64(PairedGpioBuffersReleased, buffers_released);
    STORE_AUX_STATUS_U64(PairedGpioSamplesCaptured, samples_captured);
    STORE_AUX_STATUS_U64(PairedGpioSamplesJoined, samples_joined);
    STORE_AUX_STATUS_U64(PairedGpioSamplesDelivered, samples_delivered);
    STORE_AUX_STATUS_U64(PairedGpioSamplesLost, samples_lost);
    STORE_AUX_STATUS_U64(PairedGpioRawRingOverruns, raw_ring_overruns);
    STORE_AUX_STATUS_U64(PairedGpioGenerationSkewEvents,
                         generation_skew_events);
    STORE_AUX_STATUS_U64(PairedGpioGenerationSkewSamples,
                         generation_skew_samples);
    STORE_AUX_STATUS_U64(PairedGpioCanceledGenerations,
                         canceled_generations);
    STORE_AUX_STATUS_U64(PairedGpioCancellationSamples,
                         cancellation_samples);
    STORE_AUX_STATUS_U64(PairedGpioStopTailSamples, stop_tail_samples);
    STORE_AUX_STATUS_U32(PairedGpioTimestampMismatches,
                         timestamp_mismatches);
    STORE_AUX_STATUS_U32(PairedGpioCountMismatches, count_mismatches);
    STORE_AUX_STATUS_U32(PairedGpioDestinationMismatches,
                         destination_mismatches);
    STORE_AUX_STATUS_U32(PairedGpioScheduleExhaustions,
                         schedule_exhaustions);
    STORE_AUX_STATUS_U32(PairedGpioStaleCompletions, stale_completions);
    STORE_AUX_STATUS_U32(PairedGpioCacheDmaDiscards, cache_dma_discards);
    STORE_AUX_STATUS_U32(PairedGpioCacheCpuInvalidations,
                         cache_cpu_invalidations);
    STORE_AUX_STATUS_U32(PairedGpioHardwareErrors, hardware_errors);
    STORE_AUX_STATUS_U32(PairedGpioInvariantErrors, invariant_errors);
    STORE_AUX_STATUS_U32(PairedGpioResourceConflicts, resource_conflicts);
    STORE_AUX_STATUS_U32(PairedGpioStartErrors, start_errors);
    STORE_AUX_STATUS_U32(PairedGpioStopErrors, stop_errors);
    STORE_AUX_STATUS_U32(PairedGpioStaleDmaCompletions,
                         stale_dma_completions);
    storeU32(bytes,
             protocol_v2::kStatusResponsePrimaryGpioRawRingOverrunsOffset,
             response.auxiliary_gpio.bank_ring_overruns[0]);
    storeU32(bytes, protocol_v2::kStatusResponseAuxGpioRawRingOverrunsOffset,
             response.auxiliary_gpio.bank_ring_overruns[1]);
    storeU32(bytes,
             protocol_v2::kStatusResponsePrimaryGpioStaleCompletionsOffset,
             response.auxiliary_gpio.bank_stale_completions[0]);
    storeU32(bytes, protocol_v2::kStatusResponseAuxGpioStaleCompletionsOffset,
             response.auxiliary_gpio.bank_stale_completions[1]);
#undef STORE_AUX_STATUS_U32
#undef STORE_AUX_STATUS_U64
  }
  return encodeFrame(responseFields(protocol_v1::FrameKind::kGetStatusResponse,
                                    request, run_id),
                     {payload.data(), version2
                                          ? protocol_v2::kStatusResponsePayloadSize
                                          : protocol_v1::kStatusResponsePayloadSize},
                     output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.stop_response")
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.reset_stats_response")
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.ping_response")
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

// Encoding this diagnostics-only response is not part of the measured loop or
// the streaming hot path. Keep it in program Flash so adding a faster CRC does
// not force another 32 KiB ITCM allocation block out of RAM1.
THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.checksum_benchmark_response")
Result encodeChecksumBenchmarkResponse(
    const Request &request, std::uint32_t run_id,
    const ChecksumBenchmarkResponse &response, ControlFrame &output) {
  Result result =
      verifyRequestKind(request, protocol_v1::CommandKind::kChecksumBenchmark);
  if (!result.ok() ||
      response.request.checksum_algorithm !=
          request.checksum_benchmark.checksum_algorithm ||
      response.request.vector != request.checksum_benchmark.vector ||
      response.request.memory_region !=
          request.checksum_benchmark.memory_region ||
      response.request.cache_state != request.checksum_benchmark.cache_state ||
      response.request.batch_count != request.checksum_benchmark.batch_count ||
      response.request.iterations_per_batch !=
          request.checksum_benchmark.iterations_per_batch) {
    return result.ok() ? badPayload() : result;
  }
  ChecksumBenchmarkResponse checked = response;
  if (!populateChecksumBenchmarkMetrics(checked) ||
      checked.buffer_bytes != response.buffer_bytes ||
      checked.processed_bytes != response.processed_bytes ||
      checked.cycles_per_byte_q16 != response.cycles_per_byte_q16 ||
      checked.mb_per_second_q16 != response.mb_per_second_q16 ||
      checked.projected_cpu_percent_q16 !=
          response.projected_cpu_percent_q16) {
    return badPayload();
  }

  std::array<std::uint8_t,
             protocol_v1::kChecksumBenchmarkResponsePayloadSize>
      payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  payload[protocol_v1::kChecksumBenchmarkResponseChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(response.request.checksum_algorithm);
  payload[protocol_v1::kChecksumBenchmarkResponseVectorOffset] =
      static_cast<std::uint8_t>(response.request.vector);
  payload[protocol_v1::kChecksumBenchmarkResponseMemoryRegionOffset] =
      static_cast<std::uint8_t>(response.request.memory_region);
  payload[protocol_v1::kChecksumBenchmarkResponseCacheStateOffset] =
      static_cast<std::uint8_t>(response.request.cache_state);
  storeU16(bytes, protocol_v1::kChecksumBenchmarkResponseBatchCountOffset,
           response.request.batch_count);
  storeU16(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseIterationsPerBatchOffset,
      response.request.iterations_per_batch);
  storeU32(bytes, protocol_v1::kChecksumBenchmarkResponseBufferBytesOffset,
           response.buffer_bytes);
  storeU32(bytes,
           protocol_v1::kChecksumBenchmarkResponseCycleCounterHzOffset,
           response.cycle_counter_hz);
  storeU32(bytes,
           protocol_v1::kChecksumBenchmarkResponseTimerOverheadCyclesOffset,
           response.timer_overhead_cycles);
  storeU32(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseImplementationCodeBytesOffset,
      response.implementation_code_bytes);
  storeU32(bytes, protocol_v1::kChecksumBenchmarkResponseTableBytesOffset,
           response.table_bytes);
  storeU32(bytes, protocol_v1::kChecksumBenchmarkResponseWorkingRamBytesOffset,
           response.working_ram_bytes);
  storeU32(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseDeterministicDigestOffset,
      response.deterministic_digest);
  storeU64(bytes, protocol_v1::kChecksumBenchmarkResponseProcessedBytesOffset,
           response.processed_bytes);
  storeU64(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseRawChecksumCyclesOffset,
      response.raw_checksum_cycles);
  storeU64(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseNetChecksumCyclesOffset,
      response.net_checksum_cycles);
  storeU64(bytes,
           protocol_v1::kChecksumBenchmarkResponseCacheSetupCyclesOffset,
           response.cache_setup_cycles);
  storeU32(bytes, protocol_v1::kChecksumBenchmarkResponseMinBatchCyclesOffset,
           response.min_batch_cycles);
  storeU32(bytes, protocol_v1::kChecksumBenchmarkResponseMaxBatchCyclesOffset,
           response.max_batch_cycles);
  storeU32(bytes,
           protocol_v1::kChecksumBenchmarkResponseCyclesPerByteQ16Offset,
           response.cycles_per_byte_q16);
  storeU32(bytes,
           protocol_v1::kChecksumBenchmarkResponseMbPerSecondQ16Offset,
           response.mb_per_second_q16);
  storeU32(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseProjectedCpuPercentQ16Offset,
      response.projected_cpu_percent_q16);
  storeU32(
      bytes,
      protocol_v1::kChecksumBenchmarkResponseTargetFramedBytesPerSecondOffset,
      response.target_framed_bytes_per_second);
  return encodeFrame(
      responseFields(protocol_v1::FrameKind::kChecksumBenchmarkResponse,
                     request, run_id),
      view(payload), output);
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.gpio_clock_diagnostic_response")
Result encodeGpioClockDiagnosticResponse(
    const Request &request, std::uint32_t run_id,
    const GpioClockDiagnosticResponse &response, ControlFrame &output) {
  Result result = verifyRequestKind(
      request, protocol_v1::CommandKind::kGpioClockDiagnostic);
  if (!result.ok() ||
      !validGpioClockDiagnosticRequest(
          request.gpio_clock_diagnostic) ||
      response.configured_rate_hz !=
          request.gpio_clock_diagnostic.rate_hz ||
      response.requested_event_count !=
          request.gpio_clock_diagnostic.event_count ||
      response.production_rate_hz !=
          protocol_v1::kGpioClockProductionRateHz ||
      response.pit_clock_hz != protocol_v1::kGpioClockPitHz ||
      response.pit_load_value !=
          protocol_v1::kGpioClockPitHz / response.configured_rate_hz - 1U ||
      (response.hardware_error_flags &
       ~protocol_v1::kKnownGpioClockErrorMask) != 0U) {
    return result.ok() ? badPayload() : result;
  }

  std::array<std::uint8_t,
             protocol_v1::kGpioClockDiagnosticResponsePayloadSize>
      payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
#define STORE_GPIO_CLOCK_U32(field, member)                                 \
  storeU32(bytes,                                                           \
           protocol_v1::kGpioClockDiagnosticResponse##field##Offset,        \
           response.member)
#define STORE_GPIO_CLOCK_U16(field, member)                                 \
  storeU16(bytes,                                                           \
           protocol_v1::kGpioClockDiagnosticResponse##field##Offset,        \
           response.member)
  STORE_GPIO_CLOCK_U32(ConfiguredRateHz, configured_rate_hz);
  STORE_GPIO_CLOCK_U32(ProductionRateHz, production_rate_hz);
  STORE_GPIO_CLOCK_U32(PitClockHz, pit_clock_hz);
  STORE_GPIO_CLOCK_U32(PitLoadValue, pit_load_value);
  STORE_GPIO_CLOCK_U32(RequestedEventCount, requested_event_count);
  STORE_GPIO_CLOCK_U32(ScheduledEventCount, scheduled_event_count);
  STORE_GPIO_CLOCK_U32(DmaSampleCount, dma_sample_count);
  STORE_GPIO_CLOCK_U32(DwtCounterHz, dwt_counter_hz);
  STORE_GPIO_CLOCK_U32(DwtElapsedCycles, dwt_elapsed_cycles);
  STORE_GPIO_CLOCK_U32(HardwareErrorFlags, hardware_error_flags);
  STORE_GPIO_CLOCK_U32(CcmCscmr1Configured, ccm_cscmr1_configured);
  STORE_GPIO_CLOCK_U32(CcmCcgr1Configured, ccm_ccgr1_configured);
  STORE_GPIO_CLOCK_U32(CcmCcgr2Configured, ccm_ccgr2_configured);
  STORE_GPIO_CLOCK_U32(CcmCcgr5Configured, ccm_ccgr5_configured);
  STORE_GPIO_CLOCK_U32(PitMcrConfigured, pit_mcr_configured);
  STORE_GPIO_CLOCK_U32(PitLdvalConfigured, pit_ldval_configured);
  STORE_GPIO_CLOCK_U32(PitCvalFinal, pit_cval_final);
  STORE_GPIO_CLOCK_U32(PitTctrlConfigured, pit_tctrl_configured);
  STORE_GPIO_CLOCK_U32(PitTflgFinal, pit_tflg_final);
  STORE_GPIO_CLOCK_U16(XbarSelConfigured, xbar_sel_configured);
  STORE_GPIO_CLOCK_U16(XbarCtrlConfigured, xbar_ctrl_configured);
  STORE_GPIO_CLOCK_U32(DmamuxChcfgConfigured, dmamux_chcfg_configured);
  STORE_GPIO_CLOCK_U32(DmaCrConfigured, dma_cr_configured);
  STORE_GPIO_CLOCK_U32(DmaEsFinal, dma_es_final);
  STORE_GPIO_CLOCK_U32(DmaErqConfigured, dma_erq_configured);
  STORE_GPIO_CLOCK_U32(DmaErrFinal, dma_err_final);
  STORE_GPIO_CLOCK_U32(DmaHrsFinal, dma_hrs_final);
  STORE_GPIO_CLOCK_U32(TcdSaddr, tcd_saddr);
  STORE_GPIO_CLOCK_U32(TcdDaddr, tcd_daddr);
  STORE_GPIO_CLOCK_U32(TcdNbytes, tcd_nbytes);
  STORE_GPIO_CLOCK_U32(LastSampleWord, last_sample_word);
  STORE_GPIO_CLOCK_U16(TcdCiterFinal, tcd_citer_final);
  STORE_GPIO_CLOCK_U16(TcdBiter, tcd_biter);
  STORE_GPIO_CLOCK_U16(TcdCsrFinal, tcd_csr_final);
  STORE_GPIO_CLOCK_U16(TcdAttr, tcd_attr);
  payload[protocol_v1::kGpioClockDiagnosticResponsePitChannelOffset] =
      response.pit_channel;
  payload[protocol_v1::kGpioClockDiagnosticResponseXbarInputOffset] =
      response.xbar_input;
  payload[protocol_v1::kGpioClockDiagnosticResponseXbarOutputOffset] =
      response.xbar_output;
  payload[protocol_v1::kGpioClockDiagnosticResponseEdmaChannelOffset] =
      response.edma_channel;
  payload[protocol_v1::kGpioClockDiagnosticResponseDmamuxSourceOffset] =
      response.dmamux_source;
  payload[protocol_v1::kGpioClockDiagnosticResponseEdmaPriorityOffset] =
      response.edma_priority;
  STORE_GPIO_CLOCK_U16(TcdSoff, tcd_soff);
#undef STORE_GPIO_CLOCK_U16
#undef STORE_GPIO_CLOCK_U32
  return encodeFrame(
      responseFields(
          protocol_v1::FrameKind::kGpioClockDiagnosticResponse, request,
          run_id),
      view(payload), output);
}

THINGDAQ_PROTOCOL_COLD_CODE(
    ".flashmem.protocol.gpio_capture_diagnostic_response")
Result encodeGpioCaptureDiagnosticResponse(
    const Request &request, std::uint32_t run_id,
    const GpioCaptureDiagnosticResponse &response, ControlFrame &output) {
  Result result = verifyRequestKind(
      request, protocol_v1::CommandKind::kGpioCaptureDiagnostic);
  if (!result.ok()) {
    return result;
  }

  const bool version2 =
      request.protocol_version == protocol_v2::kProtocolVersion;
  std::array<std::uint8_t,
             protocol_v2::kGpioCaptureDiagnosticResponsePayloadSize>
      payload{};
  MutableByteView bytes = mutableView(payload);
  writeSuccessPrefix(bytes);
  payload[protocol_v1::kGpioCaptureDiagnosticResponseModeOffset] =
      static_cast<std::uint8_t>(response.mode);
  payload[protocol_v1::kGpioCaptureDiagnosticResponseMetadataKindOffset] =
      response.metadata_kind;
  payload[protocol_v1::kGpioCaptureDiagnosticResponseDriveSafetyOffset] =
      response.drive_safety;
  payload[protocol_v1::kGpioCaptureDiagnosticResponseStimulusKindOffset] =
      response.stimulus_kind;
#define STORE_GPIO_CAPTURE_U32(field, member)                              \
  storeU32(bytes,                                                          \
           protocol_v1::kGpioCaptureDiagnosticResponse##field##Offset,     \
           response.member)
#define STORE_GPIO_CAPTURE_U16(field, member)                              \
  storeU16(bytes,                                                          \
           protocol_v1::kGpioCaptureDiagnosticResponse##field##Offset,     \
           response.member)
  STORE_GPIO_CAPTURE_U32(FixtureIdentity, fixture_identity);
  STORE_GPIO_CAPTURE_U32(StimulusIdentity, stimulus_identity);
  STORE_GPIO_CAPTURE_U32(HardwareErrorFlags, hardware_error_flags);
  STORE_GPIO_CAPTURE_U32(DiagnosticFlags, diagnostic_flags);
  STORE_GPIO_CAPTURE_U32(DwtCounterHz, dwt_counter_hz);
  STORE_GPIO_CAPTURE_U32(DwtElapsedCycles, dwt_elapsed_cycles);
  storeU64(bytes,
           protocol_v1::kGpioCaptureDiagnosticResponseDmaSamplesCapturedOffset,
           response.dma_samples_captured);
  STORE_GPIO_CAPTURE_U32(CompleteSamplesRetained,
                         complete_samples_retained);
  STORE_GPIO_CAPTURE_U32(SamplesAnalyzed, samples_analyzed);
  STORE_GPIO_CAPTURE_U32(StoppedPartialSamples, stopped_partial_samples);
  STORE_GPIO_CAPTURE_U32(RawWordAnd, raw_word_and);
  STORE_GPIO_CAPTURE_U32(RawWordOr, raw_word_or);
  STORE_GPIO_CAPTURE_U32(ObservedTransitions, observed_transitions);
  STORE_GPIO_CAPTURE_U16(MappingValuesChecked, mapping_values_checked);
  STORE_GPIO_CAPTURE_U16(MappingFailures, mapping_failures);
  STORE_GPIO_CAPTURE_U16(UnstableSamples, unstable_samples);
  payload[protocol_v1::kGpioCaptureDiagnosticResponsePackedValueAndOffset] =
      response.packed_value_and;
  payload[protocol_v1::kGpioCaptureDiagnosticResponsePackedValueOrOffset] =
      response.packed_value_or;
  payload[protocol_v1::kGpioCaptureDiagnosticResponseFirstPackedValueOffset] =
      response.first_packed_value;
  payload[protocol_v1::kGpioCaptureDiagnosticResponseLastPackedValueOffset] =
      response.last_packed_value;
  STORE_GPIO_CAPTURE_U32(Gpr27Before, gpr27_before);
  STORE_GPIO_CAPTURE_U32(Gpr27Configured, gpr27_configured);
  STORE_GPIO_CAPTURE_U32(Gpr27After, gpr27_after);
  STORE_GPIO_CAPTURE_U32(Gpio2GdirBefore, gpio2_gdir_before);
  STORE_GPIO_CAPTURE_U32(Gpio2GdirConfigured, gpio2_gdir_configured);
  STORE_GPIO_CAPTURE_U32(Gpio2GdirAfter, gpio2_gdir_after);
  STORE_GPIO_CAPTURE_U32(Gpio2PsrBefore, gpio2_psr_before);
  STORE_GPIO_CAPTURE_U32(Gpio2PsrConfigured, gpio2_psr_configured);
  STORE_GPIO_CAPTURE_U32(Gpio2PsrAfter, gpio2_psr_after);
  STORE_GPIO_CAPTURE_U32(PitLdvalConfigured, pit_ldval_configured);
  STORE_GPIO_CAPTURE_U32(PitTctrlConfigured, pit_tctrl_configured);
  STORE_GPIO_CAPTURE_U32(DmamuxChcfgConfigured, dmamux_chcfg_configured);
  STORE_GPIO_CAPTURE_U32(DmaErqConfigured, dma_erq_configured);
  STORE_GPIO_CAPTURE_U32(DmaErrFinal, dma_err_final);
  STORE_GPIO_CAPTURE_U16(TcdCiterConfigured, tcd_citer_configured);
  STORE_GPIO_CAPTURE_U16(TcdBiterConfigured, tcd_biter_configured);
  STORE_GPIO_CAPTURE_U16(TcdCsrConfigured, tcd_csr_configured);
  payload[
      protocol_v1::kGpioCaptureDiagnosticResponseEdmaPriorityConfiguredOffset] =
      response.edma_priority_configured;
  STORE_GPIO_CAPTURE_U32(AnalysisSampleLimit, analysis_sample_limit);
#undef STORE_GPIO_CAPTURE_U16
#undef STORE_GPIO_CAPTURE_U32
  if (version2) {
    payload[protocol_v2::kGpioCaptureDiagnosticResponseBankCountOffset] =
        response.bank_count;
    payload[protocol_v2::kGpioCaptureDiagnosticResponseAuxBankModeOffset] =
        static_cast<std::uint8_t>(response.aux_bank_mode);
    payload[
        protocol_v2::kGpioCaptureDiagnosticResponseSelectedRateProfileOffset] =
        static_cast<std::uint8_t>(response.selected_rate_profile);
    payload[protocol_v2::
                kGpioCaptureDiagnosticResponseAuxElectricallyUnstimulatedOffset] =
        response.aux_electrically_unstimulated ? 1U : 0U;
    payload[protocol_v2::
                kGpioCaptureDiagnosticResponseAuxExternalTransitionChecksRunOffset] =
        response.aux_external_transition_checks_run ? 1U : 0U;
#define STORE_AUX_DIAGNOSTIC_U32(field, member)                            \
  storeU32(bytes,                                                         \
           protocol_v2::kGpioCaptureDiagnosticResponse##field##Offset,    \
           response.member)
#define STORE_AUX_DIAGNOSTIC_U16(field, member)                            \
  storeU16(bytes,                                                         \
           protocol_v2::kGpioCaptureDiagnosticResponse##field##Offset,    \
           response.member)
    STORE_AUX_DIAGNOSTIC_U32(ConfiguredRateHz, configured_rate_hz);
    STORE_AUX_DIAGNOSTIC_U32(AuxHardwareErrorFlags,
                             aux_hardware_error_flags);
    STORE_AUX_DIAGNOSTIC_U32(AuxDiagnosticFlags, aux_diagnostic_flags);
    storeU64(bytes,
             protocol_v2::
                 kGpioCaptureDiagnosticResponseAuxDmaSamplesCapturedOffset,
             response.aux_dma_samples_captured);
    STORE_AUX_DIAGNOSTIC_U32(AuxCompleteSamplesRetained,
                             aux_complete_samples_retained);
    STORE_AUX_DIAGNOSTIC_U32(AuxSamplesAnalyzed, aux_samples_analyzed);
    STORE_AUX_DIAGNOSTIC_U32(AuxStoppedPartialSamples,
                             aux_stopped_partial_samples);
    STORE_AUX_DIAGNOSTIC_U32(AuxRawWordAnd, aux_raw_word_and);
    STORE_AUX_DIAGNOSTIC_U32(AuxRawWordOr, aux_raw_word_or);
    STORE_AUX_DIAGNOSTIC_U32(AuxObservedTransitions,
                             aux_observed_transitions);
    payload[protocol_v2::kGpioCaptureDiagnosticResponseAuxPackedValueAndOffset] =
        response.aux_packed_value_and;
    payload[protocol_v2::kGpioCaptureDiagnosticResponseAuxPackedValueOrOffset] =
        response.aux_packed_value_or;
    payload[protocol_v2::kGpioCaptureDiagnosticResponseAuxFirstPackedValueOffset] =
        response.aux_first_packed_value;
    payload[protocol_v2::kGpioCaptureDiagnosticResponseAuxLastPackedValueOffset] =
        response.aux_last_packed_value;
    STORE_AUX_DIAGNOSTIC_U32(Gpr26Before, gpr26_before);
    STORE_AUX_DIAGNOSTIC_U32(Gpr26Configured, gpr26_configured);
    STORE_AUX_DIAGNOSTIC_U32(Gpr26After, gpr26_after);
    STORE_AUX_DIAGNOSTIC_U32(Gpio1GdirBefore, gpio1_gdir_before);
    STORE_AUX_DIAGNOSTIC_U32(Gpio1GdirConfigured, gpio1_gdir_configured);
    STORE_AUX_DIAGNOSTIC_U32(Gpio1GdirAfter, gpio1_gdir_after);
    STORE_AUX_DIAGNOSTIC_U32(Gpio1PsrBefore, gpio1_psr_before);
    STORE_AUX_DIAGNOSTIC_U32(Gpio1PsrConfigured, gpio1_psr_configured);
    STORE_AUX_DIAGNOSTIC_U32(Gpio1PsrAfter, gpio1_psr_after);
    STORE_AUX_DIAGNOSTIC_U32(AuxDmamuxChcfgConfigured,
                             aux_dmamux_chcfg_configured);
    STORE_AUX_DIAGNOSTIC_U32(AuxDmaErqConfigured, aux_dma_erq_configured);
    STORE_AUX_DIAGNOSTIC_U32(AuxDmaErrFinal, aux_dma_err_final);
    STORE_AUX_DIAGNOSTIC_U16(AuxTcdCiterConfigured,
                             aux_tcd_citer_configured);
    STORE_AUX_DIAGNOSTIC_U16(AuxTcdBiterConfigured,
                             aux_tcd_biter_configured);
    STORE_AUX_DIAGNOSTIC_U16(AuxTcdCsrConfigured, aux_tcd_csr_configured);
    payload[protocol_v2::
                kGpioCaptureDiagnosticResponseAuxEdmaPriorityConfiguredOffset] =
        response.aux_edma_priority_configured;
    storeU32(bytes,
             protocol_v2::
                 kGpioCaptureDiagnosticResponsePrimaryCacheDmaDiscardsOffset,
             response.cache_dma_discards[0]);
    storeU32(bytes,
             protocol_v2::
                 kGpioCaptureDiagnosticResponseAuxCacheDmaDiscardsOffset,
             response.cache_dma_discards[1]);
    storeU32(bytes,
             protocol_v2::
                 kGpioCaptureDiagnosticResponsePrimaryCacheCpuInvalidationsOffset,
             response.cache_cpu_invalidations[0]);
    storeU32(bytes,
             protocol_v2::
                 kGpioCaptureDiagnosticResponseAuxCacheCpuInvalidationsOffset,
             response.cache_cpu_invalidations[1]);
#undef STORE_AUX_DIAGNOSTIC_U16
#undef STORE_AUX_DIAGNOSTIC_U32
  }
  return encodeFrame(
      responseFields(
          protocol_v1::FrameKind::kGpioCaptureDiagnosticResponse, request,
          run_id),
      {payload.data(),
       version2 ? protocol_v2::kGpioCaptureDiagnosticResponsePayloadSize
                : protocol_v1::kGpioCaptureDiagnosticResponsePayloadSize},
      output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.typed_error_response")
Result encodeTypedErrorResponse(const Request &request, std::uint32_t run_id,
                                protocol_v1::ErrorCode error,
                                ControlFrame &output) {
  if (request.request_id == 0U) {
    return badRequestId();
  }
  if (!isKnownError(error) || error == protocol_v1::ErrorCode::kOk) {
    return badPayload();
  }
  const protocol_v1::FrameKind request_kind = request.kind == kGetTemperature
      ? kTemperatureRequest : protocol_v1::requestFrameKind(request.kind);
  protocol_v1::CommandKind checked{};
  if (!commandForKind(request_kind, checked) || checked != request.kind) {
    return badKind();
  }
  std::array<std::uint8_t, protocol_v1::kResponsePrefixPayloadSize> payload{};
  writeErrorPrefix(mutableView(payload), error);
  return encodeFrame(
      responseFields(request.kind == kGetTemperature ? kTemperatureResponse
                     : protocol_v1::responseFrameKind(request.kind), request,
                     run_id, kResponseErrorFlag),
      view(payload), output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.temperature_response")
Result encodeTemperatureResponse(const Request &request, std::uint32_t run_id,
                                 temperature::Reading reading, ControlFrame &output) {
  if (request.kind != kGetTemperature || request.protocol_version != 2) return badKind();
  std::array<std::uint8_t, protocol_v2::kTemperatureResponsePayloadSize> payload{};
  payload[4] = static_cast<std::uint8_t>(reading.status);
  storeU32(mutableView(payload), 8, static_cast<std::uint32_t>(reading.millidegrees_c));
  return encodeFrame(responseFields(kTemperatureResponse, request, run_id), view(payload), output);
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.rejected_frame_response")
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
    const DrainResult drained = drain(command);
    if (drained != DrainResult::kNone) {
      result.command_ready = drained == DrainResult::kCommand;
      result.rejection_ready = drained == DrainResult::kRejection;
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

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.parser_session_reset")
void IncrementalCommandParser::resetSession() {
  if (buffered_ != 0U) {
    discard(buffered_);
  }
  resynchronizing_ = false;
}

ParserCounters IncrementalCommandParser::counters() const {
  ParserCounters result = counters_;
  result.buffered_bytes = buffered_;
  return result;
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.command_parser_drain")
IncrementalCommandParser::DrainResult IncrementalCommandParser::drain(
    ParsedCommand &command) {
  while (true) {
    const std::size_t magic_at = findMagic();
    if (magic_at == kNotFound) {
      const std::size_t retained = partialMagicSuffix();
      discard(buffered_ - retained);
      return DrainResult::kNone;
    }
    if (magic_at != 0U) {
      discard(magic_at);
    }
    if (buffered_ < protocol_v1::kHeaderSize) {
      return DrainResult::kNone;
    }
    FrameHeader header{};
    Result result = decodeHeader({buffer_.data(), buffered_}, header, true);
    if (!result.ok()) {
      recordFailure(result);
      const bool rejection_ready = describeRejection(result, command);
      discard(1U);
      if (rejection_ready) {
        return DrainResult::kRejection;
      }
      continue;
    }
    if (buffered_ < header.total_length) {
      return DrainResult::kNone;
    }
    Request request{};
    result = decodeRequest({buffer_.data(), header.total_length}, request);
    if (!result.ok()) {
      recordFailure(result);
      const bool rejection_ready = describeRejection(result, command);
      discard(1U);
      if (rejection_ready) {
        return DrainResult::kRejection;
      }
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
    return DrainResult::kCommand;
  }
}

THINGDAQ_PROTOCOL_COLD_CODE(".flashmem.protocol.parser_rejection")
bool IncrementalCommandParser::describeRejection(
    const Result &failure, ParsedCommand &command) const {
  if (failure.ok() || buffered_ < protocol_v1::kHeaderSize) {
    return false;
  }
  std::uint32_t request_id = 0U;
  if (!loadU32({buffer_.data(), buffered_},
               protocol_v1::kHeaderRequestIdOffset, request_id) ||
      request_id == 0U) {
    return false;
  }

  ParsedCommand rejected{};
  rejected.rejection_error = failure.error;
  rejected.rejected_request_id = request_id;
  rejected.rejected_kind =
      buffer_[protocol_v1::kHeaderKindOffset];
  rejected.rejected_version =
      buffer_[protocol_v1::kHeaderVersionOffset];
  command = rejected;
  return true;
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

}  // namespace thingdaq::protocol

#undef THINGDAQ_PROTOCOL_COLD_CODE
