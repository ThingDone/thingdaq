// Generated public protocol-v3 constants. Do not edit by hand.
// Source: protocol/protocol-v3.json
// Source SHA-256: 41b4a7a4e644888e97ae7cd61686650703ee0638b4be6a793411bdfdb9a52c6c
#pragma once

#include <cstdint>

// Keep discovery-only tables out of the bounded DTCM packet/stack budget.
#if defined(__IMXRT1062__)
#define THINGDAQ_V3_TABLE_DATA __attribute__((section(".progmem.protocol_v3.tables")))
#else
#define THINGDAQ_V3_TABLE_DATA
#endif

namespace thingdaq::protocol_v3 {

inline constexpr char kSourceSha256[] = "41b4a7a4e644888e97ae7cd61686650703ee0638b4be6a793411bdfdb9a52c6c";
inline constexpr bool kWireIsLittleEndian = true;
inline constexpr std::uint32_t kMagic = 3735928559U;
inline constexpr std::uint32_t kProtocolVersion = 3U;
inline constexpr std::uint32_t kHeaderSize = 44U;
inline constexpr std::uint32_t kTrailerSize = 4U;
inline constexpr std::uint32_t kMinFrameBytes = 48U;
inline constexpr std::uint32_t kMaxCommandPayloadBytes = 20U;
inline constexpr std::uint32_t kMaxCommandFrameBytes = 68U;
inline constexpr std::uint32_t kMaxControlFrameBytes = 2048U;
inline constexpr std::uint32_t kDataPrefixBytes = 12U;
inline constexpr std::uint32_t kMaxLogicalPayloadBytes = 4048U;
inline constexpr std::uint32_t kMaxEncodedSampleBytes = 4048U;
inline constexpr std::uint32_t kMaxDataFrameBytes = 4108U;
inline constexpr std::uint32_t kMaxAdcPairs = 1012U;
inline constexpr std::uint32_t kMaxGpio8Samples = 4048U;
inline constexpr std::uint32_t kMaxGpio16Samples = 2024U;
inline constexpr std::uint32_t kMaxCpuProfiles = 2U;
inline constexpr std::uint32_t kMaxRateProfiles = 1U;
inline constexpr std::uint32_t kMaxConfigurationTuples = 64U;
inline constexpr std::uint32_t kTimestampHz = 8000000U;
inline constexpr std::uint32_t kAdcPairRateHz = 1000000U;
inline constexpr std::uint32_t kGpioSampleRateHz = 1000000U;
inline constexpr std::uint32_t kAdcPairPeriodTicks = 8U;
inline constexpr std::uint32_t kGpioSamplePeriodTicks = 8U;
inline constexpr std::uint32_t kAdc1PhaseTicks = 4U;
inline constexpr std::uint32_t kHeaderMagicOffset = 0U;
inline constexpr std::uint32_t kHeaderVersionOffset = 4U;
inline constexpr std::uint32_t kHeaderKindOffset = 5U;
inline constexpr std::uint32_t kHeaderFlagsOffset = 6U;
inline constexpr std::uint32_t kHeaderHeaderLengthOffset = 8U;
inline constexpr std::uint32_t kHeaderChecksumAlgorithmOffset = 10U;
inline constexpr std::uint32_t kHeaderReservedOffset = 11U;
inline constexpr std::uint32_t kHeaderTotalLengthOffset = 12U;
inline constexpr std::uint32_t kHeaderPayloadLengthOffset = 16U;
inline constexpr std::uint32_t kHeaderRunIdOffset = 20U;
inline constexpr std::uint32_t kHeaderSequenceOffset = 24U;
inline constexpr std::uint32_t kHeaderRequestIdOffset = 28U;
inline constexpr std::uint32_t kHeaderFirstSampleTicksOffset = 32U;
inline constexpr std::uint32_t kHeaderItemCountOffset = 40U;
inline constexpr std::uint32_t kEmptyPayloadSize = 0U;
inline constexpr std::uint32_t kResponsePrefixPayloadSize = 4U;
inline constexpr std::uint32_t kResponsePrefixResponseStatusOffset = 0U;
inline constexpr std::uint32_t kResponsePrefixReservedOffset = 1U;
inline constexpr std::uint32_t kResponsePrefixErrorCodeOffset = 2U;
inline constexpr std::uint32_t kSettingsPayloadSize = 20U;
inline constexpr std::uint32_t kSettingsStreamMaskOffset = 0U;
inline constexpr std::uint32_t kSettingsSourceOffset = 1U;
inline constexpr std::uint32_t kSettingsChecksumAlgorithmOffset = 2U;
inline constexpr std::uint32_t kSettingsWireVersionOffset = 3U;
inline constexpr std::uint32_t kSettingsCpuProfileOffset = 4U;
inline constexpr std::uint32_t kSettingsRateProfileOffset = 5U;
inline constexpr std::uint32_t kSettingsAuxBankModeOffset = 6U;
inline constexpr std::uint32_t kSettingsGpioWidthBitsOffset = 7U;
inline constexpr std::uint32_t kSettingsGpioPolicyOffset = 8U;
inline constexpr std::uint32_t kSettingsAdcPolicyOffset = 9U;
inline constexpr std::uint32_t kSettingsAdcResolutionBitsOffset = 10U;
inline constexpr std::uint32_t kSettingsReservedOffset = 11U;
inline constexpr std::uint32_t kSettingsAdcPairRateHzOffset = 12U;
inline constexpr std::uint32_t kSettingsGpioSampleRateHzOffset = 16U;
inline constexpr std::uint32_t kCpuProfileInfoPayloadSize = 24U;
inline constexpr std::uint32_t kCpuProfileInfoCpuProfileOffset = 0U;
inline constexpr std::uint32_t kCpuProfileInfoReserved0Offset = 1U;
inline constexpr std::uint32_t kCpuProfileInfoReserved1Offset = 2U;
inline constexpr std::uint32_t kCpuProfileInfoCpuClockHzOffset = 4U;
inline constexpr std::uint32_t kCpuProfileInfoIpgClockHzOffset = 8U;
inline constexpr std::uint32_t kCpuProfileInfoAdcClockHzOffset = 12U;
inline constexpr std::uint32_t kCpuProfileInfoPitClockHzOffset = 16U;
inline constexpr std::uint32_t kCpuProfileInfoTimestampHzOffset = 20U;
inline constexpr std::uint32_t kRateProfileInfoPayloadSize = 20U;
inline constexpr std::uint32_t kRateProfileInfoRateProfileOffset = 0U;
inline constexpr std::uint32_t kRateProfileInfoReserved0Offset = 1U;
inline constexpr std::uint32_t kRateProfileInfoReserved1Offset = 2U;
inline constexpr std::uint32_t kRateProfileInfoAdcPairRateHzOffset = 4U;
inline constexpr std::uint32_t kRateProfileInfoGpioSampleRateHzOffset = 8U;
inline constexpr std::uint32_t kRateProfileInfoAdcPairPeriodTicksOffset = 12U;
inline constexpr std::uint32_t kRateProfileInfoGpioSamplePeriodTicksOffset = 14U;
inline constexpr std::uint32_t kRateProfileInfoAdc1PhaseTicksOffset = 16U;
inline constexpr std::uint32_t kRateProfileInfoReserved2Offset = 18U;
inline constexpr std::uint32_t kConfigureRequestPayloadSize = 20U;
inline constexpr std::uint32_t kConfigureRequestSettingsOffset = 0U;
inline constexpr std::uint32_t kConfigureRequestSettingsCount = 1U;
inline constexpr std::uint32_t kSettingsResponsePayloadSize = 48U;
inline constexpr std::uint32_t kSettingsResponseResponseStatusOffset = 0U;
inline constexpr std::uint32_t kSettingsResponseReservedOffset = 1U;
inline constexpr std::uint32_t kSettingsResponseErrorCodeOffset = 2U;
inline constexpr std::uint32_t kSettingsResponseSettingsOffset = 4U;
inline constexpr std::uint32_t kSettingsResponseSettingsCount = 1U;
inline constexpr std::uint32_t kSettingsResponseClocksOffset = 24U;
inline constexpr std::uint32_t kSettingsResponseClocksCount = 1U;
inline constexpr std::uint32_t kInfoResponsePayloadSize = 132U;
inline constexpr std::uint32_t kInfoResponseResponseStatusOffset = 0U;
inline constexpr std::uint32_t kInfoResponseReservedOffset = 1U;
inline constexpr std::uint32_t kInfoResponseErrorCodeOffset = 2U;
inline constexpr std::uint32_t kInfoResponseBoardIdOffset = 4U;
inline constexpr std::uint32_t kInfoResponseMcuIdOffset = 6U;
inline constexpr std::uint32_t kInfoResponseSimulatedOffset = 8U;
inline constexpr std::uint32_t kInfoResponseProtocolVersionOffset = 9U;
inline constexpr std::uint32_t kInfoResponseAdcResolutionBitsOffset = 10U;
inline constexpr std::uint32_t kInfoResponseReserved1Offset = 11U;
inline constexpr std::uint32_t kInfoResponseHardwareSerialOffset = 12U;
inline constexpr std::uint32_t kInfoResponseHardwareSerialCount = 32U;
inline constexpr std::uint32_t kInfoResponseFirmwareVersionOffset = 44U;
inline constexpr std::uint32_t kInfoResponseFirmwareVersionCount = 16U;
inline constexpr std::uint32_t kInfoResponseBuildIdOffset = 60U;
inline constexpr std::uint32_t kInfoResponseBuildIdCount = 48U;
inline constexpr std::uint32_t kInfoResponseClocksOffset = 108U;
inline constexpr std::uint32_t kInfoResponseClocksCount = 1U;
inline constexpr std::uint32_t kCapabilitiesResponsePayloadSize = 1404U;
inline constexpr std::uint32_t kCapabilitiesResponseResponseStatusOffset = 0U;
inline constexpr std::uint32_t kCapabilitiesResponseReservedOffset = 1U;
inline constexpr std::uint32_t kCapabilitiesResponseErrorCodeOffset = 2U;
inline constexpr std::uint32_t kCapabilitiesResponseCpuProfileCountOffset = 4U;
inline constexpr std::uint32_t kCapabilitiesResponseRateProfileCountOffset = 5U;
inline constexpr std::uint32_t kCapabilitiesResponseConfigurationCountOffset = 6U;
inline constexpr std::uint32_t kCapabilitiesResponseReserved1Offset = 7U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxDataFrameBytesOffset = 8U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxControlFrameBytesOffset = 12U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxLogicalPayloadBytesOffset = 16U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxEncodedSampleBytesOffset = 20U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxAdcPairsOffset = 24U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxGpio8SamplesOffset = 28U;
inline constexpr std::uint32_t kCapabilitiesResponseMaxGpio16SamplesOffset = 32U;
inline constexpr std::uint32_t kCapabilitiesResponseDefaultsOffset = 36U;
inline constexpr std::uint32_t kCapabilitiesResponseDefaultsCount = 1U;
inline constexpr std::uint32_t kCapabilitiesResponseCpuProfilesOffset = 56U;
inline constexpr std::uint32_t kCapabilitiesResponseCpuProfilesCount = 2U;
inline constexpr std::uint32_t kCapabilitiesResponseRateProfilesOffset = 104U;
inline constexpr std::uint32_t kCapabilitiesResponseRateProfilesCount = 1U;
inline constexpr std::uint32_t kCapabilitiesResponseConfigurationsOffset = 124U;
inline constexpr std::uint32_t kCapabilitiesResponseConfigurationsCount = 64U;
inline constexpr std::uint32_t kStatusResponsePayloadSize = 256U;
inline constexpr std::uint32_t kStatusResponseResponseStatusOffset = 0U;
inline constexpr std::uint32_t kStatusResponseReservedOffset = 1U;
inline constexpr std::uint32_t kStatusResponseErrorCodeOffset = 2U;
inline constexpr std::uint32_t kStatusResponseStateOffset = 4U;
inline constexpr std::uint32_t kStatusResponseReserved1Offset = 5U;
inline constexpr std::uint32_t kStatusResponseReserved2Offset = 6U;
inline constexpr std::uint32_t kStatusResponseRunIdOffset = 8U;
inline constexpr std::uint32_t kStatusResponsePendingFramesOffset = 12U;
inline constexpr std::uint32_t kStatusResponseAdcFramesProducedOffset = 16U;
inline constexpr std::uint32_t kStatusResponseAdcFramesDroppedOffset = 24U;
inline constexpr std::uint32_t kStatusResponseAdcItemsProducedOffset = 32U;
inline constexpr std::uint32_t kStatusResponseAdcItemsDroppedOffset = 40U;
inline constexpr std::uint32_t kStatusResponseGpioFramesProducedOffset = 48U;
inline constexpr std::uint32_t kStatusResponseGpioFramesDroppedOffset = 56U;
inline constexpr std::uint32_t kStatusResponseGpioItemsProducedOffset = 64U;
inline constexpr std::uint32_t kStatusResponseGpioItemsDroppedOffset = 72U;
inline constexpr std::uint32_t kStatusResponseAdcCodecCompletedOffset = 80U;
inline constexpr std::uint32_t kStatusResponseAdcCodecRawOffset = 88U;
inline constexpr std::uint32_t kStatusResponseAdcCodecDeadlineDropsOffset = 96U;
inline constexpr std::uint32_t kStatusResponseAdcCodecResourceDropsOffset = 104U;
inline constexpr std::uint32_t kStatusResponseAdcCodecWorkTicksOffset = 112U;
inline constexpr std::uint32_t kStatusResponseAdcCodecMaxWorkTicksOffset = 120U;
inline constexpr std::uint32_t kStatusResponseAdcCodecMaxAgeTicksOffset = 128U;
inline constexpr std::uint32_t kStatusResponseGpioCodecCompletedOffset = 136U;
inline constexpr std::uint32_t kStatusResponseGpioCodecRawOffset = 144U;
inline constexpr std::uint32_t kStatusResponseGpioCodecDeadlineDropsOffset = 152U;
inline constexpr std::uint32_t kStatusResponseGpioCodecResourceDropsOffset = 160U;
inline constexpr std::uint32_t kStatusResponseGpioCodecWorkTicksOffset = 168U;
inline constexpr std::uint32_t kStatusResponseGpioCodecMaxWorkTicksOffset = 176U;
inline constexpr std::uint32_t kStatusResponseGpioCodecMaxAgeTicksOffset = 184U;
inline constexpr std::uint32_t kStatusResponseAdcWireBytesTransmittedOffset = 192U;
inline constexpr std::uint32_t kStatusResponseAdcItemsPerFrameOffset = 200U;
inline constexpr std::uint32_t kStatusResponseAdcMaxFrameBytesOffset = 208U;
inline constexpr std::uint32_t kStatusResponseAdcRetentionTicksOffset = 216U;
inline constexpr std::uint32_t kStatusResponseGpioWireBytesTransmittedOffset = 224U;
inline constexpr std::uint32_t kStatusResponseGpioItemsPerFrameOffset = 232U;
inline constexpr std::uint32_t kStatusResponseGpioMaxFrameBytesOffset = 240U;
inline constexpr std::uint32_t kStatusResponseGpioRetentionTicksOffset = 248U;
inline constexpr std::uint32_t kStopResponsePayloadSize = 16U;
inline constexpr std::uint32_t kStopResponseResponseStatusOffset = 0U;
inline constexpr std::uint32_t kStopResponseReservedOffset = 1U;
inline constexpr std::uint32_t kStopResponseErrorCodeOffset = 2U;
inline constexpr std::uint32_t kStopResponseStateOffset = 4U;
inline constexpr std::uint32_t kStopResponseReserved1Offset = 5U;
inline constexpr std::uint32_t kStopResponseReserved2Offset = 6U;
inline constexpr std::uint32_t kStopResponseRunIdOffset = 8U;
inline constexpr std::uint32_t kStopResponsePendingFramesOffset = 12U;
inline constexpr std::uint32_t kErrorResponsePayloadSize = 8U;
inline constexpr std::uint32_t kErrorResponseResponseStatusOffset = 0U;
inline constexpr std::uint32_t kErrorResponseReservedOffset = 1U;
inline constexpr std::uint32_t kErrorResponseErrorCodeOffset = 2U;
inline constexpr std::uint32_t kErrorResponseRejectedKindOffset = 4U;
inline constexpr std::uint32_t kErrorResponseReserved1Offset = 5U;
inline constexpr std::uint32_t kErrorResponseReserved2Offset = 6U;
inline constexpr std::uint32_t kDataPrefixPayloadSize = 12U;
inline constexpr std::uint32_t kDataPrefixEncodingOffset = 0U;
inline constexpr std::uint32_t kDataPrefixItemBytesOffset = 1U;
inline constexpr std::uint32_t kDataPrefixReservedOffset = 2U;
inline constexpr std::uint32_t kDataPrefixDecodedBytesOffset = 4U;
inline constexpr std::uint32_t kDataPrefixRunCountOffset = 8U;
inline constexpr std::uint32_t kAdcRawPairPayloadSize = 4U;
inline constexpr std::uint32_t kAdcRawPairAdc0Offset = 0U;
inline constexpr std::uint32_t kAdcRawPairAdc1Offset = 2U;
inline constexpr std::uint32_t kAdcPack12PairPayloadSize = 3U;
inline constexpr std::uint32_t kAdcPack12PairAdc0Low8Offset = 0U;
inline constexpr std::uint32_t kAdcPack12PairAdc1Low4Adc0High4Offset = 1U;
inline constexpr std::uint32_t kAdcPack12PairAdc1High8Offset = 2U;
inline constexpr std::uint32_t kGpio8RleRecordPayloadSize = 3U;
inline constexpr std::uint32_t kGpio8RleRecordRunLengthOffset = 0U;
inline constexpr std::uint32_t kGpio8RleRecordValueOffset = 2U;
inline constexpr std::uint32_t kGpio16RleRecordPayloadSize = 4U;
inline constexpr std::uint32_t kGpio16RleRecordRunLengthOffset = 0U;
inline constexpr std::uint32_t kGpio16RleRecordValueOffset = 2U;

enum class FrameKind : std::uint8_t {
  kAdcData = 1U,
  kGpioData = 2U,
  kInfoRequest = 16U,
  kInfoResponse = 144U,
  kConfigureRequest = 17U,
  kConfigureResponse = 145U,
  kStartRequest = 18U,
  kStartResponse = 146U,
  kGetStatusRequest = 19U,
  kGetStatusResponse = 147U,
  kStopRequest = 20U,
  kStopResponse = 148U,
  kGetCapabilitiesRequest = 28U,
  kGetCapabilitiesResponse = 156U,
  kGetSettingsRequest = 29U,
  kGetSettingsResponse = 157U,
  kErrorResponse = 159U,
};

enum class CommandKind : std::uint8_t {
  kInfo = 16U,
  kConfigure = 17U,
  kStart = 18U,
  kGetStatus = 19U,
  kStop = 20U,
  kGetCapabilities = 28U,
  kGetSettings = 29U,
};

enum class FrameFlag : std::uint16_t {
  kSynthetic = 1U,
  kGapBefore = 2U,
  kEpochStart = 4U,
  kOverrunBefore = 8U,
  kResponseError = 32768U,
};

enum class ChecksumAlgorithm : std::uint8_t {
  kAdler32 = 1U,
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

enum class StreamMask : std::uint8_t {
  kAdc = 1U,
  kGpio = 2U,
};

enum class Source : std::uint8_t {
  kHardware = 0U,
  kSynthetic = 1U,
};

enum class AuxBankMode : std::uint8_t {
  kDisabled = 0U,
  kInput = 1U,
};

enum class DeviceState : std::uint8_t {
  kStopped = 1U,
  kRunning = 3U,
  kDraining = 4U,
};

enum class BoardId : std::uint16_t {
  kTeensy40 = 1U,
};

enum class McuId : std::uint16_t {
  kImxrt1062 = 1U,
};

enum class CpuProfile : std::uint8_t {
  kCpu600mhz = 1U,
  kCpu450mhz = 2U,
};

enum class RateProfile : std::uint8_t {
  kAdc1mhzGpio1mhz = 4U,
};

enum class GpioPolicy : std::uint8_t {
  kRaw = 0U,
  kRleAuto = 1U,
};

enum class AdcPolicy : std::uint8_t {
  kRaw = 0U,
  kPack12 = 1U,
};

enum class Encoding : std::uint8_t {
  kRaw = 0U,
  kGpioRle = 1U,
  kAdcPack12 = 2U,
};

inline constexpr std::uint8_t kDefaultSettings[][20] THINGDAQ_V3_TABLE_DATA = {
  {3U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
};

inline constexpr std::uint8_t kCpuProfiles[][24] THINGDAQ_V3_TABLE_DATA = {
  {1U, 0U, 0U, 0U, 0U, 70U, 195U, 35U, 128U, 209U, 240U, 8U, 96U, 52U, 60U, 2U, 0U, 54U, 110U, 1U, 0U, 18U, 122U, 0U},
  {2U, 0U, 0U, 0U, 128U, 116U, 210U, 26U, 128U, 209U, 240U, 8U, 96U, 52U, 60U, 2U, 0U, 54U, 110U, 1U, 0U, 18U, 122U, 0U},
};

inline constexpr std::uint8_t kRateProfiles[][20] THINGDAQ_V3_TABLE_DATA = {
  {4U, 0U, 0U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U, 8U, 0U, 8U, 0U, 4U, 0U, 0U, 0U},
};

inline constexpr std::uint8_t kSelectableConfigurations[][20] THINGDAQ_V3_TABLE_DATA = {
  {1U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 0U, 8U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 0U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 1U, 4U, 1U, 16U, 1U, 1U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 2U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 2U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 2U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 2U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 2U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 2U, 4U, 0U, 8U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 0U, 1U, 3U, 2U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {1U, 1U, 1U, 3U, 2U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 0U, 1U, 3U, 2U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {2U, 1U, 1U, 3U, 2U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 0U, 1U, 3U, 2U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
  {3U, 1U, 1U, 3U, 2U, 4U, 1U, 16U, 0U, 0U, 12U, 0U, 64U, 66U, 15U, 0U, 64U, 66U, 15U, 0U},
};

}  // namespace thingdaq::protocol_v3

#undef THINGDAQ_V3_TABLE_DATA
