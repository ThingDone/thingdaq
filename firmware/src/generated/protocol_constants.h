// Generated from protocol/protocol-v1.json. Do not edit by hand.
// Source SHA-256: 8adde2428ca6058f658a2ddc8b6581dbe42e326e1cbb5320fb8daa406e44ad84
#pragma once

#include <cstddef>
#include <cstdint>

namespace teensy_daq::protocol_v1 {

inline constexpr char kSourceSha256[] = "8adde2428ca6058f658a2ddc8b6581dbe42e326e1cbb5320fb8daa406e44ad84";
inline constexpr std::uint32_t kMagic = 0xDEADBEEFU;
inline constexpr std::uint8_t kProtocolVersion = 1U;
inline constexpr bool kWireIsLittleEndian = true;
inline constexpr std::size_t kHeaderSize = 44U;
inline constexpr std::size_t kTrailerSize = 4U;
inline constexpr std::size_t kMinFrameBytes = 48U;
inline constexpr std::size_t kDataFrameBytes = 4096U;
inline constexpr std::size_t kMaxDataFrameBytes = 4096U;
inline constexpr std::size_t kDataPayloadBytes = 4048U;
inline constexpr std::size_t kMaxControlFrameBytes = 1024U;
inline constexpr std::size_t kMaxControlPayloadBytes =
    kMaxControlFrameBytes - kHeaderSize - kTrailerSize;
inline constexpr std::size_t kMaxCommandFrameBytes = 56U;
inline constexpr std::size_t kMaxCommandPayloadBytes = 8U;
inline constexpr std::uint32_t kTimestampHz = 8000000U;
inline constexpr std::uint32_t kAdcPairRateHz = 1000000U;
inline constexpr std::uint32_t kAdcPairPeriodTicks = 8U;
inline constexpr std::uint32_t kAdc1PhaseTicks = 4U;
inline constexpr std::uint32_t kGpioSampleRateHz = 4000000U;
inline constexpr std::uint32_t kGpioSamplePeriodTicks = 2U;
inline constexpr std::uint32_t kFrameCoverageTicks = 8096U;
inline constexpr std::uint32_t kChecksumBenchmarkCycleCounterHz = 600000000U;
inline constexpr std::uint32_t kChecksumBenchmarkTargetFramedBytesPerSecond = 8100000U;
inline constexpr std::uint16_t kChecksumBenchmarkMaxBatchCount = 8U;
inline constexpr std::uint16_t kChecksumBenchmarkMaxIterationsPerBatch = 4096U;
inline constexpr std::uint32_t kChecksumBenchmarkMaxOperations = 32768U;
inline constexpr std::uint32_t kChecksumBenchmarkMaxProcessedBytes = 8388608U;
inline constexpr std::uint16_t kChecksumBenchmarkTimerCalibrationSamples = 32U;
inline constexpr std::uint16_t kChecksumBenchmarkWarmupOperations = 4U;
inline constexpr std::size_t kAdcBytesPerPair = 4U;
inline constexpr std::size_t kAdcPairsPerFrame = 1012U;
inline constexpr std::uint8_t kAdcResolutionBits = 12U;
inline constexpr std::uint8_t kAdcContainerBits = 16U;
inline constexpr std::size_t kGpioSamplesPerFrame = 4048U;
inline constexpr std::uint8_t kGpioPinsByBit[] = {6U, 7U, 8U, 9U, 10U, 11U, 12U, 13U};

inline constexpr std::size_t kHeaderMagicOffset = 0U;
inline constexpr std::size_t kHeaderVersionOffset = 4U;
inline constexpr std::size_t kHeaderKindOffset = 5U;
inline constexpr std::size_t kHeaderFlagsOffset = 6U;
inline constexpr std::size_t kHeaderHeaderLengthOffset = 8U;
inline constexpr std::size_t kHeaderChecksumAlgorithmOffset = 10U;
inline constexpr std::size_t kHeaderReservedOffset = 11U;
inline constexpr std::size_t kHeaderTotalLengthOffset = 12U;
inline constexpr std::size_t kHeaderPayloadLengthOffset = 16U;
inline constexpr std::size_t kHeaderRunIdOffset = 20U;
inline constexpr std::size_t kHeaderSequenceOffset = 24U;
inline constexpr std::size_t kHeaderRequestIdOffset = 28U;
inline constexpr std::size_t kHeaderFirstSampleTicksOffset = 32U;
inline constexpr std::size_t kHeaderItemCountOffset = 40U;

enum class FrameKind : std::uint8_t {
  kAdcData = 1U,
  kGpioData = 2U,
  kInfoRequest = 16U,
  kConfigureRequest = 17U,
  kStartRequest = 18U,
  kGetStatusRequest = 19U,
  kStopRequest = 20U,
  kResetStatsRequest = 21U,
  kPingRequest = 22U,
  kChecksumBenchmarkRequest = 23U,
  kInfoResponse = 144U,
  kConfigureResponse = 145U,
  kStartResponse = 146U,
  kGetStatusResponse = 147U,
  kStopResponse = 148U,
  kResetStatsResponse = 149U,
  kPingResponse = 150U,
  kChecksumBenchmarkResponse = 151U,
  kErrorResponse = 159U,
};

enum class CommandKind : std::uint8_t {
  kInfo = 16U,
  kConfigure = 17U,
  kStart = 18U,
  kGetStatus = 19U,
  kStop = 20U,
  kResetStats = 21U,
  kPing = 22U,
  kChecksumBenchmark = 23U,
};

enum class FrameFlag : std::uint16_t {
  kSynthetic = 1U,
  kGapBefore = 2U,
  kEpochStart = 4U,
  kOverrunBefore = 8U,
  kResponseError = 32768U,
};

enum class ChecksumAlgorithm : std::uint8_t {
  kNoneReserved = 0U,
  kAdler32 = 1U,
  kCrc32c = 2U,
  kCrc32IsoHdlc = 3U,
};

enum class ResponseStatus : std::uint8_t {
  kOk = 0U,
  kError = 1U,
};

enum class ErrorCode : std::uint16_t {
  kOk = 0U,
  kUnsupportedVersion = 1U,
  kUnknownFrameKind = 2U,
  kInvalidFlags = 3U,
  kInvalidLength = 4U,
  kInvalidPayload = 5U,
  kUnsupportedChecksum = 6U,
  kInvalidState = 7U,
  kUnsupportedConfiguration = 8U,
  kInvalidRequestId = 9U,
  kBusy = 10U,
  kInternalError = 11U,
  kChecksumMismatch = 12U,
};

enum class DeviceState : std::uint8_t {
  kBoot = 0U,
  kIdle = 1U,
  kConfigured = 2U,
  kRunning = 3U,
};

enum class StreamMask : std::uint8_t {
  kAdc = 1U,
  kGpio = 2U,
};

enum class Capability : std::uint32_t {
  kAdcStream = 1U,
  kGpioStream = 2U,
  kHardwareSource = 4U,
  kSyntheticSource = 8U,
  kResetStats = 16U,
  kPing = 32U,
  kChecksumBenchmark = 64U,
};

enum class Source : std::uint8_t {
  kHardware = 0U,
  kSynthetic = 1U,
};

enum class BoardId : std::uint16_t {
  kSimulator = 0U,
  kTeensy40 = 1U,
};

enum class McuId : std::uint16_t {
  kSimulated = 0U,
  kImxrt1062 = 1U,
};

enum class BenchmarkVector : std::uint8_t {
  kEmpty = 0U,
  kCanonical123456789 = 1U,
  kBuffer64 = 2U,
  kBuffer512 = 3U,
  kFrameCoverage = 4U,
};

enum class BenchmarkMemoryRegion : std::uint8_t {
  kDtcmPacket = 0U,
  kOcramDma = 1U,
};

enum class BenchmarkCacheState : std::uint8_t {
  kHotOrNative = 0U,
  kColdInvalidated = 1U,
};

inline constexpr ChecksumAlgorithm kBootstrapChecksumAlgorithm =
    ChecksumAlgorithm::kAdler32;
inline constexpr ChecksumAlgorithm kDefaultChecksumAlgorithm =
    ChecksumAlgorithm::kAdler32;
inline constexpr std::uint32_t kSupportedChecksumMask = 14U;
inline constexpr std::uint16_t kKnownFrameFlagMask = 32783U;
inline constexpr std::uint32_t kKnownCapabilityMask = 127U;

inline constexpr std::size_t kEmptyPayloadSize = 0U;
inline constexpr std::size_t kAdcDataPayloadSize = 4048U;
inline constexpr std::size_t kAdcDataPairsOffset = 0U;
inline constexpr std::size_t kAdcDataPairsCount = 1012U;
inline constexpr std::size_t kGpioDataPayloadSize = 4048U;
inline constexpr std::size_t kGpioDataSamplesOffset = 0U;
inline constexpr std::size_t kGpioDataSamplesCount = 4048U;
inline constexpr std::size_t kConfigureRequestPayloadSize = 8U;
inline constexpr std::size_t kConfigureRequestStreamMaskOffset = 0U;
inline constexpr std::size_t kConfigureRequestSourceOffset = 1U;
inline constexpr std::size_t kConfigureRequestDataChecksumAlgorithmOffset = 2U;
inline constexpr std::size_t kConfigureRequestReservedOffset = 3U;
inline constexpr std::size_t kConfigureRequestDataFrameBytesOffset = 4U;
inline constexpr std::size_t kResponsePrefixPayloadSize = 4U;
inline constexpr std::size_t kResponsePrefixResponseStatusOffset = 0U;
inline constexpr std::size_t kResponsePrefixReservedOffset = 1U;
inline constexpr std::size_t kResponsePrefixErrorCodeOffset = 2U;
inline constexpr std::size_t kInfoResponsePayloadSize = 98U;
inline constexpr std::size_t kInfoResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kInfoResponseReserved0Offset = 1U;
inline constexpr std::size_t kInfoResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kInfoResponseDeviceStateOffset = 4U;
inline constexpr std::size_t kInfoResponseProtocolVersionOffset = 5U;
inline constexpr std::size_t kInfoResponseSupportedStreamMaskOffset = 6U;
inline constexpr std::size_t kInfoResponseSupportedSourceMaskOffset = 7U;
inline constexpr std::size_t kInfoResponseSupportedChecksumMaskOffset = 8U;
inline constexpr std::size_t kInfoResponseCapabilityBitsOffset = 12U;
inline constexpr std::size_t kInfoResponseTimestampHzOffset = 16U;
inline constexpr std::size_t kInfoResponseDataFrameBytesOffset = 20U;
inline constexpr std::size_t kInfoResponseMaxControlFrameBytesOffset = 24U;
inline constexpr std::size_t kInfoResponseAdcPairRateHzOffset = 28U;
inline constexpr std::size_t kInfoResponseGpioSampleRateHzOffset = 32U;
inline constexpr std::size_t kInfoResponseAdcPairPeriodTicksOffset = 36U;
inline constexpr std::size_t kInfoResponseAdc1PhaseTicksOffset = 38U;
inline constexpr std::size_t kInfoResponseGpioSamplePeriodTicksOffset = 40U;
inline constexpr std::size_t kInfoResponseAdcResolutionBitsOffset = 42U;
inline constexpr std::size_t kInfoResponseAdcContainerBytesOffset = 43U;
inline constexpr std::size_t kInfoResponseGpioPinCountOffset = 44U;
inline constexpr std::size_t kInfoResponseDataChecksumAlgorithmOffset = 45U;
inline constexpr std::size_t kInfoResponseGpioPinMapOffset = 46U;
inline constexpr std::size_t kInfoResponseGpioPinMapCount = 8U;
inline constexpr std::size_t kInfoResponseHardwareSerialOffset = 54U;
inline constexpr std::size_t kInfoResponseFirmwareVersionMajorOffset = 58U;
inline constexpr std::size_t kInfoResponseFirmwareVersionMinorOffset = 59U;
inline constexpr std::size_t kInfoResponseFirmwareVersionPatchOffset = 60U;
inline constexpr std::size_t kInfoResponseReserved2Offset = 61U;
inline constexpr std::size_t kInfoResponseBoardIdOffset = 62U;
inline constexpr std::size_t kInfoResponseMcuIdOffset = 64U;
inline constexpr std::size_t kInfoResponseBuildIdOffset = 66U;
inline constexpr std::size_t kInfoResponseBuildIdCount = 32U;
inline constexpr std::size_t kConfigureResponsePayloadSize = 12U;
inline constexpr std::size_t kConfigureResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kConfigureResponseReserved0Offset = 1U;
inline constexpr std::size_t kConfigureResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kConfigureResponseStreamMaskOffset = 4U;
inline constexpr std::size_t kConfigureResponseSourceOffset = 5U;
inline constexpr std::size_t kConfigureResponseDataChecksumAlgorithmOffset = 6U;
inline constexpr std::size_t kConfigureResponseReserved1Offset = 7U;
inline constexpr std::size_t kConfigureResponseDataFrameBytesOffset = 8U;
inline constexpr std::size_t kStatusResponsePayloadSize = 56U;
inline constexpr std::size_t kStatusResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kStatusResponseReservedOffset = 1U;
inline constexpr std::size_t kStatusResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kStatusResponseDeviceStateOffset = 4U;
inline constexpr std::size_t kStatusResponseStreamMaskOffset = 5U;
inline constexpr std::size_t kStatusResponseSourceOffset = 6U;
inline constexpr std::size_t kStatusResponseDataChecksumAlgorithmOffset = 7U;
inline constexpr std::size_t kStatusResponseDataFrameBytesOffset = 8U;
inline constexpr std::size_t kStatusResponseAdcFramesEmittedOffset = 12U;
inline constexpr std::size_t kStatusResponseGpioFramesEmittedOffset = 20U;
inline constexpr std::size_t kStatusResponseAdcItemsDroppedOffset = 28U;
inline constexpr std::size_t kStatusResponseGpioItemsDroppedOffset = 36U;
inline constexpr std::size_t kStatusResponseParserErrorsOffset = 44U;
inline constexpr std::size_t kStatusResponseTransportErrorsOffset = 48U;
inline constexpr std::size_t kStatusResponseStatsGenerationOffset = 52U;
inline constexpr std::size_t kStopResponsePayloadSize = 8U;
inline constexpr std::size_t kStopResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kStopResponseReserved0Offset = 1U;
inline constexpr std::size_t kStopResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kStopResponseDeviceStateOffset = 4U;
inline constexpr std::size_t kStopResponseReserved1Offset = 5U;
inline constexpr std::size_t kStopResponseReserved2Offset = 6U;
inline constexpr std::size_t kResetStatsResponsePayloadSize = 8U;
inline constexpr std::size_t kResetStatsResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kResetStatsResponseReservedOffset = 1U;
inline constexpr std::size_t kResetStatsResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kResetStatsResponseStatsGenerationOffset = 4U;
inline constexpr std::size_t kPingRequestPayloadSize = 8U;
inline constexpr std::size_t kPingRequestNonceOffset = 0U;
inline constexpr std::size_t kPingResponsePayloadSize = 12U;
inline constexpr std::size_t kPingResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kPingResponseReservedOffset = 1U;
inline constexpr std::size_t kPingResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kPingResponseNonceOffset = 4U;
inline constexpr std::size_t kChecksumBenchmarkRequestPayloadSize = 8U;
inline constexpr std::size_t kChecksumBenchmarkRequestChecksumAlgorithmOffset = 0U;
inline constexpr std::size_t kChecksumBenchmarkRequestVectorOffset = 1U;
inline constexpr std::size_t kChecksumBenchmarkRequestMemoryRegionOffset = 2U;
inline constexpr std::size_t kChecksumBenchmarkRequestCacheStateOffset = 3U;
inline constexpr std::size_t kChecksumBenchmarkRequestBatchCountOffset = 4U;
inline constexpr std::size_t kChecksumBenchmarkRequestIterationsPerBatchOffset = 6U;
inline constexpr std::size_t kChecksumBenchmarkResponsePayloadSize = 96U;
inline constexpr std::size_t kChecksumBenchmarkResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kChecksumBenchmarkResponseReservedOffset = 1U;
inline constexpr std::size_t kChecksumBenchmarkResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kChecksumBenchmarkResponseChecksumAlgorithmOffset = 4U;
inline constexpr std::size_t kChecksumBenchmarkResponseVectorOffset = 5U;
inline constexpr std::size_t kChecksumBenchmarkResponseMemoryRegionOffset = 6U;
inline constexpr std::size_t kChecksumBenchmarkResponseCacheStateOffset = 7U;
inline constexpr std::size_t kChecksumBenchmarkResponseBatchCountOffset = 8U;
inline constexpr std::size_t kChecksumBenchmarkResponseIterationsPerBatchOffset = 10U;
inline constexpr std::size_t kChecksumBenchmarkResponseBufferBytesOffset = 12U;
inline constexpr std::size_t kChecksumBenchmarkResponseCycleCounterHzOffset = 16U;
inline constexpr std::size_t kChecksumBenchmarkResponseTimerOverheadCyclesOffset = 20U;
inline constexpr std::size_t kChecksumBenchmarkResponseImplementationCodeBytesOffset = 24U;
inline constexpr std::size_t kChecksumBenchmarkResponseTableBytesOffset = 28U;
inline constexpr std::size_t kChecksumBenchmarkResponseWorkingRamBytesOffset = 32U;
inline constexpr std::size_t kChecksumBenchmarkResponseDeterministicDigestOffset = 36U;
inline constexpr std::size_t kChecksumBenchmarkResponseProcessedBytesOffset = 40U;
inline constexpr std::size_t kChecksumBenchmarkResponseRawChecksumCyclesOffset = 48U;
inline constexpr std::size_t kChecksumBenchmarkResponseNetChecksumCyclesOffset = 56U;
inline constexpr std::size_t kChecksumBenchmarkResponseCacheSetupCyclesOffset = 64U;
inline constexpr std::size_t kChecksumBenchmarkResponseMinBatchCyclesOffset = 72U;
inline constexpr std::size_t kChecksumBenchmarkResponseMaxBatchCyclesOffset = 76U;
inline constexpr std::size_t kChecksumBenchmarkResponseCyclesPerByteQ16Offset = 80U;
inline constexpr std::size_t kChecksumBenchmarkResponseMbPerSecondQ16Offset = 84U;
inline constexpr std::size_t kChecksumBenchmarkResponseProjectedCpuPercentQ16Offset = 88U;
inline constexpr std::size_t kChecksumBenchmarkResponseTargetFramedBytesPerSecondOffset = 92U;
inline constexpr std::size_t kErrorResponsePayloadSize = 8U;
inline constexpr std::size_t kErrorResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kErrorResponseReserved0Offset = 1U;
inline constexpr std::size_t kErrorResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kErrorResponseRejectedKindOffset = 4U;
inline constexpr std::size_t kErrorResponseRejectedVersionOffset = 5U;
inline constexpr std::size_t kErrorResponseReserved1Offset = 6U;

constexpr std::uint16_t allowedFlags(FrameKind kind) {
  switch (kind) {
    case FrameKind::kAdcData:
      return static_cast<std::uint16_t>(FrameFlag::kSynthetic) | static_cast<std::uint16_t>(FrameFlag::kGapBefore) | static_cast<std::uint16_t>(FrameFlag::kEpochStart) | static_cast<std::uint16_t>(FrameFlag::kOverrunBefore);
    case FrameKind::kGpioData:
      return static_cast<std::uint16_t>(FrameFlag::kSynthetic) | static_cast<std::uint16_t>(FrameFlag::kGapBefore) | static_cast<std::uint16_t>(FrameFlag::kEpochStart) | static_cast<std::uint16_t>(FrameFlag::kOverrunBefore);
    case FrameKind::kInfoRequest:
      return 0U;
    case FrameKind::kConfigureRequest:
      return 0U;
    case FrameKind::kStartRequest:
      return 0U;
    case FrameKind::kGetStatusRequest:
      return 0U;
    case FrameKind::kStopRequest:
      return 0U;
    case FrameKind::kResetStatsRequest:
      return 0U;
    case FrameKind::kPingRequest:
      return 0U;
    case FrameKind::kChecksumBenchmarkRequest:
      return 0U;
    case FrameKind::kInfoResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kConfigureResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kStartResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kGetStatusResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kStopResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kResetStatsResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kPingResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kChecksumBenchmarkResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kErrorResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
  }
  return 0U;
}

constexpr FrameKind requestFrameKind(CommandKind command) {
  switch (command) {
    case CommandKind::kInfo:
      return FrameKind::kInfoRequest;
    case CommandKind::kConfigure:
      return FrameKind::kConfigureRequest;
    case CommandKind::kStart:
      return FrameKind::kStartRequest;
    case CommandKind::kGetStatus:
      return FrameKind::kGetStatusRequest;
    case CommandKind::kStop:
      return FrameKind::kStopRequest;
    case CommandKind::kResetStats:
      return FrameKind::kResetStatsRequest;
    case CommandKind::kPing:
      return FrameKind::kPingRequest;
    case CommandKind::kChecksumBenchmark:
      return FrameKind::kChecksumBenchmarkRequest;
  }
  return FrameKind::kInfoRequest;
}

constexpr FrameKind responseFrameKind(CommandKind command) {
  switch (command) {
    case CommandKind::kInfo:
      return FrameKind::kInfoResponse;
    case CommandKind::kConfigure:
      return FrameKind::kConfigureResponse;
    case CommandKind::kStart:
      return FrameKind::kStartResponse;
    case CommandKind::kGetStatus:
      return FrameKind::kGetStatusResponse;
    case CommandKind::kStop:
      return FrameKind::kStopResponse;
    case CommandKind::kResetStats:
      return FrameKind::kResetStatsResponse;
    case CommandKind::kPing:
      return FrameKind::kPingResponse;
    case CommandKind::kChecksumBenchmark:
      return FrameKind::kChecksumBenchmarkResponse;
  }
  return FrameKind::kInfoResponse;
}

static_assert(kHeaderSize + kDataPayloadBytes + kTrailerSize ==
              kDataFrameBytes);
static_assert(kAdcPairsPerFrame * kAdcBytesPerPair ==
              kDataPayloadBytes);
static_assert(kGpioSamplesPerFrame == kDataPayloadBytes);

}  // namespace teensy_daq::protocol_v1
