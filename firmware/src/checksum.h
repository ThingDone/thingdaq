#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace teensy_daq::checksum {

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(section_name) \
  __attribute__((section(section_name), used))
#else
#define TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(section_name)
#endif

// Candidate identities are intentionally independent of protocol wire IDs.
// Protocol negotiation maps enabled wire algorithms to this narrow interface.
enum class Algorithm : std::uint8_t {
  kAdler32,
  kCrc32c,
  kCrc32IsoHdlc,
};

inline constexpr std::uint32_t kAdler32Initial = 1U;
inline constexpr std::uint32_t kAdler32Modulus = 65521U;
inline constexpr std::uint32_t kCrc32Initial = 0xFFFFFFFFU;
inline constexpr std::uint32_t kCrc32FinalXor = 0xFFFFFFFFU;
inline constexpr std::uint32_t kCrc32cPolynomial = 0x1EDC6F41U;
inline constexpr std::uint32_t kCrc32cReflectedPolynomial = 0x82F63B78U;
inline constexpr std::uint32_t kCrc32IsoHdlcPolynomial = 0x04C11DB7U;
inline constexpr std::uint32_t kCrc32IsoHdlcReflectedPolynomial =
    0xEDB88320U;
inline constexpr std::size_t kCrcTableEntries = 256U;
inline constexpr std::size_t kCrcTableBytes =
    kCrcTableEntries * sizeof(std::uint32_t);

namespace detail {

constexpr std::array<std::uint32_t, kCrcTableEntries> makeReflectedCrcTable(
    std::uint32_t polynomial) {
  std::array<std::uint32_t, kCrcTableEntries> table{};
  for (std::size_t index = 0U; index < table.size(); ++index) {
    std::uint32_t remainder = static_cast<std::uint32_t>(index);
    for (std::uint8_t bit = 0U; bit < 8U; ++bit) {
      const std::uint32_t low_bit_mask = 0U - (remainder & 1U);
      remainder = (remainder >> 1U) ^ (polynomial & low_bit_mask);
    }
    table[index] = remainder;
  }
  return table;
}

inline constexpr auto kCrc32cTable
    TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(".progmem.checksum.crc32c") =
    makeReflectedCrcTable(kCrc32cReflectedPolynomial);
inline constexpr auto kCrc32IsoHdlcTable
    TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(".progmem.checksum.crc32_iso_hdlc") =
    makeReflectedCrcTable(kCrc32IsoHdlcReflectedPolynomial);

inline std::uint32_t reflectedCrc32(
    const std::uint8_t *data, std::size_t size,
    const std::array<std::uint32_t, kCrcTableEntries> &table) {
  std::uint32_t remainder = kCrc32Initial;
  for (std::size_t offset = 0U; offset < size; ++offset) {
    const std::uint8_t table_index = static_cast<std::uint8_t>(
        (remainder ^ static_cast<std::uint32_t>(data[offset])) & 0xFFU);
    remainder = (remainder >> 8U) ^ table[table_index];
  }
  return remainder ^ kCrc32FinalXor;
}

}  // namespace detail

// Callers must pass a non-null pointer for nonempty input. A null pointer is
// valid for the canonical empty input.
inline std::uint32_t adler32(const std::uint8_t *data, std::size_t size) {
  // RFC 1950/zlib's NMAX bound keeps both sums inside uint32_t while moving
  // division out of the per-byte high-rate framing loop.
  constexpr std::size_t reduction_block_bytes = 5552U;
  std::uint32_t first = kAdler32Initial;
  std::uint32_t second = 0U;
  std::size_t offset = 0U;
  while (offset < size) {
    const std::size_t remaining = size - offset;
    const std::size_t block = remaining < reduction_block_bytes
                                  ? remaining
                                  : reduction_block_bytes;
    const std::size_t end = offset + block;
    while (offset < end) {
      first += data[offset];
      second += first;
      ++offset;
    }
    first %= kAdler32Modulus;
    second %= kAdler32Modulus;
  }
  return (second << 16U) | first;
}

inline std::uint32_t crc32c(const std::uint8_t *data, std::size_t size) {
  return detail::reflectedCrc32(data, size, detail::kCrc32cTable);
}

inline std::uint32_t crc32IsoHdlc(const std::uint8_t *data,
                                  std::size_t size) {
  return detail::reflectedCrc32(data, size, detail::kCrc32IsoHdlcTable);
}

inline constexpr std::size_t tableBytes(Algorithm algorithm) {
  switch (algorithm) {
    case Algorithm::kAdler32:
      return 0U;
    case Algorithm::kCrc32c:
    case Algorithm::kCrc32IsoHdlc:
      return kCrcTableBytes;
  }
  return 0U;
}

inline bool compute(Algorithm algorithm, const std::uint8_t *data,
                    std::size_t size, std::uint32_t &result) {
  if (data == nullptr && size != 0U) {
    return false;
  }
  switch (algorithm) {
    case Algorithm::kAdler32:
      result = adler32(data, size);
      return true;
    case Algorithm::kCrc32c:
      result = crc32c(data, size);
      return true;
    case Algorithm::kCrc32IsoHdlc:
      result = crc32IsoHdlc(data, size);
      return true;
  }
  return false;
}

}  // namespace teensy_daq::checksum

#undef TEENSY_DAQ_CHECKSUM_TABLE_STORAGE
