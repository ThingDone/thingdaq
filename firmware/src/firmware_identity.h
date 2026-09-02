#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "generated/protocol_constants.h"

// The repository build helper supplies numeric provenance macros. Numeric
// values survive both Arduino's sketch-discovery preprocessor and its normal
// compiler recipe without tool-specific string-quote behavior.
#if defined(ARDUINO) && !defined(THINGDAQ_SOURCE_ID_WORD0)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_SOURCE_ID_WORD1)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_SOURCE_ID_WORD2)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_SOURCE_ID_WORD3)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_BUILD_EPOCH)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_BUILD_ID_WORD)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_CPU_PROFILE_MHZ)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_EXPECTED_CPU_HZ)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(THINGDAQ_EXPECTED_BUS_HZ)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) &&                                                \
    (!defined(THINGDAQ_BUILD_YEAR) ||                               \
     !defined(THINGDAQ_BUILD_MONTH) ||                              \
     !defined(THINGDAQ_BUILD_DAY) ||                                \
     !defined(THINGDAQ_BUILD_HOUR) ||                               \
     !defined(THINGDAQ_BUILD_MINUTE) ||                             \
     !defined(THINGDAQ_BUILD_SECOND))
#error "build firmware with firmware/tools/build_firmware.py"
#endif

#ifndef THINGDAQ_SOURCE_ID_WORD0
#define THINGDAQ_SOURCE_ID_WORD0 0ULL
#endif
#ifndef THINGDAQ_SOURCE_ID_WORD1
#define THINGDAQ_SOURCE_ID_WORD1 0ULL
#endif
#ifndef THINGDAQ_SOURCE_ID_WORD2
#define THINGDAQ_SOURCE_ID_WORD2 0ULL
#endif
#ifndef THINGDAQ_SOURCE_ID_WORD3
#define THINGDAQ_SOURCE_ID_WORD3 0ULL
#endif
#ifndef THINGDAQ_BUILD_EPOCH
#define THINGDAQ_BUILD_EPOCH 0ULL
#endif
#ifndef THINGDAQ_BUILD_ID_WORD
#define THINGDAQ_BUILD_ID_WORD THINGDAQ_SOURCE_ID_WORD0
#endif
#ifndef THINGDAQ_CPU_PROFILE_MHZ
#define THINGDAQ_CPU_PROFILE_MHZ 600U
#endif
#ifndef THINGDAQ_EXPECTED_CPU_HZ
#define THINGDAQ_EXPECTED_CPU_HZ 600000000U
#endif
#ifndef THINGDAQ_EXPECTED_BUS_HZ
#define THINGDAQ_EXPECTED_BUS_HZ 150000000U
#endif
#ifndef THINGDAQ_BUILD_YEAR
#define THINGDAQ_BUILD_YEAR 1970U
#endif
#ifndef THINGDAQ_BUILD_MONTH
#define THINGDAQ_BUILD_MONTH 1U
#endif
#ifndef THINGDAQ_BUILD_DAY
#define THINGDAQ_BUILD_DAY 1U
#endif
#ifndef THINGDAQ_BUILD_HOUR
#define THINGDAQ_BUILD_HOUR 0U
#endif
#ifndef THINGDAQ_BUILD_MINUTE
#define THINGDAQ_BUILD_MINUTE 0U
#endif
#ifndef THINGDAQ_BUILD_SECOND
#define THINGDAQ_BUILD_SECOND 0U
#endif

// The helper injects one complete clock contract. Reject hand-crafted or stale
// combinations even outside Arduino so portable compile tests exercise the
// same closed two-profile registry.
#if THINGDAQ_CPU_PROFILE_MHZ == 600U
#if THINGDAQ_EXPECTED_CPU_HZ != 600000000U || \
    THINGDAQ_EXPECTED_BUS_HZ != 150000000U
#error "invalid ThingDAQ 600 MHz clock profile"
#endif
#elif THINGDAQ_CPU_PROFILE_MHZ == 528U
#if THINGDAQ_EXPECTED_CPU_HZ != 528000000U || \
    THINGDAQ_EXPECTED_BUS_HZ != 132000000U
#error "invalid ThingDAQ 528 MHz clock profile"
#endif
#else
#error "ThingDAQ supports only the explicit 600 or 528 MHz CPU profile"
#endif

