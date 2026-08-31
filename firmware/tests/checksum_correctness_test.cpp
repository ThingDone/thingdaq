#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "checksum.h"

namespace {

namespace checksum = thingdaq::checksum;

constexpr std::array<checksum::Algorithm, 3U> kAlgorithms{
    checksum::Algorithm::kAdler32,
    checksum::Algorithm::kCrc32c,
    checksum::Algorithm::kCrc32IsoHdlc,
};
constexpr std::array<std::size_t, 33U> kEdgeLengths{
    0U,   1U,   2U,    3U,    4U,    7U,    8U,    15U,   16U,
    31U,  32U,  33U,   63U,   64U,   65U,   127U,  128U,  129U,
    255U, 256U, 257U,  511U,  512U,  513U,  1023U, 4091U, 4092U,
    4093U, 4096U, 5551U, 5552U, 5553U, 8191U,
};

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

std::uint32_t referenceAdler32(const std::uint8_t *data, std::size_t size) {
  constexpr std::uint32_t modulus = 65521U;
  std::uint32_t first = 1U;
  std::uint32_t second = 0U;
  for (std::size_t index = 0U; index < size; ++index) {
    first = (first + data[index]) % modulus;
    second = (second + first) % modulus;
  }
  return (second << 16U) | first;
}

std::uint32_t referenceReflectedCrc32(const std::uint8_t *data,
                                      std::size_t size,
                                      std::uint32_t polynomial) {
  std::uint32_t remainder = 0xFFFFFFFFU;
  for (std::size_t index = 0U; index < size; ++index) {
    remainder ^= data[index];
    for (std::uint8_t bit = 0U; bit < 8U; ++bit) {
      remainder = (remainder & 1U) != 0U
                      ? (remainder >> 1U) ^ polynomial
                      : remainder >> 1U;
    }
  }
  return remainder ^ 0xFFFFFFFFU;
}

std::uint32_t reference(checksum::Algorithm algorithm,
                        const std::uint8_t *data, std::size_t size) {
  switch (algorithm) {
    case checksum::Algorithm::kAdler32:
      return referenceAdler32(data, size);
    case checksum::Algorithm::kCrc32c:
      return referenceReflectedCrc32(data, size, 0x82F63B78U);
    case checksum::Algorithm::kCrc32IsoHdlc:
      return referenceReflectedCrc32(data, size, 0xEDB88320U);
  }
  return 0U;
}

std::uint32_t candidate(checksum::Algorithm algorithm,
                        const std::uint8_t *data, std::size_t size) {
  std::uint32_t value = 0xA5A5A5A5U;
  expect(checksum::compute(algorithm, data, size, value),
         "candidate dispatch accepts a valid byte view");
  return value;
}

void expectPublishedVector(
    const std::string &input,
    const std::array<std::uint32_t, kAlgorithms.size()> &expected,
    const std::string &name) {
  const auto *data = reinterpret_cast<const std::uint8_t *>(input.data());
  for (std::size_t index = 0U; index < kAlgorithms.size(); ++index) {
    expect(candidate(kAlgorithms[index], data, input.size()) == expected[index],
           name + " published check value");
  }
}

void testPublishedAndCanonicalVectors() {
  // Hard-coded expected values keep this test independent of the table
  // generator and of the Python/zlib implementations.
  expectPublishedVector("", {0x00000001U, 0x00000000U, 0x00000000U},
                        "empty");
  expectPublishedVector("a", {0x00620062U, 0xC1D04330U, 0xE8B7BE43U},
                        "single byte");
  expectPublishedVector("Wikipedia",
                        {0x11E60398U, 0x2D0E3663U, 0xADAAC02EU},
                        "Wikipedia");
  expectPublishedVector("123456789",
                        {0x091E01DEU, 0xE3069283U, 0xCBF43926U},
                        "123456789");
  expectPublishedVector(
      "The quick brown fox jumps over the lazy dog",
      {0x5BDC0FDAU, 0x22620404U, 0x414FA339U}, "quick-brown-fox");

  for (const checksum::Algorithm algorithm : kAlgorithms) {
    expect(candidate(algorithm, nullptr, 0U) == reference(algorithm, nullptr, 0U),
           "null empty view agrees with the independent reference");
  }
}

void testDeterministicAlignmentAndLengthEdges() {
  std::array<std::uint8_t, 8191U + 32U> storage{};
  std::uint32_t state = 0xC001D00DU;
  for (std::uint8_t &value : storage) {
    state ^= state << 13U;
    state ^= state >> 17U;
    state ^= state << 5U;
    value = static_cast<std::uint8_t>(state & 0xFFU);
  }

  for (std::size_t alignment = 0U; alignment < 32U; ++alignment) {
    const std::uint8_t *data = storage.data() + alignment;
    for (const std::size_t length : kEdgeLengths) {
      if (alignment + length > storage.size()) {
        continue;
      }
      for (const checksum::Algorithm algorithm : kAlgorithms) {
        expect(candidate(algorithm, data, length) ==
                   reference(algorithm, data, length),
               "candidate agrees at every deterministic alignment/length edge");
      }
    }
  }
}

bool readU32(std::istream &input, std::uint32_t &value) {
  std::array<unsigned char, 4U> bytes{};
  input.read(reinterpret_cast<char *>(bytes.data()),
             static_cast<std::streamsize>(bytes.size()));
  if (!input) {
    return false;
  }
  value = static_cast<std::uint32_t>(bytes[0]) |
          (static_cast<std::uint32_t>(bytes[1]) << 8U) |
          (static_cast<std::uint32_t>(bytes[2]) << 16U) |
          (static_cast<std::uint32_t>(bytes[3]) << 24U);
  return true;
}

bool writeU32(std::ostream &output, std::uint32_t value) {
  const std::array<unsigned char, 4U> bytes{
      static_cast<unsigned char>(value & 0xFFU),
      static_cast<unsigned char>((value >> 8U) & 0xFFU),
      static_cast<unsigned char>((value >> 16U) & 0xFFU),
      static_cast<unsigned char>((value >> 24U) & 0xFFU),
  };
  output.write(reinterpret_cast<const char *>(bytes.data()),
               static_cast<std::streamsize>(bytes.size()));
  return static_cast<bool>(output);
}

bool emitCorpusChecksums(const std::string &input_path,
                         const std::string &output_path) {
  std::ifstream input(input_path, std::ios::binary);
  std::ofstream output(output_path, std::ios::binary | std::ios::trunc);
  std::uint32_t count = 0U;
  if (!input || !output || !readU32(input, count) || count > 4096U) {
    return false;
  }
  for (std::uint32_t item = 0U; item < count; ++item) {
    std::uint32_t length = 0U;
    if (!readU32(input, length) || length > 1024U * 1024U) {
      return false;
    }
    std::vector<std::uint8_t> data(length);
    if (length != 0U) {
      input.read(reinterpret_cast<char *>(data.data()),
                 static_cast<std::streamsize>(length));
      if (!input) {
        return false;
      }
    }
    for (const checksum::Algorithm algorithm : kAlgorithms) {
      if (!writeU32(output, candidate(algorithm, data.data(), data.size()))) {
        return false;
      }
    }
  }
  return input.peek() == std::char_traits<char>::eof() &&
         static_cast<bool>(output);
}

}  // namespace

int main(int argc, char **argv) {
  testPublishedAndCanonicalVectors();
  testDeterministicAlignmentAndLengthEdges();
  if (failures != 0) {
    std::cerr << failures << " checksum correctness assertion(s) failed\n";
    return 1;
  }
  if (argc == 1) {
    std::cout << "independent checksum correctness tests passed\n";
    return 0;
  }
  if (argc == 3 && emitCorpusChecksums(argv[1], argv[2])) {
    return failures == 0 ? 0 : 1;
  }
  std::cerr << "usage: checksum-correctness-test [CORPUS OUTPUT]\n";
  return 2;
}
