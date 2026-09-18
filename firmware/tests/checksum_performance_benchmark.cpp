// Native-host timing of the exact firmware dispatch; not Cortex-M7 evidence.
#include <array>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include "protocol.h"

int main() {
  std::array<std::uint8_t, 4092> data{};
  for (std::size_t i = 0; i < data.size(); ++i) {
    data[i] = static_cast<std::uint8_t>((i * 37U + 11U) & 255U);
  }
  data[5] = 2;  // data-frame kind, as used by the experimental dispatch
  constexpr std::size_t iterations = 20000;
  for (std::size_t size : {2068U, 4092U}) {
    std::uint64_t digest = 0;
    std::uint32_t result = 0;
    for (std::size_t i = 0; i < 64; ++i) {
      if (!thingdaq::protocol::computeChecksum(
          thingdaq::protocol_v1::ChecksumAlgorithm::kAdler32,
          {data.data(), size}, result).ok()) return 1;
      asm volatile("" : : "g"(result) : "memory");
    }
    const auto start = std::chrono::steady_clock::now();
    for (std::size_t i = 0; i < iterations; ++i) {
      // Change an input byte and expose the result to prevent loop hoisting,
      // even if a future compiler enables cross-module optimization.
      data[44] = static_cast<std::uint8_t>(i & 255U);
      if (!thingdaq::protocol::computeChecksum(
          thingdaq::protocol_v1::ChecksumAlgorithm::kAdler32,
          {data.data(), size}, result).ok()) return 1;
      asm volatile("" : : "g"(result) : "memory");
      digest += result;
    }
    const double seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start).count();
    std::cout << std::setprecision(12)
              << "{\"coverage_bytes\":" << size
              << ",\"iterations\":" << iterations
              << ",\"seconds\":" << seconds
              << ",\"digest\":" << digest << "}\n";
  }
}
