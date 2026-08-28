#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>

#include "gpio_batch_packer.h"

namespace {

namespace constants = teensy_daq::protocol_v1;
namespace packer = teensy_daq::gpio_packer;

constexpr std::uint32_t rawWord(std::uint8_t packed) {
  std::uint32_t word = 0U;
  for (std::size_t bit = 0U; bit < 8U; ++bit) {
    if ((packed & (std::uint8_t{1U} << bit)) != 0U) {
      word |= std::uint32_t{1U}
              << teensy_daq::board::kGpioMappingsByPackedBit[bit].gpio2_bit;
    }
  }
  return word;
}

void exposePackedBytes(const std::uint8_t *bytes) {
  // The benchmark is compiled with LTO. Make every completed destination
  // buffer observable so interprocedural dead-store elimination cannot turn
  // the measured full-batch pack into a single-byte calculation.
  __asm__ volatile("" : : "g"(bytes) : "memory");
}

}  // namespace

int main() {
  static std::array<std::uint32_t, constants::kGpioSamplesPerFrame> source{};
  static std::array<std::uint8_t, constants::kGpioSamplesPerFrame> output{};
  for (std::size_t index = 0U; index < source.size(); ++index) {
    source[index] = rawWord(static_cast<std::uint8_t>(index & 0xFFU));
  }

  constexpr std::size_t warmups = 64U;
  constexpr std::size_t iterations = 4096U;
  std::uint64_t digest = 0U;
  for (std::size_t iteration = 0U; iteration < warmups; ++iteration) {
    if (packer::packGpio2Batch(source.data(), source.size(), output.data(),
                               output.size()) != output.size()) {
      return 2;
    }
    exposePackedBytes(output.data());
    digest += output[iteration % output.size()];
  }

  const auto started = std::chrono::steady_clock::now();
  for (std::size_t iteration = 0U; iteration < iterations; ++iteration) {
    source[iteration % source.size()] ^=
        std::uint32_t{1U} << teensy_daq::board::kGpioMappingsByPackedBit[0]
                                  .gpio2_bit;
    if (packer::packGpio2Batch(source.data(), source.size(), output.data(),
                               output.size()) != output.size()) {
      return 3;
    }
    exposePackedBytes(output.data());
    digest += output[(iteration * 17U) % output.size()];
  }
  const auto stopped = std::chrono::steady_clock::now();
  const double seconds =
      std::chrono::duration<double>(stopped - started).count();
  const std::uint64_t samples =
      static_cast<std::uint64_t>(iterations) * output.size();
  const double payload_megabytes_per_second =
      static_cast<double>(samples) / seconds / 1'000'000.0;

  std::cout << std::fixed << std::setprecision(3)
            << "algorithm=" << packer::kBatchAlgorithmName
            << " samples=" << samples << " seconds=" << seconds
            << " payload_mb_s=" << payload_megabytes_per_second
            << " target_payload_mb_s=4.000 digest=" << digest << '\n';
  return payload_megabytes_per_second >= 40.0 ? 0 : 4;
}
