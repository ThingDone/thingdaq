// Experimental fixed-2024-item encoder. Caller supplies disjoint 4096-byte
// buffers. A zero length selects intact RAW input; partial scratch is discarded.
// No persistent state, allocation, checksum, frame copy, or USB work is timed.
#include "benchmark.h"
#include <cstring>
#ifndef RLE_SINGLE_NAME
#define RLE_SINGLE_NAME single_pass
#endif
#ifndef RLE_SINGLE_ATTRIBUTES
#define RLE_SINGLE_ATTRIBUTES
#endif

extern "C" RLE_SINGLE_ATTRIBUTES rle_bench::Result RLE_SINGLE_NAME(
    const std::uint8_t *input, std::uint8_t *output) {
  std::uint16_t previous;
  std::memcpy(&previous, input, sizeof(previous));
#if defined(RLE_SPAN_SCAN)
  std::size_t start = 0;
  std::size_t used = 0;
  for (std::size_t item = 1; item < rle_bench::kItems; ++item) {
    std::uint16_t current;
    std::memcpy(&current, input + 2 * item, sizeof(current));
    if (current == previous) continue;
    if (used + 4 > rle_bench::kOutputLimit) return {0, 0};
    const auto count = static_cast<std::uint16_t>(item - start);
    output[used] = static_cast<std::uint8_t>(count);
    output[used + 1] = static_cast<std::uint8_t>(count >> 8);
    output[used + 2] = static_cast<std::uint8_t>(previous);
    output[used + 3] = static_cast<std::uint8_t>(previous >> 8);
    used += 4;
    start = item;
    previous = current;
  }
  if (used + 4 > rle_bench::kOutputLimit) return {0, 0};
  const auto count = static_cast<std::uint16_t>(rle_bench::kItems - start);
  output[used] = static_cast<std::uint8_t>(count);
  output[used + 1] = static_cast<std::uint8_t>(count >> 8);
  output[used + 2] = static_cast<std::uint8_t>(previous);
  output[used + 3] = static_cast<std::uint8_t>(previous >> 8);
  return {static_cast<std::uint32_t>(used + 4), 0};
#else
  std::uint16_t count = 1;
  std::size_t used = 0;
  for (std::size_t item = 1; item <= rle_bench::kItems; ++item) {
    std::uint16_t current = 0;
    if (item < rle_bench::kItems) {
      std::memcpy(&current, input + 2 * item, sizeof(current));
      if (current == previous) { ++count; continue; }
    }
    if (used + 4 > rle_bench::kOutputLimit) return {0, 0};
    output[used] = static_cast<std::uint8_t>(count);
    output[used + 1] = static_cast<std::uint8_t>(count >> 8);
    output[used + 2] = static_cast<std::uint8_t>(previous);
    output[used + 3] = static_cast<std::uint8_t>(previous >> 8);
    used += 4;
    previous = current;
    count = 1;
  }
  return {static_cast<std::uint32_t>(used), 0};
#endif
}
