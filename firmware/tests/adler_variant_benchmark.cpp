#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>

#include "checksum.h"

namespace {

using Function = std::uint32_t (*)(const std::uint8_t *, std::size_t);
volatile std::uint32_t published_digest = 0U;

void run(const char *name, Function function,
         std::array<std::uint8_t, 4092U> &input) {
  constexpr std::size_t warmups = 2048U;
  constexpr std::size_t iterations = 200000U;
  std::uint32_t digest = 0U;
  for (std::size_t index = 0U; index < warmups; ++index) {
    digest ^= function(input.data(), input.size());
  }
  const auto begin = std::chrono::steady_clock::now();
  for (std::size_t index = 0U; index < iterations; ++index) {
    digest = digest * 33U + function(input.data(), input.size());
  }
  const auto end = std::chrono::steady_clock::now();
  published_digest = digest;
  const double seconds = std::chrono::duration<double>(end - begin).count();
  const double ns_per_call = seconds * 1.0e9 / static_cast<double>(iterations);
  const double mb_per_second =
      static_cast<double>(iterations * input.size()) / seconds / 1.0e6;
  std::cout << name << ' ' << std::fixed << std::setprecision(3)
            << ns_per_call << ' ' << mb_per_second << ' ' << digest << '\n';
}

}  // namespace

int main() {
  std::array<std::uint8_t, 4092U> input{};
  for (std::size_t index = 0U; index < input.size(); ++index) {
    input[index] = static_cast<std::uint8_t>((index * 37U + 11U) & 0xFFU);
  }
  run("standard", thingdaq::checksum::adler32, input);
  run("unrolled", thingdaq::checksum::adler32Unrolled, input);
  run("dual_lane", thingdaq::checksum::adler32DualLane, input);
  return published_digest == 0xFFFFFFFFU ? 1 : 0;
}