// Fail closed when an Arduino build bypasses the exact Teensy 4.0 target. The
// core version and optimization menu are also checked by build_firmware.py;
// these preprocessor checks prevent a copied sketch from silently degrading.
#if defined(ARDUINO)
#if !defined(ARDUINO_TEENSY40)
#error "ThingDAQ supports only ARDUINO_TEENSY40"
#endif
#if !defined(__IMXRT1062__)
#error "ThingDAQ requires the i.MX RT1062"
#endif
#if !defined(F_CPU) || F_CPU != THINGDAQ_EXPECTED_CPU_HZ
#error "ThingDAQ F_CPU does not match the selected CPU profile"
#endif
#if !defined(USB_SERIAL)
#error "ThingDAQ requires the USB Serial menu option"
#endif
#if !defined(TEENSYDUINO) || TEENSYDUINO != 160
#error "unexpected Teensy core compile identity"
#endif
#if __cplusplus < 201703L
#error "ThingDAQ requires the pinned core's GNU C++17 mode"
#endif
#if !defined(THINGDAQ_OPTIMIZATION_O2STD) || \
    THINGDAQ_OPTIMIZATION_O2STD != 1
#error "ThingDAQ requires the validated standard -O2 build"
#endif
#if __GNUC__ != 15 || __GNUC_MINOR__ != 2
#error "ThingDAQ requires Arm GNU 15.2.1"
#endif
#endif

