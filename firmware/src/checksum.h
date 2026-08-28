#pragma once

#include <cstddef>
#include <cstdint>

namespace teensy_daq::checksum {

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
inline constexpr std::size_t kCrcTableSlices = 8U;
inline constexpr std::size_t kCrcTableEntries = 256U;
inline constexpr std::size_t kCrcTableBytes =
    kCrcTableSlices * kCrcTableEntries * sizeof(std::uint32_t);

// These values are pinned-build symbol sizes validated by build_firmware.py.
// They deliberately exclude the shared narrow dispatch body and the separately
// reported lookup table so a benchmark result never conflates code and data.
inline constexpr std::size_t kAdler32CodeBytes = 120U;
inline constexpr std::size_t kCrc32cCodeBytes = 308U;
inline constexpr std::size_t kCrc32IsoHdlcCodeBytes = 308U;

// Callers must pass a non-null pointer for nonempty input. A null pointer is
// valid for the canonical empty input.
std::uint32_t adler32(const std::uint8_t *data, std::size_t size);
std::uint32_t crc32c(const std::uint8_t *data, std::size_t size);
std::uint32_t crc32IsoHdlc(const std::uint8_t *data, std::size_t size);

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

inline constexpr std::size_t implementationCodeBytes(Algorithm algorithm) {
  switch (algorithm) {
    case Algorithm::kAdler32:
      return kAdler32CodeBytes;
    case Algorithm::kCrc32c:
      return kCrc32cCodeBytes;
    case Algorithm::kCrc32IsoHdlc:
      return kCrc32IsoHdlcCodeBytes;
  }
  return 0U;
}

bool compute(Algorithm algorithm, const std::uint8_t *data, std::size_t size,
             std::uint32_t &result);

}  // namespace teensy_daq::checksum
