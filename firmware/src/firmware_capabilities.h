#pragma once

#include <cstddef>
#include <cstdint>

#include "firmware_identity.h"
#include "generated/protocol_constants.h"

namespace teensy_daq::capabilities {

struct CapabilityMetadata {
  std::uint8_t protocol_version;
  std::uint8_t supported_stream_mask;
  std::uint8_t supported_source_mask;
  std::uint32_t supported_checksum_mask;
  std::uint32_t capability_bits;
  std::uint32_t timestamp_hz;
  std::size_t data_frame_bytes;
  std::size_t max_control_frame_bytes;
  std::size_t max_command_frame_bytes;
  std::size_t max_command_payload_bytes;
  std::uint32_t adc_pair_rate_hz;
  std::uint32_t gpio_sample_rate_hz;
  std::uint32_t adc_pair_period_ticks;
  std::uint32_t adc0_phase_ticks;
  std::uint32_t adc1_phase_ticks;
  std::uint32_t gpio_sample_period_ticks;
  std::uint8_t adc_resolution_bits;
  std::uint8_t adc_container_bytes;
  const std::uint8_t *gpio_pins_by_bit;
  std::size_t gpio_pin_count;
};

constexpr std::uint32_t capabilityBit(protocol_v1::Capability capability) {
  return static_cast<std::uint32_t>(capability);
}

constexpr std::uint8_t sourceBit(protocol_v1::Source source) {
  return static_cast<std::uint8_t>(
      1U << static_cast<std::uint8_t>(source));
}

// Phase 05 implements both deterministic stream layouts through the synthetic
// source. Physical ownership stays unadvertised until the peripheral phases
// replace these generators.
inline constexpr std::uint8_t kSupportedStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
inline constexpr std::uint8_t kSupportedSourceMask =
    sourceBit(protocol_v1::Source::kSynthetic);
inline constexpr std::uint32_t kCapabilityBits =
    capabilityBit(protocol_v1::Capability::kAdcStream) |
    capabilityBit(protocol_v1::Capability::kGpioStream) |
    capabilityBit(protocol_v1::Capability::kSyntheticSource) |
    capabilityBit(protocol_v1::Capability::kResetStats) |
    capabilityBit(protocol_v1::Capability::kPing) |
    capabilityBit(protocol_v1::Capability::kChecksumBenchmark);
inline constexpr std::uint32_t kAdc0PhaseTicks = 0U;

inline constexpr CapabilityMetadata kMetadata{
    identity::kProtocolVersion,
    kSupportedStreamMask,
    kSupportedSourceMask,
    protocol_v1::kSupportedChecksumMask,
    kCapabilityBits,
    protocol_v1::kTimestampHz,
    protocol_v1::kDataFrameBytes,
    protocol_v1::kMaxControlFrameBytes,
    protocol_v1::kMaxCommandFrameBytes,
    protocol_v1::kMaxCommandPayloadBytes,
    protocol_v1::kAdcPairRateHz,
    protocol_v1::kGpioSampleRateHz,
    protocol_v1::kAdcPairPeriodTicks,
    kAdc0PhaseTicks,
    protocol_v1::kAdc1PhaseTicks,
    protocol_v1::kGpioSamplePeriodTicks,
    protocol_v1::kAdcResolutionBits,
    static_cast<std::uint8_t>(protocol_v1::kAdcContainerBits / 8U),
    protocol_v1::kGpioPinsByBit,
    sizeof(protocol_v1::kGpioPinsByBit) /
        sizeof(protocol_v1::kGpioPinsByBit[0]),
};

inline constexpr std::uint32_t kDataCapabilityMask =
    capabilityBit(protocol_v1::Capability::kAdcStream) |
    capabilityBit(protocol_v1::Capability::kGpioStream) |
    capabilityBit(protocol_v1::Capability::kSyntheticSource);

static_assert(kMetadata.supported_stream_mask == 3U);
static_assert((kMetadata.capability_bits & kDataCapabilityMask) ==
              kDataCapabilityMask);
static_assert((kMetadata.capability_bits & capabilityBit(
               protocol_v1::Capability::kHardwareSource)) == 0U);
static_assert(kMetadata.supported_source_mask ==
              sourceBit(protocol_v1::Source::kSynthetic));
static_assert(kMetadata.supported_checksum_mask ==
              ((1U << static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kAdler32)) |
               (1U << static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kCrc32c)) |
               (1U << static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kCrc32IsoHdlc))));
static_assert(kMetadata.adc0_phase_ticks == 0U &&
              kMetadata.adc1_phase_ticks * 2U ==
                  kMetadata.adc_pair_period_ticks);
static_assert(kMetadata.gpio_pin_count == 8U);
static_assert(kMetadata.max_command_frame_bytes <=
              kMetadata.max_control_frame_bytes);

}  // namespace teensy_daq::capabilities
