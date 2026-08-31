#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "checksum.h"

namespace {

namespace candidate = thingdaq::checksum;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

std::uint32_t referenceReflectedCrc(const std::uint8_t *data,
                                    std::size_t size,
                                    std::uint32_t reflected_polynomial) {
  std::uint32_t remainder = 0xFFFFFFFFU;
  for (std::size_t offset = 0U; offset < size; ++offset) {
    remainder ^= data[offset];
    for (std::uint8_t bit = 0U; bit < 8U; ++bit) {
      remainder = (remainder & 1U) != 0U
                      ? (remainder >> 1U) ^ reflected_polynomial
                      : remainder >> 1U;
    }
  }
  return remainder ^ 0xFFFFFFFFU;
}

void testParametersAndCanonicalVectors() {
  static_assert(candidate::kAdler32Initial == 1U);
  static_assert(candidate::kAdler32Modulus == 65521U);
  static_assert(candidate::kCrc32cPolynomial == 0x1EDC6F41U);
  static_assert(candidate::kCrc32cReflectedPolynomial == 0x82F63B78U);
  static_assert(candidate::kCrc32IsoHdlcPolynomial == 0x04C11DB7U);
  static_assert(candidate::kCrc32IsoHdlcReflectedPolynomial ==
                0xEDB88320U);
  static_assert(candidate::kCrc32Initial == 0xFFFFFFFFU);
  static_assert(candidate::kCrc32FinalXor == 0xFFFFFFFFU);
  static_assert(candidate::kCrcTableSlices == 8U);
  static_assert(candidate::kCrcTableBytes == 8192U);
  static_assert(candidate::tableBytes(candidate::Algorithm::kAdler32) == 0U);
  static_assert(candidate::tableBytes(candidate::Algorithm::kCrc32c) ==
                8192U);
  static_assert(
      candidate::tableBytes(candidate::Algorithm::kCrc32IsoHdlc) == 8192U);

  expect(candidate::adler32(nullptr, 0U) == 0x00000001U,
         "empty Adler-32");
  expect(candidate::crc32c(nullptr, 0U) == 0x00000000U,
         "empty CRC-32C");
  expect(candidate::crc32IsoHdlc(nullptr, 0U) == 0x00000000U,
         "empty CRC-32/ISO-HDLC");

  constexpr std::array<std::uint8_t, 9U> digits{
      '1', '2', '3', '4', '5', '6', '7', '8', '9'};
  expect(candidate::adler32(digits.data(), digits.size()) == 0x091E01DEU,
         "123456789 Adler-32");
  expect(candidate::crc32c(digits.data(), digits.size()) == 0xE3069283U,
         "123456789 CRC-32C");
  expect(candidate::crc32IsoHdlc(digits.data(), digits.size()) ==
             0xCBF43926U,
         "123456789 CRC-32/ISO-HDLC");
}

void testTablesAgainstIndependentBitwiseReferences() {
  std::array<std::uint8_t, 4101U> storage{};
  for (std::size_t index = 0U; index < storage.size(); ++index) {
    storage[index] =
        static_cast<std::uint8_t>((index * 73U + index / 7U + 19U) & 0xFFU);
  }

  constexpr std::array<std::size_t, 8U> lengths{
      1U, 2U, 3U, 7U, 64U, 512U, 4092U, 4096U};
  for (std::size_t alignment = 0U; alignment < 4U; ++alignment) {
    for (const std::size_t length : lengths) {
      if (alignment + length > storage.size()) {
        continue;
      }
      const std::uint8_t *input = storage.data() + alignment;
      expect(candidate::crc32c(input, length) ==
                 referenceReflectedCrc(
                     input, length, candidate::kCrc32cReflectedPolynomial),
             "CRC-32C table/reference agreement");
      expect(candidate::crc32IsoHdlc(input, length) ==
                 referenceReflectedCrc(
                     input, length,
                     candidate::kCrc32IsoHdlcReflectedPolynomial),
             "CRC-32/ISO-HDLC table/reference agreement");
    }
  }
}

void testNarrowDispatch() {
  constexpr std::array<std::uint8_t, 3U> input{0x10U, 0x20U, 0x30U};
  std::uint32_t result = 0xA5A5A5A5U;
  expect(candidate::compute(candidate::Algorithm::kAdler32, input.data(),
                            input.size(), result) &&
             result == candidate::adler32(input.data(), input.size()),
         "Adler-32 dispatch");
  expect(candidate::compute(candidate::Algorithm::kCrc32c, input.data(),
                            input.size(), result) &&
             result == candidate::crc32c(input.data(), input.size()),
         "CRC-32C dispatch");
  expect(candidate::compute(candidate::Algorithm::kCrc32IsoHdlc, input.data(),
                            input.size(), result) &&
             result == candidate::crc32IsoHdlc(input.data(), input.size()),
         "CRC-32/ISO-HDLC dispatch");

  result = 0xA5A5A5A5U;
  expect(!candidate::compute(candidate::Algorithm::kCrc32c, nullptr, 1U,
                             result) &&
             result == 0xA5A5A5A5U,
         "dispatch rejects invalid nonempty view without changing output");
}

}  // namespace

int main() {
  testParametersAndCanonicalVectors();
  testTablesAgainstIndependentBitwiseReferences();
  testNarrowDispatch();
  if (failures == 0) {
    std::cout << "checksum candidate tests passed\n";
  }
  return failures == 0 ? 0 : 1;
}
