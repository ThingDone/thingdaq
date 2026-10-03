#include "combined_frame_experiment.h"

namespace thingdaq::combined_frame_experiment {
namespace {

void store16(std::uint8_t *output, std::size_t offset, std::uint16_t value) {
  output[offset] = static_cast<std::uint8_t>(value);
  output[offset + 1U] = static_cast<std::uint8_t>(value >> 8U);
}

void store32(std::uint8_t *output, std::size_t offset, std::uint32_t value) {
  for (std::size_t byte = 0U; byte < 4U; ++byte) {
    output[offset + byte] = static_cast<std::uint8_t>(value >> (byte * 8U));
  }
}

void store64(std::uint8_t *output, std::size_t offset, std::uint64_t value) {
  for (std::size_t byte = 0U; byte < 8U; ++byte) {
    output[offset + byte] = static_cast<std::uint8_t>(value >> (byte * 8U));
  }
}

}  // namespace

bool encode(const Fields &fields, const adc_capture::SamplePair *adc_pairs,
            const std::uint16_t *gpio_samples, std::size_t item_count,
            std::uint8_t *output, std::size_t output_size) {
  const std::size_t item_bytes = 4U + fields.gpio_bytes_per_sample;
  const std::size_t expected_size = kHeaderBytes + item_count * item_bytes;
  if (fields.run_id == 0U ||
      (fields.gpio_bytes_per_sample != 1U &&
       fields.gpio_bytes_per_sample != 2U) ||
      item_count != kItemCount || adc_pairs == nullptr ||
      gpio_samples == nullptr || output == nullptr ||
      output_size != expected_size ||
      (fields.flags & static_cast<std::uint16_t>(~0x000FU)) != 0U) {
    return false;
  }

  store32(output, 0U, 0xDEADBEEFU);
  output[4] = 2U;
  output[5] = kFrameKind;
  store16(output, 6U, fields.flags);
  store16(output, 8U, static_cast<std::uint16_t>(kHeaderBytes));
  output[10] = kNoChecksumAlgorithm;
  output[11] = 0U;
  store32(output, 12U, static_cast<std::uint32_t>(expected_size));
  store32(output, 16U,
          static_cast<std::uint32_t>(expected_size - kHeaderBytes));
  store32(output, 20U, fields.run_id);
  store32(output, 24U, fields.sequence);
  store32(output, 28U, 0U);
  store64(output, 32U, fields.first_sample_ticks);
  store32(output, 40U, static_cast<std::uint32_t>(item_count));

  for (std::size_t index = 0U; index < item_count; ++index) {
    if (((adc_pairs[index].adc0 | adc_pairs[index].adc1) & 0xF000U) != 0U ||
        (fields.gpio_bytes_per_sample == 1U && gpio_samples[index] > 0xFFU)) {
      return false;
    }
    const std::size_t offset = kHeaderBytes + index * item_bytes;
    store16(output, offset, adc_pairs[index].adc0);
    store16(output, offset + 2U, adc_pairs[index].adc1);
    output[offset + 4U] = static_cast<std::uint8_t>(gpio_samples[index]);
    if (fields.gpio_bytes_per_sample == 2U) {
      output[offset + 5U] =
          static_cast<std::uint8_t>(gpio_samples[index] >> 8U);
    }
  }
  return true;
}

}  // namespace thingdaq::combined_frame_experiment
