#include "adc_sample_packing.h"

#include <cstring>

#if defined(__IMXRT1062__)
#define THINGDAQ_ADC_PACKING_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_ADC_PACKING_CODE(section_name) __attribute__((noinline))
#endif

namespace thingdaq::adc_packing {
namespace {

bool valid(const std::uint8_t *bytes, std::size_t byte_count,
           const adc_capture::SamplePair *pairs, std::size_t pair_count,
           std::uint8_t bits_per_sample) {
  return bytes != nullptr && pairs != nullptr && pair_count != 0U &&
         packedBytes(pair_count, bits_per_sample) == byte_count;
}

bool validCodes(const adc_capture::SamplePair *pairs, std::size_t pair_count) {
  for (std::size_t index = 0U; index < pair_count; ++index) {
    if (((pairs[index].adc0 | pairs[index].adc1) & 0xF000U) != 0U) return false;
  }
  return true;
}

}  // namespace

THINGDAQ_ADC_PACKING_CODE(".flashmem.adc_packing.copy16")
bool copy16BitContainers(std::uint8_t *destination,
                         std::size_t destination_size,
                         const adc_capture::SamplePair *pairs,
                         std::size_t pair_count) {
  if (!valid(destination, destination_size, pairs, pair_count, kContainerBits) ||
      !validCodes(pairs, pair_count)) {
    return false;
  }
  std::memcpy(destination, pairs, destination_size);
  return true;
}

THINGDAQ_ADC_PACKING_CODE(".flashmem.adc_packing.pack12")
bool pack12BitPairs(std::uint8_t *destination, std::size_t destination_size,
                    const adc_capture::SamplePair *pairs,
                    std::size_t pair_count) {
  if (pair_count % 4U != 0U ||
      !valid(destination, destination_size, pairs, pair_count, kPacked12Bits) ||
      !validCodes(pairs, pair_count)) {
    return false;
  }
  for (std::size_t index = 0U; index < pair_count; index += 4U) {
    const std::uint32_t v0 = pairs[index].adc0;
    const std::uint32_t v1 = pairs[index].adc1;
    const std::uint32_t v2 = pairs[index + 1U].adc0;
    const std::uint32_t v3 = pairs[index + 1U].adc1;
    const std::uint32_t v4 = pairs[index + 2U].adc0;
    const std::uint32_t v5 = pairs[index + 2U].adc1;
    const std::uint32_t v6 = pairs[index + 3U].adc0;
    const std::uint32_t v7 = pairs[index + 3U].adc1;
    const std::uint32_t words[3] = {
        v0 | (v1 << 12U) | (v2 << 24U),
        (v2 >> 8U) | (v3 << 4U) | (v4 << 16U) | (v5 << 28U),
        (v5 >> 4U) | (v6 << 8U) | (v7 << 20U),
    };
    std::memcpy(destination + index * 3U, words, sizeof(words));
  }
  return true;
}

THINGDAQ_ADC_PACKING_CODE(".flashmem.adc_packing.unpack12")
bool unpack12BitPairs(adc_capture::SamplePair *pairs, std::size_t pair_count,
                      const std::uint8_t *source, std::size_t source_size) {
  if (pairs == nullptr || source == nullptr || pair_count == 0U ||
      source_size != packedBytes(pair_count, kPacked12Bits)) {
    return false;
  }
  for (std::size_t index = 0U; index < pair_count; ++index) {
    const std::size_t offset = index * 3U;
    pairs[index].adc0 = static_cast<std::uint16_t>(
        source[offset] | (static_cast<std::uint16_t>(source[offset + 1U]) << 8U)) &
        0x0FFFU;
    pairs[index].adc1 = static_cast<std::uint16_t>(
        (static_cast<std::uint16_t>(source[offset + 1U]) >> 4U) |
        (static_cast<std::uint16_t>(source[offset + 2U]) << 4U));
  }
  return true;
}

THINGDAQ_ADC_PACKING_CODE(".flashmem.adc_packing.pack10")
bool pack10BitPairs(std::uint8_t *destination, std::size_t destination_size,
                    const adc_capture::SamplePair *pairs,
                    std::size_t pair_count) {
  if (pair_count % 2U != 0U ||
      !valid(destination, destination_size, pairs, pair_count, kPacked10Bits) ||
      !validCodes(pairs, pair_count)) {
    return false;
  }
  for (std::size_t index = 0U; index < pair_count; index += 2U) {
    const std::uint16_t v0 = pairs[index].adc0 >> 2U;
    const std::uint16_t v1 = pairs[index].adc1 >> 2U;
    const std::uint16_t v2 = pairs[index + 1U].adc0 >> 2U;
    const std::uint16_t v3 = pairs[index + 1U].adc1 >> 2U;
    const std::size_t output = index * 5U / 2U;
    destination[output] = static_cast<std::uint8_t>(v0);
    destination[output + 1U] =
        static_cast<std::uint8_t>((v0 >> 8U) | (v1 << 2U));
    destination[output + 2U] =
        static_cast<std::uint8_t>((v1 >> 6U) | (v2 << 4U));
    destination[output + 3U] =
        static_cast<std::uint8_t>((v2 >> 4U) | (v3 << 6U));
    destination[output + 4U] = static_cast<std::uint8_t>(v3 >> 2U);
  }
  return true;
}

THINGDAQ_ADC_PACKING_CODE(".flashmem.adc_packing.unpack10")
bool unpack10BitPairs(adc_capture::SamplePair *pairs, std::size_t pair_count,
                      const std::uint8_t *source, std::size_t source_size) {
  if (pairs == nullptr || source == nullptr || pair_count == 0U ||
      pair_count % 2U != 0U ||
      source_size != packedBytes(pair_count, kPacked10Bits)) {
    return false;
  }
  for (std::size_t index = 0U; index < pair_count; index += 2U) {
    const std::size_t input = index * 5U / 2U;
    pairs[index].adc0 = static_cast<std::uint16_t>(
        source[input] | ((source[input + 1U] & 0x03U) << 8U));
    pairs[index].adc1 = static_cast<std::uint16_t>(
        (source[input + 1U] >> 2U) | ((source[input + 2U] & 0x0FU) << 6U));
    pairs[index + 1U].adc0 = static_cast<std::uint16_t>(
        (source[input + 2U] >> 4U) | ((source[input + 3U] & 0x3FU) << 4U));
    pairs[index + 1U].adc1 = static_cast<std::uint16_t>(
        (source[input + 3U] >> 6U) | (source[input + 4U] << 2U));
  }
  return true;
}

}  // namespace thingdaq::adc_packing

#undef THINGDAQ_ADC_PACKING_CODE
