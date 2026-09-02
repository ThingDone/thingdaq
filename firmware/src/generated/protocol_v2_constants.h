// Generated from protocol/protocol-v2.json. Do not edit by hand.
// Source SHA-256: 0aea5d8f82ee535c2940d380e7ab184b1f5a3b9d6da3bab315841ff421699016
#pragma once

#include <cstddef>
#include <cstdint>

namespace thingdaq::protocol_v2 {

inline constexpr char kSourceSha256[] = "0aea5d8f82ee535c2940d380e7ab184b1f5a3b9d6da3bab315841ff421699016";
inline constexpr std::uint32_t kMagic = 0xDEADBEEFU;
inline constexpr std::uint8_t kProtocolVersion = 2U;
inline constexpr bool kWireIsLittleEndian = true;
inline constexpr std::size_t kHeaderSize = 44U;
inline constexpr std::size_t kTrailerSize = 4U;
inline constexpr std::size_t kMinFrameBytes = 48U;
inline constexpr std::size_t kDataFrameBytes = 4096U;
inline constexpr std::size_t kMaxDataFrameBytes = 4096U;
inline constexpr std::size_t kDataPayloadBytes = 4048U;
inline constexpr std::size_t kMaxControlFrameBytes = 1280U;
inline constexpr std::size_t kMaxControlPayloadBytes =
    kMaxControlFrameBytes - kHeaderSize - kTrailerSize;
inline constexpr std::size_t kMaxCommandFrameBytes = 64U;
inline constexpr std::size_t kMaxCommandPayloadBytes = 16U;
inline constexpr std::uint32_t kTimestampHz = 8000000U;
inline constexpr std::uint32_t kAdcPairRateHz = 1000000U;
inline constexpr std::uint32_t kAdcPairPeriodTicks = 8U;
inline constexpr std::uint32_t kAdc1PhaseTicks = 4U;
inline constexpr std::uint32_t kGpioSampleRateHz = 4000000U;
inline constexpr std::uint32_t kGpioSamplePeriodTicks = 2U;
inline constexpr std::uint32_t kFrameCoverageTicks = 8096U;
inline constexpr std::uint16_t kSupportedConfigurationMask = 63U;
inline constexpr std::uint8_t kAdcDmaRingDepth = 8U;
inline constexpr std::uint16_t kAdcPairsPerBuffer = 1012U;
inline constexpr std::uint8_t kAdcPairBytes = 4U;
inline constexpr std::uint32_t kAdcDmaRingBytes = 32512U;
inline constexpr std::uint8_t kAdcEdmaChannels[] = {0U, 1U};
inline constexpr std::uint8_t kAdcEdmaPriorities[] = {2U, 1U};
inline constexpr std::uint8_t kAdcDmamuxSources[] = {24U, 88U};
inline constexpr std::uint8_t kAdcDmaIrqPriority = 48U;
inline constexpr std::uint8_t kGpioDmaIrqPriority = 64U;
inline constexpr std::uint16_t kPacketBufferCount = 200U;
inline constexpr std::uint16_t kPacketPrimaryCount = 105U;
inline constexpr std::uint16_t kPacketReserveCount = 95U;
inline constexpr std::uint16_t kPacketReadyQueueCapacity = 200U;
inline constexpr std::uint16_t kPacketTransmitQueueCapacity = 200U;
inline constexpr std::uint8_t kCommandQueueCapacity = 4U;
inline constexpr std::uint8_t kResponseQueueCapacity = 4U;
inline constexpr std::uint32_t kNominalPayloadBytesPerSecondPerStream = 4000000U;
inline constexpr std::uint32_t kNominalFramedBytesPerSecondPerStream = 4047431U;
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
inline constexpr std::uint8_t kGpioEdmaPriority = 0U;
inline constexpr std::uint32_t kGpioCaptureDiagnosticAnalysisSamples = 256U;
inline constexpr std::uint8_t kAdcPrimaryResolutionBits = 12U;
inline constexpr std::uint8_t kAdcFallbackResolutionBits = 10U;
inline constexpr std::uint16_t kAdcCodeMin = 0U;
inline constexpr std::uint16_t kAdcReferenceMvNominal = 3300U;
inline constexpr std::uint16_t kAdcInputMinMvNominal = 0U;
inline constexpr std::uint16_t kAdcInputMaxMvNominal = 3300U;
inline constexpr std::uint32_t kAdcIpgClockHz = 150000000U;
inline constexpr std::uint32_t kAdcClockHz = 37500000U;
inline constexpr std::uint8_t kAdcClockDivider = 4U;
inline constexpr std::uint8_t kAdcHardwareAverageCount = 0U;
inline constexpr std::uint8_t kAdcSampleTimeAdck = 3U;
inline constexpr std::uint32_t kAdcCalibrationCycleCounterHz = 600000000U;
inline constexpr std::uint32_t kAdcCalibrationDeadlineUs = 10000U;
inline constexpr std::uint32_t kAdcCalibrationPollLimit = 8000000U;
inline constexpr std::uint8_t kAdcPins[] = {14U, 15U};
inline constexpr std::uint8_t kAdcPeripherals[] = {1U, 2U};
inline constexpr std::uint8_t kAdcChannels[] = {7U, 8U};
inline constexpr std::uint32_t kAdcTriggerPitClockHz = 24000000U;
inline constexpr std::uint32_t kAdcTriggerDwtClockHz = 600000000U;
inline constexpr std::uint32_t kAdcTriggerGpioMasterRateHz = 4000000U;
inline constexpr std::uint32_t kAdcTriggerPairRateHz = 1000000U;
inline constexpr std::uint32_t kAdcTriggerIpgClockHz = 150000000U;
inline constexpr std::uint8_t kAdcTriggerGpioMasterPitChannel = 0U;
inline constexpr std::uint8_t kAdcTriggerPairPitChannel = 1U;
inline constexpr std::uint8_t kAdcTriggerGpioMasterPitLoad = 5U;
inline constexpr std::uint8_t kAdcTriggerPairPitLoad = 3U;
inline constexpr std::uint8_t kAdcTriggerPredivider = 0U;
inline constexpr std::uint8_t kAdcTriggerChainLength = 1U;
inline constexpr std::uint8_t kAdcTriggerXbarInputs[] = {57U, 57U};
inline constexpr std::uint8_t kAdcTriggerXbarOutputs[] = {103U, 107U};
inline constexpr std::uint8_t kAdcTriggerQueues[] = {0U, 4U};
inline constexpr std::uint16_t kAdcTriggerInitialDelays[] = {0U, 75U};
inline constexpr std::uint16_t kAdcTriggerEffectiveDelays[] = {1U, 76U};
inline constexpr std::uint16_t kAdcTriggerPhaseIpgCycles = 75U;
inline constexpr std::uint32_t kAdcCompletionExpectedDwtCycles = 300U;
inline constexpr std::uint32_t kAdcCompletionToleranceDwtCycles = 120U;
inline constexpr std::uint32_t kAdcTriggerDiagnosticDeadlineUs = 2000U;
inline constexpr std::uint32_t kAdcTriggerDiagnosticPollLimit = 2000000U;
inline constexpr std::uint8_t kAdcTriggerIrqPriority = 32U;
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

enum class ConfigurationProfile : std::uint16_t {
  kHardwareAdc = 1U,
  kHardwareGpio = 2U,
  kHardwareCombined = 4U,
  kSyntheticAdc = 8U,
  kSyntheticGpio = 16U,
  kSyntheticCombined = 32U,
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
  kAuxiliaryInputBank = 512U,
  kExactRateProfiles = 1024U,
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

enum class AdcReference : std::uint8_t {
  kUnspecified = 0U,
  kVrefhVreflNominal3v3 = 1U,
};

enum class AdcClockSource : std::uint8_t {
  kUnspecified = 0U,
  kSynchronousIpg = 1U,
};

enum class AdcCalibrationState : std::uint8_t {
  kNotRun = 0U,
  kSucceeded = 1U,
  kFailed = 2U,
  kTimedOut = 3U,
  kRouteInvalid = 4U,
  kConfigurationInvalid = 5U,
  kClockUnavailable = 6U,
};

enum class AdcConfigurationFlag : std::uint16_t {
  kInitialized = 1U,
  kNoHardwareAveraging = 2U,
  kHighSpeed = 4U,
  kShortestSample = 8U,
  kRoutesValidated = 16U,
  kConfigurationReadbackValid = 32U,
  kCalibrationComplete = 64U,
  kPrimary12Bit = 128U,
  kFallback10Bit = 256U,
};

enum class AdcInitializationError : std::uint32_t {
  kDwtUnavailable = 1U,
  kAdc0RouteInvalid = 2U,
  kAdc1RouteInvalid = 4U,
  kAdc0ConfigurationInvalid = 8U,
  kAdc1ConfigurationInvalid = 16U,
  kAdc0CalibrationFailed = 32U,
  kAdc1CalibrationFailed = 64U,
  kAdc0CalibrationTimeout = 128U,
  kAdc1CalibrationTimeout = 256U,
  kAdc0ReadbackInvalid = 512U,
  kAdc1ReadbackInvalid = 1024U,
};

enum class AdcTriggerConfigurationFlag : std::uint16_t {
  kConfiguredStopped = 1U,
  kClocksValid = 2U,
  kXbarRoutesValid = 4U,
  kQueuesValid = 8U,
  kAdcHardwareTriggerValid = 16U,
  kArmSequenceExercised = 32U,
  kCompletionTimingValid = 64U,
  kStoppedAfterDiagnostic = 128U,
};

enum class AdcTriggerError : std::uint32_t {
  kConvertersNotReady = 1U,
  kResourceBusy = 2U,
  kPerclkMismatch = 4U,
  kIpgClockMismatch = 8U,
  kDwtUnavailable = 16U,
  kPitConfigMismatch = 32U,
  kXbarConfigMismatch = 64U,
  kAdcEtcConfigMismatch = 128U,
  kAdcHardwareTriggerMismatch = 256U,
  kArmFailed = 512U,
  kDiagnosticTimeout = 1024U,
  kAdcEtcTriggerError = 2048U,
  kCompletionCountMismatch = 4096U,
  kCompletionTimingOutOfTolerance = 8192U,
  kCleanupFailed = 16384U,
};

inline constexpr ChecksumAlgorithm kBootstrapChecksumAlgorithm =
    ChecksumAlgorithm::kAdler32;
inline constexpr ChecksumAlgorithm kDefaultChecksumAlgorithm =
    ChecksumAlgorithm::kAdler32;
inline constexpr std::uint32_t kSupportedChecksumMask = 14U;
inline constexpr std::uint16_t kKnownFrameFlagMask = 32783U;
inline constexpr std::uint32_t kKnownCapabilityMask = 2047U;
inline constexpr std::uint16_t kKnownConfigurationProfileMask = 63U;
inline constexpr std::uint32_t kKnownGpioClockErrorMask = 32767U;
inline constexpr std::uint32_t kKnownGpioCaptureDiagnosticFlagMask = 511U;
inline constexpr std::uint32_t kKnownGpioCaptureErrorMask = 65535U;
inline constexpr std::uint16_t kKnownAdcConfigurationFlagMask = 511U;
inline constexpr std::uint32_t kKnownAdcInitializationErrorMask = 2047U;
inline constexpr std::uint16_t kKnownAdcTriggerConfigurationFlagMask = 255U;
inline constexpr std::uint32_t kKnownAdcTriggerErrorMask = 32767U;

inline constexpr std::size_t kEmptyPayloadSize = 0U;
inline constexpr std::size_t kRateProfileInfoPayloadSize = 48U;
inline constexpr std::size_t kRateProfileInfoRateProfileOffset = 0U;
inline constexpr std::size_t kRateProfileInfoAdcEtcPredividerOffset = 1U;
inline constexpr std::size_t kRateProfileInfoAdcEtcChainLengthOffset = 2U;
inline constexpr std::size_t kRateProfileInfoReservedOffset = 3U;
inline constexpr std::size_t kRateProfileInfoAdcPairRateHzOffset = 4U;
inline constexpr std::size_t kRateProfileInfoGpioSampleRateHzOffset = 8U;
inline constexpr std::size_t kRateProfileInfoAdcPairPeriodTicksOffset = 12U;
inline constexpr std::size_t kRateProfileInfoAdc1PhaseTicksOffset = 14U;
inline constexpr std::size_t kRateProfileInfoGpioSamplePeriodTicksOffset = 16U;
inline constexpr std::size_t kRateProfileInfoGpioMasterPitDividerOffset = 18U;
inline constexpr std::size_t kRateProfileInfoGpioMasterPitLoadOffset = 20U;
inline constexpr std::size_t kRateProfileInfoAdcPairPitDividerOffset = 22U;
inline constexpr std::size_t kRateProfileInfoAdcPairPitLoadOffset = 24U;
inline constexpr std::size_t kRateProfileInfoAdc0InitialDelayOffset = 26U;
inline constexpr std::size_t kRateProfileInfoAdc1InitialDelayOffset = 28U;
inline constexpr std::size_t kRateProfileInfoAdc0EffectiveDelayOffset = 30U;
inline constexpr std::size_t kRateProfileInfoAdc1EffectiveDelayOffset = 32U;
inline constexpr std::size_t kRateProfileInfoAdc1PhaseIpgCyclesOffset = 34U;
inline constexpr std::size_t kRateProfileInfoCompletionExpectedDwtCyclesOffset = 36U;
inline constexpr std::size_t kRateProfileInfoDisabledFrameCoverageTicksOffset = 40U;
inline constexpr std::size_t kRateProfileInfoInputFrameCoverageTicksOffset = 44U;
inline constexpr std::size_t kAdcDataPayloadSize = 4048U;
inline constexpr std::size_t kAdcDataPairsOffset = 0U;
inline constexpr std::size_t kAdcDataPairsCount = 1012U;
inline constexpr std::size_t kGpioDataPayloadSize = 4048U;
inline constexpr std::size_t kGpioDataSamplesOffset = 0U;
inline constexpr std::size_t kGpioDataSamplesCount = 4048U;
inline constexpr std::size_t kAdcAuxDataPayloadSize = 2024U;
inline constexpr std::size_t kAdcAuxDataPairsOffset = 0U;
inline constexpr std::size_t kAdcAuxDataPairsCount = 506U;
inline constexpr std::size_t kGpioAuxDataPayloadSize = 4048U;
inline constexpr std::size_t kGpioAuxDataSamplesOffset = 0U;
inline constexpr std::size_t kGpioAuxDataSamplesCount = 2024U;
inline constexpr std::size_t kConfigureRequestPayloadSize = 16U;
inline constexpr std::size_t kConfigureRequestStreamMaskOffset = 0U;
inline constexpr std::size_t kConfigureRequestSourceOffset = 1U;
inline constexpr std::size_t kConfigureRequestDataChecksumAlgorithmOffset = 2U;
inline constexpr std::size_t kConfigureRequestAuxBankModeOffset = 3U;
inline constexpr std::size_t kConfigureRequestDataFrameBytesOffset = 4U;
inline constexpr std::size_t kConfigureRequestAdcPairRateHzOffset = 8U;
inline constexpr std::size_t kConfigureRequestGpioSampleRateHzOffset = 12U;
inline constexpr std::size_t kResponsePrefixPayloadSize = 4U;
inline constexpr std::size_t kResponsePrefixResponseStatusOffset = 0U;
inline constexpr std::size_t kResponsePrefixReservedOffset = 1U;
inline constexpr std::size_t kResponsePrefixErrorCodeOffset = 2U;
inline constexpr std::size_t kInfoResponsePayloadSize = 632U;
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
inline constexpr std::size_t kInfoResponseAdcCodeMinOffset = 128U;
inline constexpr std::size_t kInfoResponseAdcCodeMaxOffset = 130U;
inline constexpr std::size_t kInfoResponseAdcReferenceOffset = 132U;
inline constexpr std::size_t kInfoResponseAdcClockSourceOffset = 133U;
inline constexpr std::size_t kInfoResponseAdcClockDividerOffset = 134U;
inline constexpr std::size_t kInfoResponseAdcHardwareAverageCountOffset = 135U;
inline constexpr std::size_t kInfoResponseAdcReferenceMvNominalOffset = 136U;
inline constexpr std::size_t kInfoResponseAdcInputMinMvNominalOffset = 138U;
inline constexpr std::size_t kInfoResponseAdcInputMaxMvNominalOffset = 140U;
inline constexpr std::size_t kInfoResponseAdcSampleTimeAdckOffset = 142U;
inline constexpr std::size_t kInfoResponseAdcConversionModeOffset = 143U;
inline constexpr std::size_t kInfoResponseAdcConfigurationFlagsOffset = 144U;
inline constexpr std::size_t kInfoResponseAdc0CalibrationStateOffset = 146U;
inline constexpr std::size_t kInfoResponseAdc1CalibrationStateOffset = 147U;
inline constexpr std::size_t kInfoResponseAdc0PinOffset = 148U;
inline constexpr std::size_t kInfoResponseAdc1PinOffset = 149U;
inline constexpr std::size_t kInfoResponseAdc0PeripheralOffset = 150U;
inline constexpr std::size_t kInfoResponseAdc1PeripheralOffset = 151U;
inline constexpr std::size_t kInfoResponseAdc0ChannelOffset = 152U;
inline constexpr std::size_t kInfoResponseAdc1ChannelOffset = 153U;
inline constexpr std::size_t kInfoResponseReserved5Offset = 154U;
inline constexpr std::size_t kInfoResponseAdcIpgClockHzOffset = 156U;
inline constexpr std::size_t kInfoResponseAdcClockHzOffset = 160U;
inline constexpr std::size_t kInfoResponseAdcCalibrationDeadlineUsOffset = 164U;
inline constexpr std::size_t kInfoResponseAdc0CalibrationCyclesOffset = 168U;
inline constexpr std::size_t kInfoResponseAdc1CalibrationCyclesOffset = 172U;
inline constexpr std::size_t kInfoResponseAdcInitializationErrorFlagsOffset = 176U;
inline constexpr std::size_t kInfoResponseAdcTriggerConfigurationFlagsOffset = 180U;
inline constexpr std::size_t kInfoResponseReserved6Offset = 182U;
inline constexpr std::size_t kInfoResponseAdcTriggerErrorFlagsOffset = 184U;
inline constexpr std::size_t kInfoResponseAdcTriggerPitClockHzOffset = 188U;
inline constexpr std::size_t kInfoResponseAdcTriggerDwtClockHzOffset = 192U;
inline constexpr std::size_t kInfoResponseAdcTriggerGpioMasterRateHzOffset = 196U;
inline constexpr std::size_t kInfoResponseAdcTriggerPairRateHzOffset = 200U;
inline constexpr std::size_t kInfoResponseAdcTriggerIpgClockHzOffset = 204U;
inline constexpr std::size_t kInfoResponseAdcTriggerGpioMasterPitChannelOffset = 208U;
inline constexpr std::size_t kInfoResponseAdcTriggerPairPitChannelOffset = 209U;
inline constexpr std::size_t kInfoResponseAdcTriggerGpioMasterPitLoadOffset = 210U;
inline constexpr std::size_t kInfoResponseAdcTriggerPairPitLoadOffset = 211U;
inline constexpr std::size_t kInfoResponseAdcTriggerPredividerOffset = 212U;
inline constexpr std::size_t kInfoResponseAdcTriggerChainLengthOffset = 213U;
inline constexpr std::size_t kInfoResponseAdc0TriggerXbarInputOffset = 214U;
inline constexpr std::size_t kInfoResponseAdc1TriggerXbarInputOffset = 215U;
inline constexpr std::size_t kInfoResponseAdc0TriggerXbarOutputOffset = 216U;
inline constexpr std::size_t kInfoResponseAdc1TriggerXbarOutputOffset = 217U;
inline constexpr std::size_t kInfoResponseAdc0EtcTriggerQueueOffset = 218U;
inline constexpr std::size_t kInfoResponseAdc1EtcTriggerQueueOffset = 219U;
inline constexpr std::size_t kInfoResponseAdc0TriggerInitialDelayOffset = 220U;
inline constexpr std::size_t kInfoResponseAdc1TriggerInitialDelayOffset = 222U;
inline constexpr std::size_t kInfoResponseAdc0TriggerEffectiveDelayOffset = 224U;
inline constexpr std::size_t kInfoResponseAdc1TriggerEffectiveDelayOffset = 226U;
inline constexpr std::size_t kInfoResponseAdcTriggerPhaseIpgCyclesOffset = 228U;
inline constexpr std::size_t kInfoResponseReserved7Offset = 230U;
inline constexpr std::size_t kInfoResponseAdcTriggerCcmCscmr1ConfiguredOffset = 232U;
inline constexpr std::size_t kInfoResponseAdcTriggerCcmCcgr1ConfiguredOffset = 236U;
inline constexpr std::size_t kInfoResponseAdcTriggerCcmCcgr2ConfiguredOffset = 240U;
inline constexpr std::size_t kInfoResponseAdcTriggerPitMcrConfiguredOffset = 244U;
inline constexpr std::size_t kInfoResponseAdcTriggerGpioMasterTctrlConfiguredOffset = 248U;
inline constexpr std::size_t kInfoResponseAdcTriggerPairTctrlConfiguredOffset = 252U;
inline constexpr std::size_t kInfoResponseAdcEtcCtrlConfiguredOffset = 256U;
inline constexpr std::size_t kInfoResponseAdc0EtcTriggerCtrlConfiguredOffset = 260U;
inline constexpr std::size_t kInfoResponseAdc1EtcTriggerCtrlConfiguredOffset = 264U;
inline constexpr std::size_t kInfoResponseAdc0EtcTriggerCounterConfiguredOffset = 268U;
inline constexpr std::size_t kInfoResponseAdc1EtcTriggerCounterConfiguredOffset = 272U;
inline constexpr std::size_t kInfoResponseAdc0EtcChainConfiguredOffset = 276U;
inline constexpr std::size_t kInfoResponseAdc1EtcChainConfiguredOffset = 280U;
inline constexpr std::size_t kInfoResponseAdcEtcDone01IrqFinalOffset = 284U;
inline constexpr std::size_t kInfoResponseAdcEtcDone2ErrIrqFinalOffset = 288U;
inline constexpr std::size_t kInfoResponseAdc0CompletionCountOffset = 292U;
inline constexpr std::size_t kInfoResponseAdc1CompletionCountOffset = 296U;
inline constexpr std::size_t kInfoResponseAdcCompletionDeltaCyclesOffset = 300U;
inline constexpr std::size_t kInfoResponseAdcCompletionExpectedDeltaCyclesOffset = 304U;
inline constexpr std::size_t kInfoResponseAdcCompletionToleranceCyclesOffset = 308U;
inline constexpr std::size_t kInfoResponseAdcCompletionDiagnosticElapsedCyclesOffset = 312U;
inline constexpr std::size_t kInfoResponseAdcTriggerErrorCountOffset = 316U;
inline constexpr std::size_t kInfoResponseAdc0TriggerXbarSelConfiguredOffset = 320U;
inline constexpr std::size_t kInfoResponseAdc1TriggerXbarSelConfiguredOffset = 322U;
inline constexpr std::size_t kInfoResponseAppliedStreamMaskOffset = 324U;
inline constexpr std::size_t kInfoResponseAppliedSourceOffset = 325U;
inline constexpr std::size_t kInfoResponseSupportedConfigurationMaskOffset = 326U;
inline constexpr std::size_t kInfoResponseDataPayloadBytesOffset = 328U;
inline constexpr std::size_t kInfoResponseAdcPairsPerFrameOffset = 330U;
inline constexpr std::size_t kInfoResponseGpioSamplesPerFrameOffset = 332U;
inline constexpr std::size_t kInfoResponseReserved8Offset = 334U;
inline constexpr std::size_t kInfoResponseFrameCoverageTicksOffset = 336U;
inline constexpr std::size_t kInfoResponseAdcDmaRingDepthOffset = 340U;
inline constexpr std::size_t kInfoResponseAdcPairBytesOffset = 341U;
inline constexpr std::size_t kInfoResponseAdcEdmaChannelsOffset = 342U;
inline constexpr std::size_t kInfoResponseAdcEdmaChannelsCount = 2U;
inline constexpr std::size_t kInfoResponseAdcEdmaPrioritiesOffset = 344U;
inline constexpr std::size_t kInfoResponseAdcEdmaPrioritiesCount = 2U;
inline constexpr std::size_t kInfoResponseAdcDmamuxSourcesOffset = 346U;
inline constexpr std::size_t kInfoResponseAdcDmamuxSourcesCount = 2U;
inline constexpr std::size_t kInfoResponseAdcDmaIrqPriorityOffset = 348U;
inline constexpr std::size_t kInfoResponseGpioDmaIrqPriorityOffset = 349U;
inline constexpr std::size_t kInfoResponseAdcPairsPerBufferOffset = 350U;
inline constexpr std::size_t kInfoResponseAdcDmaRingBytesOffset = 352U;
inline constexpr std::size_t kInfoResponsePacketBufferCountOffset = 356U;
inline constexpr std::size_t kInfoResponsePacketPrimaryCountOffset = 358U;
inline constexpr std::size_t kInfoResponsePacketReserveCountOffset = 360U;
inline constexpr std::size_t kInfoResponsePacketReadyQueueCapacityOffset = 362U;
inline constexpr std::size_t kInfoResponsePacketTransmitQueueCapacityOffset = 364U;
inline constexpr std::size_t kInfoResponseCommandQueueCapacityOffset = 366U;
inline constexpr std::size_t kInfoResponseResponseQueueCapacityOffset = 367U;
inline constexpr std::size_t kInfoResponseNominalPayloadBytesPerSecondPerStreamOffset = 368U;
inline constexpr std::size_t kInfoResponseNominalFramedBytesPerSecondPerStreamOffset = 372U;
inline constexpr std::size_t kInfoResponseSupportedRateProfileMaskOffset = 376U;
inline constexpr std::size_t kInfoResponseSelectedRateProfileOffset = 377U;
inline constexpr std::size_t kInfoResponseSupportedAuxBankModeMaskOffset = 378U;
inline constexpr std::size_t kInfoResponseAppliedAuxBankModeOffset = 379U;
inline constexpr std::size_t kInfoResponseGpioItemBytesOffset = 380U;
inline constexpr std::size_t kInfoResponseAuxGpioPinCountOffset = 381U;
inline constexpr std::size_t kInfoResponseRateProfileCountOffset = 382U;
inline constexpr std::size_t kInfoResponseReserved9Offset = 383U;
inline constexpr std::size_t kInfoResponseAuxGpioPinMapOffset = 384U;
inline constexpr std::size_t kInfoResponseAuxGpioPinMapCount = 8U;
inline constexpr std::size_t kInfoResponseAuxGpioPortBitsOffset = 392U;
inline constexpr std::size_t kInfoResponseAuxGpioPortBitsCount = 8U;
inline constexpr std::size_t kInfoResponseAuxGpioStandardPortOffset = 400U;
inline constexpr std::size_t kInfoResponseAuxGpioFastPortOffset = 401U;
inline constexpr std::size_t kInfoResponseAuxGpioFastSelectGprOffset = 402U;
inline constexpr std::size_t kInfoResponseGpioRawWordBytesOffset = 403U;
inline constexpr std::size_t kInfoResponseAuxGpioCaptureMaskOffset = 404U;
inline constexpr std::size_t kInfoResponsePrimaryGpioStandardPortOffset = 408U;
inline constexpr std::size_t kInfoResponsePrimaryGpioFastPortOffset = 409U;
inline constexpr std::size_t kInfoResponsePrimaryGpioFastSelectGprOffset = 410U;
inline constexpr std::size_t kInfoResponseReserved10Offset = 411U;
inline constexpr std::size_t kInfoResponsePrimaryGpioCaptureMaskOffset = 412U;
inline constexpr std::size_t kInfoResponsePrimaryGpioEdmaChannelOffset = 416U;
inline constexpr std::size_t kInfoResponseAuxGpioEdmaChannelOffset = 417U;
inline constexpr std::size_t kInfoResponsePrimaryGpioDmamuxSourceOffset = 418U;
inline constexpr std::size_t kInfoResponseAuxGpioDmamuxSourceOffset = 419U;
inline constexpr std::size_t kInfoResponsePrimaryGpioXbarOutputOffset = 420U;
inline constexpr std::size_t kInfoResponseAuxGpioXbarOutputOffset = 421U;
inline constexpr std::size_t kInfoResponsePairedGpioXbarInputOffset = 422U;
inline constexpr std::size_t kInfoResponseAuxGpioEdmaPriorityOffset = 423U;
inline constexpr std::size_t kInfoResponsePrimaryGpioEdmaPriorityOffset = 424U;
inline constexpr std::size_t kInfoResponseAdc0EdmaPriorityOffset = 425U;
inline constexpr std::size_t kInfoResponseAdc1EdmaPriorityOffset = 426U;
inline constexpr std::size_t kInfoResponseAuxGpioDmaIrqPriorityOffset = 427U;
inline constexpr std::size_t kInfoResponsePrimaryGpioRawRingDepthOffset = 428U;
inline constexpr std::size_t kInfoResponseAuxGpioRawRingDepthOffset = 429U;
inline constexpr std::size_t kInfoResponsePairedGpioJoinRequiredOffset = 430U;
inline constexpr std::size_t kInfoResponseReserved11Offset = 431U;
inline constexpr std::size_t kInfoResponseDisabledAdcPairsPerFrameOffset = 432U;
inline constexpr std::size_t kInfoResponseDisabledGpioSamplesPerFrameOffset = 434U;
inline constexpr std::size_t kInfoResponseInputAdcPairsPerFrameOffset = 436U;
inline constexpr std::size_t kInfoResponseInputGpioSamplesPerFrameOffset = 438U;
inline constexpr std::size_t kInfoResponseRateProfilesOffset = 440U;
inline constexpr std::size_t kInfoResponseRateProfilesCount = 4U;
inline constexpr std::size_t kConfigureResponsePayloadSize = 20U;
inline constexpr std::size_t kConfigureResponseResponseStatusOffset = 0U;
inline constexpr std::size_t kConfigureResponseReserved0Offset = 1U;
inline constexpr std::size_t kConfigureResponseErrorCodeOffset = 2U;
inline constexpr std::size_t kConfigureResponseStreamMaskOffset = 4U;
inline constexpr std::size_t kConfigureResponseSourceOffset = 5U;
inline constexpr std::size_t kConfigureResponseDataChecksumAlgorithmOffset = 6U;
inline constexpr std::size_t kConfigureResponseAuxBankModeOffset = 7U;
inline constexpr std::size_t kConfigureResponseDataFrameBytesOffset = 8U;
inline constexpr std::size_t kConfigureResponseAdcPairRateHzOffset = 12U;
inline constexpr std::size_t kConfigureResponseGpioSampleRateHzOffset = 16U;
inline constexpr std::size_t kStatusResponsePayloadSize = 1228U;
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
inline constexpr std::size_t kStatusResponseGpioProcessingCpuBasisPointsOffset = 134U;
inline constexpr std::size_t kStatusResponseGpioHardwareErrorsOffset = 136U;
inline constexpr std::size_t kStatusResponseGpioRawInvariantErrorsOffset = 140U;
inline constexpr std::size_t kStatusResponseGpioPackerSourceErrorsOffset = 144U;
inline constexpr std::size_t kStatusResponseGpioPackerPipelineErrorsOffset = 148U;
inline constexpr std::size_t kStatusResponseGpioPackerChronologyErrorsOffset = 152U;
inline constexpr std::size_t kStatusResponseGpioResourceConflictsOffset = 156U;
inline constexpr std::size_t kStatusResponseGpioStartErrorsOffset = 160U;
inline constexpr std::size_t kStatusResponseGpioStopErrorsOffset = 164U;
inline constexpr std::size_t kStatusResponseGpioStaleDmaCompletionsOffset = 168U;
inline constexpr std::size_t kStatusResponseAdcResolutionBitsOffset = 172U;
inline constexpr std::size_t kStatusResponseAdcContainerBytesOffset = 173U;
inline constexpr std::size_t kStatusResponseAdc0CalibrationStateOffset = 174U;
inline constexpr std::size_t kStatusResponseAdc1CalibrationStateOffset = 175U;
inline constexpr std::size_t kStatusResponseAdcCodeMinOffset = 176U;
inline constexpr std::size_t kStatusResponseAdcCodeMaxOffset = 178U;
inline constexpr std::size_t kStatusResponseAdcReferenceOffset = 180U;
inline constexpr std::size_t kStatusResponseAdcClockSourceOffset = 181U;
inline constexpr std::size_t kStatusResponseAdcClockDividerOffset = 182U;
inline constexpr std::size_t kStatusResponseAdcHardwareAverageCountOffset = 183U;
inline constexpr std::size_t kStatusResponseAdcReferenceMvNominalOffset = 184U;
inline constexpr std::size_t kStatusResponseAdcInputMinMvNominalOffset = 186U;
inline constexpr std::size_t kStatusResponseAdcInputMaxMvNominalOffset = 188U;
inline constexpr std::size_t kStatusResponseAdcSampleTimeAdckOffset = 190U;
inline constexpr std::size_t kStatusResponseAdcConversionModeOffset = 191U;
inline constexpr std::size_t kStatusResponseAdcConfigurationFlagsOffset = 192U;
inline constexpr std::size_t kStatusResponseAdc0PinOffset = 194U;
inline constexpr std::size_t kStatusResponseAdc1PinOffset = 195U;
inline constexpr std::size_t kStatusResponseAdc0PeripheralOffset = 196U;
inline constexpr std::size_t kStatusResponseAdc1PeripheralOffset = 197U;
inline constexpr std::size_t kStatusResponseAdc0ChannelOffset = 198U;
inline constexpr std::size_t kStatusResponseAdc1ChannelOffset = 199U;
inline constexpr std::size_t kStatusResponseAdcIpgClockHzOffset = 200U;
inline constexpr std::size_t kStatusResponseAdcClockHzOffset = 204U;
inline constexpr std::size_t kStatusResponseAdcCalibrationDeadlineUsOffset = 208U;
inline constexpr std::size_t kStatusResponseAdc0CalibrationCyclesOffset = 212U;
inline constexpr std::size_t kStatusResponseAdc1CalibrationCyclesOffset = 216U;
inline constexpr std::size_t kStatusResponseAdcInitializationErrorFlagsOffset = 220U;
inline constexpr std::size_t kStatusResponseAdcTriggerConfigurationFlagsOffset = 224U;
inline constexpr std::size_t kStatusResponseReserved2Offset = 226U;
inline constexpr std::size_t kStatusResponseAdcTriggerErrorFlagsOffset = 228U;
inline constexpr std::size_t kStatusResponseAdcTriggerPitClockHzOffset = 232U;
inline constexpr std::size_t kStatusResponseAdcTriggerDwtClockHzOffset = 236U;
inline constexpr std::size_t kStatusResponseAdcTriggerGpioMasterRateHzOffset = 240U;
inline constexpr std::size_t kStatusResponseAdcTriggerPairRateHzOffset = 244U;
inline constexpr std::size_t kStatusResponseAdcTriggerIpgClockHzOffset = 248U;
inline constexpr std::size_t kStatusResponseAdcTriggerGpioMasterPitChannelOffset = 252U;
inline constexpr std::size_t kStatusResponseAdcTriggerPairPitChannelOffset = 253U;
inline constexpr std::size_t kStatusResponseAdcTriggerGpioMasterPitLoadOffset = 254U;
inline constexpr std::size_t kStatusResponseAdcTriggerPairPitLoadOffset = 255U;
inline constexpr std::size_t kStatusResponseAdcTriggerPredividerOffset = 256U;
inline constexpr std::size_t kStatusResponseAdcTriggerChainLengthOffset = 257U;
inline constexpr std::size_t kStatusResponseAdc0TriggerXbarInputOffset = 258U;
inline constexpr std::size_t kStatusResponseAdc1TriggerXbarInputOffset = 259U;
inline constexpr std::size_t kStatusResponseAdc0TriggerXbarOutputOffset = 260U;
inline constexpr std::size_t kStatusResponseAdc1TriggerXbarOutputOffset = 261U;
inline constexpr std::size_t kStatusResponseAdc0EtcTriggerQueueOffset = 262U;
inline constexpr std::size_t kStatusResponseAdc1EtcTriggerQueueOffset = 263U;
inline constexpr std::size_t kStatusResponseAdc0TriggerInitialDelayOffset = 264U;
inline constexpr std::size_t kStatusResponseAdc1TriggerInitialDelayOffset = 266U;
inline constexpr std::size_t kStatusResponseAdc0TriggerEffectiveDelayOffset = 268U;
inline constexpr std::size_t kStatusResponseAdc1TriggerEffectiveDelayOffset = 270U;
inline constexpr std::size_t kStatusResponseAdcTriggerPhaseIpgCyclesOffset = 272U;
inline constexpr std::size_t kStatusResponseReserved3Offset = 274U;
inline constexpr std::size_t kStatusResponseAdcTriggerCcmCscmr1ConfiguredOffset = 276U;
inline constexpr std::size_t kStatusResponseAdcTriggerCcmCcgr1ConfiguredOffset = 280U;
inline constexpr std::size_t kStatusResponseAdcTriggerCcmCcgr2ConfiguredOffset = 284U;
inline constexpr std::size_t kStatusResponseAdcTriggerPitMcrConfiguredOffset = 288U;
inline constexpr std::size_t kStatusResponseAdcTriggerGpioMasterTctrlConfiguredOffset = 292U;
inline constexpr std::size_t kStatusResponseAdcTriggerPairTctrlConfiguredOffset = 296U;
inline constexpr std::size_t kStatusResponseAdcEtcCtrlConfiguredOffset = 300U;
inline constexpr std::size_t kStatusResponseAdc0EtcTriggerCtrlConfiguredOffset = 304U;
inline constexpr std::size_t kStatusResponseAdc1EtcTriggerCtrlConfiguredOffset = 308U;
inline constexpr std::size_t kStatusResponseAdc0EtcTriggerCounterConfiguredOffset = 312U;
inline constexpr std::size_t kStatusResponseAdc1EtcTriggerCounterConfiguredOffset = 316U;
inline constexpr std::size_t kStatusResponseAdc0EtcChainConfiguredOffset = 320U;
inline constexpr std::size_t kStatusResponseAdc1EtcChainConfiguredOffset = 324U;
inline constexpr std::size_t kStatusResponseAdcEtcDone01IrqFinalOffset = 328U;
inline constexpr std::size_t kStatusResponseAdcEtcDone2ErrIrqFinalOffset = 332U;
inline constexpr std::size_t kStatusResponseAdc0CompletionCountOffset = 336U;
inline constexpr std::size_t kStatusResponseAdc1CompletionCountOffset = 340U;
inline constexpr std::size_t kStatusResponseAdcCompletionDeltaCyclesOffset = 344U;
inline constexpr std::size_t kStatusResponseAdcCompletionExpectedDeltaCyclesOffset = 348U;
inline constexpr std::size_t kStatusResponseAdcCompletionToleranceCyclesOffset = 352U;
inline constexpr std::size_t kStatusResponseAdcCompletionDiagnosticElapsedCyclesOffset = 356U;
inline constexpr std::size_t kStatusResponseAdcTriggerErrorCountOffset = 360U;
inline constexpr std::size_t kStatusResponseAdc0TriggerXbarSelConfiguredOffset = 364U;
inline constexpr std::size_t kStatusResponseAdc1TriggerXbarSelConfiguredOffset = 366U;
inline constexpr std::size_t kStatusResponseAdc0DmaMajorLoopsOffset = 368U;
inline constexpr std::size_t kStatusResponseAdc1DmaMajorLoopsOffset = 376U;
inline constexpr std::size_t kStatusResponseAdc0DmaResultsOffset = 384U;
inline constexpr std::size_t kStatusResponseAdc1DmaResultsOffset = 392U;
inline constexpr std::size_t kStatusResponseAdcPairedMajorLoopsOffset = 400U;
inline constexpr std::size_t kStatusResponseAdcBuffersCompletedOffset = 408U;
inline constexpr std::size_t kStatusResponseAdcBuffersAcquiredOffset = 416U;
inline constexpr std::size_t kStatusResponseAdcBuffersReleasedOffset = 424U;
inline constexpr std::size_t kStatusResponseAdcPairsCapturedOffset = 432U;
inline constexpr std::size_t kStatusResponseAdcPairsDeliveredOffset = 440U;
inline constexpr std::size_t kStatusResponseAdcPairsFramedOffset = 448U;
inline constexpr std::size_t kStatusResponseAdcPairsTransmittedOffset = 456U;
inline constexpr std::size_t kStatusResponseAdcRawPairsLostOffset = 464U;
inline constexpr std::size_t kStatusResponseAdcStopPairsDiscardedOffset = 472U;
inline constexpr std::size_t kStatusResponseAdcIncompleteConversionsOffset = 480U;
inline constexpr std::size_t kStatusResponseAdcOverwrittenConversionsOffset = 488U;
inline constexpr std::size_t kStatusResponseAdcRawRingOverrunsOffset = 496U;
inline constexpr std::size_t kStatusResponseAdcIncompleteBuffersOffset = 504U;
inline constexpr std::size_t kStatusResponseAdcRawReadyDepthOffset = 512U;
inline constexpr std::size_t kStatusResponseAdcRawReadyHighWaterOffset = 514U;
inline constexpr std::size_t kStatusResponseAdcEtcErrorEventsOffset = 516U;
inline constexpr std::size_t kStatusResponseAdcEtcErrorFlagsOffset = 520U;
inline constexpr std::size_t kStatusResponseAdcDmaErrorEventsOffset = 524U;
inline constexpr std::size_t kStatusResponseAdcCompletionMismatchesOffset = 528U;
inline constexpr std::size_t kStatusResponseAdcDestinationMismatchesOffset = 532U;
inline constexpr std::size_t kStatusResponseAdcScheduleExhaustionsOffset = 536U;
inline constexpr std::size_t kStatusResponseAdcRawInvariantErrorsOffset = 540U;
inline constexpr std::size_t kStatusResponseAdcStaleCompletionsOffset = 544U;
inline constexpr std::size_t kStatusResponseAdcResourceConflictsOffset = 548U;
inline constexpr std::size_t kStatusResponseAdcStartErrorsOffset = 552U;
inline constexpr std::size_t kStatusResponseAdcStopErrorsOffset = 556U;
inline constexpr std::size_t kStatusResponseAdcStaleInterruptsOffset = 560U;
inline constexpr std::size_t kStatusResponseAdcPackerSourceErrorsOffset = 564U;
inline constexpr std::size_t kStatusResponseAdcPackerPipelineErrorsOffset = 568U;
inline constexpr std::size_t kStatusResponseAdcPackerChronologyErrorsOffset = 572U;
inline constexpr std::size_t kStatusResponseAdcFramesGeneratedOffset = 576U;
inline constexpr std::size_t kStatusResponseAdcItemsGeneratedOffset = 584U;
inline constexpr std::size_t kStatusResponseAdcFramesFramedPipelineOffset = 592U;
inline constexpr std::size_t kStatusResponseAdcItemsFramedPipelineOffset = 600U;
inline constexpr std::size_t kStatusResponseAdcItemsEmittedOffset = 608U;
inline constexpr std::size_t kStatusResponseAdcFramesTransmittedOffset = 616U;
inline constexpr std::size_t kStatusResponseAdcItemsTransmittedPipelineOffset = 624U;
inline constexpr std::size_t kStatusResponseAdcFramesDroppedOffset = 632U;
inline constexpr std::size_t kStatusResponseGpioFramesGeneratedOffset = 640U;
inline constexpr std::size_t kStatusResponseGpioItemsGeneratedOffset = 648U;
inline constexpr std::size_t kStatusResponseGpioFramesFramedPipelineOffset = 656U;
inline constexpr std::size_t kStatusResponseGpioItemsFramedPipelineOffset = 664U;
inline constexpr std::size_t kStatusResponseGpioItemsEmittedOffset = 672U;
inline constexpr std::size_t kStatusResponseGpioFramesTransmittedOffset = 680U;
inline constexpr std::size_t kStatusResponseGpioItemsTransmittedPipelineOffset = 688U;
inline constexpr std::size_t kStatusResponseGpioFramesDroppedOffset = 696U;
inline constexpr std::size_t kStatusResponseAdcPayloadBytesProducedOffset = 704U;
inline constexpr std::size_t kStatusResponseAdcPayloadBytesFramedOffset = 712U;
inline constexpr std::size_t kStatusResponseAdcPayloadBytesEmittedOffset = 720U;
inline constexpr std::size_t kStatusResponseAdcPayloadBytesTransmittedOffset = 728U;
inline constexpr std::size_t kStatusResponseAdcPayloadBytesDroppedOffset = 736U;
inline constexpr std::size_t kStatusResponseAdcFramedBytesFramedOffset = 744U;
inline constexpr std::size_t kStatusResponseAdcFramedBytesEmittedOffset = 752U;
inline constexpr std::size_t kStatusResponseAdcFramedBytesTransmittedOffset = 760U;
inline constexpr std::size_t kStatusResponseGpioPayloadBytesProducedOffset = 768U;
inline constexpr std::size_t kStatusResponseGpioPayloadBytesFramedOffset = 776U;
inline constexpr std::size_t kStatusResponseGpioPayloadBytesEmittedOffset = 784U;
inline constexpr std::size_t kStatusResponseGpioPayloadBytesTransmittedOffset = 792U;
inline constexpr std::size_t kStatusResponseGpioPayloadBytesDroppedOffset = 800U;
inline constexpr std::size_t kStatusResponseGpioFramedBytesFramedOffset = 808U;
inline constexpr std::size_t kStatusResponseGpioFramedBytesEmittedOffset = 816U;
inline constexpr std::size_t kStatusResponseGpioFramedBytesTransmittedOffset = 824U;
inline constexpr std::size_t kStatusResponseAdcPacketReadyDepthOffset = 832U;
inline constexpr std::size_t kStatusResponseGpioPacketReadyDepthOffset = 834U;
inline constexpr std::size_t kStatusResponseAdcPacketTransmitDepthOffset = 836U;
inline constexpr std::size_t kStatusResponseGpioPacketTransmitDepthOffset = 838U;
inline constexpr std::size_t kStatusResponseAdcPacketReadyHighWaterOffset = 840U;
inline constexpr std::size_t kStatusResponseGpioPacketReadyHighWaterOffset = 842U;
inline constexpr std::size_t kStatusResponseAdcPacketTransmitHighWaterOffset = 844U;
inline constexpr std::size_t kStatusResponseGpioPacketTransmitHighWaterOffset = 846U;
inline constexpr std::size_t kStatusResponsePacketReadyHighWaterOffset = 848U;
inline constexpr std::size_t kStatusResponsePacketTransmitHighWaterOffset = 850U;
inline constexpr std::size_t kStatusResponsePacketFramesPromotedOffset = 852U;
inline constexpr std::size_t kStatusResponsePacketFairnessDeferralsOffset = 860U;
inline constexpr std::size_t kStatusResponsePacketAccountedFrameSkewOffset = 868U;
inline constexpr std::size_t kStatusResponseDataPayloadBytesTransmittedOffset = 876U;
inline constexpr std::size_t kStatusResponseDataFramedBytesTransmittedOffset = 884U;
inline constexpr std::size_t kStatusResponsePacketPoolExhaustionsOffset = 892U;
inline constexpr std::size_t kStatusResponsePacketInvalidOperationsOffset = 896U;
inline constexpr std::size_t kStatusResponsePacketEncodingRejectionsOffset = 900U;
inline constexpr std::size_t kStatusResponsePacketReadyQueueRejectionsOffset = 904U;
inline constexpr std::size_t kStatusResponsePacketTransmitQueueRejectionsOffset = 908U;
inline constexpr std::size_t kStatusResponseCommandsAcceptedOffset = 912U;
inline constexpr std::size_t kStatusResponseCommandsRejectedOffset = 916U;
inline constexpr std::size_t kStatusResponseBadChecksumsOffset = 920U;
inline constexpr std::size_t kStatusResponseBadLengthsOffset = 924U;
inline constexpr std::size_t kStatusResponseBadTypesOffset = 928U;
inline constexpr std::size_t kStatusResponseBadVersionsOffset = 932U;
inline constexpr std::size_t kStatusResponseTimeoutsOffset = 936U;
inline constexpr std::size_t kStatusResponsePartialUsbWritesOffset = 940U;
inline constexpr std::size_t kStatusResponseStateErrorsOffset = 944U;
inline constexpr std::size_t kStatusResponseUsbShortCapacityDeferralsOffset = 948U;
inline constexpr std::size_t kStatusResponseUsbRxStallEventsOffset = 952U;
inline constexpr std::size_t kStatusResponseUsbTxStallEventsOffset = 956U;
inline constexpr std::size_t kStatusResponseUsbIoErrorsOffset = 960U;
inline constexpr std::size_t kStatusResponseUsbCommandQueueDepthOffset = 964U;
inline constexpr std::size_t kStatusResponseUsbResponseQueueDepthOffset = 966U;
inline constexpr std::size_t kStatusResponseUsbLowerPriorityQueueDepthOffset = 968U;
inline constexpr std::size_t kStatusResponseUsbCommandQueueHighWaterOffset = 970U;
inline constexpr std::size_t kStatusResponseUsbResponseQueueHighWaterOffset = 972U;
inline constexpr std::size_t kStatusResponseUsbActiveFrameBytesSentOffset = 974U;
inline constexpr std::size_t kStatusResponsePacketOwnedDepthOffset = 976U;
inline constexpr std::size_t kStatusResponseUsbActiveFrameSizeOffset = 978U;
inline constexpr std::size_t kStatusResponseAdcCacheDmaDiscardsOffset = 980U;
inline constexpr std::size_t kStatusResponseAdcCacheCpuInvalidationsOffset = 984U;
inline constexpr std::size_t kStatusResponseGpioCacheDmaDiscardsOffset = 988U;
inline constexpr std::size_t kStatusResponseGpioCacheCpuInvalidationsOffset = 992U;
inline constexpr std::size_t kStatusResponseBadFlagsOffset = 996U;
inline constexpr std::size_t kStatusResponseBadPayloadsOffset = 1000U;
inline constexpr std::size_t kStatusResponseBadRequestIdsOffset = 1004U;
inline constexpr std::size_t kStatusResponseResponsesQueuedOffset = 1008U;
inline constexpr std::size_t kStatusResponseResponsesCompletedOffset = 1012U;
inline constexpr std::size_t kStatusResponseResponseQueueRejectionsOffset = 1016U;
inline constexpr std::size_t kStatusResponseResponseReservationsAbandonedOffset = 1020U;
inline constexpr std::size_t kStatusResponsePacketPressureEvictionsOffset = 1024U;
inline constexpr std::size_t kStatusResponsePacketCapacityDropsWithoutEvictableFrameOffset = 1032U;
inline constexpr std::size_t kStatusResponseAdcFramesEvictedOffset = 1040U;
inline constexpr std::size_t kStatusResponseAdcFramesEvictedAfterPromotionOffset = 1048U;
inline constexpr std::size_t kStatusResponseGpioFramesEvictedOffset = 1056U;
inline constexpr std::size_t kStatusResponseGpioFramesEvictedAfterPromotionOffset = 1064U;
inline constexpr std::size_t kStatusResponseAdcPacketFillingDepthOffset = 1072U;
inline constexpr std::size_t kStatusResponseGpioPacketFillingDepthOffset = 1074U;
inline constexpr std::size_t kStatusResponseAdcFramesDroppedAfterFramingOffset = 1076U;
inline constexpr std::size_t kStatusResponseAdcFramesDroppedAfterPromotionOffset = 1084U;
inline constexpr std::size_t kStatusResponseGpioFramesDroppedAfterFramingOffset = 1092U;
inline constexpr std::size_t kStatusResponseGpioFramesDroppedAfterPromotionOffset = 1100U;
inline constexpr std::size_t kStatusResponseGpioBuffersCompletedOffset = 1108U;
inline constexpr std::size_t kStatusResponseGpioBuffersAcquiredOffset = 1116U;
inline constexpr std::size_t kStatusResponseGpioBuffersReleasedOffset = 1124U;
inline constexpr std::size_t kStatusResponseGpioSamplesDeliveredOffset = 1132U;
inline constexpr std::size_t kStatusResponseGpioStopSamplesDiscardedOffset = 1140U;
inline constexpr std::size_t kStatusResponseGpioFramesProducedOffset = 1148U;
inline constexpr std::size_t kStatusResponseGpioSamplesProducedOffset = 1156U;
inline constexpr std::size_t kStatusResponseGpioFramesPackedOffset = 1164U;
inline constexpr std::size_t kStatusResponseGpioDuplicateSamplesIgnoredOffset = 1172U;
inline constexpr std::size_t kStatusResponseAdcFramesConsumedOffset = 1180U;
inline constexpr std::size_t kStatusResponseAdcPairsConsumedOffset = 1188U;
inline constexpr std::size_t kStatusResponseAdcRawGapPairsOffset = 1196U;
inline constexpr std::size_t kStatusResponseAdcRawDropPairsProjectedOffset = 1204U;
inline constexpr std::size_t kStatusResponseGpioRawDropSamplesProjectedOffset = 1212U;
inline constexpr std::size_t kStatusResponseGpioPackerDropSamplesProjectedOffset = 1220U;
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

enum class AuxBankMode : std::uint8_t {
  kDisabled = 0U,
  kInput = 1U,
};

enum class RateProfile : std::uint8_t {
  kAdc1mhzGpio4mhz = 0U,
  kAdc500khzGpio2mhz = 1U,
  kAdc250khzGpio1mhz = 2U,
  kAdc125khzGpio500khz = 3U,
};

struct RateProfileTiming {
  RateProfile profile;
  std::uint32_t adc_pair_rate_hz;
  std::uint32_t gpio_sample_rate_hz;
  std::uint16_t adc_pair_period_ticks;
  std::uint16_t adc1_phase_ticks;
  std::uint16_t gpio_sample_period_ticks;
  std::uint16_t gpio_master_pit_divider;
  std::uint16_t gpio_master_pit_load;
  std::uint16_t adc_pair_pit_divider;
  std::uint16_t adc_pair_pit_load;
  std::uint16_t adc1_phase_ipg_cycles;
  std::uint32_t completion_expected_dwt_cycles;
  std::uint32_t disabled_frame_coverage_ticks;
  std::uint32_t input_frame_coverage_ticks;
};

inline constexpr std::size_t kMinDataFrameBytes = 2072U;
inline constexpr std::uint32_t kPitClockHz = 24000000U;
inline constexpr std::uint32_t kIpgClockHz = 150000000U;
inline constexpr std::uint32_t kDwtClockHz = 600000000U;
inline constexpr std::uint8_t kSupportedAuxBankModeMask = 3U;
inline constexpr std::uint8_t kSupportedRateProfileMask = 15U;
inline constexpr AuxBankMode kDefaultAuxBankMode =
    AuxBankMode::kDisabled;
inline constexpr RateProfile kDefaultRateProfile =
    RateProfile::kAdc1mhzGpio4mhz;
inline constexpr std::uint8_t kPrimaryGpioPinsByBit[] = {6U, 7U, 8U, 9U, 10U, 11U, 12U, 13U};
inline constexpr std::uint8_t kAuxGpioPinsByBit[] = {16U, 17U, 18U, 19U, 20U, 21U, 22U, 23U};
inline constexpr std::uint8_t kGpio16PinsByBit[] = {6U, 7U, 8U, 9U, 10U, 11U, 12U, 13U, 16U, 17U, 18U, 19U, 20U, 21U, 22U, 23U};
inline constexpr std::uint8_t kPrimaryGpioPortBitsByWireBit[] = {10U, 17U, 16U, 11U, 0U, 2U, 1U, 3U};
inline constexpr std::uint8_t kAuxGpioPortBitsByWireBit[] = {23U, 22U, 17U, 16U, 26U, 27U, 24U, 25U};
inline constexpr std::uint32_t kPrimaryGpioCaptureMask = 0x00030C0FU;
inline constexpr std::uint32_t kAuxGpioCaptureMask = 0x0FC30000U;
inline constexpr std::uint8_t kAuxGpioXbarOutput = 1U;
inline constexpr std::uint8_t kAuxGpioDmamuxSource = 31U;
inline constexpr std::uint8_t kAuxGpioEdmaChannel = 3U;
inline constexpr std::uint8_t kInputModeEdmaPriorities[] = {3U, 2U, 1U, 0U};
inline constexpr std::uint8_t kAuxGpioRawRingDepth = 4U;
inline constexpr std::uint8_t kGpioRawWordBytesPerBank = 4U;
inline constexpr bool kPairedGpioJoinRequired = true;
inline constexpr std::size_t kDisabledAdcPairsPerFrame = 1012U;
inline constexpr std::size_t kDisabledGpioSamplesPerFrame = 4048U;
inline constexpr std::size_t kInputAdcPairsPerFrame = 506U;
inline constexpr std::size_t kInputGpioSamplesPerFrame = 2024U;

inline constexpr RateProfileTiming kRateProfiles[] = {
    {RateProfile::kAdc1mhzGpio4mhz, 1000000U, 4000000U, 8U, 4U, 2U, 6U, 5U, 4U, 3U, 75U, 300U, 8096U, 4048U},
    {RateProfile::kAdc500khzGpio2mhz, 500000U, 2000000U, 16U, 8U, 4U, 12U, 11U, 4U, 3U, 150U, 600U, 16192U, 8096U},
    {RateProfile::kAdc250khzGpio1mhz, 250000U, 1000000U, 32U, 16U, 8U, 24U, 23U, 4U, 3U, 300U, 1200U, 32384U, 16192U},
    {RateProfile::kAdc125khzGpio500khz, 125000U, 500000U, 64U, 32U, 16U, 48U, 47U, 4U, 3U, 600U, 2400U, 64768U, 32384U},
};
static_assert(sizeof(kRateProfiles) / sizeof(kRateProfiles[0]) == 4U);
static_assert(kInputAdcPairsPerFrame * kAdcBytesPerPair == 2024U);
static_assert(kInputGpioSamplesPerFrame * 2U == kDataPayloadBytes);

}  // namespace thingdaq::protocol_v2
