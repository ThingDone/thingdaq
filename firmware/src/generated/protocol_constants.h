// Generated from protocol/protocol-v1.json. Do not edit by hand.
// Source SHA-256: 2662258599d7ac0686e646a006b0894a272e3809b705c3a6fbbef17b4e40279c
#pragma once

#include <cstddef>
#include <cstdint>

namespace teensy_daq::protocol_v1 {

inline constexpr char kSourceSha256[] = "2662258599d7ac0686e646a006b0894a272e3809b705c3a6fbbef17b4e40279c";
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
inline constexpr std::uint32_t kGpioClockPitHz = 24000000U;
inline constexpr std::uint32_t kGpioClockDwtHz = 600000000U;
inline constexpr std::uint32_t kGpioClockProductionRateHz = 4000000U;
inline constexpr std::uint32_t kGpioClockMinRateHz = 1000U;
inline constexpr std::uint16_t kGpioClockMinEventCount = 32U;
inline constexpr std::uint16_t kGpioClockMaxEventCount = 8192U;
inline constexpr std::uint32_t kGpioClockMaxElapsedCycles = 60000000U;
inline constexpr std::uint16_t kGpioClockDuplicateGuardEvents = 16U;
inline constexpr std::uint32_t kGpioClockCountTolerance = 1U;
inline constexpr std::uint8_t kGpioPackedWidthBits = 8U;
inline constexpr std::uint8_t kGpioRawRingDepth = 4U;
inline constexpr std::uint32_t kGpioRawSamplesPerBuffer = 4048U;
inline constexpr std::uint32_t kGpioRawRingBytes = 64768U;
inline constexpr std::uint8_t kGpioPackedRingDepth = 4U;
inline constexpr std::uint32_t kGpioPackedRingBytes = 16256U;
inline constexpr std::uint16_t kGpioPacketBufferCount = 200U;
inline constexpr std::uint8_t kGpioPitChannel = 0U;
inline constexpr std::uint8_t kGpioXbarInput = 56U;
inline constexpr std::uint8_t kGpioXbarOutput = 0U;
inline constexpr std::uint8_t kGpioXbarActiveEdge = 1U;
inline constexpr std::uint8_t kGpioEdmaChannel = 2U;
inline constexpr std::uint8_t kGpioDmamuxSource = 30U;
inline constexpr std::uint8_t kGpioEdmaPriority = 2U;
inline constexpr std::uint32_t kGpioCaptureDiagnosticAnalysisSamples = 256U;
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
  kGpioClockDiagnosticRequest = 24U,
  kGpioCaptureDiagnosticRequest = 25U,
  kInfoResponse = 144U,
  kConfigureResponse = 145U,
  kStartResponse = 146U,
  kGetStatusResponse = 147U,
  kStopResponse = 148U,
  kResetStatsResponse = 149U,
  kPingResponse = 150U,
  kChecksumBenchmarkResponse = 151U,
  kGpioClockDiagnosticResponse = 152U,
  kGpioCaptureDiagnosticResponse = 153U,
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
  kGpioClockDiagnostic = 24U,
  kGpioCaptureDiagnostic = 25U,
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
  kGpioClockDiagnostic = 128U,
  kGpioCaptureDiagnostic = 256U,
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

enum class GpioClockError : std::uint32_t {
  kDwtUnavailable = 1U,
  kResourceBusy = 2U,
  kPerclkMismatch = 4U,
  kPitGateDisabled = 8U,
  kXbarGateDisabled = 16U,
  kDmaGateDisabled = 32U,
  kPitConfigMismatch = 64U,
  kXbarConfigMismatch = 128U,
  kDmamuxConfigMismatch = 256U,
  kEdmaConfigMismatch = 512U,
  kEdmaChannelError = 1024U,
  kDeadTrigger = 2048U,
  kDuplicateTrigger = 4096U,
  kCountOutOfTolerance = 8192U,
  kMeasurementOverflow = 16384U,
};

enum class GpioCaptureDiagnosticMode : std::uint8_t {
  kNonDrivingCapture = 0U,
  kSelfDrivenSweep = 1U,
  kFixtureStimulus = 2U,
};

enum class GpioCaptureDiagnosticFlag : std::uint32_t {
  kAvailable = 1U,
  kDeclarationValid = 2U,
  kOutputDrivePermitted = 4U,
  kExternalStimulusDeclared = 8U,
  kDmaCaptureExercised = 16U,
  kPackedObservationExercised = 32U,
  kOutputDriveExercised = 64U,
  kExternalTransitionValidationExercised = 128U,
  kFinalInputSafe = 256U,
};

enum class GpioCaptureError : std::uint32_t {
  kFixtureDeclarationInvalid = 1U,
  kUnsupportedFixtureMode = 2U,
  kDwtUnavailable = 4U,
  kResourceBusy = 8U,
  kCaptureTimeout = 16U,
  kCaptureFault = 32U,
  kNoCompleteBuffer = 64U,
  kDiagnosticLeaseError = 128U,
  kCountMismatch = 256U,
  kUnsafeConfiguredDirection = 512U,
  kUnsafeInputRestore = 1024U,
  kMappingMismatch = 2048U,
  kUnexpectedOutputDrive = 4096U,
  kExternalValidationMissing = 8192U,
  kUnexpectedElectricalClaim = 16384U,
  kCleanupFailed = 32768U,
};

inline constexpr ChecksumAlgorithm kBootstrapChecksumAlgorithm =
    ChecksumAlgorithm::kAdler32;
inline constexpr ChecksumAlgorithm kDefaultChecksumAlgorithm =
    ChecksumAlgorithm::kAdler32;
inline constexpr std::uint32_t kSupportedChecksumMask = 14U;
inline constexpr std::uint16_t kKnownFrameFlagMask = 32783U;
inline constexpr std::uint32_t kKnownCapabilityMask = 511U;
inline constexpr std::uint32_t kKnownGpioClockErrorMask = 32767U;
inline constexpr std::uint32_t kKnownGpioCaptureDiagnosticFlagMask = 511U;
inline constexpr std::uint32_t kKnownGpioCaptureErrorMask = 65535U;

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
inline constexpr std::size_t kInfoResponsePayloadSize = 128U;
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
inline constexpr std::size_t kInfoResponseGpioPackedWidthBitsOffset = 98U;
inline constexpr std::size_t kInfoResponseGpioRawRingDepthOffset = 99U;
inline constexpr std::size_t kInfoResponseGpioPackedRingDepthOffset = 100U;
inline constexpr std::size_t kInfoResponseGpioCaptureDiagnosticModeOffset = 101U;
inline constexpr std::size_t kInfoResponseGpioCaptureDiagnosticFlagsOffset = 102U;
inline constexpr std::size_t kInfoResponseGpioRawSamplesPerBufferOffset = 104U;
inline constexpr std::size_t kInfoResponseGpioRawRingBytesOffset = 108U;
inline constexpr std::size_t kInfoResponseGpioPackedRingBytesOffset = 112U;
inline constexpr std::size_t kInfoResponseGpioPacketBufferCountOffset = 116U;
inline constexpr std::size_t kInfoResponseReserved3Offset = 118U;
inline constexpr std::size_t kInfoResponseGpioPitChannelOffset = 120U;
inline constexpr std::size_t kInfoResponseGpioXbarInputOffset = 121U;
inline constexpr std::size_t kInfoResponseGpioXbarOutputOffset = 122U;
inline constexpr std::size_t kInfoResponseGpioEdmaChannelOffset = 123U;
inline constexpr std::size_t kInfoResponseGpioDmamuxSourceOffset = 124U;
inline constexpr std::size_t kInfoResponseGpioEdmaPriorityOffset = 125U;
inline constexpr std::size_t kInfoResponseGpioXbarActiveEdgeOffset = 126U;
inline constexpr std::size_t kInfoResponseReserved4Offset = 127U;
inline constexpr std::size_t kConfigureResponsePayloadSize = 12U;
inline constexpr std::size_t kConfigureResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kConfigureResponseReserved0Offset = 1U;
inline constexpr std::size_t kConfigureResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kConfigureResponseStreamMaskOffset = 4U;
inline constexpr std::size_t kConfigureResponseSourceOffset = 5U;
inline constexpr std::size_t kConfigureResponseDataChecksumAlgorithmOffset = 6U;
inline constexpr std::size_t kConfigureResponseReserved1Offset = 7U;
inline constexpr std::size_t kConfigureResponseDataFrameBytesOffset = 8U;
inline constexpr std::size_t kStatusResponsePayloadSize = 172U;
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
inline constexpr std::size_t kStatusResponseGpioSamplesCapturedOffset = 56U;
inline constexpr std::size_t kStatusResponseGpioSamplesPackedOffset = 64U;
inline constexpr std::size_t kStatusResponseGpioSamplesFramedOffset = 72U;
inline constexpr std::size_t kStatusResponseGpioSamplesTransmittedOffset = 80U;
inline constexpr std::size_t kStatusResponseGpioRawSamplesLostOffset = 88U;
inline constexpr std::size_t kStatusResponseGpioPackerSamplesDroppedOffset = 96U;
inline constexpr std::size_t kStatusResponseGpioRawRingOverrunsOffset = 104U;
inline constexpr std::size_t kStatusResponseGpioDmaMajorLoopsOffset = 112U;
inline constexpr std::size_t kStatusResponseGpioRawReadyDepthOffset = 120U;
inline constexpr std::size_t kStatusResponseGpioRawReadyHighWaterOffset = 122U;
inline constexpr std::size_t kStatusResponseGpioPackedReadyDepthOffset = 124U;
inline constexpr std::size_t kStatusResponseGpioPackedReadyHighWaterOffset = 126U;
inline constexpr std::size_t kStatusResponsePacketReadyDepthOffset = 128U;
inline constexpr std::size_t kStatusResponsePacketTransmitDepthOffset = 130U;
inline constexpr std::size_t kStatusResponsePacketOwnedHighWaterOffset = 132U;
inline constexpr std::size_t kStatusResponseReserved1Offset = 134U;
inline constexpr std::size_t kStatusResponseGpioHardwareErrorsOffset = 136U;
inline constexpr std::size_t kStatusResponseGpioRawInvariantErrorsOffset = 140U;
inline constexpr std::size_t kStatusResponseGpioPackerSourceErrorsOffset = 144U;
inline constexpr std::size_t kStatusResponseGpioPackerPipelineErrorsOffset = 148U;
inline constexpr std::size_t kStatusResponseGpioPackerChronologyErrorsOffset = 152U;
inline constexpr std::size_t kStatusResponseGpioResourceConflictsOffset = 156U;
inline constexpr std::size_t kStatusResponseGpioStartErrorsOffset = 160U;
inline constexpr std::size_t kStatusResponseGpioStopErrorsOffset = 164U;
inline constexpr std::size_t kStatusResponseGpioStaleDmaCompletionsOffset = 168U;
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
inline constexpr std::size_t kGpioClockDiagnosticRequestPayloadSize = 8U;
inline constexpr std::size_t kGpioClockDiagnosticRequestRateHzOffset = 0U;
inline constexpr std::size_t kGpioClockDiagnosticRequestEventCountOffset = 4U;
inline constexpr std::size_t kGpioClockDiagnosticRequestReservedOffset = 6U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePayloadSize = 140U;
inline constexpr std::size_t kGpioClockDiagnosticResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kGpioClockDiagnosticResponseReserved0Offset = 1U;
inline constexpr std::size_t kGpioClockDiagnosticResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kGpioClockDiagnosticResponseConfiguredRateHzOffset = 4U;
inline constexpr std::size_t kGpioClockDiagnosticResponseProductionRateHzOffset = 8U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitClockHzOffset = 12U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitLoadValueOffset = 16U;
inline constexpr std::size_t kGpioClockDiagnosticResponseRequestedEventCountOffset = 20U;
inline constexpr std::size_t kGpioClockDiagnosticResponseScheduledEventCountOffset = 24U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmaSampleCountOffset = 28U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDwtCounterHzOffset = 32U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDwtElapsedCyclesOffset = 36U;
inline constexpr std::size_t kGpioClockDiagnosticResponseHardwareErrorFlagsOffset = 40U;
inline constexpr std::size_t kGpioClockDiagnosticResponseCcmCscmr1ConfiguredOffset = 44U;
inline constexpr std::size_t kGpioClockDiagnosticResponseCcmCcgr1ConfiguredOffset = 48U;
inline constexpr std::size_t kGpioClockDiagnosticResponseCcmCcgr2ConfiguredOffset = 52U;
inline constexpr std::size_t kGpioClockDiagnosticResponseCcmCcgr5ConfiguredOffset = 56U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitMcrConfiguredOffset = 60U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitLdvalConfiguredOffset = 64U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitCvalFinalOffset = 68U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitTctrlConfiguredOffset = 72U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitTflgFinalOffset = 76U;
inline constexpr std::size_t kGpioClockDiagnosticResponseXbarSelConfiguredOffset = 80U;
inline constexpr std::size_t kGpioClockDiagnosticResponseXbarCtrlConfiguredOffset = 82U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmamuxChcfgConfiguredOffset = 84U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmaCrConfiguredOffset = 88U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmaEsFinalOffset = 92U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmaErqConfiguredOffset = 96U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmaErrFinalOffset = 100U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmaHrsFinalOffset = 104U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdSaddrOffset = 108U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdDaddrOffset = 112U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdNbytesOffset = 116U;
inline constexpr std::size_t kGpioClockDiagnosticResponseLastSampleWordOffset = 120U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdCiterFinalOffset = 124U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdBiterOffset = 126U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdCsrFinalOffset = 128U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdAttrOffset = 130U;
inline constexpr std::size_t kGpioClockDiagnosticResponsePitChannelOffset = 132U;
inline constexpr std::size_t kGpioClockDiagnosticResponseXbarInputOffset = 133U;
inline constexpr std::size_t kGpioClockDiagnosticResponseXbarOutputOffset = 134U;
inline constexpr std::size_t kGpioClockDiagnosticResponseEdmaChannelOffset = 135U;
inline constexpr std::size_t kGpioClockDiagnosticResponseDmamuxSourceOffset = 136U;
inline constexpr std::size_t kGpioClockDiagnosticResponseEdmaPriorityOffset = 137U;
inline constexpr std::size_t kGpioClockDiagnosticResponseTcdSoffOffset = 138U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponsePayloadSize = 144U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseReserved0Offset = 1U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseModeOffset = 4U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseMetadataKindOffset = 5U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDriveSafetyOffset = 6U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseStimulusKindOffset = 7U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseFixtureIdentityOffset = 8U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseStimulusIdentityOffset = 12U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseHardwareErrorFlagsOffset = 16U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDiagnosticFlagsOffset = 20U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDwtCounterHzOffset = 24U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDwtElapsedCyclesOffset = 28U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDmaSamplesCapturedOffset = 32U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseCompleteSamplesRetainedOffset = 40U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseSamplesAnalyzedOffset = 44U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseStoppedPartialSamplesOffset = 48U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseRawWordAndOffset = 52U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseRawWordOrOffset = 56U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseObservedTransitionsOffset = 60U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseMappingValuesCheckedOffset = 64U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseMappingFailuresOffset = 66U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseUnstableSamplesOffset = 68U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseReserved1Offset = 70U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponsePackedValueAndOffset = 72U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponsePackedValueOrOffset = 73U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseFirstPackedValueOffset = 74U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseLastPackedValueOffset = 75U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpr27BeforeOffset = 76U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpr27ConfiguredOffset = 80U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpr27AfterOffset = 84U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpio2GdirBeforeOffset = 88U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpio2GdirConfiguredOffset = 92U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpio2GdirAfterOffset = 96U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpio2PsrBeforeOffset = 100U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpio2PsrConfiguredOffset = 104U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseGpio2PsrAfterOffset = 108U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponsePitLdvalConfiguredOffset = 112U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponsePitTctrlConfiguredOffset = 116U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDmamuxChcfgConfiguredOffset = 120U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDmaErqConfiguredOffset = 124U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseDmaErrFinalOffset = 128U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseTcdCiterConfiguredOffset = 132U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseTcdBiterConfiguredOffset = 134U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseTcdCsrConfiguredOffset = 136U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseEdmaPriorityConfiguredOffset = 138U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseReserved2Offset = 139U;
inline constexpr std::size_t kGpioCaptureDiagnosticResponseAnalysisSampleLimitOffset = 140U;
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
    case FrameKind::kGpioClockDiagnosticRequest:
      return 0U;
    case FrameKind::kGpioCaptureDiagnosticRequest:
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
    case FrameKind::kGpioClockDiagnosticResponse:
      return static_cast<std::uint16_t>(FrameFlag::kResponseError);
    case FrameKind::kGpioCaptureDiagnosticResponse:
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
    case CommandKind::kGpioClockDiagnostic:
      return FrameKind::kGpioClockDiagnosticRequest;
    case CommandKind::kGpioCaptureDiagnostic:
      return FrameKind::kGpioCaptureDiagnosticRequest;
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
    case CommandKind::kGpioClockDiagnostic:
      return FrameKind::kGpioClockDiagnosticResponse;
    case CommandKind::kGpioCaptureDiagnostic:
      return FrameKind::kGpioCaptureDiagnosticResponse;
  }
  return FrameKind::kInfoResponse;
}

static_assert(kHeaderSize + kDataPayloadBytes + kTrailerSize ==
              kDataFrameBytes);
static_assert(kAdcPairsPerFrame * kAdcBytesPerPair ==
              kDataPayloadBytes);
static_assert(kGpioSamplesPerFrame == kDataPayloadBytes);

}  // namespace teensy_daq::protocol_v1
