#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>

#include "adc_sample_packing.h"

namespace {

namespace capture = thingdaq::adc_capture;
namespace packing = thingdaq::adc_packing;
using Function = bool (*)(std::uint8_t *, std::size_t,
                          const capture::SamplePair *, std::size_t);
volatile std::uint32_t published_digest = 0U;

template <std::size_t OutputBytes>
void run(const char *name, Function function,
         const std::array<capture::SamplePair, 1012U> &pairs) {
  constexpr std::size_t warmups = 2048U;
  constexpr std::size_t iterations = 200000U;
  std::array<std::uint8_t, OutputBytes> output{};
  std::uint32_t digest = 0U;
  for (std::size_t index = 0U; index < warmups; ++index) {
    if (!function(output.data(), output.size(), pairs.data(), pairs.size())) return;
    digest += output[index % output.size()];
  }
  const auto begin = std::chrono::steady_clock::now();
  for (std::size_t index = 0U; index < iterations; ++index) {
    if (!function(output.data(), output.size(), pairs.data(), pairs.size())) return;
    digest = digest * 33U + output[index % output.size()];
  }
  const auto end = std::chrono::steady_clock::now();
  published_digest = digest;
  const double seconds = std::chrono::duration<double>(end - begin).count();
  const double ns_per_frame = seconds * 1.0e9 / static_cast<double>(iterations);
  const double pairs_per_second =
      static_cast<double>(iterations * pairs.size()) / seconds;
  std::cout << name << ' ' << std::fixed << std::setprecision(3)
            << ns_per_frame << ' ' << pairs_per_second << ' ' << digest << '\n';
}

}  // namespace

int main() {
  std::array<capture::SamplePair, 1012U> pairs{};
  for (std::size_t index = 0U; index < pairs.size(); ++index) {
    pairs[index].adc0 = static_cast<std::uint16_t>((index * 17U + 3U) & 0xFFFU);
    pairs[index].adc1 = static_cast<std::uint16_t>((index * 29U + 7U) & 0xFFFU);
  }
  run<4048U>("container16", packing::copy16BitContainers, pairs);
  run<3036U>("packed12", packing::pack12BitPairs, pairs);
  run<2530U>("packed10", packing::pack10BitPairs, pairs);
  return published_digest == 0xFFFFFFFFU ? 1 : 0;
}
