#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>

#include "combined_frame_experiment.h"

namespace experiment = thingdaq::combined_frame_experiment;
namespace capture = thingdaq::adc_capture;

template <std::size_t FrameBytes>
bool writeFrame(const char *path, std::uint8_t gpio_bytes) {
  std::array<capture::SamplePair, experiment::kItemCount> adc{};
  std::array<std::uint16_t, experiment::kItemCount> gpio{};
  std::array<std::uint8_t, FrameBytes> wire{};
  for (std::size_t index = 0U; index < adc.size(); ++index) {
    adc[index].adc0 = static_cast<std::uint16_t>((index * 3U + 1U) & 0xFFFU);
    adc[index].adc1 = static_cast<std::uint16_t>((index * 5U + 2U) & 0xFFFU);
    gpio[index] = static_cast<std::uint16_t>(
        gpio_bytes == 1U ? (index ^ 0xA5U) & 0xFFU
                         : (index * 257U + 0x1234U) & 0xFFFFU);
  }
  experiment::Fields fields{};
  fields.flags = 0x0004U;
  fields.run_id = 7U;
  fields.sequence = 11U;
  fields.first_sample_ticks = 123456U;
  fields.gpio_bytes_per_sample = gpio_bytes;
  if (!experiment::encode(fields, adc.data(), gpio.data(), adc.size(),
                          wire.data(), wire.size())) {
    return false;
  }
  std::ofstream output(path, std::ios::binary);
  output.write(reinterpret_cast<const char *>(wire.data()), wire.size());
  return output.good();
}

int main(int argc, char **argv) {
  if (argc != 3) return 2;
  return writeFrame<experiment::kFrameBytes8>(argv[1], 1U) &&
                 writeFrame<experiment::kFrameBytes16>(argv[2], 2U)
             ? 0
             : 1;
}