namespace thingdaq::identity {

struct SemanticVersion {
  std::uint8_t major;
  std::uint8_t minor;
  std::uint8_t patch;
};

inline constexpr char kProductName[] = "ThingDAQ";
inline constexpr std::array<std::uint16_t, 8U> kUsbProductNameUtf16{
    'T', 'h', 'i', 'n', 'g', 'D', 'A', 'Q',
};
inline constexpr char kBoardName[] = "Teensy 4.0";
inline constexpr char kMcuName[] = "NXP i.MX RT1062";
inline constexpr char kCpuArchitecture[] = "Arm Cortex-M7";
inline constexpr std::uint16_t kCpuProfileMhz = THINGDAQ_CPU_PROFILE_MHZ;
#if THINGDAQ_CPU_PROFILE_MHZ == 600U
inline constexpr protocol_v1::ClockProfile kClockProfile =
    protocol_v1::ClockProfile::kProduction600Mhz;
#else
inline constexpr protocol_v1::ClockProfile kClockProfile =
    protocol_v1::ClockProfile::kExperimental528Mhz;
#endif
inline constexpr const protocol_v1::ClockProfileSpec &kClockProfileSpec =
    protocol_v1::clockProfileSpec(kClockProfile);
inline constexpr std::uint32_t kExpectedCpuHz = THINGDAQ_EXPECTED_CPU_HZ;
inline constexpr std::uint32_t kExpectedBusHz = THINGDAQ_EXPECTED_BUS_HZ;
inline constexpr std::uint32_t kExpectedDwtHz = kExpectedCpuHz;
inline constexpr std::uint32_t kExpectedIpgHz = kExpectedBusHz;
inline constexpr std::uint32_t kExpectedPitHz = kClockProfileSpec.pit_hz;
inline constexpr std::uint16_t kCoreVoltageTargetMv =
    kClockProfileSpec.core_voltage_target_mv;
inline constexpr std::uint32_t kExpectedGpioSampleRateHz =
    protocol_v1::kGpioClockProductionRateHz;
inline constexpr std::uint32_t kExpectedAdcPairRateHz =
    protocol_v1::kAdcTriggerPairRateHz;
inline constexpr std::uint8_t kExpectedAdcClockDivider =
    protocol_v1::kAdcClockDivider;
inline constexpr std::uint32_t kExpectedAdcClockHz = kClockProfileSpec.adc_hz;
inline constexpr std::uint32_t kAdcNominalPhaseNanoseconds = 500U;
inline constexpr std::uint16_t kAdcNominalPhaseIpgCycles =
    kClockProfileSpec.phase_ipg_cycles;
inline constexpr std::array<std::uint16_t, 2U> kAdcTriggerInitialDelays{
    0U, kAdcNominalPhaseIpgCycles};
inline constexpr std::array<std::uint16_t, 2U> kAdcTriggerEffectiveDelays{
    1U, static_cast<std::uint16_t>(kAdcNominalPhaseIpgCycles + 1U)};
inline constexpr std::uint32_t kAdcCompletionExpectedDwtCycles =
    kClockProfileSpec.phase_dwt_cycles;
inline constexpr std::uint32_t kAdcCompletionToleranceNanoseconds = 200U;
inline constexpr std::uint32_t kAdcPrimaryConversionHalfAdckCycles = 65U;
inline constexpr std::uint32_t kAdcPairPeriodPicoseconds = 1000000U;

constexpr std::uint32_t divideCeil(std::uint64_t numerator,
                                   std::uint64_t denominator) {
  return static_cast<std::uint32_t>(
      (numerator + denominator - 1U) / denominator);
}

constexpr std::uint32_t dwtCyclesForMicroseconds(
    std::uint32_t microseconds) {
  return divideCeil(static_cast<std::uint64_t>(kExpectedDwtHz) *
                        microseconds,
                    1000000U);
}

constexpr std::uint32_t dwtCyclesForNanoseconds(
    std::uint32_t nanoseconds) {
  return divideCeil(static_cast<std::uint64_t>(kExpectedDwtHz) *
                        nanoseconds,
                    1000000000U);
}

inline constexpr std::uint32_t kAdcCompletionToleranceDwtCycles =
    kClockProfileSpec.phase_tolerance_dwt_cycles;
inline constexpr std::uint32_t kAdcPrimaryConversionTimePicoseconds =
    divideCeil(
        static_cast<std::uint64_t>(kAdcPrimaryConversionHalfAdckCycles) *
            1000000000000ULL,
        2ULL * kExpectedAdcClockHz);
inline constexpr std::uint32_t kAdcPrimaryConversionMarginPicoseconds =
    kAdcPairPeriodPicoseconds - kAdcPrimaryConversionTimePicoseconds;
inline constexpr std::uint32_t kGpioClockMaximumMeasurementMicroseconds =
    protocol_v1::kGpioClockMaxElapsedCycles /
    (protocol_v1::kGpioClockDwtHz / 1000000U);
inline constexpr std::uint32_t kGpioClockMaximumMeasurementCycles =
    dwtCyclesForMicroseconds(kGpioClockMaximumMeasurementMicroseconds);
inline constexpr char kExpectedTeensyCoreId[] = "teensy:avr";
inline constexpr char kExpectedTeensyCoreVersion[] = "1.62.0";
inline constexpr std::uint16_t kExpectedTeensyduinoMacro = 160U;
inline constexpr char kExpectedCompilerVersion[] = "15.2.1";
inline constexpr char kUsbMode[] = "USB Serial";
inline constexpr char kOptimization[] = "o2std (-O2)";
inline constexpr SemanticVersion kFirmwareVersion{1U, 0U, 0U};
inline constexpr std::uint8_t kProtocolVersion =
    protocol_v1::kProtocolVersion;
inline constexpr protocol_v1::BoardId kBoardId =
    protocol_v1::BoardId::kTeensy40;
inline constexpr protocol_v1::McuId kMcuId =
    protocol_v1::McuId::kImxrt1062;
inline constexpr std::uint64_t kBuildTimestampEpoch =
    static_cast<std::uint64_t>(THINGDAQ_BUILD_EPOCH);

constexpr bool usbProductNameMatchesIdentity() {
  if (sizeof(kProductName) != kUsbProductNameUtf16.size() + 1U) {
    return false;
  }
  for (std::size_t index = 0U; index < kUsbProductNameUtf16.size(); ++index) {
    if (kUsbProductNameUtf16[index] !=
        static_cast<std::uint8_t>(kProductName[index])) {
      return false;
    }
  }
  return kProductName[kUsbProductNameUtf16.size()] == '\0';
}

constexpr bool isLowerHex(char value) {
  return (value >= '0' && value <= '9') ||
         (value >= 'a' && value <= 'f');
}

constexpr char hexDigit(std::uint8_t value) {
  return static_cast<char>(value < 10U ? '0' + value
                                      : 'a' + value - 10U);
}

constexpr std::array<char, 65U> makeSourceId() {
  constexpr std::uint64_t words[] = {
      THINGDAQ_SOURCE_ID_WORD0,
      THINGDAQ_SOURCE_ID_WORD1,
      THINGDAQ_SOURCE_ID_WORD2,
      THINGDAQ_SOURCE_ID_WORD3,
  };
  std::array<char, 65U> result{};
  std::size_t output = 0U;
  for (std::uint64_t word : words) {
    for (std::uint8_t digit = 0U; digit < 16U; ++digit) {
      const std::uint8_t shift =
          static_cast<std::uint8_t>(60U - digit * 4U);
      result[output++] =
          hexDigit(static_cast<std::uint8_t>((word >> shift) & 0xFU));
    }
  }
  return result;
}

constexpr std::array<char, 26U> makeBuildId(std::uint64_t build_id_word) {
  std::array<char, 26U> result{
      't', 'h', 'i', 'n', 'g', 'd', 'a', 'q', '-',
  };
  for (std::size_t index = 0U; index < 16U; ++index) {
    const std::uint8_t shift = static_cast<std::uint8_t>(60U - index * 4U);
    result[index + 9U] =
        hexDigit(static_cast<std::uint8_t>((build_id_word >> shift) & 0xFU));
  }
  return result;
}

constexpr char decimalDigit(std::uint32_t value) {
  return static_cast<char>('0' + value % 10U);
}

constexpr std::array<char, 21U> makeBuildTimestampUtc() {
  constexpr std::uint32_t year = THINGDAQ_BUILD_YEAR;
  constexpr std::uint32_t month = THINGDAQ_BUILD_MONTH;
  constexpr std::uint32_t day = THINGDAQ_BUILD_DAY;
  constexpr std::uint32_t hour = THINGDAQ_BUILD_HOUR;
  constexpr std::uint32_t minute = THINGDAQ_BUILD_MINUTE;
  constexpr std::uint32_t second = THINGDAQ_BUILD_SECOND;
  return {
      decimalDigit(year / 1000U), decimalDigit(year / 100U),
      decimalDigit(year / 10U),   decimalDigit(year),
      '-',                        decimalDigit(month / 10U),
      decimalDigit(month),        '-',
      decimalDigit(day / 10U),    decimalDigit(day),
      'T',                        decimalDigit(hour / 10U),
      decimalDigit(hour),         ':',
      decimalDigit(minute / 10U), decimalDigit(minute),
      ':',                        decimalDigit(second / 10U),
      decimalDigit(second),       'Z',
      '\0',
  };
}

// kSourceId hashes every firmware input and the protocol source. The helper
// preserves the production source-derived wire ID and supplies a distinct
// source/profile/toolchain-derived ID for the experimental profile.
inline constexpr auto kSourceId = makeSourceId();
inline constexpr auto kBuildId = makeBuildId(THINGDAQ_BUILD_ID_WORD);
inline constexpr auto kBuildTimestampUtc = makeBuildTimestampUtc();

constexpr bool runtimeClocksMatchProfile(std::uint32_t cpu_actual_hz,
                                         std::uint32_t bus_actual_hz) {
  return cpu_actual_hz == kExpectedCpuHz &&
         bus_actual_hz == kExpectedBusHz;
}

constexpr bool runtimeAcquisitionClocksMatchProfile(
    std::uint32_t cpu_actual_hz, std::uint32_t bus_actual_hz,
    std::uint32_t pit_hz, std::uint32_t adc_clock_hz,
    std::uint32_t adc_clock_divider) {
  return runtimeClocksMatchProfile(cpu_actual_hz, bus_actual_hz) &&
         pit_hz == kExpectedPitHz &&
         adc_clock_divider == kExpectedAdcClockDivider &&
         adc_clock_hz == kExpectedAdcClockHz &&
         adc_clock_hz * adc_clock_divider == bus_actual_hz;
}

template <std::size_t N>
constexpr std::size_t stringLength(const std::array<char, N> &) {
  return N - 1U;
}

template <std::size_t N>
constexpr bool isLowerHexString(const std::array<char, N> &value) {
  for (std::size_t index = 0; index + 1U < N; ++index) {
    if (!isLowerHex(value[index])) {
      return false;
    }
  }
  return true;
}

static_assert(kProtocolVersion == 1U);
static_assert(kCpuProfileMhz == 600U || kCpuProfileMhz == 528U);
static_assert(kClockProfileSpec.cpu_hz == kExpectedCpuHz);
static_assert(kClockProfileSpec.ipg_hz == kExpectedIpgHz);
static_assert(kClockProfileSpec.dwt_hz == kExpectedDwtHz);
static_assert(runtimeClocksMatchProfile(kExpectedCpuHz, kExpectedBusHz));
static_assert(runtimeAcquisitionClocksMatchProfile(
    kExpectedCpuHz, kExpectedBusHz, kExpectedPitHz, kExpectedAdcClockHz,
    kExpectedAdcClockDivider));
static_assert(kExpectedDwtHz % kExpectedPitHz == 0U);
static_assert(kExpectedPitHz % kExpectedGpioSampleRateHz == 0U);
static_assert(kExpectedGpioSampleRateHz % kExpectedAdcPairRateHz == 0U);
static_assert(kExpectedIpgHz % kExpectedAdcClockDivider == 0U);
static_assert(kExpectedAdcClockHz <= 40000000U);
static_assert(kExpectedIpgHz % 2000000U == 0U);
static_assert(kExpectedDwtHz % 2000000U == 0U);
static_assert(kAdcTriggerEffectiveDelays[1] -
                      kAdcTriggerEffectiveDelays[0] ==
                  kAdcNominalPhaseIpgCycles);
static_assert(static_cast<std::uint64_t>(kAdcNominalPhaseIpgCycles) *
                      protocol_v1::kTimestampHz ==
                  static_cast<std::uint64_t>(protocol_v1::kAdc1PhaseTicks) *
                      kExpectedIpgHz);
static_assert(static_cast<std::uint64_t>(kAdcNominalPhaseIpgCycles) *
                      kExpectedDwtHz ==
                  static_cast<std::uint64_t>(
                      kAdcCompletionExpectedDwtCycles) *
                      kExpectedIpgHz);
static_assert(kAdcPrimaryConversionTimePicoseconds <
              kAdcPairPeriodPicoseconds);
static_assert(kCpuProfileMhz != 600U ||
              (kExpectedIpgHz == 150000000U &&
               kExpectedAdcClockHz == 37500000U &&
               kAdcNominalPhaseIpgCycles == 75U &&
               kAdcCompletionExpectedDwtCycles == 300U &&
               kAdcCompletionToleranceDwtCycles == 120U &&
               kAdcPrimaryConversionMarginPicoseconds == 133333U));
static_assert(kCpuProfileMhz != 528U ||
              (kExpectedIpgHz == 132000000U &&
               kExpectedAdcClockHz == 33000000U &&
               kAdcNominalPhaseIpgCycles == 66U &&
               kAdcCompletionExpectedDwtCycles == 264U &&
               kAdcCompletionToleranceDwtCycles == 106U &&
               kAdcPrimaryConversionMarginPicoseconds == 15151U));
static_assert(usbProductNameMatchesIdentity(),
              "USB descriptor product must match firmware identity");
static_assert(stringLength(kSourceId) == 64U,
              "source ID must be a full SHA-256");
static_assert(isLowerHexString(kSourceId),
              "source ID must be lowercase hexadecimal");
static_assert(stringLength(kBuildId) > 0U &&
                  stringLength(kBuildId) <
                      protocol_v1::kInfoResponseBuildIdCount,
              "build ID must fit INFO's NUL-terminated 32-byte field");
static_assert(stringLength(kBuildTimestampUtc) == 20U,
              "build timestamp must use YYYY-MM-DDTHH:MM:SSZ");
static_assert(THINGDAQ_BUILD_YEAR >= 1970U &&
                  THINGDAQ_BUILD_YEAR <= 9999U,
              "build timestamp year is outside the supported range");
static_assert(THINGDAQ_BUILD_MONTH >= 1U &&
                  THINGDAQ_BUILD_MONTH <= 12U,
              "build timestamp month is invalid");
static_assert(THINGDAQ_BUILD_DAY >= 1U && THINGDAQ_BUILD_DAY <= 31U,
              "build timestamp day is invalid");
static_assert(THINGDAQ_BUILD_HOUR <= 23U,
              "build timestamp hour is invalid");
static_assert(THINGDAQ_BUILD_MINUTE <= 59U,
              "build timestamp minute is invalid");
static_assert(THINGDAQ_BUILD_SECOND <= 59U,
              "build timestamp second is invalid");
static_assert(kSourceId.back() == '\0');
static_assert(kBuildId.back() == '\0');
static_assert(kBuildTimestampUtc.back() == '\0');

}  // namespace thingdaq::identity
