#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>

#include "generated/protocol_constants.h"
#include "generated/protocol_v2_constants.h"
#include "rate_profile_table.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_STREAM_LAYOUT_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_STREAM_LAYOUT_COLD_CODE(section_name)
#endif

namespace thingdaq::stream_layout {

enum class Status : std::uint8_t {
  kOk,
  kInvalidAuxBankMode,
  kUnsupportedRateProfile,
  kUnsupportedRatePair,
  kInvalidGeneratedContract,
};

enum class Stream : std::uint8_t {
  kAdc = 0U,
  kGpio = 1U,
};

inline constexpr std::size_t kStreamCount = 2U;

struct FrameLayout {
  std::uint32_t item_count = 0U;
  std::uint32_t item_bytes = 0U;
  std::uint32_t item_period_ticks = 0U;
  std::uint32_t payload_bytes = 0U;
  std::uint32_t frame_bytes = 0U;
  std::uint32_t coverage_ticks = 0U;

  THINGDAQ_STREAM_LAYOUT_COLD_CODE(".flashmem.stream_layout.valid")
  constexpr bool valid() const {
    if (item_count == 0U || item_bytes == 0U ||
        item_period_ticks == 0U) {
      return false;
    }
    const std::uint64_t payload =
        static_cast<std::uint64_t>(item_count) * item_bytes;
    const std::uint64_t coverage =
        static_cast<std::uint64_t>(item_count) * item_period_ticks;
    const std::uint64_t total =
        payload + protocol_v1::kHeaderSize + protocol_v1::kTrailerSize;
    return payload == payload_bytes && coverage == coverage_ticks &&
           total == frame_bytes &&
           frame_bytes <= protocol_v2::kMaxDataFrameBytes;
  }
};

constexpr bool operator==(const FrameLayout &left,
                          const FrameLayout &right) {
  return left.item_count == right.item_count &&
         left.item_bytes == right.item_bytes &&
         left.item_period_ticks == right.item_period_ticks &&
         left.payload_bytes == right.payload_bytes &&
         left.frame_bytes == right.frame_bytes &&
         left.coverage_ticks == right.coverage_ticks;
}

constexpr bool operator!=(const FrameLayout &left,
                          const FrameLayout &right) {
  return !(left == right);
}

struct RunLayout {
  std::array<FrameLayout, kStreamCount> streams{};
  protocol_v2::AuxBankMode aux_bank_mode =
      protocol_v2::AuxBankMode::kDisabled;
  protocol_v2::RateProfile rate_profile =
      protocol_v2::RateProfile::kAdc1mhzGpio4mhz;
  std::uint8_t protocol_version = protocol_v1::kProtocolVersion;

  constexpr const FrameLayout &forStream(Stream stream) const {
    const std::size_t index = static_cast<std::size_t>(stream);
    return streams[index < streams.size() ? index : 0U];
  }

