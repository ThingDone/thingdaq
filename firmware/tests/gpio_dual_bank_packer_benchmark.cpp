#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>

#include "gpio_dual_bank_packer.h"

namespace {

namespace join = thingdaq::gpio_join;
namespace packer = thingdaq::gpio_aux_packer;
namespace protocol = thingdaq::protocol_v2;

constexpr std::uint32_t rawWord(
    std::uint8_t packed, const std::uint8_t (&port_bits)[8]) {
  std::uint32_t word = 0U;
  for (std::size_t bit = 0U; bit < 8U; ++bit) {
    if ((packed & (std::uint8_t{1U} << bit)) != 0U) {
      word |= std::uint32_t{1U} << port_bits[bit];
    }
  }
  return word;
}

void exposePackedBytes(const std::uint8_t *bytes) {
  // The benchmark is compiled with LTO. Make every completed destination
  // buffer observable so interprocedural dead-store elimination cannot turn
  // the measured full-batch pack into a single-word calculation.
  __asm__ volatile("" : : "g"(bytes) : "memory");
}

}  // namespace

int main() {
  static std::array<std::uint32_t, join::kSamplesPerBlock> primary{};
  static std::array<std::uint32_t, join::kSamplesPerBlock> auxiliary{};
  static std::array<std::uint8_t,
                    join::kSamplesPerBlock * packer::kPackedWireBytesPerSample>
      output{};

  for (std::size_t index = 0U; index < primary.size(); ++index) {
    const auto primary_byte = static_cast<std::uint8_t>(index & 0xFFU);
    const auto auxiliary_byte =
        static_cast<std::uint8_t>((3U * index + 0x55U) & 0xFFU);
    primary[index] =
        rawWord(primary_byte, protocol::kPrimaryGpioPortBitsByWireBit);
    auxiliary[index] =
        rawWord(auxiliary_byte, protocol::kAuxGpioPortBitsByWireBit);
  }

  constexpr std::size_t warmups = 64U;
  constexpr std::size_t iterations = 4096U;
  std::uint64_t digest = 0U;
  for (std::size_t iteration = 0U; iteration < warmups; ++iteration) {
    if (packer::packDualBankBatch(
            primary.data(), auxiliary.data(), primary.size(), output.data(),
            output.size()) != primary.size()) {
      return 2;
    }
    exposePackedBytes(output.data());
    digest += output[iteration % output.size()];
  }

  const auto started = std::chrono::steady_clock::now();
  for (std::size_t iteration = 0U; iteration < iterations; ++iteration) {
    primary[iteration % primary.size()] ^=
        std::uint32_t{1U} << protocol::kPrimaryGpioPortBitsByWireBit[0];
    auxiliary[(iteration * 3U) % auxiliary.size()] ^=
        std::uint32_t{1U} << protocol::kAuxGpioPortBitsByWireBit[7];
    if (packer::packDualBankBatch(
            primary.data(), auxiliary.data(), primary.size(), output.data(),
            output.size()) != primary.size()) {
      return 3;
    }
    exposePackedBytes(output.data());
    digest += output[(iteration * 17U) % output.size()];
  }
  const auto stopped = std::chrono::steady_clock::now();
  const double seconds =
      std::chrono::duration<double>(stopped - started).count();
  const std::uint64_t payload_bytes =
      static_cast<std::uint64_t>(iterations) * output.size();
  const double payload_megabytes_per_second =
      static_cast<double>(payload_bytes) / seconds / 1'000'000.0;

  constexpr double target_payload_megabytes_per_second = 8.0;
  constexpr double required_headroom = 10.0;
  std::cout << std::fixed << std::setprecision(3)
            << "algorithm=dual-bank-shift-mask"
            << " samples="
            << static_cast<std::uint64_t>(iterations) * primary.size()
            << " payload_bytes=" << payload_bytes << " seconds=" << seconds
            << " payload_mb_s=" << payload_megabytes_per_second
            << " target_gpio_payload_mb_s="
            << target_payload_megabytes_per_second
            << " full_combined_payload_hypothesis_mb_s=12.000"
            << " headroom_ratio="
            << payload_megabytes_per_second /
                   target_payload_megabytes_per_second
            << " required_headroom_ratio=" << required_headroom
            << " paired_raw_storage_bytes=" << sizeof(join::PairedRawStorage)
            << " overflow_sink_bytes=" << sizeof(join::PairedOverflowSink)
            << " joiner_state_bytes=" << sizeof(join::DualBankCaptureRing)
            << " packer_state_bytes=" << sizeof(packer::AuxiliaryBatchPacker)
            << " physical_usb_acceptance=false"
            << " target_runtime_acceptance=false"
            << " digest=" << digest << '\n';
  return payload_megabytes_per_second >=
                 target_payload_megabytes_per_second * required_headroom
             ? 0
             : 4;
}

static_assert(sizeof(thingdaq::gpio_join::PairedRawStorage) == 64768U);
static_assert(sizeof(thingdaq::gpio_join::PairedOverflowSink) == 64U);
