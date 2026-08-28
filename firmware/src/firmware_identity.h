#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "generated/protocol_constants.h"

// The repository build helper supplies numeric provenance macros. Numeric
// values survive both Arduino's sketch-discovery preprocessor and its normal
// compiler recipe without tool-specific string-quote behavior.
#if defined(ARDUINO) && !defined(TEENSY_DAQ_SOURCE_ID_WORD0)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(TEENSY_DAQ_SOURCE_ID_WORD1)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(TEENSY_DAQ_SOURCE_ID_WORD2)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(TEENSY_DAQ_SOURCE_ID_WORD3)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) && !defined(TEENSY_DAQ_BUILD_EPOCH)
#error "build firmware with firmware/tools/build_firmware.py"
#endif
#if defined(ARDUINO) &&                                                \
    (!defined(TEENSY_DAQ_BUILD_YEAR) ||                               \
     !defined(TEENSY_DAQ_BUILD_MONTH) ||                              \
     !defined(TEENSY_DAQ_BUILD_DAY) ||                                \
     !defined(TEENSY_DAQ_BUILD_HOUR) ||                               \
     !defined(TEENSY_DAQ_BUILD_MINUTE) ||                             \
     !defined(TEENSY_DAQ_BUILD_SECOND))
#error "build firmware with firmware/tools/build_firmware.py"
#endif

#ifndef TEENSY_DAQ_SOURCE_ID_WORD0
#define TEENSY_DAQ_SOURCE_ID_WORD0 0ULL
#endif
#ifndef TEENSY_DAQ_SOURCE_ID_WORD1
#define TEENSY_DAQ_SOURCE_ID_WORD1 0ULL
#endif
#ifndef TEENSY_DAQ_SOURCE_ID_WORD2
#define TEENSY_DAQ_SOURCE_ID_WORD2 0ULL
#endif
#ifndef TEENSY_DAQ_SOURCE_ID_WORD3
#define TEENSY_DAQ_SOURCE_ID_WORD3 0ULL
#endif
#ifndef TEENSY_DAQ_BUILD_EPOCH
#define TEENSY_DAQ_BUILD_EPOCH 0ULL
#endif
#ifndef TEENSY_DAQ_BUILD_YEAR
#define TEENSY_DAQ_BUILD_YEAR 1970U
#endif
#ifndef TEENSY_DAQ_BUILD_MONTH
#define TEENSY_DAQ_BUILD_MONTH 1U
#endif
#ifndef TEENSY_DAQ_BUILD_DAY
#define TEENSY_DAQ_BUILD_DAY 1U
#endif
#ifndef TEENSY_DAQ_BUILD_HOUR
#define TEENSY_DAQ_BUILD_HOUR 0U
#endif
#ifndef TEENSY_DAQ_BUILD_MINUTE
#define TEENSY_DAQ_BUILD_MINUTE 0U
#endif
#ifndef TEENSY_DAQ_BUILD_SECOND
#define TEENSY_DAQ_BUILD_SECOND 0U
#endif

// Fail closed when an Arduino build bypasses the exact Teensy 4.0 target. The
// core version and optimization menu are also checked by build_firmware.py;
// these preprocessor checks prevent a copied sketch from silently degrading.
#if defined(ARDUINO)
#if !defined(ARDUINO_TEENSY40)
#error "Teensy DAQ supports only ARDUINO_TEENSY40"
#endif
#if !defined(__IMXRT1062__)
#error "Teensy DAQ requires the i.MX RT1062"
#endif
#if !defined(F_CPU) || F_CPU != 600000000
#error "Teensy DAQ requires the 600 MHz CPU menu option"
#endif
#if !defined(USB_SERIAL)
#error "Teensy DAQ requires the USB Serial menu option"
#endif
#if !defined(TEENSYDUINO) || TEENSYDUINO != 160
#error "unexpected Teensy core compile identity"
#endif
#if __cplusplus < 201703L
#error "Teensy DAQ requires the pinned core's GNU C++17 mode"
#endif
#if !defined(TEENSY_DAQ_OPTIMIZATION_O2STD) || \
    TEENSY_DAQ_OPTIMIZATION_O2STD != 1
#error "Teensy DAQ requires the validated standard -O2 build"
#endif
#if __GNUC__ != 15 || __GNUC_MINOR__ != 2
#error "Teensy DAQ requires Arm GNU 15.2.1"
#endif
#endif