  THINGDAQ_STREAM_LAYOUT_COLD_CODE(".flashmem.stream_layout.run_valid")
  constexpr bool valid() const {
    if (!streams[0].valid() || !streams[1].valid() ||
        streams[0].coverage_ticks != streams[1].coverage_ticks) {
      return false;
    }
    if (protocol_version == protocol_v1::kProtocolVersion) {
      return aux_bank_mode == protocol_v2::AuxBankMode::kDisabled &&
             rate_profile ==
                 protocol_v2::RateProfile::kAdc1mhzGpio4mhz &&
             streams[0].item_count == protocol_v1::kAdcPairsPerFrame &&
             streams[0].item_bytes == protocol_v1::kAdcBytesPerPair &&
             streams[0].item_period_ticks ==
                 protocol_v1::kAdcPairPeriodTicks &&
             streams[0].payload_bytes == protocol_v1::kDataPayloadBytes &&
             streams[0].frame_bytes == protocol_v1::kDataFrameBytes &&
             streams[1].item_count == protocol_v1::kGpioSamplesPerFrame &&
             streams[1].item_bytes == 1U &&
             streams[1].item_period_ticks ==
                 protocol_v1::kGpioSamplePeriodTicks &&
             streams[1].payload_bytes == protocol_v1::kDataPayloadBytes &&
             streams[1].frame_bytes == protocol_v1::kDataFrameBytes;
    }
    if (protocol_version != protocol_v2::kProtocolVersion) {
      return false;
    }

    const protocol_v2::RateProfileTiming *timing = nullptr;
    timing = rate_profile::timingFor(rate_profile);
    if (timing == nullptr) {
      return false;
    }

    const bool disabled =
        aux_bank_mode == protocol_v2::AuxBankMode::kDisabled;
    const bool input = aux_bank_mode == protocol_v2::AuxBankMode::kInput;
    if (!disabled && !input) {
      return false;
    }
    const std::uint32_t adc_items = static_cast<std::uint32_t>(
        disabled ? protocol_v2::kDisabledAdcPairsPerFrame
                 : protocol_v2::kInputAdcPairsPerFrame);
    const std::uint32_t gpio_items = static_cast<std::uint32_t>(
        disabled ? protocol_v2::kDisabledGpioSamplesPerFrame
                 : protocol_v2::kInputGpioSamplesPerFrame);
    const std::uint32_t gpio_item_bytes = disabled ? 1U : 2U;
    const std::uint32_t coverage =
        disabled ? timing->disabled_frame_coverage_ticks
                 : timing->input_frame_coverage_ticks;
    return streams[0].item_count == adc_items &&
           streams[0].item_bytes == protocol_v2::kAdcBytesPerPair &&
           streams[0].item_period_ticks ==
               timing->adc_pair_period_ticks &&
           streams[0].coverage_ticks == coverage &&
           streams[1].item_count == gpio_items &&
           streams[1].item_bytes == gpio_item_bytes &&
           streams[1].item_period_ticks ==
               timing->gpio_sample_period_ticks &&
           streams[1].coverage_ticks == coverage &&
           streams[1].payload_bytes == protocol_v2::kDataPayloadBytes;
  }
};

constexpr bool operator==(const RunLayout &left, const RunLayout &right) {
  return left.streams[0] == right.streams[0] &&
         left.streams[1] == right.streams[1] &&
         left.aux_bank_mode == right.aux_bank_mode &&
         left.rate_profile == right.rate_profile &&
         left.protocol_version == right.protocol_version;
}

constexpr bool operator!=(const RunLayout &left, const RunLayout &right) {
  return !(left == right);
}

struct Result {
  Status status = Status::kInvalidGeneratedContract;
  RunLayout layout{};

