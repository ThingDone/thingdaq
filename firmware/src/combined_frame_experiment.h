#pragma once

#include <cstddef>
#include <cstdint>

#include "adc_dma_capture.h"

namespace thingdaq::combined_frame_experiment {

inline constexpr std::uint8_t kFrameKind = 3U;
inline constexpr std::uint8_t kNoChecksumAlgorithm = 4U;
inline constexpr std::size_t kHeaderBytes = 44U;
inline constexpr std::size_t kItemCount = 1012U;
inline constexpr std::size_t kFrameBytes8 = kHeaderBytes + kItemCount * 5U;
inline constexpr std::size_t kFrameBytes16 = kHeaderBytes + kItemCount * 6U;

struct Fields {
  std::uint16_t flags = 0U;
  std::uint32_t run_id = 0U;
  std::uint32_t sequence = 0U;
  std::uint64_t first_sample_ticks = 0U;
  std::uint8_t gpio_bytes_per_sample = 1U;
};

bool encode(const Fields &fields, const adc_capture::SamplePair *adc_pairs,
            const std::uint16_t *gpio_samples, std::size_t item_count,
            std::uint8_t *output, std::size_t output_size);

}  // namespace thingdaq::combined_frame_experiment
