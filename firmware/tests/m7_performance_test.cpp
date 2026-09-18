#include "gpio_pack_c.h"
#include "gpio_dual_bank_packer.h"
#include "event_word.h"

#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <limits>
#include <thread>

int main() {
  constexpr std::size_t count = 2024U;
  std::array<std::uint32_t, count> primary{}, auxiliary{};
  std::array<std::uint8_t, 2U * count + 2U> output{};
  std::uint32_t random = 0x12345678U;
  for (std::size_t i = 0; i < count; ++i) {
    random = random * 1664525U + 1013904223U;
    primary[i] = i < 32U ? (1U << i) : random;
    random = random * 1664525U + 1013904223U;
    auxiliary[i] = i < 32U ? (1U << i) : random;
  }
  for (std::size_t n : {0U, 1U, 2U, 3U, 4U, 31U, 32U, 33U, 2023U, 2024U}) {
    output.fill(0xA5U);
    assert(thingdaq_pack_dual_c(primary.data(), auxiliary.data(), n,
                               output.data() + 1U, 2U * n) == n);
    assert(output[0] == 0xA5U && output[2U * n + 1U] == 0xA5U);
    for (std::size_t i = 0; i < n; ++i) {
      const auto expected = thingdaq::gpio_aux_packer::packDualBankWord(primary[i], auxiliary[i]);
      assert(output[2U * i + 1U] == (expected & 0xffU));
      assert(output[2U * i + 2U] == (expected >> 8U));
    }
  }
  output.fill(0xA5U);
  assert(thingdaq_pack_dual_c(primary.data(), auxiliary.data(), count, output.data(), 2U * count - 1U) == 0U);
  for (auto byte : output) assert(byte == 0xA5U);
  assert(thingdaq_pack_dual_c(nullptr, auxiliary.data(), 1, output.data(), 2) == 0);
  assert(thingdaq_pack_dual_c(primary.data(), nullptr, 1, output.data(), 2) == 0);
  assert(thingdaq_pack_dual_c(primary.data(), auxiliary.data(), 1, nullptr, 2) == 0);
  assert(thingdaq_pack_dual_c(nullptr, nullptr, 0, nullptr, 0) == 0);
  assert(thingdaq_pack_dual_c(primary.data(), auxiliary.data(), std::numeric_limits<std::size_t>::max(), output.data(), std::numeric_limits<std::size_t>::max()) == 0);

  thingdaq_event_word events{};
  assert(thingdaq_event_take(&events) == 0U);
  thingdaq_event_publish(&events, 1U);
  thingdaq_event_publish(&events, 5U);
  assert(thingdaq_event_take(&events) == 5U);
  assert(thingdaq_event_take(&events) == 0U);
  // Release/acquire must publish ordinary payload writes. Acknowledgement
  // prevents the producer overwriting a payload while the reader owns it.
  std::uint32_t payload = 0U;
  std::atomic<std::uint32_t> acknowledged{0U};
  std::thread producer([&] {
    for (std::uint32_t i = 1; i <= 100000U; ++i) {
      while (acknowledged.load(std::memory_order_acquire) != i - 1U) {}
      payload = i;
      thingdaq_event_publish(&events, 1U);
    }
  });
  for (std::uint32_t i = 1; i <= 100000U; ++i) {
    while (thingdaq_event_take(&events) == 0U) {}
    assert(payload == i);
    acknowledged.store(i, std::memory_order_release);
  }
  producer.join();
  // Independent concurrent publishers cannot lose each other's bits.
  std::array<std::thread, 8> publishers;
  for (std::size_t i = 0; i < publishers.size(); ++i) {
    publishers[i] = std::thread([&, i] { thingdaq_event_publish(&events, 1U << i); });
  }
  for (auto &thread : publishers) thread.join();
  assert(thingdaq_event_take(&events) == 0xFFU);
}
