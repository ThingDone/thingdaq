#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "adc_sample_packing.h"

namespace {

namespace capture = thingdaq::adc_capture;
namespace packing = thingdaq::adc_packing;
int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

std::uint16_t sampleAt(const capture::SamplePair *pairs,
                       std::size_t position) {
  return position % 2U == 0U ? pairs[position / 2U].adc0
                             : pairs[position / 2U].adc1;
}

void setSample(capture::SamplePair *pairs, std::size_t position,
               std::uint16_t value) {
  if (position % 2U == 0U) {
    pairs[position / 2U].adc0 = value;
  } else {
    pairs[position / 2U].adc1 = value;
  }
}

template <std::size_t Size>
std::array<std::uint8_t, Size> referencePack(
    const capture::SamplePair *pairs, std::size_t pair_count,
    std::uint8_t bits_per_sample) {
  std::array<std::uint8_t, Size> output{};
  std::size_t bit_offset = 0U;
  for (std::size_t position = 0U; position < pair_count * 2U; ++position) {
    std::uint16_t value = sampleAt(pairs, position);
    if (bits_per_sample == 10U) value >>= 2U;
    for (std::uint8_t bit = 0U; bit < bits_per_sample; ++bit) {
      if ((value & (1U << bit)) != 0U) {
        output[bit_offset / 8U] = static_cast<std::uint8_t>(
            output[bit_offset / 8U] | (1U << (bit_offset % 8U)));
      }
      ++bit_offset;
    }
  }
  return output;
}

void testSizesAndKnownVectors() {
  static_assert(packing::packedBytes(1012U, 16U) == 4048U);
  static_assert(packing::packedBytes(1012U, 12U) == 3036U);
  static_assert(packing::packedBytes(1012U, 10U) == 2530U);
  std::array<capture::SamplePair, 4U> pairs{{
      {0x0ABCU, 0x0123U}, {0x0000U, 0x0FFFU},
      {0x0001U, 0x0555U}, {0x0AAAU, 0x0800U}}};
  std::array<std::uint8_t, 12U> packed12{};
  expect(packing::pack12BitPairs(packed12.data(), packed12.size(), pairs.data(),
                                 pairs.size()),
         "12-bit known vector packs");
  expect(packed12[0] == 0xBCU && packed12[1] == 0x3AU &&
             packed12[2] == 0x12U,
         "12-bit pair uses the documented little-endian bitstream");
  std::array<std::uint8_t, 10U> packed10{};
  expect(packing::pack10BitPairs(packed10.data(), packed10.size(), pairs.data(),
                                 pairs.size()),
         "10-bit known vector packs");
}

void testRoundTripsEveryCodeAndPosition() {
  std::array<capture::SamplePair, 4U> source{};
  std::array<capture::SamplePair, 4U> decoded{};
  std::array<std::uint8_t, 12U> packed12{};
  std::array<std::uint8_t, 10U> packed10{};
  for (std::size_t position = 0U; position < 8U; ++position) {
    for (std::uint16_t code = 0U; code <= 0x0FFFU; ++code) {
      source = {};
      setSample(source.data(), position, code);
      expect(packing::pack12BitPairs(packed12.data(), packed12.size(),
                                     source.data(), source.size()) &&
                 packing::unpack12BitPairs(decoded.data(), decoded.size(),
                                           packed12.data(), packed12.size()),
             "12-bit exhaustive round trip executes");
      expect(packed12 == referencePack<12U>(source.data(), source.size(), 12U),
             "12-bit output matches independent bit writer");
      expect(sampleAt(decoded.data(), position) == code,
             "12-bit exhaustive round trip is lossless");
      expect(packing::pack10BitPairs(packed10.data(), packed10.size(),
                                     source.data(), source.size()) &&
                 packing::unpack10BitPairs(decoded.data(), decoded.size(),
                                           packed10.data(), packed10.size()),
             "10-bit exhaustive round trip executes");
      expect(packed10 == referencePack<10U>(source.data(), source.size(), 10U),
             "10-bit output matches independent bit writer");
      expect(sampleAt(decoded.data(), position) == (code >> 2U),
             "10-bit round trip returns the truncated code");
    }
  }
}

void testBoundsAndInvalidCodes() {
  std::array<capture::SamplePair, 4U> pairs{};
  std::array<std::uint8_t, 16U> output{};
  expect(!packing::pack12BitPairs(output.data(), 11U, pairs.data(), pairs.size()),
         "12-bit wrong output size is rejected");
  expect(!packing::pack10BitPairs(output.data(), 9U, pairs.data(), pairs.size()),
         "10-bit wrong output size is rejected");
  pairs[2].adc1 = 0x1000U;
  expect(!packing::pack12BitPairs(output.data(), 12U, pairs.data(), pairs.size()) &&
             !packing::pack10BitPairs(output.data(), 10U, pairs.data(), pairs.size()),
         "out-of-range ADC input is rejected instead of silently masked");
}

}  // namespace

int main() {
  testSizesAndKnownVectors();
  testRoundTripsEveryCodeAndPosition();
  testBoundsAndInvalidCodes();
  if (failures == 0) std::cout << "ADC sample packing tests passed\n";
  return failures == 0 ? 0 : 1;
}
