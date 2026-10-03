#pragma once

#include <cstddef>
#include <cstdint>

#include "adc_dma_capture.h"

namespace thingdaq::adc_packing {

inline constexpr std::uint8_t kContainerBits = 16U;
inline constexpr std::uint8_t kPacked12Bits = 12U;
inline constexpr std::uint8_t kPacked10Bits = 10U;

constexpr std::size_t packedBytes(std::size_t pair_count,
                                  std::uint8_t bits_per_sample) {
  const std::size_t total_bits = pair_count * 2U * bits_per_sample;
  return total_bits % 8U == 0U ? total_bits / 8U : 0U;
}

bool copy16BitContainers(std::uint8_t *destination,
                         std::size_t destination_size,
                         const adc_capture::SamplePair *pairs,
                         std::size_t pair_count);
bool pack12BitPairs(std::uint8_t *destination, std::size_t destination_size,
                    const adc_capture::SamplePair *pairs,
                    std::size_t pair_count);
bool unpack12BitPairs(adc_capture::SamplePair *pairs, std::size_t pair_count,
                      const std::uint8_t *source, std::size_t source_size);
bool pack10BitPairs(std::uint8_t *destination, std::size_t destination_size,
                    const adc_capture::SamplePair *pairs,
                    std::size_t pair_count);
bool unpack10BitPairs(adc_capture::SamplePair *pairs, std::size_t pair_count,
                      const std::uint8_t *source, std::size_t source_size);

}  // namespace thingdaq::adc_packing
