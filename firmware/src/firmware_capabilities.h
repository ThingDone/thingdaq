#pragma once

#include <cstddef>
#include <cstdint>

#include "firmware_identity.h"
#include "generated/protocol_constants.h"

namespace thingdaq::capabilities {

struct CapabilityMetadata {
  std::uint8_t protocol_version;
  std::uint8_t supported_stream_mask;
  std::uint8_t supported_source_mask;
  std::uint16_t supported_configuration_mask;
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

constexpr std::uint16_t configurationProfileBit(
    protocol_v1::Source source, std::uint8_t stream_mask) {
  const std::uint8_t adc =
      static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc);
  const std::uint8_t gpio =
      static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
  if (source == protocol_v1::Source::kHardware) {
    if (stream_mask == adc) {
      return static_cast<std::uint16_t>(
          protocol_v1::ConfigurationProfile::kHardwareAdc);
    }
    if (stream_mask == gpio) {
      return static_cast<std::uint16_t>(
          protocol_v1::ConfigurationProfile::kHardwareGpio);
    }
    if (stream_mask == static_cast<std::uint8_t>(adc | gpio)) {
      return static_cast<std::uint16_t>(
          protocol_v1::ConfigurationProfile::kHardwareCombined);
    }
  }
  if (source == protocol_v1::Source::kSynthetic) {
    if (stream_mask == adc) {
      return static_cast<std::uint16_t>(
          protocol_v1::ConfigurationProfile::kSyntheticAdc);
    }
    if (stream_mask == gpio) {
      return static_cast<std::uint16_t>(
          protocol_v1::ConfigurationProfile::kSyntheticGpio);
    }
    if (stream_mask == static_cast<std::uint8_t>(adc | gpio)) {
      return static_cast<std::uint16_t>(
          protocol_v1::ConfigurationProfile::kSyntheticCombined);
    }
  }
  return 0U;
}

constexpr bool supportsConfiguration(protocol_v1::Source source,
                                     std::uint8_t stream_mask) {
  const std::uint16_t profile = configurationProfileBit(source, stream_mask);
  return profile != 0U &&
         (protocol_v1::kSupportedConfigurationMask & profile) != 0U;
}

// Every nonempty ADC/GPIO subset is available from either the shared physical
// controller or the deterministic synthetic USB/host baseline. The explicit
// profile mask prevents a host from inferring unsupported cross-products.
inline constexpr std::uint8_t kSupportedStreamMask =
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc) |
    static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
inline constexpr std::uint8_t kSupportedSourceMask =
    sourceBit(protocol_v1::Source::kHardware) |
    sourceBit(protocol_v1::Source::kSynthetic);
inline constexpr std::uint32_t kCapabilityBits =
    capabilityBit(protocol_v1::Capability::kAdcStream) |
    capabilityBit(protocol_v1::Capability::kGpioStream) |
    capabilityBit(protocol_v1::Capability::kHardwareSource) |
    capabilityBit(protocol_v1::Capability::kSyntheticSource) |
    capabilityBit(protocol_v1::Capability::kResetStats) |
    capabilityBit(protocol_v1::Capability::kPing) |
    capabilityBit(protocol_v1::Capability::kChecksumBenchmark) |
    capabilityBit(protocol_v1::Capability::kGpioClockDiagnostic) |
    capabilityBit(protocol_v1::Capability::kGpioCaptureDiagnostic);
inline constexpr std::uint16_t kGpioCaptureDiagnosticInfoFlags =
    static_cast<std::uint16_t>(
        protocol_v1::GpioCaptureDiagnosticFlag::kAvailable) |
    static_cast<std::uint16_t>(
        protocol_v1::GpioCaptureDiagnosticFlag::kDeclarationValid);
inline constexpr std::uint32_t kAdc0PhaseTicks = 0U;

inline constexpr CapabilityMetadata kMetadata{
    identity::kProtocolVersion,
    kSupportedStreamMask,
    kSupportedSourceMask,
    protocol_v1::kSupportedConfigurationMask,
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
    capabilityBit(protocol_v1::Capability::kSyntheticSource) |
    capabilityBit(protocol_v1::Capability::kHardwareSource);

static_assert(kMetadata.supported_stream_mask == 3U);
static_assert(kMetadata.supported_configuration_mask ==
              protocol_v1::kKnownConfigurationProfileMask);
static_assert(supportsConfiguration(protocol_v1::Source::kHardware, 1U));
static_assert(supportsConfiguration(protocol_v1::Source::kHardware, 2U));
static_assert(supportsConfiguration(protocol_v1::Source::kHardware, 3U));
static_assert(supportsConfiguration(protocol_v1::Source::kSynthetic, 1U));
static_assert(supportsConfiguration(protocol_v1::Source::kSynthetic, 2U));
static_assert(supportsConfiguration(protocol_v1::Source::kSynthetic, 3U));
static_assert(!supportsConfiguration(protocol_v1::Source::kHardware, 0U));
static_assert((kMetadata.capability_bits & kDataCapabilityMask) ==
              kDataCapabilityMask);
static_assert(kMetadata.supported_source_mask ==
              (sourceBit(protocol_v1::Source::kHardware) |
               sourceBit(protocol_v1::Source::kSynthetic)));
static_assert(kMetadata.supported_checksum_mask ==
              ((1U << static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kAdler32)) |
               (1U << static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kCrc32c)) |
               (1U << static_cast<std::uint8_t>(
                          protocol_v1::ChecksumAlgorithm::kCrc32IsoHdlc))));
static_assert((kMetadata.supported_checksum_mask &
               (1U << static_cast<std::uint8_t>(
                    protocol_v1::kDefaultChecksumAlgorithm))) != 0U);
static_assert(kMetadata.adc0_phase_ticks == 0U &&
              kMetadata.adc1_phase_ticks * 2U ==
                  kMetadata.adc_pair_period_ticks);
static_assert(kMetadata.gpio_pin_count == 8U);
static_assert(kMetadata.max_command_frame_bytes <=
              kMetadata.max_control_frame_bytes);
static_assert(kMetadata.gpio_sample_rate_hz ==
              protocol_v1::kGpioClockProductionRateHz,
              "diagnostic rates must not weaken the production GPIO rate");
}  // namespace thingdaq::capabilities
