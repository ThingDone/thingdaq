#pragma once
#include <cstddef>
#include <cstdint>

namespace rle_bench {
constexpr std::size_t kItems = 2024;
constexpr std::size_t kInputBytes = kItems * 2;
// A selected frame must be strictly smaller than the 4096-byte RAW frame.
constexpr std::size_t kOutputLimit = 4044;
constexpr std::size_t kBufferBytes = 4096;
struct Result {
  std::uint32_t bytes;
  std::uint32_t error;
};
using Kernel = Result (*)(const std::uint8_t *, std::uint8_t *);
struct Variant { const char *name; Kernel function; };
}  // namespace rle_bench
