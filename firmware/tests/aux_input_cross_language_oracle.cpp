#include <cstdint>
#include <iostream>
#include <limits>

#include "gpio_dual_bank_packer.h"
#include "variable_rate_scheduler.h"

int main() {
  std::uint32_t raw_profile = 0U;
  std::uint32_t primary_word = 0U;
  std::uint32_t auxiliary_word = 0U;
  std::uint64_t gpio_first_ticks = 0U;
  std::uint32_t gpio_offset = 0U;
  std::uint64_t adc_first_ticks = 0U;
  std::uint32_t adc_offset = 0U;
  while (std::cin >> raw_profile >> primary_word >> auxiliary_word >>
         gpio_first_ticks >> gpio_offset >> adc_first_ticks >> adc_offset) {
    const auto profile =
        static_cast<thingdaq::protocol_v2::RateProfile>(raw_profile);
    const thingdaq::variable_rate::DeriveResult derived =
        thingdaq::variable_rate::derive(profile);
    if (!derived.ok()) {
      std::cerr << "unsupported profile\n";
      return 2;
    }
    const thingdaq::variable_rate::Schedule &schedule = derived.schedule;
    const std::uint64_t gpio_delta =
        static_cast<std::uint64_t>(gpio_offset) *
        schedule.gpio_sample_period_ticks;
    const std::uint64_t adc_delta =
        static_cast<std::uint64_t>(adc_offset) *
        schedule.adc_pair_period_ticks;
    if (gpio_delta > std::numeric_limits<std::uint64_t>::max() -
                         gpio_first_ticks ||
        adc_delta > std::numeric_limits<std::uint64_t>::max() -
                        adc_first_ticks ||
        schedule.adc1_phase_ticks >
            std::numeric_limits<std::uint64_t>::max() -
                (adc_first_ticks + adc_delta)) {
      std::cerr << "timestamp overflow\n";
      return 3;
    }
    const std::uint16_t packed =
        thingdaq::gpio_aux_packer::packDualBankWord(primary_word,
                                                     auxiliary_word);
    const std::uint64_t gpio_ticks = gpio_first_ticks + gpio_delta;
    const std::uint64_t adc0_ticks = adc_first_ticks + adc_delta;
    const std::uint64_t adc1_ticks =
        adc0_ticks + schedule.adc1_phase_ticks;
    std::cout << static_cast<std::uint32_t>(packed) << ' ' << gpio_ticks << ' '
              << adc0_ticks << ' ' << adc1_ticks << '\n';
  }
  if (!std::cin.eof()) {
    std::cerr << "malformed input\n";
    return 4;
  }
  return 0;
}