  constexpr bool ok() const { return status == Status::kOk; }
};

constexpr FrameLayout makeFrameLayout(std::uint32_t item_count,
                                      std::uint32_t item_bytes,
                                      std::uint32_t period_ticks) {
  FrameLayout result{};
  result.item_count = item_count;
  result.item_bytes = item_bytes;
  result.item_period_ticks = period_ticks;
  const std::uint64_t payload =
      static_cast<std::uint64_t>(item_count) * item_bytes;
  const std::uint64_t coverage =
      static_cast<std::uint64_t>(item_count) * period_ticks;
  const std::uint64_t total =
      payload + protocol_v1::kHeaderSize + protocol_v1::kTrailerSize;
  if (payload > std::numeric_limits<std::uint32_t>::max() ||
      coverage > std::numeric_limits<std::uint32_t>::max() ||
      total > std::numeric_limits<std::uint32_t>::max()) {
    return result;
  }
  result.payload_bytes = static_cast<std::uint32_t>(payload);
  result.coverage_ticks = static_cast<std::uint32_t>(coverage);
  result.frame_bytes = static_cast<std::uint32_t>(total);
  return result;
}

constexpr RunLayout legacy() {
  RunLayout result{};
  result.streams[0] = makeFrameLayout(
      static_cast<std::uint32_t>(protocol_v1::kAdcPairsPerFrame),
      protocol_v1::kAdcBytesPerPair,
      protocol_v1::kAdcPairPeriodTicks);
  result.streams[1] = makeFrameLayout(
      static_cast<std::uint32_t>(protocol_v1::kGpioSamplesPerFrame), 1U,
      protocol_v1::kGpioSamplePeriodTicks);
  result.aux_bank_mode = protocol_v2::AuxBankMode::kDisabled;
  result.rate_profile = protocol_v2::RateProfile::kAdc1mhzGpio4mhz;
  result.protocol_version = protocol_v1::kProtocolVersion;
  return result;
}

constexpr const protocol_v2::RateProfileTiming *timingFor(
    protocol_v2::RateProfile profile) {
  return rate_profile::timingFor(profile);
}

constexpr Result experimental(protocol_v2::AuxBankMode mode,
                              protocol_v2::RateProfile profile) {
  Result result{};
  if (mode != protocol_v2::AuxBankMode::kDisabled &&
      mode != protocol_v2::AuxBankMode::kInput) {
    result.status = Status::kInvalidAuxBankMode;
    return result;
  }
  const protocol_v2::RateProfileTiming *timing = timingFor(profile);
  if (timing == nullptr) {
    result.status = Status::kUnsupportedRateProfile;
    return result;
  }

  const bool input = mode == protocol_v2::AuxBankMode::kInput;
  const std::uint32_t adc_items = static_cast<std::uint32_t>(
      input ? protocol_v2::kInputAdcPairsPerFrame
            : protocol_v2::kDisabledAdcPairsPerFrame);
  const std::uint32_t gpio_items = static_cast<std::uint32_t>(
      input ? protocol_v2::kInputGpioSamplesPerFrame
            : protocol_v2::kDisabledGpioSamplesPerFrame);
  result.layout.streams[0] = makeFrameLayout(
      adc_items, protocol_v2::kAdcBytesPerPair,
      timing->adc_pair_period_ticks);
  result.layout.streams[1] = makeFrameLayout(
      gpio_items, input ? 2U : 1U, timing->gpio_sample_period_ticks);
  result.layout.aux_bank_mode = mode;
  result.layout.rate_profile = profile;
  result.layout.protocol_version = protocol_v2::kProtocolVersion;
  result.status = result.layout.valid() ? Status::kOk
                                        : Status::kInvalidGeneratedContract;
  return result;
}

constexpr Result experimentalForRates(protocol_v2::AuxBankMode mode,
                                      std::uint32_t adc_pair_rate_hz,
                                      std::uint32_t gpio_sample_rate_hz) {
  for (const protocol_v2::RateProfileTiming &timing :
       rate_profile::kTimings) {
    if (timing.adc_pair_rate_hz == adc_pair_rate_hz &&
        timing.gpio_sample_rate_hz == gpio_sample_rate_hz) {
      return experimental(mode, timing.profile);
    }
  }
  Result result{};
  result.status = Status::kUnsupportedRatePair;
  return result;
}

static_assert(kStreamCount == 2U);
static_assert(legacy().valid());
static_assert(experimental(protocol_v2::AuxBankMode::kDisabled,
                           protocol_v2::RateProfile::kAdc1mhzGpio4mhz)
                  .ok());
static_assert(experimental(protocol_v2::AuxBankMode::kInput,
                           protocol_v2::RateProfile::kAdc125khzGpio500khz)
                  .ok());
static_assert(experimental(protocol_v2::AuxBankMode::kInput,
                           protocol_v2::RateProfile::kAdc1mhzGpio4mhz)
                  .layout.streams[0]
                  .frame_bytes == protocol_v2::kMinDataFrameBytes);

}  // namespace thingdaq::stream_layout

#undef THINGDAQ_STREAM_LAYOUT_COLD_CODE
