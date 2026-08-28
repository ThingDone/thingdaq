#include "checksum.h"

#include <array>

namespace teensy_daq::checksum {
namespace detail {

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(section_name) \
  __attribute__((section(section_name), used))
#define TEENSY_DAQ_CHECKSUM_CODE_STORAGE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(section_name)
#define TEENSY_DAQ_CHECKSUM_CODE_STORAGE(section_name) \
  __attribute__((noinline))
#endif

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

extern const std::array<std::uint32_t, kCrcTableEntries> kCrc32cTable
    TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(".progmem.checksum.crc32c") =
        makeReflectedCrcTable(kCrc32cReflectedPolynomial);
extern const std::array<std::uint32_t, kCrcTableEntries> kCrc32IsoHdlcTable
    TEENSY_DAQ_CHECKSUM_TABLE_STORAGE(".progmem.checksum.crc32_iso_hdlc") =
        makeReflectedCrcTable(kCrc32IsoHdlcReflectedPolynomial);

template <const std::array<std::uint32_t, kCrcTableEntries> &Table>
std::uint32_t reflectedCrc32(const std::uint8_t *data, std::size_t size) {
  std::uint32_t remainder = kCrc32Initial;
  for (std::size_t offset = 0U; offset < size; ++offset) {
    const std::uint8_t table_index = static_cast<std::uint8_t>(
        (remainder ^ static_cast<std::uint32_t>(data[offset])) & 0xFFU);
    remainder = (remainder >> 8U) ^ Table[table_index];
  }
  return remainder ^ kCrc32FinalXor;
}

}  // namespace detail

TEENSY_DAQ_CHECKSUM_CODE_STORAGE(".text.checksum.adler32")
std::uint32_t adler32(const std::uint8_t *data, std::size_t size) {
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

TEENSY_DAQ_CHECKSUM_CODE_STORAGE(".text.checksum.crc32c")
std::uint32_t crc32c(const std::uint8_t *data, std::size_t size) {
  return detail::reflectedCrc32<detail::kCrc32cTable>(data, size);
}

TEENSY_DAQ_CHECKSUM_CODE_STORAGE(".text.checksum.crc32_iso_hdlc")
std::uint32_t crc32IsoHdlc(const std::uint8_t *data, std::size_t size) {
  return detail::reflectedCrc32<detail::kCrc32IsoHdlcTable>(data, size);
}

TEENSY_DAQ_CHECKSUM_CODE_STORAGE(".text.checksum.dispatch")
bool compute(Algorithm algorithm, const std::uint8_t *data, std::size_t size,
             std::uint32_t &result) {
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

#undef TEENSY_DAQ_CHECKSUM_CODE_STORAGE
#undef TEENSY_DAQ_CHECKSUM_TABLE_STORAGE