namespace teensy_daq::identity {

struct SemanticVersion {
  std::uint8_t major;
  std::uint8_t minor;
  std::uint8_t patch;
};

inline constexpr char kProductName[] = "Teensy DAQ";
inline constexpr std::array<std::uint16_t, 10U> kUsbProductNameUtf16{
    'T', 'e', 'e', 'n', 's', 'y', ' ', 'D', 'A', 'Q',
};
inline constexpr char kBoardName[] = "Teensy 4.0";
inline constexpr char kMcuName[] = "NXP i.MX RT1062";
inline constexpr char kCpuArchitecture[] = "Arm Cortex-M7";
inline constexpr std::uint32_t kExpectedCpuHz = 600000000U;
inline constexpr char kExpectedTeensyCoreId[] = "teensy:avr";
inline constexpr char kExpectedTeensyCoreVersion[] = "1.62.0";
inline constexpr std::uint16_t kExpectedTeensyduinoMacro = 160U;
inline constexpr char kExpectedCompilerVersion[] = "15.2.1";
inline constexpr char kUsbMode[] = "USB Serial";
inline constexpr char kOptimization[] = "o2std (-O2)";
inline constexpr SemanticVersion kFirmwareVersion{0U, 3U, 0U};
inline constexpr std::uint8_t kProtocolVersion =
    protocol_v1::kProtocolVersion;
inline constexpr protocol_v1::BoardId kBoardId =
    protocol_v1::BoardId::kTeensy40;
inline constexpr protocol_v1::McuId kMcuId =
    protocol_v1::McuId::kImxrt1062;
inline constexpr std::uint64_t kBuildTimestampEpoch =
    static_cast<std::uint64_t>(TEENSY_DAQ_BUILD_EPOCH);

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
      TEENSY_DAQ_SOURCE_ID_WORD0,
      TEENSY_DAQ_SOURCE_ID_WORD1,
      TEENSY_DAQ_SOURCE_ID_WORD2,
      TEENSY_DAQ_SOURCE_ID_WORD3,
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

constexpr std::array<char, 22U> makeBuildId(
    const std::array<char, 65U> &source_id) {
  std::array<char, 22U> result{'t', 'd', 'a', 'q', '-'};
  for (std::size_t index = 0U; index < 16U; ++index) {
    result[index + 5U] = source_id[index];
  }
  return result;
}

constexpr char decimalDigit(std::uint32_t value) {
  return static_cast<char>('0' + value % 10U);
}

constexpr std::array<char, 21U> makeBuildTimestampUtc() {
  constexpr std::uint32_t year = TEENSY_DAQ_BUILD_YEAR;
  constexpr std::uint32_t month = TEENSY_DAQ_BUILD_MONTH;
  constexpr std::uint32_t day = TEENSY_DAQ_BUILD_DAY;
  constexpr std::uint32_t hour = TEENSY_DAQ_BUILD_HOUR;
  constexpr std::uint32_t minute = TEENSY_DAQ_BUILD_MINUTE;
  constexpr std::uint32_t second = TEENSY_DAQ_BUILD_SECOND;
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

// kSourceId hashes every firmware input and the protocol source. kBuildId is
// the bounded wire identity derived from its first 16 hexadecimal digits.
inline constexpr auto kSourceId = makeSourceId();
inline constexpr auto kBuildId = makeBuildId(kSourceId);
inline constexpr auto kBuildTimestampUtc = makeBuildTimestampUtc();

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
static_assert(TEENSY_DAQ_BUILD_YEAR >= 1970U &&
                  TEENSY_DAQ_BUILD_YEAR <= 9999U,
              "build timestamp year is outside the supported range");
static_assert(TEENSY_DAQ_BUILD_MONTH >= 1U &&
                  TEENSY_DAQ_BUILD_MONTH <= 12U,
              "build timestamp month is invalid");
static_assert(TEENSY_DAQ_BUILD_DAY >= 1U && TEENSY_DAQ_BUILD_DAY <= 31U,
              "build timestamp day is invalid");
static_assert(TEENSY_DAQ_BUILD_HOUR <= 23U,
              "build timestamp hour is invalid");
static_assert(TEENSY_DAQ_BUILD_MINUTE <= 59U,
              "build timestamp minute is invalid");
static_assert(TEENSY_DAQ_BUILD_SECOND <= 59U,
              "build timestamp second is invalid");
static_assert(kSourceId.back() == '\0');
static_assert(kBuildId.back() == '\0');
static_assert(kBuildTimestampUtc.back() == '\0');

}  // namespace teensy_daq::identity
